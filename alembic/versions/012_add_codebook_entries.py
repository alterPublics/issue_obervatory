"""Add codebook_entries table for managing qualitative coding schemes.

Creates the ``codebook_entries`` table which stores reusable qualitative coding
schemes (codebooks) that researchers can apply when annotating content records.

Codebooks define structured vocabularies of codes, labels, and descriptions that
standardize annotation practices across a query design or globally.

Key design choices:
- query_design_id is nullable: NULL indicates a global/shared codebook entry
  available across all query designs.  Non-NULL indicates a query-design-specific
  codebook entry.
- Unique constraint on (query_design_id, code) prevents duplicate codes within
  a codebook scope.  PostgreSQL treats NULL as a distinct value per row in
  UNIQUE constraints, so global codes are unique separately from query-design-
  specific codes.
- category field allows grouping related codes (e.g., "framing", "stance",
  "topic") for hierarchical UI presentation.
- query_design_id FK uses ON DELETE CASCADE so that deleting a query design
  removes its codebook entries.

Revision ID: 012
Revises: 011
Create Date: 2026-02-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the codebook_entries table with all indexes."""
    op.create_table(
        "codebook_entries",
        # Primary key
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        # Scope: NULL = global/shared, non-NULL = query-design-specific.
        # ON DELETE CASCADE: deleting a query design removes its codebook.
        sa.Column(
            "query_design_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("query_designs.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # Machine-readable code (stable identifier).
        sa.Column("code", sa.String(100), nullable=False),
        # Human-readable label for the UI.
        sa.Column("label", sa.String(200), nullable=False),
        # Optional detailed explanation.
        sa.Column("description", sa.Text(), nullable=True),
        # Optional grouping label (e.g., "framing", "stance", "topic").
        sa.Column("category", sa.String(100), nullable=True),
        # TimestampMixin columns
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        # Table-level constraints
        sa.UniqueConstraint(
            "query_design_id",
            "code",
            name="uq_codebook_entry_scope_code",
        ),
    )

    # B-tree index on query_design_id for scoped lookups.
    op.create_index(
        "idx_codebook_entry_qd",
        "codebook_entries",
        ["query_design_id"],
    )

    # B-tree index on category for grouping/filtering in the UI.
    op.create_index(
        "idx_codebook_entry_category",
        "codebook_entries",
        ["category"],
    )


def downgrade() -> None:
    """Drop the codebook_entries table and all its indexes."""
    op.drop_index("idx_codebook_entry_category", table_name="codebook_entries")
    op.drop_index("idx_codebook_entry_qd", table_name="codebook_entries")
    op.drop_table("codebook_entries")
