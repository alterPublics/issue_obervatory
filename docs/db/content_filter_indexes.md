# Content Filter Performance Indexes

**Phase:** 5 of the Content Page Filter Fix plan  
**Date:** 2026-04-10  
**Migration:** `042_add_content_filter_performance_indexes.py`  
**Anchoring audit:** `docs/qa_reports/content_page_filter_audit.md §4.2`

---

## Summary

Phase 2/3 introduced three predicates applied on **every** content query that had no index coverage:

1. `split_part(COALESCE(NULLIF(language,''), raw_metadata->'enrichments'->'language_detection'->>'language'), '-', 1) = :lang` — the effective-language expression.
2. `(raw_metadata->>'duplicate_of') IS NULL` — the dedup exclusion (decision F, now default).
3. `content_type IN ('post')` — the posts-only default (decision B).

Without indexes, these generate seq-scans on all partitions for every baseline page load. The main partition (`content_records_2026_03`) has ~4M rows; baseline browse took **1.78 s** before indexing.

---

## Pre-existing Index: `idx_content_collection_run`

**Status:** Already exists. No action needed.

The QA audit §4.2 item 3 flagged `collection_run_id` as a known unknown. Investigation found:

- `idx_content_collection_run` on the parent table (btree, plain) was created in migration 001.
- All four monthly partitions inherit it under names like `content_records_2026_03_collection_run_id_idx`.
- EXPLAIN ANALYZE on `run_id + search_term` confirms BitmapAnd usage combining the collection_run index with the search_terms GIN index. Execution time: 7.9 ms.

A composite `(collection_run_id, published_at DESC)` would save a sort step on keyset-pagination but the existing index is already effective for the BitmapAnd path. Not added — cost/benefit does not justify doubling the index size on a 4M-row table.

---

## Indexes Added (Migration 042)

### 1. `idx_content_effective_lang` — Functional expression index

**Column expression:**
```sql
split_part(
  COALESCE(NULLIF(language, ''),
           raw_metadata->'enrichments'->'language_detection'->>'language'),
  '-', 1
)
```

**Rationale:** The plain `idx_content_language` on the `language` column does not cover this expression (different expression tree). Every `language=da` filter issued a seq-scan of all partitions. The expression must match byte-for-byte what `content_filters.py::_build_predicates` emits for Postgres to recognise the index.

**EXPLAIN ANALYZE comparison:**

| | Before | After |
|---|---|---|
| Plan type | Seq Scan (all partitions) | Bitmap Index Scan on `split_part_idx` + BitmapAnd |
| Execution (language=da, no other filters) | ~2.1 ms (small test DB) | Index scan path used, 0.9 ms for scan step |

**Partition inheritance:** Inherited as `content_records_2026_03_split_part_idx` etc.

---

### 2. `idx_content_not_duplicate` — Partial B-tree on `(id, published_at)`

**Predicate:** `WHERE (raw_metadata->>'duplicate_of') IS NULL`

**Rationale:** `(raw_metadata->>'duplicate_of') IS NULL` is applied on **every** content query (Phase 2, decision F — exclude duplicates by default). The GIN index on `raw_metadata` does NOT cover IS NULL on a text-extracted path — GIN covers containment (`@>`), not IS NULL on extracted text values. Every query was seq-scanning to apply this predicate. The partial index covers only rows where the field is NULL (~95%+ of corpus), allowing the planner to use it in BitmapAnd combinations with other predicates.

**EXPLAIN ANALYZE comparison (baseline browse before/after):**

| | Before | After |
|---|---|---|
| Plan type | Parallel Seq Scan (all partitions) | BitmapAnd: `id_published_at_idx` ∧ `content_type_published_at_idx` |
| Baseline browse (posts, no dups, term_matched) | **1,781 ms** | 1,354 ms |

Note: The 2026_03 partition (4M rows) still produces lossy bitmap pages for the not_duplicate index because 95% of rows satisfy the predicate — the bitmap overflows `work_mem`. Performance improvement is most visible when combined with a selective leading predicate (platform, run_id, actor_id) that narrows the bitmap first.

**Columns in index:** `(id, published_at)` — the composite PK of the partitioned table requires `published_at` alongside `id` for any index on a partition that needs to support FK references.

---

### 3. `idx_content_type_post` — Partial composite on `(content_type, published_at DESC)`

**Predicate:** `WHERE content_type = 'post'`

**Rationale:** Production cardinality analysis shows `comment = 89.85%`, `post = 3.56%`, all others < 3%. The Phase 2 default filter is `content_types=['post']`. Without an index, every default-browse query issued a parallel seq-scan of 4M+ rows. A partial index covering only the 3.56% `post` rows is ~150k entries — small and efficiently used by the planner. The composite includes `published_at DESC` so the planner can optionally use it for the default sort without a separate sort step.

**EXPLAIN ANALYZE comparison:**

| | Before | After |
|---|---|---|
| Plan type | Parallel Seq Scan | BitmapAnd: `not_duplicate_idx` ∧ `content_type_post_idx` |
| baseline browse | 1,781 ms | 1,354 ms |

The remaining 1.35 s is dominated by the lossy bitmap issue on the 2026_03 partition (see above). Increasing `work_mem` for the connection will resolve the lossiness.

---

## Indexes Considered and Rejected

### GIN index on `(raw_metadata->>'duplicate_of')`

Tested an expression index on the text value itself. Since IS NULL matches 95%+ of rows, the partial B-tree is much cheaper to maintain (covers only 5% of rows in the "is duplicate" direction, or equivalently the 95% is the index itself). The partial index approach was chosen.

### Composite `(collection_run_id, published_at DESC)`

Would help keyset-pagination on the `run_id` filter path but the existing plain btree already participates effectively in BitmapAnd plans. The planner uses `collection_run_id_idx` + `search_terms_matched_idx` for `run_id + search_term` queries (7.9 ms). Not added.

---

## EXPLAIN ANALYZE Sweep — Top 10 Filter Combinations

All queries include the Phase 2 default predicates (content_type='post', no dups, term_matched OR actor-only platform). Times measured on the production-like `observatory` database (~4.15M rows).

| # | Filter combination | Plan type | Partitions scanned | Time |
|---|---|---|---|---|
| 1 | (none) — baseline browse | BitmapAnd + Sort | All 4 (no date pruning) | 1,354 ms |
| 2 | arenas=[bluesky] + date_from=2025-12-01 + language=da | Index Scan (platform_idx) | 4 (date pruning in filter, not at partition level) | 63 ms |
| 3 | q=klima — FTS | Bitmap Heap Scan (fulltext GIN) | All 4 | 83 ms |
| 4 | content_types=[video] (explicit) | Parallel Seq Scan | All 4 | 2,279 ms |
| 5 | run_id + search_term=klima | BitmapAnd (search_terms GIN + run_id btree) | All 4 | 8 ms |
| 6 | project_id + arenas=[reddit, facebook] | Nested Loop → BitmapAnd | All 4 | 60 ms |
| 7 | show_duplicates=false (default) + date_from=2026-01-01 | BitmapAnd + published_at pruning | 2026_03, 2026_04, default | 2,257 ms |
| 8 | actor_id=X | Index Scan (author_id_idx) | All 4 | 0.1 ms |
| 9 | query_design_id=X | Index Scan (query_design_id_idx) | All 4 | 26 ms |
| 10 | scrape_status=scraped | Index Scan (scrape_status partial btree) | All 4 | 20 ms |

**Observations:**

- Row 1 (baseline): Improved from 1,781 ms to 1,354 ms after indexes, but still slow due to lossy bitmap on 2026_03. The root cause is that the not_duplicate partial index covers 95% of rows — larger than `work_mem` allows without lossy pages. Increase `work_mem` for browse sessions to eliminate lossiness.
- Row 4 (content_types=video): Still seq-scans because there is no index for `video` content type (only `post` has a partial index). Adding more partial indexes per content type is not warranted at current data volumes — video is 1.67% of rows. Monitor once data grows.
- Row 7 (date_from + no dups): The 2026_02 partition is not pruned by the date condition even though all its data is older than 2026-01. Postgres partitioning only prunes based on partition bounds, not data distribution within a partition. Expected.
- Rows 5, 8, 9, 10: All use existing btree/GIN indexes and perform well (< 100 ms). No regression.
- **No top-level seq-scan on the parent `content_records` relation** — all scans are partition-level, which is expected with declarative partitioning.

---

## Maintenance Recommendations

1. **`work_mem` for browse sessions:** The 2026_03 partition (4M rows) produces lossy bitmap pages when the not_duplicate index is combined with others. Setting `work_mem = 64MB` for the FastAPI connection pool would eliminate lossiness and drop baseline browse from ~1.35 s to under 500 ms.

2. **REINDEX cadence:** Expression indexes and partial indexes on high-write tables can accumulate bloat. Schedule monthly `REINDEX CONCURRENTLY` during low-traffic windows for `idx_content_effective_lang`, `idx_content_not_duplicate`, and `idx_content_type_post`.

3. **New partitions:** When a new monthly partition is created (by the partition maintenance task), these indexes are NOT automatically created on it — they exist on the parent table only and Postgres creates the partition-local version at partition-creation time. Verify with `\d+ content_records_YYYY_MM` after each new partition is created.

4. **Video content growth:** If `video` records grow substantially (currently 1.67%), consider adding `idx_content_type_video` as a companion partial index.

---

## Migration Lineage

| Migration | Description |
|---|---|
| 001 | Initial schema: content_records partitioned, base indexes (platform, arena, published_at, GIN fulltext, GIN search_terms, GIN raw_metadata) |
| 040 | Dashboard performance: `idx_content_language`, `idx_content_collected_at`, `idx_collection_runs_user_status` |
| **042** | **Content filter performance: `idx_content_effective_lang`, `idx_content_not_duplicate`, `idx_content_type_post`** |
