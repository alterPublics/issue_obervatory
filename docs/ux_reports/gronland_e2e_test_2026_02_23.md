# UX Test Report -- Gronland End-to-End Scenario
Date: 2026-02-23
Arenas tested: bluesky, reddit, youtube, rss_feeds, gdelt, ritzau_via, common_crawl, wayback, gab, google_search
Tiers tested: FREE, MEDIUM
Test method: Live HTTP API calls against running instance at localhost:8000

---

## Executive Summary

**Overall result: FAIL -- Critical blockers prevent a researcher from completing a basic data collection and analysis workflow.**

Of 9 FREE-tier arenas attempted, only 2 completed (ritzau_via, rss_feeds). Of those, Ritzau Via returned 80 records that bear no relationship to the search query ("Gronland"), and RSS feeds returned 0 records. Four arenas (reddit, youtube, common_crawl, wayback) became permanently stuck in "pending" status, causing the collection run to hang indefinitely in "running" state with no path to completion. The MEDIUM-tier Google Search collection failed because credentials configured in `.env` are not loaded into the database-backed credential pool, and no documentation explains this required bootstrapping step.

A researcher following the documented workflow would reach a dead end within 10 minutes of their first collection attempt. They would see a run that never finishes, data that does not match their query, and error messages about missing credentials for platforms advertised as "no credentials needed."

---

## Scenarios Tested

| Scenario | Arenas | Tier | Outcome |
|----------|--------|------|---------|
| Phase 0: Login & setup | -- | -- | PASS |
| Phase 1: Create query design | -- | -- | PASS (with issues) |
| Phase 2: FREE-tier batch collection | bluesky, reddit, youtube, rss_feeds, gdelt, ritzau_via, common_crawl, wayback, gab | FREE | FAIL |
| Phase 3: Inspect results | ritzau_via data only | FREE | FAIL (data irrelevant) |
| Phase 4: MEDIUM-tier collection | google_search | MEDIUM | FAIL |
| Phase 5: Analysis | run with 80 records | FREE | PARTIAL (endpoints work but data is meaningless) |
| Phase 6: Actor discovery / snowball | bluesky, reddit | FREE | PASS (no discoveries, correctly handled) |
| Phase 7: Export | CSV, XLSX, NDJSON, RIS, BibTeX, GEXF | -- | PASS (with issues) |
| Phase 8: Live tracking setup | ritzau_via | FREE | PASS |

---

## Arena Status Matrix

| Arena | Tier | Attempted | Started | Completed | Records | Error |
|-------|------|-----------|---------|-----------|---------|-------|
| ritzau_via | FREE | Yes | Yes | Yes | 80 | None -- but records are unfiltered (not query-relevant) |
| rss_feeds | FREE | Yes | Yes | Yes | 0 | No matching content found |
| bluesky | FREE | Yes | Yes | FAILED | 0 | "HTTP 403 from public API" |
| gab | FREE | Yes | Yes | FAILED | 0 | "no credential available for platform 'gab' at tier 'free'" |
| gdelt | FREE | Yes | Yes | FAILED | 0 | "request error for term='Gronland': " (empty error message) |
| reddit | FREE | Yes | NO | STUCK | 0 | Task never started -- permanently "pending" |
| youtube | FREE | Yes | NO | STUCK | 0 | Task never started -- permanently "pending" |
| common_crawl | FREE | Yes | NO | STUCK | 0 | Task never started -- permanently "pending" |
| wayback | FREE | Yes | NO | STUCK | 0 | Task never started -- permanently "pending" |
| google_search | MEDIUM | Yes | Yes | FAILED | 0 | "no credential available for platform 'serper' at tier 'medium'" |

---

## Workflow Step Results

### Phase 0: Setup and Login -- PASS

- **POST /auth/bearer/login**: HTTP 200, JWT token returned successfully.
- **GET /dashboard**: HTTP 302 to /dashboard, then 200. Dashboard loads.
- **GET /api/arenas/**: HTTP 200. Returns 25 registered arenas with descriptions, supported tiers, credential status, and custom config fields. The response is well-structured and informative.

**Friction point**: The bearer token login URL is `/auth/bearer/login` which requires knowing the FastAPI-Users routing structure. A researcher writing scripts would need to discover this through OpenAPI docs or trial and error.

### Phase 1: Create Query Design -- PASS (with issues)

- **POST /query-designs/**: HTTP 201. Query design created with 4 search terms, Danish locale (da/dk).
- **POST /query-designs/{id}/actors**: HTTP 201. Two actors added (Mute B. Egede, Mette Frederiksen).
- **PATCH /query-designs/{id}/arena-config/reddit**: HTTP 200. Custom subreddits configured.
- **POST /query-designs/{id}/arena-config**: HTTP 200. All 9 free-tier arenas enabled.

**Issue 1 -- group_id not auto-derived from group_label in JSON API** [core]

When creating a query design via the JSON API with `group_label` set but `group_id` omitted, all terms get `group_id: null`. The form-based endpoint (`POST .../terms`) correctly auto-derives `group_id` from `uuid.uuid5(design_id, group_label.lower())`, but the JSON `create_query_design` endpoint does not apply this logic. This means the boolean grouping (OR logic between "Gronland" and "Greenland") silently fails to take effect when using the API.

**Impact**: A researcher using the API (e.g., from a Jupyter notebook) would believe their OR grouping is configured, but it would have no effect on collection. The terms would be treated as independent keywords.

**Severity**: HIGH

**Issue 2 -- Special characters in query design creation**

The test used ASCII-approximations ("Gronland" instead of "Gronland") in the initial API call because the researcher might not be sure whether the API handles UTF-8 correctly. The system accepted these without warning, but the actual Danish spelling is "Gronland" (with o-slash). There is no guidance on whether the system normalizes or requires exact Danish characters.

**Severity**: LOW

### Phase 2: FREE-tier Batch Collection -- FAIL

- **POST /collections/**: HTTP 201. Run created in "pending" status.
- Collection dispatched to Celery workers.

**Issue 3 -- Estimated credits of 40,400 for an all-FREE collection** [core]

The credit estimation returned `estimated_credits: 40400` for a collection using only FREE-tier arenas. FREE-tier arenas should cost 0 credits. This is deeply confusing for a researcher who is told they need 40,000+ credits to use free platforms.

**Severity**: HIGH

**Issue 4 -- Four arenas permanently stuck in "pending"** [core]

Reddit, YouTube, Common Crawl, and Wayback Machine tasks were created but never transitioned from "pending" to "running." After 8+ minutes of monitoring (and confirmed by the stale_run_cleanup marking previous runs as failed after 24 hours), these tasks never start. The collection run remains in "running" status indefinitely.

The researcher sees a run that appears to be working (status: "running") but is actually dead. There is no timeout, no error, no indication that anything is wrong. The only signal is that the record count stops increasing.

**Impact**: The collection run can never complete. The researcher cannot perform analysis (some endpoints require "completed" status). The researcher has no way to know whether to wait or give up.

**Severity**: CRITICAL

**Issue 5 -- Bluesky returns HTTP 403** [data]

Bluesky search returns "HTTP 403 from public API." The arena is listed as FREE-tier with `has_credentials: true` (Bluesky handle and app password are configured in .env). The error message provides no guidance on what to do.

**Severity**: HIGH

**Issue 6 -- Gab fails claiming missing credentials despite being listed as "no credentials needed"** [core]

Gab is listed in the arenas API with `has_credentials: false` and `supported_tiers: ["free"]`. The arena description says it uses an "unauthenticated API." Yet the collector fails with "No credential available for platform 'gab' at tier 'free'." This contradiction would confuse any researcher.

**Severity**: HIGH

**Issue 7 -- GDELT error message is empty** [data]

GDELT fails with `"gdelt: request error for term='Gronland': "` -- the error message after the colon is blank. The researcher has no information about what went wrong (network error? invalid query? API down?).

**Severity**: MEDIUM

**Issue 8 -- RSS Feeds return 0 records** [data]

The RSS feeds arena completed successfully but collected 0 records. For a hot topic like Greenland in Danish media in February 2026, this is surprising. The likely explanation is that RSS feeds are "forward_only" (temporal_mode) and only capture new items that appear after the query is set up. But this is not communicated to the researcher -- they see "0 records" with no explanation of why a system monitoring 28+ Danish news feeds found nothing about Greenland.

**Severity**: MEDIUM

### Phase 3: Inspect Results -- FAIL (data quality)

- **GET /content/export?format=csv**: HTTP 200. 80 records exported.

**Issue 9 -- Ritzau Via returns unfiltered content, not query-matched results** [data]

All 80 records from Ritzau Via are general press releases with no relationship to the search query ("Gronland", "Greenland", "gronlandsk selvstaendighed", "Gronlands selvstyre"). Examples include:
- Local culture prize in Guldborgsund Kommune
- Equinox Gold (Canadian mining company) financial statements
- Andersen Consulting partnership with Grinity (Czech company)
- Jay Walker podcast distribution deal

None of these contain the search terms. The `search_terms_matched` field is EMPTY for all 80 records. This means either:
(a) The Ritzau Via collector ignores search terms entirely and returns the latest N press releases, or
(b) The search term matching logic is broken.

**Impact**: This is a fundamental data trust failure. A researcher who collects data about Greenland independence discourse and receives press releases about local gymnastics clubs and Canadian mining companies would immediately lose trust in the entire system. If this happened in a published study, it would invalidate the findings.

**Severity**: CRITICAL

**Issue 10 -- Mixed-language content in Danish-locale collection** [data]

Despite the query design being configured with `language: "da"` and `locale_country: "dk"`, multiple records are in English (e.g., Equinox Gold, Jay Walker podcast). The language field on these records shows "en." The Danish locale configuration did not filter out non-Danish content.

**Severity**: HIGH

**Issue 11 -- No titles on Ritzau Via records** [data]

All 80 Ritzau Via records have empty Title fields. The title is instead embedded as the first ~100 characters of the text_content. In the CSV export, the Title column is blank for every row.

**Severity**: MEDIUM

**Issue 12 -- Relative URLs in Ritzau Via records** [data]

URLs for Ritzau Via records are relative paths (e.g., `/pressemeddelelse/14798061/...`) rather than full URLs. A researcher clicking these links from an export file, or a reference manager importing the RIS/BibTeX file, would get broken links.

**Severity**: MEDIUM

### Phase 4: MEDIUM-tier Collection -- FAIL

**Issue 13 -- .env credentials not loaded into credential pool** [core]

Google Search (Serper) has `SERPER_API_KEY` configured in `.env`, and the arenas API reports `has_credentials: true` for google_search. However, the collection fails with "No credential available for platform 'serper' at tier 'medium'."

This indicates that API keys in `.env` are not automatically registered in the database-backed credential pool. There is likely a bootstrap step (e.g., an admin UI page or CLI command to register credentials) that is not documented in the Quick Start instructions.

A researcher following the README would configure their .env, start the application, and assume credentials are ready. They would then be blocked by credential errors with no guidance on the additional registration step.

**Severity**: CRITICAL

### Phase 5: Analysis -- PARTIAL

All analysis endpoints return valid JSON responses, but the data is meaningless because the underlying collection data is irrelevant to the query.

- **GET /analysis/{run_id}/summary**: PASS -- returns correct counts.
- **GET /analysis/{run_id}/actors**: PASS -- returns top actors (press release publishers, not Greenland-related).
- **GET /analysis/{run_id}/terms**: Returns empty array (no search_terms_matched populated).
- **GET /analysis/{run_id}/arena-comparison**: PASS -- correct structure.
- **GET /analysis/{run_id}/network/actors**: PASS -- returns empty graph (expected with single-author records).
- **GET /analysis/{run_id}/emergent-terms**: PASS -- returns TF-IDF terms, but they reflect random press releases, not Greenland discourse.

**Issue 14 -- Analysis endpoints work on "running" status runs** [core]

The analysis ran against a collection run that is still in "running" status (stuck). While this is arguably useful (partial results), it is confusing because the run status never changes. The researcher does not know if the analysis reflects complete or partial data.

**Severity**: LOW

### Phase 6: Actor Discovery and Snowball Sampling -- PASS

- **POST /actors/sampling/snowball**: Returns correct result with 0 discoveries (actors have no platform presences).
- **POST /actors/{id}/similar/cross-platform**: Returns empty array (no presences configured).

These endpoints work correctly. The results are empty because the actors lack platform presences, which is the expected behavior. The snowball sampling correctly reports wave 0 (seeds) and wave 1 (0 discoveries).

**Friction point**: A researcher would need to manually add platform presences (e.g., Bluesky handle, Reddit username) to each actor before snowball sampling can discover anything. The workflow for adding presences requires navigating to the actor profile page -- this is not obvious from the query design editor.

### Phase 7: Export -- PASS (with issues)

| Format | HTTP | Size | Notes |
|--------|------|------|-------|
| CSV | 200 | 1.1 MB | Works, human-readable headers |
| XLSX | 200 | 450 KB | Works |
| NDJSON | 200 | 3.8 MB | Works |
| Parquet | 500 | -- | Missing pyarrow dependency (clear error) |
| RIS | 200 | 569 KB | Works, correct format |
| BibTeX | 200 | 211 KB | Works |
| GEXF (actor) | 200 | 849 B | Works, valid XML (empty graph expected) |

**Issue 15 -- GEXF network_type naming mismatch** [frontend]

The GEXF export endpoint accepts `network_type` values of "actor", "bipartite", "term." But the analysis network endpoints use path names like `/network/actors` (plural). The error message when providing `actor_cooccurrence` is helpful ("Choose from: actor, bipartite, term"), but the naming inconsistency between the export and analysis APIs creates confusion.

**Severity**: LOW

**Issue 16 -- Parquet export fails due to missing optional dependency** [qa]

Parquet export returns HTTP 500 with a clear message about installing pyarrow. This is an optional dependency that is not installed in the default `pip install -e ".[dev]"`. The error message is clear and actionable.

**Severity**: LOW

### Phase 8: Live Tracking Setup -- PASS

- **POST /collections/**: Created live-mode run, HTTP 201.
- **GET /collections/{run_id}/schedule**: Returns schedule info (00:00 Copenhagen time, Europe/Copenhagen timezone).

Live tracking creation and schedule retrieval work correctly. The schedule information is clear and uses the correct timezone.

---

## Data Quality Findings

### DQ-1: Ritzau Via collector does not filter by search terms (CRITICAL)

All 80 records from Ritzau Via are unrelated to the search query. The `search_terms_matched` field is empty for every record. The collector appears to return the latest N press releases without applying any keyword filtering.

**Research impact**: Data collected through this arena cannot be used for any research question, as the content bears no relationship to the researcher's query. Any analysis performed on this data (volume over time, top actors, emergent terms) would produce misleading results.

**Responsible agent**: [data]

### DQ-2: No Danish language filtering applied to Ritzau Via (HIGH)

English-language press releases appear alongside Danish content despite the query design specifying `language: "da"`. The collector either does not pass the language filter to the API, or the Ritzau Via API does not support language filtering.

**Responsible agent**: [data]

### DQ-3: Missing content titles (MEDIUM)

Ritzau Via records have no title field populated. The text_content contains the full press release body, but the title is not extracted. This makes it harder to browse and triage results in the content browser.

**Responsible agent**: [data]

### DQ-4: Relative URLs not resolved to absolute (MEDIUM)

Ritzau Via URLs are relative paths. Without a base URL, these cannot be used to access the original content. This affects export quality (RIS, BibTeX, CSV) and undermines the researcher's ability to verify source material.

**Responsible agent**: [data]

### DQ-5: Zero records from RSS feeds for a major Danish news topic (MEDIUM)

The RSS feeds arena returned 0 records for "Gronland" despite monitoring 28+ Danish news feeds. This is likely a temporal_mode issue (forward_only), but the researcher receives no explanation. For the hottest topic in Danish politics in early 2026 (the Trump-Greenland controversy), returning zero results from Danish RSS feeds is a red flag.

**Responsible agent**: [data]

---

## Recommendations

### CRITICAL (blocks any research use)

1. **[data] Fix Ritzau Via search term filtering**: The Ritzau Via collector must filter results by the query design's search terms. Currently it returns unfiltered press releases. Verify that the `collect_by_terms()` implementation actually passes search terms to the API query, and that `search_terms_matched` is populated on returned records.

2. **[core] Fix permanently stuck collection tasks**: Reddit, YouTube, Common Crawl, and Wayback tasks never transition from "pending" to "running." Investigate the Celery task dispatch mechanism in `dispatch_batch_collection` -- tasks are created in the database but the corresponding Celery tasks are never picked up by workers. Add a timeout mechanism so that tasks stuck in "pending" for more than N minutes are automatically failed with an explanatory error.

3. **[core] Document and/or automate credential pool bootstrapping**: Credentials in `.env` are not automatically available to the credential pool. Either (a) auto-import .env credentials into the pool at startup, or (b) document the required steps to register credentials via the admin UI or CLI. The Quick Start in CLAUDE.md and README must cover this.

### HIGH (significantly impairs research workflow)

4. **[core] Fix group_id derivation in JSON API query design creation**: The `create_query_design` endpoint does not auto-derive `group_id` from `group_label` the way the form-based term endpoint does. Apply the same `uuid.uuid5(design_id, group_label.lower())` logic in the creation route so boolean grouping works via the JSON API.

5. **[core] Fix credit estimation for FREE-tier collections**: A collection using only FREE-tier arenas should estimate 0 credits, not 40,400. The credit estimation logic appears to assign costs to free arenas, which is confusing and could prevent researchers from launching collections if they have no credit allocation.

6. **[data] Fix Bluesky HTTP 403**: The Bluesky arena has credentials configured but returns 403. Investigate whether the app password has expired, the API endpoint has changed, or there is an authentication flow issue. Provide a more descriptive error message (e.g., "Bluesky authentication failed -- check your app password in Settings > App Passwords").

7. **[core] Fix Gab credential requirement**: Gab is documented as using an "unauthenticated API" and the arenas API reports `has_credentials: false`. Yet the collector requires a credential from the pool. Either make Gab truly unauthenticated or update the documentation and arena metadata to indicate that a credential is needed.

8. **[data] Enforce Danish language filtering on Ritzau Via**: English content should not appear when the query design specifies `language: "da"`. Either apply a language filter at the API level, or post-filter results by detected language.

### MEDIUM (causes confusion or requires workarounds)

9. **[data] Fix GDELT empty error message**: The GDELT error "request error for term='Gronland': " has a blank message after the colon. Capture and include the actual exception message so the researcher understands whether this is a network error, API error, or query syntax issue.

10. **[data] Populate titles for Ritzau Via records**: Extract the title/headline from Ritzau Via responses and populate the `title` field on content records.

11. **[data] Resolve relative URLs to absolute**: Prepend the Ritzau Via base URL to relative paths so that exported URLs are clickable and usable in reference managers.

12. **[frontend] Add "forward-only" explanation to RSS feeds results**: When an arena with `temporal_mode: forward_only` returns 0 records in a batch collection, display a note explaining that this arena only captures new content published after the collection starts, and that historical search is not available.

13. **[core] Add task-level timeouts**: Implement a configurable timeout (e.g., 10 minutes) per collection task. If a task remains in "pending" or "running" beyond the timeout, mark it as "failed" with a timeout error. This prevents the "stuck forever" pattern.

### LOW (polish items)

14. **[frontend] Align GEXF network_type naming with analysis endpoints**: Use consistent naming between the export `network_type` parameter ("actor", "bipartite", "term") and the analysis path names ("/network/actors", "/network/bipartite", "/network/terms").

15. **[qa] Document pyarrow as an optional dependency for Parquet export**: The error message is good, but the installation extras should include a `parquet` option (e.g., `pip install ".[parquet]"`) for clarity.

16. **[frontend] Add JSON content negotiation to content browser**: The `/content/` endpoint returns HTML by default. Add `Accept: application/json` content negotiation or a separate `/content/records` JSON endpoint so researchers writing scripts can access content data programmatically without the export endpoint.

---

## Summary Statistics

| Metric | Value |
|--------|-------|
| Total arenas attempted | 10 |
| Arenas that completed successfully | 2 (ritzau_via, rss_feeds) |
| Arenas that failed with errors | 3 (bluesky, gab, gdelt) |
| Arenas permanently stuck | 4 (reddit, youtube, common_crawl, wayback) |
| Arenas not attempted (MEDIUM) | 1 (google_search -- credential failure) |
| Total records collected | 80 |
| Records relevant to search query | 0 (estimated) |
| Collection run completed | No (stuck in "running") |
| Time from launch to giving up | 8+ minutes (run never completed) |
| Critical issues found | 3 |
| High issues found | 5 |
| Medium issues found | 5 |
| Low issues found | 3 |
| Total issues | 16 |

---

## Researcher's Verdict

If I were a Danish discourse researcher who installed this system to track the Greenland independence debate across Danish media platforms, my experience would be:

1. I log in successfully and create a query design -- this part works well.
2. I launch a collection and wait. After 10 minutes of watching "running" status with no progress, I start to worry.
3. The only arena that returned data gave me 80 press releases about gymnastics clubs and Canadian mining companies. None mention Greenland.
4. When I try to use the paid Google Search tier, the system tells me credentials are missing even though I configured them.
5. I cannot run proper analysis because the collection never finishes and the data is irrelevant.
6. I export the data to CSV and confirm it has nothing to do with my research question.

**I would conclude that the system is not ready for research use.** The fundamental promise -- "collect discourse data across platforms for a specific topic" -- is not delivered. The architecture and feature set are impressively comprehensive, but the core data collection pipeline has critical failures that make the output unusable for any research purpose.

The system needs to fix three things before it can support real research: (1) search term filtering must actually work, (2) collection runs must complete reliably, and (3) credential setup must be documented and functional.
