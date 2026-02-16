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

from issue_observatory.api.dependencies import (
    get_current_active_user,
    get_optional_user,
    require_admin,
)
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
    """
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
) -> HTMLResponse:
    """Render the collection run live status / detail page.

    Args:
        request: The current HTTP request.
        run_id: UUID of the collection run.
        current_user: The authenticated, active user.

    Returns:
        Rendered ``collections/detail.html`` template.
    """
    tpl = _templates(request)
    return tpl.TemplateResponse(
        "collections/detail.html",
        {"request": request, "user": current_user, "run_id": str(run_id)},
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
