# Fix Verification Report -- 2026-02-22

**Date:** 2026-02-22
**Tester:** UX Agent (research perspective)
**Application URL:** http://localhost:8000
**Authenticated as:** admin@example.com (admin role)

## Summary

Of the 5 critical fixes, **2 pass cleanly**, **1 passes with a regression**, and **2 still fail** (the original bug was not fully resolved or the fix introduced a new crash). Additionally, the routing fix for CRIT-01 introduced **3 significant regressions** affecting API endpoints and sub-routes.

| Fix | Verdict | Details |
|-----|---------|---------|
| CRIT-01: Route Priority Conflict | **PARTIAL PASS** | HTML detail pages now render, but priority_router wildcards break sub-routes and shadow JSON API detail endpoints |
| CRIT-02: Query Design Editor Crashes | **FAIL** | New error: `arenas_config` dict has no `global` key -- template crashes at line 1051 |
| CRIT-03: Analysis Dashboard Template Syntax Error | **PASS** | `{% raw %}...{% endraw %}` block correctly wraps JSDoc; page renders cleanly |
| CRIT-04: Codebook Schema Mismatch | **PASS** | Migration 016 adds `created_by` column; codebook page renders at 200 without errors |
| CRIT-05: Content Browser Pagination Crash | **PARTIAL PASS** | Cursor extraction no longer crashes, but paginated rows render with empty data (regression) |

---

## Detailed Findings

### CRIT-01: Route Priority Conflict

**Verdict: PARTIAL PASS -- original bug fixed, but regressions introduced**

**What was fixed:**
The `priority_router` approach successfully ensures that HTML detail pages are served before JSON API routers can intercept the request. Navigating to a query design detail, actor detail, or collection new/list pages now returns properly rendered HTML.

**Verified working:**
- `GET /query-designs` -- 200, HTML list page
- `GET /query-designs/{id}` -- 200, HTML detail page with real data (design name, clone button)
- `GET /query-designs/{id}/codebook` -- 200, HTML codebook page
- `GET /query-designs/new` -- 200, HTML editor
- `GET /collections` -- 200, HTML list page
- `GET /collections/new` -- 200, HTML launcher page
- `GET /actors` -- 200, HTML list page
- `GET /actors/{id}` -- 200, HTML detail page

**Regressions introduced:**

1. **[core] JSON API detail endpoints shadowed.** Because `priority_router` is registered before the JSON API routers (line 374 of `main.py`), ALL requests to `/query-designs/{id}`, `/collections/{run_id}`, and `/actors/{actor_id}` return HTML -- even when the caller sends `Accept: application/json`. A researcher writing a Python script against the API, or the frontend's own Alpine.js fetch calls that expect JSON, will receive HTML instead.

   - `GET /query-designs/305e03e5-...` with `Accept: application/json` -- returns HTML (should return JSON)
   - `GET /actors/f2c0b0bc-...` with `Accept: application/json` -- returns HTML (should return JSON)
   - `GET /collections/1cd78707-...` with `Accept: application/json` -- returns 500 (SearchTerm.created_at bug, see CRIT-01+collection detail bug below)

2. **[core] Sub-routes on `/actors/` broken.** The priority_router's wildcard `/actors/{actor_id}` (line 717 of `pages.py`) intercepts non-UUID paths that should route to the actors API router:

   - `GET /actors/resolution` -- 422 (UUID parse error: "resolution" treated as actor_id)
   - `GET /actors/search?q=test` -- 422 (UUID parse error: "search" treated as actor_id)
   - `GET /actors/resolution-candidates` -- likely 422 (same issue)
   - `GET /actors/sampling/snowball/platforms` -- likely 422 (same issue)
   - `POST /actors/sampling/snowball` -- likely 422 (same issue)

   **Research impact:** The entity resolution page (`/actors/resolution`) is completely inaccessible. The actor search endpoint, used by the snowball sampling UI, is broken. A researcher attempting actor discovery or entity resolution cannot proceed.

3. **[core] Sub-routes on `/collections/` broken.** Same wildcard issue with `/collections/{run_id}`:

   - `GET /collections/active-count` -- 422 (UUID parse error)
   - `GET /collections/volume-spikes` -- 422 (UUID parse error)
   - `GET /collections/volume-spikes/recent` -- 422 (UUID parse error)
   - `POST /collections/estimate` -- 422 (UUID parse error)

   **Research impact:** The dashboard's active collection count widget will fail. Volume spike alerts are inaccessible. Credit estimation before launching a collection will not work.

**Root cause:** The priority_router uses unguarded wildcard path parameters (`{actor_id}`, `{run_id}`) that match ANY string, not just UUIDs. FastAPI tries to parse the string as a UUID and fails with a 422. The fix needs either: (a) explicit literal routes for sub-paths added to priority_router before the wildcard, or (b) a content-negotiation approach where a single handler checks the Accept header and dispatches accordingly, or (c) moving HTML page routes to a different URL prefix (e.g., `/pages/...`).

---

### CRIT-02: Query Design Editor Crashes

**Verdict: FAIL -- original fix applied but new crash at different location**

**What was fixed:**
The edit page handler at line 370-389 of `pages.py` now correctly loads the full `QueryDesign` ORM object from the database with eager-loaded search terms. This fixes the original problem (passing only a string ID to the template).

**What still fails:**
The editor template (`query_designs/editor.html`, line 1051) accesses `design.arenas_config.global.languages` using Jinja2 attribute-style access. When `arenas_config` is an empty dict `{}` or does not contain a `global` key, Jinja2 raises `UndefinedError: 'dict object' has no attribute 'global'` and the page returns HTTP 500.

**Error observed:**
```
jinja2.exceptions.UndefinedError: 'dict object' has no attribute 'global'
```

**Location:** `editor.html` line 1051:
```html
x-data="languageSelector('{{ design_id }}', {{ (design.arenas_config.global.languages | default(['da'])) | tojson }})"
```

**Research impact:** A researcher cannot edit ANY query design. Clicking "Edit" on either of the two test designs (both returning 500) means the researcher is locked out of modifying search terms, arena configuration, language settings, or any other design parameter. This is a complete blocker for the query design workflow.

**Responsible agent:** `[frontend]` -- the template needs safe dict access (e.g., `design.arenas_config.get('global', {}).get('languages', ['da'])` or Jinja2 chained default filters).

---

### CRIT-03: Analysis Dashboard Template Syntax Error

**Verdict: PASS**

The `{% raw %}...{% endraw %}` block at lines 2254-2261 of `analysis/index.html` correctly prevents Jinja2 from interpreting the JSDoc `{{ nodes: Array, edges: Array }}` as template expressions.

**Verified:**
- `GET /analysis/` -- 200, HTML landing page renders
- `GET /analysis/{run_id}` -- 200, full analysis dashboard with Chart.js, network preview, and export panel renders correctly
- The JSDoc comment appears verbatim in the rendered HTML output, confirming the raw block works

No regressions observed.

---

### CRIT-04: Codebook Schema Mismatch

**Verdict: PASS**

Migration 016 (`alembic/versions/016_add_codebook_created_by.py`) correctly adds the `created_by` column with:
- `UUID` type matching `users.id`
- Foreign key constraint with `ON DELETE SET NULL`
- `nullable=True` (appropriate -- entries can exist without an assigned creator)
- B-tree index `idx_codebook_entry_created_by`

**Verified:**
- `GET /query-designs/{id}/codebook` -- 200, renders the codebook manager page with full Alpine.js CRUD interface
- No database errors in the response
- Template includes proper error handling UI (loading state, error display, empty state)
- Both test designs' codebook pages render successfully

No regressions observed.

---

### CRIT-05: Content Browser Pagination Crash

**Verdict: PARTIAL PASS -- cursor crash fixed, but paginated rows render empty**

**What was fixed:**
The cursor extraction at lines 820-829 of `content.py` now correctly extracts the ORM object from the RowMapping:
```python
last_ucr = last.get("UniversalContentRecord")
if last_ucr is not None:
    next_cursor = _encode_cursor(last_ucr.published_at, last_ucr.id)
```
This prevents the `dict-style access on Row object` crash that the original bug described.

**What still fails:**
The pagination endpoint (`GET /content/records?cursor=...`) returns rows with **empty data**. All record IDs, titles, text content, platforms, and dates are blank in the paginated response.

**Root cause:** At line 831, the function passes raw RowMapping objects to `_orm_row_to_template_dict()`:
```python
template_records = [_orm_row_to_template_dict(r) for r in records]
```

But `records` at line 815 contains RowMapping dicts with keys `"UniversalContentRecord"` (the ORM object) and `"mode"` (from the JOIN). The `_orm_row_to_template_dict()` function tries `row["published_at"]` which fails (KeyError, caught silently) and then `getattr(row, "published_at", None)` which returns `None` for a RowMapping.

**Compare with the initial page load** (lines 649-660) which correctly unpacks the ORM instance:
```python
for rrow in raw_rows:
    ucr_obj = rrow.get("UniversalContentRecord")
    ucr_obj._browse_mode = rrow.get("mode", "")
    records.append(ucr_obj)
```

The pagination endpoint is missing this unpacking step.

**Evidence:** The paginated HTML fragment contains:
```html
<tr id="record-row-"
    hx-get="/content/"
    @click="openDetail('')">
```
All values are empty strings where record IDs and data should appear.

**Research impact:** A researcher scrolling past the first 50 results in the content browser sees blank rows. They cannot access any content beyond the initial page. For a collection with hundreds or thousands of records, this means most collected data is effectively invisible.

**Responsible agent:** `[core]` -- the pagination handler needs the same ORM object unpacking that the initial page load uses.

---

## Regression Testing Results

### Navigation (sidebar links)

| Page | Status | Notes |
|------|--------|-------|
| `/dashboard` | 200 OK | Renders correctly |
| `/explore` | 200 OK | Renders correctly |
| `/arenas` | 200 OK | Renders correctly |
| `/query-designs` | 200 OK | Lists both test designs |
| `/query-designs/new` | 200 OK | Editor renders |
| `/collections` | 200 OK | Lists 3 collection runs |
| `/collections/new` | 200 OK | Launcher renders |
| `/content/` | 200 OK | Browser renders with 50 records |
| `/actors` | 200 OK | Lists 1 actor |
| `/analysis/` | 200 OK | Landing page renders |
| `/scraping-jobs` | 200 OK | |
| `/imports` | 200 OK | |
| `/admin/users` | 200 OK | |
| `/admin/credits` | 200 OK | |
| `/admin/credentials` | 200 OK | |
| `/admin/health` | 200 OK | |

### Detail pages

| Page | Status | Notes |
|------|--------|-------|
| `/query-designs/{id}` | 200 OK | Shows design name, description, clone button |
| `/query-designs/{id}/edit` | **500 ERROR** | `arenas_config.global` UndefinedError |
| `/query-designs/{id}/codebook` | 200 OK | Codebook manager renders |
| `/collections/{run_id}` | **500 ERROR** | `SearchTerm.created_at` AttributeError |
| `/actors/{actor_id}` | 200 OK | Actor detail renders |
| `/analysis/{run_id}` | 200 OK | Full dashboard with charts |

### API endpoints (JSON)

| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /query-designs/` | 200 JSON | Works correctly |
| `GET /query-designs/{id}` | **200 HTML** | Regression: returns HTML instead of JSON |
| `GET /collections/` | 200 JSON | Works correctly (list endpoint) |
| `GET /collections/{run_id}` | **500** | Crashes on SearchTerm.created_at |
| `GET /actors/` | 200 JSON | Works correctly |
| `GET /actors/{id}` | **200 HTML** | Regression: returns HTML instead of JSON |
| `GET /actors/resolution` | **422** | Regression: wildcard catches non-UUID path |
| `GET /actors/search` | **422** | Regression: wildcard catches non-UUID path |
| `GET /collections/active-count` | **422** | Regression: wildcard catches non-UUID path |
| `GET /collections/volume-spikes` | **422** | Regression: wildcard catches non-UUID path |
| `POST /collections/estimate` | **422** | Regression: wildcard catches non-UUID path |

### Content browser

| Action | Status | Notes |
|--------|--------|-------|
| Initial page load | 200 OK | 50 records displayed with data |
| Pagination (cursor) | **200 but empty rows** | Records render as blank rows |
| Content detail panel | Not tested (requires browser JS) | |

---

## Summary of Outstanding Issues

### Blockers (prevent researcher from completing task)

1. **Query design editor crashes (CRIT-02 still broken).** Every query design edit attempt returns 500. The `arenas_config.global.languages` access path is unsafe when `arenas_config` lacks a `global` key.
   - **File:** `/src/issue_observatory/api/templates/query_designs/editor.html`, line 1051
   - **Responsible agent:** `[frontend]`

2. **Collection detail page crashes (new bug in CRIT-01 fix).** `SearchTerm.created_at` does not exist; the correct attribute is `SearchTerm.added_at`.
   - **File:** `/src/issue_observatory/api/routes/pages.py`, line 560
   - **Responsible agent:** `[core]`

3. **Entity resolution page inaccessible (CRIT-01 regression).** `/actors/resolution` caught by wildcard `{actor_id}` in priority_router.
   - **File:** `/src/issue_observatory/api/routes/pages.py`, line 717 (needs guard) or `/src/issue_observatory/api/main.py`, line 374 (router registration order)
   - **Responsible agent:** `[core]`

4. **Actor search broken (CRIT-01 regression).** `/actors/search` caught by same wildcard.
   - **Responsible agent:** `[core]`

5. **Collection sub-routes broken (CRIT-01 regression).** `/collections/active-count`, `/collections/estimate`, `/collections/volume-spikes` all caught by wildcard `{run_id}`.
   - **Responsible agent:** `[core]`

### Friction Points (work but confusing or degraded)

6. **Content browser pagination shows blank rows (CRIT-05 regression).** Pagination endpoint returns HTML fragments with empty record data. Researcher sees blank table rows after scrolling past first page.
   - **File:** `/src/issue_observatory/api/routes/content.py`, around line 831 (needs ORM unpacking like lines 652-660)
   - **Responsible agent:** `[core]`

7. **JSON API detail endpoints return HTML (CRIT-01 regression).** Programmatic access to `/query-designs/{id}`, `/actors/{id}` returns HTML instead of JSON.
   - **Responsible agent:** `[core]`

---

## Recommendations (prioritized)

1. **[core] Fix the wildcard route conflicts in priority_router.** The most impactful single change. Either: (a) add explicit literal routes to priority_router for all sub-paths (`/actors/resolution`, `/actors/search`, `/collections/active-count`, `/collections/estimate`, `/collections/volume-spikes`, `/collections/volume-spikes/recent`) BEFORE the wildcard routes; or (b) use content negotiation in the handlers to check `Accept` header and delegate accordingly; or (c) constrain the path parameter type in FastAPI (e.g., `run_id: uuid.UUID` will still catch strings, but you can add a regex constraint).

2. **[core] Fix `SearchTerm.created_at` to `SearchTerm.added_at`** in `/src/issue_observatory/api/routes/pages.py` line 560. Single-line fix that unblocks the collection detail page.

3. **[frontend] Fix `arenas_config.global.languages` template access** in `/src/issue_observatory/api/templates/query_designs/editor.html` line 1051. Use Jinja2 safe access pattern, e.g.:
   ```
   {{ ((design.arenas_config or {}).get('global', {}).get('languages', ['da'])) | tojson }}
   ```
   This unblocks the query design editor.

4. **[core] Add ORM object unpacking to pagination endpoint** in `/src/issue_observatory/api/routes/content.py` around line 815-831. Apply the same extraction logic used in lines 649-660 so paginated rows contain actual record data.

5. **[core] Consider a unified routing strategy** rather than the dual priority_router/router approach. The current approach is fragile: every new sub-route on `/actors/`, `/collections/`, or `/query-designs/` will need to be manually added to priority_router to avoid being swallowed by the wildcard. A content-negotiation middleware or a separate `/api/` prefix for JSON endpoints would be more maintainable.
