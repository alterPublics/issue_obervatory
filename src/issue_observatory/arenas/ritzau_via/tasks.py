"""Celery tasks for the Via Ritzau arena.

Wraps :class:`RitzauViaCollector` methods as Celery tasks with automatic retry
behaviour and collection run status tracking.

Task naming::

    issue_observatory.arenas.ritzau_via.tasks.<action>

Via Ritzau is a free, unauthenticated API with no published rate limits.
NoCredentialAvailableError should never occur for this arena.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from issue_observatory.arenas.ritzau_via.collector import RitzauViaCollector
from issue_observatory.config.settings import get_settings
from issue_observatory.core.event_bus import elapsed_since, publish_task_update
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
)
from issue_observatory.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


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
        arena: Arena identifier (``"ritzau_via"``).
        status: New status (``"running"`` | ``"completed"`` | ``"failed"``).
        records_collected: Number of records collected.
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
            "ritzau_via: failed to update collection_tasks to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.ritzau_via.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
    # No fixed time limit — records persist incrementally and stale_run_cleanup handles stuck tasks.
)
def ritzau_via_collect_terms(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    terms: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
    language_filter: list[str] | None = None,
    **_extra: Any,
) -> dict[str, Any]:
    """Collect Via Ritzau press releases for a list of search terms.

    Applies ``language=da`` filter automatically.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search keywords to query against release titles and bodies.
        tier: Tier string — always ``"free"`` for Via Ritzau.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
        max_results: Optional cap on total records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "ritzau_via: collect_by_terms started — run=%s terms=%d",
        collection_run_id,
        len(terms),
    )
    _update_task_status(collection_run_id, "ritzau_via", "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="news_media",
        platform="ritzau_via",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    collector = RitzauViaCollector()

    # NOTE: Via Ritzau is FORWARD_ONLY — it serves live press releases and
    # does not support date-range filtering.  Coverage pre-check is
    # intentionally skipped because the API always returns current content.

    from issue_observatory.workers._task_helpers import make_batch_sink

    sink = make_batch_sink(collection_run_id, query_design_id)
    collector.configure_batch_persistence(sink=sink, batch_size=100, collection_run_id=collection_run_id)

    try:
        remaining = asyncio.run(
            collector.collect_by_terms(
                terms=terms,
                tier=Tier.FREE,
                date_from=date_from,
                date_to=date_to,
                max_results=max_results,
                language_filter=language_filter,
            )
        )
    except ArenaRateLimitError:
        logger.warning(
            "ritzau_via: rate limited on collect_by_terms for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error("ritzau_via: collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, "ritzau_via", "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="news_media",
            platform="ritzau_via",
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
        db_count = count_run_platform_records(collection_run_id, "ritzau_via")
        if db_count > 0:
            logger.info("ritzau_via: in-memory counter=0 but DB has %d records — using DB count", db_count)
            inserted = db_count

    logger.info(
        "ritzau_via: collect_by_terms completed — run=%s emitted=%d inserted=%d skipped=%d",
        collection_run_id,
        collector.batch_stats["emitted"],
        inserted,
        skipped,
    )
    _update_task_status(collection_run_id, "ritzau_via", "completed", records_collected=inserted)
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="news_media",
        platform="ritzau_via",
        status="completed",
        records_collected=inserted,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )
    return {
        "records_collected": inserted,
        "status": "completed",
        "arena": "news_media",
        "tier": "free",
    }


@celery_app.task(
    name="issue_observatory.arenas.ritzau_via.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
    # No fixed time limit — records persist incrementally and stale_run_cleanup handles stuck tasks.
)
def ritzau_via_collect_actors(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    actor_ids: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
    **_extra: Any,
) -> dict[str, Any]:
    """Collect Via Ritzau press releases from specific publishers.

    Actor IDs are Via Ritzau publisher IDs (integer strings).

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: Via Ritzau publisher IDs (e.g. ``["12345"]``).
        tier: Tier string — always ``"free"`` for Via Ritzau.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
        max_results: Optional cap on total records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry.
        ArenaCollectionError: Marks the task as FAILED.
    """
    from issue_observatory.arenas.base import Tier

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "ritzau_via: collect_by_actors started — run=%s publishers=%d",
        collection_run_id,
        len(actor_ids),
    )
    _update_task_status(collection_run_id, "ritzau_via", "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="news_media",
        platform="ritzau_via",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    collector = RitzauViaCollector()

    # NOTE: Via Ritzau is FORWARD_ONLY — coverage pre-check skipped.
    # See collect_by_terms for explanation.

    from issue_observatory.workers._task_helpers import make_batch_sink

    sink = make_batch_sink(collection_run_id, query_design_id)
    collector.configure_batch_persistence(sink=sink, batch_size=100, collection_run_id=collection_run_id)

    try:
        remaining = asyncio.run(
            collector.collect_by_actors(
                actor_ids=actor_ids,
                tier=Tier.FREE,
                date_from=date_from,
                date_to=date_to,
                max_results=max_results,
            )
        )
    except ArenaRateLimitError:
        logger.warning(
            "ritzau_via: rate limited on collect_by_actors for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error(
            "ritzau_via: actor collection error for run=%s: %s", collection_run_id, msg
        )
        _update_task_status(collection_run_id, "ritzau_via", "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="news_media",
            platform="ritzau_via",
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
        db_count = count_run_platform_records(collection_run_id, "ritzau_via")
        if db_count > 0:
            logger.info("ritzau_via: in-memory counter=0 but DB has %d records — using DB count", db_count)
            inserted = db_count

    logger.info(
        "ritzau_via: collect_by_actors completed — run=%s emitted=%d inserted=%d skipped=%d",
        collection_run_id,
        collector.batch_stats["emitted"],
        inserted,
        skipped,
    )
    _update_task_status(
        collection_run_id, "ritzau_via", "completed", records_collected=inserted
    )
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="news_media",
        platform="ritzau_via",
        status="completed",
        records_collected=inserted,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )
    return {
        "records_collected": inserted,
        "status": "completed",
        "arena": "news_media",
        "tier": "free",
    }


@celery_app.task(
    name="issue_observatory.arenas.ritzau_via.tasks.health_check",
    bind=False,
)
def ritzau_via_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the Via Ritzau arena.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = RitzauViaCollector()
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info("ritzau_via: health_check status=%s", result.get("status", "unknown"))
    return result
