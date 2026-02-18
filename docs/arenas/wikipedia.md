# Arena Research Brief: Wikipedia

**Created**: 2026-02-18
**Last updated**: 2026-02-18
**Status**: Ready for implementation
**Phase**: 2.5 (High priority -- implement after current Phase 2 work)
**Arena path**: `src/issue_observatory/arenas/wikipedia/`

---

## 1. Platform Overview

Wikipedia is the world's largest collaboratively-edited encyclopedia, serving approximately 508 million pageviews per day across all language editions. For issue tracking and discourse research, Wikipedia's value lies not in its content (which aims for encyclopedic neutrality) but in the **editorial attention signals** it produces: which articles are being edited, how frequently, by whom, what debates occur on talk pages, and how many people are reading articles about specific topics.

These signals provide a unique complement to social media volume data. When an issue becomes salient in public discourse, corresponding Wikipedia articles show increased edit frequency, talk page activity, and pageview spikes. This makes Wikipedia a barometer of sustained public attention -- distinct from the ephemeral spikes of social media.

**Role in Danish discourse**: High. Danish Wikipedia (`da.wikipedia.org`) contains approximately 290,000 articles covering all topics relevant to Danish public policy, politics, culture, and society. Articles on contested policy topics (e.g., "CO2-afgift", "Kunstig intelligens", "Klimapolitik") show edit patterns that directly reflect the intensity of public debate. English Wikipedia is also relevant for topics with international dimensions.

**Access model**: Fully open. All Wikipedia data is freely accessible via the MediaWiki API and the Wikimedia REST API. No API keys are required. Content is licensed under CC-BY-SA 3.0. The only requirement is a meaningful User-Agent header.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | MediaWiki Action API + Wikimedia REST API + Pageviews API | $0 | Unlimited read access. Polite rate limiting requested. |
| **Medium** | N/A | -- | Free tier is comprehensive. |
| **Premium** | N/A | -- | Free tier is comprehensive. |

Wikipedia is a free-only arena. No paid tiers exist or are needed.

---

## 3. API/Access Details

### MediaWiki Action API

**Base URL**: `https://da.wikipedia.org/w/api.php` (Danish) / `https://en.wikipedia.org/w/api.php` (English)

**Format**: All requests include `format=json` for JSON responses.

**Key endpoints**:

| Endpoint | Method | Description | Auth Required |
|----------|--------|-------------|---------------|
| `action=query&list=recentchanges` | GET | Recent edits across all articles | No |
| `action=query&prop=revisions` | GET | Revision history of specific pages | No |
| `action=query&list=search` | GET | Full-text search across articles | No |
| `action=query&list=usercontribs` | GET | All edits by a specific user | No |
| `action=query&prop=info` | GET | Page metadata (watchers, edit count) | No |

**Recent changes endpoint parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `rcnamespace` | int | Filter by namespace (0=article, 1=talk, etc.) |
| `rctype` | string | `edit`, `new`, `log` |
| `rclimit` | int | Results per request (max 500) |
| `rcstart` / `rcend` | timestamp | Date range (ISO 8601 or MediaWiki format) |
| `rcprop` | string | Fields to return: `user`, `timestamp`, `comment`, `sizes`, `tags` |

**Revision history endpoint parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `titles` | string | Page title(s) to query (pipe-separated for multiple) |
| `rvprop` | string | Fields: `ids`, `user`, `timestamp`, `comment`, `size`, `content`, `tags` |
| `rvlimit` | int | Revisions per request (max 500) |
| `rvstart` / `rvend` | timestamp | Date range filter |
| `rvdir` | string | `newer` or `older` (sort direction) |

**Search endpoint parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `srsearch` | string | Search query (supports intitle: prefix) |
| `srnamespace` | int | Namespace filter |
| `srlimit` | int | Results per request (max 500) |
| `sroffset` | int | Pagination offset |

### Wikimedia Core REST API

**Base URL**: `https://da.wikipedia.org/w/rest.php/v1` (or `en.wikipedia.org`)

| Endpoint | Method | Description | Notes |
|----------|--------|-------------|-------|
| `GET /page/{title}/history` | GET | Revision history in 20-revision segments | Pagination via `older_than` revision ID |
| `GET /revision/{id}` | GET | Single revision details | Includes `delta` (size change), `comment`, `user` |
| `GET /revision/{from}/compare/{to}` | GET | HTML diff between two revisions | |
| `GET /page/{title}` | GET | Current page content and metadata | |

### Wikimedia Analytics API (Pageviews)

**Base URL**: `https://wikimedia.org/api/rest_v1/metrics/pageviews`

| Endpoint | Description | Parameters |
|----------|-------------|-----------|
| `per-article/{project}/{access}/{agent}/{article}/{granularity}/{start}/{end}` | Pageviews for a specific article | `project`: `da.wikipedia` or `en.wikipedia`; `access`: `all-access`; `agent`: `user`; `granularity`: `daily` or `monthly` |
| `top/{project}/{access}/{year}/{month}/{day}` | Top-viewed articles for a date | Returns ranked list |

**Data availability**: July 2015 onward. Daily granularity. Data populates with approximately 24-hour delay.

**Python wrapper**: `mwviews` library (`PageviewsClient`) handles the API details.

### Authentication

No authentication is required for any read-only Wikipedia API access.

**Required**: A descriptive `User-Agent` header identifying the tool and providing contact information. Example:
```
IssueObservatory/1.0 (https://github.com/...; research@university.dk) python-httpx/0.27
```

Wikimedia may throttle or block requests without a meaningful User-Agent.

---

## 4. Danish Context

- **Danish Wikipedia (`da.wikipedia.org`)**: Dedicated API endpoint. All queries against this domain return Danish-language articles by default. No language filter parameter needed.
- **Article discovery**: Use `action=query&list=search&srsearch=CO2+afgift` on `da.wikipedia.org` to find articles related to Danish policy topics.
- **Talk page monitoring**: Danish Wikipedia talk pages (namespace 1) contain editorial debates in Danish. These are accessible via the same revision history API with `namespace=1`.
- **Cross-language analysis**: For topics with international dimensions, query both `da.wikipedia.org` and `en.wikipedia.org`. The Wikidata QID (e.g., Q1234) can link equivalent articles across languages.
- **Danish editors**: Notable Danish editors can be tracked via `list=usercontribs`. Combined with other arena data, this can reveal cross-platform actor behavior.
- **Pageview spikes**: Danish Wikipedia pageview spikes correlate with Danish media coverage. A spike in views of the "CO2-afgift" article typically accompanies heightened media attention to carbon tax policy.

---

## 5. Data Fields

Wikipedia produces three record types. All map to the universal content record schema.

### Wiki Revision Records (`content_type = "wiki_revision"`)

| UCR Field | Wikipedia Source | Notes |
|-----------|----------------|-------|
| `platform` | `"wikipedia"` | Constant |
| `arena` | `"reference"` | New arena group |
| `platform_id` | `"{wiki_project}:rev:{revision_id}"` | e.g., `"da.wikipedia:rev:12345678"` |
| `content_type` | `"wiki_revision"` | Edit to an article |
| `text_content` | `revision.comment` | Edit summary, NOT article text |
| `title` | Article title | e.g., `"CO2-afgift"` |
| `url` | `"https://da.wikipedia.org/w/index.php?oldid={rev_id}"` | Permalink to revision |
| `language` | `"da"` or `"en"` | Derived from wiki project domain |
| `published_at` | `revision.timestamp` | When the edit was made |
| `author_platform_id` | `revision.user` | Username or IP address |
| `author_display_name` | `revision.user` | Same value |
| `views_count` | NULL | Not applicable to individual revisions |
| `likes_count` | NULL | Wikipedia has no like system |
| `shares_count` | NULL | Not applicable |
| `comments_count` | NULL | Not directly available per revision |
| `raw_metadata` | Full revision object | `delta` (bytes changed), `minor` (boolean), `tags[]`, `parentid`, `namespace` (0=article, 1=talk), `is_talk_page` (derived), `page_id` |

### Pageview Records (`content_type = "wiki_pageview"`)

| UCR Field | Wikipedia Source | Notes |
|-----------|----------------|-------|
| `platform` | `"wikipedia"` | Constant |
| `arena` | `"reference"` | |
| `platform_id` | `"{wiki_project}:pv:{article}:{date}"` | e.g., `"da.wikipedia:pv:CO2-afgift:2026-02-17"` |
| `content_type` | `"wiki_pageview"` | Aggregated daily statistic |
| `text_content` | NULL | No text for pageview records |
| `title` | Article title | |
| `url` | `"https://da.wikipedia.org/wiki/{article}"` | Article URL |
| `language` | `"da"` or `"en"` | From project |
| `published_at` | Date of the pageview count | The date the views were counted |
| `views_count` | Pageview count | Primary data point |
| `likes_count` | NULL | |
| `raw_metadata` | Full pageview response | `access` breakdown (desktop/mobile), `agent` type |

### Talk Page Records

Talk page edits are a subset of wiki_revision records where `raw_metadata.namespace = 1`. They should be stored as standard `wiki_revision` records with `raw_metadata.is_talk_page = true`. No separate content_type is needed.

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Free | None (unauthenticated) | N/A |

No credentials are needed. The only configuration is the `User-Agent` header, which should be set via application settings (not the credential pool).

---

## 7. Rate Limits and Multi-Account Notes

| Access Type | Rate Limit | Notes |
|-------------|-----------|-------|
| MediaWiki Action API | No formal limit; polite: 1-5 req/s | Wikimedia asks automated tools not to exceed ~200 req/s |
| Wikimedia REST API | Same as above | Shared infrastructure |
| Pageviews API | ~100 req/s | More permissive; cacheable data |

**Recommended RateLimiter configuration**: 5 requests per second as a baseline. This is generous but respectful.

**Multi-account**: Not applicable. No authentication means no account-based rate limiting. Rate limits are per IP address. No multi-account strategy is needed.

---

## 8. Known Limitations

1. **Pageview data has ~24-hour delay**: Not suitable for real-time tracking. Pageview data for today will be available tomorrow.

2. **Edit summaries may be empty or uninformative**: Not all editors write meaningful edit comments. Approximately 30-40% of edits on Danish Wikipedia have no edit summary. The `text_content` field will be NULL or empty for these.

3. **Bot edits inflate edit counts**: Many Wikipedia edits are made by automated bots (format fixes, interwiki links, vandalism reversion). The `tags` field in `raw_metadata` can identify bot edits (look for tags like `mw-bot`, `OAuth CID:...`). Filter these for human-attention analysis.

4. **Vandalism and reverts**: Short-lived vandalism edits followed by immediate reverts inflate edit counts. The `tags` field includes `mw-revert` and `mw-undo` indicators. Consider filtering or flagging these.

5. **Recent changes 30-day limit**: The `list=recentchanges` endpoint returns at most 30 days of data on Wikimedia wikis. For older data, use `prop=revisions` on specific pages (which has no date limit).

6. **Pageview agent filtering**: The `agent=user` parameter filters out most automated traffic but is not perfect. Some bot traffic may still be counted.

7. **Article title encoding**: Wikipedia article titles use URL encoding for special characters. Danish characters (ae, oe, aa) are encoded in URLs but appear as plain text in API responses.

8. **No engagement metrics**: Wikipedia has no like, share, or comment system on articles. The only "engagement" signals are edit count, talk page activity, and pageview volume.

---

## 9. Collector Implementation Notes

### Architecture

- **Collection mode**: Batch polling only. No streaming/real-time component needed.
- **Three data collection strategies**:
  1. **Article-based monitoring**: Given a list of article titles, collect revision history and pageview data.
  2. **Term-based discovery**: Search for articles matching query terms, then collect data for discovered articles.
  3. **Editor-based tracking**: Given Wikipedia usernames, collect their contribution history.

### Key Implementation Guidance

1. **`collect_by_terms()` implementation**:
   - Step 1: Search for articles matching terms via `action=query&list=search`.
   - Step 2: For each discovered article, collect revision history via `action=query&prop=revisions`.
   - Step 3: For each article, collect pageview data via the Pageviews API.
   - Normalize each revision as a `wiki_revision` record. Normalize each daily pageview as a `wiki_pageview` record.

2. **`collect_by_actors()` implementation**:
   - Interpret `actor_ids` as either Wikipedia usernames (for editor tracking) or article titles (for article monitoring).
   - For usernames: Use `action=query&list=usercontribs&ucuser={username}`.
   - For article titles: Use `action=query&prop=revisions&titles={title}`.
   - The `actor_ids` parameter semantics should be documented clearly.

3. **Pagination**: Both the Action API and REST API use cursor-based pagination. The Action API uses `continue` tokens (returned in the response); the REST API uses `older_than` revision IDs.

4. **Wiki project configuration**: The collector should accept a list of wiki projects to query (default: `["da.wikipedia", "en.wikipedia"]`). The base URL is constructed from the project name.

5. **Health check**: `GET https://da.wikipedia.org/w/api.php?action=query&meta=siteinfo&format=json` -- verify 200 response and valid JSON with site metadata.

6. **Credit cost**: 0 credits for all operations (free tier only).

7. **Python libraries**:
   - Primary: `httpx.AsyncClient` for all API calls (consistent with other arenas).
   - Pageviews: `mwviews.PageviewsClient` for convenient pageview querying. Note: `mwviews` is synchronous; wrap calls in `asyncio.to_thread()`.

8. **User-Agent**: Set a configurable `WIKIPEDIA_USER_AGENT` in settings. Pass it on every request. Wikimedia may block requests without a meaningful User-Agent.

9. **Namespace handling**: Track namespaces in `raw_metadata`. Article namespace = 0, Talk namespace = 1. Set `raw_metadata.is_talk_page = True` for namespace 1 edits.

10. **Deduplication**: Use `{wiki_project}:rev:{revision_id}` as the platform_id for revisions. Revision IDs are unique per wiki project. For pageviews, use `{wiki_project}:pv:{article}:{date}` to allow daily updates without duplicates.

---

## 10. Legal Considerations (Expanded)

- **Content license**: CC-BY-SA 3.0. No restrictions on collection, storage, or analysis for research.
- **GDPR**: Wikipedia editor usernames and IP addresses (for anonymous edits) are public data, published under the CC-BY-SA license. Pseudonymization via `pseudonymized_author_id` should still be applied for consistency with project-wide GDPR baseline.
- **Terms of Service**: Wikimedia's [Terms of Use](https://foundation.wikimedia.org/wiki/Terms_of_Use) and [API etiquette guidelines](https://www.mediawiki.org/wiki/API:Etiquette) require: (a) meaningful User-Agent header, (b) polite rate limiting, (c) no modification of content via the API without appropriate authorization.
- **DSA**: Not applicable. Wikipedia/Wikimedia Foundation is a non-profit and not designated as a VLOP.
- **Ethical considerations**: Wikipedia data is among the least ethically problematic of all social media/web data. Editor usernames are chosen voluntarily and publicly displayed. The platform is designed for open collaboration and research access.

**Legal risk assessment**: Minimal. Wikipedia is the lowest-risk arena in the entire project.

---

## 11. Latency and Freshness

| Data Type | Latency | Freshness for Live Tracking |
|-----------|---------|----------------------------|
| Recent changes / revisions | Near-real-time (seconds after edit) | Excellent -- can detect edits within minutes |
| Pageview statistics | ~24 hours | Acceptable -- daily granularity is appropriate for attention tracking |
| Search index | Minutes | Newly created articles appear in search within minutes |

**Live tracking recommendation**: Daily Celery Beat job that:
1. Queries `list=recentchanges` for articles in the monitored set (last 24 hours).
2. Fetches updated pageview data for the previous day.
3. Stores new revision records and updates pageview records.

---

## 12. Recommended Architecture Summary

| Component | Recommendation |
|-----------|---------------|
| Arena group | `"reference"` (new) |
| Platform name | `"wikipedia"` |
| Supported tiers | `[Tier.FREE]` |
| Collection pattern | Batch polling (REST API + Action API) |
| Python HTTP client | `httpx.AsyncClient` |
| Pageview library | `mwviews` (wrapped in `asyncio.to_thread()`) |
| RateLimiter config | 5 req/s |
| Credential pool | Not used (unauthenticated) |
| Celery queue | Default (not streaming) |
| Beat schedule | Daily: revision + pageview update for monitored articles |
| Content types | `wiki_revision`, `wiki_pageview` |
| Danish targeting | Query `da.wikipedia.org` domain directly |
