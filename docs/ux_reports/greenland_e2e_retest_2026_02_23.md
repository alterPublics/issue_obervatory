# End-to-End Retest Report: Gronland Discourse Tracking

**Date:** 2026-02-23
**Test duration:** Approximately 45 minutes of active testing
**Tester perspective:** Danish discourse researcher, no developer background
**Query design ID:** `7fca2f6d-8863-4e58-8469-ab24ed1396df` (reused from previous test)
**Collection run ID:** `ae53144f-737b-4449-9842-c276f0ff2cf7`
**Previous test report:** `greenland_e2e_test_2026_02_23.md` (22 issues found)

---

## Executive Summary

| Step | Result | Details |
|------|--------|---------|
| 1. Authentication | PASS | Cookie-based auth works, 30-min expiry means re-auth needed during longer sessions |
| 2. Query Design Reuse | PASS | Reused existing design, added 5 new arenas (telegram, event_registry, x_twitter, threads, openrouter) |
| 3. Data Collection | PARTIAL | 11,893 records collected across 6 platforms; 2 arenas permanently stuck; run never completes |
| 4. Data Quality | IMPROVED | Record counts now accurate; Ritzau Via filtered properly; Bluesky works; TikTok works |
| 5. Snowball Sampling | FAIL | Finds 0 new actors; cross-platform matching returns empty |
| 6. Analysis | IMPROVED | Networks now have data (54 nodes/200 edges); term analysis works for Ritzau Via only |
| 7. Export | MOSTLY PASS | CSV, XLSX, NDJSON, RIS, BibTeX all work; Parquet missing dependency; GEXF valid XML but incomplete data |
| 8. Live Tracking | PARTIAL | Creates successfully; schedule endpoint works; suspend blocked by pending status |
| 9. Feed Discovery | FAIL | Still crashes on missing bs4 dependency |

**Overall verdict:** Significant improvements since the previous test. The application now collects 11,893 records (vs 3,365 before), record count accuracy is perfect (was 4x off), and several previously broken arenas (Bluesky, TikTok) now work well. However, the critical collection-never-completes bug persists (now 2 stuck arenas vs 4 before), and the search_terms_matched field remains empty for 99.3% of records, severely limiting the analysis pipeline.

---

## 1. Environment Details

### Services Running
- **uvicorn:** Port 8000, `--reload` mode
- **Celery worker:** 4 concurrency (prefork pool)
- **Celery beat:** Running
- **PostgreSQL 16:** Docker container, healthy
- **Redis 7:** Docker container, healthy
- **MinIO:** Docker container, healthy

### Arenas Tested (18 enabled)
rss_feeds, bluesky, reddit, youtube, gdelt, ritzau_via, google_search (medium), google_autocomplete, wikipedia, common_crawl, wayback, gab, tiktok, telegram, event_registry (medium), x_twitter (medium), threads, openrouter (medium)

---

## 2. Per-Arena Detailed Status

| Arena | Tier | Status | Records (API) | Records (DB) | Match | Quality |
|-------|------|--------|---------------|--------------|-------|---------|
| bluesky | free | COMPLETED | 10,391 | 10,391 | EXACT | Excellent: 99% Danish, 98.5% relevant |
| tiktok | free | COMPLETED | 1,028 | 1,028 | EXACT | Good: 99.5% relevant, has engagement scores, no language/title |
| youtube | free | COMPLETED | 278 | 278 | EXACT | Fair: only 9.7% Danish, no engagement scores |
| google_search | medium | COMPLETED | 109 | 109 | EXACT | Good: relevant results, no language tag |
| ritzau_via | free | COMPLETED | 85 | 85 | EXACT | Excellent: 100% relevant, all have matching terms, absolute URLs, titles |
| rss_feeds (DR) | free | COMPLETED | 2 | 2 | EXACT | Excellent: 100% relevant, Danish, full text |
| reddit | free | COMPLETED | 0 | 0 | EXACT | Deduped from previous run (137 records exist from earlier) |
| wikipedia | free | COMPLETED | 0 | 0 | EXACT | Deduped from previous run (1017 records exist from earlier) |
| common_crawl | free | COMPLETED | 0 | 0 | EXACT | No matching content found |
| threads | free | COMPLETED | 0 | 0 | EXACT | No matching content found |
| wayback | free | COMPLETED | 0 | 0 | EXACT | No matching content found |
| gdelt | free | FAILED | 0 | 0 | N/A | Server disconnected (GDELT API issue) |
| gab | free | FAILED | 0 | 0 | N/A | No credential in pool |
| telegram | free | FAILED | 0 | 0 | N/A | No credential in pool |
| event_registry | medium | FAILED | 0 | 0 | N/A | No credential in pool |
| x_twitter | medium | FAILED | 0 | 0 | N/A | No credential in pool for twitterapi_io |
| google_autocomplete | free | STUCK | 0 | 0 | N/A | Running status, never completes |
| openrouter | medium | STUCK | 0 | 0 | N/A | Pending status, never starts |

**Totals:** API reports 11,893 records; DB confirms 11,893 records. Perfect accuracy.

---

## 3. Comparison with Previous Test (22 Issues)

### Issues FIXED (9 of 22)

| # | Previous Issue | Current Status | Notes |
|---|---------------|----------------|-------|
| 2 | Ritzau Via 95% irrelevant | FIXED | Now 100% relevant (85 filtered records vs 539 unfiltered). Search term matching works. |
| 3 | SSE record counts 4x wrong | FIXED | API total (11,893) matches DB total exactly. Per-platform counts all match. |
| 9 | Bluesky HTTP 403 | FIXED | Bluesky now works excellently: 10,391 records, 99% Danish, high relevance. |
| 12 | Ritzau Via relative URLs | FIXED | All URLs now absolute (https://via.ritzau.dk/...). |
| 13 | Ritzau Via no titles | FIXED | All 85 records now have titles. |
| 14 | TikTok credential pool error | FIXED | TikTok collected 1,028 records with engagement scores. |
| 8 | GDELT empty error message | FIXED | Now shows "RemoteProtocolError: Server disconnected without sending a response." |
| 10 | Network analysis completely empty | PARTIALLY FIXED | Actor network: 54 nodes/200 edges. Term network: 7 nodes/14 edges. But only from Ritzau Via data. |
| 15 | Suggested terms URL pollution | IMPROVED | Top suggestions now "trump", "usa", "danmark". Only "www" (rank 6) and "dk" (rank 4) are URL fragments. |

### Issues PERSISTING (10 of 22)

| # | Previous Issue | Current Status | Notes |
|---|---------------|----------------|-------|
| 1 | Collection runs never complete | PERSISTS (reduced) | 2 arenas stuck (google_autocomplete running, openrouter pending) vs 4 before. Run still never reaches "completed". |
| 4 | Feed discovery crashes (bs4) | PERSISTS | Same ModuleNotFoundError. Researcher sees raw Python traceback. |
| 5 | search_terms_matched empty 96% | PERSISTS (worsened) | Now 99.3% empty (11,806/11,893). Only Ritzau Via (85) and DR (2) populated. Bluesky/TikTok/YouTube/Google all empty. |
| 6 | Wikipedia pageview duplication | NOT TESTABLE | Wikipedia returned 0 new records (deduped from previous run). Previous 1017-record duplication not revalidated. |
| 7 | YouTube language filtering | PERSISTS | Only 9.7% Danish (27/278). Mostly English (78) and German (77). |
| 11 | Arena comparison by arena_name | PERSISTS | "social_media" combines TikTok (1028) and YouTube (278). Researcher cannot see per-platform breakdown. |
| 16 | Cross-platform matching false positives | CHANGED | Now returns empty array instead of false positives. Different bug but still useless. |
| 17 | Parquet export empty | CHANGED | Now gives clear error: "pyarrow is required for Parquet export." Not installed. |
| 21 | Google Search no language tag | PERSISTS | All 109 records have null language. |
| 22 | YouTube no engagement scores | PERSISTS | All 278 records have null engagement_score despite YouTube providing view/like/comment counts. |

### Issues NOT RETESTED (3 of 22)

| # | Previous Issue | Reason |
|---|---------------|--------|
| 18 | JSON vs NDJSON format | Format clarified: "ndjson" is the correct parameter, "json" gives helpful error. |
| 19 | Arena config "id" field inconsistency | Not re-examined in detail. |
| 20 | BibTeX duplicate keys | Not checked (much less duplication in this run). |

### NEW Issues Found (5)

| # | Issue | Severity | Agent |
|---|-------|----------|-------|
| N1 | TikTok records have no language field (0/1,028) | MEDIUM | [data] |
| N2 | TikTok records have no title field (0/1,028) | MEDIUM | [data] |
| N3 | GEXF export via content endpoint has 0 edges despite analysis network having 200 edges | HIGH | [core] |
| N4 | Temporal GEXF export crashes with database error (500), showing raw Python traceback | HIGH | [core] |
| N5 | Bluesky collected 10,391 records during a batch run with no progress indication; researcher had no way to know it was actively collecting for 20+ minutes while appearing "stuck" | MEDIUM | [frontend] |

---

## 4. Data Quality Assessment

### Overall Metrics

| Metric | Previous Test | This Retest | Change |
|--------|--------------|-------------|--------|
| Total records | 3,365 | 11,893 | +254% |
| Platforms collecting data | 7 | 6 (new run) | -1 (but Bluesky/TikTok added) |
| API vs DB count accuracy | 785 vs 3,365 (23%) | 11,893 vs 11,893 (100%) | FIXED |
| Records with search_terms_matched | 125 (3.7%) | 87 (0.7%) | Worsened (Bluesky volume dilutes) |
| Duplicate URLs | 1,546/3,365 (46%) | 12/11,893 (0.1%) | MAJOR FIX |
| Danish language records | 52.3% | ~87% (estimated from Bluesky) | IMPROVED |
| Ritzau Via relevance | 4.8% | 100% | FIXED |

### Per-Platform Quality Grades

| Platform | Relevance | Language | Completeness | Engagement | Terms Matched | Grade |
|----------|-----------|----------|--------------|------------|---------------|-------|
| Bluesky | A (98.5%) | A (99% da) | B (no titles for posts) | B (74.5% populated) | F (0%) | B+ |
| TikTok | A (99.5%) | F (0% tagged) | C (no titles) | A (99.8% populated) | F (0%) | B- |
| Ritzau Via | A (100%) | A (100% da) | A (titles, URLs, text) | F (0%) | A (100%) | A- |
| DR (RSS) | A (100%) | A (100% da) | A (full articles) | F (0%) | A (100%) | A |
| Google Search | A (~90%) | F (0% tagged) | A (titles, snippets) | F (0%) | F (0%) | C+ |
| YouTube | C (19.4%) | C (9.7% da) | B (titles, descriptions) | F (0%) | F (0%) | D+ |

### Key Data Quality Issues

1. **search_terms_matched remains the critical gap.** Only Ritzau Via and RSS feeds populate this field. All other platforms (representing 99.3% of records) have empty arrays. This makes term co-occurrence analysis represent only 0.7% of collected data. A researcher examining the term network would see only Ritzau Via press releases, completely missing the 10,391 Bluesky posts and 1,028 TikTok videos.

2. **YouTube remains the weakest arena.** Only 9.7% Danish content despite Danish locale settings. No engagement scores despite YouTube providing view/like/comment counts. No search_terms_matched. A researcher would be better served by manual YouTube search.

3. **TikTok lacks metadata despite excellent content.** The 1,028 TikTok videos are 99.5% relevant and have good engagement scores, but zero have language tags or titles. A researcher filtering by language would lose all TikTok data.

4. **Deduplication is dramatically improved.** Only 12 duplicate URLs out of 11,893 (0.1%), all in Google Search (same URL returned for different search terms). The Wikipedia pageview duplication from the previous test (35x per URL) was not reproduced since Wikipedia returned 0 new records due to cross-run dedup.

---

## 5. Workflow Impact Assessment

A researcher attempting to track Gronland discourse today would:

1. **Successfully create or reuse a query design** with multiple search terms and arena configurations (5 minutes).
2. **Launch a collection and receive 11,893 records within ~25 minutes** -- this is a substantial dataset covering Bluesky (10K+ posts), TikTok (1K+ videos), YouTube (278 videos), and news sources (10 minutes to launch + 25 minutes collection).
3. **Wait indefinitely for the collection to "complete"** -- it never does because google_autocomplete and openrouter remain stuck. This blocks the enrichment pipeline.
4. **See useful analysis for a small subset:** Temporal comparison works across all data. Volume charts work. The term network and actor network are populated but only from Ritzau Via data (87 records, 0.7% of the dataset).
5. **Be unable to run enrichments** (language detection, sentiment, NER) because the run status never reaches "completed."
6. **Export data successfully** in CSV, XLSX, NDJSON, RIS, and BibTeX formats. GEXF export produces valid XML but with missing edges.
7. **Get misleading analysis results** because the network and term analyses represent only Ritzau Via press releases, while 87% of the data (Bluesky) is invisible to these features.

The gap between "data collected" and "data analyzed" remains the central problem. The collection pipeline has improved enormously, but the analysis pipeline still sees only a tiny fraction of what was collected.

---

## 6. Issues Found (Numbered)

### CRITICAL

**Issue 1: Collection runs never complete (PERSISTS, reduced severity)** `[core]`
The collection run remains stuck in "running" status because 2 of 18 arenas (google_autocomplete, openrouter) never transition to a terminal state. In the previous test, 4 arenas were stuck. The run cannot complete, blocking enrichments and showing perpetual "running" status. The researcher has no timeout mechanism and no way to force completion.

**Issue 2: search_terms_matched empty for 99.3% of records (PERSISTS, effectively worsened)** `[core]`
Only Ritzau Via (85) and DR (2) records have populated search_terms_matched. Bluesky (10,391), TikTok (1,028), YouTube (278), and Google Search (109) all have empty arrays. This makes the entire term analysis pipeline reflect 0.7% of the dataset. The previous test had 3.7% populated; the improvement in Ritzau Via matching is offset by the massive Bluesky volume that lacks term matching.

### HIGH

**Issue 3: GEXF export produces incomplete network data** `[core]`
The analysis network endpoint returns 54 nodes and 200 edges for actor co-occurrence, but the GEXF export via `/content/export?format=gexf&network_type=actor` produces valid GEXF XML with 0 nodes and 0 edges. The bipartite GEXF has 2,267 nodes but 0 edges. The content export and analysis endpoints use different code paths for building networks, and they disagree. A researcher who downloads the GEXF for Gephi gets an empty graph despite the in-browser preview showing a populated network.

**Issue 4: Temporal GEXF export crashes with database error** `[core]`
`GET /analysis/{run_id}/network/temporal/export-gexf?network_type=actor&interval=week` returns HTTP 500 with a raw Python traceback (SQLAlchemy asyncpg error). The researcher sees a database stack trace instead of a network file. No error handler catches this exception.

**Issue 5: Feed discovery crashes on missing bs4 dependency (PERSISTS)** `[qa]`
`POST /query-designs/{id}/discover-feeds` still crashes with `ModuleNotFoundError: No module named 'bs4'`. The researcher sees a full Python traceback. beautifulsoup4 is not installed and the error is not caught.

**Issue 6: YouTube language filtering inadequate (PERSISTS)** `[data]`
Only 9.7% of YouTube records are Danish (27/278). The `relevanceLanguage=da` and `regionCode=DK` parameters are insufficient. English (78), German (77), and other languages dominate. For a Danish-focused collection, the YouTube arena adds more noise than signal.

### MEDIUM

**Issue 7: TikTok records have no language field** `[data]`
All 1,028 TikTok records have null `language` field. The TikTok collector does not set language during normalization. A researcher filtering by `language=da` would lose all TikTok content, even though the text content is overwhelmingly Danish.

**Issue 8: TikTok records have no title field** `[data]`
All 1,028 TikTok records have null `title` field. Video titles or first-line-of-caption should be extracted during normalization. The content browser and exports use titles as the primary identifier.

**Issue 9: Google Search records have no language tag (PERSISTS)** `[data]`
All 109 Google Search records have null `language` despite Danish locale (`gl=dk`, `hl=da`). The normalizer does not set language.

**Issue 10: YouTube has no engagement scores (PERSISTS)** `[data]`
All 278 YouTube records have null `engagement_score` despite YouTube providing view_count, like_count, and comment_count. The engagement normalization pipeline misses YouTube data.

**Issue 11: Arena comparison groups by arena_name not platform_name (PERSISTS)** `[frontend]`
The arena comparison shows "social_media: 1,306 records" which combines TikTok (1,028) and YouTube (278). A researcher cannot see per-platform metrics. The `by_arena` grouping obscures which platform contributed what.

**Issue 12: Bluesky collection shows no progress during extended run** `[frontend]`
Bluesky collected 10,391 records over approximately 20 minutes while its task status showed "running" with 0 records. The researcher had no indication that data was being collected. The SSE stream and polling both showed 0 records until completion. For a 20-minute silent operation, the researcher would reasonably conclude the arena was stuck.

**Issue 13: Credential pool not auto-populated from .env** `[core]`
Five arenas (gab, telegram, event_registry, x_twitter, openrouter) have API credentials configured in `.env` but fail with "no credential available for platform X." The credentials must be manually registered in the database credential pool. The .env credentials are not auto-imported, and there is no guidance about this requirement in error messages.

**Issue 14: Parquet export requires uninstalled dependency** `[qa]`
Parquet export returns HTTP 500 with "pyarrow is required for Parquet export." The error message is helpful (improved from previous test where the file was silently empty), but the dependency is not installed, making the feature non-functional.

### LOW

**Issue 15: Subreddit suggestion returns empty** `[data]`
`GET /query-designs/{id}/suggest-subreddits` returns `[]` for a Gronland-focused query design with existing Reddit data. The feature provides no value.

**Issue 16: Live tracking suspend blocked by pending status** `[core]`
A freshly created live tracking run is in "pending" status and cannot be suspended. The error says "Only live runs with status 'active' can be suspended." There is no way to transition to "active" without waiting for Celery beat to trigger it (potentially hours). A researcher who creates a live run and immediately wants to adjust settings is blocked.

**Issue 17: Authentication expires during testing without warning** `[frontend]`
The 30-minute cookie TTL causes silent auth failures during longer testing sessions. API calls return 401 or redirect to login. No warning is provided before expiry. A researcher in the middle of analysis work would suddenly see errors with no explanation.

---

## 7. Recommendations (Prioritized)

### Must Fix Before Research Use

1. **Fix collection run completion logic** `[core]` -- Add a per-arena timeout (e.g., 10 minutes). When an arena exceeds the timeout, mark it as "timed_out" and let the run complete. The researcher should never wait indefinitely. This is the same recommendation as the previous test and remains the single most impactful fix.

2. **Populate search_terms_matched for all platforms** `[core]` -- This is the bridge between collected data and analysis. Every arena collector must set this field during normalization by matching the content against the query design's search terms. Without this, term analysis reflects only 0.7% of collected data. For platforms that search by term (Bluesky, TikTok, YouTube), the search term used for the API query should be the minimum match.

3. **Install beautifulsoup4 as a dependency** `[qa]` -- Either add it to the main dependency list or to an optional extra, and catch the ImportError with a user-friendly message.

### Should Fix Soon

4. **Auto-populate credential pool from .env** `[core]` -- On application startup, check for API credentials in environment variables and automatically register them in the credential pool. Five arenas failed because credentials existed in .env but not in the database.

5. **Fix GEXF export to match analysis network data** `[core]` -- The content export GEXF code path and the analysis network code path produce different results. The GEXF should contain the same nodes and edges as the in-browser network.

6. **Add TikTok language detection and title extraction** `[data]` -- The TikTok normalizer should extract the video title (or first line of caption) into the title field and detect language from the caption text.

7. **Fix YouTube engagement score extraction** `[data]` -- YouTube provides view_count, like_count, and comment_count in its API response. These should be normalized into engagement_score.

8. **Add progress tracking for long-running arena tasks** `[frontend]` -- Bluesky took 20+ minutes to collect 10,391 records with no progress indication. Stream intermediate record counts during collection so the researcher can see data arriving.

### Should Fix Eventually

9. **Break arena comparison by platform_name** `[frontend]` -- Show per-platform metrics in the arena comparison view. "social_media: 1,306" is less useful than "TikTok: 1,028, YouTube: 278."

10. **Improve YouTube language filtering** `[data]` -- Consider post-collection language filtering or run the language detection enricher automatically on YouTube results to flag non-Danish content.

11. **Add language tag for Google Search results** `[data]` -- Infer language from the search locale settings (gl=dk, hl=da implies likely Danish content) or from content analysis.

12. **Install pyarrow for Parquet export** `[qa]` -- The error message is now helpful, but the feature is non-functional without the dependency.

13. **Fix temporal GEXF export database error** `[core]` -- The endpoint crashes with an unhandled SQLAlchemy error. Add error handling to return a JSON error response instead of a raw traceback.

14. **Add cookie refresh mechanism** `[frontend]` -- Warn the user before the 30-minute session expires, or implement automatic token refresh to prevent silent auth failures.

---

## 8. Summary of Progress

The application has made substantial progress since the initial test:

**Major improvements:**
- Record count accuracy is now perfect (was 4x off)
- Ritzau Via filtering works correctly (was returning 95% irrelevant content)
- Bluesky is now a major data source (10,391 Danish posts)
- TikTok works (was failing with credential errors)
- GDELT error messages are now descriptive
- Deduplication dramatically improved (0.1% duplicates vs 46%)
- Network analysis produces results (was completely empty)
- Suggested terms are more useful (less URL pollution)
- GEXF format is now valid XML (was returning JSON)
- Parquet error message is now helpful (was silently empty)

**Remaining critical gap:**
The collection-never-completes bug and the search_terms_matched gap are the two issues that, together, prevent a researcher from completing a full research workflow. Fix these two, and the application becomes usable for real research. Everything else is polish.

**Data quality transformation:**
The Bluesky arena alone transforms the research utility of this tool. With 10,391 Danish-language posts at 98.5% relevance, a researcher studying Gronland discourse now has a rich Bluesky dataset that would be very difficult to assemble manually. The combination of Bluesky, TikTok, Ritzau Via, and Google Search provides genuine multi-platform coverage of Danish Gronland discourse. The main barrier is that the analysis pipeline cannot see most of this data because search_terms_matched is unpopulated.
