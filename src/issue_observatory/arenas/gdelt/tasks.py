"""Celery tasks for the GDELT arena.

Wraps :class:`~issue_observatory.arenas.gdelt.collector.GDELTCollector`
methods as Celery tasks with automatic retry behaviour and collection run
status tracking.

Task naming convention::

    issue_observatory.arenas.gdelt.tasks.<action>

Retry policy:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff
  (up to ``max_retries=3``), capped at 5 minutes between retries.
- ``ArenaCollectionError`` is logged and re-raised so Celery marks FAILED.
- ``collect_by_actors`` is not implemented and will raise immediately.

Database updates are best-effort; failures are logged and do not mask
collection outcomes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from issue_observatory.arenas.gdelt.collector import GDELTCollector
from issue_observatory.config.settings import get_settings
from issue_observatory.core.event_bus import elapsed_since, publish_task_update
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
)
from issue_observatory.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_ARENA = "gdelt"


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
            "gdelt: failed to update collection_tasks status to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.gdelt.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
    soft_time_limit=600,
    time_limit=720,
)
def gdelt_collect_terms(
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
    """Collect GDELT articles matching the supplied search terms.

    Wraps :meth:`~GDELTCollector.collect_by_terms` as an idempotent Celery
    task.  Each term generates two GDELT queries (sourcecountry:DA and
    sourcelang:danish); results are deduplicated by URL.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms (GDELT Boolean syntax supported).
        tier: Tier string — only ``"free"`` is valid for GDELT.
        date_from: ISO 8601 earliest observation date (inclusive).
        date_to: ISO 8601 latest observation date (inclusive).
        max_results: Upper bound on returned records.

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

    try:
        logger.info(
            "gdelt: collect_by_terms started — run=%s terms=%d tier=%s",
            collection_run_id,
            len(terms),
            tier,
        )
        _update_task_status(collection_run_id, _ARENA, "running")
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena=_ARENA,
            platform="gdelt",
            status="running",
            records_collected=0,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        try:
            tier_enum = Tier(tier)
        except ValueError:
            msg = f"gdelt: invalid tier '{tier}'. Only 'free' is supported."
            logger.error(msg)
            _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
            raise ArenaCollectionError(msg, arena=_ARENA, platform="gdelt")

        collector = GDELTCollector()

        # Check if force_recollect is set (opt-out from coverage check)
        force_recollect = _extra.get("force_recollect", False)

        # Pre-collection coverage check: narrow date range to uncovered gaps
        effective_date_from = date_from
        effective_date_to = date_to
        if not force_recollect and date_from and date_to:
            from datetime import datetime as _dt  # noqa: PLC0415

            from issue_observatory.core.coverage_checker import (  # noqa: PLC0415
                check_existing_coverage,
            )

            gaps = check_existing_coverage(
                platform="gdelt",
                date_from=_dt.fromisoformat(date_from) if isinstance(date_from, str) else date_from,
                date_to=_dt.fromisoformat(date_to) if isinstance(date_to, str) else date_to,
                terms=terms,
            )
            if not gaps:
                logger.info(
                    "gdelt: full coverage exists for run=%s — skipping API call, "
                    "will reindex existing records only.",
                    collection_run_id,
                )
                from issue_observatory.workers._task_helpers import (  # noqa: PLC0415
                    reindex_existing_records,
                )

                linked = reindex_existing_records(
                    platform="gdelt",
                    collection_run_id=collection_run_id,
                    query_design_id=query_design_id,
                    terms=terms,
                    date_from=date_from,
                    date_to=date_to,
                )
                _update_task_status(
                    collection_run_id, _ARENA, "completed", records_collected=0
                )
                publish_task_update(
                    redis_url=_redis_url,
                    run_id=collection_run_id,
                    arena=_ARENA,
                    platform="gdelt",
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
                "gdelt: narrowing collection to uncovered range %s — %s (run=%s)",
                effective_date_from,
                effective_date_to,
                collection_run_id,
            )

        try:
            records = asyncio.run(
                collector.collect_by_terms(
                    terms=terms,
                    tier=tier_enum,
                    date_from=effective_date_from,
                    date_to=effective_date_to,
                    max_results=max_results,
                    language_filter=language_filter,
                )
            )
        except ArenaRateLimitError:
            logger.warning(
                "gdelt: rate limited on collect_by_terms for run=%s — will retry.",
                collection_run_id,
            )
            raise
        except ArenaCollectionError as exc:
            msg = str(exc)
            logger.error("gdelt: collection error for run=%s: %s", collection_run_id, msg)
            _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena=_ARENA,
                platform="gdelt",
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise

        count = len(records)

        # Persist collected records to the database.
        from issue_observatory.workers._task_helpers import (  # noqa: PLC0415
            persist_collected_records,
            record_collection_attempts_batch,
        )

        inserted, skipped = persist_collected_records(records, collection_run_id, query_design_id, terms=terms)

        # Record successful collection attempts for future pre-checks.
        if date_from and date_to:
            record_collection_attempts_batch(
                platform="gdelt",
                collection_run_id=collection_run_id,
                query_design_id=query_design_id,
                inputs=terms,
                input_type="term",
                date_from=date_from,
                date_to=date_to,
                records_returned=inserted,
            )

        logger.info(
            "gdelt: collect_by_terms completed — run=%s records=%d inserted=%d skipped=%d",
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
            platform="gdelt",
            status="completed",
            records_collected=inserted,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        return {
            "records_collected": inserted,
            "status": "completed",
            "arena": _ARENA,
            "tier": tier,
        }
    except SoftTimeLimitExceeded:
        logger.error(
            "gdelt: collect_by_terms timed out after 10 minutes — run=%s",
            collection_run_id,
        )
        _update_task_status(
            collection_run_id,
            _ARENA,
            "failed",
            error_message="Collection timed out after 10 minutes",
        )
        return {"status": "failed", "error": "timeout", "arena": _ARENA}


@celery_app.task(
    name="issue_observatory.arenas.gdelt.tasks.health_check",
    bind=False,
)
def gdelt_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the GDELT arena.

    Delegates to :meth:`~GDELTCollector.health_check`, which issues a
    minimal DOC API query and verifies a valid JSON response.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = GDELTCollector()
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info("gdelt: health_check status=%s", result.get("status", "unknown"))
    return result
