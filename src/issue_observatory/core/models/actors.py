"""Actor ORM models.

Covers:
- ActorType: enumeration of research-relevant actor categories.
- Actor: a canonical cross-platform entity (person, organisation, outlet…).
- ActorAlias: alternative name spellings / handles for an actor.
- ActorPlatformPresence: a verified mapping of an actor to a specific
  platform account.
- ActorListMember: the many-to-many join between actors and actor lists.

Owned by the DB Engineer.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from issue_observatory.core.models.base import Base


class ActorType(str, enum.Enum):
    """Research-relevant actor type categories for Danish public discourse.

    These categories support the analytical needs of issue mapping and
    discourse tracking in the Danish media landscape.  The enum inherits
    from ``str`` so that values are stored as plain strings in the
    database (no PostgreSQL ENUM type required, avoiding migration
    complexity).

    The ``unknown`` value is the default for actors whose type has not
    been determined or does not fit other categories.
    """

    PERSON = "person"
    ORGANIZATION = "organization"
    POLITICAL_PARTY = "political_party"
    EDUCATIONAL_INSTITUTION = "educational_institution"
    TEACHERS_UNION = "teachers_union"
    THINK_TANK = "think_tank"
    MEDIA_OUTLET = "media_outlet"
    GOVERNMENT_BODY = "government_body"
    NGO = "ngo"
    COMPANY = "company"
    UNKNOWN = "unknown"

if TYPE_CHECKING:
    from issue_observatory.core.models.query_design import ActorList
    from issue_observatory.core.models.users import User


class Actor(Base):
    """A canonical real-world entity that may have a presence on many platforms.

    is_shared=True makes the actor visible to all researchers (shared library);
    is_shared=False restricts it to the creating user's query designs.

    The metadata JSONB column holds arbitrary supplementary data (e.g.
    Wikipedia URL, known country, political affiliation) without requiring
    schema changes.
    """

    __tablename__ = "actors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    canonical_name: Mapped[str] = mapped_column(
        sa.String(500),
        nullable=False,
    )
    actor_type: Mapped[Optional[str]] = mapped_column(
        sa.String(50),
        nullable=True,
    )
    description: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_shared: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.text("false"),
    )
    public_figure: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.text("false"),
        comment=(
            "GR-14 — GDPR Art. 89(1) research exemption. "
            "When True, bypass SHA-256 pseudonymization for this actor's content "
            "records: store the plain platform username as pseudonymized_author_id "
            "instead of a salted hash. "
            "MUST only be set for actors who (a) are publicly elected or appointed "
            "officials (e.g. Danish MPs, Greenlandic ministers, US federal "
            "officials) and (b) make statements strictly in their official capacity. "
            "Private individuals must remain pseudonymized regardless of "
            "public prominence. "
            "The institution's DPO should periodically review the set of "
            "public-figure-flagged actors."
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        server_default=sa.text("'{}'"),
    )

    # Relationships
    creator: Mapped[Optional[User]] = relationship(
        "User",
        foreign_keys=[created_by],
    )
    aliases: Mapped[list[ActorAlias]] = relationship(
        "ActorAlias",
        back_populates="actor",
        cascade="all, delete-orphan",
    )
    platform_presences: Mapped[list[ActorPlatformPresence]] = relationship(
        "ActorPlatformPresence",
        back_populates="actor",
        cascade="all, delete-orphan",
    )
    actor_list_memberships: Mapped[list[ActorListMember]] = relationship(
        "ActorListMember",
        back_populates="actor",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Actor id={self.id} canonical_name={self.canonical_name!r} "
            f"type={self.actor_type!r} public_figure={self.public_figure!r}>"
        )


class ActorAlias(Base):
    """An alternative name or handle for a canonical actor.

    Multiple aliases allow flexible matching during entity resolution — e.g.
    an actor known as "DR Nyheder" may also appear as "Danmarks Radio".
    """

    __tablename__ = "actor_aliases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("actors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alias: Mapped[str] = mapped_column(
        sa.String(500),
        nullable=False,
    )

    __table_args__ = (
        sa.UniqueConstraint("actor_id", "alias", name="uq_actor_alias"),
    )

    # Relationships
    actor: Mapped[Actor] = relationship("Actor", back_populates="aliases")

    def __repr__(self) -> str:
        return f"<ActorAlias actor_id={self.actor_id} alias={self.alias!r}>"


class ActorPlatformPresence(Base):
    """A confirmed platform account belonging to a canonical actor.

    The UNIQUE(platform, platform_user_id) constraint prevents the same
    platform account from being linked to two different canonical actors.

    follower_count and last_checked_at are updated by the entity resolver
    when it re-verifies platform presences.
    """

    __tablename__ = "actor_platform_presences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("actors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(
        sa.String(50),
        nullable=False,
    )
    platform_user_id: Mapped[Optional[str]] = mapped_column(
        sa.String(500),
        nullable=True,
    )
    platform_username: Mapped[Optional[str]] = mapped_column(
        sa.String(500),
        nullable=True,
    )
    profile_url: Mapped[Optional[str]] = mapped_column(
        sa.String(2000),
        nullable=True,
    )
    verified: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.text("false"),
    )
    follower_count: Mapped[Optional[int]] = mapped_column(
        sa.BigInteger,
        nullable=True,
    )
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "platform",
            "platform_user_id",
            name="uq_actor_presence_platform_user",
        ),
    )

    # Relationships
    actor: Mapped[Actor] = relationship(
        "Actor",
        back_populates="platform_presences",
    )

    def __repr__(self) -> str:
        return (
            f"<ActorPlatformPresence actor_id={self.actor_id} "
            f"platform={self.platform!r} username={self.platform_username!r}>"
        )


class ActorListMember(Base):
    """Association table linking actors to actor lists (many-to-many).

    Uses a composite primary key (actor_list_id, actor_id) so that the
    same actor can appear in multiple lists but not twice in the same list.

    added_by is a free-text field indicating the source of the membership:
    'manual', 'snowball', 'network', or 'similarity'.
    """

    __tablename__ = "actor_list_members"

    actor_list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("actor_lists.id", ondelete="CASCADE"),
        primary_key=True,
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("actors.id", ondelete="CASCADE"),
        primary_key=True,
    )
    added_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
    added_by: Mapped[str] = mapped_column(
        sa.String(50),
        nullable=False,
        server_default=sa.text("'manual'"),
    )

    # Relationships
    actor_list: Mapped[ActorList] = relationship(
        "ActorList",
        back_populates="members",
    )
    actor: Mapped[Actor] = relationship(
        "Actor",
        back_populates="actor_list_memberships",
    )

    def __repr__(self) -> str:
        return (
            f"<ActorListMember list={self.actor_list_id} "
            f"actor={self.actor_id} by={self.added_by!r}>"
        )
