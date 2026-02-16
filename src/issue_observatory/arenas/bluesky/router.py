"""Standalone FastAPI router for the Bluesky arena.

This router can be imported and mounted independently of the full application
stack for testing or ad-hoc collection without a collection run.

Mount in the main app::

    from issue_observatory.arenas.bluesky.router import router as bluesky_router
    app.include_router(bluesky_router, prefix="/api/arenas")

Or run standalone (for local testing)::

    import uvicorn
    from fastapi import FastAPI
    from issue_observatory.arenas.bluesky.router import router

    app = FastAPI()
    app.include_router(router)
    uvicorn.run(app, host="0.0.0.0", port=8080)

Endpoints:

- ``POST /bluesky/collect/terms``   — ad-hoc collection by search terms.
- ``POST /bluesky/collect/actors``  — ad-hoc collection by actor DIDs/handles.
- ``GET  /bluesky/health``          — arena health check.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.bluesky.collector import BlueskyCollector
from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
)
from issue_observatory.core.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bluesky", tags=["Bluesky"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectTermsRequest(BaseModel):
    """Request body for ad-hoc Bluesky term-based collection.

    Attributes:
        terms: Search terms (Lucene syntax supported).
        max_results: Maximum post records to return.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
    """

    terms: list[str] = Field(..., min_length=1, description="Search terms.")
    max_results: int = Field(
        default=100,
        ge=1,
        le=10_000,
        description="Maximum post records to return (1–10,000).",
    )
    date_from: str | None = Field(
        default=None,
        description="ISO 8601 lower date bound (e.g. '2026-01-01T00:00:00Z').",
    )
    date_to: str | None = Field(
        default=None,
        description="ISO 8601 upper date bound.",
    )


class CollectActorsRequest(BaseModel):
    """Request body for ad-hoc Bluesky actor-based collection.

    Attributes:
        actor_ids: Bluesky DIDs or handles to collect posts from.
        max_results: Maximum post records to return.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
    """

    actor_ids: list[str] = Field(
        ..., min_length=1, description="Bluesky DIDs or handles."
    )
    max_results: int = Field(
        default=100,
        ge=1,
        le=10_000,
        description="Maximum post records to return (1–10,000).",
    )
    date_from: str | None = Field(default=None, description="ISO 8601 lower date bound.")
    date_to: str | None = Field(default=None, description="ISO 8601 upper date bound.")


class CollectResponse(BaseModel):
    """Response body for ad-hoc collection.

    Attributes:
        count: Number of post records returned.
        arena: Arena name (always ``"bluesky"``).
        records: Normalized content record dicts.
    """

    count: int
    arena: str
    records: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post(
    "/collect/terms",
    response_model=CollectResponse,
    summary="Ad-hoc Bluesky term-based collection",
    description=(
        "Collect Bluesky posts matching the supplied search terms.  "
        "Uses the AT Protocol public API with ``lang=da`` filter applied automatically.  "
        "No credentials required.  Credits are not deducted by this endpoint."
    ),
)
async def collect_terms(
    body: CollectTermsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect Bluesky posts matching the given search terms.

    Args:
        body: Request body containing terms and optional date bounds.
        current_user: Injected active user (from JWT cookie or bearer token).

    Returns:
        Normalized post records and collection metadata.

    Raises:
        HTTPException 429: If the upstream API is rate-limited.
        HTTPException 502: On upstream API errors.
    """
    collector = BlueskyCollector()

    try:
        records = await collector.collect_by_terms(
            terms=body.terms,
            tier=Tier.FREE,
            date_from=body.date_from,
            date_to=body.date_to,
            max_results=body.max_results,
        )
    except ArenaRateLimitError as exc:
        logger.warning(
            "bluesky router: rate limited (retry_after=%.0fs) user=%s",
            exc.retry_after,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Bluesky API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "bluesky router: collection error (terms) for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Bluesky collection failed: {exc}",
        ) from exc

    logger.info(
        "bluesky router: collected %d posts (terms) for user=%s",
        len(records),
        current_user.id,
    )
    return CollectResponse(count=len(records), arena="bluesky", records=records)


@router.post(
    "/collect/actors",
    response_model=CollectResponse,
    summary="Ad-hoc Bluesky actor-based collection",
    description=(
        "Collect Bluesky posts from specific user accounts identified by DID or handle.  "
        "No credentials required.  Credits are not deducted by this endpoint."
    ),
)
async def collect_actors(
    body: CollectActorsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect Bluesky posts from the given actors.

    Args:
        body: Request body containing actor IDs and optional date bounds.
        current_user: Injected active user.

    Returns:
        Normalized post records and collection metadata.

    Raises:
        HTTPException 429: If the upstream API is rate-limited.
        HTTPException 502: On upstream API errors.
    """
    collector = BlueskyCollector()

    try:
        records = await collector.collect_by_actors(
            actor_ids=body.actor_ids,
            tier=Tier.FREE,
            date_from=body.date_from,
            date_to=body.date_to,
            max_results=body.max_results,
        )
    except ArenaRateLimitError as exc:
        logger.warning(
            "bluesky router: rate limited (retry_after=%.0fs) user=%s",
            exc.retry_after,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Bluesky API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "bluesky router: collection error (actors) for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Bluesky actor collection failed: {exc}",
        ) from exc

    logger.info(
        "bluesky router: collected %d posts (actors) for user=%s",
        len(records),
        current_user.id,
    )
    return CollectResponse(count=len(records), arena="bluesky", records=records)


@router.get(
    "/health",
    summary="Bluesky arena health check",
    description=(
        "Verify that the Bluesky AT Protocol public API is reachable.  "
        "Sends a minimal test query and verifies a valid JSON response.  "
        "Returns ``ok``, ``degraded``, or ``down``."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Run a health check against the Bluesky public API.

    Args:
        current_user: Injected active user (authentication required to
            prevent unauthenticated probing).

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = BlueskyCollector()
    result = await collector.health_check()
    logger.info(
        "bluesky router: health_check called by user=%s — status=%s",
        current_user.id,
        result.get("status"),
    )
    return result
