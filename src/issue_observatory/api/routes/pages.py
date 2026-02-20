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

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from issue_observatory.api.dependencies import (
    get_current_active_user,
    get_optional_user,
    require_admin,
)
from issue_observatory.core.database import get_db
from issue_observatory.core.models.collection import CollectionRun
from issue_observatory.core.models.query_design import QueryDesign, SearchTerm
from issue_observatory.core.models.users import User

router = APIRouter(include_in_schema=False)


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
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "arenas/index.html",
        {"request": request, "user": current_user},
    )


# ---------------------------------------------------------------------------
# Query designs
# ---------------------------------------------------------------------------


@router.get("/query-designs", response_class=HTMLResponse)
async def query_designs_list(
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Render the query design list page.

    Args:
        request: The current HTTP request.
        current_user: The authenticated, active user.

    Returns:
        Rendered ``query_designs/list.html`` template.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "query_designs/list.html",
        {"request": request, "user": current_user},
    )


@router.get("/query-designs/new", response_class=HTMLResponse)
async def query_designs_new(
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Render the query design create form.

    Args:
        request: The current HTTP request.
        current_user: The authenticated, active user.

    Returns:
        Rendered ``query_designs/editor.html`` template with empty context.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "query_designs/editor.html",
        {"request": request, "user": current_user, "design": None},
    )


@router.get("/query-designs/{design_id}", response_class=HTMLResponse)
async def query_designs_detail(
    request: Request,
    design_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Render the query design detail page.

    Args:
        request: The current HTTP request.
        design_id: UUID of the query design to display.
        current_user: The authenticated, active user.

    Returns:
        Rendered ``query_designs/detail.html`` template.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "query_designs/detail.html",
        {"request": request, "user": current_user, "design_id": str(design_id)},
    )


@router.get("/query-designs/{design_id}/edit", response_class=HTMLResponse)
async def query_designs_edit(
    request: Request,
    design_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Render the query design editor for an existing design.

    Args:
        request: The current HTTP request.
        design_id: UUID of the query design to edit.
        current_user: The authenticated, active user.

    Returns:
        Rendered ``query_designs/editor.html`` template.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "query_designs/editor.html",
        {"request": request, "user": current_user, "design_id": str(design_id)},
    )


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


@router.get("/collections", response_class=HTMLResponse)
async def collections_list(
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Render the collection run history list page.

    Args:
        request: The current HTTP request.
        current_user: The authenticated, active user.

    Returns:
        Rendered ``collections/list.html`` template.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "collections/list.html",
        {"request": request, "user": current_user},
    )


@router.get("/collections/new", response_class=HTMLResponse)
async def collections_new(
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Render the collection run launcher page.

    Args:
        request: The current HTTP request.
        current_user: The authenticated, active user.

    Returns:
        Rendered ``collections/launcher.html`` template.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "collections/launcher.html",
        {"request": request, "user": current_user},
    )


@router.get("/collections/{run_id}", response_class=HTMLResponse)
async def collections_detail(
    request: Request,
    run_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    """Render the collection run live status / detail page.

    Queries the ``CollectionRun`` record and its associated ``QueryDesign``
    and ``SearchTerm`` rows so the template can display the query design name
    and the search terms that were used in this collection.

    Args:
        request: The current HTTP request.
        run_id: UUID of the collection run.
        current_user: The authenticated, active user.
        db: Injected async database session.

    Returns:
        Rendered ``collections/detail.html`` template with an enriched
        ``run`` context dict containing ``query_design_name`` and
        ``search_terms``.
    """
    tpl = _templates(request)

    # Load the collection run, eagerly joining its query design.
    result = await db.execute(
        select(CollectionRun)
        .where(CollectionRun.id == run_id)
        .options(selectinload(CollectionRun.query_design))
    )
    collection_run = result.scalar_one_or_none()

    run_context: dict = {"id": str(run_id)}

    if collection_run is not None:
        run_context["status"] = collection_run.status
        run_context["mode"] = collection_run.mode
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
                .order_by(SearchTerm.created_at)
            )
            run_context["search_terms"] = [
                {"term": t.term, "term_type": t.term_type}
                for t in terms_result.scalars().all()
            ]
        else:
            run_context["query_design_name"] = ""
            run_context["search_terms"] = []
    else:
        run_context["search_terms"] = []

    return tpl.TemplateResponse(
        "collections/detail.html",
        {
            "request": request,
            "user": current_user,
            "run_id": str(run_id),
            "run": run_context,
        },
    )


# ---------------------------------------------------------------------------
# Content browser
# ---------------------------------------------------------------------------


@router.get("/content", response_class=HTMLResponse)
async def content_browser(
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HTMLResponse:
    """Render the content browser page.

    Args:
        request: The current HTTP request.
        current_user: The authenticated, active user.

    Returns:
        Rendered ``content/browser.html`` template.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "content/browser.html",
        {"request": request, "user": current_user},
    )


@router.get("/content/discovered-links", response_class=HTMLResponse)
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
        .where(QueryDesign.created_by == current_user.id)
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


# ---------------------------------------------------------------------------
# Admin pages
# ---------------------------------------------------------------------------


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    admin_user: Annotated[User, Depends(require_admin)],
) -> HTMLResponse:
    """Render the admin user management page.

    Args:
        request: The current HTTP request.
        admin_user: Verified admin user from the ``require_admin`` dependency.

    Returns:
        Rendered ``admin/users.html`` template.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "admin/users.html",
        {"request": request, "user": admin_user},
    )


@router.get("/admin/credits", response_class=HTMLResponse)
async def admin_credits(
    request: Request,
    admin_user: Annotated[User, Depends(require_admin)],
) -> HTMLResponse:
    """Render the admin credit allocation page.

    Args:
        request: The current HTTP request.
        admin_user: Verified admin user from the ``require_admin`` dependency.

    Returns:
        Rendered ``admin/credits.html`` template.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "admin/credits.html",
        {"request": request, "user": admin_user},
    )


@router.get("/admin/credentials", response_class=HTMLResponse)
async def admin_credentials(
    request: Request,
    admin_user: Annotated[User, Depends(require_admin)],
) -> HTMLResponse:
    """Render the admin credential pool management page.

    Args:
        request: The current HTTP request.
        admin_user: Verified admin user from the ``require_admin`` dependency.

    Returns:
        Rendered ``admin/credentials.html`` template.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "admin/credentials.html",
        {"request": request, "user": admin_user},
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
        Rendered ``admin/health.html`` template.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "admin/health.html",
        {"request": request, "user": admin_user},
    )
