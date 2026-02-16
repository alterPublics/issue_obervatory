"""Collection run management routes.

Launches, monitors, and cancels collection runs spawned from query designs.

All routes are owner-scoped: users can only operate on runs they initiated.
Admin users bypass the ownership check.

Routes:
    GET  /collections/              — list runs initiated by the current user
    POST /collections/              — create and start a collection run
    GET  /collections/{run_id}      — run detail with per-task statuses
    POST /collections/{run_id}/cancel — cancel a running collection
    GET  /collections/{run_id}/stream — SSE live status (stub, returns 501)
    POST /collections/estimate      — pre-flight credit estimate (non-destructive)
"""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from issue_observatory.api.dependencies import (
    PaginationParams,
    get_current_active_user,
    get_pagination,
    ownership_guard,
)
from issue_observatory.core.database import get_db
from issue_observatory.core.models.collection import CollectionRun
from issue_observatory.core.models.query_design import QueryDesign
from issue_observatory.core.models.users import User
from issue_observatory.core.schemas.collection import (
    CollectionRunCreate,
    CollectionRunRead,
    CreditEstimateRequest,
    CreditEstimateResponse,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _get_run_or_404(
    run_id: uuid.UUID,
    db: AsyncSession,
    *,
    load_tasks: bool = False,
) -> CollectionRun:
    """Fetch a CollectionRun by primary key or raise HTTP 404.

    Args:
        run_id: UUID of the collection run to load.
        db: Active async database session.
        load_tasks: When ``True``, eagerly load the ``tasks`` relationship
            so the detail schema can serialise per-arena task statuses.

    Returns:
        The ``CollectionRun`` ORM instance.

    Raises:
        HTTPException 404: If no run with ``run_id`` exists.
    """
    stmt = select(CollectionRun).where(CollectionRun.id == run_id)
    if load_tasks:
        stmt = stmt.options(selectinload(CollectionRun.tasks))
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection run '{run_id}' not found.",
        )
    return run


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[CollectionRunRead])
async def list_collection_runs(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    pagination: Annotated[PaginationParams, Depends(get_pagination)],
    status_filter: Optional[str] = None,
    query_design_id: Optional[uuid.UUID] = None,
) -> list[CollectionRun]:
    """List collection runs initiated by the current user.

    Results are ordered by run start time descending (newest first) and
    are cursor-paginated by UUID.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        pagination: Cursor and page-size parameters from query string.
        status_filter: Optional filter on run status (``'pending'``,
            ``'running'``, ``'completed'``, ``'failed'``).
        query_design_id: Optional filter to show runs for a specific
            query design.

    Returns:
        A list of ``CollectionRunRead`` dicts for runs initiated by the caller.
    """
    stmt = (
        select(CollectionRun)
        .where(CollectionRun.initiated_by == current_user.id)
        .order_by(CollectionRun.id.desc())
        .limit(pagination.page_size)
    )

    if status_filter is not None:
        stmt = stmt.where(CollectionRun.status == status_filter)

    if query_design_id is not None:
        stmt = stmt.where(CollectionRun.query_design_id == query_design_id)

    if pagination.cursor:
        try:
            cursor_id = uuid.UUID(pagination.cursor)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="cursor must be a valid UUID.",
            ) from exc
        stmt = stmt.where(CollectionRun.id < cursor_id)

    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Create / launch
# ---------------------------------------------------------------------------


@router.post("/", response_model=CollectionRunRead, status_code=status.HTTP_201_CREATED)
async def create_collection_run(
    payload: CollectionRunCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectionRun:
    """Create and enqueue a new collection run.

    Validates that the referenced query design exists and is owned by the
    current user, then creates a ``CollectionRun`` record in ``'pending'``
    status.  Celery task dispatch is deferred to the collection orchestration
    layer (Task 0.8 / credit service integration).

    Args:
        payload: Validated ``CollectionRunCreate`` request body.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The newly created ``CollectionRunRead``.

    Raises:
        HTTPException 404: If the query design does not exist.
        HTTPException 403: If the caller does not own the query design.
    """
    # Verify the query design exists and is owned by this user
    qd_result = await db.execute(
        select(QueryDesign).where(QueryDesign.id == payload.query_design_id)
    )
    query_design = qd_result.scalar_one_or_none()
    if query_design is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query design '{payload.query_design_id}' not found.",
        )
    ownership_guard(query_design.owner_id, current_user)

    run = CollectionRun(
        query_design_id=payload.query_design_id,
        initiated_by=current_user.id,
        mode=payload.mode,
        tier=payload.tier,
        status="pending",
        date_from=payload.date_from,
        date_to=payload.date_to,
        arenas_config=payload.arenas_config,
        estimated_credits=0,
        credits_spent=0,
        records_collected=0,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    logger.info(
        "collection_run_created",
        run_id=str(run.id),
        mode=run.mode,
        query_design_id=str(payload.query_design_id),
        user_id=str(current_user.id),
    )
    return run


# ---------------------------------------------------------------------------
# Credit estimate (pre-flight, non-destructive)
# Must be declared before /{run_id} parametric routes so FastAPI matches
# the literal path segment 'estimate' before treating it as a run_id.
# ---------------------------------------------------------------------------


@router.post("/estimate", response_model=CreditEstimateResponse)
async def estimate_collection_credits(
    payload: CreditEstimateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CreditEstimateResponse:
    """Calculate a pre-flight credit cost estimate for a proposed collection run.

    This endpoint is non-destructive — no credits are reserved and no run
    is created.  It is intended to be called from the collection launcher UI
    while the user configures the run parameters.

    The stub implementation returns zero credits for all arenas.  The full
    implementation (Task 0.8 / CreditService) will compute per-arena cost
    based on the tier, date range, and estimated result volume.

    Args:
        payload: Validated ``CreditEstimateRequest`` body.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        A ``CreditEstimateResponse`` with total and per-arena credit estimates.

    Raises:
        HTTPException 404: If the query design does not exist.
        HTTPException 403: If the caller does not own the query design.
    """
    qd_result = await db.execute(
        select(QueryDesign).where(QueryDesign.id == payload.query_design_id)
    )
    query_design = qd_result.scalar_one_or_none()
    if query_design is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query design '{payload.query_design_id}' not found.",
        )
    ownership_guard(query_design.owner_id, current_user)

    # Stub: CreditService integration deferred to Task 0.8.
    # Return a zero-credit estimate so the UI renders without error.
    return CreditEstimateResponse(
        total_credits=0,
        available_credits=0,
        can_run=True,
        per_arena={},
    )


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


@router.get("/{run_id}", response_model=CollectionRunRead)
async def get_collection_run(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectionRun:
    """Retrieve a collection run with its per-arena task statuses.

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The ``CollectionRunRead`` including task statuses.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the caller did not initiate the run (and is not admin).
    """
    run = await _get_run_or_404(run_id, db, load_tasks=True)
    ownership_guard(run.initiated_by, current_user)
    return run


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


@router.post("/{run_id}/cancel", response_model=CollectionRunRead)
async def cancel_collection_run(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectionRun:
    """Cancel a pending or running collection run.

    Sets the run status to ``'failed'`` if the run has not yet reached a
    terminal state.  Celery task revocation is handled by the orchestration
    layer (Task 0.8).  Runs already in ``'completed'`` or ``'failed'`` state
    are rejected with HTTP 409.

    Args:
        run_id: UUID of the collection run to cancel.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The updated ``CollectionRunRead`` with status ``'failed'``.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the caller did not initiate the run (and is not admin).
        HTTPException 409: If the run is already in a terminal state.
    """
    run = await _get_run_or_404(run_id, db)
    ownership_guard(run.initiated_by, current_user)

    if run.status in ("completed", "failed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot cancel a run with status '{run.status}'. "
                "Only 'pending' and 'running' runs can be cancelled."
            ),
        )

    run.status = "failed"
    run.error_log = "Cancelled by user."
    await db.commit()
    await db.refresh(run)

    logger.info(
        "collection_run_cancelled",
        run_id=str(run_id),
        user_id=str(current_user.id),
    )
    return run


# ---------------------------------------------------------------------------
# SSE stream (stub)
# ---------------------------------------------------------------------------


@router.get("/{run_id}/stream")
async def stream_collection_run(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    """Stream live collection run status via Server-Sent Events.

    This endpoint is a stub.  The full SSE implementation (Task 1.15) will
    emit per-arena task row updates using ``hx-swap-oob`` and close the
    connection with a ``run_complete`` event when the run reaches a terminal
    state.

    Args:
        run_id: UUID of the collection run to stream.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Raises:
        HTTPException 501: Always — endpoint not yet implemented.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="SSE streaming is not yet implemented. See Task 1.15.",
    )

