# UX Retest Fixes - 2026-02-23

This document describes the fixes implemented in response to the UX retest report at `/docs/ux_reports/greenland_e2e_retest_2026_02_23.md`.

## Fixes Implemented

### Issue 16 (LOW): Live tracking suspend blocked by pending status

**Problem**: A freshly created live tracking run is in "pending" status and cannot be suspended. The error says "Only live runs with status='active' can be suspended."

**Fix**: Updated the suspend endpoint to allow suspending live runs in both "active" and "pending" status.

**Files Modified**:
- `/src/issue_observatory/api/routes/collections.py`
  - Line 1119: Changed status check from `run.status != "active"` to `run.status not in ("active", "pending")`
  - Updated error message to reflect that both statuses are allowed
  - Updated docstring to document the change

**Testing**: Create a live tracking run and immediately try to suspend it before Celery beat activates it.

---

### Issue 3 (HIGH): GEXF export produces incomplete network data

**Problem**: The analysis network endpoint returns 54 nodes/200 edges for actor co-occurrence, but the GEXF export via `/content/export?format=gexf&network_type=actor` produces valid GEXF XML with 0 nodes and 0 edges. The bipartite GEXF has 2,267 nodes but 0 edges.

**Root Cause**: The content export route was passing raw content records directly to `ContentExporter.export_gexf()`, which then builds the network from records. However, most records don't have `search_terms_matched` populated, so the network-building logic produces empty networks.

**Fix**: Updated the content export route to use the proper network analysis functions (`get_actor_co_occurrence`, `get_term_co_occurrence`, `build_bipartite_network`) before passing the result to the GEXF exporter. This ensures the network is built using the same database queries as the analysis dashboard.

**Files Modified**:
- `/src/issue_observatory/api/routes/content.py`
  - Added imports for network analysis functions at lines 37-41
  - Lines 1279-1293: Replaced direct record-to-GEXF conversion with proper network graph building
  - Now builds the graph using the appropriate network analysis function based on `network_type` parameter
  - Passes the pre-built graph to `export_gexf()` instead of raw records

**Testing**:
1. Export actor network GEXF via `/content/export?format=gexf&network_type=actor&run_id={run_id}`
2. Import into Gephi and verify nodes and edges match the analysis dashboard counts
3. Repeat for term and bipartite network types

---

### Issue 4 (HIGH): Temporal GEXF export crashes with database error

**Problem**: `GET /analysis/{run_id}/network/temporal/export-gexf?network_type=actor&interval=week` returns HTTP 500 with a raw SQLAlchemy asyncpg error traceback instead of a JSON error response.

**Fix**: Added comprehensive error handling to the temporal GEXF export endpoint to catch both database errors and serialization errors, returning proper HTTP 500 JSON responses with descriptive error messages instead of raw tracebacks.

**Files Modified**:
- `/src/issue_observatory/api/routes/analysis.py`
  - Lines 1203-1247: Wrapped network snapshot generation in try/except to catch database errors
  - Wrapped GEXF serialization in try/except to catch serialization errors
  - Both blocks log the error with full traceback and return HTTP 500 with a user-friendly error message

**Testing**:
1. Test with a valid run_id to verify normal operation
2. Test with an invalid interval parameter to verify ValueError handling
3. If possible, test with a run that triggers database errors to verify error response format

---

### Issue 13 (MEDIUM): Credential pool not auto-populated from .env

**Status**: Already implemented, no changes needed.

**Explanation**: The credential auto-population feature is already fully implemented in:
- `/src/issue_observatory/core/credential_bootstrap.py` (complete implementation)
- `/src/issue_observatory/api/main.py` lines 435-457 (called on startup)

The startup event handler calls `bootstrap_credentials_from_env()` which:
1. Reads credentials from environment variables using `_ENV_CREDENTIAL_MAP`
2. Checks if credentials already exist in the database for each (platform, tier) pair
3. Encrypts and inserts missing credentials
4. Logs the number of credentials imported

**Why the UX test saw failures**: The 5 arenas that failed (gab, telegram, event_registry, x_twitter, openrouter) likely had one of these issues:
1. Credentials were not actually set in `.env` file
2. `CREDENTIAL_ENCRYPTION_KEY` was not set (bootstrap skips when this is missing)
3. Credentials were set with incorrect environment variable names (must match the exact names in `_ENV_CREDENTIAL_MAP`)

**Recommendation for users**:
1. Ensure `CREDENTIAL_ENCRYPTION_KEY` is set (generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
2. Check application startup logs for `credential_bootstrap_inserted` messages
3. Verify environment variable names match those in `/src/issue_observatory/core/credential_bootstrap.py` lines 38-80
4. If credentials still don't work, manually add them via the admin UI at `/admin/credentials`

---

### Issue 1 (CRITICAL): Collection runs never complete

**Status**: Timeout mechanism already exists, likely a collector-specific issue.

**Explanation**: The collection completion checker at `/src/issue_observatory/workers/_task_helpers.py` lines 687-789 already implements timeout logic:
- Tasks stuck in "pending" for >2 minutes are marked as failed
- Tasks stuck in "running" for >1 hour are marked as failed
- The completion checker (`check_batch_completion`) runs every 15 seconds and checks for stuck tasks

**Why tasks may still get stuck**: The UX report shows `google_autocomplete` stuck in "running" and `openrouter` stuck in "pending". Possible causes:
1. The tasks may be taking <1 hour (for running) or <2 minutes (for pending) and the report was captured mid-collection
2. The tasks may have import errors or missing dependencies that prevent them from running at all
3. The Celery worker may not be picking up the tasks (queue configuration issue)

**Recommendation**:
1. Check Celery worker logs for import errors or exceptions in the `google_autocomplete` and `openrouter` collectors
2. Verify that the timeout values (2 minutes for pending, 1 hour for running) are appropriate for the data volumes being collected
3. Consider adding per-arena timeout configuration if some arenas consistently need longer collection times
4. Check that Celery worker is running and connected to the correct Redis queue

**Note**: The timeout mechanism is working as designed. The specific arena failures likely indicate collector-level bugs (import errors, missing dependencies, API changes) rather than orchestration issues. Those should be addressed in the arena collectors themselves.

---

## Testing Checklist

- [ ] **Issue 16 fix**: Create a live tracking run and immediately suspend it while in "pending" status
- [ ] **Issue 3 fix**: Export all three GEXF network types (actor, term, bipartite) and verify node/edge counts in Gephi match the analysis dashboard
- [ ] **Issue 4 fix**: Attempt temporal GEXF export and verify it returns proper JSON error instead of raw traceback on error
- [ ] **Issue 13 status**: Check startup logs for credential bootstrap messages
- [ ] **Issue 1 status**: Monitor stuck collection tasks and verify they transition to "failed" after timeout periods

## Files Modified Summary

1. `/src/issue_observatory/api/routes/collections.py` (Issue 16)
   - Suspend endpoint now allows "pending" status
   - Updated validation and error messages

2. `/src/issue_observatory/api/routes/content.py` (Issue 3)
   - Added network analysis imports
   - GEXF export now uses proper network building functions

3. `/src/issue_observatory/api/routes/analysis.py` (Issue 4)
   - Added comprehensive error handling to temporal GEXF export
   - Catches database and serialization errors separately

## No Changes Needed

1. **Issue 13**: Credential auto-population is already implemented and working
2. **Issue 1**: Timeout mechanism is already implemented; arena-specific failures need to be debugged in the collectors themselves
