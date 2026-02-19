# Codebase Evaluation: Greenland in the Danish General Election 2026

**Author:** Research & Knowledge Agent (The Strategist)
**Date:** 2026-02-18
**Status:** Final
**Scope:** Comprehensive evaluation of the Issue Observatory codebase for mapping public discourse around "Greenland" in the Danish general election 2026, with special focus on conspiracy theory monitoring, foreign interference detection, fringe platform coverage, and cross-arena narrative tracking.

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-18 | Initial Greenland scenario evaluation. 20+ arena collectors examined, 4 reference documents cross-referenced, 10 sections with prioritized improvement roadmap. |

---

## Table of Contents

1. [Current Codebase Capabilities](#1-current-codebase-capabilities)
2. [Arena Coverage Analysis for Greenland Discourse](#2-arena-coverage-analysis-for-greenland-discourse)
3. [Cross-Arena Narrative Tracking Capabilities](#3-cross-arena-narrative-tracking-capabilities)
4. [Conspiracy Theory and Foreign Interference Monitoring](#4-conspiracy-theory-and-foreign-interference-monitoring)
5. [Source Discovery and Actor-to-Collection Workflows](#5-source-discovery-and-actor-to-collection-workflows)
6. [Multi-Language Support](#6-multi-language-support)
7. [Web Scraping and Archival Capabilities](#7-web-scraping-and-archival-capabilities)
8. [Data Management for Cross-Arena Research](#8-data-management-for-cross-arena-research)
9. [Cost Analysis](#9-cost-analysis)
10. [Prioritized Improvement Roadmap](#10-prioritized-improvement-roadmap)
11. [Comparison with Previous Evaluations](#11-comparison-with-previous-evaluations)

---

## Scenario Context

The "Greenland in the Danish General Election 2026" scenario is qualitatively different from the two previously evaluated use cases (CO2 afgift discourse tracking and AI og uddannelse issue mapping). Its distinctive requirements are:

1. **Geopolitical sensitivity**: The Greenland question involves US interest (Trump administration), Danish sovereignty, Greenlandic self-determination, and Arctic geopolitics. This generates discourse in Danish, English, Greenlandic (Kalaallisut), and potentially Russian.

2. **Conspiracy theory and disinformation monitoring**: Foreign interference narratives (Russian trolls, US influence operations) require monitoring of fringe platforms (Gab, Telegram, Discord) alongside mainstream media.

3. **Cross-arena narrative velocity**: Stories about Greenland break in international news, propagate through social media, and are refracted through Danish domestic politics. Tracking the speed and mutation of narratives across arenas is central.

4. **Election-cycle temporality**: The 2026 general election creates a bounded but high-intensity collection window where discourse volumes spike and platform behavior changes (political advertising, bot activity).

5. **Low-cost requirement**: The research team requires a free/medium tier budget. Premium-only arenas ($399.99/month Majestic, $500/month X/Twitter Enterprise) are effectively excluded.

6. **Actor network complexity**: The actor landscape spans Danish politicians, Greenlandic politicians (Naalakkersuisut), Arctic policy experts, US officials, Russian state media, and grassroots movements -- a multi-jurisdictional actor space that the previous use cases did not encounter.

### Design Philosophy: Flexibility Over Hardcoding

**Important**: The recommendations in this report should be interpreted through the lens of *application flexibility*, not use-case-specific hardcoding. The application should not carry built-in support for every possible research scenario. Instead of hardcoding Greenlandic RSS feeds, Kalaallisut language support, or specific Telegram channels into the codebase, the priority is building **researcher-configurable mechanisms** that allow any user to:

- Add their own RSS feeds, Telegram channels, Discord servers, Reddit subreddits, and Wikipedia seed articles through the UI
- Configure language filters per query design rather than relying on global defaults
- Specify platform-specific collection parameters (channel lists, subreddit lists, etc.) without code changes
- Extend the application's coverage to any topic, not just Greenland

Where this report identifies missing Greenlandic media feeds or specific subreddits, these serve as *examples* of what a researcher would need to add through self-service mechanisms. The development effort should be invested in the mechanisms, not the content.

---

## 1. Current Codebase Capabilities

### 1.1 Architecture Overview

The Issue Observatory has matured substantially since the CO2 afgift evaluation. The arena-based modular architecture now includes **24 arena implementation directories** under `src/issue_observatory/arenas/`:

```
ai_chat_search  bluesky  discord  event_registry  facebook  gab
gdelt  google_autocomplete  google_search  instagram  majestic
reddit  ritzau_via  rss_feeds  telegram  threads  tiktok  twitch
vkontakte  web/common_crawl  web/wayback  wikipedia  x_twitter  youtube
```

Source: `src/issue_observatory/arenas/` directory listing.

Of these 24 directories, the following are the implementation statuses:

| Status | Count | Arenas |
|--------|-------|--------|
| Fully implemented | 18 | google_search, google_autocomplete, bluesky, reddit, youtube, rss_feeds, gdelt, telegram, tiktok, gab, ritzau_via, event_registry, x_twitter, facebook, instagram, threads, common_crawl, wayback |
| Implemented (limited scope) | 3 | majestic (PREMIUM only), wikipedia (revision/pageview monitoring), discord (requires bot invitation per server) |
| Deferred stubs | 2 | twitch (channel discovery only, no chat), vkontakte (legal blockers) |
| Stub only | 1 | ai_chat_search |

### 1.2 Core Infrastructure Strengths

The following capabilities are operational and relevant to the Greenland scenario:

**Universal Content Record (UCR) with monthly range partitioning**
Source: `src/issue_observatory/core/models/content.py`
All arena collectors normalize data into a single schema with SHA-256 content hashing, SimHash near-duplicate fingerprinting, and pseudonymized author IDs. This is a solid foundation for cross-arena analysis.

**Actor entity resolution model**
Source: `src/issue_observatory/core/models/actors.py`
The `Actor` / `ActorPlatformPresence` / `ActorAlias` model supports tracking a single person (e.g., "Mette Frederiksen") across multiple platforms with canonical name resolution. Critical for the multi-platform actor landscape in the Greenland scenario.

**Snowball sampling and network expansion**
Source: `src/issue_observatory/sampling/snowball.py` (lines 87-254), `src/issue_observatory/sampling/network_expander.py` (lines 87-187)
The `SnowballSampler` orchestrates iterative actor discovery starting from seed actors, expanding via platform-specific social graph traversal. Platform-specific expanders exist for Bluesky (follows/followers), Reddit (comment mention mining), and YouTube (featured channels). This is directly useful for discovering Greenland-adjacent actors that are not in the initial seed list.

**Enrichment pipeline**
Source: `src/issue_observatory/analysis/enrichments/base.py` (lines 17-67), `src/issue_observatory/analysis/enrichments/language_detector.py`, `src/issue_observatory/analysis/enrichments/named_entity_extractor.py`
A pluggable `ContentEnricher` base class exists with two implemented enrichers:
- `DanishLanguageDetector`: Uses `langdetect` with a Danish character-frequency heuristic fallback (lines 30-87 of `language_detector.py`).
- `NamedEntityExtractor`: **Stub only** -- returns empty entity lists when spaCy is not installed (lines 93-112 of `named_entity_extractor.py`). The stub documents the intended output schema including `entity_type` (PERSON, ORG, GPE, LOC) and `role` (mentioned, speaker, quoted_source).

**Cross-arena deduplication**
Source: `src/issue_observatory/core/deduplication.py` (lines 41-96 for SimHash, lines 306-658 for DeduplicationService)
The `DeduplicationService` now implements:
- URL-based deduplication with tracking parameter stripping (UTM, fbclid, gclid) -- lines 254-298.
- Content hash (SHA-256) exact-duplicate detection -- lines 386-454.
- SimHash 64-bit near-duplicate detection with Union-Find clustering (Hamming distance threshold of 3) -- lines 112-226.
This addresses a critical gap identified in the CO2 report (IP2-032).

**Network analysis**
Source: `src/issue_observatory/analysis/network.py`
Actor co-occurrence networks, term co-occurrence networks, and bipartite actor-term networks are computed via SQL self-joins on `content_records`. GEXF export is available for Gephi visualization.

### 1.3 Known Systemic Issues (Carried Forward)

The Phase A QA report (`docs/ux_reports/phase_a_qa_report.md`) documented and resolved the arena registry collision issue where multiple collectors sharing the same `arena_name` caused only one per group to appear in the registry. This was resolved by assigning unique arena names. However, some Phase A items remain relevant:

- The engagement score column remains unpopulated (IP2-030 not yet implemented).
- Boolean query support is client-side only in most arenas, not server-side (IP2-031 partially addressed by term_groups parameter).
- Sentiment analysis enrichment remains a stub (IP2-034).

---

## 2. Arena Coverage Analysis for Greenland Discourse

This section evaluates each arena's suitability for the Greenland scenario specifically, organized by relevance tier.

### 2.1 Tier 1: Critical for Greenland Monitoring

#### RSS Feeds (Danish News Media)
**Source:** `src/issue_observatory/config/danish_defaults.py` lines 47-156, `src/issue_observatory/arenas/rss_feeds/`
**Relevance:** Extremely high. Danish news outlets are the primary arena for election discourse.
**Coverage:** 30+ feeds from DR, TV2, BT, Politiken, Berlingske, Ekstra Bladet, Information, Jyllands-Posten, Nordjyske, Fyens Stiftstidende, Borsen, Kristeligt Dagblad, Altinget (including section feeds for klima and uddannelse).
**Gap for Greenland:** No Greenlandic news media feeds are included in the defaults. A Greenland researcher would need Sermitsiaq.AG, KNR.gl, Arctic Today, or High North News — but more fundamentally, the RSS feed list is hardcoded in `danish_defaults.py` and cannot be extended through the UI.
**Assessment:** The current feed list is excellent for Danish domestic coverage, but the core issue is that researchers cannot add their own RSS feeds through the query design interface. Every new research topic that needs non-default feeds requires a code change. See GR-01 for the recommended self-service mechanism.

#### Google Search (SerpAPI/Serper.dev)
**Source:** `src/issue_observatory/arenas/google_search/`, `src/issue_observatory/config/danish_defaults.py` lines 192-201
**Relevance:** High. Google Search reflects what Danes encounter when searching for Greenland-related terms.
**Coverage:** Danish locale defaults (`gl=dk`, `hl=da`) are correctly applied. Supports date range filtering and search term queries.
**Strength for Greenland:** Google Search captures the full spectrum -- mainstream news, blog posts, institutional pages, and fringe sites -- in a single query. Particularly useful for discovering which narratives surface for ordinary users.
**Limitation:** SerpAPI costs $50/month at the medium tier (Developer plan, 5000 searches/month). Serper.dev is cheaper but provides fewer fields.

#### Telegram
**Source:** `src/issue_observatory/arenas/telegram/collector.py` (972 lines), `src/issue_observatory/arenas/telegram/config.py` (lines 1-95)
**Relevance:** Critical for conspiracy theory and interference monitoring.
**Current Configuration:** Only 6 default Danish channels, all mainstream news outlets (lines 14-73 of `config.py`):
```python
DEFAULT_DANISH_CHANNELS: list[str] = [
    "dr_nyheder",
    "tv2nyhederne",
    "berlingske",
    "politiken_dk",
    "bt_dk",
    "informationdk",
]
```
**Critical Gap:** The channel list is hardcoded in `config.py` and `danish_defaults.py` with no UI for researchers to add their own channels. For the Greenland scenario, the researcher would need to add political, geopolitical, and conspiracy-adjacent channels — but this is not a Greenland-specific problem. Any research scenario that requires monitoring specific Telegram channels beyond the 6 mainstream defaults faces the same barrier. See GR-02 for the recommended self-service mechanism.

**Technical Capabilities:** The Telegram collector supports `collect_by_terms()` with client-side term matching against configured channels (line 134-172 of `collector.py`). It supports `collect_by_actors()` to fetch from specific channels by username/ID (lines 174-210). The collector stores `is_forwarded` and `fwd_from_channel_id` in `raw_metadata`, which is **directly useful for tracking how Greenland narratives propagate across Telegram channels** (forwarding chains).

**Limitation:** No native language filter -- `language=None` in normalize() (no language field available from Telegram API). All language detection must happen post-collection via the enrichment pipeline. No access to private groups or encrypted chats. The FloodWaitError handling with Redis cooldown (documented in collector.py) means that aggressive collection can trigger rate limits.

#### Bluesky
**Source:** `src/issue_observatory/arenas/bluesky/`, `src/issue_observatory/config/danish_defaults.py` lines 222-228
**Relevance:** Growing rapidly in the Danish political space following the 2024 X/Twitter exodus. Danish politicians and journalists have been moving to Bluesky.
**Strengths:** Free API with no authentication required for search. Supports `lang:da` filter appended to search queries. The AT Protocol's public API is well-documented and stable.
**Relevance for Greenland:** Danish political discourse about Greenland increasingly takes place on Bluesky, especially among journalists and policy commentators. The network expander (`src/issue_observatory/sampling/network_expander.py` lines 360-429) supports Bluesky follows/followers expansion, which is valuable for mapping the Greenland discourse network.

#### Reddit
**Source:** `src/issue_observatory/arenas/reddit/`, `src/issue_observatory/config/danish_defaults.py` lines 175-186
**Relevance:** High for capturing grassroots Danish opinion on Greenland.
**Current Configuration:** Only 4 subreddits: `Denmark`, `danish`, `copenhagen`, `aarhus`.
**Gap for Greenland:** The Greenland researcher would need `r/Greenland`, `r/europe`, `r/geopolitics`, `r/worldnews`, and `r/dkpolitik` — but the subreddit list is hardcoded in `danish_defaults.py` and cannot be modified through the UI. This is the same pattern as RSS feeds and Telegram channels: the default list serves one use case (general Danish discourse) but any topic-specific research requires different subreddits.
**Assessment:** See GR-03 for the recommended self-service mechanism. The underlying issue is not which subreddits are in the default list but that the researcher cannot extend it.

### 2.2 Tier 2: Important Supporting Arenas

#### GDELT
**Source:** `src/issue_observatory/arenas/gdelt/`, `src/issue_observatory/config/danish_defaults.py` lines 207-217
**Relevance:** Moderate-high. GDELT captures international news about Greenland that Danish outlets may not cover, particularly US and Russian media perspectives.
**Strengths:** Free, no authentication. Danish filters (`sourcelang=danish`, `sourcecountry=DA`) are correctly configured. Provides tone analysis (average tone field).
**Limitation:** Known ~55% accuracy for Danish content (translation artifacts from GDELT's machine translation pipeline). GDELT is more useful for English-language international coverage of Greenland than for Danish-language content.
**Greenland-specific value:** GDELT's strength is monitoring how international media (especially US media) covers Greenland. Queries for "Greenland" + "Denmark" + "Trump" in English via GDELT would capture the international perspective effectively.

#### YouTube
**Source:** `src/issue_observatory/arenas/youtube/`, `src/issue_observatory/config/danish_defaults.py` lines 234-246
**Relevance:** Moderate. YouTube hosts political commentary, news clips, and documentary content about Greenland.
**Configuration:** `relevanceLanguage=da`, `regionCode=DK` are correctly applied.
**Greenland value:** Danish political YouTube channels, DR/TV2 clips, and international news segments about Greenland appear here. The `voice_to_text` transcript field (available via TikTok but not natively from YouTube API) could be valuable if supplemented with YouTube's auto-generated captions.
**Network expansion:** The YouTube expander (`src/issue_observatory/sampling/network_expander.py` lines 500-582) discovers related channels via `featuredChannelsUrls`, enabling discovery of Arctic policy content creators.

#### TikTok Research API
**Source:** `src/issue_observatory/arenas/tiktok/collector.py` (884 lines)
**Relevance:** Moderate, growing. TikTok is where young Danish voters encounter Greenland content, often in simplified or sensationalized form.
**Strengths:** Research API with OAuth 2.0 client credentials. `region_code: "DK"` filter applied automatically. Supports `hashtag_names` in raw_metadata. The `voice_to_text` field provides video transcript text (line documented in collector).
**Limitations:** 10-day engagement metric accuracy lag (documented in collector docstring). 30-day maximum date range per query (auto-split into windows). Free tier only.
**Greenland value:** Hashtag-based collection (`#gronland`, `#greenland`, `#groenland`, `#trumpgreenland`) could capture viral content. The voice_to_text field is particularly valuable because TikTok content is primarily video -- without it, the text_content field would often be empty or minimal.

#### Event Registry / NewsAPI.ai
**Source:** `src/issue_observatory/arenas/event_registry/`
**Relevance:** Moderate-high. The most comprehensive news API available, covering 150,000+ sources globally.
**Greenland value:** Can filter by `sourceLocationUri` for Denmark/Greenland, and by language for Danish and English simultaneously. Captures international media coverage that RSS feeds do not reach.
**Cost:** Medium tier required ($149/month for 5000 articles). This is within the budget ceiling but represents the single largest recurring cost.

#### Wikipedia
**Source:** `src/issue_observatory/arenas/wikipedia/`, `src/issue_observatory/config/danish_defaults.py` lines 299-323
**Relevance:** Moderate. Wikipedia edit wars and pageview trends on Greenland-related articles can serve as a proxy for public interest intensity.
**Configuration:** `DEFAULT_WIKI_PROJECTS = ["da.wikipedia", "en.wikipedia"]`. The `DANISH_WIKIPEDIA_SEED_ARTICLES` list is empty (line 299) and there is no UI for the researcher to specify seed articles. See GR-04 for the recommended self-service mechanism.
**Greenland value:** Monitor revision activity and pageview trends on articles such as "Gronland", "Danmarks_Riges_Faellesskab", "Selvstyre", "Trump_Greenland" (English Wikipedia). Spikes in edit frequency can indicate emerging controversy. This is a unique OSINT signal that no other arena provides.

#### Gab
**Source:** `src/issue_observatory/arenas/gab/collector.py` (963 lines)
**Relevance:** Moderate for fringe monitoring. Gab is a known vector for far-right and conspiracy content in the Anglophone world.
**Technical capability:** Uses Mastodon-compatible REST API. `collect_by_terms()` with fallback to hashtag timeline on HTTP 422 (lines documented in collector). Handles reblogs. No language filter parameter.
**Greenland value:** Gab is where English-language conspiracy theories about Greenland (US purchase, deep state narratives, Arctic resource control theories) would circulate. Danish-language content on Gab is likely minimal, but English-language content about "Denmark selling Greenland" or "Trump buying Greenland" would appear here.
**Limitation:** Free tier only. No language filter -- all language detection is post-collection.

### 2.3 Tier 3: Supplementary / Conditional

#### Discord
**Source:** `src/issue_observatory/arenas/discord/collector.py` (562 lines), `src/issue_observatory/arenas/discord/config.py`, `src/issue_observatory/arenas/discord/_http.py`
**Relevance:** Low-moderate. Discord could host niche political discussion servers about Greenland, but discovery is difficult.
**Critical limitation:** Discord bots **cannot use the search endpoint** -- only users can search. The `collect_by_terms()` method requires explicit `channel_ids` and performs client-side substring matching after fetching ALL messages from each channel (lines documented in collector.py). This means:
1. The research bot must be invited to each server manually.
2. Every message in the channel must be fetched, then filtered client-side.
3. There is no way to discover Greenland-relevant servers programmatically.

From `config.py` (line 49): `MESSAGES_PER_REQUEST: int = 100` with pagination via `before` cursor.
From `_http.py` (lines 209-296): The `fetch_channel_messages()` function paginates backward from the most recent message, with date range filtering applied during iteration.
From `danish_defaults.py` (lines 329-348): `DANISH_DISCORD_SERVERS` is an empty list, requiring manual population.

**Assessment for Greenland:** Discord monitoring is only viable if specific Greenland-relevant servers are identified through manual research and the bot is invited to them. The effort-to-value ratio is poor unless a known conspiracy community operates on Discord. Recommend deferring unless specific intelligence identifies relevant servers.

#### X/Twitter
**Source:** `src/issue_observatory/arenas/x_twitter/`
**Relevance:** Theoretically high (Danish politicians and journalists are active), but practically constrained by API access.
**Cost:** The X/Twitter API is now extremely expensive. Basic access ($100/month) provides only 10,000 tweets/month read access. Pro access ($5,000/month) is well beyond the budget. The free tier provides only write access and is useless for research collection.
**Assessment for Greenland:** Despite X/Twitter's importance for political discourse, the cost structure makes it non-viable for this project at the free/medium tier. The Bluesky arena partially compensates, as many Danish political actors have migrated. Recommend: monitor X/Twitter indirectly via GDELT (which captures tweets embedded in news articles) and Google Search (which indexes public tweets).

#### Facebook/Instagram (Meta Content Library)
**Source:** `src/issue_observatory/arenas/facebook/`, `src/issue_observatory/arenas/instagram/`
**Relevance:** Extremely high in theory (Facebook reaches 84% of Danes), but access-constrained.
**Current implementation:** Via Bright Data proxy ($500/month minimum). Direct Meta Content Library access requires an institutional application with a 2-6 month review process.
**Assessment for Greenland:** Facebook is where most Danish voters encounter Greenland discourse (political party pages, news outlet pages, public groups). The lack of affordable API access is the single largest coverage gap for Danish discourse research. The Bright Data pathway exists in the implementation but exceeds the budget ceiling.
**Recommendation:** Apply for Meta Content Library access immediately if not already in progress. This is a multi-month process. In the interim, Facebook public page content can be partially captured via RSS feeds (some outlets syndicate to Facebook), Google Search (which indexes public Facebook posts), and GDELT (which captures Facebook links in news articles).

#### LinkedIn (Manual Import)
**Source:** `src/issue_observatory/arenas/` (no dedicated collector; import endpoint only)
**Relevance:** Moderate. LinkedIn is used by 33% of Danes and hosts policy professional discourse.
**Current status:** No automated collection. An import endpoint exists for manually collected data.
**Greenland value:** LinkedIn is where Danish business and policy professionals discuss Arctic economic opportunities, Greenland mineral rights, and defense policy implications. However, the lack of automated collection makes it impractical for continuous monitoring.

#### Common Crawl
**Source:** `src/issue_observatory/arenas/web/common_crawl/collector.py` (545 lines)
**Relevance:** Moderate for historical web content discovery.
**Capability:** Queries the CC Index API for `.dk` domain captures. Term matching is against URL only, not page content. Returns metadata only -- WARC content retrieval is out of scope.
**Greenland value:** Can discover niche Danish websites discussing Greenland that are not captured by RSS feeds or search engines. The `.dk` TLD filter is correctly applied. However, the URL-only term matching means that a page about Greenland must have "greenland" or "gronland" in the URL to be found -- many do not.

#### Wayback Machine
**Source:** `src/issue_observatory/arenas/web/wayback/collector.py` (559 lines)
**Relevance:** High for deleted content recovery, especially if political actors delete statements about Greenland during the election campaign.
**Capability:** CDX API queries with `.dk` domain filtering. Returns capture metadata with constructable `wayback_url` for future content access.
**Greenland value:** Politicians and organizations may delete or modify public statements about Greenland sovereignty as the political landscape shifts during the election. The Wayback Machine provides evidence preservation capability. Content retrieval (actually downloading the archived page) is not yet implemented.

### 2.4 Tier 4: Not Viable or Deferred

#### Majestic
**Source:** `src/issue_observatory/arenas/majestic/collector.py` (1041 lines)
**Status:** PREMIUM only ($399.99/month Platinum plan).
**Greenland value:** Could map the link network connecting Greenland-focused websites, identifying which sites link to conspiracy content. Trust Flow and Citation Flow metrics could distinguish authoritative from fringe sources. However, the cost is prohibitive for this project.

#### Twitch
**Source:** `src/issue_observatory/arenas/twitch/collector.py` (deferred stub), `src/issue_observatory/arenas/twitch/config.py`
**Status:** DEFERRED. Only channel discovery via Helix API is implemented. Chat collection requires EventSub WebSocket (real-time streaming), and **historical chat messages do not exist on Twitch** -- once a stream ends, the chat is permanently lost.
**Greenland value:** Negligible. Greenland political discourse does not occur on Twitch in any significant volume.

#### VKontakte
**Source:** `src/issue_observatory/arenas/vkontakte/collector.py` (285 lines -- all stub)
**Status:** DEFERRED with hard legal blockers. From the module docstring (lines 1-54):
- EU sanctions context: VK Company sanctions status must be verified.
- Cross-border data transfer: No Russia GDPR adequacy decision (Schrems II).
- Russian jurisdiction: Federal Law No. 152-FZ interaction with GDPR.
- Geo-restrictions: API access from Denmark must be empirically verified.
- University DPO sign-off required before any data collection begins.

All methods raise `ArenaCollectionError` with the deferred message (lines 168-172, 205-209).
**Greenland value:** VKontakte is where Russian-language discourse about Arctic geopolitics occurs. Russian state media narratives about Greenland, NATO's Arctic strategy, and Danish sovereignty claims would appear on VK. However, the legal blockers are severe and unlikely to be resolved before the election.
**Recommendation:** Do not attempt VKontakte collection. Monitor Russian-language perspectives via GDELT (which captures Russian media translated to English), English-language Russian state media outlets (RT, Sputnik) via Google Search, and Telegram (where Russian state media maintains channels).

---

## 3. Cross-Arena Narrative Tracking Capabilities

### 3.1 Current Capabilities

The codebase has several features that support narrative tracking across arenas:

**Cross-arena flow analysis function (IP2-050):** Identified as needed in the strategic synthesis but **not yet implemented**. The `analysis/network.py` module builds co-occurrence networks from `content_records` but does not include temporal propagation detection (which arena publishes a story first and how it spreads).

**Temporal network snapshots (IP2-044):** Also identified as needed. The current `build_actor_cooccurrence_network()` and `build_term_cooccurrence_network()` functions produce static snapshots -- they do not support slicing by time window to observe network evolution.

**Content deduplication across arenas (implemented):**
Source: `src/issue_observatory/core/deduplication.py` lines 319-380 (`find_url_duplicates`), lines 386-454 (`find_hash_duplicates`), lines 112-226 (`find_near_duplicates`)
The `DeduplicationService` can identify when the same article appears across RSS, GDELT, Google Search, and Event Registry -- this is a prerequisite for narrative flow tracking because it establishes content identity across arenas.

**Telegram forwarding chains:**
Source: `src/issue_observatory/arenas/telegram/collector.py` (normalize method stores `is_forwarded`, `fwd_from_channel_id` in raw_metadata)
Telegram's forwarding metadata is preserved and could be used to trace how content propagates across Telegram channels. This is a unique capability among the arenas.

**search_terms_matched field:**
Every content record stores which search terms it matched as an array. This enables term-based narrative tracking: query "how many arenas matched term X this week?" across all arenas simultaneously.

### 3.2 Gaps for Greenland Narrative Tracking

**No cross-arena temporal propagation detection (CRITICAL)**
The system cannot answer: "Greenland sovereignty story appeared on GDELT at 14:00, RSS at 14:30, Bluesky at 15:00, Reddit at 16:30 -- what is the propagation sequence?" This requires:
1. Near-duplicate grouping across arenas (implemented via SimHash).
2. Temporal ordering within each group (not implemented).
3. Visualization of propagation sequences (not implemented).

**No narrative clustering**
Related but distinct content (e.g., one article about Trump's Greenland statement, another about Denmark's response, a third about Greenland's reaction) should be grouped into a "narrative cluster." This requires semantic similarity beyond SimHash (which detects near-duplicates, not thematic relatedness). BERTopic or similar topic modeling would be needed (IP2-054).

**No bot/coordination detection**
For foreign interference monitoring, the system would need to detect coordinated inauthentic behavior: many accounts posting the same content within a short window. The co-occurrence detection in `network_expander.py` (`find_co_mentioned_actors`, lines 189-269) detects actors who are mentioned together, but it does not detect coordinated posting patterns (same content, same time window, different accounts).

### 3.3 What Can Be Done Now (Without New Development)

Despite the gaps, a researcher using the current system can:

1. **Collect across 15+ arenas simultaneously** using a single query design with Greenland-related terms.
2. **Compare volume over time by arena** using the descriptive statistics module (`analysis/descriptive.py`), with the `volume_by_arena_platform()` function.
3. **Identify cross-arena duplicates** using the `DeduplicationService.run_dedup_pass()` method, which runs URL and hash dedup.
4. **Build actor co-occurrence networks** showing which actors discuss Greenland together, using `analysis/network.py`.
5. **Export to Gephi** for manual network analysis and temporal slicing (static GEXF, not dynamic).
6. **Track forwarding chains on Telegram** by querying `raw_metadata.is_forwarded` and `raw_metadata.fwd_from_channel_id`.

---

## 4. Conspiracy Theory and Foreign Interference Monitoring

### 4.1 Platform Coverage for Fringe Content

The Greenland scenario has a distinctive requirement: monitoring conspiracy theories and potential foreign interference. The relevant arenas and their capabilities:

| Arena | Fringe Content Potential | Current Status | Key Limitation |
|-------|--------------------------|---------------|----------------|
| Telegram | HIGH -- primary fringe messaging platform | Implemented but only 6 mainstream channels configured | Must add political/conspiracy channels manually |
| Gab | HIGH -- far-right English-language platform | Fully implemented | No language filter; Danish content minimal |
| Discord | MODERATE -- niche communities possible | Implemented but requires bot invitation per server | No global search; discovery is manual |
| Reddit | MODERATE -- r/conspiracy, r/worldnews threads | Implemented | Subreddit list must be expanded |
| TikTok | MODERATE -- viral misinformation vector | Implemented | 10-day engagement lag; content is video-first |
| Google Search | LOW-MODERATE -- captures fringe sites in results | Implemented | Requires specific search terms to find fringe content |
| Bluesky | LOW -- moderation-focused platform | Implemented | Less fringe content by design |
| VKontakte | HIGH for Russian interference | DEFERRED -- legal blockers | Cannot be used |
| X/Twitter | HIGH -- historically primary disinfo vector | Cost-prohibitive | $5000/month for meaningful access |

### 4.2 Specific Conspiracy Monitoring Gaps

**No content credibility scoring**
The system has no mechanism to distinguish authoritative from unreliable sources. The Majestic arena's Trust Flow metric could provide this, but it is PREMIUM-only ($399.99/month). A free alternative would be to maintain a curated list of known-credible and known-unreliable sources as actor metadata, but this requires manual curation.

**No image/video analysis**
Greenland-related disinformation may include manipulated images (e.g., fake maps showing US territory over Greenland) or deepfake videos. The system collects `media_urls` in raw_metadata but does not analyze visual content.

**No network anomaly detection**
Coordinated inauthentic behavior detection (CIB) requires temporal clustering of posting activity: many new accounts posting similar content within a narrow time window. The current co-occurrence analysis operates on term overlap, not temporal posting patterns.

**No account age/creation analysis**
Newly created accounts that immediately engage with Greenland content may indicate bot or troll activity. Account creation date is not systematically collected across arenas (Bluesky provides `createdAt`, Reddit provides `created_utc`, but most other arenas do not expose this).

### 4.3 What the System CAN Do for Conspiracy Monitoring

Despite the gaps, several useful capabilities exist:

1. **Term-based monitoring across fringe platforms:** Configure search terms including conspiracy-adjacent vocabulary:
   - Danish: "Gronland salgKonspirasjon", "Gronland USA", "Gronland suveraenitet"
   - English: "Greenland purchase", "Greenland conspiracy", "deep state Greenland", "Arctic resources"
   These terms would capture conspiracy content on Gab, Reddit, and Telegram.

2. **Actor network mapping:** Using snowball sampling from known conspiracy accounts, the system can discover connected actors. The `SnowballSampler.run()` method (lines 87-254 of `snowball.py`) supports multi-wave expansion with deduplication.

3. **Volume spike detection:** A sudden increase in Greenland-related content on Gab or Telegram, detected via `volume_over_time()` in `analysis/descriptive.py`, could indicate a coordinated campaign. The volume analysis exists; the alerting mechanism does not (would require manual monitoring of the analysis dashboard).

4. **Cross-arena duplication detection:** If the same text appears on Gab, Telegram, and Reddit within a short window, the `DeduplicationService` will flag it. This is a weak but useful signal of coordinated distribution.

---

## 5. Source Discovery and Actor-to-Collection Workflows

A researcher mapping Greenland discourse needs three complementary mechanisms for discovering and adding collection sources (accounts, channels, groups, subreddits, websites): (a) manual addition based on domain expertise, (b) discovery from already-collected data, and (c) network-based or similarity-based sampling that expands from known seeds. All three must feed smoothly into the collection pipeline. This section evaluates how well each works today.

### 5.1 Manual Addition — Works Well

**Actor Directory and Platform Presences**
Source: `src/issue_observatory/api/routes/actors.py` (lines 1087-1200), `src/issue_observatory/api/templates/actors/list.html`

The researcher can:
1. Create an actor in the Actor Directory (name, type, description)
2. Add platform presences — e.g., platform="telegram", platform_username="arctic_politics_channel"
3. Add the actor to an ActorList in a query design
4. Run collection — arenas with `collect_by_actors()` use these presences

This path works end-to-end. 20+ arenas support `collect_by_actors()`, including Telegram, Discord, Reddit, Bluesky, YouTube, TikTok, Gab, X/Twitter, Threads, Instagram, Facebook, Wikipedia, Event Registry, GDELT, and more. Only Google Search, Google Autocomplete, and AI Chat Search lack actor-based collection.

**Assessment**: The manual path is the strongest. A domain expert who knows which Telegram channels or Discord servers to monitor can add them. The main limitation is that platform-specific source lists (RSS feeds, subreddits, default Telegram channels) are hardcoded and not extensible through the UI — addressed by GR-01 through GR-04 in the roadmap.

### 5.2 Discovery from Collected Data — High Friction

**Entity Resolution (Cross-Platform Author Linking)**
Source: `src/issue_observatory/api/routes/actors.py` (lines 293-393), `src/issue_observatory/api/templates/actors/resolution.html`

The system detects when the same `author_display_name` appears on 2+ platforms and surfaces these as resolution candidates. The researcher can create an Actor record, linking the cross-platform identities. Merge and split operations are fully implemented (lines 1288-1429).

**Assessment**: Entity resolution works, but only for authors who happen to use the same display name across platforms — a weak heuristic.

**Critical Gap: No fast path from Content Browser to collection**

The Content Browser (`src/issue_observatory/api/templates/content/browser.html`) shows collected content with author names, platforms, and metadata. But there is **no mechanism** to go from "I see an interesting author or source in this content" to "add them to my collection."

A researcher who discovers a relevant Telegram channel mentioned in an RSS article, or finds a Discord server referenced in a Reddit post, must:
1. Note the channel/author name manually
2. Navigate to the Actor Directory
3. Create a new actor
4. Add the platform presence (handle, channel ID, etc.)
5. Add to an actor list in the query design
6. Re-run collection

This is 5+ navigation steps per discovered source. For the Greenland scenario, where the researcher might discover dozens of relevant channels, accounts, and websites during the initial collection sweep, this creates prohibitive manual overhead.

**What's needed**: A "quick add" action in the Content Browser — click an author name → create/link actor → add platform presence → add to active actor list. One flow, one page.

### 5.3 Network-Based Sampling (Snowball) — Works but Limited Platform Coverage

**Snowball Sampler**
Source: `src/issue_observatory/sampling/snowball.py` (lines 87-254)

The snowball sampler is fully implemented with a working UI panel in the Actor Directory (`actors/list.html` lines 272-596). The researcher can:
- Select seed actors from the current actor list
- Choose platforms for expansion
- Set depth (1-3 hops) and max actors per step
- Run sampling and view results in a table
- Add discovered actors to the current actor list

**Network Expander**
Source: `src/issue_observatory/sampling/network_expander.py` (lines 87-721)

Platform-specific expansion strategies exist for **only 3 platforms**:

| Platform | Expansion Method | Source Lines | Discovery Quality |
|----------|-----------------|-------------|-------------------|
| Bluesky | Follow graph (follows + followers, up to 500 per direction) | 360-429 | High — social graph reveals discourse community structure |
| Reddit | Comment mention mining (regex `u/username` in last 100 comments) | 431-498 | Moderate — finds accounts mentioned in conversation, not structural connections |
| YouTube | Featured channels metadata from `brandingSettings` | 500-582 | Low — only finds channels explicitly featured by seed, many channels don't use this |

**Platforms WITHOUT expanders** (returns empty list): Telegram, Discord, TikTok, Gab, X/Twitter, Threads, Instagram, Facebook, Wikipedia, GDELT, RSS, all web arenas.

This is the critical limitation for the Greenland scenario. The fringe platforms where the researcher most needs discovery — Telegram, Discord, Gab, TikTok — have no network expansion. A researcher who identifies one relevant Telegram channel cannot use the system to discover related channels.

**Generic co-mention fallback**
Source: `src/issue_observatory/sampling/network_expander.py` (lines 171-177)

A co-mention detection method exists in stub form — it would mine `content_records` for actors who are frequently mentioned alongside the seed actor. This is platform-agnostic and would work for any arena with collected content. However, it is **not implemented** (returns empty list with a comment noting future development).

**Gap in discovered actor handling**: Newly discovered actors from snowball sampling are returned as results but may not exist as Actor records in the database. Only actors that already have database records can be added to actor lists. If snowball discovers a truly new account, the researcher must manually create an Actor record for it before it can be used in collection.

### 5.4 Similarity-Based Sampling — Code Exists but Not Exposed

**Similarity Finder**
Source: `src/issue_observatory/sampling/similarity_finder.py` (lines 1-996)

A substantial similarity-based discovery module exists with three methods:

1. **Platform recommendations** (lines 190-259): Uses platform-native suggestion APIs
   - Bluesky: `app.bsky.graph.getSuggestedFollowsByActor`
   - Reddit: Finds top posters in subreddits where the seed actor posts
   - YouTube: Discovers video owners from related playlists

2. **Content similarity** (lines 261-363): Computes TF-IDF cosine similarity on actors' collected text content, with Jaccard word overlap as fallback. Returns top N similar actors ranked by content overlap.

3. **Cross-platform name search** (lines 365-424): Searches for an actor's name on other platforms
   - Bluesky: `app.bsky.actor.searchActors`
   - Reddit: `/users/search.json`
   - YouTube: `/search?type=channel`
   - Returns candidates with confidence scores

**Current status: NONE of these methods are exposed in the UI or API.** The similarity finder has no API routes and no frontend integration. A researcher cannot use any of these capabilities.

**Assessment**: The content similarity method (method 2) is particularly valuable — it would let a researcher say "find other accounts that post about similar topics to this actor." For the Greenland scenario, starting from one known Arctic policy commentator and discovering others who write about similar themes would be a powerful discovery tool. But it's completely inaccessible.

### 5.5 Platform Support Matrix for Discovery

| Platform | Manual Addition | Snowball Expansion | Similarity Discovery | Content-to-Actor |
|----------|:-:|:-:|:-:|:-:|
| Bluesky | Working | Working (follows/followers) | Code exists, not exposed | No quick path |
| Reddit | Working | Working (comment mentions) | Code exists, not exposed | No quick path |
| YouTube | Working | Working (featured channels) | Code exists, not exposed | No quick path |
| Telegram | Working | **Not implemented** | **Not implemented** | No quick path |
| Discord | Working | **Not implemented** | **Not implemented** | No quick path |
| TikTok | Working | **Not implemented** | **Not implemented** | No quick path |
| Gab | Working | **Not implemented** | **Not implemented** | No quick path |
| X/Twitter | Working | **Not implemented** | **Not implemented** | No quick path |
| Threads | Working | **Not implemented** | **Not implemented** | No quick path |
| RSS Feeds | Working (as outlet slugs) | N/A | N/A | No quick path |

### 5.6 Cross-Platform Link Mining — A Missing Discovery Mechanism

None of the existing discovery mechanisms exploit the most natural signal available in collected content: **outbound links to other platform accounts and channels.**

Fringe platform communities routinely cross-reference each other. A Telegram channel post might contain:
- `t.me/another_channel` — a link to another Telegram channel
- `discord.gg/invite_code` — a link to a Discord server
- `youtube.com/c/channel_name` — a link to a YouTube channel
- `gab.com/username` — a link to a Gab profile
- `bsky.app/profile/handle` — a link to a Bluesky account
- `reddit.com/r/subreddit_name` — a link to a Reddit community
- URLs to niche blogs or organization websites

Similarly, Reddit posts link to YouTube videos, Gab posts link to Telegram channels, and RSS articles link to social media profiles. This cross-platform link graph is already present in collected content — every content record stores `url`, `media_urls`, and the full `text_content` which may contain embedded URLs — but nothing mines it.

**This is arguably the single most effective form of network sampling for fringe platform research.** Unlike co-mention detection (which relies on @username patterns that vary by platform), URL patterns are standardized and unambiguous. A regex-based URL extractor can identify `t.me/`, `discord.gg/`, `youtube.com/`, `reddit.com/r/`, etc. with high precision. The discovered links can be automatically classified by target platform and converted into collection targets.

For the Greenland scenario, this means: collect from one known Telegram channel → find links to 3 other Telegram channels and 1 Discord server in the posts → add those as collection targets → collect from them → discover more links → repeat. This is network expansion through content-embedded link traversal, and it works across all platforms without requiring platform-specific APIs.

**Current status: Not implemented.** No URL extraction or cross-platform link mining exists in the sampling or enrichment modules. See GR-22 in Section 10.3.

### 5.7 Summary Assessment

The application provides a solid manual addition workflow and a working (but narrow) snowball sampler. The most significant gaps are:

1. **No fast path from collected content to collection targets** — the researcher sees something interesting but can't act on it without 5+ manual steps across multiple pages
2. **No cross-platform link mining** — outbound URLs in collected content (linking to other channels, accounts, servers, websites) are not extracted or used for discovery, despite being the most natural and platform-agnostic signal available
3. **Network expansion limited to 3 platforms** — the fringe platforms central to the Greenland scenario (Telegram, Discord, Gab, TikTok) have no expanders
4. **Similarity finder is dead code** — ~1000 lines of useful discovery logic that the researcher cannot access
5. **Co-mention fallback not implemented** — the one platform-agnostic expansion method that would work across all arenas is stubbed out
6. **Newly discovered actors require manual creation** — snowball results can't be directly converted to collection targets

These gaps are addressed in the updated roadmap items GR-17 through GR-22 (see Section 10.3).

---

## 6. Multi-Language Support

### 5.1 Current Language Support Architecture

The system's language support is centered on Danish, with partial English support:

**Platform-level language filters:**
Source: `src/issue_observatory/config/danish_defaults.py`

| Arena | Filter Mechanism | Configured Value |
|-------|-------------------|-----------------|
| Bluesky | `lang:da` query suffix | `BLUESKY_DANISH_FILTER = "lang:da"` (line 223) |
| Google Search | `hl=da`, `gl=dk` | `DANISH_GOOGLE_PARAMS` (lines 192-201) |
| YouTube | `relevanceLanguage=da`, `regionCode=DK` | `YOUTUBE_DANISH_PARAMS` (lines 234-246) |
| GDELT | `sourcelang=danish`, `sourcecountry=DA` | `GDELT_DANISH_FILTERS` (lines 207-217) |
| Reddit | Subreddit-based (no language filter) | English-language subreddits |
| TikTok | `region_code=DK` | Hardcoded in collector |
| Telegram | No language filter | None |
| Gab | No language filter | None |
| Discord | No language filter | None |
| RSS | Language implicit in feed selection | Danish feeds |
| Wikipedia | Project-based (`da.wikipedia`, `en.wikipedia`) | `DEFAULT_WIKI_PROJECTS` (line 315) |

**Post-collection language detection:**
Source: `src/issue_observatory/analysis/enrichments/language_detector.py` (lines 89-176)
The `DanishLanguageDetector` enricher classifies collected content using:
1. `langdetect` library (when installed): Returns ISO 639-1 code and confidence score.
2. Fallback heuristic: Counts Danish-specific characters (ae, o-slash, aa) -- if > 0.5% of characters are Danish-specific, classifies as `da`.

**PostgreSQL full-text search:**
Source: `src/issue_observatory/config/danish_defaults.py` lines 252-263
FTS configuration is `'danish'` (PostgreSQL snowball stemmer), which handles stemming and stop words for Danish text.

### 5.2 Greenland Multi-Language Gaps

The Greenland scenario requires support for **four languages**, of which only two are currently supported:

| Language | ISO Code | Current Support | Required For |
|----------|----------|----------------|--------------|
| Danish | `da` | Fully supported | Domestic political discourse |
| English | `en` | Partially supported (Google, Wikipedia, GDELT) | International coverage, US perspectives |
| Greenlandic (Kalaallisut) | `kl` | **Not supported at any level** | Greenlandic self-determination discourse |
| Russian | `ru` | **Not supported at any level** | Russian interference monitoring |

**Greenlandic (Kalaallisut) -- Critical Gap**
- The `langdetect` library's support for Kalaallisut is unverified. Most language detection libraries do not include `kl` as a supported language due to small training corpus.
- The Danish character heuristic fallback (checking for ae, o, aa) would misclassify Kalaallisut as "not Danish" because Kalaallisut uses a different character set (includes q, double consonants, long vowels).
- No Kalaallisut RSS feeds are configured.
- No Kalaallisut full-text search configuration exists in PostgreSQL (no `'kalaallisut'` text search configuration).
- The `BLUESKY_DANISH_FILTER = "lang:da"` would exclude Kalaallisut posts.

**Practical impact:** Greenlandic political discourse about self-determination and the relationship with Denmark occurs partly in Kalaallisut. Without Kalaallisut support, the system captures only the Danish-language and English-language perspectives on Greenland, missing the voices of Greenlandic people themselves. This is a significant methodological blind spot for research on Greenland sovereignty.

**Russian -- Important but Lower Priority**
- Russian-language content about Greenland/Arctic is primarily relevant for foreign interference monitoring.
- Direct collection from Russian platforms (VKontakte) is blocked by legal restrictions.
- Russian perspectives can be partially captured via GDELT (which includes machine-translated Russian media) and via Russian state media outlets' English-language social media presence (RT, Sputnik on Telegram and Gab).
- The `langdetect` library supports Russian (`ru`), so post-collection language detection would work.

### 5.3 Recommendations

1. **Allow multi-language selection per query design** (see GR-05). The language selector should accept multiple languages rather than forcing a single choice. This removes the need to hardcode support for any specific language — the researcher selects whichever languages are relevant to their topic.
2. **Allow researchers to add custom RSS feeds per query design** (see GR-01). Rather than hardcoding Greenlandic or Arctic feeds into `danish_defaults.py`, the researcher adds feed URLs (e.g., Sermitsiaq.AG, KNR.gl, Arctic Today) themselves through the UI.
3. **Generalize the language detection enricher** (see GR-07). The `langdetect` library already supports 55+ languages. Rename `DanishLanguageDetector` to `LanguageDetector` and let the researcher's configured language list drive which languages are expected vs. flagged as unexpected.
4. **For Russian and other languages with no direct collection path:** rely on indirect capture via GDELT (which includes machine-translated content), Telegram (where state media maintains channels), and Google Search (which indexes multilingual content). The researcher can add relevant Telegram channels through the mechanism in GR-02.

---

## 7. Web Scraping and Archival Capabilities

### 7.1 Current Web Collection Arenas

The system has three web-focused arenas, each with a different scope:

**Common Crawl**
Source: `src/issue_observatory/arenas/web/common_crawl/collector.py` (545 lines)
- Queries the CC Index API for `.dk` domain captures.
- `collect_by_terms()` matches terms against the URL string (line reference: term matching in collector's `_build_query_url` method), not page content.
- Returns metadata only (URL, MIME type, timestamp, content length) -- no page text.
- 1 req/sec courtesy throttle.
- `content_type = "web_index_entry"` in normalized records.

**Wayback Machine**
Source: `src/issue_observatory/arenas/web/wayback/collector.py` (559 lines)
- Queries Internet Archive CDX API for archived captures.
- `.dk` domain filtering applied.
- Returns capture metadata with a constructable `wayback_url` for future content access.
- Handles 503 responses gracefully with retry logic.
- `content_type = "web_page_snapshot"` in normalized records.

**Google Search**
Source: `src/issue_observatory/arenas/google_search/`
- Returns search result snippets and URLs, not full page content.
- Can discover niche Greenland-focused websites that do not have RSS feeds.

### 7.2 Web Scraping Gaps for Greenland

**No full-page content retrieval**
The most significant gap: none of the web arenas download and parse the actual HTML content of discovered pages. Common Crawl returns index metadata. Wayback returns archive metadata. Google Search returns snippets. For Greenland research, the researcher might discover that a niche blog at `groenlandsk-debat.dk` publishes relevant content, but the system cannot fetch and store the actual article text.

**No custom web scraper arena**
There is no general-purpose "web scraper" arena that, given a list of URLs, fetches the page, extracts text content (via readability or BeautifulSoup), and normalizes it into a content record. This would be useful for:
- Greenlandic government websites (naalakkersuisut.gl)
- Arctic policy think tanks (csis.org/programs/europe-russia-and-eurasia-program/arctic)
- Danish parliamentary proceedings on Greenland (ft.dk)
- Niche blogs and opinion sites

**WARC retrieval not implemented**
The Common Crawl collector explicitly notes that WARC retrieval is "out of scope for Phase 2." This means that even when the CC Index identifies that a relevant page was crawled, the system cannot retrieve the actual content from the WARC archive.

### 7.3 Recommendations

1. **Implement a generic URL scraper arena** (see GR-10, estimated effort: 3-5 days) that accepts a researcher-provided list of URLs, fetches pages via `httpx`, extracts main text content via `readability-lxml` or `trafilatura`, and normalizes into content records. The URL list should be configurable per query design, following the same self-service pattern as GR-01 through GR-04. This is the single most versatile addition — it enables any researcher to scrape niche websites, blogs, government pages, or think tank publications relevant to their topic without code changes.
2. **Implement WARC content retrieval** for Common Crawl results. The CC Index already provides the `warc_filename`, `warc_record_offset`, and `warc_record_length` -- these three fields are sufficient to retrieve the actual page content from Common Crawl's S3 bucket.
3. **Implement Wayback content retrieval** by fetching the archived page at the constructed `wayback_url`. The URL is already computed and stored in normalized records.

---

## 8. Data Management for Cross-Arena Research

### 8.1 Deduplication

**Exact deduplication (implemented):**
Source: `src/issue_observatory/core/deduplication.py` lines 386-454
SHA-256 content hashing catches identical text appearing on multiple arenas (e.g., a Ritzau wire story published verbatim by DR, TV2, and Politiken). URL normalization (lines 254-298) strips tracking parameters and normalizes hosts to detect the same article URL appearing across Google Search results and RSS feeds.

**Near-duplicate detection (implemented):**
Source: `src/issue_observatory/core/deduplication.py` lines 41-96 (SimHash), lines 112-226 (cluster detection)
SimHash 64-bit fingerprinting with Hamming distance threshold of 3. Union-Find clustering groups near-duplicates. This handles wire stories with minor editorial changes (headline rewriting, added paragraphs).

**Limitation for Greenland:** The O(n^2) pairwise comparison in `find_near_duplicates()` (lines 188-194) is noted as "suitable for per-run batches (typically < 50K)." For the Greenland scenario during peak election coverage, a single collection run might exceed this if all arenas are active simultaneously. The Union-Find clustering is efficient once comparisons are done, but the pairwise SimHash comparison is the bottleneck.

### 8.2 Pseudonymization

Source: `src/issue_observatory/core/normalizer.py` lines 1-80
SHA-256 pseudonymization with configurable salt (from `PSEUDONYMIZATION_SALT` environment variable). This is GDPR-compliant for research under Article 89(1) with appropriate safeguards. The salt must be kept secret so that re-identification requires knowledge of both the data and the application secret.

**Greenland-specific consideration:** Public political figures (Danish MPs, Greenlandic ministers, US officials) should generally not be pseudonymized in political discourse research -- their public statements are in the public interest. The system pseudonymizes all authors uniformly. A future enhancement would be to allow a "public figure" flag on actors in the Actor Directory that bypasses pseudonymization for their content records.

### 8.3 Data Volume Estimates

For the Greenland scenario, estimated daily collection volumes across active arenas:

| Arena | Estimated Daily Volume | Basis |
|-------|----------------------|-------|
| RSS Feeds (30+ feeds) | 500-2000 articles/day (all topics), 20-100 Greenland-relevant | DR alone publishes ~200 items/day |
| Google Search | 100-500 results per term per day | 10 search terms x 50-100 results each |
| Bluesky | 50-500 posts/day | Depends on search term specificity |
| Reddit | 20-100 posts+comments/day | 4-8 subreddits, keyword filtered |
| GDELT | 200-1000 articles/day | Greenland + Denmark + English international |
| YouTube | 10-50 videos/day | Danish + English, keyword filtered |
| TikTok | 20-100 videos/day | #gronland, #greenland hashtags |
| Telegram | 50-200 messages/day | Depends on channel count |
| Gab | 10-50 posts/day | Greenland-related English content |
| Event Registry | 50-200 articles/day | If medium tier activated |
| Wikipedia | 5-20 revision events/day | Greenland-related article watchlist |
| Common Crawl | N/A (batch, not real-time) | Periodic crawl index queries |
| Wayback | N/A (batch, not real-time) | Periodic archive queries |

**Total estimated daily volume:** 1,000-5,000 content records per day during normal periods; potentially 10,000-20,000 per day during peak election events (e.g., a Trump statement about Greenland, a Greenlandic referendum announcement).

**Storage impact:** At ~5KB per record (including raw_metadata JSONB), 5,000 records/day = ~25MB/day = ~750MB/month. PostgreSQL with monthly range partitioning handles this easily. The SimHash deduplication O(n^2) comparison at 5,000 records per run is ~12.5M comparisons -- still within the "suitable for per-run batches" threshold but approaching the upper bound.

### 8.4 Export Capabilities

Source: `src/issue_observatory/analysis/export.py`
Five export formats are supported: CSV, XLSX, NDJSON, Parquet, GEXF. For the Greenland scenario, the most useful formats are:
- **CSV/XLSX** for quantitative analysis in R or Python
- **GEXF** for network visualization in Gephi
- **Parquet** for efficient large-dataset processing

The strategic synthesis (IP2-005, IP2-006) identified that export columns need extension (adding `pseudonymized_author_id`, `content_hash`, `collection_run_id`, `query_design_name`) and human-readable headers. These improvements have been partially implemented in Phase A.

---

## 9. Cost Analysis

### 9.1 Free Tier Configuration

The following arenas are available at zero cost:

| Arena | Free Tier Capability | Credential Required |
|-------|---------------------|---------------------|
| RSS Feeds | Unlimited | No |
| GDELT | Unlimited (DOC API) | No |
| Bluesky | Unlimited (AT Protocol) | No (public API) |
| Common Crawl | Unlimited (CC Index) | No |
| Wayback Machine | Unlimited (CDX API) | No |
| Wikipedia | Unlimited (Wikimedia API) | No (User-Agent required) |
| Via Ritzau | Unlimited (v2 JSON API) | No |
| Google Autocomplete | Unlimited (undocumented endpoint) | No |
| Reddit | Rate-limited (100 req/min with OAuth) | Yes (free app registration) |
| YouTube | 10,000 units/day (~100 searches) | Yes (free API key) |
| Telegram | Unlimited (Telethon MTProto) | Yes (free API credentials) |
| TikTok | Varies by Research API approval | Yes (research API application) |
| Gab | Unlimited (Mastodon-compatible API) | Yes (free account) |
| Discord | Unlimited (Bot API) | Yes (free bot registration) |

**Total free tier monthly cost: $0**
**Free tier coverage assessment:** 14 arenas provide substantial Danish discourse coverage at zero cost. The primary gaps at free tier are: no Facebook/Instagram, no X/Twitter, no Event Registry (premium news API), no Majestic (link analysis).

### 9.2 Medium Tier Configuration

Adding the following paid services to the free tier:

| Arena/Service | Monthly Cost | Tier | Justification for Greenland |
|--------------|-------------|------|----------------------------|
| SerpAPI (Google Search) | $50/month (Developer) | Medium | 5,000 searches/month for Google SERP analysis |
| Event Registry | $149/month (Business) | Medium | 5,000 articles/month from 150K+ global sources |
| X/Twitter Basic | $100/month | Medium | 10,000 tweets/month (minimal but useful for major events) |
| **Total** | **$299/month** | | |

**Alternative medium configuration (lower cost):**

| Arena/Service | Monthly Cost | Tier | Justification |
|--------------|-------------|------|---------------|
| Serper.dev (Google Search) | $15/month (Starter) | Medium | 2,500 searches/month (cheaper alternative to SerpAPI) |
| Event Registry | $149/month (Business) | Medium | International news coverage |
| **Total** | **$164/month** | | |

**Medium tier coverage assessment:** Adding Event Registry closes the international news coverage gap significantly. Adding Google Search provides SERP analysis for how Danes discover Greenland information. The X/Twitter Basic tier provides only 10,000 tweets/month, which is thin but captures the most prominent political statements.

### 9.3 What the Budget Cannot Cover

| Arena/Service | Monthly Cost | Value for Greenland | Recommendation |
|--------------|-------------|---------------------|----------------|
| Meta Content Library | Free (if approved) | Extremely high (Facebook 84% of Danes) | Apply immediately; 2-6 month review |
| Bright Data (Facebook/Instagram) | $500+/month | High | Exceeds budget; defer |
| X/Twitter Pro | $5,000/month | High | Far exceeds budget; defer |
| Majestic Platinum | $399.99/month | Moderate (link analysis) | Exceeds budget; defer |
| Infomedia | Institutional subscription | Extremely high | Excluded per project specification |

### 9.4 Cost-Optimized Recommendation

For the Greenland scenario with budget constraints:

**Phase 1 (Immediate -- $0/month):** Activate all free-tier arenas. Once the self-service configuration mechanisms (GR-01 through GR-05) are built, the researcher adds their own Greenlandic RSS feeds, Telegram channels, subreddits, and Wikipedia seed articles through the UI. This covers 14 arenas and provides the foundational dataset.

**Phase 2 (When budget permits -- $164-299/month):** Add Event Registry for international news coverage and Google Search for SERP analysis. These two services close the most significant coverage gaps that money can address.

**Ongoing:** Submit Meta Content Library application. If approved (free), this would add the single most valuable data source for Danish discourse.

---

## 10. Prioritized Improvement Roadmap

This section presents improvements, cross-referenced against the existing IP2-xxx roadmap items where applicable. New items are assigned the prefix GR- (Greenland).

### 10.1 Critical Priority (Must-Do Before Collection Begins)

These items focus on building **researcher-configurable mechanisms** rather than hardcoding use-case-specific content. The goal is that any researcher — whether studying Greenland, housing policy, or any other issue — can configure the application themselves without code changes.

| ID | Description | Effort | Dependencies | Rationale |
|----|-------------|--------|--------------|-----------|
| GR-01 | **Researcher-configurable RSS feed list per query design.** Add a UI panel in the query design editor (or collection launcher) where the researcher can add custom RSS feed URLs alongside the built-in Danish defaults. Store as part of the query design's `arenas_config` JSON. The RSS arena collector should merge the researcher's custom feeds with the system defaults. | 2-3 days | None | Currently RSS feeds are hardcoded in `danish_defaults.py`. The Greenland scenario needs Greenlandic media feeds (Sermitsiaq, KNR), but future scenarios will need entirely different feeds. The researcher should be able to add any RSS feed URL without developer intervention. |
| GR-02 | **Researcher-configurable Telegram channel list per query design.** Add a UI field where the researcher can specify additional Telegram channel usernames to monitor beyond the system defaults. Store as part of the query design's `arenas_config` JSON. The Telegram collector already supports extending its channel list via `actor_ids` — surface this capability in the UI. | 2-3 days | None | Currently only 6 mainstream news channels are hardcoded. Any fringe monitoring scenario (not just Greenland) requires researcher-curated channel lists. |
| GR-03 | **Researcher-configurable Reddit subreddit list per query design.** Same pattern as GR-01 and GR-02: a UI field in the query design or arena config where the researcher adds subreddit names. The Reddit collector merges these with system defaults. | 1-2 days | None | Currently 4 subreddits are hardcoded. The Greenland researcher needs `r/Greenland`, `r/geopolitics`, etc.; an education researcher needs different subreddits entirely. |
| GR-04 | **Researcher-configurable Discord channel IDs and Wikipedia seed articles per query design.** Extend the per-arena configuration pattern (GR-01 through GR-03) to Discord (server/channel snowflake IDs) and Wikipedia (seed article titles). | 1-2 days | GR-01 pattern | Discord requires explicit channel IDs; Wikipedia requires seed articles. Both lists are currently empty in `danish_defaults.py` and can only be populated through code changes. |
| GR-05 | **Researcher-configurable language filters per query design.** Allow the query design to specify multiple languages (e.g., Danish + English, or Danish + English + Kalaallisut) rather than forcing a single language choice. Store as an array in the query design. Arena collectors should use these to construct appropriate platform-level filters where supported, and the enrichment pipeline should use them for post-collection language detection filtering. | 2-3 days | None | The Greenland scenario needs Danish + English + Kalaallisut. Other scenarios may need Danish + German or Danish only. The language selector currently forces a single choice. |
| GR-06 | **Add Discord, Twitch, and OpenRouter/AI Chat Search to the admin credentials dropdown.** These three platforms have implemented collectors but are missing from the credential provisioning UI (`admin/credentials.html` lines 77-94). | 0.5 days | None | Corresponds to UX blocker GL-B03. Three arenas are unreachable because credentials cannot be provisioned. |

### 10.2 High Priority (Should-Do Within First Two Weeks)

| ID | Description | Effort | Dependencies | IP2 Cross-Ref |
|----|-------------|--------|--------------|---------------|
| GR-07 | **Generalize language detection enricher beyond Danish.** The current `DanishLanguageDetector` enricher uses a Danish-specific character heuristic fallback. Rename/generalize it to a `LanguageDetector` that uses `langdetect` (which supports 55+ languages) as the primary method, with the Danish heuristic as one of several optional fallbacks. The researcher-configured language list from GR-05 should inform which languages are "expected" vs. "unexpected" in a given collection run, enabling language-based filtering in the content browser. | 2-3 days | GR-05 | Extension of IP2-008 |
| GR-08 | **Implement cross-arena temporal propagation detection**: Given a near-duplicate cluster (from SimHash), order records by `published_at` and compute propagation sequences showing which arena published first. Store as enrichment in `raw_metadata.enrichments.propagation`. | 3-5 days | IP2-050, IP2-032 (SimHash -- already implemented) | Implements IP2-050 |
| GR-09 | **Add volume spike alerting**: Implement a simple threshold-based alert that fires when term volume on any single arena exceeds 2x the rolling 7-day average. Send email notification (email infrastructure already exists per Task ae498f0). This is a generic monitoring feature, not Greenland-specific. | 1-2 days | None | New -- not in IP2 roadmap |
| GR-10 | **Implement URL scraper arena**: A generic arena that accepts a researcher-provided list of URLs, fetches page content via `httpx`, extracts main text via `trafilatura` or `readability-lxml`, and normalizes into content records. The URL list should be configurable per query design (same pattern as GR-01 through GR-04). This enables any researcher to scrape niche websites, blogs, or organization pages relevant to their topic. | 3-5 days | Arena brief required | New -- not in IP2 roadmap |

### 10.3 High Priority: Source Discovery and Actor-to-Collection Workflows

These items address the gaps identified in Section 5 — the three mechanisms through which researchers discover and operationalize new collection sources. They are arguably the most impactful improvements for any multi-platform research scenario, not just Greenland.

| ID | Description | Effort | Dependencies | IP2 Cross-Ref |
|----|-------------|--------|--------------|---------------|
| GR-17 | **Content Browser "quick add" to collection.** Add a contextual action on author names in the Content Browser: click an author → modal offers "Create Actor" (pre-filled with display name and platform) → auto-creates platform presence → offers to add to an actor list in the active query design. This collapses the current 5+ step manual process into a single flow. The same pattern should work for discovering a Telegram channel name, Discord server reference, or website URL mentioned in content — the researcher clicks and says "monitor this." Source: `src/issue_observatory/api/templates/content/browser.html` (new), `src/issue_observatory/api/routes/actors.py` (new endpoint). | 3-5 days | None | New |
| GR-18 | **Expose the Similarity Finder in the UI and API.** Wire `src/issue_observatory/sampling/similarity_finder.py` into the Actor Directory UI. Add API routes for: (a) platform recommendations ("find similar accounts to this actor on Bluesky/Reddit/YouTube"), (b) content similarity ("find other actors who post about similar topics"), (c) cross-platform name search ("search for this actor's name on other platforms"). Surface these as a "Discover Similar" panel on the actor detail page and as a tab alongside the existing Snowball Sampling panel. The content similarity method is particularly valuable — it lets a researcher say "find other accounts that post about the same topics as this one." | 3-5 days | None | New |
| GR-19 | **Implement the co-mention fallback in the network expander.** The generic co-mention detection in `src/issue_observatory/sampling/network_expander.py` (lines 171-177) is stubbed out. Implement it: mine `content_records` for authors who are frequently mentioned alongside the seed actor (via `@username` patterns, quoted content, or reply chains). This is the only platform-agnostic expansion method and would extend snowball sampling to **every arena with collected content** — including Telegram, Discord, Gab, TikTok, and all other platforms that currently have no expander. | 2-3 days | Requires collected content to exist | New |
| GR-20 | **Auto-create Actor records for snowball-discovered accounts.** Currently, newly discovered actors from snowball sampling are returned as results but cannot be added to actor lists unless they already have database Actor records. Change this: when snowball discovers a new account, automatically create an Actor record and ActorPlatformPresence so the researcher can immediately add it to a list and collect from it. Source: `src/issue_observatory/sampling/snowball.py` (lines 87-254), `src/issue_observatory/api/routes/actors.py` (snowball endpoint lines 422-542). | 1-2 days | None | New |
| GR-21 | **Add Telegram-specific network expander.** Telegram's forwarding metadata (`is_forwarded`, `fwd_from_channel_id` in `raw_metadata`) is already collected. Implement a Telegram expander that discovers channels from forwarding chains: "this channel frequently forwards from channel X and channel Y" → discover X and Y as collection targets. This is uniquely valuable because Telegram is the primary fringe monitoring platform and currently has no expansion support. Source: `src/issue_observatory/sampling/network_expander.py` (new method). | 2-3 days | Requires Telegram content to exist | New |
| GR-22 | **Cross-platform link mining from collected content.** Implement a content enricher or sampling module that extracts outbound URLs from `text_content` and `media_urls` in collected content records, classifies them by target platform using URL pattern matching (e.g., `t.me/` → Telegram channel, `discord.gg/` → Discord server, `youtube.com/c/` → YouTube channel, `reddit.com/r/` → subreddit, `bsky.app/profile/` → Bluesky account, `gab.com/` → Gab profile), and surfaces discovered platform targets to the researcher for import. This is the single most effective form of network sampling for fringe platform research because cross-platform linking is how these communities organically connect. A Telegram post linking to a Discord server or another Telegram channel is an explicit endorsement signal. The discovered links should be presented in a "Discovered Sources" panel, grouped by target platform, with one-click "add to collection" actions. This mechanism is fully platform-agnostic — it works on any content that contains URLs, which means it extends discovery to every arena without requiring platform-specific API support. | 3-5 days | Requires collected content; benefits from GR-17 (quick-add flow) | New |

### 10.4 Medium Priority (During Collection Period)


| ID | Description | Effort | Dependencies | IP2 Cross-Ref |
|----|-------------|--------|--------------|---------------|
| GR-11 | **Add coordinated posting detection enricher**: For each collection run, cluster records by (SimHash near-duplicate group, 1-hour time window, distinct author count). Flag clusters where 5+ distinct authors post near-identical content within 1 hour. | 2-3 days | IP2-036 (enrichment pipeline -- already implemented) | New -- extends IP2-036 |
| GR-12 | **Implement Wayback content retrieval**: Extend the Wayback arena to optionally fetch the actual HTML content at the constructed `wayback_url` and extract text via `trafilatura`. | 2-3 days | GR-10 (for text extraction logic) | Extension of existing Wayback arena |
| GR-13 | **Apply for Meta Content Library access** with specific justification for election discourse research. | 1 day (application) + 2-6 months (review) | None | Standing recommendation |
| GR-14 | **Public figure pseudonymization exception**: Add a `public_figure: bool` field to the Actor model. When True, bypass SHA-256 pseudonymization for that actor's content records so that public political statements are attributable. | 1-2 days | None | New -- GDPR-relevant |
| IP2-038 | **Emergent term extraction**: Directly relevant to discovering Greenland discourse associations that are not in the initial search term list (e.g., "militarbase", "rigsfaellesskab", "selvbestemmelse" appearing frequently in collected content). | 3-5 days | None | Already in IP2 roadmap |
| IP2-044 | **Temporal network snapshots**: Essential for tracking how the Greenland actor network evolves over the election campaign (new actors entering, existing actors shifting positions). | 3-5 days | None | Already in IP2 roadmap |
| IP2-034 | **Danish sentiment analysis**: Useful for classifying stance on Greenland sovereignty (supportive of sovereignty, supportive of Danish union, neutral). | 3-5 days | IP2-036 | Already in IP2 roadmap |

### 10.5 Low Priority (Post-Collection Enhancement)

| ID | Description | Effort | Dependencies | IP2 Cross-Ref |
|----|-------------|--------|--------------|---------------|
| GR-15 | **Narrative topic modeling**: Apply BERTopic to collected Greenland content to identify sub-narratives (sovereignty, resources, military, conspiracy, self-determination) automatically. | 5-7 days | IP2-054, IP2-036 | Extends IP2-054 |
| GR-16 | **Greenlandic political calendar integration**: Overlay Greenlandic political events (Inatsisartut sessions, Naalakkersuisut meetings) on volume-over-time charts as event annotations. | 1-2 days | IP2-033 | Extends IP2-033 |
| IP2-045 | **Dynamic GEXF export**: For Greenland network analysis in Gephi with Timeline, enabling visualization of how the actor network evolves week by week during the campaign. | 2-3 days | IP2-044 | Already in IP2 roadmap |
| IP2-043 | **Content annotation layer**: For qualitative coding of Greenland content by stance (pro-sovereignty, pro-union, neutral, conspiracy) and frame (security, economic, identity, democratic). | 5-7 days | None | Already in IP2 roadmap |

### 10.6 Example Query Design Specification: Greenland 2026

The following is a *draft example* showing how a researcher would configure a Greenland study using the self-service mechanisms described in GR-01 through GR-05. This is not intended to be hardcoded into the application — it illustrates the kind of configuration a researcher should be able to create entirely through the UI.

**Search Terms (Danish):**

| Category | Terms |
|----------|-------|
| Primary | Gronland, gronlandsk, Groenland, groenlandsk |
| Sovereignty | Gronlands selvstyre, Gronlands selvstaendighed, Rigsfaellesskabet, gronlandsk suveraenitet, selvstyre, selvbestemmelse |
| US/Trump | Trump Gronland, kobe Gronland, Gronland USA, amerikansk interesse Gronland |
| Resources | Gronlands mineraler, sjaeldne jordarter Gronland, Arktis ressourcer, gronlandsk olie |
| Military | Thule, Pituffik, militarbase Gronland, NATO Arktis, arktisk forsvar |
| Conspiracy | Gronland konspirasjon, Gronland deep state, Gronland korruption |

**Search Terms (English):**

| Category | Terms |
|----------|-------|
| Primary | Greenland, Greenlandic |
| Sovereignty | Greenland independence, Greenland sovereignty, Danish realm, Greenland self-rule |
| US/Trump | Trump Greenland, buy Greenland, purchase Greenland, US Greenland |
| Resources | Greenland minerals, rare earth Greenland, Arctic resources |
| Military | Thule Air Base, Pituffik Space Base, NATO Arctic |
| Conspiracy | Greenland conspiracy, deep state Greenland, Greenland cover-up |

**Search Terms (Kalaallisut):**

| Category | Terms |
|----------|-------|
| Primary | Kalaallit Nunaat, namminersorneq |
| Sovereignty | namminersornerullutik oqartussat, Inatsisartut |
| Government | Naalakkersuisut |

**Actor Lists:**

| Category | Examples |
|----------|----------|
| Danish Politicians | Prime Minister, Foreign Minister, Arctic policy spokespersons from all parties |
| Greenlandic Politicians | Premier (Naalakkersuisut chair), Inatsisartut members, Demokraatit/Siumut/IA leaders |
| US Officials | Secretary of State, US Ambassador to Denmark, relevant Senate/House committee chairs |
| Media | Sermitsiaq.AG, KNR, Arctic Today, DR Gronland correspondent |
| Think Tanks | Danish Institute for International Studies (DIIS), Arctic Institute, Center for Arctic Policy Studies |
| Organizations | Inuit Circumpolar Council, Nordic Council, NATO Arctic Command |

**Arena Configuration:**

| Arena | Tier | Active | Researcher-Added Sources (via GR-01–GR-04 mechanisms) |
|-------|------|--------|------------------------------------------------------|
| rss_feeds | Free | Yes | + Sermitsiaq.AG, KNR.gl, Arctic Today, High North News |
| bluesky | Free | Yes | (uses default settings) |
| reddit | Free | Yes | + r/Greenland, r/europe, r/geopolitics, r/worldnews |
| gdelt | Free | Yes | (also query with English terms for international coverage) |
| youtube | Free | Yes | (uses default settings) |
| telegram | Free | Yes | + Political commentary channels, Arctic geopolitics channels |
| tiktok | Free | Yes | (uses default settings) |
| gab | Free | Yes | (uses default settings) |
| wikipedia | Free | Yes | + "Gronland", "Rigsfaellesskabet", "Thule_Air_Base" seed articles |
| google_autocomplete | Free | Yes | (uses default settings) |
| ritzau_via | Free | Yes | (uses default settings) |
| common_crawl | Free | Yes | (uses default settings) |
| wayback | Free | Yes | (uses default settings) |
| google_search | Medium ($50/mo) | Conditional on budget | |
| event_registry | Medium ($149/mo) | Conditional on budget | |

---

## 11. Comparison with Previous Evaluations

### 11.1 Assessment Summary Across All Three Scenarios

| Dimension | CO2 Afgift (Feb 2026) | AI og Uddannelse (Feb 2026) | Greenland (Feb 2026) |
|-----------|----------------------|-----------------------------|----------------------|
| Overall readiness | 75-80% | 55-60% | **65-70%** |
| Arena coverage | Good (Danish domestic) | Good (Danish domestic) | **Moderate** (researchers can't add their own feeds/channels/subreddits) |
| Source discovery workflow | Not tested | Not tested | **Partial** — manual addition works; snowball on 3 platforms; similarity finder dead code; no content-to-collection quick path |
| Language support | Danish only needed | Danish + some English | **Danish + English + Kalaallisut + Russian needed** |
| Actor complexity | Moderate (Danish politicians, organizations) | Moderate (educators, unions, think tanks) | **High** (multi-jurisdictional: DK, GL, US, RU) |
| Conspiracy monitoring | Not required | Not required | **Required -- major gap** |
| Cross-arena narrative tracking | Desired but not critical | Desired for issue trajectory | **Critical -- central research question** |
| Cost sensitivity | Low | Low | **High -- free/medium tier required** |
| Temporal urgency | Ongoing (no hard deadline) | Ongoing (no hard deadline) | **High -- election-bounded window** |

### 11.2 What Changed Since the CO2 Afgift Evaluation

The following improvements have been implemented since the CO2 afgift evaluation (February 2026):

1. **SimHash near-duplicate detection** (IP2-032): Now implemented in `src/issue_observatory/core/deduplication.py`. The CO2 report flagged this as a critical gap for wire story deduplication. This directly benefits the Greenland scenario.

2. **Enrichment pipeline architecture** (IP2-036): Now implemented with `ContentEnricher` base class, `DanishLanguageDetector`, and `NamedEntityExtractor` stub. The CO2 report identified the absence of any enrichment infrastructure.

3. **Dynamic arena grid** (IP2-001): Phase A resolved the hardcoded arena grid, making all implemented arenas visible in the UI.

4. **Arena tier validation** (IP2-002): Phase A resolved misleading tier options.

5. **Duplicate exclusion in analysis** (IP2-004): Analysis queries now exclude duplicate-flagged records.

6. **Filter consolidation** (IP2-024): Analysis filter builders have been consolidated.

7. **New arenas implemented**: Discord, Wikipedia, Twitch (stub), VKontakte (stub). These were not present at the time of the CO2 evaluation.

8. **Emergent term extraction** (IP2-038): Implemented in Phase C.

9. **Temporal network snapshots** (IP2-044): Implemented in Phase C.

10. **Content annotation layer** (IP2-043): Implemented in Phase C.

11. **In-browser network preview** (IP2-042): Implemented in Phase C.

12. **Entity resolution UI** (IP2-041): Implemented in Phase C.

13. **Term grouping** (IP2-046): Implemented in Phase C.

14. **Per-arena GEXF export** (IP2-047): Implemented in Phase C.

15. **Education-specific RSS feeds** (IP2-058): Added in Phase C.

### 11.3 What the Greenland Scenario Uniquely Requires (Not Needed by Previous Scenarios)

| Requirement | Why Unique to Greenland | Existing IP2 Coverage | New Work Needed |
|-------------|------------------------|----------------------|-----------------|
| **Researcher-configurable platform sources** (RSS feeds, Telegram channels, subreddits, etc.) | Previous scenarios could use defaults; Greenland needs custom sources on every platform | None | GR-01 through GR-04 (builds reusable self-service mechanism) |
| **Fast content-to-collection workflow** | Greenland requires discovering dozens of channels/accounts during initial sweep and quickly operationalizing them | Entity resolution exists but is slow and indirect | GR-17 (content browser quick-add) |
| **Broad network expansion for source discovery** | Fringe platforms (Telegram, Discord, Gab) are central but have no expanders | Snowball works for Bluesky/Reddit/YouTube only | GR-19 (co-mention fallback), GR-21 (Telegram forwarding chains), GR-22 (cross-platform link mining) |
| **Similarity-based actor discovery** | Multi-jurisdictional actor space requires finding related accounts across platforms | `similarity_finder.py` exists (~1000 lines) but is dead code | GR-18 (expose in UI/API) |
| Multi-language query designs | Previous scenarios needed only Danish | None | GR-05 (reusable for any multilingual topic) |
| Generalized language detection | Previous scenarios needed only Danish detection | IP2-008 (Danish-only) | GR-07 (generalizes enricher for all languages) |
| Cross-arena narrative propagation velocity | Previous scenarios did not require temporal propagation tracking | IP2-050 (not implemented) | GR-08 |
| Coordinated posting detection | Previous scenarios did not involve foreign interference | None | GR-11 |
| Volume spike alerting | Previous scenarios did not have election-cycle urgency | None | GR-09 |
| Public figure pseudonymization exception | Previous scenarios did not distinguish public figures from private individuals | None | GR-14 |
| Generic URL scraper arena | Previous scenarios relied on existing API arenas | None | GR-10 (reusable for any topic needing web scraping) |
| Credential provisioning for all arenas | Previous scenarios used mainstream arenas with existing credential support | None | GR-06 (adds missing dropdown entries) |

### 11.4 Overall Assessment

The Issue Observatory is **65-70% ready** for the Greenland scenario. This is intermediate between the CO2 afgift readiness (75-80%) and the AI og uddannelse readiness (55-60%), reflecting that:

- The **core infrastructure** is solid: universal content records, deduplication, enrichment pipeline, actor resolution, and network analysis are all operational.
- The **arena coverage** is strong for Danish domestic discourse but researchers cannot extend it — RSS feeds, Telegram channels, Reddit subreddits, and Wikipedia seed articles are hardcoded and not configurable through the UI (addressed by GR-01 through GR-04).
- The **source discovery workflow** has a strong manual path and a working snowball sampler, but the gap between discovering a source and operationalizing it for collection is too wide. The content browser has no quick path to add discovered authors/channels to collection. The similarity finder (~1000 lines of discovery logic) is completely unexposed. Network expansion only works on 3 of 20+ platforms (addressed by GR-17 through GR-21).
- The **analytical capabilities** needed for narrative tracking and conspiracy monitoring exist in nascent form (SimHash, co-occurrence) but lack the temporal propagation and coordination detection features that are central to this scenario.
- The **cost constraint** is manageable -- 14 arenas are available at free tier, providing substantial coverage. The most impactful paid additions (Event Registry at $149/month, Google Search at $50/month) are within a $200-300/month budget.

The critical-priority items (GR-01 through GR-06) focus on building **researcher self-service mechanisms** — allowing users to configure their own RSS feeds, Telegram channels, Reddit subreddits, Discord servers, Wikipedia articles, and language filters per query design, plus adding missing credential dropdown entries. Total effort: ~10-14 days. These investments pay off across all future research scenarios, not just Greenland. The high-priority source discovery items (GR-17 through GR-21) address the most impactful workflow gap: enabling researchers to discover new sources from collected data, network expansion, and similarity search, and immediately operationalize them for collection (total: ~12-18 days). The analytical enhancement items (GR-07 through GR-10) add cross-arena narrative propagation, volume alerting, and a generic URL scraper (total: ~8-14 days).

---

## Appendix A: Source File Reference

All source file paths are relative to `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/`.

| File | Sections Referenced | Key Lines |
|------|-------------------|-----------|
| `src/issue_observatory/config/danish_defaults.py` | 2.1, 2.2, 5.1, 9.1, 9.5 | 47-156 (RSS), 175-186 (Reddit), 192-201 (Google), 207-217 (GDELT), 222-228 (Bluesky), 234-246 (YouTube), 252-263 (FTS), 299-323 (Wikipedia), 329-348 (Discord), 354-369 (Twitch) |
| `src/issue_observatory/arenas/telegram/collector.py` | 2.1, 3.1, 4.1 | 134-172 (collect_by_terms), 174-210 (collect_by_actors) |
| `src/issue_observatory/arenas/telegram/config.py` | 2.1, 4.1 | 14-73 (DEFAULT_DANISH_CHANNELS) |
| `src/issue_observatory/arenas/discord/collector.py` | 2.3, 4.1 | Client-side term matching, channel_ids requirement |
| `src/issue_observatory/arenas/discord/config.py` | 2.3 | 19-27 (tiers), 38-57 (API constants) |
| `src/issue_observatory/arenas/discord/_http.py` | 2.3 | 209-296 (fetch_channel_messages pagination) |
| `src/issue_observatory/arenas/gab/collector.py` | 2.2, 4.1 | Search with hashtag fallback, reblog handling |
| `src/issue_observatory/arenas/tiktok/collector.py` | 2.2, 4.1 | region_code DK, voice_to_text, 10-day engagement lag |
| `src/issue_observatory/arenas/vkontakte/collector.py` | 2.4 | 1-54 (legal blockers docstring), 168-172 (ArenaCollectionError) |
| `src/issue_observatory/arenas/twitch/collector.py` | 2.4 | Deferred stub, channel discovery only |
| `src/issue_observatory/arenas/twitch/config.py` | 2.4 | 50-56 (EventSub URL, no historical chat) |
| `src/issue_observatory/arenas/web/common_crawl/collector.py` | 6.1 | URL-only term matching, .dk TLD filter |
| `src/issue_observatory/arenas/web/wayback/collector.py` | 6.1, 6.2 | CDX API, wayback_url construction, metadata only |
| `src/issue_observatory/arenas/majestic/collector.py` | 2.4 | PREMIUM only, Trust Flow/Citation Flow |
| `src/issue_observatory/core/deduplication.py` | 7.1, 3.1 | 41-96 (SimHash), 112-226 (near-dup clusters), 254-298 (URL normalization), 306-658 (DeduplicationService) |
| `src/issue_observatory/core/normalizer.py` | 7.2 | 1-80 (pseudonymization, SHA-256 content hash) |
| `src/issue_observatory/analysis/enrichments/base.py` | 1.2 | 17-67 (ContentEnricher ABC) |
| `src/issue_observatory/analysis/enrichments/language_detector.py` | 1.2, 5.1 | 30-87 (heuristic), 89-176 (DanishLanguageDetector) |
| `src/issue_observatory/analysis/enrichments/named_entity_extractor.py` | 1.2 | 26-112 (NamedEntityExtractor stub) |
| `src/issue_observatory/analysis/network.py` | 1.2, 3.1 | Actor/term/bipartite network functions |
| `src/issue_observatory/analysis/descriptive.py` | 1.2, 3.3 | volume_over_time, top_actors, engagement_distribution |
| `src/issue_observatory/sampling/snowball.py` | 1.2, 5.3 | 87-254 (SnowballSampler.run) |
| `src/issue_observatory/sampling/network_expander.py` | 1.2, 5.3 | 87-187 (expand_from_actor), 171-177 (co-mention stub), 360-429 (Bluesky), 431-498 (Reddit), 500-582 (YouTube) |
| `src/issue_observatory/sampling/similarity_finder.py` | 5.4 | 190-259 (platform recommendations), 261-363 (content similarity), 365-424 (cross-platform name search) |
| `src/issue_observatory/api/routes/actors.py` | 5.1, 5.2 | 293-393 (entity resolution), 422-542 (snowball endpoint), 1087-1200 (platform presences), 1288-1429 (merge/split) |
| `src/issue_observatory/api/templates/actors/list.html` | 5.3 | 272-596 (snowball sampling UI panel) |
| `src/issue_observatory/api/templates/actors/resolution.html` | 5.2 | 133-321 (resolution candidates), 323-504 (merge UI) |
| `src/issue_observatory/api/templates/content/browser.html` | 5.2 | Content browser — no quick-add actor action exists |

## Appendix B: Cross-Reference to IP2 Roadmap

| IP2 Item | Greenland Relevance | Status as of Feb 2026 | Greenland-Specific Extension |
|----------|--------------------|-----------------------|-----------------------------|
| IP2-004 | High (correct analysis) | Implemented (Phase A) | None needed |
| IP2-008 | High (language detection) | Implemented (Phase B) | GR-07 extends to Kalaallisut |
| IP2-009 | High (Altinget feeds) | Implemented (Phase A) | None needed |
| IP2-032 | High (near-dedup) | Implemented (Phase B) | None needed |
| IP2-034 | High (sentiment) | Stub (Phase B) | Stance classification for Greenland sovereignty |
| IP2-036 | High (enrichment infra) | Implemented (Phase B) | GR-11 extends with coordination detection |
| IP2-038 | High (emergent terms) | Implemented (Phase C) | Direct application to Greenland term discovery |
| IP2-044 | High (temporal networks) | Implemented (Phase C) | Direct application to election network evolution |
| IP2-050 | Critical (cross-arena flow) | Not implemented | GR-08 is the Greenland implementation |
| IP2-054 | Medium (topic modeling) | Not implemented | GR-15 applies to Greenland narratives |
| IP2-057 | Low (Folketinget) | Not implemented | Could capture parliamentary Greenland debates |
| IP2-058 | Low (education feeds) | Implemented (Phase C) | Not directly relevant to Greenland |
| IP2-059 | High (Reddit expansion) | Partially implemented | GR-04 extends further for geopolitics subreddits |
