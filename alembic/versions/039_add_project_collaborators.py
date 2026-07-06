"""Add project_collaborators table for project sharing.

Revision ID: 039
Revises: 038
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_collaborators",
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'viewer'"),
        ),
        sa.Column("granted_by", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "granted_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("project_id", "user_id"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_project_collaborators_user_id",
        "project_collaborators",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_collaborators_user_id",
        table_name="project_collaborators",
    )
    op.drop_table("project_collaborators")
