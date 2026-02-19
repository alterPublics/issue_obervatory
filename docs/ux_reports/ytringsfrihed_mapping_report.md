# UX Test Report -- "Ytringsfrihed" (Freedom of Speech) Discourse Mapping

Date: 2026-02-19
Scenario: Mapping Danish public discourse around "ytringsfrihed" (freedom of speech), including sub-themes of censorship, hate speech regulation, and the tension between democratic free expression and protection of vulnerable groups
Arenas examined: All 20 mounted arena routers (google_search, google_autocomplete, bluesky, reddit, youtube, rss_feeds, gdelt, telegram, tiktok, ritzau_via, gab, event_registry, x_twitter, threads, common_crawl, wayback, majestic, facebook, instagram, ai_chat_search), plus the web scraper enrichment service
Tiers examined: free, medium, premium (conceptual walkthrough based on tier configuration)
Evaluation method: Code-based static analysis of all routes, templates, collectors, configuration, arena registry, schemas, and data flow -- simulating every step a Danish discourse researcher would take to map the "ytringsfrihed" issue across mainstream and fringe platforms

---

## Executive Summary

The Issue Observatory provides a genuinely ambitious and architecturally sound platform for multi-arena discourse research. For the "ytringsfrihed" scenario -- a topic that spans parliamentary debate, legacy media editorial pages, social media flame wars, and fringe-platform extremism -- the application offers an impressively broad set of data collection pathways. The query design system, arena configuration grid, actor management pipeline, snowball sampling, cross-platform link discovery, content browser with full-text Danish search, and multi-format export (including GEXF network graphs) represent a feature set that, when fully functional, would genuinely serve a discourse researcher's needs.

However, the evaluation reveals a consistent pattern: **individual features are well-designed, but the cross-arena discovery workflow that a "ytringsfrihed" researcher needs most -- the iterative cycle of search, discover, expand, refine -- has friction points at every transition**. The researcher can create a query design, add terms, configure arenas, and launch a collection. But the progressive discovery workflow (use Google results to seed RSS monitoring, use content mentions to discover Telegram channels, use snowball sampling to expand actor networks) requires the researcher to mentally coordinate between disconnected interface sections, manually transfer identifiers between arenas, and rely on API calls for operations that should be one-click in the UI.

**Key findings:**

1. **Strengths**: Danish locale is deeply integrated. The arena coverage is exceptional for a research tool. The actor management system (quick-add, snowball sampling, entity resolution, merge/split) is sophisticated. Export formats include GEXF for Gephi, RIS for reference managers, and Parquet for data scientists. The content browser supports Danish full-text search with proper stemming.

2. **Critical gap**: There is no "discovery dashboard" or "exploration mode" that lets a researcher start with a vague question ("how is ytringsfrihed discussed in Denmark?") and progressively build their collection strategy through guided steps. The application assumes the researcher already knows what terms, actors, and arenas to configure -- it is a collection execution engine, not a discovery assistant.

3. **Cross-arena workflow breaks**: Moving from "I found an interesting actor in Google Search results" to "now I want to track them on Bluesky and Telegram" requires navigating to the Actor management section, manually creating the actor, adding platform presences, then returning to the query design to add them to the actor list. This multi-step transfer is where researchers will lose patience.

4. **Cost model is clear but incomplete**: The free/medium/premium tier system is well-designed for cost consciousness. The pre-flight credit estimate endpoint exists but returns zero (stub). A researcher cannot evaluate cost trade-offs without real estimates.

---

## Research Scenario: "Ytringsfrihed" in Danish Public Discourse

### Research Question

How is "ytringsfrihed" (freedom of speech) constituted as a public issue in Danish discourse? What sub-framings exist (democratic principle, hate speech regulation, platform moderation, cultural sensitivity, religious expression)? Who are the key actors across mainstream and fringe platforms? Where do the most polarized positions emerge?

### Search Term Strategy

The "ytringsfrihed" issue is ideal for testing the application because:

1. **Deeply contested**: Unlike a policy topic with a clear pro/anti divide, freedom of speech in Denmark involves multiple overlapping positions -- free-speech absolutists, hate-speech regulators, cultural conservatives, progressive activists, legal scholars, and platform governance advocates. The term network should be complex.

2. **Cross-platform distribution**: This topic appears differently on each platform. News media covers legal cases and parliamentary debates. Bluesky and X have heated direct exchanges. Reddit has longer analytical threads. Telegram and Gab may host more extreme positions. Google Autocomplete reveals what the public associates with the term. YouTube has debate videos and panel discussions.

3. **Danish-specific complexity**: Denmark has a strong tradition of free speech (Grundlovens paragraf 77) but also racism/blasphemy laws (historically), recent hate speech prosecutions, the Muhammad cartoons legacy, and ongoing debates about online platform moderation. The search terms require both Danish legal/political vocabulary and broader cultural terms.

4. **Actor diversity**: Actors include politicians (multiple parties), media commentators, civil liberties organizations (PEN Danmark, Justitia), anti-hate-speech organizations (Institut for Menneskerettigheder), individual public figures involved in free speech cases, and anonymous social media voices.

### Proposed Search Terms

| Term | Type | Group | Rationale |
|------|------|-------|-----------|
| ytringsfrihed | keyword | Core | The primary Danish term |
| ytringsret | keyword | Core | Alternative legal framing (right of expression) |
| censur | keyword | Core | Censorship -- the anti-ytringsfrihed frame |
| hadtale | keyword | Regulation | Hate speech -- Danish term |
| hate speech | phrase | Regulation | English equivalent, appears in Danish discourse |
| straffelovens 266 b | phrase | Legal | The specific Danish hate speech statute |
| racismeparagraffen | keyword | Legal | Colloquial name for 266b |
| Grundlovens paragraf 77 | phrase | Legal | Constitutional free speech provision |
| ytringsfrihedskommissionen | keyword | Legal | The Freedom of Expression Commission |
| platformregulering | keyword | Tech | Platform moderation framing |
| online censur | phrase | Tech | Online censorship framing |
| deplatformering | keyword | Tech | Deplatforming -- removal from platforms |
| Muhammedtegningerne | keyword | Cultural | The cartoon crisis -- foundational Danish free speech event |
| blasfemiparagraffen | keyword | Cultural | Blasphemy law (repealed 2017, still referenced) |
| PEN Danmark | phrase | Actor | Civil liberties organization |
| Justitia | keyword | Actor | Liberal think tank focused on rule of law |
| #ytringsfrihed | hashtag | Social | Primary hashtag |
| #censur | hashtag | Social | Censorship hashtag |

**Total: 18 search terms across 5 thematic groups.** This represents a moderately complex query design -- fewer terms than the Greenland scenario (23) but with more thematic depth in a single national issue.

---

## Step-by-Step Walkthrough

### Step 1: First Contact -- Dashboard and Orientation

**Researcher action:** A Danish discourse researcher opens the Issue Observatory for the first time, intending to map "ytringsfrihed" across as many platforms as possible.

**What the researcher encounters:**

The root URL (`/`) redirects to `/dashboard`. The dashboard template (`src/issue_observatory/api/templates/dashboard/index.html`) presents:

- A page header: "Dashboard" with "Welcome, [user name]"
- Three summary cards: Credits, Active Collections, Records Collected
- Quick Actions: "New Query Design" and "New Collection" buttons prominently placed
- The left sidebar navigation: Dashboard, Query Designs, Collections, Content, Actors, Analysis -- plus an Administration section

**Assessment:**

The six-item navigation maps well to a research workflow: design your query, collect data, browse content, manage actors, analyse results. A discourse researcher would intuitively understand this progression.

However, the dashboard provides no guidance on WHERE TO START for a new research project. A researcher who wants to explore "ytringsfrihed" but doesn't yet know which arenas will be productive has no "exploration" or "discovery" entry point. The application assumes the researcher will immediately create a query design -- but for an exploratory topic, the researcher first needs to understand what the application can collect and from where.

**Finding FP-01 (friction point):** The dashboard lacks an "arena overview" or "what can I collect?" section that would help a first-time researcher understand the platform's capabilities before committing to a query design. The arena metadata endpoint (`GET /api/arenas/`) exists and returns rich information (arena_name, platform_name, supported_tiers, description, has_credentials), but this information is only surfaced in the query design editor's arena configuration grid -- not on the dashboard or in any introductory context. A researcher studying "ytringsfrihed" needs to know upfront that Telegram requires pre-curated channel names, that Gab exists as an arena (relevant for free-speech extremism), and that GDELT has a 3-month lookback window. [frontend]

**Finding FP-02 (friction point):** There is no "explore before you commit" mode. A researcher cannot try a quick Google Autocomplete query for "ytringsfrihed" to see what associations exist before creating a formal query design. The arena routers all have standalone `/collect` endpoints (`POST /arenas/google-autocomplete/collect`, `POST /arenas/bluesky/collect/terms`, etc.), but these are API-only -- there is no UI for ad-hoc exploration. This is a significant gap for the discovery-first workflow that discourse research requires. [frontend]

### Step 2: Creating the Query Design -- "Ytringsfrihed DK 2026"

**Researcher action:** Click "New Query Design" from the dashboard.

**What the researcher encounters:**

The query design editor (`src/issue_observatory/api/templates/query_designs/editor.html`) presents:

1. **Basic Information section:**
   - Name (required) -- placeholder: "e.g. Climate debate DK 2024"
   - Description -- multi-line text area
   - Language (dropdown, defaults to "da" -- Danish)
   - Country (dropdown, defaults to "DK")
   - Default Tier (radio: free/medium/premium)
   - Visibility (private/shared)

2. **Search Terms panel** -- HTMX-powered add/remove with term type selection (keyword, phrase, hashtag, url_pattern) and optional group label

3. **Arena Configuration Grid** -- Alpine.js-powered per-arena enable/disable and tier selection

4. **Actor List panel** -- HTMX-powered add/remove with actor type selection (person, organization, media_outlet, unknown) and "Profile" link for each actor

**Assessment (Basic Information):**

The language default of "da" and country default of "DK" is exactly right. The researcher does not have to configure anything Danish-specific -- the system assumes Danish context by default (`src/issue_observatory/config/danish_defaults.py`). This is a genuine strength: the `DANISH_GOOGLE_PARAMS`, `DANISH_SUBREDDITS`, `GDELT_DANISH_FILTERS`, `BLUESKY_DANISH_FILTER`, and `YOUTUBE_DANISH_PARAMS` are all applied automatically.

The researcher types "Ytringsfrihed DK 2026" as the name and "Mapping freedom of speech discourse in Denmark, 2026" as the description. The default tier is set to "free" -- cost-conscious by default, which is appropriate.

**Assessment (Search Terms):**

The term addition interface accepts form-encoded data via HTMX: the researcher types a term, selects a type (keyword/phrase/hashtag), optionally assigns a group label, and clicks "Add." The term appears immediately in the list with a colored badge indicating its type. The group label feature (`group_label` -> `group_id` via UUID5 derivation from `design_id + normalized_label`) is clever -- it creates stable grouping without requiring the researcher to manage UUIDs.

However, adding 18 search terms one at a time is tedious. There is no bulk import, no paste-multiple-terms, no CSV upload.

**Finding FP-03 (friction point):** Search terms must be added one at a time through the HTMX form. For a researcher who has designed 18 terms in a spreadsheet (as any systematic researcher would), there is no way to bulk-import them. The API endpoint `POST /query-designs/{id}/terms` accepts a single term per request. The `POST /query-designs/` create endpoint does accept `search_terms` as an array in the JSON body, but this is not exposed through the editor UI -- it requires the researcher to use the API directly. This is a significant friction point for any query design with more than a handful of terms. [frontend]

**Finding FP-04 (design problem):** The group label field is a free-text input, meaning the researcher must type the group name identically for every term that should be in the same group (e.g., "Core" for ytringsfrihed, ytringsret, censur). A dropdown populated from existing group labels would reduce typo risk and speed up entry. The backend derives a stable `group_id` from the normalized label, which is good -- but the UI does not help the researcher use it consistently. [frontend]

**Assessment (Arena Configuration Grid):**

The arena grid is powered by Alpine.js and fetches the arena list from `GET /api/arenas/`. It shows each arena as a card with:
- Arena name and platform name
- Enable/disable toggle
- Tier selector (free/medium/premium radio buttons)
- Credential status badge (green checkmark if `has_credentials` is true)

For the "ytringsfrihed" scenario, the researcher would see all 20+ arenas and need to decide which to enable. This is where the researcher's domain knowledge meets the application's capabilities.

**Finding S-01 (strength):** The arena configuration grid with per-arena tier selection is well-designed. The credential status badge immediately tells the researcher which arenas they can actually use versus which require API keys they don't have. This prevents the frustrating experience of configuring an arena, launching a collection, and only then discovering it needs credentials.

**Finding FP-05 (friction point):** The arena descriptions returned by `GET /api/arenas/` are brief one-liners. For a "ytringsfrihed" researcher deciding whether to enable Gab (a platform known for hosting free-speech extremism -- highly relevant to this topic), the description alone does not convey why this arena matters. There is no link to the arena research briefs (`docs/arenas/gab.md`) or any contextual guidance about which arenas are most relevant for different types of research questions. A "recommended for your topic" feature based on the query design's search terms would be transformative but is not present. [frontend]

**Finding FP-06 (friction point):** The arena configuration grid stores its settings via `POST /query-designs/{id}/arena-config`, but the grid does not distinguish between arenas that support term-based collection (most arenas) and those that require researcher-curated source lists (Telegram channels, Discord servers, RSS custom feeds). For "ytringsfrihed," the researcher would enable Telegram expecting to search for the term -- but Telegram actually requires pre-specified channel names. This distinction is not visible in the arena grid. The `PATCH /query-designs/{id}/arena-config/{arena_name}` endpoint supports custom configuration (e.g., `{"custom_channels": ["channel_username"]}` for Telegram), but there is no UI for entering these custom values in the arena grid itself. The researcher must know to use the API directly. [frontend] [data]

### Step 3: Configuring Arenas for "Ytringsfrihed" Discovery

**Researcher action:** The researcher begins enabling arenas, starting with those most likely to yield results for a Danish free-speech topic.

**Arena-by-arena assessment:**

#### Google Autocomplete (FREE)
**Purpose for ytringsfrihed:** Discover what the Danish public associates with "ytringsfrihed" -- autocomplete suggestions reveal popular search framings.
**API:** `POST /arenas/google-autocomplete/collect` with terms, language `da`, country `dk`.
**Assessment:** Free, no credentials needed. Danish locale params applied automatically. This is the ideal starting point for exploration -- but only accessible via API, not the UI. The researcher would need to manually construct a POST request to get autocomplete suggestions before committing to a full query design. There is no "try it" button.

#### Google Search (MEDIUM)
**Purpose for ytringsfrihed:** Find which websites, organizations, and individuals Google surfaces when Danish users search for "ytringsfrihed." Results directly seed the actor list and website scraping list.
**API:** `POST /arenas/google-search/collect` with terms, tier "medium" (Serper.dev) or "premium" (SerpAPI).
**Assessment:** Requires paid credentials (Serper.dev or SerpAPI). The `free` tier returns empty results with an explanatory message -- this is correctly documented in the router code. The researcher must understand that Google Search is not free. The response includes normalized content records with URLs and titles that can inform which actors are prominent in the discourse.

**Finding FP-07 (friction point):** The Google Search arena's free tier returns empty results. This is correct (Google Search has no free API), but the error messaging should explicitly suggest that the researcher use Google Autocomplete (free) first for discovery, then switch to Google Search (medium) for actual content. The current implementation just returns count=0 with no guidance. [data]

#### RSS Feeds (FREE)
**Purpose for ytringsfrihed:** Monitor Danish news coverage of free speech issues. The `DANISH_RSS_FEEDS` dictionary in `danish_defaults.py` includes 30+ feeds from DR, TV2, Politiken, Berlingske, Information, Altinget, and others -- an excellent selection for a Danish discourse researcher.
**API:** `POST /arenas/rss-feeds/collect/terms` with search terms matched against titles and summaries.
**Assessment:** Free, no credentials needed. The feed list includes Altinget (policy journalism), Information (independent left-liberal), Kristeligt Dagblad (Christian/ethical perspective) -- all highly relevant for "ytringsfrihed" from different editorial positions. The researcher can also add custom feeds via `PATCH /query-designs/{id}/arena-config/rss` with `{"custom_feeds": ["https://..."]}`.

**Finding S-02 (strength):** The curated `DANISH_RSS_FEEDS` list is comprehensive and well-documented. Each entry includes the outlet's editorial position and media group affiliation in code comments. For a "ytringsfrihed" researcher, the inclusion of Information (which frequently publishes opinion pieces on free speech) and Altinget (which covers the policy/legislative dimension) is excellent.

**Finding FP-08 (friction point):** The `GET /arenas/rss-feeds/feeds` endpoint lists all configured feeds, but the researcher has no way to filter or search the feed list from the UI. With 30+ feeds, the researcher cannot quickly identify which outlets have published anything about "ytringsfrihed" without collecting from all of them first. A "preview" or "test feed" feature would help. [frontend]

#### Bluesky (FREE)
**Purpose for ytringsfrihed:** Capture real-time social media debate. Bluesky is increasingly used by Danish journalists, academics, and commentators.
**API:** `POST /arenas/bluesky/collect/terms` with search terms, `POST /arenas/bluesky/collect/actors` with DIDs/handles.
**Assessment:** Free tier uses the public AT Protocol search API (no credentials needed). Danish language filter (`lang:da`) applied automatically. Both term-based and actor-based collection are supported. The `BlueskyCollector` supports Lucene query syntax, allowing complex queries like `"ytringsfrihed" OR "censur" lang:da`.

**Finding S-03 (strength):** Bluesky's free tier with no credential requirement is a genuine advantage for a cost-conscious researcher. The AT Protocol's public search is both free and reasonably capable. Combined with the automatic `lang:da` filter, this is one of the most accessible arenas for Danish discourse research.

#### Reddit (FREE)
**Purpose for ytringsfrihed:** Capture community discussion. The `DANISH_SUBREDDITS` list includes r/Denmark, r/danish, r/copenhagen, r/aarhus. Reddit discussions about "ytringsfrihed" tend to be more analytical and less polarized than on other platforms.
**API:** `POST /arenas/reddit/collect/terms` with search terms, optional `include_comments`.
**Assessment:** Free tier uses Reddit's public JSON API (no credentials needed). Custom subreddits can be added via `PATCH /query-designs/{id}/arena-config/reddit` with `{"custom_subreddits": ["SubredditName"]}`.

**Finding FP-09 (friction point):** The default `DANISH_SUBREDDITS` list is short (4 subreddits). For "ytringsfrihed," the researcher might want to monitor r/dkpolitik or other politically-focused Danish subreddits. The custom subreddit configuration exists but is API-only. The arena grid in the UI shows Reddit as enabled/disabled with a tier selector but provides no way to add custom subreddits. [frontend]

#### GDELT (FREE)
**Purpose for ytringsfrihed:** International news coverage of Danish free speech issues. GDELT machine-translates content, so both Danish and English search terms should be provided.
**API:** `POST /arenas/gdelt/collect` with terms, date range (3-month lookback limit).
**Assessment:** Free, no credentials needed. The GDELT router documentation correctly notes that callers should supply both Danish and English translations of search terms. Danish filters (`sourcelang: "danish"`, `sourcecountry: "DA"`) applied automatically.

**Finding FP-10 (design problem):** The GDELT router documentation says "Supply both Danish and English forms for best coverage," but the query design system has a single search term list shared across all arenas. There is no mechanism for arena-specific search terms. A researcher searching for "ytringsfrihed" (Danish) on GDELT should also search for "freedom of speech Denmark" (English), but adding both to the general search term list would contaminate the Bluesky and Reddit collections with irrelevant English-language results. This is a fundamental design limitation for any issue that has distinct Danish and English framings -- which includes most topics. [core] [research]

#### YouTube (MEDIUM)
**Purpose for ytringsfrihed:** Video content -- debates, interviews, panel discussions about free speech. YouTube is significant for Danish political discourse (party leaders frequently appear in YouTube-published debates).
**API:** `POST /arenas/youtube/collect/terms` with search terms, `POST /arenas/youtube/collect/actors` with channel IDs.
**Assessment:** Requires YouTube Data API v3 credentials (free quota available but limited). Danish params applied automatically (`relevanceLanguage: "da"`, `regionCode: "DK"`).

#### Telegram (MEDIUM)
**Purpose for ytringsfrihed:** Monitor extremist and alternative discourse channels. Telegram is where some Danish actors who feel "censored" on mainstream platforms migrate. Highly relevant for the "ytringsfrihed" topic.
**API:** `POST /arenas/telegram/collect` (structure inferred from router mount).
**Assessment:** Requires MTProto credentials. Critically, Telegram has no search API -- the researcher must specify channels to monitor. The custom channel configuration (`PATCH /query-designs/{id}/arena-config/telegram` with `{"custom_channels": [...]}`) exists but is not accessible from the UI.

**Finding BL-01 (blocker):** For the "ytringsfrihed" scenario, Telegram is arguably the most important fringe-platform arena. But there is no UI pathway for the researcher to specify Telegram channels. The researcher must: (1) discover channel names through other means (e.g., finding Telegram links in Google Search results or in content collected from other arenas), (2) navigate to the API documentation, (3) construct a PATCH request to the arena-config endpoint, (4) return to the collection launcher. This is a 4-step process that requires developer-level comfort with HTTP APIs. For a platform that is CRITICAL to studying "ytringsfrihed" (where actors who feel censored congregate), this is a functional blocker. [frontend] [core]

#### Gab (FREE/MEDIUM)
**Purpose for ytringsfrihed:** Monitor free-speech-absolutist platform. Gab is the canonical "free speech alternative" social network and is directly relevant to this topic.
**API:** `POST /arenas/gab/collect` with terms.
**Assessment:** The Gab arena exists and has a collector, tasks, and router. For "ytringsfrihed" research, Gab is unusually relevant -- it is a platform that was literally founded on a free-speech-maximalist ideology, and Danish users who feel their speech is restricted elsewhere may be present here.

**Finding S-04 (strength):** The inclusion of Gab as an arena shows genuine understanding of the research landscape for topics like "ytringsfrihed." Most research tools ignore fringe platforms. The Issue Observatory's coverage of Gab, Telegram, TikTok, and Threads alongside mainstream platforms reflects the reality that discourse flows between mainstream and fringe arenas.

#### Via Ritzau (FREE)
**Purpose for ytringsfrihed:** Danish press releases -- when organizations, politicians, or government bodies issue statements about free speech, they often go through Ritzau. The Via Ritzau API is free and unauthenticated.
**API:** `POST /arenas/ritzau-via/collect` with terms.
**Assessment:** Free, unauthenticated. Language filter defaults to Danish. This is a high-value arena for "ytringsfrihed" because official statements and press releases represent the institutional framing of the issue.

**Finding S-05 (strength):** Via Ritzau is a genuinely distinctive data source that most international research tools do not include. For a Danish researcher, press releases represent a crucial layer of institutional discourse that sits between news media and political speeches. Including it as a free arena is an excellent design choice.

#### TikTok (MEDIUM)
**Purpose for ytringsfrihed:** Short-video discourse. Younger Danish demographics may engage with free speech issues through TikTok formats.
**API:** `POST /arenas/tiktok/collect` with terms.
**Assessment:** Requires TikTok Research API credentials (academic access program). The medium tier reflects the API cost.

#### Event Registry (MEDIUM)
**Purpose for ytringsfrihed:** Structured news event data. Event Registry identifies "events" from news coverage and links articles to them -- useful for tracking how "ytringsfrihed" is framed across multiple news sources covering the same event.
**API:** `POST /arenas/event-registry/collect` with terms.
**Assessment:** Requires Event Registry API credentials. Paid service.

#### X/Twitter (MEDIUM/PREMIUM)
**Purpose for ytringsfrihed:** Twitter/X remains significant for Danish political commentary despite declining usage.
**API:** `POST /arenas/x-twitter/collect` with terms.
**Assessment:** Requires TwitterAPI.io (medium) or official X API (premium) credentials.

#### Facebook/Instagram (PREMIUM)
**Purpose for ytringsfrihed:** Facebook remains the largest Danish social platform. Free speech debates on Facebook groups (e.g., "Den Korte Avis" comment sections) are a major arena for this topic.
**API:** `POST /arenas/facebook/collect`, `POST /arenas/instagram/collect`.
**Assessment:** Requires Meta Content Library API access (premium only). This is the most significant accessibility barrier for Danish discourse research -- Facebook is by far the most used social platform in Denmark.

#### Common Crawl / Wayback (FREE)
**Purpose for ytringsfrihed:** Historical web content. Useful for finding think tank publications, academic analyses, and organizational position papers on free speech.
**API:** `POST /arenas/common-crawl/collect`, wayback via similar pattern.
**Assessment:** Free. Common Crawl uses CDX index queries; Wayback uses the Wayback Machine API. Both provide access to archived web content without requiring live scraping.

#### Majestic (PREMIUM)
**Purpose for ytringsfrihed:** Backlink analysis. Discover which websites link to key "ytringsfrihed" resources -- useful for mapping the web of organizations and commentators engaged in the debate.
**API:** `POST /arenas/majestic/collect`.
**Assessment:** Requires Majestic API credentials (premium).

#### AI Chat Search (MEDIUM)
**Purpose for ytringsfrihed:** Query AI models (via OpenRouter) about the issue to surface AI-mediated framings. Interesting for meta-research on how AI represents the "ytringsfrihed" debate.
**API:** `POST /arenas/ai-chat-search/collect`.
**Assessment:** Requires OpenRouter API credentials. The arena includes a `_query_expander.py` module that can expand search terms using AI -- this could be useful for generating additional search terms from a seed set.

**Finding S-06 (strength):** The AI Chat Search arena with its `_query_expander.py` module could serve as the "exploration assistant" that the application otherwise lacks (see FP-02). If exposed through the UI, a researcher could start with "ytringsfrihed" and ask the AI to suggest related Danish search terms, actors, and framings. This would address the discovery gap identified in Step 1.

#### Web Scraper (enrichment service)
**Purpose for ytringsfrihed:** Scrape specific URLs discovered through other arenas. For example, if Google Search reveals a Justitia report on free speech, the scraper can extract its full text.
**API:** `POST /scraping-jobs/` to create a job, SSE stream for progress, status polling.
**Assessment:** The scraper module (`src/issue_observatory/scraper/`) includes both HTTP (httpx) and Playwright (JS rendering) fetchers. Jobs are managed as first-class entities with their own CRUD API and SSE progress streaming. This is well-architected.

**Finding S-07 (strength):** The web scraper as a separate enrichment service is well-designed. It treats scraping jobs as managed entities with progress tracking, cancellation, and history. For a "ytringsfrihed" researcher who discovers important URLs in their collected data (e.g., links to legal analyses, think tank reports, or government documents), the scraper provides a clean path to enriching their corpus.

### Step 4: Adding Actors and Building the Initial Actor List

**Researcher action:** After configuring search terms and arenas, the researcher adds known actors to the query design.

For "ytringsfrihed," initial seed actors might include:

| Actor | Type | Relevance |
|-------|------|-----------|
| Flemming Rose | person | Editor who published Jyllands-Posten Muhammad cartoons |
| Inger Stojberg | person | Politician; free speech advocate; criminal prosecution |
| PEN Danmark | organization | Civil liberties organization focused on free speech |
| Justitia | organization | Liberal think tank; publishes ytringsfrihed indices |
| Institut for Menneskerettigheder | organization | Danish Institute for Human Rights; hate speech regulation |
| Jacob Mchangama | person | Justitia founder; prominent free speech scholar |
| Rosa Lund | person | SF politician; hate speech legislation advocate |
| Jyllands-Posten | media_outlet | Newspaper at center of cartoon crisis |

**What the researcher encounters:**

The Actor List panel in the query design editor accepts actor name and type via a form. Each submission calls `POST /query-designs/{id}/actors` which:
1. Finds or creates a canonical Actor record (case-insensitive name match)
2. Creates or finds the "Default" ActorList for this query design
3. Adds an ActorListMember linking the actor to the list
4. Returns an HTMX `<li>` fragment with the actor's name, type badge, and "Profile" link

**Assessment:**

The actor management workflow is well-thought-out. The find-or-create pattern means actors are deduplicated across query designs -- if "Jacob Mchangama" already exists from a previous project, it will be reused rather than duplicated. The "Profile" link leads to `/actors/{id}` where the researcher can view and manage platform presences.

**Finding FP-11 (friction point):** Like search terms, actors must be added one at a time. There is no bulk import. A researcher with a prepared list of 8-15 seed actors faces unnecessary repetition. The `POST /actors/quick-add-bulk` endpoint exists for the Content Browser flow, but it requires platform usernames -- not just canonical names. There is no bulk endpoint for simple name-and-type actor creation. [frontend]

**Finding FP-12 (design problem):** When adding "Jyllands-Posten" as a media_outlet actor, the researcher has no way to immediately specify its platform presences (Twitter handle, Bluesky handle, RSS feed URL, etc.). They must add the actor, click "Profile" to navigate to `/actors/{id}`, then add presences one by one via `POST /actors/{id}/presences`. This multi-page workflow interrupts the query design creation flow. [frontend]

### Step 5: Launching the Collection and Monitoring Progress

**Researcher action:** Navigate to Collections > New Collection. Select the "Ytringsfrihed DK 2026" query design, review arena configuration, and launch.

**What the researcher encounters:**

The collection launcher (`/collections/new`, template: `collections/launcher.html`) presents:
- Query design selector (dropdown of owned designs)
- Mode selector (batch with date range, or live tracking)
- Global tier selector (overridden by per-arena config from the query design)
- Pre-flight credit estimate panel (fetches from `POST /collections/estimate`)
- "Launch Collection" button

The launch creates a `CollectionRun` record via `POST /collections/` and redirects to the collection detail page (`/collections/{run_id}`), which uses SSE (`GET /collections/{run_id}/stream`) to show real-time progress per arena.

**Assessment:**

The SSE-based live monitoring is well-implemented. The `event_generator()` function in the collections router emits `task_update` events per arena (with status, records_collected, error_message, elapsed_seconds) and a `run_complete` event when finished. The 30-second keepalive prevents proxy timeouts. The initial snapshot emission means the page renders correctly even if loaded after some tasks have already completed.

**Finding FP-13 (friction point):** The pre-flight credit estimate endpoint (`POST /collections/estimate`) is a stub returning zero credits for all arenas. This means the researcher gets no cost information before launching. For a "ytringsfrihed" collection across 10+ arenas with both free and paid tiers, the researcher cannot evaluate cost trade-offs. They are flying blind. [core]

**Finding FP-14 (design problem):** The collection launcher uses a single global tier selector, but the query design already has per-arena tier configuration. The tier precedence logic (query design > launcher > global default) is documented in the code but not in the UI. A researcher who sets "free" globally but has "medium" configured for Google Search in their query design will not understand which takes precedence without reading the source code. [frontend]

### Step 6: Cross-Arena Discovery -- Using Results from One Arena to Seed Another

**Researcher action:** After the initial collection completes, the researcher wants to use the results to expand their collection. Specifically:
- Use Google Search results to discover relevant websites for scraping
- Use content mentions to find Telegram channels used by free speech actors
- Use Bluesky/Reddit actor names to seed snowball sampling
- Use the Discovered Sources feature to find cross-platform links

**6a. Content Browser and Full-Text Search:**

The content browser (`/content`, template: `content/browser.html`) supports:
- Full-text search using `to_tsvector('danish', ...)` with `plainto_tsquery`
- Platform/arena filters
- Date range filters
- Language filter
- Search term filter (from `search_terms_matched` array)
- Collection run filter
- Keyset cursor pagination (50 records per page, 2000 record cap)
- Export (CSV, XLSX, JSON, Parquet, GEXF, RIS, BibTeX)

**Finding S-08 (strength):** The Danish full-text search configuration is correctly implemented. The PostgreSQL `danish` text search config applies Danish stemming and stop words, meaning a search for "ytringsfrihedens" (genitive) will match records containing "ytringsfrihed." This is a genuine research-quality feature that many tools get wrong.

**Finding S-09 (strength):** The `search_terms_matched` array on each content record provides provenance -- the researcher can see which of their 18 search terms matched each record. This is essential for understanding which framings are associated with which content.

**6b. Discovered Sources (Cross-Platform Link Mining):**

The `GET /content/discovered-links` endpoint mines URLs from collected content text, classifies them by target platform, and aggregates by target identifier. This is the GR-22 feature.

**Assessment:**

This is the single most important feature for the cross-arena discovery workflow. A "ytringsfrihed" researcher who collects Bluesky posts will find links to Telegram channels, YouTube videos, news articles, and blog posts that the community shares. The Discovered Sources feature extracts these links, groups them by platform, and presents them for bulk addition to the actor list.

The `POST /actors/quick-add-bulk` endpoint accepts a list of discovered links with their platform and target_identifier, creates Actor + ActorPlatformPresence records, and optionally adds them to an ActorList.

The Discovered Sources page template (`content/discovered_links.html`) provides a UI for viewing these links and bulk-adding them to actor lists.

**Finding S-10 (strength):** The Discovered Sources pipeline (link mining -> platform classification -> bulk actor creation) is the closest thing to an automated cross-arena discovery workflow. For "ytringsfrihed" research, this means a Bluesky collection can automatically surface Telegram channels, YouTube channels, and organizational websites that free speech actors link to. This is a genuinely novel research feature.

**Finding FP-15 (friction point):** The Discovered Sources page requires a `query_design_id` parameter, which means the researcher must already have a query design with collected content. There is no way to mine links across multiple query designs simultaneously. A researcher who has separate query designs for different sub-topics of "ytringsfrihed" (e.g., one for legal framings, one for social media reactions) cannot see a unified view of discovered sources. [core]

**6c. Snowball Sampling:**

The `POST /actors/sampling/snowball` endpoint accepts seed actor IDs, platforms (bluesky, reddit, youtube), and expansion parameters. It returns discovered actors with their platform presences and can auto-create Actor records in the database.

**Assessment:**

Snowball sampling from seed actors is the classic social science method for discovering additional discourse participants. The implementation supports:
- Multi-wave expansion (configurable `max_depth`)
- Per-wave actor caps (`max_actors_per_step`)
- Auto-creation of Actor records for discovered accounts
- Direct addition to an ActorList (`add_to_actor_list_id`)

For "ytringsfrihed," the researcher could seed with known actors (e.g., Jacob Mchangama's Bluesky handle) and discover who follows, replies to, or is followed by them -- expanding the actor network organically.

**Finding S-11 (strength):** Snowball sampling with auto-creation and list population is a sophisticated research feature. The ability to seed with known actors and expand through platform social graphs, then immediately add discovered actors to a query design's actor list, supports the iterative discovery workflow that discourse research requires.

**Finding FP-16 (friction point):** Snowball sampling only works on Bluesky, Reddit, and YouTube (`_NETWORK_EXPANSION_PLATFORMS`). There is no expansion for Telegram, X/Twitter, Gab, or Facebook -- platforms that are all highly relevant for "ytringsfrihed" research. The limitation is reasonable (those platforms have restricted APIs), but it is not communicated in the UI. A researcher who expects to snowball-sample from a Telegram actor will not understand why it fails silently. [frontend] [data]

**6d. Entity Resolution and Actor Merging:**

The entity resolution page (`/actors/resolution`) finds `author_display_name` values that appear across multiple platforms -- evidence of cross-platform identity. The merge endpoint (`POST /actors/{id}/merge/{other_id}`) consolidates duplicate actors, re-pointing all content records and moving platform presences.

**Assessment:**

For "ytringsfrihed," the same actor often appears with different names across platforms (e.g., "Jacob Mchangama" on Bluesky, "Mchangama" in news articles, "jmchangama" on Twitter). The entity resolution system addresses this.

**Finding S-12 (strength):** The entity resolution pipeline (candidate detection -> trigram similarity matching -> merge with content re-pointing) is a research-grade feature. The split operation (`POST /actors/{id}/split`) handles the inverse case where two different people share a name. Both operations are essential for maintaining a clean actor directory in multi-platform research.

### Step 7: Analysis and Network Visualization

**Researcher action:** After collecting data, the researcher navigates to the Analysis section to examine patterns.

**What the researcher encounters:**

The analysis dashboard (`/analysis/{run_id}`, template: `analysis/index.html`) provides:

- **Run summary** (`/analysis/{run_id}/summary`): total records, platforms, date range, unique authors
- **Volume over time** (`/analysis/{run_id}/volume`): temporal distribution of collected content
- **Top actors** (`/analysis/{run_id}/actors` and `/actors-unified`): most frequent authors, both by display name and by resolved canonical identity
- **Top terms** (`/analysis/{run_id}/terms`): most frequent terms in collected content
- **Emergent terms** (`/analysis/{run_id}/emergent-terms`): TF-IDF analysis to surface terms that are distinctive to this collection vs. baseline
- **Engagement distribution** (`/analysis/{run_id}/engagement`)
- **Network graphs:**
  - Actor co-occurrence (`/analysis/{run_id}/network/actors`)
  - Term co-occurrence (`/analysis/{run_id}/network/terms`)
  - Cross-platform actors (`/analysis/{run_id}/network/cross-platform`)
  - Bipartite actor-term (`/analysis/{run_id}/network/bipartite`)
  - Temporal network snapshots (`/analysis/{run_id}/network/temporal`)
  - Enhanced bipartite (`/analysis/{run_id}/network/enhanced-bipartite`)

All network endpoints support an optional `?arena=` filter for per-arena comparison.

**Assessment:**

The analysis feature set is comprehensive for descriptive discourse analysis. The emergent terms (TF-IDF) feature is particularly valuable -- it identifies which terms are unusually frequent in this collection compared to a baseline, surfacing the distinctive vocabulary of the "ytringsfrihed" debate (e.g., "racismeparagraffen" would score high if it appears disproportionately in this collection vs. general Danish media).

The per-arena network filtering (`?arena=`) enables cross-arena comparison -- the researcher can compare the actor co-occurrence network on Bluesky vs. Reddit vs. RSS to see if different platforms host different discourse communities around "ytringsfrihed."

**Finding S-13 (strength):** The per-arena GEXF export with arena-specific filtering is a genuine research feature. A "ytringsfrihed" researcher can export separate GEXF files for each arena, open them in Gephi, and visually compare how the actor and term networks differ across platforms. This directly supports the comparative platform analysis that discourse researchers need.

**Finding FP-17 (friction point):** All analysis endpoints are scoped to a single collection run (`/analysis/{run_id}/...`). A "ytringsfrihed" researcher who has run multiple collections (e.g., one batch and one live tracking run) cannot analyse them together. Cross-run comparison requires exporting data from each run separately and combining them externally. [core] [research]

### Step 8: Export and External Analysis

**Researcher action:** Export collected data for analysis in external tools.

**Available formats:**
- **CSV** (`GET /content/export?format=csv`): Standard tabular export. Supports `include_metadata` flag.
- **XLSX** (`GET /content/export?format=xlsx`): Excel format.
- **JSON** (`GET /content/export?format=json`): NDJSON format.
- **Parquet** (`GET /content/export?format=parquet`): Columnar format for data science workflows.
- **GEXF** (`GET /content/export?format=gexf&network_type=actor|term|bipartite`): Network graph for Gephi.
- **RIS** (`GET /content/export?format=ris`): Reference manager import format.
- **BibTeX** (`GET /content/export?format=bibtex`): LaTeX reference format.

Synchronous export handles up to 10,000 records. Async export (`POST /content/export/async`) dispatches a Celery task for larger datasets, with status polling and MinIO-hosted download.

**Assessment:**

The export format selection is excellent for a research tool. RIS and BibTeX for reference managers, Parquet for data scientists, GEXF for network analysts, CSV/XLSX for general-purpose analysis. The async export for large datasets with progress tracking is well-architected.

**Finding S-14 (strength):** The seven export formats cover all major research analysis pathways. The GEXF export with three network types (actor co-occurrence, term co-occurrence, bipartite actor-term) is particularly valuable. The RIS and BibTeX formats enable direct citation of collected content in academic publications -- a detail that shows genuine understanding of the research workflow.

**Finding FP-18 (friction point):** The synchronous export cap of 10,000 records is reasonable, but the async export requires Redis and MinIO to be running. A researcher who has not configured the full Docker infrastructure (perhaps running only the FastAPI server and PostgreSQL) will encounter cryptic errors when attempting async export. The error handling for missing MinIO is not tested from the user perspective. [core]

---

## Cross-Arena Workflow Assessment

### The Iterative Discovery Loop

The ideal "ytringsfrihed" research workflow is:

1. **Explore** (Google Autocomplete, AI Chat Search) -> discover associations and framings
2. **Search** (Google Search, GDELT, RSS) -> find initial content and actors
3. **Expand** (Discovered Sources, Snowball Sampling) -> discover additional arenas and actors
4. **Deep-collect** (Bluesky, Reddit, Telegram, Gab) -> focused collection on discovered sources
5. **Resolve** (Entity Resolution, Actor Merge/Split) -> unify cross-platform identities
6. **Analyse** (Network graphs, emergent terms) -> identify patterns and structures
7. **Export** (GEXF, CSV, RIS) -> prepare for external analysis and publication

The application supports every individual step, but the transitions between steps are where the experience breaks down:

**1 to 2 (Explore to Search):** No UI for exploration (FP-02). The researcher must use API calls for ad-hoc exploration, then manually create a query design based on what they learned.

**2 to 3 (Search to Expand):** The Discovered Sources feature (S-10) bridges this gap well. Content Browser full-text search (S-08) also helps. However, moving from "I found a Telegram link in a Bluesky post" to "now I want to collect from that Telegram channel" requires API-level configuration (BL-01).

**3 to 4 (Expand to Deep-collect):** Adding newly discovered actors and sources to the query design requires navigating between the Content Browser, Actor Directory, and Query Design Editor. There is no "add this to my collection" action directly from the content view.

**4 to 5 (Deep-collect to Resolve):** The entity resolution page works but is a separate workflow. The researcher must proactively navigate to `/actors/resolution` -- there is no prompt or suggestion when duplicate actors are detected.

**5 to 6 (Resolve to Analyse):** Analysis is scoped to collection runs, not query designs. If the researcher has run multiple collections as they expanded their scope, they cannot analyse the full corpus in one view (FP-17).

**6 to 7 (Analyse to Export):** Export is well-integrated with filters matching the content browser. No significant friction.

### Overall Cross-Arena Verdict

The application provides the building blocks for cross-arena discourse research but does not yet provide the connective tissue that makes the multi-step workflow feel like a single coherent investigation. The researcher must carry context in their head between sections and manually coordinate operations that should flow naturally from one to the next.

---

## Cost Analysis: Free vs. Paid Tier Assessment

### What a "Ytringsfrihed" Researcher Can Do for Free

| Arena | Free Capability | Limitation |
|-------|----------------|------------|
| Google Autocomplete | Full functionality | No content text, only suggestions |
| RSS Feeds | Full functionality with 30+ Danish feeds | No custom feed management UI |
| Bluesky | Full search and actor collection | API rate limits |
| Reddit | Full search across Danish subreddits | No comment collection at free tier |
| GDELT | Full article metadata collection | 3-month lookback window |
| Via Ritzau | Full press release collection | Only press releases, not news |
| Gab | Basic collection | Limited data quality |
| Common Crawl | Full historical web content search | Complex query syntax |
| Wayback | Full historical page retrieval | Requires specific URLs |
| Web Scraper | Full page scraping (httpx) | No JavaScript rendering |

### What Requires Paid Access

| Arena | Tier | Est. Cost | Value for Ytringsfrihed |
|-------|------|-----------|------------------------|
| Google Search | Medium | ~$0.30/1K queries (Serper.dev) | High -- discovers key actors and websites |
| YouTube | Medium | Free quota (100 units/day) | Medium -- video debates exist but are not the primary arena |
| Telegram | Medium | $0 (self-hosted) | Very High -- critical for fringe discourse |
| TikTok | Medium | Varies (Research API) | Low -- "ytringsfrihed" is not a TikTok topic |
| Event Registry | Medium | Varies (subscription) | Medium -- structured event data |
| X/Twitter | Medium/Premium | ~$0.15/1K (TwitterAPI.io) | High -- significant Danish political discourse |
| Facebook | Premium | Meta Content Library | Very High -- largest Danish social platform |
| Instagram | Premium | Meta Content Library | Low -- visual platform, limited text discourse |
| Majestic | Premium | Subscription | Low -- backlink analysis is secondary |

### Cost-Conscious Recommendation

A "ytringsfrihed" researcher on a minimal budget should prioritize:
1. **Free tier:** Google Autocomplete + RSS Feeds + Bluesky + Reddit + GDELT + Via Ritzau (comprehensive Danish coverage at zero cost)
2. **First paid upgrade:** Google Search (medium) -- $0.30/1K queries to discover the actor and website landscape
3. **Second paid upgrade:** Telegram (medium) -- zero incremental cost but requires credential setup for MTProto, critical for tracking alternative discourse
4. **Optional:** X/Twitter (medium) if budget allows -- adds important platform but duplicates some coverage

**Finding S-15 (strength):** The free tier alone covers six arenas with genuine research value. A researcher can conduct meaningful multi-platform discourse analysis without any API expenditure, which is unusual for a research data collection tool.

---

## Friction Points Summary

| ID | Category | Description | Responsible Agent | Severity |
|----|----------|-------------|-------------------|----------|
| FP-01 | Orientation | No arena overview on dashboard; researcher cannot see capabilities before committing to query design | [frontend] | Medium |
| FP-02 | Exploration | No UI for ad-hoc exploration; arena /collect endpoints are API-only | [frontend] | High |
| FP-03 | Data entry | Search terms must be added one at a time; no bulk import | [frontend] | High |
| FP-04 | Data entry | Group label is free-text with no autocomplete from existing groups | [frontend] | Low |
| FP-05 | Guidance | Arena descriptions are too brief; no contextual relevance guidance | [frontend] | Medium |
| FP-06 | Configuration | Arena grid does not distinguish between search-capable and source-list arenas; no UI for custom config (channels, subreddits, feeds) | [frontend] [core] | High |
| FP-07 | Messaging | Google Search free tier returns empty with no alternative suggestion | [data] | Low |
| FP-08 | Preview | No feed preview or search within RSS feed list | [frontend] | Medium |
| FP-09 | Configuration | Custom subreddit configuration is API-only | [frontend] | Medium |
| FP-10 | Architecture | Single search term list shared across all arenas; no per-arena term customization | [core] [research] | Critical |
| FP-11 | Data entry | Actors must be added one at a time; no bulk import for names | [frontend] | Medium |
| FP-12 | Workflow | Adding platform presences requires navigating away from query design editor | [frontend] | Medium |
| FP-13 | Cost | Pre-flight credit estimate is a stub returning zero | [core] | High |
| FP-14 | Clarity | Tier precedence (design > launcher > global) not explained in UI | [frontend] | Medium |
| FP-15 | Scope | Discovered Sources is scoped to single query design; no cross-design view | [core] | Medium |
| FP-16 | Transparency | Snowball sampling platform limitations not communicated in UI | [frontend] [data] | Medium |
| FP-17 | Analysis | Analysis scoped to single collection run; no cross-run aggregation | [core] [research] | High |
| FP-18 | Infrastructure | Async export requires MinIO; error handling for missing infrastructure unclear | [core] | Medium |

## Blockers Summary

| ID | Description | Responsible Agent | Impact |
|----|-------------|-------------------|--------|
| BL-01 | No UI for specifying Telegram channels, Discord servers, or other source-list arenas; requires API calls | [frontend] [core] | Prevents researchers without API skills from using critical fringe-platform arenas |

---

## Strengths Summary

| ID | Description |
|----|-------------|
| S-01 | Arena configuration grid with per-arena tier selection and credential status |
| S-02 | Comprehensive curated Danish RSS feed list (30+ outlets with editorial context) |
| S-03 | Bluesky free tier with automatic Danish language filtering |
| S-04 | Fringe platform coverage (Gab, Telegram, TikTok, Threads) alongside mainstream |
| S-05 | Via Ritzau inclusion as a free institutional discourse source |
| S-06 | AI Chat Search with query expander could serve as exploration assistant |
| S-07 | Web scraper as managed enrichment service with progress tracking |
| S-08 | Danish full-text search with proper stemming and stop words |
| S-09 | Search terms matched array provides provenance per record |
| S-10 | Discovered Sources pipeline for cross-platform link mining and bulk actor creation |
| S-11 | Snowball sampling with auto-creation and list population |
| S-12 | Entity resolution with trigram similarity, merge, and split operations |
| S-13 | Per-arena GEXF export for cross-platform network comparison |
| S-14 | Seven export formats covering all major research analysis pathways |
| S-15 | Free tier covers six arenas with genuine research value |

---

## Recommendations (Prioritized)

### Critical

1. **[core] [research] Per-arena search term customization (FP-10):** Allow search terms to be tagged with target arenas. A researcher studying "ytringsfrihed" needs "freedom of speech Denmark" for GDELT but not for Bluesky. The current single-list model forces a choice between contaminating non-relevant arenas with English terms or missing English-language coverage on international arenas. Suggested approach: add an optional `target_arenas` array to the `SearchTerm` model, defaulting to all arenas when empty.

### High

2. **[frontend] Ad-hoc exploration UI (FP-02):** Add a "Quick Explore" panel to the dashboard or a standalone exploration page that wraps the existing ad-hoc `/collect` endpoints with a simple form. Let the researcher type a term, pick an arena, and see sample results without creating a query design. Google Autocomplete is the ideal starting point.

3. **[frontend] Bulk search term import (FP-03):** Add a textarea or CSV upload for bulk term entry in the query design editor. The backend `POST /query-designs/` already accepts an array of terms -- the UI just needs to expose it.

4. **[frontend] Custom arena configuration UI (FP-06, BL-01):** Add per-arena configuration panels within the arena grid for arenas that require source lists. Telegram needs a "Channels" input, Reddit needs a "Subreddits" input, RSS needs a "Custom Feeds" input. The `PATCH /query-designs/{id}/arena-config/{arena_name}` endpoint already supports this -- the UI just needs to expose it.

5. **[core] Implement real pre-flight credit estimates (FP-13):** The `POST /collections/estimate` stub needs to return actual estimates based on arena tier configuration, search term count, and date range. Researchers cannot make informed cost decisions without this.

6. **[core] [research] Cross-run analysis (FP-17):** Allow the analysis dashboard to aggregate data from multiple collection runs belonging to the same query design. At minimum, the volume-over-time and top-actors endpoints should support a `query_design_id` parameter as an alternative to `run_id`.

### Medium

7. **[frontend] Arena overview page (FP-01):** Create a dedicated "Arenas" page accessible from the navigation that shows all available arenas with descriptions, tier information, credential status, and links to research briefs. Help the researcher understand their options before designing a query.

8. **[frontend] Tier precedence explanation (FP-14):** Add a tooltip or info panel in the collection launcher explaining the tier override hierarchy.

9. **[frontend] Bulk actor import (FP-11):** Add a textarea or CSV upload for bulk actor entry in the query design editor, mirroring the bulk term import recommendation.

10. **[frontend] Snowball platform disclosure (FP-16):** When the researcher selects platforms for snowball sampling, clearly indicate which platforms support network expansion and which do not. Show a message like "Only Bluesky, Reddit, and YouTube support social graph expansion. For other platforms, use Discovered Sources to find connected actors."

11. **[frontend] Group label autocomplete (FP-04):** Add a datalist or dropdown for the group label field in the term entry form, populated from existing group labels on the current query design.

### Low

12. **[data] Google Search free-tier guidance (FP-07):** When Google Search returns empty at free tier, include a message suggesting the researcher try Google Autocomplete (free) or upgrade to medium tier.

13. **[frontend] RSS feed preview (FP-08):** Add a search/filter capability to the feeds list endpoint so researchers can check which outlets cover their topic before collecting.

14. **[frontend] Custom subreddit UI (FP-09):** Surface the custom subreddit configuration in the Reddit arena card within the arena grid.

---

## Data Quality Considerations for "Ytringsfrihed"

Although this evaluation is code-based rather than live-data-based, several data quality concerns are predictable for the "ytringsfrihed" scenario:

1. **Locale accuracy:** The automatic Danish locale filtering (`gl=dk`, `hl=da`, `lang:da`, `sourcelang=danish`) should correctly restrict results to Danish-language content. However, "ytringsfrihed" as a concept is discussed in English-language media about Denmark (e.g., international coverage of the Muhammad cartoons). The rigid Danish-only filtering may miss important international perspectives. The `PATCH /query-designs/{id}/arena-config/global` with `{"languages": ["da", "en"]}` endpoint exists to address this, but it is not accessible from the UI.

2. **Deduplication:** The `POST /content/deduplicate` endpoint and `GET /content/duplicates` inspection endpoint exist, which is good. For "ytringsfrihed" content, the same news article may appear in GDELT, RSS feeds, and Google Search results. The URL-normalized and content-hash deduplication should handle this, but the researcher needs to know to trigger it.

3. **Temporal gaps:** For live tracking runs, the daily collection schedule (00:00 Copenhagen time) means content published and deleted within 24 hours may be missed. For a volatile topic like "ytringsfrihed" where social media posts may be deleted after backlash, this is a real limitation.

4. **Actor disambiguation:** "Ytringsfrihed" discourse involves several actors with common Danish names. The entity resolution pipeline should handle this, but the researcher must proactively use it -- there is no automatic duplicate detection trigger.

---

## Conclusion

The Issue Observatory is a genuinely capable research tool with an architecture that reflects deep understanding of multi-platform discourse analysis requirements. For a "ytringsfrihed" researcher, the combination of Danish-first defaults, comprehensive arena coverage, sophisticated actor management, and research-grade export formats provides a solid foundation.

The primary improvement needed is not more features but better workflow integration -- making the transitions between exploration, collection, discovery, and analysis feel like a single coherent research process rather than a series of disconnected operations. The building blocks are excellent; the connective tissue between them is where the researcher experience needs investment.

The free-tier capability (six functional arenas covering news, social media, press releases, and international coverage) makes this tool accessible to researchers without significant API budgets, which is a meaningful advantage over commercial alternatives.
