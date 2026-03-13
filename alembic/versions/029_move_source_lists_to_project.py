"""Move source lists from query design level to project level.

Adds ``projects.source_config`` JSONB column and ``actor_lists.project_id`` FK.
Makes ``actor_lists.query_design_id`` nullable with ON DELETE SET NULL.

Data migration:
- Merges source list entries from each project's query designs into
  ``project.source_config``, deduplicating.
- Strips source list keys from ``query_designs.arenas_config``.
- Sets ``actor_lists.project_id`` from the parent query design's project_id.

Revision ID: 029
Revises: 028
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None

# Source list keys per arena to migrate from arenas_config.
_SOURCE_LIST_KEYS: dict[str, str] = {
    "rss": "custom_feeds",
    "telegram": "custom_channels",
    "reddit": "custom_subreddits",
    "discord": "custom_channel_ids",
    "wikipedia": "seed_articles",
    "facebook": "custom_pages",
    "instagram": "custom_profiles",
    "bluesky": "custom_accounts",
    "x_twitter": "custom_accounts",
    "youtube": "custom_channels",
    "tiktok": "custom_accounts",
    "threads": "custom_accounts",
    "gab": "custom_accounts",
    "domain_crawler": "target_domains",
}


def upgrade() -> None:
    # --- Schema changes ---

    # 1. Add source_config to projects
    op.add_column(
        "projects",
        sa.Column(
            "source_config",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="Per-arena source lists shared by all query designs in this project.",
        ),
    )

    # 2. Add project_id FK to actor_lists
    op.add_column(
        "actor_lists",
        sa.Column(
            "project_id",
            sa.UUID(),
            nullable=True,
        ),
    )
    op.create_index("ix_actor_lists_project_id", "actor_lists", ["project_id"])
    op.create_foreign_key(
        "fk_actor_lists_project_id",
        "actor_lists",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 3. Make query_design_id nullable and change ondelete to SET NULL
    op.alter_column(
        "actor_lists",
        "query_design_id",
        existing_type=sa.UUID(),
        nullable=True,
    )
    # Drop the old FK and recreate with SET NULL
    op.drop_constraint(
        "actor_lists_query_design_id_fkey", "actor_lists", type_="foreignkey"
    )
    op.create_foreign_key(
        "actor_lists_query_design_id_fkey",
        "actor_lists",
        "query_designs",
        ["query_design_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # --- Data migration ---
    conn = op.get_bind()

    # 4. Merge source lists from query_designs.arenas_config into project.source_config
    projects = conn.execute(sa.text("SELECT id FROM projects")).fetchall()

    for (project_id,) in projects:
        # Fetch all arenas_config from query designs in this project
        rows = conn.execute(
            sa.text(
                "SELECT id, arenas_config FROM query_designs "
                "WHERE project_id = :pid AND arenas_config IS NOT NULL"
            ),
            {"pid": project_id},
        ).fetchall()

        merged_source_config: dict = {}

        for _qd_id, arenas_config in rows:
            if not isinstance(arenas_config, dict):
                continue

            for arena_name, config_key in _SOURCE_LIST_KEYS.items():
                arena_section = arenas_config.get(arena_name)
                if not isinstance(arena_section, dict):
                    continue
                source_list = arena_section.get(config_key)
                if not isinstance(source_list, list) or not source_list:
                    continue

                # Merge into project source_config, deduplicating
                if arena_name not in merged_source_config:
                    merged_source_config[arena_name] = {config_key: []}

                existing = set(
                    merged_source_config[arena_name].get(config_key, [])
                )
                for item in source_list:
                    if item not in existing:
                        merged_source_config.setdefault(arena_name, {}).setdefault(
                            config_key, []
                        ).append(item)
                        existing.add(item)

        # Write merged source_config to project
        if merged_source_config:
            conn.execute(
                sa.text(
                    "UPDATE projects SET source_config = CAST(:sc AS jsonb) WHERE id = :pid"
                ),
                {"sc": json.dumps(merged_source_config), "pid": project_id},
            )

        # 5. Strip source list keys from query_designs.arenas_config
        for qd_id, arenas_config in rows:
            if not isinstance(arenas_config, dict):
                continue

            cleaned = dict(arenas_config)
            changed = False
            for arena_name, config_key in _SOURCE_LIST_KEYS.items():
                arena_section = cleaned.get(arena_name)
                if isinstance(arena_section, dict) and config_key in arena_section:
                    del arena_section[config_key]
                    changed = True
                    # Remove the arena section entirely if now empty
                    if not arena_section:
                        del cleaned[arena_name]

            if changed:
                conn.execute(
                    sa.text(
                        "UPDATE query_designs SET arenas_config = CAST(:ac AS jsonb) WHERE id = :qid"
                    ),
                    {"ac": json.dumps(cleaned), "qid": qd_id},
                )

    # 6. Set actor_lists.project_id from query_designs.project_id
    conn.execute(
        sa.text(
            "UPDATE actor_lists al "
            "SET project_id = qd.project_id "
            "FROM query_designs qd "
            "WHERE al.query_design_id = qd.id "
            "AND qd.project_id IS NOT NULL"
        )
    )


def downgrade() -> None:
    # --- Reverse data migration ---
    conn = op.get_bind()

    # Move source lists back from project.source_config into query_designs.arenas_config.
    # We write the project's source_config into ALL its query designs' arenas_config.
    projects = conn.execute(
        sa.text("SELECT id, source_config FROM projects WHERE source_config != '{}'::jsonb")
    ).fetchall()

    for project_id, source_config in projects:
        if not isinstance(source_config, dict):
            continue

        qd_rows = conn.execute(
            sa.text(
                "SELECT id, arenas_config FROM query_designs WHERE project_id = :pid"
            ),
            {"pid": project_id},
        ).fetchall()

        for qd_id, arenas_config in qd_rows:
            merged = dict(arenas_config) if isinstance(arenas_config, dict) else {}
            for arena_name, arena_data in source_config.items():
                if arena_name not in merged:
                    merged[arena_name] = {}
                if isinstance(arena_data, dict):
                    merged[arena_name].update(arena_data)

            conn.execute(
                sa.text(
                    "UPDATE query_designs SET arenas_config = CAST(:ac AS jsonb) WHERE id = :qid"
                ),
                {"ac": json.dumps(merged), "qid": qd_id},
            )

    # Clear actor_lists.project_id
    conn.execute(sa.text("UPDATE actor_lists SET project_id = NULL"))

    # --- Schema rollback ---
    # Restore query_design_id FK to CASCADE and NOT NULL
    op.drop_constraint(
        "actor_lists_query_design_id_fkey", "actor_lists", type_="foreignkey"
    )
    op.create_foreign_key(
        "actor_lists_query_design_id_fkey",
        "actor_lists",
        "query_designs",
        ["query_design_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column(
        "actor_lists",
        "query_design_id",
        existing_type=sa.UUID(),
        nullable=False,
    )

    # Drop project_id FK and column from actor_lists
    op.drop_constraint("fk_actor_lists_project_id", "actor_lists", type_="foreignkey")
    op.drop_index("ix_actor_lists_project_id", table_name="actor_lists")
    op.drop_column("actor_lists", "project_id")

    # Drop source_config from projects
    op.drop_column("projects", "source_config")
