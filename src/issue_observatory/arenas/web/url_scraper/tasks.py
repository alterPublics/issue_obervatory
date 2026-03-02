"""Celery tasks for the URL Scraper arena.

Wraps :class:`~issue_observatory.arenas.web.url_scraper.collector.UrlScraperCollector`
methods as Celery tasks with automatic retry behaviour and collection run
status tracking.

Task naming convention::

    issue_observatory.arenas.web.url_scraper.tasks.<action>

Retry policy:
- ``ArenaCollectionError`` is logged and re-raised so Celery marks FAILED.
- No ``ArenaRateLimitError`` is expected from the URL Scraper (no external
  API), but the retry decorator is still included for consistency.

Database updates are best-effort; failures are logged and do not mask
collection outcomes.

Note: The URL Scraper is batch-only.  It is NOT suitable for Celery Beat
periodic scheduling because the URL list is static per researcher query design
and pages do not update on a predictable schedule.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from issue_observatory.arenas.web.url_scraper.collector import UrlScraperCollector
from issue_observatory.core.exceptions import ArenaCollectionError
from issue_observatory.config.settings import get_settings
from issue_observatory.core.event_bus import elapsed_since, publish_task_update
from issue_observatory.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_ARENA = "web"
_PLATFORM = "url_scraper"


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
            "url_scraper: failed to update collection_tasks status to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.web.url_scraper.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaCollectionError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
    soft_time_limit=600,
    time_limit=720,
)
def url_scraper_collect_terms(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    terms: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
    custom_urls: list[str] | None = None,
    term_groups: list[list[str]] | None = None,
    language_filter: list[str] | None = None,
    **_extra: Any,
) -> dict[str, Any]:
    """Fetch URLs and collect content matching the search terms.

    Fetches all URLs in *custom_urls* (from ``arenas_config["url_scraper"]
    ["custom_urls"]``), extracts article text, and returns records where at
    least one search term appears in the content.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms for case-insensitive substring matching.
        tier: Tier string — ``"free"`` (max 100 URLs) or ``"medium"``
            (max 500 URLs).
        date_from: Not applied by the URL Scraper (stored for API consistency).
        date_to: Not applied by the URL Scraper.
        max_results: Upper bound on returned records.
        custom_urls: List of URLs to fetch, from
            ``arenas_config["url_scraper"]["custom_urls"]``.
        term_groups: Optional boolean AND/OR groups.  When provided, overrides
            the flat *terms* list for matching.
        language_filter: Not applied — language detection is post-collection.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaCollectionError: Marks the task as FAILED after retries.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    try:
        logger.info(
            "url_scraper: collect_by_terms started — run=%s urls=%d tier=%s",
            collection_run_id,
            len(custom_urls) if custom_urls else 0,
            tier,
        )
        _update_task_status(collection_run_id, _PLATFORM, "running")
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="web",
            platform="url_scraper",
            status="running",
            records_collected=0,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        try:
            tier_enum = Tier(tier)
        except ValueError:
            msg = f"url_scraper: invalid tier '{tier}'. Valid values: 'free', 'medium'."
            logger.error(msg)
            _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="web",
                platform="url_scraper",
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise ArenaCollectionError(msg, arena=_ARENA, platform=_PLATFORM)

        collector = UrlScraperCollector()

        try:
            records = asyncio.run(
                collector.collect_by_terms(
                    terms=terms,
                    tier=tier_enum,
                    date_from=date_from,
                    date_to=date_to,
                    max_results=max_results,
                    term_groups=term_groups,
                    language_filter=language_filter,
                    extra_urls=custom_urls,
                )
            )
        except ArenaCollectionError as exc:
            msg = str(exc)
            logger.error(
                "url_scraper: collection error on collect_by_terms for run=%s: %s",
                collection_run_id,
                msg,
            )
            _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="web",
                platform="url_scraper",
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
            "url_scraper: collect_by_terms completed — run=%s records=%d inserted=%d skipped=%d",
            collection_run_id,
            count,
            inserted,
            skipped,
        )
        _update_task_status(collection_run_id, _PLATFORM, "completed", records_collected=inserted)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="web",
            platform="url_scraper",
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
    except SoftTimeLimitExceeded:
        logger.error(
            "url_scraper: collect_by_terms timed out after 10 minutes — run=%s",
            collection_run_id,
        )
        _update_task_status(
            collection_run_id,
            _PLATFORM,
            "failed",
            error_message="Collection timed out after 10 minutes",
        )
        return {"status": "failed", "error": "timeout", "arena": _ARENA}


@celery_app.task(
    name="issue_observatory.arenas.web.url_scraper.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaCollectionError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
    soft_time_limit=600,
    time_limit=720,
)
def url_scraper_collect_actors(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    actor_ids: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
    custom_urls: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch actor website URLs and return all content (no term filtering).

    Resolves actor platform presences (``platform="url_scraper"``), fetches
    matching URLs from *custom_urls* by domain, and returns all successfully
    extracted content records.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: Actor base URLs (from ``ActorPlatformPresence.platform_username``
            where ``platform="url_scraper"``).
        tier: Tier string — ``"free"`` or ``"medium"``.
        date_from: Not applied.
        date_to: Not applied.
        max_results: Upper bound on returned records.
        custom_urls: Optional URL pool to filter by actor domain.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaCollectionError: Marks the task as FAILED after retries.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    try:
        logger.info(
            "url_scraper: collect_by_actors started — run=%s actors=%d tier=%s",
            collection_run_id,
            len(actor_ids),
            tier,
        )
        _update_task_status(collection_run_id, _PLATFORM, "running")
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="web",
            platform="url_scraper",
            status="running",
            records_collected=0,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        try:
            tier_enum = Tier(tier)
        except ValueError:
            msg = f"url_scraper: invalid tier '{tier}'. Valid values: 'free', 'medium'."
            logger.error(msg)
            _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="web",
                platform="url_scraper",
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise ArenaCollectionError(msg, arena=_ARENA, platform=_PLATFORM)

        collector = UrlScraperCollector()

        try:
            records = asyncio.run(
                collector.collect_by_actors(
                    actor_ids=actor_ids,
                    tier=tier_enum,
                    date_from=date_from,
                    date_to=date_to,
                    max_results=max_results,
                    extra_urls=custom_urls,
                )
            )
        except ArenaCollectionError as exc:
            msg = str(exc)
            logger.error(
                "url_scraper: collection error on collect_by_actors for run=%s: %s",
                collection_run_id,
                msg,
            )
            _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="web",
                platform="url_scraper",
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
            "url_scraper: collect_by_actors completed — run=%s records=%d inserted=%d skipped=%d",
            collection_run_id,
            count,
            inserted,
            skipped,
        )
        _update_task_status(collection_run_id, _PLATFORM, "completed", records_collected=inserted)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="web",
            platform="url_scraper",
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
    except SoftTimeLimitExceeded:
        logger.error(
            "url_scraper: collect_by_actors timed out after 10 minutes — run=%s",
            collection_run_id,
        )
        _update_task_status(
            collection_run_id,
            _PLATFORM,
            "failed",
            error_message="Collection timed out after 10 minutes",
        )
        return {"status": "failed", "error": "timeout", "arena": _ARENA}


@celery_app.task(
    name="issue_observatory.arenas.web.url_scraper.tasks.health_check",
    bind=False,
)
def url_scraper_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the URL Scraper arena.

    Delegates to :meth:`~UrlScraperCollector.health_check`, which fetches
    ``www.dr.dk`` and verifies that the full fetch-and-extract pipeline
    is functional.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, ``scraper_module``, ``trafilatura``, and optionally
        ``detail``.
    """
    collector = UrlScraperCollector()
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info(
        "url_scraper: health_check status=%s", result.get("status", "unknown")
    )
    return result
