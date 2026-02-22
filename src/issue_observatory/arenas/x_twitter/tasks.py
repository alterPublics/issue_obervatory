"""Celery tasks for the X/Twitter arena.

Wraps :class:`XTwitterCollector` methods as Celery tasks with retry logic,
collection run status tracking, and error reporting.

Task naming::

    issue_observatory.arenas.x_twitter.tasks.<action>

Retry policy for collection tasks:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff.
  Maximum 3 retries; backoff capped at 600 seconds (10 minutes).
- ``NoCredentialAvailableError`` immediately marks the task as FAILED
  (no retry — no credential rotation will help without operator action).

All task arguments are JSON-serializable so that the Celery result backend
can store and inspect them.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from issue_observatory.arenas.x_twitter.collector import XTwitterCollector
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

_ARENA: str = "social_media"
_PLATFORM: str = "x_twitter"


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
        arena: Arena identifier (``"social_media"``).
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
            "x_twitter: failed to update collection_tasks to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.x_twitter.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=600,
    acks_late=True,
)
def x_twitter_collect_terms(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    terms: list[str],
    tier: str = "medium",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
    language_filter: list[str] | None = None,
    **_extra: Any,
) -> dict[str, Any]:
    """Collect tweets matching a list of search terms.

    Wraps :meth:`XTwitterCollector.collect_by_terms` as an idempotent
    Celery task. Updates the ``collection_tasks`` row with progress and
    final status. Uses :class:`CredentialPool` for credential management.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms to query.
        tier: Tier string — ``"medium"`` (TwitterAPI.io) or ``"premium"``
            (X API v2 Pro).
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
        max_results: Optional cap on total records.

    Returns:
        Dict with:
        - ``records_collected`` (int): Number of normalized records.
        - ``status`` (str): ``"completed"``.
        - ``arena`` (str): ``"social_media"``.
        - ``platform`` (str): ``"x_twitter"``.
        - ``tier`` (str): The tier used.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED.
        NoCredentialAvailableError: Marks the task as FAILED immediately.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "x_twitter: collect_by_terms started — run=%s tier=%s terms=%d",
        collection_run_id,
        tier,
        len(terms),
    )
    _update_task_status(collection_run_id, _ARENA, "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="x_twitter",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    credential_pool = CredentialPool()
    collector = XTwitterCollector(credential_pool=credential_pool)
    tier_enum = Tier(tier)

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
    except NoCredentialAvailableError as exc:
        msg = f"x_twitter: no credential available for tier={tier}: {exc}"
        logger.error(msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="x_twitter",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise ArenaCollectionError(msg, arena=_ARENA, platform=_PLATFORM) from exc
    except ArenaRateLimitError:
        logger.warning(
            "x_twitter: rate limited on collect_by_terms for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error("x_twitter: collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="x_twitter",
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
        "x_twitter: collect_by_terms completed — run=%s records=%d inserted=%d skipped=%d",
        collection_run_id,
        count,
        inserted,
        skipped,
    )
    _update_task_status(collection_run_id, _ARENA, "completed", records_collected=inserted)
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="x_twitter",
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


@celery_app.task(
    name="issue_observatory.arenas.x_twitter.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=600,
    acks_late=True,
)
def x_twitter_collect_actors(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    actor_ids: list[str],
    tier: str = "medium",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
) -> dict[str, Any]:
    """Collect tweets published by specific X/Twitter users.

    Wraps :meth:`XTwitterCollector.collect_by_actors` as an idempotent
    Celery task. Each entry in *actor_ids* may be a numeric Twitter user ID
    string or a handle prefixed with ``@``.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: Twitter user IDs or ``@handles`` to collect from.
        tier: Tier string — ``"medium"`` or ``"premium"``.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
        max_results: Optional cap on total records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``platform``,
        ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED.
        NoCredentialAvailableError: Marks the task as FAILED immediately.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "x_twitter: collect_by_actors started — run=%s tier=%s actors=%d",
        collection_run_id,
        tier,
        len(actor_ids),
    )
    _update_task_status(collection_run_id, _ARENA, "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="x_twitter",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    credential_pool = CredentialPool()
    collector = XTwitterCollector(credential_pool=credential_pool)
    tier_enum = Tier(tier)

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
    except NoCredentialAvailableError as exc:
        msg = f"x_twitter: no credential available for tier={tier}: {exc}"
        logger.error(msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="x_twitter",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise ArenaCollectionError(msg, arena=_ARENA, platform=_PLATFORM) from exc
    except ArenaRateLimitError:
        logger.warning(
            "x_twitter: rate limited on collect_by_actors for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error(
            "x_twitter: actor collection error for run=%s: %s", collection_run_id, msg
        )
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="x_twitter",
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
        "x_twitter: collect_by_actors completed — run=%s records=%d inserted=%d skipped=%d",
        collection_run_id,
        count,
        inserted,
        skipped,
    )
    _update_task_status(collection_run_id, _ARENA, "completed", records_collected=inserted)
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="x_twitter",
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


@celery_app.task(
    name="issue_observatory.arenas.x_twitter.tasks.health_check",
    bind=False,
)
def x_twitter_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the X/Twitter arena.

    Delegates to :meth:`XTwitterCollector.health_check`, which performs a
    lightweight test query against the first available tier.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail`` and ``tier_tested``.
    """
    credential_pool = CredentialPool()
    collector = XTwitterCollector(credential_pool=credential_pool)
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info("x_twitter: health_check status=%s", result.get("status", "unknown"))
    return result
