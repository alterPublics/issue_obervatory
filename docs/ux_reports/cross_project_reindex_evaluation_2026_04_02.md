# UX Evaluation: Cross-Project Content Reindexing (Facebook/Instagram)
Date: 2026-04-02
Arenas evaluated: Facebook, Instagram (Bright Data, medium tier)
Tiers evaluated: medium
Scenarios run: Cross-project reuse of actor-based Bright Data collections

## Summary

A researcher has project "valg2026" with existing Facebook/Instagram data and creates a new project "remigration" with the same actor source lists. They run collection for the same date range and expect existing data to appear in the new project without re-collecting (avoiding Bright Data API costs).

This evaluation examines whether the new reindexing mechanism works correctly from the researcher's perspective and whether the experience is comprehensible.

---

## Passed

### 1. Analysis layer correctly includes linked records (when filtering by run_id)

The `_filters.py` module (lines 86-99) correctly generates an OR clause that includes both directly collected records AND records linked via `content_record_links`:

```sql
(collection_run_id = :run_id
 OR EXISTS (
   SELECT 1 FROM content_record_links crl
   WHERE crl.collection_run_id = :run_id
   AND crl.content_record_id = id
   AND crl.content_record_published_at = published_at))
```

This means all analysis dashboard endpoints (volume over time, top actors, top terms, engagement distributions, network graphs) will correctly show the linked records when the researcher views analysis for the "remigration" run. The EXISTS clause uses an indexed lookup (`idx_content_record_links_run_record`), which is performant.

### 2. Boundary day fix is sound

Both Facebook and Instagram tasks now use `latest > user_end` (strictly greater than) for the coverage skip check (Facebook line 419, Instagram line 402). Previously `>=` would skip the last day of existing coverage even if that day was only partially collected. The fix ensures the boundary day is always re-collected, which is the correct behavior -- a researcher collecting up to "2026-03-31" should get all of March 31's content, not just whatever was captured in a prior partial run.

### 3. Deduplication via ON CONFLICT prevents double-linking

The `reindex_existing_records` function uses `ON CONFLICT (content_record_id, content_record_published_at, collection_run_id) DO NOTHING`, preventing duplicate link rows if the same collection is run multiple times.

### 4. Instagram author matching accounts for platform ID mismatch

Instagram stores a numeric `owner_id` as `author_platform_id`, which does not match the profile URL used in actor lists. The Instagram task correctly extracts usernames from profile URLs and passes them as `author_names` rather than `actor_ids`, matching against `author_display_name`. This is a thoughtful handling of a platform-specific quirk.

### 5. No re-fetching from Bright Data

The coverage check runs per-actor before collection. When an actor is already fully covered, the task skips the Bright Data API call entirely. The reindex step then creates link rows for the existing records. This saves real money for the researcher.

---

## Blockers

### B1. Content browser does NOT show linked records [frontend] [core]

**This is the most significant problem with this feature.**

The content browser query (`_build_paginated_content_stmt` in `content.py`, line 480) uses a simple equality filter:

```python
stmt = stmt.where(ucr.collection_run_id == run_id)
```

This does NOT join or check `content_record_links`. When the researcher clicks "Browse content" for the "remigration" run, they will see **zero records** for Facebook and Instagram (assuming all actors were covered by prior collection and no new records were inserted). The reindexed records are invisible in the content browser.

**Researcher impact:** The researcher launches collection for "remigration", sees the task complete with "0 records" in the status page, clicks "Browse content", and finds nothing. They have no way to know that data exists and is linked. They will conclude the collection failed or their query design is wrong.

**Scope of the gap:** The following content browser code paths all use `collection_run_id == run_id` without consulting `content_record_links`:

- `_build_content_stmt()` (line 224) -- used by the full-page browser and sync export
- `_build_paginated_content_stmt()` (line 480) -- used by the HTMX pagination rows
- Search terms dropdown endpoint (line 1443) -- `WHERE cr.collection_run_id = :run_id`
- Export count helper (line 869) -- `collection_run_id == run_id`
- Sync export (line 1701) -- via `_build_content_stmt`

### B2. Collection detail page shows "0 records" with no explanation [frontend]

The collection detail page (`pages.py`, lines 1080-1090) calculates `platform_counts` by querying `content_records WHERE collection_run_id = run_id`. It does not include linked records. The "Records by Platform" table on the collection detail page will show nothing or very low numbers.

The run summary card (`_fragments/run_summary.html`, line 103) displays `run.records_collected` which comes from `CollectionRun.records_collected` (the ORM field). This is set by `_update_task_status` in the task, which only stores `total_inserted` -- newly collected records, not linked records. The researcher sees:

- Records: **0**
- Credits used: **0**

There is no UI indication that records were linked from another project. The `linked` count is logged to the server log but never surfaces to the researcher.

---

## Friction Points

### F1. The researcher has no mental model for "reindexing" [frontend] [research]

The feature is completely invisible. There is no:
- Pre-collection message explaining "We found existing data from project 'valg2026' that matches your actors and date range. This data will be available in your new project without re-collection."
- Post-collection summary showing "0 new records collected, 1,847 existing records linked from 2 prior runs."
- Any concept of "linked" or "shared" records in the UI vocabulary.

A researcher who does not know about this feature will experience it as collection silently producing zero results. A researcher who was told about it has no way to verify it worked.

### F2. Records count discrepancy between analysis and content browser

If the analysis dashboard (which uses `_filters.py` and DOES include linked records) shows data for a run, but the content browser (which does NOT include linked records) shows zero records for the same run, the researcher will see contradictory information. The analysis dashboard might show 1,847 records with volume-over-time charts, but clicking "Browse content" shows an empty table. This fundamentally undermines data trust.

### F3. Export from content browser will miss linked records [frontend]

Both sync and async export paths go through `_build_content_stmt`, which does not include linked records. A researcher who sees analysis results and then tries to export the underlying data will get an empty or incomplete file. This is a data completeness failure that could affect published research.

### F4. No filter/indicator for "linked vs. collected" records

Even once the content browser is fixed to show linked records, researchers will need to distinguish between records their run actually collected fresh (and thus can be attributed to their specific query context) and records that were collected by a prior run and linked retroactively. The `link_type` field exists on `ContentRecordLink` but is not exposed anywhere in the UI.

### F5. `reindex_existing_records` does not filter out the current run's own records

The SQL in `reindex_existing_records` (line 1749-1757) selects from `content_records cr WHERE {platform + date + actor clauses}` and inserts into `content_record_links` with `collection_run_id = :run_id`. But there is no clause excluding `cr.collection_run_id != :run_id`. This means if the current run DID collect some new records (e.g., on boundary days), those records will also get link rows pointing to the same run. While the `ON CONFLICT DO NOTHING` prevents real harm (the analysis query uses `OR`, so directly collected records are already included), it creates unnecessary rows in `content_record_links` and inflates the `linked` count logged to server logs, making debugging harder.

### F6. Instagram username matching is case-sensitive and fragile

The Instagram task extracts usernames from normalized profile URLs (`url.rstrip("/").split("/")[-1]`) and matches against `author_display_name` via `= ANY(:author_names)`. PostgreSQL string comparison is case-sensitive by default. If the Bright Data collector stores display names with different casing than the profile URL slug (e.g., "DRNyheder" vs "drnyheder"), records will not be linked. The researcher would see partial linking with no explanation for why some actors' data appears and others' does not.

---

## Data Quality Findings

### DQ1. Linked records retain original `query_design_id` on the content record itself

Content records have a `query_design_id` column that was set when the record was originally collected for "valg2026". The `ContentRecordLink` table has its own `query_design_id` field, but analysis queries in `_filters.py` that filter by `query_design_id` (lines 74-84) check `content_records.query_design_id`, not the link table. This means:

- If the researcher filters analysis by the "remigration" query design ID, linked records will NOT appear (they belong to the "valg2026" query design).
- If they filter by run_id, the linked records DO appear (via the EXISTS clause).

This creates an inconsistency: the same data is visible or invisible depending on which filter the researcher uses. For project-level analysis (which typically queries by query design), the linked records are effectively missing.

### DQ2. `term_matched` filter WILL exclude Facebook/Instagram records -- confirmed

This is a compounding problem that makes the reindexing feature functionally invisible even after fixing the content browser.

**Verified chain of evidence:**
1. Facebook `collect_by_actors` calls `make_batch_sink(collection_run_id, query_design_id)` with no `terms` parameter (facebook/tasks.py line 287). Same for Instagram (instagram/tasks.py line 276).
2. `persist_collected_records` (in `_task_helpers.py`) receives `terms=None`, so the term-matching backfill loop does nothing for these records.
3. Neither the Facebook nor Instagram collector sets `search_terms_matched` on normalized records (confirmed: no matches for `search_terms_matched` or `term_matched` in either collector).
4. The default `record.setdefault("term_matched", len(existing_terms) > 0)` sets `term_matched = False` because `existing_terms` is empty.
5. The analysis `_filters.py` always appends `term_matched = TRUE` (line 142).
6. The content browser defaults to `show_all=False` which adds `.where(ucr.term_matched.is_(True))`.

**Result:** ALL Facebook and Instagram records -- both directly collected AND linked via reindexing -- are filtered out by default in both the analysis dashboard and the content browser. They are only visible if the researcher explicitly sets `show_all=True`, which is not the default and is not prominently exposed.

This means the reindexing feature is doubly invisible: the content browser does not query `content_record_links`, AND even if it did, the `term_matched=TRUE` filter would exclude the records anyway.

**Note:** This is likely a pre-existing issue with Facebook/Instagram records in general, not specific to the reindexing change. But it means the reindexing feature cannot be evaluated in isolation -- fixing the content browser to include linked records will not help if all the records are filtered out by `term_matched`.

---

## Documentation Gaps

### G1. No documentation for the cross-project reindexing feature

There is no mention of this capability in:
- `docs/guides/what_data_is_collected.md`
- Any user-facing guide or help text
- The collection launcher or detail page

A researcher who discovers that running a duplicate collection costs zero credits will have no way to understand why or to verify their data.

### G2. No documentation explaining coverage checks and deduplication behavior

The per-actor coverage check (`get_latest_actor_coverage_date`) and the skip logic are not documented anywhere the researcher can find. The only output is a server log entry. A researcher who expects 20 actors to be collected but sees only 3 being processed (the others having been skipped due to coverage) has no visibility into why.

---

## Recommendations

Priority 1 (Blockers -- must fix before the feature is usable):

1. **[frontend] [core] Update the content browser query to include linked records.** The `_build_content_stmt` and `_build_paginated_content_stmt` functions must add an OR clause (or UNION) for records in `content_record_links` when filtering by `run_id`. Match the pattern already used in `_filters.py` (the EXISTS clause). This should also apply to the export path and search-terms-dropdown endpoint.

2. **[frontend] Update the collection detail page to show linked record counts.** The `platform_counts` query in `pages.py` (line 1081) must include records from `content_record_links`. The run summary card should distinguish between "X new records collected" and "Y existing records linked", or show a combined total with a tooltip.

3. **[core] Store `linked` count on the task or run.** The `records_collected` field on `CollectionTask` only captures newly inserted records. Either add a `records_linked` column, or update `records_collected` to include linked records, so the collection detail page can show accurate totals.

Priority 2 (Friction -- should fix for researcher comprehension):

4. **[frontend] Add a post-collection banner for reindexed data.** When a collection run completes with linked records, show a clear message: "This collection linked N existing records from prior runs. No additional API costs were incurred. The linked records are included in your analysis and content browser." This could be an SSE event similar to the existing `discovery_summary` panel.

5. **[core] Exclude current run records from reindex.** Add `AND cr.collection_run_id != CAST(:run_id AS uuid)` to the `reindex_existing_records` SELECT to avoid creating self-referential link rows.

6. **[core] Use case-insensitive matching for Instagram author names.** Change `cr.author_display_name = ANY(:author_names)` to `LOWER(cr.author_display_name) = ANY(:author_names_lower)` and lower-case the username list before passing it.

Priority 3 (Data trust -- important for publication-ready analysis):

7. **[core] Fix `query_design_id` filtering for linked records.** The `_filters.py` `query_design_id` filter should also check `content_record_links.query_design_id` with an OR/EXISTS clause, so that project-level analysis includes linked records.

8. **[frontend] Add a "source" indicator to content browser rows.** Show whether each record was directly collected or linked from another run. This helps researchers understand data provenance when citing results.

9. **[research] Document the cross-project reindexing capability.** Add a section to `docs/guides/what_data_is_collected.md` explaining that actor-based arenas (Facebook, Instagram) automatically reuse previously collected data across projects. Explain what this means for data provenance and how to verify it.

10. **[core] Fix `term_matched` for Facebook/Instagram actor-only collection (PREREQUISITE for this feature).** Facebook and Instagram `collect_by_actors` tasks do not pass `terms` to `make_batch_sink`, so all records have `term_matched=FALSE` and are invisible in both the content browser and analysis dashboard by default. Either: (a) pass the query design's search terms to `make_batch_sink` so text-matching backfill runs, or (b) set `term_matched=TRUE` for actor-only arenas where term matching is not applicable (the record was collected because the actor was in the list, which is a valid match criterion). Without this fix, the entire reindexing feature is moot -- even correctly linked records will be filtered out.
