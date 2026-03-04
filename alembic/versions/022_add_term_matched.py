"""Add term_matched flag to content_records.

Distinguishes content that matched search terms from content collected
via actor-based collection without a term match.  Defaults to true so
all existing records are treated as term-matched (correct: historical
records were all collected via search-based or filtered collection).

Key design choices:
- NOT NULL with server_default true: safe for partitioned table DDL.
- Partial index on term_matched = false: the minority case (actor-collected
  non-matching content) benefits from an index; the majority (true) does not.
- The content browser defaults to WHERE term_matched = true, hiding
  non-matching records unless the researcher explicitly toggles "Show all".

Revision ID: 022
Revises: 021
Create Date: 2026-02-26
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add term_matched boolean column to content_records."""
    op.add_column(
        "content_records",
        sa.Column(
            "term_matched",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # Partial index for the minority case: records that did NOT match a term.
    op.execute(
        "CREATE INDEX idx_content_term_matched "
        "ON content_records (term_matched) "
        "WHERE term_matched = false"
    )


def downgrade() -> None:
    """Remove term_matched from content_records."""
    op.execute("DROP INDEX IF EXISTS idx_content_term_matched")
    op.drop_column("content_records", "term_matched")
