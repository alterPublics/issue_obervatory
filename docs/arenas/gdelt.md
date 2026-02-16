# Arena Research Brief: GDELT

**Created**: 2026-02-16
**Last updated**: 2026-02-16
**Status**: Ready for implementation
**Phase**: 1 (Task 1.9, High priority)
**Arena path**: `src/issue_observatory/arenas/news_media/gdelt/`

---

## 1. Platform Overview

GDELT (Global Database of Events, Language, and Tone) monitors hundreds of thousands of news sources across 65 machine-translated languages, updating every 15 minutes. It provides free API access to event data, article metadata, and global knowledge graph data. GDELT is the strongest free option for global news monitoring, though its Danish coverage has known quality limitations.

**Role in Danish discourse**: GDELT provides a complementary signal to the RSS feeds arena. While RSS feeds cover specific curated Danish outlets, GDELT captures international coverage of Danish topics, cross-language mentions of Denmark, and articles from smaller Danish outlets not in the RSS feed list. However, GDELT's Danish coverage quality is limited: overall key field accuracy is estimated at ~55%, with ~20% data redundancy. Danish content is machine-translated to English, introducing translation artifacts. GDELT is best used for trend detection and volume signals, not for precise Danish-language text analysis.

**Access model**: Entirely free. DOC API for full-text search. BigQuery for SQL-based analysis (free within Google's 1 TB/month tier). No authentication required for DOC API.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | GDELT DOC API + BigQuery | $0 | DOC API: no auth, rolling 3-month window. BigQuery: 1 TB/month free tier. |
| **Medium** | N/A | -- | No medium tier. |
| **Premium** | N/A | -- | No premium tier. |

GDELT is a free-only arena.

---

## 3. API/Access Details

### GDELT DOC 2.0 API

**Base URL**: `https://api.gdeltproject.org/api/v2/doc/doc`

**Method**: GET

**Key Parameters**:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `query` | Search query (Boolean operators supported) | `klimaforandringer OR "climate change"` |
| `mode` | Response mode | `artlist` (article list), `artgallery`, `timelinevolraw`, `timelinevol`, `timelinetone`, `timelinelang` |
| `sourcecountry` | Filter by source country (FIPS code) | `DA` (Denmark) |
| `sourcelang` | Filter by source language | `danish` |
| `startdatetime` | Start of date range | `20260101000000` (YYYYMMDDHHmmss) |
| `enddatetime` | End of date range | `20260216235959` |
| `maxrecords` | Max articles returned | `250` (max 250 per request) |
| `format` | Response format | `json` or `html` |
| `sort` | Sort order | `dateadded`, `toneasc`, `tonedesc`, `hybridrel` |

**Response fields** (artlist mode):

| Field | Description |
|-------|-------------|
| `url` | Article URL |
| `url_mobile` | Mobile URL (if different) |
| `title` | Article title (may be translated to English) |
| `seendate` | Date GDELT first observed the article (YYYYMMDDTHHmmss) |
| `socialimage` | Featured image URL |
| `domain` | Source domain |
| `language` | Detected source language |
| `sourcecountry` | Source country |
| `tone` | Sentiment tone score (-100 to +100) |

**Important**: The DOC API provides a **rolling 3-month window**. Queries beyond 3 months into the past return no results. For historical analysis beyond 3 months, use BigQuery.

**Rate limits**: Not formally published. GDELT documentation states the API is free and open. Empirically, keep requests to ~1 per second. Excessive querying may result in temporary IP blocks. No authentication means no per-account quota tracking.

### GDELT on Google BigQuery

**Dataset**: `gdeltv2` (public dataset)

**Key tables**:
- `gdeltv2.events` -- Event records (300+ event categories, CAMEO coding)
- `gdeltv2.eventmentions` -- Event mention records linking events to articles
- `gdeltv2.gkg` -- Global Knowledge Graph (people, organizations, themes, locations, tone)

**Danish filtering in BigQuery**:
```sql
SELECT * FROM `gdelt-bq.gdeltv2.events`
WHERE SourceCommonName LIKE '%dk%'
  OR Actor1Geo_CountryCode = 'DA'
  OR ActionGeo_CountryCode = 'DA'
```

**Cost**: Free within Google BigQuery's 1 TB/month free query tier. Beyond that, $6.25/TB.

### Additional APIs

| API | Description | URL Pattern |
|-----|-------------|-------------|
| GEO API | Geographic mentions | `https://api.gdeltproject.org/api/v2/geo/geo` |
| TV API | Television news monitoring | `https://api.gdeltproject.org/api/v2/tv/tv` |
| Context API | Sentence-level co-occurrence | Part of GKG system |

---

## 4. Danish Context

- **`sourcelang:danish`**: Primary filter for Danish-language content in the DOC API. This filters by detected source language.
- **`sourcecountry:DA`**: Filters by source country (Denmark uses FIPS code `DA`, not ISO `DK`). Use in combination with `sourcelang` for best results.
- **Translation artifacts**: GDELT machine-translates all non-English content to English for processing. Danish titles and themes may appear in translated English form. This means:
  - The `title` field may be in English even for Danish articles
  - Named entity extraction may produce English transliterations of Danish names
  - Sentiment/tone scores are computed on translated text, which may not preserve Danish rhetorical nuances
- **Coverage quality**: Estimated ~55% accuracy for key fields. ~20% data redundancy (same event counted multiple times). Danish content is a small fraction of GDELT's total volume.
- **Source list**: GDELT does not publish which Danish sources it monitors. Coverage verification is impossible without empirical testing. DR, TV2, and major outlets are likely included, but smaller regional outlets may not be.
- **FIPS vs ISO country codes**: GDELT uses FIPS 10-4 country codes, not ISO 3166. Denmark = `DA` (FIPS), not `DK` (ISO). This is a common gotcha.

---

## 5. Data Fields

Mapping to the Universal Content Record schema:

| UCR Field | GDELT Source | Notes |
|-----------|-------------|-------|
| `platform` | `"gdelt"` | Constant |
| `arena` | `"news_media"` | Constant |
| `platform_id` | URL hash or GDELT event ID | No unique article ID in DOC API; use SHA-256 of URL |
| `content_type` | `"article"` | Constant for DOC API results |
| `text_content` | `title` | GDELT does not provide full article text, only title and metadata |
| `title` | `title` | May be machine-translated to English |
| `url` | `url` | Source article URL |
| `language` | `language` | GDELT's detected language (e.g., `Danish`) -- map to ISO 639-1 `da` |
| `published_at` | `seendate` | When GDELT first observed the article. Convert from `YYYYMMDDTHHmmss` format. This is observation time, not necessarily publication time. |
| `collected_at` | Now | Standard |
| `author_platform_id` | `NULL` | GDELT does not provide author information |
| `author_display_name` | `domain` | Use source domain as proxy for author/outlet |
| `views_count` | `NULL` | Not available |
| `likes_count` | `NULL` | Not available |
| `shares_count` | `NULL` | Not available |
| `comments_count` | `NULL` | Not available |
| `engagement_score` | `NULL` | Not available |
| `raw_metadata` | Full GDELT response fields | Store: `tone`, `domain`, `sourcecountry`, `socialimage`, `url_mobile`, `language`, CAMEO event codes and GKG themes (if enriched via BigQuery) |
| `media_urls` | `[socialimage]` | Featured image URL |
| `content_hash` | SHA-256 of normalized URL | URL-based dedup (same URL = same article) |

**Note**: GDELT's primary value is metadata (URL, domain, tone, timing) rather than content. Full text must be fetched separately by visiting the article URL, which is out of scope for this arena.

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Free (DOC API) | None | N/A |
| Free (BigQuery) | `{"service_account_json": "..."}` | `"bigquery"` (shared across arenas that use BigQuery) |

No credentials needed for the DOC API. BigQuery requires a Google Cloud service account with BigQuery read access to the public `gdeltv2` dataset.

---

## 7. Rate Limits and Multi-Account Notes

| Access Method | Rate Limit | Daily Cap | Notes |
|---------------|-----------|-----------|-------|
| DOC API | ~1 req/sec (empirical) | None published | No auth, no per-account tracking. IP-based throttling. |
| BigQuery | Standard BigQuery limits | 1 TB/month free | Per-GCP-project billing |

**Multi-account**: Not applicable for the DOC API (unauthenticated). For BigQuery, each GCP project has its own free tier, but running multiple projects for quota reasons is unnecessary given the 1 TB free tier.

**RateLimiter configuration**: Configure a simple 1-request-per-second limit for the DOC API. No credential rotation needed.

---

## 8. Known Limitations

1. **55% accuracy**: Academic research estimates GDELT's overall key field accuracy at ~55%. This includes event coding, geographic assignment, and actor identification. Use GDELT for volume/trend signals, not for precise content analysis.

2. **~20% data redundancy**: The same event is often counted multiple times across different source articles. Deduplication by URL is essential.

3. **No full text**: The DOC API returns article titles and metadata only. Full text must be fetched by visiting the article URL, which introduces scraping complexity and legal considerations outside this arena's scope.

4. **3-month rolling window**: The DOC API only searches the most recent 3 months. Historical analysis requires BigQuery, which adds complexity and potential cost.

5. **Translation artifacts**: Danish content appears with English-translated titles and themes. This means keyword searches must use English translations of Danish terms to find Danish content, which is counterintuitive and may miss nuances.

6. **Unknown Danish source list**: GDELT does not disclose which Danish outlets it monitors. Coverage gaps are invisible.

7. **`seendate` vs publication date**: GDELT records when it first observed an article, not when it was published. For breaking news, these may differ by minutes to hours.

8. **Outage history**: GDELT experienced an outage in June 2025 (recovered by July 2025). The service has no SLA. Treat as a best-effort data source.

9. **Legal considerations**: GDELT is a public research project. No terms of service restrict academic use. GDPR considerations are minimal -- GDELT provides article metadata, not personal data. The article URLs point to public news articles. No pseudonymization needed for GDELT records.

10. **Tone score reliability**: GDELT's tone analysis is performed on machine-translated English text. Tone scores for Danish content may not accurately reflect the original Danish-language sentiment.

---

## 9. Collector Implementation Notes

### Architecture

- **Primary collection**: DOC API polling for recent articles matching search terms.
- **Supplementary**: BigQuery for historical batch collection and volume analysis.
- **Collection mode**: Primarily `collect_by_terms`. `collect_by_actors` is limited -- GDELT does not track individual authors, but can filter by source domain.

### Key Implementation Guidance

1. **DOC API query construction**:
   - Translate query design search terms to GDELT query format
   - Combine with `sourcelang:danish` and/or `sourcecountry:DA`
   - Example: `query=klimaforandringer sourcelang:danish&mode=artlist&format=json&maxrecords=250`
   - Use Boolean operators for complex queries: `AND`, `OR`, `NOT`, parentheses, quotes

2. **Polling strategy**:
   - GDELT updates every 15 minutes
   - Poll at 15-30 minute intervals for live tracking
   - Use `startdatetime` and `enddatetime` to window queries and avoid re-processing
   - Track the last successful query timestamp per search term

3. **Dual-language search**: Because GDELT translates Danish to English, search with both Danish and English terms:
   - Danish: `klimaforandringer`
   - English: `"climate change"`
   - Combined: `(klimaforandringer OR "climate change") sourcecountry:DA`

4. **Pagination**: The DOC API returns max 250 results per request. For queries with more results, use time-windowing (narrow the date range) rather than pagination (there is no cursor-based pagination).

5. **URL-based deduplication**: Use SHA-256 of the normalized URL as `content_hash`. The same article may appear in multiple GDELT updates as engagement metrics change. Only store the first observation.

6. **BigQuery integration** (optional, for batch):
   - Use Google Cloud Python client (`google-cloud-bigquery`)
   - Query `gdeltv2.events` and `gdeltv2.gkg` tables
   - Filter by Danish actors, locations, or source domains
   - Cost: monitor query bytes processed to stay within 1 TB/month free tier

7. **Language code mapping**: GDELT uses full language names (`Danish`, `English`) rather than ISO 639-1 codes. Map to ISO codes in the normalizer: `"Danish" -> "da"`, `"English" -> "en"`, etc.

8. **FIPS country code mapping**: Map GDELT's FIPS `DA` to ISO `DK` in the normalizer for consistency with the rest of the application.

9. **Health check**: Execute a simple DOC API query (e.g., `query=Denmark&mode=artlist&format=json&maxrecords=1`) and verify a valid JSON response with at least one result.

10. **Credit cost**: 0 credits for all operations (free tier).

11. **Error handling**: GDELT may return HTML error pages instead of JSON on server errors. Check response Content-Type header before parsing. Implement retry with backoff for 5xx errors.
