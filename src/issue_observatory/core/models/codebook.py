"""Codebook model for managing qualitative coding schemes.

Owned by the DB Engineer. Do not modify without DB Engineer approval.

Stores reusable qualitative coding schemes (codebooks) that researchers can
apply when annotating content records.  Codebooks define structured vocabularies
of codes, labels, and descriptions that standardize annotation practices across
a query design or globally.

Key design choices:
- query_design_id is nullable: allows both query-design-specific codebooks and
  global/shared codebooks (NULL = global).
- Unique constraint on (query_design_id, code) prevents duplicate codes within
  a codebook scope.
- The ``category`` field allows grouping related codes (e.g., "framing",
  "stance", "topic") for UI organization.
- No FK to content_annotations: codebooks are reference data used by researchers
  during annotation, not directly linked to annotation records.  The annotation
  layer stores the applied code as a string in the ``frame`` field.
"""

from __future__ import annotations

import uuid
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from issue_observatory.core.models.base import Base, TimestampMixin


class CodebookEntry(Base, TimestampMixin):
    """A single code entry in a qualitative coding scheme (codebook).

    Codebooks provide structured vocabularies for annotating content records
    with standardized codes, labels, and descriptions.  Each entry represents
    one code option that researchers can apply during qualitative analysis.

    Attributes:
        id: UUID primary key (application-generated via uuid.uuid4).
        query_design_id: Optional FK to query_designs.id.  NULL indicates a
            global/shared codebook entry available across all query designs.
            Non-NULL indicates a query-design-specific codebook entry.
        code: Machine-readable code string (e.g., "punitive_frame",
            "economic_impact").  Used as the stable identifier in annotation data.
        label: Human-readable label displayed in the UI (e.g., "Punitive Framing",
            "Economic Impact").
        description: Optional detailed explanation of when to apply this code
            and what it means.
        category: Optional grouping label for organizing codes in the UI (e.g.,
            "framing", "stance", "topic").  Allows hierarchical presentation
            of large codebooks.

    Table-level constraints:
        - Unique constraint on (query_design_id, code): prevents duplicate codes
          within the same codebook scope.  NULL query_design_id is treated as
          a distinct value by PostgreSQL, so global codes are unique separately
          from query-design-specific codes.
    """

    __tablename__ = "codebook_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Scope: NULL = global/shared codebook, non-NULL = query-design-specific.
    # ON DELETE CASCADE: deleting a query design removes its codebook entries.
    query_design_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("query_designs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Machine-readable code (stable identifier).
    code: Mapped[str] = mapped_column(
        sa.String(100),
        nullable=False,
    )

    # Human-readable label for the UI.
    label: Mapped[str] = mapped_column(
        sa.String(200),
        nullable=False,
    )

    # Optional detailed explanation.
    description: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )

    # Optional grouping label (e.g., "framing", "stance", "topic").
    category: Mapped[Optional[str]] = mapped_column(
        sa.String(100),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        # One code per codebook scope (NULL query_design_id = global scope).
        sa.UniqueConstraint(
            "query_design_id",
            "code",
            name="uq_codebook_entry_scope_code",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CodebookEntry id={self.id} "
            f"query_design_id={self.query_design_id} "
            f"code={self.code!r} "
            f"label={self.label!r}>"
        )
