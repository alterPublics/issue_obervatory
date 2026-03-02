# Full Research Lifecycle Workflow Test -- 2026-03-01

**Date:** 2026-03-01
**Topic:** Iran discourse tracking in Danish media
**Tester perspective:** Danish discourse researcher, first-time workflow
**Application:** Issue Observatory running at localhost:8000 (clean database)
**Admin credentials:** admin@example.com / change-me-in-production

## Test Summary

This report documents a comprehensive end-to-end test of the Issue Observatory application, covering the full research lifecycle from project creation through query design, batch collection, data inspection, snowball sampling, and live tracking setup. The test used the topic "Iran" with Danish-language focus across 20 arenas.

**Overall assessment:** The application successfully collects data from multiple platforms in a single workflow and produces research-usable output. However, several bugs and UX gaps would require developer intervention in a real research scenario. The most impactful issues are: (1) actor detail pages crash with a 500 error, (2) arena task statuses incorrectly display as "Pending" after completion, (3) analysis dashboard refuses to show data from cancelled/failed collection runs, and (4) collections become stuck on slow arenas without timeout mechanisms.

---

## 1. Bug Log

### BUG-001: Actor Detail Page Crashes with 500 Error [frontend]

**Severity:** BLOCKER
**Steps to reproduce:**
1. Create an actor with a platform presence that has `follower_count = None`
2. Navigate to `/actors/{actor_id}`
3. Page returns HTTP 500 with TypeError

**Error:**
```
TypeError: '>' not supported between instances of 'NoneType' and 'int'
```

**Root cause:** In `src/issue_observatory/api/templates/actors/detail.html`, line 348:
```jinja
{% if pres.follower_count | default(0) > 0 %}
```
The Jinja2 `default` filter only activates for *undefined* variables, not for `None` values. When `follower_count` is `None` (which it is for all newly created presences), the expression becomes `None > 0`, which raises a TypeError in Python.

**Impact:** Researchers cannot view any actor profile pages, manage platform presences, or use the actor directory effectively. This blocks the entire actor management workflow.

---

### BUG-002: Platform Presence Unique Constraint Collision on Empty String [core]

**Severity:** HIGH
**Steps to reproduce:**
1. Create Actor A with a platform presence: `platform="telegram", platform_user_id=""`
2. Create Actor B with a platform presence: `platform="telegram", platform_user_id=""`
3. Second creation fails with HTTP 409: "A presence for platform 'telegram' with user_id '' already exists."

**Workaround:** Pass `platform_user_id: null` instead of `platform_user_id: ""`. This succeeds because NULL values are treated as distinct in PostgreSQL unique constraints.

**Impact:** When adding multiple actors on the same platform without knowing their numeric platform IDs (which is the common case when entering actors by URL or username), the researcher hits a confusing 409 error on the second actor. The error message references a "user_id" concept that researchers would not understand. The API should coerce empty strings to NULL for `platform_user_id`, or the unique constraint should be on `(platform, platform_username)` rather than `(platform, platform_user_id)`.

---

### BUG-003: Arena Task Statuses Show "Pending" After Completion [frontend] [core]

**Severity:** HIGH
**Steps to reproduce:**
1. Launch a batch collection run
2. Wait for arenas to finish collecting data
3. Observe the Arena Tasks table on the collection detail page
4. Arenas with 600+ records still show status "Pending" instead of "Completed"

**Observed:** All arenas that successfully collected data (bluesky: 12, google_search: 624, youtube: 686, reddit: 173, etc.) remained in "Pending" status even after their data appeared in the content browser. Only arenas that explicitly errored showed "Failed" status.

**Impact:** The researcher cannot tell which arenas finished successfully and which are still waiting. This makes the collection monitoring experience unreliable and creates confusion about whether the collection is complete.

---

### BUG-004: Collection Runs Never Complete (Stuck on Slow Arenas) [core]

**Severity:** HIGH
**Steps to reproduce:**
1. Launch a batch collection with google_autocomplete and x_twitter enabled
2. Observe that both arenas remain in "Running" status for >20 minutes
3. The overall collection run stays in "running" status indefinitely
4. The only way to proceed is to cancel the run, which sets status to "failed"

**Impact:** Collection runs never reach "completed" status because slow or stuck arena tasks have no timeout. This cascades to other issues: the analysis dashboard won't show data from "failed" runs, and the live tracking "Available" section only shows designs with "completed" runs.

---

### BUG-005: Analysis Dashboard Shows "No completed collection runs" Despite Data [frontend] [core]

**Severity:** HIGH
**Steps to reproduce:**
1. Run a collection that gets cancelled (status = "failed") due to stuck arenas
2. Navigate to `/analysis/{run_id}`
3. Page shows: "No completed collection runs yet"
4. Meanwhile, `/content/` shows 2245+ records from this run

**Impact:** The researcher has collected data but cannot access any analysis visualizations (volume over time, top actors, top terms, engagement distributions). The analysis dashboard should show data for runs with `status in ("running", "failed", "completed")` that have `records_collected > 0`, not only "completed" runs.

---

### BUG-006: Top Actors and Top Terms Show count=0 in Analysis API [core]

**Severity:** MEDIUM
**Steps to reproduce:**
1. After a collection with 2245 records, call `GET /analysis/{run_id}/actors?limit=10`
2. All returned actors have `record_count: 0`
3. Same for `GET /analysis/{run_id}/terms?limit=10` -- all terms show `record_count: 0`

**Impact:** Even if the analysis dashboard were accessible, the charts would show incorrect data. The aggregation queries appear to not properly count records by author or matched search terms.

---

### BUG-007: credits_spent Remains 0 After Collection [core]

**Severity:** MEDIUM
**Steps to reproduce:**
1. Allocate 100,000 credits to user
2. Launch a collection that collects 2245 records
3. After collection, `credits_spent` is 0
4. The credit balance is not reduced

**Impact:** Credit tracking is not functioning. Researchers cannot see how many credits a collection cost, and the credit system cannot enforce usage limits. The `estimated_credits` field shows 20050 at launch time but is never settled.

---

### BUG-008: Query Design Form Does Not Link to Project [core]

**Severity:** LOW
**Steps to reproduce:**
1. Create a project via POST `/projects/`
2. Create a query design via POST `/query-designs/form` with `project_id={project_uuid}`
3. Fetch the query design: `project_id` is `null`
4. Must manually attach via POST `/projects/{project_id}/attach/{design_id}`

**Note:** The code in `create_query_design_form` does include `project_id=parsed_project_id`, so this may be a database-level issue (FK constraint failing silently). The project was confirmed to exist before the design was created. This could also be a timing issue if the project creation transaction hadn't fully committed when the design creation ran.

**Impact:** Minor workflow friction -- researchers must manually attach designs to projects after creation via the form.

---

## 2. Issue Log (UX Friction Points)

### ISSUE-001: No Timeout Mechanism for Arena Tasks [core]

**Description:** When an arena collector hangs (as happened with google_autocomplete and x_twitter during testing), the only recourse is to cancel the entire collection run. There is no per-arena timeout, no "skip this arena" button, and no automatic timeout after N minutes.

**Researcher impact:** The researcher watches the progress page for 20+ minutes, sees no change, and must decide whether to cancel all their collected data or keep waiting indefinitely.

**Recommendation:** Add a configurable per-arena timeout (default: 10 minutes). After timeout, mark the arena task as "timed_out" and let the orchestrator continue with remaining arenas. Allow the researcher to manually skip a stuck arena from the collection detail page.

---

### ISSUE-002: No Schedule Display for Live Tracking [frontend]

**Description:** The live tracking management page says "Manage daily automated collections" but never tells the researcher *when* the daily collection runs. There is no mention of timezone, cron schedule, or "next run" time.

**Researcher impact:** The researcher has activated live tracking but has no idea whether data will be collected at midnight Copenhagen time, midnight UTC, or some other schedule. They cannot plan around it.

**Recommendation:** Display "Daily collection runs at 00:00 CET (Europe/Copenhagen)" on the active tracking card, along with "Next run: 2026-03-02 00:00 CET" or similar.

---

### ISSUE-003: Content Browser Does Not Support JSON API [frontend]

**Description:** The content browser at `/content/` and `/content/records` only returns HTML. There is no JSON API endpoint for programmatic access to collected content records.

**Researcher impact:** Cannot easily build scripts or notebooks to analyze content outside the web UI. The only programmatic access is through the export endpoints (CSV/XLSX/JSON), which are not designed for browsing or filtering.

---

### ISSUE-004: Session Expires After 30 Minutes Without Warning [frontend]

**Description:** The JWT cookie has a 30-minute TTL. During a long collection run (which can take 20+ minutes), the session expires silently. The next API call returns `{"detail":"Unauthorized"}` with no helpful message about re-authentication.

**Researcher impact:** A researcher monitoring a collection run will suddenly see empty or error responses without understanding why. The SSE stream may also silently disconnect.

**Recommendation:** (1) Extend cookie TTL to at least 2 hours for active sessions. (2) Add a client-side countdown or auto-refresh mechanism. (3) Show a visible "Session expired -- please log in again" banner instead of raw JSON errors.

---

### ISSUE-005: Date Range Warnings Are Easy to Miss [frontend]

**Description:** When launching a collection with a date range, the response includes a `warnings` array listing arenas that cannot respect the date range. This information is only visible in the JSON response, not prominently displayed in the launcher UI or the collection detail page.

**Observed warning:** "The following arenas will not respect your date range: bluesky, reddit, rss_feeds, ritzau_via, telegram, gab, google_search, google_autocomplete, x_twitter, facebook, instagram, threads, openrouter, discord, wikipedia. They will return recent/current content only."

**Researcher impact:** 15 out of 20 arenas cannot filter by date range, but the researcher may not realize this until they see historical data from 2009 in their results.

---

### ISSUE-006: Actor Addition Workflow Requires Multiple Steps [frontend]

**Description:** Adding an actor with a platform presence requires: (1) add actor by name to the query design, (2) find the actor's UUID, (3) add a platform presence via a separate API call to `/actors/{id}/presences`. There is no single-step "add actor with URL" workflow from the query design editor.

**Researcher impact:** Adding 14 actors with platform presences required ~28 API calls and manual UUID management. A researcher using the web UI would need to: add actor, click "Add presences" link (which opens a new tab), fill in the presence form on the actor detail page (which currently crashes -- see BUG-001), then return to the query design editor.

**Recommendation:** Add a combined form that accepts a platform URL (e.g., `https://bsky.app/profile/socialdemokratiet.dk`) and automatically creates both the Actor and ActorPlatformPresence in one step.

---

### ISSUE-007: Cancelled Collection Shows as "Failed" [frontend]

**Description:** When a researcher cancels a running collection (to stop stuck arenas), the status changes to "failed" rather than "cancelled" or "completed_partial". This makes it impossible to distinguish between genuine failures and intentional cancellations.

**Researcher impact:** The researcher's collection history shows multiple "failed" runs even though they intentionally cancelled them and the data was successfully collected. This creates anxiety about data quality.

---

### ISSUE-008: Record Count Jumps After Cancellation [core]

**Description:** Before cancelling the first collection, `records_collected` showed 2245. After cancelling, it jumped to 12245. The count increases significantly when the run status changes, suggesting records are being counted differently during active runs vs. after termination.

**Researcher impact:** The researcher sees inconsistent record counts, which undermines trust in the data. They cannot tell how many records were actually collected.

---

### ISSUE-009: Live Tracking Unavailable for Designs with Only Failed Runs [frontend]

**Description:** The live tracking "Available for Live Tracking" section only shows designs with completed batch runs. If all batch runs were cancelled/failed (common when arenas get stuck), the design appears in neither "Available" nor "Ready to start" sections.

**Workaround:** The researcher can still start live tracking via the direct API (`POST /live-tracking/start`) or by creating a new batch run that completes successfully.

---

### ISSUE-010: Duplicate Collection on Second Run [core]

**Description:** The second batch collection for the same query design collected new data without deduplicating against the first run. Google Search returned 706 records (previously 624), suggesting overlapping content was collected again.

**Researcher impact:** The researcher may have duplicate records in their dataset. The deduplication system (content_hash, URL normalization) should prevent identical records from being stored, but the record counts suggest otherwise.

---

## 3. Data Quality Assessment

### 3.1 Arenas That Collected Data Successfully

| Arena | Records | Quality Notes |
|-------|---------|---------------|
| Google Search | 624 | Danish-language results (dr.dk, bt.dk, kristeligt-dagblad.dk). Locale settings (gl=dk, hl=da) working correctly. Results are search snippets, not full articles. |
| YouTube | 686 | Mixed quality. Many non-Danish videos (Hindi, Urdu, English) from channels like "India Today", "SAMAA TV", "Geo News". The `relevanceLanguage=da` parameter is a hint, not a filter. |
| Wikipedia | 500 | Large volume. Likely includes revision/pageview data for Iran-related articles. |
| Reddit | 173 | Collected from configured Danish subreddits (r/Denmark). Relevant content. |
| TikTok | 147 | Collected successfully. Platform-specific content types. |
| Ritzau Via | 49 | Danish news agency wire content. High relevance, Danish language confirmed. |
| Facebook | 33 | Actor-based collection from configured Facebook page IDs. |
| Instagram | 21 | Actor-based collection from Enhedslisten's Instagram account. |
| Bluesky | 12 | Danish-language posts about Iran (lang:da filter working). Content is relevant and in Danish. Sample post: "tRump har fort amerikanerne bag lyset. Han ville regimeskifte, ikke en atomaftale." |
| GDELT | 20 | Succeeded on second run (timed out on first). Returns news article references. |

### 3.2 Arenas That Failed

| Arena | Reason | Expected? |
|-------|--------|-----------|
| Gab | No credential configured | Yes -- no GAB_ACCESS_TOKEN in .env |
| Discord | Requires explicit channel_ids | Yes -- expected, needs channel snowflake IDs |
| OpenRouter | Dispatch failure / import error | Partially -- OPENROUTER_API_KEY exists in .env but task dispatch failed |
| GDELT (run 1) | ReadTimeout connecting to api.gdeltproject.org | No -- infrastructure issue, succeeded on retry |
| Wayback Machine | Request error (unspecified) | Unclear -- minimal error detail |
| Google Autocomplete | Stuck in "Running" state for >20 minutes | Bug -- should have timed out |
| X/Twitter | Stuck in "Running" state for >20 minutes | Bug -- should have timed out |

### 3.3 Arenas with Zero Records (Not Failed)

| Arena | Status | Notes |
|-------|--------|-------|
| RSS Feeds | Pending | Expected to find "Iran" in Danish RSS feeds but returned 0 results. May indicate the RSS fetcher only checks recent items which did not contain the search terms. |
| Telegram | Pending | Configured channels (velinformeret, flemmingblicher) may not have posted about Iran during the collection window. |
| Threads | Pending | No credential configured (THREADS_ACCESS_TOKEN empty). |
| Common Crawl | Pending | Historical web archive search -- may take time or have no recent Danish Iran content. |

### 3.4 Language and Locale Accuracy

- **Bluesky:** lang:da filter working correctly. All 12 results are in Danish.
- **Google Search:** gl=dk and hl=da applied. Results are from Danish domains and in Danish.
- **YouTube:** relevanceLanguage=da is NOT a hard filter. Multiple Hindi, Urdu, and English results about Iran mixed with Danish content. **This is a significant data quality issue** -- researchers expecting Danish-language YouTube results will get a multilingual mix.
- **Ritzau Via:** Danish news wire, all content in Danish as expected.
- **Reddit:** Collected from r/Denmark and Danish subreddits. Relevant.

### 3.5 Export Quality

- XLSX export produced a valid 783KB file with 1519 rows and 20 columns
- Column headers are human-readable: "Platform", "Arena", "Content Type", "Title", "Text Content", "URL", "Author", "Author ID (Pseudonymized)", "Published At", "Views", "Likes", "Shares", "Comments", "Engagement Score", "Language", "Collection Tier", "Matched Search Terms", "Content Hash", "Collection Run ID", "Query Design ID"
- Danish characters (ae, oe, aa) are preserved correctly in the XLSX file
- Sample text: "USA gav Iran muligheden for en diplomatisk loesning, men Iran valgte at takke nej"

### 3.6 Pseudonymization

The record detail view includes a "Pseudonymized ID" field, but it was not consistently populated in the records examined. Author display names (e.g., "Henning Pedersen", "kristeligt-dagblad.dk") appear in plaintext, which is expected -- pseudonymization applies to the author_platform_id, not the display name. However, the public_figure bypass mechanism (GR-14) could not be verified because the actor detail pages crash (BUG-001).

### 3.7 Temporal Coverage

- The requested date range was 2026-02-22 to 2026-03-01
- Only GDELT and Wayback Machine support historical date ranges
- YouTube returned content dating back to 2009 (the YouTube API returns historically popular videos matching the search terms)
- Most arenas (Bluesky, Reddit, RSS, Telegram, etc.) only return recent/current content regardless of date range
- The volume-over-time chart data shows entries from 2009-2026, creating a misleading timeline

---

## 4. Workflow Assessment

### 4.1 Project and Query Design Creation (Phase 1)

The project creation workflow is clean -- a simple modal with name, description, and visibility. The query design creation via form also works, defaulting to Danish language (da) and locale (dk).

**Friction points:**
- Project-to-design linking via the form endpoint silently fails (BUG-008)
- The arena configuration grid requires a separate API call after design creation (cannot be set in the initial form)
- Adding search terms works well via HTMX -- each term appears immediately in the list
- Override terms (platform-specific alternatives) are well-designed with clear visual differentiation (amber badges vs. gray badges)

### 4.2 Actor Management (Phase 2)

Actor creation works but the multi-step process is cumbersome:
1. Add actor by name to query design (creates Actor record)
2. Navigate to actor detail page to add platform presences (CRASHES -- BUG-001)
3. Use API calls to add presences (workaround)

The actor detail page crash (BUG-001) is a blocking issue that prevents the entire actor management workflow from functioning through the web UI.

### 4.3 Batch Collection (Phase 3)

Collection launch is straightforward. The credit estimation (20050 credits) is shown upfront, and the "insufficient credits" error when credits are not allocated is clear. The date-range warnings are informative but not prominent enough.

**Critical issues:**
- Arena tasks get stuck without timeout, requiring manual cancellation
- Task statuses do not properly transition from "Pending" to "Completed"
- After cancellation, the run shows as "failed" rather than "cancelled"
- credits_spent never updates from 0

The SSE live monitoring endpoint exists but was not tested directly. The collection detail page does show arena-by-arena progress with records counts, duration, and error messages.

### 4.4 Content Browsing and Data Inspection (Phase 4)

The content browser loads and displays records with platform badges, titles, text excerpts, matched search terms, and publication dates. The record detail page shows comprehensive metadata including a "Show raw metadata" toggle.

**Good:** Platform-specific rendering (Google Search shows "Search snippet" with a note "full content not yet scraped"), external link to original content ("View original"), clear language badge.

**Issues:** No JSON API for content records, making programmatic analysis difficult.

### 4.5 Snowball Sampling (Phase 5)

Snowball sampling works well via the API. From 3 seed actors (Socialdemokratiet, Pelle Dragsted, DR Nyheder), it discovered 20 new actors via Bluesky follows/followers. The discovered actors were highly relevant Danish politicians (Nicolai Wammen, Birgitte Vind, Pernille Rosenkrantz-Theil, Simon Kollerup, Jens Joel, Morten Boedskov, Magnus Heunicke, Benny Engelbrecht).

**Limitation:** The snowball only expanded via Bluesky because other seed actors lacked presences on platforms with expansion support. YouTube and Reddit snowball expansion did not produce results.

**Actor auto-creation:** The `auto_create_actors: true` flag correctly created Actor and ActorPlatformPresence records for all 20 discovered actors.

### 4.6 Live Tracking (Phase 6)

The live tracking page has a well-designed three-section layout:
1. **Active Tracking** -- shows currently active live collections with Suspend/Resume/Stop controls, arena badges, and an expandable timeline chart
2. **Available for Live Tracking** -- shows designs with completed batch runs, with gap-fill confirmation before starting
3. **Ready to Start** -- designs with arena config but no runs

**Issues:**
- The design did not appear in "Available" because all batch runs were "failed" (cancelled)
- No schedule display (when does the daily collection run?)
- The backfill mechanism attempted to run but the batch run status was unclear

---

## 5. Improvement Recommendations

### Priority 1: Blockers (Must fix before researchers can use the system)

1. **[frontend] Fix actor detail page crash** (BUG-001): Change `pres.follower_count | default(0)` to `(pres.follower_count or 0)` in `actors/detail.html` line 348. This is a one-line fix.

2. **[core] Add per-arena timeout for collection tasks** (BUG-004, ISSUE-001): Implement a 10-minute default timeout for arena collection tasks. After timeout, mark the task as "timed_out" and continue with the collection orchestration. Allow the overall run to complete with partial results.

3. **[core] Fix arena task status transitions** (BUG-003): Arena tasks that finish collecting data should transition from "Pending" to "Completed" status. The orchestrator should update task status when the arena collector returns successfully.

4. **[core] Allow analysis dashboard for non-completed runs** (BUG-005): Change the analysis page filter from `status == "completed"` to `records_collected > 0`. Researchers with partially completed or cancelled runs should still be able to analyze their collected data.

### Priority 2: High-value improvements

5. **[core] Fix platform_user_id empty string handling** (BUG-002): Coerce empty strings to NULL for `platform_user_id` in the presence creation endpoint. The unique constraint should not treat all empty strings on the same platform as collisions.

6. **[core] Fix credit settlement** (BUG-007): After a collection run completes or is cancelled, settle the credit reservation and update `credits_spent` with the actual cost.

7. **[core] Fix top actors/terms analysis aggregation** (BUG-006): The analysis endpoints return `record_count: 0` for all actors and terms despite having data. The aggregation queries need debugging.

8. **[frontend] Add "cancelled" status distinct from "failed"** (ISSUE-007): When a researcher cancels a collection, the status should be "cancelled" or "completed_partial", not "failed". This is both a status label issue and a logical distinction.

9. **[frontend] Add schedule display to live tracking** (ISSUE-002): Show "Daily at 00:00 CET" and "Next run: YYYY-MM-DD HH:MM CET" on active tracking cards.

10. **[frontend] Extend session TTL or add auto-refresh** (ISSUE-004): A 30-minute session is too short for collection monitoring workflows.

### Priority 3: Quality-of-life improvements

11. **[frontend] Combined actor + presence creation from URL** (ISSUE-006): Accept platform URLs (e.g., `https://bsky.app/profile/user`) and auto-parse them into Actor + Presence records.

12. **[core] Add YouTube language post-filter** (data quality): Since `relevanceLanguage=da` is only a hint, add a client-side language detection step and optionally filter out non-Danish results.

13. **[frontend] Make date range warnings more prominent** (ISSUE-005): Display the warning visually in the collection launcher UI before submission, not just in the JSON response.

14. **[frontend] Show live tracking on designs with failed runs** (ISSUE-009): Allow designs with any collection history (including failed runs with data) to appear in the live tracking "Available" section.

15. **[core] Stabilize record count during collection** (ISSUE-008): Ensure `records_collected` reflects the actual count consistently, both during and after the collection run.

---

## 6. Arena Status Summary

### Collection Run 1 (3a1a51c0) -- Cancelled after ~20 min

| Arena | Status | Records | Notes |
|-------|--------|---------|-------|
| bluesky | Data collected | 12 | Danish lang:da filter working |
| common_crawl | No data | 0 | |
| discord | Failed | 0 | Needs explicit channel_ids |
| facebook | Data collected | 33 | Actor-based collection |
| gab | Failed | 0 | No credential (expected) |
| gdelt | Failed | 0 | ReadTimeout on API |
| google_autocomplete | Stuck/Running | 0 | Hung for >20 min |
| google_search | Data collected | 624 | Danish locale working |
| instagram | Data collected | 21 | Actor-based collection |
| openrouter | Failed | 0 | Dispatch failure |
| reddit | Data collected | 173 | Danish subreddits |
| ritzau_via | Data collected | 49 | Danish news wire |
| rss_feeds | No data | 0 | No Iran content in recent feeds |
| telegram | No data | 0 | Channels may not have Iran content |
| threads | No data | 0 | No credential |
| tiktok | Data collected | 147 | |
| wayback | Failed | 0 | Request error |
| wikipedia | Data collected | 500 | |
| x_twitter | Stuck/Running | 0 | Hung for >20 min |
| youtube | Data collected | 686 | Mixed languages |

**Total:** 2245 records (before cancellation count adjustment to 12245)

### Collection Run 2 (5d8cb47e) -- Cancelled after ~10 min

| Arena | Records | Notes |
|-------|---------|-------|
| google_search | 706 | Slight increase vs. run 1 |
| gdelt | 20 | Succeeded this time |
| All others | 0 or stuck | Same pattern as run 1 |

**Total:** 726 records

---

## 7. Appendix: Test Environment

- **OS:** macOS Darwin 24.6.0
- **Python:** 3.12+
- **Database:** PostgreSQL (clean, freshly migrated)
- **Redis:** Running
- **Celery:** Running with worker and beat
- **Application:** FastAPI at localhost:8000

### IDs Created During Testing

- **Project:** fd23f7b6-125b-427e-92ec-c1a03464c2e9 ("Iran Discourse Study")
- **Query Design:** f9dc2e66-246a-4e4f-82f6-976d92d0f3a0 ("Iran Discourse")
- **Collection Run 1:** 3a1a51c0-6087-4fc1-b965-82b84899278c (batch, cancelled)
- **Collection Run 2:** 5d8cb47e-a57f-41e7-b5e4-e5f6fbe0539d (batch, cancelled)
- **Live Tracking Run:** 7f7201c9-... (live, status pending/active)
- **Backfill Run:** fe4417ba-... (batch, running)

### Search Terms Added

Default: Iran, Tehran, iransk, Khamenei, JCPOA, iranere, Teheran, iranske
Override (rss_feeds): Iran politik
Override (bluesky): #Iran

### Actors Added (12 original + 10 from snowball)

Original: Enhedslisten, Facebook Page 57497067718, Facebook Page 520449347983427, Denmark Subreddit, Velinformeret, Flemming Blicher, MBrgger, Pelle Dragsted, Socialdemokratiet, DR Nyheder, TV2 Echo, SF Politik

Snowball-discovered: Nicolai Wammen, Birgitte Vind, Pernille Rosenkrantz-Theil, Simon Kollerup, Jens Joel, Morten Boedskov, Magnus Heunicke, Anne Paulin, Benny Engelbrecht, Maria Durhuus
