# Sidebar Section-by-Section UI Audit

Date: 2026-02-22
Tested against: http://localhost:8000 (uvicorn, authenticated as admin@example.com)
Application config: `redirect_slashes=False` in FastAPI

---

## Executive Summary

**4 sidebar sections are completely broken (BLOCKER)**:
- Collections (`/collections`) -- 500 Internal Server Error
- Content (`/content`) -- 404 Not Found
- Actors (`/actors`) -- 422 Unprocessable Entity
- Analysis (`/analysis`) -- 404 Not Found

**2 critical sub-pages are inaccessible**:
- Create Query Design (`/query-designs/new`) -- 422 UUID parsing error
- Launch Collection (`/collections/new`) -- 422 UUID parsing error

**The Explore page arena selector silently fails** (no arenas load, no error shown).

**The Import Data upload form submits to a non-existent endpoint**.

A researcher clicking through the sidebar would find that 4 of 8 primary navigation items are non-functional, and the two most important "create" actions (new query design, new collection) are broken. The application is not usable for any research workflow in its current state.

---

## Section-by-Section Results

### 1. Dashboard (`/dashboard`) -- HTTP 200 OK

The page loads successfully. However, it contains links that lead to broken pages:

| Link/Element | Target | Status | Issue |
|---|---|---|---|
| "Create a new query design" button | `/query-designs/new` | **422** | UUID parsing error |
| "Launch a collection" button | `/collections/new` | **422** | UUID parsing error |
| "View all content" link | `/content` | **404** | Missing trailing slash |
| "View analysis" link | `/analysis` | **404** | Missing trailing slash |
| "View all collections" link | `/collections` | **500** | `format_number` filter error |
| HTMX: recent collections widget | `/collections?limit=5&format=fragment` | **500** | Same `format_number` error |
| HTMX: credit badge | `/credits/balance` | 200 | Works |
| HTMX: active collections count | `/collections/active-count` | 200 | Works |
| HTMX: volume spike alerts | `/collections/volume-spikes/recent?days=7&limit=5` | 200 | Works |

**Researcher experience**: The dashboard loads and shows summary stats, but every action link leads to an error. A researcher cannot proceed from the dashboard to any productive workflow.

**Responsible agent**: `[core]` for route ordering; `[frontend]` for `format_number` filter registration.

---

### 2. Explore (`/explore`) -- HTTP 200 OK

The page loads but the arena selector **never populates**. The JavaScript fetches `/api/arenas/` (which returns a flat JSON array `[{...}, {...}]`) but then references `data.arenas.filter(...)`, treating the response as an object with an `.arenas` property. Since `undefined.filter()` throws, the arena list stays empty with "Loading arenas..." shown indefinitely.

The "Create Query Design from This Term" button links to `/query-designs/new` which returns 422.

| Issue | Detail |
|---|---|
| Arena selector empty | `data.arenas` should be `data` (response is an array, not `{arenas: [...]}`) |
| Create QD button broken | Links to `/query-designs/new` which gets caught by `/{design_id}` route |

**Researcher experience**: The explore page appears to load but the arena selector shows "Loading arenas..." forever. The researcher has no indication of what went wrong and no path forward.

**Responsible agent**: `[frontend]` for the `data.arenas` vs `data` mismatch in `explore/index.html` line 222.

---

### 3. Arenas (`/arenas`) -- HTTP 200 OK

The page loads correctly. The Alpine.js component properly treats the `/api/arenas/` response as an array. All 25 arenas are displayed with their tier information, descriptions, and credential status.

No broken links detected. This is one of the cleanest pages in the application.

**Researcher experience**: Works well. The researcher can browse all available data collection platforms.

---

### 4. Query Designs (`/query-designs`) -- HTTP 200 OK

The list page loads correctly. However:

| Link/Element | Target | Status | Issue |
|---|---|---|---|
| "Create new query design" button | `/query-designs/new` | **422** | Caught by API `/{design_id}` route |
| "New Query Design" button in header | `/query-designs/new` | **422** | Same issue |

**Root cause**: The API router `query_designs.router` is mounted at `/query-designs` prefix (main.py line 372) and includes a `GET /{design_id}` endpoint. The pages router (main.py line 388) defines `GET /query-designs/new`. Because the API router is included first, `GET /query-designs/new` is matched by `GET /query-designs/{design_id}` with `design_id="new"`, which fails UUID validation with a 422 error.

This is a **route ordering conflict**. The same issue affects `/query-designs/{design_id}/edit` and `/query-designs/{design_id}/codebook` (though those use UUID path params so they collide differently).

**Researcher experience**: Can see existing query designs but cannot create a new one. Complete blocker for the primary workflow.

**Responsible agent**: `[core]` for route registration order in main.py.

---

### 5. Collections (`/collections`) -- HTTP 500 Internal Server Error

The page fails with a Jinja2 template compilation error:

```
jinja2.exceptions.TemplateAssertionError: No filter named 'format_number'.
File: collections/list.html, line 100
Template code: {{ run.records_collected | default(0) | int | format_number }}
```

The `format_number` filter is used in the template but was never registered on the Jinja2 environment. The `templates` object is created at module level in `main.py` line 481 as a bare `Jinja2Templates(directory=...)` with no custom filter registration.

The same error affects `GET /collections?limit=5&format=fragment` (the HTMX fragment request from the dashboard).

**Sub-pages also broken**:
- `/collections/new` -- **422** (same route ordering issue as query designs: `new` is parsed as a `{run_id}` UUID)
- Any `/collections/{run_id}` detail page -- Would work IF the collections list page worked (the route exists and the template is different)

**Researcher experience**: Clicking "Collections" in the sidebar shows a raw error page with a Python stack trace. The researcher sees internal implementation details and has no way to view, launch, or manage collections.

**Responsible agent**: `[frontend]` for registering the `format_number` Jinja2 filter; `[core]` for route ordering.

---

### 6. Content (`/content`) -- HTTP 404 Not Found

The sidebar links to `/content` (no trailing slash). Because `redirect_slashes=False` is set in main.py line 91, `/content` and `/content/` are treated as different routes. The content browser route is `GET /` on the content router, which becomes `/content/` with the prefix. There is no route for `/content` without trailing slash (the pages.py file has a comment saying the content browser is served by content.py, but content.py only mounts at `GET /content/`).

**Workaround**: `/content/` (with trailing slash) returns 200 and works correctly. But the sidebar links to `/content` which 404s.

**Sub-endpoints**:
- `/content/records` -- 200 (HTMX cursor pagination)
- `/content/search-terms` -- 200
- `/content/export` -- Would work with correct params
- `/content/discovered-links` -- 200 (pages.py handles this correctly)
- `/content/{uuid}` -- 200 (record detail)
- `/content/discovered` -- **422** (linked from collection detail template, caught by `/{record_id}` as UUID; correct URL is `/content/discovered-links`)

**Researcher experience**: Clicking "Content" in the sidebar shows a JSON `{"detail":"Not Found"}` response. The researcher has no idea why the page doesn't load.

**Responsible agent**: `[core]` for the trailing slash mismatch; `[frontend]` for the wrong link in `collections/detail.html` (should be `/content/discovered-links` not `/content/discovered`).

---

### 7. Actors (`/actors`) -- HTTP 422 Unprocessable Entity

The page fails with:
```json
{"detail":[{"type":"missing","loc":["query","pagination"],"msg":"Field required","input":null}]}
```

**Root cause**: The `actors_list` function in `pages.py` (line 524) declares a dependency `pagination: Annotated[PaginationParams, Depends(get_pagination)]`, but `PaginationParams` and `get_pagination` are **not imported** at the top of `pages.py`. Because of `from __future__ import annotations`, Python doesn't fail at import time. FastAPI fails at request time when trying to resolve the forward-referenced type.

Additionally, the `actors_detail` function (line 579) uses `HTTPException`, `func`, and `UniversalContentRecord` which are also not imported.

**Sub-pages**:
- `/actors/resolution` -- **200** (this route is on the actors API router, not pages.py, and works correctly)
- `/actors/search?q=test` -- **200** (works correctly, on the actors API router)
- `/actors/{actor_id}` (HTML detail) -- **Never accessible**: the API router's `GET /{actor_id}` (returns JSON) is matched before the pages router's HTML version. A researcher clicking an actor name from the list would get JSON, not the detail HTML page.

**Researcher experience**: Clicking "Actors" in the sidebar shows a JSON error message about a missing "pagination" field. The researcher cannot browse, create, or manage actors.

**Responsible agent**: `[core]` for missing imports in `pages.py`; `[core]` for route ordering causing HTML detail page to be unreachable.

---

### 8. Analysis (`/analysis`) -- HTTP 404 Not Found

Same trailing-slash issue as Content. The sidebar links to `/analysis` (no trailing slash). The analysis router's `GET /` (which redirects to `/collections`) is only reachable at `/analysis/`.

Even when accessed via `/analysis/`, it redirects to `/collections` which itself is broken (500, `format_number` error).

The analysis dashboard at `/analysis/{run_id}` should work if accessed with a valid UUID, but there is no way to reach it through the sidebar navigation.

**Additional issue in collection detail template**: The link to analysis is `href="/analysis?run_id={{ run_id }}"` but should be `href="/analysis/{{ run_id }}"`. The correct route format is a path parameter, not a query parameter.

**Researcher experience**: Clicking "Analysis" shows a JSON `{"detail":"Not Found"}` response. Even if they somehow got to `/analysis/`, they'd be redirected to the broken collections page.

**Responsible agent**: `[core]` for trailing slash mismatch; `[frontend]` for wrong link format in `collections/detail.html`.

---

### 9. Tools -- Scraping Jobs (`/scraping-jobs`) -- HTTP 200 OK

The page loads correctly. HTMX endpoints are properly configured:
- `hx-get="/scraping-jobs/"` -- 200
- `hx-post="/scraping-jobs/"` -- would work with correct body

No broken links detected.

**Researcher experience**: Works correctly.

---

### 10. Tools -- Import Data (`/imports`) -- HTTP 200 OK

The page loads correctly but the **upload form submits to the wrong endpoint**.

The form has `hx-post="/content/import"` but the import API is mounted at `/api` prefix (main.py line 380), so the correct endpoint is `POST /api/content/import`.

When a researcher fills in the form and clicks "Upload and Import", the request goes to `/content/import` which gets caught by the content router's `GET /{record_id}` route with `record_id="import"`, returning a 422 UUID parsing error.

**Researcher experience**: The page looks professional and well-designed. But when the researcher actually tries to upload a file, it silently fails. The HTMX error handling may or may not display a useful message (the JavaScript expects a JSON response with `.imported` and `.skipped` fields, but gets a 422 error instead).

**Responsible agent**: `[frontend]` for the wrong endpoint path in `imports/index.html` line 32.

---

### 11. Administration -- Users (`/admin/users`) -- HTTP 200 OK

The page loads correctly with the user list displayed. HTMX endpoints:
- `hx-post="/admin/users/create"` -- 405 for GET (POST exists) -- correct behavior
- `hx-post="/admin/users/{id}/activate"` -- route exists
- `hx-post="/admin/users/{id}/deactivate"` -- route exists
- Link to credits page per user -- works

No broken links detected.

**Researcher experience**: Works correctly for admin users.

---

### 12. Administration -- Credits (`/admin/credits`) -- HTTP 200 OK

The page loads correctly. The allocation form `hx-post="/admin/credits/allocate"` route exists (405 on GET, POST expected).

No broken links detected.

**Researcher experience**: Works correctly for admin users.

---

### 13. Administration -- API Keys (`/admin/credentials`) -- HTTP 200 OK

The page loads correctly. HTMX endpoints:
- `hx-post="/admin/credentials/"` -- route exists (create credential)
- `hx-post="/admin/credentials/{id}/activate` -- route exists
- `hx-post="/admin/credentials/{id}/deactivate` -- route exists
- `hx-post="/admin/credentials/{id}/reset-errors` -- route exists
- `hx-delete="/admin/credentials/{id}` -- route exists

No broken links detected.

**Researcher experience**: Works correctly for admin users. Well-designed credential management interface.

---

### 14. Administration -- System Status (`/admin/health`) -- HTTP 200 OK

The page loads correctly. HTMX endpoints:
- `hx-get="/api/health"` -- 200, returns JSON with database and Redis status
- `hx-get="/api/arenas/health"` -- 200, returns per-arena health checks

No broken links detected.

**Researcher experience**: Works correctly. Provides good visibility into system and arena health.

---

## Additional Endpoints Tested

### API Endpoints

| Endpoint | Status | Notes |
|---|---|---|
| `GET /api/arenas/` | 200 | Returns array of 25 ArenaInfo objects correctly |
| `GET /health` | 200 | Returns `{"status": "ok"}` |
| `GET /api/health` | 200 | Returns full health with DB and Redis status |
| `GET /api/arenas/health` | 200 | Returns per-arena health for all 25 arenas |

### Auth Endpoints

| Endpoint | Status | Notes |
|---|---|---|
| `GET /auth/login` | 200 | Login page renders correctly |
| `GET /auth/register` | 200 | Registration page renders correctly |
| `GET /auth/forgot-password` | 200 | Password reset page renders correctly |
| `POST /auth/cookie/login` | 204 | Authentication works correctly |

### Static Files

| File | Status |
|---|---|
| `/static/css/app.css` | 200 |
| `/static/js/app.js` | 200 |
| `/static/js/charts.js` | 200 |
| `/static/js/network_preview.js` | 200 |

---

## Root Cause Analysis

The issues fall into three categories:

### Category 1: Route Ordering Conflict (5 issues)

**Files affected**: `src/issue_observatory/api/main.py` lines 372-388

API routers with `/{id}` path parameters are included BEFORE the pages router. This means URLs like `/query-designs/new` and `/collections/new` are caught by `/{design_id}` and `/{run_id}` respectively, and "new" fails UUID validation.

**Affected URLs**:
- `GET /query-designs/new` -- caught by query_designs API `/{design_id}`
- `GET /query-designs/{id}/edit` -- caught by query_designs API `/{design_id}` (then further routing may fail)
- `GET /collections/new` -- caught by collections API `/{run_id}`
- `GET /actors/{id}` (HTML) -- caught by actors API `/{actor_id}` (returns JSON instead of HTML)
- `GET /content/discovered` -- caught by content API `/{record_id}`

**Fix approach**: Either (a) include the pages router BEFORE the API routers, or (b) use distinct path prefixes for API vs HTML routes (e.g., `/api/query-designs` for JSON endpoints), or (c) add explicit `new` routes to the API routers that delegate to the pages handler.

### Category 2: Trailing Slash Mismatch (3 issues)

**File affected**: `src/issue_observatory/api/main.py` line 91 (`redirect_slashes=False`)

With `redirect_slashes=False`, the sidebar links to `/content` and `/analysis` do not match the API routes which define `GET /` (accessible as `/content/` and `/analysis/`).

**Affected URLs**:
- `GET /content` (sidebar link) -- 404, should be `/content/`
- `GET /analysis` (sidebar link) -- 404, should be `/analysis/`

**Fix approach**: Either (a) change sidebar links to include trailing slashes, or (b) add explicit no-trailing-slash routes in pages.py, or (c) set `redirect_slashes=True`.

### Category 3: Missing Registrations and Imports (3 issues)

| Issue | File | Detail |
|---|---|---|
| Missing `format_number` Jinja2 filter | `main.py` lines 479-481 | Filter used in `collections/list.html` but never registered |
| Missing imports in pages.py | `pages.py` lines 48-56 | `PaginationParams`, `get_pagination`, `HTTPException`, `func`, `UniversalContentRecord` all used but not imported |
| Wrong API endpoint in imports template | `imports/index.html` line 32 | `hx-post="/content/import"` should be `hx-post="/api/content/import"` |
| Wrong API response parsing in explore | `explore/index.html` line 222 | `data.arenas.filter(...)` should be `data.filter(...)` |
| Wrong link format in collection detail | `collections/detail.html` line 308 | `href="/analysis?run_id=..."` should be `href="/analysis/{{ run_id }}"` |
| Wrong link in collection detail | `collections/detail.html` line 317 | `href="/content/discovered"` should be `href="/content/discovered-links"` |

---

## Impact Summary

| Severity | Count | Sections Affected |
|---|---|---|
| **BLOCKER** (page completely broken) | 4 | Collections, Content, Actors, Analysis |
| **BLOCKER** (critical action broken) | 2 | Create Query Design, Launch Collection |
| **Major** (feature silently broken) | 3 | Explore arena selector, Import upload, Collection detail links |
| **Minor** (cosmetic/workaround exists) | 0 | -- |

**Workflow impact**: A researcher cannot complete ANY research workflow. The critical path (Create Query Design -> Launch Collection -> Browse Content -> Analyze Results) is broken at every step except the first (query design creation is broken) and last (analysis page is unreachable).

---

## Recommendations (prioritized)

1. **[core] Fix route ordering in main.py** -- Include the pages router BEFORE API routers, or use a distinct `/api/` prefix for JSON endpoints. This fixes 5 issues at once. *Highest priority.*

2. **[frontend] Register `format_number` Jinja2 filter** -- Add `templates.env.filters["format_number"] = lambda x: f"{x:,}"` after creating the Jinja2Templates instance in main.py. This unblocks the entire collections section.

3. **[core] Fix missing imports in pages.py** -- Add `PaginationParams`, `get_pagination`, `HTTPException`, `func`, and `UniversalContentRecord` to the import block. This unblocks the actors section.

4. **[frontend] Fix sidebar links for trailing slash consistency** -- Change `/content` to `/content/` and `/analysis` to `/analysis/` in `nav.html`, or add redirect routes.

5. **[frontend] Fix explore page arena loading** -- Change `data.arenas.filter(...)` to `data.filter(...)` in `explore/index.html` line 222.

6. **[frontend] Fix imports upload endpoint** -- Change `hx-post="/content/import"` to `hx-post="/api/content/import"` in `imports/index.html` line 32.

7. **[frontend] Fix collection detail links** -- Change `href="/analysis?run_id={{ run_id }}"` to `href="/analysis/{{ run_id }}"` and `href="/content/discovered"` to `href="/content/discovered-links"` in `collections/detail.html`.
