# Zeeschuimer-to-4CAT Protocol: Technical Specification for IO Receiver Endpoint

**Created**: 2026-02-21
**Last updated**: 2026-02-21
**Author**: Research Agent
**Status**: Complete
**Sources examined**:
- Zeeschuimer v1.13.6: https://github.com/digitalmethodsinitiative/zeeschuimer (commit at HEAD as of 2026-02-21)
- 4CAT: https://github.com/digitalmethodsinitiative/4cat (commit at HEAD as of 2026-02-21)

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-21 | Initial specification created from source code analysis |

---

## 1. Executive Summary

This document specifies the exact HTTP protocol that the Zeeschuimer browser extension uses to upload captured data to a 4CAT server instance. It is written so that the Issue Observatory can implement a compatible receiver endpoint, allowing Zeeschuimer to send data directly to IO without requiring 4CAT as an intermediary.

The protocol is straightforward: a single POST request carrying an NDJSON body with a custom platform header, authenticated via browser session cookies (for 4CAT) or an access token. The IO receiver should accept the same request format but use its own authentication mechanism (JWT bearer token or API key).

**Key findings**:
- The upload is a single HTTP POST to `/api/import-dataset/` with the raw NDJSON body (not multipart form data)
- Platform identification is via the `X-Zeeschuimer-Platform` header
- Each NDJSON line is a complete Zeeschuimer item record containing metadata envelope fields plus a nested `data` object with the raw platform JSON
- Authentication in 4CAT relies on browser session cookies; an `access-token` query parameter is also supported
- After upload, 4CAT returns a dataset key for polling progress; IO can simplify this to synchronous processing

---

## 2. The Upload Protocol (Zeeschuimer Side)

### 2.1 How Zeeschuimer Stores Captured Items

Zeeschuimer uses a Dexie.js (IndexedDB wrapper) database named `zeeschuimer-items` with the following schema:

```javascript
// Database schema (version 2)
items: "++id, item_id, nav_index, source_platform, last_updated,
        [item_id+source_platform+last_updated]"
uploads: "++id"
nav: "++id, tab_id, session"
settings: "key"
```

Each captured item is stored with these envelope fields:

| Field | Type | Description |
|-------|------|-------------|
| `id` | Auto-increment integer | Dexie internal PK |
| `nav_index` | String | Session:tab:navigation-index for deduplication (e.g., `"3:42:7"`) |
| `item_id` | String | Platform-specific content identifier (e.g., LinkedIn URN, tweet ID) |
| `timestamp_collected` | Integer | Unix epoch in **milliseconds** when first captured |
| `last_updated` | Integer | Unix epoch in **milliseconds** when last updated |
| `source_platform` | String | Module identifier (see Section 2.3 for complete list) |
| `source_platform_url` | String | URL of the tab/page the user was viewing when the item was captured |
| `source_url` | String | URL of the HTTP request whose response contained the data |
| `user_agent` | String | Browser user agent string at capture time |
| `data` | Object | Raw platform JSON as parsed by the platform module |

### 2.2 NDJSON Serialization

When uploading (or exporting to file), Zeeschuimer serializes each item from the database directly via `JSON.stringify(item)`, one item per line:

```javascript
// From popup/interface.js
async function get_blob(platform) {
    let ndjson = [];
    await iterate_items(platform, function(item) {
        ndjson.push(JSON.stringify(item) + "\n");
    });
    return new Blob(ndjson, {type: 'application/x-ndjson'});
}
```

Each line in the NDJSON file therefore has this structure:

```json
{
  "id": 1234,
  "nav_index": "3:42:7",
  "item_id": "urn:li:fs_updateV2:(urn:li:activity:7293847561234567890,...)",
  "timestamp_collected": 1740100000000,
  "last_updated": 1740100000000,
  "source_platform": "linkedin.com",
  "source_platform_url": "https://www.linkedin.com/feed/",
  "source_url": "https://www.linkedin.com/voyager/api/feed/updatesV2?...",
  "user_agent": "Mozilla/5.0 ...",
  "data": {
    "actor": { ... },
    "commentary": { ... },
    "content": { ... },
    "*socialDetail": { ... },
    "id": "urn:li:fs_updateV2:(urn:li:activity:7293847561234567890,...)"
  }
}
```

**Critical implementation note**: The `data` field contains the raw platform-specific JSON. The outer envelope fields (`timestamp_collected`, `source_platform`, `source_platform_url`, `source_url`, `user_agent`) are Zeeschuimer metadata. When 4CAT ingests this, it restructures it so the `data` contents become the top-level object and the envelope fields become `__import_meta`:

```python
# From 4CAT backend/lib/search.py, import_from_file()
new_item = {
    **item["data"],
    "__import_meta": {k: v for k, v in item.items() if k != "data"}
}
```

### 2.3 Platform Module Identifiers

The `source_platform` field (and the `X-Zeeschuimer-Platform` header value) is the module identifier. If a module does not specify a custom `module_id`, it defaults to the domain name. The complete mapping:

| Module Name | Domain | module_id (= source_platform) | 4CAT DATASOURCE (after sanitization) |
|-------------|--------|-------------------------------|--------------------------------------|
| LinkedIn | linkedin.com | `linkedin.com` | `linkedin` |
| TikTok (posts) | tiktok.com | `tiktok.com` | `tiktok` |
| TikTok (comments) | tiktok.com | `tiktok-comments` | `tiktok-comments` |
| Instagram (posts & reels) | instagram.com | `instagram.com` | `instagram` |
| X/Twitter | x.com | `twitter.com` | `twitter` |
| Threads | threads.com | `threads.net` | `threads` |
| Gab | gab.com | `gab.com` | `gab` |
| Truth Social | truthsocial.com | `truthsocial.com` | `truthsocial` |
| 9GAG | 9gag.com | `9gag.com` | `ninegag` |
| Imgur | imgur.com | `imgur.com` | `imgur` |
| Douyin | douyin.com | `douyin.com` | `douyin` |
| Pinterest | pinterest.com | `pinterest.com` | `pinterest` |
| RedNote/Xiaohongshu | xiaohongshu.com | `xiaohongshu.com` | `xiaohongshu` |
| RedNote (comments) | xiaohongshu.com | `xiaohongshu-comments` | `xiaohongshu-comments` |

**4CAT sanitization logic** (applied to the header value):
```python
platform = header_value.split(".")[0]  # "linkedin.com" -> "linkedin"
# Then replace digits with words:
platform = platform.replace("9", "nine")  # etc.
# "9gag" -> "ninegag"
```

### 2.4 The Upload HTTP Request

**Method**: `POST`

**URL**: `{server_base_url}/api/import-dataset/`

**Headers**:
| Header | Value | Required |
|--------|-------|----------|
| `X-Zeeschuimer-Platform` | Module identifier (e.g., `linkedin.com`, `tiktok.com`, `twitter.com`) | Yes |
| `Content-Type` | Not explicitly set by Zeeschuimer; defaults to browser XHR default (`text/plain` or unset). The body is sent as raw binary via `xhr.send(blob)`. | No |

**Query Parameters**:
| Parameter | Value | Required |
|-----------|-------|----------|
| `access-token` | 4CAT API access token (alternative to cookie auth) | No (if already authenticated via session) |
| `pseudonymise` | `"pseudonymise"` or `"anonymise"` to trigger post-processing | No |

**Body**: Raw binary blob containing the NDJSON content. Zeeschuimer constructs a `Blob` with MIME type `application/x-ndjson` and sends it directly via `xhr.send(blob)`. This is **not** multipart form data -- the entire request body is the raw NDJSON text.

**Authentication**: Zeeschuimer relies on the browser's session cookies for the 4CAT domain. The `@login_required` decorator on the 4CAT endpoint checks Flask-Login session state. If no session cookie is present, 4CAT also accepts an `access-token` query parameter or `Authentication`/`Authorization` headers, which are resolved via Flask-Login's `request_loader`:

```python
# 4CAT webtool/views/views_user.py
@current_app.login_manager.request_loader
def load_user_from_request(request):
    token = request.args.get("access-token")
    if not token:
        token = request.headers.get("Authentication")
    if not token:
        token = request.headers.get("Authorization")
    if not token:
        return None
    user = current_app.db.fetchone(
        "SELECT name AS user FROM access_tokens WHERE token = %s "
        "AND (expires = 0 OR expires > %s)",
        (token, int(time.time())))
    # ...
```

### 2.5 The Upload HTTP Response

**Success (200)**:
```json
{
    "status": "queued",
    "key": "abcdef1234567890",
    "url": "/results/abcdef1234567890/"
}
```

The `key` is used by Zeeschuimer to poll processing status.

**Error responses**:
| Status Code | Condition | Response |
|-------------|-----------|----------|
| 200 (redirect to `/login/`) | Not authenticated (session expired, no cookie) | HTML login page. Zeeschuimer detects this by checking `xhr.responseURL.indexOf('/login/')`. |
| 403 | Authentication failed | Error message |
| 404 | Unknown platform or datasource not enabled | `{"error": "Unknown platform or source format '{platform}'"}` |
| 429 | Rate limited (5 per minute limit) | Rate limit error |

### 2.6 Post-Upload Polling

After a successful upload, Zeeschuimer polls for processing completion:

**Method**: `GET`

**URL**: `{server_base_url}/api/check-query/?key={dataset_key}`

**Response**:
```json
{
    "datasource": "linkedin",
    "status": "Processing...",
    "rows": 150,
    "key": "abcdef1234567890",
    "done": false,
    "progress": 45,
    "url": "https://4cat.example.com/results/abcdef1234567890/"
}
```

Zeeschuimer polls every 1 second until `done` is `true`, then displays a link to the dataset.

---

## 3. The 4CAT Receiver Endpoint (Server Side)

### 3.1 Endpoint Implementation

The complete 4CAT endpoint is at `webtool/views/api_tool.py`:

```python
@component.route("/api/import-dataset/", methods=["POST"])
@login_required
@current_app.limiter.limit("5 per minute")
@setting_required("privileges.can_create_dataset")
def import_dataset():
    platform = request.headers.get("X-Zeeschuimer-Platform").split(".")[0]
    # Sanitize: "9gag" -> "ninegag", etc.
    platform = platform.replace("1","one").replace("2","two")...

    # Validate platform exists and is enabled
    if not platform or platform not in g.modules.datasources or \
       platform not in g.config.get('datasources.enabled'):
        return error(404, message=f"Unknown platform or source format '{platform}'")

    # Find matching worker (tries {platform}-import, then {platform}-search)
    worker_types = (f"{platform}-import", f"{platform}-search")
    worker = None
    for worker_type in worker_types:
        worker = g.modules.workers.get(worker_type)
        if worker:
            break

    # Create dataset record
    dataset = DataSet(parameters={"datasource": platform}, type=worker.type, ...)
    dataset.update_status("Importing uploaded file...")

    # Stream request body to temporary file (4096-byte chunks)
    temporary_path = dataset.get_results_path().with_suffix(".importing")
    with temporary_path.open("wb") as outfile:
        while True:
            chunk = request.stream.read(4096)
            if len(chunk) == 0:
                break
            outfile.write(chunk)

    # Queue background worker to process the file
    job = g.queue.add_job(worker_or_type=worker, ...)
    return jsonify({"status": "queued", "key": dataset.key, "url": ...})
```

### 3.2 How 4CAT Processes the NDJSON File

The background worker calls `import_from_file()` in `backend/lib/search.py`:

1. Opens the NDJSON file with UTF-8 encoding
2. Parses each line as JSON
3. NUL bytes (`\0`) are stripped from each line before parsing
4. The item is restructured: `item["data"]` becomes the top-level object, and all other fields (`timestamp_collected`, `source_platform`, etc.) are nested under `__import_meta`
5. The restructured item is passed to the platform-specific `map_item()` method for normalization
6. The file is deleted after processing

### 3.3 Rate Limiting

4CAT applies `5 per minute` rate limiting to the import endpoint. Zeeschuimer handles 429 responses with the message "4CAT server refused upload, too soon after previous one."

---

## 4. Per-Platform Data Schemas

This section documents the raw data structure within the `data` field for platforms relevant to the Issue Observatory, as captured by Zeeschuimer and normalized by 4CAT.

### 4.1 LinkedIn (Primary Use Case)

**Zeeschuimer module_id**: `linkedin.com`
**4CAT datasource**: `linkedin`
**4CAT search class**: `SearchLinkedIn` in `datasources/linkedin/search_linkedin.py`

LinkedIn data is captured from the Voyager V2 API, which LinkedIn's web frontend uses internally. Zeeschuimer intercepts responses from `linkedin.com` and parses both JSON API responses and HTML pages containing embedded `<code>` blocks with JSON data.

**Raw data structure** (the `data` field for each item):

The raw item is a deeply nested LinkedIn Voyager object with cross-references resolved by `recursively_enrich()`. Key top-level fields:

| Field Path | Type | Description |
|------------|------|-------------|
| `id` | String | URN identifier, e.g., `"urn:li:fs_updateV2:(urn:li:activity:7293847561234567890,...)"` |
| `actor.name.text` | String | Author display name |
| `actor.navigationContext.actionTarget` | String | Author profile URL |
| `actor.subDescription.text` | String | Relative timestamp (e.g., `"18h"`, `"2d"`, `"3mo"`) -- **LinkedIn does not provide absolute timestamps** |
| `actor.description.text` | String | Author headline/description |
| `actor.name.attributes[0].*miniProfile` | Object | Full author profile (username, avatar, pronouns) |
| `actor.name.attributes[0].*miniCompany` | Object | Company page info (if author is company) |
| `actor.image.attributes[0].detailData.nonEntityProfilePicture` | Object | Author avatar |
| `commentary.text.text` | String | Post body text |
| `commentary.text.attributes[]` | Array | Hashtags (`type: "HASHTAG"`), mentions (`type: "PROFILE_MENTION"`, `"COMPANY_NAME"`) |
| `commentary.text.attributesV2[]` | Array | V2 format for hashtags and mentions |
| `content.images[]` | Array | Attached images (vectorImage with rootUrl + artifacts) |
| `content.articleComponent` | Object | Linked article (title, image, navigationContext) |
| `content.*videoPlayMetadata` | Object | Video metadata (thumbnail) |
| `content.linkedInVideoComponent` | Object | LinkedIn-native video |
| `content.externalVideoComponent` | Object | External video embed |
| `content.navigationContext.actionTarget` | String | Link URL attached to post |
| `*socialDetail.*totalSocialActivityCounts` | Object | Engagement metrics (numComments, numShares, numLikes, reactionTypeCounts) |
| `*socialDetail.comments.paging.total` | Integer | Alternative comments count |
| `*socialDetail.likes.paging.total` | Integer | Alternative reactions count |
| `*socialDetail.totalShares` | Integer | Alternative shares count |
| `updateMetadata.urn` | String | Activity URN for post URL construction |
| `header.text.text` | String | Inclusion context (e.g., "X liked this", "Suggested for you") |

**4CAT normalized output fields** (from `map_item()`):

| 4CAT Field | Source | Notes |
|------------|--------|-------|
| `id` | Activity URN numerical suffix | e.g., `"7293847561234567890"` |
| `thread_id` | Same as `id` | |
| `body` | `commentary.text.text` | Post text content |
| `timestamp` | Estimated: `timestamp_collected - parse_time_ago(subDescription)` | **Imprecise** -- based on relative "18h ago" text |
| `timestamp_collected` | `__import_meta.timestamp_collected / 1000` | Converted from ms to seconds |
| `timestamp_ago` | `actor.subDescription.text` (before first `"."`) | Raw relative time string |
| `is_promoted` | `"yes"` if no digits in `time_ago`; `"no"` otherwise | Promoted posts have no time indication |
| `author` | `actor.navigationContext.actionTarget` (path after `linkedin.com/`) | e.g., `"in/john-doe"` or `"company/acme"` |
| `author_name` | `actor.name.text` | Display name |
| `author_description` | `actor.description.text` | Headline |
| `author_pronouns` | From miniProfile `customPronoun` or `standardizedPronoun` | |
| `author_avatar_url` | Largest vectorImage artifact URL | |
| `author_is_company` | `"yes"` or `"no"` | |
| `author_url` | Profile URL (without query parameters) | |
| `author_mentions` | Comma-separated `publicIdentifier` values | |
| `author_name_mentions` | Comma-separated full names of mentioned users | |
| `hashtags` | Comma-separated hashtag texts | |
| `image_urls` | Comma-separated image URLs | |
| `video_thumb_url` | Video thumbnail URL | |
| `post_url` | `"https://www.linkedin.com/feed/update/" + urn` | |
| `link_url` | External link target | |
| `comments` | Comment count | |
| `shares` | Share count | |
| `reactions` | Total reaction count | |
| `reaction_like` | Like reaction count | |
| `reaction_empathy` | Empathy reaction count | |
| `reaction_praise` | Praise reaction count | |
| `reaction_entertainment` | Entertainment reaction count | |
| `reaction_appreciation` | Appreciation reaction count | |
| `reaction_interest` | Interest reaction count | |
| `inclusion_context` | Header text | Why this post appeared in feed |
| `collected_from_url` | `__import_meta.source_platform_url` | URL of page where captured |
| `unix_timestamp` | Estimated publication epoch | |
| `unix_timestamp_collected` | Collection epoch (seconds) | |

**Critical limitation**: LinkedIn does not provide absolute timestamps. The `parse_time_ago()` method converts relative strings like `"18h"`, `"2d"`, `"3mo"` into second offsets from collection time. This means timestamps become less precise for older posts (e.g., `"3mo"` could be off by 15 days). The method currently supports English and Dutch interface languages.

### 4.2 X/Twitter

**Zeeschuimer module_id**: `twitter.com`
**4CAT datasource**: `twitter`
**4CAT search class**: `SearchTwitterViaZeeschuimer` in `datasources/twitter-import/search_twitter.py`

Twitter data is captured from `x.com` API responses. The module monitors these API endpoints: `adaptive.json`, `HomeLatestTimeline`, `HomeTimeline`, `ListLatestTweetsTimeline`, `UserTweets`, `Likes`, `SearchTimeline`, `TweetDetail`.

**Key raw data fields** within the `data` object:

| Field Path | Type | Description |
|------------|------|-------------|
| `rest_id` | String | Tweet ID (modern format) |
| `legacy.id_str` | String | Tweet ID (legacy format) |
| `legacy.full_text` | String | Tweet text |
| `legacy.created_at` | String | Timestamp, e.g., `"Mon Jan 15 12:34:56 +0000 2026"` |
| `legacy.favorite_count` | Integer | Like count |
| `legacy.retweet_count` | Integer | Retweet count |
| `legacy.reply_count` | Integer | Reply count |
| `legacy.quote_count` | Integer | Quote tweet count |
| `legacy.bookmark_count` | Integer | Bookmark count |
| `core.user_results.result.legacy` | Object | Author info (screen_name, name, followers_count, etc.) |
| `legacy.retweeted_status_result` | Object | Original tweet if this is a retweet |
| `quoted_status_result` | Object | Quoted tweet data |
| `promoted` | Boolean | Whether this is a promoted/sponsored tweet |

### 4.3 Instagram

**Zeeschuimer module_id**: `instagram.com`
**4CAT datasource**: `instagram`
**4CAT search class**: `SearchInstagram` in `datasources/instagram/search_instagram.py`

Instagram data comes in two formats: Graph API responses (with `__typename`) and item list responses. The module monitors `instagram.com` domain requests.

**Key raw data fields**:

| Field Path | Type | Description |
|------------|------|-------------|
| `id` | String | Instagram media ID |
| `code` | String | Shortcode used in URLs (e.g., `C1hWCZLPQ9T`) |
| `media_type` | Integer | 1=Photo, 2=Video, 8=Carousel |
| `user.username` | String | Author username |
| `user.full_name` | String | Author display name |
| `user.pk` | String | Author user ID |
| `caption.text` | String | Post caption |
| `taken_at` | Integer | Unix timestamp |
| `like_count` | Integer | Like count |
| `comment_count` | Integer | Comment count |
| `usertags.in[]` | Array | Tagged users |
| `location` | Object | Location data (name, lat/lng) |
| `image_versions2` | Object | Image URLs at various resolutions |
| `video_versions[]` | Array | Video URLs |
| `carousel_media[]` | Array | Carousel items |

**Known limitations**: No Stories, no Reels tab content, no For You feed, no sponsored content (ads are explicitly filtered out by 4CAT).

### 4.4 TikTok

**Zeeschuimer module_id**: `tiktok.com`
**4CAT datasource**: `tiktok`

**Key raw data fields**:

| Field Path | Type | Description |
|------------|------|-------------|
| `id` | String | Video ID |
| `desc` | String | Video description/caption |
| `createTime` | Integer | Unix timestamp |
| `author.uniqueId` | String | Author username |
| `author.nickname` | String | Author display name |
| `author.id` | String | Author user ID |
| `stats.diggCount` | Integer | Like count |
| `stats.commentCount` | Integer | Comment count |
| `stats.shareCount` | Integer | Share count |
| `stats.playCount` | Integer | View count |
| `music` | Object | Sound/music metadata |
| `challenges[]` | Array | Hashtag challenges |
| `video.duration` | Integer | Video duration in seconds |

### 4.5 Threads

**Zeeschuimer module_id**: `threads.net`
**4CAT datasource**: `threads`

Threads data is captured from `threads.com` (note: domain vs module_id differ because the module explicitly sets `module_id='threads.net'`).

### 4.6 Gab

**Zeeschuimer module_id**: `gab.com`
**4CAT datasource**: `gab`

Gab data follows Mastodon API format (status objects with `id`, `content`, `created_at`, `account`, `reblogs_count`, `favourites_count`, `replies_count`). This overlaps with our existing Gab arena collector which already uses the Mastodon-compatible API.

---

## 5. Mapping Zeeschuimer Fields to IO content_records

### 5.1 Universal Mapping (All Platforms)

These fields can be derived from the Zeeschuimer envelope regardless of platform:

| IO content_records Field | Zeeschuimer Source | Notes |
|--------------------------|--------------------|-------|
| `collected_at` | `timestamp_collected / 1000` | Convert ms to datetime |
| `platform` | Derived from `source_platform` | Map module_id to IO platform_name (see Section 5.3) |
| `arena` | Derived from platform | `"social_media"` for all Zeeschuimer platforms |
| `content_type` | `"post"` | Default; could be refined per-platform |
| `collection_tier` | `"manual"` | Fixed value: Zeeschuimer is manual capture |
| `raw_metadata.zeeschuimer` | Entire envelope | Preserve `source_platform_url`, `source_url`, `user_agent`, `nav_index` |
| `raw_metadata.import_source` | `"zeeschuimer"` | Tag for provenance |

### 5.2 LinkedIn-Specific Mapping

| IO content_records Field | Zeeschuimer/4CAT Source | Notes |
|--------------------------|--------------------|-------|
| `platform_id` | Activity URN numerical suffix | Extracted from `updateMetadata.urn` or `preDashEntityUrn` |
| `text_content` | `commentary.text.text` | Post body |
| `title` | `null` | LinkedIn posts do not have titles |
| `url` | `"https://www.linkedin.com/feed/update/urn:li:activity:" + id` | Constructed from URN |
| `language` | Not available | LinkedIn Voyager V2 does not include a language field; use IO's LanguageDetector enricher post-import |
| `published_at` | Estimated from `timestamp_collected - parse_time_ago()` | **Imprecise** -- see Section 4.1 |
| `author_platform_id` | `actor.navigationContext.actionTarget` path segment | e.g., `"in/john-doe"` |
| `author_display_name` | `actor.name.text` | |
| `likes_count` | `*socialDetail.*totalSocialActivityCounts.numLikes` | Total reactions |
| `shares_count` | `*socialDetail.*totalSocialActivityCounts.numShares` | |
| `comments_count` | `*socialDetail.*totalSocialActivityCounts.numComments` | |
| `views_count` | Not available | LinkedIn does not expose view counts in feed data |
| `engagement_score` | Compute from likes + shares + comments | Use IO's standard engagement normalization |
| `media_urls` | Image URLs from `content.images[]` | Largest artifact resolution |
| `search_terms_matched` | `[]` | Manual capture has no term matching |
| `content_hash` | SHA-256 of `text_content` | Computed at import time |
| `raw_metadata.linkedin` | Full raw item | Preserve all fields for re-processing |
| `raw_metadata.linkedin.is_promoted` | Boolean | Derived from time_ago having no digits |
| `raw_metadata.linkedin.author_is_company` | Boolean | |
| `raw_metadata.linkedin.hashtags` | Array of strings | |
| `raw_metadata.linkedin.reaction_breakdown` | Object | Per-reaction-type counts |
| `raw_metadata.linkedin.inclusion_context` | String | Why post appeared (e.g., "Suggested") |
| `raw_metadata.linkedin.link_url` | String | External link in post |

### 5.3 Platform Name Mapping (Zeeschuimer module_id to IO platform_name)

| Zeeschuimer module_id | IO platform_name | IO Arena Exists? | Notes |
|----------------------|------------------|-------------------|-------|
| `linkedin.com` | `linkedin` | No (manual import only) | Primary use case |
| `twitter.com` | `x_twitter` | Yes | Redundant -- IO has TwitterAPI.io collector |
| `instagram.com` | `instagram` | Yes | Redundant -- IO has Bright Data collector |
| `tiktok.com` | `tiktok` | Yes | Redundant -- IO has Research API collector |
| `tiktok-comments` | `tiktok_comments` | No | Could supplement TikTok arena |
| `threads.net` | `threads` | Yes | Redundant -- IO has unofficial API collector |
| `gab.com` | `gab` | Yes | Redundant -- IO has Mastodon API collector |
| `truthsocial.com` | `truth_social` | No | No Danish relevance |
| `9gag.com` | `ninegag` | No | No Danish relevance |
| `imgur.com` | `imgur` | No | No Danish relevance |
| `douyin.com` | `douyin` | No | No Danish relevance |
| `pinterest.com` | `pinterest` | No | No Danish relevance |
| `xiaohongshu.com` | `xiaohongshu` | No | No Danish relevance |
| `xiaohongshu-comments` | `xiaohongshu_comments` | No | No Danish relevance |

---

## 6. Recommended IO Endpoint Design

### 6.1 Endpoint Specification

**Route**: `POST /api/zeeschuimer/upload`

Rationale for a separate path rather than mimicking `/api/import-dataset/`: IO is not 4CAT. Using our own path avoids confusion and allows us to design the endpoint to fit our architecture while still accepting the same request format.

**However**, for Zeeschuimer compatibility, the extension hardcodes the path `/api/import-dataset/`. The user configures a server URL (e.g., `https://io.example.com`) and Zeeschuimer appends `/api/import-dataset/` automatically. Therefore, the IO receiver **must** be mounted at exactly:

**Route (for Zeeschuimer compatibility)**: `POST /api/import-dataset/`

Optionally, also mount an alias at `POST /api/zeeschuimer/upload` for programmatic use (e.g., NDJSON file upload from scripts).

**Request format**: Identical to the 4CAT protocol described in Section 2.4:
- Header: `X-Zeeschuimer-Platform: {module_id}`
- Body: Raw NDJSON (not multipart)
- Optional query parameter: `access-token` for token-based auth

**Authentication**: The IO endpoint should support two mechanisms:
1. **JWT Bearer token** (via `Authorization: Bearer {token}` header) -- primary mechanism, consistent with IO's existing auth
2. **API key via query parameter** (`?access-token={key}`) -- for Zeeschuimer compatibility, since the extension uses browser session cookies for 4CAT but IO will not share session context with a browser extension. The researcher would configure their API key in the 4CAT URL field as: `https://io.example.com?access-token=THEIR_KEY` (Zeeschuimer will append `/api/import-dataset/` and preserve query parameters)

**IMPORTANT**: Zeeschuimer sets the 4CAT URL at the base level (e.g., `https://4cat.example.com`) and appends the path. The extension normalizes the URL to `protocol + domain` only (strips paths). So the access token approach via query parameter on the base URL may not work -- the extension's `set_4cat_url()` strips everything after the third slash:

```javascript
url = url.split('/').slice(0, 3).join('/');
```

This means any query parameters in the configured URL will be lost. The most practical approach is one of:
- (a) Have the researcher log into IO in the same Firefox browser before uploading (cookie-based auth)
- (b) Fork/modify Zeeschuimer to support an API key field (small change, but requires maintaining a fork)
- (c) Implement a browser extension companion that injects auth headers for IO requests (over-engineered)

**Recommendation**: Option (a) is simplest. The IO endpoint should support session cookie authentication (the existing JWT cookie that IO sets at login) alongside Bearer token auth. This mirrors how 4CAT works -- the researcher logs into IO in Firefox, then Zeeschuimer's XHR requests include the session cookie automatically because they share the same browser context.

### 6.2 Response Format

For Zeeschuimer compatibility, the success response must include the fields that Zeeschuimer expects:

```json
{
    "status": "queued",
    "key": "import-abc123",
    "url": "/collections/import-abc123/"
}
```

However, since IO can process imports synchronously (or near-synchronously for typical Zeeschuimer upload sizes of hundreds to low thousands of items), an alternative is to process inline and return a completion response:

```json
{
    "status": "complete",
    "key": "import-abc123",
    "done": true,
    "rows": 247,
    "url": "/content/?import_id=import-abc123"
}
```

Zeeschuimer's polling logic (`upload_poll.init()`) calls `GET /api/check-query/?key={key}` and checks for `done: true`. If the response already indicates completion, it displays the success message immediately without further polling.

**Polling endpoint** (for Zeeschuimer compatibility): `GET /api/check-query/?key={key}`

This should return:
```json
{
    "done": true,
    "status": "Import complete",
    "rows": 247,
    "datasource": "linkedin",
    "url": "/content/?import_id=import-abc123"
}
```

If processing is asynchronous, return `"done": false` with a progress status until complete.

### 6.3 Processing Pipeline

1. **Receive**: Stream request body to temporary file (4096-byte chunks, matching 4CAT's approach, to handle large uploads without loading everything into memory)
2. **Validate platform**: Check `X-Zeeschuimer-Platform` header; map to IO platform name; reject unknown platforms with 404
3. **Parse NDJSON**: Read file line by line, parse each line as JSON, strip NUL bytes
4. **Restructure**: For each line, extract `item["data"]` as the content object and collect envelope fields as import metadata
5. **Normalize**: Apply platform-specific normalization to produce `content_records`:
   - LinkedIn: Use the mapping from Section 5.2
   - Other platforms: Map to existing IO normalizers where arena collectors already exist
6. **Pseudonymize**: Apply GDPR-compliant pseudonymization (SHA-256 with salt on `author_platform_id`), respecting `public_figure` bypass
7. **Deduplicate**: Compute `content_hash` and `simhash`; check for existing records
8. **Store**: Insert into `content_records` table
9. **Tag**: Set `collection_tier = "manual"`, store `raw_metadata.import_source = "zeeschuimer"`, `raw_metadata.import_meta = {envelope fields}`
10. **Respond**: Return completion status with record count

### 6.4 Query Design Association

Zeeschuimer uploads are not associated with a query design or collection run by default (manual capture has no search terms). The endpoint should:

- Accept an optional `query_design_id` query parameter to associate imported records with a specific query design
- If no query design is specified, create an ad-hoc import record (a lightweight `collection_run` with `method = "zeeschuimer_import"`)
- The `search_terms_matched` field should be empty (or populated post-hoc by running the query builder against imported text)

### 6.5 Platform Support Matrix

The IO receiver should initially support only platforms with clear research value:

| Platform | Support | Rationale |
|----------|---------|-----------|
| LinkedIn | **Yes -- priority** | Only collection path for LinkedIn data |
| X/Twitter | Yes (supplement) | Can supplement automated collection with manual captures |
| Instagram | Yes (supplement) | Can supplement automated collection |
| TikTok | Yes (supplement) | Can supplement automated collection |
| TikTok comments | Yes | Not available via Research API |
| Threads | Yes (supplement) | Can supplement automated collection |
| Gab | No (defer) | Fully covered by existing Mastodon API collector |
| All others | No (defer) | No Danish discourse relevance |

For unsupported platforms, return 404 with a clear message (matching 4CAT's behavior so Zeeschuimer displays the correct error).

---

## 7. Implementation Notes

### 7.1 Complexity Estimate

| Component | Estimated Effort | Notes |
|-----------|-----------------|-------|
| FastAPI route (`/api/import-dataset/`) | 0.5 days | Streaming body reader, header validation |
| Polling route (`/api/check-query/`) | 0.5 days | Simple status lookup |
| NDJSON parser + restructurer | 0.5 days | Line-by-line JSON parsing, envelope extraction |
| LinkedIn normalizer | 1.5 days | Most complex -- Voyager V2 parsing, timestamp estimation, author extraction, engagement metrics |
| Twitter/Instagram/TikTok normalizers | 1 day | Can delegate to existing arena normalizers with adapter layer |
| Authentication integration | 0.5 days | Cookie + Bearer token support |
| Tests | 1 day | Unit tests with sample NDJSON fixtures from each platform |
| **Total** | **~5.5 person-days** | |

### 7.2 Architecture Decision: Import Endpoint vs. Arena Collector

This should be implemented as an **import endpoint**, not an arena collector. Rationale:

- Zeeschuimer data is manually captured, not query-driven -- it cannot implement `collect_by_terms()` or `collect_by_actors()`
- There is no API to poll, no rate limits to manage, no credentials to pool
- The data flow is push-based (browser pushes to server), not pull-based (server pulls from API)
- The normalizers for each platform can reuse logic from existing arena collectors but do not need the full `ArenaCollector` lifecycle

This aligns with the recommendation in the existing Zeeschuimer assessment (`/reports/zeeschuimer_assessment.md`, Section 7).

### 7.3 File Placement

Recommended location within the IO codebase:

```
src/issue_observatory/
  imports/
    __init__.py
    router.py              # FastAPI routes: /api/import-dataset/, /api/check-query/
    zeeschuimer.py          # NDJSON parser, envelope restructurer, platform dispatcher
    normalizers/
      __init__.py
      linkedin.py           # LinkedIn Voyager V2 -> content_records
      twitter.py            # Adapter to existing x_twitter normalizer
      instagram.py          # Adapter to existing instagram normalizer
      tiktok.py             # Adapter to existing tiktok normalizer
      threads.py            # Adapter to existing threads normalizer
```

### 7.4 Sample NDJSON Line (LinkedIn)

For test fixture creation, here is a representative NDJSON line structure:

```json
{
  "id": 5,
  "nav_index": "1:42:3",
  "item_id": "urn:li:fs_updateV2:(urn:li:activity:7293847561234567890,FEED_DETAIL,EMPTY,DEFAULT,false)",
  "timestamp_collected": 1740100000000,
  "last_updated": 1740100000000,
  "source_platform": "linkedin.com",
  "source_platform_url": "https://www.linkedin.com/feed/",
  "source_url": "https://www.linkedin.com/voyager/api/feed/updatesV2?count=10&start=0",
  "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
  "data": {
    "actor": {
      "name": {
        "text": "Jane Researcher",
        "attributes": [{
          "*miniProfile": {
            "publicIdentifier": "jane-researcher",
            "firstName": "Jane",
            "lastName": "Researcher",
            "picture": {
              "rootUrl": "https://media.licdn.com/dms/image/v2/",
              "artifacts": [{"width": 200, "fileIdentifyingUrlPathSegment": "abc123"}]
            },
            "standardizedPronoun": "SHE_HER"
          }
        }]
      },
      "navigationContext": {
        "actionTarget": "https://www.linkedin.com/in/jane-researcher?miniProfileUrn=..."
      },
      "subDescription": {"text": "2d \u2022 Edited"},
      "description": {"text": "Associate Professor at University of Copenhagen"},
      "image": {"attributes": [{"detailData": {"nonEntityProfilePicture": {"vectorImage": null}}}]}
    },
    "commentary": {
      "text": {
        "text": "Interesting findings on Danish media consumption patterns. #MediaResearch #Denmark",
        "attributes": [
          {"type": "HASHTAG", "trackingUrn": "urn:li:hashtag:MediaResearch"},
          {"type": "HASHTAG", "trackingUrn": "urn:li:hashtag:Denmark"}
        ]
      }
    },
    "content": null,
    "*socialDetail": {
      "*totalSocialActivityCounts": {
        "numComments": 12,
        "numShares": 5,
        "numLikes": 87,
        "reactionTypeCounts": [
          {"reactionType": "LIKE", "count": 65},
          {"reactionType": "PRAISE", "count": 12},
          {"reactionType": "INTEREST", "count": 10}
        ]
      }
    },
    "updateMetadata": {
      "urn": "urn:li:fs_updateV2:(urn:li:activity:7293847561234567890,FEED_DETAIL,EMPTY,DEFAULT,false)"
    },
    "header": null,
    "id": "urn:li:fs_updateV2:(urn:li:activity:7293847561234567890,FEED_DETAIL,EMPTY,DEFAULT,false)"
  }
}
```

### 7.5 Known Gotchas

1. **LinkedIn timestamps are imprecise.** The `parse_time_ago()` approach loses precision for posts older than a few days. Posts shown as "3mo" ago could be off by up to 15 days. IO should store the raw `timestamp_ago` string in `raw_metadata` and flag the timestamp as estimated.

2. **Zeeschuimer `timestamp_collected` is in milliseconds.** Must divide by 1000 before converting to Python datetime. 4CAT does this explicitly: `int(item["__import_meta"]["timestamp_collected"] / 1000)`.

3. **The `data.id` field is the item_id, not a sequential integer.** For LinkedIn, it is a URN string. For Twitter, it is a tweet ID string. Do not confuse with the outer `id` field (Dexie auto-increment).

4. **LinkedIn data structure varies.** The Voyager V2 format has evolved over time with `attributes` vs `attributesV2`, `*elements` vs `elements`, and different engagement metric locations. The normalizer must handle all variants (see the 4CAT `map_item()` for reference).

5. **Instagram ad posts are filtered.** 4CAT explicitly raises `MapItemException` for Instagram ads (`product_type == "ad"` or Facebook redirect links). IO should do the same.

6. **Zeeschuimer strips URL to protocol+domain.** The `set_4cat_url()` function normalizes the configured URL to just `protocol://domain`. Any path or query parameters are stripped. This affects how authentication tokens can be passed.

7. **Rate limiting matters.** 4CAT limits to 5 uploads per minute. IO should implement similar rate limiting to prevent abuse, especially since the endpoint accepts unauthenticated-looking requests (cookie-based auth).

8. **NUL bytes in data.** 4CAT strips `\0` characters from JSON lines before parsing. Some platform API responses include null bytes that break JSON parsers.

9. **The module_id `twitter.com` is set explicitly.** Even though Zeeschuimer monitors `x.com`, the Twitter module explicitly registers with `module_id='twitter.com'` for backward compatibility. Similarly, Threads uses `threads.net` as module_id despite monitoring `threads.com`.

10. **LinkedIn has no language field.** Unlike Twitter (`lang` field) or GDELT (`sourcelang`), LinkedIn's Voyager V2 API does not include a language indicator. IO must rely on post-import language detection.

---

## 8. Testing Strategy

### 8.1 Required Test Fixtures

Create sample NDJSON files at `tests/fixtures/zeeschuimer/`:

| Fixture | Content | Source |
|---------|---------|--------|
| `linkedin_feed.ndjson` | 5-10 LinkedIn feed posts with varied types (text-only, image, video, article, company post) | Construct from Voyager V2 schema documented above |
| `linkedin_edge_cases.ndjson` | Posts with missing fields, promoted posts, aggregate URNs | Based on 4CAT's handling of edge cases |
| `twitter_timeline.ndjson` | 3-5 tweets (regular, retweet, quote tweet) | Based on Twitter GraphQL API format |
| `instagram_posts.ndjson` | 3-5 Instagram posts (photo, video, carousel) | Based on Instagram API format |
| `malformed.ndjson` | Lines with invalid JSON, NUL bytes, empty lines | For error handling tests |

### 8.2 Test Cases

1. **Upload endpoint**: POST with valid NDJSON, verify 200 response with correct structure
2. **Platform routing**: Verify `X-Zeeschuimer-Platform: linkedin.com` maps to LinkedIn normalizer
3. **Platform rejection**: Verify unknown platform returns 404 with correct message
4. **Authentication**: Verify unauthenticated requests are rejected (401/403)
5. **LinkedIn normalization**: Verify all fields map correctly, timestamp estimation, URN extraction, engagement metrics
6. **NDJSON parsing**: Verify line-by-line parsing, NUL byte stripping, malformed line handling
7. **Deduplication**: Upload same items twice, verify no duplicates created
8. **Rate limiting**: Verify rate limits are enforced
9. **Large upload**: Stream a file with 10,000+ items, verify memory usage stays bounded
10. **Polling endpoint**: Verify `/api/check-query/` returns correct status

---

## 9. Relationship to Existing IO Architecture

### 9.1 How This Fits the Import Pathway

The existing Zeeschuimer assessment (`/reports/zeeschuimer_assessment.md`, Section 7) recommends a "generic import endpoint" pattern. This specification builds on that recommendation with the specific protocol details needed for Zeeschuimer compatibility.

The import endpoint is distinct from arena collectors:
- It does not subclass `ArenaCollector`
- It does not register in the arena registry
- It does not appear in the arena configuration grid
- It creates `collection_run` records with `method = "zeeschuimer_import"` for provenance tracking

### 9.2 What Existing Code Can Be Reused

| IO Component | Reuse Opportunity |
|-------------|-------------------|
| `core/normalizer.py` | Pseudonymization (SHA-256), engagement score computation |
| `core/deduplication.py` | Content hash, SimHash near-duplicate detection |
| `core/retention_service.py` | Retention policy enforcement for imported records |
| `analysis/enrichments/language_detector.py` | Post-import language detection (critical for LinkedIn which lacks language field) |
| `analysis/enrichments/sentiment_analyzer.py` | Post-import Danish sentiment analysis |
| `arenas/x_twitter/collector.py` | Twitter normalization logic (adapt `normalize()` method) |
| `arenas/instagram/collector.py` | Instagram normalization logic |
| `arenas/tiktok/collector.py` | TikTok normalization logic |
| `arenas/threads/collector.py` | Threads normalization logic |

### 9.3 What Is New

| Component | Why It Is New |
|-----------|--------------|
| `/api/import-dataset/` route | 4CAT-compatible receiver endpoint |
| `/api/check-query/` route | 4CAT-compatible polling endpoint |
| LinkedIn normalizer | No existing LinkedIn arena collector; this is the first LinkedIn data processing code in IO |
| NDJSON streaming parser | Existing import route (`/imports`) handles different formats; this needs raw NDJSON streaming |
| Zeeschuimer envelope restructurer | Specific to Zeeschuimer's `{envelope + data}` format |

---

## 10. Open Questions

1. **Authentication mechanism**: Should we require researchers to log into IO in the same Firefox browser (cookie-based), or should we explore modifying Zeeschuimer to support an API key field? The cookie approach is zero-modification but requires the IO instance to be accessible from the researcher's browser.

2. **Query design association**: Should imported data always be associated with a query design, or should we support "orphan" imports that can be associated later? The latter is more flexible but adds complexity.

3. **Deduplication across import and automated collection**: If a researcher imports LinkedIn data via Zeeschuimer and also has automated X/Twitter collection running, how should cross-platform deduplication work for cases where the same content appears on both? The existing `content_hash` approach handles text-identical content, but cross-platform posts often have platform-specific formatting.

4. **Retroactive term matching**: After import, should IO automatically run the query builder against imported text to populate `search_terms_matched`? This would make imported data searchable by the same terms used in automated collection.

5. **Enrichment triggering**: Should the import endpoint automatically trigger the enrichment pipeline (language detection, sentiment, NER) on imported data, or should this be manual? Automatic triggering is more complete but adds processing time.

---

## Appendix A: Complete Zeeschuimer File Inventory

Files examined in this analysis:

**Zeeschuimer repository** (https://github.com/digitalmethodsinitiative/zeeschuimer):
- `manifest.json` -- Extension manifest, lists all background scripts and modules
- `js/zs-background.js` -- Core: Dexie DB schema, `register_module()`, request listener, item storage, deduplication
- `popup/interface.js` -- Upload logic: `get_blob()`, `iterate_items()`, XHR to `/api/import-dataset/`, polling via `upload_poll`, 4CAT URL config
- `popup/interface.html` -- UI: 4CAT URL input field, upload buttons, status display
- `modules/linkedin.js` -- LinkedIn Voyager V2 parser, `recursively_enrich()`
- `modules/twitter.js` -- X/Twitter GraphQL parser, module_id = `twitter.com`
- `modules/instagram.js` -- Instagram parser with partial item handling
- `modules/tiktok.js` -- TikTok parser
- `modules/tiktok-comments.js` -- TikTok comments parser, module_id = `tiktok-comments`
- `modules/threads.js` -- Threads parser, module_id = `threads.net`
- `modules/gab.js` -- Gab (Mastodon) parser
- `modules/truth.js` -- Truth Social parser
- `modules/9gag.js` -- 9GAG parser
- `modules/imgur.js` -- Imgur parser
- `modules/douyin.js` -- Douyin parser
- `modules/pinterest.js` -- Pinterest parser
- `modules/rednote.js` -- RedNote/Xiaohongshu parser
- `modules/rednote-comments.js` -- RedNote comments parser, module_id = `xiaohongshu-comments`
- `js/lib.js` -- Utility function (`traverse_data`)

**4CAT repository** (https://github.com/digitalmethodsinitiative/4cat):
- `webtool/views/api_tool.py` -- `/api/import-dataset/` endpoint, `/api/check-query/` endpoint, `/api/request-token/` endpoint
- `webtool/views/views_user.py` -- `request_loader` for access token authentication
- `webtool/__init__.py` -- Flask app initialization, `before_request` hooks
- `backend/lib/search.py` -- `import_from_file()` method: NDJSON parsing, `__import_meta` restructuring
- `datasources/linkedin/__init__.py` -- `DATASOURCE = "linkedin"`
- `datasources/linkedin/search_linkedin.py` -- `SearchLinkedIn.map_item()`, `get_author()`, `parse_time_ago()`
- `datasources/twitter-import/search_twitter.py` -- `SearchTwitterViaZeeschuimer.map_item()`, modern/legacy tweet formats
- `datasources/instagram/search_instagram.py` -- `SearchInstagram.map_item()`, Graph/itemlist formats
- `datasources/tiktok/search_tiktok.py` -- TikTok import handler
- `datasources/threads/search_threads.py` -- Threads import handler
- `datasources/gab/search_gab.py` -- Gab import handler
- All 15 `datasources/*/__init__.py` files -- DATASOURCE identifier mapping
