"""Standalone FastAPI router for the Reddit arena.

This router can be imported and mounted independently of the full application
stack for testing or ad-hoc collection without a collection run.

Mount in the main app::

    from issue_observatory.arenas.reddit.router import router as reddit_router
    app.include_router(reddit_router, prefix="/api/arenas")

Or run standalone (for local testing)::

    import uvicorn
    from fastapi import FastAPI
    from issue_observatory.arenas.reddit.router import router

    app = FastAPI()
    app.include_router(router)
    uvicorn.run(app, host="0.0.0.0", port=8080)

Endpoints:

- ``POST /reddit/collect/terms``  — ad-hoc term-based collection (authenticated).
- ``POST /reddit/collect/actors`` — ad-hoc actor-based collection (authenticated).
- ``GET  /reddit/health``         — arena health check (authenticated).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.reddit.collector import RedditCollector
from issue_observatory.core.credential_pool import CredentialPool
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.core.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reddit", tags=["Reddit"])

# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CollectByTermsRequest(BaseModel):
    """Request body for ad-hoc Reddit term-based collection.

    Attributes:
        terms: One or more search terms to query across Danish subreddits.
        max_results: Maximum number of records to return.
        include_comments: Whether to fetch top-level comments for matched posts.
            Increases API quota usage significantly.
    """

    terms: list[str] = Field(..., min_length=1, description="Search terms to query.")
    max_results: int = Field(
        default=100,
        ge=1,
        le=1_000,
        description="Maximum records to return (1–1,000).",
    )
    include_comments: bool = Field(
        default=False,
        description="Collect top-level comments for each matched post.",
    )


class CollectByActorsRequest(BaseModel):
    """Request body for ad-hoc Reddit actor-based collection.

    Attributes:
        actor_ids: Reddit usernames to collect from (without ``u/`` prefix).
        max_results: Maximum number of records to return per actor.
    """

    actor_ids: list[str] = Field(
        ..., min_length=1, description="Reddit usernames to collect from."
    )
    max_results: int = Field(
        default=100,
        ge=1,
        le=1_000,
        description="Maximum records to return (1–1,000).",
    )


class CollectResponse(BaseModel):
    """Response body for ad-hoc collection.

    Attributes:
        count: Number of records returned.
        tier: Tier used for collection (always ``"free"`` for Reddit).
        arena: Arena name (always ``"social_media"``).
        platform: Platform name (always ``"reddit"``).
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
    summary="Ad-hoc Reddit term-based collection",
    description=(
        "Search Reddit across Danish subreddits for the supplied terms. "
        "Results are deduplicated by post ID.  Intended for testing arena "
        "connectivity and exploring result quality without a full collection run."
    ),
)
async def collect_by_terms(
    body: CollectByTermsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect Reddit posts matching the given search terms.

    Args:
        body: Request body with terms, max_results, and include_comments flag.
        current_user: Injected active user (from JWT cookie or bearer token).

    Returns:
        Normalized content records and collection metadata.

    Raises:
        HTTPException 402: If no Reddit OAuth credential is configured.
        HTTPException 429: If the Reddit API is rate-limited.
        HTTPException 502: On Reddit API errors.
    """
    credential_pool = CredentialPool()
    collector = RedditCollector(
        credential_pool=credential_pool,
        include_comments=body.include_comments,
    )

    try:
        records = await collector.collect_by_terms(
            terms=body.terms,
            tier=Tier.FREE,
            max_results=body.max_results,
        )
    except NoCredentialAvailableError as exc:
        logger.warning(
            "reddit router: no credential for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "No Reddit OAuth credential configured. "
                "Ask an administrator to add a Reddit credential "
                "(platform='reddit', tier='free') via the credential management API."
            ),
        ) from exc
    except ArenaRateLimitError as exc:
        logger.warning(
            "reddit router: rate limited (retry_after=%.0fs) user=%s",
            exc.retry_after,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Reddit API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaAuthError as exc:
        logger.error(
            "reddit router: auth error for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Reddit API rejected the credential. "
                "Ask an administrator to verify the Reddit OAuth app credentials."
            ),
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "reddit router: collection error for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Reddit collection failed: {exc}",
        ) from exc

    logger.info(
        "reddit router: collect_by_terms — user=%s terms=%d records=%d",
        current_user.id,
        len(body.terms),
        len(records),
    )
    return CollectResponse(
        count=len(records),
        tier="free",
        arena="social_media",
        platform="reddit",
        records=records,
    )


@router.post(
    "/collect/actors",
    response_model=CollectResponse,
    summary="Ad-hoc Reddit actor-based collection",
    description=(
        "Collect posts and comments published by the specified Reddit usernames. "
        "Intended for testing actor collection without a full collection run."
    ),
)
async def collect_by_actors(
    body: CollectByActorsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectResponse:
    """Collect Reddit content from specific user accounts.

    Args:
        body: Request body with actor_ids (Reddit usernames) and max_results.
        current_user: Injected active user.

    Returns:
        Normalized content records and collection metadata.

    Raises:
        HTTPException 402: If no Reddit OAuth credential is configured.
        HTTPException 429: If the Reddit API is rate-limited.
        HTTPException 502: On Reddit API errors.
    """
    credential_pool = CredentialPool()
    collector = RedditCollector(credential_pool=credential_pool)

    try:
        records = await collector.collect_by_actors(
            actor_ids=body.actor_ids,
            tier=Tier.FREE,
            max_results=body.max_results,
        )
    except NoCredentialAvailableError as exc:
        logger.warning(
            "reddit router: no credential for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "No Reddit OAuth credential configured. "
                "Ask an administrator to add a Reddit credential."
            ),
        ) from exc
    except ArenaRateLimitError as exc:
        logger.warning(
            "reddit router: rate limited (retry_after=%.0fs) user=%s",
            exc.retry_after,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Reddit API rate limited. Retry after {exc.retry_after:.0f} seconds.",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ArenaAuthError as exc:
        logger.error(
            "reddit router: auth error for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Reddit API rejected the credential.",
        ) from exc
    except ArenaCollectionError as exc:
        logger.error(
            "reddit router: collection error for user=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Reddit actor collection failed: {exc}",
        ) from exc

    logger.info(
        "reddit router: collect_by_actors — user=%s actors=%d records=%d",
        current_user.id,
        len(body.actor_ids),
        len(records),
    )
    return CollectResponse(
        count=len(records),
        tier="free",
        arena="social_media",
        platform="reddit",
        records=records,
    )


@router.get(
    "/health",
    summary="Reddit arena health check",
    description=(
        "Verify that the Reddit API is reachable and the configured OAuth "
        "credential is accepted.  Fetches a single hot post from r/Denmark. "
        "Returns a status dict with one of: ``ok``, ``degraded``, or ``down``."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Run a health check against the Reddit API.

    Args:
        current_user: Injected active user (authentication required to
            prevent unauthenticated probing of OAuth credentials).

    Returns:
        Health status dict with ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    credential_pool = CredentialPool()
    collector = RedditCollector(credential_pool=credential_pool)
    result = await collector.health_check()
    logger.info(
        "reddit router: health_check called by user=%s — status=%s",
        current_user.id,
        result.get("status"),
    )
    return result
