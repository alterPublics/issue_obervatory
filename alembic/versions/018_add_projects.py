"""Add projects table and project_id to query_designs.

Creates the ``projects`` table as an organizational container for grouping
related query designs. Projects provide a hierarchical structure:
User → Project → Query Designs → Collection Runs → Content Records.

A project belongs to a single user (owner_id FK). Query designs can optionally
be attached to a project via the new ``project_id`` column on ``query_designs``.

Key design choices:
- project_id on query_designs is nullable: existing designs have no project,
  and researchers can create designs without assigning them to a project.
- ON DELETE SET NULL on the project_id FK: deleting a project detaches the
  associated query designs but does not delete them. Designs become unattached.
- ON DELETE RESTRICT on the owner_id FK: deleting a user requires explicit
  transfer or deletion of owned projects first.
- visibility field supports 'private' (owner-only) and 'shared' (future: visible
  to all researchers) access control.

Revision ID: 018
Revises: 017
Create Date: 2026-02-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the projects table and add project_id to query_designs."""
    # Create the projects table
    op.create_table(
        "projects",
        # Primary key
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Core fields
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Owner FK: ON DELETE RESTRICT requires explicit transfer/deletion
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Visibility control
        sa.Column(
            "visibility",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'private'"),
        ),
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
    )

    # B-tree index on owner_id for efficient user-scoped queries
    op.create_index(
        "idx_project_owner",
        "projects",
        ["owner_id"],
    )

    # Add project_id column to query_designs
    # ON DELETE SET NULL: deleting a project detaches designs but doesn't delete them
    op.add_column(
        "query_designs",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # B-tree index on project_id for efficient project-scoped queries
    op.create_index(
        "idx_query_design_project",
        "query_designs",
        ["project_id"],
    )


def downgrade() -> None:
    """Remove project_id from query_designs and drop the projects table."""
    # Drop the index and column from query_designs
    op.drop_index("idx_query_design_project", table_name="query_designs")
    op.drop_column("query_designs", "project_id")

    # Drop the projects table and its indexes
    op.drop_index("idx_project_owner", table_name="projects")
    op.drop_table("projects")
