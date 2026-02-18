"""Add parent_design_id to query_designs for cloning lineage tracking.

Adds a nullable self-referential foreign-key column ``parent_design_id`` to
``query_designs``.  When a researcher clones a query design via
``POST /query-designs/{design_id}/clone``, the resulting copy records the
UUID of the original design in this column so that lineage can be traced.

Design choices:
- ``ON DELETE SET NULL``: deleting the parent design must not cascade to
  clones.  Clones are independent research instruments; only the lineage
  reference is cleared.
- The column is nullable because most query designs are created from scratch
  (not via cloning) and have no parent.
- A B-tree index supports efficient queries such as
  ``WHERE parent_design_id = ?`` (e.g. "show all clones of design X").

Revision ID: 008
Revises: 007
Create Date: 2026-02-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add parent_design_id column and index to query_designs."""
    op.add_column(
        "query_designs",
        sa.Column(
            "parent_design_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("query_designs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_query_design_parent",
        "query_designs",
        ["parent_design_id"],
    )


def downgrade() -> None:
    """Remove parent_design_id column and index from query_designs."""
    op.drop_index("idx_query_design_parent", table_name="query_designs")
    op.drop_column("query_designs", "parent_design_id")
