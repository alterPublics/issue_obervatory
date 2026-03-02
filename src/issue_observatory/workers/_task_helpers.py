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

from sqlalchemy import func, select, update

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


async def fetch_designs_with_prep() -> list[dict[str, Any]]:
    """Fetch all live-tracking designs AND gather dispatch data in one async context.

    Combines ``fetch_live_tracking_designs`` with per-design credit balance,
    user email, public figure IDs, search terms, and actor IDs — all in a
    single event loop invocation.  This avoids the "Future attached to a
    different loop" error that occurs when multiple ``asyncio.run()`` calls
    share a SQLAlchemy async connection pool.

    Returns:
        List of design dicts, each augmented with ``credit_balance``,
        ``user_email``, ``public_figure_ids``, ``arena_terms``, and
        ``arena_actor_ids``.
    """
    designs = await fetch_live_tracking_designs()

    from issue_observatory.api.routes.collections import _normalize_arenas_config  # noqa: PLC0415
    from issue_observatory.arenas.registry import get_arena as _get_arena  # noqa: PLC0415

    for design in designs:
        owner_id = design["owner_id"]
        design_id = design["query_design_id"]

        # Credit balance
        async with AsyncSessionLocal() as db:
            svc = CreditService(session=db)
            design["credit_balance"] = await svc.get_available_credits(owner_id)

        # User email
        async with AsyncSessionLocal() as db:
            email_result = await db.execute(select(User.email).where(User.id == owner_id))
            design["user_email"] = email_result.scalar_one_or_none()

        # Public figure IDs
        try:
            design["public_figure_ids"] = list(
                await fetch_public_figure_ids_for_design(design_id)
            )
        except Exception:
            design["public_figure_ids"] = []

        # Per-arena terms and actor IDs
        raw_arenas_config: dict = design.get("arenas_config") or {}
        default_tier: str = design.get("default_tier") or "free"
        flat_arenas = _normalize_arenas_config(raw_arenas_config, default_tier)
        design["_flat_arenas"] = flat_arenas

        arena_terms: dict[str, list] = {}
        arena_actor_ids: dict[str, list] = {}

        for arena_name in flat_arenas:
            try:
                _collector_cls = _get_arena(arena_name)
                is_actor_only = not getattr(_collector_cls, "supports_term_search", True)
            except KeyError:
                is_actor_only = False

            if is_actor_only:
                try:
                    arena_actor_ids[arena_name] = await fetch_actor_ids_for_design_and_platform(
                        design_id, arena_name
                    )
                except Exception:
                    arena_actor_ids[arena_name] = []
            else:
                try:
                    arena_terms[arena_name] = await fetch_resolved_terms_for_arena(
                        design_id, arena_name
                    )
                except Exception:
                    arena_terms[arena_name] = []

        design["arena_terms"] = arena_terms
        design["arena_actor_ids"] = arena_actor_ids

    return designs


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
    """Return CollectionRun rows stuck in non-terminal states.

    A run is considered stale if:
    - It has been in 'running' or 'pending' status AND either:
      a) started_at > 30 min ago AND no records exist for the run, OR
      b) The most recent collected_at for the run's records is > 30 min ago, OR
      c) started_at > 24 h ago (absolute timeout fallback)

    Pending runs with started_at=NULL are newly created and NOT stale.

    Returns:
        List of dicts with ``id``, ``status``, and ``started_at``.
    """
    from sqlalchemy import or_  # noqa: PLC0415

    absolute_cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    idle_cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=30)

    async with AsyncSessionLocal() as db:
        # Subquery: most recent collected_at per run
        last_record_subq = (
            select(
                UniversalContentRecord.collection_run_id,
                func.max(UniversalContentRecord.collected_at).label("last_collected"),
            )
            .group_by(UniversalContentRecord.collection_run_id)
            .subquery()
        )

        stmt = (
            select(CollectionRun.id, CollectionRun.status, CollectionRun.started_at)
            .outerjoin(
                last_record_subq,
                CollectionRun.id == last_record_subq.c.collection_run_id,
            )
            .where(CollectionRun.status.in_(["pending", "running"]))
            .where(CollectionRun.started_at.is_not(None))
            .where(
                or_(
                    # Absolute timeout: started > 24h ago
                    CollectionRun.started_at < absolute_cutoff,
                    # Idle timeout: started > 30 min ago AND no records at all
                    (CollectionRun.started_at < idle_cutoff)
                    & (last_record_subq.c.last_collected.is_(None)),
                    # Idle timeout: last record > 30 min ago
                    last_record_subq.c.last_collected < idle_cutoff,
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
        "Marked as failed by stale_run_cleanup: no activity for >30 minutes or exceeded 24h absolute timeout"
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
    """Return the list of active DEFAULT search term strings scoped to a specific arena.

    Queries the ``search_terms`` table for all active **default** terms
    (``parent_term_id IS NULL``) associated with *query_design_id*, filtering
    to include only terms where:

    - ``is_active`` is ``True``
    - ``parent_term_id`` is ``NULL`` (excludes arena-specific overrides)
    - ``target_arenas`` is ``NULL`` (applies to all arenas), OR
    - ``target_arenas`` contains *arena_platform_name* in its JSONB array

    Override terms (``parent_term_id IS NOT NULL``) are excluded because they
    are handled by :func:`fetch_resolved_terms_for_arena` via the
    ``override_arena`` column.  Without this exclusion, overrides (which have
    ``target_arenas=NULL``) would leak into every arena's default term list.

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
            # Exclude override terms — they are arena-specific and handled
            # by fetch_resolved_terms_for_arena() via the override_arena
            # column.  Without this filter, override terms (which have
            # target_arenas=NULL) leak into every arena's default term list.
            .where(SearchTerm.parent_term_id.is_(None))
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


async def fetch_resolved_terms_for_arena(
    query_design_id: Any,
    arena_platform_name: str,
) -> list[str]:
    """Return resolved search term strings for an arena, merging overrides with defaults.

    Combines default terms (from YF-01 ``target_arenas`` logic) with any
    arena-specific override terms:

    1. Load default terms via :func:`fetch_search_terms_for_arena` (terms
       with ``target_arenas IS NULL`` or containing this arena).
    2. Load override terms for ``arena_platform_name`` (rows where
       ``override_arena == arena_platform_name`` and
       ``parent_term_id IS NOT NULL``).
    3. Return the merged (deduplicated) union of both sets, preserving order.

    Args:
        query_design_id: UUID of the ``QueryDesign`` whose search terms to load.
        arena_platform_name: Platform identifier string (e.g., ``"tiktok"``,
            ``"bluesky"``, ``"google_search"``).

    Returns:
        List of search term strings.  Empty when no active terms resolve for
        the given arena.
    """
    from issue_observatory.core.models.query_design import SearchTerm  # noqa: PLC0415

    # Step 1: load default terms (YF-01 target_arenas filtering)
    default_terms = await fetch_search_terms_for_arena(query_design_id, arena_platform_name)

    # Step 2: load arena-specific override terms
    async with AsyncSessionLocal() as db:
        override_stmt = (
            select(SearchTerm.term)
            .where(SearchTerm.query_design_id == query_design_id)
            .where(SearchTerm.is_active.is_(True))
            .where(SearchTerm.override_arena == arena_platform_name)
            .where(SearchTerm.parent_term_id.isnot(None))
            .order_by(SearchTerm.added_at)
        )
        result = await db.execute(override_stmt)
        override_terms = [str(t) for t in result.scalars().all()]

    # Step 3: merge, deduplicating while preserving order
    if not override_terms:
        return default_terms

    seen: set[str] = set()
    merged: list[str] = []
    for term in default_terms + override_terms:
        lower = term.lower()
        if lower not in seen:
            seen.add(lower)
            merged.append(term)
    return merged


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
    or 'running' status for more than 2 minutes (likely dispatch failures, import
    errors, or worker crashes).

    Args:
        run_id: UUID of the CollectionRun.

    Returns:
        Dict with 'all_done', 'total', 'completed', 'failed', 'total_records',
        'credits_spent' if tasks exist, or None if no tasks found.
    """
    from sqlalchemy import case, func  # noqa: PLC0415

    # First check for stuck tasks and mark them as failed
    # Reduced from 10 minutes to 2 minutes to detect issues faster
    stuck_cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=2)
    async with AsyncSessionLocal() as db:
        # Mark tasks that have been pending for > 2 minutes as failed
        # (likely dispatch failures or import errors preventing task execution)
        stuck_result = await db.execute(
            update(CollectionTask)
            .where(
                CollectionTask.collection_run_id == run_id,
                CollectionTask.status == "pending",
                CollectionTask.started_at.is_(None),
                select(CollectionRun.started_at)
                .where(CollectionRun.id == run_id)
                .scalar_subquery()
                < stuck_cutoff,
            )
            .values(
                status="failed",
                error_message="Task stuck in pending state for >2 minutes; likely dispatch failure, import error, or missing dependency",
                completed_at=datetime.now(tz=timezone.utc),
            )
        )
        stuck_count = stuck_result.rowcount or 0
        if stuck_count > 0:
            await db.commit()

        # Also check for tasks stuck in 'running' status for > 1 hour
        # (infinite loops, hanging HTTP calls, etc.)
        running_stuck_cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        running_stuck_result = await db.execute(
            update(CollectionTask)
            .where(
                CollectionTask.collection_run_id == run_id,
                CollectionTask.status == "running",
                CollectionTask.started_at < running_stuck_cutoff,
            )
            .values(
                status="failed",
                error_message="Task stuck in running state for >1 hour; likely infinite loop or hanging API call",
                completed_at=datetime.now(tz=timezone.utc),
            )
        )
        running_stuck_count = running_stuck_result.rowcount or 0
        if running_stuck_count > 0:
            await db.commit()
            stuck_count += running_stuck_count

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
                    (CollectionTask.status.in_(["failed", "cancelled"]), 1),
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


def _match_terms_in_text(
    text_content: str | None,
    title: str | None,
    terms: list[str],
) -> list[str]:
    """Return which search terms appear in the record's text or title.

    Simple case-insensitive substring matching.  Used as a fallback when
    a collector does not populate ``search_terms_matched`` itself.
    """
    if not terms:
        return []
    haystack = (
        (title or "").lower() + " " + (text_content or "").lower()
    )
    if not haystack.strip():
        return []
    return [t for t in terms if t.lower() in haystack]


def persist_collected_records(
    records: list[dict[str, Any]],
    collection_run_id: str,
    query_design_id: str | None = None,
    terms: list[str] | None = None,
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
        terms: Optional list of search terms used for collection. When
            provided, records with empty ``search_terms_matched`` will be
            backfilled via client-side text matching on title + text_content.

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

    # Set term_matched based on search_terms_matched presence.
    # Backfill search_terms_matched via text matching when terms are provided.
    for record in records:
        matched_terms = record.get("search_terms_matched")
        if (not matched_terms or len(matched_terms) == 0) and terms:
            matched_terms = _match_terms_in_text(
                record.get("text_content"),
                record.get("title"),
                terms,
            )
            if matched_terms:
                record["search_terms_matched"] = matched_terms
        if matched_terms and len(matched_terms) > 0:
            record.setdefault("term_matched", True)
        else:
            record.setdefault("term_matched", False)

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


def update_collection_task_status(
    collection_run_id: str,
    arena: str,
    status: str,
    records_collected: int = 0,
    duplicates_skipped: int = 0,
    error_message: str | None = None,
) -> None:
    """Best-effort update of the ``collection_tasks`` row for a specific arena.

    This is a shared helper for all arena tasks to report their progress
    and final status.  DB failures are logged at WARNING and do not propagate
    to the caller — this must never break a collection task.

    Args:
        collection_run_id: UUID string of the parent collection run.
        arena: Arena identifier (platform_name from the registry).
        status: New status value (``"running"`` | ``"completed"`` | ``"failed"``).
        records_collected: Number of records successfully inserted into the DB.
        duplicates_skipped: Number of records skipped because they were
            already present (detected via ON CONFLICT on content_hash).
        error_message: Error description for failed updates, or ``None``.
    """
    from sqlalchemy import text  # noqa: PLC0415

    from issue_observatory.core.database import get_sync_session  # noqa: PLC0415

    try:
        with get_sync_session() as session:
            session.execute(
                text(
                    """
                    UPDATE collection_tasks
                    SET status = :status,
                        records_collected = :records_collected,
                        duplicates_skipped = :duplicates_skipped,
                        error_message = :error_message,
                        completed_at = CASE WHEN :status IN ('completed', 'failed', 'cancelled')
                                            THEN NOW() ELSE completed_at END,
                        started_at   = CASE WHEN :status = 'running' AND started_at IS NULL
                                            THEN NOW() ELSE started_at END
                    WHERE collection_run_id = :run_id AND arena = :arena
                    """
                ),
                {
                    "status": status,
                    "records_collected": records_collected,
                    "duplicates_skipped": duplicates_skipped,
                    "error_message": error_message,
                    "run_id": collection_run_id,
                    "arena": arena,
                },
            )
            session.commit()
    except Exception as exc:  # noqa: BLE001
        import structlog

        log = structlog.get_logger("issue_observatory.workers._task_helpers")
        log.warning(
            "update_collection_task_status: failed to update status",
            arena=arena,
            status=status,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Actor-only arena helpers
# ---------------------------------------------------------------------------


async def fetch_actor_ids_for_design_and_platform(
    query_design_id: Any,
    platform_name: str,
) -> list[str]:
    """Return platform actor identifiers for an actor-only arena's collection.

    Queries ``ActorPlatformPresence`` rows linked (via ``ActorListMember`` and
    ``ActorList``) to the actor lists of *query_design_id*, filtered to
    ``platform == platform_name``.

    The returned strings are the best available identifier for each presence,
    chosen in this precedence order:

    1. ``profile_url`` — preferred for Facebook and Instagram, whose
       Bright Data collectors accept full page/group/profile URLs.
    2. ``platform_user_id`` — native numeric or opaque user ID returned
       by the upstream API (e.g. Twitter user ID).
    3. ``platform_username`` — display handle (e.g. ``"drnyheder"``), used
       as a fallback when neither URL nor numeric ID is available.

    Presences where all three fields are NULL are silently excluded.

    Args:
        query_design_id: UUID of the ``QueryDesign`` whose actor lists to
            inspect.
        platform_name: Platform identifier matching ``ActorPlatformPresence.platform``
            (e.g. ``"facebook"``, ``"instagram"``).

    Returns:
        Deduplicated list of actor identifier strings.  Empty list when no
        presences matching *platform_name* are found for the design.
    """
    async with AsyncSessionLocal() as db:
        stmt = (
            select(
                ActorPlatformPresence.profile_url,
                ActorPlatformPresence.platform_user_id,
                ActorPlatformPresence.platform_username,
            )
            .join(Actor, Actor.id == ActorPlatformPresence.actor_id)
            .join(ActorListMember, ActorListMember.actor_id == Actor.id)
            .join(ActorList, ActorList.id == ActorListMember.actor_list_id)
            .where(ActorList.query_design_id == query_design_id)
            .where(ActorPlatformPresence.platform == platform_name)
        )
        result = await db.execute(stmt)
        rows = result.mappings().all()

    seen: set[str] = set()
    actor_ids: list[str] = []
    for row in rows:
        # Precedence: profile_url > platform_user_id > platform_username
        identifier: str | None = (
            row["profile_url"]
            or row["platform_user_id"]
            or row["platform_username"]
        )
        if identifier and identifier not in seen:
            seen.add(identifier)
            actor_ids.append(identifier)

    return actor_ids


# ---------------------------------------------------------------------------
# Cross-design record linking (Issue 3: avoid recollection)
# ---------------------------------------------------------------------------


def reindex_existing_records(
    platform: str,
    collection_run_id: str,
    query_design_id: str | None,
    terms: list[str] | None = None,
    actor_ids: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> int:
    """Link existing content records from OTHER runs to this collection run.

    Finds records that match the given terms/actors and date range from
    previous collection runs and creates ``content_record_links`` rows so
    that the current run's analysis includes them without re-fetching.

    Args:
        platform: Platform identifier (e.g. ``"bluesky"``).
        collection_run_id: UUID string of the current collection run.
        query_design_id: UUID string of the owning query design (optional).
        terms: Search terms to match against ``search_terms_matched``.
        actor_ids: Actor platform IDs to match against ``author_platform_id``.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).

    Returns:
        Number of link rows created.
    """
    import json
    import logging

    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session  # noqa: PLC0415

    log = logging.getLogger("issue_observatory.workers._task_helpers")

    # All queries include published_at bounds for partition pruning on
    # content_records (range-partitioned by published_at, monthly).
    clauses = [
        "cr.platform = :platform",
    ]
    params: dict[str, Any] = {
        "platform": platform,
        "run_id": collection_run_id,
    }

    if date_from:
        clauses.append("cr.published_at >= CAST(:date_from AS timestamptz)")
        params["date_from"] = date_from
    if date_to:
        clauses.append("cr.published_at <= CAST(:date_to AS timestamptz)")
        params["date_to"] = date_to

    # Match on terms OR actors (whichever is provided).
    # Uses GIN-compatible @> operator for search_terms_matched,
    # and B-tree index for author_platform_id.
    if terms:
        clauses.append("cr.search_terms_matched && CAST(:terms AS text[])")
        params["terms"] = "{" + ",".join(
            '"' + t.replace("\\", "\\\\").replace('"', '\\"') + '"' for t in terms
        ) + "}"
    elif actor_ids:
        clauses.append("cr.author_platform_id = ANY(:actor_ids)")
        params["actor_ids"] = actor_ids

    where = " AND ".join(clauses)

    qd_value = f"CAST(:qd_id AS uuid)" if query_design_id else "NULL"
    if query_design_id:
        params["qd_id"] = query_design_id

    insert_sql = text(
        f"INSERT INTO content_record_links "  # noqa: S608
        f"(content_record_id, content_record_published_at, collection_run_id, "
        f"query_design_id, link_type) "
        f"SELECT cr.id, cr.published_at, CAST(:run_id AS uuid), "
        f"{qd_value}, 'reindex' "
        f"FROM content_records cr WHERE {where} "
        f"ON CONFLICT (content_record_id, content_record_published_at, collection_run_id) "
        f"DO NOTHING"
    )

    try:
        with get_sync_session() as db:
            result = db.execute(insert_sql, params)
            linked = result.rowcount
            db.commit()

        log.info(
            "reindex_existing_records: linked %d records for platform=%s run=%s",
            linked,
            platform,
            collection_run_id,
        )
        return linked
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "reindex_existing_records: failed for platform=%s run=%s: %s",
            platform,
            collection_run_id,
            exc,
        )
        return 0


# ---------------------------------------------------------------------------
# Collection attempt recording (scalable pre-check metadata)
# ---------------------------------------------------------------------------


def record_collection_attempt(
    platform: str,
    collection_run_id: str,
    query_design_id: str | None,
    input_value: str,
    input_type: str,
    date_from: str,
    date_to: str,
    records_returned: int | None,
) -> None:
    """Record a single collection attempt in the ``collection_attempts`` table.

    Called after each per-input (per-term or per-actor) collection completes.
    The coverage checker queries this lightweight table instead of scanning
    ``content_records``, keeping pre-checks O(attempts) not O(data).

    Mirrors the ``process_pull()`` pattern from the legacy spreadAnalysis
    MongoDB tool's ``pull`` collection.

    Args:
        platform: Platform identifier (e.g. ``"bluesky"``).
        collection_run_id: UUID string of the parent collection run.
        query_design_id: UUID string of the owning query design (optional).
        input_value: The search term or actor platform ID that was collected.
        input_type: ``"term"`` or ``"actor"``.
        date_from: ISO 8601 start of the collection window.
        date_to: ISO 8601 end of the collection window.
        records_returned: Number of records returned by the API, or ``None``
            if the attempt failed.
    """
    import logging

    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session  # noqa: PLC0415

    log = logging.getLogger("issue_observatory.workers._task_helpers")

    try:
        with get_sync_session() as db:
            db.execute(
                text(
                    "INSERT INTO collection_attempts "
                    "(platform, input_value, input_type, date_from, date_to, "
                    "records_returned, collection_run_id, query_design_id) "
                    "VALUES (:platform, :input_value, :input_type, "
                    "CAST(:date_from AS timestamptz), CAST(:date_to AS timestamptz), "
                    ":records_returned, CAST(:run_id AS uuid), "
                    "CAST(:qd_id AS uuid))"
                ),
                {
                    "platform": platform,
                    "input_value": input_value,
                    "input_type": input_type,
                    "date_from": date_from,
                    "date_to": date_to,
                    "records_returned": records_returned,
                    "run_id": collection_run_id,
                    "qd_id": query_design_id,
                },
            )
            db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "record_collection_attempt: failed for platform=%s input=%s: %s",
            platform,
            input_value,
            exc,
        )


def record_collection_attempts_batch(
    platform: str,
    collection_run_id: str,
    query_design_id: str | None,
    inputs: list[str],
    input_type: str,
    date_from: str,
    date_to: str,
    records_returned: int | None,
) -> None:
    """Record collection attempts for multiple inputs in a single transaction.

    Convenience wrapper around :func:`record_collection_attempt` that inserts
    one row per input value in a single DB round-trip.

    Args:
        platform: Platform identifier.
        collection_run_id: UUID string of the parent collection run.
        query_design_id: UUID string of the owning query design (optional).
        inputs: List of search terms or actor platform IDs.
        input_type: ``"term"`` or ``"actor"``.
        date_from: ISO 8601 start of the collection window.
        date_to: ISO 8601 end of the collection window.
        records_returned: Total records returned (split equally is impractical,
            so the total is stored on each row — the coverage checker only
            checks ``IS NOT NULL`` to confirm success).
    """
    import logging

    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session  # noqa: PLC0415

    log = logging.getLogger("issue_observatory.workers._task_helpers")

    if not inputs:
        return

    try:
        with get_sync_session() as db:
            for inp in inputs:
                db.execute(
                    text(
                        "INSERT INTO collection_attempts "
                        "(platform, input_value, input_type, date_from, date_to, "
                        "records_returned, collection_run_id, query_design_id) "
                        "VALUES (:platform, :input_value, :input_type, "
                        "CAST(:date_from AS timestamptz), CAST(:date_to AS timestamptz), "
                        ":records_returned, CAST(:run_id AS uuid), "
                        "CAST(:qd_id AS uuid))"
                    ),
                    {
                        "platform": platform,
                        "input_value": inp,
                        "input_type": input_type,
                        "date_from": date_from,
                        "date_to": date_to,
                        "records_returned": records_returned,
                        "run_id": collection_run_id,
                        "qd_id": query_design_id,
                    },
                )
            db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "record_collection_attempts_batch: failed for platform=%s: %s",
            platform,
            exc,
        )


# ---------------------------------------------------------------------------
# Collection attempt reconciliation
# ---------------------------------------------------------------------------


def reconcile_collection_attempts() -> dict[str, int]:
    """Validate collection_attempts against actual content_records data.

    For each valid attempt with ``records_returned > 0``, checks whether
    at least one matching content record still exists in the database.
    If no records remain (e.g. due to manual deletion or retention policy
    enforcement), the attempt is marked ``is_valid = FALSE`` so the
    coverage checker no longer trusts it.

    This runs as a periodic Celery Beat task (weekly by default) to prevent
    stale coverage claims from permanently blocking re-collection.

    The check is efficient: uses ``EXISTS`` with partition-pruning-friendly
    predicates (platform + published_at bounds) and short-circuits per row.

    Returns:
        Dict with ``attempts_checked`` and ``attempts_invalidated`` counts.
    """
    import logging

    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session  # noqa: PLC0415

    log = logging.getLogger("issue_observatory.workers._task_helpers")

    checked = 0
    invalidated = 0

    try:
        with get_sync_session() as db:
            # Fetch all valid attempts that claimed successful collection.
            # We process in batches to avoid holding a long transaction.
            rows = db.execute(
                text(
                    "SELECT id, platform, input_value, input_type, "
                    "date_from, date_to "
                    "FROM collection_attempts "
                    "WHERE is_valid = TRUE AND records_returned > 0 "
                    "ORDER BY attempted_at DESC"
                )
            ).fetchall()

            stale_ids: list[str] = []

            for row in rows:
                checked += 1
                attempt_id = str(row[0])
                platform = row[1]
                input_value = row[2]
                input_type = row[3]
                date_from = row[4]
                date_to = row[5]

                # Build a targeted EXISTS check against content_records.
                # Uses partition-pruning predicates (published_at bounds)
                # and short-circuits after the first matching row.
                cr_clauses = [
                    "platform = :platform",
                    "published_at >= CAST(:date_from AS timestamptz)",
                    "published_at <= CAST(:date_to AS timestamptz)",
                ]
                cr_params: dict[str, Any] = {
                    "platform": platform,
                    "date_from": date_from.isoformat()
                    if hasattr(date_from, "isoformat")
                    else str(date_from),
                    "date_to": date_to.isoformat()
                    if hasattr(date_to, "isoformat")
                    else str(date_to),
                }

                if input_type == "term":
                    cr_clauses.append(
                        "search_terms_matched @> CAST(:term_arr AS text[])"
                    )
                    cr_params["term_arr"] = (
                        "{"
                        + input_value.replace("\\", "\\\\").replace('"', '\\"')
                        + "}"
                    )
                elif input_type == "actor":
                    cr_clauses.append("author_platform_id = :actor_id")
                    cr_params["actor_id"] = input_value

                cr_where = " AND ".join(cr_clauses)

                exists_result = db.execute(
                    text(
                        f"SELECT EXISTS("  # noqa: S608
                        f"SELECT 1 FROM content_records WHERE {cr_where} LIMIT 1)"
                    ),
                    cr_params,
                ).scalar()

                if not exists_result:
                    stale_ids.append(attempt_id)

            # Batch-invalidate stale attempts.
            if stale_ids:
                # Process in chunks of 500 to avoid overly large IN clauses.
                for i in range(0, len(stale_ids), 500):
                    chunk = stale_ids[i : i + 500]
                    placeholders = ", ".join(
                        f"CAST(:id_{j} AS uuid)" for j in range(len(chunk))
                    )
                    params_dict = {f"id_{j}": uid for j, uid in enumerate(chunk)}
                    db.execute(
                        text(
                            f"UPDATE collection_attempts "  # noqa: S608
                            f"SET is_valid = FALSE "
                            f"WHERE id IN ({placeholders})"
                        ),
                        params_dict,
                    )
                invalidated = len(stale_ids)
                db.commit()

        log.info(
            "reconcile_collection_attempts: checked=%d invalidated=%d",
            checked,
            invalidated,
        )
    except Exception as exc:  # noqa: BLE001
        log.error(
            "reconcile_collection_attempts: error: %s",
            exc,
            exc_info=True,
        )

    return {"attempts_checked": checked, "attempts_invalidated": invalidated}
