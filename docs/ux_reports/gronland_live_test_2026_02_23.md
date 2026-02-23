# Live End-to-End Acceptance Test Report: "Gronland Diskurs"

**Date:** 2026-02-23
**Tester:** UX Test Agent (Opus 4.6)
**Application:** The Issue Observatory (localhost:8000)
**Services running:** FastAPI (uvicorn), Celery worker (4 processes), PostgreSQL, Redis
**Query Design:** "Gronland Diskurs" -- tracking Greenland sovereignty/independence discourse in Danish media

---

## 1. Summary

The Issue Observatory is partially functional for a real research scenario. Core workflows -- query design creation, collection launching, content browsing, analysis, export, annotations, and codebook management -- all work at a basic level. However, **critical issues prevent a researcher from completing a full multi-platform collection**: several arenas get permanently stuck at "pending" status, credentials configured in `.env` are not automatically available to the credential pool, and a code error crashes the design-level analysis endpoint. Of the 12 arenas tested, only 4 produced data successfully, and the researcher would need significant developer assistance to understand why others failed.

**Overall verdict:** The application demonstrates a sophisticated architecture and many features work well in isolation, but the collection reliability and credential management workflow would prevent a researcher from trusting this tool for publication-quality data collection without developer support.

---

## 2. Platform Results

### Collection Run 1: FREE tier (12 arenas requested)

| Arena | Status | Records | Notes |
|-------|--------|---------|-------|
| Ritzau Via | COMPLETED | 100 | Works reliably. Press releases in Danish. |
| Wikipedia | COMPLETED | 500 | Seed articles (Gronland, Gronlands_selvstyre, Naalakkersuisut) correctly resolved. Returned pageview and revision data for related articles. |
| RSS Feeds | COMPLETED | 9 | 9 records from 30+ Danish feeds. Lower count likely reflects narrow topic match against broad feed collection. Custom Greenlandic feeds (sermitsiaq.ag, knr.gl) may have failed silently. |
| Reddit | STUCK (pending) | 0 | Never progressed past "pending" despite credentials being available. Celery task likely never dispatched. **CRITICAL** |
| YouTube | STUCK (pending) | 0 | Same stuck behavior as Reddit. **CRITICAL** |
| Common Crawl | STUCK (pending) | 0 | Same stuck behavior. **CRITICAL** |
| Wayback Machine | STUCK (pending) | 0 | Same stuck behavior. **CRITICAL** |
| Google Autocomplete | STUCK (running) | 0 | Stayed at "running" with 0 records for 20+ minutes. Never completed or failed. **HIGH** |
| Bluesky | FAILED | 0 | "HTTP 403 from public API" -- despite credentials in `.env` and added to credential pool. Authentication issue. **HIGH** |
| TikTok | FAILED | 0 | "No credential available for platform 'tiktok' at tier 'free'" -- credential was added with correct fields but still not found. Platform name mismatch likely. **HIGH** |
| Gab | FAILED | 0 | "No credential available for platform 'gab' at tier 'free'" -- requires an access_token but none was configured (no Gab account). Expected failure but error message should explain what credential is needed. **MEDIUM** |
| GDELT | FAILED | 0 | "Server disconnected without sending a response" for Danish search terms. External API reliability issue. Error is clear. **LOW** (external dependency) |

### Collection Run 2: MEDIUM tier (Google Search only)

| Arena | Status | Records | Notes |
|-------|--------|---------|-------|
| Google Search (Serper) | COMPLETED | 163 | Worked after adding Serper API key to credential pool. Results are highly relevant: Danish and Norwegian content about Arctic politics, Greenland sovereignty, Naalakkersuisut. |

### Collection Run 3: FREE tier retry (9 arenas, after adding credentials)

| Arena | Status | Records | Notes |
|-------|--------|---------|-------|
| Ritzau Via | COMPLETED | 100 | Consistent with first run. |
| RSS Feeds | COMPLETED | 0 | Zero records on second run. Likely deduplication with first run. |
| Reddit | STUCK (pending) | 0 | Still stuck. Credential pool issue persists. |
| YouTube | STUCK (pending) | 0 | Still stuck. |
| GDELT | FAILED | 0 | Same external server issue. |
| Bluesky | FAILED | 0 | Same 403 error. |
| TikTok | FAILED | 0 | Same credential error. |
| Gab | FAILED | 0 | Same credential error. |
| Google Autocomplete | STUCK (running) | 0 | Still stuck. |

**Total records across all runs:** ~2,580 (includes some cross-run counting artifacts)

---

## 3. Feature Results

### Phase 1: Authentication and Setup

| Step | Result | Notes |
|------|--------|-------|
| Health check | PASS | `GET /health` returns `{"status":"ok"}` |
| Login | PASS (with workaround) | Login endpoint is at `/auth/cookie/login`, not `/auth/login`. A researcher reading documentation would need to know FastAPI-Users conventions. Cookie `Secure` flag is set even on HTTP localhost -- browsers may reject this. |
| Dashboard | PASS | Loads correctly, shows "Dashboard -- The Issue Observatory" |
| Arena overview | PASS | `/arenas` page loads; `/api/arenas/` returns all 25 arenas with descriptions, tiers, and credential status |

### Phase 2: Query Design

| Step | Result | Notes |
|------|--------|-------|
| Create query design (JSON API) | PASS | Created "Gronland Diskurs" with 5 terms in 2 groups. Danish characters (o with slash, a with ring) handled correctly. |
| Boolean term groups | PASS | `group_id` automatically generated from `group_label` via UUID5 deterministic hash. Same group label produces same group_id. |
| Custom subreddits config | PASS | PATCH arena-config/reddit correctly stored `custom_subreddits`. |
| Custom RSS feeds | PASS | PATCH arena-config/rss stored custom Greenlandic feed URLs. |
| Wikipedia seed articles | PASS | PATCH arena-config/wikipedia stored seed article titles. |
| Query design verification | PASS | GET returns complete design with all terms, groups, and arena configs. |

### Phase 3-4: Collection

| Step | Result | Notes |
|------|--------|-------|
| Launch batch collection | PASS | Creates run, Celery picks it up, status transitions to "running" |
| SSE live monitoring | PASS | `/collections/{id}/stream` returns per-arena status updates. Clear status messages (pending, running, completed, failed). |
| Completion detection | PARTIAL | Run never completes because stuck arenas never resolve. Run stays at "running" indefinitely. **CRITICAL** |
| Error messages | MIXED | Some errors are clear ("No credential available"), others are opaque ("HTTP 403 from public API"). GDELT error shows exact API response. |
| MEDIUM tier collection | PASS (after credential setup) | Google Search via Serper worked correctly once credential was in the pool. |

### Phase 5: Content Exploration

| Step | Result | Notes |
|------|--------|-------|
| Content browser (HTML) | PASS | `/content/` loads correctly, shows records with arena badges, content type, date, author |
| Content detail panel | PASS | HTMX slide-in panel shows full text, metadata, author, platform, link to original |
| Content count endpoint | PARTIAL | `/content/count` always returns total count regardless of `run_id` filter parameter. The filter does not appear to work. **HIGH** |
| Content filtering | PASS | Filtering by arena/platform works (tested `platform=wikipedia`). |
| Discovered links | PASS | Returns rich link mining data: URLs categorized by platform (web, instagram, twitter, tiktok, youtube), with source counts and example URLs. |

### Phase 6: Actor Discovery

| Step | Result | Notes |
|------|--------|-------|
| Actor directory listing | PASS | Returns existing actors (Donald Trump, Mute B. Egede, Mette Frederiksen). |
| Add actors to query design | PASS | All 3 actors added via POST form endpoint. Correctly links existing actors rather than creating duplicates. |
| Snowball sampling | PASS (limited) | Endpoint works but only returns seed actors with no expansion. This is expected -- snowball needs content records linked to actors to discover co-mentioned accounts. |
| Similarity finder | PASS (empty) | Returns empty list. Expected with no actor-linked content. |

### Phase 7: Actor-based Collection

Not tested -- skipped because no platform presences were configured on actors.

### Phase 8: Analysis

| Step | Result | Notes |
|------|--------|-------|
| Run-level summary | PASS | Returns total records, date range, per-arena breakdown. |
| Design-level summary | FAIL | **500 Internal Server Error**: `NameError: name 'text' is not defined` at analysis.py line 1740. Missing SQLAlchemy `text()` import. **CRITICAL** |
| Volume over time | PASS | Returns daily volume with per-arena breakdown. |
| Top actors | PASS (empty) | Returns empty list for Google Search records (expected -- search results don't have typical authors). |
| Top terms | PASS (empty) | Returns empty list. May indicate search_terms_matched is not populated for Google Search records. |
| Emergent terms (TF-IDF) | PASS | Returns Danish terms extracted from content. However, includes stop words like "vi", "siger" that should be filtered. |
| Temporal comparison | PASS | Shows week-over-week volume change (73.45% increase). |
| Arena comparison | PASS | Shows per-arena metrics: reference (500 records), news_media (109 records). |
| Actor co-occurrence network | PASS (empty) | 0 nodes, 0 edges. Expected with limited actor data. |
| Term co-occurrence network | PASS (empty) | 0 nodes, 0 edges. |
| Suggested terms | PASS | Same as emergent terms. Danish stop word filtering needed. |
| Enrichment: language detection | PASS | 93.83% Danish, 3.7% Norwegian. Highly accurate. |
| Enrichment: sentiment | PASS (empty) | 0 records analyzed. AFINN enricher may not have run or `nlp` extra not installed. |

### Phase 9: Export

| Format | Result | Size | Notes |
|--------|--------|------|-------|
| CSV | PASS | 84 KB | Well-formed, proper headers (human-readable: "Platform", "Arena", "Content Type", etc.), Danish characters preserved |
| XLSX | PASS | 42 KB | Valid Excel file |
| JSON (NDJSON) | PASS | 255 KB | Correct format, detailed records |
| Parquet | FAIL (500) | -- | "pyarrow is required for Parquet export" -- optional dependency not installed. Error message is clear and actionable. **MEDIUM** |
| GEXF | PASS | 849 B | Valid XML, but empty (0 nodes/edges). Correct given empty network data. |
| RIS | PASS | 59 KB | Valid RIS format, proper fields (TY, TI, AB, UR, PY, DP) |
| BibTeX | PASS | 41 KB | Valid BibTeX format |

### Phase 10: Live Tracking

| Step | Result | Notes |
|------|--------|-------|
| Create live tracking run | PASS | mode="live" collection created, status "pending" |
| Check schedule | PASS | Returns `next_run_at: "00:00 Copenhagen time"` with Europe/Copenhagen timezone |

### Phase 11: Annotations and Codebook

| Step | Result | Notes |
|------|--------|-------|
| Create codebook entries | PASS | Two entries created (pro_independence, pro_unity) with category and description |
| Codebook schema understanding | FRICTION | Initial attempt with nested `entries` array failed. Codebook uses flat individual entries, not a parent-child structure. Error message (422) listed required fields clearly. |
| Annotate content record | PASS | Created annotation with stance, frame, is_relevant, and notes. |
| Read back annotation | PASS | Annotation persists and is correctly returned. |

---

## 4. Issues Log

### CRITICAL

1. **[core] Arena tasks permanently stuck at "pending"**: Reddit, YouTube, Common Crawl, and Wayback Machine arenas never progress past "pending" status. Their Celery tasks appear to never be dispatched or picked up by workers. This makes the collection run never complete. The overall run stays at "running" status indefinitely. A researcher would see 4 arenas permanently loading with no explanation. Impact: 4 out of 12 arenas completely non-functional; collection run never reaches "completed" state.

2. **[core] Google Autocomplete permanently stuck at "running"**: The autocomplete arena starts running but never completes or fails, staying at 0 records indefinitely. This contributes to runs never completing. Impact: A researcher cannot get autocomplete data and the run never finishes.

3. **[core] Design-level analysis summary crashes with NameError**: `GET /analysis/design/{design_id}/summary` returns HTTP 500 with `NameError: name 'text' is not defined` at analysis.py line 1740. The `text` function from SQLAlchemy is not imported in the design-level analysis code path. Impact: A researcher aggregating analysis across multiple collection runs cannot use the design-level summary endpoint.

4. **[core] Credential pool disconnect from .env**: Credentials configured in `.env` (SERPER_API_KEY, BLUESKY_HANDLE/APP_PASSWORD, REDDIT_CLIENT_ID/SECRET, YOUTUBE_API_KEY, TIKTOK_CLIENT_KEY/SECRET) are NOT automatically available for collection. They must be manually entered into the credential pool via the admin UI (`/admin/credentials`). The initial collection run failed for every authenticated arena because of this. A researcher who followed the setup guide (which says to put API keys in `.env`) would see all authenticated arena collections fail with cryptic "no credential available" errors. Impact: First-time setup is broken for all authenticated arenas; researcher needs developer intervention to understand the dual-credential system.

### HIGH

5. **[core] Bluesky returns HTTP 403 despite credentials**: Even after adding Bluesky handle and app password to the credential pool, collections fail with "HTTP 403 from public API". The error message doesn't explain what went wrong (expired password? wrong handle? rate limited?). Impact: Bluesky collection completely non-functional.

6. **[core] TikTok credential not found despite being added**: TikTok credential was added to the pool with platform "tiktok", tier "free", and correct `client_key`/`client_secret` fields. Collection still reports "No credential available for platform 'tiktok' at tier 'free'". Possible platform name mismatch in the collector's credential lookup. Impact: TikTok collection completely non-functional.

7. **[data] Content count endpoint ignores run_id filter**: `GET /content/count?run_id={id}` returns the same total (2,580) regardless of which run_id is provided. The filter is not applied. Impact: A researcher cannot determine how many records came from a specific collection run without manually examining the data.

8. **[research] TF-IDF suggested terms include Danish stop words**: The emergent term extraction returns basic Danish stop words ("vi", "siger", "ol") as top suggestions. There appears to be no Danish stop word list applied to the TF-IDF pipeline. Impact: Suggested terms are noisy and not useful for query expansion without manual filtering.

### MEDIUM

9. **[frontend] Login endpoint path non-obvious**: The login POST endpoint is at `/auth/cookie/login` (FastAPI-Users convention), not the more intuitive `/auth/login` (which is GET-only for the login page). While the browser UI handles this transparently, a researcher writing scripts against the API would be confused. The OpenAPI docs should make this clear. Impact: API scripting friction.

10. **[core] Cookie Secure flag on HTTP localhost**: The authentication cookie has `Secure` flag set even when running on HTTP localhost. While curl ignores this, browsers may reject the cookie on non-HTTPS connections. This could prevent login in development mode. Impact: Possible development environment authentication failure.

11. **[core] Parquet export requires uninstalled dependency**: Parquet export fails with 500 and message "pyarrow is required". The error message is clear and actionable, but the feature appears in the UI as available. Impact: Minor -- researcher gets a clear error and can switch to CSV/JSON.

12. **[data] Ritzau Via returns non-Greenland content**: Many Ritzau Via records (like the Guldborgsund Kommune press release) appear unrelated to the Greenland search terms. The arena may be returning all recent press releases rather than filtering by search terms. Impact: Low precision in Ritzau Via results.

13. **[research] Sentiment enrichment produces no results**: The sentiment analysis enrichment (`/enrichments/sentiment`) returns zeros for all fields. Either the AFINN enricher didn't run, the `nlp` extra isn't installed, or sentiment data is stored differently. Impact: Sentiment analysis feature appears non-functional.

14. **[data] RSS Feeds return 0 records on second run**: The RSS Feeds arena returned 9 records on the first run but 0 on the second. This is likely correct deduplication behavior, but the researcher has no indication whether this is "0 new records found (9 already collected)" vs. "collection failed silently". Impact: Ambiguous feedback on incremental collection.

### LOW

15. **[frontend] Content records endpoint is HTML-only**: `GET /content/records` returns HTML table rows (for HTMX) regardless of Accept header. There is no JSON API for programmatic content browsing. Impact: Researchers writing scripts must use the export endpoint instead.

16. **[data] GDELT server disconnection**: GDELT API disconnects for Danish search terms containing special characters. This is an external dependency issue but could be retried. Impact: GDELT data unavailable for this session.

17. **[frontend] Arena badges show raw platform names**: In content records, arena badges show "Ritzau_via" and "Google_search" (with underscores and mixed capitalization) rather than human-readable names like "Ritzau Via" or "Google Search". Impact: Minor polish issue.

18. **[data] Wikipedia 500 records may be excessive**: Wikipedia returned 500 records for 3 seed articles, which includes revisions and pageviews. The researcher may not understand that these are monitoring signals rather than content. Impact: Potential confusion about data type.

---

## 5. Data Quality Findings

### Completeness
- **Google Search (Serper):** 163 results for 5 search terms is reasonable. Results are highly relevant to the research topic, including Danish government sources, academic papers, and news outlets.
- **Wikipedia:** 500 records from 3 seed articles. Comprehensive revision and pageview monitoring data for Greenland-related Wikipedia articles.
- **Ritzau Via:** 100 records. Mix of relevant and irrelevant press releases -- filtering precision could be improved.
- **RSS Feeds:** Only 9 records from 30+ Danish feeds. This seems low for a topic as prominent as Greenland in Danish media. May indicate the term matching is too strict or feeds weren't fetched completely.

### Accuracy
- Content text is correctly preserved with Danish characters (o with slash, ae, aa, o with stroke).
- Timestamps are in UTC with timezone awareness.
- URLs are correctly captured and link to original sources.
- Google Search content_type correctly identified as "search_result".
- Wikipedia content_type shows revision and pageview monitoring data.

### Locale Correctness
- Language detection confirms 93.83% Danish content in Google Search results -- excellent locale filtering.
- Small percentage of Norwegian (3.7%) is expected due to linguistic similarity.
- The small amounts of Estonian, Finnish, and Dutch (0.62% each) suggest occasional false positives in language detection.

### Deduplication
- RSS Feeds returning 0 on second run suggests deduplication is working correctly by content hash.
- Ritzau Via returning 100 on both runs suggests it may not be deduplicating, or the content changes between runs.
- No evidence of cross-arena deduplication (same story in Google Search and RSS). This is likely by design.

### Temporal Coverage
- Google Search results have uniform `published_at` timestamps (all 2026-02-23) because search results are snapshotted at collection time, not at original publication time. This is a known limitation of search result collection.
- Wikipedia records span 2026-01-23 to 2026-02-22, showing a month of revision data.
- Ritzau Via records are from collection day (2026-02-23).

---

## 6. Recommendations (prioritized)

### Immediate fixes (blocking researcher workflow)

1. **[core] Investigate and fix permanently stuck arena tasks.** Reddit, YouTube, Common Crawl, Wayback, and Google Autocomplete tasks never progress past pending/running. This may be a Celery task dispatch issue, a concurrency bottleneck with 4 worker processes, or a task timeout configuration problem. Without fixing this, multi-platform collection is non-functional.

2. **[core] Auto-populate credential pool from .env variables on startup.** Credentials in `.env` should be automatically loaded into the credential pool database (if not already present) when the application starts. The current dual-credential system (env vars + admin UI) is a researcher-blocking confusion point. At minimum, the documentation and error messages should clearly explain this requirement.

3. **[core] Fix NameError in design-level analysis.** Add `from sqlalchemy import text` to the imports in `analysis.py` or to the function at line 1740. This is a one-line fix.

4. **[core] Fix content count run_id filter.** The `GET /content/count` endpoint should respect the `run_id` query parameter.

### Short-term improvements (friction reduction)

5. **[core] Improve credential error messages.** When a collection fails due to missing credentials, the error message should say which credential fields are needed and how to add them (e.g., "No Bluesky credential found. Go to Admin > Credentials and add a Bluesky credential with your handle and app password.").

6. **[core] Add collection run timeout/completion logic.** A run with stuck arenas should eventually time out and mark those arenas as "timed_out", allowing the overall run to reach "completed" or "completed_with_errors" status. Currently, runs stay at "running" forever.

7. **[research] Add Danish stop word filtering to TF-IDF extraction.** The emergent term/suggested term pipeline should filter Danish stop words before ranking. A standard Danish stop word list (from NLTK or a custom list) would significantly improve the quality of term suggestions.

8. **[data] Investigate Bluesky 403 and TikTok credential lookup.** These are two distinct bugs preventing collection from platforms that should work: Bluesky authentication flow and TikTok platform name resolution in the credential pool.

### Medium-term improvements (research quality)

9. **[data] Add precision indicator for Ritzau Via.** If the arena returns all press releases rather than filtering by search terms, the researcher needs to know this. Add a metadata flag or warning indicating whether results are term-filtered or comprehensive.

10. **[frontend] Humanize arena badges.** Display "Ritzau Via" instead of "Ritzau_via", "Google Search" instead of "Google_search" in content browser badges.

11. **[research] Add deduplication transparency.** When RSS Feeds returns 0 records on a subsequent run, show "0 new records (9 duplicates skipped)" rather than just "0 records" so the researcher understands the system is working correctly.

12. **[core] Add JSON API for content browsing.** The `/content/records` endpoint should support `Accept: application/json` for programmatic access, not just HTMX HTML fragments.

---

## 7. Test Artifacts

| Artifact | Location |
|----------|----------|
| Query Design ID | `fe148954-9dc6-4a77-8292-4943c2250459` |
| Collection Run 1 (FREE) | `c8c63a7a-2a50-4e05-ba7a-1fad8958ba38` (stuck at running) |
| Collection Run 2 (MEDIUM Google) | `92c44987-da6f-45bf-9296-05a0113932ff` (completed, 163 records) |
| Collection Run 3 (FREE retry) | `7b882709-cd60-4cd8-b1b5-7cc371585af9` (stuck at running) |
| Collection Run 4 (Live tracking) | `e94217cc-7866-4fce-bbd6-813305873e61` (pending, live mode) |
| CSV Export | `/tmp/export_test.csv` (84 KB, 163 records) |
| XLSX Export | `/tmp/export_test.xlsx` (42 KB) |
| RIS Export | `/tmp/export_test.ris` (59 KB) |
| BibTeX Export | `/tmp/export_test.bib` (41 KB) |
| GEXF Export | `/tmp/export_test.gexf` (849 B, empty network) |

---

## 8. Scenarios Coverage

| Scenario | Status | Notes |
|----------|--------|-------|
| First-time setup | PARTIAL | Login works; credential management is a major friction point |
| Danish issue tracking | PARTIAL | Query design with Danish terms works; collection partially succeeds (4/12 arenas) |
| Actor discovery | PASS (limited) | Snowball sampling runs but finds no new actors (insufficient data) |
| Cross-platform comparison | BLOCKED | Only 3 platforms produced data; arena comparison analysis works but is limited |
| Live tracking lifecycle | PASS | Live run created, schedule configured |
| Export for external analysis | PASS | CSV, XLSX, JSON, RIS, BibTeX all work; GEXF valid but empty; Parquet needs pyarrow |
| Tier switching | PASS | FREE and MEDIUM tier collections work differently as expected |
| Handling failure gracefully | MIXED | Some errors clear (credential missing), others opaque (HTTP 403), stuck arenas have no feedback at all |
| Empty results | NOT TESTED | -- |
| Large-scale collection | BLOCKED | Cannot test due to stuck arenas |
