"""SQLAlchemy ORM model for scraping jobs.

The ``ScrapingJob`` model tracks web scraper enrichment runs that fill in
``text_content`` on existing thin ``content_records`` (produced by web archive
arenas) or insert new records from a user-supplied URL list.

Owned by the DB Engineer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from issue_observatory.core.models.base import Base


class ScrapingJob(Base):
    """A scraper enrichment job that fetches page text for a list of URLs.

    Two source modes are supported:

    - ``"collection_run"`` — enrich all thin (``text_content IS NULL``) records
      from a prior collection run (e.g. a Wayback Machine run).
    - ``"manual_urls"`` — insert new records for user-specified URLs.

    Attributes:
        id: UUID primary key.
        created_by: UUID of the user who created this job.
        query_design_id: Optional reference to a query design for bookkeeping.
        source_type: ``"collection_run"`` or ``"manual_urls"``.
        source_collection_run_id: UUID of the collection run to enrich
            (only for ``source_type="collection_run"``).
        source_urls: JSON list of URLs to scrape
            (only for ``source_type="manual_urls"``).
        delay_min: Minimum inter-request delay in seconds.
        delay_max: Maximum inter-request delay in seconds.
        timeout_seconds: HTTP request timeout.
        respect_robots_txt: Whether to honour robots.txt disallow rules.
        use_playwright_fallback: Whether to retry JS-only pages with Playwright.
        max_retries: Per-URL retry count on transient errors.
        status: Lifecycle state — ``"pending"``, ``"running"``, ``"completed"``,
            ``"failed"``, or ``"cancelled"``.
        celery_task_id: ID of the Celery task running this job.
        error_message: Human-readable error description if the job failed.
        total_urls: Total URLs in the work list (set once the task starts).
        urls_enriched: URLs successfully scraped and stored.
        urls_failed: URLs that raised an unrecoverable error.
        urls_skipped: URLs skipped (robots.txt, binary content, etc.).
        created_at: Timestamp when the job was created.
        started_at: Timestamp when the Celery task started executing.
        completed_at: Timestamp when the job reached a terminal state.
    """

    __tablename__ = "scraping_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    query_design_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("query_designs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Source config
    source_type: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
    )
    source_collection_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("collection_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_urls: Mapped[Optional[list]] = mapped_column(
        JSONB,
        nullable=True,
    )

    # Scraper behaviour
    delay_min: Mapped[float] = mapped_column(
        sa.Float,
        nullable=False,
        server_default=sa.text("2.0"),
    )
    delay_max: Mapped[float] = mapped_column(
        sa.Float,
        nullable=False,
        server_default=sa.text("5.0"),
    )
    timeout_seconds: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("30"),
    )
    respect_robots_txt: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.text("true"),
    )
    use_playwright_fallback: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.text("true"),
    )
    max_retries: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("2"),
    )

    # Lifecycle
    status: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        server_default=sa.text("'pending'"),
    )
    celery_task_id: Mapped[Optional[str]] = mapped_column(
        sa.String(255),
        nullable=True,
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )

    # Progress counters
    total_urls: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    )
    urls_enriched: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    )
    urls_failed: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    )
    urls_skipped: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    )

    # Timing
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        sa.Index("idx_scraping_jobs_created_by", "created_by"),
        sa.Index("idx_scraping_jobs_status", "status"),
    )
