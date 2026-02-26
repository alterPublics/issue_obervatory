"""Add parent_term_id and override_arena to search_terms.

Enables arena-specific term overrides: a SearchTerm with parent_term_id and
override_arena set replaces the parent default term for that specific arena.

Key design choices:
- parent_term_id is a self-referential FK with CASCADE delete (removing a
  default term removes all its overrides).
- CHECK constraint ensures both columns are NULL or both are non-NULL.
- Composite index on (parent_term_id, override_arena) for efficient lookups.

Revision ID: 020
Revises: 019
Create Date: 2026-02-26
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add parent_term_id and override_arena columns to search_terms."""
    # Self-referential FK for override lineage
    op.add_column(
        "search_terms",
        sa.Column(
            "parent_term_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("search_terms.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    # Arena platform_name that this override applies to
    op.add_column(
        "search_terms",
        sa.Column(
            "override_arena",
            sa.String(50),
            nullable=True,
        ),
    )

    # Composite index for efficient override lookups
    op.create_index(
        "idx_search_term_parent_override",
        "search_terms",
        ["parent_term_id", "override_arena"],
    )

    # CHECK constraint: both NULL or both non-NULL
    op.create_check_constraint(
        "ck_search_term_override_pair",
        "search_terms",
        "(parent_term_id IS NULL AND override_arena IS NULL) "
        "OR (parent_term_id IS NOT NULL AND override_arena IS NOT NULL)",
    )


def downgrade() -> None:
    """Remove parent_term_id and override_arena from search_terms."""
    op.drop_constraint("ck_search_term_override_pair", "search_terms", type_="check")
    op.drop_index("idx_search_term_parent_override", table_name="search_terms")
    op.drop_column("search_terms", "override_arena")
    op.drop_column("search_terms", "parent_term_id")
