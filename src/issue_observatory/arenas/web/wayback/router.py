"""Standalone FastAPI router for the Wayback Machine arena.

This router can be imported and mounted independently of the full application
stack for testing or ad-hoc Wayback Machine collection.

Mount in the main app::

    from issue_observatory.arenas.web.wayback.router import router as wayback_router
    app.include_router(wayback_router, prefix="/arenas")

Endpoints:

- ``POST /wayback/collect/terms`` — collect CDX captures by URL substring match.
- ``POST /wayback/collect/actors`` — collect CDX captures by domain.
- ``GET  /wayback/health`` — arena health check.

Notes:
    - By default returns CDX snapshot metadata only.
    - When ``fetch_content=true`` is set in the request body, the archived page
      content is fetched and extracted (trafilatura primary, tag-strip fallback).
      FREE tier: up to 50 content fetches per run; MEDIUM: up to 200.
    - Terms are matched as URL substrings (case-insensitive).
    - Actor IDs must be domain names or URL prefixes (e.g. ``"dr.dk"``).
    - The Internet Archive's infrastructure can be fragile. The health check
      may return ``down`` even when the service is partially functional.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.web.wayback.collector import WaybackCollector
from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.core.exceptions import ArenaCollectionError, ArenaRateLimitError
from issue_observatory.core.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wayback", tags=["Wayback Machine"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectByTermsRequest(BaseModel):
    """Request body for Wayback Machine term-based collection.

    Attributes:
        terms: Search terms matched as URL substrings (case-insensitive).
        date_from: ISO 8601 earliest capture date (inclusive).
        date_to: ISO 8601 latest capture date (inclusive).
        max_results: Upper bound on returned records.
        fetch_content: When ``True``, fetch and extract text from each
            archived page.  FREE tier: up to 50 fetches; MEDIUM: up to 200.
            Adds significant latency due to the 15 req/min rate limit.
    """

    terms: list[str] = Field(
        ...,
        min_length=1,
        description="Search terms matched as URL substrings (case-insensitive).",
    )
    date_from: str | None = Field(
        default=None,
        description="ISO 8601 start date (inclusive).",
    )
    date_to: str | None = Field(
        default=None,
        description="ISO 8601 end date (inclusive).",
    )
    max_results: int = Field(
        default=500,
        ge=1,
        le=10_000,
        description="Maximum records to return (1–10,000).",
    )
    fetch_content: bool = Field(
        default=False,
        description=(
            "When true, fetch and extract text from each archived page. "
            "FREE tier: up to 50 content fetches. MEDIUM tier: up to 200. "
            "Substantially increases latency due to the 15 req/min rate limit."
        ),
    )


class CollectByActorsRequest(BaseModel):
    """Request body for Wayback Machine actor-based collection.

    Attributes:
        actor_ids: Domain names or URL prefixes to query
            (e.g. ``["dr.dk", "tv2.dk/nyheder"]``).
        date_from: ISO 8601 earliest capture date (inclusive).
        date_to: ISO 8601 latest capture date (inclusive).
        max_results: Upper bound on returned records.
        fetch_content: When ``True``, fetch and extract text from each
            archived page.  FREE tier: up to 50 fetches; MEDIUM: up to 200.
            Adds significant latency due to the 15 req/min rate limit.
    """

    actor_ids: list[str] = Field(
        ...,
        min_length=1,
        description="Domain names or URL prefixes (e.g. 'dr.dk', 'tv2.dk/nyheder').",
    )
    date_from: str | None = Field(
        default=None,
        description="ISO 8601 start date (inclusive).",
    )
    date_to: str | None = Field(
        default=None,
        description="ISO 8601 end date (inclusive).",
    )
    max_results: int = Field(
        default=500,
        ge=1,
        le=10_000,
        description="Maximum records to return (1–10,000).",
    )
    fetch_content: bool = Field(
        default=False,
        description=(
            "When true, fetch and extract text from each archived page. "
            "FREE tier: up to 50 content fetches. MEDIUM tier: up to 200. "
            "Substantially increases latency due to the 15 req/min rate limit."
        ),
    )


class CollectResponse(BaseModel):
    """Response body for Wayback Machine collection.

    Attributes:
        count: Number of records returned.
        tier: Tier used (always ``"free"`` for Wayback Machine).
        arena: Arena name (always ``"web"``).
        platform: Platform name (always ``"wayback"``).
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
    summary="Wayback Machine collection by search terms",
    description=(
        "Query the Wayback Machine CDX API for Danish (.dk) pages where the URL "
        "contains the search terms. By default returns CDX snapshot metadata. "
        "Set ``fetch_content=true`` to also retrieve and extract archived page text "
        "(trafilatura primary, tag-strip fallback). Terms are matched case-insensitively "
        "as URL substrings."
    ),
)
async def collect_by_terms(
    body: CollectByTermsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect Wayback Machine CDX captures matching the search terms.

    When ``body.fetch_content`` is ``True``, the archived page content is
    fetched via the Wayback playback URL and text is extracted.  This
    substantially increases response time due to the 15 req/min rate limit
    on content fetches.

    Args:
        body: Request body with terms, optional date range, max_results,
            and fetch_content flag.
        current_user: Injected active user.

    Returns:
        Normalized snapshot records and collection metadata.  When
        ``fetch_content`` was ``True``, successfully fetched records have
        ``text_content`` populated and ``content_type`` set to
        ``"web_page"``.

    Raises:
        HTTPException 429: If the CDX API is rate-limited.
        HTTPException 502: On upstream API errors.
    """
    collector = WaybackCollector()

    try:
        records = await collector.collect_by_terms(
            terms=body.terms,
            tier=Tier.FREE,
            date_from=body.date_from,
            date_to=body.date_to,
            max_results=body.max_results,
            fetch_content=body.fetch_content,
        )
    except ArenaRateLimitError as exc:
        logger.warning(
            "wayback router: rate limited for user=%s", current_user.id
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Wayback Machine CDX API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "wayback router: collection error for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Wayback Machine collection failed: {exc}",
        ) from exc

    logger.info(
        "wayback router: collected %d records for user=%s (fetch_content=%s)",
        len(records),
        current_user.id,
        body.fetch_content,
    )
    return CollectResponse(
        count=len(records),
        tier="free",
        arena="web",
        platform="wayback",
        records=records,
    )


@router.post(
    "/collect/actors",
    response_model=CollectResponse,
    summary="Wayback Machine collection by actor domains",
    description=(
        "Query the Wayback Machine CDX API for all captures of the specified "
        "domains or URL prefixes. By default returns CDX snapshot metadata. "
        "Set ``fetch_content=true`` to also retrieve and extract archived page text."
    ),
)
async def collect_by_actors(
    body: CollectByActorsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect Wayback Machine CDX captures for the specified actor domains.

    When ``body.fetch_content`` is ``True``, the archived page content is
    fetched via the Wayback playback URL and text is extracted.

    Args:
        body: Request body with actor_ids, optional date range, max_results,
            and fetch_content flag.
        current_user: Injected active user.

    Returns:
        Normalized snapshot records and collection metadata.  When
        ``fetch_content`` was ``True``, successfully fetched records have
        ``text_content`` populated and ``content_type`` set to
        ``"web_page"``.

    Raises:
        HTTPException 429: If the CDX API is rate-limited.
        HTTPException 502: On upstream API errors.
    """
    collector = WaybackCollector()

    try:
        records = await collector.collect_by_actors(
            actor_ids=body.actor_ids,
            tier=Tier.FREE,
            date_from=body.date_from,
            date_to=body.date_to,
            max_results=body.max_results,
            fetch_content=body.fetch_content,
        )
    except ArenaRateLimitError as exc:
        logger.warning(
            "wayback router: rate limited for user=%s", current_user.id
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Wayback Machine CDX API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "wayback router: collection error for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Wayback Machine collection failed: {exc}",
        ) from exc

    logger.info(
        "wayback router: collected %d records for user=%s (fetch_content=%s)",
        len(records),
        current_user.id,
        body.fetch_content,
    )
    return CollectResponse(
        count=len(records),
        tier="free",
        arena="web",
        platform="wayback",
        records=records,
    )


@router.get(
    "/health",
    summary="Wayback Machine arena health check",
    description=(
        "Query the CDX API for a single capture of ``dr.dk`` and verify a "
        "valid response is returned. Returns ``ok``, ``degraded``, or ``down``. "
        "Note: The Internet Archive can be fragile — ``down`` may be transient."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Run a health check against the Wayback Machine CDX API.

    Args:
        current_user: Injected active user.

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = WaybackCollector()
    result = await collector.health_check()
    logger.info(
        "wayback router: health_check called by user=%s — status=%s",
        current_user.id,
        result.get("status"),
    )
    return result
