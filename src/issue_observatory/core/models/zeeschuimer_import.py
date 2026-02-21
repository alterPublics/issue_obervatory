"""Zeeschuimer import job ORM model.

Tracks manual data imports from the Zeeschuimer browser extension (which
captures social media content as researchers browse). Each import job
represents a single NDJSON file upload from Zeeschuimer.

Zeeschuimer compatibility:
- The 'key' field is returned to Zeeschuimer in the upload response and used
  for polling status via /api/check-query/?key={key}
- Status progression matches 4CAT expectations: queued → processing → complete
- The platform field stores the Zeeschuimer module_id (e.g., "linkedin.com",
  "twitter.com") as received via the X-Zeeschuimer-Platform header

Owned by the DB Engineer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from issue_observatory.core.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from issue_observatory.core.models.query_design import QueryDesign
    from issue_observatory.core.models.users import User


class ZeeschuimerImport(Base, TimestampMixin):
    """A manual data import job from the Zeeschuimer browser extension.

    Status progression (happy path):
        queued → processing → complete

    Failure path:
        queued / processing → failed

    The 'key' field is a human-readable short identifier (e.g., "import-abc123")
    that Zeeschuimer uses to poll for status updates. It must be unique and
    URL-safe.

    Platform field stores the Zeeschuimer module_id as received via the
    X-Zeeschuimer-Platform header. This is mapped to IO platform names during
    processing (e.g., "linkedin.com" → "linkedin", "twitter.com" → "x_twitter").

    Progress tracking:
    - rows_total: the total number of NDJSON lines in the upload
    - rows_processed: the number of lines successfully processed so far
    - progress_percent: calculated as (rows_processed / rows_total * 100)

    Optional query_design_id allows researchers to associate imported records
    with a specific query design for organizational purposes. When NULL, the
    import is standalone (orphan import).

    All imported content_records have:
    - collection_tier = "manual"
    - raw_metadata.import_source = "zeeschuimer"
    - raw_metadata.zeeschuimer_import_id = {this import's id}
    - raw_metadata.zeeschuimer = {envelope metadata from Zeeschuimer}
    """

    __tablename__ = "zeeschuimer_imports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    key: Mapped[str] = mapped_column(
        sa.String(100),
        nullable=False,
        unique=True,
        index=True,
        comment="Short identifier for polling (e.g., 'import-abc123')",
    )
    initiated_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    query_design_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("query_designs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Optional association with a query design for organization",
    )
    platform: Mapped[str] = mapped_column(
        sa.String(50),
        nullable=False,
        index=True,
        comment="Zeeschuimer module_id (e.g., 'linkedin.com', 'twitter.com')",
    )
    status: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        server_default=sa.text("'queued'"),
        index=True,
        comment="queued | processing | complete | failed",
    )
    rows_total: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
        comment="Total number of NDJSON lines in the upload",
    )
    rows_processed: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
        comment="Number of lines successfully processed",
    )
    rows_imported: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
        comment="Number of content_records created (after deduplication)",
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )
    file_path: Mapped[Optional[str]] = mapped_column(
        sa.String(500),
        nullable=True,
        comment="Path to the uploaded NDJSON file (deleted after processing)",
    )
    import_metadata: Mapped[Optional[dict]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        server_default=sa.text("'{}'"),
        comment="Additional metadata (e.g., file size, user agent)",
    )

    # Relationships
    initiator: Mapped[User] = relationship(
        "User",
        foreign_keys=[initiated_by],
        back_populates="zeeschuimer_imports",
    )
    query_design: Mapped[Optional[QueryDesign]] = relationship(
        "QueryDesign",
        foreign_keys=[query_design_id],
        back_populates="zeeschuimer_imports",
    )

    def __repr__(self) -> str:
        return (
            f"<ZeeschuimerImport id={self.id} key={self.key!r} "
            f"platform={self.platform!r} status={self.status!r}>"
        )

    @property
    def progress_percent(self) -> float:
        """Calculate progress as a percentage (0-100)."""
        if self.rows_total == 0:
            return 0.0
        return round((self.rows_processed / self.rows_total) * 100, 1)
