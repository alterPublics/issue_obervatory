"""Query design ORM models.

Covers:
- QueryDesign: the owner-scoped research instrument comprising search terms
  and actor lists, configured per-arena.
- SearchTerm: an individual keyword, phrase, hashtag, or URL pattern within
  a query design.
- ActorList: a named, curated set of actors attached to a query design.

ActorListMember (the join table) lives in actors.py to avoid circular imports
and to keep all actor-related tables together.

Owned by the DB Engineer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from issue_observatory.core.models.base import Base

if TYPE_CHECKING:
    from issue_observatory.core.models.actors import ActorListMember
    from issue_observatory.core.models.collection import CollectionRun
    from issue_observatory.core.models.project import Project
    from issue_observatory.core.models.users import User
    from issue_observatory.core.models.zeeschuimer_import import ZeeschuimerImport


class QueryDesign(Base):
    """A named, owner-scoped research instrument.

    A query design bundles a set of search terms and actor lists and controls
    the per-arena tier configuration for collection runs.

    visibility controls access:
    - 'private':  visible only to the owner.
    - 'team':     visible to all researchers in the system (read-only for others).
    - 'public':   visible to anyone including unauthenticated users (future).

    language and locale_country carry the default locale for arena collectors
    that accept language/geo filters (YouTube, Google, GDELT, Bluesky …).
    """

    __tablename__ = "query_designs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        sa.String(200),
        nullable=False,
    )
    description: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )
    visibility: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        server_default=sa.text("'private'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
        onupdate=sa.text("NOW()"),
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.text("true"),
    )
    default_tier: Mapped[str] = mapped_column(
        sa.String(10),
        nullable=False,
        server_default=sa.text("'free'"),
    )
    language: Mapped[str] = mapped_column(
        sa.String(10),
        nullable=False,
        server_default=sa.text("'da'"),
    )
    locale_country: Mapped[str] = mapped_column(
        sa.String(5),
        nullable=False,
        server_default=sa.text("'dk'"),
    )
    arenas_config: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )
    # Self-referential FK to track cloning lineage (IP2-051).
    # ON DELETE SET NULL so that deleting a parent does not cascade to clones.
    parent_design_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("query_designs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Optional FK to Project for organizational grouping (R-06).
    # ON DELETE SET NULL so that deleting a project detaches designs but doesn't delete them.
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationships
    owner: Mapped[User] = relationship(
        "User",
        foreign_keys=[owner_id],
        back_populates="query_designs",
    )
    project: Mapped[Optional[Project]] = relationship(
        "Project",
        foreign_keys=[project_id],
        back_populates="query_designs",
    )
    search_terms: Mapped[list[SearchTerm]] = relationship(
        "SearchTerm",
        back_populates="query_design",
        cascade="all, delete-orphan",
    )
    actor_lists: Mapped[list[ActorList]] = relationship(
        "ActorList",
        back_populates="query_design",
        cascade="all, delete-orphan",
    )
    collection_runs: Mapped[list[CollectionRun]] = relationship(
        "CollectionRun",
        back_populates="query_design",
    )
    zeeschuimer_imports: Mapped[list[ZeeschuimerImport]] = relationship(
        "ZeeschuimerImport",
        back_populates="query_design",
    )

    def __repr__(self) -> str:
        return (
            f"<QueryDesign id={self.id} name={self.name!r} "
            f"owner_id={self.owner_id}>"
        )


class SearchTerm(Base):
    """An individual search term within a query design.

    term_type controls how arena collectors interpret the value:
    - 'keyword':     free-text keyword (default)
    - 'phrase':      exact phrase match (quoted search)
    - 'hashtag':     platform hashtag (# prepended if not present)
    - 'url_pattern': URL prefix or domain to match

    Soft-deletion via is_active=False preserves historical coverage data
    for completed collection runs that referenced this term.
    """

    __tablename__ = "search_terms"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    query_design_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("query_designs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    term: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
    )
    term_type: Mapped[str] = mapped_column(
        sa.String(50),
        nullable=False,
        server_default=sa.text("'keyword'"),
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.text("true"),
    )
    added_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    group_label: Mapped[str | None] = mapped_column(
        sa.String(200),
        nullable=True,
    )
    # Optional list of arena platform_names. NULL = all arenas.
    target_arenas: Mapped[list[str] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Optional list of arena platform_names. NULL = all arenas.",
    )
    # Optional dict mapping ISO 639-1 language codes to translated terms.
    # Example: {"kl": "CO2-akilerisitsinnaanera", "en": "CO2 tax"}
    # NULL = no translations available (use the primary term value).
    translations: Mapped[dict[str, str] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment=(
            "Optional dict mapping ISO 639-1 language codes to translated terms. "
            "NULL = no translations available."
        ),
    )

    # Arena override mechanism: when both are set, this term replaces the
    # parent default term for the specified arena.  When both are NULL, this
    # is a default term that applies to all arenas (unless overridden).
    parent_term_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("search_terms.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    override_arena: Mapped[str | None] = mapped_column(
        sa.String(50),
        nullable=True,
        comment=(
            "Arena platform_name this override applies to. "
            "NULL = default term (applies to all arenas unless overridden)."
        ),
    )

    # Relationships
    query_design: Mapped[QueryDesign] = relationship(
        "QueryDesign",
        back_populates="search_terms",
    )
    parent_term: Mapped[SearchTerm | None] = relationship(
        "SearchTerm",
        remote_side=[id],
        foreign_keys=[parent_term_id],
        back_populates="arena_overrides",
    )
    arena_overrides: Mapped[list[SearchTerm]] = relationship(
        "SearchTerm",
        foreign_keys="SearchTerm.parent_term_id",
        back_populates="parent_term",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        sa.Index(
            "idx_search_term_parent_override",
            "parent_term_id",
            "override_arena",
        ),
        sa.CheckConstraint(
            "(parent_term_id IS NULL AND override_arena IS NULL) "
            "OR (parent_term_id IS NOT NULL AND override_arena IS NOT NULL)",
            name="ck_search_term_override_pair",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SearchTerm id={self.id} term={self.term!r} "
            f"type={self.term_type!r}>"
        )


class ActorList(Base):
    """A named, curated set of actors attached to a query design.

    Actor lists allow targeted collection from known accounts rather than
    (or in addition to) keyword-based search.

    sampling_method documents how the list was constructed:
    'manual', 'snowball', 'network', or 'similarity'.
    """

    __tablename__ = "actor_lists"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    query_design_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("query_designs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        sa.String(200),
        nullable=False,
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
    sampling_method: Mapped[Optional[str]] = mapped_column(
        sa.String(50),
        nullable=True,
    )

    # Relationships
    query_design: Mapped[QueryDesign] = relationship(
        "QueryDesign",
        back_populates="actor_lists",
    )
    creator: Mapped[Optional[User]] = relationship(
        "User",
        foreign_keys=[created_by],
    )
    members: Mapped[list[ActorListMember]] = relationship(
        "ActorListMember",
        back_populates="actor_list",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<ActorList id={self.id} name={self.name!r} "
            f"query_design_id={self.query_design_id}>"
        )
