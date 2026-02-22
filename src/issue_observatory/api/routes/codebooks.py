"""Annotation codebook CRUD routes.

Provides endpoints for researchers to define and manage structured qualitative
coding schemes (codebooks) for content annotation. Codebook entries define a
controlled vocabulary of codes with labels, descriptions, and optional categories.

Codebook scoping:
    - Query-design-scoped: Each codebook entry can be scoped to a specific
      query design (query_design_id NOT NULL). Researchers can only manage
      codebooks for query designs they own.
    - Global codebooks: Entries with query_design_id=NULL are visible to all
      researchers but can only be created/modified by admins.

Ownership and access control:
    - Non-admin users can only create/modify/delete codebook entries for
      query designs they own.
    - Admins can manage all codebook entries including global entries.
    - All users can read global codebook entries.

Routes:
    GET    /codebooks                      — list codebooks (filterable by query_design_id)
    GET    /codebooks/{codebook_id:uuid}        — get single codebook entry
    POST   /codebooks                      — create new codebook entry
    PATCH  /codebooks/{codebook_id:uuid}        — update codebook entry
    DELETE /codebooks/{codebook_id:uuid}        — delete codebook entry
    GET    /query-designs/{design_id}/codebook — convenience: get all entries for a design

Deletion policy:
    When a codebook entry is deleted, annotations that reference it by code are
    NOT automatically deleted. They become "orphaned" — the code string remains
    in the annotation but no longer has a codebook entry. This preserves annotation
    data while allowing codebook evolution.

BLOCKING DEPENDENCY:
    This module requires a ``CodebookEntry`` model to be created by the DB Engineer
    in ``core/models/annotations.py`` before these routes can function. See
    ``core/schemas/codebook.py`` for the required model schema.

    Once the model exists, it must be imported in this module and added to
    ``core/models/__init__.py`` for SQLAlchemy discovery.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.api.dependencies import get_current_active_user, ownership_guard
from issue_observatory.core.database import get_db
from issue_observatory.core.models.annotations import CodebookEntry
from issue_observatory.core.models.query_design import QueryDesign
from issue_observatory.core.models.users import User
from issue_observatory.core.schemas.codebook import (
    CodebookEntryCreate,
    CodebookEntryRead,
    CodebookEntryUpdate,
    CodebookListResponse,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper: Check query design ownership
# ---------------------------------------------------------------------------


async def _verify_design_ownership(
    design_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
) -> None:
    """Verify that the current user owns the given query design.

    Admins bypass this check. Non-admin users must own the design.

    Args:
        design_id: UUID of the query design to check.
        current_user: The authenticated user making the request.
        db: Async database session.

    Raises:
        HTTPException 404: If the query design does not exist.
        HTTPException 403: If the user does not own the design and is not admin.
    """
    if current_user.role == "admin":
        return  # Admins can manage all codebooks

    stmt = select(QueryDesign).where(QueryDesign.id == design_id)
    result = await db.execute(stmt)
    design = result.scalar_one_or_none()

    if design is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query design '{design_id}' not found.",
        )

    ownership_guard(design.created_by, current_user)


# ---------------------------------------------------------------------------
# GET /codebooks
# ---------------------------------------------------------------------------


@router.get("/", response_model=CodebookListResponse)
async def list_codebooks(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    query_design_id: Optional[uuid.UUID] = Query(
        default=None,
        description="Filter to codebook entries for a specific query design. "
        "Omit to see all entries the user has access to (owned + global).",
    ),
) -> CodebookListResponse:
    """List codebook entries accessible to the current user.

    Non-admin users see:
    - Global entries (query_design_id=NULL)
    - Entries for query designs they own
    - Optionally filtered by a specific query_design_id they own

    Admin users see all codebook entries regardless of ownership.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        query_design_id: Optional filter to a specific query design.

    Returns:
        CodebookListResponse with a list of matching entries and total count.

    Raises:
        HTTPException 403: If a non-admin user tries to filter by a query_design_id
            they do not own.
    """
    stmt = select(CodebookEntry).order_by(CodebookEntry.code)

    if query_design_id is not None:
        # Verify ownership if filtering by design
        await _verify_design_ownership(query_design_id, current_user, db)
        stmt = stmt.where(CodebookEntry.query_design_id == query_design_id)
    elif current_user.role != "admin":
        # Non-admins see global entries + their own design-scoped entries
        stmt = stmt.where(
            (CodebookEntry.query_design_id.is_(None))
            | (CodebookEntry.created_by == current_user.id)
        )

    result = await db.execute(stmt)
    entries = result.scalars().all()

    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    logger.debug(
        "codebook.list",
        user_id=str(current_user.id),
        query_design_id=str(query_design_id) if query_design_id else None,
        count=len(entries),
    )

    return CodebookListResponse(
        entries=[CodebookEntryRead.model_validate(e) for e in entries],
        total=total,
        query_design_id=query_design_id,
    )


# ---------------------------------------------------------------------------
# GET /codebooks/{codebook_id:uuid}
# ---------------------------------------------------------------------------


@router.get("/{codebook_id:uuid}", response_model=CodebookEntryRead)
async def get_codebook_entry(
    codebook_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CodebookEntryRead:
    """Retrieve a single codebook entry by ID.

    Non-admin users can only retrieve:
    - Global entries (query_design_id=NULL)
    - Entries for query designs they own

    Admin users can retrieve any codebook entry.

    Args:
        codebook_id: UUID of the codebook entry to retrieve.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The requested codebook entry.

    Raises:
        HTTPException 404: If the entry does not exist or the user lacks access.
    """
    stmt = select(CodebookEntry).where(CodebookEntry.id == codebook_id)
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()

    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Codebook entry '{codebook_id}' not found.",
        )

    # Access control: admins see all, non-admins see global + owned
    if current_user.role != "admin":
        if entry.query_design_id is not None and entry.created_by != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Codebook entry '{codebook_id}' not found.",
            )

    logger.debug(
        "codebook.retrieved",
        codebook_id=str(codebook_id),
        user_id=str(current_user.id),
    )

    return CodebookEntryRead.model_validate(entry)


# ---------------------------------------------------------------------------
# POST /codebooks
# ---------------------------------------------------------------------------


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=CodebookEntryRead)
async def create_codebook_entry(
    body: CodebookEntryCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CodebookEntryRead:
    """Create a new codebook entry.

    Non-admin users must provide a query_design_id they own. Only admins can
    create global codebook entries (query_design_id=NULL).

    Args:
        body: Codebook entry fields to set.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The newly created codebook entry.

    Raises:
        HTTPException 400: If code uniqueness constraint is violated (duplicate
            code within the same query_design_id scope).
        HTTPException 403: If a non-admin tries to create a global entry or an
            entry for a query design they do not own.
        HTTPException 404: If the specified query_design_id does not exist.
    """
    # Access control: global entries require admin
    if body.query_design_id is None and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can create global codebook entries.",
        )

    # Verify ownership if query_design_id is provided
    if body.query_design_id is not None:
        await _verify_design_ownership(body.query_design_id, current_user, db)

    entry = CodebookEntry(
        id=uuid.uuid4(),
        code=body.code,
        label=body.label,
        description=body.description,
        category=body.category,
        query_design_id=body.query_design_id,
        created_by=current_user.id,
    )
    db.add(entry)

    try:
        await db.commit()
        await db.refresh(entry)
    except IntegrityError as exc:
        await db.rollback()
        logger.warning(
            "codebook.create.duplicate",
            code=body.code,
            query_design_id=str(body.query_design_id) if body.query_design_id else None,
            user_id=str(current_user.id),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"A codebook entry with code '{body.code}' already exists "
                f"in this scope. Codes must be unique within a query design."
            ),
        ) from exc

    logger.info(
        "codebook.created",
        codebook_id=str(entry.id),
        code=body.code,
        query_design_id=str(body.query_design_id) if body.query_design_id else None,
        user_id=str(current_user.id),
    )

    return CodebookEntryRead.model_validate(entry)


# ---------------------------------------------------------------------------
# PATCH /codebooks/{codebook_id:uuid}
# ---------------------------------------------------------------------------


@router.patch("/{codebook_id:uuid}", response_model=CodebookEntryRead)
async def update_codebook_entry(
    codebook_id: uuid.UUID,
    body: CodebookEntryUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CodebookEntryRead:
    """Update an existing codebook entry.

    Non-admin users can only update entries for query designs they own.
    Admin users can update any entry including global entries.

    WARNING: Changing the ``code`` field will orphan any existing annotations
    that reference the old code. Consider the implications before making this change.

    Args:
        codebook_id: UUID of the codebook entry to update.
        body: Fields to update. All fields are optional.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The updated codebook entry.

    Raises:
        HTTPException 400: If code uniqueness constraint is violated.
        HTTPException 403: If the user does not have permission to modify this entry.
        HTTPException 404: If the entry does not exist.
    """
    stmt = select(CodebookEntry).where(CodebookEntry.id == codebook_id)
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()

    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Codebook entry '{codebook_id}' not found.",
        )

    # Access control: admins can update all, non-admins can only update their own
    if current_user.role != "admin":
        if entry.query_design_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can modify global codebook entries.",
            )
        if entry.created_by != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to modify this codebook entry.",
            )

    # Apply updates — only overwrite fields that are explicitly present
    if body.code is not None:
        logger.warning(
            "codebook.code_changed",
            codebook_id=str(codebook_id),
            old_code=entry.code,
            new_code=body.code,
            message="Changing code may orphan existing annotations.",
        )
        entry.code = body.code
    if body.label is not None:
        entry.label = body.label
    if body.description is not None:
        entry.description = body.description
    if body.category is not None:
        entry.category = body.category

    try:
        await db.commit()
        await db.refresh(entry)
    except IntegrityError as exc:
        await db.rollback()
        logger.warning(
            "codebook.update.duplicate",
            codebook_id=str(codebook_id),
            code=body.code,
            user_id=str(current_user.id),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"A codebook entry with code '{body.code}' already exists "
                f"in this scope. Codes must be unique within a query design."
            ),
        ) from exc

    logger.info(
        "codebook.updated",
        codebook_id=str(codebook_id),
        user_id=str(current_user.id),
    )

    return CodebookEntryRead.model_validate(entry)


# ---------------------------------------------------------------------------
# DELETE /codebooks/{codebook_id:uuid}
# ---------------------------------------------------------------------------


@router.delete("/{codebook_id:uuid}", status_code=status.HTTP_200_OK)
async def delete_codebook_entry(
    codebook_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> JSONResponse:
    """Delete a codebook entry.

    Non-admin users can only delete entries for query designs they own.
    Admin users can delete any entry including global entries.

    NOTE: Deleting a codebook entry does NOT cascade delete annotations that
    reference it. Those annotations will become "orphaned" — the code string
    remains in the annotation but no longer has a codebook definition.

    Args:
        codebook_id: UUID of the codebook entry to delete.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        200 JSON ``{"deleted": true}`` on success.

    Raises:
        HTTPException 403: If the user does not have permission to delete this entry.
        HTTPException 404: If the entry does not exist.
    """
    stmt = select(CodebookEntry).where(CodebookEntry.id == codebook_id)
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()

    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Codebook entry '{codebook_id}' not found.",
        )

    # Access control: admins can delete all, non-admins can only delete their own
    if current_user.role != "admin":
        if entry.query_design_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can delete global codebook entries.",
            )
        if entry.created_by != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete this codebook entry.",
            )

    entry_id = str(entry.id)
    entry_code = entry.code
    await db.delete(entry)
    await db.commit()

    logger.info(
        "codebook.deleted",
        codebook_id=entry_id,
        code=entry_code,
        user_id=str(current_user.id),
    )

    return JSONResponse({"deleted": True}, status_code=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# GET /query-designs/{design_id}/codebook (convenience endpoint)
# ---------------------------------------------------------------------------


@router.get("/query-designs/{design_id}/codebook", response_model=CodebookListResponse)
async def get_design_codebook(
    design_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CodebookListResponse:
    """Retrieve all codebook entries for a specific query design.

    This is a convenience endpoint equivalent to calling
    ``GET /codebooks?query_design_id={design_id}``.

    Includes both design-scoped entries and global entries (query_design_id=NULL)
    so the researcher sees the full vocabulary available for annotating content
    from this query design.

    Args:
        design_id: UUID of the query design.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        CodebookListResponse with all entries for this design plus global entries.

    Raises:
        HTTPException 403: If the user does not own the query design.
        HTTPException 404: If the query design does not exist.
    """
    # Verify ownership
    await _verify_design_ownership(design_id, current_user, db)

    stmt = (
        select(CodebookEntry)
        .where(
            (CodebookEntry.query_design_id == design_id)
            | (CodebookEntry.query_design_id.is_(None))
        )
        .order_by(CodebookEntry.category, CodebookEntry.code)
    )
    result = await db.execute(stmt)
    entries = result.scalars().all()

    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    logger.debug(
        "codebook.design_codebook",
        design_id=str(design_id),
        user_id=str(current_user.id),
        count=len(entries),
    )

    return CodebookListResponse(
        entries=[CodebookEntryRead.model_validate(e) for e in entries],
        total=total,
        query_design_id=design_id,
    )
