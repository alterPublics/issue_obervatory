"""Add comments_config JSONB column to projects table.

Per-platform comment collection configuration. Researchers can enable
comment collection for specific platforms (Reddit, Bluesky, YouTube, etc.)
with configurable modes: search_terms, source_list_actors, or post_urls.

When empty (default {}), no comment collection is triggered (backward compatible).

Revision ID: 032
Revises: 031
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "comments_config",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment=(
                "Per-platform comment collection config."
                " Keys are platform names, values are {enabled, mode, ...}."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "comments_config")
