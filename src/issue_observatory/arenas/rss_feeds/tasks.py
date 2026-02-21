"""Celery tasks for the RSS Feeds arena.

Wraps :class:`~issue_observatory.arenas.rss_feeds.collector.RSSFeedsCollector`
methods as Celery tasks with automatic retry behaviour and collection run
status tracking.

Task naming convention::

    issue_observatory.arenas.rss_feeds.tasks.<action>

Retry policy:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff
  (up to ``max_retries=3``).  RSS feeds have no formal rate limits, but this
  handles transient HTTP 429 responses from individual outlets.
- ``ArenaCollectionError`` is logged and re-raised so Celery marks the task
  FAILED.

All tasks update the ``collection_tasks`` row as best-effort (DB failures are
logged at WARNING and do not mask collection outcomes).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from issue_observatory.arenas.rss_feeds.collector import RSSFeedsCollector
from issue_observatory.config.settings import get_settings
from issue_observatory.core.event_bus import elapsed_since, publish_task_update
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
)
from issue_observatory.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_ARENA = "rss_feeds"


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
        status: New status value (``"running"`` | ``"completed"`` | ``"failed"``).
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
            "rss_feeds: failed to update collection_tasks status to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def _load_arenas_config(query_design_id: str) -> dict:
    """Load ``arenas_config`` from the QueryDesign row identified by *query_design_id*.

    Uses a synchronous SQLAlchemy session (Celery worker context).  Returns an
    empty dict if the design is not found or on any DB error.

    Args:
        query_design_id: UUID string of the owning query design.

    Returns:
        The ``arenas_config`` JSONB dict, or ``{}`` on failure.
    """
    try:
        from issue_observatory.core.database import get_sync_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with get_sync_session() as session:
            row = session.execute(
                text(
                    "SELECT arenas_config FROM query_designs WHERE id = :id"
                ),
                {"id": query_design_id},
            ).fetchone()
            if row and row[0]:
                return dict(row[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "rss_feeds: failed to load arenas_config for design %s: %s",
            query_design_id,
            exc,
        )
    return {}


@celery_app.task(
    name="issue_observatory.arenas.rss_feeds.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def rss_feeds_collect_terms(
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
    """Collect RSS entries matching the supplied search terms.

    Wraps :meth:`~RSSFeedsCollector.collect_by_terms` as an idempotent
    Celery task.  Updates the ``collection_tasks`` row with progress and
    final status.

    Reads ``arenas_config["rss"]["custom_feeds"]`` from the QueryDesign
    (GR-01) and passes the extra feed URLs to the collector.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms to match against entry titles and summaries.
        tier: Tier string — only ``"free"`` is valid for RSS Feeds.
        date_from: ISO 8601 earliest publication date (inclusive).
        date_to: ISO 8601 latest publication date (inclusive).
        max_results: Upper bound on returned records.
        language_filter: Optional list of ISO 639-1 language codes resolved
            from ``arenas_config["languages"]`` (GR-05).

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
        "rss_feeds: collect_by_terms started — run=%s terms=%d tier=%s",
        collection_run_id,
        len(terms),
        tier,
    )
    _update_task_status(collection_run_id, _ARENA, "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena=_ARENA,
        platform="rss_feeds",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    # GR-01: read researcher-configured extra feed URLs from arenas_config.
    arenas_config = _load_arenas_config(query_design_id)
    extra_feed_urls: list[str] | None = None
    rss_config = arenas_config.get("rss") or {}
    if isinstance(rss_config, dict):
        raw_custom = rss_config.get("custom_feeds")
        if isinstance(raw_custom, list) and raw_custom:
            extra_feed_urls = [str(u) for u in raw_custom if u]

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"rss_feeds: invalid tier '{tier}'. Only 'free' is supported."
        logger.error(msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        raise ArenaCollectionError(msg, arena=_ARENA, platform="rss_feeds")

    collector = RSSFeedsCollector()

    try:
        records = asyncio.run(
            collector.collect_by_terms(
                terms=terms,
                tier=tier_enum,
                date_from=date_from,
                date_to=date_to,
                max_results=max_results,
                language_filter=language_filter,
                extra_feed_urls=extra_feed_urls,
            )
        )
    except ArenaRateLimitError:
        logger.warning(
            "rss_feeds: rate limited on collect_by_terms for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error("rss_feeds: collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena=_ARENA,
            platform="rss_feeds",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise

    count = len(records)
    logger.info(
        "rss_feeds: collect_by_terms completed — run=%s records=%d",
        collection_run_id,
        count,
    )
    _update_task_status(collection_run_id, _ARENA, "completed", records_collected=count)
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena=_ARENA,
        platform="rss_feeds",
        status="completed",
        records_collected=count,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    return {
        "records_collected": count,
        "status": "completed",
        "arena": _ARENA,
        "tier": tier,
    }


@celery_app.task(
    name="issue_observatory.arenas.rss_feeds.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def rss_feeds_collect_actors(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    actor_ids: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
) -> dict[str, Any]:
    """Collect all RSS entries from feeds associated with specific outlets.

    Wraps :meth:`~RSSFeedsCollector.collect_by_actors`.  ``actor_ids`` are
    feed keys or outlet slug prefixes from :data:`DANISH_RSS_FEEDS`.

    Reads ``arenas_config["rss"]["custom_feeds"]`` from the QueryDesign
    (GR-01) and passes the extra feed URLs to the collector.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: Feed keys or outlet slug prefixes (e.g. ``"dr"``).
        tier: Tier string — only ``"free"`` is valid.
        date_from: ISO 8601 earliest publication date (inclusive).
        date_to: ISO 8601 latest publication date (inclusive).
        max_results: Upper bound on returned records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry.
        ArenaCollectionError: Marks the task as FAILED.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "rss_feeds: collect_by_actors started — run=%s actors=%d tier=%s",
        collection_run_id,
        len(actor_ids),
        tier,
    )
    _update_task_status(collection_run_id, _ARENA, "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena=_ARENA,
        platform="rss_feeds",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"rss_feeds: invalid tier '{tier}'. Only 'free' is supported."
        logger.error(msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        raise ArenaCollectionError(msg, arena=_ARENA, platform="rss_feeds")

    # GR-01: read researcher-configured extra feed URLs from arenas_config.
    arenas_config = _load_arenas_config(query_design_id)
    extra_feed_urls: list[str] | None = None
    rss_config = arenas_config.get("rss") or {}
    if isinstance(rss_config, dict):
        raw_custom = rss_config.get("custom_feeds")
        if isinstance(raw_custom, list) and raw_custom:
            extra_feed_urls = [str(u) for u in raw_custom if u]

    collector = RSSFeedsCollector()

    try:
        records = asyncio.run(
            collector.collect_by_actors(
                actor_ids=actor_ids,
                tier=tier_enum,
                date_from=date_from,
                date_to=date_to,
                max_results=max_results,
                extra_feed_urls=extra_feed_urls,
            )
        )
    except ArenaRateLimitError:
        logger.warning(
            "rss_feeds: rate limited on collect_by_actors for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error("rss_feeds: collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena=_ARENA,
            platform="rss_feeds",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise

    count = len(records)
    logger.info(
        "rss_feeds: collect_by_actors completed — run=%s records=%d",
        collection_run_id,
        count,
    )
    _update_task_status(collection_run_id, _ARENA, "completed", records_collected=count)
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena=_ARENA,
        platform="rss_feeds",
        status="completed",
        records_collected=count,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    return {
        "records_collected": count,
        "status": "completed",
        "arena": _ARENA,
        "tier": tier,
    }


@celery_app.task(
    name="issue_observatory.arenas.rss_feeds.tasks.health_check",
    bind=False,
)
def rss_feeds_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the RSS Feeds arena.

    Delegates to :meth:`~RSSFeedsCollector.health_check`, which fetches
    the DR all-news feed and verifies it parses correctly.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = RSSFeedsCollector()
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info(
        "rss_feeds: health_check status=%s", result.get("status", "unknown")
    )
    return result
