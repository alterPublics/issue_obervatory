"""Standalone FastAPI router for the Discord arena.

This router can be imported and mounted independently of the full application
stack for testing or ad-hoc Discord message collection.

Mount in the main app::

    from issue_observatory.arenas.discord.router import router as discord_router
    app.include_router(discord_router, prefix="/api/arenas")

Or run standalone::

    import uvicorn
    from fastapi import FastAPI
    from issue_observatory.arenas.discord.router import router

    app = FastAPI()
    app.include_router(router)
    uvicorn.run(app, host="0.0.0.0", port=8082)

Endpoints:

- ``POST /discord/collect/terms``  — collect by search terms (channel-scoped).
- ``POST /discord/collect/actors`` — collect by Discord user IDs.
- ``GET  /discord/health``         — arena health check.

Important: Discord bots cannot search by keyword. The ``channel_ids`` field
in the terms request is required — there is no fallback global search.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.discord.collector import DiscordCollector
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.core.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/discord", tags=["Discord"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class DiscordCollectByTermsRequest(BaseModel):
    """Request body for Discord term-based collection.

    Attributes:
        terms: Search terms matched client-side against message content.
            Discord bots cannot perform server-side keyword search.
        channel_ids: Discord channel snowflake IDs to retrieve messages from.
            Required — Discord has no global search for bot accounts.
        date_from: ISO 8601 earliest message date (inclusive).
        date_to: ISO 8601 latest message date (inclusive).
        max_results: Upper bound on returned records.
    """

    terms: list[str] = Field(..., min_length=1, description="Search terms for client-side matching.")
    channel_ids: list[str] | None = Field(
        default=None,
        description=(
            "Discord channel snowflake IDs to fetch messages from. "
            "Required — Discord bots cannot search across servers without explicit channel IDs."
        ),
    )
    date_from: str | None = Field(default=None, description="ISO 8601 start date (inclusive).")
    date_to: str | None = Field(default=None, description="ISO 8601 end date (inclusive).")
    max_results: int = Field(
        default=1_000,
        ge=1,
        le=10_000,
        description="Maximum records to return.",
    )


class DiscordCollectByActorsRequest(BaseModel):
    """Request body for Discord actor-based collection.

    Attributes:
        actor_ids: Discord user snowflake IDs to filter messages by author.
        channel_ids: Discord channel snowflake IDs to search within.
        date_from: ISO 8601 earliest message date (inclusive).
        date_to: ISO 8601 latest message date (inclusive).
        max_results: Upper bound on returned records.
    """

    actor_ids: list[str] = Field(
        ...,
        min_length=1,
        description="Discord user snowflake IDs to match as message authors.",
    )
    channel_ids: list[str] | None = Field(
        default=None,
        description="Discord channel snowflake IDs to search within.",
    )
    date_from: str | None = Field(default=None, description="ISO 8601 start date (inclusive).")
    date_to: str | None = Field(default=None, description="ISO 8601 end date (inclusive).")
    max_results: int = Field(
        default=1_000,
        ge=1,
        le=10_000,
        description="Maximum records to return.",
    )


class DiscordCollectResponse(BaseModel):
    """Response body for Discord collection endpoints.

    Attributes:
        count: Number of records returned.
        tier: Tier used (always ``"free"``).
        arena: Arena name (always ``"social_media"``).
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
    "/collect/terms",
    response_model=DiscordCollectResponse,
    summary="Collect Discord messages matching search terms (client-side filtering)",
    description=(
        "Fetches messages from the specified Discord channels and returns those "
        "whose content matches any of the supplied terms (case-insensitive). "
        "IMPORTANT: Discord bots cannot search by keyword server-side. "
        "``channel_ids`` is required; all term matching is done client-side "
        "after retrieving messages from each channel."
    ),
)
async def collect_by_terms(
    body: DiscordCollectByTermsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DiscordCollectResponse:
    """Collect Discord messages by term matching.

    Args:
        body: Request body with terms, channel IDs, and optional date range.
        current_user: Injected active user.

    Returns:
        Normalized content records and collection metadata.

    Raises:
        HTTPException 400: If no channel_ids are provided.
        HTTPException 429: On rate limit from the Discord API.
        HTTPException 502: On unrecoverable collection error.
        HTTPException 503: If no bot token credential is available.
    """
    if not body.channel_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "channel_ids is required for Discord collection. "
                "Discord bots cannot search by keyword without explicit channel IDs."
            ),
        )

    collector = DiscordCollector()

    try:
        records = await collector.collect_by_terms(
            terms=body.terms,
            tier=Tier.FREE,
            date_from=body.date_from,
            date_to=body.date_to,
            max_results=body.max_results,
            channel_ids=body.channel_ids,
        )
    except NoCredentialAvailableError as exc:
        logger.error("discord router: no bot token for user=%s", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Discord bot token not configured: {exc}",
        ) from exc
    except ArenaRateLimitError as exc:
        logger.warning("discord router: rate limited for user=%s", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Discord API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        logger.error("discord router: collection error for user=%s: %s", current_user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Discord collection failed: {exc}",
        ) from exc

    logger.info(
        "discord router: collect_by_terms returned %d records for user=%s",
        len(records),
        current_user.id,
    )
    return DiscordCollectResponse(
        count=len(records),
        tier="free",
        arena="social_media",
        records=records,
    )


@router.post(
    "/collect/actors",
    response_model=DiscordCollectResponse,
    summary="Collect Discord messages by specific user IDs",
    description=(
        "Fetches messages from the specified Discord channels and returns those "
        "authored by the provided Discord user snowflake IDs. "
        "``channel_ids`` is required; Discord bots cannot enumerate messages "
        "by user across all servers."
    ),
)
async def collect_by_actors(
    body: DiscordCollectByActorsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DiscordCollectResponse:
    """Collect Discord messages by actor/user ID filtering.

    Args:
        body: Request body with actor IDs, channel IDs, and optional date range.
        current_user: Injected active user.

    Returns:
        Normalized content records and collection metadata.

    Raises:
        HTTPException 400: If no channel_ids are provided.
        HTTPException 429: On rate limit from the Discord API.
        HTTPException 502: On unrecoverable collection error.
        HTTPException 503: If no bot token credential is available.
    """
    if not body.channel_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "channel_ids is required for Discord actor collection. "
                "Discord bots cannot enumerate all messages by user without a channel list."
            ),
        )

    collector = DiscordCollector()

    try:
        records = await collector.collect_by_actors(
            actor_ids=body.actor_ids,
            tier=Tier.FREE,
            date_from=body.date_from,
            date_to=body.date_to,
            max_results=body.max_results,
            channel_ids=body.channel_ids,
        )
    except NoCredentialAvailableError as exc:
        logger.error("discord router: no bot token for user=%s", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Discord bot token not configured: {exc}",
        ) from exc
    except ArenaRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Discord API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        logger.error("discord router: collection error for user=%s: %s", current_user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Discord actor collection failed: {exc}",
        ) from exc

    logger.info(
        "discord router: collect_by_actors returned %d records for user=%s",
        len(records),
        current_user.id,
    )
    return DiscordCollectResponse(
        count=len(records),
        tier="free",
        arena="social_media",
        records=records,
    )


@router.get(
    "/health",
    summary="Discord arena health check",
    description=(
        "Calls ``GET /gateway`` with the configured bot token and verifies "
        "a 200 response. Returns ``ok`` if the API is reachable and the token "
        "is valid, ``down`` otherwise."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Run a health check for the Discord arena.

    Args:
        current_user: Injected active user.

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = DiscordCollector()
    result = await collector.health_check()
    logger.info(
        "discord router: health_check called by user=%s — status=%s",
        current_user.id,
        result.get("status"),
    )
    return result
