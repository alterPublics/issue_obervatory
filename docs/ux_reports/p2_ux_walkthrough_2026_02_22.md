# P2-11 UX Researcher Walkthrough Report

**Date:** 2026-02-22
**Evaluator:** UX Research Agent (Danish discourse researcher perspective)
**Method:** Static code review of all templates, routes, Alpine.js components, and application JavaScript
**Scope:** Seven core researcher workflows evaluated against the actual codebase
**Application state:** Not running; evaluated by reading source code

---

## Executive Summary

The Issue Observatory has an ambitious and well-structured interface design. The template architecture shows thoughtful attention to research workflows: progressive disclosure in the query design editor, clear tier labeling, research lifecycle indicators, and collapsible source-list configuration panels. The navigation sidebar uses plain English labels that a researcher would understand, and the overall information hierarchy is sound.

However, the application has **systemic routing and integration problems** that prevent most workflows from functioning end-to-end. Previous evaluation reports (2026-02-20 comprehensive evaluation, 2026-02-22 sidebar audit, 2026-02-22 fix verification) have documented many of these issues, and the fixes attempted so far have introduced regressions of comparable severity. As of this review, **a researcher cannot complete a single full workflow** from query design through collection to analysis and export without encountering at least one blocking error.

Beyond the routing breakage, this report identifies friction points and design problems that would persist even after all bugs are fixed. These are the issues that determine whether a researcher will trust the tool enough to use it in published research.

---

## Workflow 1: First-Time Setup and Dashboard Orientation

### What the researcher experiences

A new researcher arrives at the login page (`/auth/login`). The page is clean and branded ("Issue Observatory -- Danish media monitor -- Aarhus University"). The login form uses a Danish university email as the placeholder (`forsker@ku.dk`), which is a small but effective signal that this tool is built for Danish academic researchers. Error messages for bad credentials are clear ("Incorrect email or password"), and the pending-activation message explains what to do next.

After login, the researcher reaches the dashboard. The layout is a standard three-column summary card row plus a recent collections panel plus quick links. The welcome message personalizes with the user's display name.

### Passed

- **Login flow design** is clear and well-labeled. Session expiry banner, pending activation notice, and inline error handling are all implemented with plain language. `[frontend]`
- **Sidebar navigation** uses research-appropriate labels: "Query Designs" (not "Projects"), "Content" (not "Records"), "Actors" (not "Entities"). The "Tools" and "Administration" sections are visually separated, which correctly signals they are secondary. `[frontend]`
- **Dashboard quick actions** point to the right places conceptually: "Create new query design", "Start new collection", "Browse content", "Analyse data". `[frontend]`
- **"About this platform" card** gives a one-sentence description that a researcher would understand: "Issue Observatory collects and analyses public discourse across digital media arenas with a focus on the Danish context." `[frontend]`

### Friction Points

- **F-DASH-1: "Records Collected" card polls /content/count endpoint.** The Alpine.js component tries to fetch a JSON count from `/content/count`. If this endpoint does not exist or returns an unexpected format, the card silently shows a dash forever. There is no loading indicator beyond the initial em-dash, and no error state. A researcher would see "---" and not know whether the system has no data or is broken. The card should show "0 records" when the database is empty, not a typographic dash. `[frontend]`

- **F-DASH-2: Volume spike alerts container uses hidden class with hx-on::after-swap logic.** The previous audit (2026-02-22 visual audit) identified that the original Alpine x-data/x-init approach was broken. The current code uses `hx-on::after-swap` to conditionally unhide the container. This is an improvement, but the behavior is still opaque: if the HTMX request fails or returns empty HTML, the div stays hidden with no indication that volume spike monitoring exists. A researcher who has never seen a volume spike will not know this feature is available. Consider always showing a "Volume Spikes" section with a "No recent spikes detected" message when empty. `[frontend]`

- **F-DASH-3: Recent Collections panel uses format=fragment query parameter.** The HTMX request to `/collections/?limit=5&format=fragment` assumes the collections list route supports a fragment rendering mode. If the route does not recognize `format=fragment` and returns the full page HTML, the dashboard will show a duplicated collections page inside the Recent Collections card. The sidebar audit (2026-02-22) confirmed this causes a 500 error due to the `format_number` filter issue. A researcher sees a loading spinner that never resolves. `[core]`

### Blockers

- **B-DASH-1: All dashboard action links lead to broken pages.** The sidebar audit confirmed that `/query-designs/new` returns 422 (UUID parsing), `/collections/new` returns 422, `/content` returns 404 (trailing slash mismatch), `/collections` returns 500, and `/analysis` returns 404. A researcher who logs in successfully is immediately trapped on the dashboard with no functional next step. `[core]`

---

## Workflow 2: Query Design Creation

### What the researcher experiences

The query design editor (`/query-designs/new` and `/query-designs/{id}/edit`) is the most complex page in the application. It contains a metadata form, a search terms panel with single/bulk add modes, an actor list panel with single/bulk add and inline platform presence forms, an arena configuration grid with per-arena tier selection, a multi-language selector, and five source-list configuration panels (RSS, Telegram, Reddit, Discord, Wikipedia).

### Passed

- **P-QD-1: Metadata form is clean and well-labeled.** The five fields (Name, Description, Visibility, Default Collection Tier, Primary Language) are presented in a logical order. The placeholder text ("e.g. Climate debate DK 2024") gives a concrete example that matches real research. The visibility field explanatory text ("Public designs are visible to all users, but only you can edit them") is clear. `[frontend]`

- **P-QD-2: Tier labels use researcher language.** "Free -- free data sources only", "Medium -- low-cost paid services", "Premium -- best available" avoids developer jargon. `[frontend]`

- **P-QD-3: Search term types have helpful tooltips.** The title attribute on the term type dropdown explains each option in plain terms: "Keyword: matches anywhere in text; Phrase: matches exact multi-word phrase; Hashtag: matches #-prefixed tag; URL pattern: matches web addresses". The inline help text below the form reinforces these definitions. `[frontend]`

- **P-QD-4: Bulk import formats are well-documented.** Both the term bulk import and actor bulk import panels include clear format explanations with concrete Danish examples (e.g., "Lars Lokke Rasmussen | person", "Socialdemokratiet | political_party", "ytringsfrihed | keyword | Danish terms | bluesky,reddit"). This reduces trial-and-error significantly. `[frontend]`

- **P-QD-5: Group autocomplete suggestions match research concepts.** The datalist suggests "Primary terms", "Discourse associations", "Actor discovery terms", "English variants", "Related concepts" -- all of which reflect how a discourse researcher actually organizes search terms. `[research]`

- **P-QD-6: Arena configuration grid has credential status indicators.** The green/gray dot next to each arena name tells the researcher whether the required API key is configured before they try to collect. The tooltip "Credentials not configured -- this arena will be skipped during collection" is actionable. `[frontend]`

- **P-QD-7: Source-list arena panels have clear setup instructions.** Each panel (RSS, Telegram, Reddit, Discord, Wikipedia) includes specific examples relevant to Danish research. The RSS panel suggests Greenlandic feeds (`sermitsiaq.ag/rss`, `knr.gl/da/rss.xml`), which shows genuine attention to the Danish/Greenlandic research context. `[research]`

- **P-QD-8: Clone functionality is discoverable.** The "Clone" button appears both on the list page and on the detail/edit pages, with a confirmation dialog that names the design being cloned. The provenance note ("Cloned from: [link]") maintains research traceability. `[frontend]`

### Friction Points

- **F-QD-1: Create flow requires two saves.** The "New Query Design" form has a "Create Query Design" button for the metadata. Only after this initial save can the researcher add search terms, configure arenas, or add actors (these sections are gated behind `{% if is_edit %}`). This two-step flow is not explained upfront. A researcher arriving at the create page might expect to fill everything in and save once. The form should either explain "Create the design first, then add terms and configure arenas" or allow single-step creation. `[frontend]`

- **F-QD-2: Per-arena term scoping uses platform_name identifiers.** The arena scoping checkboxes in the term add form display `arena.platform_name` (e.g., `google_search`, `rss_feeds`, `x_twitter`). These are developer identifiers, not human-readable labels. A researcher does not think of Twitter as "x_twitter" or RSS feeds as "rss_feeds". The template should display `arena.label` (the human-readable name) with `platform_name` as a hidden value. `[frontend]`

- **F-QD-3: Actor type list mixes familiar and unfamiliar categories.** The actor type dropdown includes 11 options ranging from "Person" and "Organization" (universally understood) to "Teachers' union" (very specific to Danish education research). While the specificity is valuable, a first-time user might be confused by the mix of generic and domain-specific types. Brief parenthetical descriptions would help: "Teachers' union (e.g., DLF, GL)". `[frontend]`

- **F-QD-4: Actor type badge in the list handles only 3 of 11 types.** The Jinja2 template for the actor row in the editor checks for `person`, `organisation` (British spelling), and `media_outlet`. All other 8 types (political_party, educational_institution, etc.) display as "Account", which is misleading. The actor type dropdown correctly uses "organization" (American spelling), but the display badge checks "organisation" -- so even organization-type actors will show as "Account". `[frontend]`

- **F-QD-5: "AI-Powered Discovery" promotional section is placed between search terms and actor list.** This interrupts the logical flow of the editor. The section is visually prominent (gradient background, icon) but its instructions ("Run a collection with a broad query like 'suggest 20 related terms for [your topic]'") require the researcher to leave the editor, configure the AI Chat Search arena, run a collection, review results, and then return. This workflow is not a natural part of query design editing. The section would be better placed on the query design detail page or the explore page. `[frontend]`

- **F-QD-6: Language selector defaults crash when arenas_config is empty.** Line 1051 of the editor template accesses `design.arenas_config.get('global', {}).get('languages', ['da'])`. When `arenas_config` is `None` (which is the default for a new design), the `or {}` fallback handles the None case, but the fix verification report (2026-02-22) confirmed that when `arenas_config` is an empty dict `{}`, accessing `.global` still crashes with an UndefinedError. This means the editor page fails to render for any design that has not had its arena config explicitly saved with a `global` key. `[core]`

- **F-QD-7: Arena configuration grid fetches arenas from /api/arenas/ but the Explore page arena fetch was broken.** The sidebar audit found that the Explore page's arena fetch references `data.arenas.filter(...)` but the API returns a flat array. The same pattern may affect the editor's `arenaConfigGrid` Alpine component. If the component handles the response format correctly, this is fine, but if it has the same `data.arenas` assumption, the grid will never populate. `[frontend]`

### Blockers

- **B-QD-1: Editor page crashes for most existing designs.** As confirmed by the fix verification report, the editor template throws a Jinja2 UndefinedError when `arenas_config` does not contain a `global` key. Any design created through the API or through the create form (which does not set `arenas_config.global`) will fail to load in the editor. `[core]` `[frontend]`

- **B-QD-2: /query-designs/new returns 422 due to route wildcard.** The priority_router fix introduced a `{design_id:uuid}` wildcard that intercepts literal paths like "new". The fix verification report confirmed this. A researcher clicking "New Query Design" from the dashboard or the list page sees a cryptic 422 error. `[core]`

---

## Workflow 3: Arena Selection and Tier Configuration

### What the researcher experiences

Arena configuration is embedded within the query design editor as a dynamic table. Each row shows an arena name, credential indicator, enabled toggle, tier radio buttons, and estimated credits.

### Passed

- **P-AR-1: Tier radio buttons visually disable unsupported tiers.** Arenas that only support FREE tier correctly gray out the MEDIUM and PREMIUM radio buttons. The tooltip on disabled tiers explains why they are unavailable. This prevents a researcher from selecting an impossible configuration. `[frontend]`

- **P-AR-2: Google Search amber badge is clear.** The "Requires MEDIUM+ tier" badge on Google Search and Google Autocomplete arenas prevents a common mistake (enabling Google arenas at FREE tier where no API is available). `[frontend]`

- **P-AR-3: Source-list arenas have a "Config" badge.** The amber gear icon with "Config" text indicates which arenas require additional setup. The info box below the grid explains what to do. `[frontend]`

- **P-AR-4: "Enable all" / "Disable all" buttons reduce clicks.** For a researcher who wants to cast a wide net, the "Enable all" button saves individually toggling 25 arenas. `[frontend]`

- **P-AR-5: Dedicated arenas overview page is well-structured.** The `/arenas` page organizes all arenas by tier (Free, Medium, Premium) with narrative descriptions of what each arena category covers ("News & Mainstream Media", "Social Media Platforms", "Fringe & Alternative Platforms", "Web Archives & Search"). This helps a researcher understand the platform landscape before making configuration decisions. `[research]`

### Friction Points

- **F-AR-1: Arena names in the grid show both label and platform_name.** The grid shows the human-readable label (e.g., "Google Search") and below it the machine identifier in monospace ("google_search"). While the label is prominent, the monospace identifier is visual noise for a researcher. Platform identifiers only matter for developers or for the per-arena term scoping. Consider hiding the platform_name behind a "show technical details" toggle. `[frontend]`

- **F-AR-2: No arena-level description visible without hovering.** The arena description is truncated to a single line with a tooltip for the full text. On a 25-row table, researchers must hover over each arena to understand what it collects. A brief always-visible description (even just the arena_name grouping like "Social Media" or "News Media") would help. `[frontend]`

- **F-AR-3: Credit estimate relies on an endpoint that may be broken.** The estimate trigger posts to `/collections/estimate`. The sidebar audit confirmed that `/collections/estimate` is intercepted by the wildcard `{run_id}` route and returns a 422 UUID parsing error. If this is the case, the credit estimate column in the arena grid will never populate, and the researcher has no visibility into costs before launching. `[core]`

- **F-AR-4: Tier precedence explanation is hidden behind a details element.** The "Which tier will be used?" expandable on the collection launcher is an important concept (per-arena tier overrides, global tier, design default), but it is collapsed by default. A researcher who does not notice this disclosure may not understand why a collection used a different tier than expected. `[frontend]`

### Blockers

- **B-AR-1: Arena configuration grid save may not persist correctly.** The "Save Arena Config" button posts to `/query-designs/{design_id}/arena-config`. If this route exists and works, configuration is saved. But the editor page crash (B-QD-1) means the researcher cannot even reach the arena grid on existing designs. `[core]`

---

## Workflow 4: Collection Launch

### What the researcher experiences

The collection launcher (`/collections/new`) is a two-panel layout: configuration form on the left, credit estimate on the right. The form includes a query design selector, batch/live mode toggle, date range fields (batch only), and tier radio buttons.

### Passed

- **P-CL-1: Batch vs. Live mode toggle is clear.** The segmented control with explanatory text ("Collect data for a specific time period" vs. "Runs automatically every day at midnight Copenhagen time") uses research language, not cron syntax. `[frontend]`

- **P-CL-2: Date range coverage notes are genuinely useful.** The blue info box listing per-arena date coverage ("RSS Feeds: Real-time only -- typically last 24-48 hours", "GDELT: Historical coverage available -- years of data", "Bluesky: Last 30 days via search API") is one of the most valuable pieces of the interface. This information directly affects research methodology decisions and is rarely communicated in data collection tools. `[research]`

- **P-CL-3: Credit estimate panel updates on form changes.** The debounced 400ms estimate request gives responsive feedback as the researcher adjusts settings. The "Insufficient credits" disabled state on the launch button prevents accidental overspending. `[frontend]`

- **P-CL-4: No query designs yet state is handled.** When the researcher has no query designs, the form shows a yellow notice with a direct link to create one, rather than an empty dropdown with no explanation. `[frontend]`

- **P-CL-5: Preselection from query design detail works.** The `?design_id=` query parameter auto-selects the design in the dropdown and triggers the estimate, creating a smooth transition from "I want to collect data for this design" to the launcher. `[frontend]`

### Friction Points

- **F-CL-1: Date fields have no defaults.** The From and To date inputs are empty by default. A researcher might expect "last 7 days" or "last 30 days" as a sensible default, or at least today's date in the "To" field. Empty dates raise the question: if I leave these blank, does the system collect everything? The coverage notes mention per-arena limits but do not explain what happens when no dates are specified. `[frontend]`

- **F-CL-2: Tier selection on the launcher vs. in the design is confusing.** The researcher has already set a "Default Collection Tier" on the query design, and may have configured per-arena tiers in the arena grid. Now the launcher presents yet another tier selector. The tier precedence explanation is available but collapsed. A researcher who configured everything carefully in the design editor may not understand why they are being asked to choose a tier again. `[frontend]`

- **F-CL-3: No summary of what will be collected.** The launcher shows the query design name and the tier, but does not summarize the number of search terms, number of enabled arenas, or list of actors. The researcher is launching a collection without a final confirmation of scope. A "You are about to collect data from 8 arenas using 12 search terms" summary would increase confidence. `[frontend]`

### Blockers

- **B-CL-1: /collections/new returns 422 (route wildcard issue).** Same as B-QD-2. The researcher cannot reach the launcher page. `[core]`

- **B-CL-2: Credit estimate endpoint returns 422.** The estimate request posts to `/collections/estimate`, which is intercepted by the wildcard route. The researcher has no cost information before launching. `[core]`

---

## Workflow 5: Results Review (Content Browser)

### What the researcher experiences

The content browser (`/content`) is a two-column layout with a filter sidebar and a paginated content table. Clicking a row opens a detail panel on the right. Filters include full-text search, arena checkboxes, date range, language, collection mode, collection run, and search term matched.

### Passed

- **P-CB-1: Filter sidebar is comprehensive and well-organized.** The seven filter categories cover the dimensions a researcher would care about: what platform, when, what language, which collection, which search term. The order (search first, then arena, then date, then language) follows natural research priority. `[frontend]`

- **P-CB-2: Arena filter populates dynamically.** The Alpine component fetches arena names from `/api/arenas/`, so the filter stays current as new arenas are added. No hardcoded arena list. `[frontend]`

- **P-CB-3: Engagement score tooltip explains limitations.** The column header tooltip reads "Composite engagement score (likes + shares + comments). Not comparable across platforms -- each platform weights metrics differently." This is an essential methodological caveat that most tools omit. `[research]`

- **P-CB-4: 2000-row cap is clearly communicated.** The yellow banner when the cap is reached ("Display capped at 2,000 rows. Export CSV to download all matching records.") explains the limitation and offers the workaround inline. `[frontend]`

- **P-CB-5: Quick-add actor from content is a smart workflow.** The author name in each row is clickable and opens a quick-add dialog. This supports the common research pattern of "I found an interesting actor in my data, now I want to track them." `[research]`

- **P-CB-6: Infinite scroll with sentinel row.** The content table loads incrementally as the researcher scrolls, avoiding a long initial page load. The loading spinner in the sentinel row provides visual feedback. `[frontend]`

### Friction Points

- **F-CB-1: Arena filter shows arena_name instead of platform_name labels.** The arena checkbox labels use `arena.arena_name` (e.g., "social_media", "news_media") rather than `arena.platform_name` (e.g., "reddit", "youtube") or a human-readable label. This means a researcher sees grouping labels like "social_media" repeated multiple times rather than specific platform names. The filter should show individual platform names or human-readable labels. `[frontend]`

- **F-CB-2: Language filter is limited to three options.** The dropdown offers "All languages", "Danish (da)", "English (en)", and "German (de)". But the system supports 7+ languages (including Greenlandic, Swedish, Norwegian, Russian). A researcher working with Greenlandic content cannot filter for it. The language dropdown should match the language options available in the query design editor. `[frontend]`

- **F-CB-3: Collection run dropdown shows truncated names with dates.** The run selector truncates the query design name to 24 characters and the date to 10 characters, producing cryptic entries like "Test Gron Omstilling... (2026-02-1...)". A researcher with many runs for similar designs cannot distinguish between them. Including the tier and a record count would help. `[frontend]`

- **F-CB-4: Search term filter depends on an endpoint that may not exist.** The search term dropdown uses `hx-get="/content/search-terms"` to populate options when a collection run is selected. The comprehensive evaluation (2026-02-20) listed the missing `GET /content/search-terms` endpoint as M-FE-5. If this endpoint does not exist, the search term filter is non-functional, and the researcher sees an empty dropdown with no error message. `[core]`

- **F-CB-5: Export button implementation is fragile.** The CSV export button uses a complex two-step approach: first an HTMX GET to check for the Content-Disposition header, then a JavaScript redirect to the same URL. If the first request fails or does not include the header, the download silently does not happen. The researcher clicks "Export CSV" and nothing visible occurs. A simpler direct download link would be more reliable. `[frontend]`

- **F-CB-6: Published date shows raw ISO timestamp.** The "Published" column displays the timestamp truncated to 16 characters, yielding something like "2026-02-15T14:32". This is not a human-friendly date format. A researcher would expect "15 Feb 2026, 14:32" or similar localized format. `[frontend]`

### Blockers

- **B-CB-1: /content returns 404 due to trailing slash mismatch.** The sidebar audit confirmed that navigating to `/content` returns 404 because `redirect_slashes=True` in main.py was previously `False`, and the nav links to `/content` without trailing slash. The fix verification report indicates `redirect_slashes=True` was set, which should resolve this, but the content route handler needs to be mounted at the correct path. `[core]`

---

## Workflow 6: Export

### What the researcher experiences

Export is available from two locations: the content browser sidebar (CSV export) and the analysis dashboard export panel (CSV, XLSX, NDJSON, Parquet, GEXF, RIS, BibTeX).

### Passed

- **P-EX-1: Analysis export panel offers seven formats.** CSV, XLSX, NDJSON, Parquet, GEXF, RIS, and BibTeX cover the major needs: spreadsheet analysis (CSV/XLSX), programmatic processing (NDJSON/Parquet), network visualization (GEXF), and citation management (RIS/BibTeX). `[research]`

- **P-EX-2: GEXF export includes network type selection.** When GEXF is selected, a fieldset appears with radio buttons for "Actor co-occurrence", "Term co-occurrence", and "Bipartite (actor-term)". This directly maps to common network analysis approaches. `[research]`

- **P-EX-3: Async export for large datasets.** The "Export async (large dataset)" button acknowledges that large collections may take time and provides a job ID with status tracking. `[frontend]`

- **P-EX-4: Network sections include "Export to GEXF" inline.** Each network tab (actor co-occurrence, term co-occurrence, bipartite) has a direct GEXF download link, so the researcher does not need to scroll to the separate export panel. `[frontend]`

### Friction Points

- **F-EX-1: Export format names assume technical knowledge.** "NDJSON" and "Parquet" are developer-oriented format names. A researcher who works primarily in R or Python might recognize them, but many discourse researchers use SPSS, NVivo, or Excel. Adding brief descriptions ("NDJSON -- newline-delimited JSON for Python/R processing", "Parquet -- columnar format for large datasets in Python/R") would help. `[frontend]`

- **F-EX-2: No export preview.** The researcher clicks "Export" and receives a file, but has no preview of what columns will be included or how the data is structured. A "Preview first 5 rows" feature or a column list would help researchers verify the export meets their needs before downloading a potentially large file. `[frontend]`

- **F-EX-3: engagement_score is missing from flat exports.** The comprehensive evaluation (2026-02-20, M-AN-2) found that `engagement_score` is absent from the `_FLAT_COLUMNS` list in `export.py`. A researcher who sees engagement scores in the browser will not find them in the CSV export, with no warning about the discrepancy. `[data]`

- **F-EX-4: RIS/BibTeX export context is unclear.** These citation formats are available in the export dropdown, but the analysis page does not explain when a researcher would use them. The typical use case is citing specific content items in a publication, but the export appears to cover an entire collection run (up to 10k records). Citing 10,000 items is unusual. The interface should clarify whether this exports citations for all records or allows selecting specific records for citation. `[frontend]`

### Blockers

- **B-EX-1: Analysis dashboard template had a Jinja2 syntax error.** The comprehensive workflow test (2026-02-22) found that the JSDoc comment `{{ nodes: Array, edges: Array }}` in the analysis template caused a compile error. The fix verification report confirmed this was fixed with `{% raw %}...{% endraw %}`. If this fix holds, the export panel on the analysis page is accessible. But the analysis page itself requires a completed collection run, which requires a working launcher, which is currently blocked. `[core]`

---

## Workflow 7: Error Messages and Recovery

### What the researcher experiences

Errors can occur at many points: login failures, missing credentials, collection failures, rate limits, API key expiry, and template rendering errors.

### Passed

- **P-ER-1: Login error messages are specific and actionable.** "Incorrect email or password" (not "Authentication failed"), "Your account is pending activation by an administrator" (with explanation), "Your session has expired. Please sign in again." (with redirect back to original page). `[frontend]`

- **P-ER-2: Flash message system supports four severity levels.** Success (green), error (red), warning (amber), info (blue) with dismissible banners. Query-param flash fallback allows server redirects to communicate status without sessions. `[frontend]`

- **P-ER-3: Collection detail page has clear suspend/resume/cancel actions.** Each button includes explanatory text: "Suspend pauses daily collection without deleting your data. Cancel permanently ends the run." The confirmation dialogs explain consequences before the action is taken. `[frontend]`

- **P-ER-4: Explore page has a structured error display.** The red error banner shows "Exploration failed" with the error message and a close button. The structure (icon, title, message, dismiss) is consistent across the application. `[frontend]`

- **P-ER-5: Credential management page explains write-only security.** "Encrypted credential pool -- values are never shown after creation" sets correct expectations. The researcher understands that they cannot retrieve a key after adding it. `[frontend]`

### Friction Points

- **F-ER-1: Arena configuration grid fetch error is a bare string.** When the arena list fetch fails, the error state shows `x-text="_loadError"` -- whatever error message the JavaScript catch block produces. This could be a network error, a JSON parse error, or a 500 stack trace. The error should be translated to researcher language: "Could not load the list of available arenas. Check your connection and try refreshing the page. If the problem persists, contact your administrator." `[frontend]`

- **F-ER-2: HTMX 401 handler redirects silently.** When a session expires during an HTMX partial request (e.g., while adding a search term), the global handler in `app.js` redirects to the login page. The researcher loses any unsaved work in the current form without warning. An intercepting dialog ("Your session has expired. Save your work and sign in again.") would be safer. `[frontend]`

- **F-ER-3: Collection detail SSE comment says /api/collections/ path.** The template comment at line 8 of `collections/detail.html` still references `/api/collections/{run_id}/stream`, but the actual `sse-connect` attribute on line 81 correctly uses `/collections/{{ run_id }}/stream`. The comment is misleading for anyone reading the code. More importantly, if the SSE endpoint does not match the actual route mount point, live monitoring will silently fail. The fix summary (2026-02-20) addressed the `/api` prefix issue. `[core]`

- **F-ER-4: Import page posts to /api/content/import but imports router is mounted at /api.** The import form (`hx-post="/api/content/import"`) targets a path under `/api`. Looking at `main.py` line 384, the imports router is mounted at prefix `/api`. If the imports router defines a route at `/content/import`, the full path would be `/api/content/import`, which matches. But if the route is at `/imports/upload` or similar, the form will 404 silently. The researcher clicks "Upload and Import" and sees nothing happen. `[core]`

- **F-ER-5: Query design delete confirmation is generic.** The delete button says "Delete query design '[name]'? All associated search terms will also be deleted." This does not mention that collection runs and their data are NOT deleted (they are linked but not cascaded). A researcher might hesitate to delete a design because they fear losing their collected data. Clarifying "Your collected data will be preserved" would reduce anxiety. `[frontend]`

- **F-ER-6: No error page template.** The application does not appear to have a custom 404 or 500 error page template. When a route returns an error, the researcher sees either a raw JSON error response, a FastAPI default error page, or a browser error page. A branded error page with "Something went wrong" and a link back to the dashboard would maintain the user experience during failures. `[frontend]`

---

## Cross-Cutting Observations

### Navigation and Information Architecture

- **The sidebar lacks "where am I" context beyond link highlighting.** Active links are highlighted in blue, but there is no breadcrumb or page path indicator. On nested pages (e.g., `/query-designs/{id}/edit` or `/analysis/{run_id}`), the researcher knows they are in the Query Designs or Analysis section, but not which specific entity they are viewing.

- **The analysis page is not directly navigable from the sidebar.** The sidebar links to `/analysis`, which shows the landing page ("Select a collection run to analyse"). The researcher must then navigate to `/collections`, find a completed run, and click through to its analysis. There is no "analyse this run" link on the collection detail page. UPDATE: The collection detail page does not include a direct "View Analysis" link. The analysis landing page links back to collections. This creates a circular navigation pattern.

### Data Trust

- **No data provenance trail visible to the researcher.** When a researcher looks at content in the browser, they see the platform, author, text, date, and engagement score. They do not see: which API endpoint produced this record, what search query matched it, whether it was deduplicated, or what the original API response contained. For published research, scholars need to describe their data collection methodology precisely. The `raw_metadata` JSONB field contains this information but is not exposed in the UI.

- **Engagement scores are presented without normalization context.** The content browser shows engagement scores as bare numbers. The application implements log-scaled 0-100 normalization (per IP2-030), but the UI does not indicate that these are normalized scores, not raw counts. A researcher might cite "engagement score: 47" without knowing this is a transformed value. The analysis dashboard should explain the normalization method.

- **Deduplication status is invisible.** The system implements URL hash, content hash, and SimHash near-duplicate detection. But the content browser does not indicate whether a record is a duplicate or has near-duplicates. A researcher analyzing volume trends needs to know whether duplicates inflate their counts.

### Accessibility

- **Toggle switches lack visible labels.** The arena enable/disable toggles in the configuration grid use `aria-pressed` and `aria-label` attributes (good), but the visual design relies entirely on color (blue=enabled, gray=disabled). A researcher with color vision deficiency may not distinguish these states. Adding a small "ON"/"OFF" text label inside or beside the toggle would improve accessibility.

- **Small text throughout.** Many UI elements use `text-xs` (0.75rem / 12px), which is below the WCAG recommended minimum of 16px for body text. While 12px is acceptable for secondary labels, the content browser table body, filter labels, and export options all use this small size. On a standard laptop screen, prolonged reading of content records at 12px will cause strain.

---

## Prioritized Recommendations

### Priority 1: Route Architecture (must fix before any workflow is usable)

1. **[core] Resolve the wildcard route conflict systematically.** The `priority_router` approach of adding literal routes before wildcards is fragile and has already caused regressions for `/collections/estimate`, `/actors/resolution`, `/actors/search`, and `/collections/active-count`. A content-negotiation middleware that dispatches based on `Accept` header, or a clean separation of API routes under `/api/` prefix, would be more robust.

2. **[core] Fix the editor template arenas_config crash.** The `arenas_config.get('global', {})` pattern needs null-safe handling in Jinja2. Use `(design.arenas_config or {}).get('global', {}).get('languages', ['da'])` or pre-process the variable in the route handler to ensure a safe default.

3. **[core] Implement or verify the /content/search-terms endpoint.** This is needed for the content browser search term filter to function.

### Priority 2: Researcher Confidence (friction that undermines data trust)

4. **[frontend] Add a collection launch summary panel.** Before clicking "Start Collection", show: number of enabled arenas, number of search terms, number of actors, estimated date range, estimated credits. This is the "preflight checklist" that gives a researcher confidence they configured everything correctly.

5. **[frontend] Surface deduplication and normalization metadata.** In the content browser detail panel, show whether the record has duplicates or near-duplicates. In the analysis dashboard, explain the engagement score normalization method.

6. **[data] Add engagement_score to flat export columns.** The missing column in `_FLAT_COLUMNS` (M-AN-2) means researchers lose a key metric when exporting.

7. **[frontend] Replace platform_name identifiers with human-readable labels.** Affects: arena scoping checkboxes in term form, arena filter in content browser, arena names in the configuration grid monospace line.

### Priority 3: Workflow Polish (friction that slows researchers down)

8. **[frontend] Set sensible date defaults on the collection launcher.** Default the "To" field to today and "From" field to 7 days ago for batch mode.

9. **[frontend] Improve the content browser date display.** Replace truncated ISO timestamps with localized date formatting (e.g., "15 Feb 2026, 14:32").

10. **[frontend] Add a custom error page.** Create a branded 404/500 template with navigation back to the dashboard.

11. **[frontend] Expand the language filter in the content browser.** Match the 7 languages available in the query design editor.

12. **[frontend] Add "View Analysis" link on the collection detail page.** For completed runs, include a direct link to `/analysis/{run_id}` to eliminate the circular navigation pattern.

13. **[frontend] Move the AI-Powered Discovery section.** Relocate from the query design editor to the query design detail page or the explore page, where it fits the research workflow more naturally.

### Priority 4: Documentation and Accessibility

14. **[frontend] Add format descriptions to export options.** Brief explanatory text for NDJSON, Parquet, and GEXF.

15. **[frontend] Add visible labels to toggle switches.** For color-blind accessibility.

16. **[frontend] Increase base font size for content tables.** Move from `text-xs` to `text-sm` for table body content.

17. **[frontend] Create a "Getting Started" guide accessible from the dashboard.** For first-time researchers who need orientation beyond the sidebar labels.

---

## Relationship to Previous Reports

This walkthrough builds on and cross-references:

- `/docs/ux_reports/comprehensive_evaluation_2026_02_20.md` -- 13 critical issues identified; fixes applied but with regressions
- `/docs/ux_reports/fix_summary_2026_02_20.md` -- 35 issues fixed; test suite passes but UI issues persist
- `/docs/ux_reports/comprehensive_workflow_test_2026_02_22.md` -- CRIT-01 through CRIT-05 identified via live testing
- `/docs/ux_reports/sidebar_audit_2026_02_22.md` -- 4 sidebar sections broken, 2 critical sub-pages inaccessible
- `/docs/ux_reports/fix_verification_2026_02_22.md` -- 2 of 5 critical fixes pass; 3 have regressions
- `/docs/ux_reports/visual_behavioral_audit_2026_02_22.md` -- Dashboard widget bugs, volume spike visibility issue

The pattern across these reports is consistent: individual features are well-designed, but the integration layer (route registration, template variable passing, HTMX endpoint alignment) is where the application breaks down. The recommended path forward is to stabilize the routing architecture first, then address the researcher-facing friction points identified in this walkthrough.
