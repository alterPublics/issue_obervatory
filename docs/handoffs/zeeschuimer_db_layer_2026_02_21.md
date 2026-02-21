# Zeeschuimer Import Integration — Database Layer Implementation

**Date**: 2026-02-21
**Author**: Database & Data Processing Engineer
**Status**: Complete
**Handoff to**: Core Application Engineer

---

## Summary

The database layer for the Zeeschuimer import integration is now complete. This enables the Issue Observatory to receive NDJSON data uploads from the Zeeschuimer browser extension, providing a collection pathway for platforms that lack automated API access (primarily LinkedIn).

The implementation creates a new `zeeschuimer_imports` table to track import jobs separately from the existing `collection_runs` table, reflecting the fundamentally different data flow (push-based manual capture vs. pull-based query-driven collection).

---

## What Was Implemented

### 1. New ORM Model: `ZeeschuimerImport`

**File**: `/src/issue_observatory/core/models/zeeschuimer_import.py`

A new SQLAlchemy 2.0 model tracking each import job from Zeeschuimer with:
- Unique polling `key` for Zeeschuimer status checks (e.g., "import-abc123")
- Status progression: `queued` → `processing` → `complete`/`failed`
- Progress tracking: `rows_total`, `rows_processed`, `rows_imported`
- Platform identification from the `X-Zeeschuimer-Platform` header
- Optional association with a `query_design_id` for organization
- Audit trail: `initiated_by`, `started_at`, `completed_at`, `error_message`
- `progress_percent` property for polling responses

### 2. Migration 014: `zeeschuimer_imports` Table

**File**: `/alembic/versions/014_add_zeeschuimer_imports_table.py`

Creates the table with:
- UUID primary key
- Foreign keys to `users.id` (ON DELETE RESTRICT) and `query_designs.id` (ON DELETE SET NULL)
- Five indexes for efficient lookups (key, initiated_by, query_design_id, platform, status)
- TimestampMixin columns (created_at, updated_at)
- JSONB `metadata` field for extensibility
- Fully reversible `upgrade()` and `downgrade()` functions

### 3. Updated Existing Models

**Files**:
- `/src/issue_observatory/core/models/users.py` — added reverse relationship `zeeschuimer_imports`
- `/src/issue_observatory/core/models/query_design.py` — added reverse relationship `zeeschuimer_imports`
- `/src/issue_observatory/core/models/__init__.py` — exported `ZeeschuimerImport`

### 4. Documentation

**File**: `/docs/status/db.md`

Added comprehensive documentation in the status file covering:
- Schema design rationale (why a separate table vs. reusing `collection_runs`)
- Field-by-field schema documentation
- Platform mapping table (Zeeschuimer module_id → IO platform_name)
- Content tagging requirements for imported records
- Next steps for the Core Application Engineer

---

## Schema Overview

### Table: `zeeschuimer_imports`

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID | Primary key |
| `key` | VARCHAR(100), UNIQUE | Polling key for Zeeschuimer (e.g., "import-abc123") |
| `initiated_by` | UUID, FK users(id) | User who uploaded the data |
| `query_design_id` | UUID, FK query_designs(id), NULL | Optional organizational link |
| `platform` | VARCHAR(50) | Zeeschuimer module_id (e.g., "linkedin.com") |
| `status` | VARCHAR(20) | queued \| processing \| complete \| failed |
| `rows_total` | INTEGER | Total NDJSON lines |
| `rows_processed` | INTEGER | Lines successfully parsed |
| `rows_imported` | INTEGER | Content records created (after dedup) |
| `started_at` | TIMESTAMPTZ, NULL | Processing start time |
| `completed_at` | TIMESTAMPTZ, NULL | Processing end time |
| `error_message` | TEXT, NULL | Error details if failed |
| `file_path` | VARCHAR(500), NULL | Temporary NDJSON file path |
| `metadata` | JSONB | Additional metadata (file size, user agent, etc.) |
| `created_at` | TIMESTAMPTZ | Record creation timestamp |
| `updated_at` | TIMESTAMPTZ | Last update timestamp |

**Indexes**: key (unique), initiated_by, query_design_id, platform, status

---

## Why a Separate Table?

The decision to create a dedicated `zeeschuimer_imports` table rather than reusing `collection_runs` was based on:

1. **Different data flow**: Push-based (browser → server) vs. pull-based (server → API)
2. **Different lifecycle**: No tasks, arenas_config, credit transactions, or tier logic
3. **Different tracking needs**: Polling key, row-level progress, platform from HTTP header
4. **Cleaner separation**: Avoids special-casing "zeeschuimer_import" mode throughout the codebase

---

## Imported Content Record Tagging

All content records created from Zeeschuimer imports should be tagged with:

```python
{
    "collection_tier": "manual",
    "raw_metadata": {
        "import_source": "zeeschuimer",
        "zeeschuimer_import_id": str(import.id),
        "zeeschuimer": {
            "nav_index": "...",
            "source_platform_url": "...",
            "source_url": "...",
            "user_agent": "...",
            "timestamp_collected": 1740100000000
        }
    }
}
```

This enables filtering and provenance tracking for manually captured data.

---

## Platform Mapping Reference

| Zeeschuimer module_id | IO platform_name | Use Case |
|----------------------|------------------|----------|
| `linkedin.com` | `linkedin` | **Primary** — no automated collection for LinkedIn |
| `twitter.com` | `x_twitter` | Supplement automated collection |
| `instagram.com` | `instagram` | Supplement automated collection |
| `tiktok.com` | `tiktok` | Supplement automated collection |
| `tiktok-comments` | `tiktok_comments` | Not available via Research API |
| `threads.net` | `threads` | Supplement automated collection |

---

## What's Still Needed (Core Application Engineer)

The database layer is complete, but the import endpoint and processing logic are not yet implemented. The Core Application Engineer will need to build:

### 1. FastAPI Routes

**`POST /api/import-dataset/`** (Zeeschuimer upload endpoint):
- Accept raw NDJSON body (not multipart form data)
- Read `X-Zeeschuimer-Platform` header
- Stream body to temporary file
- Create `ZeeschuimerImport` record with status="queued"
- Return `{"status": "queued", "key": "import-abc123", "url": "/content/?import_id=..."}`

**`GET /api/check-query/?key={key}`** (Zeeschuimer polling endpoint):
- Look up `ZeeschuimerImport` by `key`
- Return `{"done": bool, "status": "...", "rows": N, "progress": N, "datasource": "...", "url": "..."}`

### 2. NDJSON Parser

- Line-by-line streaming parser (handle large files without loading into memory)
- Strip NUL bytes (`\0`) from each line before JSON parsing (per 4CAT spec)
- Restructure Zeeschuimer envelope: extract `item["data"]` as content, store envelope fields as `import_meta`

### 3. Platform-Specific Normalizers

**Priority: LinkedIn** (`linkedin.com` → `linkedin`):
- Parse LinkedIn Voyager V2 API format
- Estimate timestamps from relative time strings ("2d ago", "3mo ago") — see Section 4.1 of spec
- Extract engagement metrics, hashtags, mentions, media URLs
- Map to universal content_record schema (Section 5.2 of spec)

**Other platforms**: Adapt existing arena normalizers where possible (Twitter, Instagram, TikTok).

### 4. Processing Task

Options:
- **Synchronous** (simple, suitable for typical upload sizes of hundreds to low thousands of records)
- **Celery task** (async, better for large uploads, but adds complexity)

Update `rows_processed` and `status` as processing proceeds.

### 5. Error Handling

- Validate platform support (reject unknown platforms with 404)
- Catch parsing errors per line (log, skip, continue)
- Set `status = 'failed'` and populate `error_message` on critical failures
- Clean up temporary file after processing

### 6. Authentication

Support two mechanisms:
- **JWT Bearer token** (via `Authorization: Bearer {token}` header) — preferred
- **Session cookie** (for browser-based Zeeschuimer uploads in the same Firefox session)

---

## Testing Checklist

- [ ] Create import record with valid `key`
- [ ] Poll status via `/api/check-query/?key={key}`
- [ ] Parse valid LinkedIn NDJSON fixture (see Section 7.4 of spec for sample data)
- [ ] Handle malformed JSON lines gracefully
- [ ] Deduplicate imported records by `content_hash`
- [ ] Tag imported records with `import_source = "zeeschuimer"`
- [ ] Associate import with `query_design_id` (optional)
- [ ] Reject unsupported platforms with 404
- [ ] Verify `progress_percent` property calculation
- [ ] Test large upload (1000+ lines) — memory-efficient streaming

---

## Reference Documentation

- **Full protocol specification**: `/docs/research_reports/zeeschuimer_4cat_protocol.md` (91 pages, complete reference)
- **DB status file**: `/docs/status/db.md` (section: "Zeeschuimer Import Integration — Data Layer")
- **Zeeschuimer repository**: https://github.com/digitalmethodsinitiative/zeeschuimer
- **4CAT reference implementation**: https://github.com/digitalmethodsinitiative/4cat

---

## Files Changed

### Created
- `/src/issue_observatory/core/models/zeeschuimer_import.py`
- `/alembic/versions/014_add_zeeschuimer_imports_table.py`
- `/docs/handoffs/zeeschuimer_db_layer_2026_02_21.md` (this file)

### Modified
- `/src/issue_observatory/core/models/__init__.py` — added `ZeeschuimerImport` export
- `/src/issue_observatory/core/models/users.py` — added reverse relationship
- `/src/issue_observatory/core/models/query_design.py` — added reverse relationship
- `/docs/status/db.md` — added full documentation section

---

## Questions?

Contact the Database & Data Processing Engineer for any schema-related questions or clarifications.
