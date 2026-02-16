"""Standalone FastAPI router for the Facebook arena.

Exposes three endpoints that can be exercised independently of the Celery
task system:

- ``POST /facebook/collect/terms`` — collect Facebook posts matching keywords.
- ``POST /facebook/collect/actors`` — collect posts from specific Facebook pages.
- ``GET /facebook/health`` — arena connectivity health check.

Mount in ``api/main.py``::

    from issue_observatory.arenas.facebook.router import router as facebook_router
    application.include_router(facebook_router, prefix="/arenas")

Resulting paths: ``/arenas/facebook/collect/terms`` etc.

Note: Because Bright Data uses asynchronous dataset delivery, the collect
endpoints may take several minutes to return. For production use, prefer
the Celery tasks which support long time limits and retries.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.facebook.collector import FacebookCollector
from issue_observatory.core.credential_pool import get_credential_pool
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)

router = APIRouter(prefix="/facebook", tags=["facebook"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectByTermsRequest(BaseModel):
    """Request body for the collect/terms endpoint.

    Attributes:
        terms: Keywords or phrases to query. Applied with country=DK targeting.
        tier: Tier to use — ``"medium"`` (Bright Data, default) or
            ``"premium"`` (MCL, raises NotImplementedError until approved).
        date_from: ISO date lower bound (``YYYY-MM-DD``), optional.
        date_to: ISO date upper bound (``YYYY-MM-DD``), optional.
        max_results: Maximum records to return. Defaults to 500.
    """

    terms: list[str]
    tier: str = "medium"
    date_from: str | None = None
    date_to: str | None = None
    max_results: int = 500


class CollectByActorsRequest(BaseModel):
    """Request body for the collect/actors endpoint.

    Attributes:
        actor_ids: Facebook page URLs (e.g. ``https://www.facebook.com/drnyheder``)
            or numeric page IDs.
        tier: Tier to use — ``"medium"`` (Bright Data, default) or
            ``"premium"`` (MCL stub, not yet available).
        date_from: ISO date lower bound (``YYYY-MM-DD``), optional.
        date_to: ISO date upper bound (``YYYY-MM-DD``), optional.
        max_results: Maximum records to return. Defaults to 500.
    """

    actor_ids: list[str]
    tier: str = "medium"
    date_from: str | None = None
    date_to: str | None = None
    max_results: int = 500


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post("/collect/terms")
async def collect_by_terms(
    request: CollectByTermsRequest,
) -> dict[str, Any]:
    """Collect Facebook posts matching one or more keywords.

    Invokes :meth:`FacebookCollector.collect_by_terms` directly. Uses Bright
    Data asynchronous dataset delivery — allow several minutes for results
    to be ready. For long-running collections, prefer the Celery task.

    Args:
        request: Search request parameters.

    Returns:
        Dict with ``count`` (int) and ``records`` (list of normalized dicts).

    Raises:
        HTTPException 422: If an unsupported tier is requested.
        HTTPException 429: On rate limit from Bright Data.
        HTTPException 501: For PREMIUM tier (MCL pending approval).
        HTTPException 503: On connection error or missing credentials.
    """
    try:
        tier_enum = Tier(request.tier)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported tier '{request.tier}'. Use 'medium'.",
        )

    credential_pool = get_credential_pool()
    collector = FacebookCollector(credential_pool=credential_pool)

    try:
        records = await collector.collect_by_terms(
            terms=request.terms,
            tier=tier_enum,
            date_from=request.date_from,
            date_to=request.date_to,
            max_results=request.max_results,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
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
    """Collect Facebook posts from specific pages.

    Accepts Facebook page URLs or numeric page IDs.

    Args:
        request: Actor collection request parameters.

    Returns:
        Dict with ``count`` (int) and ``records`` (list of normalized dicts).

    Raises:
        HTTPException 422: If an unsupported tier is requested.
        HTTPException 429: On rate limit from Bright Data.
        HTTPException 501: For PREMIUM tier (MCL pending approval).
        HTTPException 503: On connection error or missing credentials.
    """
    try:
        tier_enum = Tier(request.tier)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported tier '{request.tier}'. Use 'medium'.",
        )

    credential_pool = get_credential_pool()
    collector = FacebookCollector(credential_pool=credential_pool)

    try:
        records = await collector.collect_by_actors(
            actor_ids=request.actor_ids,
            tier=tier_enum,
            date_from=request.date_from,
            date_to=request.date_to,
            max_results=request.max_results,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except NoCredentialAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ArenaRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except (ArenaAuthError, ArenaCollectionError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"count": len(records), "records": records}


@router.get("/health")
async def health() -> dict[str, Any]:
    """Run a connectivity health check for the Facebook arena.

    Tests the Bright Data API token and service reachability.

    Returns:
        Dict with ``status``, ``arena``, ``platform``, ``checked_at``,
        and optionally ``detail`` and ``tier_tested``.
    """
    credential_pool = get_credential_pool()
    collector = FacebookCollector(credential_pool=credential_pool)
    return await collector.health_check()
