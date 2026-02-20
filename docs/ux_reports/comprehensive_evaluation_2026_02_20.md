# Comprehensive Evaluation Report: The Issue Observatory

**Date:** 2026-02-20
**Evaluators:** QA Guardian (x3), UX Tester (x2), Research Strategist
**Scope:** Full application evaluated against `/docs/application_description.md`
**Method:** Read-only code audit across 6 parallel evaluation streams

---

## Executive Summary

The Issue Observatory is a substantial and largely well-implemented application. The 21 arena collectors, universal content record schema, analysis module, and export pipeline are fundamentally sound. However, the evaluation uncovered **13 CRITICAL issues**, **21 MAJOR issues**, and **23 MINOR issues** across the codebase. The most concerning patterns are:

1. **Broken integration points** -- several features are individually implemented but not wired together (codebook-annotation link, enrichment JSONB key mismatches, bulk import schema mismatches)
2. **Wrong URL prefixes** -- templates reference `/api/collections/` when routes are mounted at `/collections/`, breaking SSE monitoring and cancel functionality
3. **Runtime failures in maintenance code** -- the engagement refresh task references non-existent columns and calls instance methods on classes
4. **Stale code** -- commented-out integration code with incorrect FIXME comments, hardcoded arena lists that haven't kept pace with new collectors

---

## CRITICAL Issues (13 total)

These cause runtime failures, complete feature breakage, or data corruption.

### Infrastructure & Backend (3)

| # | Description | File | Fix |
|---|-------------|------|-----|
| **C-INF-1** | `maintenance_tasks.py` references non-existent `external_id` column (should be `platform_id`) -- engagement refresh task crashes with `UndefinedColumn` | `workers/maintenance_tasks.py:350-433` | Replace `external_id` with `platform_id` |
| **C-INF-2** | `get_arena()` returns a class, but code calls `collector.refresh_engagement()` as if it's an instance -- `TypeError` at runtime | `workers/maintenance_tasks.py:396-420` | Instantiate: `collector = get_arena(name)()` |
| **C-INF-3** | `get_arena()` raises `KeyError` on unknown platform, but code checks `if collector is None:` -- unhandled `KeyError` crash | `workers/maintenance_tasks.py:396-400` | Use try/except `KeyError` |

### Enrichment Pipeline (4)

| # | Description | File | Fix |
|---|-------------|------|-----|
| **C-ENR-1** | Language distribution query reads `enrichments.language_detector` but enricher writes to `enrichments.language_detection` -- always returns empty | `analysis/descriptive.py:1273-1277` | Fix JSONB key path |
| **C-ENR-2** | NER entities query reads `enrichments.named_entity_extractor` but enricher writes to `enrichments.actor_roles` -- always returns empty | `analysis/descriptive.py:1343-1346` | Fix JSONB key path |
| **C-ENR-3** | Propagation query reads `enrichments.propagation_detector` with fields `story_id`/`propagated` but enricher writes `enrichments.propagation` with `cluster_id`/`is_origin` -- 3 errors in one query | `analysis/descriptive.py:1404-1415` | Fix JSONB key + field names |
| **C-ENR-4** | Coordination query reads `enrichments.coordination_detector` with field `coordinated` but enricher writes `enrichments.coordination` with `flagged` -- always returns empty | `analysis/descriptive.py:1478-1487` | Fix JSONB key + field names |

### Frontend (4)

| # | Description | File | Fix |
|---|-------------|------|-----|
| **C-FE-1** | SSE live monitoring uses `/api/collections/{id}/stream` -- routes are at `/collections/`, so SSE gets 404. **Live collection monitoring is completely broken.** | `templates/collections/detail.html:81` | Remove `/api` prefix |
| **C-FE-2** | Cancel buttons use `/api/collections/{id}/cancel` -- same prefix error. **Researchers cannot cancel any running collection.** | `templates/collections/detail.html:179,222` | Remove `/api` prefix |
| **C-FE-3** | Duplicate Jinja2 block structure in editor template (lines 764-786 duplicate lines 756-763, with orphaned `{% endfor %}` and out-of-scope `{{ actor.id }}`). **Query design editor will throw TemplateSyntaxError.** | `templates/query_designs/editor.html:756-786` | Remove duplicate block |
| **C-FE-4** | Actor type badge checks `'organisation'` (British) but DB stores `"organization"` (American). **All organization-type actors display as "Account".** | `templates/actors/list.html:260` | Fix spelling to `'organization'` |

### Integration (2)

| # | Description | File | Fix |
|---|-------------|------|-----|
| **C-INT-1** | Codebook-annotation integration code is commented out with stale FIXME ("model doesn't exist" -- it does). Sends HTTP 501. **Codebook-based annotation is non-functional.** | `routes/annotations.py:271-312` | Uncomment code, remove 501 |
| **C-INT-2** | Discovered Sources bulk import sends `{sources: [...]}` wrapper with `platform_username` field, but backend expects bare `list[QuickAddBulkItem]` with `target_identifier` field. **Bulk import always fails.** | `templates/content/discovered_links.html:893-921` vs `routes/actors.py:932-1022` | Align payload schema |

---

## MAJOR Issues (21 total)

These cause significant feature degradation or incorrect behavior.

### Backend Logic (7)

| # | Description | File |
|---|-------------|------|
| M-BE-1 | Duplicate `NoCredentialAvailableError` with different base classes (`Exception` vs `IssueObservatoryError`) -- Threads arena errors escape app-level handlers | `core/credential_pool.py:75` vs `core/exceptions.py:94` |
| M-BE-2 | Duplicate `Tier` enum in two locations -- identity comparison fails | `arenas/base.py:38` vs `config/tiers.py:26` |
| M-BE-3 | `get_tier_config()` ABC declares `-> dict` but implementations return `TierConfig \| None` | `arenas/base.py:230` |
| M-BE-4 | Telegram `collect_by_terms` adds non-standard parameters breaking ABC interface | `arenas/telegram/collector.py:123` |
| M-BE-5 | X/Twitter `normalize()` adds non-standard `tier_source` parameter | `arenas/x_twitter/collector.py:278` |
| M-BE-6 | 23 files use deprecated `datetime.utcnow()` (Python 3.12+) | Across 23 files |
| M-BE-7 | 10 arenas misuse `platform="bluesky"` for generic query formatting, silently dropping multi-group boolean queries | 10 collector files |

### Analysis & Export (3)

| # | Description | File |
|---|-------------|------|
| M-AN-1 | `get_run_summary()` JOIN inflates per-arena record counts (N*M multiplication) | `analysis/descriptive.py:1587-1607` |
| M-AN-2 | `engagement_score` missing from `_FLAT_COLUMNS` -- silently dropped from all CSV/XLSX/Parquet exports | `analysis/export.py:52-72` |
| M-AN-3 | `pseudonymized_author_id` column is `String(64)` -- sufficient for SHA-256 hashes but truncates plain usernames stored for public figures (GR-14 bypass) | `core/models/content.py:163-166` |

### Frontend & Routes (8)

| # | Description | File |
|---|-------------|------|
| M-FE-1 | Credit estimate in QD editor: wrong path (`/api/collections/`) AND wrong method (`GET` vs `POST`) | `templates/query_designs/editor.html:806` |
| M-FE-2 | Credits route module is an empty stub -- no API endpoints | `routes/credits.py` |
| M-FE-3 | 3 arena routers not mounted in main.py (wikipedia, discord, url_scraper) | `api/main.py:219-299` |
| M-FE-4 | Content browser arena filter hardcoded to 11 of 21+ arenas | `templates/content/browser.html:73-85` |
| M-FE-5 | Missing `GET /content/search-terms` endpoint -- search term filter in content browser is non-functional | `templates/content/browser.html:171` |
| M-FE-6 | `analysis.py` uses `design.created_by` but QueryDesign uses `owner_id` -- AttributeError on all design-level analysis | `routes/analysis.py:1530` |
| M-FE-7 | Actor type badges handle only 3 of 11 types -- 8 types display as "Account" | `templates/actors/list.html:257-266` |
| M-FE-8 | Content browser missing `content_type` filter (described in application description) | `templates/content/browser.html` |

### Actor & Discovery (3)

| # | Description | File |
|---|-------------|------|
| M-AD-1 | Telegram omitted from snowball sampling platforms despite backend support | `routes/actors.py:73` |
| M-AD-2 | Entity resolution split operation has no UI (backend endpoint exists) | `templates/actors/resolution.html` |
| M-AD-3 | Quick-add modal uses non-canonical actor type values ("Individual", "Bot") instead of enum values ("person") | `templates/content/discovered_links.html:610-615` |

---

## MINOR Issues (23 total)

| # | Category | Description | File |
|---|----------|-------------|------|
| m-1 | Documentation | CLAUDE.md references `external_id` but model uses `platform_id` | CLAUDE.md |
| m-2 | Documentation | `content_records` lacks `updated_at` despite TimestampMixin claim | CLAUDE.md |
| m-3 | Documentation | `dkpolitik` not in central `danish_defaults.py` (only in arena-specific extras) | `config/danish_defaults.py` |
| m-4 | Documentation | Right-to-erasure only works for entity-resolved content | `core/retention_service.py` |
| m-5 | Documentation | Stale "BACKEND GAP" comments in 4+ templates for resolved issues | Multiple templates |
| m-6 | Documentation | Application description says "versioned specification" but no version field exists | Conceptual gap |
| m-7 | Code quality | RSS collector writes `arena="news_media"` but registers as `"rss_feeds"` | `arenas/rss_feeds/collector.py` |
| m-8 | Code quality | YouTube `collect_by_terms` never releases credential (resource leak on error) | `arenas/youtube/collector.py:161` |
| m-9 | Code quality | YouTube `collect_by_actors` same credential leak issue | `arenas/youtube/collector.py:261` |
| m-10 | Code quality | AI Chat Search `normalize()` always raises `NotImplementedError` (LSP violation) | `arenas/ai_chat_search/collector.py:283` |
| m-11 | Code quality | `credential_pool.release()` called with extra `platform` kwarg | `arenas/google_search/collector.py:336` |
| m-12 | Code quality | `SentimentAnalyzer` docstring thresholds don't match code thresholds | `analysis/enrichments/sentiment_analyzer.py:38-39` |
| m-13 | Code quality | `NamedEntityExtractor.enrich()` always returns stub data (raises ImportError) | `analysis/enrichments/named_entity_extractor.py:93-99` |
| m-14 | Code quality | `propagation.py` doesn't use shared `_filters.py` duplicate exclusion | `analysis/propagation.py:117-137` |
| m-15 | Code quality | `coordination.py` doesn't use shared `_filters.py` duplicate exclusion | `analysis/coordination.py:113-141` |
| m-16 | Code quality | Temporal network `_fetch_actor_temporal_rows()` doesn't scope b-side to same run | `analysis/network.py:839-853` |
| m-17 | Code quality | BibTeX `_LATEX_ESCAPE` backslash replacement ordering corrupts output | `analysis/export.py:1162-1179` |
| m-18 | Frontend | Inconsistent template resolution patterns across route modules | Multiple route files |
| m-19 | Frontend | Vestigial empty chart section headers in charts.js | `static/js/charts.js:282-295` |
| m-20 | Frontend | Duplicate `collectionLauncher` definition in app.js and template | `static/js/app.js:60-106` |
| m-21 | Frontend | Dead `queryEditor` definition in app.js | `static/js/app.js:115-128` |
| m-22 | Frontend | LinkedIn in platform presence dropdown despite being unsupported | `templates/query_designs/editor.html:728` |
| m-23 | Frontend | Discovered sources platform filter missing Twitter, Instagram, TikTok options | `templates/content/discovered_links.html:214-226` |

---

## What Works Well

Despite the issues above, the vast majority of the application is correctly implemented:

- **All 21 arena collectors** implement the pattern correctly (register, collect_by_terms, normalize)
- **Danish locale defaults** are centralized and correctly applied across all arenas (Google gl=dk/hl=da, YouTube relevanceLanguage=da/regionCode=DK, Bluesky lang:da, GDELT sourcelang:danish/sourcecountry:DA, Event Registry dan, X/Twitter lang:da, Reddit 6+ Danish subreddits, Via Ritzau language=da, 38 curated RSS feeds)
- **SHA-256 pseudonymization** with configurable salt and public figure bypass works correctly
- **Boolean term groups** with AND/OR logic, per-arena term scoping, and group labels
- **All 7 export formats** are implemented (CSV with UTF-8 BOM, XLSX, NDJSON, Parquet, GEXF, RIS, BibTeX)
- **All 3 network analysis types** (actor co-occurrence, term co-occurrence, bipartite)
- **Temporal network snapshots** for discourse evolution tracking
- **Deduplication pipeline** (URL, content hash, SimHash near-duplicate) works correctly
- **Engagement score normalization** (0-100 scale with platform-specific weights)
- **Query design cloning** with parent lineage
- **Snowball sampling** for Bluesky, Reddit, YouTube with provenance tracking
- **Entity resolution** merge workflow with trigram similarity detection
- **Content annotation** with stance vocabulary (positive, negative, neutral, contested, irrelevant)
- **SSE event bus** architecture (the infrastructure works -- only the template URL is wrong)
- **Multi-language support** via arenas_config["languages"]
- **Codebook CRUD** (create, read, update, delete codebook entries -- only the annotation integration is broken)
- **Credit service** (balance, reservation, settlement, refund, estimation -- only the REST API surface is missing)
- **Actor type taxonomy** (11 types, exceeding the 7 described)
- **38 curated RSS feeds** (exceeds the "28+" claim)
- **Per-arena term scoping** via target_arenas JSONB with GIN index
- **Configurable source lists** for Telegram, Reddit, RSS, Discord, Wikipedia
- **Cross-run comparison** endpoint
- **Design-level analysis aggregation**
- **Suggested terms** (TF-IDF emergent term extraction)
- **Propagation detection** enrichment
- **Coordination detection** enrichment
- **Volume spike alerting** (threshold-based, 7-day rolling average)
- **Discovered sources** with platform classification and one-click addition
- **RSS feed autodiscovery** and Reddit subreddit suggestion

---

## Recommended Fix Priority

### Priority 1 -- Immediate (blocks core workflows)

1. **C-FE-1 + C-FE-2**: Fix `/api/collections/` to `/collections/` in `collections/detail.html` (3 line changes -- restores SSE monitoring and cancel)
2. **C-FE-3**: Remove duplicate template block in `query_designs/editor.html` lines 764-786 (restores query design editor)
3. **C-ENR-1 through C-ENR-4**: Fix 4 JSONB key paths in `analysis/descriptive.py` (restores entire enrichment dashboard)
4. **C-INT-1**: Uncomment codebook integration in `annotations.py` (connects two working systems)
5. **C-FE-4**: Fix `'organisation'` to `'organization'` in `actors/list.html`

### Priority 2 -- High (significant feature gaps)

6. **C-INF-1 through C-INF-3**: Fix `maintenance_tasks.py` (restores engagement refresh)
7. **C-INT-2**: Align bulk import payload schema between frontend and backend
8. **M-FE-6**: Change `design.created_by` to `design.owner_id` in `analysis.py` (restores design-level analysis)
9. **M-AN-2**: Add `engagement_score` to export columns
10. **M-FE-1**: Fix credit estimate path and method in `editor.html`
11. **M-FE-4 + M-FE-5**: Dynamic arena filter list + search-terms endpoint in content browser

### Priority 3 -- Medium (architecture cleanup)

12. **M-BE-1**: Deduplicate `NoCredentialAvailableError`
13. **M-BE-2**: Deduplicate `Tier` enum
14. **M-BE-6**: Replace 23 `datetime.utcnow()` calls with `datetime.now(timezone.utc)`
15. **M-FE-3**: Mount missing arena routers (wikipedia, discord, url_scraper)
16. **M-AD-1**: Add Telegram to snowball sampling platforms
17. **M-AN-3**: Widen `pseudonymized_author_id` column for public figure bypass

### Priority 4 -- Low (polish and cleanup)

18. Remove stale "BACKEND GAP" comments across templates
19. Fix actor type badge display to handle all 11 types (M-FE-7)
20. Fix quick-add modal actor type values to use canonical enum (M-AD-3)
21. Add entity resolution split UI (M-AD-2)
22. Clean up vestigial JS code (m-19, m-20, m-21)
23. Fix BibTeX escape ordering (m-17)
24. Add credential release `finally` blocks to YouTube collector (m-8, m-9)
25. Implement credits REST API endpoints (M-FE-2)
26. Update CLAUDE.md `external_id` reference to `platform_id` (m-1)

---

## Evaluation Stream Details

This report synthesizes findings from six parallel evaluation agents:

1. **QA Guardian -- Core Infrastructure Audit**: Arena base class, registry, normalizer, credential pool, 8 arena collectors, workers, exceptions. Found 3 CRITICAL, 7 MAJOR, 7 MINOR.
2. **UX Tester -- Research Workflow Evaluation**: Query design editor, collection launcher, SSE monitoring, content browser. Found 1 critical architecture pattern, 2 MAJOR, 9 MINOR gaps.
3. **Research Strategist -- Compliance and Danish Defaults**: GDPR pseudonymization, retention service, Danish locale defaults, multi-language support, ethical features. Found 0 CRITICAL, 2 MAJOR, 2 MINOR.
4. **QA Guardian -- Analysis, Export, Enrichment Audit**: Analysis module, 7 export formats, 5 enrichers, analysis routes. Found 4 CRITICAL, 5 MAJOR, 7 MINOR.
5. **UX Tester -- Actor Management and Discovery**: Actor directory, snowball sampling, entity resolution, discovered sources, quick-add. Found 2 CRITICAL, 5 MAJOR, 1 MINOR.
6. **QA Guardian -- Frontend Templates and Routes**: 13+ route modules, 39 templates, 3 JS files, main app assembly. Found 4 CRITICAL, 7 MAJOR, 8 MINOR.

Individual agent reports are available in the agent output files. The UX workflow report was also written to `/docs/ux_reports/workflow_code_review_report.md`.
