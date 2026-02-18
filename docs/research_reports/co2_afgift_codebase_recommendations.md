# Research Strategist Report: Codebase Evaluation for CO2 Afgift Issue Mapping

**Author:** Research & Knowledge Agent (The Strategist)
**Date:** 2026-02-17
**Status:** Final
**Scope:** Full codebase evaluation of the Issue Observatory for supporting "CO2 afgift" (carbon tax/levy) discourse mapping across Danish public arenas

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-17 | Initial report. Full codebase exploration and evaluation. |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Capability Assessment](#2-current-capability-assessment)
3. [Arena Coverage Analysis](#3-arena-coverage-analysis)
4. [Query Design and Search Capabilities](#4-query-design-and-search-capabilities)
5. [Data Collection and Quality](#5-data-collection-and-quality)
6. [Analysis and Visualization Gaps](#6-analysis-and-visualization-gaps)
7. [Danish Language and Locale Support](#7-danish-language-and-locale-support)
8. [Export and Integration](#8-export-and-integration)
9. [Prioritized Improvement Roadmap](#9-prioritized-improvement-roadmap)
10. [Architecture and Technical Debt](#10-architecture-and-technical-debt)

---

## 1. Executive Summary

The Issue Observatory codebase provides a substantial foundation for mapping discourse around "CO2 afgift" (Danish carbon tax/levy) across multiple platforms and media arenas. The system implements 18 arena collectors, a universal content record schema with Danish full-text search, a three-tier pricing model, actor entity resolution, cross-arena deduplication, network analysis (actor co-occurrence, term co-occurrence, bipartite), and export to CSV/XLSX/NDJSON/Parquet/GEXF formats.

**Overall assessment: The system is architecturally sound and approximately 75-80% ready for a CO2 afgift study.** The primary gaps are not in infrastructure but in research-specific query design features, analytical depth, and operational concerns that arise specifically when tracking a complex multi-faceted Danish policy issue.

### Critical findings requiring action before a CO2 afgift study

1. **No boolean query logic.** The `SearchTerm` model (`src/issue_observatory/core/models/query_design.py`, line 140) supports only individual terms of type keyword/phrase/hashtag/url_pattern. There is no mechanism for boolean combinations (AND/OR/NOT), proximity operators, or term grouping. A CO2 afgift study requires compound queries such as `"CO2 afgift" AND (landbrug OR industri OR transport)` to distinguish sector-specific discourse threads.

2. **No sentiment or stance indicators in the schema.** The `UniversalContentRecord` (`src/issue_observatory/core/models/content.py`) has no column for sentiment polarity, stance classification, or framing category. For a policy issue like CO2 afgift, knowing whether content is supportive, oppositional, or neutral toward the tax is a fundamental analytical dimension. This data belongs in `raw_metadata` JSONB as an enrichment step, but no enrichment pipeline exists.

3. **No temporal comparison or trend detection.** The analysis module (`src/issue_observatory/analysis/descriptive.py`) computes volume over time (`get_volume_over_time`, line 127) but does not support period-over-period comparison, anomaly detection, or event-driven spike identification. For tracking CO2 afgift around parliamentary debates, budget negotiations, or EU policy announcements, the ability to detect and annotate volume spikes against an external event timeline is essential.

4. **Limited cross-arena narrative tracking.** The system can detect that the same URL or the same content hash appears across arenas (via `DeduplicationService` in `src/issue_observatory/core/deduplication.py`), but it cannot track how a narrative frame (e.g., "CO2 afgift rammer landbruget hardest") propagates from one arena to another over time. This is the core research question for issue mapping and requires sequence-aware cross-arena analysis.

5. **Open blocker B-02 partially resolved.** The term co-occurrence and bipartite GEXF export functions (`_build_term_gexf` and `_build_bipartite_gexf` in `src/issue_observatory/analysis/export.py`, lines 497 and 573) are now implemented. However, the frontend download buttons were historically broken (per Phase 3 UX report). Verification that the fix is end-to-end functional is needed before relying on network exports for CO2 afgift analysis.

### What works well today

- Danish locale defaults are comprehensive and correctly configured for every arena (`src/issue_observatory/config/danish_defaults.py`)
- The 28 Danish RSS feeds cover all major national outlets where CO2 afgift coverage would appear
- PostgreSQL full-text search uses the Danish snowball stemmer (`to_tsvector('danish', ...)`) with a GIN index, enabling efficient content search for Danish-language terms
- GDPR compliance architecture (pseudonymization via SHA-256 with salt, DPIA-aligned) is production-ready
- Actor entity resolution model supports cross-platform tracking of key CO2 afgift stakeholders
- Credit system and tier management allow cost-controlled collection across paid arenas

---

## 2. Current Capability Assessment

### 2.1 Architecture Overview

The system follows a modular arena-based architecture. Each arena is a self-contained package under `src/issue_observatory/arenas/` containing a collector, router, tasks module, and config. The `ArenaCollector` abstract base class (`src/issue_observatory/arenas/base.py`) enforces a consistent interface with two collection modes (`collect_by_terms`, `collect_by_actors`), tier validation, credit estimation, and health checking.

All collected data normalizes into the `content_records` table (`src/issue_observatory/core/models/content.py`), which is range-partitioned by `published_at` (monthly boundaries). This partitioning is well-suited for CO2 afgift research because policy discourse tends to cluster around legislative calendar events, and partition pruning will keep queries efficient as the dataset grows.

### 2.2 Implemented Arenas (18 total)

| Arena | Path | Tiers | Relevance to CO2 Afgift |
|-------|------|-------|------------------------|
| Google Search | `arenas/google_search/` | MEDIUM, PREMIUM | **Critical** -- tracks what search results appear for CO2 afgift queries |
| Google Autocomplete | `arenas/google_autocomplete/` | MEDIUM, PREMIUM | **High** -- reveals public search behavior around the issue |
| RSS Feeds | `arenas/rss_feeds/` | FREE | **Critical** -- 28 Danish news outlets, primary news coverage source |
| Reddit | `arenas/reddit/` | FREE | **Medium** -- r/Denmark discussions |
| Bluesky | `arenas/bluesky/` | FREE | **Medium** -- growing Danish presence, lang:da filtering |
| YouTube | `arenas/youtube/` | FREE (API key) | **High** -- video discourse, political commentary channels |
| GDELT | `arenas/gdelt/` | FREE | **High** -- global news coverage with Danish source filtering |
| Telegram | `arenas/telegram/` | FREE (user account) | **Low-Medium** -- Danish political channels, niche |
| TikTok | `arenas/tiktok/` | MEDIUM | **Low** -- limited Danish political content |
| Via Ritzau | `arenas/ritzau_via/` | FREE | **High** -- press releases from organizations regarding CO2 policy |
| Gab | `arenas/gab/` | FREE | **Low** -- minimal Danish content |
| Event Registry | `arenas/event_registry/` | MEDIUM, PREMIUM | **Critical** -- full-text Danish news with NLP |
| X/Twitter | `arenas/x_twitter/` | MEDIUM, PREMIUM | **High** -- political debate, 13% Danish usage |
| Facebook | `arenas/facebook/` | MEDIUM, PREMIUM | **Critical** -- 84% Danish usage, primary social platform |
| Instagram | `arenas/instagram/` | MEDIUM, PREMIUM | **Medium** -- visual/infographic content |
| Threads | `arenas/threads/` | FREE, MEDIUM | **Low-Medium** -- emerging platform |
| Majestic | `arenas/majestic/` | PREMIUM | **Medium** -- web graph analysis of CO2 policy advocacy sites |
| Common Crawl / Wayback | `arenas/web/` | FREE | **Medium** -- historical baseline, deleted content recovery |

### 2.3 Core Infrastructure Status

| Component | File | Status | CO2 Afgift Readiness |
|-----------|------|--------|---------------------|
| Normalizer | `core/normalizer.py` | Complete | Ready -- handles Danish characters, SHA-256 pseudonymization |
| Credential Pool | `core/credential_pool.py` | Complete | Ready -- multi-key rotation for paid arenas |
| Rate Limiter | `workers/rate_limiter.py` | Complete | Ready -- Redis-backed sliding window |
| Deduplication | `core/deduplication.py` | Complete | Partial -- URL and hash dedup work; near-duplicate detection (fuzzy) absent |
| Snowball Sampling | `sampling/snowball.py` | Complete (backend) | UI blocked (B-01) -- cannot initiate from frontend |
| Credit Service | `core/credit_service.py` | Complete | Ready |
| Descriptive Analysis | `analysis/descriptive.py` | Complete | Gaps -- see Section 6 |
| Network Analysis | `analysis/network.py` | Complete | Functional -- see Section 6 for limitations |
| Export | `analysis/export.py` | Complete | Ready with caveats -- see Section 8 |

---

## 3. Arena Coverage Analysis

### 3.1 Coverage Assessment for CO2 Afgift Discourse

CO2 afgift discourse in Denmark occurs primarily in the following spaces, ordered by expected volume and importance:

1. **National news media** (RSS feeds, Event Registry, GDELT) -- the primary venue for policy coverage. Parliamentary debates, government proposals, expert commentary, and stakeholder reactions are reported here. Coverage: **Strong.** The 28 RSS feeds in `DANISH_RSS_FEEDS` (`src/issue_observatory/config/danish_defaults.py`, line 47) include DR (public broadcaster, 17 feeds), TV2, Politiken, Berlingske, Jyllands-Posten, Information, Borsen (financial daily -- especially important for carbon tax economic analysis), and regional outlets. Event Registry adds full-text article access with Danish NLP.

2. **Facebook** (84% Danish penetration) -- the largest social media arena for Danish public discourse. Interest groups (e.g., Landbrugets climate debate groups, Greenpeace Denmark, Danish Industry), political party pages, and citizen discussion in comments. Coverage: **Conditional.** Depends on Meta Content Library approval or Bright Data fallback. MCL provides engagement metrics and post view counts. Without MCL, Facebook coverage is limited to Bright Data's asynchronous dataset delivery (hours of latency).

3. **X/Twitter** (13% Danish penetration) -- overrepresented in political/media elite discourse. Politicians, journalists, and policy experts disproportionately active here. Coverage: **Available at cost.** TwitterAPI.io at MEDIUM tier ($0.15/1K tweets) is the recommended path. The `lang:da` operator works. 100 reads/month at free tier is unusable for any real study.

4. **Google Search** -- reveals how the issue is framed in search results and what sources dominate public information access. Coverage: **Good.** Serper.dev (MEDIUM) and SerpAPI (PREMIUM) both support `gl=dk`, `hl=da`. Google Autocomplete captures public search patterns.

5. **YouTube** -- increasingly important for Danish policy debate. Channels like DR's YouTube, Altinget, and political party channels publish policy explainers and debates. Coverage: **Good.** Free tier with API key, `relevanceLanguage=da`, `regionCode=DK`. RSS-first strategy for actor-based collection minimizes quota usage.

6. **LinkedIn** (33% Danish penetration) -- professional discourse among policy stakeholders, industry leaders, and researchers. Coverage: **Critical gap.** No automated collection path exists as of February 2026. The arena brief (`docs/arenas/linkedin.md`) documents that DSA Article 40 researcher access is the premium path but is not yet operationalized. The only current data pathway is Zeeschuimer browser capture (manual, non-scalable). Third-party scraping is legally risky (CNIL fined KASPR 240K EUR). **For a CO2 afgift study, LinkedIn discourse from industry stakeholders (Dansk Industri, Landbrug & Fodevarer, green tech companies) would be highly valuable but is currently inaccessible at scale.**

7. **Via Ritzau** -- press releases from organizations making CO2 policy statements (industry associations, NGOs, government ministries). Coverage: **Good.** Free, unauthenticated JSON API. Excellent for tracking when organizations issue formal positions.

8. **Reddit** -- limited but occasionally contains substantive Danish climate policy discussion. Coverage: **Adequate.** Free tier via r/Denmark, r/danish, r/copenhagen, r/aarhus. Content volume for CO2 afgift specifically will be low.

### 3.2 Coverage Gaps

| Gap | Severity | Mitigation |
|-----|----------|------------|
| LinkedIn professional discourse | **High** | Manual Zeeschuimer capture for key stakeholders; NDJSON import endpoint exists (`POST /api/content/import`) |
| Altinget.dk (specialized policy news) | **Medium** | Not in RSS feed list. Altinget is the most important Danish policy-specific news source. Must add their RSS feed to `DANISH_RSS_FEEDS` if available, or use Event Registry. |
| Folketinget.dk (parliamentary proceedings) | **High** | No arena for official parliamentary documents, committee reports, or voting records. These are the authoritative source for CO2 afgift legislative history. Would require a custom arena or manual import. |
| Danish podcasts | **Low** | No audio content arena exists. Some CO2 afgift discourse occurs in policy podcasts (e.g., Altinget Podcast, DR P1 Debat). Out of scope for Phase 1-2. |
| Infomedia | **Blocked** | Explicitly excluded per project specification despite being the most comprehensive Danish news archive. Not available for this project. |
| Snapchat (45% Danish penetration) | **Low** | No public API. Content is ephemeral. Not viable for systematic collection. |

### 3.3 Recommended Arena Activation for CO2 Afgift

**Tier 1 -- Activate immediately (free or low cost):**
- RSS Feeds (free)
- GDELT (free)
- Via Ritzau (free)
- Bluesky (free)
- Reddit (free)
- YouTube (free, API key only)
- Google Autocomplete (medium tier, low cost per query)

**Tier 2 -- Activate with budget allocation:**
- Google Search (medium tier, Serper.dev)
- Event Registry (medium tier, $90/month, 5K tokens)
- X/Twitter (medium tier, TwitterAPI.io, $0.15/1K tweets)

**Tier 3 -- Activate when access is granted:**
- Facebook/Instagram (pending MCL approval or Bright Data subscription)

**Defer or skip:**
- TikTok (low Danish political content volume)
- Gab (negligible Danish presence)
- Telegram (only if specific CO2 afgift channels are identified)
- Majestic (useful for link analysis post-collection, not primary collection)
- Threads (minimal Danish policy content)

---

## 4. Query Design and Search Capabilities

### 4.1 Current Query Design Model

The query design system (`src/issue_observatory/core/models/query_design.py`) provides:

- **SearchTerm** (line 140): Individual terms with types `keyword`, `phrase`, `hashtag`, `url_pattern`
- **ActorList** (line 199): Named sets of actors with sampling method tracking
- **QueryDesign** (line 34): Bundles terms and actor lists with per-arena tier configuration via `arenas_config` JSONB
- **Locale defaults**: `language='da'`, `locale_country='dk'` (lines 96-105)

### 4.2 CO2 Afgift Query Design Requirements

A comprehensive CO2 afgift study requires the following search term categories:

**Primary terms (Danish):**
- `CO2 afgift` (keyword) -- the canonical term
- `CO2-afgift` (keyword) -- hyphenated variant
- `kulstofafgift` (keyword) -- carbon tax/levy
- `klimaafgift` (keyword) -- climate levy
- `drivhusgasafgift` (keyword) -- greenhouse gas levy
- `gron skattereform` (phrase) -- green tax reform
- `gron omstilling` AND `afgift` -- green transition + tax (requires boolean logic NOT currently available)
- `#CO2afgift` (hashtag)
- `#klimaafgift` (hashtag)

**Sector-specific terms (Danish):**
- `CO2 afgift landbrug` (phrase) -- agriculture
- `CO2 afgift industri` (phrase) -- industry
- `CO2 afgift transport` (phrase) -- transport
- `CO2 afgift energi` (phrase) -- energy
- `klimakvote` (keyword) -- emission quotas (related policy instrument)
- `gronskat` (keyword) -- green tax

**English variants (for GDELT, international coverage):**
- `Denmark carbon tax` (phrase)
- `Danish CO2 levy` (phrase)
- `Denmark green tax reform` (phrase)

**URL patterns:**
- `url_pattern: altinget.dk` (policy news)
- `url_pattern: klimaraadet.dk` (Danish Climate Council)
- `url_pattern: kefm.dk` (Ministry of Climate, Energy and Utilities)

### 4.3 Query Design Gaps

**Gap 1: No boolean logic support**

The `SearchTerm` model stores individual terms as flat strings. There is no mechanism for:
- AND combinations: `"CO2 afgift" AND "landbrug"`
- OR grouping: `CO2-afgift OR kulstofafgift OR klimaafgift`
- NOT exclusion: `"CO2 afgift" NOT "EU ETS"` (to exclude EU-level discussions)
- Proximity: `"CO2" NEAR/3 "afgift"` (terms within 3 words of each other)

**Impact on CO2 afgift research:** Without boolean logic, the researcher must create many individual search terms and rely on post-collection filtering to achieve the same effect. This increases both API cost (more queries) and noise (irrelevant results that match individual terms but not the compound intent). For example, searching for `"gron omstilling"` alone will return content about green transition in general, not specifically about CO2 tax within the green transition context.

**Recommended approach:** Add a `query_expression` column to `SearchTerm` or introduce a `TermGroup` model that allows boolean combinations. Each arena collector would parse the expression into platform-native query syntax. Alternatively, implement a simpler "term group" concept where terms within the same group are ANDed and groups are ORed.

**Gap 2: No synonym expansion or term variants**

Danish compound words create variant challenges:
- `CO2 afgift` vs `CO2-afgift` vs `CO2afgift` (space, hyphen, no separator)
- `gron` vs `groen` (o with stroke vs oe digraph)
- `klimaforandringer` vs `klima forandringer` vs `klimaforandring` (singular/plural, compound)

The system has no automatic synonym expansion or Danish morphological awareness at the query level. Each variant must be entered as a separate `SearchTerm`.

**Recommended approach:** Add a `synonyms` TEXT[] column to `SearchTerm` or implement a pre-processing step in each arena collector that expands known Danish compound word variants. The PostgreSQL full-text search index already uses the Danish snowball stemmer for post-collection search, but this does not help with upstream API queries.

**Gap 3: No query template or preset system**

For a recurring research use case like CO2 afgift tracking, researchers need the ability to clone, template, and version query designs. The `QueryDesign` model has `visibility` (private/team/public) but no versioning, cloning, or template mechanism.

**Gap 4: No term weighting or priority**

All search terms have equal weight in collection. For CO2 afgift research, the primary term `"CO2 afgift"` should have higher collection priority and quota allocation than secondary context terms like `"klimakvote"`.

### 4.4 Actor-Based Collection for CO2 Afgift

The actor system is well-designed for this use case. Key actors for CO2 afgift include:

**Government/Parliament:**
- Klimaministeren (Minister for Climate)
- Skatteministeren (Tax Minister)
- Dansk Folketing members on Klima-, Energi- og Forsyningsudvalget
- Klimaraadet (Danish Climate Council)

**Industry/Business:**
- Dansk Industri (DI)
- Landbrug & Fodevarer (Agriculture & Food Council)
- Dansk Erhverv (Danish Chamber of Commerce)
- Borsen financial journalists

**NGOs/Advocacy:**
- Greenpeace Danmark
- Danmarks Naturfredningsforening (DN)
- Concito (green think tank)
- Radet for Gron Omstilling

**Media actors:**
- Altinget klimaredaktion
- DR Nyheder klimajournalister
- Information klimasektion

The `Actor` model (`src/issue_observatory/core/models/actors.py`, line 30) supports `actor_type` values including `person`, `organization`, `media_outlet`, and `government`, which map well to these categories. The `ActorPlatformPresence` model (line 147) allows mapping each canonical actor to their accounts across platforms (e.g., Dansk Industri on Twitter, Facebook, LinkedIn, and YouTube).

**Gap:** The `actor_type` enum is not formally constrained. Adding `think_tank`, `interest_group`, and `political_party` as recognized types would improve categorization for policy-focused research.

---

## 5. Data Collection and Quality

### 5.1 Normalization Pipeline

The `Normalizer` class (`src/issue_observatory/core/normalizer.py`) uses a candidate-key extraction pattern to map heterogeneous platform data to the universal schema. For CO2 afgift research, the relevant quality characteristics are:

**Strengths:**
- Content hash computation (line 286) uses Unicode NFC normalization, whitespace collapsing, and lowercasing before SHA-256, which handles Danish character variations (ae, o-stroke, a-ring) correctly
- Pseudonymization (line 262) uses SHA-256 with a configurable salt, GDPR-compliant for Danish research
- The `raw_metadata` JSONB column preserves all platform-specific fields, allowing post-hoc extraction of platform-specific CO2 afgift indicators

**Weaknesses:**
- Language detection is delegated entirely to each platform's own `language`/`lang` field (line 153). When platforms do not provide a language tag (common for Facebook, Instagram, Telegram), there is no client-side language detection. Danish content may be silently missed or misclassified.
- The `content_type` field (line 154) defaults to `"post"` when the platform does not specify one. This loses the distinction between original posts, replies/comments, reposts/shares, and articles -- all important for CO2 afgift discourse analysis (e.g., distinguishing original commentary from amplification).

### 5.2 Deduplication

The `DeduplicationService` (`src/issue_observatory/core/deduplication.py`) implements:

1. **URL deduplication** (line 116): Normalizes URLs by lowercasing, stripping `www.`, removing tracking parameters (UTM, fbclid, gclid), sorting remaining query parameters, and stripping trailing slashes. This will correctly deduplicate a Berlingske article about CO2 afgift collected via RSS, GDELT, and Event Registry.

2. **Content hash deduplication** (line 183): Finds records with identical SHA-256 content hashes across different platforms/arenas. This catches wire service content (Ritzau dispatches) that appears verbatim in multiple outlets.

3. **Mark-and-sweep** (line 257): Stamps duplicates with `raw_metadata['duplicate_of']` pointing to the canonical record UUID.

**Gaps for CO2 afgift research:**

- **No fuzzy/near-duplicate detection.** Two articles about the same CO2 afgift development that share 80% of their text (e.g., a Ritzau wire story lightly edited by DR and TV2) will not be detected as duplicates because their content hashes differ. This inflates volume counts and distorts engagement aggregations. Implementing MinHash or SimHash for near-duplicate detection would address this.

- **Deduplication is run-scoped.** The `run_dedup_pass` method (line 309) scopes to a single `run_id`. Cross-run deduplication (e.g., the same CO2 afgift article collected in both a daily batch and a live tracking run) requires manual invocation with `query_design_id` scope. There is no automatic global dedup pass.

- **No duplicate exclusion in analysis.** The descriptive analysis functions (`src/issue_observatory/analysis/descriptive.py`) do not filter out records where `raw_metadata->>'duplicate_of' IS NOT NULL`. This means duplicate-marked records still count toward volume, top actors, and engagement distributions. This is a correctness issue for any published analysis.

### 5.3 Content Freshness

| Arena | Latency | Impact on CO2 Afgift Tracking |
|-------|---------|-------------------------------|
| RSS Feeds | 5-15 minutes (polling interval) | Acceptable for daily tracking |
| Bluesky | Near real-time (WebSocket) or polling | Good |
| Reddit | Minutes (API polling) | Good |
| GDELT | 15-minute refresh cycle | Acceptable |
| Event Registry | Near real-time for indexed sources | Good |
| Facebook (Bright Data) | Hours (async dataset delivery) | Problematic for live events |
| X/Twitter (TwitterAPI.io) | Near real-time | Good |
| TikTok | **10-day engagement lag** | Serious -- engagement metrics delayed by 10 days |
| YouTube | Minutes (search API) to hours (RSS) | Acceptable |
| Via Ritzau | Near real-time (JSON API) | Good |

For a CO2 afgift study focused on legislative events (Folketinget debates, ministerial announcements), the RSS and X/Twitter latencies are acceptable. However, if the study includes live tracking during a parliamentary session or a climate summit, the Facebook Bright Data latency (hours) is a significant limitation.

### 5.4 Engagement Metric Reliability

The `UniversalContentRecord` stores four engagement metrics: `views_count`, `likes_count`, `shares_count`, `comments_count` (all nullable BigInteger). The `engagement_score` (Float) field exists but is documented as "computed by analysis layer" and is never populated by any collector.

**CO2 afgift implications:**
- **Cross-platform engagement comparison is not meaningful without normalization.** A YouTube video with 10K views and a Facebook post with 10K likes are not equivalent engagement levels. The `engagement_score` field was designed for this purpose but remains unimplemented.
- **TikTok's 10-day engagement lag** means that any engagement-based analysis of TikTok CO2 afgift content must wait at least 10 days after collection for metrics to stabilize. This is documented in the arena brief but not enforced or surfaced in the analysis UI.
- **RSS feeds provide no engagement data.** News articles collected via RSS will have NULL for all four engagement metrics, making them invisible in engagement-based rankings despite being the primary venue for CO2 afgift coverage. This creates a structural bias toward social media content in any engagement-weighted analysis.

---

## 6. Analysis and Visualization Gaps

### 6.1 Current Analysis Capabilities

The analysis module provides two files:

**`src/issue_observatory/analysis/descriptive.py`:**
- `get_volume_over_time()` -- time series with arena breakdown (granularity: hour/day/week/month)
- `get_top_actors()` -- ranked by post count and total engagement
- `get_top_terms()` -- frequency of search terms matched
- `get_engagement_distribution()` -- mean/median/p95/max for likes/shares/comments/views
- `get_run_summary()` -- per-run aggregate statistics

**`src/issue_observatory/analysis/network.py`:**
- `get_actor_co_occurrence()` -- actors sharing search terms (self-join with `&&` array overlap)
- `get_term_co_occurrence()` -- search terms appearing in the same record
- `get_cross_platform_actors()` -- actors active on 2+ platforms
- `build_bipartite_network()` -- actor-to-term edges

### 6.2 Gaps for CO2 Afgift Analysis

**Gap 1: No sentiment or stance analysis**

For a policy issue like CO2 afgift, the most fundamental analytical question is not "how much discourse is there?" but "what positions are being taken?" The system has no sentiment analysis, stance detection, or framing classification capability. Every record is treated as neutral volume.

**Recommended approach:** Add an enrichment pipeline that:
1. Uses a Danish-language sentiment model (e.g., DaNLP's BERT-based sentiment model, or the Scandinavian Sentiment model from the Alexandra Institute)
2. Stores results in `raw_metadata` JSONB under a standardized key (e.g., `raw_metadata.enrichments.sentiment`)
3. Extends the descriptive analysis to include sentiment distribution over time
4. Enables filtering by sentiment in the content browser

**Gap 2: No topic modeling or frame detection**

CO2 afgift discourse is multidimensional: economic competitiveness, environmental necessity, social fairness (regressive taxation), agricultural impact, EU alignment, and more. The system cannot identify or track these sub-topics/frames.

**Recommended approach:** Implement topic modeling as a post-collection enrichment step:
1. BERTopic or Top2Vec on Danish-language content (requires a Danish BERT embedding model)
2. Store topic assignments in `raw_metadata.enrichments.topic`
3. Add `get_topic_distribution()` to the analysis module
4. Enable topic-filtered views in the content browser

**Gap 3: No temporal event correlation**

The `get_volume_over_time()` function returns raw counts with no context. For CO2 afgift research, a spike in volume on 2026-03-15 is meaningless without knowing that the government announced a new tax rate that day. The system needs:
1. An event registry or annotation system where researchers can mark known events (parliamentary votes, government announcements, expert report releases)
2. Overlay visualization of events on the volume timeline
3. Pre/post event comparison (e.g., discourse volume and sentiment in the 7 days before vs. after an announcement)

**Gap 4: No arena-comparative analysis**

The `get_volume_over_time()` function includes arena breakdown (`arenas` dict in each time bucket), but there is no dedicated function for comparing how the same issue is covered across arenas. For CO2 afgift, a key research question is: Does the framing in news media differ from the framing on social media? Which actors drive the discourse in each arena?

**Recommended analysis additions:**
- `get_arena_comparison(query_design_id, metric)` -- side-by-side arena metrics
- `get_cross_arena_flow(query_design_id)` -- temporal sequence showing which arena covers a story first
- `get_actor_arena_distribution(query_design_id)` -- where each actor's content appears

**Gap 5: No content clustering**

When collecting CO2 afgift content, thousands of records will refer to the same underlying news event (e.g., government announcement) expressed in different words across different platforms. The system has no content clustering capability. Without it, the researcher must manually identify that 500 records from a single day all concern the same announcement.

**Gap 6: Network analysis lacks temporal dimension**

All four network analysis functions operate on static snapshots -- they aggregate across the entire query/run scope without temporal segmentation. For CO2 afgift, understanding how the actor network evolves over time (e.g., new actors entering the debate after a legislative proposal) requires temporal network analysis: network snapshots at configurable intervals (weekly, monthly) with change detection (new nodes, new edges, weight changes).

**Gap 7: The `get_top_terms()` function is limited to matched search terms**

The `get_top_terms()` function (`src/issue_observatory/analysis/descriptive.py`, line 297) unnests the `search_terms_matched` array column. This only shows which of the researcher's own query terms appeared most frequently -- it does not perform any term extraction from the collected text content itself. For CO2 afgift research, identifying emergent terms and phrases (terms the researcher did not search for but that frequently co-occur with the search results) is crucial for discovering new angles and frames.

**Recommended approach:** Add a `get_emergent_terms()` function that:
1. Performs TF-IDF or keyBERT extraction on `text_content` within the query scope
2. Filters out the researcher's own search terms
3. Returns ranked novel terms that may indicate new frames or sub-topics

### 6.3 Visualization

The frontend uses HTMX + Alpine.js + Jinja2 templates. The analysis dashboard (served at `/analysis/{run_id}`) provides HTML views of the descriptive statistics and network data. For CO2 afgift research, the following visualization capabilities are absent:

1. **No interactive timeline** -- volume charts are static HTML; no zoom, pan, or event annotation
2. **No network visualization in the browser** -- GEXF files must be exported and opened in Gephi; no in-browser force-directed graph
3. **No geographic visualization** -- Denmark has strong regional variation in CO2 afgift attitudes (agricultural regions vs. urban centers); no map view exists
4. **No comparison dashboard** -- no side-by-side view of two query designs or two time periods

---

## 7. Danish Language and Locale Support

### 7.1 Current Danish Support

The system's Danish language support is implemented at multiple levels:

**Configuration layer** (`src/issue_observatory/config/danish_defaults.py`):
- `DEFAULT_LANGUAGE = "da"` -- ISO 639-1 Danish
- `DEFAULT_LOCALE_COUNTRY = "DK"` -- ISO 3166-1
- `DANISH_GOOGLE_PARAMS = {"gl": "dk", "hl": "da"}` -- Google geolocation and host language
- `GDELT_DANISH_FILTERS = {"sourcelang": "danish", "sourcecountry": "DA"}` -- GDELT uses FIPS codes
- `BLUESKY_DANISH_FILTER = "lang:da"` -- Bluesky AT Protocol language filter
- `YOUTUBE_DANISH_PARAMS = {"relevanceLanguage": "da", "regionCode": "DK"}` -- YouTube Data API
- `POSTGRES_FTS_LANGUAGE = "danish"` -- PostgreSQL Danish snowball stemmer

**Database layer:**
- Full-text search index: `CREATE INDEX idx_content_fulltext ON content_records USING GIN(to_tsvector('danish', coalesce(text_content, '') || ' ' || coalesce(title, '')))`
- Query design defaults: `language server_default='da'`, `locale_country server_default='dk'`

**Arena-specific:**
- RSS feeds: 28 Danish-language news feeds covering all major national outlets
- Reddit: 4 Danish subreddits (Denmark, danish, copenhagen, aarhus)
- Bluesky: `lang:da` appended to search queries; client-side language filter for actor-based collection
- Via Ritzau: `language=da` parameter
- Event Registry: Uses ISO 639-3 `"dan"` (not `"da"`) -- correctly documented in the arena brief

### 7.2 Danish-Specific Gaps for CO2 Afgift

**Gap 1: No client-side Danish language detection**

Platforms that do not provide a `language` field (Facebook, Instagram, some Telegram channels) will have `language=NULL` in the content record. There is no fallback language detection. For CO2 afgift, this means Danish-language posts from these platforms cannot be reliably filtered by language in the content browser.

**Recommended approach:** Integrate a fast Danish language detector (e.g., `langdetect`, `lingua-py`, or `fasttext lid.176.bin`) as a normalizer enrichment step. When `language` is NULL after platform extraction, run detection on `text_content` and store the result.

**Gap 2: Danish compound word handling in search**

Danish is an agglutinative language with extensive compounding. The term `CO2afgift` (no space) should match content containing `CO2-afgift` (hyphenated) and `CO2 afgift` (spaced). The PostgreSQL Danish snowball stemmer handles this for post-collection full-text search, but upstream API queries to platforms do not benefit from this stemming.

**Impact:** A search for `"CO2 afgift"` on Bluesky will miss posts that write `"CO2-afgift"` or `"CO2afgift"`. The researcher must manually enter all variants as separate search terms.

**Gap 3: o-stroke (oe) encoding variations**

The Danish letter `o` (o with stroke) is sometimes encoded as `oe` in URLs, usernames, and legacy text. The normalizer does not perform o-stroke/oe normalization. For CO2 afgift search, the term `"gron omstilling"` (green transition, where "gron" has an o-stroke) should also match `"groen omstilling"`.

**Gap 4: Danish RSS feed character encoding**

The RSS collector (`src/issue_observatory/arenas/rss_feeds/collector.py`) uses feedparser, which handles encoding well. However, the content browser full-text search uses `to_tsvector('danish', ...)` which requires the content to be stored in proper Unicode NFC form. The normalizer does apply NFC normalization for the content hash (line 305) but this normalized form is not what gets stored in `text_content` -- the raw string from the feed is stored. If any RSS feed delivers content in a non-NFC encoding, the full-text search may miss matches.

### 7.3 GDELT Danish Coverage Quality

GDELT's Danish content has approximately 55% accuracy due to machine translation artifacts. This is documented in the knowledge base (`reports/cross_platform_data_collection.md`). For CO2 afgift research specifically:

- GDELT translates Danish article titles and content to English for its Global Knowledge Graph. The original Danish text is not stored.
- The `sourcelang=danish` filter restricts to articles identified as originally Danish, but language detection errors occur.
- The `sourcecountry=DA` filter restricts to sources geolocated to Denmark.
- **Recommendation for CO2 afgift:** Use GDELT as a volume indicator and source discovery tool, not as a primary text corpus. Cross-reference GDELT-identified articles against RSS feed or Event Registry collections for the actual Danish text.

---

## 8. Export and Integration

### 8.1 Current Export Capabilities

The `ContentExporter` class (`src/issue_observatory/analysis/export.py`) provides five formats:

| Format | Method | Columns | Notes |
|--------|--------|---------|-------|
| CSV | `export_csv()` | 15 flat + optional raw_metadata | UTF-8 BOM for Excel/Danish characters |
| XLSX | `export_xlsx()` | 15 flat | Bold headers, auto-size, frozen panes |
| NDJSON | `export_json()` | All fields | Line-delimited for streaming |
| Parquet | `export_parquet()` | 15 flat (typed) | pyarrow schema with proper types |
| GEXF | `export_gexf()` | Network-dependent | 3 network types: actor, term, bipartite |

The 15 flat columns (`_FLAT_COLUMNS`, line 42): `platform`, `arena`, `content_type`, `title`, `text_content`, `url`, `author_display_name`, `published_at`, `views_count`, `likes_count`, `shares_count`, `comments_count`, `language`, `collection_tier`, `search_terms_matched`.

Export routes exist at:
- `GET /api/content/export/csv` (sync, up to 10K records)
- `POST /api/content/export/async` (async via Celery, unlimited, MinIO download)
- `GET /api/content/export/status/{task_id}` (poll for async completion)

### 8.2 Export Gaps for CO2 Afgift Research

**Gap 1: Missing columns in flat export**

The `_FLAT_COLUMNS` list omits several fields that are important for CO2 afgift analysis:

- `pseudonymized_author_id` -- needed for cross-platform actor matching in external tools
- `content_hash` -- needed for deduplication verification in external analysis
- `author_id` (FK to actors table) -- needed to join with actor metadata
- `collection_run_id` -- needed to trace data provenance
- `query_design_id` -- needed to trace which query produced each record
- `engagement_score` -- designed for cross-platform normalization (currently unpopulated)

**Impact:** Researchers exporting CO2 afgift data to R, Python/pandas, or NVivo for analysis cannot perform entity resolution or deduplication checks without these columns.

**Recommended fix:** Add a configurable column selection mechanism to the export functions, or define an "extended" column list alongside the current flat list.

**Gap 2: No filtered export based on analysis results**

The content export is based on database queries (run_id, query_design_id, date range, full-text search). There is no mechanism to export based on analysis results -- for example, "export only records from the top 10 actors in this network" or "export only records containing these co-occurring terms." For CO2 afgift research, the ability to export a subset identified through network analysis is essential for qualitative coding workflows.

**Gap 3: No annotation or coding export**

The system has no annotation layer. Researchers performing qualitative content analysis of CO2 afgift discourse (e.g., frame coding, argument mapping) cannot store their annotations alongside the content records or export annotated datasets.

**Gap 4: GEXF export builds networks from raw records in memory**

The `_build_actor_gexf()`, `_build_term_gexf()`, and `_build_bipartite_gexf()` methods in `export.py` reconstruct networks from flat content record lists entirely in Python memory (lines 411-647). For a large CO2 afgift dataset (tens of thousands of records), this could be memory-intensive. The SQL-based network functions in `network.py` are more efficient but are not directly wired to the GEXF export.

**Gap 5: No RIS/BibTeX export for academic citation**

For publishing CO2 afgift research, collected news articles and social media posts need to be citable. There is no export format for reference managers (RIS, BibTeX, or CSL-JSON).

### 8.3 Integration Readiness

| External Tool | Integration Status | CO2 Afgift Relevance |
|---------------|-------------------|---------------------|
| Gephi (network analysis) | GEXF export works | High -- actor/term networks |
| R / tidyverse | CSV/Parquet export works | High -- quantitative analysis |
| Python / pandas | CSV/Parquet/NDJSON export works | High -- computational analysis |
| NVivo (qualitative) | CSV export usable but lacks annotations | Medium -- qualitative coding |
| VOSviewer (bibliometric) | No direct export | Low |
| MAXQDA | CSV export usable | Medium |
| Power BI / Tableau | CSV/XLSX export usable | Medium -- dashboard creation |

---

## 9. Prioritized Improvement Roadmap

The following improvements are prioritized by their impact on a CO2 afgift study, feasibility within the current architecture, and estimated effort.

### Priority 1: Pre-Study Blockers (must fix before CO2 afgift data collection)

| ID | Improvement | Effort | Owner | Files Affected |
|----|------------|--------|-------|----------------|
| P1.1 | **Add Altinget RSS feed** to `DANISH_RSS_FEEDS` | 1 hour | Research Agent | `config/danish_defaults.py` |
| P1.2 | **Add duplicate exclusion to analysis queries** -- filter `WHERE raw_metadata->>'duplicate_of' IS NULL` in all descriptive and network analysis functions | 2-4 hours | DB Engineer | `analysis/descriptive.py`, `analysis/network.py` |
| P1.3 | **Extend `_FLAT_COLUMNS` for export** -- add `pseudonymized_author_id`, `content_hash`, `collection_run_id` | 1-2 hours | DB Engineer | `analysis/export.py` |
| P1.4 | **Verify B-02 fix end-to-end** -- confirm term and bipartite GEXF downloads work from the UI | 1 hour | QA Engineer | `analysis/export.py`, frontend templates |
| P1.5 | **Create CO2 afgift use case document** with full query design specification, actor lists, arena activation plan | 4-6 hours | Research Agent | `docs/use_cases/co2_afgift.md` |

### Priority 2: High-Impact Enhancements (significantly improve study quality)

| ID | Improvement | Effort | Owner | Files Affected |
|----|------------|--------|-------|----------------|
| P2.1 | **Client-side Danish language detection** -- fallback when platform does not provide language field | 1-2 days | Core Engineer | `core/normalizer.py`, new dependency |
| P2.2 | **Engagement score normalization** -- implement cross-platform engagement score computation and populate the `engagement_score` column | 2-3 days | DB Engineer | `core/normalizer.py` or new enrichment module |
| P2.3 | **Boolean query support** -- add `TermGroup` model or `query_expression` field to `SearchTerm` | 3-5 days | DB Engineer + Core Engineer | `models/query_design.py`, arena collectors |
| P2.4 | **Near-duplicate detection** (SimHash/MinHash) -- catch lightly-edited wire stories appearing across outlets | 3-5 days | DB Engineer | `core/deduplication.py`, new dependency |
| P2.5 | **Temporal volume comparison** -- add period-over-period analysis and event annotation overlay | 2-3 days | DB Engineer | `analysis/descriptive.py`, API routes |
| P2.6 | **Populate `engagement_score`** -- define and implement the cross-platform normalization formula | 1-2 days | DB Engineer | `core/normalizer.py` or dedicated enrichment |

### Priority 3: Research Depth Enhancements (would significantly enrich findings)

| ID | Improvement | Effort | Owner | Files Affected |
|----|------------|--------|-------|----------------|
| P3.1 | **Danish sentiment analysis enrichment** -- integrate DaNLP or Alexandra Institute sentiment model | 3-5 days | Core Engineer | New enrichment module, `analysis/descriptive.py` |
| P3.2 | **Emergent term extraction** -- TF-IDF or keyBERT on collected text content | 2-3 days | DB Engineer | `analysis/descriptive.py` or new module |
| P3.3 | **Temporal network snapshots** -- weekly/monthly actor co-occurrence network evolution | 3-5 days | DB Engineer | `analysis/network.py` |
| P3.4 | **Cross-arena narrative flow analysis** -- which arena covers a story first, how it propagates | 5-7 days | DB Engineer + Research Agent | New analysis module |
| P3.5 | **Topic modeling enrichment** (BERTopic on Danish text) | 5-7 days | Core Engineer | New enrichment module |
| P3.6 | **Folketinget.dk parliamentary proceedings arena** -- custom arena for legislative documents | 5-7 days | Core Engineer + Research Agent | New arena module, arena brief |

### Priority 4: Nice-to-Have (improve workflow but not analytical substance)

| ID | Improvement | Effort | Owner | Files Affected |
|----|------------|--------|-------|----------------|
| P4.1 | **Query design cloning and versioning** | 2-3 days | DB Engineer + Frontend | `models/query_design.py`, API routes, templates |
| P4.2 | **Content annotation layer** for qualitative coding | 5-7 days | DB Engineer + Frontend | New model, API routes, templates |
| P4.3 | **In-browser network visualization** (d3.js force-directed graph) | 3-5 days | Frontend Engineer | Templates, static assets |
| P4.4 | **RIS/BibTeX export** for academic citation | 1-2 days | DB Engineer | `analysis/export.py` |
| P4.5 | **Filtered export from analysis results** (export only records matching network/top-actor criteria) | 2-3 days | DB Engineer | API routes, `analysis/export.py` |

---

## 10. Architecture and Technical Debt

### 10.1 Architectural Strengths

1. **Modular arena architecture.** Each arena is fully self-contained with its own collector, router, tasks, and config. Adding a new arena (e.g., Folketinget.dk) follows a well-defined pattern and does not require changes to core infrastructure.

2. **Universal content record.** The single normalized table with monthly range partitioning is a sound choice. The composite PK `(id, published_at)` enables efficient partition pruning for time-scoped queries.

3. **JSONB for extensibility.** The `raw_metadata` column on `content_records` and the `metadata` column on `actors` allow schema-free extension. This is where sentiment scores, topic labels, and other enrichment data should be stored without requiring Alembic migrations.

4. **Three-tier pricing model.** The `Tier` enum (FREE/MEDIUM/PREMIUM) with per-arena configuration via `arenas_config` JSONB is well-designed for cost management. A CO2 afgift study can start at free tier and selectively upgrade arenas as budget allows.

5. **GDPR-by-design.** SHA-256 pseudonymization with configurable salt, environment-variable-based secret management, and the actor entity resolution model that separates canonical identity from platform-specific accounts.

### 10.2 Technical Debt Items

**TD-1: Raw SQL in analysis module**

Both `descriptive.py` and `network.py` use `text()` SQL strings extensively rather than SQLAlchemy ORM queries. This is documented as intentional (PostgreSQL-specific constructs like `date_trunc`, `unnest`, `percentile_cont`, array overlap `&&`). While functionally correct, it:
- Makes the analysis layer fragile to schema changes (column renames, table restructures)
- Prevents SQLAlchemy's query composition features (e.g., adding filters dynamically)
- Requires manual bind parameter management with string interpolation for filter clauses

**Impact on CO2 afgift:** Adding new analysis functions (sentiment distribution, topic distribution, arena comparison) will require additional raw SQL strings, increasing the maintenance burden.

**TD-2: Duplicate filter construction across descriptive.py and network.py**

Both `_build_content_filters()` in descriptive.py (line 74) and `_build_run_filter()` in network.py (line 62) implement nearly identical filter construction logic. This violates DRY and means any new filter parameter (e.g., language, content_type, sentiment) must be added in two places.

**TD-3: GEXF export reconstructs networks from records instead of using network.py functions**

The `ContentExporter` GEXF methods (`_build_actor_gexf`, `_build_term_gexf`, `_build_bipartite_gexf`) reconstruct networks from flat content record dicts in Python memory. Meanwhile, `network.py` has SQL-optimized versions of the same computations (`get_actor_co_occurrence`, `get_term_co_occurrence`, `build_bipartite_network`). The export should call the network analysis functions and convert the graph dicts to GEXF XML, rather than duplicating the network construction logic.

**TD-4: No enrichment pipeline architecture**

There is no formal pipeline for post-collection enrichments (sentiment, language detection, topic modeling, entity linking). Each enrichment would need to be implemented ad-hoc. A proper enrichment pipeline with:
- A pluggable enricher interface (similar to `ArenaCollector`)
- An enrichment task queue (Celery)
- Standardized storage in `raw_metadata.enrichments`
- Enrichment status tracking per record

...would make it significantly easier to add the analytical capabilities needed for CO2 afgift research.

**TD-5: No data versioning or audit trail for content records**

Content records are mutable (via the deduplication mark_duplicates and potential re-collection). There is no audit trail of changes. For a published CO2 afgift study, the ability to reproduce the exact dataset at a given point in time is important. The `CreditTransaction` model provides an immutable audit log for credit events, but no analogous mechanism exists for content record changes.

**TD-6: Engagement metrics are write-once**

Engagement metrics (likes, shares, comments, views) are captured at collection time and never updated. For content collected early in its lifecycle (e.g., a breaking CO2 afgift announcement), the engagement metrics will be significantly underrepresented. There is no re-collection or metric refresh mechanism, except for TikTok which documents the 10-day lag but also does not implement re-collection.

### 10.3 Scalability Considerations for CO2 Afgift

A comprehensive CO2 afgift study collecting from 8-10 arenas over a 6-month period could generate:

| Arena | Estimated Monthly Records | 6-Month Total |
|-------|--------------------------|---------------|
| RSS Feeds (filtered) | 200-500 | 1,200-3,000 |
| GDELT (filtered) | 500-1,000 | 3,000-6,000 |
| Event Registry (filtered) | 200-400 | 1,200-2,400 |
| X/Twitter | 1,000-3,000 | 6,000-18,000 |
| Facebook (if available) | 2,000-5,000 | 12,000-30,000 |
| YouTube | 100-300 | 600-1,800 |
| Bluesky | 50-200 | 300-1,200 |
| Reddit | 50-100 | 300-600 |
| Via Ritzau | 50-100 | 300-600 |
| Google Search | 500-1,000 per batch | 3,000-6,000 |

**Estimated total: 28,000-70,000 records over 6 months.**

This volume is well within the system's capacity. The monthly partitioning will distribute records across 6-7 partitions. The GIN indexes on `search_terms_matched` and `raw_metadata` will handle the query load. The actor co-occurrence self-join in `get_actor_co_occurrence()` could become expensive beyond ~50K records; the `LIMIT` parameter (default 200 edges) mitigates this.

### 10.4 Cost Estimate for CO2 Afgift Study

| Arena | Tier | Monthly Cost | 6-Month Cost |
|-------|------|-------------|-------------|
| RSS Feeds | FREE | $0 | $0 |
| GDELT | FREE | $0 | $0 |
| Via Ritzau | FREE | $0 | $0 |
| Bluesky | FREE | $0 | $0 |
| Reddit | FREE | $0 | $0 |
| YouTube | FREE (API key) | $0 | $0 |
| Google Autocomplete | MEDIUM (Serper.dev) | ~$5-10 | ~$30-60 |
| Google Search | MEDIUM (Serper.dev) | ~$10-20 | ~$60-120 |
| Event Registry | MEDIUM | $90 | $540 |
| X/Twitter | MEDIUM (TwitterAPI.io) | ~$5-15 | ~$30-90 |
| Facebook | MEDIUM (Bright Data) | ~$50-100 | ~$300-600 |
| **Total** | | **~$160-235/month** | **~$960-1,410** |

Note: If Meta Content Library is approved (free for researchers), the Facebook cost drops to $0, reducing the total to ~$660-810 for 6 months.

---

## Appendix A: File Reference Index

All file paths referenced in this report are relative to the project root (`/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/`):

| File | Absolute Path | Relevance |
|------|---------------|-----------|
| Universal Content Record | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/models/content.py` | Central schema, engagement metrics, partitioning, indexes |
| Query Design models | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/models/query_design.py` | Search terms, actor lists, arena config |
| Collection models | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/models/collection.py` | Run/task tracking, credit transactions |
| Actor models | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/models/actors.py` | Entity resolution, cross-platform presence |
| Normalizer | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/normalizer.py` | Pseudonymization, content hashing, field extraction |
| Deduplication | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/deduplication.py` | URL normalization, hash dedup, mark-and-sweep |
| Danish defaults | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/config/danish_defaults.py` | RSS feeds, locale params, FTS config |
| Descriptive analysis | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/analysis/descriptive.py` | Volume, top actors, top terms, engagement |
| Network analysis | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/analysis/network.py` | Co-occurrence, cross-platform actors, bipartite |
| Export | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/analysis/export.py` | CSV, XLSX, NDJSON, Parquet, GEXF |
| Arena base class | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/arenas/base.py` | Collector interface, Tier enum |
| Research status | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/docs/status/research.md` | Arena brief status, open blockers |

## Appendix B: CO2 Afgift Actor Seed List (Proposed)

The following actors should be pre-populated in the actor directory for a CO2 afgift study. This is not exhaustive but covers the primary institutional stakeholders.

| Canonical Name | Actor Type | Platforms Expected |
|---------------|------------|-------------------|
| Klimaministeriet | government | Twitter, Facebook, YouTube |
| Skatteministeriet | government | Twitter, Facebook |
| Klimaraadet | government | Twitter, Facebook, YouTube |
| Dansk Industri (DI) | organization | Twitter, Facebook, LinkedIn, YouTube |
| Landbrug & Fodevarer | organization | Twitter, Facebook, LinkedIn |
| Dansk Erhverv | organization | Twitter, Facebook, LinkedIn |
| Greenpeace Danmark | organization | Twitter, Facebook, Instagram, YouTube |
| Danmarks Naturfredningsforening | organization | Twitter, Facebook, Instagram |
| Concito | think_tank | Twitter, Facebook, LinkedIn |
| Radet for Gron Omstilling | organization | Twitter, Facebook |
| DR Nyheder | media_outlet | Twitter, Facebook, YouTube, Bluesky |
| TV2 Nyheder | media_outlet | Twitter, Facebook, YouTube |
| Altinget | media_outlet | Twitter, Facebook, LinkedIn |
| Borsen | media_outlet | Twitter, Facebook, LinkedIn |
| Politiken | media_outlet | Twitter, Facebook |
| Berlingske | media_outlet | Twitter, Facebook |
| Information | media_outlet | Twitter, Facebook |

---

*End of report. This document should be reviewed by the full agent team before initiating CO2 afgift data collection. Priority 1 items (P1.1-P1.5) should be completed first, followed by the creation of a formal use case document at `/docs/use_cases/co2_afgift.md`.*
