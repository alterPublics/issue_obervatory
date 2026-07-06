"""Add engagement_scalers table for data-driven engagement normalization.

Stores per-platform fitted Yeo-Johnson + MinMaxScaler parameters so that
engagement scores can be computed using pure-Python math at scoring time,
without requiring sklearn at inference.

Revision ID: 036
Revises: 035
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "engagement_scalers",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("platform", sa.String(50), nullable=False, unique=True),
        sa.Column("transformer_params", JSONB, nullable=False),
        sa.Column("scaler_params", JSONB, nullable=False),
        sa.Column("sample_size", sa.Integer, nullable=False),
        sa.Column("stats", JSONB, nullable=True),
        sa.Column("fitted_at", sa.DateTime(timezone=True), nullable=False),
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


def downgrade() -> None:
    op.drop_table("engagement_scalers")
