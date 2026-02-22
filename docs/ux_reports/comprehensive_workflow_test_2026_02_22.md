# Comprehensive Workflow UX Test Report
Date: 2026-02-22
Tester: UX Research Agent (researcher perspective)
Application: The Issue Observatory (http://localhost:8000)
Auth: admin@example.com (admin role)

## Executive Summary

This report documents a systematic end-to-end evaluation of the Issue Observatory application from a Danish discourse researcher's perspective. Testing covered all 10 primary workflow scenarios across the application's page routes, API endpoints, templates, and data outputs.

**The application has a pervasive, critical routing conflict that makes most detail pages unusable.** Because the JSON API routers are registered in `main.py` before the HTML page routers, every `GET /{entity_id}` URL (query designs, collections, actors) returns raw JSON instead of a rendered HTML page. A researcher clicking on any item from a list page will see unintelligible JSON data instead of the expected detail view.

Additionally, three separate template rendering errors prevent the query design editor, the codebook system, and the analysis dashboard from loading at all. Combined, these issues mean that roughly 60% of the application's core workflows are currently broken from a user's perspective.

The areas that DO work correctly are well-designed: the navigation sidebar, list pages, the dashboard, the collection launcher, the CSV export, and the arenas overview all render properly and use clear, research-appropriate language.

---

## Critical Issues (Workflow Blockers)

### CRIT-01: Route Priority Conflict -- Detail Pages Return Raw JSON Instead of HTML [core]

**Severity:** Critical (blocks 5+ workflows)

**Description:** When a researcher clicks on any entity name in a list to view its details, they see raw JSON data instead of a formatted HTML page. The application returns `Content-Type: application/json` instead of `text/html`.

**Root cause (observed from user perspective):** The FastAPI application in `main.py` (line 376-392) registers JSON API routers BEFORE the HTML page router. Since both define `GET /{id}` patterns on the same prefix, FastAPI matches the API route first. The `pages.router` (line 392) never gets a chance to handle these requests.

**Affected pages:**
- `GET /query-designs/{design_id}` -- returns JSON instead of `query_designs/detail.html`
- `GET /collections/{run_id}` -- returns JSON instead of `collections/detail.html`
- `GET /actors/{actor_id}` -- returns JSON instead of `actors/detail.html`
- `GET /content/discovered-links` -- returns JSON instead of `content/discovered_links.html`

**Steps to reproduce:**
1. Log in to the application
2. Navigate to Query Designs (the list page loads correctly)
3. Click on any query design name
4. Expected: A formatted detail page showing the design's metadata, search terms, actor list, arena config, and run history
5. Actual: Raw JSON like `{"id":"305e03e5-...","owner_id":"0c8efb75-...","name":"Test Gron Omstilling",...}`

**Impact on researcher:** This breaks the fundamental browse-and-drill-down navigation pattern. A researcher cannot view details of any query design, collection run, or actor through the web interface. They are forced to read raw JSON, which is unintelligible to a non-developer user. Every workflow that involves navigating from a list to a detail view is broken.

**Affected workflows:** 1 (Query Design Lifecycle), 2 (Collection Launch and Monitoring), 3 (Content Browsing -- discovered links), 5 (Actor Management), 6 (Navigation and Cross-Linking)

---

### CRIT-02: Query Design Editor Crashes with Template Error [core] [frontend]

**Severity:** Critical (blocks query design editing)

**Description:** Navigating to the query design editor (`/query-designs/{id}/edit`) produces a 500 Internal Server Error. The Jinja2 template `query_designs/editor.html` references `design.arenas_config` on line 1051, but the page route in `pages.py` (line 299-319) only passes `design_id` as a string, not a full design object with an `arenas_config` attribute.

**Error message (from server trace):**
```
jinja2.exceptions.UndefinedError: 'dict object' has no attribute 'arenas_config'
```

**Steps to reproduce:**
1. Navigate to Query Designs list
2. Click "Edit" on any design
3. Expected: The query design editor page loads with the design's current terms, actors, and arena configuration
4. Actual: A 500 error page (or raw stack trace in debug mode)

**Impact on researcher:** Researchers cannot edit any existing query design. The only way to modify search terms or arena settings is to delete and recreate the design, losing all associated collection history. This effectively makes the application a one-shot tool where mistakes in initial design are permanent.

**Affected workflows:** 1 (Query Design Lifecycle), 8 (Arena Configuration)

---

### CRIT-03: Analysis Dashboard Template Has Jinja2 Syntax Error [frontend]

**Severity:** Critical (blocks all analysis)

**Description:** The analysis dashboard template (`analysis/index.html`) contains a JSDoc comment with double curly braces (`{{ nodes: Array, edges: Array }}`) that Jinja2 interprets as a template expression. This causes a compile-time syntax error that prevents the entire analysis page from rendering.

**Error message (from server trace):**
```
jinja2.exceptions.TemplateSyntaxError: expected token 'end of print statement', got ':'
  File "analysis/index.html", line 2259
    * @param {{ nodes: Array, edges: Array }} graphData
```

**Steps to reproduce:**
1. Navigate to Analysis from the sidebar
2. The landing page loads correctly and shows "Select a collection run to analyse"
3. Click on any completed run (or navigate directly to `/analysis/{run_id}`)
4. Expected: The analysis dashboard with volume charts, top actors, network graphs, and export options
5. Actual: A 500 error / stack trace

**Impact on researcher:** No analysis can be performed through the web interface. The entire descriptive statistics, network visualization, temporal comparison, arena comparison, and export workflow is inaccessible. This is the culmination of the data collection pipeline -- without analysis, the tool cannot deliver on its core purpose.

**Affected workflows:** 4 (Analysis Dashboard), 6 (Navigation and Cross-Linking)

---

### CRIT-04: Codebook System Crashes Due to Database Schema Mismatch [core] [data]

**Severity:** Critical (blocks codebook management)

**Description:** The codebooks API endpoint crashes with a database error because the ORM model references a `created_by` column that does not exist in the `codebook_entries` table. The database only has a `created_at` column.

**Error message:**
```
asyncpg.exceptions.UndefinedColumnError: column codebook_entries.created_by does not exist
HINT: Perhaps you meant to reference the column "codebook_entries.created_at".
```

**Steps to reproduce:**
1. Navigate to a query design detail page (if CRIT-01 were fixed)
2. Click "Manage Codebook"
3. The codebook manager page itself loads (HTML renders), but it tries to fetch codebook entries via the API
4. The API call crashes with a 500 error

Alternatively:
1. Call `GET /codebooks/?query_design_id={id}` directly
2. Observe the 500 error

**Impact on researcher:** The codebook system (SB-16), which supports qualitative coding of collected content, is completely non-functional. Researchers cannot create, view, or manage annotation codebooks. The codebook badge on the query design detail page will also fail.

**Affected workflows:** 10 (Annotations and Codebooks)

---

### CRIT-05: Content Browser Pagination Crashes [core]

**Severity:** Critical (blocks content browsing)

**Description:** The content records endpoint (`GET /content/records`) crashes when there are records to paginate. The cursor encoding logic references `last["published_at"]` using dict-style access on a SQLAlchemy Row object, which does not support this access pattern.

**Error message:**
```
KeyError: 'published_at'
```

**Steps to reproduce:**
1. Navigate to Content browser (`/content/`)
2. The page HTML shell loads, but the HTMX call to `/content/records` to populate the table body fails
3. Expected: A table of collected content records with filtering and pagination
4. Actual: The table body area remains empty or shows an error

**Impact on researcher:** The content browser, which is the primary interface for examining collected data, cannot display any records. A researcher has collected 146 records (confirmed via `/content/count`) but cannot see them. They can export via CSV (which works), but they cannot browse, filter, search, or inspect individual records through the web interface.

**Affected workflows:** 3 (Content Browsing), 10 (Annotations and Codebooks -- since you need to view content to annotate it)

---

## High-Priority Issues

### HIGH-01: Analysis Landing Page Sends Researcher to Collections List Instead of Analysis Selection [frontend]

**Severity:** High

**Description:** The Analysis landing page (`/analysis/`) shows a "Select a collection run to analyse" prompt with a "View Collections" button that links to `/collections`. This navigates the researcher away from the analysis context entirely, to the general collections list. The collections list page has no "Analyze" action button on each row. The researcher must manually construct the URL `/analysis/{run_id}` or know to look for analysis links elsewhere.

Even though the analysis landing page has a "Recent completed runs" section that would link directly to analysis, it only appears when there are completed runs. The run with 146 records has status "pending" (not "completed"), so even though it has data, it does not appear in this list.

**Steps to reproduce:**
1. Click "Analysis" in the sidebar
2. See the landing page with "Select a collection run to analyse"
3. Click "View Collections"
4. Expected: A collection selection interface within the analysis context, or at minimum, the collections list with an "Analyze" button on each completed run
5. Actual: Redirected to the standard collections list page, which has no analysis action. The researcher is stranded.

**Impact on researcher:** The researcher cannot discover how to get from collected data to analysis. The "View Collections" link is a navigational dead end for analysis purposes. The collections list shows "Run ID", "Status", "Records", and "Started" but no "Analyze" action.

**Affected workflows:** 4 (Analysis Dashboard)

---

### HIGH-02: Content Page Requires Trailing Slash -- Redirect Creates Friction [core]

**Severity:** High

**Description:** Navigating to `/content` (without trailing slash) returns a `307 Temporary Redirect` to `/content/`. This is because the content API router is mounted at `/content` prefix, and the main content browser is at `GET /content/` (the root of that router). The sidebar link (`href="/content"`) triggers this redirect every time.

While the page eventually loads, the redirect means HTMX `hx-boost` may not handle it gracefully in all cases, and the browser URL bar shows `/content/` while the sidebar link says `/content`.

**Steps to reproduce:**
1. Click "Content" in the sidebar
2. Expected: Content browser loads directly
3. Actual: A 307 redirect from `/content` to `/content/`, then the page loads

**Affected workflows:** 3 (Content Browsing), 6 (Navigation and Cross-Linking)

---

### HIGH-03: Collection Runs Stuck in "Pending" Status Despite Having Data [data]

**Severity:** High (data trust issue)

**Description:** The collection run `1cd78707-5952-4421-a48e-c34311d48fa0` has 146 records collected but remains in "pending" status. This means:
- It does not appear in the analysis landing page's "Recent completed runs" list
- The analysis dashboard may refuse to analyze it (status checks)
- The researcher sees conflicting information: records exist but the run appears incomplete

**Impact on researcher:** The researcher does not know whether their collection succeeded, failed, or is still running. The status indicator says "pending" but records have clearly been collected. This is a data trust issue -- the researcher cannot confidently determine the state of their data.

**Affected workflows:** 2 (Collection Launch and Monitoring), 4 (Analysis Dashboard)

---

## Medium-Priority Issues

### MED-01: No "Analyze" Action in Collections List [frontend]

**Severity:** Medium

**Description:** The collections list page (`/collections`) shows run ID, status, records, and start time, but provides no "Analyze" button or link for completed runs. The researcher must know to navigate to `/analysis/{run_id}` manually or find the link in the query design detail page (which itself is broken per CRIT-01).

**Steps to reproduce:**
1. Navigate to Collections
2. See the list of runs
3. Expected: An "Analyze" action button next to completed runs
4. Actual: Only the run ID is clickable, linking to the collection detail page (which returns JSON per CRIT-01)

**Affected workflows:** 4 (Analysis Dashboard), 6 (Navigation and Cross-Linking)

---

### MED-02: Dashboard User Display Name Shows "None" [frontend]

**Severity:** Medium

**Description:** The navigation sidebar shows the user's display name as "None" (the Python None value rendered as a string). The template uses `{{ user.display_name | default(user.email | default('')) }}` but the User model's `display_name` field is `None`, and the Jinja2 `default` filter only replaces undefined variables, not None values.

**Steps to reproduce:**
1. Log in and view the sidebar
2. Expected: The user's email or a friendly display name
3. Actual: "None" appears as the display name, with "admin@example.com" below it

**Impact on researcher:** Minor but creates a sense of an incomplete or buggy application. The "None" text looks like a programming error, not a missing display name.

**Affected workflows:** All (navigation sidebar appears on every page)

---

### MED-03: Credit Balance Shows 0 -- No Guidance on Getting Credits [frontend]

**Severity:** Medium

**Description:** The credit balance badge in the sidebar and dashboard shows "Credits: 0" with no indication of how to obtain credits. A new researcher would not know whether this is normal, whether they need to request credits from an administrator, or whether all FREE-tier arenas simply do not require credits.

**Steps to reproduce:**
1. View the sidebar or dashboard
2. See "Credits: 0"
3. Expected: Context about what credits are for, and either a link to request credits or a note that FREE-tier arenas don't require credits
4. Actual: Just the number "0" with no explanation

**Impact on researcher:** Creates confusion about whether they can proceed with collections. May stop a researcher from launching a collection, thinking they cannot do so without credits.

**Affected workflows:** 2 (Collection Launch and Monitoring), 7 (Tier Switching)

---

### MED-04: Clone Action Uses HTMX POST But hx-boost="false" Creates Navigation Confusion [frontend]

**Severity:** Medium

**Description:** The "Clone" action on query designs uses `hx-post` with `hx-boost="false"`. This means cloning a design triggers a full page navigation via the 303 redirect response. However, because the redirect target is `/query-designs/{new_id}` (a detail page), and CRIT-01 causes detail pages to return JSON, the clone action will navigate the researcher to a page of raw JSON.

**Steps to reproduce:**
1. Navigate to Query Designs list
2. Click "Clone" on a design
3. Confirm the clone
4. Expected: Navigate to the new design's editor or detail page
5. Actual: Navigate to a page showing raw JSON (due to CRIT-01)

**Affected workflows:** 1 (Query Design Lifecycle)

---

### MED-05: Annotations Endpoint Returns 404 [core]

**Severity:** Medium

**Description:** The annotations endpoint at `GET /annotations/` returns a 404 "Not Found" error. This may be a routing issue or the endpoint may not be fully implemented.

**Steps to reproduce:**
1. Call `GET /annotations/`
2. Expected: A list of annotations or an empty list
3. Actual: `{"detail":"Not Found"}`

**Affected workflows:** 10 (Annotations and Codebooks)

---

## Low-Priority Issues

### LOW-01: Actor Similarity Search Endpoint Returns 404 [core]

**Severity:** Low

**Description:** The actor similarity search endpoint at `GET /actors/{id}/similarity-search` returns 404. This may be expected if the endpoint is at a different path, or it may indicate a missing implementation.

**Affected workflows:** 5 (Actor Management)

---

### LOW-02: No Visual Feedback During HTMX Loading States [frontend]

**Severity:** Low

**Description:** Several HTMX-powered sections (recent runs on dashboard, credit balance, volume spike alerts) show placeholder text like "Loading..." but the transitions can be abrupt. There is a loading spinner partial (`_partials/loading_spinner.html`) that is used in some places but not consistently.

**Affected workflows:** All

---

### LOW-03: Matched Search Terms in Export Show Common Danish Words [data]

**Severity:** Low (data quality observation)

**Description:** In the CSV export, the `Matched Search Terms` column contains very common Danish words like "den", "og", "i", "er", "et" (the Danish equivalents of "the", "and", "in", "is", "a"). These appear to be single-character or very short keyword matches rather than meaningful research terms. This suggests that the search term matching may be too broad, or that the query design used for this collection contained overly generic terms.

**Impact on researcher:** This is a data quality concern rather than a bug. If a researcher set up meaningful search terms like "gron omstilling" but sees matches on "og" (and), they would question whether the matching algorithm is working correctly, or whether the data can be trusted for analysis.

**Affected workflows:** 3 (Content Browsing), 4 (Analysis Dashboard)

---

## Passed Workflows (Working Correctly)

### Navigation Sidebar
- All primary navigation links resolve correctly
- Active page highlighting works (blue highlight on current page)
- Admin section is correctly shown only for admin users
- Credit badge polls and displays balance
- User display area shows email (though display name shows "None")
- Logout form is functional

### Dashboard
- Renders correctly with summary cards (Credits, Active Collections, Records Collected)
- Quick Actions section has correct links
- Recent Collections section loads via HTMX (fragment format)
- All links navigate to correct destinations

### Query Design List Page
- Renders correctly with design name, visibility, tier, term count, status
- "New Query Design" button links to `/query-designs/new`
- Edit, Collect, Clone, and Delete actions have correct URLs
- Empty state is handled with a call-to-action

### Query Design Create (New)
- The `/query-designs/new` page loads correctly
- Creating a design via the API works (JSON POST to `/query-designs/`)

### Collections List Page
- Renders correctly with run ID, status, records, start time
- Links to collection detail pages (though those pages return JSON per CRIT-01)

### Collection Launcher
- The `/collections/new` page loads correctly
- Creating a collection run via the API works

### Arenas Overview Page
- The `/arenas` page loads correctly
- Arena registry API returns all 25 registered arenas

### Explore Page
- The `/explore` page loads correctly

### Admin Pages
- Users (`/admin/users`) loads correctly
- Credits (`/admin/credits`) loads correctly
- API Keys (`/admin/credentials`) loads correctly
- System Status (`/admin/health`) loads correctly

### Authentication
- Login page renders correctly
- Registration page renders correctly
- Cookie-based auth works correctly (30-minute JWT)
- Logout form is present in the sidebar

### Imports and Scraping
- Import page (`/imports`) loads correctly
- Scraping jobs page (`/scraping-jobs`) loads correctly

### Content Export
- CSV export (`GET /content/export?format=csv`) works correctly
- Output contains real Danish-language news content from DR, Politiken, and other outlets
- Headers are human-readable (not developer field names)
- Data includes platform, arena, content type, title, text, URL, timestamps, language

### Data Quality (from CSV export)
- Content is genuinely Danish-language (confirmed: DR, TV2, Berlingske articles)
- Timestamps are present and plausible
- URLs are valid and point to real Danish news articles
- Content hash column is populated (deduplication infrastructure is working)
- Language field is correctly set to "da"

---

## Data Quality Findings

### DQ-01: Search Term Matching Appears Overly Broad
The matched search terms for the existing collection include extremely common Danish stop words ("den", "og", "i", "er", "et"). These are the most frequent words in Danish and would match nearly every piece of text. This suggests either the query design used these as search terms, or the matching algorithm is not filtering on full terms. A researcher relying on this data for publication would question the selectivity of the collection.

### DQ-02: Collection Run Status Does Not Reflect Actual State
Run `1cd78707` has 146 records but status "pending". This inconsistency undermines confidence in the data pipeline's reporting accuracy.

### DQ-03: Engagement Metrics Are Empty
All exported records show empty values for views, likes, shares, comments, and engagement_score. For RSS/news content this is expected (news articles don't have engagement metrics), but the columns are present and empty, which could confuse a researcher into thinking the data collection failed to capture these metrics.

---

## Recommendations (Prioritized)

### Priority 1 -- Must Fix Before Any Researcher Can Use the Application

1. **[core] Fix route registration order in `main.py`:** Register HTML page routes (including `pages.router`) BEFORE the JSON API routers, or use content negotiation (Accept header) to distinguish HTML from JSON requests on the same URL pattern. The page routes for detail views (`/query-designs/{id}`, `/collections/{id}`, `/actors/{id}`) must take precedence over the JSON API routes when a browser requests the page. Alternatively, prefix all API routes with `/api/` to avoid path conflicts entirely.

2. **[frontend] Fix Jinja2 syntax error in `analysis/index.html`:** Escape the JSDoc comment on line 2259 that uses `{{ nodes: Array, edges: Array }}`. Replace the double curly braces in JavaScript comments with Jinja2-safe alternatives (e.g., use `{# ... #}` Jinja2 comments, or escape with `{% raw %}...{% endraw %}`).

3. **[core] Fix query design editor template context:** The `pages.py` route for `query_designs_edit` (line 299-319) passes only `design_id` as a string, but the `editor.html` template expects a `design` object with attributes like `arenas_config`. Either load the full QueryDesign from the database and pass it as context, or modify the template to fetch this data client-side.

4. **[data] Fix codebook_entries schema mismatch:** Either add a `created_by` column to the `codebook_entries` table via a new Alembic migration, or remove the `created_by` attribute from the CodebookEntry ORM model. The model and database must agree.

5. **[core] Fix content records pagination KeyError:** The cursor encoding in `content.py` accesses `last["published_at"]` with dict-style syntax on a SQLAlchemy Row. Use attribute access (`last.published_at`) or convert the row to a dict first.

### Priority 2 -- Improve Researcher Workflow

6. **[frontend] Add "Analyze" action to collections list:** Add an "Analyze" button or link next to completed collection runs in the collections list template, linking to `/analysis/{run_id}`.

7. **[frontend] Fix analysis landing page navigation:** Instead of linking to `/collections` (a dead end for analysis), either show a run selector directly on the analysis landing page, or link to `/collections` with a query parameter that highlights the analysis action.

8. **[frontend] Fix user display name rendering:** Use `{{ user.display_name or user.email or '' }}` instead of `{{ user.display_name | default(user.email) }}` to handle None values correctly in Jinja2.

9. **[frontend] Add credit guidance:** When credits are 0, show a brief message explaining that FREE-tier arenas do not require credits, and that an admin can allocate credits for MEDIUM/PREMIUM tiers.

### Priority 3 -- Polish and Data Quality

10. **[data] Review search term matching breadth:** The presence of common Danish stop words in matched search terms suggests the matching may need a minimum term length filter or stop word exclusion.

11. **[core] Ensure collection run status updates correctly:** Run status should transition from "pending" to "running" to "completed" (or "failed"). A run with 146 records should not remain in "pending" status.

12. **[frontend] Add consistent loading states:** Use the loading spinner partial consistently across all HTMX-powered sections.

---

## Summary Table of Issues

| ID | Severity | Title | Responsible Agent | Workflows Affected |
|----|----------|-------|-------------------|--------------------|
| CRIT-01 | Critical | Detail pages return JSON instead of HTML | [core] | 1, 2, 3, 5, 6 |
| CRIT-02 | Critical | Query design editor crashes (template error) | [core] [frontend] | 1, 8 |
| CRIT-03 | Critical | Analysis dashboard template syntax error | [frontend] | 4, 6 |
| CRIT-04 | Critical | Codebook system crashes (schema mismatch) | [core] [data] | 10 |
| CRIT-05 | Critical | Content browser pagination crashes | [core] | 3, 10 |
| HIGH-01 | High | Analysis landing sends to dead-end page | [frontend] | 4 |
| HIGH-02 | High | Content page requires trailing slash redirect | [core] | 3, 6 |
| HIGH-03 | High | Collection runs stuck in pending with data | [data] | 2, 4 |
| MED-01 | Medium | No "Analyze" action in collections list | [frontend] | 4, 6 |
| MED-02 | Medium | Dashboard shows "None" for display name | [frontend] | All |
| MED-03 | Medium | No guidance on credit system | [frontend] | 2, 7 |
| MED-04 | Medium | Clone action navigates to JSON page | [frontend] | 1 |
| MED-05 | Medium | Annotations endpoint returns 404 | [core] | 10 |
| LOW-01 | Low | Actor similarity search returns 404 | [core] | 5 |
| LOW-02 | Low | Inconsistent loading states | [frontend] | All |
| LOW-03 | Low | Matched search terms include stop words | [data] | 3, 4 |

---

## Test Environment

- Application: The Issue Observatory, running locally at http://localhost:8000
- Server: Uvicorn
- Database: PostgreSQL (with 135 content records, 3 collection runs, 2 query designs)
- Authentication: admin@example.com (admin role, cookie-based JWT)
- Arenas registered: 25 (confirmed via `/api/arenas/`)
- Testing method: HTTP requests via curl with session cookies, source code inspection of routes and templates
