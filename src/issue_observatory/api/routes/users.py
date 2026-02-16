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
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
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
