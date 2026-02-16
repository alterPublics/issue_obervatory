# Arena Research Brief: Common Crawl / Wayback Machine

**Created**: 2026-02-16
**Last updated**: 2026-02-16
**Status**: Ready for implementation
**Phase**: 2 (Task 2.10, Low priority)
**Arena path**: `src/issue_observatory/arenas/web/common_crawl/` and `src/issue_observatory/arenas/web/wayback/`

---

## 1. Platform Overview

This brief covers two complementary web archive services that are combined into a single implementation task due to their shared role: providing historical web snapshots for batch analysis.

### Common Crawl

Common Crawl (commoncrawl.org) is a non-profit that performs monthly crawls of the open web, archiving 2.5-3 billion pages per crawl. The complete archive spans 2008 to present and is stored on Amazon S3 as a public dataset. Data is available in three formats: WARC (raw HTTP responses), WAT (metadata extracted from WARC), and WET (plain text extracted from WARC). The index is queryable via AWS Athena (serverless SQL) or the Common Crawl Index API.

### Wayback Machine

The Wayback Machine (web.archive.org), operated by the Internet Archive, has archived over 1 trillion web pages since 1996. It provides snapshot access to historical versions of any web page, with a CDX (Capture/inDeX) API for programmatically searching the archive by URL, date range, and other filters. The service is entirely free with no API keys required.

**Role in Danish discourse**: These archives serve a fundamentally different function from real-time collection arenas. They enable:

- **Historical baseline**: What did a Danish website say about a topic before the current issue cycle began?
- **Content change tracking**: How did a news article, government page, or organization website change over time? (Wayback Machine excels here.)
- **Deleted content recovery**: Retrieving articles or pages that have been removed from the live web.
- **Large-scale Danish web analysis**: What does the Danish portion of the web look like in aggregate? (Common Crawl enables this via its `.dk` domain coverage.)
- **Source verification**: Confirming that a cited article or web page existed and contained specific content at a specific date.

Neither service provides real-time data. Both are batch-oriented retrospective tools. They are lowest-priority in Phase 2 because they do not contribute to live issue tracking, but they provide unique capabilities for historical analysis and source verification that no other arena offers.

**Access model**: Both are free. Common Crawl incurs AWS Athena query costs (~$1.50 per full index scan). Wayback Machine CDX API is free, unauthenticated, with informal rate limits.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | Common Crawl (via Athena) + Wayback Machine CDX API | ~$0-5/month | Athena: ~$1.50 per full index scan (10 TB scanned at $5/TB). Wayback CDX: $0. |
| **Medium** | N/A | -- | No medium tier. |
| **Premium** | N/A | -- | No premium tier. |

Both services are effectively free-tier. Common Crawl has a small variable cost for Athena queries, but for targeted Danish queries (filtering by `.dk` domain early reduces scan volume), costs are minimal.

---

## 3. API/Access Details

### Common Crawl

#### Access Methods

**1. Common Crawl Index API (cc-index)**

**Base URL**: `https://index.commoncrawl.org/CC-MAIN-{crawl-id}-index`

Where `{crawl-id}` is a crawl identifier like `2026-05` (year-week format).

**Parameters**:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `url` | URL or URL pattern to search for | `*.dk/*` |
| `matchType` | How to match the URL | `exact`, `prefix`, `host`, `domain` |
| `output` | Response format | `json` (one JSON object per line) |
| `limit` | Max results | `1000` |
| `filter` | Field-based filtering | `=status:200` |
| `from` | Timestamp lower bound | `20260101` |
| `to` | Timestamp upper bound | `20260216` |

**Response fields** (per capture):

| Field | Description |
|-------|-------------|
| `urlkey` | SURT-formatted URL (reversed domain, for efficient sorting) |
| `timestamp` | Capture timestamp (YYYYMMDDHHmmss) |
| `url` | Original URL |
| `mime` | MIME type |
| `mime-detected` | Detected MIME type |
| `status` | HTTP status code |
| `digest` | SHA-1 hash of content |
| `length` | Record length in WARC |
| `offset` | Byte offset in WARC file |
| `filename` | WARC filename on S3 |
| `languages` | Detected languages (e.g., `"dan"`) |
| `charset` | Character encoding |

**2. AWS Athena (SQL queries)**

Common Crawl maintains a columnar index in the `commoncrawl` database on AWS Athena. This enables SQL queries across the entire archive.

**Table**: `ccindex`

**Key columns**:

| Column | Type | Description |
|--------|------|-------------|
| `url_host_tld` | string | Top-level domain (e.g., `dk`) |
| `url_host_registered_domain` | string | Registered domain (e.g., `dr.dk`) |
| `url_host_name` | string | Full hostname (e.g., `www.dr.dk`) |
| `url_path` | string | URL path |
| `url_query` | string | URL query string |
| `fetch_time` | timestamp | When the page was fetched |
| `fetch_status` | int | HTTP status code |
| `content_mime_type` | string | MIME type |
| `content_mime_detected` | string | Detected MIME type |
| `content_languages` | string | Detected languages |
| `warc_filename` | string | WARC file location on S3 |
| `warc_record_offset` | bigint | Byte offset in WARC file |
| `warc_record_length` | bigint | Record length |
| `content_digest` | string | Content hash |
| `crawl` | string | Crawl identifier (partition key) |

**Example Athena query for Danish pages**:

```sql
SELECT url, fetch_time, content_mime_type, content_languages,
       warc_filename, warc_record_offset, warc_record_length
FROM ccindex
WHERE crawl = 'CC-MAIN-2026-05'
  AND url_host_tld = 'dk'
  AND fetch_status = 200
  AND content_mime_detected = 'text/html'
  AND content_languages LIKE '%dan%'
LIMIT 1000;
```

**Cost**: Athena charges $5 per TB scanned. A full scan of one crawl's index is approximately 300 GB (columnar), costing ~$1.50. Filtering by `crawl` partition and `url_host_tld` significantly reduces scan volume.

**3. Direct S3 Access (WARC files)**

Raw WARC files are stored on `s3://commoncrawl/`. After identifying records via the index or Athena, fetch the specific WARC record by file, offset, and length:

```
s3://commoncrawl/{warc_filename}
Range: bytes={offset}-{offset + length - 1}
```

This retrieves the raw HTTP response (headers + body) for the archived page.

#### Python Libraries for Common Crawl

- **`comcrawl`** (PyPI): Simple Python wrapper for the CC Index API.
- **`warcio`** (PyPI): Reading and writing WARC files.
- **`boto3`** (PyPI): AWS SDK for S3 access and Athena queries.
- **`cdx_toolkit`** (PyPI): Unified interface for both Common Crawl and Wayback Machine CDX APIs.

### Wayback Machine

#### CDX API

**Base URL**: `https://web.archive.org/cdx/search/cdx`

**Parameters**:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `url` | URL to search for | `dr.dk/nyheder/*` |
| `matchType` | URL matching mode | `exact`, `prefix`, `host`, `domain` |
| `output` | Response format | `json` |
| `limit` | Max results | `1000` |
| `from` | Start timestamp | `20250101000000` |
| `to` | End timestamp | `20260216235959` |
| `filter` | Field-based filter | `statuscode:200`, `mimetype:text/html` |
| `collapse` | Deduplicate by field | `timestamp:8` (one per day), `digest` (unique content) |
| `fl` | Fields to return | `urlkey,timestamp,original,mimetype,statuscode,digest,length` |
| `gzip` | Gzip compress response | `true` |
| `showResumeKey` | Enable pagination | `true` |
| `resumeKey` | Continue from previous page | (returned by previous response) |

**Response fields**:

| Field | Description |
|-------|-------------|
| `urlkey` | SURT-formatted URL |
| `timestamp` | Capture timestamp (YYYYMMDDHHmmss) |
| `original` | Original URL |
| `mimetype` | MIME type |
| `statuscode` | HTTP status code |
| `digest` | SHA-1 hash of content |
| `length` | Response length |

#### Retrieving Archived Pages

After finding captures via the CDX API, retrieve the actual page content:

**URL pattern**: `https://web.archive.org/web/{timestamp}id_/{url}`

The `id_` suffix requests the raw content without Wayback Machine's toolbar injection. Without `id_`, the response includes Wayback Machine's navigation banner and rewritten URLs.

**Example**: `https://web.archive.org/web/20260101120000id_/https://dr.dk/nyheder/indland/article123`

#### Wayback Machine Availability API

**Endpoint**: `https://archive.org/wayback/available`

**Parameters**: `url={url}&timestamp={timestamp}`

**Response**: Returns the closest available snapshot to the requested timestamp.

```json
{
  "url": "dr.dk",
  "archived_snapshots": {
    "closest": {
      "status": "200",
      "available": true,
      "url": "https://web.archive.org/web/20260115/https://dr.dk/",
      "timestamp": "20260115120000"
    }
  }
}
```

#### Rate Limits

| Service | Rate Limit | Notes |
|---------|-----------|-------|
| CDX API search | ~1 req/sec (informal) | No authentication, IP-based throttling |
| Page retrieval | ~30 req/sec (informal) | Higher throughput for retrieving individual pages |
| Availability API | ~1 req/sec | Lightweight check |

Rate limits are not formally documented. The Internet Archive has experienced infrastructure fragility (November 2025 Cloudflare disruption, October 2024 security breach). Implement conservative rate limiting and graceful failure handling.

#### Python Libraries for Wayback Machine

- **`waybackpy`** (PyPI): Python wrapper for Wayback Machine APIs (CDX, availability, save).
- **`cdx_toolkit`** (PyPI): Unified interface for both Wayback Machine and Common Crawl CDX APIs.
- **`requests`**: Direct HTTP access works well given the simple API.

---

## 4. Danish Context

- **Common Crawl `.dk` coverage**: Each Common Crawl crawl captures a subset of the `.dk` domain space. Coverage varies by crawl but typically includes major Danish sites. Use the Athena query `WHERE url_host_tld = 'dk'` to extract the Danish slice. The `content_languages` field containing `"dan"` provides additional filtering for Danish-language pages on non-`.dk` domains.
- **Wayback Machine Danish coverage**: The Wayback Machine archives pages on demand (via user save requests) and through its own crawling. Major Danish sites (DR, TV2, Berlingske, government sites) are well-archived. Smaller sites may have sparse or no coverage.
- **No active Danish language NLP**: Neither service performs NLP on content. They store raw web pages. Any language detection, entity extraction, or content analysis must be performed by the Issue Observatory's own pipeline after retrieval.
- **Character encoding**: Danish pages use characters like ae, oe, aa and their modern equivalents. Most modern pages use UTF-8, but older archived pages may use ISO-8859-1 or Windows-1252. The WARC record includes the original HTTP Content-Type header, which specifies encoding. Handle encoding conversion in the normalizer.
- **Paywall content**: Archived versions of paywalled Danish sites (Berlingske, Politiken, JP) may contain full article text if the page was captured before a paywall was applied, or may contain only the teaser/preview. This varies by snapshot and is unpredictable.
- **Deleted content**: Danish news outlets occasionally remove articles (corrections, legal requests, GDPR right-to-erasure). The Wayback Machine may still have archived copies. Using these for research is legally permissible under Art. 89 but ethically requires consideration -- document this in the research ethics assessment.
- **DNS/domain changes**: Some Danish outlets have changed domains over the years (e.g., Borsen was `borsen.dk` and may have migrated). Track domain aliases when querying historical archives.

---

## 5. Data Fields

### Common Crawl to UCR Mapping

| UCR Field | Common Crawl Source | Notes |
|-----------|---------------------|-------|
| `platform` | `"common_crawl"` | Constant |
| `arena` | `"web"` | Constant |
| `platform_id` | `content_digest` or SHA-256 of `url + timestamp` | Content hash from the index, or construct from URL + capture time |
| `content_type` | `"web_page"` | New content type for archived web pages |
| `text_content` | Extracted from WARC body | Requires HTML parsing and text extraction (e.g., `trafilatura`, `readability-lxml`). Not available from the index alone -- must fetch the WARC record. |
| `title` | Extracted from HTML `<title>` tag | Requires fetching and parsing the WARC record |
| `url` | `url` (from index) | Original URL |
| `language` | `content_languages` | Map from ISO 639-3 (`"dan"`) to ISO 639-1 (`"da"`). May contain multiple languages. |
| `published_at` | `fetch_time` (Athena) or `timestamp` (Index API) | Crawl timestamp, not publication date. Publication date must be extracted from the page content if needed. |
| `collected_at` | Now | Standard |
| `author_platform_id` | `NULL` | Not available from crawl data |
| `author_display_name` | Domain extracted from URL | Use registered domain as proxy |
| `views_count` | `NULL` | Not available |
| `likes_count` | `NULL` | Not available |
| `shares_count` | `NULL` | Not available |
| `comments_count` | `NULL` | Not available |
| `engagement_score` | `NULL` | Not available |
| `raw_metadata` | Index metadata | Store: `content_digest`, `warc_filename`, `warc_record_offset`, `warc_record_length`, `content_mime_type`, `fetch_status`, `crawl` identifier |
| `media_urls` | `[]` | Could extract from HTML but not from index alone |
| `content_hash` | `content_digest` (SHA-1 from index) or SHA-256 of text | Index provides SHA-1 of raw content; compute SHA-256 of extracted text for cross-arena dedup |

### Wayback Machine to UCR Mapping

| UCR Field | Wayback Machine Source | Notes |
|-----------|------------------------|-------|
| `platform` | `"wayback_machine"` | Constant |
| `arena` | `"web"` | Constant |
| `platform_id` | SHA-256 of `url + timestamp` | Construct from the URL and capture timestamp |
| `content_type` | `"web_page_snapshot"` | Distinct from `"web_page"` to indicate this is a point-in-time snapshot |
| `text_content` | Extracted from retrieved page | Requires fetching the archived page and parsing HTML |
| `title` | Extracted from HTML `<title>` tag | Requires fetching the archived page |
| `url` | `original` (from CDX) | Original URL (not the `web.archive.org` URL) |
| `language` | `NULL` from CDX; detect from content | CDX API does not provide language. Detect from fetched content or infer from `.dk` TLD. |
| `published_at` | `timestamp` (from CDX) | Capture timestamp. Convert from `YYYYMMDDHHmmss` format. This is when the page was archived, not necessarily when it was published. |
| `collected_at` | Now | Standard |
| `author_platform_id` | `NULL` | Not available |
| `author_display_name` | Domain extracted from URL | Use domain as proxy |
| `views_count` | `NULL` | Not available |
| `likes_count` | `NULL` | Not available |
| `shares_count` | `NULL` | Not available |
| `comments_count` | `NULL` | Not available |
| `engagement_score` | `NULL` | Not available |
| `raw_metadata` | CDX metadata + retrieval metadata | Store: `digest`, `statuscode`, `mimetype`, `length`, `wayback_url` (the full `web.archive.org` URL for reference) |
| `media_urls` | `[]` | Could extract from HTML |
| `content_hash` | SHA-256 of extracted text | For cross-arena dedup |

**Important**: Both mappings require a two-step process: (1) query the index/CDX to find relevant records, (2) fetch the actual page content to populate `text_content` and `title`. Step 1 is cheap; step 2 is bandwidth-intensive and should be done selectively.

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Common Crawl (Athena) | `{"aws_access_key_id": "...", "aws_secret_access_key": "...", "aws_region": "us-east-1"}` | `"aws"` (shared with any other AWS-dependent arenas) |
| Common Crawl (Index API) | None | N/A |
| Common Crawl (S3 direct) | Same as Athena, or anonymous access for public bucket | `"aws"` |
| Wayback Machine | None | N/A |

The Common Crawl Index API and Wayback Machine CDX API require no authentication. AWS credentials are needed only for Athena queries and authenticated S3 access (though the `commoncrawl` S3 bucket allows anonymous reads in `us-east-1`).

---

## 7. Rate Limits and Multi-Account Notes

| Service | Rate Limit | Cost Cap | Notes |
|---------|-----------|----------|-------|
| Common Crawl Index API | ~1 req/sec (informal) | N/A (free) | IP-based. No authentication. |
| AWS Athena | Standard AWS limits | $5/TB scanned | Per-AWS-account. Athena concurrent query limit: 25 (default). |
| Common Crawl S3 | Standard S3 throughput | Free (public bucket) | No per-request cost in `us-east-1`. |
| Wayback CDX API | ~1 req/sec (informal) | N/A (free) | IP-based. Internet Archive infrastructure can be fragile. |
| Wayback page retrieval | ~30 req/sec (informal) | N/A (free) | Higher throughput, but be respectful of shared infrastructure. |

**Multi-account**: Not applicable for the free APIs. For Athena, each AWS account has its own query limits and billing. Multiple AWS accounts are unnecessary for the expected query volume.

**RateLimiter configuration**: Configure 1 request per second for both Index API and CDX API searches. For page retrieval (Wayback), configure 5-10 requests per second as a conservative starting point.

---

## 8. Known Limitations

1. **Not real-time**: Common Crawl crawls are monthly, with results available weeks after the crawl completes. The Wayback Machine archives pages asynchronously. Neither service is suitable for live tracking. Use for historical analysis and source verification only.

2. **Incomplete coverage**: Neither service archives the entire web. Coverage of smaller Danish sites may be sparse. A page not found in the archive does not mean it never existed.

3. **Two-step retrieval**: Index queries return metadata only. Fetching actual page content requires a separate HTTP request per page, which is bandwidth-intensive. Plan for selective retrieval based on index filtering.

4. **No structured content extraction**: Both services provide raw HTML. Extracting clean article text, publication dates, author names, and other structured data from arbitrary HTML pages requires robust content extraction (e.g., `trafilatura`, `newspaper3k`, `readability-lxml`). This is a significant implementation effort.

5. **Capture timestamp vs. publication date**: Both services record when a page was captured/fetched, not when its content was originally published. Publication date must be extracted from the page content itself (e.g., from `<meta>` tags, JSON-LD, or visible date elements). This extraction is fragile and site-specific.

6. **Content may differ from live version**: Archived pages may represent an earlier or later version than the content of interest. Paywalled content may be partially or fully captured depending on when the archiver visited.

7. **Common Crawl Athena cost**: While cheap per query (~$1.50 for a full scan), costs can accumulate with frequent or broad queries. Use partition pruning (`WHERE crawl = '...'`) and column selection to minimize scan volume.

8. **Wayback Machine infrastructure fragility**: The Internet Archive experienced a significant security breach in October 2024 and Cloudflare-related disruptions in November 2025. The service has no SLA. Implement robust error handling and do not depend on Wayback Machine availability for time-sensitive research.

9. **Legal considerations**: Both services archive publicly available web content. Using archived content for academic research is well-established practice. GDPR considerations: archived pages may contain personal data (names, photos, contact information). Under Art. 89 research exemption, this is permissible, but apply the standard `pseudonymized_author_id` to any extracted author information. For content removed from the live web at the request of a data subject (Art. 17 right to erasure), using the archived version for research is a gray area -- document this in the ethics assessment and consult with institutional data protection officer if specific cases arise.

10. **Encoding and rendering**: Older archived pages may use non-UTF-8 encodings, have broken CSS, or reference missing resources. The raw HTML is what was captured at the time. Text extraction tools handle encoding issues, but rendering-dependent content (JavaScript-generated text) may not be captured.

11. **Common Crawl robots.txt**: Common Crawl respects `robots.txt`. Pages blocked by `robots.txt` at crawl time will not be in the archive. This may exclude some Danish content from behind content delivery configurations.

---

## 9. Collector Implementation Notes

### Architecture

This arena is split into two collectors sharing the same arena category (`web`):

- **`CommonCrawlCollector`** at `src/issue_observatory/arenas/web/common_crawl/`
- **`WaybackCollector`** at `src/issue_observatory/arenas/web/wayback/`

Both are batch-oriented. They do not participate in live tracking (Celery Beat periodic tasks). They are triggered on-demand via collection runs in `batch` mode.

### Key Implementation Guidance

#### Common Crawl

1. **Query strategy**: Use the CC Index API for targeted URL lookups (e.g., "find all captures of `dr.dk/nyheder/*` from crawl `CC-MAIN-2026-05`"). Use Athena for broader queries (e.g., "find all `.dk` pages mentioning specific terms" -- though this requires fetching WARC records to search text).

2. **Index-first approach**: Always query the index first. Do not attempt to process entire WARC files. Each WARC file is ~1 GB compressed; there are tens of thousands per crawl. The index tells you exactly which WARC file and byte offset to fetch.

3. **Selective content retrieval**: After querying the index, apply relevance filters (URL patterns, domains, MIME types) before fetching WARC records. Only retrieve pages that match the query design's scope.

4. **WARC record fetching**: Use HTTP Range requests to fetch individual records from S3:
   ```
   GET s3://commoncrawl/{warc_filename}
   Range: bytes={offset}-{offset + length - 1}
   ```
   Parse with `warcio.ArchiveIterator`.

5. **Text extraction**: After fetching WARC records, extract article text using `trafilatura` (best for news articles) or `readability-lxml`. Store extracted text in `text_content`. Store the raw WARC record reference in `raw_metadata` for reproducibility.

6. **Athena query cost optimization**:
   - Always filter by `crawl` partition (reduces scan by ~98%).
   - Filter by `url_host_tld = 'dk'` early.
   - Select only needed columns.
   - Use `LIMIT` for exploratory queries.
   - Monitor bytes scanned via Athena query statistics.

7. **`cdx_toolkit` for unified access**: The `cdx_toolkit` library provides a single interface for both Common Crawl and Wayback Machine CDX APIs. Consider using it to reduce code duplication.

#### Wayback Machine

1. **CDX query construction**: Use `url` with `matchType=prefix` for domain-wide searches (e.g., all captures of `dr.dk/nyheder/*`). Use `collapse=timestamp:8` to deduplicate to one capture per day. Use `filter=statuscode:200` to exclude error pages.

2. **Pagination**: Use `showResumeKey=true` and `resumeKey` for paginating through large result sets. The CDX API does not support offset-based pagination.

3. **Content retrieval**: Fetch pages using the `id_` URL pattern to get raw content:
   `https://web.archive.org/web/{timestamp}id_/{url}`

4. **Content change tracking**: For a specific URL, fetch all captures (`matchType=exact`, no `collapse`), compare content hashes (`digest`), and identify when content changed. This is the Wayback Machine's unique value -- tracking how a page evolved over time.

5. **Rate limiting**: Respect the Internet Archive's shared infrastructure. Configure at 1 CDX query per second and 5 page retrievals per second. Implement exponential backoff on 503 and 429 responses.

6. **Save Page Now**: The Wayback Machine's "Save Page Now" API (`https://web.archive.org/save/{url}`) can be used to trigger archival of specific Danish pages for future reference. Use sparingly and only for pages of active research interest.

#### Shared Guidance

7. **`collect_by_terms` adaptation**: These arenas do not support keyword search in the traditional sense. Map `collect_by_terms` to URL-pattern searches: for each search term, identify relevant URLs from other arenas (RSS articles, Event Registry results) and query the archives for those specific URLs.

8. **`collect_by_actors` adaptation**: Map actors to their web domains (from `actor_platform_presences`). Query archives for domain-wide captures.

9. **Health check**:
   - Common Crawl: Query the Index API for a known URL and verify a valid response.
   - Wayback Machine: Query the Availability API for a well-known URL (e.g., `dr.dk`) and verify `available: true`.

10. **Credit cost**: Common Crawl Athena queries: map $1.50 per full scan to 150 credits (1 credit = $0.01). Wayback Machine: 0 credits. Index API queries: 0 credits. Adjust credit mapping based on actual Athena cost optimization.

11. **Error handling**:
    - Common Crawl Index API: May return empty results for URLs not in the crawl. Not an error.
    - Athena: Handle `QueryExhausted`, `InternalServerError`, timeout errors.
    - Wayback CDX API: Returns empty response for URLs with no captures. Handle 503 (service overloaded), 429 (rate limited).
    - Wayback page retrieval: Handle 404 (snapshot not available at exact timestamp), 503, timeouts.

12. **Storage considerations**: Full web page content can be large. Store extracted text in `text_content` (typically a few KB per article). Store WARC/archive references in `raw_metadata` rather than the full HTML, to avoid database bloat. If full HTML archival is desired, store in MinIO/S3 and reference the object key in `raw_metadata`.
