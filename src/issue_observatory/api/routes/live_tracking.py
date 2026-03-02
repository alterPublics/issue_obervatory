"""Live tracking management routes.

Provides a dedicated page for managing daily automated (live) collections,
with automatic gap-filling when starting live tracking and a timeline
visualization of collected data.

Routes:
    GET  /live-tracking/       — live tracking management page
    POST /live-tracking/start  — start live tracking with automatic gap-fill
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from issue_observatory.api.dependencies import (
    get_current_active_user,
    ownership_guard,
)
from issue_observatory.core.database import get_db
from issue_observatory.core.models.collection import CollectionRun
from issue_observatory.core.models.project import Project
from issue_observatory.core.models.query_design import QueryDesign
from issue_observatory.core.models.users import User
from issue_observatory.core.schemas.collection import CollectionRunCreate

logger = structlog.get_logger(__name__)

router = APIRouter()


def _templates(request: Request) -> Jinja2Templates:
    """Resolve the Jinja2Templates instance from the app state."""
    templates = request.app.state.templates
    if templates is None:
        raise RuntimeError("Templates not configured on app.state")
    return templates


# ---------------------------------------------------------------------------
# GET /live-tracking/ — management page
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def live_tracking_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Render the live tracking management page.

    Queries three groups of query designs:
    1. Active tracking — designs with an active/suspended/pending live run
    2. Available — designs with completed batch runs but no active live run
    3. Ready to start — active designs with arenas_config but no runs at all
    """
    user_id = current_user.id

    # --- Group 1: Active tracking ---
    # Designs with a live run in active/suspended/pending status
    active_live_runs_stmt = (
        select(
            CollectionRun,
            QueryDesign.name.label("design_name"),
            QueryDesign.id.label("design_id"),
        )
        .join(QueryDesign, CollectionRun.query_design_id == QueryDesign.id)
        .where(
            CollectionRun.initiated_by == user_id,
            CollectionRun.mode == "live",
            CollectionRun.status.in_(["active", "suspended", "pending"]),
        )
        .order_by(CollectionRun.started_at.desc().nullslast())
    )
    active_result = await db.execute(active_live_runs_stmt)
    active_rows = active_result.all()

    active_tracking = []
    active_design_ids: set[uuid.UUID] = set()

    # Pre-fetch total records per design (across ALL runs) for the active cards.
    design_totals_stmt = (
        select(
            CollectionRun.query_design_id,
            func.coalesce(func.sum(CollectionRun.records_collected), 0).label("total"),
        )
        .where(CollectionRun.initiated_by == user_id)
        .group_by(CollectionRun.query_design_id)
    )
    design_totals_result = await db.execute(design_totals_stmt)
    design_total_map: dict[uuid.UUID, int] = {
        row.query_design_id: row.total
        for row in design_totals_result.all()
    }

    for run, design_name, design_id in active_rows:
        active_design_ids.add(design_id)
        # Get arenas from arenas_config
        arenas_config = run.arenas_config or {}
        enabled_arenas: list[str] = []
        if "arenas" in arenas_config and isinstance(arenas_config["arenas"], list):
            for entry in arenas_config["arenas"]:
                if isinstance(entry, dict) and entry.get("enabled", True):
                    arena_id = entry.get("id") or entry.get("platform_name")
                    if arena_id:
                        enabled_arenas.append(arena_id)
        else:
            for key, val in arenas_config.items():
                if key.startswith("_") or key == "arenas" or key == "languages":
                    continue
                if isinstance(val, str):
                    enabled_arenas.append(key)
                elif isinstance(val, dict):
                    enabled_arenas.append(key)

        active_tracking.append({
            "run_id": str(run.id),
            "design_id": str(design_id),
            "design_name": design_name or "Untitled",
            "status": run.status,
            "records_collected": run.records_collected or 0,
            "total_design_records": design_total_map.get(design_id, 0),
            "credits_spent": run.credits_spent or 0,
            "started_at": run.started_at,
            "suspended_at": run.suspended_at,
            "tier": run.tier or "free",
            "enabled_arenas": enabled_arenas,
        })

    # --- Group 2: Available for live tracking ---
    # Designs with at least one completed batch run, no active live run,
    # owned by this user
    available_subq = (
        select(
            QueryDesign.id.label("design_id"),
            QueryDesign.name.label("design_name"),
            func.max(CollectionRun.date_to).label("last_data_date"),
            func.sum(CollectionRun.records_collected).label("total_records"),
        )
        .join(CollectionRun, CollectionRun.query_design_id == QueryDesign.id)
        .where(
            QueryDesign.owner_id == user_id,
            QueryDesign.is_active.is_(True),
            CollectionRun.mode == "batch",
            CollectionRun.status.in_(["completed", "cancelled"]),
            CollectionRun.records_collected > 0,
        )
        .group_by(QueryDesign.id, QueryDesign.name)
    )
    available_result = await db.execute(available_subq)
    available_rows = available_result.all()

    today = date.today()
    yesterday = today - timedelta(days=1)

    available_designs = []
    for row in available_rows:
        design_id = row.design_id
        if design_id in active_design_ids:
            continue

        last_date = row.last_data_date
        if last_date is not None:
            if isinstance(last_date, datetime):
                last_date_d = last_date.date()
            else:
                last_date_d = last_date
            gap_days = (yesterday - last_date_d).days
            if gap_days <= 0:
                gap_label = "Up to date"
            else:
                gap_label = f"{gap_days}-day gap"
        else:
            last_date_d = None
            gap_days = -1
            gap_label = "No data"

        available_designs.append({
            "design_id": str(design_id),
            "design_name": row.design_name or "Untitled",
            "last_data_date": str(last_date_d) if last_date_d else None,
            "gap_days": gap_days,
            "gap_label": gap_label,
            "total_records": row.total_records or 0,
        })

    # --- Group 3: Ready to start (no runs at all) ---
    # Active designs with arenas_config, no collection runs
    ready_subq = (
        select(QueryDesign)
        .outerjoin(CollectionRun, CollectionRun.query_design_id == QueryDesign.id)
        .where(
            QueryDesign.owner_id == user_id,
            QueryDesign.is_active.is_(True),
            CollectionRun.id.is_(None),
        )
    )
    ready_result = await db.execute(ready_subq)
    ready_designs_raw = ready_result.scalars().all()

    ready_designs = []
    for qd in ready_designs_raw:
        if qd.id in active_design_ids:
            continue
        # Only show designs that have some arenas configured
        if qd.arenas_config:
            ready_designs.append({
                "design_id": str(qd.id),
                "design_name": qd.name or "Untitled",
                "last_data_date": None,
                "gap_days": -1,
                "gap_label": "No data",
                "total_records": 0,
            })

    # --- Data Timeline context: projects and all active designs ---
    projects_result = await db.execute(
        select(Project.id, Project.name)
        .where(Project.owner_id == user_id)
        .order_by(Project.name)
    )
    user_projects = [
        {"id": str(row.id), "name": row.name}
        for row in projects_result.all()
    ]

    all_designs_result = await db.execute(
        select(QueryDesign.id, QueryDesign.name, QueryDesign.project_id)
        .where(
            QueryDesign.owner_id == user_id,
            QueryDesign.is_active.is_(True),
        )
        .order_by(QueryDesign.name)
    )
    all_designs = [
        {
            "id": str(row.id),
            "name": row.name or "Untitled",
            "project_id": str(row.project_id) if row.project_id else None,
        }
        for row in all_designs_result.all()
    ]

    templates = _templates(request)
    return templates.TemplateResponse(
        "live_tracking/index.html",
        {
            "request": request,
            "user": current_user,
            "active_tracking": active_tracking,
            "available_designs": available_designs,
            "ready_designs": ready_designs,
            "projects": user_projects,
            "all_designs": all_designs,
        },
    )


# ---------------------------------------------------------------------------
# POST /live-tracking/start — start live tracking with gap-fill
# ---------------------------------------------------------------------------


@router.post("/start", status_code=status.HTTP_303_SEE_OTHER)
async def start_live_tracking(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    query_design_id: Annotated[str, Form()],
) -> RedirectResponse:
    """Start live tracking for a query design with automatic gap-fill.

    1. Validates ownership and checks no existing active live run.
    2. Finds the last data date from completed batch runs.
    3. If there's a gap, creates a backfill batch run.
    4. Creates a live run with status='active'.
    5. Redirects to /live-tracking with a success flash.
    """
    # Parse the query design ID
    try:
        qd_id = uuid.UUID(query_design_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid query design ID",
        ) from exc

    # Verify the query design exists and is owned by this user
    qd_result = await db.execute(
        select(QueryDesign).where(QueryDesign.id == qd_id)
    )
    query_design = qd_result.scalar_one_or_none()
    if query_design is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query design '{qd_id}' not found.",
        )
    ownership_guard(query_design.owner_id, current_user)

    # Check no existing active live run for this design
    existing_live_stmt = select(CollectionRun).where(
        CollectionRun.query_design_id == qd_id,
        CollectionRun.mode == "live",
        CollectionRun.status.in_(["active", "suspended", "pending"]),
    )
    existing_live_result = await db.execute(existing_live_stmt)
    existing_live = existing_live_result.scalar_one_or_none()
    if existing_live is not None:
        return RedirectResponse(
            url="/live-tracking?flash=Live+tracking+is+already+active+for+this+design&flash_level=warning",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    # Find the last data date from completed batch runs
    last_date_stmt = select(func.max(CollectionRun.date_to)).where(
        CollectionRun.query_design_id == qd_id,
        CollectionRun.mode == "batch",
        CollectionRun.status == "completed",
    )
    last_date_result = await db.execute(last_date_stmt)
    last_date_to = last_date_result.scalar_one_or_none()

    today = date.today()
    yesterday = today - timedelta(days=1)

    # Import create_collection_run for reuse
    from issue_observatory.api.routes.collections import create_collection_run

    # --- Gap-fill logic ---
    if last_date_to is None:
        # No data at all: create a single-day batch run for yesterday
        backfill_payload = CollectionRunCreate(
            query_design_id=qd_id,
            mode="batch",
            tier=query_design.default_tier or "free",
            date_from=datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=timezone.utc),
            date_to=datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59, tzinfo=timezone.utc),
        )
        try:
            await create_collection_run(request, backfill_payload, db, current_user)
        except HTTPException as exc:
            logger.warning(
                "backfill_creation_failed",
                query_design_id=str(qd_id),
                error=str(exc.detail),
            )
    else:
        # Check for gap
        if isinstance(last_date_to, datetime):
            last_date_d = last_date_to.date()
        else:
            last_date_d = last_date_to
        gap_start = last_date_d + timedelta(days=1)
        if gap_start <= yesterday:
            backfill_payload = CollectionRunCreate(
                query_design_id=qd_id,
                mode="batch",
                tier=query_design.default_tier or "free",
                date_from=datetime(gap_start.year, gap_start.month, gap_start.day, tzinfo=timezone.utc),
                date_to=datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59, tzinfo=timezone.utc),
            )
            try:
                await create_collection_run(request, backfill_payload, db, current_user)
            except HTTPException as exc:
                logger.warning(
                    "backfill_creation_failed",
                    query_design_id=str(qd_id),
                    error=str(exc.detail),
                )

    # --- Create the live run ---
    live_payload = CollectionRunCreate(
        query_design_id=qd_id,
        mode="live",
        tier=query_design.default_tier or "free",
    )
    live_run = await create_collection_run(request, live_payload, db, current_user)

    # Set status to 'active' so the daily beat task picks it up.
    # create_collection_run creates with status='pending', but
    # fetch_live_tracking_designs only picks up status='active'.
    live_run.status = "active"
    await db.commit()

    logger.info(
        "live_tracking_started",
        query_design_id=str(qd_id),
        run_id=str(live_run.id),
        user_id=str(current_user.id),
    )

    return RedirectResponse(
        url="/live-tracking?flash=Live+tracking+started+successfully&flash_level=success",
        status_code=status.HTTP_303_SEE_OTHER,
    )
