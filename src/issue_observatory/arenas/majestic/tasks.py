"""Celery tasks for the Majestic backlink intelligence arena.

Wraps :class:`~issue_observatory.arenas.majestic.collector.MajesticCollector`
methods as Celery tasks with automatic retry behaviour and collection run
status tracking.

Task naming convention::

    issue_observatory.arenas.majestic.tasks.<action>

Retry policy:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff
  (up to ``max_retries=3``), capped at 5 minutes between retries.
- ``ArenaCollectionError`` is logged and re-raised so Celery marks the task
  FAILED (this includes budget exhaustion for Majestic).
- ``NoCredentialAvailableError`` is logged and re-raised; Celery marks FAILED.

Note on tier strings:
    Task arguments carry tier as a plain string (``"premium"``).
    The :class:`~issue_observatory.arenas.base.Tier` enum is reconstructed
    inside each task to keep Celery arguments JSON-serializable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from issue_observatory.arenas.majestic.collector import MajesticCollector
from issue_observatory.config.settings import get_settings
from issue_observatory.core.credential_pool import CredentialPool
from issue_observatory.core.event_bus import elapsed_since, publish_task_update
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_ARENA = "web"
_PLATFORM = "majestic"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _update_task_status(
    collection_run_id: str,
    arena: str,
    status: str,
    records_collected: int = 0,
    error_message: str | None = None,
) -> None:
    """Best-effort update of the ``collection_tasks`` row for this arena.

    Args:
        collection_run_id: UUID string of the parent collection run.
        arena: Arena identifier.
        status: New status value (``"running"``, ``"completed"``, ``"failed"``).
        records_collected: Number of records collected so far.
        error_message: Error description for failed updates.
    """
    try:
        from issue_observatory.core.database import get_sync_session

        with get_sync_session() as session:
            from sqlalchemy import text

            session.execute(
                text(
                    """
                    UPDATE collection_tasks
                    SET status = :status,
                        records_collected = GREATEST(records_collected, :records_collected),
                        error_message = :error_message,
                        completed_at = CASE WHEN :status IN ('completed', 'failed')
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
                    "error_message": error_message,
                    "run_id": collection_run_id,
                    "arena": arena,
                },
            )
            session.commit()
    except Exception as exc:
        logger.warning(
            "majestic: failed to update collection_tasks status to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.majestic.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
    # No fixed time limit — records persist incrementally and stale_run_cleanup handles stuck tasks.
)
def majestic_collect_terms(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    terms: list[str],
    tier: str = "premium",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
    language_filter: list[str] | None = None,
    **_extra: Any,
) -> dict[str, Any]:
    """Collect domain-level metrics for a list of domain names or URLs.

    Each term is treated as a domain name (or a URL from which the domain
    is extracted).  Returns ``content_type="domain_metrics"`` records.

    Only ``"premium"`` tier is accepted.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Domain names or URLs to analyse.
            Example: ``["dr.dk", "tv2.dk", "https://politiken.dk/"]``.
        tier: Must be ``"premium"``.
        date_from: Unused — Majestic does not filter domain metrics by date.
        date_to: Unused.
        max_results: Upper bound on returned records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED in Celery.
        NoCredentialAvailableError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "majestic: collect_by_terms started — run=%s terms=%d tier=%s",
        collection_run_id,
        len(terms),
        tier,
    )
    _update_task_status(collection_run_id, _PLATFORM, "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="web",
        platform="majestic",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"majestic: invalid tier '{tier}'. Only 'premium' is supported."
        logger.error(msg)
        _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="web",
            platform="majestic",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise ArenaCollectionError(msg, arena=_ARENA, platform=_PLATFORM)

    credential_pool = CredentialPool()
    collector = MajesticCollector(credential_pool=credential_pool)

    from issue_observatory.workers._task_helpers import make_batch_sink

    sink = make_batch_sink(collection_run_id, query_design_id, terms=terms)
    collector.configure_batch_persistence(sink=sink, batch_size=100, collection_run_id=collection_run_id)

    # Check if force_recollect is set (opt-out from coverage check)
    force_recollect = _extra.get("force_recollect", False)

    # Pre-collection coverage check: narrow date range to uncovered gaps
    effective_date_from = date_from
    effective_date_to = date_to
    if not force_recollect and date_from and date_to:
        from datetime import datetime as _dt

        from issue_observatory.core.coverage_checker import (
            check_existing_coverage,
        )

        gaps = check_existing_coverage(
            platform="majestic",
            date_from=_dt.fromisoformat(date_from) if isinstance(date_from, str) else date_from,
            date_to=_dt.fromisoformat(date_to) if isinstance(date_to, str) else date_to,
            terms=terms,
        )
        if not gaps:
            logger.info(
                "majestic: full coverage exists for run=%s — skipping API call, "
                "will reindex existing records only.",
                collection_run_id,
            )
            from issue_observatory.workers._task_helpers import (
                reindex_existing_records,
            )

            linked = reindex_existing_records(
                platform="majestic",
                collection_run_id=collection_run_id,
                query_design_id=query_design_id,
                terms=terms,
                date_from=date_from,
                date_to=date_to,
            )
            _update_task_status(
                collection_run_id, _PLATFORM, "completed", records_collected=0
            )
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="web",
                platform="majestic",
                status="completed",
                records_collected=0,
                error_message=None,
                elapsed_seconds=elapsed_since(_task_start),
            )
            return {
                "records_collected": 0,
                "records_linked": linked,
                "status": "completed",
                "arena": _ARENA,
                "tier": tier,
                "coverage_skip": True,
            }
        # Use the first gap's boundaries as the narrowed date range
        effective_date_from = gaps[0][0].isoformat()
        effective_date_to = gaps[-1][1].isoformat()
        logger.info(
            "majestic: narrowing collection to uncovered range %s — %s (run=%s)",
            effective_date_from,
            effective_date_to,
            collection_run_id,
        )

    try:
        remaining = asyncio.run(
            collector.collect_by_terms(
                terms=terms,
                tier=tier_enum,
                date_from=effective_date_from,
                date_to=effective_date_to,
                max_results=max_results,
                language_filter=language_filter,
            )
        )
    except ArenaRateLimitError:
        logger.warning(
            "majestic: rate limited on collect_by_terms for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except (ArenaCollectionError, NoCredentialAvailableError) as exc:
        msg = str(exc)
        logger.error(
            "majestic: collection error for run=%s: %s", collection_run_id, msg
        )
        _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="web",
            platform="majestic",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise

    fallback_inserted, fallback_skipped = 0, 0
    if remaining:
        from issue_observatory.workers._task_helpers import (
            persist_collected_records,
        )

        fallback_inserted, fallback_skipped = persist_collected_records(
            remaining, collection_run_id, query_design_id, terms=terms
        )
    inserted = collector.batch_stats["inserted"] + fallback_inserted
    skipped = collector.batch_stats["skipped"] + fallback_skipped

    # Fallback: if in-memory counters lost track, use the actual DB count.
    if inserted == 0:
        from issue_observatory.workers._task_helpers import (
            count_run_platform_records,
        )
        db_count = count_run_platform_records(collection_run_id, "majestic")
        if db_count > 0:
            logger.info("majestic: in-memory counter=0 but DB has %d records — using DB count", db_count)
            inserted = db_count

    # Link existing records from other runs that match these terms/dates.
    from issue_observatory.workers._task_helpers import (
        record_collection_attempts_batch,
        reindex_existing_records,
    )

    linked = reindex_existing_records(
        platform="majestic",
        collection_run_id=collection_run_id,
        query_design_id=query_design_id,
        terms=terms,
        date_from=date_from,
        date_to=date_to,
    )

    # Record collection attempt metadata.
    record_collection_attempts_batch(
        platform="majestic",
        collection_run_id=collection_run_id,
        query_design_id=query_design_id,
        inputs=terms,
        input_type="term",
        date_from=date_from or "",
        date_to=date_to or "",
        records_returned=inserted,
        per_input_counts=collector.per_input_counts,
    )

    logger.info(
        "majestic: collect_by_terms completed — run=%s emitted=%d inserted=%d "
        "skipped=%d linked=%d",
        collection_run_id,
        collector.batch_stats["emitted"],
        inserted,
        skipped,
        linked,
    )
    _update_task_status(
        collection_run_id, _PLATFORM, "completed", records_collected=inserted
    )

    return {
        "records_collected": inserted,
        "status": "completed",
        "arena": _ARENA,
        "tier": tier,
    }


@celery_app.task(
    name="issue_observatory.arenas.majestic.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
    # No fixed time limit — records persist incrementally and stale_run_cleanup handles stuck tasks.
)
def majestic_collect_actors(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    actor_ids: list[str],
    tier: str = "premium",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
    **_extra: Any,
) -> dict[str, Any]:
    """Collect domain metrics and individual backlinks for domain actor IDs.

    Actor IDs are domain names.  For each domain the task fetches domain-level
    metrics (``GetIndexItemInfo``) and up to
    ``MAJESTIC_MAX_BACKLINKS_PER_DOMAIN`` individual backlinks
    (``GetBackLinkData``, Mode=1: one per referring domain).

    Only ``"premium"`` tier is accepted.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: List of domain names.  Example: ``["dr.dk", "tv2.dk"]``.
        tier: Must be ``"premium"``.
        date_from: ISO 8601 start date for backlink filtering (optional).
        date_to: ISO 8601 end date for backlink filtering (optional).
        max_results: Upper bound on total returned records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED in Celery.
        NoCredentialAvailableError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "majestic: collect_by_actors started — run=%s actors=%d tier=%s",
        collection_run_id,
        len(actor_ids),
        tier,
    )
    _update_task_status(collection_run_id, _PLATFORM, "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="web",
        platform="majestic",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"majestic: invalid tier '{tier}'. Only 'premium' is supported."
        logger.error(msg)
        _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="web",
            platform="majestic",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise ArenaCollectionError(msg, arena=_ARENA, platform=_PLATFORM)

    credential_pool = CredentialPool()
    collector = MajesticCollector(credential_pool=credential_pool)

    from issue_observatory.workers._task_helpers import make_batch_sink

    sink = make_batch_sink(collection_run_id, query_design_id)
    collector.configure_batch_persistence(sink=sink, batch_size=100, collection_run_id=collection_run_id)

    # --- Pre-collection coverage check ---
    force_recollect = _extra.get("force_recollect", False)
    effective_date_from = date_from
    effective_date_to = date_to

    if not force_recollect and date_from and date_to:
        from datetime import datetime as _dt

        from issue_observatory.core.coverage_checker import check_existing_coverage

        gaps = check_existing_coverage(
            platform="majestic",
            date_from=_dt.fromisoformat(date_from),
            date_to=_dt.fromisoformat(date_to),
            actor_ids=actor_ids,
        )
        if not gaps:
            logger.info(
                "majestic: full coverage exists for run=%s — skipping API call",
                collection_run_id,
            )
            _update_task_status(
                collection_run_id, _PLATFORM, "completed", records_collected=0
            )
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="web",
                platform="majestic",
                status="completed",
                records_collected=0,
                error_message=None,
                elapsed_seconds=elapsed_since(_task_start),
            )
            return {
                "records_collected": 0,
                "status": "completed",
                "arena": _ARENA,
                "tier": tier,
                "coverage_skip": True,
            }
        effective_date_from = gaps[0][0].isoformat()
        effective_date_to = gaps[-1][1].isoformat()

    try:
        remaining = asyncio.run(
            collector.collect_by_actors(
                actor_ids=actor_ids,
                tier=tier_enum,
                date_from=effective_date_from,
                date_to=effective_date_to,
                max_results=max_results,
            )
        )
    except ArenaRateLimitError:
        logger.warning(
            "majestic: rate limited on collect_by_actors for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except (ArenaCollectionError, NoCredentialAvailableError) as exc:
        msg = str(exc)
        logger.error(
            "majestic: collection error for run=%s: %s", collection_run_id, msg
        )
        _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="web",
            platform="majestic",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise

    fallback_inserted, fallback_skipped = 0, 0
    if remaining:
        from issue_observatory.workers._task_helpers import (
            persist_collected_records,
        )

        fallback_inserted, fallback_skipped = persist_collected_records(
            remaining, collection_run_id, query_design_id
        )
    inserted = collector.batch_stats["inserted"] + fallback_inserted
    skipped = collector.batch_stats["skipped"] + fallback_skipped

    # Fallback: if in-memory counters lost track, use the actual DB count.
    if inserted == 0:
        from issue_observatory.workers._task_helpers import (
            count_run_platform_records,
        )
        db_count = count_run_platform_records(collection_run_id, "majestic")
        if db_count > 0:
            logger.info("majestic: in-memory counter=0 but DB has %d records — using DB count", db_count)
            inserted = db_count

    # Link existing records from other runs that match these actors/dates.
    from issue_observatory.workers._task_helpers import reindex_existing_records

    linked = reindex_existing_records(
        platform="majestic",
        collection_run_id=collection_run_id,
        query_design_id=query_design_id,
        actor_ids=actor_ids,
        date_from=date_from,
        date_to=date_to,
    )

    # Record collection attempt metadata.
    if date_from and date_to:
        from issue_observatory.workers._task_helpers import (
            record_collection_attempts_batch,
        )

        record_collection_attempts_batch(
            platform="majestic",
            collection_run_id=collection_run_id,
            query_design_id=query_design_id,
            inputs=actor_ids,
            input_type="actor",
            date_from=date_from,
            date_to=date_to,
            records_returned=inserted,
            per_input_counts=collector.per_input_counts,
        )

    logger.info(
        "majestic: collect_by_actors completed — run=%s emitted=%d inserted=%d "
        "skipped=%d linked=%d",
        collection_run_id,
        collector.batch_stats["emitted"],
        inserted,
        skipped,
        linked,
    )
    _update_task_status(
        collection_run_id, _PLATFORM, "completed", records_collected=inserted
    )

    return {
        "records_collected": inserted,
        "status": "completed",
        "arena": _ARENA,
        "tier": tier,
    }


@celery_app.task(
    name="issue_observatory.arenas.majestic.tasks.health_check",
    bind=False,
)
def majestic_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the Majestic arena.

    Delegates to :meth:`~MajesticCollector.health_check`, which issues
    ``GetIndexItemInfo`` for ``dr.dk`` and verifies a Trust Flow > 0.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``trust_flow``, ``ref_domains``,
        and ``detail``.
    """
    credential_pool = CredentialPool()
    collector = MajesticCollector(credential_pool=credential_pool)
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info(
        "majestic: health_check status=%s trust_flow=%s",
        result.get("status", "unknown"),
        result.get("trust_flow"),
    )
    return result
