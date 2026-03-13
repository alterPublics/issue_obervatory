# Collection Run Report — 2026-03-05

**Run ID:** `a0ebe9ce-3137-4e8e-8688-f7ba50a2fd93`
**Project:** valg2026
**Query Design:** Udenrigspolitik og forsvar
**Tier:** premium | **Mode:** batch
**Date Range:** 2026-02-28 → 2026-03-05

## Status Summary

| Arena | Status | Records | Dupes Skipped | Notes |
|-------|--------|---------|---------------|-------|
| google_search | Completed | 2,322 | 0 | |
| telegram | Completed | 781 | 0 | |
| reddit | Completed | 814 | 0 | |
| google_autocomplete | Completed | 630 | 0 | |
| wikipedia | Completed | 334 | 0 | |
| ritzau_via | Completed | 283 | 0 | |
| rss_feeds | Completed | 0 | 21 | All dupes (already collected) |
| url_scraper | Completed | 0 | 0 | |
| x_twitter | Running | 0 | 0 | Still in progress |
| bluesky | Running | 0 | 0 | Still in progress |
| domain_crawler | Running | 0 | 0 | Still in progress |
| instagram | Running | 0 | 0 | Still in progress |
| common_crawl | **Failed** | 0 | 0 | Server disconnected |
| discord | **Failed** | 0 | 0 | Config error — missing channel_ids |
| facebook | **Failed** | 0 | 0 | Bright Data trigger HTTP 400 |
| gdelt | **Failed** | 0 | 0 | Rate limit 429 |
| openrouter | **Failed** | 0 | 0 | Task dispatch failure |
| tiktok | **Failed** | 0 | 0 | Research API HTTP 500 |
| youtube | **Failed** | 0 | 0 | Quota exceeded |

**Completed:** 8 arenas (5,164 records)
**Running:** 4 arenas
**Failed:** 7 arenas

---

## Failure Analysis

### 1. GDELT — Rate limit (HTTP 429)
- **Error:** `gdelt: HTTP 429 for term='grønland' — Please limit requests to one every 5 seconds`
- **Category:** Rate limiting
- **Cause:** Likely the duplicate run hammered GDELT with parallel requests from both runs, exceeding the 1-request-per-5-seconds limit.
- **Fix:** The GDELT collector should enforce stricter rate limiting (5s minimum between requests). Consider adding a per-arena global rate limiter in Redis rather than per-task.
- **Severity:** Medium — data recoverable by re-running after cooldown.

### 2. YouTube — Quota exhausted
- **Error:** `youtube: quota exceeded on endpoint 'videos'`
- **Category:** Quota / billing
- **Cause:** YouTube Data API v3 has a daily quota (default 10,000 units). The duplicate run may have consumed the remaining quota.
- **Fix:** Credit estimation should account for YouTube quota limits. Consider checking remaining quota before dispatching. Quota resets at midnight Pacific Time.
- **Severity:** High — blocks YouTube collection for the rest of the day.

### 3. Facebook — Bright Data HTTP 400 (ROOT CAUSE FOUND)
- **Error:** `facebook: Bright Data trigger HTTP 400`
- **Category:** Code bug — missing URL normalization
- **Root cause:** The `custom_pages` list in the query design stores **plain Facebook usernames** (e.g. `"socialdemokratiet"`, `"radikalevenstre"`), but `FacebookCollector.collect_by_actors()` passes them directly to Bright Data in the `"url"` field without converting to full URLs. Bright Data expects `https://www.facebook.com/socialdemokratiet` but received just `"socialdemokratiet"`, resulting in HTTP 400 Bad Request.
- **Contrast:** The Instagram collector has `_normalize_profile_url()` which prepends `https://www.instagram.com/` for plain usernames. Facebook's collector lacks this normalization.
- **Fix:** Add `_normalize_facebook_url()` in `arenas/facebook/collector.py` (see below). Apply it in `_collect_brightdata_actors()` before building the payload.
- **Code location:** `src/issue_observatory/arenas/facebook/collector.py:377` — the `url` field needs normalization.
- **Severity:** **Critical** — Facebook collection is completely broken until fixed.

### 4. TikTok — Research API HTTP 500
- **Error:** `tiktok: HTTP 500 from Research API`
- **Category:** Upstream API error
- **Cause:** TikTok's Research API returned a server error. Could be transient or indicate an API issue on their side.
- **Action needed:** Retry later. If persistent, check TikTok Research API status page.
- **Severity:** Medium — likely transient.

### 5. Discord — Missing channel_ids (config error)
- **Error:** `Discord requires explicit channel_ids — there is no global keyword search for bot accounts.`
- **Category:** Configuration
- **Cause:** Discord was enabled in the arena config but no `channel_ids` were specified. Discord bots cannot do global keyword search — they need explicit channel snowflake IDs.
- **Fix:** The launcher should either: (a) not include Discord unless channel_ids are configured in the query design's arenas_config, or (b) skip Discord gracefully with a warning instead of failing.
- **Severity:** Low — expected behavior, but poor UX. Should be a warning, not a failure.

### 6. Common Crawl — Server disconnected
- **Error:** `Server disconnected without sending a response.`
- **Category:** Network / upstream
- **Cause:** Common Crawl's CDX API dropped the connection. Could be timeout, server overload, or network issue.
- **Action needed:** Retry. Add connection retry logic with exponential backoff if not present.
- **Severity:** Low — transient.

### 7. OpenRouter / AI Chat Search — Task dispatch failure (ROOT CAUSE FOUND)
- **Error:** `Task stuck in pending state for >2 minutes; likely dispatch failure, import error, or missing dependency`
- **Category:** Task registration / naming mismatch
- **Root cause:** The arena is registered as `platform_name="openrouter"` in the registry. The dispatcher resolves the task module via `get_task_module("openrouter")` which maps to `issue_observatory.arenas.ai_chat_search.tasks`. The task name sent is `issue_observatory.arenas.ai_chat_search.tasks.collect_by_terms`, which IS correctly registered. However, the ai_chat_search task is **not being picked up by the Celery worker**, likely because the task module is not imported during worker startup (the `celery_app` autodiscovery may miss it due to the nested module structure). The Celery worker registered tasks list shows NO ai_chat_search tasks.
- **Fix:** Ensure `ai_chat_search.tasks` is imported during Celery worker startup. Add it to the `include` list in the Celery app configuration.
- **Severity:** High — AI chat search arena is non-functional.

### 8. Instagram — Collection timed out (ROOT CAUSE FOUND)
- **Error:** `Collection timed out` after 24 min 59 sec
- **Category:** Architecture / scalability
- **Root cause:** The Instagram collector iterates over each actor **one-by-one** (`collector.py:245-258`), triggering a separate Bright Data snapshot per profile. With ~200+ actors in the list, each snapshot requires a trigger + polling cycle (~30s intervals × up to 40 attempts = potentially 20 min per actor). The `soft_time_limit=1500` (25 min) kills the task before it can process more than a few actors.
- **Contrast:** Facebook batches all URLs into a single trigger grouped by dataset type (`collector.py:253`). Instagram should do the same.
- **Fix options:**
  1. **Batch profiles into a single Bright Data trigger** (preferred — matches Facebook's approach)
  2. Split the actor list into chunks and dispatch sub-tasks (more complex)
  3. Increase time limit (bandaid — doesn't solve the N sequential API calls problem)
- **Code location:** `src/issue_observatory/arenas/instagram/collector.py:245-258`
- **Severity:** **Critical** — Instagram collection will always fail with a large actor list.

### 9. Telegram — Collection timed out
- **Error:** `Collection timed out after 10 minutes`
- **Category:** Time limit too short
- **Root cause:** Telegram's `soft_time_limit` is set to 600s (10 min). With a large number of channel searches, this is insufficient.
- **Severity:** Medium — increase the time limit for Telegram tasks.

---

## Systemic Issues Identified

### Issue 1: Duplicate Collection Runs (CRITICAL)
Both runs (`a0ebe9ce` and `9f09bb84`) were launched for the same query design simultaneously. No server-side deduplication guard exists. See `docs/issues/duplicate_collection_runs.md`.

### Issue 2: DB Connection Pool Exhaustion
During monitoring, `psycopg2.OperationalError: too many clients already` was observed. The duplicate runs likely consumed double the expected connections. PostgreSQL `max_connections` may need tuning, or the application connection pool needs proper limits.

### Issue 3: Cancellation Does Not Propagate to Celery Tasks (CRITICAL)
When a run is cancelled via the UI, the `cancel_collection_run()` endpoint sets the run status to `cancelled` in the DB but **does not revoke the Celery tasks**. The `celery_task_id` field on `collection_tasks` is `None` for all tasks, so there's nothing to revoke by ID. Additionally, the arena task code (`persist_collected_records`, collector loops) never checks if the parent run has been cancelled — tasks keep collecting and inserting records indefinitely.

**Impact during this run:** 3 zombie tasks (domain_crawler, instagram, x_twitter) continued running for the cancelled run, inserting 10,403 records that shouldn't exist, wasting API credits, and competing for DB connections.

**Fix required:**
1. Store `celery_task_id` on `CollectionTask` rows when dispatching
2. Revoke all active Celery tasks in the cancel endpoint
3. Add a periodic cancellation check in long-running collectors (e.g., check run status every N batches)

### Issue 4: Arenas enabled without required config
Discord and OpenRouter were included in the collection despite not being properly configured. The launcher should validate arena prerequisites before dispatch.

---

## Recommendations

1. **Immediate:** Add `_normalize_facebook_url()` to Facebook collector — collection is fully broken without this
2. **Immediate:** Batch Instagram profiles into single Bright Data trigger instead of N sequential calls
3. **Immediate:** Implement duplicate run guard (see `docs/issues/duplicate_collection_runs.md`)
4. **Immediate:** Fix cancellation propagation — store celery_task_id and revoke on cancel
5. **Short-term:** Register ai_chat_search tasks with Celery worker (add to `include` list)
6. **Short-term:** Increase Telegram task time limit (currently 10 min, needs ~25 min for large collections)
7. **Short-term:** Add arena prerequisite validation at launch time (Discord needs channel_ids, etc.)
8. **Short-term:** Add retry logic with backoff for transient failures (Common Crawl, TikTok)
9. **Short-term:** Enforce GDELT rate limiting at 5s intervals
10. **Medium-term:** Add YouTube quota pre-check before dispatch
11. **Medium-term:** Review PostgreSQL max_connections and connection pooling config
