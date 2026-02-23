"""Authentication routes: login, logout, registration, and password reset.

Sets up two FastAPI-Users authentication backends:

1. **Cookie backend** (``name="cookie"``) — used by the browser UI.
   Stores the JWT access token in an HttpOnly, SameSite=Lax cookie named
   ``access_token`` (30 min TTL).  This is the primary transport for the
   Jinja2/HTMX frontend.

2. **Bearer backend** (``name="bearer"``) — used for programmatic API
   access.  Clients pass ``Authorization: Bearer <token>`` headers.

Both backends share the same ``JWTStrategy`` (same secret and lifetime),
so a token issued via one transport is valid on the other.

Exported names:
    fastapi_users: the ``FastAPIUsers`` instance (used in ``main.py`` for
        dependency injection shortcuts and mounting routers).
    cookie_backend: the cookie ``AuthenticationBackend``.
    bearer_backend: the bearer ``AuthenticationBackend``.
    auth_router: combined APIRouter with all auth sub-routers attached.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi_users import FastAPIUsers
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    CookieTransport,
    JWTStrategy,
)

from issue_observatory.config.settings import get_settings
from issue_observatory.core.models.users import User
from issue_observatory.core.user_manager import (
    UserCreate,
    UserRead,
    UserUpdate,
    get_user_manager,
)

# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------

# Determine if we should use secure cookies based on debug mode
settings = get_settings()
cookie_secure = not settings.debug  # Only set Secure flag in production

cookie_transport = CookieTransport(
    cookie_name="access_token",
    cookie_max_age=1800,  # 30 minutes
    cookie_httponly=True,
    cookie_samesite="lax",
    cookie_secure=cookie_secure,
)
"""HttpOnly, SameSite=Lax cookie transport for browser-based sessions.

The short 30-minute TTL limits the exposure window if a cookie is leaked.
``SameSite=Lax`` mitigates CSRF while allowing top-level navigations.
The ``Secure`` flag is only set when ``debug=False`` to allow HTTP development.
"""

bearer_transport = BearerTransport(tokenUrl="/auth/bearer/login")
"""Bearer token transport for programmatic API clients.

Clients include ``Authorization: Bearer <token>`` on every request.
Token URL is documented in the auto-generated OpenAPI schema.
"""


# ---------------------------------------------------------------------------
# JWT strategy factory
# ---------------------------------------------------------------------------


def get_jwt_strategy() -> JWTStrategy:
    """Build a ``JWTStrategy`` from application settings.

    Called once per request by FastAPI-Users' dependency injection.
    The strategy is not cached so that a settings reload (e.g. in tests)
    picks up a fresh secret.

    Returns:
        A ``JWTStrategy`` configured with ``secret_key`` from settings and
        a 30-minute token lifetime.
    """
    settings = get_settings()
    return JWTStrategy(
        secret=settings.secret_key,
        lifetime_seconds=settings.access_token_expire_minutes * 60,
    )


# ---------------------------------------------------------------------------
# Authentication backends
# ---------------------------------------------------------------------------

cookie_backend: AuthenticationBackend = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)
"""Cookie-based auth backend — primary transport for the browser UI."""

bearer_backend: AuthenticationBackend = AuthenticationBackend(
    name="bearer",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)
"""Bearer-token auth backend — primary transport for API clients."""

# ---------------------------------------------------------------------------
# FastAPIUsers instance
# ---------------------------------------------------------------------------

fastapi_users: FastAPIUsers[User, uuid.UUID] = FastAPIUsers(
    get_user_manager,
    [cookie_backend, bearer_backend],
)
"""Central FastAPI-Users instance.

Used in ``api/main.py`` to mount auth routers, and in ``api/dependencies.py``
to obtain ``current_user`` / ``current_active_user`` / ``current_superuser``
dependency shortcuts.
"""

# ---------------------------------------------------------------------------
# Router assembly
# ---------------------------------------------------------------------------

auth_router = APIRouter()
"""Combined router that mounts all FastAPI-Users sub-routers.

Included in the main FastAPI app under the ``/auth`` prefix.

Routes provided:
- Cookie login/logout:  POST /auth/cookie/login, POST /auth/cookie/logout
- Bearer login/logout:  POST /auth/bearer/login, POST /auth/bearer/logout
- Registration:         POST /auth/register
- Password reset:       POST /auth/forgot-password, POST /auth/reset-password
"""

# Cookie login / logout
auth_router.include_router(
    fastapi_users.get_auth_router(cookie_backend),
    prefix="/cookie",
    tags=["auth:cookie"],
)

# Bearer login / logout
auth_router.include_router(
    fastapi_users.get_auth_router(bearer_backend),
    prefix="/bearer",
    tags=["auth:bearer"],
)

# Registration endpoint — new accounts land in is_active=False state
auth_router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    tags=["auth:register"],
)

# Password reset (forgot + reset with token)
auth_router.include_router(
    fastapi_users.get_reset_password_router(),
    tags=["auth:password-reset"],
)

# Users router (self-service profile GET/PATCH + admin GET/PATCH/DELETE)
users_router = APIRouter()
"""FastAPI-Users users router (profile management).

Included in the main app under the ``/users`` prefix.

Routes provided:
- GET  /users/me
- PATCH /users/me
- GET  /users/{id}   (superuser only)
- PATCH /users/{id}  (superuser only)
- DELETE /users/{id} (superuser only)
"""

users_router.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    tags=["users"],
)
