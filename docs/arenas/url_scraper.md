# Arena Research Brief: URL Scraper

**Created**: 2026-02-19
**Last updated**: 2026-02-19
**Status**: Ready for implementation
**Phase**: Greenland Roadmap (GR-10, High priority)
**Arena path**: `src/issue_observatory/arenas/web/url_scraper/`

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-19 | Initial arena brief. Created as prerequisite for GR-10 implementation. |

---

## 1. Platform Overview

The URL Scraper arena is a self-hosted web content extraction service. Unlike other web arenas (Common Crawl, Wayback Machine) that query external archives for metadata, the URL Scraper fetches **live web pages** from a researcher-provided list of URLs, extracts the main article text, and normalizes the result into Universal Content Records. There is no external API dependency -- the arena uses the existing `src/issue_observatory/scraper/` module for HTTP fetching and content extraction.

**Role in Danish discourse**: This arena fills a critical gap identified in the Greenland codebase evaluation (Section 7.2): none of the existing web arenas download and parse the actual HTML content of discovered pages. Researchers studying Danish public discourse frequently encounter niche websites, institutional pages, think tank publications, and government documents that have no RSS feed and are not indexed by GDELT or Event Registry. The URL Scraper enables direct content extraction from these sources.

**Example sources for Greenland research**:
- Greenlandic government (naalakkersuisut.gl) -- policy statements, press releases
- Arctic Today (arctictoday.com) -- English-language Arctic news
- Danish parliamentary debates (ft.dk/samling) -- committee hearings, debate transcripts
- Danish Institute for International Studies (diis.dk) -- policy analysis, working papers
- Sermitsiaq.AG -- Greenlandic news outlet (if no RSS feed available)
- KNR.gl -- Greenlandic Broadcasting Corporation

**Example sources for other research scenarios**: The arena is not Greenland-specific. Any researcher can provide URLs relevant to their topic -- education policy publications, climate research portals, niche political blogs, municipal government pages, etc.

**Access model**: No external API. No authentication. No subscription cost. Rate-limited by the application itself (per-domain politeness). Respects `robots.txt`.

---

## 2. Tier Configuration

| Tier | Service | Cost | Max URLs/Run | Rate Limit | JS Rendering |
|------|---------|------|-------------|-----------|--------------|
| **Free** | httpx (async HTTP) | $0 | 100 | 1 req/sec per domain | No |
| **Medium** | httpx + Playwright fallback | $0 | 500 | 2 req/sec per domain | Yes (for JS-heavy pages) |
| **Premium** | N/A | -- | -- | -- | -- |

**Cost notes**: Both tiers are free in terms of external service costs. The only cost is compute resources (CPU/memory for Playwright browser instances at MEDIUM tier). No API keys, no subscriptions, no per-request charges.

**Tier selection guidance**: Start with FREE. Escalate to MEDIUM only when specific URLs return JS-only page shells (the existing `HttpFetcher` detects this automatically via `FetchResult.needs_playwright`). Most news sites, government pages, and institutional publications render content server-side and work with FREE tier.

---

## 3. API/Access Details

### No External API

This arena does not call any third-party API. It fetches pages directly from their origin servers using the existing scraper module.

### Existing Module Reuse

The collector MUST use the existing `src/issue_observatory/scraper/` module rather than re-implementing HTTP fetching or content extraction. The relevant components are:

**`HttpFetcher`** (`src/issue_observatory/scraper/http_fetcher.py`):
- `fetch_url(url, *, client, timeout, respect_robots, robots_cache) -> FetchResult`
- Async function using `httpx.AsyncClient`
- Built-in `robots.txt` compliance checking with domain-level caching
- Binary content-type detection (skips PDFs, images, video, etc.)
- JS-shell detection via body length threshold (`JS_SHELL_BODY_THRESHOLD = 500` characters)
- Returns `FetchResult` dataclass with `html`, `status_code`, `final_url`, `error`, `needs_playwright`
- Custom user agent: `IssueObservatory/1.0` with contact URL

**`ContentExtractor`** (`src/issue_observatory/scraper/content_extractor.py`):
- `extract_from_html(html, url) -> ExtractedContent`
- Primary extraction: `trafilatura` with `include_tables=True`, `no_fallback=False`
- Fallback extraction: stdlib `HTMLParser` tag stripping
- Returns `ExtractedContent` dataclass with `text`, `title`, `language`
- Metadata extraction via `trafilatura.extract_metadata()` for title and language
- Content truncation at `MAX_CONTENT_BYTES = 900 KB`
- NUL byte removal for PostgreSQL compatibility

**`PlaywrightFetcher`** (`src/issue_observatory/scraper/playwright_fetcher.py`):
- `fetch_url_playwright(url, *, timeout) -> FetchResult`
- Optional dependency -- only imported when `use_playwright_fallback` is enabled
- Launches headless Chromium, waits for `networkidle`
- Used at MEDIUM tier as fallback for pages where `FetchResult.needs_playwright == True`

**`config.py`** (`src/issue_observatory/scraper/config.py`):
- `DEFAULT_DELAY_MIN = 2.0` seconds, `DEFAULT_DELAY_MAX = 5.0` seconds
- `DEFAULT_TIMEOUT = 30` seconds
- `USER_AGENT = "IssueObservatory/1.0 ..."`
- `ROBOTS_USER_AGENT = "IssueObservatory"`, `ROBOTS_USER_AGENT_FALLBACK = "*"`
- `BINARY_CONTENT_TYPES` -- frozenset of skippable MIME prefixes
- `JS_SHELL_BODY_THRESHOLD = 500` characters

---

## 4. Danish Context

- **Language**: The URL Scraper is language-agnostic. It does not filter by language at fetch time. Language detection is performed post-extraction by `trafilatura.extract_metadata()` (which returns an ISO 639-1 language code) and can be further enriched by the `DanishLanguageDetector` enrichment pipeline.
- **Danish/Greenlandic government sites**: Danish government sites (retsinformation.dk, ft.dk, stm.dk) and Greenlandic government sites (naalakkersuisut.gl, ina.gl) generally render server-side HTML and do not require Playwright. They are expected to work at FREE tier.
- **Paywall considerations**: The URL Scraper cannot bypass paywalls. If a researcher provides a URL to a paywalled article (e.g., on Berlingske or Politiken), the scraper will extract only the visible preview/teaser text, not the full article. This is consistent with the RSS arena's behavior and the application's policy of not circumventing access controls.
- **Character encoding**: Danish pages using ae, oe, aa characters are handled correctly by `httpx`'s automatic encoding detection and `trafilatura`'s internal encoding handling. Kalaallisut content on `.gl` domains should also decode correctly as UTF-8.
- **`robots.txt` on Danish sites**: Most Danish news sites allow crawling of article pages (their business model depends on search engine indexing). Government sites (`.dk`, `.gl`) generally have permissive `robots.txt` policies. The scraper's fail-open behavior (allow if `robots.txt` fetch fails) means that sites without a `robots.txt` are scraped normally.
- **Wire content**: If the researcher provides URLs to the same Ritzau wire story as published on multiple outlets, the existing deduplication infrastructure (SHA-256 content hash, SimHash near-duplicate detection) will identify these as duplicates during normalization.

---

## 5. Data Fields

Mapping to the Universal Content Record schema:

| UCR Field | URL Scraper Source | Notes |
|-----------|-------------------|-------|
| `platform` | `"url_scraper"` | Constant for all records from this arena |
| `arena` | `"web"` | Shared arena category with Common Crawl and Wayback Machine |
| `platform_id` | SHA-256 of the URL string | Deterministic; same URL always produces the same ID. Computed via `hashlib.sha256(url.encode()).hexdigest()` |
| `content_type` | `"web_page"` | Same content type as Common Crawl |
| `text_content` | `ExtractedContent.text` | Article text from `trafilatura` or tag-stripping fallback. May be `None` if extraction fails. Capped at 900 KB. |
| `title` | `ExtractedContent.title` | Page title from `trafilatura.extract_metadata()`. Falls back to HTML `<title>` tag. May be `None`. |
| `url` | Input URL (or `FetchResult.final_url` after redirects) | Store the final URL after redirect resolution to avoid duplicate entries for redirected URLs |
| `language` | `ExtractedContent.language` | ISO 639-1 code from `trafilatura` metadata extraction. May be `None` -- enrichment pipeline provides fallback detection. |
| `published_at` | Extracted from page metadata, else collection timestamp | Priority order: (1) `trafilatura.extract_metadata().date` (parses `<meta>` tags, JSON-LD, Open Graph, visible dates), (2) HTTP `Last-Modified` header, (3) `collected_at` as final fallback. See implementation notes. |
| `collected_at` | `datetime.utcnow()` | Standard |
| `author_platform_id` | Domain name extracted from URL | e.g., `"sermitsiaq.ag"`, `"ft.dk"`, `"diis.dk"`. Use `urllib.parse.urlparse(url).netloc` with `www.` prefix stripped. |
| `author_display_name` | Domain name (same as `author_platform_id`) | The "author" for a scraped web page is the publishing domain |
| `views_count` | `NULL` | Not available from web scraping |
| `likes_count` | `NULL` | Not available from web scraping |
| `shares_count` | `NULL` | Not available from web scraping |
| `comments_count` | `NULL` | Not available from web scraping |
| `engagement_score` | `NULL` | Not available from web scraping |
| `raw_metadata` | Dict with fetch and extraction metadata | See raw_metadata specification below |
| `media_urls` | `[]` | Could be extracted from HTML in future; not in initial implementation |
| `content_hash` | SHA-256 of normalized `text_content` | Standard content hash for cross-arena deduplication via `Normalizer.compute_content_hash()` |

### `raw_metadata` Specification

The `raw_metadata` JSONB column should store:

```json
{
  "source_url": "https://naalakkersuisut.gl/da/Naalakkersuisut/Nyheder/2026/02/1802_pressemeddelelse",
  "final_url": "https://naalakkersuisut.gl/da/Naalakkersuisut/Nyheder/2026/02/1802_pressemeddelelse",
  "http_status_code": 200,
  "content_type_header": "text/html; charset=utf-8",
  "last_modified_header": "2026-02-18T14:30:00Z",
  "extraction_method": "trafilatura",
  "needs_playwright": false,
  "is_blocked": false,
  "robots_txt_allowed": true,
  "fetch_error": null,
  "fetch_duration_ms": 1234,
  "content_length_bytes": 8542
}
```

For failed fetches that are still logged (per error isolation requirement):

```json
{
  "source_url": "https://example.dk/restricted-page",
  "final_url": "https://example.dk/restricted-page",
  "http_status_code": 403,
  "is_blocked": true,
  "robots_txt_allowed": true,
  "fetch_error": "HTTP 403",
  "extraction_method": null,
  "needs_playwright": false
}
```

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Free | None | N/A |
| Medium | None | N/A |

No credentials are required at any tier. The URL Scraper uses unauthenticated HTTP requests to public web pages.

---

## 7. Rate Limits and Multi-Account Notes

| Tier | Rate Limit | Max URLs/Run | Concurrency | Notes |
|------|-----------|-------------|-------------|-------|
| Free | 1 req/sec per domain | 100 | 1 concurrent request per domain | Global concurrency via asyncio.Semaphore |
| Medium | 2 req/sec per domain | 500 | 1 concurrent request per domain | Same domain politeness; higher throughput via parallelism across domains |

**Per-domain rate limiting**: The rate limit is per-domain, not global. When scraping URLs from 10 different domains, the collector can issue up to 10 (FREE) or 20 (MEDIUM) requests per second total, while respecting the per-domain cap. This prevents overloading any single web server while maintaining overall throughput.

**Implementation**: Use a dict of per-domain `asyncio.Semaphore` instances (one per unique domain in the URL list). Each semaphore is acquired before fetching a URL from that domain, and an `asyncio.sleep(1.0)` (FREE) or `asyncio.sleep(0.5)` (MEDIUM) is inserted between requests to the same domain.

**Multi-account**: Not applicable. No accounts or credentials are used.

**robots.txt caching**: Cache `robots.txt` responses in memory, keyed by origin (`scheme://netloc`). The existing `_is_allowed_by_robots()` in `http_fetcher.py` already implements a `robots_cache` dict parameter. For the arena collector, create the cache once per collection run and pass it to all `fetch_url()` calls. For long-running collection runs, consider refreshing the cache if a run exceeds 24 hours (edge case, unlikely given the 100/500 URL caps).

---

## 8. Known Limitations

1. **No JavaScript rendering at FREE tier**: Pages that require JavaScript execution to render their content (single-page applications, React/Angular/Vue sites) will return near-empty text at FREE tier. The `HttpFetcher` detects this (body < 500 characters after stripping) and sets `needs_playwright=True`, but FREE tier does not act on this flag. Affected URLs are logged with `needs_playwright: true` in `raw_metadata` so the researcher can identify them and upgrade to MEDIUM tier if needed.

2. **Cannot scrape authenticated/paywalled pages**: The scraper sends unauthenticated HTTP requests. Pages requiring login, subscription, or cookie-based access will return only the publicly visible portion (login page, paywall teaser, etc.). This is by design -- the application does not store or transmit user credentials for third-party sites.

3. **`robots.txt` compliance may block some content**: The scraper respects `robots.txt` Disallow rules for the `IssueObservatory` user agent and the `*` wildcard. Some government or news sites may have restrictive `robots.txt` policies that block scraping. Blocked URLs are logged with `robots_txt_allowed: false` in `raw_metadata` and `is_blocked: true`. The researcher is informed but the scraper does not bypass the restriction.

4. **Publication date extraction is fragile**: Determining when a web page was originally published is inherently unreliable. `trafilatura.extract_metadata().date` uses heuristics (Open Graph `article:published_time`, `<meta name="date">`, JSON-LD `datePublished`, visible date patterns in text). These heuristics fail on many page types -- government documents, think tank reports, blog posts without structured metadata. The HTTP `Last-Modified` header is a weak signal (it reflects the last time the server modified the response, not necessarily the content publication date). When no date can be extracted, `collected_at` is used as a fallback, which means the content record's `published_at` reflects when it was scraped, not when it was written. Researchers must be aware of this limitation when performing temporal analysis.

5. **No incremental/change detection**: The URL Scraper fetches the current version of each page on every run. It does not track whether page content has changed since the last scrape. If the same URL list is run twice, the second run will produce new content records (different `collected_at`, potentially different `text_content` if the page changed). Deduplication by `content_hash` will prevent exact duplicates from being stored, but near-duplicates (minor page changes) will create separate records. For change tracking, use the Wayback Machine arena instead.

6. **Content quality varies by page structure**: `trafilatura` is optimized for news articles and blog posts. Its extraction quality degrades on:
   - PDF-heavy sites (PDFs are skipped by the binary content-type check)
   - Heavily tabular content (partially supported with `include_tables=True`)
   - Image-heavy pages with minimal text
   - Forum/discussion pages (may extract navigation and sidebar text)
   - Pages with very short content (may fall through to the tag-stripping fallback, which is less precise)

7. **No media extraction**: The initial implementation does not extract images, videos, or other media from scraped pages. `media_urls` is set to `[]`. Media extraction could be added in a future iteration if needed.

8. **URL list is static per run**: The URL list is provided at the start of a collection run and cannot be modified while the run is in progress. For continuous monitoring of web pages, the researcher must create recurring collection runs with the same URL list (or use the RSS arena if feeds are available).

9. **Legal considerations**: Scraping publicly accessible web pages for academic research is well-established practice and is protected under GDPR Article 89 research exemptions and the Danish Databeskyttelsesloven section 10. The scraper's `robots.txt` compliance, research-identifying user agent string, and respectful rate limiting demonstrate good-faith adherence to web scraping norms. However:
   - Some sites' Terms of Service may prohibit automated access. The application's research purpose provides a defensible position, but this is a gray area.
   - Scraped content may contain personal data (author names, quoted individuals, contact information). Standard GDPR processing applies -- personal data in scraped content should be treated with the same pseudonymization and minimization practices applied to all other arenas.
   - The DSA does not specifically address web scraping, but Article 40 researcher access provisions apply only to VLOPs, not to arbitrary websites.

---

## 9. Search Capabilities

### `collect_by_terms()` Behavior

The URL Scraper's `collect_by_terms()` operates differently from API-based arenas. It does not perform server-side search queries. Instead:

1. Fetch ALL URLs in the configured `custom_urls` list
2. Extract text content from each successfully fetched page
3. Apply client-side term matching against the extracted `text_content` and `title`
4. Return only records where at least one search term matches

**Term matching implementation**: Case-insensitive substring matching against `text_content` and `title`. Support phrase matching (quoted terms). Populate `search_terms_matched` array in the returned records. This is the same client-side matching pattern used by the Telegram collector (`collector.py` lines 134-172).

**Boolean query support**: When `term_groups` is provided, apply boolean AND/OR logic client-side. Each inner list (AND group) requires all terms to appear in the content. Groups are ORed. Use `build_boolean_query_groups()` from `arenas/query_builder.py`.

### `collect_by_actors()` Behavior

For actor-based collection, the collector resolves actor platform presences where `platform == "url_scraper"`. The `platform_username` field on `ActorPlatformPresence` should contain the base URL of the actor's website (e.g., `"https://naalakkersuisut.gl"`).

The collector:
1. Retrieves all `ActorPlatformPresence` records for the given `actor_ids` where `platform == "url_scraper"`
2. For each presence, uses the `platform_username` URL as a prefix filter against the `custom_urls` list
3. Fetches and extracts content from matching URLs
4. Returns all records (no term filtering -- actor-based collection returns all content from that actor's domain)

If no `custom_urls` match the actor's domain, the collector should fetch the actor's `platform_username` URL directly (the base URL of the website). This enables a fallback where the researcher has added actors with website presences but has not explicitly listed individual page URLs.

---

## 10. Configuration in `arenas_config`

The URL list is stored in the query design's `arenas_config` JSONB field, following the same pattern as RSS custom feeds (`arenas_config["rss"]["custom_feeds"]`) and Telegram custom channels:

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

The `custom_urls` list is the sole input to the collector. There are no system-default URLs (unlike RSS feeds, which have a curated default feed list). The researcher provides all URLs through the query design's arena configuration UI.

**URL validation at configuration time**: The arena configuration UI should validate that each entry is a syntactically valid URL (scheme + host at minimum). It should NOT validate that the URL is reachable -- that check happens at collection time, with failures logged per the error isolation requirement.

---

## 11. Collector Implementation Notes

### Architecture

- **Arena name**: `"url_scraper"`
- **Platform name**: `"url_scraper"`
- **Arena category**: `web` (same parent as `common_crawl` and `wayback`)
- **Supported tiers**: `[Tier.FREE, Tier.MEDIUM]`
- **Collection mode**: Batch (on-demand per collection run). Not suitable for Celery Beat periodic tasks because the URL list is static and pages do not update on a predictable schedule.
- **Directory**: `src/issue_observatory/arenas/web/url_scraper/`

### Key Implementation Guidance

1. **Reuse existing scraper module**: The collector MUST use `fetch_url()` from `http_fetcher.py` and `extract_from_html()` from `content_extractor.py`. Do not re-implement HTTP fetching, `robots.txt` checking, JS-shell detection, or content extraction. The scraper module already handles all edge cases (timeouts, redirects, binary content-type detection, encoding, content truncation).

2. **Per-URL error isolation**: If one URL fails (network error, timeout, HTTP 4xx/5xx, `robots.txt` block, extraction failure), the collector MUST continue processing remaining URLs. Failed URLs should be logged and optionally stored as partial records with `text_content=None` and the error details in `raw_metadata`. This is critical because a researcher providing 100 URLs should not lose 99 successful results because one URL was unreachable.

3. **Tier-based behavior**:

   **FREE tier**:
   - Max 100 URLs per run
   - Use `fetch_url()` from `http_fetcher.py` only (no Playwright)
   - 1 req/sec per domain rate limit
   - If `FetchResult.needs_playwright == True`, log the URL with a warning and store a partial record with `needs_playwright: true` in `raw_metadata`, but do not attempt Playwright fetch

   **MEDIUM tier**:
   - Max 500 URLs per run
   - Use `fetch_url()` as primary
   - If `FetchResult.needs_playwright == True`, retry with `fetch_url_playwright()` from `playwright_fetcher.py`
   - 2 req/sec per domain rate limit
   - Playwright dependency must be optional -- handle `ImportError` gracefully if Playwright is not installed (log warning, treat as FREE tier for that URL)

4. **URL deduplication before fetching**: Before starting the fetch loop, deduplicate the `custom_urls` list. Normalize URLs by:
   - Stripping trailing slashes
   - Removing common tracking parameters (UTM, fbclid, gclid) -- use the same URL normalization logic from `src/issue_observatory/core/deduplication.py`
   - Lowercasing the hostname

   This prevents fetching the same page twice when the researcher has accidentally provided duplicate or near-duplicate URLs.

5. **Domain grouping for rate limiting**: Group URLs by domain before fetching. Create one `asyncio.Semaphore(1)` per domain to ensure sequential access within a domain. Use `asyncio.gather()` across domains for parallel fetching. This maximizes throughput while respecting per-domain rate limits.

6. **`robots.txt` compliance**: Create a single `robots_cache: dict[str, bool]` at the start of the collection run and pass it to all `fetch_url()` calls. The existing `_is_allowed_by_robots()` function caches results per origin, so repeated URLs from the same domain will not re-fetch `robots.txt`. The cache persists for the duration of the collection run.

7. **Publication date extraction priority**:
   ```
   1. trafilatura.extract_metadata(html, default_url=url).date
   2. HTTP Last-Modified header from FetchResult (parse with email.utils.parsedate_to_datetime)
   3. datetime.utcnow() (fallback — collection timestamp)
   ```
   When using `trafilatura`'s date, note that it returns a string in `YYYY-MM-DD` format, not a datetime object. Parse it to a timezone-aware datetime.

8. **`httpx.AsyncClient` lifecycle**: Create a single `httpx.AsyncClient` instance at the start of `collect_by_terms()` / `collect_by_actors()` and reuse it for all fetches within the run. Configure with:
   - `timeout=DEFAULT_TIMEOUT` (30 seconds)
   - `follow_redirects=True`
   - `headers={"User-Agent": USER_AGENT}`
   - Connection pool limits appropriate for the tier

9. **Health check**: Attempt to fetch a well-known stable URL (e.g., `https://www.dr.dk/`) and verify that `FetchResult.html` is non-empty and `extract_from_html()` returns non-None text. This validates that the full fetch-and-extract pipeline works.

10. **Credit cost**: 0 credits for all operations at both tiers. The URL Scraper is entirely self-hosted with no external API costs.

11. **Normalization function**: The `normalize()` method should:
    - Compute `platform_id` as `hashlib.sha256(final_url.encode()).hexdigest()` using the final URL after redirect resolution (not the original URL, to avoid duplicates for redirected pages)
    - Compute `content_hash` via `Normalizer.compute_content_hash(text_content)` for cross-arena deduplication
    - Compute `pseudonymized_author_id` via `Normalizer.pseudonymize_author(domain)` for consistency with other arenas, even though the "author" is a domain name
    - Set `language` from `ExtractedContent.language` if available

12. **Progress reporting**: Given that URL scraping can be slow (100 URLs at 1 req/sec = ~100+ seconds, plus extraction time), the collector should report progress. Use the same pattern as the existing scraper router's SSE progress stream -- track `total_urls`, `urls_processed`, `urls_failed`, `urls_skipped` counters and expose them via the collection run status.

### Tier Configuration Constants

```python
# src/issue_observatory/arenas/web/url_scraper/config.py

URL_SCRAPER_TIERS = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=100,
        rate_limit_per_minute=60,      # 1 req/sec per domain
        requires_credential=False,
        estimated_credits_per_1k=0,
    ),
    Tier.MEDIUM: TierConfig(
        tier=Tier.MEDIUM,
        max_results_per_run=500,
        rate_limit_per_minute=120,     # 2 req/sec per domain
        requires_credential=False,
        estimated_credits_per_1k=0,
    ),
}

# Per-domain politeness
DOMAIN_DELAY_FREE: float = 1.0       # seconds between requests to same domain (FREE)
DOMAIN_DELAY_MEDIUM: float = 0.5     # seconds between requests to same domain (MEDIUM)

# Health check
HEALTH_CHECK_URL: str = "https://www.dr.dk/"
```

### Relationship to Existing Scraper Router

The existing scraper module at `src/issue_observatory/scraper/router.py` provides a FastAPI router for managing scraping jobs (create, list, cancel, stream progress). The URL Scraper arena should NOT duplicate this infrastructure. Instead:

- The arena collector (`UrlScraperCollector`) handles the `ArenaCollector` interface (`collect_by_terms`, `collect_by_actors`, `normalize`)
- The collection orchestration (task dispatch, progress tracking) uses the standard arena task infrastructure (Celery tasks at `src/issue_observatory/arenas/web/url_scraper/tasks.py`)
- The existing scraper router remains as a separate, complementary service for ad-hoc scraping jobs outside the arena framework

The key distinction: the scraper router creates standalone `ScrapingJob` records and stores results in scraped content tables. The URL Scraper arena creates `CollectionRun` records and stores results as `UniversalContentRecord` entries in `content_records`. They share the same underlying fetch/extract code but serve different purposes.

---

## 12. Use Case Examples

### Greenland Research (GR-10 Primary Use Case)

**Scenario**: A researcher studying Greenlandic self-determination discourse wants to collect content from government websites and Arctic policy publications that have no RSS feeds.

**Configuration**:
```json
{
  "url_scraper": {
    "custom_urls": [
      "https://naalakkersuisut.gl/da/Naalakkersuisut/Nyheder",
      "https://naalakkersuisut.gl/da/Naalakkersuisut/Nyheder/2026/01",
      "https://naalakkersuisut.gl/da/Naalakkersuisut/Nyheder/2026/02",
      "https://arctictoday.com/category/greenland/",
      "https://www.ft.dk/samling/20251/almdel/GRU/bilag.htm",
      "https://www.diis.dk/en/research/arctic",
      "https://www.diis.dk/publikationer?field_research_area_target_id=41"
    ],
    "tier": "free"
  }
}
```

**Search terms**: `["Gronland", "Greenland", "selvbestemmelse", "rigsfaellesskab", "sovereignty"]`

**Expected output**: Content records from each URL that mention any search term, with extracted article text, publication dates where available, and domain-based author attribution.

### Complementary Use with Other Arenas

The URL Scraper is most effective when used alongside discovery arenas:

1. **Google Search discovers relevant URLs** -> researcher adds them to `custom_urls` -> URL Scraper fetches full content
2. **RSS feeds provide headlines and summaries** -> researcher wants full article text for paywalled outlets -> URL Scraper attempts extraction (may only get paywall teaser)
3. **GDELT identifies international articles about Denmark** -> researcher wants full text, not just GDELT snippets -> URL Scraper fetches the original articles
4. **Cross-platform link mining (GR-22)** discovers niche websites mentioned in Telegram/Discord -> researcher adds discovered URLs to `custom_urls`

This "discovery-then-scrape" workflow is the intended usage pattern. The URL Scraper is a content-retrieval tool, not a content-discovery tool.
