"""Add platform_url_errors table for dead page suppression.

Tracks URLs that consistently return errors from data providers
(e.g. Bright Data dead_page, login_required). URLs with failure_count >= 2
and last_seen_at within 30 days are suppressed from future collection runs.

Revision ID: 028
Revises: 027
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_url_errors",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("error_code", sa.String(100), nullable=False),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column(
            "first_seen_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "last_seen_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "failure_count",
            sa.Integer,
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.UniqueConstraint("platform", "url", name="uq_platform_url_errors_platform_url"),
    )
    op.create_index(
        "idx_platform_url_errors_lookup",
        "platform_url_errors",
        ["platform", "failure_count", "last_seen_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_platform_url_errors_lookup", table_name="platform_url_errors")
    op.drop_table("platform_url_errors")
