# Comments Collection Module -- Implementation Plan

**Created**: 2026-03-12
**Last updated**: 2026-03-12 (v2 -- native API preference)
**Author**: Research Agent
**Status**: Draft -- ready for team review
**Depends on**: Feasibility report at `/docs/research_reports/comments_collection_feasibility.md`

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-12 v2 | **Native API preference revision.** Restricted Bright Data usage to Facebook and Instagram only (no decent free alternatives). YouTube now uses Data API v3 `commentThreads.list` exclusively (removed Bright Data fallback). TikTok now uses Research API `video/comment/list` exclusively (removed Bright Data option). Added X/Twitter, Gab, and Telegram to Phase 2 as native-API implementations. Simplified shared Bright Data module to 2-platform scope. Revised cost estimates downward (~$126/month to ~$54/month for reference scenario). Updated phase assignments and file references throughout. |
| 2026-03-12 | Initial draft. Complete architectural specification covering data model, workflow, per-platform implementation, shared Bright Data module, UI flow, cost management, and phased rollout. |

---

## Table of Contents

1. [Design Vision and Requirements](#1-design-vision-and-requirements)
2. [Data Model Changes](#2-data-model-changes)
3. [Comment Collection Workflow](#3-comment-collection-workflow)
4. [Per-Platform Implementation](#4-per-platform-implementation)
5. [Shared Bright Data Comment Module](#5-shared-bright-data-comment-module)
6. [Configuration UI Flow](#6-configuration-ui-flow)
7. [Cost and Rate Limit Management](#7-cost-and-rate-limit-management)
8. [Phased Rollout](#8-phased-rollout)
9. [GDPR and Legal Compliance](#9-gdpr-and-legal-compliance)
10. [Open Questions for Team Discussion](#10-open-questions-for-team-discussion)

---

## 1. Design Vision and Requirements

### 1.1 User-Facing Model

The comment collection module integrates into **project configuration**. For each project, the researcher can:

1. **Enable comment collection per platform** -- toggle which platforms should have comments collected.
2. **Specify targeting criteria** (per platform), choosing from three modes:
   - **Search terms** -- select from terms already in the project's query designs. Any post matching those terms on the enabled platform will have its comments collected.
   - **Source list actors** -- select from actors already in the project's query designs. Any post published by those actors will have its comments collected.
   - **Post URLs** -- provide specific post URLs to collect comments from directly.

### 1.2 Architecture Principles

- Comments are stored in the **same `content_records` table** as posts, using `content_type = "comment"` or `"reply"`. This preserves the universal schema's strength and avoids schema bifurcation.
- A new **`parent_platform_id`** column on `content_records` enables efficient thread reconstruction queries without JSONB path traversal.
- Comment configuration lives in a **`comments_config` JSONB column** on the `Project` model, following the precedent of `arenas_config` and `source_config`.
- Comment collection runs as a **post-collection phase** within the existing `CollectionRun` lifecycle, not as a separate scheduled task.
- A **shared Bright Data comment base** eliminates code duplication across the two Bright Data comment platforms (Facebook and Instagram). All other platforms use their native free APIs exclusively to minimize paid data provider costs.

---

## 2. Data Model Changes

### 2.1 New Column on `content_records` (Schema Migration Required)

**File**: `src/issue_observatory/core/models/content.py`
**Migration**: `alembic/versions/032_add_parent_platform_id.py`

Add one new nullable column to `UniversalContentRecord`:

```
parent_platform_id  String(500), nullable, indexed
```

**Purpose**: Stores the platform-native ID of the parent post that this comment is replying to. For example:
- Facebook: the post URL or post ID that the comment is on
- YouTube: the video ID that the comment is on
- Bluesky: the AT URI of the post being replied to
- Reddit: the submission ID (already stored in `raw_metadata.parent_post_id` -- this column promotes it for query efficiency)

**Why a first-class column**: The feasibility report (Section 5) recommended this when comment collection spans 3+ arenas. Thread reconstruction queries (`SELECT * FROM content_records WHERE parent_platform_id = :post_id`) are dramatically faster than JSONB path traversal (`raw_metadata->>'parent_post_id'`), especially on a partitioned table.

**Index**: B-tree index on `parent_platform_id` (inherited by all partitions):
```python
sa.Index("idx_content_parent_platform_id", "parent_platform_id"),
```

**Backward compatibility**: The column is nullable. All existing records have `parent_platform_id = NULL`. Existing Reddit comment records that store `parent_post_id` in `raw_metadata` are unaffected -- a backfill migration can optionally populate the new column from `raw_metadata->>'parent_post_id'` for existing Reddit comments.

### 2.2 New JSONB Column on `projects` Table

**File**: `src/issue_observatory/core/models/project.py`
**Migration**: `alembic/versions/032_add_parent_platform_id.py` (same migration)

Add a `comments_config` JSONB column to the `Project` model:

```python
comments_config: Mapped[dict] = mapped_column(
    JSONB,
    nullable=False,
    server_default=sa.text("'{}'::jsonb"),
    comment="Per-platform comment collection configuration.",
)
```

### 2.3 `comments_config` JSONB Schema

The `comments_config` column stores per-platform configuration as a JSON object. Each key is a `platform_name` (matching the arena registry key), and the value is a configuration object:

```json
{
  "facebook": {
    "enabled": true,
    "targeting_mode": "actors",
    "actor_list_ids": ["uuid-1", "uuid-2"],
    "search_term_ids": [],
    "post_urls": [],
    "max_comments_per_post": 500,
    "include_replies": true,
    "min_comments_threshold": 1
  },
  "instagram": {
    "enabled": true,
    "targeting_mode": "actors",
    "actor_list_ids": ["uuid-3"],
    "search_term_ids": [],
    "post_urls": [],
    "max_comments_per_post": 200,
    "include_replies": true,
    "min_comments_threshold": 1
  },
  "bluesky": {
    "enabled": true,
    "targeting_mode": "terms",
    "actor_list_ids": [],
    "search_term_ids": ["uuid-a", "uuid-b"],
    "post_urls": [],
    "max_thread_depth": 6,
    "min_comments_threshold": 1
  },
  "youtube": {
    "enabled": true,
    "targeting_mode": "actors",
    "actor_list_ids": ["uuid-4"],
    "search_term_ids": [],
    "post_urls": [],
    "max_comments_per_video": 100,
    "include_replies": true,
    "max_quota_units": 3000,
    "min_comments_threshold": 5
  },
  "reddit": {
    "enabled": true,
    "targeting_mode": "terms",
    "actor_list_ids": [],
    "search_term_ids": [],
    "post_urls": [],
    "max_comments_per_post": 100,
    "max_reply_depth": 3,
    "min_comments_threshold": 1
  }
}
```

**Field definitions**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `enabled` | boolean | Yes | Master toggle for this platform's comment collection. |
| `targeting_mode` | string | Yes | One of `"terms"`, `"actors"`, or `"urls"`. Determines which posts get their comments collected. |
| `actor_list_ids` | UUID[] | No | When `targeting_mode = "actors"`: which ActorList UUIDs (from the project's query designs) to use. Posts by actors in these lists have their comments collected. |
| `search_term_ids` | UUID[] | No | When `targeting_mode = "terms"`: which SearchTerm UUIDs to use. Posts matching these terms have their comments collected. |
| `post_urls` | string[] | No | When `targeting_mode = "urls"`: direct post/video URLs to collect comments from. |
| `max_comments_per_post` | int | No | Cap on comments collected per parent post. Default: platform-specific (see Section 4). |
| `max_thread_depth` | int | No | Maximum reply nesting depth (Bluesky, Reddit). Default: platform-specific. |
| `max_reply_depth` | int | No | Alias for `max_thread_depth` used by Reddit configuration. |
| `include_replies` | boolean | No | Whether to collect replies to top-level comments (YouTube, Facebook, Instagram). Default: `true`. |
| `max_quota_units` | int | No | For YouTube only: maximum Data API quota units to spend on comment collection per run. Default: `3000` (30% of the 10,000 daily quota per key). |
| `min_comments_threshold` | int | No | Only collect comments for posts with at least this many comments (reported by `comments_count`). Default: `1`. Cost optimization lever for Bright Data platforms (Facebook, Instagram) -- setting to 5+ significantly reduces spend. Also useful as a relevance filter for free-API platforms. |

### 2.4 No New Tables Required

Comments are stored in the existing `content_records` table. The existing `CollectionTask` model tracks comment collection tasks. No new tables are needed.

### 2.5 Content Record Field Usage for Comments

| `content_records` Column | Usage for Comments |
|----|---|
| `content_type` | `"comment"` for top-level comments; `"reply"` for replies to comments |
| `parent_platform_id` | **NEW** -- platform-native ID of the parent post |
| `text_content` | Comment text body |
| `title` | `NULL` (comments have no title) |
| `author_platform_id` | Commenter's platform ID (always pseudonymized -- no public_figure bypass) |
| `author_display_name` | Commenter's display name (pseudonymized) |
| `pseudonymized_author_id` | SHA-256(salt + platform + commenter_id) |
| `likes_count` | Comment likes/upvotes |
| `comments_count` | Number of replies to this comment (if available) |
| `published_at` | Comment publication timestamp |
| `platform_id` | Platform-native comment ID |
| `url` | Direct URL to the comment (if available) |
| `raw_metadata` | Platform-specific fields: `thread_depth`, `root_post_platform_id`, `parent_comment_id`, nested reply data |

### 2.6 Pydantic Schema Addition

**File**: `src/issue_observatory/core/schemas/project.py`

Add a `CommentsConfigPlatform` Pydantic model for validation:

```python
class CommentsConfigPlatform(BaseModel):
    enabled: bool = False
    targeting_mode: Literal["terms", "actors", "urls"] = "actors"
    actor_list_ids: list[uuid.UUID] = []
    search_term_ids: list[uuid.UUID] = []
    post_urls: list[str] = []
    max_comments_per_post: int | None = None
    max_thread_depth: int | None = None
    max_reply_depth: int | None = None
    include_replies: bool = True
    max_quota_units: int | None = None  # YouTube only: cap on Data API quota units
    min_comments_threshold: int = 1

class CommentsConfig(BaseModel):
    """Root validator for Project.comments_config JSONB."""
    __root__: dict[str, CommentsConfigPlatform] = {}
```

---

## 3. Comment Collection Workflow

### 3.1 Overview: Two-Phase Collection Within a Single Run

Comment collection operates as **Phase 2** of a collection run. Phase 1 is the existing post/content collection. Phase 2 collects comments on the posts gathered in Phase 1 (and/or on directly specified post URLs).

```
CollectionRun lifecycle:
  pending -> running (Phase 1: post collection)
                    -> running (Phase 2: comment collection)
                    -> completed
```

This is NOT a separate Celery Beat task. Comment collection is dispatched by the same orchestration code that handles post collection, as a continuation of the same `CollectionRun`.

### 3.2 Trigger Mechanism

After all Phase 1 arena tasks for a `CollectionRun` complete (detected by `check_all_tasks_terminal()` in `_task_helpers.py`), the orchestration layer checks whether the project has `comments_config` with any platforms enabled.

**New orchestration function** (in `workers/tasks.py` or `workers/_comment_orchestrator.py`):

```
dispatch_comment_collection(collection_run_id, project_id) -> None
```

This function:

1. Loads the project's `comments_config` from the database.
2. For each platform with `enabled = True`:
   a. Resolves the target posts based on `targeting_mode` (see Section 3.3).
   b. Filters posts by `min_comments_threshold` (only collect comments for posts with `comments_count >= threshold`).
   c. Creates a `CollectionTask` row with `arena = "{platform}_comments"` to distinguish from the post collection task.
   d. Dispatches the platform-specific comment collection Celery task.

### 3.3 Target Post Resolution by Targeting Mode

#### Mode: `"terms"` (search term targeting)

1. Query `content_records` for the current `collection_run_id` where:
   - `platform = :platform`
   - `content_type IN ("post", "video", "status")` (not already a comment)
   - At least one element of `search_terms_matched` matches a term whose `SearchTerm.id` is in the `search_term_ids` list.
2. Extract the `platform_id` and `url` of each matching post.
3. Pass these as the input to the comment collection task.

**SQL sketch** (async SQLAlchemy):
```python
stmt = (
    select(
        UniversalContentRecord.platform_id,
        UniversalContentRecord.url,
        UniversalContentRecord.comments_count,
    )
    .where(
        UniversalContentRecord.collection_run_id == run_id,
        UniversalContentRecord.platform == platform_name,
        UniversalContentRecord.content_type.in_(["post", "video", "status"]),
        UniversalContentRecord.comments_count >= min_threshold,
    )
)
```

For term matching, the search_terms are resolved from `search_term_ids` via the `SearchTerm` table, then compared against `search_terms_matched` ARRAY on the content records. Since term-based targeting only applies to posts already collected by those terms, this is effectively "collect comments for all posts collected in this run on this platform that matched the configured terms."

**Simplification**: If ALL search terms in the project's query designs are selected, the query simplifies to "collect comments for all posts collected in this run on this platform."

#### Mode: `"actors"` (actor list targeting)

1. Resolve actor platform IDs from the `actor_list_ids`:
   - `ActorList` -> `ActorListMember` -> `Actor` -> `ActorPlatformPresence` (where `platform = :platform`)
   - Collect all `platform_user_id` values.
2. Query `content_records` for the current `collection_run_id` where:
   - `platform = :platform`
   - `author_platform_id IN (:actor_platform_ids)` (posts by these actors)
   - `content_type IN ("post", "video", "status")`
   - `comments_count >= min_threshold`
3. Extract `platform_id` and `url` for comment collection.

**Important**: For actor-only arenas (Facebook, Instagram), this is the natural flow -- the project already collects posts from these actors, and the comment module collects comments on those posts.

#### Mode: `"urls"` (direct URL targeting)

1. Use the `post_urls` list directly from `comments_config`.
2. No database query needed -- the URLs are the input.
3. The comment collection task receives these URLs and fetches comments.
4. For Bright Data platforms (Facebook, Instagram), submit the URLs directly. For native API platforms (YouTube, Bluesky, TikTok, Reddit), extract the platform_id from the URL and use the platform's comment API endpoint.

### 3.4 CollectionTask Records for Comments

Each comment collection dispatch creates a `CollectionTask` row:

```python
CollectionTask(
    collection_run_id=run_id,
    arena=f"{platform}_comments",   # e.g., "facebook_comments"
    platform=platform_name,          # e.g., "facebook"
    status="pending",
)
```

Using `arena = "{platform}_comments"` (rather than the platform's `arena_name` like `"social_media"`) avoids collision with the Phase 1 post collection task for the same platform in the same run. The `platform` column retains the canonical platform name for filtering and reporting.

### 3.5 Post-Collection Hook Integration Point

**File**: `src/issue_observatory/workers/tasks.py`

The existing `trigger_daily_collection` task dispatches arena tasks for each design. After all arena tasks complete for a run, the orchestration layer must invoke comment dispatch. The integration point is `check_all_tasks_terminal()` in `_task_helpers.py`, which is already called to detect run completion.

**Proposed approach**: Add a new Celery task `dispatch_comments_for_run` that is dispatched as a **callback** when the last Phase 1 arena task completes. This avoids polling:

```python
@celery_app.task(name="issue_observatory.workers.tasks.dispatch_comments_for_run")
def dispatch_comments_for_run(collection_run_id: str) -> dict[str, Any]:
    """Dispatch comment collection tasks for a completed post-collection phase.

    Called as a callback when all Phase 1 arena tasks for a run reach terminal state.
    Checks the project's comments_config and dispatches platform-specific comment
    collection tasks for each enabled platform.
    """
```

Each arena task's completion handler (in the individual `tasks.py` files) should check whether it was the **last** task to complete, and if so, dispatch `dispatch_comments_for_run`. The `check_all_tasks_terminal()` helper already provides this check.

### 3.6 Interaction with Live-Tracking Mode

For live-tracking designs (mode="live"), comment collection runs after each daily post-collection cycle completes. The `trigger_daily_collection` Beat task dispatches Phase 1 arena tasks. When they complete, `dispatch_comments_for_run` fires automatically and collects comments on the newly gathered posts.

For batch collections (mode="batch"), comments are collected once after the batch run completes.

### 3.7 Workflow Diagram

```
[Celery Beat: trigger_daily_collection]
    |
    v
[Phase 1: dispatch arena tasks per design]
    |-- facebook.tasks.collect_by_actors
    |-- bluesky.tasks.collect_by_terms
    |-- youtube.tasks.collect_by_actors
    |-- reddit.tasks.collect_by_terms
    ...
    |
    v  (when last Phase 1 task completes)
[dispatch_comments_for_run(run_id)]
    |
    |-- Check project.comments_config
    |-- Resolve target posts per platform
    |-- Filter by min_comments_threshold
    |
    v
[Phase 2: dispatch comment tasks per platform]
    |-- facebook.tasks.collect_comments     (Bright Data)
    |-- instagram.tasks.collect_comments    (Bright Data)
    |-- bluesky.tasks.collect_comments      (AT Protocol API)
    |-- youtube.tasks.collect_comments      (Data API v3)
    |-- reddit.tasks.collect_comments       (asyncpraw)
    |-- tiktok.tasks.collect_comments       (Research API)
    ...
    |
    v  (when last Phase 2 task completes)
[Run marked completed]
```

---

## 4. Per-Platform Implementation

### 4.1 Facebook Comments (Bright Data)

**API**: Bright Data Web Scraper API -- Facebook Comments Scraper
**Dataset ID**: `gd_lkay758p1eanlolqw8`
**Pricing**: $1.50 / 1,000 comment records
**Credential**: Same `platform="brightdata_facebook"`, `tier="medium"` -- no new credential needed

**Config additions** (`arenas/facebook/config.py`):
```python
FACEBOOK_DATASET_ID_COMMENTS: str = "gd_lkay758p1eanlolqw8"
FACEBOOK_COMMENT_COST_PER_1K: float = 1.50
```

**Input format**: JSON array of post URLs:
```json
[
  {"url": "https://www.facebook.com/drnyheder/posts/12345678"},
  {"url": "https://www.facebook.com/drnyheder/posts/87654321"}
]
```

**Output fields** (from Bright Data):
| Bright Data Field | Maps to `content_records` Column | Notes |
|---|---|---|
| `comment_id` | `platform_id` | Unique comment identifier |
| `comment_text` | `text_content` | Comment body text |
| `num_likes` | `likes_count` | |
| `num_replies` | `comments_count` | Count of replies to this comment |
| `date` | `published_at` | Comment timestamp |
| `user_name` | `author_display_name` | MUST be pseudonymized |
| `user_id` | `author_platform_id` | MUST be pseudonymized |
| `user_url` | `raw_metadata.user_url` | MUST be pseudonymized |
| `post_id` | `parent_platform_id` | Links comment to parent post |
| `post_url` | `raw_metadata.parent_post_url` | |
| `replies` | `raw_metadata.replies` | Nested reply objects |

**New task** (`arenas/facebook/tasks.py`):
```
issue_observatory.arenas.facebook.tasks.collect_comments
```

**Implementation approach**: Inherits from the shared Bright Data comment base (Section 5). The platform-specific work is:
1. Resolve post URLs from collected content records (Phase 1 output)
2. Call `BrightDataCommentCollector.collect_comments(post_urls, dataset_id)`
3. Normalize using a `_normalize_facebook_comment()` method

**Max URLs per trigger**: 5,000 (Bright Data limit). For projects with more than 5,000 qualifying posts, batch into multiple triggers.

**GDPR**: ALL commenter identifiers (`user_name`, `user_id`, `user_url`) are pseudonymized. The `public_figure` bypass does NOT apply to commenters.

### 4.2 Instagram Comments (Bright Data)

**API**: Bright Data Web Scraper API -- Instagram Comments Scraper
**Dataset ID**: `gd_ltppn085pokosxh13`
**Pricing**: $1.50 / 1,000 comment records
**Credential**: Same `platform="brightdata_instagram"`, `tier="medium"`

**Config additions** (`arenas/instagram/config.py`):
```python
INSTAGRAM_DATASET_ID_COMMENTS: str = "gd_ltppn085pokosxh13"
INSTAGRAM_COMMENT_COST_PER_1K: float = 1.50
```

**Input format**: JSON array of post URLs:
```json
[
  {"url": "https://www.instagram.com/p/ABC123/"},
  {"url": "https://www.instagram.com/reel/DEF456/"}
]
```

**Output fields**:
| Bright Data Field | Maps to `content_records` Column | Notes |
|---|---|---|
| `comment` | `text_content` | Comment body text |
| `comment_user` | `author_display_name` | MUST be pseudonymized |
| `comment_date` | `published_at` | |
| `likes_number` | `likes_count` | |
| `replies_number` | `comments_count` | Count of replies |
| `user_profile_url` | `raw_metadata.user_profile_url` | MUST be pseudonymized |
| `post_url` | `raw_metadata.parent_post_url` | |
| `post_id` | `parent_platform_id` | Links to parent post |
| `replies` | `raw_metadata.replies` | Nested reply objects |

**URL extraction from collected posts**: Instagram posts collected via Bright Data have a `url` field in the format `https://www.instagram.com/p/{shortcode}/`. This URL is used directly as input to the Comments Scraper.

**New task** (`arenas/instagram/tasks.py`):
```
issue_observatory.arenas.instagram.tasks.collect_comments
```

**Implementation**: Nearly identical to Facebook. Uses the shared Bright Data comment base.

### 4.3 Bluesky Comments (AT Protocol API)

**API endpoint**: `app.bsky.feed.getPostThread`
- URL: `https://bsky.social/xrpc/app.bsky.feed.getPostThread`
- Parameters: `uri={at_uri}&depth={1-1000}&parentHeight=0`
- Authentication: Same session token as post collection
- Rate limit: Shared with post collection (3,000 req / 5 min with auth)

**Config additions** (`arenas/bluesky/config.py`):
```python
BSKY_GET_POST_THREAD_ENDPOINT: str = f"{BSKY_API_BASE}/app.bsky.feed.getPostThread"
DEFAULT_THREAD_DEPTH: int = 6
```

**Response structure**:
```json
{
  "thread": {
    "post": { ... },
    "replies": [
      {
        "post": { ... },
        "replies": [
          { "post": { ... }, "replies": [] }
        ]
      }
    ]
  }
}
```

**Normalization**: Each reply in the thread tree is a standard Bluesky post view. The existing `BlueskyCollector.normalize()` method handles the field mapping. Additional fields:
- `content_type`: `"reply"` (instead of `"post"`)
- `parent_platform_id`: AT URI of the parent post
- `raw_metadata.thread_depth`: Nesting level (0 = direct reply to original post)
- `raw_metadata.root_post_platform_id`: AT URI of the root post

**New method** on `BlueskyCollector`:
```python
async def collect_comments(
    self,
    post_uris: list[str],
    max_depth: int = 6,
) -> list[dict[str, Any]]:
    """Fetch reply threads for a list of Bluesky post URIs."""
```

**New task** (`arenas/bluesky/tasks.py`):
```
issue_observatory.arenas.bluesky.tasks.collect_comments
```

**Deduplication concern**: A reply to a post that ALSO matches the search term may have been collected in Phase 1 as a standalone post. The deduplication pipeline (URL hash + content hash) prevents duplicate storage. The `content_type` should be updated to `"reply"` when thread traversal reveals a previously-collected post is actually a reply.

**Rate limit budget**: For 1,000 posts with 30% having replies, this is ~300 `getPostThread` calls. At 600 req/min (authenticated), this takes ~30 seconds. No budget concern.

**Tier**: FREE (no cost)

### 4.4 YouTube Comments

**Method**: YouTube Data API v3 `commentThreads.list` exclusively. No Bright Data fallback -- the Data API provides generous comment quota (2 units per call vs. 100 units for `search.list`) and the `max_quota_units` parameter prevents comment collection from starving video search.

**API endpoint**: `commentThreads.list`
- URL: `https://www.googleapis.com/youtube/v3/commentThreads`
- Parameters: `videoId={id}&part=snippet,replies&maxResults=100&key={api_key}`
- Quota cost: 2 units per call (paginated)
- Returns: Top-level comments + up to 5 inline replies per comment

For comments with >5 replies, fetch remaining via `comments.list`:
- URL: `https://www.googleapis.com/youtube/v3/comments`
- Parameters: `parentId={comment_id}&part=snippet&maxResults=100&key={api_key}`
- Quota cost: 1 unit per call (paginated)

**Output field mapping**:
| YouTube API Field | Maps to `content_records` Column |
|---|---|
| `snippet.topLevelComment.id` | `platform_id` |
| `snippet.topLevelComment.snippet.textDisplay` | `text_content` |
| `snippet.topLevelComment.snippet.likeCount` | `likes_count` |
| `snippet.topLevelComment.snippet.publishedAt` | `published_at` |
| `snippet.topLevelComment.snippet.authorChannelId.value` | `author_platform_id` |
| `snippet.topLevelComment.snippet.authorDisplayName` | `author_display_name` |
| `snippet.videoId` | `parent_platform_id` |
| `snippet.totalReplyCount` | `comments_count` |

**Quota budget**: For 100 videos averaging 50 comments each:
- `commentThreads.list`: 100 calls * 2 units = 200 units
- `comments.list` (replies): ~50 calls * 1 unit = 50 units
- Total: ~250 units out of 10,000 daily quota per key

**Quota protection**: The `max_quota_units` parameter (default: 3,000, configurable in `comments_config["youtube"]`) caps the total quota units spent on comment collection per run. When the budget is exhausted, the task logs a warning and returns partial results. This ensures video search always retains at least 70% of the daily quota.

**New method** on `YouTubeCollector`:
```python
async def collect_comments(
    self,
    video_ids: list[str],
    max_comments_per_video: int = 100,
    include_replies: bool = True,
    max_quota_units: int = 3000,
) -> list[dict[str, Any]]:
```

**New task** (`arenas/youtube/tasks.py`):
```
issue_observatory.arenas.youtube.tasks.collect_comments
```

**Tier**: FREE (no cost, quota only)

### 4.5 Reddit Comments (asyncpraw)

**Current state**: Reddit already collects top-level comments via `_collect_post_comments()`. The comments module will:
1. Promote this to a configurable Phase 2 task (decoupled from inline comment collection during post search)
2. Add support for nested reply depth beyond `replace_more(limit=0)`

**API**: `asyncpraw` -- `submission.comments.replace_more(limit=N)` + `submission.comments.list()`
- `limit=0`: Only pre-loaded top-level comments (1 API call)
- `limit=N`: Fetch N additional "load more" batches (1 API call each)

**Config-driven depth**: `max_reply_depth` in `comments_config["reddit"]` maps to `replace_more(limit=N)`:
- `max_reply_depth=0` -> `replace_more(limit=0)` (top-level only, current behavior)
- `max_reply_depth=3` -> `replace_more(limit=3)` (3 levels of nested replies)
- The depth filter in `_collect_post_comments()` changes from `depth != 0` to `depth <= max_reply_depth`

**Target post resolution**: For Reddit in targeting mode `"terms"`, the comment task queries posts collected in Phase 1 that matched the configured search terms and have `comments_count >= min_comments_threshold`.

**Existing code reuse**: The `_collect_post_comments()` and `_comment_to_raw()` methods already exist. The comment task wraps them in a new Celery task that:
1. Queries Phase 1 posts from `content_records` for this run
2. Fetches comments for each post via asyncpraw
3. Persists via batch sink

**New task** (`arenas/reddit/tasks.py`):
```
issue_observatory.arenas.reddit.tasks.collect_comments
```

**Change to default behavior**: When the comments module is active, the inline `include_comments` flag on `RedditCollector.__init__()` should default to `False` even if `INCLUDE_COMMENTS_DEFAULT` changes, to avoid double-collecting. Phase 2 handles comment collection instead.

**Rate limit impact**: `replace_more(limit=3)` can add 3 API calls per post. For 500 posts with 30% having comments, this adds ~450 API calls at 90 req/min = ~5 minutes.

**Tier**: FREE

### 4.6 TikTok Comments (Research API)

**Method**: TikTok Research API `video/comment/list` endpoint exclusively. No Bright Data -- the Research API provides comment data at no cost, and a dedicated quota budget prevents comment collection from starving video search.

**API endpoint**: `POST https://open.tiktokapis.com/v2/research/video/comment/list/`
- Authentication: OAuth 2.0 client credentials (same as video search)
- Rate limit: Shared 1,000 req/day global cap across all Research API endpoints
- Returns: Top-level comments for a given video; up to 100 per page, cursor-paginated

**Request body**:
```json
{
  "video_id": 12345,
  "max_count": 100,
  "cursor": 0
}
```

**Response fields** (from `fields` parameter):
- `id`, `text`, `like_count`, `reply_count`, `create_time`
- `parent_comment_id` (for replies to comments)
- Author info requires separate user endpoint (not recommended due to quota cost)

**Output field mapping**:
| Research API Field | Maps to `content_records` Column |
|---|---|
| `id` | `platform_id` |
| `text` | `text_content` |
| `like_count` | `likes_count` |
| `reply_count` | `comments_count` |
| `create_time` | `published_at` (Unix epoch -> datetime) |
| `parent_comment_id` | `raw_metadata.parent_comment_id` |
| video_id (from request) | `parent_platform_id` |

**Author pseudonymization note**: The comment list endpoint does NOT return author usernames or IDs in its standard response. This is actually a GDPR advantage -- no commenter PII is collected. If the API response structure changes to include author fields, those must be pseudonymized per Section 9.1.

**Quota budget**: The 1,000 req/day global cap is shared with video search. The comment collection task enforces a dedicated budget via `max_comment_requests` in `comments_config["tiktok"]`:
- Default: 200 req/day (20% of daily budget reserved for comments)
- This allows fetching comments for up to 200 videos (1 page each) or fewer videos with deeper pagination
- Enforced via a separate rate limit key: `ratelimit:tiktok:research_api:comments:{credential_id}`

**For a typical collection**: 50 videos with comments enabled, averaging 2 pages each = 100 API calls. Well within the 200-request budget.

**Config additions** (`arenas/tiktok/config.py`):
```python
TIKTOK_COMMENT_ENDPOINT: str = "/v2/research/video/comment/list/"
TIKTOK_DEFAULT_COMMENT_QUOTA: int = 200  # max req/day for comments
TIKTOK_COMMENT_PAGE_SIZE: int = 100
```

**New method** on `TikTokCollector`:
```python
async def collect_comments(
    self,
    video_ids: list[int],
    max_comments_per_video: int = 100,
    max_comment_requests: int = 200,
) -> list[dict[str, Any]]:
    """Fetch comments for videos via the Research API comment/list endpoint."""
```

**New task** (`arenas/tiktok/tasks.py`):
```
issue_observatory.arenas.tiktok.tasks.collect_comments
```

**Tier**: FREE (no cost, quota only)

### 4.7 X/Twitter Comments (Phase 2)

**Method**: `conversation_id` search via the existing X/Twitter API access (TwitterAPI.io at MEDIUM tier, or X API v2 at PREMIUM tier). No additional API keys or services needed.

**API approach**: Use the search endpoint already integrated in `x_twitter/collector.py` with the `conversation_id:{tweet_id}` search operator. This returns all tweets in a conversation thread, including direct replies and nested replies.

**Search query construction**:
```
conversation_id:{tweet_id}
```

This operator is supported by both:
- TwitterAPI.io search (MEDIUM tier, existing integration)
- X API v2 Full-Archive Search (PREMIUM tier, if available)

**Output field mapping**: The returned tweets use the same schema as regular tweet collection. The comment-specific additions are:
- `content_type`: `"reply"` (for all conversation replies)
- `parent_platform_id`: The `in_reply_to_tweet_id` field from the tweet object
- `raw_metadata.conversation_id`: The root tweet ID
- `raw_metadata.thread_depth`: Inferred from reply chain length

**Implementation notes**:
- The existing `XTwitterCollector._search_term()` method can be reused with `conversation_id` queries
- Each target post requires one search query (paginated if the conversation is large)
- Deduplication: replies that also match the project's search terms may already exist from Phase 1 collection

**Rate limit impact**: Each `conversation_id` query consumes one search request. For 200 qualifying posts, this adds 200 search requests to the daily usage. The existing rate limiter (`ratelimit:x_twitter:{credential_id}`) governs this.

**Cost**: Depends on existing tier -- $0 if using FREE tier (limited), standard search pricing at MEDIUM tier via TwitterAPI.io.

**New task** (`arenas/x_twitter/tasks.py`):
```
issue_observatory.arenas.x_twitter.tasks.collect_comments
```

**Tier**: MEDIUM (uses existing X/Twitter API access)

### 4.8 Telegram Comments (Deferred to Phase 2)

Requires resolving linked discussion groups. Moderate engineering effort. Deferred to Phase 2.

### 4.9 Gab Comments (Phase 2)

**Method**: Mastodon-compatible API endpoint `/api/v1/statuses/{id}/context`. Trivial to implement given Gab's Mastodon API compatibility.

**API endpoint**: `GET https://gab.com/api/v1/statuses/{status_id}/context`
- Authentication: Bearer token (existing `gab` credential)
- Returns: `ancestors` (parent posts) and `descendants` (replies)

**Output field mapping**: Identical to Bluesky thread traversal -- each descendant is normalized to a content record with `content_type = "reply"` and `parent_platform_id` set to the replied-to status ID.

**Danish relevance**: Low. Gab has minimal Danish user presence. However, the implementation is trivial (1-2 hours of engineering effort) and uses the free API, so there is no cost argument for deferral.

**New task** (`arenas/gab/tasks.py`):
```
issue_observatory.arenas.gab.tasks.collect_comments
```

**Tier**: FREE

### 4.10 Platform Support Summary

| Platform | Phase | Method | Tier | Cost per 1K comments | New credential needed? |
|---|---|---|---|---|---|
| Facebook | **Phase 1** | Bright Data Comments Scraper | MEDIUM | $1.50 | No |
| Instagram | **Phase 1** | Bright Data Comments Scraper | MEDIUM | $1.50 | No |
| Bluesky | **Phase 1** | AT Protocol `getPostThread` | FREE | $0 | No |
| Reddit | **Phase 1** | asyncpraw `replace_more()` | FREE | $0 | No |
| YouTube | **Phase 1** | Data API v3 `commentThreads.list` | FREE | $0 (quota) | No |
| TikTok | **Phase 1** | Research API `video/comment/list` | FREE | $0 (quota) | No |
| X/Twitter | **Phase 2** | `conversation_id` search | MEDIUM | varies | No |
| Telegram | **Phase 2** | Telethon `get_messages(reply_to=)` | FREE | $0 | No |
| Gab | **Phase 2** | Mastodon `/statuses/{id}/context` | FREE | $0 | No |
| Threads | Phase 3 | Meta Content Library (blocked on MCL approval) | FREE | $0 | No |

**Key change from v1**: Only Facebook and Instagram use Bright Data (paid). All other platforms use their native free APIs, reducing the paid comment collection footprint from 4 platforms to 2. TikTok moved from Phase 2 (Bright Data) to Phase 1 (Research API). X/Twitter and Gab moved from Phase 3 to Phase 2.

---

## 5. Shared Bright Data Comment Module

### 5.1 Design Rationale

Facebook and Instagram are the only two platforms using Bright Data for comment collection (all other platforms use their native free APIs). Both use the identical Bright Data trigger/poll/download pattern with the same pricing ($1.50/1K comments). The existing codebase already duplicates this trigger/poll/download pattern between `facebook/collector.py` and `instagram/collector.py` for post collection. A shared comment module prevents adding two more copies of the same pattern for comment scrapers.

**Scope note**: This module is intentionally limited to 2 platforms. If future platforms require Bright Data comment scrapers, this module can accommodate them, but the current design prioritizes native free APIs wherever possible.

### 5.2 Module Location

**New file**: `src/issue_observatory/arenas/_brightdata_comments.py`

This is a shared internal module (prefixed with `_`) used by individual arena collectors. It is NOT a registered arena -- it provides base functionality.

### 5.3 Class Design

```python
class BrightDataCommentCollector:
    """Shared base for Bright Data Comment Scraper integrations.

    Handles the trigger/poll/download lifecycle for any Bright Data Comment
    Scraper dataset. Platform-specific normalizers are injected by subclasses.

    Attributes:
        dataset_id: The Bright Data dataset ID for the comment scraper.
        platform_name: The platform name for logging and credential lookup.
        credential_platform: The credential pool platform key (e.g., "brightdata_facebook").
    """

    def __init__(
        self,
        dataset_id: str,
        platform_name: str,
        credential_platform: str,
        credential_pool: CredentialPool | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None: ...

    async def collect_comments(
        self,
        post_urls: list[str],
        max_urls_per_trigger: int = 5000,
    ) -> list[dict[str, Any]]:
        """Trigger Bright Data comment scraper and poll for results.

        Batches URLs into groups of max_urls_per_trigger (5,000 max per BD API).
        Uses the same trigger/poll/download flow as existing post collectors.

        Args:
            post_urls: List of post/video URLs to collect comments from.
            max_urls_per_trigger: Maximum URLs per Bright Data trigger call.

        Returns:
            List of raw comment dicts from Bright Data.
        """

    async def _trigger_snapshot(
        self,
        client: httpx.AsyncClient,
        urls: list[str],
        api_token: str,
    ) -> str:
        """Submit URLs to Bright Data and return snapshot_id."""

    async def _poll_progress(
        self,
        client: httpx.AsyncClient,
        snapshot_id: str,
        api_token: str,
    ) -> bool:
        """Poll Bright Data progress endpoint. Returns True when ready."""

    async def _download_snapshot(
        self,
        client: httpx.AsyncClient,
        snapshot_id: str,
        api_token: str,
    ) -> list[dict[str, Any]]:
        """Download completed snapshot as JSON."""
```

### 5.4 Shared Configuration Constants

These constants are already defined in `facebook/config.py` and `instagram/config.py` with identical values. They should be consolidated into the shared module or into a common Bright Data config:

```python
BRIGHTDATA_API_BASE: str = "https://api.brightdata.com/datasets/v3"
BRIGHTDATA_COMMENT_TRIGGER_URL: str = f"{BRIGHTDATA_API_BASE}/trigger?dataset_id={{dataset_id}}&include_errors=true"
BRIGHTDATA_PROGRESS_URL: str = f"{BRIGHTDATA_API_BASE}/progress/{{snapshot_id}}"
BRIGHTDATA_SNAPSHOT_URL: str = f"{BRIGHTDATA_API_BASE}/snapshot/{{snapshot_id}}?format=json"
BRIGHTDATA_POLL_INTERVAL: int = 30
BRIGHTDATA_MAX_POLL_ATTEMPTS: int = 40
BRIGHTDATA_RATE_LIMIT_MAX_CALLS: int = 2
BRIGHTDATA_RATE_LIMIT_WINDOW_SECONDS: int = 1
BRIGHTDATA_COMMENT_COST_PER_1K: float = 1.50
```

### 5.5 Platform-Specific Normalizers

Each Bright Data platform provides a normalizer method that maps Bright Data's comment fields to the universal content record schema. These are injected into the base class:

```python
# In facebook/collector.py (or a new facebook/_comment_normalizer.py)
def normalize_facebook_comment(raw: dict[str, Any], normalizer: Normalizer) -> dict[str, Any]:
    """Map a Bright Data Facebook comment to the universal schema."""

# In instagram/collector.py (or a new instagram/_comment_normalizer.py)
def normalize_instagram_comment(raw: dict[str, Any], normalizer: Normalizer) -> dict[str, Any]:
    """Map a Bright Data Instagram comment to the universal schema."""
```

Only these two normalizers are needed. YouTube, TikTok, Bluesky, Reddit, X/Twitter, Gab, and Telegram all use their native APIs and have platform-specific normalization within their own collector modules.

### 5.6 Integration Pattern Per Arena

Each arena that uses Bright Data comments (currently only Facebook and Instagram) adds:

1. **Config constant**: `{PLATFORM}_DATASET_ID_COMMENTS` in `{platform}/config.py`
2. **Comment normalizer**: A function or method mapping BD fields to universal schema
3. **Celery task**: `{platform}/tasks.py::collect_comments` that:
   a. Creates a `BrightDataCommentCollector` instance with the platform's dataset ID
   b. Resolves post URLs from Phase 1 content records
   c. Calls `collect_comments(post_urls)`
   d. Normalizes and persists via batch sink

All other platforms (YouTube, TikTok, Bluesky, Reddit, X/Twitter, Gab, Telegram) implement their own `collect_comments` Celery task using their native API clients directly, without the shared Bright Data module.

### 5.7 Error Handling

Bright Data comment scrapers use the same error semantics as post scrapers:
- **Snapshot delivery failure**: Retry up to `BRIGHTDATA_MAX_POLL_ATTEMPTS` (40 * 30s = 20 min)
- **Per-URL errors**: Bright Data returns `include_errors=true` errors per URL. These are logged via `record_url_errors()` (existing pattern from Facebook/Instagram post collection).
- **Rate limit**: Courtesy throttle at 2 req/sec. Bright Data handles proxy rotation internally.
- **Credential failure**: `NoCredentialAvailableError` -> task fails immediately.

---

## 6. Configuration UI Flow

### 6.1 Location in the UI

Comment collection settings live on the **Project Detail page** (`/projects/{project_id}`). A new "Comments" tab or expandable section is added alongside the existing project info and query design list.

**Template file**: `src/issue_observatory/api/templates/projects/detail.html`

### 6.2 UI Design

The comments configuration panel has:

1. **Platform toggle cards** -- one card per commentable platform. Each card shows:
   - Platform name and icon
   - Enable/disable toggle (Alpine.js `x-data`)
   - When enabled, a targeting mode selector and associated controls

2. **Targeting mode selector** (radio buttons per platform):
   - **"Match search terms"** -- shows a multi-select of search terms from the project's query designs
   - **"Match actor lists"** -- shows a multi-select of actor lists from the project's query designs
   - **"Specific post URLs"** -- shows a textarea for pasting URLs

3. **Advanced options** (collapsible per platform):
   - `max_comments_per_post` (number input)
   - `max_thread_depth` (number input, for Bluesky/Reddit)
   - `include_replies` (checkbox, for Bright Data platforms: Facebook/Instagram)
   - `min_comments_threshold` (number input, cost optimization -- primarily for Facebook/Instagram)
   - `max_quota_units` (number input, for YouTube -- caps daily API quota spent on comments)
   - `max_comment_requests` (number input, for TikTok -- caps daily Research API requests for comments)

4. **Cost estimate** (computed client-side):
   - Based on the number of qualifying posts in recent collection runs and the platform's cost per 1K comments
   - Displayed as "Estimated monthly cost: ~$XX" per platform

### 6.3 HTMX Save Mechanism

The comments config is saved via a `PATCH` request to a new endpoint:

```
PATCH /projects/{project_id}/comments-config
Content-Type: application/json

{
  "facebook": { "enabled": true, "targeting_mode": "actors", ... },
  "bluesky": { "enabled": true, "targeting_mode": "terms", ... }
}
```

**Route** (`src/issue_observatory/api/routes/projects.py`):
```python
@router.patch("/{project_id}/comments-config")
async def update_comments_config(
    project_id: uuid.UUID,
    comments_config: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Update the project's comment collection configuration."""
```

This endpoint validates the config against the `CommentsConfig` Pydantic schema, verifies that referenced `actor_list_ids` and `search_term_ids` belong to query designs within this project, and persists to `Project.comments_config`.

### 6.4 Search Term and Actor List Resolution

The UI needs to display searchable lists of:

**Search terms**: Aggregated from all `QueryDesign` instances attached to the project:
```python
terms = (
    select(SearchTerm)
    .join(QueryDesign)
    .where(QueryDesign.project_id == project_id, SearchTerm.is_active.is_(True))
)
```

**Actor lists**: From the project directly (`Project.actor_lists`) and from attached query designs:
```python
actor_lists = (
    select(ActorList)
    .where(
        (ActorList.project_id == project_id) |
        (ActorList.query_design_id.in_(
            select(QueryDesign.id).where(QueryDesign.project_id == project_id)
        ))
    )
)
```

These are fetched via new API endpoints:
```
GET /projects/{project_id}/available-terms    -> list of SearchTerm summaries
GET /projects/{project_id}/available-actors   -> list of ActorList summaries
```

### 6.5 Platform Availability

Not all platforms support comment collection. The UI should show only platforms that:
1. Are registered in the arena registry
2. Have comment collection implemented (tracked via a new class attribute on `ArenaCollector`)
3. Are enabled in the project's `arenas_config`

**Proposed attribute** on `ArenaCollector`:
```python
supports_comment_collection: bool = False
```

Set to `True` on platforms that implement `collect_comments()`.

---

## 7. Cost and Rate Limit Management

### 7.1 Credit Cost Estimation

The `dispatch_comments_for_run` orchestration function estimates comment collection credits BEFORE dispatching tasks. Credit estimation only applies to **Facebook and Instagram** (the only Bright Data platforms). All other platforms use free APIs and incur no monetary cost.

**Estimation formula** (Facebook/Instagram only):
```
estimated_credits = (qualifying_posts * avg_comments_per_post * cost_per_comment)
```

Where:
- `qualifying_posts`: Count of posts from Phase 1 that pass the `min_comments_threshold` filter
- `avg_comments_per_post`: Platform-specific heuristic based on the `comments_count` values from Phase 1 posts (use the median of non-zero values, capped at `max_comments_per_post`)
- `cost_per_comment`: $0.0015 (Bright Data pricing: $1.50 / 1,000 comments)

A `CreditTransaction` with `transaction_type="reservation"` is created before dispatch, following the existing pattern.

**Reference scenario cost estimate**: A project tracking 30 Facebook pages + 20 Instagram accounts, with `min_comments_threshold=5`:
- Facebook: ~200 qualifying posts/day * 25 avg comments = 5,000 comments * $0.0015 = ~$7.50/day = ~$225/month
- Instagram: ~150 qualifying posts/day * 15 avg comments = 2,250 comments * $0.0015 = ~$3.38/day = ~$101/month
- All other platforms: $0
- **Total: ~$326/month** (v1 estimate was ~$504/month before TikTok/YouTube Bright Data removal)

For cost-sensitive projects, raising `min_comments_threshold` to 10 reduces qualifying posts by ~40-60%, bringing the estimate to ~$130-$195/month.

### 7.2 Rate Limit Budget Allocation

#### YouTube Data API Quota

YouTube comments use the Data API v3 exclusively. The quota budget is shared with video search:

- Daily quota per key: 10,000 units
- `search.list`: 100 units/call
- `videos.list`: 1 unit/50 videos
- `commentThreads.list`: 2 units/call
- `comments.list` (replies): 1 unit/call

**Budget allocation**: The comment collection task should track cumulative quota usage and stop when a configurable threshold is reached (default: 30% of daily quota = 3,000 units for comments).

This is implemented as a `max_quota_units` parameter on the YouTube comment collection method:
```python
async def collect_comments(
    self,
    video_ids: list[str],
    ...
    max_quota_units: int = 3000,
) -> list[dict[str, Any]]:
```

#### TikTok Research API

The 1,000 req/day global cap is shared across ALL Research API endpoints (video search, video detail, and comment list). The comment collection task enforces a dedicated budget via `max_comment_requests` (default: 200, i.e., 20% of the daily budget):

```
ratelimit:tiktok:research_api:comments:{credential_id}
```

This rate limit key is separate from the video search key, allowing independent tracking of comment vs. search quota consumption. The task stops collecting when the budget is exhausted and logs partial completion. The remaining 80% of quota (800 req/day) is reserved for video search operations.

**Capacity at default budget**: 200 requests * 100 comments/page = up to 20,000 comments/day across all target videos.

#### Bluesky

3,000 req / 5 min with authentication. Comment collection adds ~300 requests for 1,000 posts. No special budgeting needed.

#### Reddit

100 req/min shared with post collection. Comment collection adds ~1-3 calls per post. For large collections, the task should yield to the rate limiter between posts.

### 7.3 Cost Optimization: `min_comments_threshold`

The `min_comments_threshold` parameter in `comments_config` serves two purposes depending on the platform:

**For paid platforms (Facebook, Instagram)**: This is the primary cost lever. Setting it to 5 means "only collect comments for posts that have 5+ comments." This:
- Reduces the number of Bright Data triggers (each trigger costs based on URLs submitted)
- Focuses comment collection on posts that actually generated discussion
- For a project tracking 50 Facebook pages: setting threshold from 1 to 5 typically reduces qualifying posts by 40-60%, directly reducing Bright Data costs

**For free-but-quota-limited platforms (YouTube, TikTok)**: The threshold conserves API quota rather than money. Skipping low-comment posts means fewer API calls, leaving more quota for high-value targets.

**For unlimited free platforms (Bluesky, Reddit, Gab)**: The threshold still improves collection efficiency by skipping posts with negligible discussion, but there is no cost or quota pressure.

**Default**: 1 (collect for all posts with at least one comment)
**Recommended for cost-sensitive projects**: 5-10 (primarily affects Facebook/Instagram costs)

### 7.4 Cost Reporting

The existing `CreditTransaction` model tracks costs. Comments generate transactions with:
- `transaction_type = "settlement"`
- `arena = "{platform}_comments"` (distinguishes from post collection costs)
- `platform = "{platform}"`
- `description = "Comment collection: {N} URLs, {M} comments"`

The project detail page and the analysis dashboard should show comment collection costs separately from post collection costs. This requires filtering `CreditTransaction` rows where `arena` ends with `"_comments"`.

---

## 8. Phased Rollout

### Phase 1: MVP (Weeks 1-3)

**Scope**: Core infrastructure + 6 platforms (4 free API + 2 Bright Data)

| Component | Effort | Owner |
|---|---|---|
| **Migration 032**: Add `parent_platform_id` to `content_records`, `comments_config` to `projects` | Small | DB Engineer |
| **Pydantic schema**: `CommentsConfigPlatform`, `CommentsConfig` | Small | DB Engineer |
| **Shared Bright Data comment module**: `_brightdata_comments.py` (2-platform scope) | Small | Core Engineer |
| **Facebook comments**: Config constant + normalizer + task | Small | Core Engineer |
| **Instagram comments**: Config constant + normalizer + task | Small | Core Engineer |
| **Bluesky comments**: `getPostThread` method + normalizer + task | Small | Core Engineer |
| **Reddit comments**: Phase 2 task decoupling + depth config | Small | Core Engineer |
| **YouTube comments**: Data API v3 `commentThreads.list` method + normalizer + task | Moderate | Core Engineer |
| **TikTok comments**: Research API `video/comment/list` method + normalizer + task | Moderate | Core Engineer |
| **Comment orchestrator**: `dispatch_comments_for_run` + post-completion hook | Moderate | Core Engineer |
| **UI**: Comments config panel on project detail page | Moderate | Frontend Agent |
| **API endpoints**: `PATCH /projects/{id}/comments-config`, `GET /projects/{id}/available-terms`, `GET /projects/{id}/available-actors` | Small | Core Engineer |
| **Tests**: Unit tests for normalizers, integration tests for orchestrator | Moderate | QA Engineer |

**Milestone**: A researcher can enable comment collection for Facebook, Instagram, Bluesky, Reddit, YouTube, and TikTok on a project, and comments are automatically collected after each post-collection run.

**Estimated monthly cost at MVP**: Only Facebook and Instagram incur Bright Data costs. For a reference scenario (30 FB pages + 20 IG accounts, threshold=5): ~$326/month. All other platforms: $0.

### Phase 2: Expansion (Weeks 4-6)

| Component | Effort | Owner |
|---|---|---|
| **X/Twitter comments**: `conversation_id` search via existing API access | Moderate | Core Engineer |
| **Telegram comments**: Discussion group resolution + reply fetch | Moderate | Core Engineer |
| **Gab comments**: Mastodon `/statuses/{id}/context` endpoint | Small | Core Engineer |
| **Cost estimation UI**: Per-platform cost forecasts on config panel | Moderate | Frontend Agent |
| **Comment analytics**: Descriptive stats for comments in analysis module | Moderate | Core Engineer |
| **Thread visualization**: Comment thread tree view on content detail page | Moderate | Frontend Agent |
| **Backfill for Reddit**: Populate `parent_platform_id` from `raw_metadata` | Small | DB Engineer |

### Phase 3: Advanced (Weeks 7+)

| Component | Effort | Owner |
|---|---|---|
| **Threads comments**: MCL integration (blocked on MCL approval) | Moderate | Core Engineer |
| **Comment sentiment enrichment**: NLP pipeline for comment tone | Large | Core Engineer |
| **Comment network analysis**: Commenter interaction graphs | Large | Core Engineer |
| **Selective re-collection**: Re-scrape comments for posts with new comments since last scrape | Moderate | Core Engineer |

### MVP Definition

The MVP is complete when:
- [ ] A researcher can toggle comment collection ON for Facebook, Instagram, Bluesky, Reddit, YouTube, or TikTok on a project
- [ ] The researcher can choose targeting mode (terms, actors, or URLs) per platform
- [ ] After a post-collection run completes, comments are automatically collected for qualifying posts
- [ ] Comments appear in the content records table with correct `content_type`, `parent_platform_id`, and pseudonymized author identifiers
- [ ] Comment collection costs are tracked in `CreditTransaction` (for Facebook/Instagram Bright Data usage)
- [ ] The project detail page shows comment collection configuration
- [ ] Comments are visible in the content list alongside posts

---

## 9. GDPR and Legal Compliance

### 9.1 Pseudonymization

ALL comment authors are treated as private individuals. The `public_figure` bypass (GR-14, GDPR Art. 89(1)) does NOT apply to commenters, even when commenting on a public figure's post. This means:

- `author_platform_id` -> SHA-256(PSEUDONYMIZATION_SALT + platform + commenter_id)
- `author_display_name` -> SHA-256(PSEUDONYMIZATION_SALT + platform + display_name)
- All additional author identifiers in `raw_metadata` (e.g., `user_url`, `user_profile_url`) must also be pseudonymized before storage

The `Normalizer.normalize()` method already handles pseudonymization. Comment normalizers must NOT pass commenter IDs in the `public_figure_ids` set, even if the commenter happens to be a public figure (their comment is collected in the context of replying, not in the context of being a monitored public figure).

### 9.2 Retention

Comments are subject to the same retention policies as posts. The `enforce_retention_policy` Beat task already deletes `content_records` older than the configured retention window. No changes needed.

### 9.3 Right of Erasure

If a data subject exercises their GDPR right of erasure (Art. 17), their comments must be deletable. Since comments are stored in `content_records` with `pseudonymized_author_id`, erasure requests are processed by:
1. Computing the pseudonymized ID from the subject's claimed platform identity
2. Deleting all `content_records` where `pseudonymized_author_id = :hash`

This existing mechanism works for comments without modification.

### 9.4 Platform Terms of Service

The feasibility report (Section 7) provides a detailed legal analysis per platform. Summary:
- **Bright Data platforms** (Facebook, Instagram only): Bright Data assumes platform-access compliance. The project must ensure GDPR pseudonymization.
- **Direct API platforms** (Bluesky, Reddit, YouTube Data API, TikTok Research API, X/Twitter, Gab, Telegram): API Terms of Service generally permit comment collection for research purposes. The TikTok Research API explicitly requires approved research use cases.
- **DSA Article 40**: Comment collection falls within the scope of researcher access for VLOPs (Facebook, Instagram, TikTok, YouTube, X/Twitter are all designated VLOPs).

### 9.5 Data Minimization

The `min_comments_threshold` and `max_comments_per_post` parameters serve as data minimization controls (GDPR Art. 5(1)(c)). Researchers should be encouraged to set reasonable limits rather than collecting all comments indiscriminately.

---

## 10. Open Questions for Team Discussion

### For DB Engineer

1. **Partitioned table index**: The `parent_platform_id` index on `content_records` will be inherited by all monthly partitions. Is there a performance concern with adding another B-tree index to this already heavily-indexed partitioned table?

2. **Backfill migration**: Should the migration backfill `parent_platform_id` from `raw_metadata->>'parent_post_id'` for existing Reddit comments? This is a potentially expensive operation on a large partitioned table.

3. **Phase 2 comment `CollectionTask.arena` naming**: Using `"{platform}_comments"` (e.g., `"facebook_comments"`) avoids collision with post tasks but introduces a new naming convention. Is there a better approach? Alternatives: add a `task_type` column (`"post"` vs `"comment"`), or use `arena = "social_media"` with `platform = "facebook_comments"`.

### For Core Engineer

4. **Post-completion hook**: The proposed callback pattern (each arena task checks `check_all_tasks_terminal()` on completion and dispatches `dispatch_comments_for_run`) may cause a race condition if two tasks complete simultaneously. Should we use a Redis lock or a Celery chord instead?

5. **Bright Data module extraction**: With only Facebook and Instagram using Bright Data for comments, the shared `_brightdata_comments.py` module is relatively small (2 platform normalizers). Should we go further and extract the existing Bright Data trigger/poll/download pattern from `facebook/collector.py` and `instagram/collector.py` into a general `_brightdata_base.py` that handles both post and comment scrapers? This would reduce the existing duplication across 4 Bright Data integrations (FB posts, IG posts, FB comments, IG comments) but may be over-engineering for the current 2-platform comment scope.

6. **ArenaCollector ABC changes**: Adding `supports_comment_collection: bool` and potentially `collect_comments()` as an optional method on `ArenaCollector` changes the ABC interface. Should this be a separate `CommentCollector` mixin class instead?

### For Frontend Agent

7. **UI placement**: Should comments config be a new tab on the project detail page, a collapsible section within the existing page, or a separate settings page?

8. **Actor list / search term selection**: The multi-select for actor lists and search terms could be a checkbox list, a tag-input field, or a transfer list (available -> selected). Which pattern fits the existing UI best?

### For QA Engineer

9. **Test strategy**: Comment collection involves cross-task coordination (Phase 1 completion triggers Phase 2). What is the best approach for integration testing this workflow -- a full end-to-end test with mock APIs, or isolated unit tests for the orchestrator?

### For the Whole Team

10. **"comments" naming**: The codebase currently uses `content_type = "comment"` for top-level comments and `content_type = "reply"` for nested replies (following Reddit's convention). Should we standardize on `"comment"` for ALL levels and use `raw_metadata.thread_depth` to distinguish? Or keep the `"comment"` / `"reply"` distinction? The Bluesky feasibility assessment uses `"reply"` for all thread replies, while Reddit uses `"comment"` for top-level.

**Proposed convention**:
- `content_type = "comment"` -- a top-level response to a post
- `content_type = "reply"` -- a response to a comment (nested)
- Both have `parent_platform_id` set

11. **Scope creep guard**: Should comment collection be limited to the three targeting modes described (terms, actors, URLs), or should we also support "collect comments for ALL posts in this run" as a fourth mode (effectively a checkbox that skips targeting resolution)?

---

## File Reference

All file paths below are absolute from the repository root (`/home/jakobbaek/codespace/issue_observatory/issue_obervatory/`).

### Files to Create

| File | Owner | Description |
|---|---|---|
| `alembic/versions/032_add_parent_platform_id.py` | DB Engineer | Migration adding `parent_platform_id` to `content_records` and `comments_config` to `projects` |
| `src/issue_observatory/arenas/_brightdata_comments.py` | Core Engineer | Shared Bright Data comment collection module |
| `src/issue_observatory/workers/_comment_orchestrator.py` | Core Engineer | Comment collection orchestration (dispatch_comments_for_run) |

### Files to Modify

| File | Owner | Changes |
|---|---|---|
| `src/issue_observatory/core/models/content.py` | DB Engineer | Add `parent_platform_id` column |
| `src/issue_observatory/core/models/project.py` | DB Engineer | Add `comments_config` JSONB column |
| `src/issue_observatory/core/models/__init__.py` | DB Engineer | No model changes needed (same models) |
| `src/issue_observatory/core/schemas/project.py` | DB Engineer | Add `CommentsConfigPlatform`, `CommentsConfig` Pydantic models |
| `src/issue_observatory/arenas/base.py` | Core Engineer | Add `supports_comment_collection: bool = False` |
| `src/issue_observatory/arenas/facebook/config.py` | Core Engineer | Add `FACEBOOK_DATASET_ID_COMMENTS` |
| `src/issue_observatory/arenas/facebook/tasks.py` | Core Engineer | Add `collect_comments` task |
| `src/issue_observatory/arenas/instagram/config.py` | Core Engineer | Add `INSTAGRAM_DATASET_ID_COMMENTS` |
| `src/issue_observatory/arenas/instagram/tasks.py` | Core Engineer | Add `collect_comments` task |
| `src/issue_observatory/arenas/bluesky/config.py` | Core Engineer | Add `BSKY_GET_POST_THREAD_ENDPOINT`, `DEFAULT_THREAD_DEPTH` |
| `src/issue_observatory/arenas/bluesky/collector.py` | Core Engineer | Add `collect_comments()` method |
| `src/issue_observatory/arenas/bluesky/tasks.py` | Core Engineer | Add `collect_comments` task |
| `src/issue_observatory/arenas/reddit/collector.py` | Core Engineer | Refactor `_collect_post_comments()` for configurable depth |
| `src/issue_observatory/arenas/reddit/tasks.py` | Core Engineer | Add `collect_comments` task |
| `src/issue_observatory/arenas/youtube/collector.py` | Core Engineer | Add `collect_comments()` method |
| `src/issue_observatory/arenas/youtube/tasks.py` | Core Engineer | Add `collect_comments` task |
| `src/issue_observatory/arenas/tiktok/config.py` | Core Engineer | Add `TIKTOK_COMMENT_ENDPOINT`, `TIKTOK_DEFAULT_COMMENT_QUOTA`, `TIKTOK_COMMENT_PAGE_SIZE` |
| `src/issue_observatory/arenas/tiktok/collector.py` | Core Engineer | Add `collect_comments()` method using Research API `video/comment/list` |
| `src/issue_observatory/arenas/tiktok/tasks.py` | Core Engineer | Add `collect_comments` task |
| `src/issue_observatory/arenas/x_twitter/collector.py` | Core Engineer | Add `collect_comments()` method using `conversation_id` search (Phase 2) |
| `src/issue_observatory/arenas/x_twitter/tasks.py` | Core Engineer | Add `collect_comments` task (Phase 2) |
| `src/issue_observatory/arenas/gab/collector.py` | Core Engineer | Add `collect_comments()` method using Mastodon `/context` endpoint (Phase 2) |
| `src/issue_observatory/arenas/gab/tasks.py` | Core Engineer | Add `collect_comments` task (Phase 2) |
| `src/issue_observatory/arenas/telegram/collector.py` | Core Engineer | Add `collect_comments()` method for discussion group replies (Phase 2) |
| `src/issue_observatory/arenas/telegram/tasks.py` | Core Engineer | Add `collect_comments` task (Phase 2) |
| `src/issue_observatory/workers/tasks.py` | Core Engineer | Add post-completion hook for comment dispatch |
| `src/issue_observatory/workers/_task_helpers.py` | Core Engineer | Add helpers for target post resolution |
| `src/issue_observatory/api/routes/projects.py` | Core Engineer | Add `PATCH /comments-config`, `GET /available-terms`, `GET /available-actors` |
| `src/issue_observatory/api/templates/projects/detail.html` | Frontend Agent | Add comments configuration panel |

### Files Unchanged

| File | Reason |
|---|---|
| `src/issue_observatory/arenas/registry.py` | No registry changes needed (comment tasks are not new arenas) |
| `src/issue_observatory/core/normalizer.py` | Existing pseudonymization works for comments |
| `src/issue_observatory/core/models/collection.py` | Existing `CollectionTask` model works for comment tasks |
