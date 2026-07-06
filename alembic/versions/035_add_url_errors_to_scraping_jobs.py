"""Add url_errors JSONB column to scraping_jobs.

Stores per-URL skip/fail reasons as ``{url: reason}`` so the UI can
show why individual URLs were not enriched.

Revision ID: 035
Revises: 034
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scraping_jobs",
        sa.Column("url_errors", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scraping_jobs", "url_errors")
