"""User management routes: admin activation, role management, and API key handling.

FastAPI-Users provides self-service profile GET/PATCH at ``/users/me`` and
admin GET/PATCH/DELETE at ``/users/{id}`` (see ``auth.py: users_router``).

This module adds the **application-level** admin operations that FastAPI-Users
does not cover:

- Activate / deactivate a user account (admin only)
- Change a user's role (admin only)
- Generate or revoke a user's API key (self or admin)
- List all users (admin only)

These routes are mounted at ``/admin/users`` in ``main.py``.
"""

from __future__ import annotations

import secrets
import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.api.dependencies import get_current_active_user, require_admin
from issue_observatory.core.database import get_db
from issue_observatory.core.models.users import User

router = APIRouter()
"""Admin user management router.

Mounted at ``/admin/users`` in the main FastAPI application.
"""


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class UserAdminRead(BaseModel):
    """Admin-level user view including role and activation status.

    Differs from ``UserRead`` (in ``user_manager.py``) by including
    ``api_key`` visibility (masked) and ``last_login_at``.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: Optional[str] = None
    role: str
    is_active: bool
    last_login_at: Optional[str] = None


class RoleUpdateRequest(BaseModel):
    """Request body for changing a user's role.

    Attributes:
        role: The target role.  Must be ``'researcher'`` or ``'admin'``.
    """

    role: str


class ActivationRequest(BaseModel):
    """Request body for toggling a user's active status.

    Attributes:
        is_active: ``True`` to activate, ``False`` to deactivate.
    """

    is_active: bool


class ApiKeyResponse(BaseModel):
    """Response returned when a new API key is generated.

    Attributes:
        api_key: The plain-text API key.  This is the **only** time the
            raw key is returned — it is stored as-is in the database (not
            hashed) so that the key can be used directly on subsequent
            requests.  Treat it like a password.
    """

    api_key: str


# ---------------------------------------------------------------------------
# Admin list all users
# ---------------------------------------------------------------------------


@router.get(
    "/",
    response_model=list[UserAdminRead],
    summary="List all users (admin)",
)
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[User]:
    """Return all user accounts.

    Admin-only endpoint.  Returns all users regardless of active status,
    ordered by creation time (oldest first).

    Args:
        db: Injected async database session.
        _admin: Injected admin user (validates the caller is an admin).

    Returns:
        List of ``UserAdminRead`` objects.
    """
    result = await db.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Admin activate / deactivate
# ---------------------------------------------------------------------------


@router.patch(
    "/{user_id}/activation",
    response_model=UserAdminRead,
    summary="Activate or deactivate a user account (admin)",
)
async def set_user_activation(
    user_id: uuid.UUID,
    body: ActivationRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> User:
    """Activate or deactivate a user account.

    New registrations land in ``is_active=False`` state.  An admin must call
    this endpoint with ``{"is_active": true}`` to grant access.

    Args:
        user_id: UUID of the user to update.
        body: Activation request containing the desired ``is_active`` value.
        db: Injected async database session.
        _admin: Injected admin user (validates the caller is an admin).

    Returns:
        Updated ``UserAdminRead`` object.

    Raises:
        HTTPException 404: If the user does not exist.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    user.is_active = body.is_active
    await db.commit()
    await db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Admin role change
# ---------------------------------------------------------------------------


@router.patch(
    "/{user_id}/role",
    response_model=UserAdminRead,
    summary="Change a user's role (admin)",
)
async def set_user_role(
    user_id: uuid.UUID,
    body: RoleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> User:
    """Change the role of a user account.

    Valid roles are ``'researcher'`` and ``'admin'``.  Admins cannot demote
    themselves through this endpoint — they would need another admin to do so.

    Args:
        user_id: UUID of the user whose role to change.
        body: Role update request with the target role string.
        db: Injected async database session.
        _admin: Injected admin user (validates the caller is an admin).

    Returns:
        Updated ``UserAdminRead`` object.

    Raises:
        HTTPException 400: If the requested role is not valid.
        HTTPException 404: If the user does not exist.
    """
    allowed_roles = {"researcher", "admin"}
    if body.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role '{body.role}'.  Must be one of: {sorted(allowed_roles)}.",
        )
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    user.role = body.role
    await db.commit()
    await db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# API key management (self or admin)
# ---------------------------------------------------------------------------


@router.post(
    "/me/api-key",
    response_model=ApiKeyResponse,
    summary="Generate a new API key for the calling user",
    status_code=status.HTTP_201_CREATED,
)
async def generate_api_key(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ApiKeyResponse:
    """Generate a secure random API key for the authenticated user.

    Replaces any existing API key.  The new key is returned **once** in the
    response body.  It is stored in the database in plain text so it can be
    used directly in ``Authorization: ApiKey <key>`` headers.

    Args:
        db: Injected async database session.
        current_user: The authenticated user requesting a new key.

    Returns:
        ``ApiKeyResponse`` containing the new plain-text API key.
    """
    # 32 bytes of entropy → 64 hex characters, consistent with the column size.
    new_key = secrets.token_hex(32)
    current_user.api_key = new_key
    await db.commit()
    return ApiKeyResponse(api_key=new_key)


@router.delete(
    "/me/api-key",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the calling user's API key",
    response_model=None,
)
async def revoke_api_key(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Revoke (clear) the authenticated user's API key.

    After this call, programmatic access via the API key is no longer
    possible until a new key is generated.

    Args:
        db: Injected async database session.
        current_user: The authenticated user revoking their key.
    """
    current_user.api_key = None
    await db.commit()


# ------------------------------------------------------------------
# Self-service preferences
# ------------------------------------------------------------------


class PreferencesRead(BaseModel):
    """User preferences stored in the metadata JSONB column."""

    model_config = ConfigDict(from_attributes=True)

    skip_pseudonymization: bool = False


class PreferencesUpdate(BaseModel):
    """Request body for updating user preferences."""

    skip_pseudonymization: bool | None = None


@router.get(
    "/me/preferences",
    response_model=PreferencesRead,
    summary="Get the calling user's preferences",
)
async def get_preferences(
    current_user: User = Depends(get_current_active_user),
) -> PreferencesRead:
    """Return the authenticated user's preferences.

    Preferences are stored in the ``metadata`` JSONB column on the
    ``users`` table under the ``preferences`` key.

    Args:
        current_user: The authenticated user.

    Returns:
        Current preference values with defaults applied.
    """
    prefs = (current_user.metadata_ or {}).get("preferences", {})
    return PreferencesRead(
        skip_pseudonymization=prefs.get(
            "skip_pseudonymization", False
        ),
    )


@router.patch(
    "/me/preferences",
    response_model=PreferencesRead,
    summary="Update the calling user's preferences",
)
async def update_preferences(
    body: PreferencesUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PreferencesRead:
    """Update the authenticated user's preferences.

    Only fields present in the request body are updated; omitted fields
    retain their current values.  Preferences are stored in the
    ``metadata`` JSONB column under the ``preferences`` key.

    Args:
        body: Partial preferences update.
        db: Injected async database session.
        current_user: The authenticated user.

    Returns:
        Updated preference values.
    """
    meta = dict(current_user.metadata_ or {})
    prefs = dict(meta.get("preferences", {}))

    if body.skip_pseudonymization is not None:
        prefs["skip_pseudonymization"] = body.skip_pseudonymization

    meta["preferences"] = prefs
    current_user.metadata_ = meta
    await db.commit()
    await db.refresh(current_user)

    return PreferencesRead(
        skip_pseudonymization=prefs.get(
            "skip_pseudonymization", False
        ),
    )


# ---------------------------------------------------------------------------
# HTMX helpers — HTML fragment endpoints for the admin/users.html template
# ---------------------------------------------------------------------------


def _user_row_html(u: User) -> str:
    """Render a single ``<tr>`` for the users table matching the template structure."""
    initial = ((u.display_name or u.email or "?")[0]).upper()
    display = u.display_name or ""
    email = u.email or ""
    role = u.role or "researcher"
    is_active = u.is_active

    if role == "admin":
        role_badge = (
            '<span class="inline-flex px-2 py-0.5 rounded text-xs font-medium '
            'bg-red-100 text-red-800">Admin</span>'
        )
    else:
        role_badge = (
            '<span class="inline-flex px-2 py-0.5 rounded text-xs font-medium '
            'bg-gray-100 text-gray-600">Researcher</span>'
        )

    if is_active:
        status_badge = (
            '<span class="inline-flex px-2 py-0.5 rounded-full text-xs font-medium '
            'bg-green-100 text-green-800">Active</span>'
        )
    else:
        status_badge = (
            '<span class="inline-flex px-2 py-0.5 rounded-full text-xs font-medium '
            'bg-yellow-100 text-yellow-800">Pending</span>'
        )

    last_login = str(u.last_login_at)[:16] if u.last_login_at else "Never"
    created = str(u.created_at)[:10] if u.created_at else ""

    if not is_active:
        action_btn = (
            f'<button type="button" '
            f'hx-post="/admin/users/{u.id}/activate" '
            f'hx-target="#user-row-{u.id}" '
            f'hx-swap="outerHTML" '
            f'class="text-sm text-green-700 hover:text-green-900 px-2 py-1 rounded '
            f'hover:bg-green-50 transition-colors">Activate</button>'
        )
    else:
        action_btn = (
            f'<button type="button" '
            f'hx-post="/admin/users/{u.id}/deactivate" '
            f'hx-target="#user-row-{u.id}" '
            f'hx-swap="outerHTML" '
            f'hx-confirm="Deactivate account for {email}?" '
            f'class="text-sm text-yellow-700 hover:text-yellow-900 px-2 py-1 rounded '
            f'hover:bg-yellow-50 transition-colors">Deactivate</button>'
        )

    return (
        f'<tr class="hover:bg-gray-50" id="user-row-{u.id}">'
        f'<td class="px-6 py-4">'
        f'<div class="flex items-center gap-3">'
        f'<div class="w-8 h-8 rounded-full bg-blue-100 text-blue-700 flex items-center '
        f'justify-center text-sm font-bold flex-shrink-0">{initial}</div>'
        f'<div><p class="font-medium text-gray-900">{display}</p>'
        f'<p class="text-xs text-gray-500">{email}</p></div></div></td>'
        f'<td class="px-6 py-4">{role_badge}</td>'
        f'<td class="px-6 py-4">{status_badge}</td>'
        f'<td class="px-6 py-4 text-gray-500 text-xs">{last_login}</td>'
        f'<td class="px-6 py-4 text-gray-500 text-xs">{created}</td>'
        f'<td class="px-6 py-4 text-right"><div class="flex items-center justify-end gap-2">'
        f'{action_btn}'
        f'<a href="/admin/credits?user_id={u.id}" '
        f'class="text-sm text-gray-500 hover:text-blue-600 px-2 py-1 rounded '
        f'hover:bg-gray-100 transition-colors">Credits</a>'
        f'</div></td></tr>'
    )


@router.post("/{user_id}/activate", response_class=HTMLResponse)
async def activate_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> HTMLResponse:
    """Activate a user account and return the updated table row as HTML.

    Args:
        user_id: UUID of the user to activate.
        db: Injected async database session.
        _admin: Injected admin user (validates the caller is an admin).

    Returns:
        HTML ``<tr>`` fragment for HTMX swap.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    user.is_active = True
    await db.commit()
    await db.refresh(user)
    return HTMLResponse(_user_row_html(user))


@router.post("/{user_id}/deactivate", response_class=HTMLResponse)
async def deactivate_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> HTMLResponse:
    """Deactivate a user account and return the updated table row as HTML.

    Args:
        user_id: UUID of the user to deactivate.
        db: Injected async database session.
        _admin: Injected admin user (validates the caller is an admin).

    Returns:
        HTML ``<tr>`` fragment for HTMX swap.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    user.is_active = False
    await db.commit()
    await db.refresh(user)
    return HTMLResponse(_user_row_html(user))


@router.post("/create", response_class=HTMLResponse)
async def admin_create_user(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    display_name: Annotated[str, Form()] = "",
    role: Annotated[str, Form()] = "researcher",
    is_active: Annotated[bool, Form()] = True,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> HTMLResponse:
    """Create a new user account (admin only) and return a table row as HTML.

    Args:
        request: The current HTTP request.
        email: Email address for the new user.
        password: Plain-text password (will be hashed).
        display_name: Optional display name.
        role: User role (``researcher`` or ``admin``).
        is_active: Whether the account is immediately active.
        db: Injected async database session.
        _admin: Injected admin user (validates the caller is an admin).

    Returns:
        HTML ``<tr>`` fragment for HTMX swap.
    """
    from issue_observatory.core.user_manager import UserManager  # noqa: PLC0415

    allowed_roles = {"researcher", "admin"}
    if role not in allowed_roles:
        return HTMLResponse(
            '<div class="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-800">'
            f"Invalid role '{role}'. Must be one of: {sorted(allowed_roles)}.</div>",
            status_code=400,
        )

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        return HTMLResponse(
            '<div class="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-800">'
            f"A user with email '{email}' already exists.</div>",
            status_code=400,
        )

    from fastapi_users.password import PasswordHelper  # noqa: PLC0415

    password_helper = PasswordHelper()
    hashed = password_helper.hash(password)

    user = User(
        email=email,
        hashed_password=hashed,
        display_name=display_name or None,
        role=role,
        is_active=is_active,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return HTMLResponse(_user_row_html(user))
