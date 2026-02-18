"""Add group_id and group_label to search_terms.

Allows researchers to categorise search terms into named groups within a
query design (e.g. "Primary terms", "English variants").  Terms with the
same ``group_id`` belong to the same group; ``NULL`` means ungrouped.
``group_label`` is the human-readable display name for the group and is
expected to be identical for all rows sharing a ``group_id``.

Revision ID: 006
Revises: 005
Create Date: 2026-02-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add group_id and group_label columns to search_terms."""
    op.add_column(
        "search_terms",
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "search_terms",
        sa.Column(
            "group_label",
            sa.String(200),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_search_term_group",
        "search_terms",
        ["group_id"],
    )


def downgrade() -> None:
    """Remove group_id and group_label columns from search_terms."""
    op.drop_index("idx_search_term_group", table_name="search_terms")
    op.drop_column("search_terms", "group_label")
    op.drop_column("search_terms", "group_id")
