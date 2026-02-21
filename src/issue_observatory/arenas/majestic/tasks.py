"""Celery tasks for the Majestic backlink intelligence arena.

Wraps :class:`~issue_observatory.arenas.majestic.collector.MajesticCollector`
methods as Celery tasks with automatic retry behaviour and collection run
status tracking.

Task naming convention::

    issue_observatory.arenas.majestic.tasks.<action>

Retry policy:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff
  (up to ``max_retries=3``), capped at 5 minutes between retries.
- ``ArenaCollectionError`` is logged and re-raised so Celery marks the task
  FAILED (this includes budget exhaustion for Majestic).
- ``NoCredentialAvailableError`` is logged and re-raised; Celery marks FAILED.

Note on tier strings:
    Task arguments carry tier as a plain string (``"premium"``).
    The :class:`~issue_observatory.arenas.base.Tier` enum is reconstructed
    inside each task to keep Celery arguments JSON-serializable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from issue_observatory.arenas.majestic.collector import MajesticCollector
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.config.settings import get_settings
from issue_observatory.core.event_bus import elapsed_since, publish_task_update
from issue_observatory.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_ARENA = "web"
_PLATFORM = "majestic"


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
            "majestic: failed to update collection_tasks status to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.majestic.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def majestic_collect_terms(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    terms: list[str],
    tier: str = "premium",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
    language_filter: list[str] | None = None,
) -> dict[str, Any]:
    """Collect domain-level metrics for a list of domain names or URLs.

    Each term is treated as a domain name (or a URL from which the domain
    is extracted).  Returns ``content_type="domain_metrics"`` records.

    Only ``"premium"`` tier is accepted.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Domain names or URLs to analyse.
            Example: ``["dr.dk", "tv2.dk", "https://politiken.dk/"]``.
        tier: Must be ``"premium"``.
        date_from: Unused — Majestic does not filter domain metrics by date.
        date_to: Unused.
        max_results: Upper bound on returned records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED in Celery.
        NoCredentialAvailableError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "majestic: collect_by_terms started — run=%s terms=%d tier=%s",
        collection_run_id,
        len(terms),
        tier,
    )
    _update_task_status(collection_run_id, _ARENA, "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="web",
        platform="majestic",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"majestic: invalid tier '{tier}'. Only 'premium' is supported."
        logger.error(msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="web",
            platform="majestic",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise ArenaCollectionError(msg, arena=_ARENA, platform=_PLATFORM)

    collector = MajesticCollector()

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
    except ArenaRateLimitError:
        logger.warning(
            "majestic: rate limited on collect_by_terms for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except (ArenaCollectionError, NoCredentialAvailableError) as exc:
        msg = str(exc)
        logger.error(
            "majestic: collection error for run=%s: %s", collection_run_id, msg
        )
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="web",
            platform="majestic",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise

    count = len(records)
    logger.info(
        "majestic: collect_by_terms completed — run=%s records=%d",
        collection_run_id,
        count,
    )
    _update_task_status(
        collection_run_id, _ARENA, "completed", records_collected=count
    )

    return {
        "records_collected": count,
        "status": "completed",
        "arena": _ARENA,
        "tier": tier,
    }


@celery_app.task(
    name="issue_observatory.arenas.majestic.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def majestic_collect_actors(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    actor_ids: list[str],
    tier: str = "premium",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
) -> dict[str, Any]:
    """Collect domain metrics and individual backlinks for domain actor IDs.

    Actor IDs are domain names.  For each domain the task fetches domain-level
    metrics (``GetIndexItemInfo``) and up to
    ``MAJESTIC_MAX_BACKLINKS_PER_DOMAIN`` individual backlinks
    (``GetBackLinkData``, Mode=1: one per referring domain).

    Only ``"premium"`` tier is accepted.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: List of domain names.  Example: ``["dr.dk", "tv2.dk"]``.
        tier: Must be ``"premium"``.
        date_from: ISO 8601 start date for backlink filtering (optional).
        date_to: ISO 8601 end date for backlink filtering (optional).
        max_results: Upper bound on total returned records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED in Celery.
        NoCredentialAvailableError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "majestic: collect_by_actors started — run=%s actors=%d tier=%s",
        collection_run_id,
        len(actor_ids),
        tier,
    )
    _update_task_status(collection_run_id, _ARENA, "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="web",
        platform="majestic",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"majestic: invalid tier '{tier}'. Only 'premium' is supported."
        logger.error(msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="web",
            platform="majestic",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise ArenaCollectionError(msg, arena=_ARENA, platform=_PLATFORM)

    collector = MajesticCollector()

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
    except ArenaRateLimitError:
        logger.warning(
            "majestic: rate limited on collect_by_actors for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except (ArenaCollectionError, NoCredentialAvailableError) as exc:
        msg = str(exc)
        logger.error(
            "majestic: collection error for run=%s: %s", collection_run_id, msg
        )
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="web",
            platform="majestic",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise

    count = len(records)
    logger.info(
        "majestic: collect_by_actors completed — run=%s records=%d",
        collection_run_id,
        count,
    )
    _update_task_status(
        collection_run_id, _ARENA, "completed", records_collected=count
    )

    return {
        "records_collected": count,
        "status": "completed",
        "arena": _ARENA,
        "tier": tier,
    }


@celery_app.task(
    name="issue_observatory.arenas.majestic.tasks.health_check",
    bind=False,
)
def majestic_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the Majestic arena.

    Delegates to :meth:`~MajesticCollector.health_check`, which issues
    ``GetIndexItemInfo`` for ``dr.dk`` and verifies a Trust Flow > 0.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``trust_flow``, ``ref_domains``,
        and ``detail``.
    """
    collector = MajesticCollector()
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info(
        "majestic: health_check status=%s trust_flow=%s",
        result.get("status", "unknown"),
        result.get("trust_flow"),
    )
    return result
