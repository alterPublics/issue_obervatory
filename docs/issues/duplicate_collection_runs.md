# BUG: Duplicate Collection Runs Launched for Same Query Design

**Severity:** Critical
**Discovered:** 2026-03-05
**Status:** Open

## Summary

Two identical collection runs were launched simultaneously for the same query design, wasting resources and creating duplicate data. No server-side guard prevents this.

## Incident

- **Project:** valg2026
- **Query Design:** "Udenrigspolitik og forsvar" (`9e2d6ea2`)
- **Run A** (`a0ebe9ce`): kept — collected ~6,000+ records
- **Run B** (`9f09bb84`): cancelled manually — had collected ~4,200 records before cancellation
- Both runs started at the same second (18:50:27 UTC), suggesting a double-submit from the launcher UI

## Root Cause

There is **no server-side check** in `create_collection_run()` or `create_project_collection()` to prevent launching a new run when a `pending` or `running` run already exists for the same query design.

The frontend launcher (`collections/launcher.html`) has an Alpine.js `launching` flag that disables the button after click, but this is a client-side-only guard — it doesn't survive page refreshes, browser back-button, or multiple tabs.

### Affected code

- `src/issue_observatory/api/routes/collections.py:400` — `create_collection_run()`: no duplicate check
- `src/issue_observatory/api/routes/collections.py:757` — `create_project_collection()`: iterates QDs without checking for existing active runs
- `src/issue_observatory/api/templates/collections/launcher.html:356` — client-only `launching` disable

## Recommended Fix

Add a server-side guard in `create_collection_run()` before creating the `CollectionRun` row:

```python
# Check for existing active runs for this query design
existing_active = await db.execute(
    select(CollectionRun).where(
        CollectionRun.query_design_id == payload.query_design_id,
        CollectionRun.status.in_(["pending", "running"]),
    )
)
if existing_active.scalar_one_or_none() is not None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "A collection run is already pending or running for this query design. "
            "Cancel the existing run before launching a new one."
        ),
    )
```

Additionally, the form should use `hx-disable-elt="this"` for HTMX-level double-submit prevention.

## Impact

- Duplicate data collected (wasted API credits on premium tier)
- Potential rate-limit exhaustion from parallel identical requests
- Confusing UX — user sees two runs for the same thing
- Data deduplication may catch some overlaps, but not guaranteed across all arenas
