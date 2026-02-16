"""Standalone FastAPI router for the X/Twitter arena.

Exposes three endpoints that can be exercised independently of the Celery
task system:

- ``POST /x-twitter/collect/terms`` — collect tweets matching search terms.
- ``POST /x-twitter/collect/actors`` — collect tweets from specific accounts.
- ``GET /x-twitter/health`` — arena connectivity health check.

Mount in ``api/main.py``::

    from issue_observatory.arenas.x_twitter.router import router as x_twitter_router
    application.include_router(x_twitter_router, prefix="/arenas")

Resulting paths: ``/arenas/x-twitter/collect/terms`` etc.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.x_twitter.collector import XTwitterCollector
from issue_observatory.core.credential_pool import get_credential_pool
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)

router = APIRouter(prefix="/x-twitter", tags=["x-twitter"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectByTermsRequest(BaseModel):
    """Request body for the collect/terms endpoint.

    Attributes:
        terms: Search terms to query. X/Twitter operators are supported
            (e.g. ``#dkpol``, ``klimapolitik``, ``from:LarsLoekke``).
        tier: Tier to use — ``"medium"`` (TwitterAPI.io, default) or
            ``"premium"`` (X API v2 Pro).
        date_from: ISO date lower bound (``YYYY-MM-DD``), optional.
        date_to: ISO date upper bound (``YYYY-MM-DD``), optional.
        max_results: Maximum records to return. Defaults to 100.
    """

    terms: list[str]
    tier: str = "medium"
    date_from: str | None = None
    date_to: str | None = None
    max_results: int = 100


class CollectByActorsRequest(BaseModel):
    """Request body for the collect/actors endpoint.

    Attributes:
        actor_ids: Twitter user IDs (numeric strings) or handles (``@username``).
        tier: Tier to use — ``"medium"`` or ``"premium"``.
        date_from: ISO date lower bound (``YYYY-MM-DD``), optional.
        date_to: ISO date upper bound (``YYYY-MM-DD``), optional.
        max_results: Maximum records to return. Defaults to 100.
    """

    actor_ids: list[str]
    tier: str = "medium"
    date_from: str | None = None
    date_to: str | None = None
    max_results: int = 100


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post("/collect/terms")
async def collect_by_terms(
    request: CollectByTermsRequest,
) -> dict[str, Any]:
    """Collect tweets matching one or more search terms.

    Invokes :meth:`XTwitterCollector.collect_by_terms` directly (synchronous
    HTTP call, not via Celery). Suitable for interactive testing and small
    ad-hoc collections.

    Args:
        request: Search request parameters.

    Returns:
        Dict with ``count`` (int) and ``records`` (list of normalized dicts).

    Raises:
        HTTPException 422: If an unsupported tier is requested.
        HTTPException 429: On rate limit from upstream API.
        HTTPException 503: On connection error or missing credentials.
    """
    try:
        tier_enum = Tier(request.tier)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported tier '{request.tier}'. Use 'medium' or 'premium'.",
        )

    credential_pool = get_credential_pool()
    collector = XTwitterCollector(credential_pool=credential_pool)

    try:
        records = await collector.collect_by_terms(
            terms=request.terms,
            tier=tier_enum,
            date_from=request.date_from,
            date_to=request.date_to,
            max_results=request.max_results,
        )
    except NoCredentialAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ArenaRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except (ArenaAuthError, ArenaCollectionError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"count": len(records), "records": records}


@router.post("/collect/actors")
async def collect_by_actors(
    request: CollectByActorsRequest,
) -> dict[str, Any]:
    """Collect tweets from specific X/Twitter accounts.

    Accepts numeric user IDs or handles (with or without leading ``@``).

    Args:
        request: Actor collection request parameters.

    Returns:
        Dict with ``count`` (int) and ``records`` (list of normalized dicts).

    Raises:
        HTTPException 422: If an unsupported tier is requested.
        HTTPException 429: On rate limit from upstream API.
        HTTPException 503: On connection error or missing credentials.
    """
    try:
        tier_enum = Tier(request.tier)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported tier '{request.tier}'. Use 'medium' or 'premium'.",
        )

    credential_pool = get_credential_pool()
    collector = XTwitterCollector(credential_pool=credential_pool)

    try:
        records = await collector.collect_by_actors(
            actor_ids=request.actor_ids,
            tier=tier_enum,
            date_from=request.date_from,
            date_to=request.date_to,
            max_results=request.max_results,
        )
    except NoCredentialAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ArenaRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except (ArenaAuthError, ArenaCollectionError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"count": len(records), "records": records}


@router.get("/health")
async def health() -> dict[str, Any]:
    """Run a connectivity health check for the X/Twitter arena.

    Tests the first available tier (medium before premium). Returns the
    health status dict from :meth:`XTwitterCollector.health_check`.

    Returns:
        Dict with ``status``, ``arena``, ``platform``, ``checked_at``,
        and optionally ``detail`` and ``tier_tested``.
    """
    credential_pool = get_credential_pool()
    collector = XTwitterCollector(credential_pool=credential_pool)
    return await collector.health_check()
