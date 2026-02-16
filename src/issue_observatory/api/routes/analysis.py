"""Analysis and statistics routes.

Provides JSON endpoints for descriptive and network analysis of a completed
collection run, plus an HTML page for the analysis dashboard.

All endpoints require authentication and enforce ownership scoping: the
requesting user must have initiated the referenced collection run, or hold
the ``admin`` role.

Routes:
    GET /analysis/                              — redirect to collections list
    GET /analysis/{run_id}                      — HTML analysis dashboard
    GET /analysis/{run_id}/summary              — JSON run summary stats
    GET /analysis/{run_id}/volume               — JSON volume over time
    GET /analysis/{run_id}/actors               — JSON top actors
    GET /analysis/{run_id}/terms                — JSON top terms
    GET /analysis/{run_id}/engagement           — JSON engagement distribution
    GET /analysis/{run_id}/network/actors       — JSON actor co-occurrence graph
    GET /analysis/{run_id}/network/terms        — JSON term co-occurrence graph
    GET /analysis/{run_id}/network/cross-platform  — JSON cross-platform actors
    GET /analysis/{run_id}/network/bipartite    — JSON bipartite actor-term graph
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.analysis.descriptive import (
    get_engagement_distribution,
    get_run_summary,
    get_top_actors,
    get_top_terms,
    get_volume_over_time,
)
from issue_observatory.analysis.network import (
    build_bipartite_network,
    get_actor_co_occurrence,
    get_cross_platform_actors,
    get_term_co_occurrence,
)
from issue_observatory.api.dependencies import get_current_active_user, ownership_guard
from issue_observatory.core.database import get_db
from issue_observatory.core.models.collection import CollectionRun
from issue_observatory.core.models.users import User

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Internal helper — ownership-scoped run lookup
# ---------------------------------------------------------------------------


async def _get_run_or_raise(
    run_id: uuid.UUID,
    db: AsyncSession,
    current_user: User,
) -> CollectionRun:
    """Fetch a CollectionRun and verify the caller's ownership.

    Args:
        run_id: UUID of the collection run.
        db: Active async database session.
        current_user: The authenticated user making the request.

    Returns:
        The ``CollectionRun`` ORM instance.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user is not the owner and not an admin.
    """
    stmt = select(CollectionRun).where(CollectionRun.id == run_id)
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()

    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection run '{run_id}' not found.",
        )

    ownership_guard(run.initiated_by, current_user)
    return run


# ---------------------------------------------------------------------------
# Root redirect
# ---------------------------------------------------------------------------


@router.get("/", include_in_schema=False)
async def analysis_index_redirect() -> RedirectResponse:
    """Redirect to the collections list with a prompt to select a run.

    Returns:
        HTTP 302 redirect to ``/collections``.
    """
    return RedirectResponse(url="/collections", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------


@router.get("/{run_id}", include_in_schema=False)
async def analysis_dashboard(
    run_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Any:
    """Render the analysis dashboard HTML page for a collection run.

    Args:
        run_id: UUID of the collection run to analyse.
        request: The incoming HTTP request (required by Jinja2 TemplateResponse).
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        A Jinja2 ``TemplateResponse`` rendering ``analysis/index.html``.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    run = await _get_run_or_raise(run_id, db, current_user)

    templates = request.app.state.templates
    if templates is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Template engine not initialised.",
        )

    return templates.TemplateResponse(
        "analysis/index.html",
        {
            "request": request,
            "run_id": str(run_id),
            "run": {
                "id": str(run.id),
                "status": run.status,
                "mode": run.mode,
                "query_design_id": str(run.query_design_id) if run.query_design_id else None,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "credits_spent": run.credits_spent,
                "tier": getattr(run, "tier", None),
            },
        },
    )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


@router.get("/{run_id}/summary")
async def run_summary(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Return high-level statistics for a single collection run.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        Dict with run metadata and aggregated statistics.
        See ``analysis.descriptive.get_run_summary`` for the full schema.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    await _get_run_or_raise(run_id, db, current_user)
    return await get_run_summary(db, run_id=run_id)


# ---------------------------------------------------------------------------
# Volume over time
# ---------------------------------------------------------------------------


@router.get("/{run_id}/volume")
async def volume_over_time(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    platform: Optional[str] = Query(default=None, description="Filter by platform."),
    arena: Optional[str] = Query(default=None, description="Filter by arena."),
    date_from: Optional[datetime] = Query(default=None, description="Lower bound on published_at."),
    date_to: Optional[datetime] = Query(default=None, description="Upper bound on published_at."),
    granularity: str = Query(default="day", description="Time bucket: hour, day, week, month."),
) -> list[dict[str, Any]]:
    """Return content volume over time for the given collection run.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        platform: Optional platform filter.
        arena: Optional arena filter.
        date_from: Optional lower bound on ``published_at``.
        date_to: Optional upper bound on ``published_at``.
        granularity: Time bucket size — one of ``hour``, ``day``, ``week``, ``month``.

    Returns:
        List of dicts with ``period``, ``count``, and ``arenas`` breakdown.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
        HTTPException 422: If ``granularity`` is invalid.
    """
    await _get_run_or_raise(run_id, db, current_user)
    try:
        return await get_volume_over_time(
            db,
            run_id=run_id,
            arena=arena,
            platform=platform,
            date_from=date_from,
            date_to=date_to,
            granularity=granularity,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


# ---------------------------------------------------------------------------
# Top actors
# ---------------------------------------------------------------------------


@router.get("/{run_id}/actors")
async def top_actors(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    platform: Optional[str] = Query(default=None, description="Filter by platform."),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200, description="Maximum actors to return."),
) -> list[dict[str, Any]]:
    """Return top authors by post volume and total engagement.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        platform: Optional platform filter.
        date_from: Optional lower bound on ``published_at``.
        date_to: Optional upper bound on ``published_at``.
        limit: Maximum number of actors to return (1–200, default 20).

    Returns:
        List of dicts ordered by post count descending.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    await _get_run_or_raise(run_id, db, current_user)
    return await get_top_actors(
        db,
        run_id=run_id,
        platform=platform,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Top terms
# ---------------------------------------------------------------------------


@router.get("/{run_id}/terms")
async def top_terms(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200, description="Maximum terms to return."),
) -> list[dict[str, Any]]:
    """Return top search terms by match frequency across content records.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        date_from: Optional lower bound on ``published_at``.
        date_to: Optional upper bound on ``published_at``.
        limit: Maximum number of terms to return (1–200, default 20).

    Returns:
        List of dicts with ``term`` and ``count``, ordered by count descending.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    await _get_run_or_raise(run_id, db, current_user)
    return await get_top_terms(
        db,
        run_id=run_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Engagement distribution
# ---------------------------------------------------------------------------


@router.get("/{run_id}/engagement")
async def engagement_distribution(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    platform: Optional[str] = Query(default=None),
    arena: Optional[str] = Query(default=None),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
) -> dict[str, Any]:
    """Return statistical distribution of per-post engagement metrics.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        platform: Optional platform filter.
        arena: Optional arena filter.
        date_from: Optional lower bound on ``published_at``.
        date_to: Optional upper bound on ``published_at``.

    Returns:
        Dict keyed by metric (likes, shares, comments, views) with
        mean, median, p95, and max sub-keys.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    await _get_run_or_raise(run_id, db, current_user)
    return await get_engagement_distribution(
        db,
        run_id=run_id,
        arena=arena,
        platform=platform,
        date_from=date_from,
        date_to=date_to,
    )


# ---------------------------------------------------------------------------
# Network — actor co-occurrence
# ---------------------------------------------------------------------------


@router.get("/{run_id}/network/actors")
async def network_actors(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    platform: Optional[str] = Query(default=None),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    min_co_occurrences: int = Query(default=2, ge=1, description="Minimum edge weight."),
) -> dict[str, Any]:
    """Return the actor co-occurrence graph for the given collection run.

    Two actors co-occur when their posts share at least one search term.
    The edge weight is the number of distinct content record pairs.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        platform: Optional platform filter applied to both sides of the join.
        date_from: Optional lower bound on ``published_at``.
        date_to: Optional upper bound on ``published_at``.
        min_co_occurrences: Minimum edge weight to include (default 2).

    Returns:
        Graph dict ``{nodes: [...], edges: [...]}``.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    await _get_run_or_raise(run_id, db, current_user)
    return await get_actor_co_occurrence(
        db,
        run_id=run_id,
        platform=platform,
        date_from=date_from,
        date_to=date_to,
        min_co_occurrences=min_co_occurrences,
    )


# ---------------------------------------------------------------------------
# Network — term co-occurrence
# ---------------------------------------------------------------------------


@router.get("/{run_id}/network/terms")
async def network_terms(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    min_co_occurrences: int = Query(default=2, ge=1, description="Minimum shared records."),
) -> dict[str, Any]:
    """Return the term co-occurrence graph for the given collection run.

    Two terms co-occur when they appear together in the same content record's
    ``search_terms_matched`` array.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        min_co_occurrences: Minimum number of shared records (default 2).

    Returns:
        Graph dict ``{nodes: [...], edges: [...]}``.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    await _get_run_or_raise(run_id, db, current_user)
    return await get_term_co_occurrence(
        db,
        run_id=run_id,
        min_co_occurrences=min_co_occurrences,
    )


# ---------------------------------------------------------------------------
# Network — cross-platform actors
# ---------------------------------------------------------------------------


@router.get("/{run_id}/network/cross-platform")
async def network_cross_platform(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    min_platforms: int = Query(default=2, ge=2, description="Minimum platform count."),
) -> list[dict[str, Any]]:
    """Return canonical actors active on multiple platforms in this run.

    Only records where entity resolution has been performed (``author_id`` is
    non-null) are considered.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        min_platforms: Minimum number of distinct platforms required (default 2).

    Returns:
        List of dicts with ``actor_id``, ``canonical_name``, ``platform_count``,
        ``platforms``, and ``total_records``, ordered by platform count descending.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    await _get_run_or_raise(run_id, db, current_user)
    return await get_cross_platform_actors(
        db,
        run_id=run_id,
        min_platforms=min_platforms,
    )


# ---------------------------------------------------------------------------
# Network — bipartite actor-term graph
# ---------------------------------------------------------------------------


@router.get("/{run_id}/network/bipartite")
async def network_bipartite(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: int = Query(default=500, ge=1, le=2000, description="Max edges to return."),
) -> dict[str, Any]:
    """Return the bipartite actor-term graph for the given collection run.

    Each unique ``(pseudonymized_author_id, term)`` pair becomes an edge.
    The edge weight is the number of content records where that author matched
    that term.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        limit: Maximum number of edges to return (default 500, max 2000).

    Returns:
        Graph dict ``{nodes: [...], edges: [...]}`` with typed nodes
        (``type: "actor"`` or ``type: "term"``).

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    await _get_run_or_raise(run_id, db, current_user)
    return await build_bipartite_network(
        db,
        run_id=run_id,
        limit=limit,
    )
