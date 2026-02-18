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
5. [Multi-Language Support](#5-multi-language-support)
6. [Web Scraping and Archival Capabilities](#6-web-scraping-and-archival-capabilities)
7. [Data Management for Cross-Arena Research](#7-data-management-for-cross-arena-research)
8. [Cost Analysis](#8-cost-analysis)
9. [Prioritized Improvement Roadmap](#9-prioritized-improvement-roadmap)
10. [Comparison with Previous Evaluations](#10-comparison-with-previous-evaluations)

---

## Scenario Context

The "Greenland in the Danish General Election 2026" scenario is qualitatively different from the two previously evaluated use cases (CO2 afgift discourse tracking and AI og uddannelse issue mapping). Its distinctive requirements are:

1. **Geopolitical sensitivity**: The Greenland question involves US interest (Trump administration), Danish sovereignty, Greenlandic self-determination, and Arctic geopolitics. This generates discourse in Danish, English, Greenlandic (Kalaallisut), and potentially Russian.

2. **Conspiracy theory and disinformation monitoring**: Foreign interference narratives (Russian trolls, US influence operations) require monitoring of fringe platforms (Gab, Telegram, Discord) alongside mainstream media.

3. **Cross-arena narrative velocity**: Stories about Greenland break in international news, propagate through social media, and are refracted through Danish domestic politics. Tracking the speed and mutation of narratives across arenas is central.

4. **Election-cycle temporality**: The 2026 general election creates a bounded but high-intensity collection window where discourse volumes spike and platform behavior changes (political advertising, bot activity).

5. **Low-cost requirement**: The research team requires a free/medium tier budget. Premium-only arenas ($399.99/month Majestic, $500/month X/Twitter Enterprise) are effectively excluded.

6. **Actor network complexity**: The actor landscape spans Danish politicians, Greenlandic politicians (Naalakkersuisut), Arctic policy experts, US officials, Russian state media, and grassroots movements -- a multi-jurisdictional actor space that the previous use cases did not encounter.

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
**Gap for Greenland:** No Greenlandic news media feeds. The following are missing and critical:
- **Sermitsiaq.AG** (the main Greenlandic daily, publishes in Danish and Kalaallisut)
- **KNR.gl** (Kalaallit Nunaata Radioa -- Greenland's public broadcaster, publishes in Danish)
- **Arctic Today** or **High North News** (English-language Arctic policy media)
**Assessment:** The current feed list is excellent for Danish domestic coverage but has a blind spot on Greenlandic perspectives. Adding 3-5 Greenlandic/Arctic feeds is a high-priority, low-effort improvement.

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
**Critical Gap:** No political channels, no conspiracy/disinformation channels, no Greenland-specific channels, no Russian-language channels. For the Greenland scenario, the following types of channels would need to be added:
- Danish political commentary channels
- Greenlandic community channels
- Arctic geopolitics channels
- Russian state media in Danish/English (RT, Sputnik if they have Telegram presence in the region)
- Known Danish conspiracy theory channels (these must be identified through manual research)

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
**Gap for Greenland:** Missing subreddits that are directly relevant:
- `r/Greenland` (small but topically critical)
- `r/dkpolitik` (Danish politics -- needs verification of activity level)
- `r/europe` (Greenland/Denmark sovereignty discussions frequently appear here)
- `r/geopolitics` (Arctic policy discourse)
- `r/worldnews` (for major Greenland stories with international reach)
**Assessment:** The current subreddit list is too narrow for the Greenland scenario. However, expanding it is a configuration-only change in `danish_defaults.py`.

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
**Configuration:** `DEFAULT_WIKI_PROJECTS = ["da.wikipedia", "en.wikipedia"]`. The `DANISH_WIKIPEDIA_SEED_ARTICLES` list is empty (line 299) and needs population with Greenland-relevant articles.
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

## 5. Multi-Language Support

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

1. **Add `kl` (Kalaallisut) to language filter options** in the query design editor, even though platform-level filtering for Kalaallisut is not available on most platforms. Post-collection filtering via `langdetect` (if it supports `kl`) would be the mechanism.
2. **Add Greenlandic news RSS feeds** (Sermitsiaq.AG, KNR.gl) to `DANISH_RSS_FEEDS` in `danish_defaults.py`. These outlets publish in both Danish and Kalaallisut, so no language filter is needed at the feed level.
3. **Test `langdetect` for Kalaallisut support** -- if unsupported, consider adding a character-frequency heuristic for Kalaallisut (checking for doubled consonants, `q`, long vowels) similar to the existing Danish heuristic.
4. **For Russian:** rely on indirect capture via GDELT and English-language Russian media Telegram channels rather than attempting direct Russian-language collection.

---

## 6. Web Scraping and Archival Capabilities

### 6.1 Current Web Collection Arenas

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

### 6.2 Web Scraping Gaps for Greenland

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

### 6.3 Recommendations

1. **Implement a generic URL scraper arena** (estimated effort: 3-5 days) that accepts a list of URLs, fetches pages via `httpx`, extracts main text content via `readability-lxml` or `trafilatura`, and normalizes into content records. This would be the most versatile addition for the Greenland scenario.
2. **Implement WARC content retrieval** for Common Crawl results. The CC Index already provides the `warc_filename`, `warc_record_offset`, and `warc_record_length` -- these three fields are sufficient to retrieve the actual page content from Common Crawl's S3 bucket.
3. **Implement Wayback content retrieval** by fetching the archived page at the constructed `wayback_url`. The URL is already computed and stored in normalized records.

---

## 7. Data Management for Cross-Arena Research

### 7.1 Deduplication

**Exact deduplication (implemented):**
Source: `src/issue_observatory/core/deduplication.py` lines 386-454
SHA-256 content hashing catches identical text appearing on multiple arenas (e.g., a Ritzau wire story published verbatim by DR, TV2, and Politiken). URL normalization (lines 254-298) strips tracking parameters and normalizes hosts to detect the same article URL appearing across Google Search results and RSS feeds.

**Near-duplicate detection (implemented):**
Source: `src/issue_observatory/core/deduplication.py` lines 41-96 (SimHash), lines 112-226 (cluster detection)
SimHash 64-bit fingerprinting with Hamming distance threshold of 3. Union-Find clustering groups near-duplicates. This handles wire stories with minor editorial changes (headline rewriting, added paragraphs).

**Limitation for Greenland:** The O(n^2) pairwise comparison in `find_near_duplicates()` (lines 188-194) is noted as "suitable for per-run batches (typically < 50K)." For the Greenland scenario during peak election coverage, a single collection run might exceed this if all arenas are active simultaneously. The Union-Find clustering is efficient once comparisons are done, but the pairwise SimHash comparison is the bottleneck.

### 7.2 Pseudonymization

Source: `src/issue_observatory/core/normalizer.py` lines 1-80
SHA-256 pseudonymization with configurable salt (from `PSEUDONYMIZATION_SALT` environment variable). This is GDPR-compliant for research under Article 89(1) with appropriate safeguards. The salt must be kept secret so that re-identification requires knowledge of both the data and the application secret.

**Greenland-specific consideration:** Public political figures (Danish MPs, Greenlandic ministers, US officials) should generally not be pseudonymized in political discourse research -- their public statements are in the public interest. The system pseudonymizes all authors uniformly. A future enhancement would be to allow a "public figure" flag on actors in the Actor Directory that bypasses pseudonymization for their content records.

### 7.3 Data Volume Estimates

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

### 7.4 Export Capabilities

Source: `src/issue_observatory/analysis/export.py`
Five export formats are supported: CSV, XLSX, NDJSON, Parquet, GEXF. For the Greenland scenario, the most useful formats are:
- **CSV/XLSX** for quantitative analysis in R or Python
- **GEXF** for network visualization in Gephi
- **Parquet** for efficient large-dataset processing

The strategic synthesis (IP2-005, IP2-006) identified that export columns need extension (adding `pseudonymized_author_id`, `content_hash`, `collection_run_id`, `query_design_name`) and human-readable headers. These improvements have been partially implemented in Phase A.

---

## 8. Cost Analysis

### 8.1 Free Tier Configuration

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

### 8.2 Medium Tier Configuration

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

### 8.3 What the Budget Cannot Cover

| Arena/Service | Monthly Cost | Value for Greenland | Recommendation |
|--------------|-------------|---------------------|----------------|
| Meta Content Library | Free (if approved) | Extremely high (Facebook 84% of Danes) | Apply immediately; 2-6 month review |
| Bright Data (Facebook/Instagram) | $500+/month | High | Exceeds budget; defer |
| X/Twitter Pro | $5,000/month | High | Far exceeds budget; defer |
| Majestic Platinum | $399.99/month | Moderate (link analysis) | Exceeds budget; defer |
| Infomedia | Institutional subscription | Extremely high | Excluded per project specification |

### 8.4 Cost-Optimized Recommendation

For the Greenland scenario with budget constraints:

**Phase 1 (Immediate -- $0/month):** Activate all free-tier arenas with Greenland-specific configuration. This covers 14 arenas and provides the foundational dataset.

**Phase 2 (When budget permits -- $164-299/month):** Add Event Registry for international news coverage and Google Search for SERP analysis. These two services close the most significant coverage gaps that money can address.

**Ongoing:** Submit Meta Content Library application. If approved (free), this would add the single most valuable data source for Danish discourse.

---

## 9. Prioritized Improvement Roadmap

This section presents Greenland-specific improvements, cross-referenced against the existing IP2-xxx roadmap items where applicable. New items are assigned the prefix GR- (Greenland).

### 9.1 Critical Priority (Must-Do Before Collection Begins)

| ID | Description | Effort | Dependencies | Rationale |
|----|-------------|--------|--------------|-----------|
| GR-01 | **Add Greenlandic news RSS feeds** to `DANISH_RSS_FEEDS`: Sermitsiaq.AG (sermitsiaq.ag/rss), KNR.gl (knr.gl/rss). Verify feed URLs and add to `danish_defaults.py`. | 0.25 days | None | Greenlandic perspectives are completely absent from the current feed list. |
| GR-02 | **Add Arctic/international news RSS feeds**: Arctic Today, High North News, The Arctic Institute. | 0.25 days | None | International Arctic policy coverage supplements the Danish domestic perspective. |
| GR-03 | **Expand Telegram channel list** with political, policy, and (verified) conspiracy-adjacent channels relevant to Greenland/Arctic discourse. Requires manual research to identify channels. | 1-2 days | Manual research | The current 6-channel list covers only mainstream Danish news. Telegram is the primary fringe monitoring platform. |
| GR-04 | **Expand Reddit subreddit list** to include `r/Greenland`, `r/europe`, `r/geopolitics`, `r/worldnews`, `r/dkpolitik` (verify activity). | 0.1 days | None | Cross-references IP2-059. Current list (4 subreddits) is too narrow for geopolitical discourse. |
| GR-05 | **Populate `DANISH_WIKIPEDIA_SEED_ARTICLES`** with Greenland-relevant article titles: "Gronland", "Rigsfaellesskabet", "Selvstyre_(Gronland)", "Gronlands_geologiske_undersogelse", "Thule_Air_Base", "Trump_Greenland_purchase" (English). | 0.1 days | None | Wikipedia edit activity monitoring requires seed articles. The list is currently empty (line 299 of `danish_defaults.py`). |
| GR-06 | **Design comprehensive Greenland query design** with search terms in all four languages and actor lists spanning Danish politicians, Greenlandic politicians, US officials, and Arctic policy organizations. | 2-3 days | GR-01 through GR-05 | This is the research design artifact that all collection depends on. See Section 9.5 for draft specification. |

### 9.2 High Priority (Should-Do Within First Two Weeks)

| ID | Description | Effort | Dependencies | IP2 Cross-Ref |
|----|-------------|--------|--------------|---------------|
| GR-07 | **Test and add Kalaallisut language detection** to `DanishLanguageDetector` enricher. Test whether `langdetect` supports `kl`. If not, implement Kalaallisut character-frequency heuristic alongside the Danish one. | 1-2 days | None | Extension of IP2-008 |
| GR-08 | **Implement cross-arena temporal propagation detection**: Given a near-duplicate cluster (from SimHash), order records by `published_at` and compute propagation sequences showing which arena published first. Store as enrichment in `raw_metadata.enrichments.propagation`. | 3-5 days | IP2-050, IP2-032 (SimHash -- already implemented) | Implements IP2-050 for the Greenland use case |
| GR-09 | **Add volume spike alerting**: Implement a simple threshold-based alert that fires when Greenland term volume on any single arena exceeds 2x the rolling 7-day average. Send email notification (email infrastructure already exists per Task ae498f0). | 1-2 days | None | New -- not in IP2 roadmap |
| GR-10 | **Implement URL scraper arena**: A generic arena that accepts a list of URLs, fetches page content via `httpx`, extracts main text via `trafilatura` or `readability-lxml`, and normalizes into content records. | 3-5 days | Arena brief required | New -- not in IP2 roadmap |

### 9.3 Medium Priority (During Collection Period)

| ID | Description | Effort | Dependencies | IP2 Cross-Ref |
|----|-------------|--------|--------------|---------------|
| GR-11 | **Add coordinated posting detection enricher**: For each collection run, cluster records by (SimHash near-duplicate group, 1-hour time window, distinct author count). Flag clusters where 5+ distinct authors post near-identical content within 1 hour. | 2-3 days | IP2-036 (enrichment pipeline -- already implemented) | New -- extends IP2-036 |
| GR-12 | **Implement Wayback content retrieval**: Extend the Wayback arena to optionally fetch the actual HTML content at the constructed `wayback_url` and extract text via `trafilatura`. | 2-3 days | GR-10 (for text extraction logic) | Extension of existing Wayback arena |
| GR-13 | **Apply for Meta Content Library access** with specific justification for election discourse research. | 1 day (application) + 2-6 months (review) | None | Standing recommendation |
| GR-14 | **Public figure pseudonymization exception**: Add a `public_figure: bool` field to the Actor model. When True, bypass SHA-256 pseudonymization for that actor's content records so that public political statements are attributable. | 1-2 days | None | New -- GDPR-relevant |
| IP2-038 | **Emergent term extraction**: Directly relevant to discovering Greenland discourse associations that are not in the initial search term list (e.g., "militarbase", "rigsfaellesskab", "selvbestemmelse" appearing frequently in collected content). | 3-5 days | None | Already in IP2 roadmap |
| IP2-044 | **Temporal network snapshots**: Essential for tracking how the Greenland actor network evolves over the election campaign (new actors entering, existing actors shifting positions). | 3-5 days | None | Already in IP2 roadmap |
| IP2-034 | **Danish sentiment analysis**: Useful for classifying stance on Greenland sovereignty (supportive of sovereignty, supportive of Danish union, neutral). | 3-5 days | IP2-036 | Already in IP2 roadmap |

### 9.4 Low Priority (Post-Collection Enhancement)

| ID | Description | Effort | Dependencies | IP2 Cross-Ref |
|----|-------------|--------|--------------|---------------|
| GR-15 | **Narrative topic modeling**: Apply BERTopic to collected Greenland content to identify sub-narratives (sovereignty, resources, military, conspiracy, self-determination) automatically. | 5-7 days | IP2-054, IP2-036 | Extends IP2-054 |
| GR-16 | **Greenlandic political calendar integration**: Overlay Greenlandic political events (Inatsisartut sessions, Naalakkersuisut meetings) on volume-over-time charts as event annotations. | 1-2 days | IP2-033 | Extends IP2-033 |
| IP2-045 | **Dynamic GEXF export**: For Greenland network analysis in Gephi with Timeline, enabling visualization of how the actor network evolves week by week during the campaign. | 2-3 days | IP2-044 | Already in IP2 roadmap |
| IP2-043 | **Content annotation layer**: For qualitative coding of Greenland content by stance (pro-sovereignty, pro-union, neutral, conspiracy) and frame (security, economic, identity, democratic). | 5-7 days | None | Already in IP2 roadmap |

### 9.5 Draft Query Design Specification: Greenland 2026

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

| Arena | Tier | Active |
|-------|------|--------|
| rss_feeds | Free | Yes -- with Greenlandic feeds added (GR-01, GR-02) |
| bluesky | Free | Yes |
| reddit | Free | Yes -- with expanded subreddits (GR-04) |
| gdelt | Free | Yes -- also query with English terms for international coverage |
| youtube | Free | Yes |
| telegram | Free | Yes -- with expanded channel list (GR-03) |
| tiktok | Free | Yes |
| gab | Free | Yes |
| wikipedia | Free | Yes -- with seed articles (GR-05) |
| google_autocomplete | Free | Yes |
| ritzau_via | Free | Yes |
| common_crawl | Free | Yes |
| wayback | Free | Yes |
| google_search | Medium ($50/mo) | Conditional on budget |
| event_registry | Medium ($149/mo) | Conditional on budget |

---

## 10. Comparison with Previous Evaluations

### 10.1 Assessment Summary Across All Three Scenarios

| Dimension | CO2 Afgift (Feb 2026) | AI og Uddannelse (Feb 2026) | Greenland (Feb 2026) |
|-----------|----------------------|-----------------------------|----------------------|
| Overall readiness | 75-80% | 55-60% | **65-70%** |
| Arena coverage | Good (Danish domestic) | Good (Danish domestic) | **Moderate** (missing Greenlandic, international Arctic, fringe) |
| Language support | Danish only needed | Danish + some English | **Danish + English + Kalaallisut + Russian needed** |
| Actor complexity | Moderate (Danish politicians, organizations) | Moderate (educators, unions, think tanks) | **High** (multi-jurisdictional: DK, GL, US, RU) |
| Conspiracy monitoring | Not required | Not required | **Required -- major gap** |
| Cross-arena narrative tracking | Desired but not critical | Desired for issue trajectory | **Critical -- central research question** |
| Cost sensitivity | Low | Low | **High -- free/medium tier required** |
| Temporal urgency | Ongoing (no hard deadline) | Ongoing (no hard deadline) | **High -- election-bounded window** |

### 10.2 What Changed Since the CO2 Afgift Evaluation

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

### 10.3 What the Greenland Scenario Uniquely Requires (Not Needed by Previous Scenarios)

| Requirement | Why Unique to Greenland | Existing IP2 Coverage | New Work Needed |
|-------------|------------------------|----------------------|-----------------|
| Greenlandic/Kalaallisut language support | Previous scenarios needed only Danish | None | GR-07 |
| Greenlandic media RSS feeds | Previous scenarios covered Danish domestic only | None | GR-01, GR-02 |
| Conspiracy channel monitoring on Telegram | Previous scenarios did not involve disinformation | None | GR-03 |
| Cross-arena narrative propagation velocity | Previous scenarios did not require temporal propagation tracking | IP2-050 (not implemented) | GR-08 |
| Coordinated posting detection | Previous scenarios did not involve foreign interference | None | GR-11 |
| Volume spike alerting | Previous scenarios did not have election-cycle urgency | None | GR-09 |
| Multi-jurisdictional actor space (DK/GL/US/RU) | Previous scenarios were Danish domestic only | None | GR-06 (query design) |
| Public figure pseudonymization exception | Previous scenarios did not distinguish public figures from private individuals | None | GR-14 |
| Generic URL scraper arena | Previous scenarios relied on existing API arenas | None | GR-10 |
| Arctic geopolitics subreddits | Previous scenarios needed only Danish subreddits | IP2-059 (partially) | GR-04 |

### 10.4 Overall Assessment

The Issue Observatory is **65-70% ready** for the Greenland scenario. This is intermediate between the CO2 afgift readiness (75-80%) and the AI og uddannelse readiness (55-60%), reflecting that:

- The **core infrastructure** is solid: universal content records, deduplication, enrichment pipeline, actor resolution, and network analysis are all operational.
- The **arena coverage** is strong for Danish domestic discourse but has significant gaps for Greenlandic, Arctic international, and fringe platform content.
- The **analytical capabilities** needed for narrative tracking and conspiracy monitoring exist in nascent form (SimHash, co-occurrence) but lack the temporal propagation and coordination detection features that are central to this scenario.
- The **language support** is the most significant structural gap -- Kalaallisut is completely unsupported and would require new development to address even partially.
- The **cost constraint** is manageable -- 14 arenas are available at free tier, providing substantial coverage. The most impactful paid additions (Event Registry at $149/month, Google Search at $50/month) are within a $200-300/month budget.

The critical-priority items (GR-01 through GR-06) are primarily configuration changes with very low effort (total: 3-5 days). These should be completed before any collection begins. The high-priority items (GR-07 through GR-10) represent meaningful new development (total: 8-14 days) that would significantly enhance the system's suitability for this scenario.

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
| `src/issue_observatory/sampling/snowball.py` | 1.2, 4.3 | 87-254 (SnowballSampler.run) |
| `src/issue_observatory/sampling/network_expander.py` | 1.2, 2.1 | 87-187 (expand_from_actor), 189-269 (co-mention), 360-429 (Bluesky), 431-498 (Reddit), 500-582 (YouTube) |

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
