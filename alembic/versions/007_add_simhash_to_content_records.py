"""Add simhash column to content_records for near-duplicate detection.

Adds a 64-bit SimHash fingerprint column (``simhash BIGINT NULL``) to the
``content_records`` table.  SimHash enables fast approximate-duplicate
detection via Hamming distance comparison: two records with a Hamming distance
<= 3 bits are considered near-duplicates.

Implementation notes:
- ``content_records`` is range-partitioned by ``published_at``.  Alembic's
  ``op.add_column()`` does NOT propagate to all child partitions when used
  against a partitioned parent table in PostgreSQL — it only alters the
  parent table DDL, leaving the existing partitions without the column.
  We therefore use raw DDL (``op.execute`` with ALTER TABLE) which PostgreSQL
  propagates automatically to all existing and future partitions.
- The B-tree index ``idx_content_records_simhash`` is created on the parent
  table and is inherited by partitions (PostgreSQL 11+).
- ``NULL`` means the SimHash has not yet been computed (e.g. record has no
  text content, or was collected before this migration ran).

Revision ID: 007
Revises: 006
Create Date: 2026-02-18
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add simhash BIGINT NULL column and B-tree index to content_records.

    Uses raw ALTER TABLE DDL because content_records is partitioned.
    op.add_column() does not propagate to child partitions; ALTER TABLE does.
    """
    op.execute(
        "ALTER TABLE content_records ADD COLUMN IF NOT EXISTS simhash BIGINT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_records_simhash "
        "ON content_records (simhash)"
    )


def downgrade() -> None:
    """Drop the simhash index and column from content_records."""
    op.execute("DROP INDEX IF EXISTS idx_content_records_simhash")
    op.execute("ALTER TABLE content_records DROP COLUMN IF EXISTS simhash")
