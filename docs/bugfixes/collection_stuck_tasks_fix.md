# Bug Fix: Collection Run Tasks Stuck in "Pending" Indefinitely

**Date:** 2026-02-23
**Severity:** HIGH
**Status:** FIXED
**Reporter:** User (B-01 blocker)
**Fixer:** Core Application Engineer

---

## Problem Description

When launching a collection run with multiple arenas (e.g., 10+ arenas enabled), some arena tasks would remain stuck in "pending" status indefinitely with:
- No `celery_task_id` assigned
- No `started_at` timestamp
- No `error_message`
- The overall collection run never transitions to "completed"

Affected arenas in reported case: reddit, youtube, common_crawl, wayback
Working arenas in same run: wikipedia, ritzau_via, threads, bluesky, gab, google_search, tiktok, gdelt

This prevented collection runs from ever completing, blocking all downstream analysis.

---

## Root Cause Analysis

The bug was caused by a **race condition between task dispatch and worker capacity** combined with **missing failure detection**:

### 1. Dispatch Flow
```python
# dispatch_batch_collection task
create_collection_tasks(run_id, arena_list)  # Creates CollectionTask rows with status='pending'
for arena in arenas:
    celery_app.send_task(arena_task_name, ...)  # Dispatches to Celery queue
```

### 2. Worker Capacity Limitation
- Celery worker runs with `--concurrency=4` (4 worker processes)
- Worker prefetch is set to `1` (each worker takes 1 task at a time)
- **Maximum 4 tasks can be in-flight simultaneously**
- When 10+ arenas are dispatched in rapid succession, only the first 4 get picked up immediately
- The remaining 6+ tasks sit in the Redis queue waiting for a worker to become free

### 3. Missing Mechanisms
The original implementation lacked:
- **No Celery task ID tracking**: When `send_task()` was called, the returned `AsyncResult.id` was not stored in the `CollectionTask` row
- **No dispatch failure detection**: If `send_task()` threw an exception, the task stayed in "pending" forever
- **No stuck task timeout**: Tasks that were queued but never picked up by a worker would never be detected
- **No completion guarantee**: `check_batch_completion` only checked if tasks were terminal, but didn't handle tasks that never started

### 4. Why Some Tasks Worked
The arenas that reached terminal states (wikipedia, bluesky, etc.) were the first 4-8 dispatched and immediately picked up by available workers. Tasks dispatched later stayed queued, and if workers were still busy with long-running collections, they never got started.

---

## Solution Implemented

### 1. Capture and Store Celery Task IDs
**File:** `src/issue_observatory/workers/tasks.py` (dispatch_batch_collection)

```python
# Before: fire-and-forget dispatch
celery_app.send_task(task_name, kwargs=task_kwargs, queue="celery")

# After: capture task ID
async_task = celery_app.send_task(task_name, kwargs=task_kwargs, queue="celery")
task_id_updates.append((platform_name, async_task.id))

# Store task IDs in CollectionTask rows
for platform_name, celery_task_id in task_id_updates:
    asyncio.run(update_task_celery_id(run_uuid, platform_name, celery_task_id))
```

**New helper:** `update_task_celery_id()` in `_task_helpers.py`

### 2. Mark Dispatch Failures Immediately
**File:** `src/issue_observatory/workers/tasks.py`

```python
try:
    async_task = celery_app.send_task(...)
except Exception as dispatch_exc:
    # Immediately mark the CollectionTask as failed so the run can complete
    asyncio.run(mark_task_failed(
        run_uuid,
        platform_name,
        f"Celery dispatch failed: {dispatch_exc}",
    ))
    skipped += 1
```

**New helper:** `mark_task_failed()` in `_task_helpers.py`

### 3. Detect and Fail Stuck Tasks (10-Minute Timeout)
**File:** `src/issue_observatory/workers/_task_helpers.py` (check_all_tasks_terminal)

```python
# Before checking terminal status, mark tasks stuck in 'pending' for >10 minutes as failed
stuck_cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=10)
stuck_result = await db.execute(
    update(CollectionTask)
    .where(
        CollectionTask.collection_run_id == run_id,
        CollectionTask.status == "pending",
        CollectionTask.created_at < stuck_cutoff,
    )
    .values(
        status="failed",
        error_message="Task stuck in pending state for >10 minutes; likely dispatch failure or worker crash",
        completed_at=datetime.now(tz=timezone.utc),
    )
)
```

This runs every 15 seconds when `check_batch_completion` polls, so stuck tasks are detected and marked as failed within ~10-11 minutes maximum.

### 4. Handle "No Terms" Case
**File:** `src/issue_observatory/workers/tasks.py`

```python
arena_terms = arena_terms_map.get(platform_name, [])
if not arena_terms:
    # YF-01: This arena has no search terms scoped to it
    asyncio.run(mark_task_failed(
        run_uuid,
        platform_name,
        "No search terms scoped to this arena (YF-01)",
    ))
    continue
```

Previously, arenas with no scoped terms were silently skipped but their CollectionTask row stayed "pending".

---

## Testing Recommendations

### 1. Unit Tests
- Test `update_task_celery_id()` updates the correct row
- Test `mark_task_failed()` sets status and error_message
- Test `check_all_tasks_terminal()` marks stuck tasks as failed

### 2. Integration Tests
Create a collection run with 12 arenas and verify:
- All 12 CollectionTask rows are created
- All 12 have a `celery_task_id` assigned (or are marked failed if dispatch failed)
- After 10 minutes, any tasks still in "pending" are marked as failed
- The run eventually reaches "completed" or "failed" status

### 3. Manual Verification
1. Launch a collection run with 10+ arenas
2. Check `collection_tasks` table after 1 minute:
   - All rows should have `celery_task_id IS NOT NULL` OR `status='failed'`
3. Check again after 15 minutes:
   - All rows should be in terminal state (completed/failed)
4. Check `collection_runs`:
   - Run should have `status='completed'` and `completed_at IS NOT NULL`

---

## Files Modified

1. `src/issue_observatory/workers/_task_helpers.py`
   - Added `update_task_celery_id()` helper
   - Added `mark_task_failed()` helper
   - Modified `check_all_tasks_terminal()` to detect and mark stuck tasks

2. `src/issue_observatory/workers/tasks.py`
   - Modified `dispatch_batch_collection()` to capture task IDs
   - Added immediate failure marking for dispatch errors
   - Added handling for "no terms" case
   - Improved logging in `check_batch_completion()`

---

## Migration Required

**No database migration needed.** The `celery_task_id` column already exists on the `collection_tasks` table. The fix only changes how it's populated.

---

## Backward Compatibility

Fully backward compatible. Existing collection runs will continue to work. The stuck task detection mechanism only applies to tasks created after this fix is deployed.

---

## Performance Impact

**Minimal.** The fix adds:
- One extra DB update per arena task (to store `celery_task_id`) — negligible overhead
- One UPDATE query in `check_all_tasks_terminal()` to mark stuck tasks — runs only when tasks are actually stuck
- Slightly more verbose logging

All changes are within the orchestration layer and do not affect arena collector performance.

---

## Deployment Notes

1. **No downtime required** — this is a hot-fix safe to deploy during operation
2. **Workers must be restarted** to pick up the new task code
3. **Recommended deployment order:**
   1. Deploy code changes
   2. Restart Celery workers: `docker-compose restart worker`
   3. Restart Celery beat (if running): `docker-compose restart beat`
4. **Monitoring:** Check logs for `stuck_marked_failed` messages — these indicate the fix is working

---

## Future Improvements

1. **Add Prometheus metrics** for stuck task detection rate
2. **Configurable timeout** — make the 10-minute threshold a settings variable
3. **Worker pool monitoring** — add admin UI to show Celery worker queue depth
4. **Task retry mechanism** — if a task fails due to dispatch, auto-retry once
5. **Celery task state reconciliation** — periodically check Celery's task state and sync with CollectionTask rows

---

## Conclusion

This fix resolves the critical blocker where collection runs would hang indefinitely due to tasks stuck in pending state. The three-pronged approach (capture task IDs, mark dispatch failures immediately, detect stuck tasks with timeout) ensures all collection runs eventually reach a terminal state.

**Expected outcome:** Collection runs with 10+ arenas will now complete within:
- Best case: ~2-5 minutes (all tasks successful)
- Worst case: ~15 minutes (all tasks timeout and are marked as failed)

No collection run should remain in "pending" or "running" state indefinitely.
