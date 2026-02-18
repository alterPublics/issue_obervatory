# Arena Research Brief: Twitch

**Created**: 2026-02-18
**Last updated**: 2026-02-18
**Status**: Deferred (ready for implementation when research need arises)
**Phase**: 3+ (Low priority -- implement only for specific research questions)
**Arena path**: `src/issue_observatory/arenas/twitch/`

---

## 1. Platform Overview

Twitch is the dominant live-streaming platform globally, with approximately 140 million monthly active users. Primarily focused on gaming content, it also hosts "Just Chatting" streams, political commentary, music, and creative content. Chat messages during live streams constitute the primary discourse data of interest for research.

**Critical architectural constraint**: Twitch does not provide any API endpoint for retrieving historical chat messages. Once a stream ends, chat messages are permanently gone unless they were captured in real time during the broadcast. This makes Twitch a **streaming-only collection target** -- the Celery worker must maintain persistent WebSocket connections to monitored channels, capturing chat as it happens. If the worker is offline when a stream occurs, that data is irretrievably lost.

**Role in Danish discourse**: Low. Twitch is primarily a gaming and entertainment platform. Danish Twitch streamers exist but the platform is not a venue for political or public discourse. Occasional crossover occurs when politicians or public figures appear on streams, but this is rare. Twitch's Danish relevance is limited to: gaming community discourse, youth culture, occasional political streamer appearances, and live event commentary.

**Danish user base**: Approximately 10-15% of the 18-34 Danish demographic.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | Twitch Helix API + EventSub WebSocket | $0 | Full access with registered application |
| **Medium** | N/A | -- | No paid tier exists |
| **Premium** | N/A | -- | No paid tier exists |

Twitch is a free-only arena.

---

## 3. API/Access Details

### Helix API (Metadata and Discovery)

**Base URL**: `https://api.twitch.tv/helix`

| Endpoint | Method | Description | Key Parameters |
|----------|--------|-------------|---------------|
| `GET /streams` | GET | List active live streams | `language`, `game_id`, `user_login`, `first` (max 100) |
| `GET /search/channels` | GET | Search for channels by name | `query`, `first` (max 100) |
| `GET /search/categories` | GET | Search for games/categories | `query` |
| `GET /channels` | GET | Channel metadata | `broadcaster_id` |
| `GET /chat/chatters` | GET | List current chatters | `broadcaster_id`, `moderator_id` |
| `GET /users` | GET | User information | `id` or `login` |

**No historical chat endpoint exists.** There is no REST API method for retrieving past chat messages.

### EventSub WebSocket (Real-Time Chat)

**Protocol**: WebSocket
**Endpoint**: `wss://eventsub.wss.twitch.tv/ws`

The `channel.chat.message` subscription type delivers real-time chat messages:

| Property | Value |
|----------|-------|
| Subscription type | `channel.chat.message` (version 1) |
| Transport | `websocket` |
| Cost | 0 per subscription |
| Max subscriptions/connection | 300 |
| Max connections/user token | 3 |
| Max total subscriptions/app | 10,000 |

**Required scopes**: `user:read:chat` (from the bot user). If using app access token: additionally `user:bot` from the bot user, and either `channel:bot` from the broadcaster or moderator status.

**Event payload fields** (per `channel.chat.message` event):

| Field | Description |
|-------|-------------|
| `broadcaster_user_id` | Channel owner ID |
| `broadcaster_user_login` | Channel name |
| `chatter_user_id` | Message sender ID |
| `chatter_user_login` | Message sender name |
| `message_id` | Unique message ID |
| `message.text` | Full message text |
| `message.fragments[]` | Parsed message segments (text, emotes, cheers, mentions) |
| `color` | User's chat color |
| `badges[]` | User's badges (subscriber, moderator, VIP, etc.) |
| `reply` | Reply metadata (if replying to another message) |
| `channel_points_custom_reward_id` | If triggered by a channel point redemption |

### Authentication

**OAuth 2.0**:
1. Register an application at `dev.twitch.tv/console`.
2. Obtain `Client ID` and `Client Secret`.
3. Generate an app access token via Client Credentials grant: `POST https://id.twitch.tv/oauth2/token`.
4. For EventSub chat: generate a user access token with `user:read:chat` scope via Authorization Code grant.

### Python Library

**Package**: `twitchAPI` (PyPI, version 4.x)
- Full Helix API client with async support.
- Built-in EventSub WebSocket handling (`EventSubWebsocket` class).
- OAuth token management.
- Chat message event subscription.

---

## 4. Danish Context

- **Stream-level language filter**: The `GET /streams` endpoint accepts `language=da` to find streams where the broadcaster has declared Danish as the stream language. This identifies Danish streams but does not filter individual chat messages.
- **Chat language**: Individual chat messages have no language field. Chat in Danish streams may be in Danish, English, or mixed.
- **Danish Twitch ecosystem**: Small. Danish streamers are primarily in gaming categories. Occasional streams in "Just Chatting" or "Politics" categories may feature Danish-language discussion.
- **Channel discovery**: Use `GET /streams?language=da` during peak Danish hours (18:00-23:00 CET) to identify active Danish channels. Build a curated `DANISH_TWITCH_CHANNELS` list over time.
- **Volume expectation**: Low. Most Danish Twitch channels have <100 concurrent viewers with correspondingly low chat volume.

---

## 5. Data Fields

| UCR Field | Twitch Source | Notes |
|-----------|-------------|-------|
| `platform` | `"twitch"` | Constant |
| `arena` | `"social_media"` | Shared arena group |
| `platform_id` | `"{broadcaster_user_id}:{message_id}"` | Composite key |
| `content_type` | `"chat_message"` | New content type for ephemeral chat |
| `text_content` | `message.text` | Full chat message text |
| `title` | NULL | Chat messages have no title |
| `url` | `"https://twitch.tv/{broadcaster_user_login}"` | Channel URL (no per-message permalink) |
| `language` | `broadcaster.language` | Stream-level language, not per-message |
| `published_at` | Event timestamp | When the message was sent |
| `author_platform_id` | `chatter_user_id` | Twitch user ID |
| `author_display_name` | `chatter_user_login` | Twitch username |
| `views_count` | NULL | Not applicable to chat messages |
| `likes_count` | NULL | No like system in Twitch chat |
| `shares_count` | NULL | No share mechanism |
| `comments_count` | NULL | Not applicable |
| `raw_metadata` | Full event payload | Include: `broadcaster_user_id`, `broadcaster_user_login`, `badges[]`, `message.fragments[]` (emote details), `color`, `reply` (threading), `channel_points_custom_reward_id` |
| `media_urls` | `[]` | Chat messages do not contain media attachments |

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Free | `{"client_id": "...", "client_secret": "...", "user_token": "..."}` | `"twitch"` |

**Setup process**:
1. Register application at `dev.twitch.tv/console`.
2. Create a Twitch account for the bot.
3. Generate app access token (Client Credentials).
4. Generate user access token with `user:read:chat` scope (Authorization Code flow -- requires one-time browser-based authorization).
5. Store all three values in CredentialPool.

---

## 7. Rate Limits and Multi-Account Notes

| Scope | Limit | Notes |
|-------|-------|-------|
| Helix API | 800 points/minute | App access token; most endpoints cost 1 point |
| EventSub subscriptions | 300 per WebSocket connection | |
| WebSocket connections | 3 per user token | |
| EventSub total | 10,000 subscriptions per application | |

**Effective chat monitoring capacity**: With 3 WebSocket connections at 300 subscriptions each, a single bot account can monitor 900 channels simultaneously. This is more than sufficient for Danish Twitch coverage.

**Multi-account**: Not needed given the generous subscription limits.

---

## 8. Known Limitations

1. **No historical chat data**: The single most critical constraint. If the collector is not connected during a live stream, that chat data is permanently lost. There is no API to retrieve past chat.

2. **Stream must be live**: Chat messages are only generated during active streams. No data is produced when a channel is offline. Collection is entirely dependent on stream schedules.

3. **Emote-heavy content**: Twitch chat is heavily emote-based. Messages may consist largely of emote names (e.g., "Kappa", "PogChamp", "LUL") with limited semantic value for standard text analysis. Consider preprocessing to identify and tag emote usage patterns.

4. **High message velocity**: Popular channels can generate thousands of messages per minute. The collector must handle sustained high throughput. For typical Danish channels with <100 viewers, this is not a concern.

5. **No per-message permalink**: Individual chat messages cannot be linked to or retrieved after the stream. The `url` field can only point to the channel, not the specific message.

6. **Third-party historical datasets**: Community datasets exist on Hugging Face (e.g., historical Twitch chat logs) but are patchy, unofficial, and may have licensing restrictions. Not recommended as a primary or reliable data source.

7. **Subscriber-only chat**: Some channels restrict chat to subscribers. The bot cannot read messages in subscriber-only chat unless it is a subscriber.

8. **Chat moderation**: Messages removed by moderators or AutoMod may still be delivered via EventSub but with reduced content. The behavior is not fully documented.

---

## 9. Collector Implementation Notes

### Architecture

**Streaming-only collection** -- there is no batch mode for Twitch chat.

1. **Channel discovery** (`collect_by_terms`): Use `GET /search/channels` and `GET /streams?language=da` to discover Danish channels. This populates the channel watchlist but does not collect chat. Returns channel metadata as normalized records (not chat messages).

2. **Chat collection** (streaming): A `TwitchStreamer` class (following the `BlueskyStreamer` pattern) that:
   - Connects to the EventSub WebSocket endpoint.
   - Subscribes to `channel.chat.message` for each configured channel.
   - Normalizes and stores messages as they arrive.
   - Runs indefinitely on the `"streaming"` Celery queue.
   - Stores cursor/checkpoint in Redis for reconnection state.

3. **`collect_by_actors`**: Interpret `actor_ids` as Twitch channel broadcaster IDs. Subscribe to their `channel.chat.message` events. Capture all chat from those channels.

### Key Implementation Guidance

1. **Python library**: Use `twitchAPI` (v4.x) for both Helix API calls and EventSub WebSocket handling. The `EventSubWebsocket` class manages connection lifecycle, subscription creation, and reconnection.

2. **Worker configuration**: Streaming task runs on the `"streaming"` queue with extended time limits (24 hours soft, 25 hours hard). Celery Beat restarts the task daily. On restart, resubscribe to all configured channels.

3. **Channel list management**: Maintain a `DANISH_TWITCH_CHANNELS` configuration. Discovery script runs periodically via `GET /streams?language=da` to identify new channels.

4. **Health check**: Call `GET /streams?first=1` with the app access token. Verify 200 response.

5. **Credit cost**: 0 credits (free tier only).

6. **Backpressure**: For high-volume channels, consider buffering messages in Redis before writing to PostgreSQL. Batch inserts reduce database pressure.

---

## 10. Legal Considerations (Expanded)

- **Twitch Developer Agreement**: Permits data collection via official APIs for authorized purposes. Research use of public chat data is not explicitly addressed but is generally considered permissible for academic research.
- **GDPR**: Twitch chat messages contain usernames (personal data). Public chat is publicly visible to anyone who visits the stream. Pseudonymization via `pseudonymized_author_id` is required.
- **Ethical considerations**: Twitch chat participants may not expect their messages to be collected for research. The ephemeral nature of chat creates an expectation of impermanence. Consider whether active disclosure is needed in monitored channels.
- **DSA**: Twitch (owned by Amazon) is likely a VLOP. DSA researcher access provisions have not been applied to Twitch chat data specifically.

**Legal risk assessment**: Low to moderate. Public chat in live streams is broadly considered public discourse, but ethical considerations around participant expectations should be addressed.

---

## 11. Latency and Freshness

| Mode | Latency | Notes |
|------|---------|-------|
| EventSub (streaming) | Milliseconds | Real-time delivery |
| Helix API (metadata) | Near-real-time | Stream status updates within seconds |

**There is no batch/historical mode.** Freshness is binary: either the collector is connected and receiving data, or it is not.

---

## 12. Recommended Architecture Summary

| Component | Recommendation |
|-----------|---------------|
| Arena group | `"social_media"` (existing) |
| Platform name | `"twitch"` |
| Supported tiers | `[Tier.FREE]` |
| Collection pattern | **Streaming only** (EventSub WebSocket) |
| Python library | `twitchAPI` (v4.x) |
| RateLimiter config | 800 points/minute for Helix; EventSub is event-driven |
| Credential pool | `platform="twitch"`, fields: `{"client_id", "client_secret", "user_token"}` |
| Celery queue | `"streaming"` (extended time limits) |
| Beat schedule | Daily: restart streaming task, update channel discovery |
| Content types | `"chat_message"` |
| Danish targeting | `language=da` on stream discovery; channel curation |
| Pre-implementation | Create Twitch app, generate tokens, curate channel list |
