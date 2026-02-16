"""SQLAlchemy declarative base and shared mixins for all ORM models.

Owned by the DB Engineer. Do not modify without DB Engineer approval.

Provides:
- Base: the DeclarativeBase subclass all models inherit from
- TimestampMixin: created_at / updated_at columns with server-side defaults
- UserOwnedMixin: owner_id FK column pointing at users.id
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for all Issue Observatory models."""

    # Use the PostgreSQL UUID type for all UUID columns by default.
    type_annotation_map = {
        uuid.UUID: UUID(as_uuid=True),
    }


class TimestampMixin:
    """Adds created_at and updated_at columns with database-side defaults.

    updated_at is refreshed by application code or a PostgreSQL trigger;
    the server default only fires on INSERT.  The onupdate kwarg on the
    Column covers the ORM-level UPDATE path.
    """

    created_at: Mapped[sa.DateTime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
    updated_at: Mapped[sa.DateTime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
        onupdate=sa.text("NOW()"),
    )


class UserOwnedMixin:
    """Adds an owner_id FK column that references users.id.

    Tables that include this mixin are user-scoped: queries must always
    filter by owner_id to enforce data isolation between researchers.
    The FK uses ON DELETE RESTRICT so that deleting a user requires
    explicit transfer or deletion of owned records first.
    """

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
