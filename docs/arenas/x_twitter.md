# Arena Research Brief: X/Twitter

**Created**: 2026-02-16
**Last updated**: 2026-02-16
**Status**: Ready for implementation
**Phase**: 2 (Task 2.1, Critical priority)
**Arena path**: `src/issue_observatory/arenas/social_media/x_twitter/`

---

## 1. Platform Overview

X (formerly Twitter) is a microblogging and social networking platform with approximately 600 million monthly active users globally. Despite only 13% penetration among Danish 16-74-year-olds, X punches far above its weight in Danish public discourse. Danish defence researchers have found that X discussions closely mirror parliamentary debate themes. The platform is disproportionately used by journalists, politicians, academics, and opinion leaders, making it a critical arena for tracking elite discourse and issue framing in Denmark.

**Role in Danish discourse**: X/Twitter is not a mass-market platform in Denmark (unlike Facebook at 84% or Instagram at 56%), but it functions as a public square for political elites. Danish politicians, media professionals, and institutional accounts use X for real-time commentary, breaking news reaction, and policy debate. The hashtag #dkpol is the primary Danish political discussion marker. Content from X frequently seeds or amplifies stories in mainstream media.

**Access model**: No viable free tier for research. The official free tier allows only 100 reads/month, which is unusable. Research-grade access requires either a third-party service (medium tier) or the official Pro tier ($5,000/month). Academic Research access was eliminated in June 2023 with no replacement.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | Official X API Free tier | $0 | 100 reads/month, 500 posts/month. Write-focused. Unusable for research. |
| **Medium** | TwitterAPI.io | $0.15 per 1,000 tweets | Third-party scraping service. Keyword search, user timeline, full-archive. ~800ms latency. 1,000+ QPS. |
| **Premium** | Official X API Pro tier | $5,000/month | 1,000,000 posts/month read. Full-archive search. Filtered streaming (near-real-time). |

**Recommended starting tier**: Medium (TwitterAPI.io). The cost difference is dramatic -- collecting 100,000 tweets via TwitterAPI.io costs $15; the same via the official Pro tier requires a $5,000/month subscription. The medium tier is recommended unless the project requires official filtered streaming or the legal protections of an official API agreement.

---

## 3. API/Access Details

### Medium Tier: TwitterAPI.io

**Base URL**: `https://api.twitterapi.io/twitter/`

**Authentication**: API key in `X-API-Key` header.

**Key Endpoints**:

| Endpoint | Method | Description | Cost |
|----------|--------|-------------|------|
| `/tweet/advanced_search` | GET | Full-archive tweet search with query operators | $0.15/1K tweets |
| `/user/last_tweets` | GET | Get recent tweets from a user timeline | $0.15/1K tweets |
| `/user/info` | GET | User profile metadata | Included |
| `/tweet/detail` | GET | Single tweet with engagement metrics | Included |

**Search endpoint parameters** (`/tweet/advanced_search`):

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | string | Search query using X/Twitter search operators (see below) |
| `queryType` | string | `Latest` (reverse chronological) or `Top` (relevance) |
| `cursor` | string | Pagination cursor from previous response |

**Search query operators** (passed in `query` parameter):

| Operator | Example | Description |
|----------|---------|-------------|
| Keyword | `klimapolitik` | Basic keyword match |
| Phrase | `"groen omstilling"` | Exact phrase match |
| Hashtag | `#dkpol` | Hashtag search |
| From user | `from:LarsLoekke` | Tweets from specific user |
| To user | `to:LarsLoekke` | Replies to specific user |
| Language | `lang:da` | Danish-language tweets |
| Date range | `since:2026-01-01 until:2026-02-01` | Date-bounded search |
| Retweet filter | `-filter:retweets` | Exclude retweets |
| Reply filter | `filter:replies` | Only replies |
| Link filter | `filter:links` | Only tweets with URLs |
| Min engagement | `min_faves:10` | Minimum like count |
| OR/AND | `klimapolitik OR energipolitik` | Boolean operators |

**Response format**: JSON with `tweets` array and `next_cursor` for pagination. Each tweet object includes full text, author info, engagement metrics, media, and entities.

**Rate limits**:
- 1,000+ queries per second (service-side)
- No published daily cap -- billing is per tweet retrieved
- Recommended: implement client-side rate limiting to control costs

**Latency**: ~800ms per request.

### Premium Tier: Official X API Pro

**Base URL**: `https://api.x.com/2/`

**Authentication**: OAuth 2.0 Bearer Token (App-only) or OAuth 2.0 PKCE (user context). Bearer token is sufficient for read-only search.

**Key Endpoints**:

| Endpoint | Method | Quota Cost | Description |
|----------|--------|------------|-------------|
| `GET /2/tweets/search/all` | GET | 300 req/15 min, 1 req/sec | Full-archive search (Pro+ only) |
| `GET /2/tweets/search/recent` | GET | 450 req/15 min | Last 7 days search |
| `GET /2/users/:id/tweets` | GET | 900 req/15 min | User timeline |
| `GET /2/tweets/:id` | GET | 900 req/15 min | Single tweet lookup |
| `GET /2/tweets/search/stream` | GET | 50 rules, 5M tweets/mo | Filtered real-time stream |

**Full-archive search parameters** (`/2/tweets/search/all`):

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | string | Search query (same operators as TwitterAPI.io above) |
| `start_time` | string | ISO 8601 start timestamp |
| `end_time` | string | ISO 8601 end timestamp |
| `max_results` | integer | 10-500 per page |
| `next_token` | string | Pagination token |
| `tweet.fields` | string | Comma-separated fields to return |
| `expansions` | string | Related objects to expand (author, media, etc.) |
| `user.fields` | string | Author fields to include |

**Filtered streaming** (Pro tier exclusive):
- `POST /2/tweets/search/stream/rules` to add filter rules (up to 50 rules)
- `GET /2/tweets/search/stream` for persistent connection receiving matching tweets
- Rules support the same operators as search
- Near-real-time delivery (seconds latency)
- 5,000,000 tweets/month cap on Pro tier

**Rate limits** (Pro tier):

| Endpoint | Rate Limit | Window |
|----------|-----------|--------|
| Full-archive search | 300 requests | 15 minutes |
| Recent search | 450 requests | 15 minutes |
| User timeline | 900 requests | 15 minutes |
| Tweet lookup | 900 requests | 15 minutes |
| Filtered stream | 1 connection | Persistent |

**Monthly cap**: 1,000,000 tweets read per month across all endpoints.

### Python Libraries

**For TwitterAPI.io (medium tier)**:
- No official SDK. Use `httpx` or `aiohttp` with the REST API directly.
- Simple request/response pattern; no complex auth flow.

**For Official API (premium tier)**:
- `tweepy` (v4.14+): Well-maintained, supports v2 API, async support via `AsyncClient`
- `twikit`: Alternative lightweight client
- Install: `pip install tweepy`

---

## 4. Danish Context

- **`lang:da`**: Both TwitterAPI.io and the official API support the `lang:da` search operator, which filters for tweets classified as Danish by X's language detection model. This is the primary mechanism for Danish content collection.
- **Language detection quality**: X's language classifier is generally reliable for Danish but may misclassify some tweets, particularly short ones, code-mixed tweets (Danish/English), or tweets consisting primarily of names, URLs, or hashtags. Some Danish tweets may be tagged as Swedish (`sv`) or Norwegian (`no`) due to linguistic similarity.
- **Key Danish hashtags**: `#dkpol` (politics), `#dkmedier` (media), `#dkgreen` (climate/environment), `#dkbiz` (business), `#sundpol` (health policy), `#skolechat` (education), `#dkaid` (development aid), `#eudk` (EU/Denmark).
- **Key Danish accounts to track** (non-exhaustive):
  - Political leaders: party leaders, ministers, prominent MPs
  - Media outlets: @LarsMortensen (DR), @tvaborgen (TV2), @LarsBojeMathies (Berlingske), @LarsLoekke, @JeppeBruus
  - Institutional: @LarsLoekke, @LarsBojeMathies, @LarsBojeMathies, @LarsBojeMathies
  - Note: Actor lists should be curated per query design, not hardcoded. The above are examples only.
- **Danish content volume**: X/Twitter has ~13% penetration in Denmark. Danish-language tweet volume is moderate -- estimated at thousands to tens of thousands of tweets per day depending on news cycle. Collection via `lang:da` search is feasible at the medium tier without excessive cost.
- **Danish police on X**: As of 2024-2025, Danish police increasingly use the Via Ritzau platform instead of X for operational announcements, though individual officers and some units remain active on X.

---

## 5. Data Fields

Mapping to the Universal Content Record schema:

| UCR Field | X/Twitter Source (TwitterAPI.io) | X/Twitter Source (Official v2 API) | Notes |
|-----------|--------------------------------|-----------------------------------|-------|
| `platform` | `"x_twitter"` | `"x_twitter"` | Constant |
| `arena` | `"social_media"` | `"social_media"` | Constant |
| `platform_id` | `tweet.id` | `data.id` | Tweet ID (numeric string) |
| `content_type` | `"post"` | `"post"` | Tweets, replies, quotes all map to `"post"` |
| `text_content` | `tweet.text` | `data.text` | Full tweet text (up to 280 chars; 25,000 for X Premium subscribers) |
| `title` | `NULL` | `NULL` | Tweets have no title |
| `url` | Constructed: `https://x.com/{username}/status/{id}` | Constructed: `https://x.com/{username}/status/{id}` | |
| `language` | `tweet.lang` | `data.lang` | ISO 639-1 language code |
| `published_at` | `tweet.created_at` | `data.created_at` | ISO 8601 timestamp |
| `collected_at` | Now | Now | Standard |
| `author_platform_id` | `tweet.author.id` | `includes.users[].id` | Numeric user ID |
| `author_display_name` | `tweet.author.name` | `includes.users[].name` | Display name |
| `views_count` | `tweet.views` | `data.public_metrics.impression_count` | View/impression count |
| `likes_count` | `tweet.favorites` | `data.public_metrics.like_count` | |
| `shares_count` | `tweet.retweets` | `data.public_metrics.retweet_count` + `quote_count` | Retweets + quotes |
| `comments_count` | `tweet.replies` | `data.public_metrics.reply_count` | |
| `engagement_score` | Compute from views, likes, retweets, replies | Compute from metrics | Normalized |
| `raw_metadata` | Full tweet object | Full response with expansions | Store: `entities` (hashtags, mentions, URLs, cashtags), `referenced_tweets` (reply-to, quote, retweet references), `context_annotations`, `geo`, `source`, `conversation_id`, media objects |
| `media_urls` | Extract from `tweet.media[].url` | Extract from `includes.media[].url` | Image and video URLs |
| `content_hash` | SHA-256 of normalized `text_content` | SHA-256 of normalized `text_content` | For deduplication |

**Tweet types**: The normalizer must handle:
- **Original tweets**: Standard posts
- **Retweets**: `referenced_tweets` contains `type: "retweeted"`. Store the original tweet's text; set `raw_metadata.is_retweet = true`.
- **Quote tweets**: `referenced_tweets` contains `type: "quoted"`. Store both the quoting text and the quoted tweet reference.
- **Replies**: `referenced_tweets` contains `type: "replied_to"`. Store `conversation_id` and `in_reply_to_user_id` in `raw_metadata`.

**Field normalization between tiers**: The normalizer must handle different JSON structures from TwitterAPI.io vs. the official v2 API. Implement two parsing paths that converge to the same UCR output. The tier determines which parser is invoked.

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Medium (TwitterAPI.io) | `{"api_key": "twitterapi-io-key-xxx"}` | `"twitterapi_io"` |
| Premium (Official X API) | `{"bearer_token": "AAA..."}` | `"x_twitter"` |

**Credential pool for medium tier (TwitterAPI.io)**:
- TwitterAPI.io bills per tweet retrieved, not per API key
- Multiple API keys are useful for parallelism and fault tolerance, not quota multiplication
- Recommendation: Start with 2-3 TwitterAPI.io API keys in the CredentialPool
- If one key is rate-limited or encounters an error, the pool rotates to the next

**Credential pool for premium tier (Official X API)**:
- Each X API Pro subscription ($5,000/month) includes one set of credentials
- Multiple subscriptions are not cost-effective
- Single credential with careful rate limit management is the expected pattern

---

## 7. Rate Limits and Multi-Account Notes

### Medium Tier (TwitterAPI.io)

| Metric | Value | Notes |
|--------|-------|-------|
| Requests per second | 1,000+ | Service-side capacity |
| Daily request cap | None published | Billing-based (pay per tweet) |
| Results per page | Variable (typically 20-50) | Use cursor pagination |
| Cost control | Client-side budget | Implement credit-based budget enforcement |

**Cost control is the primary constraint, not rate limits.** TwitterAPI.io does not impose hard rate limits but charges per tweet. The CredentialPool and CreditService must enforce per-run budget limits to prevent runaway costs. Implement a `max_credits` parameter on collection tasks.

### Premium Tier (Official X API Pro)

| Metric | Value | Notes |
|--------|-------|-------|
| Full-archive search | 300 req / 15 min | 1 req/sec |
| Recent search | 450 req / 15 min | |
| Monthly tweet cap | 1,000,000 | Across all read endpoints |
| Streaming rules | 50 concurrent | |
| Streaming cap | 5,000,000 tweets/month | |

**RateLimiter configuration**:
- Use `x-rate-limit-remaining` and `x-rate-limit-reset` response headers for adaptive rate limiting
- Track monthly tweet consumption against the 1,000,000 cap
- For the medium tier, track credit consumption rather than request rate

---

## 8. Search Capabilities

### collect_by_terms() Implementation

For both tiers, `collect_by_terms()` maps query design search terms to X/Twitter search operators:

1. Take each search term from the query design
2. Append `lang:da` for Danish language filtering
3. Optionally append date range operators (`since:YYYY-MM-DD until:YYYY-MM-DD`)
4. Execute search and paginate through all results (or until `max_results` reached)

**Example query construction**:
- Query design term: `klimapolitik`
- Constructed query: `klimapolitik lang:da since:2026-01-01 until:2026-02-01 -filter:retweets`

**Hashtag terms** from the query design (term_type = `hashtag`) should be passed directly as `#hashtag` in the query.

### collect_by_actors() Implementation

1. Map actor platform presences to X/Twitter usernames or user IDs
2. **Medium tier**: Use `/user/last_tweets` endpoint for each actor
3. **Premium tier**: Use `/2/users/:id/tweets` endpoint for each actor, or construct search queries with `from:username`
4. Filter by date range client-side or via search operators
5. Paginate through all results

**For large actor lists**: Batch actor collection by constructing OR queries: `from:user1 OR from:user2 OR from:user3 lang:da`. X search supports up to ~1024 characters per query, allowing approximately 20-30 usernames per query.

---

## 9. Latency and Freshness

| Tier | Mode | Latency | Notes |
|------|------|---------|-------|
| Medium | Search (TwitterAPI.io) | ~800ms per request + indexing delay | Tweets typically searchable within minutes of posting |
| Premium | Search (official) | ~1-3 sec per request + indexing delay | Full-archive: minutes to hours for indexing |
| Premium | Filtered streaming | Seconds | Near-real-time delivery of matching tweets |

**Polling interval recommendation**:
- For live tracking: Poll every 15 minutes (medium tier) or use filtered streaming (premium tier)
- For batch collection: No polling needed -- search with date range parameters

---

## 10. Known Limitations

1. **No free tier for research**: The official free tier (100 reads/month) is completely unusable for data collection. This is a paid-only arena.

2. **Third-party service risk**: TwitterAPI.io and similar services operate by scraping X. X has historically attempted to shut down scrapers, though court rulings (X Corp v. Bright Data, 2024, dismissed) have favored scrapers for public data. There is an ongoing risk that X may succeed in blocking specific services. The ArenaCollector abstraction allows swapping to alternative providers (SocialData API at $0.0002/tweet, Bright Data at $250/100K) if TwitterAPI.io is disrupted.

3. **Engagement metric accuracy at medium tier**: Third-party services may return engagement metrics that are slightly delayed or approximate compared to the official API. For research requiring precise engagement data, the premium tier is preferable.

4. **Monthly cap on premium tier**: The 1,000,000 tweets/month read cap on the Pro tier limits large-scale historical collection. Plan batch collection carefully to stay within budget.

5. **Retweet handling**: Retweets contain the full text of the original tweet prefixed with "RT @username:". The normalizer should extract the original text and flag the record as a retweet in `raw_metadata`. Some studies exclude retweets entirely; make this configurable.

6. **Thread detection**: Twitter threads (multi-tweet posts by the same author) should be linked via `conversation_id`. The normalizer should preserve this in `raw_metadata` to enable thread reconstruction.

7. **Deleted and suspended content**: Tweets that are deleted or from suspended accounts after collection cannot be re-fetched. The initial collection captures a snapshot. This is a common limitation across all platforms.

8. **Nitter is dead**: Nitter-based approaches ceased functioning in January 2024 when X disabled guest accounts. Do not attempt to use Nitter as a fallback.

9. **Rate limit changes**: X has historically changed rate limits and API tier pricing with little notice. Monitor the X developer changelog and be prepared to adjust RateLimiter configuration.

10. **Danish language edge cases**: Short tweets (under ~20 characters), tweets mixing Danish and English, and tweets consisting primarily of URLs or mentions may not be correctly classified as `lang:da`. Consider supplementing `lang:da` search with keyword-based queries using known Danish terms.

---

## 11. Legal Considerations

**Official API (premium tier)**:
- X API Terms of Service permit data collection for research purposes
- Data redistribution is prohibited (individual tweet IDs may be shared; full tweet objects may not)
- 30-day data freshness requirement (must re-fetch or delete after 30 days) -- for academic research under GDPR Art. 89, longer retention with pseudonymization is defensible. Document in DPIA.

**Third-party service (medium tier)**:
- TwitterAPI.io operates under the legal precedent established by *X Corp v. Bright Data* (2024, dismissed) and *hiQ v. LinkedIn* (2022) -- scraping publicly available data has been consistently upheld by US courts
- SerpAPI provides an explicit "U.S. Legal Shield" if the project later switches providers
- In the EU context: scraping public tweets does not require X's consent, but GDPR applies to all personal data collected. Standard pseudonymization via `pseudonymized_author_id` is required.

**GDPR implications**:
- Tweet text, author names, and profile information constitute personal data under GDPR
- Legal basis: Art. 6(1)(e) combined with Art. 89 for university research
- Pseudonymize author identifiers using `SHA-256(platform + platform_user_id + project_salt)`
- Include X/Twitter collection in the project DPIA
- If collecting tweets that reveal political opinions (common in #dkpol), this constitutes special category data under Art. 9(1). Legal basis: Art. 9(2)(j) combined with Databeskyttelsesloven section 10 ("significant societal importance")

**DSA Article 40**:
- X is designated as a VLOP under the DSA
- The European Commission fined X EUR 120 million on December 5, 2025, with EUR 40M specifically for researcher access violations
- DSA Art. 40(12) grants researchers the right to access publicly accessible data through automated means
- X's DSA researcher access program is not yet fully operational, but enforcement pressure is increasing
- This may become a viable access path during the project lifecycle; monitor developments

---

## 12. Recommended Implementation Approach

### Architecture

- **Dual-tier collector**: Implement a single `XTwitterCollector` that accepts both medium and premium tier configurations. The tier determines which API client and parser are used.
- **Cost-controlled collection**: Because the medium tier bills per tweet, implement strict credit budget enforcement. Each collection task should have a `max_credits` parameter that halts collection when reached.
- **Cursor-based pagination**: Both TwitterAPI.io and the official API use cursor-based pagination. Implement with retry logic for cursor continuation after transient failures.

### Key Implementation Guidance

1. **Medium tier (`collect_by_terms`)**:
   - Construct search query from query design terms + `lang:da` + date range
   - Call `/tweet/advanced_search` with `queryType=Latest` for chronological collection
   - Paginate with `cursor` until no more results or `max_credits` reached
   - Track tweets retrieved for credit accounting (1 credit per tweet, billed at $0.15/1K)

2. **Medium tier (`collect_by_actors`)**:
   - Map actor platform presences to X/Twitter usernames
   - Call `/user/last_tweets` for each actor
   - Paginate and filter by date range client-side
   - Alternative: use search with `from:username lang:da since:... until:...`

3. **Premium tier (`collect_by_terms`)**:
   - Use `tweepy.Client.search_all_tweets()` for full-archive search
   - Set `tweet_fields`, `user_fields`, `expansions` for complete data
   - Paginate with `next_token`
   - Respect 300 req/15 min rate limit; use RateLimiter

4. **Premium tier (filtered streaming)**:
   - Set up stream rules matching query design terms + `lang:da`
   - Use `tweepy.StreamingClient` for persistent WebSocket connection
   - Run as a dedicated Celery worker (similar to Bluesky Jetstream)
   - Handle disconnections with exponential backoff reconnect
   - Persist stream cursor for restart continuity

5. **Normalizer**: Implement two parsing paths:
   - `_parse_twitterapi_io(raw)` for medium tier responses
   - `_parse_official_v2(raw)` for premium tier responses
   - Both converge to the same UCR dict output

6. **Health check**:
   - Medium tier: `GET /tweet/advanced_search?query=test&queryType=Latest` with a 1-result limit
   - Premium tier: `GET /2/tweets/search/recent?query=test&max_results=10`

7. **Credit cost mapping**:
   - Medium tier: 1 credit = 1 tweet retrieved (cost: $0.15 per 1,000 credits)
   - Premium tier: Fixed monthly cost; credit mapping is based on monthly tweet read budget (1,000,000/month = ~33,333/day)
