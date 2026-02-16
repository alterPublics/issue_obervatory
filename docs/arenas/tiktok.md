# Arena Research Brief: TikTok

**Created**: 2026-02-16
**Last updated**: 2026-02-16
**Status**: Ready for implementation
**Phase**: 1 (Task 1.11, High priority)
**Arena path**: `src/issue_observatory/arenas/social_media/tiktok/`

---

## 1. Platform Overview

TikTok is a short-form video platform with approximately 1.7 billion monthly active users globally. In Denmark, TikTok penetration is approximately 19% of the population, making it the sixth most-used social media platform. TikTok's demographic skews young (primarily 16-30), and its algorithmic feed drives viral propagation of content across national borders. For Danish discourse research, TikTok captures political communication, news commentary, and cultural trends that are often underrepresented on text-centric platforms.

**Role in Danish discourse**: TikTok's 19% Danish penetration is modest compared to Facebook (84%) or Instagram (56%), but it is the primary platform for younger Danish users and increasingly important for political communication. Danish politicians, news outlets (DR, TV2), and activist organizations maintain active TikTok presences. Content about Danish topics also circulates in English and other languages on the platform. TikTok's algorithmic amplification means that Danish content can reach far beyond the platform's Danish user base.

**Access model**: The TikTok Research API provides academic access to video search, user information, and comments. Access has been confirmed for this project. The API uses OAuth 2.0 client credentials flow. Tokens expire every 2 hours. The free tier allows 1,000 requests/day. Bright Data provides a medium-tier fallback at $1/1K records for fresher data or higher volume.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | TikTok Research API | $0 | 1,000 requests/day, up to 100K records. Academic access confirmed. 10-day engagement lag. |
| **Medium** | Bright Data TikTok Scraper API | $1/1K records | ~4.1s response time. Near-real-time data. No engagement lag. |
| **Premium** | N/A | -- | No premium tier exists. |

**Phase 1 implementation**: Free tier only. The medium tier (Bright Data) is documented for future activation if the Research API's 10-day engagement lag or 1,000 requests/day limit proves insufficient.

---

## 3. API/Access Details

### TikTok Research API

**Base URL**: `https://open.tiktokapis.com/v2/research/`

**Authentication**: OAuth 2.0 Client Credentials flow.
1. Register an application at the TikTok for Developers portal (https://developers.tiktok.com/)
2. Apply for Research API access (academic/researcher application)
3. Obtain `client_key` and `client_secret`
4. Request access token: `POST https://open.tiktokapis.com/v2/oauth/token/` with `grant_type=client_credentials`
5. Access tokens expire every **2 hours** -- the collector must implement automatic token refresh

**Key Endpoints**:

| Endpoint | Method | Description | Auth Required |
|----------|--------|-------------|---------------|
| `POST /v2/oauth/token/` | POST | Obtain access token | client_key + client_secret |
| `POST /v2/research/video/query/` | POST | Search videos by keyword, hashtag, region, date range | Bearer token |
| `POST /v2/research/video/comment/list/` | POST | Get comments on a specific video | Bearer token |
| `POST /v2/research/user/info/` | POST | Get user profile information | Bearer token |
| `POST /v2/research/user/followers/` | POST | Get a user's followers | Bearer token |
| `POST /v2/research/user/following/` | POST | Get accounts a user follows | Bearer token |
| `POST /v2/research/user/liked_videos/` | POST | Get a user's liked videos | Bearer token |
| `POST /v2/research/user/pinned_videos/` | POST | Get a user's pinned videos | Bearer token |
| `POST /v2/research/user/reposted_videos/` | POST | Get a user's reposted videos | Bearer token |

**Video query endpoint** (`/v2/research/video/query/`):

Request body (JSON):
| Field | Type | Description |
|-------|------|-------------|
| `query` | object | Query conditions (see below) |
| `start_date` | string | Start date (YYYYMMDD format) |
| `end_date` | string | End date (YYYYMMDD format) |
| `max_count` | integer | Results per page (max 100) |
| `cursor` | integer | Pagination cursor (0-indexed) |
| `search_id` | string | Returned from first query; must be passed for subsequent pages |
| `is_random` | boolean | If true, returns random sample instead of ranked results |

**Query conditions**: The `query` object supports boolean logic with `and`, `or`, `not` operators containing arrays of condition objects:
| Condition | Field | Description |
|-----------|-------|-------------|
| `keyword` | `field_name: "keyword"`, `field_values: ["term1", "term2"]` | Keyword in video description |
| `hashtag` | `field_name: "hashtag_name"`, `field_values: ["tag1"]` | Hashtag filter |
| `region` | `field_name: "region_code"`, `field_values: ["DK"]` | Country/region code |
| `video_id` | `field_name: "id"`, `field_values: ["123"]` | Specific video ID |
| `username` | `field_name: "username"`, `field_values: ["user1"]` | Specific username |

**Response fields** (configurable via `fields` parameter):
- `id`, `video_description`, `create_time`, `region_code`, `share_count`, `view_count`, `like_count`, `comment_count`, `music_id`, `hashtag_names`, `username`, `effect_ids`, `playlist_id`, `voice_to_text`

**Rate limits**:
- **1,000 requests per day** (across all endpoints)
- **100 results per request** (max_count)
- Theoretical daily maximum: **100,000 records** (1,000 requests x 100 results)
- Rate limit reset: daily at UTC midnight
- No published per-minute rate limit, but aggressive bursting may trigger throttling

**Token management**:
- Access tokens expire every 2 hours
- The collector must detect 401 responses and automatically request a new token
- Token refresh does not count against the 1,000 daily request limit

### Bright Data TikTok (Medium Tier -- documented, not Phase 1)

**Type**: Scraper API / Dataset API
**Cost**: $1 per 1,000 records (scraper API), $500 per 200K records (datasets)
**Latency**: ~4.1 seconds per request
**Success rate**: ~100% reported
**Advantage**: Near-real-time data without the 10-day engagement lag
**Authentication**: Bright Data API key

---

## 4. Danish Context

- **Region filter**: The Research API supports `region_code: "DK"` to filter videos by the creator's registered region. This is the primary mechanism for identifying Danish content.
- **Language limitations**: The Research API does not provide a direct language filter parameter. Danish-language content must be identified by:
  1. Region code filter (`DK`)
  2. Client-side language detection on `video_description` and `voice_to_text` fields
  3. Danish keyword and hashtag searches
- **Danish hashtags**: Relevant hashtags include `#dkpol`, `#denmark`, `#danmark`, `#dansk`, `#danskpolitik`, `#dktiktok`, `#fyp` (combined with Danish keywords), and topic-specific tags.
- **Danish TikTok creators**: Danish politicians, media outlets (DR, TV2, BT), cultural figures, and activist organizations have active TikTok presences. These should be tracked via the `username` query condition.
- **voice_to_text field**: TikTok's Research API provides a `voice_to_text` transcription field for videos with spoken content. This is valuable for Danish content analysis since the primary content medium is video/audio, not text. The quality of Danish speech-to-text transcription via this field is unverified and should be evaluated during initial data collection.
- **Content volume**: At 19% Danish penetration, TikTok content volume about Danish topics is moderate. The 1,000 requests/day limit is likely sufficient for targeted keyword and actor-based collection.

---

## 5. Data Fields

Mapping to the Universal Content Record schema:

| UCR Field | TikTok Source | Notes |
|-----------|--------------|-------|
| `platform` | `"tiktok"` | Constant |
| `arena` | `"social_media"` | Constant |
| `platform_id` | `id` (video ID) | Globally unique |
| `content_type` | `"video"` | TikTok content is primarily video |
| `text_content` | `video_description` + `voice_to_text` | Concatenate description and transcription. `voice_to_text` may be empty. |
| `title` | `NULL` | TikTok videos have no separate title field |
| `url` | Constructed: `https://www.tiktok.com/@{username}/video/{id}` | Derived from username and video ID |
| `language` | Detect from `video_description` / `voice_to_text` | No native language field in API response |
| `published_at` | `create_time` | Unix timestamp |
| `collected_at` | Now | Standard |
| `author_platform_id` | `username` | TikTok username |
| `author_display_name` | `username` | Research API does not return display name in video query; must fetch via user info endpoint |
| `views_count` | `view_count` | Subject to 10-day engagement lag |
| `likes_count` | `like_count` | Subject to 10-day engagement lag |
| `shares_count` | `share_count` | Subject to 10-day engagement lag |
| `comments_count` | `comment_count` | Subject to 10-day engagement lag |
| `engagement_score` | Compute from views, likes, shares, comments | Normalize; note engagement lag caveat |
| `raw_metadata` | Full response object | See below |
| `media_urls` | `NULL` | Video URLs are not provided by Research API (only metadata) |
| `content_hash` | SHA-256 of normalized `video_description` | For deduplication |

**`raw_metadata` should include**:
- `region_code`: creator's region
- `hashtag_names`: array of hashtags on the video
- `music_id`: background music identifier
- `effect_ids`: applied effects
- `playlist_id`: if part of a playlist
- `voice_to_text`: full speech transcription
- `is_random`: whether result came from random sampling
- `search_id`: for pagination context

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Free | `{"client_key": "...", "client_secret": "..."}` | `"tiktok"` |
| Medium | `{"bright_data_api_key": "..."}` | `"bright_data_tiktok"` |

**Notes**:
- `client_key` and `client_secret` are obtained from the TikTok for Developers portal after Research API access is approved
- Academic access application requires institutional affiliation and research proposal
- Access has been confirmed for this project during planning phase
- The collector should cache the access token and refresh it automatically before or upon expiration (every 2 hours)
- For Phase 1, only the free tier credential is needed

---

## 7. Rate Limits and Multi-Account Notes

| Metric | Value | Notes |
|--------|-------|-------|
| Requests per day | 1,000 | Across all endpoints, per application |
| Results per request | 100 max | Video query endpoint |
| Max daily records | ~100,000 | Theoretical: 1,000 x 100 |
| Token expiry | 2 hours | Must auto-refresh |
| Rate limit reset | UTC midnight | Daily quota resets |

**Multi-account considerations**:
- The TikTok Research API rate limit is per application (client_key), not per user account
- Multiple Research API applications would require separate academic approvals, which is not practical
- If the 1,000 requests/day limit is reached, the medium tier (Bright Data) provides overflow capacity
- **Recommendation**: Use a single Research API application. The 1,000 requests/day limit (100K records) is substantial for targeted Danish collection. Reserve Bright Data for overflow or when real-time data is needed.

**RateLimiter configuration**: Set a conservative rate of ~40 requests per hour (960/day) to spread requests evenly across the day and avoid exhausting the daily quota in a burst. Track daily usage via Redis key `credential:quota:{id}:daily` with TTL until midnight UTC.

---

## 8. Known Limitations

1. **10-day engagement lag**: This is the most significant limitation. The Research API serves archived data, and TikTok states that accurate engagement statistics (view_count, like_count, share_count, comment_count) can take up to 10 days to finalize. Researchers report persistent discrepancies even after this period. For any analysis requiring accurate engagement metrics, data should be re-collected after the 10-day window. TikTok's policy requires data refresh every 15 days.

2. **No video content access**: The Research API provides metadata only -- video files, thumbnails, and audio are not available for download. The `voice_to_text` transcription field partially compensates by providing spoken content as text, but visual content analysis is not possible through this API alone.

3. **2-hour token expiry**: Access tokens have a short 2-hour lifetime. The collector must implement robust token refresh logic, detecting 401 responses and transparently obtaining new tokens without losing pagination state.

4. **No streaming/real-time API**: There is no firehose or event-driven API. All collection is polling-based. Combined with the 10-day engagement lag, TikTok is best suited for retrospective analysis rather than real-time monitoring.

5. **Region code limitations**: The `region_code` filter is based on the creator's account registration region, not content language or topic. Danish-language content from creators registered outside Denmark will be missed. Conversely, non-Danish content from DK-registered creators will be included.

6. **Date range constraint**: The video query endpoint requires `start_date` and `end_date` parameters. The maximum date range per query is 30 days. For longer historical collection, split into 30-day windows.

7. **Search result ordering**: Results are returned by TikTok's relevance ranking, not chronologically. For comprehensive collection, use the `is_random: true` parameter for random sampling, or paginate exhaustively through all results.

8. **Danish speech-to-text quality**: The `voice_to_text` field quality for Danish-language videos is unverified. TikTok's transcription may perform poorly on Danish speech. Flag with `WARNING: UNVERIFIED` in documentation and evaluate during initial data collection.

9. **API deprecation risk**: TikTok has faced legislative pressure in multiple countries (including potential US ban). The Research API could be affected by regulatory changes. The IMPLEMENTATION_PLAN.md risk register notes Bright Data as a fallback if the Research API is deprecated.

10. **Legal considerations**:
    - TikTok Research API is explicitly designed for academic research and governed by TikTok's Research API Terms of Service
    - GDPR applies to all collected personal data (usernames, video descriptions, speech transcriptions)
    - Standard pseudonymization via `pseudonymized_author_id` is required
    - TikTok is designated as a VLOP (Very Large Online Platform) under the EU Digital Services Act, which strengthens the legal basis for researcher access under DSA Article 40
    - Data must be refreshed every 15 days per TikTok's policy -- implement automated re-collection scheduling
    - Content involving minors is prevalent on TikTok; the DPIA should address collection of content by and about underage users

---

## 9. Collector Implementation Notes

### Architecture

- **Polling-based collection only**: No streaming capability. Implement `collect_by_terms` (keyword/hashtag search) and `collect_by_actors` (username-based search).
- **Token manager**: Implement a token cache with automatic refresh before expiration. Store the current token and its expiry time; refresh proactively at ~1:50 hours rather than waiting for 401 errors.
- **Engagement re-collection**: Implement a scheduled task to re-collect engagement metrics for videos older than 10 days but newer than 15 days, updating `views_count`, `likes_count`, `shares_count`, and `comments_count` in existing records.

### Key Implementation Guidance

1. **Token management**:
   - Store current access token and expiry timestamp in Redis
   - Refresh token when less than 10 minutes remain before expiry
   - Token request: `POST https://open.tiktokapis.com/v2/oauth/token/` with `client_key`, `client_secret`, `grant_type=client_credentials`
   - Parse response for `access_token` and `expires_in` (7200 seconds)

2. **Search-based collection** (`collect_by_terms`):
   - Build query object with `and`/`or` conditions combining keywords and `region_code: "DK"`
   - Set `start_date` and `end_date` within 30-day windows
   - Set `max_count: 100` for maximum results per request
   - Paginate using `cursor` and `search_id` from the first response
   - Continue until `has_more: false` or `max_results` reached
   - Apply client-side language detection on `video_description` for Danish content verification

3. **Actor-based collection** (`collect_by_actors`):
   - Map actor platform presences to TikTok usernames
   - Use the `username` query condition: `{"field_name": "username", "field_values": ["actor_username"]}`
   - Combine with date range parameters for bounded collection
   - Also fetch user profile info via `/v2/research/user/info/` for actor metadata

4. **Engagement metric refresh**:
   - Schedule a daily Celery Beat task to identify records collected 10-15 days ago
   - Re-query those videos by ID using the `id` query condition
   - Update engagement fields in existing records
   - Mark records with `raw_metadata.engagement_refreshed_at` timestamp

5. **Date windowing**:
   - For batch collection spanning more than 30 days, split into 30-day windows
   - Process windows sequentially to manage daily request budget
   - Track which windows have been completed for resume capability

6. **Health check**: `POST /v2/research/video/query/` with a minimal query (e.g., `keyword: "test"`, `region_code: "DK"`, date range of today, `max_count: 1`). Verify 200 response with valid JSON. Check remaining daily quota if the API provides this information.

7. **Credit cost**: 1 credit per API request (maps directly to the daily limit of 1,000). Pre-flight estimation: count the number of API requests needed based on query complexity and expected pagination depth.

8. **Error handling**:
   - 401: Token expired -- refresh and retry
   - 429: Rate limited -- log, wait, retry with exponential backoff
   - Response with `error.code`: Log the specific error code and message; some errors indicate query syntax issues rather than transient failures
