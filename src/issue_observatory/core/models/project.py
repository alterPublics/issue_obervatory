"""Project ORM model.

Projects are organizational units that group related query designs together.
They provide a hierarchical structure: User → Project → Query Designs → Collection Runs.

Visibility controls access:
- 'private': visible only to the owner.
- 'shared': visible to all researchers in the system (future enhancement).

Owned by the DB Engineer.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from issue_observatory.core.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from issue_observatory.core.models.collection import CollectionRun
    from issue_observatory.core.models.query_design import QueryDesign
    from issue_observatory.core.models.users import User


class Project(Base, TimestampMixin):
    """An organizational container grouping related query designs.

    Projects help researchers organize their work by grouping query designs
    that investigate related research questions or target the same issue domain.

    Attributes:
        id: Unique identifier.
        name: Human-readable project name.
        description: Optional detailed description of the project purpose.
        owner_id: Foreign key to the user who owns this project.
        visibility: Access control level ('private' or 'shared').
        created_at: Timestamp when the project was created (from TimestampMixin).
        updated_at: Timestamp of last modification (from TimestampMixin).

    Relationships:
        owner: The User who owns this project.
        query_designs: List of QueryDesign instances attached to this project.
    """

    __tablename__ = "projects"
    __table_args__ = (
        sa.UniqueConstraint("owner_id", "name", name="uq_project_owner_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(
        sa.String(200),
        nullable=False,
    )
    description: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    visibility: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        server_default=sa.text("'private'"),
    )

    # Relationships
    owner: Mapped[User] = relationship(
        "User",
        foreign_keys=[owner_id],
        back_populates="projects",
    )
    query_designs: Mapped[list[QueryDesign]] = relationship(
        "QueryDesign",
        back_populates="project",
        order_by="QueryDesign.name",
    )
    collection_runs: Mapped[list[CollectionRun]] = relationship(
        "CollectionRun",
        back_populates="project",
    )

    def __repr__(self) -> str:
        return (
            f"<Project id={self.id} name={self.name!r} "
            f"owner_id={self.owner_id}>"
        )
