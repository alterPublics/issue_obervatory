"""Standalone FastAPI router for the Google Search arena.

This router can be imported and mounted independently of the full application
stack for testing or ad-hoc collection without a collection run.

Mount in the main app::

    from issue_observatory.arenas.google_search.router import router as google_search_router
    app.include_router(google_search_router, prefix="/api/arenas")

Or run standalone (for local testing)::

    import uvicorn
    from fastapi import FastAPI
    from issue_observatory.arenas.google_search.router import router

    app = FastAPI()
    app.include_router(router)
    uvicorn.run(app, host="0.0.0.0", port=8080)

Endpoints:

- ``POST /google-search/collect``  — ad-hoc collection by terms (authenticated).
- ``GET  /google-search/health``   — arena health check (authenticated).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.google_search.collector import GoogleSearchCollector
from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.core.credential_pool import CredentialPool
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.core.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/google-search", tags=["Google Search"])

# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectRequest(BaseModel):
    """Request body for ad-hoc Google Search collection.

    Attributes:
        terms: One or more search terms to query.
        tier: Operational tier — ``"medium"`` (Serper.dev, default) or
            ``"premium"`` (SerpAPI).  ``"free"`` is accepted but returns
            an empty result set with an explanatory message.
        max_results: Maximum number of records to return.  Capped by the
            tier's ``max_results_per_run`` configuration.
    """

    terms: list[str] = Field(..., min_length=1, description="Search terms to query.")
    tier: str = Field(default="medium", description="Operational tier: medium or premium.")
    max_results: int = Field(
        default=100,
        ge=1,
        le=10_000,
        description="Maximum records to return (1–10,000).",
    )


class CollectResponse(BaseModel):
    """Response body for ad-hoc collection.

    Attributes:
        count: Number of records returned.
        tier: Tier used for collection.
        arena: Arena name (always ``"google_search"``).
        records: Normalized content record dicts.
        message: Optional informational message (e.g., tier guidance).
    """

    count: int
    tier: str
    arena: str
    records: list[dict[str, Any]]
    message: str | None = None


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post(
    "/collect",
    response_model=CollectResponse,
    summary="Ad-hoc Google Search collection",
    description=(
        "Collect Google Search results for the supplied terms without creating "
        "a full collection run.  Intended for testing arena connectivity and "
        "exploring result quality.  Credits are not deducted by this endpoint — "
        "use the collection run API for credit-tracked collection."
    ),
)
async def collect(
    body: CollectRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect Google Search results for the given terms.

    Args:
        body: Request body containing terms, tier, and max_results.
        current_user: Injected active user (from JWT cookie or bearer token).

    Returns:
        Normalized content records and collection metadata.

    Raises:
        HTTPException 400: If the tier value is invalid.
        HTTPException 402: If no API credential is available for the tier.
        HTTPException 429: If the upstream API is rate-limited.
        HTTPException 502: On upstream API errors.
    """
    try:
        tier_enum = Tier(body.tier)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid tier '{body.tier}'. "
                "Valid values: 'free' (returns empty), 'medium', 'premium'."
            ),
        )

    if tier_enum == Tier.FREE:
        logger.info(
            "google_search router: FREE tier requested by user=%s — returning empty with guidance.",
            current_user.id,
        )
        return CollectResponse(
            count=0,
            tier=body.tier,
            arena="google_search",
            records=[],
            message=(
                "Google Search has no free API. Try Google Autocomplete (free) "
                "for discovery, or upgrade to medium tier (Serper.dev) for "
                "search results."
            ),
        )

    credential_pool = CredentialPool()
    collector = GoogleSearchCollector(credential_pool=credential_pool)

    try:
        records = await collector.collect_by_terms(
            terms=body.terms,
            tier=tier_enum,
            max_results=body.max_results,
        )
    except NoCredentialAvailableError as exc:
        logger.warning(
            "google_search router: no credential for tier=%s user=%s: %s",
            body.tier,
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"No API credential configured for Google Search at tier '{body.tier}'. "
                "Ask an administrator to add a credential."
            ),
        ) from exc
    except ArenaRateLimitError as exc:
        logger.warning(
            "google_search router: rate limited (retry_after=%.0fs) user=%s",
            exc.retry_after,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Google Search API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaAuthError as exc:
        logger.error(
            "google_search router: auth error for tier=%s user=%s: %s",
            body.tier,
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Google Search API rejected the credential. "
                "Ask an administrator to verify the API key."
            ),
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "google_search router: collection error for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google Search collection failed: {exc}",
        ) from exc

    logger.info(
        "google_search router: collected %d records for user=%s tier=%s",
        len(records),
        current_user.id,
        body.tier,
    )
    return CollectResponse(
        count=len(records),
        tier=body.tier,
        arena="google_search",
        records=records,
    )


@router.get(
    "/health",
    summary="Google Search arena health check",
    description=(
        "Verify that the Serper.dev API is reachable and the configured "
        "credential is accepted.  Returns a status dict with one of: "
        "``ok``, ``degraded``, or ``down``."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Run a health check against the Serper.dev API.

    Args:
        current_user: Injected active user (authentication required to
            prevent unauthenticated probing of API credentials).

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    credential_pool = CredentialPool()
    collector = GoogleSearchCollector(credential_pool=credential_pool)
    result = await collector.health_check()
    logger.info(
        "google_search router: health_check called by user=%s — status=%s",
        current_user.id,
        result.get("status"),
    )
    return result
