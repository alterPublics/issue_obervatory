"""Health check route handlers for the Issue Observatory API.

Exposes three health endpoints:

``GET /api/health``
    Shallow liveness check: verifies the process is alive and can reach the
    database (``SELECT 1``) and Redis (``PING``).  Always returns HTTP 200;
    the ``status`` field distinguishes ``"ok"`` from ``"degraded"``.

``GET /api/arenas/health``
    Aggregate arena health: calls ``health_check()`` on every registered
    arena collector and returns a per-arena breakdown plus an overall status.
    Always returns HTTP 200; ``overall`` is ``"ok"``, ``"degraded"``, or
    ``"error"`` depending on arena statuses.

These endpoints are diagnostic — they must never raise HTTP 5xx errors.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import redis.asyncio as aioredis
import sqlalchemy as sa
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from issue_observatory.arenas.registry import autodiscover, list_arenas
from issue_observatory.config.settings import get_settings
from issue_observatory.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])

# ---------------------------------------------------------------------------
# Helper — DB check
# ---------------------------------------------------------------------------


async def _check_database() -> str:
    """Run ``SELECT 1`` against the configured database.

    Returns:
        ``"ok"`` if the query succeeds, ``"error"`` otherwise.
    """
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(sa.text("SELECT 1"))
        return "ok"
    except Exception:
        logger.exception("Health check: database unreachable")
        return "error"


# ---------------------------------------------------------------------------
# Helper — Redis check
# ---------------------------------------------------------------------------


async def _check_redis() -> str:
    """Send ``PING`` to the configured Redis instance.

    Returns:
        ``"ok"`` if Redis responds, ``"error"`` otherwise.
    """
    settings = get_settings()
    try:
        client: aioredis.Redis = aioredis.from_url(
            settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        await client.ping()
        await client.aclose()
        return "ok"
    except Exception:
        logger.exception("Health check: Redis unreachable")
        return "error"


# ---------------------------------------------------------------------------
# Helper — Celery worker check
# ---------------------------------------------------------------------------


async def _check_celery_workers() -> str:
    """Check if any Celery workers are responding.

    Uses ``celery_app.control.inspect().ping()`` to query active workers.
    This is a soft check: no workers responding returns ``"no_workers"``
    instead of ``"error"`` since the web app can function without workers
    (just no background collection tasks).

    Returns:
        ``"ok"`` if at least one worker responds, ``"no_workers"`` if none
        respond, or ``"error"`` if the Celery/Redis connection fails.
    """
    try:
        # Import Celery app here to avoid circular imports at module load.
        from issue_observatory.workers.celery_app import (  # noqa: PLC0415
            celery_app,
        )

        # Run the synchronous inspect().ping() in a thread pool to avoid
        # blocking the async event loop.
        loop = asyncio.get_running_loop()
        inspect = celery_app.control.inspect(timeout=2.0)
        ping_result = await loop.run_in_executor(None, inspect.ping)

        # ping_result is a dict like {"celery@hostname": {"ok": "pong"}}
        # or None if no workers responded.
        if ping_result and len(ping_result) > 0:
            return "ok"
        return "no_workers"
    except Exception:
        logger.exception("Health check: Celery inspect failed")
        return "error"


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------


@router.get("/api/health", include_in_schema=True)
async def system_health() -> JSONResponse:
    """Return process-level health including database and Redis connectivity.

    Performs lightweight checks in parallel:

    - ``SELECT 1`` against PostgreSQL.
    - ``PING`` against Redis.
    - ``celery_app.control.inspect().ping()`` to check for active workers.

    Always returns HTTP 200.  The ``status`` field is ``"ok"`` when all
    dependencies are reachable, ``"degraded"`` when one or more fail or
    when no Celery workers are responding (the web app still functions,
    but background tasks will not run).

    Returns:
        JSON with keys: ``status``, ``version``, ``database``, ``redis``,
        ``celery``, ``timestamp``.
    """
    db_status, redis_status, celery_status = await asyncio.gather(
        _check_database(),
        _check_redis(),
        _check_celery_workers(),
    )

    # Overall status is "ok" only if all three checks pass.
    # Celery "no_workers" is treated as degraded, not error, since the
    # web app still serves requests without background workers.
    if db_status == "ok" and redis_status == "ok" and celery_status == "ok":
        overall = "ok"
    else:
        overall = "degraded"

    payload = {
        "status": overall,
        "version": "0.1.0",
        "database": db_status,
        "redis": redis_status,
        "celery": celery_status,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    logger.info("system_health_check", extra={"health": payload})
    return JSONResponse(payload)


# ---------------------------------------------------------------------------
# GET /api/arenas/health
# ---------------------------------------------------------------------------


async def _arena_health(platform_name: str, cls: type) -> tuple[str, dict]:
    """Run ``health_check()`` for a single arena collector class.

    Args:
        platform_name: Unique platform key for the collector (registry key).
        cls: The ``ArenaCollector`` subclass.

    Returns:
        Tuple of ``(platform_name, health_dict)``.
    """
    try:
        collector = cls()
        result: dict = await collector.health_check()
        return platform_name, result
    except Exception:
        logger.exception("Arena health check failed", extra={"arena": platform_name})
        return platform_name, {
            "status": "error",
            "arena": platform_name,
            "error": "health_check raised an exception",
            "checked_at": datetime.now(UTC).isoformat(),
        }


@router.get("/api/arenas/health", include_in_schema=True)
async def arenas_health() -> JSONResponse:
    """Return health status for every registered arena collector.

    Calls ``health_check()`` on all arenas concurrently.  The aggregate
    ``overall`` status is:

    - ``"ok"`` — all arenas report ``"ok"``.
    - ``"degraded"`` — at least one arena reports ``"degraded"`` or
      ``"not_implemented"``, none report ``"error"`` or ``"down"``.
    - ``"error"`` — at least one arena reports ``"error"`` or ``"down"``.

    Always returns HTTP 200.

    Returns:
        JSON with keys: ``arenas`` (dict keyed by platform_name) and
        ``overall`` (aggregate status string).
    """
    autodiscover()
    arenas = list_arenas()

    from issue_observatory.arenas.registry import get_arena  # noqa: PLC0415

    tasks = [
        _arena_health(info["platform_name"], get_arena(info["platform_name"]))
        for info in arenas
    ]
    results: list[tuple[str, dict]] = await asyncio.gather(*tasks)

    arena_map: dict[str, dict] = {name: data for name, data in results}

    # Determine overall status
    statuses = {data.get("status", "error") for data in arena_map.values()}
    if "error" in statuses or "down" in statuses:
        overall = "error"
    elif statuses - {"ok"}:
        # Remaining non-ok statuses: degraded, not_implemented
        overall = "degraded"
    else:
        overall = "ok"

    payload = {
        "arenas": arena_map,
        "overall": overall,
    }
    logger.info("arenas_health_check", extra={"overall": overall, "count": len(arena_map)})
    return JSONResponse(payload)
