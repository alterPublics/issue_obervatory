"""Standalone FastAPI router for the Event Registry arena.

This router can be imported and mounted independently of the full application
stack for testing or ad-hoc Event Registry collection.

Mount in the main app::

    from issue_observatory.arenas.event_registry.router import router as event_registry_router
    app.include_router(event_registry_router, prefix="/arenas")

Or run standalone::

    import uvicorn
    from fastapi import FastAPI
    from issue_observatory.arenas.event_registry.router import router

    app = FastAPI()
    app.include_router(router)
    uvicorn.run(app, host="0.0.0.0", port=8090)

Endpoints:

- ``POST /event-registry/collect/terms``  — collect by search terms (authenticated).
- ``POST /event-registry/collect/actors`` — collect by concept URIs (authenticated).
- ``GET  /event-registry/health``         — arena health check (authenticated).

Notes:
    - MEDIUM or PREMIUM tier required.  No free tier exists for this arena.
    - ``actor_ids`` must be Event Registry concept URIs (Wikipedia-based).
      Use the Event Registry ``/suggestConcepts`` endpoint to resolve names.
    - Token budget is the primary operational constraint.  Each page of up to
      100 articles costs 1 token.  Monitor ``remaining_tokens`` in responses.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.event_registry.collector import EventRegistryCollector
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.core.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/event-registry", tags=["Event Registry"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectTermsRequest(BaseModel):
    """Request body for Event Registry keyword-based article collection.

    Attributes:
        terms: Danish search keywords (work natively without translation).
        tier: Operational tier — ``"medium"`` or ``"premium"``.
        date_from: ISO 8601 earliest publication date (inclusive).
        date_to: ISO 8601 latest publication date (inclusive).
        max_results: Maximum records to return per call.
    """

    terms: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Search terms.  Danish keywords work natively "
            "(e.g. 'klimaforandringer', 'sundhedsvaesenet')."
        ),
    )
    tier: str = Field(
        default="medium",
        description="Operational tier: 'medium' (5K tokens/month) or 'premium' (50K tokens/month).",
    )
    date_from: str | None = Field(
        default=None,
        description="ISO 8601 start date (inclusive), e.g. '2026-01-01'.",
    )
    date_to: str | None = Field(
        default=None,
        description="ISO 8601 end date (inclusive), e.g. '2026-02-16'.",
    )
    max_results: int = Field(
        default=500,
        ge=1,
        le=10_000,
        description="Maximum records to return (1–10,000).  Each 100 articles costs 1 token.",
    )


class CollectActorsRequest(BaseModel):
    """Request body for Event Registry concept URI-based collection.

    Attributes:
        actor_ids: Event Registry concept URIs (Wikipedia-based).
        tier: Operational tier — ``"medium"`` or ``"premium"``.
        date_from: ISO 8601 earliest publication date (inclusive).
        date_to: ISO 8601 latest publication date (inclusive).
        max_results: Maximum records to return per call.
    """

    actor_ids: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Event Registry concept or source URIs.  "
            "Example: 'http://en.wikipedia.org/wiki/Mette_Frederiksen'."
        ),
    )
    tier: str = Field(
        default="medium",
        description="Operational tier: 'medium' or 'premium'.",
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


class CollectResponse(BaseModel):
    """Response body for Event Registry collection endpoints.

    Attributes:
        count: Number of normalized records returned.
        tier: Tier used for this collection.
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
    summary="Collect Event Registry Danish news articles by keyword",
    description=(
        "Query the NewsAPI.ai (Event Registry) API for Danish news articles "
        "matching the supplied keywords.  Language filter ``lang='dan'`` and "
        "``sourceLocationUri=Denmark`` are applied automatically.  Full article "
        "body, NLP enrichments (concepts, categories, sentiment), and event "
        "clustering metadata are included in the response.  Each page of up to "
        "100 articles costs 1 Event Registry token."
    ),
)
async def collect_by_terms(
    body: CollectTermsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect Event Registry articles for the given search terms.

    Args:
        body: Request body with terms, tier, optional date range, max_results.
        current_user: Injected active user (authentication required).

    Returns:
        Normalized content records with NLP enrichments and collection metadata.

    Raises:
        HTTPException 400: If tier string is not ``"medium"`` or ``"premium"``.
        HTTPException 429: If rate limited by the Event Registry API.
        HTTPException 402: If token budget is exhausted.
        HTTPException 503: If no credential is available.
        HTTPException 502: On upstream API errors.
    """
    try:
        tier_enum = Tier(body.tier)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tier '{body.tier}'. Event Registry supports: medium, premium.",
        )

    collector = EventRegistryCollector()

    try:
        records = await collector.collect_by_terms(
            terms=body.terms,
            tier=tier_enum,
            date_from=body.date_from,
            date_to=body.date_to,
            max_results=body.max_results,
        )
    except NoCredentialAvailableError as exc:
        logger.warning(
            "event_registry router: no credential for user=%s tier=%s",
            current_user.id,
            body.tier,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No Event Registry credential available for tier '{body.tier}'. "
            "Provision credentials in the CredentialPool.",
        ) from exc
    except ArenaAuthError as exc:
        logger.error(
            "event_registry router: auth error for user=%s: %s", current_user.id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Event Registry API key rejected: {exc}",
        ) from exc
    except ArenaRateLimitError as exc:
        logger.warning(
            "event_registry router: rate limited for user=%s", current_user.id
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Event Registry API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        err_msg = str(exc)
        logger.error(
            "event_registry router: collection error for user=%s: %s",
            current_user.id,
            err_msg,
        )
        # HTTP 402 budget exhaustion gets a specific status code
        http_status = (
            status.HTTP_402_PAYMENT_REQUIRED
            if "token budget exhausted" in err_msg.lower()
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=http_status,
            detail=f"Event Registry collection failed: {err_msg}",
        ) from exc

    logger.info(
        "event_registry router: collected %d records for user=%s tier=%s",
        len(records),
        current_user.id,
        body.tier,
    )
    return CollectResponse(
        count=len(records),
        tier=body.tier,
        arena="news_media",
        records=records,
    )


@router.post(
    "/collect/actors",
    response_model=CollectResponse,
    summary="Collect Event Registry Danish news articles by concept URI",
    description=(
        "Query the NewsAPI.ai (Event Registry) API for Danish news articles "
        "mentioning the specified concept URIs (Wikipedia-based entity URIs).  "
        "Use the Event Registry ``/suggestConcepts`` endpoint to resolve actor "
        "names (e.g. 'Mette Frederiksen', 'Folketing') to URIs before calling "
        "this endpoint.  ``lang='dan'`` and ``sourceLocationUri=Denmark`` are "
        "applied automatically."
    ),
)
async def collect_by_actors(
    body: CollectActorsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect Event Registry articles for the given concept URIs.

    Args:
        body: Request body with actor_ids (concept URIs), tier, date range.
        current_user: Injected active user (authentication required).

    Returns:
        Normalized content records with NLP enrichments.

    Raises:
        HTTPException 400: If tier string is invalid.
        HTTPException 429: If rate limited.
        HTTPException 402: If token budget is exhausted.
        HTTPException 503: If no credential is available.
        HTTPException 502: On upstream API errors.
    """
    try:
        tier_enum = Tier(body.tier)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tier '{body.tier}'. Event Registry supports: medium, premium.",
        )

    collector = EventRegistryCollector()

    try:
        records = await collector.collect_by_actors(
            actor_ids=body.actor_ids,
            tier=tier_enum,
            date_from=body.date_from,
            date_to=body.date_to,
            max_results=body.max_results,
        )
    except NoCredentialAvailableError as exc:
        logger.warning(
            "event_registry router: no credential for user=%s tier=%s",
            current_user.id,
            body.tier,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No Event Registry credential available for tier '{body.tier}'.",
        ) from exc
    except ArenaAuthError as exc:
        logger.error(
            "event_registry router: auth error for user=%s: %s", current_user.id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Event Registry API key rejected: {exc}",
        ) from exc
    except ArenaRateLimitError as exc:
        logger.warning(
            "event_registry router: rate limited for user=%s", current_user.id
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Event Registry API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        err_msg = str(exc)
        logger.error(
            "event_registry router: collection error for user=%s: %s",
            current_user.id,
            err_msg,
        )
        http_status = (
            status.HTTP_402_PAYMENT_REQUIRED
            if "token budget exhausted" in err_msg.lower()
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=http_status,
            detail=f"Event Registry collection failed: {err_msg}",
        ) from exc

    logger.info(
        "event_registry router: collect_by_actors — %d records for user=%s tier=%s",
        len(records),
        current_user.id,
        body.tier,
    )
    return CollectResponse(
        count=len(records),
        tier=body.tier,
        arena="news_media",
        records=records,
    )


@router.get(
    "/health",
    summary="Event Registry arena health check",
    description=(
        "Issue a minimal ``getArticles`` request (``lang='dan'``, "
        "``articlesCount=1``) to verify API connectivity and report remaining "
        "token count.  Requires a valid ``event_registry`` credential in the "
        "CredentialPool.  Returns ``ok``, ``degraded``, or ``down``."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Run a health check against the Event Registry API.

    Args:
        current_user: Injected active user (authentication required).

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, ``remaining_tokens`` (when available), and
        optionally ``detail``.
    """
    collector = EventRegistryCollector()
    result = await collector.health_check()
    logger.info(
        "event_registry router: health_check called by user=%s — status=%s remaining_tokens=%s",
        current_user.id,
        result.get("status"),
        result.get("remaining_tokens"),
    )
    return result
