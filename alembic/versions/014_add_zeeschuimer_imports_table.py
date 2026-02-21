"""Add zeeschuimer_imports table for manual data import tracking.

Creates the zeeschuimer_imports table to track manual data uploads from the
Zeeschuimer browser extension. This enables IO to accept NDJSON data directly
from Zeeschuimer, providing a collection pathway for platforms that lack
automated collection support (primarily LinkedIn).

Each import record tracks:
- A unique short key for Zeeschuimer polling (e.g., "import-abc123")
- The platform/module_id from the X-Zeeschuimer-Platform header
- Processing status (queued → processing → complete/failed)
- Progress tracking (rows_total, rows_processed, rows_imported)
- Optional association with a query design for organization
- Audit trail (who initiated, when started/completed, error messages)

Imported content_records are tagged with:
- collection_tier = "manual"
- raw_metadata.import_source = "zeeschuimer"
- raw_metadata.zeeschuimer_import_id = {import.id}

This table is distinct from collection_runs because Zeeschuimer imports are
push-based (browser sends data to server) rather than pull-based (server queries
API), and they don't execute query designs or follow the batch/live collection
model.

See /docs/research_reports/zeeschuimer_4cat_protocol.md for the full protocol
specification.

Revision ID: 014
Revises: 013
Create Date: 2026-02-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the zeeschuimer_imports table."""
    op.create_table(
        "zeeschuimer_imports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "key",
            sa.String(length=100),
            nullable=False,
            comment="Short identifier for polling (e.g., 'import-abc123')",
        ),
        sa.Column(
            "initiated_by",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "query_design_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Optional association with a query design for organization",
        ),
        sa.Column(
            "platform",
            sa.String(length=50),
            nullable=False,
            comment="Zeeschuimer module_id (e.g., 'linkedin.com', 'twitter.com')",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'queued'"),
            nullable=False,
            comment="queued | processing | complete | failed",
        ),
        sa.Column(
            "rows_total",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="Total number of NDJSON lines in the upload",
        ),
        sa.Column(
            "rows_processed",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="Number of lines successfully processed",
        ),
        sa.Column(
            "rows_imported",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="Number of content_records created (after deduplication)",
        ),
        sa.Column(
            "started_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "file_path",
            sa.String(length=500),
            nullable=True,
            comment="Path to the uploaded NDJSON file (deleted after processing)",
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=True,
            comment="Additional metadata (e.g., file size, user agent)",
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_zeeschuimer_imports")),
        sa.ForeignKeyConstraint(
            ["initiated_by"],
            ["users.id"],
            name=op.f("fk_zeeschuimer_imports_initiated_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["query_design_id"],
            ["query_designs.id"],
            name=op.f("fk_zeeschuimer_imports_query_design_id_query_designs"),
            ondelete="SET NULL",
        ),
    )

    # Indexes for efficient lookups
    op.create_index(
        op.f("ix_zeeschuimer_imports_key"),
        "zeeschuimer_imports",
        ["key"],
        unique=True,
    )
    op.create_index(
        op.f("ix_zeeschuimer_imports_initiated_by"),
        "zeeschuimer_imports",
        ["initiated_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_zeeschuimer_imports_query_design_id"),
        "zeeschuimer_imports",
        ["query_design_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_zeeschuimer_imports_platform"),
        "zeeschuimer_imports",
        ["platform"],
        unique=False,
    )
    op.create_index(
        op.f("ix_zeeschuimer_imports_status"),
        "zeeschuimer_imports",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the zeeschuimer_imports table."""
    op.drop_index(
        op.f("ix_zeeschuimer_imports_status"),
        table_name="zeeschuimer_imports",
    )
    op.drop_index(
        op.f("ix_zeeschuimer_imports_platform"),
        table_name="zeeschuimer_imports",
    )
    op.drop_index(
        op.f("ix_zeeschuimer_imports_query_design_id"),
        table_name="zeeschuimer_imports",
    )
    op.drop_index(
        op.f("ix_zeeschuimer_imports_initiated_by"),
        table_name="zeeschuimer_imports",
    )
    op.drop_index(
        op.f("ix_zeeschuimer_imports_key"),
        table_name="zeeschuimer_imports",
    )
    op.drop_table("zeeschuimer_imports")
