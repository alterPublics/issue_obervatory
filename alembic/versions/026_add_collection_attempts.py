"""Add collection_attempts table for scalable pre-collection checks.

Lightweight metadata log of every collection attempt — mirrors the ``pull``
collection from the legacy spreadAnalysis MongoDB tool.  The pre-collection
coverage checker queries this small table instead of scanning the
partitioned ``content_records`` table.

Revision ID: 026
Revises: 025
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collection_attempts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column(
            "input_value",
            sa.Text,
            nullable=False,
            comment="Search term or actor platform ID that was collected.",
        ),
        sa.Column(
            "input_type",
            sa.String(20),
            nullable=False,
            comment="'term' or 'actor' — the type of input_value.",
        ),
        sa.Column("date_from", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("date_to", TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "records_returned",
            sa.Integer,
            nullable=True,
            comment="Number of records returned. NULL if attempt failed.",
        ),
        sa.Column(
            "collection_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("collection_runs.id", ondelete="CASCADE"),
            nullable=True,
            comment=(
                "NULL for synthetic backfill rows created by the coverage "
                "checker fallback."
            ),
        ),
        sa.Column(
            "query_design_id",
            UUID(as_uuid=True),
            sa.ForeignKey("query_designs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "attempted_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "is_valid",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("TRUE"),
            comment=(
                "Set to FALSE by reconciliation when underlying data "
                "no longer exists in content_records."
            ),
        ),
    )

    # Primary lookup index for the coverage checker.
    op.create_index(
        "idx_collection_attempts_lookup",
        "collection_attempts",
        ["platform", "input_value", "input_type"],
    )

    # Cascade cleanup — find attempts for a given run.
    op.create_index(
        "idx_collection_attempts_run",
        "collection_attempts",
        ["collection_run_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_collection_attempts_run", table_name="collection_attempts")
    op.drop_index("idx_collection_attempts_lookup", table_name="collection_attempts")
    op.drop_table("collection_attempts")
