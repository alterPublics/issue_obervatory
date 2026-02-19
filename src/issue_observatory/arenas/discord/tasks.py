"""Celery tasks for the Discord arena.

Wraps :class:`~issue_observatory.arenas.discord.collector.DiscordCollector`
methods as Celery tasks with automatic retry behaviour and collection run
status tracking.

Task naming convention::

    issue_observatory.arenas.discord.tasks.<action>

Retry policy:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff
  (up to ``max_retries=3``). Discord may return HTTP 429 on per-route or
  global rate limit exhaustion.
- ``ArenaCollectionError`` is logged and re-raised so Celery marks the task
  FAILED.

All tasks update the ``collection_tasks`` row as best-effort (DB failures are
logged at WARNING and do not mask collection outcomes).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from issue_observatory.arenas.discord.collector import DiscordCollector
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
)
from issue_observatory.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_ARENA = "discord"


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
            "discord: failed to update collection_tasks status to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# arenas_config helper
# ---------------------------------------------------------------------------


def _load_arenas_config(query_design_id: str) -> dict:
    """Load ``arenas_config`` from the QueryDesign row identified by *query_design_id*.

    Uses a synchronous SQLAlchemy session (Celery worker context).  Returns an
    empty dict if the design is not found or on any DB error.

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
            "discord: failed to load arenas_config for design %s: %s",
            query_design_id,
            exc,
        )
    return {}


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.discord.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def discord_collect_terms(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    terms: list[str],
    channel_ids: list[str] | None = None,
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
) -> dict[str, Any]:
    """Collect Discord messages matching the supplied search terms.

    Wraps :meth:`~DiscordCollector.collect_by_terms` as an idempotent
    Celery task. Updates the ``collection_tasks`` row with progress and
    final status.

    NOTE: Discord bots cannot search by keyword. All term matching happens
    client-side. ``channel_ids`` is required — without it collection fails.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms matched client-side against message content.
        channel_ids: Discord channel snowflake IDs to retrieve messages from.
        tier: Tier string — only ``"free"`` is valid for Discord.
        date_from: ISO 8601 earliest publication date (inclusive).
        date_to: ISO 8601 latest publication date (inclusive).
        max_results: Upper bound on returned records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    logger.info(
        "discord: collect_by_terms started — run=%s terms=%d channels=%s tier=%s",
        collection_run_id,
        len(terms),
        len(channel_ids) if channel_ids else 0,
        tier,
    )
    _update_task_status(collection_run_id, _ARENA, "running")

    # GR-04: read researcher-configured extra channel IDs from arenas_config.
    arenas_config = _load_arenas_config(query_design_id)
    extra_channel_ids: list[str] | None = None
    discord_config = arenas_config.get("discord") or {}
    if isinstance(discord_config, dict):
        raw_channels = discord_config.get("custom_channel_ids")
        if isinstance(raw_channels, list) and raw_channels:
            extra_channel_ids = [str(c) for c in raw_channels if c]

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"discord: invalid tier '{tier}'. Only 'free' is supported."
        logger.error(msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        raise ArenaCollectionError(msg, arena=_ARENA, platform="discord")

    collector = DiscordCollector()

    try:
        records = asyncio.run(
            collector.collect_by_terms(
                terms=terms,
                tier=tier_enum,
                date_from=date_from,
                date_to=date_to,
                max_results=max_results,
                channel_ids=channel_ids,
                extra_channel_ids=extra_channel_ids,
            )
        )
    except ArenaRateLimitError:
        logger.warning(
            "discord: rate limited on collect_by_terms for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error("discord: collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        raise

    count = len(records)
    logger.info(
        "discord: collect_by_terms completed — run=%s records=%d",
        collection_run_id,
        count,
    )
    _update_task_status(collection_run_id, _ARENA, "completed", records_collected=count)

    return {
        "records_collected": count,
        "status": "completed",
        "arena": _ARENA,
        "tier": tier,
    }


@celery_app.task(
    name="issue_observatory.arenas.discord.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def discord_collect_actors(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    actor_ids: list[str],
    channel_ids: list[str] | None = None,
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
) -> dict[str, Any]:
    """Collect Discord messages authored by specific Discord user IDs.

    Wraps :meth:`~DiscordCollector.collect_by_actors`. ``actor_ids`` are
    Discord user snowflake IDs. ``channel_ids`` is required.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: Discord user snowflake IDs to filter messages by.
        channel_ids: Discord channel snowflake IDs to search within.
        tier: Tier string — only ``"free"`` is valid.
        date_from: ISO 8601 earliest publication date (inclusive).
        date_to: ISO 8601 latest publication date (inclusive).
        max_results: Upper bound on returned records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry.
        ArenaCollectionError: Marks the task as FAILED.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    logger.info(
        "discord: collect_by_actors started — run=%s actors=%d channels=%s tier=%s",
        collection_run_id,
        len(actor_ids),
        len(channel_ids) if channel_ids else 0,
        tier,
    )
    _update_task_status(collection_run_id, _ARENA, "running")

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"discord: invalid tier '{tier}'. Only 'free' is supported."
        logger.error(msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        raise ArenaCollectionError(msg, arena=_ARENA, platform="discord")

    collector = DiscordCollector()

    try:
        records = asyncio.run(
            collector.collect_by_actors(
                actor_ids=actor_ids,
                tier=tier_enum,
                date_from=date_from,
                date_to=date_to,
                max_results=max_results,
                channel_ids=channel_ids,
            )
        )
    except ArenaRateLimitError:
        logger.warning(
            "discord: rate limited on collect_by_actors for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error("discord: collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        raise

    count = len(records)
    logger.info(
        "discord: collect_by_actors completed — run=%s records=%d",
        collection_run_id,
        count,
    )
    _update_task_status(collection_run_id, _ARENA, "completed", records_collected=count)

    return {
        "records_collected": count,
        "status": "completed",
        "arena": _ARENA,
        "tier": tier,
    }


@celery_app.task(
    name="issue_observatory.arenas.discord.tasks.health_check",
    bind=False,
)
def discord_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the Discord arena.

    Delegates to :meth:`~DiscordCollector.health_check`, which calls
    ``GET /gateway`` with the configured bot token and verifies a 200 response.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = DiscordCollector()
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info(
        "discord: health_check status=%s", result.get("status", "unknown")
    )
    return result
