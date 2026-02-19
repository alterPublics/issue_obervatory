"""Add public_figure flag to actors table for GR-14 pseudonymization bypass.

GR-14 implements a GDPR Article 89(1) research-exemption exception to the
default SHA-256 pseudonymization applied to all author identifiers collected
by the observatory.

Background
----------
The normalizer stores a salted SHA-256 hash of each author's platform user ID
as ``content_records.pseudonymized_author_id``.  This protects private
individuals' identities in compliance with GDPR.

For political discourse research, elected and appointed public officials
(Danish Folketing MPs, Greenlandic ministers, US federal officials, etc.)
make statements in their official capacity that are part of the public record.
Pseudonymizing these authors makes it impossible to attribute collected
content to named public figures, defeating a primary research purpose.

This migration adds a single boolean column to the ``actors`` table.  When set
to ``True``, the collection pipeline must store the plain platform username in
``pseudonymized_author_id`` instead of the salted hash.  The column defaults to
``false`` so that every existing actor continues to be pseudonymized unless
explicitly opted in.

GDPR compliance constraints
----------------------------
- Exemption applies strictly under GDPR Art. 89(1) (scientific research).
- Must only be applied to publicly elected or appointed officials acting in
  their official capacity.
- Private individuals must remain pseudonymized regardless of public
  prominence.
- The research institution's Data Protection Officer (DPO) must periodically
  review the set of actors flagged ``public_figure = true``.

Implementation note for the Core Application Engineer
------------------------------------------------------
The pseudonymization bypass is *not* automatic from this migration alone.
``core/normalizer.py`` must be updated to accept an ``is_public_figure`` flag
and return the raw platform username when the flag is ``True``.  See
``docs/status/db.md`` (GR-14 section) for the exact change required.

Revision ID: 009
Revises: 008
Create Date: 2026-02-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add public_figure BOOLEAN NOT NULL DEFAULT false to actors.

    The server-side default ensures all existing actor rows receive ``false``
    without requiring a full-table rewrite in PostgreSQL (the default is
    written directly to the column's default metadata and applied to new rows;
    existing rows are populated by the NOT NULL + DEFAULT combination).
    """
    op.add_column(
        "actors",
        sa.Column(
            "public_figure",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
            comment=(
                "GR-14 — GDPR Art. 89(1) research exemption. "
                "When True, bypass SHA-256 pseudonymization for this actor: "
                "store the plain platform username as pseudonymized_author_id. "
                "Use ONLY for publicly elected or appointed officials acting in "
                "official capacity. Private individuals must remain pseudonymized. "
                "DPO must review flagged actors periodically."
            ),
        ),
    )


def downgrade() -> None:
    """Remove public_figure column from actors.

    Dropping this column re-enables uniform pseudonymization for all actors.
    Any content records whose pseudonymized_author_id was stored as a plain
    username (rather than a hash) will NOT be retroactively re-hashed by this
    migration — that remediation must be performed separately if needed.
    """
    op.drop_column("actors", "public_figure")
