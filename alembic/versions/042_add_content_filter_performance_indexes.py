"""Add performance indexes for content-page filter queries.

Phase 5 of the content-page filter fix plan. Addresses seq-scans identified
by the QA audit (docs/qa_reports/content_page_filter_audit.md §4.2) and the
EXPLAIN ANALYZE sweep conducted during Phase 5 execution.

Indexes added
=============

1. idx_content_effective_lang — functional expression index on the language
   fallback expression used by every language filter:

     split_part(COALESCE(NULLIF(language,''),
       raw_metadata->'enrichments'->'language_detection'->>'language'), '-', 1)

   The existing idx_content_language (plain btree on the ``language`` column)
   does NOT cover this expression. Every language= query seq-scanned all
   partitions (~2 ms/partition baseline, worse on large corpora). This index
   makes the expression selectable by the planner for equality predicates.

   The expression is reproduced verbatim from the sa_clause in
   ``core/queries/content_filters.py::_build_predicates`` so Postgres can
   recognise the match. Any byte difference breaks the correspondence.

2. idx_content_not_duplicate — partial B-tree index on ``(id, published_at)``
   covering only rows where ``raw_metadata->>'duplicate_of' IS NULL``.

   Phase 2 applies this predicate on EVERY content query (decision F —
   duplicate exclusion by default). The GIN index on ``raw_metadata`` does
   NOT cover IS NULL on a text-extracted JSONB path; every query issues a
   seq-scan post-filter. Since ~95%+ of rows are not duplicates, a partial
   index is small and can be combined by the planner via BitmapAnd with other
   bitmap index scans. The (id, published_at) columns are included because
   the composite PK on partitioned tables requires published_at alongside id.

3. idx_content_type_post — partial B-tree index on
   ``(content_type, published_at DESC)`` covering only rows where
   ``content_type = 'post'``.

   Context: content_type cardinality in production is heavily skewed —
   'comment' = 89.85%, 'post' = 3.56%, all others < 3%. The Phase 2 default
   is posts-only (content_types=['post']). Without an index, every default-
   browse query issues a parallel seq-scan of 4M+ rows taking ~1.8 s. A
   partial index covering only the 3.56% 'post' rows is ~150k entries; the
   planner can use it for bitmap heap scans in combination with other
   predicates (term_matched, duplicate_of, ownership subquery). The composite
   includes published_at DESC so the planner can also use it for the default
   sort without a separate sort step.

Indexes NOT added (and reasoning)
==================================

- Composite (collection_run_id, published_at DESC): the existing plain btree
  ``idx_content_collection_run`` already exists on the parent and inherits to
  all partitions. Adding the composite would improve keyset-pagination on the
  run_id path slightly but the planner already combines it via BitmapAnd with
  other indexes. Cost/benefit does not justify doubling the index size on a
  4M-row table.

- Expression index for duplicate_of using GIN: tried an expression index on
  (raw_metadata->>'duplicate_of') but since IS NULL matches 95%+ of rows the
  partial B-tree index on id/published_at is much cheaper to maintain and
  equally effective.

Production note on CONCURRENTLY
================================

PostgreSQL does NOT support CREATE INDEX CONCURRENTLY on the parent of a
partitioned table (it would need to be applied partition-by-partition). We
use the same approach as migration 040: plain ``CREATE INDEX IF NOT EXISTS``
which acquires a SHARE lock per partition sequentially. On the 4M-row
production DB this will run for several minutes. Schedule during low-traffic
hours or apply manually per partition if zero-downtime is required.

Revision ID: 042
Revises: 041
"""

from __future__ import annotations

from alembic import op

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Effective-language functional index.
    #    Expression must match EXACTLY what content_filters.py emits for the
    #    language predicate — any byte difference prevents index usage.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_effective_lang "
        "ON content_records ("
        "  (split_part("
        "    COALESCE(NULLIF(language, ''), "
        "             raw_metadata->'enrichments'->'language_detection'->>'language'"
        "    ), '-', 1"
        "  ))"
        ")"
    )

    # 2. Partial B-tree index for duplicate-exclusion predicate.
    #    (id, published_at) columns are needed because the partitioned PK
    #    requires published_at alongside id for uniqueness referencing.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_not_duplicate "
        "ON content_records (id, published_at) "
        "WHERE (raw_metadata->>'duplicate_of') IS NULL"
    )

    # 3. Partial composite index for posts-only default browse.
    #    post = 3.56% of rows. Index covers (content_type, published_at DESC)
    #    within the WHERE content_type = 'post' partial predicate so the planner
    #    can use it for both the equality filter and the default DESC sort.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_type_post "
        "ON content_records (content_type, published_at DESC) "
        "WHERE content_type = 'post'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_content_type_post")
    op.execute("DROP INDEX IF EXISTS idx_content_not_duplicate")
    op.execute("DROP INDEX IF EXISTS idx_content_effective_lang")
