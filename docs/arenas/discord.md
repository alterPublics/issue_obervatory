# Arena Research Brief: Discord

**Created**: 2026-02-18
**Last updated**: 2026-02-18
**Status**: Ready for implementation (pending ethical review)
**Phase**: 3+ (Medium priority -- implement when specific research need arises)
**Arena path**: `src/issue_observatory/arenas/discord/`

---

## 1. Platform Overview

Discord is a real-time communication platform with over 200 million monthly active users globally. Originally designed for gaming communities, it is now used broadly for community building, education, interest groups, and some political discussion. Content is organized into servers (guilds) containing channels (text, voice, forum, stage).

Discord's architecture is fundamentally different from conventional social media: content is semi-public (visible to server members but not indexed by search engines), there is no global content feed or discovery mechanism, and access requires server membership. This makes Discord a **curated-community collection target** where the researcher must identify and join specific servers of interest.

**Role in Danish discourse**: Low to moderate. Danish Discord communities exist -- the r/Denmark Discord server has approximately 4,100 members, and DISBOARD lists dozens of servers tagged "denmark", "dansk", and "danmark" including political debate servers, social communities, and interest-based groups. However, Discord is not a primary venue for Danish public discourse compared to Facebook, X/Twitter, or even Reddit. Its value lies in capturing niche community conversations, particularly among younger demographics (18-34), gaming communities, and educational communities.

**Danish user base**: Not separately measured in Danish social media statistics. Estimated at 10-20% of the Danish population, overlapping heavily with the Snapchat demographic. Primarily used for non-political purposes.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | Discord Bot API + Gateway | $0 | Full access to joined servers. Rate limited (50 req/s global). |
| **Medium** | N/A | -- | No paid tier exists. |
| **Premium** | N/A | -- | No paid tier exists. |

Discord is a free-only arena.

---

## 3. API/Access Details

### REST API (Batch Collection)

**Base URL**: `https://discord.com/api/v10`

**Key endpoints**:

| Endpoint | Method | Description | Auth Required |
|----------|--------|-------------|---------------|
| `GET /channels/{id}/messages` | GET | Fetch messages from a channel | Yes (Bot token) |
| `GET /guilds/{id}/channels` | GET | List all channels in a server | Yes |
| `GET /guilds/{id}` | GET | Server metadata | Yes |
| `GET /guilds/{id}/members` | GET | List server members | Yes |

**Message pagination parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | int | Messages per request (max 100) |
| `before` | snowflake | Get messages before this ID |
| `after` | snowflake | Get messages after this ID |
| `around` | snowflake | Get messages around this ID |

**IMPORTANT LIMITATION**: Bots cannot use the `/channels/{id}/messages/search` endpoint. Content search by keyword is NOT available via the bot API. All term matching must be done client-side after message retrieval.

### Gateway API (Real-Time Streaming)

**Protocol**: WebSocket
**Endpoint**: `wss://gateway.discord.gg/?v=10&encoding=json`

The Gateway delivers real-time events. The bot receives `MESSAGE_CREATE` events for all channels it can access across all servers it has joined.

**Privileged Intents** (required):

| Intent | Privileged? | Required For | Approval |
|--------|------------|--------------|----------|
| `GUILD_MESSAGES` | No | Receiving message events in servers | Automatic |
| `MESSAGE_CONTENT` | **Yes** | Reading the text content of messages | Enable in Developer Portal; no approval needed for bots in <100 servers |
| `GUILD_MEMBERS` | **Yes** | Member list and join/leave events | Same as above |

Without `MESSAGE_CONTENT`, the bot receives message events but the `content` field is empty. This intent is mandatory for research collection.

### Authentication

Bot token obtained from the [Discord Developer Portal](https://discord.com/developers/applications). Passed as `Authorization: Bot {token}` header on all requests.

### Python Library

**Package**: `discord.py` (PyPI, version 2.x)
**Key methods**:
- `channel.history(limit=100, before=..., after=...)` -- async iterator for batch message retrieval
- `@client.event async def on_message(message)` -- event handler for real-time messages

---

## 4. Danish Context

- **No native language filter**: Discord messages have no language field. Danish content is identified through server/channel curation and downstream language detection.
- **Server curation**: The researcher must identify Danish-language servers via:
  - DISBOARD (`disboard.org/servers/tag/denmark`, `/tag/dansk`, `/tag/danmark`)
  - Discord.me (tag-based discovery)
  - Known communities (r/Denmark Discord, Danish political debate servers)
  - Snowball: discovering new servers via links in other Danish communities
- **Danish-relevant servers** (initial discovery, status as of 2026-02-18):
  - r/Denmark Discord (~4,100 members) -- general Danish community
  - Danish political debate servers (multiple, identified via DISBOARD tags)
  - "Rottehullet" -- Danish community with debate channels
  - Various Danish gaming, education, and interest servers
- **Bot deployment**: The research bot must be invited to each server by a server administrator. This is a manual process requiring relationship-building with community administrators.

---

## 5. Data Fields

| UCR Field | Discord Source | Notes |
|-----------|---------------|-------|
| `platform` | `"discord"` | Constant |
| `arena` | `"social_media"` | Shared arena group |
| `platform_id` | Message snowflake ID | Globally unique; encodes creation timestamp |
| `content_type` | `"post"` | All channel messages |
| `text_content` | `message.content` | **Requires MESSAGE_CONTENT privileged intent** |
| `title` | NULL | Discord messages have no title |
| `url` | `"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"` | Constructed permalink |
| `language` | NULL | No language field; detect downstream |
| `published_at` | Extracted from snowflake ID or `message.timestamp` | |
| `author_platform_id` | `message.author.id` | Snowflake user ID |
| `author_display_name` | `message.author.global_name` or `message.author.username` | |
| `views_count` | NULL | Discord does not track views |
| `likes_count` | Sum of `message.reactions[].count` | Reaction emoji counts |
| `shares_count` | NULL | No share/repost mechanism |
| `comments_count` | `message.thread.message_count` | If the message spawned a thread |
| `raw_metadata` | Full message object | Include: `guild_id`, `guild_name`, `channel_id`, `channel_name`, `attachments[]`, `embeds[]`, `mentions[]`, `referenced_message` (replies), `thread`, `reactions[]`, `pinned`, `type` (message type enum) |
| `media_urls` | `message.attachments[].url` | Image/file attachment URLs (CDN URLs, may expire) |

**Snowflake ID timestamp extraction**: Discord snowflake IDs encode the creation timestamp. Extract with: `timestamp_ms = (snowflake >> 22) + 1420070400000`. This can serve as a cross-check on `message.timestamp`.

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Free | `{"bot_token": "..."}` | `"discord"` |

**Setup process**:
1. Create an application at `discord.com/developers/applications`.
2. Add a Bot to the application.
3. Enable `MESSAGE_CONTENT` and `GUILD_MEMBERS` privileged intents in the Bot settings.
4. Generate a bot token (this is the credential to store in CredentialPool).
5. Generate an OAuth2 invite URL with `bot` scope and `Read Message History`, `View Channels` permissions.
6. Share the invite URL with target server administrators.

---

## 7. Rate Limits and Multi-Account Notes

| Scope | Limit | Reset | Notes |
|-------|-------|-------|-------|
| Global | 50 requests/second | Rolling | Per bot token |
| `GET /channels/{id}/messages` | ~5 requests/5 seconds | Per channel | Per-route limit |
| Invalid requests | 10,000 per 10 minutes | Rolling | 401/403/429 responses |
| Gateway events | 120 identifies/minute | Rolling | WebSocket connection |

**Rate limit response headers**: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `X-RateLimit-Reset-After`, `X-RateLimit-Bucket`. Parse these for adaptive rate limiting.

**discord.py handles rate limiting automatically**: The library queues requests and waits for rate limit windows to reset. No manual rate limiter configuration is needed when using `discord.py`. However, the project's `RateLimiter` should still be configured for consistency and for raw HTTP requests outside the library.

**Multi-account**: Generally not needed. A single bot account can join up to ~100 servers without privileged intent approval. For larger deployments, multiple bot tokens could be rotated via CredentialPool.

**Batch retrieval speed**: At 100 messages per request and ~5 requests per 5 seconds per channel, retrieving a channel's full history proceeds at ~100 messages/second. A channel with 100,000 messages takes approximately 17 minutes to fully retrieve.

---

## 8. Known Limitations

1. **No keyword search for bots**: The most significant constraint. The `/messages/search` endpoint is restricted to user accounts (not bot tokens). All term matching must be done client-side after retrieving messages from channels.

2. **Bot must be invited to each server**: No programmatic way to discover or join servers. Requires manual relationship with server administrators.

3. **MESSAGE_CONTENT privileged intent required**: Without this intent, message `content` is empty. Must be enabled in the Developer Portal. Bots in 75+ servers must apply for approval from Discord.

4. **No message edit history**: Only the current version of edited messages is available. If a message was edited, the original text is lost.

5. **Attachment URLs expire**: Discord CDN URLs for file attachments have limited lifetimes. Media must be downloaded during collection if archival is needed.

6. **Server-scoped permissions**: The bot needs per-channel `READ_MESSAGE_HISTORY` permission. Some channels within a server may restrict this even if the bot has server-wide access.

7. **No view counts**: Discord does not track or expose message view counts.

8. **Thread complexity**: Discord threads are separate channels spawned from messages. Thread messages require separate API calls to retrieve. The `thread.message_count` on the parent message gives a count but not the content.

9. **Ephemeral messages**: Some interactions produce ephemeral messages visible only to the invoking user. These are not accessible to the bot.

---

## 9. Collector Implementation Notes

### Architecture

**Dual-mode collection** (following the BlueskyStreamer pattern):

1. **Batch mode** (`collect_by_terms` / `collect_by_actors`):
   - Use `discord.py`'s `channel.history()` async iterator to retrieve historical messages.
   - Iterate through all channels in configured servers.
   - Apply term matching client-side (case-insensitive substring match on `message.content`).
   - For `collect_by_actors`: filter messages by `author.id`.

2. **Streaming mode** (separate `DiscordStreamer` class):
   - Connect to the Discord Gateway via `discord.py`'s `Client`.
   - Handle `on_message` events for real-time collection.
   - Filter by configured server/channel IDs.
   - Apply term matching on incoming messages.
   - Runs as a dedicated Celery streaming task on the `"streaming"` queue.

### Key Implementation Guidance

1. **Server/channel configuration**: Create a `DANISH_DISCORD_SERVERS` configuration in `config/danish_defaults.py` or in the arena config. Structure:
   ```python
   DANISH_DISCORD_SERVERS = [
       {"guild_id": "123...", "name": "r/Denmark", "channel_ids": ["456...", "789..."]},
   ]
   ```
   If `channel_ids` is empty, monitor all text channels in the server.

2. **Batch collection flow**:
   - For each configured server, list channels via `GET /guilds/{id}/channels`.
   - For each text channel, retrieve messages via `channel.history(after=last_collected_id, limit=None)`.
   - Apply date range filtering and term matching.
   - Normalize each message.

3. **Streaming collection flow**:
   - The `DiscordStreamer` class creates a `discord.Client` with `MESSAGE_CONTENT` intent.
   - `on_ready`: Log connected servers and channels.
   - `on_message`: Check if the message is from a monitored server/channel. If so, normalize and call `on_record` callback.
   - Store the last processed message ID per channel in Redis: `streaming:cursor:discord:{channel_id}`.

4. **Health check**: Verify bot token validity by calling `GET /users/@me` and checking for a 200 response.

5. **Credit cost**: 0 credits (free tier only).

6. **Error handling**: `discord.py` handles rate limiting, reconnection, and heartbeating. Main failure modes: token revocation, server kick/ban, channel permission change.

---

## 10. Legal Considerations (Expanded)

- **Discord Developer Terms of Service**: Permit bots to access messages from servers where the bot is a member with appropriate permissions. Prohibit "scraping" and "harvesting" user data without consent. Research bot operating in public servers with server owner knowledge is likely compliant, but this is a gray area that requires careful ethical consideration.
- **GDPR**: Discord messages contain personal data (usernames, message content, potentially identifiable information in message text). Pseudonymization via `pseudonymized_author_id` is required. Legal basis: Art. 6(1)(e) + Art. 89 for university research.
- **Ethical considerations**: Discord communities have an expectation of semi-privacy. Unlike Twitter/X or Reddit, Discord content is not publicly indexed. Recommendations:
  - Inform server administrators that a research bot is present.
  - Only collect from servers with genuinely public communities.
  - Consider posting a research disclosure notice in monitored servers.
  - Document the ethical justification in the DPIA.
  - Consult with university ethics board if collecting from communities with vulnerable populations.
- **DSA**: Discord is likely a VLOP but DSA Article 40 researcher access has not been operationalized for Discord.

**Legal risk assessment**: Moderate. Higher than most arenas due to the semi-private nature of Discord communities. Ethical review recommended before deployment.

---

## 11. Latency and Freshness

| Mode | Latency | Notes |
|------|---------|-------|
| REST API (batch) | Near-real-time | Messages available via API immediately after sending |
| Gateway (streaming) | Sub-second | Real-time event delivery |

---

## 12. Recommended Architecture Summary

| Component | Recommendation |
|-----------|---------------|
| Arena group | `"social_media"` (existing) |
| Platform name | `"discord"` |
| Supported tiers | `[Tier.FREE]` |
| Collection pattern | Hybrid: batch (REST API) + streaming (Gateway WebSocket) |
| Python library | `discord.py` (v2.x) |
| RateLimiter config | Handled by discord.py; project RateLimiter at 50 req/s as safety net |
| Credential pool | `platform="discord"`, fields: `{"bot_token": "..."}` |
| Celery queue | Default (batch), `"streaming"` (Gateway) |
| Beat schedule | Daily: incremental batch update for monitored channels |
| Content types | `"post"` |
| Danish targeting | Server/channel curation (no native language filter) |
| Pre-implementation | Create bot, enable intents, get invited to target servers, ethical review |
