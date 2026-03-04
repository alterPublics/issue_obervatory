"""Add actor skip tracking columns to collection_tasks.

Tracks actors that were skipped during collect_by_actors() due to per-actor
errors (HTTP failures, not found, forbidden, etc.). Enables post-collection
reporting of partial collection coverage.

Revision ID: 024
Revises: 023
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collection_tasks",
        sa.Column(
            "actors_skipped",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "collection_tasks",
        sa.Column(
            "skipped_actor_detail",
            JSONB,
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("collection_tasks", "skipped_actor_detail")
    op.drop_column("collection_tasks", "actors_skipped")
