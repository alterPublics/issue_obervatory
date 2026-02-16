# Arena Research Brief: Threads

**Created**: 2026-02-16
**Last updated**: 2026-02-16
**Status**: Ready for implementation
**Phase**: 2 (Task 2.6, High priority)
**Arena path**: `src/issue_observatory/arenas/social_media/threads/`

---

## 1. Platform Overview

Threads is Meta's text-based social media platform, launched in July 2023 as a competitor to X/Twitter. Built on Instagram's infrastructure, Threads is tightly integrated with Instagram accounts -- users sign up using their Instagram credentials. As of early 2026, Threads has grown rapidly with an estimated 200+ million monthly active users globally. The platform supports the ActivityPub protocol (Fediverse integration), though this remains in beta.

**Role in Danish discourse**: Threads' Danish user base is growing but still small. The platform is attracting some of the same journalist, media professional, and public commentator audience that migrated from X/Twitter to Bluesky. Threads is not yet among the platforms tracked in Danish social media surveys (no penetration figure is published by Danmarks Statistik or DataReportal for Denmark specifically). It is an emerging platform worth monitoring, but Danish content volume is expected to be low in the near term. Threads may grow in importance if X/Twitter continues to alienate users and if Meta's institutional promotion of the platform gains traction.

**Access model**: Threads offers a free public API (launched June 2024) with limited research utility. The Meta Content Library (MCL) includes Threads data since February 2025, providing the richest research access if approved. There is no third-party scraping service specifically for Threads at competitive pricing.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | Threads API (Official, public) | $0 | OAuth 2.0 required. Publishing, content retrieval, reply management, keyword/mention search. Rate limits apply. |
| **Medium** | Meta Content Library (MCL) | $371/month + $1,000 setup (via SOMAR/ICPSR) | MCL includes Threads since February 2025. Access to public content from profiles with 1,000+ followers. Same application as Facebook/Instagram MCL. |
| **Premium** | N/A | -- | MCL is the highest tier available. |

**Note**: The Threads API and MCL represent fundamentally different access paths. The Threads API is designed for app developers (publishing, managing your own content, webhooks), not researchers. MCL provides the research-grade search and bulk retrieval capabilities. The free tier is usable for targeted collection but limited for large-scale research.

---

## 3. API/Access Details

### Free Tier: Threads API

**Base URL**: `https://graph.threads.net/v1.0/`

**Authentication**: OAuth 2.0. Requires a Meta Developer account and a registered app with Threads API permissions.

**Setup**:
1. Create a Meta Developer account at developers.facebook.com
2. Create an app and add the Threads use case
3. Configure OAuth redirect URL
4. Generate access tokens (short-lived: 1 hour; long-lived: 60 days)

**Key Endpoints**:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /{user_id}/threads` | GET | Get a user's threads (posts) |
| `GET /{thread_id}` | GET | Get a single thread (post) with fields |
| `GET /{thread_id}/replies` | GET | Get replies to a thread |
| `GET /{user_id}/threads_search` | GET | Search user's threads by keyword |
| `POST /{user_id}/threads` | POST | Publish a new thread (not needed for research) |
| `GET /{user_id}/threads_insights` | GET | Analytics for user's own threads |
| `GET /{thread_id}/conversation` | GET | Get full conversation thread |

**Search capabilities** (`/{user_id}/threads_search`):

| Parameter | Type | Description |
|-----------|------|-------------|
| `q` | string | Search query (keyword or mention) |
| `fields` | string | Comma-separated fields to return |
| `limit` | integer | Results per page |
| `after`/`before` | string | Pagination cursors |

**Available fields** (requested via `fields` parameter):

| Field | Description |
|-------|-------------|
| `id` | Thread ID |
| `text` | Post text content |
| `timestamp` | ISO 8601 creation time |
| `media_type` | `TEXT_POST`, `IMAGE`, `VIDEO`, `CAROUSEL_ALBUM`, `REPOST_FACADE` |
| `media_url` | URL of image or video |
| `permalink` | Permanent URL to the thread on Threads.net |
| `username` | Author's username |
| `shortcode` | Short identifier for the thread |
| `is_quote_post` | Whether this is a quote post |
| `is_reply` | Whether this is a reply |
| `is_repost` | Whether this is a repost (equivalent of retweet) |
| `has_replies` | Whether the thread has replies |
| `root_post` | The root post of a conversation (for replies) |
| `replied_to` | The post this is a reply to |
| `quoted_post` | The quoted post (for quote posts) |
| `reposted_post` | The original post (for reposts) |
| `hide_status` | Content moderation status |
| `reply_audience` | Who can reply (everyone, accounts_you_follow, mentioned_only) |
| `alt_text` | Image alt text |
| `link_attachment_url` | URL of attached link |

**Engagement metrics** (via `threads_insights` -- for own account only):

| Metric | Description |
|--------|-------------|
| `views` | Number of views |
| `likes` | Number of likes |
| `replies` | Number of replies |
| `reposts` | Number of reposts |
| `quotes` | Number of quotes |
| `shares` | Number of shares |

**Critical limitation**: The `threads_insights` endpoint only returns analytics for the authenticated user's own posts. You cannot retrieve engagement metrics (likes, replies, reposts, views) for other users' posts through the Threads API. This severely limits the API's research utility -- you can see post text and metadata but not how much engagement it received, unless you are the post's author.

**Webhooks** (real-time notifications):
- Threads API supports webhooks for new replies, mentions, and other events
- Configured via the Meta Developer dashboard
- Useful for real-time monitoring of mentions of specific terms
- Limited to events related to the authenticated app's user

**Rate limits**:

| Limit Type | Value | Notes |
|------------|-------|-------|
| Per-user rate limit | 250 API calls per hour | Per authenticated user token |
| Per-app rate limit | Varies | Based on app's active user count |
| Publishing limit | 250 posts per 24 hours | Per user (not relevant for research) |
| Search results | Paginated | No documented maximum total results |

**Token management**:
- Short-lived tokens: 1 hour validity
- Long-lived tokens: 60 days validity
- Long-lived tokens can be refreshed before expiry
- Token refresh: `GET /refresh_access_token?grant_type=th_refresh_token&access_token={token}`

### Medium Tier: Meta Content Library (MCL)

The MCL integration for Threads follows the same pattern as Facebook/Instagram MCL access documented in `/docs/arenas/facebook_instagram.md`. Key Threads-specific details:

**Threads coverage in MCL**:
- Included since February 2025
- Covers public content from profiles with 1,000+ followers
- Search, date range, and content type filtering
- Engagement metrics available (likes, replies, reposts, views)
- Near-real-time access

**Threads-specific limitation in MCL**:
- Threads data **cannot be exported as CSV** from MCL. Analysis must occur within the cleanroom environment.
- This is a critical difference from Facebook and Instagram MCL access, which support CSV export for large accounts.

**Application**: Same application process as Facebook/Instagram MCL (see `/docs/arenas/facebook_instagram.md` section 3). A single MCL approval covers Facebook, Instagram, and Threads.

---

## 4. Danish Context

- **Danish Threads adoption**: No published penetration figure exists for Denmark specifically. Based on global adoption patterns and Denmark's demographics (high smartphone penetration, Instagram at 56%), Threads likely has a small but growing Danish user base, estimated in the low hundreds of thousands.
- **Content language**: Threads does not provide a native language filter. Danish content must be identified through:
  - Searching for Danish keywords and hashtags
  - Targeting known Danish accounts
  - Client-side language detection on post text
- **Key Danish Threads users** (speculative, based on platform migration patterns):
  - Danish journalists who joined Threads alongside or instead of Bluesky
  - Media outlet accounts (DR, TV2, Berlingske)
  - Politicians and public figures who maintain Instagram presences (Threads is linked to Instagram)
  - Tech and media commentators
- **Content volume**: Low. Danish Threads content is expected to be orders of magnitude lower than Facebook, lower than Instagram, and comparable to or lower than Bluesky. The platform is worth monitoring for trend detection but will not provide high-volume Danish discourse data in the near term.
- **Overlap with Bluesky**: Both platforms attract X/Twitter migrants. Some Danish users post on both Bluesky and Threads. The `content_hash` deduplication mechanism will catch identical cross-posts.

---

## 5. Data Fields

Mapping to the Universal Content Record schema:

### Free Tier (Threads API)

| UCR Field | Threads API Source | Notes |
|-----------|-------------------|-------|
| `platform` | `"threads"` | Constant |
| `arena` | `"social_media"` | Constant |
| `platform_id` | `id` | Thread ID |
| `content_type` | `"post"` | Posts, replies, quotes, reposts all map to `"post"` |
| `text_content` | `text` | Post text content |
| `title` | `NULL` | Threads posts have no title |
| `url` | `permalink` | Permanent URL |
| `language` | Detect from `text` | Threads API does not expose language metadata |
| `published_at` | `timestamp` | ISO 8601 |
| `collected_at` | Now | Standard |
| `author_platform_id` | Derive from API context (user_id) | The API returns `username` but not a stable numeric user ID for other users' posts |
| `author_display_name` | `username` | Username (display name not separately available) |
| `views_count` | `NULL` | Not available for other users' posts via API |
| `likes_count` | `NULL` | Not available for other users' posts via API |
| `shares_count` | `NULL` | Not available for other users' posts via API |
| `comments_count` | `NULL` | Not available for other users' posts via API |
| `engagement_score` | `NULL` | Cannot compute without engagement metrics |
| `raw_metadata` | Full API response | Store: `media_type`, `is_quote_post`, `is_reply`, `is_repost`, `reply_audience`, `root_post`, `replied_to`, `quoted_post`, `reposted_post`, `link_attachment_url`, `alt_text`, `hide_status` |
| `media_urls` | `[media_url]` | Image or video URL (single; carousel items require separate calls) |
| `content_hash` | SHA-256 of normalized `text` | For deduplication |

### Medium Tier (MCL)

| UCR Field | MCL Source | Notes |
|-----------|-----------|-------|
| `platform` | `"threads"` | Constant |
| `arena` | `"social_media"` | Constant |
| `platform_id` | `post.id` | MCL post ID |
| `content_type` | `"post"` | |
| `text_content` | `post.text` | Post text |
| `title` | `NULL` | |
| `url` | `post.permalink` | |
| `language` | `post.language` | MCL may provide language metadata |
| `published_at` | `post.creation_time` | |
| `collected_at` | Now | |
| `author_platform_id` | `post.creator_id` | |
| `author_display_name` | `post.creator_name` | |
| `views_count` | `post.view_count` | Available in MCL |
| `likes_count` | `post.likes_count` | Available in MCL |
| `shares_count` | `post.reposts_count` | Reposts |
| `comments_count` | `post.replies_count` | |
| `engagement_score` | Compute from all metrics | Normalized |
| `raw_metadata` | Full MCL response | Store all available fields |
| `media_urls` | Extract from media objects | |
| `content_hash` | SHA-256 of normalized `text` | |

**The engagement metric gap is the primary difference between tiers.** The free Threads API does not provide engagement metrics for other users' posts, making it suitable only for text collection and conversation structure analysis, not for engagement-based research. MCL provides full engagement metrics.

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Free (Threads API) | `{"app_id": "12345", "app_secret": "secret", "access_token": "long-lived-token"}` | `"threads"` |
| Medium (MCL) | Same as Facebook/Instagram MCL (see `/docs/arenas/facebook_instagram.md`) | `"meta_content_library"` |

**Token refresh for free tier**:
- Long-lived tokens expire after 60 days
- Implement automatic token refresh in the CredentialPool: refresh tokens at least 7 days before expiry
- Store token expiry timestamp in `api_credentials.quota_reset_at` and use it as a refresh trigger
- If a token expires without refresh, manual re-authentication is required (OAuth flow)

**Multi-account**:
- Free tier: Each Threads account provides its own OAuth token. Multiple accounts can be pooled for higher throughput (250 API calls/hour per account).
- However: creating multiple Threads accounts requires multiple Instagram accounts. Threads accounts cannot exist independently of Instagram.
- Recommendation: Start with 1-2 Threads API tokens. The low volume of Danish content means throughput is unlikely to be a bottleneck.

---

## 7. Rate Limits and Multi-Account Notes

### Free Tier (Threads API)

| Metric | Value | Notes |
|--------|-------|-------|
| Per-user rate limit | 250 calls / hour | Per authenticated user token |
| Per-app rate limit | Varies | Scales with active user count |
| Search results per page | Configurable | Use `limit` parameter |
| Token validity | 60 days (long-lived) | Must refresh before expiry |

**250 calls/hour is sufficient for Danish collection**: With low Danish content volume and targeted search queries, 250 API calls per hour per token provides ample capacity. At ~50 results per page, a single token can retrieve ~12,500 posts per hour.

### Medium Tier (MCL)

Same rate limits as Facebook/Instagram MCL: 500,000 results/week shared across Facebook, Instagram, and Threads.

**RateLimiter configuration**:
- Free tier: Sliding window of 250 requests per 3,600 seconds per token
- MCL tier: Track weekly retrieval count (shared with Facebook/Instagram MCL usage)

---

## 8. Search Capabilities

### collect_by_terms() -- Free Tier

The Threads API search endpoint (`/{user_id}/threads_search`) has a critical limitation: it searches **within a specific user's threads**, not across all public Threads content. This means:

1. You cannot perform a global keyword search across all Threads posts
2. To search for a term, you must specify which user's posts to search
3. This makes term-based collection a two-step process:
   a. Maintain a list of known Danish Threads accounts
   b. Search each account's posts for matching terms

**Workaround**: Combine actor-based collection with client-side term filtering. Collect posts from known Danish accounts, then filter for matching terms locally.

**MCL (medium tier)**: Provides global keyword search across all public Threads content. This is the recommended approach for term-based collection.

### collect_by_actors() -- Free Tier

This is the more natural collection mode for the free tier:

1. Map actor platform presences to Threads usernames
2. Use `GET /{user_id}/threads` to retrieve each actor's posts
3. Paginate through results with cursor
4. Filter by date range client-side (no date filter parameter in the API)

**MCL (medium tier)**: Filter by creator ID to retrieve all public posts from specific actors.

---

## 9. Latency and Freshness

| Tier | Latency | Notes |
|------|---------|-------|
| Free (Threads API) | Seconds | Real-time API access to published posts |
| Free (Webhooks) | Near-real-time | Push notifications for new replies/mentions to the authenticated user |
| Medium (MCL) | Near-real-time | Posts available within minutes of publication |

**Polling interval recommendation**:
- Free tier: Poll every 30-60 minutes for actor-based collection (low volume)
- MCL: Poll every 30-60 minutes (shared with Facebook/Instagram polling)
- Webhooks: Configure for real-time mention/reply monitoring if tracking specific topics through a project Threads account

---

## 10. Known Limitations

1. **No engagement metrics for other users' posts (free tier)**: This is the most significant limitation. The Threads API only provides engagement data (likes, replies, reposts, views) for the authenticated user's own posts. For research requiring engagement analysis, MCL is necessary.

2. **No global keyword search (free tier)**: The search endpoint is user-scoped, not global. You cannot search across all public Threads for a keyword. This makes term-based discovery impractical without MCL.

3. **No language filter**: Neither the Threads API nor MCL provides a native language filter for Threads content. Danish content must be identified through keyword targeting, known Danish accounts, or client-side language detection.

4. **MCL CSV export not available for Threads**: Unlike Facebook and Instagram MCL data, Threads data cannot be exported as CSV. Analysis must occur within the cleanroom environment. This complicates cross-platform analysis in the Issue Observatory's local database.

5. **Instagram dependency**: Threads accounts are linked to Instagram accounts. If an Instagram account is deleted or suspended, the Threads account is also affected. Actor tracking must account for this linkage.

6. **Small Danish content volume**: Threads' Danish user base is small and growing. The platform may not provide enough content for statistically meaningful discourse analysis on its own. It is most valuable as a complementary source alongside Bluesky, X/Twitter, and Facebook.

7. **Fediverse integration (beta)**: Threads' ActivityPub integration is in beta. When fully operational, Threads posts may be accessible via the Fediverse (Mastodon-compatible APIs). This could provide an alternative free access path in the future. Monitor developments.

8. **Content moderation labels**: Posts may have a `hide_status` field indicating content moderation actions. Preserve this in `raw_metadata` but be aware that hidden posts may still be accessible via the API.

9. **Repost handling**: Reposts (`is_repost = true`) contain a reference to the original post (`reposted_post`). The normalizer should store the original post's text and flag the record as a repost in `raw_metadata`.

10. **Token expiry**: Long-lived tokens expire after 60 days. If token refresh is not automated, collection will silently fail after expiry. Implement proactive token refresh monitoring.

---

## 11. Legal Considerations

**Threads API (free tier)**:
- Official API with Meta-sanctioned terms of service
- Data collection for research is permitted within the API's terms
- Standard API usage -- no scraping or Terms of Service concerns
- GDPR applies to all personal data collected (post text, usernames)

**Meta Content Library (medium tier)**:
- Same legal framework as Facebook/Instagram MCL (see `/docs/arenas/facebook_instagram.md` section 11)
- Fully compliant research access path
- Cleanroom environment enforces data handling restrictions
- Research must focus on systemic risk or public interest topics

**DSA Article 40**:
- Instagram (and by extension Threads, as part of Meta's platform family) is designated as a VLOP
- DSA Art. 40(12) grants researchers the right to access publicly accessible data
- If MCL access is not approved, DSA Art. 40 provides an independent legal basis to request access to Threads data
- Meta received preliminary breach findings in October 2025 for inadequate researcher access

**GDPR specifics**:
- Legal basis: Art. 6(1)(e) + Art. 89 for university research
- Threads usernames are linked to Instagram identities -- pseudonymization is especially important given the cross-platform identity linkage
- Pseudonymize: `SHA-256("threads" + user_id + project_salt)`
- Include Threads collection in the project DPIA
- Note the Instagram-Threads identity linkage in the DPIA as a data minimization consideration

---

## 12. Recommended Implementation Approach

### Architecture

- **Dual-tier collector**: `ThreadsCollector` implementing ArenaCollector, supporting free (Threads API) and medium (MCL) tiers.
- **Shared MCL client**: If MCL access is approved, reuse the MCL API client built for Facebook/Instagram (see `/docs/arenas/facebook_instagram.md` section 12). The MCL client should be a shared component across all Meta platform collectors.
- **Actor-first strategy**: Given the free tier's lack of global search, the primary collection strategy at the free tier is actor-based: maintain a list of known Danish Threads accounts and poll their posts periodically.

### Key Implementation Guidance

1. **Free tier `collect_by_actors()`**:
   - Map actor platform presences to Threads usernames
   - For each actor, call `GET /{user_id}/threads` with fields parameter requesting all available fields
   - Paginate with cursor until all posts retrieved or `max_results` reached
   - Filter by date range client-side (compare `timestamp` to `date_from`/`date_to`)
   - No engagement metrics available -- `views_count`, `likes_count`, `shares_count`, `comments_count` will all be NULL

2. **Free tier `collect_by_terms()`**:
   - This is a two-step process at the free tier:
     a. Maintain a curated list of Danish Threads accounts (in `danish_defaults.py` or actor lists)
     b. For each account, call `GET /{user_id}/threads_search?q={term}`
     c. Aggregate results across all accounts
   - This is less efficient than global search but is the only option at the free tier
   - For efficiency, combine with `collect_by_actors()`: collect all posts from Danish accounts, then filter for matching terms locally

3. **MCL tier** (`collect_by_terms()` and `collect_by_actors()`):
   - Use the shared MCL API client
   - Search by keyword with Threads content type filter
   - Filter by date range and creator ID as needed
   - Full engagement metrics available

4. **Token management**:
   - Store long-lived token in CredentialPool with `quota_reset_at` set to token expiry date
   - Implement a Celery Beat task to refresh tokens at least 7 days before expiry
   - On token expiry, mark credential as inactive in CredentialPool and log a warning

5. **Normalizer**: Implement two parsing paths:
   - `_parse_threads_api(raw)` for free tier API responses
   - `_parse_mcl_threads(raw)` for MCL responses
   - Both converge to the same UCR dict output
   - Handle the engagement metrics gap: free tier records will have NULL engagement fields

6. **Health check**:
   - Free tier: `GET /me?fields=id,username` with a valid token -- verify 200 response
   - MCL tier: Same as Facebook/Instagram MCL health check

7. **Credit cost mapping**:
   - Free tier: 0 credits (no API cost)
   - MCL tier: Shared with Facebook/Instagram MCL credit budget (weekly 500,000 results cap)

8. **Danish account discovery**:
   - Cross-reference known Danish Instagram accounts (from Instagram actor lists) to find corresponding Threads accounts
   - Search for Danish hashtags on Threads to discover new Danish accounts
   - Maintain a growing list of Danish Threads accounts in the actor management system
