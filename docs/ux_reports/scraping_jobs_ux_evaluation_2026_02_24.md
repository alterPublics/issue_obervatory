# UX Evaluation: Scraping Jobs Page
Date: 2026-02-24
Evaluator: UX Tester (Research Perspective)

## Summary

The Scraping Jobs feature has a page route, a template, an API router with HTMX-friendly endpoints, and a backing database model. The overall structure is sound, but there are **8 distinct issues** ranging from silent HTMX failures (the Cancel and Delete buttons do nothing useful) to form-vs-schema default mismatches and a collection run input that asks for a raw UUID instead of a dropdown. Several of these are blockers: a researcher who creates a scraping job will not be able to cancel or delete it through the UI.

---

## Issue 1 (BLOCKER): Cancel button returns JSON, HTMX expects HTML -- button silently breaks the table

**What is wrong:**
The Cancel button in `_jobs_table.html` (line 73) sends `hx-post="/api/scraping-jobs/{{ job.id }}/cancel"` with `hx-target="#jobs-container"` and `hx-swap="innerHTML"`. HTMX sends an `Accept: text/html` header for such requests.

However, the `cancel_scraping_job` route in `router.py` (line 374) is declared with `response_model=ScrapingJobRead` and returns a single `ScrapingJob` ORM object. FastAPI serializes this as JSON regardless of the `Accept` header. It does **not** negotiate content type or return the `_jobs_table.html` partial.

**What actually happens when a researcher clicks Cancel:**
The JSON blob `{"id": "...", "status": "cancelled", ...}` is injected as raw text into `#jobs-container`, replacing the entire jobs table with unreadable JSON. The researcher sees their job list vanish and be replaced by a wall of JSON data. They cannot recover without reloading the page.

**Files and lines:**
- `/src/issue_observatory/api/templates/scraping/_jobs_table.html` line 73 -- expects HTML response
- `/src/issue_observatory/scraper/router.py` line 374 -- returns JSON

**What it should do:**
The cancel endpoint should detect the `Accept: text/html` header (or `HX-Request` header) and, when present, re-query the user's jobs and return the rendered `_jobs_table.html` partial -- exactly as the `create_scraping_job_form` endpoint already does (router.py line 149). Alternatively, the HTMX attribute could be changed to trigger a table reload event instead of swapping the response directly.

**Responsible agent:** `[core]`

---

## Issue 2 (BLOCKER): Delete button returns HTTP 204 No Content -- HTMX replaces table with empty string

**What is wrong:**
The Delete button in `_jobs_table.html` (line 83) sends `hx-delete="/api/scraping-jobs/{{ job.id }}"` with `hx-target="#jobs-container"` and `hx-swap="innerHTML"`.

The `delete_scraping_job` route in `router.py` (line 433) returns `HTTP 204 No Content` with an empty body. HTMX faithfully swaps the contents of `#jobs-container` with this empty body, which **wipes the entire jobs table from the page**. The researcher sees the table disappear entirely. They must reload the page to see their remaining jobs.

**Files and lines:**
- `/src/issue_observatory/api/templates/scraping/_jobs_table.html` line 83 -- expects HTML response to replace table
- `/src/issue_observatory/scraper/router.py` line 433 -- returns 204 empty body

**What it should do:**
Same resolution as Issue 1: for HTML/HTMX requests, the delete endpoint should re-query jobs and return the updated `_jobs_table.html` partial. For JSON API requests, the 204 response is correct.

**Responsible agent:** `[core]`

---

## Issue 3 (FRICTION): Collection Run input requires a raw UUID instead of a dropdown

**What is wrong:**
When a researcher selects the "Collection run" source type in the Create Scraping Job dialog, they are presented with a plain text input (`_jobs_table.html` / `index.html` line 83) with placeholder text "Run UUID". The researcher is expected to type or paste a UUID string.

No researcher knows collection run UUIDs by heart. They would need to navigate to the Collections page, find the run, copy its UUID from the URL bar, come back to the Scraping Jobs page, open the dialog, and paste it. This is a multi-step hunt that breaks flow.

**Files and lines:**
- `/src/issue_observatory/api/templates/scraping/index.html` lines 79-85 -- the raw text input

**What it should do:**
This should be a `<select>` dropdown populated with the user's recent collection runs (showing the query design name, date, and record count). The page route at `pages.py` line 1511 should query and pass recent collection runs as template context, and the template should render them as selectable options. Alternatively, an HTMX-powered search/autocomplete field that queries `/collections` by name fragment would also work.

**Responsible agent:** `[frontend]` for the template change, `[core]` for passing collection run data to the page context

---

## Issue 4 (FRICTION): Form default values disagree with schema defaults

**What is wrong:**
The Create Scraping Job form in `index.html` sets `delay_min` to `1` (line 108) and `delay_max` to `3` (line 118). But the form handler in `router.py` line 158-159 defaults to `delay_min=2.0` and `delay_max=5.0`. The Pydantic schema `ScrapingJobCreate` also defaults to `delay_min=2.0` and `delay_max=5.0`.

If the researcher opens "Advanced options" and sees the prefilled values (1 and 3), they might assume those are the recommended defaults. But if they submit the form **without** opening Advanced options, the HTML form will send `1` and `3` (the `value` attributes), not the schema defaults. The inconsistency is confusing and could lead to more aggressive scraping than intended.

Additionally, the form's `respect_robots_txt` checkbox is checked by default (line 137), but the `use_playwright_fallback` checkbox is unchecked (line 143). The schema defaults `use_playwright_fallback=True`. So the form's visual default (unchecked = False) contradicts what happens when using the JSON API (True). A researcher using the form gets different behavior than a researcher using the API -- for no apparent reason.

**Files and lines:**
- `/src/issue_observatory/api/templates/scraping/index.html` lines 108, 118, 143 -- form defaults
- `/src/issue_observatory/scraper/router.py` lines 158-159 -- form handler defaults
- `/src/issue_observatory/core/schemas/scraping.py` lines 41-45 -- schema defaults

**What it should do:**
All three layers (form HTML `value` attributes, form handler defaults, and schema defaults) should agree. The form should show `2` and `5` for delay fields, and `use_playwright_fallback` should be checked by default (matching the schema's `True` default).

**Responsible agent:** `[frontend]`

---

## Issue 5 (FRICTION): No progress feedback during active scraping jobs

**What is wrong:**
The scraper router has a well-designed SSE endpoint at `GET /api/scraping-jobs/{job_id}/stream` (router.py line 478) that streams live progress events. But the `_jobs_table.html` template never connects to it. The table auto-refreshes every 15 seconds via the `hx-trigger="load, jobCreated from:body, every 15s"` on the parent container (index.html line 28), which is a coarse polling approach.

For a researcher running a scraping job against hundreds of URLs, the 15-second polling means they see stale progress for up to 15 seconds at a time. More importantly, the table shows running jobs with a spinner icon, but there is no progress bar or percentage indicator. The researcher sees "Running" with the Total/Enriched/Failed counters, but only updated every 15 seconds. For a long-running job (hundreds of URLs at 2-5 second delay each = 10-40 minutes), this is a poor experience.

**Files and lines:**
- `/src/issue_observatory/api/templates/scraping/index.html` line 28 -- 15-second polling instead of SSE
- `/src/issue_observatory/api/templates/scraping/_jobs_table.html` -- no progress bar, no SSE connection
- `/src/issue_observatory/scraper/router.py` lines 478-569 -- SSE endpoint exists but is unused by the frontend

**What it should do:**
For running jobs, the table row should either: (a) connect to the SSE stream and update counters in real-time, or (b) at minimum display a progress bar based on `urls_enriched / total_urls`. The SSE endpoint is already built and ready; the frontend just never wires it up.

**Responsible agent:** `[frontend]`

---

## Issue 6 (FRICTION): No error display when job creation fails

**What is wrong:**
The form in `index.html` (line 50-53) submits via `hx-post="/api/scraping-jobs/form"` and on success closes the dialog via `@htmx:after-request`. However, if the server returns a 422 error (e.g., empty Collection Run UUID, or invalid UUID format), the HTMX response will contain an error JSON, not an HTML fragment. The `hx-target="#jobs-container"` will swap this error JSON into the table area, replacing the jobs list with an error message blob. The dialog will still close (the `@htmx:after-request` event fires for all responses, not just successful ones).

The researcher experience: they click "Create Job" with a bad input, the dialog closes, and the jobs table is replaced with a JSON error string. They have no idea what went wrong.

**Files and lines:**
- `/src/issue_observatory/api/templates/scraping/index.html` line 53 -- `@htmx:after-request` fires on all responses
- `/src/issue_observatory/scraper/router.py` lines 200-213 -- UUID parse errors return HTTPException (JSON)

**What it should do:**
The `@htmx:after-request` handler should check `event.detail.successful` (or the response status code) and only close the dialog on success. On error, the form should display a user-readable error message inside the dialog itself. The error response from the server should ideally be an HTML fragment that can be shown inline.

**Responsible agent:** `[frontend]` for the dialog behavior, `[core]` for returning HTML error fragments for form submissions

---

## Issue 7 (DESIGN): No link between Collections and Scraping Jobs

**What is wrong:**
The Scraping Jobs page exists as an isolated tool under the "Tools" section in the nav (nav.html line 47). There is no entry point from the Collection detail page to create a scraping job for that collection's URLs. A researcher who just completed a collection run and wants to enrich URLs with full-text content must:

1. Note/copy the collection run UUID
2. Navigate to Scraping Jobs (a different section)
3. Click "New Scraping Job"
4. Paste the UUID

There is no "Enrich with full text" button on the collection detail page, and no contextual link. The feature is essentially invisible unless the researcher knows to look under "Tools."

**Files and lines:**
- `/src/issue_observatory/api/templates/_partials/nav.html` line 47 -- only entry point
- `/src/issue_observatory/api/templates/collections/` -- no scraping job links anywhere

**What it should do:**
The Collection detail page should include an "Enrich URLs with full text" action button that either navigates to the Scraping Jobs page with the collection run pre-selected, or opens an inline creation form. This is the natural point in the workflow where a researcher would want this feature.

**Responsible agent:** `[frontend]` for adding the button, `[core]` for supporting a `?collection_run_id=` query parameter on the scraping jobs page

---

## Issue 8 (MINOR): Truncated UUID display in Source column is not helpful

**What is wrong:**
In `_jobs_table.html` line 28, the collection run UUID is displayed truncated to 8 characters: `{{ job.source_collection_run_id | string | truncate(8, true, '') }}`. This shows something like `a3f7e2c1` which is meaningless to a researcher. They cannot tell which collection run it refers to.

Similarly, the `created_at` timestamp on line 67 is truncated to 16 characters, which for an ISO timestamp like `2026-02-24T14:30:00+00:00` yields `2026-02-24T14:30` -- passable but not formatted in a human-friendly way.

**Files and lines:**
- `/src/issue_observatory/api/templates/scraping/_jobs_table.html` line 28 -- truncated UUID
- `/src/issue_observatory/api/templates/scraping/_jobs_table.html` line 67 -- truncated timestamp

**What it should do:**
The Source column should display the query design name and collection date rather than a truncated UUID. This requires joining or pre-fetching the collection run's query design name when loading jobs. The timestamp should use a human-friendly format like "24 Feb 2026, 14:30" using a Jinja2 filter.

**Responsible agent:** `[core]` for enriching job data with collection run details, `[frontend]` for display formatting

---

## Summary Table

| # | Severity | Issue | File(s) | Agent |
|---|----------|-------|---------|-------|
| 1 | BLOCKER | Cancel button injects JSON into table | `_jobs_table.html:73`, `router.py:374` | `[core]` |
| 2 | BLOCKER | Delete button wipes table (204 empty body) | `_jobs_table.html:83`, `router.py:433` | `[core]` |
| 3 | FRICTION | Collection run input requires raw UUID | `index.html:79-85` | `[frontend]` + `[core]` |
| 4 | FRICTION | Form defaults disagree with schema defaults | `index.html:108,118,143`, `router.py:158-159`, `scraping.py:41-45` | `[frontend]` |
| 5 | FRICTION | SSE progress endpoint exists but is never used | `index.html:28`, `router.py:478` | `[frontend]` |
| 6 | FRICTION | Form errors close dialog and inject JSON | `index.html:53`, `router.py:200-213` | `[frontend]` + `[core]` |
| 7 | DESIGN | No link from Collection detail to Scraping Jobs | `nav.html:47`, `collections/` templates | `[frontend]` + `[core]` |
| 8 | MINOR | Truncated UUID and timestamp not researcher-friendly | `_jobs_table.html:28,67` | `[frontend]` + `[core]` |
