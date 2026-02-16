"""Standalone FastAPI router for the Gab arena.

Provides ad-hoc collection endpoints for the Gab Mastodon-compatible API.
All endpoints require authentication and OAuth credentials in the CredentialPool.

Mount in the main app::

    from issue_observatory.arenas.gab.router import router as gab_router
    app.include_router(gab_router, prefix="/arenas")

Endpoints:

- ``POST /gab/collect/terms``  — collect by keyword or hashtag.
- ``POST /gab/collect/actors`` — collect by Gab account ID or username.
- ``GET  /gab/health``         — arena health check.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.gab.collector import GabCollector
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.core.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gab", tags=["Gab"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectTermsRequest(BaseModel):
    """Request body for ad-hoc Gab term-based collection.

    Attributes:
        terms: Keywords or hashtags (``#tag``) to search for.
        max_results: Maximum post records to return.
        date_from: ISO 8601 lower date bound (optional, client-side filter).
        date_to: ISO 8601 upper date bound (optional, client-side filter).
    """

    terms: list[str] = Field(
        ..., min_length=1, description="Keywords or hashtags (#tag) to search for."
    )
    max_results: int = Field(
        default=100,
        ge=1,
        le=10_000,
        description="Maximum post records to return (1–10,000).",
    )
    date_from: str | None = Field(
        default=None,
        description="ISO 8601 lower date bound (client-side filter).",
    )
    date_to: str | None = Field(
        default=None,
        description="ISO 8601 upper date bound (client-side filter).",
    )


class CollectActorsRequest(BaseModel):
    """Request body for ad-hoc Gab actor-based collection.

    Attributes:
        actor_ids: Gab account IDs (numeric) or usernames.
        max_results: Maximum post records to return.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
    """

    actor_ids: list[str] = Field(
        ..., min_length=1, description="Gab account IDs or usernames."
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
    """Response body for ad-hoc collection endpoints.

    Attributes:
        count: Number of post records returned.
        arena: Arena name (always ``"social_media"``).
        platform: Platform name (always ``"gab"``).
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
    summary="Ad-hoc Gab term-based collection",
    description=(
        "Collect Gab posts matching the supplied keywords or hashtags. "
        "For hashtag terms (starting with #), falls back to the hashtag timeline "
        "if the search endpoint is restricted. "
        "Requires Gab OAuth credentials in the CredentialPool."
    ),
)
async def collect_terms(
    body: CollectTermsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect Gab posts matching the given search terms.

    Args:
        body: Request body with terms and optional date bounds.
        current_user: Injected active user.

    Returns:
        Normalized post records and collection metadata.

    Raises:
        HTTPException 429: If the Gab API is rate-limited.
        HTTPException 401: If credentials are rejected.
        HTTPException 503: If no credential is available.
        HTTPException 502: On other upstream API errors.
    """
    collector = GabCollector()

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
            detail="No Gab OAuth credential available. Configure credentials first.",
        ) from exc
    except ArenaRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Gab API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Gab credential error: {exc}",
        ) from exc
    except ArenaCollectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gab collection failed: {exc}",
        ) from exc

    logger.info(
        "gab router: collected %d posts (terms) for user=%s",
        len(records),
        current_user.id,
    )
    return CollectResponse(
        count=len(records),
        arena="social_media",
        platform="gab",
        records=records,
    )


@router.post(
    "/collect/actors",
    response_model=CollectResponse,
    summary="Ad-hoc Gab actor-based collection",
    description=(
        "Collect Gab posts from specific accounts by account ID or username. "
        "Usernames are resolved to account IDs automatically. "
        "Requires Gab OAuth credentials in the CredentialPool."
    ),
)
async def collect_actors(
    body: CollectActorsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect Gab posts from the given actors.

    Args:
        body: Request body with actor IDs/usernames and optional date bounds.
        current_user: Injected active user.

    Returns:
        Normalized post records and collection metadata.

    Raises:
        HTTPException 429: If the Gab API is rate-limited.
        HTTPException 401: If credentials are rejected.
        HTTPException 503: If no credential is available.
        HTTPException 502: On other upstream API errors.
    """
    collector = GabCollector()

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
            detail="No Gab OAuth credential available.",
        ) from exc
    except ArenaRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Gab API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Gab credential error: {exc}",
        ) from exc
    except ArenaCollectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gab actor collection failed: {exc}",
        ) from exc

    logger.info(
        "gab router: collected %d posts (actors) for user=%s",
        len(records),
        current_user.id,
    )
    return CollectResponse(
        count=len(records),
        arena="social_media",
        platform="gab",
        records=records,
    )


@router.get(
    "/health",
    summary="Gab arena health check",
    description=(
        "Verify that the Gab Mastodon-compatible API is reachable and credentials are valid. "
        "Returns ``ok``, ``degraded``, or ``down``."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Run a health check against the Gab API.

    Args:
        current_user: Injected active user.

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = GabCollector()
    result = await collector.health_check()
    logger.info(
        "gab router: health_check called by user=%s — status=%s",
        current_user.id,
        result.get("status"),
    )
    return result
