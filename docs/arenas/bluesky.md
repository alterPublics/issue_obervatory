# Arena Research Brief: Bluesky

**Created**: 2026-02-16
**Last updated**: 2026-02-16
**Status**: Ready for implementation
**Phase**: 1 (Task 1.5, Critical priority)
**Arena path**: `src/issue_observatory/arenas/social_media/bluesky/`

---

## 1. Platform Overview

Bluesky is a decentralized social network built on the AT Protocol. As of early 2026, it has approximately 28 million monthly active users. Bluesky is the most research-friendly major social media platform -- all public data is freely accessible through the AT Protocol with no API keys required for read-only access. The platform explicitly invites research use.

**Role in Danish discourse**: Bluesky's Danish user base is small but growing, particularly among journalists, researchers, and tech-oriented users who migrated from X/Twitter. With X/Twitter at only 13% penetration in Denmark, Bluesky captures part of the public debate community that has left X. The `lang:da` filter enables targeted collection of Danish-language content. While the total volume of Danish content is much lower than on Facebook or X/Twitter, Bluesky disproportionately captures media professionals and opinion leaders.

**Access model**: Fully open. All public data available for free. As of early 2026, authentication is required for read access via the public API endpoint (`public.api.bsky.app`). Use handle + app password to obtain a session token.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | AT Protocol public API + Jetstream firehose | $0 | 3,000 req/5 min (public API). Jetstream: unlimited, no auth. |
| **Medium** | N/A | -- | No medium tier exists. Free tier is sufficient. |
| **Premium** | N/A | -- | No premium tier exists. Free tier is sufficient. |

Bluesky is a free-only arena. The AT Protocol's openness means there is no need for paid tiers.

---

## 3. API/Access Details

### Public API (Search and Lookup)

**Base URL**: `https://public.api.bsky.app`

**Key Endpoints**:

| Endpoint | Method | Description | Auth Required |
|----------|--------|-------------|---------------|
| `app.bsky.feed.searchPosts` | GET | Full-text post search with filters | Yes (as of 2026) |
| `app.bsky.actor.searchActors` | GET | Search for users by name/handle | Yes (as of 2026) |
| `app.bsky.feed.getAuthorFeed` | GET | Get posts by a specific user | Yes (as of 2026) |
| `app.bsky.feed.getPostThread` | GET | Get a post and its reply thread | Yes (as of 2026) |
| `app.bsky.actor.getProfile` | GET | Get user profile details | Yes (as of 2026) |
| `app.bsky.feed.getTimeline` | GET | Authenticated user's timeline | Yes |

**Search endpoint details** (`app.bsky.feed.searchPosts`):

| Parameter | Type | Description |
|-----------|------|-------------|
| `q` | string | Search query (Lucene syntax supported) |
| `lang` | string | Language filter (e.g., `da` for Danish) |
| `author` | string | Filter by author DID or handle |
| `since` | string | Start date (ISO 8601, e.g., `2026-01-01T00:00:00Z`) |
| `until` | string | End date (ISO 8601) |
| `tag` | string | Hashtag filter (without #) |
| `limit` | integer | Results per page (max 100) |
| `cursor` | string | Pagination cursor |

**Search query syntax**: Supports Lucene operators including `AND`, `OR`, `NOT`, quoted phrases, and parentheses for grouping.

**Authentication** (required as of early 2026):
- Create an app password at bsky.app settings (Settings > App Passwords)
- Use `com.atproto.server.createSession` to obtain an access token (JWT)
- Pass token in `Authorization: Bearer <token>` header on all subsequent requests
- Session tokens are valid for a limited time; refresh as needed

**Rate limits**:
- Authenticated: 3,000 requests per 5 minutes (per account)
- Rate limit headers returned: `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`

### Jetstream Firehose (Real-Time)

**Protocol**: WebSocket

**Endpoints** (multiple regions available):
- `wss://jetstream1.us-east.bsky.network/subscribe`
- `wss://jetstream2.us-east.bsky.network/subscribe`
- `wss://jetstream1.us-west.bsky.network/subscribe`
- `wss://jetstream2.us-west.bsky.network/subscribe`

**Parameters**:
| Parameter | Description |
|-----------|-------------|
| `wantedCollections` | Filter by collection type: `app.bsky.feed.post`, `app.bsky.feed.like`, `app.bsky.feed.repost`, `app.bsky.graph.follow`, etc. |
| `wantedDids` | Filter by specific user DIDs (up to 10,000) |
| `cursor` | Unix microsecond timestamp for replay from a specific point |
| `compress` | Enable zstd compression (~56% bandwidth reduction) |

**Authentication**: None required.

**Bandwidth**: 4-8 GB/hour unfiltered. With `wantedCollections=app.bsky.feed.post` and zstd compression, substantially less.

**Latency**: Sub-second from post creation to delivery.

**No language filter on firehose**: Jetstream does not support server-side language filtering. Danish posts must be filtered client-side after receiving the full stream (or filtering by known Danish user DIDs).

### atproto Python SDK

**Package**: `atproto` (PyPI)
**Installation**: `pip install atproto`

Provides a full-featured client with typed methods for all XRPC endpoints, including firehose subscription support.

---

## 4. Danish Context

- **`lang:da`** filter on `searchPosts` returns posts where the author set their post language to Danish or where the platform detected Danish. This is the primary mechanism for collecting Danish content via search.
- **Firehose limitation**: No server-side language filter. Two strategies for Danish collection via Jetstream:
  1. Maintain a list of known Danish user DIDs and filter with `wantedDids` (up to 10,000 DIDs)
  2. Receive all posts and filter client-side by language detection (expensive in bandwidth)
- **Danish user discovery**: Search for posts with `lang:da` to discover Danish users, then track their DIDs for firehose filtering. Also search for Danish keywords, hashtags like `#dkpol`, `#dkmedier`, and known Danish handles.
- **Handle format**: Danish users often use `.bsky.social` handles or custom domain handles (e.g., `journalist.dr.dk`). Custom domain handles can help identify institutional accounts.
- **Content volume**: Danish Bluesky content is low-to-moderate volume. Search-based collection is likely sufficient without needing the firehose for most use cases. The firehose becomes valuable for real-time tracking of breaking events.

---

## 5. Data Fields

Mapping to the Universal Content Record schema:

| UCR Field | Bluesky Source | Notes |
|-----------|---------------|-------|
| `platform` | `"bluesky"` | Constant |
| `arena` | `"social_media"` | Constant |
| `platform_id` | `uri` (AT URI, e.g., `at://did:plc:.../app.bsky.feed.post/...`) | Globally unique |
| `content_type` | `"post"` | Posts, replies, quotes all map to `"post"` |
| `text_content` | `record.text` | Post text content |
| `title` | `NULL` | Bluesky posts have no title |
| `url` | Constructed: `https://bsky.app/profile/{handle}/post/{rkey}` | Derive from AT URI |
| `language` | `record.langs[0]` | Array of language codes; take first |
| `published_at` | `record.createdAt` | ISO 8601 timestamp |
| `collected_at` | Now | Standard |
| `author_platform_id` | `author.did` | Decentralized Identifier |
| `author_display_name` | `author.displayName` | Display name |
| `views_count` | `NULL` | Bluesky does not expose view counts |
| `likes_count` | `likeCount` | From post view |
| `shares_count` | `repostCount` | Reposts |
| `comments_count` | `replyCount` | Replies |
| `engagement_score` | Compute from likes + reposts + replies | Normalized |
| `raw_metadata` | Full post object | Store: `embed` (links, images, quoted posts), `facets` (mentions, links, hashtags), `labels`, `threadgate`, `reply` parent/root references |
| `media_urls` | Extract from `embed.images[].fullsize` | Image URLs |
| `content_hash` | SHA-256 of normalized `text_content` | For deduplication |

**Embedded content**: Posts can embed images (up to 4), external links (with preview card), quoted posts, and video. The `embed` object structure varies by type. The normalizer must handle all embed types.

**Facets**: The `facets` array contains rich text annotations -- mentions, links, and hashtags with byte-range positions. Parse these to extract structured metadata.

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Free | `{"handle": "handle.bsky.social", "app_password": "xxxx-xxxx-xxxx-xxxx"}` | `"bluesky"` |

**Recommendation**: Use app passwords (not main account passwords) for authentication. Create app passwords at bsky.app Settings > App Passwords. Store as `BLUESKY_HANDLE` and `BLUESKY_APP_PASSWORD` in the `.env` file or add via the admin credentials panel.

---

## 7. Rate Limits and Multi-Account Notes

| Access Type | Rate Limit | Reset Window | Notes |
|-------------|-----------|--------------|-------|
| Authenticated | 3,000 req / 5 min | Rolling 5-minute window | Per account (required as of 2026) |
| Jetstream | No rate limit | N/A | Bandwidth-limited only |

**Multi-account considerations**:
- Authenticated access at 3,000 req/5 min is generous enough for most Danish collection needs. With 100 results per search request, a single account can retrieve 300,000 posts per 5-minute window.
- Multiple accounts are unnecessary unless the project scales to very high-volume collection across many query designs simultaneously.
- If multi-account is needed: create separate Bluesky accounts with app passwords. No phone verification required. No known ban risk for read-only API access.

**RateLimiter configuration**: Use the `RateLimit-Remaining` and `RateLimit-Reset` response headers for adaptive rate limiting rather than hardcoded delays.

---

## 8. Known Limitations

1. **Small Danish user base**: Bluesky's Danish community is growing but small. Total Danish-language post volume is orders of magnitude lower than Facebook or even X/Twitter. Coverage is biased toward journalists, tech workers, and academics.

2. **No view counts**: Unlike most platforms, Bluesky does not expose view/impression counts. Engagement analysis is limited to likes, reposts, and replies.

3. **Language detection imperfect**: The `lang` field is set by the posting client, not verified by the platform. Some Danish posts may be tagged with incorrect language codes, and vice versa.

4. **Firehose bandwidth**: The unfiltered Jetstream is 4-8 GB/hour. For a project focused on Danish content, this is excessive. Prefer search-based collection or DID-filtered firehose.

5. **No full-archive search guarantee**: The `searchPosts` endpoint searches an index that may not include all historical posts. Very old posts may not be discoverable via search. For complete coverage of specific accounts, use `getAuthorFeed` pagination.

6. **Decentralized identity**: Users can migrate their DID between servers (PDS instances). The DID remains stable, but the handle (e.g., `user.bsky.social`) can change. Always use DID as the primary identifier, not the handle.

7. **Legal considerations**: Bluesky's terms are highly permissive for research. The AT Protocol is designed for open access. GDPR applies to personal data in posts (author names, profile info). Standard pseudonymization via `pseudonymized_author_id` is sufficient. No special legal risks.

8. **Content moderation labels**: Posts may carry moderation labels (e.g., `nsfw`, `spam`). These should be preserved in `raw_metadata` but do not affect collection.

---

## 9. Collector Implementation Notes

### Architecture

- **Dual collection mode**: Implement both search-based collection (`collect_by_terms`) and author-feed collection (`collect_by_actors`).
- **Optional firehose**: Implement Jetstream subscription as an additional real-time mode for live tracking. This is a WebSocket connection, distinct from the REST API polling pattern used by other arenas. Consider implementing this as a separate Celery worker.

### Key Implementation Guidance

1. **Search-based collection** (`collect_by_terms`):
   - Use `app.bsky.feed.searchPosts` with `lang:da` filter
   - Support Lucene query syntax: pass query design terms directly
   - Paginate with cursor until all results retrieved or `max_results` reached
   - Set `since`/`until` parameters for date-bounded batch collection

2. **Actor-based collection** (`collect_by_actors`):
   - Map actor platform presences to Bluesky DIDs
   - Use `app.bsky.feed.getAuthorFeed` for each actor
   - Paginate with cursor; filter by date range client-side
   - More reliable than search for complete account coverage

3. **Firehose collection** (optional, for live tracking):
   - Connect to Jetstream WebSocket endpoint
   - Filter by `wantedCollections=app.bsky.feed.post`
   - If Danish DID list available, use `wantedDids` parameter
   - Otherwise, filter client-side by language detection on received posts
   - Store cursor (Unix microsecond timestamp) for reconnection at the last processed event
   - Handle disconnections with exponential backoff reconnect

4. **AT URI parsing**: Extract `did` and `rkey` from the AT URI format `at://did:plc:xxxx/app.bsky.feed.post/yyyy` to construct web URLs and for deduplication.

5. **Embed handling**: The normalizer must handle multiple embed types:
   - `app.bsky.embed.images` -- extract image URLs to `media_urls`
   - `app.bsky.embed.external` -- extract linked URL to `raw_metadata`
   - `app.bsky.embed.record` -- quoted post reference
   - `app.bsky.embed.recordWithMedia` -- quoted post with images

6. **Authentication flow**: On first API request, call `com.atproto.server.createSession` with `identifier` (handle) and `password` (app password) to obtain `accessJwt`. Cache this token for subsequent requests. Include it in all API calls via `Authorization: Bearer {accessJwt}` header.

7. **Health check**: Authenticate, then `GET https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=test&limit=1` -- verify 200 response and valid JSON.

8. **Credit cost**: 0 credits for all operations (free tier only). No credit deduction needed.

9. **Python SDK**: The collector uses `httpx.AsyncClient` for direct API calls rather than the `atproto` package, to maintain consistency with other arena collectors. Session management is implemented manually via the `_authenticate()` method.
