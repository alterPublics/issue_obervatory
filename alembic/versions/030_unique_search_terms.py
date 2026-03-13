"""Add unique constraint on search_terms to prevent duplicate terms.

Revision ID: 030
Revises: 029
"""
from __future__ import annotations

from alembic import op

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Unique index on (query_design_id, term, group_id) for default terms
    # (where parent_term_id IS NULL).  Override terms are scoped by
    # parent_term_id + override_arena which already has an index.
    # COALESCE handles NULL group_id so that two terms with NULL group_id
    # are still considered duplicates of each other.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_search_term_per_design
        ON search_terms (query_design_id, term, COALESCE(group_id, '00000000-0000-0000-0000-000000000000'))
        WHERE parent_term_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("uq_search_term_per_design", table_name="search_terms")
