"""Arena metadata API routes.

Exposes a single endpoint that returns the live list of all registered arena
collectors, enriched with credential status from the ``api_credentials`` table
and environment variables.

Routes:
    GET /api/arenas/  — list all registered arenas with credential status
"""

from __future__ import annotations

import os
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.arenas.registry import autodiscover, list_arenas
from issue_observatory.core.database import get_db
from issue_observatory.core.models.credentials import ApiCredential

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/arenas", tags=["arenas"])


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class CustomConfigField(BaseModel):
    """Schema for a single custom configuration field (YF-02).

    Attributes:
        field: Configuration key name (e.g. ``"custom_channels"``).
        label: Human-readable label for the UI.
        type: Input type (``"list"``, ``"boolean"``, ``"text"``).
        placeholder: Placeholder text for the input.
        help: Help text explaining what the field is for.
        example: Example value to show in the UI.
    """

    field: str
    label: str
    type: str
    placeholder: str
    help: str
    example: str


class ArenaInfo(BaseModel):
    """Metadata for a single registered arena collector.

    Attributes:
        arena_name: Logical arena identifier (e.g. ``"bluesky"``).
        platform_name: Underlying platform name written to content records.
        supported_tiers: List of tier strings the arena supports (``"free"``,
            ``"medium"``, ``"premium"``).
        temporal_mode: Temporal capability mode (``"historical"``, ``"recent"``,
            ``"forward_only"``, or ``"mixed"``).
        description: One-line human-readable description of the arena.
        has_credentials: ``True`` when at least one active credential exists
            in the ``api_credentials`` table for this platform.
        custom_config_fields: Optional list of custom configuration fields
            for researcher-curated source lists (YF-02). Present only when
            the arena requires custom configuration.
    """

    arena_name: str
    platform_name: str
    supported_tiers: list[str]
    temporal_mode: str
    description: str
    has_credentials: bool
    custom_config_fields: list[CustomConfigField] | None = None


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[ArenaInfo])
async def list_available_arenas(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ArenaInfo]:
    """Return the live list of all registered arena collectors.

    Calls ``autodiscover()`` to ensure all ``@register`` decorators have
    executed, then ``list_arenas()`` to build the base list.  Enriches each
    entry with ``has_credentials`` by checking the ``api_credentials`` table
    for any active credential whose ``platform`` column matches the arena's
    ``platform_name``.

    This endpoint is unauthenticated by design: the arena list is not
    sensitive and is needed by the query design editor before login state
    is confirmed.  Credential status shows only whether credentials
    *exist*, not their contents.

    Args:
        db: Injected async database session.

    Returns:
        List of :class:`ArenaInfo` objects, one per registered collector,
        ordered alphabetically by ``arena_name``.
    """
    # Ensure all collector modules have been imported so @register decorators
    # have fired.  autodiscover() is idempotent and safe to call every request.
    autodiscover()

    arenas = list_arenas()

    # Collect distinct platform_names we need to check credentials for.
    platform_names = {entry["platform_name"] for entry in arenas}

    # Single query: fetch platform names that have at least one active credential.
    result = await db.execute(
        select(ApiCredential.platform)
        .where(
            ApiCredential.platform.in_(platform_names),
            ApiCredential.is_active.is_(True),
        )
        .distinct()
    )
    platforms_with_credentials: set[str] = {row[0] for row in result.fetchall()}

    # M-1 fix: also check environment variables for credentials.
    # Maps platform_name -> list of env var names that indicate credentials
    # are available.  A platform counts as credentialed if ANY of its env
    # vars are set to a non-empty value.
    _ENV_CREDENTIAL_MAP: dict[str, list[str]] = {
        "google_search": ["SERPER_API_KEY", "SERPAPI_API_KEY"],
        "google_autocomplete": ["SERPER_API_KEY", "SERPAPI_API_KEY"],
        "bluesky": ["BLUESKY_HANDLE"],
        "reddit": ["REDDIT_CLIENT_ID"],
        "youtube": ["YOUTUBE_API_KEY"],
        "tiktok": ["TIKTOK_CLIENT_KEY"],
        "event_registry": ["EVENT_REGISTRY_API_KEY"],
        "x_twitter": ["TWITTERAPIIO_API_KEY", "X_API_KEY"],
        "openrouter": ["OPENROUTER_API_KEY"],
        "majestic": ["MAJESTIC_API_KEY"],
        "telegram": ["TELEGRAM_API_ID"],
        "discord": ["DISCORD_BOT_TOKEN"],
        "twitch": ["TWITCH_CLIENT_ID"],
    }
    for platform, env_keys in _ENV_CREDENTIAL_MAP.items():
        if platform in platforms_with_credentials:
            continue  # already detected via DB
        if any(os.environ.get(key) for key in env_keys):
            platforms_with_credentials.add(platform)

    logger.debug(
        "arenas_list_request",
        arena_count=len(arenas),
        credentialed_platforms=sorted(platforms_with_credentials),
    )

    return [
        ArenaInfo(
            arena_name=entry["arena_name"],
            platform_name=entry["platform_name"],
            supported_tiers=entry["supported_tiers"],
            temporal_mode=entry["temporal_mode"],
            description=entry["description"],
            has_credentials=entry["platform_name"] in platforms_with_credentials,
            custom_config_fields=(
                [CustomConfigField(**field) for field in entry["custom_config_fields"]]
                if entry.get("custom_config_fields")
                else None
            ),
        )
        for entry in arenas
    ]
