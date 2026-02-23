# End-to-End Acceptance Test Report: Gronland Discourse Tracking

**Date:** 2026-02-23
**Test duration:** Approximately 25 minutes of active testing
**Tester perspective:** Danish discourse researcher, no developer background
**Query design ID:** `7fca2f6d-8863-4e58-8469-ab24ed1396df`
**Collection run ID:** `177152d7-5af4-4d0b-91f7-4be16aeb6b14`

---

## Executive Summary

| Step | Result | Details |
|------|--------|---------|
| 1. Create Query Design | PASS | Created with 6 terms, 13 arenas configured, custom RSS/Reddit/Wikipedia sources |
| 2. Data Collection | PARTIAL | 3365 records collected, but 4 arenas stuck in "pending" indefinitely; run never completes |
| 3. Data Quality Review | FAIL | 95% of Ritzau Via records irrelevant; massive Wikipedia duplication; language filtering weak |
| 4. Snowball Sampling | PARTIAL | Runs but finds nothing useful without pre-configured platform presences |
| 5. Actor-Based Collection | SKIP | Blocked by empty actor presences |
| 6. Analysis | PARTIAL | Summary and temporal work; networks empty; enrichments blocked by stalled run |
| 7. Export | PASS | CSV, XLSX, RIS, BibTeX all work; GEXF empty due to empty network |
| 8. Live Tracking | PARTIAL | Live run created; schedule endpoint works; suspend blocked by pending status |

**Overall verdict:** The application successfully collects real data from multiple platforms, but a researcher cannot complete a full research workflow due to collection runs that never finish, severe data quality problems with Ritzau Via, and a broken link between collected data and the analysis pipeline (empty networks, missing search term matching, no enrichments).

---

## 1. Environment Details

### Services Running
- **uvicorn:** Port 8000, `--reload` mode
- **Celery worker:** 4 concurrency (prefork pool)
- **PostgreSQL 16:** Docker container, healthy
- **Redis 7:** Docker container, healthy
- **MinIO:** Docker container, healthy

### Configured API Credentials
| Platform | Has Credentials | Status |
|----------|----------------|--------|
| Google Search (Serper) | Yes | Working (52 records) |
| Bluesky | Yes | Failed (HTTP 403) |
| Reddit | Yes | Working (137 records) |
| YouTube | Yes | Working (1332 records) |
| TikTok | Yes | Failed (credential pool error) |
| GDELT | N/A (free) | Failed (empty error) |
| RSS Feeds | N/A (free) | Working (125 records from DR, Altinget, TV2, Borsen) |
| Ritzau Via | N/A (free) | Working but returns irrelevant content (539 records) |
| Wikipedia | N/A (free) | Working (1017 records) |
| Gab | No | Failed (no credential) |
| Telegram | No | Not tested |
| Event Registry | No | Not tested |
| X/Twitter | No | Not tested |
| Common Crawl | N/A (free) | Stuck in pending |
| Wayback | N/A (free) | Stuck in pending |
| Google Autocomplete | Yes | Stuck in running (0 records) |

### Arenas Tested (13 enabled)
rss_feeds, bluesky, reddit, youtube, gdelt, ritzau_via, google_search (medium tier), google_autocomplete, wikipedia, common_crawl, wayback, gab, tiktok

---

## 2. Detailed Test Log

### Step 1: Create Query Design

**Action:** POST /query-designs/ with JSON body
**Result:** 201 Created
**Time:** Instant

Created query design "E2E Test Gronland 2026-02-23" with:
- 6 search terms: "gronland", "gronland" (with oe-ligature), "gronlandsk" (with oe-ligature), "greenland", "naalakkersuisut", "Mute B. Egede" (with u-acute)
- Danish locale (language=da, locale_country=dk)
- 13 arenas enabled via POST /query-designs/{id}/arena-config
- Custom RSS feeds: sermitsiaq.ag/rss, knr.gl/da/rss
- Custom subreddits: r/greenland
- Wikipedia seed articles: Gronland, Gronlands_selvstyre, Naalakkersuisut

**Observations:**
- Bulk term endpoint expects a plain JSON array, not a wrapper object. The 422 error message ("Input should be a valid list") is clear enough.
- Arena config uses `id` field (not `platform_name`). This is inconsistent with how arenas are referenced elsewhere.
- Special characters (oe-ligature, u-acute) handled correctly throughout.

### Step 2: Data Collection

**Action:** POST /collections/ with query_design_id and tier=free
**Result:** 201 Created, run started within 1 second
**Time to first records:** Under 5 seconds (37 records at first poll)

**Per-arena outcomes (from SSE stream):**

| Arena | SSE Status | SSE Records | Actual DB Records | Notes |
|-------|-----------|-------------|-------------------|-------|
| google_search | completed | 52 | 215 | SSE undercounts; 4x discrepancy |
| rss_feeds | completed | 0 | 125 | SSE says 0 but DB has 125 (DR, Altinget, TV2, Borsen) |
| ritzau_via | completed | 120 | 539 | SSE undercounts; 4.5x discrepancy |
| wikipedia | completed | 17 | 1017 | SSE reports only seed articles; actual is all pageviews |
| bluesky | failed | 0 | 0 | "HTTP 403 from public API" |
| gdelt | failed | 0 | 0 | "request error for term='gronland': " (empty error message) |
| gab | failed | 0 | 0 | "no credential available" |
| tiktok | failed | 0 | 0 | "no credential available" |
| reddit | pending | 0 | 137 | Stuck in "pending" forever; data actually collected |
| youtube | pending | 0 | 1332 | Stuck in "pending" forever; data actually collected |
| google_autocomplete | running | 0 | 0 | Stuck in "running" forever; no data |
| common_crawl | pending | 0 | 0 | Stuck in "pending" forever |
| wayback | pending | 0 | 0 | Stuck in "pending" forever |

**Totals:** Collection run model says 785 records; actual DB count is 3365. The run never transitions from "running" to "completed" because 4 arenas remain stuck in "pending" status forever.

### Step 3: Data Quality Review

**Export method:** Content export as JSON (NDJSON format, 16MB)

**Completeness:**
- 3365 total records across 9 distinct platforms
- Missing title: 539/3365 (all Ritzau Via press releases -- zero titles)
- Missing text_content: 1254/3365 (YouTube videos and Wikipedia pageviews)
- Missing URL: 0/3365 (all have URLs)
- Missing published_at: 0/3365 (all have dates)

**Language Distribution:**
- Danish (da): 52.3% (1760 records) -- only half the data is Danish
- English variants (en, en-US, en-GB, en-IN, en-CA, en-AU, en-IE): 25.4%
- Greenlandic (kl): 3.4% (116 records -- from KNR/YouTube)
- Other languages (de, hi, fr, tr, hu, etc.): 8.4%
- None/unknown: 10.5% (352 records, mostly Google Search)

**Deduplication:**
- 3365 URLs, 1819 unique = 1546 potential duplicates (46%)
- Worst case: da.wikipedia.org/wiki/Gronland appears 35 times (daily pageviews counted as separate records)
- Cross-platform overlap: Wikipedia pages appear in both Google Search results and Wikipedia pageview data

**Relevance (Ritzau Via):**
- Only 26 of 539 Ritzau Via records (4.8%) contain any search term
- Remaining 513 records are completely unrelated press releases (insurance, sports, diabetes, weather)
- All 539 records have relative URLs (e.g., `/pressemeddelelse/14801753/...`) instead of absolute URLs
- Zero records have populated `search_terms_matched` field

**search_terms_matched field:**
Only RSS feed records (dr, altinget, boersen, tv2 = 125 records) have this field populated. All other platforms (3240 records, 96%) have it empty. This breaks the entire term co-occurrence analysis.

**engagement_score:**
Only Reddit (137 records, scores 0.13-1.00) and Wikipedia (797 records, all 0.00) have engagement scores. YouTube, Google Search, and Ritzau Via have none.

### Step 4: Snowball Sampling

**Action:** POST /actors/sampling/snowball with seed actor "Mute B. Egede"
**Result:** Found 0 new actors

**Root cause:** The actor had no platform presences. After manually adding a Reddit presence, the snowball ran but still found 0 new actors in wave 1.

**Cross-platform matching test:** POST /actors/{id}/similar/cross-platform
**Result:** Found 10 results, all completely wrong -- searched Reddit for "Muted" (partial name match) and returned random users (u/Muted-Bar8442, u/Muted-Bear-8957, etc.) with confidence scores 0.0-0.125.

### Step 5: Analysis

**Descriptive summary:** Works. Shows 785 records grouped by arena_name (social_media: 596, news_media: 120, google_search: 52, reference: 17). Uses arena_name not platform_name, so Reddit and YouTube are indistinguishable.

**Top actors:** Dominated by irrelevant Ritzau Via sources (Globenewswire, Danmarks Idretsforbund, If Forsikring, Diabetesforeningen) and English YouTube channels (Fox News, CNN, NBC News). Only 1 relevant Greenland actor: "KNR Nutaarsiassat / KNR News".

**Top terms:** Returns empty array -- search_terms_matched is unpopulated for 96% of records.

**Actor co-occurrence network:** 0 nodes, 0 edges -- author_id FK not populated (no entity resolution).

**Term co-occurrence network:** 0 nodes, 0 edges -- search_terms_matched unpopulated.

**Suggested terms (TF-IDF):** Polluted with URL fragments ("https", "com", "www", "youtube", "instagram"). "trump" at position 5 and "denmark" at position 7 are the only potentially useful suggestions.

**Temporal comparison:** Works correctly. Shows 347 records in current week vs 18 last week.

**Engagement analysis:** Works but only reflects YouTube data (median 26K views, max 11.3M).

**Enrichment pipeline:** Cannot run -- blocked by "Cannot enrich a run with status 'running'" since the collection never completes.

### Step 6: Export

| Format | Result | File Size | Notes |
|--------|--------|-----------|-------|
| CSV | PASS | 30,277 lines | Human-readable headers, UTF-8 BOM for Excel compatibility |
| XLSX | PASS | 1.8 MB | Correct content type |
| JSON | PASS | 16 MB | Actually NDJSON format despite .json extension |
| RIS | PASS | 27,798 lines | Well-formed RIS entries |
| BibTeX | PASS | 25,687 lines | Correct LaTeX URL escaping; duplicate keys from duplicate records |
| Parquet | FAIL | 25 bytes | File is essentially empty |
| GEXF | FAIL | 23 bytes | Returns JSON `{"nodes":[],"edges":[]}` instead of GEXF XML |

### Step 7: Query Design Update and Live Tracking

**Adding terms:** POST /query-designs/{id}/terms/bulk -- added 3 terms ("trump gronland", "rigsfaellesskab", "arktis"). Works.

**Live tracking:** POST /collections/ with mode=live -- creates run in "pending" status with estimated_credits=9000.

**Schedule endpoint:** GET /collections/{id}/schedule returns `{"next_run_at": "00:00 Copenhagen time"}`. Informative.

**Suspend:** Blocked by "Cannot suspend run with mode='live' status='pending'".

### Step 8: Additional Feature Tests

**Feed discovery:** POST /query-designs/{id}/discover-feeds crashes with `ModuleNotFoundError: No module named 'bs4'`. The researcher sees a raw Python traceback instead of an error message.

**Subreddit suggestion:** GET /query-designs/{id}/suggest-subreddits returns empty array. Functional but unhelpful.

---

## 3. Issues Found

### CRITICAL

**Issue 1: Collection runs never complete** `[core]`
Collection runs remain stuck in "running" status indefinitely because some arenas (reddit, youtube, common_crawl, wayback, google_autocomplete) never transition out of "pending" or "running" in the orchestration layer, even though some of them (reddit, youtube) successfully collected data. This blocks the entire downstream workflow: enrichment cannot run, the run never shows as "completed" in the UI, and the researcher has no way to know their collection is actually done.

**Issue 2: Ritzau Via returns 95% irrelevant content** `[data]`
The Ritzau Via collector returns its entire recent feed (539 records) regardless of search terms. Only 26 records (4.8%) contain any of the researcher's search terms. This severely pollutes the dataset and produces misleading top-actor rankings. The collector appears to ignore search terms entirely and dump all recent press releases.

**Issue 3: SSE arena status tracking disconnected from actual task execution** `[core]`
The SSE event stream reports arena statuses that contradict the actual data. Reddit and YouTube show "pending" with 0 records, but the database contains 137 and 1332 records respectively. RSS feeds shows "completed" with 0 records, but 125 RSS-sourced records exist. Google Search shows 52 records, but 215 exist in the database. The records_collected field on the CollectionRun model (785) is a quarter of the actual count (3365).

**Issue 4: Feed discovery endpoint crashes (missing dependency)** `[qa]`
POST /query-designs/{id}/discover-feeds crashes with `ModuleNotFoundError: No module named 'bs4'`. The error is not caught, so the researcher sees a raw Python traceback. The beautifulsoup4 package appears to be a missing or optional dependency that is not installed.

### HIGH

**Issue 5: search_terms_matched unpopulated for 96% of records** `[core]`
Only RSS feed records (125 of 3365) have the `search_terms_matched` field populated. All other platforms leave it empty. This makes the entire term analysis pipeline useless (top terms returns empty, term co-occurrence network has 0 nodes). A researcher cannot determine which search terms drove which results.

**Issue 6: Wikipedia pageview duplication inflates record counts** `[data]`
A single Wikipedia article creates one content_record per day of pageview data. The "Gronland" article appears 35 times (once per day). With 3 seed articles plus linked articles, this produces 1017 records that are effectively the same URLs with different daily counts. This inflates the dataset by 30% and distorts any volume-based analysis.

**Issue 7: YouTube language filtering inadequate** `[data]`
Only 13% (177 of 1332) YouTube records are in Danish. The majority is English (524) or other languages (de, kl, hi, fr, tr, etc.). Despite `relevanceLanguage=da` and `regionCode=DK` being configured, the YouTube Data API returns predominantly English content for the query "greenland".

**Issue 8: GDELT error message is empty** `[core]`
GDELT failure shows: "gdelt: request error for term='gronland': " with an empty string after the colon. The researcher has no idea what went wrong. The actual error should be logged and displayed.

**Issue 9: Bluesky returns HTTP 403** `[data]`
Despite valid credentials being configured, Bluesky fails with "HTTP 403 from public API". This may indicate an expired app password or a change in the Bluesky public search API. The error message is clear but provides no recovery guidance.

**Issue 10: Network analysis completely empty** `[core]`
Both actor co-occurrence (0 nodes, 0 edges) and term co-occurrence (0 nodes, 0 edges) networks produce nothing. Actor networks fail because content_records.author_id is never populated (no automatic entity resolution runs). Term networks fail because search_terms_matched is empty. A researcher who navigates to the network tab sees nothing at all.

### MEDIUM

**Issue 11: Arena comparison groups by arena_name not platform_name** `[frontend]`
The arena comparison shows "social_media: 596 records" which combines Reddit (137), YouTube (1332), and potentially other social platforms. A researcher cannot tell which platform contributed what. The analysis should break down by platform_name for meaningful comparison.

**Issue 12: Ritzau Via records have relative URLs** `[data]`
All 539 Ritzau Via records use relative URLs like `/pressemeddelelse/14801753/...` instead of absolute URLs like `https://via.ritzau.dk/pressemeddelelse/14801753/...`. These are not clickable or usable in citations.

**Issue 13: Ritzau Via records have no titles** `[data]`
All 539 Ritzau Via records have empty title fields. Only the text_content is populated. This makes the content browser and exports less useful since titles are the primary identifier in most views.

**Issue 14: TikTok and Gab fail with misleading credential error** `[core]`
TikTok has credentials configured in .env (TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET are set), yet the collection fails with "no credential available for platform 'tiktok' at tier 'free'". The credentials may not have been stored in the credential pool database. The error message suggests adding credentials, but they are already in .env.

**Issue 15: Suggested terms polluted with URL fragments** `[data]`
TF-IDF term extraction returns "https", "com", "www", "youtube", "instagram" as top suggestions. URLs in text_content and raw_metadata are not stripped before TF-IDF analysis. Useful terms like "trump" and "denmark" are buried at positions 5 and 7.

**Issue 16: Cross-platform actor matching returns false positives** `[data]`
Searching Reddit for "Mute B. Egede" returns random users whose names start with "Muted-" (Muted-Bar8442, Muted-Bear-8957, etc.). The string matching appears to do substring/prefix matching on usernames rather than name matching, producing useless results.

**Issue 17: Parquet export produces empty file** `[core]`
The Parquet export produces a 25-byte file that contains no data. Either the export function is broken or the content type / encoding is wrong.

### LOW

**Issue 18: JSON export uses NDJSON format** `[frontend]`
The `format=json` export produces newline-delimited JSON (one object per line) rather than a JSON array. This is technically a different format and may confuse researchers who try to parse it with standard JSON parsers. The error from `json.load()` ("Extra data") is not self-explanatory.

**Issue 19: Arena config endpoint uses "id" field inconsistently** `[frontend]`
The arena config POST endpoint expects `{"id": "bluesky"}` while the arena registry API returns `{"platform_name": "bluesky"}`. This inconsistency would confuse a researcher writing scripts against the API.

**Issue 20: BibTeX export has duplicate citation keys** `[data]`
When the same URL appears multiple times (Wikipedia pageviews), the BibTeX export generates duplicate citation keys (e.g., `record_ef617d61` appears twice). LaTeX/BibTeX will reject or silently drop duplicates.

**Issue 21: Google Search records have no language tag** `[data]`
All 215 Google Search records have `language: null` despite the search being configured with Danish locale (`gl=dk`, `hl=da`). The normalizer does not infer or set language for Google Search results.

**Issue 22: Engagement scores missing for most platforms** `[data]`
Only Reddit (0.13-1.00) has meaningful engagement scores. YouTube, the largest data source (1332 records), has zero engagement scores despite YouTube providing view counts, like counts, and comment counts. Wikipedia scores are all 0.00 (functionally useless).

---

## 4. Data Quality Assessment

### By Platform

| Platform | Records | Relevance | Language Quality | Completeness | Dedup Status |
|----------|---------|-----------|-----------------|--------------|--------------|
| YouTube | 1332 | Mixed (broad "greenland" query) | 13% Danish | No text content | No major dupes |
| Wikipedia | 1017 | Good (seed articles) | 100% Danish | No text content | Severe (35x per URL) |
| Ritzau Via | 539 | 4.8% relevant | 82% Danish | No titles, relative URLs | Minor |
| Google Search | 215 | Good | No lang tag | Has titles + snippets | Minor cross-platform |
| Reddit | 137 | Good | Mixed (no lang tag) | Has text content | Minor |
| DR/TV2/Altinget/Borsen | 125 | Excellent (term-matched) | 100% Danish | Full articles | None |
| RSS Feeds total | 125 | Excellent | 100% Danish | Full articles | None |

### Key Quality Metrics
- **Precision (records actually about Gronland):** Approximately 70% (RSS: 100%, Google: ~90%, YouTube: ~60%, Wikipedia: ~80%, Ritzau Via: ~5%)
- **Recall (estimated coverage of major Danish Gronland coverage):** Low. No Bluesky, no GDELT, no X/Twitter. RSS feeds only capture what's published during the collection window.
- **Temporal coverage:** 2009 to 2026 (YouTube historical), but bulk of content from last week
- **Cross-platform deduplication:** Not performed. Same stories appear in Google Search results and RSS feeds.

---

## 5. Recommendations (Prioritized)

### Must Fix Before Research Use

1. **Fix collection run completion logic** `[core]` -- Runs must transition to "completed" when all arena tasks have finished or timed out. A stuck arena should not block the entire run forever. Add a configurable timeout per arena (e.g., 5 minutes) after which the arena is marked as "timed_out" and the run can complete.

2. **Fix Ritzau Via search term filtering** `[data]` -- The collector must filter press releases by search terms rather than dumping the entire feed. Only records matching at least one search term should be stored.

3. **Populate search_terms_matched for all platforms** `[core]` -- This field is critical for term analysis and is the primary link between what the researcher asked for and what was collected. Every arena collector's normalize() method should set this field.

4. **Fix SSE event record counting** `[core]` -- The SSE status events and the CollectionRun.records_collected field must reflect the actual number of records stored. A 4x discrepancy between reported and actual counts destroys researcher trust.

### Should Fix Soon

5. **Add dependency check for feed discovery** `[qa]` -- Either install beautifulsoup4 as a required dependency or catch the ImportError gracefully with a user-friendly message ("Feed discovery requires the 'scraping' optional dependency").

6. **Deduplicate Wikipedia pageview records** `[data]` -- Consider storing pageview time series as a single record with daily counts in raw_metadata, rather than one record per day per article. Alternatively, provide a deduplication strategy that collapses pageview records.

7. **Improve YouTube language filtering** `[data]` -- Add post-collection language filtering or use the language detection enricher to filter non-Danish results. The YouTube API's relevanceLanguage parameter is clearly insufficient.

8. **Fix Ritzau Via URLs** `[data]` -- Prepend the base URL (https://via.ritzau.dk) to all relative URLs in the normalizer.

9. **Fix Ritzau Via title extraction** `[data]` -- Extract titles from the press release content (first line or first sentence) if the API does not provide a title field.

10. **Strip URLs from TF-IDF suggested terms** `[data]` -- Apply URL detection and removal before running TF-IDF extraction on text content. URL fragments are never useful as suggested search terms.

### Should Fix Eventually

11. **Break arena comparison by platform_name** `[frontend]` -- Show per-platform breakdowns in the arena comparison view, not just per-arena grouping.

12. **Fix GDELT empty error message** `[core]` -- Ensure the actual HTTP error or exception message is captured and displayed.

13. **Add entity resolution during collection** `[core]` -- Automatically run entity resolution (or at least author_id linking) during or immediately after collection to enable network analysis.

14. **Fix cross-platform actor matching** `[data]` -- The name matching algorithm should use proper name similarity (not substring matching on usernames). For a Greenlandic/Danish name like "Mute B. Egede", searching Reddit for "Muted-*" is wrong.

15. **Fix Parquet export** `[core]` -- The Parquet export produces an essentially empty file. Debug and fix the serialization.

16. **Add engagement score extraction for YouTube** `[data]` -- YouTube provides view_count, like_count, and comment_count. These should be normalized into the engagement_score field.

17. **Add credential pool guidance for .env credentials** `[frontend]` -- TikTok has credentials in .env but not in the credential pool database. Either auto-import .env credentials into the pool on startup, or provide clear documentation about how to register credentials.

---

## 6. Researcher Workflow Impact

A researcher attempting to track Gronland discourse using this application today would:

1. **Successfully create a query design** (10 minutes)
2. **Launch a collection and see some data arrive** (5 minutes)
3. **Wait indefinitely for the collection to "complete"** -- it never does
4. **Be unable to run enrichments** (blocked by non-completed status)
5. **See misleading analysis** dominated by irrelevant Ritzau Via press releases about insurance and diabetes
6. **Find empty network visualizations** with no explanation why
7. **Be able to export data** in CSV/XLSX for manual analysis outside the application
8. **Not know that their dataset is only 52% Danish** without manually checking

The application collects real, working data from real platforms -- this is a significant achievement. The gap is in the orchestration and post-collection pipeline: the data lands in the database but the application does not reliably track, validate, or analyze it. A researcher can use the export function to extract data and analyze it in R or Python, but the built-in analysis features are currently unusable for this scenario.
