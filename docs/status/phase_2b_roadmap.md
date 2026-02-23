# Phase 2B Roadmap

**Created:** 2026-02-23
**Status:** Planning -- none of these items are implemented yet

This document captures planned improvements, feature requests, and known issues that fall outside the Phase 2A polish sweep. Items are organized by priority and grouped by theme. Each item notes whether it is a bug fix, UX improvement, or new feature.

---

## Priority Legend

- **P0 (Blocker):** Broken functionality that prevents normal use
- **P1 (High):** Major UX gap or frequently-encountered friction
- **P2 (Medium):** Improvement that would meaningfully help researchers
- **P3 (Low):** Nice-to-have polish or future capability

---

## 1. Broken Pages and Access Issues (P0)

### R-01: Credits page inaccessible

**Type:** Bug
**Reported:** User cannot access the Credits admin page.
**Root cause:** Likely a route registration issue, missing nav link, or permission gate rejecting non-admin users who should have access. The route at `/admin/credits` exists in `routes/credits.py` with two endpoints (balance + allocate).
**Action:** Investigate why the page returns an error. Check: (a) route mounting in `main.py`, (b) `require_admin` dependency, (c) nav link visibility conditions in `_partials/nav.html`.

### R-02: API Keys page inaccessible

**Type:** Bug
**Reported:** The credentials/API keys page at `/admin/credentials` cannot be accessed, though it worked in a previous version.
**Root cause:** Same category as R-01 -- likely a route registration regression or auth guard issue.
**Action:** Verify the scraper and credentials route groups are mounted. Check for import errors in the route modules that would silently prevent registration.

### R-03: Scraping Jobs page broken

**Type:** Bug
**Reported:** The Scraping Jobs page does not work.
**Root cause:** The scraper router (`scraper/router.py`) is fully implemented with CRUD + SSE streaming. The issue is likely in route mounting or the page template failing to load. A Phase 1 fix addressed the route registration but the page may still have frontend issues.
**Action:** Verify `scraper.router` is included in the app assembly. Test the page end-to-end.

### R-04: Collection detail page not working properly

**Type:** Bug
**Reported:** Clicking the details button for a single collection does not show useful information. The detail page does not seem to work properly.
**Root cause:** The detail page uses SSE for live updates. If the SSE endpoint fails or the run is in a broken state, the page may appear empty. Also, the page currently does not show per-platform record counts.
**Action:** (a) Fix any SSE connection failures for terminal-state runs. (b) Add per-platform record breakdown to the detail page (see R-12 below).

---

## 2. Stale Collection Cleanup (P0)

### R-05: Stale running collections cluttering dashboard

**Type:** UX / Operational
**Reported:** Dashboard shows many collections still marked as "running" that are clearly stale.
**Current state:** A `cleanup_stale_runs` Celery Beat task already exists. It runs every 10 minutes and marks runs as failed if: (a) started >24h ago, or (b) started >30min ago with no records, or (c) last record collected >30min ago.
**Root cause:** Either Celery Beat is not running, or the cleanup task is failing silently, or the timeouts are too generous for the user's workflow.
**Action:** (a) Verify Celery Beat is active and the `cleanup_stale_runs` task is firing. (b) Add a manual "Cancel stale runs" button on the admin health page or dashboard for immediate cleanup. (c) Consider reducing the idle timeout from 30 minutes to 15 minutes. (d) On the dashboard, visually distinguish "stuck" runs (running but no recent activity) from genuinely active ones.

---

## 3. Issue Project Concept (P1 -- New Feature)

### R-06: Issue Project as top-level organizational unit

**Type:** New feature
**Reported:** Collections, query designs, and analysis are currently flat lists. The user wants to group everything under an "issue project" (e.g., "Greenland Sovereignty Discourse", "Social Fraud in Denmark") that contains multiple query design versions and their collection runs.

**Current state:** No project concept exists. The hierarchy is: User -> Query Designs -> Collection Runs -> Content Records. Query designs can be cloned (IP2-051) but have no grouping.

**Design requirements:**
1. New `Project` model: `id`, `name`, `description`, `owner_id`, `visibility`, `created_at`, `updated_at`
2. `query_designs.project_id` FK (nullable for migration, required for new designs)
3. Project CRUD routes at `/projects/`
4. Project detail page showing all query designs and their runs
5. Filter content browser by project (via the query designs belonging to that project)
6. Filter collections list by project
7. Analysis should be launchable at the project level (aggregate across all runs in all designs within the project)
8. **Data sharing:** Multiple projects referencing the same content should not trigger re-collection. Content records are already linked to `collection_run_id`, not to projects, so this is naturally handled -- the same content can appear in runs across different projects.

**Implementation approach:**
- Phase 1: Model + migration + CRUD routes + nav entry
- Phase 2: Attach existing query designs to projects, update list/detail pages
- Phase 3: Project-level analysis aggregation, project-scoped content filtering

**Files affected:** `core/models/` (new model), `routes/` (new project routes), all list pages (add project filter/grouping), `analysis/` (project-level aggregation), nav template.

---

## 4. Content Browser Filters (P1)

### R-07: Content browser filters not working

**Type:** Bug
**Reported:** None of the content browser filters (arena, date range, language, search term, collection run) seem to work.
**Root cause:** The filter form uses `hx-trigger="change, keyup changed delay:400ms"` to fire HTMX requests to `GET /content/records`. The backend route may not be handling the filter parameters correctly, or the HTMX response may not be a valid fragment for `hx-swap="innerHTML"` on `#records-tbody`.
**Action:** (a) Test each filter parameter individually against the `/content/records` endpoint. (b) Verify the route handler parses all query params (arenas, date_from, date_to, language, search_term, run_id, mode, q). (c) Check browser console for HTMX errors or 4xx/5xx responses.

### R-08: Arena filter shows duplicates and empty categories

**Type:** Bug
**Reported:** The arena filter in the content browser shows "social media" multiple times and empty categories.
**Root cause:** The arena filter fetches from `/api/arenas/` which returns one entry per collector (keyed by `platform_name`). The parenthetical suffix shows `arena_name` (a grouping label like `social_media` shared by Bluesky, Reddit, TikTok, etc.). This creates visual clutter and confusion. The "empty categories" may be deferred stubs (Twitch, VKontakte) that have no `supported_tiers`.
**Action:** (a) The deferred stub filter (`supported_tiers.length > 0`) is already in `arenaFilter()` -- verify it works. (b) Remove the `arena_name` parenthetical from the content browser filter since it adds confusion. The content browser should show only `displayLabel` (e.g., "Bluesky", "Reddit") without the grouping label. (c) Alternatively, group the checkboxes by `arena_name` with a section header.

### R-09: Collection run filter uses meaningless names

**Type:** UX
**Reported:** The collection run dropdown shows names that the user has no relation to.
**Current state:** The dropdown shows `run.query_design_name (run.created_at truncated)`. If query designs are unnamed or if the user has many runs, this is unhelpful.
**Action:** (a) Show the query design name prominently, plus the date and record count: e.g., "Greenland Study (15 Feb, 423 records)" instead of just the name and truncated date. (b) Group runs by query design in the dropdown using `<optgroup>`. (c) When the Issue Project concept (R-06) is implemented, filter this dropdown by the active project.

---

## 5. Explore Page Improvements (P1)

### R-10: Many platforms return errors on the Explore page

**Type:** Bug
**Reported:** A lot of platforms on the Explore page do not work properly or return errors.
**Current state:** The Explore page (`explore/index.html`) POSTs to arena-specific collect endpoints. It filters to FREE tier arenas only. Errors may come from: (a) missing credentials for arenas that need them even on free tier, (b) rate limit exhaustion, (c) arenas that don't support the generic `collect/terms` endpoint pattern.
**Action:** (a) Add per-arena error messages that explain why a search failed (e.g., "Credentials not configured for this arena"). (b) Show a credential status indicator next to each arena in the selector. (c) Gracefully handle arenas that don't support term-based search (e.g., RSS Feeds, Wayback Machine) by hiding them from the Explore page or showing an explanatory message.

### R-11: Explore results are not explorable

**Type:** Bug / UX gap
**Reported:** Platforms that work show "X items found" without making them explorable.
**Current state:** The template does have an inline results table (title, author, published, engagement) and a modal detail view. If the user is seeing only a count, the results rendering may be failing due to unexpected response format from some arenas.
**Action:** (a) Verify the response format from each arena's collect endpoint matches `{"records": [...]}`. (b) Ensure the results table renders for all arena response shapes. (c) Add a fallback that shows raw JSON if structured rendering fails.

### R-12: Explore should support multi-platform search and term addition

**Type:** New feature
**Reported:** It should be possible to explore multiple platforms simultaneously and iteratively add discovered terms to an existing query design.
**Action:** (a) Add multi-select for platforms (checkboxes instead of radio buttons). (b) Fire parallel searches across selected platforms and merge results into a single table with a platform column. (c) Add an "Add to Query Design" button per result row and a bulk "Add selected terms" action. (d) Add a query design selector dropdown so the user can pick which design to add terms to. (e) Show a running list of "terms added this session" for the user's reference.

---

## 6. Analysis Page Redesign (P2)

### R-13: Analysis page feels superfluous

**Type:** UX
**Reported:** The Analysis page currently just links back to Collections where you navigate to analysis via a single collection.
**Current state:** The analysis landing (`analysis/landing.html`) lists query designs with their completed runs. Each run links to `/analysis/{run_id}`. There is also a "Cross-run analysis" link per design that goes to `/analysis/design/{design_id}`.
**Action:** (a) Make the analysis landing page more useful by showing summary stats (total records across all designs, top platforms, date range coverage) directly on the landing. (b) When Issue Projects (R-06) exist, organize analysis by project. (c) Add a "Quick analysis" mode that lets the user pick multiple runs and get a combined view without navigating through Collections first. (d) Add direct links to analysis from the dashboard and from query design detail pages (the latter already exists).

---

## 7. Actors Page Redesign (P2)

### R-14: Actors page should support large-scale snowball sampling workflows

**Type:** New feature / UX redesign
**Reported:** The Actors page should be geared towards much larger snowball sampling iterations. It should be possible to: (a) select all accounts from a single or multiple platforms belonging to a single issue project, (b) run network-based sampling or cross-platform link discovery, (c) save all discovered accounts for inspection, (d) selectively or bulk-add discoveries to the current collection.

**Current state:** The snowball sampling panel exists on the actors list page. It supports seed actor selection, platform checkboxes, depth slider, and bulk-add to actor list. But it operates on the flat actor list, not scoped to a project.

**Action:**
1. **Project scoping:** When Issue Projects (R-06) exist, scope the actor list to a project so seed selection is relevant.
2. **Platform-based selection:** Add "Select all actors with presence on [platform]" buttons above the seed actor list.
3. **Larger result sets:** Increase the default `max_actors_per_step` and add pagination to the results table. Currently capped at 20 per step.
4. **Discovery persistence:** Save all snowball discoveries to a "Pending Review" staging area (separate from the main actor list) so the researcher can review, filter, and selectively promote actors.
5. **Cross-platform link method:** The `SimilarityFinder` and `network_expander.py` (co-mention, Telegram forwarding) already exist in the backend. Expose these as additional discovery methods alongside snowball sampling on the UI, with clear explanations of each method.
6. **Bulk operations:** "Add all to actor list", "Add selected to actor list", "Ignore selected" actions on the discovery staging area.

---

## 8. Credential Management UX (P2)

### R-15: Tier selection on credential form is confusing

**Type:** UX
**Reported:** When adding credentials via the interface, it seems weird that the tier is chosen by the user. The tier should be inferred from the credential type being entered.
**Current state:** The credential form has a platform dropdown and a separate tier dropdown. The tier dropdown already disables unsupported tiers per platform, but the user still has to actively choose.
**Action:** (a) Auto-select the tier based on the platform selection. Most platforms have a single natural tier (e.g., YouTube API key = FREE, Serper.dev = MEDIUM, SerpAPI = PREMIUM). (b) For platforms with multiple tiers (e.g., Google Search supports both MEDIUM via Serper and PREMIUM via SerpAPI), use the credential type/key prefix to infer the tier, or show a brief explanation. (c) Consider hiding the tier selector entirely and auto-determining it, showing only a read-only badge: "This credential enables the Medium tier for Google Search."

---

## 9. Collection Detail Improvements (P2)

### R-16: Collection detail should show per-platform record counts

**Type:** New feature
**Reported:** When viewing a collection detail, it would be great to see overall stats such as number of records per platform collected so far, and output from what is being collected right now.
**Current state:** The detail page has an SSE-driven task table showing per-arena task status, but does not aggregate record counts per platform.
**Action:** (a) Add a summary card at the top showing total records, broken down by platform (e.g., "Bluesky: 142, Reddit: 89, GDELT: 312"). (b) Update the `run_summary.html` fragment to include per-platform counts. (c) For running collections, show a live-updating log or recent records preview (last 5 items collected).

---

## 10. Arenas Page Repositioning (P3)

### R-17: Arenas page has limited function

**Type:** UX
**Reported:** The Arenas page does not have much practical function and should perhaps be moved to a "Documentation" or "Guides" section.
**Current state:** `arenas/index.html` shows all arenas organized by tier with descriptions, credential status, and temporal capability. It is informational, not interactive.
**Action:** (a) Move the arenas overview to a "Documentation" or "Platform Guide" section in the nav. (b) Add useful context: link to each arena's research brief (`/docs/arenas/{platform}.md`), show rate limits and data freshness, explain what each platform is good for. (c) Alternatively, integrate the arena information into the query design editor and collection launcher where it is actionable, and demote the standalone page to a reference section.

---

## 11. Original Phase 2B Items (P2-P3)

These items were identified during the Phase 2A planning process.

### F1: Pre-launch collection summary panel (P2)

Show "You are about to collect from 8 arenas using 12 terms and 5 actors" before launching a collection.
**File:** `collections/launcher.html` + `routes/collections.py`
**Requires:** Counting active terms/actors for the selected query design server-side.

### F2: Breadcrumb navigation (P3)

Add `Dashboard > Collections > Run xyz` breadcrumbs to nested pages.
**File:** `_partials/breadcrumbs.html` (new partial), included from `base.html`
**Requires:** Passing `breadcrumbs` list to template context in each route.

### F4: Query design two-step creation explanation (P3)

Add inline help text on create page explaining "Create the design first, then add terms on the edit page."
**File:** `query_designs/editor.html`

### F5: Content browser collection run dropdown -- show record count (P2)

Show "Greenland Study (15 Feb, 423 records)" instead of "Greenland Study (2026-02-1...)".
**File:** `content/browser.html`, `routes/content.py` `_fetch_recent_runs()`

### A1: Entity resolution guidance (P3)

Add help text on the resolution page explaining when to merge vs. skip candidates.
**File:** `actors/resolution.html`

### A2: Mixed hash/name display unification (P3)

Content browser shows pseudonymized hashes, actor pages show names. Would require a cross-reference lookup or consistent display policy.

### A3: Snowball discovery method explanations (P2)

Add tooltips explaining what "Bluesky Follows", "Co-mention", "Telegram Forwarding" discovery methods mean.
**File:** `actors/list.html` snowball results section

### A4: Actor network visualization (P3)

In-browser force-directed graph of actor co-occurrence (IP2-042). Uses existing `static/js/network_preview.js` + Sigma.js.
**File:** `actors/detail.html` or `analysis/index.html` network tab

---

## Implementation Priority Order

| Priority | Items | Theme |
|----------|-------|-------|
| P0 | R-01, R-02, R-03, R-04, R-05 | Fix broken pages and stale runs |
| P1 | R-06, R-07, R-08, R-09, R-10, R-11, R-12 | Issue Projects + filter/explore fixes |
| P2 | R-13, R-14, R-15, R-16, F1, F5, A3 | Analysis/actor redesign + credential UX |
| P3 | R-17, F2, F4, A1, A2, A4 | Documentation + polish |

The P0 items should be investigated and fixed before any new feature work. The Issue Project concept (R-06) is the largest single item and is a dependency for several other improvements (R-09, R-13, R-14, R-17 all benefit from project scoping).
