# UX Test Report -- "Greenland" Issue Mapping for the Danish General Election 2026

Date: 2026-02-18
Scenario: Mapping discourse around "Greenland" as an issue in the Danish general election 2026
Arenas examined: All 24 implemented arena collectors, with focus on the 11 visible in UI + newly discovered discord, twitch, vkontakte, wikipedia, common_crawl, wayback, majestic, and ai_chat_search
Tiers examined: free, medium (selective), premium (Majestic only)
Evaluation method: Code-based static analysis of all templates, source files, collector implementations, configuration, arena registry, and data flow -- simulating every step a Danish politics/geopolitics researcher would take to map the "Greenland" issue across mainstream and fringe platforms

---

## Research Scenario

### Research Question

How is the issue of "Greenland" constituted in Danish public discourse leading up to the 2026 general election? Who are the key actors? What discourse associations emerge (sovereignty, independence, Arctic security, Trump/US, natural resources, colonial history, self-determination, NATO)? Where might conspiracy theories or foreign interference narratives form? How does discourse flow between mainstream media arenas and fringe/alternative platforms?

### Why This Scenario is a Uniquely Challenging Test

The Greenland scenario differs fundamentally from both the CO2 afgift and AI-og-uddannelse scenarios in ways that expose application weaknesses those earlier tests could not:

1. **Conspiracy and foreign interference dimension**: The researcher explicitly needs Telegram, Reddit, Discord, TikTok, Twitch, and Gab to cast a wide net across platforms where conspiracy theories and foreign interference narratives form. These platforms have fundamentally different data access models (Telegram requires MTProto credentials and pre-curated channels; Discord requires bot invitation to specific servers; Twitch only captures live chat in real time).

2. **International geopolitical topic with domestic resonance**: Unlike CO2 afgift (primarily domestic policy) or AI-og-uddannelse (sector-specific), "Greenland" intersects with Trump/US foreign policy, Russian Arctic ambitions, Chinese mining interests, indigenous self-determination, colonial history, and NATO security. Search terms must span Danish, English, and Greenlandic/Kalaallisut contexts.

3. **Web scraping requirement**: The researcher wants to find "relevant webpages that are neither social media platforms nor news sites, but small blogs, personal sites, organization sites" -- directly testing the Common Crawl, Wayback Machine, and Majestic arenas.

4. **Cross-arena data flow**: The scenario requires tracing how a narrative (e.g., "Trump wants to buy Greenland") flows from fringe platforms to mainstream media. This demands cross-arena comparison, provenance tracking, and temporal sequence reconstruction.

5. **Manual channel/account discovery**: For platforms without search endpoints (Discord, Twitch), the researcher must discover and specify which channels, servers, or streams to monitor. This tests the application's support for researcher-driven curation of data sources.

---

## Query Design Specification: "Greenland DK Election 2026"

### Search Term Strategy

For this geopolitically complex issue, search terms must cover six thematic dimensions:

#### Core Danish Political Terms

| Term | Type | Rationale |
|------|------|-----------|
| "Gronland" | Keyword | The primary Danish term for Greenland |
| "gronlandsk selvstaendighed" | Phrase | Greenlandic independence -- core constitutional question |
| "Rigsfaellesskabet" | Keyword | The Commonwealth of the Realm -- constitutional framework for Denmark/Greenland/Faroe Islands |
| "arktisk sikkerhed" | Phrase | Arctic security -- defense/geopolitical framing |
| "gronlandsk uafhaengighed" | Phrase | Greenlandic independence -- variant framing |
| "Mute Egede" | Phrase | Premier of Greenland -- key political actor |
| "kolonihistorie" | Keyword | Colonial history -- postcolonial framing of the relationship |

#### English Geopolitical Terms

| Term | Type | Rationale |
|------|------|-----------|
| "Greenland Denmark" | Phrase | English-language international coverage |
| "Trump Greenland" | Phrase | Trump's repeated interest in acquiring Greenland |
| "Arctic sovereignty" | Phrase | Sovereignty framing in English-language geopolitical discourse |

#### Conspiracy and Foreign Interference Terms

| Term | Type | Rationale |
|------|------|-----------|
| "Greenland Russia" | Phrase | Russian Arctic interest narrative |
| "Greenland China" | Phrase | Chinese mining/investment narrative |
| "arktisk strategi" | Phrase | Arctic strategy -- broader geopolitical framing |
| "Gronland USA" | Phrase | Danish-language framing of US interest |

#### Social Media Hashtags

| Term | Type | Rationale |
|------|------|-----------|
| #Gronland | Hashtag | Primary Danish hashtag |
| #GreenlandIsDanish | Hashtag | Pro-Danish sovereignty hashtag (English, social media) |
| #FreeGreenland | Hashtag | Pro-independence / anti-colonial hashtag |
| #ArcticSecurity | Hashtag | Geopolitical/defense framing |

#### Self-Determination and Indigenous Framing

| Term | Type | Rationale |
|------|------|-----------|
| "Inuit Ataqatigiit" | Phrase | Pro-independence Greenlandic political party |
| "selvbestemmelse Gronland" | Phrase | Self-determination -- indigenous rights framing |
| "Naalakkersuisut" | Keyword | Government of Greenland (Kalaallisut term) |

#### NATO and Defense

| Term | Type | Rationale |
|------|------|-----------|
| "Pituffik" | Keyword | Thule Air Base (renamed Pituffik Space Base) -- US military presence |
| "NATO Arktis" | Phrase | NATO Arctic presence -- defense discourse |

**Total: 23 search terms across 6 thematic dimensions.** This is the most extensive search term set of the three test scenarios, reflecting the geopolitical complexity and the conspiracy monitoring requirement.

---

## Step-by-Step Walkthrough

### Step 1: First Contact -- Dashboard and Navigation

**Researcher action:** A Danish politics/geopolitics researcher opens the Issue Observatory for the first time, intending to map Greenland discourse across mainstream and fringe platforms.

**What the researcher sees:** The dashboard with "Welcome, [name]", summary cards (Credits, Active Collections, Records Collected), Quick Actions (Create new query design, Start new collection, Browse content, Analyse data), and "About this platform" text.

**Assessment:**

The "Phase 0 -- Google Search arena active" stale text has been removed from the dashboard template (confirmed: no "Phase 0" string found in `src/issue_observatory/api/templates/dashboard/index.html` or `admin/health.html`). This addresses findings FP-01 and FP-02 from the CO2 afgift report.

**Phase A Fix Verified (FP-01/FP-02):** The stale "Phase 0" text has been removed from both the dashboard and the system health page. The researcher no longer sees contradictory information about which arenas are active.

The "Celery Beat" jargon in the live mode description has also been removed (confirmed: no "Celery Beat" or "celery beat" found anywhere in the templates directory). This addresses FP-16 from the CO2 afgift report.

**Phase A Fix Verified (FP-16):** Developer jargon "Celery Beat" has been removed from the collection launcher.

---

### Step 2: Creating the Query Design

**Researcher action:** Click "New Query Design" and enter:
- Name: "Greenland DK Election 2026"
- Description: "Mapping discourse around Greenland as an issue in the 2026 Danish general election. Covers sovereignty, independence, Arctic security, Trump/US, colonial history, conspiracy theories, and foreign interference narratives. Multi-platform study including fringe monitoring."
- Visibility: Private
- Default Tier: Free
- Language: Danish (da)

**Assessment:**

The query design creation form works as described in previous reports. The language dropdown still offers only three options: Danish (da), English (en), German (de). For the Greenland scenario, this is a significant limitation because the issue exists simultaneously in Danish, English, and Kalaallisut (Greenlandic). The researcher will need English search terms alongside Danish ones, but the language dropdown applies a single-language filter globally.

**Finding GL-01 (confirms IM-04):** The language selector forces a single language choice. For the Greenland scenario, the researcher needs to track discourse in both Danish AND English (and ideally Kalaallisut). There is no "multilingual" or "Danish + English" option. The researcher must choose Danish and hope that English search terms still return English-language results despite the Danish locale setting. On some arenas (Google Search with `gl=dk`, `hl=da`), setting language to Danish will bias results away from English-language international coverage of Greenland, potentially missing Trump/US narrative coverage from English-language media. [frontend], [core]

---

### Step 3: Adding Search Terms with Term Grouping

**Researcher action:** Add the 23 search terms specified above.

**Assessment:**

The search term panel in the query design editor has been significantly improved since the CO2 afgift report. Two critical Phase A additions are now present.

**Phase A Fix Verified (FP-04 -- Term Type Explanations):** The editor now includes a help text box (`src/issue_observatory/api/templates/query_designs/editor.html`, lines 257-262) with explanations for each term type:
- "Keyword -- Match any content containing this word."
- "Phrase -- Match exact multi-word phrase (use for names, compound terms)."
- "Hashtag -- Match the specific hashtag across social platforms."
- "URL pattern -- Match URLs containing this string (useful for tracking specific domains or articles)."

This addresses the previously reported FP-04 friction point. The researcher now understands what each type does before selecting it.

**Phase A Fix Verified (IM-06 -- Term Grouping):** The editor now supports term grouping. A "Group (optional)" input appears below the main term entry row (line 240-253), with a datalist offering predefined suggestions: "Primary terms", "Discourse associations", "Actor discovery terms", "English variants", "Related concepts" (lines 194-200). The Alpine `termGroupManager()` component (lines 792-924) manages visual group headers that are dynamically injected as `<li>` elements before each group's first term. Groups can be renamed inline by clicking the header label.

This is an excellent addition for the Greenland scenario. The researcher can now organize their 23 terms into the 6 thematic dimensions specified above, with visual group headers separating "Core Danish Political Terms" from "Conspiracy and Foreign Interference Terms" from "Social Media Hashtags" -- maintaining the analytical structure of the search term strategy.

**Finding GL-02 (new):** The term grouping feature is functional but has a subtle discoverability issue. The "Group (optional)" label and input are styled in a very muted fashion (`text-xs text-gray-400`, `bg-gray-50`, `border-gray-200`) and positioned on a secondary row below the main term entry. A researcher adding terms quickly may not notice it at all unless they specifically look for grouping capability. The datalist suggestions are helpful but require the researcher to click into the input to see them. A more prominent label or a brief note in the help text ("You can group terms by function -- e.g., Primary terms, English variants") would improve discoverability. [frontend]

**Phase A Fix Verified (FP-05 -- "termer" label):** The term count now reads "X terms" instead of "X termer" (line 206: `{{ terms | length }} term{% if terms | length != 1 %}s{% endif %}`). The mixed Danish/English language issue has been resolved.

**Finding GL-03 (new):** The group names are not persisted to the server when individual terms are renamed. The `termGroupManager.renameGroup()` method (lines 910-922) updates the DOM's `data-group` attributes client-side only, with a comment noting "A future PATCH endpoint would persist this change." If the researcher renames "Primary terms" to "Sovereignty terms" and refreshes the page, the rename is lost. For 23 terms across 6 groups, losing group structure on page refresh is frustrating. [frontend], [core]

---

### Step 4: Adding Actors for Greenland Discourse

**Researcher action:** Add key actors spanning the Greenland discourse:

| Actor | Type | Rationale |
|-------|------|-----------|
| Mute Egede | Person | Premier of Greenland (Naalakkersuisut) |
| Mette Frederiksen | Person | Prime Minister of Denmark |
| Lars Lokke Rasmussen | Person | Foreign Minister, key Greenland policy voice |
| Troels Lund Poulsen | Person | Defense Minister |
| Naalakkersuisut | Government body | Government of Greenland |
| Inuit Ataqatigiit | Political party | Pro-independence Greenlandic party |
| Det Udenrigspolitiske Selskab | NGO | Danish foreign policy society |
| Dansk Institut for Internationale Studier (DIIS) | Think tank | Danish foreign policy research |

**Assessment:**

The actor type dropdown now lists all 11 `ActorType` enum values (`src/issue_observatory/api/templates/query_designs/editor.html`, lines 309-321): Person, Organization, Political party, Educational institution, Teachers' union, Think tank, Media outlet, Government body, NGO, Company, Unknown.

For the Greenland scenario, the availability of "Political party", "Government body", "Think tank", and "NGO" as types is excellent -- these map directly to the actor categories in this geopolitical study.

**Phase A Fix Verified (C-3/C-4 -- Actor Type Fixes):** The Phase A QA report identified two critical actor type bugs: the default `actor_type="account"` (not a valid enum value) and the badge map spelling mismatch (`"organisation"` vs `"organization"`). However, examining the template at lines 347-356, the badge rendering in the editor template still uses the old pattern:

```
{% if atype == 'person' %}
    <span class="... bg-blue-100 text-blue-700 ...">Person</span>
{% elif atype == 'organisation' %}
    <span class="... bg-purple-100 text-purple-700 ...">Org</span>
{% elif atype == 'media_outlet' %}
    <span class="... bg-orange-100 text-orange-700 ...">Media</span>
{% else %}
    <span class="... bg-gray-100 text-gray-600 ...">Account</span>
{% endif %}
```

**Finding GL-04 (persists from C-4):** The editor template at line 351 still checks for `atype == 'organisation'` (British spelling) while the dropdown submits `value="organization"` (American spelling, line 311). Any actor added as "Organization" will fall through to the gray "Account" badge in the template. The QA report identified this fix requirement, but the template-side rendering has not been updated. Actors typed as "Government body", "Political party", "Think tank", "NGO", and "Organization" all render with the generic gray "Account" badge, losing visual distinction. For the Greenland scenario with 8 actors across 5 types, this makes the actor list visually undifferentiated. [frontend]

**Finding GL-05 (new, specific to Greenland scenario):** The actor type taxonomy does not include "State/Territory government" as a distinct category. "Naalakkersuisut" (the Government of Greenland) is neither a sovereign state government nor a standard organization -- it is a self-governing territory government within the Danish Realm. "Government body" is the closest available type, but it conflates Greenland's government with Danish ministries or EU institutions. For research on sovereignty and self-determination, this distinction matters politically. This is a minor taxonomic limitation, not a blocker -- the researcher can use "Government body" and clarify in their methodology. [research]

---

### Step 5: Arena Configuration -- The Critical Test for Fringe Monitoring

**Researcher action:** Open the Arena Configuration grid to enable arenas for the Greenland study.

**Assessment:**

The arena grid is now fetched dynamically from `GET /api/arenas/` (Phase A fix IP2-001). The Alpine `arenaConfigGrid()` component calls `fetch('/api/arenas/')` on `init()` (line 639). The backend `list_arenas()` in `registry.py` is now keyed by `platform_name` (not `arena_name`), and `autodiscover()` correctly imports all 24 collector modules. The `/api/arenas/` endpoint returns one entry per registered platform.

**However, there is a critical mismatch in the frontend that undermines this fix.**

**Finding GL-B01 (BLOCKER -- Arena grid collapses platforms by arena_name):** The frontend maps each API response entry to a grid row using `id: a.arena_name` (line 645 of editor.html). Since `arena_name` is a logical grouping label, not a unique identifier, multiple platforms share the same `arena_name`:

- `arena_name = "social_media"`: Reddit, YouTube, Telegram, TikTok, Gab, X/Twitter, Threads, Discord, VKontakte, Twitch (10 platforms)
- `arena_name = "news_media"`: Ritzau, Event Registry (2 platforms)
- `arena_name = "web"`: Common Crawl, Wayback, Majestic (3 platforms)

When Alpine renders `x-for="arena in arenas" :key="arena.id"`, the `arena.id` is not unique. All 10 social media platforms share `id: "social_media"`. The behavior depends on Alpine's key deduplication: either only the last platform with each `arena_name` renders (the remaining are silently dropped), or all render but share the same state (enable/disable toggles affect all rows with the same key simultaneously). In either case, the researcher cannot independently configure Reddit, Telegram, Discord, TikTok, Gab, etc.

This is worse than the original hardcoded list (which at least showed 11 distinct rows by using unique identifiers). The Phase A fix for IP2-001 solved the registry key collision on the backend but introduced a frontend key collision that collapses the expanded arena set back down.

The fix is straightforward: change line 645 from `id: a.arena_name` to `id: a.platform_name`. The saved config endpoint and the `_arenaLabel()` function must also be updated to use `platform_name` as the identifier.

**Research impact for the Greenland scenario:** The researcher cannot independently enable/configure Reddit, Telegram, Discord, Gab, TikTok, Twitch, X/Twitter, and Threads. This blocks the entire fringe monitoring dimension of the study. The researcher wanted to "cast the net widely across Telegram, Reddit, Discord, TikTok, Twitch" -- they cannot do this through the UI.

Additionally, the `_arenaLabel()` function (lines 751-764) only contains labels for 11 arena names. New arenas like Discord, Twitch, Wikipedia, Common Crawl, Wayback, Majestic, VKontakte, Facebook, and Instagram use the fallback `arenaName.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())` which converts `"common_crawl"` to `"Common Crawl"` (acceptable), `"ai_chat_search"` to `"Ai Chat Search"` (incorrect capitalization), and `"x_twitter"` to `"X Twitter"` (acceptable but should be `"X / Twitter"`).

---

### Step 6: Evaluating Individual Arenas for the Greenland Scenario

The researcher wants to configure the following arenas. I evaluate each against the Greenland use case.

#### Telegram -- Danish/Greenlandic Political Channels

**Configuration file:** `src/issue_observatory/arenas/telegram/config.py`

**Default channel list** (lines 54-61): `dr_nyheder`, `tv2nyhederne`, `berlingske`, `politiken_dk`, `bt_dk`, `informationdk`.

**Assessment for Greenland:** The default Danish Telegram channel list is entirely composed of mainstream news outlets. For the Greenland scenario, the researcher needs political and geopolitical channels: Danish defense-focused channels, Greenlandic political discourse channels, Arctic geopolitics channels, and potentially Russian/Chinese state media channels that discuss Greenland.

The Telegram collector supports extending the channel list via `actor_ids` in collection calls (line 181: `channels = _build_channel_list(self._default_channels, actor_ids)`). However, the researcher has no UI mechanism to specify additional Telegram channels. The actor list in the query design captures names and types but does not link to Telegram channel usernames. The researcher would need to add Telegram channel handles as actor platform presences in the Actor Directory, then ensure those presences are picked up as `actor_ids` during collection. This workflow is not documented or guided anywhere.

**Finding GL-06 (new):** Telegram channel discovery is entirely manual and undocumented from the researcher's perspective. The default channel list covers mainstream news only. For the Greenland scenario, the researcher needs to find and specify political/geopolitical Telegram channels, but the application provides no discovery tools for Telegram channels. The Telegram API supports `client.get_entity()` for resolving channel URLs, but no UI presents this capability. A researcher who wants to monitor a specific Greenland political channel (e.g., a hypothetical "gronlandnyt" or "arctic_politics" channel) must know its exact Telegram username in advance and add it as a platform presence in the Actor Directory. [frontend], [research]

**Finding GL-07 (new):** Telegram has no language filter (confirmed in the collector docstring: "No built-in language filter exists in Telegram. All messages from the configured Danish channel list are collected regardless of language." -- collector.py line 33). For the Greenland scenario, where the researcher searches channels that might contain both Danish and English content, there is no server-side or client-side language filtering. Language detection must happen downstream. The researcher is not informed of this limitation in the arena description or anywhere in the UI. [research]

#### Discord -- Political Community Discovery

**Configuration file:** `src/issue_observatory/config/danish_defaults.py`, line 329

**Default server list:** Empty (`DANISH_DISCORD_SERVERS: list[dict[str, str | list[str]]] = []`).

**Assessment for Greenland:** Discord is implemented (`src/issue_observatory/arenas/discord/collector.py`) as a fully functional collector using the Discord Bot REST API. However:

1. The default Danish Discord server list is empty -- there are no pre-configured servers.
2. The Discord collector requires explicit `channel_ids` for both `collect_by_terms()` and `collect_by_actors()` -- there is no global search capability for bots (line 160-166: "Discord requires explicit channel_ids -- there is no global keyword search for bot accounts").
3. The bot must be invited to each target server by its administrator before collection can begin.
4. Discord is missing from the credentials dropdown in the admin panel (confirmed: no "discord" option in `admin/credentials.html` lines 78-94).

**Finding GL-B02 (BLOCKER -- Discord unusable without pre-configured channels and credential support):** For the Greenland scenario, Discord could be a valuable arena for monitoring Danish political community discussions. However, three barriers make it completely unusable:
(a) No default Danish Discord servers are configured.
(b) No UI exists for the researcher to specify channel IDs or discover servers.
(c) Discord is not listed in the admin credentials dropdown, so the bot token cannot be provisioned through the UI.
The researcher must know specific Discord server/channel snowflake IDs, manually add the credential via CLI/database, and somehow pass channel IDs to the collector -- none of which is supported through the research workflow. [frontend], [core]

#### Twitch -- Live Political Discourse

**Configuration file:** `src/issue_observatory/config/danish_defaults.py`, line 354

**Default channel list:** Empty (`DANISH_TWITCH_CHANNELS: list[str] = []`).

**Assessment for Greenland:** The Twitch collector (`src/issue_observatory/arenas/twitch/collector.py`) is explicitly marked as a "DEFERRED stub implementation" (line 1). It implements channel discovery only via the Helix REST API -- the batch methods return channel metadata records, not chat messages (lines 16-18: "The batch methods here return **channel metadata records**, not chat messages. They are useful for channel discovery"). Real-time chat collection via EventSub WebSocket is NOT implemented.

**Finding GL-08 (new):** The Twitch arena is registered in the collector registry and will appear in the `/api/arenas/` response, but it is a stub that cannot collect chat messages. The collector.py docstring clearly states: "Twitch does not expose any endpoint for retrieving historical chat messages. Once a stream ends, chat is gone." (lines 8-9). For the Greenland scenario, monitoring Twitch for political discourse would only capture channel metadata (title, game, viewer count), not the actual chat content where discourse occurs. The researcher would see a "Twitch" arena in the grid with no indication that it is a stub. [frontend], [research]

#### Reddit -- Danish and International Political Subreddits

**Configuration file:** `src/issue_observatory/arenas/reddit/config.py`

**Subreddit list:** Now includes 8 subreddits: `Denmark`, `danish`, `copenhagen`, `aarhus`, `dkfinance`, `dkpolitik`, `scandinavia`, `NORDVANSEN` (lines 72-93).

**Assessment for Greenland:** The Reddit config has been improved since the CO2 afgift report. The addition of `dkpolitik` and `scandinavia` is directly relevant for the Greenland scenario. However, several subreddits that would be valuable for Greenland discourse are still missing:

- `r/Greenland` -- a small but directly relevant subreddit
- `r/geopolitics` -- English-language geopolitical discussions frequently cover Greenland
- `r/worldnews` -- international coverage
- `r/NATOwave` or similar defense-oriented subreddits
- `r/conspiracy` -- for monitoring conspiracy narratives about Greenland

**Finding GL-09 (new):** The Reddit subreddit list is hard-coded in `reddit/config.py` and `danish_defaults.py`. The researcher cannot add subreddits through the UI. For the Greenland scenario, `r/Greenland` is an obviously relevant subreddit that is not included. The researcher would need to know that subreddit configuration is a code-level change and request developer assistance. [research], [core]

#### Gab -- Far-Right and Fringe Political Content

**Collector:** `src/issue_observatory/arenas/gab/collector.py` -- fully implemented with search and actor-based collection via the Mastodon-compatible API.

**Assessment for Greenland:** Gab could contain far-right discourse about Greenland, particularly from the "GreenlandIsDanish" / anti-independence angle, or from Trump-aligned posters who discuss US acquisition of Greenland. The collector supports keyword search and is marked as `Tier.FREE`. Gab is included in the admin credentials dropdown (confirmed at line 88 of credentials.html). This is one of the few fringe platforms that is fully accessible through the research workflow.

**Phase A Fix Verified:** Gab was previously missing from the credentials dropdown. It is now present.

#### Common Crawl -- Blog and Personal Site Discovery

**Collector:** `src/issue_observatory/arenas/web/common_crawl/collector.py`

**Assessment for Greenland:** Common Crawl queries the CC Index API for `.dk` domain captures and filters by term in the URL path. This is directly relevant to the researcher's request to find "relevant webpages that are neither social media platforms nor news sites, but small blogs, personal sites, organization sites."

However, Common Crawl returns index metadata only -- no full page content (line 8-10: "Returns CC Index entries (metadata only) -- WARC record retrieval is out of scope for Phase 2"). The researcher gets URL, timestamp, and WARC location references, but not the actual text of the blog post.

**Finding GL-10 (new):** Common Crawl and Wayback Machine return metadata-only records. The researcher can discover URLs of blogs and personal sites that discuss Greenland (on `.dk` domains), but the actual content of those pages is not collected. The content_records table would contain URLs and timestamps but empty text_content fields. The researcher cannot do discourse analysis on Common Crawl results without manually visiting each URL. This limitation is not documented anywhere the researcher would see it. The arena description says "Common Crawl open web archive -- petabyte-scale crawl dataset (free)" which implies content is available, not just metadata. [research], [data]

#### Wayback Machine -- Historical Web Snapshots

**Collector:** `src/issue_observatory/arenas/web/wayback/collector.py`

**Assessment for Greenland:** Same limitation as Common Crawl -- returns CDX capture metadata only (line 8-10). Useful for discovering which Danish websites discussed Greenland historically, but not for content analysis. The Wayback Machine has a unique value for the Greenland scenario: tracking how specific Danish government pages about Greenland policy have changed over time. However, this use case requires full page content retrieval which is out of scope.

#### Majestic -- Backlink Intelligence

**Collector:** `src/issue_observatory/arenas/majestic/collector.py`

**Assessment for Greenland:** Majestic provides link graph data (Trust Flow, Citation Flow, backlinks) for web domains. For the Greenland scenario, it could reveal which websites link to key Greenland-related pages, mapping the web authority structure around the issue. However, Majestic requires PREMIUM tier only (line 8: "Supported tiers: PREMIUM only"), which conflicts with the researcher's budget constraint of "mainly free tier with selective medium tier use."

**Finding GL-11 (new):** Majestic is premium-only ($399.99/month API plan). The researcher explicitly asked for "free tier with selective medium tier usage." Majestic's premium-only requirement means the backlink intelligence dimension of the study is not available within the budget constraint. This is not a bug -- it is a legitimate tier constraint -- but the arena description in the grid says "Majestic backlink index -- maps web authority and citation networks (premium)" without stating the cost, which could lead to surprise when the researcher discovers the price. [research]

#### Wikipedia -- Editorial Attention Signals

**Collector:** `src/issue_observatory/arenas/wikipedia/collector.py`

**Assessment for Greenland:** Wikipedia is uniquely valuable for the Greenland scenario. The Danish Wikipedia article "Gronland" and related articles ("Rigsfaellesskabet", "Gronlands selvstyre", "Thulebasen") have edit histories that reflect how the issue is contested and revised in encyclopedic discourse. The Wikipedia collector supports both article search and revision history retrieval, querying both `da.wikipedia` and `en.wikipedia` (confirmed in `danish_defaults.py`, line 315).

**Finding GL-12 (new):** Wikipedia is a new arena not present in any previous report. It is well-suited to the Greenland scenario because Wikipedia edit wars and article revision patterns are a form of discourse contestation. The `DANISH_WIKIPEDIA_SEED_ARTICLES` list in `danish_defaults.py` (line 299) is empty, with example entries commented out. The researcher would need to populate this list with Greenland-related article titles, but there is no UI for this -- it is a code-level configuration. [research], [core]

#### AI Chat Search -- How LLMs Frame Greenland

**Collector:** `src/issue_observatory/arenas/ai_chat_search/collector.py`

**Assessment for Greenland:** The AI Chat Search arena queries LLM chatbots and captures their cited web sources. For the Greenland scenario, this would reveal how AI chatbots frame the Greenland sovereignty question -- a meta-level of analysis showing what information sources are being surfaced by LLMs when users ask about Greenland.

**Finding GL-13 (new):** AI Chat Search operates only at medium and premium tiers (no free tier). The researcher's budget allows "selective medium tier use," so this arena could be included for targeted queries. However, the arena grid frontend issue (GL-B01) prevents any interaction with this arena regardless. [research]

#### VKontakte -- Russian Perspective

**Collector:** `src/issue_observatory/arenas/vkontakte/collector.py`

**Assessment for Greenland:** VKontakte (VK) would be uniquely valuable for the Greenland scenario's conspiracy/foreign interference dimension: monitoring Russian-language discourse about Greenland and Arctic sovereignty. However, the collector is a complete stub -- all methods immediately raise `ArenaCollectionError` with the message: "VKontakte arena is not yet implemented. This arena is DEFERRED pending university legal review of EU sanctions implications."

**Finding GL-14 (new):** VKontakte is deferred pending legal review and cannot collect any data. For the Greenland scenario's foreign interference monitoring dimension, this removes the most direct window into Russian discourse about Arctic sovereignty. The stub appears in the arena registry and will appear in the grid, but any attempt to collect from it will fail with an error message about legal review -- which is appropriate for safety but frustrating for the researcher. [research]

---

### Step 7: Arena Configuration Grid -- Full Assessment

**Researcher action:** After understanding each arena's capabilities, attempt to configure the arena grid.

**Assessment:**

Due to GL-B01 (arena_name key collision in the frontend), the researcher cannot properly configure individual social media platforms. However, the arena grid does include several Phase A improvements that can be verified.

**Phase A Fix Verified (IP2-002 -- Tier Validation):** The arena grid now disables tier radio buttons for tiers not in `arena.supportedTiers` (lines 522-530). The label uses `cursor-not-allowed opacity-40` for unsupported tiers, and a tooltip explains: "This arena only supports free tier(s)" (via `unsupportedTierTitle()` at line 740-742). This means Bluesky's medium/premium options are greyed out with explanation, which addresses FP-09 from the CO2 report.

**Phase A Fix Verified (IP2-003 -- Arena Descriptions):** Each arena row now displays a description from `ARENA_DESCRIPTIONS` (lines 488-491). The description is shown as a muted text line below the arena name, truncated with CSS and showing the full text on hover. This addresses FP-13 from the CO2 report. For Greenland, the researcher can now see that "GDELT" means "GDELT global event database -- open dataset of news mentions worldwide" and that "Telegram" means "Telegram public channels collected via Telegram MTProto API."

**Phase A Fix Verified (Credential Status Indicator):** Each arena row shows a green/gray dot indicating whether credentials are configured (lines 478-482). This addresses FP-10's concern about credential visibility. The researcher can now see at a glance which arenas have active credentials.

**Phase A Fix Verified (Save Confirmation):** The arena config save button now shows a "Saved" success message that fades after 3 seconds (lines 567-600, using Alpine `x-show="saved"` with transition). This addresses FP-14 from the CO2 report.

**Finding GL-15 (new):** The content browser's arena filter checkboxes are still hardcoded to 11 arenas (confirmed in `browser.html` lines 61-73). Even if the arena grid is fixed to show all 24 platforms, the content browser filter will only show the original 11. Records from Discord, Wikipedia, Common Crawl, Wayback, etc. cannot be filtered individually in the content browser -- they would appear in "All" but have no dedicated checkbox. [frontend]

---

### Step 8: Collection Launch and Monitoring

**Researcher action:** Save the query design, navigate to the detail page, click "Run collection."

**Assessment:**

**Phase A Fix Verified (IP2-018 -- Collection Detail Shows Run Data):** The collection detail template (`collections/detail.html`, lines 41-47) now conditionally shows the query design name in the page header when `run.query_design_name` is available, falling back to "Collection Run" if not. Lines 53-63 show search terms as styled badges when `run.search_terms` is populated. This addresses FP-19 and FP-20 from the CO2 report.

The collection launcher template (confirmed in `collections/launcher.html`) continues to work as expected: query design selector, mode toggle, date range, tier selector, and credit estimate panel.

---

### Step 9: Browsing Collected Content -- Cross-Arena Comparison

**Researcher action:** After collection, browse results in the Content Browser with a focus on comparing mainstream vs. fringe discourse about Greenland.

**Assessment:**

The content browser's search term filter has been improved. It now uses an HTMX-loaded dropdown that fetches terms from `GET /content/search-terms?run_id={uuid}` when a collection run is selected (lines 140-158, 161-168). This addresses IM-20's concern about free-text term filtering.

However, the stale "BACKEND GAP" comment remains in the template (lines 124-139) stating that the endpoint "does not yet exist." The QA report confirmed the endpoint IS now implemented (`content.py` line 758). The comment is misleading for developers but invisible to researchers.

**Finding GL-16 (new -- specific to Greenland scenario):** The content browser has no mechanism for comparing mainstream vs. fringe content side by side. For the Greenland scenario, the researcher wants to see whether the "Trump Greenland" narrative appears differently on Gab versus RSS feeds. The browser supports filtering by arena checkboxes one at a time, but not comparative views (e.g., split screen showing Gab results on the left and RSS results on the right). The researcher must mentally switch between arena filters, losing context. This is a design limitation inherent to the single-table content browser paradigm. [frontend], [research]

**Finding GL-17 (new -- specific to Greenland scenario):** The content browser cannot show which arena a record came from without clicking into the detail panel on standard laptop screens. The arena column is hidden below the xl breakpoint (1280px) -- this persists from FP-21 in the CO2 report. For the Greenland scenario where distinguishing between mainstream (RSS, GDELT) and fringe (Gab, Telegram) is the central analytical question, this is especially problematic. [frontend]

---

### Step 10: Actor Discovery -- Cross-Platform Tracking for Greenland

**Researcher action:** Navigate to the Actor Directory to set up cross-platform tracking and snowball sampling.

**Assessment:**

**Phase A Fix Verified (IP2-007 -- Actor Synchronization):** The actor sync code is implemented in `query_designs.py` (lines 830-920). When a researcher adds an actor to a query design, the system calls `_find_or_create_actor()` which performs a case-insensitive lookup on `canonical_name` and either links to an existing Actor record or creates a new one. The `_get_or_create_default_actor_list()` function ensures each query design has a "Default" actor list. This addresses blocker IM-B01 from the AI-og-uddannelse report.

The researcher who adds "Mute Egede" to the query design should now find this actor in the Actor Directory. The `Profile` link appears on the actor list item when `actor_id` is present (editor.html lines 358-362), bridging the query design to the directory.

**Finding GL-18 (new -- verifying actor sync):** While the backend actor sync is implemented, the sync only creates a canonical Actor record with the name and type. It does NOT create platform presences for the actor. The researcher adds "Mute Egede (Person)" to the query design -- an Actor record is created in the directory -- but the actor has no Bluesky handle, no Telegram channel, no Reddit username. The researcher must still manually navigate to the actor's profile page and add platform presences one by one. For the Greenland scenario with 8 actors who may each be present on 3-5 platforms, this is 24-40 manual entries. [frontend], [core]

**Finding GL-19 (new -- Greenland-specific):** The Snowball Sampling panel would be valuable for discovering additional actors in the Greenland discourse network. However, snowball sampling relies on network traversal on platforms with follow/reply structures. For the Greenland scenario's fringe platform focus, the most important discovery would be finding relevant Telegram channels, Discord servers, and Gab accounts -- but snowball sampling on these platforms may not be supported or may require specific credential types that the researcher does not have. The sampling platform selection checkboxes may not include all relevant platforms. [research]

---

### Step 11: Analysis Dashboard and Network Export

**Researcher action:** Navigate to the Analysis dashboard for the completed collection run.

**Assessment:**

**Phase A Fix Verified (IP2-012 -- Analysis Filter Dropdowns):** The analysis filter bar now uses `<select>` dropdowns for Platform and Arena (confirmed in `analysis/index.html` lines 170-173), populated from `GET /analysis/{run_id}/filter-options`. However, the stale "BACKEND GAP" comment persists in the template (lines 158-165) claiming the endpoint does not exist -- it does. The dropdowns function correctly when the endpoint responds with the distinct platform and arena values.

**Phase A Fix Verified (IP2-006 -- Human-Readable Export Headers):** The export module (`analysis/export.py` lines 79-101) now defines `_COLUMN_HEADERS` with human-readable labels: "Platform", "Arena", "Content Type", "Title", "Text Content", "URL", "Author", "Author ID (Pseudonymized)", etc. The columns now include `collection_run_id` and `query_design_id` (lines 70-72), addressing IM-38 from the AI-og-uddannelse report.

**Phase A Fix Verified (IP2-004 -- Duplicate Exclusion in Analysis):** The `_filters.py` module now always appends a `(raw_metadata->>'duplicate_of') IS NULL` predicate to all analysis queries, ensuring duplicates are excluded from charts and network exports. This addresses the deduplication transparency concern from DQ-03 of the CO2 report.

**Finding GL-20 (new -- specific to Greenland network analysis):** The GEXF network export generates three types: actor co-occurrence, term co-occurrence, and bipartite. For the Greenland scenario with 23 search terms across 6 thematic groups, the term co-occurrence network would be particularly valuable -- revealing which discourse frames (sovereignty, Trump, colonial history, Arctic security) cluster together. However, the GEXF export does not preserve the term group labels from the query design. In Gephi, the researcher sees 23 term nodes in a flat list with no indication that "gronlandsk selvstaendighed" and "Rigsfaellesskabet" belong to the "Core Danish Political Terms" group while "Greenland Russia" and "Greenland China" belong to the "Conspiracy" group. The group_label should be included as a node attribute in the term GEXF. [data], [research]

**Finding GL-21 (persists from IM-39):** There is no per-arena GEXF export. For the Greenland scenario, the researcher specifically wants to compare discourse network structures between mainstream arenas (RSS, GDELT) and fringe arenas (Gab, Telegram). This requires generating separate GEXF files filtered by arena, which is not supported. The researcher must export CSV, filter in R/Python, and rebuild networks manually. [research]

---

### Step 12: Cross-Arena Data Management Assessment

The researcher's central question is: "Can the interface support managing different types of data from different arenas, using data collected in one Arena in another while maintaining provenance, and both combining AND disentangling arenas?"

#### Managing Different Data Types

**Google Autocomplete** produces search suggestion data (public associations). **Google Search** produces ranked URL lists (attention delegation). **Bluesky/Reddit/Gab** produce short-form social posts. **RSS/GDELT** produce news article metadata. **Telegram** produces channel messages. **Common Crawl/Wayback** produce URL index entries.

These are fundamentally different data types, but the application normalizes them all into the `content_records` schema. The `content_type` field distinguishes between types (e.g., "post", "article", "suggestion", "domain_metrics"), and the `arena` and `platform` fields preserve provenance.

**Finding GL-22 (new):** The content_records schema is flexible enough to hold all data types, but the content browser does not visually distinguish between them. A Google Autocomplete suggestion, a Bluesky post, and an RSS article all appear as rows in the same table. The "Content Type" is not shown as a column or badge in the table rows (confirmed: browser.html table columns are Platform, Content, Author, Published, Arena, Engagement -- no Content Type). For the Greenland scenario where the researcher explicitly needs to distinguish between "public associations" (Autocomplete), "attention delegation" (Search), and "discourse" (social/news), this information is only available in the detail panel's raw metadata. [frontend]

#### Using Data from One Arena in Another

The application's Actor Directory is the primary mechanism for cross-arena data use. An actor discovered in RSS collection (e.g., a politician mentioned in news articles) can be added to the Actor Directory and then used for actor-based collection on Bluesky or Reddit.

However, this workflow is manual. There is no automated "discover actors in Arena A, then automatically collect their posts from Arena B" pipeline.

**Finding GL-23 (new):** Cross-arena data use is technically possible but entirely manual. The researcher must: (1) browse content from Arena A, (2) identify an actor, (3) click "Find actor" to create/link in the Actor Directory, (4) add platform presences for the actor on other platforms, (5) run a new collection with actor-based mode on those platforms. Each step requires navigating to a different page. There is no "right-click actor -> collect from all platforms" shortcut. For the Greenland scenario with potentially dozens of actors, this creates a significant manual overhead. [frontend], [core]

#### Provenance Tracking

Each content record stores `arena`, `platform`, `collection_run_id`, and `collection_tier`. These are now included in the flat export columns (Phase A fix IP2-006). In the content browser, the detail panel shows the arena and collection run ID.

**Finding GL-24 (positive):** Provenance is well-preserved in the data layer. Each record carries its arena, platform, collection run, and tier. The Phase A export improvements ensure these fields are included in CSV/XLSX exports. The researcher can always determine which arena and collection run produced each record. This is a strength for the Greenland scenario where cross-arena comparison requires knowing the source of each data point.

---

### Step 13: Admin Credentials for Fringe Platforms

**Researcher action:** Navigate to Admin > API Keys to configure credentials for fringe monitoring platforms.

**Assessment:**

The credentials dropdown (`admin/credentials.html` lines 77-94) now includes:
YouTube, Telegram, TikTok, Serper.dev, SerpAPI, TwitterAPI.io, Bluesky, Reddit, Gab, Threads, Facebook (Bright Data), Instagram (Bright Data), Event Registry, Majestic, GDELT (no key needed), RSS Feeds (no key needed).

**Finding GL-B03 (BLOCKER -- Missing credential platforms for fringe monitoring):** The credentials dropdown is missing several platforms that have registered collectors:
- **Discord** -- collector exists, requires `bot_token`, not in dropdown
- **Twitch** -- collector exists, requires `client_id` + `client_secret`, not in dropdown
- **Wikipedia** -- collector exists (unauthenticated, no credential needed, but should still appear for clarity)
- **VKontakte** -- deferred, no credential needed until legal review
- **OpenRouter** (AI Chat Search) -- collector exists, requires API key, not in dropdown

For the Greenland scenario, the absence of Discord from the credential dropdown means the researcher cannot provision a bot token, making the entire Discord arena unreachable. This is part of the GL-B02 blocker. [frontend]

---

## Passed

### GL-P01: Phase 0 stale text removed from dashboard and health page
No "Phase 0" or "Google Search arena active" text found in any template. The researcher no longer sees contradictory information about the application's capabilities.

### GL-P02: Celery Beat jargon removed from live mode description
No "Celery Beat" string found in any template. The live mode uses researcher-friendly language.

### GL-P03: Term type help text added to query design editor
The editor includes a help box explaining Keyword, Phrase, Hashtag, and URL pattern types (editor.html lines 257-262).

### GL-P04: Term grouping feature added to query design editor
Terms can be organized into named groups with visual headers. Datalist suggestions include "Primary terms", "Discourse associations", "Actor discovery terms", "English variants", "Related concepts." Group headers are clickable for inline renaming.

### GL-P05: Term count label language corrected
"X terms" instead of "X termer" -- consistent English throughout the UI.

### GL-P06: Arena descriptions displayed in configuration grid
Each arena row shows a one-line description from `ARENA_DESCRIPTIONS`, truncated with hover tooltip for full text.

### GL-P07: Arena tier validation implemented
Unsupported tiers are greyed out with `cursor-not-allowed opacity-40` and a tooltip explaining which tiers are supported. Researchers cannot accidentally select an unsupported tier.

### GL-P08: Arena credential status indicator added
Green/gray dots on each arena row show whether API credentials are configured, with hover text explaining the implication.

### GL-P09: Arena config save confirmation added
A "Saved" success message appears briefly after saving arena configuration, with a "Save failed" error fallback.

### GL-P10: Actor synchronization between query design and Actor Directory
Adding an actor to a query design now creates/links a canonical Actor record in the Actor Directory via case-insensitive lookup. The "Profile" link appears on successfully synced actors.

### GL-P11: Collection detail shows query design name and search terms
The collection detail page header shows the query design name when available, and search terms are displayed as styled badges.

### GL-P12: Analysis filter bar uses dropdown selectors
Platform and Arena filters are now `<select>` dropdowns populated from the API, replacing the previous free-text inputs.

### GL-P13: Export column headers are human-readable
CSV/XLSX exports now use labels like "Platform", "Author", "Matched Search Terms" instead of snake_case column names.

### GL-P14: Export includes collection_run_id and query_design_id
The flat export columns include provenance metadata for organizing multiple exports.

### GL-P15: Duplicate exclusion always applied in analysis
The `_filters.py` module ensures `(raw_metadata->>'duplicate_of') IS NULL` is always present in analysis queries.

### GL-P16: Reddit subreddit list expanded
Now includes `dkfinance`, `dkpolitik`, `scandinavia`, and `NORDVANSEN` alongside the original 4, providing broader coverage for Danish political discourse.

### GL-P17: Gab added to credentials dropdown
The admin credentials form includes Gab, allowing the researcher to provision credentials for fringe monitoring.

### GL-P18: Arena registry keyed by platform_name (backend)
The registry singleton is now keyed by `platform_name` (unique per collector) rather than `arena_name` (shared grouping label). All 24 collectors are registered without backend collisions.

---

## Friction Points

### GL-01: Language selector forces single language for bilingual/multilingual topics
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 154-158
No multilingual option available. The Greenland topic requires both Danish and English tracking. [frontend], [core]

### GL-02: Term grouping feature has low discoverability
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 240-253
The "Group (optional)" input is styled very muted and may be missed during rapid term entry. [frontend]

### GL-03: Term group renaming is client-side only and not persisted
File: `src/issue_observatory/api/templates/query_designs/editor.html`, lines 910-922
Group renames are lost on page refresh. No server-side persistence endpoint exists. [frontend], [core]

### GL-04: Actor type badge rendering still uses British spelling "organisation"
File: `src/issue_observatory/api/templates/query_designs/editor.html`, line 351
Actors typed as "organization", "government_body", "political_party", "think_tank", "ngo" all render with a generic gray "Account" badge instead of type-specific colors. [frontend]

### GL-05: Actor type taxonomy lacks "State/Territory government" for Greenlandic entities
The "Government body" type conflates Danish ministries with Greenland's self-governing Naalakkersuisut. Minor taxonomic limitation. [research]

### GL-06: Telegram channel discovery is entirely manual and undocumented
File: `src/issue_observatory/arenas/telegram/config.py`, lines 54-61
Default channel list is mainstream news only. No UI for adding political/geopolitical channels. [frontend], [research]

### GL-07: Telegram has no language filter and this is not disclosed to the researcher
File: `src/issue_observatory/arenas/telegram/collector.py`, line 33
All messages from configured channels are collected regardless of language. No UI warning. [research]

### GL-08: Twitch arena is a stub but appears as a functional arena in the grid
File: `src/issue_observatory/arenas/twitch/collector.py`, lines 1-30
Returns channel metadata only, not chat messages. The researcher has no indication the arena is a stub. [frontend], [research]

### GL-09: Reddit subreddits are code-level configuration only
File: `src/issue_observatory/arenas/reddit/config.py`, lines 72-93
The researcher cannot add `r/Greenland` or `r/geopolitics` through the UI. [research], [core]

### GL-10: Common Crawl and Wayback return metadata only, not page content
Files: `src/issue_observatory/arenas/web/common_crawl/collector.py`, lines 8-10; `src/issue_observatory/arenas/web/wayback/collector.py`, lines 8-10
Arena descriptions do not warn that only URL index entries (not content) are returned. [research], [data]

### GL-11: Majestic is premium-only with no cost disclosure in the grid
File: `src/issue_observatory/arenas/majestic/collector.py`, line 8
The arena description says "(premium)" but does not mention the $399.99/month API cost. [research]

### GL-12: Wikipedia seed articles are empty and code-level configuration only
File: `src/issue_observatory/config/danish_defaults.py`, line 299
`DANISH_WIKIPEDIA_SEED_ARTICLES = []` -- no UI for specifying articles to monitor. [research], [core]

### GL-13: AI Chat Search is medium/premium only and blocked by frontend arena grid issue
The arena cannot be accessed even at medium tier due to GL-B01. [research]

### GL-14: VKontakte is deferred but appears in the arena grid with no clear UI warning
File: `src/issue_observatory/arenas/vkontakte/collector.py`, lines 72-76
All collection methods raise an error about legal review. No visual indication in the grid. [frontend], [research]

### GL-15: Content browser arena filter checkboxes are hardcoded to 11 arenas
File: `src/issue_observatory/api/templates/content/browser.html`, lines 61-73
Records from Discord, Wikipedia, Common Crawl, Wayback, etc. have no filter checkbox. [frontend]

### GL-16: No mechanism for comparing mainstream vs. fringe discourse side by side
The content browser supports single-arena filtering but not comparative views. [frontend], [research]

### GL-17: Arena column hidden below xl breakpoint (persists from FP-21)
File: `src/issue_observatory/api/templates/content/browser.html`
On standard laptop screens, the researcher cannot see which arena a record came from. [frontend]

### GL-18: Actor sync creates Actor records but not platform presences
File: `src/issue_observatory/api/routes/query_designs.py`, lines 890-920
The researcher must manually add platform handles for every actor on every platform. [frontend], [core]

### GL-19: Snowball sampling may not support fringe platform discovery
Platform-specific network traversal requirements limit sampling to platforms with follow/reply structures. [research]

### GL-20: GEXF term network does not include term group labels as node attributes
File: `src/issue_observatory/analysis/export.py`
The researcher's 6 thematic term groups are not preserved in the network export. [data], [research]

### GL-21: No per-arena GEXF export (persists from IM-39)
The researcher cannot compare network structures between mainstream and fringe arenas. [research]

### GL-22: Content browser does not show Content Type as a column or badge
File: `src/issue_observatory/api/templates/content/browser.html`
Autocomplete suggestions, social posts, and news articles are visually indistinguishable in the table. [frontend]

### GL-23: Cross-arena data use is entirely manual with no shortcuts
Moving from "discover actor in Arena A" to "collect from Arena B" requires 5+ navigation steps. [frontend], [core]

---

## Blockers

### GL-B01: Arena configuration grid collapses platforms by arena_name, not platform_name

**File:** `src/issue_observatory/api/templates/query_designs/editor.html`, line 645

**Observation:** The frontend maps API response entries using `id: a.arena_name`. Since `arena_name` is a shared logical grouping label (not unique per collector), all 10 social media platforms receive `id: "social_media"`, both news media platforms receive `id: "news_media"`, and all 3 web platforms receive `id: "web"`. Alpine's `x-for` directive with `:key="arena.id"` cannot properly handle duplicate keys. The result is that the researcher sees at most one row per `arena_name` group instead of one row per platform.

The backend registry was correctly fixed (keyed by `platform_name`), and the `/api/arenas/` endpoint returns all 24 collectors with unique `platform_name` values. But the frontend collapses them back into a handful of rows.

**Research impact:** The researcher cannot independently enable, disable, or configure tiers for Reddit, Telegram, Discord, TikTok, Gab, Twitch, X/Twitter, Threads, YouTube, Facebook, or Instagram. All social media platforms share a single toggle. This completely blocks the scenario's requirement to "cast the net widely across Telegram, Reddit, Discord, TikTok, Twitch" with platform-specific configuration.

**Fix:** Change line 645 from `id: a.arena_name` to `id: a.platform_name`. Update `_arenaLabel()` to accept `platform_name` values. Update the saved config endpoint to store/retrieve by `platform_name`.

### GL-B02: Discord arena requires channel IDs and bot token but has no UI support

**Files:** `src/issue_observatory/arenas/discord/collector.py`, lines 159-166; `src/issue_observatory/api/templates/admin/credentials.html`, lines 77-94

**Observation:** The Discord collector requires explicit `channel_ids` (there is no global search for bots), and a bot token must be provisioned. Neither requirement has UI support: (a) the credentials dropdown does not include Discord; (b) there is no field anywhere in the query design or collection launcher for specifying Discord channel snowflake IDs.

**Research impact:** Discord is completely unreachable through the research workflow. The researcher who wants to monitor Danish political Discord servers for Greenland discourse cannot configure credentials, specify channels, or trigger collection.

### GL-B03: Credentials dropdown missing Discord, Twitch, and OpenRouter

**File:** `src/issue_observatory/api/templates/admin/credentials.html`, lines 77-94

**Observation:** Three platform collectors that require credentials are not listed in the admin credentials dropdown: Discord (bot_token), Twitch (client_id + client_secret), and OpenRouter/AI Chat Search (api_key). Without credential provisioning, these arenas cannot collect data.

**Research impact:** Three arenas with implemented collectors are unreachable because credentials cannot be provisioned through the UI. This affects the Greenland scenario's fringe monitoring (Discord), live stream monitoring (Twitch), and AI framing analysis (AI Chat Search).

---

## Data Quality Findings

### GL-DQ-01: GDELT dual-query deduplication for Greenland

**Source:** `src/issue_observatory/config/danish_defaults.py`, lines 207-217

**Observation:** GDELT uses `sourcelang=danish` and `sourcecountry=DA` as separate queries, deduplicated by URL. For the Greenland topic, English-language articles from US/UK media about Greenland would match `sourcecountry=DA` only if they are coded by GDELT as having a Danish source. Articles from non-Danish English-language media about Greenland may be missed entirely because they match neither filter. Meanwhile, Danish-language articles about Greenland from Danish media would match both filters and be deduplicated.

**Research impact:** International English-language coverage of the Greenland issue (Trump statements, US policy discussions, Arctic security analyses) may be underrepresented in GDELT results. The researcher should supplement with Google Search using English terms to capture international coverage.

### GL-DQ-02: RSS feed coverage for Greenland -- no Greenlandic media

**Source:** `src/issue_observatory/config/danish_defaults.py`, lines 47-156

**Observation:** The curated RSS feed list includes 35+ Danish news outlets but zero Greenlandic media outlets. Sermitsiaq (the main Greenlandic newspaper), KNR (Greenlandic broadcasting), and AG (Atuagagdliutit/Gronlandsposten) are not included. For a study centered on Greenland, the absence of Greenlandic media RSS feeds is a significant gap.

**Research impact:** The researcher's RSS-based news analysis would capture how Danish media frames Greenland, but not how Greenlandic media frames its own situation. This is a fundamental coverage gap for a sovereignty/self-determination study. The researcher should be warned about this limitation.

### GL-DQ-03: Bluesky Danish language filter may exclude Greenlandic posts in Kalaallisut

**Source:** `src/issue_observatory/config/danish_defaults.py`, line 223

**Observation:** The Bluesky filter uses `lang:da` (Danish). Kalaallisut (Greenlandic, ISO 639-1: `kl`) is a distinct language from Danish. Posts written in Kalaallisut about Greenlandic politics would be filtered OUT by the `lang:da` filter. If Greenlandic politicians or community members post in Kalaallisut on Bluesky, this content would be invisible to the collector.

**Research impact:** The Danish language filter systematically excludes Greenlandic-language discourse. For a study about Greenlandic self-determination, this is a methodological bias that the researcher must document: the data captures the Danish perspective on Greenland but not the Greenlandic perspective in their own language.

### GL-DQ-04: Google Autocomplete reveals public search associations for Greenland

**Source:** `src/issue_observatory/config/danish_defaults.py`, lines 192-201

**Observation (positive):** Google Autocomplete with `gl=dk`, `hl=da` will reveal what Danish Google users associate with "Gronland" -- e.g., "Gronland selvstaendighed", "Gronland Trump", "Gronland olie", "Gronland vejr". These autocomplete suggestions are a valuable data source for mapping the public imagination around the Greenland issue.

### GL-DQ-05: Term co-occurrence network would reveal geopolitical discourse clusters

**Observation (positive):** With 23 search terms across 6 thematic dimensions, the term co-occurrence GEXF would reveal which geopolitical framings cluster together. If "Trump Greenland" frequently co-occurs with "arktisk sikkerhed" but rarely with "kolonihistorie", this reveals a geopolitical security framing rather than a postcolonial framing. The methodological structure is sound for this analysis.

---

## Recommendations

### Priority 1 -- Critical for the Greenland scenario

**R-01** [frontend] -- Fix the arena configuration grid to use `platform_name` instead of `arena_name` as the row `id`. Change line 645 of `editor.html` from `id: a.arena_name` to `id: a.platform_name`. Update `_arenaLabel()` to include labels for all 24 platform names. Update the saved config endpoint to store/retrieve by `platform_name`. This single fix unblocks access to all 24 platforms. [Addresses GL-B01]

**R-02** [frontend] -- Add Discord, Twitch, and OpenRouter to the admin credentials dropdown. This unblocks credential provisioning for three implemented arenas. [Addresses GL-B03]

**R-03** [frontend], [core] -- Add a mechanism for specifying platform-specific collection parameters (Telegram channel usernames, Discord channel IDs, Reddit subreddits) through the query design or collection launcher UI. Currently, these are code-level configurations only. A "Platform-specific settings" section per arena in the query design editor would allow the researcher to enter channel/subreddit lists. [Addresses GL-06, GL-09, GL-B02]

### Priority 2 -- High value for fringe monitoring research

**R-04** [frontend] -- Make the content browser arena filter checkboxes dynamic, fetched from the server's arena registry (like the arena config grid). This ensures records from all platforms can be filtered individually. [Addresses GL-15]

**R-05** [frontend] -- Fix the actor type badge rendering in `editor.html` line 351 to use the American spelling `"organization"` matching the `ActorType` enum. Add badge styles for all 11 actor types (political_party, government_body, think_tank, ngo, educational_institution, teachers_union, company, unknown). [Addresses GL-04]

**R-06** [research] -- Add Greenlandic media RSS feeds to `danish_defaults.py`: Sermitsiaq (sermitsiaq.ag), KNR (knr.gl), AG/Gronlandsposten. This is essential for any Greenland-focused study. [Addresses GL-DQ-02]

**R-07** [frontend] -- Add visual indicators for deferred/stub arenas in the grid. VKontakte should show a "Deferred -- pending legal review" badge. Twitch should show a "Discovery only -- live chat requires streaming worker" badge. [Addresses GL-08, GL-14]

**R-08** [data], [research] -- Include term `group_label` as a node attribute in the term co-occurrence and bipartite GEXF exports. This preserves the researcher's analytical structure in Gephi. [Addresses GL-20]

### Priority 3 -- Enhancements for multi-platform discourse research

**R-09** [frontend], [core] -- Add multilingual query design support (e.g., "Danish + English" or "All languages"). The language selector should allow multiple selections. [Addresses GL-01]

**R-10** [frontend] -- Add a "Content Type" column or badge to the content browser table rows, or at minimum add Content Type to the arena filter checkboxes. [Addresses GL-22]

**R-11** [research] -- Add per-arena GEXF export to the analysis dashboard. Allow the researcher to filter network exports by arena for cross-platform comparison. [Addresses GL-21]

**R-12** [frontend], [core] -- Persist term group renames to the server. Implement a `PATCH /query-designs/{id}/terms/{term_id}/group` endpoint. [Addresses GL-03]

**R-13** [research] -- Document Common Crawl and Wayback limitations prominently in the arena descriptions. Change "Common Crawl open web archive -- petabyte-scale crawl dataset (free)" to "Common Crawl web archive index -- URL metadata from petabyte-scale crawl (content requires separate WARC retrieval, not yet available)." [Addresses GL-10]

**R-14** [research] -- Add Kalaallisut (kl) to the language dropdown in the query design editor and as a Bluesky filter option. For Greenland research, this is an essential language. [Addresses GL-DQ-03]

---

## Phase A Fix Verification Summary

The following table summarizes which Phase A fixes have been verified as effective for the Greenland scenario:

| Phase A Fix | Finding ID | Status | Notes |
|-------------|-----------|--------|-------|
| IP2-001: Dynamic arena grid | GL-B01 | PARTIAL -- backend fixed, frontend broken | Registry keyed by `platform_name` (correct), but frontend uses `arena_name` as row ID (incorrect) |
| IP2-002: Arena tier validation | GL-P07 | VERIFIED | Unsupported tiers greyed out with tooltip |
| IP2-003: Arena descriptions | GL-P06 | VERIFIED | Descriptions shown below arena names |
| IP2-004: Duplicate exclusion | GL-P15 | VERIFIED | Always-on predicate in `_filters.py` |
| IP2-006: Human-readable export headers | GL-P13 | VERIFIED | `_COLUMN_HEADERS` with readable labels |
| IP2-007: Actor synchronization | GL-P10 | VERIFIED | `_find_or_create_actor()` works correctly |
| IP2-009: Altinget RSS | -- | NOT TESTABLE | URL verification requires live network |
| IP2-012: Analysis filter dropdowns | GL-P12 | VERIFIED | Platform/Arena are now `<select>` elements |
| IP2-018: Collections detail page | GL-P11 | VERIFIED | Query design name and search terms shown |
| C-1: Test regressions | -- | NOT VERIFIED | Test execution requires Docker environment |
| C-3: Actor type default "account" | -- | PARTIALLY VERIFIED | Backend fix not directly verifiable via template analysis |
| C-4: Badge spelling "organisation" | GL-04 | NOT FIXED in template | Template still checks for British spelling |
| FP-01/FP-02: Stale Phase 0 text | GL-P01 | VERIFIED | Removed from all templates |
| FP-05: Mixed "termer" language | GL-P05 | VERIFIED | Corrected to English "terms" |
| FP-14: No save confirmation | GL-P09 | VERIFIED | "Saved" message with auto-dismiss |
| FP-16: Celery Beat jargon | GL-P02 | VERIFIED | Removed from templates |

---

## Overall Assessment

### Can a Danish politics/geopolitics researcher map Greenland discourse across mainstream and fringe platforms using this application?

**No -- not without developer intervention for the fringe platform dimension. The mainstream dimension works with caveats.**

The Phase A fixes have significantly improved the core research workflow. The dynamic arena grid, tier validation, arena descriptions, actor synchronization, human-readable exports, analysis filter dropdowns, and duplicate exclusion represent meaningful progress toward a usable research tool.

However, the Greenland scenario reveals a fundamental mismatch between the application's current capabilities and the requirements of cross-platform fringe monitoring research:

1. **The arena grid frontend bug (GL-B01)** collapses all social media platforms into a single row, making platform-specific configuration impossible. This single issue blocks the entire fringe monitoring dimension.

2. **Three arenas lack credential support (GL-B03)**: Discord, Twitch, and AI Chat Search cannot be provisioned through the UI.

3. **Platform-specific configuration is code-level only**: Telegram channels, Discord servers, Reddit subreddits, and Wikipedia articles cannot be specified through the research workflow.

4. **No Greenlandic media sources are included**: RSS feeds cover Danish media but not Greenlandic media (Sermitsiaq, KNR), and the Bluesky language filter excludes Kalaallisut content.

### What the researcher CAN do at free/medium tier

- Collect from Google Search, Google Autocomplete, Bluesky, RSS Feeds, GDELT, Ritzau, and (if the grid is fixed) Reddit, YouTube, Gab individually
- Use 23 search terms organized into 6 thematic groups
- Track 8 named actors with automatic Actor Directory synchronization
- Generate term co-occurrence and bipartite GEXF networks for discourse association analysis
- Export data with human-readable headers and provenance metadata
- Filter content by arena, date, language, and matched search term

### What the researcher CANNOT do without developer intervention

- Configure individual social media platforms (blocked by GL-B01)
- Monitor Discord servers for Greenland discourse (blocked by GL-B02, GL-B03)
- Monitor Twitch streams (blocked by stub collector + GL-B03)
- Add Telegram channels for political/geopolitical monitoring (no UI)
- Add Reddit subreddits like r/Greenland (no UI)
- Include Greenlandic media RSS feeds (not configured)
- Use AI Chat Search for LLM framing analysis (no credentials UI)
- Generate per-arena GEXF networks for mainstream vs. fringe comparison

### Severity Rating

| Dimension | Rating | Notes |
|-----------|--------|-------|
| Discoverability | Good | Phase A improvements (descriptions, credential dots, term grouping) significantly help |
| Comprehensibility | Good | Term type help text, tier validation tooltips, and human-readable exports are clear |
| Completeness | Poor | Arena grid bug blocks platform-specific configuration; fringe platforms lack UI support |
| Data Trust | Moderate | Provenance is well-preserved; deduplication is automatic; but Greenlandic media and Kalaallisut gaps affect coverage |
| Recovery | Good | Error handling and credential status indicators are appropriate |

### Comparison to Previous Reports

The Greenland scenario reveals problems that the CO2 afgift and AI-og-uddannelse scenarios could not expose:

1. **Arena grid frontend bug is NEW**: The Phase A fix for IP2-001 introduced a frontend regression that was not testable in the previous code-based analyses (which examined the hardcoded list). The dynamic grid is worse than the hardcoded list because it collapses platforms that were previously distinct.

2. **Fringe platform support gaps are NEW**: Previous scenarios focused on mainstream arenas. The Greenland scenario's explicit fringe monitoring requirement exposes Discord, Twitch, and VKontakte as implemented-but-unreachable arenas.

3. **Platform-specific configuration is NEW**: Previous scenarios accepted default configurations. The Greenland scenario requires researcher-curated channel lists for Telegram and Discord, which is not possible through the UI.

4. **Greenlandic media and language gaps are NEW**: Previous scenarios focused on Danish-language discourse. The Greenland scenario reveals that the Danish focus systematically excludes Greenlandic perspectives -- a methodological bias specific to this topic.

### Readiness Verdict

The application is **ready for pilot-stage mainstream discourse tracking** on Greenland at free tier, covering Google, Bluesky, RSS Feeds, GDELT, and Ritzau -- provided the arena grid frontend bug (GL-B01) is fixed first.

The application is **not ready for fringe monitoring or cross-platform conspiracy tracking** until:
1. GL-B01 is fixed (arena grid uses `platform_name`)
2. GL-B02 is addressed (Discord credential and channel configuration)
3. GL-B03 is addressed (credentials dropdown includes all platforms)
4. Platform-specific configuration is surfaced in the UI (R-03)

The most impactful single fix is **R-01** (change `id: a.arena_name` to `id: a.platform_name` in line 645 of editor.html), which would immediately unblock access to all 24 registered platforms in the arena configuration grid.
