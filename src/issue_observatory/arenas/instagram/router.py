"""Standalone FastAPI router for the Instagram arena.

Exposes three endpoints that can be exercised independently of the Celery
task system:

- ``POST /instagram/collect/terms`` — collect posts matching hashtags.
- ``POST /instagram/collect/actors`` — collect posts from specific profiles.
- ``GET /instagram/health`` — arena connectivity health check.

Mount in ``api/main.py``::

    from issue_observatory.arenas.instagram.router import router as instagram_router
    application.include_router(instagram_router, prefix="/arenas")

Resulting paths: ``/arenas/instagram/collect/terms`` etc.

Note: Because Bright Data uses asynchronous dataset delivery, the collect
endpoints may take several minutes to return. For production use, prefer
the Celery tasks which support long time limits and retries.

Danish targeting note: ``collect/terms`` converts keywords to hashtags.
For more reliable Danish content, use ``collect/actors`` with known Danish
Instagram account usernames.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.instagram.collector import InstagramCollector
from issue_observatory.core.credential_pool import get_credential_pool
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)

router = APIRouter(prefix="/instagram", tags=["instagram"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectByTermsRequest(BaseModel):
    """Request body for the collect/terms endpoint.

    Attributes:
        terms: Keywords or hashtags to query. Terms are converted to
            Instagram hashtags for discovery (spaces stripped, ``#`` prepended).
            Terms already starting with ``#`` are used as-is.
        tier: Tier to use — ``"medium"`` (Bright Data, default) or
            ``"premium"`` (MCL stub, not yet available).
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
        actor_ids: Instagram usernames (without ``@``) or full profile URLs
            (e.g. ``drnyheder`` or ``https://www.instagram.com/drnyheder``).
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
    """Collect Instagram posts matching hashtags derived from search terms.

    Converts each term to an Instagram hashtag and submits a Bright Data
    request. Instagram has no native full-text search; hashtag-based
    collection is the primary term-based discovery mechanism.

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
    collector = InstagramCollector(credential_pool=credential_pool)

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
    """Collect Instagram posts from specific profiles.

    This is the recommended mode for Danish content collection — target
    known Danish media outlets, politicians, and organizational accounts.

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
    collector = InstagramCollector(credential_pool=credential_pool)

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
    """Run a connectivity health check for the Instagram arena.

    Tests the Bright Data API token and service reachability.

    Returns:
        Dict with ``status``, ``arena``, ``platform``, ``checked_at``,
        and optionally ``detail`` and ``tier_tested``.
    """
    credential_pool = get_credential_pool()
    collector = InstagramCollector(credential_pool=credential_pool)
    return await collector.health_check()
