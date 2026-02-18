"""Internal async DB helpers for orchestration tasks.

This module contains the async coroutines used by the synchronous Celery
tasks in ``workers/tasks.py``.  They are separated to keep each file under
400 lines and to make the individual helpers unit-testable without importing
the Celery application.

All functions open their own ``AsyncSessionLocal`` context managers and
commit or close the session before returning.  This is intentional: Celery
workers call these via ``asyncio.run()`` from synchronous task bodies, so
each invocation requires a fresh event loop with no pre-existing session.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update

from issue_observatory.core.credit_service import CreditService
from issue_observatory.core.database import AsyncSessionLocal
from issue_observatory.core.models.collection import (
    CollectionRun,
    CollectionTask,
    CreditTransaction,
)
from issue_observatory.core.models.query_design import QueryDesign
from issue_observatory.core.models.users import User
from issue_observatory.core.retention_service import RetentionService

_retention_service = RetentionService()


# ---------------------------------------------------------------------------
# trigger_daily_collection helpers
# ---------------------------------------------------------------------------


async def fetch_live_tracking_designs() -> list[dict[str, Any]]:
    """Query all active live-tracking query designs and their run state.

    A query design qualifies for daily dispatch if:
    - ``QueryDesign.is_active`` is True
    - There exists at least one ``CollectionRun`` for that design with
      ``mode='live'`` and ``status='active'``

    Returns:
        List of dicts with keys: ``query_design_id``, ``owner_id``,
        ``arenas_config``, ``default_tier``, ``language``,
        ``run_id``, ``run_status``.
        The ``language`` field holds the raw comma-separated language string
        from ``QueryDesign.language`` (e.g. ``"da"`` or ``"da,en"``).
        Use :func:`~issue_observatory.core.schemas.query_design.parse_language_codes`
        to convert it to a list.
    """
    async with AsyncSessionLocal() as db:
        stmt = (
            select(
                QueryDesign.id.label("query_design_id"),
                QueryDesign.owner_id,
                QueryDesign.arenas_config,
                QueryDesign.default_tier,
                QueryDesign.language,
                CollectionRun.id.label("run_id"),
                CollectionRun.status.label("run_status"),
            )
            .join(
                CollectionRun,
                (CollectionRun.query_design_id == QueryDesign.id)
                & (CollectionRun.mode == "live")
                & (CollectionRun.status == "active"),
            )
            .where(QueryDesign.is_active.is_(True))
        )
        result = await db.execute(stmt)
        rows = result.mappings().all()
        return [dict(row) for row in rows]


async def get_user_email(user_id: Any) -> str | None:
    """Return the email address for a user ID, or None if not found.

    Args:
        user_id: UUID of the user row to look up.

    Returns:
        Email string or None.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User.email).where(User.id == user_id))
        return result.scalar_one_or_none()


async def get_user_credit_balance(user_id: Any) -> int:
    """Return the available credit balance for a user.

    Args:
        user_id: UUID of the user whose balance to check.

    Returns:
        Available credit count as a non-negative integer.
    """
    async with AsyncSessionLocal() as db:
        svc = CreditService(session=db)
        return await svc.get_available_credits(user_id)


async def suspend_run(run_id: Any) -> None:
    """Update a CollectionRun's status to 'suspended'.

    Args:
        run_id: UUID of the CollectionRun to suspend.
    """
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CollectionRun)
            .where(CollectionRun.id == run_id)
            .values(status="suspended")
        )
        await db.commit()


# ---------------------------------------------------------------------------
# settle_pending_credits helpers
# ---------------------------------------------------------------------------


async def fetch_unsettled_reservations() -> list[dict[str, Any]]:
    """Find reservation transactions whose run has completed without a settlement.

    A reservation is pending settlement when:
    - ``CreditTransaction.transaction_type = 'reservation'``
    - The associated ``CollectionRun.completed_at`` is not NULL
    - No ``CreditTransaction`` with ``transaction_type='settlement'`` exists
      for the same (user_id, collection_run_id, arena, platform) combination.

    Returns:
        List of dicts with reservation fields plus ``run_completed_at``,
        ``records_collected``, and ``user_email``.
    """
    async with AsyncSessionLocal() as db:
        settled_subq = (
            select(
                CreditTransaction.collection_run_id,
                CreditTransaction.arena,
                CreditTransaction.platform,
            )
            .where(CreditTransaction.transaction_type == "settlement")
            .subquery()
        )

        stmt = (
            select(
                CreditTransaction.id.label("txn_id"),
                CreditTransaction.user_id,
                CreditTransaction.collection_run_id,
                CreditTransaction.arena,
                CreditTransaction.platform,
                CreditTransaction.tier,
                CreditTransaction.credits_consumed.label("reserved_credits"),
                CollectionRun.completed_at,
                CollectionRun.records_collected,
                User.email.label("user_email"),
            )
            .join(
                CollectionRun,
                CollectionRun.id == CreditTransaction.collection_run_id,
            )
            .join(User, User.id == CreditTransaction.user_id)
            .where(CreditTransaction.transaction_type == "reservation")
            .where(CollectionRun.completed_at.is_not(None))
            .where(
                ~(
                    select(settled_subq.c.collection_run_id)
                    .where(
                        settled_subq.c.collection_run_id
                        == CreditTransaction.collection_run_id
                    )
                    .where(settled_subq.c.arena == CreditTransaction.arena)
                    .where(settled_subq.c.platform == CreditTransaction.platform)
                    .exists()
                )
            )
        )

        result = await db.execute(stmt)
        rows = result.mappings().all()
        return [dict(row) for row in rows]


async def settle_single_reservation(row: dict[str, Any]) -> None:
    """Write a settlement transaction for one pending reservation row.

    Uses the reserved credit amount as the actual amount (conservative fallback
    when no granular arena-reported usage is available).

    Args:
        row: Dict as returned by :func:`fetch_unsettled_reservations`.
    """
    async with AsyncSessionLocal() as db:
        svc = CreditService(session=db)
        await svc.settle(
            user_id=row["user_id"],
            collection_run_id=row["collection_run_id"],
            arena=row["arena"],
            platform=row["platform"],
            tier=row["tier"],
            actual_credits=row["reserved_credits"],
            description="Settled by settle_pending_credits periodic task",
        )


# ---------------------------------------------------------------------------
# cleanup_stale_runs helpers
# ---------------------------------------------------------------------------


async def fetch_stale_runs() -> list[dict[str, Any]]:
    """Return CollectionRun rows stuck in non-terminal states for > 24 hours.

    Targets:
    - Runs with ``status='running'`` where ``started_at < now() - 24h``
    - Runs with ``status='pending'`` where ``started_at < now() - 24h``
      or ``started_at IS NULL``

    Returns:
        List of dicts with ``id``, ``status``, and ``started_at``.
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    async with AsyncSessionLocal() as db:
        stmt = (
            select(CollectionRun.id, CollectionRun.status, CollectionRun.started_at)
            .where(CollectionRun.status.in_(["pending", "running"]))
            .where(
                (
                    (CollectionRun.status == "running")
                    & (CollectionRun.started_at < cutoff)
                )
                | (
                    (CollectionRun.status == "pending")
                    & (
                        (CollectionRun.started_at < cutoff)
                        | CollectionRun.started_at.is_(None)
                    )
                )
            )
        )
        result = await db.execute(stmt)
        rows = result.mappings().all()
        return [dict(row) for row in rows]


async def mark_runs_failed(run_ids: list[Any]) -> int:
    """Bulk-update CollectionRun and CollectionTask rows to status='failed'.

    Also marks any non-terminal ``CollectionTask`` rows for those runs as
    failed with an explanatory error message.

    Args:
        run_ids: List of CollectionRun UUIDs to mark as failed.

    Returns:
        Number of CollectionRun rows updated.
    """
    if not run_ids:
        return 0

    stale_msg = (
        "Marked as failed by stale_run_cleanup: exceeded 24h without completion"
    )
    async with AsyncSessionLocal() as db:
        run_result = await db.execute(
            update(CollectionRun)
            .where(CollectionRun.id.in_(run_ids))
            .values(status="failed", error_log=stale_msg)
        )
        await db.execute(
            update(CollectionTask)
            .where(CollectionTask.collection_run_id.in_(run_ids))
            .where(
                CollectionTask.status.not_in(["completed", "failed", "cancelled"])
            )
            .values(status="failed", error_message=stale_msg)
        )
        await db.commit()

    return run_result.rowcount or 0


# ---------------------------------------------------------------------------
# enforce_retention_policy helper
# ---------------------------------------------------------------------------


async def enforce_retention(retention_days: int) -> int:
    """Call RetentionService.enforce_retention with the configured window.

    Args:
        retention_days: Number of days beyond which records are deleted.

    Returns:
        Number of content records deleted.
    """
    async with AsyncSessionLocal() as db:
        return await _retention_service.enforce_retention(
            db, retention_days=retention_days
        )
