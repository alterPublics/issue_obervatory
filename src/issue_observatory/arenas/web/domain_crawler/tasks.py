"""Celery tasks for the Domain Crawler arena.

Wraps :class:`~issue_observatory.arenas.web.domain_crawler.collector.DomainCrawlerCollector`
methods as Celery tasks with status tracking and SSE event publishing.

Task naming convention::

    issue_observatory.arenas.web.domain_crawler.tasks.<action>

Retry policy:
- ``ArenaCollectionError`` is logged and re-raised so Celery marks FAILED.
- No ``ArenaRateLimitError`` is expected (no external API), but the retry
  decorator is included for consistency.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from issue_observatory.arenas.web.domain_crawler.collector import DomainCrawlerCollector
from issue_observatory.config.settings import get_settings
from issue_observatory.core.event_bus import elapsed_since, publish_task_update
from issue_observatory.core.exceptions import ArenaCollectionError
from issue_observatory.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_ARENA = "web"
_PLATFORM = "domain_crawler"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_arenas_config(query_design_id: str) -> dict:
    """Load ``arenas_config`` from the QueryDesign row.

    Uses a synchronous SQLAlchemy session (Celery worker context).

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
                text("SELECT arenas_config FROM query_designs WHERE id = :id"),
                {"id": query_design_id},
            ).fetchone()
            if row and row[0]:
                return dict(row[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "domain_crawler: failed to load arenas_config for design %s: %s",
            query_design_id,
            exc,
        )
    return {}


def _update_task_status(
    collection_run_id: str,
    arena: str,
    status: str,
    records_collected: int = 0,
    error_message: str | None = None,
) -> None:
    """Best-effort update of the ``collection_tasks`` row for this arena."""
    try:
        from issue_observatory.core.database import get_sync_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with get_sync_session() as session:
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
            "domain_crawler: failed to update collection_tasks status to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.web.domain_crawler.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaCollectionError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
    soft_time_limit=7200,  # 2 hours — idle timeout in collector handles early stop
    time_limit=7500,  # 2h05m hard limit
)
def domain_crawler_collect_terms(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    terms: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
    term_groups: list[list[str]] | None = None,
    language_filter: list[str] | None = None,
    **_extra: Any,
) -> dict[str, Any]:
    """Crawl domains and collect articles matching the search terms.

    Reads ``arenas_config["domain_crawler"]["target_domains"]`` from the
    QueryDesign and passes researcher-configured domains to the collector.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms for case-insensitive matching.
        tier: Tier string — only ``"free"`` is valid.
        date_from: Not applied by the Domain Crawler.
        date_to: Not applied.
        max_results: Upper bound on returned records.
        term_groups: Optional boolean AND/OR groups.
        language_filter: Not applied.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    try:
        logger.info(
            "domain_crawler: collect_by_terms started — run=%s terms=%d tier=%s",
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

        # Load researcher-configured extra domains from arenas_config
        arenas_config = _load_arenas_config(query_design_id)
        extra_domains: list[str] | None = None
        dc_config = arenas_config.get("domain_crawler") or {}
        if isinstance(dc_config, dict):
            raw_domains = dc_config.get("target_domains")
            if isinstance(raw_domains, list) and raw_domains:
                extra_domains = [str(d).strip() for d in raw_domains if d]

        try:
            tier_enum = Tier(tier)
        except ValueError:
            msg = f"domain_crawler: invalid tier '{tier}'. Only 'free' is supported."
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

        collector = DomainCrawlerCollector()

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
                    extra_domains=extra_domains,
                )
            )
        except ArenaCollectionError as exc:
            msg = str(exc)
            logger.error(
                "domain_crawler: collection error on collect_by_terms for run=%s: %s",
                collection_run_id,
                msg,
            )
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

        count = len(records)

        # Persist collected records to the database.
        from issue_observatory.workers._task_helpers import persist_collected_records  # noqa: PLC0415

        inserted, skipped = persist_collected_records(
            records, collection_run_id, query_design_id
        )
        logger.info(
            "domain_crawler: collect_by_terms completed — run=%s records=%d inserted=%d skipped=%d",
            collection_run_id,
            count,
            inserted,
            skipped,
        )
        _update_task_status(
            collection_run_id, _PLATFORM, "completed", records_collected=inserted
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
        }
    except SoftTimeLimitExceeded:
        logger.error(
            "domain_crawler: collect_by_terms timed out — run=%s",
            collection_run_id,
        )
        _update_task_status(
            collection_run_id,
            _PLATFORM,
            "failed",
            error_message="Collection timed out after 2 hours",
        )
        return {"status": "failed", "error": "timeout", "arena": _ARENA}


@celery_app.task(
    name="issue_observatory.arenas.web.domain_crawler.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaCollectionError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
    soft_time_limit=1800,
    time_limit=2100,
)
def domain_crawler_collect_actors(
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
    """Crawl actor domains and return all articles (no term filtering).

    ``actor_ids`` are domain names (e.g., ``"dr.dk"``).

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: Domain names to crawl.
        tier: Tier string — only ``"free"`` is valid.
        date_from: Not applied.
        date_to: Not applied.
        max_results: Upper bound on returned records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    try:
        logger.info(
            "domain_crawler: collect_by_actors started — run=%s actors=%d tier=%s",
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
            msg = f"domain_crawler: invalid tier '{tier}'. Only 'free' is supported."
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

        collector = DomainCrawlerCollector()

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
        except ArenaCollectionError as exc:
            msg = str(exc)
            logger.error(
                "domain_crawler: collection error on collect_by_actors for run=%s: %s",
                collection_run_id,
                msg,
            )
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

        count = len(records)

        from issue_observatory.workers._task_helpers import persist_collected_records  # noqa: PLC0415

        inserted, skipped = persist_collected_records(
            records, collection_run_id, query_design_id
        )
        logger.info(
            "domain_crawler: collect_by_actors completed — run=%s records=%d inserted=%d skipped=%d",
            collection_run_id,
            count,
            inserted,
            skipped,
        )
        _update_task_status(
            collection_run_id, _PLATFORM, "completed", records_collected=inserted
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
        }
    except SoftTimeLimitExceeded:
        logger.error(
            "domain_crawler: collect_by_actors timed out — run=%s",
            collection_run_id,
        )
        _update_task_status(
            collection_run_id,
            _PLATFORM,
            "failed",
            error_message="Collection timed out after 2 hours",
        )
        return {"status": "failed", "error": "timeout", "arena": _ARENA}


@celery_app.task(
    name="issue_observatory.arenas.web.domain_crawler.tasks.health_check",
    bind=False,
)
def domain_crawler_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the Domain Crawler arena."""
    collector = DomainCrawlerCollector()
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info(
        "domain_crawler: health_check status=%s", result.get("status", "unknown")
    )
    return result
