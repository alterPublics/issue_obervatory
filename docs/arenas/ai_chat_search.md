# Arena Research Brief: AI Chat Search

**Created**: 2026-02-17
**Last updated**: 2026-02-17
**Status**: Ready for implementation
**Phase**: 2
**Arena path**: `src/issue_observatory/arenas/ai_chat_search/`

---

## 1. Platform Overview

AI Chat Search captures the AI-mediated information environment -- specifically, the synthesized answers and cited sources that web-search-enabled large language models return when asked about Danish public issues. As AI chatbots increasingly substitute for traditional search engines, the responses they produce constitute a distinct information layer: users receive a framed, synthesized narrative rather than a ranked list of URLs.

**Role in Danish discourse**: This arena measures two research dimensions that no other arena captures. First, **source selection bias**: which Danish media outlets, institutions, and websites AI models cite when answering questions about Danish issues. Second, **framing effects**: how AI models synthesize, summarize, and frame topics for users. Together these reveal the AI-mediated information diet available to Danish users who ask chatbots instead of (or in addition to) using Google Search.

**Complementary to Google Search**: This arena is designed to run on the same query designs as the Google Search arena. Where Google Search captures what users *find* (ranked URLs), AI Chat Search captures what users are *told* (synthesized answers). The two arenas together provide a comprehensive picture of the search-based information environment.

**Access model**: Collection uses OpenRouter as a unified API gateway. OpenRouter routes requests to Perplexity's Sonar models, which perform live web searches and return both a synthesized answer and a structured citations array. The implementation team has verified that OpenRouter passes through Perplexity's `citations` array correctly.

**Two-phase collection design**: Each collection run involves two steps:

1. **Query expansion**: A cheap LLM (no web search) generates N realistic Danish user phrasings from each search term. This simulates the diversity of how real users phrase questions to chatbots.
2. **AI chat search**: Each expanded phrasing is submitted to a web-search-enabled model (Perplexity Sonar via OpenRouter). The full response text and structured citations are captured.

**Important distinction**: This arena produces two types of content records per query: the AI-generated response itself (`ai_chat_response`) and each individual cited source (`ai_chat_citation`). Both are stored as separate records in the universal content record schema.

---

## 2. Tier Configuration

| Tier | Chat Model | Expansion Model | Phrasings/Term | Cost Estimate | Notes |
|------|-----------|-----------------|----------------|---------------|-------|
| **Free** | N/A | N/A | N/A | Not available | No free web-search AI API exists. Returns empty list with warning. |
| **Medium** | `perplexity/sonar` via OpenRouter | `google/gemma-3-27b-it:free` | 5 | ~$5--15/month | 10 terms, 5 phrasings, 1x/day |
| **Premium** | `perplexity/sonar-pro` via OpenRouter | `google/gemma-3-27b-it:free` | 10 | ~$15--45/month | 10 terms, 10 phrasings, multi-model comparison possible |

**FREE tier is explicitly unavailable.** The `AiChatSearchCollector` returns an empty list and logs a warning when `tier=Tier.FREE` is requested. This is enforced in `collector.py` and reflected in the tier config.

**Query expansion cost**: Negligible (<$0.001 per call) since the expansion model uses a free tier on OpenRouter (`google/gemma-3-27b-it:free`).

---

## 3. API/Access Details

### OpenRouter API (Both Tiers)

**Endpoint**: `POST https://openrouter.ai/api/v1/chat/completions`

**Authentication**: `Authorization: Bearer <OPENROUTER_API_KEY>` header.

**Request format**: OpenAI-compatible JSON body.

| Body Parameter | Type | Description | Example |
|----------------|------|-------------|---------|
| `model` | string | Model identifier | `"perplexity/sonar"` or `"perplexity/sonar-pro"` |
| `messages` | array | Chat messages array | See below |
| `temperature` | float | Sampling temperature | `0` (deterministic) |

**System prompt** (enforces Danish language):

```
Du er en hjælpsom assistent. Svar altid på dansk. Besvar brugerens spørgsmål grundigt og præcist.
```

**User message**: The expanded phrasing (e.g., `"Hvad er CO2 afgiften i Danmark?"`)

**Response**: OpenAI-compatible JSON with additional `citations` field.

| Response Field | Type | Description |
|----------------|------|-------------|
| `choices[0].message.content` | string | Full AI-generated response text |
| `citations` | array | Top-level array of cited URLs (Perplexity format A) |
| `choices[0].message.citations` | array | Per-message citations with url/title/snippet (Perplexity format B) |
| `usage.prompt_tokens` | integer | Input tokens consumed |
| `usage.completion_tokens` | integer | Output tokens consumed |
| `model` | string | Actual model used |

**Citation format handling**: Perplexity returns citations in two possible formats. Format A is a top-level `citations` array containing URL strings. Format B is `choices[0].message.citations` containing objects with `url`, `title`, and `snippet` fields. The implementation must handle both formats and extract citations regardless of which format the API returns for a given request.

### Query Expansion (Pre-Processing Step)

**Endpoint**: Same OpenRouter endpoint.

**Model**: `google/gemma-3-27b-it:free` (zero cost).

**System prompt**:

```
Du er en dansk bruger der soeger information via en AI-chatbot.
Generer praecis {N} realistiske spoergsmaal som en dansker ville stille
om dette emne. Varier mellem faktuelle, holdningsoegende og praktiske
spoergsmaal. Svar kun med spoergsmaalene, et per linje.
```

**User message**: The original search term (e.g., `"CO2 afgift"`).

**Response parsing**: Split response text by newlines, strip numbering prefixes, filter empty lines. Expected output: N lines, each a realistic Danish phrasing of the query.

### SDK / Python Library

No dedicated SDK is used. The implementation uses `httpx.AsyncClient` for direct HTTP requests to the OpenRouter API. Low-level request logic is in `_openrouter.py` (private module), separated from the collector.

---

## 4. Danish Context

- **Danish language enforcement**: Unlike Google Search (which uses `gl=dk` and `hl=da` parameters), AI Chat Search enforces Danish via the system prompt: `"Svar altid pa dansk"`. This instructs the model to respond in Danish regardless of the language of its source material.
- **No native language filter**: Perplexity's web search backend does not expose a `lang=da` parameter. The system prompt approach is the only mechanism for influencing response language. Cited sources may be in English or other languages, but the synthesized response will be in Danish.
- **Query expansion in Danish**: The expansion step generates phrasings in Danish, simulating how Danish users actually phrase questions to chatbots. This is critical -- English phrasings would yield different source selection and framing.
- **Danish source visibility**: A key research output of this arena is measuring which Danish sources (DR, TV2, Berlingske, Politiken, etc.) AI models cite versus international sources. The citation records enable systematic analysis of Danish source representation in AI-mediated search.
- **Danish media ecosystem interaction**: AI chatbots may cite paywalled Danish content (e.g., Berlingske, Jyllands-Posten) in their responses while users cannot access the original source. This creates an information asymmetry worth documenting.

---

## 5. Data Fields

This arena produces two content record types.

### Type A: `ai_chat_response` (one per expanded phrasing)

| UCR Field | Source | Notes |
|-----------|--------|-------|
| `platform` | `"openrouter"` | Constant, set by collector |
| `arena` | `"ai_chat_search"` | Constant, set by collector |
| `platform_id` | `sha256(phrasing + model + day_bucket)` | Deterministic dedup key. Same phrasing + model + day produces the same ID. |
| `content_type` | `"ai_chat_response"` | Set by collector |
| `text_content` | `choices[0].message.content` | Full AI-generated response text |
| `title` | Expanded phrasing sent to model | e.g., `"Hvad er CO2 afgiften i Danmark?"` |
| `url` | `NULL` | AI responses have no URL |
| `language` | `"da"` | Enforced via system prompt |
| `published_at` | `datetime.now(UTC)` | Timestamp of collection (no pre-existing publish date) |
| `collected_at` | `datetime.now(UTC)` | Standard |
| `author_platform_id` | Model name | e.g., `"perplexity/sonar"` |
| `author_display_name` | `NULL` | No author concept |
| `views_count` | `NULL` | Not available |
| `likes_count` | `NULL` | Not available |
| `shares_count` | `NULL` | Not available |
| `comments_count` | `NULL` | Not available |
| `engagement_score` | `NULL` | Not available |
| `raw_metadata` | Full metadata dict | See below |
| `media_urls` | `[]` | No media extraction |
| `content_hash` | SHA-256 of `text_content` | Standard dedup |

**`raw_metadata` for `ai_chat_response`**:

```json
{
  "query_phrasing": "Hvad er CO2 afgiften i Danmark?",
  "search_term_original": "CO2 afgift",
  "model_used": "perplexity/sonar",
  "citations": [
    {"url": "https://dr.dk/...", "title": "...", "snippet": "..."}
  ],
  "tokens_used": {"prompt": 142, "completion": 387},
  "temperature": 0,
  "search_engine_underlying": "perplexity"
}
```

### Type B: `ai_chat_citation` (one per cited source, MEDIUM/PREMIUM tiers)

| UCR Field | Source | Notes |
|-----------|--------|-------|
| `platform` | Domain of cited source | e.g., `"dr.dk"`, `"berlingske.dk"` |
| `arena` | `"ai_chat_search"` | Constant, set by collector |
| `platform_id` | `sha256(citation_url + phrasing + day_bucket)` | Dedup key: same citation for the same phrasing on the same day |
| `content_type` | `"ai_chat_citation"` | Set by collector |
| `text_content` | Citation snippet | If available from Perplexity format B; may be `NULL` in format A |
| `title` | Citation title | If available; may be `NULL` |
| `url` | Cited URL | The actual URL that Perplexity cited |
| `language` | `NULL` | Cited source language is unknown |
| `published_at` | `NULL` | No date information from citations |
| `collected_at` | `datetime.now(UTC)` | Standard |
| `author_platform_id` | `NULL` | No author metadata from citations |
| `author_display_name` | `NULL` | No author metadata |
| `views_count` | `NULL` | Not available |
| `likes_count` | `NULL` | Not available |
| `shares_count` | `NULL` | Not available |
| `comments_count` | `NULL` | Not available |
| `engagement_score` | `NULL` | Not available |
| `raw_metadata` | Citation metadata dict | See below |
| `media_urls` | `[]` | No media extraction |
| `content_hash` | SHA-256 of `url` | URL-based dedup |

**`raw_metadata` for `ai_chat_citation`**:

```json
{
  "parent_response_platform_id": "sha256(...)",
  "citation_rank": 1,
  "original_term": "CO2 afgift",
  "expanded_phrasing": "Hvad er CO2 afgiften i Danmark?",
  "model": "perplexity/sonar"
}
```

---

## 6. Credential Requirements

| Tier | Environment Variable | CredentialPool `platform` | Notes |
|------|---------------------|--------------------------|-------|
| Free | N/A | N/A | Not supported |
| Medium | `OPENROUTER_API_KEY` | `"openrouter"` | Same key for both tiers |
| Premium | `OPENROUTER_API_KEY` | `"openrouter"` | Same key as Medium |

**Single credential**: One OpenRouter API key provides access to all models, including both the expansion model (`google/gemma-3-27b-it:free`) and the chat search models (`perplexity/sonar`, `perplexity/sonar-pro`). Tier selection determines which model is called, not which credential is used.

**Credential acquisition**: The collector calls `credential_pool.acquire(platform="openrouter", tier=<current_tier>)`. On error, `credential_pool.report_error()` is called. Credentials are always released in a `finally` block.

**Optional direct Perplexity fallback**: If OpenRouter becomes unavailable or degrades, a direct Perplexity API key (`PERPLEXITY_API_KEY`) can be configured as a fallback. This is not required for initial implementation but should be considered for production resilience.

---

## 7. Rate Limits and Multi-Account Notes

| Tier | Provider Rate Limit | Effective Throughput | Cost Model |
|------|--------------------|--------------------|------------|
| Medium (Sonar via OpenRouter) | OpenRouter: 200 req/min (free tier), higher on paid | ~50 phrasings/run (10 terms x 5 phrasings) | Pay-per-token via OpenRouter credits |
| Premium (Sonar Pro via OpenRouter) | Same OpenRouter limits | ~100 phrasings/run (10 terms x 10 phrasings) | Pay-per-token, higher per-token cost |

**Token-based pricing**: Unlike the credit-per-query model of SERP APIs, AI Chat Search costs are token-based. Perplexity Sonar on OpenRouter costs approximately $1/1M input tokens and $1/1M output tokens. Sonar Pro costs approximately $3/1M input tokens and $15/1M output tokens. Actual costs depend on response length.

**Expansion model cost**: The `google/gemma-3-27b-it:free` model on OpenRouter has zero token cost. Rate limits on free models are lower (approximately 20 req/min) but sufficient for the expansion step, which generates only N phrasings per search term.

**Rate limiter integration**: The collector uses the shared Redis-backed `RateLimiter` from `workers/rate_limiter.py` with the provider key `"openrouter"`. Rate-limited requests are gated through `rate_limited_request()`.

**Multi-account**: Multiple OpenRouter API keys can be registered in the `CredentialPool` to increase effective throughput or distribute cost across accounts.

**Celery retry**: On `ArenaRateLimitError` (HTTP 429), Celery tasks retry with exponential backoff (up to 3 retries, capped at 5 minutes between attempts).

---

## 8. Search Capabilities

### Keyword Search

This arena does not perform keyword search in the traditional sense. Instead, search terms are expanded into natural-language questions via the query expansion step, then submitted as conversational queries to an AI chatbot. The AI model's internal web search determines which sources are retrieved and cited.

### Query Expansion

For each search term (e.g., `"CO2 afgift"`), the expansion model generates N realistic Danish phrasings:

- `"Hvad er CO2 afgiften i Danmark?"`
- `"Hvad koster CO2 afgift for min bil?"`
- `"Hvornaar traeder den nye CO2 afgift i kraft?"`
- `"Er CO2 afgiften fair for danske virksomheder?"`
- `"Hvordan pavirker CO2 afgiften danske landmaend?"`

Phrasings vary between factual, opinion-seeking, and practical question types to capture the diversity of real user behavior.

### Actor-Based Collection

**Not supported.** AI chatbots do not have a concept of "search by author" or "search by domain." The `collect_by_actors()` method raises `NotImplementedError`. Source-level analysis is performed post-hoc by analyzing the citation records.

### Date Filtering

**Not supported.** AI chatbot responses reflect the model's current web search results. There is no mechanism to request responses based on a specific date range. The `date_from` and `date_to` parameters are ignored.

---

## 9. Latency and Freshness

- **Response latency**: Perplexity Sonar typically responds in 3--8 seconds per query (including web search time). Sonar Pro may take 5--15 seconds for more thorough searches. Query expansion adds approximately 1--2 seconds per term.
- **Freshness of citations**: Perplexity performs a live web search for each query. Cited sources reflect the current web index at query time, comparable to Google Search freshness. However, the model's synthesis may incorporate training knowledge alongside live search results.
- **No real-time streaming**: Collection is polling-based. There is no streaming or webhook mechanism.
- **Recommended polling interval**: For issue tracking, poll key terms once per day. AI responses are less volatile than SERP rankings (the same question asked twice in the same day often yields similar framing), so daily collection is sufficient for tracking framing changes over time. More frequent polling (2--4x/day) is warranted during major events.
- **Non-determinism**: Even with `temperature=0`, AI responses are not perfectly deterministic. Minor variations in phrasing, citation order, or emphasis may occur between identical queries. Treat each response as a timestamped snapshot of AI-mediated framing.

---

## 10. Legal Considerations

- **Terms of service**: OpenRouter is a commercial API gateway that permits programmatic access. Perplexity's Sonar models are offered as API products intended for automated use. Using these services for research data collection is within their intended use case.
- **GDPR**: AI-generated responses are synthetic text, not personal data. Cited sources are publicly available URLs. No special GDPR measures are needed for the collected data itself. If cited URLs lead to pages containing personal data, GDPR assessment of downstream content retrieval (out of scope for this arena) would be required.
- **DSA**: AI chatbots are not currently designated as Very Large Online Platforms (VLOPs) under the DSA, though this is an evolving regulatory area. Perplexity is not subject to DSA Article 40 researcher access requirements as of February 2026. OpenRouter as a gateway is similarly not a VLOP.
- **Research use**: Both OpenRouter and Perplexity permit research use under standard API terms. No additional license or application is required.
- **AI-generated content**: The collected responses are AI-generated text. Any research publication using this data should clearly identify it as AI-generated content and not attribute it to human authors.
- **Copyright of AI responses**: The legal status of copyright in AI-generated text is unsettled in the EU. For research purposes under GDPR Article 89 and the Danish Databeskyttelsesloven, this is not a blocking concern, but researchers should be aware of the evolving legal landscape.
- **Data retention**: AI chat responses are ephemeral by nature -- the same question may receive a different answer tomorrow. The collected data represents a point-in-time observation of AI-mediated framing and should be documented as such.

---

## 11. Known Limitations and Gotchas

1. **Citation extraction format variability**: Perplexity returns citations in two formats: a top-level `citations` array (URL strings) or `choices[0].message.citations` (objects with url/title/snippet). The implementation must handle both. The format may vary between requests or model versions without notice.

2. **Non-deterministic responses**: Even with `temperature=0`, responses are not perfectly reproducible. The underlying web search may return different sources at different times, and the model's synthesis introduces inherent variability. Store the model version in `raw_metadata` for reproducibility tracking.

3. **Danish language compliance**: The system prompt `"Svar altid pa dansk"` works reliably but is not guaranteed. In edge cases (highly technical English-language topics, code snippets), the model may include English text. Monitor response language in quality checks.

4. **Query expansion bias**: The expansion model introduces its own biases in how it phrases questions. Different expansion models will produce different phrasings, which will elicit different responses and citations. Store all expansion metadata for transparency. A researcher review step for generated phrasings is recommended as a future feature.

5. **`collect_by_actors()` not supported**: This method raises `NotImplementedError`. There is no mechanism to query AI chatbots for content by a specific author or domain.

6. **No engagement metrics**: AI chat responses carry no likes, shares, comments, or view counts. All engagement UCR fields are `NULL`.

7. **Citation snippet availability**: Citation snippets are only available when Perplexity returns format B citations (objects with `snippet` field). Format A citations (URL-only array) provide no snippet. The `text_content` field for `ai_chat_citation` records may be `NULL`.

8. **Token cost variability**: Response length (and therefore cost) varies significantly by query. Broad questions (`"Fortael mig om dansk klimapolitik"`) produce longer responses than narrow ones (`"Hvad er CO2 afgiften?"`). Budget estimates assume average response lengths.

9. **Model availability on OpenRouter**: Model identifiers on OpenRouter may change if Perplexity updates model versions. The `config.py` module should define model identifiers as constants for easy updating.

10. **Expansion model quality**: The free `google/gemma-3-27b-it:free` model may occasionally produce malformed phrasings (e.g., English text, numbering artifacts, meta-commentary). The newline parser should include basic filtering to discard obviously invalid phrasings.

11. **No date filtering**: Like Google Search, there is no mechanism to restrict AI chat responses to a specific time period. The model's web search may cite sources of any age.

12. **Health check dependency**: Health check requires a valid OpenRouter credential and a successful response from the expansion model and the chat model. If either is unavailable, the check returns `"degraded"`.

---

## 12. Collector Implementation Notes

### Architecture (to be implemented)

The AI Chat Search arena will be implemented at `src/issue_observatory/arenas/ai_chat_search/` with the following module structure:

| Module | Purpose |
|--------|---------|
| `collector.py` | `AiChatSearchCollector` class implementing `ArenaCollector` interface |
| `_openrouter.py` | Low-level HTTP client for OpenRouter API; two-format citation extractor |
| `_query_expander.py` | Phrasing generation prompt template + newline parser with filtering |
| `config.py` | Model names per tier, phrasings count per tier, constants, prompt templates |
| `tasks.py` | Celery task definitions |
| `router.py` | FastAPI router for manual triggering and status |
| `README.md` | Operational documentation |

### Key Implementation Details

1. **Class registration**: `AiChatSearchCollector` is decorated with `@register`, making it discoverable via the arena registry. `arena_name = "ai_chat_search"`, `platform_name = "openrouter"`.

2. **Tier dispatch**: The collector selects the chat model based on tier:
   - `Tier.MEDIUM` --> `perplexity/sonar`, 5 phrasings per term
   - `Tier.PREMIUM` --> `perplexity/sonar-pro`, 10 phrasings per term
   - `Tier.FREE` --> returns `[]` with warning log

3. **Collection flow** (`collect_by_terms()`):
   1. For each search term, call the query expander to generate N phrasings.
   2. For each phrasing, call the OpenRouter API with the web-search model.
   3. Parse the response: extract `text_content` from `choices[0].message.content`.
   4. Extract citations from either top-level `citations` or `choices[0].message.citations`.
   5. Create one `ai_chat_response` content record per phrasing.
   6. Create one `ai_chat_citation` content record per cited source.
   7. Return all content records.

4. **Deterministic dedup keys**:
   - Response: `sha256(phrasing + model + day_bucket)` where `day_bucket` is the UTC date string (e.g., `"2026-02-17"`).
   - Citation: `sha256(citation_url + phrasing + day_bucket)`.
   This ensures that re-running collection for the same day does not create duplicate records.

5. **Error handling**: HTTP status codes are mapped to typed exceptions:
   - 429 --> `ArenaRateLimitError`
   - 401/403 --> `ArenaAuthError`
   - Other non-2xx --> `ArenaCollectionError`
   - Network errors --> `ArenaCollectionError`
   On `ArenaRateLimitError` or `ArenaAuthError`, the credential pool is notified via `report_error()`.

6. **Temperature**: Always set to `0` for maximum reproducibility. Stored in `raw_metadata` for each response.

7. **HTTP client**: Uses `httpx.AsyncClient` with 30-second timeout for expansion calls and 60-second timeout for chat search calls (Perplexity web search can be slow). An injected client can be provided for testing.

### Files Modified Outside the New Package

Only two files require changes outside the new package:

| File | Change |
|------|--------|
| `workers/celery_app.py` | Add `"issue_observatory.arenas.ai_chat_search.tasks"` to the `include` list |
| `api/main.py` | Mount the `ai_chat_search` router |

**No new database migration is required.** Both content record types (`ai_chat_response` and `ai_chat_citation`) use the existing universal content record schema.

### Polling Strategy

- For ongoing issue tracking: poll key terms once per day.
- For event monitoring: increase to 2--4x/day during active events.
- For baseline snapshots: daily collection of a fixed term list.
- Budget: at Medium tier, 10 terms x 5 phrasings x 1x/day = 50 API calls/day. At approximately $0.001/call for Sonar, this is roughly $1.50/month. The higher estimates ($5--15/month) account for longer responses, more terms, and overhead.

### Schema Note (ADR Candidate)

Storing expanded phrasings for researcher review is a cross-cutting concern that could benefit the Google Search arena as well (e.g., expanding search terms into variant queries). A generic `expanded_phrasings` table (linked to `search_terms`, with `generation_method`, `approved`, `expansion_model` columns) is the right long-term solution. For the initial implementation, phrasings are generated on-the-fly and stored in `raw_metadata` only. This should be revisited as an ADR if multiple arenas adopt query expansion.
