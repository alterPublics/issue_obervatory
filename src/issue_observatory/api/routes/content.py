"""Content browser routes.

Provides a read-only API for browsing and inspecting collected content
records stored in the universal ``content_records`` table.

Results are always filtered to the current user's own collection runs.
Records from shared or public query designs are not exposed here unless
the current user's run collected them.

Routes:
    GET /content/       — browse collected content with cursor pagination
    GET /content/{id}   — get a single content record detail
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.api.dependencies import (
    PaginationParams,
    get_current_active_user,
    get_pagination,
)
from issue_observatory.core.database import get_db
from issue_observatory.core.models.collection import CollectionRun
from issue_observatory.core.models.content import UniversalContentRecord
from issue_observatory.core.models.users import User
from issue_observatory.core.schemas.content import ContentRecordRead

logger = structlog.get_logger(__name__)

router = APIRouter()

_MAX_LIMIT = 200


# ---------------------------------------------------------------------------
# List / browse
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[ContentRecordRead])
async def browse_content(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    pagination: Annotated[PaginationParams, Depends(get_pagination)],
    platform: Optional[str] = Query(default=None, description="Filter by platform name."),
    arena: Optional[str] = Query(default=None, description="Filter by arena name."),
    query_design_id: Optional[uuid.UUID] = Query(
        default=None, description="Filter by query design UUID."
    ),
    date_from: Optional[datetime] = Query(
        default=None, description="Filter content published on or after this timestamp."
    ),
    date_to: Optional[datetime] = Query(
        default=None, description="Filter content published on or before this timestamp."
    ),
    search_term: Optional[str] = Query(
        default=None,
        description="Filter records where search_terms_matched contains this term.",
    ),
    language: Optional[str] = Query(
        default=None, description="Filter by ISO 639-1 language code."
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=_MAX_LIMIT,
        description="Number of records to return (max 200).",
    ),
) -> list[UniversalContentRecord]:
    """Browse collected content with optional filters and cursor pagination.

    Results are scoped to content collected by the current user's own
    collection runs.  Records are ordered by ``collected_at`` descending
    (most recently ingested first).

    Query parameters allow narrowing by platform, arena, date range, matched
    search term, and language.  All filters are additive (AND logic).

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        pagination: Cursor and page-size parameters from query string.
        platform: Optional platform filter (e.g. ``'youtube'``).
        arena: Optional arena filter (e.g. ``'social_media'``).
        query_design_id: Optional filter to content from a specific design.
        date_from: Optional lower bound on ``published_at``.
        date_to: Optional upper bound on ``published_at``.
        search_term: Optional filter on ``search_terms_matched`` array membership.
        language: Optional ISO 639-1 language code filter.
        limit: Maximum records to return (1–200, overrides ``page_size`` from
            the shared pagination params for this endpoint).

    Returns:
        A list of ``ContentRecordRead`` dicts matching the applied filters.
    """
    # Sub-query: collect_run IDs that belong to this user
    user_run_ids_subq = (
        select(CollectionRun.id)
        .where(CollectionRun.initiated_by == current_user.id)
        .scalar_subquery()
    )

    stmt = (
        select(UniversalContentRecord)
        .where(UniversalContentRecord.collection_run_id.in_(user_run_ids_subq))
        .order_by(UniversalContentRecord.collected_at.desc())
        .limit(limit)
    )

    if platform is not None:
        stmt = stmt.where(UniversalContentRecord.platform == platform)

    if arena is not None:
        stmt = stmt.where(UniversalContentRecord.arena == arena)

    if query_design_id is not None:
        stmt = stmt.where(UniversalContentRecord.query_design_id == query_design_id)

    if date_from is not None:
        stmt = stmt.where(UniversalContentRecord.published_at >= date_from)

    if date_to is not None:
        stmt = stmt.where(UniversalContentRecord.published_at <= date_to)

    if language is not None:
        stmt = stmt.where(UniversalContentRecord.language == language)

    if search_term is not None:
        # PostgreSQL array containment: search_terms_matched @> ARRAY[search_term]
        stmt = stmt.where(
            UniversalContentRecord.search_terms_matched.contains([search_term])
        )

    if pagination.cursor:
        try:
            cursor_id = uuid.UUID(pagination.cursor)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="cursor must be a valid UUID.",
            ) from exc
        stmt = stmt.where(UniversalContentRecord.id < cursor_id)

    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


@router.get("/{record_id}", response_model=ContentRecordRead)
async def get_content_record(
    record_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UniversalContentRecord:
    """Retrieve a single content record by ID.

    The record must belong to a collection run initiated by the current user.
    Admin users can access any record.

    Args:
        record_id: UUID of the content record.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The ``ContentRecordRead`` for the requested record.

    Raises:
        HTTPException 404: If the record does not exist or is not owned
            by the current user.
    """
    if current_user.role == "admin":
        stmt = select(UniversalContentRecord).where(
            UniversalContentRecord.id == record_id
        )
    else:
        user_run_ids_subq = (
            select(CollectionRun.id)
            .where(CollectionRun.initiated_by == current_user.id)
            .scalar_subquery()
        )
        stmt = select(UniversalContentRecord).where(
            UniversalContentRecord.id == record_id,
            UniversalContentRecord.collection_run_id.in_(user_run_ids_subq),
        )

    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Content record '{record_id}' not found.",
        )

    return record
