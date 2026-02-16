"""FastAPI standalone router for the Threads arena.

Provides independently testable endpoints for term-based and actor-based
collection, plus a health check.  All endpoints mount under the ``/threads``
prefix when included in the main application under ``/arenas``.

Endpoint summary:
- ``POST /threads/collect/terms``  — collect posts matching search terms
- ``POST /threads/collect/actors`` — collect posts by actor IDs (PRIMARY mode)
- ``GET  /threads/health``         — verify Threads API connectivity

At FREE tier, ``/collect/terms`` falls back to actor-based collection with
client-side keyword filtering (global search is unavailable in the Threads
API).  Supply ``DEFAULT_DANISH_THREADS_ACCOUNTS`` in config to make this mode
useful.

Usage in integration tests (inject a mock credential pool)::

    from fastapi.testclient import TestClient
    from issue_observatory.arenas.threads.router import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.threads.collector import ThreadsCollector
from issue_observatory.core.credential_pool import get_credential_pool
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)

router = APIRouter(prefix="/threads", tags=["threads"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CollectByTermsRequest(BaseModel):
    """Request body for term-based Threads collection.

    Attributes:
        terms: Search terms to match in post text (case-insensitive).
        tier: Operational tier (``"free"`` or ``"medium"``).  Defaults to
            ``"free"``.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
        max_results: Upper bound on returned records.  Defaults to 100.
    """

    terms: list[str]
    tier: str = "free"
    date_from: datetime | None = None
    date_to: datetime | None = None
    max_results: int = 100


class CollectByActorsRequest(BaseModel):
    """Request body for actor-based Threads collection.

    Attributes:
        actor_ids: Threads user IDs or usernames to collect posts from.
        tier: Operational tier.  Defaults to ``"free"``.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
        max_results: Upper bound on returned records.  Defaults to 100.
    """

    actor_ids: list[str]
    tier: str = "free"
    date_from: datetime | None = None
    date_to: datetime | None = None
    max_results: int = 100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_tier(tier_str: str) -> Tier:
    """Resolve a tier string to a :class:`Tier` enum value.

    Args:
        tier_str: ``"free"``, ``"medium"``, or ``"premium"``.

    Returns:
        The corresponding :class:`Tier` enum value.

    Raises:
        HTTPException: 400 if the tier string is unrecognised.
    """
    try:
        return Tier(tier_str)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tier '{tier_str}'. Valid values: free, medium, premium.",
        )


def _build_collector() -> ThreadsCollector:
    """Instantiate a :class:`ThreadsCollector` with the application credential pool.

    Returns:
        A :class:`ThreadsCollector` wired to the singleton credential pool.
    """
    credential_pool = get_credential_pool()
    return ThreadsCollector(credential_pool=credential_pool)


def _handle_collection_error(exc: Exception) -> HTTPException:
    """Convert a collection exception to an appropriate :class:`HTTPException`.

    Args:
        exc: The exception raised by a collector method.

    Returns:
        An :class:`HTTPException` with an appropriate status code and detail.
    """
    if isinstance(exc, NoCredentialAvailableError):
        return HTTPException(
            status_code=503,
            detail=f"No Threads credential available: {exc}",
        )
    if isinstance(exc, ArenaAuthError):
        return HTTPException(
            status_code=401,
            detail=f"Threads token expired or invalid: {exc}",
        )
    if isinstance(exc, ArenaRateLimitError):
        return HTTPException(
            status_code=429,
            detail=f"Threads API rate limit hit: {exc}",
        )
    if isinstance(exc, NotImplementedError):
        return HTTPException(
            status_code=501,
            detail=str(exc),
        )
    return HTTPException(
        status_code=500,
        detail=f"Threads collection error: {exc}",
    )


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post(
    "/collect/terms",
    summary="Collect Threads posts matching search terms",
    response_description="Count and list of normalized content records.",
)
async def collect_by_terms(
    request: CollectByTermsRequest,
) -> dict[str, Any]:
    """Collect Threads posts matching one or more search terms.

    At FREE tier, global keyword search is not available in the Threads API.
    This endpoint falls back to collecting from
    ``DEFAULT_DANISH_THREADS_ACCOUNTS`` (if configured) and filtering
    client-side.  Returns an empty list if no accounts are configured.

    At MEDIUM tier, returns HTTP 501 (MCL integration not yet implemented).

    Args:
        request: Collection parameters including terms, tier, date range, and
            result cap.

    Returns:
        JSON with ``count`` (int) and ``records`` (list of normalized dicts).

    Raises:
        HTTPException 400: Unrecognised tier value.
        HTTPException 401: Token expired or invalid.
        HTTPException 429: Rate limit hit.
        HTTPException 501: MCL tier not yet implemented.
        HTTPException 503: No credential available.
    """
    tier = _resolve_tier(request.tier)
    collector = _build_collector()
    try:
        results = await collector.collect_by_terms(
            terms=request.terms,
            tier=tier,
            date_from=request.date_from,
            date_to=request.date_to,
            max_results=request.max_results,
        )
    except (
        NoCredentialAvailableError,
        ArenaAuthError,
        ArenaRateLimitError,
        ArenaCollectionError,
        NotImplementedError,
    ) as exc:
        raise _handle_collection_error(exc) from exc

    return {"count": len(results), "records": results}


@router.post(
    "/collect/actors",
    summary="Collect Threads posts by actor IDs (primary mode)",
    response_description="Count and list of normalized content records.",
)
async def collect_by_actors(
    request: CollectByActorsRequest,
) -> dict[str, Any]:
    """Collect Threads posts published by specific actors.

    This is the PRIMARY collection mode for the Threads arena at FREE tier.
    Actor IDs should be Threads user IDs or usernames.

    At MEDIUM tier, returns HTTP 501 (MCL integration not yet implemented).

    Args:
        request: Collection parameters including actor IDs, tier, date range,
            and result cap.

    Returns:
        JSON with ``count`` (int) and ``records`` (list of normalized dicts).

    Raises:
        HTTPException 400: Unrecognised tier value.
        HTTPException 401: Token expired or invalid.
        HTTPException 429: Rate limit hit.
        HTTPException 501: MCL tier not yet implemented.
        HTTPException 503: No credential available.
    """
    tier = _resolve_tier(request.tier)
    collector = _build_collector()
    try:
        results = await collector.collect_by_actors(
            actor_ids=request.actor_ids,
            tier=tier,
            date_from=request.date_from,
            date_to=request.date_to,
            max_results=request.max_results,
        )
    except (
        NoCredentialAvailableError,
        ArenaAuthError,
        ArenaRateLimitError,
        ArenaCollectionError,
        NotImplementedError,
    ) as exc:
        raise _handle_collection_error(exc) from exc

    return {"count": len(results), "records": results}


@router.get(
    "/health",
    summary="Threads API health check",
    response_description="Health status dict.",
)
async def health() -> dict[str, Any]:
    """Verify that the Threads API is reachable with the configured token.

    Calls ``GET /me?fields=id,username`` to confirm token validity and API
    availability.

    Returns:
        JSON with ``status`` (``"ok"`` | ``"degraded"`` | ``"down"``),
        ``arena``, ``platform``, ``checked_at``, and optionally ``username``
        or ``detail``.
    """
    collector = _build_collector()
    return await collector.health_check()
