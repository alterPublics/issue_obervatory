# Implementation Plan: Discord, Twitch, VKontakte, and Wikipedia Arenas

**Created**: 2026-02-18
**Author**: Research Agent
**Status**: Draft -- ready for team discussion
**Depends on**: IMPLEMENTATION_PLAN.md (Phase architecture), Implementation Plan 2.0 (Phase A-D)

---

## Changelog

- 2026-02-18: Initial creation. Comprehensive implementation plan for four new arenas based on codebase exploration and API research.

---

## 1. Executive Summary

This document provides a complete implementation plan for adding four new arenas to The Issue Observatory: **Discord**, **Twitch**, **VKontakte (VK)**, and **Wikipedia**. Each arena is assessed for API capability, Danish discourse relevance, legal compliance, and architectural fit with the existing `ArenaCollector` pattern.

**Recommendation summary**:

| Arena | Priority | Phase | Danish Relevance | Architecture Pattern | Estimated Effort |
|-------|----------|-------|-----------------|---------------------|-----------------|
| Wikipedia | **High** | Phase 2.5 (next after current Phase 2) | **High** -- editorial attention signals | Batch polling (REST API) | M (3-5 days) |
| Discord | **Medium** | Phase 3+ | **Low-to-Moderate** -- niche communities | Bot-based batch + streaming hybrid | L (5-8 days) |
| Twitch | **Low** | Phase 3+ (deferred) | **Low** -- gaming-focused | Streaming-only (EventSub WebSocket) | L (5-8 days) |
| VKontakte | **Low** | Phase 4 / Future | **Essentially none** for Danish focus | Standard batch polling | M (3-5 days) |

**Build order recommendation**: Wikipedia first, then Discord if research needs warrant it. Twitch and VK should be deferred unless specific research questions require them.

---

## 2. Cross-Cutting Architectural Concerns

Before detailing individual arenas, several cross-cutting decisions apply to multiple arenas in this plan.

### 2.1 Streaming Collection Pattern

Two arenas in this plan (Twitch chat, Discord real-time) require persistent connections that receive events as they occur, rather than polling endpoints. The existing codebase already has infrastructure for this pattern:

**Existing precedent in the codebase:**
- `BlueskyStreamer` in `src/issue_observatory/arenas/bluesky/collector.py` (line 596) implements a WebSocket-based firehose client with exponential backoff reconnection.
- The Celery configuration in `src/issue_observatory/workers/celery_app.py` (line 113) already routes `stream*` tasks to a dedicated `"streaming"` queue.
- Telegram's event handler pattern in `src/issue_observatory/arenas/telegram/collector.py` uses persistent MTProto connections.

**No new base class is needed.** The existing `ArenaCollector` base class is flexible enough because:
1. `collect_by_terms()` and `collect_by_actors()` are already async and can run indefinitely with streaming loops inside them.
2. The streaming worker queue (`"streaming"`) already exists with appropriate routing rules.
3. The `BlueskyStreamer` pattern (separate class composed with the collector for normalization) can be reused directly.

**What IS needed:**
- Add streaming task routes in `celery_app.py` for Discord and Twitch (pattern: `issue_observatory.arenas.discord.tasks.stream*` and `issue_observatory.arenas.twitch.tasks.stream*`).
- Streaming workers should have extended `task_time_limit` (24 hours or unlimited) since they run continuously.
- A cursor/checkpoint persistence mechanism (already demonstrated by `BlueskyStreamer._cursor`) should be formalized as a Redis key pattern: `streaming:cursor:{platform}:{channel_id}`.

### 2.2 Database Schema Implications

**No new extension tables are required** for any of the four arenas. The existing `content_records` table with its JSONB `raw_metadata` column is sufficient. Each arena's platform-specific data will be stored in `raw_metadata`.

However, the following schema considerations apply:

| Arena | `platform` value | `arena` value | `content_type` values | Notes |
|-------|-----------------|---------------|----------------------|-------|
| Wikipedia | `"wikipedia"` | `"reference"` (new arena group) | `"wiki_revision"`, `"wiki_pageview"`, `"wiki_talk"` | New arena group `"reference"` for encyclopedic/reference sources |
| Discord | `"discord"` | `"social_media"` | `"post"` (message), `"comment"` (reply) | Joins existing social_media arena group |
| Twitch | `"twitch"` | `"social_media"` | `"chat_message"` | New content_type for ephemeral chat |
| VK | `"vkontakte"` | `"social_media"` | `"post"`, `"comment"` | Standard social media content types |

**Content type addition**: `"chat_message"` is a new content_type that should be added to any content_type validation. It applies to Twitch chat and potentially Discord messages in high-velocity channels. It signals to analysis code that the content is ephemeral, high-volume, and low-individual-significance (meaningful only in aggregate).

**Wikipedia-specific consideration**: Wikipedia data is fundamentally different from social media posts. A revision is not a "post" -- it is an edit to an existing document. The `text_content` field should contain the edit diff summary or comment, not the full article text. The `title` field maps naturally to the article title. The `url` field points to the specific revision URL. The `author_platform_id` is the Wikipedia username or IP address.

### 2.3 Configuration and Environment Variables

New environment variables required:

| Variable | Arena | Required | Description |
|----------|-------|----------|-------------|
| `DISCORD_BOT_TOKEN` | Discord | Yes (for any collection) | Bot token from Discord Developer Portal |
| `TWITCH_CLIENT_ID` | Twitch | Yes | Twitch application Client ID |
| `TWITCH_CLIENT_SECRET` | Twitch | Yes | Twitch application Client Secret |
| `VK_ACCESS_TOKEN` | VK | Yes | VK standalone app access token |
| (none) | Wikipedia | No | MediaWiki APIs are unauthenticated; only a User-Agent header is required |

All credentials should be stored in the `api_credentials` table via `CredentialPool`, not as flat environment variables, consistent with the project's credential management architecture. The environment variables above are listed for documentation purposes; in practice they are entered through the admin credential UI.

**User-Agent requirement for Wikipedia**: The Wikimedia APIs require a meaningful `User-Agent` header identifying the tool and a contact email. This should be configurable via settings:
```
WIKIPEDIA_USER_AGENT=IssueObservatory/1.0 (https://github.com/...; contact@university.dk) python-httpx/0.27
```

### 2.4 New Arena Group: "reference"

Wikipedia does not fit cleanly into any existing arena group (`social_media`, `news_media`, `web`, `google_search`, `ai_chat_search`). I recommend creating a new arena group `"reference"` for encyclopedic and reference sources. This group could also accommodate future additions such as Wikidata, OpenStreetMap discussion, or scholarly databases.

The `ARENA_DESCRIPTIONS` dict in `src/issue_observatory/arenas/registry.py` should be extended:
```python
"reference": (
    "Reference and encyclopedic sources (Wikipedia, Wikidata) tracking editorial attention"
),
```

---

## 3. Arena: Wikipedia

### 3.1 Platform Overview

Wikipedia is the world's largest collaboratively-edited encyclopedia. For issue tracking research, its value lies not in the content itself (which aims for neutrality), but in the **editorial attention signals**: which articles are being edited, how frequently, by whom, what talk page debates are occurring, and how many people are reading articles on specific topics. These signals reveal which issues the informed public considers important enough to contest or update.

Danish Wikipedia (`da.wikipedia.org`) has its own API endpoint and contains articles on all topics relevant to Danish public discourse. English Wikipedia (`en.wikipedia.org`) is also relevant for topics that have international dimensions.

**Role in Danish discourse**: High. Wikipedia edit activity and pageview data are direct measures of public/editorial attention. When an issue becomes salient in Danish public discourse, the corresponding Wikipedia articles will show increased edit frequency, talk page activity, and pageviews. This provides a complementary signal to social media volume.

**Approximate Danish scope**: da.wikipedia.org has ~290,000 articles. Pageview data is available from July 2015 onward with daily granularity.

### 3.2 API Documentation

Wikipedia data is accessible through three complementary APIs:

#### 3.2.1 MediaWiki Action API

**Base URL**: `https://da.wikipedia.org/w/api.php` (Danish) / `https://en.wikipedia.org/w/api.php` (English)

| Endpoint | Description | Key Parameters |
|----------|-------------|---------------|
| `action=query&list=recentchanges` | List recent edits across all articles | `rcnamespace`, `rctype`, `rclimit` (max 500), `rcstart`, `rcend` |
| `action=query&prop=revisions` | Get revision history of specific pages | `titles`, `rvprop` (content, user, timestamp, comment, size), `rvlimit` (max 500) |
| `action=query&list=search` | Full-text search across articles | `srsearch`, `srnamespace`, `srlimit` |
| `action=query&prop=info` | Page metadata (creation date, edit count, watchers) | `titles`, `inprop=watchers|visitingwatchers` |

**Authentication**: None required for read-only access.

**Required header**: `User-Agent` must identify the tool and provide contact information.

#### 3.2.2 Wikimedia Core REST API

**Base URL**: `https://en.wikipedia.org/w/rest.php/v1` (or `da.wikipedia.org`)

| Endpoint | Description | Notes |
|----------|-------------|-------|
| `GET /page/{title}/history` | Revision history in 20-revision segments | Pagination via `older_than` parameter |
| `GET /revision/{id}` | Single revision details | Includes `delta` (size change), `comment`, `user` |
| `GET /revision/{id}/compare/{id}` | Diff between two revisions | HTML diff output |

#### 3.2.3 Wikimedia Analytics API (Pageviews)

**Base URL**: `https://wikimedia.org/api/rest_v1/metrics/pageviews`

| Endpoint | Description | Parameters |
|----------|-------------|-----------|
| `per-article/{project}/{access}/{agent}/{article}/{granularity}/{start}/{end}` | Pageviews for a specific article | `project`: `da.wikipedia` or `en.wikipedia`; `granularity`: `daily` or `monthly`; `access`: `all-access`, `desktop`, `mobile-web`, `mobile-app` |
| `top/{project}/{access}/{year}/{month}/{day}` | Top-viewed articles for a specific day | Returns ranked list of most-viewed pages |

**Data availability**: From July 2015 onward. Daily granularity. Data populates with approximately 24-hour delay.

#### 3.2.4 Python Libraries

| Library | PyPI Package | Purpose |
|---------|-------------|---------|
| `mwviews` | `mwviews` | Pageview statistics wrapper. `PageviewsClient` with `article_views()`, `top_articles()` |
| `mwclient` | `mwclient` | Full MediaWiki API client. Edit history, page content, search |
| `mediawikiapi` | `mediawikiapi` | Lightweight Wikipedia query library |

**Recommendation**: Use `mwviews` for pageview data and raw `httpx` for the REST API (revision history, recent changes). The `mwclient` library is well-maintained but synchronous; for async collection, direct HTTP calls with `httpx.AsyncClient` are preferred.

### 3.3 Tier Mapping

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | MediaWiki API + Wikimedia Analytics API | $0 | Unlimited read access. Rate limit: polite usage requested (no formal limit, but 200 req/s is the practical maximum before throttling) |
| **Medium** | N/A | -- | Free tier is comprehensive |
| **Premium** | N/A | -- | Free tier is comprehensive |

Wikipedia is a **free-only arena**. There are no paid tiers.

### 3.4 Rate Limits and Quotas

| API | Rate Limit | Notes |
|-----|-----------|-------|
| MediaWiki Action API | No formal limit; throttle to ~1 req/s for polite usage | Wikimedia requests that automated tools make no more than 200 req/s; practically, 1-5 req/s is appropriate for research collection |
| Wikimedia REST API | Same as above | Shares infrastructure with Action API |
| Pageviews API | ~100 req/s | More permissive; cacheable data |

**Recommended RateLimiter configuration**: 5 requests per second (generous but polite).

### 3.5 Data Fields Available (Universal Content Record Mapping)

Wikipedia produces three types of records:

#### Wiki Revision Records (`content_type = "wiki_revision"`)

| UCR Field | Wikipedia Source | Notes |
|-----------|----------------|-------|
| `platform` | `"wikipedia"` | Constant |
| `arena` | `"reference"` | New arena group |
| `platform_id` | `"{wiki_project}:rev:{revision_id}"` | e.g., `"da.wikipedia:rev:12345678"` |
| `content_type` | `"wiki_revision"` | Edit to an article |
| `text_content` | `revision.comment` | Edit summary/comment, NOT full article text |
| `title` | Article title | e.g., `"CO2-afgift"` |
| `url` | `"https://da.wikipedia.org/w/index.php?oldid={rev_id}"` | Permalink to specific revision |
| `language` | `"da"` or `"en"` | Derived from wiki project |
| `published_at` | `revision.timestamp` | When the edit was made |
| `author_platform_id` | `revision.user` | Wikipedia username or IP |
| `author_display_name` | `revision.user` | Same (Wikipedia uses usernames) |
| `views_count` | NULL | Not applicable to revisions |
| `likes_count` | NULL | Wikipedia has no like system |
| `shares_count` | NULL | Not applicable |
| `comments_count` | NULL | Not directly available |
| `raw_metadata` | Full revision object | Include: `delta` (size change in bytes), `minor` flag, `tags`, `parentid`, `namespace`, `is_talk_page` |

#### Pageview Records (`content_type = "wiki_pageview"`)

| UCR Field | Wikipedia Source | Notes |
|-----------|----------------|-------|
| `platform_id` | `"{wiki_project}:pv:{article}:{date}"` | e.g., `"da.wikipedia:pv:CO2-afgift:2026-02-17"` |
| `content_type` | `"wiki_pageview"` | Aggregated daily pageview statistic |
| `text_content` | NULL | No text content for pageview records |
| `title` | Article title | |
| `views_count` | Pageview count | The primary data point |
| `raw_metadata` | Full pageview response | Include: `access` type breakdown, `agent` type breakdown |

#### Talk Page Records (`content_type = "wiki_talk"`)

These are a subset of wiki_revision where the namespace is `Talk:` (namespace 1). They are stored as `wiki_revision` records with `raw_metadata.is_talk_page = true` and `raw_metadata.namespace = 1`.

### 3.6 Search Capabilities

| Capability | Supported | Method |
|------------|-----------|--------|
| Keyword search (article titles) | Yes | `action=query&list=search&srsearch=...` |
| Full-text search (article content) | Yes | Same endpoint, searches content by default |
| Date range filtering | Yes | `rcstart`/`rcend` for recent changes; revision timestamp filtering |
| Author search | Yes | `action=query&list=usercontribs&ucuser=...` |

### 3.7 Actor-Based Collection

Wikipedia "actors" are editors. The `action=query&list=usercontribs` endpoint retrieves all edits by a specific user. This maps to `collect_by_actors()` where `actor_ids` are Wikipedia usernames.

For the Danish context, relevant "actors" might include: known journalists, politicians, or organizations that actively edit Wikipedia articles on policy topics.

### 3.8 Danish Language Support

Danish Wikipedia has a dedicated API endpoint at `da.wikipedia.org`. No language filtering parameter is needed -- querying `da.wikipedia.org` returns Danish content by default. For cross-language analysis, the collector should support configuring which wiki projects to query (e.g., `["da.wikipedia", "en.wikipedia"]`).

### 3.9 Latency and Freshness

| Data Type | Latency | Notes |
|-----------|---------|-------|
| Recent changes / revisions | Near-real-time | Available within seconds of an edit |
| Pageview statistics | ~24 hours | Data populates with approximately one-day delay |

### 3.10 Legal Considerations

- **License**: All Wikipedia content is CC-BY-SA 3.0. No legal restrictions on accessing or storing content.
- **GDPR**: Wikipedia usernames are public. IP addresses of anonymous editors are also public (visible in revision history). Pseudonymization via `pseudonymized_author_id` should still be applied.
- **Terms of Service**: Wikimedia's API terms require a descriptive User-Agent header and polite rate limiting. No explicit prohibition on automated research access.
- **DSA**: Not applicable (Wikipedia is not a commercial platform).

**Legal risk assessment**: Minimal. Wikipedia is the least legally complex arena in the entire project.

### 3.11 Known Limitations and Gotchas

1. **Pageview data is not real-time**: ~24-hour delay. Not suitable for live tracking of breaking events.
2. **Edit summaries may be empty**: Not all editors write meaningful edit comments. The `text_content` field will be NULL for these revisions.
3. **Bot edits**: Many Wikipedia edits are made by automated bots. The `raw_metadata.tags` field can help identify bot edits. Consider filtering them out for human-attention analysis.
4. **Vandalism and reverts**: Short-lived vandalism edits may inflate edit counts. The `raw_metadata.tags` field includes revert indicators.
5. **Recent changes limit**: The `list=recentchanges` endpoint returns at most the last 30 days of data on Wikimedia wikis. For older data, use the revision history API on specific pages.
6. **Pageview ambiguity**: Pageviews count all visits, including bots. The `agent=user` parameter filters out most automated traffic but is not perfect.

### 3.12 Recommended Implementation Approach

**Collection strategies:**

1. **Term-based collection** (`collect_by_terms`): For each search term, find relevant Wikipedia articles via `action=query&list=search`, then collect revision history and pageview data for those articles. This is a two-step process: discovery then monitoring.

2. **Actor-based collection** (`collect_by_actors`): For each Wikipedia username, retrieve their contribution history via `action=query&list=usercontribs`.

3. **Article watchlist collection**: A Wikipedia-specific mode where the researcher defines a list of article titles to monitor. The collector retrieves revision history, talk page activity, and pageview statistics for those articles. This maps most naturally to `collect_by_actors` where the "actors" are article titles stored as `ActorPlatformPresence` records with `platform="wikipedia"`.

**Suggested polling intervals:**
- Batch mode: One-time historical retrieval of revision history and pageviews.
- Live tracking mode: Daily collection of recent changes and pageview updates via Celery Beat.

**Error handling**: Wikipedia APIs are highly reliable. The main error case is rate limiting (HTTP 429), which should trigger exponential backoff.

**Python libraries**: Use `httpx.AsyncClient` for all API calls. Use `mwviews.PageviewsClient` for pageview data (note: synchronous library; wrap in `asyncio.to_thread()`).

### 3.13 Implementation Priority and Phase Assignment

**Priority: High**
**Phase: 2.5** (implement immediately after current Phase 2 work completes, before Phase 3 analysis features)

**Rationale**: Wikipedia provides a unique editorial-attention signal not available from any other arena. It is free, legally unencumbered, well-documented, and technically simple to implement. It produces high-value research data (which topics are being contested, how public attention shifts over time) that directly supports Marres-style issue mapping. The pageview time series is particularly valuable for triangulating with social media volume data.

**Dependencies**: None beyond the standard Phase 0 infrastructure (ArenaCollector base class, Celery, credential pool, normalizer).

---

## 4. Arena: Discord

### 4.1 Platform Overview

Discord is a real-time communication platform originally designed for gaming communities, now widely used for general-purpose community building, education, and interest groups. As of 2025, Discord has over 200 million monthly active users globally.

Discord's architecture is fundamentally different from typical social media platforms:
- Content is organized into **servers** (guilds) containing **channels** (text, voice, forum, stage).
- Messages are semi-public: visible to anyone who joins a server, but not indexed by search engines and not accessible without server membership.
- There is **no global content search API**. You can only access messages within servers where your bot is a member.

**Role in Danish discourse**: Low to moderate. Danish Discord communities exist (the r/Denmark Discord has ~4,100 members; DISBOARD lists servers tagged "denmark", "dansk", "danmark"), but Discord is not a primary venue for Danish public discourse. It hosts niche communities around gaming, education, specific interest groups, and some political discussion servers. Its value is primarily for understanding community-level discourse in specific subcultures rather than broad public debate.

**Danish user base**: Not separately measured in Danish social media statistics. Discord's 45% penetration in Danish demographics overlaps significantly with Snapchat's user base (younger demographics). Likely 10-20% of the Danish population uses Discord regularly, primarily for non-political purposes.

### 4.2 API Documentation

#### 4.2.1 Discord Bot API

**Base URL**: `https://discord.com/api/v10`

| Endpoint | Method | Description | Key Parameters |
|----------|--------|-------------|---------------|
| `GET /channels/{id}/messages` | GET | Fetch messages from a channel | `limit` (max 100), `before`, `after`, `around` |
| `GET /guilds/{id}/channels` | GET | List all channels in a server | |
| `GET /guilds/{id}` | GET | Server metadata | |
| `GET /guilds/{id}/members` | GET | List server members | `limit` (max 1000), `after` |
| `GET /users/{id}` | GET | User information | |

**IMPORTANT LIMITATION**: There is **no search endpoint** available to bot accounts. The `/channels/{id}/messages/search` endpoint exists but is explicitly restricted to user accounts, not bots. Bots can only paginate through messages sequentially using `before`/`after` cursors.

**Authentication**: Bot token (obtained from Discord Developer Portal). Passed as `Authorization: Bot {token}`.

**Gateway (WebSocket)**: `wss://gateway.discord.gg/?v=10&encoding=json`

The Gateway provides real-time events via WebSocket. The bot receives `MESSAGE_CREATE` events for all channels it has access to in all servers it has joined.

#### 4.2.2 Privileged Intents

Discord requires bots to declare which data they need access to via "Gateway Intents":

| Intent | Privileged? | Required for | Notes |
|--------|------------|--------------|-------|
| `GUILD_MESSAGES` | No | Receiving message events | Standard intent |
| `MESSAGE_CONTENT` | **Yes** | Reading message text content | Must be enabled in Developer Portal. Bots in <100 servers can enable without approval. Bots in 75+ servers must apply for approval. |
| `GUILD_MEMBERS` | **Yes** | Member list, join/leave events | Required for actor-based analysis |

**Critical constraint**: The `MESSAGE_CONTENT` privileged intent is required to read the actual text of messages. Without it, the bot receives message events but the `content` field is empty. For a research bot that needs to read messages, this intent is non-negotiable.

**Approval process**: Bots in fewer than 100 servers can enable privileged intents via the Developer Portal without approval. Since this is a research tool deployed to a small number of curated servers, approval should not be needed.

#### 4.2.3 Python Library

**Package**: `discord.py` (PyPI: `discord.py`, version 2.x)

Provides a full async client with `channel.history()` for batch message retrieval and event handlers for real-time message reception.

### 4.3 Tier Mapping

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | Discord Bot API | $0 | Full access to joined servers. Rate limited. |
| **Medium** | N/A | -- | No paid tier exists |
| **Premium** | N/A | -- | No paid tier exists |

Discord is a **free-only arena**. The bot must be invited to each server the researcher wants to monitor, which is a manual curation step analogous to Telegram's channel list.

### 4.4 Rate Limits and Quotas

| Scope | Limit | Notes |
|-------|-------|-------|
| Global | 50 requests/second per bot | Across all API calls |
| Channel messages (GET) | ~5 requests/5 seconds per channel | Per-route limit |
| Channel messages (POST) | 5 messages/5 seconds per channel | Sending messages (not needed for collection) |
| Invalid requests | 10,000 per 10 minutes | 401, 403, or 429 responses |
| Gateway | 120 events/minute (identify limit) | For WebSocket connection |

**RateLimiter configuration**: Parse `X-RateLimit-Remaining` and `X-RateLimit-Reset` response headers for adaptive rate limiting. The discord.py library handles this automatically.

### 4.5 Data Fields Available

| UCR Field | Discord Source | Notes |
|-----------|---------------|-------|
| `platform` | `"discord"` | Constant |
| `arena` | `"social_media"` | Shared group |
| `platform_id` | Message snowflake ID | Globally unique, encodes timestamp |
| `content_type` | `"post"` | All channel messages are posts |
| `text_content` | `message.content` | Requires MESSAGE_CONTENT intent |
| `title` | NULL | Discord messages have no title |
| `url` | `"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"` | Constructed permalink |
| `language` | NULL | Discord has no language field; detect downstream |
| `published_at` | Extracted from snowflake ID or `message.timestamp` | |
| `author_platform_id` | `message.author.id` | Snowflake user ID |
| `author_display_name` | `message.author.username` or `message.author.global_name` | |
| `views_count` | NULL | Discord does not track views |
| `likes_count` | Sum of reaction counts | `message.reactions` array |
| `shares_count` | NULL | No share/repost mechanism |
| `comments_count` | Thread message count (if threaded) | `message.thread.message_count` |
| `raw_metadata` | Full message object | Include: `guild_id`, `channel_id`, `channel_name`, `guild_name`, `attachments`, `embeds`, `mentions`, `referenced_message` (for replies), `thread` info, `reactions` |
| `media_urls` | `message.attachments[].url` | Image/file attachment URLs |

### 4.6 Search Capabilities

| Capability | Supported | Notes |
|------------|-----------|-------|
| Keyword search | **No** (bots cannot use search endpoint) | Must paginate through all messages |
| Author filtering | Yes (client-side) | Filter messages by `author.id` after retrieval |
| Date range | Yes | Use `before`/`after` parameters on GET messages |
| Channel filtering | Yes | Query specific channels by ID |

**Critical limitation**: The inability to search by keyword means Discord collection is fundamentally **channel-first, not term-first**. The researcher curates a list of channels to monitor (analogous to Telegram), and term matching is applied client-side after retrieval.

### 4.7 Actor-Based Collection

`collect_by_actors` can be implemented by iterating through all monitored channels and filtering messages by `author.id`. This is inefficient for large servers. An alternative is to maintain per-user message indexes in `raw_metadata`, but this adds complexity.

**Recommendation**: Implement `collect_by_actors` as a filtered subset of channel-based collection. The `actor_ids` parameter should accept Discord user snowflake IDs.

### 4.8 Danish Language Support

Discord has no native language field or filter. Danish content must be identified through:
1. Curating Danish-language servers to monitor.
2. Client-side language detection on collected messages (downstream enrichment).

### 4.9 Latency and Freshness

| Mode | Latency |
|------|---------|
| Gateway (real-time) | Sub-second |
| REST API (batch) | Near-real-time (messages available immediately) |

### 4.10 Legal Considerations

- **Terms of Service**: Discord's Developer Terms of Service allow bots to collect messages from servers where the bot is a member with appropriate permissions. However, Discord explicitly prohibits "scraping" and "harvesting" user data without consent. A research bot operating in public servers with the server owner's knowledge is likely compliant, but this is a gray area.
- **GDPR**: Discord messages contain personal data (usernames, message content). Pseudonymization via `pseudonymized_author_id` is required. The research must have a valid legal basis (Art. 6(1)(e) + Art. 89 for university research).
- **Ethical considerations**: Unlike public social media platforms, Discord communities often have an expectation of semi-privacy. Researchers should: (a) inform server administrators that a research bot is present, (b) only collect from servers where the community is genuinely public, (c) document the ethical justification in the DPIA.
- **DSA**: Discord is likely a Very Large Online Platform (VLOP) under the DSA, but DSA Article 40 researcher access provisions have not been applied to Discord's architecture (there is no "public data feed" to request access to).

**Legal risk assessment**: Moderate. Higher than most other arenas due to the semi-private nature of Discord communities. Requires explicit ethical justification and server administrator consent.

### 4.11 Known Limitations and Gotchas

1. **No keyword search for bots**: The most significant limitation. All term matching must be done client-side.
2. **Bot must be invited to each server**: Manual curation required. No way to discover or join servers programmatically for research purposes.
3. **MESSAGE_CONTENT privileged intent**: Required for reading message text. Must be enabled in Developer Portal.
4. **Message rate limiting**: Fetching message history is rate-limited to ~5 requests/5 seconds per channel, with 100 messages per request. For a channel with 100,000 messages, this means ~17 minutes to retrieve all history.
5. **No message edit history**: Discord shows current message content only. If a message was edited, only the current version is available via the API.
6. **Attachment URLs expire**: Discord CDN attachment URLs have limited lifetimes. Media must be downloaded during collection if archival is needed.
7. **Server-scoped permissions**: The bot needs per-channel READ_MESSAGE_HISTORY permission. Some channels may be restricted even within a server the bot has joined.

### 4.12 Recommended Implementation Approach

**Dual-mode collection:**

1. **Batch mode** (`collect_by_terms` / `collect_by_actors`): Use the REST API's `GET /channels/{id}/messages` endpoint with `before`/`after` pagination to retrieve historical messages. Apply term matching client-side. Use `discord.py`'s `channel.history()` method.

2. **Streaming mode**: Connect to the Discord Gateway via WebSocket. Receive `MESSAGE_CREATE` events in real time. Filter by server/channel membership and apply term matching on received messages. Use `discord.py`'s event-driven client (`on_message` handler).

**Architecture**: Follow the `BlueskyStreamer` pattern -- a `DiscordStreamer` class that uses a `discord.py` client, receives events, normalizes via the collector, and calls an `on_record` callback.

**Suggested polling intervals:**
- Batch mode: One-time historical retrieval, then daily incremental updates.
- Live tracking: Persistent Gateway connection (streaming worker).

**Curated server list**: Similar to Telegram's `DANISH_TELEGRAM_CHANNELS`, create a `DANISH_DISCORD_SERVERS` configuration in `config/danish_defaults.py` containing server IDs and channel IDs to monitor. Initial set based on DISBOARD discovery:
- r/Denmark Discord
- Danish political discussion servers
- (To be curated based on research needs)

**Error handling**: `discord.py` handles rate limiting, reconnection, and heartbeating automatically. The main error cases are: bot token revocation, server kicks/bans, and channel permission changes.

### 4.13 Implementation Priority and Phase Assignment

**Priority: Medium**
**Phase: 3+** (after core analysis features are complete)

**Rationale**: Discord's Danish relevance is low-to-moderate. The platform is architecturally more complex than most arenas (bot setup, privileged intents, no search, server invitation requirements). The value proposition is niche community monitoring, which is a secondary research need compared to mainstream platforms. However, Discord can be valuable for specific research questions about youth discourse, gaming communities, or educational communities.

**Dependencies**:
- Standard Phase 0 infrastructure
- Pre-Phase: Curate list of Danish Discord servers relevant to research topics
- Pre-Phase: Create Discord bot application and obtain token
- Pre-Phase: Get bot invited to target servers (requires server admin cooperation)

---

## 5. Arena: Twitch

### 5.1 Platform Overview

Twitch is the dominant live-streaming platform, primarily focused on gaming content but increasingly used for "Just Chatting" streams, political commentary, and cultural events. Chat messages during live streams constitute the discourse data of interest.

**Critical architectural constraint**: Twitch does not provide any API endpoint for retrieving historical chat messages. Once a stream ends, chat messages are gone unless they were captured in real time. This makes Twitch a **streaming-only collection target** -- the Celery worker must maintain persistent connections to monitored channels, capturing chat as it happens.

**Role in Danish discourse**: Low. Twitch is primarily a gaming platform. Danish Twitch streamers exist but the platform is not a venue for political or public discourse. Occasional crossover occurs when politicians or public figures appear on streams, but this is rare. Danish Twitch usage is approximately 10-15% of the 18-34 demographic.

### 5.2 API Documentation

#### 5.2.1 Twitch Helix API

**Base URL**: `https://api.twitch.tv/helix`

| Endpoint | Method | Description | Notes |
|----------|--------|-------------|-------|
| `GET /streams` | GET | Get active streams | Filter by `game_id`, `language`, `user_login` |
| `GET /search/channels` | GET | Search for channels | `query` parameter |
| `GET /search/categories` | GET | Search for game/category | |
| `GET /channels` | GET | Channel metadata | `broadcaster_id` |
| `GET /chat/chatters` | GET | List chatters in a channel | Requires moderator or broadcaster auth |

**No historical chat endpoint exists.** There is no `GET /chat/messages` or equivalent for retrieving past chat.

#### 5.2.2 EventSub (Real-Time Chat)

**Protocol**: WebSocket

**Endpoint**: `wss://eventsub.wss.twitch.tv/ws`

The `channel.chat.message` subscription type (version 1, cost 0) delivers real-time chat messages via WebSocket.

| Parameter | Value |
|-----------|-------|
| Subscription type | `channel.chat.message` |
| Transport | `websocket` |
| Max subscriptions per connection | 300 |
| Max connections per user token | 3 |
| Required scope | `user:read:chat` (from chatting user) |

**Authentication**: OAuth 2.0 with Client Credentials (for app access token) plus user token with `user:read:chat` scope.

#### 5.2.3 Python Library

**Package**: `twitchAPI` (PyPI: `twitchAPI`, version 4.x)

Provides full Helix API client, EventSub WebSocket support, and OAuth handling.

### 5.3 Tier Mapping

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | Twitch Helix API + EventSub | $0 | Full access with registered application |
| **Medium** | N/A | -- | No paid tier |
| **Premium** | N/A | -- | No paid tier |

Twitch is a **free-only arena**.

### 5.4 Rate Limits and Quotas

| Scope | Limit | Notes |
|-------|-------|-------|
| Helix API | 800 points/minute (app access token) | Most endpoints cost 1 point |
| EventSub subscriptions | 300 per WebSocket connection | |
| WebSocket connections | 3 per user token | |
| EventSub total subscriptions | 10,000 per application | |

### 5.5 Data Fields Available

| UCR Field | Twitch Source | Notes |
|-----------|-------------|-------|
| `platform` | `"twitch"` | Constant |
| `arena` | `"social_media"` | Shared group |
| `platform_id` | `"{channel_id}:{message_id}"` | Composite ID |
| `content_type` | `"chat_message"` | New content type |
| `text_content` | `message.text` | Chat message text |
| `title` | NULL | Chat messages have no title |
| `url` | `"https://twitch.tv/{channel_name}"` | Channel URL (no per-message permalink) |
| `language` | `broadcaster.language` | Stream-level language, not per-message |
| `published_at` | Event timestamp | When the message was sent |
| `author_platform_id` | `chatter_user_id` | Twitch user ID |
| `author_display_name` | `chatter_user_name` | |
| `views_count` | NULL | Not applicable to chat |
| `likes_count` | NULL | No like system in chat |
| `shares_count` | NULL | No share mechanism |
| `comments_count` | NULL | Not applicable |
| `raw_metadata` | Full event payload | Include: `channel_id`, `channel_name`, `badges` (subscriber, moderator, etc.), `fragments` (emotes), `reply` (if reply to another message), `color` (user's chat color) |

### 5.6 Search Capabilities

| Capability | Supported | Notes |
|------------|-----------|-------|
| Keyword search (chat) | **No** | No historical chat search exists |
| Channel search | Yes | `GET /search/channels` by name |
| Stream search | Yes | `GET /streams` with language filter |
| Date range | **No** | Real-time only |

### 5.7 Danish Language Support

Twitch streams have a `language` field set by the broadcaster. The `GET /streams` endpoint accepts a `language` parameter to filter streams by language:
- `language=da` returns Danish-language streams.

However, this filters by the stream's declared language, not by the language of individual chat messages. Chat messages have no language field.

### 5.8 Latency and Freshness

Real-time only. EventSub delivers messages within milliseconds of being sent in chat. There is no batch or historical mode.

### 5.9 Legal Considerations

- **Terms of Service**: Twitch Developer Agreement permits collection of data via official APIs for authorized purposes. Research use of chat data is a gray area but not explicitly prohibited.
- **GDPR**: Chat messages contain usernames (personal data). Pseudonymization required. Twitch chat is public by nature (anyone can view a stream's chat).
- **Ethical considerations**: Twitch chat participants may not expect their messages to be collected for research. Consider whether opt-in consent mechanisms are needed for specific research contexts.
- **DSA**: Twitch is owned by Amazon and likely a VLOP. DSA researcher access provisions have not been operationalized for Twitch chat data.

**Legal risk assessment**: Low to moderate. Public chat data from live streams is broadly considered public discourse, but ethical review is recommended.

### 5.10 Known Limitations and Gotchas

1. **No historical chat data**: The single most important constraint. If the collector is not connected during a stream, that chat data is permanently lost.
2. **Stream must be live**: Chat messages are only generated during live streams. Collection is dependent on stream schedules.
3. **High-volume channels**: Popular streamers can generate thousands of messages per minute. The collector must handle high message rates without dropping events.
4. **Emote-heavy content**: Twitch chat is heavily emote-based. The `text_content` may be dominated by emote names (e.g., "Kappa PogChamp LUL") which have limited semantic value for text-based analysis.
5. **No per-message permalink**: Unlike most platforms, individual Twitch chat messages cannot be linked to or retrieved after the fact.
6. **Third-party datasets**: Community datasets on Hugging Face contain historical Twitch chat logs but are patchy, unofficial, and may have licensing issues. Not recommended as a primary data source.

### 5.11 Recommended Implementation Approach

**Streaming-only architecture:**

1. **Channel discovery** (`collect_by_terms`): Use `GET /search/channels` and `GET /streams?language=da` to discover Danish channels. This does not collect chat but identifies which channels to monitor.

2. **Chat collection** (streaming): Subscribe to `channel.chat.message` events for curated channels via EventSub WebSocket. Each subscription monitors one channel. With 300 subscriptions per connection and 3 connections per user token, a single bot account can monitor up to 900 channels simultaneously.

3. **Worker architecture**: A dedicated Celery streaming task that:
   - Connects to the EventSub WebSocket.
   - Subscribes to `channel.chat.message` for all configured channels.
   - Normalizes and stores messages as they arrive.
   - Stores cursor/checkpoint in Redis for reconnection.
   - Runs indefinitely on the `"streaming"` queue with extended time limits.

**Suggested polling intervals**: N/A (streaming only).

**Curated channel list**: Create a `DANISH_TWITCH_CHANNELS` configuration listing channels to monitor. Discovery via `GET /streams?language=da` during live hours.

### 5.12 Implementation Priority and Phase Assignment

**Priority: Low**
**Phase: 3+** (deferred until specific research need arises)

**Rationale**: Twitch's Danish discourse relevance is low. The streaming-only architecture adds significant operational complexity (the worker must be running 24/7 to capture data). The emote-heavy, ephemeral nature of Twitch chat makes it difficult to analyze with standard text-based methods. The effort-to-value ratio is unfavorable compared to other arenas.

**Recommendation**: Defer unless a specific research question requires Twitch chat data (e.g., studying gaming community reactions to political events, or analyzing live political debate streams on Twitch).

**Dependencies**:
- Standard Phase 0 infrastructure
- Streaming worker queue (already exists)
- Pre-Phase: Create Twitch application, obtain Client ID and Client Secret
- Pre-Phase: Curate list of Danish Twitch channels

---

## 6. Arena: VKontakte (VK)

### 6.1 Platform Overview

VKontakte (VK) is the dominant social media platform in Russia and the CIS (Commonwealth of Independent States), with approximately 100 million monthly active users. It provides a substantially more open API than most Western platforms.

**Role in Danish discourse**: Essentially none. VK has negligible Danish user penetration. Denmark does not have a significant Russian-speaking diaspora compared to countries like Germany, Finland, or the Baltic states. VK is not a venue for Danish public discourse.

**Value proposition**: VK's value for this project lies entirely in **future expansion** scenarios:
1. Studying Russian-language influence operations targeting Danish/European discourse.
2. Analyzing CIS media ecosystems for comparative research.
3. Tracking Russian-language reactions to Danish policy decisions (e.g., NATO, Arctic policy, energy policy).

### 6.2 API Documentation

**Base URL**: `https://api.vk.com/method/`

| Method | Description | Key Parameters |
|--------|-------------|---------------|
| `wall.search` | Search posts across public walls by keyword | `query`, `count` (max 100), `owners_only`, `extended` |
| `wall.get` | Get posts from a specific community/profile | `owner_id`, `count` (max 100), `offset`, `filter` |
| `newsfeed.search` | Global keyword search across public posts | `q`, `count` (max 200), `start_time`, `end_time`, `latitude`, `longitude` |
| `groups.search` | Find communities by keyword | `q`, `type`, `country_id`, `city_id` |
| `groups.getMembers` | List members of a community | `group_id`, `count` (max 1000) |
| `wall.getComments` | Get comments on a post | `owner_id`, `post_id`, `count` (max 100) |

**Authentication**: OAuth 2.0 with standalone app token. Create an app at `vk.com/dev`, generate an access token with the necessary permissions.

**API version**: Specified via `v` parameter (current: `5.199`). All requests must include `v` and `access_token` parameters.

### 6.3 Tier Mapping

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | VK Official API | $0 | Generous limits, full access to public data |
| **Medium** | N/A | -- | Free tier is comprehensive |
| **Premium** | N/A | -- | Free tier is comprehensive |

VK is a **free-only arena**. The official API provides comprehensive access to public data.

### 6.4 Rate Limits and Quotas

| Scope | Limit | Notes |
|-------|-------|-------|
| Global | 3 requests/second | Per access token |
| `wall.get` | 3 req/s | Standard limit |
| `newsfeed.search` | 3 req/s | Standard limit |
| `execute` method | Allows batching up to 25 API calls per request | Effectively increases throughput to 75 API calls/second |

The `execute` method accepts VKScript code that can call up to 25 API methods per single request. This is the recommended approach for high-throughput collection.

**RateLimiter configuration**: 3 requests per second per access token. Use the `execute` method for batching where possible.

### 6.5 Data Fields Available

| UCR Field | VK Source | Notes |
|-----------|----------|-------|
| `platform` | `"vkontakte"` | Constant |
| `arena` | `"social_media"` | Shared group |
| `platform_id` | `"{owner_id}_{post_id}"` | e.g., `"-12345_67890"` (negative = community) |
| `content_type` | `"post"` or `"comment"` | |
| `text_content` | `post.text` | Post text content |
| `title` | NULL | VK posts have no title |
| `url` | `"https://vk.com/wall{owner_id}_{post_id}"` | Constructed permalink |
| `language` | NULL | VK has no language field; detect downstream |
| `published_at` | `post.date` | Unix timestamp |
| `author_platform_id` | `post.from_id` | VK user/community ID |
| `author_display_name` | Requires separate `users.get` or `groups.getById` call | Not included in post response |
| `views_count` | `post.views.count` | Available for community posts |
| `likes_count` | `post.likes.count` | |
| `shares_count` | `post.reposts.count` | |
| `comments_count` | `post.comments.count` | |
| `raw_metadata` | Full post object | Include: `attachments` (photos, videos, links, documents), `copy_history` (repost chain), `geo`, `signer_id`, `is_pinned`, `marked_as_ads` |
| `media_urls` | Extract from `attachments[].photo.sizes[-1].url` | Largest available photo size |

### 6.6 Search Capabilities

| Capability | Supported | Method |
|------------|-----------|--------|
| Keyword search (global) | Yes | `newsfeed.search` |
| Keyword search (wall) | Yes | `wall.search` |
| Community search | Yes | `groups.search` |
| Date range | Yes | `start_time`/`end_time` (Unix timestamps) in `newsfeed.search` |
| Author filtering | Yes | `wall.get` with `owner_id` |
| Geographic filtering | Yes | `newsfeed.search` supports `latitude`/`longitude` |

### 6.7 Actor-Based Collection

`collect_by_actors` maps directly to `wall.get` with `owner_id` set to the user or community ID. For communities, the `owner_id` is negative (e.g., `-12345`). For users, it is positive.

### 6.8 Danish Language Support

VK has no native language filter. Content language must be determined via:
1. Geographic filtering (`newsfeed.search` with `latitude`/`longitude` near Danish cities).
2. Community curation (finding any Danish-language communities on VK).
3. Client-side language detection on collected text.

In practice, there is virtually no Danish-language content on VK. Any Danish-context research using VK would focus on Russian-language content about Denmark.

### 6.9 Latency and Freshness

| Data Type | Latency |
|-----------|---------|
| Posts and comments | Near-real-time |
| Search results | Minutes (index delay) |

### 6.10 Legal Considerations

- **Terms of Service**: VK's API Terms allow use of publicly available data for non-commercial research purposes. However, VK is a Russian company subject to Russian data protection law (Federal Law No. 152-FZ).
- **GDPR**: VK data contains personal information of Russian/CIS users. If the research processes data of EU residents found on VK, GDPR applies. For data of non-EU residents, the legal framework is different.
- **Sanctions**: EU sanctions against Russia (post-2022) do not explicitly prohibit accessing VK for research purposes, but the sanctions landscape is complex and evolving. Consult with university legal counsel before proceeding.
- **Geo-restrictions**: VK is banned or restricted in several countries (Ukraine, some EU member states). API access from Denmark may require specific network configurations. Access status should be verified before implementation begins.
- **Ethical considerations**: Research involving Russian social media data in the current geopolitical context requires careful ethical framing. Document the research purpose, scope, and data handling procedures explicitly.

**Legal risk assessment**: Moderate to high. The combination of Russian jurisdiction, EU sanctions context, geo-restrictions, and cross-border data transfer concerns makes VK the most legally complex arena in this plan. University legal review is mandatory before implementation.

### 6.11 Known Limitations and Gotchas

1. **Geo-restrictions**: VK may be inaccessible from certain EU countries or IP ranges. Test API access from the deployment location before investing in implementation.
2. **Access token scope**: Some methods require specific permissions (e.g., `wall.search` requires the `wall` permission). Ensure the access token has all necessary scopes.
3. **Community privacy**: VK communities can be closed (private). Only public communities are accessible via the API.
4. **Author name resolution**: Post objects do not include author names directly. A separate `users.get` or `groups.getById` call is needed to resolve `from_id` to a display name. Use the `extended=1` parameter on `wall.get` and `newsfeed.search` to include user/group profiles in the response.
5. **VKScript complexity**: The `execute` method uses VKScript (a JavaScript-like language). Building efficient batch queries requires VKScript proficiency.
6. **API version pinning**: Always include the `v` parameter. Breaking changes between API versions are common.
7. **Rate limit enforcement**: The 3 req/s limit is strictly enforced. Error code 6 ("Too many requests per second") requires backoff.

### 6.12 Recommended Implementation Approach

**Standard batch polling:**

1. **Term-based collection** (`collect_by_terms`): Use `newsfeed.search` for global keyword search with date range filtering. Paginate via `start_from` parameter.

2. **Actor-based collection** (`collect_by_actors`): Use `wall.get` for each community/user with `owner_id` parameter. Paginate via `offset`.

3. **Python library**: Use the `vk_api` package (PyPI: `vk_api`) which handles authentication, rate limiting (queues requests to respect 3 req/s), and pagination.

**Suggested polling intervals:**
- Batch mode: One-time historical retrieval.
- Live tracking: Daily collection via Celery Beat (VK content is not time-critical for this project).

### 6.13 Implementation Priority and Phase Assignment

**Priority: Low**
**Phase: 4 / Future** (not in current roadmap)

**Rationale**: VK has zero relevance to Danish public discourse research. Its inclusion makes sense only for future expansion into Russian-language influence operation tracking or comparative CIS media ecosystem analysis. The legal/compliance overhead (sanctions review, cross-border data transfer assessment) is disproportionate to the research value in the current project scope.

**Recommendation**: Do not implement until a specific research question requires VK data. When that need arises, conduct a legal review first, then implement.

**Dependencies**:
- Standard Phase 0 infrastructure
- Pre-Phase: University legal review of EU sanctions implications
- Pre-Phase: Verify API accessibility from deployment location
- Pre-Phase: Create VK application and obtain access token

---

## 7. Cross-Platform Architecture Notes

### 7.1 Streaming Worker Configuration Updates

For Discord and Twitch, the following additions to `celery_app.py` task routes are needed:

```python
task_routes = {
    # Existing routes...
    "issue_observatory.arenas.discord.tasks.stream*": {
        "queue": "streaming",
        "soft_time_limit": 86_400,   # 24 hours
        "time_limit": 90_000,        # 25 hours (restart cycle)
    },
    "issue_observatory.arenas.twitch.tasks.stream*": {
        "queue": "streaming",
        "soft_time_limit": 86_400,
        "time_limit": 90_000,
    },
}
```

The streaming workers should be configured with extended time limits because they run indefinitely. The soft limit triggers a graceful shutdown and reconnection; the hard limit is a safety net.

### 7.2 Registry and Description Updates

Add to `ARENA_DESCRIPTIONS` in `src/issue_observatory/arenas/registry.py`:

```python
"wikipedia": (
    "Wikipedia editorial attention signals: revision history, talk page activity, and pageview statistics"
),
"discord": (
    "Discord server messages from curated Danish community servers (bot-based collection)"
),
"twitch": (
    "Twitch live stream chat messages captured in real time via EventSub"
),
"vkontakte": (
    "VKontakte (VK) public posts and community content (Russian/CIS focus)"
),
```

### 7.3 Danish Defaults Configuration Updates

Add to `config/danish_defaults.py`:

```python
# Wikipedia - Danish article watchlist seeds
DANISH_WIKIPEDIA_SEED_ARTICLES: list[str] = [
    # To be populated per research query design
]

# Discord - Danish server IDs to monitor (populated via admin UI)
DANISH_DISCORD_SERVERS: list[dict[str, str]] = [
    # {"guild_id": "...", "name": "r/Denmark", "channel_ids": ["..."]}
]

# Twitch - Danish channels to monitor
DANISH_TWITCH_CHANNELS: list[str] = [
    # To be populated per research needs
]
```

### 7.4 Credential Pool Entries

| Platform | Pool `platform` value | Credential fields |
|----------|----------------------|-------------------|
| Wikipedia | N/A (no auth needed) | N/A |
| Discord | `"discord"` | `{"bot_token": "..."}` |
| Twitch | `"twitch"` | `{"client_id": "...", "client_secret": "...", "user_token": "..."}` |
| VK | `"vkontakte"` | `{"access_token": "...", "app_id": "..."}` |

### 7.5 Arena Tier Configuration Matrix Update

Add these rows to the existing matrix in `IMPLEMENTATION_PLAN.md`:

| Arena | Platform | Free Tier | Medium Tier ($) | Premium Tier ($$) |
|-------|----------|-----------|-----------------|-------------------|
| Reference | Wikipedia | MediaWiki API + Pageviews API (free, unlimited) | -- | -- |
| Social Media | Discord | Bot API (free, rate-limited) | -- | -- |
| Social Media | Twitch | Helix API + EventSub (free) | -- | -- |
| Social Media | VKontakte | VK Official API (free, 3 req/s) | -- | -- |

All four are free-only arenas.

---

## 8. Implementation Sequencing

```
Phase 2.5 (Next, 1-2 weeks):
  Wikipedia arena implementation
    - WikipediaCollector (batch: revision history + pageviews)
    - Celery tasks (batch collection + daily pageview update)
    - Arena brief at /docs/arenas/wikipedia.md

Phase 3+ (After core analysis features, if needed):
  Discord arena implementation
    - DiscordCollector (batch: channel history)
    - DiscordStreamer (real-time: Gateway MESSAGE_CREATE)
    - Pre-Phase: Bot setup, server curation, admin consent
    - Arena brief at /docs/arenas/discord.md

Phase 3+ (Deferred unless specifically needed):
  Twitch arena implementation
    - TwitchCollector (streaming-only: EventSub chat)
    - Pre-Phase: Application setup, channel curation
    - Arena brief at /docs/arenas/twitch.md

Phase 4 / Future (Not in current roadmap):
  VKontakte arena implementation
    - VKCollector (batch: wall.get, newsfeed.search)
    - Pre-Phase: Legal review, access verification
    - Arena brief at /docs/arenas/vkontakte.md
```

---

## 9. File Deliverables

When each arena is implemented, the following files should be created:

### Per Arena:

| File | Description |
|------|-------------|
| `src/issue_observatory/arenas/{platform}/` | Arena package directory |
| `src/issue_observatory/arenas/{platform}/__init__.py` | Package init with module docstring |
| `src/issue_observatory/arenas/{platform}/collector.py` | `ArenaCollector` subclass with `@register` decorator |
| `src/issue_observatory/arenas/{platform}/config.py` | Tier configs, constants, default channel/article lists |
| `src/issue_observatory/arenas/{platform}/router.py` | Standalone FastAPI router |
| `src/issue_observatory/arenas/{platform}/tasks.py` | Celery tasks wrapping collector methods |
| `docs/arenas/{platform}.md` | Arena research brief (12-section format) |
| `tests/arenas/test_{platform}_collector.py` | Collector unit tests |
| `tests/arenas/test_{platform}_normalizer.py` | Normalization tests |

### Cross-cutting updates:

| File | Change |
|------|--------|
| `src/issue_observatory/arenas/registry.py` | Add `ARENA_DESCRIPTIONS` entries |
| `src/issue_observatory/workers/celery_app.py` | Add task module includes and streaming routes |
| `src/issue_observatory/config/danish_defaults.py` | Add Danish default configurations |
| `.env.example` | Document new environment variables |
| `docs/status/research.md` | Update arena brief status |

---

## 10. Risk Assessment

| Risk | Arena | Impact | Mitigation |
|------|-------|--------|------------|
| Discord MESSAGE_CONTENT intent denied | Discord | No message text collection possible | Keep bot in <100 servers to avoid approval process |
| Discord server admin rejects bot | Discord | Cannot collect from that server | Maintain relationships with server admins; explain research purpose |
| Twitch streamer goes offline unexpectedly | Twitch | Gap in chat data | Accept as inherent limitation; document coverage gaps |
| VK API inaccessible from EU | VK | Cannot collect any data | Test access before implementation; consider VPN as last resort (with legal review) |
| VK sanctions landscape changes | VK | Must cease collection | Monitor sanctions updates; build collection with easy disable capability |
| Wikipedia bot edits inflate signals | Wikipedia | False attention signals | Filter bot edits using `tags` field; `agent=user` on pageviews |
| High-volume Discord/Twitch channels overwhelm storage | Discord, Twitch | Database growth, performance | Implement per-channel message volume caps; archive old chat data aggressively |

---

## 11. Decision Points for Team Discussion

The following items require team input before proceeding:

1. **New arena group "reference"**: Should Wikipedia be placed in a new `"reference"` arena group, or should it be added to `"web"`? The "reference" designation better communicates its nature but adds a new category.

2. **Wikipedia content_type values**: Should we use `"wiki_revision"`, `"wiki_pageview"`, `"wiki_talk"` as proposed, or use simpler types like `"edit"`, `"statistic"`, `"discussion"`?

3. **Discord ethical framework**: What level of disclosure is required when deploying a research bot to a Discord server? Options range from "inform server admin" to "post a public notice in the server" to "do not collect from Discord at all."

4. **VK legal review trigger**: At what point should university legal counsel be engaged for VK assessment? Before writing any code, or only when a specific research question requires VK data?

5. **Streaming worker lifecycle**: The current streaming architecture assumes workers restart daily (24-hour time limit). Should this be extended to continuous operation with health check pings, or is daily restart acceptable?

---

*This plan is produced by the Research Agent. Individual arena briefs with the full 12-section format will be created at `/docs/arenas/{platform}.md` when each arena enters active implementation. The core-application-engineer agent should use this document as the authoritative specification for implementation sequencing and architectural decisions.*
