"""Standalone FastAPI router for the TikTok arena.

Provides ad-hoc collection endpoints for the TikTok Research API.
All endpoints require authentication (JWT cookie or bearer token).

Mount in the main app::

    from issue_observatory.arenas.tiktok.router import router as tiktok_router
    app.include_router(tiktok_router, prefix="/arenas")

Endpoints:

- ``POST /tiktok/collect/terms``  — collect by search terms (DK region).
- ``POST /tiktok/collect/actors`` — collect by TikTok usernames.
- ``GET  /tiktok/health``         — arena health check.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.tiktok.collector import TikTokCollector
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.core.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tiktok", tags=["TikTok"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectTermsRequest(BaseModel):
    """Request body for ad-hoc TikTok term-based collection.

    Attributes:
        terms: Search keywords. Region filter ``DK`` is applied automatically.
        max_results: Maximum video records to return.
        date_from: ISO 8601 lower date bound (optional, defaults to 30 days ago).
        date_to: ISO 8601 upper date bound (optional, defaults to today).
    """

    terms: list[str] = Field(..., min_length=1, description="Search keywords.")
    max_results: int = Field(
        default=100,
        ge=1,
        le=10_000,
        description="Maximum video records to return (1–10,000).",
    )
    date_from: str | None = Field(
        default=None,
        description="ISO 8601 lower date bound (e.g. '2026-01-01').",
    )
    date_to: str | None = Field(
        default=None,
        description="ISO 8601 upper date bound.",
    )


class CollectActorsRequest(BaseModel):
    """Request body for ad-hoc TikTok actor-based collection.

    Attributes:
        actor_ids: TikTok usernames (without leading ``@``).
        max_results: Maximum video records to return.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
    """

    actor_ids: list[str] = Field(
        ..., min_length=1, description="TikTok usernames (without leading @)."
    )
    max_results: int = Field(
        default=100,
        ge=1,
        le=10_000,
        description="Maximum video records to return (1–10,000).",
    )
    date_from: str | None = Field(default=None, description="ISO 8601 lower date bound.")
    date_to: str | None = Field(default=None, description="ISO 8601 upper date bound.")


class CollectResponse(BaseModel):
    """Response body for ad-hoc collection endpoints.

    Attributes:
        count: Number of video records returned.
        arena: Arena name (always ``"social_media"``).
        platform: Platform name (always ``"tiktok"``).
        records: Normalized content record dicts.
    """

    count: int
    arena: str
    platform: str
    records: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post(
    "/collect/terms",
    response_model=CollectResponse,
    summary="Ad-hoc TikTok term-based collection",
    description=(
        "Collect TikTok video metadata matching the supplied keywords. "
        "Applies ``region_code: DK`` filter automatically. "
        "Engagement metrics are subject to a 10-day accuracy lag. "
        "Requires TikTok Research API credentials in the CredentialPool."
    ),
)
async def collect_terms(
    body: CollectTermsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect TikTok videos matching the given search terms.

    Args:
        body: Request body with terms and optional date bounds.
        current_user: Injected active user.

    Returns:
        Normalized video records and collection metadata.

    Raises:
        HTTPException 429: If the TikTok API is rate-limited.
        HTTPException 401: If credentials are rejected.
        HTTPException 503: If no credential is available.
        HTTPException 502: On other upstream API errors.
    """
    collector = TikTokCollector()

    try:
        records = await collector.collect_by_terms(
            terms=body.terms,
            tier=Tier.FREE,
            date_from=body.date_from,
            date_to=body.date_to,
            max_results=body.max_results,
        )
    except NoCredentialAvailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No TikTok Research API credential available. Configure credentials first.",
        ) from exc
    except ArenaRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"TikTok API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"TikTok credential error: {exc}",
        ) from exc
    except ArenaCollectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"TikTok collection failed: {exc}",
        ) from exc

    logger.info(
        "tiktok router: collected %d videos (terms) for user=%s",
        len(records),
        current_user.id,
    )
    return CollectResponse(
        count=len(records),
        arena="social_media",
        platform="tiktok",
        records=records,
    )


@router.post(
    "/collect/actors",
    response_model=CollectResponse,
    summary="Ad-hoc TikTok actor-based collection",
    description=(
        "Collect TikTok video metadata from specific users (by username). "
        "Engagement metrics are subject to a 10-day accuracy lag. "
        "Requires TikTok Research API credentials in the CredentialPool."
    ),
)
async def collect_actors(
    body: CollectActorsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect TikTok videos from the given actors.

    Args:
        body: Request body with actor usernames and optional date bounds.
        current_user: Injected active user.

    Returns:
        Normalized video records and collection metadata.

    Raises:
        HTTPException 429: If the TikTok API is rate-limited.
        HTTPException 401: If credentials are rejected.
        HTTPException 503: If no credential is available.
        HTTPException 502: On other upstream API errors.
    """
    collector = TikTokCollector()

    try:
        records = await collector.collect_by_actors(
            actor_ids=body.actor_ids,
            tier=Tier.FREE,
            date_from=body.date_from,
            date_to=body.date_to,
            max_results=body.max_results,
        )
    except NoCredentialAvailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No TikTok Research API credential available.",
        ) from exc
    except ArenaRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"TikTok API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"TikTok credential error: {exc}",
        ) from exc
    except ArenaCollectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"TikTok actor collection failed: {exc}",
        ) from exc

    logger.info(
        "tiktok router: collected %d videos (actors) for user=%s",
        len(records),
        current_user.id,
    )
    return CollectResponse(
        count=len(records),
        arena="social_media",
        platform="tiktok",
        records=records,
    )


@router.get(
    "/health",
    summary="TikTok arena health check",
    description=(
        "Verify that the TikTok Research API is reachable and credentials are valid. "
        "Sends a minimal test query. Returns ``ok``, ``degraded``, or ``down``."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Run a health check against the TikTok Research API.

    Args:
        current_user: Injected active user.

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = TikTokCollector()
    result = await collector.health_check()
    logger.info(
        "tiktok router: health_check called by user=%s — status=%s",
        current_user.id,
        result.get("status"),
    )
    return result
