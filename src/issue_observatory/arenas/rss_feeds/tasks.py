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
        from sqlalchemy import text

        from issue_observatory.core.database import get_sync_session

        with get_sync_session() as session:
            row = session.execute(
                text(
                    "SELECT arenas_config FROM query_designs WHERE id = :id"
                ),
                {"id": query_design_id},
            ).fetchone()
            if row and row[0]:
                return dict(row[0])
    except Exception as exc:
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
    # No fixed time limit — records persist incrementally and stale_run_cleanup handles stuck tasks.
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
    **_extra: Any,
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
    from issue_observatory.arenas.base import Tier

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "rss_feeds: collect_by_terms started — run=%s terms=%d tier=%s",
        collection_run_id,
        len(terms),
        tier,
    )
    from issue_observatory.workers._task_helpers import (
        update_collection_task_status,
    )

    update_collection_task_status(collection_run_id, _ARENA, "running")
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
        update_collection_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        raise ArenaCollectionError(msg, arena=_ARENA, platform="rss_feeds")

    collector = RSSFeedsCollector()

    # NOTE: RSS feeds are FORWARD_ONLY — they only return current/recent
    # entries and cannot backfill historical data.  Coverage pre-check is
    # intentionally skipped because it would prevent re-fetching feeds
    # whose content changes with every poll.

    from issue_observatory.workers._task_helpers import (
        make_batch_sink,
        persist_collected_records,
    )

    sink = make_batch_sink(collection_run_id, query_design_id, terms=terms)
    collector.configure_batch_persistence(sink=sink, batch_size=100, collection_run_id=collection_run_id)

    try:
        remaining = asyncio.run(
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
        update_collection_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
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

        db_count = count_run_platform_records(collection_run_id, "rss_feeds")
        if db_count > 0:
            logger.info(
                "rss_feeds: in-memory counter=0 but DB has %d records — using DB count",
                db_count,
            )
            inserted = db_count

    logger.info(
        "rss_feeds: collect_by_terms completed — run=%s emitted=%d inserted=%d skipped=%d",
        collection_run_id,
        collector.batch_stats["emitted"],
        inserted,
        skipped,
    )
    update_collection_task_status(
        collection_run_id,
        _ARENA,
        "completed",
        records_collected=inserted,
        duplicates_skipped=skipped,
    )
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena=_ARENA,
        platform="rss_feeds",
        status="completed",
        records_collected=inserted,
        duplicates_skipped=skipped,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    return {
        "records_collected": inserted,
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
    # No fixed time limit — records persist incrementally and stale_run_cleanup handles stuck tasks.
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
    **_extra: Any,
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
    from issue_observatory.arenas.base import Tier
    from issue_observatory.workers._task_helpers import (
        update_collection_task_status,
    )

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "rss_feeds: collect_by_actors started — run=%s actors=%d tier=%s",
        collection_run_id,
        len(actor_ids),
        tier,
    )
    update_collection_task_status(collection_run_id, _ARENA, "running")
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
        update_collection_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
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

    # NOTE: RSS feeds are FORWARD_ONLY — coverage pre-check skipped.
    # See collect_by_terms for explanation.

    from issue_observatory.workers._task_helpers import (
        make_batch_sink,
        persist_collected_records,
    )

    sink = make_batch_sink(collection_run_id, query_design_id)
    collector.configure_batch_persistence(sink=sink, batch_size=100, collection_run_id=collection_run_id)

    try:
        remaining = asyncio.run(
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
        update_collection_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
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

        db_count = count_run_platform_records(collection_run_id, "rss_feeds")
        if db_count > 0:
            logger.info(
                "rss_feeds: in-memory counter=0 but DB has %d records — using DB count",
                db_count,
            )
            inserted = db_count

    logger.info(
        "rss_feeds: collect_by_actors completed — run=%s emitted=%d inserted=%d skipped=%d",
        collection_run_id,
        collector.batch_stats["emitted"],
        inserted,
        skipped,
    )
    update_collection_task_status(
        collection_run_id,
        _ARENA,
        "completed",
        records_collected=inserted,
        duplicates_skipped=skipped,
    )
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena=_ARENA,
        platform="rss_feeds",
        status="completed",
        records_collected=inserted,
        duplicates_skipped=skipped,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    return {
        "records_collected": inserted,
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
