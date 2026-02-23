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
from issue_observatory.core.models.actors import Actor, ActorListMember, ActorPlatformPresence
from issue_observatory.core.models.collection import (
    CollectionRun,
    CollectionTask,
    CreditTransaction,
)
from issue_observatory.core.models.content import UniversalContentRecord
from issue_observatory.core.models.query_design import ActorList, QueryDesign
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
                CollectionRun.query_design_id,
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
        # Only mark runs as stale when started_at is set AND older than 24h.
        # Pending runs with started_at=NULL are newly created and waiting for
        # the Celery worker to pick them up — they are NOT stale.
        stmt = (
            select(CollectionRun.id, CollectionRun.status, CollectionRun.started_at)
            .where(CollectionRun.status.in_(["pending", "running"]))
            .where(CollectionRun.started_at.is_not(None))
            .where(CollectionRun.started_at < cutoff)
        )
        result = await db.execute(stmt)
        rows = result.mappings().all()
        return [dict(row) for row in rows]


async def mark_runs_failed(run_ids: list[Any]) -> int:
    """Bulk-update CollectionRun and CollectionTask rows to status='failed'.

    Also marks any non-terminal ``CollectionTask`` rows for those runs as
    failed with an explanatory error message.

    M-05: Publishes a run_complete event to the Redis event bus for each
    run so that SSE streams can close properly.

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
        # Fetch run details before updating so we can publish accurate counts
        run_data_stmt = select(
            CollectionRun.id,
            CollectionRun.records_collected,
            CollectionRun.credits_spent,
        ).where(CollectionRun.id.in_(run_ids))
        run_data_result = await db.execute(run_data_stmt)
        run_data_rows = run_data_result.all()

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

    # M-05: Publish run_complete events for SSE subscribers
    from issue_observatory.config.settings import get_settings
    from issue_observatory.core.event_bus import publish_run_complete

    settings = get_settings()
    for row in run_data_rows:
        publish_run_complete(
            redis_url=settings.redis_url,
            run_id=str(row.id),
            status="failed",
            records_collected=row.records_collected or 0,
            credits_spent=row.credits_spent or 0,
        )

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


# ---------------------------------------------------------------------------
# GR-14 public-figure helpers
# ---------------------------------------------------------------------------


async def fetch_public_figure_ids_for_design(query_design_id: Any) -> set[str]:
    """Return the set of platform user IDs for all public-figure actors in a query design.

    Queries the actor-list members associated with *query_design_id* and
    returns the ``platform_user_id`` values from their
    ``ActorPlatformPresence`` rows where the linked ``Actor.public_figure``
    flag is ``True``.

    This set is consumed by :func:`~workers.tasks.trigger_daily_collection`
    before dispatching arena tasks.  It is passed to each arena task as
    ``public_figure_ids`` and ultimately forwarded to
    :meth:`~core.normalizer.Normalizer.normalize` so that records authored
    by known public figures bypass SHA-256 pseudonymization (GR-14 —
    GDPR Art. 89(1) research exemption).

    Only non-NULL ``platform_user_id`` values are included.  Presences
    that have only a ``platform_username`` but no ``platform_user_id`` are
    intentionally excluded because the normalizer matches on
    ``author_platform_id`` (the native numeric or string user ID returned by
    the upstream API), not on the display handle.

    Args:
        query_design_id: UUID of the ``QueryDesign`` whose actor lists to
            inspect.

    Returns:
        Set of ``platform_user_id`` strings.  Empty set when no public-figure
        actors are configured for the design, or when the design has no actor
        lists at all.
    """
    async with AsyncSessionLocal() as db:
        stmt = (
            select(ActorPlatformPresence.platform_user_id)
            .join(Actor, Actor.id == ActorPlatformPresence.actor_id)
            .join(ActorListMember, ActorListMember.actor_id == Actor.id)
            .join(ActorList, ActorList.id == ActorListMember.actor_list_id)
            .where(ActorList.query_design_id == query_design_id)
            .where(Actor.public_figure.is_(True))
            .where(ActorPlatformPresence.platform_user_id.is_not(None))
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return {str(uid) for uid in rows}


# ---------------------------------------------------------------------------
# YF-01: Per-arena search term scoping
# ---------------------------------------------------------------------------


async def fetch_search_terms_for_arena(
    query_design_id: Any,
    arena_platform_name: str,
) -> list[str]:
    """Return the list of active search term strings scoped to a specific arena.

    Queries the ``search_terms`` table for all active terms associated with
    *query_design_id*, filtering to include only terms where:

    - ``is_active`` is ``True``
    - ``target_arenas`` is ``NULL`` (applies to all arenas), OR
    - ``target_arenas`` contains *arena_platform_name* in its JSONB array

    This implements YF-01 per-arena search term scoping, allowing researchers
    to target specific terms to specific platforms (e.g., hashtags to Twitter
    only, subreddit names to Reddit only).

    Args:
        query_design_id: UUID of the ``QueryDesign`` whose search terms to load.
        arena_platform_name: Platform identifier string (e.g., ``"reddit"``,
            ``"bluesky"``, ``"google"``).  Must match the ``platform_name``
            attribute of the registered arena collector.

    Returns:
        List of search term strings.  Empty list when no active terms are
        scoped to the given arena, or when the design has no active terms at all.
    """
    from issue_observatory.core.models.query_design import SearchTerm  # noqa: PLC0415

    async with AsyncSessionLocal() as db:
        # YF-01 filtering logic:
        # Include terms where target_arenas is NULL (all arenas)
        # OR where the JSONB array contains the arena platform_name.
        # PostgreSQL's JSONB ? operator checks for string existence in array/object.
        from sqlalchemy import func, or_  # noqa: PLC0415

        stmt = (
            select(SearchTerm.term)
            .where(SearchTerm.query_design_id == query_design_id)
            .where(SearchTerm.is_active.is_(True))
            .where(
                or_(
                    # SQL NULL (from server_default or direct SQL insert):
                    SearchTerm.target_arenas.is_(None),
                    # JSON null (from asyncpg mapping Python None to JSONB null):
                    func.jsonb_typeof(SearchTerm.target_arenas) == "null",
                    # JSONB ? operator: does the array contain this string?
                    SearchTerm.target_arenas.has_key(arena_platform_name),  # type: ignore[attr-defined]
                )
            )
            .order_by(SearchTerm.added_at)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return [str(term) for term in rows]


# ---------------------------------------------------------------------------
# SB-03: Post-Collection Discovery Summary (enrichment completion)
# ---------------------------------------------------------------------------


async def get_discovery_summary(run_id: str) -> dict[str, int]:
    """Compute discovery statistics for a completed collection run.

    Queries the database to count:
    - Emergent terms discovered via TF-IDF analysis (not in original query)
    - Discovered sources/links extracted from collected content

    Used by SB-03 to emit a post-collection summary notification.

    Implementation notes:
    - Emergent terms are computed on-demand via TF-IDF (no persistent table).
    - Discovered links are computed on-demand via LinkMiner (no persistent table).
    - This function runs lightweight versions of both analyses to generate counts.

    Args:
        run_id: UUID string of the CollectionRun to analyze.

    Returns:
        Dict with keys:
        - ``suggested_terms``: Count of emergent terms not in original query
        - ``discovered_links``: Total discovered link count (min 2 mentions)
        - ``telegram_links``: Count of Telegram-specific discovered links
    """
    from uuid import UUID  # noqa: PLC0415

    from issue_observatory.analysis.descriptive import get_emergent_terms  # noqa: PLC0415
    from issue_observatory.analysis.link_miner import LinkMiner  # noqa: PLC0415

    run_uuid = UUID(run_id)

    async with AsyncSessionLocal() as db:
        # ------------------------------------------------------------------
        # 1. Count emergent terms (TF-IDF terms not in original search terms)
        # ------------------------------------------------------------------
        try:
            # Call get_emergent_terms with modest parameters to get a quick count.
            # This requires scikit-learn; if not installed, returns empty list.
            emergent_terms = await get_emergent_terms(
                db=db,
                run_id=run_uuid,
                top_n=50,
                exclude_search_terms=True,
                min_doc_frequency=2,
            )
            suggested_terms_count = len(emergent_terms)
        except Exception:  # noqa: BLE001
            # If scikit-learn is not installed or TF-IDF fails, return zero.
            suggested_terms_count = 0

        # ------------------------------------------------------------------
        # 2. Count discovered links using LinkMiner
        # ------------------------------------------------------------------
        try:
            # Fetch the collection run to get query_design_id.
            run_result = await db.execute(
                select(CollectionRun.query_design_id).where(CollectionRun.id == run_uuid)
            )
            qd_id = run_result.scalar_one_or_none()

            if qd_id is None:
                # No query design associated — return zero counts.
                discovered_links_count = 0
                telegram_links_count = 0
            else:
                miner = LinkMiner()
                # Mine all platforms with min_source_count=2 (at least 2 mentions).
                all_links = await miner.mine(
                    db=db,
                    query_design_id=qd_id,
                    min_source_count=2,
                    limit=1000,  # generous limit for summary
                )
                discovered_links_count = len(all_links)

                # Count Telegram-specific links.
                telegram_links_count = sum(
                    1 for link in all_links if link.platform == "telegram"
                )
        except Exception:  # noqa: BLE001
            # If link mining fails, return zero counts.
            discovered_links_count = 0
            telegram_links_count = 0

    return {
        "suggested_terms": suggested_terms_count,
        "discovered_links": discovered_links_count,
        "telegram_links": telegram_links_count,
    }


# ---------------------------------------------------------------------------
# Batch collection dispatch helpers
# ---------------------------------------------------------------------------


async def fetch_batch_run_details(run_id: Any) -> dict[str, Any] | None:
    """Load a CollectionRun and its QueryDesign for batch dispatch.

    Args:
        run_id: UUID of the CollectionRun.

    Returns:
        Dict with run and design fields, or None if not found.
    """
    async with AsyncSessionLocal() as db:
        stmt = (
            select(
                CollectionRun.id.label("run_id"),
                CollectionRun.query_design_id,
                CollectionRun.arenas_config,
                CollectionRun.tier.label("default_tier"),
                CollectionRun.date_from,
                CollectionRun.date_to,
                CollectionRun.initiated_by.label("owner_id"),
                QueryDesign.language,
            )
            .join(QueryDesign, QueryDesign.id == CollectionRun.query_design_id)
            .where(CollectionRun.id == run_id)
        )
        result = await db.execute(stmt)
        row = result.mappings().first()
        return dict(row) if row else None


async def set_run_status(
    run_id: Any,
    status: str,
    *,
    started_at: bool = False,
    completed_at: bool = False,
    error_log: str | None = None,
) -> None:
    """Update a CollectionRun's status and optional timestamps.

    Args:
        run_id: UUID of the CollectionRun.
        status: New status value.
        started_at: If True, set started_at to NOW().
        completed_at: If True, set completed_at to NOW().
        error_log: Optional error log message.
    """
    values: dict[str, Any] = {"status": status}
    if started_at:
        values["started_at"] = datetime.now(tz=timezone.utc)
    if completed_at:
        values["completed_at"] = datetime.now(tz=timezone.utc)
    if error_log is not None:
        values["error_log"] = error_log

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CollectionRun)
            .where(CollectionRun.id == run_id)
            .values(**values)
        )
        await db.commit()


async def create_collection_tasks(
    run_id: Any,
    arena_platforms: list[dict[str, str]],
) -> None:
    """Bulk-create CollectionTask rows for a batch run.

    Args:
        run_id: UUID of the parent CollectionRun.
        arena_platforms: List of dicts with 'arena_name' and 'platform_name'.
    """
    async with AsyncSessionLocal() as db:
        for ap in arena_platforms:
            task = CollectionTask(
                collection_run_id=run_id,
                arena=ap["platform_name"],
                platform=ap["platform_name"],
                status="pending",
            )
            db.add(task)
        await db.commit()


async def update_task_celery_id(
    run_id: Any,
    platform_name: str,
    celery_task_id: str,
) -> None:
    """Update a CollectionTask row with its Celery task ID.

    Called after successfully dispatching a Celery task to record the task ID
    for status tracking and debugging.

    Args:
        run_id: UUID of the parent CollectionRun.
        platform_name: Platform identifier for the arena task.
        celery_task_id: Celery task ID returned by send_task().
    """
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CollectionTask)
            .where(
                CollectionTask.collection_run_id == run_id,
                CollectionTask.platform == platform_name,
            )
            .values(celery_task_id=celery_task_id)
        )
        await db.commit()


async def mark_task_failed(
    run_id: Any,
    platform_name: str,
    error_message: str,
) -> None:
    """Mark a CollectionTask as failed with an error message.

    Used when task dispatch fails or when a task needs to be skipped
    (e.g., no search terms available for that arena).

    Args:
        run_id: UUID of the parent CollectionRun.
        platform_name: Platform identifier for the arena task.
        error_message: Error description explaining why the task failed.
    """
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CollectionTask)
            .where(
                CollectionTask.collection_run_id == run_id,
                CollectionTask.platform == platform_name,
            )
            .values(
                status="failed",
                error_message=error_message,
                completed_at=datetime.now(tz=timezone.utc),
            )
        )
        await db.commit()


async def check_all_tasks_terminal(run_id: Any) -> dict[str, Any] | None:
    """Check whether all CollectionTasks for a run have reached terminal state.

    Also detects and marks as failed any tasks that have been stuck in 'pending'
    status for more than 10 minutes (likely dispatch failures or worker crashes).

    Args:
        run_id: UUID of the CollectionRun.

    Returns:
        Dict with 'all_done', 'total', 'completed', 'failed', 'total_records',
        'credits_spent' if tasks exist, or None if no tasks found.
    """
    from sqlalchemy import case, func  # noqa: PLC0415

    # First check for stuck tasks and mark them as failed
    stuck_cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=10)
    async with AsyncSessionLocal() as db:
        # Mark tasks that have been pending for > 10 minutes without a celery_task_id
        # as failed (likely dispatch failures)
        stuck_result = await db.execute(
            update(CollectionTask)
            .where(
                CollectionTask.collection_run_id == run_id,
                CollectionTask.status == "pending",
                CollectionTask.created_at < stuck_cutoff,
            )
            .values(
                status="failed",
                error_message="Task stuck in pending state for >10 minutes; likely dispatch failure or worker crash",
                completed_at=datetime.now(tz=timezone.utc),
            )
        )
        stuck_count = stuck_result.rowcount or 0
        if stuck_count > 0:
            await db.commit()

        # Now check terminal status
        stmt = select(
            func.count(CollectionTask.id).label("total"),
            func.sum(
                case(
                    (CollectionTask.status == "completed", 1),
                    else_=0,
                )
            ).label("completed"),
            func.sum(
                case(
                    (CollectionTask.status == "failed", 1),
                    else_=0,
                )
            ).label("failed"),
            func.sum(CollectionTask.records_collected).label("total_records"),
        ).where(CollectionTask.collection_run_id == run_id)

        result = await db.execute(stmt)
        row = result.mappings().first()
        if not row or row["total"] == 0:
            return None

        total = row["total"]
        completed = row["completed"] or 0
        failed = row["failed"] or 0
        total_records = row["total_records"] or 0

        # Also fetch the run's credits_spent
        run_result = await db.execute(
            select(CollectionRun.credits_spent).where(CollectionRun.id == run_id)
        )
        credits_spent = run_result.scalar_one_or_none() or 0

        return {
            "all_done": (completed + failed) >= total,
            "total": total,
            "completed": completed,
            "failed": failed,
            "total_records": total_records,
            "credits_spent": credits_spent,
            "stuck_marked_failed": stuck_count,
        }


# ---------------------------------------------------------------------------
# Record persistence for arena collection tasks
# ---------------------------------------------------------------------------


def persist_collected_records(
    records: list[dict[str, Any]],
    collection_run_id: str,
    query_design_id: str | None = None,
) -> tuple[int, int]:
    """Bulk-insert normalized content records into the database.

    Uses a synchronous session (safe for Celery worker context) with
    ``INSERT ... ON CONFLICT DO NOTHING`` to skip duplicate records
    (matched on ``content_hash`` + ``published_at``).

    Args:
        records: List of normalized record dicts from a collector's
            ``collect_by_terms()`` or ``collect_by_actors()``.
        collection_run_id: UUID string of the parent collection run,
            used to update ``collection_runs.records_collected``.
        query_design_id: Optional UUID string of the owning query design.
            Injected into each record if not already set.

    Returns:
        Tuple of ``(inserted_count, skipped_count)``.
    """
    import json

    import structlog
    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session  # noqa: PLC0415

    logger = structlog.get_logger("issue_observatory.workers._task_helpers")

    if not records:
        return 0, 0

    # Columns that need explicit CAST() for psycopg2 type inference.
    _JSONB_COLS = {"raw_metadata"}
    _TEXT_ARRAY_COLS = {"search_terms_matched", "media_urls"}
    _UUID_COLS = {"collection_run_id", "query_design_id", "author_id"}
    _TIMESTAMP_COLS = {"published_at", "collected_at"}

    inserted = 0
    skipped = 0

    with get_sync_session() as db:
        for record in records:
            # Inject run/design IDs if the normalizer didn't set them.
            if not record.get("collection_run_id"):
                record["collection_run_id"] = collection_run_id
            if not record.get("query_design_id") and query_design_id:
                record["query_design_id"] = query_design_id

            columns = [k for k, v in record.items() if v is not None]
            if not columns:
                skipped += 1
                continue

            # Build placeholder list with CAST() for types the driver may
            # not infer correctly from plain strings.
            placeholders = []
            params: dict[str, Any] = {}
            for col in columns:
                val = record[col]
                if col in _JSONB_COLS:
                    placeholders.append(f"CAST(:{col} AS jsonb)")
                    params[col] = json.dumps(val) if not isinstance(val, str) else val
                elif col in _TEXT_ARRAY_COLS:
                    # text[] columns — convert Python list to PostgreSQL array literal.
                    placeholders.append(f"CAST(:{col} AS text[])")
                    if isinstance(val, list):
                        params[col] = "{" + ",".join(
                            '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
                            for v in val
                        ) + "}"
                    else:
                        params[col] = str(val)
                elif col in _UUID_COLS:
                    placeholders.append(f"CAST(:{col} AS uuid)")
                    params[col] = str(val)
                elif col in _TIMESTAMP_COLS:
                    placeholders.append(f"CAST(:{col} AS timestamptz)")
                    # Strip trailing 'Z' if offset already present.
                    sval = str(val)
                    if sval.endswith("+00:00Z"):
                        sval = sval[:-1]
                    params[col] = sval
                else:
                    placeholders.append(f":{col}")
                    # Clamp simhash to signed bigint range.
                    if col == "simhash" and isinstance(val, int) and val > 9223372036854775807:
                        params[col] = val - 18446744073709551616  # 2^64
                    else:
                        params[col] = val

            col_list = ", ".join(columns)
            val_list = ", ".join(placeholders)

            stmt = text(
                f"INSERT INTO content_records ({col_list}) "  # noqa: S608
                f"VALUES ({val_list}) "
                f"ON CONFLICT (content_hash, published_at) "
                f"WHERE content_hash IS NOT NULL DO NOTHING"
            )
            try:
                # Use a SAVEPOINT so individual failures don't kill the batch.
                db.begin_nested()
                result = db.execute(stmt, params)
                if result.rowcount == 1:
                    inserted += 1
                else:
                    skipped += 1
                db.commit()  # release savepoint
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "persist_collected_records: insert failed",
                    error=str(exc),
                    platform=record.get("platform"),
                    url=record.get("url", "")[:100],
                )
                db.rollback()  # rollback to savepoint only
                skipped += 1

        db.commit()

        # Update the collection run's records_collected counter.
        if inserted > 0:
            db.execute(
                text(
                    "UPDATE collection_runs "
                    "SET records_collected = records_collected + :count "
                    "WHERE id = CAST(:run_id AS uuid)"
                ),
                {"count": inserted, "run_id": collection_run_id},
            )
            db.commit()

    logger.info(
        "persist_collected_records: done",
        inserted=inserted,
        skipped=skipped,
        run_id=collection_run_id,
    )
    return inserted, skipped
