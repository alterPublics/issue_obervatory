"""Universal content record ORM model.

This is the central table of the Issue Observatory schema.  Every piece of
collected content from every arena and platform normalizes into this table.

IMPORTANT DESIGN NOTES
----------------------
1. The table is range-partitioned by published_at (month boundaries).
   The SQLAlchemy ORM model declares the partition clause via
   __table_args__ using the postgresql_partition_by keyword argument.
   Alembic's autogenerate does NOT support partitioned tables fully — the
   migration (001_initial_schema.py) uses raw DDL to create the table.
   This model exists for ORM-level query support; the CREATE TABLE DDL
   in the migration is authoritative.

2. The composite primary key (id, published_at) is required by PostgreSQL
   for range-partitioned tables — the partition key must be part of the PK.

3. All indexes are created on the parent table and are inherited by
   partitions automatically (PostgreSQL 11+).

4. Do NOT add columns to this table without DB Engineer sign-off.
   Platform-specific fields belong in raw_metadata JSONB or in a
   separate extension table under core/models/arena_extensions/.

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
    from issue_observatory.core.models.actors import Actor
    from issue_observatory.core.models.collection import CollectionRun
    from issue_observatory.core.models.query_design import QueryDesign


class UniversalContentRecord(Base):
    """A single piece of content collected from any arena/platform.

    Columns are grouped by concern:

    Identity
        id, platform, arena, platform_id, content_type, url

    Text payload
        text_content, title, language

    Temporal
        published_at (partition key), collected_at

    Author (denormalized for query performance)
        author_platform_id, author_display_name, author_id (FK to actors),
        pseudonymized_author_id (SHA-256 hash for GDPR-safe analytics)

    Engagement metrics (nullable — not all platforms expose all metrics)
        views_count, likes_count, shares_count, comments_count,
        engagement_score (normalized cross-platform score)

    Collection context
        collection_run_id, query_design_id, search_terms_matched,
        collection_tier

    Platform-specific payload (Layer 2)
        raw_metadata (JSONB), media_urls (TEXT[])

    Deduplication
        content_hash (SHA-256 of normalized text)
    """

    __tablename__ = "content_records"

    # ------------------------------------------------------------------
    # Composite primary key: (id, published_at) — required by PostgreSQL
    # for range-partitioned tables.
    # ------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        primary_key=True,
        nullable=True,
    )

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    platform: Mapped[str] = mapped_column(
        sa.String(50),
        nullable=False,
    )
    arena: Mapped[str] = mapped_column(
        sa.String(50),
        nullable=False,
    )
    platform_id: Mapped[Optional[str]] = mapped_column(
        sa.String(500),
        nullable=True,
    )
    content_type: Mapped[str] = mapped_column(
        sa.String(50),
        nullable=False,
    )
    url: Mapped[Optional[str]] = mapped_column(
        sa.String(2000),
        nullable=True,
    )

    # ------------------------------------------------------------------
    # Text payload
    # ------------------------------------------------------------------
    text_content: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )
    title: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )
    language: Mapped[Optional[str]] = mapped_column(
        sa.String(10),
        nullable=True,
    )

    # ------------------------------------------------------------------
    # Temporal
    # ------------------------------------------------------------------
    collected_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )

    # ------------------------------------------------------------------
    # Author — denormalized for query speed
    # ------------------------------------------------------------------
    author_platform_id: Mapped[Optional[str]] = mapped_column(
        sa.String(500),
        nullable=True,
    )
    author_display_name: Mapped[Optional[str]] = mapped_column(
        sa.String(500),
        nullable=True,
    )
    author_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("actors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    pseudonymized_author_id: Mapped[Optional[str]] = mapped_column(
        sa.String(64),
        nullable=True,
    )

    # ------------------------------------------------------------------
    # Engagement metrics
    # ------------------------------------------------------------------
    views_count: Mapped[Optional[int]] = mapped_column(
        sa.BigInteger,
        nullable=True,
    )
    likes_count: Mapped[Optional[int]] = mapped_column(
        sa.BigInteger,
        nullable=True,
    )
    shares_count: Mapped[Optional[int]] = mapped_column(
        sa.BigInteger,
        nullable=True,
    )
    comments_count: Mapped[Optional[int]] = mapped_column(
        sa.BigInteger,
        nullable=True,
    )
    engagement_score: Mapped[Optional[float]] = mapped_column(
        sa.Float,
        nullable=True,
    )

    # ------------------------------------------------------------------
    # Collection context
    # ------------------------------------------------------------------
    collection_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("collection_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    query_design_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("query_designs.id", ondelete="SET NULL"),
        nullable=True,
    )
    search_terms_matched: Mapped[Optional[list]] = mapped_column(
        sa.ARRAY(sa.Text),
        nullable=True,
    )
    collection_tier: Mapped[str] = mapped_column(
        sa.String(10),
        nullable=False,
    )

    # ------------------------------------------------------------------
    # Platform-specific payload (Layer 2)
    # ------------------------------------------------------------------
    raw_metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        server_default=sa.text("'{}'"),
    )
    media_urls: Mapped[Optional[list]] = mapped_column(
        sa.ARRAY(sa.Text),
        nullable=True,
    )

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------
    content_hash: Mapped[Optional[str]] = mapped_column(
        sa.String(64),
        nullable=True,
    )
    simhash: Mapped[Optional[int]] = mapped_column(
        sa.BigInteger,
        nullable=True,
    )

    # ------------------------------------------------------------------
    # Table-level constraints and indexes.
    #
    # The postgresql_partition_by argument instructs SQLAlchemy to emit
    # PARTITION BY RANGE (published_at) in the CREATE TABLE statement.
    # Alembic autogenerate does not honour this kwarg — the migration DDL
    # is therefore written by hand in 001_initial_schema.py.
    #
    # Indexes on the parent table are inherited by all child partitions
    # automatically (PostgreSQL 11+).  The full-text index uses a
    # functional expression and must be created with op.execute() in the
    # migration because SQLAlchemy Index cannot express arbitrary
    # tsvector expressions portably.
    # ------------------------------------------------------------------
    __table_args__ = (
        # Deduplication constraint: one record per (platform, native ID, month)
        sa.UniqueConstraint(
            "platform",
            "platform_id",
            "published_at",
            name="uq_content_platform_id_published",
        ),
        # B-tree indexes
        sa.Index("idx_content_platform", "platform"),
        sa.Index("idx_content_arena", "arena"),
        sa.Index("idx_content_published", "published_at"),
        sa.Index("idx_content_query", "query_design_id"),
        sa.Index("idx_content_hash", "content_hash"),
        # GIN indexes for array and JSONB columns
        sa.Index(
            "idx_content_terms",
            "search_terms_matched",
            postgresql_using="gin",
        ),
        sa.Index(
            "idx_content_metadata",
            "raw_metadata",
            postgresql_using="gin",
        ),
        # Full-text search index is created via raw DDL in the migration
        # because SQLAlchemy cannot express the tsvector expression here.
        # See 001_initial_schema.py for:
        #   CREATE INDEX idx_content_fulltext ON content_records
        #   USING GIN(to_tsvector('danish',
        #       coalesce(text_content, '') || ' ' || coalesce(title, '')));
        #
        # Partition directive (ignored by autogenerate; honoured by
        # create_all() against a live database):
        {"postgresql_partition_by": "RANGE (published_at)"},
    )

    # ------------------------------------------------------------------
    # Relationships (load-time only; partitioned tables work normally for
    # SELECT queries that include published_at in the WHERE clause)
    # ------------------------------------------------------------------
    author: Mapped[Optional[Actor]] = relationship(
        "Actor",
        foreign_keys=[author_id],
        lazy="select",
    )
    collection_run: Mapped[Optional[CollectionRun]] = relationship(
        "CollectionRun",
        foreign_keys=[collection_run_id],
        lazy="select",
    )
    query_design: Mapped[Optional[QueryDesign]] = relationship(
        "QueryDesign",
        foreign_keys=[query_design_id],
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<UniversalContentRecord id={self.id} "
            f"platform={self.platform!r} arena={self.arena!r} "
            f"published_at={self.published_at}>"
        )
