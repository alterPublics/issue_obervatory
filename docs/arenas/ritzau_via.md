# Arena Research Brief: Via Ritzau

**Created**: 2026-02-16
**Last updated**: 2026-02-16
**Status**: Ready for implementation
**Phase**: 1 (Task 1.12, Medium priority)
**Arena path**: `src/issue_observatory/arenas/news_media/ritzau_via/`

---

## 1. Platform Overview

Via Ritzau is the press release distribution platform operated by Ritzaus Bureau A/S, Denmark's only remaining national news agency (founded 1866). Via Ritzau distributes press releases from Danish companies, government agencies, municipalities, organizations, and public institutions. Unlike the Ritzau editorial wire (which is subscription-only and distributed to 170 Danish media clients), Via Ritzau provides free, unauthenticated JSON access to press releases via a REST API.

**Role in Danish discourse**: Via Ritzau is a primary channel through which Danish organizations communicate officially with the media and public. Press releases distributed through Via Ritzau are frequently picked up by Danish news outlets and form the basis of news stories. The platform provides direct access to organizational framing of issues before journalistic mediation. Notably, the Danish police distribute operational announcements through Ritzau's platform after leaving X/Twitter, making this a significant source for public safety communications.

Ritzau is owned by a consortium of Danish media companies including JP/Politikens Hus, DR, Dagbladet Borsen, and Jysk Fynske Medier. It delivers approximately 130,000 news stories annually. Via Ritzau covers a subset of this: the press release channel.

**Access model**: Free, unauthenticated REST API returning JSON. No API keys, no OAuth, no registration required. The API is publicly documented at `https://via.ritzau.dk`.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | Via Ritzau REST API v2 | $0 | Unauthenticated JSON access. No known rate limits. |
| **Medium** | N/A | -- | No medium tier exists. |
| **Premium** | N/A | -- | No premium tier exists. |

Via Ritzau is a free-only arena. The API is entirely open and unauthenticated.

---

## 3. API/Access Details

### Via Ritzau REST API v2

**Base URL**: `https://via.ritzau.dk/json/v2/`

**Key Endpoints**:

| Endpoint | Method | Description | Auth Required |
|----------|--------|-------------|---------------|
| `GET /json/v2/releases` | GET | List/search press releases | No |
| `GET /json/v2/releases/{id}` | GET | Get a specific press release by ID | No |
| `GET /json/v2/publishers` | GET | List available publishers | No |
| `GET /json/v2/channels` | GET | List available channels/categories | No |

**Release list/search parameters** (`/json/v2/releases`):

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | string | Free-text keyword search across release title and body |
| `publisherId` | integer | Filter by publisher (organization) ID |
| `channelId` | integer | Filter by channel/category ID |
| `language` | string | Language filter: `da` (Danish), `en` (English), `fi` (Finnish), `no` (Norwegian), `sv` (Swedish) |
| `fromDate` | string | Start date filter (ISO 8601 or YYYY-MM-DD) |
| `toDate` | string | End date filter |
| `limit` | integer | Results per page |
| `offset` | integer | Pagination offset |

**Response structure** (per release):
- `id`: unique release identifier
- `headline`: press release headline
- `subHeadline`: secondary headline
- `body`: full HTML body content
- `summary`: short summary/lead
- `publishedAt`: publication timestamp (ISO 8601)
- `updatedAt`: last update timestamp
- `publisher`: object with `id`, `name`, `logo` URL
- `channels`: array of channel objects with `id`, `name`
- `language`: language code
- `images`: array of image objects with URL, caption, credit
- `attachments`: array of document attachments (PDF, etc.)
- `url`: canonical URL on via.ritzau.dk
- `contacts`: press contact information

**Authentication**: None required. All endpoints are publicly accessible.

**Rate limits**: No published rate limits. The API is designed for public consumption of press releases. However, aggressive polling should be avoided out of courtesy.

**Pagination**: Offset-based using `limit` and `offset` parameters.

**Content format**: The `body` field contains HTML-formatted text. The collector should strip HTML tags for plain text storage in `text_content` while preserving the original HTML in `raw_metadata`.

---

## 4. Danish Context

- **Language filter**: The API supports `language=da` to return only Danish-language press releases. This is the primary collection filter.
- **Multi-language support**: Via Ritzau distributes releases in Danish, English, Finnish, Norwegian, and Swedish. Some organizations publish the same release in multiple languages. Use `language=da` as the default filter; optionally collect `language=en` for English-language releases about Danish topics.
- **Publisher landscape**: Publishers include:
  - Danish government ministries and agencies (e.g., Statsministeriet, Sundhedsministeriet)
  - Danish municipalities (kommuner)
  - Danish companies (Novo Nordisk, Maersk, Orsted, etc.)
  - Danish NGOs and interest organizations
  - Danish police (Rigspolitiet and regional police districts)
  - Danish universities and research institutions
  - Political parties
- **News cycle integration**: Press releases on Via Ritzau frequently appear verbatim or lightly edited in Danish news media within hours. Cross-referencing Via Ritzau releases with Danish RSS feed content enables tracking of source-to-publication propagation.
- **Content type**: All content from this arena is `content_type: "press_release"`. This is a distinct content type in the universal content record schema, reflecting its nature as official organizational communication rather than editorial content or user-generated content.

---

## 5. Data Fields

Mapping to the Universal Content Record schema:

| UCR Field | Via Ritzau Source | Notes |
|-----------|------------------|-------|
| `platform` | `"ritzau_via"` | Constant |
| `arena` | `"news_media"` | Constant |
| `platform_id` | `id` (release ID) | Unique within Via Ritzau |
| `content_type` | `"press_release"` | Constant for this arena |
| `text_content` | `body` (HTML stripped to plain text) | Strip HTML tags; preserve structure with newlines |
| `title` | `headline` | Primary headline. Store `subHeadline` in `raw_metadata`. |
| `url` | `url` (canonical Via Ritzau URL) | Direct link to the press release |
| `language` | `language` | Natively provided: `da`, `en`, `fi`, `no`, `sv` |
| `published_at` | `publishedAt` | ISO 8601 timestamp |
| `collected_at` | Now | Standard |
| `author_platform_id` | `publisher.id` | Publisher organization ID |
| `author_display_name` | `publisher.name` | Publisher organization name |
| `views_count` | `NULL` | Not provided |
| `likes_count` | `NULL` | Not applicable |
| `shares_count` | `NULL` | Not provided |
| `comments_count` | `NULL` | Not applicable |
| `engagement_score` | `NULL` | No engagement metrics available |
| `raw_metadata` | Full release object | See below |
| `media_urls` | Extract from `images[].url` | Image URLs from the press release |
| `content_hash` | SHA-256 of normalized `text_content` | For deduplication |

**`raw_metadata` should include**:
- `subHeadline`: secondary headline
- `summary`: lead/summary text
- `body_html`: original HTML body (preserved for rich formatting)
- `publisher`: full publisher object (id, name, logo)
- `channels`: array of channel categorizations
- `images`: array of image objects with captions and credits
- `attachments`: array of attached documents (PDF URLs, etc.)
- `contacts`: press contact information (names, emails, phones)
- `updatedAt`: last update timestamp (for detecting edits)

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Free | None | N/A |

**No credentials required.** Via Ritzau's API is fully public and unauthenticated. No entry is needed in the CredentialPool for this arena. The collector should operate without requesting credentials from the pool.

---

## 7. Rate Limits and Multi-Account Notes

| Metric | Value | Notes |
|--------|-------|-------|
| Published rate limit | None known | No documented rate limits |
| Authentication | None | No accounts, no credentials |
| Pagination | Offset-based | `limit` + `offset` parameters |

**Multi-account considerations**: Not applicable. No authentication means no per-account rate limiting.

**Recommended polling interval**: Poll every 15-30 minutes for new releases. Press releases are published during Danish business hours (08:00-17:00 CET) with occasional evening/weekend releases for breaking news. A polling interval of 15 minutes during business hours and 60 minutes outside business hours is appropriate.

**RateLimiter configuration**: Set a conservative rate of 10 requests per minute as a courtesy limit to avoid overloading the Via Ritzau servers. This is far more than needed for normal operation (a single request with `limit=50` and date filtering retrieves all recent releases).

---

## 8. Known Limitations

1. **Press releases only**: Via Ritzau provides access only to press releases distributed through the platform, not to the Ritzau editorial wire service. The editorial wire (which contains original news stories, analysis, and breaking news) is subscription-only and distributed through proprietary systems to subscribing media houses. For editorial wire content, Infomedia's Mediearkiv is the access point, but it requires an institutional subscription not available for this project.

2. **No engagement metrics**: Press releases have no likes, shares, comments, or view counts. Engagement analysis must be done by cross-referencing Via Ritzau content with its uptake in news media (via RSS feeds, GDELT) and social media platforms.

3. **HTML body content**: The `body` field contains HTML-formatted text, not plain text. The normalizer must strip HTML tags while preserving paragraph structure. Be aware of embedded media, tables, and styled content that may not convert cleanly to plain text.

4. **No real-time push**: There is no WebSocket or webhook mechanism. Collection is polling-based only. Press releases appear when published; there is typically no delay between publication and API availability.

5. **Publisher identification**: Publisher names may vary slightly across releases (e.g., abbreviations, department names). Actor resolution should use `publisher.id` as the primary identifier, not the name string.

6. **Historical depth**: The depth of historical data available through the API is not documented. Verify during initial testing how far back the `/json/v2/releases` endpoint returns data.

7. **API stability**: Via Ritzau's API is a public service for press release distribution, not a formally supported developer API. There is no SLA, no versioning guarantee, and no developer documentation portal. The v2 endpoint format may change without notice. Monitor for breaking changes.

8. **Legal considerations**:
   - Press releases are published for public distribution; there is no legal barrier to collection
   - Press contact information (names, emails, phone numbers) in the `contacts` field is personal data under GDPR. Store in `raw_metadata` but include in pseudonymization processing.
   - Publisher logos and images may be subject to copyright. Store URLs in `media_urls` but do not redistribute without checking terms.
   - No Terms of Service restrictions on API access have been identified

---

## 9. Collector Implementation Notes

### Architecture

- **Polling-based collection**: Implement `collect_by_terms` (keyword search) and `collect_by_actors` (publisher-based collection).
- **No authentication overhead**: The simplest arena to implement -- no credential management, no token refresh, no rate limit negotiation.
- **HTML normalization**: The body content requires HTML-to-text conversion as a normalization step.

### Key Implementation Guidance

1. **Search-based collection** (`collect_by_terms`):
   - Use `GET /json/v2/releases?query={term}&language=da&fromDate={date}&toDate={date}`
   - Paginate using `offset` parameter until all results retrieved
   - Apply `language=da` filter by default
   - Date range filtering with `fromDate` and `toDate` for batch collection

2. **Actor-based collection** (`collect_by_actors`):
   - Map actor platform presences to Via Ritzau publisher IDs
   - Use `GET /json/v2/releases?publisherId={id}&fromDate={date}&toDate={date}`
   - The publisher list endpoint (`/json/v2/publishers`) enables discovery of publisher IDs
   - Consider periodic publisher list refresh to discover new organizations

3. **Live tracking** (polling mode):
   - Poll `GET /json/v2/releases?language=da&fromDate={last_poll_time}` at configured interval
   - Store the `publishedAt` of the most recently collected release as the high-water mark
   - During Danish business hours (08:00-17:00 CET): poll every 15 minutes
   - Outside business hours: poll every 60 minutes

4. **HTML-to-text conversion**:
   - Use `beautifulsoup4` or `html2text` to convert the `body` field to plain text
   - Preserve paragraph breaks as newlines
   - Store original HTML in `raw_metadata.body_html`
   - Strip scripts, styles, and non-content elements

5. **Publisher metadata caching**:
   - Fetch and cache the publisher list (`/json/v2/publishers`) on collector startup
   - Refresh daily
   - Use cached publisher names for `author_display_name` rather than relying on per-release publisher data

6. **Deduplication**: Use `platform_id` (release ID) as the primary dedup key. Also check `content_hash` to detect identical releases published under different IDs (e.g., multi-language variants with the same content).

7. **Health check**: `GET https://via.ritzau.dk/json/v2/releases?limit=1&language=da` -- verify 200 response and valid JSON with at least one release.

8. **Credit cost**: 0 credits (free tier only). No credit deduction needed.

9. **Channel/category metadata**: Fetch the channel list (`/json/v2/channels`) and store channel names in `raw_metadata.channels`. These categories (e.g., health, politics, business) are useful for content classification.

10. **Python implementation**: Use `httpx` (async) or `requests` for HTTP calls. No specialized library exists for Via Ritzau. The API is simple enough that raw HTTP calls with response parsing are appropriate.
