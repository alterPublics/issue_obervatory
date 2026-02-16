"""Standalone FastAPI router for the Google Autocomplete arena.

This router can be imported and mounted independently of the full application
stack for testing or ad-hoc collection without a collection run.

Mount in the main app::

    from issue_observatory.arenas.google_autocomplete.router import router as autocomplete_router
    app.include_router(autocomplete_router, prefix="/api/arenas")

Or run standalone (for local testing)::

    import uvicorn
    from fastapi import FastAPI
    from issue_observatory.arenas.google_autocomplete.router import router

    app = FastAPI()
    app.include_router(router)
    uvicorn.run(app, host="0.0.0.0", port=8080)

Endpoints:

- ``POST /google-autocomplete/collect``  — ad-hoc collection by terms.
- ``GET  /google-autocomplete/health``   — arena health check.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.google_autocomplete.collector import GoogleAutocompleteCollector
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

router = APIRouter(prefix="/google-autocomplete", tags=["Google Autocomplete"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectRequest(BaseModel):
    """Request body for ad-hoc Google Autocomplete collection.

    Attributes:
        terms: One or more search terms to get autocomplete suggestions for.
        tier: Operational tier — ``"free"`` (default), ``"medium"``, or
            ``"premium"``.
        max_results: Maximum total suggestion records to return.
    """

    terms: list[str] = Field(..., min_length=1, description="Search terms.")
    tier: str = Field(
        default="free",
        description="Operational tier: free, medium, or premium.",
    )
    max_results: int = Field(
        default=100,
        ge=1,
        le=50_000,
        description="Maximum suggestion records to return (1–50,000).",
    )


class CollectResponse(BaseModel):
    """Response body for ad-hoc collection.

    Attributes:
        count: Number of suggestion records returned.
        tier: Tier used for collection.
        arena: Arena name (always ``"google_autocomplete"``).
        records: Normalized content record dicts.
    """

    count: int
    tier: str
    arena: str
    records: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post(
    "/collect",
    response_model=CollectResponse,
    summary="Ad-hoc Google Autocomplete collection",
    description=(
        "Collect Google Autocomplete suggestions for the supplied terms without "
        "creating a full collection run.  Intended for testing arena connectivity "
        "and exploring suggestion quality.  Credits are not deducted by this "
        "endpoint — use the collection run API for credit-tracked collection."
    ),
)
async def collect(
    body: CollectRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect Google Autocomplete suggestions for the given terms.

    Args:
        body: Request body containing terms, tier, and max_results.
        current_user: Injected active user (from JWT cookie or bearer token).

    Returns:
        Normalized suggestion records and collection metadata.

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
                "Valid values: 'free', 'medium', 'premium'."
            ),
        )

    credential_pool = CredentialPool() if tier_enum != Tier.FREE else None
    collector = GoogleAutocompleteCollector(credential_pool=credential_pool)

    try:
        records = await collector.collect_by_terms(
            terms=body.terms,
            tier=tier_enum,
            max_results=body.max_results,
        )
    except NoCredentialAvailableError as exc:
        logger.warning(
            "google_autocomplete router: no credential for tier=%s user=%s: %s",
            body.tier,
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"No API credential configured for Google Autocomplete at tier '{body.tier}'. "
                "Ask an administrator to add a credential."
            ),
        ) from exc
    except ArenaRateLimitError as exc:
        logger.warning(
            "google_autocomplete router: rate limited (retry_after=%.0fs) user=%s",
            exc.retry_after,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Google Autocomplete API rate limited. "
                f"Retry after {exc.retry_after:.0f} seconds."
            ),
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaAuthError as exc:
        logger.error(
            "google_autocomplete router: auth error for tier=%s user=%s: %s",
            body.tier,
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Google Autocomplete API rejected the credential. "
                "Ask an administrator to verify the API key."
            ),
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "google_autocomplete router: collection error for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google Autocomplete collection failed: {exc}",
        ) from exc

    logger.info(
        "google_autocomplete router: collected %d suggestions for user=%s tier=%s",
        len(records),
        current_user.id,
        body.tier,
    )
    return CollectResponse(
        count=len(records),
        tier=body.tier,
        arena="google_autocomplete",
        records=records,
    )


@router.get(
    "/health",
    summary="Google Autocomplete arena health check",
    description=(
        "Verify that the Google Autocomplete endpoint is reachable.  "
        "Tests the FREE tier undocumented endpoint by default.  "
        "Returns a status dict with one of: ``ok``, ``degraded``, or ``down``."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Run a health check against the Google Autocomplete endpoint.

    Args:
        current_user: Injected active user (authentication required to
            prevent unauthenticated probing).

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = GoogleAutocompleteCollector()
    result = await collector.health_check()
    logger.info(
        "google_autocomplete router: health_check called by user=%s — status=%s",
        current_user.id,
        result.get("status"),
    )
    return result
