# Arena Research Brief: Reddit

**Created**: 2026-02-16
**Last updated**: 2026-02-16
**Status**: Ready for implementation
**Phase**: 1 (Task 1.6, Critical priority)
**Arena path**: `src/issue_observatory/arenas/social_media/reddit/`

---

## 1. Platform Overview

Reddit is a social discussion platform organized around topic-specific communities (subreddits). It is free for non-commercial and academic use at 100 queries per minute via OAuth. Reddit's value for Danish discourse research lies in r/Denmark and other Danish-language subreddits, which host substantive discussions on politics, news, and social issues that are often more detailed than equivalent discussions on other platforms.

**Role in Danish discourse**: Reddit is not among Denmark's most popular platforms by overall penetration, but r/Denmark (~350K+ members) is one of the most active Scandinavian subreddits. It hosts long-form discussions of Danish politics, news events, and social issues. The demographic skews younger (18-35) and more tech-literate than the Danish average. Reddit discussions often surface perspectives underrepresented in mainstream media.

**Access model**: Free API via OAuth 2.0 with 100 requests/minute. PRAW (Python Reddit API Wrapper) is the standard library. Pushshift is dead for external researchers; Arctic Shift provides historical data dumps.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | Reddit API via PRAW (100 req/min) | $0 | OAuth required. Non-commercial/academic use. Streaming support for real-time. |
| **Medium** | N/A | -- | No medium tier exists. |
| **Premium** | N/A | -- | Commercial API starts at ~$12K+/year, not needed for research. |

Reddit is a free-only arena for this project. The free API is sufficient for both search and streaming collection.

---

## 3. API/Access Details

### Reddit API via PRAW

**Library**: PRAW (Python Reddit API Wrapper) v7.7.1+
**Installation**: `pip install praw`

**Authentication**: OAuth 2.0 "script" application type.
1. Create an app at https://www.reddit.com/prefs/apps/
2. Select "script" type
3. Obtain `client_id` and `client_secret`
4. Use with a Reddit account username/password

**Key PRAW Methods**:

| Method | Description | Rate Cost |
|--------|-------------|-----------|
| `reddit.subreddit("Denmark").search(query, sort, time_filter)` | Search posts in a subreddit | 1 request |
| `reddit.subreddit("Denmark").hot/new/top(limit)` | Get posts by sort order | 1 request |
| `reddit.subreddit("Denmark").stream.submissions()` | Real-time new post stream | Persistent connection, polls internally |
| `reddit.subreddit("Denmark").stream.comments()` | Real-time new comment stream | Persistent connection, polls internally |
| `submission.comments.list()` | Get comments on a post | 1 request |
| `reddit.redditor("username").submissions.new(limit)` | Get user's posts | 1 request |
| `reddit.search(query, subreddit, sort, time_filter)` | Cross-subreddit search | 1 request |

**Search parameters**:
| Parameter | Values | Description |
|-----------|--------|-------------|
| `query` | string | Search query (supports Reddit search syntax) |
| `sort` | `relevance`, `hot`, `top`, `new`, `comments` | Sort order |
| `time_filter` | `all`, `year`, `month`, `week`, `day`, `hour` | Time range filter |
| `limit` | 1-100 | Results per request (max 100) |

**Search syntax**: Reddit search supports `title:query`, `selftext:query`, `author:username`, `subreddit:name`, `flair:text`, `url:domain`, `site:domain`, quoted phrases, and boolean `AND`/`OR`/`NOT`.

**Rate limits**: 100 requests per minute per OAuth client. PRAW handles rate limiting internally. Response headers include `X-Ratelimit-Remaining`, `X-Ratelimit-Reset`, `X-Ratelimit-Used`.

**Pagination**: Reddit uses `after`/`before` token-based pagination. Maximum ~1,000 results per listing (hard Reddit limitation). For larger result sets, use time-windowed queries.

---

## 4. Danish Context

- **Default subreddits** (from `danish_defaults.py`): `['Denmark', 'danish', 'copenhagen', 'aarhus']`
- **Additional relevant subreddits**: `dkfinance`, `scandinavia`, `NORDVANSEN`, and topic-specific Danish subreddits as discovered.
- **Language**: Reddit has no built-in language filter parameter. Danish content is identified by:
  1. Subreddit: r/Denmark content is predominantly Danish
  2. Client-side language detection on `title` and `selftext`
  3. Flair: some subreddits use Danish-language flair
- **Content language**: Posts in r/Denmark are a mix of Danish and English. English posts often discuss Denmark-related topics. The collector should store both and let downstream analysis filter by language.
- **Cultural context**: r/Denmark has active daily discussion threads ("Fri snak fredag", etc.) that aggregate many comments under a single post. These should be collected as comments, not just the parent post.

---

## 5. Data Fields

Mapping to the Universal Content Record schema:

| UCR Field | Reddit Source (Submission) | Reddit Source (Comment) | Notes |
|-----------|--------------------------|------------------------|-------|
| `platform` | `"reddit"` | `"reddit"` | Constant |
| `arena` | `"social_media"` | `"social_media"` | Constant |
| `platform_id` | `submission.id` (e.g., `1a2b3c`) | `comment.id` | Reddit's base-36 ID |
| `content_type` | `"post"` | `"comment"` | |
| `text_content` | `submission.selftext` | `comment.body` | Markdown format. Link posts have empty selftext. |
| `title` | `submission.title` | `NULL` (or parent post title in metadata) | Comments have no title |
| `url` | `submission.url` or `submission.permalink` | `comment.permalink` | `permalink` is the Reddit discussion URL; `url` may be an external link |
| `language` | Detect from text | Detect from text | No native language field |
| `published_at` | `datetime.fromtimestamp(submission.created_utc)` | `datetime.fromtimestamp(comment.created_utc)` | Unix timestamp |
| `collected_at` | Now | Now | Standard |
| `author_platform_id` | `submission.author.name` | `comment.author.name` | Username string; `[deleted]` if removed |
| `author_display_name` | `submission.author.name` | `comment.author.name` | Reddit uses username as display name |
| `views_count` | `NULL` | `NULL` | Reddit does not expose view counts via API |
| `likes_count` | `submission.score` | `comment.score` | Net score (upvotes minus downvotes). Reddit fuzzes this number. |
| `shares_count` | `submission.num_crossposts` | `NULL` | Crossposts |
| `comments_count` | `submission.num_comments` | `NULL` | |
| `engagement_score` | `submission.upvote_ratio` | `NULL` | Float 0-1 |
| `raw_metadata` | Full submission attributes | Full comment attributes | See below |
| `media_urls` | Extract from `submission.url` if image/video | `NULL` | |
| `content_hash` | SHA-256 of normalized text | SHA-256 of normalized text | |

**`raw_metadata` should include**:
- `subreddit`: subreddit name
- `subreddit_id`: subreddit ID
- `link_flair_text`: post flair
- `is_self`: whether it is a self/text post or link post
- `domain`: domain of linked URL (for link posts)
- `over_18`: NSFW flag
- `spoiler`: spoiler flag
- `stickied`: whether pinned
- `distinguished`: moderator/admin distinction
- `gilded`: awards count
- `parent_id`: for comments, the parent comment or post ID
- `depth`: comment depth in thread (0 = top-level reply)

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Free | `{"client_id": "...", "client_secret": "...", "username": "...", "password": "...", "user_agent": "IssueObservatory/1.0"}` | `"reddit"` |

**Notes**:
- `user_agent` must be descriptive and include a version number. Reddit blocks generic user agents.
- Reddit requires a user account for OAuth script-type apps. Create dedicated research accounts.
- Each credential set (client_id + account) shares the 100 req/min limit.

---

## 7. Rate Limits and Multi-Account Notes

| Metric | Value | Notes |
|--------|-------|-------|
| Requests per minute | 100 | Per OAuth client |
| Results per listing | 100 max | Per request |
| Max listing depth | ~1,000 | Hard Reddit API limit; use time windows for more |
| Streaming | Continuous | PRAW manages polling internally |

**Multi-account considerations**:
- Each Reddit OAuth app + account combination gets its own 100 req/min quota.
- Multiple accounts can be used via CredentialPool to increase throughput.
- Reddit's terms prohibit using multiple accounts to circumvent rate limits for commercial purposes. For non-commercial research, this is a grey area. Document in ethics paperwork.
- **Recommendation**: Start with a single account. Add additional accounts only if 100 req/min proves insufficient for the query design volume.
- PRAW instances are not thread-safe. Each Celery worker should create its own PRAW instance with its own credential from the pool.

**RateLimiter configuration**: PRAW handles rate limiting internally (sleeps when approaching the limit). The shared RateLimiter should be configured as a safety net at 90 req/min to leave headroom.

---

## 8. Known Limitations

1. **No language filter**: Reddit API has no `lang` parameter. Danish content must be identified by subreddit membership or client-side language detection. This means non-Danish content from r/Denmark (English posts) will also be collected.

2. **1,000-result listing limit**: Reddit API returns a maximum of ~1,000 results per listing, regardless of pagination. For comprehensive historical collection, use time-windowed queries (e.g., week-by-week) to work around this limit.

3. **Score fuzzing**: Reddit deliberately fuzzes vote scores to prevent manipulation. The `score` field is approximate, not exact. `upvote_ratio` provides a more stable engagement signal.

4. **Deleted content**: Authors can delete their posts/comments. Deleted content shows `[deleted]` for author and `[removed]` for moderator-removed content. The text content is lost. Consider collecting and storing content promptly.

5. **Pushshift is dead**: The historical archive Pushshift is restricted to Reddit moderators only. Arctic Shift (https://arctic-shift.org/) provides downloadable data dumps as an alternative for historical analysis, but not a live API.

6. **Rate limit for streaming**: PRAW streaming uses polling internally (checks for new items every few seconds). It is not a true push-based stream. There is a brief delay (seconds to ~1 minute) between post creation and detection.

7. **Comment tree complexity**: Popular posts can have thousands of nested comments. Fetching all comments requires multiple API calls (`submission.comments.replace_more(limit=None)`), which can be expensive. Consider setting a depth or count limit.

8. **Legal considerations**: Reddit API is free for non-commercial and academic use. The project qualifies. GDPR applies to usernames and post content (personal data). Standard pseudonymization via `pseudonymized_author_id` is sufficient. Reddit's API terms prohibit sharing raw data publicly -- only aggregated/anonymized results. This aligns with the project's GDPR approach.

9. **r/reddit4researchers**: Academic researchers can apply for formal research access via this subreddit, potentially receiving higher rate limits. Worth exploring but not blocking for Phase 1 implementation.

---

## 9. Collector Implementation Notes

### Architecture

- **Dual collection**: Implement both `collect_by_terms` (subreddit search) and `collect_by_actors` (user post history).
- **Streaming mode**: Implement `subreddit.stream.submissions()` and `subreddit.stream.comments()` for live tracking as a persistent Celery worker.
- **Comment collection**: Decide whether to collect comments automatically with posts or as a separate configurable step (comments significantly increase volume and API usage).

### Key Implementation Guidance

1. **PRAW instance per worker**: PRAW is not thread-safe. Each Celery worker must create its own `praw.Reddit` instance. Acquire credentials from CredentialPool at worker initialization, not per-task.

2. **Search strategy**:
   - For each search term, search across configured subreddits: `reddit.subreddit("Denmark+danish+copenhagen").search(term)`
   - Use `sort="new"` for chronological collection
   - Use `time_filter` to bound date ranges for batch collection
   - For comprehensive batch collection, chunk into weekly time windows to avoid the 1,000-result limit

3. **Streaming implementation**:
   - Run `subreddit.stream.submissions()` in a dedicated Celery worker
   - The stream yields new submissions as they appear
   - Filter by search terms client-side (stream does not support keyword filtering)
   - Store the last processed submission ID for restart recovery

4. **Comment collection strategy**:
   - By default, collect only top-level comments on matched submissions
   - Use `submission.comments.replace_more(limit=0)` to skip "load more comments" links (saves API calls)
   - For deep analysis, set `replace_more(limit=None)` but budget for high API usage

5. **Actor-based collection**:
   - Map actor platform presences to Reddit usernames
   - Use `reddit.redditor(username).submissions.new(limit=100)` and `.comments.new(limit=100)`
   - Paginate with `after` token for larger histories

6. **Deduplication**: Use `platform_id` (Reddit's post/comment ID) as the primary dedup key. The `UNIQUE(platform, platform_id, published_at)` constraint handles this at the database level.

7. **Health check**: Execute `reddit.subreddit("Denmark").hot(limit=1)` and verify a valid response. Check rate limit headers.

8. **Credit cost**: 0 credits (free tier only).

9. **User agent**: Set a descriptive user agent string: `"IssueObservatory/1.0 (research project; contact: <email>)"`. Reddit blocks requests with generic user agents.
