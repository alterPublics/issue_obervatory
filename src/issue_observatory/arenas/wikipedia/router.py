"""Standalone FastAPI router for the Wikipedia arena.

This router can be imported and mounted independently of the full application
stack for testing or ad-hoc Wikipedia collection.

Mount in the main app::

    from issue_observatory.arenas.wikipedia.router import router as wikipedia_router
    app.include_router(wikipedia_router, prefix="/api/arenas")

Or run standalone::

    import uvicorn
    from fastapi import FastAPI
    from issue_observatory.arenas.wikipedia.router import router

    app = FastAPI()
    app.include_router(router)
    uvicorn.run(app, host="0.0.0.0", port=8082)

Endpoints:

- ``POST /wikipedia/collect/terms``  — collect revisions and pageviews by
  search terms (authenticated).
- ``POST /wikipedia/collect/actors`` — collect revisions by Wikipedia
  usernames (authenticated).
- ``GET  /wikipedia/health``         — arena health check (authenticated).
- ``GET  /wikipedia/pageviews/{article}`` — direct pageview lookup for a
  specific article and date range (authenticated, convenience endpoint).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.wikipedia.collector import WikipediaCollector
from issue_observatory.arenas.wikipedia.config import (
    DEFAULT_MAX_RESULTS,
    DEFAULT_WIKI_PROJECTS,
)
from issue_observatory.core.exceptions import ArenaCollectionError, ArenaRateLimitError
from issue_observatory.core.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wikipedia", tags=["Wikipedia"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectByTermsRequest(BaseModel):
    """Request body for term-based Wikipedia collection.

    Attributes:
        terms: Search terms matched against Wikipedia article titles and
            content via the MediaWiki full-text search API.
        date_from: ISO 8601 earliest revision date to include (inclusive).
        date_to: ISO 8601 latest revision date to include (inclusive).
        max_results: Upper bound on returned records.
        language_filter: Restrict to specific Wikipedia language editions.
            ``["da"]`` for Danish only, ``["da", "en"]`` for both.
        include_pageviews: Whether to include daily pageview records for
            discovered articles (in addition to revision records).
    """

    terms: list[str] = Field(..., min_length=1, description="Search terms to match against Wikipedia articles.")
    date_from: str | None = Field(default=None, description="ISO 8601 start date (inclusive).")
    date_to: str | None = Field(default=None, description="ISO 8601 end date (inclusive).")
    max_results: int = Field(
        default=DEFAULT_MAX_RESULTS,
        ge=1,
        le=5_000,
        description="Maximum records to return.",
    )
    language_filter: list[str] | None = Field(
        default=None,
        description="Language editions to query: 'da', 'en', or both. Defaults to both.",
    )


class CollectByActorsRequest(BaseModel):
    """Request body for actor-based Wikipedia collection.

    Attributes:
        actor_ids: Wikipedia usernames whose contribution history to collect.
        date_from: ISO 8601 earliest contribution date to include.
        date_to: ISO 8601 latest contribution date to include.
        max_results: Upper bound on returned records.
    """

    actor_ids: list[str] = Field(..., min_length=1, description="Wikipedia usernames to collect contributions for.")
    date_from: str | None = Field(default=None, description="ISO 8601 start date (inclusive).")
    date_to: str | None = Field(default=None, description="ISO 8601 end date (inclusive).")
    max_results: int = Field(
        default=DEFAULT_MAX_RESULTS,
        ge=1,
        le=5_000,
        description="Maximum records to return.",
    )


class CollectResponse(BaseModel):
    """Response body for Wikipedia collection endpoints.

    Attributes:
        count: Number of records returned.
        tier: Tier used (always ``"free"`` for Wikipedia).
        arena: Arena group (always ``"reference"``).
        records: Normalized content record dicts (mix of ``wiki_revision``
            and ``wiki_pageview`` types).
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
    summary="Collect Wikipedia revisions and pageviews matching search terms",
    description=(
        "Searches Danish (and optionally English) Wikipedia for articles "
        "matching the supplied terms, then collects revision history and "
        "daily pageview data for each discovered article. Returns a mix of "
        "``wiki_revision`` and ``wiki_pageview`` content records."
    ),
)
async def collect_by_terms(
    body: CollectByTermsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect Wikipedia records by term-based article discovery.

    Args:
        body: Request body with terms, date range, and optional language filter.
        current_user: Injected active user.

    Returns:
        Normalized content records and collection metadata.

    Raises:
        HTTPException 429: On rate limit from Wikimedia APIs.
        HTTPException 502: On unrecoverable collection error.
    """
    collector = WikipediaCollector()

    try:
        records = await collector.collect_by_terms(
            terms=body.terms,
            tier=Tier.FREE,
            date_from=body.date_from,
            date_to=body.date_to,
            max_results=body.max_results,
            language_filter=body.language_filter,
        )
    except ArenaRateLimitError as exc:
        logger.warning(
            "wikipedia router: rate limited for user=%s", current_user.id
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Wikipedia collection rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "wikipedia router: collection error for user=%s: %s", current_user.id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Wikipedia collection failed: {exc}",
        ) from exc

    logger.info(
        "wikipedia router: collect_by_terms returned %d records for user=%s",
        len(records),
        current_user.id,
    )
    return CollectResponse(
        count=len(records),
        tier="free",
        arena="reference",
        records=records,
    )


@router.post(
    "/collect/actors",
    response_model=CollectResponse,
    summary="Collect Wikipedia revisions by editor username",
    description=(
        "Retrieves the contribution history of specific Wikipedia editors "
        "(by username) on both Danish and English Wikipedia. Returns "
        "``wiki_revision`` records for each edit made by the specified users "
        "within the optional date range."
    ),
)
async def collect_by_actors(
    body: CollectByActorsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect Wikipedia revision records for specific Wikipedia editors.

    Args:
        body: Request body with usernames and optional date range.
        current_user: Injected active user.

    Returns:
        Normalized content records and collection metadata.

    Raises:
        HTTPException 429: On rate limit from Wikimedia APIs.
        HTTPException 502: On unrecoverable collection error.
    """
    collector = WikipediaCollector()

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
            detail=f"Wikipedia rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "wikipedia router: collection error for user=%s: %s", current_user.id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Wikipedia collection failed: {exc}",
        ) from exc

    logger.info(
        "wikipedia router: collect_by_actors returned %d records for user=%s",
        len(records),
        current_user.id,
    )
    return CollectResponse(
        count=len(records),
        tier="free",
        arena="reference",
        records=records,
    )


@router.get(
    "/health",
    summary="Wikipedia arena health check",
    description=(
        "Fetches ``action=query&meta=siteinfo`` from ``da.wikipedia.org`` "
        "and verifies the response is valid JSON. Returns ``ok``, or "
        "``down`` if the API is unreachable."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Run a health check for the Wikipedia arena.

    Args:
        current_user: Injected active user.

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``site`` or ``detail``.
    """
    collector = WikipediaCollector()
    result = await collector.health_check()
    logger.info(
        "wikipedia router: health_check called by user=%s — status=%s",
        current_user.id,
        result.get("status"),
    )
    return result


@router.get(
    "/pageviews/{article}",
    summary="Fetch daily pageviews for a specific Wikipedia article",
    description=(
        "Convenience endpoint for direct pageview lookup. Returns daily "
        "``wiki_pageview`` records for the specified article title on the "
        "requested wiki project (default: ``da.wikipedia``) over the given "
        "date range (default: last 30 days)."
    ),
)
async def get_pageviews(
    article: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    wiki_project: str = Query(
        default="da.wikipedia",
        description="Wiki project identifier (e.g. 'da.wikipedia' or 'en.wikipedia').",
    ),
    date_from: str | None = Query(
        default=None,
        description="ISO 8601 start date (inclusive). Defaults to 30 days ago.",
    ),
    date_to: str | None = Query(
        default=None,
        description="ISO 8601 end date (inclusive). Defaults to yesterday.",
    ),
) -> dict[str, Any]:
    """Fetch daily pageview records for a specific Wikipedia article.

    Args:
        article: Wikipedia article title (URL-decoded; spaces are acceptable).
        current_user: Injected active user.
        wiki_project: Wiki project identifier.
        date_from: Start of the date range.
        date_to: End of the date range.

    Returns:
        Dict with ``count``, ``article``, ``wiki_project``, and ``records``
        (list of normalized ``wiki_pageview`` dicts).

    Raises:
        HTTPException 400: If the wiki_project value is unrecognised.
        HTTPException 429: On rate limit.
        HTTPException 502: On API error.
    """
    if wiki_project not in DEFAULT_WIKI_PROJECTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown wiki_project '{wiki_project}'. "
                f"Valid values: {DEFAULT_WIKI_PROJECTS}"
            ),
        )

    # Resolve date range: default to last 30 days ending yesterday.
    now = datetime.now(tz=timezone.utc)
    if date_to is None:
        date_to = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    if date_from is None:
        date_from = (now - timedelta(days=31)).strftime("%Y-%m-%d")

    from issue_observatory.arenas.wikipedia.collector import (  # noqa: PLC0415
        _resolve_pageview_date_range,
    )

    pv_start, pv_end = _resolve_pageview_date_range(date_from, date_to)

    collector = WikipediaCollector()
    semaphore = asyncio.Semaphore(5)

    try:
        async with collector._build_http_client() as client:
            raw_pvs = await collector._get_pageviews(
                client, article, wiki_project, pv_start, pv_end, semaphore
            )
        records = [collector.normalize(pv) for pv in raw_pvs]
    except ArenaRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Wikimedia rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Pageview lookup failed: {exc}",
        ) from exc

    logger.info(
        "wikipedia router: pageviews for '%s' on %s — %d records for user=%s",
        article,
        wiki_project,
        len(records),
        current_user.id,
    )
    return {
        "count": len(records),
        "article": article,
        "wiki_project": wiki_project,
        "date_from": date_from,
        "date_to": date_to,
        "records": records,
    }
