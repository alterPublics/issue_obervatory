"""User management ORM models.

Covers:
- User: the core identity record, compatible with FastAPI-Users conventions.
- CreditAllocation: admin grants a pool of credits to a user for a period.
- RefreshToken: JWT refresh token store supporting revocation.

Owned by the DB Engineer.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from issue_observatory.core.models.base import Base

if TYPE_CHECKING:
    from issue_observatory.core.models.collection import (
        CollectionRun,
        CreditTransaction,
    )
    from issue_observatory.core.models.project import Project
    from issue_observatory.core.models.query_design import QueryDesign
    from issue_observatory.core.models.zeeschuimer_import import ZeeschuimerImport


class User(Base):
    """An authenticated researcher or administrator.

    is_active defaults to False so that admin approval is required before a
    newly registered account can log in (see IMPLEMENTATION_PLAN.md §Auth).

    api_key is a randomly generated opaque token for programmatic access;
    it is distinct from the JWT issued via the browser login flow.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(
        sa.String(320),
        unique=True,
        nullable=False,
        index=True,
    )
    hashed_password: Mapped[Optional[str]] = mapped_column(
        sa.String(1024),
        nullable=True,
    )
    display_name: Mapped[Optional[str]] = mapped_column(
        sa.String(200),
        nullable=True,
    )
    role: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        server_default=sa.text("'researcher'"),
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.text("false"),
    )
    api_key: Mapped[Optional[str]] = mapped_column(
        sa.String(64),
        unique=True,
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        server_default=sa.text("'{}'"),
    )

    # Relationships
    credit_allocations: Mapped[list[CreditAllocation]] = relationship(
        "CreditAllocation",
        foreign_keys="CreditAllocation.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    projects: Mapped[list[Project]] = relationship(
        "Project",
        foreign_keys="Project.owner_id",
        back_populates="owner",
    )
    query_designs: Mapped[list[QueryDesign]] = relationship(
        "QueryDesign",
        foreign_keys="QueryDesign.owner_id",
        back_populates="owner",
    )
    collection_runs: Mapped[list[CollectionRun]] = relationship(
        "CollectionRun",
        foreign_keys="CollectionRun.initiated_by",
        back_populates="initiator",
    )
    credit_transactions: Mapped[list[CreditTransaction]] = relationship(
        "CreditTransaction",
        back_populates="user",
    )
    zeeschuimer_imports: Mapped[list[ZeeschuimerImport]] = relationship(
        "ZeeschuimerImport",
        foreign_keys="ZeeschuimerImport.initiated_by",
        back_populates="initiator",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role!r}>"


class CreditAllocation(Base):
    """A block of credits granted by an admin to a user for a given period.

    valid_until=None means the allocation has no expiry.  The credit
    service sums current non-expired allocations to compute a user's balance.
    """

    __tablename__ = "credit_allocations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    credits_amount: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
    )
    allocated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    allocated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
    valid_from: Mapped[date] = mapped_column(
        sa.Date,
        nullable=False,
    )
    valid_until: Mapped[Optional[date]] = mapped_column(
        sa.Date,
        nullable=True,
    )
    memo: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )

    # Relationships
    user: Mapped[User] = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="credit_allocations",
    )
    allocator: Mapped[Optional[User]] = relationship(
        "User",
        foreign_keys=[allocated_by],
    )

    def __repr__(self) -> str:
        return (
            f"<CreditAllocation id={self.id} user_id={self.user_id} "
            f"amount={self.credits_amount}>"
        )


class RefreshToken(Base):
    """Stored JWT refresh token supporting server-side revocation.

    Only the SHA-256 hash of the token string is persisted — the raw token
    is never stored.  Revoked tokens have revoked_at set; expired tokens are
    identified by expires_at < NOW().  A periodic cleanup job removes rows
    where expires_at < NOW() - interval '7 days'.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="refresh_tokens")

    def __repr__(self) -> str:
        return (
            f"<RefreshToken id={self.id} user_id={self.user_id} "
            f"expires_at={self.expires_at}>"
        )
