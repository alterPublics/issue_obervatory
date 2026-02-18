"""Standalone FastAPI router for the Twitch arena — DEFERRED stub.

This router can be imported and mounted independently of the full application
stack for testing or ad-hoc Twitch channel discovery.

Mount in the main app::

    from issue_observatory.arenas.twitch.router import router as twitch_router
    app.include_router(twitch_router, prefix="/api/arenas")

Or run standalone::

    import uvicorn
    from fastapi import FastAPI
    from issue_observatory.arenas.twitch.router import router

    app = FastAPI()
    app.include_router(router)
    uvicorn.run(app, host="0.0.0.0", port=8083)

Endpoints:

- ``POST /twitch/collect/terms``  — channel discovery by search terms.
- ``POST /twitch/collect/actors`` — channel metadata for known broadcasters.
- ``GET  /twitch/health``         — Helix API health check.

IMPORTANT: These endpoints return channel metadata, NOT chat messages.
Real-time chat collection via EventSub WebSocket is the primary collection
mode for Twitch chat and is not yet implemented. The streaming worker
(``"streaming"`` Celery queue) must be used once TwitchStreamer is built.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.twitch.collector import TwitchCollector
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.core.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/twitch", tags=["Twitch"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class TwitchCollectByTermsRequest(BaseModel):
    """Request body for Twitch channel discovery by search terms.

    NOTE: This returns channel metadata, NOT chat messages. Twitch does not
    provide historical chat data. Real-time chat requires the streaming worker.

    Attributes:
        terms: Channel name queries sent to ``GET /search/channels``.
        language_filter: ISO 639-1 language codes to filter by broadcaster language.
        max_results: Upper bound on returned channel metadata records.
    """

    terms: list[str] = Field(..., min_length=1, description="Channel name search queries.")
    language_filter: list[str] | None = Field(
        default=None,
        description=(
            "ISO 639-1 language codes to filter by broadcaster_language "
            "(e.g. ['da', 'en'])."
        ),
    )
    max_results: int = Field(
        default=500,
        ge=1,
        le=10_000,
        description="Maximum channel metadata records to return.",
    )


class TwitchCollectByActorsRequest(BaseModel):
    """Request body for Twitch channel metadata by broadcaster login names.

    NOTE: This returns channel metadata, NOT chat messages. Real-time chat
    collection requires the streaming worker (not yet implemented).

    Attributes:
        actor_ids: Twitch broadcaster login names (e.g. ``["shroud", "pokimane"]``).
        max_results: Upper bound on returned records.
    """

    actor_ids: list[str] = Field(
        ...,
        min_length=1,
        description="Twitch broadcaster login names.",
    )
    max_results: int = Field(
        default=500,
        ge=1,
        le=10_000,
        description="Maximum channel metadata records to return.",
    )


class TwitchCollectResponse(BaseModel):
    """Response body for Twitch collection endpoints.

    Attributes:
        count: Number of records returned.
        tier: Tier used (always ``"free"``).
        arena: Arena name (always ``"social_media"``).
        records: Normalized channel metadata record dicts.
        note: Reminder that this is channel metadata, not chat messages.
    """

    count: int
    tier: str
    arena: str
    records: list[dict[str, Any]]
    note: str


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post(
    "/collect/terms",
    response_model=TwitchCollectResponse,
    summary="Discover Twitch channels matching search terms (channel metadata only)",
    description=(
        "Searches for Twitch channels using ``GET /search/channels`` and returns "
        "channel metadata records. NOTE: This does NOT collect chat messages. "
        "Twitch chat is streaming-only — historical chat is not available via any "
        "Twitch API. Real-time chat collection requires the EventSub streaming worker "
        "(not yet implemented)."
    ),
)
async def collect_by_terms(
    body: TwitchCollectByTermsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> TwitchCollectResponse:
    """Discover Twitch channels by search term.

    Args:
        body: Request body with search terms and optional language filter.
        current_user: Injected active user.

    Returns:
        Normalized channel metadata records and collection metadata.

    Raises:
        HTTPException 429: On rate limit from the Twitch Helix API.
        HTTPException 502: On unrecoverable collection error.
        HTTPException 503: If no Twitch credentials are available.
    """
    collector = TwitchCollector()

    try:
        records = await collector.collect_by_terms(
            terms=body.terms,
            tier=Tier.FREE,
            max_results=body.max_results,
            language_filter=body.language_filter,
        )
    except NoCredentialAvailableError as exc:
        logger.error("twitch router: no credentials for user=%s", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Twitch credentials not configured: {exc}",
        ) from exc
    except ArenaRateLimitError as exc:
        logger.warning("twitch router: rate limited for user=%s", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Twitch API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        logger.error("twitch router: collection error for user=%s: %s", current_user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Twitch channel discovery failed: {exc}",
        ) from exc

    logger.info(
        "twitch router: collect_by_terms returned %d channel records for user=%s",
        len(records),
        current_user.id,
    )
    return TwitchCollectResponse(
        count=len(records),
        tier="free",
        arena="social_media",
        records=records,
        note=(
            "Channel metadata only. Real-time chat requires EventSub streaming worker "
            "(not yet implemented). Twitch has no historical chat API."
        ),
    )


@router.post(
    "/collect/actors",
    response_model=TwitchCollectResponse,
    summary="Retrieve Twitch channel metadata for known broadcasters (channel metadata only)",
    description=(
        "Searches for Twitch channels by broadcaster login name and returns "
        "channel metadata records. NOTE: This does NOT collect chat messages. "
        "Real-time chat collection requires the EventSub streaming worker "
        "(not yet implemented)."
    ),
)
async def collect_by_actors(
    body: TwitchCollectByActorsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> TwitchCollectResponse:
    """Retrieve Twitch channel metadata for known broadcaster accounts.

    Args:
        body: Request body with broadcaster login names.
        current_user: Injected active user.

    Returns:
        Normalized channel metadata records and collection metadata.

    Raises:
        HTTPException 429: On rate limit from the Twitch Helix API.
        HTTPException 502: On unrecoverable collection error.
        HTTPException 503: If no Twitch credentials are available.
    """
    collector = TwitchCollector()

    try:
        records = await collector.collect_by_actors(
            actor_ids=body.actor_ids,
            tier=Tier.FREE,
            max_results=body.max_results,
        )
    except NoCredentialAvailableError as exc:
        logger.error("twitch router: no credentials for user=%s", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Twitch credentials not configured: {exc}",
        ) from exc
    except ArenaRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Twitch API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        logger.error("twitch router: collection error for user=%s: %s", current_user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Twitch actor collection failed: {exc}",
        ) from exc

    logger.info(
        "twitch router: collect_by_actors returned %d channel records for user=%s",
        len(records),
        current_user.id,
    )
    return TwitchCollectResponse(
        count=len(records),
        tier="free",
        arena="social_media",
        records=records,
        note=(
            "Channel metadata only. Real-time chat requires EventSub streaming worker "
            "(not yet implemented). Twitch has no historical chat API."
        ),
    )


@router.get(
    "/health",
    summary="Twitch arena health check",
    description=(
        "Calls ``GET /streams?first=1`` on the Twitch Helix API with an app access "
        "token. Returns ``ok`` if the API is reachable and credentials are valid. "
        "NOTE: This only checks the Helix REST API, not the EventSub WebSocket used "
        "for real-time chat collection."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Run a health check for the Twitch arena (Helix API only).

    Args:
        current_user: Injected active user.

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = TwitchCollector()
    result = await collector.health_check()
    logger.info(
        "twitch router: health_check called by user=%s — status=%s",
        current_user.id,
        result.get("status"),
    )
    return result
