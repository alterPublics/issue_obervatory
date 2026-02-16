"""Initial schema: all core tables, indexes, and content_records partitions.

Creates the complete Issue Observatory database schema in FK-dependency order:

1. users                  — identity and auth
2. credit_allocations     — user credit pools (FK → users)
3. refresh_tokens         — JWT revocation store (FK → users)
4. api_credentials        — encrypted credential pool
5. actors                 — canonical cross-platform entities (FK → users)
6. actor_aliases          — alternative names for actors (FK → actors)
7. actor_platform_presences — per-platform account mappings (FK → actors)
8. query_designs          — owner-scoped research instruments (FK → users)
9. search_terms           — terms within a query design (FK → query_designs)
10. actor_lists           — curated actor sets within a query design (FK → query_designs, users)
11. actor_list_members    — join table (FK → actor_lists, actors)
12. collection_runs       — run-level tracking (FK → query_designs, users)
13. collection_tasks      — per-arena task units (FK → collection_runs, api_credentials)
14. credit_transactions   — immutable audit log (FK → users, collection_runs)
15. content_records       — universal partitioned content table
    + initial partitions for current month and next 2 months
    + all indexes including GIN and full-text Danish

PARTITIONING NOTE
-----------------
content_records is created with PARTITION BY RANGE (published_at).
Alembic's create_table() helper does NOT support postgresql_partition_by —
the table is therefore created via op.execute() with raw DDL.  SQLAlchemy's
autogenerate will NOT detect this table correctly in subsequent runs; this
is intentional.  Do not run alembic revision --autogenerate for schema
changes to content_records — write explicit migrations instead.

Revision ID: 001
Revises:
Create Date: 2026-02-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _exec(sql: str) -> None:
    """Execute a raw SQL string via the current Alembic connection."""
    op.execute(sa.text(sql))


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    """Create all tables, indexes, and initial content_records partitions."""

    # ------------------------------------------------------------------
    # 1. users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("hashed_password", sa.String(1024), nullable=True),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("role", sa.String(20), nullable=False, server_default=sa.text("'researcher'")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("api_key", sa.String(64), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("metadata", JSONB, nullable=True, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_api_key", "users", ["api_key"], unique=True)

    # ------------------------------------------------------------------
    # 2. credit_allocations
    # ------------------------------------------------------------------
    op.create_table(
        "credit_allocations",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("credits_amount", sa.Integer, nullable=False),
        sa.Column("allocated_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("allocated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("valid_from", sa.Date, nullable=False),
        sa.Column("valid_until", sa.Date, nullable=True),
        sa.Column("memo", sa.Text, nullable=True),
    )
    op.create_index("ix_credit_allocations_user_id", "credit_allocations", ["user_id"])

    # ------------------------------------------------------------------
    # 3. refresh_tokens
    # ------------------------------------------------------------------
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)

    # ------------------------------------------------------------------
    # 4. api_credentials
    # ------------------------------------------------------------------
    op.create_table(
        "api_credentials",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("tier", sa.String(10), nullable=False),
        sa.Column("credential_name", sa.String(200), nullable=False),
        sa.Column("credentials", JSONB, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("daily_quota", sa.Integer, nullable=True),
        sa.Column("monthly_quota", sa.Integer, nullable=True),
        sa.Column("quota_reset_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index(
        "idx_credentials_platform_tier_active",
        "api_credentials",
        ["platform", "tier", "is_active"],
    )

    # ------------------------------------------------------------------
    # 5. actors
    # ------------------------------------------------------------------
    op.create_table(
        "actors",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("canonical_name", sa.String(500), nullable=False),
        sa.Column("actor_type", sa.String(50), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_shared", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("metadata", JSONB, nullable=True, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_actors_created_by", "actors", ["created_by"])

    # ------------------------------------------------------------------
    # 6. actor_aliases
    # ------------------------------------------------------------------
    op.create_table(
        "actor_aliases",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("actors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias", sa.String(500), nullable=False),
        sa.UniqueConstraint("actor_id", "alias", name="uq_actor_alias"),
    )
    op.create_index("ix_actor_aliases_actor_id", "actor_aliases", ["actor_id"])

    # ------------------------------------------------------------------
    # 7. actor_platform_presences
    # ------------------------------------------------------------------
    op.create_table(
        "actor_platform_presences",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("actors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("platform_user_id", sa.String(500), nullable=True),
        sa.Column("platform_username", sa.String(500), nullable=True),
        sa.Column("profile_url", sa.String(2000), nullable=True),
        sa.Column("verified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("follower_count", sa.BigInteger, nullable=True),
        sa.Column("last_checked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("platform", "platform_user_id", name="uq_actor_presence_platform_user"),
    )
    op.create_index("ix_actor_platform_presences_actor_id", "actor_platform_presences", ["actor_id"])

    # ------------------------------------------------------------------
    # 8. query_designs
    # ------------------------------------------------------------------
    op.create_table(
        "query_designs",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("visibility", sa.String(20), nullable=False, server_default=sa.text("'private'")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("default_tier", sa.String(10), nullable=False, server_default=sa.text("'free'")),
        sa.Column("language", sa.String(10), nullable=False, server_default=sa.text("'da'")),
        sa.Column("locale_country", sa.String(5), nullable=False, server_default=sa.text("'dk'")),
    )
    op.create_index("ix_query_designs_owner_id", "query_designs", ["owner_id"])

    # ------------------------------------------------------------------
    # 9. search_terms
    # ------------------------------------------------------------------
    op.create_table(
        "search_terms",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("query_design_id", sa.UUID(), sa.ForeignKey("query_designs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("term", sa.Text, nullable=False),
        sa.Column("term_type", sa.String(50), nullable=False, server_default=sa.text("'keyword'")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("added_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_search_terms_query_design_id", "search_terms", ["query_design_id"])

    # ------------------------------------------------------------------
    # 10. actor_lists
    # ------------------------------------------------------------------
    op.create_table(
        "actor_lists",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("query_design_id", sa.UUID(), sa.ForeignKey("query_designs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sampling_method", sa.String(50), nullable=True),
    )
    op.create_index("ix_actor_lists_query_design_id", "actor_lists", ["query_design_id"])
    op.create_index("ix_actor_lists_created_by", "actor_lists", ["created_by"])

    # ------------------------------------------------------------------
    # 11. actor_list_members
    # ------------------------------------------------------------------
    op.create_table(
        "actor_list_members",
        sa.Column("actor_list_id", sa.UUID(), sa.ForeignKey("actor_lists.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("actors.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("added_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("added_by", sa.String(50), nullable=False, server_default=sa.text("'manual'")),
    )

    # ------------------------------------------------------------------
    # 12. collection_runs
    # ------------------------------------------------------------------
    op.create_table(
        "collection_runs",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("query_design_id", sa.UUID(), sa.ForeignKey("query_designs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("initiated_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("tier", sa.String(10), nullable=False, server_default=sa.text("'free'")),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("date_from", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("date_to", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("arenas_config", JSONB, nullable=True, server_default=sa.text("'{}'")),
        sa.Column("estimated_credits", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("credits_spent", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("error_log", sa.Text, nullable=True),
        sa.Column("records_collected", sa.Integer, nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_collection_runs_query_design_id", "collection_runs", ["query_design_id"])
    op.create_index("ix_collection_runs_initiated_by", "collection_runs", ["initiated_by"])
    op.create_index("ix_collection_runs_status", "collection_runs", ["status"])

    # ------------------------------------------------------------------
    # 13. collection_tasks
    # ------------------------------------------------------------------
    op.create_table(
        "collection_tasks",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("collection_run_id", sa.UUID(), sa.ForeignKey("collection_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("arena", sa.String(50), nullable=False),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("celery_task_id", sa.String(200), nullable=True),
        sa.Column("credential_id", sa.UUID(), sa.ForeignKey("api_credentials.id", ondelete="SET NULL"), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("records_collected", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("rate_limit_state", JSONB, nullable=True, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_collection_tasks_collection_run_id", "collection_tasks", ["collection_run_id"])
    op.create_index("ix_collection_tasks_status", "collection_tasks", ["status"])

    # ------------------------------------------------------------------
    # 14. credit_transactions
    # ------------------------------------------------------------------
    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("collection_run_id", sa.UUID(), sa.ForeignKey("collection_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("arena", sa.String(50), nullable=False),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("tier", sa.String(10), nullable=False),
        sa.Column("credits_consumed", sa.Integer, nullable=False),
        sa.Column("transaction_type", sa.String(50), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("description", sa.Text, nullable=True),
    )
    op.create_index("ix_credit_transactions_user_id", "credit_transactions", ["user_id"])
    op.create_index("ix_credit_transactions_collection_run_id", "credit_transactions", ["collection_run_id"])
    op.create_index("ix_credit_transactions_created_at", "credit_transactions", ["created_at"])

    # ------------------------------------------------------------------
    # 15. content_records — partitioned parent table
    #
    # This table MUST be created with raw DDL because Alembic's
    # create_table() helper does not support PARTITION BY.  The
    # PostgreSQL composite primary key must include the partition key
    # (published_at).
    # ------------------------------------------------------------------
    _exec("""
        CREATE TABLE content_records (
            id                      UUID        NOT NULL DEFAULT gen_random_uuid(),
            published_at            TIMESTAMPTZ,
            platform                VARCHAR(50) NOT NULL,
            arena                   VARCHAR(50) NOT NULL,
            platform_id             VARCHAR(500),
            content_type            VARCHAR(50) NOT NULL,
            url                     VARCHAR(2000),
            text_content            TEXT,
            title                   TEXT,
            language                VARCHAR(10),
            collected_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            author_platform_id      VARCHAR(500),
            author_display_name     VARCHAR(500),
            author_id               UUID        REFERENCES actors(id) ON DELETE SET NULL,
            pseudonymized_author_id VARCHAR(64),
            views_count             BIGINT,
            likes_count             BIGINT,
            shares_count            BIGINT,
            comments_count          BIGINT,
            engagement_score        FLOAT,
            collection_run_id       UUID        REFERENCES collection_runs(id) ON DELETE SET NULL,
            query_design_id         UUID        REFERENCES query_designs(id) ON DELETE SET NULL,
            search_terms_matched    TEXT[],
            collection_tier         VARCHAR(10) NOT NULL,
            raw_metadata            JSONB       DEFAULT '{}',
            media_urls              TEXT[],
            content_hash            VARCHAR(64),
            PRIMARY KEY (id, published_at),
            CONSTRAINT uq_content_platform_id_published
                UNIQUE (platform, platform_id, published_at)
        ) PARTITION BY RANGE (published_at)
    """)

    # ------------------------------------------------------------------
    # content_records indexes (created on parent; inherited by partitions)
    # ------------------------------------------------------------------
    _exec("CREATE INDEX idx_content_platform ON content_records (platform)")
    _exec("CREATE INDEX idx_content_arena    ON content_records (arena)")
    _exec("CREATE INDEX idx_content_published ON content_records (published_at)")
    _exec("CREATE INDEX idx_content_query    ON content_records (query_design_id)")
    _exec("CREATE INDEX idx_content_hash     ON content_records (content_hash)")
    _exec("CREATE INDEX idx_content_author   ON content_records (author_id)")

    # GIN indexes for array and JSONB columns
    _exec(
        "CREATE INDEX idx_content_terms    ON content_records "
        "USING GIN (search_terms_matched)"
    )
    _exec(
        "CREATE INDEX idx_content_metadata ON content_records "
        "USING GIN (raw_metadata)"
    )

    # Full-text search using Danish dictionary
    _exec(
        "CREATE INDEX idx_content_fulltext ON content_records "
        "USING GIN (to_tsvector('danish', "
        "coalesce(text_content, '') || ' ' || coalesce(title, '')))"
    )

    # ------------------------------------------------------------------
    # 15b. Initial monthly partitions
    #
    # We create partitions for the current month (February 2026) and
    # the following two months (March 2026, April 2026).
    # A separate maintenance job (or future migration) creates additional
    # partitions on a rolling basis.  The default partition catches any
    # rows with published_at values outside the explicit ranges.
    # ------------------------------------------------------------------

    # February 2026
    _exec("""
        CREATE TABLE content_records_2026_02
        PARTITION OF content_records
        FOR VALUES FROM ('2026-02-01') TO ('2026-03-01')
    """)

    # March 2026
    _exec("""
        CREATE TABLE content_records_2026_03
        PARTITION OF content_records
        FOR VALUES FROM ('2026-03-01') TO ('2026-04-01')
    """)

    # April 2026
    _exec("""
        CREATE TABLE content_records_2026_04
        PARTITION OF content_records
        FOR VALUES FROM ('2026-04-01') TO ('2026-05-01')
    """)

    # Default partition: catches NULL published_at and out-of-range dates.
    # Rows landing here signal a data quality issue and should be
    # investigated — the partition exists so no insert fails silently.
    _exec("""
        CREATE TABLE content_records_default
        PARTITION OF content_records DEFAULT
    """)


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    """Drop all tables created by this migration in reverse dependency order."""

    # Drop content_records partitions then parent table.
    # Each partition must be dropped before the parent can be dropped.
    _exec("DROP TABLE IF EXISTS content_records_default")
    _exec("DROP TABLE IF EXISTS content_records_2026_04")
    _exec("DROP TABLE IF EXISTS content_records_2026_03")
    _exec("DROP TABLE IF EXISTS content_records_2026_02")
    _exec("DROP TABLE IF EXISTS content_records")

    # Drop remaining tables in reverse FK dependency order.
    op.drop_table("credit_transactions")
    op.drop_table("collection_tasks")
    op.drop_table("collection_runs")
    op.drop_table("actor_list_members")
    op.drop_table("actor_lists")
    op.drop_table("search_terms")
    op.drop_table("query_designs")
    op.drop_table("actor_platform_presences")
    op.drop_table("actor_aliases")
    op.drop_table("actors")
    op.drop_table("api_credentials")
    op.drop_table("refresh_tokens")
    op.drop_table("credit_allocations")
    op.drop_table("users")
