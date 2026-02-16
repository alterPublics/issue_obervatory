# Arena Research Brief: Gab

**Created**: 2026-02-16
**Last updated**: 2026-02-16
**Status**: Ready for implementation
**Phase**: 1 (Task 1.13, Medium priority)
**Arena path**: `src/issue_observatory/arenas/social_media/gab/`

---

## 1. Platform Overview

Gab is a social media platform that positions itself as a "free speech" alternative to mainstream platforms. Since July 2019, Gab has operated on a fork of the Mastodon open-source social networking software, making its API compatible with the Mastodon API documented at docs.joinmastodon.org. Gab has approximately 4-5 million registered accounts, though active user counts are significantly lower and not publicly reported. The platform is primarily English-language and predominantly used by right-wing, far-right, and conspiracy-oriented communities, particularly in the United States.

**Role in Danish discourse**: Gab's relevance to Danish discourse research is limited but specific. The platform is not among the commonly used social media platforms in Denmark (Danish social media penetration statistics do not typically include Gab). However, Gab is relevant for:
- Tracking Danish far-right actors who maintain presences on Gab alongside mainstream platforms
- Monitoring international far-right discourse about Denmark or Danish topics (e.g., immigration policy, free speech debates, "Muhammad cartoons" legacy)
- Identifying cross-platform propagation of narratives from fringe platforms into Danish mainstream discourse
- Studying the Danish corner of international conspiracy communities

Gab should be understood as a low-volume, niche monitoring target -- not a primary source of Danish discourse data.

**Access model**: Mastodon-compatible REST API with OAuth 2.0 authentication. Free tier only. Requires a Gab account for API access.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | Mastodon-compatible API at gab.com | $0 | OAuth 2.0 authentication. ~300 req/5 min (Mastodon default). |
| **Medium** | N/A | -- | No medium tier exists. |
| **Premium** | N/A | -- | No premium tier exists. |

Gab is a free-only arena. No paid API tiers exist.

---

## 3. API/Access Details

### Mastodon-Compatible REST API

**Base URL**: `https://gab.com/api/`

Since Gab runs a Mastodon fork, the API follows the Mastodon API specification (docs.joinmastodon.org) with possible Gab-specific modifications. The documentation below is based on the Mastodon API specification. Gab-specific deviations are noted where known.

**Authentication**: OAuth 2.0
1. Register an application: `POST /api/v1/apps` with `client_name`, `redirect_uris`, `scopes`
2. Obtain `client_id` and `client_secret` from the response
3. Authorize the user: direct to `https://gab.com/oauth/authorize?client_id=...&redirect_uri=...&response_type=code&scope=read`
4. Exchange authorization code for access token: `POST /oauth/token` with `grant_type=authorization_code`, `code`, `client_id`, `client_secret`, `redirect_uri`
5. Use access token in `Authorization: Bearer <token>` header

**Key Endpoints**:

| Endpoint | Method | Description | Auth Required |
|----------|--------|-------------|---------------|
| `GET /api/v1/search` | GET | Search content, accounts, hashtags | Yes |
| `GET /api/v2/search` | GET | Extended search with type parameter | Yes |
| `GET /api/v1/accounts/{id}/statuses` | GET | Get posts by a specific account | Yes |
| `GET /api/v1/accounts/lookup` | GET | Look up account by username | Yes |
| `GET /api/v1/statuses/{id}` | GET | Get a specific post | Yes |
| `GET /api/v1/statuses/{id}/context` | GET | Get parent and child posts (thread) | Yes |
| `GET /api/v1/timelines/tag/{hashtag}` | GET | Get posts with a specific hashtag | Yes |
| `GET /api/v1/timelines/public` | GET | Public timeline | Yes |
| `GET /api/v1/streaming` | WebSocket | Real-time streaming (public, hashtag, user) | Yes |

**Search endpoint details** (`GET /api/v2/search`):

| Parameter | Type | Description |
|-----------|------|-------------|
| `q` | string | Search query |
| `type` | string | Filter results: `accounts`, `hashtags`, `statuses` |
| `resolve` | boolean | Attempt WebFinger lookup for remote accounts |
| `limit` | integer | Results per page (default 20, max 40) |
| `offset` | integer | Pagination offset |
| `min_id` | string | Return results newer than this ID |
| `max_id` | string | Return results older than this ID |

**Account statuses endpoint** (`GET /api/v1/accounts/{id}/statuses`):

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | integer | Results per page (default 20, max 40) |
| `max_id` | string | Return statuses older than this ID |
| `since_id` | string | Return statuses newer than this ID |
| `min_id` | string | Return statuses immediately newer than this ID |
| `only_media` | boolean | Only return statuses with media |
| `exclude_replies` | boolean | Exclude reply statuses |
| `exclude_reblogs` | boolean | Exclude reblogs/reposts |
| `pinned` | boolean | Only return pinned statuses |

**Rate limits**: Mastodon default rate limits are approximately 300 requests per 5 minutes. Gab may apply different limits. Rate limit headers follow the standard pattern: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.

**Streaming API**: WebSocket at `wss://gab.com/api/v1/streaming` supports streams:
- `public` -- all public posts
- `public:local` -- local-only posts
- `hashtag` -- posts with a specific hashtag
- `user` -- authenticated user's home timeline

---

## 4. Danish Context

- **No language filter**: The Mastodon API does not provide a native language filter parameter on search or timeline endpoints. Individual statuses include a `language` field set by the author's client, but this cannot be used as a server-side filter.
- **Danish content is rare**: Gab is predominantly English-language. Danish-language content on Gab is extremely sparse. The primary collection strategy is:
  1. **Actor-based**: Identify known Danish far-right, conspiracy, or fringe actors who have Gab accounts and collect their posts regardless of language
  2. **Keyword-based**: Search for Danish keywords (`Danmark`, `dansk`, `dkpol`) and Denmark-related English keywords (`Denmark`, `Danish`, `Copenhagen`)
  3. **Hashtag-based**: Monitor hashtags related to Danish topics
- **Cross-platform tracking**: The primary research value is tracking actors who are also active on mainstream Danish platforms (X/Twitter, Facebook, Telegram) to study cross-platform narrative propagation between fringe and mainstream spaces.
- **Expected volume**: Very low. Likely single-digit to low double-digit posts per day matching Danish queries. This arena will produce far less data than any other Phase 1 arena.

---

## 5. Data Fields

Mapping to the Universal Content Record schema:

| UCR Field | Gab/Mastodon Source | Notes |
|-----------|---------------------|-------|
| `platform` | `"gab"` | Constant |
| `arena` | `"social_media"` | Constant |
| `platform_id` | `status.id` | String ID, unique within Gab |
| `content_type` | `"post"` | Posts, replies, reblogs all map to `"post"` |
| `text_content` | `status.content` (HTML stripped to plain text) | Mastodon returns HTML; strip tags |
| `title` | `NULL` | Gab posts have no title field (unless using Gab's long-form feature, stored in `raw_metadata`) |
| `url` | `status.url` or `status.uri` | Canonical URL on gab.com |
| `language` | `status.language` | ISO 639-1 code set by client; may be null or inaccurate |
| `published_at` | `status.created_at` | ISO 8601 timestamp |
| `collected_at` | Now | Standard |
| `author_platform_id` | `status.account.id` | Gab account ID |
| `author_display_name` | `status.account.display_name` | Display name |
| `views_count` | `NULL` | Mastodon API does not provide view counts |
| `likes_count` | `status.favourites_count` | Favourites/likes |
| `shares_count` | `status.reblogs_count` | Reblogs (reposts) |
| `comments_count` | `status.replies_count` | Reply count |
| `engagement_score` | Compute from favourites + reblogs + replies | Normalized |
| `raw_metadata` | Full status object | See below |
| `media_urls` | `status.media_attachments[].url` | Image, video, audio URLs |
| `content_hash` | SHA-256 of normalized plain text | For deduplication |

**`raw_metadata` should include**:
- `account`: full account object (id, username, display_name, note, avatar, header, followers_count, following_count, statuses_count, created_at)
- `in_reply_to_id`: parent status ID if this is a reply
- `in_reply_to_account_id`: parent author ID if this is a reply
- `reblog`: full reblogged status object if this is a repost
- `media_attachments`: array of media objects (type, url, preview_url, description)
- `mentions`: array of mentioned accounts
- `tags`: array of hashtags used
- `emojis`: custom emojis used
- `card`: link preview card (url, title, description, image)
- `poll`: poll data if present
- `sensitive`: content warning flag
- `spoiler_text`: content warning text
- `visibility`: `public`, `unlisted`, `private`, `direct`
- `application`: client application name

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Free | `{"client_id": "...", "client_secret": "...", "access_token": "..."}` | `"gab"` |

**Notes**:
- A Gab account is required to register an OAuth application and obtain API access
- The OAuth flow requires user authorization; the access token should be obtained interactively once and then stored in the CredentialPool
- `client_id` and `client_secret` are obtained from `POST /api/v1/apps`
- `access_token` is obtained through the OAuth 2.0 authorization code flow
- Request `read` scope for collection purposes
- Creating a Gab account requires email verification; no phone verification
- **Research ethics note**: Creating an account on Gab to monitor content raises ethical considerations that should be documented in the research ethics self-assessment (Pre-Phase task E.3). The account should be clearly identified as a research account in its profile.

---

## 7. Rate Limits and Multi-Account Notes

| Metric | Value | Notes |
|--------|-------|-------|
| Requests per 5 minutes | ~300 | Mastodon default; Gab may differ |
| Results per search request | 40 max | Per Mastodon API spec |
| Results per statuses request | 40 max | Per Mastodon API spec |
| Streaming | Continuous | WebSocket-based |

**Multi-account considerations**:
- Given the expected low volume of Danish-relevant content, a single account is sufficient
- Gab may be more aggressive than standard Mastodon instances about blocking automated access or research accounts
- If the account is suspended, create a replacement; no complex multi-account strategy is needed
- Rate limits are generous relative to the expected query volume

**RateLimiter configuration**: Use the `X-RateLimit-Remaining` and `X-RateLimit-Reset` response headers for adaptive rate limiting. Set a conservative baseline of 200 requests per 5 minutes (below the Mastodon default of 300) to provide headroom.

---

## 8. Known Limitations

1. **Gab-specific API deviations**: Gab's Mastodon fork may have modified, removed, or added API endpoints compared to the standard Mastodon API. The documentation at docs.joinmastodon.org is the best available reference, but Gab-specific behavior must be verified through testing. Flag any deviations discovered during implementation.

2. **Low Danish content volume**: Danish-language content on Gab is extremely sparse. The arena will produce far less data than any other Phase 1 arena. This is expected and acceptable -- the value is in cross-platform actor tracking, not volume.

3. **No view counts**: Like standard Mastodon, Gab does not expose view/impression counts via the API. Engagement analysis is limited to favourites, reblogs, and replies.

4. **Search limitations**: Mastodon's search functionality is intentionally limited (by design, to discourage harassment). Full-text search may be restricted to the user's own posts, mentions, and favourited posts. Gab may have relaxed this restriction, but verification is needed. Hashtag search and account lookup should work reliably.

5. **IP and geographic blocking**: Gab has historically blocked access from certain IP ranges and countries (e.g., Israeli IPs, some UK restrictions). Verify that API access works from the deployment infrastructure. If blocked, a proxy may be needed.

6. **Platform instability**: Gab has experienced periods of downtime, infrastructure changes, and feature modifications. API availability is less reliable than major platforms. The health check should be run frequently.

7. **Content moderation concerns and research ethics**:
   - Gab hosts content that would be removed on mainstream platforms, including hate speech, extremist content, and disinformation
   - Researchers collecting from Gab should be aware of the potential for exposure to harmful content
   - The DPIA should explicitly address collection from Gab and the nature of content expected
   - Data collected from Gab should be handled with care regarding dissemination -- direct quotes or attribution could amplify harmful content
   - The research ethics self-assessment (Pre-Phase task E.3) should document the justification for monitoring Gab, the expected content types, and researcher well-being considerations
   - Danish data protection law (Databeskyttelsesloven 10) requirements apply to any special category data (political opinions, religious beliefs) that may be prevalent on Gab

8. **Historical data gap**: Historical Gab datasets exist from the pre-Mastodon era (Pushshift Gab archive, August 2016 - December 2018; Fair & Wesslen ICWSM 2019 dataset with 37M posts and 24.5M comments), but these cover a different platform version. Post-2019 data requires live API collection only.

9. **Federation status**: Gab's Mastodon instance is defederated from nearly all other Mastodon/ActivityPub instances. This means Gab content does not appear on the broader Fediverse, and federation-based discovery tools will not find Gab content. All collection must go directly to `gab.com`.

10. **Legal considerations**:
    - Gab's Terms of Service do not explicitly prohibit research use of the API, but they are less research-friendly than platforms like Bluesky
    - GDPR applies to all personal data (usernames, display names, post content, profile information)
    - Standard pseudonymization via `pseudonymized_author_id` is required
    - Gab is not designated as a VLOP under the EU Digital Services Act (too few EU users), so DSA Article 40 researcher access provisions do not apply
    - The legal basis for processing is Art. 6(1)(e) public task + Art. 89 research exemption, same as other arenas
    - Content on Gab may include material that is illegal under Danish law (e.g., hate speech under Straffelovens 266b). The research exemption covers collection for analysis but not redistribution. Consult with legal advisors if specific content raises concerns.

---

## 9. Collector Implementation Notes

### Architecture

- **Dual collection mode**: Implement both `collect_by_terms` (search + hashtag timeline) and `collect_by_actors` (account statuses).
- **Optional streaming**: Implement WebSocket streaming for real-time monitoring of public timeline or specific hashtags. Given the low expected volume, polling may be sufficient.
- **HTML normalization**: Mastodon API returns status content as HTML. The normalizer must strip HTML tags for plain text storage.

### Key Implementation Guidance

1. **Search-based collection** (`collect_by_terms`):
   - Use `GET /api/v2/search?q={term}&type=statuses` for keyword search
   - Supplement with `GET /api/v1/timelines/tag/{hashtag}` for hashtag-based collection
   - Paginate using `max_id` parameter (ID-based pagination, not offset)
   - Test full-text search capability on Gab specifically -- if restricted, fall back to hashtag and account-based collection
   - Apply client-side language detection for Danish content filtering

2. **Actor-based collection** (`collect_by_actors`):
   - Map actor platform presences to Gab account IDs
   - Look up accounts by username: `GET /api/v1/accounts/lookup?acct={username}`
   - Fetch statuses: `GET /api/v1/accounts/{id}/statuses?limit=40`
   - Paginate using `max_id` for historical collection
   - Use `since_id` for incremental collection (only new posts since last check)

3. **HTML-to-text conversion**:
   - Mastodon returns status `content` as HTML (paragraphs, links, mentions as anchor tags)
   - Use `beautifulsoup4` or similar to extract plain text
   - Preserve mention usernames and hashtag text
   - Store original HTML in `raw_metadata.content_html`

4. **Reblog handling**:
   - When a status is a reblog (repost), the `reblog` field contains the original status
   - Store the reblog as a separate record with the original author and content
   - Note the reblogging user and context in `raw_metadata`

5. **Thread retrieval**:
   - Use `GET /api/v1/statuses/{id}/context` to retrieve the full thread (ancestors and descendants)
   - Useful for collecting complete discussions around matched posts

6. **Streaming implementation** (optional):
   - Connect to `wss://gab.com/api/v1/streaming?stream=public` for the full public timeline
   - Or `?stream=hashtag&tag={tag}` for hashtag-specific streams
   - Filter incoming statuses by keywords and language client-side
   - Handle WebSocket disconnections with exponential backoff reconnect

7. **Health check**: `GET https://gab.com/api/v1/timelines/public?limit=1` with valid Bearer token -- verify 200 response and valid JSON. If this fails, also check `GET https://gab.com/api/v1/instance` for server status information.

8. **Credit cost**: 0 credits (free tier only).

9. **Mastodon.py library**: Consider using the `Mastodon.py` Python library (`pip install Mastodon.py`) which provides a typed client for the Mastodon API. Initialize with `Mastodon(api_base_url='https://gab.com', access_token=token)`. Test compatibility with Gab's fork -- some methods may not work if Gab has modified the underlying API.

10. **Account registration for OAuth**: The OAuth flow requires registering an app and authorizing a user. This is an interactive one-time setup:
    ```
    POST /api/v1/apps
    {
      "client_name": "IssueObservatory",
      "redirect_uris": "urn:ietf:wg:oauth:2.0:oob",
      "scopes": "read"
    }
    ```
    Then direct user to authorization URL, obtain code, exchange for token. Store the resulting access token in the CredentialPool.
