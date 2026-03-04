"""Add unique constraint on (owner_id, name) for projects.

Prevents a single user from creating multiple projects with the same name.

Revision ID: 023
Revises: 022
"""

from __future__ import annotations

from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_project_owner_name", "projects", ["owner_id", "name"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_project_owner_name", "projects", type_="unique")
