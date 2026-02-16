# QA Guardian — Status

_Last updated: 2026-02-16 (Phase 2 arena tests written — x_twitter, event_registry, threads, sampling)_

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
| `sampling/network_expander.py` | 75% | Tests written — see `tests/unit/test_sampling.py` |
| `sampling/similarity_finder.py` | 75% | Tests written — see `tests/unit/test_sampling.py` |
| `sampling/snowball.py` | 75% | Tests written — see `tests/unit/test_sampling.py` |
| **Overall minimum** | **75%** | Not yet measured |

---

## Arena Review Status

| Arena | Review Status | Blocking Issues |
|-------|--------------|-----------------|
| google_search | PARTIAL | Integration tests with mocked HTTP not yet written; normalize() unit tests complete |
| google_autocomplete | TESTS WRITTEN | All checklist items covered; pending CI run |
| bluesky | TESTS WRITTEN | All checklist items covered; pending CI run |
| reddit | TESTS WRITTEN | All checklist items covered; pending CI run |
| youtube | TESTS WRITTEN | All checklist items covered; pending CI run |
| rss_feeds | TESTS WRITTEN | All checklist items covered; pending CI run |
| gdelt | TESTS WRITTEN | All checklist items covered; pending CI run |
| x_twitter | TESTS WRITTEN | normalize() both paths, tweet type detection, MEDIUM/PREMIUM tiers, 429, health_check; pending CI run |
| event_registry | TESTS WRITTEN | normalize(), ISO 639-3 mapping, token budget thresholds, 402, collect_by_actors(); pending CI run |
| threads | TESTS WRITTEN | pagination, collect_by_terms() empty accounts, engagement presence/absence, reply type, MEDIUM stub; pending CI run |

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
| bluesky | `respx` on `public.api.bsky.app` | None |
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

## Open Issues

### Priority: Medium

- `tests/unit/test_credit_service.py` — Tests use mock session. Integration tests against real DB (testing the SQL formulae) are needed and should live in `tests/integration/test_credit_service_integration.py`. This is not blocking Phase 0 completion.

- `tests/integration/test_auth_flow.py` — Some route stubs (query-designs POST) use `pytest.skip()` when the endpoint returns 404. These tests will activate automatically as routes are implemented.

- `tests/conftest.py` — The `CREDENTIAL_ENCRYPTION_KEY` default `dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==` is a placeholder that is NOT a valid Fernet key (Fernet requires exactly 32 URL-safe base64-encoded bytes). The CI workflow correctly references `${{ secrets.CREDENTIAL_ENCRYPTION_KEY }}`. For local development, generate a real key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and set it in your `.env` file.

- `tests/arenas/test_reddit.py` — Reddit's `collect_by_terms()` is tested with a mocked asyncpraw client. The TooManyRequests exception test requires asyncprawcore to be installed; this is a direct dependency of asyncpraw and will be present in any environment where asyncpraw is installed.

### Priority: Low

- `tests/fixtures/sample_data/` — Known-good normalized records for schema validation tests not yet written.

- `tests/unit/test_logging.py` — Pre-existing test; should be reviewed to confirm it still passes after conftest env bootstrap.

---

## Blocked

_No arenas are currently blocked by QA._

All six Phase 1 arenas (google_autocomplete, bluesky, reddit, youtube, rss_feeds, gdelt) have complete test suites. Blocking authority will be exercised if CI reveals coverage below 75% or if any normalize() tests reveal data integrity issues when run against a live environment.

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
