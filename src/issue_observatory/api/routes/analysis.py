"""Analysis and statistics routes.

Provides JSON endpoints for descriptive and network analysis of a completed
collection run, plus an HTML page for the analysis dashboard.

All endpoints require authentication and enforce ownership scoping: the
requesting user must have initiated the referenced collection run, or hold
the ``admin`` role.

Routes:
    GET /analysis/                                      — redirect to collections list
    GET /analysis/{run_id}                              — HTML analysis dashboard
    GET /analysis/{run_id}/summary                      — JSON run summary stats
    GET /analysis/{run_id}/volume                       — JSON volume over time
    GET /analysis/{run_id}/actors                       — JSON top actors
    GET /analysis/{run_id}/actors-unified               — JSON top actors by canonical identity
    GET /analysis/{run_id}/terms                        — JSON top terms
    GET /analysis/{run_id}/emergent-terms               — JSON TF-IDF emergent terms
    GET /analysis/{run_id}/engagement                   — JSON engagement distribution
    GET /analysis/{run_id}/network/actors               — JSON actor co-occurrence graph (supports ?arena=)
    GET /analysis/{run_id}/network/terms                — JSON term co-occurrence graph (supports ?arena=)
    GET /analysis/{run_id}/network/cross-platform       — JSON cross-platform actors
    GET /analysis/{run_id}/network/bipartite            — JSON bipartite actor-term graph (supports ?arena=)
    GET /analysis/{run_id}/network/temporal             — JSON temporal network snapshots
    GET /analysis/{run_id}/network/enhanced-bipartite   — JSON enhanced bipartite network
    GET /analysis/{run_id}/network/{type}/temporal      — JSON temporal index (path alias)
    GET /analysis/{run_id}/network/{type}/temporal/{period} — JSON single-period graph

Per-arena GEXF export (IP2-047):
    The ``/network/actors``, ``/network/terms``, and ``/network/bipartite``
    endpoints all accept an optional ``arena`` query parameter.  Passing
    ``?arena=<arena_slug>`` restricts the underlying co-occurrence query to
    records from that arena only.  The response graph dict can then be passed
    directly to ``ContentExporter.export_gexf()`` to produce an arena-scoped
    GEXF file for cross-arena comparison in Gephi.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.analysis.coordination import get_coordination_events
from issue_observatory.analysis.descriptive import (
    compare_runs,
    get_arena_comparison,
    get_coordination_signals,
    get_emergent_terms,
    get_engagement_distribution,
    get_language_distribution,
    get_propagation_patterns,
    get_run_summary,
    get_sentiment_distribution,
    get_temporal_comparison,
    get_top_actors,
    get_top_actors_unified,
    get_top_named_entities,
    get_top_terms,
    get_volume_over_time,
)
from issue_observatory.analysis.propagation import get_propagation_flows
from issue_observatory.analysis.export import ContentExporter
from issue_observatory.analysis.network import (
    build_bipartite_network,
    build_enhanced_bipartite_network,
    get_actor_co_occurrence,
    get_cross_platform_actors,
    get_temporal_network_snapshots,
    get_term_co_occurrence,
)
from issue_observatory.api.dependencies import get_current_active_user, ownership_guard
from issue_observatory.core.database import get_db
from issue_observatory.core.models.collection import CollectionRun
from issue_observatory.core.models.content import UniversalContentRecord
from issue_observatory.core.models.query_design import QueryDesign, SearchTerm
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
# Cross-run comparison (SB-06)
# ---------------------------------------------------------------------------


@router.get("/compare")
async def compare_collection_runs(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    run_ids: str = Query(
        ...,
        description="Comma-separated list of exactly two run UUIDs to compare (baseline,new).",
    ),
) -> dict[str, Any]:
    """Compare two collection runs and return delta metrics.

    Computes volume deltas, new actors in run 2 not in run 1, new terms,
    and content overlap (via content_hash). Run 1 is treated as the baseline,
    run 2 as the new run.

    The requesting user must own both runs (or be an admin).

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        run_ids: Comma-separated pair of run UUIDs, e.g. ``run1_id,run2_id``.

    Returns:
        Dict with ``volume_delta``, ``new_actors``, ``new_terms``, and
        ``content_overlap`` keys. See ``compare_runs`` in
        ``analysis.descriptive`` for the full schema.

    Raises:
        HTTPException 400: If ``run_ids`` does not contain exactly 2 UUIDs.
        HTTPException 404: If either run does not exist.
        HTTPException 403: If the current user does not own both runs.
    """
    parts = [p.strip() for p in run_ids.split(",") if p.strip()]
    if len(parts) != 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="run_ids must contain exactly two comma-separated UUIDs.",
        )

    try:
        run_id_1 = uuid.UUID(parts[0])
        run_id_2 = uuid.UUID(parts[1])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid UUID format in run_ids: {exc}",
        ) from exc

    # Verify ownership of both runs
    await _get_run_or_raise(run_id_1, db, current_user)
    await _get_run_or_raise(run_id_2, db, current_user)

    return await compare_runs(db, run_id_1=run_id_1, run_id_2=run_id_2)


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
# Temporal comparison (IP2-033)
# ---------------------------------------------------------------------------


@router.get("/{run_id}/temporal-comparison")
async def temporal_comparison(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    period: str = Query(
        default="week",
        description="Time period for comparison: 'week' or 'month'.",
    ),
    date_from: Optional[datetime] = Query(
        default=None,
        description="Optional start of current period (ISO 8601).",
    ),
    date_to: Optional[datetime] = Query(
        default=None,
        description="Optional end of current period (ISO 8601).",
    ),
) -> dict[str, Any]:
    """Period-over-period volume comparison (current vs previous period).

    Computes volume for the current period and the immediately preceding
    period of equal length, returning delta and percentage change metrics.
    Includes per-arena breakdown.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        period: Time period — ``"week"`` (default) or ``"month"``.
        date_from: Optional start of the current period. If not provided,
            uses the latest record date as the end of the current period.
        date_to: Optional end of the current period.

    Returns:
        Dict with ``current_period``, ``previous_period``, ``delta``,
        ``pct_change``, and ``per_arena`` breakdown.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
        HTTPException 422: If ``period`` is invalid.
    """
    await _get_run_or_raise(run_id, db, current_user)
    try:
        return await get_temporal_comparison(
            db,
            run_id=run_id,
            period=period,
            date_from=date_from,
            date_to=date_to,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


# ---------------------------------------------------------------------------
# Arena comparison (IP2-037)
# ---------------------------------------------------------------------------


@router.get("/{run_id}/arena-comparison")
async def arena_comparison(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Side-by-side arena metrics for a collection run.

    Returns per-arena breakdown with record count, unique actors, unique
    search terms matched, average engagement score, and date range.
    Includes an aggregate totals row.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        Dict with ``by_arena`` list and ``totals`` aggregate::

            {
              "by_arena": [
                {
                  "arena": "news_media",
                  "record_count": 1234,
                  "unique_actors": 87,
                  "unique_terms": 23,
                  "avg_engagement": 42.5,
                  "earliest_record": "2026-02-01T00:00:00+00:00",
                  "latest_record": "2026-02-17T23:59:59+00:00",
                },
                ...
              ],
              "totals": {...},
            }

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    await _get_run_or_raise(run_id, db, current_user)
    return await get_arena_comparison(db, run_id=run_id)


# ---------------------------------------------------------------------------
# Network — actor co-occurrence
# ---------------------------------------------------------------------------


@router.get("/{run_id}/network/actors")
async def network_actors(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    platform: Optional[str] = Query(default=None, description="Filter by platform."),
    arena: Optional[str] = Query(default=None, description="Filter to a specific arena."),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    min_co_occurrences: int = Query(default=2, ge=1, description="Minimum edge weight."),
) -> dict[str, Any]:
    """Return the actor co-occurrence graph for the given collection run.

    Two actors co-occur when their posts share at least one search term.
    The edge weight is the number of distinct content record pairs.

    Pass ``arena`` to restrict both sides of the co-occurrence join to a single
    arena, enabling per-arena GEXF export for cross-arena comparison.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        platform: Optional platform filter applied to both sides of the join.
        arena: Optional arena filter applied to both sides of the join.
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
        arena=arena,
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
    arena: Optional[str] = Query(default=None, description="Filter to a specific arena."),
    min_co_occurrences: int = Query(default=2, ge=1, description="Minimum shared records."),
) -> dict[str, Any]:
    """Return the term co-occurrence graph for the given collection run.

    Two terms co-occur when they appear together in the same content record's
    ``search_terms_matched`` array.

    Pass ``arena`` to restrict co-occurrence computation to records from a
    single arena, enabling per-arena GEXF export for cross-arena comparison.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        arena: Optional arena filter.
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
        arena=arena,
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
    arena: Optional[str] = Query(default=None, description="Filter to a specific arena."),
    limit: int = Query(default=500, ge=1, le=2000, description="Max edges to return."),
) -> dict[str, Any]:
    """Return the bipartite actor-term graph for the given collection run.

    Each unique ``(pseudonymized_author_id, term)`` pair becomes an edge.
    The edge weight is the number of content records where that author matched
    that term.

    Pass ``arena`` to restrict the graph to records from a single arena,
    enabling per-arena GEXF export for cross-arena comparison.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        arena: Optional arena filter.
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
        arena=arena,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Emergent terms (IP2-038)
# ---------------------------------------------------------------------------


@router.get("/{run_id}/emergent-terms")
async def emergent_terms(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    top_n: int = Query(default=50, ge=5, le=200, description="Number of top terms to return."),
    exclude_search_terms: bool = Query(
        default=True,
        description="Exclude terms already present as query design search terms.",
    ),
    min_doc_frequency: int = Query(
        default=2, ge=1, description="Minimum document frequency to include a term."
    ),
) -> list[dict[str, Any]]:
    """Extract frequently-occurring terms from text content using TF-IDF.

    Uses scikit-learn's TfidfVectorizer with Danish tokenization.  Returns the
    top-N terms ordered by mean TF-IDF score, optionally excluding existing
    search terms so that the results surface genuinely novel vocabulary.

    Requires scikit-learn to be installed.  Returns an empty list when fewer
    than 5 text records are available or the vocabulary is empty.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        top_n: Number of top terms to return (5–200, default 50).
        exclude_search_terms: Whether to exclude terms from the query design's
            search term list (default True).
        min_doc_frequency: Minimum document frequency threshold (default 2).

    Returns:
        List of dicts ``{"term": str, "score": float, "document_frequency": int}``
        ordered by TF-IDF score descending.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    run = await _get_run_or_raise(run_id, db, current_user)
    query_design_id: uuid.UUID | None = getattr(run, "query_design_id", None)
    return await get_emergent_terms(
        db,
        query_design_id=query_design_id,
        run_id=run_id,
        top_n=top_n,
        exclude_search_terms=exclude_search_terms,
        min_doc_frequency=min_doc_frequency,
    )


# ---------------------------------------------------------------------------
# Top actors unified (IP2-039)
# ---------------------------------------------------------------------------


@router.get("/{run_id}/actors-unified")
async def top_actors_unified(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200, description="Maximum actors to return."),
) -> list[dict[str, Any]]:
    """Return top authors by post volume, grouped by canonical Actor identity.

    Unlike ``/actors`` which groups by ``(pseudonymized_author_id, platform)``,
    this endpoint groups by the resolved ``author_id`` FK so that the same
    real-world actor appearing across multiple platforms is counted once.

    Only records where entity resolution has been performed (``author_id`` is
    non-null) are considered.  Returns an empty list when no resolved actors
    exist.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        date_from: Optional lower bound on ``published_at``.
        date_to: Optional upper bound on ``published_at``.
        limit: Maximum number of actors to return (1–200, default 20).

    Returns:
        List of dicts with ``actor_id``, ``canonical_name``, ``platforms``,
        ``count``, and ``total_engagement``, ordered by post count descending.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    run = await _get_run_or_raise(run_id, db, current_user)
    query_design_id: uuid.UUID | None = getattr(run, "query_design_id", None)
    return await get_top_actors_unified(
        db,
        query_design_id=query_design_id,
        run_id=run_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Temporal network snapshots (IP2-044)
# ---------------------------------------------------------------------------


@router.get("/{run_id}/network/temporal")
async def network_temporal(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    interval: str = Query(
        default="week",
        description="Time bucket size: 'day', 'week', or 'month'.",
    ),
    network_type: str = Query(
        default="actor",
        description="Network type: 'actor' or 'term'.",
    ),
    limit_per_snapshot: int = Query(
        default=100,
        ge=10,
        le=500,
        description="Maximum edges per snapshot.",
    ),
) -> list[dict[str, Any]]:
    """Return a time-series of network snapshots for the given collection run.

    Each snapshot covers one time bucket (day/week/month) and contains a graph
    dict representing the network built from records in that bucket only.
    Intervals are auto-upgraded (day→week→month) when the date range would
    produce more than 52 buckets.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        interval: Time bucket size — one of ``"day"``, ``"week"``,
            ``"month"`` (default ``"week"``).
        network_type: Network to compute — ``"actor"`` for actor co-occurrence
            or ``"term"`` for term co-occurrence (default ``"actor"``).
        limit_per_snapshot: Maximum number of edges per snapshot (10–500,
            default 100).

    Returns:
        List of dicts ``{"period": str, "node_count": int, "edge_count": int,
        "graph": {...}}`` ordered by period ascending.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
        HTTPException 422: If ``interval`` or ``network_type`` is invalid.
    """
    await _get_run_or_raise(run_id, db, current_user)
    try:
        return await get_temporal_network_snapshots(
            db,
            run_id=run_id,
            interval=interval,
            network_type=network_type,
            limit_per_snapshot=limit_per_snapshot,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


# ---------------------------------------------------------------------------
# Enhanced bipartite network (IP2-040)
# ---------------------------------------------------------------------------


@router.get("/{run_id}/network/enhanced-bipartite")
async def network_enhanced_bipartite(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: int = Query(
        default=500, ge=1, le=2000, description="Max edges in the base bipartite graph."
    ),
    top_emergent: int = Query(
        default=30,
        ge=5,
        le=100,
        description="Number of emergent terms to add (from TF-IDF extraction).",
    ),
) -> dict[str, Any]:
    """Return an enhanced bipartite actor-term graph with emergent topic nodes.

    Combines the standard bipartite graph (actors linked to search terms they
    matched) with additional term nodes discovered via TF-IDF extraction.
    Term nodes carry a ``term_type`` attribute:

    - ``"search_term"`` — came from the ``search_terms_matched`` array.
    - ``"emergent_term"`` — discovered via TF-IDF extraction.

    Requires scikit-learn for emergent term extraction.  Falls back to the
    plain bipartite graph (all terms as ``"search_term"``) when scikit-learn
    is unavailable or no text records exist.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        limit: Maximum number of edges in the base bipartite graph
            (default 500, max 2000).
        top_emergent: Number of emergent terms to extract and add as term nodes
            (5–100, default 30).

    Returns:
        Graph dict ``{"nodes": [...], "edges": [...]}`` with term nodes
        carrying a ``"term_type"`` attribute.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    run = await _get_run_or_raise(run_id, db, current_user)
    query_design_id: uuid.UUID | None = getattr(run, "query_design_id", None)

    # Extract emergent terms first (returns [] gracefully if sklearn unavailable).
    emergent = await get_emergent_terms(
        db,
        query_design_id=query_design_id,
        run_id=run_id,
        top_n=top_emergent,
        exclude_search_terms=True,
    )

    return await build_enhanced_bipartite_network(
        db,
        emergent_terms=emergent,
        query_design_id=query_design_id,
        run_id=run_id,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Temporal network snapshots — type-path aliases (IP2-044 frontend alignment)
# Frontend expects /network/{type}/temporal and /network/{type}/temporal/{period}
# ---------------------------------------------------------------------------


@router.get("/{run_id}/network/{network_type}/temporal")
async def network_temporal_by_type(
    run_id: uuid.UUID,
    network_type: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    interval: str = Query(default="week", description="Time bucket: day, week, month."),
    limit_per_snapshot: int = Query(default=100, ge=10, le=500),
) -> list[dict[str, Any]]:
    """Temporal network snapshots — path alias with network_type in URL.

    Delegates to :func:`network_temporal` with ``network_type`` extracted from
    the URL path instead of a query parameter.  This matches the URL convention
    used by the analysis dashboard frontend.

    Args:
        run_id: UUID of the collection run.
        network_type: One of ``"actor"``, ``"term"``, or ``"bipartite"``.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        interval: Time bucket size (default ``"week"``).
        limit_per_snapshot: Maximum edges per snapshot (default 100).

    Returns:
        List of ``{"period", "node_count", "edge_count", "graph"}`` dicts
        ordered by period ascending.  Omits the ``"graph"`` key for the index
        listing so callers can request individual period graphs separately.
    """
    await _get_run_or_raise(run_id, db, current_user)
    try:
        snapshots = await get_temporal_network_snapshots(
            db,
            run_id=run_id,
            interval=interval,
            network_type=network_type,
            limit_per_snapshot=limit_per_snapshot,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    # Return index without full graph payloads (frontend fetches per-period below).
    return [
        {"period": s["period"], "node_count": s["node_count"], "edge_count": s["edge_count"]}
        for s in snapshots
    ]


@router.get("/{run_id}/network/{network_type}/temporal/{period}")
async def network_temporal_period(
    run_id: uuid.UUID,
    network_type: str,
    period: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    interval: str = Query(default="week", description="Time bucket: day, week, month."),
    limit_per_snapshot: int = Query(default=200, ge=10, le=500),
) -> dict[str, Any]:
    """Return the network graph for a single temporal period.

    The *period* path parameter must match one of the ISO 8601 period strings
    returned by the temporal index endpoint (e.g. ``"2026-02-01T00:00:00"``).
    URL-encoding is applied by the browser automatically.

    Args:
        run_id: UUID of the collection run.
        network_type: One of ``"actor"``, ``"term"``.
        period: ISO 8601 period string matching a snapshot period key.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        interval: Must match the interval used for the index request.
        limit_per_snapshot: Maximum edges in the returned snapshot.

    Returns:
        Graph dict ``{"nodes": [...], "edges": [...]}`` for the requested period.

    Raises:
        HTTPException 404: If the period is not found in the temporal index.
    """
    await _get_run_or_raise(run_id, db, current_user)
    try:
        snapshots = await get_temporal_network_snapshots(
            db,
            run_id=run_id,
            interval=interval,
            network_type=network_type,
            limit_per_snapshot=limit_per_snapshot,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    # Find the requested period — match on ISO string prefix to tolerate TZ variants.
    for snapshot in snapshots:
        snap_period = str(snapshot.get("period", ""))
        if snap_period.startswith(period) or period.startswith(snap_period):
            return snapshot.get("graph", {"nodes": [], "edges": []})

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Period '{period}' not found in temporal snapshots for this run.",
    )


# ---------------------------------------------------------------------------
# Temporal GEXF export (1.3)
# ---------------------------------------------------------------------------


@router.get("/{run_id}/network/temporal/export-gexf")
async def export_temporal_network_gexf(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    interval: str = Query(default="week", description="Time bucket: day, week, month."),
    network_type: str = Query(default="actor", description="Network type: actor or term."),
    limit_per_snapshot: int = Query(default=100, ge=10, le=500),
) -> Response:
    """Export temporal network snapshots as dynamic GEXF file for Gephi Timeline.

    Creates a GEXF 1.3 document with ``mode="dynamic"`` and ``<spells>``
    elements on nodes and edges. Suitable for import into Gephi's Timeline
    visualization plugin.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        interval: Time bucket size (default "week").
        network_type: Network to compute — "actor" or "term" (default "actor").
        limit_per_snapshot: Maximum edges per snapshot (default 100).

    Returns:
        A Response with GEXF XML bytes and Content-Disposition header for download.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
        HTTPException 422: If interval or network_type is invalid.
    """
    await _get_run_or_raise(run_id, db, current_user)

    try:
        snapshots = await get_temporal_network_snapshots(
            db,
            run_id=run_id,
            interval=interval,
            network_type=network_type,
            limit_per_snapshot=limit_per_snapshot,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    exporter = ContentExporter()
    gexf_bytes = await exporter.export_temporal_gexf(snapshots)

    filename = f"run_{run_id}_temporal_{network_type}_{interval}.gexf"

    logger.info(
        "analysis.export_temporal_gexf",
        run_id=str(run_id),
        network_type=network_type,
        interval=interval,
        snapshot_count=len(snapshots),
    )

    return Response(
        content=gexf_bytes,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Filter options — distinct platforms and arenas for a run
# ---------------------------------------------------------------------------


@router.get("/{run_id}/filter-options")
async def get_filter_options(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, list[str]]:
    """Return distinct platform and arena values for the given collection run.

    Called by the analysis dashboard to populate the platform and arena filter
    dropdowns before any chart is rendered.  Returns empty lists rather than
    HTTP 404 when the run does not exist, so the UI degrades gracefully.

    Ownership scoping is enforced: non-admin users can only query runs they
    initiated.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        ``{"platforms": [...], "arenas": [...]}`` with sorted, deduplicated
        string lists.  Either list may be empty when no content has been
        collected yet.
    """
    # Verify ownership; return empty lists if the run is not found rather than
    # propagating 404 — the analysis dashboard renders gracefully without data.
    try:
        await _get_run_or_raise(run_id, db, current_user)
    except Exception:  # noqa: BLE001
        return {"platforms": [], "arenas": []}

    platform_stmt = (
        select(distinct(UniversalContentRecord.platform))
        .where(UniversalContentRecord.collection_run_id == run_id)
        .order_by(UniversalContentRecord.platform)
    )
    arena_stmt = (
        select(distinct(UniversalContentRecord.arena))
        .where(UniversalContentRecord.collection_run_id == run_id)
        .order_by(UniversalContentRecord.arena)
    )

    platform_result = await db.execute(platform_stmt)
    arena_result = await db.execute(arena_stmt)

    platforms: list[str] = [row[0] for row in platform_result.fetchall() if row[0]]
    arenas: list[str] = [row[0] for row in arena_result.fetchall() if row[0]]

    logger.info(
        "analysis.filter_options",
        run_id=str(run_id),
        platform_count=len(platforms),
        arena_count=len(arenas),
    )

    return {"platforms": platforms, "arenas": arenas}


# ---------------------------------------------------------------------------
# Filtered export (IP2-055)
# ---------------------------------------------------------------------------

_EXPORT_CONTENT_TYPES: dict[str, str] = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ndjson": "application/x-ndjson",
    "parquet": "application/octet-stream",
    "ris": "application/x-research-info-systems",
    "bibtex": "application/x-bibtex",
}

_EXPORT_EXTENSIONS: dict[str, str] = {
    "csv": "csv",
    "xlsx": "xlsx",
    "ndjson": "ndjson",
    "parquet": "parquet",
    "ris": "ris",
    "bibtex": "bib",
}


def _record_to_dict(r: UniversalContentRecord) -> dict[str, Any]:
    """Convert an ORM row to a plain dict suitable for export functions.

    Args:
        r: A ``UniversalContentRecord`` ORM instance.

    Returns:
        A dict with all scalar columns serialized.  UUID and datetime values
        are kept as Python objects so that the exporters can format them.
    """
    return {
        "id": str(r.id) if r.id else None,
        "platform": r.platform,
        "arena": r.arena,
        "platform_id": r.platform_id,
        "content_type": r.content_type,
        "url": r.url,
        "text_content": r.text_content,
        "title": r.title,
        "language": r.language,
        "published_at": r.published_at,
        "collected_at": r.collected_at,
        "author_platform_id": r.author_platform_id,
        "author_display_name": r.author_display_name,
        "author_id": str(r.author_id) if r.author_id else None,
        "pseudonymized_author_id": r.pseudonymized_author_id,
        "views_count": r.views_count,
        "likes_count": r.likes_count,
        "shares_count": r.shares_count,
        "comments_count": r.comments_count,
        "engagement_score": r.engagement_score,
        "collection_run_id": str(r.collection_run_id) if r.collection_run_id else None,
        "query_design_id": str(r.query_design_id) if r.query_design_id else None,
        "search_terms_matched": r.search_terms_matched or [],
        "collection_tier": r.collection_tier,
        "raw_metadata": r.raw_metadata or {},
        "media_urls": r.media_urls or [],
        "content_hash": r.content_hash,
    }


@router.get("/{run_id}/filtered-export")
async def filtered_export(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    format: str = Query(
        default="csv",
        description=(
            "Export format: csv, xlsx, ndjson, parquet, ris, bibtex."
        ),
    ),
    platform: Optional[str] = Query(default=None, description="Filter by platform name."),
    arena: Optional[str] = Query(default=None, description="Filter by arena name."),
    date_from: Optional[datetime] = Query(
        default=None, description="Inclusive lower bound on published_at (ISO 8601)."
    ),
    date_to: Optional[datetime] = Query(
        default=None, description="Inclusive upper bound on published_at (ISO 8601)."
    ),
    search_term: Optional[str] = Query(
        default=None,
        description="Only include records matching this search term in search_terms_matched.",
    ),
    top_actors: Optional[str] = Query(
        default=None,
        description="Comma-separated list of author_display_name values to filter by.",
    ),
    min_engagement: Optional[float] = Query(
        default=None, description="Minimum engagement_score to include."
    ),
    limit: int = Query(
        default=10_000,
        ge=1,
        le=10_000,
        description="Maximum number of records to export (hard cap: 10 000).",
    ),
) -> Response:
    """Export filtered content records from a collection run as a file download.

    Applies the specified filters to the ``content_records`` table, scoped to
    the given collection run.  The result is returned synchronously as a file
    with the appropriate ``Content-Disposition: attachment`` header.

    Supported formats: ``csv``, ``xlsx``, ``ndjson``, ``parquet``, ``ris``,
    ``bibtex``.  Use ``GET /content/export/async`` for datasets larger than
    10 000 records.

    Args:
        run_id: UUID of the collection run to export from.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        format: Output format — one of csv, xlsx, ndjson, parquet, ris, bibtex.
        platform: Optional platform name filter.
        arena: Optional arena name filter.
        date_from: Optional lower bound on ``published_at``.
        date_to: Optional upper bound on ``published_at``.
        search_term: Optional term that must appear in ``search_terms_matched``.
        top_actors: Optional comma-separated list of ``author_display_name``
            values to restrict the export to.
        min_engagement: Optional minimum ``engagement_score``.
        limit: Maximum records to include (1–10 000; default 10 000).

    Returns:
        A ``Response`` with the file bytes and a ``Content-Disposition:
        attachment`` header.

    Raises:
        HTTPException 400: If the requested format is not supported.
        HTTPException 403: If the current user does not own the run.
        HTTPException 404: If the run does not exist.
    """
    run = await _get_run_or_raise(run_id, db, current_user)

    if format not in _EXPORT_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported export format {format!r}. "
                f"Choose from: {', '.join(_EXPORT_CONTENT_TYPES)}."
            ),
        )

    # Build query with ownership scope (run already verified) and all filters.
    stmt = (
        select(UniversalContentRecord)
        .where(UniversalContentRecord.collection_run_id == run_id)
        .order_by(UniversalContentRecord.collected_at.desc())
        .limit(limit)
    )

    if platform:
        stmt = stmt.where(UniversalContentRecord.platform == platform)
    if arena:
        stmt = stmt.where(UniversalContentRecord.arena == arena)
    if date_from:
        stmt = stmt.where(UniversalContentRecord.published_at >= date_from)
    if date_to:
        stmt = stmt.where(UniversalContentRecord.published_at <= date_to)
    if search_term:
        # Use PostgreSQL array containment (@>) to match exact term in the array.
        stmt = stmt.where(
            UniversalContentRecord.search_terms_matched.contains([search_term])
        )
    if min_engagement is not None:
        stmt = stmt.where(
            UniversalContentRecord.engagement_score >= min_engagement
        )
    if top_actors:
        actor_names = [a.strip() for a in top_actors.split(",") if a.strip()]
        if actor_names:
            stmt = stmt.where(
                UniversalContentRecord.author_display_name.in_(actor_names)
            )

    db_result = await db.execute(stmt)
    orm_rows = list(db_result.scalars().all())
    records = [_record_to_dict(r) for r in orm_rows]

    exporter = ContentExporter()

    try:
        if format == "csv":
            file_bytes = await exporter.export_csv(records)
        elif format == "xlsx":
            file_bytes = await exporter.export_xlsx(records)
        elif format == "ndjson":
            file_bytes = await exporter.export_json(records)
        elif format == "parquet":
            file_bytes = await exporter.export_parquet(records)
        elif format == "ris":
            file_bytes = exporter.export_ris(records)
        else:  # bibtex
            file_bytes = exporter.export_bibtex(records)
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    ext = _EXPORT_EXTENSIONS[format]
    filename = f"run_{run_id}_{format}_export.{ext}"
    content_type = _EXPORT_CONTENT_TYPES[format]

    logger.info(
        "analysis.filtered_export",
        run_id=str(run_id),
        user_id=str(current_user.id),
        format=format,
        record_count=len(records),
    )

    return Response(
        content=file_bytes,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Suggested terms (IP2-053)
# ---------------------------------------------------------------------------


@router.get("/{run_id}/suggested-terms")
async def suggested_terms(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    top_n: int = Query(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of suggested terms to return.",
    ),
    min_doc_frequency: int = Query(
        default=2,
        ge=1,
        description="Minimum document frequency for a term to be suggested.",
    ),
) -> list[dict[str, Any]]:
    """Return emergent terms from collected data that are not already in the query design.

    Calls ``get_emergent_terms()`` with TF-IDF extraction scoped to the given
    run, then fetches the existing search terms from the associated query design
    and removes any overlap, so only genuinely novel vocabulary is returned.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        top_n: Maximum number of suggestions to return (1–50, default 10).
        min_doc_frequency: Minimum document frequency for a suggested term
            (default 2).

    Returns:
        List of dicts ``{"term": str, "score": float, "document_frequency": int}``
        ordered by TF-IDF score descending, excluding terms already present in
        the query design.

    Raises:
        HTTPException 403: If the current user does not own the run.
        HTTPException 404: If the run does not exist.
    """
    run = await _get_run_or_raise(run_id, db, current_user)
    query_design_id: uuid.UUID | None = getattr(run, "query_design_id", None)

    # Fetch all emergent terms (more than top_n so we can filter after exclusion).
    all_emergent = await get_emergent_terms(
        db,
        query_design_id=query_design_id,
        run_id=run_id,
        top_n=top_n * 4,  # over-fetch to survive exclusion filtering
        exclude_search_terms=True,
        min_doc_frequency=min_doc_frequency,
    )

    # Build a set of existing search term strings for this query design.
    existing_terms: set[str] = set()
    if query_design_id is not None:
        term_stmt = select(SearchTerm.term).where(
            SearchTerm.query_design_id == query_design_id,
            SearchTerm.is_active.is_(True),
        )
        term_result = await db.execute(term_stmt)
        existing_terms = {row[0].lower() for row in term_result.fetchall()}

    # Exclude terms already in the query design (case-insensitive).
    suggestions = [
        item
        for item in all_emergent
        if item["term"].lower() not in existing_terms
    ][:top_n]

    logger.info(
        "analysis.suggested_terms",
        run_id=str(run_id),
        query_design_id=str(query_design_id) if query_design_id else None,
        existing_count=len(existing_terms),
        suggestion_count=len(suggestions),
    )

    return suggestions


# ---------------------------------------------------------------------------
# YF-06: Cross-Run Analysis — Query Design Level
# ---------------------------------------------------------------------------


async def _get_design_or_raise(
    design_id: uuid.UUID,
    db: AsyncSession,
    current_user: User,
) -> QueryDesign:
    """Fetch a QueryDesign and verify the caller's ownership.

    Args:
        design_id: UUID of the query design.
        db: Active async database session.
        current_user: The authenticated user making the request.

    Returns:
        The ``QueryDesign`` ORM instance.

    Raises:
        HTTPException 404: If the design does not exist.
        HTTPException 403: If the current user is not the owner and not an admin.
    """
    stmt = select(QueryDesign).where(QueryDesign.id == design_id)
    result = await db.execute(stmt)
    design = result.scalar_one_or_none()

    if design is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query design '{design_id}' not found.",
        )

    ownership_guard(design.owner_id, current_user)
    return design


@router.get("/design/{design_id}", include_in_schema=False)
async def analysis_dashboard_design(
    design_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Any:
    """Render the analysis dashboard HTML page for all runs in a query design.

    Aggregates data across all collection runs belonging to the specified query
    design, enabling researchers to analyze their full corpus for a topic.

    Args:
        design_id: UUID of the query design to analyse.
        request: The incoming HTTP request (required by Jinja2 TemplateResponse).
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        A Jinja2 ``TemplateResponse`` rendering ``analysis/design.html``.

    Raises:
        HTTPException 404: If the query design does not exist.
        HTTPException 403: If the current user does not own the design.
    """
    design = await _get_design_or_raise(design_id, db, current_user)

    templates = request.app.state.templates
    if templates is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Template engine not initialised.",
        )

    # Fetch all completed runs for this design to show context.
    runs_stmt = (
        select(CollectionRun)
        .where(
            CollectionRun.query_design_id == design_id,
            CollectionRun.status == "completed",
        )
        .order_by(CollectionRun.started_at.desc())
    )
    runs_result = await db.execute(runs_stmt)
    runs = runs_result.scalars().all()

    return templates.TemplateResponse(
        "analysis/design.html",
        {
            "request": request,
            "design_id": str(design_id),
            "design": {
                "id": str(design.id),
                "name": design.name,
                "description": design.description,
            },
            "run_count": len(runs),
            "runs": [
                {
                    "id": str(r.id),
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "records_collected": r.records_collected,
                }
                for r in runs
            ],
        },
    )


@router.get("/design/{design_id}/summary")
async def design_summary(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Return aggregated statistics across all runs in a query design.

    Args:
        design_id: UUID of the query design.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        Dict with design metadata and aggregated run statistics.

    Raises:
        HTTPException 404: If the query design does not exist.
        HTTPException 403: If the current user does not own the design.
    """
    await _get_design_or_raise(design_id, db, current_user)

    # Aggregate across all runs for this design.
    sql = text(
        """
        SELECT
            COUNT(DISTINCT cr.id)                     AS total_runs,
            COUNT(DISTINCT cr.id) FILTER (
                WHERE cr.status = 'completed'
            )                                         AS completed_runs,
            COALESCE(SUM(cr.credits_spent), 0)       AS total_credits,
            COALESCE(SUM(cr.records_collected), 0)   AS total_records,
            MIN(cr.started_at)                       AS first_run_at,
            MAX(cr.completed_at)                     AS last_completed_at
        FROM collection_runs cr
        WHERE cr.query_design_id = :design_id
        """
    )
    result = await db.execute(sql, {"design_id": str(design_id)})
    row = result.fetchone()

    if row is None:
        return {
            "design_id": str(design_id),
            "total_runs": 0,
            "completed_runs": 0,
            "total_credits": 0,
            "total_records": 0,
            "first_run_at": None,
            "last_completed_at": None,
        }

    return {
        "design_id": str(design_id),
        "total_runs": row.total_runs,
        "completed_runs": row.completed_runs,
        "total_credits": int(row.total_credits or 0),
        "total_records": int(row.total_records or 0),
        "first_run_at": row.first_run_at.isoformat() if row.first_run_at else None,
        "last_completed_at": row.last_completed_at.isoformat() if row.last_completed_at else None,
    }


@router.get("/design/{design_id}/volume")
async def design_volume_over_time(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    platform: Optional[str] = Query(default=None, description="Filter by platform."),
    arena: Optional[str] = Query(default=None, description="Filter by arena."),
    date_from: Optional[datetime] = Query(default=None, description="Lower bound on published_at."),
    date_to: Optional[datetime] = Query(default=None, description="Upper bound on published_at."),
    granularity: str = Query(default="day", description="Time bucket: hour, day, week, month."),
) -> list[dict[str, Any]]:
    """Return content volume over time across all runs in a query design.

    Args:
        design_id: UUID of the query design.
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
        HTTPException 404: If the query design does not exist.
        HTTPException 403: If the current user does not own the design.
        HTTPException 422: If ``granularity`` is invalid.
    """
    await _get_design_or_raise(design_id, db, current_user)
    try:
        return await get_volume_over_time(
            db,
            query_design_id=design_id,
            run_id=None,
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


@router.get("/design/{design_id}/actors")
async def design_top_actors(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    platform: Optional[str] = Query(default=None, description="Filter by platform."),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200, description="Maximum actors to return."),
) -> list[dict[str, Any]]:
    """Return top authors by post volume across all runs in a query design.

    Args:
        design_id: UUID of the query design.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        platform: Optional platform filter.
        date_from: Optional lower bound on ``published_at``.
        date_to: Optional upper bound on ``published_at``.
        limit: Maximum number of actors to return (1–200, default 20).

    Returns:
        List of dicts ordered by post count descending.

    Raises:
        HTTPException 404: If the query design does not exist.
        HTTPException 403: If the current user does not own the design.
    """
    await _get_design_or_raise(design_id, db, current_user)
    return await get_top_actors(
        db,
        query_design_id=design_id,
        run_id=None,
        platform=platform,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )


@router.get("/design/{design_id}/terms")
async def design_top_terms(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200, description="Maximum terms to return."),
) -> list[dict[str, Any]]:
    """Return top search terms by match frequency across all runs in a query design.

    Args:
        design_id: UUID of the query design.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        date_from: Optional lower bound on ``published_at``.
        date_to: Optional upper bound on ``published_at``.
        limit: Maximum number of terms to return (1–200, default 20).

    Returns:
        List of dicts with ``term`` and ``count``, ordered by count descending.

    Raises:
        HTTPException 404: If the query design does not exist.
        HTTPException 403: If the current user does not own the design.
    """
    await _get_design_or_raise(design_id, db, current_user)
    return await get_top_terms(
        db,
        query_design_id=design_id,
        run_id=None,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )


@router.get("/design/{design_id}/network/actors")
async def design_network_actors(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    platform: Optional[str] = Query(default=None, description="Filter by platform."),
    arena: Optional[str] = Query(default=None, description="Filter to a specific arena."),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    min_co_occurrences: int = Query(default=2, ge=1, description="Minimum edge weight."),
) -> dict[str, Any]:
    """Return the actor co-occurrence graph across all runs in a query design.

    Args:
        design_id: UUID of the query design.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        platform: Optional platform filter applied to both sides of the join.
        arena: Optional arena filter applied to both sides of the join.
        date_from: Optional lower bound on ``published_at``.
        date_to: Optional upper bound on ``published_at``.
        min_co_occurrences: Minimum edge weight to include (default 2).

    Returns:
        Graph dict ``{nodes: [...], edges: [...]}``.

    Raises:
        HTTPException 404: If the query design does not exist.
        HTTPException 403: If the current user does not own the design.
    """
    await _get_design_or_raise(design_id, db, current_user)
    return await get_actor_co_occurrence(
        db,
        query_design_id=design_id,
        run_id=None,
        platform=platform,
        arena=arena,
        date_from=date_from,
        date_to=date_to,
        min_co_occurrences=min_co_occurrences,
    )


@router.get("/design/{design_id}/network/terms")
async def design_network_terms(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    arena: Optional[str] = Query(default=None, description="Filter to a specific arena."),
    min_co_occurrences: int = Query(default=2, ge=1, description="Minimum shared records."),
) -> dict[str, Any]:
    """Return the term co-occurrence graph across all runs in a query design.

    Args:
        design_id: UUID of the query design.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        arena: Optional arena filter.
        min_co_occurrences: Minimum number of shared records (default 2).

    Returns:
        Graph dict ``{nodes: [...], edges: [...]}``.

    Raises:
        HTTPException 404: If the query design does not exist.
        HTTPException 403: If the current user does not own the design.
    """
    await _get_design_or_raise(design_id, db, current_user)
    return await get_term_co_occurrence(
        db,
        query_design_id=design_id,
        run_id=None,
        arena=arena,
        min_co_occurrences=min_co_occurrences,
    )


@router.get("/design/{design_id}/network/bipartite")
async def design_network_bipartite(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    arena: Optional[str] = Query(default=None, description="Filter to a specific arena."),
    limit: int = Query(default=500, ge=1, le=2000, description="Max edges to return."),
) -> dict[str, Any]:
    """Return the bipartite actor-term graph across all runs in a query design.

    Args:
        design_id: UUID of the query design.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        arena: Optional arena filter.
        limit: Maximum number of edges to return (default 500, max 2000).

    Returns:
        Graph dict ``{nodes: [...], edges: [...]}`` with typed nodes.

    Raises:
        HTTPException 404: If the query design does not exist.
        HTTPException 403: If the current user does not own the design.
    """
    await _get_design_or_raise(design_id, db, current_user)
    return await build_bipartite_network(
        db,
        query_design_id=design_id,
        run_id=None,
        arena=arena,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# SB-15: Enrichment Results Dashboard (P3)
# ---------------------------------------------------------------------------


@router.get("/{run_id}/enrichments/languages")
async def enrichment_languages(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[dict[str, Any]]:
    """Return language distribution from language detection enrichment results.

    Queries the ``language_detector`` enrichment data in
    ``raw_metadata.enrichments`` and aggregates by detected language code.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        List of dicts ordered by count descending::

            [
              {"language": "da", "count": 523, "percentage": 68.5},
              {"language": "en", "count": 142, "percentage": 18.6},
              ...
            ]

        Returns an empty list when no language enrichment data exists.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    await _get_run_or_raise(run_id, db, current_user)
    return await get_language_distribution(db, run_id=run_id)


@router.get("/{run_id}/enrichments/entities")
async def enrichment_entities(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    limit: int = Query(default=20, ge=1, le=100, description="Maximum entities to return."),
) -> list[dict[str, Any]]:
    """Return most frequent named entities from NER enrichment results.

    Queries the ``named_entity_extractor`` enrichment data and returns the
    top-N most frequently mentioned entities.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        limit: Maximum number of entities to return (1–100, default 20).

    Returns:
        List of dicts ordered by count descending::

            [
              {"entity": "Danmark", "count": 142, "types": ["GPE", "LOC"]},
              {"entity": "København", "count": 87, "types": ["GPE"]},
              ...
            ]

        Returns an empty list when no NER enrichment data exists.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    await _get_run_or_raise(run_id, db, current_user)
    return await get_top_named_entities(db, run_id=run_id, limit=limit)


@router.get("/{run_id}/enrichments/propagation")
async def enrichment_propagation(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[dict[str, Any]]:
    """Return cross-arena propagation patterns from enrichment results.

    Queries the ``propagation_detector`` enrichment data and returns stories
    that propagated across 2 or more arenas.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        List of dicts ordered by story size descending::

            [
              {
                "story_id": "abc123...",
                "arenas": ["news_media", "social_media"],
                "platforms": ["rss_feeds", "reddit", "bluesky"],
                "record_count": 24,
                "first_seen": "2026-02-10T08:30:00+00:00",
                "last_seen": "2026-02-15T14:22:00+00:00",
              },
              ...
            ]

        Returns an empty list when no propagation enrichment data exists.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    await _get_run_or_raise(run_id, db, current_user)
    return await get_propagation_patterns(db, run_id=run_id)


# ---------------------------------------------------------------------------
# Propagation flows query (1.2)
# ---------------------------------------------------------------------------


@router.get("/{run_id}/propagation/flows")
async def propagation_flows(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    min_arenas_reached: int = Query(default=2, ge=2, description="Minimum arenas reached."),
    limit: int = Query(default=100, ge=1, le=200, description="Maximum flows to return."),
) -> list[dict[str, Any]]:
    """Return top propagation flows sorted by number of arenas reached.

    A propagation flow is a near-duplicate cluster where content first appeared
    in one arena and subsequently spread to one or more other arenas. Returns
    the origin record for each qualifying cluster, enriched with the full
    propagation sequence.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        min_arenas_reached: Minimum number of distinct arenas required (default 2).
        limit: Maximum number of flows to return (default 100).

    Returns:
        List of dicts ordered by total_arenas_reached descending, then by
        max_lag_hours descending::

            [
              {
                "cluster_id": "...",
                "record_id": "...",
                "arena": "gdelt",
                "platform": "gdelt",
                "origin_published_at": "2026-02-19T14:00:00+00:00",
                "total_arenas_reached": 4,
                "max_lag_hours": 2.5,
                "propagation_sequence": [
                    {
                        "arena": "news",
                        "platform": "dr",
                        "published_at": "...",
                        "lag_minutes": 90.0
                    },
                    ...
                ],
                "computed_at": "2026-02-19T16:00:00+00:00"
              },
              ...
            ]

        Returns an empty list when no propagation-enriched records match the filters.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    await _get_run_or_raise(run_id, db, current_user)
    return await get_propagation_flows(
        db,
        collection_run_id=run_id,
        min_arenas_reached=min_arenas_reached,
        limit=limit,
    )


@router.get("/{run_id}/enrichments/coordination")
async def enrichment_coordination(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[dict[str, Any]]:
    """Return coordination signals from enrichment results.

    Queries the ``coordination_detector`` enrichment data and returns detected
    patterns of coordinated posting activity (burst patterns, identical content
    from multiple actors within short time windows).

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        List of dicts ordered by signal strength descending::

            [
              {
                "coordination_type": "burst",
                "actor_count": 12,
                "record_count": 87,
                "content_hash": "abc123...",
                "time_window_hours": 2.5,
                "first_post": "2026-02-14T10:00:00+00:00",
                "last_post": "2026-02-14T12:30:00+00:00",
              },
              ...
            ]

        Returns an empty list when no coordination enrichment data exists.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    await _get_run_or_raise(run_id, db, current_user)
    return await get_coordination_signals(db, run_id=run_id)


@router.get("/{run_id}/enrichments/sentiment")
async def enrichment_sentiment(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Return sentiment distribution from sentiment analysis enrichment results.

    Queries the ``sentiment_analyzer`` enrichment data and aggregates sentiment
    scores across all enriched records.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        Dict with sentiment counts and average score::

            {
              "positive": 145,
              "negative": 67,
              "neutral": 423,
              "average_score": 0.12,
              "total_records": 635
            }

        All counts default to 0 when no sentiment enrichment data exists.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    await _get_run_or_raise(run_id, db, current_user)
    return await get_sentiment_distribution(db, run_id=run_id)


# ---------------------------------------------------------------------------
# Coordination events query (1.1)
# ---------------------------------------------------------------------------


@router.get("/{run_id}/coordination/events")
async def coordination_events(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    min_score: float = Query(default=0.5, ge=0.0, le=1.0, description="Minimum coordination score."),
    limit: int = Query(default=50, ge=1, le=200, description="Maximum events to return."),
) -> list[dict[str, Any]]:
    """Return clusters flagged as potential coordination events, sorted by score.

    Queries the coordination enrichment data for records flagged as potential
    coordinated posting patterns. Returns one representative record per cluster,
    ordered by coordination_score descending.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        min_score: Minimum coordination score (0-1) to include (default 0.5).
        limit: Maximum number of distinct cluster summaries to return (default 50).

    Returns:
        List of dicts ordered by coordination_score descending::

            [
              {
                "cluster_id": "...",
                "record_id": "...",
                "flagged": true,
                "distinct_authors_in_window": 12,
                "time_window_hours": 1.0,
                "coordination_score": 0.85,
                "earliest_in_window": "2026-02-19T14:00:00+00:00",
                "latest_in_window": "2026-02-19T14:45:00+00:00",
                "platforms_involved": ["gab", "reddit", "telegram"],
                "computed_at": "2026-02-19T16:00:00+00:00"
              },
              ...
            ]

        Returns an empty list when no coordination-enriched records match the filters.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the current user does not own the run.
    """
    await _get_run_or_raise(run_id, db, current_user)
    return await get_coordination_events(
        db,
        collection_run_id=run_id,
        min_score=min_score,
        limit=limit,
    )
