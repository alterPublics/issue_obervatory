"""Standalone FastAPI router for the URL Scraper arena.

This router can be imported and mounted independently of the full application
stack for testing or ad-hoc URL scraping.

Mount in the main app::

    from issue_observatory.arenas.web.url_scraper.router import router as url_scraper_router
    app.include_router(url_scraper_router, prefix="/arenas")

Endpoints:

- ``POST /url-scraper/collect/terms`` — fetch URLs and filter by search terms.
- ``POST /url-scraper/collect/actors`` — fetch actor website URLs.
- ``GET  /url-scraper/health`` — arena health check.

Notes:
    - The URL list is provided in the request body (``custom_urls``).
    - Content extraction is performed synchronously within the request.
    - For large URL lists (>10 URLs), prefer Celery task dispatch via the
      collection orchestration API rather than calling this router directly.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl

from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.web.url_scraper.collector import UrlScraperCollector
from issue_observatory.core.exceptions import ArenaCollectionError
from issue_observatory.core.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/url-scraper", tags=["URL Scraper"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectByTermsRequest(BaseModel):
    """Request body for URL Scraper term-based collection.

    Attributes:
        custom_urls: List of URLs to fetch and filter.
        terms: Search terms for case-insensitive substring matching.
        term_groups: Optional boolean AND/OR groups (each inner list is ANDed;
            groups are ORed).  When provided, overrides ``terms`` for matching.
        tier: Operational tier (``"free"`` or ``"medium"``).
        max_results: Maximum records to return.
    """

    custom_urls: list[str] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="URLs to fetch.  Each must be a valid absolute HTTP(S) URL.",
    )
    terms: list[str] = Field(
        default_factory=list,
        description="Search terms for case-insensitive substring matching.",
    )
    term_groups: list[list[str]] | None = Field(
        default=None,
        description=(
            "Boolean AND/OR groups.  Each inner list is an AND-group; "
            "groups are ORed.  When provided, ``terms`` is ignored."
        ),
    )
    tier: str = Field(
        default="free",
        description="Operational tier: 'free' (max 100 URLs) or 'medium' (max 500 URLs).",
    )
    max_results: int = Field(
        default=100,
        ge=1,
        le=500,
        description="Maximum records to return (1–500).",
    )


class CollectByActorsRequest(BaseModel):
    """Request body for URL Scraper actor-based collection.

    Attributes:
        actor_ids: Actor base URLs (``platform_username`` from
            ``ActorPlatformPresence`` where ``platform="url_scraper"``).
        custom_urls: Optional pool of pre-discovered URLs to filter by actor
            domain.  When omitted, each actor base URL is fetched directly.
        tier: Operational tier.
        max_results: Maximum records to return.
    """

    actor_ids: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Actor base URLs (e.g. 'https://naalakkersuisut.gl'). "
            "Must be valid absolute HTTP(S) URLs."
        ),
    )
    custom_urls: list[str] | None = Field(
        default=None,
        description=(
            "Optional URL pool to filter by actor domain.  If omitted, "
            "actor base URLs are fetched directly."
        ),
    )
    tier: str = Field(
        default="free",
        description="Operational tier: 'free' or 'medium'.",
    )
    max_results: int = Field(
        default=100,
        ge=1,
        le=500,
        description="Maximum records to return (1–500).",
    )


class CollectResponse(BaseModel):
    """Response body for URL Scraper collection.

    Attributes:
        count: Number of records returned.
        tier: Tier used for this collection.
        arena: Arena name (``"web"``).
        platform: Platform name (``"url_scraper"``).
        records: Normalized content record dicts.
    """

    count: int
    tier: str
    arena: str
    platform: str
    records: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post(
    "/collect/terms",
    response_model=CollectResponse,
    summary="URL Scraper collection by search terms",
    description=(
        "Fetch all URLs in ``custom_urls``, extract article text, and return "
        "only records where at least one search term appears in the content "
        "or title.  Term matching is case-insensitive substring search.  "
        "For boolean AND/OR logic, supply ``term_groups`` instead of ``terms``."
    ),
)
async def collect_by_terms(
    body: CollectByTermsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect web page content matching the search terms.

    Args:
        body: Request body with URL list, terms, and collection options.
        current_user: Injected authenticated user.

    Returns:
        Normalized content records for pages where terms match.

    Raises:
        HTTPException 400: If the tier value is invalid.
        HTTPException 502: On unexpected collection failure.
    """
    try:
        tier_enum = Tier(body.tier)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tier '{body.tier}'. Valid values: 'free', 'medium'.",
        )

    collector = UrlScraperCollector()

    try:
        records = await collector.collect_by_terms(
            terms=body.terms,
            tier=tier_enum,
            max_results=body.max_results,
            term_groups=body.term_groups,
            extra_urls=body.custom_urls,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "url_scraper router: collection error for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"URL scraper collection failed: {exc}",
        ) from exc

    logger.info(
        "url_scraper router: collect_by_terms — %d records for user=%s",
        len(records),
        current_user.id,
    )
    return CollectResponse(
        count=len(records),
        tier=body.tier,
        arena="web",
        platform="url_scraper",
        records=records,
    )


@router.post(
    "/collect/actors",
    response_model=CollectResponse,
    summary="URL Scraper collection by actor websites",
    description=(
        "Fetch web pages associated with specific actors.  Each actor ID is "
        "a base URL (e.g. 'https://naalakkersuisut.gl').  If ``custom_urls`` "
        "is provided, URLs matching the actor's domain are fetched from that "
        "pool.  Otherwise, the actor's base URL is fetched directly.  "
        "No term filtering is applied — all content is returned."
    ),
)
async def collect_by_actors(
    body: CollectByActorsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect all web page content for the specified actor websites.

    Args:
        body: Request body with actor base URLs and optional URL pool.
        current_user: Injected authenticated user.

    Returns:
        Normalized content records for all successfully fetched pages.

    Raises:
        HTTPException 400: If the tier value is invalid.
        HTTPException 502: On unexpected collection failure.
    """
    try:
        tier_enum = Tier(body.tier)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tier '{body.tier}'. Valid values: 'free', 'medium'.",
        )

    collector = UrlScraperCollector()

    try:
        records = await collector.collect_by_actors(
            actor_ids=body.actor_ids,
            tier=tier_enum,
            max_results=body.max_results,
            extra_urls=body.custom_urls,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "url_scraper router: collect_by_actors error for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"URL scraper collection failed: {exc}",
        ) from exc

    logger.info(
        "url_scraper router: collect_by_actors — %d records for user=%s",
        len(records),
        current_user.id,
    )
    return CollectResponse(
        count=len(records),
        tier=body.tier,
        arena="web",
        platform="url_scraper",
        records=records,
    )


@router.get(
    "/health",
    summary="URL Scraper arena health check",
    description=(
        "Fetch a stable Danish website (www.dr.dk) to verify that the "
        "HTTP fetch and trafilatura extraction pipeline is functional.  "
        "Returns ``ok``, ``degraded``, or ``down``.  No external API is "
        "involved; this validates local scraper infrastructure only."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Run a health check for the URL Scraper arena.

    Args:
        current_user: Injected authenticated user.

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, ``scraper_module``, ``trafilatura``, and
        optionally ``detail``.
    """
    collector = UrlScraperCollector()
    result = await collector.health_check()
    logger.info(
        "url_scraper router: health_check called by user=%s — status=%s",
        current_user.id,
        result.get("status"),
    )
    return result
