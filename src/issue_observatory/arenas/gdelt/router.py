"""Standalone FastAPI router for the GDELT arena.

This router can be imported and mounted independently of the full application
stack for testing or ad-hoc GDELT collection.

Mount in the main app::

    from issue_observatory.arenas.gdelt.router import router as gdelt_router
    app.include_router(gdelt_router, prefix="/api/arenas")

Or run standalone::

    import uvicorn
    from fastapi import FastAPI
    from issue_observatory.arenas.gdelt.router import router

    app = FastAPI()
    app.include_router(router)
    uvicorn.run(app, host="0.0.0.0", port=8082)

Endpoints:

- ``POST /gdelt/collect``  — ad-hoc collection by terms (authenticated).
- ``GET  /gdelt/health``   — arena health check (authenticated).

Notes:
    - ``collect_by_actors`` is not exposed; GDELT does not support it.
    - GDELT uses Danish search terms AND English translations for best coverage
      (see research brief).  Callers should supply both if available.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.gdelt.collector import GDELTCollector
from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.core.exceptions import ArenaCollectionError, ArenaRateLimitError
from issue_observatory.core.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gdelt", tags=["GDELT"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectRequest(BaseModel):
    """Request body for GDELT article collection.

    Attributes:
        terms: Search terms (GDELT Boolean operators supported: AND, OR, NOT,
            quoted phrases).  Supply both Danish and English translations of
            key terms for best coverage (GDELT machine-translates to English).
        date_from: ISO 8601 earliest observation date (inclusive).  GDELT
            DOC API has a rolling 3-month window; earlier dates return empty.
        date_to: ISO 8601 latest observation date (inclusive).
        max_results: Upper bound on returned records.
    """

    terms: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Search terms.  Supply both Danish and English forms for best "
            "coverage (GDELT machine-translates Danish to English)."
        ),
    )
    date_from: str | None = Field(
        default=None,
        description="ISO 8601 start date (inclusive).  Max 3-month lookback.",
    )
    date_to: str | None = Field(
        default=None,
        description="ISO 8601 end date (inclusive).",
    )
    max_results: int = Field(
        default=500,
        ge=1,
        le=5_000,
        description="Maximum records to return (1–5,000).",
    )


class CollectResponse(BaseModel):
    """Response body for GDELT collection.

    Attributes:
        count: Number of records returned.
        tier: Tier used (always ``"free"`` for GDELT).
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
    "/collect",
    response_model=CollectResponse,
    summary="Ad-hoc GDELT article collection",
    description=(
        "Query the GDELT DOC 2.0 API for Danish news articles matching the "
        "supplied terms.  Two queries are issued per term (sourcecountry:DA "
        "and sourcelang:danish); results are deduplicated by URL.  GDELT "
        "provides a rolling 3-month window."
    ),
)
async def collect(
    body: CollectRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect GDELT articles for the given search terms.

    Args:
        body: Request body with terms, optional date range, and max_results.
        current_user: Injected active user.

    Returns:
        Normalized content records and collection metadata.

    Raises:
        HTTPException 429: If the GDELT API is rate-limited.
        HTTPException 502: On upstream API errors.
    """
    collector = GDELTCollector()

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
            "gdelt router: rate limited for user=%s", current_user.id
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"GDELT API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "gdelt router: collection error for user=%s: %s", current_user.id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GDELT collection failed: {exc}",
        ) from exc

    logger.info(
        "gdelt router: collected %d records for user=%s",
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
    summary="GDELT arena health check",
    description=(
        "Issue a minimal DOC API query (``denmark``, maxrecords=1) and verify "
        "a valid JSON response is returned.  Returns ``ok``, ``degraded``, "
        "or ``down``."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Run a health check against the GDELT DOC API.

    Args:
        current_user: Injected active user.

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = GDELTCollector()
    result = await collector.health_check()
    logger.info(
        "gdelt router: health_check called by user=%s — status=%s",
        current_user.id,
        result.get("status"),
    )
    return result
