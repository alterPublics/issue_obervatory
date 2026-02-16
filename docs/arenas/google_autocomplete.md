# Arena Research Brief: Google Autocomplete

**Created**: 2026-02-16
**Last updated**: 2026-02-16
**Status**: Ready for implementation
**Phase**: 1 (Task 1.4, Critical priority)
**Arena path**: `src/issue_observatory/arenas/google_autocomplete/`

---

## 1. Platform Overview

Google Autocomplete (also called Google Suggest) provides real-time search suggestions as users type queries. It reflects what people are searching for and is shaped by trending topics, search volume, and Google's content policies. For Danish public discourse research, autocomplete suggestions reveal what topics are salient in the Danish search landscape at any given moment. Tracking suggestion changes over time provides a unique signal for issue emergence and salience shifts.

There is **no official Google Autocomplete API**. Collection relies on either an undocumented Google endpoint or third-party SERP services.

**Role in Danish discourse**: Google is the dominant search engine in Denmark (>90% market share). Autocomplete suggestions in Danish (`hl=da`, `gl=dk`) directly reflect Danish search behavior and issue salience. No commercial service tracks autocomplete suggestion changes over time, making a scheduled polling system the recommended approach.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | Undocumented Google endpoint (`suggestqueries.google.com`) | $0 | No authentication. Google blocks excessive querying. No published rate limits. Unreliable for sustained collection. |
| **Medium** | Serper.dev autocomplete | $0.30-$1.00 per 1K queries | Autocomplete included as a search type at standard pricing. 2,500 free queries on signup. No subscription required. |
| **Premium** | SerpAPI autocomplete | $2.75-$25.00 per 1K queries | Dedicated autocomplete endpoint. 1-hour caching (cached queries free). 0.26-1.3 sec response. U.S. Legal Shield. |

**Recommendation**: Start with Free tier for low-volume exploratory work. Use Medium (Serper.dev) for sustained collection. Premium (SerpAPI) justified only if the caching benefit and legal shield are needed.

---

## 3. API/Access Details

### Free Tier: Undocumented Endpoint

**Endpoint**: `https://suggestqueries.google.com/complete/search`

**Parameters**:
| Parameter | Value | Description |
|-----------|-------|-------------|
| `q` | search query | The partial query to get suggestions for |
| `client` | `firefox` or `chrome` | Response format (`firefox` returns JSON array) |
| `hl` | `da` | Interface/suggestion language (Danish) |
| `gl` | `dk` | Geolocation (Denmark) |

**Authentication**: None required.

**Response format** (client=firefox):
```json
["query", ["suggestion 1", "suggestion 2", "suggestion 3", ...]]
```

**Rate limits**: Unpublished. Google will block IPs making excessive requests. Empirically, keeping requests under 1 per second per IP is generally safe, but there is no guarantee. Blocking behavior may vary without notice.

### Medium Tier: Serper.dev

**Endpoint**: `POST https://google.serper.dev/autocomplete`

**Authentication**: API key in `X-API-KEY` header.

**Request body**:
```json
{
  "q": "klimaforandringer",
  "gl": "dk",
  "hl": "da"
}
```

**Response**: JSON with suggestions array including suggestion text and relevance scores.

**Rate limits**: 300 queries/second (shared across all endpoints). No daily cap beyond purchased credits.

**Latency**: 1-2 seconds.

### Premium Tier: SerpAPI

**Endpoint**: `GET https://serpapi.com/search?engine=google_autocomplete`

**Authentication**: API key as `api_key` query parameter.

**Parameters**:
| Parameter | Value | Description |
|-----------|-------|-------------|
| `q` | query | Partial search query |
| `hl` | `da` | Language |
| `gl` | `dk` | Country |

**Response**: JSON with `suggestions` array, each containing `value`, `relevance`, and `type` fields.

**Rate limits**: Plan-dependent. Developer: 100 searches/month. Business: 5,000/month. Enterprise: 15,000/month.

**Caching**: 1-hour cache. Repeated identical queries within the cache window are free (do not count against quota).

**Latency**: 0.26-1.3 seconds.

---

## 4. Danish Context

- **`hl=da`**: Sets suggestion language to Danish. Critical for getting Danish-language suggestions rather than English defaults.
- **`gl=dk`**: Sets geolocation to Denmark. Ensures suggestions reflect Danish search trends.
- Both parameters must be set together for accurate Danish autocomplete data.
- Autocomplete suggestions are influenced by the user's location, language settings, trending searches in Denmark, and Google's content policies (which filter out certain suggestions).
- Danish special characters (ae, oe, aa / danish letters) are handled correctly by all three tiers.

---

## 5. Data Fields

Mapping to the Universal Content Record schema:

| UCR Field | Autocomplete Source | Notes |
|-----------|-------------------|-------|
| `platform` | `"google"` | Constant |
| `arena` | `"google_autocomplete"` | Constant |
| `platform_id` | SHA-256 of `query + suggestion + timestamp` | No native ID; generate deterministic hash |
| `content_type` | `"autocomplete_suggestion"` | Custom content type |
| `text_content` | Suggestion text | The autocomplete suggestion string |
| `title` | Input query | The partial query that generated these suggestions |
| `url` | `NULL` | No URL associated |
| `language` | `"da"` | From `hl` parameter |
| `published_at` | Collection timestamp | No native publish date; use collection time |
| `collected_at` | Now | Standard |
| `author_platform_id` | `NULL` | No author concept |
| `author_display_name` | `NULL` | No author concept |
| `views_count` | `NULL` | Not available |
| `likes_count` | `NULL` | Not available |
| `shares_count` | `NULL` | Not available |
| `comments_count` | `NULL` | Not available |
| `engagement_score` | Relevance score (if available) | SerpAPI and Serper return relevance; undocumented endpoint does not |
| `raw_metadata` | Full API response | Store rank position, relevance score, query parameters used |
| `content_hash` | SHA-256 of normalized suggestion text | For deduplication |

**Note**: The `raw_metadata` JSONB field should store:
- `query`: the input query that generated the suggestion
- `rank`: position in the suggestion list (0-indexed)
- `relevance`: relevance score (when available from paid tiers)
- `gl`: geolocation parameter used
- `hl`: language parameter used
- `tier`: which service tier was used

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Free | None required | N/A (no credential needed) |
| Medium | `{"api_key": "serper_api_key_value"}` | `"serper"` |
| Premium | `{"api_key": "serpapi_api_key_value"}` | `"serpapi"` |

**Note**: Serper.dev and SerpAPI credentials are shared with the Google Search arena. The CredentialPool should use `platform="serper"` or `platform="serpapi"` (not `platform="google_autocomplete"`) so credentials are shared across both arenas. Quota tracking must account for usage from both arenas against the same credential.

---

## 7. Rate Limits and Multi-Account Notes

| Tier | Rate Limit | Daily Cap | Monthly Cap | Multi-Account Benefit |
|------|-----------|-----------|-------------|----------------------|
| Free | ~1 req/sec (empirical, unpublished) | Unknown | Unknown | Rotating IPs helps but is unreliable |
| Medium (Serper) | 300 req/sec | No hard cap | Credit-based | Multiple API keys increase throughput. Each key has its own credit balance. |
| Premium (SerpAPI) | Plan-dependent | Plan-dependent | 100-15,000+ depending on plan | Multiple accounts multiply quota. Caching reduces effective usage. |

**CredentialPool configuration**:
- For Free tier: No credential rotation needed, but consider rotating through proxy IPs if rate-limited.
- For Medium/Premium: Standard API key rotation via CredentialPool. Set `daily_quota` on each credential to match the plan limit.
- Serper.dev is credit-based (not subscription), so `monthly_quota` should track remaining credit balance.

---

## 8. Known Limitations

1. **No historical data**: Autocomplete reflects current suggestions only. There is no way to retrieve what suggestions were shown yesterday. This makes consistent polling intervals essential for longitudinal tracking.

2. **Undocumented endpoint instability**: The free endpoint (`suggestqueries.google.com`) has no SLA, no documentation, and Google can change or block it at any time. It should not be the sole collection method for production use.

3. **Suggestion filtering**: Google actively filters autocomplete suggestions, removing those related to violence, hate speech, explicit content, and certain politically sensitive topics. This means autocomplete data has a systematic bias -- it does not represent all search queries, only those Google permits in suggestions.

4. **Caching and personalization**: Suggestions may vary by IP address, browser state, and Google account. Using consistent parameters (`hl=da`, `gl=dk`) and no authentication helps but does not guarantee identical results across requests.

5. **No engagement metrics**: Unlike other arenas, autocomplete provides no views, likes, or shares. The only available signal is rank position and relevance score (paid tiers only).

6. **Legal considerations**: All third-party SERP services technically violate Google's Terms of Service. Legal precedent (hiQ v. LinkedIn, X Corp v. Bright Data) favors scrapers, and SerpAPI offers a U.S. Legal Shield, but this remains a grey area. The undocumented endpoint is accessed directly and carries similar ToS risk. GDPR is not a concern for this arena -- autocomplete suggestions are not personal data.

7. **Deduplication complexity**: The same suggestion may appear across multiple polling intervals. Use `content_hash` on normalized suggestion text combined with a time window to avoid storing duplicate entries while still capturing when suggestions change.

---

## 9. Collector Implementation Notes

### Architecture

- **Content type**: `autocomplete_suggestion` (distinct from search results)
- **Collection mode**: Primarily `collect_by_terms` -- each search term in the query design generates a set of autocomplete suggestions. `collect_by_actors` is not applicable for this arena.
- **Polling strategy**: For live tracking, poll at regular intervals (e.g., every 6 hours for each term). Store all suggestions with timestamps to build a time series of suggestion changes.

### Key Implementation Guidance

1. **Tier fallback**: Implement graceful fallback from Free to Medium tier. If the undocumented endpoint returns errors or blocks, automatically switch to Serper.dev if credentials are available.

2. **Deduplication logic**: Compare new suggestions against the most recent set for the same query. Only create new records when suggestions change (new suggestion appears, suggestion disappears, or rank order changes). Store unchanged polls as a heartbeat in `raw_metadata` without creating new content records.

3. **Query expansion**: For each search term in the query design, consider generating partial query prefixes (e.g., for "klimaforandringer", also query "klimaforandringer ", "klimaforandringer d", etc.) to capture a wider range of suggestions. This multiplies API calls, so tier and credit budget must be considered.

4. **Shared credentials**: The collector must request credentials from CredentialPool using `platform="serper"` or `platform="serpapi"`, not a platform-specific string. Coordinate with the Google Search arena to avoid double-counting quota.

5. **Response parsing**: Each tier returns suggestions in a different format. The normalizer must handle all three:
   - Free: JSON array `["query", ["sug1", "sug2", ...]]`
   - Serper: JSON object with suggestions array
   - SerpAPI: JSON object with `suggestions` list of objects

6. **Health check**: Test the undocumented endpoint with a simple query (`q=test&client=firefox&hl=da&gl=dk`). For paid tiers, verify API key validity and remaining quota.

7. **Credit cost mapping**: 1 credit = 1 autocomplete query (for both Serper and SerpAPI). This matches the credit system defined in IMPLEMENTATION_PLAN.md.
