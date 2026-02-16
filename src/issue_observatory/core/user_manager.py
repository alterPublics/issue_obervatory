"""FastAPI-Users integration: UserManager, Pydantic schemas, and database adapter.

This module wires the existing ``User`` SQLAlchemy model (defined by the DB
Engineer in ``core/models/users.py``) into FastAPI-Users without modifying
that file.

The adapter maps our domain fields to the interface FastAPI-Users expects:

- ``is_superuser``: derived at runtime from ``user.role == 'admin'``
- ``is_verified``:  always ``True`` — we use ``is_active`` for admin-gated
  activation rather than a separate email-verification step.

Exports:
    UserRead, UserCreate, UserUpdate: Pydantic schemas for FastAPI-Users.
    UserManager: The FastAPI-Users manager class.
    ObservatoryUserDatabase: SQLAlchemy adapter bridging our User model.
    get_user_db: FastAPI dependency yielding ObservatoryUserDatabase.
    get_user_manager: FastAPI dependency yielding UserManager.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any, Optional

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users.db import SQLAlchemyUserDatabase
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.config.settings import get_settings
from issue_observatory.core.database import get_db
from issue_observatory.core.models.users import User


# ---------------------------------------------------------------------------
# Pydantic schemas (FastAPI-Users contract)
# ---------------------------------------------------------------------------


class UserRead(BaseModel):
    """Public user representation returned by API endpoints.

    ``is_superuser`` is derived from ``role == 'admin'`` at serialisation
    time.  ``is_verified`` is always ``True`` because this project uses
    admin activation (``is_active``) rather than email verification.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: Optional[str] = None
    role: str
    is_active: bool
    is_superuser: bool
    is_verified: bool


class UserCreate(BaseModel):
    """Schema for new user registration.

    New accounts are inactive by default until an admin enables them.
    The ``role`` field cannot be set at registration; it defaults to
    ``'researcher'`` in the database.
    """

    email: EmailStr
    password: str
    display_name: Optional[str] = None


class UserUpdate(BaseModel):
    """Schema for self-service profile updates.

    Only ``password``, ``display_name``, and ``email`` may be changed by
    the user themselves.  ``role`` and ``is_active`` are admin-only fields
    managed through the admin routes.
    """

    password: Optional[str] = None
    display_name: Optional[str] = None
    email: Optional[EmailStr] = None


# ---------------------------------------------------------------------------
# Virtual-field helper
# ---------------------------------------------------------------------------


def _attach_virtual_fields(user: User) -> User:
    """Attach ``is_superuser`` and ``is_verified`` shims to a ``User`` row.

    FastAPI-Users expects these attributes.  Our model expresses the same
    concepts through ``role`` and ``is_active`` respectively.

    Args:
        user: The SQLAlchemy ``User`` instance to enrich in-place.

    Returns:
        The same ``user`` instance with virtual attributes set.
    """
    user.is_superuser = user.role == "admin"  # type: ignore[attr-defined]
    user.is_verified = True  # type: ignore[attr-defined]
    return user


# ---------------------------------------------------------------------------
# Custom SQLAlchemy user database adapter
# ---------------------------------------------------------------------------


class ObservatoryUserDatabase(SQLAlchemyUserDatabase):
    """SQLAlchemy adapter that bridges our ``User`` model to FastAPI-Users.

    Overrides the CRUD methods to:
    1. Strip ``is_superuser`` / ``is_verified`` from write dicts (those
       columns do not exist on our table).
    2. Force ``is_active=False`` on new registrations (admin must activate).
    3. Attach virtual ``is_superuser`` and ``is_verified`` attributes to
       every returned ``User`` instance.
    """

    async def get(self, id: Any) -> Optional[User]:  # type: ignore[override]
        """Fetch a user by primary key and attach virtual fields.

        Args:
            id: The user's UUID primary key.

        Returns:
            Enriched ``User`` instance, or ``None`` if not found.
        """
        user = await super().get(id)
        return _attach_virtual_fields(user) if user else None

    async def get_by_email(self, email: str) -> Optional[User]:  # type: ignore[override]
        """Fetch a user by email address and attach virtual fields.

        Args:
            email: The user's email address (case-insensitive lookup
                is handled by the database unique index).

        Returns:
            Enriched ``User`` instance, or ``None`` if not found.
        """
        user = await super().get_by_email(email)
        return _attach_virtual_fields(user) if user else None

    async def create(self, create_dict: dict[str, Any]) -> User:  # type: ignore[override]
        """Create a new user row and attach virtual fields.

        Strips FastAPI-Users-specific fields that are absent from our
        schema and enforces ``is_active=False`` for all new registrations.

        Args:
            create_dict: Field mapping for the new ``User`` row, as built
                by FastAPI-Users from a ``UserCreate`` schema.

        Returns:
            Enriched ``User`` instance.
        """
        create_dict.pop("is_superuser", None)
        create_dict.pop("is_verified", None)
        create_dict["is_active"] = False  # admin must activate
        user = await super().create(create_dict)
        return _attach_virtual_fields(user)

    async def update(self, user: User, update_dict: dict[str, Any]) -> User:  # type: ignore[override]
        """Update an existing user row and re-attach virtual fields.

        Args:
            user: The existing ``User`` instance to update.
            update_dict: Fields to update.

        Returns:
            Enriched updated ``User`` instance.
        """
        update_dict.pop("is_superuser", None)
        update_dict.pop("is_verified", None)
        updated = await super().update(user, update_dict)
        return _attach_virtual_fields(updated)

    async def get_by_api_key(self, api_key: str) -> Optional[User]:
        """Fetch a user by their programmatic API key.

        Args:
            api_key: The opaque 64-character API key string.

        Returns:
            Enriched ``User`` instance, or ``None`` if not found.
        """
        result = await self.session.execute(
            select(User).where(User.api_key == api_key)
        )
        user = result.scalars().first()
        return _attach_virtual_fields(user) if user else None


# ---------------------------------------------------------------------------
# UserManager
# ---------------------------------------------------------------------------


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """FastAPI-Users UserManager with project-specific lifecycle hooks.

    Uses ``secret_key`` from application settings for both password-reset
    and verification token signing.  Email verification is a no-op in this
    project; admin activation via ``is_active`` is the gating mechanism.
    """

    @property
    def reset_password_token_secret(self) -> str:
        """Secret key used to sign password-reset tokens.

        Returns:
            The application ``secret_key`` from settings.
        """
        return get_settings().secret_key

    @property
    def verification_token_secret(self) -> str:
        """Secret key used to sign email-verification tokens.

        Returns:
            The application ``secret_key`` from settings.
        """
        return get_settings().secret_key

    async def on_after_register(
        self, user: User, request: Optional[Request] = None
    ) -> None:
        """Log new user registration; account stays inactive until admin approves.

        Args:
            user: The newly created ``User`` instance.
            request: The originating HTTP request, if available.
        """
        import structlog  # noqa: PLC0415

        logger = structlog.get_logger(__name__)
        logger.info(
            "new_user_registered",
            user_id=str(user.id),
            email=user.email,
            note="account inactive until admin approval",
        )

    async def on_after_forgot_password(
        self, user: User, token: str, request: Optional[Request] = None
    ) -> None:
        """Log password-reset token generation.

        In production, integrate an email backend here to send the reset link.

        Args:
            user: The ``User`` who requested a password reset.
            token: The signed reset token (do not log in full in production).
            request: The originating HTTP request, if available.
        """
        import structlog  # noqa: PLC0415

        logger = structlog.get_logger(__name__)
        logger.info(
            "password_reset_requested",
            user_id=str(user.id),
            email=user.email,
        )

    async def on_after_request_verify(
        self, user: User, token: str, request: Optional[Request] = None
    ) -> None:
        """No-op verification hook; this project uses admin activation instead.

        Args:
            user: The ``User`` for whom verification was requested.
            token: The signed verification token (unused).
            request: The originating HTTP request, if available.
        """
        import structlog  # noqa: PLC0415

        logger = structlog.get_logger(__name__)
        logger.info(
            "email_verification_requested_noop",
            user_id=str(user.id),
            note="admin activation is used instead of email verification",
        )


# ---------------------------------------------------------------------------
# FastAPI dependency factories
# ---------------------------------------------------------------------------


async def get_user_db(
    session: AsyncSession = Depends(get_db),
) -> AsyncGenerator[ObservatoryUserDatabase, None]:
    """Provide an ``ObservatoryUserDatabase`` session for FastAPI-Users.

    Args:
        session: An injected async SQLAlchemy session from ``get_db``.

    Yields:
        An ``ObservatoryUserDatabase`` bound to the current session.
    """
    yield ObservatoryUserDatabase(session, User)


async def get_user_manager(
    user_db: ObservatoryUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    """Provide a ``UserManager`` instance for FastAPI-Users.

    Args:
        user_db: An injected ``ObservatoryUserDatabase``.

    Yields:
        A ``UserManager`` instance ready for use.
    """
    yield UserManager(user_db)
