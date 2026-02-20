# Issue Observatory -- Release Notes 2026-02-20

**Author:** Research & Knowledge Agent (The Strategist)
**Date:** 2026-02-20
**Scope:** Comprehensive implementation status across all six research recommendation reports and the Implementation Plan 2.0 roadmap. This document is the single source of truth for what has been built, what remains, and where each recommendation stands.

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-20 | Initial release notes. Cross-referenced 127 recommendation IDs across 6 reports against actual implementations. |
| 2026-02-20 (afternoon) | Implemented SB-01 through SB-16 (16 items). Migration 012 added. |
| 2026-02-20 (evening) | Implemented 11 remaining items: IP2-030, IP2-033, IP2-034, IP2-035, IP2-037, YF-05, YF-10, YF-13, YF-14, YF-16. Corrected 20+ items from stale status files that were already in the codebase. |
| 2026-02-20 (final) | Complete rewrite of release notes. Full codebase audit against all 6 reports plus IP2-001 through IP2-061. Verified every claim against actual file existence, grep matches, and route definitions. Added comprehensive IP2 full item tracker (61 items). |
| 2026-02-20 (late) | Completed all Phase A frontend polish items (IP2-011--IP2-029). Implemented IP2-052 (multilingual query design with bilingual term pairing, migration 013). Implemented IP2-061 (resolved actor names in network charts). Confirmed IP2-041 and YF-12 already fully implemented. Fixed pre-existing bug in _task_helpers.py (QA-001/QA-002). |

---

## Executive Summary

Six research recommendation reports were produced between 2026-02-17 and 2026-02-20. Together they contain **157 recommendation IDs** (with significant cross-report overlap reducing to approximately **97 unique items**). As of 2026-02-20 final audit:

| Report | Total IDs | Implemented | Non-code / Deferred | Remaining Code | Rate |
|--------|-----------|-------------|---------------------|----------------|------|
| CO2 Afgift (P1.1--P4.5) | 20 | 18 | 2 (P1.5 research artifact, P3.5/P3.6 Phase D) | 0 | 100% of actionable |
| AI og Uddannelse (IM-1.1--IM-4.5) | 22 | 21 | 1 (IM-1.6 research artifact) | 0 | 100% of actionable |
| Greenland (GR-01--GR-22) | 22 | 20 | 2 (GR-13 institutional, GR-15 Phase D) | 0 | 100% of actionable |
| Ytringsfrihed (YF-01--YF-16) | 16 | 16 | 0 | 0 | 100% |
| Socialt Bedrageri (SB-01--SB-16) | 16 | 16 | 0 | 0 | 100% |
| Implementation Plan 2.0 (IP2-001--IP2-061) | 61 | 59 | 2 (IP2-054, IP2-057 Phase D) | 0 | 97% |
| **Unique items (deduplicated)** | **~97** | **~94** | **~4** | **0** | **~97%** |

All actionable code items across all six reports are now implemented. Two items remain deferred to Phase D (IP2-054 BERTopic topic modeling requiring GPU, IP2-057 Folketinget.dk arena requiring research brief). Two non-code items (use case documents P1.5, IM-1.6) and one institutional process (GR-13 Meta Content Library application) are the only outstanding work.

### Key Capabilities Delivered

- **24 arena directories** (21 functional, 2 deferred stubs, 1 limited)
- **13 database migrations** defining the complete schema
- **6 enrichment modules** (language detection, named entity extraction, propagation detection, coordination detection, sentiment analysis, plus the ContentEnricher base class)
- **Researcher self-service mechanisms** for RSS feeds, Telegram channels, Reddit subreddits, Discord channels, Wikipedia seed articles, and per-arena search term scoping
- **Discovery feedback loops** with one-click term addition, source addition, and RSS feed/subreddit autodiscovery
- **Cross-run and design-level analysis** supporting iterative research workflows
- **In-browser network visualization** (Sigma.js) with temporal, per-arena, and dynamic GEXF export
- **Annotation codebook management** for structured qualitative coding
- **Danish sentiment analysis** using AFINN lexicon
- **Credit estimation** returning real per-arena cost projections

---

## What's New: Socialt Bedrageri Implementations (SB-01 through SB-16, 2026-02-20)

All 16 recommendations from the "socialt bedrageri" (social benefits fraud) codebase evaluation have been implemented. These span three architectural layers.

### Discovery Feedback Loop (SB-01, SB-02, SB-03)

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| SB-01 | One-click term addition from suggested terms | HTMX "Add" button per suggested term on the analysis dashboard. Posts to `POST /query-designs/{design_id}/terms` with `group_label: "auto_discovered"`. Button shows "Added" state and disables after success. Terms already in the design are pre-marked. |
| SB-02 | One-click source addition from discovered links | Per-link "Add to [arena] config" buttons on the Discovered Sources page. Calls `PATCH /query-designs/{design_id}/arena-config/{arena_name}` to append identifiers to custom lists. Scoped to a specific query design. |
| SB-03 | Post-collection discovery notification | After collection and enrichment, the collection detail page summarizes discovery potential: suggested new terms count, cross-platform discovered links count with platform breakdown. Links to the analysis dashboard and discovered-links page. |

### Temporal Capability Transparency (SB-04, SB-05)

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| SB-04 | Arena temporal capability metadata | New `temporal_mode` class attribute on `ArenaCollector` (via `TemporalMode` enum at `base.py` line 56) with values `"historical"`, `"recent"`, `"forward_only"`, `"mixed"`. All 21 functional collectors declare their mode. Included in arena registry metadata and `GET /api/arenas/` response. Arena grid and collection launcher display temporal badges. |
| SB-05 | Date range warning on collection launch | When creating a batch collection run with date parameters, the system checks enabled arenas' `temporal_mode`. Non-historical arenas generate a warning message displayed on the launcher template. |

### Iterative Workflow Support (SB-06, SB-07, SB-08)

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| SB-06 | Cross-run comparison endpoint | `GET /analysis/compare?run_ids=id1,id2` returns volume delta per arena, new actors, new terms, and content overlap percentage. Reuses existing descriptive analysis functions with a diff layer. |
| SB-07 | Design-level analysis aggregation | New endpoints: `GET /analysis/design/{design_id}/summary`, `/volume`, `/actors`, `/terms`, plus network endpoints (`/network/actors`, `/network/terms`, `/network/bipartite`). Aggregates across all completed runs for a query design. Run selector allows toggling individual runs. |
| SB-08 | "Promote to live tracking" button | On the query design detail page, when at least one completed batch run exists, a "Start Live Tracking" button opens a confirmation dialog and calls `POST /collections/` with live mode. |

### Source Discovery Assistance (SB-09, SB-10, SB-11)

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| SB-09 | RSS feed autodiscovery | New `arenas/rss_feeds/feed_discovery.py` module. `POST /query-designs/{design_id}/discover-feeds` accepts a website URL, parses `<link rel="alternate">` tags, probes common feed paths, and returns discovered feeds for one-click addition. New dependency: `beautifulsoup4>=4.12`. ADR-012 documents the design. |
| SB-10 | Reddit subreddit suggestion | Subreddit suggestion logic in `api/routes/query_designs.py`. `GET /query-designs/{design_id}/suggest-subreddits` uses Reddit's `/subreddits/search` API with the design's search terms. Returns subreddit metadata for one-click addition to `arenas_config["reddit"]["custom_subreddits"]`. FREE-tier call. |
| SB-11 | AI Chat Search as discovery accelerator | AI Chat Search arena repositioned in the UI as a discovery tool with a dedicated "AI Discovery" button on the query design page. |

### Workflow Transition and Cost Transparency (SB-12, SB-13, SB-14)

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| SB-12 | Research lifecycle indicator | Query design detail page shows current stage (Design / Exploring / Tracking / Paused), derived from existing collection run data. Horizontal stepper display. |
| SB-13 | Content source labeling (batch/live) | Content browser filter dropdown for "Collection mode: All / Batch / Live". Badge per content card distinguishes exploratory from tracking data. |
| SB-14 | Credit estimation implementation | `CreditService.estimate()` in `core/credit_service.py` now returns real per-arena credit estimates based on term count, date range, tier, and each collector's `estimate_credits()` method. Replaces previous zero-return stub. |

### Analysis and Annotation Enhancements (SB-15, SB-16)

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| SB-15 | Enrichment results dashboard tab | New "Enrichments" tab on the analysis dashboard. Four new analysis functions in `descriptive.py`: `get_language_distribution()`, `get_top_named_entities()`, `get_propagation_patterns()`, `get_coordination_signals()`. Four new API endpoints under `/analysis/{run_id}/enrichments/`. |
| SB-16 | Annotation codebook management | New `CodebookEntry` model (`core/models/codebook.py`). Migration 012 creates `codebook_entries` table. CRUD API at `/codebooks/`. Full frontend UI at `annotations/codebook_manager.html`. Supports query-design-scoped and global codebooks. Integrates with the content annotation panel as a dropdown for structured coding. |

### Migration Required

**Migration 012** (`012_add_codebook_entries`) must be run to support the SB-16 annotation codebook feature:

```bash
alembic upgrade head
```

This migration creates the `codebook_entries` table with columns: `id` (UUID PK), `query_design_id` (nullable FK), `code` (VARCHAR), `label` (VARCHAR), `description` (TEXT), `created_at`, `updated_at`. Unique constraint on `(query_design_id, code)`.

---

## What's New: Evening Batch Implementations (2026-02-20 evening)

### Analysis Features

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| IP2-030 | Engagement score normalization | `compute_normalized_engagement()` in `core/normalizer.py` (line 448). Platform-specific weights (Reddit, YouTube, Bluesky, X/Twitter, Facebook, Instagram, TikTok) with log scaling to 0--100 range. Automatically applied during `normalize()`. |
| IP2-033 | Temporal volume comparison | `get_temporal_comparison()` in `analysis/descriptive.py` (line 894). Period-over-period analysis (week/month) with per-arena breakdown, delta counts, and percentage changes. API: `GET /analysis/{run_id}/temporal-comparison?period=week|month`. |
| IP2-037 | Arena-comparative analysis | `get_arena_comparison()` in `analysis/descriptive.py` (line 1096). Per-arena metrics: record_count, unique_actors, unique_terms, avg_engagement, date range. API: `GET /analysis/{run_id}/arena-comparison`. |

### Enrichment Features

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| IP2-034 | Danish sentiment analysis enrichment | `SentimentAnalyzer` enricher in `analysis/enrichments/sentiment_analyzer.py`. Uses AFINN lexicon (Danish wordlist built-in). Stores `{score, raw_score, label}` in `raw_metadata.enrichments.sentiment`. Score normalized to [-1, 1] via tanh. Labels: positive (>0.1), negative (<-0.1), neutral. Optional `afinn` dependency added to `[nlp]` extra in `pyproject.toml` (line 79). |
| IP2-035 | Engagement metric refresh | Optional `refresh_engagement()` method on `ArenaCollector` base class (line 334). Celery task `refresh_engagement_metrics` in `workers/maintenance_tasks.py` (line 265) processes records in batches of 50 per platform. API: `POST /collections/{run_id}/refresh-engagement` (202 Accepted, async). Rate limited to 5 requests/minute. |

### Frontend Features

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| YF-05 | Ad-hoc exploration mode (dynamic) | Explore page (`explore/index.html`) now fetches arenas dynamically from `/api/arenas/` via `loadArenas()`, filtering to FREE tier only. Responsive grid layout with `availableArenas` Alpine.js data and arena descriptions. |
| YF-10 | Group label autocomplete | `_updateDatalist()` in QD editor collects unique group labels from existing term rows and merges with hardcoded defaults in `<datalist>`. |
| YF-13 | Discovered sources cross-design view | Scope toggle ("This Design" / "All My Designs") added to `content/discovered_links.html` (line 164). Backend already supports user-scope mode when `query_design_id` is omitted. |
| YF-14 | Google Search free-tier guidance | Amber info badge on Google Search and Google Autocomplete rows in QD editor arena grid: "Requires MEDIUM+ tier" with tooltip. |
| YF-16 | Actor platform presence inline add | Expandable inline form in QD editor actor rows. Platform dropdown + username input, HTMX POST to `/actors/{actor_id}/presences`. Auto-collapses on success. |

---

## What's New: Late Batch Implementations (2026-02-20 late)

### Phase A Frontend Polish (IP2-011 through IP2-029, all 17 items)

All 17 Phase A frontend polish items have been completed. Most were found to already be implemented during audit; the following 5 items required new implementation:

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| IP2-013 | Chart axis labels | Y-axis "Number of records" labels added to analysis dashboard Chart.js configuration. |
| IP2-015 | Term type help text (tooltips) | Tooltips on Keyword, Phrase, and Hashtag options in the term type dropdown in the QD editor. |
| IP2-017 | Admin credential form missing platforms | Gab, Threads, Bright Data, and SerpAPI added to the platform dropdown in `admin/credentials.html`. |
| IP2-019 | Replace "Celery Beat" jargon | Developer terminology replaced with researcher-friendly "Scheduled collection" throughout templates. |
| IP2-021 | Timestamp timezone display | UTC timezone labels appended to all displayed timestamps in templates. |

The remaining 12 items (IP2-011, IP2-012, IP2-014, IP2-016, IP2-018, IP2-020, IP2-022, IP2-023, IP2-026, IP2-027, IP2-028, IP2-029) were confirmed as already implemented during the audit.

### Multilingual Query Design (IP2-052)

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| IP2-052 | Multilingual query design | Migration 013 adds `translations JSONB` column to `search_terms` table. Bilingual term pairing stores per-language translations keyed by ISO 639-1 code (e.g., `{"en": "climate tax", "da": "CO2 afgift"}`). Query builder integration automatically expands terms with their translations during collection. Frontend UI adds collapsible per-term translation input rows in the QD editor. Fully implements the IM-4.2 bilingual term pairing requirement. |

### Resolved Actor Names in Charts (IP2-061)

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| IP2-061 | Mixed hash/name resolution in charts | Network analysis functions in `analysis/network.py` now use LEFT JOIN on `actors` table with COALESCE to prefer resolved actor display names over pseudonymized hash identifiers. Applies to actor co-occurrence, bipartite, and cross-platform actor networks. |

### Audit Confirmations (IP2-041, YF-12)

| ID | Description | Details |
|----|-------------|---------|
| IP2-041 | Entity resolution UI | Full researcher-facing UI confirmed as already implemented: entity resolution page supports triggering, monitoring, and reviewing resolution results. Previously listed as "Partial" in error. |
| YF-12 | RSS feed preview | Feed list search/preview widget confirmed as already implemented. Previously listed as "Not done" in error. |

### Bug Fix (QA-001/QA-002)

Pre-existing bug fixed in `src/issue_observatory/workers/_task_helpers.py`. Details tracked under QA-001 and QA-002.

### Migration Required

**Migration 013** (`013_add_search_term_translations`) must be run to support the IP2-052 multilingual query design feature:

```bash
alembic upgrade head
```

This migration adds a nullable `translations JSONB` column to the `search_terms` table. Non-breaking: existing rows default to NULL.

---

## What's New: Audit Corrections (items confirmed as already implemented)

The following items were listed as "Not Yet Implemented" in stale status files but were found to already exist in the codebase during the final audit. No new code was written for these; the correction is to the tracking documents only.

| ID | Description | Evidence (file or function) |
|----|-------------|----------|
| IP2-001 | Dynamic arena grid | QD editor uses Alpine.js `arenaConfigGrid` fetching from `/api/arenas/` |
| IP2-002 | Arena tier validation | `supportedTiers.includes(t)` disables unsupported tier radio buttons in QD editor |
| IP2-003 | Arena descriptions in config grid | `arena.description` rendered in grid cells |
| IP2-007 | Actor synchronization (QD to Actor Directory) | Creates/links Actor + ActorListMember from QD editor |
| IP2-010 | Phase 0 text removed | No "Phase 0" string in any user-facing template |
| IP2-038 | Emergent term extraction | TF-IDF implementation; `GET /analysis/{run_id}/emergent-terms` route exists |
| IP2-039 | Unified actor ranking | `get_top_actors_unified()` in `descriptive.py` (line 591) |
| IP2-040 | Enhanced bipartite network | `build_enhanced_bipartite_network()` in `network.py` (line 972) |
| IP2-042 | In-browser network preview | `api/static/js/network_preview.js` + Sigma.js integration |
| IP2-044 | Temporal network snapshots | Weekly/monthly network evolution with change detection |
| IP2-045 | Dynamic GEXF export | `export_temporal_gexf()` in `export.py` (line 1032) with dynamic mode and spells |
| IP2-047 | Per-arena GEXF | Arena filter parameter in `export.py` and analysis routes |
| IP2-050 | Cross-arena flow analysis | `analysis/propagation.py` + `PropagationDetector` enricher |
| IP2-053 | Query term suggestion | Suggested terms API endpoint at `/analysis/{run_id}/emergent-terms` |
| IP2-055 | Filtered export | Analysis template + content browser + routes support filtered export |
| YF-07 | Bulk actor import | Bulk add in `actors.py` route + editor template |
| YF-08 | Arena overview page | `arenas/index.html` -- dynamic, tier-organized |
| YF-09 | Tier precedence explanation | Launcher template, collections routes, `base.py` |
| YF-11 | Snowball platform transparency | Actors template and route |
| GR-18 | Similarity Finder in UI | `/actors/{id}/similarity-search` + `cross-platform-match` |
| GR-19 | Co-mention fallback | `_expand_via_comention()` in `network_expander.py` |
| GR-20 | Auto-create actors from snowball | `actors.py` route + `snowball.py` |
| GR-21 | Telegram forwarding chain | Forwarding chain analysis in `network_expander.py` |

---

## Per-Report Status: CO2 Afgift (P1.1--P4.5)

**Report date:** 2026-02-17
**Report path:** `/docs/research_reports/co2_afgift_codebase_recommendations.md`

| ID | Description | Status | Implemented Via |
|----|-------------|--------|-----------------|
| P1.1 | Add Altinget RSS feed | Done | IP2-009. Main feed + uddannelse and klima section feeds added. |
| P1.2 | Duplicate exclusion in analysis queries | Done | IP2-004. `_filters.py` shared filter builder excludes `duplicate_of IS NOT NULL`. |
| P1.3 | Extend flat export columns | Done | IP2-005. Added `pseudonymized_author_id`, `content_hash`, `collection_run_id`, `query_design_name`. |
| P1.4 | Verify B-02 end-to-end | Done | B-02 fix. GEXF download buttons now include correct `network_type` parameter. |
| P1.5 | Create CO2 afgift use case document | N/A | Research artifact, not codebase implementation. |
| P2.1 | Client-side Danish language detection | Done | IP2-008. `LanguageDetector` enricher with `langdetect` + Danish heuristic fallback. |
| P2.2 | Engagement score normalization | Done | IP2-030. Platform-specific weights with log scaling in `normalizer.py`. |
| P2.3 | Boolean query support | Done | IP2-031. `group_id`/`group_label` on SearchTerm; `query_builder.py` with AND/OR group logic. |
| P2.4 | Near-duplicate detection (SimHash) | Done | IP2-032. SimHash 64-bit in `deduplication.py`, migration 007, Hamming distance threshold 3. |
| P2.5 | Temporal volume comparison | Done | IP2-033. `get_temporal_comparison()` with week/month periods. |
| P2.6 | Populate engagement_score | Done | Same as P2.2 / IP2-030. |
| P3.1 | Danish sentiment analysis enrichment | Done | IP2-034. `SentimentAnalyzer` enricher using AFINN Danish lexicon. |
| P3.2 | Emergent term extraction | Done | IP2-038. TF-IDF extraction. Suggested terms API endpoint available. |
| P3.3 | Temporal network snapshots | Done | IP2-044. Weekly/monthly network evolution with change detection. |
| P3.4 | Cross-arena narrative flow analysis | Done | GR-08 / IP2-050. Propagation detection enricher + `analysis/propagation.py`. |
| P3.5 | Topic modeling (BERTopic) | Deferred | IP2-054. Phase D. Requires GPU and heavy dependencies. |
| P3.6 | Folketinget.dk arena | Deferred | IP2-057. Arena brief not yet written. |
| P4.1 | Query design cloning | Done | IP2-051. Migration 008, `parent_design_id`. |
| P4.2 | Content annotation layer | Done | IP2-043. Migration 005, model, routes, UI. |
| P4.3 | In-browser network visualization | Done | IP2-042. Sigma.js integration with `network_preview.js`. |
| P4.4 | RIS/BibTeX export | Done | IP2-056. Both formats available in export module. |
| P4.5 | Filtered export from analysis results | Done | IP2-055. Available in analysis template and content browser. |

**Result: 18/20 code items implemented (100% of actionable). P1.5 is a research artifact. P3.5 and P3.6 are deferred to Phase D.**

---

## Per-Report Status: AI og Uddannelse (IM-1.1--IM-4.5)

**Report date:** 2026-02-18
**Report path:** `/docs/research_reports/ai_uddannelse_codebase_recommendations.md`

| ID | Description | Status | Implemented Via |
|----|-------------|--------|-----------------|
| IM-1.1 | Verify and fix B-02 (GEXF exports) | Done | B-02 fix. All three GEXF types produce correct output. |
| IM-1.2 | Add Altinget RSS feed | Done | IP2-009. |
| IM-1.3 | Add education-specific RSS feeds | Done | IP2-058. Folkeskolen, Gymnasieskolen, KU, DTU, CBS. |
| IM-1.4 | Duplicate exclusion in analysis | Done | IP2-004. |
| IM-1.5 | Extend flat export columns | Done | IP2-005. |
| IM-1.6 | Create AI og uddannelse use case document | N/A | Research artifact. |
| IM-2.1 | Emergent term extraction | Done | IP2-038. TF-IDF on collected text. |
| IM-2.2 | Unified actor ranking | Done | IP2-039. `get_top_actors_unified()` in `descriptive.py`. |
| IM-2.3 | Bipartite network with extracted topics | Done | IP2-040. `build_enhanced_bipartite_network()` in `network.py`. |
| IM-2.4 | Client-side Danish language detection | Done | IP2-008. |
| IM-2.5 | Content annotation layer | Done | IP2-043. |
| IM-3.1 | Temporal network snapshots | Done | IP2-044. |
| IM-3.2 | Dynamic GEXF export | Done | IP2-045. `export_temporal_gexf()` with dynamic mode and spells. |
| IM-3.3 | Cross-arena flow analysis | Done | GR-08 / IP2-050. Propagation detection enricher. |
| IM-3.4 | Boolean query support | Done | IP2-031. |
| IM-3.5 | Named entity extraction | Done | IP2-049. spaCy-based, optional `nlp-ner` extra. |
| IM-3.6 | Actor type enumeration | Done | IP2-060. `ActorType` enum with 11 categories. |
| IM-4.1 | Query design cloning | Done | IP2-051. |
| IM-4.2 | Bilingual term pairing | Done | IP2-052. Migration 013 adds `translations JSONB` to search_terms. Bilingual term pairing with query builder integration. Frontend UI with collapsible per-term translation inputs. |
| IM-4.3 | In-browser network visualization | Done | IP2-042. Sigma.js integration with `network_preview.js`. |
| IM-4.4 | Filtered export from analysis results | Done | IP2-055. Available in analysis template and content browser. |
| IM-4.5 | Query term suggestion from collected data | Done | IP2-053 / IP2-038. Suggested terms endpoint returns novel terms from collected content. |

**Result: 21/22 code items implemented (100% of actionable). IM-1.6 is a research artifact.**

---

## Per-Report Status: Greenland (GR-01--GR-22)

**Report date:** 2026-02-18
**Report path:** `/docs/research_reports/greenland_codebase_recommendations.md`

| ID | Description | Status | Implemented Via |
|----|-------------|--------|-----------------|
| GR-01 | Researcher-configurable RSS feeds | Done | `arenas_config["rss"]["custom_feeds"]`. Backend + frontend panel. |
| GR-02 | Researcher-configurable Telegram channels | Done | `arenas_config["telegram"]["custom_channels"]`. Backend + frontend panel. |
| GR-03 | Researcher-configurable Reddit subreddits | Done | `arenas_config["reddit"]["custom_subreddits"]`. Backend + frontend panel. |
| GR-04 | Discord channel IDs + Wikipedia seed articles | Done | `arenas_config["discord"]["custom_channel_ids"]` and `arenas_config["wikipedia"]["seed_articles"]`. |
| GR-05 | Multi-language selector per query design | Done | `arenas_config["languages"]` array. Frontend toggle-button multi-select for 7 languages. |
| GR-06 | Missing platforms in credentials dropdown | Done | Discord, Twitch, OpenRouter added to `admin/credentials.html`. |
| GR-07 | Generalize language detection enricher | Done | `LanguageDetector` (renamed from `DanishLanguageDetector`), `langdetect` with heuristic fallback. |
| GR-08 | Cross-arena temporal propagation detection | Done | `PropagationDetector` enricher in `analysis/enrichments/propagation_detector.py`. Stores in `raw_metadata.enrichments.propagation`. Companion `analysis/propagation.py` for query functions. |
| GR-09 | Volume spike alerting | Done | `analysis/alerting.py`. Threshold-based (2x 7-day rolling average). |
| GR-10 | URL scraper arena | Done | `arenas/web/url_scraper/`. FREE and MEDIUM tiers. Researcher-provided URL list via `arenas_config["url_scraper"]["custom_urls"]`. |
| GR-11 | Coordinated posting detection | Done | `CoordinationDetector` enricher. Sliding-window algorithm, 1-hour windows, 5+ distinct author threshold. `analysis/coordination.py` query functions. |
| GR-12 | Wayback Machine content retrieval | Done | Optional `fetch_content` parameter. Trafilatura text extraction. Per-tier caps. Configurable via `arenas_config["wayback"]["fetch_content"]`. |
| GR-13 | Apply for Meta Content Library | N/A | Institutional process, not code. Standing recommendation. 2--6 month review cycle. |
| GR-14 | Public figure pseudonymization bypass | Done | `public_figure` boolean on Actor (migration 009). Normalizer bypass with audit trail. `ArenaCollector.set_public_figure_ids()`. |
| GR-15 | Narrative topic modeling (BERTopic) | Deferred | IP2-054. Phase D. Same as P3.5. |
| GR-16 | Political calendar overlay | Done | `static/data/political_calendar.json` (12 events). Chart.js annotation plugin. Category/country filters. |
| GR-17 | Content Browser quick-add actor | Done | `POST /actors/quick-add`, `POST /actors/quick-add-bulk`. Frontend modal on author click in Content Browser. |
| GR-18 | Expose Similarity Finder in UI | Done | API at `/actors/{id}/similarity-search` + `cross-platform-match`. |
| GR-19 | Co-mention fallback in network expander | Done | `_expand_via_comention()` fully implemented in `network_expander.py`. |
| GR-20 | Auto-create Actor records for snowball discoveries | Done | Auto-creation in `actors.py` route + `snowball.py`. |
| GR-21 | Telegram forwarding chain expander | Done | Forwarding chain analysis in `network_expander.py`. |
| GR-22 | Cross-platform link mining | Done | `analysis/link_miner.py` with regex URL extraction, platform classification. `GET /content/discovered-links` endpoint. Frontend Discovered Sources page. |

**Result: 20/22 code items implemented (100% of actionable). GR-13 is institutional process. GR-15 is deferred to Phase D.**

---

## Per-Report Status: Ytringsfrihed (YF-01--YF-16)

**Report date:** 2026-02-19
**Report path:** `/docs/research_reports/ytringsfrihed_codebase_recommendations.md`

| ID | Description | Status | Notes |
|----|-------------|--------|-------|
| YF-01 | Per-arena search term scoping | Done | Migrations 010 + 011. `target_arenas JSONB NULL` on `search_terms` with GIN index. Task dispatch filtering implemented. |
| YF-02 | Source-list arena configuration UI | Done (via GR-01--GR-04) | The generic per-arena custom config mechanism requested by YF-02 was built as GR-01 through GR-04 (RSS, Telegram, Reddit, Discord, Wikipedia panels in query design editor). |
| YF-03 | Bulk search term import | Done | Bulk term import implemented. |
| YF-04 | Pre-flight credit estimation | Done (via SB-14) | `CreditService.estimate()` now returns real per-arena values. |
| YF-05 | Ad-hoc exploration mode | Done | `explore/index.html` with dynamic arena list from `/api/arenas/` via `loadArenas()`. |
| YF-06 | Cross-run analysis aggregation | Done (via SB-07) | Design-level analysis endpoints implemented. |
| YF-07 | Bulk actor import | Done | Bulk add in `actors.py` route + editor template. |
| YF-08 | Arena overview page | Done | `arenas/index.html` -- dynamic, tier-organized, with descriptions. |
| YF-09 | Tier precedence explanation | Done | Found in launcher template, collections routes, `base.py` documentation. |
| YF-10 | Group label autocomplete enhancement | Done | Dynamic `_updateDatalist()` in QD editor collects existing group labels. |
| YF-11 | Snowball sampling platform transparency | Done | Platform transparency in actors template and route. |
| YF-12 | RSS feed preview | Done | Confirmed already implemented during audit. |
| YF-13 | Discovered sources cross-design view | Done | Scope toggle ("This Design" / "All My Designs") in `discovered_links.html` (line 164). |
| YF-14 | Google Search free-tier guidance | Done | Amber badge on Google arenas in QD editor: "Requires MEDIUM+ tier". |
| YF-15 | Custom subreddit UI | Done (via GR-03) | Subsumed by the Reddit custom subreddits panel. |
| YF-16 | Actor platform presence inline add | Done | Inline expandable form in QD editor actor rows. HTMX POST to `/actors/{actor_id}/presences`. |

**Result: 16/16 implemented (100%).**

---

## Per-Report Status: Socialt Bedrageri (SB-01--SB-16)

**Report date:** 2026-02-20
**Report path:** `/docs/research_reports/socialt_bedrageri_codebase_recommendations.md`

All 16 items implemented on 2026-02-20. See the "What's New: Socialt Bedrageri" section above for full details.

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

## Cross-Reference Table: Items Recommended by Multiple Reports

The following table maps items that appeared in two or more reports to the single implementation that addressed all of them.

| Implementation | CO2 Afgift | AI og Uddannelse | Greenland | Ytringsfrihed | Socialt Bedrageri | IP2 |
|---------------|------------|-----------------|-----------|---------------|-------------------|-----|
| **Duplicate exclusion in analysis** | P1.2 | IM-1.4 | -- | -- | -- | IP2-004 |
| **Extend flat export columns** | P1.3 | IM-1.5 | -- | -- | -- | IP2-005 |
| **Human-readable export headers** | (FP-33) | (IM-37) | -- | -- | -- | IP2-006 |
| **Add Altinget RSS feed** | P1.1 | IM-1.2 | -- | -- | -- | IP2-009 |
| **Client-side language detection** | P2.1 | IM-2.4 | GR-07 | -- | -- | IP2-008 |
| **Boolean query support** | P2.3 | IM-3.4 | -- | -- | -- | IP2-031 |
| **Near-duplicate detection (SimHash)** | P2.4 | -- | (used) | -- | -- | IP2-032 |
| **Enrichment pipeline architecture** | (TD-4) | (TD-3) | (used) | -- | -- | IP2-036 |
| **Content annotation layer** | P4.2 | IM-2.5 | -- | -- | SB-16 extends | IP2-043 |
| **Query design cloning** | P4.1 | IM-4.1 | -- | -- | -- | IP2-051 |
| **Emergent term extraction** | P3.2 | IM-2.1 | (used) | -- | SB-01 builds on | IP2-038 |
| **Temporal network snapshots** | P3.3 | IM-3.1 | (used) | -- | -- | IP2-044 |
| **Cross-arena flow analysis** | P3.4 | IM-3.3 | GR-08 | -- | -- | IP2-050 |
| **Named entity extraction** | -- | IM-3.5 | (used) | -- | -- | IP2-049 |
| **Actor type enumeration** | (Gap) | IM-3.6 | -- | -- | -- | IP2-060 |
| **RIS/BibTeX export** | P4.4 | -- | -- | -- | -- | IP2-056 |
| **Education RSS feeds** | -- | IM-1.3 | -- | -- | -- | IP2-058 |
| **Reddit subreddit expansion** | (DQ-04) | -- | -- | -- | -- | IP2-059 |
| **Source-list config UI** | -- | -- | GR-01--04 | YF-02 | -- | -- |
| **Per-arena term scoping** | -- | -- | (GR-05 partial) | YF-01 | -- | -- |
| **Credit estimation** | -- | -- | -- | YF-04 | SB-14 | -- |
| **Cross-run analysis** | -- | -- | -- | YF-06 | SB-06, SB-07 | -- |
| **Consolidate filter builders** | (TD-2) | (TD-1) | -- | -- | -- | IP2-024 |
| **GEXF uses network.py** | (TD-3) | (TD-2) | -- | -- | -- | IP2-025 |
| **Topic modeling (BERTopic)** | P3.5 | -- | GR-15 | -- | -- | IP2-054 |
| **Folketinget.dk arena** | P3.6 | -- | -- | -- | -- | IP2-057 |
| **In-browser network preview** | P4.3 | IM-4.3 | -- | -- | -- | IP2-042 |
| **Filtered export** | P4.5 | IM-4.4 | -- | -- | -- | IP2-055 |
| **Engagement normalization** | P2.2, P2.6 | -- | -- | -- | -- | IP2-030 |
| **Sentiment analysis** | P3.1 | -- | -- | -- | -- | IP2-034 |
| **Temporal comparison** | P2.5 | -- | -- | -- | -- | IP2-033 |
| **Multilingual query design / Bilingual term pairing** | -- | IM-4.2 | (GR-05 partial) | -- | -- | IP2-052 |

---

## Remaining Work: Not Yet Implemented

As of 2026-02-20 (late), all actionable code items from all six research reports and the IP2 roadmap have been implemented. The following items are the only remaining work.

### Phase D Deferred Items

| ID | Description | Reports | Notes |
|----|-------------|---------|-------|
| IP2-054 | Topic modeling (BERTopic) | CO2 (P3.5), GR-15, IP2 | Requires GPU, heavy dependencies (torch, BERTopic). Not appropriate for current deployment profile. |
| IP2-057 | Folketinget.dk parliamentary proceedings arena | CO2 (P3.6), IP2 | Arena brief required before implementation. Requires research into Folketinget.dk data access. |

### Non-Code Items

| ID | Description | Reports | Notes |
|----|-------------|---------|-------|
| P1.5 | Create CO2 afgift use case document | CO2 | Research artifact for `/docs/use_cases/`. |
| IM-1.6 | Create AI og uddannelse use case document | AI | Research artifact for `/docs/use_cases/`. |
| GR-13 | Apply for Meta Content Library | GR | Institutional process. 2--6 month review cycle. |

---

## IP2 Full Item Tracker (IP2-001 through IP2-061)

This is the authoritative reference for the status of every item in the Implementation Plan 2.0 roadmap. Each status has been verified against the actual codebase as of 2026-02-20.

### Phase A: Foundation Fixes

| ID | Description | Phase | Status | Verified By |
|----|-------------|-------|--------|-------------|
| IP2-001 | Dynamic arena grid from server registry | A | Done | QD editor Alpine.js `arenaConfigGrid`, `/api/arenas/` |
| IP2-002 | Arena tier validation (disable unsupported) | A | Done | `supportedTiers.includes(t)` in QD editor |
| IP2-003 | Arena descriptions in config grid | A | Done | `arena.description` in grid |
| IP2-004 | Duplicate exclusion in analysis queries | A | Done | `_filters.py` |
| IP2-005 | Extend flat export columns | A | Done | `export.py` |
| IP2-006 | Human-readable export headers | A | Done | `export.py` |
| IP2-007 | Actor synchronization (QD to Actor Directory) | A | Done | QD editor creates/links Actor + ActorListMember |
| IP2-008 | Client-side language detection | A | Done | `LanguageDetector` enricher |
| IP2-009 | Add Altinget RSS feed | A | Done | `danish_defaults.py` |
| IP2-010 | Update stale "Phase 0" text | A | Done | No "Phase 0" in templates |
| IP2-011 | Arena column always visible | A | Done | xl-only class removed; arena column visible at all breakpoints |
| IP2-012 | Analysis filter dropdowns | A | Done | Dropdowns populated from run data replace free-text inputs |
| IP2-013 | Chart axis labels | A | Done | Y-axis "Number of records" labels added to analysis charts |
| IP2-014 | Query design detail shows arena config | A | Done | Read-only arena configuration display on QD detail page |
| IP2-015 | Term type help text (tooltips) | A | Done | Tooltips on Keyword/Phrase/Hashtag term type options |
| IP2-016 | Snowball sampling discoverability | A | Done | Nav link to snowball sampling from Actor Directory |
| IP2-017 | Admin credential form missing platforms | A | Done | Gab, Threads, Bright Data, SerpAPI added to platform dropdown |
| IP2-018 | Collection detail context (QD name, terms) | A | Done | QD name and terms summary shown in collection detail header |
| IP2-019 | Replace "Celery Beat" jargon | A | Done | Researcher-friendly "Scheduled collection" label |
| IP2-020 | Save confirmation feedback | A | Done | Flash/checkmark feedback after arena config save |
| IP2-021 | Timestamp timezone display | A | Done | UTC timezone labels on timestamps |
| IP2-022 | Tier precedence documentation | A | Done | Already implemented in launcher template and base.py |
| IP2-023 | Date range guidance per arena | A | Done | Per-arena historical coverage tooltips in launcher |
| IP2-024 | Consolidate analysis filter builders | A | Done | `_filters.py` |
| IP2-025 | GEXF export uses network.py functions | A | Done | `export.py` consumes network analysis |
| IP2-026 | Relabel "JSON" export to "NDJSON" | A | Done | Export label updated with format tooltip |
| IP2-027 | Fix mixed-language "termer" | A | Done | Consistent English labels throughout |
| IP2-028 | Engagement score tooltip | A | Done | Tooltip explaining score is not cross-platform comparable |
| IP2-029 | Search term filter as dropdown | A | Done | Dropdown populated from QD terms |

**Phase A: 29/29 done (100%).**

### Phase B: Discourse Tracking Maturity

| ID | Description | Phase | Status | Verified By |
|----|-------------|-------|--------|-------------|
| IP2-030 | Engagement score normalization | B | Done | `compute_normalized_engagement()` in `normalizer.py` (line 448) |
| IP2-031 | Boolean query support | B | Done | `query_builder.py`, migration 006 |
| IP2-032 | Near-duplicate detection (SimHash) | B | Done | `deduplication.py`, migration 007 |
| IP2-033 | Temporal volume comparison | B | Done | `get_temporal_comparison()` in `descriptive.py` (line 894) |
| IP2-034 | Danish sentiment analysis enrichment | B | Done | `SentimentAnalyzer` in `enrichments/sentiment_analyzer.py` |
| IP2-035 | Engagement metric refresh | B | Done | `refresh_engagement()` on base (line 334), `maintenance_tasks.py` (line 265) |
| IP2-036 | Enrichment pipeline architecture | B | Done | `ContentEnricher` base class, 6 enrichers registered |
| IP2-037 | Arena-comparative analysis | B | Done | `get_arena_comparison()` in `descriptive.py` (line 1096) |

**Phase B: 8/8 done (100%).**

### Phase C: Issue Mapping Capabilities

| ID | Description | Phase | Status | Verified By |
|----|-------------|-------|--------|-------------|
| IP2-038 | Emergent term extraction (TF-IDF) | C | Done | `/analysis/{run_id}/emergent-terms` route |
| IP2-039 | Unified actor ranking | C | Done | `get_top_actors_unified()` in `descriptive.py` (line 591) |
| IP2-040 | Bipartite network with extracted topics | C | Done | `build_enhanced_bipartite_network()` in `network.py` (line 972) |
| IP2-041 | Entity resolution UI | C | Done | Full researcher-facing UI confirmed: entity resolution page with trigger, monitor, and review capabilities |
| IP2-042 | In-browser network preview | C | Done | `api/static/js/network_preview.js` + Sigma.js |
| IP2-043 | Content annotation layer | C | Done | Migration 005, model, routes, UI |
| IP2-044 | Temporal network snapshots | C | Done | Weekly/monthly network evolution |
| IP2-045 | Dynamic GEXF export | C | Done | `export_temporal_gexf()` in `export.py` (line 1032) |
| IP2-046 | Term grouping in query design | C | Done | Migration 006 |
| IP2-047 | Per-arena GEXF export | C | Done | Arena filter in `export.py` and analysis routes |
| IP2-048 | Platform attribute on bipartite GEXF | C | Done | `export.py` |
| IP2-049 | Named entity extraction | C | Done | `NamedEntityExtractor` enricher, spaCy-based |
| IP2-050 | Cross-arena flow analysis | C | Done | `analysis/propagation.py` + `PropagationDetector` enricher |
| IP2-058 | Education-specific RSS feeds | C | Done | Folkeskolen, Gymnasieskolen, KU, DTU, CBS |

**Phase C: 14/14 done (100%).**

### Phase D: Advanced Research Features

| ID | Description | Phase | Status | Verified By |
|----|-------------|-------|--------|-------------|
| IP2-051 | Query design cloning and versioning | D | Done | Migration 008, `parent_design_id` |
| IP2-052 | Multilingual query design | D | Done | Migration 013 adds `translations JSONB` to search_terms. Bilingual term pairing with query builder integration. Frontend UI with collapsible per-term translation inputs. |
| IP2-053 | Query term suggestion from collected data | D | Done | Shares endpoint with IP2-038 emergent terms |
| IP2-054 | Topic modeling enrichment (BERTopic) | D | Not done | Deferred. GPU + heavy dependencies required. |
| IP2-055 | Filtered export from analysis results | D | Done | Analysis template + content browser + routes |
| IP2-056 | RIS/BibTeX export | D | Done | `export.py` |
| IP2-057 | Folketinget.dk arena | D | Not done | Arena brief not yet written. |
| IP2-059 | Expand Danish Reddit subreddits | D | Done | r/dkfinance added, r/dkpolitik verified |
| IP2-060 | Formalize actor_type values | D | Done | `ActorType` enum |
| IP2-061 | Mixed hash/name resolution in charts | D | Done | Network analysis functions use LEFT JOIN + COALESCE to prefer resolved actor names over hashes |

**Phase D: 8/10 done (80%). 2 deferred (IP2-054, IP2-057).**

### IP2 Summary

| Phase | Total | Done | Partial | Not Done | Deferred |
|-------|-------|------|---------|----------|----------|
| A: Foundation Fixes | 29 | 29 | 0 | 0 | 0 |
| B: Tracking Maturity | 8 | 8 | 0 | 0 | 0 |
| C: Issue Mapping | 14 | 14 | 0 | 0 | 0 |
| D: Advanced Features | 10 | 8 | 0 | 0 | 2 |
| **Total** | **61** | **59** | **0** | **0** | **2** |

Effective implementation rate: **59/61 (97%)**. The 2 deferred items (IP2-054 BERTopic topic modeling, IP2-057 Folketinget.dk arena) are intentionally excluded from the current release due to infrastructure requirements (GPU) and missing prerequisites (arena brief).

---

## Database Migrations Summary

All 13 migrations have been verified to exist in `alembic/versions/`. All must be applied via `alembic upgrade head`.

| Migration | Description | Related IDs | Date |
|-----------|-------------|-------------|------|
| 001 | Initial schema: all core tables, indexes, content_records partitions | -- | 2026-02-15 |
| 002 | `arenas_config JSONB` on query_designs | GR-01 through GR-05 | 2026-02-15 |
| 003 | `suspended_at` on collection_runs | B-03 | 2026-02-16 |
| 004 | Scraping jobs table | -- | 2026-02-16 |
| 005 | Content annotations table | IP2-043, P4.2, IM-2.5 | 2026-02-17 |
| 006 | Search term groups (`group_id`, `group_label`) | IP2-046, IP2-031 | 2026-02-17 |
| 007 | `simhash BIGINT` on content_records | IP2-032, P2.4 | 2026-02-18 |
| 008 | Query design cloning (`parent_design_id`) | IP2-051, P4.1, IM-4.1 | 2026-02-18 |
| 009 | `public_figure BOOLEAN` on actors | GR-14 | 2026-02-19 |
| 010 | `target_arenas JSONB` on search_terms | YF-01 | 2026-02-19 |
| 011 | GIN index on `search_terms.target_arenas` | YF-01 | 2026-02-19 |
| 012 | `codebook_entries` table | SB-16 | 2026-02-20 |
| **013** | **`translations JSONB` on search_terms** | **IP2-052** | **2026-02-20** |

**Action required:** If upgrading from any previous state, run:

```bash
alembic upgrade head
```

Migration 013 adds a nullable `translations` JSONB column to `search_terms` for bilingual term pairing (IP2-052). Non-breaking: existing rows default to NULL.

---

## API Changes

### New API Endpoints (2026-02-20, full day)

| Method | Path | Description | ID |
|--------|------|-------------|-----|
| GET | `/analysis/compare` | Cross-run comparison | SB-06 |
| GET | `/analysis/design/{id}/summary` | Design-level analysis summary | SB-07 |
| GET | `/analysis/design/{id}/volume` | Design-level volume | SB-07 |
| GET | `/analysis/design/{id}/actors` | Design-level actors | SB-07 |
| GET | `/analysis/design/{id}/terms` | Design-level terms | SB-07 |
| GET | `/analysis/design/{id}/network/actors` | Design-level actor network | SB-07 |
| GET | `/analysis/design/{id}/network/terms` | Design-level term network | SB-07 |
| GET | `/analysis/design/{id}/network/bipartite` | Design-level bipartite network | SB-07 |
| GET | `/analysis/{run_id}/enrichments/languages` | Language distribution | SB-15 |
| GET | `/analysis/{run_id}/enrichments/entities` | Named entity summary | SB-15 |
| GET | `/analysis/{run_id}/enrichments/propagation` | Propagation patterns | SB-15 |
| GET | `/analysis/{run_id}/enrichments/coordination` | Coordination signals | SB-15 |
| GET | `/analysis/{run_id}/temporal-comparison` | Period-over-period volume | IP2-033 |
| GET | `/analysis/{run_id}/arena-comparison` | Per-arena metrics | IP2-037 |
| GET | `/analysis/{run_id}/emergent-terms` | TF-IDF emergent terms | IP2-038 |
| GET | `/analysis/{run_id}/actors-unified` | Top actors by canonical identity | IP2-039 |
| POST | `/collections/{run_id}/refresh-engagement` | Re-fetch engagement metrics (async) | IP2-035 |
| POST | `/query-designs/{id}/discover-feeds` | RSS feed autodiscovery | SB-09 |
| GET | `/query-designs/{id}/suggest-subreddits` | Reddit subreddit suggestions | SB-10 |
| GET/POST/PUT/DELETE | `/codebooks/*` | Codebook CRUD | SB-16 |

### Modified API Endpoints

| Method | Path | Change | ID |
|--------|------|--------|-----|
| POST | `/collections/estimate` | Now returns real per-arena credit estimates (was stub returning zeros). Response schema unchanged. | SB-14 |
| GET | `/api/arenas/` | Response now includes `temporal_mode` field per arena. | SB-04 |

### New Dependencies

| Package | Version | Required By | Extra |
|---------|---------|-------------|-------|
| `beautifulsoup4` | `>=4.12,<5.0` | SB-09 (RSS feed autodiscovery) | Core |
| `afinn` | `>=0.1,<1.0` | IP2-034 (Danish sentiment analysis) | `[nlp]` |

### No Breaking Changes

All changes are additive. Existing API contracts, database schemas (after migration), and frontend templates remain backward-compatible. The `POST /collections/estimate` endpoint now returns real values instead of zeros, which is a behavior change but not a contract change -- the response schema is unchanged.

---

## New Files Added (2026-02-20)

| File | Purpose |
|------|---------|
| `src/issue_observatory/arenas/rss_feeds/feed_discovery.py` | RSS feed autodiscovery module (SB-09) |
| `src/issue_observatory/core/models/codebook.py` | CodebookEntry ORM model (SB-16) |
| `src/issue_observatory/core/schemas/codebook.py` | Codebook Pydantic schemas (SB-16) |
| `src/issue_observatory/api/routes/codebooks.py` | Codebook CRUD API routes (SB-16) |
| `src/issue_observatory/api/templates/annotations/codebook_manager.html` | Codebook management UI (SB-16) |
| `src/issue_observatory/analysis/enrichments/sentiment_analyzer.py` | Danish sentiment analysis enricher (IP2-034) |
| `alembic/versions/012_add_codebook_entries.py` | Migration for codebook_entries table (SB-16) |
| `alembic/versions/013_add_search_term_translations.py` | Migration for translations JSONB on search_terms (IP2-052) |
| `docs/decisions/ADR-012-source-discovery-assistance.md` | ADR for SB-09/SB-10 design decisions |
| `docs/implementation_notes/SB-09-SB-10-source-discovery.md` | Implementation notes for source discovery |
| `docs/implementation_notes/SB-16_codebook_ui_implementation.md` | Implementation notes for codebook UI |
| `docs/implementation_reports/SB-16_codebook_management_api.md` | API layer implementation report |
| `docs/implementation_reports/SB-16_API_SUMMARY.md` | Quick reference for SB-16 API |
| `docs/testing/socialt_bedrageri_test_plan.md` | Test plan for all 16 SB items |

## Modified Files (2026-02-20, evening batch)

| File | Changes |
|------|---------|
| `src/issue_observatory/core/normalizer.py` | Added `compute_normalized_engagement()` (IP2-030) |
| `src/issue_observatory/analysis/descriptive.py` | Added `get_temporal_comparison()`, `get_arena_comparison()`, `get_top_actors_unified()` (IP2-033, IP2-037, IP2-039) |
| `src/issue_observatory/api/routes/analysis.py` | Added temporal-comparison, arena-comparison, actors-unified, emergent-terms endpoints |
| `src/issue_observatory/arenas/base.py` | Added optional `refresh_engagement()` method, `TemporalMode` enum (IP2-035, SB-04) |
| `src/issue_observatory/workers/maintenance_tasks.py` | Added `refresh_engagement_metrics` Celery task (IP2-035) |
| `src/issue_observatory/api/routes/collections.py` | Added refresh-engagement endpoint (IP2-035) |
| `src/issue_observatory/analysis/enrichments/__init__.py` | Registered SentimentAnalyzer |
| `src/issue_observatory/api/templates/query_designs/editor.html` | YF-14 badge, YF-16 inline form |
| `src/issue_observatory/api/templates/content/discovered_links.html` | YF-13 scope toggle |
| `src/issue_observatory/api/templates/explore/index.html` | YF-05 dynamic arena list |
| `pyproject.toml` | Added `afinn` to `[nlp]` extra |

## Modified Files (2026-02-20, late batch)

| File | Changes |
|------|---------|
| `src/issue_observatory/api/templates/content/browser.html` | IP2-011 arena column always visible, IP2-029 search term filter dropdown |
| `src/issue_observatory/api/templates/analysis/dashboard.html` | IP2-012 filter dropdowns, IP2-013 chart axis labels, IP2-028 engagement tooltip |
| `src/issue_observatory/api/templates/query_designs/detail.html` | IP2-014 read-only arena config display |
| `src/issue_observatory/api/templates/query_designs/editor.html` | IP2-015 term type tooltips, IP2-052 per-term translation inputs |
| `src/issue_observatory/api/templates/actors/index.html` | IP2-016 snowball sampling nav link |
| `src/issue_observatory/api/templates/admin/credentials.html` | IP2-017 missing platforms added |
| `src/issue_observatory/api/templates/collections/detail.html` | IP2-018 QD name and terms summary, IP2-019 "Celery Beat" replaced |
| `src/issue_observatory/api/templates/collections/launcher.html` | IP2-023 date range guidance tooltips |
| `src/issue_observatory/api/templates/partials/arena_config_save.html` | IP2-020 save confirmation feedback |
| `src/issue_observatory/api/templates/base.html` | IP2-021 timezone labels on timestamps |
| `src/issue_observatory/api/templates/analysis/export_panel.html` | IP2-026 NDJSON label, IP2-027 English labels |
| `src/issue_observatory/core/models/search_term.py` | IP2-052 `translations` JSONB column |
| `src/issue_observatory/core/schemas/search_term.py` | IP2-052 translations field |
| `src/issue_observatory/arenas/query_builder.py` | IP2-052 bilingual term expansion |
| `src/issue_observatory/analysis/network.py` | IP2-061 LEFT JOIN + COALESCE for resolved actor names |
| `src/issue_observatory/workers/_task_helpers.py` | QA-001/QA-002 bug fix |

---

## Implementation Timeline

| Date | Items Implemented | Key Milestone |
|------|------------------|---------------|
| 2026-02-15 | Core infrastructure, migrations 001--004 | Project bootstrap complete |
| 2026-02-16 | Arena briefs (all Phase 1 + Phase 2) | Engineering agents unblocked |
| 2026-02-17 | CO2 afgift report, Phase 3 UX fixes (B-01 through B-03) | B-02 GEXF fix (critical data correctness) |
| 2026-02-18 | AI uddannelse report, IP2 strategy, Greenland report, IP2-004/005/006/008/009/024/025/031/032/036/043/046/048/049/051/056/058/059/060 | Phase A + B + C foundation complete |
| 2026-02-19 | GR-01 through GR-22 (18 code items), YF-01, YF-03, migrations 009--011 | Researcher self-service mechanisms complete |
| 2026-02-20 (AM) | SB-01 through SB-16 (16 items), migration 012 | Discovery feedback loop + iterative workflow complete |
| 2026-02-20 (PM) | IP2-030/033/034/035/037, YF-05/10/13/14/16, 20+ audit corrections | Analysis maturity + enrichment pipeline complete |
| 2026-02-20 (late) | IP2-011--029 (Phase A polish), IP2-052, IP2-061, migration 013, QA-001/QA-002 fix | All IP2 actionable items complete |

---

## Overall Assessment

The Issue Observatory has reached a mature state for multi-platform Danish discourse research. As of 2026-02-20 (late):

**Infrastructure:**
- 24 arena directories (21 functional, 2 deferred stubs, 1 limited)
- 13 database migrations defining the complete schema
- DB-backed credential pool with Fernet encryption, Redis lease/quota/cooldown
- Celery + Redis task queue with rate limiting (Lua sliding window)
- SSE live collection monitoring via Redis pub/sub

**Data Quality:**
- 6 enrichment modules providing automated post-collection analysis (language detection, NER, propagation, coordination, sentiment, plus the base class)
- Near-duplicate detection via SimHash with Hamming distance threshold
- Engagement score normalization across 7 platform types
- Deduplication pipeline (URL, content hash, SimHash)

**Research Workflow:**
- Researcher self-service configuration for RSS feeds, Telegram channels, Reddit subreddits, Discord channels, and Wikipedia seed articles
- Per-arena search term scoping (YF-01) preventing cross-arena contamination
- Discovery feedback loops (one-click term/source addition, RSS autodiscovery, subreddit suggestion)
- Cross-run and design-level analysis for iterative research
- Annotation codebook management for structured qualitative coding
- In-browser network visualization (Sigma.js) with 4 GEXF export modes (static, dynamic/temporal, per-arena, enhanced bipartite)

**What Remains:**
- **2 Phase D deferred features** (IP2-054 BERTopic topic modeling requiring GPU infrastructure, IP2-057 Folketinget.dk arena requiring research brief).
- **2 non-code items** (use case documents P1.5, IM-1.6) -- research artifacts for `/docs/use_cases/`.
- **1 institutional process** (GR-13 Meta Content Library application) -- 2--6 month review cycle.

All actionable code items from all six research reports and the full IP2 roadmap (59/61 items, 97%) have been implemented. The system fully supports both discourse tracking (CO2 afgift style) and issue mapping (Marres style) research methodologies.

---

*End of release notes. This document is the single source of truth for implementation status as of 2026-02-20. It should be updated when additional implementations from the remaining work items are completed.*
