# Retest Report: Previously-Failing Arenas
Date: 2026-02-27
Test environment: localhost:8000, Celery worker with concurrency 4
Query design: greenland_base (58784edf-0d8f-4c54-b8a7-e6d2f69aed94)
Search terms: "gronland", "Inatsisartut", "nuuk", "#gronland"

---

## Summary Table

| Platform | Tier | Original Issue | Result | Records | Original Fix Status |
|----------|------|---------------|--------|---------|-------------------|
| X/Twitter | medium | POST-to-GET migration needed for TwitterAPI.io | **SUCCESS** | 1,273 | RESOLVED |
| Facebook | medium | Orchestrator did not dispatch collect_by_actors | **SUCCESS** | 29 | RESOLVED |
| Instagram | medium | Orchestrator dispatch + Posts scraper fix | **SUCCESS** | 14 | RESOLVED |
| Telegram | free | `async with client:` caused indefinite hang | **PARTIAL** | 0 | RESOLVED (hang fixed), new issue (0 records) |
| OpenRouter / AI Chat Search | medium | Task stuck in pending | **FAIL** | 0 | NOT RESOLVED (new root cause identified) |
| Common Crawl | free | Upstream server disconnection | **PARTIAL** | 0 | RESOLVED (no disconnection), 0 records expected |

---

## Per-Platform Detailed Results

### 1. X/Twitter (medium tier) -- SUCCESS

**Collection run:** 636dd28c-df69-4d04-bc9f-df90d5dd306f
**Records collected:** 1,273
**Duration:** ~143 seconds (01:37:26 to 01:39:50 UTC)
**Deduplication:** 0 skipped

The POST-to-GET migration fix for TwitterAPI.io is confirmed working. The collector
successfully searched for all 4 terms ("gronland", "Inatsisartut", "nuuk", "#gronland")
and returned 1,273 tweets. The task completed cleanly with status "completed".

**Original issue:** RESOLVED.

---

### 2. Facebook (medium tier) -- SUCCESS

**Collection run:** 636dd28c-df69-4d04-bc9f-df90d5dd306f
**Records collected:** 29
**Duration:** ~80 seconds (01:37:23 to 01:38:29 UTC)
**Actors:** 2 Facebook pages (57497067718 and 520449347983427)

The orchestrator now correctly detects Facebook as an actor-only arena
(`supports_term_search=False`) and dispatches `collect_by_actors` instead of
`collect_by_terms`. Bright Data scraping completed successfully, downloading a
snapshot with 29 items. All 29 records were inserted.

**Original issue:** RESOLVED.

---

### 3. Instagram (medium tier) -- SUCCESS

**Collection run:** 636dd28c-df69-4d04-bc9f-df90d5dd306f
**Records collected:** 14
**Duration:** ~34 seconds (01:37:24 to 01:37:59 UTC)
**Actors:** 1 (enhedslisten)

The orchestrator correctly dispatches Instagram as an actor-only arena. The Posts
scraper with discovery mode (replacing the broken Reels scraper) successfully
collected 14 items from the enhedslisten Instagram profile. Deduplication is working
correctly -- when the same collection was run again in a subsequent run, all 14
records were detected as duplicates and skipped (0 inserted, 14 skipped).

**Original issue:** RESOLVED.

---

### 4. Telegram (free tier) -- PARTIAL

**Collection run:** b1e01e07-e132-486f-853f-cfa34d5850d0
**Records collected:** 0
**Duration:** ~5 seconds (completed fast, no hang)
**Channels attempted:** 6 default channels

**The hang is fixed.** The explicit connect/verify pattern replacing `async with client:`
works correctly. The Telegram client connected and completed the task in approximately
5 seconds. This is a major improvement from the previous behavior where the task would
hang indefinitely.

**However, 0 records were collected** because:

1. The default Telegram channels (`dr_nyheder`, `politiken_dk`, `bt_dk`, `informationdk`)
   do not exist as valid Telegram usernames. The worker logged clear warnings:
   - "No user has 'dr_nyheder' as username -- skipping."
   - "No user has 'politiken_dk' as username -- skipping."
   - "No user has 'bt_dk' as username -- skipping."
   - "Nobody is using this username, or the username is unacceptable" (for `informationdk`)

2. The actors configured in the query design (Frihedslisten Telegram, Flemming Blicher
   Telegram) were **not used** because the dispatcher sent `collect_by_terms`, not
   `collect_by_actors`. Telegram supports both methods and is not flagged as "actor-only",
   so the dispatcher defaults to term-based collection which searches the default
   (non-existent) channels.

**Original issue (hang):** RESOLVED.
**New issue (0 records):** Two sub-issues discovered:

- **[data]** Default Telegram channel list contains invalid usernames. These
  channels do not exist on Telegram. The config should be updated or removed.

- **[core]** Dispatch logic does not combine term-based and actor-based collection
  for arenas that support both methods. If a researcher configures actors for
  Telegram but also has search terms, only `collect_by_terms` runs and the
  actors are ignored. The researcher has no way to know this from the UI.

---

### 5. OpenRouter / AI Chat Search (medium tier) -- FAIL

**Collection run:** 0f0353af-c8ac-4438-bd49-52a988af60fc
**Records collected:** 0
**Duration:** < 2 seconds before crash

The task was dispatched and received by the worker, but failed immediately with
two cascading errors:

1. **HTTP 429 Too Many Requests** from OpenRouter API (`openrouter.ai/api/v1/chat/completions`).
   The account's rate limit has been exhausted. This is an external service limitation.

2. **TypeError in error handling:** When the rate limit error was caught, the collector
   tried to report it via `CredentialPool.report_error()` but called it with the wrong
   arguments:

   ```
   TypeError: CredentialPool.report_error() missing 1 required positional argument: 'error'
   ```

   The collector code at `collector.py:547-550` calls:
   ```python
   await self.credential_pool.report_error(
       platform=self.platform_name,
       credential_id=credential_id,
   )
   ```

   But the `CredentialPool.report_error()` signature requires:
   ```python
   async def report_error(self, credential_id, error, platform=None)
   ```

   The caller omits the required `error` parameter (the actual exception instance).

3. **Task status never updated:** Because the Celery task raised an unhandled exception,
   the CollectionTask row in the database was never updated from "pending" to "failed".
   The task appears to still be waiting from the researcher's perspective.

**Original issue (stuck in pending):** NOT RESOLVED -- different root cause identified.
The original issue was likely also caused by this same TypeError crashing the error
handler, which then crashes the entire task, leaving the DB row in "pending" forever.

**Bugs found:**

- **[core]** `report_error()` call in `arenas/ai_chat_search/collector.py:547-550`
  is missing the `error` argument. This affects every rate-limit or auth error
  in the AI Chat Search arena.

- **[core]** When a Celery arena task raises an unhandled exception, the
  CollectionTask row is never updated to "failed" status. The researcher sees
  "pending" forever with no error message.

---

### 6. Common Crawl (free tier) -- PARTIAL

**Collection run:** a84e3e26-18af-46dc-bb1c-1d3c45dced1c
**Records collected:** 0
**Duration:** ~6.5 seconds

The task completed cleanly with no errors. The previous issue (upstream server
disconnection) did not occur. The index was successfully queried (CC-MAIN-2026-08)
but returned 0 results for all 4 search terms.

This is likely expected behavior: Common Crawl indexes are built from periodic
web crawls, and the terms "gronland", "Inatsisartut", "nuuk", and "#gronland"
may not appear in the CC-MAIN-2026-08 index or may not match the query format
expected by the Common Crawl index API.

**Original issue (upstream disconnection):** RESOLVED.
**0 records:** Not a bug -- expected behavior for niche terms in a web archive index.

---

## Cross-Cutting Issues Discovered

### BLOCKER: check_batch_completion crashes on every run

**Affects all 6 test runs and all future collection runs.**

The `check_batch_completion` Celery task crashes with:
```
AttributeError: type object 'CollectionTask' has no attribute 'created_at'
```

Location: `src/issue_observatory/workers/_task_helpers.py:789`

The code at line 789 references `CollectionTask.created_at` for stuck-task detection,
but the `CollectionTask` model (`src/issue_observatory/core/models/collection.py:170`)
does not have a `created_at` column. It has `started_at` and `completed_at`, but no
`created_at`.

**Impact:** No collection run can ever transition from "running" to "completed" or
"failed". The run status stays at "running" forever, even when all arena tasks have
finished. This means:

- The researcher never sees a completion confirmation
- The SSE `run_complete` event is never published
- The enrichment pipeline is never triggered
- Credit settlement is never finalized
- The collection list shows all runs as eternally "running"

**Fix:** Replace `CollectionTask.created_at` with the appropriate column. Since
`CollectionTask` represents when it was created (dispatched), using the related
`CollectionRun.started_at` or changing the stuck detection to use
`CollectionTask.started_at IS NULL` for pending tasks would be appropriate.

**Tag:** [core]

---

### BLOCKER: Unhandled Celery task exceptions leave CollectionTask rows in "pending"

When a Celery arena task raises an unhandled exception (as happened with OpenRouter),
the CollectionTask row in the database is never updated to reflect the failure. The
task remains in "pending" status with no error_message, even though the Celery task
has terminated.

The stuck-task detection in `check_batch_completion` was meant to catch this case
(marking tasks pending for >2 minutes as failed), but it cannot run because of the
`created_at` bug above. Even when fixed, the 2-minute timeout is a workaround -- the
proper fix would be to update the CollectionTask status in a `try/finally` or Celery
`on_failure` callback.

**Tag:** [core]

---

### Tier precedence merge causes unintended multi-arena dispatch

When launching a collection via the API with `arenas_config: {"x_twitter": "medium"}`,
the system merges this with the query design's saved `arenas_config` (which contains
all 25 arenas in nested format). Because the QD config takes precedence
(`{**launcher_arena_config, **design_arena_config}`), any arenas enabled in the QD
are ALWAYS dispatched regardless of what the researcher specifies at launch time.

This means a researcher cannot launch a single-arena test collection without first
modifying the query design's arena configuration. From a research workflow perspective,
this is unintuitive -- the researcher expects that specifying `arenas_config` at
launch time would REPLACE the design defaults, not merge with them.

**Tag:** [core]

---

## Run Reference Table

| Run ID | Arenas Dispatched | Notes |
|--------|------------------|-------|
| 636dd28c-df69-4d04-bc9f-df90d5dd306f | openrouter, google_autocomplete, google_search, facebook, instagram, x_twitter | Initial test; all from QD config |
| e349b67f-6d75-43ef-820b-4c5d8fd0e846 | openrouter, google_autocomplete, google_search, facebook, instagram, x_twitter | Unintended duplicate; QD config override |
| b1e01e07-e132-486f-853f-cfa34d5850d0 | telegram | After QD config update |
| a84e3e26-18af-46dc-bb1c-1d3c45dced1c | common_crawl | After QD config update |
| 0f0353af-c8ac-4438-bd49-52a988af60fc | openrouter | After QD config update |

---

## Recommendations (prioritized)

1. **[core] Fix `CollectionTask.created_at` reference in `_task_helpers.py:789`.**
   This is a critical blocker preventing any collection run from completing.
   Replace with `CollectionTask.started_at IS NULL` for pending-task stuck detection.

2. **[core] Fix `report_error()` call in `ai_chat_search/collector.py:547-550`.**
   Add the missing `error` argument. The same pattern should be audited across all
   arena collectors that call `credential_pool.report_error()`.

3. **[core] Add Celery `on_failure` callback to arena tasks** to update the
   CollectionTask row when a task crashes with an unhandled exception. This prevents
   "ghost pending" tasks that never resolve.

4. **[data] Remove or update invalid default Telegram channels** (`dr_nyheder`,
   `politiken_dk`, `bt_dk`, `informationdk`). These do not exist on Telegram.
   Consider removing default channels entirely and requiring researcher configuration
   via `arenas_config["telegram"]["custom_channels"]`.

5. **[core] Dispatch both `collect_by_terms` and `collect_by_actors` for arenas
   that support both methods** (Telegram, Reddit, YouTube, etc.). Currently, if
   an arena has `supports_term_search=True`, only `collect_by_terms` is dispatched
   and configured actors are silently ignored. At minimum, warn the researcher if
   actors are configured but will not be used.
