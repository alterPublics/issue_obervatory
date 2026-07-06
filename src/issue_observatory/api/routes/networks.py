"""Networks page API routes.

Provides JSON endpoints for keyword, entity, and domain co-occurrence
network analysis across query designs, with GEXF export support. Unlike
the run-scoped analysis routes, these endpoints operate across all
collection runs that belong to a project or set of query designs, making
them suitable for longitudinal and cross-run network exploration.

All endpoints require authentication. Results are scoped to the requesting
user's own projects and query designs.

Routes:
    GET /networks/keyword-network   — JSON keyword co-occurrence graph
    GET /networks/entity-network    — JSON named-entity co-occurrence graph
    GET /networks/domain-network    — JSON domain co-occurrence graph from
                                      url_extraction enrichments
    GET /networks/filter-options    — JSON filter metadata (projects, designs,
                                      terms, categories, platforms)
    GET /networks/export-gexf       — GEXF file download for keyword, entity,
                                      or domain network
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import distinct, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.analysis.export import ContentExporter
from issue_observatory.analysis.network_builder import (
    build_domain_network,
    build_entity_network,
    build_keyword_network,
)
from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.arenas.categories import ARENA_CATEGORY_LABELS
from issue_observatory.core.database import get_db
from issue_observatory.core.models.project import Project
from issue_observatory.core.models.project_collaborator import ProjectCollaborator
from issue_observatory.core.models.query_design import QueryDesign, SearchTerm
from issue_observatory.core.models.users import User

logger = structlog.get_logger(__name__)

router = APIRouter()

_DEFAULT_ENTITY_TYPES = "PERSON,ORG,GPE,LOC"
_VALID_KEYWORD_MODES = {"bipartite", "unipartite_sender", "unipartite_platform", "unipartite_keyword"}
_VALID_ENTITY_MODES = {"bipartite", "unipartite_sender", "unipartite_platform", "unipartite_entity"}
_VALID_DOMAIN_MODES = {"bipartite", "unipartite_sender", "unipartite_platform", "unipartite_domain"}


def parse_csv_param(value: str | None) -> list[str]:
    """Parse a comma-separated query param into a list of non-empty strings."""
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


async def resolve_design_ids(
    db: AsyncSession,
    project_id: uuid.UUID | None,
    explicit_ids: list[str],
    user_id: uuid.UUID,
) -> list[uuid.UUID] | None:
    """Resolve project_id and/or explicit IDs to query_design_ids.

    When neither project_id nor explicit_ids are provided, returns all query
    design IDs from the user's own and collaborated projects to ensure data
    is always scoped to the authenticated user.
    """
    from sqlalchemy import or_

    collaborated_project_ids = (
        select(ProjectCollaborator.project_id)
        .where(ProjectCollaborator.user_id == user_id)
        .scalar_subquery()
    )

    if explicit_ids:
        return [uuid.UUID(i) for i in explicit_ids]

    if project_id is not None:
        result = await db.execute(
            select(QueryDesign.id).join(Project).where(
                Project.id == project_id,
                or_(
                    Project.owner_id == user_id,
                    Project.id.in_(collaborated_project_ids),
                ),
            )
        )
        ids = [row[0] for row in result.fetchall()]
        return ids if ids else []

    # No project or explicit IDs — scope to ALL user's query designs
    result = await db.execute(
        select(QueryDesign.id)
        .join(Project, Project.id == QueryDesign.project_id, isouter=True)
        .where(
            or_(
                Project.owner_id == user_id,
                Project.id.in_(collaborated_project_ids),
            )
        )
    )
    ids = [row[0] for row in result.fetchall()]
    return ids if ids else []


# ---------------------------------------------------------------------------
# Keyword network
# ---------------------------------------------------------------------------


@router.get("/keyword-network")
async def get_keyword_network(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    project_id: uuid.UUID | None = Query(default=None, description="Filter by project."),
    query_design_ids: str | None = Query(
        default=None, description="Comma-separated query design UUIDs."
    ),
    search_terms: str | None = Query(
        default=None, description="Comma-separated search terms for window mode."
    ),
    arena_categories: str | None = Query(
        default=None,
        description="Comma-separated arena categories (news, search, web, social_media).",
    ),
    platforms: str | None = Query(
        default=None, description="Comma-separated platform slugs."
    ),
    languages: str | None = Query(
        default=None, description="Comma-separated language codes (ISO 639-1, e.g. 'da,en')."
    ),
    date_from: datetime | None = Query(
        default=None, description="Lower bound on published_at."
    ),
    date_to: datetime | None = Query(
        default=None, description="Upper bound on published_at."
    ),
    mode: str = Query(
        default="bipartite", description="Network mode: bipartite or unipartite."
    ),
    content_mode: str = Query(
        default="full", description="Content mode: full or window."
    ),
    window_size: int | None = Query(
        default=None,
        description="Window half-width in words (content_mode='window').",
    ),
    min_weight: int = Query(
        default=1, ge=1, description="Minimum edge weight to include."
    ),
    giant_component_only: bool = Query(
        default=False, description="Return only the giant connected component."
    ),
    group_by: str = Query(
        default="sender",
        description="Grouping dimension: 'sender' (author) or 'platform'.",
    ),
    min_items: int | None = Query(
        default=None, ge=1,
        description="Minimum distinct keywords a sender/platform must have.",
    ),
    max_items: int | None = Query(
        default=None, ge=1,
        description="Maximum keywords to keep per sender/platform (top by weight).",
    ),
) -> dict[str, Any]:
    """Build a keyword co-occurrence network from collected content records."""
    if mode not in _VALID_KEYWORD_MODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid mode {mode!r}. Choose from: {', '.join(sorted(_VALID_KEYWORD_MODES))}",
        )
    design_ids = await resolve_design_ids(
        db, project_id, parse_csv_param(query_design_ids), current_user.id
    )

    terms_list = parse_csv_param(search_terms)
    categories_list = parse_csv_param(arena_categories)
    platforms_list = parse_csv_param(platforms)
    languages_list = parse_csv_param(languages)

    # Window mode requires search terms — auto-fetch from query designs if none provided
    if content_mode == "window" and not terms_list and design_ids:
        result = await db.execute(
            select(distinct(SearchTerm.term)).where(
                SearchTerm.query_design_id.in_([str(d) for d in design_ids])
            )
        )
        terms_list = [row[0] for row in result.fetchall()]

    graph = await build_keyword_network(
        db,
        mode=mode,
        content_mode=content_mode,
        window_size=window_size,
        query_design_ids=design_ids,
        platform=platforms_list or None,
        arena_category=categories_list or None,
        date_from=date_from,
        date_to=date_to,
        search_terms=terms_list,
        min_weight=min_weight,
        giant_component_only=giant_component_only,
        group_by=group_by,
        min_items=min_items,
        max_items=max_items,
        language=languages_list or None,
    )

    logger.info(
        "keyword_network_built",
        user_id=str(current_user.id),
        node_count=len(graph.get("nodes", [])),
        edge_count=len(graph.get("edges", [])),
        mode=mode,
        group_by=group_by,
    )
    return graph


# ---------------------------------------------------------------------------
# Entity network
# ---------------------------------------------------------------------------


@router.get("/entity-network")
async def get_entity_network(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    project_id: uuid.UUID | None = Query(default=None, description="Filter by project."),
    query_design_ids: str | None = Query(
        default=None, description="Comma-separated query design UUIDs."
    ),
    search_terms: str | None = Query(
        default=None, description="Comma-separated search terms to filter by."
    ),
    arena_categories: str | None = Query(
        default=None,
        description="Comma-separated arena categories (news, search, web, social_media).",
    ),
    platforms: str | None = Query(
        default=None, description="Comma-separated platform slugs."
    ),
    languages: str | None = Query(
        default=None, description="Comma-separated language codes (ISO 639-1, e.g. 'da,en')."
    ),
    date_from: datetime | None = Query(
        default=None, description="Lower bound on published_at."
    ),
    date_to: datetime | None = Query(
        default=None, description="Upper bound on published_at."
    ),
    entity_types: str | None = Query(
        default=_DEFAULT_ENTITY_TYPES,
        description=(
            "Comma-separated spaCy entity type labels to include "
            "(default: PERSON,ORG,GPE,LOC)."
        ),
    ),
    mode: str = Query(
        default="bipartite", description="Network mode: bipartite or unipartite."
    ),
    min_weight: int = Query(
        default=1, ge=1, description="Minimum edge weight to include."
    ),
    giant_component_only: bool = Query(
        default=False, description="Return only the giant connected component."
    ),
    group_by: str = Query(
        default="sender",
        description="Grouping dimension: 'sender' (author) or 'platform'.",
    ),
    min_items: int | None = Query(
        default=None, ge=1,
        description="Minimum distinct entities a sender/platform must have.",
    ),
    max_items: int | None = Query(
        default=None, ge=1,
        description="Maximum entities to keep per sender/platform (top by weight).",
    ),
) -> dict[str, Any]:
    """Build a named-entity co-occurrence network from collected content records."""
    if mode not in _VALID_ENTITY_MODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid mode {mode!r}. Choose from: {', '.join(sorted(_VALID_ENTITY_MODES))}",
        )
    design_ids = await resolve_design_ids(
        db, project_id, parse_csv_param(query_design_ids), current_user.id
    )

    terms_list = parse_csv_param(search_terms)
    categories_list = parse_csv_param(arena_categories)
    platforms_list = parse_csv_param(platforms)
    languages_list = parse_csv_param(languages)
    types_list = parse_csv_param(entity_types)

    graph = await build_entity_network(
        db,
        mode=mode,
        entity_types=types_list,
        query_design_ids=design_ids,
        platform=platforms_list or None,
        arena_category=categories_list or None,
        date_from=date_from,
        date_to=date_to,
        search_terms=terms_list or None,
        min_weight=min_weight,
        giant_component_only=giant_component_only,
        group_by=group_by,
        min_items=min_items,
        max_items=max_items,
        language=languages_list or None,
    )

    logger.info(
        "entity_network_built",
        user_id=str(current_user.id),
        node_count=len(graph.get("nodes", [])),
        edge_count=len(graph.get("edges", [])),
        entity_types=entity_types,
        group_by=group_by,
    )
    return graph


# ---------------------------------------------------------------------------
# Domain network
# ---------------------------------------------------------------------------


@router.get("/domain-network")
async def get_domain_network(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    project_id: uuid.UUID | None = Query(default=None, description="Filter by project."),
    query_design_ids: str | None = Query(
        default=None, description="Comma-separated query design UUIDs."
    ),
    search_terms: str | None = Query(
        default=None, description="Comma-separated search terms to filter by."
    ),
    arena_categories: str | None = Query(
        default=None,
        description="Comma-separated arena categories (news, search, web, social_media).",
    ),
    platforms: str | None = Query(
        default=None, description="Comma-separated platform slugs."
    ),
    languages: str | None = Query(
        default=None, description="Comma-separated language codes (ISO 639-1, e.g. 'da,en')."
    ),
    date_from: datetime | None = Query(
        default=None, description="Lower bound on published_at."
    ),
    date_to: datetime | None = Query(
        default=None, description="Upper bound on published_at."
    ),
    mode: str = Query(
        default="bipartite", description="Network mode: bipartite or unipartite."
    ),
    min_weight: int = Query(
        default=1, ge=1, description="Minimum edge weight to include."
    ),
    giant_component_only: bool = Query(
        default=False, description="Return only the giant connected component."
    ),
    group_by: str = Query(
        default="sender",
        description="Grouping dimension: 'sender' (author) or 'platform'.",
    ),
    min_items: int | None = Query(
        default=None, ge=1,
        description="Minimum distinct domains a sender/platform must have.",
    ),
    max_items: int | None = Query(
        default=None, ge=1,
        description="Maximum domains to keep per sender/platform (top by weight).",
    ),
    exclude_self_references: bool = Query(
        default=True,
        description=(
            "Exclude URLs tagged type='self_reference' (platform post permalinks). "
            "Recommended to keep True — the default surfaces substantive outbound "
            "linking rather than a platform's own self-permalinks."
        ),
    ),
) -> dict[str, Any]:
    """Build a domain co-occurrence network from URL-extraction enrichments."""
    if mode not in _VALID_DOMAIN_MODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid mode {mode!r}. Choose from: {', '.join(sorted(_VALID_DOMAIN_MODES))}",
        )
    design_ids = await resolve_design_ids(
        db, project_id, parse_csv_param(query_design_ids), current_user.id
    )

    terms_list = parse_csv_param(search_terms)
    categories_list = parse_csv_param(arena_categories)
    platforms_list = parse_csv_param(platforms)
    languages_list = parse_csv_param(languages)

    graph = await build_domain_network(
        db,
        mode=mode,
        query_design_ids=design_ids,
        platform=platforms_list or None,
        arena_category=categories_list or None,
        date_from=date_from,
        date_to=date_to,
        search_terms=terms_list or None,
        min_weight=min_weight,
        giant_component_only=giant_component_only,
        group_by=group_by,
        min_items=min_items,
        max_items=max_items,
        language=languages_list or None,
        exclude_self_references=exclude_self_references,
    )

    logger.info(
        "domain_network_built",
        user_id=str(current_user.id),
        node_count=len(graph.get("nodes", [])),
        edge_count=len(graph.get("edges", [])),
        mode=mode,
        group_by=group_by,
        exclude_self_references=exclude_self_references,
    )
    return graph


# ---------------------------------------------------------------------------
# Filter options
# ---------------------------------------------------------------------------


@router.get("/filter-options")
async def get_filter_options(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    project_id: uuid.UUID | None = Query(
        default=None,
        description="Project to scope query designs and search terms.",
    ),
) -> dict[str, Any]:
    """Return filter metadata for populating the Networks page filter controls.

    Fetches projects, query designs (scoped to the selected project when
    provided), search terms, all arena category labels, and distinct platform
    slugs from the ``content_records`` table.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        project_id: Optional UUID to restrict query designs to a single project.

    Returns:
        Dict with keys:

        - ``projects`` — list of ``{id, name}`` dicts for the user's projects.
        - ``query_designs`` — list of ``{id, name, project_id}`` dicts.
        - ``search_terms`` — list of distinct term strings from the designs.
        - ``arena_categories`` — list of ``{value, label}`` dicts for all four
          canonical categories.
        - ``platforms`` — list of distinct platform slug strings from the DB.
    """
    # Projects owned by or shared with the user.
    from sqlalchemy import or_

    collaborated_project_ids = (
        select(ProjectCollaborator.project_id)
        .where(ProjectCollaborator.user_id == current_user.id)
        .scalar_subquery()
    )
    projects_result = await db.execute(
        select(Project.id, Project.name)
        .where(
            or_(
                Project.owner_id == current_user.id,
                Project.id.in_(collaborated_project_ids),
            )
        )
        .order_by(Project.name)
    )
    projects = [{"id": str(row.id), "name": row.name} for row in projects_result.fetchall()]

    # Query designs — scoped to project when given, otherwise all user/shared designs.
    designs_stmt = (
        select(QueryDesign.id, QueryDesign.name, QueryDesign.project_id)
        .join(Project, Project.id == QueryDesign.project_id, isouter=True)
        .where(
            or_(
                Project.owner_id == current_user.id,
                Project.id.in_(collaborated_project_ids),
                QueryDesign.project_id.is_(None),
            )
        )
    )
    if project_id is not None:
        designs_stmt = designs_stmt.where(QueryDesign.project_id == project_id)
    designs_stmt = designs_stmt.order_by(QueryDesign.name)

    designs_result = await db.execute(designs_stmt)
    query_designs = [
        {
            "id": str(row.id),
            "name": row.name,
            "project_id": str(row.project_id) if row.project_id else None,
        }
        for row in designs_result.fetchall()
    ]

    # Search terms from the resolved designs.
    design_ids = [uuid.UUID(d["id"]) for d in query_designs]
    search_terms: list[str] = []
    if design_ids:
        terms_result = await db.execute(
            select(distinct(SearchTerm.term))
            .where(SearchTerm.query_design_id.in_(design_ids))
            .order_by(SearchTerm.term)
        )
        search_terms = [row[0] for row in terms_result.fetchall()]

    # All four canonical arena categories.
    arena_categories = [
        {"value": key, "label": label} for key, label in ARENA_CATEGORY_LABELS.items()
    ]

    # Distinct platforms with at least one content record.
    platforms_result = await db.execute(
        text(
            "SELECT DISTINCT platform FROM content_records "
            "WHERE platform IS NOT NULL ORDER BY platform"
        )
    )
    platforms = [row[0] for row in platforms_result.fetchall()]

    # Distinct languages with at least one content record.
    languages_result = await db.execute(
        text(
            "SELECT DISTINCT language FROM content_records "
            "WHERE language IS NOT NULL ORDER BY language"
        )
    )
    available_languages = [row[0] for row in languages_result.fetchall()]

    return {
        "projects": projects,
        "query_designs": query_designs,
        "search_terms": search_terms,
        "arena_categories": arena_categories,
        "platforms": platforms,
        "languages": available_languages,
    }


# ---------------------------------------------------------------------------
# GEXF export
# ---------------------------------------------------------------------------


@router.get("/export-gexf")
async def export_gexf(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    network_type: str = Query(
        default="keyword",
        description="Which network to export: 'keyword', 'entity', or 'domain'.",
    ),
    project_id: uuid.UUID | None = Query(default=None, description="Filter by project."),
    query_design_ids: str | None = Query(
        default=None, description="Comma-separated query design UUIDs."
    ),
    search_terms: str | None = Query(
        default=None,
        description="Comma-separated search terms (keyword network, window mode).",
    ),
    arena_categories: str | None = Query(
        default=None,
        description="Comma-separated arena categories (news, search, web, social_media).",
    ),
    platforms: str | None = Query(
        default=None, description="Comma-separated platform slugs."
    ),
    languages: str | None = Query(
        default=None, description="Comma-separated language codes (ISO 639-1)."
    ),
    date_from: datetime | None = Query(
        default=None, description="Lower bound on published_at."
    ),
    date_to: datetime | None = Query(
        default=None, description="Upper bound on published_at."
    ),
    mode: str = Query(
        default="bipartite", description="Network mode: bipartite or unipartite."
    ),
    content_mode: str = Query(
        default="full",
        description="Content mode: full or window (keyword network only).",
    ),
    window_size: int | None = Query(
        default=None,
        description="Window half-width in words (keyword network, window mode).",
    ),
    entity_types: str | None = Query(
        default=_DEFAULT_ENTITY_TYPES,
        description="Comma-separated NER label filter (entity network only).",
    ),
    min_weight: int = Query(
        default=1, ge=1, description="Minimum edge weight to include."
    ),
    giant_component_only: bool = Query(
        default=False, description="Return only the giant connected component."
    ),
    backbone: bool = Query(
        default=True,
        description="Apply node/edge limit backboning. Set to false for full graph export.",
    ),
    group_by: str = Query(
        default="sender",
        description="Grouping dimension: 'sender' (author) or 'platform'.",
    ),
    min_items: int | None = Query(
        default=None, ge=1,
        description="Minimum distinct items a sender/platform must have.",
    ),
    max_items: int | None = Query(
        default=None, ge=1,
        description="Maximum items to keep per sender/platform (top by weight).",
    ),
    exclude_self_references: bool = Query(
        default=True,
        description="Exclude type='self_reference' URLs (domain network only).",
    ),
) -> StreamingResponse:
    """Build a network and stream the result as a GEXF file download."""
    if network_type not in {"keyword", "entity", "domain"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="network_type must be 'keyword', 'entity', or 'domain'.",
        )

    design_ids = await resolve_design_ids(
        db, project_id, parse_csv_param(query_design_ids), current_user.id
    )

    categories_list = parse_csv_param(arena_categories)
    platforms_list = parse_csv_param(platforms)
    languages_list = parse_csv_param(languages)

    suffix = "_backbone" if backbone else "_full"
    if network_type == "keyword":
        terms_list = parse_csv_param(search_terms)
        graph = await build_keyword_network(
            db,
            mode=mode,
            content_mode=content_mode,
            window_size=window_size,
            query_design_ids=design_ids,
            platform=platforms_list or None,
            arena_category=categories_list or None,
            date_from=date_from,
            date_to=date_to,
            search_terms=terms_list,
            min_weight=min_weight,
            giant_component_only=giant_component_only,
            enforce_limits=backbone,
            group_by=group_by,
            min_items=min_items,
            max_items=max_items,
            language=languages_list or None,
        )
        filename = f"keyword_network{suffix}.gexf"
    elif network_type == "entity":
        terms_list = parse_csv_param(search_terms)
        types_list = parse_csv_param(entity_types)
        graph = await build_entity_network(
            db,
            mode=mode,
            entity_types=types_list,
            query_design_ids=design_ids,
            platform=platforms_list or None,
            arena_category=categories_list or None,
            date_from=date_from,
            date_to=date_to,
            search_terms=terms_list or None,
            min_weight=min_weight,
            language=languages_list or None,
            giant_component_only=giant_component_only,
            enforce_limits=backbone,
            group_by=group_by,
            min_items=min_items,
            max_items=max_items,
        )
        filename = f"entity_network{suffix}.gexf"
    else:
        terms_list = parse_csv_param(search_terms)
        graph = await build_domain_network(
            db,
            mode=mode,
            query_design_ids=design_ids,
            platform=platforms_list or None,
            arena_category=categories_list or None,
            date_from=date_from,
            date_to=date_to,
            search_terms=terms_list or None,
            min_weight=min_weight,
            language=languages_list or None,
            giant_component_only=giant_component_only,
            enforce_limits=backbone,
            group_by=group_by,
            min_items=min_items,
            max_items=max_items,
            exclude_self_references=exclude_self_references,
        )
        filename = f"domain_network{suffix}.gexf"

    exporter = ContentExporter()
    # Map network builder types to GEXF serializer types
    _gexf_type_map = {"keyword": "bipartite", "entity": "bipartite", "domain": "bipartite"}
    gexf_network_type = _gexf_type_map.get(network_type, "bipartite")
    gexf_bytes: bytes = await exporter.export_gexf(graph, network_type=gexf_network_type)

    logger.info(
        "gexf_export_streamed",
        user_id=str(current_user.id),
        network_type=network_type,
        node_count=len(graph.get("nodes", [])),
        edge_count=len(graph.get("edges", [])),
        filename=filename,
    )

    return StreamingResponse(
        io.BytesIO(gexf_bytes),
        media_type="application/gexf+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
