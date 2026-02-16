"""FastAPI dependency injection providers.

Provides reusable dependencies for authentication, authorisation, pagination,
and settings access.  All auth dependencies delegate to FastAPI-Users via the
``fastapi_users`` instance defined in ``api/routes/auth.py``.

Dependency hierarchy::

    get_optional_user         — returns None if unauthenticated
    get_current_user          — requires any valid JWT (cookie or bearer)
    get_current_active_user   — additionally requires is_active=True
    require_admin             — additionally requires role='admin'

Note on import order:
    This module imports from ``api.routes.auth`` at the function level (inside
    each dependency function body) to avoid a circular import.  The chain is:
    ``auth.py`` → ``user_manager.py`` → ``database.py``, with no back-edge to
    ``dependencies.py``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, AsyncGenerator, Optional

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, status

from issue_observatory.config.settings import get_settings
from issue_observatory.core.models.users import User


# ---------------------------------------------------------------------------
# Internal helpers that resolve the FastAPIUsers instance at call time
# ---------------------------------------------------------------------------


def _current_user_dep(*, active: bool, optional: bool):  # type: ignore[return]
    """Return a FastAPI-Users ``current_user`` callable dependency.

    Defers the import of ``fastapi_users`` until the dependency is first
    resolved by FastAPI, breaking the module-level circular import.

    Args:
        active: If ``True``, reject inactive users with HTTP 403.
        optional: If ``True``, return ``None`` instead of raising 401.

    Returns:
        A FastAPI ``Depends``-compatible callable.
    """
    from issue_observatory.api.routes.auth import fastapi_users  # noqa: PLC0415

    return fastapi_users.current_user(active=active, optional=optional)


# ---------------------------------------------------------------------------
# Core auth dependencies
# ---------------------------------------------------------------------------


async def get_current_user(
    user: Annotated[User, Depends(_current_user_dep(active=False, optional=False))],
) -> User:
    """Require a valid JWT (cookie or bearer); user need not be active.

    Prefer ``get_current_active_user`` for most routes.  Use this dependency
    only where inactive users still need access (e.g. an "account pending"
    status page).

    Args:
        user: Injected ``User`` instance from FastAPI-Users.

    Returns:
        The authenticated ``User`` (may have ``is_active=False``).

    Raises:
        HTTPException 401: If no valid JWT is present.
    """
    return user


async def get_current_active_user(
    user: Annotated[User, Depends(_current_user_dep(active=True, optional=False))],
) -> User:
    """Require a valid JWT and ``is_active=True``.

    Standard dependency for any route that requires a logged-in, approved
    researcher account.

    Args:
        user: Injected ``User`` instance from FastAPI-Users.

    Returns:
        The active ``User``.

    Raises:
        HTTPException 401: If no valid JWT is present.
        HTTPException 403: If the user account is not active.
    """
    return user


async def get_optional_user(
    user: Annotated[
        Optional[User],
        Depends(_current_user_dep(active=True, optional=True)),
    ],
) -> Optional[User]:
    """Return the current active user, or ``None`` if unauthenticated.

    Used on public-facing routes where authentication is not required but
    user context is useful when present (e.g. public content browsers,
    landing pages).

    Args:
        user: Optionally injected ``User`` instance from FastAPI-Users.

    Returns:
        The active ``User``, or ``None`` if the request carries no valid JWT.
    """
    return user


async def require_admin(
    user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    """Require an active user with ``role='admin'``.

    Guards admin-only endpoints: user activation, credit allocation,
    credential management, and system health views.

    Args:
        user: An active ``User`` from ``get_current_active_user``.

    Returns:
        The admin ``User``.

    Raises:
        HTTPException 403: If the user's role is not ``'admin'``.
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required.",
        )
    return user


# ---------------------------------------------------------------------------
# Redis async client
# ---------------------------------------------------------------------------


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """Yield a per-request async Redis client and close it on teardown.

    Uses ``REDIS_URL`` from application settings.  The connection is opened
    lazily on first I/O and closed after the request completes.

    Yields:
        An ``aioredis.Redis`` (``redis.asyncio.Redis``) instance configured
        to decode responses as strings.

    Example::

        @router.get("/stream")
        async def stream(redis: Annotated[aioredis.Redis, Depends(get_redis)]):
            pubsub = redis.pubsub()
            ...
    """
    settings = get_settings()
    client: aioredis.Redis = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
    )
    try:
        yield client
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Ownership guard
# ---------------------------------------------------------------------------


def ownership_guard(resource_owner_id: uuid.UUID, current_user: User) -> None:
    """Raise HTTP 403 if ``current_user`` is neither the owner nor an admin.

    Call this inside route handlers that operate on user-owned resources
    (query designs, collection runs, etc.) to enforce data isolation.

    Example usage::

        @router.get("/query-designs/{design_id}")
        async def get_design(
            design_id: uuid.UUID,
            db: AsyncSession = Depends(get_db),
            current_user: User = Depends(get_current_active_user),
        ):
            design = await db.get(QueryDesign, design_id)
            if design is None:
                raise HTTPException(status_code=404)
            ownership_guard(design.owner_id, current_user)
            return design

    Args:
        resource_owner_id: The ``owner_id`` / ``initiated_by`` UUID of the
            resource being accessed.
        current_user: The authenticated user making the request.

    Raises:
        HTTPException 403: If ``current_user.id != resource_owner_id``
            and ``current_user.role != 'admin'``.
    """
    if current_user.role == "admin":
        return
    if current_user.id != resource_owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this resource.",
        )


# ---------------------------------------------------------------------------
# Pagination parameters
# ---------------------------------------------------------------------------


@dataclass
class PaginationParams:
    """Cursor-pagination parameters shared across list endpoints.

    Attributes:
        cursor: Opaque pagination cursor (typically a stringified UUID or
            ISO 8601 timestamp from the last record of the previous page).
        page_size: Number of records to return per page (1–200).
    """

    cursor: Optional[str]
    page_size: int


def get_pagination(
    cursor: Optional[str] = None,
    page_size: int = 50,
) -> PaginationParams:
    """Parse and validate cursor-pagination query parameters.

    Args:
        cursor: Optional opaque cursor string from the previous response.
        page_size: Number of items per page.  Clamped to 1–200; defaults
            to 50.

    Returns:
        A ``PaginationParams`` dataclass with validated values.

    Raises:
        HTTPException 422: If ``page_size`` is outside the range 1–200.
    """
    if not 1 <= page_size <= 200:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="page_size must be between 1 and 200.",
        )
    return PaginationParams(cursor=cursor, page_size=page_size)
