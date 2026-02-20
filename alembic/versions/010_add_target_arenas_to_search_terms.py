"""Add target_arenas to search_terms.

Implements YF-01: Per-Arena Search Term Scoping.

Adds an optional ``target_arenas`` JSONB column to the ``search_terms`` table,
allowing researchers to specify which arena platform_names (e.g. ``["reddit", "youtube"]``)
a given term should be dispatched to.  When ``NULL``, the term applies to all
enabled arenas in the collection run (backward-compatible default).

This prevents credit waste and contamination by allowing terms to be scoped to
relevant platforms (e.g., Danish terms to Danish-language arenas, English terms
to multi-language arenas like YouTube).

Revision ID: 010
Revises: 009
Create Date: 2026-02-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add target_arenas column to search_terms."""
    op.add_column(
        "search_terms",
        sa.Column(
            "target_arenas",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Optional list of arena platform_names. NULL = all arenas.",
        ),
    )


def downgrade() -> None:
    """Remove target_arenas column from search_terms."""
    op.drop_column("search_terms", "target_arenas")
