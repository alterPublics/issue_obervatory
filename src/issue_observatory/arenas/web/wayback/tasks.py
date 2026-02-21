"""Celery tasks for the Wayback Machine arena.

Wraps :class:`~issue_observatory.arenas.web.wayback.collector.WaybackCollector`
methods as Celery tasks with automatic retry behaviour and collection run
status tracking.

Task naming convention::

    issue_observatory.arenas.web.wayback.tasks.<action>

Retry policy:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff
  (up to ``max_retries=3``), capped at 5 minutes between retries.
- ``ArenaCollectionError`` is logged and re-raised so Celery marks FAILED.

Database updates are best-effort; failures are logged and do not mask
collection outcomes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from issue_observatory.arenas.web.wayback.collector import WaybackCollector
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
)
from issue_observatory.config.settings import get_settings
from issue_observatory.core.event_bus import elapsed_since, publish_task_update
from issue_observatory.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_ARENA = "web"
_PLATFORM = "wayback"


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
        status: New status value.
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
            "wayback: failed to update collection_tasks status to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.web.wayback.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def wayback_collect_terms(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    terms: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
    language_filter: list[str] | None = None,
    arenas_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect Wayback Machine CDX captures for Danish pages matching the terms.

    Queries the CDX API for ``.dk`` domain captures and filters client-side
    by URL substring matching.  When ``arenas_config["wayback"]["fetch_content"]``
    is ``True``, the archived page content is also fetched and extracted.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms matched as URL substrings.
        tier: Tier string — only ``"free"`` is valid.
        date_from: ISO 8601 earliest capture date (inclusive).
        date_to: ISO 8601 latest capture date (inclusive).
        max_results: Upper bound on returned records.
        language_filter: Optional ISO 639-1 language code list (unused by
            Wayback Machine; passed through for interface consistency).
        arenas_config: Optional arenas configuration dict.  When present,
            ``arenas_config["wayback"]["fetch_content"]`` controls whether
            archived page content is fetched for each record.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``,
        and ``fetch_content`` (bool reflecting the resolved setting).

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    fetch_content: bool = bool(
        (arenas_config or {}).get("wayback", {}).get("fetch_content", False)
    )

    logger.info(
        "wayback: collect_by_terms started — run=%s terms=%d tier=%s fetch_content=%s",
        collection_run_id,
        len(terms),
        tier,
        fetch_content,
    )
    _update_task_status(collection_run_id, _ARENA, "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="web",
        platform="wayback",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"wayback: invalid tier '{tier}'. Only 'free' is supported."
        logger.error(msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="web",
            platform="wayback",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise ArenaCollectionError(msg, arena=_ARENA, platform=_PLATFORM)

    collector = WaybackCollector()

    try:
        records = asyncio.run(
            collector.collect_by_terms(
                terms=terms,
                tier=tier_enum,
                date_from=date_from,
                date_to=date_to,
                max_results=max_results,
                language_filter=language_filter,
                fetch_content=fetch_content,
            )
        )
    except ArenaRateLimitError:
        logger.warning(
            "wayback: rate limited on collect_by_terms for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error("wayback: collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="web",
            platform="wayback",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise

    count = len(records)
    logger.info(
        "wayback: collect_by_terms completed — run=%s records=%d fetch_content=%s",
        collection_run_id,
        count,
        fetch_content,
    )
    _update_task_status(collection_run_id, _ARENA, "completed", records_collected=count)
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="web",
        platform="wayback",
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
        "fetch_content": fetch_content,
    }


@celery_app.task(
    name="issue_observatory.arenas.web.wayback.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def wayback_collect_actors(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    actor_ids: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
    arenas_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect Wayback Machine CDX captures for the specified actor domains.

    Actor IDs are domain names or URL prefixes (e.g. ``"dr.dk"``).  When
    ``arenas_config["wayback"]["fetch_content"]`` is ``True``, the archived
    page content is also fetched and extracted for each record.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: Domain names or URL prefixes to query.
        tier: Tier string — only ``"free"`` is valid.
        date_from: ISO 8601 earliest capture date (inclusive).
        date_to: ISO 8601 latest capture date (inclusive).
        max_results: Upper bound on returned records.
        arenas_config: Optional arenas configuration dict.  When present,
            ``arenas_config["wayback"]["fetch_content"]`` controls whether
            archived page content is fetched for each record.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``,
        and ``fetch_content`` (bool reflecting the resolved setting).
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    fetch_content: bool = bool(
        (arenas_config or {}).get("wayback", {}).get("fetch_content", False)
    )

    logger.info(
        "wayback: collect_by_actors started — run=%s actors=%d tier=%s fetch_content=%s",
        collection_run_id,
        len(actor_ids),
        tier,
        fetch_content,
    )
    _update_task_status(collection_run_id, _ARENA, "running")

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"wayback: invalid tier '{tier}'. Only 'free' is supported."
        logger.error(msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="web",
            platform="wayback",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise ArenaCollectionError(msg, arena=_ARENA, platform=_PLATFORM)

    collector = WaybackCollector()

    try:
        records = asyncio.run(
            collector.collect_by_actors(
                actor_ids=actor_ids,
                tier=tier_enum,
                date_from=date_from,
                date_to=date_to,
                max_results=max_results,
                fetch_content=fetch_content,
            )
        )
    except ArenaRateLimitError:
        logger.warning(
            "wayback: rate limited on collect_by_actors for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error("wayback: collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="web",
            platform="wayback",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise

    count = len(records)
    logger.info(
        "wayback: collect_by_actors completed — run=%s records=%d fetch_content=%s",
        collection_run_id,
        count,
        fetch_content,
    )
    _update_task_status(collection_run_id, _ARENA, "completed", records_collected=count)
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="web",
        platform="wayback",
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
        "fetch_content": fetch_content,
    }


@celery_app.task(
    name="issue_observatory.arenas.web.wayback.tasks.health_check",
    bind=False,
)
def wayback_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the Wayback Machine arena.

    Delegates to :meth:`~WaybackCollector.health_check`, which queries
    the CDX API for a single capture of ``dr.dk``.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = WaybackCollector()
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info("wayback: health_check status=%s", result.get("status", "unknown"))
    return result
