"""Collection run management routes.

Launches, monitors, and cancels collection runs spawned from query designs.

All routes are owner-scoped: users can only operate on runs they initiated.
Admin users bypass the ownership check.

Routes:
    GET  /collections/              — list runs initiated by the current user
    POST /collections/              — create and start a collection run
    GET  /collections/{run_id}      — run detail with per-task statuses
    POST /collections/{run_id}/cancel — cancel a running collection
    GET  /collections/{run_id}/stream — SSE live status
    POST /collections/estimate      — pre-flight credit estimate (non-destructive)
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Annotated, AsyncGenerator, Optional

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from issue_observatory.api.dependencies import (
    PaginationParams,
    get_current_active_user,
    get_pagination,
    get_redis,
    ownership_guard,
)
from issue_observatory.core.database import get_db
from issue_observatory.core.email_service import EmailService, get_email_service
from issue_observatory.core.models.collection import CollectionRun, CollectionTask
from issue_observatory.core.models.query_design import QueryDesign
from issue_observatory.core.models.users import User
from issue_observatory.core.schemas.collection import (
    CollectionRunCreate,
    CollectionRunRead,
    CreditEstimateRequest,
    CreditEstimateResponse,
)
from issue_observatory.analysis.alerting import fetch_recent_volume_spikes

from issue_observatory.api.limiter import limiter

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper: template resolver
# ---------------------------------------------------------------------------


def _templates(request: Request) -> Jinja2Templates:
    """Resolve the Jinja2Templates instance from the app state.

    Args:
        request: The incoming HTTP request.

    Returns:
        The app's Jinja2Templates instance.

    Raises:
        RuntimeError: If templates are not configured on app.state.
    """
    templates = request.app.state.templates
    if templates is None:
        raise RuntimeError("Templates not configured on app.state")
    return templates


# ---------------------------------------------------------------------------
# Active count (dashboard polling)
# ---------------------------------------------------------------------------


@router.get("/active-count")
async def get_active_collection_count(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> str:
    """Return an HTML fragment with the count of active collection runs.

    Polls pending and running runs initiated by the current user.  Returns
    a minimal HTML snippet suitable for direct insertion into the dashboard's
    active-runs card via HTMX ``hx-target`` swap.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        HTML fragment string with the active run count.
    """
    stmt = (
        select(func.count(CollectionRun.id))
        .where(
            and_(
                CollectionRun.initiated_by == current_user.id,
                or_(
                    CollectionRun.status == "pending",
                    CollectionRun.status == "running",
                ),
            )
        )
    )
    result = await db.execute(stmt)
    count = result.scalar() or 0

    # Return the same HTML structure as the dashboard's initial placeholder
    # so the swap is smooth.
    return f"""<div id="dashboard-active-runs"
         hx-get="/collections/active-count"
         hx-trigger="every 15s"
         hx-target="#dashboard-active-runs"
         hx-swap="outerHTML">
    <p class="text-2xl font-bold text-gray-900">{count}</p>
    <p class="text-xs text-gray-500 mt-1">Active collection{"s" if count != 1 else ""}</p>
</div>"""


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


@router.get("/")
async def list_collection_runs(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    pagination: Annotated[PaginationParams, Depends(get_pagination)],
    status_filter: Optional[str] = None,
    query_design_id: Optional[uuid.UUID] = None,
    format: Optional[str] = None,
) -> list[CollectionRun] | str:
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
        format: When set to ``"fragment"``, returns an HTML table fragment
            suitable for direct insertion into the dashboard.  Otherwise
            returns JSON list of ``CollectionRunRead`` dicts.

    Returns:
        A list of ``CollectionRunRead`` dicts (JSON response) or an HTML
        fragment (when ``format="fragment"``).
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
    runs = list(result.scalars().all())

    # If format=fragment, render an HTML table for dashboard HTMX consumption
    if format == "fragment":
        if not runs:
            return """<div class="px-6 py-8 text-center text-sm text-gray-500">
    No collection runs yet. <a href="/collections/new" class="text-blue-600 hover:underline">Start your first collection</a>.
</div>"""

        # Build a simple HTML table with run summaries
        rows_html = ""
        for run in runs:
            status_badge_class = {
                "pending": "bg-yellow-100 text-yellow-800",
                "running": "bg-blue-100 text-blue-800",
                "completed": "bg-green-100 text-green-800",
                "failed": "bg-red-100 text-red-800",
                "suspended": "bg-gray-100 text-gray-800",
            }.get(run.status, "bg-gray-100 text-gray-800")

            started_at_str = run.started_at.strftime("%Y-%m-%d %H:%M") if run.started_at else "—"

            rows_html += f"""<tr class="hover:bg-gray-50">
    <td class="px-6 py-3 text-sm">
        <a href="/collections/{run.id}" class="text-blue-600 hover:underline font-medium">
            {run.mode.capitalize()} Collection
        </a>
    </td>
    <td class="px-6 py-3 text-sm">
        <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium {status_badge_class}">
            {run.status.capitalize()}
        </span>
    </td>
    <td class="px-6 py-3 text-sm text-gray-900">{run.records_collected:,}</td>
    <td class="px-6 py-3 text-sm text-gray-500">{started_at_str}</td>
</tr>
"""

        return f"""<table class="min-w-full divide-y divide-gray-200">
    <thead class="bg-gray-50">
        <tr>
            <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Collection</th>
            <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
            <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Records</th>
            <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Started</th>
        </tr>
    </thead>
    <tbody class="bg-white divide-y divide-gray-200">
{rows_html}    </tbody>
</table>
<div class="px-6 py-3 border-t border-gray-200 text-center">
    <a href="/collections" class="text-sm text-blue-600 hover:underline">View all collections →</a>
</div>"""

    # Default: return JSON list of CollectionRunRead
    return runs


# ---------------------------------------------------------------------------
# Create / launch
# ---------------------------------------------------------------------------


@router.post("/", response_model=CollectionRunRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_collection_run(  # type: ignore[misc]
    request: Request,
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

    # -----------------------------------------------------------------------
    # Tier precedence resolution (IP2-022)
    #
    # Tier selection follows a strict three-level hierarchy (highest priority
    # first):
    #
    #   1. Per-arena override in the QUERY DESIGN's ``arenas_config``
    #      (``query_designs.arenas_config``).  These are the researcher's saved
    #      preferences and represent the most specific configuration.
    #
    #   2. Per-arena override in the LAUNCHER REQUEST's ``arenas_config``
    #      (``payload.arenas_config``).  Explicitly provided at launch time
    #      and can supplement arenas not configured in the query design.
    #
    #   3. Global default ``tier`` in the LAUNCHER REQUEST (``payload.tier``).
    #      Applies to any arena not covered by levels 1 or 2.
    #
    # The merged config is stored on ``collection_runs.arenas_config`` as an
    # immutable snapshot so that re-running historical reports is reproducible.
    # -----------------------------------------------------------------------

    # Build the merged arenas_config for the run.
    # Start from the query design's saved preferences (level 1), then apply
    # any launcher-level overrides for arenas not already in the design config
    # (level 2).
    design_arena_config: dict = query_design.arenas_config or {}
    launcher_arena_config: dict = payload.arenas_config or {}

    # Merge: query design config takes precedence; launcher config fills gaps.
    merged_arenas_config: dict = {**launcher_arena_config, **design_arena_config}

    logger.debug(
        "tier_precedence_resolved",
        run_global_tier=payload.tier,
        design_arenas_count=len(design_arena_config),
        launcher_arenas_count=len(launcher_arena_config),
        merged_arenas_count=len(merged_arenas_config),
    )

    # -----------------------------------------------------------------------
    # SB-05: Date range capability check
    #
    # When the user specifies date_from/date_to for a batch collection, check
    # each enabled arena's temporal_mode and warn if any have RECENT or
    # FORWARD_ONLY modes that will not respect the date range.
    # -----------------------------------------------------------------------
    date_range_warnings: list[str] = []
    if payload.mode == "batch" and (payload.date_from or payload.date_to):
        from issue_observatory.arenas.base import TemporalMode
        from issue_observatory.arenas.registry import autodiscover, get_arena

        autodiscover()
        limited_arenas: list[str] = []

        # Check all arenas that are enabled in the merged config
        for platform_name in merged_arenas_config.keys():
            try:
                collector_cls = get_arena(platform_name)
                temporal_mode = getattr(collector_cls, "temporal_mode", None)
                if temporal_mode in (TemporalMode.RECENT, TemporalMode.FORWARD_ONLY):
                    limited_arenas.append(platform_name)
            except KeyError:
                # Arena not registered; skip
                continue

        if limited_arenas:
            date_range_warnings.append(
                f"The following arenas will not respect your date range: {', '.join(limited_arenas)}. "
                "They will return recent/current content only."
            )

    run = CollectionRun(
        query_design_id=payload.query_design_id,
        initiated_by=current_user.id,
        mode=payload.mode,
        # Global default tier — used for arenas not present in merged_arenas_config.
        tier=payload.tier,
        status="pending",
        date_from=payload.date_from,
        date_to=payload.date_to,
        # Immutable snapshot of the merged per-arena config for this run.
        # Per-arena tier overrides in this dict always take precedence over the
        # global ``tier`` field above (enforced by arena orchestration workers).
        arenas_config=merged_arenas_config,
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
        warnings_count=len(date_range_warnings),
    )

    # Build response with warnings
    response = CollectionRunRead.model_validate(run)
    response.warnings = date_range_warnings
    return response


# ---------------------------------------------------------------------------
# Credit estimate (pre-flight, non-destructive)
# Must be declared before /{run_id} parametric routes so FastAPI matches
# the literal path segment 'estimate' before treating it as a run_id.
# ---------------------------------------------------------------------------


@router.post("/estimate")
async def estimate_collection_credits(
    request: Request,
    payload: CreditEstimateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    hx_request: Optional[str] = Header(default=None, alias="HX-Request"),
) -> CreditEstimateResponse | HTMLResponse:
    """Calculate a pre-flight credit cost estimate for a proposed collection run.

    This endpoint is non-destructive — no credits are reserved and no run
    is created.  It is intended to be called from the collection launcher UI
    while the user configures the run parameters.

    Estimates are heuristic-based and may vary from actual costs by ±50%.
    They provide order-of-magnitude accuracy for budget planning.

    SB-14: This endpoint now returns real estimates based on:
    - Number of active search terms in the query design
    - Number of enabled arenas per tier
    - Date range (for batch mode, defaults to 30 days for live mode)
    - Each arena collector's estimate_credits() implementation

    When the ``HX-Request`` header is present, renders the
    ``_fragments/credit_estimate.html`` template fragment. Otherwise returns
    JSON.

    Args:
        request: The incoming HTTP request.
        payload: Validated ``CreditEstimateRequest`` body.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        hx_request: HTMX header; when set, response is HTML.

    Returns:
        A ``CreditEstimateResponse`` with total and per-arena credit estimates
        (JSON), or an HTML fragment when ``hx_request`` is set.

    Raises:
        HTTPException 404: If the query design does not exist.
        HTTPException 403: If the caller does not own the query design.
    """
    from issue_observatory.core.credit_service import CreditService

    # Load query design and verify ownership
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

    # Merge arena config: query design base + launcher override
    merged_arenas_config = {**query_design.arenas_config, **payload.arenas_config}

    # Use CreditService to compute the estimate
    credit_service = CreditService(db)
    estimate = await credit_service.estimate(
        query_design_id=payload.query_design_id,
        tier=payload.tier,
        arenas_config=merged_arenas_config,
        date_from=payload.date_from,
        date_to=payload.date_to,
    )

    # Get user's available credit balance
    balance = await credit_service.get_balance(current_user.id)
    available_credits = balance["available"]

    # Determine if run can proceed
    total_credits = estimate["total_credits"]
    can_run = total_credits <= available_credits

    logger.info(
        "credit_estimate_requested",
        query_design_id=str(payload.query_design_id),
        user_id=str(current_user.id),
        total_credits=total_credits,
        available_credits=available_credits,
        can_run=can_run,
    )

    # When called via HTMX, render the credit_estimate fragment
    if hx_request:
        templates = _templates(request)
        return templates.TemplateResponse(
            "_fragments/credit_estimate.html",
            {
                "request": request,
                "estimate": {
                    "total_credits": total_credits,
                    "available_credits": available_credits,
                    "sufficient": can_run,
                    "per_arena": estimate["per_arena"],
                },
                "error": None,
            },
        )

    # Otherwise return JSON
    return CreditEstimateResponse(
        total_credits=total_credits,
        available_credits=available_credits,
        can_run=can_run,
        per_arena=estimate["per_arena"],
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
    email_svc: Annotated[EmailService, Depends(get_email_service)],
) -> CollectionRun:
    """Cancel a pending or running collection run.

    Sets the run status to ``'failed'`` if the run has not yet reached a
    terminal state.  Celery task revocation is handled by the orchestration
    layer (Task 0.8).  Runs already in ``'completed'`` or ``'failed'`` state
    are rejected with HTTP 409.

    Sends a ``collection_failure`` notification email to the user as a
    fire-and-forget task so the HTTP response is never delayed.

    Args:
        run_id: UUID of the collection run to cancel.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        email_svc: Injected email notification service.

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

    # Fire-and-forget: notify the user that the run was cancelled/failed.
    asyncio.create_task(
        email_svc.send_collection_failure(
            user_email=str(current_user.email),
            run_id=run_id,
            arena="all",
            error="Collection run cancelled by user.",
        )
    )

    # M-05: Publish run_complete event to SSE subscribers
    from issue_observatory.config.settings import get_settings
    from issue_observatory.core.event_bus import publish_run_complete

    settings = get_settings()
    publish_run_complete(
        redis_url=settings.redis_url,
        run_id=str(run_id),
        status="failed",
        records_collected=run.records_collected,
        credits_spent=run.credits_spent,
    )

    return run


# ---------------------------------------------------------------------------
# Suspend / Resume (live tracking runs)
# ---------------------------------------------------------------------------


@router.post("/{run_id}/suspend", response_model=CollectionRunRead)
async def suspend_collection_run(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectionRun:
    """Suspend an active live-tracking collection run.

    Sets ``CollectionRun.status`` to ``'suspended'`` and records
    ``suspended_at`` to the current UTC time.  Only valid on runs with
    ``mode='live'`` and ``status='active'``.

    Args:
        run_id: UUID of the collection run to suspend.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The updated ``CollectionRunRead`` with status ``'suspended'``.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the caller did not initiate the run (and is not admin).
        HTTPException 409: If the run is not a live run in active status.
    """
    from datetime import datetime, timezone  # noqa: PLC0415

    run = await _get_run_or_404(run_id, db)
    ownership_guard(run.initiated_by, current_user)

    if run.mode != "live" or run.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot suspend run with mode='{run.mode}' status='{run.status}'. "
                "Only live runs with status='active' can be suspended."
            ),
        )

    run.status = "suspended"
    run.suspended_at = datetime.now(tz=timezone.utc)
    await db.commit()
    await db.refresh(run)

    logger.info(
        "collection_run_suspended",
        run_id=str(run_id),
        user_id=str(current_user.id),
    )
    return run


@router.post("/{run_id}/resume", response_model=CollectionRunRead)
async def resume_collection_run(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> CollectionRun:
    """Resume a suspended live-tracking collection run.

    Sets ``CollectionRun.status`` back to ``'active'`` and clears
    ``suspended_at``.  Only valid on runs with ``mode='live'`` and
    ``status='suspended'``.

    Args:
        run_id: UUID of the collection run to resume.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The updated ``CollectionRunRead`` with status ``'active'``.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the caller did not initiate the run (and is not admin).
        HTTPException 409: If the run is not suspended.
    """
    run = await _get_run_or_404(run_id, db)
    ownership_guard(run.initiated_by, current_user)

    if run.mode != "live" or run.status != "suspended":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot resume run with mode='{run.mode}' status='{run.status}'. "
                "Only live runs with status='suspended' can be resumed."
            ),
        )

    run.status = "active"
    run.suspended_at = None
    await db.commit()
    await db.refresh(run)

    logger.info(
        "collection_run_resumed",
        run_id=str(run_id),
        user_id=str(current_user.id),
    )
    return run


# ---------------------------------------------------------------------------
# Schedule info (live tracking runs)
# ---------------------------------------------------------------------------

#: Next run time derived from the daily_collection beat entry (hour=0, minute=0,
#: Copenhagen time).  Exposed as a human-readable string.
_DAILY_COLLECTION_NEXT_RUN = "00:00 Copenhagen time"
_DAILY_COLLECTION_TIMEZONE = "Europe/Copenhagen"


@router.get("/{run_id}/schedule")
async def get_collection_schedule(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict:
    """Return schedule information for a live-tracking collection run.

    Derives next-run timing from the ``daily_collection`` Celery Beat entry
    defined in ``workers/beat_schedule.py`` (00:00 Copenhagen time).

    Args:
        run_id: UUID of the collection run.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        A dict with keys:
        - ``mode``: always ``"live"`` for valid requests.
        - ``status``: current run status (``"active"`` or ``"suspended"``).
        - ``next_run_at``: human-readable next-trigger time string.
        - ``timezone``: IANA timezone name for the schedule.
        - ``last_triggered_at``: ``started_at`` of the run, or ``None``.
        - ``suspended_at``: timestamp the run was suspended, or ``None``.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the caller did not initiate the run (and is not admin).
        HTTPException 400: If the run is not a live-tracking run.
    """
    run = await _get_run_or_404(run_id, db)
    ownership_guard(run.initiated_by, current_user)

    if run.mode != "live":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Schedule information is only available for live tracking runs.",
        )

    return {
        "mode": run.mode,
        "status": run.status,
        "next_run_at": _DAILY_COLLECTION_NEXT_RUN,
        "timezone": _DAILY_COLLECTION_TIMEZONE,
        "last_triggered_at": run.started_at.isoformat() if run.started_at else None,
        "suspended_at": run.suspended_at.isoformat() if run.suspended_at else None,
    }


# ---------------------------------------------------------------------------
# Refresh engagement metrics (IP2-035)
# ---------------------------------------------------------------------------


@router.post("/{run_id}/refresh-engagement", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
async def refresh_engagement_metrics_endpoint(
    request: Request,
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, str]:
    """Launch an asynchronous task to refresh engagement metrics for a run.

    Re-fetches current likes, shares, comments, and views counts for all
    content records in the specified collection run. Engagement metrics
    change over time, so this endpoint allows researchers to update
    historical data with fresh counts.

    The refresh task groups records by platform and calls each arena's
    ``refresh_engagement()`` method (if implemented). Arenas that do not
    support metric refresh are skipped silently.

    Only completed runs can be refreshed. The task processes records in
    batches (50 external_ids per API call) to respect rate limits.

    This endpoint is rate-limited to 5 requests per minute per user.

    Args:
        request: The incoming HTTP request (used by rate limiter).
        run_id: UUID of the collection run to refresh.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        Dict with ``task_id`` and ``run_id`` for tracking the refresh task.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the caller did not initiate the run (and is not admin).
        HTTPException 409: If the run is not in 'completed' status.
    """
    run = await _get_run_or_404(run_id, db)
    ownership_guard(run.initiated_by, current_user)

    if run.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot refresh engagement for a run with status '{run.status}'. "
                "Only completed runs can be refreshed."
            ),
        )

    # Launch the Celery task asynchronously
    from issue_observatory.workers.maintenance_tasks import refresh_engagement_metrics

    task = refresh_engagement_metrics.delay(str(run_id))

    logger.info(
        "refresh_engagement_launched",
        run_id=str(run_id),
        task_id=task.id,
        user_id=str(current_user.id),
    )

    return {
        "task_id": task.id,
        "run_id": str(run_id),
        "message": "Engagement metric refresh task launched. This may take several minutes.",
    }


# ---------------------------------------------------------------------------
# Enrichment pipeline trigger (1.4/2.1)
# ---------------------------------------------------------------------------


@router.post("/{run_id}/enrich")
async def trigger_enrichment(
    run_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, str]:
    """Dispatch the enrichment pipeline for a completed collection run.

    Triggers the ``enrich_collection_run`` Celery task which applies all
    configured enrichers (language detection, NER, sentiment, coordination,
    propagation) to the collected content records.

    The run must be in ``completed`` status before enrichment can be triggered.

    Args:
        run_id: UUID of the collection run to enrich.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        Dict with ``task_id`` and ``run_id`` for tracking the enrichment task.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the caller did not initiate the run (and is not admin).
        HTTPException 409: If the run is not in 'completed' status.
    """
    run = await _get_run_or_404(run_id, db)
    ownership_guard(run.initiated_by, current_user)

    if run.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot enrich a run with status '{run.status}'. "
                "Only completed runs can be enriched."
            ),
        )

    # Launch the Celery enrichment task asynchronously
    from issue_observatory.workers.tasks import enrich_collection_run

    task = enrich_collection_run.delay(str(run_id))

    logger.info(
        "enrichment_pipeline_launched",
        run_id=str(run_id),
        task_id=task.id,
        user_id=str(current_user.id),
    )

    return {
        "task_id": task.id,
        "run_id": str(run_id),
        "message": "Enrichment pipeline task launched. This may take several minutes.",
    }


# ---------------------------------------------------------------------------
# Volume spike alerts (2.4)
# ---------------------------------------------------------------------------


@router.get("/volume-spikes")
async def get_volume_spikes(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    query_design_id: uuid.UUID = Query(..., description="UUID of the query design to query."),
    days: int = Query(default=30, ge=1, le=365, description="Number of past days to include."),
) -> list[dict[str, Any]]:
    """Return volume spike alerts for a query design from the last N days.

    Volume spikes are detected when collection volume for an arena exceeds 2x
    the rolling 7-day average. Spike events are stored in
    ``collection_runs.arenas_config["_volume_spikes"]`` when detected.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        query_design_id: UUID of the query design to query spikes for.
        days: Number of past days to include (1-365, default 30).

    Returns:
        List of dicts, each containing run metadata and spike details::

            [
              {
                "run_id": "...",
                "completed_at": "2026-02-15T10:00:00+00:00",
                "volume_spikes": [
                  {
                    "arena_name": "social_media",
                    "platform": "bluesky",
                    "current_count": 523,
                    "rolling_7d_average": 145.2,
                    "ratio": 3.6,
                    "top_terms": ["term1", "term2", "term3"]
                  },
                  ...
                ]
              },
              ...
            ]

        Returns an empty list when no spikes exist in the window.

    Raises:
        HTTPException 404: If the query design does not exist.
        HTTPException 403: If the caller does not own the query design.
    """
    # Verify the query design exists and is owned by this user
    qd_result = await db.execute(
        select(QueryDesign).where(QueryDesign.id == query_design_id)
    )
    query_design = qd_result.scalar_one_or_none()
    if query_design is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query design '{query_design_id}' not found.",
        )
    ownership_guard(query_design.owner_id, current_user)

    # Fetch recent volume spikes from the alerting module
    spikes = await fetch_recent_volume_spikes(
        session=db,
        query_design_id=query_design_id,
        days=days,
    )

    logger.info(
        "volume_spikes_fetched",
        query_design_id=str(query_design_id),
        user_id=str(current_user.id),
        spike_count=len(spikes),
        days=days,
    )

    return spikes


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------

#: Terminal states after which no further updates will arrive.
_TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})


@router.get("/{run_id}/stream")
async def stream_collection_run(
    run_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> StreamingResponse:
    """Stream live collection run status via Server-Sent Events.

    Opens a ``text/event-stream`` response and pushes updates as the run
    progresses:

    1. Immediately emits the current state of every ``CollectionTask`` row
       associated with this run so the client can render an initial snapshot
       without waiting for the first live event.

    2. If the run is already in a terminal state (``completed``, ``failed``,
       or ``cancelled``), emits a ``run_complete`` event and closes the
       connection.

    3. Otherwise, subscribes to the Redis pub/sub channel
       ``collection:{run_id}`` and forwards messages as SSE events until:

       - A ``run_complete`` event is received, or
       - The client disconnects (``request.is_disconnected()``), or
       - No message arrives within 30 seconds, in which case a keepalive
         comment (``": keepalive"``) is emitted and the loop continues.

    **Event types**:

    ``task_update``::

        event: task_update
        data: {"arena":"bluesky","platform":"bluesky","status":"running",
                "records_collected":47,"error_message":null,"elapsed_seconds":12.4}

    ``run_complete``::

        event: run_complete
        data: {"status":"completed","records_collected":312,"credits_spent":0}

    Args:
        run_id: UUID of the collection run to stream.
        request: The incoming HTTP request (used for disconnect detection).
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        redis: Injected async Redis client.

    Returns:
        A ``StreamingResponse`` with ``Content-Type: text/event-stream``.

    Raises:
        HTTPException 404: If the run does not exist.
        HTTPException 403: If the caller did not initiate the run (and is
            not an admin).
    """
    run = await _get_run_or_404(run_id, db, load_tasks=True)
    ownership_guard(run.initiated_by, current_user)

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE frames for the collection run."""
        # --- 1. Emit current task snapshot ---------------------------------
        task_result = await db.execute(
            select(CollectionTask).where(
                CollectionTask.collection_run_id == run_id
            )
        )
        for task in task_result.scalars():
            payload = {
                "arena": task.arena,
                "platform": task.platform,
                "status": task.status,
                "records_collected": task.records_collected,
                "error_message": task.error_message,
                "elapsed_seconds": None,
            }
            yield f"event: task_update\ndata: {json.dumps(payload)}\n\n"

        # --- 2. If already terminal, emit run_complete and stop ------------
        if run.status in _TERMINAL_STATUSES:
            complete_payload = {
                "status": run.status,
                "records_collected": run.records_collected,
                "credits_spent": run.credits_spent,
            }
            yield f"event: run_complete\ndata: {json.dumps(complete_payload)}\n\n"
            return

        # --- 3. Subscribe to Redis pub/sub and forward messages ------------
        channel = f"collection:{run_id}"
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        logger.debug("sse: subscribed to channel=%s user=%s", channel, current_user.id)

        try:
            while True:
                if await request.is_disconnected():
                    logger.debug(
                        "sse: client disconnected channel=%s", channel
                    )
                    break

                try:
                    message = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True),
                        timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    # No message in 30 s — send a keepalive comment to
                    # prevent proxies from closing an idle connection.
                    yield ": keepalive\n\n"
                    continue

                if message is None:
                    # get_message returned None (no message ready yet).
                    await asyncio.sleep(0.05)
                    continue

                raw_data = message.get("data")
                if not isinstance(raw_data, str):
                    continue

                try:
                    data = json.loads(raw_data)
                except json.JSONDecodeError:
                    logger.warning("sse: non-JSON message on channel=%s", channel)
                    continue

                event_type = data.pop("event", "task_update")
                yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

                if event_type == "run_complete":
                    break
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            logger.debug("sse: unsubscribed from channel=%s", channel)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

