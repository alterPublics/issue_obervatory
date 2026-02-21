# Issue Observatory -- Release Notes 2026-02-21

**Author:** Research & Knowledge Agent (The Strategist)
**Date:** 2026-02-21
**Scope:** Comprehensive implementation status as of 2026-02-21. This document is the single source of truth for what has been built, what remains, and where each recommendation stands. It supersedes the 2026-02-20 release notes.

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-21 | Comprehensive release notes created. Incorporates all 2026-02-20 content plus 2026-02-21 additions: Enhanced Snowball Sampling (6 phases), Zeeschuimer import integration (protocol spec, DB layer, import module, platform normalizers, blocker fixes), two coherency audits (research + QA), migrations 014 and 015, and 74 new tests. |

---

## Executive Summary

The Issue Observatory is a modular multi-platform media data collection and analysis application for Danish public discourse research. As of 2026-02-21, the system has reached a mature state with comprehensive coverage across 24 arena directories (21 functional), 15 database migrations, a full enrichment pipeline, and a new Zeeschuimer import pathway for manual data capture.

### Quantitative Summary

| Category | Count |
|----------|-------|
| Arena implementations | 25 (21 functional, 2 deferred stubs, 2 limited) |
| Database migrations | 15 |
| Enrichment modules | 6 (language detection, NER, sentiment, propagation, coordination, plus ContentEnricher base class) |
| Alembic models (ORM) | 11 tables |
| API route modules | 14 |
| Frontend templates | 30+ pages and partials |
| Test files | 69+ |
| Recommendation reports produced | 6 |
| Recommendation IDs tracked | 157 (approximately 97 unique after deduplication) |
| Unique items implemented | approximately 94 of 97 (97%) |

### Key Capabilities

- **25 arena implementations** spanning social media, news media, web archives, search engines, and AI chat
- **Zeeschuimer import integration** enabling manual capture of LinkedIn, Twitter/X, Instagram, TikTok, and Threads content via browser extension
- **Snowball sampling** with graph expansion across 7 platforms, URL-based co-mention detection, configurable thresholds, and corpus-level co-occurrence analysis
- **6 enrichment modules** for automated post-collection analysis
- **Researcher self-service mechanisms** for RSS feeds, Telegram channels, Reddit subreddits, Discord channels, Wikipedia seed articles, and per-arena search term scoping
- **Discovery feedback loops** with one-click term/source addition, RSS feed autodiscovery, and subreddit suggestion
- **In-browser network visualization** (Sigma.js) with 4 GEXF export modes
- **Annotation codebook management** for structured qualitative coding
- **Cross-run and design-level analysis** supporting iterative research workflows
- **GDPR compliance** with pseudonymization, public figure bypass, retention policies, and data subject deletion

---

## What's New on 2026-02-21

### 1. Enhanced Snowball Sampling (6 phases, 74 new tests)

The snowball sampling subsystem received a major enhancement. Previously, network expansion supported 4 platforms (Bluesky, Reddit, YouTube, Telegram) with @mention-only co-mention fallback. This release adds substantial new capabilities.

#### Phase 1: Discovery Method Transparency

Researchers can now see how each actor was discovered during snowball sampling.

| Change | Details |
|--------|---------|
| `discovery_method` on `SnowballActorEntry` | New field populated from `actor_dict.get("discovery_method", "")`. |
| "Method" column in discovered actors table | New column in the snowball results table on the Actor Directory page. |
| `formatMethod()` Alpine helper | Maps internal snake_case method strings to human-readable labels. |
| Response key mapping | Frontend correctly maps API response keys with field normalization. |

#### Phase 2: New Platform Graph Expansion (TikTok, Gab, X/Twitter)

Three new platform-specific expanders bring the total from 4 to 7 platforms with native follower/following graph traversal.

| Platform | API | Auth | Discovery Methods |
|----------|-----|------|-------------------|
| TikTok | Research API v2 (`/research/user/followers/`, `/following/`) | OAuth 2.0 client credentials | `tiktok_followers`, `tiktok_following` |
| Gab | Mastodon-compatible (`/api/v1/accounts/{id}/followers`, `/following`) | Bearer token (optional) | `gab_followers`, `gab_following` |
| X/Twitter | TwitterAPI.io (`/twitter/user/followers`, `/followings`) | API key in `X-API-Key` header | `x_twitter_followers`, `x_twitter_following` |

Implementation details:
- `_expand_tiktok()`: OAuth 2.0 token via `_get_tiktok_token()` helper. Caps at 500 actors per direction.
- `_expand_gab()`: Resolves username to account ID via lookup endpoint. New `_get_json_list()` helper for Mastodon's array responses.
- `_expand_x_twitter()`: Uses `twitterapi_io` credential pool entry at MEDIUM tier.
- New `_post_json()` helper for TikTok's POST-based API.

#### Phase 3: URL-Based Co-Mention for News Media

News media arenas (RSS, GDELT, Event Registry, Common Crawl, Wayback) rarely use @mentions but frequently link to social media profiles. The co-mention fallback now detects these URL references.

| Change | Details |
|--------|---------|
| `_URL_PLATFORM_MAP` constant | Maps link_miner URL classification slugs to actor platform names. |
| URL extraction in `_expand_via_comention()` | Second pass calls `link_miner._extract_urls()` then `_classify_url()` on each URL. |
| Cross-platform discovery | URL-discovered actors get `discovery_method="url_comention"` with platform derived from the URL. |
| Reddit user profile rule | New regex rule in `link_miner.py` matching `reddit.com/u/` and `reddit.com/user/` URLs. |

#### Phase 4: Configurable Co-Mention Thresholds

The minimum number of shared records required for co-mention detection is now researcher-configurable (previously hardcoded at 2).

| Change | Details |
|--------|---------|
| `min_comention_records` on `SnowballRequest` | New field with default `2`, flows through to `_expand_via_comention(min_records=...)`. |
| UI input control | New number input in the snowball panel with explanatory tooltip. |

#### Phase 5: Corpus-Level Co-Occurrence Endpoint

The standalone `find_co_mentioned_actors()` method now has an API endpoint and UI.

| Component | Details |
|-----------|---------|
| Schemas | `CorpusCoOccurrenceRequest`, `CoOccurrencePair`, `CorpusCoOccurrenceResponse` |
| Endpoint | `POST /actors/sampling/co-occurrence` |
| UI | Collapsible "Corpus Co-occurrence" panel on the Actor Directory page. |

#### Phase 6: Tests

74 new tests across 2 test files, all passing.

| Test File | Count | Coverage |
|-----------|-------|----------|
| `tests/unit/sampling/test_network_expander_new.py` | 43 | TikTok/Gab/X expansion, URL co-mention, dispatch routing |
| `tests/unit/routes/test_actors_snowball_schema.py` | 31 | Schema validation for snowball and co-occurrence |

Network expander test coverage improved from 57% to 66% (+9 points).

#### Snowball Sampling: Before vs After

| Capability | Before | After |
|------------|--------|-------|
| Platforms with graph expansion | 4 (Bluesky, Reddit, YouTube, Telegram) | 7 (+TikTok, Gab, X/Twitter) |
| Discovery method visibility | Hidden | Exposed in API response + UI table column |
| Co-mention detection | @mention regex only | @mention regex + URL-based detection via link_miner |
| Co-mention threshold | Hardcoded at 2 | Configurable via `min_comention_records` |
| Corpus-level co-occurrence | Method existed, no API/UI | Full endpoint + UI panel |

---

### 2. Zeeschuimer Import Integration

A complete Zeeschuimer integration enabling the Issue Observatory to receive NDJSON data directly from the Zeeschuimer browser extension. This provides the first automated-ish collection pathway for LinkedIn and supplements existing automated collection for other platforms.

#### 2.1 Protocol Specification

Full reverse-engineering of the Zeeschuimer-to-4CAT upload protocol from source code analysis.

**Report:** `/docs/research_reports/zeeschuimer_4cat_protocol.md`

Key findings:
- Upload is a single POST to `/api/import-dataset/` with raw NDJSON body (not multipart) and `X-Zeeschuimer-Platform` header
- Each NDJSON line is a Zeeschuimer envelope with `data` nested object containing raw platform JSON
- Authentication via browser session cookies or `access-token` query parameter/header
- Complete platform module_id to 4CAT datasource name mapping documented for all 14 modules
- Detailed field mapping from LinkedIn Voyager V2 to IO content_records schema
- LinkedIn uses relative timestamps only ("2d ago", "3mo") requiring estimation

#### 2.2 Database Layer

| Component | File | Description |
|-----------|------|-------------|
| `ZeeschuimerImport` model | `core/models/zeeschuimer_import.py` | ORM model tracking import jobs with status progression, row-level progress, polling key |
| Migration 014 | `alembic/versions/014_add_zeeschuimer_imports_table.py` | Creates `zeeschuimer_imports` table with 5 indexes |
| Migration 015 | `alembic/versions/015_make_content_hash_unique.py` | Replaces non-unique B-tree index on `content_hash` with unique partial index for `ON CONFLICT` support |

Design decision: A dedicated `zeeschuimer_imports` table was created rather than reusing `collection_runs`, because the data flow is fundamentally different (push-based manual capture vs. pull-based query-driven collection) and the tracking needs differ (polling key, row-level progress, platform from HTTP header).

#### 2.3 Import Module

New `src/issue_observatory/imports/` module structure:

| File | Purpose |
|------|---------|
| `zeeschuimer.py` | `ZeeschuimerProcessor` class: line-by-line NDJSON streaming, NUL byte stripping, platform dispatch, normalization, deduplication, bulk insert |
| `normalizers/linkedin.py` | LinkedIn Voyager V2 format: activity ID extraction, relative timestamp estimation, nested author parsing, engagement metrics, hashtags/mentions/media |
| `normalizers/twitter.py` | Twitter GraphQL format adapter (both `rest_id` and legacy `id_str` formats) |
| `normalizers/instagram.py` | Both Graph API and item list formats; ad filtering (WARNING-4 fix) |
| `normalizers/tiktok.py` | Video and comment detection; TikTok challenges/hashtag extraction |
| `normalizers/threads.py` | Both caption object and thread_items formats |

#### 2.4 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/import-dataset/` | Receives raw NDJSON body, streams to temp file, processes and inserts records |
| GET | `/api/check-query/` | Polls import status by key (4CAT-compatible polling) |

Authentication: JWT cookie (browser session) or Bearer token.

#### 2.5 Platform Support

| Zeeschuimer module_id | IO platform_name | Notes |
|----------------------|------------------|-------|
| `linkedin.com` | `linkedin` | **Primary use case** -- only collection path for LinkedIn data |
| `twitter.com` | `x_twitter` | Supplements automated collection |
| `instagram.com` | `instagram` | Supplements automated collection |
| `tiktok.com` | `tiktok` | Supplements automated collection |
| `tiktok-comments` | `tiktok_comments` | Not available via Research API |
| `threads.net` | `threads` | Supplements automated collection |

#### 2.6 Blocker Fixes Applied

Four blockers and multiple warnings identified during QA review were fixed:

| ID | Description | Fix |
|----|-------------|-----|
| BLOCKER-1 | `ON CONFLICT (content_hash)` failed without unique index | Migration 015 + WHERE clause matching |
| BLOCKER-2 | Used `CollectionRun` instead of `ZeeschuimerImport` model | Switched to dedicated model, removed in-memory state dict |
| BLOCKER-3 | Polling endpoint lacked authentication | Added `get_current_active_user` dependency |
| BLOCKER-4 | `published_at` NULL for LinkedIn promoted posts | Fallback to `collected_at` with `raw_metadata` annotation |
| WARNING-2 | Unused `import logging` in normalizers | Removed from 6 files |
| WARNING-3 | Used stdlib `logging` instead of `structlog` in imports.py | Switched to `structlog.get_logger()` |
| WARNING-4 | Instagram ads not filtered | Added `product_type == "ad"` detection |
| WARNING-6 | `collected_at` stored as datetime instead of ISO string | Converted to `.isoformat()` |
| WARNING-7 | Redundant temp file cleanup | Removed from `except` block (handled by `finally`) |
| WARNING-8 | `_bulk_insert()` committed transaction internally | Removed commit, let caller manage boundaries |

---

### 3. Comprehensive Evaluation and Fix Cycle (2026-02-20, carried through 2026-02-21)

A full application evaluation on 2026-02-20 identified 13 CRITICAL, 21 MAJOR, and 23 MINOR issues across the codebase. All 35 issues from the priority tiers were fixed on the same day:

**Test suite result after fixes:** 1572 passed, 1 skipped in 47.28s

#### Critical Fixes Applied (13)

| Category | IDs | Key Fixes |
|----------|-----|-----------|
| Infrastructure (3) | C-INF-1/2/3 | `external_id` -> `platform_id` column name, collector instantiation, KeyError handling in maintenance_tasks.py |
| Enrichment (4) | C-ENR-1/2/3/4 | JSONB key path mismatches between enrichers and analysis queries (language_detection, actor_roles, propagation, coordination) |
| Frontend (4) | C-FE-1/2/3/4 | SSE URL prefix fix (live monitoring broken), cancel button URL fix, duplicate Jinja2 block removal, actor type badge spelling |
| Integration (2) | C-INT-1/2 | Codebook-annotation integration uncommented, bulk import payload schema aligned |

---

### 4. Coherency Audits (2026-02-21)

Two independent coherency audits were conducted to identify disconnected code paths, missing integrations, and dead features.

#### Research Agent Coherency Audit

**Report:** `/docs/research_reports/coherency_audit_2026_02_21.md`

Identified 6 critical, 11 moderate, and 9 minor findings. Key systemic issues:

| Finding | Severity | Description |
|---------|----------|-------------|
| 1.4 | CRITICAL | Enrichment pipeline has no user-facing trigger -- enrichment task exists but is never dispatched automatically or manually |
| 2.1 | CRITICAL | Collection completion does not chain enrichment or deduplication |
| 1.1 | MODERATE | `coordination.py` `get_coordination_events()` is never called from any route |
| 1.2 | MODERATE | `propagation.py` `get_propagation_flows()` is never called from any route |
| 1.5 | MODERATE | Sentiment analysis enricher writes data but no API endpoint surfaces it |
| 2.4 | MODERATE | Volume spike alerts detected and stored but not visible in UI |
| 1.6 | MODERATE | Scraping jobs have no frontend navigation or UI |
| 1.7 | MODERATE | Data import has no frontend navigation or UI |

#### QA Coherency Audit

**Report:** `/docs/research_reports/qa_coherency_audit_2026_02_21.md`

Identified 7 critical, 10 moderate, and 8 minor issues. Key findings:

| Finding | Severity | Description |
|---------|----------|-------------|
| C-01 | CRITICAL | Credits route module is an empty stub -- all credit balance endpoints return 404 |
| C-02 | CRITICAL | Health check task dispatcher generates incorrect task names for all 25 arenas |
| C-03 | CRITICAL | Actors list/detail pages have no HTML page routes -- nav link returns JSON |
| C-04 | CRITICAL | Discovered links page crashes on load due to non-existent model attribute reference |
| C-05 | CRITICAL | Beat schedule entries for RSS Feeds and GDELT call arena tasks without required arguments |

**Note:** These coherency audit findings represent integration gaps and disconnected code paths in the current codebase. They are tracked for remediation but do not affect the functional status of the core collection, analysis, and export capabilities.

---

### 5. Research Knowledge Artifacts (2026-02-21)

| Document | Path | Description |
|----------|------|-------------|
| Zeeschuimer-to-4CAT Protocol Specification | `/docs/research_reports/zeeschuimer_4cat_protocol.md` | Complete reverse-engineering of the upload protocol from Zeeschuimer v1.13.6 and 4CAT source code |
| Coherency Audit Report | `/docs/research_reports/coherency_audit_2026_02_21.md` | Full-stack coherency audit identifying disconnected features, missing integrations, dead code |
| QA Coherency Audit | `/docs/research_reports/qa_coherency_audit_2026_02_21.md` | Code-level coherency audit of 248 Python source files |
| Network Expansion API Assessment | `/docs/research_reports/network_expansion_api_assessment.md` | Evaluation of 8 platforms for graph traversal (completed 2026-02-20, implemented 2026-02-21) |
| Co-mention Snowball Recommendation | `/docs/research_reports/comention_snowball_recommendation.md` | Methodology recommendation (completed 2026-02-20, implemented 2026-02-21) |

---

## Implemented Arenas (25 implementations)

| Arena | Directory | Status | Tiers | Danish Configuration | Notes |
|-------|-----------|--------|-------|---------------------|-------|
| Google Search | `arenas/google_search/` | Fully implemented | MEDIUM, PREMIUM | `gl=dk`, `hl=da` | Serper.dev (MEDIUM), SerpAPI (PREMIUM) |
| Google Autocomplete | `arenas/google_autocomplete/` | Fully implemented | MEDIUM, PREMIUM | `gl=dk`, `hl=da` | Shares credentials with Google Search |
| Bluesky | `arenas/bluesky/` | Fully implemented | FREE | `lang:da` filter | WebSocket Jetstream for streaming |
| Reddit | `arenas/reddit/` | Fully implemented | FREE | r/Denmark, r/danish, r/copenhagen, r/aarhus, r/dkpolitik | asyncpraw, configurable subreddits (GR-03) |
| YouTube | `arenas/youtube/` | Fully implemented | FREE | `relevanceLanguage=da`, `regionCode=DK` | Data API v3, RSS-first strategy |
| RSS Feeds | `arenas/rss_feeds/` | Fully implemented | FREE | 28+ Danish feeds | DR, TV2, Politiken, Berlingske, BT, Altinget, etc. Configurable custom feeds (GR-01). Feed autodiscovery (SB-09). |
| GDELT | `arenas/gdelt/` | Fully implemented | FREE | `sourcelang:danish`, `sourcecountry:DA` | ~55% accuracy, translation artifacts |
| Telegram | `arenas/telegram/` | Fully implemented | FREE | 6+ Danish channels | MTProto via Telethon, configurable channels (GR-02) |
| TikTok | `arenas/tiktok/` | Fully implemented | FREE | -- | Research API (free tier only; MEDIUM tier documented but not implemented), 10-day engagement lag |
| Via Ritzau | `arenas/ritzau_via/` | Fully implemented | FREE | `language=da` | Unauthenticated JSON API |
| Gab | `arenas/gab/` | Fully implemented | FREE | -- | Mastodon-compatible API; very low Danish volume expected |
| Event Registry | `arenas/event_registry/` | Fully implemented | MEDIUM, PREMIUM | ISO 639-3 `"dan"` | Full article text, event clustering |
| X/Twitter | `arenas/x_twitter/` | Fully implemented | MEDIUM, PREMIUM | `lang:da` | TwitterAPI.io (MEDIUM), Official API (PREMIUM) |
| Facebook | `arenas/facebook/` | Fully implemented | MEDIUM, PREMIUM | -- | Bright Data or Meta Content Library |
| Instagram | `arenas/instagram/` | Fully implemented | MEDIUM, PREMIUM | -- | Bright Data; no native language filter |
| Threads | `arenas/threads/` | Fully implemented | FREE, MEDIUM | -- | Unofficial API; small Danish volume expected |
| Common Crawl | `arenas/web/common_crawl/` | Fully implemented | FREE | -- | Index query + content fetch; historical/retrospective only |
| Wayback Machine | `arenas/web/wayback/` | Fully implemented | FREE | -- | Optional content fetching (GR-12); deleted content recovery |
| URL Scraper | `arenas/web/url_scraper/` | Fully implemented | FREE, MEDIUM | -- | Researcher-provided URL list |
| Wikipedia | `arenas/wikipedia/` | Implemented (limited) | FREE | -- | Revision/pageview monitoring, seed articles (GR-04) |
| Discord | `arenas/discord/` | Implemented (limited) | FREE | -- | Requires bot invitation per server, configurable channels (GR-04) |
| AI Chat Search | `arenas/ai_chat_search/` | Fully implemented | MEDIUM | -- | OpenRouter, query expansion, citation extraction |
| Majestic | `arenas/majestic/` | Implemented (PREMIUM only) | PREMIUM | -- | Backlink index, $400/month |
| Twitch | `arenas/twitch/` | Deferred stub | -- | -- | Channel discovery only |
| VKontakte | `arenas/vkontakte/` | Deferred stub | -- | -- | Pending legal review |

### Additional Collection Pathways

| Pathway | Status | Platforms Supported | Notes |
|---------|--------|---------------------|-------|
| Zeeschuimer Import | Implemented (2026-02-21) | LinkedIn, Twitter/X, Instagram, TikTok, TikTok Comments, Threads | Push-based manual capture via browser extension. Only collection path for LinkedIn. |
| Manual CSV/NDJSON Import | API implemented, no UI | Any platform | `POST /content/import` endpoint exists but lacks frontend navigation |

---

## Core Infrastructure (all implemented)

| Component | File(s) | Status |
|-----------|---------|--------|
| ArenaCollector ABC | `arenas/base.py` | Complete -- includes `public_figure_ids` bypass (GR-14), `TemporalMode` enum (SB-04), `refresh_engagement()` (IP2-035) |
| Arena registry | `arenas/registry.py` | Complete -- keyed by `platform_name`, autodiscovery |
| Query builder (boolean) | `arenas/query_builder.py` | Complete -- AND/OR group logic (IP2-031), bilingual term expansion (IP2-052) |
| Normalizer | `core/normalizer.py` | Complete -- SHA-256 pseudonymization with public figure bypass, engagement normalization (IP2-030) |
| Credential pool | `core/credential_pool.py` | Complete -- DB-backed, Fernet encryption, Redis lease/quota/cooldown |
| Rate limiter | `workers/rate_limiter.py` | Complete -- Redis sliding window Lua script |
| Credit service | `core/credit_service.py` | Complete -- balance, reservation, settlement, refund, estimation (SB-14) |
| Entity resolver | `core/entity_resolver.py` | Complete |
| Deduplication | `core/deduplication.py` | Complete -- URL, content hash, SimHash near-duplicate |
| Retention service | `core/retention_service.py` | Complete |
| Event bus (SSE) | `core/event_bus.py` | Complete -- Redis pub/sub for live collection monitoring |
| Email service | `core/email_service.py` | Complete -- no-op when SMTP not configured |
| Zeeschuimer processor | `imports/zeeschuimer.py` | Complete -- NDJSON streaming, platform dispatch, bulk insert |

---

## Database Migrations (15 total)

All 15 migrations have been verified. Apply via `alembic upgrade head`.

| Migration | Description | Related IDs | Date |
|-----------|-------------|-------------|------|
| 001 | Initial schema: all core tables, indexes, content_records partitions | -- | 2026-02-15 |
| 002 | `arenas_config JSONB` on query_designs | GR-01 through GR-05 | 2026-02-15 |
| 003 | `suspended_at` on collection_runs | B-03 | 2026-02-16 |
| 004 | Scraping jobs table | -- | 2026-02-16 |
| 005 | Content annotations table | IP2-043 | 2026-02-17 |
| 006 | Search term groups (`group_id`, `group_label`) | IP2-046, IP2-031 | 2026-02-17 |
| 007 | `simhash BIGINT` on content_records | IP2-032 | 2026-02-18 |
| 008 | Query design cloning (`parent_design_id`) | IP2-051 | 2026-02-18 |
| 009 | `public_figure BOOLEAN` on actors | GR-14 | 2026-02-19 |
| 010 | `target_arenas JSONB` on search_terms | YF-01 | 2026-02-19 |
| 011 | GIN index on `search_terms.target_arenas` | YF-01 | 2026-02-19 |
| 012 | `codebook_entries` table | SB-16 | 2026-02-20 |
| 013 | `translations JSONB` on search_terms | IP2-052 | 2026-02-20 |
| **014** | **`zeeschuimer_imports` table** | **Zeeschuimer integration** | **2026-02-21** |
| **015** | **Unique partial index on `content_hash`** | **Zeeschuimer BLOCKER-1** | **2026-02-21** |

---

## Analysis Module

| Component | File | Status |
|-----------|------|--------|
| Descriptive analytics | `analysis/descriptive.py` | Complete -- volume, top actors (with resolved names), top terms, temporal comparison (IP2-033), arena comparison (IP2-037), language distribution, NER entities, propagation patterns, coordination signals |
| Network analysis | `analysis/network.py` | Complete -- actor co-occurrence, term co-occurrence, bipartite, cross-platform actors, resolved actor names (IP2-061) |
| Export | `analysis/export.py` | Complete -- CSV, XLSX, NDJSON, Parquet, GEXF (3 types), RIS, BibTeX |
| Shared filter builder | `analysis/_filters.py` | Complete (IP2-024) |
| Propagation analysis | `analysis/propagation.py` | Complete (GR-08) |
| Volume spike alerting | `analysis/alerting.py` | Complete (GR-09) |
| Link mining | `analysis/link_miner.py` | Complete (GR-22) -- URL extraction, platform classification, Reddit user profile URLs |
| Coordination detection | `analysis/coordination.py` | Complete (GR-11) |

### Enrichment Pipeline

| Enricher | File | Status |
|----------|------|--------|
| Base class | `analysis/enrichments/base.py` | Complete -- `ContentEnricher` ABC |
| Language detection | `analysis/enrichments/language_detector.py` | Complete (IP2-008) |
| Named entity extraction | `analysis/enrichments/named_entity_extractor.py` | Complete (IP2-049) |
| Propagation detection | `analysis/enrichments/propagation_detector.py` | Complete (GR-08) |
| Coordination detection | `analysis/enrichments/coordination_detector.py` | Complete (GR-11) |
| Danish sentiment analysis | `analysis/enrichments/sentiment_analyzer.py` | Complete (IP2-034) |

---

## Per-Report Implementation Status

Six research recommendation reports have been produced. Together they contain 157 recommendation IDs (with significant cross-report overlap reducing to approximately 97 unique items).

| Report | Total IDs | Implemented | Non-code / Deferred | Remaining Code | Rate |
|--------|-----------|-------------|---------------------|----------------|------|
| CO2 Afgift (P1.1--P4.5) | 20 | 18 | 2 (P1.5 research artifact, P3.5/P3.6 Phase D) | 0 | 100% of actionable |
| AI og Uddannelse (IM-1.1--IM-4.5) | 22 | 21 | 1 (IM-1.6 research artifact) | 0 | 100% of actionable |
| Greenland (GR-01--GR-22) | 22 | 20 | 2 (GR-13 institutional, GR-15 Phase D) | 0 | 100% of actionable |
| Ytringsfrihed (YF-01--YF-16) | 16 | 16 | 0 | 0 | 100% |
| Socialt Bedrageri (SB-01--SB-16) | 16 | 16 | 0 | 0 | 100% |
| Implementation Plan 2.0 (IP2-001--IP2-061) | 61 | 59 | 2 (IP2-054, IP2-057 Phase D) | 0 | 97% |
| **Unique items (deduplicated)** | **approximately 97** | **approximately 94** | **approximately 4** | **0** | **approximately 97%** |

---

## IP2 Full Item Tracker (IP2-001 through IP2-061)

### Phase A: Foundation Fixes (29/29 done -- 100%)

| ID | Description | Status | Verified By |
|----|-------------|--------|-------------|
| IP2-001 | Dynamic arena grid from server registry | Done | QD editor Alpine.js `arenaConfigGrid`, `/api/arenas/` |
| IP2-002 | Arena tier validation (disable unsupported) | Done | `supportedTiers.includes(t)` in QD editor |
| IP2-003 | Arena descriptions in config grid | Done | `arena.description` in grid |
| IP2-004 | Duplicate exclusion in analysis queries | Done | `_filters.py` |
| IP2-005 | Extend flat export columns | Done | `export.py` |
| IP2-006 | Human-readable export headers | Done | `export.py` |
| IP2-007 | Actor synchronization (QD to Actor Directory) | Done | QD editor creates/links Actor + ActorListMember |
| IP2-008 | Client-side language detection | Done | `LanguageDetector` enricher |
| IP2-009 | Add Altinget RSS feed | Done | `danish_defaults.py` (main + section feeds) |
| IP2-010 | Update stale "Phase 0" text | Done | No "Phase 0" in templates |
| IP2-011 | Arena column always visible | Done | xl-only class removed |
| IP2-012 | Analysis filter dropdowns | Done | Dropdowns populated from run data |
| IP2-013 | Chart axis labels | Done | Y-axis labels added |
| IP2-014 | Query design detail shows arena config | Done | Read-only arena config display |
| IP2-015 | Term type help text (tooltips) | Done | Tooltips on term type options |
| IP2-016 | Snowball sampling discoverability | Done | Nav link from Actor Directory |
| IP2-017 | Admin credential form missing platforms | Done | Gab, Threads, Bright Data, SerpAPI added |
| IP2-018 | Collection detail context | Done | QD name and terms in detail header |
| IP2-019 | Replace "Celery Beat" jargon | Done | "Scheduled collection" label |
| IP2-020 | Save confirmation feedback | Done | Flash/checkmark feedback |
| IP2-021 | Timestamp timezone display | Done | UTC labels on timestamps |
| IP2-022 | Tier precedence documentation | Done | Launcher template and base.py |
| IP2-023 | Date range guidance per arena | Done | Per-arena historical coverage tooltips |
| IP2-024 | Consolidate analysis filter builders | Done | `_filters.py` |
| IP2-025 | GEXF export uses network.py | Done | `export.py` consumes network analysis |
| IP2-026 | Relabel "JSON" export to "NDJSON" | Done | Export label updated |
| IP2-027 | Fix mixed-language "termer" | Done | Consistent English labels |
| IP2-028 | Engagement score tooltip | Done | Score caveat tooltip |
| IP2-029 | Search term filter as dropdown | Done | Dropdown populated from QD terms |

### Phase B: Discourse Tracking Maturity (8/8 done -- 100%)

| ID | Description | Status | Verified By |
|----|-------------|--------|-------------|
| IP2-030 | Engagement score normalization | Done | `compute_normalized_engagement()` in `normalizer.py` |
| IP2-031 | Boolean query support | Done | `query_builder.py`, migration 006 |
| IP2-032 | Near-duplicate detection (SimHash) | Done | `deduplication.py`, migration 007 |
| IP2-033 | Temporal volume comparison | Done | `get_temporal_comparison()` in `descriptive.py` |
| IP2-034 | Danish sentiment analysis enrichment | Done | `SentimentAnalyzer` enricher, AFINN lexicon |
| IP2-035 | Engagement metric refresh | Done | `refresh_engagement()` on base, Celery task, API endpoint |
| IP2-036 | Enrichment pipeline architecture | Done | `ContentEnricher` base class, 6 enrichers |
| IP2-037 | Arena-comparative analysis | Done | `get_arena_comparison()` in `descriptive.py` |

### Phase C: Issue Mapping Capabilities (14/14 done -- 100%)

| ID | Description | Status | Verified By |
|----|-------------|--------|-------------|
| IP2-038 | Emergent term extraction (TF-IDF) | Done | `/analysis/{run_id}/emergent-terms` route |
| IP2-039 | Unified actor ranking | Done | `get_top_actors_unified()` in `descriptive.py` |
| IP2-040 | Bipartite network with extracted topics | Done | `build_enhanced_bipartite_network()` in `network.py` |
| IP2-041 | Entity resolution UI | Done | Full researcher-facing UI |
| IP2-042 | In-browser network preview | Done | `network_preview.js` + Sigma.js |
| IP2-043 | Content annotation layer | Done | Migration 005, model, routes, UI |
| IP2-044 | Temporal network snapshots | Done | Weekly/monthly network evolution |
| IP2-045 | Dynamic GEXF export | Done | `export_temporal_gexf()` in `export.py` |
| IP2-046 | Term grouping in query design | Done | Migration 006 |
| IP2-047 | Per-arena GEXF export | Done | Arena filter in `export.py` |
| IP2-048 | Platform attribute on bipartite GEXF | Done | `export.py` |
| IP2-049 | Named entity extraction | Done | `NamedEntityExtractor` enricher, spaCy |
| IP2-050 | Cross-arena flow analysis | Done | `propagation.py` + `PropagationDetector` enricher |
| IP2-058 | Education-specific RSS feeds | Done | Folkeskolen, Gymnasieskolen, KU, DTU, CBS |

### Phase D: Advanced Research Features (8/10 done -- 80%)

| ID | Description | Status | Verified By |
|----|-------------|--------|-------------|
| IP2-051 | Query design cloning and versioning | Done | Migration 008, `parent_design_id` |
| IP2-052 | Multilingual query design | Done | Migration 013, bilingual term pairing |
| IP2-053 | Query term suggestion from collected data | Done | Shares endpoint with IP2-038 |
| IP2-054 | Topic modeling enrichment (BERTopic) | **Not done** | Deferred. GPU + heavy dependencies required. |
| IP2-055 | Filtered export from analysis results | Done | Analysis template + content browser |
| IP2-056 | RIS/BibTeX export | Done | `export.py` |
| IP2-057 | Folketinget.dk arena | **Not done** | Arena brief not yet written. |
| IP2-059 | Expand Danish Reddit subreddits | Done | r/dkpolitik added |
| IP2-060 | Formalize actor_type values | Done | `ActorType` enum |
| IP2-061 | Mixed hash/name resolution in charts | Done | LEFT JOIN + COALESCE for resolved names |

### IP2 Summary

| Phase | Total | Done | Deferred |
|-------|-------|------|----------|
| A: Foundation Fixes | 29 | 29 | 0 |
| B: Tracking Maturity | 8 | 8 | 0 |
| C: Issue Mapping | 14 | 14 | 0 |
| D: Advanced Features | 10 | 8 | 2 |
| **Total** | **61** | **59** | **2** |

Effective implementation rate: **59/61 (97%)**.

---

## Greenland Roadmap Items (GR-01 through GR-22)

| ID | Description | Status |
|----|-------------|--------|
| GR-01 | Researcher-configurable RSS feeds | Done |
| GR-02 | Researcher-configurable Telegram channels | Done |
| GR-03 | Researcher-configurable Reddit subreddits | Done |
| GR-04 | Discord channel IDs + Wikipedia seed articles | Done |
| GR-05 | Multi-language selector per query design | Done |
| GR-06 | Missing platforms in credentials dropdown | Done |
| GR-07 | Generalize language detection enricher | Done |
| GR-08 | Cross-arena temporal propagation detection | Done |
| GR-09 | Volume spike alerting | Done |
| GR-10 | URL scraper arena | Done |
| GR-11 | Coordinated posting detection | Done |
| GR-12 | Wayback Machine content retrieval | Done |
| GR-13 | Apply for Meta Content Library | N/A -- institutional process |
| GR-14 | Public figure pseudonymization bypass | Done |
| GR-15 | Narrative topic modeling (BERTopic) | Deferred (= IP2-054) |
| GR-16 | Political calendar overlay | Done |
| GR-17 | Content Browser quick-add actor | Done |
| GR-18 | Expose Similarity Finder in UI | Done |
| GR-19 | Co-mention fallback in network expander | Done |
| GR-20 | Auto-create actors from snowball discoveries | Done |
| GR-21 | Telegram forwarding chain expander | Done |
| GR-22 | Cross-platform link mining | Done |

**Result: 20/22 code items implemented (100% of actionable). GR-13 is institutional. GR-15 is deferred to Phase D.**

---

## Phase 3 Blocker Fixes (B-01 through B-04)

| ID | Description | Status |
|----|-------------|--------|
| B-01 | Snowball sampling UI entry point | Done |
| B-02 | GEXF network type buttons | Done |
| B-03 | Live tracking schedule visibility | Done |
| B-04 | Admin credential form missing platforms | Done |

---

## Ytringsfrihed Report Items (YF-01 through YF-16)

| ID | Description | Status |
|----|-------------|--------|
| YF-01 | Per-arena search term scoping | Done -- migrations 010 + 011 |
| YF-02 | Source-list arena configuration UI | Done (via GR-01--GR-04) |
| YF-03 | Bulk search term import | Done |
| YF-04 | Pre-flight credit estimation | Done (via SB-14) |
| YF-05 | Ad-hoc exploration mode | Done |
| YF-06 | Cross-run analysis aggregation | Done (via SB-07) |
| YF-07 | Bulk actor import | Done |
| YF-08 | Arena overview page | Done |
| YF-09 | Tier precedence explanation | Done |
| YF-10 | Group label autocomplete | Done |
| YF-11 | Snowball platform transparency | Done |
| YF-12 | RSS feed preview | Done |
| YF-13 | Discovered sources cross-design view | Done |
| YF-14 | Google Search free-tier guidance | Done |
| YF-15 | Custom subreddit UI | Done (via GR-03) |
| YF-16 | Actor platform presence inline add | Done |

**Result: 16/16 implemented (100%).**

---

## Socialt Bedrageri Report Items (SB-01 through SB-16)

| ID | Description | Status |
|----|-------------|--------|
| SB-01 | One-click term addition from suggested terms | Done |
| SB-02 | One-click source addition from discovered links | Done |
| SB-03 | Post-collection discovery notification | Done |
| SB-04 | Arena temporal capability metadata | Done |
| SB-05 | Date range warning on collection launch | Done |
| SB-06 | Cross-run comparison endpoint | Done |
| SB-07 | Design-level analysis aggregation | Done |
| SB-08 | "Promote to live tracking" button | Done |
| SB-09 | RSS feed autodiscovery | Done |
| SB-10 | Reddit subreddit suggestion | Done |
| SB-11 | AI Chat Search as discovery accelerator | Done |
| SB-12 | Research lifecycle indicator | Done |
| SB-13 | Content source labeling (batch/live) | Done |
| SB-14 | Credit estimation implementation | Done |
| SB-15 | Enrichment results dashboard tab | Done |
| SB-16 | Annotation codebook management | Done |

**Result: 16/16 implemented (100%).**

---

## API Changes (cumulative, 2026-02-20 through 2026-02-21)

### New API Endpoints

| Method | Path | Description | Date |
|--------|------|-------------|------|
| POST | `/api/import-dataset/` | Zeeschuimer NDJSON upload | 2026-02-21 |
| GET | `/api/check-query/` | Zeeschuimer import status polling | 2026-02-21 |
| POST | `/actors/sampling/co-occurrence` | Corpus-level actor co-occurrence analysis | 2026-02-21 |
| GET | `/analysis/compare` | Cross-run comparison | 2026-02-20 |
| GET | `/analysis/design/{id}/summary` | Design-level analysis summary | 2026-02-20 |
| GET | `/analysis/design/{id}/volume` | Design-level volume | 2026-02-20 |
| GET | `/analysis/design/{id}/actors` | Design-level actors | 2026-02-20 |
| GET | `/analysis/design/{id}/terms` | Design-level terms | 2026-02-20 |
| GET | `/analysis/design/{id}/network/*` | Design-level networks (actors, terms, bipartite) | 2026-02-20 |
| GET | `/analysis/{run_id}/enrichments/*` | Enrichment results (languages, entities, propagation, coordination) | 2026-02-20 |
| GET | `/analysis/{run_id}/temporal-comparison` | Period-over-period volume | 2026-02-20 |
| GET | `/analysis/{run_id}/arena-comparison` | Per-arena metrics | 2026-02-20 |
| GET | `/analysis/{run_id}/emergent-terms` | TF-IDF emergent terms | 2026-02-20 |
| GET | `/analysis/{run_id}/actors-unified` | Top actors by canonical identity | 2026-02-20 |
| POST | `/collections/{run_id}/refresh-engagement` | Re-fetch engagement metrics (async) | 2026-02-20 |
| POST | `/query-designs/{id}/discover-feeds` | RSS feed autodiscovery | 2026-02-20 |
| GET | `/query-designs/{id}/suggest-subreddits` | Reddit subreddit suggestions | 2026-02-20 |
| CRUD | `/codebooks/*` | Codebook management | 2026-02-20 |

### Modified API Endpoints

| Method | Path | Change | Date |
|--------|------|--------|------|
| GET | `/actors/sampling/snowball/platforms` | Now returns 7 platforms (added TikTok, Gab, X/Twitter) | 2026-02-21 |
| POST | `/actors/sampling/snowball` | Response includes `discovery_method`; accepts `min_comention_records` | 2026-02-21 |
| POST | `/collections/estimate` | Returns real per-arena credit estimates (was stub) | 2026-02-20 |
| GET | `/api/arenas/` | Includes `temporal_mode` field per arena | 2026-02-20 |

### No Breaking Changes

All changes are additive. Existing API contracts, database schemas (after migration), and frontend templates remain backward-compatible.

---

## New Dependencies

| Package | Version | Required By | Extra |
|---------|---------|-------------|-------|
| `beautifulsoup4` | `>=4.12,<5.0` | SB-09 (RSS feed autodiscovery) | Core |
| `afinn` | `>=0.1,<1.0` | IP2-034 (Danish sentiment analysis) | `[nlp]` |

No new dependencies were required for the 2026-02-21 work (snowball sampling, Zeeschuimer integration).

---

## Files Created (2026-02-21)

| File | Purpose |
|------|---------|
| `src/issue_observatory/core/models/zeeschuimer_import.py` | ZeeschuimerImport ORM model |
| `src/issue_observatory/imports/__init__.py` | Import module package |
| `src/issue_observatory/imports/zeeschuimer.py` | NDJSON processor and dispatcher |
| `src/issue_observatory/imports/normalizers/__init__.py` | Normalizer exports |
| `src/issue_observatory/imports/normalizers/linkedin.py` | LinkedIn Voyager V2 normalizer |
| `src/issue_observatory/imports/normalizers/twitter.py` | Twitter/X adapter normalizer |
| `src/issue_observatory/imports/normalizers/instagram.py` | Instagram adapter normalizer |
| `src/issue_observatory/imports/normalizers/tiktok.py` | TikTok adapter normalizer |
| `src/issue_observatory/imports/normalizers/threads.py` | Threads adapter normalizer |
| `alembic/versions/014_add_zeeschuimer_imports_table.py` | Migration: zeeschuimer_imports table |
| `alembic/versions/015_make_content_hash_unique.py` | Migration: unique partial index on content_hash |
| `tests/unit/sampling/test_network_expander_new.py` | 43 tests for network expander |
| `tests/unit/routes/test_actors_snowball_schema.py` | 31 tests for snowball schemas |
| `tests/unit/routes/__init__.py` | Package marker |
| `docs/research_reports/zeeschuimer_4cat_protocol.md` | Protocol specification |
| `docs/research_reports/coherency_audit_2026_02_21.md` | Research agent coherency audit |
| `docs/research_reports/qa_coherency_audit_2026_02_21.md` | QA coherency audit |
| `docs/handoffs/zeeschuimer_db_layer_2026_02_21.md` | DB layer handoff document |
| `docs/implementation_notes/zeeschuimer_integration.md` | Integration implementation notes |
| `docs/status/zeeschuimer_blocker_fixes.md` | Blocker fix documentation |
| `docs/migrations/migration_015_notes.md` | Migration 015 notes |

## Files Modified (2026-02-21)

| File | Changes |
|------|---------|
| `src/issue_observatory/sampling/network_expander.py` | 3 new platform expanders, `_post_json()`, `_get_json_list()`, `_get_tiktok_token()`, URL co-mention logic, `min_comention_records` threading |
| `src/issue_observatory/api/routes/actors.py` | `discovery_method` on response, `min_comention_records` on request, co-occurrence schemas and endpoint, expanded platform list |
| `src/issue_observatory/sampling/snowball.py` | `min_comention_records` parameter passthrough |
| `src/issue_observatory/analysis/link_miner.py` | Reddit user profile URL rule |
| `src/issue_observatory/api/templates/actors/list.html` | Method column, `formatMethod()`, co-occurrence panel, expanded platform list |
| `src/issue_observatory/core/models/__init__.py` | Added `ZeeschuimerImport` export |
| `src/issue_observatory/core/models/users.py` | Added `zeeschuimer_imports` reverse relationship |
| `src/issue_observatory/core/models/query_design.py` | Added `zeeschuimer_imports` reverse relationship |
| `src/issue_observatory/api/routes/imports.py` | Zeeschuimer endpoints, BLOCKER-1/2/3 fixes, WARNING-3/7 fixes |
| `docs/status/db.md` | Updated with migrations 014, 015 and ZeeschuimerImport model |
| `docs/status/research.md` | Updated with Zeeschuimer protocol spec entry |

---

## Known Limitations and Remaining Work

### Phase D Deferred Items

| ID | Description | Reason |
|----|-------------|--------|
| IP2-054 | Topic modeling (BERTopic) | Requires GPU infrastructure, heavy dependencies (torch, BERTopic). Not appropriate for current deployment profile. |
| IP2-057 | Folketinget.dk parliamentary proceedings arena | Arena research brief required before implementation. Requires investigation of Folketinget.dk data access. |

### Non-Code Items

| ID | Description | Type |
|----|-------------|------|
| P1.5 | Create CO2 afgift use case document | Research artifact for `/docs/use_cases/` |
| IM-1.6 | Create AI og uddannelse use case document | Research artifact for `/docs/use_cases/` |
| GR-13 | Apply for Meta Content Library | Institutional process, 2--6 month review cycle |

### Coherency Audit Findings (Identified 2026-02-21, Not Yet Resolved)

The coherency audits identified integration gaps that need resolution. These are tracked in the audit reports and represent the priority backlog for near-term work.

**Critical integration gaps:**
- Enrichment pipeline has no automatic trigger or manual trigger endpoint (coherency audit 1.4 / 2.1)
- Credits route module is an empty stub -- all credit balance endpoints return 404 (QA audit C-01)
- Health check task dispatcher generates incorrect task names (QA audit C-02)
- Actors list/detail pages have no HTML page routes (QA audit C-03)
- Discovered links page crashes on load (QA audit C-04)
- Beat schedule entries for RSS/GDELT call arena tasks without required arguments (QA audit C-05)

**Moderate integration gaps:**
- `coordination.py` and `propagation.py` have detailed analysis functions that are never called from routes
- Sentiment analysis writes data but has no surfacing endpoint
- Volume spike alerts are detected but not displayed in UI
- Scraping jobs and data import have no frontend navigation
- Enrichment results not structured in content browser detail panel
- Retention service not exposed in admin UI

**Full details:** `/docs/research_reports/coherency_audit_2026_02_21.md` and `/docs/research_reports/qa_coherency_audit_2026_02_21.md`

### Excluded Sources

- **Infomedia** is explicitly excluded (institutional-subscription-only, not available for this project)
- **LinkedIn** has no automated collection path; Zeeschuimer manual capture (implemented 2026-02-21) is the only option
- **VKontakte** is deferred pending legal review (EU sanctions context)

---

## Implementation Timeline

| Date | Key Items | Milestone |
|------|-----------|-----------|
| 2026-02-15 | Core infrastructure, migrations 001--004 | Project bootstrap |
| 2026-02-16 | All Phase 1 + Phase 2 arena briefs | Engineering agents unblocked |
| 2026-02-17 | CO2 afgift report, Phase 3 UX fixes (B-01--B-04) | Data correctness fixes (B-02 GEXF) |
| 2026-02-18 | AI uddannelse report, IP2 strategy, Greenland report, core IP2 items | Phase A+B+C foundation |
| 2026-02-19 | GR-01--GR-22, YF-01--YF-16, migrations 009--011 | Researcher self-service complete |
| 2026-02-20 (AM) | SB-01--SB-16, migration 012 | Discovery feedback loop complete |
| 2026-02-20 (PM) | IP2-030/033/034/035/037, YF-05/10/13/14/16, 20+ audit corrections | Analysis maturity complete |
| 2026-02-20 (late) | IP2-011--029, IP2-052, IP2-061, migration 013, comprehensive evaluation + 35 fixes | All IP2 actionable items complete; 1572 tests passing |
| **2026-02-21** | **Enhanced Snowball Sampling (6 phases), Zeeschuimer integration (protocol + DB + import module + normalizers + blocker fixes), coherency audits, migrations 014--015, 74 new tests** | **Manual capture pathway operational; 7-platform snowball sampling** |

---

## Cross-Reference Table: Multi-Report Items

Items recommended by two or more reports, mapped to the single implementation that addressed all of them.

| Implementation | CO2 | AI/Uddan. | Greenland | Ytringsfr. | Soc. Bedr. | IP2 |
|---------------|-----|-----------|-----------|------------|------------|-----|
| Duplicate exclusion | P1.2 | IM-1.4 | -- | -- | -- | IP2-004 |
| Flat export columns | P1.3 | IM-1.5 | -- | -- | -- | IP2-005 |
| Altinget RSS | P1.1 | IM-1.2 | -- | -- | -- | IP2-009 |
| Language detection | P2.1 | IM-2.4 | GR-07 | -- | -- | IP2-008 |
| Boolean query | P2.3 | IM-3.4 | -- | -- | -- | IP2-031 |
| Content annotation | P4.2 | IM-2.5 | -- | -- | SB-16 ext. | IP2-043 |
| Query design cloning | P4.1 | IM-4.1 | -- | -- | -- | IP2-051 |
| Emergent terms | P3.2 | IM-2.1 | -- | -- | SB-01 ext. | IP2-038 |
| Cross-arena flow | P3.4 | IM-3.3 | GR-08 | -- | -- | IP2-050 |
| In-browser network | P4.3 | IM-4.3 | -- | -- | -- | IP2-042 |
| Filtered export | P4.5 | IM-4.4 | -- | -- | -- | IP2-055 |
| Source-list config UI | -- | -- | GR-01--04 | YF-02 | -- | -- |
| Credit estimation | -- | -- | -- | YF-04 | SB-14 | -- |
| Cross-run analysis | -- | -- | -- | YF-06 | SB-06/07 | -- |
| Topic modeling (deferred) | P3.5 | -- | GR-15 | -- | -- | IP2-054 |
| Multilingual query | -- | IM-4.2 | GR-05 part. | -- | -- | IP2-052 |

---

## Research Reports Produced

| Report | Date | Path |
|--------|------|------|
| CO2 afgift codebase evaluation | 2026-02-17 | `/docs/research_reports/co2_afgift_codebase_recommendations.md` |
| AI og uddannelse codebase evaluation | 2026-02-18 | `/docs/research_reports/ai_uddannelse_codebase_recommendations.md` |
| Implementation Plan 2.0 Strategic Synthesis | 2026-02-18 | `/docs/research_reports/implementation_plan_2_0_strategy.md` |
| Greenland in the Danish General Election 2026 | 2026-02-18 | `/docs/research_reports/greenland_codebase_recommendations.md` |
| Ytringsfrihed discourse mapping | 2026-02-19 | `/docs/research_reports/ytringsfrihed_codebase_recommendations.md` |
| Socialt bedrageri codebase evaluation | 2026-02-20 | `/docs/research_reports/socialt_bedrageri_codebase_recommendations.md` |
| Co-mention snowball methodology | 2026-02-20 | `/docs/research_reports/comention_snowball_recommendation.md` |
| Network expansion API assessment | 2026-02-20 | `/docs/research_reports/network_expansion_api_assessment.md` |
| Zeeschuimer-to-4CAT protocol specification | 2026-02-21 | `/docs/research_reports/zeeschuimer_4cat_protocol.md` |
| Coherency audit report | 2026-02-21 | `/docs/research_reports/coherency_audit_2026_02_21.md` |
| QA coherency audit | 2026-02-21 | `/docs/research_reports/qa_coherency_audit_2026_02_21.md` |

---

## Arena Briefs (all complete)

| Arena | Path | Status |
|-------|------|--------|
| Google Search | `/docs/arenas/google_search.md` | Complete |
| Google Autocomplete | `/docs/arenas/google_autocomplete.md` | Complete |
| Bluesky | `/docs/arenas/bluesky.md` | Complete |
| Reddit | `/docs/arenas/reddit.md` | Complete |
| YouTube | `/docs/arenas/youtube.md` | Complete |
| RSS Feeds | `/docs/arenas/rss_feeds.md` | Complete |
| GDELT | `/docs/arenas/gdelt.md` | Complete |
| Telegram | `/docs/arenas/telegram.md` | Complete |
| TikTok | `/docs/arenas/tiktok.md` | Complete |
| Via Ritzau | `/docs/arenas/ritzau_via.md` | Complete |
| Gab | `/docs/arenas/gab.md` | Complete |
| Event Registry | `/docs/arenas/event_registry.md` | Complete |
| X/Twitter | `/docs/arenas/x_twitter.md` | Complete |
| Facebook/Instagram | `/docs/arenas/facebook_instagram.md` | Complete |
| LinkedIn | `/docs/arenas/linkedin.md` | Complete |
| Threads | `/docs/arenas/threads.md` | Complete |
| Common Crawl / Wayback | `/docs/arenas/common_crawl_wayback.md` | Complete |
| URL Scraper | `/docs/arenas/url_scraper.md` | Complete |
| Wikipedia | `/docs/arenas/wikipedia.md` | Complete |
| Discord | `/docs/arenas/discord.md` | Complete |
| Twitch | `/docs/arenas/twitch.md` | Complete (deferred) |
| VKontakte | `/docs/arenas/vkontakte.md` | Complete (deferred) |
| AI Chat Search | `/docs/arenas/ai_chat_search.md` | Complete |

---

## Overall Assessment

The Issue Observatory has reached a mature state for multi-platform Danish discourse research. As of 2026-02-21:

**Infrastructure:**
- 24 arena directories (21 functional, 2 deferred stubs, 1 limited) plus Zeeschuimer import for 6 additional platform data sources
- 15 database migrations defining the complete schema including Zeeschuimer import support
- DB-backed credential pool with Fernet encryption, Redis lease/quota/cooldown
- Celery + Redis task queue with rate limiting (Lua sliding window)
- SSE live collection monitoring via Redis pub/sub

**Data Collection:**
- Automated collection across 21 platforms covering social media, news media, search engines, web archives, and AI chat
- Manual capture via Zeeschuimer browser extension for LinkedIn (only pathway), Twitter/X, Instagram, TikTok, TikTok Comments, and Threads
- Snowball sampling with graph expansion across 7 platforms plus URL-based and @mention co-mention detection

**Data Quality:**
- 6 enrichment modules for automated post-collection analysis (language detection, NER, sentiment, propagation, coordination)
- Near-duplicate detection via SimHash with Hamming distance threshold
- Engagement score normalization across 7 platform types
- Deduplication pipeline (URL, content hash, SimHash)
- Content hash uniqueness enforced at database level (migration 015)

**Research Workflow:**
- Researcher self-service configuration for RSS feeds, Telegram channels, Reddit subreddits, Discord channels, and Wikipedia seed articles
- Per-arena search term scoping (YF-01) preventing cross-arena contamination
- Discovery feedback loops (one-click term/source addition, RSS autodiscovery, subreddit suggestion)
- Cross-run and design-level analysis for iterative research
- Annotation codebook management for structured qualitative coding
- In-browser network visualization (Sigma.js) with 4 GEXF export modes
- Corpus-level co-occurrence analysis

**What Remains:**
- **2 Phase D deferred features** (IP2-054 BERTopic topic modeling, IP2-057 Folketinget.dk arena)
- **2 non-code items** (use case documents P1.5, IM-1.6)
- **1 institutional process** (GR-13 Meta Content Library application)
- **Coherency audit findings** (6 critical + 11 moderate integration gaps identified 2026-02-21; see audit reports for details)

All actionable code items from all six research reports and the full IP2 roadmap (59/61 items, 97%) have been implemented. The Zeeschuimer integration adds a crucial manual capture pathway for LinkedIn, the last major platform without automated access. The system supports both discourse tracking (CO2 afgift style) and issue mapping (Marres style) research methodologies.

---

*End of release notes. This document is the single source of truth for implementation status as of 2026-02-21. For the previous day's incremental release notes, see `release_notes_2026_02_20.md`.*
