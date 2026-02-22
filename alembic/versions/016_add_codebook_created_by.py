"""Add created_by column to codebook_entries table.

The CodebookEntry ORM model defines a ``created_by`` column (FK to users.id)
for ownership tracking, but migration 012 omitted this column from the table
definition.  This migration adds it with a B-tree index for efficient
ownership-scoped queries.

Revision ID: 016
Revises: 015
Create Date: 2026-02-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add created_by column to codebook_entries."""
    op.add_column(
        "codebook_entries",
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_codebook_entry_created_by",
        "codebook_entries",
        ["created_by"],
    )


def downgrade() -> None:
    """Remove created_by column from codebook_entries."""
    op.drop_index("idx_codebook_entry_created_by", table_name="codebook_entries")
    op.drop_column("codebook_entries", "created_by")
