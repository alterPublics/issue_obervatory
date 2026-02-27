"""Add content_record_links table for cross-design record linking.

When a collection run overlaps with data already collected by another run,
links are created instead of re-fetching from the upstream API.  Analysis
filters include linked records when querying by collection_run_id.

Revision ID: 025
Revises: 024
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_record_links",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("content_record_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "content_record_published_at",
            TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "collection_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("collection_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "query_design_id",
            UUID(as_uuid=True),
            sa.ForeignKey("query_designs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "linked_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "link_type",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'reindex'"),
        ),
        sa.UniqueConstraint(
            "content_record_id",
            "content_record_published_at",
            "collection_run_id",
            name="uq_content_record_link",
        ),
    )
    op.create_index(
        "idx_content_record_links_run",
        "content_record_links",
        ["collection_run_id"],
    )
    op.create_index(
        "idx_content_record_links_design",
        "content_record_links",
        ["query_design_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_content_record_links_design", table_name="content_record_links")
    op.drop_index("idx_content_record_links_run", table_name="content_record_links")
    op.drop_table("content_record_links")
