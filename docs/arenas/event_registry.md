# Arena Research Brief: Event Registry / NewsAPI.ai

**Created**: 2026-02-16
**Last updated**: 2026-02-16
**Status**: Ready for implementation
**Phase**: 2 (Task 2.4, High priority)
**Arena path**: `src/issue_observatory/arenas/news_media/event_registry/`

---

## 1. Platform Overview

Event Registry (eventregistry.org) and its API brand NewsAPI.ai are the same platform, operated by Event Registry Ltd. (Ljubljana, Slovenia). The system monitors 150,000+ news outlets in 60+ languages, ingests articles in near-real-time, and applies NLP enrichment including entity extraction, categorization, sentiment analysis, and -- critically -- **event clustering**, which groups articles about the same real-world event across sources and languages. Historical data extends back to 2014.

**Role in Danish discourse**: Event Registry provides a significant upgrade over GDELT for news monitoring. Where GDELT offers metadata-only with ~55% accuracy and English-translated titles, Event Registry provides full article text, native-language NLP processing (including Danish), entity extraction, and event deduplication. It serves as the primary paid news API for the Issue Observatory, complementing the free RSS feeds and GDELT arenas with richer metadata, broader source coverage, and article-level deduplication via event clustering.

**Danish coverage**: Event Registry monitors Danish outlets including DR, TV2, Berlingske, Politiken, Jyllands-Posten, Information, BT, Ekstra Bladet, and regional outlets. The exact source list can be queried via the API's `suggestNewsSources` endpoint filtered by location. Danish (`da`) is among the 60+ supported languages for NLP processing, meaning entity extraction and categorization are performed on the original Danish text rather than a machine translation.

**Access model**: Token-based. Monthly subscription plans provide a fixed number of tokens. Each API call consumes tokens based on the complexity of the request and the volume of data returned.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | N/A | -- | No free tier. A limited trial account may be available for evaluation (typically 30 days or 2,000 tokens). |
| **Medium** | NewsAPI.ai Starter | ~$90/month | 5,000 tokens/month. Sufficient for targeted Danish issue tracking with moderate query volume. |
| **Premium** | NewsAPI.ai Business | ~$490/month | 50,000 tokens/month. Required for high-volume collection, historical backfill, or multiple concurrent query designs. |

**Token consumption model**: Token costs vary by endpoint. Article search typically costs 1 token per request (returning up to 100 articles). Event search costs 1 token per request. Fetching full article content costs additional tokens. The exact token costs should be confirmed against the current pricing page at registration time.

> WARNING: Pricing and token allocations are based on publicly available information as of early 2026. Confirm exact pricing at `https://newsapi.ai/pricing` before committing to a subscription.

---

## 3. API/Access Details

### Authentication

**Method**: API key passed as a query parameter (`apiKey`) or in request headers.

**Obtaining credentials**: Register at `https://newsapi.ai/register`. An API key is generated upon account creation. The key is a long alphanumeric string.

### Base URL

`https://newsapi.ai/api/v1/`

Alternative (legacy): `https://eventregistry.org/api/v1/`

Both hostnames resolve to the same service. NewsAPI.ai is the current branding.

### Key Endpoints

#### Article Search

**Endpoint**: `POST /article/getArticles`

**Description**: Search for articles matching keywords, concepts, categories, sources, locations, dates, and languages.

**Key parameters**:

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `keyword` | string/array | Keyword(s) to search for | `"klimaforandringer"` |
| `keywordOper` | string | Boolean operator for multiple keywords | `"and"`, `"or"` |
| `conceptUri` | string/array | Concept URI(s) for entity-based search | `"http://en.wikipedia.org/wiki/Denmark"` |
| `categoryUri` | string | Category URI for topic filtering | `"news/Politics"` |
| `sourceUri` | string/array | Filter by specific news source | `"dr.dk"`, `"tv2.dk"` |
| `sourceLocationUri` | string | Filter by source country | `"http://en.wikipedia.org/wiki/Denmark"` |
| `lang` | string/array | Language filter (ISO 639-1) | `"dan"` (3-letter ISO 639-3 code for Danish) |
| `dateStart` | string | Start date | `"2026-01-01"` |
| `dateEnd` | string | End date | `"2026-02-16"` |
| `articlesPage` | int | Page number (1-indexed) | `1` |
| `articlesCount` | int | Articles per page (max 100) | `100` |
| `articlesSortBy` | string | Sort order | `"date"`, `"rel"`, `"sourceImportance"` |
| `articlesSortByAsc` | bool | Ascending sort | `false` |
| `resultType` | string | Response format | `"articles"`, `"uriWgtList"`, `"timeAggr"` |
| `apiKey` | string | API key | (your key) |

**Response fields** (per article):

| Field | Description |
|-------|-------------|
| `uri` | Unique article URI within Event Registry |
| `url` | Original article URL |
| `title` | Article title (in original language) |
| `body` | Full article text (in original language) |
| `date` | Publication date (`YYYY-MM-DD`) |
| `dateTime` | Publication datetime (ISO 8601) |
| `dateTimePub` | Alternative publication datetime |
| `lang` | Article language (3-letter ISO 639-3) |
| `isDuplicate` | Boolean: whether this article is a duplicate of another |
| `duplicateList` | URIs of duplicate articles |
| `source` | Source object: `uri`, `title`, `dataType`, `location` |
| `authors` | Array of author objects: `uri`, `name`, `isAgency` |
| `categories` | Array of category objects: `uri`, `label`, `wgt` |
| `concepts` | Array of concept objects: `uri`, `label`, `type` (person/org/loc), `score` |
| `image` | Featured image URL |
| `eventUri` | URI of the event this article belongs to (if clustered) |
| `sentiment` | Sentiment score (-1 to +1) |
| `wgt` | Article importance weight |
| `relevance` | Relevance score for the search query |
| `shares` | Social sharing counts object (Facebook, Twitter, etc.) -- availability varies |

#### Event Search

**Endpoint**: `POST /event/getEvents`

**Description**: Search for events (clusters of articles about the same real-world happening).

**Key parameters**: Similar to article search, plus event-specific filters like `minArticlesInEvent`, `eventLocationUri`.

**Response**: Returns event objects containing: `uri`, `title` (multi-language), `summary`, `date`, `location`, `concepts`, `categories`, `articleCounts` (per language), and links to constituent articles.

#### Suggest Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /suggestConcepts` | Autocomplete for entities (people, orgs, locations) |
| `POST /suggestCategories` | Autocomplete for news categories |
| `POST /suggestNewsSources` | Search for monitored news sources |
| `POST /suggestLocations` | Autocomplete for locations |

#### Additional Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /article/getArticleForAnalysis` | Full NLP analysis of a single article |
| `POST /minuteStreamArticles` | Streaming endpoint for near-real-time article delivery |
| `POST /article/getArticlesForTopicPage` | Articles matching a pre-configured topic page |
| `GET /overview/getTopCorrelations` | Trending topics and correlations |

### Python SDK

**Library**: `eventregistry` (PyPI)
**Installation**: `pip install eventregistry`

The official Python SDK wraps all API endpoints with a high-level interface:

```python
from eventregistry import EventRegistry, QueryArticlesIter
er = EventRegistry(apiKey="YOUR_KEY")
q = QueryArticlesIter(
    keywords="klimaforandringer",
    lang="dan",
    sourceLocationUri=er.getLocationUri("Denmark"),
    dateStart="2026-01-01",
    dateEnd="2026-02-16"
)
for article in q.execQuery(er, sortBy="date"):
    print(article)
```

The `QueryArticlesIter` class handles pagination automatically.

---

## 4. Danish Context

- **Language code**: Event Registry uses ISO 639-3 three-letter codes. Danish is `"dan"`, not `"da"`. The normalizer must map `"dan"` to ISO 639-1 `"da"` for the UCR `language` field.
- **Native NLP**: Unlike GDELT (which machine-translates to English), Event Registry performs entity extraction, categorization, and sentiment analysis on the original Danish text. This means Danish named entities (e.g., "Mette Frederiksen", "Folketing", "Danske Bank") are extracted correctly without translation artifacts.
- **Source location filtering**: Use `sourceLocationUri` set to Denmark's Wikipedia URI to filter articles from Danish sources. This is more reliable than language filtering alone, as some Danish outlets publish in English.
- **Event clustering across languages**: Event Registry's event clustering groups Danish and international articles about the same event. This is valuable for tracking how Danish stories receive international coverage and vice versa.
- **Danish source coverage**: The `suggestNewsSources` endpoint filtered by Denmark should be queried at implementation time to verify which Danish outlets are monitored. Major outlets (DR, TV2, Berlingske, Politiken, JP, BT, Ekstra Bladet, Information) are expected to be present.
- **Keyword search in Danish**: Keyword search operates on the original article text. Danish search terms (e.g., `klimaforandringer`, `sundhedsvaesenet`, `flygtningepolitik`) work directly without requiring English translation, unlike GDELT.
- **Concept URIs for Danish entities**: Use `suggestConcepts` to find the correct Wikipedia-based URIs for Danish entities. For example, searching for "Mette Frederiksen" returns the concept URI that can be used for precise entity-based filtering.

---

## 5. Data Fields

Mapping to the Universal Content Record schema:

| UCR Field | Event Registry Source | Notes |
|-----------|----------------------|-------|
| `platform` | `"event_registry"` | Constant |
| `arena` | `"news_media"` | Constant |
| `platform_id` | `uri` | Event Registry's unique article URI |
| `content_type` | `"article"` | Constant |
| `text_content` | `body` | Full article text in original language. Major advantage over GDELT and RSS. |
| `title` | `title` | In original language (Danish for Danish articles) |
| `url` | `url` | Original article URL |
| `language` | `lang` | Map from ISO 639-3 (`"dan"`) to ISO 639-1 (`"da"`) |
| `published_at` | `dateTime` or `dateTimePub` | ISO 8601 format. Prefer `dateTimePub` when available. |
| `collected_at` | Now | Standard |
| `author_platform_id` | `authors[0].uri` | First author URI, if present |
| `author_display_name` | `authors[0].name` | First author name, if present. May be journalist name or agency name. |
| `views_count` | `NULL` | Not directly available |
| `likes_count` | `NULL` | Not available |
| `shares_count` | `shares.facebook` or total | Social share counts, if available. Availability varies by article. Store as `raw_metadata`. |
| `comments_count` | `NULL` | Not available |
| `engagement_score` | `wgt` | Article importance weight can serve as a proxy. Store in `raw_metadata` as well. |
| `raw_metadata` | Full article object | Store: `eventUri`, `sentiment`, `wgt`, `relevance`, `isDuplicate`, `duplicateList`, `categories`, `concepts`, `shares`, `source`, `authors`, `image` |
| `media_urls` | `[image]` | Featured image URL, if present |
| `content_hash` | SHA-256 of normalized URL | URL-based dedup. Also use `isDuplicate` flag and `eventUri` for Event Registry's own deduplication. |

**Key advantage**: Event Registry provides `body` (full article text), `concepts` (extracted entities with types and scores), `categories` (topic classification), `sentiment` (article-level), and `eventUri` (event clustering). These are stored in `raw_metadata` and provide substantially richer metadata than GDELT or RSS.

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Medium | `{"api_key": "newsapi_ai_key"}` | `"event_registry"` |
| Premium | `{"api_key": "newsapi_ai_key"}` | `"event_registry"` |

Same credential format for both tiers. The tier distinction is determined by the subscription plan associated with the API key, not by anything in the credential itself.

---

## 7. Rate Limits and Multi-Account Notes

| Tier | Rate Limit | Token Budget | Notes |
|------|-----------|--------------|-------|
| Medium (Starter) | Not formally published; ~10 req/sec empirically | 5,000 tokens/month | 1 token per article search request (up to 100 results) |
| Premium (Business) | Not formally published; ~10 req/sec empirically | 50,000 tokens/month | Same per-request cost, higher monthly budget |

**Token tracking**: The API returns remaining token count in response headers or response body. The collector should track token consumption and pause collection when approaching the monthly limit. Expose remaining tokens in the admin health dashboard.

**Multi-account**: Multiple API keys can be pooled via `CredentialPool` to increase effective monthly token budgets. Each subscription is independent. This is a straightforward way to scale if 5,000 tokens/month is insufficient.

**RateLimiter configuration**: Configure at ~5 requests per second to stay well within empirical limits. Token budget enforcement is more important than rate limiting for this arena.

> WARNING: Exact rate limits are not published in Event Registry documentation. The ~10 req/sec figure is based on community reports. Implement adaptive backoff on HTTP 429 responses.

---

## 8. Known Limitations

1. **Token budget is the primary constraint**: Unlike free arenas, Event Registry has a hard monthly token budget. At 5,000 tokens/month (Medium), and ~1 token per search request returning up to 100 articles, the collector can execute approximately 5,000 searches per month. For targeted Danish issue tracking this is sufficient; for broad monitoring across many query designs, the Premium tier or multi-key pooling may be necessary.

2. **No free tier for production use**: Trial accounts are limited and temporary. This arena cannot operate at the free tier. Budget allocation is required.

3. **Article body availability**: While Event Registry provides `body` (full text), some paywalled outlets may provide only partial text. The amount of text available depends on what the source outlet exposes in its RSS feed or web page. This is not an Event Registry limitation per se, but a source-level constraint.

4. **Social sharing counts**: The `shares` field (Facebook, Twitter share counts) is present on some articles but not all. Do not rely on this for engagement analysis. Treat as supplementary metadata.

5. **Sentiment score quality for Danish**: Event Registry performs sentiment analysis on original-language text. However, the quality of Danish sentiment analysis has not been independently validated for this project. Consider the sentiment score as indicative, not authoritative.

6. **Event clustering lag**: Event clustering (assigning articles to events) may lag behind article ingestion. A newly published article may not have an `eventUri` immediately. Re-fetching articles after 1-2 hours can fill in event assignments.

7. **ISO 639-3 language codes**: Event Registry uses 3-letter language codes (`dan`, `eng`, `swe`) rather than the 2-letter ISO 639-1 codes used in the UCR schema. The normalizer must perform this mapping.

8. **Duplicate detection**: Event Registry flags articles as duplicates (`isDuplicate: true`) when they are near-copies. The `duplicateList` field contains URIs of duplicates. Decide at collection time whether to ingest duplicates (storing the flag for analysis) or filter them out.

9. **Legal considerations**: Event Registry is a commercial service that aggregates published news content. Using it for academic research is within the terms of service. GDPR considerations: article metadata (journalist names, source outlets) is professional information from published content. Apply `pseudonymized_author_id` for consistency but journalist bylines in published articles do not require special GDPR treatment. Full article text may contain personal data (names of individuals mentioned in articles) -- this falls under the Art. 89 research exemption documented in the DPIA.

10. **API endpoint stability**: Event Registry has been operational since 2014 and maintains backward compatibility. However, the `eventregistry.org` domain and the `newsapi.ai` domain currently both work. Monitor for any migration announcements.

---

## 9. Collector Implementation Notes

### Architecture

- **Primary collection**: `collect_by_terms` using the `getArticles` endpoint with keyword and Danish language/source filters.
- **Secondary**: `collect_by_actors` by mapping actors to concept URIs (via `suggestConcepts`) and using `conceptUri` filters.
- **Event enrichment**: After collecting articles, optionally fetch event details for articles that have `eventUri` set, to get event-level metadata (cross-language coverage, total article counts).

### Key Implementation Guidance

1. **Query construction**: Translate query design search terms to Event Registry keyword queries. Combine with `lang="dan"` and/or `sourceLocationUri` for Denmark. Use `conceptUri` for entity-based queries (more precise than keyword matching).

2. **Pagination**: Use `QueryArticlesIter` from the Python SDK for automatic pagination, or manually increment `articlesPage`. Each page request costs 1 token.

3. **Token budget management**:
   - Track tokens consumed per collection run in `credit_transactions`.
   - Map 1 Event Registry token = 1 credit in the credit system.
   - Implement a hard stop when monthly token budget is exhausted.
   - The API returns remaining token count -- use this as the authoritative budget tracker.

4. **Deduplication strategy**:
   - Primary: `platform_id` (article URI) uniqueness in the database.
   - Secondary: Check `isDuplicate` flag. Decide per query design whether to skip duplicates.
   - Cross-arena: Articles from Event Registry will overlap with RSS feed and GDELT records for the same articles. Use `content_hash` (SHA-256 of normalized URL) for cross-arena dedup.

5. **Polling strategy**:
   - For live tracking: poll every 30-60 minutes with `dateStart` set to the last successful collection time.
   - For batch collection: iterate over date ranges with `dateStart`/`dateEnd`, paginating through results.
   - The `minuteStreamArticles` endpoint offers near-real-time delivery but consumes tokens continuously. Evaluate cost-effectiveness before enabling.

6. **Concept URI resolution**: Use `suggestConcepts` to resolve actor names to concept URIs at query design creation time. Cache the mappings. This enables precise entity-based search rather than keyword matching.

7. **Language code mapping**: Map Event Registry's ISO 639-3 codes to ISO 639-1 in the normalizer:
   - `"dan"` -> `"da"` (Danish)
   - `"eng"` -> `"en"` (English)
   - `"swe"` -> `"sv"` (Swedish)
   - `"nob"` -> `"nb"` (Norwegian Bokmal)

8. **Health check**: Execute a simple article search (e.g., `keyword="Denmark"`, `lang="dan"`, `articlesCount=1`) and verify a valid JSON response with at least one article. Also check remaining token count.

9. **Credit cost**: 1 credit per API request (1 token). A search returning 100 articles costs 1 credit. Budget accordingly.

10. **Error handling**: The API returns structured error responses with error codes. Handle:
    - `402`: Token budget exhausted (stop collection, alert admin)
    - `429`: Rate limit exceeded (backoff and retry)
    - `401`: Invalid API key (mark credential as errored in pool)
    - `5xx`: Server errors (retry with exponential backoff)

11. **Storing NLP enrichments**: The `concepts`, `categories`, and `sentiment` fields from Event Registry are high-value metadata. Store the full arrays in `raw_metadata.concepts`, `raw_metadata.categories`, and `raw_metadata.sentiment` for downstream analysis. Consider creating GIN-indexed JSONB paths for frequently queried concept types.
