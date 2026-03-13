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
        from sqlalchemy import text

        from issue_observatory.core.database import get_sync_session

        with get_sync_session() as session:
            row = session.execute(
                text("SELECT arenas_config FROM query_designs WHERE id = :id"),
                {"id": query_design_id},
            ).fetchone()
            if row and row[0]:
                return dict(row[0])
    except Exception as exc:
        logger.warning(
            "domain_crawler: failed to load arenas_config for design %s: %s",
            query_design_id,
            exc,
        )
    return {}


def _load_known_urls() -> set[str]:
    """Load URLs already collected by the domain crawler.

    Queries both ``url`` (final URL after redirects) and
    ``raw_metadata->>'source_url'`` (originally discovered URL) so that
    deduplication works regardless of redirects.

    Returns:
        Set of known URL strings, or empty set on failure.
    """
    try:
        from sqlalchemy import text

        from issue_observatory.core.database import get_sync_session

        with get_sync_session() as session:
            rows = session.execute(
                text(
                    "SELECT url, raw_metadata->>'source_url' "
                    "FROM content_records WHERE platform = 'domain_crawler'"
                )
            ).fetchall()
            urls: set[str] = set()
            for row in rows:
                if row[0]:
                    urls.add(row[0])
                if row[1]:
                    urls.add(row[1])
            return urls
    except Exception as exc:
        logger.warning("domain_crawler: failed to load known URLs: %s", exc)
        return set()


def _update_task_status(
    collection_run_id: str,
    arena: str,
    status: str,
    records_collected: int = 0,
    error_message: str | None = None,
) -> None:
    """Best-effort update of the ``collection_tasks`` row for this arena."""
    try:
        from sqlalchemy import text

        from issue_observatory.core.database import get_sync_session

        with get_sync_session() as session:
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
    # No fixed time limit — records persist incrementally and stale_run_cleanup handles stuck tasks.
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
    from issue_observatory.arenas.base import Tier

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

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
    known_urls = _load_known_urls()
    if known_urls:
        collector.set_known_urls(known_urls)
        logger.info("domain_crawler: loaded %d known URLs for dedup", len(known_urls))

    # Incremental persistence: persist each batch of records as soon as
    # the domains in that batch are crawled, so records are browsable
    # before the full multi-hour crawl finishes.
    from issue_observatory.workers._task_helpers import persist_collected_records

    total_inserted = 0
    total_skipped = 0

    def _persist_batch(batch_records: list[dict[str, Any]]) -> None:
        nonlocal total_inserted, total_skipped
        if not batch_records:
            return
        ins, skp = persist_collected_records(
            batch_records, collection_run_id, query_design_id
        )
        total_inserted += ins
        total_skipped += skp
        _update_task_status(
            collection_run_id, _PLATFORM, "running", records_collected=total_inserted
        )
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena=_ARENA,
            platform=_PLATFORM,
            status="running",
            records_collected=total_inserted,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

    try:
        asyncio.run(
            collector.collect_by_terms(
                terms=terms,
                tier=tier_enum,
                date_from=date_from,
                date_to=date_to,
                max_results=max_results,
                term_groups=term_groups,
                language_filter=language_filter,
                extra_domains=extra_domains,
                on_batch=_persist_batch,
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
            records_collected=total_inserted,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise

    # Fallback: if batch callback counters lost track, use the actual DB count.
    if total_inserted == 0:
        from issue_observatory.workers._task_helpers import (
            count_run_platform_records,
        )

        db_count = count_run_platform_records(collection_run_id, "domain_crawler")
        if db_count > 0:
            logger.info(
                "domain_crawler: in-memory counter=0 but DB has %d records — using DB count",
                db_count,
            )
            total_inserted = db_count

    logger.info(
        "domain_crawler: collect_by_terms completed — run=%s inserted=%d skipped=%d",
        collection_run_id,
        total_inserted,
        total_skipped,
    )
    _update_task_status(
        collection_run_id, _PLATFORM, "completed", records_collected=total_inserted
    )
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena=_ARENA,
        platform=_PLATFORM,
        status="completed",
        records_collected=total_inserted,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    return {
        "records_collected": total_inserted,
        "status": "completed",
        "arena": _ARENA,
        "platform": _PLATFORM,
        "tier": tier,
    }


@celery_app.task(
    name="issue_observatory.arenas.web.domain_crawler.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaCollectionError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
    # No fixed time limit — records persist incrementally and stale_run_cleanup handles stuck tasks.
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
    from issue_observatory.arenas.base import Tier

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

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
    known_urls = _load_known_urls()
    if known_urls:
        collector.set_known_urls(known_urls)
        logger.info("domain_crawler: loaded %d known URLs for dedup", len(known_urls))

    from issue_observatory.workers._task_helpers import persist_collected_records

    total_inserted = 0
    total_skipped = 0

    def _persist_batch(batch_records: list[dict[str, Any]]) -> None:
        nonlocal total_inserted, total_skipped
        if not batch_records:
            return
        ins, skp = persist_collected_records(
            batch_records, collection_run_id, query_design_id
        )
        total_inserted += ins
        total_skipped += skp
        _update_task_status(
            collection_run_id, _PLATFORM, "running", records_collected=total_inserted
        )
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena=_ARENA,
            platform=_PLATFORM,
            status="running",
            records_collected=total_inserted,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

    try:
        asyncio.run(
            collector.collect_by_actors(
                actor_ids=actor_ids,
                tier=tier_enum,
                date_from=date_from,
                date_to=date_to,
                max_results=max_results,
                on_batch=_persist_batch,
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
            records_collected=total_inserted,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise

    # Fallback: if batch callback counters lost track, use the actual DB count.
    if total_inserted == 0:
        from issue_observatory.workers._task_helpers import (
            count_run_platform_records,
        )

        db_count = count_run_platform_records(collection_run_id, "domain_crawler")
        if db_count > 0:
            logger.info(
                "domain_crawler: in-memory counter=0 but DB has %d records — using DB count",
                db_count,
            )
            total_inserted = db_count

    logger.info(
        "domain_crawler: collect_by_actors completed — run=%s inserted=%d skipped=%d",
        collection_run_id,
        total_inserted,
        total_skipped,
    )
    _update_task_status(
        collection_run_id, _PLATFORM, "completed", records_collected=total_inserted
    )
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena=_ARENA,
        platform=_PLATFORM,
        status="completed",
        records_collected=total_inserted,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    return {
        "records_collected": total_inserted,
        "status": "completed",
        "arena": _ARENA,
        "platform": _PLATFORM,
        "tier": tier,
    }


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
