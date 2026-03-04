"""Celery tasks for the Bluesky arena.

Wraps :class:`BlueskyCollector` methods as Celery tasks with automatic retry
behaviour, collection run status tracking, and error reporting.

Task naming::

    issue_observatory.arenas.bluesky.tasks.<action>

Retry policy:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff
  (``autoretry_for`` + ``retry_backoff=True``), up to ``max_retries=3``.
- Other ``ArenaCollectionError`` subclasses are logged and re-raised.

Bluesky is free-only, so ``NoCredentialAvailableError`` should never occur
in normal operation.  It is handled gracefully for interface consistency.

Database updates:
- Best-effort via ``_update_task_status()`` — DB failures are logged at WARNING
  and do not mask the collection outcome.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from issue_observatory.arenas.bluesky.collector import BlueskyCollector
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _update_task_status(
    collection_run_id: str,
    arena: str,
    status: str,
    records_collected: int = 0,
    error_message: str | None = None,
    actors_skipped: int = 0,
    skipped_actor_detail: list[dict[str, str]] | None = None,
) -> None:
    """Best-effort update of the ``collection_tasks`` row for this arena.

    Failures are logged at WARNING and do not affect the collection outcome.

    Args:
        collection_run_id: UUID string of the parent collection run.
        arena: Arena identifier (``"bluesky"``).
        status: New status (``"running"`` | ``"completed"`` | ``"failed"``).
        records_collected: Number of records collected (for completed updates).
        error_message: Error description (for failed updates).
        actors_skipped: Number of actors skipped due to per-actor errors.
        skipped_actor_detail: List of dicts with actor_id, reason, error.
    """
    try:
        from issue_observatory.core.database import get_sync_session  # noqa: PLC0415

        with get_sync_session() as session:
            import json  # noqa: PLC0415

            from sqlalchemy import text  # noqa: PLC0415

            session.execute(
                text(
                    """
                    UPDATE collection_tasks
                    SET status = :status,
                        records_collected = :records_collected,
                        error_message = :error_message,
                        actors_skipped = :actors_skipped,
                        skipped_actor_detail = :skipped_actor_detail,
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
                    "actors_skipped": actors_skipped,
                    "skipped_actor_detail": json.dumps(skipped_actor_detail)
                    if skipped_actor_detail
                    else None,
                    "run_id": collection_run_id,
                    "arena": arena,
                },
            )
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "bluesky: failed to update collection_tasks to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.bluesky.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
    soft_time_limit=600,
    time_limit=720,
)
def bluesky_collect_terms(
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
    """Collect Bluesky posts for a list of search terms.

    Wraps :meth:`BlueskyCollector.collect_by_terms` as an idempotent Celery
    task.  Updates the ``collection_tasks`` row with progress and final status.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms to query.
        tier: Tier string — always ``"free"`` for Bluesky.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
        max_results: Optional cap on total records.
        language_filter: Optional list of ISO 639-1 language codes (IP2-052).

    Returns:
        Dict with:
        - ``records_collected`` (int): Number of normalized records.
        - ``status`` (str): ``"completed"``.
        - ``arena`` (str): ``"bluesky"``.
        - ``tier`` (str): ``"free"``.

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
            "bluesky: collect_by_terms started — run=%s terms=%d",
            collection_run_id,
            len(terms),
        )
        _update_task_status(collection_run_id, "bluesky", "running")
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="bluesky",
            platform="bluesky",
            status="running",
            records_collected=0,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        credential_pool = CredentialPool()
        collector = BlueskyCollector(credential_pool=credential_pool)

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
                platform="bluesky",
                date_from=_dt.fromisoformat(date_from) if isinstance(date_from, str) else date_from,
                date_to=_dt.fromisoformat(date_to) if isinstance(date_to, str) else date_to,
                terms=terms,
            )
            if not gaps:
                logger.info(
                    "bluesky: full coverage exists for run=%s — skipping API call, "
                    "will reindex existing records only.",
                    collection_run_id,
                )
                # Skip API call — jump to persist + reindex
                from issue_observatory.workers._task_helpers import (  # noqa: PLC0415
                    reindex_existing_records,
                )

                linked = reindex_existing_records(
                    platform="bluesky",
                    collection_run_id=collection_run_id,
                    query_design_id=query_design_id,
                    terms=terms,
                    date_from=date_from,
                    date_to=date_to,
                )
                _update_task_status(
                    collection_run_id, "bluesky", "completed", records_collected=0
                )
                publish_task_update(
                    redis_url=_redis_url,
                    run_id=collection_run_id,
                    arena="bluesky",
                    platform="bluesky",
                    status="completed",
                    records_collected=0,
                    error_message=None,
                    elapsed_seconds=elapsed_since(_task_start),
                )
                return {
                    "records_collected": 0,
                    "records_linked": linked,
                    "status": "completed",
                    "arena": "bluesky",
                    "tier": "free",
                    "coverage_skip": True,
                }
            # Use the first gap's boundaries as the narrowed date range
            effective_date_from = gaps[0][0].isoformat()
            effective_date_to = gaps[-1][1].isoformat()
            logger.info(
                "bluesky: narrowing collection to uncovered range %s — %s (run=%s)",
                effective_date_from,
                effective_date_to,
                collection_run_id,
            )

        # Define a progress callback that emits SSE updates during long-running collections
        def _report_progress(count: int) -> None:
            """Publish intermediate progress via event_bus during collection."""
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="bluesky",
                platform="bluesky",
                status="running",
                records_collected=count,
                error_message=None,
                elapsed_seconds=elapsed_since(_task_start),
            )
            logger.debug("bluesky: progress update — collected=%d", count)

        try:
            records = asyncio.run(
                collector.collect_by_terms(
                    terms=terms,
                    tier=Tier.FREE,
                    date_from=effective_date_from,
                    date_to=effective_date_to,
                    max_results=max_results,
                    language_filter=language_filter,
                    progress_callback=_report_progress,
                )
            )
        except NoCredentialAvailableError as exc:
            # Should not occur for Bluesky (free/unauthenticated), but handle gracefully.
            msg = f"bluesky: credential error (unexpected): {exc}"
            logger.error(msg)
            _update_task_status(collection_run_id, "bluesky", "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="bluesky",
                platform="bluesky",
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise ArenaCollectionError(msg, arena="bluesky", platform="bluesky") from exc
        except ArenaRateLimitError:
            logger.warning(
                "bluesky: rate limited on collect_by_terms for run=%s — will retry.",
                collection_run_id,
            )
            raise
        except ArenaCollectionError as exc:
            msg = str(exc)
            logger.error("bluesky: collection error for run=%s: %s", collection_run_id, msg)
            _update_task_status(collection_run_id, "bluesky", "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="bluesky",
                platform="bluesky",
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
            reindex_existing_records,
        )

        inserted, skipped = persist_collected_records(records, collection_run_id, query_design_id)

        # Link existing records from other runs that match these terms/dates.
        linked = reindex_existing_records(
            platform="bluesky",
            collection_run_id=collection_run_id,
            query_design_id=query_design_id,
            terms=terms,
            date_from=date_from,
            date_to=date_to,
        )

        # Record successful collection attempts for future pre-checks.
        if date_from and date_to:
            record_collection_attempts_batch(
                platform="bluesky",
                collection_run_id=collection_run_id,
                query_design_id=query_design_id,
                inputs=terms,
                input_type="term",
                date_from=date_from,
                date_to=date_to,
                records_returned=inserted,
            )

        logger.info(
            "bluesky: collect_by_terms completed — run=%s records=%d inserted=%d "
            "skipped=%d linked=%d",
            collection_run_id,
            count,
            inserted,
            skipped,
            linked,
        )
        _update_task_status(collection_run_id, "bluesky", "completed", records_collected=inserted)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="bluesky",
            platform="bluesky",
            status="completed",
            records_collected=inserted,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )
        return {
            "records_collected": inserted,
            "status": "completed",
            "arena": "bluesky",
            "tier": "free",
        }
    except SoftTimeLimitExceeded:
        logger.error(
            "bluesky: collect_by_terms timed out after 10 minutes — run=%s",
            collection_run_id,
        )
        _update_task_status(
            collection_run_id,
            "bluesky",
            "failed",
            error_message="Collection timed out after 10 minutes",
        )
        return {"status": "failed", "error": "timeout", "arena": "bluesky"}


@celery_app.task(
    name="issue_observatory.arenas.bluesky.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
    soft_time_limit=600,
    time_limit=720,
)
def bluesky_collect_actors(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    actor_ids: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
) -> dict[str, Any]:
    """Collect Bluesky posts published by specific actors.

    Wraps :meth:`BlueskyCollector.collect_by_actors` as an idempotent Celery
    task.  Each *actor_id* should be a Bluesky DID or handle.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: Bluesky DIDs or handles to collect from.
        tier: Tier string — always ``"free"`` for Bluesky.
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

    try:
        logger.info(
            "bluesky: collect_by_actors started — run=%s actors=%d",
            collection_run_id,
            len(actor_ids),
        )
        _update_task_status(collection_run_id, "bluesky", "running")
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="bluesky",
            platform="bluesky",
            status="running",
            records_collected=0,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        credential_pool = CredentialPool()
        collector = BlueskyCollector(credential_pool=credential_pool)

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
        except ArenaRateLimitError:
            logger.warning(
                "bluesky: rate limited on collect_by_actors for run=%s — will retry.",
                collection_run_id,
            )
            raise
        except ArenaCollectionError as exc:
            msg = str(exc)
            logger.error("bluesky: actor collection error for run=%s: %s", collection_run_id, msg)
            _update_task_status(collection_run_id, "bluesky", "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="bluesky",
                platform="bluesky",
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
            reindex_existing_records,
        )

        inserted, skipped = persist_collected_records(records, collection_run_id, query_design_id)

        # Link existing records from other runs that match these actors/dates.
        linked = reindex_existing_records(
            platform="bluesky",
            collection_run_id=collection_run_id,
            query_design_id=query_design_id,
            actor_ids=actor_ids,
            date_from=date_from,
            date_to=date_to,
        )

        # Record successful collection attempts for future pre-checks.
        if date_from and date_to:
            record_collection_attempts_batch(
                platform="bluesky",
                collection_run_id=collection_run_id,
                query_design_id=query_design_id,
                inputs=actor_ids,
                input_type="actor",
                date_from=date_from,
                date_to=date_to,
                records_returned=inserted,
            )

        skipped_actors = collector.skipped_actors
        logger.info(
            "bluesky: collect_by_actors completed — run=%s records=%d inserted=%d "
            "dupes_skipped=%d actors_skipped=%d linked=%d",
            collection_run_id,
            count,
            inserted,
            skipped,
            len(skipped_actors),
            linked,
        )
        _update_task_status(
            collection_run_id,
            "bluesky",
            "completed",
            records_collected=inserted,
            actors_skipped=len(skipped_actors),
            skipped_actor_detail=skipped_actors or None,
        )
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="bluesky",
            platform="bluesky",
            status="completed",
            records_collected=inserted,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )
        return {
            "records_collected": inserted,
            "status": "completed",
            "arena": "bluesky",
            "tier": "free",
            "actors_skipped": len(skipped_actors),
        }
    except SoftTimeLimitExceeded:
        logger.error(
            "bluesky: collect_by_actors timed out after 10 minutes — run=%s",
            collection_run_id,
        )
        _update_task_status(
            collection_run_id,
            "bluesky",
            "failed",
            error_message="Collection timed out after 10 minutes",
        )
        return {"status": "failed", "error": "timeout", "arena": "bluesky"}


@celery_app.task(
    name="issue_observatory.arenas.bluesky.tasks.health_check",
    bind=False,
)
def bluesky_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the Bluesky arena.

    Delegates to :meth:`BlueskyCollector.health_check`, which sends a
    minimal test query to the AT Protocol public API.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    credential_pool = CredentialPool()
    collector = BlueskyCollector(credential_pool=credential_pool)
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info("bluesky: health_check status=%s", result.get("status", "unknown"))
    return result
