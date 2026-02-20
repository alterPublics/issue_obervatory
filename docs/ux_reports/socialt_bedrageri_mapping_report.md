# UX Test Report -- "Socialt Bedrageri" (Social Benefits Fraud) Discourse Mapping

Date: 2026-02-20
Scenario: Mapping Danish public discourse around "socialt bedrageri" (social benefits fraud), including tensions between welfare enforcement/fraud prevention and protection of vulnerable populations
Arenas examined: All 21 functional arena collectors, with focus on FREE tier arenas and selective MEDIUM tier usage
Tiers examined: Primarily free tier, with targeted medium tier for Google Search, X/Twitter, and TikTok
Evaluation method: Code-based walkthrough of all routes, collectors, templates, schemas, sampling modules, analysis pipeline, and enrichment features -- simulating a researcher who starts with minimal domain knowledge and must use the application's discovery features to iteratively build a comprehensive mapping

---

## Executive Summary

This scenario tests the Issue Observatory's most demanding use case: a researcher with limited prior knowledge of a discourse landscape who must bootstrap a comprehensive multi-platform mapping through iterative discovery, source expansion, and progressive refinement. Unlike previous evaluations where the researcher arrives with a well-formed search strategy, the "socialt bedrageri" scenario requires the application to actively assist in **discovering what to look for**.

The application performs well as a collection execution engine -- once you know your terms, actors, and arenas, the infrastructure for launching, monitoring, and analysing collections is solid. However, this scenario exposes a fundamental workflow gap: **the iterative discovery cycle (collect → analyse → discover → refine → re-collect) requires too many manual context switches and provides too little guidance about what to do next**. The researcher must hold the discovery strategy in their head while navigating between disconnected interface sections.

**Key findings:**

1. **Strengths**: The suggested-terms endpoint (TF-IDF extraction) is genuinely useful for vocabulary expansion. The discovered-links endpoint (GR-22) successfully surfaces cross-platform references. Query design cloning (IP2-051) enables clean versioning of iterative refinements. The snowball sampling pipeline is architecturally complete. Boolean term groups support nuanced AND/OR query structures. Researcher-configurable source lists (custom RSS feeds, Reddit subreddits, Telegram channels) provide the flexibility this scenario demands.

2. **Primary gap**: There is no guided "exploration mode" workflow. The researcher must manually orchestrate the cycle: run initial collection → check analysis dashboard → note suggested terms → navigate to query design editor → add terms → check discovered links → manually add RSS feeds → clone design → re-launch collection. Each step requires navigating to a different section with no breadcrumb or workflow state tracking.

3. **Historical vs. forward-only tension**: The transition from exploratory batch collection to live tracking is technically supported (batch mode vs. live mode on CollectionRun) but the implications are not surfaced to the researcher. Which arenas can look backwards? How far back? The application provides no temporal-capability metadata per arena, forcing the researcher to discover limitations through trial and error.

4. **Cost model works for this scenario**: The free tier covers 12+ arenas adequately for the "socialt bedrageri" topic. Selective medium-tier usage for Google Search and X/Twitter adds high-value social media and search-engine perspectives at manageable cost. The pre-flight credit estimate endpoint exists but is heuristic-based.

5. **Actor building is powerful but disconnected**: The quick-add, snowball sampling, and network expansion features are individually well-designed but require the researcher to manually bridge between content discovery (content browser) and actor management (actor directory/snowball panel). There is no "one-click: add this author and all their co-occurring actors to my study" shortcut.

---

## Scenario Description

### Research Question

How is "socialt bedrageri" (social benefits fraud) constituted as a public issue in Danish discourse? What are the dominant framings -- punitive enforcement vs. protection of vulnerable populations? Who are the key institutional and individual actors across media, politics, and social platforms? How does the discourse propagate across different arenas?

### Why This Scenario Is Challenging

1. **Low prior knowledge**: Unlike academic topics with established bibliographies, welfare fraud discourse is diffuse -- it appears in news reports about specific fraud cases, political speeches about budget reform, social media outrage about "nassere" (freeloaders), and institutional reports from KL (Local Government Denmark) and Udbetaling Danmark. The researcher doesn't know where to start.

2. **Source discovery is essential**: The relevant Telegram channels, Reddit threads, niche RSS feeds (e.g., municipal newsletters, Altinget welfare policy), and YouTube commentators are not obvious. The researcher must discover them through the application's features.

3. **Temporal complexity**: Some discourse is event-driven (a major fraud case in the news), some is structural (ongoing political debate about kontanthjælp). The researcher needs both historical backfill and forward-looking monitoring.

4. **Multi-framing**: The same issue is framed as "cracking down on cheaters" (enforcement frame), "protecting the social safety net" (fiscal frame), "not punishing the innocent" (justice frame), and "structural inequality causes desperation" (systemic frame). The search terms must capture all framings.

5. **Cost sensitivity**: This is a research project, not an enterprise operation. Maximising coverage within the free tier while using paid sources strategically is essential.

### Proposed Initial Search Terms

The researcher begins with basic domain knowledge and constructs an initial term set:

| Term | Type | Group | Rationale |
|------|------|-------|-----------|
| socialt bedrageri | phrase | Core | Primary concept term |
| velfærdsbedrageri | keyword | Core | Alternative: welfare fraud |
| kontanthjælpsbedrageri | keyword | Core | Specific: cash benefit fraud |
| dagpengesvindel | keyword | Core | Specific: unemployment benefit fraud |
| socialt snyd | phrase | Core | Colloquial: social cheating |
| kontanthjælpsmodtager | keyword | Welfare system | Benefit recipient (neutral) |
| kontanthjælpsloft | keyword | Policy | Cash benefit ceiling (policy reform) |
| Udbetaling Danmark | phrase | Actor | Central payment authority |
| kontrolgruppe | keyword | Enforcement | Municipal fraud investigation units |
| nassere | keyword | Framing | Pejorative: freeloaders |
| sociale ydelser | phrase | System | Social benefits (neutral system term) |
| #socialtbedrageri | hashtag | Social | Primary hashtag |

**Total: 12 initial terms across 4 thematic groups.** This is deliberately a starter set -- the scenario tests whether the application helps the researcher expand it.

---

## Step-by-Step Walkthrough

### Step 1: Create Initial Query Design

**Researcher action:** Create a new query design named "Socialt Bedrageri -- Dansk diskurs 2024-2026", add the 12 initial search terms with boolean group structure.

**Endpoints involved:**
- `POST /query-designs/` -- create the design
- `POST /query-designs/{id}/terms` -- add individual terms (one at a time via HTMX form)
- `POST /query-designs/{id}/terms/bulk` -- add multiple terms at once (JSON API)

**What works well:**
- The query design creation flow is straightforward: name, description, visibility, default tier, language (da), locale country (DK). All fields have sensible defaults for the Danish context.
- Term type selection (keyword, phrase, hashtag, url_pattern) is clear and maps well to the search terms above.
- Group labels support boolean grouping -- terms can be assigned to groups like "Core", "Policy", "Enforcement" with stable `group_id` UUIDs derived from the label.
- The `target_arenas` field (YF-01) allows scoping specific terms to specific arenas -- e.g., hashtags only to social media platforms.
- Bulk term import (`POST /terms/bulk`) exists for researchers who prepare term lists externally, which is a genuine workflow improvement.

**Friction encountered:**
- **F-01 (Minor)**: Adding 12 terms one at a time through the HTMX form is tedious. The bulk endpoint exists as a JSON API but there is no bulk-add UI in the editor template. The researcher must either use the API directly or add terms one by one through the form.
- **F-02 (Minor)**: There is no "import from CSV/text file" option in the UI for search terms. Researchers often prepare term lists in spreadsheets.
- **F-03 (Minor)**: When adding a term with a group label, the researcher must type the group label consistently each time. There is no dropdown of existing groups -- if the researcher types "Core" vs "core" vs "Kerne", they get different groups. The UUID derivation normalises case (`uuid5(design_id, label.lower())`), but misspellings create unintended splits.
- **F-04 (Cosmetic)**: The term list in the editor shows term type badges and arena scoping indicators, but not the group label visually. Groups are indicated via `data-group` attributes for JavaScript grouping, but the visual grouping depends on client-side JS that is not evident from the route logic alone.

**Severity: Minor friction overall. The core workflow functions correctly.**

### Step 2: Configure Source-List Arenas

**Researcher action:** Before launching the first collection, configure the source-list arenas (RSS, Reddit, Telegram) with sources relevant to welfare fraud discourse.

**Endpoints involved:**
- `PATCH /query-designs/{id}/arena-config/rss` -- add custom RSS feeds
- `PATCH /query-designs/{id}/arena-config/reddit` -- add custom subreddits
- `PATCH /query-designs/{id}/arena-config/telegram` -- add custom channels
- `POST /query-designs/{id}/arena-config` -- set per-arena tier and enabled/disabled status

**What works well:**
- The PATCH endpoint for per-arena custom config is well-designed: `{"custom_feeds": ["https://altinget.dk/social/rss"]}` cleanly merges into the `arenas_config` JSONB.
- The default Danish RSS feeds (28+ curated feeds: DR, TV2, Politiken, Berlingske, BT, etc.) mean the researcher doesn't need to know every major outlet -- broad news coverage is built in.
- Multiple arenas support researcher customisation: RSS, Telegram, Reddit, Discord, Wikipedia.
- The template has collapsible per-arena configuration panels with save buttons and success/error feedback.
- The YF-02 info box explains that source-list arenas need additional configuration.

**Friction encountered:**
- **F-05 (Major)**: The researcher doesn't know which RSS feeds are relevant to "socialt bedrageri" at this stage. The built-in 28 feeds cover major outlets (DR, TV2, etc.) which will capture mainstream coverage, but specialised feeds (Altinget's social policy section, KL.dk municipal newsletters, welfare policy blogs) are unknown. **There is no feed discovery feature** -- the researcher must find relevant RSS feeds externally and paste URLs. The discovered-links endpoint (GR-22) could theoretically surface these after initial collection, but that requires running a collection first, creating a chicken-and-egg problem.
- **F-06 (Major)**: The researcher doesn't know which Telegram channels discuss welfare fraud in Danish. The application provides no Telegram channel discovery feature. The researcher would need to use external tools (Telegram's built-in search, tgstat.com) to find channels, then paste channel usernames into the config. This is a significant cold-start problem for niche topics.
- **F-07 (Minor)**: For Reddit, the default subreddits (r/Denmark, r/danish, r/copenhagen, r/aarhus, r/dkpolitik) are reasonable starting points. The researcher can add more via `custom_subreddits`. However, Reddit's search within specific subreddits is limited -- the Reddit collector searches across configured subreddits, but the researcher doesn't know if welfare fraud is discussed in r/Denmark or r/dkpolitik or some other subreddit.
- **F-08 (Minor)**: The arena configuration grid shows all available arenas with tier selection, but it does not indicate which arenas support `collect_by_terms` vs. `collect_by_actors` only. Some arenas (e.g., Discord) require channel IDs the researcher doesn't have yet. There is no tooltip or hint about what each arena can actually do for this query.

**Severity: F-05 and F-06 are Major friction. The cold-start problem for source-list arenas is the central challenge of this scenario.**

### Step 3: Initial Exploratory Collection (FREE Tier)

**Researcher action:** Launch a batch collection across FREE-tier arenas to get an initial snapshot of the discourse landscape.

**Endpoints involved:**
- `POST /collections/` -- create and launch collection run
- `GET /collections/{run_id}/stream` -- SSE live monitoring
- `POST /collections/estimate` -- pre-flight credit estimate

**Arenas selected for initial run (all FREE tier):**

| Arena | Temporal Capability | Expected Value for This Issue |
|-------|---------------------|-------------------------------|
| RSS Feeds | Recent items in feed (typically 1-7 days) | HIGH -- mainstream news coverage |
| Via Ritzau | Recent wire stories | HIGH -- breaking fraud stories |
| GDELT | Historical (months/years) | HIGH -- news articles with date range |
| Bluesky | Recent posts (API search window) | MEDIUM -- growing Danish user base |
| Reddit | Recent posts (search API, no date filter) | MEDIUM -- discussion threads |
| YouTube | Search results (relevance sorted) | MEDIUM -- news clips, commentary |
| Gab | Recent posts | LOW -- niche platform |
| Common Crawl | Historical (quarterly crawls) | MEDIUM -- web pages mentioning the issue |
| Wayback Machine | Historical (archived URLs) | LOW -- requires known URLs |
| Wikipedia | Current state + revision history | LOW -- limited to specific articles |
| Threads | Recent posts | MEDIUM -- Meta platform engagement |

**What works well:**
- The collection launch schema is clean: `query_design_id`, `mode: "batch"`, `tier: "free"`, `date_from`, `date_to`. The batch mode with date range is appropriate for exploratory collection.
- Per-arena tier overrides via `arenas_config` on the CollectionRun allow the researcher to keep some arenas at free while selectively upgrading others.
- SSE live monitoring (`GET /collections/{run_id}/stream`) provides real-time feedback with per-arena task status updates. The HTMX `sse-connect` integration means the collection detail page updates automatically.
- The credit estimate endpoint provides a pre-flight cost check before committing.
- Error isolation: if one arena fails (e.g., Gab is unreachable), others continue. The per-task status model (`CollectionTask` per arena) gives granular feedback.

**Friction encountered:**
- **F-09 (Major)**: **The application does not surface which arenas support historical date ranges vs. forward-only collection.** The `CollectionRunCreate` schema accepts `date_from` and `date_to`, but many arena collectors ignore these parameters (e.g., Reddit's search API has no date-range filter, RSS feeds only contain current items, Bluesky search has a limited lookback window). The researcher who sets `date_from: 2025-01-01, date_to: 2026-02-20` will get inconsistent temporal coverage per arena with no indication of which arenas actually respected the date range and which returned "whatever is currently available". This is the **most significant discovery problem** in the exploratory phase.
- **F-10 (Minor)**: The collection launcher UI (HTML template) shows the arena grid for enabling/disabling arenas, but the code-based arena config grid (IP2-001, not yet implemented) would dynamically populate from the server registry. Currently the arena list may be hardcoded in the template or populated via the `list_arenas()` registry call, but there is no per-arena description explaining what each arena does or what data it returns.
- **F-11 (Minor)**: There is no way to run a "discovery collection" that is marked differently from a "production collection". All collection runs feed into the same data pool, which is good for comprehensive analysis, but the researcher may want to distinguish "exploratory runs with initial terms" from "refined runs with expanded terms" in the analysis. The `collection_run_id` FK on content records enables this distinction, but the UI doesn't make it easy to compare runs side by side.
- **F-12 (Cosmetic)**: The keepalive mechanism for SSE (30-second comment frames) is properly implemented, but long-running collections across 10+ arenas may take several minutes. The researcher needs to understand that progress is happening even when individual arena tasks are slow.

**Severity: F-09 is Major. Temporal transparency is critical for exploratory research.**

### Step 4: Review Initial Results and Discover

**Researcher action:** After the initial collection completes, browse collected content, use the analysis dashboard, and leverage discovery features to expand the research scope.

**Endpoints involved:**
- `GET /content/records` -- browse collected content (HTMX paginated)
- `GET /analysis/{run_id}/summary` -- run summary statistics
- `GET /analysis/{run_id}/volume` -- volume over time
- `GET /analysis/{run_id}/actors` -- top actors
- `GET /analysis/{run_id}/actors-unified` -- top actors by canonical identity
- `GET /analysis/{run_id}/terms` -- top terms
- `GET /analysis/{run_id}/suggested-terms` -- TF-IDF emergent terms
- `GET /content/discovered-links` -- cross-platform link mining (GR-22)

**What works well:**
- **Suggested terms** (`GET /analysis/{run_id}/suggested-terms`): This is the single most valuable discovery feature for this scenario. It runs TF-IDF extraction on collected content, removes terms already in the query design, and returns novel vocabulary. For "socialt bedrageri", this could surface terms like "dobbeltliv" (double life), "kontrolindsats" (control effort), "snyderi" (cheating), "tilbagebetaling" (repayment), "fejludbetaling" (incorrect payment), "Ankestyrelsen" (appeals board), or names of specific fraud cases. The `exclude_search_terms=True` flag ensures the researcher only sees genuinely new discoveries.
- **Top actors** (`/actors` and `/actors-unified`): The unified endpoint resolves actors across platforms using the entity resolver, showing the researcher who is talking about this issue. For welfare fraud, expect politicians (social affairs spokespeople), journalists (welfare beat reporters), institutional actors (Udbetaling Danmark, KL), and citizen commentators.
- **Discovered links** (`GET /content/discovered-links`): The LinkMiner extracts URLs from `text_content`, classifies them by platform, and returns grouped results. This could reveal: YouTube videos about fraud cases, Telegram channels sharing welfare fraud stories, specific web pages from municipal control units, links to parliamentary debates on retsinformation.dk, etc. Grouped by platform and sorted by `source_count`, high-signal targets surface first.
- **Volume over time**: For an issue like socialt bedrageri, volume spikes likely correlate with major fraud cases or policy announcements. The volume timeline helps the researcher identify peak discourse periods.

**Friction encountered:**
- **F-13 (Major)**: **The suggested-terms endpoint returns terms but has no UI action to add them to the query design.** The researcher sees suggested terms in the analysis dashboard but must mentally note them, navigate to the query design editor, and manually type each one. There should be a one-click "Add to query design" button next to each suggested term.
- **F-14 (Major)**: **The discovered-links endpoint surfaces new sources but has no UI action to add them.** If the researcher discovers a relevant Telegram channel URL or an RSS feed URL in the discovered links, they must copy the identifier, navigate to the query design editor's arena config panel, and paste it into the custom sources field. There should be a "Add as custom feed" or "Add as monitored channel" button.
- **F-15 (Minor)**: The analysis dashboard is scoped to a single `run_id`. For an iterative discovery workflow, the researcher needs to compare results across multiple runs (initial exploration vs. refined collection). The YF-06 cross-run analysis endpoints exist (`/analysis/designs/{design_id}/...`) but the primary analysis dashboard entry point still routes through a specific run.
- **F-16 (Minor)**: The content browser shows records with platform, arena, title, text content, and engagement score, but the slide-in detail panel rendering depends on template code. The researcher needs to quickly scan content to identify relevant sources and actors. Scanning efficiency depends on how much content is visible per page and whether filtering is fast.
- **F-17 (Minor)**: Top actors lists show `author_display_name` and counts, but for pseudonymised authors (GDPR compliance via SHA-256), the researcher sees hashed IDs rather than human-readable names. This is correct for privacy, but makes it harder to identify which authors are worth tracking. The `public_figure` flag bypass (GR-14) helps for known public figures but doesn't help discover new ones.

**Severity: F-13 and F-14 are Major. They represent the core gap in the discovery workflow -- the application discovers valuable information but makes it hard to act on it.**

### Step 5: Refine Query Design (Clone and Expand)

**Researcher action:** Clone the initial query design, add newly discovered terms and sources, and prepare for a refined collection.

**Endpoints involved:**
- `POST /query-designs/{id}/clone` -- clone design (IP2-051)
- `POST /query-designs/{new_id}/terms` -- add discovered terms
- `PATCH /query-designs/{new_id}/arena-config/rss` -- add discovered RSS feeds
- `PATCH /query-designs/{new_id}/arena-config/telegram` -- add discovered channels
- `PATCH /query-designs/{new_id}/arena-config/reddit` -- add discovered subreddits

**What works well:**
- **Query design cloning** is excellent for this workflow. The researcher clicks "Clone" on the original design, getting a deep copy with "(copy)" appended to the name, all search terms, all actor lists, all arena configs, and the `parent_design_id` linking back to the original. This is exactly how versioned research designs should work.
- The clone provenance is displayed: "Cloned from: Socialt Bedrageri v1" with a link back to the parent design. This maintains the research audit trail.
- The `arenas_config` JSONB merge on PATCH is well-designed: `PATCH /arena-config/rss {"custom_feeds": ["https://newdiscovery.dk/rss"]}` merges into existing config without overwriting the built-in feeds.
- Search terms support `is_active` toggling, so the researcher can deactivate terms that produced noise without deleting them (though this toggle is currently not exposed as a standalone endpoint -- terms are active by default and only hard-deleted via DELETE).

**Friction encountered:**
- **F-18 (Minor)**: After cloning, the researcher must manually transfer each discovered term from the analysis dashboard to the query design editor. With 10+ suggested terms, this is tedious. An "Apply suggested terms to design" batch action would streamline this significantly.
- **F-19 (Minor)**: There is no term deactivation endpoint (only hard delete). If the researcher adds a term that produces too much noise, the only option is deletion, which loses the record of what was tried. A `PATCH /terms/{term_id}` to toggle `is_active` would preserve research methodology records.
- **F-20 (Minor)**: The clone name "{original} (copy)" is functional but not semantic. The researcher would prefer naming it "Socialt Bedrageri v2 -- expanded terms" during the clone operation, not as a separate update step after creation.
- **F-21 (Cosmetic)**: After cloning, the redirect goes to `/query-designs/{new_id}` (the clone's editor), which is correct. But there's no visual indicator that this is a fresh clone vs. a regular design beyond the provenance link at the top.

**Severity: Minor friction. The cloning workflow is one of the strongest features for iterative research.**

### Step 6: Build Actor Lists from Initial Results

**Researcher action:** Identify key actors from the initial collection and build a tracked actor list using quick-add, bulk-add, and snowball sampling.

**Endpoints involved:**
- `POST /actors/quick-add` -- single-step actor creation from content browser
- `POST /actors/quick-add-bulk` -- bulk create from discovered links
- `POST /query-designs/{id}/actors` -- add actor to query design
- `POST /query-designs/{id}/actors/bulk` -- bulk add actors (YF-07)
- `POST /actors/{id}/presences` -- add platform presence
- `POST /actors/sampling/snowball` -- run snowball sampling
- `GET /actors/sampling/snowball/platforms` -- available expansion platforms

**What works well:**
- **Quick-add from content browser** (GR-17): The researcher can spot an author in the content browser and add them as an actor with one action: display name, platform, platform username, actor type. This creates a canonical Actor record and optionally adds them to a specific actor list. For "socialt bedrageri", this lets the researcher quickly capture: politicians quoted in RSS/GDELT articles, journalists who wrote multiple pieces, social media commentators with high engagement.
- **Bulk add to query design** (YF-07): The researcher can import a prepared list of actors (e.g., all members of the Folketing's social affairs committee) via JSON API. Each actor is created-or-linked to a canonical record and added to the design's default actor list.
- **Actor directory with platform presences**: Each actor can have multiple platform presences (e.g., "Mette Frederiksen" has presences on Bluesky, X/Twitter, Instagram). This enables cross-platform actor-based collection.
- **Snowball sampling** is architecturally complete: given seed actors and platforms (Bluesky, Reddit, YouTube support network expansion), the sampler iteratively discovers connected accounts (followers, co-commenters, related channels) up to configurable depth and budget limits. Error isolation means one failed expansion doesn't abort the whole run.
- **Actor link in query design editor**: Each actor in the design's actor list has a "Profile" link to their actor detail page and an "Add presences" link to configure their platform identities. This connects the query design workflow to the actor management workflow.

**Friction encountered:**
- **F-22 (Major)**: **Snowball sampling requires seed actors with platform presences configured, but the quick-add flow doesn't prompt for platform presence setup.** The researcher quick-adds "Peter Hummelgaard" (Social Affairs Minister) from an RSS article, but the quick-add only captures the display name and platform username from the content record's context. To use this actor as a snowball seed on Bluesky, the researcher must navigate to the actor's profile page, add a Bluesky presence (handle), then return to the snowball sampling panel. This multi-step handoff breaks the discovery flow.
- **F-23 (Minor)**: Network expansion currently supports only Bluesky, Reddit, and YouTube (per `_NETWORK_EXPANSION_PLATFORMS`). For a welfare fraud topic, X/Twitter and Telegram would be more valuable expansion platforms but are not supported for snowball sampling. This limits the utility of snowball sampling for this specific use case.
- **F-24 (Minor)**: The snowball sampling results include `auto_created_actor_ids` -- newly discovered actors are automatically added to the Actor directory. But the researcher then needs to manually add these discovered actors to their query design's actor list. There is no "add all snowball results to my design" batch action.
- **F-25 (Minor)**: There is no "show me which actors in my results co-occur with each other" shortcut from the content browser to the actor co-occurrence network. The researcher must go to the analysis dashboard, check the actor co-occurrence graph, then manually identify interesting clusters and add them via the actor directory. A more integrated workflow would let the researcher select actors from the network visualization and add them to their design.

**Severity: F-22 is Major. The disconnection between actor creation and platform presence setup breaks the snowball sampling workflow.**

### Step 7: Second Collection Round (Refined Design)

**Researcher action:** Launch a collection using the refined (cloned) query design with expanded terms and sources.

**Endpoints involved:**
- `POST /collections/` -- launch new collection with the cloned design
- `GET /collections/?query_design_id={id}` -- list runs for this design

**What works well:**
- The new collection run references the cloned query design, so all data is linked to the same research project through the query design lineage (`parent_design_id`).
- Content from both the initial and refined runs is in the same data pool (`content_records` table), filterable by `collection_run_id` or `query_design_id`.
- The collection list can be filtered by `query_design_id`, showing all runs for this research project in one view.
- Deduplication (URL hash + content hash + SimHash near-duplicate) prevents duplicate records when the refined collection re-fetches content already captured in the initial run.

**Friction encountered:**
- **F-26 (Minor)**: There is no "diff" view between two collection runs. The researcher cannot easily see "what did the refined design capture that the initial design missed?" They would need to export both runs and compare externally, or use the analysis endpoints with different `run_id` parameters. A comparative run analysis view would be valuable for iterative refinement.
- **F-27 (Minor)**: Content records from the second run that overlap with the first (deduplicated) are silently dropped. The researcher doesn't know how many records were deduplicated vs. genuinely new. The `duplicate_of` markers in `raw_metadata` track this, but there is no summary exposed in the collection detail or analysis dashboard.
- **F-28 (Cosmetic)**: The collection list shows runs with their status, record counts, and credit costs. But there is no indication of which query design version was used or how the designs differ. The researcher must click through to each run to see its associated design.

**Severity: Minor friction. The data pooling and deduplication work correctly.**

### Step 8: Transition from Exploration to Live Tracking

**Researcher action:** After two rounds of exploratory batch collection, the researcher is satisfied with their term set and source configuration. They want to set up ongoing daily monitoring.

**Endpoints involved:**
- `POST /collections/` with `mode: "live"` -- create live tracking run
- `GET /collections/{run_id}/schedule` -- check schedule info
- `POST /collections/{run_id}/suspend` -- pause live tracking
- `POST /collections/{run_id}/resume` -- resume live tracking

**What works well:**
- The `mode: "live"` option on `CollectionRunCreate` creates a run that is picked up by Celery Beat for daily execution at 00:00 Copenhagen time. This is the correct mechanism for ongoing monitoring.
- **Suspend/resume** endpoints are well-designed: a researcher can pause live tracking during holidays or when redesigning the study, then resume without data loss. The `suspended_at` timestamp provides audit trail.
- The schedule endpoint returns human-readable timing: `{"next_run_at": "00:00 Copenhagen time", "timezone": "Europe/Copenhagen"}`.
- Live tracking runs use the same query design as batch runs, so the full term set, actor list, and arena config apply.

**Friction encountered:**
- **F-29 (Major)**: **There is no clear UI/workflow guidance for transitioning from batch exploration to live tracking.** The researcher must create a new collection run with `mode: "live"` -- but should they use the same query design or the refined clone? Should the batch runs be "archived" somehow? What happens to historical data from batch runs when live tracking starts collecting forward-looking data? The application treats batch and live as independent collection runs, which is architecturally correct, but the researcher needs guidance on the transition workflow.
- **F-30 (Major)**: **The researcher cannot see which arenas will actually produce new data in live mode vs. which only work in batch.** Arenas like GDELT, Common Crawl, and Wayback Machine are primarily historical/archival -- they may not produce meaningful daily updates. The researcher might enable all 12 FREE arenas for live tracking, only to find that 5 of them never return new content in daily runs, wasting collection cycles and muddying the analysis with "no new data" runs.
- **F-31 (Minor)**: Daily collection at 00:00 Copenhagen time is a fixed schedule. The researcher cannot configure the frequency (hourly for breaking stories, weekly for slower-moving topics) or the time of day. For "socialt bedrageri", major fraud cases might break during business hours, and the researcher might want more frequent collection during peak news cycles.
- **F-32 (Minor)**: There is no notification mechanism beyond email for live tracking events. Volume spike alerts (GR-09) are stored on collection runs and available via `GET /query-designs/{id}/alerts`, but the researcher must actively check. An in-app notification badge or dashboard widget showing "3 new volume spikes detected this week" would improve awareness.

**Severity: F-29 and F-30 are Major. The batch-to-live transition needs explicit guidance and arena-level temporal metadata.**

### Step 9: Selective MEDIUM Tier Usage

**Researcher action:** After establishing the free-tier monitoring baseline, selectively add MEDIUM-tier arenas for higher-value data.

**Selected MEDIUM-tier additions:**

| Arena | Tier | Cost Rationale | Value for This Issue |
|-------|------|----------------|----------------------|
| Google Search (Serper.dev) | MEDIUM | ~$50/month for moderate usage | HIGH -- captures search results about fraud cases, policy pages, municipal reports |
| X/Twitter (TwitterAPI.io) | MEDIUM | Per-query pricing | HIGH -- political discourse, journalist commentary, public outrage |
| TikTok | MEDIUM | Per-query pricing | MEDIUM -- younger demographic perspective, viral fraud stories |
| AI Chat Search (OpenRouter) | MEDIUM | Per-query pricing | MEDIUM -- query expansion and citation extraction |

**What works well:**
- Per-arena tier override works correctly: the researcher can set `arenas_config: {"google_search": "medium", "x_twitter": "medium"}` while keeping all other arenas at free tier.
- The tier precedence system (IP2-022) correctly resolves: per-arena config on query design > per-arena config on launcher > global default tier. This means the researcher can save their tier preferences on the query design and have them apply to every subsequent run.
- The credit estimate endpoint provides pre-flight cost awareness.
- The AI Chat Search arena (OpenRouter) offers query expansion -- feeding the researcher's terms through an LLM to generate related queries and extract citations from LLM responses. This is particularly useful for a topic like "socialt bedrageri" where the researcher may not know all the Danish policy vocabulary.

**Friction encountered:**
- **F-33 (Minor)**: The credit estimate is heuristic-based (±50% accuracy per the docstring). For budget-conscious researchers, this uncertainty is uncomfortable. A "run one query for $X" test mode would help calibrate expectations.
- **F-34 (Minor)**: There is no cumulative cost dashboard showing "how much have I spent this month across all MEDIUM-tier arenas?" The credit service exists but the route handler for credit management is noted as "partial stub" in CLAUDE.md. Researchers need clear cost visibility.
- **F-35 (Cosmetic)**: The tier names (free, medium, premium) are clear, but the mapping to actual services (Serper.dev, TwitterAPI.io) is not visible in the UI. The researcher must consult documentation to understand which provider each tier uses.

**Severity: Minor friction. The tier system is well-designed for cost-conscious usage.**

### Step 10: Cross-Arena Analysis

**Researcher action:** Analyse the collected data across all arenas to understand discourse propagation, actor networks, and framing patterns.

**Endpoints involved:**
- `GET /analysis/{run_id}/network/actors` -- actor co-occurrence graph
- `GET /analysis/{run_id}/network/terms` -- term co-occurrence graph
- `GET /analysis/{run_id}/network/cross-platform` -- cross-platform actors
- `GET /analysis/{run_id}/network/bipartite` -- bipartite actor-term graph
- `GET /analysis/{run_id}/network/temporal` -- temporal network snapshots
- `GET /content/export?format=gexf&network_type=actors` -- GEXF export for Gephi
- `GET /content/export?format=csv` -- flat export for R/Python analysis

**What works well:**
- **Cross-platform actor analysis** is particularly valuable for this scenario. If "Peter Hummelgaard" (Social Affairs Minister) appears in RSS news articles, Bluesky posts, and YouTube interviews, the cross-platform endpoint surfaces this multi-arena presence. For welfare fraud discourse, identifying which actors operate across platforms reveals the opinion leaders.
- **Term co-occurrence** can reveal framing clusters: "socialt bedrageri" co-occurring with "kontrol" and "sanktion" (enforcement frame) vs. co-occurring with "sårbare borgere" and "retssikkerhed" (justice frame).
- **Temporal network snapshots** track how the discourse network evolves over time -- useful for detecting when a fraud case breaks (sudden term/actor burst) and how it propagates.
- **GEXF export** for Gephi supports three graph types (actor co-occurrence, term co-occurrence, bipartite) with optional per-arena filtering (`?arena=`). This enables the researcher to produce publication-quality network visualisations.
- **Propagation analysis** (GR-08) can detect cross-arena temporal patterns: a story breaks on Ritzau, appears in DR RSS an hour later, generates Bluesky discussion the same day, and triggers Reddit threads the next day.
- **Multiple export formats** (CSV, XLSX, NDJSON, Parquet, GEXF, RIS, BibTeX) cover the full range of downstream analysis tools.

**Friction encountered:**
- **F-36 (Minor)**: The analysis dashboard is scoped per-run rather than per-design by default. For a researcher who has run 4 exploratory collections + 2 weeks of live tracking, the most useful view would aggregate all data for the query design. The YF-06 cross-run endpoints exist but are less prominent than the per-run analysis.
- **F-37 (Minor)**: Coordination detection (GR-11) exists as a query function but the UI integration is unclear from the route code. The researcher interested in whether there is coordinated posting about welfare fraud (e.g., political messaging campaigns) would need to know this feature exists.
- **F-38 (Cosmetic)**: Export file naming uses generic patterns. For a researcher managing multiple exports across designs and runs, more descriptive filenames (including the design name and date range) would help file management.

**Severity: Minor friction. The analysis capabilities are comprehensive.**

### Step 11: Annotation and Qualitative Coding

**Researcher action:** Annotate key content items with stance labels and qualitative codes for deeper analysis.

**Endpoints involved:**
- `POST /annotations/` -- create annotation
- `GET /annotations/?content_record_id={id}` -- read annotations for a record
- `DELETE /annotations/{id}` -- delete annotation

**What works well:**
- Content annotations support a stance vocabulary (positive, negative, neutral, contested, irrelevant) that maps well to discourse analysis frameworks.
- Annotations are linked to specific content records, creating a qualitative layer over quantitative collection data.
- The annotation model allows free-text notes alongside stance labels.

**Friction encountered:**
- **F-39 (Minor)**: There is no batch annotation feature. For a researcher coding 50 articles about a specific fraud case, they must annotate one at a time through the content detail panel.
- **F-40 (Minor)**: There is no annotation export. The researcher's qualitative coding is stored in the database but cannot be easily exported alongside the content records for external qualitative analysis tools (NVivo, ATLAS.ti).
- **F-41 (Minor)**: The stance vocabulary is fixed (positive, negative, neutral, contested, irrelevant). For welfare fraud discourse, the researcher might want custom categories: "enforcement frame", "justice frame", "fiscal frame", "systemic frame". Custom annotation schemas are not supported.

**Severity: Minor friction. Annotation is a supplementary feature that works for basic use.**

---

## Multi-Step Workflow Assessment

### Exploration-to-Tracking Transition

The workflow from initial exploration to live tracking requires the following multi-step sequence:

1. Create initial query design with starter terms → 2. Configure source-list arenas (RSS, Reddit, Telegram) → 3. Launch batch collection → 4. Review results in analysis dashboard → 5. Use suggested-terms endpoint to discover new vocabulary → 6. Use discovered-links endpoint to find new sources → 7. Clone query design → 8. Manually add discovered terms to cloned design → 9. Manually add discovered sources to arena config → 10. Build actor lists from initial results → 11. Launch refined batch collection → 12. Compare results → 13. Switch to live tracking mode

**Assessment:** Steps 1-4 work smoothly. Steps 5-9 are where the workflow breaks down -- the researcher discovers valuable information (terms, sources, actors) in one part of the application but must manually transfer it to another part. Steps 10-12 add further manual coordination. Step 13 requires understanding of batch vs. live mode implications that are not surfaced in the UI.

**Overall rating: Functional but high-friction.** The individual components are well-implemented, but the transitions between them require too much manual coordination. A "research workflow wizard" or "discovery sidebar" that tracks the researcher's discovery state and offers one-click actions would transform this from a disconnected tool set into a cohesive research workflow.

### Historical vs. Forward-Only Data Source Navigation

**Arena temporal capabilities (not surfaced in the application):**

| Arena | Historical Lookback | Forward Collection | Notes |
|-------|--------------------|--------------------|-------|
| GDELT | Months/years | Daily updates | Best historical source |
| Common Crawl | Quarterly crawl archives | No real-time | Historical only |
| Wayback Machine | Years (archived pages) | No -- requires known URLs | Archival |
| Event Registry | Months (with date filters) | Daily updates | MEDIUM tier |
| TikTok | 30 days (with date range) | Yes | MEDIUM tier |
| X/Twitter | 7 days (search API) | Yes | MEDIUM tier |
| Reddit | Limited (no date filter in API) | Yes (recent posts) | Sorted by relevance |
| Bluesky | Limited (API search window) | Yes | Growing platform |
| RSS Feeds | Current feed items (1-7 days) | Yes | Ephemeral |
| Via Ritzau | Recent stories | Yes | Wire service |
| YouTube | Search results (relevance) | Yes | Date-sorted option |
| Gab | Recent posts | Yes | Small platform |
| Threads | Recent posts | Yes | Unofficial API |
| Wikipedia | Full revision history | Watchlist monitoring | Revision-based |

**Assessment:** The researcher has no way to see this table within the application. The `supported_tiers` attribute is exposed per arena, but there is no `temporal_capabilities` or `lookback_window` metadata. This forces trial-and-error discovery of temporal limitations, which is particularly frustrating when the researcher sets a date range expecting comprehensive historical coverage.

### Query Design Iteration (Versioning, Cloning, Refinement)

**Assessment: Good.** The clone + parent_design_id lineage is a solid foundation for iterative research design. The researcher can trace the evolution of their query design from initial exploration through multiple refinements. The JSONB `arenas_config` preservation in clones means source configurations are inherited correctly.

**Gap:** There is no "design comparison" view showing the diff between two design versions (terms added/removed, sources changed). This would be valuable for methodology documentation.

### Actor List Building and Expansion Workflow

**Assessment: Architecturally complete but operationally disconnected.** All the pieces exist -- quick-add from content, bulk import, snowball sampling, network expansion, entity resolution, merge/split. But the workflow requires navigating between content browser (discover actor) → actor directory (configure presences) → snowball panel (expand network) → query design editor (add to design). Each transition is a page navigation with context loss.

### Source Discovery and Addition

**Assessment: The cold-start problem is real.** For RSS feeds, the built-in 28 Danish feeds provide excellent baseline coverage. For Telegram channels, Reddit subreddits, and niche web sources, the researcher starts from zero. The discovered-links endpoint can surface these after initial collection, but the chicken-and-egg problem remains: you need data to discover sources, but you need sources to collect data.

---

## Cost Optimization Assessment

### FREE Tier Coverage

For the "socialt bedrageri" scenario, the FREE tier covers the research adequately for initial exploration:

| Category | Arenas | Assessment |
|----------|--------|------------|
| News media | RSS Feeds (28+ feeds), Via Ritzau, GDELT | Excellent -- covers all major Danish outlets |
| Social media | Bluesky, Reddit, Gab, Threads | Moderate -- misses X/Twitter (the largest Danish social media political discourse platform) |
| Video | YouTube | Good -- free search API |
| Web archive | Common Crawl, Wayback Machine | Good for historical context |
| Messaging | Telegram | Good if channels are known |
| Reference | Wikipedia | Niche utility |

**Assessment:** The free tier provides 12+ arenas that collectively capture the broad discourse landscape. The critical gap is X/Twitter (MEDIUM), which for Danish political discourse about welfare policy is likely the single most important social media source. The researcher should budget for MEDIUM-tier X/Twitter access as a priority.

### Recommended MEDIUM Tier Additions

1. **X/Twitter** (HIGH priority): Danish political discourse is heavily concentrated on X/Twitter. Politicians, journalists, and commentators discuss welfare policy actively. Cost-effective via TwitterAPI.io.
2. **Google Search** (MEDIUM priority): Captures municipal reports, think-tank publications, and government policy documents that don't appear in RSS feeds.
3. **TikTok** (LOW priority for this topic): Welfare fraud is not primarily a youth/viral topic. May capture some "nasser" outrage content but lower signal-to-noise.
4. **AI Chat Search** (MEDIUM priority): Query expansion could help discover welfare policy vocabulary the researcher doesn't know.

### Cost Estimate

With primarily free-tier arenas and selective medium-tier usage for X/Twitter and Google Search, estimated monthly cost is low. The credit service provides budget guardrails, and the pre-flight estimate endpoint helps calibrate before each run.

---

## Platform Coverage Matrix

| Arena | Tier Used | Temporal Coverage | Value for This Issue | Data Volume Expected |
|-------|-----------|-------------------|----------------------|---------------------|
| RSS Feeds | FREE | Rolling 1-7 days | HIGH | 50-200 articles/day |
| Via Ritzau | FREE | Rolling recent | HIGH | 10-50 stories/day |
| GDELT | FREE | Historical months | HIGH | 100-500 articles/month |
| Bluesky | FREE | Recent posts | MEDIUM | 20-100 posts/day |
| Reddit | FREE | Recent relevance | MEDIUM | 5-30 threads/week |
| YouTube | FREE | Search relevance | MEDIUM | 10-50 videos |
| Threads | FREE | Recent posts | LOW-MEDIUM | 10-30 posts/day |
| Gab | FREE | Recent posts | LOW | 0-5 posts/day |
| Common Crawl | FREE | Quarterly archive | LOW-MEDIUM | Variable |
| Wayback Machine | FREE | Historical archive | LOW | Requires known URLs |
| Wikipedia | FREE | Revision history | LOW | 0-5 edits/week |
| Telegram | FREE | Recent messages | MEDIUM | Depends on channels known |
| X/Twitter | MEDIUM | 7-day window | HIGH | 50-200 tweets/day |
| Google Search | MEDIUM | Search index | HIGH | 50-100 results/query |
| TikTok | MEDIUM | 30-day window | LOW | 5-20 videos |
| AI Chat Search | MEDIUM | LLM citations | MEDIUM | Supplementary |

---

## Suggested New Features

Based on this scenario's discovery-intensive workflow, the following features would significantly improve the researcher experience:

### 1. Arena Temporal Capability Metadata (HIGH priority)
Expose per-arena `lookback_window`, `supports_date_range`, and `collection_mode` (historical/forward/both) as structured metadata in the arena registry. Surface this in the collection launcher UI so the researcher knows what to expect from each arena before launching.

### 2. One-Click "Add to Design" from Discovery Results (HIGH priority)
Add actionable buttons to:
- Suggested terms → "Add to current query design"
- Discovered links → "Add as custom RSS feed / Telegram channel / Reddit subreddit"
- Top actors → "Add to actor list"
This would transform the discovery workflow from multi-step manual transfer to one-click actions.

### 3. Source Discovery Assist (HIGH priority)
For the cold-start problem with source-list arenas, provide:
- **RSS feed discovery**: Given the search terms, search for RSS feeds from Danish websites that cover the topic (e.g., via Google RSS search, or matching known Danish outlet section feeds).
- **Telegram channel search**: Integrate with Telegram's search API or tgstat.dk to find Danish channels related to the search terms.
- **Reddit subreddit recommendation**: Based on initial results, suggest subreddits where the issue is discussed.

### 4. Research Workflow Tracker (MEDIUM priority)
A sidebar or progress indicator that tracks the researcher's position in the discovery cycle: "You've completed initial collection → Suggested terms available → 3 new sources discovered → Clone design recommended". This would guide researchers through the iterative workflow without requiring them to hold the strategy in their head.

### 5. Run Comparison / Diff View (MEDIUM priority)
A view that shows the difference between two collection runs: new records, new actors, new terms, new sources. This helps the researcher evaluate whether their query design refinement was productive.

### 6. Batch Annotation with Custom Schemas (MEDIUM priority)
Allow researchers to define custom annotation categories (e.g., discourse frames) and annotate multiple records at once. Export annotations alongside content for qualitative analysis tools.

### 7. Configurable Collection Frequency for Live Tracking (LOW priority)
Allow the researcher to set collection frequency per design: hourly, daily (current), weekly. Event-driven topics benefit from more frequent collection during peak periods.

### 8. Arena-Level Collection Results Transparency (LOW priority)
After each collection run, show per-arena results including: "Records collected", "Date range actually covered", "Terms that matched", "Arena-specific notes (e.g., 'Reddit: no date filter applied, sorted by relevance')". This helps the researcher understand what they actually got from each arena.

### 9. Smart Source Suggestions from Content (LOW priority)
When the content corpus mentions specific sources repeatedly (e.g., many articles link to "udbetaling.dk", or multiple posts reference "t.me/danskpolitik"), automatically suggest these as custom sources to add to the appropriate arena configuration.

### 10. Actor Platform Presence Auto-Detection (LOW priority)
When quick-adding an actor from content, attempt to automatically find their presence on other platforms (e.g., if adding from a Bluesky post, check if a Twitter/X handle with the same name exists). This would reduce the manual platform presence setup that currently blocks snowball sampling.

---

## Data Quality Observations

1. **Deduplication across runs**: The URL hash + content hash + SimHash near-duplicate pipeline correctly prevents duplicate records when refined collections re-fetch overlapping content. The `duplicate_of` marker in `raw_metadata` preserves the audit trail.

2. **Language filtering**: Danish locale defaults (`lang:da`, `gl=dk`, `hl=da`, `sourcelang:danish`) are well-configured across arenas. However, welfare fraud discourse may include Norwegian/Swedish terms ("sosialstønadsbedrageri", "välfärdsbedrägeri") that could be relevant in Scandinavian cross-border discussions. The multi-language selector (GR-05) supports adding additional languages.

3. **Pseudonymization**: SHA-256 pseudonymization with salt correctly protects private citizens' identities. The public figure bypass (GR-14) is appropriate for politicians and institutional actors in welfare fraud discourse. The `public_figure` flag requires manual setting per actor, which is manageable for a focused study.

4. **Engagement score comparability**: Engagement scores come from different platforms with different scales (Reddit upvotes vs. Bluesky likes vs. YouTube views). The engagement score normalization (IP2-030) is listed as "not yet implemented", meaning cross-platform engagement comparison is unreliable.

5. **SimHash near-duplicate detection**: Useful for detecting slightly-modified press releases (common in Danish news, where DR/TV2/Ritzau often carry the same wire story with minor edits). This prevents inflated record counts.

---

## Friction Log

| # | Description | Severity | Step | Category |
|---|-------------|----------|------|----------|
| F-01 | No bulk term add UI in editor; only JSON API exists | Minor | S1 | Query Design |
| F-02 | No CSV/text file import for search terms | Minor | S1 | Query Design |
| F-03 | No dropdown for existing term groups; free-text group labels risk misspelling | Minor | S1 | Query Design |
| F-04 | Group labels not visually distinct in term list | Cosmetic | S1 | Query Design |
| F-05 | No RSS feed discovery feature for cold-start source finding | Major | S2 | Source Discovery |
| F-06 | No Telegram channel discovery feature | Major | S2 | Source Discovery |
| F-07 | Reddit subreddit relevance unknown before collection | Minor | S2 | Source Discovery |
| F-08 | Arena capabilities (terms vs. actors, temporal, tier) not described in UI | Minor | S2 | Arena Config |
| F-09 | No per-arena temporal capability metadata; inconsistent date range handling | Major | S3 | Collection |
| F-10 | Arena grid may lack per-arena descriptions | Minor | S3 | Collection |
| F-11 | No "discovery vs. production" run distinction | Minor | S3 | Collection |
| F-12 | Long-running collections need better progress feedback | Cosmetic | S3 | Collection |
| F-13 | Suggested terms have no one-click "add to design" action | Major | S4 | Discovery |
| F-14 | Discovered links have no one-click "add as source" action | Major | S4 | Discovery |
| F-15 | Analysis dashboard scoped per-run, not per-design by default | Minor | S4 | Analysis |
| F-16 | Content browser scanning efficiency depends on template | Minor | S4 | Content |
| F-17 | Pseudonymised authors hard to identify as trackable actors | Minor | S4 | Privacy |
| F-18 | No batch "apply suggested terms to design" action | Minor | S5 | Query Design |
| F-19 | No term deactivation endpoint; only hard delete | Minor | S5 | Query Design |
| F-20 | Clone name defaults to "{original} (copy)"; no rename during clone | Minor | S5 | Query Design |
| F-21 | Cloned design not visually distinct from regular design | Cosmetic | S5 | Query Design |
| F-22 | Quick-add doesn't prompt for platform presence setup; blocks snowball | Major | S6 | Actor Mgmt |
| F-23 | Snowball sampling limited to Bluesky/Reddit/YouTube expansion | Minor | S6 | Sampling |
| F-24 | Snowball results not auto-added to query design actor list | Minor | S6 | Sampling |
| F-25 | No shortcut from network visualization to actor list addition | Minor | S6 | Analysis |
| F-26 | No run comparison / diff view between collection runs | Minor | S7 | Analysis |
| F-27 | Deduplication counts not surfaced in run summary | Minor | S7 | Collection |
| F-28 | Collection list doesn't show which design version was used | Cosmetic | S7 | Collection |
| F-29 | No guidance for batch-to-live tracking transition workflow | Major | S8 | Workflow |
| F-30 | No indication which arenas produce data in live mode vs. batch only | Major | S8 | Collection |
| F-31 | Fixed daily collection schedule; no frequency customisation | Minor | S8 | Collection |
| F-32 | Volume spike alerts need in-app notification, not just API/email | Minor | S8 | Monitoring |
| F-33 | Credit estimate has ±50% accuracy; no test mode | Minor | S9 | Cost |
| F-34 | No cumulative cost dashboard across runs | Minor | S9 | Cost |
| F-35 | Tier-to-provider mapping not visible in UI | Cosmetic | S9 | Cost |
| F-36 | Analysis dashboard should default to design-level, not run-level | Minor | S10 | Analysis |
| F-37 | Coordination detection UI integration unclear | Minor | S10 | Analysis |
| F-38 | Export filenames generic; need design name and date range | Cosmetic | S10 | Export |
| F-39 | No batch annotation feature | Minor | S11 | Annotation |
| F-40 | No annotation export for external tools | Minor | S11 | Annotation |
| F-41 | Fixed stance vocabulary; no custom annotation schemas | Minor | S11 | Annotation |

**Summary:** 8 Major, 24 Minor, 9 Cosmetic = 41 total friction points

**Blocker count: 0** -- no functionality is completely broken. All friction points represent workflow inefficiency or missing guidance, not fundamental failures.

---

## Conclusion

The Issue Observatory provides a remarkably comprehensive infrastructure for multi-platform discourse research. For the "socialt bedrageri" scenario, the application successfully supports:
- Creating nuanced boolean query designs with Danish-specific search terms
- Collecting across 12+ FREE-tier arenas with Danish locale defaults
- Discovering new vocabulary through TF-IDF term extraction
- Discovering new sources through cross-platform link mining
- Building actor networks through quick-add, snowball sampling, and entity resolution
- Versioning research designs through cloning with provenance tracking
- Analysing discourse through co-occurrence networks, temporal snapshots, and propagation detection
- Exporting data in multiple formats for external analysis

The primary improvement opportunity is **closing the action gap between discovery and execution**: when the application discovers a relevant term, source, or actor, the researcher should be able to act on that discovery with one click rather than navigating through multiple pages. The secondary opportunity is **temporal transparency**: each arena should clearly communicate what time periods it can cover, so the researcher can make informed decisions about collection strategies.

For a researcher studying "socialt bedrageri", the application would produce valuable multi-platform data within a reasonable budget, but would require approximately 2-3 hours of manual coordination work that could be reduced to 30 minutes with the suggested workflow improvements.
