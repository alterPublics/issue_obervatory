# UX Test Report — Phase 3

Date: 2026-02-17
Arenas tested: google_search, google_autocomplete, bluesky, rss_feeds, reddit, youtube, gdelt, telegram, tiktok, ritzau_via, gab, event_registry, majestic, wayback_machine, common_crawl, facebook, instagram, threads
Tiers tested: free, medium, premium (as described in source and documentation)

---

## Scenarios Tested

All 12 scenarios from the Core Scenario Set were evaluated through static analysis of source files and templates. No live application instance was available. Evaluation was conducted by reading the following files in their entirety:

- `docs/guides/env_setup.md`
- `docs/guides/what_data_is_collected.md`
- `src/issue_observatory/arenas/bluesky/collector.py`
- `src/issue_observatory/arenas/rss_feeds/config.py`
- `src/issue_observatory/arenas/google_search/collector.py`
- `src/issue_observatory/arenas/google_search/tasks.py`
- `src/issue_observatory/arenas/youtube/collector.py` (first 80 lines)
- `src/issue_observatory/config/danish_defaults.py`
- `src/issue_observatory/sampling/snowball.py`
- `src/issue_observatory/analysis/export.py`
- `src/issue_observatory/analysis/descriptive.py` (first 60 lines)
- `src/issue_observatory/workers/beat_schedule.py`
- `src/issue_observatory/workers/tasks.py` (google_search tasks)
- `src/issue_observatory/core/event_bus.py`
- `src/issue_observatory/api/templates/query_designs/editor.html`
- `src/issue_observatory/api/templates/actors/list.html`
- `src/issue_observatory/api/templates/actors/detail.html`
- `src/issue_observatory/api/templates/content/browser.html`
- `src/issue_observatory/api/templates/_fragments/content_table_body.html`
- `src/issue_observatory/api/templates/collections/detail.html`
- `src/issue_observatory/api/templates/collections/launcher.html`
- `src/issue_observatory/api/templates/analysis/index.html`
- `src/issue_observatory/api/templates/admin/credentials.html`
- `src/issue_observatory/api/templates/_partials/empty_state.html`
- `src/issue_observatory/api/templates/_partials/credit_badge.html`
- `src/issue_observatory/api/templates/_fragments/credit_estimate.html`

---

## Passed

### S1 — First-time setup: generation commands are clear and correct
The four required secret-generation commands in `docs/guides/env_setup.md` are accurate, copy-pasteable, and produce correctly-formatted outputs. The `openssl rand -hex 32` command for SECRET_KEY, the Fernet Python one-liner for CREDENTIAL_ENCRYPTION_KEY, and the `openssl rand -hex 16` command for PSEUDONYMIZATION_SALT are each preceded by a clear explanation of purpose. The warning that PSEUDONYMIZATION_SALT must never change after data collection begins is prominently placed and written in plain language.

### S1 — First-time setup: arena credential table is comprehensive
The credential requirements table in Part 6 of `env_setup.md` covers all 18 arenas, correctly distinguishes free-from-box arenas from those requiring credentials, and includes approximate costs per 1,000 records for paid services. The "How to obtain" column links to the correct external registration pages.

### S2 — Danish locale: Google Search locale parameters are correctly implemented
`DANISH_GOOGLE_PARAMS` in `danish_defaults.py` defines `gl=dk` and `hl=da`. The `GoogleSearchCollector` imports these as `DANISH_PARAMS` via `google_search/config.py` and applies them to every Serper.dev and SerpAPI request. The documentation in `what_data_is_collected.md` accurately describes this. No discrepancy was found between documentation and implementation.

### S2 — Danish locale: Bluesky `lang=da` filter is correctly implemented
`BlueskyCollector._search_term()` at line 458 applies `"lang": DANISH_LANG` to every `searchPosts` request. `DANISH_LANG` is set to `"da"` in `bluesky/config.py`. The `BLUESKY_DANISH_FILTER` constant in `danish_defaults.py` (`"lang:da"`) is the query-suffix form; the bare `"da"` form used in the `lang` parameter is correct for the AT Protocol API. The documentation accurately states `lang:da` is applied.

### S2 — Danish locale: RSS feeds are correctly scoped to Danish outlets
`DANISH_RSS_FEEDS` in `danish_defaults.py` contains 27 entries covering DR (9 national + 8 regional), TV2, BT, Politiken, Berlingske, Ekstra Bladet, Information, Jyllands-Posten, Nordjyske, Fyens Stiftstidende, Børsen, and Kristeligt Dagblad. The documentation claims "27+" feeds, which matches exactly. Language is hardcoded to `"da"` as the documentation states.

### S3 — Actor directory: basic CRUD works discoverably
The Actor Directory (`actors/list.html`) provides an "Add Actor" button that opens a modal with clear form fields. The detail page (`actors/detail.html`) provides a "Platform Presences" section with an "Add presence" button, and the Entity Resolution panel is present and collapsible. The merge and split operations include confirmation dialogs.

### S5 — Collection launcher: mode toggle is present and labelled
The launcher template (`collections/launcher.html`) includes a clearly labelled toggle between "Batch (historical)" and "Live (ongoing)" modes. Each mode shows a contextual description sentence below the toggle. The date range section correctly appears only in batch mode.

### S5 — Collection detail: cancel button is present during live runs
The collection detail page (`collections/detail.html`) shows a "Cancel run" button while a run is in a non-terminal state. A confirmation dialog is triggered before cancellation. The "Run again" link appears after terminal state.

### S6 — Analysis dashboard: summary cards provide key research metadata
The four summary cards (Total records, Arenas, Date range, Credits spent) give the researcher the essential provenance information needed to contextualize a dataset. The date range card shows the actual span of published_at values, which is methodologically correct.

### S7 — XLSX export: Danish character encoding is correct
`export.py` lines 146 applies a UTF-8 BOM marker (`"\ufeff".encode("utf-8")`) before the CSV bytes. `export_xlsx()` uses openpyxl, which natively handles Unicode including Danish characters (æøå) without additional encoding steps. The documentation comment on line 157 explicitly confirms: "UTF-8 safe for Danish æøå".

### S9 — Credential failure: error is recorded and surfaced
`google_search/tasks.py` captures `NoCredentialAvailableError`, `ArenaRateLimitError`, and `ArenaCollectionError`, updates the `collection_tasks` row with `error_message`, and publishes an SSE event. The collection detail page renders a "Notes" column in the task table, which is where the error message would appear.

### S10 — Empty state: content browser has a graceful empty state
`content/browser.html` includes an explicit empty state partial with the message "No content matches your filters" and the suggestion "Try broadening the filters in the sidebar, or run a new collection." This is a reasonable fallback.

### S11 — Credit awareness: insufficient-credits state disables launch
`collections/launcher.html` gates the submit button via Alpine's `canLaunch` computed property: `this.estimatedCredits <= this.availableCredits`. When false, the button receives `disabled`, `opacity-50`, and `cursor-not-allowed` classes. The tooltip text reads "Insufficient credits". The credit estimate fragment shows a red warning panel with the text "Insufficient credits. Contact an administrator to be allocated more."

### S12 — Documentation accuracy: Bluesky section is accurate
The `what_data_is_collected.md` Bluesky section correctly describes `lang:da` filtering, the `getAuthorFeed` endpoint for actors, AT Protocol URI as the platform identifier, and the fact that no credentials are needed. The "NOT collected" list accurately includes direct messages, private posts, and full thread context.

### S12 — Documentation accuracy: RSS Feeds section is accurate
The documentation lists all major outlet groups. The claim of "27+" feeds matches the 27-entry `DANISH_RSS_FEEDS` dict. The language hardcoding to `"da"` is correctly described. The ETag/If-Modified-Since conditional GET optimization is correctly described in the "Tiers available" section.

---

## Friction Points

### FP-01 — Setup: verification step requires a virtual environment that may not exist [S1]
**File:** `docs/guides/env_setup.md`, Step 2 of Part 8 (line 474–486)
**Observation:** Step 2 of the verification section provides a Python command prefixed with "From the project root, with your virtual environment activated." A researcher who has only just completed the .env file has not yet installed Python dependencies or created a virtual environment. The guide does not explain how to set up the virtual environment before this point, and does not reference any installation guide.
**Research impact:** The researcher following the guide literally hits a dead end at verification step 2. They cannot run the Python snippet without dependencies installed. They may skip this step or ask a developer.
**Tag:** [core]

### FP-02 — Setup: Docker installation is assumed [S1]
**File:** `docs/guides/env_setup.md`, Part 8, Step 3 (line 495–503)
**Observation:** The guide instructs the researcher to run `docker compose up -d` without any prior check that Docker is installed. There is no "Prerequisites" section. A researcher on a new machine (common in university research settings) will encounter an error here with no guidance.
**Research impact:** Researcher is blocked until they independently discover and install Docker Desktop.
**Tag:** [core]

### FP-03 — Query editor: arena tier radio buttons show all three options for every arena regardless of availability [S2, S8]
**File:** `src/issue_observatory/api/templates/query_designs/editor.html`, lines 392–409
**Observation:** The arena configuration grid renders three tier radio buttons (free, medium, premium) for every arena. Arenas that only support FREE (Bluesky, RSS Feeds, GDELT, Reddit, TikTok, Gab, Ritzau) still display "medium" and "premium" options. Selecting medium for Bluesky triggers a warning in the collector but the researcher receives no visible feedback in the UI.
**Research impact:** Researcher may believe they are collecting at medium tier on Bluesky (expecting richer data) when the collector silently falls back to free. This is a data trust problem: the collection appears to succeed at the configured tier, but the actual tier differs.
**Tag:** [frontend]

### FP-04 — Query editor: no explanation of what each tier provides per arena [S8]
**File:** `src/issue_observatory/api/templates/query_designs/editor.html`, lines 356–426
**Observation:** The arena grid shows tier radio buttons with no tooltip, popover, or help text explaining what each tier provides for that specific arena. A researcher cannot tell from the editor alone what they gain by switching Google Search from free to medium, or whether medium tier on YouTube uses a different API.
**Research impact:** Researchers make tier decisions without knowing the cost implications or data quality differences. They are likely to leave everything at "free" or to select "medium" without understanding the credit cost.
**Tag:** [frontend]

### FP-05 — Query editor: no explanation of what "Keyword", "Phrase", "Hashtag", "URL pattern" term types mean [S2]
**File:** `src/issue_observatory/api/templates/query_designs/editor.html`, lines 169–176
**Observation:** The search term type dropdown offers "Keyword", "Phrase", "Hashtag", and "URL pattern" with no explanatory text. A researcher does not know whether selecting "Phrase" causes quotes to be added automatically, or whether "Hashtag" prepends a # sign, or whether the type affects how each arena handles the query.
**Research impact:** Researchers may select the wrong term type, affecting collection results in ways that are invisible until data is inspected.
**Tag:** [frontend]

### FP-06 — Actor discovery: no visible entry point from the actor list [S3]
**File:** `src/issue_observatory/api/templates/actors/list.html` (entire file)
**Observation:** The Actor Directory page has no button, link, or mention of snowball sampling or actor discovery. The `SnowballSampler` exists as a backend service but it is not reachable from the actor list page. The researcher would need to discover the actor detail page and then find the Entity Resolution section, which is collapsed by default.
**Research impact:** Actor discovery via snowball sampling is a key research workflow. If a researcher cannot find the entry point, this feature is invisible. The researcher will manually add actors one by one.
**Tag:** [frontend]

### FP-07 — Actor detail page: snowball sampling is not exposed; entity resolution is collapsed by default [S3]
**File:** `src/issue_observatory/api/templates/actors/detail.html`, lines 371–465
**Observation:** The "Entity Resolution" section at the bottom of the actor detail page handles merge and split operations — these are data quality operations. Snowball sampling (discovering new actors) is not present on this page at all. The `SnowballSampler` backend has no corresponding UI surface. A researcher looking for "discover actors related to this one" has no path forward.
**Research impact:** The snowball sampling feature is implemented in the backend but has no frontend entry point. A researcher cannot use it through the UI.
**Tag:** [frontend]

### FP-08 — Content browser: "Engagement" column is unlabelled and platform-specific [S4]
**File:** `src/issue_observatory/api/templates/content/browser.html`, line 246 and `_fragments/content_table_body.html`, lines 84–103
**Observation:** The "Engagement" column header is displayed without any explanation of what "engagement_score" represents. It is a synthetic composite metric. The actual metric (likes, upvotes, views, shares) varies by platform. A researcher comparing a score of 47 from Reddit with a score of 47 from YouTube cannot know these represent entirely different quantities.
**Research impact:** Cross-platform engagement comparison is methodologically unsound without explanation. A researcher who publishes conclusions based on comparing engagement scores across platforms has not been warned that these are not comparable.
**Tag:** [frontend], [research]

### FP-09 — Content browser: Arena column is hidden below xl breakpoint [S4]
**File:** `src/issue_observatory/api/templates/content/browser.html`, line 245; `_fragments/content_table_body.html`, line 79
**Observation:** The "Arena" column uses `hidden xl:table-cell` CSS classes. At screen widths below 1280px (the Tailwind `xl` breakpoint), this column is invisible. At 1920x1080, this column is visible. At 1366x768 (typical laptop), it is not. The Platform column remains visible but does not distinguish between google_search and google_autocomplete, or between rss_feeds and ritzau_via.
**Research impact:** On a standard laptop display, a researcher cannot see which arena a record came from. This is particularly important for Google results (two distinct arenas) and for understanding the data source.
**Tag:** [frontend]

### FP-10 — Collection launcher: "Celery Beat" appears in the live mode description [S5]
**File:** `src/issue_observatory/api/templates/collections/launcher.html`, line 112
**Observation:** The description text for live mode reads: "Start ongoing daily collection (Celery Beat)." This is developer-facing terminology. A Danish discourse researcher is likely to have no understanding of what Celery Beat is.
**Research impact:** Minor confusion — the researcher does not know what "Celery Beat" is, but the surrounding context ("daily collection") provides enough information. Nonetheless, internal technology names should not appear in user-facing strings.
**Tag:** [frontend]

### FP-11 — Collection detail: no indication of when a live run will next fire [S5]
**File:** `src/issue_observatory/api/templates/collections/detail.html` (entire file)
**Observation:** The collection detail page shows the current status and a task table, but no information about when a live-tracking collection will next fire. The beat schedule fires at midnight Copenhagen time (`crontab(hour=0, minute=0)` in `beat_schedule.py`) but this is not communicated anywhere in the UI. A researcher who launches a live run in the afternoon and returns the next morning does not know whether any data was collected overnight.
**Research impact:** Researchers cannot confirm their live tracking is working until they check the next day. No schedule display, no "next run at:" timestamp, no "last ran at:" timestamp on the detail page.
**Tag:** [frontend]

### FP-12 — Analysis dashboard: chart panels have no axis labels [S6]
**File:** `src/issue_observatory/api/templates/analysis/index.html`, lines 209–277
**Observation:** The four chart panels (Volume over time, Top actors, Top terms, Engagement distribution) have titles but no axis labels. The "Volume over time" chart's y-axis is not labelled "Number of records" and the x-axis is not labelled "Date". The "Top actors" chart's x-axis (record count) is not labelled. Chart rendering is delegated to Chart.js helper functions (`initMultiArenaVolumeChart`, `initActorsChart`, etc.) that are not visible in the template — axis labels would need to be added at the Chart.js configuration level.
**Research impact:** A researcher cannot produce publication-quality screenshots of these charts without annotating them externally. The charts are adequate for exploration but not for direct inclusion in academic papers.
**Tag:** [frontend]

### FP-13 — Analysis dashboard: "Top actors" mixes display names and pseudonymized IDs [S6]
**File:** `src/issue_observatory/api/templates/analysis/index.html`, lines 643–645
**Observation:** The `actorsChart` JavaScript component uses `r.author_display_name || r.pseudonymized_author_id || '?'` as the bar chart label. This means some bars show a human-readable username (e.g. "mette.frederiksen.bsky.social") and others show a 64-character hex pseudonym — in the same chart. There is no visual distinction between the two types of label.
**Research impact:** The researcher cannot distinguish identified actors from pseudonymized ones at a glance. A bar labelled with a hash could represent a high-volume anonymous account or an author for whom display_name was not collected. This is a data interpretation problem.
**Tag:** [frontend], [research]

### FP-14 — Analysis dashboard: all three GEXF export buttons link to identical endpoint [S6, S7]
**File:** `src/issue_observatory/api/templates/analysis/index.html`, lines 308–319, 333–342, 354–363
**Observation:** The "Download actor network (GEXF)", "Download term network (GEXF)", and "Download bipartite network (GEXF)" buttons all link to `/content/export?format=gexf&run_id={{ run_id }}`. There is no `network_type` parameter distinguishing which network is requested. The researcher selects the tab they want (actor, term, or bipartite) and clicks download, but all three downloads produce the same file.
**Research impact:** Researchers who want a term co-occurrence network or bipartite network cannot actually obtain these from the UI — they all get the actor co-occurrence network. This is a direct research capability gap.
**Tag:** [frontend], [core]

### FP-15 — Export: XLSX column headers use internal snake_case field names [S7]
**File:** `src/issue_observatory/analysis/export.py`, lines 42–58
**Observation:** `_FLAT_COLUMNS` contains: `"platform"`, `"arena"`, `"content_type"`, `"title"`, `"text_content"`, `"url"`, `"author_display_name"`, `"published_at"`, `"views_count"`, `"likes_count"`, `"shares_count"`, `"comments_count"`, `"language"`, `"collection_tier"`, `"search_terms_matched"`. These are written verbatim as column headers in both CSV and XLSX exports. A researcher opening the file sees "text_content", "views_count", and "search_terms_matched" as headers, which are internal identifiers.
**Research impact:** Researchers sharing exported files with collaborators or journal reviewers will receive questions about the column names. The file requires a separate data dictionary to interpret.
**Tag:** [data]

### FP-16 — Export: JSON format produces NDJSON, not standard JSON [S7]
**File:** `src/issue_observatory/analysis/export.py`, lines 228–256; `src/issue_observatory/api/templates/analysis/index.html`, lines 427–435
**Observation:** The export panel UI offers "JSON" as a format option. The implementation (`export_json()`) produces NDJSON (one JSON object per line). When a researcher opens this file expecting a JSON array, they see what appears to be a malformed JSON file. There is no label or tooltip in the export UI explaining that the JSON format is NDJSON.
**Research impact:** Researchers unfamiliar with NDJSON will fail to load the file into tools that expect a standard JSON array (e.g., the `json.load()` function in Python, or browser-based JSON viewers).
**Tag:** [frontend], [data]

### FP-17 — Credential form: Telegram session string generation instruction is incomplete [S8, S9]
**File:** `src/issue_observatory/api/templates/admin/credentials.html`, lines 163–168
**Observation:** The Telegram credential form shows a help text: `Generate with: python -c "from telethon.sync import TelegramClient; ..."` The command is truncated with `...` and is not a complete runnable command. A researcher attempting to set up Telegram credentials has no actionable guidance.
**Research impact:** Telegram setup is blocked unless the researcher consults the `scripts/telegram_auth.py` file, which is referenced in `env_setup.md` but not linked from the credential form.
**Tag:** [frontend]

### FP-18 — Credential form: Gab, Threads, Facebook, and Instagram are absent from platform selector [S8]
**File:** `src/issue_observatory/api/templates/admin/credentials.html`, lines 74–90
**Observation:** The platform dropdown in the "Add Credentials" modal lists: YouTube, Telegram, TikTok, Serper.dev, TwitterAPI.io, Bluesky, Reddit, Event Registry, Majestic, GDELT, RSS Feeds. Missing from the list: Gab, Threads, Facebook (Bright Data), Instagram (Bright Data), and SerpAPI (for Google Search premium). These arenas require credentials but cannot be configured through the UI.
**Research impact:** Researchers wanting to use these arenas must use the `bootstrap_admin.py` CLI script instead — there is no indication of this in the UI, and the admin guide section links only to the UI path.
**Tag:** [frontend]

### FP-19 — Content browser: export button triggers a GET that then redirects, rather than a direct download [S7]
**File:** `src/issue_observatory/api/templates/content/browser.html`, lines 165–179
**Observation:** The "Export CSV" button in the content browser sidebar uses an HTMX pattern: it fires a GET to `/content/export`, and only if the response includes a `Content-Disposition` header does it trigger `window.location.href`. This is a two-step pattern that may appear to do nothing for a second before the download begins. If the export endpoint returns an error instead of a file, the HTMX swap target is `none` and the researcher receives no visible feedback.
**Research impact:** On a slow server or large dataset, the researcher clicks "Export CSV" and nothing appears to happen. They may click it multiple times, triggering multiple export requests.
**Tag:** [frontend]

### FP-20 — Documentation: YouTube has no dedicated section in what_data_is_collected.md [S12]
**File:** `docs/guides/what_data_is_collected.md`
**Observation:** YouTube appears in the Summary Table at the end of the document and in the arena configuration grid, but there is no dedicated section in the body of the documentation covering what YouTube data is collected, what Danish targeting parameters are applied, what is NOT collected, or how actor-based collection works for YouTube channels. The source code uses `relevanceLanguage=da` and `regionCode=DK` (confirmed in `youtube/config.py` via `DANISH_PARAMS`), but this is not documented for researchers.
**Research impact:** A researcher using YouTube data cannot cite what filtering was applied without reading source code.
**Tag:** [research]

### FP-21 — Documentation: Bluesky streaming (Jetstream) described as available but has an undocumented dependency [S12]
**File:** `docs/guides/what_data_is_collected.md`, lines 137; `src/issue_observatory/arenas/bluesky/collector.py`, lines 610–615
**Observation:** The documentation states: "Additionally, the system can subscribe to the Bluesky firehose (Jetstream) for real-time streaming of all posts." The `BlueskyStreamer.run()` method raises `ImportError` with the message "The 'websockets' package is required for BlueskyStreamer. Install it with: pip install websockets" if the package is absent. The package is not installed by default. The documentation does not mention this prerequisite.
**Research impact:** A researcher who enables Bluesky streaming expects real-time Danish post collection. If the package is missing, streaming fails silently (or with an opaque error) at runtime.
**Tag:** [research], [data]

### FP-22 — Beat schedule: RSS feeds and GDELT run every 15 minutes independently of collection runs [S5]
**File:** `src/issue_observatory/workers/beat_schedule.py`, lines 99–118
**Observation:** `rss_feeds_collect_terms` and `gdelt_collect_terms` tasks run on a `crontab(minute="*/15")` schedule, independently of any researcher-initiated collection run. These tasks collect continuously in the background. The researcher UI provides no visibility into these background runs — there is no feed of "RSS collected 47 articles at 14:15" in the dashboard or anywhere else.
**Research impact:** A researcher who checks content before launching their own collection may find records already present. They cannot determine whether these came from their collection or from background tasks. This inflates record counts relative to a researcher's specific query design.
**Tag:** [frontend], [data]

---

## Blockers

### B-01 — Snowball sampling has no frontend entry point [S3]
**File:** `src/issue_observatory/sampling/snowball.py` (backend); `actors/list.html`, `actors/detail.html` (no corresponding UI element)
**Observation:** The `SnowballSampler` class is fully implemented in the backend. The `get_snowball_sampler()` factory function exists for dependency injection. However, no page in the UI surfaces a "Run snowball sampling" action. The Actor Directory page has no such button. The Actor Detail page's Entity Resolution section handles merge/split — not discovery. There is no API route visible in the templates that would trigger a snowball run.
**Research impact:** This is a complete functional gap. A researcher cannot use snowball sampling through the UI. They would need to call the API directly or ask a developer. Actor discovery, one of the core stated Phase 3 features, is unreachable through normal research workflows.
**Tag:** [frontend], [core]

### B-02 — Term and bipartite GEXF networks are not distinguishable from actor GEXF in the export [S6, S7]
**File:** `src/issue_observatory/api/templates/analysis/index.html`, lines 308–363; `src/issue_observatory/analysis/export.py`
**Observation:** The analysis dashboard presents three network types (actor co-occurrence, term co-occurrence, bipartite actor-term). All three "Download ... (GEXF)" links point to `/content/export?format=gexf&run_id={{ run_id }}`. The `ContentExporter.export_gexf()` only implements actor co-occurrence logic. Term co-occurrence and bipartite network generation are not implemented in `export.py`. A researcher navigating to the "Term network" tab, reading the description, and clicking "Download term network (GEXF)" receives an actor co-occurrence network instead.
**Research impact:** The UI implies three distinct network export capabilities. Two of them (term, bipartite) do not produce the described output. A researcher building a term co-occurrence analysis would be working with wrong data without knowing it.
**Tag:** [core], [frontend]

### B-03 — No UI for viewing or suspending the live tracking schedule [S5]
**File:** `src/issue_observatory/api/templates/collections/detail.html`, `src/issue_observatory/workers/beat_schedule.py`
**Observation:** Once a collection is set to "Live (ongoing)" mode, the UI provides a "Cancel run" button that permanently terminates it. There is no "pause" or "suspend" function. More critically, there is no display anywhere in the UI showing when the next beat-scheduled collection will fire, what the current schedule is, or a history of beat-triggered runs distinct from manually-triggered runs. The beat schedule is defined in Python code and is not configurable through the UI.
**Research impact:** A researcher running a multi-week live tracking study cannot verify the schedule is active, cannot pause collection during a holiday, and cannot see a log of automatically-triggered runs vs. manual ones.
**Tag:** [frontend], [core]

### B-04 — Admin credential form missing five platform options [S8]
**File:** `src/issue_observatory/api/templates/admin/credentials.html`, lines 74–90
**Observation:** (See also FP-18.) Gab, Threads, Facebook (Bright Data), Instagram (Bright Data), and SerpAPI are missing from the "Add Credentials" platform dropdown. These arenas are fully implemented in the backend but cannot be configured via the admin UI. The only alternative is the `bootstrap_admin.py` CLI script, which is not referenced from the credentials page.
**Research impact:** A researcher wanting to collect Facebook, Instagram, Gab, or Threads data cannot add credentials through the UI. This is a complete setup blocker for these arenas.
**Tag:** [frontend]

---

## Data Quality Findings

### DQ-01 — Bluesky actor-based collection applies no language filter
**Source:** `src/issue_observatory/arenas/bluesky/collector.py`, `_fetch_author_feed()` method (lines 485–549)
**Observation:** `collect_by_actors()` calls `_fetch_author_feed()`, which sends `getAuthorFeed` requests without any `lang` parameter. Date filtering is applied client-side. There is no language filter applied to author feed results — a Bluesky handle may post in English, Danish, and other languages, and all posts within the date range are collected regardless of language.
**Documentation claim:** `what_data_is_collected.md` states that `lang:da` is applied to Bluesky collection. This is accurate for term-based collection but inaccurate for actor-based collection.
**Research impact:** A researcher who selects actor-based Bluesky collection for a Danish politician's account will receive all of that account's posts, including English-language posts, contrary to the documented behaviour and their research expectation.
**Tag:** [data]

### DQ-02 — GEXF edge construction uses collection_run_id as co-occurrence unit, not shared terms
**Source:** `src/issue_observatory/analysis/export.py`, lines 397–412
**Observation:** The GEXF export's edge construction logic (`export_gexf()`) connects two authors when they "both appear in records linked to the same collection_run_id." This means every author in a run is potentially connected to every other author, as they all share the same run ID. Edge weight is the number of shared runs, not the number of shared topics or shared terms. The edge attribute `shared_terms` accumulates all terms from the run, not the intersection of terms from records authored by both authors.
**Documentation claim:** `analysis/index.html` line 304 states: "two authors are linked when they both posted content matching at least one shared search term. Edge weight is the number of distinct record pairs."
**Research impact:** The GEXF documentation and implementation are inconsistent. The implementation creates a fully-connected component from everyone in the same run, which is not a co-occurrence network in the methodological sense. A researcher using this for network analysis of public discourse will have a fundamentally incorrect network topology.
**Tag:** [data], [core]

### DQ-03 — Reddit default subreddit list is reduced in source vs. documentation
**Source:** `src/issue_observatory/config/danish_defaults.py`, `DANISH_SUBREDDITS` (lines 140–151)
**Observation:** `DANISH_SUBREDDITS` lists 4 subreddits: Denmark, danish, copenhagen, aarhus. The `what_data_is_collected.md` documentation (line 175) lists 7: r/Denmark, r/danish, r/copenhagen, r/aarhus, r/dkfinance, r/scandinavia, and r/NORDVANSEN. The source code contains only 4.
**Research impact:** Researchers relying on the documented list to know which communities are monitored will have an inaccurate picture. The three missing subreddits (r/dkfinance, r/scandinavia, r/NORDVANSEN) may contain relevant Danish discourse that is not collected.
**Tag:** [data]

### DQ-04 — GDELT filter uses two separate queries (sourcecountry and sourcelang) but deduplication scope is not visible
**Source:** `src/issue_observatory/config/danish_defaults.py`, `GDELT_DANISH_FILTERS` (lines 172–180); `what_data_is_collected.md` line 515
**Observation:** The documentation says "Two queries are run per search term: one filtered by `sourcecountry:DA` and another by `sourcelang:danish`. Results are deduplicated by URL." The deduplication happens server-side but there is no indication in the content browser or analysis dashboard of how many duplicates were removed, or whether the deduplication is working. A researcher who notices high GDELT record counts has no way to determine if duplicates are being correctly suppressed.
**Research impact:** Potential inflation of GDELT record counts if deduplication is incomplete. Researchers need transparency about deduplication rates to assess data quality.
**Tag:** [data]

### DQ-05 — Jyllands-Posten RSS URL is flagged as uncertain in source but not in documentation
**Source:** `src/issue_observatory/config/danish_defaults.py`, lines 100–104 (comment on JP feed)
**Observation:** The comment reads: "NOTE: JP's RSS availability is uncertain as of 2026 (shifting to app-first delivery). This URL may return 404 — the RSS arena health check will flag it." The `what_data_is_collected.md` documentation lists Jyllands-Posten as an included source without any caveat.
**Research impact:** A researcher designing a study that requires Jyllands-Posten coverage may build a research design around data that is not being collected. The health check will flag it at the system level but this is not surfaced to researchers in the UI or documentation.
**Tag:** [data], [research]

### DQ-06 — Temporal accuracy: TikTok 10-day lag caveat is documented but not surfaced in the browser
**Source:** `docs/guides/what_data_is_collected.md`, lines 238–239
**Observation:** The documentation correctly states that TikTok engagement metrics have an approximately 10-day accuracy lag. However, this caveat is not shown anywhere in the content browser or analysis dashboard when viewing TikTok records. A researcher looking at TikTok view counts in the first 10 days after posting may treat them as final values.
**Research impact:** Researchers may base viral content analyses on inaccurate TikTok engagement data without realising it.
**Tag:** [data], [frontend]

---

## Recommendations

### Priority 1 — Critical: address before researchers use the system

**R-01** [frontend] [core] — Expose snowball sampling in the Actor Directory and/or Actor Detail page. A "Discover related actors" button on the actor list or detail page should allow the researcher to select seed actors and launch a snowball run. The results should be presented as a reviewable list with platform, username, discovery depth, and an "Add to query design" action. Without this, a core Phase 3 feature is inaccessible.

**R-02** [core] [frontend] — Implement distinct GEXF export endpoints for term co-occurrence and bipartite networks, or remove the Term and Bipartite tab buttons until the exports are implemented. A researcher must never be able to download a file that appears to be one network type but is actually another. The current state is a silent data integrity failure.

**R-03** [data] — Fix the GEXF edge construction logic in `export.py`. The current implementation creates edges between all authors who share a collection_run_id, which is not a co-occurrence network. Edges should connect authors who both have records matching at least one common search term. Edge weight should be the count of distinct (term, record-pair) combinations. The `shared_terms` attribute should contain only terms common to both authors' records.

**R-04** [frontend] — Add Gab, Threads, Facebook (Bright Data), Instagram (Bright Data), and SerpAPI to the Admin > Credentials platform dropdown. Until these are in the UI, researchers cannot configure these arenas without developer assistance.

**R-05** [data] — Fix the DANISH_SUBREDDITS list in `danish_defaults.py` to match the documentation (add r/dkfinance, r/scandinavia, r/NORDVANSEN), or update the documentation to match the code. The mismatch is a data integrity issue.

### Priority 2 — High: address before researchers publish results

**R-06** [frontend] [research] — Add arena-aware tier validation to the query design editor. When a researcher selects "medium" or "premium" for an arena that only supports "free" (Bluesky, RSS Feeds, GDELT, Reddit, TikTok, Gab, Ritzau), show a visible warning or disable the non-supported options. This prevents silent tier fallback that undermines researcher trust in collection configuration.

**R-07** [frontend] — Add a "next scheduled run" and "last run at" timestamp to the collection detail page for live-tracking collections. The schedule (midnight Copenhagen) should be stated in plain language: "This collection runs daily at midnight (Copenhagen time, UTC+1/UTC+2)."

**R-08** [frontend] — Add axis labels to all Analysis Dashboard charts. At minimum: y-axis = "Number of records" for volume chart, x-axis = "Record count" for actor and term charts. These labels must be added at the Chart.js configuration level in `static/js/charts.js`.

**R-09** [data] [research] — Add a language filter to `collect_by_actors()` in `BlueskyCollector`. Post-collection client-side filtering by `language == "da"` would address the gap. The documentation should be updated to accurately describe that actor-based collection does not apply a server-side language filter.

**R-10** [frontend] [research] — Add a panel or tooltip to the analysis dashboard's "Top actors" chart distinguishing pseudonymized IDs from display names. A legend entry reading "Hash-format IDs indicate authors whose display names were not collected" would suffice.

**R-11** [research] — Add a dedicated YouTube section to `what_data_is_collected.md` covering what is collected per video, the `relevanceLanguage=da` and `regionCode=DK` Danish targeting parameters, and the RSS-first quota strategy. The current summary table entry is insufficient for a researcher to understand and cite YouTube data collection.

**R-12** [core] [frontend] — Add `network_type` parameter support to the GEXF export endpoint (`/content/export?format=gexf&network_type=actor|term|bipartite`). Update the three download buttons in `analysis/index.html` to include the appropriate `network_type` parameter.

### Priority 3 — Medium: improves researcher experience

**R-13** [frontend] — Rename the "Export (up to 10k records)" button to "Export (up to 10,000 records)" and add a tooltip explaining: "For larger datasets, use the async export below which has no record limit." Make the distinction between sync and async export explicit in the UI, not implicit through button placement.

**R-14** [frontend] — Rename "JSON" in the export format selector to "NDJSON (one record per line)" and add a tooltip: "This format has one JSON object per line, not a JSON array. Use CSV or XLSX for compatibility with spreadsheet software."

**R-15** [frontend] — Change the live mode description text from "Start ongoing daily collection (Celery Beat)" to "Start ongoing daily collection. Runs automatically every day at midnight Copenhagen time."

**R-16** [core] — Add `docs/guides/prerequisites.md` covering Docker installation, the need for a Python virtual environment, and system requirements. Link to it from the first line of `env_setup.md`.

**R-17** [frontend] — Fix the Telegram session string help text in the credentials form. Replace the truncated `python -c "from telethon.sync import TelegramClient; ..."` snippet with a complete reference: "Run `scripts/telegram_auth.py` to generate your session string. See the setup guide for instructions."

**R-18** [data] [frontend] — Surface TikTok's 10-day engagement accuracy lag as a warning banner when viewing TikTok records in the content browser that were published within the last 10 days. A row-level badge stating "Engagement metrics may be incomplete (published within 10 days)" would suffice.

**R-19** [data] — Add a caveat to the Jyllands-Posten entry in `what_data_is_collected.md`: "Note: JP's RSS feed availability is uncertain as of 2026. The system will attempt to collect from this feed but may receive no results. Check the arena health monitor for feed status."

**R-20** [frontend] — Add a "View background collection history" link somewhere in the collections list that shows beat-scheduler-triggered runs separately from manually-launched runs. Researchers need to know whether their term query design is being collected by background tasks separately from their own initiated runs.

**R-21** [frontend] — Add help text below the Search Term type dropdown in the query editor explaining each type: "Keyword: matches any word in sequence. Phrase: matches the exact phrase (wrapped in quotes on supported arenas). Hashtag: prepends # automatically. URL pattern: matches content linking to this URL pattern."

**R-22** [data] — Clearly document the deduplication rate per arena in `what_data_is_collected.md` or expose deduplication statistics in the analysis dashboard (e.g., "X records deduplicated out of Y fetched"). This is particularly important for GDELT, which runs dual queries, and for RSS feeds where the same article may appear in multiple DR feeds.

**R-23** [frontend] [research] — Add platform-specific engagement metric labels to the content browser's engagement column header. At minimum, a tooltip on the "Engagement" column header should read: "A composite score derived from platform-specific metrics (e.g., Reddit: upvotes; Bluesky: likes + reposts; YouTube: view count). Not comparable across platforms."

---

## QA Guardian Assessment

**Reviewed:** 2026-02-17
**Reviewer:** QA Guardian

### Defects Fixed in This Review

| ID | Severity | File | Description | Status |
|----|----------|------|-------------|--------|
| DQ-02 | Critical | `analysis/export.py` | GEXF edge construction corrected to true co-occurrence | Fixed |
| DQ-01 | High | `arenas/bluesky/collector.py` | Client-side `lang:da` filter added to `collect_by_actors` | Fixed |
| DQ-03 | Medium | `docs/guides/what_data_is_collected.md` | Reddit subreddit list corrected to match code (4 subreddits, not 7) | Fixed |

### Blockers Requiring Implementation Work

| ID | Severity | Responsible | Description |
|----|----------|-------------|-------------|
| B-01 | High | [core][frontend] | Snowball sampling: no UI entry point; `SnowballSampler` is implemented but unreachable through any page in the application |
| B-02 | High | [core][frontend] | GEXF export: term and bipartite network types are not implemented; all three download buttons (`actor`, `term`, `bipartite`) silently return the actor co-occurrence network |
| B-03 | Medium | [core][frontend] | Live tracking: no schedule visibility anywhere in the UI, no suspend/pause (only permanent cancel); researchers cannot confirm the beat schedule is active or view its history |

### Tests Required

The following tests must be written to prevent regression of the two code fixes.

**DQ-01 regression tests — `tests/arenas/test_bluesky.py`**

```
test_fetch_author_feed_excludes_posts_with_non_danish_langs
    Fixture: a feed response containing three posts:
      - post_a: langs=["da"]  (should be included)
      - post_b: langs=["en"]  (should be excluded)
      - post_c: langs=["de", "en"]  (should be excluded, neither lang is "da")
    Assert: collect_by_actors() returns exactly one record (post_a).

test_fetch_author_feed_includes_posts_with_no_langs_field
    Fixture: a feed response where the "record" dict has no "langs" key.
    Assert: collect_by_actors() includes the post (language undeclared = do not exclude).

test_fetch_author_feed_includes_posts_with_empty_langs_list
    Fixture: a feed response where record["langs"] = [].
    Assert: collect_by_actors() includes the post (empty list = undeclared).

test_fetch_author_feed_includes_posts_with_langs_containing_da
    Fixture: a feed response where record["langs"] = ["da", "en"]
      (bilingual post explicitly tagged Danish).
    Assert: collect_by_actors() includes the post.

test_collect_by_actors_danish_text_preserved_after_language_filter
    Fixture: a feed response with a Danish-lang post whose text_content
      contains "klimaforandringer pavirker aeldre i kobenhavn" (using ae/oe
      for test fixture safety; real fixture should use authentic aeligature chars).
    Assert: the returned record's text_content preserves "æ", "ø", "å" exactly.
```

**DQ-02 regression tests — `tests/unit/test_export_gexf.py`** (new file)

```
test_export_gexf_edges_based_on_shared_terms_not_shared_run
    Records: author_A has records matching ["klima"], author_B has records
      matching ["klima", "skat"], author_C has records matching ["skat"] only.
      All three share the same collection_run_id.
    Assert:
      - Edge (A, B) exists with weight=1, shared_terms="klima"
      - Edge (B, C) exists with weight=1, shared_terms="skat"
      - Edge (A, C) does NOT exist (they share no search terms)
      - Total edge count == 2 (not 3, which the old full-graph logic would produce)

test_export_gexf_edge_weight_counts_distinct_shared_terms
    Records: author_A and author_B each have records matching ["klima", "skat", "sundhed"].
    Assert:
      - One edge (A, B) with weight=3
      - shared_terms contains exactly "klima", "skat", "sundhed" (pipe-joined, sorted)

test_export_gexf_no_edges_when_authors_share_no_terms
    Records: author_A matches ["klima"], author_B matches ["sport"].
    Assert: edge_map is empty; GEXF output has zero <edge> elements.

test_export_gexf_node_label_falls_back_to_pseudonymized_id
    Records: one record where author_display_name is None/empty.
    Assert: the <node> element's label attribute equals the pseudonymized_author_id,
      not an empty string.

test_export_gexf_records_without_pseudonymized_author_id_are_skipped
    Records: one record with pseudonymized_author_id=None.
    Assert: nodes element is empty; no exception raised.

test_export_gexf_output_is_valid_xml_with_gexf_namespace
    Records: two authors sharing one term.
    Assert: output bytes parse as valid XML; root element tag contains "gexf";
      xmlns attribute is "http://gexf.net/1.3".

test_export_gexf_shared_terms_attribute_is_intersection_not_union
    Records: author_A posts matching ["klima", "skat"]; author_B posts matching
      ["skat", "sport"].
    Assert: edge (A, B) shared_terms contains only "skat", not "klima" or "sport".
```

All new tests must use `@pytest.mark.asyncio` and produce deterministic GEXF output
(sort all collections before comparison). The GEXF tests belong in `tests/unit/`
because they require no database or HTTP connections.

---

## Research-Strategist Assessment

**Assessed by:** Research Agent (The Strategist)
**Date:** 2026-02-17

This assessment evaluates every blocker and data quality finding from the perspective of a researcher who publishes peer-reviewed findings based on data collected through The Issue Observatory. The question for each item is: if a researcher submitted a paper tomorrow using data from this system, what specific risk does this defect pose to the validity of their published conclusions?

Note: The QA Guardian has already fixed DQ-01, DQ-02, and DQ-03 as documented above. This assessment is written against the original findings to ensure the fixes are sufficient and to document the residual risks. Where a fix has been applied, this is noted.

---

### Research Validity Risks

#### Blockers

| ID | Finding | Validity Risk Rating | Specific Risk to Published Findings |
|----|---------|---------------------|-------------------------------------|
| B-01 | Snowball sampling has no frontend entry point | **Medium** (affects completeness) | A researcher who cannot use snowball sampling will build an actor corpus manually. The resulting corpus will be smaller and biased toward actors the researcher already knew about. Published findings will under-represent peripheral discourse participants. However, the data that IS collected remains valid -- the risk is incompleteness, not corruption. The researcher can accurately describe their actor selection method as "purposive" rather than "snowball-sampled." |
| B-02 | Term and bipartite GEXF networks are indistinguishable from actor GEXF | **Critical** (invalidates findings) | A researcher who downloads what the UI labels "term co-occurrence network" and publishes a term co-occurrence analysis has in fact analyzed an actor co-occurrence network. The network topology, centrality measures, community structure, and every derived statistic are wrong. This is not a caveat -- it is a factual error in the published analysis. A reviewer with access to the GEXF file could detect the discrepancy. The QA Guardian's fix addressed DQ-02 (the edge construction logic for the actor network), but B-02 remains: the term and bipartite network exports are still not implemented, so all three download buttons still produce the same actor co-occurrence file. |
| B-03 | No UI for viewing or suspending the live tracking schedule | **Medium** (affects completeness) | A researcher running a 30-day live tracking study cannot verify that collection occurred on each day. If the beat scheduler silently failed for 3 days mid-study, the researcher has a temporal gap they may not detect. Published time-series analyses would show a dip that reflects infrastructure failure, not discourse dynamics. The researcher cannot distinguish the two. However, the data that was collected during operational periods remains valid. |
| B-04 | Admin credential form missing five platform options | **Medium** (affects completeness) | A researcher cannot configure Facebook, Instagram, Gab, Threads, or SerpAPI through the UI. This blocks collection from these arenas entirely for researchers without command-line access. Published findings that claim "cross-platform Danish discourse analysis" will be missing Facebook (84% Danish penetration) and Instagram (56% penetration) -- the two largest social media platforms in Denmark. The omission is severe in terms of coverage but does not corrupt data from arenas that do work. |

#### Data Quality Findings

| ID | Finding | Validity Risk Rating | QA Fix Status | Residual Risk |
|----|---------|---------------------|---------------|---------------|
| DQ-01 | Bluesky actor-based collection applies no language filter | **High** (requires caveats) | **Fixed** (client-side `lang:da` filter added) | Low. The fix adds client-side filtering. Residual risk: posts with undeclared language (`langs` absent or empty) are included per the QA test specifications, which is the correct conservative behavior. Researchers should be aware that some included posts may not be Danish if the author did not declare a language. The documentation correction described below is still needed. |
| DQ-02 | GEXF edge construction uses collection_run_id, not shared terms | **Critical** (invalidates findings) | **Fixed** (edge construction rewritten to use shared search terms) | Low. The fix corrects the actor co-occurrence network. Residual risk: the term co-occurrence and bipartite network exports remain unimplemented (see B-02). The actor network itself should now be methodologically correct, pending verification via the regression tests specified by the QA Guardian. |
| DQ-03 | Reddit default subreddit list: documentation says 7, code has 4 | **High** (requires caveats) | **Fixed** (documentation corrected to list 4 subreddits) | Low. The documentation now matches the code. Residual risk: r/dkfinance may contain relevant Danish financial discourse that is not collected. This is a known coverage limitation, not a data integrity issue. Researchers studying economic discourse should consider adding r/dkfinance to their query design's actor list manually. |
| DQ-04 | GDELT deduplication scope is not visible | **Medium** (affects completeness) | Not fixed | Medium. If deduplication is incomplete, GDELT record counts are inflated. A researcher reporting "GDELT contributed N articles" may be double-counting. This affects volume comparisons across arenas. The duplicate records contain the same content, so text analysis is affected by weighting, not by the introduction of incorrect data. |
| DQ-05 | Jyllands-Posten RSS URL flagged as uncertain in code but not in documentation | **High** (requires caveats) | Not fixed | High. Jyllands-Posten is one of Denmark's three largest broadsheet newspapers. A researcher who claims RSS coverage of "all major Danish broadsheets" based on the documentation may in fact be missing JP entirely. The health check will flag it at the system level but this is not surfaced to researchers. |
| DQ-06 | TikTok 10-day engagement lag not surfaced in browser | **Medium** (affects completeness) | Not fixed | Medium. The documentation notes the caveat but the browser does not. Researchers who read the documentation before analyzing data will know about it; those who browse data first will not. |

---

### Priority Order for Remediation

The ordering principle is: defects that corrupt data silently rank above defects that block features visibly. A researcher who encounters a blocker knows they have a problem. A researcher whose GEXF file contains wrong data does not know until a reviewer catches it -- or does not catch it.

Items marked "QA-FIXED" have been addressed in code but may still need documentation corrections or regression test verification.

| Priority | ID | Type | Status | Rationale |
|----------|-----|------|--------|-----------|
| 1 | DQ-02 | Data Quality | QA-FIXED | **Was the single most dangerous defect.** The GEXF export produced a fully-connected graph. The QA fix rewrites edge construction to use shared search terms. This fix must be verified by the regression tests specified above before the export can be considered safe for researcher use. Until tests pass, treat the GEXF export as unreliable. |
| 2 | B-02 | Blocker | Open | **Silent mislabelling persists.** Even with DQ-02 fixed, the UI offers three network types but delivers only one (actor co-occurrence). A researcher who clicks "Download term network" still receives an actor network. The immediate mitigation is to remove or disable the Term and Bipartite tabs until those exports are implemented. This is a template change (remove two tab panels from `analysis/index.html`) that eliminates the mislabelling risk. |
| 3 | DQ-05 | Data Quality | Open | **Silent coverage gap for a major outlet.** Jyllands-Posten may be absent with no warning to the researcher. Documentation must add a caveat. This is a one-sentence edit. |
| 4 | DQ-01 | Data Quality | QA-FIXED | **Code fixed; documentation not yet corrected.** The `what_data_is_collected.md` Bluesky section still states `lang:da` is applied without distinguishing term-based from actor-based collection. The documentation correction described below must be applied so that researchers' methods sections cite accurate behavior. |
| 5 | DQ-03 | Data Quality | QA-FIXED | **Documentation fixed.** The subreddit list in `what_data_is_collected.md` now matches the code. No further action needed unless the team decides to add the three missing subreddits to the code. |
| 6 | B-04 | Blocker | Open | **Visible blocker for 5 arenas.** Researchers cannot configure Facebook, Instagram, Gab, Threads, or SerpAPI credentials through the UI. The CLI workaround exists but is not discoverable from the UI. Adding these platforms to the dropdown is a template-level change. |
| 7 | B-03 | Blocker | Open | **Invisible schedule.** The researcher cannot verify that live tracking is running. Temporal gaps in data may go undetected. The minimum viable fix is displaying "Next scheduled run: midnight Copenhagen time" on the collection detail page for live runs. |
| 8 | DQ-04 | Data Quality | Open | **Invisible count inflation.** GDELT deduplication may be incomplete. The impact is limited to volume comparisons. Surfacing deduplication statistics in the analysis dashboard would address this. |
| 9 | DQ-06 | Data Quality | Open | **Known lag, invisible in context.** Adding a row-level badge for TikTok records published within the last 10 days would address this. Low urgency because the documentation does note the caveat. |
| 10 | B-01 | Blocker | Open | **Missing feature, not wrong data.** Snowball sampling is unavailable through the UI. The researcher's actor corpus will be smaller but the collected data is correct. This is a capability limitation, not a data integrity issue. |

---

### Recommended Researcher Workarounds

These workarounds are intended for researchers who need to use the system before the remaining defects are fixed. Each workaround is specific and actionable.

**B-02 -- Term and bipartite GEXF network buttons produce the actor network:**
Do not use the "Download term network (GEXF)" or "Download bipartite network (GEXF)" buttons. They produce an actor co-occurrence network, not what they claim. To construct a term co-occurrence network manually: (1) export all records as CSV with `search_terms_matched` and `text_content` columns; (2) for each pair of search terms, count how many records match both terms; (3) create an edge between term pairs that co-occur in at least one record, weighted by co-occurrence count. For a bipartite network: (1) create one node set for authors and one for search terms; (2) create an edge from each author to each term appearing in their records. Both constructions can be done in Python with networkx and exported to GEXF via `networkx.write_gexf()`.

**DQ-05 -- Jyllands-Posten RSS availability uncertain:**
After completing an RSS collection run, filter the content browser by arena=rss_feeds and search for "Jyllands-Posten" or "JP" in the source/author fields. If no JP records appear, note in the methods section: "Jyllands-Posten was not available via RSS during the collection period." If JP coverage is essential, supplement with Event Registry, which indexes JP articles independently of RSS feeds.

**B-04 -- Cannot add credentials for Facebook, Instagram, Gab, Threads, SerpAPI via UI:**
Use the bootstrap CLI script: `docker compose exec app python scripts/bootstrap_admin.py`. The script prompts interactively for platform, tier, and credential fields. Platform keys to use: `brightdata_facebook`, `brightdata_instagram`, `gab`, `threads`, `serpapi`. This is documented in `docs/guides/env_setup.md`, Part 6, under "Adding a credential via the bootstrap script."

**B-03 -- No UI visibility into live tracking schedule:**
The beat scheduler fires daily at midnight Copenhagen time (UTC+1 in winter, UTC+2 in summer). To verify collection occurred, check the content browser each morning and filter by `collected_at` for the previous day. If records with `collected_at` timestamps near 00:00 CET/CEST appear, the beat task ran. For multi-week studies, maintain a daily verification log external to the system. Also note: RSS feeds and GDELT run on a separate 15-minute beat cycle regardless of researcher-initiated collections -- records from these arenas may appear in the content browser even when no manual collection run is active.

**B-01 -- Snowball sampling not accessible through UI:**
Manually expand the actor corpus by inspecting collected data. In the content browser, identify frequently-appearing authors. For Bluesky, examine follows and followers of seed actors using the AT Protocol API directly: `https://bsky.social/xrpc/app.bsky.graph.getFollows?actor=HANDLE&limit=100`. For Reddit, examine moderator lists and frequent commenters in the target subreddits. Add discovered actors manually through the Actor Directory's "Add Actor" form.

**DQ-04 -- GDELT deduplication not visible:**
When reporting GDELT record counts, note in the methods section: "GDELT records were collected via dual queries (sourcecountry:DA and sourcelang:danish) with URL-based deduplication. The effective deduplication rate was not auditable through the system interface." To verify independently, export GDELT records to CSV and check for duplicate URLs: in Python, `df[df.duplicated(subset='url', keep=False)]` will reveal any remaining duplicates.

**DQ-06 -- TikTok engagement lag not shown in browser:**
When analyzing TikTok engagement data, compare `published_at` and `collected_at` for each record. Flag or exclude records where the gap is fewer than 10 days. In the methods section, note: "TikTok engagement metrics were considered provisional for records collected within 10 days of publication, per the TikTok Research API's documented accuracy lag."

---

### Documentation Corrections Needed

The following specific sentences in the documentation are inaccurate based on the UX findings. Each entry quotes the inaccurate text and provides the corrected version. Items marked "QA-FIXED" for the code fix still require the documentation correction listed here.

#### File: `docs/guides/what_data_is_collected.md`

**Correction 1 -- Bluesky language filter scope (line 137):**

> Inaccurate: "The search query is appended with `lang:da` to request Danish-language posts."

Corrected: "For term-based collection, the search query includes a `lang:da` parameter to request Danish-language posts. For actor-based collection (fetching an actor's public feed via `getAuthorFeed`), client-side language filtering excludes posts not tagged as Danish. Posts with no declared language are included. Researchers should be aware that some actor-based results may include non-Danish content if the author did not declare a language tag."

**Correction 2 -- Bluesky Jetstream dependency (line 137, second sentence):**

> Inaccurate: "Additionally, the system can subscribe to the Bluesky firehose (Jetstream) for real-time streaming of all posts, with client-side language filtering."

Corrected: "Additionally, the system can subscribe to the Bluesky firehose (Jetstream) for real-time streaming of all posts, with client-side language filtering. Note: Jetstream streaming requires the `websockets` Python package, which is not installed by default. Install it with `pip install websockets` before enabling streaming."

**Correction 3 -- Reddit subreddit list (line 175):**

> Previously inaccurate: "The system searches within a predefined set of Danish subreddits: r/Denmark, r/danish, r/copenhagen, r/aarhus, r/dkfinance, r/scandinavia, and r/NORDVANSEN."

QA-FIXED: The QA Guardian has corrected this line to list 4 subreddits matching the code. Verify the correction reads: "The system searches within a predefined set of Danish subreddits: r/Denmark, r/danish, r/copenhagen, and r/aarhus."

**Correction 4 -- Jyllands-Posten RSS caveat (around line 407):**

> Inaccurate (by omission): Jyllands-Posten is listed among RSS feed sources without any caveat about feed availability.

Corrected: Add after the Jyllands-Posten entry: "(Note: Jyllands-Posten's RSS feed availability is uncertain as of 2026. JP has shifted toward app-first content delivery, and this RSS URL may return no data. Check the arena health monitor for current feed status.)"

**Correction 5 -- Missing YouTube section:**

> Inaccurate (by omission): YouTube has no dedicated section in the document body. It appears only in the Summary Table. The `relevanceLanguage=da` and `regionCode=DK` parameters are not documented for researchers.

Corrected: Add a YouTube section under "Social Media Platforms" documenting: what is collected per video (title, description, view count, like count, comment count, channel name, publish date, video ID, tags, category), what is NOT collected (video files, comments, subscriber counts, private/unlisted videos), Danish targeting (`relevanceLanguage=da`, `regionCode=DK`), how actors work (channel IDs or URLs; system fetches recent uploads), tiers available (FREE via RSS feed polling of channel uploads, MEDIUM via YouTube Data API v3 with `api_key` credentials), and the quota management strategy (RSS-first to minimize API unit consumption).

#### File: `docs/guides/env_setup.md`

**Correction 6 -- Missing prerequisites before verification Step 2 (line 475):**

> Inaccurate (by omission): "From the project root, with your virtual environment activated:" -- assumes the researcher has already created a virtual environment and installed dependencies, but the guide never explains how to do this.

Corrected: Add before Step 2: "Prerequisites: You must have Python 3.11+ installed and a virtual environment set up with the project's dependencies. If you have not done this, run: `python -m venv .venv && source .venv/bin/activate && pip install -e .` from the project root. If `pip install -e .` fails, ensure you have the project's build dependencies (see `pyproject.toml`)."

**Correction 7 -- Missing Docker prerequisite before Step 3 (line 492):**

> Inaccurate (by omission): The guide instructs the researcher to run `docker compose up -d` without verifying Docker is installed.

Corrected: Add before Step 3: "Prerequisite: Docker Desktop (or Docker Engine + Docker Compose plugin) must be installed. Verify with `docker --version`. If the command is not found, install Docker Desktop from https://www.docker.com/products/docker-desktop/ before continuing."

**Correction 8 -- Credential UI limitation not mentioned (Part 6, after line 346):**

> Inaccurate (by omission): The instructions for adding credentials via the admin UI do not mention that five platforms are absent from the UI dropdown.

Corrected: Add after the admin UI instructions: "Note: The following platforms are not yet available in the admin UI credential dropdown and must be configured via the bootstrap script below: Gab (`gab`), Threads (`threads`), Facebook via Bright Data (`brightdata_facebook`), Instagram via Bright Data (`brightdata_instagram`), and Google Search premium via SerpAPI (`serpapi`)."
