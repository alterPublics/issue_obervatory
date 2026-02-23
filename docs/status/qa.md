# QA Guardian — Status

_Last updated: 2026-02-19 (Greenland Roadmap GR-01 through GR-22 post-implementation QA review — conditional pass, no blockers, 4 warnings)_

---

## Infrastructure Status

| Component | Status | Notes |
|-----------|--------|-------|
| CI pipeline (`.github/workflows/ci.yml`) | DONE | lint + test + security jobs |
| Pre-commit hooks (`.pre-commit-config.yaml`) | DONE | ruff + pre-commit-hooks |
| `tests/conftest.py` | DONE | db_session, client, user fixtures, auth helpers |
| `tests/factories/` | DONE | UserFactory, QueryDesignFactory, ContentRecordFactory |
| Pytest configuration (`pyproject.toml`) | DONE | asyncio_mode=auto, respx added to dev deps |
| `respx` HTTP mock library | ADDED | `pyproject.toml` dev extras, `>=0.21,<0.22` |

---

## Coverage

_Tests are written but cannot be run without a live PostgreSQL instance.
Coverage percentages will be updated after first CI run._

| Component | Required | Status |
|-----------|----------|--------|
| `core/normalizer.py` | 90% | Tests written (unit) |
| `core/credit_service.py` | 85% | Tests written (unit, mock session) |
| `arenas/base.py` | 80% | Tests written (unit) |
| `arenas/google_search/collector.py` | 80% | Tests written (unit, normalize path) |
| `arenas/google_autocomplete/collector.py` | 80% | Tests written — see `tests/arenas/test_google_autocomplete.py` |
| `arenas/bluesky/collector.py` | 80% | Tests written — see `tests/arenas/test_bluesky.py` |
| `arenas/reddit/collector.py` | 80% | Tests written — see `tests/arenas/test_reddit.py` |
| `arenas/youtube/collector.py` | 80% | Tests written — see `tests/arenas/test_youtube.py` |
| `arenas/rss_feeds/collector.py` | 80% | Tests written — see `tests/arenas/test_rss_feeds.py` |
| `arenas/gdelt/collector.py` | 80% | Tests written — see `tests/arenas/test_gdelt.py` |
| `arenas/x_twitter/collector.py` | 80% | Tests written — see `tests/arenas/test_x_twitter.py` |
| `arenas/event_registry/collector.py` | 80% | Tests written — see `tests/arenas/test_event_registry.py` |
| `arenas/threads/collector.py` | 80% | Tests written — see `tests/arenas/test_threads.py` |
| `arenas/ai_chat_search/collector.py` | 80% | Tests written — see `tests/arenas/test_ai_chat_search.py` |
| `arenas/facebook/collector.py` | 80% | Tests written — see `tests/arenas/test_facebook.py` |
| `arenas/instagram/collector.py` | 80% | Tests written — see `tests/arenas/test_instagram.py` |
| `arenas/telegram/collector.py` | 80% | Tests written — see `tests/arenas/test_telegram.py` |
| `arenas/tiktok/collector.py` | 80% | Tests written — see `tests/arenas/test_tiktok.py` |
| `arenas/gab/collector.py` | 80% | Tests written — see `tests/arenas/test_gab.py` |
| `arenas/ritzau_via/collector.py` | 80% | Tests written — see `tests/arenas/test_ritzau_via.py` |
| `arenas/majestic/collector.py` | 80% | Tests written — see `tests/arenas/test_majestic.py` |
| `arenas/web/common_crawl/collector.py` | 80% | Tests written — see `tests/arenas/test_common_crawl.py` |
| `arenas/web/wayback/collector.py` | 80% | Tests written — see `tests/arenas/test_wayback.py` |
| `arenas/ai_chat_search/_openrouter.py` | 80% | Tests written — HTTP error mapping, extract_citations() both formats |
| `arenas/ai_chat_search/_query_expander.py` | 80% | Tests written — prefix stripping, empty-line filtering, n_phrasings cap |
| `arenas/ai_chat_search/_records.py` | 90%+ | Tests written — make_response_record(), make_citation_record(), all fields |
| `sampling/network_expander.py` | 75% | Tests written — see `tests/unit/test_sampling.py` |
| `sampling/similarity_finder.py` | 75% | Tests written — see `tests/unit/test_sampling.py` |
| `sampling/snowball.py` | 75% | Tests written — see `tests/unit/test_sampling.py` |
| `analysis/export.py` | 85% | Tests written (unit, mock session) — see `tests/unit/test_export.py`; Phase C: `_build_dynamic_gexf()`, `export_temporal_gexf()` need tests |
| `analysis/descriptive.py` | 85% | Tests written (unit, mock session) — see `tests/unit/test_descriptive.py`; Phase C: `get_emergent_terms()`, `get_top_actors_unified()` need tests |
| `analysis/network.py` | 85% | Tests written (unit, mock session) — see `tests/unit/test_network.py`; Phase C: `get_temporal_network_snapshots()`, `build_enhanced_bipartite_network()` need tests |
| `analysis/enrichments/base.py` | 85% | Phase C (new file): needs unit tests for `ContentEnricher` ABC and `EnrichmentError` |
| `analysis/enrichments/language_detector.py` | 85% | Phase C (new file): needs tests for `is_applicable()`, `enrich()` with langdetect mock, heuristic fallback, and Danish-char threshold |
| `workers/tasks.py::enrich_collection_run` | 70% | Phase C (new task): needs tests for batch loop, enricher dispatch, unknown enricher warning, retry on DB error |
| `core/credential_pool.py` | 80% | Tests written (unit, mock Redis + mock DB) — see `tests/unit/test_credential_pool.py` |
| `workers/rate_limiter.py` | 80% | Tests written (unit, mock Redis evalsha) — see `tests/unit/test_rate_limiter.py` |
| `core/deduplication.py` | 90%+ | `normalise_url`, `DeduplicationService` covered; `compute_simhash` (8 tests), `hamming_distance` (4 tests) added in `TestComputeSimhash` + `TestHammingDistance` classes (H-01 resolved). |
| `arenas/query_builder.py` | 85%+ | Tests written — `tests/unit/test_query_builder.py` — `build_boolean_query_groups` (8 tests), `format_boolean_query_for_platform` (10 tests), `has_boolean_groups` (3 tests), Danish char preservation (H-06 resolved). |
| `analysis/export.py` (RIS/BibTeX) | 85%+ | `TestExportRis` (8 tests) + `TestExportBibTeX` (6 tests) added to `tests/unit/test_export.py` (H-02 resolved). |
| `api/routes/query_designs.py` (clone) | 85%+ | Integration tests in `tests/integration/test_clone_query_design.py` — 9 tests covering name suffix, search term copy, actor list copy, parent_design_id, UUID generation, 303 redirect, redirect URL, 404, 403 (H-03 resolved). |
| `api/routes/analysis.py` (filtered-export, suggested-terms) | 80%+ | Unit tests in `tests/unit/test_analysis_phase_d_routes.py` — `TestFilteredExport` (7 tests: unknown format 400, 403, 404, content-disposition, RIS MIME, BibTeX MIME, platform filter), `TestSuggestedTerms` (5 tests: required keys, existing terms excluded, 404, 403, empty gracefully) (H-04 + H-05 resolved). |
| `core/schemas/query_design.py` (parse_language_codes) | 90%+ | `tests/unit/test_query_design_schema.py` — 10 tests covering single code, comma-separated, whitespace stripping, empty string fallback, three languages, trailing comma, uppercasing, deduplication, insertion order, None handling (M-01 resolved). |
| `analysis/descriptive.py` (get_top_actors IP2-061) | 90%+ | 3 tests added to `TestGetTopActors` in `tests/unit/test_descriptive.py`: `resolved_name` field present, `resolved_name` is None when no actor row, `actor_id` field present (M-02 resolved). |
| **Overall minimum** | **75%** | Not yet measured; Phase D additions bring several paths to 0%. |

---

## Arena Review Status

| Arena | Review Status | Blocking Issues |
|-------|--------------|-----------------|
| google_search | TESTS WRITTEN | Integration tests (MEDIUM/PREMIUM collect_by_terms, collect_by_actors, health_check) + normalize() unit tests; pending CI run |
| google_autocomplete | TESTS WRITTEN | All checklist items covered; pending CI run |
| bluesky | TESTS WRITTEN | All checklist items covered; pending CI run |
| reddit | TESTS WRITTEN | All checklist items covered; pending CI run |
| youtube | TESTS WRITTEN | All checklist items covered; pending CI run |
| rss_feeds | TESTS WRITTEN | All checklist items covered; pending CI run |
| gdelt | TESTS WRITTEN | All checklist items covered; pending CI run |
| x_twitter | TESTS WRITTEN | normalize() both paths, tweet type detection, MEDIUM/PREMIUM tiers, 429, health_check; pending CI run |
| event_registry | TESTS WRITTEN | normalize(), ISO 639-3 mapping, token budget thresholds, 402, collect_by_actors(); pending CI run |
| threads | TESTS WRITTEN | pagination, collect_by_terms() empty accounts, engagement presence/absence, reply type, MEDIUM stub; pending CI run |
| ai_chat_search | TESTS WRITTEN | extract_citations() Format A/B, HTTP error mapping, query expansion parsing, make_response_record(), make_citation_record(), tier behaviour, collect_by_terms() integration, health_check(); pending CI run |
| facebook | TESTS WRITTEN — pending CI run | normalize() Bright Data + MCL paths, comment detection, reaction aggregation, media URLs, collect_by_terms() full async cycle (trigger→poll→download), collect_by_actors() URL+numeric ID, 429/401/403, PREMIUM NotImplementedError, health_check() ok/degraded/down, Danish chars, 64-char content_hash |
| instagram | TESTS WRITTEN — pending CI run | normalize() Bright Data + MCL paths, Reel detection (product_type/media_type), carousel media URLs, hashtag extraction, collect_by_terms() full async cycle, collect_by_actors() username+URL, 429/401/403, PREMIUM NotImplementedError, _term_to_hashtag() utility, health_check() ok/degraded/down, Danish chars, 64-char content_hash |
| telegram | TESTS WRITTEN — pending CI run | _message_to_dict() field extraction from Telethon mocks, normalize() platform_id={channel}_{msg}, t.me URL construction, reaction sum→likes_count, forwards→shares, replies→comments, media_urls always [], collect_by_terms() + collect_by_actors() with patched Telethon, FloodWait→ArenaRateLimitError, no-credential→NoCredentialAvailableError, non-FREE tier warning, deduplication, health_check() ok/degraded/down, _build_channel_list(), _parse_datetime(), get_tier_config() FREE/MEDIUM/PREMIUM, Danish chars |
| tiktok | TESTS WRITTEN — pending CI run | normalize() OAuth flow, video query, collect_by_terms(), collect_by_actors(), HTTP 429/401, Danish chars, health_check(), tier validation |
| gab | TESTS WRITTEN — pending CI run | normalize() HTML strip, reblog handling, collect_by_terms(), hashtag fallback, collect_by_actors(), HTTP 429/401/422, Danish chars, health_check(), tier validation |
| ritzau_via | TESTS WRITTEN — pending CI run | normalize() HTML strip, publisher author, collect_by_terms(), collect_by_actors(), HTTP 429/500/403, wrapped responses, Danish chars, health_check(), no-credential handling |
| majestic | TESTS WRITTEN — pending CI run | normalize() domain_metrics + backlink paths, TrustFlow as engagement_score, Danish anchor text, collect_by_terms(), collect_by_actors(), API error codes (InvalidAPIKey/RateLimitExceeded/InsufficientCredits), HTTP 429/401, health_check() ok/degraded/down, tier validation |
| common_crawl | TESTS WRITTEN — pending CI run | normalize() web_index_entry, language mapping dan→da, WARC fields in raw_metadata, platform_id from digest, collect_by_terms(), collect_by_actors(), HTTP 429/404, health_check() with collinfo.json fixture, tier validation |
| wayback | TESTS WRITTEN — pending CI run | normalize() web_page_snapshot, language='da' from .dk TLD, wayback_url in raw_metadata, platform_id SHA-256(url+timestamp), collect_by_terms(), collect_by_actors(), HTTP 429/503, health_check() ok/down, Danish URL preservation, tier validation |

---

## Test Files Created (2026-02-17, facebook/instagram/telegram)

### Fixture files

| File | Purpose |
|------|---------|
| `tests/fixtures/api_responses/facebook/brightdata_snapshot_response.json` | Bright Data Facebook snapshot: 5 records — regular post with reaction breakdown (Grøn/Ålborg Danish text), TV2 post, Berlingske photo+carousel, empty-message post, comment post (has comment_id). |
| `tests/fixtures/api_responses/instagram/brightdata_snapshot_response.json` | Bright Data Instagram snapshot: 4 records — image post with Danish caption (Grøn/Ålborg), carousel post with 2 carousel_media items, Reel (product_type=clips, media_type=2, video_view_count=45000), empty-caption post. |
| `tests/fixtures/api_responses/telegram/` | No JSON file (Telethon returns Python objects). Tests use `_make_message()` and `_make_entity()` MagicMock helpers defined in `test_telegram.py`. |

### Test files

| File | Arena | Tests | Key classes |
|------|-------|-------|-------------|
| `tests/arenas/test_facebook.py` | facebook | 28 | TestNormalizeBrightData (21), TestNormalizeMCL (4), TestTierValidation (3), TestCollectByTerms (8), TestCollectByActors (4), TestHealthCheck (5) |
| `tests/arenas/test_instagram.py` | instagram | 34 | TestNormalizeBrightData (23), TestNormalizeMCL (5), TestTermToHashtag (3), TestTierValidation (3), TestCollectByTerms (8), TestCollectByActors (4), TestHealthCheck (5) |
| `tests/arenas/test_telegram.py` | telegram | 39 | TestMessageToDict (11), TestNormalize (19), TestBuildChannelList (3), TestParseDatetime (3), TestCollectByTerms (8), TestCollectByActors (5), TestHealthCheck (5), TestGetTierConfig (3) |

### Mocking strategy

| Arena | HTTP mocking | Other mocking |
|-------|-------------|---------------|
| facebook | `respx` on BRIGHTDATA_TRIGGER_URL (POST), BRIGHTDATA_PROGRESS_URL (GET), BRIGHTDATA_SNAPSHOT_URL (GET); health_check mocked on `api.brightdata.com/datasets/v3` (GET) | `MagicMock` CredentialPool with `AsyncMock.acquire`; `httpx.AsyncClient` injected via `http_client=` constructor param |
| instagram | `respx` on BRIGHTDATA_INSTAGRAM_POSTS_URL (POST), BRIGHTDATA_PROGRESS_URL (GET), BRIGHTDATA_SNAPSHOT_URL (GET); health_check mocked on `api.brightdata.com/datasets/v3` (GET) | `MagicMock` CredentialPool with `AsyncMock.acquire`; `httpx.AsyncClient` injected via `http_client=` constructor param |
| telegram | No HTTP mocking (Telethon uses MTProto, not httpx) | `patch("telethon.TelegramClient", return_value=client_mock)` + `patch("telethon.sessions.StringSession")` + `patch("telethon.errors.FloodWaitError", Exception)` + `patch("telethon.errors.UserDeactivatedBanError", Exception)`; error-path tests use `patch.object(collector, "_collect_*_with_credential", AsyncMock(side_effect=...))` |

---

## Test Files Created (2026-02-16)

### Fixture files

| File | Purpose |
|------|---------|
| `tests/fixtures/api_responses/google_autocomplete/free_response.json` | FREE tier JSON array response with Danish suggestions |
| `tests/fixtures/api_responses/bluesky/search_posts_response.json` | AT Protocol searchPosts response with Danish posts |
| `tests/fixtures/api_responses/reddit/search_response.json` | Reddit Listing API response (informational; asyncpraw is mocked) |
| `tests/fixtures/api_responses/youtube/videos_list_response.json` | YouTube videos.list response with Danish video metadata |
| `tests/fixtures/api_responses/rss_feeds/dr_feed_response.xml` | DR RSS feed XML with Danish article entries |
| `tests/fixtures/api_responses/gdelt/artlist_response.json` | GDELT artlist JSON with Danish news articles |

### Test files

| File | Arena | Tests |
|------|-------|-------|
| `tests/arenas/test_google_autocomplete.py` | google_autocomplete | 20 tests: normalize(), collect_by_terms(), collect_by_actors(), health_check() |
| `tests/arenas/test_bluesky.py` | bluesky | 22 tests: normalize(), collect_by_terms(), health_check() |
| `tests/arenas/test_reddit.py` | reddit | 20 tests: normalize(), collect_by_terms(), health_check() |
| `tests/arenas/test_youtube.py` | youtube | 22 tests: normalize(), collect_by_terms(), health_check() |
| `tests/arenas/test_rss_feeds.py` | rss_feeds | 20 tests: normalize(), collect_by_terms(), health_check() |
| `tests/arenas/test_gdelt.py` | gdelt | 22 tests: normalize(), collect_by_terms(), collect_by_actors(), health_check() |

### Per-arena test coverage matrix

All six arenas have tests covering:

- [x] `normalize()` — correct `platform`, `arena`, `content_type` values
- [x] `normalize()` — `pseudonymized_author_id` is non-None when author present
- [x] `normalize()` — all required schema fields present (`platform`, `arena`, `content_type`, `collected_at`, `collection_tier`)
- [x] `normalize()` — Danish character preservation: æ, ø, å in titles/text (parametrized)
- [x] `collect_by_terms()` — non-empty list returned on success
- [x] `collect_by_terms()` — empty response → returns `[]`, no exception
- [x] `collect_by_terms()` — HTTP 429 → raises `ArenaRateLimitError`
- [x] `collect_by_terms()` — malformed/unexpected response → logs warning, returns `[]`
- [x] `collect_by_terms()` — Danish text preserved end-to-end
- [x] `health_check()` — returns `{"status": "ok"}` on valid response
- [x] `health_check()` — returns degraded/down on error responses
- [x] `collect_by_actors()` — `NotImplementedError` for arenas that don't support it (google_autocomplete, gdelt)

### Mocking strategy

| Arena | HTTP mocking | Other mocking |
|-------|-------------|---------------|
| google_autocomplete | `respx` on `suggestqueries.google.com` | None |
| bluesky | `respx` on `bsky.social` | None |
| reddit | N/A (asyncpraw, no direct HTTP) | `unittest.mock.patch` on `_build_reddit_client` + `asyncpraw.models` MagicMock |
| youtube | N/A (`_client.py` helpers injected) | `unittest.mock.patch` on `search_videos_page`, `fetch_videos_batch`, `make_api_request` |
| rss_feeds | `respx` on feed URLs | None (feedparser parses real XML from response body) |
| gdelt | `respx` on `api.gdeltproject.org` | `patch.object` on `_rate_limit_wait` (avoids 1s sleep) |

---

## Test Files Created (2026-02-16, Phase 2)

### Fixture files

| File | Purpose |
|------|---------|
| `tests/fixtures/api_responses/x_twitter/twitterapiio_response.json` | TwitterAPI.io advanced search response with Danish tweets (tweet, retweet, reply, quote_tweet types) |
| `tests/fixtures/api_responses/event_registry/get_articles_response.json` | Event Registry getArticles response with Danish news articles (lang=dan, remainingTokens field) |
| `tests/fixtures/api_responses/threads/user_threads_response.json` | Threads API user threads response with Danish posts, replies, and engagement fields |

### Test files

| File | Component | Tests |
|------|-----------|-------|
| `tests/arenas/test_x_twitter.py` | x_twitter | 38 tests: normalize() twitterapiio path, normalize() v2 path, tweet type detection (all 4 types), utility functions, collect_by_terms() MEDIUM+PREMIUM, tier validation, health_check() |
| `tests/arenas/test_event_registry.py` | event_registry | 35 tests: normalize() (language mapping, body, Danish chars), collect_by_terms(), collect_by_actors(), token budget WARNING+CRITICAL, HTTP 402, health_check() |
| `tests/arenas/test_threads.py` | threads | 28 tests: normalize() (reply type, engagement presence/absence), collect_by_actors() pagination, collect_by_terms() empty accounts, MEDIUM stub, health_check() |
| `tests/unit/test_sampling.py` | sampling | 32 tests: NetworkExpander (Bluesky follows/followers, co-mentions, Danish names), SimilarityFinder (cross-platform, content with/without sklearn), SnowballSampler (dedup, wave_log, max_actors_per_step) |

### Phase 2 test coverage matrix

All Phase 2 arenas have tests covering:

- [x] `normalize()` — correct `platform`, `arena`, `content_type` values
- [x] `normalize()` — all required schema fields present
- [x] `normalize()` — Danish character preservation: æ, ø, å (parametrized)
- [x] `collect_by_terms()` — non-empty list returned on success
- [x] `collect_by_terms()` — empty response returns `[]`, no exception
- [x] `collect_by_terms()` — HTTP 429 raises `ArenaRateLimitError`
- [x] `collect_by_terms()` — Danish text preserved end-to-end
- [x] `health_check()` — returns `{"status": "ok"}` on valid response
- [x] `health_check()` — returns degraded/down on error responses

X/Twitter specific:
- [x] normalize() dispatches correctly to `_parse_twitterapiio()` and `_parse_twitter_v2()`
- [x] Tweet type detection: tweet, retweet, reply, quote_tweet (both API paths)
- [x] MEDIUM tier acquires credential via `platform="twitterapi_io"`
- [x] PREMIUM tier acquires credential via `platform="x_twitter"`

Event Registry specific:
- [x] `"dan"` maps to `"da"` via `map_language()`
- [x] Article `body` field becomes `text_content`
- [x] Token budget WARNING logged at 20% remaining
- [x] Token budget CRITICAL raises `ArenaCollectionError` at 5% remaining
- [x] HTTP 402 raises `ArenaCollectionError`
- [x] `collect_by_actors()` sends `conceptUri` parameter
- [x] `health_check()` reports `remaining_tokens` field

Threads specific:
- [x] `collect_by_terms()` at FREE with no accounts returns `[]` and logs WARNING
- [x] `collect_by_actors()` pagination advances via cursor
- [x] Engagement fields present for token-owner posts, `None` for others
- [x] `content_type="reply"` when `is_reply=True`
- [x] `Tier.MEDIUM` raises `NotImplementedError` for both collection methods

Sampling specific:
- [x] `NetworkExpander.expand_from_actor()` discovers follows + followers on Bluesky
- [x] `NetworkExpander.find_co_mentioned_actors()` maps DB rows to result dicts
- [x] `SimilarityFinder.cross_platform_match()` returns confidence_score per result
- [x] `SimilarityFinder.find_similar_by_content()` runs with sklearn (TF-IDF path)
- [x] `SimilarityFinder.find_similar_by_content()` runs without sklearn (Jaccard fallback)
- [x] `SnowballSampler.run()` deduplicates actors by platform:user_id key
- [x] `SnowballSampler.run()` populates `wave_log` with discovered counts and methods
- [x] `SnowballSampler.run()` respects `max_actors_per_step`

### Mocking strategy

| Component | HTTP mocking | Other mocking |
|-----------|-------------|---------------|
| x_twitter | `respx` on `api.twitterapi.io` (POST) and `api.twitter.com/2` (GET) | `unittest.mock.MagicMock` for CredentialPool |
| event_registry | `respx` on `newsapi.ai/api/v1/article/getArticles` | `patch.object` on `_rate_limit_wait`; MagicMock CredentialPool |
| threads | `respx` on `graph.threads.net/v1.0/{user_id}/threads` and `/me` | `unittest.mock.patch` on `DEFAULT_DANISH_THREADS_ACCOUNTS`; MagicMock CredentialPool |
| sampling | `respx` on AT Protocol public API endpoints | `unittest.mock.AsyncMock` for DB session; `patch.dict(sys.modules)` for sklearn absence |

---

## Test Files Created (2026-02-17, Phase 3 — ai_chat_search)

### Fixture files

| File | Purpose |
|------|---------|
| `tests/fixtures/api_responses/ai_chat_search/openrouter_chat_response_format_a.json` | Realistic OpenRouter/Perplexity response with top-level `citations` as URL strings (Format A). 5 citations from Danish media sources (dr.dk, berlingske.dk, information.dk, ft.dk, ens.dk). Danish-language `content` field with CO2-afgift text including æ, ø, å characters. |
| `tests/fixtures/api_responses/ai_chat_search/openrouter_chat_response_format_b.json` | Realistic OpenRouter/Perplexity Sonar Pro response with `choices[0].message.citations` as objects with `url`, `title`, `snippet` (Format B). 3 citations with Danish titles and snippets on Grønland topic. |
| `tests/fixtures/api_responses/ai_chat_search/openrouter_expand_response.json` | Response from `google/gemma-3-27b-it:free` for query expansion. 5 Danish CO2-afgift phrasings with `1. ` numbered prefix, to exercise the prefix-stripping parser. |

### Test file

| File | Component | Tests |
|------|-----------|-------|
| `tests/arenas/test_ai_chat_search.py` | ai_chat_search | 62 tests across 8 test classes |

### Test class breakdown

| Class | Tests | Covers |
|-------|-------|--------|
| `TestExtractCitations` | 8 | Format A normalisation, Format B objects, Format B priority over A, empty/missing citations, missing url skipped, empty-string skipped |
| `TestChatCompletion` | 5 | HTTP 200 success, 429 ArenaRateLimitError (retry_after), 401 ArenaAuthError, 403 ArenaAuthError, 500 ArenaCollectionError |
| `TestQueryExpander` | 5 | `_parse_phrasings()` dot prefix, parenthesis prefix, empty-line filter, n_phrasings cap; `expand_term()` returns clean strings |
| `TestMakeResponseRecord` | 13 | content_type, language, platform, arena, author_platform_id, platform_id 64-char hex, content_hash 64-char hex, raw_metadata keys, temperature=0, search_engine_underlying, determinism; parametrized Danish character preservation |
| `TestMakeCitationRecord` | 11 | content_type, arena, domain extraction (dr.dk), full URL, platform_id hex, content_hash = SHA-256(url), text_content=snippet (B), text_content=None (A), title preserved (B), title=None (A), www. subdomain |
| `TestAiChatSearchCollectorClass` | 8 | FREE not in supported_tiers, MEDIUM in supported_tiers, PREMIUM in supported_tiers, collect_by_actors() NotImplementedError, get_tier_config(MEDIUM) requires_credential, get_tier_config(PREMIUM) requires_credential, get_tier_config(FREE) ValueError, collect_by_terms(FREE) returns [] + logs WARNING |
| `TestCollectByTermsIntegration` | 7 | MEDIUM success (response + citation records), MEDIUM field values (platform/language/arena), PREMIUM Format B snippet in text_content, HTTP 429 propagation, HTTP 401 propagation, all-blank phrasings returns [], empty citations → response-only records, no-credential raises |
| `TestHealthCheck` | 5 | OK on successful expansion, down on HTTP 401, down on no credential, arena/platform/checked_at always present, down on HTTP 500 |

### Coverage matrix for ai_chat_search

- [x] `extract_citations()` — Format A (URL strings → normalised dicts with title=None/snippet=None)
- [x] `extract_citations()` — Format B (objects with url/title/snippet → returned as-is)
- [x] `extract_citations()` — Format B priority when both keys present
- [x] `extract_citations()` — empty/missing citations → returns `[]`
- [x] `chat_completion()` — HTTP 429 → `ArenaRateLimitError` with `retry_after`
- [x] `chat_completion()` — HTTP 401 → `ArenaAuthError`
- [x] `chat_completion()` — HTTP 403 → `ArenaAuthError`
- [x] `chat_completion()` — HTTP 500 → `ArenaCollectionError`
- [x] `chat_completion()` — HTTP 200 → returns parsed JSON dict
- [x] `expand_term()` / `_parse_phrasings()` — `"1. "` prefix stripped
- [x] `expand_term()` / `_parse_phrasings()` — `"1) "` prefix stripped
- [x] `expand_term()` / `_parse_phrasings()` — empty lines filtered
- [x] `expand_term()` / `_parse_phrasings()` — respects `n_phrasings` cap
- [x] `make_response_record()` — `content_type="ai_chat_response"`, `language="da"`, `platform="openrouter"`, `arena="ai_chat_search"`
- [x] `make_response_record()` — `author_platform_id` equals model name
- [x] `make_response_record()` — `platform_id` is 64-char hex (SHA-256)
- [x] `make_response_record()` — `content_hash` is 64-char hex
- [x] `make_response_record()` — `raw_metadata` contains all 7 required keys
- [x] `make_response_record()` — `platform_id` is deterministic (same inputs = same ID)
- [x] `make_response_record()` — Danish characters æ, ø, å preserved in `text_content` (parametrized: 3 cases)
- [x] `make_citation_record()` — `content_type="ai_chat_citation"`, `arena="ai_chat_search"`
- [x] `make_citation_record()` — `platform` equals extracted domain (e.g. `"dr.dk"`)
- [x] `make_citation_record()` — `url` equals full citation URL
- [x] `make_citation_record()` — `platform_id` is 64-char hex
- [x] `make_citation_record()` — `content_hash` = SHA-256(url)
- [x] `make_citation_record()` — `text_content` = snippet when snippet present (Format B)
- [x] `make_citation_record()` — `text_content` = None when snippet absent (Format A)
- [x] `make_citation_record()` — `title` preserved when present (Format B), None when absent (Format A)
- [x] `Tier.FREE` → `collect_by_terms()` returns `[]` and logs WARNING
- [x] `Tier.MEDIUM` and `Tier.PREMIUM` in `supported_tiers`
- [x] `collect_by_actors()` → `NotImplementedError`
- [x] `get_tier_config(MEDIUM)` and `get_tier_config(PREMIUM)` → `requires_credential=True`
- [x] `collect_by_terms()` MEDIUM success → both `ai_chat_response` and `ai_chat_citation` records returned
- [x] `collect_by_terms()` PREMIUM with Format B → citation records have snippet in `text_content`
- [x] `collect_by_terms()` HTTP 429 on chat call → `ArenaRateLimitError` propagated
- [x] `collect_by_terms()` HTTP 401 on chat call → `ArenaAuthError` propagated
- [x] `collect_by_terms()` all-blank phrasings → `[]` returned, no exception
- [x] `collect_by_terms()` empty citations in response → only `ai_chat_response` records, no `ai_chat_citation`
- [x] `health_check()` success → `{"status": "ok", "arena": "ai_chat_search", "platform": "openrouter", "checked_at": ..., "detail": ...}`
- [x] `health_check()` HTTP 401 → `{"status": "down"}`
- [x] `health_check()` no credential → `{"status": "down", "detail": "No credential ..."}`
- [x] `health_check()` HTTP 500 → `{"status": "down"}`

### Mocking strategy

| Layer | Mechanism |
|-------|-----------|
| HTTP calls to `https://openrouter.ai/api/v1/chat/completions` | `respx.mock` context manager; `respx.post(OPENROUTER_API_URL).mock(...)` |
| `CredentialPool` | `unittest.mock.MagicMock` with `AsyncMock` for `.acquire()` and `.release()` |
| `httpx.AsyncClient` injection | Collector constructed with `http_client=client` inside `respx.mock` context |
| No-credential cases | `monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)` + `credential_pool=None` |

---

## Test Files Created (2026-02-17, Infrastructure Unit Tests)

### Test files

| File | Component | Tests |
|------|-----------|-------|
| `tests/unit/test_credential_pool.py` | `core/credential_pool.py` | 27 tests: NoCredentialAvailableError, _is_uuid(), _decrypt_credentials() (dict passthrough + Fernet roundtrip + tampered bytes), _discover_env_credentials() (primary/numbered/empty/prefix), acquire() env-var path (happy path, no credential, cooldown, circuit breaker, rotation, DB credential lease), release() (task_id, wildcard scan, Redis error swallowed), report_error() env path (count increment, accumulation, ArenaRateLimitError cooldown, ArenaAuthError cooldown, generic no-cooldown, circuit breaker blocks acquisition), report_error() DB path (Redis cooldown key set, max cooldown at threshold), _is_on_cooldown(), _is_quota_exceeded() (daily, monthly, none), _increment_quota() (first call sets TTL, subsequent call skips TTL), _seconds_until_midnight_utc(), _seconds_until_month_end_utc(), get_credential_pool() singleton |
| `tests/unit/test_rate_limiter.py` | `workers/rate_limiter.py` | 27 tests: RateLimitTimeoutError (attributes, message, is Exception), RateLimitConfig (defaults, custom), ARENA_DEFAULTS (reddit hourly, bluesky minute, youtube daily), _key() (namespaced string, all components, day window), _resolve_config() (caller override, arena default, unknown arena global default), acquire() (returns True/False from Lua result, True when Redis down, key arg passed correctly), check_and_acquire() (all windows available, minute exhausted, rollback on second window fail, True when Redis down, burst_size added to limit), is_rate_limited() (True/False from count vs limit, False when Redis down), get_wait_time() (0 when not limited, 0 when Redis down, positive when exhausted), wait_for_slot() (immediate return, RateLimitTimeoutError, succeeds after retry, key in error message), reset() (deletes all window keys, swallows Redis error), rate_limited_request() (clean enter/exit, exception propagates, sleeps until slot) |
| `tests/unit/test_deduplication.py` | `core/deduplication.py` | 28 tests: normalise_url() (lowercase, www strip, no-www unchanged, utm_source, utm_medium, utm_campaign, fbclid, gclid, _ga, ref, non-tracking preserved, sorted params, trailing slash stripped, root path preserved, malformed URL, identical after tracking stripped, distinct paths distinct), find_url_duplicates() (empty, unique URLs, shared URL two platforms, null URL ignored, group has platform/arena keys), find_hash_duplicates() (empty, same hash different platforms, same platform/arena not surfaced, distinct hashes not grouped, count field), mark_duplicates() (returns 0 for empty list, calls db.execute, returns rowcount), run_dedup_pass() (correct summary keys, zero counts, calls commit, marks URL duplicates with canonical election, url_groups count), get_deduplication_service() (returns instance, new instance each call) |

### Mocking strategy

| Component | Mocking |
|-----------|---------|
| credential_pool | Redis client via `MagicMock` with `AsyncMock` on `.get`, `.setex`, `.delete`, `.incr`, `.expire`, `.keys`; DB queries patched with `patch.object`; no live DB or Redis |
| rate_limiter | Redis client via `MagicMock` with `AsyncMock` on `.script_load`, `.evalsha`, `.zrem`, `.delete`; SHA cache pre-populated to skip `_ensure_scripts_loaded`; `asyncio.sleep` patched where needed |
| deduplication | `AsyncSession` via `MagicMock` with `AsyncMock` on `.execute` returning named-tuple rows; `DeduplicationService` methods patched individually in `run_dedup_pass` tests; no live DB |

---

## Test Files Created (2026-02-17, Phase 4 — majestic, common_crawl, wayback, google_search)

### Fixture files

| File | Purpose |
|------|---------|
| `tests/fixtures/api_responses/majestic/get_index_item_info_response.json` | Majestic `GetIndexItemInfo` response with two Danish domains (dr.dk TrustFlow=68, politiken.dk TrustFlow=62), full metrics fields including topical trust flow |
| `tests/fixtures/api_responses/majestic/get_backlink_data_response.json` | Majestic `GetBackLinkData` response with three backlinks to dr.dk, including Danish anchor text ("Grøn omstilling", "Velfærd og bæredygtighed") |
| `tests/fixtures/api_responses/common_crawl/index_search_response.ndjson` | CC Index NDJSON response with four Danish .dk captures (dr.dk, politiken.dk, berlingske.dk, tv2.dk), Danish URLs with æ/ø/å, languages="dan" and "dan,eng" |
| `tests/fixtures/api_responses/common_crawl/collinfo_response.json` | CC collinfo.json response listing three crawl indexes (CC-MAIN-2025-51, -47, -42) |
| `tests/fixtures/api_responses/wayback/cdx_response.json` | Wayback Machine CDX API 2D JSON array with four .dk domain captures including field names header row |
| `tests/fixtures/api_responses/google_search/serpapi_organic.json` | SerpAPI `organic_results` response for "klimaforandringer" with three Danish results; snippets contain Grønland, Færøerne, Velfærdsstatens, Ålborg |

### Test files

| File | Arena | Tests |
|------|-------|-------|
| `tests/arenas/test_majestic.py` | majestic | 37 tests: normalize() domain_metrics (15) + backlink (8), collect_by_terms() PREMIUM (11), collect_by_actors() (2), health_check() (6), tier config (3) |
| `tests/arenas/test_common_crawl.py` | common_crawl (web) | 32 tests: normalize() (18 incl. 6 parametrized Danish chars), collect_by_terms() (8), collect_by_actors() (2), health_check() (4), tier config (3) |
| `tests/arenas/test_wayback.py` | wayback (web) | 37 tests: normalize() (17 incl. 6 parametrized Danish chars), collect_by_terms() (8), collect_by_actors() (2), health_check() (5), tier config (3) |
| `tests/arenas/test_google_search.py` | google_search | 25 tests: collect_by_terms() MEDIUM (9) + PREMIUM (3), collect_by_actors() (3), no-credential (1), health_check() (4) |

### Phase 4 test coverage matrix

All four arenas have tests covering:

- [x] `normalize()` — correct `platform`, `arena`, `content_type` values
- [x] `normalize()` — all required schema fields present (`platform`, `arena`, `content_type`, `collected_at`, `collection_tier`)
- [x] `normalize()` — `content_hash` is a 64-char hex string (where applicable)
- [x] `normalize()` — Danish character preservation: æ, ø, å in URLs/text (parametrized)
- [x] `collect_by_terms()` — non-empty list returned on success
- [x] `collect_by_terms()` — empty response returns `[]`, no exception
- [x] `collect_by_terms()` — HTTP 429 raises `ArenaRateLimitError`
- [x] `collect_by_terms()` — HTTP 401/403 raises `ArenaAuthError` (majestic, google_search)
- [x] `collect_by_terms()` — Danish text/URLs preserved end-to-end
- [x] `collect_by_actors()` — functional for all four arenas
- [x] `health_check()` — returns `{"status": "ok"}` on valid response
- [x] `health_check()` — returns `"down"` or `"degraded"` on error responses
- [x] `health_check()` — always includes `checked_at`, `arena`, `platform`

Majestic-specific: domain_metrics vs backlink dispatch, API error codes (InvalidAPIKey/RateLimitExceeded/InsufficientCredits), FREE/MEDIUM NotImplementedError, degraded on TrustFlow=0.

Common Crawl-specific: platform_id from digest fallback, dan→da language mapping, WARC fields in raw_metadata, graceful 404 handling.

Wayback-specific: language='da' inferred from .dk TLD, wayback_url in raw_metadata, 503 handled gracefully (no exception), CDX field preservation.

Google Search-specific: MEDIUM→Serper.dev POST, PREMIUM→SerpAPI GET, actor→site: conversion, FREE tier returns [] + logs WARNING, no-credential raises NoCredentialAvailableError.

### Mocking strategy

| Component | HTTP mocking | Other mocking |
|-----------|-------------|---------------|
| majestic | `respx` on `https://api.majestic.com/api/json` (GET) | `patch.object` on `_rate_limit_wait`; `MagicMock` CredentialPool |
| common_crawl | `respx` on CC Index search URL (GET) and `CC_COLLINFO_URL` | `patch.object` on `_rate_limit_wait` |
| wayback | `respx` on `WB_CDX_BASE_URL` (GET) | `patch.object` on `_rate_limit_wait` |
| google_search | `respx` on `SERPER_API_URL` (POST) and `SERPAPI_URL` (GET) | `MagicMock` CredentialPool with `AsyncMock.acquire` |

---

## Phase A Refactoring — Test Fixes (2026-02-18)

### Background

Phase A refactored the analysis layer to always exclude duplicate records by centralising
filter logic in `src/issue_observatory/analysis/_filters.py`.  The new module's two
public functions — `build_content_filters()` and `build_content_where()` — always append
the predicate `(raw_metadata->>'duplicate_of') IS NULL` regardless of what other filters
the caller supplies.  This broke five existing unit tests that asserted pre-refactoring
behaviour (empty clause lists / empty WHERE strings when no filters were given).

### Tests Fixed

| ID | File | Line (old) | Old assertion | New assertion |
|----|------|-----------|--------------|--------------|
| C-1a | `tests/unit/test_descriptive.py` | 175 | `assert result == ""` | `assert result.startswith("WHERE")` and `"(raw_metadata->>'duplicate_of') IS NULL" in result` |
| C-1b | `tests/unit/test_network.py` | 175 | `assert clauses == []` | `assert len(clauses) == 1` and duplicate exclusion in `clauses[0]` |
| C-1c | `tests/unit/test_network.py` | 206 | `assert len(clauses) == 2` | `assert len(clauses) == 3` (2 dates + dup exclusion) |
| C-1d | `tests/unit/test_network.py` | 214 | `assert clause.startswith("cr.")` (all clauses) | Assert `"cr." in clause` for all; `clause.startswith("cr.")` only for non-dup-exclusion clauses |
| C-1e | `tests/unit/test_export.py` | 146 | `assert col in header_line` (snake_case) | `assert _COLUMN_HEADERS.get(col, col) in header_line` (human-readable labels) |

### New Test Files Added

| File | Module under test | Tests |
|------|------------------|-------|
| `tests/unit/test_filters.py` | `analysis/_filters.py` | 20 tests: `build_content_filters()` with no args, query_design_id, run_id, both, arena/platform, date range, table alias; `build_content_where()` with no args, all filters, always non-empty, date predicates |
| `tests/unit/test_arenas_route.py` | `api/routes/arenas.py` | 9 tests: `list_available_arenas()` returns all arenas from `list_arenas()`, each has correct fields, `has_credentials=True/False` correctly computed, empty registry, supported_tiers preserved, `autodiscover()` called exactly once |
| `tests/unit/test_content_route_search_terms.py` | `api/routes/content.py::get_search_terms_for_run` | 9 tests: no `run_id` → default option only; with `run_id` and terms → all options; no terms → default only; HTML special chars escaped (XSS); Danish chars (æ, ø, å) preserved; response is HTMLResponse 200; admin and non-admin trigger DB execute; term order preserved |
| `tests/unit/test_analysis_route_filter_options.py` | `api/routes/analysis.py::get_filter_options` | 8 tests: valid `run_id` returns platforms+arenas; unknown `run_id` → empty lists; ownership failure → empty lists; empty content records → empty lists; response always has both keys; multiple platforms in DB order; `None` values excluded; 2 DB `execute()` calls for valid run |

---

## Test Files Written (2026-02-18, Phase D — Test Gap Closure)

### New and Modified Files

| File | Gap | Tests Added | Strategy |
|------|-----|-------------|----------|
| `tests/unit/test_deduplication.py` | H-01 | `TestComputeSimhash` (8 tests), `TestHammingDistance` (4 tests) — 12 total | Pure-function tests; no mocking needed. `compute_simhash` and `hamming_distance` added to top-level import block. |
| `tests/unit/test_export.py` | H-02 | `TestExportRis` (8 tests), `TestExportBibTeX` (6 tests) — 14 total | Synchronous (no `@pytest.mark.asyncio` needed since `export_ris` and `export_bibtex` are sync methods). Use existing `EXPORTER`, `_make_record()`, `DANISH_TEXT`, `DANISH_AUTHOR` helpers. |
| `tests/unit/test_query_builder.py` | H-06 | `TestBuildBooleanQueryGroups` (8 tests), `TestFormatBooleanQueryForPlatform` (10 tests), `TestHasBooleanGroups` (3 tests) — 21 total | Pure-function tests; no mocking. All platform formatters tested. |
| `tests/integration/test_clone_query_design.py` | H-03 | `TestCloneQueryDesign` (9 tests) — requires live DB | Live DB integration tests using `client` + `db_session` + `test_user` fixtures. `follow_redirects=False` to verify the 303 status code directly. |
| `tests/unit/test_analysis_phase_d_routes.py` | H-04, H-05 | `TestFilteredExport` (7 tests), `TestSuggestedTerms` (5 tests) — 12 total | Mock `_get_run_or_raise` via `patch`. Mock DB session for ORM row results. Functions called directly (not via HTTP) with plain Python args. |
| `tests/unit/test_query_design_schema.py` | M-01 | `TestParseLanguageCodes` (10 tests) | Pure-function tests; no mocking. |
| `tests/unit/test_descriptive.py` | M-02 | 3 tests appended to `TestGetTopActors` class | Mock SQL rows with `resolved_name` and `author_id` attributes; verify fields in returned dicts. |

### Test Count Summary (Phase D additions only)

| Gap | Tests | Status |
|-----|-------|--------|
| H-01 (SimHash) | 12 | RESOLVED |
| H-02 (RIS/BibTeX export) | 14 | RESOLVED |
| H-03 (clone endpoint) | 9 | RESOLVED |
| H-04 (filtered-export route) | 7 | RESOLVED |
| H-05 (suggested-terms route) | 5 | RESOLVED |
| H-06 (query_builder) | 21 | RESOLVED |
| M-01 (parse_language_codes) | 10 | RESOLVED |
| M-02 (get_top_actors resolved_name) | 3 | RESOLVED |
| **Phase D total** | **81** | **All gaps resolved** |

### Key Design Decisions

- `export_ris()` and `export_bibtex()` are synchronous methods (not `async`). Tests in `TestExportRis` and `TestExportBibTeX` are plain `def` (no `@pytest.mark.asyncio`).
- `test_compute_simhash_very_different_texts_have_higher_hamming_distance_than_similar` uses a relative comparison (different pair distance >= similar pair distance) rather than an absolute threshold, because SimHash bit distribution is probabilistic and an absolute threshold could flake.
- `test_clone_copies_actor_list_structure` tests actor list name/ID copying without members, since member tests require a pre-existing `Actor` row in the actors table (not provided by the conftest fixtures).
- Integration tests in `test_clone_query_design.py` use `follow_redirects=False` to capture the raw 303 response; the `client` fixture uses `follow_redirects=True` by default, so the test must override this per-call.

---

## Open Issues

### Priority: High (Phase C — tests required before merge)

The following Phase C functions are unblocked (no correctness issues) but have
zero test coverage.  Tests must be written before the Phase C branch is merged.

**`tests/unit/test_descriptive.py`** — add:

- `test_get_emergent_terms_returns_empty_when_sklearn_missing` — patch `sklearn` import to raise `ImportError`; assert result is `[]`.
- `test_get_emergent_terms_returns_empty_when_fewer_than_5_records` — mock DB returning 4 rows; assert result is `[]`.
- `test_get_emergent_terms_excludes_existing_search_terms` — mock DB with text content and a `search_terms` row; assert the existing term is not in the returned list.
- `test_get_emergent_terms_returns_top_n_by_score` — mock DB with 20+ text records; assert `len(result) <= top_n`.
- `test_get_emergent_terms_preserves_danish_characters` — include `"æøå"` in mock text content; assert term appears in output.
- `test_get_top_actors_unified_returns_empty_when_no_resolved_actors` — mock DB returning empty result set; assert result is `[]`.
- `test_get_top_actors_unified_groups_across_platforms` — mock DB returning two rows with same `author_id` but different `platform`; assert `platforms` list contains both.
- `test_get_top_actors_unified_total_engagement_coalesced` — mock DB returning null engagement; assert `total_engagement = 0`.

**`tests/unit/test_network.py`** — add:

- `test_get_temporal_network_snapshots_returns_empty_for_no_records` — mock DB `range_sql` returning `None`; assert result is `[]`.
- `test_get_temporal_network_snapshots_interval_not_downgraded_when_date_span_small` — mock DB range = 10 days, request `interval="week"`; assert `effective_interval == "week"` (not "day").
- `test_get_temporal_network_snapshots_interval_upgraded_to_month_for_large_span` — mock DB range = 400 days, request `interval="day"`; assert `effective_interval == "month"`.
- `test_get_temporal_network_snapshots_raises_for_invalid_interval` — assert `ValueError` on `interval="hour"`.
- `test_get_temporal_network_snapshots_raises_for_invalid_network_type` — assert `ValueError` on `network_type="bipartite"`.
- `test_build_enhanced_bipartite_network_with_empty_emergent_terms` — empty list; assert graph has only `term_type="search_term"` on term nodes.
- `test_build_enhanced_bipartite_network_adds_emergent_term_nodes` — non-empty emergent_terms; assert at least one node has `term_type="emergent_term"`.
- `test_build_enhanced_bipartite_network_skips_duplicate_search_terms` — emergent term already in base graph; assert no duplicate node.

**`tests/unit/test_export.py`** — add:

- `test_export_temporal_gexf_returns_bytes` — call `export_temporal_gexf([])` with empty snapshot list; assert result is `bytes`.
- `test_build_dynamic_gexf_mode_is_dynamic` — parse output XML; assert `graph[@mode] == "dynamic"`.
- `test_build_dynamic_gexf_node_has_spells` — one snapshot, two nodes; assert each node has `<spells>` child.
- `test_build_dynamic_gexf_edge_has_start_end` — one snapshot, one edge; assert edge element has `start` and `end` attributes.
- `test_export_gexf_enhanced_bipartite_routes_to_bipartite_serializer` — call `export_gexf(graph, network_type="enhanced_bipartite")`; assert result is valid GEXF bytes without `ValueError`.

**`tests/unit/test_enrichments.py`** (new file) — create with:

- `test_danish_language_detector_is_applicable_true_when_no_language_and_has_text`
- `test_danish_language_detector_is_applicable_false_when_language_set`
- `test_danish_language_detector_is_applicable_false_when_text_empty`
- `test_danish_language_detector_enrich_uses_langdetect_when_installed` — mock `langdetect.detect_langs`
- `test_danish_language_detector_enrich_falls_back_to_heuristic_when_langdetect_missing` — patch import to raise `ImportError`
- `test_danish_language_detector_heuristic_returns_da_above_threshold` — text with >0.5% Danish chars
- `test_danish_language_detector_heuristic_returns_none_below_threshold` — text with no Danish chars
- `test_enrichment_error_is_exception` — assert `isinstance(EnrichmentError(), Exception)`
- `test_content_enricher_repr` — assert `repr(DanishLanguageDetector())` contains enricher_name

**`tests/unit/test_tasks.py`** — add to existing file:

- `test_enrich_collection_run_processes_all_batches` — mock `fetch_content_records_for_run` returning two batches then `[]`; assert `records_processed` equals total records.
- `test_enrich_collection_run_skips_non_applicable_records` — `is_applicable` always False; assert `enrichments_applied == 0`.
- `test_enrich_collection_run_logs_warning_for_unknown_enricher_names` — pass `enricher_names=["nonexistent"]`; assert `enrichers` list is empty and task returns early.
- `test_enrich_collection_run_retries_on_db_error` — first call to `fetch_content_records_for_run` raises; assert `self.retry` called.

### Priority: Medium

- `tests/unit/test_credit_service.py` — Tests use mock session. Integration tests against real DB (testing the SQL formulae) are needed and should live in `tests/integration/test_credit_service_integration.py`. This is not blocking Phase 0 completion.

- `tests/integration/test_auth_flow.py` — Some route stubs (query-designs POST) use `pytest.skip()` when the endpoint returns 404. These tests will activate automatically as routes are implemented.

- `tests/conftest.py` — The `CREDENTIAL_ENCRYPTION_KEY` default `dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==` is a placeholder that is NOT a valid Fernet key (Fernet requires exactly 32 URL-safe base64-encoded bytes). The CI workflow correctly references `${{ secrets.CREDENTIAL_ENCRYPTION_KEY }}`. For local development, generate a real key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and set it in your `.env` file.

- `tests/arenas/test_reddit.py` — Reddit's `collect_by_terms()` is tested with a mocked asyncpraw client. The TooManyRequests exception test requires asyncprawcore to be installed; this is a direct dependency of asyncpraw and will be present in any environment where asyncpraw is installed.

### Priority: Low

- `tests/fixtures/sample_data/` — Known-good normalized records for schema validation tests not yet written.

- `tests/unit/test_logging.py` — Pre-existing test; should be reviewed to confirm it still passes after conftest env bootstrap.

---

## Fixed (Phase C — 2026-02-18)

| ID | Severity | File | Description |
|----|----------|------|-------------|
| PC-01 | High | `src/issue_observatory/analysis/network.py` lines 711–717 | **Interval auto-upgrade logic could downgrade the requested interval.** The original `break` condition `if candidate == interval or interval in ("week", "month")` fired on the first candidate that fit within `_MAX_BUCKETS`, even when that candidate was finer-grained (e.g. "day") than the requested "week". Fixed: the loop now stops only when `_interval_order.index(candidate) >= _interval_order.index(interval)`, guaranteeing the effective interval is always equal to or coarser than what the caller requested. |
| PC-02 | Low | `src/issue_observatory/analysis/network.py` line 704 | **Dead import.** `from datetime import timedelta` was imported inside `get_temporal_network_snapshots` but `timedelta` was never referenced. Removed. |
| PC-03 | Low | `src/issue_observatory/analysis/export.py` lines 713–721 | **Duplicate docstring section.** The `export_gexf` method docstring contained the "All three output formats:" bullet list twice. The second copy was removed. |
| PC-04 | Low | `src/issue_observatory/analysis/enrichments/language_detector.py` | **Unused stdlib import.** `import logging` and `_stdlib_logger = logging.getLogger(__name__)` were defined but never referenced anywhere in the file. All logging in `language_detector.py` uses `structlog`. Both declarations removed. |

---

## Fixed (Phase 3 — 2026-02-17)

| ID | Severity | File | Description |
|----|----------|------|-------------|
| DQ-02 | Critical | `src/issue_observatory/analysis/export.py` | GEXF edge construction was grouping all authors by `collection_run_id`, producing a full graph. Fixed to group authors by shared `search_terms_matched` entries. Edge weight now equals number of distinct shared terms; `shared_terms` attribute contains the true intersection of terms. Regression tests in `tests/unit/test_export.py::TestExportGexfActor::test_gexf_actor_edge_weight_equals_shared_term_count` and `test_gexf_actor_grouping_by_term_not_by_run_id`. |
| DQ-01 | High | `src/issue_observatory/arenas/bluesky/collector.py` | `_fetch_author_feed()` returned all posts regardless of language. Added client-side filter: posts with a `langs` array that does not contain `"da"` are excluded; posts with no `langs` field are included. The AT Protocol `getAuthorFeed` endpoint does not support a server-side `lang` parameter. |
| DQ-03 | Medium | `docs/guides/what_data_is_collected.md` | Documentation claimed 7 subreddits (r/Denmark, r/danish, r/copenhagen, r/aarhus, r/dkfinance, r/scandinavia, r/NORDVANSEN). Code (`danish_defaults.py`) contains only 4. Documentation updated to match code. |

---

## Blocked

### B-01 — Snowball sampling: no UI entry point [HIGH]

**Reported:** 2026-02-17 (Phase 3 UX review, B-01)
**Responsible:** [core][frontend]
**Files:** `src/issue_observatory/sampling/snowball.py` (backend complete); `src/issue_observatory/api/templates/actors/list.html`, `src/issue_observatory/api/templates/actors/detail.html` (no UI surface)
**Detail:** `SnowballSampler` is fully implemented. No page in the application surfaces a "Run snowball sampling" action. The actor list has no such button. The actor detail page's Entity Resolution section handles merge/split only. There is no API route visible from any template that would trigger a snowball run.
**Impact:** Actor discovery is a stated Phase 3 feature and is completely unreachable through the UI. Researchers cannot use it without calling the API directly.
**Required fix:** Add a "Discover related actors" button to `actors/list.html` or `actors/detail.html`. Wire it to the `SnowballSampler` via a new API route. Present results as a reviewable list with platform, username, discovery depth, and an "Add to query design" action.

### B-02 — GEXF export: term and bipartite network types not implemented [HIGH]

**Reported:** 2026-02-17 (Phase 3 UX review, B-02)
**Responsible:** [core][frontend]
**Files:** `src/issue_observatory/api/templates/analysis/index.html` lines 308-363; `src/issue_observatory/analysis/export.py`
**Detail:** All three "Download ... (GEXF)" buttons (`actor network`, `term network`, `bipartite network`) link to the same endpoint `/content/export?format=gexf&run_id={{ run_id }}` with no `network_type` parameter. `export_gexf()` only implements actor co-occurrence. Term and bipartite exports are not implemented.
**Impact:** A researcher selecting the "Term network" tab and clicking download receives an actor co-occurrence GEXF file. This is a silent data integrity failure — the file appears valid but represents the wrong network type.
**Required fix:** Add `network_type=actor|term|bipartite` parameter support to the export endpoint. Update the three download buttons to pass the appropriate parameter. Implement `export_gexf_terms()` and `export_gexf_bipartite()` methods, or remove the Term and Bipartite buttons until implemented.

### B-03 — Live tracking: no schedule visibility, no suspend [MEDIUM]

**Reported:** 2026-02-17 (Phase 3 UX review, B-03)
**Responsible:** [core][frontend]
**Files:** `src/issue_observatory/api/templates/collections/detail.html`; `src/issue_observatory/workers/beat_schedule.py`
**Detail:** The collection detail page provides no information about when a live-tracking collection will next fire (beat schedule: `crontab(hour=0, minute=0)` = midnight Copenhagen). There is no "pause/suspend" function — only permanent cancel. Beat-triggered runs are not distinguishable from manually-triggered runs in the task table.
**Impact:** A researcher cannot confirm their live collection is active, cannot pause it during a holiday, and cannot see a separate log of automatic vs. manual runs.
**Required fix:** Add a "Next scheduled run: [timestamp]" display to the collection detail page for live-mode collections. Add a suspend/pause action that disables beat-triggered runs without deleting the collection. Distinguish beat-triggered task rows from manual-trigger rows in the task table.

---

_Phase 1 and Phase 2 arenas remain unblocked. Blocking authority will be exercised if CI reveals coverage below 75% or if normalize() tests reveal data integrity issues when run against a live environment._

---

## Phase D QA Review (2026-02-18)

**Overall verdict: APPROVED WITH WARNINGS**

No blocking issues found. Six high-priority test gaps must be resolved before the Phase D branch is merged into main.

---

### Check Results

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | All new Python files: `from __future__ import annotations`, type hints, docstrings, no wildcard imports | PASS | `deduplication.py`, `query_builder.py`, `export.py` (new methods), `query_design.py` (schema), migrations 007/008 all conform. `deduplication.py` has one deferred import (`from collections import defaultdict` inside a function body at lines 197, 362, 427) — acceptable pattern for deferred imports, not a wildcard import. |
| 2 | All new async DB functions use `await` | PASS | `find_near_duplicates()`, `detect_and_mark_near_duplicates()`, `clone_query_design()`, `filtered_export()`, `suggested_terms()` all use `await db.execute(...)`. |
| 3 | No synchronous DB calls in async context | PASS | No blocking ORM calls found. `export_ris()` and `export_bibtex()` are synchronous but are pure CPU functions not touching the DB; they are called from an async route handler via a synchronous call, which is acceptable for fast CPU-only work. |
| 4 | Error handling: 404/403 on missing/unauthorized resources | PASS | `clone_query_design()` raises 404 when design not found; calls `ownership_guard()` for 403. `filtered_export()` calls `_get_run_or_raise()` which raises 404 and 403. `suggested_terms()` calls `_get_run_or_raise()`. `filtered_export()` raises 400 on unknown format. |
| 5 | No XSS vulnerabilities in new template code | PASS | `_render_term_list_item()` and `_render_actor_list_item()` use `_html_escape()` which escapes `&`, `<`, `>`, `"`, `'`. Injected values in HTML fragments are sanitised. |
| 6 | SimHash migration 007: raw ALTER TABLE DDL, index on parent table | PASS | Migration uses `op.execute("ALTER TABLE content_records ADD COLUMN IF NOT EXISTS simhash BIGINT NULL")` — correctly bypasses `op.add_column()` which does not propagate to child partitions. Index created on parent table via `op.execute("CREATE INDEX IF NOT EXISTS idx_content_records_simhash ON content_records (simhash)")`. Both documented in the migration module docstring. |
| 7 | SimHash algorithm: 64-bit integer, Hamming distance uses XOR | PASS | `compute_simhash()` accumulates 64-element weight vector and sets bits to produce an unsigned 64-bit integer. `hamming_distance(a, b)` returns `bin(a ^ b).count("1")` — correct XOR-based popcount. |
| 8 | Cloning deep copy: SearchTerm.group_id/group_label copied; new ActorListMember rows; new IDs | PASS | `clone_query_design()` at lines 399-408 copies `term.group_id` and `term.group_label` into new `SearchTerm` instances. New `ActorList` objects are created for each actor list. New `ActorListMember` rows reference the new list ID. New UUIDs are generated via ORM default (`id` not set, generated by the DB). |
| 9 | Boolean query builder: correct group_id grouping, at least one collector uses native boolean syntax | PASS | `build_boolean_query_groups()` uses `OrderedDict` keyed by `str(group_id)` for named groups and synthetic `__null_N__` keys for ungrouped terms — correct AND-within-group, OR-across-groups logic. `format_boolean_query_for_platform()` implements platform-native syntax for Google, Twitter/X, Reddit, YouTube, GDELT, Bluesky. Reddit uses `+` join (Lucene AND). |
| 10 | Multilingual parsing: `parse_language_codes("da,en")` = `["da", "en"]`, `parse_language_codes("da")` = `["da"]` | PASS | `parse_language_codes()` splits on `,`, strips whitespace, lowercases, deduplicates in insertion order. Returns `["da"]` as fallback when input is empty. The function returns `["da"]` for `"da"` and `["da", "en"]` for `"da,en"`. |
| 11 | `get_top_actors()` LEFT JOIN uses `actor_id` FK correctly; NULL actors do not break query | PASS | SQL in `descriptive.py` lines 255-277: `LEFT JOIN actors a ON a.id = c.author_id`. `MAX(a.canonical_name)` aggregate handles NULL gracefully (MAX of NULL = NULL). Output dict uses `row.resolved_name` which is None when no actor row exists. |
| 12 | RIS format: correct tags, each record ends with `ER  - ` | PASS | `export_ris()` produces: `TY  - ELEC`, `TI  - `, `AB  - `, `AU  - `, `UR  - `, `PY  - `, `DP  - `, `N1  - `, `ER  - `. Each record ends with `ER  - ` (line 965) followed by a blank line separator. The `ER  - ` line terminates each entry correctly per RIS spec. NOTE: `ER  - ` has a trailing space after the dash — this matches the RIS specification (two spaces, dash, two spaces). |
| 13 | BibTeX format: unique entry keys, `{` and `}` escaped in field values | PASS | Entry keys are `record_{content_hash[:8]}` — unique when content hashes are unique; fallback uses SHA-256 of URL. `_tex()` escapes `\\` first (to avoid double-escaping), then `{` to `\{` and `}` to `\}`. Backslash-first ordering is correct. |
| 14 | Filtered export: ownership check present; unknown format raises 400 | PASS | `filtered_export()` calls `_get_run_or_raise(run_id, db, current_user)` which enforces ownership. Unknown format check at line 1146: `if format not in _EXPORT_CONTENT_TYPES: raise HTTPException(400, ...)`. |
| 15 | `network_preview.js`: exports `window.initNetworkPreview` and `window.destroyNetworkPreview`; WebGL context leak prevention via singleton registry | PASS | `_instances = new Map()` at module scope (line 86) acts as the singleton registry. `initNetworkPreview` kills existing instance before creating new one (lines 195-198). `destroyNetworkPreview` kills and removes from registry. Both functions assigned to `window.*` at lines 175 and 320. |
| 16 | Migration chain: 007 revises 006, 008 revises 007; both have `downgrade()` | PASS | Migration 007: `down_revision = "006"`. Migration 008: `down_revision = "007"`. Both implement `downgrade()`. 007 downgrade drops index then column. 008 downgrade drops index then column. |
| 17 | base.py abstract method: all 20 collectors implement updated `collect_by_terms()` signature | WARN | The scope statement says "all 20 arena collectors updated with `term_groups` + `language_filter` params". This review verified `query_builder.py` is correct and the calling convention is documented. However, individual collector files were not inspected in this review pass. A targeted grep-based audit is recommended before merge. |
| 18 | Clone endpoint returns 303 redirect to `/query-designs/{clone.id}` (not `/edit`) | PASS | `clone_query_design()` returns `RedirectResponse(url=f"/query-designs/{clone.id}", status_code=status.HTTP_303_SEE_OTHER)`. URL does not contain `/edit`. |
| 19 | Sigma.js CDN: graphology@0.25.4 compatible with sigma@3.0.0-beta.35 | PASS | Template loads `graphology@0.25.4` and `sigma@3.0.0-beta.35`. Sigma v3 requires graphology v0.25+; 0.25.4 satisfies this constraint. CDN URLs are consistent. |
| 20 | Test gap identification (see below) | WARN | Six HIGH, four MEDIUM test gaps identified. |

---

### Critical Issues (Blocking)

None. No blocking issues found.

---

### High Issues (Must resolve before merge)

**H-01** — `compute_simhash()` and `hamming_distance()` have zero test coverage.

These are pure functions with deterministic output and are the algorithmic core of the near-duplicate detection feature. The test file `tests/unit/test_deduplication.py` imports only `DeduplicationService`, `get_deduplication_service`, and `normalise_url` — it does not import or test `compute_simhash` or `hamming_distance`.

Tests required in `tests/unit/test_deduplication.py`:

```python
def test_compute_simhash_returns_integer():
    result = compute_simhash("hello world")
    assert isinstance(result, int)

def test_compute_simhash_returns_64_bit_value():
    result = compute_simhash("klimaforandringer i Danmark")
    assert 0 <= result < (1 << 64)

def test_compute_simhash_returns_zero_for_empty_string():
    assert compute_simhash("") == 0

def test_compute_simhash_returns_zero_for_whitespace_only():
    assert compute_simhash("   ") == 0

def test_compute_simhash_identical_texts_produce_identical_fingerprint():
    text = "Grøn omstilling er vigtig for velfærdsstaten"
    assert compute_simhash(text) == compute_simhash(text)

def test_compute_simhash_similar_texts_have_low_hamming_distance():
    a = compute_simhash("klimaforandringer og vejret i Danmark")
    b = compute_simhash("klimaforandringer og vejret i Danmark idag")
    assert hamming_distance(a, b) <= 10

def test_compute_simhash_very_different_texts_have_high_hamming_distance():
    a = compute_simhash("klimaforandringer")
    b = compute_simhash("den store mur i Kina")
    assert hamming_distance(a, b) > 10

def test_compute_simhash_preserves_danish_characters():
    result_da = compute_simhash("Grøn omstilling: æøå er vigtige bogstaver")
    assert isinstance(result_da, int)

def test_hamming_distance_identical_values_is_zero():
    h = compute_simhash("test")
    assert hamming_distance(h, h) == 0

def test_hamming_distance_uses_xor():
    assert hamming_distance(0b1010, 0b0101) == 4

def test_hamming_distance_single_bit_difference():
    assert hamming_distance(0b1000, 0b0000) == 1

def test_find_near_duplicates_returns_empty_for_no_records():
    ...  # mock DB returning empty rows

def test_detect_and_mark_near_duplicates_returns_zero_for_no_clusters():
    ...  # mock find_near_duplicates returning []
```

**H-02** — `export_ris()` and `export_bibtex()` have zero test coverage.

`tests/unit/test_export.py` covers CSV, XLSX, NDJSON, Parquet, and GEXF but contains no test class for `TestExportRis` or `TestExportBibTeX`.

Tests required in `tests/unit/test_export.py`:

```python
class TestExportRis:
    def test_ris_export_returns_bytes():
    def test_ris_export_starts_with_TY_tag():
    def test_ris_each_record_ends_with_ER():
    def test_ris_title_tag_present_when_title_available():
    def test_ris_uses_text_content_truncated_when_no_title():
    def test_ris_author_tag_present_when_author_available():
    def test_ris_url_tag_present_when_url_available():
    def test_ris_py_tag_contains_year_from_published_at():
    def test_ris_dp_tag_contains_platform_and_arena():
    def test_ris_n1_tag_contains_search_terms():
    def test_ris_omits_empty_tags():
    def test_ris_preserves_danish_characters_in_title():
    def test_ris_empty_records_returns_empty_bytes():
    def test_ris_multiple_records_have_multiple_ER_terminators():

class TestExportBibTeX:
    def test_bibtex_export_returns_bytes():
    def test_bibtex_entry_key_derived_from_content_hash():
    def test_bibtex_entry_key_uses_url_sha256_fallback_when_no_hash():
    def test_bibtex_entry_type_is_misc():
    def test_bibtex_title_field_present():
    def test_bibtex_curly_braces_escaped_in_title():
    def test_bibtex_backslash_escaped_before_braces():
    def test_bibtex_howpublished_contains_url_command():
    def test_bibtex_year_extracted_from_published_at():
    def test_bibtex_note_contains_search_terms():
    def test_bibtex_annote_contains_platform_arena():
    def test_bibtex_preserves_danish_characters():
    def test_bibtex_empty_records_returns_empty_bytes():
    def test_bibtex_unique_keys_across_records():
```

**H-03** — `clone_query_design()` endpoint has zero integration test coverage.

The clone endpoint is the only new write endpoint in Phase D. Its deep-copy logic (search terms, actor lists, members) requires integration tests to verify correctness.

Tests required in a new file `tests/integration/test_clone_query_design.py` or as additions to `tests/integration/test_auth_flow.py`:

```python
async def test_clone_creates_new_query_design_with_copy_suffix():
async def test_clone_copies_search_terms_with_group_id_and_group_label():
async def test_clone_copies_actor_list_members():
async def test_clone_sets_parent_design_id_to_original_id():
async def test_clone_generates_new_uuids_for_all_cloned_rows():
async def test_clone_returns_303_redirect_to_clone_id():
async def test_clone_redirect_url_does_not_contain_edit():
async def test_clone_returns_404_for_nonexistent_design():
async def test_clone_returns_403_for_design_owned_by_another_user():
```

**H-04** — `GET /analysis/{run_id}/filtered-export` has zero integration test coverage.

This endpoint adds six new format dispatch paths (csv, xlsx, ndjson, parquet, ris, bibtex) with filter logic. The ownership check and the unknown-format 400 path need explicit tests.

Tests required in `tests/unit/test_analysis_route_filter_options.py` or a new `tests/unit/test_filtered_export_route.py`:

```python
async def test_filtered_export_csv_returns_bytes_with_content_disposition():
async def test_filtered_export_unknown_format_returns_400():
async def test_filtered_export_returns_403_for_unauthorized_run():
async def test_filtered_export_returns_404_for_nonexistent_run():
async def test_filtered_export_platform_filter_reduces_record_count():
async def test_filtered_export_date_from_filter_applied():
async def test_filtered_export_ris_format_returns_application_x_ris_content_type():
async def test_filtered_export_bibtex_format_returns_application_x_bibtex_content_type():
```

**H-05** — `GET /analysis/{run_id}/suggested-terms` has zero integration test coverage.

```python
async def test_suggested_terms_returns_list_of_dicts_with_term_score_document_frequency():
async def test_suggested_terms_excludes_existing_search_terms():
async def test_suggested_terms_returns_empty_list_when_sklearn_unavailable():
async def test_suggested_terms_returns_404_for_nonexistent_run():
async def test_suggested_terms_returns_403_for_unauthorized_run():
async def test_suggested_terms_top_n_limits_result_count():
```

**H-06** — `build_boolean_query_groups()` and `format_boolean_query_for_platform()` have zero test coverage.

`query_builder.py` is a new module with non-trivial logic. No test file for it exists.

Tests required in a new file `tests/unit/test_query_builder.py`:

```python
def test_build_boolean_query_groups_empty_input_returns_empty_list():
def test_build_boolean_query_groups_ungrouped_terms_each_form_own_group():
def test_build_boolean_query_groups_same_group_id_terms_are_anded():
def test_build_boolean_query_groups_different_group_ids_are_separate_groups():
def test_build_boolean_query_groups_mixed_grouped_and_ungrouped():
def test_build_boolean_query_groups_empty_term_strings_are_skipped():
def test_build_boolean_query_groups_uuid_and_string_group_ids_match():
def test_format_boolean_query_for_platform_empty_groups_returns_empty_string():
def test_format_boolean_query_for_platform_single_term_no_operators():
def test_format_generic_multi_group_uses_AND_OR():
def test_format_google_multi_term_group_uses_parentheses_and_OR():
def test_format_twitter_multi_term_group_uses_parentheses_and_OR():
def test_format_reddit_multi_term_group_uses_plus_join():
def test_format_youtube_groups_joined_with_pipe():
def test_format_bluesky_returns_only_first_group():
def test_format_gdelt_uses_explicit_AND_OR():
def test_has_boolean_groups_returns_true_when_any_group_id_set():
def test_has_boolean_groups_returns_false_when_all_none():
# Danish characters preserved in formatted query string:
def test_format_query_preserves_danish_characters():
```

---

### Medium Issues

**M-01** — `parse_language_codes()` has zero test coverage.

This function is the critical dispatch mechanism for multilingual collection. The fallback to `["da"]` on empty input and the deduplication logic should be tested.

Add to `tests/unit/` a new file `tests/unit/test_query_design_schema.py`:

```python
def test_parse_language_codes_single_code():
    assert parse_language_codes("da") == ["da"]

def test_parse_language_codes_comma_separated():
    assert parse_language_codes("da,en") == ["da", "en"]

def test_parse_language_codes_strips_whitespace():
    assert parse_language_codes("da, en") == ["da", "en"]

def test_parse_language_codes_lowercases():
    assert parse_language_codes("DA,EN") == ["da", "en"]

def test_parse_language_codes_deduplicates():
    assert parse_language_codes("da, EN, da") == ["da", "en"]

def test_parse_language_codes_preserves_insertion_order():
    result = parse_language_codes("en,da,sv")
    assert result == ["en", "da", "sv"]

def test_parse_language_codes_empty_string_returns_da_fallback():
    assert parse_language_codes("") == ["da"]
```

**M-02** — `get_top_actors()` LEFT JOIN change (IP2-061) has zero test coverage in unit tests.

The SQL change adds `LEFT JOIN actors a ON a.id = c.author_id` and a new `resolved_name` field. Tests in `test_descriptive.py` should mock a DB row with a non-null `resolved_name` and one with null. Add to `tests/unit/test_descriptive.py`:

```python
async def test_get_top_actors_returns_resolved_name_when_author_resolved():
    # Mock row with non-null resolved_name (actor in actors table)
    ...
async def test_get_top_actors_returns_none_resolved_name_when_no_actor_row():
    # Mock row with resolved_name = None (author_id not in actors table)
    ...
async def test_get_top_actors_actor_id_field_present_in_returned_dicts():
    ...
```

**M-03** — Migration 007 `downgrade()` drops index before column — verify order is safe.

In migration 007's `downgrade()`, the index is dropped first (`DROP INDEX IF EXISTS idx_content_records_simhash`) and then the column (`ALTER TABLE content_records DROP COLUMN IF EXISTS simhash`). This ordering is correct for PostgreSQL (an index on a column being dropped would prevent the column drop if the index were not dropped first). No code change needed; this is a documentation note for the migration review checklist.

**M-04** — `network_preview.js` `_instances` singleton is module-scope, not `window`-scoped.

The `_instances = new Map()` is at module-level (file scope), which is correct for a single-page application where the script is loaded once. However, if the script is ever imported as a module (ES module syntax), the singleton would be scoped to the module, not the window. The current UMD-style `'use strict'` script loaded via `<script src=...>` shares the global scope correctly. Low risk; no change required at this time, but noted for future ESM migration.

---

### Test Files Written (Phase D Gap Closure — 2026-02-18)

All Phase D test gaps have been resolved. See "Test Files Written (2026-02-18, Phase D)" section above for full details.

| Priority | File | Test Cases | Status |
|----------|------|-----------|--------|
| HIGH | `tests/unit/test_deduplication.py` (additions) | `TestComputeSimhash` (8), `TestHammingDistance` (4) | DONE |
| HIGH | `tests/unit/test_export.py` (additions) | `TestExportRis` (8), `TestExportBibTeX` (6) | DONE |
| HIGH | `tests/unit/test_query_builder.py` (new file) | `TestBuildBooleanQueryGroups` (8), `TestFormatBooleanQueryForPlatform` (10), `TestHasBooleanGroups` (3) | DONE |
| HIGH | `tests/integration/test_clone_query_design.py` (new file) | `TestCloneQueryDesign` (9 integration tests) | DONE |
| HIGH | `tests/unit/test_analysis_phase_d_routes.py` (new file) | `TestFilteredExport` (7), `TestSuggestedTerms` (5) | DONE |
| MEDIUM | `tests/unit/test_query_design_schema.py` (new file) | `TestParseLanguageCodes` (10) | DONE |
| MEDIUM | `tests/unit/test_descriptive.py` (additions) | 3 tests appended to `TestGetTopActors` | DONE |

---

### Carry-forward from Phase C (still open)

The following Phase C test gaps from the prior QA review remain open. They are not blocking Phase D but must be resolved before the next major release:

- `tests/unit/test_descriptive.py`: `get_emergent_terms` 5 tests, `get_top_actors_unified` 3 tests
- `tests/unit/test_network.py`: `get_temporal_network_snapshots` 5 tests, `build_enhanced_bipartite_network` 3 tests
- `tests/unit/test_export.py`: `_build_dynamic_gexf` 4 tests, `export_temporal_gexf` 1 test
- `tests/unit/test_enrichments.py` (new file): 9 tests
- `tests/unit/test_tasks.py`: `enrich_collection_run` 4 tests

---

## Notes for Phase 1 Arena Implementations

When each Phase 1 arena is submitted for review, the QA gate requires:

1. Unit tests for `normalize()` with recorded API response fixtures in `tests/fixtures/api_responses/<platform>/`.
2. Integration test for `collect_by_terms()` with mocked HTTP (use `respx` library, added to `dev` dependencies).
3. At least one Danish character test: verify æ, ø, å survive the full normalize path.
4. Edge cases: empty results, HTTP 429, malformed JSON response, missing required fields.
5. Health check test.
6. Coverage must not drop below 75% overall.

The `mock_http_client` fixture in `conftest.py` provides the interface contract.
Arena test files should override it per-platform with `respx` mocks loading from
`tests/fixtures/api_responses/<platform>/`.

---

## Greenland Roadmap (GR) — Post-Implementation Review (2026-02-19)

_Full report: `/docs/ux_reports/gr_implementation_qa.md`_

**Result: CONDITIONAL PASS** — No blockers. 4 warnings. Test files for all GR modules are missing (primary debt).

### GR Arena Review Status

| Arena | Status | Notes |
|-------|--------|-------|
| url_scraper (GR-10) | REVIEW COMPLETE — no tests yet | QA checklist in `core.md` line 1517-1531; import verification test needed |
| wayback _content_fetcher (GR-12) | REVIEW COMPLETE — no tests yet | W-01: runtime import test required before deployment |

### GR Coverage Gaps (all require test files)

| Component | Required | Status |
|-----------|----------|--------|
| `analysis/enrichments/propagation_detector.py` | 85% | NO TESTS — enrich_cluster(), single-arena skip, missing timestamps |
| `analysis/enrichments/coordination_detector.py` | 85% | NO TESTS — sliding-window, threshold, score normalisation |
| `analysis/enrichments/language_detector.py` | 85% | Tests noted in prior review as needed; still missing |
| `analysis/alerting.py` + `_alerting_store.py` | 85% | NO TESTS — detect_volume_spikes, store, fetch, email |
| `analysis/link_miner.py` | 80% | NO TESTS — URL regex, platform classification, aggregation |
| `sampling/network_expander.py` (GR-19, GR-21 additions) | 75% | PARTIAL — existing `test_sampling.py` covers Bluesky/Reddit/YouTube; _expand_via_comention and _expand_via_telegram_forwarding not covered |
| `sampling/snowball.py` (GR-20 additions) | 75% | PARTIAL — existing tests cover core run(); auto_create_actor_records() not covered |
| `arenas/web/url_scraper/collector.py` | 80% | NO TESTS |
| `arenas/web/wayback/_content_fetcher.py` | 75% | NO TESTS — rate limiting, error isolation, extractor selection |
| `api/routes/query_designs.py` (PATCH endpoint GR-01-05, alerts GR-09) | 75% | NO TESTS for new endpoints |
| `api/routes/actors.py` (quick-add GR-17, similarity GR-18, snowball GR-20) | 75% | NO TESTS for GR-17/GR-18/GR-20 endpoints |
| `api/routes/content.py` (discovered-links GR-22) | 75% | NO TESTS for GET /content/discovered-links |

### Warnings (active)

- **W-01** `arenas/web/wayback/_content_fetcher.py`: runtime circular-import verification needed. See Section 1.5 of GR QA report.
- **W-02** `docs/status/core.md`: GR-21 section missing. Add GR-21 entry referencing `_expand_via_telegram_forwarding()`.
- **W-03** GR-18 frontend QA checklist: 7 items unchecked in `core.md` lines 1475-1482. Frontend Engineer must verify HTMX/Alpine bindings interactively.
- **W-04** GR-10 `normalize()` tier parameter: public `normalize(record)` delegates to `_normalize_raw_record(record, Tier.FREE)` — external callers using the base class interface get FREE tier regardless of actual tier. Tracked as technical debt.

### Open Issues

```markdown
## Blocked
(none)

## Warnings
- W-01: wayback/_content_fetcher.py — circular import risk with scraper module unverified at runtime.
  Fix: run test_wayback_content_fetcher_imports.py before next deployment.
- W-02: core.md GR-21 section missing — Core Application Engineer to add.
- W-03: GR-18 frontend QA checklist (7 items) — Frontend Engineer to verify interactively.
- W-04: url_scraper normalize() hardcodes Tier.FREE for public interface callers.
```
