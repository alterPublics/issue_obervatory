"""Add extracted_urls and video_downloads tables, and url_filter_criteria to scraping_jobs.

Introduces the URL-extraction pipeline data layer:

- ``extracted_urls``: stores every hyperlink extracted from a content record
  body, after cleaning and standardization.  No FK to ``content_records``
  because PostgreSQL cannot enforce referential integrity across
  range-partitioned tables; ``content_record_id`` +
  ``content_record_published_at`` allow partition-pruned lookups.
  ``query_design_id`` and ``project_id`` are denormalized (no FK) for fast
  filter queries.

- ``video_downloads``: tracks yt-dlp download jobs for video URLs found in
  ``extracted_urls``.  FK to ``extracted_urls.id`` (CASCADE on delete) and an
  optional FK to ``scraping_jobs.id`` (SET NULL on delete).

- ``scraping_jobs.url_filter_criteria`` (JSONB): optional criteria applied
  when selecting which extracted URLs to enqueue for scraping or downloading.

Revision ID: 034
Revises: 033
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # extracted_urls
    # ------------------------------------------------------------------
    op.create_table(
        "extracted_urls",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # No FK to content_records: PG cannot enforce FKs across partitions.
        sa.Column("content_record_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "content_record_published_at",
            TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column("url_raw", sa.Text, nullable=False),
        sa.Column("url_cleaned", sa.Text, nullable=False),
        sa.Column("url_domain", sa.String(500), nullable=True),
        sa.Column("url_type", sa.String(30), nullable=True),
        sa.Column("platform", sa.String(50), nullable=True),
        # Denormalized — no FK, for performance.
        sa.Column("query_design_id", UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", UUID(as_uuid=True), nullable=True),
        sa.Column("search_terms_matched", sa.ARRAY(sa.Text), nullable=True),
        sa.Column(
            "extracted_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "content_record_id",
            "content_record_published_at",
            "url_cleaned",
            name="uq_extracted_urls_record_url",
        ),
    )

    # B-tree indexes for point-lookups and filter queries.
    op.create_index(
        "idx_extracted_urls_url_cleaned",
        "extracted_urls",
        ["url_cleaned"],
    )
    op.create_index(
        "idx_extracted_urls_url_domain",
        "extracted_urls",
        ["url_domain"],
    )
    op.create_index(
        "idx_extracted_urls_content_record_id",
        "extracted_urls",
        ["content_record_id"],
    )
    op.create_index(
        "idx_extracted_urls_query_design_id",
        "extracted_urls",
        ["query_design_id"],
    )
    op.create_index(
        "idx_extracted_urls_project_id",
        "extracted_urls",
        ["project_id"],
    )
    op.create_index(
        "idx_extracted_urls_platform",
        "extracted_urls",
        ["platform"],
    )
    # GIN index for array containment queries (e.g. search_terms_matched @> '{term}').
    op.create_index(
        "idx_extracted_urls_search_terms",
        "extracted_urls",
        ["search_terms_matched"],
        postgresql_using="gin",
    )

    # ------------------------------------------------------------------
    # video_downloads
    # ------------------------------------------------------------------
    op.create_table(
        "video_downloads",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "extracted_url_id",
            UUID(as_uuid=True),
            sa.ForeignKey("extracted_urls.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("video_id", sa.String(200), nullable=True),
        sa.Column("video_platform", sa.String(30), nullable=True),
        sa.Column("file_path", sa.Text, nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger, nullable=True),
        sa.Column("duration_seconds", sa.Float, nullable=True),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("uploader", sa.Text, nullable=True),
        sa.Column("upload_date", sa.Date, nullable=True),
        sa.Column("metadata_json", JSONB, nullable=True),
        sa.Column(
            "download_status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "scraping_job_id",
            UUID(as_uuid=True),
            sa.ForeignKey("scraping_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "completed_at",
            TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )

    op.create_index(
        "idx_video_downloads_extracted_url_id",
        "video_downloads",
        ["extracted_url_id"],
    )
    op.create_index(
        "idx_video_downloads_download_status",
        "video_downloads",
        ["download_status"],
    )
    # Composite index for platform-native deduplication checks.
    op.create_index(
        "idx_video_downloads_platform_video_id",
        "video_downloads",
        ["video_platform", "video_id"],
    )

    # ------------------------------------------------------------------
    # scraping_jobs.url_filter_criteria
    # ------------------------------------------------------------------
    op.add_column(
        "scraping_jobs",
        sa.Column(
            "url_filter_criteria",
            JSONB,
            nullable=True,
        ),
    )


def downgrade() -> None:
    # Remove url_filter_criteria from scraping_jobs first.
    op.drop_column("scraping_jobs", "url_filter_criteria")

    # Drop video_downloads (has FK to extracted_urls — must go first).
    op.drop_index("idx_video_downloads_platform_video_id", table_name="video_downloads")
    op.drop_index("idx_video_downloads_download_status", table_name="video_downloads")
    op.drop_index("idx_video_downloads_extracted_url_id", table_name="video_downloads")
    op.drop_table("video_downloads")

    # Drop extracted_urls.
    op.drop_index("idx_extracted_urls_search_terms", table_name="extracted_urls")
    op.drop_index("idx_extracted_urls_platform", table_name="extracted_urls")
    op.drop_index("idx_extracted_urls_project_id", table_name="extracted_urls")
    op.drop_index("idx_extracted_urls_query_design_id", table_name="extracted_urls")
    op.drop_index("idx_extracted_urls_content_record_id", table_name="extracted_urls")
    op.drop_index("idx_extracted_urls_url_domain", table_name="extracted_urls")
    op.drop_index("idx_extracted_urls_url_cleaned", table_name="extracted_urls")
    op.drop_table("extracted_urls")
