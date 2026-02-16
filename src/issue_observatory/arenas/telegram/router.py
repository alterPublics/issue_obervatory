"""Standalone FastAPI router for the Telegram arena.

This router can be imported and mounted independently of the full application
stack for testing or ad-hoc collection without a collection run.

Mount in the main app::

    from issue_observatory.arenas.telegram.router import router as telegram_router
    app.include_router(telegram_router, prefix="/api/arenas")

Or run standalone (for local testing)::

    import uvicorn
    from fastapi import FastAPI
    from issue_observatory.arenas.telegram.router import router

    app = FastAPI()
    app.include_router(router)
    uvicorn.run(app, host="0.0.0.0", port=8080)

Endpoints:

- ``POST /telegram/collect/terms``  — ad-hoc collection by search terms.
- ``POST /telegram/collect/actors`` — ad-hoc collection by channel usernames/IDs.
- ``GET  /telegram/health``         — arena health check.

**Credentials required**: All collection endpoints require a Telegram credential
to be present in the CredentialPool.  Missing credentials return HTTP 503.

**Authentication required**: All endpoints require a logged-in user
(``get_current_active_user`` dependency) to prevent unauthenticated scraping
via this API surface.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.telegram.collector import TelegramCollector
from issue_observatory.core.credential_pool import get_credential_pool
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.core.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["Telegram"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectTermsRequest(BaseModel):
    """Request body for ad-hoc Telegram term-based collection.

    Attributes:
        terms: Search terms.  Each term is searched within each monitored
            channel using Telegram's built-in message search.
        channel_ids: Optional additional channel usernames or numeric IDs
            to include beyond the default Danish channel list.
        max_results: Maximum message records to return.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
    """

    terms: list[str] = Field(..., min_length=1, description="Search terms.")
    channel_ids: list[str] | None = Field(
        default=None,
        description=(
            "Optional additional Telegram channel usernames (e.g. 'dr_nyheder') "
            "or numeric channel IDs (e.g. '-1001234567890') to search."
        ),
    )
    max_results: int = Field(
        default=100,
        ge=1,
        le=10_000,
        description="Maximum message records to return (1–10,000).",
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
    """Request body for ad-hoc Telegram actor-based collection.

    Attributes:
        actor_ids: Telegram channel usernames or numeric channel IDs.
        max_results: Maximum message records to return.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
    """

    actor_ids: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Telegram channel usernames (e.g. 'dr_nyheder') or numeric IDs "
            "(e.g. '-1001234567890')."
        ),
    )
    max_results: int = Field(
        default=100,
        ge=1,
        le=10_000,
        description="Maximum message records to return (1–10,000).",
    )
    date_from: str | None = Field(default=None, description="ISO 8601 lower date bound.")
    date_to: str | None = Field(default=None, description="ISO 8601 upper date bound.")


class CollectResponse(BaseModel):
    """Response body for ad-hoc collection.

    Attributes:
        count: Number of message records returned.
        arena: Arena name (``"social_media"``).
        platform: Platform name (``"telegram"``).
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
    summary="Ad-hoc Telegram term-based collection",
    description=(
        "Search monitored Danish Telegram channels for messages matching the "
        "supplied search terms.  Each term is searched independently within "
        "each channel using the Telegram MTProto API.  Credentials are required.  "
        "Credits are not deducted by this endpoint."
    ),
)
async def collect_terms(
    body: CollectTermsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect Telegram messages matching the given search terms.

    Args:
        body: Request body containing terms, optional channel list, and date bounds.
        current_user: Injected active user (from JWT cookie or bearer token).

    Returns:
        Normalized message records and collection metadata.

    Raises:
        HTTPException 429: If the Telegram API issues a FloodWaitError.
        HTTPException 503: If no Telegram credential is available.
        HTTPException 502: On other upstream MTProto errors.
    """
    credential_pool = get_credential_pool()
    collector = TelegramCollector(credential_pool=credential_pool)

    try:
        records = await collector.collect_by_terms(
            terms=body.terms,
            tier=Tier.FREE,
            date_from=body.date_from,
            date_to=body.date_to,
            max_results=body.max_results,
            actor_ids=body.channel_ids,
        )
    except NoCredentialAvailableError as exc:
        logger.warning(
            "telegram router: no credential available for user=%s", current_user.id
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No Telegram credential is available. "
                "Provision at least one account via the CredentialPool "
                "(platform='telegram', tier='free')."
            ),
        ) from exc
    except ArenaRateLimitError as exc:
        logger.warning(
            "telegram router: FloodWaitError (retry_after=%.0fs) user=%s",
            exc.retry_after,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Telegram API rate limited (FloodWaitError). "
                f"Retry after {exc.retry_after:.0f} seconds."
            ),
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "telegram router: collection error (terms) for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Telegram collection failed: {exc}",
        ) from exc

    logger.info(
        "telegram router: collected %d messages (terms) for user=%s",
        len(records),
        current_user.id,
    )
    return CollectResponse(
        count=len(records),
        arena="social_media",
        platform="telegram",
        records=records,
    )


@router.post(
    "/collect/actors",
    response_model=CollectResponse,
    summary="Ad-hoc Telegram actor-based collection",
    description=(
        "Collect messages from specific Telegram channels by username or numeric ID.  "
        "Messages are fetched in reverse-chronological order with optional date filtering.  "
        "Credentials are required.  Credits are not deducted by this endpoint."
    ),
)
async def collect_actors(
    body: CollectActorsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect Telegram messages from the given channels.

    Args:
        body: Request body containing channel IDs and optional date bounds.
        current_user: Injected active user.

    Returns:
        Normalized message records and collection metadata.

    Raises:
        HTTPException 429: If the Telegram API issues a FloodWaitError.
        HTTPException 503: If no Telegram credential is available.
        HTTPException 502: On other upstream MTProto errors.
    """
    credential_pool = get_credential_pool()
    collector = TelegramCollector(credential_pool=credential_pool)

    try:
        records = await collector.collect_by_actors(
            actor_ids=body.actor_ids,
            tier=Tier.FREE,
            date_from=body.date_from,
            date_to=body.date_to,
            max_results=body.max_results,
        )
    except NoCredentialAvailableError as exc:
        logger.warning(
            "telegram router: no credential available for user=%s", current_user.id
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No Telegram credential is available. "
                "Provision at least one account via the CredentialPool "
                "(platform='telegram', tier='free')."
            ),
        ) from exc
    except ArenaRateLimitError as exc:
        logger.warning(
            "telegram router: FloodWaitError (retry_after=%.0fs) user=%s",
            exc.retry_after,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Telegram API rate limited (FloodWaitError). "
                f"Retry after {exc.retry_after:.0f} seconds."
            ),
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "telegram router: collection error (actors) for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Telegram actor collection failed: {exc}",
        ) from exc

    logger.info(
        "telegram router: collected %d messages (actors) for user=%s",
        len(records),
        current_user.id,
    )
    return CollectResponse(
        count=len(records),
        arena="social_media",
        platform="telegram",
        records=records,
    )


@router.get(
    "/health",
    summary="Telegram arena health check",
    description=(
        "Verify that the Telegram MTProto API is reachable using the first "
        "available credential.  Calls ``client.get_me()`` to confirm the session "
        "is valid.  Returns ``ok``, ``degraded``, or ``down``."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Run a health check against the Telegram MTProto API.

    Args:
        current_user: Injected active user (authentication required to prevent
            unauthenticated probing of credential status).

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    credential_pool = get_credential_pool()
    collector = TelegramCollector(credential_pool=credential_pool)
    result = await collector.health_check()
    logger.info(
        "telegram router: health_check called by user=%s — status=%s",
        current_user.id,
        result.get("status"),
    )
    return result
