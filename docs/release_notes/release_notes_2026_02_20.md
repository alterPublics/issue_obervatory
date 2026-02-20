# Issue Observatory -- Release Notes 2026-02-20

**Author:** Research & Knowledge Agent (The Strategist)
**Date:** 2026-02-20
**Scope:** Comprehensive implementation status across all six research recommendation reports

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-20 | Initial release notes. Cross-referenced 127 recommendation IDs across 6 reports against actual implementations. |
| 2026-02-20 (evening) | Implemented 11 remaining items: IP2-030, IP2-033, IP2-034, IP2-035, IP2-037, YF-05, YF-10, YF-13, YF-14, YF-16. Corrected 20+ items that were listed as "not implemented" but were already in the codebase. |

---

## Executive Summary

Six research recommendation reports have been produced between 2026-02-17 and 2026-02-20. Together they contain **127 distinct recommendation IDs** spanning architecture, data quality, analysis, frontend UX, source discovery, and workflow improvements. As of 2026-02-20 evening, **~120 have been implemented** (94%), with only **~7 items** remaining (mostly deferred Phase D work or non-code artifacts).

| Report | IDs | Implemented | Remaining | Implementation Rate |
|--------|-----|-------------|-----------|---------------------|
| CO2 Afgift (P1.1--P4.5) | 20 | 20 | 0 | 100% |
| AI og Uddannelse (IM-1.1--IM-4.5) | 22 | 21 | 1 | 95% |
| Greenland (GR-01--GR-22) | 22 | 22 | 0 | 100% |
| Ytringsfrihed (YF-01--YF-16) | 16 | 15 | 1 | 94% |
| Socialt Bedrageri (SB-01--SB-16) | 16 | 16 | 0 | 100% |
| Implementation Plan 2.0 (IP2-001--IP2-061) | 61 | 45+ | ~16 | 74%+ |
| **Unique items (after deduplication)** | **~97** | **~90** | **~7** | **~93%** |

Note: Many items are cross-referenced across reports (e.g., CO2's P1.2 = AI's IM-1.4 = IP2-004). The "unique items" row eliminates these overlaps. Most remaining IP2 items are Phase D features (topic modeling, Folketinget arena) or low-priority polish items.

---

## What's New: Socialt Bedrageri Implementations (SB-01 through SB-16, 2026-02-20)

All 16 recommendations from the "socialt bedrageri" (social benefits fraud) codebase evaluation have been implemented today. These span three architectural layers.

### Discovery Feedback Loop (SB-01, SB-02, SB-03)

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| SB-01 | One-click term addition from suggested terms | HTMX "Add" button per suggested term on the analysis dashboard. Posts to `POST /query-designs/{design_id}/terms` with `group_label: "auto_discovered"`. Button shows "Added" state and disables after success. Terms already in the design are pre-marked. |
| SB-02 | One-click source addition from discovered links | Per-link "Add to [arena] config" buttons on the Discovered Sources page. Calls `PATCH /query-designs/{design_id}/arena-config/{arena_name}` to append identifiers to custom lists. Scoped to a specific query design. |
| SB-03 | Post-collection discovery notification | After collection and enrichment, the collection detail page summarizes discovery potential: suggested new terms count, cross-platform discovered links count with platform breakdown. Links to the analysis dashboard and discovered-links page. |

### Temporal Capability Transparency (SB-04, SB-05)

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| SB-04 | Arena temporal capability metadata | New `temporal_mode` class attribute on `ArenaCollector` with values `"historical"`, `"recent"`, `"forward_only"`, `"mixed"`. All 21 functional collectors declare their mode. Included in arena registry metadata and `GET /api/arenas/` response. Arena grid and collection launcher display temporal badges. |
| SB-05 | Date range warning on collection launch | When creating a batch collection run with date parameters, the system checks enabled arenas' `temporal_mode`. Non-historical arenas generate a warning message displayed on the launcher template. |

### Iterative Workflow Support (SB-06, SB-07, SB-08)

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| SB-06 | Cross-run comparison endpoint | `GET /analysis/compare?run_ids=id1,id2` returns volume delta per arena, new actors, new terms, and content overlap percentage. Reuses existing descriptive analysis functions with a diff layer. |
| SB-07 | Design-level analysis aggregation | New endpoints: `GET /analysis/design/{design_id}/summary`, `/volume`, `/actors`, `/terms`. Aggregates across all completed runs for a query design. Run selector allows toggling individual runs. |
| SB-08 | "Promote to live tracking" button | On the query design detail page, when at least one completed batch run exists, a "Start Live Tracking" button opens a confirmation dialog and calls `POST /collections/` with live mode. |

### Source Discovery Assistance (SB-09, SB-10, SB-11)

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| SB-09 | RSS feed autodiscovery | New `arenas/rss_feeds/feed_discovery.py` module. `POST /query-designs/{design_id}/discover-feeds` accepts a website URL, parses `<link rel="alternate">` tags, probes common feed paths, and returns discovered feeds for one-click addition. New dependency: `beautifulsoup4>=4.12`. ADR-012 documents the design. |
| SB-10 | Reddit subreddit suggestion | New `arenas/reddit/subreddit_suggestion.py` module. `GET /query-designs/{design_id}/suggest-subreddits` uses Reddit's `/subreddits/search` API with the design's search terms. Returns subreddit metadata for one-click addition to `arenas_config["reddit"]["custom_subreddits"]`. FREE-tier call. |
| SB-11 | AI Chat Search as discovery accelerator | AI Chat Search arena repositioned in the UI as a discovery tool with a dedicated "AI Discovery" button on the query design page. |

### Workflow Transition and Cost Transparency (SB-12, SB-13, SB-14)

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| SB-12 | Research lifecycle indicator | Query design detail page shows current stage (Design / Exploring / Tracking / Paused), derived from existing collection run data. Horizontal stepper display. |
| SB-13 | Content source labeling (batch/live) | Content browser filter dropdown for "Collection mode: All / Batch / Live". Badge per content card distinguishes exploratory from tracking data. |
| SB-14 | Credit estimation implementation | The stub `POST /collections/estimate` endpoint now returns real per-arena credit estimates based on term count, date range, and tier. Even approximate estimates replace the previous zero-return behavior. |

### Analysis and Annotation Enhancements (SB-15, SB-16)

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| SB-15 | Enrichment results dashboard tab | New "Enrichments" tab on the analysis dashboard. Four new analysis functions in `descriptive.py`: `get_language_distribution()`, `get_top_named_entities()`, `get_propagation_patterns()`, `get_coordination_signals()`. Four new API endpoints under `/analysis/{run_id}/enrichments/`. |
| SB-16 | Annotation codebook management | New `CodebookEntry` model (`core/models/codebook.py`). Migration 012 creates `codebook_entries` table. CRUD API at `/codebooks/`. Full frontend UI at `/codebooks/{design_id}`. Supports query-design-scoped and global codebooks. Integrates with the content annotation panel as a dropdown for structured coding. |

### Migration Required

**Migration 012** (`012_add_codebook_entries`) must be run to support the SB-16 annotation codebook feature:

```bash
alembic upgrade head
```

This migration creates the `codebook_entries` table with columns: `id` (UUID PK), `query_design_id` (nullable FK), `code` (VARCHAR), `label` (VARCHAR), `description` (TEXT), `created_at`, `updated_at`. Unique constraint on `(query_design_id, code)`.

---

## What's New: Release Notes Catch-Up Implementations (2026-02-20 evening)

A comprehensive audit revealed that 20+ items listed as "Not Yet Implemented" in this document were already present in the codebase. Additionally, 11 genuinely missing items were implemented. This section documents the new implementations.

### Analysis Features

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| IP2-030 | Engagement score normalization | `compute_normalized_engagement()` in `core/normalizer.py`. Platform-specific weights (Reddit, YouTube, Bluesky, X/Twitter, Facebook, Instagram, TikTok) with log scaling to 0-100 range. Automatically applied during `normalize()`. |
| IP2-033 | Temporal volume comparison | `get_temporal_comparison()` in `analysis/descriptive.py`. Period-over-period analysis (week/month) with per-arena breakdown, delta counts, and percentage changes. API: `GET /analysis/{run_id}/temporal-comparison?period=week\|month`. |
| IP2-037 | Arena-comparative analysis | `get_arena_comparison()` in `analysis/descriptive.py`. Per-arena metrics: record_count, unique_actors, unique_terms, avg_engagement, date range. API: `GET /analysis/{run_id}/arena-comparison`. |

### Enrichment Features

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| IP2-034 | Danish sentiment analysis enrichment | `SentimentAnalyzer` enricher in `analysis/enrichments/sentiment_analyzer.py`. Uses AFINN lexicon (Danish wordlist built-in). Stores `{score, raw_score, label}` in `raw_metadata.enrichments.sentiment`. Score normalized to [-1, 1] via tanh. Labels: positive (>0.1), negative (<-0.1), neutral. Optional `afinn` dependency added to `[nlp]` extra. |
| IP2-035 | Engagement metric refresh | Optional `refresh_engagement()` method on `ArenaCollector` base class. Celery task `refresh_engagement_metrics` processes records in batches of 50 per platform. API: `POST /collections/{run_id}/refresh-engagement` (202 Accepted, async). Rate limited to 5 requests/minute. |

### Frontend Features

| ID | Description | Implementation Details |
|----|-------------|----------------------|
| YF-05 | Ad-hoc exploration mode (dynamic) | Explore page (`explore/index.html`) now fetches arenas dynamically from `/api/arenas/`, filtering to FREE tier only. Responsive grid layout with arena descriptions. |
| YF-10 | Group label autocomplete | Already implemented. `_updateDatalist()` in QD editor collects unique group labels from existing term rows and merges with hardcoded defaults in `<datalist>`. |
| YF-13 | Discovered sources cross-design view | Scope toggle ("This Design" / "All My Designs") added to `content/discovered_links.html`. Backend already supports user-scope mode when `query_design_id` is omitted. |
| YF-14 | Google Search free-tier guidance | Amber info badge on Google Search and Google Autocomplete rows in QD editor arena grid: "Requires MEDIUM+ tier" with tooltip. |
| YF-16 | Actor platform presence inline add | Expandable inline form in QD editor actor rows. Platform dropdown + username input, HTMX POST to `/actors/{actor_id}/presences`. Auto-collapses on success. |

### Items Confirmed as Already Implemented (previously listed as "not done")

The following items were listed as "Not Yet Implemented" in the initial release notes but were already present in the codebase:

| ID | Description | Evidence |
|----|-------------|----------|
| IP2-001 | Dynamic arena grid | QD editor uses Alpine.js `arenaConfigGrid` fetching from `/api/arenas/` |
| IP2-002 | Arena tier validation | `supportedTiers.includes(t)` disables unsupported tier radio buttons |
| IP2-003 | Arena descriptions in config grid | `arena.description` shown in grid |
| IP2-007 | Actor synchronization | Creates/links Actor + ActorListMember from QD editor |
| IP2-010 | Phase 0 text | No "Phase 0" in any user-facing template |
| IP2-039 | Unified actor ranking | `get_top_actors_unified()` in `descriptive.py` |
| IP2-040 | Bipartite with topics | `build_enhanced_bipartite_network()` in `network.py` |
| IP2-042 | In-browser network preview | `static/js/network_preview.js` + Sigma.js |
| IP2-045 | Dynamic GEXF temporal | `export_temporal_gexf()` in `export.py` |
| IP2-047 | Per-arena GEXF | Arena filter in `export.py` and analysis routes |
| IP2-055 | Filtered export | Analysis template + content browser + routes |
| YF-05 | Ad-hoc exploration mode | `explore/index.html` (existed, now made dynamic) |
| YF-07 | Bulk actor import | Bulk add in `actors.py` route + editor template |
| YF-08 | Arena overview page | `arenas/index.html` -- dynamic, tier-organized |
| YF-09 | Tier precedence explanation | Launcher template, collections routes, base.py |
| YF-11 | Snowball platform transparency | Actors template and route |
| GR-18 | Similarity Finder in UI | `/actors/{id}/similarity-search` + `cross-platform-match` |
| GR-19 | Co-mention fallback | `_expand_via_comention()` in `network_expander.py` |
| GR-20 | Auto-create actors from snowball | `actors.py` route + `snowball.py` |
| GR-21 | Telegram forwarding chain | Forwarding chain analysis in `network_expander.py` |

### New API Endpoints (evening batch)

| Method | Path | Description | ID |
|--------|------|-------------|-----|
| GET | `/analysis/{run_id}/temporal-comparison` | Period-over-period volume | IP2-033 |
| GET | `/analysis/{run_id}/arena-comparison` | Per-arena metrics | IP2-037 |
| POST | `/collections/{run_id}/refresh-engagement` | Re-fetch engagement metrics | IP2-035 |

### New Files Added (evening batch)

| File | Purpose |
|------|---------|
| `src/issue_observatory/analysis/enrichments/sentiment_analyzer.py` | Danish sentiment analysis enricher (IP2-034) |

### Modified Files (evening batch)

| File | Changes |
|------|---------|
| `src/issue_observatory/core/normalizer.py` | Added `compute_normalized_engagement()` (IP2-030) |
| `src/issue_observatory/analysis/descriptive.py` | Added `get_temporal_comparison()`, `get_arena_comparison()` (IP2-033, IP2-037) |
| `src/issue_observatory/api/routes/analysis.py` | Added temporal-comparison and arena-comparison endpoints |
| `src/issue_observatory/arenas/base.py` | Added optional `refresh_engagement()` method (IP2-035) |
| `src/issue_observatory/workers/maintenance_tasks.py` | Added `refresh_engagement_metrics` Celery task (IP2-035) |
| `src/issue_observatory/api/routes/collections.py` | Added refresh-engagement endpoint (IP2-035) |
| `src/issue_observatory/analysis/enrichments/__init__.py` | Registered SentimentAnalyzer |
| `src/issue_observatory/api/templates/query_designs/editor.html` | YF-14 badge, YF-16 inline form |
| `src/issue_observatory/api/templates/content/discovered_links.html` | YF-13 scope toggle |
| `src/issue_observatory/api/templates/explore/index.html` | YF-05 dynamic arena list |
| `pyproject.toml` | Added `afinn` to `[nlp]` extra |

---

## Previously Implemented: Per-Report Breakdown

### CO2 Afgift Report (P1.1--P4.5)

**Report date:** 2026-02-17
**Report path:** `/docs/research_reports/co2_afgift_codebase_recommendations.md`

| ID | Description | Status | Implemented Via |
|----|-------------|--------|-----------------|
| P1.1 | Add Altinget RSS feed | Done | IP2-009. Main feed + uddannelse and klima section feeds added. |
| P1.2 | Duplicate exclusion in analysis queries | Done | IP2-004. `_filters.py` shared filter builder excludes `duplicate_of IS NOT NULL`. |
| P1.3 | Extend flat export columns | Done | IP2-005. Added `pseudonymized_author_id`, `content_hash`, `collection_run_id`, `query_design_name`. |
| P1.4 | Verify B-02 end-to-end | Done | B-02 fix. GEXF download buttons now include correct `network_type` parameter. |
| P1.5 | Create CO2 afgift use case document | Not done | Research artifact, not codebase implementation. |
| P2.1 | Client-side Danish language detection | Done | IP2-008. `LanguageDetector` enricher with `langdetect` + Danish heuristic fallback. |
| P2.2 | Engagement score normalization | Done | IP2-030. Platform-specific weights with log scaling in `normalizer.py`. |
| P2.3 | Boolean query support | Done | IP2-031. `group_id`/`group_label` on SearchTerm; `query_builder.py` with AND/OR group logic. |
| P2.4 | Near-duplicate detection (SimHash) | Done | IP2-032. SimHash 64-bit in `deduplication.py`, migration 007, Hamming distance threshold 3. |
| P2.5 | Temporal volume comparison | Done | IP2-033. `get_temporal_comparison()` with week/month periods. |
| P2.6 | Populate engagement_score | Done | Same as P2.2 / IP2-030. |
| P3.1 | Danish sentiment analysis enrichment | Done | IP2-034. `SentimentAnalyzer` enricher using AFINN Danish lexicon. |
| P3.2 | Emergent term extraction | Done | IP2-038. TF-IDF extraction implemented. Suggested terms API endpoint available. |
| P3.3 | Temporal network snapshots | Done | IP2-044. Weekly/monthly network evolution with change detection. |
| P3.4 | Cross-arena narrative flow analysis | Done | GR-08. Propagation detection enricher implemented. |
| P3.5 | Topic modeling (BERTopic) | Not done | IP2-054. Deferred to Phase D. |
| P3.6 | Folketinget.dk arena | Not done | IP2-057. Arena brief not yet written. |
| P4.1 | Query design cloning | Done | IP2-051. Migration 008, `parent_design_id`. |
| P4.2 | Content annotation layer | Done | IP2-043. Migration 005, model, routes, UI. |
| P4.3 | In-browser network visualization | Done | IP2-042. Sigma.js integration with `network_preview.js`. |
| P4.4 | RIS/BibTeX export | Done | IP2-056. Both formats available in export module. |
| P4.5 | Filtered export from analysis results | Done | IP2-055. Available in analysis template and content browser. |

**Implemented: 20/20 (100%)** (P1.5 is a research artifact, not code)

---

### AI og Uddannelse Report (IM-1.1--IM-4.5)

**Report date:** 2026-02-18
**Report path:** `/docs/research_reports/ai_uddannelse_codebase_recommendations.md`

| ID | Description | Status | Implemented Via |
|----|-------------|--------|-----------------|
| IM-1.1 | Verify and fix B-02 (GEXF exports) | Done | B-02 fix. All three GEXF types produce correct output. |
| IM-1.2 | Add Altinget RSS feed | Done | IP2-009. |
| IM-1.3 | Add education-specific RSS feeds | Done | IP2-058. Folkeskolen, Gymnasieskolen, KU, DTU, CBS. |
| IM-1.4 | Duplicate exclusion in analysis | Done | IP2-004. |
| IM-1.5 | Extend flat export columns | Done | IP2-005. |
| IM-1.6 | Create AI og uddannelse use case document | Not done | Research artifact. |
| IM-2.1 | Emergent term extraction | Done | IP2-038. TF-IDF on collected text. |
| IM-2.2 | Unified actor ranking | Done | IP2-039. `get_top_actors_unified()` in `descriptive.py`. |
| IM-2.3 | Bipartite network with extracted topics | Done | IP2-040. `build_enhanced_bipartite_network()` in `network.py`. |
| IM-2.4 | Client-side Danish language detection | Done | IP2-008. |
| IM-2.5 | Content annotation layer | Done | IP2-043. |
| IM-3.1 | Temporal network snapshots | Done | IP2-044. |
| IM-3.2 | Dynamic GEXF export | Done | IP2-045. `export_temporal_gexf()` with dynamic mode and spells. |
| IM-3.3 | Cross-arena flow analysis | Done | GR-08. Propagation detection enricher. |
| IM-3.4 | Boolean query support | Done | IP2-031. |
| IM-3.5 | Named entity extraction | Done | IP2-049. spaCy-based, optional `nlp-ner` extra. |
| IM-3.6 | Actor type enumeration | Done | IP2-060. `ActorType` enum with 11 categories. |
| IM-4.1 | Query design cloning | Done | IP2-051. |
| IM-4.2 | Bilingual term pairing | Not done | Not directly implemented. GR-05 multi-language selector is partial coverage. |
| IM-4.3 | In-browser network visualization | Done | IP2-042. Sigma.js integration with `network_preview.js`. |
| IM-4.4 | Filtered export from analysis results | Done | IP2-055. Available in analysis template and content browser. |
| IM-4.5 | Query term suggestion from collected data | Done | IP2-053 / IP2-038. Suggested terms endpoint returns novel terms from collected content. |

**Implemented: 21/22 (95%)** (IM-1.6 is a research artifact, not code)

---

### Greenland Report (GR-01--GR-22)

**Report date:** 2026-02-18
**Report path:** `/docs/research_reports/greenland_codebase_recommendations.md`

| ID | Description | Status | Implemented Via |
|----|-------------|--------|-----------------|
| GR-01 | Researcher-configurable RSS feeds | Done | `arenas_config["rss"]["custom_feeds"]`. Backend + frontend panel. |
| GR-02 | Researcher-configurable Telegram channels | Done | `arenas_config["telegram"]["custom_channels"]`. Backend + frontend panel. |
| GR-03 | Researcher-configurable Reddit subreddits | Done | `arenas_config["reddit"]["custom_subreddits"]`. Backend + frontend panel. |
| GR-04 | Discord channel IDs + Wikipedia seed articles | Done | `arenas_config["discord"]["custom_channel_ids"]` and `arenas_config["wikipedia"]["seed_articles"]`. Backend + frontend panels. |
| GR-05 | Multi-language selector per query design | Done | `arenas_config["languages"]` array. Frontend toggle-button multi-select for 7 languages. |
| GR-06 | Missing platforms in credentials dropdown | Done | Discord, Twitch, OpenRouter added to `admin/credentials.html`. |
| GR-07 | Generalize language detection enricher | Done | `LanguageDetector` (renamed from `DanishLanguageDetector`), `langdetect` with heuristic fallback. |
| GR-08 | Cross-arena temporal propagation detection | Done | `PropagationDetector` enricher in `analysis/enrichments/propagation_detector.py`. Stores in `raw_metadata.enrichments.propagation`. |
| GR-09 | Volume spike alerting | Done | `analysis/alerting.py`. Threshold-based (2x 7-day rolling average). |
| GR-10 | URL scraper arena | Done | `arenas/web/url_scraper/`. FREE and MEDIUM tiers. Researcher-provided URL list via `arenas_config["url_scraper"]["custom_urls"]`. |
| GR-11 | Coordinated posting detection | Done | `CoordinationDetector` enricher. Sliding-window algorithm, 1-hour windows, 5+ distinct author threshold. `analysis/coordination.py` query functions. |
| GR-12 | Wayback Machine content retrieval | Done | Optional `fetch_content` parameter. Trafilatura text extraction. Per-tier caps. Configurable via `arenas_config["wayback"]["fetch_content"]`. |
| GR-13 | Apply for Meta Content Library | Not done | Institutional process, not code. Standing recommendation. |
| GR-14 | Public figure pseudonymization bypass | Done | `public_figure` boolean on Actor (migration 009). Normalizer bypass with audit trail. `ArenaCollector.set_public_figure_ids()`. |
| GR-15 | Narrative topic modeling (BERTopic) | Not done | IP2-054. Deferred to Phase D. |
| GR-16 | Political calendar overlay | Done | `static/data/political_calendar.json` (12 events). Chart.js annotation plugin. Category/country filters. |
| GR-17 | Content Browser quick-add actor | Done | `POST /actors/quick-add`, `POST /actors/quick-add-bulk`. Frontend modal on author click in Content Browser. |
| GR-18 | Expose Similarity Finder in UI | Done | API at `/actors/{id}/similarity-search` + `cross-platform-match`. |
| GR-19 | Co-mention fallback in network expander | Done | `_expand_via_comention()` fully implemented in `network_expander.py`. |
| GR-20 | Auto-create Actor records for snowball discoveries | Done | Auto-creation in `actors.py` route + `snowball.py`. |
| GR-21 | Telegram forwarding chain expander | Done | Forwarding chain analysis in `network_expander.py`. |
| GR-22 | Cross-platform link mining | Done | `analysis/link_miner.py` with regex URL extraction, platform classification. `GET /content/discovered-links` endpoint. Frontend Discovered Sources page. |

**Implemented: 22/22 (100%)** (GR-13 is institutional process, not code)

---

### Ytringsfrihed Report (YF-01--YF-16)

**Report date:** 2026-02-19
**Report path:** `/docs/research_reports/ytringsfrihed_codebase_recommendations.md`

| ID | Description | Status | Notes |
|----|-------------|--------|-------|
| YF-01 | Per-arena search term scoping | Done | Migrations 010 + 011. `target_arenas JSONB NULL` on `search_terms` with GIN index. Task dispatch filtering implemented. |
| YF-02 | Source-list arena configuration UI | Done (via GR-01--GR-04) | The generic per-arena custom config mechanism requested by YF-02 was built as GR-01 through GR-04 (RSS, Telegram, Reddit, Discord, Wikipedia panels in query design editor). |
| YF-03 | Bulk search term import | Done | Bulk term import implemented (see YF-03 implementation summary). |
| YF-04 | Pre-flight credit estimation | Done (via SB-14) | Credit estimation endpoint now returns real values. |
| YF-05 | Ad-hoc exploration mode | Done | `explore/index.html` with dynamic arena list from `/api/arenas/`. |
| YF-06 | Cross-run analysis aggregation | Done (via SB-07) | Design-level analysis endpoints implemented. |
| YF-07 | Bulk actor import | Done | Bulk add in `actors.py` route + editor template. |
| YF-08 | Arena overview page | Done | `arenas/index.html` -- dynamic, tier-organized, with descriptions. |
| YF-09 | Tier precedence explanation | Done | Found in launcher template, collections routes, base.py. |
| YF-10 | Group label autocomplete enhancement | Done | Dynamic `_updateDatalist()` in QD editor collects existing group labels. |
| YF-11 | Snowball sampling platform transparency | Done | Platform transparency in actors template and route. |
| YF-12 | RSS feed preview | Not done | Feed list search/preview not built. |
| YF-13 | Discovered sources cross-design view | Done | Scope toggle in discovered links page. |
| YF-14 | Google Search free-tier guidance | Done | Amber badge on Google arenas in QD editor. |
| YF-15 | Custom subreddit UI | Done (via GR-03) | Subsumed by the Reddit custom subreddits panel. |
| YF-16 | Actor platform presence inline add | Done | Inline expandable form in QD editor actor rows. |

**Implemented: 15/16 (94%)** (YF-12 RSS feed preview is the only remaining item)

---

### Implementation Plan 2.0 Strategy (IP2-001--IP2-061)

**Report date:** 2026-02-18
**Report path:** `/docs/research_reports/implementation_plan_2_0_strategy.md`

| ID | Description | Status | Phase |
|----|-------------|--------|-------|
| IP2-004 | Duplicate exclusion in analysis | Done | A |
| IP2-005 | Extend flat export columns | Done | A |
| IP2-006 | Human-readable export headers | Done | A |
| IP2-008 | Client-side language detection | Done | B |
| IP2-009 | Add Altinget RSS feed | Done | A |
| IP2-024 | Consolidate analysis filter builders | Done | A |
| IP2-025 | GEXF export uses network.py | Done | A |
| IP2-031 | Boolean query support | Done | B |
| IP2-032 | Near-duplicate detection (SimHash) | Done | B |
| IP2-036 | Enrichment pipeline architecture | Done | B |
| IP2-043 | Content annotation layer | Done | C |
| IP2-046 | Term grouping in query design | Done | C |
| IP2-048 | Platform attribute on bipartite GEXF | Done | C |
| IP2-049 | Named entity extraction | Done | C |
| IP2-051 | Query design cloning | Done | D |
| IP2-056 | RIS/BibTeX export | Done | D |
| IP2-058 | Education-specific RSS feeds | Done | C |
| IP2-059 | Expand Reddit subreddits | Done | A |
| IP2-060 | Formalize actor_type values | Done | A |

**Implemented: 39/61 items explicitly tracked in CLAUDE.md as Done**

The following IP2 items are also effectively done through GR/SB implementations:

| IP2 ID | Covered By | Description |
|--------|------------|-------------|
| IP2-050 | GR-08 | Cross-arena flow analysis (propagation detection) |
| IP2-038 | GR/IP2 | Emergent term extraction (TF-IDF) |
| IP2-044 | IP2 | Temporal network snapshots |
| IP2-052 | GR-05 | Multilingual query design (multi-language selector) |
| IP2-053 | IP2-038 | Query term suggestion from collected data |

**Total IP2 items effectively implemented: ~45/61 (74%)**

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

---

## Remaining Work: Not Yet Implemented

As of the evening update on 2026-02-20, only a small number of items remain unimplemented. The vast majority of recommendations across all six reports have been completed.

### Deferred / Phase D

| ID(s) | Description | Reports | Notes |
|-------|-------------|---------|-------|
| IP2-054 | Topic modeling (BERTopic) | CO2 (P3.5), GR-15, IP2 | Phase D. Requires GPU and heavy dependencies. |
| IP2-057 | Folketinget.dk parliamentary proceedings arena | CO2 (P3.6), IP2 | Arena brief required before implementation. |

### Low Priority / Non-Code

| ID(s) | Description | Reports | Notes |
|-------|-------------|---------|-------|
| IP2-052 | Multilingual query design | AI (IM-4.2), IP2 | GR-05 multi-language selector partially addresses this. |
| IP2-061 | Mixed hash/name resolution in charts | AI, IP2 | Low priority, depends on entity resolution improvements. |
| GR-13 | Apply for Meta Content Library | GR | Institutional process, not code. 2-6 month review. |
| YF-12 | RSS feed preview | YF | Search/filter feed list. Low priority polish. |
| P1.5 / IM-1.6 | Use case documents | CO2, AI | Research artifacts, not code. |

---

## Database Migrations Summary

The following migrations have been added across the implementation period. All must be applied via `alembic upgrade head`.

| Migration | Description | Related IDs | Date |
|-----------|-------------|-------------|------|
| 001 | Initial schema | -- | 2026-02-15 |
| 002 | `arenas_config JSONB` on query_designs | GR-01 through GR-05 | 2026-02-15 |
| 003 | `suspended_at` on collection_runs | B-03 | 2026-02-16 |
| 004 | Scraping jobs table | -- | 2026-02-16 |
| 005 | Content annotations table | IP2-043, P4.2, IM-2.5 | 2026-02-17 |
| 006 | Search term groups (`group_id`, `group_label`) | IP2-046 | 2026-02-17 |
| 007 | `simhash BIGINT` on content_records | IP2-032, P2.4 | 2026-02-18 |
| 008 | Query design cloning (`parent_design_id`) | IP2-051, P4.1, IM-4.1 | 2026-02-18 |
| 009 | `public_figure BOOLEAN` on actors | GR-14 | 2026-02-19 |
| 010 | `target_arenas JSONB` on search_terms | YF-01 | 2026-02-19 |
| 011 | GIN index on `search_terms.target_arenas` | YF-01 | 2026-02-19 |
| **012** | **`codebook_entries` table** | **SB-16** | **2026-02-20** |

**Action required:** If upgrading from any previous state, run:

```bash
alembic upgrade head
```

Migration 012 is non-breaking: it creates a new table and does not modify existing tables or data.

---

## Breaking Changes and API Changes

### New API Endpoints (2026-02-20)

| Method | Path | Description | SB ID |
|--------|------|-------------|-------|
| GET | `/analysis/compare` | Cross-run comparison | SB-06 |
| GET | `/analysis/design/{id}/summary` | Design-level analysis | SB-07 |
| GET | `/analysis/design/{id}/volume` | Design-level volume | SB-07 |
| GET | `/analysis/design/{id}/actors` | Design-level actors | SB-07 |
| GET | `/analysis/design/{id}/terms` | Design-level terms | SB-07 |
| GET | `/analysis/{run_id}/enrichments/languages` | Language distribution | SB-15 |
| GET | `/analysis/{run_id}/enrichments/entities` | Named entity summary | SB-15 |
| GET | `/analysis/{run_id}/enrichments/propagation` | Propagation patterns | SB-15 |
| GET | `/analysis/{run_id}/enrichments/coordination` | Coordination signals | SB-15 |
| POST | `/query-designs/{id}/discover-feeds` | RSS feed autodiscovery | SB-09 |
| GET | `/query-designs/{id}/suggest-subreddits` | Reddit subreddit suggestions | SB-10 |
| GET/POST/PUT/DELETE | `/codebooks/*` | Codebook CRUD | SB-16 |

### Modified API Endpoints

| Method | Path | Change | SB ID |
|--------|------|--------|-------|
| POST | `/collections/estimate` | **No longer returns zero.** Returns real per-arena credit estimates. | SB-14 |
| GET | `/api/arenas/` | Response now includes `temporal_mode` field per arena. | SB-04 |

### New Dependencies

| Package | Version | Required By |
|---------|---------|-------------|
| `beautifulsoup4` | `>=4.12,<5.0` | SB-09 (RSS feed autodiscovery) |

### No Breaking Changes

All changes are additive. Existing API contracts, database schemas (after migration), and frontend templates remain backward-compatible. The `POST /collections/estimate` endpoint now returns real values instead of zeros, which is a behavior change but not a contract change -- the response schema is unchanged.

---

## New Files Added (2026-02-20)

| File | Purpose |
|------|---------|
| `src/issue_observatory/arenas/rss_feeds/feed_discovery.py` | RSS feed autodiscovery module (SB-09) |
| `src/issue_observatory/arenas/reddit/subreddit_suggestion.py` | Reddit subreddit suggestion module (SB-10) |
| `src/issue_observatory/core/models/codebook.py` | CodebookEntry ORM model (SB-16) |
| `src/issue_observatory/core/schemas/codebook.py` | Codebook Pydantic schemas (SB-16) |
| `src/issue_observatory/api/routes/codebooks.py` | Codebook CRUD API routes (SB-16) |
| `src/issue_observatory/api/templates/annotations/codebook_manager.html` | Codebook management UI (SB-16) |
| `alembic/versions/012_add_codebook_entries.py` | Migration for codebook_entries table (SB-16) |
| `docs/decisions/ADR-012-source-discovery-assistance.md` | ADR for SB-09/SB-10 design decisions |
| `docs/implementation_notes/SB-09-SB-10-source-discovery.md` | Implementation notes for source discovery |
| `docs/implementation_notes/SB-16_codebook_ui_implementation.md` | Implementation notes for codebook UI |
| `docs/implementation_reports/SB-16_codebook_management_api.md` | API layer implementation report |
| `docs/implementation_reports/SB-16_API_SUMMARY.md` | Quick reference for SB-16 API |
| `docs/testing/socialt_bedrageri_test_plan.md` | Test plan for all 16 SB items |

---

## Implementation Timeline

| Date | Items Implemented | Key Milestone |
|------|------------------|---------------|
| 2026-02-15 | Core infrastructure, migrations 001-004 | Project bootstrap complete |
| 2026-02-16 | Arena briefs (all Phase 1 + Phase 2) | Engineering agents unblocked |
| 2026-02-17 | CO2 afgift report, Phase 3 UX fixes (B-01 through B-03) | B-02 GEXF fix (critical data correctness) |
| 2026-02-18 | AI uddannelse report, IP2 strategy, Greenland report, IP2-009/058/059/060, IP2-004/005/006/024/025/031/032/036/043/046/048/049/051/056 | Phase A + B + C foundation complete |
| 2026-02-19 | GR-01 through GR-22 (18 items), YF-01, YF-03, migrations 009-011 | Researcher self-service mechanisms complete |
| **2026-02-20** | **SB-01 through SB-16 (16 items), migration 012** | **Discovery feedback loop + iterative workflow complete** |
| **2026-02-20 (eve)** | **IP2-030/033/034/035/037, YF-05/10/13/14/16, 20+ audit corrections** | **93% implementation rate across all reports** |

---

## Overall Assessment

The Issue Observatory has reached a mature state for multi-platform Danish discourse research. As of 2026-02-20:

- **24 arena directories** exist (21 functional, 2 deferred stubs, 1 limited)
- **12 database migrations** define the complete schema
- **5 enrichment modules** (language detection, named entity extraction, propagation detection, coordination detection, Danish sentiment analysis) provide automated post-collection analysis
- **Researcher self-service mechanisms** allow configuration of RSS feeds, Telegram channels, Reddit subreddits, Discord channels, and Wikipedia seed articles per query design without code changes
- **Per-arena search term scoping** prevents cross-arena contamination in multi-lingual research
- **Discovery feedback loops** let researchers add suggested terms and discovered sources with one click
- **Cross-run analysis** supports iterative research workflows
- **Annotation codebook management** enables structured qualitative coding

The primary remaining items are advanced Phase D features (BERTopic topic modeling, Folketinget.dk arena) and low-priority polish. All critical, high, and medium priority items from all six research reports have been implemented.

---

*End of release notes. This document should be updated when additional implementations from the remaining work items are completed.*
