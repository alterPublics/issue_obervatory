"""Make content_hash index unique to support ON CONFLICT deduplication.

Replaces the non-unique B-tree index on content_records.content_hash with a
unique partial index. This is required for the Zeeschuimer import process,
which uses `ON CONFLICT (content_hash) DO NOTHING` to avoid inserting
duplicate content.

PostgreSQL requires a unique index or unique constraint for ON CONFLICT
specifications. The original migration (001) created a non-unique index,
which causes every Zeeschuimer import INSERT to fail with:

    ERROR: there is no unique or exclusion constraint matching
           the ON CONFLICT specification

The partial index (WHERE content_hash IS NOT NULL) is necessary because
content_hash is nullable — records without text content may have NULL
content_hash values, and PostgreSQL requires that multiple NULLs be allowed
even when using a unique index.

PARTITIONING NOTE
-----------------
The content_records table is partitioned by published_at (monthly ranges).
PostgreSQL automatically creates the partial unique index on each partition
when it is created on the parent table. No separate partition-level DDL
is required.

Revision ID: 015
Revises: 014
Create Date: 2026-02-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _exec(sql: str) -> None:
    """Execute a raw SQL string via the current Alembic connection."""
    op.execute(sa.text(sql))


def upgrade() -> None:
    """Replace non-unique content_hash index with unique partial index."""
    # Drop the existing non-unique index created in migration 001
    _exec("DROP INDEX IF EXISTS idx_content_hash")

    # Create a unique partial index that excludes NULL values.
    # Must include published_at because content_records is partitioned by it —
    # PostgreSQL requires all partition key columns in unique indexes.
    # ON CONFLICT clauses must reference (content_hash, published_at) accordingly.
    _exec("""
        CREATE UNIQUE INDEX idx_content_hash_unique
        ON content_records (content_hash, published_at)
        WHERE content_hash IS NOT NULL
    """)


def downgrade() -> None:
    """Restore the original non-unique index."""
    # Drop the unique partial index
    _exec("DROP INDEX IF EXISTS idx_content_hash_unique")

    # Recreate the original non-unique B-tree index from migration 001
    _exec("CREATE INDEX idx_content_hash ON content_records (content_hash, published_at)")
