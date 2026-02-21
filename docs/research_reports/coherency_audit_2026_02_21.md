# Coherency Audit Report -- Issue Observatory

**Created:** 2026-02-21
**Author:** Research Agent (The Strategist)
**Scope:** Full codebase coherency audit across all layers (routes, templates, analysis modules, core services, workers, arenas)

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-21 | Initial comprehensive audit |

---

## Executive Summary

This audit systematically traces every implemented capability through all layers of the application stack -- from backend analysis functions through API routes to frontend templates -- to identify disconnections, missing integrations, dead code, and documentation mismatches. The codebase is generally well-integrated for its scope. However, the audit identifies **6 critical**, **11 moderate**, and **9 minor** findings across five categories.

The most significant systemic issue is that several analysis modules (`coordination.py`, `propagation.py`) define public query functions that are never called from any route or task, meaning they are fully implemented backend capabilities with no way for users to invoke them. The second systemic issue is that several UI features (scraping jobs, data import, enrichment triggering, password reset page routing) lack proper frontend navigation paths, rendering them effectively invisible to researchers.

---

## Category 1: Disconnected Features

These are implemented capabilities that exist in the code but are not accessible through the expected API or UI pathways.

### 1.1 `coordination.py` -- `get_coordination_events()` is Never Called

**Severity: MODERATE**

The `analysis/coordination.py` module defines `get_coordination_events()`, which queries `raw_metadata.enrichments.coordination` for flagged clusters of coordinated posting. This function is never imported or called from any route, template, or worker task.

The analysis routes in `routes/analysis.py` do expose `GET /{run_id}/enrichments/coordination`, but that endpoint calls `get_coordination_signals()` from `descriptive.py`, not `get_coordination_events()` from `coordination.py`. The two functions query the same underlying data but with different aggregation logic:

- `get_coordination_signals()` in `descriptive.py` aggregates by coordination type (burst, hash-match).
- `get_coordination_events()` in `coordination.py` returns individual cluster-level records with DISTINCT ON semantics.

**Impact:** The more detailed per-cluster coordination analysis is inaccessible. Researchers can see aggregate coordination signals but cannot drill down into individual clusters.

**Recommended fix:** Either (a) add a new route `GET /analysis/{run_id}/coordination/events` that calls `get_coordination_events()`, or (b) integrate its output into the existing enrichment coordination endpoint alongside the aggregate view, or (c) document it as an internal-only function if the aggregate view is sufficient.

### 1.2 `propagation.py` -- `get_propagation_flows()` is Never Called from Routes

**Severity: MODERATE**

The `analysis/propagation.py` module defines `get_propagation_flows()`, which returns the top cross-arena propagation flows with full origin-to-destination sequences. This function is re-exported in `analysis/__init__.py` but is never called from any API route.

The analysis routes expose `GET /{run_id}/enrichments/propagation`, but that endpoint calls `get_propagation_patterns()` from `descriptive.py`, not `get_propagation_flows()` from `propagation.py`. Similar to the coordination case, these provide different aggregation levels:

- `get_propagation_patterns()` returns story-level summaries.
- `get_propagation_flows()` returns individual record-level flows with full propagation sequences.

**Impact:** The detailed propagation flow data (which records propagated where, in what order) is inaccessible through the API. The enrichment endpoint returns a useful summary but not the full flow detail.

**Recommended fix:** Add a route for detailed propagation flows, or incorporate flow details into the existing enrichment propagation endpoint response.

### 1.3 `export_temporal_gexf()` Has No Route

**Severity: MINOR**

`ContentExporter.export_temporal_gexf()` in `analysis/export.py` produces dynamic GEXF files with temporal attributes (IP2-045). No API endpoint calls this function. The analysis template offers GEXF export via `/content/export?format=gexf`, which calls the standard `export_gexf()`, not the temporal variant.

**Impact:** Researchers cannot export temporal GEXF files for use in Gephi's timeline feature. The function works but is unreachable.

**Recommended fix:** Add a `temporal_gexf` format option to the analysis filtered-export endpoint, or create a dedicated endpoint `GET /analysis/{run_id}/network/temporal/export-gexf`.

### 1.4 Enrichment Pipeline Has No User-Facing Trigger

**Severity: CRITICAL**

The `enrich_collection_run` Celery task exists in `workers/tasks.py` and fully implements the enrichment pipeline (language detection, NER, sentiment, propagation, coordination). However:

1. It is **not** in the Celery Beat schedule (`beat_schedule.py`), so it never runs automatically.
2. There is **no** API endpoint that dispatches it manually.
3. There is **no** UI button to trigger enrichment on a completed collection run.
4. The `daily_collection` task in `workers/tasks.py` does not chain enrichment after collection completes.

The enrichment results dashboard tab in `analysis/index.html` (SB-15) calls `GET /analysis/{run_id}/enrichments/languages|entities|propagation|coordination`, but these will always return empty results because enrichment is never triggered.

**Impact:** The entire enrichment pipeline (6 enrichers) and the enrichment results dashboard are effectively dead features. Language detection, NER, sentiment analysis, propagation detection, and coordination detection never execute.

**Recommended fix:** Either (a) add enrichment to the Beat schedule as a post-collection step, (b) chain `enrich_collection_run.delay(run_id)` at the end of collection run completion in the orchestration task, or (c) add a `POST /collections/{run_id}/enrich` endpoint with a corresponding UI button on the collection detail page.

### 1.5 Sentiment Analysis Has No Surfacing Endpoint

**Severity: MODERATE**

The `SentimentAnalyzer` enricher writes sentiment data to `raw_metadata.enrichments.sentiment_analyzer`, but:

1. `descriptive.py` has no `get_sentiment_distribution()` or similar function.
2. The analysis routes have no `GET /{run_id}/enrichments/sentiment` endpoint.
3. The enrichment results dashboard in the analysis template does not include a sentiment panel.

Language, NER, propagation, and coordination each have dedicated enrichment endpoints and dashboard panels (SB-15), but sentiment does not.

**Impact:** Even if the enrichment pipeline were triggered (see finding 1.4), sentiment analysis results would be written to the database but never surfaced to the researcher.

**Recommended fix:** Add `get_sentiment_distribution()` to `descriptive.py`, a route at `GET /analysis/{run_id}/enrichments/sentiment`, and a fifth panel in the enrichment results section of `analysis/index.html`.

### 1.6 Scraping Jobs Have No Frontend Navigation or UI

**Severity: MODERATE**

The scraper module (`scraper/router.py`) is fully implemented and mounted at `/scraping-jobs/` in `main.py`. It provides CRUD for scraping jobs with SSE progress streaming. However:

1. The navigation sidebar (`_partials/nav.html`) has no link to a scraping jobs page.
2. No HTML template exists for listing or creating scraping jobs.
3. The `pages.py` route module has no page route for scraping jobs.

The API endpoints work, but there is no way for a researcher to reach them through the browser UI.

**Impact:** Web scraping enrichment is API-only. Researchers cannot use the browser to create, monitor, or manage scraping jobs.

**Recommended fix:** Create a scraping jobs template, add a page route in `pages.py`, and add a navigation link (possibly under a "Tools" section in the sidebar).

### 1.7 Data Import Has No Frontend Navigation or UI

**Severity: MODERATE**

The imports module (`routes/imports.py`) provides both manual CSV/NDJSON upload (`POST /content/import`) and Zeeschuimer 4CAT-compatible endpoints (`POST /import-dataset/`, `GET /check-query/`). However:

1. No HTML template exists for file upload.
2. The navigation sidebar has no link to an import page.
3. The `pages.py` route module has no page route for imports.
4. No template references the `/content/import` endpoint.

**Impact:** Manual data import is API-only. Researchers cannot upload CSV or NDJSON files through the browser UI. The Zeeschuimer integration is designed for browser extension use (which is correct), but manual CSV import should be accessible in the UI.

**Recommended fix:** Create an import page template with a file upload form, add it to `pages.py`, and add a navigation entry (possibly under "Content" or "Tools").

---

## Category 2: Missing Integration Points

### 2.1 Collection Completion Does Not Chain Enrichment or Deduplication

**Severity: CRITICAL**

When a collection run completes, the system does not automatically:
- Run the enrichment pipeline (`enrich_collection_run`)
- Run near-duplicate detection (`deduplicate_run`)
- Run SimHash computation

The `trigger_daily_collection` task dispatches per-arena collection tasks but has no callback or chain that triggers post-processing when all arena tasks finish. The deduplication endpoint exists (`POST /content/deduplicate`) but requires manual invocation.

**Impact:** Every collection run requires manual API calls to trigger enrichment and deduplication, which defeats the purpose of automated collection.

**Recommended fix:** Add a completion callback to the collection orchestration that chains `deduplicate_run` and `enrich_collection_run` once all arena tasks for a run finish.

### 2.2 Enrichment Results Not Shown in Content Browser Detail Panel

**Severity: MODERATE**

The content browser detail template (`content/record_detail.html`) displays `raw_metadata` as raw JSON. It does not extract or render enrichment results from `raw_metadata.enrichments.*` in a structured format. A record that has been enriched with language detection, NER, and sentiment will show these only as nested JSON.

**Impact:** Individual record enrichment results are not human-readable in the content browser. Researchers must mentally parse JSONB to see enrichment outputs for a specific record.

**Recommended fix:** Add a structured "Enrichments" section to `record_detail.html` that extracts and formats `raw_metadata.enrichments` sub-keys when present, similar to how the analysis dashboard renders aggregate enrichment data.

### 2.3 Retention Service Not Exposed in Admin UI

**Severity: MINOR**

`core/retention_service.py` implements GDPR-compliant data retention (delete records older than `DATA_RETENTION_DAYS`). It is called from the `enforce_retention_policy` Beat task. However:

1. There is no admin UI page to view or configure the retention policy.
2. The `data_retention_days` setting (default: 730) in `config/settings.py` can only be changed via environment variables, not through the admin interface.
3. There is no admin endpoint to view what the current retention window is or how many records would be affected.

**Impact:** Administrators cannot inspect or adjust retention policy without server access.

**Recommended fix:** Add a retention section to the admin health page showing the current retention window, last enforcement run, and records affected.

### 2.4 Volume Spike Alerts Not Shown in Collection Detail or Dashboard

**Severity: MODERATE**

`analysis/alerting.py` implements GR-09 volume spike detection, and `_alerting_helpers.py` provides `send_volume_spike_alert()` for email notification. Volume spikes are stored in `collection_runs.arenas_config["_volume_spikes"]`. However:

1. The spike detection runs as part of `trigger_daily_collection` (confirmed via `workers/_alerting_helpers.py`).
2. The stored spikes are never read back or displayed in any template.
3. The collection detail page does not show spike alerts.
4. The dashboard does not show a spike alert banner.
5. The `fetch_recent_volume_spikes()` function exists but is not called from any route.

The `query_designs.py` route does import from `alerting.py` (line 1798), suggesting partial integration in the query design context, but the general dashboard and collection views do not surface spikes.

**Impact:** Volume spikes are detected and stored but not visible to researchers in most contexts. They must check email (if SMTP is configured) or inspect `arenas_config` JSONB directly.

**Recommended fix:** Add spike display to the collection detail page, the dashboard, and/or the analysis dashboard.

---

## Category 3: Dead Code or Orphaned Modules

### 3.1 `analysis/coordination.py` -- Potentially Orphaned

**Severity: MINOR**

`get_coordination_events()` is defined but never imported by any other module except within `coordination.py` itself. It is not re-exported in `analysis/__init__.py` (unlike `get_propagation_flows()`). See finding 1.1 for details.

### 3.2 `DescriptiveStats` Dataclass Never Used

**Severity: MINOR**

`analysis/descriptive.py` defines a `DescriptiveStats` dataclass (lines 48-59) with fields for `volume_over_time`, `top_actors`, `top_terms`, and `engagement_distribution`. This class is never instantiated anywhere in the codebase. All functions in `descriptive.py` return plain dicts/lists directly to the route layer rather than populating this container.

**Impact:** No functional impact -- it is dead code that adds mild confusion.

**Recommended fix:** Remove the `DescriptiveStats` class or refactor the functions to use it.

### 3.3 `DanishLanguageDetector` -- Deprecated Alias Still Exported

**Severity: MINOR**

`analysis/enrichments/__init__.py` exports `DanishLanguageDetector` as a "deprecated alias" for `LanguageDetector`. A search shows no usage of `DanishLanguageDetector` anywhere outside the `__init__.py` itself and the enrichments module. If no external consumer uses this alias, it should be removed.

**Impact:** Minimal -- it adds a name to the public API that should not be used.

**Recommended fix:** Remove the alias after confirming no test or external code uses it. Add a deprecation warning if backward compatibility is required.

---

## Category 4: Inconsistent Feature Coverage

### 4.1 Password Reset Template Exists but No Page Route Serves It

**Severity: CRITICAL**

The template `auth/reset_password.html` exists and correctly targets `POST /auth/forgot-password` and `POST /auth/reset-password` (FastAPI-Users routes). However, `pages.py` has no `GET /auth/reset-password` page route to serve this template. The template can never be rendered.

The `auth_router` in `routes/auth.py` includes `fastapi_users.get_reset_password_router()`, which provides the JSON API endpoints. But the HTML template that provides the user-facing form has no route to deliver it.

**Impact:** Password reset is completely non-functional from the browser UI. Users cannot request or complete a password reset.

**Recommended fix:** Add `GET /auth/reset-password` and `GET /auth/forgot-password` page routes in `pages.py` that render `auth/reset_password.html`. Alternatively, add these as routes in a dedicated auth pages section.

### 4.2 Registration Has No UI Page

**Severity: CRITICAL**

The `auth_router` includes `fastapi_users.get_register_router()` which provides `POST /auth/register`. However:

1. No template exists for a registration page.
2. No page route serves a registration form.
3. The login template does not link to a registration page.

The `bootstrap_admin.py` script handles initial admin creation, but there is no way for new researchers to self-register through the browser.

**Impact:** New user registration is entirely API-only. Researchers cannot create accounts through the UI.

**Recommended fix:** Create a `register.html` template, add a page route, and link to it from the login page. Alternatively, document that registration is admin-only and is done via the admin user management page.

### 4.3 Logout Link Points to Non-Existent Endpoint

**Severity: CRITICAL**

The navigation sidebar (`_partials/nav.html` line 86) contains `<a href="/auth/logout">Sign out</a>`. However, there is no `GET /auth/logout` route. FastAPI-Users provides `POST /auth/cookie/logout` (not GET, not at `/auth/logout`).

**Impact:** The sign-out button in the navigation does not work. Clicking it likely produces a 404 error.

**Recommended fix:** Change the logout link to submit a POST request to `/auth/cookie/logout` (e.g., using a form with a submit button, or an HTMX `hx-post`). GET-based logout is a CSRF vulnerability and should be avoided.

### 4.4 Design-Level Analysis Missing Several Endpoints Present on Run-Level

**Severity: MINOR**

The analysis routes provide design-level aggregation for volume, actors, terms, and network graphs (`GET /analysis/design/{design_id}/...`). However, several run-level endpoints have no design-level equivalents:

| Run-Level Endpoint | Design-Level Equivalent |
|---|---|
| `/{run_id}/engagement` | Missing |
| `/{run_id}/temporal-comparison` | Missing |
| `/{run_id}/arena-comparison` | Missing |
| `/{run_id}/actors-unified` | Missing |
| `/{run_id}/emergent-terms` | Missing |
| `/{run_id}/suggested-terms` | Missing |
| `/{run_id}/enrichments/*` | Missing |
| `/{run_id}/network/enhanced-bipartite` | Missing |
| `/{run_id}/network/temporal` | Missing |
| `/{run_id}/filtered-export` | Missing |

**Impact:** When researchers use the design-level analysis dashboard (`/analysis/design/{design_id}`), they have access to only volume, actors, terms, and three network types. The richer analysis features (engagement distributions, arena comparison, temporal comparison, emergent terms, enrichment results) are only available at the run level.

**Recommended fix:** Prioritize adding design-level equivalents for the most-used endpoints (engagement, arena-comparison, emergent-terms, filtered-export). The `design.html` template should only show tabs/panels for which backend endpoints exist.

### 4.5 Promote to Live Tracking (SB-08) -- Frontend Button, No Backend Route

**Severity: MODERATE**

The query design detail template (`query_designs/detail.html` line 70-82) shows a "Start Live Tracking" button when a completed batch run exists (SB-08). However, there is no dedicated API endpoint for promoting a batch query design to live tracking. The button appears to open a dialog (`@click="openDialog()"`), and the dialog likely creates a new collection run with `mode=live`. The `POST /collections/` endpoint supports `mode=live`, so the frontend could work if the dialog correctly calls this endpoint.

However, the `collections.py` routes have no `promote_to_live` or equivalent action. The SB-08 feature relies entirely on the frontend creating a new live collection run via the existing `POST /collections/` endpoint, which is functional but semantically awkward (it is a "create" rather than a "promote" action).

**Impact:** Functional (the button likely works), but there is no explicit backend operation. If the dialog implementation is incomplete, the button does nothing.

**Recommended fix:** Verify the dialog JavaScript implementation actually submits a `POST /collections/` request with `mode=live`. If so, document this as the intended flow. If the dialog is incomplete, implement it.

---

## Category 5: Configuration Gaps

### 5.1 MinIO Configuration Required for Async Export but Not Documented

**Severity: MODERATE**

The async export flow (`POST /content/export/async`) and its download endpoint (`GET /content/export/{job_id}/download`) require a running MinIO instance. The settings in `config/settings.py` define `minio_endpoint`, `minio_root_user`, `minio_root_password`, `minio_bucket`, and `minio_secure` with localhost defaults. However:

1. The `docker-compose.yml` may not include a MinIO service (not verified in this audit).
2. The `.env.example` file may not document MinIO variables.
3. There is no startup validation that MinIO is reachable when async export is used.

**Impact:** Async export will fail at runtime with an unhelpful error if MinIO is not configured.

**Recommended fix:** Add MinIO to `docker-compose.yml` if not present, document the environment variables in `.env.example`, and add a health check for MinIO in the admin health page.

### 5.2 SMTP Configuration for Email Notifications is Silent No-Op

**Severity: MINOR**

The `EmailService` operates as a no-op when SMTP is not configured ("Complete -- no-op when SMTP not configured" per CLAUDE.md). This means:

- Collection failure emails (`send_collection_failure`) are silently dropped.
- Volume spike alerts (`send_volume_spike_alert`) are silently dropped.
- Low-credit warnings are silently dropped.

There is no admin UI indication that email is not configured, and no log message at startup warning that email notifications are disabled.

**Impact:** Administrators may expect to receive alerts and never realize they are not being sent.

**Recommended fix:** Log a WARNING at application startup if SMTP is not configured. Add a visual indicator on the admin health page showing email service status.

### 5.3 RSS Feed and GDELT Beat Tasks Run Without Query Design Context

**Severity: MODERATE**

The Beat schedule (`beat_schedule.py`) includes standalone periodic tasks for RSS feeds and GDELT:

```python
"rss_feeds_collect_terms": {
    "task": "issue_observatory.arenas.rss_feeds.tasks.collect_by_terms",
    "schedule": crontab(minute="*/15"),
},
"gdelt_collect_terms": {
    "task": "issue_observatory.arenas.gdelt.tasks.collect_by_terms",
    "schedule": crontab(minute="*/15"),
},
```

These tasks are dispatched by Celery Beat every 15 minutes, but it is unclear what query design, search terms, or collection run they operate under. The `trigger_daily_collection` task properly iterates over active live-tracking query designs and dispatches per-arena tasks with context. These standalone RSS and GDELT tasks may fail at runtime because they receive no `run_id`, `query_design_id`, or search terms.

**Impact:** If these tasks expect arguments they do not receive, they fail silently every 15 minutes. If they operate without context, they may collect data without linking it to any query design.

**Recommended fix:** Verify what happens when `rss_feeds.tasks.collect_by_terms` is called without arguments. If it requires context, remove these Beat entries (the `trigger_daily_collection` task already handles RSS and GDELT as part of live-tracking designs). If these are intended for a "background monitoring" mode, document their behavior.

---

## Category 6: Documentation vs. Reality Mismatches

### 6.1 CLAUDE.md Lists Actors Page Route as `/actors` but Content Router Also Has `/content` Route

**Severity: MINOR**

Minor inconsistency: CLAUDE.md states the content browser page is at `GET /content`. The `pages.py` module has a `/content` page route that renders `content/browser.html`, but the `content.py` route module _also_ has a `GET /` route (which is mounted at `/content/`) that renders the same template with data. Both routes serve the content browser -- one as a simple page, the other as a data-populated page. This duplication means navigating to `/content` renders an empty-state browser, while the data-populated version is only reached through HTMX interactions.

**Impact:** The duplication is harmless but confusing. The `pages.py` version likely exists as a fallback before the full `content.py` router was implemented.

**Recommended fix:** Remove the `/content` route from `pages.py` since the `content.py` router already handles it with full data loading.

### 6.2 CLAUDE.md States "Refresh Engagement" is Done (IP2-035) but No UI Access

**Severity: MODERATE**

CLAUDE.md marks IP2-035 (engagement metric refresh) as "Done" with an API endpoint and Celery task. The `POST /collections/{run_id}/refresh-engagement` endpoint exists in `collections.py`. However, no template has a button or link to trigger this endpoint. The collection detail template does not include a "Refresh Engagement" button.

**Impact:** The feature exists at the API level but is not discoverable by researchers using the browser UI.

**Recommended fix:** Add a "Refresh Engagement Metrics" button to `collections/detail.html` for completed runs, wired via `hx-post` to the existing endpoint.

### 6.3 CLAUDE.md Lists Deduplication as Complete but No UI Trigger

**Severity: MINOR**

The content deduplication endpoints (`POST /content/deduplicate` and `GET /content/duplicates`) exist. No template surfaces a "Run Deduplication" button or displays duplicate groups. See also finding 2.1.

---

## Summary Table

| # | Finding | Category | Severity |
|---|---------|----------|----------|
| 1.1 | `get_coordination_events()` never called | Disconnected | Moderate |
| 1.2 | `get_propagation_flows()` never called from routes | Disconnected | Moderate |
| 1.3 | `export_temporal_gexf()` has no route | Disconnected | Minor |
| 1.4 | Enrichment pipeline has no trigger | Disconnected | **Critical** |
| 1.5 | Sentiment analysis has no surfacing endpoint | Disconnected | Moderate |
| 1.6 | Scraping jobs have no frontend UI | Disconnected | Moderate |
| 1.7 | Data import has no frontend UI | Disconnected | Moderate |
| 2.1 | Collection completion does not chain enrichment/dedup | Missing Integration | **Critical** |
| 2.2 | Enrichment results not shown in content detail | Missing Integration | Moderate |
| 2.3 | Retention service not in admin UI | Missing Integration | Minor |
| 2.4 | Volume spike alerts not displayed | Missing Integration | Moderate |
| 3.1 | `coordination.py` potentially orphaned | Dead Code | Minor |
| 3.2 | `DescriptiveStats` dataclass unused | Dead Code | Minor |
| 3.3 | `DanishLanguageDetector` deprecated alias | Dead Code | Minor |
| 4.1 | Password reset template has no page route | Inconsistent | **Critical** |
| 4.2 | Registration has no UI page | Inconsistent | **Critical** |
| 4.3 | Logout link targets non-existent endpoint | Inconsistent | **Critical** |
| 4.4 | Design-level analysis missing many endpoints | Inconsistent | Minor |
| 4.5 | Promote to live tracking -- verify frontend completion | Inconsistent | Moderate |
| 5.1 | MinIO config required but not documented | Configuration | Moderate |
| 5.2 | SMTP silent no-op without warning | Configuration | Minor |
| 5.3 | RSS/GDELT Beat tasks run without context | Configuration | Moderate |
| 6.1 | Duplicate content browser page routes | Docs Mismatch | Minor |
| 6.2 | Engagement refresh has no UI button | Docs Mismatch | Moderate |
| 6.3 | Deduplication has no UI trigger | Docs Mismatch | Minor |

---

## Prioritized Fix Recommendations

### Immediate (blocks researcher use)

1. **Fix logout link** (4.3) -- Change from `GET /auth/logout` to `POST /auth/cookie/logout` using a form or HTMX.
2. **Fix password reset** (4.1) -- Add page routes to serve `reset_password.html`.
3. **Fix registration** (4.2) -- Create registration template and page route, or document admin-only registration flow.

### High Priority (major feature gaps)

4. **Wire enrichment pipeline trigger** (1.4, 2.1) -- Either chain enrichment after collection completion or add a manual trigger button.
5. **Add sentiment surfacing** (1.5) -- Add descriptive function, route, and dashboard panel.
6. **Surface volume spike alerts** (2.4) -- Display in dashboard and collection detail.

### Medium Priority (usability gaps)

7. **Add scraping jobs UI** (1.6) -- Template, page route, navigation link.
8. **Add data import UI** (1.7) -- File upload template, page route, navigation link.
9. **Add engagement refresh button** (6.2) -- Button on collection detail page.
10. **Verify RSS/GDELT Beat tasks** (5.3) -- Confirm they receive proper context or remove.
11. **Surface propagation and coordination details** (1.1, 1.2) -- Add routes for detailed views.

### Low Priority (polish)

12. **Remove dead code** (3.1, 3.2, 3.3) -- Clean up unused dataclass, aliases, orphaned functions.
13. **Add design-level analysis parity** (4.4) -- Extend design-level endpoints incrementally.
14. **Document MinIO setup** (5.1) -- Add to docker-compose and .env.example.
15. **Add SMTP status indicator** (5.2) -- Startup warning and admin page indicator.
16. **Add temporal GEXF export** (1.3) -- Route for dynamic GEXF.
17. **Remove duplicate content browser route** (6.1) -- Remove from `pages.py`.

---

## Methodology

This audit was conducted by:

1. Reading all API route files in `src/issue_observatory/api/routes/` to catalog every exposed endpoint.
2. Reading all frontend templates in `src/issue_observatory/api/templates/` to catalog every UI element and its backend dependency.
3. Reading the navigation sidebar (`_partials/nav.html`) to verify all major sections are navigable.
4. Reading all analysis modules (`analysis/*.py`) and tracing each public function to its consumers.
5. Cross-referencing enrichment pipeline components (enrichers, helpers, tasks) with their trigger points and result surfacing.
6. Checking worker task definitions against the Beat schedule and manual trigger points.
7. Verifying that core services (credential pool, credit service, retention service, entity resolver, deduplication, email service) are wired into both API routes and worker tasks.
8. Checking the sampling and scraper modules for full stack integration.
9. Comparing CLAUDE.md feature claims against actual code.

Functions were traced using import graph analysis (searching for `from issue_observatory.X import Y` patterns) and call site analysis (searching for function name usage across all source files).
