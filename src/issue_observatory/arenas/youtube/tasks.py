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
    """
    try:
        from issue_observatory.core.database import get_sync_session  # noqa: PLC0415

        with get_sync_session() as session:
            from sqlalchemy import text  # noqa: PLC0415

            session.execute(
                text(
                    """
                    UPDATE collection_tasks
                    SET status            = :status,
                        records_collected = :records_collected,
                        error_message     = :error_message,
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
                    "run_id": collection_run_id,
                    "arena": arena,
                },
            )
            session.commit()
    except Exception as exc:  # noqa: BLE001
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
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "youtube: collect_by_terms started — run=%s terms=%d tier=%s",
        collection_run_id,
        len(terms),
        tier,
    )
    _update_task_status(collection_run_id, _ARENA, "running")
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
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
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

    try:
        records = asyncio.run(
            collector.collect_by_terms(
                terms=terms,
                tier=tier_enum,
                date_from=date_from,
                date_to=date_to,
                max_results=max_results,
                language_filter=language_filter,
            )
        )
    except NoCredentialAvailableError as exc:
        msg = f"youtube: all API keys exhausted — no credential available: {exc}"
        logger.critical(msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
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
    except ArenaRateLimitError as exc:
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
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
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

    count = len(records)

    # Persist collected records to the database.
    from issue_observatory.workers._task_helpers import persist_collected_records  # noqa: PLC0415

    inserted, skipped = persist_collected_records(records, collection_run_id, query_design_id)
    logger.info(
        "youtube: collect_by_terms completed — run=%s records=%d inserted=%d skipped=%d",
        collection_run_id,
        count,
        inserted,
        skipped,
    )
    _update_task_status(collection_run_id, _ARENA, "completed", records_collected=inserted)
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


@celery_app.task(
    name="issue_observatory.arenas.youtube.tasks.collect_by_actors",
    bind=True,
    max_retries=5,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=600,
    acks_late=True,
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
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "youtube: collect_by_actors started — run=%s channels=%d tier=%s",
        collection_run_id,
        len(actor_ids),
        tier,
    )
    _update_task_status(collection_run_id, _ARENA, "running")
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
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
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

    try:
        records = asyncio.run(
            collector.collect_by_actors(
                actor_ids=actor_ids,
                tier=tier_enum,
                date_from=date_from,
                date_to=date_to,
                max_results=max_results,
            )
        )
    except NoCredentialAvailableError as exc:
        msg = f"youtube: all API keys exhausted — no credential available: {exc}"
        logger.critical(msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
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
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
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

    count = len(records)

    # Persist collected records to the database.
    from issue_observatory.workers._task_helpers import persist_collected_records  # noqa: PLC0415

    inserted, skipped = persist_collected_records(records, collection_run_id, query_design_id)
    logger.info(
        "youtube: collect_by_actors completed — run=%s records=%d inserted=%d skipped=%d",
        collection_run_id,
        count,
        inserted,
        skipped,
    )
    _update_task_status(collection_run_id, _ARENA, "completed", records_collected=inserted)
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
