"""ORM model for URLs extracted from content records.

The ``extracted_urls`` table stores every hyperlink found in the body of a
``content_record``, after cleaning and deduplication.  It is the primary
input to the URL-extraction pipeline and the parent table for
``video_downloads``.

Design notes
------------
- No FK to ``content_records``: PostgreSQL cannot enforce referential integrity
  across range-partitioned tables.  ``content_record_id`` +
  ``content_record_published_at`` together allow a partition-pruned lookup when
  needed.
- ``query_design_id`` and ``project_id`` are denormalized (no FK) so that
  filter queries remain fast without joining up through the collection
  hierarchy.
- ``search_terms_matched`` is denormalized from the source content record to
  allow term-level network queries without a join.

Owned by the DB Engineer.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from issue_observatory.core.models.base import Base


class ExtractedUrl(Base):
    """A URL extracted from a content record's body text.

    Each row represents a single (content_record, cleaned_url) pair.  The
    three-column unique constraint mirrors the content_records partition key so
    that upserts remain efficient across monthly partitions.

    Attributes:
        id: UUID primary key.
        content_record_id: ID of the source content record (no FK; see above).
        content_record_published_at: ``published_at`` of the source record,
            included for partition-pruned lookups.
        url_raw: The URL exactly as it appeared in the content body.
        url_cleaned: The URL after standardization (scheme normalised,
            tracking params stripped, fragment dropped).
        url_domain: Registered domain extracted from ``url_cleaned``
            (e.g. ``"dr.dk"``, ``"youtu.be"``).
        url_type: Extraction source — ``"text_extracted"`` for links found in
            body text, ``"self_reference"`` for the record's own canonical URL.
        platform: Denormalized platform identifier from the source record.
        query_design_id: Denormalized reference to the query design (no FK).
        project_id: Denormalized reference to the project (no FK).
        search_terms_matched: Copy of the source record's matched search terms.
        extracted_at: Timestamp when this URL was extracted.
    """

    __tablename__ = "extracted_urls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    content_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    content_record_published_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    url_raw: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
    )
    url_cleaned: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
    )
    url_domain: Mapped[str | None] = mapped_column(
        sa.String(500),
        nullable=True,
    )
    url_type: Mapped[str | None] = mapped_column(
        sa.String(30),
        nullable=True,
    )
    platform: Mapped[str | None] = mapped_column(
        sa.String(50),
        nullable=True,
    )
    query_design_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    search_terms_matched: Mapped[list | None] = mapped_column(
        sa.ARRAY(sa.Text),
        nullable=True,
    )
    extracted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
    scraped: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.text("FALSE"),
    )

    # Relationships
    video_downloads: Mapped[list[VideoDownload]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "VideoDownload",
        back_populates="extracted_url",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # Partition-aware deduplication: one row per (content_record, cleaned URL).
        sa.UniqueConstraint(
            "content_record_id",
            "content_record_published_at",
            "url_cleaned",
            name="uq_extracted_urls_record_url",
        ),
        # B-tree indexes for point-lookups and range scans.
        sa.Index("idx_extracted_urls_url_cleaned", "url_cleaned"),
        sa.Index("idx_extracted_urls_url_domain", "url_domain"),
        sa.Index("idx_extracted_urls_content_record_id", "content_record_id"),
        sa.Index("idx_extracted_urls_query_design_id", "query_design_id"),
        sa.Index("idx_extracted_urls_project_id", "project_id"),
        sa.Index("idx_extracted_urls_platform", "platform"),
        # GIN index for array containment queries on search_terms_matched.
        sa.Index(
            "idx_extracted_urls_search_terms",
            "search_terms_matched",
            postgresql_using="gin",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ExtractedUrl id={self.id} domain={self.url_domain!r} "
            f"type={self.url_type!r} record={self.content_record_id}>"
        )
