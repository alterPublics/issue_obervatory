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
from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.core.database import get_db
from issue_observatory.core.models.project import Project
from issue_observatory.core.models.query_design import QueryDesign
from issue_observatory.core.models.users import User
from issue_observatory.core.schemas.project import (
    ProjectCreate,
    ProjectListResponse,
    ProjectRead,
    ProjectUpdate,
)

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
            latest_run = max(design.collection_runs, key=lambda r: r.started_at)

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
