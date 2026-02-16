"""Celery tasks for the Telegram arena.

Wraps :class:`TelegramCollector` methods as Celery tasks with automatic retry
behaviour, collection run status tracking, and error reporting.

Task naming::

    issue_observatory.arenas.telegram.tasks.<action>

Retry policy:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff
  (``autoretry_for`` + ``retry_backoff=True``), up to ``max_retries=3``.
  The ``retry_after`` attribute from ``ArenaRateLimitError`` is the exact
  FloodWaitError seconds from Telegram; Celery backoff is a safety net on
  top of this.
- ``NoCredentialAvailableError`` is treated as a fatal failure — if all
  credentials are banned or on cooldown, the task should not retry
  indefinitely.
- Other ``ArenaCollectionError`` subclasses are logged and re-raised.

Asyncio integration:
- Telethon is natively async.  Celery workers use
  ``asyncio.run()`` to execute the async collector inside the sync task
  wrapper.  This is the same pattern used by other arena tasks (Bluesky,
  Reddit, YouTube).

Database updates:
- Best-effort via ``_update_task_status()`` — DB failures are logged at
  WARNING and do not mask the collection outcome.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from issue_observatory.arenas.telegram.collector import TelegramCollector
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
            "telegram: failed to update collection_tasks to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.telegram.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=600,
    acks_late=True,
)
def telegram_collect_terms(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    terms: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
    channel_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Collect Telegram messages matching a list of search terms.

    Searches each term across the configured Danish channel list (and any
    additional channels in ``channel_ids``) using the Telethon MTProto client.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms to query across monitored channels.
        tier: Tier string — always ``"free"`` for Telegram.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
        max_results: Optional cap on total records.
        channel_ids: Additional channel usernames or numeric IDs to search
            beyond the default Danish channel list.

    Returns:
        Dict with:
        - ``records_collected`` (int): Number of normalized records.
        - ``status`` (str): ``"completed"``.
        - ``arena`` (str): ``"social_media"``.
        - ``platform`` (str): ``"telegram"``.
        - ``tier`` (str): ``"free"``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
            The ``retry_after`` attribute reflects the exact FloodWaitError wait.
        ArenaCollectionError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415
    from issue_observatory.core.credential_pool import get_credential_pool  # noqa: PLC0415

    logger.info(
        "telegram: collect_by_terms started — run=%s terms=%d",
        collection_run_id,
        len(terms),
    )
    _update_task_status(collection_run_id, "social_media", "running")

    credential_pool = get_credential_pool()
    collector = TelegramCollector(credential_pool=credential_pool)

    try:
        records = asyncio.run(
            collector.collect_by_terms(
                terms=terms,
                tier=Tier.FREE,
                date_from=date_from,
                date_to=date_to,
                max_results=max_results,
                actor_ids=channel_ids,
            )
        )
    except NoCredentialAvailableError as exc:
        msg = f"telegram: no credential available: {exc}"
        logger.error(msg)
        _update_task_status(collection_run_id, "social_media", "failed", error_message=msg)
        raise ArenaCollectionError(
            msg, arena="social_media", platform="telegram"
        ) from exc
    except ArenaRateLimitError:
        logger.warning(
            "telegram: FloodWaitError on collect_by_terms for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error("telegram: collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, "social_media", "failed", error_message=msg)
        raise

    count = len(records)
    logger.info(
        "telegram: collect_by_terms completed — run=%s records=%d",
        collection_run_id,
        count,
    )
    _update_task_status(
        collection_run_id, "social_media", "completed", records_collected=count
    )
    return {
        "records_collected": count,
        "status": "completed",
        "arena": "social_media",
        "platform": "telegram",
        "tier": "free",
    }


@celery_app.task(
    name="issue_observatory.arenas.telegram.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=600,
    acks_late=True,
)
def telegram_collect_actors(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    actor_ids: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
) -> dict[str, Any]:
    """Collect Telegram messages from specific channels.

    Each ``actor_id`` is a public Telegram channel username (e.g.
    ``"dr_nyheder"``) or a numeric channel ID.  Messages are fetched
    in reverse-chronological order with optional date filtering.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: Telegram channel usernames or numeric IDs.
        tier: Tier string — always ``"free"`` for Telegram.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
        max_results: Optional cap on total records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``,
        ``platform``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415
    from issue_observatory.core.credential_pool import get_credential_pool  # noqa: PLC0415

    logger.info(
        "telegram: collect_by_actors started — run=%s actors=%d",
        collection_run_id,
        len(actor_ids),
    )
    _update_task_status(collection_run_id, "social_media", "running")

    credential_pool = get_credential_pool()
    collector = TelegramCollector(credential_pool=credential_pool)

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
    except NoCredentialAvailableError as exc:
        msg = f"telegram: no credential available: {exc}"
        logger.error(msg)
        _update_task_status(collection_run_id, "social_media", "failed", error_message=msg)
        raise ArenaCollectionError(
            msg, arena="social_media", platform="telegram"
        ) from exc
    except ArenaRateLimitError:
        logger.warning(
            "telegram: FloodWaitError on collect_by_actors for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error(
            "telegram: actor collection error for run=%s: %s", collection_run_id, msg
        )
        _update_task_status(collection_run_id, "social_media", "failed", error_message=msg)
        raise

    count = len(records)
    logger.info(
        "telegram: collect_by_actors completed — run=%s records=%d",
        collection_run_id,
        count,
    )
    _update_task_status(
        collection_run_id, "social_media", "completed", records_collected=count
    )
    return {
        "records_collected": count,
        "status": "completed",
        "arena": "social_media",
        "platform": "telegram",
        "tier": "free",
    }


@celery_app.task(
    name="issue_observatory.arenas.telegram.tasks.health_check",
    bind=False,
)
def telegram_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the Telegram arena.

    Connects to Telegram via the first available credential and calls
    ``client.get_me()`` to verify the session is valid.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    from issue_observatory.core.credential_pool import get_credential_pool  # noqa: PLC0415

    credential_pool = get_credential_pool()
    collector = TelegramCollector(credential_pool=credential_pool)
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info("telegram: health_check status=%s", result.get("status", "unknown"))
    return result
