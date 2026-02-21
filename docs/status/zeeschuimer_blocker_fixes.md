# Zeeschuimer Integration - Blocker Fixes Applied

**Date:** 2026-02-21
**Engineer:** Core Application Engineer
**Status:** All blockers and critical warnings fixed

---

## Overview

This document summarizes the fixes applied to address the 4 blockers and most important warnings identified in the QA review of the Zeeschuimer integration.

---

## BLOCKER-1: ON CONFLICT (content_hash) — Partial Unique Index Fix

### Issue
The `ON CONFLICT (content_hash) DO NOTHING` clause did not match the partial unique index created by migration 015: `WHERE content_hash IS NOT NULL`.

### Fix Applied
Updated both bulk insert methods to use the full conflict target with WHERE clause:

**Files Modified:**
- `/src/issue_observatory/imports/zeeschuimer.py` (line 261-264)
- `/src/issue_observatory/api/routes/imports.py` (line 178-181)

**Change:**
```python
# Before
ON CONFLICT (content_hash) DO NOTHING

# After
ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL DO NOTHING
```

This matches PostgreSQL's requirement that partial unique index conflict targets must include the WHERE clause.

---

## BLOCKER-2: Switch from CollectionRun to ZeeschuimerImport Model

### Issue
The route code used `CollectionRun` instead of the dedicated `ZeeschuimerImport` model, and maintained an in-memory state dict instead of persisting to the database.

### Fix Applied

**Files Modified:**
- `/src/issue_observatory/api/routes/imports.py`
  - Removed `_zeeschuimer_import_state` in-memory dict (line 411)
  - Replaced `CollectionRun` creation with `ZeeschuimerImport` (lines 461-471)
  - Updated progress tracking to write to DB record (lines 490-500)
  - Modified polling endpoint to query DB instead of in-memory state (lines 625-668)

- `/src/issue_observatory/imports/zeeschuimer.py`
  - Changed parameter from `collection_run_id` to `zeeschuimer_import_id` (line 68)
  - Updated docstrings and log messages
  - Added `zeeschuimer_import_id` to `raw_metadata` for audit trail (line 182)

**Key Changes:**
1. **Upload endpoint:** Creates `ZeeschuimerImport` record with `status="queued"`
2. **Processing:** Updates `status` to `"processing"`, tracks `rows_total`, `rows_processed`, `rows_imported`
3. **Completion:** Sets `status="complete"` or `"failed"`, records `completed_at` timestamp
4. **Polling endpoint:** Queries DB by `key` field, returns live status

---

## BLOCKER-3: Add Authentication to Polling Endpoint

### Issue
The `/check-query/` polling endpoint was missing authentication, allowing unauthenticated access to import status.

### Fix Applied

**File Modified:**
- `/src/issue_observatory/api/routes/imports.py` (line 612)

**Change:**
```python
async def zeeschuimer_check_query(
    key: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],  # BLOCKER-3: Added
) -> dict:
```

The endpoint now requires an authenticated active user, matching the upload endpoint's security model.

---

## BLOCKER-4: published_at NULL Fallback

### Issue
When `published_at` is None (LinkedIn promoted posts, unparseable timestamps), the record would fail insertion due to NOT NULL constraint.

### Fix Applied

**File Modified:**
- `/src/issue_observatory/imports/zeeschuimer.py` (lines 176-183)

**Change:**
```python
# BLOCKER-4: Fall back to collected_at if published_at is None
if not record.get("published_at"):
    fallback_timestamp = timestamp_collected or datetime.now(tz=timezone.utc)
    record["published_at"] = fallback_timestamp.isoformat()
    if "raw_metadata" not in record or record["raw_metadata"] is None:
        record["raw_metadata"] = {}
    record["raw_metadata"]["published_at_source"] = "collected_at_fallback"
```

This ensures:
1. Every record has a valid `published_at` timestamp
2. Fallback is documented in `raw_metadata` for transparency
3. LinkedIn promoted posts (which have no time indication) get a reasonable estimated timestamp

---

## WARNING-2: Remove Unused `import logging`

### Issue
All normalizer files imported `logging` but never used it (all logging is done via `structlog`).

### Fix Applied

**Files Modified:**
- `/src/issue_observatory/imports/normalizers/linkedin.py` (line 21)
- `/src/issue_observatory/imports/normalizers/twitter.py` (line 16)
- `/src/issue_observatory/imports/normalizers/instagram.py` (line 13)
- `/src/issue_observatory/imports/normalizers/tiktok.py` (line 14)
- `/src/issue_observatory/imports/normalizers/threads.py` (line 10)
- `/src/issue_observatory/imports/zeeschuimer.py` (line 20)

**Change:** Removed `import logging` from all files.

---

## WARNING-3: Switch to structlog in imports.py

### Issue
The route file used `logging.getLogger(__name__)` instead of the project-standard `structlog.get_logger(__name__)`.

### Fix Applied

**File Modified:**
- `/src/issue_observatory/api/routes/imports.py` (lines 23, 28, 40)

**Change:**
```python
# Before
import logging
logger = logging.getLogger(__name__)

# After
import structlog
logger = structlog.get_logger(__name__)
```

Also updated all log calls to use structured logging format (key=value pairs).

---

## WARNING-4: Instagram Ad Filtering

### Issue
Instagram ads should be filtered out during normalization to avoid cluttering the dataset with promoted content.

### Fix Applied

**File Modified:**
- `/src/issue_observatory/imports/normalizers/instagram.py` (lines 86-94)

**Change:**
```python
# Skip Instagram ads (WARNING-4)
product_type = str(raw_data.get("product_type") or "").lower()
if product_type == "ad":
    logger.info(
        "instagram.ad_filtered",
        post_id=post_id,
        shortcode=shortcode,
    )
    # Return a minimal record that will be skipped by validation
    # (missing required fields)
    return {"id": post_id, "instagram_ad_filtered": True}
```

Ads are detected via `product_type == "ad"` and filtered early in the normalization pipeline.

---

## WARNING-6: Convert collected_at to ISO String

### Issue
The `collected_at` override was stored as a datetime object instead of ISO 8601 string, causing serialization inconsistencies.

### Fix Applied

**File Modified:**
- `/src/issue_observatory/imports/zeeschuimer.py` (line 176)

**Change:**
```python
# Before
if timestamp_collected:
    record["collected_at"] = timestamp_collected

# After (WARNING-6)
if timestamp_collected:
    record["collected_at"] = timestamp_collected.isoformat()
```

---

## WARNING-7: Remove Redundant Temp File Cleanup

### Issue
The `except` block cleaned up the temp file, but the `finally` block also cleaned it up, resulting in redundant logic.

### Fix Applied

**File Modified:**
- `/src/issue_observatory/api/routes/imports.py` (lines 536-545)

**Change:** Removed temp file cleanup from the `except` block (lines 589-591 in old code). The `finally` block handles all cleanup cases.

---

## WARNING-8: Remove Commit from _bulk_insert()

### Issue
The `_bulk_insert()` method in `zeeschuimer.py` called `await self._db.commit()`, violating the principle of letting the caller manage transaction boundaries.

### Fix Applied

**File Modified:**
- `/src/issue_observatory/imports/zeeschuimer.py` (line 276)

**Change:**
```python
# WARNING-8: Let the caller manage the commit boundary
return inserted, skipped
```

Removed the `await self._db.commit()` line. The caller (`process_file`) now commits after bulk insert completes, and the route endpoint commits after updating the `ZeeschuimerImport` status.

---

## Files Modified Summary

| File | Lines Changed | Changes |
|------|--------------|---------|
| `/src/issue_observatory/imports/zeeschuimer.py` | ~30 | BLOCKER-1, BLOCKER-2, BLOCKER-4, WARNING-2, WARNING-6, WARNING-8 |
| `/src/issue_observatory/api/routes/imports.py` | ~50 | BLOCKER-1, BLOCKER-2, BLOCKER-3, WARNING-3, WARNING-7 |
| `/src/issue_observatory/imports/normalizers/linkedin.py` | 1 | WARNING-2 |
| `/src/issue_observatory/imports/normalizers/twitter.py` | 1 | WARNING-2 |
| `/src/issue_observatory/imports/normalizers/instagram.py` | 10 | WARNING-2, WARNING-4 |
| `/src/issue_observatory/imports/normalizers/tiktok.py` | 1 | WARNING-2 |
| `/src/issue_observatory/imports/normalizers/threads.py` | 1 | WARNING-2 |

**Total:** 7 files modified, ~95 lines changed

---

## Testing Recommendations

### Unit Tests Required
1. Test `ON CONFLICT` with NULL `content_hash` values (should insert successfully)
2. Test `ON CONFLICT` with duplicate `content_hash` (should skip)
3. Test `published_at` fallback logic with LinkedIn promoted posts
4. Test Instagram ad filtering with `product_type="ad"`

### Integration Tests Required
1. Full Zeeschuimer upload → processing → polling flow
2. Verify `ZeeschuimerImport` record creation and status progression
3. Verify `raw_metadata.zeeschuimer_import_id` is set correctly
4. Test authentication on `/check-query/` endpoint (should reject unauthenticated requests)

### Manual Testing
1. Upload a real Zeeschuimer NDJSON file via `/import-dataset/`
2. Poll `/check-query/` with the returned key
3. Verify records appear in `content_records` table
4. Check `raw_metadata` for `zeeschuimer_import_id` and `published_at_source`
5. Verify Instagram ads are filtered from the dataset

---

## Notes for QA Engineer

- **Migration 015** must be applied before testing (creates the partial unique index)
- All syntax checks passed successfully
- Structured logging format updated throughout
- Transaction boundary management is now consistent
- Ready for comprehensive test coverage

---

**Status:** Ready for QA review
**Next Steps:** Run full test suite, verify integration tests pass
