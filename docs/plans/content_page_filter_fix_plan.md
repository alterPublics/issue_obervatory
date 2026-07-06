# Content Page Filter Fix — Implementation Plan

**Date:** 2026-04-10
**Anchoring reports:**
- `docs/ux_reports/content_page_filter_review.md` (researcher-perspective UX evaluation)
- `docs/qa_reports/content_page_filter_audit.md` (code-level QA audit)

Both reports converged independently on the same root causes. This plan turns their findings into sequenced, actionable work.

## Decisions Made (2026-04-10)

All seven decisions in §3 have been answered:

- **A (sampling):** **Rename to "Recent Content".** Document the `published_at DESC` sort honestly. Do NOT implement random or stratified sampling.
- **B (content type default):** **Posts-only default** with a visible, clearable "Show comments" filter. The default must be surfaced as an active filter pill so users can see and clear it.
- **C (auto-select project):** **Keep, push URL.** Auto-select latest project but write `project_id` into URL via `hx-push-url` so the filter is visible, bookmarkable, and resettable.
- **D (collaborator scoping):** **Everywhere.** Collaborators see each other's content in browser, detail, dashboard count, AND export. Implement via single `OwnershipScope.owner_plus_collaborators`.
- **E (`_build_content_stmt` deletion):** **Delete.** Follows from D.
- **F (duplicate exclusion):** **Apply by default, add "Show duplicates" checkbox.** Parity with analysis by default; researchers can opt in to audit dedup.
- **G (analysis refactor scope):** **Yes — migrate all analysis callers.** Phase 1 is split into 1a (shared helper + content routes) and 1b (analysis layer migration, 18 call sites across 6 files).

---

## Executive Summary

- The content page maintains **four parallel filter implementations** (`_build_browse_stmt`, `_build_content_stmt`, `content_record_count`, `analysis/_filters.build_content_where`). They disagree on duplicate exclusion, ownership scoping, term-matched semantics, linked-record resolution, arena-plural support, and language fallback. All correctness bugs trace back to this divergence.
- The blocking P0 defects (`show_all` mutation, export filter drop, count/row mismatch, `content_types=["post"]` silent default, language default unclearable) cannot be safely point-fixed because any fix at one call site re-introduces a skew at another. **Convergence onto a single helper is a prerequisite for fixing the bugs, not an optimization.**
- **All seven decision gates have been answered** (see above). The plan can proceed end-to-end without further product input.
- **Phase 0 must land a regression harness** with real-DB fixtures (project collaborator, admin, stranger; multiple arenas incl. Facebook; deduped vs non-deduped corpus; linked runs) before any code move. The current test suite has **zero** coverage for filter SQL.
- **Success criterion (binding):** every visible sidebar control works in isolation AND every pairwise combination AND every triple with `(q, arenas, date, show_all, content_types)`, with `count == rendered rows` across initial load, HTMX reload, and export CSV. The page is honestly renamed to "Recent Content" and the sort is documented.

---

## 1. Architectural Decision — The Shared Filter Helper

### 1.1 Chosen approach

Create `src/issue_observatory/core/queries/content_filters.py` exposing:

- **`ContentFilterSpec`** — a frozen dataclass with every filter field that any of the browse/count/export/analysis paths can apply. Fields: `q`, `platforms: list[str]`, `arenas: list[str]`, `date_from`, `date_to`, `languages: list[str]`, `search_terms: list[str]`, `run_id`, `query_design_id`, `query_design_ids`, `mode`, `project_id`, `show_all`, `scrape_status`, `content_types`, `include_duplicates`, `include_linked`, `actor_ids`, plus scope fields `current_user` and `ownership_mode: Literal["owner_only","owner_plus_collaborators","admin"]`.
- **`OwnershipScope`** — single source of truth. Returns a SQLAlchemy `scalar_subquery()` and a raw-SQL predicate string from the identical underlying logic (`CollectionRun.initiated_by == user.id OR project.id IN collaborator_projects`).
- **`apply_content_filters(stmt: Select, spec: ContentFilterSpec) -> Select`** — SQLAlchemy-Core entry point for content routes.
- **`build_content_where_sql(spec, *, table_alias, params) -> str`** — raw-SQL entry point for `analysis/_filters.py`.
- **`build_count_stmt(spec)`** — same predicates, `select(func.count())`.
- **`build_browse_stmt(spec, *, cursor, sort, limit)`** — adds sort, keyset/offset, and joins for the template projection.

**Two invariants enforced by the module:**

1. All four call sites obtain their predicates from `apply_content_filters` or `build_content_where_sql` — no new `.where(...)` calls in `content.py` outside this helper.
2. The SQLAlchemy-Core and raw-SQL paths share a single internal `_build_predicates(spec) -> list[Predicate]` core that yields a neutral IR. A new predicate added once is visible to both.

### 1.2 Migration of the four existing call sites

| Call site | File:line | Migration action |
|---|---|---|
| `_build_browse_stmt` | `content.py:422-626` | Replace filter body (501-576) with `apply_content_filters(base_stmt, spec)`. Sort/pagination stays. Function shrinks to ~50 lines. |
| `_build_content_stmt` | `content.py:164-282` | **Delete.** `/content/export` switches to `build_browse_stmt(spec, cursor=None, sort=None, limit=limit)`. |
| `_count_matching` | `content.py:700-769` | Replace body with `build_count_stmt(spec)`. |
| `content_record_count` (dashboard) | `content.py:881-952` | Rewrite using `spec` with collaborator scoping per decision D. Query-design shortcut becomes an optimization hint inside `build_count_stmt`. |
| `analysis/_filters.build_content_filters` | `analysis/_filters.py:35-209` | **Deleted in Phase 1b.** All 18 callers migrate to `ContentFilterSpec` + `build_content_where_sql`. |

### 1.3 Alternatives considered

- **Alternative A — extend `analysis/_filters.py` in place.** Rejected. The analysis module uses raw SQL strings and f-string composition. Exposing a SQLAlchemy-Core-producing API from a module named `_filters` is misleading, and content routes are the dominant caller (5 endpoints vs 2 in analysis).
- **Alternative B — build a `ContentFilterBuilder` class on top of `_build_browse_stmt`, keep `analysis/_filters` untouched.** Rejected. Keeps the divergence between content browser and analysis (duplicate exclusion, linked-record EXISTS). Cross-page parity is a stated requirement.
- **Alternative C — pure raw-SQL string helper shared by everything.** Rejected. Content routes use SQLAlchemy ORM row mapping (`_orm_row_to_template_dict` expects attribute access on `UniversalContentRecord` instances). Converting to raw SQL is a bigger lift than unifying predicates.

### 1.4 Trade-offs

- Sharing with analysis costs one neutral IR layer (~150 lines) but buys full parity and kills four classes of drift at once.
- The SQLAlchemy/raw-SQL bridge is narrow and testable — one predicate-to-dialect function per side.
- **Analysis callers are fully migrated to `ContentFilterSpec` in Phase 1b** (decision G). They no longer construct their own predicate lists; they build a spec from their function arguments and call `build_content_where_sql(spec)`. This removes drift risk structurally and gives the codebase a single filter-spec type.

### 1.5 Analysis layer scope (Phase 1b)

The analysis layer has **18 call sites across 6 files** that currently use raw SQL f-string composition via `analysis/_filters.build_content_filters` or `build_content_where`:

| File | Call sites | Pattern |
|---|---|---|
| `analysis/descriptive.py` | 13 | Via private wrapper `_build_content_filters` at `:63-88`, which delegates to `build_content_where`. Call sites at `:154, 282, 480, 570, 636, 755, 972, 1667, 1735, 1808, 1981`. |
| `analysis/network.py` | 1 | `build_content_filters` at `:92` (private wrapper at `:77-94`). |
| `analysis/network_builder.py` | 2 | `build_content_where` at `:86, 270`. |
| `analysis/ner_extraction.py` | 1 | `build_content_where` at `:78`. |
| `analysis/keyword_extraction.py` | 1 | `build_content_where` at `:94`. |
| `analysis/__init__.py` | 1 re-export | `build_content_filters, build_content_where` at `:5, :30-31`. |

Every call site embeds the returned `WHERE` string into an f-string SQL query. Phase 1b replaces each call with:

```python
spec = ContentFilterSpec(
    query_design_id=query_design_id,
    run_id=run_id,
    arena=arena,
    platform=platform,
    date_from=date_from,
    date_to=date_to,
    search_terms=search_terms,
    language=language,
    include_linked=include_linked,
    ownership_mode="admin",  # analysis callers pre-scope their own run_ids
)
where = build_content_where_sql(spec, table_alias=prefix, params=params)
```

The analysis surface has fewer filter fields than the content route surface (no `q` full-text, no `scrape_status`, no `show_all`, no `mode`, no `content_types`). Those fields default to "not applied" in `ContentFilterSpec` so analysis callers can ignore them.

After migration, `analysis/_filters.py` is **deleted** and the re-exports from `analysis/__init__.py` are removed. Anything importing `from issue_observatory.analysis import build_content_filters` breaks at import time — intentional, so we catch every caller.

---

## 2. Sequenced Phases

### Phase 0 — Regression Harness (no code changes)

**Goal.** Lock in currently-intended behavior as a pinned contract so later fixes cannot silently regress orthogonal filters.

**Tasks.**

1. New fixture module `tests/integration/api/content/conftest.py` providing:
   - `seeded_corpus`: 200-400 records spanning `(arena ∈ {news, reddit, bluesky, facebook, instagram, youtube, x}) × (content_type ∈ {post, comment, search_result, video, article, tweet}) × (language ∈ {da, en, de, null, "da-DK"}) × (term_matched ∈ {true, false}) × (duplicate_of ∈ {set, null})`, tied to 2 collection runs and 2 query designs, across 2 users + 1 stranger.
   - `admin_user`, `owner_user`, `collaborator_user`, `stranger_user` fixtures with credentials.
   - `deduplicated_corpus` variant with `raw_metadata.duplicate_of` flags.
2. `test_filter_current_behavior.py` — parametric matrix over `(filters dict, expected_count, expected_first_row_id)` that asserts the **current** broken state, tagged `@pytest.mark.xfail(strict=False)`. Flipped to `strict=True` in Phase 2.
3. `test_filter_diff_harness.py` — runs any `ContentFilterSpec` through both old and new code paths, asserts row-ID sets identical. Takes a JSON matrix as input. Required by Phase 1 exit.
4. `test_count_vs_rows_invariant.py` — `total_count == len(rendered_rows)` for every filter combination. Core success criterion.
5. `test_export_equals_browse.py` — `/content/export?format=json` body has exact same record IDs as `/content/records?format=json` (concatenated across pages).

**Exit criteria.**
- CI green for all xfail-pinned tests.
- Diff harness parametric and extensible.
- Fixture spans all 16 sidebar controls (incl. not-yet-built filters with `@pytest.mark.skip`).

**Dependencies.** None. Runs in isolation.
**Effort.** L — fixture corpus is the long pole. 3-5 engineering days.
**Owners.** `qa-guardian` (lead), `db-data-engineer` (fixture SQL), `core-application-engineer` (fixture Python wiring).

---

### Phase 1a — Shared Filter Helper: Content Routes (gate: Phase 0 green)

**Goal.** Land `core/queries/content_filters.py` and route the **four content-route filter stacks** through it with **zero behavior change**. Pure refactor. Phase 2 is gated on 1a only.

**Tasks.**

1. Create `src/issue_observatory/core/queries/__init__.py` and `content_filters.py` with the types and functions from §1.1. **Reproduce current behavior predicate-for-predicate**, including the `effective_show_all` mutation, the `["post"]` default, and the ownership asymmetry.
2. Add `ContentFilterSpec.from_browse_route(...)` and `from_export_route(...)` constructors that encode current ownership asymmetry explicitly (ready to be resolved in Phase 2).
3. Replace bodies of `_build_browse_stmt` (501-576), `_build_content_stmt` (231-280), and `_count_matching` (743-768) with delegations.
4. Update `content_record_count` (909-951) to use `build_count_stmt`, preserving the query-design shortcut as an optimization hint.
5. Run the Phase 0 diff harness — every spec must produce identical row sets pre/post refactor.

**Exit criteria.**
- Diff harness green for 100% of spec matrix.
- All existing xfail tests still xfail with the same reason codes (no accidental fixes).
- `_build_content_stmt` still exists but is a 5-line delegator (not yet deleted).
- `content.py` shrinks by ≥ 200 lines.
- `grep "stmt = stmt.where" src/issue_observatory/api/routes/content.py` returns only the post-hoc `.in_()` calls at `:1094, :1358, :1804` (folded in Phase 2).

**Dependencies.** Phase 0.
**Effort.** L. 4-6 engineering days.
**Owners.** `core-application-engineer` (lead), `db-data-engineer` (SQL parity review), `qa-guardian` (diff harness).

---

### Phase 1b — Analysis Layer Migration (gate: Phase 1a green; parallel with Phase 2)

**Goal.** Migrate the **18 analysis call sites** off `analysis/_filters.py` to `ContentFilterSpec` + `build_content_where_sql`. Delete `analysis/_filters.py` entirely. Pure refactor with parity tests.

**Tasks.**

1. **Add analysis-specific predicate coverage to the shared helper.** Compare `analysis/_filters.py:35-209` against what the helper already supports. Missing fields that analysis needs but content routes do not: none — the analysis surface is a proper subset of the content surface. Confirm the `table_alias` parameter is carried through end-to-end in `build_content_where_sql(spec, *, table_alias, params)`.

2. **Add `include_linked` semantics to the spec.** Analysis `build_content_filters` has an `include_linked: bool = True` parameter that controls whether `content_record_links` is joined via `EXISTS`. Content routes implicitly include linked records when `run_id` or `query_design_ids` is set. Surface this as `ContentFilterSpec.include_linked: bool = True` and honor it in the helper predicates at `:83-90, :109-115, :188-207` of the current `_filters.py`.

3. **Migrate `analysis/descriptive.py`.** Delete the private `_build_content_filters` wrapper at `:63-88`. Replace every call site:
   - `:154` — `get_overview_statistics`
   - `:282` — `get_content_volume_by_platform`
   - `:480` — `get_top_actors`
   - `:570` — `get_actor_activity_timeline`
   - `:636` — `get_cross_platform_overlap`
   - `:755` — `get_engagement_metrics`
   - `:972` — (identify based on Grep output)
   - `:1667, 1735, 1808, 1981` — timeline / distribution functions
   Each becomes:
   ```python
   spec = ContentFilterSpec(
       query_design_id=query_design_id, run_id=run_id, ...,
       ownership_mode="admin",
   )
   where = build_content_where_sql(spec, table_alias="", params=params)
   ```

4. **Migrate `analysis/network.py`.** Delete the private wrapper at `:77-94`. Replace the single call site at `:92`.

5. **Migrate `analysis/network_builder.py`.** Replace the two call sites at `:86, :270`. Both use a table alias (typical pattern `a.` for the outer join) — verify the alias is passed through correctly.

6. **Migrate `analysis/ner_extraction.py`** at `:78` and **`analysis/keyword_extraction.py`** at `:94`. Both use `build_content_where`.

7. **Delete `src/issue_observatory/analysis/_filters.py` entirely.** Remove the re-exports from `analysis/__init__.py:5, :30-31`. Any remaining import fails at module load time — this is the intended hard-break so no caller is silently left behind.

8. **Parity diff test.** For each migrated function (descriptive stats, network, enrichments), add a parity test that runs the function pre- and post-migration against the Phase 0 fixture corpus and asserts the returned data structures are byte-identical. Tag as `test_analysis_migration_parity.py`.

9. **EXPLAIN ANALYZE on hot analysis queries.** The analysis layer currently benefits from the `include_linked` short-circuit optimization (skipping the EXISTS join for large aggregate queries). Verify the migrated versions maintain the same query plans — any regression in `get_overview_statistics` or `get_content_volume_by_platform` is a blocker.

**Exit criteria.**
- `analysis/_filters.py` deleted.
- `grep -rn "build_content_filters\|build_content_where" src/` returns only matches inside `core/queries/content_filters.py` and test files.
- `test_analysis_migration_parity.py` green for all 18 call sites.
- EXPLAIN ANALYZE confirms no query plan regressions on the 5 hot analysis queries.
- Import check: `python -c "from issue_observatory.analysis import build_content_filters"` raises `ImportError`.

**Dependencies.** Phase 1a.
**Effort.** M. 3-4 engineering days.
**Parallel with Phase 2.** Phase 1b and Phase 2 touch disjoint files (analysis layer vs content route), so they can run concurrently by different engineers.
**Owners.** `db-data-engineer` (lead — owns analysis layer per AGENTS.md), `core-application-engineer` (helper API stability), `qa-guardian` (parity tests).

---

### Phase 2 — P0 Correctness Fixes (gate: Phase 1a green)

**Goal.** Fix every P0 data-correctness bug from the reports.

**Tasks.**

1. **`show_all` mutation removed.** (QA §2.1, UX Blocker #3.)
   - Delete `effective_show_all = show_all or len(arenas_list) > 0` at `content.py:1063` and `:1324`.
   - Inside `apply_content_filters`, when `show_all is False`, apply predicate `(term_matched = TRUE) OR (platform IN :actor_only_platforms)`. Source `ACTOR_ONLY_PLATFORMS` from new constant in `src/issue_observatory/arenas/categories.py`, seeded from `workers/tasks.py:1507,1541`.
   - Regression test: `test_show_all_semantics.py::test_facebook_visible_with_show_all_false`.

2. **`/content/export` parity fix.** (QA §2.2, punch list items 12-13.)
   - Add missing query params to `export_content_sync` at `content.py:1686-1722`: `q`, `mode`, `project_id`, `show_all`, `scrape_status`, `content_types`.
   - Replace `_build_content_stmt(...)` call at `:1789-1800` with `build_browse_stmt(spec, cursor=None, sort=None, limit=limit)`.
   - **Delete `_build_content_stmt` entirely.**
   - Update `_record_to_dict` to accept ORM row via `spec.projection_mode` so GEXF path still works.
   - Regression test: `test_export_equals_browse.py` turns from xfail to green.

3. **Count/row parity.** (QA §3.2, UX Blocker #3.)
   - Replace `_count_matching(..., show_all=show_all)` at `content.py:1143-1160` and `:1442-1459` with `build_count_stmt(spec)`. Remove drift-prone positional arguments.
   - Regression test: `test_count_vs_rows_invariant.py` must be green.

4. **`content_types` default — posts-only, with visible clearable filter.** (QA §2.4, UX Blocker #1. Decision B.)
   - **Keep** `content_types=["post"]` as the default in `ContentFilterSpec.from_browse_route()` when the user has not explicitly specified a value. This preserves the current researcher-typical view.
   - **Critical:** the default MUST be visible to the user. Implement via a filter pill (Phase 6 item 1) that shows "Content type: Posts" with an (x) to clear — even on initial page load when the user has not touched the filter.
   - Template update `browser.html:254-278`: restructure the Posts/Comments checkbox pair into a multi-select covering the 14 real content_type values (`post, comment, search_result, video, reply, autocomplete_suggestion, ai_chat_citation, tweet, wiki_pageview, reel, article, scraped_web_page, ai_chat_response, press_release`). Group them visually (Social / Search / Reference / News / AI) for scannability. Default-check only `post`.
   - Add an explicit "All content types" pseudo-option that, when selected, clears the filter. Serialize this as `content_types=__all__` or via a separate hidden sentinel so the backend can distinguish "all" from "none selected".
   - **Distinguish explicit-clear from not-sent.** Like decision (B + E) for language: if the form submits `content_types` as an empty list (user unchecked all boxes), treat as explicit-clear and pass `None` to the spec. If the form does not submit `content_types` at all (initial page load, no filter params), apply the posts-only default. Use the same "was_explicit" sentinel pattern as language.
   - **Regression test:** `test_content_types_defaults.py` covers: (a) initial load shows posts only, (b) unchecking all boxes shows everything, (c) `content_types=video` shows only videos, (d) filter pill is always present and clickable.

5. **Language default unclearable.** (UX Blocker #2.)
   - Introduce a "was_explicit" sentinel for `language` like the existing `project_id_was_explicit` pattern at `:1017`. If the user submits `language=""`, treat as explicit clear and do NOT apply project default.
   - Regression test: `test_filter_reset_clears_language.py`.

6. **Initial-load vs HTMX-refresh parity.** (QA §2.3 + UX Major #8.)
   - Add hidden `<input name="platform">` and `name="arena"` in `browser.html` near line 53 so singular params survive HTMX reloads.
   - Add `platform` and `arena` `Query()` parameters to `content_records_fragment` at `:1202`.
   - Delete `arena=None` hardcode at `:1336` and `:1447`.
   - Project auto-select: push `project_id` into URL via `hx-push-url` (per decision C.a). Implementation at `:1030-1040`.

7. **`arenas_list` post-hoc IN clause folded into spec.** (Punch list items 11, 16.)
   - Move three `stmt = stmt.where(UniversalContentRecord.platform.in_(arenas_list))` calls at `:1094, 1358, 1804` into `ContentFilterSpec.platforms: list[str]`.

**Exit criteria.**
- `test_count_vs_rows_invariant.py` green for all sidebar-expressible combinations.
- `test_export_equals_browse.py` green.
- `test_show_all_semantics.py`, `test_content_types_defaults.py`, `test_filter_reset_clears_language.py` green.
- `test_filter_current_behavior.py` xfail tests that encoded P0 bugs flip to strict=True and remain green.
- Manual smoke: open `/content`, select 3 arenas incl. Facebook, uncheck `show_all`, verify Facebook records appear while YouTube records are still term-matched only. Count badge matches rows.

**Dependencies.** Phase 1a. (Phase 1b can run in parallel.)
**Effort.** L. 4-5 engineering days.
**Owners.** `core-application-engineer` (lead), `frontend-engineer` (template), `qa-guardian` (regression tests).

---

### Phase 3 — Missing Filters (gate: Phase 2 green)

**Goal.** Ship every filter the user expects. Make "reset" actually reset.

**Tasks.**

1. **Actor filter.** Filters `content_records.author_id IN (...)`. HTMX-lazy load scoped to selected `run_id` or `project_id`.
   - New endpoint `GET /content/actors` returning `<option>` fragment, mirroring `/content/search-terms` at `:1479-1550`.
   - New `ContentFilterSpec.actor_ids: list[UUID]` field.
   - Template: new `<select name="actor_id">` block between Search Term and Scrape Status.
   - Verify `idx_content_author` is not partial and covers `IN` path.

2. **Query design filter.** Sidebar affordance matching existing `query_design_id` URL param at `:978`.
   - Add `<select name="query_design_id">` next to Project, populated from user's query designs.
   - Already in `ContentFilterSpec`.

3. **Full content_type multi-select.** If decision B = "all by default", template reflects this.

4. **"Reset filters" truly resets.** Current `<a href="/content">` at `browser.html:282` re-applies auto-defaults.
   - Change to `<a href="/content?reset=true">` and honor sentinel to bypass auto-select.
   - OR surface filter pills with individual (x) buttons (see Phase 6).

5. **Search term dropdown race.** Fix at `browser.html:173-201` by moving fetch to `hx-trigger="htmx:afterRequest from:#filter-form"`. Remove misread `hx-include="[name='search_term']"`.

6. **Search term link resolution.** Fix UX Major #6 — `_build_browse_stmt` must use `_run_id_filter` when a run_id is selected so linked-record terms don't dead-end.

**Exit criteria.**
- Phase 0 matrix regrown to cover new filters.
- Every sidebar control exercised in isolation and in combination with ≥3 others.
- "Reset filters" verified manually and via smoke test.

**Dependencies.** Phase 2.
**Effort.** M. 3-4 engineering days.
**Owners.** `core-application-engineer`, `frontend-engineer`, `ui-designer` (filter pills), `qa-guardian`.

---

### Phase 4 — Rename to "Recent Content" (gate: none; can run any time after Phase 2)

**Goal.** Make the page's stated purpose match its implementation. The page is recency-ordered — call it that.

**Tasks.**

1. **Rename page header.** `browser.html:320-340` — change "Content Browser" (or current copy) to "Recent Content".
2. **Update page description.** Below the header, add one-line subtitle: "Most recent content collected across all configured arenas, ordered by publication time."
3. **Update 2000-row cap banner** at `browser.html:363-369`: "Showing the 2,000 most recently published records that match your filters. For the full matching set, export CSV."
4. **Search and remove** every instance of inaccurate sampling claims from the codebase. Audit `src/` and researcher-facing `docs/` and update or remove the copy.
5. **Update navigation label** in `_partials/nav.html` if it says "Content Browser" → "Recent Content".
6. **Update researcher documentation.** If `docs/researcher_guides/` mentions the content page, align the description with the new semantics.
7. **Add an explicit sort disclosure** near the table header: "Sorted by publication date, newest first. Click any column to re-sort."
8. **Integration test** `test_page_rename.py` — assert the page title, subtitle, and banner copy match the new strings.

**Exit criteria.**
- Page header, subtitle, banner, and nav label all say "Recent Content".
- Zero matches for inaccurate sampling claims in `src/` and researcher-facing docs.
- Docs aligned.

**Dependencies.** None (can ship any time after Phase 2, or even before if desired).
**Effort.** S. 1 engineering day.
**Owners.** `frontend-engineer` (lead), `ui-designer` (copy review), `research-strategist` (docs update).

---

### Phase 5 — Performance + Indexes (gate: Phase 2; parallel with Phase 3)

**Goal.** Eliminate seq-scans from Phase 2/3 fixes. Verify assumed indexes exist.

**Tasks.**

1. **Verify `collection_run_id` is indexed.** QA §4.2 item 3 flags as known unknown. Run `\d content_records` live; if absent, migration `04X_add_content_collection_run_id_index.py` for btree on `(collection_run_id, published_at DESC)`.
2. **Effective-language functional index.** New migration creating `CREATE INDEX idx_content_effective_lang ON content_records ((split_part(COALESCE(NULLIF(language, ''), raw_metadata->'enrichments'->'language_detection'->>'language'), '-', 1)))`.
3. **`content_type` index.** Check cardinality first. If >90% `post`, partial index `WHERE content_type != 'post'`; otherwise full `(content_type, published_at DESC)` composite.
4. **Duplicate-exclusion predicate index.** Verify `idx_content_metadata` GIN covers `(raw_metadata->>'duplicate_of') IS NULL`, or add partial index.
5. **EXPLAIN ANALYZE on top 10 filter combinations** from integration matrix. Any seq-scan without partition prefilter is a regression — block merge.

**Exit criteria.**
- All Phase 3 combinations execute <200ms on staging corpus.
- EXPLAIN ANALYZE shows index usage for every combination.
- No full-table seq-scan of `content_records` unless `total_count > 100k`.

**Dependencies.** Phase 2.
**Effort.** M. 2-3 engineering days.
**Owners.** `db-data-engineer` (lead), `core-application-engineer` (SQLAlchemy wiring).

---

### Phase 6 — UX Polish (gate: Phase 3; optional for initial release)

**Goal.** Make filter state visible. Correct UI labels.

**Tasks.**

1. **Active filter pills.** Each active filter shown as a chip above results with individual (x) removal. Makes auto-applied defaults (project, language) visible.
2. **Validation feedback.** Display 400 error banner when `_parse_date_param` fails instead of silently dropping filter.
3. **20-run cap disclosure.** Surface in UI ("Showing 20 most recent runs") and provide search-within-runs affordance.
4. **Page-size control.** Expose `limit` parameter with "Show 50 / 100 / 200 per page" select.
5. **Arena-vs-platform label fix.** Template says "Arena" but filter sends platform names. Either relabel "Arena" → "Platform" in sidebar, or route filter through `arena` column consistently. Requires `ui-designer` decision.

**Exit criteria.**
- Usability test: a new researcher can identify what's filtering their view and how to clear it without reading docs.
- No silent filter state remains.

**Dependencies.** Phase 3.
**Effort.** M. 2-3 engineering days.
**Owners.** `ui-designer` (lead), `frontend-engineer`, `qa-guardian`.

---

## 3. Decisions (all resolved 2026-04-10)

All seven decisions have been answered by the user. The plan proceeds without further gates.

| ID | Topic | Answer | Blocks |
|---|---|---|---|
| A | Sampling semantics | **Rename to "Recent Content."** Document the `published_at DESC` sort. Do not implement random/stratified sampling. | Phase 4 |
| B | Content type default | **Posts-only default** with visible, clearable filter pill. Expand checkbox pair to cover all 14 content types. Support explicit-clear. | Phase 2 item 4 |
| C | Auto-select project | **Keep, push URL** via `hx-push-url`. Filter becomes visible, bookmarkable, resettable. | Phase 2 item 6 |
| D | Collaborator scoping | **Everywhere.** Browser, detail, dashboard count, export all use `OwnershipScope.owner_plus_collaborators`. | Phase 1a, Phase 2 item 3 |
| E | `_build_content_stmt` | **Delete.** Export shares browse query (follows from D). | Phase 2 item 2 |
| F | Duplicate exclusion | **Apply by default, add "Show duplicates" checkbox.** Parity with analysis; researchers can opt in. | Phase 1a predicate list |
| G | Analysis refactor scope | **Full migration.** Delete `analysis/_filters.py`, migrate 18 callers to `ContentFilterSpec`. See Phase 1b. | Phase 1b |

**Implementation notes derived from the decisions:**

- **Decision B expansion.** The "visible filter pill" approach means the default is never silent. On initial page load, the user sees a pill at the top of the results: `Content type: Posts [x]`. Clicking (x) submits `content_types=__all__` and shows everything. This resolves the UX Blocker #1 concern that researchers "have no way to know what was filtered". Phase 6 filter-pill work is therefore **coupled to** Phase 2 item 4 — the pill must ship together with the posts-only default.
- **Decision G expansion.** Phase 1b migrates 18 call sites across 6 files (see §1.5). After migration, `analysis/_filters.py` is deleted entirely. This is an intentional hard-break: any remaining caller fails at import time, so no drift is possible.
- **Decision F expansion.** The content browser gets a new "Show duplicates" checkbox in the sidebar (Phase 3). Default unchecked. When checked, `ContentFilterSpec.include_duplicates = True` and the `(raw_metadata->>'duplicate_of') IS NULL` predicate is skipped. Analysis callers always set `include_duplicates=False` (the default).

---

## 4. Risks and Sequencing Traps

1. **Changing `content_types` default will look like a regression.** Mitigation: Phase 6 filter pills surface the default; Phase 2 ships with a release note and a one-time "we changed how content type filters work" banner on first visit.
2. **Ownership scoping fix could leak data.** Mitigation: `test_ownership_scoping.py` matrix covers `{owner, collaborator, admin, stranger} × {/, /records, /export, /{id}, /count}` = 20 cases. Zero-row strangers AND non-empty collaborators both asserted.
3. **Actor filter introduces N+1 risk.** Mitigation: Phase 3 item 1 scopes the actor list to the current `run_id` or `project_id`; if neither is set, filter disabled. Paged `/content/actors` with search.
4. **Refactor regressions during Phase 1.** Even a single `nullif` drop shifts row sets. Mitigation: Phase 0 diff harness is non-negotiable — Phase 1 cannot merge unless diff harness is green for every spec.
5. **Partition pruning regression.** `content_records` is range-partitioned by `published_at`. Dropping a partition-pruning predicate will full-table scan 20+ partitions. Mitigation: Phase 5 EXPLAIN ANALYZE pass before merge.
6. **Danish character preservation.** Currently tested only in `test_content_route_search_terms.py`, not in browse path. Add to Phase 0 fixtures.
7. **`format` parameter shadow.** When Phase 6 renames to `format_: str | None = Query(None, alias="format")`, verify slowapi comment at `:1685` is still valid; if not, re-enable rate-limiting.
8. **Auto-select invalidates bookmarks.** Mitigation: Decision C.a (push URL) makes bookmarks stable.
9. **HTMX form re-entrancy.** Use `hx-sync="closest form:drop"` as safety net for out-of-order responses.
10. **`content_record_count` scope drift.** Keep the `query_design_ids` short-circuit as an optimization hint inside `build_count_stmt` — same predicates, different indexed access path. EXPLAIN ANALYZE pre/post.

---

## 5. Test Strategy

Extend `tests/integration/api/content/`. All tests use `seeded_corpus`.

| File | Coverage |
|---|---|
| `test_filter_diff_harness.py` | Pre/post refactor row-set identity for every spec. Phase 1 gate. |
| `test_count_vs_rows_invariant.py` | `count(filter) == len(rows(filter))` for every combination. Phase 2 gate. |
| `test_export_equals_browse.py` | Export CSV row IDs = browse row IDs for same filter. Phase 2 gate. |
| `test_show_all_semantics.py` | Facebook visible when `show_all=False`; Reddit excludes non-matched. |
| `test_content_types_defaults.py` | Post-only vs all-types per decision B. |
| `test_filter_reset_clears_language.py` | `?language=` empty string does NOT reapply project default. |
| `test_ownership_scoping.py` | 4 users × 5 routes = 20 cases. Each asserts specific row-ID set. |
| `test_cursor_pagination.py` | Keyset and offset pagination round-trips. |
| `test_duplicate_exclusion.py` | Content browser and analysis agree on row counts. |
| `test_filter_composition_matrix.py` | All pairs `(A, B)` asserting result is `rows(A) ∩ rows(B)`. |
| `test_actor_filter.py` | Phase 3. |
| `test_query_design_filter.py` | Phase 3. |
| `test_search_terms_race.py` | Phase 3 — dropdown not repopulated before form response. |
| `test_sampling_representativeness.py` | Phase 4 per decision A. |
| `test_danish_text_preserved.py` | `æ/ø/å` through filter → SQL → response → rendered HTML. |

Unit companions at `tests/unit/core/queries/test_content_filters.py` cover `ContentFilterSpec` shape, `OwnershipScope` logic, and predicate parity across dialects.

Every test is parametric over a `FilterSpec` matrix declared in `tests/integration/api/content/_matrix.py` — adding a new filter means adding one row, not N test files.

---

## 6. Out of Scope (Explicitly Deferred)

- **Raw JSONB filter exposure** (QA §8 item 19). Net-new feature.
- **Dynamic full-text search dictionary for non-Danish** (QA §8 item 17). Per-language expression indexes needed.
- **Strict date parsing with 400 errors** (QA §2.10). Phase 6 adds banner; full 400 flow deferred.
- **Content-count endpoint renaming** (QA §3.3). Cosmetic.
- **Analysis descriptive/network caller migration** (decision G option a). Follow-up cleanup.
- **Async export parity with sync export** (`/content/export/async`). Same filter-drop risk, audit separately.
- **20-run cap removal.** Phase 6 surfaces the cap; removal is a separate performance exercise.
- **Filter pills as independently shippable.** Phase 6 ships it; could be first user-facing win if priorities shift.

---

## 7. Phase Dependency Graph

```
Phase 0 (regression harness)
    └── Phase 1a (shared helper: content routes)
            ├── Phase 1b (analysis layer migration)   ──┐
            │                                           │
            └── Phase 2 (P0 correctness fixes)          │  parallel streams
                    ├── Phase 3 (missing filters + "Show duplicates" checkbox)
                    │       ├── Phase 4 (rename to "Recent Content") [independent; can ship any time]
                    │       └── Phase 6 (UX polish incl. filter pills, coupled to Phase 2 item 4)
                    └── Phase 5 (perf + indexes)
```

**Parallelism notes:**
- Phase 1b (analysis migration) runs in parallel with Phase 2 — different engineers, disjoint files.
- Phase 4 (rename) has no dependencies and can ship any time after Phase 2; it's the lightest lift.
- Phase 6 filter-pill work is coupled to Phase 2 item 4 — the pill ships together with the posts-only default so the default is never silent.

---

## Critical Files for Implementation

- `src/issue_observatory/api/routes/content.py`
- `src/issue_observatory/api/templates/content/browser.html`
- `src/issue_observatory/analysis/_filters.py`
- `src/issue_observatory/core/queries/content_filters.py` **(new — the shared helper)**
- `tests/integration/api/content/conftest.py` **(new — the fixture corpus Phase 0 depends on)**

---

## Rough Effort Summary

| Phase | Effort | Days | Parallelizable? |
|---|---|---|---|
| 0 — Regression harness | L | 3-5 | No |
| 1a — Shared helper (content routes) | L | 4-6 | No |
| 1b — Analysis layer migration (18 call sites) | M | 3-4 | Yes — parallel with Phase 2 |
| 2 — P0 correctness fixes | L | 4-5 | Yes — parallel with Phase 1b |
| 3 — Missing filters + "Show duplicates" checkbox | M | 3-4 | No |
| 4 — Rename to "Recent Content" | S | 1 | Yes — any time after Phase 2 |
| 5 — Performance + indexes | M | 2-3 | Yes — parallel with Phase 3 |
| 6 — UX polish (filter pills coupled to Phase 2) | M | 2-3 | Partially |
| **Total (serial upper bound)** | | **22-31 days** | |
| **Total (with parallelism)** | | **~16-22 days** | |

**Critical path to data correctness** (Phases 0 → 1a → 2): ~11-16 days. This is the minimum before the P0 bugs are fixed. Phase 1b runs concurrently with Phase 2 to close the analysis-layer drift gap. Phase 4 (rename) is a 1-day drop-in that can happen any time after Phase 2.

**Recommended staffing:**
- Phases 0, 1a: `qa-guardian` + `core-application-engineer` together (fixture + helper).
- Phase 1b: `db-data-engineer` solo (owns analysis layer), while Phase 2 runs in parallel.
- Phase 2: `core-application-engineer` + `frontend-engineer` + `qa-guardian`.
- Phase 3: `core-application-engineer` + `frontend-engineer`.
- Phase 4: `frontend-engineer` solo (1 day).
- Phase 5: `db-data-engineer` solo.
- Phase 6: `ui-designer` + `frontend-engineer` (filter pills ship with Phase 2).
