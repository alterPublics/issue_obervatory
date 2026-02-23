# UX Test Report -- Phase E2E Acceptance: Gronland Sovereignty Scenario
Date: 2026-02-23
Arenas tested: bluesky, reddit, youtube, rss_feeds, gdelt, ritzau_via, gab, wikipedia, threads, common_crawl, wayback, google_search, google_autocomplete, tiktok (14 of 25)
Tiers tested: FREE, MEDIUM (google_search)

## Test Context

Research question: "How is the discourse around Greenland sovereignty framed across Danish and international media and social platforms in early 2026?"

Query design: "Gronland - Dansk Suveraenitet 2026" with 6 initial search terms (4 Danish, 2 English), 3 actors (Mette Frederiksen, Mute B. Egede, Donald Trump), custom Reddit subreddits and Wikipedia seed articles.

Application running at localhost:8000 with Celery workers active; Celery beat scheduler NOT running.

---

## Scenarios Tested

| Scenario | Arenas | Tier | Outcome |
|----------|--------|------|---------|
| First-time setup (auth, dashboard) | N/A | N/A | PASS |
| Query design creation with terms + actors | N/A | N/A | PASS with issues |
| Multi-arena batch collection | 14 arenas | FREE + MEDIUM | PARTIAL -- 620 records, 5 arenas failed, 4 stuck pending |
| Content browsing | N/A | N/A | PASS (HTML mode only) |
| Analysis (descriptive, temporal, network) | N/A | N/A | PARTIAL -- 1 SQL crash |
| Export (CSV, XLSX, RIS, BibTeX, GEXF) | N/A | N/A | PASS |
| Enrichments (language, sentiment, entities) | N/A | N/A | FAIL -- language endpoint crashes |
| Query design cloning | N/A | N/A | PASS |
| Adding search terms post-collection | N/A | N/A | PASS |
| Credit estimation | N/A | N/A | FAIL -- wrong estimates |

---

## Passed

1. **Authentication (bearer + cookie)**: Both login methods work correctly. Bearer token returns JSON, cookie session serves HTML pages. HTTP 200 on both paths.

2. **Dashboard rendering**: Loads cleanly with proper page title, navigation, and active run count polling.

3. **Query design creation via JSON API**: POST /query-designs/ correctly creates a design with 6 search terms, Danish locale (da/dk), proper group labels. HTTP 201.

4. **Actor addition to query design**: All 3 actors created with HTTP 201. Actors correctly appear in the Actor Directory with canonical names and types. Existing actors (from prior tests) are linked rather than duplicated.

5. **Arena-specific config via PATCH**: Reddit custom subreddits and Wikipedia seed articles correctly stored via PATCH endpoint. Response confirms the stored values.

6. **Query design cloning**: POST /clone returns HTTP 303 redirect. The clone has all 7 terms, "(copy)" suffix, and preserves arena config and actor lists.

7. **Content export -- CSV**: 3339 lines, valid CSV with human-readable column headers (Platform, Arena, Content Type, Title, Text Content, URL, Author, etc.). BOM present for Excel compatibility.

8. **Content export -- XLSX**: 263KB valid Excel 2007+ file.

9. **Content export -- RIS**: 4579 lines, valid RIS format with TY, TI, AB, AU, UR, PY, DP, ER tags.

10. **Content export -- BibTeX**: 4459 lines, valid BibTeX with @misc entries, proper LaTeX escaping.

11. **Content export -- GEXF**: Valid XML structure with proper GEXF 1.3 schema, node/edge attributes defined. Empty in this case (no actor co-occurrence data) but structurally correct.

12. **Temporal comparison**: Returns meaningful data showing week-over-week change (+105.77%), per-arena breakdowns. Useful for tracking discourse trends.

13. **Analysis summary**: Correctly aggregates records by arena (reference: 500, news_media: 120), shows date range, run status.

14. **Arena comparison**: Per-arena breakdowns with unique actors, unique terms, engagement averages, and temporal bounds.

15. **All HTML pages load**: Dashboard, arenas, explore, content browser, actors directory, codebooks all return HTTP 200.

---

## Friction Points

### F-01: POST /arena-config silently destroys PATCH-set custom configs [core]
**Researcher action**: Researcher configures custom Reddit subreddits via the arena config grid, then clicks "Save" on the tier/enable grid.
**What happened**: The POST /arena-config endpoint replaces the ENTIRE `arenas_config` JSONB column with `{"arenas": [...]}`, wiping any per-arena custom configs (custom_subreddits, seed_articles, etc.) that were set via PATCH.
**Why it matters**: A researcher who carefully configured custom sources then saves their tier preferences will silently lose all source customization. There is no warning. The researcher would only discover this when the collection returns unexpected results.
**Impact**: HIGH -- data integrity. The researcher's carefully curated source lists vanish without notice.

### F-02: Arena config format mismatch between UI grid and collection engine [core]
**Researcher action**: Researcher enables arenas and sets tiers via the arena config grid.
**What happened**: The arena config grid stores data as `{"arenas": [{"id": "bluesky", "enabled": true, "tier": "free"}, ...]}` (list of objects under "arenas" key). But the collection engine's tier precedence code and credit estimation code iterate over the arenas_config dict keys expecting `{"platform_name": "tier_string"}` format. The engine sees keys: "arenas", "reddit", "wikipedia" -- not the individual arena names.
**Why it matters**: Per-arena tier overrides set via the grid (e.g., google_search at medium) may not be correctly applied during collection. The credit estimate incorrectly reports `per_arena: {"arenas": 0, "reddit": 0, "wikipedia": 0}` instead of per-platform estimates.
**Impact**: HIGH -- the researcher cannot trust that their tier configuration is being applied.

### F-03: group_id not auto-derived from group_label in JSON API path [core]
**Researcher action**: Creates a query design via JSON API with group_label="Danish terms" on search terms.
**What happened**: The terms are created with `group_label: "Danish terms"` but `group_id: null`. The form-based add-term endpoint auto-derives `group_id` from `group_label` using `uuid5(design_id, label.lower())`, but the JSON creation path does not.
**Why it matters**: Terms with the same group_label but null group_id may not be recognized as belonging to the same group by downstream logic (boolean query builder, UI grouping).
**Impact**: MEDIUM -- inconsistent behavior between API paths.

### F-04: Content browser returns HTML fragments, not JSON, via API [frontend]
**Researcher action**: Programmer tries to access content records via GET /content/records with Accept: application/json.
**What happened**: The endpoint always returns HTML table row fragments (HTMX partials), not JSON. There is no JSON content listing endpoint for programmatic access to individual records with full metadata.
**Why it matters**: A researcher writing a script to process collected data cannot access individual records via the API. They must use the export endpoints, which return flat files without the rich JSONB metadata.
**Impact**: MEDIUM -- limits programmatic workflow integration.

### F-05: Suggested terms returns common stop words [data]
**Researcher action**: Runs TF-IDF emergent term extraction to discover new search terms.
**What happened**: The top 10 suggested terms are: "og", "the", "at", "er", "for", "det", "en", "til", "der", "and" -- all Danish and English stop words.
**Why it matters**: The feature is rendered useless. A researcher relying on this for iterative query expansion would gain nothing from these suggestions.
**Impact**: MEDIUM -- feature exists but provides no value. Needs stop word filtering for Danish and English at minimum.

### F-06: Credit allocation succeeds but balance remains 0 [core]
**Researcher action**: Admin allocates 100,000 credits to the test user via POST /admin/credits/allocate.
**What happened**: The endpoint returns a success HTML fragment ("Successfully allocated 100000 credits") but subsequent balance checks and collection launches show 0 available credits.
**Why it matters**: Credits cannot be used. All medium/premium tier collections fail with "Insufficient credits" despite allocation appearing to succeed.
**Impact**: HIGH -- blocks all paid-tier collection.

### F-07: Google Search SERPER_API_KEY not recognized by credential pool [core]
**Researcher action**: Has SERPER_API_KEY in .env, expects Google Search collection to work.
**What happened**: Google Search task fails with "No credential available for platform 'serper' at tier 'medium'". The API key exists in .env but the credential pool does not find it.
**Why it matters**: The researcher configured their API key correctly in .env but the system does not use it. The error message references platform 'serper' (internal name) rather than 'Google Search' (user-facing name), which adds confusion.
**Impact**: HIGH -- a core arena (Google Search, MEDIUM tier) is completely non-functional despite correct configuration.

### F-08: Multiple arenas fail with "no credential available" despite .env config [core]
**Researcher action**: Enables TikTok and Gab arenas with FREE tier.
**What happened**: Both fail with "No credential available for platform 'X' at tier 'free'". TikTok has TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET in .env; Gab is listed as not needing credentials in CLAUDE.md.
**Why it matters**: The credential pool seems to require credentials to be registered in the database (via the admin UI) rather than reading from environment variables. But the documentation and .env suggest env vars should work. This is a gap between documentation and implementation.
**Impact**: HIGH -- multiple arenas non-functional.

---

## Blockers

### B-01: Collection run never completes -- tasks stuck in "pending" indefinitely [core]
**Researcher action**: Launches a batch collection with 14 arenas.
**What happened**: After 10+ minutes, 4 arena tasks (reddit, youtube, common_crawl, wayback) remain in "pending" status with no start time, no celery_task_id, and no error. 1 task (google_autocomplete) is stuck in "running" with 0 records. The overall run status remains "running" indefinitely.
**Why it matters**: The researcher cannot determine when their collection is "done". The run never transitions to "completed" status. No clear error is shown. The researcher would be left staring at a spinning indicator forever, unable to proceed to analysis with confidence that all available data has been collected.
**Impact**: BLOCKER -- the fundamental collection workflow does not reach completion.

### B-02: Language enrichment endpoint crashes with SQL GroupingError [data]
**Researcher action**: Views language distribution of collected content via the enrichments dashboard.
**What happened**: HTTP 500 with full Python stack trace: `asyncpg.exceptions.GroupingError: column "content_records.raw_metadata" must appear in the GROUP BY clause or be used in an aggregate function`. The raw SQL in `descriptive.py:1263` has a column alias `language` derived from a JSONB path expression that conflicts with PostgreSQL's GROUP BY requirements.
**Why it matters**: A researcher sees an unrecoverable server error with a stack trace instead of a useful message. The full traceback is returned to the client, which is also a security concern (leaks file paths and internal structure).
**Impact**: BLOCKER -- enrichments dashboard tab for language detection is completely broken.

---

## Data Quality Findings

### DQ-01: Via Ritzau returns unrelated press releases instead of filtered results [data]
**Observation**: The 120 records from ritzau_via include press releases about Teva Pharmaceuticals (FDA drug application), Guldborgsund cultural awards, and other topics completely unrelated to Greenland sovereignty. The search terms ("gronland", "greenland", "trump gronland", etc.) do not appear to be applied as filters.
**Impact**: CRITICAL for research -- a researcher trusting this data would include irrelevant content in their analysis. The arena appears to fetch ALL recent Ritzau content rather than filtering by the query design's search terms.

### DQ-02: RSS Feeds returns 0 records despite 28+ Danish feeds configured [data]
**Observation**: The rss_feeds arena completed successfully but collected 0 records. Given that "Greenland" is a major ongoing topic in Danish news in February 2026, at least some of the 28+ configured Danish feeds (DR, Politiken, Berlingske, etc.) should have matching content.
**Possible cause**: Search term matching may be too strict, or the RSS parser only checks titles (not content), or the feeds were not fetched successfully. The task reports success with 0 records, providing no diagnostic information about why no matches were found.
**Impact**: SIGNIFICANT for research -- a major data source appears non-functional, with no indication of what went wrong.

### DQ-03: Wikipedia returns 500 records with no search term matching metadata [data]
**Observation**: Wikipedia returned 500 records (the clear majority of all collected data). The search_terms_matched field in the export data needs verification. If seed articles were configured, the records should be page revisions related to Greenland, but the lack of clear provenance information in the export makes it difficult to confirm.
**Impact**: MEDIUM -- the data volume is large but the researcher has limited visibility into whether the records actually match their query design or are a generic dump of recent Wikipedia revisions.

### DQ-04: GDELT returns 0 records with truncated error message [data]
**Observation**: The GDELT task failed with error "gdelt: request error for term='gronland': " (empty error detail after the colon). GDELT is configured with `sourcelang:danish` and `sourcecountry:DA`, which should return Danish news content about Greenland. The empty error message provides no diagnostic value.
**Impact**: MEDIUM -- a free-tier news arena is non-functional with no actionable error information.

### DQ-05: Bluesky returns HTTP 403 despite having credentials [data]
**Observation**: Bluesky task fails immediately with "HTTP 403 from public API". Credentials (BLUESKY_HANDLE, BLUESKY_APP_PASSWORD) are configured in .env. The error may indicate the public search API has been deprecated, access is forbidden from this IP, or requires re-authentication, but the error message does not specify the URL that returned 403 or suggest remediation.
**Impact**: MEDIUM -- a social media arena is non-functional. The error message is not actionable.

### DQ-06: No enrichments were run post-collection [core]
**Observation**: Sentiment, language detection, and named entity enrichment all return empty results. The enrichment pipeline (enrich_collection_run Celery task) does not appear to be triggered automatically after collection.
**Impact**: MEDIUM -- enrichments require manual trigger or are only dispatched post-completion, and since the run never completes (B-01), enrichments never run.

---

## Recommendations

### Priority 1 -- Blockers (must fix before researcher use)

1. **[core] Fix collection run completion logic**: Investigate why reddit, youtube, common_crawl, wayback tasks remain in "pending" indefinitely. The orchestration layer may not be dispatching Celery tasks for all arenas, or tasks may fail silently. Add a timeout mechanism that fails stuck tasks after a configurable period and transitions the run to "completed" when all tasks reach terminal state.

2. **[data] Fix language enrichment SQL query**: In `analysis/descriptive.py:1263`, the raw SQL GROUP BY clause must reference the full JSONB path expression, not the column alias. Change `GROUP BY language` to `GROUP BY 1` or repeat the full expression. Also wrap the endpoint in proper error handling that returns a JSON error response, not a stack trace.

3. **[core] Fix credential pool to read .env variables**: The credential pool appears to require database-registered credentials but .env variables (SERPER_API_KEY, TIKTOK_CLIENT_KEY, etc.) should be used as fallback. Document which approach is canonical and make both paths work. This blocks Google Search, TikTok, Gab, and potentially other arenas.

4. **[core] Fix credit allocation persistence**: The admin credit allocation endpoint returns success but the balance remains 0. Investigate whether the CreditAllocation row is actually committed, and whether the CreditService.get_balance() query correctly sums allocations. This blocks all paid-tier collection.

### Priority 2 -- Major Design Issues

5. **[core] Reconcile arena config format between POST /arena-config and collection engine**: Either change the POST endpoint to store `{"platform_name": "tier_string"}` format, or update the collection engine to parse the `{"arenas": [{...}]}` format. Currently neither system understands the other's format.

6. **[core] Prevent POST /arena-config from destroying PATCH configs**: The POST endpoint should merge the arenas list with existing per-arena custom configs, not replace the entire JSONB column. Alternatively, store tier config and custom source config in separate JSONB paths.

7. **[data] Add stop word filtering to suggested terms TF-IDF**: The emergent term extraction must filter common Danish and English stop words before returning suggestions. Without this, the feature provides no research value.

8. **[data] Fix Via Ritzau search term filtering**: The ritzau_via arena must apply search terms as filters. Currently it appears to return all recent press releases regardless of the query design's terms.

9. **[core] Add actionable error messages for credential failures**: Error messages like "No credential available for platform 'serper' at tier 'medium'" should explain what the researcher needs to do (e.g., "Add your Serper API key in the Admin > Credentials page, or set SERPER_API_KEY in your .env file and restart the application").

### Priority 3 -- Polish and Documentation

10. **[core] Auto-derive group_id from group_label in JSON API path**: Match the behavior of the form endpoint. When group_label is provided but group_id is not, derive group_id from uuid5(design_id, label.lower()).

11. **[frontend] Add JSON content listing endpoint**: Provide a JSON-native content records endpoint (separate from the HTMX partials) for programmatic access.

12. **[core] Do not expose stack traces to the client**: In DEBUG mode, full stack traces are returned to the browser. In production, this would be a security risk. Add proper error handling middleware that returns structured JSON errors.

13. **[data] Improve GDELT error reporting**: The GDELT error message is truncated/empty. Ensure the full error detail (HTTP status, response body, URL) is captured in the task error_message.

14. **[research] Document credential registration workflow**: Make it clear whether credentials should go in .env or in the database credential pool (or both), and document the mapping between .env variable names and platform names used by the credential pool.

---

## Test Environment Details

- **Application**: Issue Observatory at http://localhost:8000
- **Auth**: admin@example.com / Bearer token authentication
- **Query Design ID**: d2256aeb-4f4d-4edf-9ede-7ee9180ac91b
- **Collection Run ID**: 5a3f9d0e-1050-41f1-baac-732ba21cd9a7
- **Total records collected**: 620 (500 Wikipedia + 120 Via Ritzau)
- **Arenas succeeded**: 4 (wikipedia, ritzau_via, rss_feeds, threads)
- **Arenas failed**: 5 (bluesky, gab, google_search, tiktok, gdelt)
- **Arenas stuck**: 4 (reddit, youtube, common_crawl, wayback)
- **Arenas still running**: 1 (google_autocomplete)
- **Test duration**: ~15 minutes from login to final status check
