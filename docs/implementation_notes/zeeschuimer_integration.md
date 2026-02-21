# Zeeschuimer Integration Implementation

**Created**: 2026-02-21
**Author**: Core Application Engineer
**Status**: Complete — Ready for QA Review

---

## Summary

Implemented a complete Zeeschuimer integration that allows the Issue Observatory to receive NDJSON data directly from the Zeeschuimer browser extension, following the 4CAT-compatible protocol. This enables manual capture of LinkedIn, Twitter/X, Instagram, TikTok, and Threads content.

---

## Components Implemented

### 1. Module Structure

```
src/issue_observatory/imports/
├── __init__.py                   # Module exports
├── zeeschuimer.py                # NDJSON processor and dispatcher
└── normalizers/
    ├── __init__.py               # Normalizer exports
    ├── linkedin.py               # LinkedIn Voyager V2 normalizer (NEW)
    ├── twitter.py                # Twitter/X adapter normalizer
    ├── instagram.py              # Instagram adapter normalizer
    ├── tiktok.py                 # TikTok adapter normalizer
    └── threads.py                # Threads adapter normalizer
```

### 2. API Routes (in `api/routes/imports.py`)

Added two 4CAT-compatible endpoints:

**`POST /api/import-dataset/`**
- Receives raw NDJSON body stream from Zeeschuimer
- Requires `X-Zeeschuimer-Platform` header (e.g., "linkedin.com", "twitter.com")
- Authenticates via JWT cookie or Bearer token
- Streams request body to temp file (4096-byte chunks)
- Creates a `CollectionRun` with `mode="zeeschuimer_import"`
- Processes file and returns import key
- Rate limited: 5 uploads per minute per user

**`GET /api/check-query/`**
- Polls import status by key
- Returns `{"done": bool, "status": str, "rows": int, "datasource": str, "url": str}`
- Compatible with Zeeschuimer's polling logic

### 3. Platform Normalizers

#### LinkedIn Normalizer (`normalizers/linkedin.py`)
**Most complex** — processes LinkedIn Voyager V2 API format:
- Extracts activity ID from URN patterns
- Estimates publication timestamp from relative time strings ("18h ago", "2d", "3mo")
- Parses deeply nested author fields (miniProfile, miniCompany)
- Extracts engagement metrics from multiple field locations
- Handles hashtags, mentions, images, videos, links
- Computes reaction breakdown by type
- Preserves inclusion context ("why you're seeing this")

**Key challenge**: LinkedIn provides only relative timestamps, requiring `parse_time_ago()` to estimate publication dates.

#### Twitter Normalizer (`normalizers/twitter.py`)
Adapter that maps Zeeschuimer's Twitter GraphQL format to IO schema:
- Handles both modern (`rest_id`) and legacy (`id_str`) formats
- Parses Twitter timestamp format (`"Mon Jan 15 12:34:56 +0000 2026"`)
- Extracts author from `core.user_results.result.legacy` path
- Maps engagement metrics (likes, retweets, replies, quotes, bookmarks)

#### Instagram Normalizer (`normalizers/instagram.py`)
Adapter that handles both Instagram API formats:
- Graph API format (with `__typename`)
- Item list format (with `media_type` integer codes)
- Constructs post URL from shortcode
- Detects content type (photo, video, carousel, reel)
- Extracts location metadata

#### TikTok Normalizer (`normalizers/tiktok.py`)
Handles both TikTok videos and comments:
- Detects comment vs. video based on `cid` field or platform identifier
- Constructs video URL from author username and video ID
- Extracts hashtags from challenges array
- Maps engagement metrics (digg/like, comment, share, play counts)

#### Threads Normalizer (`normalizers/threads.py`)
Adapts Threads data (Instagram-like but distinct):
- Handles both caption object and thread_items formats
- Extracts reply/repost/quote counts from `text_post_app_info`
- Constructs post URL from code

### 4. NDJSON Processor (`zeeschuimer.py`)

**`ZeeschuimerProcessor` class**:
- Streams file line by line (never loads entire file into memory)
- Strips NUL bytes from each line before JSON parsing (4CAT compatibility)
- Restructures each item: extracts `data` as content, collects envelope as metadata
- Dispatches to platform-specific normalizer based on `source_platform`
- Applies universal normalization via `Normalizer.normalize()`
- Computes `content_hash` (SHA-256) and `simhash` for deduplication
- Bulk-inserts into `content_records` table with `ON CONFLICT DO NOTHING`
- Tags all records with `collection_tier="manual"` and `raw_metadata.import_source="zeeschuimer"`

### 5. Authentication

Supports two mechanisms (as recommended in spec):
1. **JWT cookie** (session-based) — for browser extensions in same browser context
2. **Bearer token** (`Authorization: Bearer {token}` header) — for programmatic access

### 6. Platform Support Matrix

| Zeeschuimer module_id | IO platform_name | Status | Notes |
|----------------------|------------------|--------|-------|
| `linkedin.com` | `linkedin` | **Full support** | Only collection path for LinkedIn data |
| `twitter.com` | `x_twitter` | Full support | Supplements automated collection |
| `instagram.com` | `instagram` | Full support | Supplements automated collection |
| `tiktok.com` | `tiktok` | Full support | Supplements automated collection |
| `tiktok-comments` | `tiktok_comments` | Full support | Not available via Research API |
| `threads.net` | `threads` | Full support | Supplements automated collection |

Unsupported platforms (Gab, Truth Social, 9GAG, Imgur, etc.) return HTTP 404 with 4CAT-compatible error message.

---

## Technical Decisions

### 1. Router Integration
**Decision**: Merged Zeeschuimer routes into existing `api/routes/imports.py` rather than creating a separate router.
**Rationale**: Both the existing multipart file upload and the Zeeschuimer protocol are import pathways; keeping them in one module improves discoverability and maintains logical grouping.

### 2. Synchronous Processing
**Decision**: Process files synchronously within the HTTP handler (not queued to Celery).
**Rationale**: Typical Zeeschuimer uploads are small (hundreds to low thousands of items); synchronous processing provides immediate feedback and simplifies state management. Can be moved to Celery for larger files in the future.

### 3. In-Memory State Tracking
**Decision**: Use module-level dict `_zeeschuimer_import_state` for tracking import status.
**Rationale**: Simplifies initial implementation; sufficient for typical single-server deployments. Production should migrate to Redis for multi-server setups.

### 4. Collection Run Tracking
**Decision**: Create a `CollectionRun` with `mode="zeeschuimer_import"` for each upload.
**Rationale**: Provides provenance tracking, credit accounting (if enabled), and consistent data model with automated collections. Query design is `NULL` because manual imports are not query-driven.

### 5. LinkedIn Timestamp Estimation
**Decision**: Estimate publication timestamps from relative time strings via `parse_time_ago()`.
**Rationale**: LinkedIn Voyager V2 does not provide absolute timestamps; this is the only option. Timestamps become less precise for older posts (e.g., "3mo" could be off by 15 days). The raw `time_ago_str` is preserved in `raw_metadata` and the estimated timestamp is flagged.

---

## Quality Standards Compliance

All code follows the technical standards defined in `CLAUDE.md`:

- **Type hints**: All function signatures have strict type hints
- **Docstrings**: Google-style docstrings on all public classes and functions
- **Async I/O**: All database operations are async
- **Error handling**: Custom exceptions from `core/exceptions.py` with proper chaining
- **Logging**: Structured logging via structlog
- **File length**: All files under 400 lines
- **Danish defaults**: N/A (Zeeschuimer data is pre-captured, no filtering applied)

---

## Dependencies

No new dependencies required. All normalizers use existing libraries:
- `httpx` (already present)
- `structlog` (already present)
- `Normalizer` from `core/normalizer.py`
- `compute_simhash` from `core/deduplication.py`

---

## Testing Notes

Syntax validation passed for all modules. Next steps for QA:

1. **Unit tests**: Create sample NDJSON fixtures for each platform (see spec Section 8.1)
2. **Integration tests**: Test the full upload → process → insert pathway
3. **Edge cases**: Malformed JSON, NUL bytes, missing fields, promoted posts (LinkedIn)
4. **Rate limiting**: Verify 5/minute limit is enforced
5. **Authentication**: Test both JWT cookie and Bearer token auth
6. **Deduplication**: Upload same items twice, verify no duplicates created
7. **Large uploads**: Test with 10,000+ item files to verify memory stays bounded

Suggested test fixtures:
```
tests/fixtures/zeeschuimer/
├── linkedin_feed.ndjson         # 5-10 varied LinkedIn posts
├── linkedin_edge_cases.ndjson   # Promoted posts, missing fields, aggregate URNs
├── twitter_timeline.ndjson      # 3-5 tweets (regular, retweet, quote)
├── instagram_posts.ndjson       # 3-5 posts (photo, video, carousel)
├── tiktok_videos.ndjson         # 3-5 videos
├── threads_posts.ndjson         # 3-5 threads
└── malformed.ndjson             # Invalid JSON, NUL bytes, empty lines
```

---

## Known Limitations

1. **LinkedIn timestamps are imprecise**: Posts older than a few days may have publication dates off by several days or weeks (inherent to Voyager V2 API limitation).
2. **In-memory state tracking**: Not suitable for multi-server deployments without Redis migration.
3. **No progress streaming**: Large uploads show no progress updates (all-or-nothing processing).
4. **Search term matching**: Imported records have `search_terms_matched=[]` because they were manually captured. Retroactive term matching (running the query builder against imported text) is not implemented.

---

## Future Enhancements

1. **Celery task queue**: For uploads > 5,000 items, offload processing to Celery worker
2. **Redis state store**: Replace in-memory dict with Redis for multi-server support
3. **Progress streaming**: Emit SSE events during processing for large uploads
4. **Retroactive term matching**: Auto-run query builder against imported text to populate `search_terms_matched`
5. **Auto-enrichment**: Trigger enrichment pipeline (language detection, sentiment, NER) on import
6. **Query design association**: Allow optional `?query_design_id={uuid}` parameter to link imports to a specific design

---

## Files Changed/Created

**Created**:
- `/src/issue_observatory/imports/__init__.py`
- `/src/issue_observatory/imports/zeeschuimer.py`
- `/src/issue_observatory/imports/normalizers/__init__.py`
- `/src/issue_observatory/imports/normalizers/linkedin.py`
- `/src/issue_observatory/imports/normalizers/twitter.py`
- `/src/issue_observatory/imports/normalizers/instagram.py`
- `/src/issue_observatory/imports/normalizers/tiktok.py`
- `/src/issue_observatory/imports/normalizers/threads.py`
- `/docs/implementation_notes/zeeschuimer_integration.md` (this file)

**Modified**:
- `/src/issue_observatory/api/routes/imports.py` — Added Zeeschuimer routes

---

## Status File Update Required

`/docs/status/core.md` should be updated to mark Zeeschuimer integration as ready for QA review.

---

## References

- **Specification**: `/docs/research_reports/zeeschuimer_4cat_protocol.md`
- **4CAT source**: `https://github.com/digitalmethodsinitiative/4cat`
- **Zeeschuimer source**: `https://github.com/digitalmethodsinitiative/zeeschuimer`
