# ADR-012: Source Discovery Assistance (SB-09, SB-10)

**Date:** 2026-02-20
**Status:** Implemented
**Context:** Socialt Bedrageri recommendations (P2)

## Context

Researchers need streamlined workflows for discovering and adding new data sources to their query designs. Manual URL discovery and validation is time-consuming and error-prone.

Two key discovery patterns emerged from the Socialt Bedrageri use case:
1. **RSS feed autodiscovery**: Given a Danish news outlet or organization website, automatically find available RSS/Atom feeds.
2. **Subreddit suggestion**: Given a research topic, discover relevant Reddit communities (subreddits) to include in the collection scope.

## Decision

Implement two source discovery endpoints in the query design routes:

### SB-09: RSS Feed Autodiscovery

**Endpoint:** `POST /query-designs/{design_id}/discover-feeds`

**Implementation:**
- New module: `src/issue_observatory/arenas/rss_feeds/feed_discovery.py`
- Dependencies: `httpx` (async HTTP), `beautifulsoup4` (HTML parsing)
- Discovery algorithm:
  1. Fetch the website HTML
  2. Parse `<link rel="alternate" type="application/rss+xml">` and `<link rel="alternate" type="application/atom+xml">` tags
  3. If no `<link>` tags found, probe common feed path patterns: `/rss`, `/feed`, `/atom.xml`, `/feeds/posts/default`, `/index.xml`, `/rss.xml`
  4. Verify discovered URLs with HEAD requests to confirm feed content types
  5. Return list of feed URLs with titles and types

**Usage:**
```json
POST /query-designs/{design_id}/discover-feeds
{
  "url": "https://www.dr.dk"
}

Response:
[
  {
    "url": "https://www.dr.dk/nyheder/service/feeds/allenyheder",
    "title": "DR Nyheder - Seneste nyt",
    "feed_type": "rss"
  }
]
```

Researchers can then add discovered feed URLs to `arenas_config["rss"]["custom_feeds"]` via the existing `PATCH /query-designs/{id}/arena-config/rss` endpoint.

### SB-10: Reddit Subreddit Suggestion

**Endpoint:** `GET /query-designs/{design_id}/suggest-subreddits?query=...&limit=20`

**Implementation:**
- New module: `src/issue_observatory/arenas/reddit/subreddit_suggestion.py`
- Uses Reddit's native subreddit search API: `GET /subreddits/search`
- FREE-tier asyncpraw call (no paid API required)
- When `query` parameter is omitted, the endpoint uses the query design's active search terms as the search query

**Usage:**
```json
GET /query-designs/{design_id}/suggest-subreddits?query=folkeskole

Response:
[
  {
    "name": "dkpolitik",
    "display_name": "dkpolitik",
    "display_name_prefixed": "r/dkpolitik",
    "subscribers": 8542,
    "description": "For diskussion af dansk politik og valg",
    "active_user_count": 42
  }
]
```

Researchers can then add suggested subreddit names to `arenas_config["reddit"]["custom_subreddits"]` via `PATCH /query-designs/{id}/arena-config/reddit`.

## Consequences

### Positive
- Reduced manual URL discovery time — researchers can autodiscover feeds from Danish outlet home pages
- Improved discoverability of relevant Reddit communities beyond the default Danish subreddit set
- Consistent with existing arena configuration pattern (GR-01, GR-03)
- No breaking changes to existing APIs

### Negative
- New dependency: `beautifulsoup4` added to core dependencies (lightweight, widely used)
- Feed autodiscovery may fail on JavaScript-rendered sites (acceptable trade-off; most RSS feeds are statically linked in HTML)

### Integration Points
- Both endpoints return JSON lists ready for one-click addition to `arenas_config`
- Frontend (when implemented) will call these endpoints from the query design editor's arena configuration panel
- Error handling follows established arena collector patterns: timeouts, HTTP errors, and missing credentials raise appropriate `ArenaCollectionError` or `HTTPException`

## Implementation Notes

### Type Hints
All functions have strict type hints per coding standards.

### Error Handling
- RSS feed discovery: Handles timeouts, HTTP errors, invalid HTML gracefully
- Reddit subreddit suggestion: Handles rate limiting, auth failures, and missing credentials

### Async/Await
Both implementations are fully async using `httpx.AsyncClient` and `asyncpraw`.

### Logging
Structured logging via `structlog` for all discovery operations (success count, query, design_id).

### Testing
Unit tests pending (to be added by QA Engineer per standard arena test pattern).

## Related Documents
- `/docs/research_reports/greenland_codebase_recommendations.md` (SB-09, SB-10)
- `/docs/arenas/rss_feeds.md` (arena brief)
- `/docs/arenas/reddit.md` (arena brief)
- `CLAUDE.md` (GR-01, GR-03 researcher-configurable sources)

## Future Extensions
- **YF-02**: Frontend UI for source discovery (to be implemented by Frontend Engineer)
- **Feed validation**: Fetch and parse discovered feeds to verify they contain recent entries before suggesting
- **Subreddit quality filters**: Rank suggestions by activity/relevance using `active_user_count` and recent post volume
