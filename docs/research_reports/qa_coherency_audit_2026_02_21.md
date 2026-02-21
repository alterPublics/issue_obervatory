# QA Coherency Audit -- 2026-02-21

**Auditor:** QA Guardian Agent
**Scope:** Full code-level coherency audit of the Issue Observatory codebase
**Date:** 2026-02-21
**Codebase size:** 248 Python source files (src/), 69 test files

---

## Executive Summary

This audit systematically examined the Issue Observatory codebase for disconnected code paths, missing links between layers, and half-wired features. The audit identified **7 critical**, **10 moderate**, and **8 minor** issues across routes, templates, Celery tasks, the event bus, and test coverage.

The most impactful findings are:
1. The credits route module is a stub -- all credit balance endpoints referenced by every page are 404s.
2. Health check task dispatch uses wrong task names -- none of the 25 arena health checks can be dispatched.
3. The actors list/detail pages have no HTML page routes -- the nav link to `/actors` returns JSON.
4. The discovered links page crashes on load due to a non-existent model attribute reference.
5. Beat schedule entries for RSS Feeds and GDELT call arena tasks without required arguments.

---

## Critical Findings

### C-01: Credits route module is an empty stub -- all credit balance endpoints return 404

**Files:**
- `/src/issue_observatory/api/routes/credits.py` (lines 1--14)
- `/src/issue_observatory/api/templates/dashboard/index.html` (line 49)
- `/src/issue_observatory/api/templates/_partials/credit_badge.html` (line 11)
- `/src/issue_observatory/api/templates/admin/credits.html` (line 18)

**Issue:** The `credits.py` route module contains only a docstring and an empty router -- no endpoints are implemented. However, the following frontend elements make HTMX requests to credit endpoints that do not exist:

- `hx-get="/credits/balance"` -- called on **every page load** via the `credit_badge.html` partial in the navigation sidebar, and again on the dashboard page. This fires on load and every 30 seconds.
- `hx-post="/admin/credits/allocate"` -- called from the admin credits page.

Since the router is mounted at `/credits` prefix and has zero routes, every HTMX poll returns a 404, which silently fails in the browser but generates continuous error noise in logs.

**Severity:** CRITICAL -- Every authenticated page load generates a 404 error on the credit badge poll. The admin credits page is entirely non-functional.

**Suggested fix:** Implement `GET /credits/balance` returning an HTML fragment with `credits_available` and `credits_reserved` values queried from `CreditService.get_balance()`. Implement `POST /credits/allocate` for the admin allocation form.

---

### C-02: Health check task dispatcher generates incorrect task names

**Files:**
- `/src/issue_observatory/workers/tasks.py` (line 379)
- All 25 arena `tasks.py` files (e.g., `/src/issue_observatory/arenas/rss_feeds/tasks.py` line 365)

**Issue:** The `health_check_all_arenas` task (line 379) generates dispatched task names using the pattern:

```
{arena_package}.tasks.{platform_name}_health_check
```

For example, for RSS Feeds it generates:
```
issue_observatory.arenas.rss_feeds.tasks.rss_feeds_health_check
```

But every arena registers its health check task with the name:
```
issue_observatory.arenas.rss_feeds.tasks.health_check
```

The `_health_check` suffix pattern in the dispatcher appends `{platform_name}_health_check`, but the actual registered task name is simply `health_check`. This means **none of the 25 arena health checks can be dispatched** by the periodic beat task.

**Severity:** CRITICAL -- The admin health dashboard (`/admin/health`) and the `health_check_all_arenas` beat entry (every 5 minutes) silently fail for all arenas.

**Suggested fix:** Change line 379 in `workers/tasks.py` from:
```python
task_name = f"{arena_package}.tasks.{platform_name}_health_check"
```
to:
```python
task_name = f"{arena_package}.tasks.health_check"
```

---

### C-03: `discovered_links_page` references non-existent model attribute `QueryDesign.created_by`

**Files:**
- `/src/issue_observatory/api/routes/pages.py` (line 501)
- `/src/issue_observatory/core/models/query_design.py` (line 57: `owner_id`)

**Issue:** The `discovered_links_page` route in `pages.py` line 501 filters query designs with:
```python
.where(QueryDesign.created_by == current_user.id)
```

But the `QueryDesign` model defines `owner_id` (line 57), not `created_by`. The `created_by` attribute exists on `ActorList` (line 269 of the same file), not on `QueryDesign`. This will raise an `AttributeError` at runtime when any user navigates to `/content/discovered-links`.

**Severity:** CRITICAL -- The discovered links page (`/content/discovered-links`) crashes on every request.

**Suggested fix:** Change `QueryDesign.created_by` to `QueryDesign.owner_id` on line 501 of `pages.py`.

---

### C-04: No HTML page routes for actors list and detail pages

**Files:**
- `/src/issue_observatory/api/routes/pages.py` -- missing `/actors` and `/actors/{actor_id}` page routes
- `/src/issue_observatory/api/routes/actors.py` -- returns JSON for `GET /actors/` and `GET /actors/{actor_id}`
- `/src/issue_observatory/api/templates/actors/list.html` -- exists but never rendered as full page
- `/src/issue_observatory/api/templates/actors/detail.html` -- exists but never rendered as full page
- `/src/issue_observatory/api/templates/_partials/nav.html` (line 24) -- links to `/actors`

**Issue:** The navigation sidebar links to `/actors` (nav.html line 24), and templates like `actors/list.html` and `actors/detail.html` extend `base.html` and expect rich template context (`actors`, `actor`, `presences`, `content_cursor`). However:

1. There are no page routes in `pages.py` for `/actors` or `/actors/{actor_id}`.
2. The actors API router at `/actors/` returns `list[ActorResponse]` JSON (or a minimal HTML `<ul>` fragment for HTMX requests), not a full page render.
3. The actor detail endpoint `GET /actors/{actor_id}` returns `ActorResponse` JSON.

Clicking "Actors" in the navigation sidebar serves a JSON array to the browser instead of the `actors/list.html` template.

**Severity:** CRITICAL -- The Actor Directory page and all actor detail pages are inaccessible through normal navigation. Users see raw JSON.

**Suggested fix:** Add page routes in `pages.py`:
```python
@router.get("/actors", response_class=HTMLResponse)
async def actors_list_page(request, current_user, db):
    tpl = _templates(request)
    # Fetch actors and render actors/list.html
    ...

@router.get("/actors/{actor_id}", response_class=HTMLResponse)
async def actor_detail_page(request, actor_id, current_user, db):
    tpl = _templates(request)
    # Fetch actor, presences, content and render actors/detail.html
    ...
```

---

### C-05: Celery Beat schedule dispatches RSS Feeds and GDELT tasks without required arguments

**Files:**
- `/src/issue_observatory/workers/beat_schedule.py` (lines 100--118)
- `/src/issue_observatory/arenas/rss_feeds/tasks.py` (lines 146--155: signature requires `query_design_id`, `collection_run_id`, `terms`)
- `/src/issue_observatory/arenas/gdelt/tasks.py` (lines 111--120: signature requires `query_design_id`, `collection_run_id`, `terms`)

**Issue:** The beat schedule defines two periodic tasks:

```python
"rss_feeds_collect_terms": {
    "task": "issue_observatory.arenas.rss_feeds.tasks.collect_by_terms",
    "schedule": crontab(minute="*/15"),
}
"gdelt_collect_terms": {
    "task": "issue_observatory.arenas.gdelt.tasks.collect_by_terms",
    "schedule": crontab(minute="*/15"),
}
```

Both task functions require `query_design_id`, `collection_run_id`, and `terms` as mandatory positional/keyword arguments. The beat schedule entries provide no `args` or `kwargs`, so every 15-minute invocation immediately fails with a `TypeError` for missing arguments.

These tasks are redundant with `trigger_daily_collection`, which correctly iterates over live-tracking query designs and dispatches arena tasks with proper arguments.

**Severity:** CRITICAL -- Every 15-minute dispatch generates a `TypeError` in the Celery worker. The tasks fail silently (no retry configured for `TypeError`). This produces continuous error noise in worker logs.

**Suggested fix:** Remove the `rss_feeds_collect_terms` and `gdelt_collect_terms` entries from `beat_schedule.py`. Collection for all arenas is already orchestrated by `trigger_daily_collection` at midnight.

---

### C-06: Event bus `emit_event` function does not exist

**Files:**
- `/src/issue_observatory/workers/tasks.py` (line 850)
- `/src/issue_observatory/core/event_bus.py` -- defines `publish_task_update` and `publish_run_complete`, but NOT `emit_event`

**Issue:** The `enrich_collection_run` task (line 850 of `workers/tasks.py`) imports and calls:
```python
from issue_observatory.core.event_bus import emit_event
emit_event(run_id, {...})
```

But `event_bus.py` defines only `publish_task_update`, `publish_run_complete`, and `elapsed_since`. There is no `emit_event` function. This will raise an `ImportError` at runtime when the SB-03 discovery notification code path is reached.

The import is inside a try/except block so it will not crash the enrichment task, but the discovery summary SSE event will never be delivered to the frontend.

**Severity:** CRITICAL -- The SB-03 post-collection discovery notification feature is completely non-functional. The `discovery_summary` SSE event is never emitted.

**Suggested fix:** Either rename the import to use `publish_task_update` with appropriate message formatting, or add an `emit_event` function to `event_bus.py` that wraps `publish_task_update` with a generic payload interface.

---

### C-07: Collections estimate endpoint is POST but launcher template uses hx-get

**Files:**
- `/src/issue_observatory/api/routes/collections.py` (line 311): `@router.post("/estimate", ...)`
- `/src/issue_observatory/api/templates/collections/launcher.html` (line 287): `hx-get="/collections/estimate"`

**Issue:** The credit estimate endpoint is defined as `POST /collections/estimate` (accepting a JSON `CreditEstimateRequest` body), but the collection launcher template fires an `hx-get` request with form data included via `hx-include`. The GET request will receive a 405 Method Not Allowed from FastAPI.

Note: The query design editor template (`editor.html` line 783) correctly uses `hx-post`, so this is specifically a launcher template issue.

**Severity:** CRITICAL -- The credit estimate panel in the collection launcher page never loads. Users cannot see cost estimates before launching a collection run.

**Suggested fix:** Change `hx-get` to `hx-post` on line 287 of `launcher.html`.

---

## Moderate Findings

### M-01: Dashboard `active-count` endpoint does not exist

**Files:**
- `/src/issue_observatory/api/templates/dashboard/index.html` (line 69): `hx-get="/collections/active-count"`
- `/src/issue_observatory/api/routes/collections.py` -- no `/active-count` endpoint defined

**Issue:** The dashboard card "Active Collections" polls `GET /collections/active-count` every 15 seconds. No such endpoint exists in the collections router. The HTMX request returns 404.

**Severity:** MODERATE -- The active collections count on the dashboard permanently shows "Loading..."

**Suggested fix:** Add a `GET /collections/active-count` endpoint that returns an HTML fragment with the count of runs where `status IN ('pending', 'running')`.

---

### M-02: Dashboard `format=fragment` parameter not handled by collections list endpoint

**Files:**
- `/src/issue_observatory/api/templates/dashboard/index.html` (line 107): `hx-get="/collections?limit=5&format=fragment"`
- `/src/issue_observatory/api/routes/collections.py` (line 101): no `format` parameter handling

**Issue:** The dashboard's "Recent Collections" section requests `GET /collections?limit=5&format=fragment`, expecting an HTML table body fragment. The collections list endpoint returns `list[CollectionRunRead]` JSON for all requests. The `format=fragment` query parameter is silently ignored.

**Severity:** MODERATE -- The recent collections section on the dashboard shows raw JSON instead of a formatted table.

**Suggested fix:** Add a `format` query parameter to `list_collection_runs` that returns an HTML fragment (e.g., rendered from `_fragments/run_summary.html`) when `format=fragment`.

---

### M-03: Admin health page endpoints `/admin/health/status` and `/admin/health/arenas` do not exist

**Files:**
- `/src/issue_observatory/api/templates/admin/health.html` (lines 38, 67)
- `/src/issue_observatory/api/routes/health.py` -- defines `/api/health` and `/api/arenas/health` only

**Issue:** The admin health template polls:
- `hx-get="/admin/health/status"` (line 38)
- `hx-get="/admin/health/arenas"` (line 67)

The actual health endpoints are at `/api/health` and `/api/arenas/health`. The `/admin/health/*` paths are not defined anywhere, so both HTMX requests return 404.

**Severity:** MODERATE -- The admin health dashboard shows permanent loading spinners for both infrastructure status and arena health.

**Suggested fix:** Either add HTMX-returning routes at `/admin/health/status` and `/admin/health/arenas` that render HTML fragments, or update the template to point to `/api/health` and `/api/arenas/health` with appropriate response handling.

---

### M-04: Navigation logout link points to `/auth/logout` but actual endpoint is `/auth/cookie/logout` (POST)

**Files:**
- `/src/issue_observatory/api/templates/_partials/nav.html` (line 86): `href="/auth/logout"`
- `/src/issue_observatory/api/routes/auth.py` (line 136): actual path is `POST /auth/cookie/logout`

**Issue:** The sidebar's "Sign out" link is a plain `<a href="/auth/logout">` which issues a GET request to `/auth/logout`. The FastAPI-Users cookie logout endpoint is at `POST /auth/cookie/logout`. The GET to `/auth/logout` returns 404 (or 405 if it were found).

**Severity:** MODERATE -- Users cannot log out through the UI.

**Suggested fix:** Change the logout link to a form submission:
```html
<form method="post" action="/auth/cookie/logout">
    <button type="submit" class="...">Sign out</button>
</form>
```

---

### M-05: `publish_run_complete` is defined but never called

**Files:**
- `/src/issue_observatory/core/event_bus.py` (line 133): `def publish_run_complete(...)`
- Searched entire codebase: no callers found

**Issue:** The `publish_run_complete` function is defined to send a `run_complete` SSE event when all arena tasks finish, but no orchestration code ever calls it. The SSE stream in `collections.py` subscribes to the Redis channel and waits for a `run_complete` event, but since nothing publishes this event, live-tracking SSE connections never receive the terminal event. They will time out or detect completion only on their next database poll (which does not happen in the SSE implementation).

`publish_task_update` is also barely used -- only the Google Search arena tasks call it (1 of 25 arenas).

**Severity:** MODERATE -- SSE live monitoring of collection runs never receives a terminal `run_complete` event from 24 of 25 arenas. The SSE stream hangs indefinitely until the client disconnects.

**Suggested fix:** Each arena's `collect_by_terms` task should call `publish_task_update` at status transitions. A higher-level orchestration task (or the `settle_pending_credits` task) should call `publish_run_complete` when all arena tasks for a run have reached terminal states.

---

### M-06: `get_arenas_by_arena_name` is defined but never called

**Files:**
- `/src/issue_observatory/arenas/registry.py` (line 322): `def get_arenas_by_arena_name(...)`

**Issue:** This function filters the registry by the logical `arena_name` grouping label and returns all matching collectors. It is never called from any route, task, or other module in the codebase.

**Severity:** MINOR (reclassified from moderate -- dead code but no functional impact)

**Suggested fix:** Either remove the function or document its intended use case. If it is meant for future multi-collector arena dispatching, add a test.

---

### M-07: Only 1 of 25 arenas publishes SSE task_update events

**Files:**
- `/src/issue_observatory/arenas/google_search/tasks.py` (line 48): imports `publish_task_update`
- All other 24 arena `tasks.py` files: do not import or call `publish_task_update`

**Issue:** The SSE live collection monitoring system is designed to receive `task_update` events from each arena as collection progresses. Only the Google Search arena calls `publish_task_update`. All other arenas update the `collection_tasks` database table but do not emit SSE events. This means the live monitoring page shows updates only for Google Search; all other arenas appear frozen.

**Severity:** MODERATE -- Live monitoring SSE is effectively non-functional for 24 of 25 arenas.

**Suggested fix:** Add `publish_task_update` calls to all arena tasks at the `running` (start), `completed`, and `failed` transitions.

---

### M-08: `_build_sync_dsn` duplicated across two files

**Files:**
- `/src/issue_observatory/workers/maintenance_tasks.py` (line 51)
- `/src/issue_observatory/workers/export_tasks.py` (line 94)

**Issue:** The `_build_sync_dsn` helper function is copy-pasted identically in both files. Any bug fix or enhancement needs to be applied in both places.

**Severity:** MODERATE -- Code duplication creates maintenance risk.

**Suggested fix:** Extract into a shared utility, e.g., `workers/_db_helpers.py`, and import from both modules.

---

### M-09: Missing test coverage for critical paths

**Files:**
- `/tests/` directory structure

**Issue:** The following critical modules have **zero test files**:

| Module | Test coverage |
|--------|--------------|
| `core/retention_service.py` | No tests |
| `core/event_bus.py` | No tests |
| `core/email_service.py` | No tests |
| `core/entity_resolver.py` | No tests |
| `api/routes/collections.py` | No route tests |
| `api/routes/content.py` | Only `test_content_route_search_terms.py` (1 specific test) |
| `api/routes/actors.py` | Only `test_actors_snowball_schema.py` (schema test only) |
| `api/routes/analysis.py` | Only `test_analysis_phase_d_routes.py` and filter options (limited) |
| `api/routes/query_designs.py` | Only `test_clone_query_design.py` (1 integration test) |
| `workers/tasks.py` | Only `test_task_helpers.py` (helpers, not orchestration tasks) |
| `analysis/coordination.py` | Only enrichment detector test |
| `analysis/propagation.py` | No tests |

Out of 248 source files, only 69 test files exist, and many test files cover only happy-path scenarios.

**Severity:** MODERATE -- Critical functionality (GDPR retention, credit settlement, collection orchestration, SSE streaming, export pipeline) has no test coverage.

**Suggested fix:** Prioritize test creation for: (1) retention_service (GDPR compliance), (2) collections routes (core user workflow), (3) workers/tasks.py orchestration (production reliability).

---

### M-10: `refresh_engagement_metrics` task creates new event loops inside a synchronous Celery worker

**Files:**
- `/src/issue_observatory/workers/maintenance_tasks.py` (lines 418--425)

**Issue:** The engagement refresh task creates a new `asyncio` event loop per batch inside a synchronous Celery worker:
```python
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
try:
    engagement_map = loop.run_until_complete(
        collector.refresh_engagement(platform_ids, tier=tier)
    )
finally:
    loop.close()
```

This pattern is fragile under Celery's worker process model. Other tasks in `workers/tasks.py` use `asyncio.run()` instead, which is the safer pattern. Creating/setting/closing event loops manually can leak resources or interfere with other Celery tasks running in the same worker process.

**Severity:** MODERATE -- Potential resource leak or worker instability under concurrent task execution.

**Suggested fix:** Replace with `asyncio.run()` to match the pattern used in all other Celery tasks.

---

## Minor Findings

### m-01: Unused template `_fragments/credit_estimate.html` may not be connected

**Files:**
- `/src/issue_observatory/api/templates/_fragments/credit_estimate.html`

**Issue:** This fragment template exists but it is unclear whether any route renders it. The estimate endpoint returns a `CreditEstimateResponse` JSON model, not an HTML fragment. The launcher template targets `#estimate-panel` for the response, but the endpoint returns JSON.

**Severity:** MINOR -- Fragment template exists but may not be rendered by any code path.

---

### m-02: `_normalise_url` duplicated between `core/deduplication.py` and `workers/maintenance_tasks.py`

**Files:**
- `/src/issue_observatory/workers/maintenance_tasks.py` (line 63)
- `/src/issue_observatory/core/deduplication.py` (original implementation)

**Issue:** URL normalization logic is duplicated. The docstring in `maintenance_tasks.py` explicitly notes this duplication.

**Severity:** MINOR -- Documented technical debt.

---

### m-03: Twitch and VKontakte stub arenas included in health check dispatch

**Files:**
- `/src/issue_observatory/arenas/twitch/tasks.py` -- stub with health check task
- `/src/issue_observatory/arenas/vkontakte/tasks.py` -- stub with health check task
- `/src/issue_observatory/workers/tasks.py` (health_check_all_arenas)

**Issue:** Twitch and VKontakte are deferred stubs with no functional collectors, but they register health check tasks. The `health_check_all_arenas` task dispatches health checks for them. While the tasks themselves handle this gracefully (returning "not_implemented"), it adds noise to the admin health dashboard.

**Severity:** MINOR -- No functional impact; slight UI noise.

---

### m-04: `ARENA_DESCRIPTIONS` has an entry for `"google"` which is not a registered platform_name

**Files:**
- `/src/issue_observatory/arenas/registry.py` (line 95--97)

**Issue:** The description for `"google"` is a fallback comment noting that both Google collectors use distinct platform names. This key will never match any registered collector's `platform_name`.

**Severity:** MINOR -- Dead configuration entry.

---

### m-05: `analysis/design/{design_id}` HTML page route renders `analysis/design.html` but has no page route in `pages.py`

**Files:**
- `/src/issue_observatory/api/routes/analysis.py` (line 1534): `GET /analysis/design/{design_id}`
- `/src/issue_observatory/api/templates/analysis/design.html`

**Issue:** The analysis route module provides its own HTML rendering for the design-level analysis page at `GET /analysis/design/{design_id}`, which is fine. However, this route is not listed in the `pages.py` docstring and uses a different URL pattern than other pages (no `/analysis/design/{id}` in the nav). Users can only reach it through direct links from collection detail pages.

**Severity:** MINOR -- Discoverability issue; no functional impact.

---

### m-06: `analysis/compare` endpoint exists but no template references it

**Files:**
- `/src/issue_observatory/api/routes/analysis.py` (line 230): `GET /analysis/compare`

**Issue:** The cross-run comparison endpoint exists in the API but no template or frontend code appears to reference it. The endpoint was implemented for SB-06 but the UI integration may be incomplete.

**Severity:** MINOR -- Backend feature without frontend exposure.

---

### m-07: No test for discord or url_scraper arena collectors

**Files:**
- `/tests/arenas/` -- no `test_discord.py` or `test_url_scraper.py`

**Issue:** The Discord and URL Scraper arenas are listed as "implemented" in CLAUDE.md but have no arena-level tests.

**Severity:** MINOR -- Reduced confidence in these arena implementations.

---

### m-08: Auth page route for `/auth/reset-password` exists as a template but no explicit page route in `pages.py`

**Files:**
- `/src/issue_observatory/api/templates/auth/reset_password.html`
- `/src/issue_observatory/api/routes/pages.py` -- no route for rendering this template

**Issue:** The password reset HTML template exists but there is no page route to render it. The FastAPI-Users password reset flow uses its own JSON endpoints (`POST /auth/forgot-password`, `POST /auth/reset-password`), so the HTML template may be intended for a custom UI that is not yet wired.

**Severity:** MINOR -- Template exists but may not be accessible.

---

## Summary Table

| ID | Severity | Category | Component | Status |
|----|----------|----------|-----------|--------|
| C-01 | CRITICAL | Missing endpoint | `credits.py` (stub) | All credit balance polling returns 404 |
| C-02 | CRITICAL | Wrong task names | `workers/tasks.py` line 379 | All 25 arena health checks fail to dispatch |
| C-03 | CRITICAL | Wrong attribute | `pages.py` line 501 | Discovered links page crashes (AttributeError) |
| C-04 | CRITICAL | Missing page routes | `pages.py` | Actors list/detail show JSON instead of HTML |
| C-05 | CRITICAL | Missing arguments | `beat_schedule.py` lines 100-118 | RSS/GDELT beat tasks fail every 15 minutes |
| C-06 | CRITICAL | Missing function | `event_bus.py` | SB-03 discovery notification ImportError |
| C-07 | CRITICAL | HTTP method mismatch | `launcher.html` line 287 | Credit estimate never loads in launcher |
| M-01 | MODERATE | Missing endpoint | `collections.py` | Dashboard active-count shows "Loading..." |
| M-02 | MODERATE | Missing parameter | `collections.py` | Dashboard recent runs shows JSON |
| M-03 | MODERATE | Wrong endpoint paths | `health.html` lines 38,67 | Admin health page shows loading spinners |
| M-04 | MODERATE | Wrong endpoint path | `nav.html` line 86 | Logout button returns 404 |
| M-05 | MODERATE | Unreachable code | `event_bus.py` line 133 | `publish_run_complete` never called |
| M-06 | MODERATE | Unreachable code | `registry.py` line 322 | `get_arenas_by_arena_name` never called |
| M-07 | MODERATE | Missing integration | 24 arena `tasks.py` files | SSE live monitoring broken for most arenas |
| M-08 | MODERATE | Code duplication | `maintenance_tasks.py`, `export_tasks.py` | `_build_sync_dsn` duplicated |
| M-09 | MODERATE | Test gaps | `/tests/` | No tests for retention, event bus, email, entity resolver |
| M-10 | MODERATE | Fragile pattern | `maintenance_tasks.py` lines 418-425 | Manual event loop in Celery worker |
| m-01 | MINOR | Unused template | `_fragments/credit_estimate.html` | May not be rendered |
| m-02 | MINOR | Code duplication | `maintenance_tasks.py` line 63 | `_normalise_url` duplicated |
| m-03 | MINOR | Noise | twitch/vkontakte stubs | Included in health check dispatch |
| m-04 | MINOR | Dead config | `registry.py` line 95 | `"google"` description never matched |
| m-05 | MINOR | Discoverability | `analysis.py` line 1534 | Design-level analysis not in nav |
| m-06 | MINOR | Unused endpoint | `analysis.py` line 230 | `compare` endpoint with no frontend |
| m-07 | MINOR | Test gap | discord, url_scraper | No arena tests |
| m-08 | MINOR | Unused template | `auth/reset_password.html` | No page route |

---

## Recommended Fix Priority

### Immediate (before any user testing)
1. **C-01**: Implement `GET /credits/balance` endpoint (stops 404 noise on every page)
2. **C-03**: Fix `QueryDesign.created_by` to `QueryDesign.owner_id` in `pages.py` line 501
3. **C-04**: Add actor list and detail page routes in `pages.py`
4. **C-07**: Change `hx-get` to `hx-post` in `launcher.html` line 287
5. **M-04**: Fix logout link to use POST to `/auth/cookie/logout`

### Short-term (within 1 week)
6. **C-02**: Fix health check task name generation in `workers/tasks.py`
7. **C-05**: Remove orphaned RSS/GDELT beat schedule entries
8. **C-06**: Add `emit_event` to `event_bus.py` or fix the import
9. **M-01, M-02**: Add dashboard-specific endpoints for active-count and fragment rendering
10. **M-03**: Fix admin health template endpoint paths

### Medium-term (within 2 weeks)
11. **M-05, M-07**: Wire SSE event publishing into all arena tasks
12. **M-09**: Write tests for retention_service, event_bus, collections routes
13. **M-08, m-02**: Extract shared utilities to eliminate duplication
14. **M-10**: Replace manual event loop with `asyncio.run()` in engagement refresh

---

*Report generated by QA Guardian Agent, 2026-02-21*
