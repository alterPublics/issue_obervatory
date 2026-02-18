"""Standalone FastAPI router for the VKontakte (VK) arena.

DEFERRED ARENA -- Phase 4 / Future
====================================

All endpoints in this router return HTTP 501 Not Implemented. The routes
are included in the API specification (visible in /docs and /redoc) so that:

1. The deferred status is clearly communicated to API consumers.
2. The intended endpoint contract is documented before implementation.
3. Integration tests can verify the 501 response rather than 404.

DO NOT activate or enable collection without completing the legal review
described in docs/arenas/new_arenas_implementation_plan.md section 6.10.

Mount in the main app::

    from issue_observatory.arenas.vkontakte.router import router as vk_router
    app.include_router(vk_router, prefix="/api/arenas")

Endpoints:

- POST /vkontakte/collect/terms   -- collect by search terms (501)
- POST /vkontakte/collect/actors  -- collect by VK owner IDs (501)
- GET  /vkontakte/health          -- arena health check (not_implemented)
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.arenas.vkontakte.collector import VKontakteCollector
from issue_observatory.core.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vkontakte", tags=["VKontakte"])

_DEFERRED_DETAIL: str = (
    "VKontakte arena is deferred pending university legal review. "
    "See docs/arenas/new_arenas_implementation_plan.md section 6 for details."
)

# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class VKCollectByTermsRequest(BaseModel):
    """Request body for VK term-based collection (deferred -- always 501).

    Attributes:
        terms: Search terms to query against the VK newsfeed.search endpoint.
        date_from: ISO 8601 earliest publication date (inclusive).
        date_to: ISO 8601 latest publication date (inclusive).
        max_results: Upper bound on returned records.
    """

    terms: list[str] = Field(..., min_length=1, description="Search terms to match.")
    date_from: str | None = Field(
        default=None, description="ISO 8601 start date (inclusive)."
    )
    date_to: str | None = Field(
        default=None, description="ISO 8601 end date (inclusive)."
    )
    max_results: int = Field(
        default=500,
        ge=1,
        le=10_000,
        description="Maximum records to return.",
    )


class VKCollectByActorsRequest(BaseModel):
    """Request body for VK actor-based collection (deferred -- always 501).

    Attributes:
        actor_ids: VK owner IDs. Negative integers are community IDs
            (e.g. "-12345"); positive integers are user IDs.
        date_from: ISO 8601 earliest publication date.
        date_to: ISO 8601 latest publication date.
        max_results: Upper bound on returned records.
    """

    actor_ids: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "VK owner IDs. Negative integers are community IDs "
            "(e.g. '-12345'); positive integers are user IDs."
        ),
    )
    date_from: str | None = Field(
        default=None, description="ISO 8601 start date (inclusive)."
    )
    date_to: str | None = Field(
        default=None, description="ISO 8601 end date (inclusive)."
    )
    max_results: int = Field(
        default=500,
        ge=1,
        le=10_000,
        description="Maximum records to return.",
    )


# ---------------------------------------------------------------------------
# Route handlers (all return 501 Not Implemented)
# ---------------------------------------------------------------------------


@router.post(
    "/collect/terms",
    summary="[DEFERRED] Collect VK posts matching search terms",
    description=(
        "**This arena is deferred pending university legal review.**\n\n"
        "When implemented, this endpoint will call `newsfeed.search` on the "
        "VK API to retrieve public posts matching the supplied search terms. "
        "Date range filtering maps to `start_time`/`end_time` Unix timestamps.\n\n"
        "**Legal requirement**: EU sanctions review, GDPR cross-border data "
        "transfer assessment, and university DPO sign-off are required before "
        "this endpoint can be activated.\n\n"
        "See `docs/arenas/new_arenas_implementation_plan.md` section 6 for "
        "full details."
    ),
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
)
async def collect_by_terms(
    body: VKCollectByTermsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Any:
    """Stub endpoint -- raises 501 Not Implemented.

    Args:
        body: Request body (validated but not used).
        current_user: Injected active user.

    Raises:
        HTTPException 501: Always -- arena is deferred pending legal review.
    """
    logger.info(
        "vkontakte router: collect_by_terms called by user=%s -- returning 501 "
        "(deferred arena, pending legal review).",
        current_user.id,
    )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=_DEFERRED_DETAIL,
    )


@router.post(
    "/collect/actors",
    summary="[DEFERRED] Collect VK posts from specific communities or users",
    description=(
        "**This arena is deferred pending university legal review.**\n\n"
        "When implemented, this endpoint will call `wall.get` on the VK API "
        "to retrieve all posts from the specified community (negative owner_id) "
        "or user (positive owner_id) walls.\n\n"
        "**Legal requirement**: EU sanctions review, GDPR cross-border data "
        "transfer assessment, and university DPO sign-off are required before "
        "this endpoint can be activated.\n\n"
        "See `docs/arenas/new_arenas_implementation_plan.md` section 6 for "
        "full details."
    ),
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
)
async def collect_by_actors(
    body: VKCollectByActorsRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Any:
    """Stub endpoint -- raises 501 Not Implemented.

    Args:
        body: Request body (validated but not used).
        current_user: Injected active user.

    Raises:
        HTTPException 501: Always -- arena is deferred pending legal review.
    """
    logger.info(
        "vkontakte router: collect_by_actors called by user=%s -- returning 501 "
        "(deferred arena, pending legal review).",
        current_user.id,
    )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=_DEFERRED_DETAIL,
    )


@router.get(
    "/health",
    summary="VKontakte arena health check",
    description=(
        "Returns the health status of the VKontakte arena. "
        "Since this arena is deferred, status is always `not_implemented`."
    ),
)
async def health(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Return the health status of the (deferred) VKontakte arena.

    Unlike the collect endpoints, this returns HTTP 200 with a
    ``status: not_implemented`` payload rather than 501. This allows
    health monitoring systems to distinguish between a broken arena and
    a deliberately deferred one.

    Args:
        current_user: Injected active user.

    Returns:
        Health status dict with status="not_implemented".
    """
    collector = VKontakteCollector()
    result: dict[str, Any] = await collector.health_check()
    logger.info(
        "vkontakte router: health_check called by user=%s -- status=%s",
        current_user.id,
        result.get("status"),
    )
    return result
