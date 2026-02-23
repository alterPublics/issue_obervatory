"""Redis pub/sub event bus for real-time collection run status updates.

Arena Celery tasks call :func:`publish_task_update` after each status change.
The FastAPI SSE endpoint subscribes to the corresponding channel and forwards
messages to connected browser clients.

Channel naming convention::

    collection:{run_id}

Message shapes:

Task update (published by arena tasks at status transitions and on batch
completion)::

    {
        "event": "task_update",
        "arena": "bluesky",
        "platform": "bluesky",
        "status": "running",        # pending | running | completed | failed
        "records_collected": 47,
        "duplicates_skipped": 3,
        "error_message": null,
        "elapsed_seconds": 12.4
    }

Run complete (published by the orchestration layer when all tasks finish)::

    {
        "event": "run_complete",
        "status": "completed",      # completed | failed | cancelled
        "records_collected": 312,
        "credits_spent": 0
    }

Usage in arena tasks::

    from issue_observatory.core.event_bus import publish_task_update

    publish_task_update(
        redis_url=settings.redis_url,
        run_id=collection_run_id,
        arena="bluesky",
        platform="bluesky",
        status="running",
        records_collected=0,
        duplicates_skipped=0,
        error_message=None,
        elapsed_seconds=0.0,
    )

The function is synchronous so it can be called from Celery task bodies
(which run in a standard thread-pool worker, not inside an event loop).
It creates a short-lived synchronous Redis connection, publishes the message,
then closes the connection immediately.  This is intentionally fire-and-forget:
a publish failure is logged at WARNING and never propagates to the caller.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


def publish_task_update(
    redis_url: str,
    run_id: str,
    arena: str,
    platform: str,
    status: str,
    records_collected: int = 0,
    duplicates_skipped: int = 0,
    error_message: Optional[str] = None,
    elapsed_seconds: float = 0.0,
) -> None:
    """Publish a task-update event to the collection run's Redis pub/sub channel.

    Designed to be called from synchronous Celery task bodies.  Opens a
    short-lived synchronous Redis connection, publishes one message, and
    closes immediately.

    The message is silently dropped (with a WARNING log) if Redis is
    unavailable or if the ``redis`` package is not installed — this must
    never break a collection task.

    Args:
        redis_url: Redis connection URL (e.g. ``redis://localhost:6379/0``).
            Use the application's ``settings.redis_url``.
        run_id: UUID string of the collection run (used as the channel suffix).
        arena: Arena identifier (e.g. ``"bluesky"``).
        platform: Platform identifier (e.g. ``"bluesky"``).
        status: Task status string: ``"pending"``, ``"running"``,
            ``"completed"``, or ``"failed"``.
        records_collected: Number of records collected so far in this task.
        duplicates_skipped: Number of duplicate records skipped (already in DB).
        error_message: Human-readable error description, or ``None``.
        elapsed_seconds: Wall-clock seconds since this task started, or 0.0
            if not tracked by the caller.
    """
    try:
        import redis as redis_lib  # noqa: PLC0415

        payload: dict = {
            "event": "task_update",
            "arena": arena,
            "platform": platform,
            "status": status,
            "records_collected": records_collected,
            "duplicates_skipped": duplicates_skipped,
            "error_message": error_message,
            "elapsed_seconds": round(elapsed_seconds, 1),
        }
        channel = f"collection:{run_id}"
        r = redis_lib.from_url(redis_url, decode_responses=True)
        try:
            r.publish(channel, json.dumps(payload))
            logger.debug(
                "event_bus: published task_update arena=%s status=%s run=%s",
                arena,
                status,
                run_id,
            )
        finally:
            r.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "event_bus: failed to publish task_update for run=%s arena=%s: %s",
            run_id,
            arena,
            exc,
        )


def publish_run_complete(
    redis_url: str,
    run_id: str,
    status: str,
    records_collected: int,
    credits_spent: int,
) -> None:
    """Publish a run-complete event to the collection run's Redis pub/sub channel.

    Called by the orchestration layer (``workers/tasks.py``) once all
    per-arena tasks have reached a terminal state.  Also suitable for
    calling after a manual cancel.

    Args:
        redis_url: Redis connection URL.
        run_id: UUID string of the collection run.
        status: Terminal status: ``"completed"``, ``"failed"``, or
            ``"cancelled"``.
        records_collected: Aggregate records collected across all arenas.
        credits_spent: Total credits consumed by this run.
    """
    try:
        import redis as redis_lib  # noqa: PLC0415

        payload: dict = {
            "event": "run_complete",
            "status": status,
            "records_collected": records_collected,
            "credits_spent": credits_spent,
        }
        channel = f"collection:{run_id}"
        r = redis_lib.from_url(redis_url, decode_responses=True)
        try:
            r.publish(channel, json.dumps(payload))
            logger.info(
                "event_bus: published run_complete status=%s run=%s records=%d",
                status,
                run_id,
                records_collected,
            )
        finally:
            r.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "event_bus: failed to publish run_complete for run=%s: %s",
            run_id,
            exc,
        )


# ---------------------------------------------------------------------------
# Timing helper
# ---------------------------------------------------------------------------


def elapsed_since(start_ts: float) -> float:
    """Return wall-clock seconds elapsed since ``start_ts``.

    Args:
        start_ts: Timestamp from :func:`time.monotonic` recorded at task start.

    Returns:
        Elapsed seconds as a float.
    """
    return time.monotonic() - start_ts
