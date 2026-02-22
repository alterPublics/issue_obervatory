# UX Test Report -- Gronland Retest
Date: 2026-02-22
Arenas tested: RSS Feeds, GDELT, Ritzau Via, Bluesky, Reddit, YouTube, Wikipedia, Common Crawl, Wayback Machine, TikTok (configured but not executed)
Tiers tested: FREE

## Context

This is a retest following fixes applied to issues B-1, M-1 through M-5 identified in the previous test round. The test scenario tracks "Gronland" (Greenland) discourse across multiple Danish media arenas. Testing was performed via direct HTTP requests against the running application at http://localhost:8000.

**Admin credentials**: admin@example.com / change-me-in-production

---

## Scenarios Tested

1. **Login and dashboard verification** (M-3 retest)
2. **Arena overview and credential detection** (M-1 retest)
3. **Query design creation with search terms and groups**
4. **Arena configuration on query design**
5. **Batch collection launch and monitoring** (B-1 retest)
6. **Content browsing and search term matching** (M-5 retest)
7. **Actor directory and snowball sampling UI**
8. **Analysis dashboard with by_arena breakdown** (M-4 retest)
9. **Data export (CSV, XLSX, GEXF)**
10. **Explore (ad-hoc query) page**

---

## Verification of Previous Fixes

### VERIFIED-FIXED: M-3 -- User display name shows "None"

**URL**: http://localhost:8000/dashboard

The dashboard now shows "Welcome, admin@example.com" and the sidebar profile area displays the email address with avatar initial "A". When no display name is set, the email is used as a sensible fallback. No "None" text visible anywhere.

### VERIFIED-FIXED: M-2 -- Collection launcher shows empty dropdown

**URL**: http://localhost:8000/collections/new

The query design dropdown now populates correctly. All four query designs are listed with their names: "GDPR Test Design", "Gronland Sovereignty Discourse", "Gronland Test Retest Feb 2026", plus one additional design. Each option includes the `data-tier` attribute for tier precedence display.

### VERIFIED-FIXED: M-4 -- Analysis by_arena returns empty

**URL**: http://localhost:8000/analysis/1cd78707-5952-4421-a48e-c34311d48fa0/summary

The summary endpoint now returns a populated `by_arena` array: `[{"arena": "news_media", "record_count": 135, "tasks_records_collected": 0}]`. The volume endpoint also correctly breaks down data by arena. The analysis dashboard loads with all tabs (volume, actors, terms, network, export, enrichments).

### VERIFIED-FIXED (code present): B-1 -- Batch collection dispatch missing

The `dispatch_batch_collection` Celery task exists at `src/issue_observatory/workers/tasks.py:1026` and is registered with the Celery worker (confirmed in worker log). The collection route at line 512-517 calls `dispatch_batch_collection.delay(str(run.id))` when mode is "batch". **However**, the task fails at runtime due to two new bugs (see Blockers B-NEW-1 and B-NEW-2 below). The fix is structurally correct but does not produce working collections.

### PARTIALLY FIXED: M-1 -- .env credentials not detected

**URL**: http://localhost:8000/api/arenas/

The fix code is present at `src/issue_observatory/api/routes/arenas.py:132-155`. It defines an `_ENV_CREDENTIAL_MAP` dictionary mapping platform names to environment variable names and checks `os.environ.get()` for each. However, **all arenas report `has_credentials: false`** despite the `.env` file containing valid credentials for Google Search, Bluesky, Reddit, YouTube, and TikTok.

**Root cause**: The M-1 fix uses `os.environ.get(key)` but Pydantic Settings v2 (used by this application) does NOT inject `.env` file values into `os.environ`. It reads them into the Settings model only. The running uvicorn process does not have the .env values exported to its OS environment, so `os.environ.get("SERPER_API_KEY")` returns None.

**Impact**: Every arena shows a gray "No credentials configured" dot on the arenas overview page and in the query design editor grid. A researcher would believe no credentials are configured and might not attempt MEDIUM-tier collections that would actually work.

### CANNOT VERIFY: M-5 -- Search terms match stopwords

The fix cannot be verified because no new collections can run (see B-NEW-1 and B-NEW-2). Existing data from previous collections still contains stopword matches ("den", "og", "i", "er", "et") in the `search_terms_matched` field. The code change for word-boundary matching exists, but its effectiveness on live data is untested.

---

## Blockers

### B-NEW-1: arenas_config format mismatch prevents all collection dispatch [core]

**Severity**: BLOCKER -- No collections can execute.

**What the researcher sees**: They configure arenas on a query design, launch a batch collection, and the run appears as "Pending". After a few minutes it silently transitions to "Failed" with the error "Marked as failed by stale_run_cleanup: exceeded 24h without completion". Zero records are collected.

**Technical detail** (from Celery worker log):
```
dispatch_batch_collection: arena not registered; skipping arena=arenas
dispatch_batch_collection: no arenas dispatched; completing run
```

The arena config is saved in the database as:
```json
{"arenas": [{"id": "rss_feeds", "tier": "free", "enabled": true}, ...]}
```

But `dispatch_batch_collection` at line 1128 iterates with:
```python
for platform_name, arena_tier in arenas_config.items():
```

This yields `("arenas", [list...])` as the single entry. The task tries to look up an arena named "arenas", fails, and skips it. No arenas are dispatched.

The save endpoint (`POST /query-designs/{id}/arena-config`) stores the list-of-objects format via `_raw_config_to_response`, but the dispatch task expects a flat dict like `{"bluesky": "free", "youtube": "free"}`.

**Research impact**: Complete workflow stoppage. A researcher cannot collect any data through the web interface.

### B-NEW-2: asyncio.run() inside Celery prefork workers causes event loop errors [core]

**Severity**: BLOCKER -- Even when the format mismatch is fixed, run status cannot be updated.

**What the researcher sees**: Collection runs remain stuck in "Pending" status indefinitely because the Celery task cannot write status updates back to the database.

**Technical detail** (from Celery worker log):
```
RuntimeError: Event loop is closed
dispatch_batch_collection: failed to update run status
    error="Task ... got Future ... attached to a different loop"
```

The `dispatch_batch_collection` task uses `asyncio.run()` to call async helper functions (`fetch_batch_run_details`, `set_run_status`, etc.). In Celery's prefork worker pool, `asyncio.run()` creates and destroys event loops. After the first `asyncio.run()` call, subsequent calls fail because asyncpg connections from the first loop are cached in the SQLAlchemy connection pool and cannot be reused in a new event loop.

**Research impact**: Compounds B-NEW-1. Even if arenas were dispatched, status tracking would be broken, leaving runs in limbo.

### B-NEW-3: HTMX forms submit form-encoded data to JSON-only endpoints [frontend]

**Severity**: BLOCKER -- Core UI forms do not work in the browser.

**What the researcher sees**: They fill out the "New Query Design" form and click "Create Query Design" -- nothing happens (or an error appears). They fill out the collection launcher form and click "Launch Collection" -- nothing happens.

**Affected forms**:
- `POST /query-designs/` -- Query design creation (expects `QueryDesignCreate` JSON body)
- `PUT /query-designs/{id}` -- Query design update (expects `QueryDesignUpdate` JSON body)
- `POST /collections/` -- Collection launch (expects `CollectionRunCreate` JSON body)
- `POST /query-designs/{id}/arena-config` -- Arena config save (expects `ArenaConfigPayload` JSON body)

All these forms use HTMX `hx-post` or `hx-put` attributes which send `application/x-www-form-urlencoded` data by default. The FastAPI endpoints accept Pydantic model parameters (not `Form()` parameters), so they require `application/json`. The server returns HTTP 422:

```json
{"detail": [{"type": "model_attributes_type", "loc": ["body"],
  "msg": "Input should be a valid dictionary or object to extract fields from"}]}
```

**Forms that DO work**: Search term addition (`POST /{id}/terms`) uses `Form()` parameters and returns `HTMLResponse`. Actor quick-add also uses `Form()`.

**Research impact**: A researcher cannot create query designs, edit them, configure arenas, or launch collections through the web interface. They would need to use curl or a REST client, which is not a reasonable expectation.

---

## Friction Points

### F-1: Query design detail page shows "No search terms defined" despite terms existing [frontend]

**URL**: http://localhost:8000/query-designs/01d9d67e-f457-4be8-baf8-dccaf7a9183e

The detail template at `templates/query_designs/detail.html:265` checks `{% if terms %}` but the route at `routes/pages.py:358-365` passes terms nested inside `design.search_terms`, not as a top-level `terms` variable. The JSON API response for the same design correctly returns 4 search terms.

**Research impact**: A researcher viewing their query design sees "0 terms" and "No search terms defined" even after adding terms. They would be confused about whether their terms were saved. They might add duplicate terms or give up.

### F-2: stale_run_cleanup marks fresh runs as "exceeded 24h" [core]

Newly created collection runs (minutes old) are being marked as failed with "exceeded 24h without completion". This suggests either the stale_run_cleanup task has a time comparison bug, or it is applying a much shorter threshold than advertised.

**Research impact**: Even if B-NEW-1 and B-NEW-2 were fixed, short-running collections might be prematurely killed by the cleanup task.

### F-3: Content browser export shows platform as "unknown" in Python CSV parsing [data]

When the CSV export is parsed programmatically, the Platform column sometimes appears empty or as "unknown" depending on the CSV parser handling. The raw CSV file contains correct "dr" and "ritzau_via" values. This may be an encoding issue with non-ASCII content causing column misalignment.

**Research impact**: Researchers doing automated analysis of exported CSV may get incorrect platform attribution.

### F-4: No navigation path from analysis landing to analysis of existing runs [frontend]

**URL**: http://localhost:8000/analysis/

The analysis landing page shows "Select a collection run to analyse" with a link to "View Collections". But the collections list page shows all runs as "Failed" with no obvious "Analyse" button on failed runs. The URL pattern `/analysis/{run_id}` is not discoverable. A researcher would need to manually construct the URL.

Even for the run with 146 records (which has data despite being marked "failed"), there is no UI path to reach the analysis dashboard. The collection detail page links to analysis, but only for non-failed runs.

**Research impact**: A researcher with collected data cannot find the analysis tools without developer guidance.

### F-5: Arena config grid uses arena_name as identifier, causing collisions [frontend]

The arena config grid Alpine.js component at line 1910 uses `a.arena_name` as the entry `id`. Multiple platforms share the same `arena_name` (e.g., reddit and youtube both have `arena_name: "social_media"`). This means they would map to a single entry in the config grid, preventing independent configuration.

The saved config uses these arena_name values as keys, so enabling "social_media" at tier "free" would apply to both reddit and youtube indistinguishably. The dispatch task then cannot find an arena named "social_media" in the registry (only "reddit" and "youtube" exist).

**Research impact**: The researcher cannot independently configure platforms that share an arena group, and the saved configuration does not map to actual platform names.

### F-6: Collection launcher does not show which arenas will run [frontend]

**URL**: http://localhost:8000/collections/new

The launcher form has no arena selection or summary. It relies entirely on arenas being pre-configured in the query design. But there is no indication on the launcher page of which arenas are enabled, nor a link to edit the query design's arena config from the launcher.

A researcher selecting a query design and clicking "Launch" has no visibility into what will actually be collected. If no arenas are configured, the collection silently collects nothing.

**Research impact**: Black-box collection launch with no preview of scope.

---

## Passed

### P-1: Authentication flow works correctly
Login via `POST /auth/cookie/login` returns 204 with a session cookie. Subsequent requests are authenticated. Logout link is present.

### P-2: Dashboard displays correctly
All three summary cards (Credits, Active Collections, Records Collected) render properly. Quick Actions links work. "About this platform" section is present with accurate description. No "Phase 0" text visible (IP2-010 confirmed).

### P-3: Arena overview page loads with comprehensive arena list
**URL**: http://localhost:8000/arenas

All 25 arena implementations are listed, organized by tier (Free, Medium, Premium). Each arena shows its description, supported tiers, and credential status indicator. The tier badges use appropriate colors (green for free, blue for medium, purple for premium).

### P-4: Search term addition via HTMX works correctly
`POST /query-designs/{id}/terms` uses `Form()` parameters and returns HTML fragments. Adding terms "gronland", "greenland", "selvstyre", and "rigsfaellesskab" with group labels "Primary" and "Governance" all succeeded with HTTP 201. Term groups are assigned UUID `group_id` values automatically.

### P-5: Content browser renders records with metadata
**URL**: http://localhost:8000/content/

135 records display in a paginated table with columns: Platform, Content preview, Author, Published date, Arena, Engagement score. Click-to-expand detail panel is implemented. Quick-add actor button appears on author names.

### P-6: Content record detail shows full metadata
Individual record pages display full text content, platform metadata, raw JSON data, and the annotation panel. Danish text content (including special characters ae, oe, aa) renders correctly.

### P-7: CSV and XLSX export produce valid files
- CSV export returns proper `text/csv` with human-readable headers (IP2-006)
- XLSX export returns valid `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` (57KB)
- GEXF export returns valid XML with GEXF 1.3 schema, node attributes (type, frequency, degree), and edge weights

### P-8: Analysis API endpoints return correct data
- `/analysis/{run_id}/summary` -- returns record count, date range, by_arena breakdown
- `/analysis/{run_id}/volume` -- returns daily volume with arena breakdown
- `/analysis/{run_id}/actors` -- returns top actors with pseudonymized IDs
- `/analysis/{run_id}/terms` -- returns top matched terms with counts
- `/analysis/{run_id}/network/terms` -- returns 5 nodes and 10 edges

### P-9: Actor directory with public figure badge
**URL**: http://localhost:8000/actors

One actor (Mette Frederiksen) displays with correct "Person" type badge and amber "PF" (Public Figure) indicator with GDPR Art. 89(1) tooltip. Snowball sampling panel is accessible via button.

### P-10: System health monitoring
`GET /api/health` returns all-green status for PostgreSQL, Redis, and Celery. Arena health endpoint shows differentiated statuses (ok/degraded/down/not_implemented) for all 25 arenas.

### P-11: Explore page for ad-hoc queries
**URL**: http://localhost:8000/explore

The ad-hoc exploration page loads with a search input, arena selector (filtered to free-tier arenas), and result display area. This is the YF-05 feature.

### P-12: Discovered links API returns mined URLs
`GET /content/discovered-links` returns 2 discovered links with platform classification ("web"), source counts, and example source URLs. Link mining (GR-22) is functional.

---

## Data Quality Findings

### DQ-1: Stopword contamination in search_terms_matched field

All 135 existing records have `search_terms_matched` containing Danish stopwords: "i" (in, 95 records), "er" (is, 92), "et" (a, 66), "og" (and, 34), "den" (the, 28). The query design's actual search terms ("klima", "energi") also appear but are drowned out by stopword noise.

**Impact on research**: Term frequency analysis is meaningless. The top-5 terms chart shows only stopwords. A researcher analyzing which search terms were most prevalent would get nonsensical results. This data cannot be cited in a publication without manual cleaning.

**Note**: This is existing data from the previous test round. The M-5 fix for word-boundary matching may resolve this for future collections, but it cannot be verified until collections work (B-NEW-1, B-NEW-2).

### DQ-2: All records from single platform (Ritzau Via)

The 135 existing records are exclusively from Ritzau Via (news_media arena). Despite the collection being a batch run intended for multiple arenas, no data was collected from RSS feeds, GDELT, Bluesky, YouTube, or any other platform. This is consistent with the dispatch orchestration failures (B-NEW-1, B-NEW-2) observed in this retest.

**Impact on research**: Cross-platform analysis is impossible with single-platform data. The system appears to collect from one arena only, which defeats the multi-platform purpose of the tool.

### DQ-3: Content relevance questionable for topic-based collection

Several records in the Ritzau Via dataset appear to be general press releases with no connection to the query design topics ("klima", "energi"). For example, the Andersen Consulting / Grinity press release is about management consulting, not climate or energy. The stopword matching (DQ-1) explains this: any Danish text will match "i", "og", "er", etc.

**Impact on research**: The collected data has very low precision for the intended research topic, making it unsuitable for discourse analysis without extensive manual filtering.

---

## Recommendations

Ordered by priority (blockers first, then impact on researcher workflow):

1. **[core] Fix arenas_config format mismatch (B-NEW-1)**: The `dispatch_batch_collection` task must parse the `{"arenas": [{id, tier, enabled}]}` format that the save endpoint produces, OR the save endpoint must store in the flat dict format that the dispatch task expects. The dispatch task should convert the list format to `{platform_name: tier}` for enabled arenas.

2. **[core] Fix asyncio.run() in Celery workers (B-NEW-2)**: Replace `asyncio.run()` calls in Celery tasks with a single event loop per worker process (e.g., using `asgiref.sync.async_to_sync`, or creating one loop at task startup and reusing it). The current approach of creating/destroying event loops per `asyncio.run()` call is incompatible with asyncpg connection pooling.

3. **[frontend] Fix HTMX form encoding to match backend expectations (B-NEW-3)**: Either add the HTMX `json-enc` extension and `hx-ext="json-enc"` to forms that target JSON endpoints, OR change the backend endpoints to accept both `Form()` and JSON body parameters, OR convert forms to use Alpine.js `fetch()` with `Content-Type: application/json` instead of HTMX form submission.

4. **[core] Fix M-1 env var detection (M-1 regression)**: Replace `os.environ.get(key)` in the arena list endpoint with a check against the Pydantic Settings model (e.g., `get_settings().serper_api_key`) or call `load_dotenv()` at application startup to inject .env values into `os.environ`.

5. **[frontend] Fix detail page search term rendering (F-1)**: Add `terms=design_context["search_terms"]` to the template context in `routes/pages.py:358-365`, or update the template to use `design.search_terms` instead of `terms`.

6. **[frontend] Fix arena_name vs platform_name in config grid (F-5)**: Use `a.platform_name` instead of `a.arena_name` as the entry identifier in the arena config grid. This ensures each platform is independently configurable and the saved config keys match the arena registry.

7. **[core] Review stale_run_cleanup threshold (F-2)**: Verify that the 24-hour threshold is applied correctly. Fresh runs should not be marked as stale within minutes. Check whether the `created_at` timestamp is being compared correctly against the current time.

8. **[frontend] Add arena preview to collection launcher (F-6)**: Show the list of enabled arenas for the selected query design on the launcher page, with a link to edit the arena config if none are enabled.

9. **[frontend] Add analysis link from failed runs with data (F-4)**: If a collection run has `records_collected > 0` despite being in "failed" status, show an "Analyse collected data" link on both the collection list and detail pages.

10. **[data] Add stopword exclusion list for Danish (DQ-1)**: Consider adding a configurable stopword list (at minimum: i, er, et, og, den, det, en, til, af, at, for, med, som, pa, har, var, kan, vil, ikke, blev, fra) to prevent these from being recorded in `search_terms_matched`. This affects both data quality and analysis results.

---

## Testing Limitations

The following scenarios could NOT be tested due to the collection blockers:

- **Live data collection from any arena**: All batch collections fail silently.
- **Cross-platform comparison**: Only single-platform (Ritzau Via) data exists.
- **Live tracking lifecycle**: Cannot promote to live tracking without a working batch first.
- **MEDIUM tier collection**: Cannot test Google Search collection.
- **SSE live monitoring**: No running collection to monitor.
- **Enrichment pipeline**: No new data to enrich (language detection, sentiment, NER).
- **M-5 word-boundary fix verification**: Cannot collect new data to test whether stopwords are excluded.
- **Actor discovery from collected content**: Insufficient multi-platform data.
- **Network analysis with meaningful data**: Only stopword co-occurrence available.

---

## Summary

Of the six previously reported issues:
- **3 are verified fixed**: M-2 (dropdown population), M-3 (display name), M-4 (by_arena analysis)
- **1 is partially fixed**: M-1 (credential detection code exists but uses wrong API to check env vars)
- **1 is fixed in code but untestable**: B-1 (dispatch task exists but encounters new runtime errors)
- **1 cannot be verified**: M-5 (word-boundary matching -- no new collections possible)

**Three new blockers** were discovered that collectively prevent any collection from executing:
1. arenas_config format mismatch between save and dispatch
2. asyncio event loop conflicts in Celery workers
3. HTMX form encoding incompatible with JSON API endpoints

The application's infrastructure (PostgreSQL, Redis, Celery) is healthy. The frontend renders correctly. Individual API endpoints return valid data. The analysis module works with existing data. Export formats (CSV, XLSX, GEXF) produce valid files.

However, the core workflow -- creating a query design, configuring arenas, launching a collection, and browsing results -- cannot be completed end-to-end through the web interface. A researcher would be unable to collect any new data without developer intervention.
