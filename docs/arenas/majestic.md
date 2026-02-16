# Arena Research Brief: Majestic

**Created**: 2026-02-16
**Last updated**: 2026-02-16
**Status**: Ready for implementation
**Phase**: 2 (Task 2.7, Medium priority)
**Arena path**: `src/issue_observatory/arenas/web/majestic/`

---

## 1. Platform Overview

Majestic (majestic.com) is a specialist backlink intelligence platform that maintains one of the largest link indexes on the web. It provides two core datasets: the **Fresh Index** (updated daily, ~844 billion URLs) covering the last 120 days, and the **Historic Index** (spanning 19+ years, 21.7+ trillion URLs). Majestic's proprietary metrics -- **Trust Flow** (quality of links pointing to a URL/domain, scored 0-100) and **Citation Flow** (volume of links, scored 0-100) -- quantify the authority and influence of web pages and domains. The **Topical Trust Flow** system categorizes linking sites across 800+ topics, enabling analysis of which topical communities link to a given domain.

**Role in Danish discourse**: Majestic occupies a distinct niche in the Issue Observatory. While other arenas collect content (articles, posts, comments), Majestic tracks **how content propagates through the web via hyperlinks**. For Danish discourse research, this enables:

- Mapping which websites link to Danish news outlets and vice versa
- Identifying authority structures in the Danish web ecosystem (which domains are most trusted/cited)
- Tracking backlink growth to specific articles or domains during issue cycles (a spike in backlinks to a DR article indicates broader discourse uptake)
- Detecting when fringe or foreign sites link to Danish content (or vice versa), indicating cross-ecosystem discourse flow
- Analyzing the topical profile of Danish domains (what topics does a domain's linking neighborhood cover?)

Majestic does not provide article text, social engagement metrics, or real-time content. It provides structural metadata about the web graph. This is complementary to all other arenas.

**Access model**: API key included with paid subscription plans. Premium tier only -- there is no free API access. Web UI is available on lower plans but is insufficient for programmatic research.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | N/A | -- | No free tier. A free account provides very limited web UI access (no API). |
| **Medium** | N/A | -- | The Lite plan ($49.99/mo) and Pro plan ($99.99/mo) provide web UI access but insufficient or no API access for programmatic use. |
| **Premium** | Majestic API (Full plan) | $399.99/month | 100 million analysis units/month. Full API access. Required for programmatic collection. |

**Analysis units**: Each API call consumes analysis units based on the amount of data returned. A single `GetBackLinkData` call returning 1,000 rows consumes approximately 1,000 analysis units. The 100M unit monthly budget is generous for targeted domain analysis but can be consumed quickly by broad crawl-style queries.

> WARNING: Pricing is based on publicly available information from majestic.com as of early 2026. The Full API plan has been historically stable at ~$400/month but should be confirmed before subscription.

---

## 3. API/Access Details

### Authentication

**Method**: API key passed as query parameter (`app_api_key`) or in OpenApp authentication flow.

**Obtaining credentials**: Subscribe to the Full API plan at majestic.com. The API key is available in account settings. Majestic also supports OpenApp (OAuth-like) for third-party applications, but API key authentication is simpler for server-side collection.

### Base URL

`https://api.majestic.com/api/json`

Alternative formats: Replace `json` with `xml` or `csv` for different response formats.

### Key API Commands

#### GetIndexItemInfo

**Description**: Get Trust Flow, Citation Flow, backlink counts, and referring domain counts for one or more URLs or domains.

**Parameters**:

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `items` | int | Number of items to analyze | `1` |
| `item0` | string | URL or domain to analyze | `"dr.dk"` |
| `item1`...`itemN` | string | Additional items (batch up to 100) | `"tv2.dk"` |
| `datasource` | string | Index to query | `"fresh"` or `"historic"` |
| `app_api_key` | string | API key | (your key) |

**Response fields**:

| Field | Description |
|-------|-------------|
| `ItemNum` | Item index in the batch |
| `Item` | URL/domain queried |
| `ResultCode` | `"OK"` or error code |
| `Status` | HTTP status observed by Majestic crawler |
| `ExtBackLinks` | Total external backlink count |
| `RefDomains` | Number of unique referring domains |
| `RefSubNets` | Number of unique referring subnets (Class C) |
| `RefIPs` | Number of unique referring IPs |
| `TrustFlow` | Trust Flow score (0-100) |
| `CitationFlow` | Citation Flow score (0-100) |
| `TopicalTrustFlow_Topic_0` | Top topical category |
| `TopicalTrustFlow_Value_0` | Score for top topical category |
| `TrustMetric` | Legacy metric (deprecated, use TrustFlow) |
| `IndexedURLs` | Number of URLs from this domain in the index |
| `AnalysisResUnits` | Analysis units consumed by this call |

#### GetBackLinkData

**Description**: Retrieve individual backlinks pointing to a URL or domain.

**Parameters**:

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `item` | string | URL or domain to get backlinks for | `"dr.dk/nyheder/indland/article123"` |
| `datasource` | string | Index to query | `"fresh"` or `"historic"` |
| `Count` | int | Number of backlinks to return (max 50,000) | `1000` |
| `Mode` | int | `0` = all backlinks, `1` = one per domain, `2` = one per subdomain | `0` |
| `MaxSourceURLs` | int | Max backlinks per source domain | `10` |
| `FilterTopic` | string | Filter by Topical Trust Flow topic | `"News/Magazines"` |
| `FilterTopicExclude` | bool | Exclude the topic instead of include | `false` |
| `RefDomain` | string | Filter backlinks from a specific domain | `"example.com"` |
| `From` | string | Date filter start (YYYY-MM-DD) | `"2026-01-01"` |
| `To` | string | Date filter end | `"2026-02-16"` |

**Response fields per backlink**:

| Field | Description |
|-------|-------------|
| `SourceURL` | URL of the page containing the backlink |
| `TargetURL` | URL being linked to |
| `AnchorText` | Link anchor text |
| `SourceTrustFlow` | Trust Flow of the linking page |
| `SourceCitationFlow` | Citation Flow of the linking page |
| `SourceTopicalTrustFlow_Topic_0` | Topical category of the linking page |
| `FlagNoFollow` | Whether the link is nofollow |
| `FlagRedirect` | Whether the link is a redirect |
| `FlagFrame` | Whether the link is in a frame |
| `FlagOldCrawl` | Whether the link was found in an older crawl |
| `FlagAltText` | Whether anchor text is from image alt attribute |
| `FlagMention` | Whether this is a mention (unlinked URL reference) |
| `FirstIndexedDate` | When Majestic first discovered this backlink |
| `LastSeenDate` | When Majestic last confirmed this backlink exists |
| `DateLost` | When the backlink was lost (if applicable) |
| `ReasonLost` | Reason for loss (page removed, link removed, etc.) |

#### GetRefDomains

**Description**: Get referring domains (unique domains linking to a target).

**Parameters**: Similar to `GetBackLinkData`, but returns domain-level aggregates.

**Response fields per referring domain**:

| Field | Description |
|-------|-------------|
| `Domain` | Referring domain name |
| `TrustFlow` | Trust Flow of the referring domain |
| `CitationFlow` | Citation Flow of the referring domain |
| `TopicalTrustFlow_Topic_0` | Top topic of the referring domain |
| `ExtBackLinks` | Number of backlinks from this domain |
| `FirstSeen` | When links from this domain were first seen |
| `LastSeen` | When links from this domain were last confirmed |

#### Additional Commands

| Command | Description |
|---------|-------------|
| `GetTopBackLinks` | Top backlinks sorted by Trust Flow |
| `GetNewLostBackLinks` | Backlinks gained or lost in a time period |
| `GetAnchorText` | Anchor text distribution for a URL/domain |
| `GetTopicsForURL` | Topical Trust Flow breakdown for a URL/domain |
| `GetSearchResults` | Search Majestic's index by keyword (limited) |

### Python Access

There is no official Majestic Python SDK. Use `requests` directly against the JSON API.

```python
import requests

params = {
    "cmd": "GetIndexItemInfo",
    "items": 2,
    "item0": "dr.dk",
    "item1": "tv2.dk",
    "datasource": "fresh",
    "app_api_key": "YOUR_KEY"
}
response = requests.get("https://api.majestic.com/api/json", params=params)
data = response.json()
```

---

## 4. Danish Context

- **Domain-centric analysis**: Majestic is most useful when analyzing specific Danish domains. Maintain a curated list of Danish news domains, political party domains, government domains (.dk TLD), and organization domains as targets for backlink analysis.
- **Danish TLD coverage**: The `.dk` TLD is well-indexed by Majestic. Filtering by TLD or by known Danish domains is the primary mechanism for Danish focus (there is no language filter in the Majestic API -- it indexes URLs, not text content).
- **No language filtering**: Majestic indexes the web graph structure (who links to whom), not page content. There is no `lang=da` parameter. Danish focus is achieved by querying Danish domains as targets or sources.
- **Topical Trust Flow for Danish sites**: Querying the topical profile of Danish domains reveals their position in the global web's topical structure. A Danish news outlet with high Trust Flow in "News/Magazines" and "Society/Politics" confirms its role as a discourse authority.
- **Cross-ecosystem tracking**: Majestic can reveal when international or fringe sites begin linking to Danish news articles, indicating cross-border discourse flow. This is particularly relevant for tracking disinformation or foreign influence narratives referencing Danish media.
- **Historical baseline**: The Historic Index (19+ years) enables establishing baseline link profiles for Danish domains, against which sudden changes (link spikes, new referring domains) can be detected during issue tracking.

---

## 5. Data Fields

Majestic data maps to the Universal Content Record schema in a non-standard way. Majestic does not provide content (articles, posts) -- it provides link relationship data. The mapping below treats each **backlink relationship** as a content record of type `"backlink"`.

| UCR Field | Majestic Source | Notes |
|-----------|----------------|-------|
| `platform` | `"majestic"` | Constant |
| `arena` | `"web"` | Constant |
| `platform_id` | Hash of `SourceURL + TargetURL` | No native unique ID; generate from the link pair |
| `content_type` | `"backlink"` | New content type for this arena |
| `text_content` | `AnchorText` | The anchor text of the link. May be empty for image links. |
| `title` | `NULL` | Majestic does not provide page titles |
| `url` | `TargetURL` | The URL being linked to (the subject of analysis) |
| `language` | `NULL` | Majestic does not detect language |
| `published_at` | `FirstIndexedDate` | When Majestic first discovered the link. Not the same as when the link was actually created, but the best available proxy. |
| `collected_at` | Now | Standard |
| `author_platform_id` | `NULL` | No author concept in backlink data |
| `author_display_name` | Domain of `SourceURL` | Use the linking domain as a proxy for "author" |
| `views_count` | `NULL` | Not available |
| `likes_count` | `NULL` | Not available |
| `shares_count` | `NULL` | Not available |
| `comments_count` | `NULL` | Not available |
| `engagement_score` | `SourceTrustFlow` | Trust Flow of the linking page serves as an authority/quality proxy |
| `raw_metadata` | Full backlink record | Store: `SourceURL`, `TargetURL`, `SourceTrustFlow`, `SourceCitationFlow`, `SourceTopicalTrustFlow_Topic_0`, `FlagNoFollow`, `FlagRedirect`, `FirstIndexedDate`, `LastSeenDate`, `DateLost`, `ReasonLost`, `AnchorText` |
| `media_urls` | `[]` | Not applicable |
| `content_hash` | SHA-256 of `SourceURL + TargetURL` | Dedup on the link pair |

**Alternative mapping for domain-level data**: When using `GetIndexItemInfo` to track domain metrics over time, store as `content_type="domain_metrics"` with the domain as `url`, Trust Flow/Citation Flow in `raw_metadata`, and `collected_at` as the timestamp. This creates a time series of domain authority.

| UCR Field | Source (domain metrics) | Notes |
|-----------|------------------------|-------|
| `platform` | `"majestic"` | Constant |
| `platform_id` | `domain + "_" + date` | Domain name + collection date |
| `content_type` | `"domain_metrics"` | New content type |
| `url` | Domain URL | e.g., `"https://dr.dk"` |
| `raw_metadata` | Full index item info | `TrustFlow`, `CitationFlow`, `ExtBackLinks`, `RefDomains`, `TopicalTrustFlow_*`, `IndexedURLs` |

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Premium | `{"api_key": "majestic_api_key"}` | `"majestic"` |

Only one credential type. The API key is tied to the Full API subscription.

---

## 7. Rate Limits and Multi-Account Notes

| Tier | Rate Limit | Monthly Cap | Notes |
|------|-----------|-------------|-------|
| Premium (Full API) | Not formally published; ~1 req/sec recommended | 100 million analysis units | Units consumed vary by command and data volume |

**Analysis unit consumption examples**:
- `GetIndexItemInfo` for 1 domain: ~1 unit
- `GetIndexItemInfo` batch of 100 domains: ~100 units
- `GetBackLinkData` returning 1,000 rows: ~1,000 units
- `GetBackLinkData` returning 50,000 rows: ~50,000 units
- `GetNewLostBackLinks` for a popular domain: varies by volume

**Multi-account**: Multiple Majestic Full API subscriptions can be pooled via `CredentialPool` if the 100M unit budget is insufficient. However, at $400/month per subscription, this is expensive. For most Danish discourse research use cases, a single subscription should suffice.

**RateLimiter configuration**: Configure at 1 request per second. Majestic's API is not designed for high-frequency polling -- it is a batch analysis tool, not a real-time feed.

---

## 8. Known Limitations

1. **Premium-only access**: At $399.99/month, Majestic is the most expensive single-arena subscription in the Issue Observatory. Justify the cost based on specific research questions that require backlink/authority analysis.

2. **No content**: Majestic provides link graph data, not article text. It answers "who links to whom" and "how authoritative are they," not "what did they say." It must be used in conjunction with content-providing arenas (RSS, Event Registry, GDELT).

3. **No language filtering**: The API operates on URLs and domains, not on text content. Danish focus must be achieved through domain curation, not language parameters.

4. **Crawl latency**: The Fresh Index updates daily, but Majestic's crawler may not visit every page daily. A new backlink to a Danish article may take 1-7 days to appear in the Fresh Index. The Historic Index updates less frequently.

5. **FirstIndexedDate is not creation date**: `FirstIndexedDate` reflects when Majestic's crawler first discovered the link, not when the linking page was published or the link was added. For recently created links, these are typically close; for older links, there may be significant lag.

6. **No real-time monitoring**: Majestic does not support streaming, webhooks, or push notifications for new backlinks. All collection is poll-based. For near-real-time backlink alerts, implement periodic `GetNewLostBackLinks` queries (e.g., daily).

7. **Analysis unit budget management**: Unlike token-based APIs where each request costs a fixed amount, Majestic's unit cost scales with the volume of data returned. A single query against a high-traffic domain can consume hundreds of thousands of units. Implement budget guards.

8. **Legal considerations**: Majestic's data is derived from public web crawling, similar to search engines. No ToS restrictions on using API data for research. GDPR considerations are minimal -- backlink data is about URLs and domains, not personal data. Anchor text may occasionally contain personal names (e.g., a link with text "Interview with [Person Name]"), but this is published web content covered by the Art. 89 research exemption. No special pseudonymization required beyond standard UCR handling.

9. **API response format**: The JSON response uses a flat structure with numbered fields (e.g., `TopicalTrustFlow_Topic_0`, `TopicalTrustFlow_Value_0`, `TopicalTrustFlow_Topic_1`, etc.) rather than arrays. The normalizer must handle this non-standard format.

10. **No official Python SDK**: Unlike Event Registry, Majestic does not provide an official Python library. The collector must use `requests` directly. This increases implementation effort but provides full control over request construction.

---

## 9. Collector Implementation Notes

### Architecture

- **Primary collection mode**: Neither `collect_by_terms` nor `collect_by_actors` maps cleanly to Majestic's model. Majestic operates on **URLs and domains**, not on search terms or user accounts. Implement two collection strategies:
  1. **Domain monitoring**: Periodically query `GetIndexItemInfo` for a curated list of Danish domains to track Trust Flow and backlink count changes over time.
  2. **Backlink analysis**: Query `GetBackLinkData` and `GetNewLostBackLinks` for specific URLs or domains of interest (e.g., articles identified by other arenas as high-engagement).

- **Integration with other arenas**: The Majestic collector is most valuable when triggered by signals from other arenas. For example: when the RSS or Event Registry arena detects a high-volume article, the Majestic collector can query backlinks to that article's URL to track web-level propagation.

### Key Implementation Guidance

1. **Domain list curation**: Maintain a configurable list of Danish domains to monitor in `danish_defaults.py` or a configuration table. Include:
   - Major news outlets: `dr.dk`, `tv2.dk`, `berlingske.dk`, `politiken.dk`, `jp.dk`, `bt.dk`, `eb.dk`, `information.dk`
   - Government: `stm.dk`, `ft.dk`, `regeringen.dk`
   - Political parties: party websites
   - Research/advocacy: relevant organizations
   - The list should be extensible via the query design's actor list (map actors to domains).

2. **Polling strategy**:
   - Domain metrics (`GetIndexItemInfo`): Weekly. Domain-level metrics change slowly.
   - New/lost backlinks (`GetNewLostBackLinks`): Daily for high-priority domains, weekly for others.
   - Article-level backlinks (`GetBackLinkData`): On-demand, triggered by other arenas identifying high-interest articles.

3. **Analysis unit budget management**:
   - Track unit consumption via the `AnalysisResUnits` field in API responses.
   - Set a daily cap (e.g., 3M units/day) to prevent a single runaway query from exhausting the monthly budget.
   - Prefer `Mode=1` (one backlink per domain) for initial surveys; switch to `Mode=0` (all backlinks) only for targeted deep analysis.
   - Use `MaxSourceURLs` to limit backlinks per source domain.

4. **`collect_by_terms` adaptation**: While Majestic does not support keyword search in the traditional sense, `GetSearchResults` provides limited keyword search within the index. However, this is not the primary use case. Map `collect_by_terms` to: "for each search term, find articles from other arenas matching the term, then query Majestic for backlinks to those article URLs."

5. **`collect_by_actors` adaptation**: Map actors to their associated domains (from `actor_platform_presences` where `platform="web"`). Query `GetIndexItemInfo` and `GetBackLinkData` for those domains.

6. **Time series storage**: For domain metrics tracking, store periodic snapshots. Use `content_type="domain_metrics"` with `platform_id` constructed as `"{domain}_{date}"` to create a time series. This enables visualizing Trust Flow changes during issue cycles.

7. **Health check**: Execute `GetIndexItemInfo` for a single known domain (e.g., `dr.dk`) and verify a valid response with `ResultCode="OK"` and reasonable Trust Flow/Citation Flow values. Also check remaining analysis units.

8. **Credit cost**: Map Majestic analysis units to credits. Suggested mapping: 1,000 analysis units = 1 credit (since a single API call typically consumes hundreds to thousands of units). Adjust the mapping based on actual usage patterns during testing.

9. **Error handling**:
   - `"InsufficientCredits"` result code: Budget exhausted, stop collection.
   - `"RateLimitExceeded"`: Backoff and retry.
   - Empty results: The domain/URL may not be in Majestic's index. Log and skip.
   - `"InvalidAPIKey"`: Mark credential as errored in pool.

10. **Fresh vs. Historic Index**: Default to the Fresh Index (`datasource="fresh"`) for current analysis. Use the Historic Index (`datasource="historic"`) for longitudinal studies or when the Fresh Index has insufficient data for smaller Danish domains.
