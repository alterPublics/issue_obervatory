"""ProjectCollaborator ORM model.

Associates users with projects they have been granted access to.
Supports role-based sharing: 'viewer' (read-only) with future extensibility
to 'editor' (read + launch collections).

Owned by the DB Engineer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from issue_observatory.core.models.base import Base

if TYPE_CHECKING:
    from issue_observatory.core.models.project import Project
    from issue_observatory.core.models.users import User


class ProjectCollaborator(Base):
    """A user granted access to a project they do not own.

    The composite primary key on (project_id, user_id) prevents duplicate
    grants.  CASCADE deletes ensure rows are cleaned up when either the
    project or the user is removed.

    Attributes:
        project_id: FK to the shared project.
        user_id: FK to the collaborator user.
        role: Access level — currently only 'viewer'.
        granted_by: FK to the user who granted access (nullable for admin grants).
        granted_at: Timestamp of when access was granted.
    """

    __tablename__ = "project_collaborators"
    __table_args__ = (
        sa.PrimaryKeyConstraint("project_id", "user_id"),
        sa.Index("ix_project_collaborators_user_id", "user_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        server_default=sa.text("'viewer'"),
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )

    # Relationships
    project: Mapped[Project] = relationship(
        "Project",
        back_populates="collaborators",
    )
    user: Mapped[User] = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="project_collaborations",
    )
    grantor: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[granted_by],
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectCollaborator project_id={self.project_id} "
            f"user_id={self.user_id} role={self.role!r}>"
        )
