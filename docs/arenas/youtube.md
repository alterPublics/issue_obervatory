# Arena Research Brief: YouTube

**Created**: 2026-02-16
**Last updated**: 2026-02-16
**Status**: Ready for implementation
**Phase**: 1 (Task 1.7, Critical priority)
**Arena path**: `src/issue_observatory/arenas/social_media/youtube/`

---

## 1. Platform Overview

YouTube is the largest video platform globally. In Denmark, YouTube's ad audience reaches 4.69 million Danes (78.3% of the population), making it the single largest platform by reach. The YouTube Data API v3 is free with a quota of 10,000 units/day per Google Cloud project. YouTube is valuable for tracking Danish public discourse through news channels (DR, TV2), political commentary, and public debate videos.

**Role in Danish discourse**: YouTube is the second most-used platform for news in Denmark (28% of Danes get news from YouTube). Major Danish outlets (DR, TV2, Berlingske, Politiken) maintain active YouTube channels. Danish political parties, NGOs, and commentators also use YouTube. The platform captures video-based discourse not available on text-focused platforms.

**Access model**: Free API (quota-limited). RSS feeds for channel monitoring (free, no quota cost). Transcript extraction via third-party library (free, no API quota but requires proxies from server environments).

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | YouTube Data API v3 (10K units/day/project) + RSS feeds + youtube-transcript-api | $0 | Pool multiple GCP project API keys via CredentialPool to multiply quota. |
| **Medium** | N/A | -- | No medium tier. Free is sufficient with key pooling. |
| **Premium** | N/A | -- | Quota increases available on application to Google. |

YouTube is a free-only arena, but the quota constraint makes credential pooling essential for sustained collection.

---

## 3. API/Access Details

### YouTube Data API v3

**Base URL**: `https://www.googleapis.com/youtube/v3/`

**Authentication**: API key (for public data only) or OAuth 2.0 (for private data -- not needed for this project). API key passed as `key` query parameter.

**Key Endpoints and Quota Costs**:

| Endpoint | Method | Quota Cost | Description |
|----------|--------|------------|-------------|
| `search` | GET | **100 units** | Search for videos, channels, playlists |
| `videos` | GET | **1 unit** | Video metadata, statistics, snippet (batch up to 50 IDs) |
| `channels` | GET | **1 unit** | Channel metadata and statistics |
| `commentThreads` | GET | **1 unit** | Top-level comments on a video |
| `comments` | GET | **1 unit** | Replies to a comment |
| `captions` | GET | **50 units** | Download caption track (requires OAuth) |

**Search endpoint parameters**:

| Parameter | Description |
|-----------|-------------|
| `q` | Search query |
| `type` | `video`, `channel`, `playlist` |
| `order` | `date`, `rating`, `relevance`, `title`, `viewCount` |
| `publishedAfter` | ISO 8601 timestamp (e.g., `2026-01-01T00:00:00Z`) |
| `publishedBefore` | ISO 8601 timestamp |
| `relevanceLanguage` | ISO 639-1 language code (e.g., `da`) -- biases results toward this language |
| `regionCode` | ISO 3166-1 alpha-2 country code (e.g., `DK`) |
| `maxResults` | 1-50 per page |
| `pageToken` | Pagination token |
| `part` | Required: `snippet`. Optional: `id` |

**Videos endpoint (batch metadata)**:

| Parameter | Description |
|-----------|-------------|
| `id` | Comma-separated video IDs (up to 50) |
| `part` | `snippet,statistics,contentDetails,topicDetails,localizations` |

This is the most efficient endpoint: 1 unit for up to 50 video metadata lookups.

**Quota System**:
- Default: 10,000 units per day per Google Cloud project
- Resets at midnight Pacific Time (UTC-8)
- Search is the most expensive operation at 100 units each
- Default quota allows: 100 searches/day OR 10,000 video lookups/day OR a mix
- Quota increase: Apply via Google Cloud console. Requires justification. Approval is not guaranteed.

### YouTube RSS Feeds (No Quota Cost)

**Channel feed**: `https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}`
**Playlist feed**: `https://www.youtube.com/feeds/videos.xml?playlist_id={PLAYLIST_ID}`

- Returns the 15 most recent videos in Atom XML format
- Updates within minutes of new uploads
- No authentication required
- No quota cost
- Cannot filter by search terms or date range
- Ideal for monitoring specific Danish channels for new content

### youtube-transcript-api (Transcripts)

**Library**: `youtube-transcript-api`
**Installation**: `pip install youtube-transcript-api`

- Extracts timestamped captions/subtitles without API key
- Supports auto-generated and manually uploaded captions
- YouTube actively blocks cloud provider IP ranges -- residential proxies ($5-50/month) required for server-side deployment
- Not all videos have captions; auto-generated captions are available for most spoken-language videos
- Quality varies; auto-generated Danish captions have moderate accuracy

---

## 4. Danish Context

- **`relevanceLanguage=da`**: Biases search results toward Danish-language content. This is not a hard filter -- English results may still appear. Use in combination with `regionCode=DK`.
- **`regionCode=DK`**: Restricts results to videos available in Denmark and biases toward Danish content.
- **Both parameters together** provide the best Danish filtering available, though neither guarantees Danish-only results.
- **Key Danish YouTube channels** to monitor via RSS (non-exhaustive):
  - DR (Danmarks Radio): multiple channels for news, documentaries, entertainment
  - TV2 Danmark
  - Berlingske
  - Politiken
  - Danish Parliament (Folketinget)
  - Danish political parties
  - Danish influencers and commentators
- **Transcript language**: For `youtube-transcript-api`, request Danish transcripts with `languages=['da']`. Fall back to auto-generated if manual transcripts are unavailable.

---

## 5. Data Fields

Mapping to the Universal Content Record schema:

| UCR Field | YouTube Source | Notes |
|-----------|--------------|-------|
| `platform` | `"youtube"` | Constant |
| `arena` | `"social_media"` | Constant |
| `platform_id` | `video.id` (e.g., `dQw4w9WgXcQ`) | 11-character video ID |
| `content_type` | `"video"` or `"comment"` | |
| `text_content` | `video.snippet.description` or transcript text or `comment.snippet.textDisplay` | For videos: description + transcript if available. For comments: comment text. |
| `title` | `video.snippet.title` | Video title |
| `url` | `https://www.youtube.com/watch?v={id}` | Constructed |
| `language` | `video.snippet.defaultLanguage` or `defaultAudioLanguage` | May be null; detect from title/description |
| `published_at` | `video.snippet.publishedAt` | ISO 8601 |
| `collected_at` | Now | Standard |
| `author_platform_id` | `video.snippet.channelId` | Channel ID |
| `author_display_name` | `video.snippet.channelTitle` | Channel name |
| `views_count` | `video.statistics.viewCount` | |
| `likes_count` | `video.statistics.likeCount` | May be hidden by uploader |
| `shares_count` | `NULL` | YouTube API does not expose share count |
| `comments_count` | `video.statistics.commentCount` | May be disabled |
| `engagement_score` | Compute from views, likes, comments | Normalized |
| `raw_metadata` | Full video resource | Store: `contentDetails.duration`, `topicDetails.topicCategories`, `snippet.tags`, `snippet.categoryId`, `statistics` (full), `snippet.thumbnails` |
| `media_urls` | `[snippet.thumbnails.high.url]` | Thumbnail URL |
| `content_hash` | SHA-256 of normalized title + description | |

**Comment fields**:

| UCR Field | YouTube Comment Source |
|-----------|-----------------------|
| `platform_id` | `comment.id` |
| `content_type` | `"comment"` |
| `text_content` | `comment.snippet.textDisplay` |
| `title` | `NULL` |
| `url` | Constructed from video URL + comment ID |
| `author_platform_id` | `comment.snippet.authorChannelId.value` |
| `author_display_name` | `comment.snippet.authorDisplayName` |
| `likes_count` | `comment.snippet.likeCount` |
| `published_at` | `comment.snippet.publishedAt` |

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Free | `{"api_key": "AIza..."}` | `"youtube"` |

**Multi-key pooling**:
- Each API key comes from a separate Google Cloud project
- Each project has its own 10,000 units/day quota
- Pool N keys to get N x 10,000 units/day
- **Recommendation**: Start with 3-5 GCP project keys for 30,000-50,000 units/day
- Creating GCP projects is free. API keys for YouTube Data API are free.

---

## 7. Rate Limits and Multi-Account Notes

| Metric | Value | Notes |
|--------|-------|-------|
| Daily quota | 10,000 units / GCP project | Resets at midnight Pacific Time |
| Search cost | 100 units per call | Max 50 results per call |
| Video metadata cost | 1 unit per call | Batch up to 50 video IDs per call |
| Comment cost | 1 unit per call | |
| Requests per second | Not formally published | Empirically ~10-20 req/sec before throttling |
| RSS feeds | Unlimited | No quota, no auth |

**Multi-key strategy** (essential for this arena):
- Create multiple GCP projects, each with YouTube Data API v3 enabled
- Add each API key to the CredentialPool with `daily_quota=10000`
- The CredentialPool tracks usage per key and rotates to available keys
- Set `quota_reset_at` to next midnight Pacific Time for each key

**Quota optimization strategy**:
1. Use RSS feeds to detect new videos from monitored channels (0 quota cost)
2. Use `videos` endpoint to batch-fetch metadata for discovered videos (1 unit per 50 videos)
3. Reserve `search` endpoint for keyword-based discovery (100 units each -- use sparingly)
4. Collect comments selectively (1 unit per page of ~20 comments)

**RateLimiter configuration**: Track quota units consumed, not just request count. The RateLimiter must understand that search = 100 units while videos.list = 1 unit.

---

## 8. Known Limitations

1. **Search is expensive**: At 100 units per search call, the default 10,000 unit quota allows only 100 searches per day per key. This is the primary bottleneck. Mitigate with key pooling and RSS-first strategy.

2. **Search result delay**: New videos may take hours to appear in search results, even though they appear in `videos.list` and RSS feeds within minutes. For timely collection, do not rely solely on search.

3. **No share count**: The YouTube API does not expose how many times a video has been shared. This is a gap in engagement metrics.

4. **Like count may be hidden**: Video owners can choose to hide the like count. When hidden, `likeCount` is not returned.

5. **Transcript proxy requirement**: `youtube-transcript-api` is actively blocked on cloud provider IPs (AWS, GCP, Azure). Residential proxies ($5-50/month) are required for server-side transcript extraction. This adds operational complexity and cost.

6. **Quota reset timing**: Quotas reset at midnight Pacific Time, not UTC. The CredentialPool must account for this timezone difference.

7. **`relevanceLanguage` is a bias, not a filter**: Setting `relevanceLanguage=da` biases results toward Danish but does not guarantee it. English-language videos about Denmark will also appear. Client-side language filtering may be needed.

8. **Comment pagination**: Popular videos can have millions of comments. Fetching all comments is impractical. Set a configurable comment limit per video (e.g., top 100 comments by relevance).

9. **Legal considerations**: YouTube Data API Terms of Service allow data collection for research. Data must not be stored for more than 30 days unless refreshed (YouTube's "Authorized Data" policy). However, for academic research under GDPR Art. 89, longer retention with pseudonymization is defensible. Document this in the DPIA. Standard `pseudonymized_author_id` applies.

10. **Category mapping**: YouTube uses numeric category IDs (e.g., 25 = News & Politics). Map these to human-readable names in the normalizer for `raw_metadata`.

---

## 9. Collector Implementation Notes

### Architecture

- **Three collection modes**:
  1. RSS feed monitoring for new videos from tracked channels (zero quota cost)
  2. Search-based keyword discovery (expensive -- 100 units/search)
  3. Batch metadata enrichment (cheap -- 1 unit per 50 videos)
- **Separate transcript worker**: Transcript extraction should be a separate optional step, triggered after video collection, running through a proxy.

### Key Implementation Guidance

1. **RSS-first strategy**:
   - Maintain a list of Danish YouTube channel IDs in `danish_defaults.py`
   - Poll RSS feeds for each channel at 15-30 minute intervals (configurable)
   - Parse Atom XML to extract new video IDs and basic metadata
   - Queue new video IDs for batch metadata enrichment via `videos.list`
   - This approach uses 0 search quota and provides near-real-time detection

2. **Search-based discovery** (`collect_by_terms`):
   - Use `search` endpoint with `relevanceLanguage=da`, `regionCode=DK`
   - Set `publishedAfter`/`publishedBefore` for date-bounded batch collection
   - Paginate with `pageToken` (max 50 results per page)
   - Budget: each search term x each pagination page = 100 units
   - Immediately batch-fetch full metadata for discovered video IDs via `videos.list`

3. **Batch metadata enrichment**:
   - Collect video IDs from RSS and search
   - Call `videos.list` with up to 50 IDs comma-separated per request (1 unit)
   - Request `part=snippet,statistics,contentDetails,topicDetails`
   - This is the most quota-efficient way to get full video data

4. **Actor-based collection** (`collect_by_actors`):
   - Map actors to YouTube channel IDs
   - Use RSS feed for each channel (free) to get recent video IDs
   - Use `search` endpoint with `channelId` parameter for historical search (100 units each)
   - Alternatively, use `playlistItems` endpoint with the channel's "uploads" playlist ID (1 unit) -- derive uploads playlist ID by replacing `UC` prefix of channel ID with `UU`

5. **Comment collection**:
   - Use `commentThreads` endpoint with `videoId` parameter
   - `order=relevance` for most-engaged comments first
   - Set a per-video comment limit (configurable, default 100)
   - 1 unit per page of ~20 comments

6. **Transcript collection** (optional):
   - Use `youtube-transcript-api` with residential proxy
   - Request `languages=['da', 'en']` with Danish priority
   - Store transcript text in `text_content` (appended to description) or as a separate content record
   - Handle `TranscriptsDisabled`, `NoTranscriptFound` errors gracefully

7. **Quota tracking**: The CredentialPool must track quota units consumed (not just request count). Implement a `quota_unit_cost` lookup:
   - `search`: 100 units
   - `videos.list`: 1 unit
   - `channels.list`: 1 unit
   - `commentThreads.list`: 1 unit
   - `comments.list`: 1 unit

8. **Health check**: Execute `videos.list` with a known video ID and verify response. Check remaining quota from response headers.

9. **Credit cost mapping**: 1 credit = 1 YouTube API unit. A search costs 100 credits. A video lookup costs 1 credit. This directly maps to the credit system.
