# Implementation Plan 2.0 -- Strategic Synthesis

**Author:** Research & Knowledge Agent (The Strategist)
**Date:** 2026-02-18
**Status:** Final
**Scope:** Unified prioritized implementation roadmap synthesizing findings from both UX test cases (CO2 afgift discourse tracking and AI og uddannelse issue mapping) and their corresponding codebase evaluations

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-18 | Initial strategic synthesis. Cross-referencing 4 input reports with 36 friction points, 5 blockers, 10 data quality findings, and 42+ improvement recommendations. |

---

## Table of Contents

1. [Cross-Case Findings Synthesis](#1-cross-case-findings-synthesis)
2. [Methodology-Aware Prioritization](#2-methodology-aware-prioritization)
3. [Unified Improvement Roadmap](#3-unified-improvement-roadmap)
4. [Implementation Phases](#4-implementation-phases)
5. [Dependency Graph](#5-dependency-graph)
6. [Cost-Benefit Analysis](#6-cost-benefit-analysis)
7. [Tier and Arena Strategy](#7-tier-and-arena-strategy)

---

## Source Documents

| ID | Document | Path |
|----|----------|------|
| UX-CO2 | UX Test Report: CO2 Afgift Discourse Mapping | `/docs/ux_reports/co2_afgift_mapping_report.md` |
| CB-CO2 | Codebase Evaluation: CO2 Afgift | `/docs/research_reports/co2_afgift_codebase_recommendations.md` |
| UX-AI | UX Test Report: AI og uddannelse Issue Mapping | `/docs/ux_reports/ai_uddannelse_mapping_report.md` |
| CB-AI | Codebase Evaluation: AI og uddannelse | `/docs/research_reports/ai_uddannelse_codebase_recommendations.md` |

---

## 1. Cross-Case Findings Synthesis

### 1.1 Problems That Appeared in BOTH Test Cases (Systemic -- Highest Priority)

These findings surfaced in both the CO2 afgift and AI og uddannelse evaluations. They are structural problems that affect any research use of the system, regardless of topic or methodology.

| Problem | CO2 Afgift Finding IDs | AI og Uddannelse Finding IDs | Nature |
|---------|----------------------|---------------------------|--------|
| Arena grid hardcoded, missing 8+ implemented arenas | FP-10, FP-11, B-01 (UX-CO2); P1 (CB-CO2) | IM-11, IM-B03 (UX-AI) | Frontend + Core |
| Arena tier options misleading (free-only arenas show medium/premium) | FP-09 (UX-CO2) | IM-10 (UX-AI) | Frontend |
| No arena descriptions in configuration grid | FP-13 (UX-CO2) | IM-13 (UX-AI) | Frontend |
| Query design actors disconnected from Actor Directory | FP-07 (UX-CO2) | IM-08, IM-24, IM-B01 (UX-AI) | Frontend + Core |
| No term type explanations (Keyword/Phrase/Hashtag) | FP-04 (UX-CO2) | IM-05 (UX-AI) | Frontend |
| Query design detail page omits arena configuration | FP-15 (UX-CO2) | IM-15 (UX-AI) | Frontend |
| Dashboard and System Status show stale "Phase 0" text | FP-01, FP-02, FP-36 (UX-CO2) | IM-01 (UX-AI) | Frontend |
| Arena column hidden below xl breakpoint in content browser | FP-21 (UX-CO2) | IM-18 (UX-AI) | Frontend |
| Engagement score unexplained, not comparable cross-platform | FP-22 (UX-CO2); P2.2 (CB-CO2) | IM-21 (UX-AI) | Frontend + Research |
| Analysis charts have no axis labels | FP-30 (UX-CO2) | IM-29 (UX-AI) | Frontend |
| Analysis filter bar uses free-text instead of dropdowns | FP-31 (UX-CO2) | IM-30 (UX-AI) | Frontend |
| Export column headers use snake_case | FP-33 (UX-CO2); P1.3 (CB-CO2) | IM-37 (UX-AI); Gap 4 (CB-AI sec 6.2) | Data |
| No in-browser network preview | FP-32 (UX-CO2) | IM-31 (UX-AI); Gap 1 (CB-AI sec 6.2) | Frontend |
| Snowball sampling panel collapsed, low discoverability | FP-27 (UX-CO2) | IM-25 (UX-AI) | Frontend |
| "Celery Beat" developer jargon in live mode description | FP-16 (UX-CO2) | IM-17 (UX-AI) | Frontend |
| Timestamps lack timezone information | FP-25 (UX-CO2) | IM-22 (UX-AI) | Frontend |
| No boolean query logic in SearchTerm model | P2.3 (CB-CO2) | Gap 1 (CB-AI sec 4.3) | Core + DB |
| Duplicate-marked records counted in analysis | P1.2 (CB-CO2); TD-4 (CB-CO2) | IM-1.4, TD-4 (CB-AI) | DB |
| Missing columns in flat export (pseudonymized_author_id, content_hash, etc.) | P1.3 (CB-CO2); Gap 1 (CB-CO2 sec 8.2) | IM-1.5 (CB-AI); Gap 4 (CB-AI sec 6.2) | DB |
| No client-side Danish language detection fallback | P2.1 (CB-CO2); Gap 1 (CB-CO2 sec 7.2) | IM-2.4 (CB-AI); Gap 1 (CB-AI sec 7) | Core |
| No enrichment pipeline architecture | TD-4 (CB-CO2) | TD-3 (CB-AI) | Core |
| Filter construction duplicated across descriptive.py and network.py | TD-2 (CB-CO2) | TD-1 (CB-AI) | DB |
| GEXF export reconstructs networks from records instead of using network.py | TD-3 (CB-CO2) | TD-2 (CB-AI) | DB |
| Altinget.dk missing from RSS feed list | Gap (CB-CO2 sec 3.2) | Gap (CB-AI sec 3.3) | Research |
| LinkedIn coverage gap (no automated collection) | Gap (CB-CO2 sec 3.2) | Gap (CB-AI sec 3.3) | Research |
| Admin credential form missing platforms | B-02 (Phase 3); B-04 (Phase 3) | -- | Frontend |
| Date range guidance absent in collection launcher | FP-17 (UX-CO2) | IM-16 (UX-AI) | Frontend + Research |
| Tier precedence ambiguity (query design vs. launcher) | FP-18 (UX-CO2) | -- | Frontend + Core |
| Mixed language "termer" in English UI | FP-05 (UX-CO2) | IM-07 (UX-AI) | Frontend |
| Collection detail header shows UUID not query design name | FP-20 (UX-CO2) | -- | Frontend |
| No success confirmation after saving arena config | FP-14 (UX-CO2) | -- | Frontend |

### 1.2 Problems Unique to Discourse Tracking (CO2 Afgift)

These issues surfaced primarily in the CO2 afgift scenario, where the research question involves known terms, known actors, and longitudinal volume/engagement tracking.

| Problem | Finding IDs | Nature |
|---------|------------|--------|
| No sentiment or stance indicators in schema | Critical #2 (CB-CO2) | Core + DB |
| No temporal comparison or trend detection (period-over-period, event annotation) | Critical #3, Gap 3 (CB-CO2 sec 6.2) | DB |
| Near-duplicate detection absent (wire service lightly-edited articles) | P2.4 (CB-CO2); Gap (CB-CO2 sec 5.2) | DB |
| Engagement metrics write-once, no refresh mechanism | TD-6 (CB-CO2) | Core |
| Engagement score column unpopulated (normalization formula absent) | P2.2, P2.6 (CB-CO2) | DB |
| No cross-arena narrative flow tracking | Critical #4 (CB-CO2); Gap 4 (CB-CO2 sec 6.2) | DB + Research |
| Reddit subreddit list too narrow (r/dkfinance missing for CO2 afgift) | DQ-04 (UX-CO2) | Research |
| Jyllands-Posten RSS availability uncertain | DQ-01 (UX-CO2) | Research |
| Folketinget.dk parliamentary proceedings not covered | Gap (CB-CO2 sec 3.2) | Research |
| No RIS/BibTeX export for academic citation | P4.4 (CB-CO2) | DB |
| Credit estimate endpoint ("...") may not resolve | FP-12 (UX-CO2) | Frontend + Core |
| Content browser "Search" vs "Search Term" filter confusion | FP-23 (UX-CO2) | Frontend |
| Language filter missing Norwegian/Swedish/Unknown options | FP-24 (UX-CO2) | Frontend |
| NDJSON export mislabelled as "JSON" | FP-34 (UX-CO2) | Frontend |
| Parquet format unexplained | FP-35 (UX-CO2) | Frontend |

### 1.3 Problems Unique to Issue Mapping (AI og uddannelse)

These issues surfaced in the Marres-style issue mapping scenario, which demands explorative discovery, actor-centric analysis, and network visualization.

| Problem | Finding IDs | Nature |
|---------|------------|--------|
| No emergent term/topic extraction from collected text | Critical #1, Gap 1 (CB-AI sec 5); DQ-01 (UX-AI); IM-34 (UX-AI) | Core + DB |
| No actor role classification (speaker vs. mentioned vs. quoted) | Critical #2, Gap (CB-AI sec 2.1) | Core + DB |
| No controversy detection (co-occurrence conflates agreement and disagreement) | Critical #4 (CB-AI); sec 2.5 (CB-AI) | Research + Core |
| Bipartite network limited to pre-defined search terms, not extracted topics | Critical #6, Gap 3 (CB-AI sec 5) | DB |
| No temporal network analysis (static snapshots only) | Critical #5, Gap 5 (CB-AI sec 5) | DB |
| No cross-arena flow analysis (which arena breaks stories first) | Gap 6 (CB-AI sec 5) | DB + Research |
| No annotation/coding layer for qualitative research | Gap 4 (CB-AI sec 5); IM-2.5 (CB-AI) | DB + Frontend |
| No entity resolution UI | IM-B02 (UX-AI); IM-36 (UX-AI) | Frontend + Core |
| No term grouping/categorization within query design | IM-06 (UX-AI); R-10 (UX-AI) | Frontend + Research |
| No multilingual query design (cannot select "Danish + English") | IM-04 (UX-AI) | Frontend + Core |
| No per-arena GEXF export | IM-39 (UX-AI); R-12 (UX-AI) | DB + Frontend |
| Bipartite GEXF lacks platform attribute on actor nodes | IM-35 (UX-AI); R-09 (UX-AI) | Data |
| get_top_actors() groups by platform, fragmenting cross-platform actors | TD-5 (CB-AI) | DB |
| Snowball sampling results lack discovery path explanation | IM-28 (UX-AI) | Frontend + Research |
| Quick Actions panel not oriented toward issue mapping workflow | IM-02 (UX-AI) | Frontend |
| No query design versioning or cloning | Gap 2 (CB-AI sec 4.3); IM-4.1 (CB-AI) | DB + Frontend |
| Mixed readable names and hash IDs in Top Actors chart | IM-32 (UX-AI) | Frontend + Core |
| Record detail panel lacks "Related records" cross-reference | IM-23 (UX-AI) | Frontend + Research |
| No query term suggestion from collected data | Gap 5 (CB-AI sec 4.3) | DB |
| AI Chat Search arena invisible despite unique value for AI topic | IM-11, IM-12 (UX-AI) | Frontend |
| No dynamic GEXF export (temporal attributes for Gephi Timeline) | Gap 2 (CB-AI sec 6.2) | DB |
| Education-specific RSS feeds missing (Folkeskolen.dk, university news) | Gap (CB-AI sec 3.3) | Research |

### 1.4 What Worked Well in Both Cases (Preserve and Build On)

The following capabilities received positive assessments in both test cases and should be maintained:

| Strength | Evidence |
|----------|----------|
| Danish locale defaults are comprehensive and correct | P-05 (UX-CO2); IM-P09 (UX-AI); sec 7.1 (CB-CO2); sec confirmed (CB-AI) |
| GEXF network exports now support all three types (actor, term, bipartite) | P-02, P-03 (UX-CO2); IM-P04 through IM-P08 (UX-AI) |
| Content record detail panel is researcher-friendly | P-06 (UX-CO2); IM-P01, IM-P02, IM-P03 (UX-AI) |
| Matched search terms displayed as badges -- directly useful for both methodologies | P-06 (UX-CO2); IM-P01 (UX-AI) |
| Live tracking schedule with suspend/resume controls | P-04 (UX-CO2) |
| Snowball sampling panel exists (though low discoverability) | P-01 (UX-CO2); noted in UX-AI |
| Content browser filter system with arena checkboxes and debounced auto-submit | P-09 (UX-CO2); IM-P10 (UX-AI) |
| Export panel supports 5 formats including async export for large datasets | P-07 (UX-CO2) |
| Query design editor supports rapid inline term and actor entry | P-08 (UX-CO2) |
| Modular arena architecture enables clean addition of new arenas | sec 10.1 (CB-CO2) |
| Universal content record with monthly range partitioning | sec 10.1 (CB-CO2); confirmed (CB-AI) |
| GDPR-compliant pseudonymization (SHA-256 with configurable salt) | sec 10.1 (CB-CO2); confirmed (CB-AI) |
| Actor entity resolution model (Actor / ActorPlatformPresence / ActorAlias) | sec 2.1 (CB-AI) |
| Content similarity-based actor discovery (SimilarityFinder) | sec 1 strengths (CB-AI) |
| PostgreSQL Danish snowball stemmer for full-text search | sec 7.1 (CB-CO2) |

---

## 2. Methodology-Aware Prioritization

The Issue Observatory must support two distinct research methodologies:

### 2.1 Discourse Tracking (CO2 Afgift Style)

**Characteristics:** Known terms, known actors, volume and engagement over time, framing analysis, cross-platform comparison, longitudinal tracking.

**Core operations:**
- Define search terms and actors
- Collect across arenas at scheduled intervals
- Track volume trends with temporal granularity
- Compare engagement across platforms
- Export for statistical analysis

**Current readiness:** 75-80% (CB-CO2 assessment)

### 2.2 Issue Mapping (AI og uddannelse / Marres Style)

**Characteristics:** Explorative discovery, emergent term extraction, actor role classification, discourse association detection, controversy identification, network visualization, iterative query refinement.

**Core operations:**
- Start with seed terms and actors
- Discover new terms and actors through collection and analysis
- Build and visualize bipartite actor-discourse networks
- Trace how the issue travels across arenas
- Qualitatively code content for stance and framing
- Iterate: refine queries based on discoveries

**Current readiness:** 55-60% (CB-AI assessment)

### 2.3 Prioritization Principle

Items are prioritized in the following order:

1. **Both methodologies** -- systemic issues that affect all research use (highest priority)
2. **Discourse tracking maturity** -- bringing the more-ready methodology to publication quality
3. **Issue mapping capabilities** -- enabling the Marres methodology that requires deeper analytical features
4. **Advanced features** -- enhancements that improve both workflows but are not blockers

---

## 3. Unified Improvement Roadmap

All recommendations from the four input reports have been deduplicated, cross-referenced, and assigned unique IDs. Each item is tagged with:
- Which reports identified it (cross-reference)
- Which methodology it serves (Both / Tracking / Mapping)
- Estimated effort (person-days)
- Dependencies
- Responsible agent type

### 3.1 Foundation Fixes (Serve Both Methodologies)

| ID | Description | Reports | Methodology | Effort | Dependencies | Agent |
|----|-------------|---------|-------------|--------|--------------|-------|
| IP2-001 | **Dynamic arena grid**: Populate arena configuration grid from server registry instead of hardcoded JS array. Include arena availability, credential status, and supported tiers. | FP-10/11, B-01 (UX-CO2); IM-11, IM-B03 (UX-AI); R-01 (UX-CO2); R-01 (UX-AI) | Both | 3-4 days | None | frontend-engineer + core-application-engineer |
| IP2-002 | **Arena tier validation**: Disable or grey out unsupported tier options per arena. Tooltip explains why. | FP-09 (UX-CO2); IM-10 (UX-AI); R-03 (UX-CO2); R-06 (UX-AI) | Both | 1-2 days | IP2-001 | frontend-engineer |
| IP2-003 | **Arena descriptions**: Add one-line description and data-type explanation to each arena in the configuration grid. | FP-13 (UX-CO2); IM-13, IM-14 (UX-AI); R-02 (UX-CO2); R-05 (UX-AI) | Both | 1 day | IP2-001 | frontend-engineer + research-strategist |
| IP2-004 | **Duplicate exclusion in analysis**: Add `WHERE raw_metadata->>'duplicate_of' IS NULL` to all descriptive and network analysis queries. | P1.2 (CB-CO2); IM-1.4 (CB-AI); TD-4 (both) | Both | 0.5 days | None | db-data-engineer |
| IP2-005 | **Extend flat export columns**: Add `pseudonymized_author_id`, `content_hash`, `collection_run_id`, `query_design_name` to `_FLAT_COLUMNS`. | P1.3 (CB-CO2); IM-1.5, IM-38 (CB-AI) | Both | 0.5 days | None | db-data-engineer |
| IP2-006 | **Human-readable export headers**: Replace snake_case column names with readable labels (e.g., "Text Content", "Matched Search Terms"). | FP-33 (UX-CO2); IM-37 (UX-AI); R-11 (UX-CO2); R-14 (UX-AI) | Both | 0.5 days | IP2-005 | db-data-engineer |
| IP2-007 | **Actor synchronization**: Auto-create or link Actor Directory entries when actors are added to a query design. Eliminate duplicate-entry workflow. | FP-07 (UX-CO2); IM-08, IM-24, IM-B01 (UX-AI); R-02 (UX-AI) | Both | 2-3 days | None | frontend-engineer + core-application-engineer |
| IP2-008 | **Client-side Danish language detection**: Integrate langdetect or fasttext as normalizer fallback when platform does not provide language tag. | P2.1 (CB-CO2); IM-2.4 (CB-AI) | Both | 1-2 days | None | core-application-engineer |
| IP2-009 | **Add Altinget RSS feed** to `DANISH_RSS_FEEDS` in danish_defaults.py. | P1.1 (CB-CO2); IM-1.2 (CB-AI) | Both | 0.1 days | None | research-strategist |
| IP2-010 | **Update stale "Phase 0" text** on dashboard and System Status page to reflect actual feature set. | FP-01, FP-02, FP-36 (UX-CO2); IM-01 (UX-AI); R-08 (UX-CO2) | Both | 0.25 days | None | frontend-engineer |
| IP2-011 | **Arena column always visible**: Show arena column in content browser at all breakpoints (remove xl-only class). | FP-21 (UX-CO2); IM-18 (UX-AI) | Both | 0.1 days | None | frontend-engineer |
| IP2-012 | **Analysis filter dropdowns**: Replace free-text Platform/Arena inputs with dropdown selectors populated from run data. | FP-31 (UX-CO2); IM-30 (UX-AI); R-06 (UX-CO2) | Both | 1 day | None | frontend-engineer |
| IP2-013 | **Chart axis labels**: Add y-axis ("Number of records") and x-axis labels to all analysis dashboard charts. | FP-30 (UX-CO2); IM-29 (UX-AI); R-07 (UX-CO2); R-15 (UX-AI) | Both | 0.5 days | None | frontend-engineer |
| IP2-014 | **Query design detail shows arena config**: Add read-only arena configuration display to the query design detail page. | FP-15 (UX-CO2); IM-15 (UX-AI); R-04 (UX-CO2); R-08 (UX-AI) | Both | 1 day | None | frontend-engineer |
| IP2-015 | **Term type help text**: Add tooltips or inline descriptions below the term type dropdown explaining Keyword, Phrase, Hashtag, URL pattern behavior. | FP-04 (UX-CO2); IM-05 (UX-AI); R-05 (UX-CO2) | Both | 0.25 days | None | frontend-engineer |
| IP2-016 | **Snowball sampling discoverability**: Add navigation link or prominent mention on Actor Directory page. Auto-expand when actors exist. | FP-27 (UX-CO2); IM-25 (UX-AI); R-14 (UX-CO2); R-17 (UX-AI) | Both | 0.5 days | None | frontend-engineer |
| IP2-017 | **Admin credential form**: Add missing platforms (Gab, Threads, Facebook/Bright Data, Instagram/Bright Data, SerpAPI) to the credential dropdown. | B-04 (Phase 3); B-02 (UX-CO2); R-15 (UX-CO2) | Both | 0.5 days | None | frontend-engineer |
| IP2-018 | **Collection detail context**: Show query design name prominently in header and include search terms summary on collection detail page. | FP-19, FP-20 (UX-CO2); R-10 (UX-CO2) | Both | 0.5 days | None | frontend-engineer |
| IP2-019 | **Replace "Celery Beat" jargon** with researcher-friendly live mode description. | FP-16 (UX-CO2); IM-17 (UX-AI); R-09 (UX-CO2) | Both | 0.1 days | None | frontend-engineer |
| IP2-020 | **Save confirmation feedback**: Flash message or checkmark after saving arena configuration. | FP-14 (UX-CO2); R-17 (UX-CO2) | Both | 0.25 days | None | frontend-engineer |
| IP2-021 | **Timestamp timezone display**: Show timezone (CET/CEST or UTC) on all timestamps in record detail and collection pages. | FP-25 (UX-CO2); IM-22 (UX-AI) | Both | 0.5 days | None | frontend-engineer |
| IP2-022 | **Tier precedence resolution**: Document or enforce which tier wins when query design per-arena tier conflicts with launcher global tier. | FP-18 (UX-CO2) | Both | 0.5 days | None | core-application-engineer |
| IP2-023 | **Date range guidance**: Add per-arena tooltip in collection launcher explaining historical coverage capabilities (RSS = real-time only, GDELT = years). | FP-17 (UX-CO2); IM-16 (UX-AI); R-16 (UX-CO2) | Both | 0.5 days | None | frontend-engineer + research-strategist |
| IP2-024 | **Consolidate analysis filter builders**: Merge `_build_content_filters()` and `_build_run_filter()` into a shared utility. | TD-2 (CB-CO2); TD-1 (CB-AI) | Both | 1 day | None | db-data-engineer |
| IP2-025 | **GEXF export uses network.py functions**: Refactor GEXF export to consume graph dicts from network analysis functions instead of reconstructing from records. | TD-3 (CB-CO2); TD-2 (CB-AI) | Both | 1-2 days | None | db-data-engineer |
| IP2-026 | **Relabel "JSON" export to "NDJSON"** with format explanation tooltip. | FP-34 (UX-CO2); R-12 (UX-CO2) | Both | 0.1 days | None | frontend-engineer |
| IP2-027 | **Fix mixed-language "termer"** label to consistent English. | FP-05 (UX-CO2); IM-07 (UX-AI) | Both | 0.1 days | None | frontend-engineer |
| IP2-028 | **Engagement score tooltip**: Add explanation of what the composite engagement score represents and that it is not comparable cross-platform. | FP-22 (UX-CO2); IM-21 (UX-AI); R (UX-AI) | Both | 0.25 days | None | frontend-engineer |
| IP2-029 | **Content browser search term filter as dropdown**: Replace free-text "Search Term" filter with dropdown populated from the query design's terms. | FP-23 (UX-CO2); IM-20 (UX-AI); R-07 (UX-AI) | Both | 0.5 days | None | frontend-engineer |

### 3.2 Discourse Tracking Maturity Items

| ID | Description | Reports | Methodology | Effort | Dependencies | Agent |
|----|-------------|---------|-------------|--------|--------------|-------|
| IP2-030 | **Engagement score normalization**: Define and implement cross-platform engagement score formula. Populate the `engagement_score` column. | P2.2, P2.6 (CB-CO2) | Tracking | 2-3 days | None | db-data-engineer |
| IP2-031 | **Boolean query support**: Add `TermGroup` model or `query_expression` field to SearchTerm. Parse into platform-native query syntax per arena. | P2.3 (CB-CO2); Gap 1 (CB-AI sec 4.3); IM-3.4 (CB-AI) | Both | 3-5 days | None | db-data-engineer + core-application-engineer |
| IP2-032 | **Near-duplicate detection**: Implement SimHash or MinHash for near-duplicate detection of lightly-edited wire stories. | P2.4 (CB-CO2) | Tracking | 3-5 days | IP2-004 | db-data-engineer |
| IP2-033 | **Temporal volume comparison**: Add period-over-period analysis and event annotation overlay to volume charts. | P2.5 (CB-CO2); Gap 3 (CB-CO2 sec 6.2) | Tracking | 2-3 days | None | db-data-engineer |
| IP2-034 | **Danish sentiment analysis enrichment**: Integrate DaNLP or Alexandra Institute sentiment model as post-collection enrichment. | P3.1 (CB-CO2); Gap 2 (CB-AI sec 5) | Both | 3-5 days | IP2-036 | core-application-engineer |
| IP2-035 | **Engagement metric refresh**: Implement re-collection mechanism for updating engagement metrics on previously collected content. | TD-6 (CB-CO2) | Tracking | 2-3 days | None | core-application-engineer |
| IP2-036 | **Enrichment pipeline architecture**: Create pluggable enricher interface (similar to ArenaCollector) with Celery task queue and standardized `raw_metadata.enrichments` storage. | TD-4 (CB-CO2); TD-3 (CB-AI) | Both | 3-5 days | None | core-application-engineer |
| IP2-037 | **Arena-comparative analysis**: Add `get_arena_comparison()` and `get_actor_arena_distribution()` functions. | Gap 4 (CB-CO2 sec 6.2) | Tracking | 2-3 days | IP2-024 | db-data-engineer |

### 3.3 Issue Mapping Capabilities

| ID | Description | Reports | Methodology | Effort | Dependencies | Agent |
|----|-------------|---------|-------------|--------|--------------|-------|
| IP2-038 | **Emergent term extraction**: TF-IDF or KeyBERT on collected text content to discover discourse associations beyond pre-defined search terms. | Gap 1 (CB-AI sec 5); DQ-01 (UX-AI); IM-34 (UX-AI); IM-2.1 (CB-AI) | Mapping | 3-5 days | None | core-application-engineer + db-data-engineer |
| IP2-039 | **Unified actor ranking**: Add `get_top_actors_unified()` grouping by `author_id` (canonical actor) instead of per-platform fragmentation. | TD-5 (CB-AI); IM-2.2 (CB-AI) | Mapping | 1-2 days | None | db-data-engineer |
| IP2-040 | **Bipartite network with extracted topics**: Extend `build_bipartite_network()` to use emergent topics as term nodes (not just search terms). | Critical #6, Gap 3 (CB-AI sec 5); IM-2.3 (CB-AI) | Mapping | 2-3 days | IP2-038 | db-data-engineer |
| IP2-041 | **Entity resolution UI**: Provide researcher-facing mechanism for triggering, monitoring, and reviewing cross-platform entity resolution. | IM-B02 (UX-AI); IM-36 (UX-AI); R-03 (UX-AI) | Mapping | 2-3 days | None | frontend-engineer + core-application-engineer |
| IP2-042 | **In-browser network preview**: Add lightweight force-directed graph visualization (d3-force or sigma.js) to network analysis tabs. | FP-32 (UX-CO2); IM-31 (UX-AI); R-04 (UX-AI); IM-4.3 (CB-AI) | Both | 3-5 days | None | frontend-engineer |
| IP2-043 | **Content annotation layer**: Add ContentAnnotation and ActorAnnotation models for qualitative coding (stance, frame, relevance, free text). | Gap 4 (CB-AI sec 5); IM-2.5 (CB-AI); P4.2 (CB-CO2) | Mapping | 5-7 days | None | db-data-engineer + frontend-engineer |
| IP2-044 | **Temporal network snapshots**: Add `get_temporal_network_snapshots()` for weekly/monthly network evolution with change detection. | Gap 5 (CB-AI sec 5); IM-3.1 (CB-AI); Gap 6 (CB-CO2 sec 6.2) | Mapping | 3-5 days | None | db-data-engineer |
| IP2-045 | **Dynamic GEXF export**: Support `mode="dynamic"` with temporal attributes on nodes and edges for Gephi Timeline. | Gap 2 (CB-AI sec 6.2); IM-3.2 (CB-AI) | Mapping | 2-3 days | IP2-044 | db-data-engineer |
| IP2-046 | **Term grouping in query design**: Allow categorizing search terms (primary, discourse association, actor discovery, English variant) with visual grouping. | IM-06 (UX-AI); R-10 (UX-AI) | Mapping | 1-2 days | None | frontend-engineer + db-data-engineer |
| IP2-047 | **Per-arena GEXF export**: Allow generating network files filtered by arena for cross-platform network comparison. | IM-39 (UX-AI); R-12 (UX-AI) | Mapping | 1-2 days | IP2-025 | db-data-engineer |
| IP2-048 | **Platform attribute on bipartite GEXF actor nodes**: Include platform metadata on actor nodes in bipartite network export. | IM-35 (UX-AI); R-09 (UX-AI) | Mapping | 0.5 days | None | db-data-engineer |
| IP2-049 | **Named entity extraction from text**: Identify mentioned actors and organizations in news articles (speaker vs. mentioned vs. quoted). | Gap (CB-AI sec 2.1); IM-3.5 (CB-AI) | Mapping | 3-5 days | IP2-036 | core-application-engineer |
| IP2-050 | **Cross-arena flow analysis**: Detect temporal propagation sequences showing which arena covers a story first and how it propagates. | Gap 6 (CB-AI sec 5); IM-3.3 (CB-AI); Critical #4 (CB-CO2) | Both | 3-5 days | IP2-004, IP2-032 | db-data-engineer + research-strategist |

### 3.4 Advanced Research Features

| ID | Description | Reports | Methodology | Effort | Dependencies | Agent |
|----|-------------|---------|-------------|--------|--------------|-------|
| IP2-051 | **Query design cloning and versioning**: Snapshot query designs at each iteration; support branching and comparison. | Gap 3 (CB-CO2 sec 4.3); Gap 2 (CB-AI sec 4.3); P4.1 (CB-CO2); IM-4.1 (CB-AI) | Both | 2-3 days | None | db-data-engineer + frontend-engineer |
| IP2-052 | **Multilingual query design**: Support "Danish + English" or arbitrary language combinations per query design. | IM-04 (UX-AI); Gap 3 (CB-AI sec 4.3); R-16 (UX-AI) | Mapping | 1-2 days | None | frontend-engineer + core-application-engineer |
| IP2-053 | **Query term suggestion from collected data**: After collection, suggest new terms based on emergent term extraction results. | Gap 5 (CB-AI sec 4.3); IM-4.5 (CB-AI) | Mapping | 2-3 days | IP2-038 | db-data-engineer |
| IP2-054 | **Topic modeling enrichment** (BERTopic on Danish text): Full topic modeling with topic assignments stored as enrichments. | P3.5 (CB-CO2); Gap 1 (CB-AI sec 5) | Both | 5-7 days | IP2-036, IP2-038 | core-application-engineer |
| IP2-055 | **Filtered export from analysis results**: Export only records matching network, top-actor, or term-filter criteria. | P4.5 (CB-CO2); IM-4.4 (CB-AI) | Both | 2-3 days | None | db-data-engineer |
| IP2-056 | **RIS/BibTeX export for academic citation**: Generate reference manager-compatible output for collected articles. | P4.4 (CB-CO2) | Tracking | 1-2 days | None | db-data-engineer |
| IP2-057 | **Folketinget.dk parliamentary proceedings arena**: Custom arena for Danish legislative documents, committee reports, and voting records. | Gap (CB-CO2 sec 3.2); P3.6 (CB-CO2) | Tracking | 5-7 days | Arena brief required | core-application-engineer + research-strategist |
| IP2-058 | **Add education-specific RSS feeds**: Folkeskolen.dk, Gymnasieskolen, university news pages. | IM-1.3 (CB-AI) | Mapping | 0.25 days | None | research-strategist |
| IP2-059 | **Expand Danish Reddit subreddits**: Add r/dkfinance (economic discourse) and verify r/dkpolitik availability. | DQ-04 (UX-CO2); DQ-03 (UX-AI) | Both | 0.1 days | None | research-strategist |
| IP2-060 | **Actor type enumeration**: Formalize `actor_type` values with research-relevant categories (educational_institution, teachers_union, think_tank, political_party, etc.). | Gap (CB-CO2 sec 4.4); IM-3.6 (CB-AI) | Both | 0.25 days | None | research-strategist + db-data-engineer |
| IP2-061 | **Mixed hash/name resolution in Top Actors chart**: Display canonical actor name from Actor Directory when entity resolution has linked a hash to a known actor. | IM-32 (UX-AI) | Mapping | 1-2 days | IP2-041 | frontend-engineer + core-application-engineer |

---

## 4. Implementation Phases

### Phase A: Foundation Fixes

**Principle:** Items that are blockers or affect both methodologies. Must be done first.

**Duration estimate:** 2-3 weeks (with parallel work across agents)

| ID | Description | Effort | Agent | Priority within Phase |
|----|-------------|--------|-------|----------------------|
| IP2-004 | Duplicate exclusion in analysis | 0.5 days | db-data-engineer | A1 -- data correctness |
| IP2-005 | Extend flat export columns | 0.5 days | db-data-engineer | A1 -- data completeness |
| IP2-006 | Human-readable export headers | 0.5 days | db-data-engineer | A1 -- usability |
| IP2-009 | Add Altinget RSS feed | 0.1 days | research-strategist | A1 -- coverage |
| IP2-059 | Expand Reddit subreddits | 0.1 days | research-strategist | A1 -- coverage |
| IP2-060 | Formalize actor_type values | 0.25 days | research-strategist + db-data-engineer | A1 -- schema |
| IP2-001 | Dynamic arena grid | 3-4 days | frontend-engineer + core-application-engineer | A2 -- unblocks 8 arenas |
| IP2-007 | Actor synchronization (QD <-> Actor Directory) | 2-3 days | frontend-engineer + core-application-engineer | A2 -- unblocks actor workflow |
| IP2-002 | Arena tier validation | 1-2 days | frontend-engineer | A3 -- depends on IP2-001 |
| IP2-003 | Arena descriptions | 1 day | frontend-engineer + research-strategist | A3 -- depends on IP2-001 |
| IP2-010 | Update stale "Phase 0" text | 0.25 days | frontend-engineer | A3 -- quick fix |
| IP2-011 | Arena column always visible | 0.1 days | frontend-engineer | A3 -- quick fix |
| IP2-013 | Chart axis labels | 0.5 days | frontend-engineer | A3 -- quick fix |
| IP2-014 | Query design detail shows arena config | 1 day | frontend-engineer | A3 -- usability |
| IP2-015 | Term type help text | 0.25 days | frontend-engineer | A3 -- quick fix |
| IP2-016 | Snowball sampling discoverability | 0.5 days | frontend-engineer | A3 -- quick fix |
| IP2-017 | Admin credential form platforms | 0.5 days | frontend-engineer | A3 -- quick fix |
| IP2-018 | Collection detail context (name, terms) | 0.5 days | frontend-engineer | A3 -- usability |
| IP2-019 | Replace "Celery Beat" jargon | 0.1 days | frontend-engineer | A3 -- quick fix |
| IP2-020 | Save confirmation feedback | 0.25 days | frontend-engineer | A3 -- quick fix |
| IP2-021 | Timestamp timezone display | 0.5 days | frontend-engineer | A3 -- usability |
| IP2-022 | Tier precedence resolution | 0.5 days | core-application-engineer | A3 -- clarity |
| IP2-023 | Date range guidance | 0.5 days | frontend-engineer + research-strategist | A3 -- usability |
| IP2-024 | Consolidate analysis filter builders | 1 day | db-data-engineer | A3 -- tech debt |
| IP2-025 | GEXF export uses network.py functions | 1-2 days | db-data-engineer | A3 -- tech debt |
| IP2-026 | Relabel "JSON" to "NDJSON" | 0.1 days | frontend-engineer | A3 -- quick fix |
| IP2-027 | Fix mixed-language "termer" | 0.1 days | frontend-engineer | A3 -- quick fix |
| IP2-028 | Engagement score tooltip | 0.25 days | frontend-engineer | A3 -- quick fix |
| IP2-029 | Search term filter as dropdown | 0.5 days | frontend-engineer | A3 -- usability |
| IP2-012 | Analysis filter dropdowns | 1 day | frontend-engineer | A3 -- usability |

**Phase A total effort estimate:** ~22-28 person-days

**Phase A agent breakdown:**
- frontend-engineer: ~12-15 person-days
- core-application-engineer: ~4-6 person-days
- db-data-engineer: ~5-6 person-days
- research-strategist: ~1-2 person-days

### Phase B: Discourse Tracking Maturity

**Principle:** Items that bring the CO2 afgift / tracking workflow to publication quality.

**Duration estimate:** 3-4 weeks (following Phase A)

| ID | Description | Effort | Agent | Priority within Phase |
|----|-------------|--------|-------|----------------------|
| IP2-008 | Client-side Danish language detection | 1-2 days | core-application-engineer | B1 -- data quality |
| IP2-030 | Engagement score normalization | 2-3 days | db-data-engineer | B1 -- cross-platform comparability |
| IP2-031 | Boolean query support | 3-5 days | db-data-engineer + core-application-engineer | B1 -- query precision |
| IP2-036 | Enrichment pipeline architecture | 3-5 days | core-application-engineer | B2 -- enables Phase C and D enrichments |
| IP2-032 | Near-duplicate detection (SimHash/MinHash) | 3-5 days | db-data-engineer | B2 -- data quality |
| IP2-033 | Temporal volume comparison + event annotation | 2-3 days | db-data-engineer | B2 -- analytical depth |
| IP2-037 | Arena-comparative analysis functions | 2-3 days | db-data-engineer | B2 -- cross-platform |
| IP2-034 | Danish sentiment analysis enrichment | 3-5 days | core-application-engineer | B3 -- depends on IP2-036 |
| IP2-035 | Engagement metric refresh | 2-3 days | core-application-engineer | B3 -- data freshness |

**Phase B total effort estimate:** ~22-33 person-days

**Phase B agent breakdown:**
- core-application-engineer: ~10-15 person-days
- db-data-engineer: ~12-18 person-days

### Phase C: Issue Mapping Capabilities

**Principle:** Items that enable Marres-style issue mapping. Many depend on Phase B's enrichment pipeline.

**Duration estimate:** 4-6 weeks (can overlap with late Phase B)

| ID | Description | Effort | Agent | Priority within Phase |
|----|-------------|--------|-------|----------------------|
| IP2-038 | Emergent term extraction (TF-IDF/KeyBERT) | 3-5 days | core-application-engineer + db-data-engineer | C1 -- defining capability |
| IP2-039 | Unified actor ranking (by canonical identity) | 1-2 days | db-data-engineer | C1 -- actor fidelity |
| IP2-041 | Entity resolution UI | 2-3 days | frontend-engineer + core-application-engineer | C1 -- cross-platform actors |
| IP2-042 | In-browser network preview | 3-5 days | frontend-engineer | C1 -- explorative workflow |
| IP2-040 | Bipartite network with extracted topics | 2-3 days | db-data-engineer | C2 -- depends on IP2-038 |
| IP2-043 | Content annotation layer | 5-7 days | db-data-engineer + frontend-engineer | C2 -- qualitative coding |
| IP2-044 | Temporal network snapshots | 3-5 days | db-data-engineer | C2 -- issue trajectory |
| IP2-045 | Dynamic GEXF export | 2-3 days | db-data-engineer | C3 -- depends on IP2-044 |
| IP2-046 | Term grouping in query design | 1-2 days | frontend-engineer + db-data-engineer | C3 -- organizational |
| IP2-047 | Per-arena GEXF export | 1-2 days | db-data-engineer | C3 -- depends on IP2-025 |
| IP2-048 | Platform attribute on bipartite GEXF nodes | 0.5 days | db-data-engineer | C3 -- quick fix |
| IP2-049 | Named entity extraction | 3-5 days | core-application-engineer | C3 -- depends on IP2-036 |
| IP2-050 | Cross-arena flow analysis | 3-5 days | db-data-engineer + research-strategist | C3 -- depends on IP2-004, IP2-032 |
| IP2-058 | Education-specific RSS feeds | 0.25 days | research-strategist | C1 -- coverage |

**Phase C total effort estimate:** ~27-42 person-days

**Phase C agent breakdown:**
- core-application-engineer: ~6-10 person-days
- db-data-engineer: ~14-21 person-days
- frontend-engineer: ~6-10 person-days
- research-strategist: ~1-2 person-days

### Phase D: Advanced Research Features

**Principle:** Enhancements that improve both workflows but are not blockers for either.

**Duration estimate:** 4-6 weeks (can overlap with Phase C)

| ID | Description | Effort | Agent |
|----|-------------|--------|-------|
| IP2-051 | Query design cloning and versioning | 2-3 days | db-data-engineer + frontend-engineer |
| IP2-052 | Multilingual query design | 1-2 days | frontend-engineer + core-application-engineer |
| IP2-053 | Query term suggestion from collected data | 2-3 days | db-data-engineer |
| IP2-054 | Topic modeling enrichment (BERTopic) | 5-7 days | core-application-engineer |
| IP2-055 | Filtered export from analysis results | 2-3 days | db-data-engineer |
| IP2-056 | RIS/BibTeX export | 1-2 days | db-data-engineer |
| IP2-057 | Folketinget.dk arena | 5-7 days | core-application-engineer + research-strategist |
| IP2-061 | Mixed hash/name resolution in charts | 1-2 days | frontend-engineer + core-application-engineer |

**Phase D total effort estimate:** ~19-29 person-days

---

## 5. Dependency Graph

### Critical Path

The critical path through the roadmap identifies the longest chain of dependent work items:

```
IP2-001 (dynamic arena grid)
  --> IP2-002 (tier validation)
  --> IP2-003 (arena descriptions)

IP2-036 (enrichment pipeline)
  --> IP2-034 (sentiment analysis)
  --> IP2-049 (named entity extraction)
  --> IP2-054 (topic modeling, Phase D)

IP2-038 (emergent term extraction)
  --> IP2-040 (bipartite with extracted topics)
  --> IP2-053 (term suggestion from data, Phase D)

IP2-044 (temporal network snapshots)
  --> IP2-045 (dynamic GEXF)

IP2-004 (duplicate exclusion) + IP2-032 (near-duplicate detection)
  --> IP2-050 (cross-arena flow analysis)

IP2-025 (GEXF uses network.py)
  --> IP2-047 (per-arena GEXF)

IP2-041 (entity resolution UI)
  --> IP2-061 (hash/name resolution in charts)
```

### Parallel Work Streams

Three independent work streams can proceed simultaneously within each phase:

**Stream 1 -- Frontend UX fixes (frontend-engineer):**
IP2-010, IP2-011, IP2-013, IP2-015, IP2-016, IP2-017, IP2-019, IP2-020, IP2-021, IP2-026, IP2-027, IP2-028, IP2-029 (all independent, Phase A)

**Stream 2 -- Data correctness (db-data-engineer):**
IP2-004, IP2-005, IP2-006, IP2-024, IP2-025 (Phase A, mostly independent)

**Stream 3 -- Arena and actor infrastructure (frontend-engineer + core-application-engineer):**
IP2-001 --> IP2-002 --> IP2-003 (serial within stream)
IP2-007 (independent of IP2-001)

### Items That Block the Most Downstream Work

| Item | Items it blocks (direct + transitive) |
|------|--------------------------------------|
| IP2-001 (dynamic arena grid) | IP2-002, IP2-003 |
| IP2-036 (enrichment pipeline) | IP2-034, IP2-049, IP2-054 |
| IP2-038 (emergent term extraction) | IP2-040, IP2-053 |
| IP2-025 (GEXF uses network.py) | IP2-047 |
| IP2-044 (temporal network snapshots) | IP2-045 |
| IP2-004 (duplicate exclusion) | IP2-050 |
| IP2-032 (near-duplicate detection) | IP2-050 |

**Recommendation:** IP2-001 and IP2-036 should be started as early as possible because they unblock the most downstream work.

---

## 6. Cost-Benefit Analysis

### Phase A: Foundation Fixes

| Metric | Estimate |
|--------|----------|
| Engineering effort | 22-28 person-days (~4.5-6 weeks at 5 days/week with 1 engineer per stream; ~2-3 weeks with parallel streams) |
| Research impact | Unblocks access to 8 additional arenas (Event Registry, X/Twitter, Threads, AI Chat Search, Facebook, Instagram, Majestic, Common Crawl). Eliminates data correctness issues (duplicate counting). Makes existing features discoverable and transparent. |
| Test case findings resolved | UX-CO2: FP-01, FP-02, FP-04, FP-05, FP-07, FP-09, FP-10, FP-11, FP-13, FP-14, FP-15, FP-16, FP-17, FP-18, FP-19, FP-20, FP-21, FP-22, FP-23, FP-25, FP-27, FP-30, FP-31, FP-33, FP-34, FP-36, B-01, B-02. UX-AI: IM-01, IM-05, IM-07, IM-08, IM-10, IM-11, IM-13, IM-15, IM-17, IM-18, IM-20, IM-21, IM-22, IM-25, IM-29, IM-30, IM-37, IM-38, IM-B01, IM-B03. CB-CO2: P1.1-P1.3, TD-2, TD-3. CB-AI: IM-1.2, IM-1.4, IM-1.5, TD-1, TD-2. |
| New research questions answerable | None new -- Phase A makes existing capabilities usable, not new capabilities. But it makes the system trustworthy for pilot research on either methodology. |

### Phase B: Discourse Tracking Maturity

| Metric | Estimate |
|--------|----------|
| Engineering effort | 22-33 person-days (~4.5-7 weeks at 5 days/week per agent stream) |
| Research impact | Enables publication-quality discourse tracking. Cross-platform engagement comparison becomes meaningful. Boolean queries reduce noise and API costs. Temporal event correlation supports policy analysis. Enrichment pipeline is the architectural prerequisite for all NLP-based features. |
| Test case findings resolved | CB-CO2: P2.1-P2.6, P3.1, TD-4, TD-6. CB-AI: IM-2.4. |
| New research questions answerable | "How does CO2 afgift coverage change around legislative events?" (IP2-033). "What is the relative engagement level of CO2 afgift content across platforms?" (IP2-030). "What sentiment does each actor express toward the carbon tax?" (IP2-034). "How do different outlets edit the same wire story?" (IP2-032). |

### Phase C: Issue Mapping Capabilities

| Metric | Estimate |
|--------|----------|
| Engineering effort | 27-42 person-days (~5.5-8.5 weeks per agent stream) |
| Research impact | Enables Marres-style issue mapping as a supported methodology. Emergent term extraction (IP2-038) is the single most transformative capability -- it shifts the system from data collection to data discovery. Combined with bipartite topic networks (IP2-040) and in-browser visualization (IP2-042), a researcher can produce an issue map without leaving the application. |
| Test case findings resolved | CB-AI: IM-2.1 through IM-2.5, IM-3.1 through IM-3.5, TD-5. UX-AI: IM-06, IM-31, IM-34, IM-35, IM-39, IM-B02, DQ-01. |
| New research questions answerable | "What discourse associations are emerging around AI og uddannelse that I did not anticipate?" (IP2-038). "How does the actor-discourse network evolve over time?" (IP2-044, IP2-045). "Which arena covers the issue first and how does it propagate?" (IP2-050). "What are the contested points in this issue?" (IP2-043 enables manual coding; IP2-049 enables automated detection of mentioned entities). |

### Phase D: Advanced Research Features

| Metric | Estimate |
|--------|----------|
| Engineering effort | 19-29 person-days |
| Research impact | Quality-of-life improvements. Versioning supports iterative methodology. Topic modeling provides richer discourse structure. Parliamentary data expands the institutional coverage. Academic citation export supports publication workflow. |
| Test case findings resolved | CB-CO2: P3.5, P3.6, P4.1, P4.4, P4.5. CB-AI: IM-4.1 through IM-4.5. UX-AI: IM-04, IM-32. |
| New research questions answerable | "How has my query design evolved over the course of this study?" (IP2-051). "What are the dominant topics in this discourse beyond my search terms?" (IP2-054). "What did the Folketing say about CO2 afgift during the spring session?" (IP2-057). |

### Cumulative Effort Summary

| Phase | Person-Days (Low) | Person-Days (High) | Cumulative Low | Cumulative High |
|-------|-------------------|-------------------|----------------|-----------------|
| A: Foundation | 22 | 28 | 22 | 28 |
| B: Tracking Maturity | 22 | 33 | 44 | 61 |
| C: Issue Mapping | 27 | 42 | 71 | 103 |
| D: Advanced Features | 19 | 29 | 90 | 132 |

---

## 7. Tier and Arena Strategy

### 7.1 Arena Prioritization for Implementation Fixes

Based on both test cases, the following arenas should be prioritized in the dynamic arena grid rollout (IP2-001):

| Priority | Arena | Rationale | Currently Visible |
|----------|-------|-----------|-------------------|
| 1 | Event Registry | Critical for both CO2 afgift and AI og uddannelse. Full-text Danish news with NLP. | No -- missing from grid |
| 2 | X/Twitter | High for both test cases. 13% Danish penetration but overrepresented in political/media elite discourse. | No -- missing from grid |
| 3 | AI Chat Search | Uniquely valuable for AI og uddannelse (meta-analysis). Novel methodology. | No -- missing from grid |
| 4 | Facebook | 84% Danish penetration. Critical for both test cases but access-dependent. | No -- missing from grid |
| 5 | Instagram | Medium for both. Student/visual content. | No -- missing from grid |
| 6 | Threads | Low-medium. Emerging. | No -- missing from grid |
| 7 | Common Crawl / Wayback | Historical baseline. Niche use. | No -- missing from grid |
| 8 | Majestic | Premium-only. Web graph analysis. | No -- missing from grid |
| Already visible | Google Search, Google Autocomplete, Bluesky, Reddit, YouTube, RSS Feeds, GDELT, Telegram, TikTok, Ritzau Via, Gab | -- | Yes |

### 7.2 Default Free/Medium Tier Configuration for Danish Research

Based on both test cases, the following default configuration is recommended for Danish discourse research at the free/medium constraint:

**Free tier default (zero cost):**

| Arena | Tier | Danish Configuration |
|-------|------|---------------------|
| RSS Feeds | FREE | 28+ Danish feeds (after adding Altinget + education-specific per IP2-009, IP2-058) |
| GDELT | FREE | `sourcelang=danish`, `sourcecountry=DA` |
| Bluesky | FREE | `lang:da` search filter, client-side language filter for actor collection |
| Reddit | FREE | r/Denmark, r/danish, r/copenhagen, r/aarhus, r/dkfinance (after IP2-059) |
| YouTube | FREE | `relevanceLanguage=da`, `regionCode=DK` |
| Via Ritzau | FREE | `language=da` |
| Google Autocomplete | FREE/MEDIUM | `gl=dk`, `hl=da` (medium tier via Serper.dev for better coverage) |

**Medium tier addition (~$100-120/month):**

| Arena | Tier | Monthly Cost | Danish Configuration |
|-------|------|-------------|---------------------|
| Google Search | MEDIUM (Serper.dev) | $5-20 | `gl=dk`, `hl=da` |
| Event Registry | MEDIUM | $90 | ISO 639-3 `"dan"`, 5K tokens/month |
| X/Twitter | MEDIUM (TwitterAPI.io) | $5-15 | `lang:da` search operator |

**Conditional activation (requires access or additional budget):**

| Arena | Tier | Monthly Cost | Condition |
|-------|------|-------------|-----------|
| Facebook | MEDIUM (Bright Data or MCL) | $0-100 | MCL approval ($0) or Bright Data subscription ($50-100) |
| TikTok | MEDIUM | $10-20 | More relevant for AI og uddannelse than CO2 afgift |
| Instagram | MEDIUM (Bright Data) | Included with Facebook | Shared Bright Data subscription |

### 7.3 Cost Projections for Typical Studies

| Study Type | Duration | Monthly Cost | Total Cost | Expected Records |
|------------|----------|-------------|------------|-----------------|
| **Pilot study** (free tier only, 1 arena topic) | 1 month | $0 | $0 | 500-2,000 |
| **CO2 afgift discourse tracking** (free + medium, 10 arenas) | 6 months | $160-235 | $960-1,410 | 28,000-70,000 |
| **AI og uddannelse issue mapping** (free + medium, Phase A+B arenas) | 4 months | $103-120 | $412-480 | 8,000-25,000 |
| **AI og uddannelse full** (all arenas incl. Facebook/TikTok) | 4 months | $163-240 | $652-960 | 15,000-40,000 |
| **Combined study** (both topics, shared infrastructure) | 6 months | $200-300 | $1,200-1,800 | 40,000-100,000 |

### 7.4 Arena-Specific Recommendations

**Event Registry (IP2-001 unblocks):** The single most impactful arena to make visible. At $90/month (medium tier), it provides full-text Danish news articles with NLP (event clustering, entity extraction), which is a significant upgrade over RSS feeds (titles + excerpts only) and GDELT (translated, 55% accuracy). For both CO2 afgift and AI og uddannelse, Event Registry should be the primary paid news arena.

**AI Chat Search (IP2-001 unblocks):** A methodologically novel arena. For the AI og uddannelse topic specifically, this arena creates a meta-analytical dimension: how do AI chatbots themselves frame the issue the researcher is studying? This has no equivalent in any other platform. At medium tier (API call cost), it is affordable and unique. For CO2 afgift, it provides supplementary data on how AI systems present climate tax information.

**X/Twitter (IP2-001 unblocks):** At medium tier via TwitterAPI.io ($0.15/1K tweets), this is dramatically cheaper than the official Pro tier ($5K/month). Danish political/media elite discourse is concentrated here despite only 13% population penetration. The `lang:da` operator works on both official and third-party APIs.

**LinkedIn (no automated collection):** Both test cases identified LinkedIn as the highest-value coverage gap. No implementation action is possible -- the arena brief documents that no automated collection path exists as of February 2026. The recommended approach remains manual Zeeschuimer capture with NDJSON import. This applies equally to both CO2 afgift (industry stakeholders) and AI og uddannelse (university rectors, professors, EdTech professionals).

**Facebook/Instagram (access-dependent):** The Meta Content Library application is pending. If approved, it provides free researcher access with engagement metrics. If not, Bright Data is the fallback at $50-100/month. The decision point is the MCL application status -- this should be tracked and the recommendation updated when the status changes.

---

## Appendix A: Finding Cross-Reference Index

This table maps every finding ID from the four source reports to its unified roadmap item.

| Source Report | Finding ID | Unified Item |
|---------------|-----------|--------------|
| UX-CO2 | FP-01 | IP2-010 |
| UX-CO2 | FP-02 | IP2-010 |
| UX-CO2 | FP-03 | IP2-002, IP2-003 |
| UX-CO2 | FP-04 | IP2-015 |
| UX-CO2 | FP-05 | IP2-027 |
| UX-CO2 | FP-07 | IP2-007 |
| UX-CO2 | FP-09 | IP2-002 |
| UX-CO2 | FP-10 | IP2-001 |
| UX-CO2 | FP-11 | IP2-001 |
| UX-CO2 | FP-12 | IP2-001 (resolved by dynamic grid) |
| UX-CO2 | FP-13 | IP2-003 |
| UX-CO2 | FP-14 | IP2-020 |
| UX-CO2 | FP-15 | IP2-014 |
| UX-CO2 | FP-16 | IP2-019 |
| UX-CO2 | FP-17 | IP2-023 |
| UX-CO2 | FP-18 | IP2-022 |
| UX-CO2 | FP-19 | IP2-018 |
| UX-CO2 | FP-20 | IP2-018 |
| UX-CO2 | FP-21 | IP2-011 |
| UX-CO2 | FP-22 | IP2-028, IP2-030 |
| UX-CO2 | FP-23 | IP2-029 |
| UX-CO2 | FP-25 | IP2-021 |
| UX-CO2 | FP-27 | IP2-016 |
| UX-CO2 | FP-30 | IP2-013 |
| UX-CO2 | FP-31 | IP2-012 |
| UX-CO2 | FP-32 | IP2-042 |
| UX-CO2 | FP-33 | IP2-006 |
| UX-CO2 | FP-34 | IP2-026 |
| UX-CO2 | FP-35 | (not prioritized -- tooltip only) |
| UX-CO2 | FP-36 | IP2-010 |
| UX-CO2 | B-01 | IP2-001 |
| UX-CO2 | B-02 | IP2-017 |
| UX-CO2 | DQ-01 | (research documentation -- JP RSS) |
| UX-CO2 | DQ-03 | (documentation only) |
| UX-CO2 | DQ-04 | IP2-059 |
| CB-CO2 | P1.1 | IP2-009 |
| CB-CO2 | P1.2 | IP2-004 |
| CB-CO2 | P1.3 | IP2-005 |
| CB-CO2 | P2.1 | IP2-008 |
| CB-CO2 | P2.2, P2.6 | IP2-030 |
| CB-CO2 | P2.3 | IP2-031 |
| CB-CO2 | P2.4 | IP2-032 |
| CB-CO2 | P2.5 | IP2-033 |
| CB-CO2 | P3.1 | IP2-034 |
| CB-CO2 | P3.2 | IP2-038 |
| CB-CO2 | P3.3 | IP2-044 |
| CB-CO2 | P3.4 | IP2-050 |
| CB-CO2 | P3.5 | IP2-054 |
| CB-CO2 | P3.6 | IP2-057 |
| CB-CO2 | P4.1 | IP2-051 |
| CB-CO2 | P4.2 | IP2-043 |
| CB-CO2 | P4.3 | IP2-042 |
| CB-CO2 | P4.4 | IP2-056 |
| CB-CO2 | P4.5 | IP2-055 |
| CB-CO2 | TD-2 | IP2-024 |
| CB-CO2 | TD-3 | IP2-025 |
| CB-CO2 | TD-4 | IP2-004, IP2-036 |
| CB-CO2 | TD-6 | IP2-035 |
| UX-AI | IM-01 | IP2-010 |
| UX-AI | IM-02 | (not prioritized -- cosmetic) |
| UX-AI | IM-03 | (not prioritized -- metadata field) |
| UX-AI | IM-04 | IP2-052 |
| UX-AI | IM-05 | IP2-015 |
| UX-AI | IM-06 | IP2-046 |
| UX-AI | IM-07 | IP2-027 |
| UX-AI | IM-08 | IP2-007 |
| UX-AI | IM-10 | IP2-002 |
| UX-AI | IM-11 | IP2-001 |
| UX-AI | IM-13 | IP2-003 |
| UX-AI | IM-15 | IP2-014 |
| UX-AI | IM-16 | IP2-023 |
| UX-AI | IM-17 | IP2-019 |
| UX-AI | IM-18 | IP2-011 |
| UX-AI | IM-20 | IP2-029 |
| UX-AI | IM-21 | IP2-028 |
| UX-AI | IM-22 | IP2-021 |
| UX-AI | IM-23 | (not prioritized -- advanced feature) |
| UX-AI | IM-25 | IP2-016 |
| UX-AI | IM-29 | IP2-013 |
| UX-AI | IM-30 | IP2-012 |
| UX-AI | IM-31 | IP2-042 |
| UX-AI | IM-32 | IP2-061 |
| UX-AI | IM-33 | (GEXF node ID -- by design for GDPR) |
| UX-AI | IM-34 | IP2-038 |
| UX-AI | IM-35 | IP2-048 |
| UX-AI | IM-37 | IP2-006 |
| UX-AI | IM-38 | IP2-005 |
| UX-AI | IM-39 | IP2-047 |
| UX-AI | IM-B01 | IP2-007 |
| UX-AI | IM-B02 | IP2-041 |
| UX-AI | IM-B03 | IP2-001 |
| UX-AI | DQ-01 | IP2-038 |
| UX-AI | DQ-03 | IP2-059 |
| CB-AI | IM-1.2 | IP2-009 |
| CB-AI | IM-1.3 | IP2-058 |
| CB-AI | IM-1.4 | IP2-004 |
| CB-AI | IM-1.5 | IP2-005 |
| CB-AI | IM-2.1 | IP2-038 |
| CB-AI | IM-2.2 | IP2-039 |
| CB-AI | IM-2.3 | IP2-040 |
| CB-AI | IM-2.4 | IP2-008 |
| CB-AI | IM-2.5 | IP2-043 |
| CB-AI | IM-3.1 | IP2-044 |
| CB-AI | IM-3.2 | IP2-045 |
| CB-AI | IM-3.3 | IP2-050 |
| CB-AI | IM-3.4 | IP2-031 |
| CB-AI | IM-3.5 | IP2-049 |
| CB-AI | IM-3.6 | IP2-060 |
| CB-AI | IM-4.1 | IP2-051 |
| CB-AI | IM-4.2 | IP2-052 |
| CB-AI | IM-4.3 | IP2-042 |
| CB-AI | IM-4.4 | IP2-055 |
| CB-AI | IM-4.5 | IP2-053 |
| CB-AI | TD-1 | IP2-024 |
| CB-AI | TD-2 | IP2-025 |
| CB-AI | TD-3 | IP2-036 |
| CB-AI | TD-4 | IP2-004 |
| CB-AI | TD-5 | IP2-039 |

---

## Appendix B: Readiness Assessment After Each Phase

| Phase Completed | Discourse Tracking Readiness | Issue Mapping Readiness |
|-----------------|---------------------------|------------------------|
| Current (pre-implementation) | 75-80% | 55-60% |
| After Phase A | 88-92% (pilot-to-publication bridge) | 68-72% (pilot with workarounds) |
| After Phase B | 95%+ (publication quality) | 72-75% (improved but still gaps) |
| After Phase C | 95%+ (unchanged) | 88-92% (full Marres workflow supported) |
| After Phase D | 97%+ (comprehensive) | 95%+ (comprehensive) |

---

*This document is the master planning artifact for Implementation Plan 2.0. It should be reviewed by all agent team members before work begins. Changes to this document should be tracked in the changelog and flagged for team discussion per the Research Agent's working protocol.*

*End of strategic synthesis.*
