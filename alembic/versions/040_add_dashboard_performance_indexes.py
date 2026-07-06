"""Add indexes to improve dashboard query performance.

Addresses several missing indexes identified by profiling the dashboard page
load, which fires 8+ concurrent DB queries on every visit:

collection_runs:
- Composite (initiated_by, status) — used by /collections/active-count,
  polled every 15 seconds.
- Composite (project_id, started_at) — used by the dashboard project list
  which groups by project and orders by MAX(started_at).

content_records:
- B-tree on language — used by filter-options, volume, actors, and terms
  dashboard endpoints for language filtering.
- B-tree on collected_at — used by snapshot delta volume ORDER BY and date
  range filtering on collected_at.

content_record_links:
- Composite (query_design_id, content_record_id, content_record_published_at)
  — used by the correlated EXISTS subquery in _filters.build_content_filters
  when scoping by query_design_ids.  The existing composite index only covers
  the collection_run_id path.

Revision ID: 040
Revises: 039
"""

from __future__ import annotations

from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- collection_runs --
    op.create_index(
        "idx_collection_runs_user_status",
        "collection_runs",
        ["initiated_by", "status"],
    )
    op.create_index(
        "idx_collection_runs_project_started",
        "collection_runs",
        ["project_id", "started_at"],
    )

    # -- content_records (partitioned — indexes inherit to all partitions) --
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_language "
        "ON content_records (language)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_collected_at "
        "ON content_records (collected_at)"
    )

    # -- content_record_links --
    op.create_index(
        "idx_content_record_links_qd_record",
        "content_record_links",
        ["query_design_id", "content_record_id", "content_record_published_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_content_record_links_qd_record", table_name="content_record_links")
    op.execute("DROP INDEX IF EXISTS idx_content_collected_at")
    op.execute("DROP INDEX IF EXISTS idx_content_language")
    op.drop_index("idx_collection_runs_project_started", table_name="collection_runs")
    op.drop_index("idx_collection_runs_user_status", table_name="collection_runs")
