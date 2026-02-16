# Arena Research Brief: Google Search (SERP)

**Created**: 2026-02-16
**Last updated**: 2026-02-16
**Status**: Implemented (retroactive documentation)
**Phase**: 2 (Task 2.2, Critical priority)
**Arena path**: `src/issue_observatory/arenas/google_search/`

---

## 1. Platform Overview

Google Search is the dominant search engine in Denmark with over 90% market share. This arena collects Google Search Engine Results Pages (SERP) -- specifically the organic result listings returned for programmatic queries. SERP data provides a snapshot of what Google surfaces for a given query at a given moment, which is a proxy for information visibility and issue salience in the Danish search landscape.

**Role in Danish discourse**: Google Search results reflect what content is most visible to Danish users seeking information on any topic. By collecting SERP snapshots for issue-related queries with Danish locale parameters (`gl=dk`, `hl=da`), the system captures which sources, frames, and narratives dominate the information environment for Danish search users. This is complementary to social media collection (which captures what people say) -- SERP collection captures what people find.

**Access model**: Google provides no free programmatic search API. Collection requires a third-party SERP API provider. Two providers are supported:
- **Serper.dev** (MEDIUM tier) -- low-cost, credit-based pricing
- **SerpAPI** (PREMIUM tier) -- higher cost, higher rate limits, additional metadata

**Important distinction**: This arena collects SERP result metadata (titles, URLs, snippets, positions), not the full content of the linked pages. Results are position-snapshots reflecting Google's ranking at collection time.

---

## 2. Tier Configuration

| Tier | Service | Cost | Rate Limit | Max Results/Run | Notes |
|------|---------|------|------------|-----------------|-------|
| **Free** | N/A | Not available | -- | -- | Google has no free programmatic search API. Returns empty list with warning. |
| **Medium** | Serper.dev | $0.30 / 1K queries | 100 req/min | 10,000 | POST-based JSON API. 2,500 free queries on signup. |
| **Premium** | SerpAPI | ~$2.75--25 / 1K queries | 200 req/min | 100,000 | GET-based API. Pricing varies by plan tier. |

**FREE tier is explicitly unavailable.** The `GoogleSearchCollector` returns an empty list and logs a warning when `tier=Tier.FREE` is requested. This is enforced in `collector.py` and reflected in the tier config (`GOOGLE_SEARCH_TIERS[Tier.FREE] = None`).

---

## 3. API/Access Details

### Serper.dev (MEDIUM tier)

**Endpoint**: `POST https://google.serper.dev/search`

**Authentication**: `X-API-KEY` header with the Serper.dev API key.

**Request format**: JSON body.

| Body Parameter | Type | Description | Example |
|----------------|------|-------------|---------|
| `q` | string | Search query | `"klimaforandringer"` |
| `gl` | string | Geolocation (country) | `"dk"` (Denmark) |
| `hl` | string | Host/interface language | `"da"` (Danish) |
| `num` | integer | Results per page (max 10) | `10` |
| `page` | integer | Page number (1-indexed) | `1` |

**Response**: JSON object with an `organic` array containing result objects:

| Response Field | Type | Description |
|----------------|------|-------------|
| `title` | string | Result title |
| `link` | string | Result URL |
| `snippet` | string | Result description/snippet |
| `position` | integer | SERP position (1-indexed) |
| `date` | string | Date string (if present, not always available) |
| `sitelinks` | array | Sitelink sub-results (if present) |

### SerpAPI (PREMIUM tier)

**Endpoint**: `GET https://serpapi.com/search`

**Authentication**: `api_key` query parameter.

| Query Parameter | Type | Description | Example |
|-----------------|------|-------------|---------|
| `q` | string | Search query | `"klimaforandringer"` |
| `gl` | string | Geolocation | `"dk"` |
| `hl` | string | Interface language | `"da"` |
| `num` | integer | Results per page (max 10) | `10` |
| `start` | integer | Offset (0-indexed) | `0`, `10`, `20` |
| `api_key` | string | SerpAPI API key | -- |
| `engine` | string | Search engine | `"google"` |
| `output` | string | Response format | `"json"` |

**Response**: JSON object with an `organic_results` array. Field names differ slightly from Serper.dev (e.g., `link` vs. URL field naming), but the normalizer handles both via generic key extraction.

### SDK / Python Library

No dedicated SDK is used. The implementation uses `httpx.AsyncClient` for direct HTTP requests. Low-level request logic is in `_client.py` (private module), separated from the collector to keep file sizes manageable.

---

## 4. Danish Context

- **`gl=dk`**: Sets the geolocation to Denmark, ensuring results reflect the Danish Google index (the same results a user physically in Denmark would see).
- **`hl=da`**: Sets the interface language to Danish, which influences result ranking and may surface Danish-language content more prominently.
- **Single source of truth**: Danish parameters are sourced from `issue_observatory.config.danish_defaults.DANISH_GOOGLE_PARAMS` and applied automatically to every outbound request. They cannot be overridden per-request. This is shared with the Google Autocomplete arena.
- **No explicit language filter**: Unlike platforms with a `lang:da` parameter, Google Search does not offer an API-level content language filter. The `gl=dk` and `hl=da` parameters influence ranking but do not guarantee all results are in Danish. Results may include English-language content that Google deems relevant to Danish users.
- **Danish search behavior**: Google's Danish index reflects the local media ecosystem. Queries for Danish political terms, institutions, or current events will surface Danish news outlets (DR, TV2, Berlingske, Politiken, etc.) prominently due to the `gl=dk` parameter.

---

## 5. Data Fields

Mapping to the Universal Content Record schema. The normalizer uses generic key extraction -- Serper.dev field names (e.g., `link`, `snippet`) are matched by the `Normalizer._extract_str()` method which tries multiple candidate keys in sequence.

| UCR Field | Source (Serper.dev) | Source (SerpAPI) | Notes |
|-----------|-------------------|-----------------|-------|
| `platform` | `"google"` | `"google"` | Constant, set by collector |
| `arena` | `"google_search"` | `"google_search"` | Constant, set by collector |
| `platform_id` | `url` (extracted via `["id", "post_id", "item_id", "url"]`) | Same | Falls through to `url` since SERP results have no native ID. Effectively SHA-256 of the URL via `content_hash`. |
| `content_type` | `"search_result"` | `"search_result"` | Set by collector before normalization (`raw_item.setdefault("content_type", "search_result")`) |
| `text_content` | `snippet` (via `["text", "body", "content", ..., "snippet"]`) | `snippet` | The SERP snippet text |
| `title` | `title` | `title` | Result title as displayed on the SERP |
| `url` | `link` (via `["url", "link", "permalink", ...]`) | `link` | The destination URL of the search result |
| `language` | `NULL` | `NULL` | SERP APIs do not return per-result language. Inferred from `gl`/`hl` context. |
| `published_at` | `date` (if present) | `date` (if present) | Not always available. Many SERP results have no date. |
| `collected_at` | `datetime.now(UTC)` | Same | Standard |
| `author_platform_id` | `NULL` | `NULL` | SERP results have no author concept |
| `author_display_name` | `NULL` | `NULL` | No author metadata |
| `views_count` | `NULL` | `NULL` | Not available |
| `likes_count` | `NULL` | `NULL` | Not available |
| `shares_count` | `NULL` | `NULL` | Not available |
| `comments_count` | `NULL` | `NULL` | Not available |
| `engagement_score` | `NULL` | `NULL` | Not available |
| `raw_metadata` | Full raw result dict | Full raw result dict | Includes `position`, `sitelinks`, `date`, and any other provider-specific fields |
| `media_urls` | `[]` | `[]` | No media URL extraction for SERP results |
| `content_hash` | SHA-256 of URL (fallback when `text_content` is empty) or SHA-256 of `snippet` | Same | URL-based dedup when snippet is missing; snippet-based otherwise |

**Key observation**: The `position` field (SERP ranking position) is preserved in `raw_metadata` but has no dedicated UCR column. This is important metadata for analysis -- it indicates how visible a result is (position 1 vs. position 50).

---

## 6. Credential Requirements

| Tier | Environment Variable | CredentialPool `platform` | Notes |
|------|---------------------|--------------------------|-------|
| Free | N/A | N/A | Not supported |
| Medium | `SERPER_MEDIUM_API_KEY` | `"serper"` | Shared with Google Autocomplete arena |
| Premium | `SERPAPI_PREMIUM_API_KEY` | `"serpapi"` | Shared with Google Autocomplete arena |

**Credential sharing**: Serper.dev and SerpAPI credentials are shared between the Google Search and Google Autocomplete arenas. The `CredentialPool` uses platform-level keys (`"serper"`, `"serpapi"`), not arena-level keys. This means credit consumption from both arenas draws from the same account balance.

**Credential acquisition**: The collector calls `credential_pool.acquire(platform="serper", tier="medium")` for MEDIUM tier and `credential_pool.acquire(platform="serpapi", tier="premium")` for PREMIUM tier. On error, `credential_pool.report_error()` is called. Credentials are always released in a `finally` block.

---

## 7. Rate Limits and Multi-Account Notes

| Tier | Rate Limit | Pagination | Credit Model |
|------|-----------|------------|--------------|
| Medium (Serper.dev) | 100 req/min (configured in `TierConfig`) | `page` parameter, 1-indexed | 1 query = 1 credit (each query returns 1 page of up to 10 results) |
| Premium (SerpAPI) | 200 req/min (configured in `TierConfig`) | `start` offset, 0-indexed | Varies by plan; estimated 3 credits / 1K results |

**Serper.dev effective limit**: While Serper.dev advertises up to 100 requests/second for its API, the practical limit is credit-based. At $0.30/1K queries, a run collecting 10,000 results requires 1,000 queries (1,000 credits).

**SerpAPI plan variation**: SerpAPI pricing ranges from $50/month (5K searches) to $250/month (30K searches) and beyond. The per-query cost varies by plan: $2.75/1K at the high end to as low as $8.33/1K at the low-volume plan.

**Rate limiter integration**: The collector uses the shared Redis-backed `RateLimiter` from `workers/rate_limiter.py` when injected. Rate-limited requests are gated through `rate_limited_request()` context manager with provider-specific keys (`"serper"` or `"serpapi"`).

**Multi-account**: Multiple API keys can be registered in the `CredentialPool` for either provider. The pool handles rotation and error reporting. Multiple Serper.dev or SerpAPI accounts can be used to increase effective throughput or credit budget.

**Celery retry**: On `ArenaRateLimitError` (HTTP 429), Celery tasks retry with exponential backoff (up to 3 retries, capped at 5 minutes between attempts).

---

## 8. Search Capabilities

### Keyword Search
Standard Google search syntax is supported. Terms are passed directly as the `q` parameter. Boolean operators (`AND`, `OR`, `-`), quoted phrases, and site-scoping (`site:dr.dk`) all work because the query is executed by Google's search engine.

### Actor-Based Collection
Google Search has no native concept of actors/authors. The `collect_by_actors()` method converts actor identifiers (expected to be domain names) into `site:` queries:

```
actor_id = "dr.dk"  -->  query = "site:dr.dk"
```

This retrieves pages indexed from the specified domain within the Danish Google index.

### Date Filtering
**Not supported.** Neither Serper.dev nor SerpAPI exposes a date-range filter in the standard Google Search API. The `date_from` and `date_to` parameters accepted by the collector interface are ignored. For historical news content, use GDELT or Event Registry.

### Pagination
Both providers return a maximum of 10 organic results per request. The collector paginates automatically:
- Serper.dev: increments the `page` parameter (1, 2, 3, ...)
- SerpAPI: increments the `start` offset (0, 10, 20, ...)

Pagination stops when:
1. The API returns fewer than 10 results (no more pages), or
2. The `max_results` limit is reached.

---

## 9. Latency and Freshness

- **Response latency**: Sub-second to low single-digit seconds per query for both providers.
- **Freshness of results**: Results reflect Google's current index at query time. This is a snapshot, not a historical archive. Re-querying the same term at a different time may return different results due to index updates, ranking algorithm changes, or news cycle evolution.
- **No real-time streaming**: SERP collection is polling-based only. There is no equivalent of a firehose or WebSocket stream.
- **Recommended polling interval**: For issue tracking, poll key terms every 4-12 hours to capture SERP changes without excessive credit consumption. More frequent polling (hourly) is warranted during breaking events but is expensive.

---

## 10. Legal Considerations

- **Terms of service**: Both Serper.dev and SerpAPI are commercial API services designed for programmatic access to Google Search results. Using these services is within their intended use case and does not violate Google's Terms of Service (unlike direct scraping of google.com).
- **GDPR**: SERP results are publicly available information. Individual search results do not typically contain personal data beyond publicly published author names on news articles. No special GDPR measures are needed for SERP metadata. If full page content is later fetched from result URLs (out of scope for this arena), GDPR assessment of that content is required.
- **DSA**: Google Search is designated as a Very Large Online Platform (VLOP) under the DSA. DSA Article 40 researcher access applies to Google's platform data, but this arena uses third-party API providers rather than direct Google data access, so DSA researcher access is not directly relevant.
- **Research use**: Both Serper.dev and SerpAPI permit research use. No additional license or application is required beyond a standard API subscription.
- **Data retention**: SERP snapshots are ephemeral by nature (results change over time). The collected data represents a point-in-time observation and should be documented as such in any research output.

---

## 11. Known Limitations and Gotchas

1. **No date filtering**: The `date_from` and `date_to` parameters are accepted by the interface but silently ignored. There is no API-level mechanism to restrict results to a date range. Google's `tbs` parameter (time-based search) is not exposed by either provider in the standard API.

2. **Position-snapshot data**: Results represent what Google returns at query time. Rankings change continuously. The same query may yield different results hours or days later. Treat SERP data as timestamped snapshots, not stable records.

3. **No engagement metrics**: Search results carry no likes, shares, comments, or view counts. All engagement UCR fields are `NULL`. The only implicit engagement signal is the SERP position (stored in `raw_metadata`).

4. **10 results per page**: Both providers cap organic results at 10 per request. Deep pagination beyond page 10 (position 100+) produces diminishing returns -- result quality degrades and the data becomes less meaningful for visibility analysis.

5. **No content body**: The `text_content` field contains only the SERP snippet (typically 1-2 sentences), not the full page content. Full-text retrieval requires fetching the URL separately, which is out of scope for this arena.

6. **`collect_by_actors()` is domain-only**: Actor IDs are treated as domain names and converted to `site:` queries. This does not support individual author identification within a domain.

7. **Credit consumption across arenas**: Serper.dev and SerpAPI credentials are shared with the Google Autocomplete arena. Credit budgets must account for consumption from both arenas.

8. **No language guarantee**: Unlike social media `lang:da` filters, the `gl=dk` and `hl=da` parameters influence but do not guarantee Danish-language results. English-language content relevant to Danish users may appear.

9. **Health check requires credentials**: The `health_check()` method requires a valid Serper.dev credential. If no credential is available, it returns `"degraded"` status rather than `"down"`.

10. **SerpAPI response field differences**: SerpAPI returns organic results under the key `organic_results`, while Serper.dev uses `organic`. The `_client.py` module handles this difference, but if raw responses are inspected directly, this mismatch could cause confusion.

---

## 12. Collector Implementation Notes

### Architecture (as implemented)

The Google Search arena is fully implemented at `src/issue_observatory/arenas/google_search/` with the following module structure:

| Module | Purpose |
|--------|---------|
| `collector.py` | `GoogleSearchCollector` class implementing `ArenaCollector` interface |
| `_client.py` | Low-level HTTP helpers: `fetch_serper()` and `fetch_serpapi()` |
| `config.py` | Constants: API URLs, tier configs, Danish params, pagination settings |
| `README.md` | Operational documentation |

### Key Implementation Details

1. **Class registration**: `GoogleSearchCollector` is decorated with `@register`, making it discoverable via the arena registry. `arena_name = "google_search"`, `platform_name = "google"`.

2. **Tier dispatch**: The collector selects the provider based on tier:
   - `Tier.MEDIUM` --> `fetch_serper()` (POST, `X-API-KEY` header, JSON body)
   - `Tier.PREMIUM` --> `fetch_serpapi()` (GET, `api_key` query param, `engine=google`)
   - `Tier.FREE` --> returns `[]` with warning log

3. **Pagination loop** (`_collect_term()`): Iterates pages until `max_results` is reached or the API returns fewer than `MAX_RESULTS_PER_PAGE` (10) results. Each result is normalized inline via `self.normalize()`.

4. **Normalization**: The `normalize()` method sets `content_type="search_result"` on the raw item before delegating to the shared `Normalizer`. The normalizer's generic key extraction handles both Serper.dev (`link`, `snippet`) and SerpAPI (`link`, `snippet`) field names.

5. **Error handling**: HTTP status codes are mapped to typed exceptions:
   - 429 --> `ArenaRateLimitError` (with `Retry-After` header extraction)
   - 401/403 --> `ArenaAuthError`
   - Other non-2xx --> `ArenaCollectionError`
   - Network errors --> `ArenaCollectionError`
   On `ArenaRateLimitError` or `ArenaAuthError`, the credential pool is notified via `report_error()`.

6. **Credit estimation** (`estimate_credits()`): Calculates estimated cost as:
   - MEDIUM: 1 credit per query (pages_per_term * num_terms)
   - PREMIUM: `ceil(total_results * estimated_credits_per_1k / 1000)`

7. **Health check**: Sends a minimal Serper.dev query (`q=test`, `num=1`, with Danish params) and verifies a successful response. Returns `"ok"`, `"degraded"`, or `"down"`.

8. **HTTP client**: Uses `httpx.AsyncClient` with 30-second timeout. An injected client can be provided for testing. The client is used as an async context manager within `collect_by_terms()`.

### Polling Strategy

- For ongoing issue tracking: poll key terms every 4-12 hours.
- For event monitoring: increase to hourly during active events.
- For baseline snapshots: daily collection of a fixed term list.
- Budget: at $0.30/1K queries (Serper.dev), 100 terms polled 4x/day = 400 queries/day = ~$3.60/month.
