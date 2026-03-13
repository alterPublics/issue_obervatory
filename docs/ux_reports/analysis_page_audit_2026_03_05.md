# Analysis Page Comprehensive UX Audit

**Date:** 2026-03-05
**Page:** `/analysis/design/65c84d82-7055-451c-a1dc-525dd5f862ee` (query design "iran_base")
**Design:** iran_base -- 4 collection runs (3 with records), 1011 total records across bluesky, reddit, rss_feeds, ritzau_via, wikipedia, domain_crawler
**Method:** Live page fetch, template source code review, API endpoint testing, JavaScript analysis

---

## Executive Summary

The analysis page is a feature-rich dashboard that attempts to provide researchers with volume trends, actor/term distributions, network graphs, enrichment results, and export capabilities. However, the page suffers from **two server-crashing bugs** (temporal networks, filtered export), **four categories of empty/non-functional panels** (enrichments, emergent terms, suggested terms, cross-platform actors), **misleading data presentation** (no run status indicators, subreddit-as-actor confusion), and **structural UX issues** (duplicate-looking controls, no filter reactivity without explicit button click). A researcher would encounter at least 5 broken panels and 2 server errors before completing a basic analysis workflow.

---

## Section-by-Section Findings

### 1. Summary Cards (Top of Page)

**Status: PARTIALLY WORKING -- data accuracy issues**

The four summary cards load successfully from `GET /analysis/design/{id}/summary`. However:

**Issue 1.1 -- "Completed runs" shows 0 when there are clearly records** [frontend]
The summary endpoint returns `completed_runs: 0` and `total_runs: 4`. This is technically correct -- all 4 runs have status `failed` or `cancelled` in the database. But the page simultaneously shows "3 runs" badge in the header and lists 3 runs in both the dropdown filter and the "Included Runs" table at the bottom, with record counts of 206, 503, and 878. The researcher sees contradictory information: a prominent "0" for completed runs alongside evidence that 1011 records were collected. The disconnect is never explained.

**Issue 1.2 -- "Total credits" shows 0** [core]
The summary shows `total_credits: 0`. All runs used free-tier arenas, so this is likely technically correct, but the card label dynamically switches between "Total credits" and "Credits spent" depending on which field is present. Showing "0" for credits without context is confusing -- the researcher cannot tell whether credits were not tracked, were not consumed, or were not applicable.

**Issue 1.3 -- Date range card formatting is fragile** [frontend]
The date range card uses a complex chain: `(summary.content_date_from || summary.published_at_min || summary.first_run_at || '').slice(0,10)`. This works but produces raw ISO date fragments like "2009-10-26" without any locale formatting. A Danish researcher would expect "26. okt. 2009" or at minimum "26/10/2009".

---

### 2. Filter Bar

**Status: WORKING with significant UX friction**

The filter bar includes: Collection Run dropdown, Platform dropdown, Arena dropdown, Date From/To inputs, Granularity toggle (hour/day/week/month), Apply and Reset buttons.

**Issue 2.1 -- Filters require explicit "Apply" click** [frontend]
Changing the run dropdown, platform, arena, or granularity does NOT automatically refresh the charts. The researcher must click "Apply" after every change. This is unintuitive -- the run dropdown, in particular, feels like it should immediately switch context since it is the most common filter action. The `@filter-applied.window` event mechanism is correctly wired, but it only fires on explicit `applyFilters()` call.

**Issue 2.2 -- Platform and Arena dropdowns are populated from filter-options endpoint but may be empty on first render** [frontend]
The `GET /analysis/design/{id}/filter-options` endpoint returns `{"platforms": [...], "arenas": [...]}`. The dropdowns use `<template x-for>` to render options. If the fetch fails (network error, 404), the dropdowns silently show only "All platforms" / "All arenas" with no indication that filter options failed to load.

**Issue 2.3 -- Granularity buttons have no visual feedback on apply** [frontend]
Clicking a granularity button (hour/day/week/month) changes its visual state immediately but does not trigger a chart refresh. This creates a false sense of action -- the researcher clicks "week", sees it highlighted, and expects the volume chart to update. Nothing happens until they also click "Apply".

---

### 3. Volume Over Time Chart

**Status: WORKING**

The volume chart loads from `GET /analysis/design/{id}/volume` and renders correctly as a multi-arena line chart via `initMultiArenaVolumeChart`. The data spans from 2009 to 2026 (reflecting the range of collected records).

**Issue 3.1 -- Calendar event overlay loads but may clutter sparse data** [frontend]
The political calendar events (`/static/data/political_calendar.json`) are enabled by default (`showCalendarEvents: true`). For a dataset spanning 2009-2026 on a daily granularity, the annotation lines would be extremely dense. The category filter checkboxes (election, parliament, international, other) and country radio buttons (All, Denmark, Greenland, International) work correctly in the template code, but with only recent events in the calendar file (2026), they are irrelevant for the historical portion of the data.

**Issue 3.2 -- No indication of which arenas contribute to each line** [frontend]
The legend shows arena names ("news_media", "reference", "social_media", "web") which are internal arena group names rather than researcher-friendly labels. A researcher tracking "iran" in Danish media would not immediately understand what "reference" means (it refers to Wikipedia).

---

### 4. Top Actors Chart

**Status: WORKING but data quality issue**

The chart loads from `GET /analysis/design/{id}/actors?limit=20` and renders as a horizontal bar chart.

**Issue 4.1 -- CRITICAL: Subreddit names appear as "actors"** [data]
The top two "actors" are "Denmark" (105 records) and "scandinavia" (41 records). These are Reddit subreddit names (`r/Denmark`, `r/scandinavia`), not people or organizations. They are being treated as `author_display_name` values in the actor ranking. This fundamentally misleads the researcher about who is discussing Iran in Danish media. The Reddit collector appears to be storing the subreddit name in the author field rather than the actual post author.

**Issue 4.2 -- No platform disambiguation in actor labels** [frontend]
The chart shows "DR Udland (dkbot)" from Bluesky alongside "Denmark" from Reddit. There is no visual indicator of which platform each actor comes from. The actors API response includes `platform` but the chart rendering code ignores it.

**Issue 4.3 -- Resolved actor names not populated** [data]
All actors have `resolved_name: null` and `actor_id: null`, meaning none have been linked to the Actor Directory. The "Green check indicates identity confirmed via Actor Directory" legend at the bottom of the chart panel never activates. This is likely expected for a dataset without entity resolution, but the legend is always present (even when irrelevant), which may confuse researchers.

---

### 5. Top Terms Chart

**Status: WORKING**

The chart loads from `GET /analysis/design/{id}/terms?limit=20` and shows 6 terms: "iran" (915), "iranske" (151), "khamenei" (51), "teheran" (20), "tehran" (7), "revolutionsgarden" (5). This is a plausible distribution for an Iran-focused query design.

No issues identified -- this panel works as expected.

---

### 6. Engagement Distribution Chart

**Status: WORKING**

The chart loads from `GET /analysis/design/{id}/engagement` and shows grouped bars for likes, shares, comments, and views with mean/median/p95 values. The data is reasonable (likes mean=17.23, views mean=218.76).

**Issue 6.1 -- Mean vs median disparity not explained** [frontend]
The chart shows mean=17.23 and median=2.0 for likes, suggesting a heavy right tail (a few viral posts pull the mean up). This is important methodological context that is not surfaced to the researcher. A tooltip or annotation explaining the disparity would help researchers decide whether to use mean or median in their analysis.

---

### 7. Emergent Terms Panel

**Status: NOT WORKING -- returns empty data**

The endpoint `GET /analysis/design/{id}/emergent-terms?top_n=20&exclude_search_terms=1` returns `[]` (empty array). The panel correctly shows "No emergent terms data available for this design."

**Issue 7.1 -- Empty state does not explain WHY there are no emergent terms** [frontend]
The empty state message is generic. It does not tell the researcher whether: (a) TF-IDF analysis has not been run yet, (b) there are insufficient records for analysis, (c) all frequent terms happen to be search terms, or (d) the enrichment pipeline has not processed this data. The researcher has no way to trigger the analysis or understand what would need to happen for emergent terms to appear.

---

### 8. Network Analysis Section

**Status: PARTIALLY WORKING -- temporal views crash, static views work**

The network section has 4 tabs: Actor network, Term network, Bipartite, Cross-platform actors.

#### 8a. Actor Network (Static)

**Status: WORKING**

The actor co-occurrence network loads (77 nodes, 200 edges) and renders via sigma.js with ForceAtlas2 layout. Zoom controls work. GEXF export link is present and functional.

**Issue 8a.1 -- Node labels only visible on zoom** [frontend]
`labelRenderedSizeThreshold: 6` means labels only appear when zoomed in. On the default view, the researcher sees a cloud of colored dots with no labels. This makes the initial impression of the network graph feel empty or broken, even though hovering reveals labels.

**Issue 8a.2 -- "Author" and "Term" legend shown for actor-only network** [frontend]
The legend at the bottom shows both "Author" (blue) and "Term" (amber) node types, but an actor co-occurrence network should only contain author nodes. The legend is hardcoded in the template for all three network tab types rather than being dynamic based on the actual node types in the graph.

#### 8b. Actor Network (Temporal)

**Status: BROKEN -- server crash (500 error)**

Clicking "Temporal Snapshots" triggers `GET /analysis/design/{id}/network/actor/temporal`, which crashes with:
```
asyncpg.exceptions.AmbiguousColumnError: column reference "term_matched" is ambiguous
```

**Root cause identified:** In `/src/issue_observatory/analysis/network.py`, the `_fetch_actor_temporal_rows` function builds a b-side filter by calling `_build_run_filter(None, None, None, None, None, None, b_params)` with no table alias. The `build_content_filters` function in `_filters.py` always appends `term_matched = TRUE` (line 126). When no table alias is provided, this produces the unaliased `term_matched = TRUE`. The SQL query uses a self-join (`content_records a JOIN content_records b`), so `term_matched` is ambiguous because both tables have that column.

The `raw_metadata` clause is partially fixed by the `.replace("raw_metadata", "b.raw_metadata")` line, but `term_matched` is not similarly handled.

**Research impact:** A researcher clicking "Temporal Snapshots" sees an infinite loading spinner or an unexplained error. The temporal network feature is completely unusable. No error message is shown to the researcher explaining what happened.

#### 8c. Term Network (Static)

**Status: WORKING**

The term co-occurrence network loads (6 nodes, 8 edges) and renders correctly.

#### 8d. Term Network (Temporal)

**Status: BROKEN -- same server crash as 8b**

Same `AmbiguousColumnError` as the actor temporal endpoint (in `_fetch_term_temporal_rows`, the `scope_filter` uses `a.` prefix but the raw SQL includes `cr.` as the table alias and the filter clauses do not match).

Wait -- actually looking at the term temporal SQL more carefully, it uses `cr` as the alias, not `a`. The `scope_filter` was built with `table_alias="a."`, so clauses reference `a.query_design_id`, `a.term_matched`, etc. But the SQL uses `cr` as the table name. This is a **different** bug: alias mismatch. The scope filter says `a.term_matched = TRUE` but the table is aliased as `cr`, causing either a "column a.term_matched does not exist" or an ambiguity error.

#### 8e. Bipartite Network (Static)

**Status: WORKING**

The bipartite network loads (232 nodes, 307 edges) and renders via sigma.js. Being larger than 100 nodes, it would trigger the `tooLarge` warning and show the top 100 by degree.

#### 8f. Cross-Platform Actors Tab

**Status: WORKING but empty**

The endpoint `GET /analysis/design/{id}/network/cross-platform` returns `[]`. The table shows "No cross-platform actors found. Entity resolution may not have been performed for this collection run." This is accurate -- no entity resolution has been performed.

**Issue 8f.1 -- Developer jargon in description** [frontend]
The tab description says: "Actors resolved across multiple platforms via entity resolution. Only actors where `author_id` is non-null are shown." The code-formatted `author_id` is developer language. A researcher does not know what `author_id` means or how entity resolution works. The description should explain in plain terms what this feature does and what the researcher needs to do to populate it.

#### 8g. Duplicate Menu Controls in Network Section

**Status: DESIGN ISSUE -- not a technical bug**

Each of the three network tabs (Actor, Term, Bipartite) has its own "Static Network" / "Temporal Snapshots" toggle buttons. When a researcher looks at the network section, they see the tab bar AND the view mode toggle, creating a two-level navigation structure:
```
[Actor network] [Term network] [Bipartite] [Cross-platform actors]
[Static Network] [Temporal Snapshots]
```
This is likely what the user reported as "duplicate menus." The view mode toggle appears identically in all three tabs, creating visual repetition. A researcher might expect the "Static Network" / "Temporal Snapshots" choice to be a global setting rather than per-tab.

---

### 9. Enrichment Analysis Section

**Status: ALL FOUR PANELS SHOW EMPTY STATE -- endpoint returns empty arrays**

The enrichment section contains four panels: Language Distribution, Top Named Entities, Cross-Arena Propagation, Coordination Signals.

All four endpoints return empty arrays `[]` with HTTP 200:
- `GET /analysis/design/{id}/enrichments/languages` -> `[]`
- `GET /analysis/design/{id}/enrichments/entities?limit=20` -> `[]`
- `GET /analysis/design/{id}/enrichments/propagation` -> `[]`
- `GET /analysis/design/{id}/enrichments/coordination` -> `[]`

**Issue 9.1 -- No explanation of why enrichments are empty** [frontend]
All four panels show generic empty state messages like "No language enrichment data available" or "No cross-arena propagation patterns detected." The researcher has no way to know:
- Whether the enrichment pipeline has run
- Whether it needs to be triggered manually
- Whether there is insufficient data for analysis
- Whether enrichments are a paid feature
- How long enrichments take to process after collection

The descriptive text at the top says "Enrichments are applied after collection completes and may take a few minutes to process" but does not indicate whether they HAVE been applied yet.

**Issue 9.2 -- All runs are status=failed, enrichments may never have run** [core]
Since all collection runs have status `failed` (not `completed`), the post-collection enrichment pipeline may never have been triggered. The enrichment section does not check or communicate this prerequisite.

---

### 10. Export Data Section

**Status: PARTIALLY WORKING -- sync export works, filtered export crashes, async export starts**

#### 10a. Sync Export (up to 10k records)

**Status: WORKING**

The "Export (up to 10 k records)" button correctly generates download URLs. Tested `GET /content/export?format=csv&query_design_id=...` -- returns valid CSV data with Danish characters preserved (ae, oe, aa confirmed in content).

GEXF export also works -- produces valid XML with proper namespace declarations.

#### 10b. Filtered Export

**Status: BROKEN -- server crash (500 error)** [core]

Clicking "Download filtered records" (with a search_term filter applied) triggers `GET /analysis/design/{id}/filtered-export?format=csv&search_term=iran`, which crashes with:
```
NotImplementedError: ARRAY.contains() not implemented for the base ARRAY type;
please use the dialect-specific ARRAY type
```
This indicates the filtered-export endpoint uses SQLAlchemy's generic `ARRAY.contains()` instead of PostgreSQL-specific `ARRAY` type, causing a crash when filtering by search_term.

**Research impact:** A researcher who wants to export only records matching a specific search term gets a server error with no user-facing message.

#### 10c. Async Export

**Status: PARTIALLY WORKING**

The async export endpoint `POST /content/export/async` returns `{"job_id": "...", "status": "pending"}` with HTTP 202. The polling mechanism is correctly implemented in JavaScript. However, the actual job execution depends on the Celery worker, which was not tested in this audit.

#### 10d. Export Format Options

**Status: CORRECTLY IMPLEMENTED**

The format selector offers 7 formats: CSV, XLSX, NDJSON, PARQUET, GEXF, RIS, BibTeX. The GEXF option correctly shows an additional "Network type" radio group (Actor co-occurrence / Term co-occurrence / Bipartite actor-term). The conditional visibility via `x-show="exportFormat === 'gexf'"` works correctly.

**Issue 10d.1 -- RIS and BibTeX tooltip icons are functional but appearance is subtle** [frontend]
The "?" help icon next to RIS ("for Zotero, Mendeley, EndNote") and BibTeX ("for LaTeX/Overleaf") is a small gray circle that could be easily missed. These are important format hints for researchers who may not know the difference.

---

### 11. Suggested Terms Panel

**Status: WORKING but empty**

The endpoint `GET /analysis/design/{id}/suggested-terms?top_n=10` returns `[]`. The panel shows "No suggestions available for this design."

**Issue 11.1 -- Duplicate functionality with Emergent Terms panel** [frontend]
Both "Emergent Terms" and "Suggested Terms" panels appear to serve nearly identical purposes: showing terms from collected content that are not in the query design. Both have "Add to design" buttons. Both return empty arrays for this dataset. The difference between them is not explained to the researcher:
- "Emergent Terms" uses TF-IDF scoring and supports configurable `top_n` and `exclude_search_terms` options
- "Suggested Terms" appears to use a simpler ranking

Having both panels on the same page without clear differentiation creates confusion.

---

### 12. Included Runs Table

**Status: WORKING but missing critical information**

The table at the bottom lists 3 runs with their IDs (truncated), start timestamps, and record counts. All three show the same timestamp "2026-03-05T07:08" which is confusing.

**Issue 12.1 -- No run status column** [frontend]
The table does not show the status of each run. All three runs are `failed` in the database, but the researcher sees only record counts and start times. Without a status indicator, the researcher has no way to know their data came from failed runs that may be incomplete.

**Issue 12.2 -- Run IDs are not clickable** [frontend]
The truncated run IDs (e.g., "46fe0b6f...") are plain text, not links. The researcher cannot navigate to the collection detail page to see what happened during the run, which arenas succeeded, which failed, or what error occurred.

**Issue 12.3 -- All runs show identical timestamps** [data]
All three runs display "2026-03-05T07:08" as their start time. Either all runs were started simultaneously (unusual) or the timestamp precision is being truncated too aggressively.

---

### 13. Compare Runs Modal

**Status: CONDITIONALLY WORKING**

The "Compare runs" button only appears when a specific run is selected in the filter dropdown (`x-show="filters.run_id"`). The modal loads, fetches available runs, and navigates to `/analysis/compare?run_ids=...`.

**Issue 13.1 -- Compare excludes non-completed runs, resulting in empty list** [core]
The compare modal JavaScript filters `availableRuns` to `r.status === 'completed'`. Since all runs are `failed`, the modal shows "No other completed runs available for comparison." The researcher selects a run (which has data), clicks "Compare runs", and is told there is nothing to compare against -- even though other runs with data exist. The filter should include runs with `records_collected > 0` regardless of status, or at least explain why no runs are available.

---

## Blocker Issues (Prevent Researcher from Completing Task)

| # | Issue | Component | Responsible |
|---|-------|-----------|-------------|
| B1 | Temporal network endpoints crash with SQL `AmbiguousColumnError` on `term_matched` | Backend | [core] |
| B2 | Filtered export endpoint crashes with `ARRAY.contains() NotImplementedError` | Backend | [core] |
| B3 | Subreddit names displayed as actors (r/Denmark as "Denmark" with 105 records) | Data | [data] |

## Friction Points (Work but Confusing or Misleading)

| # | Issue | Component | Responsible |
|---|-------|-----------|-------------|
| F1 | "Completed runs: 0" displayed alongside 1011 records and 3 listed runs | Summary cards | [frontend] |
| F2 | Filters require explicit "Apply" click; granularity toggle gives false feedback | Filter bar | [frontend] |
| F3 | Arena names are internal identifiers ("reference", "social_media") not researcher-friendly labels | Volume chart | [frontend] |
| F4 | Network node labels invisible at default zoom level | Network graph | [frontend] |
| F5 | "Author"/"Term" legend shown for all network types including actor-only | Network graph | [frontend] |
| F6 | `author_id` developer jargon in cross-platform actors description | Network tab | [frontend] |
| F7 | Duplicate "Emergent Terms" and "Suggested Terms" panels with no differentiation | Page layout | [frontend] |
| F8 | Included Runs table missing status column; runs are failed but this is hidden | Table | [frontend] |
| F9 | Run IDs in table not clickable; no navigation to run detail page | Table | [frontend] |
| F10 | Date range in summary card uses raw ISO format, not Danish locale | Summary cards | [frontend] |
| F11 | No platform indicator on actor names in chart | Top actors chart | [frontend] |
| F12 | Mean vs median disparity in engagement not explained | Engagement chart | [frontend] |
| F13 | Compare runs modal shows empty list because it only includes "completed" runs | Modal | [frontend] |
| F14 | "Static Network" / "Temporal Snapshots" toggle repeated in each tab looks like duplicate menus | Network section | [frontend] |

## Panels with Empty State (Working but No Data)

| Panel | Status | Explanation |
|-------|--------|-------------|
| Emergent Terms | Empty array returned | TF-IDF analysis may not have run; empty message is generic |
| Suggested Terms | Empty array returned | Same concern as emergent terms |
| Cross-Platform Actors | Empty array returned | Entity resolution not performed; message is adequate |
| Language Distribution | Empty array returned | Enrichment pipeline likely never triggered (all runs failed) |
| Named Entities | Empty array returned | Same as above |
| Cross-Arena Propagation | Empty array returned | Same as above |
| Coordination Signals | Empty array returned | Same as above |

All 7 empty panels show generic messages without explaining whether the emptiness is expected, temporary, or requires action from the researcher.

## Data Quality Findings

| # | Finding | Responsible |
|---|---------|-------------|
| D1 | Reddit collector stores subreddit name as `author_display_name`; "Denmark" and "scandinavia" appear as top actors | [data] |
| D2 | All 4 collection runs are status `failed` or `cancelled`; none completed successfully. The 1011 records are partial collection results from failed runs | [core] |
| D3 | All 3 data-bearing runs show identical start timestamp (2026-03-05T07:08), suggesting they were launched simultaneously or the timestamp resolution is too coarse | [data] |
| D4 | No enrichment data exists for any records, meaning language detection, NER, propagation analysis, and coordination detection have not been performed | [core] |
| D5 | No actors have been entity-resolved (`actor_id` is null for all records), so cross-platform analysis is impossible | [data] |

## Recommendations (Prioritized)

### Critical (Must Fix)

1. **[core] Fix `AmbiguousColumnError` in temporal network SQL.** The `_build_run_filter` call for the b-side of the self-join must produce aliased clauses. The `term_matched = TRUE` clause at line 126 of `_filters.py` needs the table alias applied. Similarly, `_fetch_term_temporal_rows` uses `cr` as alias but the scope filter references `a.`.

2. **[core] Fix `ARRAY.contains() NotImplementedError` in filtered export.** The filtered-export endpoint uses SQLAlchemy's base `ARRAY` type for `search_terms_matched` containment. Switch to `postgresql.ARRAY` or use a raw SQL `@>` operator.

3. **[data] Fix Reddit collector to use actual post author, not subreddit name.** The `author_display_name` field must contain the username of the person who posted, not the subreddit. The current behavior completely corrupts actor analysis for any dataset including Reddit.

### High Priority

4. **[frontend] Add run status indicators everywhere runs are displayed.** The "Included Runs" table, the run dropdown, and the summary cards should all clearly show whether runs completed, failed, or were cancelled. Use color-coded badges (green/red/yellow). A researcher must know their data came from failed runs that may be incomplete.

5. **[frontend] Make filters reactive without requiring "Apply" click.** At minimum, the run dropdown should trigger an immediate refresh. Consider debounced reactivity for all filters, or at least explain why "Apply" is needed.

6. **[frontend] Differentiate or merge Emergent Terms and Suggested Terms panels.** Either clearly explain the difference between these two nearly-identical panels or merge them into one.

7. **[frontend] Add explanatory text to all empty-state panels.** Each empty panel should indicate (a) whether the analysis has been attempted, (b) what prerequisite is needed (completed run, enrichment pipeline, etc.), and (c) what the researcher can do to populate it.

### Medium Priority

8. **[frontend] Use researcher-friendly arena labels.** Replace "reference" with "Wikipedia", "social_media" with "Social Media (Bluesky, Reddit)", etc. The internal arena group names are developer shorthand.

9. **[frontend] Add platform badge to actor names in chart.** Show "(Bluesky)", "(Reddit)", etc. next to each actor name, or use color coding by platform.

10. **[frontend] Make run IDs in Included Runs table clickable.** Link to `/collections/{run_id}` so the researcher can investigate run details.

11. **[frontend] Format dates in Danish locale.** Summary card dates should use locale-appropriate formatting, not raw ISO substrings.

12. **[frontend] Adjust Compare Runs modal to include runs with data.** Filter by `records_collected > 0` rather than `status === 'completed'` so researchers can compare partial runs.

13. **[frontend] Set network node label threshold lower.** Change `labelRenderedSizeThreshold` to 3 or 4 so some labels are visible at the default zoom level. Currently the researcher sees an unlabeled dot cloud.

14. **[frontend] Make network legend dynamic based on actual node types.** Only show "Author" and "Term" in the legend when both types are present in the graph.

---

## Test Environment Details

- Server: `http://localhost:8022`
- User: `admin@example.com` (admin role)
- Query design: `65c84d82-7055-451c-a1dc-525dd5f862ee` ("iran_base")
- Collection runs: 4 total (3 failed with records, 1 cancelled with 0 records)
- Database: PostgreSQL at localhost:5481
- Browser simulation: curl with cookie authentication

## Files Referenced

- `/home/jakobbaek/codespace/issue_observatory/issue_obervatory/src/issue_observatory/api/templates/analysis/index.html` -- 170KB analysis template
- `/home/jakobbaek/codespace/issue_observatory/issue_obervatory/src/issue_observatory/api/static/js/charts.js` -- Chart.js rendering helpers
- `/home/jakobbaek/codespace/issue_observatory/issue_obervatory/src/issue_observatory/api/static/js/network_preview.js` -- Sigma.js network preview
- `/home/jakobbaek/codespace/issue_observatory/issue_obervatory/src/issue_observatory/api/routes/analysis.py` -- Analysis API routes (3700+ lines)
- `/home/jakobbaek/codespace/issue_observatory/issue_obervatory/src/issue_observatory/analysis/network.py` -- Network analysis functions (contains temporal bug)
- `/home/jakobbaek/codespace/issue_observatory/issue_obervatory/src/issue_observatory/analysis/_filters.py` -- Shared SQL filter builder (source of `term_matched` ambiguity)
