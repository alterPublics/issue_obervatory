"""Add duplicates_skipped column to collection_tasks.

Revision ID: 017
Revises: 016
Create Date: 2026-02-23

Adds a `duplicates_skipped` integer column to the `collection_tasks` table
to track how many records were skipped during collection because they were
already present in the database (detected via ON CONFLICT on content_hash).

This improves transparency for researchers: when a collection run returns
0 new records, they can now see whether this means "no content matched"
or "X matching records were already collected previously."

Context: The deduplication count flows from `persist_collected_records()`
(which returns `(inserted, skipped)`) to the per-arena task status updates,
and is surfaced via both the SSE live monitoring stream and the collection
detail page.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add duplicates_skipped column to collection_tasks."""
    op.add_column(
        "collection_tasks",
        sa.Column(
            "duplicates_skipped",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    """Remove duplicates_skipped column from collection_tasks."""
    op.drop_column("collection_tasks", "duplicates_skipped")
