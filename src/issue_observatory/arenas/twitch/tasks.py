"""Celery tasks for the Twitch arena — DEFERRED stub.

Wraps :class:`~issue_observatory.arenas.twitch.collector.TwitchCollector`
methods as Celery tasks with automatic retry behaviour and collection run
status tracking.

Task naming convention::

    issue_observatory.arenas.twitch.tasks.<action>

IMPORTANT: These batch tasks return channel metadata only. Real-time Twitch
chat collection requires a separate streaming task (not yet implemented)
routed to the ``"streaming"`` Celery queue with extended time limits:

    issue_observatory.arenas.twitch.tasks.stream* -> "streaming" queue

Retry policy:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff
  (up to ``max_retries=3``).
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

from issue_observatory.arenas.twitch.collector import TwitchCollector
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
)
from issue_observatory.config.settings import get_settings
from issue_observatory.core.event_bus import elapsed_since, publish_task_update
from issue_observatory.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_ARENA = "twitch"


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
        status: New status value (``"running"`` | ``"completed"`` | ``"failed"``).
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
            "twitch: failed to update collection_tasks status to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.twitch.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def twitch_collect_terms(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    terms: list[str],
    tier: str = "free",
    max_results: int | None = None,
    language_filter: list[str] | None = None,
) -> dict[str, Any]:
    """Discover Twitch channels matching the supplied search terms.

    Wraps :meth:`~TwitchCollector.collect_by_terms` as a Celery task.
    Returns channel metadata records, NOT chat messages. Chat is streaming-only.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Channel name search queries.
        tier: Tier string — only ``"free"`` is valid for Twitch.
        max_results: Upper bound on returned records.
        language_filter: ISO 639-1 language codes to filter by broadcaster language.

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

    logger.info(
        "twitch: collect_by_terms started — run=%s terms=%d tier=%s",
        collection_run_id,
        len(terms),
        tier,
    )
    _update_task_status(collection_run_id, _ARENA, "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="twitch",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"twitch: invalid tier '{tier}'. Only 'free' is supported."
        logger.error(msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="twitch",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise ArenaCollectionError(msg, arena=_ARENA, platform="twitch")

    collector = TwitchCollector()

    try:
        records = asyncio.run(
            collector.collect_by_terms(
                terms=terms,
                tier=tier_enum,
                max_results=max_results,
                language_filter=language_filter,
            )
        )
    except ArenaRateLimitError:
        logger.warning(
            "twitch: rate limited on collect_by_terms for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error("twitch: collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="twitch",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise

    count = len(records)
    logger.info(
        "twitch: collect_by_terms completed — run=%s records=%d",
        collection_run_id,
        count,
    )
    _update_task_status(collection_run_id, _ARENA, "completed", records_collected=count)
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="twitch",
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
    }


@celery_app.task(
    name="issue_observatory.arenas.twitch.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def twitch_collect_actors(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    actor_ids: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
) -> dict[str, Any]:
    """Retrieve Twitch channel metadata for known broadcaster login names.

    Wraps :meth:`~TwitchCollector.collect_by_actors`. ``actor_ids`` are
    Twitch broadcaster login names. Returns channel metadata, NOT chat.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: Twitch broadcaster login names.
        tier: Tier string — only ``"free"`` is valid.
        date_from: Ignored — Twitch has no historical chat API.
        date_to: Ignored.
        max_results: Upper bound on returned records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry.
        ArenaCollectionError: Marks the task as FAILED.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "twitch: collect_by_actors started — run=%s actors=%d tier=%s",
        collection_run_id,
        len(actor_ids),
        tier,
    )
    _update_task_status(collection_run_id, _ARENA, "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="twitch",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"twitch: invalid tier '{tier}'. Only 'free' is supported."
        logger.error(msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="twitch",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise ArenaCollectionError(msg, arena=_ARENA, platform="twitch")

    collector = TwitchCollector()

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
            "twitch: rate limited on collect_by_actors for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error("twitch: collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="twitch",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise

    count = len(records)
    logger.info(
        "twitch: collect_by_actors completed — run=%s records=%d",
        collection_run_id,
        count,
    )
    _update_task_status(collection_run_id, _ARENA, "completed", records_collected=count)
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="twitch",
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
    }


@celery_app.task(
    name="issue_observatory.arenas.twitch.tasks.health_check",
    bind=False,
)
def twitch_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the Twitch arena (Helix API only).

    Delegates to :meth:`~TwitchCollector.health_check`, which calls
    ``GET /streams?first=1`` with an app access token.

    NOTE: This only checks the Helix REST API. The EventSub WebSocket used
    for real-time chat is not checked here.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = TwitchCollector()
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info(
        "twitch: health_check status=%s", result.get("status", "unknown")
    )
    return result
