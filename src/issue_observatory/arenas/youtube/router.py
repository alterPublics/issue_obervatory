"""Standalone FastAPI router for the YouTube arena.

Provides independent HTTP endpoints for testing and direct invocation of the
YouTube collector without going through the full Celery task pipeline.

Mount this router in the main FastAPI application::

    from issue_observatory.arenas.youtube.router import router as youtube_router
    app.include_router(youtube_router, prefix="/arenas")

All endpoints construct a :class:`YouTubeCollector` with the application-scoped
:class:`CredentialPool` and execute the collection synchronously (inside
``asyncio`` via the endpoint's own async context).

Credential pool is injected via the ``get_credential_pool`` FastAPI dependency.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.youtube.collector import YouTubeCollector
from issue_observatory.core.credential_pool import CredentialPool, get_credential_pool
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/youtube", tags=["youtube"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CollectByTermsRequest(BaseModel):
    """Request body for ``POST /youtube/collect/terms``.

    Attributes:
        terms: Search terms to query.
        tier: Operational tier.  Only ``"free"`` is valid for YouTube.
        date_from: Optional ISO 8601 lower bound for ``publishedAfter``.
        date_to: Optional ISO 8601 upper bound for ``publishedBefore``.
        max_results: Upper bound on total records returned.
    """

    terms: list[str]
    tier: str = "free"
    date_from: str | None = None
    date_to: str | None = None
    max_results: int = 100


class CollectByActorsRequest(BaseModel):
    """Request body for ``POST /youtube/collect/actors``.

    Attributes:
        actor_ids: YouTube channel IDs (format: ``UC...``).
        tier: Operational tier.  Only ``"free"`` is valid for YouTube.
        date_from: Optional ISO 8601 lower bound for publication date.
        date_to: Optional ISO 8601 upper bound for publication date.
        max_results: Upper bound on total records returned.
    """

    actor_ids: list[str]
    tier: str = "free"
    date_from: str | None = None
    date_to: str | None = None
    max_results: int = 100


class CollectionResponse(BaseModel):
    """Response body for collection endpoints.

    Attributes:
        count: Number of records returned.
        records: List of normalized content record dicts.
        arena: Arena name (``"social_media"``).
        platform: Platform name (``"youtube"``).
        tier: Tier used for the collection.
    """

    count: int
    records: list[dict[str, Any]]
    arena: str
    platform: str
    tier: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/collect/terms",
    response_model=CollectionResponse,
    summary="Collect YouTube videos by search terms",
    description=(
        "Search YouTube for videos matching the provided terms using "
        "``search.list`` (100 units/call) with Danish locale defaults "
        "(``relevanceLanguage=da``, ``regionCode=DK``).  Enriches results "
        "via ``videos.list`` batch calls (1 unit per 50 videos)."
    ),
)
async def collect_by_terms(
    request: CollectByTermsRequest,
    credential_pool: CredentialPool = Depends(get_credential_pool),
) -> CollectionResponse:
    """Collect YouTube videos for a list of search terms.

    Args:
        request: Collection parameters including terms and optional date range.
        credential_pool: Application-scoped credential pool (injected).

    Returns:
        :class:`CollectionResponse` with normalized records and metadata.

    Raises:
        HTTPException 400: Invalid tier value.
        HTTPException 503: Quota exhausted or all credentials unavailable.
        HTTPException 500: Unrecoverable collection error.
    """
    try:
        tier_enum = Tier(request.tier)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier '{request.tier}'. Valid values: free, medium, premium.",
        )

    collector = YouTubeCollector(credential_pool=credential_pool)

    try:
        records = await collector.collect_by_terms(
            terms=request.terms,
            tier=tier_enum,
            date_from=request.date_from,
            date_to=request.date_to,
            max_results=request.max_results,
        )
    except NoCredentialAvailableError as exc:
        logger.error("youtube router: no credential available: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="No YouTube API key available. Configure YOUTUBE_FREE_API_KEY.",
        )
    except ArenaRateLimitError as exc:
        logger.warning("youtube router: quota exhausted: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"YouTube API quota exhausted. Retry after {exc.retry_after:.0f}s.",
        )
    except ArenaCollectionError as exc:
        logger.error("youtube router: collection error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return CollectionResponse(
        count=len(records),
        records=records,
        arena="social_media",
        platform="youtube",
        tier=request.tier,
    )


@router.post(
    "/collect/actors",
    response_model=CollectionResponse,
    summary="Collect YouTube videos from specific channels",
    description=(
        "Poll RSS feeds for the specified YouTube channel IDs (``UC...`` format) "
        "at zero quota cost, then enrich via ``videos.list`` batch calls "
        "(1 unit per 50 videos).  Actor IDs must be YouTube channel IDs."
    ),
)
async def collect_by_actors(
    request: CollectByActorsRequest,
    credential_pool: CredentialPool = Depends(get_credential_pool),
) -> CollectionResponse:
    """Collect YouTube videos from specific channel IDs via RSS feeds.

    Args:
        request: Collection parameters including channel IDs and optional date range.
        credential_pool: Application-scoped credential pool (injected).

    Returns:
        :class:`CollectionResponse` with normalized records and metadata.

    Raises:
        HTTPException 400: Invalid tier value.
        HTTPException 503: Quota exhausted or all credentials unavailable.
        HTTPException 500: Unrecoverable collection error.
    """
    try:
        tier_enum = Tier(request.tier)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier '{request.tier}'. Valid values: free, medium, premium.",
        )

    collector = YouTubeCollector(credential_pool=credential_pool)

    try:
        records = await collector.collect_by_actors(
            actor_ids=request.actor_ids,
            tier=tier_enum,
            date_from=request.date_from,
            date_to=request.date_to,
            max_results=request.max_results,
        )
    except NoCredentialAvailableError as exc:
        logger.error("youtube router: no credential available: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="No YouTube API key available. Configure YOUTUBE_FREE_API_KEY.",
        )
    except ArenaRateLimitError as exc:
        logger.warning("youtube router: quota exhausted: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"YouTube API quota exhausted. Retry after {exc.retry_after:.0f}s.",
        )
    except ArenaCollectionError as exc:
        logger.error("youtube router: collection error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return CollectionResponse(
        count=len(records),
        records=records,
        arena="social_media",
        platform="youtube",
        tier=request.tier,
    )


@router.get(
    "/health",
    summary="YouTube arena health check",
    description=(
        "Calls ``videos.list`` with a known video ID (1 quota unit) to verify "
        "that the API key is valid and the YouTube Data API v3 is reachable."
    ),
)
async def health(
    credential_pool: CredentialPool = Depends(get_credential_pool),
) -> dict[str, Any]:
    """Run a connectivity health check for the YouTube arena.

    Args:
        credential_pool: Application-scoped credential pool (injected).

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = YouTubeCollector(credential_pool=credential_pool)
    return await collector.health_check()


@router.get(
    "/estimate",
    summary="Estimate YouTube API quota units for a collection run",
    description=(
        "Returns an estimated quota unit cost for collecting the given terms or "
        "actor channel IDs.  One search call = 100 units; one videos.list batch = "
        "1 unit (up to 50 videos).  RSS polling is free."
    ),
)
async def estimate_credits(
    terms: list[str] = Query(default=[], description="Search terms to estimate"),
    actor_ids: list[str] = Query(default=[], description="Channel IDs to estimate"),
    max_results: int = Query(default=100, ge=1, description="Expected result count"),
    tier: str = Query(default="free", description="Operational tier"),
) -> dict[str, Any]:
    """Estimate quota units for a YouTube collection run.

    Args:
        terms: Search terms to estimate cost for.
        actor_ids: Channel IDs (RSS-only, zero search quota).
        max_results: Expected upper bound on results.
        tier: Operational tier (only ``"free"`` is valid).

    Returns:
        Dict with ``estimated_units``, ``daily_quota_per_key``,
        ``keys_required``, and ``tier``.

    Raises:
        HTTPException 400: Invalid tier value.
    """
    try:
        tier_enum = Tier(tier)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier '{tier}'. Valid values: free, medium, premium.",
        )

    collector = YouTubeCollector()
    estimated_units = await collector.estimate_credits(
        terms=terms or None,
        actor_ids=actor_ids or None,
        tier=tier_enum,
        max_results=max_results,
    )

    from issue_observatory.arenas.youtube.config import DAILY_QUOTA_PER_KEY  # noqa: PLC0415
    import math  # noqa: PLC0415

    keys_required = math.ceil(estimated_units / DAILY_QUOTA_PER_KEY) if estimated_units > 0 else 1

    return {
        "estimated_units": estimated_units,
        "daily_quota_per_key": DAILY_QUOTA_PER_KEY,
        "keys_required": keys_required,
        "tier": tier,
    }
