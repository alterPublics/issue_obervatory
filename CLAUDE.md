# CLAUDE.md -- Issue Observatory Project Guide

**Last updated:** 2026-02-20

This file provides essential context for AI agents working on the Issue Observatory codebase. It reflects the actual state of the implementation as of the date above and supersedes any conflicting guidance in other documents.

---

## Project Identity

**The Issue Observatory** is a modular multi-platform media data collection and analysis application for media and communications research. It tracks mediated content around specific issues across diverse digital platforms (called "arenas") in a Danish context, with architecture designed for international expansion.

- **Repository:** `issue_observatory`
- **Python version:** 3.12+
- **Framework:** FastAPI + Jinja2 + HTMX 2 + Alpine.js 3
- **Database:** PostgreSQL 16+ with JSONB, partitioned content_records table
- **Task queue:** Celery + Redis
- **ORM:** SQLAlchemy 2.0 (async, declarative)

---

## Key Reference Documents

| Document | Path | Purpose |
|----------|------|---------|
| Implementation Plan (original) | `/IMPLEMENTATION_PLAN.md` | Original phased build plan, architecture, schema |
| Implementation Plan 2.0 Strategy | `/docs/research_reports/implementation_plan_2_0_strategy.md` | Unified improvement roadmap with 61 items (IP2-001 through IP2-061) |
| Agent definitions | `/AGENTS.md` | Agent roles and ownership boundaries |
| Agent system prompts | `/.claude/agents/` | Detailed agent instructions |
| Status files | `/docs/status/{agent}.md` | Per-agent implementation status |
| Arena briefs | `/docs/arenas/{platform}.md` | Research briefs for each arena (required before implementation) |
| Cross-platform research | `/reports/cross_platform_data_collection.md` | Platform API research |
| Danish context guide | `/reports/danish_context_guide.md` | GDPR, DSA, Danish media landscape |
| UX test reports | `/docs/ux_reports/` | Scenario-based evaluations |
| Research reports | `/docs/research_reports/` | Codebase evaluations and recommendations |

---

## Current Implementation Status

### Implemented Arenas (25 implementations)

| Arena | Directory | Status | Tiers | Notes |
|-------|-----------|--------|-------|-------|
| Google Search | `arenas/google_search/` | Fully implemented | MEDIUM, PREMIUM | Serper.dev (MEDIUM), SerpAPI (PREMIUM) |
| Google Autocomplete | `arenas/google_autocomplete/` | Fully implemented | MEDIUM, PREMIUM | Shares credentials with Google Search |
| Bluesky | `arenas/bluesky/` | Fully implemented | FREE | `lang:da` filter, WebSocket Jetstream |
| Reddit | `arenas/reddit/` | Fully implemented | FREE | asyncpraw, configurable subreddits (GR-03) |
| YouTube | `arenas/youtube/` | Fully implemented | FREE | Data API v3, RSS-first strategy |
| RSS Feeds | `arenas/rss_feeds/` | Fully implemented | FREE | 28+ Danish feeds, configurable custom feeds (GR-01) |
| GDELT | `arenas/gdelt/` | Fully implemented | FREE | `sourcelang:danish`, `sourcecountry:DA` |
| Telegram | `arenas/telegram/` | Fully implemented | FREE | MTProto via Telethon, configurable channels (GR-02) |
| TikTok | `arenas/tiktok/` | Fully implemented | FREE | FREE tier only (MEDIUM tier documented but not implemented), 10-day engagement lag |
| Via Ritzau | `arenas/ritzau_via/` | Fully implemented | FREE | Unauthenticated JSON API |
| Gab | `arenas/gab/` | Fully implemented | FREE | Mastodon-compatible API |
| Event Registry | `arenas/event_registry/` | Fully implemented | MEDIUM, PREMIUM | ISO 639-3 `"dan"` |
| X/Twitter | `arenas/x_twitter/` | Fully implemented | MEDIUM, PREMIUM | TwitterAPI.io (MEDIUM) |
| Facebook | `arenas/facebook/` | Fully implemented | MEDIUM, PREMIUM | Bright Data or MCL |
| Instagram | `arenas/instagram/` | Fully implemented | MEDIUM, PREMIUM | Bright Data |
| Threads | `arenas/threads/` | Fully implemented | FREE, MEDIUM | Unofficial API |
| Common Crawl | `arenas/web/common_crawl/` | Fully implemented | FREE | Index query + content fetch |
| Wayback Machine | `arenas/web/wayback/` | Fully implemented | FREE | Optional content fetching (GR-12) |
| URL Scraper | `arenas/web/url_scraper/` | Fully implemented | FREE, MEDIUM | Researcher-provided URL list |
| Wikipedia | `arenas/wikipedia/` | Implemented (limited) | FREE | Revision/pageview monitoring, seed articles (GR-04) |
| Discord | `arenas/discord/` | Implemented (limited) | FREE | Requires bot invitation per server, configurable channels (GR-04) |
| AI Chat Search | `arenas/ai_chat_search/` | Fully implemented | MEDIUM | OpenRouter, query expansion, citation extraction |
| Majestic | `arenas/majestic/` | Implemented (PREMIUM only) | PREMIUM | Backlink index, $400/month |
| Twitch | `arenas/twitch/` | Deferred stub | -- | Channel discovery only |
| VKontakte | `arenas/vkontakte/` | Deferred stub | -- | Pending legal review |

### Core Infrastructure (all implemented)

| Component | File(s) | Status |
|-----------|---------|--------|
| ArenaCollector ABC | `arenas/base.py` | Complete -- includes public_figure_ids bypass (GR-14) |
| Arena registry | `arenas/registry.py` | Complete -- keyed by platform_name, autodiscovery |
| Query builder (boolean) | `arenas/query_builder.py` | Complete -- AND/OR group logic (IP2-031) |
| Normalizer | `core/normalizer.py` | Complete -- SHA-256 pseudonymization with public figure bypass |
| Credential pool | `core/credential_pool.py` | Complete -- DB-backed, Fernet encryption, Redis lease/quota/cooldown |
| Rate limiter | `workers/rate_limiter.py` | Complete -- Redis sliding window Lua script |
| Credit service | `core/credit_service.py` | Complete -- balance, reservation, settlement, refund, estimation (SB-14) |
| Entity resolver | `core/entity_resolver.py` | Complete |
| Deduplication | `core/deduplication.py` | Complete -- URL, content hash, SimHash near-duplicate |
| Retention service | `core/retention_service.py` | Complete |
| Event bus (SSE) | `core/event_bus.py` | Complete -- Redis pub/sub for live collection monitoring |
| Email service | `core/email_service.py` | Complete -- no-op when SMTP not configured |

### Database Models and Migrations (12 migrations)

| Migration | Description |
|-----------|-------------|
| 001 | Initial schema: all core tables, indexes, content_records partitions |
| 002 | `arenas_config JSONB` on query_designs |
| 003 | `suspended_at` on collection_runs |
| 004 | Scraping jobs table |
| 005 | Content annotations table (IP2-043) |
| 006 | Search term groups: `group_id`, `group_label` on search_terms (IP2-046) |
| 007 | `simhash BIGINT` on content_records (IP2-032, near-duplicate detection) |
| 008 | Query design cloning: `parent_design_id` (IP2-051) |
| 009 | `public_figure BOOLEAN` on actors (GR-14) |
| 010 | `target_arenas JSONB` on search_terms (YF-01, per-arena term scoping) |
| 011 | GIN index on `search_terms.target_arenas` for YF-01 query performance |
| 012 | `codebook_entries` table (SB-16, annotation codebook management) |

### Analysis Module

| Component | File | Status |
|-----------|------|--------|
| Descriptive analytics | `analysis/descriptive.py` | Complete -- volume, top actors (with resolved names), top terms, temporal comparison (IP2-033), arena comparison (IP2-037) |
| Network analysis | `analysis/network.py` | Complete -- actor co-occurrence, term co-occurrence, bipartite, cross-platform actors |
| Export | `analysis/export.py` | Complete -- CSV, XLSX, NDJSON, Parquet, GEXF (3 types), RIS, BibTeX |
| Shared filter builder | `analysis/_filters.py` | Complete (IP2-024) |
| Propagation analysis | `analysis/propagation.py` | Complete (GR-08) -- cross-arena temporal propagation |
| Volume spike alerting | `analysis/alerting.py` | Complete (GR-09) -- threshold-based, 7-day rolling average |
| Link mining | `analysis/link_miner.py` | Complete (GR-22) -- URL extraction, platform classification |
| Coordination detection | `analysis/coordination.py` | Complete (GR-11) -- query functions for coordinated posting |

### Enrichment Pipeline (IP2-036 equivalent, implemented)

| Enricher | File | Status |
|----------|------|--------|
| Base class | `analysis/enrichments/base.py` | Complete -- `ContentEnricher` ABC, `EnrichmentError` |
| Language detection | `analysis/enrichments/language_detector.py` | Complete (IP2-008) -- langdetect with heuristic fallback |
| Named entity extraction | `analysis/enrichments/named_entity_extractor.py` | Complete (IP2-049) -- spaCy-based, optional `nlp-ner` extra |
| Propagation detection | `analysis/enrichments/propagation_detector.py` | Complete (GR-08) |
| Coordination detection | `analysis/enrichments/coordination_detector.py` | Complete (GR-11) |
| Danish sentiment analysis | `analysis/enrichments/sentiment_analyzer.py` | Complete (IP2-034) -- AFINN lexicon, optional `nlp` extra |

### Scraper Module (standalone)

| Component | File | Status |
|-----------|------|--------|
| HTTP fetcher | `scraper/http_fetcher.py` | Complete -- httpx-based |
| Playwright fetcher | `scraper/playwright_fetcher.py` | Complete -- JS-rendered pages |
| Content extractor | `scraper/content_extractor.py` | Complete -- trafilatura |
| Config | `scraper/config.py` | Complete |
| Tasks | `scraper/tasks.py` | Complete |
| Routes | `scraper/router.py` | Complete |

### Sampling Module

| Component | File | Status |
|-----------|------|--------|
| Snowball sampling | `sampling/snowball.py` | Complete |
| Network expansion | `sampling/network_expander.py` | Complete |
| Similarity finder | `sampling/similarity_finder.py` | Complete -- TF-IDF cosine (with scikit-learn) or Jaccard fallback |

### Frontend

All major templates are implemented:
- Dashboard, Query Design editor/list/detail, Collection launcher/list/detail (with SSE live monitoring)
- Content browser with slide-in detail panel, Discovered Sources page (GR-22)
- Actor directory with snowball sampling panel (B-01), entity resolution page
- Analysis dashboard with charts, network tabs, export panel, political calendar overlay (GR-16)
- Admin pages: credentials, health, users, credits
- Auth: login, password reset

### API Routes

| Route module | Path prefix | Key endpoints |
|-------------|------------|---------------|
| `routes/pages.py` | `/` | HTML page rendering |
| `routes/query_designs.py` | `/query-designs` | CRUD + arena config + clone |
| `routes/collections.py` | `/collections` | Launch, list, detail, SSE stream, suspend/resume |
| `routes/content.py` | `/content` | Browser, record detail, export, discovered links |
| `routes/actors.py` | `/actors` | CRUD, presences, quick-add, bulk-add, snowball |
| `routes/analysis.py` | `/analysis` | Descriptive stats, network data, filtered export, suggested terms |
| `routes/annotations.py` | `/annotations` | GET, POST, DELETE content annotations |
| `routes/codebooks.py` | `/codebooks` | Codebook CRUD (SB-16) |
| `routes/arenas.py` | `/api/arenas` | List registered arenas, health status |
| `routes/auth.py` | `/auth` | Login, register, password reset |
| `routes/credits.py` | `/admin/credits` | Credit allocation |
| `routes/health.py` | `/health` | Health check |
| `routes/imports.py` | `/imports` | Data import |
| `routes/users.py` | `/admin/users` | User management |

---

## Architecture Patterns (Established in Implementation)

### Arena Implementation Pattern

Every arena lives in `src/issue_observatory/arenas/{arena_name}/` and contains:
- `collector.py` -- subclass of `ArenaCollector`, decorated with `@register`
- `config.py` -- arena-specific configuration constants
- `tasks.py` -- Celery tasks wrapping collector calls
- `router.py` -- FastAPI router (optional per-arena endpoints)
- `__init__.py` -- empty or minimal

The `ArenaCollector` base class defines:
- `arena_name` (str) -- logical grouping label (e.g., `"social_media"`, `"news_media"`)
- `platform_name` (str) -- unique per-collector identifier (e.g., `"reddit"`, `"youtube"`)
- `supported_tiers` (list[Tier]) -- which tiers the collector supports
- `collect_by_terms()` -- keyword search collection (supports `term_groups` for boolean logic and `language_filter` for multi-language)
- `collect_by_actors()` -- actor-based collection
- `normalize()` -- raw API response to universal content record
- `get_tier_config()` -- tier-specific API configuration
- `set_public_figure_ids()` -- GR-14 pseudonymization bypass

**Registry design:** Keyed by `platform_name` (not `arena_name`). Multiple collectors can share the same `arena_name` grouping label without collision. Use `get_arena(platform_name)` for lookups, `list_arenas()` for full listing.

### Researcher-Configurable Source Lists (GR-01 through GR-04)

Arenas that depend on curated source lists support researcher customization via `arenas_config` JSONB on query_designs:
- `arenas_config["rss"]["custom_feeds"]` -- extra RSS feed URLs
- `arenas_config["telegram"]["custom_channels"]` -- extra Telegram channel usernames
- `arenas_config["reddit"]["custom_subreddits"]` -- extra subreddit names
- `arenas_config["discord"]["custom_channel_ids"]` -- Discord channel snowflake IDs
- `arenas_config["wikipedia"]["seed_articles"]` -- Wikipedia article titles
- `arenas_config["languages"]` -- multi-language list (overrides single `language` field)
- `arenas_config["wayback"]["fetch_content"]` -- boolean to enable content retrieval

These are persisted via `PATCH /query-designs/{design_id}/arena-config/{arena_name}`.

### Enrichment Pipeline Pattern

Enrichments are pluggable post-collection processors. Each enricher:
1. Subclasses `ContentEnricher` from `analysis/enrichments/base.py`
2. Defines `enricher_name` (string key)
3. Implements `is_applicable(record)` and `enrich(record)`
4. Writes output to `raw_metadata.enrichments.{enricher_name}` as JSONB

No schema migration is needed for new enrichers. Enrichments are triggered by the `enrich_collection_run` Celery task.

### Content Record Universal Schema

All collected data normalizes to `content_records` (range-partitioned by `published_at`, monthly boundaries). Platform-specific data goes in the `raw_metadata` JSONB column. Key fields:
- `id` (UUID), `published_at` (composite PK)
- `arena`, `platform`, `content_type`
- `title`, `text_content`, `url`, `platform_id`
- `author_display_name`, `author_platform_id`, `pseudonymized_author_id`
- `language`, `engagement_score`
- `content_hash` (SHA-256), `simhash` (BIGINT, near-duplicate fingerprint)
- `search_terms_matched` (JSONB array)
- `raw_metadata` (JSONB -- platform data, enrichments, duplicate_of markers)
- `author_id` (FK to actors for entity resolution)
- `collection_run_id` (FK to collection_runs)
- `collected_at` (timestamp -- note: content_records does NOT use TimestampMixin as records are immutable)

### Tier Precedence (IP2-022)

When resolving which tier to use for a collection run:
1. Per-arena tier in `CollectionRun.arenas_config` (highest priority)
2. Per-arena tier in the launcher request's `arenas_config`
3. Global default `CollectionRun.tier` field (lowest priority)

### SSE Live Collection Monitoring

Collection progress is streamed via SSE (`GET /collections/{run_id}/stream`):
- `event_bus.py` uses synchronous Redis pub/sub (callable from Celery workers)
- Frontend uses `hx-ext="sse"` with `sse-connect` and `sse-close="run_complete"`
- Keepalive every 30 seconds to prevent proxy timeout

---

## Coding Standards

### Python

- Python 3.12+, strict type hints on all function signatures
- `from __future__ import annotations` in all files
- Async everywhere possible (httpx, SQLAlchemy async, FastAPI)
- Pydantic v2 for all data validation and serialization
- Google-style docstrings on all public classes and functions
- No wildcard imports

### Naming

- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions/methods: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Arena names: `snake_case` (e.g., `google_search`, `x_twitter`, `rss_feeds`)
- Celery task names: dotted path matching module location

### Error Handling

- Custom exception hierarchy rooted in `IssueObservatoryError` (`core/exceptions.py`)
- Arena-specific exceptions: `ArenaCollectionError`, `ArenaRateLimitError`, `ArenaAuthError`
- Never swallow exceptions silently -- log at minimum
- All external API calls wrapped in try/except with specific error types
- Structured logging via structlog

### Linting and Formatting

- Ruff for linting (rules: E, W, F, I, B, C4, UP, ANN, TCH, RUF) and formatting
- Line length: 100
- Quote style: double
- Mypy strict mode with `pydantic.mypy` plugin
- Pre-commit hooks configured (`.pre-commit-config.yaml`)

### Testing

- pytest with `asyncio_mode = "auto"`
- `respx` for HTTP mocking (all arena collectors)
- Test fixtures in `tests/fixtures/api_responses/{arena_name}/`
- Test factories in `tests/factories/` (UserFactory, QueryDesignFactory, ContentRecordFactory)
- Test file naming: `test_{module_name}.py`
- Unit tests: `tests/unit/`
- Arena tests: `tests/arenas/`
- Integration tests: `tests/integration/`
- Coverage target: 80% for core/, 75% for arenas/

### UI Language

- All user-facing strings are in **English**. No Danish in templates, Alpine components, or JavaScript.
- `<html lang="en">` in base templates.
- Danish is only relevant as data/query parameters (locale settings, RSS URLs, language codes).

### Database

- SQLAlchemy 2.0 declarative style
- All tables have `created_at` and `updated_at` timestamps (via `TimestampMixin`), except `content_records` which uses `collected_at` only (records are immutable)
- Platform-specific data in `raw_metadata` JSONB -- no platform-specific columns on the universal schema
- UUIDs for all primary keys
- Alembic for all migrations -- never modify tables manually

---

## Danish Context

### Language and Locale Defaults

All arena collectors apply Danish locale defaults. Configuration is centralized in `src/issue_observatory/config/danish_defaults.py`:

| Arena | Danish Configuration |
|-------|---------------------|
| Google Search / Autocomplete | `gl=dk`, `hl=da` |
| YouTube | `relevanceLanguage=da`, `regionCode=DK` |
| Bluesky | `lang:da` search filter |
| GDELT | `sourcelang:danish`, `sourcecountry:DA` |
| Event Registry | ISO 639-3 `"dan"` |
| X/Twitter | `lang:da` search operator |
| Reddit | r/Denmark, r/danish, r/copenhagen, r/aarhus, r/dkpolitik (plus configurable) |
| Via Ritzau | `language=da` |
| RSS Feeds | 28+ curated Danish feeds (DR, TV2, Politiken, Berlingske, BT, etc.) |

Language stored as ISO 639-1 (`da`), country as ISO 3166-1 (`DK`).

### RSS Feed Sources (28+ feeds)

Major outlets: DR (all feeds), TV2, BT, Politiken, Berlingske, Ekstra Bladet, Information, Jyllands-Posten, Nordjyske, Borsen, Kristeligt Dagblad, Altinget (main + section feeds), education-sector feeds (Folkeskolen, Gymnasieskolen, KU, DTU, CBS).

### Excluded Sources

- **Infomedia** is explicitly excluded (institutional-subscription-only, not available for this project)
- **LinkedIn** has no automated collection path -- manual Zeeschuimer capture with NDJSON import is the only option

### Legal Compliance

- GDPR compliance: pseudonymization (SHA-256 with salt), data subject deletion (retention_service.py), purpose limitation (content linked to query_designs), configurable retention policies
- Public figure bypass (GR-14): `public_figure=True` on Actor records exempts from pseudonymization per GDPR Art. 89(1), with audit trail in `raw_metadata`
- LinkedIn scraping carries HIGH legal risk in EU (CNIL precedent)
- Content annotations support qualitative coding with stance vocabulary (positive, negative, neutral, contested, irrelevant)

---

## Implementation Plan 2.0 -- Progress Tracker

The authoritative improvement roadmap is at `/docs/research_reports/implementation_plan_2_0_strategy.md`. Items are organized into 4 phases (A through D). Below is the current implementation status of key items:

### Implemented (completed items)

| ID | Description | Status |
|----|-------------|--------|
| IP2-004 | Duplicate exclusion in analysis | Done -- `_filters.py` |
| IP2-005 | Extend flat export columns | Done |
| IP2-006 | Human-readable export headers | Done |
| IP2-008 | Client-side language detection | Done -- LanguageDetector enricher |
| IP2-009 | Add Altinget RSS feed | Done -- main + section feeds |
| IP2-024 | Consolidate analysis filter builders | Done -- `_filters.py` |
| IP2-025 | GEXF export uses network.py | Done |
| IP2-031 | Boolean query support | Done -- `query_builder.py`, `group_id`/`group_label` on SearchTerm |
| IP2-032 | Near-duplicate detection (SimHash) | Done -- migration 007, `compute_simhash` |
| IP2-036 | Enrichment pipeline architecture | Done -- `ContentEnricher` base class, 6 enrichers |
| IP2-043 | Content annotation layer | Done -- model, migration 005, routes, UI |
| IP2-046 | Term grouping in query design | Done -- migration 006 |
| IP2-048 | Platform attribute on bipartite GEXF | Done |
| IP2-049 | Named entity extraction | Done -- spaCy-based, optional dependency |
| IP2-051 | Query design cloning | Done -- migration 008 |
| IP2-056 | RIS/BibTeX export | Done |
| IP2-058 | Education-specific RSS feeds | Done |
| IP2-059 | Expand Reddit subreddits | Done |
| IP2-060 | Formalize actor_type values | Done -- ActorType enum |
| IP2-001 | Dynamic arena grid (populate from server registry) | Done -- Alpine.js `arenaConfigGrid` fetching from `/api/arenas/` |
| IP2-002 | Arena tier validation (disable unsupported tiers) | Done -- `supportedTiers.includes(t)` disables unsupported tiers |
| IP2-003 | Arena descriptions in config grid | Done -- `arena.description` shown in grid |
| IP2-007 | Actor synchronization (QD <-> Actor Directory) | Done -- creates/links Actor + ActorListMember |
| IP2-010 | Update stale "Phase 0" text on dashboard | Done -- no "Phase 0" in any user-facing template |
| IP2-030 | Engagement score normalization | Done -- platform-specific weights, log scaling, 0-100 score in `normalizer.py` |
| IP2-033 | Temporal volume comparison | Done -- `get_temporal_comparison()` in `descriptive.py`, week/month periods |
| IP2-034 | Danish sentiment analysis enrichment | Done -- AFINN lexicon, `SentimentAnalyzer` enricher, optional `nlp` extra |
| IP2-035 | Engagement metric refresh | Done -- `refresh_engagement()` on ArenaCollector, Celery task, API endpoint |
| IP2-037 | Arena-comparative analysis | Done -- `get_arena_comparison()` in `descriptive.py`, per-arena metrics |
| IP2-038 | Emergent term extraction (TF-IDF) | Done -- suggested terms API endpoint |
| IP2-039 | Unified actor ranking | Done -- `get_top_actors_unified()` in `descriptive.py` |
| IP2-040 | Bipartite network with extracted topics | Done -- `build_enhanced_bipartite_network()` in `network.py` |
| IP2-042 | In-browser network preview | Done -- `static/js/network_preview.js` + Sigma.js |
| IP2-044 | Temporal network snapshots | Done -- `get_temporal_network_snapshots()` in `network.py` |
| IP2-045 | Dynamic GEXF export (temporal attributes) | Done -- `export_temporal_gexf()` in `export.py` |
| IP2-047 | Per-arena GEXF export | Done -- arena filter in `export.py` and analysis routes |
| IP2-050 | Cross-arena flow analysis | Done -- propagation detection (GR-08) |
| IP2-055 | Filtered export from analysis results | Done -- analysis template + content browser |

### Greenland Roadmap Items (implemented)

| ID | Description | Status |
|----|-------------|--------|
| GR-01 | Researcher-configurable RSS feeds | Done |
| GR-02 | Researcher-configurable Telegram channels | Done |
| GR-03 | Researcher-configurable Reddit subreddits | Done |
| GR-04 | Discord channel IDs + Wikipedia seed articles | Done |
| GR-05 | Multi-language selector | Done |
| GR-08 | Cross-arena propagation detection | Done |
| GR-09 | Volume spike alerting | Done |
| GR-11 | Coordinated posting detection | Done |
| GR-12 | Wayback Machine content retrieval | Done |
| GR-14 | Public figure pseudonymization bypass | Done |
| GR-16 | Political calendar overlay | Done |
| GR-17 | Content browser quick-add actor | Done |
| GR-22 | Discovered sources panel | Done |
| GR-18 | Expose Similarity Finder in UI | Done -- `/actors/{id}/similarity-search` + `cross-platform-match` |
| GR-19 | Co-mention fallback in network expander | Done -- `_expand_via_comention()` in `network_expander.py` |
| GR-20 | Auto-create actors from snowball discoveries | Done -- `actors.py` route + `snowball.py` |
| GR-21 | Telegram forwarding chain expander | Done -- forwarding chain analysis in `network_expander.py` |

### Phase 3 Blocker Fixes (implemented)

| ID | Description | Status |
|----|-------------|--------|
| B-01 | Snowball sampling UI entry point | Done |
| B-02 | GEXF network type buttons | Done |
| B-03 | Live tracking schedule visibility | Done |

### Ytringsfrihed Report Items (implemented)

| ID | Description | Status |
|----|-------------|--------|
| YF-01 | Per-arena search term scoping | Done -- migrations 010 + 011 |
| YF-02 | Source-list arena configuration UI | Done (via GR-01 through GR-04) |
| YF-05 | Ad-hoc exploration mode | Done -- `explore/index.html`, dynamic arena list |
| YF-07 | Bulk actor import | Done -- bulk add in `actors.py` route + editor template |
| YF-08 | Arena overview page | Done -- `arenas/index.html`, tier-organized |
| YF-09 | Tier precedence explanation | Done -- launcher template, collections routes, base.py |
| YF-10 | Group label autocomplete | Done -- dynamic datalist in QD editor |
| YF-11 | Snowball platform transparency | Done -- actors template and route |
| YF-13 | Discovered sources cross-design view | Done -- scope toggle in discovered links page |
| YF-14 | Google Search free-tier guidance | Done -- amber badge on Google arenas |
| YF-16 | Actor platform presence inline add | Done -- inline form in QD editor |

### Socialt Bedrageri Report Items (all 16 implemented)

| ID | Description | Status |
|----|-------------|--------|
| SB-01 | One-click term addition from suggested terms | Done |
| SB-02 | One-click source addition from discovered links | Done |
| SB-03 | Post-collection discovery notification | Done |
| SB-04 | Arena temporal capability metadata | Done -- `TemporalMode` enum on ArenaCollector |
| SB-05 | Date range warning on collection launch | Done |
| SB-06 | Cross-run comparison endpoint | Done |
| SB-07 | Design-level analysis aggregation | Done |
| SB-08 | Promote to live tracking button | Done |
| SB-09 | RSS feed autodiscovery | Done -- `feed_discovery.py` |
| SB-10 | Reddit subreddit suggestion | Done |
| SB-11 | AI Chat Search as discovery accelerator | Done |
| SB-12 | Research lifecycle indicator | Done |
| SB-13 | Content source labeling (batch/live) | Done |
| SB-14 | Credit estimation implementation | Done -- real per-arena values |
| SB-15 | Enrichment results dashboard tab | Done |
| SB-16 | Annotation codebook management | Done -- migration 012, CRUD routes |

### Not Yet Implemented (key remaining items)

| ID | Description | Phase | Notes |
|----|-------------|-------|-------|
| IP2-011--029 | 15 Phase A frontend polish items | A | Label changes, tooltips, dropdowns, timezone display (~5-8 person-days total) |
| IP2-041 | Entity resolution UI (full researcher-facing) | C | Backend exists; UI partial |
| IP2-052 | Multilingual query design | D | GR-05 multi-language selector partially covers |
| IP2-054 | Topic modeling (BERTopic) | D | Requires GPU, heavy dependencies |
| IP2-057 | Folketinget.dk arena | D | Arena brief required |
| IP2-061 | Mixed hash/name resolution in charts | D | Low priority |
| YF-12 | RSS feed preview | -- | Low priority polish |

For the full item-by-item tracker (61 IP2 items + all 6 reports), see `/docs/release_notes/release_notes_2026_02_20.md`.

---

## Git and Workflow

### Branch Strategy

- `main` -- stable, tested, deployable
- `develop` -- integration branch
- `feature/{arena-name}` or `feature/{module-name}` -- feature branches

### Commit Messages

Format: `{scope}: {description}`
Scopes: `core`, `arena/{name}`, `analysis`, `sampling`, `infra`, `docs`, `tests`
Examples: `core: add query design CRUD endpoints`, `arena/bluesky: implement keyword search collector`

### Agent Coordination

Five agent roles are defined in `/AGENTS.md` and `/.claude/agents/`:
1. **Core Application Engineer** (`core/`) -- FastAPI, Celery, arena collectors
2. **DB & Data Engineer** (`db/`) -- Schema, models, migrations, analysis
3. **Frontend Engineer** (`frontend/`) -- Templates, HTMX, Alpine.js, CSS
4. **QA Guardian** (`qa/`) -- Tests, CI/CD, code review
5. **Research Strategist** (`research/`) -- Arena briefs, knowledge base, ADRs

Key rule: Arena implementation requires a completed research brief at `/docs/arenas/{platform}.md` before engineering work begins.

---

## Running the Project

### Prerequisites

- Python 3.12+
- PostgreSQL 16+
- Redis 7+
- Docker and Docker Compose (for full stack)

### Quick Start

```bash
# Create virtual environment
python -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Start infrastructure
docker-compose up -d postgres redis

# Run migrations
alembic upgrade head

# Bootstrap admin user
python scripts/bootstrap_admin.py

# Start FastAPI
uvicorn issue_observatory.api.main:app --reload

# Start Celery worker (separate terminal)
celery -A issue_observatory.workers.celery_app worker -l info

# Start Celery beat (separate terminal)
celery -A issue_observatory.workers.celery_app beat -l info
```

### Running Tests

```bash
# All tests
pytest

# Unit tests only
pytest tests/unit/

# Arena tests only
pytest tests/arenas/

# Specific arena
pytest tests/arenas/test_bluesky.py

# Skip integration tests
pytest -m "not integration"
```

### Environment Variables

See `.env.example` for all required environment variables. Key ones:
- `DATABASE_URL` -- PostgreSQL connection string
- `REDIS_URL` -- Redis connection string
- `PSEUDONYMIZATION_SALT` -- Required for GDPR-compliant author pseudonymization
- `JWT_SECRET_KEY` -- Auth token signing

---

## Optional Dependencies

| Extra | Package | Purpose |
|-------|---------|---------|
| `ml` | scikit-learn | Content similarity scoring in SimilarityFinder |
| `nlp` | langdetect, afinn | Language detection enricher, Danish sentiment analysis enricher |
| `nlp-ner` | spaCy | Named entity extraction (also requires `python -m spacy download da_core_news_lg`) |
