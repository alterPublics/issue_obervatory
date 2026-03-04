# UX Evaluation: Design-Level Analysis Dashboard

Date: 2026-03-03
Evaluator: UX Tester (researcher perspective)
Feature evaluated: Conversion of analysis dashboard from run-level to design-level (cross-run) as default view

## Files Evaluated

- `/src/issue_observatory/api/templates/analysis/index.html` -- main analysis dashboard template (dual-mode)
- `/src/issue_observatory/api/templates/analysis/landing.html` -- analysis landing page
- `/src/issue_observatory/api/routes/analysis.py` -- route handlers including redirect logic
- `/src/issue_observatory/api/templates/_partials/nav.html` -- sidebar navigation
- `/src/issue_observatory/api/templates/collections/detail.html` -- collection detail (upstream link)
- `/src/issue_observatory/api/templates/collections/list.html` -- collections list (upstream link)
- `/src/issue_observatory/api/templates/query_designs/detail.html` -- query design detail (upstream link)

---

## PRAISE -- What works well

### P-1. Landing page is well-structured

The landing page (`landing.html`) groups runs by query design with clear visual hierarchy. Each design shows its run count, and individual runs display their top platforms, date ranges, and record counts. This gives the researcher a genuine overview before they dive in. The "View analysis" link per design and the per-run clickable rows provide two clean entry points depending on whether the researcher wants aggregated or run-scoped analysis.

### P-2. The redirect from legacy run URLs is smooth

When a researcher visits `/analysis/{run_id}` (the old URL pattern), the route handler correctly redirects to `/analysis/design/{design_id}?run_id={run_id}`. This preserves backward compatibility for bookmarks and links from the collections list and detail pages. The 302 redirect is the right status code. The fallback to a direct per-run render for orphaned runs (no query design) is a sensible edge case handler.

### P-3. Summary cards adapt intelligently to scope

The summary cards use conditional labels: "Completed runs" vs "Arenas", "Total credits" vs "Credits spent", and "Date range" shows either the first/last run dates or the published_at range depending on mode. This is good contextual adaptation -- the researcher sees design-level metrics when viewing the full design and run-level metrics when scoped to a single run.

### P-4. The "Viewing single run" badge provides clear scope feedback

When a run is pre-selected in design mode (via the `run_id` query parameter or the dropdown), a blue pill badge reading "Viewing single run" appears in the page header. This is a concise visual signal that the researcher is not looking at the full cross-run picture.

### P-5. Export URL construction is scope-aware

The `_buildExportUrl()` and `_gexfExportUrl()` JavaScript functions correctly pass `query_design_id` in design mode and `run_id` in run mode (or both when a specific run is selected within a design). The async export also handles this correctly, providing `query_design_id` when no run is selected. This means export scope matches what the researcher sees on screen.

### P-6. Empty states use mode-aware language

Empty state messages throughout the template use `{{ 'design' if mode == 'design' else 'run' }}` to say things like "No emergent terms data available for this design" rather than always saying "this run". This is a small but meaningful detail for comprehensibility.

### P-7. Query design detail page provides a clear entry point

The query design detail page shows a "Design-level analysis" link (purple badge) in the Run History section header, but only when there are completed runs. This is well-gated and discoverable from the right place in the researcher's workflow.

### P-8. URL bar updates when switching runs

The `$watch` on `filters.run_id` in the `analysisDashboard` Alpine component calls `history.replaceState` to add or remove the `run_id` query parameter. This means researchers can bookmark or share a URL that reflects their current scope, which is important for collaborative work and reproducibility.

---

## BLOCKERS -- Issues that prevent a researcher from completing their task

### B-1. Compare Runs modal is broken in design-mode cross-run view [frontend]

**What happens:** The researcher opens the design-level dashboard with no specific run selected (the default aggregated view). They click "Compare runs". The modal opens, but the baseline run reference (`currentRunId`) reads from `window.__analysisScope.runId`, which is an empty string when no run is selected.

**What the researcher sees:** The modal shows "Current run (baseline):" followed by an empty string truncated to 8 characters. The instructions say "Select another run from the same query design to compare metrics" -- but the comparison endpoint at `/analysis/compare?run_ids=,{selectedRunId}` will fail because the first UUID is empty.

**Research impact:** Cross-run comparison is a core use case for design-level analysis (comparing a batch run from last week to this week's run). The feature is prominently displayed but non-functional from the default design-level view. A researcher would need to first select a specific run in the dropdown to establish a "baseline", but there is no guidance about this requirement.

**Severity:** Blocker. The button is visible and clickable in the default state, but the action it initiates cannot succeed.

### B-2. "Add to query design" button on Emergent Terms still copies to clipboard [frontend]

**What happens:** In the Emergent Terms panel (lines 596-610), the "Add to query design" button actually calls `copyTerm(t.term)` which copies the term to the clipboard. The button label says "Add to query design" and the icon suggests addition, but the actual behavior is clipboard copy. The template comment explicitly acknowledges this: "Full integration... requires a backend endpoint and a design picker modal. For now this copies the term name to the clipboard."

**What the researcher sees:** They click "Add to query design" and nothing visually confirms the term was added to any design. A toast appears at the bottom-right, but it is a clipboard confirmation toast, not an "added to design" confirmation.

**Research impact:** The Suggested Terms panel (lines 1479-1558) has a working "Add to design" button that actually POSTs to the backend. Having two very similar panels on the same page with contradictory behavior -- one that genuinely adds and one that silently copies -- creates confusion and erodes trust. In design mode, the discrepancy is even more confusing because the researcher expects design-scoped operations to work.

**Severity:** Blocker. The button label actively misleads the researcher about what happens. This should either be fixed to actually add terms, or the button label should honestly say "Copy to clipboard" with a clipboard icon.

---

## FRICTION POINTS -- Things that work but create confusion or unnecessary effort

### F-1. "Reset" button does not reset the run selector [frontend]

**What happens:** In design mode, clicking "Reset" in the filter bar clears platform, arena, dates, and granularity back to defaults, but deliberately does not clear the Collection Run dropdown. The code comment says "Don't reset run_id in design mode -- it is a scope selector, not a filter."

**Why it's problematic:** From the researcher's perspective, "Reset" should return the page to its default state. If they selected a specific run and then applied some filters, "Reset" leaves them scoped to a single run with cleared sub-filters -- not returned to the cross-run view they started with. The distinction between "scope selector" and "filter" is an implementation concept, not a researcher concept. Every visible dropdown in the filter bar looks like a filter.

**Recommendation:** Either (a) reset the run selector too and have "Reset" truly return to the default cross-run view, or (b) visually separate the run selector from the filter bar (e.g. place it in the header area or with a divider) so the researcher can see that it is a different kind of control.

### F-2. Collection Run dropdown values are raw ISO timestamps [frontend]

**What happens:** The run dropdown at line 272 displays options like `2026-02-15T14:30:22 (847 records)`. The `r.started_at[:16]` slice produces an ISO 8601 fragment with the `T` separator, which is developer formatting, not human-readable.

**Why it's problematic:** The landing page shows formatted dates like "15 Feb 2026, 14:30" for the same runs. When the researcher gets to the dashboard, the same runs appear in a less readable format. This inconsistency undermines the polished feel of the landing page. More importantly, when a researcher has five or six runs, distinguishing between them by ISO timestamp alone is difficult. There is no mode label (batch/live) in the dropdown, unlike the landing page which shows this clearly.

**Recommendation:** Format run options consistently with the landing page: human-readable date + batch/live badge + record count. Consider adding run status if multiple failed runs exist.

### F-3. "Included Runs" table at the bottom is too far from the scope context [frontend]

**What happens:** The "Included Runs" table appears at the very bottom of the page, after the export section, suggested terms, and all chart panels. It lists all runs with truncated run IDs, raw ISO timestamps, and record counts.

**Why it's problematic:** By the time a researcher scrolls to the bottom to verify which runs are included in the analysis, they have already consumed all the charts and data. The table should serve as a reference for understanding the scope of what they are seeing. Placing it at the bottom means it functions more as an afterthought than as a scope definition. Additionally, the run IDs are 8-character hex fragments that are meaningless to researchers.

**Recommendation:** Move this table (or a condensed version of it) to appear directly below the filter bar and above the charts. Alternatively, make the run count badge in the header clickable to reveal a popover/dropdown showing the included runs. Replace hex fragments with formatted dates and batch/live labels.

### F-4. No explicit "All runs" scope indicator when no run is selected [frontend]

**What happens:** When the researcher is viewing the default cross-run analysis (no run selected), the page header shows the design name, a purple "N runs" badge, and a "View design" link. There is no explicit text or visual indicator that says "Showing aggregated data across all runs."

**Why it's problematic:** When a specific run IS selected, there is a clear "Viewing single run" badge. The absence of an analogous "Viewing all runs" indicator means the default state has weaker scope communication than the narrowed state. A first-time researcher looking at the dashboard cannot immediately confirm they are seeing cross-run aggregated data versus some default run.

**Recommendation:** Add a green or neutral badge that reads "All runs" or "Cross-run aggregate" in the same position where "Viewing single run" appears. This makes the scope explicit in both states.

### F-5. Summary card "Date range" is confusing in design mode [frontend]

**What happens:** In design mode, the Date Range summary card shows `first_run_at` to `last_completed_at` from the aggregate query. These are the dates when collection runs started and completed -- not the date range of the content itself.

**Why it's problematic:** A researcher interpreting "Date range" on an analysis dashboard would naturally expect this to show the temporal span of the collected content (earliest published_at to latest published_at). Instead, it shows when the collection infrastructure ran. If a batch collection in 2026 fetched articles from 2024-2025, the date range would show 2026 dates, which would confuse the researcher about what time period their data actually covers.

**The run-level summary (get_run_summary) returns `published_at_min` and `published_at_max`, which are the content dates.** The design-level summary returns `first_run_at` and `last_completed_at`, which are operational dates. The JavaScript tries to handle both: `(summary.first_run_at || summary.published_at_min || '').slice(0,10)` -- but this means in design mode, `first_run_at` takes precedence and the researcher always sees operational dates.

**Recommendation:** The design-level summary endpoint should also query `MIN(published_at)` and `MAX(published_at)` from `content_records` for the design, and the card should display content dates, not operational dates. The operational dates could be shown separately as "Collection period" if needed.

### F-6. The "Compare runs" button title is misleading in design-mode [frontend]

**What happens:** The Compare runs button has `title="Compare this run with another run"` (line 183). In design mode with no run selected, there is no "this run" to compare.

**Why it's problematic:** The tooltip assumes a run is selected. In the default cross-run view, this tooltip is incorrect and potentially confusing.

**Recommendation:** Make the tooltip context-aware: in design mode without a run selected, it should say "Select a run to compare" or disable the button entirely until a run is selected from the dropdown.

### F-7. Collection list and detail pages still link to old `/analysis/{run_id}` URL [frontend]

**What happens:** The collections list page (`list.html` line 199) shows "Analyse" linking to `/analysis/{run_id}`. The collection detail page (`detail.html` lines 334 and 374) shows "View suggested terms" and "Analyse Collected Data" linking to `/analysis/{run_id}`.

**Why it works but is friction:** These old URLs are redirected via the route handler to `/analysis/design/{design_id}?run_id={run_id}`, so the researcher does eventually land on the right page. However, the redirect causes a visible page flash (302 redirect), and the researcher sees their URL bar change to an unexpected URL. If they were trying to get a run-level view specifically, they instead land on a design-scoped view with that run pre-selected.

**Recommendation:** Update these templates to link directly to `/analysis/design/{design.id}?run_id={run.id}` where the design_id is available. This eliminates the redirect and makes the navigation feel direct. Keep the `/analysis/{run_id}` redirect for true bookmarks and external links.

### F-8. Platform/Arena filter dropdowns use raw database values [frontend]

**What happens:** The filter dropdowns for Platform and Arena are populated from `GET .../filter-options` which returns raw database strings like `rss_feeds`, `google_search`, `x_twitter`. These appear as-is in the dropdown.

**Why it's problematic:** The landing page applies `| replace('_', ' ') | capitalize` to platform names for readability. The filter dropdowns on the analysis dashboard do not apply any formatting. A researcher sees "rss_feeds" in the dropdown but "Rss feeds" on the landing page and the chart legends may use yet another format.

**Recommendation:** Apply consistent human-readable formatting to platform/arena names in the filter dropdowns, matching the treatment used elsewhere.

### F-9. Cross-platform actors table still references "this collection run" [frontend]

**What happens:** At line 1039-1040, the empty state for cross-platform actors says: "No cross-platform actors found. Entity resolution may not have been performed for this collection run." This text is static and does not adapt to design mode.

**Why it's problematic:** In design mode, the researcher is looking at data across all runs, not a single collection run. The message should say "this query design" in design mode, matching the pattern used elsewhere in the template.

**Recommendation:** Use the same mode-aware pattern: `this {{ 'design' if mode == 'design' else 'run' }}`.

### F-10. Export scope is not explicitly communicated [frontend]

**What happens:** The export panel shows "Export (up to 10 k records)" and "Export async (large dataset)" buttons. In design mode with no run selected, these export all records across all runs in the design. With a run selected, they export only that run's records. There is no text stating what scope the export covers.

**Why it's problematic:** A researcher about to export data for publication needs to know exactly what they are exporting. If they have five runs totaling 50,000 records and the sync export caps at 10,000, they need to understand whether those 10,000 come from all runs or just one. The "Apply additional filters" section mentions "Platform, arena, and date filters from the dashboard filter bar are also applied" which is helpful, but there is no mention of run scope.

**Recommendation:** Add a scope indicator line above the export buttons: "Exporting all data from [design name] (N runs)" or "Exporting data from run started [date]" depending on the current scope.

---

## SUGGESTIONS -- Minor improvements

### S-1. Landing page empty state could link to Query Designs, not just Collections [frontend]

**What happens:** When no collection runs exist, the empty state says "Run a collection first, then return here to analyse the results" with a "View Collections" button. But if the researcher has no query designs yet, they need to create one before they can collect.

**Recommendation:** Add a secondary link: "Or create a new query design to get started."

### S-2. Quick tip banner could be dismissable [frontend]

The blue "Click 'View analysis' to open the full dashboard" tip banner on the landing page is always shown. After the researcher has used the analysis page several times, it becomes noise.

**Recommendation:** Add an `x-data` dismiss button that stores the dismissal in localStorage.

### S-3. "Included Runs" table rows could be clickable to scope the dashboard [frontend]

Currently the runs table at the bottom is display-only. If a researcher sees a run with unexpected numbers and wants to investigate, they have to scroll back up to the filter bar and select it from the dropdown.

**Recommendation:** Make each row a clickable link or button that selects that run in the filter bar dropdown and scrolls to the top.

### S-4. The back arrow in design mode links to the query design, not the landing page [frontend]

In design mode, the back arrow (left chevron) links to `/query-designs/{design_id}`. This makes sense as a navigation path, but a researcher who arrived from the landing page (`/analysis`) might expect the back button to return them there.

**Recommendation:** This is defensible as-is, since the query design is the "parent" of the analysis view. No change required, but consider adding a breadcrumb trail: Analysis > [Design Name] > (optional: [Run date]).

### S-5. "Analyse" text on collection list uses British English inconsistently

The collection list page uses "Analyse" (British spelling) while the collection detail page uses "Analyse Collected Data" (also British). The landing page and dashboard use "analysis" (neutral). The codebase is in English but inconsistent on American/British variants.

**Recommendation:** Pick one spelling convention and apply it everywhere.

### S-6. The `search_terms_matched` array reference in term co-occurrence description uses developer jargon [frontend]

At line 795-797, the term co-occurrence description includes `<code>search_terms_matched</code>` which is a database column name. A researcher would not know what this refers to.

**Recommendation:** Replace with plain language: "...when they appear together in the same collected record."

---

## DATA QUALITY CONSIDERATIONS

### DQ-1. Design-level aggregation does not deduplicate across runs [data]

When a live tracking design has daily runs, the same content may be collected in consecutive runs. The design-level summary counts `SUM(records_collected)` from `collection_runs`, which would include cross-run duplicates. The charts query `content_records` directly and filter by `query_design_id`, which may or may not deduplicate depending on whether the dedup service ran cross-run.

**Research impact:** A researcher comparing "total records" on the summary card with the actual chart data points may see discrepancies. The summary card could overcount if duplicates exist across runs.

**Recommendation:** The design-level summary should either count distinct content records from `content_records` (matching what charts show), or clearly label the metric as "total collected (may include cross-run duplicates)."

### DQ-2. Design-level filter-options endpoint does not pass `run_id` when scoping [data]

The `design_filter_options` route (line 2804) accepts `run_id` and correctly scopes the query. But the JavaScript `init()` function in `analysisDashboard` calls `_buildAnalysisUrl('filter-options')` during initialization, which does include `run_id` if one is pre-selected. This means filter options are correctly scoped to the selected run.

However, when the researcher subsequently changes the run dropdown, the filter options are NOT refreshed. The platform and arena dropdowns continue showing options from the initial load. If the new run only collected from 3 arenas but the initial run had 8, the researcher sees stale options.

**Recommendation:** Re-fetch filter options when `filters.run_id` changes, or fetch once for the full design scope (no run_id) and keep those options stable regardless of run selection.

---

## DOCUMENTATION GAPS

### DOC-1. No documentation describes the design-level analysis feature

There is no mention in any user-facing guide of the design-level analysis concept. `docs/guides/what_data_is_collected.md` does not mention that analysis can span multiple runs. A researcher discovering this for the first time will rely entirely on in-page cues.

**Recommendation:** Add a section to the guide (or create a new `docs/guides/analysis_dashboard.md`) explaining: what cross-run analysis means, how to access it, what the run dropdown does, and how export scope works.

### DOC-2. Route docstrings still reference the old URL structure

The docstring at the top of `analysis.py` (lines 11-36) lists all endpoints under `GET /analysis/{run_id}/...`. The design-level endpoints (`GET /analysis/design/{design_id}/...`) are not documented in this header block. A developer reading the route file would not immediately understand the dual routing structure.

**Recommendation:** Update the module docstring to document both URL patterns.

---

## SUMMARY

The design-level analysis dashboard is a significant and well-conceived improvement to the researcher's workflow. The core architecture -- landing page grouped by design, design-scoped data fetching, URL-bar synchronization, and export scope awareness -- is sound. The implementation handles the dual design/run mode cleanly through a shared Alpine scope and URL builder.

The two blockers are both addressable: the Compare Runs modal needs a guard for the case when no run is selected (disable the button or prompt the researcher to select a baseline first), and the Emergent Terms "Add to query design" button needs either a real backend action or an honest label.

The friction points are clustered around scope communication: the researcher needs more explicit, consistent signals about whether they are viewing cross-run or single-run data, and the transitions between these states (especially via "Reset") should be more intuitive. The date range confusion in summary cards could undermine data trust if not addressed.

Overall, this is a well-executed transition that genuinely serves the research workflow of iterative collection and cumulative analysis. The issues identified are polish-level rather than architectural, with the exception of the two blockers.

### Priority ranking

| Priority | ID | Summary | Responsible |
|----------|-----|---------|-------------|
| 1 | B-1 | Compare Runs modal broken in default design-mode view | [frontend] |
| 2 | B-2 | Emergent Terms "Add to query design" misleadingly copies to clipboard | [frontend] |
| 3 | F-5 | Date range card shows operational dates, not content dates | [core] + [frontend] |
| 4 | F-1 | Reset button does not reset run selector | [frontend] |
| 5 | F-10 | Export scope not explicitly communicated | [frontend] |
| 6 | F-4 | No "All runs" scope indicator in default view | [frontend] |
| 7 | F-2 | Run dropdown uses raw ISO timestamps | [frontend] |
| 8 | DQ-1 | Design-level aggregation may double-count cross-run duplicates | [data] |
| 9 | F-7 | Collection pages still use redirect-triggering old URLs | [frontend] |
| 10 | F-3 | Included Runs table too far from scope context | [frontend] |
| 11 | F-6 | Compare button tooltip misleading without run selected | [frontend] |
| 12 | F-9 | Cross-platform actors empty state not mode-aware | [frontend] |
| 13 | F-8 | Platform/Arena filter dropdowns use raw database values | [frontend] |
| 14 | DQ-2 | Filter options not refreshed when run selection changes | [frontend] |
| 15 | S-6 | Developer jargon in term co-occurrence description | [frontend] |
| 16 | DOC-1 | No user-facing documentation for design-level analysis | [research] |
| 17 | DOC-2 | Route docstring does not cover design endpoints | [core] |
