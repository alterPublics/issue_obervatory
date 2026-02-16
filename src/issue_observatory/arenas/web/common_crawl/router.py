"""Standalone FastAPI router for the Common Crawl arena.

This router can be imported and mounted independently of the full application
stack for testing or ad-hoc Common Crawl collection.

Mount in the main app::

    from issue_observatory.arenas.web.common_crawl.router import router as common_crawl_router
    app.include_router(common_crawl_router, prefix="/arenas")

Endpoints:

- ``POST /common-crawl/collect/terms`` — collect index entries by search terms.
- ``POST /common-crawl/collect/actors`` — collect index entries by domain.
- ``GET  /common-crawl/health`` — arena health check.

Notes:
    - Returns CC Index metadata only; WARC content retrieval is out of scope.
    - Terms are matched as URL substrings (case-insensitive).
    - Actor IDs must be registered domain names (e.g. ``"dr.dk"``).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.web.common_crawl.collector import CommonCrawlCollector
from issue_observatory.arenas.web.common_crawl.config import CC_DEFAULT_INDEX
from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.core.exceptions import ArenaCollectionError, ArenaRateLimitError
from issue_observatory.core.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/common-crawl", tags=["Common Crawl"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectByTermsRequest(BaseModel):
    """Request body for Common Crawl term-based collection.

    Attributes:
        terms: Search terms matched as URL substrings (case-insensitive).
        date_from: ISO 8601 earliest capture date (inclusive).
        date_to: ISO 8601 latest capture date (inclusive).
        max_results: Upper bound on returned records.
        cc_index: Common Crawl index to query. Defaults to the most recent.
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
    cc_index: str = Field(
        default=CC_DEFAULT_INDEX,
        description="Common Crawl index identifier (e.g. 'CC-MAIN-2025-51').",
    )


class CollectByActorsRequest(BaseModel):
    """Request body for Common Crawl actor-based collection.

    Attributes:
        actor_ids: Domain names to query (e.g. ``["dr.dk", "tv2.dk"]``).
        date_from: ISO 8601 earliest capture date (inclusive).
        date_to: ISO 8601 latest capture date (inclusive).
        max_results: Upper bound on returned records.
        cc_index: Common Crawl index to query.
    """

    actor_ids: list[str] = Field(
        ...,
        min_length=1,
        description="Registered domain names (e.g. 'dr.dk', 'tv2.dk').",
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
    cc_index: str = Field(
        default=CC_DEFAULT_INDEX,
        description="Common Crawl index identifier (e.g. 'CC-MAIN-2025-51').",
    )


class CollectResponse(BaseModel):
    """Response body for Common Crawl collection.

    Attributes:
        count: Number of records returned.
        tier: Tier used (always ``"free"`` for Common Crawl).
        arena: Arena name (always ``"web"``).
        platform: Platform name (always ``"common_crawl"``).
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
    summary="Common Crawl collection by search terms",
    description=(
        "Query the Common Crawl Index API for Danish (.dk) pages where the URL "
        "contains the search terms. Returns index metadata only — WARC record "
        "retrieval (full page content) is out of scope. Terms are matched "
        "case-insensitively as URL substrings."
    ),
)
async def collect_by_terms(
    body: CollectByTermsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect Common Crawl index entries matching the search terms.

    Args:
        body: Request body with terms, optional date range, and max_results.
        current_user: Injected active user.

    Returns:
        Normalized index entry records and collection metadata.

    Raises:
        HTTPException 429: If the CC Index API is rate-limited.
        HTTPException 502: On upstream API errors.
    """
    collector = CommonCrawlCollector(cc_index=body.cc_index)

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
            "common_crawl router: rate limited for user=%s", current_user.id
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Common Crawl API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "common_crawl router: collection error for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Common Crawl collection failed: {exc}",
        ) from exc

    logger.info(
        "common_crawl router: collected %d records for user=%s",
        len(records),
        current_user.id,
    )
    return CollectResponse(
        count=len(records),
        tier="free",
        arena="web",
        platform="common_crawl",
        records=records,
    )


@router.post(
    "/collect/actors",
    response_model=CollectResponse,
    summary="Common Crawl collection by actor domains",
    description=(
        "Query the Common Crawl Index API for all captures of the specified "
        "domains. Actor IDs must be registered domain names (e.g. 'dr.dk'). "
        "Returns index metadata only."
    ),
)
async def collect_by_actors(
    body: CollectByActorsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect Common Crawl index entries for the specified actor domains.

    Args:
        body: Request body with actor_ids (domain names), date range, etc.
        current_user: Injected active user.

    Returns:
        Normalized index entry records and collection metadata.

    Raises:
        HTTPException 429: If the CC Index API is rate-limited.
        HTTPException 502: On upstream API errors.
    """
    collector = CommonCrawlCollector(cc_index=body.cc_index)

    try:
        records = await collector.collect_by_actors(
            actor_ids=body.actor_ids,
            tier=Tier.FREE,
            date_from=body.date_from,
            date_to=body.date_to,
            max_results=body.max_results,
        )
    except ArenaRateLimitError as exc:
        logger.warning(
            "common_crawl router: rate limited for user=%s", current_user.id
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Common Crawl API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "common_crawl router: collection error for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Common Crawl collection failed: {exc}",
        ) from exc

    logger.info(
        "common_crawl router: collected %d records for user=%s",
        len(records),
        current_user.id,
    )
    return CollectResponse(
        count=len(records),
        tier="free",
        arena="web",
        platform="common_crawl",
        records=records,
    )


@router.get(
    "/health",
    summary="Common Crawl arena health check",
    description=(
        "Fetch ``https://index.commoncrawl.org/collinfo.json`` and verify that "
        "a non-empty list of crawl indexes is returned. Returns ``ok``, "
        "``degraded``, or ``down``."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Run a health check against the Common Crawl Index API.

    Args:
        current_user: Injected active user.

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail`` or ``latest_index``.
    """
    collector = CommonCrawlCollector()
    result = await collector.health_check()
    logger.info(
        "common_crawl router: health_check called by user=%s — status=%s",
        current_user.id,
        result.get("status"),
    )
    return result
