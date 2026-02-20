"""Content annotation model for qualitative coding of content records.

Owned by the DB Engineer. Do not modify without DB Engineer approval.

Stores researcher-coded qualitative judgements on individual content records:
stance, frame, relevance flag, free-text notes, and flexible JSONB tags.

One annotation per user per content record is enforced via a unique constraint
on (created_by, content_record_id, content_published_at).  Multiple researchers
can annotate the same record independently.

The content_record_id + content_published_at pair is a logical reference to
the partitioned content_records table (which has a composite PK of id +
published_at).  No database-level FK constraint is defined on this pair because
PostgreSQL does not support FK references that only partially match a composite
PK on a partitioned table.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from issue_observatory.core.models.base import Base, TimestampMixin


class ContentAnnotation(Base, TimestampMixin):
    """Researcher annotation on a single content record.

    Stores qualitative coding decisions made by a researcher during analysis.
    Multiple annotations per record are allowed — one per user per record —
    enforced by the unique constraint on (created_by, content_record_id,
    content_published_at).  Multiple researchers can annotate the same record
    independently.

    Attributes:
        id: UUID primary key (application-generated via uuid.uuid4).
        created_by: UUID of the researcher who created this annotation.
            Soft FK to users.id (SET NULL on delete so annotations survive
            user deletion for audit purposes).
        content_record_id: Logical reference to content_records.id.
            No DB-level FK because content_records is partitioned and FK
            references must match the full composite PK.
        content_published_at: Required companion to content_record_id for
            the composite logical reference into the partitioned table.
        stance: Researcher-coded stance label.  One of:
            "positive", "negative", "neutral", "contested", "irrelevant".
            NULL means not yet coded.
        frame: Free-text frame label (e.g. "economic", "environmental").
        is_relevant: Explicit relevance flag.  True = relevant to the
            research question.  NULL means not yet coded.
        notes: Free-text annotation notes.
        collection_run_id: Optional FK to collection_runs.id.  Allows
            filtering annotations by the collection context in which the
            record was gathered.
        query_design_id: Optional FK to query_designs.id.  Allows filtering
            annotations by study / query design.
        tags: JSONB array of researcher-defined string tags for flexible
            categorical coding.
    """

    __tablename__ = "content_annotations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Ownership — who created this annotation.
    # ON DELETE SET NULL: annotations survive user deletion for audit purposes.
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Logical reference into the partitioned content_records table.
    # No DB-level FK — see module docstring.
    content_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    content_published_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        index=True,
    )

    # ---------------------------------------------------------------------------
    # Qualitative coding fields
    # ---------------------------------------------------------------------------

    # Valid values: "positive", "negative", "neutral", "contested", "irrelevant".
    # Enforced at the application layer, not via a DB CHECK constraint so that
    # the vocabulary can evolve without a schema migration.
    stance: Mapped[Optional[str]] = mapped_column(
        sa.String(20),
        nullable=True,
    )

    frame: Mapped[Optional[str]] = mapped_column(
        sa.String(200),
        nullable=True,
    )

    is_relevant: Mapped[Optional[bool]] = mapped_column(
        sa.Boolean,
        nullable=True,
    )

    notes: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )

    # ---------------------------------------------------------------------------
    # Context links — optional, used for filtering annotations by study
    # ---------------------------------------------------------------------------

    collection_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("collection_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    query_design_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("query_designs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ---------------------------------------------------------------------------
    # Flexible researcher-defined tags
    # ---------------------------------------------------------------------------

    tags: Mapped[Optional[list]] = mapped_column(
        JSONB,
        nullable=True,
    )

    # ---------------------------------------------------------------------------
    # Table-level constraints and indexes
    # ---------------------------------------------------------------------------

    __table_args__ = (
        # One annotation per user per content record (NULL created_by treated as
        # a distinct value per row by PostgreSQL — nulls are not equal in UNIQUE).
        sa.UniqueConstraint(
            "created_by",
            "content_record_id",
            "content_published_at",
            name="uq_annotation_user_record",
        ),
        # GIN index for fast JSONB tag queries (e.g. tags @> '["economic"]').
        sa.Index("idx_annotation_tags", "tags", postgresql_using="gin"),
    )

    def __repr__(self) -> str:
        return (
            f"<ContentAnnotation id={self.id} "
            f"content_record_id={self.content_record_id} "
            f"created_by={self.created_by} "
            f"stance={self.stance!r}>"
        )


class CodebookEntry(Base, TimestampMixin):
    """Structured qualitative coding scheme entry for annotations.

    Codebook entries define a controlled vocabulary of codes with labels,
    descriptions, and optional categories that researchers can use when
    annotating content records. This allows standardized, structured
    qualitative coding instead of free-text frame entries.

    Codebook entries can be scoped to a specific query design or marked as
    global (query_design_id=NULL) to be available across all studies.
    Non-admin users can only create/modify design-scoped entries they own.
    Admins can manage global entries.

    Attributes:
        id: UUID primary key (application-generated via uuid.uuid4).
        code: Short identifier for this entry (e.g., "punitive_frame").
            Must be unique within the scope of query_design_id.
            Used as the value stored in ContentAnnotation.frame when selected.
        label: Human-readable display name (e.g., "Punitive Framing").
            Shown in dropdown UI elements.
        description: Optional longer explanation of when to use this code.
            Useful for training coders and documenting the coding scheme.
        category: Optional grouping label (e.g., "stance", "frame").
            Used to organize codes in the UI (e.g., as optgroups in dropdowns).
        query_design_id: Optional FK to query_designs.id.
            NULL means this is a global codebook entry visible to all
            researchers. Non-NULL means it's scoped to a specific query design
            and only visible to researchers with access to that design.
        created_by: UUID of the user who created this entry.
            Soft FK to users.id (SET NULL on delete).

    Unique constraint:
        (query_design_id, code) — codes must be unique within a query design scope.
        NULL query_design_id is treated as a distinct value per row.
    """

    __tablename__ = "codebook_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    code: Mapped[str] = mapped_column(
        sa.String(100),
        nullable=False,
        index=True,
    )

    label: Mapped[str] = mapped_column(
        sa.String(200),
        nullable=False,
    )

    description: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )

    category: Mapped[Optional[str]] = mapped_column(
        sa.String(100),
        nullable=True,
        index=True,
    )

    # Scope: design-specific or global
    query_design_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("query_designs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Ownership — who created this entry
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ---------------------------------------------------------------------------
    # Table-level constraints and indexes
    # ---------------------------------------------------------------------------

    __table_args__ = (
        # Code must be unique within a query design scope
        sa.UniqueConstraint(
            "query_design_id",
            "code",
            name="uq_codebook_design_code",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CodebookEntry id={self.id} "
            f"code={self.code!r} "
            f"query_design_id={self.query_design_id}>"
        )
