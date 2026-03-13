"""Project CRUD routes.

Provides endpoints for researchers to create and manage projects — organizational
containers that group related query designs together. Projects provide a hierarchical
structure: User → Project → Query Designs → Collection Runs → Content Records.

Ownership and access control:
    - Non-admin users can only create/modify/delete their own projects.
    - Admins can manage all projects.
    - Visibility 'private' = owner-only, 'shared' = all researchers (future).

Routes:
    GET    /                           — list projects for current user
    POST   /                           — create new project
    GET    /{project_id:uuid}         — project detail page (HTML)
    PATCH  /{project_id:uuid}         — update project name/description/visibility
    DELETE /{project_id:uuid}         — delete project (detaches query designs)
    POST   /{project_id:uuid}/clone   — deep-clone project with all query designs
    POST   /{project_id:uuid}/attach/{design_id:uuid}   — attach query design
    POST   /{project_id:uuid}/detach/{design_id:uuid}   — detach query design

Deletion policy:
    Deleting a project sets project_id=NULL on all attached query designs
    (via ON DELETE SET NULL FK). The designs are not deleted, just unattached.

Owned by the DB Engineer.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Body, Depends, Form, HTTPException, status
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.core.database import get_db
from issue_observatory.core.models.actors import ActorListMember
from issue_observatory.core.models.project import Project
from issue_observatory.core.models.query_design import ActorList, QueryDesign, SearchTerm
from issue_observatory.core.models.users import User

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper: Check project ownership
# ---------------------------------------------------------------------------


async def _verify_project_ownership(
    project_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
) -> Project:
    """Verify that the current user owns the given project.

    Admins bypass this check. Non-admin users must own the project.

    Args:
        project_id: UUID of the project to check.
        current_user: The authenticated user making the request.
        db: Async database session.

    Returns:
        The Project instance if access is granted.

    Raises:
        HTTPException 404: If the project does not exist.
        HTTPException 403: If the user does not own the project and is not admin.
    """
    stmt = select(Project).where(Project.id == project_id)
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    # Access control: admins can manage all projects, non-admins must own
    if current_user.role != "admin" and project.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this project.",
        )

    return project


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def list_projects(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """List projects for the current user.

    Non-admin users see only their own projects. Admin users see all projects.

    Args:
        request: The FastAPI request object (for template rendering).
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        HTML response with the project list page.
    """
    stmt = (
        select(
            Project,
            func.count(QueryDesign.id).label("query_design_count"),
        )
        .outerjoin(QueryDesign, QueryDesign.project_id == Project.id)
        .group_by(Project)
        .order_by(Project.updated_at.desc())
    )

    # Non-admins see only their own projects
    if current_user.role != "admin":
        stmt = stmt.where(Project.owner_id == current_user.id)

    result = await db.execute(stmt)
    rows = result.all()

    projects_with_counts = []
    for row in rows:
        project_dict = {
            "id": row.Project.id,
            "name": row.Project.name,
            "description": row.Project.description,
            "owner_id": row.Project.owner_id,
            "visibility": row.Project.visibility,
            "created_at": row.Project.created_at,
            "updated_at": row.Project.updated_at,
            "query_design_count": row.query_design_count,
        }
        projects_with_counts.append(project_dict)

    logger.debug(
        "projects.list",
        user_id=str(current_user.id),
        count=len(projects_with_counts),
    )

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "projects/list.html",
        {
            "request": request,
            "user": current_user,
            "projects": projects_with_counts,
        },
    )


# ---------------------------------------------------------------------------
# POST /
# ---------------------------------------------------------------------------


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_project(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    name: str = Form(...),
    description: str = Form(None),
    visibility: str = Form("private"),
) -> JSONResponse:
    """Create a new project.

    Form-encoded for HTMX compatibility. Returns JSON with the new project ID.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        name: Project name (required).
        description: Project description (optional).
        visibility: Access control level (defaults to 'private').

    Returns:
        JSON response with the new project's ID and redirect URL.
    """
    project = Project(
        id=uuid.uuid4(),
        name=name,
        description=description if description else None,
        visibility=visibility,
        owner_id=current_user.id,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    logger.info(
        "project.created",
        project_id=str(project.id),
        name=name,
        user_id=str(current_user.id),
    )

    return JSONResponse(
        {
            "id": str(project.id),
            "name": project.name,
            "redirect": f"/projects/{project.id}",
        },
        status_code=status.HTTP_201_CREATED,
    )


# ---------------------------------------------------------------------------
# GET /{project_id:uuid}
# ---------------------------------------------------------------------------


@router.get("/{project_id:uuid}", response_class=HTMLResponse)
async def get_project_detail(
    project_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Retrieve project detail page showing attached query designs.

    Args:
        project_id: UUID of the project to retrieve.
        request: The FastAPI request object (for template rendering).
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        HTML response with the project detail page.

    Raises:
        HTTPException 404: If the project does not exist or the user lacks access.
        HTTPException 403: If the user does not own the project and is not admin.
    """
    project = await _verify_project_ownership(project_id, current_user, db)

    # Load query designs attached to this project with their latest collection run
    stmt = (
        select(QueryDesign)
        .where(QueryDesign.project_id == project_id)
        .options(selectinload(QueryDesign.collection_runs))
        .order_by(QueryDesign.name)
    )
    result = await db.execute(stmt)
    query_designs = result.scalars().all()

    # Enrich each design with latest collection run info
    designs_with_runs = []
    for design in query_designs:
        latest_run = None
        if design.collection_runs:
            runs_with_start = [r for r in design.collection_runs if r.started_at is not None]
            if runs_with_start:
                latest_run = max(runs_with_start, key=lambda r: r.started_at)
            else:
                latest_run = design.collection_runs[0]

        designs_with_runs.append({
            "id": design.id,
            "name": design.name,
            "description": design.description,
            "created_at": design.created_at,
            "latest_run": {
                "id": latest_run.id,
                "status": latest_run.status,
                "started_at": latest_run.started_at,
                "completed_at": latest_run.completed_at,
                "records_collected": latest_run.records_collected,
            } if latest_run else None,
        })

    logger.debug(
        "project.detail",
        project_id=str(project_id),
        user_id=str(current_user.id),
        query_design_count=len(query_designs),
    )

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "projects/detail.html",
        {
            "request": request,
            "user": current_user,
            "project": project,
            "query_designs": designs_with_runs,
            "source_config": project.source_config or {},
            "comments_config": project.comments_config or {},
        },
    )


# ---------------------------------------------------------------------------
# PATCH /{project_id:uuid}
# ---------------------------------------------------------------------------


@router.patch("/{project_id:uuid}")
async def update_project(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    name: str = Form(None),
    description: str = Form(None),
    visibility: str = Form(None),
) -> JSONResponse:
    """Update an existing project.

    Form-encoded for HTMX compatibility. Only fields explicitly provided are updated.

    Args:
        project_id: UUID of the project to update.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        name: New project name (optional).
        description: New project description (optional).
        visibility: New access control level (optional).

    Returns:
        JSON response with success status.

    Raises:
        HTTPException 403: If the user does not have permission to modify this project.
        HTTPException 404: If the project does not exist.
    """
    project = await _verify_project_ownership(project_id, current_user, db)

    # Apply updates — only overwrite fields that are explicitly present
    if name is not None:
        project.name = name
    if description is not None:
        project.description = description
    if visibility is not None:
        project.visibility = visibility

    await db.commit()
    await db.refresh(project)

    logger.info(
        "project.updated",
        project_id=str(project_id),
        user_id=str(current_user.id),
    )

    return JSONResponse(
        {
            "updated": True,
            "id": str(project.id),
            "name": project.name,
        },
        status_code=status.HTTP_200_OK,
    )


# ---------------------------------------------------------------------------
# DELETE /{project_id:uuid}
# ---------------------------------------------------------------------------


@router.delete("/{project_id:uuid}", status_code=status.HTTP_200_OK)
async def delete_project(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> JSONResponse:
    """Delete a project.

    Sets project_id=NULL on all attached query designs (via ON DELETE SET NULL FK).
    The query designs are not deleted, just detached from the project.

    Args:
        project_id: UUID of the project to delete.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        200 JSON with deleted status.

    Raises:
        HTTPException 403: If the user does not have permission to delete this project.
        HTTPException 404: If the project does not exist.
    """
    project = await _verify_project_ownership(project_id, current_user, db)

    project_name = project.name
    await db.delete(project)
    await db.commit()

    logger.info(
        "project.deleted",
        project_id=str(project_id),
        name=project_name,
        user_id=str(current_user.id),
    )

    return JSONResponse(
        {"deleted": True, "redirect": "/projects"},
        status_code=status.HTTP_200_OK,
    )


# ---------------------------------------------------------------------------
# POST /{project_id:uuid}/clone
# ---------------------------------------------------------------------------


@router.post("/{project_id:uuid}/clone")
async def clone_project(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> JSONResponse:
    """Clone a project including all query designs, search terms, and actor lists.

    Creates a deep copy of the project owned by the current user. The clone
    includes source_config, arenas_config, and all attached query designs
    with their search terms and actor list members.

    Args:
        project_id: UUID of the project to clone.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        JSON response with the new project ID and redirect URL.

    Raises:
        HTTPException 404: If the project does not exist.
        HTTPException 403: If the user does not own the project and is not admin.
    """
    # Load the original project with all nested relationships.
    await _verify_project_ownership(project_id, current_user, db)

    stmt = (
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.query_designs)
            .selectinload(QueryDesign.search_terms),
            selectinload(Project.query_designs)
            .selectinload(QueryDesign.actor_lists)
            .selectinload(ActorList.members),
        )
    )
    result = await db.execute(stmt)
    original = result.scalar_one()

    # Determine a unique name, respecting uq_project_owner_name.
    base_name = f"{original.name} (copy)"
    clone_name = base_name
    suffix = 2
    while True:
        exists_stmt = select(
            func.count(Project.id)
        ).where(
            Project.owner_id == current_user.id,
            Project.name == clone_name,
        )
        count = (await db.execute(exists_stmt)).scalar_one()
        if count == 0:
            break
        clone_name = f"{base_name} {suffix}"
        suffix += 1

    # Create the cloned Project.
    clone = Project(
        id=uuid.uuid4(),
        name=clone_name,
        description=original.description,
        visibility="private",
        owner_id=current_user.id,
        source_config=dict(original.source_config) if original.source_config else {},
        arenas_config=dict(original.arenas_config) if original.arenas_config else {},
        comments_config=dict(original.comments_config) if original.comments_config else {},
    )
    db.add(clone)
    await db.flush()

    # Deep-copy each attached QueryDesign with search terms and actor lists.
    for qd in original.query_designs:
        new_qd = QueryDesign(
            owner_id=current_user.id,
            project_id=clone.id,
            name=qd.name,
            description=qd.description,
            visibility="private",
            default_tier=qd.default_tier,
            language=qd.language,
            locale_country=qd.locale_country,
            arenas_config=dict(qd.arenas_config) if qd.arenas_config else {},
            is_active=True,
            parent_design_id=qd.id,
        )
        db.add(new_qd)
        await db.flush()

        for term in qd.search_terms:
            new_term = SearchTerm(
                query_design_id=new_qd.id,
                term=term.term,
                term_type=term.term_type,
                group_id=term.group_id,
                group_label=term.group_label,
                target_arenas=term.target_arenas,
                translations=term.translations,
                is_active=term.is_active,
            )
            db.add(new_term)

        for actor_list in qd.actor_lists:
            new_list = ActorList(
                query_design_id=new_qd.id,
                name=actor_list.name,
                description=actor_list.description,
                created_by=current_user.id,
                sampling_method=actor_list.sampling_method,
            )
            db.add(new_list)
            await db.flush()

            for member in actor_list.members:
                new_member = ActorListMember(
                    actor_list_id=new_list.id,
                    actor_id=member.actor_id,
                    added_by="clone",
                )
                db.add(new_member)

    await db.commit()

    logger.info(
        "project.cloned",
        original_id=str(project_id),
        clone_id=str(clone.id),
        user_id=str(current_user.id),
    )

    return JSONResponse(
        {
            "id": str(clone.id),
            "name": clone.name,
            "redirect": f"/projects/{clone.id}",
        },
        status_code=status.HTTP_201_CREATED,
    )


# ---------------------------------------------------------------------------
# POST /{project_id:uuid}/attach/{design_id:uuid}
# ---------------------------------------------------------------------------


@router.post("/{project_id:uuid}/attach/{design_id:uuid}")
async def attach_query_design(
    project_id: uuid.UUID,
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> JSONResponse:
    """Attach an existing query design to this project.

    The user must own both the project and the query design (or be admin).

    Args:
        project_id: UUID of the project.
        design_id: UUID of the query design to attach.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        JSON response with success status.

    Raises:
        HTTPException 404: If the project or query design does not exist.
        HTTPException 403: If the user does not own both resources.
    """
    project = await _verify_project_ownership(project_id, current_user, db)

    # Verify the query design exists and user owns it
    stmt = select(QueryDesign).where(QueryDesign.id == design_id)
    result = await db.execute(stmt)
    design = result.scalar_one_or_none()

    if design is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query design '{design_id}' not found.",
        )

    # Access control: admins can attach any design, non-admins must own it
    if current_user.role != "admin" and design.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to modify this query design.",
        )

    # Attach the design to the project
    design.project_id = project_id
    await db.commit()

    logger.info(
        "project.attach_design",
        project_id=str(project_id),
        design_id=str(design_id),
        user_id=str(current_user.id),
    )

    return JSONResponse(
        {"attached": True, "design_id": str(design_id)},
        status_code=status.HTTP_200_OK,
    )


# ---------------------------------------------------------------------------
# POST /{project_id:uuid}/detach/{design_id:uuid}
# ---------------------------------------------------------------------------


@router.post("/{project_id:uuid}/detach/{design_id:uuid}")
async def detach_query_design(
    project_id: uuid.UUID,
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> JSONResponse:
    """Detach a query design from this project.

    Sets project_id=NULL on the query design. The design is not deleted.

    Args:
        project_id: UUID of the project.
        design_id: UUID of the query design to detach.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        JSON response with success status.

    Raises:
        HTTPException 404: If the project or query design does not exist.
        HTTPException 403: If the user does not own the project.
    """
    project = await _verify_project_ownership(project_id, current_user, db)

    # Verify the query design exists and is attached to this project
    stmt = select(QueryDesign).where(
        QueryDesign.id == design_id,
        QueryDesign.project_id == project_id,
    )
    result = await db.execute(stmt)
    design = result.scalar_one_or_none()

    if design is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query design '{design_id}' not found in this project.",
        )

    # Detach the design from the project
    design.project_id = None
    await db.commit()

    logger.info(
        "project.detach_design",
        project_id=str(project_id),
        design_id=str(design_id),
        user_id=str(current_user.id),
    )

    return JSONResponse(
        {"detached": True, "design_id": str(design_id)},
        status_code=status.HTTP_200_OK,
    )


# ---------------------------------------------------------------------------
# GET /{project_id:uuid}/source-config
# ---------------------------------------------------------------------------


@router.get("/{project_id:uuid}/source-config")
async def get_source_config(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> JSONResponse:
    """Return the full source_config for a project.

    Args:
        project_id: UUID of the project.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        JSON response with the source_config dict.
    """
    project = await _verify_project_ownership(project_id, current_user, db)
    return JSONResponse(
        project.source_config or {},
        status_code=status.HTTP_200_OK,
    )


# ---------------------------------------------------------------------------
# PATCH /{project_id:uuid}/source-config/{arena_name}
# ---------------------------------------------------------------------------


@router.patch("/{project_id:uuid}/source-config/{arena_name}")
async def patch_source_config(
    project_id: uuid.UUID,
    arena_name: str,
    payload: Annotated[dict, Body()],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> JSONResponse:
    """Deep-merge source list entries into ``project.source_config[arena_name]``.

    The request body is a JSON object of key-value pairs (e.g.
    ``{"custom_feeds": ["https://..."]}``) to merge into the arena section.

    Args:
        project_id: UUID of the project.
        arena_name: Arena identifier (e.g. ``"rss"``, ``"facebook"``).
        payload: Dict of key-value pairs to merge.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        JSON response with the updated arena section.
    """
    if not arena_name or not arena_name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="arena_name must not be empty.",
        )
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must be a non-empty JSON object.",
        )

    project = await _verify_project_ownership(project_id, current_user, db)

    current_config: dict = dict(project.source_config) if project.source_config else {}
    existing_section: dict = dict(current_config.get(arena_name) or {})
    existing_section.update(payload)
    current_config[arena_name] = existing_section

    project.source_config = current_config
    await db.commit()

    logger.info(
        "project.source_config_patched",
        project_id=str(project_id),
        arena_name=arena_name,
        keys=list(payload.keys()),
    )
    return JSONResponse(
        {"arena_name": arena_name, "source_config_section": existing_section},
        status_code=status.HTTP_200_OK,
    )


# ---------------------------------------------------------------------------
# GET /{project_id:uuid}/arenas-config
# ---------------------------------------------------------------------------


@router.get("/{project_id:uuid}/arenas-config")
async def get_arenas_config(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> JSONResponse:
    """Return the project-level arenas_config.

    Args:
        project_id: UUID of the project.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        JSON response with the arenas_config dict.
    """
    project = await _verify_project_ownership(project_id, current_user, db)
    return JSONResponse(
        project.arenas_config or {},
        status_code=status.HTTP_200_OK,
    )


# ---------------------------------------------------------------------------
# POST /{project_id:uuid}/arenas-config
# ---------------------------------------------------------------------------


class _ArenasConfigPayload(BaseModel):
    """Payload for updating project-level arena enable/disable config."""

    arenas: list[dict] = []


@router.post("/{project_id:uuid}/arenas-config")
async def save_arenas_config(
    project_id: uuid.UUID,
    payload: Annotated[_ArenasConfigPayload, Body()],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> JSONResponse:
    """Save the project-level arenas_config (full replace).

    Accepts ``{"arenas": [{"id": "tiktok", "enabled": true}, ...]}``
    and writes to ``project.arenas_config``.  When the list is empty,
    all QD-enabled arenas pass through (backward compatible).

    Args:
        project_id: UUID of the project.
        payload: Arena config payload with a list of arena entries.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        JSON response with the saved arenas_config.
    """
    project = await _verify_project_ownership(project_id, current_user, db)

    project.arenas_config = {"arenas": payload.arenas}
    await db.commit()

    logger.info(
        "project.arenas_config_saved",
        project_id=str(project_id),
        arena_count=len(payload.arenas),
    )
    return JSONResponse(
        project.arenas_config,
        status_code=status.HTTP_200_OK,
    )


# ---------------------------------------------------------------------------
# GET /{project_id:uuid}/comments-config
# ---------------------------------------------------------------------------


@router.get("/{project_id:uuid}/comments-config")
async def get_comments_config(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> JSONResponse:
    """Return the full comments_config for a project.

    Args:
        project_id: UUID of the project.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        JSON response with the comments_config dict.
    """
    project = await _verify_project_ownership(project_id, current_user, db)
    return JSONResponse(
        project.comments_config or {},
        status_code=status.HTTP_200_OK,
    )


# ---------------------------------------------------------------------------
# PATCH /{project_id:uuid}/comments-config/{platform_name}
# ---------------------------------------------------------------------------

_VALID_COMMENT_MODES = {"search_terms", "source_list_actors", "post_urls"}

_COMMENT_CAPABLE_PLATFORMS = {
    "reddit", "bluesky", "youtube", "tiktok", "facebook", "instagram",
}


@router.patch("/{project_id:uuid}/comments-config/{platform_name}")
async def patch_comments_config(
    project_id: uuid.UUID,
    platform_name: str,
    payload: Annotated[dict, Body()],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> JSONResponse:
    """Deep-merge comment settings into ``project.comments_config[platform_name]``.

    Validates that the platform supports comments, the mode is valid, and
    mode-specific inputs are well-formed.

    Args:
        project_id: UUID of the project.
        platform_name: Platform identifier (e.g. ``"reddit"``, ``"bluesky"``).
        payload: Dict of settings to merge (e.g. ``{"enabled": true, "mode": "search_terms"}``).
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        JSON response with the updated platform section.
    """
    if platform_name not in _COMMENT_CAPABLE_PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Platform '{platform_name}' does not support comment collection. "
                f"Supported: {sorted(_COMMENT_CAPABLE_PLATFORMS)}"
            ),
        )
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must be a non-empty JSON object.",
        )

    # Validate mode if provided
    mode = payload.get("mode")
    if mode is not None and mode not in _VALID_COMMENT_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid mode '{mode}'. Must be one of: {sorted(_VALID_COMMENT_MODES)}",
        )

    # Validate post_urls format if provided
    post_urls = payload.get("post_urls")
    if post_urls is not None:
        if not isinstance(post_urls, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="post_urls must be a list of URL strings.",
            )
        for url in post_urls:
            if not isinstance(url, str) or not url.startswith("http"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid URL in post_urls: {url!r}",
                )

    project = await _verify_project_ownership(project_id, current_user, db)

    current_config: dict = dict(project.comments_config) if project.comments_config else {}
    existing_section: dict = dict(current_config.get(platform_name) or {})
    existing_section.update(payload)
    current_config[platform_name] = existing_section

    project.comments_config = current_config
    await db.commit()

    logger.info(
        "project.comments_config_patched",
        project_id=str(project_id),
        platform=platform_name,
        keys=list(payload.keys()),
    )
    return JSONResponse(
        {"platform": platform_name, "comments_config_section": existing_section},
        status_code=status.HTTP_200_OK,
    )


# ---------------------------------------------------------------------------
# DELETE /{project_id:uuid}/comments-config/{platform_name}
# ---------------------------------------------------------------------------


@router.delete("/{project_id:uuid}/comments-config/{platform_name}")
async def delete_comments_config(
    project_id: uuid.UUID,
    platform_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> JSONResponse:
    """Remove comment configuration for a specific platform.

    Args:
        project_id: UUID of the project.
        platform_name: Platform identifier to remove.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        JSON response confirming deletion.
    """
    project = await _verify_project_ownership(project_id, current_user, db)

    current_config: dict = dict(project.comments_config) if project.comments_config else {}
    if platform_name not in current_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No comment config for platform '{platform_name}'.",
        )

    del current_config[platform_name]
    project.comments_config = current_config
    await db.commit()

    logger.info(
        "project.comments_config_deleted",
        project_id=str(project_id),
        platform=platform_name,
    )
    return JSONResponse(
        {"deleted": True, "platform": platform_name},
        status_code=status.HTTP_200_OK,
    )
