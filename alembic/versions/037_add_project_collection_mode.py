"""Add collection_mode column to projects table.

Supports 'default' (terms + actors) and 'actors_only' (skip term-based
collection, dispatch only collect_by_actors using source lists).

Revision ID: 037
Revises: 036
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "collection_mode",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'default'"),
            comment="Collection mode: 'default' or 'actors_only'.",
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "collection_mode")
