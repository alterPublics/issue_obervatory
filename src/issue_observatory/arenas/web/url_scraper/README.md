# URL Scraper Arena

**Arena path**: `src/issue_observatory/arenas/web/url_scraper/`
**Arena name**: `web` | **Platform name**: `url_scraper`
**Greenland roadmap ticket**: GR-10

## Overview

The URL Scraper arena fetches live web pages from a researcher-provided list
of URLs, extracts article text using `trafilatura`, and stores results as
Universal Content Records in the `web` arena.

Unlike API-based arenas that query external search indices, the URL Scraper
fetches pages directly from their origin servers.  It fills a critical gap for
sources that have no RSS feed and are not indexed by GDELT or Event Registry —
particularly niche government websites, institutional publications, and
Greenlandic media sites (naalakkersuisut.gl, knr.gl, sermitsiaq.ag).

## Tier Configuration

| Tier   | Max URLs/Run | Rate Limit         | JS Rendering  | Credential |
|--------|--------------|--------------------|---------------|------------|
| FREE   | 100          | 1 req/sec / domain | No            | None       |
| MEDIUM | 500          | 2 req/sec / domain | Playwright    | None       |

Both tiers are free in terms of external service costs.

## Setup

### FREE Tier (default)

No setup required.  The arena uses `httpx` for HTTP fetching (already a
project dependency) and `trafilatura` for text extraction.

Install `trafilatura` if not already present:

```bash
uv pip install trafilatura
```

### MEDIUM Tier (Playwright)

Install Playwright and download the Chromium browser binary:

```bash
uv pip install playwright>=1.48
playwright install chromium
```

The MEDIUM tier activates Playwright automatically for pages where the
`HttpFetcher` detects a JavaScript-only shell (body < 500 characters).
If Playwright is not installed when MEDIUM tier is requested, affected
URLs fall back to httpx-only behaviour (a warning is logged).

## Configuration in `arenas_config`

The URL list is stored in the query design's `arenas_config` JSONB field:

```json
{
  "url_scraper": {
    "custom_urls": [
      "https://naalakkersuisut.gl/da/Naalakkersuisut/Nyheder",
      "https://arctictoday.com/category/greenland/",
      "https://www.ft.dk/samling/20251/almdel/GRU/bilag.htm",
      "https://www.diis.dk/en/research/arctic"
    ],
    "tier": "free"
  }
}
```

The `custom_urls` list is the sole input to the collector.  There are no
system-default URLs.  Researchers provide all URLs through the query design
configuration UI.

## Collection Modes

### `collect_by_terms(extra_urls=custom_urls, terms=...)`

1. Fetches ALL URLs in `custom_urls`
2. Extracts text content from each page
3. Filters client-side: returns only records where any term appears in
   `text_content` or `title` (case-insensitive substring)
4. Supports boolean AND/OR groups via `term_groups` parameter

### `collect_by_actors(actor_ids=..., extra_urls=custom_urls)`

Actor IDs are base URLs from `ActorPlatformPresence.platform_username`
where `platform="url_scraper"` (e.g. `"https://naalakkersuisut.gl"`).

1. Filters `custom_urls` by domain prefix match against each actor base URL
2. If no `custom_urls` match, fetches the actor base URL directly
3. Returns all content without term filtering

## API Endpoints

When the router is mounted under `/arenas`:

| Method | Path                              | Description                          |
|--------|-----------------------------------|--------------------------------------|
| POST   | `/arenas/url-scraper/collect/terms`  | Fetch URLs, filter by terms          |
| POST   | `/arenas/url-scraper/collect/actors` | Fetch actor website URLs             |
| GET    | `/arenas/url-scraper/health`         | Verify fetch-and-extract pipeline    |

## Error Isolation

One URL failure (HTTP 4xx/5xx, timeout, extraction error, robots.txt block)
never stops the remaining URLs from being processed.  Failed URLs are logged
and recorded with `is_blocked=True` in `raw_metadata`.

## Robots.txt Compliance

The collector respects `robots.txt` disallow rules for the `IssueObservatory`
user agent.  Results are cached per origin for the duration of the collection
run.  If `robots.txt` cannot be fetched (network error, 404), the URL is
treated as allowed (fail-open).

## UCR Field Mapping

| UCR Field              | Source                                              |
|------------------------|-----------------------------------------------------|
| `platform`             | `"url_scraper"`                                     |
| `arena`                | `"web"`                                             |
| `platform_id`          | `sha256(final_url).hexdigest()`                     |
| `content_type`         | `"web_page"`                                        |
| `text_content`         | `trafilatura` extraction (tag-stripping fallback)   |
| `title`                | `trafilatura.extract_metadata().title`              |
| `url`                  | Final URL after redirect resolution                 |
| `language`             | `trafilatura.extract_metadata().language` or `None` |
| `published_at`         | trafilatura date / Last-Modified header / now()     |
| `author_platform_id`   | Domain name (e.g. `"sermitsiaq.ag"`)               |
| `author_display_name`  | Domain name (same)                                  |
| `content_hash`         | `sha256(text_content)` for deduplication            |

## Known Limitations

- **No JavaScript at FREE tier**: SPA pages return near-empty text.
  `needs_playwright: true` is recorded in `raw_metadata` for affected URLs.
- **Paywalls**: Only publicly visible content is extracted.
- **No incremental fetch**: Every run re-fetches all URLs.  Exact duplicates
  are caught by `content_hash`; near-duplicates create separate records.
- **Publication date fragility**: `trafilatura`'s date extraction uses
  heuristics and fails on many page types.  `collected_at` is the fallback.

## Celery Tasks

```python
from issue_observatory.arenas.web.url_scraper.tasks import (
    url_scraper_collect_terms,
    url_scraper_collect_actors,
    url_scraper_health_check,
)

# Dispatch term collection
url_scraper_collect_terms.delay(
    query_design_id="...",
    collection_run_id="...",
    terms=["Gronland", "selvbestemmelse"],
    tier="free",
    custom_urls=["https://naalakkersuisut.gl/da/Naalakkersuisut/Nyheder"],
)
```
