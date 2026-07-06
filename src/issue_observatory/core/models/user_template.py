"""User template ORM model for preconfigured user profiles.

Admins create templates to quickly provision users with consistent
credit amounts, platform access lists, and credential modes.

Owned by the DB Engineer.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from issue_observatory.core.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from issue_observatory.core.models.users import User


class UserTemplate(Base, TimestampMixin):
    """A preconfigured profile for creating users with consistent settings.

    Admins define templates with credit amounts, platform access rules,
    and central credential toggles.  When a user is created from a template,
    the settings are copied to the user record (independently editable afterward).

    Platform access logic:
    - ``allowed_platforms`` empty + ``disallowed_platforms`` empty → all platforms
    - ``allowed_platforms`` non-empty → whitelist (only those platforms)
    - ``disallowed_platforms`` always blocks listed platforms (takes precedence)
    """

    __tablename__ = "user_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(
        sa.String(200),
        unique=True,
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
    )
    credits_amount: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    )
    allowed_platforms: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    disallowed_platforms: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    use_central_credentials: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.text("true"),
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    creator: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[created_by],
    )

    def __repr__(self) -> str:
        return (
            f"<UserTemplate id={self.id} name={self.name!r} "
            f"credits={self.credits_amount}>"
        )
