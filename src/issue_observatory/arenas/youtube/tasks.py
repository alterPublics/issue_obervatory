"""Celery tasks for the YouTube arena.

Wraps :class:`YouTubeCollector` methods as Celery tasks with automatic retry
behaviour, credential rotation on quota exhaustion, collection run status
tracking, and error reporting.

Task naming follows the project convention::

    issue_observatory.arenas.youtube.tasks.<action>

All tasks are registered in the Celery app via the ``include`` list in
:mod:`issue_observatory.workers.celery_app`.

Retry policy:
- ``ArenaRateLimitError`` (quota exhausted) → rotate credentials via
  ``CredentialPool``, then retry up to ``max_retries=5`` with exponential
  backoff.
- ``NoCredentialAvailableError`` (all keys exhausted) → log CRITICAL,
  update status to "failed", do not retry.
- Other ``ArenaCollectionError`` subclasses → log ERROR, update status to
  "failed", re-raise so Celery marks task as FAILED.

Credential rotation flow:
1. ``ArenaRateLimitError`` is caught in the task.
2. Task calls ``CredentialPool.report_error()`` on the exhausted key.
3. Task calls ``CredentialPool.acquire()`` for a fresh key.
4. If no fresh key → ``NoCredentialAvailableError`` → task fails.
5. If fresh key available → task retries with the new key in context.

Database updates:
- Best-effort via synchronous SQLAlchemy in a ``get_sync_session()`` call.
- DB failures are logged at WARNING and never mask collection outcomes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from issue_observatory.arenas.youtube.collector import YouTubeCollector
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

# Arena constants reused in this module
_ARENA = "social_media"
_PLATFORM = "youtube"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _update_task_status(
    collection_run_id: str,
    arena: str,
    status: str,
    records_collected: int = 0,
    error_message: str | None = None,
    actors_skipped: int = 0,
    skipped_actor_detail: list[dict[str, str]] | None = None,
) -> None:
    """Best-effort update of the ``collection_tasks`` row for this arena.

    Runs the DB update synchronously via ``get_sync_session()``.  Failures
    are logged at WARNING level; they must not mask the collection outcome.

    Args:
        collection_run_id: UUID string of the parent collection run.
        arena: Arena identifier (``"social_media"``).
        status: New status (``"running"`` | ``"completed"`` | ``"failed"``).
        records_collected: Number of records collected.
        error_message: Error description for ``"failed"`` updates.
        actors_skipped: Number of actors skipped due to per-actor errors.
        skipped_actor_detail: List of dicts with actor_id, reason, error.
    """
    try:
        from issue_observatory.core.database import get_sync_session

        with get_sync_session() as session:
            import json

            from sqlalchemy import text

            session.execute(
                text(
                    """
                    UPDATE collection_tasks
                    SET status            = :status,
                        records_collected = GREATEST(records_collected, :records_collected),
                        error_message     = :error_message,
                        actors_skipped    = :actors_skipped,
                        skipped_actor_detail = :skipped_actor_detail,
                        completed_at      = CASE
                            WHEN :status IN ('completed', 'failed') THEN NOW()
                            ELSE completed_at END,
                        started_at        = CASE
                            WHEN :status = 'running' AND started_at IS NULL THEN NOW()
                            ELSE started_at END
                    WHERE collection_run_id = :run_id
                      AND arena             = :arena
                    """
                ),
                {
                    "status": status,
                    "records_collected": records_collected,
                    "error_message": error_message,
                    "actors_skipped": actors_skipped,
                    "skipped_actor_detail": json.dumps(skipped_actor_detail)
                    if skipped_actor_detail
                    else None,
                    "run_id": collection_run_id,
                    "arena": arena,
                },
            )
            session.commit()
    except Exception as exc:
        logger.warning(
            "youtube: failed to update collection_tasks status to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.youtube.tasks.collect_by_terms",
    bind=True,
    max_retries=5,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=600,  # cap backoff at 10 minutes
    acks_late=True,
    # No fixed time limit — records persist incrementally and stale_run_cleanup handles stuck tasks.
)
def youtube_collect_terms(
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
    """Collect YouTube videos for a list of search terms.

    Uses ``search.list`` (100 units/call) followed by ``videos.list`` batch
    enrichment (1 unit/50 videos).  On quota exhaustion, rotates to the next
    available GCP project API key before retrying.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms to query.
        tier: Tier string — only ``"free"`` is valid for YouTube.
        date_from: Optional ISO 8601 ``publishedAfter`` filter.
        date_to: Optional ISO 8601 ``publishedBefore`` filter.
        max_results: Optional upper bound on total records to return.

    Returns:
        Dict with:
        - ``records_collected`` (int): Number of normalized records retrieved.
        - ``status`` (str): ``"completed"`` or ``"failed"``.
        - ``arena`` (str): ``"social_media"``.
        - ``platform`` (str): ``"youtube"``.
        - ``tier`` (str): The tier used.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with credential rotation.
        ArenaCollectionError: Marks the task as FAILED in Celery.
        NoCredentialAvailableError: All API keys exhausted — task fails.
    """
    from issue_observatory.arenas.base import Tier

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    try:
        logger.info(
            "youtube: collect_by_terms started — run=%s terms=%d tier=%s",
            collection_run_id,
            len(terms),
            tier,
        )
        _update_task_status(collection_run_id, _PLATFORM, "running")
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena=_ARENA,
            platform=_PLATFORM,
            status="running",
            records_collected=0,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        try:
            tier_enum = Tier(tier)
        except ValueError:
            msg = f"youtube: invalid tier '{tier}'. Valid values: free, medium, premium."
            logger.error(msg)
            _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena=_ARENA,
                platform=_PLATFORM,
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise ArenaCollectionError(msg, arena=_ARENA, platform=_PLATFORM)

        credential_pool = CredentialPool()
        collector = YouTubeCollector(credential_pool=credential_pool)
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
                platform=_PLATFORM,
                date_from=_dt.fromisoformat(date_from) if isinstance(date_from, str) else date_from,
                date_to=_dt.fromisoformat(date_to) if isinstance(date_to, str) else date_to,
                terms=terms,
            )
            if not gaps:
                logger.info(
                    "youtube: full coverage exists for run=%s — skipping API call, "
                    "will reindex existing records only.",
                    collection_run_id,
                )
                from issue_observatory.workers._task_helpers import (
                    reindex_existing_records,
                )

                linked = reindex_existing_records(
                    platform=_PLATFORM,
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
                    arena=_ARENA,
                    platform=_PLATFORM,
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
            effective_date_from = gaps[0][0].isoformat()
            effective_date_to = gaps[-1][1].isoformat()
            logger.info(
                "youtube: narrowing collection to uncovered range %s — %s (run=%s)",
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
        except NoCredentialAvailableError as exc:
            msg = f"youtube: all API keys exhausted — no credential available: {exc}"
            logger.critical(msg)
            _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena=_ARENA,
                platform=_PLATFORM,
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise
        except ArenaRateLimitError:
            # Attempt credential rotation before Celery retries the task.
            logger.warning(
                "youtube: quota exhausted on collect_by_terms run=%s — attempting credential rotation.",
                collection_run_id,
            )
            # report_error was already called inside the collector; just re-raise
            # so autoretry fires with a fresh CredentialPool on the next attempt.
            raise
        except ArenaCollectionError as exc:
            msg = str(exc)
            logger.error("youtube: collection error for run=%s: %s", collection_run_id, msg)
            _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena=_ARENA,
                platform=_PLATFORM,
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise

        # Persist any records not yet flushed by the sink (fallback path).
        from issue_observatory.workers._task_helpers import (
            persist_collected_records,
            record_collection_attempts_batch,
            reindex_existing_records,
        )

        fallback_inserted, fallback_skipped = 0, 0
        if remaining:
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
            db_count = count_run_platform_records(collection_run_id, "youtube")
            if db_count > 0:
                logger.info("youtube: in-memory counter=0 but DB has %d records — using DB count", db_count)
                inserted = db_count

        # Link existing records from other runs that match these terms/dates.
        linked = reindex_existing_records(
            platform="youtube",
            collection_run_id=collection_run_id,
            query_design_id=query_design_id,
            terms=terms,
            date_from=date_from,
            date_to=date_to,
        )

        # Record successful collection attempts for future pre-checks.
        if date_from and date_to:
            record_collection_attempts_batch(
                platform="youtube",
                collection_run_id=collection_run_id,
                query_design_id=query_design_id,
                inputs=terms,
                input_type="term",
                date_from=date_from,
                date_to=date_to,
                records_returned=inserted,
                per_input_counts=collector.per_input_counts,
            )

        logger.info(
            "youtube: collect_by_terms completed — run=%s emitted=%d inserted=%d "
            "skipped=%d linked=%d",
            collection_run_id,
            collector.batch_stats["emitted"],
            inserted,
            skipped,
            linked,
        )
        _update_task_status(collection_run_id, _PLATFORM, "completed", records_collected=inserted)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena=_ARENA,
            platform=_PLATFORM,
            status="completed",
            records_collected=inserted,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        return {
            "records_collected": inserted,
            "status": "completed",
            "arena": _ARENA,
            "platform": _PLATFORM,
            "tier": tier,
        }
    except Exception as exc:
        msg = f"youtube: unexpected error for run={collection_run_id}: {type(exc).__name__}: {exc}"
        logger.error(msg, exc_info=True)
        _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg[:500])
        publish_task_update(
            redis_url=get_settings().redis_url,
            run_id=collection_run_id,
            arena=_ARENA,
            platform=_PLATFORM,
            status="failed",
            records_collected=0,
            error_message=msg[:500],
            elapsed_seconds=0,
        )
        raise


@celery_app.task(
    name="issue_observatory.arenas.youtube.tasks.collect_by_actors",
    bind=True,
    max_retries=5,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=600,
    acks_late=True,
    # No fixed time limit — records persist incrementally and stale_run_cleanup handles stuck tasks.
)
def youtube_collect_actors(
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
    """Collect YouTube videos from specific channels via RSS feeds.

    Polls the RSS feed for each channel at zero quota cost, then
    batch-enriches discovered video IDs via ``videos.list`` (1 unit per
    50 videos).  On quota exhaustion, rotates to the next API key.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: YouTube channel IDs (format: ``UC...``).
        tier: Tier string — only ``"free"`` is valid for YouTube.
        date_from: Optional ISO 8601 lower bound for publication date.
        date_to: Optional ISO 8601 upper bound for publication date.
        max_results: Optional upper bound on total records to return.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``,
        ``platform``, and ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with credential rotation.
        ArenaCollectionError: Marks the task as FAILED in Celery.
        NoCredentialAvailableError: All API keys exhausted — task fails.
    """
    from issue_observatory.arenas.base import Tier

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    try:
        logger.info(
            "youtube: collect_by_actors started — run=%s channels=%d tier=%s",
            collection_run_id,
            len(actor_ids),
            tier,
        )
        _update_task_status(collection_run_id, _PLATFORM, "running")
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena=_ARENA,
            platform=_PLATFORM,
            status="running",
            records_collected=0,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        try:
            tier_enum = Tier(tier)
        except ValueError:
            msg = f"youtube: invalid tier '{tier}'. Valid values: free, medium, premium."
            logger.error(msg)
            _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena=_ARENA,
                platform=_PLATFORM,
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise ArenaCollectionError(msg, arena=_ARENA, platform=_PLATFORM)

        credential_pool = CredentialPool()
        collector = YouTubeCollector(credential_pool=credential_pool)
        from issue_observatory.workers._task_helpers import make_batch_sink

        sink = make_batch_sink(collection_run_id, query_design_id)
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
                platform=_PLATFORM,
                date_from=_dt.fromisoformat(date_from) if isinstance(date_from, str) else date_from,
                date_to=_dt.fromisoformat(date_to) if isinstance(date_to, str) else date_to,
                actor_ids=actor_ids,
            )
            if not gaps:
                logger.info(
                    "youtube: full coverage exists for run=%s — skipping API call, "
                    "will reindex existing records only.",
                    collection_run_id,
                )
                from issue_observatory.workers._task_helpers import (
                    reindex_existing_records,
                )

                linked = reindex_existing_records(
                    platform=_PLATFORM,
                    collection_run_id=collection_run_id,
                    query_design_id=query_design_id,
                    actor_ids=actor_ids,
                    date_from=date_from,
                    date_to=date_to,
                )
                _update_task_status(
                    collection_run_id, _PLATFORM, "completed", records_collected=0
                )
                publish_task_update(
                    redis_url=_redis_url,
                    run_id=collection_run_id,
                    arena=_ARENA,
                    platform=_PLATFORM,
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
            effective_date_from = gaps[0][0].isoformat()
            effective_date_to = gaps[-1][1].isoformat()
            logger.info(
                "youtube: narrowing collection to uncovered range %s — %s (run=%s)",
                effective_date_from,
                effective_date_to,
                collection_run_id,
            )

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
        except NoCredentialAvailableError as exc:
            msg = f"youtube: all API keys exhausted — no credential available: {exc}"
            logger.critical(msg)
            _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena=_ARENA,
                platform=_PLATFORM,
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise
        except ArenaRateLimitError:
            logger.warning(
                "youtube: quota exhausted on collect_by_actors run=%s — will retry.",
                collection_run_id,
            )
            raise
        except ArenaCollectionError as exc:
            msg = str(exc)
            logger.error("youtube: collection error for run=%s: %s", collection_run_id, msg)
            _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena=_ARENA,
                platform=_PLATFORM,
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise

        # Persist any records not yet flushed by the sink (fallback path).
        from issue_observatory.workers._task_helpers import (
            persist_collected_records,
            record_collection_attempts_batch,
            reindex_existing_records,
        )

        fallback_inserted, fallback_skipped = 0, 0
        if remaining:
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
            db_count = count_run_platform_records(collection_run_id, "youtube")
            if db_count > 0:
                logger.info("youtube: in-memory counter=0 but DB has %d records — using DB count", db_count)
                inserted = db_count

        # Link existing records from other runs that match these actors/dates.
        linked = reindex_existing_records(
            platform="youtube",
            collection_run_id=collection_run_id,
            query_design_id=query_design_id,
            actor_ids=actor_ids,
            date_from=date_from,
            date_to=date_to,
        )

        # Record successful collection attempts for future pre-checks.
        if date_from and date_to:
            record_collection_attempts_batch(
                platform="youtube",
                collection_run_id=collection_run_id,
                query_design_id=query_design_id,
                inputs=actor_ids,
                input_type="actor",
                date_from=date_from,
                date_to=date_to,
                records_returned=inserted,
                per_input_counts=collector.per_input_counts,
            )

        skipped_actors = collector.skipped_actors
        logger.info(
            "youtube: collect_by_actors completed — run=%s emitted=%d inserted=%d "
            "dupes_skipped=%d actors_skipped=%d linked=%d",
            collection_run_id,
            collector.batch_stats["emitted"],
            inserted,
            skipped,
            len(skipped_actors),
            linked,
        )
        _update_task_status(
            collection_run_id,
            _PLATFORM,
            "completed",
            records_collected=inserted,
            actors_skipped=len(skipped_actors),
            skipped_actor_detail=skipped_actors or None,
        )
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena=_ARENA,
            platform=_PLATFORM,
            status="completed",
            records_collected=inserted,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        return {
            "records_collected": inserted,
            "status": "completed",
            "arena": _ARENA,
            "platform": _PLATFORM,
            "tier": tier,
            "actors_skipped": len(skipped_actors),
        }
    except Exception as exc:
        msg = f"youtube: unexpected error for run={collection_run_id}: {type(exc).__name__}: {exc}"
        logger.error(msg, exc_info=True)
        _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg[:500])
        publish_task_update(
            redis_url=get_settings().redis_url,
            run_id=collection_run_id,
            arena=_ARENA,
            platform=_PLATFORM,
            status="failed",
            records_collected=0,
            error_message=msg[:500],
            elapsed_seconds=0,
        )
        raise


@celery_app.task(
    name="issue_observatory.arenas.youtube.tasks.health_check",
    bind=False,
)
def youtube_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the YouTube arena.

    Delegates to :meth:`YouTubeCollector.health_check`, which calls
    ``videos.list`` with a known video ID (1 quota unit) to verify that the
    API key is valid and the service is reachable.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    credential_pool = CredentialPool()
    collector = YouTubeCollector(credential_pool=credential_pool)
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info(
        "youtube: health_check status=%s", result.get("status", "unknown")
    )
    return result


# ---------------------------------------------------------------------------
# Comments collection task
# ---------------------------------------------------------------------------

_COMMENTS_ARENA = "youtube_comments"


@celery_app.task(
    name="issue_observatory.arenas.youtube.tasks.collect_comments",
    bind=True,
    max_retries=5,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=600,
    acks_late=True,
)
def youtube_collect_comments(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    post_ids: list[dict],
    tier: str = "free",
    max_comments_per_post: int = 100,
    depth: int = 0,
    **_extra: Any,
) -> dict[str, Any]:
    """Collect comments for a list of YouTube videos via ``commentThreads.list``.

    For each video in ``post_ids`` the task calls ``collect_comments()`` on a
    :class:`YouTubeCollector` instance, paginating with ``nextPageToken`` until
    ``max_comments_per_post`` is reached.  When ``depth=1`` replies from each
    thread's ``replies.comments`` list are included at no extra API cost.

    On quota exhaustion (``ArenaRateLimitError``) the task is automatically
    retried up to ``max_retries=5`` times with exponential back-off capped at
    10 minutes.  Each retry constructs a fresh :class:`CredentialPool` so that
    a different API key is used for the next attempt.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        post_ids: List of dicts each containing ``"platform_id"`` (YouTube
            video ID string).
        tier: Tier string — only ``"free"`` is valid for YouTube.
        max_comments_per_post: Maximum comment threads to collect per video.
        depth: Reply depth — ``0`` = top-level only, ``1`` = include replies.

    Returns:
        Dict with:
        - ``records_collected`` (int): Number of normalized records saved.
        - ``status`` (str): ``"completed"`` or ``"failed"``.
        - ``arena`` (str): ``"youtube_comments"``.
        - ``platform`` (str): ``"youtube"``.
        - ``tier`` (str): The tier used.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with credential rotation.
        ArenaCollectionError: Marks the task as FAILED in Celery.
        NoCredentialAvailableError: All API keys exhausted — task fails.
    """
    from issue_observatory.arenas.base import Tier

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    try:
        logger.info(
            "youtube: collect_comments started — run=%s videos=%d tier=%s depth=%d",
            collection_run_id,
            len(post_ids),
            tier,
            depth,
        )
        _update_task_status(collection_run_id, _COMMENTS_ARENA, "running")
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena=_COMMENTS_ARENA,
            platform=_PLATFORM,
            status="running",
            records_collected=0,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        try:
            tier_enum = Tier(tier)
        except ValueError:
            msg = f"youtube: invalid tier '{tier}'. Valid values: free, medium, premium."
            logger.error(msg)
            _update_task_status(
                collection_run_id, _COMMENTS_ARENA, "failed", error_message=msg
            )
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena=_COMMENTS_ARENA,
                platform=_PLATFORM,
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise ArenaCollectionError(msg, arena=_COMMENTS_ARENA, platform=_PLATFORM)

        credential_pool = CredentialPool()
        collector = YouTubeCollector(credential_pool=credential_pool)
        from issue_observatory.workers._task_helpers import make_batch_sink

        sink = make_batch_sink(collection_run_id, query_design_id)
        collector.configure_batch_persistence(
            sink=sink, batch_size=100, collection_run_id=collection_run_id
        )

        try:
            comment_records = asyncio.run(
                collector.collect_comments(
                    post_ids=post_ids,
                    tier=tier_enum,
                    max_comments_per_post=max_comments_per_post,
                    depth=depth,
                )
            )
        except NoCredentialAvailableError as exc:
            msg = f"youtube: all API keys exhausted during collect_comments: {exc}"
            logger.critical(msg)
            _update_task_status(
                collection_run_id, _COMMENTS_ARENA, "failed", error_message=msg
            )
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena=_COMMENTS_ARENA,
                platform=_PLATFORM,
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise
        except ArenaRateLimitError:
            logger.warning(
                "youtube: quota exhausted on collect_comments run=%s — will retry.",
                collection_run_id,
            )
            raise
        except ArenaCollectionError as exc:
            msg = str(exc)
            logger.error(
                "youtube: collection error during collect_comments run=%s: %s",
                collection_run_id,
                msg,
            )
            _update_task_status(
                collection_run_id, _COMMENTS_ARENA, "failed", error_message=msg
            )
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena=_COMMENTS_ARENA,
                platform=_PLATFORM,
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise

        # Persist any records not yet flushed by the sink (fallback path).
        from issue_observatory.workers._task_helpers import (
            persist_collected_records,
        )

        fallback_inserted, _fallback_skipped = 0, 0
        if comment_records:
            fallback_inserted, _fallback_skipped = persist_collected_records(
                comment_records, collection_run_id, query_design_id
            )
        inserted = collector.batch_stats["inserted"] + fallback_inserted

        # Fallback: if in-memory counters lost track, use the actual DB count.
        if inserted == 0 and comment_records:
            from issue_observatory.workers._task_helpers import (
                count_run_platform_records,
            )

            db_count = count_run_platform_records(collection_run_id, _PLATFORM)
            if db_count > 0:
                logger.info(
                    "youtube: collect_comments in-memory counter=0 but DB has %d records",
                    db_count,
                )
                inserted = db_count

        logger.info(
            "youtube: collect_comments completed — run=%s inserted=%d videos=%d",
            collection_run_id,
            inserted,
            len(post_ids),
        )
        _update_task_status(
            collection_run_id, _COMMENTS_ARENA, "completed", records_collected=inserted
        )
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena=_COMMENTS_ARENA,
            platform=_PLATFORM,
            status="completed",
            records_collected=inserted,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        return {
            "records_collected": inserted,
            "status": "completed",
            "arena": _COMMENTS_ARENA,
            "platform": _PLATFORM,
            "tier": tier,
        }
    except Exception as exc:
        msg = (
            f"youtube: unexpected error in collect_comments run={collection_run_id}: "
            f"{type(exc).__name__}: {exc}"
        )
        logger.error(msg, exc_info=True)
        _update_task_status(
            collection_run_id, _COMMENTS_ARENA, "failed", error_message=msg[:500]
        )
        publish_task_update(
            redis_url=get_settings().redis_url,
            run_id=collection_run_id,
            arena=_COMMENTS_ARENA,
            platform=_PLATFORM,
            status="failed",
            records_collected=0,
            error_message=msg[:500],
            elapsed_seconds=0,
        )
        raise
