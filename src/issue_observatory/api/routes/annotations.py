"""Content annotation CRUD routes.

Provides endpoints for researchers to attach qualitative coding decisions
(stance, frame, relevance, notes, tags) to individual content records.

Annotation ownership:
    - Each annotation is scoped to the researcher who created it
      (stored in ``created_by``).
    - Researchers can only read and modify their own annotations.
    - Admins can read all annotations for a given record.

Routes:
    GET    /annotations/{record_id:uuid}  — get the current user's annotation for
                                       a content record (200 with data, or 200
                                       with null body if not yet annotated).
    POST   /annotations/{record_id:uuid}  — create or upsert the current user's
                                       annotation for a content record.
    DELETE /annotations/{record_id:uuid}  — delete the current user's annotation
                                       for a content record.

All routes require authentication (``get_current_active_user``).

The ``published_at`` query / body parameter is required because
``content_records`` is range-partitioned on ``published_at``.  The value is
stored in ``content_published_at`` and forms part of the unique constraint
that identifies a specific annotation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.api.dependencies import get_current_active_user, ownership_guard
from issue_observatory.core.database import get_db
from issue_observatory.core.models.annotations import CodebookEntry, ContentAnnotation
from issue_observatory.core.models.users import User

logger = structlog.get_logger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Valid stance vocabulary
# ---------------------------------------------------------------------------

_VALID_STANCES = frozenset(
    {"positive", "negative", "neutral", "contested", "irrelevant"}
)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class AnnotationUpsertBody(BaseModel):
    """Request body for POST /annotations/{record_id:uuid}.

    All coding fields are optional so that a researcher can save a partial
    annotation and return later to complete it.

    Attributes:
        published_at: ISO 8601 timestamp matching the content record's
            ``published_at``.  Required to locate the correct partition.
        stance: Stance label.  One of "positive", "negative", "neutral",
            "contested", "irrelevant".  None to leave unset.
        frame: Free-text frame label (e.g. "economic", "environmental").
            Mutually exclusive with ``codebook_entry_id`` for frame coding.
        codebook_entry_id: Optional UUID of a codebook entry to use for
            structured coding. When provided, the codebook entry's ``code``
            is automatically populated into the annotation's ``frame`` field.
            This enforces vocabulary consistency. Mutually exclusive with
            free-text ``frame``.
        is_relevant: Relevance flag.  True = relevant, False = irrelevant,
            None = not yet coded.
        notes: Free-text annotation notes.
        tags: List of researcher-defined string tags.
        collection_run_id: Optional UUID of a collection run for context.
        query_design_id: Optional UUID of a query design for context.
    """

    published_at: datetime
    stance: Optional[str] = Field(default=None, max_length=20)
    frame: Optional[str] = Field(default=None, max_length=200)
    codebook_entry_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Codebook entry to use for structured coding (populates frame field)",
    )
    is_relevant: Optional[bool] = None
    notes: Optional[str] = None
    tags: Optional[list[str]] = None
    collection_run_id: Optional[uuid.UUID] = None
    query_design_id: Optional[uuid.UUID] = None


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------


def _annotation_to_dict(annotation: ContentAnnotation) -> dict[str, Any]:
    """Serialise a ``ContentAnnotation`` ORM instance to a JSON-safe dict.

    All UUID fields are returned as strings.  Timestamps are ISO 8601 strings.

    Args:
        annotation: An ORM instance loaded from the database.

    Returns:
        Dict with string keys suitable for a JSON response.
    """
    pub = annotation.content_published_at
    created = annotation.created_at
    updated = annotation.updated_at

    return {
        "id": str(annotation.id),
        "created_by": str(annotation.created_by) if annotation.created_by else None,
        "content_record_id": str(annotation.content_record_id),
        "content_published_at": pub.isoformat() if pub else None,
        "stance": annotation.stance,
        "frame": annotation.frame,
        "is_relevant": annotation.is_relevant,
        "notes": annotation.notes,
        "collection_run_id": (
            str(annotation.collection_run_id) if annotation.collection_run_id else None
        ),
        "query_design_id": (
            str(annotation.query_design_id) if annotation.query_design_id else None
        ),
        "tags": annotation.tags or [],
        "created_at": created.isoformat() if created else None,
        "updated_at": updated.isoformat() if updated else None,
    }


# ---------------------------------------------------------------------------
# GET /annotations/{record_id:uuid}
# ---------------------------------------------------------------------------


@router.get("/{record_id:uuid}")
async def get_annotation(
    record_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    published_at: datetime = Query(
        ...,
        description=(
            "ISO 8601 timestamp matching the content record's published_at.  "
            "Required because content_records is partitioned on published_at."
        ),
    ),
) -> JSONResponse:
    """Return the current user's annotation for a content record.

    Admins can retrieve any annotation for the given record by passing an
    optional ``user_id`` filter (future enhancement).  Currently, both
    researchers and admins retrieve only their own annotation.

    Args:
        record_id: UUID of the target content record.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        published_at: The ``published_at`` timestamp of the content record
            (required for partition routing).

    Returns:
        200 JSON with the annotation dict, or 200 with ``{"annotation": null}``
        if the current user has not yet annotated this record.
    """
    stmt = select(ContentAnnotation).where(
        ContentAnnotation.content_record_id == record_id,
        ContentAnnotation.created_by == current_user.id,
        ContentAnnotation.content_published_at == published_at,
    )

    result = await db.execute(stmt)
    annotation = result.scalar_one_or_none()

    if annotation is None:
        logger.debug(
            "annotation.not_found",
            record_id=str(record_id),
            user_id=str(current_user.id),
        )
        return JSONResponse({"annotation": None}, status_code=status.HTTP_200_OK)

    logger.debug(
        "annotation.retrieved",
        annotation_id=str(annotation.id),
        record_id=str(record_id),
        user_id=str(current_user.id),
    )

    return JSONResponse(
        {"annotation": _annotation_to_dict(annotation)},
        status_code=status.HTTP_200_OK,
    )


# ---------------------------------------------------------------------------
# POST /annotations/{record_id:uuid}
# ---------------------------------------------------------------------------


@router.post("/{record_id:uuid}", status_code=status.HTTP_200_OK)
async def upsert_annotation(
    record_id: uuid.UUID,
    body: AnnotationUpsertBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> JSONResponse:
    """Create or update the current user's annotation for a content record.

    Implements upsert semantics: if no annotation exists for the
    (current_user, record_id, published_at) triplet, a new row is inserted.
    If one already exists, its coding fields are updated in place.

    Codebook integration:
        If ``codebook_entry_id`` is provided, the endpoint fetches the
        corresponding codebook entry and uses its ``code`` to populate the
        annotation's ``frame`` field. This enforces vocabulary consistency.
        The ``frame`` and ``codebook_entry_id`` fields are mutually exclusive.

    Args:
        record_id: UUID of the target content record.
        body: Annotation fields to set.  ``published_at`` is required;
            all coding fields are optional.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        200 JSON with the saved annotation dict.

    Raises:
        HTTPException 400: If the ``stance`` value is not one of the allowed
            vocabulary terms, or if both ``frame`` and ``codebook_entry_id``
            are provided simultaneously.
        HTTPException 404: If ``codebook_entry_id`` is provided but does not
            exist or the user lacks access to it.
    """
    # Validate stance vocabulary at the application layer.
    if body.stance is not None and body.stance not in _VALID_STANCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid stance {body.stance!r}.  "
                f"Must be one of: {', '.join(sorted(_VALID_STANCES))}."
            ),
        )

    # Validate mutual exclusivity of frame and codebook_entry_id
    if body.frame is not None and body.codebook_entry_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot provide both 'frame' and 'codebook_entry_id'. Use one or the other.",
        )

    # Resolve codebook entry if provided
    resolved_frame = body.frame
    if body.codebook_entry_id is not None:
        codebook_stmt = select(CodebookEntry).where(
            CodebookEntry.id == body.codebook_entry_id
        )
        codebook_result = await db.execute(codebook_stmt)
        codebook_entry = codebook_result.scalar_one_or_none()

        if codebook_entry is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Codebook entry '{body.codebook_entry_id}' not found.",
            )

        # Access control: user must have access to this codebook entry
        # (either it's global or they own the associated query design)
        if codebook_entry.query_design_id is not None:
            if current_user.role != "admin" and codebook_entry.created_by != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Codebook entry '{body.codebook_entry_id}' not found.",
                )

        resolved_frame = codebook_entry.code

        logger.debug(
            "annotation.codebook_resolved",
            codebook_entry_id=str(body.codebook_entry_id),
            resolved_frame=resolved_frame,
        )

    # Normalise the published_at to UTC-aware before storing.
    published_at = body.published_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    # Check for an existing annotation to determine insert vs. update.
    stmt = select(ContentAnnotation).where(
        ContentAnnotation.content_record_id == record_id,
        ContentAnnotation.created_by == current_user.id,
        ContentAnnotation.content_published_at == published_at,
    )
    result = await db.execute(stmt)
    annotation = result.scalar_one_or_none()

    if annotation is None:
        # Insert new annotation.
        annotation = ContentAnnotation(
            id=uuid.uuid4(),
            created_by=current_user.id,
            content_record_id=record_id,
            content_published_at=published_at,
            stance=body.stance,
            frame=resolved_frame,  # Use resolved frame from codebook if provided
            is_relevant=body.is_relevant,
            notes=body.notes,
            collection_run_id=body.collection_run_id,
            query_design_id=body.query_design_id,
            tags=body.tags,
        )
        db.add(annotation)
        log_event = "annotation.created"
    else:
        # Update existing annotation — only overwrite fields that are
        # explicitly present in the request body (not absent = no change).
        annotation.stance = body.stance
        annotation.frame = resolved_frame  # Use resolved frame from codebook if provided
        annotation.is_relevant = body.is_relevant
        annotation.notes = body.notes
        annotation.collection_run_id = body.collection_run_id
        annotation.query_design_id = body.query_design_id
        annotation.tags = body.tags
        log_event = "annotation.updated"

    await db.commit()
    await db.refresh(annotation)

    logger.info(
        log_event,
        annotation_id=str(annotation.id),
        record_id=str(record_id),
        user_id=str(current_user.id),
        stance=body.stance,
    )

    return JSONResponse(
        {"annotation": _annotation_to_dict(annotation)},
        status_code=status.HTTP_200_OK,
    )


# ---------------------------------------------------------------------------
# DELETE /annotations/{record_id:uuid}
# ---------------------------------------------------------------------------


@router.delete("/{record_id:uuid}", status_code=status.HTTP_200_OK)
async def delete_annotation(
    record_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    published_at: datetime = Query(
        ...,
        description="ISO 8601 timestamp matching the content record's published_at.",
    ),
) -> JSONResponse:
    """Delete the current user's annotation for a content record.

    Researchers may only delete their own annotations.  Admins may delete
    any annotation — the ``ownership_guard`` helper is called with the
    annotation's ``created_by`` field to enforce this.

    Args:
        record_id: UUID of the target content record.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        published_at: The ``published_at`` timestamp of the content record
            (required for partition routing).

    Returns:
        200 JSON ``{"deleted": true}`` on success.

    Raises:
        HTTPException 404: If no annotation exists for this record and user.
        HTTPException 403: If the current user does not own the annotation
            and is not an admin.
    """
    stmt = select(ContentAnnotation).where(
        ContentAnnotation.content_record_id == record_id,
        ContentAnnotation.content_published_at == published_at,
    )

    # Admins can delete any annotation; researchers are scoped to their own.
    if current_user.role != "admin":
        stmt = stmt.where(ContentAnnotation.created_by == current_user.id)

    result = await db.execute(stmt)
    annotation = result.scalar_one_or_none()

    if annotation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No annotation found for record '{record_id}' "
                f"by the current user."
            ),
        )

    # For the admin path, enforce ownership guard as a belt-and-suspenders check.
    if current_user.role != "admin" and annotation.created_by is not None:
        ownership_guard(annotation.created_by, current_user)

    annotation_id = str(annotation.id)
    await db.delete(annotation)
    await db.commit()

    logger.info(
        "annotation.deleted",
        annotation_id=annotation_id,
        record_id=str(record_id),
        user_id=str(current_user.id),
    )

    return JSONResponse({"deleted": True}, status_code=status.HTTP_200_OK)
