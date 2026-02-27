"""HTML page routes rendered with Jinja2 templates.

All routes in this module return full HTML pages for the browser UI.
They are separate from the JSON API routes to keep concerns isolated.

For HTMX partial updates the JSON API routes in the adjacent modules
return data which the HTMX attributes on the templates consume directly.

Authentication is enforced by checking the ``current_user`` dependency;
unauthenticated requests receive a redirect to ``/auth/login`` rather than
a JSON 401 because the browser UI does not handle JSON error responses.

Admin routes additionally require ``role='admin'`` via the ``require_admin``
dependency.

Routes:
    GET /                               → redirect to /dashboard
    GET /dashboard                      → dashboard/index.html
    GET /explore                        → explore/index.html
    GET /arenas                         → arenas/index.html
    GET /query-designs                  → query_designs/list.html
    GET /query-designs/new              → query_designs/editor.html
    GET /query-designs/{design_id}      → query_designs/detail.html
    GET /query-designs/{design_id}/edit → query_designs/editor.html
    GET /collections                    → collections/list.html
    GET /collections/new                → collections/launcher.html
    GET /collections/{run_id}           → collections/detail.html
    GET /content                        → content/browser.html
    GET /auth/login                     → auth/login.html
    GET /admin/users                    → admin/users.html
    GET /admin/credits                  → admin/credits.html
    GET /admin/credentials              → admin/credentials.html
    GET /admin/health                   → admin/health.html
"""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from issue_observatory.api.dependencies import (
    PaginationParams,
    get_current_active_user,
    get_optional_user,
    get_pagination,
    require_admin,
)
from issue_observatory.core.models.content import UniversalContentRecord
from issue_observatory.core.database import get_db
from issue_observatory.core.models.collection import CollectionRun, CollectionTask
from issue_observatory.core.models.project import Project
from issue_observatory.core.models.query_design import QueryDesign, SearchTerm
from issue_observatory.core.models.users import CreditAllocation, User

router = APIRouter(include_in_schema=False)

# Routes that must be evaluated BEFORE API routers so that literal path
# segments like ``/new`` are matched before ``/{id}`` catch-all patterns.
priority_router = APIRouter(include_in_schema=False)


def _prefers_json(request: Request) -> bool:
    """Return True when the client explicitly prefers JSON over HTML.

    HTMX requests and normal browser navigation always get HTML.  Only
    programmatic API callers sending ``Accept: application/json`` without
    ``text/html`` are routed to the JSON path.
    """
    if request.headers.get("hx-request"):
        return False
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return False
    return "application/json" in accept


def _templates(request: Request) -> Jinja2Templates:
    """Resolve the Jinja2Templates instance from the app state.

    The templates engine is stored on the app instance by ``main.py`` during
    startup so that page routes do not need to know the template directory
    path.

    Args:
        request: The current HTTP request, used to access ``request.app``.

    Returns:
        The ``Jinja2Templates`` instance configured in ``main.py``.

    Raises:
        RuntimeError: If templates are not available (startup event hasn't run).
    """
    if not hasattr(request.app.state, "templates") or request.app.state.templates is None:
        raise RuntimeError(
            "Templates not initialized. Ensure the FastAPI app startup event has run."
        )
    return request.app.state.templates


# ---------------------------------------------------------------------------
# Root redirect
# ---------------------------------------------------------------------------


@router.get("/")
async def root_redirect() -> RedirectResponse:
    """Redirect the root URL to the dashboard.

    Returns:
        A 302 redirect response to ``/dashboard``.
    """
    return RedirectResponse(url="/dashboard", status_code=302)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Render the dashboard overview page.

    Shows active collection runs, credit balance, and recent activity feed.

    Args:
        request: The current HTTP request.
        current_user: The authenticated, active user.

    Returns:
        Rendered ``dashboard/index.html`` template.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "dashboard/index.html",
        {"request": request, "user": current_user},
    )


# ---------------------------------------------------------------------------
# Explore (ad-hoc topic exploration)
# ---------------------------------------------------------------------------


@router.get("/explore", response_class=HTMLResponse)
async def explore_page(
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Render the ad-hoc exploration page.

    Allows researchers to run quick queries against low-cost arenas (Google
    Autocomplete, Bluesky, Reddit, RSS Feeds, Gab) to discover associations
    before committing to a formal query design.

    Args:
        request: The current HTTP request.
        current_user: The authenticated, active user.

    Returns:
        Rendered ``explore/index.html`` template.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "explore/index.html",
        {"request": request, "user": current_user},
    )


# ---------------------------------------------------------------------------
# Arenas
# ---------------------------------------------------------------------------


@router.get("/arenas", response_class=HTMLResponse)
async def arenas_page(
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Render the arenas overview page.

    Displays all registered arena collectors with their metadata, organized by
    tier. Provides a high-level view of available data collection platforms
    before researchers create a query design.

    Args:
        request: The current HTTP request.
        current_user: The authenticated, active user.

    Returns:
        Rendered ``arenas/index.html`` template.
    """
    from issue_observatory.arenas.registry import autodiscover, list_arenas  # noqa: PLC0415

    autodiscover()
    arenas = list_arenas()

    tpl = _templates(request)
    return tpl.TemplateResponse(
        "arenas/index.html",
        {"request": request, "user": current_user, "arenas": arenas},
    )


# ---------------------------------------------------------------------------
# Query designs
# ---------------------------------------------------------------------------


@router.get("/query-designs", response_class=HTMLResponse)
async def query_designs_list(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Render the query design list page.

    Args:
        request: The current HTTP request.
        db: Injected async database session.
        current_user: The authenticated, active user.

    Returns:
        Rendered ``query_designs/list.html`` template.
    """
    stmt = (
        select(QueryDesign)
        .where(QueryDesign.owner_id == current_user.id)
        .order_by(QueryDesign.created_at.desc())
    )
    result = await db.execute(stmt)
    designs_rows = result.scalars().all()

    designs = []
    for d in designs_rows:
        # Count search terms for display
        term_stmt = select(func.count()).select_from(SearchTerm).where(
            SearchTerm.query_design_id == d.id
        )
        term_result = await db.execute(term_stmt)
        term_count = term_result.scalar() or 0

        designs.append({
            "id": str(d.id),
            "name": d.name,
            "description": d.description,
            "visibility": d.visibility,
            "default_tier": d.default_tier,
            "search_term_count": term_count,
            "created_at": d.created_at.isoformat() if d.created_at else "",
            "is_active": d.is_active,
        })

    tpl = _templates(request)
    return tpl.TemplateResponse(
        "query_designs/list.html",
        {"request": request, "user": current_user, "designs": designs},
    )


@priority_router.get("/query-designs/new", response_class=HTMLResponse)
async def query_designs_new(
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: Optional[str] = None,
) -> HTMLResponse:
    """Render the query design create form.

    Args:
        request: The current HTTP request.
        current_user: The authenticated, active user.
        db: Injected async database session.
        project_id: Optional project UUID string to auto-attach the new design.

    Returns:
        Rendered ``query_designs/editor.html`` template with empty context.
    """
    parsed_project_id: uuid.UUID | None = None
    project_name = ""
    if project_id and project_id.strip():
        try:
            parsed_project_id = uuid.UUID(project_id.strip())
        except ValueError:
            pass  # Ignore invalid UUIDs — fall through without project context

    if parsed_project_id:
        result = await db.execute(
            select(Project.name).where(Project.id == parsed_project_id)
        )
        project_name = result.scalar_one_or_none() or ""

    # Only pass project context when a real project was found.
    # This prevents hidden field emission for non-existent UUIDs.
    verified_project_id = str(parsed_project_id) if project_name else ""

    tpl = _templates(request)
    return tpl.TemplateResponse(
        "query_designs/editor.html",
        {
            "request": request,
            "user": current_user,
            "design": None,
            "project_id": verified_project_id,
            "project_name": project_name,
        },
    )


@priority_router.get("/query-designs/{design_id:uuid}")
async def query_designs_detail(
    request: Request,
    design_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Render the query design detail page, or return JSON for API clients.

    Args:
        request: The current HTTP request.
        design_id: UUID of the query design to display.
        current_user: The authenticated, active user.
        db: Injected async database session.

    Returns:
        Rendered ``query_designs/detail.html`` template for browsers,
        or a JSON response for ``Accept: application/json`` callers.
    """
    # Load the full query design with search terms and project.
    stmt = (
        select(QueryDesign)
        .where(QueryDesign.id == design_id)
        .options(
            selectinload(QueryDesign.search_terms),
            selectinload(QueryDesign.project),
        )
    )
    result = await db.execute(stmt)
    design = result.scalar_one_or_none()

    if design is None:
        raise HTTPException(status_code=404, detail="Query design not found")

    # JSON API path — delegate to the API handler's response model.
    if _prefers_json(request):
        from issue_observatory.api.routes.query_designs import get_query_design

        return await get_query_design(design_id, db, current_user)

    # HTML path — build template context and render.
    tpl = _templates(request)
    term_count = len(design.search_terms) if design.search_terms else 0

    design_context = {
        "id": str(design.id),
        "name": design.name,
        "description": design.description,
        "visibility": design.visibility,
        "default_tier": design.default_tier,
        "language": design.language,
        "locale_country": design.locale_country,
        "arenas_config": design.arenas_config or {},
        "is_active": design.is_active,
        "search_term_count": term_count,
        "search_terms": [
            {
                "id": str(t.id),
                "term": t.term,
                "term_type": t.term_type,
                "group_id": str(t.group_id) if t.group_id else None,
                "group_label": t.group_label,
                "target_arenas": t.target_arenas,
                "is_active": t.is_active,
            }
            for t in (design.search_terms or [])
        ],
        "created_at": design.created_at.isoformat() if design.created_at else "",
    }

    # Project context for breadcrumb/badge display.
    project_context = {}
    if design.project:
        project_context = {
            "project_id": str(design.project.id),
            "project_name": design.project.name,
        }

    return tpl.TemplateResponse(
        "query_designs/detail.html",
        {
            "request": request,
            "user": current_user,
            "design_id": str(design_id),
            "design": design_context,
            **project_context,
        },
    )


@priority_router.get("/query-designs/{design_id:uuid}/edit", response_class=HTMLResponse)
async def query_designs_edit(
    request: Request,
    design_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    """Render the query design editor for an existing design.

    Args:
        request: The current HTTP request.
        design_id: UUID of the query design to edit.
        current_user: The authenticated, active user.
        db: Injected async database session.

    Returns:
        Rendered ``query_designs/editor.html`` template.
    """
    tpl = _templates(request)

    # Load the full query design object so the editor template can access
    # arenas_config and other attributes without a client-side fetch.
    stmt = (
        select(QueryDesign)
        .where(QueryDesign.id == design_id)
        .options(
            selectinload(QueryDesign.search_terms).selectinload(
                SearchTerm.parent_term
            ),
            selectinload(QueryDesign.project),
        )
    )
    result = await db.execute(stmt)
    design = result.scalar_one_or_none()

    if design is None:
        raise HTTPException(status_code=404, detail="Query design not found")

    # Sort terms: grouped first (alpha by group_label), ungrouped last
    sorted_terms = sorted(
        design.search_terms,
        key=lambda t: (0 if t.group_label else 1, t.group_label or "", t.term),
    )

    # Project context for breadcrumb display.
    project_context = {}
    if design.project:
        project_context = {
            "project_id": str(design.project.id),
            "project_name": design.project.name,
        }

    return tpl.TemplateResponse(
        "query_designs/editor.html",
        {
            "request": request,
            "user": current_user,
            "design_id": str(design_id),
            "design": design,
            "terms": sorted_terms,
            **project_context,
        },
    )


@priority_router.get("/query-designs/{design_id:uuid}/codebook", response_class=HTMLResponse)
async def query_design_codebook_manager(
    request: Request,
    design_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    """Render the codebook manager page for a query design.

    Provides a full CRUD interface for managing structured qualitative coding
    schemes (codebook entries) scoped to a specific query design.

    Args:
        request: The current HTTP request.
        design_id: UUID of the query design.
        current_user: The authenticated, active user.
        db: Injected async database session.

    Returns:
        Rendered ``annotations/codebook_manager.html`` template.
    """
    # Fetch the query design to get its name for breadcrumb navigation
    stmt = select(QueryDesign).where(QueryDesign.id == design_id)
    result = await db.execute(stmt)
    design = result.scalar_one_or_none()

    design_name = design.name if design else "Query Design"

    tpl = _templates(request)
    return tpl.TemplateResponse(
        "annotations/codebook_manager.html",
        {
            "request": request,
            "user": current_user,
            "design_id": str(design_id),
            "design_name": design_name,
        },
    )


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


@router.get("/collections", response_class=HTMLResponse)
async def collections_list(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Render the collection run history list page, grouped by project.

    Runs with a project_id are aggregated into per-project rows showing
    combined records, credits, and status. Orphan runs (no project) are
    shown in a separate section at the bottom.

    Args:
        request: The current HTTP request.
        db: Injected async database session.
        current_user: The authenticated, active user.

    Returns:
        Rendered ``collections/list.html`` template.
    """
    from issue_observatory.core.models.project import Project as ProjectModel  # noqa: PLC0415

    stmt = (
        select(CollectionRun)
        .options(
            selectinload(CollectionRun.query_design),
            selectinload(CollectionRun.project),
        )
        .where(CollectionRun.initiated_by == current_user.id)
        .order_by(CollectionRun.started_at.desc().nulls_last())
        .limit(200)
    )
    result = await db.execute(stmt)
    runs_rows = result.scalars().all()

    # Group runs by project_id
    project_runs: dict[str, list] = {}  # project_id -> list of runs
    orphan_runs: list[dict] = []

    for r in runs_rows:
        run_dict = {
            "id": str(r.id),
            "query_design_name": r.query_design.name if r.query_design else "(unknown design)",
            "mode": r.mode,
            "tier": r.tier,
            "status": r.status,
            "records_collected": r.records_collected,
            "credits_spent": r.credits_spent,
            "started_at": r.started_at.isoformat() if r.started_at else "",
        }

        if r.project_id:
            pid = str(r.project_id)
            if pid not in project_runs:
                project_runs[pid] = []
            project_runs[pid].append(run_dict)
        else:
            orphan_runs.append(run_dict)

    # Build per-project aggregates
    projects_with_runs: list[dict] = []
    for r in runs_rows:
        if r.project_id and str(r.project_id) in project_runs:
            pid = str(r.project_id)
            # Only process each project once
            if any(p["project_id"] == pid for p in projects_with_runs):
                continue

            runs_list = project_runs[pid]
            statuses = {run["status"] for run in runs_list}
            total_records = sum(run["records_collected"] for run in runs_list)
            total_credits = sum(run["credits_spent"] for run in runs_list)
            latest_started = max(
                (run["started_at"] for run in runs_list if run["started_at"]),
                default="",
            )

            # Aggregate status logic
            if "running" in statuses or "pending" in statuses:
                agg_status = "running"
            elif statuses == {"completed"}:
                agg_status = "completed"
            elif statuses == {"failed"}:
                agg_status = "failed"
            elif "completed" in statuses:
                agg_status = "partial"
            else:
                agg_status = "failed"

            projects_with_runs.append({
                "project_id": pid,
                "project_name": r.project.name if r.project else "(unknown project)",
                "status": agg_status,
                "total_records": total_records,
                "total_credits": total_credits,
                "latest_started": latest_started,
                "run_count": len(runs_list),
                "qd_count": len({run["query_design_name"] for run in runs_list}),
            })

    # Sort by latest activity descending
    projects_with_runs.sort(key=lambda p: p["latest_started"], reverse=True)

    tpl = _templates(request)
    return tpl.TemplateResponse(
        "collections/list.html",
        {
            "request": request,
            "user": current_user,
            "projects_with_runs": projects_with_runs,
            "orphan_runs": orphan_runs,
        },
    )


@priority_router.get("/collections/project/{project_id:uuid}", response_class=HTMLResponse)
async def project_collection_detail(
    request: Request,
    project_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    """Render the project-level collection detail page.

    Aggregates all collection runs for the given project into a single
    view with combined stats, per-platform record counts, and a per-QD
    run table.

    Args:
        request: The current HTTP request.
        project_id: UUID of the project.
        current_user: The authenticated, active user.
        db: Injected async database session.

    Returns:
        Rendered ``collections/project_detail.html`` template.
    """
    from issue_observatory.core.models.content import UniversalContentRecord  # noqa: PLC0415

    tpl = _templates(request)

    # Load the project
    proj_result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = proj_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Load all collection runs for this project with QD and tasks
    runs_result = await db.execute(
        select(CollectionRun)
        .where(
            CollectionRun.project_id == project_id,
            CollectionRun.initiated_by == current_user.id,
        )
        .options(
            selectinload(CollectionRun.query_design),
            selectinload(CollectionRun.tasks),
        )
        .order_by(CollectionRun.started_at.desc().nulls_last())
    )
    runs = runs_result.scalars().all()

    # Aggregate stats
    total_records = sum(r.records_collected for r in runs)
    total_credits = sum(r.credits_spent for r in runs)
    total_estimated = sum(r.estimated_credits for r in runs)
    statuses = {r.status for r in runs}

    if "running" in statuses or "pending" in statuses:
        overall_status = "running"
    elif statuses == {"completed"}:
        overall_status = "completed"
    elif statuses == {"failed"}:
        overall_status = "failed"
    elif "completed" in statuses:
        overall_status = "partial"
    else:
        overall_status = "pending" if runs else "no_runs"

    any_running = overall_status == "running"

    # Per-platform record counts across all runs
    run_ids = [r.id for r in runs]
    platform_counts: dict[str, int] = {}
    if run_ids:
        pc_result = await db.execute(
            select(
                UniversalContentRecord.platform,
                func.count(UniversalContentRecord.id).label("count"),
            )
            .where(UniversalContentRecord.collection_run_id.in_(run_ids))
            .group_by(UniversalContentRecord.platform)
        )
        platform_counts = {row.platform: row.count for row in pc_result.all()}

    # Per-QD run list
    qd_runs: list[dict] = []
    for r in runs:
        qd_runs.append({
            "id": str(r.id),
            "query_design_name": r.query_design.name if r.query_design else "(unknown)",
            "query_design_id": str(r.query_design_id) if r.query_design_id else "",
            "mode": r.mode,
            "tier": r.tier,
            "status": r.status,
            "records_collected": r.records_collected,
            "credits_spent": r.credits_spent,
            "started_at": r.started_at.isoformat() if r.started_at else "",
        })

    # Date range across all runs
    date_froms = [r.date_from for r in runs if r.date_from]
    date_tos = [r.date_to for r in runs if r.date_to]
    date_range = ""
    if date_froms or date_tos:
        earliest = min(date_froms).strftime("%Y-%m-%d") if date_froms else "?"
        latest = max(date_tos).strftime("%Y-%m-%d") if date_tos else "?"
        date_range = f"{earliest} to {latest}"

    return tpl.TemplateResponse(
        "collections/project_detail.html",
        {
            "request": request,
            "user": current_user,
            "project": {
                "id": str(project.id),
                "name": project.name,
                "description": project.description,
            },
            "aggregate": {
                "total_records": total_records,
                "total_credits": total_credits,
                "total_estimated": total_estimated,
                "status": overall_status,
                "run_count": len(runs),
                "date_range": date_range,
            },
            "platform_counts": platform_counts,
            "qd_runs": qd_runs,
            "any_running": any_running,
        },
    )


@priority_router.get("/collections/new", response_class=HTMLResponse)
async def collections_new(
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    """Render the collection run launcher page.

    Loads the current user's query designs so the launcher dropdown
    is populated.

    Args:
        request: The current HTTP request.
        current_user: The authenticated, active user.
        db: Injected async database session.

    Returns:
        Rendered ``collections/launcher.html`` template.
    """
    from issue_observatory.core.models.query_design import (  # noqa: PLC0415
        ActorList,
        QueryDesign as QD,
    )
    from issue_observatory.core.models.actors import ActorListMember  # noqa: PLC0415

    stmt = (
        select(QD)
        .where(QD.owner_id == current_user.id)
        .where(QD.is_active.is_(True))
        .order_by(QD.name)
    )
    result = await db.execute(stmt)
    designs = result.scalars().all()

    # F1: Fetch term counts and actor counts per design for the pre-launch summary.
    design_ids = [d.id for d in designs]

    term_counts: dict[uuid.UUID, int] = {}
    actor_counts: dict[uuid.UUID, int] = {}

    if design_ids:
        # Term counts per design
        term_count_result = await db.execute(
            select(
                SearchTerm.query_design_id,
                func.count(SearchTerm.id).label("cnt"),
            )
            .where(
                SearchTerm.query_design_id.in_(design_ids),
                SearchTerm.is_active.is_(True),
            )
            .group_by(SearchTerm.query_design_id)
        )
        term_counts = {row.query_design_id: row.cnt for row in term_count_result.all()}

        # Actor counts per design (distinct actors across all actor lists)
        actor_count_result = await db.execute(
            select(
                ActorList.query_design_id,
                func.count(func.distinct(ActorListMember.actor_id)).label("cnt"),
            )
            .join(ActorListMember, ActorListMember.actor_list_id == ActorList.id)
            .where(ActorList.query_design_id.in_(design_ids))
            .group_by(ActorList.query_design_id)
        )
        actor_counts = {row.query_design_id: row.cnt for row in actor_count_result.all()}

    # Attach counts as attributes so the template can read them via data attributes.
    design_dicts = []
    for d in designs:
        design_dicts.append({
            "id": str(d.id),
            "name": d.name,
            "default_tier": d.default_tier if hasattr(d, "default_tier") else "free",
            "term_count": term_counts.get(d.id, 0),
            "actor_count": actor_counts.get(d.id, 0),
            "project_id": str(d.project_id) if d.project_id else "",
        })

    # Load user's projects for the project-based launcher.
    from issue_observatory.core.models.project import Project as ProjectModel  # noqa: PLC0415

    proj_stmt = (
        select(ProjectModel)
        .where(ProjectModel.owner_id == current_user.id)
        .options(selectinload(ProjectModel.query_designs))
        .order_by(ProjectModel.name)
    )
    proj_result = await db.execute(proj_stmt)
    projects = [
        {
            "id": str(p.id),
            "name": p.name,
            "qd_count": len([qd for qd in p.query_designs if qd.is_active]),
        }
        for p in proj_result.scalars().all()
    ]

    # Check for ?project_id= query param to preselect
    preselected_project_id = request.query_params.get("project_id", "")

    tpl = _templates(request)
    return tpl.TemplateResponse(
        "collections/launcher.html",
        {
            "request": request,
            "user": current_user,
            "query_designs": design_dicts,
            "projects": projects,
            "preselected_project_id": preselected_project_id,
        },
    )


@priority_router.get("/collections/{run_id:uuid}")
async def collections_detail(
    request: Request,
    run_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Render the collection run detail page, or return JSON for API clients.

    Queries the ``CollectionRun`` record and its associated ``QueryDesign``
    and ``SearchTerm`` rows so the template can display the query design name
    and the search terms that were used in this collection.

    Args:
        request: The current HTTP request.
        run_id: UUID of the collection run.
        current_user: The authenticated, active user.
        db: Injected async database session.

    Returns:
        Rendered ``collections/detail.html`` template for browsers,
        or a JSON response for ``Accept: application/json`` callers.
    """
    # JSON API path — delegate to the API handler.
    if _prefers_json(request):
        from issue_observatory.api.routes.collections import get_collection_run

        return await get_collection_run(run_id, db, current_user)

    tpl = _templates(request)

    # Load the collection run, eagerly joining its query design.
    result = await db.execute(
        select(CollectionRun)
        .where(CollectionRun.id == run_id)
        .options(selectinload(CollectionRun.query_design))
    )
    collection_run = result.scalar_one_or_none()

    run_context: dict = {"id": str(run_id)}
    tasks: list[dict] = []

    if collection_run is not None:
        run_context["status"] = collection_run.status
        run_context["mode"] = collection_run.mode
        run_context["tier"] = collection_run.tier
        run_context["records_collected"] = collection_run.records_collected
        run_context["credits_spent"] = collection_run.credits_spent
        run_context["started_at"] = (
            collection_run.started_at.isoformat() if collection_run.started_at else None
        )
        run_context["query_design_id"] = (
            str(collection_run.query_design_id)
            if collection_run.query_design_id
            else ""
        )

        query_design: Optional[QueryDesign] = collection_run.query_design
        if query_design is not None:
            run_context["query_design_name"] = query_design.name

            # Load search terms for the associated query design.
            terms_result = await db.execute(
                select(SearchTerm)
                .where(
                    SearchTerm.query_design_id == query_design.id,
                    SearchTerm.is_active.is_(True),
                )
                .order_by(SearchTerm.added_at)
            )
            run_context["search_terms"] = [
                {"term": t.term, "term_type": t.term_type}
                for t in terms_result.scalars().all()
            ]
        else:
            run_context["query_design_name"] = ""
            run_context["search_terms"] = []

        # Load CollectionTask rows for this run.
        tasks_result = await db.execute(
            select(CollectionTask)
            .where(CollectionTask.collection_run_id == run_id)
            .order_by(CollectionTask.arena, CollectionTask.platform)
        )
        collection_tasks = tasks_result.scalars().all()

        # Build task dicts with fields expected by _fragments/task_row.html.
        for task in collection_tasks:
            duration_seconds = None
            if task.started_at and task.completed_at:
                duration_seconds = int((task.completed_at - task.started_at).total_seconds())

            tasks.append({
                "id": str(task.id),
                "arena": task.arena,
                "platform": task.platform,
                "status": task.status,
                "records_collected": task.records_collected,
                "credits_spent": 0,  # Credits are tracked at run level, not task level
                "error_message": task.error_message,
                "duration_seconds": duration_seconds,
            })

        # Query per-platform record counts for this run.
        platform_counts_result = await db.execute(
            select(
                UniversalContentRecord.platform,
                func.count(UniversalContentRecord.id).label("count"),
            )
            .where(UniversalContentRecord.collection_run_id == run_id)
            .group_by(UniversalContentRecord.platform)
        )
        platform_counts = {row.platform: row.count for row in platform_counts_result.all()}
        run_context["platform_counts"] = platform_counts
    else:
        run_context["search_terms"] = []

    return tpl.TemplateResponse(
        "collections/detail.html",
        {
            "request": request,
            "user": current_user,
            "run_id": str(run_id),
            "run": run_context,
            "tasks": tasks,
        },
    )


# ---------------------------------------------------------------------------
# Content browser
# ---------------------------------------------------------------------------
# NOTE: The main content browser page (/content) is served by content.py
# which includes full data fetching and filtering. Only auxiliary routes
# (like discovered-links) are defined here.


@priority_router.get("/content/discovered-links", response_class=HTMLResponse)
async def discovered_links_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    query_design_id: Optional[uuid.UUID] = None,
) -> HTMLResponse:
    """Render the discovered sources page (GR-22, YF-13).

    Displays cross-platform links found in collected content. When
    ``query_design_id`` is provided, scopes to that single design. When
    omitted, shows links across all of the user's query designs.

    Args:
        request: The current HTTP request.
        db: Injected async database session.
        current_user: The authenticated, active user.
        query_design_id: Optional UUID to scope to a single query design.

    Returns:
        Rendered ``content/discovered_links.html`` template with initial
        context: empty links list (populated via HTMX on page load), user's
        query designs for the dropdown, and active filter state.
    """
    tpl = _templates(request)

    # Fetch user's query designs for the dropdown selector.
    stmt = (
        select(QueryDesign)
        .where(QueryDesign.owner_id == current_user.id)
        .order_by(QueryDesign.created_at.desc())
    )
    result = await db.execute(stmt)
    query_designs = result.scalars().all()

    query_designs_list = [
        {"id": str(qd.id), "name": qd.name}
        for qd in query_designs
    ]

    return tpl.TemplateResponse(
        "content/discovered_links.html",
        {
            "request": request,
            "user": current_user,
            "links": [],  # Populated by HTMX
            "total": 0,
            "has_more": False,
            "next_offset": 0,
            "filter": {
                "platform": "",
                "min_count": 2,
                "query_design_id": str(query_design_id) if query_design_id else "",
            },
            "query_designs": query_designs_list,
            "active_query_design_id": str(query_design_id) if query_design_id else "",
        },
    )


# ---------------------------------------------------------------------------
# Actors
# ---------------------------------------------------------------------------


@router.get("/actors", response_class=HTMLResponse)
async def actors_list(
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    pagination: Annotated[PaginationParams, Depends(get_pagination)],
) -> HTMLResponse:
    """Render the actor directory list page.

    Args:
        request: The current HTTP request.
        current_user: The authenticated, active user.
        db: Injected async database session.
        pagination: Pagination parameters (limit, cursor).

    Returns:
        Rendered ``actors/list.html`` template with actor list data.
    """
    from issue_observatory.core.models.actors import Actor

    tpl = _templates(request)

    # Query actors created by current user or shared
    stmt = (
        select(Actor)
        .where(
            (Actor.created_by == current_user.id) | (Actor.is_shared.is_(True))
        )
        .order_by(Actor.created_at.desc())
        .limit(pagination.page_size)
    )

    result = await db.execute(stmt)
    actors = result.scalars().all()

    actors_list = [
        {
            "id": str(actor.id),
            "name": actor.canonical_name,
            "type": actor.actor_type,
            "description": actor.description,
            "public_figure": actor.public_figure,
            "platforms": [],
            "content_count": 0,
            "last_seen": actor.created_at.isoformat() if actor.created_at else "",
        }
        for actor in actors
    ]

    return tpl.TemplateResponse(
        "actors/list.html",
        {
            "request": request,
            "user": current_user,
            "actors": actors_list,
            "total_count": len(actors_list),
            "cursor": None,
        },
    )


@priority_router.get("/actors/{actor_id:uuid}")
async def actors_detail(
    request: Request,
    actor_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Render the actor detail page, or return JSON for API clients.

    Args:
        request: The current HTTP request.
        actor_id: UUID of the actor to display.
        current_user: The authenticated, active user.
        db: Injected async database session.

    Returns:
        Rendered ``actors/detail.html`` template for browsers,
        or a JSON response for ``Accept: application/json`` callers.
    """
    # JSON API path — delegate to the API handler.
    if _prefers_json(request):
        from issue_observatory.api.routes.actors import get_actor

        return await get_actor(actor_id, db, current_user)

    from issue_observatory.core.models.actors import Actor, ActorPlatformPresence

    tpl = _templates(request)

    # Load actor with presences
    result = await db.execute(
        select(Actor)
        .where(Actor.id == actor_id)
        .options(selectinload(Actor.platform_presences))
    )
    actor_record = result.scalar_one_or_none()

    if not actor_record:
        raise HTTPException(status_code=404, detail="Actor not found")

    # Count content records for this actor
    content_count_stmt = select(func.count()).select_from(UniversalContentRecord).where(
        UniversalContentRecord.author_id == actor_id
    )
    content_count_result = await db.execute(content_count_stmt)
    content_count = content_count_result.scalar() or 0

    # Build actor context
    actor_context = {
        "id": str(actor_record.id),
        "name": actor_record.canonical_name,
        "type": actor_record.actor_type,
        "description": actor_record.description,
        "public_figure": actor_record.public_figure,
        "content_count": content_count,
        "created_at": actor_record.created_at.isoformat() if actor_record.created_at else "",
    }

    # Build presences list
    presences_list = [
        {
            "id": str(p.id),
            "platform": p.platform,
            "username": p.platform_username,
            "profile_url": p.profile_url,
            "follower_count": p.follower_count,
            "verified": p.verified,
            "last_checked": p.last_checked_at.isoformat() if p.last_checked_at else "",
        }
        for p in (actor_record.platform_presences or [])
    ]

    # Load recent content (limit 20)
    recent_content_stmt = (
        select(UniversalContentRecord)
        .where(UniversalContentRecord.author_id == actor_id)
        .order_by(UniversalContentRecord.published_at.desc())
        .limit(20)
    )
    recent_content_result = await db.execute(recent_content_stmt)
    recent_content_records = recent_content_result.scalars().all()

    recent_content_list = [
        {
            "id": str(r.id),
            "platform": r.platform,
            "title": r.title,
            "text": r.text_content,
            "published_at": r.published_at.isoformat() if r.published_at else "",
        }
        for r in recent_content_records
    ]

    return tpl.TemplateResponse(
        "actors/detail.html",
        {
            "request": request,
            "user": current_user,
            "actor": actor_context,
            "presences": presences_list,
            "recent_content": recent_content_list,
            "content_cursor": None,
        },
    )


# ---------------------------------------------------------------------------
# Auth pages
# ---------------------------------------------------------------------------


@router.get("/auth/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    session_expired: Optional[str] = None,
) -> HTMLResponse:
    """Render the login page.

    The ``session_expired`` query parameter triggers a banner message when
    the HTMX 401 handler redirects here after a cookie expiry.

    Args:
        request: The current HTTP request.
        session_expired: When ``'1'``, the template renders a session-expired
            banner variant of the login form.

    Returns:
        Rendered ``auth/login.html`` template.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "auth/login.html",
        {
            "request": request,
            "session_expired": session_expired == "1",
        },
    )


@router.get("/auth/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(
    request: Request,
    success: Optional[str] = None,
) -> HTMLResponse:
    """Render the forgot password page.

    Users enter their email to receive a password reset link.
    No authentication required.

    Args:
        request: The current HTTP request.
        success: If "1", show the success message.

    Returns:
        Rendered ``auth/reset_password.html`` template without token.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "auth/reset_password.html",
        {
            "request": request,
            "token": None,
            "error": None,
            "success": success == "1",
        },
    )


@router.get("/auth/reset-password", response_class=HTMLResponse)
async def reset_password_page(
    request: Request,
    token: Optional[str] = None,
    success: Optional[str] = None,
) -> HTMLResponse:
    """Render the reset password form page.

    When a token is present in the query string (from the email link),
    displays the new password form. Otherwise, shows the request-reset form.
    No authentication required.

    Args:
        request: The current HTTP request.
        token: Password reset token from the email link.
        success: If "1", show the success message.

    Returns:
        Rendered ``auth/reset_password.html`` template.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "auth/reset_password.html",
        {
            "request": request,
            "token": token,
            "error": None,
            "success": success == "1",
        },
    )


@router.get("/auth/register", response_class=HTMLResponse)
async def register_page(
    request: Request,
    success: Optional[str] = None,
) -> HTMLResponse:
    """Render the user registration page.

    No authentication required. New accounts are created with
    ``is_verified=False`` and require admin activation.

    Args:
        request: The current HTTP request.
        success: When ``'1'``, displays success message.

    Returns:
        Rendered ``auth/register.html`` template.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "auth/register.html",
        {
            "request": request,
            "register_success": success == "1",
        },
    )


# ---------------------------------------------------------------------------
# Admin pages
# ---------------------------------------------------------------------------


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    admin_user: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Render the admin user management page.

    Args:
        request: The current HTTP request.
        admin_user: Verified admin user from the ``require_admin`` dependency.
        db: Injected async database session.

    Returns:
        Rendered ``admin/users.html`` template.
    """
    result = await db.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "admin/users.html",
        {"request": request, "user": admin_user, "users": users},
    )


@router.get("/admin/credits", response_class=HTMLResponse)
async def admin_credits(
    request: Request,
    admin_user: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Render the admin credit allocation page.

    Args:
        request: The current HTTP request.
        admin_user: Verified admin user from the ``require_admin`` dependency.
        db: Injected async database session.

    Returns:
        Rendered ``admin/credits.html`` template.
    """
    users_result = await db.execute(select(User).order_by(User.email))
    users = users_result.scalars().all()

    alloc_query = (
        select(CreditAllocation, User.email.label("user_email"))
        .join(User, CreditAllocation.user_id == User.id)
        .order_by(CreditAllocation.allocated_at.desc())
        .limit(50)
    )
    rows = (await db.execute(alloc_query)).all()
    allocations = [
        {
            "user_email": r.user_email,
            "credits_amount": r.CreditAllocation.credits_amount,
            "valid_until": r.CreditAllocation.valid_until,
            "memo": r.CreditAllocation.memo,
            "allocated_at": r.CreditAllocation.allocated_at,
        }
        for r in rows
    ]

    tpl = _templates(request)
    return tpl.TemplateResponse(
        "admin/credits.html",
        {
            "request": request,
            "user": admin_user,
            "users": users,
            "allocations": allocations,
        },
    )


@router.get("/admin/credentials", response_class=HTMLResponse)
async def admin_credentials(
    request: Request,
    admin_user: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Render the admin credential pool management page.

    Args:
        request: The current HTTP request.
        admin_user: Verified admin user from the ``require_admin`` dependency.
        db: Injected async database session.

    Returns:
        Rendered ``admin/credentials.html`` template.
    """
    from issue_observatory.core.models.credentials import ApiCredential  # noqa: PLC0415

    result = await db.execute(
        select(ApiCredential).order_by(ApiCredential.created_at.desc())
    )
    credentials = result.scalars().all()
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "admin/credentials.html",
        {"request": request, "user": admin_user, "credentials": credentials},
    )


@router.get("/admin/health", response_class=HTMLResponse)
async def admin_health(
    request: Request,
    admin_user: Annotated[User, Depends(require_admin)],
) -> HTMLResponse:
    """Render the admin system health dashboard.

    Args:
        request: The current HTTP request.
        admin_user: Verified admin user from the ``require_admin`` dependency.

    Returns:
        Rendered ``admin/health.html`` template with SMTP status (BB-3).
    """
    from issue_observatory.core.email_service import get_email_service

    email_service = get_email_service()
    smtp_configured = email_service.is_configured()

    tpl = _templates(request)
    return tpl.TemplateResponse(
        "admin/health.html",
        {
            "request": request,
            "user": admin_user,
            "smtp_configured": smtp_configured,
        },
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@router.get("/scraping-jobs", response_class=HTMLResponse)
async def scraping_jobs_page(
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Render the scraping jobs management page.

    Allows researchers to create and monitor scraping jobs that enrich
    collected URLs with full-text content extraction.

    Args:
        request: The current HTTP request.
        current_user: The authenticated, active user.

    Returns:
        Rendered ``scraping/index.html`` template.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "scraping/index.html",
        {"request": request, "user": current_user},
    )


@router.get("/imports", response_class=HTMLResponse)
async def imports_page(
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Render the data import page.

    Allows researchers to upload CSV or NDJSON files for import, including
    Zeeschuimer-captured data from platforms without API access.

    Args:
        request: The current HTTP request.
        current_user: The authenticated, active user.

    Returns:
        Rendered ``imports/index.html`` template.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "imports/index.html",
        {"request": request, "user": current_user},
    )
