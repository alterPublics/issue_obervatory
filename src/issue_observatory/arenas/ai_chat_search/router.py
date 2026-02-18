"""Standalone FastAPI router for the AI Chat Search arena.

This router can be imported and mounted independently of the full application
stack for testing or ad-hoc AI chat search collection.

Mount in the main app::

    from issue_observatory.arenas.ai_chat_search.router import router as ai_chat_search_router
    app.include_router(ai_chat_search_router, prefix="/arenas")

Or run standalone::

    import uvicorn
    from fastapi import FastAPI
    from issue_observatory.arenas.ai_chat_search.router import router

    app = FastAPI()
    app.include_router(router)
    uvicorn.run(app, host="0.0.0.0", port=8091)

Endpoints:

- ``POST /ai-chat-search/collect/terms`` — collect by search terms (authenticated).
- ``GET  /ai-chat-search/health``         — arena health check (authenticated).

Notes:
    - MEDIUM or PREMIUM tier required.  FREE tier is explicitly unsupported.
    - Each collection run generates N phrasings per term (5 for MEDIUM,
      10 for PREMIUM) and submits each to Perplexity Sonar via OpenRouter.
    - Returns a mix of ``ai_chat_response`` and ``ai_chat_citation`` records.
    - ``collect_by_actors`` is NOT available — AI chatbots have no author
      search concept.  Source analysis is performed post-hoc on citation records.
    - An ``OPENROUTER_API_KEY`` environment variable or a CredentialPool entry
      with ``platform="openrouter"`` is required.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.ai_chat_search.collector import AiChatSearchCollector
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.core.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai-chat-search", tags=["AI Chat Search"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectTermsRequest(BaseModel):
    """Request body for AI Chat Search term-based collection.

    Attributes:
        terms: Danish search terms to expand and submit to the AI chatbot.
        tier: Operational tier — ``"medium"`` or ``"premium"``.
        max_results: Maximum total records to return (responses + citations).
    """

    terms: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Danish search terms to expand and query.  Each term produces N "
            "phrasings (5 for medium, 10 for premium), each submitted to "
            "Perplexity Sonar via OpenRouter."
        ),
    )
    tier: str = Field(
        default="medium",
        description=(
            "Operational tier: 'medium' (perplexity/sonar, 5 phrasings/term) "
            "or 'premium' (perplexity/sonar-pro, 10 phrasings/term). "
            "FREE tier is not supported for this arena."
        ),
    )
    max_results: int = Field(
        default=500,
        ge=1,
        le=10_000,
        description=(
            "Maximum total records to return across all record types "
            "(ai_chat_response + ai_chat_citation).  Defaults to 500."
        ),
    )


class CollectResponse(BaseModel):
    """Response body for AI Chat Search collection endpoints.

    Attributes:
        count: Total number of records returned (responses + citations).
        tier: Tier used for this collection run.
        arena: Arena name (always ``"ai_chat_search"``).
        records: Normalized content record dicts (mix of
            ``ai_chat_response`` and ``ai_chat_citation`` types).
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
    summary="Collect AI chat search responses and citations by Danish search terms",
    description=(
        "Expand each search term into N realistic Danish phrasings via a free LLM "
        "(google/gemma-3-27b-it:free), then submit each phrasing to Perplexity "
        "Sonar (via OpenRouter) which performs a live web search and returns a "
        "synthesized Danish response.  Produces two record types: "
        "``ai_chat_response`` (one per phrasing) and ``ai_chat_citation`` "
        "(one per cited URL per phrasing).  "
        "MEDIUM tier uses perplexity/sonar with 5 phrasings/term; "
        "PREMIUM tier uses perplexity/sonar-pro with 10 phrasings/term.  "
        "Requires an OpenRouter API key (OPENROUTER_API_KEY env var or CredentialPool)."
    ),
)
async def collect_by_terms(
    body: CollectTermsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect AI chat search responses and citations for the given search terms.

    Args:
        body: Request body with terms, tier, and max_results.
        current_user: Injected active user (authentication required).

    Returns:
        Collection response with normalized content records.

    Raises:
        HTTPException 400: If tier string is not ``"medium"`` or ``"premium"``.
        HTTPException 429: If rate limited by the OpenRouter API.
        HTTPException 503: If no OpenRouter credential is available.
        HTTPException 502: On upstream API errors (auth or collection failures).
    """
    if body.tier not in ("medium", "premium"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid tier '{body.tier}'. "
                "AI Chat Search supports: medium, premium. "
                "FREE tier is not supported (no free web-search AI API exists)."
            ),
        )

    try:
        tier_enum = Tier(body.tier)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tier '{body.tier}'. AI Chat Search supports: medium, premium.",
        )

    collector = AiChatSearchCollector()

    try:
        records = await collector.collect_by_terms(
            terms=body.terms,
            tier=tier_enum,
            max_results=body.max_results,
        )
    except NoCredentialAvailableError as exc:
        logger.warning(
            "ai_chat_search router: no credential for user=%s tier=%s",
            current_user.id,
            body.tier,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"No OpenRouter credential available for tier '{body.tier}'. "
                "Set the OPENROUTER_API_KEY environment variable or provision "
                "credentials in the CredentialPool with platform='openrouter'."
            ),
        ) from exc
    except ArenaAuthError as exc:
        logger.error(
            "ai_chat_search router: auth error for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenRouter API key rejected: {exc}",
        ) from exc
    except ArenaRateLimitError as exc:
        logger.warning(
            "ai_chat_search router: rate limited for user=%s",
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"OpenRouter API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "ai_chat_search router: collection error for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI Chat Search collection failed: {exc}",
        ) from exc

    logger.info(
        "ai_chat_search router: collected %d records for user=%s tier=%s terms=%d",
        len(records),
        current_user.id,
        body.tier,
        len(body.terms),
    )
    return CollectResponse(
        count=len(records),
        tier=body.tier,
        arena="ai_chat_search",
        records=records,
    )


@router.get(
    "/health",
    summary="AI Chat Search arena health check",
    description=(
        "Verify OpenRouter API connectivity by expanding the term 'Danmark' "
        "with 1 phrasing using the free google/gemma-3-27b-it:free model.  "
        "No Perplexity credits are consumed.  "
        "Returns 'ok' if the expansion model is reachable, 'degraded' if "
        "it returns no phrasings, or 'down' if no credential is available "
        "or a connection error occurs."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Run a health check against the OpenRouter API.

    Args:
        current_user: Injected active user (authentication required).

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = AiChatSearchCollector()
    result = await collector.health_check()
    logger.info(
        "ai_chat_search router: health_check called by user=%s — status=%s",
        current_user.id,
        result.get("status"),
    )
    return result
