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

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

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
from issue_observatory.core.models.project import Project
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
                QueryDesign.project_id,
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


async def _fetch_last_collected_per_platform(run_id: Any) -> dict[str, datetime]:
    """Return the latest collected_at timestamp per platform for a collection run.

    Args:
        run_id: UUID of the CollectionRun to query.

    Returns:
        Dict mapping platform name to the most recent collected_at datetime.
    """
    async with AsyncSessionLocal() as db:
        stmt = (
            select(
                UniversalContentRecord.platform,
                func.max(UniversalContentRecord.collected_at).label("last_collected"),
            )
            .where(UniversalContentRecord.collection_run_id == run_id)
            .group_by(UniversalContentRecord.platform)
        )
        result = await db.execute(stmt)
        return {row.platform: row.last_collected for row in result.all()}


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

    from issue_observatory.api.routes.collections import _normalize_arenas_config
    from issue_observatory.arenas.registry import get_arena as _get_arena

    for design in designs:
        owner_id = design["owner_id"]
        design_id = design["query_design_id"]
        project_id = design.get("project_id")

        # Credit balance
        async with AsyncSessionLocal() as db:
            svc = CreditService(session=db)
            design["credit_balance"] = await svc.get_available_credits(owner_id)

        # User email
        async with AsyncSessionLocal() as db:
            email_result = await db.execute(select(User.email).where(User.id == owner_id))
            design["user_email"] = email_result.scalar_one_or_none()

        # Public figure IDs — prefer project-scoped if available
        try:
            if project_id:
                design["public_figure_ids"] = list(
                    await fetch_public_figure_ids_for_project(project_id)
                )
            else:
                design["public_figure_ids"] = list(
                    await fetch_public_figure_ids_for_design(design_id)
                )
        except Exception:
            design["public_figure_ids"] = []

        # Per-arena terms and actor IDs
        raw_arenas_config: dict = design.get("arenas_config") or {}
        default_tier: str = design.get("default_tier") or "free"
        flat_arenas = _normalize_arenas_config(raw_arenas_config, default_tier)

        # Project-level arena filter (intersection).
        if project_id:
            async with AsyncSessionLocal() as db:
                proj = await db.get(Project, project_id)
                if proj and proj.arenas_config:
                    proj_arenas = _normalize_arenas_config(proj.arenas_config, default_tier)
                    if proj_arenas:
                        flat_arenas = {k: v for k, v in flat_arenas.items() if k in proj_arenas}

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
                    if project_id:
                        arena_actor_ids[arena_name] = await fetch_actor_ids_for_project_and_platform(
                            project_id, arena_name
                        )
                    else:
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

        # Last-collected timestamps for date-bound computation in live dispatch
        try:
            design["last_collected_by_platform"] = await _fetch_last_collected_per_platform(
                design["run_id"]
            )
        except Exception:
            design["last_collected_by_platform"] = {}

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
    from sqlalchemy import or_

    absolute_cutoff = datetime.now(tz=UTC) - timedelta(hours=24)
    idle_cutoff = datetime.now(tz=UTC) - timedelta(minutes=30)

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
    from issue_observatory.core.models.query_design import SearchTerm

    async with AsyncSessionLocal() as db:
        # YF-01 filtering logic:
        # Include terms where target_arenas is NULL (all arenas)
        # OR where the JSONB array contains the arena platform_name.
        # PostgreSQL's JSONB ? operator checks for string existence in array/object.
        from sqlalchemy import func, or_

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
    from issue_observatory.core.models.query_design import SearchTerm

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
    from uuid import UUID

    from issue_observatory.analysis.descriptive import get_emergent_terms
    from issue_observatory.analysis.link_miner import LinkMiner

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
        except Exception:
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
        except Exception:
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
                CollectionRun.project_id,
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
        values["started_at"] = datetime.now(tz=UTC)
    if completed_at:
        values["completed_at"] = datetime.now(tz=UTC)
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
                completed_at=datetime.now(tz=UTC),
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
    from sqlalchemy import case, func

    async with AsyncSessionLocal() as db:
        # Check if the run itself has been cancelled by the user.
        # If so, mark all non-terminal tasks as cancelled immediately.
        run_status_result = await db.execute(
            select(CollectionRun.status).where(CollectionRun.id == run_id)
        )
        run_status = run_status_result.scalar_one_or_none()
        if run_status == "cancelled":
            cancel_result = await db.execute(
                update(CollectionTask)
                .where(
                    CollectionTask.collection_run_id == run_id,
                    CollectionTask.status.notin_(["completed", "failed", "cancelled"]),
                )
                .values(
                    status="cancelled",
                    error_message="Run cancelled by user.",
                    completed_at=datetime.now(tz=UTC),
                )
            )
            if cancel_result.rowcount and cancel_result.rowcount > 0:
                await db.commit()

    # First check for stuck tasks and mark them as failed
    # Reduced from 10 minutes to 2 minutes to detect issues faster
    stuck_cutoff = datetime.now(tz=UTC) - timedelta(minutes=2)
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
                completed_at=datetime.now(tz=UTC),
            )
        )
        stuck_count = stuck_result.rowcount or 0
        if stuck_count > 0:
            await db.commit()

        # Also check for tasks stuck in 'running' status for too long.
        # The global Celery hard limit is 2 hours (celery_app.py:134).
        # Arena-specific limits range from 12 min to 2h 5min.
        # A task still 'running' 30 min past the global soft limit (1 hour)
        # is certainly dead (killed by Celery without updating the DB).
        running_stuck_cutoff = datetime.now(tz=UTC) - timedelta(minutes=90)
        running_stuck_result = await db.execute(
            update(CollectionTask)
            .where(
                CollectionTask.collection_run_id == run_id,
                CollectionTask.status == "running",
                CollectionTask.started_at < running_stuck_cutoff,
            )
            .values(
                status="failed",
                error_message="Task stuck in running state for >90 min (past Celery hard limit); likely killed without status update",
                completed_at=datetime.now(tz=UTC),
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


def _fetch_terms_for_design(query_design_id: str) -> list[str]:
    """Look up active search terms for a query design from the database.

    Uses a synchronous session (safe for Celery worker context).
    Returns an empty list on any error to avoid blocking persistence.
    """
    try:
        from sqlalchemy import text as sa_text

        from issue_observatory.core.database import get_sync_session

        with get_sync_session() as session:
            rows = session.execute(
                sa_text(
                    "SELECT term FROM search_terms "
                    "WHERE query_design_id = CAST(:qd_id AS uuid) AND is_active = true"
                ),
                {"qd_id": query_design_id},
            ).fetchall()
            return [row[0] for row in rows] if rows else []
    except Exception:
        return []


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


class RunCancelledError(Exception):
    """Raised when a collection run has been cancelled by the user."""


def is_run_cancelled(collection_run_id: str) -> bool:
    """Check whether a collection run has been cancelled.

    Uses a synchronous DB query (safe for Celery worker context).
    Returns ``True`` if the run status is ``'cancelled'``.
    Returns ``False`` on any error (fail-open to avoid blocking tasks).
    """
    try:
        from sqlalchemy import text

        from issue_observatory.core.database import get_sync_session

        with get_sync_session() as session:
            row = session.execute(
                text("SELECT status FROM collection_runs WHERE id = :id"),
                {"id": collection_run_id},
            ).fetchone()
            if row and row[0] == "cancelled":
                return True
    except Exception:
        pass
    return False


def check_run_cancelled(collection_run_id: str) -> None:
    """Raise ``RunCancelledError`` if the run has been cancelled.

    Call this at natural checkpoints in long-running arena tasks
    (between API pages, between batch inserts, etc.) to bail out
    promptly when the user cancels a run.
    """
    if is_run_cancelled(collection_run_id):
        raise RunCancelledError(
            f"Collection run {collection_run_id} was cancelled by the user."
        )


def make_rate_limiter() -> Any:
    """Create a shared Redis-backed :class:`RateLimiter` for arena tasks.

    Returns a :class:`~issue_observatory.workers.rate_limiter.RateLimiter`
    backed by the application's Redis instance.  The async Redis client
    opens connections lazily on first use, so this is safe to call from
    synchronous Celery task bodies before ``asyncio.run()``.

    Returns:
        A :class:`RateLimiter` instance, or ``None`` if Redis is unavailable.
    """
    try:
        import redis.asyncio as aioredis

        from issue_observatory.config.settings import get_settings
        from issue_observatory.workers.rate_limiter import RateLimiter

        settings = get_settings()
        redis_client = aioredis.from_url(
            str(settings.redis_url),
            encoding="utf-8",
            decode_responses=True,
        )
        return RateLimiter(redis_client=redis_client)
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "Could not create rate limiter — collectors will run without shared rate limiting"
        )
        return None


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

    from issue_observatory.core.database import get_sync_session

    logger = structlog.get_logger("issue_observatory.workers._task_helpers")

    if not records:
        return 0, 0

    # Bail out early if the run was cancelled while we were collecting.
    check_run_cancelled(collection_run_id)

    # Auto-fetch search terms from the query design when not explicitly provided.
    # This ensures actor-only arenas (Facebook, Instagram) and any task that
    # forgot to pass terms still get term-matching backfill.
    if not terms and query_design_id:
        terms = _fetch_terms_for_design(query_design_id)

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
                f"INSERT INTO content_records ({col_list}) "
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
            except Exception as exc:
                logger.warning(
                    "persist_collected_records: insert failed",
                    error=str(exc),
                    platform=record.get("platform"),
                    url=(record.get("url") or "")[:100],
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


def make_batch_sink(
    collection_run_id: str,
    query_design_id: str | None = None,
    terms: list[str] | None = None,
) -> Callable[[list[dict[str, Any]]], tuple[int, int]]:
    """Create a batch sink callback for :meth:`ArenaCollector.configure_batch_persistence`.

    Returns a closure that delegates to :func:`persist_collected_records`
    with the given run/design context pre-bound.

    Args:
        collection_run_id: UUID string of the parent collection run.
        query_design_id: Optional UUID string of the owning query design.
        terms: Optional search terms for term-matching backfill.

    Returns:
        Callable that accepts ``list[dict]`` and returns ``(inserted, skipped)``.
    """

    def _sink(records: list[dict[str, Any]]) -> tuple[int, int]:
        return persist_collected_records(records, collection_run_id, query_design_id, terms)

    return _sink


def count_run_platform_records(collection_run_id: str, platform: str) -> int:
    """Count actual content records for a run + platform.

    Useful as a fallback when in-memory counters may be inaccurate (e.g. after
    a task redelivery where the first execution persisted records but the
    counter was lost).

    Args:
        collection_run_id: UUID string of the parent collection run.
        platform: Platform name (e.g. ``"telegram"``, ``"bluesky"``).

    Returns:
        Number of content_records rows, or ``0`` on DB error.
    """
    from sqlalchemy import text

    try:
        with get_sync_session() as session:
            row = session.execute(
                text(
                    "SELECT COUNT(*) FROM content_records "
                    "WHERE collection_run_id = CAST(:run_id AS uuid) "
                    "AND platform = :platform"
                ),
                {"run_id": collection_run_id, "platform": platform},
            ).scalar()
            return int(row or 0)
    except Exception:
        return 0


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
    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

    try:
        with get_sync_session() as session:
            session.execute(
                text(
                    """
                    UPDATE collection_tasks
                    SET status = :status,
                        records_collected = GREATEST(records_collected, :records_collected),
                        duplicates_skipped = :duplicates_skipped,
                        error_message = :error_message,
                        completed_at = CASE WHEN :status IN ('completed', 'failed', 'cancelled')
                                            THEN NOW() ELSE completed_at END,
                        started_at   = CASE WHEN :status = 'running' AND started_at IS NULL
                                            THEN NOW() ELSE started_at END
                    WHERE collection_run_id = :run_id AND arena = :arena
                        AND status != 'cancelled'
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
    except Exception as exc:
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


async def fetch_actor_ids_for_project_and_platform(
    project_id: Any,
    platform_name: str,
) -> list[str]:
    """Return platform actor identifiers scoped to a *project* (not query design).

    Same logic as :func:`fetch_actor_ids_for_design_and_platform`, but queries
    ``ActorList.project_id`` instead of ``ActorList.query_design_id``.

    Args:
        project_id: UUID of the Project whose actor lists to inspect.
        platform_name: Platform identifier (e.g. ``"facebook"``).

    Returns:
        Deduplicated list of actor identifier strings.
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
            .where(ActorList.project_id == project_id)
            .where(ActorPlatformPresence.platform == platform_name)
        )
        result = await db.execute(stmt)
        rows = result.mappings().all()

    seen: set[str] = set()
    actor_ids: list[str] = []
    for row in rows:
        identifier: str | None = (
            row["profile_url"]
            or row["platform_user_id"]
            or row["platform_username"]
        )
        if identifier and identifier not in seen:
            seen.add(identifier)
            actor_ids.append(identifier)

    return actor_ids


async def fetch_public_figure_ids_for_project(project_id: Any) -> set[str]:
    """Return public-figure platform user IDs scoped to a *project*.

    Same logic as :func:`fetch_public_figure_ids_for_design`, but queries
    ``ActorList.project_id`` instead of ``ActorList.query_design_id``.

    Args:
        project_id: UUID of the Project whose actor lists to inspect.

    Returns:
        Set of ``platform_user_id`` strings.
    """
    async with AsyncSessionLocal() as db:
        stmt = (
            select(ActorPlatformPresence.platform_user_id)
            .join(Actor, Actor.id == ActorPlatformPresence.actor_id)
            .join(ActorListMember, ActorListMember.actor_id == Actor.id)
            .join(ActorList, ActorList.id == ActorListMember.actor_list_id)
            .where(ActorList.project_id == project_id)
            .where(Actor.public_figure.is_(True))
            .where(ActorPlatformPresence.platform_user_id.is_not(None))
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return {str(uid) for uid in rows}


# ---------------------------------------------------------------------------
# Source list helpers (actor workflow redesign)
# ---------------------------------------------------------------------------


def read_source_list_from_arenas_config(
    arenas_config: dict,
    platform_name: str,
    config_key: str,
) -> list[str]:
    """Read a source list from the ``arenas_config`` JSONB for a given platform.

    Returns the string array stored at
    ``arenas_config[platform_name][config_key]``, or an empty list when the
    key does not exist or the value is not a list.

    This is a pure synchronous helper — no DB access is required because the
    raw ``arenas_config`` dict is loaded from the ``QueryDesign`` row by the
    caller before entering the async dispatch context.

    Args:
        arenas_config: The raw ``arenas_config`` JSONB dict from ``QueryDesign``.
        platform_name: Arena platform identifier (e.g. ``"bluesky"``).
        config_key: The sub-key within the platform section
            (e.g. ``"custom_accounts"``).  Comes from the collector class's
            ``source_list_config_key`` attribute.

    Returns:
        List of identifier strings. Empty list when the path does not exist,
        is ``None``, or contains non-string elements (those are silently
        filtered out).
    """
    arena_section = arenas_config.get(platform_name)
    if not isinstance(arena_section, dict):
        return []
    raw_list = arena_section.get(config_key)
    if not isinstance(raw_list, list):
        return []
    return [item for item in raw_list if isinstance(item, str) and item]


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
    import logging

    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

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

    qd_value = "CAST(:qd_id AS uuid)" if query_design_id else "NULL"
    if query_design_id:
        params["qd_id"] = query_design_id

    insert_sql = text(
        f"INSERT INTO content_record_links "
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
    except Exception as exc:
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

    from issue_observatory.core.database import get_sync_session

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
    except Exception as exc:
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
    per_input_counts: dict[str, int] | None = None,
) -> None:
    """Record collection attempts for multiple inputs in a single transaction.

    Convenience wrapper that inserts one row per input value in a single
    DB round-trip.

    When ``per_input_counts`` is provided, each input gets its actual count
    (0 for terms that returned no results).  Otherwise, all inputs get the
    same ``records_returned`` value (the run total) for backward
    compatibility.

    A ``records_returned`` of 0 is valid and means "the API was queried but
    returned nothing for this input".  The coverage checker treats this as
    valid coverage to avoid needlessly re-querying empty terms.

    Args:
        platform: Platform identifier.
        collection_run_id: UUID string of the parent collection run.
        query_design_id: UUID string of the owning query design (optional).
        inputs: List of search terms or actor platform IDs.
        input_type: ``"term"`` or ``"actor"``.
        date_from: ISO 8601 start of the collection window.
        date_to: ISO 8601 end of the collection window.
        records_returned: Fallback records count used when ``per_input_counts``
            is not provided.
        per_input_counts: Optional mapping of input → actual records count.
    """
    import logging

    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

    log = logging.getLogger("issue_observatory.workers._task_helpers")

    if not inputs:
        return

    try:
        with get_sync_session() as db:
            for inp in inputs:
                if per_input_counts is not None:
                    # Only record coverage for inputs the collector actually
                    # queried.  Inputs missing from per_input_counts were never
                    # sent to the API (e.g. collector crashed mid-run), so
                    # recording them as 0 would create false coverage.
                    if inp not in per_input_counts:
                        continue
                    count = per_input_counts[inp]
                else:
                    count = records_returned
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
                        "records_returned": count,
                        "run_id": collection_run_id,
                        "qd_id": query_design_id,
                    },
                )
            db.commit()
    except Exception as exc:
        log.warning(
            "record_collection_attempts_batch: failed for platform=%s: %s",
            platform,
            exc,
        )


# ---------------------------------------------------------------------------
# Platform URL error helpers (dead page suppression)
# ---------------------------------------------------------------------------


def get_suppressed_urls(platform: str, urls: list[str]) -> set[str]:
    """Return the subset of *urls* that should be suppressed (dead/errored).

    A URL is suppressed when ``failure_count >= 2`` AND ``last_seen_at`` is
    within the last 30 days.  After 30 days the URL is retried automatically.

    Fail-open: returns an empty set on any DB error so collection is never
    blocked by a bug in the suppression logic.

    Args:
        platform: Platform identifier (e.g. ``"facebook"``).
        urls: Candidate URLs to check.

    Returns:
        Set of URLs that should be skipped.
    """
    import logging

    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

    log = logging.getLogger("issue_observatory.workers._task_helpers")

    if not urls:
        return set()

    try:
        with get_sync_session() as db:
            rows = db.execute(
                text(
                    "SELECT url FROM platform_url_errors "
                    "WHERE platform = :platform "
                    "AND url = ANY(:urls) "
                    "AND failure_count >= 2 "
                    "AND last_seen_at > NOW() - INTERVAL '30 days'"
                ),
                {"platform": platform, "urls": urls},
            ).fetchall()
            return {row[0] for row in rows}
    except Exception as exc:
        log.warning("get_suppressed_urls: failed for platform=%s: %s", platform, exc)
        return set()


def record_url_errors(
    platform: str,
    errors: list[dict[str, str]],
) -> None:
    """UPSERT error records for URLs that failed collection.

    Each entry in *errors* should have keys ``url``, ``error_code``, and
    optionally ``error_detail``.  On conflict the ``failure_count`` is
    incremented, ``last_seen_at`` is updated, and the latest error code
    is stored.

    Best-effort: DB failures are logged and do not propagate.

    Args:
        platform: Platform identifier.
        errors: List of ``{"url": ..., "error_code": ..., "error_detail": ...}`` dicts.
    """
    import logging

    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

    log = logging.getLogger("issue_observatory.workers._task_helpers")

    if not errors:
        return

    try:
        with get_sync_session() as db:
            for err in errors:
                db.execute(
                    text(
                        "INSERT INTO platform_url_errors "
                        "(platform, url, error_code, error_detail) "
                        "VALUES (:platform, :url, :error_code, :error_detail) "
                        "ON CONFLICT ON CONSTRAINT uq_platform_url_errors_platform_url "
                        "DO UPDATE SET "
                        "  error_code = EXCLUDED.error_code, "
                        "  error_detail = EXCLUDED.error_detail, "
                        "  last_seen_at = NOW(), "
                        "  failure_count = platform_url_errors.failure_count + 1"
                    ),
                    {
                        "platform": platform,
                        "url": err.get("url", ""),
                        "error_code": err.get("error_code", "unknown"),
                        "error_detail": err.get("error_detail"),
                    },
                )
            db.commit()
            log.info(
                "record_url_errors: recorded %d errors for platform=%s",
                len(errors),
                platform,
            )
    except Exception as exc:
        log.warning("record_url_errors: failed for platform=%s: %s", platform, exc)


def clear_url_errors(platform: str, urls: list[str]) -> None:
    """Remove error records for URLs that produced valid data (page recovered).

    Called after a successful collection to clear suppression for URLs that
    are working again.

    Best-effort: DB failures are logged and do not propagate.

    Args:
        platform: Platform identifier.
        urls: URLs that successfully returned data.
    """
    import logging

    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

    log = logging.getLogger("issue_observatory.workers._task_helpers")

    if not urls:
        return

    try:
        with get_sync_session() as db:
            db.execute(
                text(
                    "DELETE FROM platform_url_errors "
                    "WHERE platform = :platform AND url = ANY(:urls)"
                ),
                {"platform": platform, "urls": urls},
            )
            db.commit()
    except Exception as exc:
        log.warning("clear_url_errors: failed for platform=%s: %s", platform, exc)


# ---------------------------------------------------------------------------
# Tier fallback helper
# ---------------------------------------------------------------------------


def run_with_tier_fallback(
    collector: Any,
    collect_method: str,
    kwargs: dict[str, Any],
    requested_tier_str: str,
    platform: str,
    task_logger: Any = None,
) -> tuple[Any, str]:
    """Run a collection method with automatic tier fallback on credential failure.

    When the requested tier has no available credentials, tries lower tiers
    in order: PREMIUM → MEDIUM → FREE.  Only tiers in the collector's
    ``supported_tiers`` are attempted.

    The collection method is called via ``asyncio.run()`` (suitable for
    synchronous Celery task bodies).

    Args:
        collector: An :class:`ArenaCollector` instance.
        collect_method: Method name to call (e.g. ``"collect_by_terms"``).
        kwargs: Keyword arguments for the collection method.  The ``tier``
            key will be overwritten on each fallback attempt.
        requested_tier_str: Originally requested tier value string.
        platform: Platform name for logging.
        task_logger: Logger instance (defaults to module logger).

    Returns:
        Tuple of ``(result, used_tier_str)`` — the collection result and the
        tier value string that was actually used.

    Raises:
        NoCredentialAvailableError: If no supported tier has credentials.
    """
    import asyncio
    import logging

    from issue_observatory.arenas.base import Tier
    from issue_observatory.core.exceptions import NoCredentialAvailableError

    log = task_logger or logging.getLogger(__name__)

    tier_order = [Tier.PREMIUM, Tier.MEDIUM, Tier.FREE]
    requested_tier = Tier(requested_tier_str)

    try:
        start_idx = tier_order.index(requested_tier)
    except ValueError:
        start_idx = 0

    tiers_to_try = [t for t in tier_order[start_idx:] if t in collector.supported_tiers]

    if not tiers_to_try:
        raise NoCredentialAvailableError(platform=platform, tier=requested_tier_str)

    last_exc: NoCredentialAvailableError | NotImplementedError | None = None
    method = getattr(collector, collect_method)

    for tier in tiers_to_try:
        try:
            kwargs["tier"] = tier
            result = asyncio.run(method(**kwargs))
            if tier != requested_tier:
                log.warning(
                    "%s: fell back from tier=%s to tier=%s due to missing credentials",
                    platform,
                    requested_tier.value,
                    tier.value,
                )
            return result, tier.value
        except NoCredentialAvailableError as exc:
            last_exc = exc
            log.warning(
                "%s: no credential for tier=%s, trying lower tier...",
                platform,
                tier.value,
            )
            continue
        except NotImplementedError as exc:
            last_exc = exc
            log.warning(
                "%s: tier=%s not implemented (%s), trying lower tier...",
                platform,
                tier.value,
                exc,
            )
            continue

    if isinstance(last_exc, NotImplementedError):
        raise NoCredentialAvailableError(
            platform=platform, tier=requested_tier_str
        ) from last_exc
    raise last_exc or NoCredentialAvailableError(
        platform=platform, tier=requested_tier_str
    )


# ---------------------------------------------------------------------------
# Collection attempt reconciliation
# ---------------------------------------------------------------------------


def reconcile_collection_attempts(
    min_age_days: int = 14,
) -> dict[str, int]:
    """Validate collection_attempts against actual content_records data.

    For each valid attempt with ``records_returned > 0`` that is older than
    ``min_age_days``, checks whether at least one matching content record
    still exists in the database.  If no records remain (e.g. due to manual
    deletion or retention policy enforcement), the attempt is marked
    ``is_valid = FALSE`` so the coverage checker no longer trusts it.

    Recent attempts (< ``min_age_days`` old) are skipped because they
    represent current, trustworthy coverage — even if no content records
    exist for a specific search term (which simply means the API returned
    zero results for that term).

    Zero-result attempts (``records_returned = 0``) are also skipped because
    they legitimately indicate "the API was queried and found nothing".

    This runs as a periodic Celery Beat task (weekly by default) to prevent
    stale coverage claims from permanently blocking re-collection.

    The check is efficient: uses ``EXISTS`` with partition-pruning-friendly
    predicates (platform + published_at bounds) and short-circuits per row.

    Args:
        min_age_days: Only reconcile attempts older than this many days.
            Defaults to 14 days to avoid invalidating current coverage data.

    Returns:
        Dict with ``attempts_checked`` and ``attempts_invalidated`` counts.
    """
    import logging

    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

    log = logging.getLogger("issue_observatory.workers._task_helpers")

    checked = 0
    invalidated = 0

    try:
        with get_sync_session() as db:
            # Fetch valid attempts older than min_age_days with records_returned > 0.
            # Recent attempts are trusted regardless of content existence.
            # Zero-result attempts are valid coverage (API returned nothing).
            rows = db.execute(
                text(
                    "SELECT id, platform, input_value, input_type, "
                    "date_from, date_to "
                    "FROM collection_attempts "
                    "WHERE is_valid = TRUE AND records_returned > 0 "
                    "AND attempted_at < NOW() - CAST(:min_age AS interval) "
                    "ORDER BY attempted_at DESC"
                ),
                {"min_age": f"{min_age_days} days"},
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
                        f"SELECT EXISTS("
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
                            f"UPDATE collection_attempts "
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
    except Exception as exc:
        log.error(
            "reconcile_collection_attempts: error: %s",
            exc,
            exc_info=True,
        )

    return {"attempts_checked": checked, "attempts_invalidated": invalidated}


# ---------------------------------------------------------------------------
# "Only collect new" filters
# ---------------------------------------------------------------------------


async def filter_new_terms(
    query_design_id: str,
    platform: str,
    terms: list[str],
) -> list[str]:
    """Return only terms that have no matching content records yet.

    Checks ``search_terms_matched`` on existing content records for the
    given query design and platform, then returns terms not already present.
    """
    if not terms:
        return []

    from sqlalchemy import text

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT DISTINCT unnest(search_terms_matched) "
                "FROM content_records "
                "WHERE query_design_id = CAST(:qd_id AS uuid) "
                "AND platform = :platform"
            ),
            {"qd_id": str(query_design_id), "platform": platform},
        )
        existing = {row[0] for row in result}

    return [t for t in terms if t not in existing]


async def filter_new_actors(
    query_design_id: str,
    platform: str,
    actor_ids: list[str],
    config_key: str | None = None,
) -> list[str]:
    """Return only source list entries not present in the most recent completed run.

    Source list identifiers (usernames, URLs) differ from
    ``author_platform_id`` stored in content records, so matching against
    records is unreliable.  Instead, compare the current source list against
    the snapshot stored on the most recent completed ``CollectionRun`` for
    the same query design.  Only entries absent from that snapshot are
    returned as "new".

    Falls back to returning all ``actor_ids`` when no previous run exists
    (first collection) or when the previous run's config cannot be read.
    """
    if not actor_ids:
        return []

    from sqlalchemy import text

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT arenas_config "
                "FROM collection_runs "
                "WHERE query_design_id = CAST(:qd_id AS uuid) "
                "AND status = 'completed' "
                "ORDER BY created_at DESC "
                "LIMIT 1"
            ),
            {"qd_id": str(query_design_id)},
        )
        row = result.first()

    if row is None or row[0] is None:
        # No previous completed run — everything is new.
        return actor_ids

    prev_config: dict = row[0]

    # Extract previous source list for this platform.
    prev_section = prev_config.get(platform)
    if not isinstance(prev_section, dict) or not config_key:
        # Can't determine previous list — fall back to all.
        return actor_ids

    prev_list = prev_section.get(config_key)
    if not isinstance(prev_list, list):
        # Platform wasn't in the previous run — everything is new.
        return actor_ids

    prev_set = set(prev_list)
    return [a for a in actor_ids if a not in prev_set]


# ---------------------------------------------------------------------------
# Comment collection helpers
# ---------------------------------------------------------------------------


async def fetch_posts_for_comment_collection(
    collection_run_id: str,
    platform: str,
    comments_config: dict,
    project_id: str,
    date_from: Any | None = None,
    date_to: Any | None = None,
) -> list[dict]:
    """Return posts matching the comment collection criteria for a platform.

    Queries all posts in the project for the given platform within the date
    range — not limited to a single collection run. This allows researchers
    to enable comment collection later and still pick up posts from earlier
    runs.

    Modes:
    - ``search_terms``: posts where ``search_terms_matched`` overlaps configured terms.
    - ``source_list_actors``: posts where ``author_id`` is in configured actor lists.
    - ``post_urls``: returns the explicit URLs as-is (no DB query needed).

    Args:
        collection_run_id: UUID of the triggering collection run (used for
            fallback scoping if no date range is available).
        platform: Platform name (e.g. ``"reddit"``, ``"bluesky"``).
        comments_config: The platform's section from ``project.comments_config``.
        project_id: UUID of the project.
        date_from: Start of the date range (from the collection run).
        date_to: End of the date range (from the collection run).

    Returns:
        List of dicts with ``platform_id``, ``url``, ``published_at`` keys.
    """
    from sqlalchemy import Text as SAText
    from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY

    mode = comments_config.get("mode", "search_terms")

    if mode == "post_urls":
        urls = comments_config.get("post_urls") or []
        return [{"platform_id": None, "url": u, "published_at": None} for u in urls if u]

    async with AsyncSessionLocal() as db:
        # Scope to all runs in this project for the given platform
        project_run_ids = (
            select(CollectionRun.id)
            .where(CollectionRun.project_id == project_id)
            .scalar_subquery()
        )

        # Subquery: posts that already have comments collected for them.
        from sqlalchemy import exists
        from sqlalchemy.orm import aliased

        ExistingComment = aliased(UniversalContentRecord)
        has_comments = (
            exists()
            .where(
                ExistingComment.platform == platform,
                ExistingComment.content_type == "comment",
                ExistingComment.raw_metadata["parent_post_id"].astext
                == UniversalContentRecord.platform_id,
            )
        )

        stmt = (
            select(
                UniversalContentRecord.platform_id,
                UniversalContentRecord.url,
                UniversalContentRecord.published_at,
            )
            .where(
                UniversalContentRecord.collection_run_id.in_(project_run_ids),
                UniversalContentRecord.platform == platform,
                UniversalContentRecord.content_type.notin_(["comment", "reply"]),
                ~has_comments,
            )
        )

        # Apply date range filter on published_at
        if date_from is not None:
            stmt = stmt.where(UniversalContentRecord.published_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(UniversalContentRecord.published_at <= date_to)

        if mode == "search_terms":
            configured_terms = comments_config.get("search_terms") or []
            if configured_terms:
                # Filter posts whose search_terms_matched array overlaps with configured terms
                for term in configured_terms:
                    stmt = stmt.where(
                        UniversalContentRecord.search_terms_matched
                        .cast(PG_ARRAY(SAText))
                        .contains([term])
                    )

        elif mode == "source_list_actors":
            actor_list_ids = comments_config.get("actor_list_ids") or []
            if actor_list_ids:
                from issue_observatory.core.models.actors import ActorListMember
                from issue_observatory.core.models.query_design import ActorList

                actor_ids_subq = (
                    select(ActorListMember.actor_id)
                    .join(ActorList, ActorListMember.actor_list_id == ActorList.id)
                    .where(ActorList.id.in_(actor_list_ids))
                    .scalar_subquery()
                )
                stmt = stmt.where(
                    UniversalContentRecord.author_id.in_(actor_ids_subq)
                )

        # Deduplicate by platform_id (same post may appear in multiple runs)
        stmt = stmt.distinct(UniversalContentRecord.platform_id)

        result = await db.execute(stmt)
        rows = result.mappings().all()
        return [
            {
                "platform_id": str(row["platform_id"]) if row["platform_id"] else None,
                "url": row["url"],
                "published_at": row["published_at"].isoformat() if row["published_at"] else None,
            }
            for row in rows
        ]


async def fetch_project_comments_config(project_id: str) -> dict:
    """Fetch the comments_config from a project.

    Args:
        project_id: UUID string of the project.

    Returns:
        The comments_config dict, or empty dict if not found.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project.comments_config).where(Project.id == project_id)
        )
        config = result.scalar_one_or_none()
        return dict(config) if config else {}
