# End-to-End UX Test Report: Gronland Sovereignty Discourse Research Workflow

**Date:** 2026-02-22
**Tester:** UX Research Evaluator (automated scenario)
**Application URL:** http://localhost:8000
**Scenario:** A Danish discourse researcher wants to track media coverage of the Greenland sovereignty issue across multiple platforms, from query design through data collection, analysis, and export.

---

## 1. Executive Summary

The Issue Observatory presents a well-designed and coherent interface for a multi-platform media research workflow. The navigation structure is intuitive, the query design editor is comprehensive, and the analysis and export capabilities are functional. However, the test revealed a **critical blocker**: batch-mode collection runs are created in the database but never dispatched to Celery workers for actual execution. The run remains perpetually "Pending" with no explanation to the researcher, no error message, and no recovery guidance. This renders the primary research workflow non-functional for one-off (batch) collections.

Beyond this blocker, several significant friction points were identified: the arena credential detection mechanism does not reflect .env-configured credentials; the user's display name shows as "None" throughout the interface; the collection launcher's query design dropdown shows "No query designs yet" even when designs exist; and there is a disconnect between the two-step form workflow (create design via form vs. JSON API) that would confuse researchers interacting via the browser.

**Overall assessment: The application has strong architectural foundations and a thoughtful UI, but the batch collection pipeline is broken and prevents the core research workflow from completing.**

---

## 2. Test Results by Phase

### Phase 1: Setup and Discovery -- PASS (with issues)

| Step | Result | Notes |
|------|--------|-------|
| Health check (`/health`) | PASS | Returns `{"status": "ok"}` |
| Arena listing (`/api/arenas/`) | PASS | 25 arenas returned with descriptions, tiers, and config fields |
| Credential audit | PARTIAL | .env has credentials for Serper, Bluesky, Reddit, TikTok, YouTube, but `/api/arenas/` reports ALL arenas as `has_credentials: false` |
| Login | PASS | Cookie-based auth with JWT. Login at `/auth/cookie/login` returns 204 with `access_token` cookie |
| Dashboard | PASS | Loads correctly. Shows credits, active collections, records count, recent collections, quick actions |

**Issues found:**
- **User display name shows "None"** throughout the sidebar and dashboard ("Welcome, None"). The admin user has no name field set. A researcher would expect to see their name or at least their email prefix.
- **All arenas show `has_credentials: false`** despite several being configured in `.env`. The credential pool system is separate from .env environment variables. A researcher who followed the `.env.example` to configure credentials would see the Arenas page claim no credentials exist. There is no guidance on this mismatch.
- **Root URL redirects to `/dashboard` without auth**, then the dashboard returns 401. The 302 -> 401 flow could confuse a researcher -- they would expect either a redirect to login or a dashboard, not a redirect that then fails.

### Phase 2: Query Design Creation -- PASS (with friction)

| Step | Result | Notes |
|------|--------|-------|
| Create query design | PASS | POST `/query-designs/` with JSON body returns 201 |
| Add search terms | PASS | POST to `/query-designs/{id}/terms` with form-urlencoded; 5 terms added across 3 groups |
| Configure arena settings | PASS | PATCH to Reddit (custom subreddits), RSS (Sermitsiaq feed), Wikipedia (seed articles) all return 200 |
| Danish character handling | NOT TESTED | Term entry used ASCII ("gronland" not "gronland"). The form allows Danish characters but testing was done via curl |

**Issues found:**
- **Form submission expects JSON, but the HTML form uses `method="POST"` without JS serialization.** When posting `Content-Type: application/x-www-form-urlencoded` (as a browser form would submit without HTMX), the endpoint returns 422 with "Input should be a valid dictionary or object." The HTMX `hx-post` intercepts in the browser, but this means the form has no graceful fallback for non-JS scenarios.
- **The term form returns HTML fragments** (for HTMX swap) but accepts `application/x-www-form-urlencoded`. This is correct for the HTMX workflow but makes programmatic interaction with the API inconsistent -- some endpoints expect JSON, others accept form-encoded data.
- **No real-time preview of boolean query logic.** A researcher adding terms to groups (core_terms, trump_angle, sovereignty) has no way to see the resulting boolean query that will be sent to each platform. The groups are visible but the logical combination (AND between groups, OR within groups) is not explained on the form itself.

### Phase 3: Data Collection -- BLOCKER

| Step | Result | Notes |
|------|--------|-------|
| Launch collection | PASS (record created) | POST to `/collections/` returns 201. Run ID assigned. Helpful date range warning returned (SB-05). |
| Collection execution | BLOCKER | Run remains at `status: "pending"` indefinitely. No Celery task is dispatched. |
| SSE monitoring | NOT TESTABLE | The SSE stream connects but no events arrive because no tasks run. |
| Per-arena results | NOT TESTABLE | No arena tasks created. |

**Critical finding:**

The `create_collection_run` API endpoint creates a `CollectionRun` database record with `status="pending"` but does **not** dispatch a Celery task to begin the actual data collection for batch-mode runs. The code comment at line 307-308 of `collections.py` states: "Celery task dispatch is deferred to the collection orchestration layer (Task 0.8 / credit service integration)."

The only collection orchestration mechanism that exists (`trigger_daily_collection` in `workers/tasks.py`) processes **live-tracking** designs exclusively. There is no equivalent batch dispatch mechanism.

The researcher's experience: they click "Start Collection," see a run with "Pending" status, wait, and nothing ever happens. There is no error message, no timeout notification, no indication of what to do next. Eventually (after 24 hours) the stale_run_cleanup task will mark the run as "failed" with the message "Marked as failed by stale_run_cleanup: exceeded 24h without completion" -- but the researcher would have given up long before that.

**Research impact: A researcher cannot collect any data through the normal batch workflow. This makes the entire application non-functional for its primary use case.**

### Phase 4: Snowball Sampling -- NOT TESTABLE

Could not test because no data was collected in the Gronland run. The actors directory and snowball features exist in the UI but require collected content with resolved actors.

### Phase 5: Analysis -- PARTIAL (tested on prior data)

| Step | Result | Notes |
|------|--------|-------|
| Analysis dashboard | PASS | Loads correctly for old run (1cd78707) |
| Summary statistics | PARTIAL | Returns `total_records: 135` but `by_arena: []` (empty). The per-arena breakdown is missing. |
| Network analysis (terms) | PASS | Returns term co-occurrence graph correctly |
| Enrichments | NOT TESTED | No enrichment data on existing records |

**Issues found:**
- **Analysis summary reports `by_arena: []` for a run with 135 records.** The researcher would see summary cards (total records, date range) but the per-arena breakdown -- critical for multi-platform research -- shows nothing. This may be a data issue with the old run's records not having proper arena metadata, or a query bug.
- **Analysis requires a "completed" run**, but the page still renders for "failed" runs. This is actually good (data that was collected before failure should be analyzable), but the "Failed" badge on the analysis page has no explanation of what failed and whether the data is trustworthy.

### Phase 6: Export -- PASS

| Step | Result | Notes |
|------|--------|-------|
| CSV export | PASS | 135 records exported. Human-readable headers. Correct `Content-Disposition`. |
| XLSX export | PASS | 57KB file with correct MIME type. |
| GEXF export | PASS (empty) | Valid GEXF structure but no nodes/edges (no actor data in records). |
| Export headers | PASS | `x-record-count`, proper filenames, correct charset. |

**Issues found:**
- **Matched Search Terms column contains stopwords.** For the old "GDPR Test Design" (terms: "klima", "energi"), the CSV shows `search_terms_matched` values like "den | og | i | er | et" -- these are common Danish articles and conjunctions, not the actual search terms. This suggests the matching logic is flagging substring matches of very short words. A researcher seeing this would distrust the data.
- **GEXF export is empty** when actor data is absent. The file is valid XML but contains `<nodes />` and `<edges />`. A researcher who downloads this and opens it in Gephi would see a blank canvas with no explanation of why.

### Phase 7: Live Tracking -- NOT TESTABLE

Could not promote to live tracking because no batch collection completed. The "Promote to Live Tracking" button exists on the query design detail page (SB-08 confirmed), and the research lifecycle indicator is visible.

---

## 3. Arena Status Matrix

| Arena (platform_name) | Tier | .env Credentials | `has_credentials` API | Collected? | Records | Notes |
|----------------------|------|------------------|-----------------------|-----------|---------|-------|
| bluesky | FREE | Yes (handle + app password) | false | No | 0 | Batch dispatch broken |
| reddit | FREE | Yes (client_id + secret) | false | No | 0 | Custom subreddits configured |
| youtube | FREE | Yes (API key) | false | No | 0 | |
| rss_feeds | FREE | N/A (no credentials needed) | false | No | 0 | Custom feed (Sermitsiaq) added |
| gdelt | FREE | N/A | false | No | 0 | |
| ritzau_via | FREE | N/A | false | Yes* | 135* | *From prior "GDPR Test Design" run |
| wikipedia | FREE | N/A | false | No | 0 | Seed articles configured |
| gab | FREE | No | false | No | 0 | |
| tiktok | FREE | Yes (client key + secret) | false | No | 0 | |
| threads | FREE | No | false | No | 0 | |
| common_crawl | FREE | N/A | false | No | 0 | |
| wayback | FREE | N/A | false | No | 0 | |
| url_scraper | FREE | N/A | false | No | 0 | |
| discord | FREE | No | false | No | 0 | |
| google_autocomplete | FREE | N/A | false | No | 0 | |
| google_search | MEDIUM | Yes (Serper API key) | false | No | 0 | |
| event_registry | MEDIUM | No | false | No | 0 | |
| x_twitter | MEDIUM | No | false | No | 0 | |
| facebook | MEDIUM | No | false | No | 0 | |
| instagram | MEDIUM | No | false | No | 0 | |
| openrouter | MEDIUM | No | false | No | 0 | |
| majestic | PREMIUM | No | false | No | 0 | |
| twitch | DEFERRED | No | false | No | 0 | Stub only |
| vkontakte | DEFERRED | No | false | No | 0 | Pending legal review |

**Key observation:** All arenas report `has_credentials: false` despite six services having credentials in `.env`. The credential pool system (Fernet-encrypted DB storage) is separate from environment variables. Credentials loaded from `.env` are apparently not reflected in the `has_credentials` check, which only inspects the DB-backed credential pool.

---

## 4. Issues Log

### BLOCKERS

| # | Issue | Component | Description | Research Impact |
|---|-------|-----------|-------------|-----------------|
| B-1 | Batch collection dispatch is missing | `[core]` | Creating a batch-mode collection run via POST `/collections/` writes a database record but does not dispatch any Celery task. The run remains "pending" forever. The only dispatch mechanism (`trigger_daily_collection`) handles live-tracking mode only. | **A researcher cannot collect any data through one-off batch collections, which is the primary workflow for initial data gathering.** |
| B-2 | No feedback on stuck pending run | `[frontend]` | When a collection run stays at "Pending" status, the collection detail page shows "Records: 0, Credits used: 0, Started: ---" with no error message, no progress indicator, and no guidance. The researcher has no way to know the run will never start. | **The researcher waits indefinitely, not knowing whether to wait longer, retry, or seek help.** |

### MAJOR

| # | Issue | Component | Description | Research Impact |
|---|-------|-----------|-------------|-----------------|
| M-1 | Credential detection disconnected from .env | `[core]` | The `/api/arenas/` endpoint reports `has_credentials: false` for all arenas, even those with credentials configured in `.env`. The credential pool system only checks the DB-backed encrypted store, not environment variables. | A researcher who followed setup instructions to add API keys in `.env` sees every arena marked as "no credentials" on the Arenas page, causing confusion about whether their setup worked. |
| M-2 | Collection launcher shows "No query designs" | `[frontend]` | The collection launcher page (`/collections/new`) displays "No query designs yet" even when query designs exist. The server-rendered select element is empty because the page template does not load the query designs for the dropdown. | The researcher must use the "Run batch collection" button from the query design detail page (which pre-fills the design_id) rather than the general launcher -- but there is no indication of this workaround. |
| M-3 | User display name shows "None" | `[frontend]` | The sidebar and dashboard show "Welcome, None" and the user avatar shows "A" for admin. The bootstrap admin user has no first_name/last_name set. | Minor cosmetic but creates an unprofessional first impression. A researcher might think their account is broken. |
| M-4 | Analysis by_arena returns empty for real data | `[data]` | The analysis summary endpoint returns `by_arena: []` for a collection run with 135 records. The per-arena breakdown -- essential for cross-platform comparison research -- is missing. | The researcher cannot see how records break down across arenas, which is the fundamental unit of analysis in multi-platform research. |
| M-5 | Search term matching produces stopword matches | `[data]` | The `search_terms_matched` field in exported content records contains Danish stopwords ("den", "og", "i", "er", "et") rather than actual research terms. This appears to be a substring matching issue where short common words in search terms match within article text. | Matched terms are meaningless for filtering and analysis. A researcher cannot trust the term-matching data for any quantitative reporting. |

### MINOR

| # | Issue | Component | Description |
|---|-------|-----------|-------------|
| m-1 | Form POST fallback returns 422 | `[core]` | The query design creation form uses `hx-post` (JSON), but native form submission sends form-urlencoded, which the API rejects with a Pydantic validation error. |
| m-2 | Trailing slash redirects | `[core]` | Several routes (e.g., `/content`) redirect 307 to `/content/`. This is standard FastAPI behavior but causes double requests. |
| m-3 | Cookie expiry is 30 minutes | `[core]` | The access_token cookie has `Max-Age=1800` (30 minutes). A researcher doing a long analysis session would be logged out and potentially lose unsaved work in Alpine.js components. |
| m-4 | Boolean query logic not explained in UI | `[frontend]` | The term grouping system (AND between groups, OR within groups) is not documented on the query design editor page itself. A researcher adding groups needs to understand the logic to build effective queries. |
| m-5 | GEXF export is empty without actors | `[data]` | When no actor data exists, the GEXF export contains valid XML but empty nodes/edges. No explanatory note is included in the file or download response to indicate why the graph is empty. |
| m-6 | Credit badge never loads | `[frontend]` | The sidebar credit badge (`/credits/balance`) and dashboard credit card show "Credits: loading..." and "Loading..." because the HTMX polling runs client-side. In curl testing they appear as placeholder text. If credit allocation is not configured, this should show "0 credits" rather than perpetual loading. |
| m-7 | No indication of Celery worker status in UI | `[frontend]` | The System Status page checks PostgreSQL, Redis, and "Overall" health via the API. It does not show whether Celery workers are actually running and processing tasks. A researcher cannot diagnose why their collection is not starting. |

### COSMETIC

| # | Issue | Component | Description |
|---|-------|-----------|-------------|
| c-1 | "Ritzau_via" display name in content browser | `[frontend]` | Platform name shown as "Ritzau_via" (snake_case) rather than "Ritzau Via" or "Via Ritzau" in the content records table. |
| c-2 | locale_country inconsistency | `[core]` | Some query designs store `locale_country: "dk"` (lowercase) while others store `"DK"` (uppercase). Should be normalized. |
| c-3 | Run ID shown as UUID in analysis page subtitle | `[frontend]` | The analysis dashboard shows the full UUID under the page title: "1cd78707-5952-4421-a48e-c34311d48fa0". This is developer-facing; a researcher would prefer to see the query design name or a short run identifier. |

---

## 5. Data Quality Assessment

### Existing Content Records (135 from prior "GDPR Test Design" run)

| Dimension | Rating | Notes |
|-----------|--------|-------|
| **Completeness** | Partial | Records exist from ritzau_via (news_media) and DR (rss_feeds) only. No data from other arenas. The collection appears to have captured a subset of available content. |
| **Accuracy** | Good | Article titles are correct Danish text with proper characters (ae, oe, aa displayed correctly in UTF-8). URLs point to real articles. Timestamps are plausible. |
| **Locale correctness** | Good | All records have `language: da`. Content is genuinely Danish-language material from Danish outlets (DR, TV2, Politiken, etc.). |
| **Deduplication** | Not assessable | Only one arena's data exists per record. Cross-arena deduplication cannot be evaluated. |
| **Temporal coverage** | Partial | Date range spans 2025-12-01 to 2026-02-22 for ritzau_via content, and recent days for RSS. No unexplained gaps visible in the sample. |
| **Search term matching** | Poor | `search_terms_matched` contains generic Danish words ("den", "og", "i", "er") that appear to be matched from the search terms "klima" and "energi" via some substring or token overlap mechanism. The matching logic appears unreliable. |
| **Engagement metrics** | Not available | All engagement fields (views, likes, shares, comments, engagement_score) are empty/null for RSS and Ritzau content, which is expected for those sources. |
| **Pseudonymization** | Working | `author_platform_id` fields contain pseudonymized hashes. The GDPR compliance mechanism appears functional. |

### Gronland Query Design Data

No data was collected due to the batch dispatch blocker (B-1). Cannot assess data quality for the Greenland discourse topic.

---

## 6. Recommendations (Prioritized)

### Priority 1: Critical -- Restore Core Functionality

1. **[core] Implement batch collection dispatch.** The `create_collection_run` endpoint must dispatch a Celery orchestration task when `mode="batch"`. This task should iterate over registered arenas (filtered by tier), send per-arena `collect_by_terms` tasks, and update the run status to "running". Without this, the application's primary workflow is non-functional. This is the single most impactful fix.

2. **[core] Bridge .env credentials to the credential detection check.** The `has_credentials` field on arena info should reflect both the DB-backed credential pool AND any credentials loaded from environment variables. Alternatively, provide clear documentation that .env credentials must be imported into the credential pool via the Admin > API Keys page. Currently, a researcher following the .env setup instructions would never see credentials detected.

3. **[frontend] Show meaningful feedback for stuck pending runs.** When a collection run has been in "pending" status for more than 60 seconds, the collection detail page should show a warning: "This collection has not started processing. This may indicate that the background worker is not running. Please contact your administrator." The SSE stream should also surface this state.

### Priority 2: Major -- Research Workflow Quality

4. **[frontend] Fix collection launcher query design dropdown.** The `/collections/new` page should populate the query design select element from the database. Currently it renders "No query designs yet" even when designs exist. The workaround (using the "Run batch collection" button from query design detail) should remain but not be the only path.

5. **[data] Fix search term matching logic.** The `search_terms_matched` field should contain only the researcher's actual search terms that triggered each record's inclusion, not incidental substring matches of common words. If the matching uses a simple contains/overlap check, it needs to be scoped to the actual query terms ("klima", "energi") rather than decomposed tokens.

6. **[data] Fix analysis by_arena breakdown.** The analysis summary endpoint should return per-arena record counts. If the issue is that records lack proper arena metadata, the normalization pipeline should ensure `arena` and `platform` fields are populated for all records.

7. **[frontend] Set default admin user display name.** The bootstrap admin script should set a display name (e.g., "Administrator") rather than leaving it as None. Alternatively, the sidebar template should fall back to the email prefix when the name is null.

### Priority 3: Important -- Research Experience

8. **[frontend] Show Celery worker status on System Health page.** The admin health page should indicate whether Celery workers are active and processing tasks. The `/api/health` endpoint already checks Celery -- this information should be surfaced on the admin health page with specific worker count or last-active timestamp.

9. **[frontend] Explain boolean query logic on the query design editor.** Add a tooltip or inline help text near the term grouping controls that explains: "Terms within the same group are combined with OR. Different groups are combined with AND. Example: (gronland OR greenland) AND (Trump gronland)."

10. **[core] Extend cookie session timeout.** The 30-minute session timeout is too short for research work. Consider 4-8 hours, or implement a silent token refresh mechanism.

11. **[frontend] Add empty-state guidance for GEXF export.** When a GEXF export would produce an empty graph, show a message explaining that actor data is required for network visualization and suggest running entity resolution first.

12. **[frontend] Normalize platform display names in content browser.** Show "Via Ritzau" instead of "Ritzau_via", "Google Search" instead of "google_search", etc. The `_arenaLabel()` function in the query editor already has this mapping -- it should be reused in the content browser.

---

## 7. Positive Findings

The following aspects of the application work well and represent strong UX design choices:

- **Navigation structure** is clear and maps well to the research workflow (Design -> Collect -> Browse -> Analyze -> Export).
- **Arena overview page** provides excellent research context with tier-organized cards, credential indicators, and descriptions written in research language rather than developer jargon.
- **Query design editor** supports term grouping, per-arena scoping (YF-01), arena-specific configuration (custom RSS feeds, subreddits, Wikipedia articles), and bulk import -- all features a serious researcher needs.
- **Research lifecycle indicator** (SB-12) on the query design detail page gives the researcher a visual sense of where they are in the workflow.
- **Date range warnings** (SB-05) on collection launch helpfully explain which arenas will and will not respect the requested date range.
- **CSV export** uses human-readable headers (IP2-006), includes the content hash for reproducibility, and sets proper HTTP headers for file download.
- **Explore page** (YF-05) provides a low-commitment way to test a topic before creating a formal query design.
- **Codebook management** (SB-16) and **annotation system** (IP2-043) support qualitative coding workflows.
- **Tier precedence explanation** in the collection launcher is clear and accurate.
- **Clone design** button supports iterative query refinement without destroying the original.

---

## 8. Test Environment Notes

- **Application version:** 0.1.0
- **Infrastructure:** PostgreSQL 16 (Docker), Redis 7 (Docker), MinIO (Docker)
- **Celery workers:** The `/api/health` endpoint reports `celery: "ok"`, but no Celery worker process appears to be actively processing tasks. The health check may be testing Redis connectivity rather than actual worker availability.
- **Previous data:** 135 content records exist from a prior "GDPR Test Design" collection (run 1cd78707) that collected from ritzau_via and DR RSS. That run was also marked "failed" by stale_run_cleanup, suggesting the batch dispatch issue is longstanding.
- **Credentials configured in .env:** Serper (Google Search), Bluesky, Reddit, TikTok, YouTube. None of these appear in the DB-backed credential pool.
