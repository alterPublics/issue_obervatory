# UX Test Report -- Gronland Retest 2 (Post-Fix Verification)
Date: 2026-02-22
Arenas tested: RSS Feeds, GDELT, Ritzau Via, Bluesky, Reddit, YouTube, Gab, Wikipedia (configured; none collected data)
Tiers tested: FREE

## Context

This is the second retest following a batch of 9 fixes applied to issues identified in earlier rounds. The test scenario tracks "Gronland" (Greenland) sovereignty discourse across 8 Danish media arenas at the free tier. Testing was performed via direct HTTP requests against the running application at http://localhost:8000.

**Admin credentials**: admin@example.com / change-me-in-production

---

## Verification of Fixed Issues

### FIXED: B-NEW-3 -- HTMX forms now POST to form-encoded endpoints

**Endpoints tested**:
- `POST /query-designs/form` -- returned HTTP 303 redirect to `/query-designs/{id}/edit`
- `POST /collections/form` -- returned HTTP 303 redirect to `/collections/{run_id}`

Both form-encoded endpoints accept `application/x-www-form-urlencoded` data and redirect correctly. This resolves the blocker that prevented researchers from creating query designs and launching collections through the web interface.

**Verdict**: FIXED

### FIXED: M-1 -- Credential detection now uses load_dotenv()

**Endpoint tested**: `GET /api/arenas/`

Six arenas correctly report `has_credentials: true`:
- bluesky
- google_autocomplete
- google_search
- reddit
- tiktok
- youtube

The remaining 19 arenas correctly report `has_credentials: false`. This matches the expected configuration from the `.env` file.

**Verdict**: FIXED

### FIXED: F-1 -- Query design detail page shows search terms

**Endpoint tested**: `GET /query-designs/{design_id}`

The detail page for the newly created "Gronland Selvstyre 2026" design correctly displays all 4 search terms (gronland, selvstyre, rigsfaellesskab, Greenland) under the "Search Terms" heading. No "No search terms defined" message appears when terms exist.

**Verdict**: FIXED

### FIXED: F-4 -- Collections list shows "Analyse" link for failed runs with data

**Endpoint tested**: `GET /collections`

The collections list page shows an "Analyse" link for the failed run `1cd78707-5952-4421-a48e-c34311d48fa0` (which has 135 records). The link correctly points to `/analysis/{run_id}`. Failed runs without data do not show the Analyse link.

**Verdict**: FIXED

### FIXED: F-5 -- Arena config grid uses platform_name as identifier

**Endpoint tested**: `GET /query-designs/{design_id}/edit`

The arena config grid Alpine.js component uses `a.platform_name` as the entry identifier:
```javascript
id: a.platform_name,
```
This ensures each platform (e.g., reddit, youtube) is independently configurable even when multiple platforms share the same `arena_name` grouping (e.g., "social_media").

**Verdict**: FIXED

### FIXED: F-6 -- Collection launcher shows arena preview when design is selected

**Endpoint tested**: `GET /collections/new`

The launcher page includes a `loadArenaConfig()` function that fetches `GET /query-designs/{design_id}/arena-config` when a query design is selected and renders a summary table of enabled arenas with their tier badges. The researcher can see which arenas will be included before launching.

**Verdict**: FIXED

### FIXED: Stale run cleanup no longer marks fresh runs as stale

**Evidence**: The collection run `3ed1182d-1d20-4997-a2aa-1ae40980cdac` created during this test remained in "Pending" status for over 5 minutes without being prematurely marked as "Failed" by `cleanup_stale_runs`. The worker log shows the cleanup task is registered but produced no "exceeded" or "marked as failed" messages for the fresh run.

**Verdict**: FIXED

---

## NOT FIXED: B-NEW-2 -- asyncio event loop errors in Celery workers

**Severity**: BLOCKER -- All collections fail. No data can be collected.

The asyncio event loop error persists and is the root cause of total collection failure. The `dispatch_batch_collection` Celery task makes multiple `asyncio.run()` calls in sequence:

1. `asyncio.run(fetch_batch_run_details(run_uuid))` -- line 1068 -- succeeds (first call)
2. `asyncio.run(set_run_status(run_uuid, "running"))` -- line 1149 -- FAILS
3. `asyncio.run(fetch_public_figure_ids_for_design(design_id))` -- line 1159 -- FAILS (sometimes)
4. `asyncio.run(create_collection_tasks(run_uuid, arena_entries))` -- line 1197 -- FAILS
5. `asyncio.run(fetch_search_terms_for_arena(design_id, platform))` -- line 1216 -- FAILS for 4 of 8 arenas

After the first `asyncio.run()` call completes, the event loop is closed. Subsequent calls create new event loops, but asyncpg database connections created during the first call are cached in the SQLAlchemy connection pool and remain bound to the old (closed) event loop. This produces:

```
RuntimeError: Task <Task pending ...> got Future <Future pending ...> attached to a different loop
```

**Consequence**: Of 8 configured arenas, only 4 (rss_feeds, ritzau_via, reddit, gab) had their tasks dispatched. The other 4 (gdelt, bluesky, youtube, wikipedia) were skipped because `fetch_search_terms_for_arena` failed for them. The run status was never updated from "Pending" to "Running", and no CollectionTask rows were created, leaving the completion checker unable to track progress.

The pattern is stochastic -- the first `asyncio.run()` succeeds, the second sometimes succeeds and sometimes fails depending on whether the connection pool reuses a connection from the previous event loop or creates a new one. Arenas dispatched alternately succeed and fail as the pool cycles connections.

**Research impact**: The researcher sees a collection stuck at "Pending" forever, with no indication of what went wrong. No data is collected from any arena.

---

## New Blocker Discovered

### B-NEW-4: Arena tasks reject `public_figure_ids` keyword argument

**Severity**: BLOCKER -- Even when arena tasks are dispatched, they immediately fail.

The `dispatch_batch_collection` task passes `public_figure_ids` in the task kwargs (line 1249 of `tasks.py`):
```python
task_kwargs: dict[str, Any] = {
    "query_design_id": str(design_id),
    "collection_run_id": run_id,
    "terms": arena_terms,
    "tier": tier,
    "language_filter": language_filter,
    "public_figure_ids": public_figure_ids,  # <-- this parameter
}
```

But none of the arena task functions accept this parameter. All four dispatched arena tasks failed with:
```
TypeError: rss_feeds_collect_terms() got an unexpected keyword argument 'public_figure_ids'
TypeError: ritzau_via_collect_terms() got an unexpected keyword argument 'public_figure_ids'
TypeError: reddit_collect_terms() got an unexpected keyword argument 'public_figure_ids'
TypeError: gab_collect_terms() got an unexpected keyword argument 'public_figure_ids'
```

The arena task function signatures only accept:
- `query_design_id`, `collection_run_id`, `terms`, `tier`, `date_from`, `date_to`, `max_results`, `language_filter`

The `public_figure_ids` parameter (from GR-14) is dispatched by the orchestrator but not accepted by any arena task.

**Research impact**: This compounds B-NEW-2. Even if the event loop issue were resolved, every arena task would immediately crash. Zero records would be collected from any arena. The researcher sees a permanently stuck "Pending" collection with no error explanation.

---

## Friction Points

### F-NEW-1: Editor page does not pre-populate existing search terms [frontend]

**URL**: `GET /query-designs/{design_id}/edit`

When a researcher navigates to the editor page for a query design that already has search terms, the terms list is empty. The `<ul id="terms-list">` has no children and the message "No search terms yet" is displayed.

The terms do exist in the database (verified via the JSON API and the detail page). But the editor template renders the terms list as an empty `<ul>` and only populates it via the POST form's `hx-target="#terms-list"` when a NEW term is added.

**Research impact**: A researcher returning to edit their query design cannot see which terms they have already added. They cannot delete, reorder, or modify existing terms. They might add duplicate terms because they do not see the current state. This effectively makes the editor a one-shot tool -- usable when first creating a design but not for ongoing refinement.

### F-NEW-2: Collection detail stuck at "Pending" with no error information [frontend]

When a collection run fails to start due to worker errors, the detail page shows "Pending" status indefinitely with no error messages, no arena task list, and no indication that anything went wrong. The SSE connection is established but no events are received because the worker never publishes any.

A researcher would check the page repeatedly, waiting for something to happen, with no way to know that the collection has silently failed.

**Research impact**: Without any error feedback, the researcher has no recovery path except to ask a developer to check the Celery logs.

### F-NEW-3: Group labels not shown on query design detail page [frontend]

**URL**: `GET /query-designs/{design_id}`

The detail page shows the search terms but does not display their group labels (e.g., "Primary", "Governance", "English"). The group labels are stored in the database and returned in the JSON API response, but the HTML template does not render them.

**Research impact**: Minor -- the researcher designed their term groups on the editor page and can see them there. But the detail page gives an incomplete view of the query design structure.

---

## Passed

### P-1: Authentication flow
Login via `POST /auth/cookie/login` returns 204 with session cookie. All subsequent requests are authenticated. The dashboard renders with "Welcome, admin@example.com".

### P-2: Dashboard
No "Phase 0" text. Three summary cards (Credits, Active Collections, Records Collected) render. Quick Actions (New Query Design, New Collection) work. Recent Collections section loads.

### P-3: Query design creation via form endpoint
`POST /query-designs/form` accepts form-encoded data and redirects to the editor. The design is persisted with correct name ("Gronland Selvstyre 2026"), description, tier ("free"), language ("da"), and locale ("dk").

### P-4: Search term addition with group labels
`POST /query-designs/{id}/terms` accepts form-encoded data and returns HTTP 201 for each term. All 4 terms (gronland, selvstyre, rigsfaellesskab, Greenland) with groups (Primary, Governance, English) were created successfully.

### P-5: Arena configuration via JSON endpoint
`POST /query-designs/{id}/arena-config` accepts JSON body and returns HTTP 200 with the saved configuration. All 8 arenas (rss_feeds, gdelt, ritzau_via, bluesky, reddit, youtube, gab, wikipedia) were enabled at free tier.

### P-6: Collection launch via form endpoint
`POST /collections/form` accepts form-encoded data and redirects to the collection detail page. The collection run is created in the database and dispatched to Celery.

### P-7: Content browser with 135 existing records
The content browser at `/content/` renders 135 records from previous collection runs. Platform column shows "ritzau_via", arena column shows "news_media". Pagination, search, and filter controls are present.

### P-8: CSV and XLSX exports
- CSV export (`/content/export?format=csv`): 108 KB, correct headers (Platform, Arena, Content Type, Title, Text Content, URL, Author, etc.), proper UTF-8 encoding of Danish characters.
- XLSX export (`/content/export?format=xlsx`): 57 KB, valid spreadsheet format.

### P-9: GEXF export
`/content/export?format=gexf&network_type=term&run_id={run_id}` returns valid GEXF 1.3 XML (4 KB) with node attributes (type, frequency, degree) and weighted edges.

### P-10: Analysis dashboard with live data
`/analysis/{run_id}` renders with volume chart, actors tab, terms tab, network preview, and export panel. API endpoints return correct data:
- Summary: 135 records, 1 arena (news_media), date range Dec 2025 to Feb 2026
- Volume: Daily counts with arena breakdown
- Actors: Top authors with pseudonymized IDs (Taenketanken Prospekt, If Forsikring, etc.)
- Terms: Term frequency list (contaminated with stopwords -- see Data Quality)
- Network: 5 nodes, 10 edges (term co-occurrence)

### P-11: Arena overview page
All 25 arenas listed, organized by tier (Free/Medium/Premium). Credential indicators show green dots for the 6 configured arenas and gray dots for the rest. Descriptions, temporal mode indicators, and custom config fields are displayed.

### P-12: Actor directory
Mette Frederiksen appears with Person type and Public Figure badge. Add Actor form and Snowball Sampling panel are accessible.

---

## Data Quality Findings

### DQ-1: Stopword contamination persists in existing data

The 135 existing records from Ritzau Via contain `search_terms_matched` dominated by Danish stopwords:
- "i" (in/at): 95 records (70%)
- "er" (is): 92 records (68%)
- "et" (a/an): 66 records (49%)
- "og" (and): 34 records (25%)
- "den" (the): 28 records (21%)
- "klima" (actual search term): 15 records (11%)
- "energi" (actual search term): 6 records (4%)

**96 of 135 records (71%) matched ONLY on stopwords**, not on the actual search terms "klima" or "energi". These records are completely irrelevant to the research topic.

**Cannot verify whether the M-5 word-boundary fix resolves this** because no new collections can execute due to B-NEW-2 and B-NEW-4.

### DQ-2: Top terms analysis is meaningless with stopword contamination

The `/analysis/{run_id}/terms` endpoint returns:
1. "i" (95 matches)
2. "er" (92)
3. "et" (66)
4. "og" (34)
5. "den" (28)
6. "klima" (15)
7. "energi" (6)

A researcher viewing the "Top Terms" chart would see only common Danish grammar words, not discourse-relevant terms. The network analysis (term co-occurrence) is similarly contaminated -- all 5 nodes are stopwords.

### DQ-3: No new data collected in this test

Despite configuring 8 free-tier arenas and launching 2 collection runs, zero new records were collected. All arena tasks failed due to the `public_figure_ids` keyword argument error (B-NEW-4) and the asyncio event loop error (B-NEW-2).

---

## Recommendations

Ordered by priority (blockers first):

1. **[core] Fix `public_figure_ids` keyword argument mismatch (B-NEW-4)**: Either add `public_figure_ids: list[str] | None = None` to all arena task function signatures, or add `**kwargs` to absorb extra keyword arguments, or remove `public_figure_ids` from the dispatch `task_kwargs` and pass it through a different mechanism (e.g., store on the CollectionRun model, let each arena task load it from the DB). This is a one-line-per-arena fix that would immediately unblock all arena task dispatch.

2. **[core] Fix asyncio event loop / connection pool conflict (B-NEW-2)**: The pattern of multiple sequential `asyncio.run()` calls in `dispatch_batch_collection` is fundamentally incompatible with asyncpg connection pooling in Celery's prefork model. Options:
   - Create a single async coroutine that performs ALL the DB operations (fetch details, set status, fetch terms, create tasks) in one `asyncio.run()` call.
   - Use `loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)` with proper cleanup and a dedicated SQLAlchemy engine per invocation.
   - Switch to synchronous SQLAlchemy with psycopg2 for Celery tasks instead of async.
   - Dispose the engine connection pool between `asyncio.run()` calls.

3. **[frontend] Pre-populate existing search terms on editor page (F-NEW-1)**: The editor template should render existing terms into the `#terms-list` element when the page loads. This could be done server-side (render `<li>` elements in the Jinja2 template) or client-side (fetch terms via AJAX on page load and populate the list).

4. **[frontend] Show error state when collection fails silently (F-NEW-2)**: Add a timeout mechanism to the collection detail page that transitions the display from "Pending" to "Something may have gone wrong" after a configurable period (e.g., 2 minutes without SSE events). Include a link to retry or check system health.

5. **[data] Verify M-5 stopword fix once collections work**: The word-boundary matching fix for search term matching needs validation with live collection data. If stopwords still appear in `search_terms_matched` after the fix, consider implementing an explicit Danish stopword exclusion list.

6. **[frontend] Display group labels on query design detail page (F-NEW-3)**: Add the group label badge next to each search term on the detail page, matching the visual design used in the editor.

---

## End-to-End Workflow Assessment

### What works

The researcher CAN:
- Log in and navigate the application
- Create a query design with a name, description, language, and locale
- Add search terms with group labels
- Configure arena selection with tier assignments
- View which arenas have credentials configured
- Browse existing content records
- Export data in CSV, XLSX, and GEXF formats
- View analysis dashboards with charts, actor rankings, and network visualizations
- Manage actors and mark public figures

### What does not work

The researcher CANNOT:
- Collect any new data from any arena (blocked by B-NEW-2 + B-NEW-4)
- See their existing search terms when returning to the editor page (F-NEW-1)
- Understand why a collection is stuck at "Pending" (F-NEW-2)
- See meaningful term analysis (stopword contamination in existing data)

### Summary

Of the 9 previously reported issues:
- **7 are verified FIXED**: B-NEW-3, M-1, F-1, F-4, F-5, F-6, stale run cleanup
- **1 is NOT FIXED**: B-NEW-2 (asyncio event loop errors persist)
- **1 NEW BLOCKER discovered**: B-NEW-4 (public_figure_ids keyword argument rejected by all arena tasks)

The two remaining blockers (B-NEW-2 and B-NEW-4) are both in the collection dispatch pipeline and together prevent any data collection. B-NEW-4 is likely a simpler fix (add the missing parameter to arena task signatures). B-NEW-2 requires a more fundamental change to how the dispatch task manages async database operations.

The web interface improvements are substantial -- the form-encoded endpoints, credential detection, arena preview, and Analyse link all work correctly. The application is much closer to being functional, but the collection pipeline remains the critical gap.
