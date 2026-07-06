"""Dashboard API routes.

Provides project-scoped analytics endpoints for the main dashboard page.
All endpoints require authentication and enforce ownership scoping: the
requesting user must own the referenced project.

Routes:
    GET /dashboard/projects         — list user's projects with recent run timestamps
    GET /dashboard/volume           — volume over time for a project
    GET /dashboard/actors           — top actors for a project
    GET /dashboard/terms            — top terms for a project
    GET /dashboard/filter-options   — available arena categories and platforms
    GET /dashboard/export           — data export in multiple formats
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import distinct, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.analysis.descriptive import (
    get_top_actors,
    get_top_terms,
    get_volume_with_deltas,
)
from issue_observatory.analysis.export import ContentExporter
from issue_observatory.api.dependencies import (
    get_current_active_user,
    is_project_collaborator,
    ownership_guard,
)
from issue_observatory.arenas.categories import (
    ARENA_CATEGORIES,
    ARENA_CATEGORY_LABELS,
    VALID_CATEGORIES,
)
from issue_observatory.core.database import AsyncSessionLocal, get_db
from issue_observatory.core.models.collection import CollectionRun
from issue_observatory.core.models.content import UniversalContentRecord
from issue_observatory.core.models.project import Project
from issue_observatory.core.models.query_design import QueryDesign
from issue_observatory.core.models.users import User

logger = structlog.get_logger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Export format metadata (mirrors the subset supported here)
# ---------------------------------------------------------------------------

_EXPORT_CONTENT_TYPES: dict[str, str] = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "json": "application/x-ndjson",
    "parquet": "application/octet-stream",
}

_EXPORT_EXTENSIONS: dict[str, str] = {
    "csv": "csv",
    "xlsx": "xlsx",
    "json": "ndjson",
    "parquet": "parquet",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_project_query_design_ids(
    db: AsyncSession,
    project_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Get query design IDs belonging to a project.

    Access control is handled by the caller (``_resolve_project_or_raise``),
    so this function does not filter by owner.

    Args:
        db: Active async database session.
        project_id: UUID of the project.

    Returns:
        List of query design UUIDs belonging to the project.
    """
    result = await db.execute(
        select(QueryDesign.id).where(QueryDesign.project_id == project_id)
    )
    return [row[0] for row in result.fetchall()]


async def _resolve_project_or_raise(
    db: AsyncSession,
    project_id: uuid.UUID,
    current_user: User,
) -> tuple[Project, list[uuid.UUID]]:
    """Fetch a project, verify ownership, and return all its query design IDs.

    Args:
        db: Active async database session.
        project_id: UUID of the project to resolve.
        current_user: The authenticated user making the request.

    Returns:
        A tuple of (Project instance, list of query design UUIDs).

    Raises:
        HTTPException 404: If the project does not exist.
        HTTPException 403: If the user does not own the project.
    """
    stmt = select(Project).where(Project.id == project_id)
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    # Owner/admin pass directly; collaborators pass too (dashboard is read-only)
    if current_user.role != "admin" and project.owner_id != current_user.id:
        if not await is_project_collaborator(db, project_id, current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource.",
            )

    design_ids = await _get_project_query_design_ids(db, project_id)
    return project, design_ids


async def _get_latest_published_at(
    db: AsyncSession,
    design_ids: list[uuid.UUID],
) -> datetime | None:
    """Return the most recent ``published_at`` across content for these designs.

    ``content_records`` is range-partitioned by ``published_at`` (monthly), so
    ``MAX(published_at)`` is evaluated via a reverse-scan on the newest
    partition — it does not walk the full table.
    """
    if not design_ids:
        return None
    result = await db.execute(
        select(func.max(UniversalContentRecord.published_at)).where(
            UniversalContentRecord.query_design_id.in_(design_ids)
        )
    )
    return result.scalar()


async def _get_most_recent_project_id(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> uuid.UUID | None:
    """Return the UUID of the most recently created/shared project for the user.

    Considers both owned projects and projects shared with the user.

    Args:
        db: Active async database session.
        user_id: UUID of the requesting user.

    Returns:
        UUID of the most recent project, or None if the user has no projects.
    """
    from sqlalchemy import or_

    from issue_observatory.core.models.project_collaborator import ProjectCollaborator

    collaborated_project_ids = (
        select(ProjectCollaborator.project_id)
        .where(ProjectCollaborator.user_id == user_id)
        .scalar_subquery()
    )
    stmt = (
        select(Project.id)
        .where(
            or_(
                Project.owner_id == user_id,
                Project.id.in_(collaborated_project_ids),
            )
        )
        .order_by(Project.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return row


def _record_to_dict(
    r: UniversalContentRecord,
    design_name_by_id: dict[uuid.UUID, str] | None = None,
) -> dict[str, Any]:
    """Convert a UniversalContentRecord ORM instance to a plain dict for export.

    Args:
        r: A ``UniversalContentRecord`` ORM instance.
        design_name_by_id: Optional ``{query_design_id: name}`` map used to
            resolve the human-readable query design label for the exported
            ``query_design`` column.  Falls back to the stringified UUID
            when the id is unknown and to an empty string when the record
            has no design_id.

    Returns:
        A dict with scalar field values suitable for passing to ContentExporter.
        Datetime fields are kept as Python objects so the exporters can format them.
    """
    raw_meta = r.raw_metadata or {}

    # Extract cleaned external links from URL enrichment
    url_enrichment = (raw_meta.get("enrichments") or {}).get("url_extraction") or {}
    url_entries = url_enrichment.get("urls") or []
    cleaned_links = [
        u["cleaned"] for u in url_entries
        if u.get("cleaned") and u.get("type") != "self_reference"
    ]
    links_str = "; ".join(cleaned_links) if cleaned_links else ""

    # Search rank (Google Search position)
    search_rank = raw_meta.get("position")

    # Arena category
    arena_category = ARENA_CATEGORY_LABELS.get(
        ARENA_CATEGORIES.get(r.platform or "", ""), ""
    )

    # Language: prefer top-level field, fall back to enrichment detection
    language = r.language
    if not language:
        lang_enrichment = (raw_meta.get("enrichments") or {}).get("language_detection") or {}
        language = lang_enrichment.get("language")

    # Query design label — prefer the human-readable name; fall back to the
    # UUID so exports remain traceable even when the caller did not pass
    # a name map.
    if r.query_design_id is None:
        query_design_label = ""
    elif design_name_by_id is not None and r.query_design_id in design_name_by_id:
        query_design_label = design_name_by_id[r.query_design_id]
    else:
        query_design_label = str(r.query_design_id)

    return {
        "query_design": query_design_label,
        "platform": r.platform,
        "arena": r.arena,
        "arena_category": arena_category,
        "content_type": r.content_type,
        "title": r.title,
        "text_content": r.text_content,
        "url": r.url,
        "links": links_str,
        "author_display_name": r.author_display_name,
        "pseudonymized_author_id": r.pseudonymized_author_id,
        "published_at": r.published_at,
        "views_count": r.views_count,
        "likes_count": r.likes_count,
        "shares_count": r.shares_count,
        "comments_count": r.comments_count,
        "engagement_score": r.engagement_score,
        "language": language,
        "search_terms_matched": r.search_terms_matched,
        "search_rank": int(search_rank) if search_rank is not None else None,
        "content_hash": r.content_hash,
        "raw_metadata": r.raw_metadata,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/projects")
async def list_projects(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, list[dict[str, Any]]]:
    """List the current user's projects with metadata for the dashboard overview.

    Returns each project with its most recent collection run timestamp (if any)
    and the count of attached query designs.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        A dict with a ``projects`` list.  Each entry has:
        - ``id``: project UUID string
        - ``name``: project display name
        - ``last_run_at``: ISO 8601 timestamp of the most recent run, or null
        - ``query_design_count``: number of query designs in the project
    """
    # Include owned projects + projects shared with the user
    from sqlalchemy import or_

    from issue_observatory.core.models.project_collaborator import ProjectCollaborator

    collaborated_project_ids = (
        select(ProjectCollaborator.project_id)
        .where(ProjectCollaborator.user_id == current_user.id)
        .scalar_subquery()
    )
    stmt = (
        select(
            Project.id,
            Project.name,
            func.count(distinct(QueryDesign.id)).label("design_count"),
        )
        .outerjoin(QueryDesign, QueryDesign.project_id == Project.id)
        .where(
            or_(
                Project.owner_id == current_user.id,
                Project.id.in_(collaborated_project_ids),
            )
        )
        .group_by(Project.id, Project.name)
        .order_by(Project.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    if not rows:
        return {"projects": []}

    project_ids = [row.id for row in rows]

    # Fetch the most recent collection run per query design for each project.
    # We join collection_runs via query_design_id to attribute a run to a project.
    last_run_stmt = (
        select(
            QueryDesign.project_id,
            func.max(CollectionRun.started_at).label("last_run_at"),
        )
        .join(CollectionRun, CollectionRun.query_design_id == QueryDesign.id)
        .where(
            QueryDesign.project_id.in_(project_ids),
            CollectionRun.started_at.isnot(None),
        )
        .group_by(QueryDesign.project_id)
    )
    last_run_result = await db.execute(last_run_stmt)
    last_run_by_project: dict[uuid.UUID, datetime] = {
        row.project_id: row.last_run_at for row in last_run_result.all()
    }

    projects: list[dict[str, Any]] = []
    for row in rows:
        last_run_at = last_run_by_project.get(row.id)
        projects.append(
            {
                "id": str(row.id),
                "name": row.name,
                "last_run_at": last_run_at.isoformat() if last_run_at else None,
                "query_design_count": row.design_count,
            }
        )

    logger.debug("dashboard.list_projects", user_id=str(current_user.id), count=len(projects))
    return {"projects": projects}


@router.get("/latest-date")
async def get_latest_record_date(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    project_id: uuid.UUID | None = Query(
        default=None,
        description=(
            "Project UUID. Omit to use the user's most recently created project "
            "(same scoping rule as the chart endpoints, so the anchor date always "
            "matches the data the charts will display)."
        ),
    ),
) -> dict[str, str | None]:
    """Return the latest ``published_at`` for the given project scope.

    Used by the dashboard to anchor the date-range presets ("Last 1M", "Last 3M",
    ...) to the newest record in the selected project instead of the current
    wall-clock time, so presets land on a range that actually contains data.

    Scoping matches the chart endpoints (volume/actors/terms): when
    ``project_id`` is omitted, the user's most recently created project is used.
    Returns ``{"latest_date": null}`` when the scope has no records.
    """
    resolved_id = project_id or await _get_most_recent_project_id(db, current_user.id)
    if resolved_id is None:
        return {"latest_date": None}

    _, design_ids = await _resolve_project_or_raise(db, resolved_id, current_user)
    latest = await _get_latest_published_at(db, design_ids)
    return {"latest_date": latest.isoformat() if latest else None}


@router.get("/volume")
async def get_project_volume(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    project_id: uuid.UUID | None = Query(
        default=None,
        description="Project UUID. Omit to use the most recently created project.",
    ),
    date_from: datetime | None = Query(
        default=None,
        description="Inclusive lower bound on published_at (ISO 8601). Defaults to 30 days ago.",
    ),
    date_to: datetime | None = Query(
        default=None,
        description="Inclusive upper bound on published_at (ISO 8601). Defaults to now.",
    ),
    granularity: str = Query(
        default="day",
        description="Time bucket size: hour, day, week, or month.",
    ),
    arena_category: str | None = Query(
        default=None,
        description="Filter by arena category: news, search, web, or social_media.",
    ),
    platform: str | None = Query(
        default=None,
        description="Filter by platform name (e.g. 'reddit').",
    ),
    language: str | None = Query(
        default=None,
        description="Filter by detected language (ISO 639-1, e.g. 'da').",
    ),
) -> list[dict[str, Any]]:
    """Return content volume over time for a project.

    Delegates to :func:`~issue_observatory.analysis.descriptive.get_volume_with_deltas`
    with delta computation for snapshot arenas (Google Search, Autocomplete).

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user.
        project_id: Project to scope the query to.
        date_from: Lower bound on published_at; defaults to 30 days ago.
        date_to: Upper bound on published_at; defaults to now.
        granularity: Bucket size — one of hour, day, week, month.
        arena_category: Optional arena category filter.
        platform: Optional platform filter.
        language: Optional detected language filter.

    Returns:
        A list of dicts with ``period``, ``count``, and ``arenas`` keys.

    Raises:
        HTTPException 400: If granularity or arena_category is invalid.
        HTTPException 404: If the project is not found.
        HTTPException 403: If the user does not own the project.
    """
    if arena_category is not None and arena_category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid arena_category {arena_category!r}. "
                f"Valid values: {sorted(VALID_CATEGORIES)}."
            ),
        )

    resolved_id = project_id or await _get_most_recent_project_id(db, current_user.id)
    if resolved_id is None:
        return []

    _, design_ids = await _resolve_project_or_raise(db, resolved_id, current_user)
    if not design_ids:
        return []

    anchor = await _get_latest_published_at(db, design_ids) or datetime.now(UTC)
    effective_date_from = date_from or (anchor - timedelta(days=30))
    effective_date_to = date_to or anchor

    try:
        return await get_volume_with_deltas(
            db,
            arena=arena_category,
            platform=platform,
            date_from=effective_date_from,
            date_to=effective_date_to,
            granularity=granularity,
            query_design_ids=design_ids,
            language=language,
            include_linked=False,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/actors")
async def get_project_top_actors(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    project_id: uuid.UUID | None = Query(
        default=None,
        description="Project UUID. Omit to use the most recently created project.",
    ),
    date_from: datetime | None = Query(
        default=None,
        description="Inclusive lower bound on published_at (ISO 8601). Defaults to 30 days ago.",
    ),
    date_to: datetime | None = Query(
        default=None,
        description="Inclusive upper bound on published_at (ISO 8601). Defaults to now.",
    ),
    arena_category: str | None = Query(
        default=None,
        description="Filter by arena category: news, search, web, or social_media.",
    ),
    platform: str | None = Query(
        default=None,
        description="Filter by platform name (e.g. 'reddit').",
    ),
    language: str | None = Query(
        default=None,
        description="Filter by detected language (ISO 639-1, e.g. 'da').",
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of actors to return.",
    ),
) -> list[dict[str, Any]]:
    """Return top actors by post volume for a project.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user.
        project_id: Project to scope the query to.
        date_from: Lower bound on published_at; defaults to 30 days ago.
        date_to: Upper bound on published_at; defaults to now.
        arena_category: Optional arena category filter
            (ignored by get_top_actors, kept for API symmetry).
        platform: Optional platform filter.
        language: Optional detected language filter.
        limit: Maximum number of actors to return (1-100).

    Returns:
        A list of actor dicts ordered by count descending.

    Raises:
        HTTPException 400: If arena_category is invalid.
        HTTPException 404: If the project is not found.
        HTTPException 403: If the user does not own the project.
    """
    if arena_category is not None and arena_category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid arena_category {arena_category!r}. "
                f"Valid values: {sorted(VALID_CATEGORIES)}."
            ),
        )

    resolved_id = project_id or await _get_most_recent_project_id(db, current_user.id)
    if resolved_id is None:
        return []

    _, design_ids = await _resolve_project_or_raise(db, resolved_id, current_user)
    if not design_ids:
        return []

    anchor = await _get_latest_published_at(db, design_ids) or datetime.now(UTC)
    effective_date_from = date_from or (anchor - timedelta(days=30))
    effective_date_to = date_to or anchor

    return await get_top_actors(
        db,
        platform=platform,
        date_from=effective_date_from,
        date_to=effective_date_to,
        limit=limit,
        query_design_ids=design_ids,
        language=language,
        include_linked=False,
    )


@router.get("/terms")
async def get_project_top_terms(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    project_id: uuid.UUID | None = Query(
        default=None,
        description="Project UUID. Omit to use the most recently created project.",
    ),
    date_from: datetime | None = Query(
        default=None,
        description="Inclusive lower bound on published_at (ISO 8601). Defaults to 30 days ago.",
    ),
    date_to: datetime | None = Query(
        default=None,
        description="Inclusive upper bound on published_at (ISO 8601). Defaults to now.",
    ),
    arena_category: str | None = Query(
        default=None,
        description="Filter by arena category (kept for API symmetry; not applied to term query).",
    ),
    platform: str | None = Query(
        default=None,
        description="Filter by platform name (kept for API symmetry; not applied to term query).",
    ),
    language: str | None = Query(
        default=None,
        description="Filter by detected language (ISO 639-1, e.g. 'da').",
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of terms to return.",
    ),
) -> list[dict[str, Any]]:
    """Return top search terms by match frequency for a project.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user.
        project_id: Project to scope the query to.
        date_from: Lower bound on published_at; defaults to 30 days ago.
        date_to: Upper bound on published_at; defaults to now.
        arena_category: Accepted for API symmetry but not applied (terms span all arenas).
        platform: Accepted for API symmetry but not applied (terms span all platforms).
        language: Optional detected language filter.
        limit: Maximum number of terms to return (1-100).

    Returns:
        A list of dicts with ``term`` and ``count`` keys, ordered by count descending.

    Raises:
        HTTPException 400: If arena_category is invalid.
        HTTPException 404: If the project is not found.
        HTTPException 403: If the user does not own the project.
    """
    if arena_category is not None and arena_category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid arena_category {arena_category!r}. "
                f"Valid values: {sorted(VALID_CATEGORIES)}."
            ),
        )

    resolved_id = project_id or await _get_most_recent_project_id(db, current_user.id)
    if resolved_id is None:
        return []

    _, design_ids = await _resolve_project_or_raise(db, resolved_id, current_user)
    if not design_ids:
        return []

    anchor = await _get_latest_published_at(db, design_ids) or datetime.now(UTC)
    effective_date_from = date_from or (anchor - timedelta(days=30))
    effective_date_to = date_to or anchor

    return await get_top_terms(
        db,
        date_from=effective_date_from,
        date_to=effective_date_to,
        limit=limit,
        query_design_ids=design_ids,
        language=language,
        include_linked=False,
    )


@router.get("/filter-options")
async def get_filter_options(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    project_id: uuid.UUID | None = Query(
        default=None,
        description="Project UUID. Omit to use the most recently created project.",
    ),
) -> dict[str, Any]:
    """Return available arena categories and platforms for filtering.

    Queries distinct ``arena`` and ``platform`` values from content_records
    scoped to the project's query designs, then enriches arena slugs with
    human-readable labels from the canonical categories mapping.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user.
        project_id: Project to scope the query to.

    Returns:
        A dict with:
        - ``arena_categories``: list of ``{"value": str, "label": str}`` dicts
        - ``platforms``: sorted list of platform name strings
    """
    resolved_id = project_id or await _get_most_recent_project_id(db, current_user.id)
    if resolved_id is None:
        return {
            "arena_categories": [
                {"value": k, "label": v} for k, v in ARENA_CATEGORY_LABELS.items()
            ],
            "platforms": [],
        }

    _, design_ids = await _resolve_project_or_raise(db, resolved_id, current_user)
    if not design_ids:
        return {
            "arena_categories": [
                {"value": k, "label": v} for k, v in ARENA_CATEGORY_LABELS.items()
            ],
            "platforms": [],
        }

    placeholders = ", ".join(f":id_{i}" for i in range(len(design_ids)))
    params: dict[str, Any] = {f"id_{i}": str(did) for i, did in enumerate(design_ids)}

    # Single scan instead of three separate DISTINCT queries.
    # Language: prefer the column, fall back to the enrichment result.
    _LANG_EXPR = (
        "COALESCE(NULLIF(language, ''), "
        "raw_metadata->'enrichments'->'language_detection'->>'language')"
    )
    combined_sql = text(
        f"""
        SELECT
            COALESCE(array_agg(DISTINCT arena) FILTER (WHERE arena IS NOT NULL), '{{}}') AS arenas,
            COALESCE(array_agg(DISTINCT platform) FILTER (WHERE platform IS NOT NULL), '{{}}') AS platforms,
            COALESCE(array_agg(DISTINCT split_part({_LANG_EXPR}, '-', 1)) FILTER (WHERE {_LANG_EXPR} IS NOT NULL), '{{}}') AS languages
        FROM content_records
        WHERE query_design_id IN ({placeholders})
          AND (raw_metadata->>'duplicate_of') IS NULL
        """
    )
    result = await db.execute(combined_sql, params)
    row = result.fetchone()

    present_arenas: set[str] = set(row.arenas) if row and row.arenas else set()
    platforms: list[str] = sorted(row.platforms) if row and row.platforms else []
    languages: list[str] = sorted(row.languages) if row and row.languages else []

    # Build arena_categories list: flat string values that the frontend
    # maps to display labels via its own categoryLabels dict.
    arena_categories = [
        k for k in ARENA_CATEGORY_LABELS if k in present_arenas
    ]

    logger.debug(
        "dashboard.filter_options",
        user_id=str(current_user.id),
        project_id=str(resolved_id),
        arena_count=len(arena_categories),
        platform_count=len(platforms),
    )
    return {"arena_categories": arena_categories, "platforms": platforms, "languages": languages}


@router.get("/platform-counts")
async def get_platform_counts(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    project_id: uuid.UUID | None = Query(
        default=None,
        description="Project UUID. Omit to use the most recently created project.",
    ),
    matched_only: bool = Query(
        default=True,
        description="If true, only count records that matched a search term.",
    ),
    language: str | None = Query(
        default=None,
        description="Filter by detected language (ISO 639-1, e.g. 'da').",
    ),
    arena_category: str | None = Query(
        default=None,
        description="Filter by arena category: news, search, web, or social_media.",
    ),
    platform: str | None = Query(
        default=None,
        description="Filter by platform name (e.g. 'reddit').",
    ),
) -> list[dict[str, Any]]:
    """Return per-platform record counts grouped by content type.

    Queries content_records scoped to the project's query designs and groups
    by platform and content_type (post, comment, etc.), returning totals for
    each combination plus a per-platform total.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user.
        project_id: Project to scope the query to.
        matched_only: When true, only count term-matched records.

    Returns:
        A list of dicts, each with ``platform``, ``posts``, ``comments``,
        ``other``, and ``total`` counts, sorted by total descending.
    """
    resolved_id = project_id or await _get_most_recent_project_id(db, current_user.id)
    if resolved_id is None:
        return []

    _, design_ids = await _resolve_project_or_raise(db, resolved_id, current_user)
    if not design_ids:
        return []

    placeholders = ", ".join(f":id_{i}" for i in range(len(design_ids)))
    params: dict[str, Any] = {f"id_{i}": str(did) for i, did in enumerate(design_ids)}

    matched_clause = "AND term_matched = true" if matched_only else ""
    # Language: prefer the column, fall back to the enrichment result.
    _LANG_EXPR = (
        "COALESCE(NULLIF(language, ''), "
        "raw_metadata->'enrichments'->'language_detection'->>'language')"
    )
    language_clause = ""
    if language:
        language_clause = f"AND split_part({_LANG_EXPR}, '-', 1) = :language"
        params["language"] = language.split("-")[0]
    arena_clause = ""
    if arena_category:
        arena_clause = "AND arena = :arena_category"
        params["arena_category"] = arena_category
    platform_clause = ""
    if platform:
        platform_clause = "AND platform = :platform"
        params["platform"] = platform
    sql = text(
        f"""
        SELECT platform,
               content_type,
               count(*) AS cnt
        FROM content_records
        WHERE query_design_id IN ({placeholders})
          AND (raw_metadata->>'duplicate_of') IS NULL
          {matched_clause}
          {language_clause}
          {arena_clause}
          {platform_clause}
        GROUP BY platform, content_type
        ORDER BY platform
        """
    )
    result = await db.execute(sql, params)
    rows = result.fetchall()

    # Aggregate into per-platform rows with posts/comments/other breakdown
    platform_data: dict[str, dict[str, int]] = {}
    for row in rows:
        plat = row.platform or "unknown"
        ct = (row.content_type or "").lower()
        if plat not in platform_data:
            platform_data[plat] = {"posts": 0, "comments": 0, "other": 0, "total": 0}
        bucket = platform_data[plat]
        if ct in ("post", "article", "video", "image", "link", "story"):
            bucket["posts"] += row.cnt
        elif ct in ("comment", "reply"):
            bucket["comments"] += row.cnt
        else:
            bucket["other"] += row.cnt
        bucket["total"] += row.cnt

    output = [
        {"platform": plat, **counts}
        for plat, counts in platform_data.items()
    ]
    output.sort(key=lambda x: x["total"], reverse=True)

    logger.debug(
        "dashboard.platform_counts",
        user_id=str(current_user.id),
        project_id=str(resolved_id),
        platform_count=len(output),
    )
    return output


@router.get("/export")
async def export_project_data(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    project_id: uuid.UUID | None = Query(
        default=None,
        description="Project UUID. Omit to use the most recently created project.",
    ),
    date_from: datetime | None = Query(
        default=None,
        description="Inclusive lower bound on published_at (ISO 8601). Defaults to 30 days ago.",
    ),
    date_to: datetime | None = Query(
        default=None,
        description="Inclusive upper bound on published_at (ISO 8601). Defaults to now.",
    ),
    arena_category: str | None = Query(
        default=None,
        description="Filter by arena category: news, search, web, or social_media.",
    ),
    platform: str | None = Query(
        default=None,
        description="Filter by platform name (e.g. 'reddit').",
    ),
    language: str | None = Query(
        default=None,
        description="Filter by detected language (ISO 639-1, e.g. 'da').",
    ),
    format: str = Query(
        default="csv",
        description="Export format: csv, xlsx, json, or parquet.",
    ),
    limit: int | None = Query(
        default=None,
        ge=1,
        description=(
            "Maximum number of records to export.  "
            "CSV has no cap (streamed row-by-row).  "
            "xlsx/json/parquet are capped at 10 000 because they must be "
            "assembled fully in memory; values above the cap are clamped."
        ),
    ),
) -> Response:
    """Export project content records as a file download.

    Fetches term-matched, non-duplicate content records scoped to the project
    and applies the specified filters before passing to ContentExporter.

    CSV exports are streamed row-by-row so arbitrarily large result sets can
    be downloaded without blowing server memory.  The other formats (xlsx,
    json, parquet) must materialise the full dataset in memory before sending
    bytes, so they are capped at 10 000 rows.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user.
        project_id: Project to scope the export to.
        date_from: Lower bound on published_at; defaults to 30 days ago.
        date_to: Upper bound on published_at; defaults to now.
        arena_category: Optional arena category filter.
        platform: Optional platform filter.
        language: Optional detected language filter (ISO 639-1).
        format: Output format - one of csv, xlsx, json, parquet.
        limit: Maximum records to include.  ``None`` means unlimited for
            CSV; non-CSV formats are always clamped to 10 000.

    Returns:
        A streaming ``Response`` (CSV) or buffered ``Response`` (other
        formats), both with a ``Content-Disposition: attachment`` header.

    Raises:
        HTTPException 400: If format or arena_category is invalid.
        HTTPException 404: If the project is not found.
        HTTPException 403: If the user does not own the project.
    """
    _NONSTREAM_LIMIT = 10_000
    if format not in _EXPORT_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported export format {format!r}. "
                f"Choose from: {', '.join(_EXPORT_CONTENT_TYPES)}."
            ),
        )

    if arena_category is not None and arena_category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid arena_category {arena_category!r}. "
                f"Valid values: {sorted(VALID_CATEGORIES)}."
            ),
        )

    resolved_id = project_id or await _get_most_recent_project_id(db, current_user.id)
    if resolved_id is None:
        return Response(
            content=b"",
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="empty_export.csv"'},
        )

    _, design_ids = await _resolve_project_or_raise(db, resolved_id, current_user)
    if not design_ids:
        return Response(
            content=b"",
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="empty_export.csv"'},
        )

    stmt = (
        select(UniversalContentRecord)
        .where(
            UniversalContentRecord.query_design_id.in_(design_ids),
            UniversalContentRecord.term_matched.is_(True),
            UniversalContentRecord.raw_metadata["duplicate_of"].as_string().is_(None),
        )
        .order_by(UniversalContentRecord.collected_at.desc())
    )

    if date_from is not None:
        stmt = stmt.where(UniversalContentRecord.published_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(UniversalContentRecord.published_at <= date_to)

    if arena_category is not None:
        stmt = stmt.where(UniversalContentRecord.arena == arena_category)
    if platform is not None:
        stmt = stmt.where(UniversalContentRecord.platform == platform)
    if language is not None:
        # Normalize locale variants (e.g. "da-DK" → "da") and fall back to the
        # language_detection enrichment when the column is empty.  Mirrors
        # analysis._filters.build_content_filters so the export matches the
        # dashboard charts exactly.
        lang_base = language.split("-")[0]
        lang_col = func.coalesce(
            func.nullif(UniversalContentRecord.language, ""),
            UniversalContentRecord.raw_metadata["enrichments"]["language_detection"][
                "language"
            ].as_string(),
        )
        stmt = stmt.where(func.split_part(lang_col, "-", 1) == lang_base)

    exporter = ContentExporter()
    ext = _EXPORT_EXTENSIONS[format]
    filename = f"project_{resolved_id}_{format}_export.{ext}"
    content_type = _EXPORT_CONTENT_TYPES[format]

    # Resolve {design_id: design_name} once so rows can stamp the
    # human-readable design name in the ``query_design`` column without
    # N+1 lookups during streaming.
    design_name_result = await db.execute(
        select(QueryDesign.id, QueryDesign.name).where(
            QueryDesign.id.in_(design_ids)
        )
    )
    design_name_by_id: dict[uuid.UUID, str] = {
        row.id: row.name for row in design_name_result.all()
    }

    if format == "csv":
        # Unbounded streaming path.  ``limit`` is respected when set; when
        # None the entire filtered result set is streamed.  ``yield_per``
        # tells SQLAlchemy to fetch and expire ORM rows in chunks so memory
        # stays flat regardless of total row count.
        csv_stmt = (stmt.limit(limit) if limit else stmt).execution_options(
            yield_per=500
        )

        # IMPORTANT: do not reuse the dependency-injected ``db`` session
        # inside the streaming generator.  FastAPI closes the session
        # provided by ``Depends(get_db)`` when the route handler returns,
        # and the StreamingResponse generator keeps iterating *after* that
        # point — which would kill the server-side cursor mid-stream and
        # silently truncate the download.  Instead, open a dedicated
        # session whose lifetime is bound to the generator itself.
        async def _record_dict_iter() -> AsyncIterator[dict[str, Any]]:
            async with AsyncSessionLocal() as stream_db:
                result = await stream_db.stream_scalars(csv_stmt)
                async for row in result:
                    yield _record_to_dict(row, design_name_by_id)

        logger.info(
            "dashboard.export_stream_start",
            project_id=str(resolved_id),
            user_id=str(current_user.id),
            format=format,
            limit=limit,
        )
        return StreamingResponse(
            exporter.export_csv_stream(_record_dict_iter()),
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # Non-streaming formats: materialise everything in memory, always clamped.
    effective_limit = min(limit or _NONSTREAM_LIMIT, _NONSTREAM_LIMIT)
    db_result = await db.execute(stmt.limit(effective_limit))
    orm_rows = list(db_result.scalars().all())
    records = [_record_to_dict(r, design_name_by_id) for r in orm_rows]

    try:
        if format == "xlsx":
            file_bytes = await exporter.export_xlsx(records)
        elif format == "json":
            file_bytes = await exporter.export_json(records)
        else:  # parquet
            file_bytes = await exporter.export_parquet(records)
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    logger.info(
        "dashboard.export",
        project_id=str(resolved_id),
        user_id=str(current_user.id),
        format=format,
        record_count=len(records),
        effective_limit=effective_limit,
    )

    return Response(
        content=file_bytes,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
