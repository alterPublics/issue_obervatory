"""Add user_templates table and extend users with template/credential/platform fields.

Revision ID: 038
Revises: 037
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create user_templates table
    op.create_table(
        "user_templates",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "credits_amount", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "allowed_platforms",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "disallowed_platforms",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "use_central_credentials",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # 2. Add columns to users table
    op.add_column(
        "users",
        sa.Column("template_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "use_central_credentials",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "allowed_platforms",
            JSONB,
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "disallowed_platforms",
            JSONB,
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    # 3. Add FK and index
    op.create_foreign_key(
        "fk_users_template_id",
        "users",
        "user_templates",
        ["template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_users_template_id", "users", ["template_id"])


def downgrade() -> None:
    op.drop_index("ix_users_template_id", "users")
    op.drop_constraint("fk_users_template_id", "users", type_="foreignkey")
    op.drop_column("users", "disallowed_platforms")
    op.drop_column("users", "allowed_platforms")
    op.drop_column("users", "use_central_credentials")
    op.drop_column("users", "template_id")
    op.drop_table("user_templates")
