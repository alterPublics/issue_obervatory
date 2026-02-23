# Data Quality Finding: Collection Tasks Permanently Stuck in "Pending"

**Date**: 2026-02-23
**Severity**: CRITICAL
**Arenas affected**: reddit, youtube, common_crawl, wayback
**Responsible agent**: [core]

## Observation

When a batch collection is launched with 9 free-tier arenas enabled, tasks for reddit, youtube, common_crawl, and wayback are created in the database with status "pending" but never transition to "running." The tasks remain in "pending" indefinitely, preventing the parent collection run from ever reaching "completed" status.

## Evidence

### Timeline of collection run da8b3d65-2c0b-4981-bdf5-4fc4b381b181

| Arena | Status at T+30s | Status at T+90s | Status at T+5min | Status at T+8min |
|-------|-----------------|-----------------|-------------------|-------------------|
| ritzau_via | completed (80 records) | completed | completed | completed |
| bluesky | failed | failed | failed | failed |
| gab | failed | failed | failed | failed |
| rss_feeds | running | completed (0) | completed | completed |
| gdelt | running | failed | failed | failed |
| reddit | **pending** | **pending** | **pending** | **pending** |
| youtube | **pending** | **pending** | **pending** | **pending** |
| common_crawl | **pending** | **pending** | **pending** | **pending** |
| wayback | **pending** | **pending** | **pending** | **pending** |

### Historical pattern (from collections list)

Multiple runs from previous testing sessions (2026-02-22) show the same pattern:
- Run 5a3f9d0e: status "running" since 18:52 yesterday (8+ hours ago), 620 records but still "running"
- Run 5a9b7792: status "running" since 18:36 yesterday, 0 records
- Runs e4a33162, ca6d4006, c037582a, 858880c7, 27d9d3ab: All marked as failed by `stale_run_cleanup` with error "exceeded 24h without completion"

This is a systemic issue, not a one-time failure.

## Probable cause

The Celery task dispatch mechanism (`dispatch_batch_collection`) creates CollectionTask rows in the database and then dispatches corresponding Celery tasks. For the stuck arenas, either:

1. The Celery tasks are dispatched but never received by workers (queue routing issue)
2. The Celery tasks fail silently during dispatch (error swallowed in the try/except block in the collections route)
3. There is a concurrency bottleneck -- the 5 non-stuck tasks saturate the 4 Celery workers, and the remaining tasks are queued but never dequeued

The dispatch_batch_collection code has a `try/except` block with the comment "Non-fatal: the run is created; the stale_run_cleanup task will eventually mark it as failed" -- this suggests that silent dispatch failures are a known possibility but treated as acceptable.

## Research impact

This failure pattern means:
1. A researcher can never get a complete multi-arena collection
2. Collection runs appear to be "running" forever with no error messages
3. The researcher has no way to distinguish "still working" from "permanently stuck"
4. Analysis on partial data produces misleading results because the researcher does not know which arenas contributed data

## Recommended fix

1. Add a per-task timeout: if a task remains in "pending" for more than 5 minutes, mark it as "failed" with error "Task dispatch timed out -- Celery may not have received the task"
2. Add a per-run completion check: if all tasks are in terminal states (completed/failed), transition the run to "completed" (even if some tasks failed)
3. Log the actual Celery task dispatch result (task ID) on the CollectionTask row so it can be debugged
4. Consider running arena tasks concurrently rather than sequentially -- the current pattern appears to serialize task execution

## Reproduction steps

1. Create a query design with any search terms
2. Enable reddit, youtube, common_crawl, and wayback arenas at FREE tier
3. Launch a batch collection
4. Monitor the collection run status via GET /collections/{run_id} with Accept: application/json
5. Observe that reddit, youtube, common_crawl, and wayback remain in "pending" status indefinitely
6. Wait 10+ minutes -- the tasks never start
