"""Add arenas_config JSONB column to projects table.

Project-level arena enable/disable. Intersection filter with QD arenas_config:
an arena must be enabled at both project and query design level to dispatch.
When empty (default {}), all QD-enabled arenas pass through (backward compatible).

Revision ID: 031
Revises: 030
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "arenas_config",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment=(
                "Project-level arena enable/disable."
                " Intersection filter with QD arenas_config."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "arenas_config")
