# Issue Observatory -- Release Notes 2026-02-21

**Date:** 2026-02-21
**Scope:** Enhanced Snowball Sampling -- new platform graph expansion, URL-based co-mention detection, configurable thresholds, corpus-level co-occurrence endpoint, and discovery method transparency.

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-21 | Enhanced Snowball Sampling: 6-phase implementation covering discovery transparency, 3 new platform expanders, URL co-mention detection, configurable thresholds, corpus co-occurrence endpoint, and 74 new tests. |

---

## Executive Summary

The snowball sampling subsystem received a major enhancement across six implementation phases. Previously, network expansion supported 4 platforms (Bluesky, Reddit, YouTube, Telegram) with @mention-only co-mention fallback. This release:

- **Adds graph expansion for 3 new platforms** (TikTok, Gab, X/Twitter), bringing the total to 7 platforms with native follower/following traversal
- **Surfaces `discovery_method` in the API and UI**, giving researchers visibility into how each actor was discovered
- **Introduces URL-based co-mention detection** for news media arenas (RSS, GDELT, Event Registry, Common Crawl) where @mentions are rare but URLs to social profiles are common
- **Makes co-mention thresholds configurable** via the snowball sampling UI
- **Exposes corpus-level co-occurrence analysis** as a standalone endpoint with its own UI panel
- **Adds 74 new tests** (43 network expander, 31 schema) with network_expander.py coverage improving from 57% to 66%

---

## What's New: Enhanced Snowball Sampling

### Phase 1: Discovery Method Transparency

Researchers can now see how each actor was discovered during snowball sampling.

| Change | Details |
|--------|---------|
| `discovery_method` on `SnowballActorEntry` | New `discovery_method: str = ""` field on the Pydantic response schema. Populated from `actor_dict.get("discovery_method", "")` in the response building loop. |
| "Method" column in discovered actors table | New column in the snowball results table on the Actor Directory page. |
| `formatMethod()` Alpine helper | Maps internal snake_case method strings to human-readable labels (e.g., `comention_fallback` -> "Co-mention", `bluesky_followers` -> "Bluesky Followers", `url_comention` -> "URL Co-mention"). |
| Response key mapping | Frontend `runSnowball()` now correctly maps API response keys (`total_actors` -> `total_found`, `actors` -> `discovered_actors`) with field normalization. |

### Phase 2: New Platform Graph Expansion (TikTok, Gab, X/Twitter)

Three new platform-specific expanders bring the total from 4 to 7 platforms with native follower/following graph traversal.

| Platform | API | Auth | Pagination | Discovery Methods |
|----------|-----|------|------------|-------------------|
| **TikTok** | Research API v2 (`/research/user/followers/`, `/following/`) | OAuth 2.0 client credentials | POST with `cursor` + `has_more`, max 100/page | `tiktok_followers`, `tiktok_following` |
| **Gab** | Mastodon-compatible (`/api/v1/accounts/{id}/followers`, `/following`) | Bearer token (optional) | `max_id` cursor, 40/page | `gab_followers`, `gab_following` |
| **X/Twitter** | TwitterAPI.io (`/twitter/user/followers`, `/followings`) | API key in `X-API-Key` header | `next_cursor`, 200/page | `x_twitter_followers`, `x_twitter_following` |

**Implementation details:**

- `_expand_tiktok()`: Requires `client_key` + `client_secret` credentials. Obtains Bearer token via `_get_tiktok_token()` OAuth helper. Caps at 500 actors per direction. Falls back to `username` when `display_name` is absent.
- `_expand_gab()`: First resolves username to account ID via `GET /api/v1/accounts/lookup?acct=...`. Uses new `_get_json_list()` helper (Mastodon returns arrays, not dicts). Falls back to `username` when `acct` is absent.
- `_expand_x_twitter()`: Uses `twitterapi_io` credential pool entry at MEDIUM tier. Falls back to `screen_name`/`userId` when `userName`/`id` fields are absent.
- New `_post_json()` helper mirrors existing `_get_json()` for TikTok's POST-based API.
- New `_get_json_list()` helper handles Mastodon-compatible endpoints that return JSON arrays.

**Credential tier mapping:**

| Platform | Credential Pool Key | Tier |
|----------|-------------------|------|
| TikTok | `tiktok` | `free` |
| Gab | `gab` | `free` |
| X/Twitter | `twitterapi_io` | `medium` |

### Phase 3: URL-Based Co-Mention for News Media

News media arenas (RSS, GDELT, Event Registry, Common Crawl, Wayback) rarely use @mentions but frequently link to social media profiles. The co-mention fallback now detects these URL references.

| Change | Details |
|--------|---------|
| `_URL_PLATFORM_MAP` constant | Maps link_miner URL classification slugs to actor platform names: `twitter` -> `x_twitter`, `bluesky` -> `bluesky`, `youtube` -> `youtube`, `tiktok` -> `tiktok`, `gab` -> `gab`, `instagram` -> `instagram`, `telegram` -> `telegram`, `reddit` -> `reddit`, `reddit_user` -> `reddit`. |
| URL extraction in `_expand_via_comention()` | After the existing @mention regex pass, a second pass calls `link_miner._extract_urls()` on each record's text, then `_classify_url()` on each URL. Classified URLs mapping to known platforms are counted as co-mentions. |
| Cross-platform discovery | URL-discovered actors get `discovery_method="url_comention"` and their platform is derived from the URL (not the query platform). A news article on an RSS feed linking to `https://x.com/someuser` correctly creates an X/Twitter actor. |
| Reddit user profile rule | New regex rule in `link_miner.py` matching `reddit.com/u/` and `reddit.com/user/` URLs (slug `reddit_user`), added before the existing subreddit rule. |

### Phase 4: Configurable Co-Mention Thresholds

The minimum number of shared records required for co-mention detection is now researcher-configurable (previously hardcoded at 2).

| Change | Details |
|--------|---------|
| `min_comention_records` on `SnowballRequest` | New field with default `2`. Flows through `SnowballSampler.run()` -> `NetworkExpander.expand_from_actor()` -> `_expand_via_comention(min_records=...)`. |
| UI input control | New "Min. records for co-mention detection" number input in the snowball panel right column with explanatory tooltip. |

### Phase 5: Corpus-Level Co-Occurrence Endpoint

The standalone `find_co_mentioned_actors()` method -- which finds actor pairs appearing together across an entire query design's content -- now has an API endpoint and UI.

| Component | Details |
|-----------|---------|
| **Schemas** | `CorpusCoOccurrenceRequest(query_design_id: UUID, min_co_occurrences: int = 3)`, `CoOccurrencePair(actor_a, actor_b, platform, co_occurrence_count)`, `CorpusCoOccurrenceResponse(pairs, total_pairs)` |
| **Endpoint** | `POST /actors/sampling/co-occurrence` -- calls `NetworkExpander().find_co_mentioned_actors()` |
| **UI** | Collapsible "Corpus Co-occurrence" panel below the snowball panel on the Actor Directory page. Query design selector, min co-occurrences input, results table (Actor A, Actor B, Platform, Count). Alpine.js `corpusCoOccurrence()` component. |

### Phase 6: Tests

74 new tests across 2 test files, all passing.

**`tests/unit/sampling/test_network_expander_new.py`** (43 tests):

| Test Class | Count | Coverage |
|------------|-------|----------|
| `TestPostJson` | 3 | `_post_json()` success, HTTP error, connection error |
| `TestExpandTiktok` | 7 | OAuth flow, pagination, empty credentials, missing keys, display name fallback |
| `TestExpandGab` | 7 | Account lookup, Mastodon pagination, bearer token, acct fallback |
| `TestExpandXTwitter` | 7 | Cursor pagination, API key header, screen_name fallback |
| `TestExpandViaComentionUrlDiscovery` | 6 | URL extraction, platform mapping, seed exclusion, min_records threshold |
| `TestExpandFromActorDispatch` | 9 | Routing for 3 new platforms, credential tier selection, fallback, error handling |
| `TestMakeActorDict` | 3 | Field completeness, Danish characters, empty strings |
| `TestComentionConstants` | 1 | Default threshold value |

**`tests/unit/routes/test_actors_snowball_schema.py`** (31 tests):

| Test Class | Count | Coverage |
|------------|-------|----------|
| `TestSnowballActorEntry` | 6 | `discovery_method` field, defaults, serialization, Danish characters |
| `TestSnowballRequest` | 7 | `min_comention_records` field, defaults, serialization |
| `TestCorpusCoOccurrenceRequest` | 7 | UUID validation, defaults, rejection of invalid input |
| `TestCoOccurrencePair` | 4 | Field completeness, round-trip, required field validation |
| `TestCorpusCoOccurrenceResponse` | 7 | Empty response, structure, JSON serialization round-trip |

**Coverage impact:** `network_expander.py` coverage improved from 57% to 66% (+9 points).

---

## Files Modified

| File | Changes |
|------|---------|
| `src/issue_observatory/sampling/network_expander.py` | Added 3 platform expanders (`_expand_tiktok`, `_expand_gab`, `_expand_x_twitter`), `_post_json()` and `_get_json_list()` helpers, `_get_tiktok_token()` OAuth helper, `_URL_PLATFORM_MAP`, URL co-mention logic in `_expand_via_comention()`, `min_comention_records` parameter threading, dispatch cases for 3 new platforms |
| `src/issue_observatory/api/routes/actors.py` | Added `discovery_method` to `SnowballActorEntry`, `min_comention_records` to `SnowballRequest`, 3 new corpus co-occurrence schemas, `POST /actors/sampling/co-occurrence` endpoint, updated `_NETWORK_EXPANSION_PLATFORMS` to 7 platforms |
| `src/issue_observatory/sampling/snowball.py` | Added `min_comention_records` parameter to `run()`, passed through to `expand_from_actor()` |
| `src/issue_observatory/analysis/link_miner.py` | Added Reddit user profile URL rule (`reddit.com/u/` and `reddit.com/user/`) |
| `src/issue_observatory/api/templates/actors/list.html` | Added "Method" column, `formatMethod()` helper, response key mapping in `runSnowball()`, updated platform list to 7, min co-mention records input, corpus co-occurrence panel with Alpine `corpusCoOccurrence()` component |

## Files Created

| File | Purpose |
|------|---------|
| `tests/unit/sampling/test_network_expander_new.py` | 43 tests for new network expander methods |
| `tests/unit/routes/test_actors_snowball_schema.py` | 31 tests for snowball and co-occurrence schemas |
| `tests/unit/routes/__init__.py` | Package marker for routes test subdirectory |

---

## API Changes

### New Endpoint

| Method | Path | Description |
|--------|------|-------------|
| POST | `/actors/sampling/co-occurrence` | Corpus-level actor co-occurrence analysis across a query design's collected content |

### Modified Schemas

| Schema | Change |
|--------|--------|
| `SnowballActorEntry` | Added `discovery_method: str = ""` |
| `SnowballRequest` | Added `min_comention_records: int = 2` |

### Modified Endpoint Behavior

| Method | Path | Change |
|--------|------|--------|
| GET | `/actors/sampling/snowball/platforms` | Now returns 7 platforms (added `tiktok`, `gab`, `x_twitter`) |
| POST | `/actors/sampling/snowball` | Response now includes `discovery_method` per actor; accepts `min_comention_records` parameter |

### No Breaking Changes

All changes are additive. Existing snowball sampling behavior is unchanged -- `discovery_method` defaults to empty string, `min_comention_records` defaults to 2 (the previous hardcoded value), and the 3 new platform expanders only activate when matching credentials are configured.

### No New Dependencies

All new functionality uses existing dependencies (`httpx`, `structlog`, `pydantic`). No new packages or database migrations required.

---

## Updated Capability Summary

### Snowball Sampling: Before vs After

| Capability | Before | After |
|------------|--------|-------|
| Platforms with graph expansion | 4 (Bluesky, Reddit, YouTube, Telegram) | 7 (+TikTok, Gab, X/Twitter) |
| Discovery method visibility | Hidden (tracked internally only) | Exposed in API response + UI table column |
| Co-mention detection | @mention regex only | @mention regex + URL-based detection via link_miner |
| Co-mention threshold | Hardcoded at 2 | Configurable via `min_comention_records` (default 2) |
| Corpus-level co-occurrence | Method existed, no API/UI | Full endpoint + UI panel |
| Network expander test coverage | 57% | 66% (+9 points) |

---

*This document covers changes made on 2026-02-21. For the comprehensive implementation status across all reports and the IP2 roadmap, see `release_notes_2026_02_20.md`.*
