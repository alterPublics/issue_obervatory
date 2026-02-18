"""Arena metadata API routes.

Exposes a single endpoint that returns the live list of all registered arena
collectors, enriched with credential status from the ``api_credentials`` table.

Routes:
    GET /api/arenas/  — list all registered arenas with credential status
"""

from __future__ import annotations

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


class ArenaInfo(BaseModel):
    """Metadata for a single registered arena collector.

    Attributes:
        arena_name: Logical arena identifier (e.g. ``"bluesky"``).
        platform_name: Underlying platform name written to content records.
        supported_tiers: List of tier strings the arena supports (``"free"``,
            ``"medium"``, ``"premium"``).
        description: One-line human-readable description of the arena.
        has_credentials: ``True`` when at least one active credential exists
            in the ``api_credentials`` table for this platform.
    """

    arena_name: str
    platform_name: str
    supported_tiers: list[str]
    description: str
    has_credentials: bool


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

    logger.debug(
        "arenas_list_request",
        arena_count=len(arenas),
        credentialed_platforms=list(platforms_with_credentials),
    )

    return [
        ArenaInfo(
            arena_name=entry["arena_name"],
            platform_name=entry["platform_name"],
            supported_tiers=entry["supported_tiers"],
            description=entry["description"],
            has_credentials=entry["platform_name"] in platforms_with_credentials,
        )
        for entry in arenas
    ]
