"""Celery tasks for the Threads arena.

Wraps :class:`ThreadsCollector` methods as Celery tasks with automatic retry
behaviour, collection run status tracking, and error reporting.

Task naming::

    issue_observatory.arenas.threads.tasks.<action>

Retry policy:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff
  (``autoretry_for`` + ``retry_backoff=True``), up to ``max_retries=3``.
- ``ArenaAuthError`` is logged at ERROR and re-raised without retry (the
  token must be refreshed manually or by the periodic refresh task).
- Other ``ArenaCollectionError`` subclasses are logged and re-raised.

Token refresh:
- ``threads_refresh_tokens`` is a periodic task added to the Celery Beat
  schedule.  It iterates over all active Threads credentials and refreshes
  any token within ``TOKEN_REFRESH_DAYS`` days of its 60-day expiry.

Database updates:
- Best-effort via ``_update_task_status()`` — DB failures are logged at
  WARNING and do not mask the collection outcome.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from issue_observatory.arenas.threads.collector import ThreadsCollector
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.config.settings import get_settings
from issue_observatory.core.event_bus import elapsed_since, publish_task_update
from issue_observatory.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_PLATFORM: str = "threads"
_ARENA: str = "social_media"


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

    Failures are logged at WARNING and do not affect the collection outcome.

    Args:
        collection_run_id: UUID string of the parent collection run.
        arena: Arena identifier (``"threads"``).
        status: New status (``"running"`` | ``"completed"`` | ``"failed"``).
        records_collected: Number of records collected (for completed updates).
        error_message: Error description (for failed updates).
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
            "threads: failed to update collection_tasks to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Collection tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.threads.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
    soft_time_limit=600,
    time_limit=720,
)
def threads_collect_terms(
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
    """Collect Threads posts matching a list of search terms.

    At FREE tier this falls back to actor-based collection with client-side
    keyword filtering (global search is not available in the Threads API).
    Returns an empty list if no default Danish accounts are configured.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms to match (case-insensitive).
        tier: Tier string (``"free"`` or ``"medium"``).
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
        max_results: Optional cap on total records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaAuthError: Marks the task as FAILED (token must be refreshed).
        ArenaCollectionError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415
    from issue_observatory.core.credential_pool import get_credential_pool  # noqa: PLC0415
    from issue_observatory.workers.rate_limiter import get_redis_client  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    try:
        logger.info(
            "threads: collect_by_terms started — run=%s terms=%d tier=%s",
            collection_run_id,
            len(terms),
            tier,
        )
        _update_task_status(collection_run_id, _PLATFORM, "running")
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="threads",
            status="running",
            records_collected=0,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        tier_enum = Tier.FREE if tier == "free" else Tier.MEDIUM
        credential_pool = get_credential_pool()

        try:
            redis_client = asyncio.run(get_redis_client())
        except Exception:
            redis_client = None

        from issue_observatory.workers.rate_limiter import RateLimiter  # noqa: PLC0415

        rate_limiter = RateLimiter(redis_client=redis_client) if redis_client else None
        collector = ThreadsCollector(
            credential_pool=credential_pool,
            rate_limiter=rate_limiter,
        )

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
                platform=_PLATFORM,
                date_from=_dt.fromisoformat(date_from) if isinstance(date_from, str) else date_from,
                date_to=_dt.fromisoformat(date_to) if isinstance(date_to, str) else date_to,
                terms=terms,
            )
            if not gaps:
                logger.info(
                    "threads: full coverage exists for run=%s — skipping API call, "
                    "will reindex existing records only.",
                    collection_run_id,
                )
                from issue_observatory.workers._task_helpers import (  # noqa: PLC0415
                    reindex_existing_records,
                )

                linked = reindex_existing_records(
                    platform=_PLATFORM,
                    collection_run_id=collection_run_id,
                    query_design_id=query_design_id,
                    terms=terms,
                    date_from=date_from,
                    date_to=date_to,
                )
                _update_task_status(
                    collection_run_id, _PLATFORM, "completed", records_collected=0
                )
                publish_task_update(
                    redis_url=_redis_url,
                    run_id=collection_run_id,
                    arena=_ARENA,
                    platform=_PLATFORM,
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
                "threads: narrowing collection to uncovered range %s — %s (run=%s)",
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
        except NoCredentialAvailableError as exc:
            msg = f"threads: no credential available: {exc}"
            logger.error(msg)
            _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="social_media",
                platform="threads",
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise ArenaCollectionError(msg, arena=_ARENA, platform=_PLATFORM) from exc
        except ArenaAuthError as exc:
            msg = f"threads: auth error (token may have expired): {exc}"
            logger.error(msg)
            _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="social_media",
                platform="threads",
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise
        except ArenaRateLimitError:
            logger.warning(
                "threads: rate limited on collect_by_terms for run=%s — will retry.",
                collection_run_id,
            )
            raise
        except ArenaCollectionError as exc:
            msg = str(exc)
            logger.error(
                "threads: collection error for run=%s: %s", collection_run_id, msg
            )
            _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="social_media",
                platform="threads",
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
                platform=_PLATFORM,
                collection_run_id=collection_run_id,
                query_design_id=query_design_id,
                inputs=terms,
                input_type="term",
                date_from=date_from,
                date_to=date_to,
                records_returned=inserted,
            )

        logger.info(
            "threads: collect_by_terms completed — run=%s records=%d inserted=%d skipped=%d",
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
            "tier": tier,
        }
    except SoftTimeLimitExceeded:
        logger.error(
            "threads: collect_by_terms timed out after 10 minutes — run=%s",
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
    name="issue_observatory.arenas.threads.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
    soft_time_limit=600,
    time_limit=720,
)
def threads_collect_actors(
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
    """Collect Threads posts published by specific actors.

    PRIMARY collection mode for the Threads arena.  Actor IDs should be
    Threads user IDs or usernames.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: Threads user IDs or usernames to collect from.
        tier: Tier string (``"free"`` or ``"medium"``).
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
        max_results: Optional cap on total records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaAuthError: Marks the task as FAILED (token must be refreshed).
        ArenaCollectionError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415
    from issue_observatory.core.credential_pool import get_credential_pool  # noqa: PLC0415
    from issue_observatory.workers.rate_limiter import get_redis_client  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    try:
        logger.info(
            "threads: collect_by_actors started — run=%s actors=%d tier=%s",
            collection_run_id,
            len(actor_ids),
            tier,
        )
        _update_task_status(collection_run_id, _PLATFORM, "running")
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="threads",
            status="running",
            records_collected=0,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        tier_enum = Tier.FREE if tier == "free" else Tier.MEDIUM
        credential_pool = get_credential_pool()

        try:
            redis_client = asyncio.run(get_redis_client())
        except Exception:
            redis_client = None

        from issue_observatory.workers.rate_limiter import RateLimiter  # noqa: PLC0415

        rate_limiter = RateLimiter(redis_client=redis_client) if redis_client else None
        collector = ThreadsCollector(
            credential_pool=credential_pool,
            rate_limiter=rate_limiter,
        )

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
                platform=_PLATFORM,
                date_from=_dt.fromisoformat(date_from) if isinstance(date_from, str) else date_from,
                date_to=_dt.fromisoformat(date_to) if isinstance(date_to, str) else date_to,
                actor_ids=actor_ids,
            )
            if not gaps:
                logger.info(
                    "threads: full coverage exists for run=%s — skipping API call, "
                    "will reindex existing records only.",
                    collection_run_id,
                )
                from issue_observatory.workers._task_helpers import (  # noqa: PLC0415
                    reindex_existing_records,
                )

                linked = reindex_existing_records(
                    platform=_PLATFORM,
                    collection_run_id=collection_run_id,
                    query_design_id=query_design_id,
                    actor_ids=actor_ids,
                    date_from=date_from,
                    date_to=date_to,
                )
                _update_task_status(
                    collection_run_id, _PLATFORM, "completed", records_collected=0
                )
                publish_task_update(
                    redis_url=_redis_url,
                    run_id=collection_run_id,
                    arena=_ARENA,
                    platform=_PLATFORM,
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
                "threads: narrowing collection to uncovered range %s — %s (run=%s)",
                effective_date_from,
                effective_date_to,
                collection_run_id,
            )

        try:
            records = asyncio.run(
                collector.collect_by_actors(
                    actor_ids=actor_ids,
                    tier=tier_enum,
                    date_from=effective_date_from,
                    date_to=effective_date_to,
                    max_results=max_results,
                )
            )
        except NoCredentialAvailableError as exc:
            msg = f"threads: no credential available: {exc}"
            logger.error(msg)
            _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="social_media",
                platform="threads",
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise ArenaCollectionError(msg, arena=_ARENA, platform=_PLATFORM) from exc
        except ArenaAuthError as exc:
            msg = f"threads: auth error (token may have expired): {exc}"
            logger.error(msg)
            _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="social_media",
                platform="threads",
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise
        except ArenaRateLimitError:
            logger.warning(
                "threads: rate limited on collect_by_actors for run=%s — will retry.",
                collection_run_id,
            )
            raise
        except ArenaCollectionError as exc:
            msg = str(exc)
            logger.error(
                "threads: actor collection error for run=%s: %s", collection_run_id, msg
            )
            _update_task_status(collection_run_id, _PLATFORM, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="social_media",
                platform="threads",
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

        inserted, skipped = persist_collected_records(records, collection_run_id, query_design_id)

        # Record successful collection attempts for future pre-checks.
        if date_from and date_to:
            record_collection_attempts_batch(
                platform=_PLATFORM,
                collection_run_id=collection_run_id,
                query_design_id=query_design_id,
                inputs=actor_ids,
                input_type="actor",
                date_from=date_from,
                date_to=date_to,
                records_returned=inserted,
            )

        logger.info(
            "threads: collect_by_actors completed — run=%s records=%d inserted=%d skipped=%d",
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
            "tier": tier,
        }
    except SoftTimeLimitExceeded:
        logger.error(
            "threads: collect_by_actors timed out after 10 minutes — run=%s",
            collection_run_id,
        )
        _update_task_status(
            collection_run_id,
            _PLATFORM,
            "failed",
            error_message="Collection timed out after 10 minutes",
        )
        return {"status": "failed", "error": "timeout", "arena": _ARENA}


# ---------------------------------------------------------------------------
# Health check task
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.threads.tasks.health_check",
    bind=False,
)
def threads_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the Threads arena.

    Delegates to :meth:`ThreadsCollector.health_check`, which sends a
    ``GET /me?fields=id,username`` request with the configured token.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``username`` or ``detail``.
    """
    from issue_observatory.core.credential_pool import get_credential_pool  # noqa: PLC0415

    credential_pool = get_credential_pool()
    collector = ThreadsCollector(credential_pool=credential_pool)
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info(
        "threads: health_check status=%s", result.get("status", "unknown")
    )
    return result


# ---------------------------------------------------------------------------
# Token refresh task (periodic)
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.threads.tasks.refresh_tokens",
    bind=False,
    acks_late=True,
)
def threads_refresh_tokens() -> dict[str, Any]:
    """Refresh all active Threads long-lived tokens that are near expiry.

    Iterates over all active ``platform="threads", tier="free"`` credentials
    in the DB and calls :meth:`ThreadsCollector.refresh_token_if_needed` for
    each one.

    This task is triggered daily by the Celery Beat schedule entry
    ``threads_refresh_tokens`` to ensure no token reaches the 60-day expiry
    without being renewed.

    Returns:
        Dict with:
        - ``refreshed`` (int): Number of tokens that were refreshed.
        - ``checked`` (int): Total credentials checked.
        - ``status`` (str): ``"completed"``.
    """
    from issue_observatory.core.credential_pool import get_credential_pool  # noqa: PLC0415

    credential_pool = get_credential_pool()
    collector = ThreadsCollector(credential_pool=credential_pool)

    async def _run_refresh() -> dict[str, Any]:
        """Fetch all Threads credentials and refresh tokens as needed."""
        db_rows = await credential_pool._query_db_credentials(
            platform="threads", tier="free"
        )
        checked = len(db_rows)
        refreshed = 0
        for row in db_rows:
            cred_id = str(row.id)
            try:
                did_refresh = await collector.refresh_token_if_needed(
                    credential_id=cred_id,
                    credential_pool=credential_pool,
                )
                if did_refresh:
                    refreshed += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "threads: token refresh check failed for credential '%s': %s",
                    cred_id,
                    exc,
                )
        return {"refreshed": refreshed, "checked": checked, "status": "completed"}

    result: dict[str, Any] = asyncio.run(_run_refresh())
    logger.info(
        "threads: refresh_tokens completed — checked=%d refreshed=%d",
        result["checked"],
        result["refreshed"],
    )
    return result
