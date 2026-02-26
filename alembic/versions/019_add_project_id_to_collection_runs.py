"""Add project_id to collection_runs.

Adds a ``project_id`` column to ``collection_runs`` so that collection runs
launched from a project can be grouped and aggregated at the project level.

Key design choices:
- project_id is nullable: existing runs (and per-QD launches without a project)
  have no project association.
- ON DELETE SET NULL: deleting a project detaches runs but does not delete them.
- B-tree index for efficient project-scoped queries (collections list, detail).
- Data backfill: populates project_id from the associated query design's project_id
  for existing runs, so historical data is immediately grouped.

Revision ID: 019
Revises: 018
Create Date: 2026-02-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add project_id column to collection_runs with backfill."""
    # Add nullable project_id FK column
    op.add_column(
        "collection_runs",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # B-tree index for project-scoped queries
    op.create_index(
        "idx_collection_run_project",
        "collection_runs",
        ["project_id"],
    )

    # Backfill: set project_id from the associated query design's project_id
    op.execute(
        """
        UPDATE collection_runs
        SET project_id = qd.project_id
        FROM query_designs qd
        WHERE collection_runs.query_design_id = qd.id
          AND qd.project_id IS NOT NULL
        """
    )


def downgrade() -> None:
    """Remove project_id from collection_runs."""
    op.drop_index("idx_collection_run_project", table_name="collection_runs")
    op.drop_column("collection_runs", "project_id")
