# SB-09 & SB-10: Source Discovery Assistance Implementation

**Implemented:** 2026-02-20
**Priority:** P2 (Socialt Bedrageri recommendations)
**Status:** Backend complete, frontend integration pending

## Overview

Two new endpoints enable researchers to discover and add data sources to their query designs:

1. **SB-09: RSS Feed Autodiscovery** — `POST /query-designs/{id}/discover-feeds`
2. **SB-10: Reddit Subreddit Suggestion** — `GET /query-designs/{id}/suggest-subreddits`

Both endpoints are now live and ready for frontend integration.

---

## SB-09: RSS Feed Autodiscovery

### Endpoint

```
POST /query-designs/{design_id}/discover-feeds
Content-Type: application/json

{
  "url": "https://www.dr.dk"
}
```

### Response

```json
[
  {
    "url": "https://www.dr.dk/nyheder/service/feeds/allenyheder",
    "title": "DR Nyheder - Seneste nyt",
    "feed_type": "rss"
  },
  {
    "url": "https://www.dr.dk/nyheder/service/feeds/politik",
    "title": "DR Politik",
    "feed_type": "rss"
  }
]
```

### Implementation Details

**Files:**
- `src/issue_observatory/arenas/rss_feeds/feed_discovery.py` (new)
- `src/issue_observatory/api/routes/query_designs.py` (endpoint added)

**Discovery Algorithm:**
1. Fetch HTML from the provided URL
2. Parse `<link rel="alternate">` tags with RSS/Atom content types
3. If no tags found, probe common feed paths:
   - `/rss`, `/rss.xml`
   - `/feed`, `/feed.xml`
   - `/atom.xml`
   - `/feeds/posts/default` (Blogger)
   - `/index.xml` (Hugo)
4. Verify discovered URLs with HEAD requests
5. Deduplicate and return with titles

**Error Handling:**
- 400 Bad Request: Empty URL
- 403 Forbidden: Ownership guard failure
- 404 Not Found: Query design does not exist
- 500 Internal Server Error: Network timeout, connection error, invalid HTML

**Security:**
- Follows redirects with max 5 hops
- 15-second timeout per request
- User-Agent identifies Issue Observatory

**Dependencies:**
- `httpx` (async HTTP)
- `beautifulsoup4` (HTML parsing) — **newly added to pyproject.toml**

---

## SB-10: Reddit Subreddit Suggestion

### Endpoint

```
GET /query-designs/{design_id}/suggest-subreddits?query=folkeskole&limit=20
```

**Query Parameters:**
- `query` (optional): Explicit search query. When omitted, uses the first 3 active search terms from the query design.
- `limit` (optional): Max results (1-100, default 20)

### Response

```json
[
  {
    "name": "dkpolitik",
    "display_name": "dkpolitik",
    "display_name_prefixed": "r/dkpolitik",
    "subscribers": 8542,
    "description": "For diskussion af dansk politik og valg",
    "active_user_count": 42
  },
  {
    "name": "Denmark",
    "display_name": "Denmark",
    "display_name_prefixed": "r/Denmark",
    "subscribers": 347891,
    "description": "Danish news and discussion",
    "active_user_count": 1203
  }
]
```

### Implementation Details

**Files:**
- `src/issue_observatory/arenas/reddit/subreddit_suggestion.py` (new)
- `src/issue_observatory/api/routes/query_designs.py` (endpoint added)

**Search Strategy:**
1. Build search query from query design's active search terms (if `query` param not provided)
2. Use Reddit's `/subreddits/search` API via asyncpraw
3. Return top N results with subscriber counts and descriptions

**Error Handling:**
- 403 Forbidden: Ownership guard failure
- 404 Not Found: Query design does not exist
- 422 Unprocessable Entity: Invalid limit (must be 1-100)
- 500 Internal Server Error: Reddit API unavailable, rate limited, or auth failure

**Credentials:**
- Uses RedditCollector's credential acquisition logic
- Falls back to `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` env vars when no credential pool is configured

**Rate Limiting:**
- Reddit's native 100 req/min limit applies
- This is a FREE-tier API call (no paid access required)

**Dependencies:**
- `asyncpraw` (already in project)

---

## Integration with Existing Arena Config

Both endpoints return data ready for one-click addition to `arenas_config`:

### Adding Discovered RSS Feeds

```
PATCH /query-designs/{design_id}/arena-config/rss
Content-Type: application/json

{
  "custom_feeds": [
    "https://www.dr.dk/nyheder/service/feeds/allenyheder",
    "https://www.tv2.dk/feeds/all"
  ]
}
```

### Adding Suggested Subreddits

```
PATCH /query-designs/{design_id}/arena-config/reddit
Content-Type: application/json

{
  "custom_subreddits": ["dkpolitik", "folkeskole"]
}
```

The existing `PATCH /query-designs/{id}/arena-config/{arena_name}` endpoint (GR-01, GR-03) handles persistence.

---

## Frontend Integration Notes (for Frontend Engineer)

### Query Design Editor Arena Config Panel

Add two new discovery buttons in the arena configuration UI:

1. **RSS Feeds Arena Section**
   - Button: "Discover Feeds from URL"
   - Opens modal with URL input field
   - Calls `POST /query-designs/{id}/discover-feeds` with entered URL
   - Displays discovered feeds as a checklist
   - On confirmation, merges selected feed URLs into `custom_feeds` array
   - Submits via `PATCH /query-designs/{id}/arena-config/rss`

2. **Reddit Arena Section**
   - Button: "Suggest Subreddits"
   - Calls `GET /query-designs/{id}/suggest-subreddits` (no modal needed; uses query design's terms automatically)
   - Displays suggested subreddits in a modal with subscriber counts and descriptions
   - User checks relevant subreddits
   - On confirmation, merges selected subreddit names into `custom_subreddits` array
   - Submits via `PATCH /query-designs/{id}/arena-config/reddit`

### Example Frontend Workflow (RSS)

1. User navigates to query design editor → Arena Configuration tab
2. User scrolls to RSS Feeds section
3. User clicks "Discover Feeds from URL" button
4. Modal opens with input: "Enter website URL"
5. User types: `https://www.dr.dk`
6. Frontend calls: `POST /query-designs/{design_id}/discover-feeds {"url": "https://www.dr.dk"}`
7. Backend returns list of discovered feeds
8. Frontend displays checklist of feed URLs with titles
9. User selects desired feeds
10. On "Add Selected", frontend submits: `PATCH /query-designs/{design_id}/arena-config/rss {"custom_feeds": [...]}`
11. Success toast: "3 RSS feeds added"

### Example Frontend Workflow (Reddit)

1. User navigates to query design editor → Arena Configuration tab
2. User scrolls to Reddit section
3. User clicks "Suggest Subreddits" button
4. Frontend calls: `GET /query-designs/{design_id}/suggest-subreddits` (no query param)
5. Backend builds query from active search terms automatically
6. Frontend displays modal with subreddit list (name, subscribers, description)
7. User checks relevant subreddits
8. On "Add Selected", frontend submits: `PATCH /query-designs/{design_id}/arena-config/reddit {"custom_subreddits": [...]}`
9. Success toast: "2 subreddits added"

---

## Testing Notes (for QA Engineer)

### Unit Tests Needed

1. `tests/arenas/test_rss_feed_discovery.py`:
   - Test `discover_feeds()` with mocked HTML responses (respx)
   - Test `<link>` tag parsing with various feed types
   - Test common path probing fallback
   - Test error handling (timeout, 404, malformed HTML)
   - Test URL deduplication

2. `tests/arenas/test_reddit_subreddit_suggestion.py`:
   - Test `suggest_subreddits()` with mocked asyncpraw responses
   - Test query building from search terms
   - Test rate limit handling
   - Test credential fallback to env vars

3. `tests/api/test_query_designs_routes.py` (add new tests):
   - Test `POST /query-designs/{id}/discover-feeds` endpoint
   - Test `GET /query-designs/{id}/suggest-subreddits` endpoint
   - Test ownership guards
   - Test error responses (empty URL, invalid limit, etc.)

### Manual Testing

1. Start development server
2. Create a query design
3. Call `POST /query-designs/{id}/discover-feeds` with `{"url": "https://www.dr.dk"}`
4. Verify response contains expected DR feeds
5. Call `GET /query-designs/{id}/suggest-subreddits?query=folkeskole`
6. Verify response contains relevant Danish subreddits

---

## Performance Characteristics

### RSS Feed Discovery
- **Latency:** 1-5 seconds per website (depends on page load time and number of probed paths)
- **Concurrency:** Single synchronous request per discovery call (no parallel probing)
- **Caching:** None (each discovery is fresh)
- **Scalability:** No concerns; this is a researcher-initiated action, not automated

### Reddit Subreddit Suggestion
- **Latency:** 500ms-2s (Reddit API response time)
- **Rate Limiting:** Subject to Reddit's 100 req/min limit (shared with collection runs)
- **Concurrency:** Single request per suggestion call
- **Scalability:** No concerns; this is a researcher-initiated action

---

## Future Enhancements

1. **Feed Validation**: Fetch and parse discovered feeds to verify they contain recent entries
2. **Feed Preview**: Show sample headlines from discovered feeds before adding
3. **Subreddit Activity Scores**: Rank subreddits by recent post/comment volume
4. **Bulk Discovery**: Accept multiple URLs for batch feed discovery
5. **Caching**: Cache discovered feeds per domain for 24 hours to reduce repeated fetches
6. **Telegram Channel Discovery**: Similar pattern for suggesting Telegram channels (requires Telegram API integration)

---

## Related Files

**Implementation:**
- `src/issue_observatory/arenas/rss_feeds/feed_discovery.py`
- `src/issue_observatory/arenas/reddit/subreddit_suggestion.py`
- `src/issue_observatory/api/routes/query_designs.py` (lines 1797-2017)
- `pyproject.toml` (beautifulsoup4 dependency added)

**Documentation:**
- `docs/decisions/ADR-012-source-discovery-assistance.md`
- `docs/research_reports/greenland_codebase_recommendations.md` (SB-09, SB-10)

**Tests (to be written):**
- `tests/arenas/test_rss_feed_discovery.py` (new)
- `tests/arenas/test_reddit_subreddit_suggestion.py` (new)
- `tests/api/test_query_designs_routes.py` (add new test cases)
