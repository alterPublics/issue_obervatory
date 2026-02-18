"""Add suspended_at column to collection_runs.

Supports the live-tracking suspend/resume feature (B-03).  A live
``CollectionRun`` can be paused by the owner, which sets ``status`` to
``'suspended'`` and records the timestamp in this new column.  Resuming
the run clears the column and sets ``status`` back to ``'active'``.

Revision ID: 003
Revises: 002
Create Date: 2026-02-17
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add suspended_at TIMESTAMPTZ column to collection_runs (nullable)."""
    op.add_column(
        "collection_runs",
        sa.Column(
            "suspended_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove suspended_at column from collection_runs."""
    op.drop_column("collection_runs", "suspended_at")
