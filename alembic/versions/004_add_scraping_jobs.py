"""Add scraping_jobs table and supporting indexes.

Creates the ``scraping_jobs`` table used by the web scraper enrichment service
to track progress and results of URL scraping runs.

Also adds ``idx_content_collection_run`` on ``content_records.collection_run_id``
which is required for efficient enrichment queries in ``collection_run`` mode.

Revision ID: 004
Revises: 003
Create Date: 2026-02-17
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create scraping_jobs table and add supporting indexes."""
    op.create_table(
        "scraping_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "query_design_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("query_designs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Source config
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column(
            "source_collection_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("collection_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_urls", postgresql.JSONB(), nullable=True),
        # Scraper behaviour
        sa.Column(
            "delay_min",
            sa.Float(),
            nullable=False,
            server_default=sa.text("2.0"),
        ),
        sa.Column(
            "delay_max",
            sa.Float(),
            nullable=False,
            server_default=sa.text("5.0"),
        ),
        sa.Column(
            "timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("30"),
        ),
        sa.Column(
            "respect_robots_txt",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "use_playwright_fallback",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "max_retries",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("2"),
        ),
        # Lifecycle
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        # Progress counters
        sa.Column(
            "total_urls",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "urls_enriched",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "urls_failed",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "urls_skipped",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        # Timing
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "started_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )

    # Indexes on scraping_jobs
    op.create_index(
        "idx_scraping_jobs_created_by",
        "scraping_jobs",
        ["created_by"],
    )
    op.create_index(
        "idx_scraping_jobs_status",
        "scraping_jobs",
        ["status"],
    )

    # Index on content_records.collection_run_id for efficient enrichment queries.
    # content_records is range-partitioned, so the index is created on the
    # parent table and inherited by all child partitions automatically.
    op.create_index(
        "idx_content_collection_run",
        "content_records",
        ["collection_run_id"],
    )


def downgrade() -> None:
    """Drop scraping_jobs table and supporting indexes."""
    op.drop_index("idx_content_collection_run", table_name="content_records")
    op.drop_index("idx_scraping_jobs_status", table_name="scraping_jobs")
    op.drop_index("idx_scraping_jobs_created_by", table_name="scraping_jobs")
    op.drop_table("scraping_jobs")
