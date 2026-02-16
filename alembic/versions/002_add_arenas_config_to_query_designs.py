"""Add arenas_config JSONB column to query_designs.

The arena configuration grid in the frontend stores per-query-design arena tier
settings (which arenas are enabled and at what tier).  Previously this was stored
as a workaround on the most recent ``CollectionRun`` for a design, which created
a misleading coupling between design configuration and run-time state.

This migration promotes ``arenas_config`` to a first-class column on
``query_designs`` so that:
- Arena config persists independently of whether a collection run has been
  initiated.
- The API can read/write arena config via a stable, predictable location.
- No CollectionRun placeholder is needed just to carry frontend state.

The ``collection_runs.arenas_config`` column is intentionally retained; it
records the arena config that was *active at the time a run was launched*,
which serves as an immutable audit snapshot.

Revision ID: 002
Revises: 001
Create Date: 2026-02-16
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add arenas_config JSONB column to query_designs with an empty-object default."""
    op.add_column(
        "query_designs",
        sa.Column(
            "arenas_config",
            postgresql.JSONB(),
            nullable=False,
            server_default="'{}'::jsonb",
        ),
    )


def downgrade() -> None:
    """Remove arenas_config column from query_designs."""
    op.drop_column("query_designs", "arenas_config")
