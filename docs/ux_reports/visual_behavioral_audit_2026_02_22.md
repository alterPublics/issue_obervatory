# Visual and Behavioral Audit -- All Pages
Date: 2026-02-22
Method: Static code analysis of all templates, route handlers, and fragment endpoints
Scope: Every sidebar section page: /dashboard, /explore, /arenas, /query-designs, /collections, /content, /actors, /analysis, /scraping-jobs, /imports, /admin/users, /admin/credits, /admin/credentials, /admin/health

---

## 1. Sidebar Duplication Investigation

**Finding: The sidebar is included exactly once in the page template chain.**

`base.html` line 55: `{% include '_partials/nav.html' %}` -- this is the sole inclusion point. No template includes nav.html a second time.

However, **sidebar duplication can still occur via `hx-boost="true"`** on the `<body>` tag (base.html line 54). When HTMX boosts a link click, it fetches the target URL and swaps the response body into the current page. If the response is a full HTML page (which it is -- all page routes extend base.html), HTMX is supposed to extract only the `<body>` content. But if any of the following happen, the sidebar can appear twice:

- A FastAPI route that shares a path prefix with a page route returns unexpected content (JSON, a string, or a different HTML structure), and HTMX mishandles the swap.
- The browser navigates to a route that returns a `RedirectResponse` (like `/analysis` redirecting to `/collections`), and HTMX follows the redirect but then processes the full page body including the sidebar.

**Likely root cause of reported sidebar duplication:** The `hx-boost="true"` attribute on `<body>` means all `<a>` clicks are intercepted by HTMX. When HTMX receives a full HTML page with `<!DOCTYPE html>` and extracts the body, it should work correctly. But if any response returns partial HTML without the full document structure, or if redirect chains confuse the body extraction, the entire response (including a second sidebar) gets injected into `<main>`.

**Recommended investigation:**
- In the browser, open DevTools Network tab and click each nav link. Verify the response is a full HTML document (not a fragment with nav embedded). `[frontend]`
- Check whether the `/analysis` redirect (302 to `/collections`) causes duplication when boosted. `[frontend]`

---

## 2. Dashboard (/dashboard)

### 2.1 Volume Spikes Card -- String Return Type Bug

**Page:** `/dashboard`
**What looks wrong:** The volume spikes alert section may display raw JSON-encoded string instead of HTML.

**Evidence:**
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/routes/collections.py`, lines 1103-1112:
```python
if hx_request:
    templates = _templates(request)
    return templates.TemplateResponse(
        "_fragments/volume_spike_alerts.html",
        {
            "request": request,
            "spikes": spikes,
        },
    ).body.decode("utf-8")

return spikes
```

The endpoint return type is `-> list[dict[str, Any]] | str` (line 1027). When called via HTMX, it renders a template and then calls `.body.decode("utf-8")`, which produces a Python `str`. FastAPI will JSON-serialize this string, wrapping it in double quotes and escaping newlines. The HTMX swap target (`hx-swap="innerHTML"`) will receive `"<div class=\"bg-gradient-to-r ...\">\n..."` instead of actual HTML.

**Suggested fix:** Return `HTMLResponse(content=rendered_body)` instead of the raw decoded string. Or return the `TemplateResponse` directly without calling `.body.decode()`.
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/routes/collections.py`
Change lines 1106-1112 to return the `TemplateResponse` object directly. `[core]`

### 2.2 Volume Spikes Card -- Alpine x-data Disconnect

**Page:** `/dashboard`
**What looks wrong:** The volume spikes container has `class="hidden"` and an Alpine `x-data` with `x-init="$watch('spikes', ...)"`, but the `spikes` array is never populated by HTMX. The HTMX response replaces the innerHTML of the div, but the Alpine component's `spikes` reactive data property is never updated -- the HTML swap bypasses Alpine's reactivity system entirely.

**Evidence:**
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/dashboard/index.html`, lines 96-104:
```html
<div id="volume-spike-alerts"
     hx-get="/collections/volume-spikes/recent?days=7&limit=5"
     hx-trigger="load, every 60s"
     hx-target="#volume-spike-alerts"
     hx-swap="innerHTML"
     class="hidden"
     x-data="{ spikes: [] }"
     x-init="$watch('spikes', value => { if (value && value.length > 0) { $el.classList.remove('hidden'); } })">
</div>
```

The HTMX response will replace the innerHTML with the rendered volume spike alerts HTML fragment. But this does not update the Alpine `spikes` array. The `$watch` callback never fires. The `class="hidden"` is never removed. **Result: even if there are volume spikes, the card stays invisible.**

**Suggested fix:** Either (a) remove the Alpine x-data/x-init and instead have the fragment itself include `class="hidden"` removal (e.g., the fragment already conditionally renders nothing when there are no spikes), or (b) use an HTMX afterSwap event handler in JavaScript to unhide the container if it has content.
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/dashboard/index.html`
The simplest fix: remove `class="hidden"`, remove the `x-data` and `x-init`, and let the fragment handle emptiness (the fragment template `_fragments/volume_spike_alerts.html` already renders nothing when `spikes` is empty). `[frontend]`

### 2.3 "Records Collected" Card -- Permanently Static

**Page:** `/dashboard`
**What looks wrong:** The "Records Collected" card shows a dash (`---`) placeholder forever. It has no `hx-get` attribute, so it never loads data from the server.

**Evidence:**
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/dashboard/index.html`, lines 78-93:
```html
{# Total records card #}
<div class="bg-white rounded-lg shadow p-5">
    ...
    <p class="text-2xl font-bold text-gray-900">---</p>
    <p class="text-xs text-gray-500 mt-1">
        <a href="/content" class="text-blue-600 hover:underline">View all content</a>
    </p>
</div>
```

There is no HTMX polling attribute. The card will always display "---".

**Suggested fix:** Add an HTMX `hx-get` that points to an endpoint returning the total record count, or render the count server-side in the page handler. This requires a new endpoint or modifying the `/dashboard` page handler to query the count. `[core]` `[frontend]`

### 2.4 Active Collections and Recent Runs -- Correct

**Note:** The `GET /collections/active-count` endpoint (line 88) now correctly declares `response_class=HTMLResponse` and returns `HTMLResponse(...)` (line 123). Similarly, the `GET /collections/?format=fragment` branch (line 233-282) returns `HTMLResponse(...)`. These were previously returning raw strings but have been fixed. **No issue here.**

---

## 3. Arenas Page (/arenas)

### 3.1 Narrative Text Shows "0 data collection arenas"

**Page:** `/arenas`
**What looks wrong:** The narrative text at the top of the page says "The Issue Observatory provides access to **0 data collection arenas**" because the route handler does not pass an `arenas` variable to the template context.

**Evidence:**
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/routes/pages.py`, lines 188-191:
```python
return tpl.TemplateResponse(
    "arenas/index.html",
    {"request": request, "user": current_user},
)
```

No `arenas` key in the context dict.

File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/arenas/index.html`, line 20:
```html
<strong>{{ arenas | length }} data collection arenas</strong>
```

Jinja2's `length` filter on an undefined variable (which defaults to `Undefined` in Jinja2 strict mode, or empty string in non-strict mode) will produce `0`.

The rest of the page works because the Alpine.js `arenaOverview()` component fetches arenas from `/api/arenas/` on `init()`. But the server-side narrative text is always wrong.

**Suggested fix:** Either:
- (a) Pass `arenas` from the page handler by querying the arena registry, or
- (b) Make the narrative text dynamic using Alpine.js (e.g., `x-text="arenas.length + ' data collection arenas'"`).

File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/routes/pages.py` or
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/arenas/index.html` `[frontend]`

---

## 4. Query Designs Page (/query-designs)

### 4.1 Always Shows Empty State

**Page:** `/query-designs`
**What looks wrong:** The page always displays the "No query designs yet" empty state with a CTA button, even if the user has created query designs, because the route handler does not pass `designs` to the template.

**Evidence:**
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/routes/pages.py`, lines 214-217:
```python
return tpl.TemplateResponse(
    "query_designs/list.html",
    {"request": request, "user": current_user},
)
```

No `designs` key.

File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/query_designs/list.html`, line 25:
```html
{% if designs | default([]) | length > 0 %}
```

Since `designs` is not passed, `default([])` produces an empty list, `length` is 0, and the template always shows the empty state block (lines 138-145).

**Suggested fix:** In the page handler, query the database for `QueryDesign` records owned by the current user and pass them as `designs`.
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/routes/pages.py`, modify `query_designs_list()`. `[core]`

---

## 5. Collections Page (/collections)

### 5.1 Always Shows Empty State

**Page:** `/collections`
**What looks wrong:** Same pattern as Query Designs -- the page always shows "No collections yet" empty state because the route handler does not pass `runs`.

**Evidence:**
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/routes/pages.py`, lines 347-350:
```python
return tpl.TemplateResponse(
    "collections/list.html",
    {"request": request, "user": current_user},
)
```

No `runs` key.

File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/collections/list.html`, line 27:
```html
{% if runs | default([]) | length > 0 %}
```

Always evaluates to false.

**Suggested fix:** Query `CollectionRun` records in the handler and pass as `runs`.
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/routes/pages.py`, modify `collections_list()`. `[core]`

---

## 6. Actors Page (/actors)

### 6.1 Double Row Rendering from Missing Fragment

**Page:** `/actors`
**What looks wrong:** Each actor row is rendered twice -- once from the `{% include %}` with `ignore missing`, and once from the inline fallback that follows it.

**Evidence:**
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/actors/list.html`, lines 228-231:
```html
{% for actor in actors %}
{% include '_fragments/actor_row.html' ignore missing %}
{# Fallback inline row if fragment doesn't exist yet #}
<tr class="hover:bg-gray-50 transition-colors" id="actor-row-{{ actor.id }}">
```

The file `_fragments/actor_row.html` does **NOT exist** (confirmed by glob search). The `ignore missing` directive causes Jinja2 to silently skip the include. Then the inline `<tr>` is always rendered. **If the fragment DID exist, BOTH would render.**

Currently this means only the inline row renders (which is correct behavior for a missing fragment). But the intent was clearly "either/or" -- the comment says "Fallback inline row if fragment doesn't exist yet." The code does not implement this conditional: it would need `{% if _fragments/actor_row.html exists %}...{% else %}...{% endif %}`, which Jinja2 does not natively support.

**Severity:** Low -- currently works correctly by accident (fragment is missing so only inline renders). But if someone creates `_fragments/actor_row.html` later, every actor will appear twice.

**Suggested fix:** Remove the `{% include ... ignore missing %}` line entirely and keep only the inline row. Or create the fragment file and remove the inline fallback.
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/actors/list.html` `[frontend]`

**Note:** The actors page handler DOES correctly pass `actors` to the template (pages.py lines 575-583). This page is one of the few list pages that works correctly.

---

## 7. Analysis Page (/analysis)

### 7.1 Silent Redirect to Collections

**Page:** `/analysis`
**What looks wrong:** Clicking "Analysis" in the sidebar navigates the researcher to `/collections` with no explanation. There is no indication that they need to select a collection run first, or that the analysis page requires a run_id.

**Evidence:**
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/routes/analysis.py`, lines 133-140:
```python
@router.get("/", include_in_schema=False)
async def analysis_index_redirect() -> RedirectResponse:
    """Redirect to the collections list with a prompt to select a run."""
    return RedirectResponse(url="/collections", status_code=status.HTTP_302_FOUND)
```

The redirect goes to `/collections` with no query parameter, flash message, or UI cue. The researcher clicks "Analysis" and ends up on the collections list, confused about why they are there.

Additionally, with `hx-boost="true"`, HTMX will intercept this redirect. When it receives a 302, HTMX follows the redirect and swaps the response body. This should work but the experience is disorienting.

**Suggested fix:** Either:
- (a) Show a landing page at `/analysis` that says "Select a collection run to analyse" with links to recent runs, or
- (b) Add a `?from=analysis` parameter to the redirect and show a banner on the collections page.

File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/routes/analysis.py` `[frontend]`

---

## 8. Admin: System Status (/admin/health)

### 8.1 Infrastructure Status Swaps Raw JSON into HTML Container

**Page:** `/admin/health`
**What looks wrong:** The infrastructure status section uses HTMX to poll `GET /api/health`, which returns a JSON response. HTMX swaps this raw JSON text into the `#infrastructure-status` div, displaying something like `{"status":"ok","version":"0.1.0","database":"ok","redis":"ok","timestamp":"2026-02-22T..."}` instead of styled status cards.

**Evidence:**
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/admin/health.html`, lines 37-42:
```html
<div id="infrastructure-status"
     hx-get="/api/health"
     hx-trigger="load, every 15s"
     hx-target="#infrastructure-status"
     hx-swap="innerHTML"
     hx-indicator="#health-spinner">
```

File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/routes/health.py`, lines 89-120:
```python
@router.get("/api/health", include_in_schema=True)
async def system_health() -> JSONResponse:
    ...
    return JSONResponse(payload)
```

The endpoint returns `JSONResponse` -- HTMX receives `application/json` content. When HTMX swaps this into the div, it displays raw JSON text.

**Suggested fix:** Create an HTML fragment endpoint (e.g., `GET /admin/health/status`) that returns a rendered HTML partial with styled status cards, and point the HTMX `hx-get` at that endpoint instead. The `/api/health` endpoint should remain as-is for API consumers.
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/admin/health.html` and a new route handler. `[core]` `[frontend]`

### 8.2 Arena Health Also Swaps Raw JSON

**Page:** `/admin/health`
**What looks wrong:** Same issue -- `GET /api/arenas/health` returns `JSONResponse`, but the template swaps it into `#arena-health` innerHTML.

**Evidence:**
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/admin/health.html`, lines 104-108:
```html
<div id="arena-health"
     hx-get="/api/arenas/health"
     hx-trigger="load, every 60s"
     hx-target="#arena-health"
     hx-swap="innerHTML">
```

File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/routes/health.py`, lines 152-198:
The endpoint returns `JSONResponse(payload)`.

**Suggested fix:** Same approach -- create an HTML fragment endpoint or add content negotiation (return HTML when `Accept: text/html`, JSON otherwise).
File: same as 8.1 `[core]` `[frontend]`

---

## 9. Admin: Credit Allocation (/admin/credits)

### 9.1 Danish Placeholder Text

**Page:** `/admin/credits`
**What looks wrong:** The credit amount input has a Danish placeholder: `placeholder="f.eks. 1000"` which should be English per the project's UI language standard.

**Evidence:**
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/admin/credits.html`, line 44:
```html
<input type="number" id="credits_amount" name="credits_amount"
       min="1" required placeholder="f.eks. 1000"
```

**Suggested fix:** Change to `placeholder="e.g. 1000"`.
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/admin/credits.html` `[frontend]`

---

## 10. Scraping Jobs (/scraping-jobs)

### 10.1 Dialog Button Missing Alpine x-data Scope

**Page:** `/scraping-jobs`
**What looks wrong:** The "New Scraping Job" button uses `@click="$refs.createDialog.showModal()"` (line 14), which requires Alpine.js `$refs` context. However, the button is not inside an `x-data` scope. The `<dialog>` element with `x-ref="createDialog"` is at line 44, outside the button's parent hierarchy.

**Evidence:**
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/scraping/index.html`, lines 13-15:
```html
<button type="button"
        @click="$refs.createDialog.showModal()"
        class="...">
```

Line 44:
```html
<dialog x-ref="createDialog" ...>
```

The button and dialog are siblings under `{% block content %}`, but neither is wrapped in an `x-data` scope that would provide `$refs`. Alpine requires `$refs` to be resolved within the same `x-data` component scope.

**Severity:** This will cause a JavaScript error when the button is clicked. The dialog will not open.

**Suggested fix:** Wrap the entire content block (or at least the button + dialog pair) in a parent `<div x-data>` to establish an Alpine scope.
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/scraping/index.html` `[frontend]`

---

## 11. Import Data (/imports)

### 11.1 Upload Target Endpoint Uncertainty

**Page:** `/imports`
**What looks wrong:** The upload form posts to `hx-post="/api/content/import"` (line 32). The route registration in main.py shows `imports.router` mounted at prefix `/api` (line 384). Need to verify the actual endpoint path matches.

**Evidence:**
File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/imports/index.html`, line 32:
```html
<form hx-post="/api/content/import"
```

File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/main.py`, line 384:
```python
application.include_router(imports.router, prefix="/api", tags=["imports"])
```

If the imports router defines a route at `/content/import`, the full path would be `/api/content/import`, which matches. This needs verification of the actual route definition in `routes/imports.py`.

**Severity:** Low -- likely correct but should be verified with a live test. `[qa]`

---

## 12. Content Browser (/content)

### 12.1 Filter Sidebar is Intentional (Not Duplication)

**Page:** `/content`
**What looks wrong:** The page has two sidebars visible -- the navigation sidebar from base.html and a filter sidebar within the content area. This is by design, not a duplication bug. The filter sidebar is semantically different (`<aside class="w-64">` with filter form controls).

**Severity:** Not a bug. But on a laptop screen (1366x768 or smaller), having a 256px nav sidebar + 256px filter sidebar + content area could cause horizontal overflow or a cramped main area.

**Suggested fix:** Consider making the filter sidebar collapsible on smaller screens, or moving filters to a top bar on narrow viewports. `[frontend]`

---

## 13. Explore Page (/explore)

### 13.1 No Issues Found

The explore page correctly fetches arenas from `/api/arenas/` using `data.filter(...)` (line 222). The Alpine component handles loading and error states. No template variable issues.

---

## 14. Admin: Users (/admin/users)

### 14.1 No Issues Found

The page handler correctly passes `users` to the template (pages.py line 830). The "Create User" button uses `x-data` + `$dispatch('open-create-user')` pattern which correctly establishes an Alpine scope. The modal uses a separate `x-data="{ open: false }"` with window event listener. This pattern works correctly.

---

## 15. Admin: API Keys (/admin/credentials)

### 15.1 No Issues Found

The page handler correctly passes `credentials` to the template (pages.py line 908). The modal pattern uses `$dispatch('open-add-credential')` which works the same as the users page. The `credentialForm()` Alpine component correctly tracks `platform` state for conditional field display.

---

## Summary of All Findings

### Blockers (prevent researcher from completing task)

| # | Page | Issue | Responsible |
|---|------|-------|-------------|
| B-1 | /query-designs | Always shows empty state regardless of data | [core] |
| B-2 | /collections | Always shows empty state regardless of data | [core] |
| B-3 | /admin/health | Infrastructure and arena status display raw JSON | [core] [frontend] |
| B-4 | /scraping-jobs | "New Scraping Job" button does not open dialog (Alpine scope missing) | [frontend] |

### Friction Points (works but confusing or wrong)

| # | Page | Issue | Responsible |
|---|------|-------|-------------|
| F-1 | /dashboard | Volume spikes card stays hidden even when spikes exist (Alpine/HTMX disconnect) | [frontend] |
| F-2 | /dashboard | Volume spikes endpoint returns JSON-encoded string instead of HTML | [core] |
| F-3 | /dashboard | "Records Collected" card permanently shows dash placeholder | [core] [frontend] |
| F-4 | /arenas | Narrative text says "0 data collection arenas" (missing template variable) | [frontend] |
| F-5 | /analysis | Silent redirect to /collections with no explanation | [frontend] |
| F-6 | /admin/credits | Danish placeholder text "f.eks. 1000" | [frontend] |
| F-7 | /actors | Latent double-row bug from `ignore missing` + inline fallback | [frontend] |

### Notes (not bugs, but worth awareness)

| # | Page | Note |
|---|------|------|
| N-1 | /content | Dual sidebar (nav + filters) is by design but may be cramped on laptops |
| N-2 | All pages | `hx-boost="true"` on body means all navigation is HTMX-intercepted; redirect chains and JSON API responses can cause unexpected rendering |
| N-3 | /imports | Upload endpoint path `/api/content/import` should be verified against actual route registration |

---

## Recommended Fix Priority

1. **B-1 and B-2** (query-designs and collections empty state): These are the two most-visited pages after the dashboard. A researcher who creates a query design and then navigates to the list page will see "No query designs yet" -- they will think their work was lost. Fix by adding DB queries in the page handlers.

2. **B-3** (admin/health raw JSON): An admin checking system status sees raw JSON instead of formatted cards. Fix by creating HTML fragment endpoints or adding content negotiation.

3. **B-4** (scraping-jobs dialog): The "New Scraping Job" button is non-functional. Fix by wrapping the content block in `<div x-data>`.

4. **F-1 and F-2** (dashboard volume spikes): Fix the hidden card issue by removing the Alpine x-data/hidden pattern and fixing the return type of the volume spikes endpoint.

5. **F-3** (dashboard records count): Add a server endpoint or render the count server-side.

6. **F-4** (arenas narrative): Either pass the count from the server or make the text Alpine-driven.

7. **F-5** (analysis redirect): Add a landing page or at minimum a flash message.

8. **F-6** (Danish placeholder): One-line fix, change "f.eks." to "e.g."

9. **F-7** (actors double-row): Remove the dead `{% include %}` line.
