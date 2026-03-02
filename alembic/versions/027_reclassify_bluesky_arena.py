"""Reclassify Bluesky arena from 'bluesky' to 'social_media'.

Bluesky records were stored with arena='bluesky' instead of
'social_media' (the grouping used by all other social media collectors).
This migration updates existing records to use the correct arena label.

Revision ID: 027
Revises: 026
"""

from __future__ import annotations

from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE content_records SET arena = 'social_media' WHERE arena = 'bluesky'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE content_records SET arena = 'bluesky'"
        " WHERE arena = 'social_media' AND platform = 'bluesky'"
    )
