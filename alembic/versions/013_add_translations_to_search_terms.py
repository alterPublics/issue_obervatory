"""Add translations column to search_terms for multilingual query support.

Adds a ``translations`` JSONB column to the ``search_terms`` table to support
IP2-052: Multilingual query design with bilingual term pairing.

When a query design targets multiple languages (via arenas_config["languages"]),
researchers can provide translations of each search term so that collectors use
the appropriate translation when querying arenas in non-Danish languages.

The translations column stores a dictionary mapping ISO 639-1 language codes
to translated term strings::

    {"kl": "CO2-akilerisitsinnaanera", "en": "CO2 tax"}

When NULL or empty, no translations are available (use the primary ``term`` value).

Revision ID: 013
Revises: 012
Create Date: 2026-02-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the translations JSONB column to search_terms."""
    op.add_column(
        "search_terms",
        sa.Column(
            "translations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment=(
                "Optional dict mapping ISO 639-1 language codes to translated terms. "
                "NULL = no translations available."
            ),
        ),
    )


def downgrade() -> None:
    """Remove the translations column from search_terms."""
    op.drop_column("search_terms", "translations")
