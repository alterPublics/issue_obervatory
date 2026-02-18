# Arena Research Brief: Danish RSS Feeds

**Created**: 2026-02-16
**Last updated**: 2026-02-16
**Status**: Ready for implementation
**Phase**: 1 (Task 1.8, Critical priority)
**Arena path**: `src/issue_observatory/arenas/news_media/rss_feeds/`

---

## 1. Platform Overview

RSS (Really Simple Syndication) feeds provide structured, machine-readable access to news articles from Danish media outlets. Most major Danish news organizations maintain active RSS feeds. This arena provides the primary free mechanism for near-real-time Danish news monitoring, covering national, regional, and niche outlets.

**Role in Danish discourse**: RSS feeds from DR, TV2, BT, Politiken, Berlingske, Information, Ekstra Bladet, and regional outlets provide the backbone of Danish news monitoring. Combined, these feeds cover the full spectrum of Danish journalism -- public service (DR), commercial TV (TV2), tabloid (BT, Ekstra Bladet), broadsheet (Politiken, Berlingske, Information), financial (Borsen), and regional (Nordjyske, Fyens Stiftstidende, Jyllands-Posten). RSS is the fastest free method to detect when Danish media publishes new content.

**Access model**: Free, unauthenticated HTTP polling. No API keys. No rate limits (beyond standard web server behavior). Full article text is generally not available via RSS for paywalled outlets -- feeds provide title, summary/description, publication date, and URL.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | feedparser polling | $0 | Direct RSS feed polling. No authentication. No rate limits. |
| **Medium** | Inoreader API | $7.50/month (Pro tier) | 2,500 feed subscriptions, 10,000 API req/day, keyword monitoring. 50 articles per request limit. |
| **Premium** | N/A | -- | No premium tier needed. |

**Recommendation**: Start with Free tier (feedparser). Inoreader is useful only if feed management complexity grows beyond what a simple polling loop handles, or if keyword-based feed monitoring is needed.

---

## 3. API/Access Details

### Free Tier: feedparser

**Library**: `feedparser` (PyPI)
**Installation**: `pip install feedparser`

**Usage**: `feedparser.parse("https://www.dr.dk/nyheder/service/feeds/allenyheder")`

**No authentication required for any confirmed Danish RSS feed.**

**Curated Danish Feed List**:

#### DR (Danmarks Radio) -- 20+ feeds

| Feed | URL | Content |
|------|-----|---------|
| All news | `https://www.dr.dk/nyheder/service/feeds/allenyheder` | All DR news |
| Domestic | `https://www.dr.dk/nyheder/service/feeds/indland` | Danish domestic news |
| International | `https://www.dr.dk/nyheder/service/feeds/udland` | International news |
| Politics | `https://www.dr.dk/nyheder/service/feeds/politik` | Political news |
| Money | `https://www.dr.dk/nyheder/service/feeds/penge` | Business/economy |
| Sports | `https://www.dr.dk/nyheder/service/feeds/sporten` | Sports |
| Science | `https://www.dr.dk/nyheder/service/feeds/viden` | Science/knowledge |
| Culture | `https://www.dr.dk/nyheder/service/feeds/kultur` | Culture |
| Regional (x9) | `https://www.dr.dk/nyheder/service/feeds/{region}` | Regional feeds |

#### Other National Outlets

| Outlet | Feed URL | Status |
|--------|----------|--------|
| TV2 | `https://feeds.services.tv2.dk/api/feeds/nyheder/rss` | Verified active |
| BT | `https://www.bt.dk/bt/seneste/rss` | Verified active |
| Politiken | `http://politiken.dk/rss/senestenyt.rss` | Verified active |
| Information | `http://www.information.dk/feed` | Verified active |
| Berlingske | `https://www.berlingske.dk/content/rss` | Verified active |
| Ekstra Bladet | `https://ekstrabladet.dk/rssfeed/all` | Active (see feeds page at `/services/rss-feeds-fra-ekstra-bladet/4576561`) |
| Nordjyske | `https://nordjyske.dk/rss/nyheder` | Active |
| Fyens Stiftstidende | `https://fyens.dk/feed/danmark` | Active (pattern: `/feed/{category}`) |

#### Altinget Section Feeds (Added: IP2-009)

| Feed | URL | Status |
|------|-----|--------|
| Altinget Main | `https://www.altinget.dk/feed/rss.xml` | In config (existing) |
| Altinget Uddannelse | `https://www.altinget.dk/uddannelse/rss` | Unverified -- follows expected pattern |
| Altinget Klima | `https://www.altinget.dk/klima/rss` | Unverified -- follows expected pattern |

#### Education-Sector Feeds (Added: IP2-058)

These feeds support the "AI og uddannelse" (AI and education) issue mapping use case and broader education policy tracking in Denmark.

| Outlet | Feed URL | Status | Notes |
|--------|----------|--------|-------|
| Folkeskolen | `https://www.folkeskolen.dk/rss` | Unverified | Published by DLF (Danmarks Laererforening). Primary/lower-secondary education. |
| Gymnasieskolen | `https://gymnasieskolen.dk/feed` | Unverified | Published by GL (Gymnasieskolernes Laererforening). Upper-secondary education. |
| KU (Univ. of Copenhagen) | `https://nyheder.ku.dk/feed/` | Unverified | University news feed. |
| DTU | `https://www.dtu.dk/nyheder/rss` | Unverified | Technical University of Denmark news. |
| CBS | `https://www.cbs.dk/rss` | Unverified | Copenhagen Business School news. |
| DEA (think tank) | `https://dea.nu/feed` | Unverified, commented out in config | Education/research policy think tank. RSS availability uncertain. |

**Important**: All education-sector feed URLs above are unverified and based on common Danish website RSS patterns. They must be confirmed at implementation time via the RSS arena health check. If a URL returns an error, consult the outlet's website for the correct feed path.

#### Uncertain/Needs Verification

| Outlet | Feed URL | Status |
|--------|----------|--------|
| Jyllands-Posten | `https://jp.dk/rss/topnyheder.jsp` | Possibly discontinued; verify at implementation time |
| Borsen | Unknown | Needs investigation |
| Kristeligt Dagblad | Unknown | Needs investigation |

**Polling interval**: 5-60 minutes depending on outlet update frequency. DR and TV2 update frequently (every few minutes for breaking news). Smaller outlets may update hourly or less.

### Medium Tier: Inoreader API

**Base URL**: `https://www.inoreader.com/reader/api/0/`

**Authentication**: OAuth 2.0 or API key.

**Key endpoints**:
- `stream/contents/{feed_id}` -- Get articles from a feed
- `stream/ids/{feed_id}` -- Get article IDs only
- `subscription/quickadd?quickadd={feed_url}` -- Subscribe to a feed

**Limitations**: 50 articles per request. 10,000 API requests per day. 2,500 feed subscriptions max.

**Benefit over feedparser**: Inoreader handles feed parsing, deduplication, and caching server-side. It also supports keyword monitoring rules that can flag articles matching specific terms.

---

## 4. Danish Context

- **Language**: All curated feeds are Danish-language outlets. Content is predominantly in Danish. No language filter parameter needed -- the feed selection itself provides the Danish filter.
- **Paywall impact**: Many Danish outlets (Berlingske, Politiken, JP, Information, Borsen) are partially or fully paywalled. RSS feeds from these outlets provide title, summary, and URL, but not full article text. Full text extraction requires a separate web scraping step or a subscription-based approach, which is out of scope for this arena.
- **Regional coverage**: DR provides regional feeds covering all of Denmark. Nordjyske and Fyens Stiftstidende cover specific regions. Together with national outlets, this provides broad geographic coverage.
- **Wire content**: Ritzau wire stories distributed to Danish media appear in outlet RSS feeds (e.g., DR, TV2). This creates natural deduplication challenges -- the same story may appear in multiple feeds with slightly different framing.
- **Feed directories**: FeedSpot "Top 25 Denmark News RSS Feeds" and RSSKataloget.dk can help discover additional Danish feeds.

---

## 5. Data Fields

Mapping to the Universal Content Record schema:

| UCR Field | RSS Source | Notes |
|-----------|-----------|-------|
| `platform` | Feed-specific slug (e.g., `"dr"`, `"tv2"`, `"politiken"`) | Derive from feed URL |
| `arena` | `"news_media"` | Constant |
| `platform_id` | `entry.id` or `entry.link` | RSS `<guid>` or `<link>` element. Use link as fallback if guid is absent. |
| `content_type` | `"article"` | Constant |
| `text_content` | `entry.summary` or `entry.description` | Usually a brief summary, not full text. May contain HTML -- strip tags. |
| `title` | `entry.title` | Article headline |
| `url` | `entry.link` | URL to full article |
| `language` | `"da"` | Assumed Danish for curated feeds. Override if feed `xml:lang` differs. |
| `published_at` | `entry.published_parsed` | feedparser returns a time struct; convert to datetime. Some feeds use `updated` instead. |
| `collected_at` | Now | Standard |
| `author_platform_id` | `NULL` | RSS author info is inconsistent |
| `author_display_name` | `entry.author` (if present) | Often absent or set to outlet name |
| `views_count` | `NULL` | Not available via RSS |
| `likes_count` | `NULL` | Not available via RSS |
| `shares_count` | `NULL` | Not available via RSS |
| `comments_count` | `NULL` | Not available via RSS |
| `engagement_score` | `NULL` | Not available via RSS |
| `raw_metadata` | Full entry dict | Store: `tags`/`categories`, `media_content`, `enclosures`, `source` feed name, `updated` |
| `media_urls` | Extract from `media_content` or `enclosures` | Article images, if provided |
| `content_hash` | SHA-256 of normalized title | Title-based hash for cross-feed deduplication |

**Note on `platform` field**: Each outlet gets its own platform slug so content can be filtered by source. Derive from a configured feed-to-platform mapping, not by parsing URLs (which is fragile).

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Free | None | N/A |
| Medium | `{"api_key": "inoreader_api_key", "oauth_token": "..."}` | `"inoreader"` |

No credentials needed for the Free tier. All curated Danish RSS feeds are publicly accessible.

---

## 7. Rate Limits and Multi-Account Notes

| Tier | Rate Limit | Daily Cap | Notes |
|------|-----------|-----------|-------|
| Free (feedparser) | None formal | None | Be respectful: poll each feed at most once per 5 minutes. Respect `Cache-Control` and `ETag` headers. |
| Medium (Inoreader) | 10,000 req/day | 10,000 | 50 articles per request |

**Multi-account**: Not applicable. RSS feeds are unauthenticated. Inoreader allows only one account per subscription.

**Polling etiquette**: Even though there are no formal rate limits, rapid polling of the same feed is wasteful and may result in IP blocking by news outlets. Recommended intervals:
- High-frequency feeds (DR, TV2): 5-10 minutes
- Medium-frequency feeds (Berlingske, Politiken): 15-30 minutes
- Low-frequency feeds (regional, niche): 30-60 minutes

**Conditional GET**: Implement `If-Modified-Since` and `If-None-Match` (ETag) headers on feed requests. If the feed has not changed, the server returns 304 Not Modified with no body, saving bandwidth and processing.

---

## 8. Known Limitations

1. **No full article text**: Paywalled outlets provide only title and summary via RSS. Full text extraction would require web scraping or a subscription (e.g., Infomedia). The RSS arena collects metadata and summaries only.

2. **No engagement metrics**: RSS provides no views, likes, shares, or comments. These fields will be NULL for all RSS-collected content.

3. **Inconsistent feed formats**: Different outlets use different RSS/Atom standards. Some use RSS 2.0, others Atom 1.0. feedparser handles both transparently, but field names may vary. Test each feed individually.

4. **Feed discovery and maintenance**: Outlets may change feed URLs without notice. JP may have discontinued its RSS feed. Implement health monitoring to detect dead feeds. The feed list in `danish_defaults.py` must be maintained.

5. **Deduplication across feeds**: The same Ritzau wire story may appear in DR, TV2, BT, and other outlet feeds. Cross-feed deduplication via `content_hash` on normalized title is essential but imperfect (outlets may change headlines).

6. **Publication date reliability**: Some feeds provide `published` dates, others only `updated` dates. Some entries have no date at all. The normalizer must handle all cases and fall back to `collected_at` if no date is available.

7. **Summary quality varies**: DR feeds provide substantial summaries. Other outlets may provide only a sentence or even just the title. The `text_content` field will have inconsistent length and quality across outlets.

8. **Legal considerations**: RSS feeds are published for public consumption. No ToS restrictions on programmatic access. GDPR considerations are minimal -- article metadata is not personal data. Author names (journalists) are professional information. Standard `pseudonymized_author_id` is not needed for journalist bylines but should be applied for consistency.

9. **XML parsing errors**: Some feeds produce malformed XML occasionally. feedparser is tolerant of most errors, but implement try/except handling for each feed parse.

---

## 9. Collector Implementation Notes

### Architecture

- **Collection mode**: Primarily `collect_by_terms` -- match article titles and summaries against search terms from the query design. Also `collect_by_actors` if actors map to specific outlets (e.g., tracking DR's output).
- **Polling loop**: A Celery Beat periodic task that polls all configured feeds at their respective intervals.
- **Feed registry**: Maintain a configurable list of feed URLs with metadata (outlet name, platform slug, category, polling interval) in `danish_defaults.py` or a configuration table.

### Key Implementation Guidance

1. **Feed configuration structure**: Each feed entry should specify:
   ```python
   {
       "url": "https://www.dr.dk/nyheder/service/feeds/allenyheder",
       "platform": "dr",
       "name": "DR - All News",
       "category": "national",
       "poll_interval_minutes": 10,
       "language": "da"
   }
   ```

2. **Polling strategy**:
   - Use Celery Beat to schedule feed polling at configured intervals
   - Implement conditional GET (If-Modified-Since, ETag) to minimize bandwidth
   - Parse feed with `feedparser.parse(url)`
   - For each entry, check if `platform_id` already exists in the database
   - Only insert new entries (deduplication by `entry.id` or `entry.link`)

3. **Term matching**: After collecting new feed entries, match against active query design search terms:
   - Case-insensitive substring match on `title` and `summary`
   - Support phrase matching (quoted terms)
   - Mark matched terms in `search_terms_matched` array

4. **Feed health monitoring**:
   - Track last successful parse timestamp and HTTP status for each feed
   - Flag feeds that return errors for 3+ consecutive polls
   - Expose feed health in the admin health dashboard
   - Log feed format changes (e.g., new fields appearing, fields disappearing)

5. **Actor-based collection**: Map actors to outlets or journalist bylines:
   - If an actor is mapped to a platform (e.g., `platform="dr"`), collect all entries from that outlet's feeds
   - If an actor is mapped to a journalist name, filter entries by `entry.author` match

6. **Conditional GET implementation**:
   ```python
   # Store last ETag and Last-Modified per feed
   headers = {}
   if feed.last_etag:
       headers["If-None-Match"] = feed.last_etag
   if feed.last_modified:
       headers["If-Modified-Since"] = feed.last_modified
   response = requests.get(feed.url, headers=headers)
   if response.status_code == 304:
       return []  # No new content
   ```

7. **HTML stripping**: RSS `summary` and `description` fields often contain HTML. Strip tags and decode entities before storing in `text_content`. Use a library like `bleach` or `html.parser` for safe stripping.

8. **Health check**: Attempt to fetch and parse one feed (e.g., DR all news). Verify valid response with at least one entry.

9. **Credit cost**: 0 credits for all operations (free tier).

10. **Inoreader (Medium tier)**: If implemented, use the Inoreader API to manage feed subscriptions and retrieve articles. The main benefit is server-side keyword monitoring and deduplication. Configure in CredentialPool with `platform="inoreader"`.
