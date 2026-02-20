"""Add GIN index on search_terms.target_arenas.

Improves performance of YF-01 per-arena search term filtering by adding a
GIN index on the ``target_arenas`` JSONB column. This accelerates the JSONB
``has_key()`` operator used in ``fetch_search_terms_for_arena()`` to filter
terms by arena platform_name.

Without this index, every collection dispatch performs a sequential scan of
the ``search_terms`` table. With the index, lookups are O(log n) instead of O(n).

Revision ID: 011
Revises: 010
Create Date: 2026-02-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add GIN index on target_arenas for efficient JSONB key lookups."""
    op.create_index(
        "ix_search_terms_target_arenas_gin",
        "search_terms",
        ["target_arenas"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Remove GIN index on target_arenas."""
    op.drop_index(
        "ix_search_terms_target_arenas_gin",
        table_name="search_terms",
    )
