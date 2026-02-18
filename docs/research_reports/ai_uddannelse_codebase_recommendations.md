# Research Strategist Report: Codebase Evaluation for Marres-Style Issue Mapping of "AI og uddannelse"

**Author:** Research & Knowledge Agent (The Strategist)
**Date:** 2026-02-18
**Status:** Final
**Scope:** Full codebase evaluation of the Issue Observatory for supporting Noortje Marres-style issue mapping of "AI og uddannelse" (AI and education) in Danish public discourse, constrained to FREE and MEDIUM tiers

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-18 | Initial report. Full codebase evaluation for Marres-style issue mapping of AI og uddannelse. |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Issue Mapping Methodology Support](#2-issue-mapping-methodology-support)
3. [Arena Coverage for AI og uddannelse](#3-arena-coverage-for-ai-og-uddannelse)
4. [Query Design Capabilities for Explorative Issue Mapping](#4-query-design-capabilities-for-explorative-issue-mapping)
5. [Analysis Pipeline Gaps for Issue Mapping](#5-analysis-pipeline-gaps-for-issue-mapping)
6. [Visualization and Export for Issue Mapping](#6-visualization-and-export-for-issue-mapping)
7. [Technical Debt Impact on Issue Mapping](#7-technical-debt-impact-on-issue-mapping)
8. [Recommended Actor Seed List](#8-recommended-actor-seed-list)
9. [Recommended Query Design Specification](#9-recommended-query-design-specification)
10. [Cost Estimate at Free/Medium Tiers](#10-cost-estimate-at-freemedium-tiers)
11. [Prioritized Improvement Roadmap](#11-prioritized-improvement-roadmap)
12. [Comparison to CO2 Afgift Recommendations](#12-comparison-to-co2-afgift-recommendations)

---

## 1. Executive Summary

### What is the research question?

This evaluation assesses how well the Issue Observatory codebase supports Noortje Marres-style issue mapping of "AI og uddannelse" (AI and education) in Danish public discourse. Issue mapping in the Marres tradition is not monitoring or sentiment tracking. It is a specific digital methods practice with five core operations:

1. **Actor mapping**: Identifying who speaks about the issue and from what institutional position
2. **Discourse association detection**: Discovering what other topics, frames, and concerns become connected to the issue
3. **Controversy identification**: Finding where actors disagree, form alliances, or contest definitions
4. **Cross-platform tracing**: Following how the issue travels between media arenas
5. **Network visualization**: Producing visual maps of the actor-issue-discourse topology

### Overall assessment: approximately 55-60% ready for Marres-style issue mapping

This is a lower readiness score than the CO2 afgift evaluation (75-80%) because issue mapping has fundamentally different analytical requirements from discourse tracking. The Issue Observatory was designed primarily as a data collection and basic descriptive analysis platform. Its strengths -- multi-arena collection, universal content normalization, actor entity resolution, GEXF export -- provide an excellent data foundation. However, the analytical layer that transforms collected data into an issue map is largely absent.

### Critical findings

1. **No discourse association detection.** The system can identify which of the researcher's own search terms appear in collected content (`search_terms_matched`), but it cannot discover emergent associations -- the topics, frames, and concerns that actors connect to AI og uddannelse without the researcher having pre-specified them. This is the single most important capability for Marres-style issue mapping and it does not exist anywhere in the codebase. Neither the `get_top_terms()` function (`/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/analysis/descriptive.py`, line 297) nor any other analysis function extracts terms from the actual text content. See Section 5, Gap 1.

2. **No actor role classification.** The `Actor` model (`/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/models/actors.py`, line 30) stores `actor_type` as an unconstrained string, with no ability to distinguish between an actor who speaks about the issue (e.g., a university rector publishing a statement), an actor who is mentioned in discourse (e.g., ChatGPT as a technology artifact), and an actor who is quoted as a source (e.g., a researcher cited in a news article). This three-way distinction (speaker / mentioned entity / quoted source) is fundamental to issue mapping. See Section 2.1.

3. **No stance or position mapping.** Issue mapping requires knowing not just that an actor speaks about AI og uddannelse, but what position they take -- are they advocating for integration of AI tools in teaching, warning about academic integrity risks, or demanding regulation? No stance detection, frame classification, or position coding capability exists. The `UniversalContentRecord` (`/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/models/content.py`) has no column for this, and no enrichment pipeline exists to add it post-collection. See Section 5, Gap 2.

4. **No controversy detection.** The network analysis module (`/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/analysis/network.py`) builds co-occurrence networks where edges represent shared search terms. This produces association networks, not controversy networks. Two actors who both mention "AI og uddannelse" but take diametrically opposed positions appear as connected nodes with the same edge weight as two actors who agree entirely. There is no mechanism to detect or represent disagreement. See Section 2.5.

5. **Network analysis lacks the temporal dimension essential for issue mapping.** All four network functions (`get_actor_co_occurrence`, `get_term_co_occurrence`, `get_cross_platform_actors`, `build_bipartite_network`) produce static snapshots. Marres-style issue mapping requires temporal network analysis to show how the issue's contours evolve -- when new actors enter, when discourse associations shift, when controversies intensify or resolve. See Section 5, Gap 5.

6. **The bipartite network is structurally correct for issue mapping but limited by search-term-only nodes.** The `build_bipartite_network()` function (`/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/analysis/network.py`, line 523) creates actor-to-term edges, which is the right topology for an issue map. However, the "term" nodes are only the researcher's pre-specified search terms, not emergent discourse associations extracted from the text. A true issue map would have actor nodes connected to discourse-topic nodes discovered through text analysis. See Section 5, Gap 3.

### What works well for issue mapping

- **Actor entity resolution across platforms.** The `Actor` / `ActorPlatformPresence` / `ActorAlias` model hierarchy (`/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/models/actors.py`) is precisely what issue mapping needs: a canonical actor identity with verified cross-platform presence. When DR Nyheder publishes about AI og uddannelse on YouTube, Twitter, and their website, entity resolution ensures all three appearances are attributed to the same actor node in the issue map.

- **Snowball sampling for actor discovery.** The `SnowballSampler` (`/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/sampling/snowball.py`) and `NetworkExpander` (`/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/sampling/network_expander.py`) implement iterative actor discovery from seed actors via follows/followers (Bluesky), featured channels (YouTube), and comment mentions (Reddit). This is directly useful for building the actor component of an issue map: start with known AI og uddannelse stakeholders and discover connected actors algorithmically.

- **Content similarity-based actor discovery.** The `SimilarityFinder.find_similar_by_content()` method (`/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/sampling/similarity_finder.py`, line 261) uses TF-IDF cosine similarity on collected text content to discover actors who produce similar content. For issue mapping, this can identify actors who write about similar topics even if they are not socially connected on any platform.

- **GEXF export for Gephi.** The `ContentExporter.export_gexf()` method (`/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/analysis/export.py`, line 653) produces three network types (actor co-occurrence, term co-occurrence, bipartite) in GEXF 1.3 format. Gephi is the standard tool for producing the visual issue maps that are the output of Marres-style research. The GEXF export pipeline is functional for actor networks but has the open blocker B-02 for term and bipartite networks.

- **Cross-platform actor tracking.** The `get_cross_platform_actors()` function (`/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/analysis/network.py`, line 445) specifically identifies actors present on multiple platforms. For AI og uddannelse, knowing that the rector of KU appears on LinkedIn, in news media RSS, and on Twitter simultaneously strengthens the actor mapping.

---

## 2. Issue Mapping Methodology Support

This section evaluates the five core operations of Marres-style issue mapping against the current codebase.

### 2.1 Actor Extraction and Tracking

**Assessment: Strong foundation, missing role classification**

The codebase provides three levels of actor handling:

**Level 1: Raw author data (collection layer)**

Every `UniversalContentRecord` stores `author_platform_id`, `author_display_name`, and `pseudonymized_author_id`. These are populated by the `Normalizer` (`/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/normalizer.py`, line 166-196) from platform-specific fields. This captures the speaker -- the actor who published the content.

**Level 2: Canonical actor identity (entity resolution layer)**

The `Actor` model with `ActorAlias` and `ActorPlatformPresence` enables cross-platform identity resolution. The `author_id` FK on `UniversalContentRecord` (line 157) links each piece of content to a canonical actor entity.

**Level 3: Actor sampling and discovery (sampling layer)**

The `SnowballSampler`, `NetworkExpander`, and `SimilarityFinder` provide algorithmic actor discovery. The `ActorListMember.added_by` field (line 248 of actors.py) tracks how each actor was discovered: `'manual'`, `'snowball'`, `'network'`, or `'similarity'`.

**Gaps for issue mapping:**

| Gap | Impact | Description |
|-----|--------|-------------|
| No actor role classification | **Critical** | The system only captures the speaking actor (the author). In news media coverage of AI og uddannelse, the author (journalist) is distinct from the mentioned actors (ChatGPT, KU, Uddannelsesministeriet) and quoted sources ("ifølge professor X..."). Issue mapping needs all three roles. |
| No actor stance/position | **Critical** | Actors are tracked by volume and engagement, not by what position they take on the issue. See Section 5, Gap 2. |
| `actor_type` is unconstrained | **Medium** | The field accepts any string. For AI og uddannelse, adding formal types (`educational_institution`, `student_organization`, `teachers_union`, `tech_company`, `research_center`, `think_tank`, `political_actor`) would enable typed network partitioning in Gephi. |
| No actor influence metrics beyond follower count | **Low** | `ActorPlatformPresence.follower_count` (actors.py line 191) is the only influence indicator. Betweenness centrality, eigenvector centrality, or brokerage scores would be more relevant for issue mapping. However, these can be computed in Gephi after export. |

### 2.2 Discourse Association Detection

**Assessment: Not implemented**

Discourse association detection is the process of discovering which other topics, frames, concepts, and concerns become attached to the issue under study. In the Marres tradition, this is what gives the "map" its substance -- not just who speaks, but what discursive connections they make.

For AI og uddannelse, expected discourse associations include:
- "Snyd" / "plagiat" (cheating / plagiarism)
- "Akademisk integritet" (academic integrity)
- "Digital kompetencer" (digital competencies)
- "Fremtidens arbejdsmarked" (future labor market)
- "GDPR" / "persondata" (data protection in educational contexts)
- "Eksamen" / "eksaminationsformer" (examination formats)
- "Undervisningskvalitet" (teaching quality)
- "ChatGPT" / "kunstig intelligens" (specific technology artifacts)

The system has no capability to discover these associations automatically. The `get_top_terms()` function (`descriptive.py`, line 297) only counts occurrences of the researcher's own search terms. It does not perform any form of:

- Named entity extraction from text content
- Key phrase extraction (TF-IDF, RAKE, KeyBERT)
- Topic modeling (BERTopic, LDA, Top2Vec)
- Co-word analysis on the full text corpus (as opposed to the `search_terms_matched` array)
- Frame detection or classification

**Why this matters specifically for AI og uddannelse:** The AI-in-education issue is at a formative stage in Danish public discourse (unlike CO2 afgift, which has established policy frames). New discourse associations are likely forming rapidly -- for example, a connection between "AI og uddannelse" and "social ulighed" (social inequality) might emerge when a report shows that AI tutoring tools benefit students from privileged backgrounds disproportionately. The system cannot detect this emergence.

### 2.3 Network Construction

**Assessment: Partially suitable, needs extension**

The network analysis module provides four network types:

| Network Type | Function | Issue Mapping Suitability |
|---|---|---|
| Actor co-occurrence | `get_actor_co_occurrence()` | **Partial.** Shows which actors share search terms. Does not show actor-to-issue discourse connections or disagreement. Suitable as a starting point for actor mapping. |
| Term co-occurrence | `get_term_co_occurrence()` | **Limited.** Only uses pre-specified search terms, not emergent terms. Would need to operate on extracted discourse topics to be useful for issue mapping. |
| Cross-platform actors | `get_cross_platform_actors()` | **Good.** Directly useful for identifying actors who engage with AI og uddannelse across multiple arenas. |
| Bipartite actor-term | `build_bipartite_network()` | **Architecturally correct but data-limited.** The right graph topology for an issue map (actors linked to discourse topics), but term nodes are only search terms, not discourse associations. |

**What issue mapping needs that is missing:**

1. **Actor-discourse bipartite network with extracted topics** -- not search terms but topics discovered from the text corpus. This is the canonical issue map topology.
2. **Controversy network** -- actors linked by disagreement edges (opposing positions on the same sub-issue). Requires stance detection.
3. **Actor-arena membership network** -- which actors appear in which arenas, revealing media landscape structure.
4. **Temporal network slices** -- the same network at different time points, showing evolution of the issue map.

### 2.4 Cross-Platform Tracing

**Assessment: Infrastructure exists, analytical functions missing**

The data model supports cross-platform tracing: every `UniversalContentRecord` has `platform`, `arena`, and `published_at` fields, and the `get_cross_platform_actors()` function identifies actors present on multiple platforms. The deduplication service (`/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/deduplication.py`) detects when the same content appears across arenas via URL and hash matching.

**What is missing for issue tracing:**

- **Cross-arena flow analysis.** For AI og uddannelse, a key research question is: does the issue originate in news media (a Politiken feature on AI in universities) and then propagate to social media (reactions on Twitter, Reddit, Bluesky)? Or does it emerge bottom-up (a student TikTok about ChatGPT goes viral, then news media covers it)? The system has no function to detect temporal propagation sequences across arenas.
- **Source-to-coverage tracking.** Via Ritzau press releases about AI og uddannelse (from universities, unions, or ministries) can be matched against subsequent news coverage via URL/hash dedup, but there is no dedicated analysis function that traces the source-to-coverage chain and measures amplification.
- **Issue trajectory visualization.** No timeline showing which arenas covered the issue first, second, third, with volume and actor composition per arena at each time point.

### 2.5 Controversy Identification

**Assessment: Not implemented**

Controversy identification requires detecting that actors take opposing positions on the same sub-issue. This is the hardest analytical challenge for any issue mapping system and is typically done through a combination of:

1. **Stance classification** (automated or manual): Does this content support, oppose, or take a neutral position on X?
2. **Claim extraction**: What specific claims does this content make about AI og uddannelse?
3. **Alignment analysis**: Which actors align with which claims?

None of these capabilities exist in the codebase. The actor co-occurrence network (`get_actor_co_occurrence()`) conflates agreement and disagreement because the edge weight is based on shared search terms, not shared or opposing positions.

**For AI og uddannelse**, expected controversies include:
- **Pro-integration vs. pro-prohibition**: Should universities allow or ban AI tools for student assignments?
- **Skills vs. knowledge**: Does AI change what students need to learn?
- **Equity**: Does AI-assisted education increase or decrease educational inequality?
- **Danish vs. English**: Should AI tools used in Danish education support the Danish language specifically?
- **Regulation approach**: Should regulation come from institutions (university-level policies), the sector (ministerial guidelines), or the EU (AI Act)?

**Recommended approach for the issue mapping workflow:** Given the absence of automated controversy detection, the recommended approach is a hybrid workflow:

1. Collect data using the Issue Observatory's multi-arena infrastructure
2. Export to CSV/XLSX for qualitative coding of stance and controversy in NVivo or MAXQDA
3. Import coded annotations back (requires annotation import capability -- see Section 5, Gap 4)
4. Build controversy networks from the coded data in Gephi

This hybrid workflow is methodologically sound for the Marres tradition, which emphasizes interpretive analysis over fully automated classification. However, it requires the annotation/coding import pathway that does not currently exist.

---

## 3. Arena Coverage for AI og uddannelse

### 3.1 Where Does the AI og uddannelse Discussion Happen?

The AI og uddannelse issue in Denmark is distributed across a different set of arenas than the CO2 afgift issue. Key differences:

1. **LinkedIn is more important** for AI og uddannelse than for CO2 afgift. University rectors, professors, education policy professionals, and tech company representatives use LinkedIn as their primary professional discourse platform. For CO2 afgift, industry lobbyists and politicians drove the LinkedIn discourse; for AI og uddannelse, the academic and technology sectors are even more LinkedIn-concentrated.

2. **YouTube is more important** because educational institutions and edtech companies produce video content (lectures, demos, policy discussions) about AI in education. Several Danish university channels have dedicated AI og uddannelse content series.

3. **TikTok and Instagram are more relevant** than for CO2 afgift because student discourse about AI tools (ChatGPT, Copilot) happens primarily on these platforms. Student-driven content -- study tips involving AI, complaints about university policies, and demonstrations of AI-assisted work -- is a distinctive feature of this issue.

4. **Folketinget.dk is less central** (at least for now). AI og uddannelse is not yet at the legislative proposal stage in Denmark the way CO2 afgift was. The discourse is currently more institutional (university policies) and sectoral (ministerial guidelines) than parliamentary.

5. **Specialized education media** are important venues. Altinget (policy news, not in the RSS list), Folkeskolen.dk (teachers' professional outlet), Magisterbladet (DM union magazine), and Gymnasieskolen (upper secondary teachers' outlet) are all relevant.

### 3.2 Arena Assessment at Free/Medium Tiers

| Arena | Path | Tiers Available | AI og uddannelse Relevance | Coverage Assessment |
|-------|------|-----------------|---------------------------|---------------------|
| RSS Feeds | `arenas/rss_feeds/` | FREE | **Critical** | Strong for national news; missing education-specific outlets (see Section 3.3) |
| Google Search | `arenas/google_search/` | MEDIUM | **High** | Reveals how the issue is framed in search results, which sources dominate |
| Google Autocomplete | `arenas/google_autocomplete/` | MEDIUM | **High** | Captures public search patterns -- "AI i folkeskolen", "ChatGPT eksamen", etc. |
| YouTube | `arenas/youtube/` | FREE | **High** | University channels, edtech demos, policy discussions, student content |
| Reddit | `arenas/reddit/` | FREE | **Medium** | r/Denmark discussions about AI in education; student perspectives |
| Bluesky | `arenas/bluesky/` | FREE | **Medium** | Growing Danish academic presence; some education policy actors active |
| GDELT | `arenas/gdelt/` | FREE | **Medium** | Volume indicator for international coverage of Danish AI education discourse |
| Via Ritzau | `arenas/ritzau_via/` | FREE | **Medium** | University and union press releases about AI policies |
| Event Registry | `arenas/event_registry/` | MEDIUM | **High** | Full-text Danish news with NLP; superior to RSS for textual analysis |
| X/Twitter | `arenas/x_twitter/` | MEDIUM | **High** | Education policy debate, journalist discourse, political commentary |
| Facebook | `arenas/facebook/` | MEDIUM | **Critical** | Parent groups, teacher groups, university groups -- 84% Danish penetration |
| Instagram | `arenas/instagram/` | MEDIUM | **Medium** | Student perspectives on AI in education |
| TikTok | `arenas/tiktok/` | MEDIUM | **Medium-High** | Student discourse about ChatGPT, AI tools, study practices |
| Threads | `arenas/threads/` | FREE | **Low** | Minimal Danish education discourse |
| Telegram | `arenas/telegram/` | FREE | **Low** | No identified Danish AI education channels |
| Gab | `arenas/gab/` | FREE | **Negligible** | No Danish education discourse |
| LinkedIn | `arenas/linkedin/` (no collector) | N/A | **Critical** | Highest-value gap -- see Section 3.3 |
| Majestic | `arenas/majestic/` | PREMIUM (excluded) | N/A | Web graph analysis not available at free/medium |

### 3.3 Coverage Gaps Specific to AI og uddannelse

| Gap | Severity | Description | Mitigation |
|-----|----------|-------------|------------|
| **LinkedIn** | **Critical** | The most important professional discourse platform for university rectors, professors, EdTech professionals, and education policy actors. No automated collection path exists. The arena brief (`/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/docs/arenas/linkedin.md`) documents that DSA Article 40 researcher access is the premium path but is not yet operationalized. | Manual Zeeschuimer browser capture for key actors; NDJSON import via `POST /api/content/import`. Budget 30-60 minutes per data collection session for manual LinkedIn capture. |
| **Altinget.dk** | **High** | The most important Danish policy news source. Altinget has a dedicated uddannelse (education) section and frequently covers AI policy. Not in `DANISH_RSS_FEEDS` (`/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/config/danish_defaults.py`). | Add Altinget RSS feed. Also available via Event Registry at MEDIUM tier. |
| **Folkeskolen.dk** | **High** | The professional outlet of Danmarks Laererforening (Danish Teachers' Union). Primary venue for teacher discourse about AI in education. | Verify RSS feed availability; add to `DANISH_RSS_FEEDS` if available. Otherwise, use Event Registry. |
| **Magisterbladet** | **Medium** | DM union magazine. Covers AI in higher education from the academic staff perspective. | Check for RSS feed; otherwise manual or Event Registry. |
| **Gymnasieskolen** | **Medium** | Upper secondary teachers' outlet. Covers AI policy in gymnasiet specifically. | Check for RSS feed; otherwise manual or Event Registry. |
| **University websites** | **Medium** | Official AI policies, strategy documents, and news items from KU, DTU, AU, CBS, SDU, AAU, RUC, ITU. Most have press/news sections but are not systematically monitored. | Add university news RSS feeds to `DANISH_RSS_FEEDS` if available. URL patterns for Google Search (`site:ku.dk`, `site:dtu.dk`). |
| **Uddannelses- og Forskningsstyrelsen (UFM)** | **Medium** | The Danish Agency for Education and Research publishes AI-in-education guidelines. No systematic monitoring. | Via Ritzau press releases + Google Search with `site:ufm.dk`. |
| **Student platforms** | **Low** | Student newspapers (Uniavisen, Universitetsavisen, etc.) are not in the RSS feed list. TikTok and Instagram capture some student discourse. | Add student newspaper RSS feeds where available. |

### 3.4 Recommended Arena Activation for AI og uddannelse Issue Mapping

**Phase A -- Activate immediately (free tier, no cost):**

| Arena | Tier | Purpose for Issue Mapping |
|-------|------|--------------------------|
| RSS Feeds | FREE | National news coverage + education-specific outlets (after adding feeds) |
| GDELT | FREE | Volume indicator and source discovery |
| Bluesky | FREE | Academic/policy actor discourse |
| Reddit | FREE | Student perspectives, public debate |
| YouTube | FREE | Institutional content, educational video discourse |
| Via Ritzau | FREE | Official press releases from universities and unions |
| Google Autocomplete | MEDIUM (low cost) | Public search behavior around AI og uddannelse |

**Phase B -- Activate with budget (medium tier):**

| Arena | Tier | Purpose for Issue Mapping |
|-------|------|--------------------------|
| Google Search | MEDIUM | Search result framing and source dominance |
| Event Registry | MEDIUM | Full-text Danish news with NLP |
| X/Twitter | MEDIUM | Elite discourse, political/academic debate |

**Phase C -- Activate when access granted or budget permits:**

| Arena | Tier | Purpose for Issue Mapping |
|-------|------|--------------------------|
| Facebook | MEDIUM | Broadest Danish social media discourse |
| TikTok | MEDIUM | Student discourse specifically |
| Instagram | MEDIUM | Visual/student content |

**Phase D -- Manual collection (no automated path):**

| Source | Method | Purpose |
|--------|--------|---------|
| LinkedIn | Zeeschuimer + NDJSON import | Professional discourse from education sector actors |

**Skip:**
- Gab, Telegram, Threads (negligible AI og uddannelse content)
- Majestic (premium-only, out of scope)

---

## 4. Query Design Capabilities for Explorative Issue Mapping

### 4.1 The Iterative Nature of Issue Mapping Query Design

Marres-style issue mapping is fundamentally explorative and iterative. The researcher does not begin with a fixed set of search terms and collect data once. Instead, the workflow is:

1. **Seed query**: Start with core terms ("AI og uddannelse", "kunstig intelligens uddannelse")
2. **Initial collection**: Collect data from selected arenas
3. **Emergent discovery**: Analyze collected data to discover new terms, actors, and discourse associations
4. **Query refinement**: Add discovered terms and actors to the query design
5. **Expanded collection**: Re-collect with the enriched query
6. **Repeat** until the issue map stabilizes (saturation)

This iterative cycle is the defining characteristic of issue mapping methodology. The codebase must support it.

### 4.2 Current Query Design Model Assessment

The `QueryDesign` model (`/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/models/query_design.py`, line 34) and `SearchTerm` model (line 140) provide:

- Named, owner-scoped query designs with Danish locale defaults (language `da`, country `dk`)
- Individual search terms with types: `keyword`, `phrase`, `hashtag`, `url_pattern`
- Actor lists with sampling method tracking (`manual`, `snowball`, `network`, `similarity`)
- Per-arena tier configuration via `arenas_config` JSONB
- Soft-deletion of search terms via `is_active=False` to preserve historical coverage data
- Visibility controls (`private`, `team`, `public`)

**Strengths for issue mapping:**

- The `ActorList` model with `sampling_method` tracking is excellent for documenting how the issue map's actor population was constructed -- essential for methodological transparency.
- The `SearchTerm.is_active` flag allows the researcher to add and deactivate terms iteratively without losing the record of what was searched.
- The per-arena `arenas_config` allows different tiers for different arenas, matching the free/medium constraint.

### 4.3 Query Design Gaps for Explorative Issue Mapping

**Gap 1: No boolean query logic (same as CO2 afgift)**

The `SearchTerm` model stores flat strings. For AI og uddannelse issue mapping, the researcher needs:
- `"kunstig intelligens" AND uddannelse` (to avoid noise from general AI content)
- `AI AND (eksamen OR undervisning OR studie*)` (to capture sector-specific discourse)
- `ChatGPT NOT (pris OR abonnement)` (to exclude product/pricing discussions)

Without boolean logic, each variant must be a separate search term, increasing both noise (false positives from individual terms) and API cost (more queries per collection run).

**Gap 2: No query versioning or branching**

Issue mapping is iterative. The researcher needs to:
- Save a snapshot of the query design at each iteration
- Compare results between query versions ("what did adding 'eksamen' to the search terms reveal?")
- Branch a query design to explore different directions simultaneously

The `QueryDesign` model has `visibility` and `updated_at` but no versioning mechanism. There is no way to clone a query design with modifications.

**Gap 3: No support for bilingual query pairs**

AI og uddannelse discourse is inherently bilingual. Danish actors use English terms ("AI", "machine learning", "ChatGPT") alongside Danish terms ("kunstig intelligens", "maskinlaering", "eksamen"). The system has no concept of a bilingual term pair where "kunstig intelligens" and "artificial intelligence" are recognized as the same concept in different languages. Each must be entered as a separate search term, and there is no grouping mechanism.

**Gap 4: No synonym or compound-word expansion for Danish**

Same as CO2 afgift: `AI uddannelse` / `AI-uddannelse` / `AIuddannelse` are three separate search terms. The Danish compound `undervisningskvalitet` should also match `undervisnings kvalitet` and `undervisnings-kvalitet`.

**Gap 5: No query term suggestion from collected data**

After an initial collection, the system cannot suggest new search terms based on what it found. For issue mapping, the ideal workflow would be:
1. Collect data for "AI og uddannelse"
2. The system identifies that "ChatGPT" and "eksamen" frequently co-occur in collected content
3. The system suggests adding these as search terms for the next iteration

This requires the emergent term extraction capability discussed in Section 5, Gap 1.

### 4.4 AI og uddannelse Query Design Bilingual Challenge

The AI og uddannelse issue presents a more significant bilingual challenge than CO2 afgift because:

1. **The technology itself is named in English.** "AI", "ChatGPT", "Copilot", "machine learning" are used in Danish discourse without translation. CO2 afgift had only the policy-specific English variants ("Denmark carbon tax").

2. **Academic discourse is partially English-medium.** Danish university researchers publish in English and discuss AI in education in English-language academic fora. Their Danish public discourse mixes languages.

3. **The GDELT translation problem is worse.** GDELT translates Danish articles to English, introducing artifacts. For AI og uddannelse, the already-English terms ("AI", "ChatGPT") in Danish articles may cause GDELT's translation to preserve more structure than for a purely Danish topic, but the hybrid-language nature makes accuracy assessment harder.

4. **Platform language filters interact differently.** On Bluesky, `lang:da` will exclude English-language posts about Danish AI education. On YouTube, `relevanceLanguage=da` does not filter by content language but by relevance to Danish-speaking users, so English-language content about AI in education may appear.

---

## 5. Analysis Pipeline Gaps for Issue Mapping

### Gap 1: No Emergent Term/Topic Extraction (CRITICAL for issue mapping)

**Current state:** The `get_top_terms()` function (`descriptive.py`, line 297) unnests the `search_terms_matched` array and counts occurrences. This only shows how often the researcher's own query terms appeared.

**What issue mapping requires:** A function that extracts new, previously unknown terms and topics from the collected text content itself. This is the mechanism by which the issue map discovers its own structure -- the discourse associations that define the issue's contours.

**Recommended implementation:**

```
get_emergent_terms(query_design_id, method='tfidf', top_n=50)
```

Three methods, in order of implementation complexity:

1. **TF-IDF extraction** (simplest): Compute TF-IDF scores across all `text_content` in the query scope, filter out the researcher's search terms, and return the top N novel terms. The `_tokenize()` function in `similarity_finder.py` (line 84) already handles Danish tokenization with `[a-z0-9aeoea]{2,}` pattern -- this can be reused.

2. **KeyBERT** (moderate): Use a Danish BERT embedding model (e.g., `Maltehb/danish-bert-botxo` or the Scandinavian model from the Alexandra Institute) to extract key phrases. This produces multi-word expressions ("akademisk integritet", "digital kompetencer") rather than single tokens.

3. **BERTopic** (most powerful): Full topic modeling that clusters content into coherent topics, each represented by a set of descriptive terms. This directly produces the discourse association nodes needed for the issue map.

**Files affected:** New module `src/issue_observatory/analysis/text_analysis.py` or extension of `descriptive.py`.

### Gap 2: No Stance/Position Classification

**Current state:** No sentiment, stance, or frame classification capability exists anywhere in the codebase.

**What issue mapping requires:** For each content record (or at minimum, for a human-coded subset), a classification of what position the actor takes on AI og uddannelse. At minimum, a three-value stance: `supportive`, `critical`, `neutral`. Ideally, a more nuanced frame classification: `integration_advocate`, `integrity_concern`, `regulatory_demand`, `equity_concern`, `skills_transformation`, `technology_skepticism`.

**Recommended approach for issue mapping:** Given the explorative nature of the research, automated stance detection is premature -- the frames and positions are not yet known and will emerge from the data. The recommended approach is:

1. Build a **qualitative coding interface** (annotation layer) in the content browser where the researcher can manually code records with stance/frame labels
2. Store annotations in `raw_metadata.annotations` (JSONB) or a dedicated `content_annotations` table
3. After sufficient manual coding, consider training a classifier on the coded data

This matches the Marres methodological emphasis on interpretive analysis over automated classification.

### Gap 3: Bipartite Network Limited to Search Terms

**Current state:** `build_bipartite_network()` (network.py, line 523) creates actor-term edges where terms are `search_terms_matched` entries.

**What issue mapping requires:** A bipartite network where the term nodes are discourse topics extracted from the text content (Gap 1), not the researcher's search terms. This is the canonical issue map: actors connected to the discourses they engage in.

**Recommended implementation:** Once Gap 1 (emergent term extraction) is resolved, add:

```
build_issue_map_network(query_design_id, topic_method='tfidf', min_topic_frequency=5)
```

This function would:
1. Extract topics from the text corpus (using Gap 1 implementation)
2. For each content record, assign the top N topics
3. Build a bipartite graph: actor nodes linked to topic nodes, with edge weight = frequency

This produces the actual issue map.

### Gap 4: No Annotation/Coding Layer

**Current state:** No mechanism for researchers to annotate collected content with qualitative codes. The system is collection-and-display only.

**What issue mapping requires:** Marres-style issue mapping involves iterative interpretation of collected data. The researcher needs to:
- Code content records with frames, positions, controversy labels
- Mark content as relevant/irrelevant (inclusion/exclusion coding)
- Annotate actors with institutional roles, positions, alliance membership
- Create "issue categories" that group related content records

This is a fundamental capability gap for any qualitative research methodology, not just issue mapping.

**Recommended implementation:** A `ContentAnnotation` model:
```
content_annotation:
  id: UUID
  content_record_id: FK -> content_records
  annotator_id: FK -> users
  annotation_type: str (stance, frame, relevance, category, free_text)
  value: str
  created_at: timestamp
```

With an `ActorAnnotation` model for actor-level coding:
```
actor_annotation:
  id: UUID
  actor_id: FK -> actors
  annotator_id: FK -> users
  annotation_type: str (institutional_role, position, alliance)
  value: str
  created_at: timestamp
```

### Gap 5: No Temporal Network Analysis

**Current state:** All four network functions operate on a static snapshot across the entire time range. The `date_from` and `date_to` parameters on `get_actor_co_occurrence()` (network.py, line 135-136) allow scoping to a time window, but there is no function that produces a sequence of network snapshots.

**What issue mapping requires:** Temporal network analysis showing:
- **Network evolution**: How does the actor-discourse network change week by week?
- **New actor entry**: When does a new actor (e.g., a new minister, a tech company, a student organization) enter the issue discourse?
- **Discourse shift**: When do new discourse associations appear or old ones fade?
- **Event-driven changes**: How does the network change after a significant event (e.g., a university announces an AI policy, or a plagiarism scandal involving AI is publicized)?

**Recommended implementation:**

```
get_temporal_network_snapshots(query_design_id, interval='week', network_type='bipartite')
```

Returns a list of network snapshots, one per time interval, each in the same graph dict format as the current functions. Also returns a `changes` dict highlighting new/removed nodes and edges between consecutive snapshots.

**GEXF dynamic mode:** The current GEXF export uses `graph mode="static"` (export.py, line 403). GEXF 1.3 supports `mode="dynamic"` with temporal attributes (start/end dates on nodes and edges). Implementing temporal GEXF would allow the researcher to animate the issue map evolution in Gephi's Timeline feature.

### Gap 6: No Cross-Arena Flow Analysis

**Current state:** The deduplication service detects identical content across arenas, and `get_volume_over_time()` provides per-arena volume breakdowns. But there is no function that analyzes the temporal sequence of coverage across arenas.

**What issue mapping requires:** For AI og uddannelse, understanding how the issue travels between arenas is a key research question:
- Does a university press release (Via Ritzau) trigger news coverage (RSS) which then triggers social media discourse (Twitter, Reddit)?
- Or does a viral student video (TikTok) trigger news coverage which then triggers institutional response?

**Recommended implementation:**

```
get_cross_arena_flow(query_design_id, event_window_hours=24)
```

For each cluster of related content (identified by shared content hash, URL, or topic), determine which arena published first and build a flow graph showing propagation paths. Return:
- `flow_sequences`: list of arena-to-arena propagation chains with timestamps
- `arena_first_mover`: which arena breaks stories most often
- `average_propagation_delay`: mean time from first appearance to appearance in each other arena

### Gap 7: No Qualitative Content Browser Filters

**Current state:** The content browser supports filtering by arena, platform, date range, and full-text search. The analysis functions support `query_design_id`, `run_id`, `arena`, `platform`, `date_from`, `date_to`.

**What issue mapping requires:** The ability to filter and browse content by:
- Actor type (show me only content from educational institutions)
- Annotation/coding label (show me only content coded as "equity_concern")
- Network position (show me content from actors with degree centrality > 5)
- Discourse association (show me content that mentions "eksamen" AND "ChatGPT" but NOT "snyd")

These filters are essential for the iterative exploration that defines issue mapping.

---

## 6. Visualization and Export for Issue Mapping

### 6.1 Current Export Assessment for Issue Mapping

| Format | Export Method | Issue Mapping Suitability |
|--------|-------------|--------------------------|
| GEXF (actor co-occurrence) | `export_gexf(records, "actor")` | **Good** -- produces a valid network for Gephi. Usable as a starting point for actor mapping. |
| GEXF (term co-occurrence) | `export_gexf(records, "term")` | **Blocked (B-02)** -- per status file, this export may still produce the actor network. Must be verified before use. |
| GEXF (bipartite) | `export_gexf(records, "bipartite")` | **Blocked (B-02)** -- same concern. Also limited to search terms (not emergent discourse topics). |
| CSV | `export_csv()` | **Adequate** -- usable for import into NVivo, MAXQDA, or R for qualitative coding. Missing `pseudonymized_author_id` and `content_hash` columns. |
| XLSX | `export_xlsx()` | **Adequate** -- same column limitations as CSV. |
| Parquet | `export_parquet()` | **Good** -- efficient for computational analysis in Python/pandas or R/arrow. |
| NDJSON | `export_json()` | **Good** -- includes all fields including `raw_metadata`. Best for programmatic analysis. |

### 6.2 Visualization Gaps for Issue Mapping

**Gap 1: No in-browser network visualization**

Issue mapping is an iterative visual practice. The researcher needs to see network visualizations in the browser while exploring the data, not only after exporting to Gephi. A lightweight d3.js or Sigma.js force-directed graph in the analysis dashboard would dramatically improve the issue mapping workflow.

**Gap 2: No dynamic GEXF for temporal issue maps**

The GEXF export produces static networks (`mode="static"` in `_make_gexf_root()`, export.py line 403). Issue mapping requires temporal evolution. GEXF 1.3 supports `mode="dynamic"` with `<spells>` elements on nodes and edges to indicate when they are active. This would enable the Gephi Timeline feature.

**Gap 3: No export for DMI (Digital Methods Initiative) tools**

The Marres digital methods tradition relies heavily on tools from the Digital Methods Initiative (DMI) at the University of Amsterdam. Key tools include:
- **Issue Crawler** (web network analysis): The system does not produce output compatible with Issue Crawler input (URL seed lists).
- **Triangulation tool**: Requires tabular data with platform, URL, and engagement columns in a specific format.
- **Gephi** is supported via GEXF.
- **RAW Graphs**: Requires CSV with specific column structures for chart types (alluvial, treemap, etc.).

**Gap 4: Missing columns in flat export for issue mapping**

The `_FLAT_COLUMNS` list (export.py, line 42) omits several fields essential for issue mapping workflows in external tools:
- `pseudonymized_author_id` -- needed for entity resolution in R/Python
- `content_hash` -- needed for cross-referencing deduplicated records
- `collection_run_id` -- needed for tracing data provenance
- `author_id` (FK to actors) -- needed for joining with actor metadata in external tools

### 6.3 Integration with Issue Mapping Tools

| Tool | Current Integration | What is Needed |
|------|-------------------|----------------|
| **Gephi** | GEXF export works (actor network verified; term/bipartite blocked by B-02) | Fix B-02; add dynamic GEXF; add emergent topic nodes to bipartite network |
| **NVivo** | CSV export usable for import | Add annotation/coding layer; export annotations as NVivo-compatible project |
| **MAXQDA** | CSV export usable | Same as NVivo |
| **R / tidyverse** | CSV/Parquet export works | Add `pseudonymized_author_id`, `content_hash` to flat columns |
| **Python / networkx** | NDJSON export works; network dicts are JSON-serializable | Add JSON export of network analysis results (graph dicts) |
| **Cortext / CorTexT Manager** | No direct integration | Would require CSV export with co-word matrix or bipartite edge list format |
| **Issue Crawler (DMI)** | No integration | Would require URL list export for web crawling |
| **RAW Graphs** | CSV export usable for some chart types | Column naming must match RAW Graphs conventions |

---

## 7. Technical Debt Impact on Issue Mapping

### TD-1: Analysis module filter duplication hinders extension

Both `_build_content_filters()` in `descriptive.py` (line 74) and `_build_run_filter()` in `network.py` (line 62) implement nearly identical filter construction. Adding issue-mapping-specific filters (by annotation label, by actor type, by discourse topic) would require modifying both functions. A shared filter builder is needed before extending the analysis layer.

**Impact on issue mapping:** Every new analysis function for issue mapping (emergent terms, temporal networks, cross-arena flow) will need filter construction. Without consolidation, the number of duplicate filter implementations will grow from 2 to 5+.

### TD-2: GEXF export reconstructs networks from records in memory

The `_build_actor_gexf()`, `_build_term_gexf()`, and `_build_bipartite_gexf()` methods in `export.py` (lines 411-647) reconstruct networks from flat content record lists in Python memory, duplicating the SQL-based network construction in `network.py`. For issue mapping, which may require larger datasets (see Section 10), this duplication wastes memory and risks inconsistency between the in-browser network view and the exported GEXF.

**Recommended fix:** The GEXF export should consume the graph dict output from `network.py` functions, not raw content records.

### TD-3: No enrichment pipeline architecture

There is no formal pipeline for post-collection enrichments. Each enrichment (language detection, sentiment analysis, topic modeling, named entity extraction) would need ad-hoc implementation. For issue mapping, at least three enrichments are needed:
1. Client-side Danish language detection (for platforms without `lang` field)
2. Emergent term/topic extraction
3. Named entity extraction (to identify mentioned actors)

A pluggable enricher interface (similar to `ArenaCollector`) with standardized storage in `raw_metadata.enrichments` would prevent these from becoming ad-hoc additions.

### TD-4: Duplicate-marked records still counted in analysis

The descriptive and network analysis functions do not filter out records where `raw_metadata->>'duplicate_of' IS NOT NULL`. For issue mapping, duplicate records distort both volume counts and network edge weights. The same Ritzau press release about AI og uddannelse appearing via RSS, GDELT, and Event Registry would create three records and inflate the issuing actor's degree centrality.

### TD-5: `get_top_actors()` groups by platform (line 276)

The `GROUP BY pseudonymized_author_id, author_display_name, platform` in `get_top_actors()` (descriptive.py, line 276) treats the same actor on different platforms as distinct actors. For issue mapping, where cross-platform identity is fundamental, this produces misleading rankings. An actor active on Twitter, YouTube, and RSS (like DR Nyheder) appears as three separate entries rather than one consolidated entry.

**Recommended fix:** Add an alternative `get_top_actors_unified()` that groups by `author_id` (FK to actors table, after entity resolution) rather than by `pseudonymized_author_id` and `platform`. This produces a single entry per canonical actor with per-platform breakdowns.

### TD-6: Open blocker B-02 (term and bipartite GEXF)

Per the status file (`/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/docs/status/research.md`, line 71), B-02 is still open: "Term and bipartite GEXF exports produce actor network." The term co-occurrence and bipartite actor-term networks are both essential for issue mapping (they are, respectively, the discourse association map and the issue map). If B-02 means these exports are broken, issue mapping cannot produce its core output.

**Verification needed:** The CO2 afgift report (line 49) notes that `_build_term_gexf` and `_build_bipartite_gexf` are "now implemented" in export.py (which I can confirm from the current source code -- lines 497 and 573), but that "verification that the fix is end-to-end functional is needed." The code now contains distinct implementations for all three network types. The remaining B-02 concern may be at the frontend route/button level, not the export function level.

---

## 8. Recommended Actor Seed List

The following actor seed list is designed specifically for issue mapping of AI og uddannelse. Actors are categorized by their role in the issue, which determines their expected position in the issue map.

### 8.1 Educational Institutions

| Canonical Name | Actor Type | Platforms Expected | Issue Map Role |
|---------------|------------|-------------------|----------------|
| Kobenhavns Universitet (KU) | educational_institution | Twitter, Facebook, YouTube, LinkedIn, RSS | Major research university; likely to have institutional AI policy |
| Danmarks Tekniske Universitet (DTU) | educational_institution | Twitter, Facebook, YouTube, LinkedIn, RSS | Technical focus; likely to be pro-integration |
| Aarhus Universitet (AU) | educational_institution | Twitter, Facebook, YouTube, LinkedIn, RSS | Major university; broad disciplinary range |
| Copenhagen Business School (CBS) | educational_institution | Twitter, Facebook, YouTube, LinkedIn, RSS | Business/economics focus; management of AI in education |
| Syddansk Universitet (SDU) | educational_institution | Twitter, Facebook, LinkedIn, RSS | Regional perspective; likely early policy adopter |
| Aalborg Universitet (AAU) | educational_institution | Twitter, Facebook, LinkedIn, RSS | Problem-based learning tradition; distinct pedagogical perspective |
| Roskilde Universitet (RUC) | educational_institution | Twitter, Facebook, LinkedIn, RSS | Interdisciplinary focus; critical perspective likely |
| IT-Universitetet i Kobenhavn (ITU) | educational_institution | Twitter, Facebook, YouTube, LinkedIn, RSS | IT/CS-specific; direct expertise in AI |
| Professionshojskolerne (UC) | educational_institution | Twitter, Facebook, LinkedIn | Teacher training institutions; implementation perspective |

### 8.2 Teachers' and Academic Unions

| Canonical Name | Actor Type | Platforms Expected | Issue Map Role |
|---------------|------------|-------------------|----------------|
| Danmarks Laererforening (DLF) | teachers_union | Twitter, Facebook, YouTube, RSS | Folkeskole teachers; pedagogical perspective |
| DM (Dansk Magisterforening) | union | Twitter, Facebook, LinkedIn, RSS | Academic staff; research and teaching conditions |
| Djof | union | Twitter, Facebook, LinkedIn, RSS | Legal, economics, political science professionals |
| IDA (Ingeniorforbundet) | union | Twitter, Facebook, LinkedIn, RSS | Engineers; technical implementation perspective |
| Gymnasieskolernes Laererforening (GL) | teachers_union | Twitter, Facebook, RSS | Upper secondary teachers; examination reform |

### 8.3 Student Organizations

| Canonical Name | Actor Type | Platforms Expected | Issue Map Role |
|---------------|------------|-------------------|----------------|
| Danske Studerendes Faellesrad (DSF) | student_organization | Twitter, Facebook, Instagram, RSS | National student voice; policy advocacy |
| Studenterraadet KU | student_organization | Facebook, Instagram | KU-specific student perspective |
| Polyteknisk Forening (DTU) | student_organization | Facebook, Instagram, LinkedIn | DTU engineering students |

### 8.4 Political Actors

| Canonical Name | Actor Type | Platforms Expected | Issue Map Role |
|---------------|------------|-------------------|----------------|
| Uddannelses- og Forskningsministeren | political_actor | Twitter, Facebook, RSS | Ministerial authority; policy direction |
| Borneundervisningsministeren | political_actor | Twitter, Facebook, RSS | K-12 education authority |
| Uddannelses- og Forskningsudvalget | political_actor | RSS | Parliamentary committee; legislative scrutiny |
| Teknologiraadet | government_body | Twitter, Facebook, RSS | Technology assessment; advisory role |

### 8.5 Think Tanks and Research Centers

| Canonical Name | Actor Type | Platforms Expected | Issue Map Role |
|---------------|------------|-------------------|----------------|
| DEA (Taenketanken DEA) | think_tank | Twitter, Facebook, LinkedIn, RSS | Education policy research; evidence-based advocacy |
| Teknologiraadet | research_center | Twitter, Facebook, RSS | Technology assessment body |
| EVA (Danmarks Evalueringsinstitut) | research_center | Twitter, Facebook, LinkedIn, RSS | Education quality evaluation |
| AI Denmark | organization | Twitter, LinkedIn | AI industry/research coordination |
| Center for Computational Thinking (CBS) | research_center | LinkedIn, Twitter | Applied AI education research |
| Alexandra Instituttet | research_center | LinkedIn, Twitter | Danish AI research; language technology |

### 8.6 Technology Companies

| Canonical Name | Actor Type | Platforms Expected | Issue Map Role |
|---------------|------------|-------------------|----------------|
| Microsoft Danmark | tech_company | Twitter, Facebook, LinkedIn, YouTube | Copilot integration in education; commercial interest |
| Google Danmark | tech_company | Twitter, LinkedIn, YouTube | Gemini, Workspace for Education; commercial interest |
| OpenAI | tech_company | Twitter, Bluesky | ChatGPT provider; not Denmark-specific but referenced universally |

### 8.7 Media Actors

| Canonical Name | Actor Type | Platforms Expected | Issue Map Role |
|---------------|------------|-------------------|----------------|
| DR Nyheder | media_outlet | Twitter, Facebook, YouTube, Bluesky, RSS | Public broadcaster; AI education reporting |
| TV2 Nyheder | media_outlet | Twitter, Facebook, YouTube, RSS | Commercial broadcaster |
| Altinget | media_outlet | Twitter, Facebook, LinkedIn, RSS | Policy news; education section |
| Politiken | media_outlet | Twitter, Facebook, RSS | Broadsheet; education/culture coverage |
| Information | media_outlet | Twitter, Facebook, RSS | Critical/analytical coverage |
| Folkeskolen | media_outlet | Facebook, RSS | Teachers' professional outlet |
| Magisterbladet | media_outlet | Facebook, LinkedIn | DM union magazine |
| Uniavisen | media_outlet | Facebook, RSS | Student newspaper (KU) |

---

## 9. Recommended Query Design Specification

### 9.1 Primary Search Terms (Danish)

| Term | Type | Rationale |
|------|------|-----------|
| `AI og uddannelse` | phrase | Canonical issue name |
| `AI i uddannelse` | phrase | Common variant |
| `kunstig intelligens uddannelse` | phrase | Full Danish translation |
| `AI undervisning` | keyword | AI in teaching/instruction |
| `AI eksamen` | keyword | AI and examinations -- key controversy area |
| `ChatGPT uddannelse` | keyword | Specific tool + education |
| `ChatGPT eksamen` | keyword | Specific tool + examination |
| `ChatGPT skole` | keyword | Specific tool + school (K-12) |
| `ChatGPT universitet` | keyword | Specific tool + university |
| `AI folkeskolen` | keyword | AI in primary/lower secondary school |
| `AI gymnasiet` | keyword | AI in upper secondary school |
| `AI universitetet` | keyword | AI at the university |
| `kunstig intelligens skole` | keyword | Full Danish + school |
| `digital kompetencer AI` | keyword | Digital competencies frame |
| `akademisk integritet AI` | phrase | Academic integrity frame |
| `AI snyd` | keyword | AI cheating -- controversy term |
| `AI plagiat` | keyword | AI plagiarism |
| `maskinlaering uddannelse` | keyword | Machine learning + education |

### 9.2 Secondary Search Terms (Danish, sector-specific)

| Term | Type | Rationale |
|------|------|-----------|
| `Copilot uddannelse` | keyword | Microsoft's AI tool in education |
| `Gemini uddannelse` | keyword | Google's AI tool |
| `AI laeringsmidler` | keyword | AI learning materials |
| `AI didaktik` | keyword | AI and didactics/pedagogy |
| `AI paedagogik` | keyword | AI and pedagogy |
| `AI-vaerktoj undervisning` | keyword | AI tools in teaching |
| `AI eksaminationsform` | keyword | AI and examination formats |
| `AI retningslinjer universitet` | keyword | AI guidelines at universities |

### 9.3 Hashtag Terms

| Term | Type | Rationale |
|------|------|-----------|
| `#AIogUddannelse` | hashtag | Issue-specific hashtag (may or may not be in use) |
| `#AIiSkolen` | hashtag | AI in school |
| `#ChatGPTDK` | hashtag | Danish ChatGPT discussion |
| `#dkudd` | hashtag | Danish education discussion hashtag |
| `#dkpol` | hashtag | Danish politics hashtag (for political discourse about AI education) |
| `#edtech` | hashtag | Education technology (international, but used by Danish actors) |

### 9.4 English Variant Terms (for GDELT, international coverage)

| Term | Type | Rationale |
|------|------|-----------|
| `Denmark AI education` | phrase | International coverage of Danish context |
| `Danish universities AI` | phrase | International coverage |
| `ChatGPT Danish schools` | phrase | Specific tools + Danish context |
| `artificial intelligence education Denmark` | phrase | Full term + country |

### 9.5 URL Pattern Terms

| Term | Type | Rationale |
|------|------|-----------|
| `url_pattern: ufm.dk` | url_pattern | Ministry of Education and Research |
| `url_pattern: dea.nu` | url_pattern | DEA think tank |
| `url_pattern: eva.dk` | url_pattern | Danish Evaluation Institute |
| `url_pattern: altinget.dk/forskning` | url_pattern | Altinget research/education section |
| `url_pattern: folkeskolen.dk` | url_pattern | Teachers' professional outlet |
| `url_pattern: teknologiradet.dk` | url_pattern | Danish Board of Technology |

### 9.6 Issue Mapping Iteration Plan

**Iteration 1 (Week 1-2): Core collection**
- Activate all Phase A (free) arenas
- Use primary search terms only
- Seed actor list: educational institutions + unions + political actors
- Expected yield: 500-1,500 records

**Iteration 2 (Week 3-4): Term expansion**
- Analyze Iteration 1 data for emergent terms (manually, until Gap 1 is resolved)
- Add secondary terms based on what appeared in collected data
- Expand actor list using snowball sampling from seed actors
- Add Phase B arenas (Google Search, Event Registry, X/Twitter)
- Expected yield: 1,500-4,000 additional records

**Iteration 3 (Week 5-6): Deep collection**
- Full term set active
- Full actor list active (seeds + snowball-discovered)
- Activate Phase C arenas if budget permits (Facebook, TikTok)
- Begin qualitative coding of collected data
- Expected yield: 3,000-8,000 additional records

**Iteration 4 (Week 7-8): Saturation check and mapping**
- Assess whether new collection runs produce diminishing new actors/terms
- Export to Gephi for network visualization
- Produce preliminary issue map
- Identify gaps and underrepresented arenas

### 9.7 Recommended `arenas_config` for the Query Design

```json
{
  "rss_feeds": "free",
  "gdelt": "free",
  "bluesky": "free",
  "reddit": "free",
  "youtube": "free",
  "ritzau_via": "free",
  "google_autocomplete": "medium",
  "google_search": "medium",
  "event_registry": "medium",
  "x_twitter": "medium"
}
```

---

## 10. Cost Estimate at Free/Medium Tiers

### 10.1 Per-Arena Monthly Cost Estimate

| Arena | Tier | Monthly Cost | Basis |
|-------|------|-------------|-------|
| RSS Feeds | FREE | $0 | 28+ Danish feeds, polling every 10-15 min |
| GDELT | FREE | $0 | REST API, no auth |
| Bluesky | FREE | $0 | AT Protocol public API |
| Reddit | FREE | $0 | Public JSON API + auth for rate limit increase |
| YouTube | FREE | $0 | API key (10K quota units/day, shared across arenas) |
| Via Ritzau | FREE | $0 | Unauthenticated JSON API |
| Google Autocomplete | MEDIUM | $3-5 | Serper.dev; ~20-40 autocomplete queries/month |
| Google Search | MEDIUM | $5-10 | Serper.dev; ~50-100 search queries/month |
| Event Registry | MEDIUM | $90 | 5K tokens/month at medium tier |
| X/Twitter | MEDIUM | $5-15 | TwitterAPI.io at $0.15/1K tweets; ~30-100K tweets/month scope |
| Facebook (if activated) | MEDIUM | $50-100 | Bright Data subscription |
| TikTok (if activated) | MEDIUM | $10-20 | Research API; limited volume expected |
| **Total (Phase A+B only)** | | **~$103-120/month** | |
| **Total (all phases)** | | **~$163-240/month** | |

### 10.2 Duration-Based Cost Estimate

| Duration | Phase A+B Only | All Phases |
|----------|---------------|------------|
| 2 months (initial mapping) | $206-240 | $326-480 |
| 4 months (iterative mapping) | $412-480 | $652-960 |
| 6 months (comprehensive study) | $618-720 | $978-1,440 |

**Note:** These costs are lower than the CO2 afgift estimate ($960-1,410 for 6 months) because:
1. AI og uddannelse is a more focused issue with lower expected social media volume
2. The free/medium constraint excludes premium tier arenas
3. Facebook is listed as conditional (Phase C), not Phase B

### 10.3 Volume Estimates

| Arena | Estimated Monthly Records | Basis |
|-------|--------------------------|-------|
| RSS Feeds (filtered for AI uddannelse) | 100-300 | Lower than CO2 afgift; education is a narrower media beat |
| GDELT (filtered) | 200-500 | International + Danish coverage |
| Event Registry (filtered) | 100-250 | Token-budget-limited |
| X/Twitter | 500-2,000 | Danish Twitter education discourse is active but smaller than policy discourse |
| YouTube | 50-150 | University channels, edtech content |
| Bluesky | 20-100 | Growing but small Danish academic presence |
| Reddit | 30-80 | r/Denmark AI discussions |
| Via Ritzau | 20-50 | University and union press releases |
| Google Search | 200-500 per batch | Search result snapshots |
| Google Autocomplete | 50-100 per batch | Autocomplete suggestions |
| Facebook (if active) | 1,000-3,000 | Teacher groups, parent groups, university groups |
| TikTok (if active) | 100-500 | Student AI discourse |

**Estimated total (Phase A+B, 4 months): 8,000-25,000 records**
**Estimated total (all phases, 4 months): 15,000-40,000 records**

These volumes are well within the system's scalability envelope. Monthly partitioning, GIN indexes, and the actor co-occurrence self-join `LIMIT` parameter will handle this without performance concerns.

---

## 11. Prioritized Improvement Roadmap

The following improvements are prioritized specifically for Marres-style issue mapping of AI og uddannelse. Priorities differ significantly from the CO2 afgift roadmap because issue mapping has different analytical requirements.

### Priority 1: Pre-Study Blockers (must fix before starting issue mapping)

| ID | Improvement | Effort | Owner | Files Affected | Rationale |
|----|------------|--------|-------|----------------|-----------|
| IM-1.1 | **Verify and fix B-02** -- confirm term and bipartite GEXF exports work end-to-end | 2-4 hours | QA Engineer | `analysis/export.py`, frontend templates | The bipartite network IS the issue map. Without it, the core research output cannot be produced. |
| IM-1.2 | **Add Altinget RSS feed** to `DANISH_RSS_FEEDS` | 1 hour | Research Agent | `config/danish_defaults.py` | Altinget is the most important Danish policy news source for education. |
| IM-1.3 | **Add education-specific RSS feeds** (Folkeskolen.dk, university news pages) | 2-3 hours | Research Agent | `config/danish_defaults.py` | AI og uddannelse discourse lives in education-specific outlets not in the current feed list. |
| IM-1.4 | **Add duplicate exclusion to analysis queries** | 2-4 hours | DB Engineer | `analysis/descriptive.py`, `analysis/network.py` | Duplicate records distort network edge weights and volume counts. Same as CO2 afgift P1.2. |
| IM-1.5 | **Extend `_FLAT_COLUMNS` for export** -- add `pseudonymized_author_id`, `content_hash`, `collection_run_id`, `author_id` | 1-2 hours | DB Engineer | `analysis/export.py` | External tools (R, Gephi, NVivo) need these columns for entity resolution and deduplication. Same as CO2 afgift P1.3. |
| IM-1.6 | **Create AI og uddannelse use case document** | 4-6 hours | Research Agent | `docs/use_cases/ai_uddannelse.md` | Full query design specification, actor lists, arena activation plan, iteration schedule. |

### Priority 2: Core Issue Mapping Capabilities (essential for producing an issue map)

| ID | Improvement | Effort | Owner | Files Affected | Rationale |
|----|------------|--------|-------|----------------|-----------|
| IM-2.1 | **Emergent term extraction** -- TF-IDF or KeyBERT on collected text content | 3-5 days | Core Engineer + DB Engineer | New `analysis/text_analysis.py` or extension of `descriptive.py` | Without this, the researcher cannot discover discourse associations -- the defining element of an issue map. This is the single highest-impact improvement for issue mapping. |
| IM-2.2 | **Unified actor ranking** -- `get_top_actors_unified()` grouping by `author_id` instead of platform | 1-2 days | DB Engineer | `analysis/descriptive.py` | Cross-platform actor identity is essential for issue mapping. The current per-platform grouping (line 276) fragments actors across platforms. |
| IM-2.3 | **Bipartite network with extracted topics** -- extend `build_bipartite_network()` to use emergent topics, not just search terms | 2-3 days | DB Engineer | `analysis/network.py` | This produces the actual issue map: actors connected to discourse topics. Depends on IM-2.1. |
| IM-2.4 | **Client-side Danish language detection** | 1-2 days | Core Engineer | `core/normalizer.py` | AI og uddannelse content from platforms without language tags (Facebook, Instagram) must be identifiable as Danish. Same as CO2 afgift P2.1. |
| IM-2.5 | **Content annotation layer** for qualitative coding | 5-7 days | DB Engineer + Frontend Engineer | New model, API routes, templates | Qualitative coding of stance, frame, and controversy is essential for interpretive issue mapping. The researcher needs to code content in the browser and export annotated datasets. |

### Priority 3: Enhanced Issue Mapping (significantly enrich the issue map)

| ID | Improvement | Effort | Owner | Files Affected | Rationale |
|----|------------|--------|-------|----------------|-----------|
| IM-3.1 | **Temporal network snapshots** -- weekly/monthly network evolution | 3-5 days | DB Engineer | `analysis/network.py` | Issue mapping requires showing how the actor-discourse topology evolves over time. |
| IM-3.2 | **Dynamic GEXF export** -- temporal attributes on nodes and edges | 2-3 days | DB Engineer | `analysis/export.py` | Enables Gephi Timeline for animated issue map visualization. |
| IM-3.3 | **Cross-arena flow analysis** | 3-5 days | DB Engineer + Research Agent | New analysis module | Understanding how AI og uddannelse discourse travels between arenas is a key research question. |
| IM-3.4 | **Boolean query support** | 3-5 days | DB Engineer + Core Engineer | `models/query_design.py`, arena collectors | Reduces noise and API cost in the iterative query refinement cycle. Same as CO2 afgift P2.3. |
| IM-3.5 | **Named entity extraction from text** | 3-5 days | Core Engineer | New enrichment module | Identifies mentioned actors and organizations in news articles, enabling the speaker/mentioned/quoted distinction (Section 2.1). |
| IM-3.6 | **Actor type enumeration** -- formalize `actor_type` values relevant to AI og uddannelse | 1-2 hours | Research Agent + DB Engineer | `models/actors.py` or documentation | Enables typed partitioning in Gephi (color by actor type). |

### Priority 4: Workflow Enhancements (improve the iterative mapping process)

| ID | Improvement | Effort | Owner | Files Affected | Rationale |
|----|------------|--------|-------|----------------|-----------|
| IM-4.1 | **Query design cloning and versioning** | 2-3 days | DB Engineer + Frontend | `models/query_design.py`, API routes | Issue mapping is iterative; the researcher needs to track query evolution. |
| IM-4.2 | **Bilingual term pairing** -- group Danish/English terms as equivalents | 1-2 days | DB Engineer | `models/query_design.py` | AI og uddannelse is inherently bilingual. |
| IM-4.3 | **In-browser network visualization** (Sigma.js or d3.js) | 3-5 days | Frontend Engineer | Templates, static assets | Eliminates the export-to-Gephi loop for quick visual exploration during iterative mapping. |
| IM-4.4 | **Filtered export from analysis results** | 2-3 days | DB Engineer | API routes, `analysis/export.py` | "Export only records from the top 10 actors" or "export only records containing these co-occurring terms." |
| IM-4.5 | **Query term suggestion from collected data** | 2-3 days | DB Engineer | `analysis/descriptive.py` or new module | Supports the iterative query refinement cycle by suggesting new terms based on emergent term extraction (depends on IM-2.1). |

---

## 12. Comparison to CO2 Afgift Recommendations

### 12.1 What is the Same

| Area | Finding | Both Reports |
|------|---------|-------------|
| No boolean query logic | SearchTerm model supports only flat strings | Yes -- affects both issues equally |
| No duplicate exclusion in analysis | Analysis functions count duplicate-marked records | Yes -- correctness issue for any research |
| Missing columns in flat export | `pseudonymized_author_id`, `content_hash`, `collection_run_id` missing from `_FLAT_COLUMNS` | Yes -- needed for any external analysis |
| No client-side Danish language detection | Platforms without language tags have NULL language | Yes -- affects all Danish data collection |
| LinkedIn coverage gap | No automated collection path | Yes -- critical for both issues, slightly more critical for AI og uddannelse |
| Altinget.dk missing from RSS feeds | Most important policy news source not in feed list | Yes -- affects both issues |
| GDELT 55% accuracy | Machine translation artifacts | Yes -- same limitation regardless of topic |
| Filter duplication across analysis modules | `_build_content_filters()` and `_build_run_filter()` are nearly identical | Yes -- technical debt affects all extensions |
| GEXF export memory inefficiency | Reconstructs networks from records instead of using network.py functions | Yes -- same issue |
| Engagement metrics are write-once | No re-collection or refresh mechanism | Yes -- same limitation |

### 12.2 What is Different

| Area | CO2 Afgift Assessment | AI og uddannelse Assessment | Why Different |
|------|----------------------|---------------------------|---------------|
| **Overall readiness** | 75-80% | 55-60% | Issue mapping requires analytical capabilities (discourse detection, controversy mapping, temporal networks) that discourse tracking does not |
| **Primary analytical gap** | No sentiment/stance analysis | No emergent term/topic extraction | CO2 afgift is a policy issue with known positions; AI og uddannelse is a forming issue where the frames are being discovered |
| **Most important missing capability** | Boolean query logic | Discourse association detection (Gap 1) | For policy tracking, query precision matters most; for issue mapping, discovery matters most |
| **Folketinget.dk** | High priority gap | Low priority gap | CO2 afgift was at legislative stage; AI og uddannelse is at institutional/sectoral stage |
| **TikTok relevance** | Low | Medium-High | Student discourse about AI tools is distinctive on TikTok |
| **YouTube relevance** | High (political commentary) | High (educational content) | Different content type but similar importance level |
| **Actor role complexity** | Moderate (supporters vs. opponents) | High (speaker vs. mentioned vs. quoted) | News coverage of AI og uddannelse involves complex attribution chains |
| **Bilingual challenge** | Minor (mostly Danish terms + a few English policy terms) | Major (technology terms are inherently English, academic discourse mixes languages) | AI terminology is English-native |
| **Temporal analysis priority** | Medium (tied to legislative calendar) | High (issue is forming, trajectory matters) | CO2 afgift had established temporal patterns; AI og uddannelse is emergent |
| **Controversy detection priority** | Medium (positions are largely known) | Critical (controversies are forming and need to be discovered) | Known vs. unknown controversy structure |
| **Network analysis adequacy** | Adequate for basic analysis | Structurally insufficient | Issue mapping needs bipartite actor-topic networks with extracted (not pre-specified) topics |
| **Qualitative coding need** | Low (quantitative/descriptive analysis sufficient) | High (interpretive analysis is methodologically essential) | Marres tradition requires human interpretation |
| **Estimated study cost (4 months)** | ~$640-940 | ~$412-480 (Phase A+B), ~$652-960 (all) | AI og uddannelse is a narrower issue with lower expected volume, partially offset by including TikTok |
| **Estimated data volume (4 months)** | 18,000-47,000 records | 8,000-25,000 (Phase A+B), 15,000-40,000 (all) | AI og uddannelse generates less social media volume than carbon tax policy |

### 12.3 Items that Should Be Addressed Before Either Study

The following items from the CO2 afgift roadmap are pre-requisites for any research use of the system, regardless of the specific issue:

1. **P1.2 / IM-1.4**: Add duplicate exclusion to analysis queries
2. **P1.3 / IM-1.5**: Extend `_FLAT_COLUMNS` for export
3. **P2.1 / IM-2.4**: Client-side Danish language detection
4. **P1.1 / IM-1.2**: Add Altinget RSS feed

### 12.4 Items Uniquely Important for Issue Mapping

The following items are not on the CO2 afgift roadmap but are essential for Marres-style issue mapping:

1. **IM-2.1**: Emergent term extraction (the defining capability gap)
2. **IM-2.3**: Bipartite network with extracted topics (the issue map itself)
3. **IM-2.5**: Content annotation layer (qualitative coding for interpretive analysis)
4. **IM-3.1**: Temporal network snapshots (issue trajectory analysis)
5. **IM-3.2**: Dynamic GEXF export (temporal visualization in Gephi)
6. **IM-3.5**: Named entity extraction (mentioned actor identification)

---

## Appendix A: File Reference Index

All file paths are absolute paths within the project directory.

| File | Path | Relevance to Report |
|------|------|-------------------|
| Universal Content Record | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/models/content.py` | Schema, engagement metrics, partitioning |
| Query Design models | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/models/query_design.py` | Search terms, actor lists, arena config |
| Actor models | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/models/actors.py` | Entity resolution, cross-platform presence, actor types |
| Collection models | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/models/collection.py` | Run/task tracking, credit transactions |
| Normalizer | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/normalizer.py` | Pseudonymization, content hashing, field extraction |
| Deduplication | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/core/deduplication.py` | URL normalization, hash dedup, mark-and-sweep |
| Danish defaults | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/config/danish_defaults.py` | RSS feeds, locale params, FTS config |
| Descriptive analysis | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/analysis/descriptive.py` | Volume, top actors, top terms, engagement |
| Network analysis | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/analysis/network.py` | Co-occurrence, cross-platform actors, bipartite |
| Export | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/analysis/export.py` | CSV, XLSX, NDJSON, Parquet, GEXF |
| Arena base class | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/arenas/base.py` | Collector interface, Tier enum |
| Snowball sampler | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/sampling/snowball.py` | Iterative actor discovery |
| Network expander | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/sampling/network_expander.py` | Platform-specific actor expansion |
| Similarity finder | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/sampling/similarity_finder.py` | Content-based and cross-platform actor similarity |
| Research status | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/docs/status/research.md` | Arena brief status, open blockers |
| CO2 afgift report | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/docs/research_reports/co2_afgift_codebase_recommendations.md` | Reference for comparison |
| LinkedIn arena brief | `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/docs/arenas/linkedin.md` | LinkedIn access restrictions documentation |

---

*End of report. This document should be reviewed by the full agent team before initiating AI og uddannelse data collection. Priority 1 items (IM-1.1 through IM-1.6) should be completed first, with IM-2.1 (emergent term extraction) as the highest-priority single improvement for issue mapping capability. The roadmap diverges significantly from the CO2 afgift roadmap because Marres-style issue mapping requires analytical capabilities (discourse discovery, temporal networks, qualitative coding) that standard discourse tracking does not.*
