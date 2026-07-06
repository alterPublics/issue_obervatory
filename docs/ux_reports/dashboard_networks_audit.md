# UX Audit Report -- Dashboard & Networks Restructuring

Date: 2026-03-14
Scope: Phases 0-5 restructuring (terminology standardization, dashboard overhaul, nav changes, networks backend/frontend, analysis retirement)
Tested against: http://localhost:8022 (authenticated as admin)

---

## BLOCKERS

### B1. Dashboard and Networks JavaScript never executes [frontend]

**Severity:** BLOCKER -- both pages are non-functional

Both `dashboard/index.html` and `networks/index.html` place their Alpine.js component definitions inside `{% block scripts %}`. The base template (`base.html`) does not define a `{% block scripts %}` block. Jinja2 silently discards content in undefined blocks.

The base template defines only three blocks: `title`, `extra_head`, and `content`.

**Impact:** The `dashboardAnalytics()` and `networksDashboard()` functions never appear in the rendered HTML. This means:
- Dashboard: no charts render, no project selector works, no date range presets, no export buttons
- Networks: no filter options load, "Build Network" does nothing, no GEXF export

The researcher sees static HTML with empty chart canvases and unresponsive controls.

**Files:**
- `src/issue_observatory/api/templates/base.html` -- missing `{% block scripts %}` definition
- `src/issue_observatory/api/templates/dashboard/index.html` line 290 -- uses `{% block scripts %}`
- `src/issue_observatory/api/templates/networks/index.html` line 265 -- uses `{% block scripts %}`

**Fix:** Either add `{% block scripts %}{% endblock %}` before `</body>` in `base.html`, or move the script content into `{% block content %}` or `{% block extra_head %}` following the pattern used by all other templates in the codebase.

---

### B2. Networks API endpoints crash with wrong argument order [core]

**Severity:** BLOCKER -- all three network API endpoints return 500 errors when project_id is provided

The function `resolve_design_ids()` in `networks.py` has the signature:

    resolve_design_ids(db, project_id, explicit_ids, user_id)

But all three call sites pass arguments in a different order:

    resolve_design_ids(db, current_user.id, project_id, query_design_ids)

This passes `current_user.id` (a UUID) as `project_id`, `project_id` (UUID or None) as `explicit_ids` (expects `list[str]`), and `query_design_ids` (a string or None) as `user_id` (expects UUID).

**Impact:** Any request to `/networks/keyword-network`, `/networks/entity-network`, or `/networks/export-gexf` that includes a `project_id` parameter crashes with a 500 error. Without `project_id`, the function returns `None` for `design_ids`, which produces empty results rather than a crash -- but also means the researcher gets no data.

**Files:**
- `src/issue_observatory/api/routes/networks.py` lines 157-159, 258-260, 487-489

**Fix:** Change all three call sites to:

    resolve_design_ids(db, project_id, parse_csv_param(query_design_ids), current_user.id)

Note that `query_design_ids` is a string, but `explicit_ids` expects `list[str]` -- it must be parsed first.

---

### B3. Networks page missing Sigma.js and graphology CDN dependencies [frontend]

**Severity:** BLOCKER -- network visualization cannot render even if JS executed

The networks template does not load the Sigma.js, graphology, or graphology-library CDN scripts that `network_preview.js` requires. These are loaded via `{% block extra_head %}` in `analysis/index.html` and `actors/detail.html`, but the networks page has no such block.

Additionally, `network_preview.js` itself is not loaded on the networks page.

**Impact:** Even if B1 were fixed, `window.initNetworkPreview()` would be undefined, and `window.Graph`, `window.Sigma`, `window.graphologyLayout`, and `window.graphologyLayoutForceAtlas2` would all be missing. The network visualization canvas would remain empty.

**Files:**
- `src/issue_observatory/api/templates/networks/index.html` -- missing CDN script tags and `network_preview.js` include
- Compare with `src/issue_observatory/api/templates/analysis/index.html` lines 20-41 for the required includes

---

### B4. Dashboard uses undefined CSS classes [frontend]

**Severity:** BLOCKER -- dashboard visual layout is broken

The dashboard template uses `.card`, `.btn-primary`, and `.btn-secondary` CSS classes. These are defined in `input.css` using Tailwind's `@apply` directive, which only works when compiled via `npx tailwindcss`. The compiled `app.css` does not contain these classes (intentionally -- it only holds non-utility rules). The Tailwind CDN play script loaded in `base.html` cannot process `@apply` from external CSS files.

No other template in the codebase uses these classes -- all existing templates use inline Tailwind utility classes directly.

**Impact:** All card containers on the dashboard render as plain unstyled `<div>` elements (no background, no border, no padding, no border-radius, no shadow). The "New Query Design" and "New Collection" buttons are unstyled. The page looks broken.

The networks template also uses `.card` (5 occurrences) with the same problem.

**Files:**
- `src/issue_observatory/api/templates/dashboard/index.html` -- 10 uses of `.card`, 1 use each of `.btn-primary` and `.btn-secondary`
- `src/issue_observatory/api/templates/networks/index.html` -- 5 uses of `.card`
- `src/issue_observatory/api/static/css/input.css` lines 22-40, 63-65 -- class definitions using `@apply`
- `src/issue_observatory/api/static/css/app.css` -- 43 lines, does not contain these classes

**Fix:** Either (a) replace `.card`, `.btn-primary`, `.btn-secondary` with inline Tailwind utilities matching the patterns used elsewhere in the codebase, or (b) run `make css` to compile `input.css` into `app.css` and ensure the build output includes these classes.

---

## MAJOR ISSUES

### M1. Arena category data inconsistency after Phase 0 migration [data]

**Severity:** MAJOR -- dashboard shows stale arena categories, filter-options mismatch

The `/dashboard/volume` endpoint returns arena values including `"reference"` and `"news_media"` which are old category names that predate the Phase 0 standardization to four categories (`news`, `search`, `web`, `social_media`). This means the database migration did not update all existing content records.

Observed distinct arena values in volume data: `google_autocomplete`, `google_search`, `news_media`, `reference`, `social_media`.

The filter-options endpoint only shows categories that match the four canonical values, so records with `news_media` or `reference` arena values are invisible to the category filter. Meanwhile, `google_autocomplete` and `google_search` are platform names being used as arena values, which is a different field.

**Impact:** A researcher filtering by "News" will miss content records tagged with the old `news_media` arena value. Records with `reference` arena value are completely unfilterable. Volume chart legends show inconsistent naming.

**Files:**
- `alembic/versions/033_standardize_arena_categories.py` -- migration may not have updated all records
- `src/issue_observatory/arenas/categories.py` -- canonical mapping does not include `reference` or `news_media`
- `src/issue_observatory/analysis/descriptive.py` -- the `get_volume_with_deltas` function groups by `arena` column

---

### M2. Analysis links throughout the app now dead-end at dashboard [frontend]

**Severity:** MAJOR -- researcher loses context navigating from collections to analysis

Multiple templates still contain links to `/analysis/{run_id}` and `/analysis/design/{design_id}`:
- `collections/detail.html` -- "View Analysis" button (lines 334, 374)
- `collections/list.html` -- per-run analysis link (line 199)
- `projects/detail.html` -- project analysis link (line 63)
- `query_designs/detail.html` -- design analysis link (line 429)
- `collections/project_detail.html` -- project analysis link (line 208)

All of these now redirect to `/dashboard` with no explanation and no context about which run/design the researcher was trying to analyze.

**Impact:** A researcher completing a collection run clicks "View Analysis" and is silently redirected to the generic dashboard. They have no way to understand that the per-run analysis page was removed, where their analysis went, or how to access the equivalent functionality via the new dashboard or networks pages.

---

### M3. Dashboard filter-options returns incorrect arena_categories structure [core]

**Severity:** MAJOR -- dashboard Alpine.js code expects strings, API returns objects

The `/dashboard/filter-options` endpoint returns arena_categories as a list of objects: `[{"value": "social_media", "label": "Social Media"}]`.

The dashboard Alpine.js component (if it were executing -- see B1) iterates over `arenaCategories` with:

    <template x-for="cat in arenaCategories" :key="cat">
        <option :value="cat" x-text="categoryLabels[cat] || cat"></option>
    </template>

This code treats each item as a plain string. But the API returns objects with `value` and `label` keys. The `<option>` values would be `[object Object]` and the category labels would not display correctly.

**Files:**
- `src/issue_observatory/api/routes/dashboard.py` lines 599-604 -- returns `{"value": k, "label": v}`
- `src/issue_observatory/api/templates/dashboard/index.html` lines 151-153 -- expects string values

**Fix:** Either change the API to return a flat list of strings, or change the template to use `cat.value` and `cat.label`.

---

## MINOR ISSUES

### m1. `/explore` route still accessible [frontend]

The `/explore` route still returns 200 even though "Explore" was removed from the navigation. The route should either be removed or redirect to an appropriate destination.

---

### m2. Networks page graph mode dropdown has hardcoded unipartite values [frontend]

The graph mode dropdown (line 156 of networks/index.html) includes a dynamic option:

    <option :value="networkType === 'keyword' ? 'unipartite_keyword' : 'unipartite_entity'" ...>

But the `mode` parameter passed to the API is set directly from `graphMode`. If the researcher selects "Collapse keywords" then switches `networkType` to "entity", the stored `graphMode` value (`unipartite_keyword`) becomes invalid for entity networks. No validation or reset occurs.

---

### m3. Dashboard "Records Collected" card uses raw fetch instead of HTMX [frontend]

The "Records Collected" card uses an Alpine.js component with `fetch('/content/count')` while the "Credits" and "Active Collections" cards use HTMX `hx-get`. This inconsistency means the Records card does not benefit from HTMX boost navigation (cookie refresh, error handling), though it does function correctly.

---

### m4. Networks page legend colors may not match Sigma.js rendering [frontend]

The legend hardcodes node type colors (`#7C3AED` for Sender, `#D4C020` for Keyword, etc.) but the `_resolveNodeType()` function maps `'sender'` to `'actor'` and `'keyword'`/`'entity'` to `'term'`. The `network_preview.js` uses `COLOR_ACTOR` for `'actor'` type and `COLOR_TERM` for `'term'` type. For entity networks, all entity nodes get mapped to `'term'` type (line 404: `if (node.node_type === 'entity') return 'term'`), so they would all render as `COLOR_TERM` (#D4C020) -- but the legend shows separate colors for PERSON, ORG, and GPE/LOC. The legend is misleading.

---

### m5. Dashboard volume chart may not handle multi-arena stacking correctly [frontend]

The `initMultiArenaVolumeChart` function in `charts.js` expects `arenaNames` for creating stacked datasets. The volume API returns arena values as keys in the `arenas` dict, but these include a mix of old category names (`news_media`, `reference`) and platform names (`google_search`, `google_autocomplete`) alongside new categories (`social_media`). If the chart were rendering (blocked by B1), the legend would show these inconsistent labels.

---

## PASSED

1. **Navigation structure:** "Explore" has been correctly removed from the sidebar navigation. "Networks" appears correctly in the primary navigation list. All nav links point to valid routes.

2. **Analysis JSON endpoints preserved:** `/analysis/{run_id}/volume`, `/analysis/{run_id}/summary`, and other JSON API endpoints continue to work correctly, returning valid data. Only the HTML routes redirect.

3. **Analysis HTML redirects work:** `/analysis/` redirects to `/dashboard` (302). `/analysis/{run_id}` redirects to `/dashboard` (302). The redirects are functional even if the UX of losing context is problematic (see M2).

4. **Dashboard API endpoints functional:**
   - `GET /dashboard/projects` -- returns valid JSON with project list, run timestamps, design counts (200)
   - `GET /dashboard/volume` -- returns time-series data with arena breakdowns (200)
   - `GET /dashboard/actors` -- returns top actors with counts and engagement (200)
   - `GET /dashboard/terms` -- returns top search terms with counts (200)
   - `GET /dashboard/filter-options` -- returns arena categories and platforms (200)
   - `GET /dashboard/export?format=csv` -- returns valid CSV with proper headers and Danish characters (200)

5. **Networks filter-options endpoint functional:** `GET /networks/filter-options` returns projects, query designs, search terms, arena categories, and platforms correctly.

6. **Dashboard page loads:** The HTML is served with 200 status and 39KB of content. The static structure (headings, labels, layout skeleton) is present.

7. **Networks page loads:** The HTML is served with 200 status and 37KB of content.

8. **Authentication flow:** Login with admin credentials works. Cookie-based JWT authentication properly gates all tested endpoints.

9. **Dashboard export preserves Danish characters:** The CSV export from `/dashboard/export` correctly preserves Danish characters (verified: "LDRE SKAL IKKE DO AF UNDERERNAERING" with proper AE/O/AA).

10. **HTMX partial endpoints:** `/credits/balance` and `/collections/active-count` return proper HTMX-compatible HTML fragments that the dashboard summary cards can consume.

---

## RECOMMENDATIONS (prioritized)

1. **[frontend] CRITICAL: Add `{% block scripts %}{% endblock %}` to base.html** before `</body>`, immediately above the session expiry script. This unblocks both dashboard and networks pages. Alternatively, move the JS into `{% block extra_head %}` following the existing template pattern.

2. **[core] CRITICAL: Fix `resolve_design_ids` argument order** in `networks.py` at all three call sites (lines 157-159, 258-260, 487-489). Change from `(db, current_user.id, project_id, query_design_ids)` to `(db, project_id, parse_csv_param(query_design_ids), current_user.id)`.

3. **[frontend] CRITICAL: Add Sigma.js/graphology CDN includes and network_preview.js** to the networks template, either via `{% block extra_head %}` or at the top of the content block. Copy the pattern from `analysis/index.html` lines 20-41.

4. **[frontend] CRITICAL: Replace `.card`, `.btn-primary`, `.btn-secondary`** in dashboard and networks templates with inline Tailwind utility classes. Use the equivalent: `bg-white rounded-lg shadow-brand p-6 border border-purple-100/60` for cards.

5. **[data] HIGH: Run a data migration** to update all existing `content_records` with old `arena` values (`news_media`, `reference`, etc.) to the new canonical four categories. Verify the Phase 0 migration covered all records.

6. **[frontend] HIGH: Update stale `/analysis/` links** in collections/detail.html, collections/list.html, projects/detail.html, query_designs/detail.html, and collections/project_detail.html. Either point to `/dashboard?project_id=X` with context, or remove the links and replace with links to the networks page.

7. **[core] MEDIUM: Fix dashboard filter-options response format** to match what the Alpine.js template expects. Either return flat strings or update the template to use `.value`/`.label` accessors.

8. **[frontend] LOW: Remove or redirect the `/explore` route** since it was removed from navigation.

9. **[frontend] LOW: Fix networks legend color mapping** to accurately reflect how `_resolveNodeType()` maps node types to colors in network_preview.js.
