"""Standalone FastAPI router for the RSS Feeds arena.

This router can be imported and mounted independently of the full application
stack for testing or ad-hoc feed collection.

Mount in the main app::

    from issue_observatory.arenas.rss_feeds.router import router as rss_router
    app.include_router(rss_router, prefix="/api/arenas")

Or run standalone::

    import uvicorn
    from fastapi import FastAPI
    from issue_observatory.arenas.rss_feeds.router import router

    app = FastAPI()
    app.include_router(router)
    uvicorn.run(app, host="0.0.0.0", port=8081)

Endpoints:

- ``POST /rss-feeds/collect/terms``   — collect by search terms (authenticated).
- ``POST /rss-feeds/collect/actors``  — collect by outlet slugs (authenticated).
- ``GET  /rss-feeds/health``          — arena health check (authenticated).
- ``GET  /rss-feeds/feeds``           — list configured feeds (authenticated).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.rss_feeds.collector import RSSFeedsCollector
from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.config.danish_defaults import DANISH_RSS_FEEDS
from issue_observatory.core.exceptions import ArenaCollectionError, ArenaRateLimitError
from issue_observatory.core.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rss-feeds", tags=["RSS Feeds"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectByTermsRequest(BaseModel):
    """Request body for term-based RSS collection.

    Attributes:
        terms: Search terms matched case-insensitively against entry titles
            and summaries.
        date_from: ISO 8601 earliest publication date (inclusive).
        date_to: ISO 8601 latest publication date (inclusive).
        max_results: Upper bound on returned records.
    """

    terms: list[str] = Field(..., min_length=1, description="Search terms to match.")
    date_from: str | None = Field(default=None, description="ISO 8601 start date (inclusive).")
    date_to: str | None = Field(default=None, description="ISO 8601 end date (inclusive).")
    max_results: int = Field(
        default=500,
        ge=1,
        le=10_000,
        description="Maximum records to return.",
    )


class CollectByActorsRequest(BaseModel):
    """Request body for actor-based RSS collection.

    Attributes:
        actor_ids: Outlet keys or slug prefixes from ``DANISH_RSS_FEEDS``
            (e.g. ``["dr", "tv2_nyheder"]``).
        date_from: ISO 8601 earliest publication date.
        date_to: ISO 8601 latest publication date.
        max_results: Upper bound on returned records.
    """

    actor_ids: list[str] = Field(..., min_length=1, description="Outlet keys or slug prefixes.")
    date_from: str | None = Field(default=None, description="ISO 8601 start date (inclusive).")
    date_to: str | None = Field(default=None, description="ISO 8601 end date (inclusive).")
    max_results: int = Field(
        default=500,
        ge=1,
        le=10_000,
        description="Maximum records to return.",
    )


class CollectResponse(BaseModel):
    """Response body for RSS collection endpoints.

    Attributes:
        count: Number of records returned.
        tier: Tier used (always ``"free"`` for RSS Feeds).
        arena: Arena name (always ``"news_media"``).
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
    response_model=CollectResponse,
    summary="Collect Danish RSS entries matching search terms",
    description=(
        "Fetches all configured Danish RSS feeds and returns entries whose "
        "title or summary match any of the supplied terms (case-insensitive). "
        "Optional date range filtering is supported."
    ),
)
async def collect_by_terms(
    body: CollectByTermsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect RSS entries by term matching.

    Args:
        body: Request body with terms and optional date range.
        current_user: Injected active user.

    Returns:
        Normalized content records and collection metadata.

    Raises:
        HTTPException 429: On rate limit from outlet servers.
        HTTPException 502: On unrecoverable collection error.
    """
    collector = RSSFeedsCollector()

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
            "rss_feeds router: rate limited for user=%s", current_user.id
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"RSS feed collection rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "rss_feeds router: collection error for user=%s: %s", current_user.id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"RSS feed collection failed: {exc}",
        ) from exc

    logger.info(
        "rss_feeds router: collect_by_terms returned %d records for user=%s",
        len(records),
        current_user.id,
    )
    return CollectResponse(
        count=len(records),
        tier="free",
        arena="news_media",
        records=records,
    )


@router.post(
    "/collect/actors",
    response_model=CollectResponse,
    summary="Collect all RSS entries from specific outlets",
    description=(
        "Fetches all entries from feeds associated with the supplied outlet "
        "slugs or feed keys (e.g. ``'dr'``, ``'tv2_nyheder'``).  No term "
        "filtering is applied — all entries from the matched feeds are returned."
    ),
)
async def collect_by_actors(
    body: CollectByActorsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect RSS entries from specific outlets.

    Args:
        body: Request body with outlet slugs and optional date range.
        current_user: Injected active user.

    Returns:
        Normalized content records and collection metadata.

    Raises:
        HTTPException 429: On rate limit from outlet servers.
        HTTPException 502: On unrecoverable collection error.
    """
    collector = RSSFeedsCollector()

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
            detail=f"RSS feed rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "rss_feeds router: collection error for user=%s: %s", current_user.id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"RSS feed collection failed: {exc}",
        ) from exc

    logger.info(
        "rss_feeds router: collect_by_actors returned %d records for user=%s",
        len(records),
        current_user.id,
    )
    return CollectResponse(
        count=len(records),
        tier="free",
        arena="news_media",
        records=records,
    )


@router.get(
    "/health",
    summary="RSS Feeds arena health check",
    description=(
        "Fetches the DR all-news feed and verifies it parses correctly. "
        "Returns ``ok``, ``degraded``, or ``down``."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Run a health check for the RSS Feeds arena.

    Args:
        current_user: Injected active user.

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = RSSFeedsCollector()
    result = await collector.health_check()
    logger.info(
        "rss_feeds router: health_check called by user=%s — status=%s",
        current_user.id,
        result.get("status"),
    )
    return result


@router.get(
    "/feeds",
    summary="List all configured Danish RSS feeds",
    description=(
        "Returns the full list of curated Danish RSS feeds with their keys "
        "and URLs.  Use feed keys as ``actor_ids`` in the collect/actors endpoint."
    ),
)
async def list_feeds(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Return the configured Danish RSS feed registry.

    Args:
        current_user: Injected active user.

    Returns:
        Dict with ``count`` and ``feeds`` (dict of key -> url).
    """
    return {
        "count": len(DANISH_RSS_FEEDS),
        "feeds": DANISH_RSS_FEEDS,
    }
