# Network Expansion API Assessment: Graph-Based Snowball Sampling Capabilities

**Created**: 2026-02-20
**Author**: Research Strategist
**Status**: Complete
**Scope**: Evaluate follower/following graph traversal APIs across all implemented arenas

---

## Changelog

- 2026-02-20: Initial assessment covering 8 platforms

---

## 1. Context

The `NetworkExpander` class (`src/issue_observatory/sampling/network_expander.py`) currently supports 4 platform-specific expansion strategies:

| Platform | Strategy | Mechanism |
|----------|----------|-----------|
| Bluesky | `_expand_bluesky()` | `app.bsky.graph.getFollows` / `getFollowers` (AT Protocol public API) |
| Reddit | `_expand_reddit()` | `u/username` mention extraction from comment history |
| YouTube | `_expand_youtube()` | `featuredChannelsUrls` from `brandingSettings` |
| Telegram | `_expand_via_telegram_forwarding()` | Forwarding chain analysis in `content_records` JSONB |

All other platforms (TikTok, X/Twitter, Facebook, Instagram, Threads, Gab, Discord, Majestic) fall back to `_expand_via_comention()`, which mines `@username` patterns from stored `content_records.text_content`. Co-mention is a distinct analytical strategy (discursive association) compared to structural graph traversal (social network ties). See `/docs/research_reports/comention_snowball_recommendation.md` for the methodological distinction.

This assessment evaluates whether each platform's API, at the tier we currently use, supports follower/following or similar graph traversal that could replace or supplement co-mention detection.

---

## 2. Assessment Summary Table

| Platform | API Supports Graph? | Endpoint | Tier Required | Rate/Cost Impact | Daily Quota | Recommend Implementation? | Priority |
|----------|-------------------|----------|---------------|-----------------|-------------|--------------------------|----------|
| **TikTok** | **YES** | `POST /v2/research/user/followers/` and `/following/` | FREE (Research API) | Shares daily quota | 20,000 calls/day (separate from video query) | **YES -- HIGH** | 1 |
| **Gab** | **YES** | `GET /api/v1/accounts/{id}/followers` and `/following` | FREE (Mastodon API) | ~300 req/5 min | No separate cap | **YES -- HIGH** | 2 |
| **X/Twitter** | **YES** | `GET /twitter/user/followers` and `/followings` (TwitterAPI.io) | MEDIUM | $0.15/1K users returned | Billing-based | **YES -- MEDIUM** | 3 |
| **Discord** | **PARTIAL** | `GET /guilds/{id}/members` | FREE | Requires `GUILD_MEMBERS` privileged intent | 50 req/s global | **NO** (not graph traversal) | -- |
| **Instagram** | **YES (via Bright Data)** | Bright Data Instagram Followers Scraper | MEDIUM | ~$1.50/1K records | Billing-based | **CONDITIONAL** | 4 |
| **Facebook** | **NO** | No follower/following API via Bright Data or MCL | -- | -- | -- | **NO** | -- |
| **Threads** | **NO** | Free API has no follower list endpoints | -- | -- | -- | **NO** | -- |
| **Majestic** | **YES (structural)** | `GetRefDomains` / `GetBackLinkData` | PREMIUM | ~1K analysis units per call | 100M units/month | **Already implicit** (backlink = link graph) | -- |

---

## 3. Detailed Per-Platform Assessment

### 3.1. TikTok Research API -- RECOMMENDED (Priority 1)

**Verdict: Implement dedicated `_expand_tiktok()` strategy.**

The TikTok Research API provides explicit follower/following endpoints that are already documented in our arena brief (`/docs/arenas/tiktok.md`, section 3) but have not been leveraged by the `NetworkExpander`.

**Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /v2/research/user/followers/` | POST | Returns a paginated list of a user's followers |
| `POST /v2/research/user/following/` | POST | Returns a paginated list of accounts a user follows |

**Request parameters:**
- `username` (string): TikTok username to query
- `max_count` (integer): Results per page (max 100)
- `cursor` (integer): Pagination cursor

**Response fields per user:**
- `display_name`: User's display name
- `username`: TikTok username (the unique identifier)

**Rate limits (separate from video query quota):**
- 20,000 calls per day for follower/following endpoints
- 100 records per call
- Theoretical daily maximum: 2,000,000 follower/following records per day
- Resets at 12:00 AM UTC

**Cost:** $0 (included in Research API access, which is already confirmed for this project).

**Implementation notes:**
- The existing TikTok collector already handles OAuth token management (`_get_access_token()`) and rate limiting. The `NetworkExpander` can reuse the token acquisition logic or, following the existing pattern, make direct `httpx` calls to avoid circular imports.
- The follower/following quota (20,000 calls/day) is **separate** from the video query quota (1,000 calls/day). Using these endpoints does not reduce video collection capacity.
- The `TIKTOK_USER_INFO_URL` is already defined in `arenas/tiktok/config.py` but the follower/following URLs are not. Two new constants are needed:
  - `TIKTOK_USER_FOLLOWERS_URL = "https://open.tiktokapis.com/v2/research/user/followers/"`
  - `TIKTOK_USER_FOLLOWING_URL = "https://open.tiktokapis.com/v2/research/user/following/"`
- Discovery method label: `"tiktok_followers"` and `"tiktok_following"`.
- Cap pagination at 500 per direction (matching the Bluesky pattern) to avoid exhausting quota on accounts with millions of followers.

**Why this is high priority:** TikTok is the only currently-implemented platform where we have confirmed API access to follower/following data at zero cost, with a generous dedicated quota, and where the API is already fully integrated into the collector. The implementation effort is low (follows the exact same pattern as `_expand_bluesky()`), and TikTok's algorithmic nature means follower graphs are especially valuable -- you cannot infer network structure from co-mentions on a platform where content surfacing is algorithm-driven rather than follow-driven.

---

### 3.2. Gab (Mastodon-Compatible API) -- RECOMMENDED (Priority 2)

**Verdict: Implement dedicated `_expand_gab()` strategy.**

The Mastodon API specification, which Gab follows as a fork, includes explicit follower and following list endpoints. These are standard Mastodon endpoints documented at `docs.joinmastodon.org`.

**Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/v1/accounts/{id}/followers` | GET | Paginated list of accounts following the target |
| `GET /api/v1/accounts/{id}/following` | GET | Paginated list of accounts the target follows |

**Response:** Array of Mastodon `Account` objects, each containing:
- `id`: Account ID
- `username`: Username (without domain)
- `display_name`: Display name
- `url`: Profile URL
- `followers_count`, `following_count`, `statuses_count`

**Pagination:** Link header-based (`max_id`, `since_id`). No offset pagination.

**Rate limits:** ~300 requests per 5 minutes (Mastodon default; Gab may differ). Adaptive rate limiting via `X-RateLimit-Remaining` headers.

**Cost:** $0 (free tier only).

**Implementation notes:**
- The Gab collector already handles account ID resolution (`_resolve_account_id()`) and authenticated GET requests (`_make_get_request()`). The `NetworkExpander` can follow the same direct-HTTP pattern.
- Base URL: `https://gab.com/api/v1/accounts/{id}/followers` and `/following`.
- Account IDs are numeric strings on Gab (Mastodon-style).
- Discovery method label: `"gab_followers"` and `"gab_following"`.
- Cap at 500 per direction.
- IMPORTANT CAVEAT: Gab's Mastodon fork may have modified or restricted these endpoints. The Gab arena brief (`/docs/arenas/gab.md`, section 8, limitation 1) explicitly notes: "Gab's Mastodon fork may have modified, removed, or added API endpoints." These endpoints must be tested against the live Gab API before the `NetworkExpander` strategy is committed. Mark as UNVERIFIED until tested.

**Why this is high priority despite low Danish content:** The primary research value of Gab is cross-platform actor tracking (arena brief section 1). Follower/following graphs on Gab reveal the social network structure of far-right and fringe communities, which is precisely the kind of structural information that co-mention detection cannot provide. Danish actors on Gab are tracked to study cross-platform propagation, and knowing who they follow (and who follows them) on Gab is essential for understanding information flow pathways. The implementation effort is low.

---

### 3.3. X/Twitter (via TwitterAPI.io) -- RECOMMENDED (Priority 3)

**Verdict: Implement dedicated `_expand_x_twitter()` strategy.**

TwitterAPI.io, the medium-tier service we use for X/Twitter collection, provides follower and following list endpoints.

**Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /twitter/user/followers` | GET | Paginated list of a user's followers |
| `GET /twitter/user/followings` | GET | Paginated list of accounts a user follows |

**Request parameters:**
- `userName` (string, required): Twitter/X username
- `cursor` (string, optional): Pagination cursor from previous response

**Response:** JSON with `followers` (or `followings`) array, `has_next_page` boolean, and `next_cursor` string. Each user object includes: `name`, `userName`, `id`, `verified`, `followers_count`, `following_count`, `created_at`.

**Rate limits:** 1,000+ QPS (service-side). No published daily cap -- billing is per user record returned.

**Cost:** $0.15 per 1,000 user records returned (same pricing as tweets). Each page returns ~200 users.

**Cost estimate for snowball sampling:** Expanding a single actor's followers + following at 500 per direction = ~5 API pages = ~1,000 user records = $0.15. For 20 seed actors: ~$3.00.

**Implementation notes:**
- The X/Twitter collector currently uses `httpx` with `X-API-Key` header authentication. The `NetworkExpander` can follow the same direct-HTTP pattern.
- Base URL: `https://api.twitterapi.io/twitter/user/followers` and `/followings`.
- Requires credential pool access for `platform="twitterapi_io"`.
- Discovery method label: `"x_twitter_followers"` and `"x_twitter_following"`.
- Cap at 500 per direction to control costs.
- Credit cost: 1 credit per ~200 users returned (adjust credit mapping to reflect follower-list pricing).

**Why medium priority:** X/Twitter at 13% Danish penetration is disproportionately important for elite discourse, but the medium tier introduces a per-record cost that does not exist for TikTok or Gab. The cost is modest but nonzero. Additionally, X/Twitter's follower graphs for public figures (politicians, journalists) are large, which means pagination and cost management need careful implementation. Co-mention detection works reasonably well for X/Twitter because the platform's `@mention` convention is pervasive -- unlike TikTok where mentions are rare in video descriptions.

---

### 3.4. Discord -- NOT RECOMMENDED

**Verdict: Co-mention fallback is appropriate. Server member lists are not graph data.**

Discord's `GET /guilds/{id}/members` endpoint returns the list of all members in a server. This is not a follower/following graph -- Discord does not have follow relationships. Server membership is more analogous to "group membership" than "social ties."

**Why not implement:**
- Server member lists do not reveal directed social relationships. All members of a server are equally "connected" in a flat structure.
- The research bot must be a member of the server and have the `GUILD_MEMBERS` privileged intent enabled. The current arena brief notes this is available for bots in fewer than 100 servers.
- Member lists reveal who is in a server, but not who interacts with whom. Co-mention detection from collected messages is actually more informative for understanding discursive connections within a server.
- Listing all members of a server and treating them as "connected actors" would flood the snowball suggestions with irrelevant noise.

**Alternative already available:** The co-mention fallback extracts `@username` patterns from Discord messages, which reflects actual discursive interaction -- a much stronger signal than shared server membership.

---

### 3.5. Instagram (via Bright Data) -- CONDITIONAL

**Verdict: Technically feasible but conditional on cost-benefit for specific research needs.**

Bright Data offers an Instagram Followers Scraper that can retrieve follower lists for public profiles.

**Endpoint:** Bright Data Instagram Followers Scraper API.
**Response:** JSON/NDJSON/CSV with follower profile data (username, id, followers count, verified status, etc.).
**Cost:** ~$1.50 per 1,000 follower records.

**Why conditional, not recommended:**
1. **Cost is significant for large accounts.** A Danish politician with 50,000 Instagram followers would cost ~$75 to enumerate. For 20 seed actors: potentially $500-$1,500. This is an order of magnitude more expensive than X/Twitter via TwitterAPI.io.
2. **Instagram follower graphs are less informative for Danish discourse research.** Instagram's engagement model is visual (likes, comments on posts), not conversational (@mentions). Co-mention detection from caption text captures the discourse-relevant connections.
3. **MCL (premium tier) may provide better options.** If Meta Content Library access is approved, it may provide more structured relationship data within the cleanroom. Implementing a Bright Data follower scraper now would be superseded.
4. **Ethical consideration:** Mass follower list enumeration via scraping is more intrusive than other data collection methods. The DPIA should address this if implemented.

**Recommendation:** Defer unless a specific research question requires Instagram network topology. If needed, implement as a per-request feature (not default snowball expansion) with explicit cost warnings.

---

### 3.6. Facebook -- NOT FEASIBLE

**Verdict: No graph traversal available at any tier we use.**

Neither Bright Data (medium tier) nor the Meta Content Library (premium tier) provides access to Facebook friend lists, Page follower lists, or Group member lists in a form suitable for network expansion.

- **Bright Data Facebook Datasets:** Provide post data from public Pages and Groups. No follower/friend list endpoints.
- **Meta Content Library:** Provides content search and engagement metrics. Does not expose social graph data (who follows whom).
- **Facebook Graph API (direct):** The `/friends` and `/subscribers` edges have been heavily restricted since 2018 and are not available to research applications. Page follower lists are not exposed.

**Co-mention is the best available strategy** for Facebook. The platform's tagging and mention conventions in public posts provide reasonable co-occurrence signals.

---

### 3.7. Threads -- NOT FEASIBLE

**Verdict: No follower/following list endpoints in the Threads API.**

The Threads API (free tier) provides endpoints for retrieving a user's posts, replies, and conversation threads, but does **not** expose follower or following lists. The API was designed for app developers (publishing and managing content), not for research-scale data access.

The arena brief (`/docs/arenas/threads.md`, section 3) documents the available endpoints. None support graph traversal:
- `GET /{user_id}/threads` -- user's posts
- `GET /{thread_id}/replies` -- replies to a post
- `GET /{user_id}/threads_search` -- keyword search within a user's posts

**MCL (medium tier):** The Meta Content Library includes Threads data since February 2025 but, like the Facebook MCL, does not expose social graph relationships.

**Co-mention is the best available strategy** for Threads.

---

### 3.8. Majestic -- ALREADY IMPLICIT (Different Domain)

**Verdict: Backlink relationships are a form of network, but at the domain/URL level, not the actor level.**

Majestic's `GetRefDomains` and `GetBackLinkData` endpoints already provide a graph structure: "who links to whom" at the web domain level. This is conceptually equivalent to network expansion for web actors.

However, this operates at a fundamentally different level than the `NetworkExpander`:
- Majestic maps **domain-to-domain** or **URL-to-URL** relationships.
- The `NetworkExpander` maps **actor-to-actor** relationships.
- Majestic has no concept of user accounts or followers.

The Majestic arena is already designed as a "link graph" analyzer (arena brief section 1). Its integration with the `NetworkExpander` would require bridging from URLs to actors via `ActorPlatformPresence` records where `platform="web"`. This is architecturally feasible but would produce a qualitatively different kind of "expansion" (web graph neighbors rather than social graph neighbors).

**Recommendation:** Do not add Majestic to `NetworkExpander`. Instead, consider exposing Majestic's referring domain data as a separate "web graph expansion" feature in the discovered sources panel, which already exists (GR-22).

---

## 4. Implementation Priority Roadmap

### Phase 1: TikTok (HIGH, ~0.5-1 day engineering effort)

**Rationale:** Zero additional cost, generous dedicated quota (20K calls/day), confirmed API access, follows existing `_expand_bluesky()` pattern exactly.

**Implementation sketch:**
1. Add `TIKTOK_USER_FOLLOWERS_URL` and `TIKTOK_USER_FOLLOWING_URL` constants to `arenas/tiktok/config.py`.
2. Add `_expand_tiktok()` method to `NetworkExpander` in `sampling/network_expander.py`:
   - Acquire TikTok OAuth token via credential pool.
   - POST to followers endpoint with `{"username": "<username>", "max_count": 100}`.
   - Paginate with cursor until 500 results or no more pages.
   - Repeat for following endpoint.
   - Return `ActorDict` list with `discovery_method="tiktok_followers"` / `"tiktok_following"`.
3. Add `elif platform == "tiktok":` branch in `expand_from_actor()`.
4. Unit test with `respx` mock for the two endpoints.

### Phase 2: Gab (HIGH, ~0.5 day engineering effort)

**Rationale:** Zero cost, follows Mastodon standard API, low complexity. Needs live verification against Gab's fork.

**Implementation sketch:**
1. Add `_expand_gab()` method to `NetworkExpander`:
   - GET `https://gab.com/api/v1/accounts/{id}/followers` with Bearer token.
   - Parse Link header for pagination (or use `max_id`).
   - Cap at 500 per direction.
   - Return `ActorDict` list with `discovery_method="gab_followers"` / `"gab_following"`.
2. Add `elif platform == "gab":` branch.
3. Unit test with `respx`.
4. Flag for integration testing against live API to verify Gab fork compatibility.

### Phase 3: X/Twitter (MEDIUM, ~1 day engineering effort)

**Rationale:** Low per-use cost but nonzero. High research value for elite discourse analysis. Needs credit budget integration.

**Implementation sketch:**
1. Add `_expand_x_twitter()` method to `NetworkExpander`:
   - GET `https://api.twitterapi.io/twitter/user/followers?userName=<username>` with `X-API-Key` header.
   - Paginate with `cursor` until 500 results.
   - Repeat for followings endpoint.
   - Return `ActorDict` list with `discovery_method="x_twitter_followers"` / `"x_twitter_following"`.
2. Add `elif platform == "x_twitter":` branch.
3. Integrate with `CreditService` for cost tracking (each page of ~200 users = small credit charge).
4. Unit test with `respx`.

### Deferred: Instagram via Bright Data (LOW, implement only on specific research demand)

---

## 5. Impact on Arena Briefs

The TikTok arena brief (`/docs/arenas/tiktok.md`) already documents the followers/following endpoints in its API table (section 3). No update needed -- the brief is accurate and complete on this point.

The Gab arena brief (`/docs/arenas/gab.md`) does not explicitly mention the Mastodon `/followers` and `/following` endpoints. This is a gap -- the brief should be updated to add these endpoints to the API table and note their availability for network expansion.

The X/Twitter arena brief (`/docs/arenas/x_twitter.md`) does not mention TwitterAPI.io's follower/following endpoints. This should be updated.

---

## 6. Implications for Research Methodology

Adding dedicated graph-based expansion to TikTok, Gab, and X/Twitter changes the `NetworkExpander`'s coverage profile significantly:

| Platform | Current Strategy | Proposed Strategy | Signal Type |
|----------|-----------------|-------------------|-------------|
| Bluesky | Follower/following graph | (unchanged) | Structural |
| Reddit | Comment mention extraction | (unchanged) | Discursive |
| YouTube | Featured channels | (unchanged) | Curatorial |
| Telegram | Forwarding chains | (unchanged) | Content propagation |
| **TikTok** | Co-mention fallback | **Follower/following graph** | **Structural** |
| **Gab** | Co-mention fallback | **Follower/following graph** | **Structural** |
| **X/Twitter** | Co-mention fallback | **Follower/following graph** | **Structural** |
| Discord | Co-mention fallback | (unchanged -- co-mention) | Discursive |
| Instagram | Co-mention fallback | (unchanged unless funded) | Discursive |
| Facebook | Co-mention fallback | (unchanged -- not feasible) | Discursive |
| Threads | Co-mention fallback | (unchanged -- not feasible) | Discursive |

After implementation, 4 of the 11 social media platforms will have structural graph expansion (Bluesky, TikTok, Gab, X/Twitter), covering the platforms most critical for network analysis in Danish discourse research.

The `discovery_method` field on each returned `ActorDict` already distinguishes between expansion strategies. As recommended in `/docs/research_reports/comention_snowball_recommendation.md`, this field should be surfaced in the UI so researchers can see which expansion method produced each suggestion.

---

## Sources

- [TikTok User Followers API Documentation](https://developers.tiktok.com/doc/research-api-specs-query-user-followers)
- [TikTok User Following API Documentation](https://developers.tiktok.com/doc/research-api-specs-query-user-following)
- [TikTok Research API FAQ (Rate Limits)](https://developers.tiktok.com/doc/research-api-faq)
- [TwitterAPI.io Followers Endpoint Documentation](https://docs.twitterapi.io/api-reference/endpoint/get_user_followers)
- [TwitterAPI.io Blog: Get Twitter Account Followers](https://twitterapi.io/blog/get-twitter-account-followers)
- [Mastodon API: Accounts Methods (Followers/Following)](https://docs.joinmastodon.org/methods/accounts/)
- [Bright Data Instagram Followers Scraper](https://brightdata.com/products/web-scraper/instagram/followers)
- [Discord Guild Resource Documentation](https://discord.com/developers/docs/resources/guild)
