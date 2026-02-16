"""Standalone FastAPI router for the Via Ritzau arena.

Provides ad-hoc collection endpoints for the Via Ritzau press release API.
No credentials required — the API is publicly accessible.

Mount in the main app::

    from issue_observatory.arenas.ritzau_via.router import router as ritzau_router
    app.include_router(ritzau_router, prefix="/arenas")

Endpoints:

- ``POST /ritzau-via/collect/terms``  — collect by keyword search (language=da).
- ``POST /ritzau-via/collect/actors`` — collect by publisher ID.
- ``GET  /ritzau-via/health``         — arena health check.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.ritzau_via.collector import RitzauViaCollector
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
)
from issue_observatory.core.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ritzau-via", tags=["Via Ritzau"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectTermsRequest(BaseModel):
    """Request body for ad-hoc Via Ritzau term-based collection.

    Attributes:
        terms: Keywords to search across press release titles and bodies.
        max_results: Maximum press release records to return.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
    """

    terms: list[str] = Field(
        ..., min_length=1, description="Search keywords for press release search."
    )
    max_results: int = Field(
        default=100,
        ge=1,
        le=10_000,
        description="Maximum press release records to return (1–10,000).",
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
    """Request body for ad-hoc Via Ritzau publisher-based collection.

    Attributes:
        actor_ids: Via Ritzau publisher IDs (integer strings).
        max_results: Maximum press release records to return.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
    """

    actor_ids: list[str] = Field(
        ..., min_length=1, description="Via Ritzau publisher IDs."
    )
    max_results: int = Field(
        default=100,
        ge=1,
        le=10_000,
        description="Maximum press release records to return (1–10,000).",
    )
    date_from: str | None = Field(default=None, description="ISO 8601 lower date bound.")
    date_to: str | None = Field(default=None, description="ISO 8601 upper date bound.")


class CollectResponse(BaseModel):
    """Response body for ad-hoc collection endpoints.

    Attributes:
        count: Number of press release records returned.
        arena: Arena name (always ``"news_media"``).
        platform: Platform name (always ``"ritzau_via"``).
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
    summary="Ad-hoc Via Ritzau term-based collection",
    description=(
        "Collect Via Ritzau press releases matching the supplied keywords. "
        "Applies ``language=da`` filter automatically. No credentials required."
    ),
)
async def collect_terms(
    body: CollectTermsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect press releases matching the given search terms.

    Args:
        body: Request body with terms and optional date bounds.
        current_user: Injected active user.

    Returns:
        Normalized press release records and collection metadata.

    Raises:
        HTTPException 429: If the API is rate-limited.
        HTTPException 502: On upstream API errors.
    """
    collector = RitzauViaCollector()

    try:
        records = await collector.collect_by_terms(
            terms=body.terms,
            tier=Tier.FREE,
            date_from=body.date_from,
            date_to=body.date_to,
            max_results=body.max_results,
        )
    except ArenaRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Via Ritzau API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Via Ritzau collection failed: {exc}",
        ) from exc

    logger.info(
        "ritzau_via router: collected %d releases (terms) for user=%s",
        len(records),
        current_user.id,
    )
    return CollectResponse(
        count=len(records),
        arena="news_media",
        platform="ritzau_via",
        records=records,
    )


@router.post(
    "/collect/actors",
    response_model=CollectResponse,
    summary="Ad-hoc Via Ritzau publisher-based collection",
    description=(
        "Collect Via Ritzau press releases from specific publishers by their publisher IDs. "
        "No credentials required."
    ),
)
async def collect_actors(
    body: CollectActorsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect press releases from the given publishers.

    Args:
        body: Request body with publisher IDs and optional date bounds.
        current_user: Injected active user.

    Returns:
        Normalized press release records and collection metadata.

    Raises:
        HTTPException 429: If the API is rate-limited.
        HTTPException 502: On upstream API errors.
    """
    collector = RitzauViaCollector()

    try:
        records = await collector.collect_by_actors(
            actor_ids=body.actor_ids,
            tier=Tier.FREE,
            date_from=body.date_from,
            date_to=body.date_to,
            max_results=body.max_results,
        )
    except ArenaRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Via Ritzau API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Via Ritzau actor collection failed: {exc}",
        ) from exc

    logger.info(
        "ritzau_via router: collected %d releases (actors) for user=%s",
        len(records),
        current_user.id,
    )
    return CollectResponse(
        count=len(records),
        arena="news_media",
        platform="ritzau_via",
        records=records,
    )


@router.get(
    "/health",
    summary="Via Ritzau arena health check",
    description=(
        "Verify that the Via Ritzau REST API is reachable. "
        "Returns ``ok``, ``degraded``, or ``down``."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Run a health check against the Via Ritzau API.

    Args:
        current_user: Injected active user.

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = RitzauViaCollector()
    result = await collector.health_check()
    logger.info(
        "ritzau_via router: health_check called by user=%s — status=%s",
        current_user.id,
        result.get("status"),
    )
    return result
