# Comments and Replies Collection Feasibility Report

**Created**: 2026-03-12
**Last updated**: 2026-03-12 (v2 -- corrected Bright Data comment scraper findings)
**Author**: Research Agent
**Status**: Complete -- ready for team review

---

## 1. Executive Summary

This report assesses the feasibility of adding a **comments/replies collection module** to The Issue Observatory. The analysis examines all 12 social media arenas plus web-based arenas to determine which platforms already return comments, which can be extended with minimal effort, which require significant engineering, and which cannot support comment collection at all.

**Key findings:**
- **2 arenas already collect comments** (Reddit, Discord)
- **6 arenas can add comments with moderate effort** (Facebook, Instagram, Bluesky, YouTube, Gab, Telegram)
- **3 arenas are possible but face significant constraints** (X/Twitter, TikTok, Threads)
- **1 arena cannot feasibly collect comments** (Twitch)

A major finding in v2 of this report: **Bright Data offers dedicated Comment Scraper datasets** for Facebook, Instagram, TikTok, and YouTube -- all at $1.50/1K records, using the same trigger/poll/download pattern already implemented in our Facebook and Instagram post collectors. This dramatically improves the feasibility picture for Meta platforms and provides a quota-free alternative for TikTok and YouTube comments.

The highest-value targets for implementation are **Facebook** and **Instagram** (highest Danish usage at 84% and 56%; Bright Data integration pattern already in codebase), **YouTube** (high Danish discourse value; both Data API and Bright Data paths available), and **Bluesky** (free API, thread-native architecture).

---

## 2. Methodology

For each platform, this report examines:
1. The current collector implementation in `src/issue_observatory/arenas/{platform}/collector.py`
2. The corresponding config file for API endpoints, rate limits, and tier definitions
3. The existing arena research brief at `docs/arenas/{platform}.md` where available
4. The platform's public API documentation for comment-related endpoints

The assessment uses the project's existing tier model (FREE / MEDIUM / PREMIUM) and evaluates each platform against the universal content record schema, which already supports `content_type` values of `"comment"` and `"reply"`.

---

## 3. Platform-by-Platform Assessment

### 3.1 Already Collecting Comments

#### Reddit
- **Current state**: The collector already has full comment collection infrastructure. The `_collect_post_comments()` method fetches top-level comments for matched posts. The `_comment_to_raw()` method normalizes comments to content records with `content_type = "comment"`, including `parent_id`, `depth`, `parent_post_id`, and `parent_post_title` fields.
- **Configuration**: Comment collection is **off by default** (`INCLUDE_COMMENTS_DEFAULT = False` in config.py). When enabled, `MAX_COMMENTS_PER_POST = 100` top-level comments are collected per post.
- **Current limitation**: Only collects top-level comments (depth 0) via `replace_more(limit=0)`. Nested reply threads are not traversed.
- **What expanding would require**: Change `replace_more(limit=0)` to `replace_more(limit=N)` to fetch nested replies, and remove the `depth != 0` filter. This would significantly increase API usage (each `replace_more` call is an additional API request).
- **Rate limit impact**: Reddit allows 100 req/min. With `replace_more(limit=0)`, comment collection adds 1 API call per post. Enabling nested replies could add 5-50 calls per popular post depending on thread depth.
- **Tier**: FREE (no cost change)
- **Verdict**: **Already implemented (top-level only). Expanding to nested replies is straightforward but has significant rate-limit implications.**

#### Discord
- **Current state**: The collector fetches all messages from configured channels. Discord messages **are inherently threaded** -- replies reference a `referenced_message` via `referenced_message_id` in `raw_metadata`. Thread messages (in Discord Thread channels) are included automatically when the bot has access to the thread channel. The normalizer records `comments_count` from `thread.message_count` and `referenced_message_id`.
- **Configuration**: No separate comment toggle exists. All messages in a channel (including replies and thread messages) are collected.
- **Current limitation**: The collector only fetches messages from explicitly configured channel IDs. To collect thread messages, the thread channel IDs must be added to the channel list. Discord threads create new channel IDs.
- **What expanding would require**: After fetching channel messages, enumerate active threads in each channel via `GET /channels/{channel_id}/threads` and fetch messages from each thread channel. This is a moderate engineering task.
- **Rate limit impact**: Each thread fetch is an additional pagination sequence. Discord's rate limits are per-route (5 req/5s per route), which is generous for this use case.
- **Tier**: FREE (no cost change)
- **Verdict**: **Already collecting replies in flat channels. Thread enumeration requires moderate new code.**

---

### 3.2 Easy to Add (API supports it, minimal-to-moderate new code)

#### Facebook (via Bright Data Comments Scraper)
- **API**: Bright Data Web Scraper API -- dedicated Facebook Comments Scraper.
- **Dataset ID**: `gd_lkay758p1eanlolqw8`
- **Pricing**: $1.50 per 1,000 comment records (pay-as-you-go, same as post collection).
- **Input**: One or more Facebook post URLs. Submitted as a JSON array, e.g., `[{"url": "https://www.facebook.com/dr.dk/posts/12345"}]`. Supports bulk submission of up to 5,000 URLs per trigger.
- **Output fields**: `comment_id`, `comment_text`, `num_likes`, `num_replies`, `date`, `user_name`, `user_id`, `user_url`, `post_id`, `post_url`, `profile_name`, `profile_url`. Also includes `replies` (nested reply objects when available).
- **Current collector behavior**: The Facebook collector (`arenas/facebook/collector.py`) already implements the full Bright Data trigger/poll/download pattern for posts. It uses `build_trigger_url(dataset_id)` to construct the trigger URL, polls `BRIGHTDATA_PROGRESS_URL`, and downloads completed snapshots via `BRIGHTDATA_SNAPSHOT_URL`. Comment collection would follow the **identical integration pattern** with a different dataset ID.
- **What adding comments would require**:
  1. Add `FACEBOOK_DATASET_ID_COMMENTS = "gd_lkay758p1eanlolqw8"` to `facebook/config.py`.
  2. After post collection completes, extract post URLs from collected content records.
  3. Submit post URLs to the Comments Scraper dataset via the existing `_trigger_and_poll()` pattern.
  4. Write a `_normalize_comment()` method mapping Bright Data comment fields to the universal content record schema with `content_type = "comment"`.
  5. Pseudonymize `user_name`, `user_id`, `user_url` per GDPR requirements (all commenters are treated as private individuals).
- **Rate limit impact**: Same courtesy throttle as post collection (2 calls/sec). Comment scraper triggers are independent from post scraper triggers. No additional rate limit concern.
- **Credential reuse**: Uses the exact same Bright Data API token (`platform="brightdata_facebook"`, `tier="medium"`). No new credentials needed.
- **Legal considerations**: Bright Data's comment scraper collects publicly visible comments. GDPR pseudonymization is mandatory for all commenter identifiers. The arena brief (`docs/arenas/facebook_instagram.md`, lines 101-106) already documented that Facebook comments on public posts are available through Bright Data.
- **Estimated engineering effort**: Small-to-moderate. The trigger/poll/download infrastructure is already built. The new work is: a config constant, a comment trigger method, and a comment normalizer.
- **Verdict**: **Easy to add. Same Bright Data pattern already in codebase. Highest Danish relevance (84% usage). Recommended for Phase 1.**

#### Instagram (via Bright Data Comments Scraper)
- **API**: Bright Data Web Scraper API -- dedicated Instagram Comments Scraper.
- **Dataset ID**: `gd_ltppn085pokosxh13`
- **Pricing**: $1.50 per 1,000 comment records (pay-as-you-go, same as post collection).
- **Input**: One or more Instagram post/reel URLs. Submitted as a JSON array, e.g., `[{"url": "https://www.instagram.com/p/ABC123/"}]`. Supports bulk submission of up to 5,000 URLs per trigger.
- **Output fields**: `comment_user` (username), `comment_date`, `comment` (text body), `likes_number`, `replies_number`, `user_profile_url`, `post_url`, `post_id`. Also includes `replies` (nested reply array when available).
- **Current collector behavior**: The Instagram collector (`arenas/instagram/collector.py`) already implements the full Bright Data trigger/poll/download pattern for posts using `INSTAGRAM_DATASET_ID_POSTS = "gd_lk5ns7kz21pck8jpis"` in discovery mode. Comment collection would follow the **identical pattern** with the Comments dataset ID.
- **What adding comments would require**:
  1. Add `INSTAGRAM_DATASET_ID_COMMENTS = "gd_ltppn085pokosxh13"` to `instagram/config.py`.
  2. After post collection completes, extract individual post URLs (e.g., `https://www.instagram.com/p/{shortcode}/`) from collected content records.
  3. Submit post URLs to the Comments Scraper dataset via the existing trigger/poll/download pattern.
  4. Write a `_normalize_comment()` method mapping Bright Data comment fields to the universal schema with `content_type = "comment"`.
  5. Pseudonymize `comment_user`, `user_profile_url` per GDPR requirements.
- **Rate limit impact**: Same as Facebook -- no additional rate limit concern beyond the existing courtesy throttle.
- **Credential reuse**: Uses the same Bright Data API token (`platform="brightdata_instagram"`, `tier="medium"`). No new credentials needed.
- **Danish targeting note**: Since Instagram has no native language field, comments are collected via Danish actor accounts. Comments on Danish actors' posts are predominantly Danish regardless of commenter nationality, making this a viable approach for Danish discourse research.
- **Legal considerations**: Instagram comments on public accounts are publicly visible. However, many Danish Instagram accounts are private, and comments on private accounts are not accessible. GDPR pseudonymization is mandatory for all commenter identifiers. The arena brief (`docs/arenas/facebook_instagram.md`, line 128) already documented this scraper's existence.
- **Estimated engineering effort**: Small-to-moderate. Near-identical to the Facebook comment implementation.
- **Verdict**: **Easy to add. Same Bright Data pattern, same credential, same cost structure. Second-highest Danish relevance (56% usage). Recommended for Phase 1.**

#### Bluesky
- **API endpoint**: `app.bsky.feed.getPostThread` -- retrieves a post and its full reply tree. This endpoint is documented in the arena brief (`docs/arenas/bluesky.md`, line 46) and is authenticated (same session token as current collection).
- **Current collector behavior**: Collects posts via `searchPosts` and `getAuthorFeed`. The normalizer already captures `replyCount` (mapped to `comments_count`) and `reply_ref` (the `record.reply` field indicating whether a post is itself a reply). However, the collector does **not** follow reply threads.
- **What adding comments would require**:
  1. After collecting a post with `replyCount > 0`, call `getPostThread` with `uri={post_uri}&depth=6` (max depth).
  2. Traverse the `replies` array in the response recursively.
  3. Normalize each reply using the existing `normalize()` method with `content_type = "reply"`.
  4. Deduplicate by AT URI (replies from the same thread may overlap with search results).
- **Rate limit impact**: 3,000 req / 5 min (600/min) with authentication. Each `getPostThread` call is 1 request. For a collection of 1,000 posts with 30% having replies, this adds ~300 requests -- well within budget.
- **Tier**: FREE (no cost change)
- **Estimated engineering effort**: Small. The `normalize()` method already handles the post view format. The main work is adding a `_fetch_post_thread()` helper and wiring it into the collection flow.
- **Verdict**: **Easy to add. The AT Protocol's thread model maps cleanly to the universal schema.**

#### YouTube

**Option A: YouTube Data API v3 (FREE tier)**
- **API endpoint**: `commentThreads.list` (2 quota units per call) returns top-level comments and their replies for a video. `comments.list` (1 unit per call) returns replies to a specific comment.
- **Current collector behavior**: Collects video metadata via `search.list` (100 units/call) and `videos.list` (1 unit/50 videos). The normalizer already captures `commentCount` from video statistics. No comment content is collected.
- **What adding comments would require**:
  1. After enriching videos via `videos.list`, call `commentThreads.list?videoId={id}&part=snippet,replies&maxResults=100` for each video.
  2. Each response page returns up to 100 top-level comments and up to 5 inline replies per comment.
  3. For comments with more than 5 replies, call `comments.list?parentId={comment_id}` to paginate through remaining replies.
  4. Normalize each comment with `content_type = "comment"`, mapping `textDisplay`, `authorChannelId`, `likeCount`, `publishedAt`, and `parentId`.
- **Rate limit impact**: `commentThreads.list` costs 2 quota units per call. For 100 videos averaging 50 comments each, this is ~100 API calls = 200 quota units. Combined with `search.list` (100 units/call) and `videos.list` (1 unit/50 videos), a typical collection run might use 500-2,000 additional quota units. The daily quota is 10,000 units per API key.
- **Tier**: FREE (YouTube Data API v3 has no monetary cost)

**Option B: Bright Data YouTube Comments Scraper (MEDIUM tier)**
- **Dataset ID**: `gd_lk9q0ew71spt1mxywf`
- **Pricing**: $1.50 per 1,000 comment records (pay-as-you-go).
- **Input**: YouTube video URLs. Submitted as JSON array, e.g., `[{"url": "https://www.youtube.com/watch?v=XXXXX"}]`. Up to 5,000 URLs per trigger.
- **Output fields**: `comment_id`, `comment_text`, `likes`, `replies` (count), `username`, `timestamp`, `video_url`, `video_id`. Also includes nested reply objects.
- **Advantage over Data API**: Does NOT consume the YouTube Data API's 10,000 units/day quota. Runs independently, so comment collection has zero impact on video search capacity. Also avoids the need for quota budgeting logic.
- **Trade-off**: Costs money ($1.50/1K) vs. free Data API. For large-scale comment collection (e.g., 50,000+ comments/month), the cost may be significant.

**Recommendation**: Use the YouTube Data API (Option A) as the primary path since it is free and the quota impact is manageable for moderate collection volumes. Reserve the Bright Data scraper (Option B) for high-volume runs where quota is a binding constraint.

- **Estimated engineering effort**: Moderate for either option. Option A requires a new `_fetch_video_comments()` method and quota budgeting. Option B follows the Bright Data trigger/poll/download pattern.
- **Verdict**: **Easy to add with two viable paths. High Danish discourse value for news channels (DR, TV2, Berlingske).**

#### Gab
- **API endpoint**: Gab uses the Mastodon-compatible API. `GET /api/v1/statuses/{id}/context` returns the full conversation thread (ancestors and descendants) for any status.
- **Current collector behavior**: Collects statuses via search and account timelines. The normalizer already captures `replies_count`, `in_reply_to_id`, and `in_reply_to_account_id`. No reply threads are fetched.
- **What adding comments would require**:
  1. After collecting a status with `replies_count > 0`, call `GET /api/v1/statuses/{id}/context`.
  2. The response contains `{ "ancestors": [...], "descendants": [...] }`.
  3. Normalize each descendant status with `content_type = "reply"`, preserving `in_reply_to_id` for thread reconstruction.
- **Rate limit impact**: Gab's rate limits are Mastodon-standard (300 req/5 min). Each context call is 1 request. For a typical small collection of 200 statuses with 20% having replies, this adds ~40 requests.
- **Tier**: FREE (no cost change)
- **Estimated engineering effort**: Small. The `normalize()` method already handles the Mastodon status format. The main work is adding a `_fetch_status_context()` helper.
- **Verdict**: **Easy to add. Low Danish volume means this is a low priority, but the implementation is trivial.**

#### Telegram
- **API endpoint**: Telethon's `client.get_messages(entity, reply_to=message_id)` retrieves replies to a specific message in a Telegram channel's Discussion group. Alternatively, `message.replies` attribute already provides the reply count.
- **Current collector behavior**: Collects channel messages via `client.get_messages()` with search/pagination. The normalizer already captures `replies_count` (from `message.replies.replies`), `reply_to_msg_id`, and `is_forwarded`. No reply content is fetched.
- **What adding comments would require**:
  1. For messages with `replies_count > 0`, fetch replies via `client.get_messages(entity, reply_to=msg.id, limit=MAX_REPLIES)`.
  2. This requires the discussion group to be linked to the channel (most Danish news channels have this).
  3. Normalize each reply with `content_type = "reply"` and `parent_id = original_message_id`.
- **Rate limit impact**: Telethon's FloodWaitError is the binding constraint (approximately 20 req/min safe limit). Each reply-fetch is 1 API call per page (100 messages/page). For 500 channel posts with 10% having replies averaging 20 replies each, this adds ~10 API calls.
- **Tier**: FREE (no cost change)
- **Estimated engineering effort**: Moderate. The Telethon API for fetching replies requires resolving the linked discussion group, which adds complexity.
- **Verdict**: **Feasible with moderate effort. The linked discussion group resolution adds an implementation wrinkle.**

---

### 3.3 Possible but Complex (API supports it, significant constraints)

#### X/Twitter

**MEDIUM tier (TwitterAPI.io):**
- **API endpoint**: TwitterAPI.io does not appear to have a dedicated conversation/replies endpoint. The advanced search endpoint could be used with `conversation_id:{tweet_id}` as a search operator to fetch replies within a conversation thread, but this counts as a separate search query with associated costs.
- **Current collector behavior**: Collects tweets via `GET /twitter/tweet/advanced_search`. The normalizer maps `public_metrics.reply_count` to `comments_count` and includes `conversation_id` and `in_reply_to_user_id` in the tweet fields. Replies that match the `lang:da` search are already collected as independent tweets with `content_type = "post"`.
- **What adding comments would require**: For each collected tweet, issue a new search with `query=conversation_id:{tweet_id} lang:da` to fetch all Danish-language replies in the conversation. Each conversation fetch is a new paginated search request.
- **Rate limit impact**: 1 call/sec rate limit. Each conversation fetch is at least 1 additional API call. For 1,000 tweets with 20% having replies, this adds ~200 API calls at 1/sec = ~3 minutes of additional collection time plus ~$0.03 in additional cost (at $0.15/1K tweets).
- **Cost impact**: Each reply fetched costs the same as a regular tweet ($0.00015/tweet). For high-reply conversations, this could significantly increase costs.

**PREMIUM tier (X API v2 Pro):**
- **API endpoint**: `GET /2/tweets/search/all` with `query=conversation_id:{tweet_id}` retrieves all replies in a conversation thread. The API already returns `conversation_id` and `in_reply_to_user_id` in the current field set.
- **Rate limit impact**: 300 req/15 min = 15/min. Each conversation fetch is 1+ paginated calls. This is the binding constraint -- fetching replies for 200 conversations would consume most of the 15-minute budget.
- **Cost impact**: X API v2 Pro access is $5,000/month. No per-tweet cost, but the rate limit is the practical constraint.

- **Estimated engineering effort**: Moderate-to-high. Both tiers require a new method to fetch conversation threads, handle pagination, deduplicate against already-collected tweets, and manage the additional rate limit budget.
- **Verdict**: **Possible at MEDIUM tier via conversation_id search (adds cost). Possible at PREMIUM tier but rate-limit constrained. The `conversation_id` field is already collected, making thread reconstruction partially possible without additional API calls.**

#### TikTok

**Option A: TikTok Research API (FREE tier)**
- **API endpoint**: `POST /v2/research/video/comment/list/` returns `id`, `text`, `like_count`, `reply_count`, `create_time`, and `parent_comment_id`.
- **Current collector behavior**: Collects video metadata via `POST /v2/research/video/query/`. The normalizer maps `comment_count` to the universal schema. No comment content is fetched.
- **Rate limit impact**: The TikTok Research API has a **1,000 requests/day** global cap across ALL endpoints. Comment fetching consumes the same quota pool as video search. For 500 videos averaging 20 comments each, this would require ~100 API calls (500 * 20 / 100), consuming 10% of the daily quota.
- **Engagement lag**: Comments are subject to the same ~10-day accuracy lag as other engagement metrics.
- **Constraint**: The 1,000 req/day limit means comment collection directly competes with video collection. Needs careful quota budgeting.

**Option B: Bright Data TikTok Comments Scraper (MEDIUM tier) -- RECOMMENDED**
- **Dataset ID**: `gd_lkf2st302ap89utw5k`
- **Pricing**: $1.50 per 1,000 comment records (pay-as-you-go).
- **Input**: TikTok video URLs. Submitted as JSON array, e.g., `[{"url": "https://www.tiktok.com/@user/video/12345"}]`. Up to 5,000 URLs per trigger.
- **Output fields**: `comment_text`, `num_likes`, `num_replies`, `commenter_user_name`, `commenter_id`, `date_created`, `video_url`, `video_id`. Also includes nested `replies` when available.
- **Advantage over Research API**: The Bright Data scraper does NOT consume the TikTok Research API's 1,000 req/day quota. This completely eliminates the quota competition problem. Comment collection via Bright Data runs independently of the FREE-tier video search.
- **Integration pattern**: Same trigger/poll/download pattern as the Facebook and Instagram Bright Data collectors already in the codebase. Would require adding a Bright Data credential for TikTok (`platform="brightdata_tiktok"`, `tier="medium"`).
- **No engagement lag**: Bright Data scrapes comments at the time of request, so freshness is limited only by scraper execution time (typically 1-5 minutes), not the Research API's ~10-day lag.

**IMPORTANT NOTE**: The Research API comment endpoint availability needs verification. The TikTok Research API documentation has changed multiple times in 2025-2026. As of the last verified check, the comment list endpoint exists but may have additional access requirements beyond the base Research API approval.

- **Estimated engineering effort**: Moderate. Option A follows the existing Research API pattern. Option B follows the existing Bright Data pattern. Either way, the main work is a comment normalizer and collection flow.
- **Verdict**: **The Bright Data scraper (Option B) is strongly recommended over the Research API (Option A). It avoids the quota constraint, eliminates the engagement lag for comments, and follows an integration pattern already proven in the codebase. The only trade-off is cost ($1.50/1K records vs. free).**

#### Threads
- **API endpoint**: The Threads API provides `GET /{thread_id}/replies` to fetch replies to a specific thread. This endpoint returns the same fields as the regular threads endpoint (`id`, `text`, `timestamp`, `username`, `permalink`, etc.).
- **Current collector behavior**: Collects threads via `GET /{user_id}/threads`. The normalizer already captures `is_reply`, `has_replies`, `reply_to_id`, and `replies` (reply count, only for token owner's posts). The `content_type` is set to `"reply"` when `is_reply` is True.
- **What adding comments would require**:
  1. For posts with `has_replies = True`, call `GET /{thread_id}/replies?fields=id,text,timestamp,...`.
  2. Paginate via cursor-based pagination.
  3. Normalize using the existing `normalize()` method (already handles replies).
- **Critical constraint**: The Threads API uses **OAuth 2.0 user tokens with limited scope**. The `/{thread_id}/replies` endpoint **only works for threads authored by the authenticated user** (the token owner). You cannot fetch replies to threads authored by other users. This makes it useless for research-grade comment collection of third-party accounts.
- **Alternative**: The Meta Content Library (MCL) would provide comment access for any public thread, but MCL access is pending institutional approval (Phase 2 stub).
- **Rate limit impact**: 250 calls/hour. Each reply-fetch is 1+ paginated calls. The rate limit is manageable.
- **Tier**: FREE (limited to own threads), MEDIUM/MCL (pending approval)
- **Estimated engineering effort**: Small for own-thread replies. MCL integration is a separate Phase 2 project.
- **Verdict**: **Technically possible but practically useless at FREE tier due to the own-threads-only restriction. Requires MCL access (MEDIUM tier) for research-grade reply collection.**

---

### 3.4 Not Feasible (API doesn't support it or would require a different architecture)

#### Twitch
- **Current state**: The collector is a **deferred stub** that only returns channel metadata, not chat messages. Twitch does not have a historical chat API -- once a stream ends, chat messages are gone.
- **Chat collection**: Twitch chat is only accessible via the **EventSub WebSocket** (`channel.chat.message` subscription type) during live streams. This is a fundamentally different architecture (streaming, not batch) that requires:
  1. A persistent WebSocket connection (streaming worker).
  2. Real-time message processing and storage.
  3. An OAuth user access token with `user:read:chat` scope.
- **Comment/reply model**: Twitch chat is a flat message stream, not a threaded discussion. There is no concept of "replies to a message" in the Twitch API (chat messages may contain @mentions but have no parent-child relationship in the API).
- **Why it is not feasible**: The entire collection model is incompatible with batch comment collection. Twitch chat requires a streaming architecture that does not exist in the current system.
- **Verdict**: **Not feasible. Twitch chat is streaming-only with no historical access and no threaded reply model. Requires a dedicated streaming worker (separate initiative).**

---

### 3.5 Web-Based Arenas (Brief Assessment)

| Arena | Comments Applicable? | Notes |
|-------|---------------------|-------|
| **RSS Feeds** | No | RSS entries are published articles. Reader comments live on the publisher's website, not in the RSS feed. Comment collection would require scraping each article's web page. |
| **Wikipedia** | Partially | Wikipedia Talk pages are discussion threads, but they follow a unique wikitext format, not a standard comment API. The collector currently fetches revision history, not Talk page content. Adding Talk page parsing would be a separate feature. |
| **GDELT** | No | GDELT indexes news articles at the metadata level. No comment data. |
| **Event Registry** | No | Event Registry provides article metadata and full text. No comment data. |
| **Google Search** | No | Returns search result snippets only. |
| **Google Autocomplete** | No | Returns suggested search queries only. |
| **Common Crawl / Wayback** | Theoretically | Web archive snapshots may contain article comment sections. Extracting structured comments from arbitrary HTML is an NLP/scraping challenge beyond current scope. |
| **URL Scraper** | Theoretically | The Playwright-based scraper could extract comments from rendered web pages, but this requires per-site parsing rules. Not generalizable. |

---

## 4. Prioritized Implementation Roadmap

### Phase 1: Quick Wins (1-2 weeks engineering effort)

| Priority | Platform | Effort | Rationale |
|----------|----------|--------|-----------|
| 1 | **Facebook** (Bright Data Comments Scraper) | Small-moderate | Highest Danish usage (84%). Same Bright Data trigger/poll/download pattern already in codebase. Only needs a new dataset ID constant and comment normalizer. |
| 2 | **Instagram** (Bright Data Comments Scraper) | Small-moderate | Second-highest Danish usage (56%). Near-identical implementation to Facebook comments. Can share normalizer logic. |
| 3 | **Reddit** (expand to nested replies) | Small | Already implemented for top-level. Enable by default and add depth traversal. |
| 4 | **Bluesky** (add `getPostThread`) | Small | Free API, clean thread model, growing Danish user base. |

### Phase 2: High-Value Additions (2-4 weeks engineering effort)

| Priority | Platform | Effort | Rationale |
|----------|----------|--------|-----------|
| 5 | **YouTube** (Data API `commentThreads.list` + Bright Data fallback) | Moderate | High Danish discourse value (DR, TV2 channels). Two implementation paths. |
| 6 | **TikTok** (Bright Data Comments Scraper) | Moderate | Avoids Research API quota constraint entirely. 19% Danish TikTok usage and growing. |
| 7 | **X/Twitter** (conversation_id search) | Moderate | High discourse value but adds cost (MEDIUM) or rate-limit pressure (PREMIUM). |
| 8 | **Telegram** (discussion group replies) | Moderate | Moderate Danish relevance. Requires discussion group resolution logic. |

### Phase 3: Deferred (requires external access or architectural changes)

| Priority | Platform | Blocker | Estimated timeline |
|----------|----------|---------|--------------------|
| 9 | **Threads** (MCL for third-party replies) | MCL application pending institutional approval. FREE tier limited to own threads. | Phase 2 of MCL integration |
| 10 | **Gab** (add `/statuses/{id}/context`) | Trivial Mastodon API, but very low Danish relevance limits priority. | When Danish Gab activity warrants it |
| 11 | **Discord** (thread enumeration) | Moderate code, but thread access requires bot permissions per server. | Phase 2 |
| 12 | **Twitch** (streaming chat) | Requires new streaming worker architecture. No historical API. | Separate initiative |

---

## 5. Schema Considerations

The universal content record schema already supports comments through:

- `content_type`: String field (50 chars). Currently used values include `"post"`, `"video"`, `"comment"`, `"reply"`, `"chat_message"`. The `"comment"` type is already used by the Reddit collector.
- `raw_metadata` JSONB: Can store `parent_id`, `parent_post_id`, `thread_depth`, `in_reply_to_user_id`, and other threading metadata without schema migration.
- `comments_count`: Integer field already present on parent records.

**Recommended additions** (no schema migration required -- all go into `raw_metadata`):
- `raw_metadata.parent_content_record_id`: UUID reference to the parent post's content record (for in-database thread reconstruction)
- `raw_metadata.thread_depth`: Integer indicating nesting level (0 = top-level comment, 1 = reply to comment, etc.)
- `raw_metadata.root_post_platform_id`: The platform_id of the original post at the root of the thread

**Potential schema migration** (for future consideration):
- Adding a `parent_platform_id` column (String, nullable) to `content_records` would enable efficient thread reconstruction queries without JSONB path traversal. This is recommended if comment collection becomes a standard feature across 3+ arenas.

---

## 6. Architectural Recommendations

### 6.1 Collection Mode Toggle
Add a per-arena configuration flag in `arenas_config` JSONB on `query_designs`:
```json
{
  "reddit": {
    "include_comments": true,
    "max_comments_per_post": 50,
    "max_reply_depth": 3
  },
  "bluesky": {
    "include_replies": true,
    "max_thread_depth": 6
  }
}
```
This follows the existing pattern for `custom_subreddits`, `custom_channels`, etc.

### 6.2 Collection Ordering
Comments should be collected **after** the parent post collection is complete and persisted. This ensures:
1. The parent `content_record` exists in the database before comments reference it.
2. Deduplication can check whether a reply was already collected as a standalone post (e.g., a Bluesky reply matching the search term).
3. The collection runner can apply a comment budget (max comments across all posts) without over-fetching.

### 6.3 Rate Limit Budgeting
For platforms where comment fetching shares a quota pool with primary collection (YouTube, TikTok), the task runner should:
1. Reserve a percentage of the quota for comment collection (e.g., 30% of YouTube's 10,000 daily units).
2. Prioritize comments on high-engagement posts (sort by `comments_count` descending, collect top N).
3. Log quota usage separately for post collection vs. comment collection for cost transparency.

### 6.4 Deduplication
Comments collected via thread traversal may overlap with content already collected via search (e.g., a Bluesky reply that also matches the search term). The existing deduplication pipeline (URL hash + content hash + SimHash) should handle this, but the `content_type` field should be updated when a previously-collected `"post"` is identified as a `"reply"` or `"comment"` through thread traversal.

---

## 7. Legal Considerations

### GDPR
- Comments are personal data attributable to private individuals (unlike public figure posts). The project's pseudonymization pipeline (SHA-256 with salt) applies equally to comment authors.
- The `public_figure` bypass on the Actor model does **not** apply to commenters -- all comment authors must be pseudonymized.
- Retention policies should apply equally to comments and posts.

### Platform Terms of Service
- **X/Twitter**: The X API Terms allow collecting replies via search. No additional restrictions.
- **Bluesky**: The AT Protocol is open. No TOS restrictions on thread traversal.
- **YouTube**: The YouTube API Terms of Service permit collecting comments for research purposes via the Data API.
- **Reddit**: The Reddit API Terms allow comment collection for academic research. The User Agreement and API Terms were updated in 2024 to restrict commercial use, but academic research with no commercial intent remains permitted.
- **TikTok**: The Research API Terms permit comment collection for approved research projects. The project's existing TikTok Research API approval may already cover comment endpoints, but this should be verified with TikTok's research team.
- **Facebook/Instagram**: Comment collection via Bright Data Web Scraper API operates under Bright Data's compliance framework. Bright Data claims compliance with applicable laws and platform terms for public data collection. However, Meta's Terms of Service restrict automated scraping. The legal position is: (a) Bright Data assumes platform-access compliance responsibility as the data provider; (b) the project must still ensure GDPR compliance for all commenter personal data; (c) MCL access (pending institutional approval) would provide the most legally robust path for Meta platform comment data. For research purposes under GDPR Article 89 and Databeskyttelsesloven Paragraph 10, collecting publicly visible comments with proper pseudonymization is defensible.

### DSA Article 40
Comment collection falls within the scope of DSA Article 40 researcher access for VLOPs (Very Large Online Platforms). If the project obtains DSA researcher access, this would provide an additional legal basis for comment collection across Facebook, Instagram, TikTok, and X/Twitter.

---

## 8. Cost Impact Summary

| Platform | Current Cost | Additional Cost for Comments | Notes |
|----------|-------------|------------------------------|-------|
| **Facebook** | $1.50/1K posts | **+$1.50/1K comments** | Same Bright Data credential, new dataset ID. Cost is proportional to number of post URLs submitted. |
| **Instagram** | $1.50/1K posts | **+$1.50/1K comments** | Same Bright Data credential, new dataset ID. |
| Reddit | Free | Free | Same API, more requests |
| Bluesky | Free | Free | Same API, additional requests |
| YouTube (Data API) | Free | Free (quota cost) | ~200-2,000 additional quota units/day |
| YouTube (Bright Data) | Free (posts via Data API) | +$1.50/1K comments | Alternative to Data API quota; independent of video search. |
| **TikTok (Bright Data)** | Free (videos via Research API) | **+$1.50/1K comments** | Does NOT consume Research API quota. Independent collection path. |
| TikTok (Research API) | Free | Free (quota cost) | Shares 1,000 req/day budget with video search -- NOT recommended. |
| Gab | Free | Free | Minimal additional requests |
| Telegram | Free | Free | Same MTProto client |
| X/Twitter (MEDIUM) | $0.15/1K tweets | +$0.15/1K replies | Each reply costs the same as a tweet |
| X/Twitter (PREMIUM) | $5,000/month flat | No additional cost | Rate-limit constrained, not cost-constrained |
| Threads | Free | Free (own threads only) | Limited utility at FREE tier |

### Bright Data Comment Collection Cost Estimate

For a typical Danish discourse research project tracking 50 Danish public actors across Facebook and Instagram, with weekly collection:

| Scenario | Posts/week | Avg comments/post | Comments/week | Monthly cost |
|----------|-----------|-------------------|---------------|-------------|
| Facebook (50 pages) | ~500 | ~30 | ~15,000 | ~$90 |
| Instagram (50 profiles) | ~300 | ~20 | ~6,000 | ~$36 |
| TikTok (20 accounts) | ~100 | ~50 | ~5,000 | ~$30 |
| YouTube (20 channels) | ~50 | ~100 | ~5,000 | ~$30 |
| **Total** | | | **~31,000** | **~$186/month** |

These estimates assume moderate Danish public discourse accounts. High-engagement accounts (e.g., DR Nyheder, Mette Frederiksen) may have 10x more comments per post.

---

## 9. Open Questions Requiring Investigation

1. **TikTok Research API comment endpoint availability**: Does the current Research API approval include the `video/comment/list` endpoint? This needs verification with TikTok's research access team. (Note: the Bright Data alternative bypasses this question entirely.)
2. **Bright Data comment scraper reply nesting**: The Facebook and Instagram comment scrapers return a `replies` field. How deep does reply nesting go? Is it only one level (replies to top-level comments), or does it include full thread depth? This affects whether we need a separate "reply" fetch after the initial comment fetch.
3. **Threads API scope expansion**: Can the Threads API `/{thread_id}/replies` endpoint be used with a business account token to access replies on other public accounts? The documentation is ambiguous on this point.
4. **YouTube comment language filtering**: Does `commentThreads.list` support a language filter, or would Danish-language comment filtering need to happen client-side?
5. **Content record schema**: Should `parent_platform_id` be elevated to a first-class column for efficient thread reconstruction, or is `raw_metadata` JSONB sufficient for the initial implementation?
6. **Bright Data comment scraper rate of freshness**: When a post receives new comments after the initial scrape, does re-submitting the post URL return only new comments or all comments including previously collected ones? This affects deduplication strategy.
7. **Cost optimization**: Should comment collection be triggered for ALL collected posts, or only for posts exceeding a configurable `min_comments_threshold` (e.g., only fetch comments for posts with 5+ comments)? This could significantly reduce costs for Facebook and Instagram where many posts have few or no comments.

---

## 10. Recommendation

**Immediate action (this sprint)**:
1. **Facebook and Instagram comment collection via Bright Data**. These are the highest-impact additions due to Danish usage (84% and 56% respectively). The integration pattern is already proven in the codebase -- the only new work is adding dataset ID constants and comment normalizers. The implementation can be done in parallel since both follow the same pattern.
2. **Enable Reddit top-level comment collection by default** (`INCLUDE_COMMENTS_DEFAULT = True`) and add Bluesky thread fetching via `getPostThread`. These are the lowest-risk, lowest-cost additions.

**Next sprint**:
3. **YouTube comment collection** via Data API `commentThreads.list` with configurable quota budget. YouTube comments on Danish news channels (DR, TV2, Berlingske) are high-value discourse data. The Bright Data fallback provides a safety valve if quota is insufficient.
4. **TikTok comment collection via Bright Data scraper**. This eliminates the Research API quota constraint and engagement lag issues. Growing Danish TikTok usage (19%) makes this increasingly relevant.

**Defer**:
- **Threads**: Until MCL access is approved (FREE tier is own-threads-only).
- **X/Twitter reply threads**: Until the cost/rate-limit trade-off is better understood through usage data.
- **Twitch**: Requires streaming architecture (separate initiative).

### Bright Data Unified Comment Collection Module

A key architectural opportunity: since Facebook, Instagram, TikTok, and YouTube comments all use the same Bright Data trigger/poll/download pattern with identical pricing, it is worth building a **shared Bright Data comment collection module** rather than four separate implementations. This module would:
1. Accept a list of post/video URLs with a dataset ID parameter.
2. Submit them to the appropriate Bright Data Comment Scraper.
3. Poll for completion using the shared progress/snapshot endpoints.
4. Dispatch to a platform-specific normalizer for field mapping.

This reduces code duplication and makes adding future Bright Data comment scrapers (if they release one for X/Twitter, for example) trivial.

---

## Appendix A: Bright Data Comment Scraper Dataset Reference

All Bright Data comment scrapers use the same API infrastructure:
- **Base URL**: `https://api.brightdata.com/datasets/v3`
- **Trigger**: `POST /trigger?dataset_id={id}&include_errors=true`
- **Poll**: `GET /progress/{snapshot_id}`
- **Download**: `GET /snapshot/{snapshot_id}?format=json`
- **Authentication**: `Bearer {api_token}` header
- **Max URLs per trigger**: 5,000
- **Pricing**: $1.50/1K records (all platforms, pay-as-you-go)

| Platform | Dataset ID | Input Format | Key Output Fields |
|----------|-----------|--------------|-------------------|
| Facebook Comments | `gd_lkay758p1eanlolqw8` | `[{"url": "https://facebook.com/.../posts/..."}]` | `comment_id`, `comment_text`, `num_likes`, `num_replies`, `date`, `user_name`, `user_id`, `post_url` |
| Instagram Comments | `gd_ltppn085pokosxh13` | `[{"url": "https://instagram.com/p/..."}]` | `comment_user`, `comment` (text), `comment_date`, `likes_number`, `replies_number`, `post_url` |
| TikTok Comments | `gd_lkf2st302ap89utw5k` | `[{"url": "https://tiktok.com/@.../video/..."}]` | `comment_text`, `num_likes`, `num_replies`, `commenter_user_name`, `commenter_id`, `date_created`, `video_url` |
| YouTube Comments | `gd_lk9q0ew71spt1mxywf` | `[{"url": "https://youtube.com/watch?v=..."}]` | `comment_id`, `comment_text`, `likes`, `replies`, `username`, `timestamp`, `video_url` |

**Note on dataset IDs**: These IDs were verified via Bright Data's public product pages as of 2026-03-12. Dataset IDs can change if Bright Data updates or replaces scrapers. The IDs should be verified against the Bright Data dashboard before implementation begins.

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-12 (v2) | **Major correction**: Reclassified Facebook and Instagram from "Not Feasible" to "Easy to Add" based on Bright Data dedicated Comment Scraper datasets. Added Bright Data comment scrapers for TikTok and YouTube as alternatives to native APIs. Updated TikTok assessment with Bright Data Option B (avoids Research API quota constraint). Updated YouTube with dual-path recommendation. Added Appendix A with Bright Data comment scraper dataset reference table. Revised prioritization roadmap: Facebook and Instagram now Phase 1 priorities. Added cost estimation table for typical Danish research project. Updated legal considerations for Meta platform scraping. Added open questions about Bright Data reply nesting depth and freshness behavior. Added recommendation for shared Bright Data comment collection module. |
| 2026-03-12 | Initial report created. Full assessment of all 12 social media arenas plus web-based arenas. |
