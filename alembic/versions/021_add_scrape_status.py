"""Add scrape_status to content_records.

Tracks the scraping state of URL-bearing content records:
- NULL = scraping not applicable (social media posts, autocomplete, etc.)
- 'pending' = URL exists but full text not yet scraped
- 'scraped' = full text retrieved and stored in text_content
- 'failed' = scrape attempted but failed

Key design choices:
- Partial index WHERE scrape_status IS NOT NULL avoids bloating the index
  with the majority of records where scraping is not applicable.
- No backfill needed: NULL is the correct default for all existing records.
- content_records is partitioned — column addition is DDL-only on the parent.

Revision ID: 021
Revises: 020
Create Date: 2026-02-26
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add scrape_status column to content_records."""
    op.add_column(
        "content_records",
        sa.Column(
            "scrape_status",
            sa.String(20),
            nullable=True,
        ),
    )

    # Partial index: only index rows where scraping is relevant
    op.execute(
        "CREATE INDEX idx_content_scrape_status "
        "ON content_records (scrape_status) "
        "WHERE scrape_status IS NOT NULL"
    )


def downgrade() -> None:
    """Remove scrape_status from content_records."""
    op.execute("DROP INDEX IF EXISTS idx_content_scrape_status")
    op.drop_column("content_records", "scrape_status")
