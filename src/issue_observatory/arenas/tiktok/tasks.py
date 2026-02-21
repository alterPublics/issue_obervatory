"""Celery tasks for the TikTok arena.

Wraps :class:`TikTokCollector` methods as Celery tasks with automatic retry
behaviour, collection run status tracking, and error reporting.

Task naming::

    issue_observatory.arenas.tiktok.tasks.<action>

Retry policy:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff
  up to ``max_retries=3``.
- ``ArenaAuthError`` triggers one retry after credential refresh.
- Other ``ArenaCollectionError`` subclasses are logged and re-raised.

Engagement lag note:
    TikTok's Research API engagement metrics (view_count, like_count, etc.)
    require up to 10 days to stabilize. The ``tiktok_refresh_engagement``
    task skeleton is provided for Phase 3 implementation of scheduled
    engagement metric re-collection.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from issue_observatory.arenas.tiktok.collector import TikTokCollector
from issue_observatory.config.settings import get_settings
from issue_observatory.core.event_bus import elapsed_since, publish_task_update
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
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
        arena: Arena identifier (``"tiktok"``).
        status: New status (``"running"`` | ``"completed"`` | ``"failed"``).
        records_collected: Number of records collected.
        error_message: Error description for failed updates.
    """
    try:
        from issue_observatory.core.database import get_sync_session  # noqa: PLC0415

        with get_sync_session() as session:
            from sqlalchemy import text  # noqa: PLC0415

            session.execute(
                text(
                    """
                    UPDATE collection_tasks
                    SET status = :status,
                        records_collected = :records_collected,
                        error_message = :error_message,
                        completed_at = CASE WHEN :status IN ('completed', 'failed')
                                            THEN NOW() ELSE completed_at END,
                        started_at   = CASE WHEN :status = 'running' AND started_at IS NULL
                                            THEN NOW() ELSE started_at END
                    WHERE collection_run_id = :run_id AND arena = :arena
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
            "tiktok: failed to update collection_tasks to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.tiktok.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def tiktok_collect_terms(
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
    """Collect TikTok videos for a list of search terms.

    Applies ``region_code: "DK"`` filter automatically. Date ranges longer
    than 30 days are split into 30-day windows by the collector.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms to query.
        tier: Tier string — always ``"free"`` for TikTok in Phase 1.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
        max_results: Optional cap on total records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "tiktok: collect_by_terms started — run=%s terms=%d",
        collection_run_id,
        len(terms),
    )
    _update_task_status(collection_run_id, "tiktok", "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="tiktok",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    collector = TikTokCollector()

    try:
        records = asyncio.run(
            collector.collect_by_terms(
                terms=terms,
                tier=Tier.FREE,
                date_from=date_from,
                date_to=date_to,
                max_results=max_results,
                language_filter=language_filter,
            )
        )
    except NoCredentialAvailableError as exc:
        msg = f"tiktok: no credential available: {exc}"
        logger.error(msg)
        _update_task_status(collection_run_id, "tiktok", "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="tiktok",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise ArenaCollectionError(msg, arena="social_media", platform="tiktok") from exc
    except ArenaRateLimitError:
        logger.warning(
            "tiktok: rate limited on collect_by_terms for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except (ArenaAuthError, ArenaCollectionError) as exc:
        msg = str(exc)
        logger.error("tiktok: collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, "tiktok", "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="tiktok",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise

    count = len(records)
    logger.info(
        "tiktok: collect_by_terms completed — run=%s records=%d",
        collection_run_id,
        count,
    )
    _update_task_status(collection_run_id, "tiktok", "completed", records_collected=count)
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="tiktok",
        status="completed",
        records_collected=count,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )
    return {
        "records_collected": count,
        "status": "completed",
        "arena": "social_media",
        "tier": "free",
    }


@celery_app.task(
    name="issue_observatory.arenas.tiktok.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def tiktok_collect_actors(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    actor_ids: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
) -> dict[str, Any]:
    """Collect TikTok videos published by specific actors (usernames).

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: TikTok usernames (without leading ``@``).
        tier: Tier string — always ``"free"`` for TikTok in Phase 1.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
        max_results: Optional cap on total records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "tiktok: collect_by_actors started — run=%s actors=%d",
        collection_run_id,
        len(actor_ids),
    )
    _update_task_status(collection_run_id, "tiktok", "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="tiktok",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    collector = TikTokCollector()

    try:
        records = asyncio.run(
            collector.collect_by_actors(
                actor_ids=actor_ids,
                tier=Tier.FREE,
                date_from=date_from,
                date_to=date_to,
                max_results=max_results,
            )
        )
    except NoCredentialAvailableError as exc:
        msg = f"tiktok: no credential available: {exc}"
        logger.error(msg)
        _update_task_status(collection_run_id, "tiktok", "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="tiktok",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise ArenaCollectionError(msg, arena="social_media", platform="tiktok") from exc
    except ArenaRateLimitError:
        logger.warning(
            "tiktok: rate limited on collect_by_actors for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except (ArenaAuthError, ArenaCollectionError) as exc:
        msg = str(exc)
        logger.error("tiktok: actor collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, "tiktok", "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="tiktok",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise

    count = len(records)
    logger.info(
        "tiktok: collect_by_actors completed — run=%s records=%d",
        collection_run_id,
        count,
    )
    _update_task_status(collection_run_id, "tiktok", "completed", records_collected=count)
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="tiktok",
        status="completed",
        records_collected=count,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )
    return {
        "records_collected": count,
        "status": "completed",
        "arena": "social_media",
        "tier": "free",
    }


@celery_app.task(
    name="issue_observatory.arenas.tiktok.tasks.health_check",
    bind=False,
)
def tiktok_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the TikTok arena.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = TikTokCollector()
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info("tiktok: health_check status=%s", result.get("status", "unknown"))
    return result


@celery_app.task(
    name="issue_observatory.arenas.tiktok.tasks.refresh_engagement",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=600,
    acks_late=True,
)
def tiktok_refresh_engagement(
    self: Any,
    collection_run_id: str | None = None,
) -> dict[str, Any]:
    """Refresh engagement metrics for TikTok videos in the 10-15 day lag window.

    TikTok's Research API engagement metrics (view_count, like_count,
    share_count, comment_count) require up to 10 days to stabilize. This
    task re-fetches metrics for records where:
    - ``collected_at < NOW() - 10 days``
    - ``published_at > NOW() - 15 days``

    This implements TikTok's policy requirement to refresh data every 15 days.

    TODO (Phase 3): Implement full engagement refresh logic:
    1. Query DB for content_records where platform='tiktok' and
       collected_at < NOW() - interval '10 days' and
       published_at > NOW() - interval '15 days' and
       raw_metadata->>'engagement_refreshed_at' IS NULL.
    2. For each record, re-query the TikTok API using the video id query
       condition: {"field_name": "id", "field_values": [video_id]}.
    3. Update view_count, like_count, share_count, comment_count in the DB.
    4. Set raw_metadata.engagement_refreshed_at = NOW().
    5. Log the number of records refreshed.

    Args:
        collection_run_id: Optional UUID string of a collection run for
            context tracking.

    Returns:
        Dict with ``status``, ``refreshed_count``, and ``detail``.
    """
    logger.info(
        "tiktok: refresh_engagement task invoked (Phase 3 TODO) — run=%s",
        collection_run_id,
    )
    # TODO (Phase 3): implement engagement metric refresh as described above.
    return {
        "status": "skipped",
        "refreshed_count": 0,
        "detail": (
            "Engagement refresh is a Phase 3 feature. "
            "See task docstring for implementation specification."
        ),
    }
