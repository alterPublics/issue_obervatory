# Arena Research Brief: Telegram

**Created**: 2026-02-16
**Last updated**: 2026-02-16
**Status**: Ready for implementation
**Phase**: 1 (Task 1.10, High priority)
**Arena path**: `src/issue_observatory/arenas/social_media/telegram/`

---

## 1. Platform Overview

Telegram is a messaging platform with public channels and groups that function as broadcasting and discussion spaces. Telegram channels are one-to-many broadcast tools used by media outlets, political organizations, activist groups, and public figures. For research, Telegram provides access to public channel messages, including full message history, views, forwards, reactions, and media files.

**Role in Danish discourse**: Telegram's Danish user base is relatively small and not well-documented in standard usage statistics. However, Telegram has become significant for specific segments of Danish public discourse:
- Danish alternative media and activist groups maintain active channels
- Some Danish political organizations use Telegram for member communication
- Danish far-right and conspiracy-theory communities have migrated to Telegram after deplatforming from mainstream social media
- Danish government agencies and police have not adopted Telegram as an official channel

Telegram's value is in capturing discourse segments that are underrepresented or absent from mainstream platforms. Channel discovery requires manual curation based on domain knowledge and cross-referencing known actors from other platforms.

**Access model**: Free via Telethon (MTProto client library). Requires Telegram API credentials (api_id, api_hash from my.telegram.org) and phone number authentication. Real-time event handlers for new messages. Full message history access for public channels.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | Telethon (MTProto library), 2-3 accounts via CredentialPool | $0 | Full access to public channels. Account ban risk with aggressive scraping. |
| **Medium** | N/A | -- | No medium tier. |
| **Premium** | N/A | -- | No premium tier. |

Telegram is a free-only arena. The operational cost is the risk of account bans, mitigated by using multiple accounts and respecting rate limits exactly.

---

## 3. API/Access Details

### Telethon (MTProto Client Library)

**Library**: Telethon v1.42+
**Installation**: `pip install telethon`

**Authentication setup**:
1. Go to https://my.telegram.org/apps
2. Create an application to get `api_id` (integer) and `api_hash` (string)
3. First-time authentication requires a phone number and verification code (interactive)
4. After initial auth, a session file is created that enables subsequent non-interactive connections

**Key Methods**:

| Method | Description | Notes |
|--------|-------------|-------|
| `client.iter_messages(channel, search=query)` | Search messages in a channel | Keyword search |
| `client.iter_messages(channel, offset_date=date)` | Get messages before a date | Historical collection |
| `client.iter_messages(channel, limit=N)` | Get N most recent messages | Recent collection |
| `client.get_entity(channel_username)` | Get channel/group metadata | Channel info, member count |
| `client.iter_participants(channel)` | List channel members | Only for groups, not broadcast channels |
| `client(functions.messages.GetRepliesRequest(...))` | Get replies/comments on a post | For channels with comments enabled |

**Event handlers** (real-time):
```python
@client.on(events.NewMessage(chats=channel_list))
async def handler(event):
    # Process new message in real-time
```

**Rate limits**: Telegram enforces rate limits via `FloodWaitError`. When this error is raised, the `seconds` attribute specifies exactly how long to wait. The wait time MUST be honoured exactly -- waiting less will result in longer bans. Typical wait times range from a few seconds to several minutes depending on the action and frequency.

**Session management**: Telethon creates a `.session` file (SQLite database) that stores the authenticated session. This file must be preserved between restarts. For CredentialPool integration, session files should be stored as base64-encoded strings in the credential payload or in a persistent volume.

### TGStat API (Supplementary)

**URL**: https://tgstat.com/
**Coverage**: Strongest in Russia/CIS regions. Limited Danish channel coverage.
**Features**: Subscriber dynamics, cross-channel mention tracking, keyword monitoring.
**Cost**: Free tier available; paid plans for API access.
**Recommendation**: Not recommended as primary source for Danish research. May be useful for discovering Danish channels through cross-referencing.

---

## 4. Danish Context

- **No language filter**: Telegram has no built-in language filtering. Danish content must be identified by:
  1. Monitoring known Danish-language channels (curated list)
  2. Client-side language detection on collected messages
- **Channel discovery**: This is a manual, domain-knowledge-driven process. Strategies:
  1. Identify Danish actors known from other platforms and search for their Telegram presence
  2. Search for Danish keywords in public channels
  3. Use t.me search and third-party directories (tgstat.com, telegramchannels.me)
  4. Snowball: follow channel cross-references and forwarded message sources
  5. Consult existing research on Danish Telegram communities
- **Pre-Phase task E.5**: IMPLEMENTATION_PLAN.md specifies a pre-Phase 1 task to curate an initial list of Danish public channels. This list is a prerequisite for this arena. Document as a use case in `docs/use_cases/telegram_danish.md`.
- **Content types**: Danish Telegram content includes text posts, forwarded messages from other channels, images, videos, documents, polls, and voice messages. Text extraction is straightforward for text posts; media requires separate download.
- **Danish far-right monitoring**: Telegram is a significant platform for Danish far-right and conspiracy communities. Research in this space requires careful ethical documentation (Pre-Phase task E.3).

---

## 5. Data Fields

Mapping to the Universal Content Record schema:

| UCR Field | Telegram Source | Notes |
|-----------|----------------|-------|
| `platform` | `"telegram"` | Constant |
| `arena` | `"social_media"` | Constant |
| `platform_id` | `message.id` (integer, unique per channel) | Combine with channel ID for global uniqueness: `{channel_id}_{message_id}` |
| `content_type` | `"post"` | Channel posts. Could also be `"comment"` for discussion replies. |
| `text_content` | `message.text` or `message.raw_text` | `raw_text` strips formatting. `text` preserves markdown-like formatting. Use `raw_text` for analysis. |
| `title` | `NULL` | Telegram messages have no title |
| `url` | `https://t.me/{channel_username}/{message_id}` | Constructed from channel username and message ID |
| `language` | Detect from `message.text` | No native language field. Use language detection library. |
| `published_at` | `message.date` | UTC datetime |
| `collected_at` | Now | Standard |
| `author_platform_id` | `message.sender_id` or channel ID | For channel posts, the sender is the channel itself |
| `author_display_name` | Channel title or sender name | |
| `views_count` | `message.views` | Available for channel posts |
| `likes_count` | Sum of `message.reactions` | Sum all reaction counts |
| `shares_count` | `message.forwards` | Number of times forwarded |
| `comments_count` | `message.replies.replies` (if comments enabled) | |
| `engagement_score` | Compute from views, forwards, reactions | Normalized |
| `raw_metadata` | Full message attributes | See below |
| `media_urls` | Extract from `message.media` | Photo, video, document URLs (require download) |
| `content_hash` | SHA-256 of normalized text | |

**`raw_metadata` should include**:
- `channel_id`: source channel ID
- `channel_username`: source channel username
- `channel_title`: source channel title
- `fwd_from`: forwarded message source (channel/user, message ID)
- `reply_to`: replied-to message ID
- `media_type`: type of attached media (photo, video, document, poll, etc.)
- `reactions`: list of reaction types and counts
- `edit_date`: if message was edited, the edit timestamp
- `grouped_id`: for media groups (multiple photos in one post)
- `via_bot_id`: if posted via a bot

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Free | `{"api_id": 12345, "api_hash": "abc...", "phone": "+45...", "session_string": "base64..."}` | `"telegram"` |

**Critical notes**:
- `api_id` and `api_hash` are obtained from https://my.telegram.org/apps
- `phone` is the phone number associated with the Telegram account
- `session_string` is the serialized Telethon session (base64-encoded) -- this replaces the need for interactive phone verification after initial setup
- Initial session creation requires interactive verification (enter code sent to phone). This must be done once per account before adding to the CredentialPool.
- **2-3 accounts recommended** per IMPLEMENTATION_PLAN.md to distribute load and mitigate ban risk
- Each account needs a unique phone number (Danish or international)

---

## 7. Rate Limits and Multi-Account Notes

| Action | Approximate Limit | Notes |
|--------|--------------------|-------|
| Messages per channel history request | 100 per request | Pagination via `offset_id` or `offset_date` |
| Concurrent channel subscriptions | ~500 per account | For event handlers |
| `FloodWaitError` | Variable (seconds to minutes) | Server-specified wait time. MUST honour exactly. |
| Channel joins per day | ~20-50 | New channel joins are rate-limited |

**Multi-account strategy (essential)**:
- Use 2-3 accounts to distribute monitoring load
- Assign channels to accounts to avoid all accounts monitoring the same channel
- Rotate which account handles historical backfill vs. real-time monitoring
- If one account is banned, the others continue operating

**FloodWaitError handling**:
- When Telethon raises `FloodWaitError(seconds=N)`:
  - Wait exactly N seconds (not less, not more than necessary)
  - Log the wait time and the action that triggered it
  - Set a cooldown on the credential in CredentialPool
  - Redis key `credential:cooldown:{id}` with TTL = N seconds

**Account ban risk**:
- Aggressive scraping patterns (rapid history downloads, joining many channels quickly) increase ban risk
- Mitigate by: spacing requests, honoring FloodWait, using aged accounts (not newly created), limiting channel joins per day
- Document multi-account use and ban risk mitigation in ethics paperwork (Pre-Phase task E.3)

**RateLimiter configuration**: Do not use a fixed rate limit. Instead, rely on FloodWaitError as the rate signal and back off accordingly. Set a conservative default of ~30 requests per minute per account as a baseline, adjustable based on observed FloodWait frequency.

---

## 8. Known Limitations

1. **Account ban risk**: The primary operational risk. Accounts can be temporarily or permanently banned for aggressive scraping. Mitigation: multiple accounts, conservative request rates, exact FloodWait compliance. Cannot be fully eliminated.

2. **Interactive initial setup**: Each account requires one-time interactive authentication (phone verification code). This cannot be automated. Session strings must be generated manually and then stored in the CredentialPool.

3. **Channel discovery is manual**: There is no reliable automated method to discover all Danish Telegram channels. The initial channel list depends on domain expertise and manual curation (Pre-Phase task E.5).

4. **No language filter**: All content from monitored channels is collected regardless of language. Language detection must be applied client-side.

5. **Media download complexity**: Photos, videos, and documents are not directly available as URLs. They must be downloaded via Telethon (`client.download_media(message)`), which consumes bandwidth and storage. Consider downloading only metadata/thumbnails by default and full media on demand.

6. **Message edits and deletions**: Channel admins can edit or delete messages. Edits update the message in place; deletions remove it. For complete tracking, implement edit detection (compare `edit_date` with stored version) and handle `MessageDeleted` events.

7. **Session file management**: Telethon sessions are stored as SQLite files. For containerized deployment, sessions must be persisted outside the container (volume mount) or serialized as strings in the database.

8. **No search across channels**: Telegram's API does not support global search across all public channels. Search (`iter_messages(channel, search=query)`) only works within a single specified channel. This means keyword-based discovery requires iterating over all monitored channels.

9. **Legal and ethical considerations**:
   - Telegram channels are public, but members have a reasonable expectation of semi-privacy in some groups
   - GDPR applies to all personal data: usernames, profile photos, message content
   - Standard pseudonymization via `pseudonymized_author_id` is required
   - For channels focused on sensitive topics (health, politics, religion), special category data under Art. 9 GDPR may be present. Document in DPIA.
   - Multi-account use should be documented in ethics paperwork
   - Telegram's ToS prohibit automated mass data collection, but Telethon is widely used for research without enforcement action

10. **Encrypted chats inaccessible**: Telegram's end-to-end encrypted "Secret Chats" are not accessible via the API. This arena only covers public channels and groups.

---

## 9. Collector Implementation Notes

### Architecture

- **Dual mode**: Historical backfill (`collect_by_terms` / `collect_by_actors`) and real-time event handler (live tracking).
- **Persistent worker**: Real-time monitoring requires a long-running Celery worker with active Telethon connections. This is architecturally different from request-response API arenas.
- **Channel registry**: Maintain a configurable list of monitored channel usernames/IDs, either in `danish_defaults.py` or a database table.

### Key Implementation Guidance

1. **Session management**:
   - Store session strings in the CredentialPool (Fernet-encrypted with other credentials)
   - On worker startup, deserialize the session string and create a Telethon client
   - Use `StringSession` for serializable sessions: `session_string = StringSession.save(client.session)`

2. **Historical collection** (`collect_by_terms` and `collect_by_actors`):
   - For each monitored channel, use `client.iter_messages(channel)` with date filters
   - Paginate using `offset_date` for date-bounded collection
   - Filter by search terms client-side (or use `search` parameter for single-term searches within a channel)
   - Limit batch size to avoid triggering FloodWait

3. **Real-time collection** (live tracking):
   - Register event handlers for `events.NewMessage` on monitored channels
   - Handler processes each message: normalize, match against query design terms, store if matched
   - Keep the Telethon client connection alive in a dedicated Celery worker
   - Handle disconnections with automatic reconnection

4. **Channel assignment to accounts**:
   - Distribute monitored channels across available accounts (credentials)
   - Assign based on load balancing (equal number of channels per account)
   - Store the assignment in Redis or database for persistence

5. **FloodWait handling**:
   ```python
   from telethon.errors import FloodWaitError
   try:
       messages = await client.iter_messages(channel, limit=100)
   except FloodWaitError as e:
       # Report to CredentialPool for cooldown tracking
       await credential_pool.report_cooldown(credential_id, seconds=e.seconds)
       await asyncio.sleep(e.seconds)
       # Retry after wait
   ```

6. **Forwarded message tracking**: When a message is forwarded from another channel, store the source channel info in `raw_metadata.fwd_from`. This enables cross-channel propagation analysis.

7. **Actor-based collection**:
   - Map actors to Telegram channel usernames or user IDs
   - Use `client.get_entity(username)` to resolve the entity
   - Collect all messages from the actor's channel(s)

8. **Health check**: For each credential/account, attempt `client.get_me()` to verify the session is valid and the account is not banned. Check each monitored channel with `client.get_entity(channel)`.

9. **Credit cost**: 0 credits (free tier). All costs are operational (phone numbers, proxy services if used).

10. **Asyncio integration**: Telethon is natively async. The collector must run in an async context. Use `asyncio.run()` or integrate with Celery's async task support. Each Telethon client maintains its own event loop.
