"""Add content_annotations table for qualitative coding of content records.

Creates the ``content_annotations`` table which stores researcher-coded
qualitative judgements (stance, frame, relevance, free-text notes, and JSONB
tags) on individual content records.

Key design choices:
- No FK to content_records: content_records is range-partitioned with a
  composite PK (id, published_at).  PostgreSQL requires that a FK reference
  matches the full composite PK, which would tightly couple this table to the
  partition scheme.  Instead, (content_record_id, content_published_at) are
  kept as a logical reference.
- One annotation per user per record enforced by uq_annotation_user_record.
- GIN index on the JSONB tags column for fast containment queries.
- created_by FK uses ON DELETE SET NULL so that annotations survive user
  deletion (preserving the audit trail for shared research datasets).

Revision ID: 005
Revises: 004
Create Date: 2026-02-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the content_annotations table with all indexes."""
    op.create_table(
        "content_annotations",
        # Primary key
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        # Ownership — SET NULL so annotations survive user deletion.
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Logical reference into the partitioned content_records table.
        # No DB-level FK — see module docstring.
        sa.Column(
            "content_record_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "content_published_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        # Qualitative coding fields
        sa.Column("stance", sa.String(20), nullable=True),
        sa.Column("frame", sa.String(200), nullable=True),
        sa.Column("is_relevant", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        # Context links
        sa.Column(
            "collection_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("collection_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "query_design_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("query_designs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Flexible researcher-defined tags (stored as a JSON array of strings)
        sa.Column("tags", postgresql.JSONB(), nullable=True),
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
            "created_by",
            "content_record_id",
            "content_published_at",
            name="uq_annotation_user_record",
        ),
    )

    # B-tree indexes for common filter/join columns
    op.create_index(
        "idx_annotation_created_by",
        "content_annotations",
        ["created_by"],
    )
    op.create_index(
        "idx_annotation_content_record",
        "content_annotations",
        ["content_record_id"],
    )
    op.create_index(
        "idx_annotation_published_at",
        "content_annotations",
        ["content_published_at"],
    )
    op.create_index(
        "idx_annotation_run",
        "content_annotations",
        ["collection_run_id"],
    )
    op.create_index(
        "idx_annotation_qd",
        "content_annotations",
        ["query_design_id"],
    )

    # GIN index for fast JSONB tag containment queries (e.g. tags @> '["x"]').
    op.create_index(
        "idx_annotation_tags",
        "content_annotations",
        ["tags"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Drop the content_annotations table and all its indexes."""
    # Drop indexes before the table (Alembic will also drop them as part of
    # drop_table, but being explicit here makes the downgrade intent clear).
    op.drop_index("idx_annotation_tags", table_name="content_annotations")
    op.drop_index("idx_annotation_qd", table_name="content_annotations")
    op.drop_index("idx_annotation_run", table_name="content_annotations")
    op.drop_index("idx_annotation_published_at", table_name="content_annotations")
    op.drop_index("idx_annotation_content_record", table_name="content_annotations")
    op.drop_index("idx_annotation_created_by", table_name="content_annotations")
    op.drop_table("content_annotations")
