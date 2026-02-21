# Workflow Code Review Report -- Application Description vs. Implementation

Date: 2026-02-20
Scope: Four-stage research workflow (Query Design, Collection, Content Browsing, Analysis)
Method: Read-only code review comparing `/docs/application_description.md` against route handlers, templates, and Alpine.js components

---

## Summary

The codebase delivers substantially on the application description's promises. The backend route handlers, database models, and template markup support the vast majority of described capabilities. However, several stale "BACKEND GAP" comments in templates create false impressions of missing functionality, the page handler layer passes minimal server-side context to templates (creating a dependence on client-side API calls that may not always fire), and the content browser is missing a `content_type` filter that the application description explicitly claims exists. This report details every verified gap, organized by workflow stage.

---

## Stage 1: Query Design

### PASSED -- Features confirmed in code

| Application description claim | Code location | Verified |
|------|------|------|
| "Terms can be organized into boolean groups using AND/OR logic" | `query_designs.py` lines 637-642 (group_id/group_label), `editor.html` line 257 (group_label input), `query_builder.py` mentioned in CLAUDE.md | YES |
| "Each term can optionally be scoped to specific platforms" | `query_designs.py` lines 644-657 (target_arenas parsing), `editor.html` lines 271-317 (arena scoping UI) | YES |
| "Terms can also be assigned group labels" | `query_designs.py` line 584 (group_label form field), `editor.html` lines 256-269 (group input with datalist autocomplete) | YES |
| "Query designs support cloning" | `query_designs.py` lines 333-449 (clone endpoint with deep copy of terms, actors, arenas_config, parent_design_id) | YES |
| Clone shows "parent lineage" | `editor.html` lines 47-58 (parent design link), `detail.html` lines 54-69 (clone button) | YES |
| "Actor lists define people, organizations..." with cross-platform presence | `query_designs.py` lines 1361-1472 (actor add with canonical Actor creation), `editor.html` lines 558-571 (actor type dropdown: person, organization, political_party, educational_institution, teachers_union, think_tank, media_outlet, government_body, ngo, company) | YES |
| "Researchers can provide custom source lists" (Telegram, Reddit, RSS, Discord, Wikipedia) | `query_designs.py` lines 974-1059 (PATCH arena-config endpoint supporting rss/telegram/reddit/discord/wikipedia/global sections) | YES |
| "Four types: keyword, phrase, hashtag, URL pattern" | `editor.html` lines 232-239 (term_type select) | YES |
| Bulk term import | `query_designs.py` lines 701-809 (bulk endpoint), `editor.html` lines 362-430 (bulk textarea UI with format help) | YES |
| Bulk actor import | `query_designs.py` lines 1475-1603 (bulk actors endpoint), `editor.html` lines 589-651 (bulk actor textarea UI) | YES |
| Platform presence inline add (YF-16) | `editor.html` lines 679-755 (inline presence form per actor with platform dropdown) | YES |
| RSS feed autodiscovery (SB-09) | `query_designs.py` lines 1832-1913 (discover-feeds endpoint) | YES |
| Reddit subreddit suggestion (SB-10) | `query_designs.py` lines 1921-2038 (suggest-subreddits endpoint) | YES |

### GAPS

**GAP 1: Page handlers pass minimal context -- templates render empty on server side**
- Severity: MAJOR gap
- Application description says: "A researcher begins by creating a query design -- a named, versioned specification of what to collect. A query design contains three elements: search terms, actor lists, and arena configuration."
- Code reality: The page handler for the query design detail page (`pages.py` lines 234-254) passes only `{"request": request, "user": current_user, "design_id": str(design_id)}` to the template. The detail template (`detail.html`) references `design.name`, `terms`, `actors`, `runs`, and other context variables that are never populated server-side. These are protected by Jinja2 `| default({})` and `| default([])` filters so the page renders without errors, but all content areas (design name, search terms list, actor list, run history) will appear empty on initial render.
- Research impact: The templates are designed for a hybrid architecture where Alpine.js and HTMX load data from JSON API endpoints after page load. If JavaScript fails to execute or any API call returns an error, the researcher sees a blank page with no indication of what went wrong. There is no `<noscript>` fallback.
- File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/routes/pages.py` lines 234-277
- Responsible agent: [core]

**GAP 2: Query design list page passes no `designs` to template**
- Severity: MAJOR gap (same root cause as GAP 1)
- The list page handler (`pages.py` lines 192-210) passes no `designs` variable. The template (`list.html` line 25) checks `{% if designs | default([]) | length > 0 %}` and will always show the empty state on initial render.
- For this to work, the list page MUST be loading designs via HTMX after initial render, but no such mechanism is visible in the list template -- it uses `{% for design in designs %}` which is purely server-side.
- File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/routes/pages.py` lines 192-210
- Responsible agent: [core]

**GAP 3: Editor template has duplicated actor list markup**
- Severity: MINOR gap
- The editor template contains what appears to be duplicated actor list iteration blocks. Lines 655-763 contain the actor list with inline presence forms. Lines 764-786 contain what appears to be a second copy of the actor delete button and empty state, creating potentially malformed HTML.
- File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/query_designs/editor.html` lines 764-786
- Research impact: May cause layout glitches or double-rendered actor items.
- Responsible agent: [frontend]

**GAP 4: Actor type mismatch between server-rendered and HTMX-added actors**
- Severity: MINOR gap
- The server-rendered actor list in `editor.html` (line 665) checks for `atype == 'organisation'` (with an 's'), but the route handler `_render_actor_list_item` (line 1269) checks for `"organization"` (without 's'). The ActorType enum in the codebase uses `"organization"`. This means server-rendered actors with type "organization" fall through to the default "Account" badge, while HTMX-added actors correctly show "Org".
- File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/query_designs/editor.html` line 665
- Responsible agent: [frontend]

---

## Stage 2: Collection

### PASSED -- Features confirmed in code

| Application description claim | Code location | Verified |
|------|------|------|
| "Batch mode collects data for a specified date range" | `collections.py` lines 158-301 (create endpoint with mode, date_from, date_to) | YES |
| "Live tracking mode schedules recurring collection" | `launcher.html` lines 87-113 (batch/live toggle), `collections.py` line 268 (mode field on CollectionRun) | YES |
| "Per-arena guidance on which platforms support historical date ranges" | `launcher.html` lines 147-178 (date range coverage notes per arena) | YES |
| "Pre-flight credit estimation" | `collections.py` lines 311-393 (estimate endpoint using CreditService), `launcher.html` lines 805-844 (estimate trigger UI) | YES |
| "SSE live monitoring" | `detail.html` lines 79-84 (hx-ext="sse" with sse-connect and sse-close) | YES |
| "Suspend and resume live tracking" | `collections.py` lines 503-587 (suspend and resume endpoints with status/suspended_at management) | YES |
| "Schedule panel shows next scheduled execution" | `detail.html` lines 97-133 (liveSchedulePanel Alpine component with next_run_at display) | YES |
| "Tier precedence: per-arena override > launcher > global default" | `collections.py` lines 200-234 (three-level merge with detailed comments) | YES |
| Date range capability warnings (SB-05) | `collections.py` lines 237-266 (TemporalMode check for RECENT/FORWARD_ONLY arenas) | YES |
| "Promote to Live Tracking" button (SB-08) | `detail.html` lines 70-82 (conditionally shown button), lines 424-519 (confirmation dialog) | YES |
| Live tracking daily schedule at midnight Copenhagen time | `launcher.html` line 112 ("midnight Copenhagen time CET/CEST") | YES |

### GAPS

**GAP 5: Collections page handler does not load run data for template**
- Severity: MAJOR gap (same pattern as GAP 1)
- The collections list page handler (visible in pages.py routing table) passes minimal context. The template iterates over `runs` which would be empty. Same issue for the detail page -- the `run`, `tasks`, and `search_terms` context variables expected by `detail.html` must be loaded via API calls.
- Responsible agent: [core]

---

## Stage 3: Content Browsing

### PASSED -- Features confirmed in code

| Application description claim | Code location | Verified |
|------|------|------|
| "Filterable, searchable interface" | `browser.html` lines 48-55 (filter form with HTMX trigger), `content.py` lines 256-349 (keyset-paginated query builder) | YES |
| "Filter by platform, date range, language" | `browser.html` lines 69-133 (arena checkboxes, date inputs, language select) | YES |
| "Filter by search term matched" | `browser.html` lines 188-200 (search term select), `content.py` line 331 (search_terms_matched array filter) | YES |
| "Filter by collection mode (batch or live)" | `browser.html` lines 136-148 (SB-13 mode filter), `content.py` lines 333-344 (mode subquery filter) | YES |
| "Full-text search uses PostgreSQL's Danish text configuration" | `content.py` lines 346-349: `to_tsvector('danish', ...)` with `plainto_tsquery` | YES |
| "Slide-in detail panel" (via HTMX row click) | `browser.html` line 8 mentions "Detail panel: HTMX-loaded record detail on row click" | YES |
| "Matched search term badges" in detail | `record_detail.html` lines 153-164 (badges with blue styling) | YES |
| "View original" link | `record_detail.html` lines 64-76 (external link with noopener) | YES |
| "Raw metadata" expandable viewer | `record_detail.html` lines 167-190 (Alpine toggle, JSON pretty-print) | YES |
| Annotation panel with stance labels (IP2-043, SB-16) | `record_detail.html` lines 192-249 (annotation panel with stance dropdown: positive, negative, neutral, contested, irrelevant) | YES |
| "Discovered sources panel" (GR-22) | `content.py` lines 880+ (discovered-links endpoint), `discovered_links.html` template exists | YES |
| Quick-add actor from content browser (GR-17) | `browser.html` lines 11-12 mention quick-add modal; `content.py` line 671 passes `active_query_design_id` | YES |
| Search terms dropdown loads per-run (IP2-029) | `content.py` lines 803-870 (get_search_terms_for_run endpoint exists and functional) | YES |
| Seven export formats | `content.py` lines 55-73 (csv, xlsx, json/ndjson, parquet, gexf, ris, bibtex) | YES |

### GAPS

**GAP 6: Content browser missing `content_type` filter**
- Severity: MAJOR gap
- Application description says: "Researchers can filter by platform, date range, language, content type, search term matched, and collection mode (batch or live)."
- Code reality: The content browser sidebar (`browser.html`) has filters for arena, date range, language, collection mode, collection run, and search term. There is NO `content_type` filter. The `_build_browse_stmt` function in `content.py` does not accept a `content_type` parameter. The query builder `_build_content_stmt` also lacks content_type filtering.
- Research impact: A researcher studying a specific issue across platforms cannot filter to show only "video" content from YouTube, or only "article" content from RSS, or only "post" content from Bluesky. They must manually scan mixed content types.
- File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/content/browser.html` (missing from sidebar)
- File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/routes/content.py` lines 81-150 (missing parameter)
- Responsible agents: [frontend] for template, [core] for route handler

**GAP 7: Content browser arena checkboxes are hardcoded and incomplete**
- Severity: MAJOR gap
- Application description says the application supports 21 functional platform collectors.
- Code reality: The content browser sidebar (`browser.html` lines 73-85) hardcodes only 11 arena checkboxes: google_search, google_autocomplete, bluesky, reddit, youtube, rss_feeds, gdelt, telegram, tiktok, ritzau_via, gab. Missing from the filter UI: event_registry, x_twitter, facebook, instagram, threads, common_crawl, wayback, url_scraper, wikipedia, discord, ai_chat_search, majestic.
- Research impact: A researcher who collects data from Event Registry, X/Twitter, Facebook, or any of the 10 missing arenas CANNOT filter the content browser to show only records from those arenas. There is no "Other arenas" option either. Content from those arenas appears in the browser but cannot be isolated.
- File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/content/browser.html` lines 73-85
- Responsible agent: [frontend]

**GAP 8: Stale "BACKEND GAP" comments in templates**
- Severity: MINOR gap (documentation quality, not functional)
- Two template comments claim backend endpoints do not exist when they actually do:
  - `browser.html` line 154: Claims `GET /content/search-terms` does not exist. It DOES exist at `content.py` line 803.
  - `browser.html` line 22: Claims `active_query_design_id` is not passed. It IS passed at `content.py` line 671.
  - `analysis/index.html` line 190: Claims `GET /analysis/{run_id}/filter-options` does not exist. It DOES exist at `analysis.py` line 1129.
  - `analysis/index.html` line 424: Claims `GET /analysis/{run_id}/emergent-terms` does not exist. It DOES exist at `analysis.py` line 768.
- Research impact: None directly, but a developer reading these comments would waste time building endpoints that already exist.
- File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/content/browser.html` lines 22-27, 151-166
- File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/analysis/index.html` lines 190-196, 424-429
- Responsible agent: [frontend]

---

## Stage 4: Analysis

### PASSED -- Features confirmed in code

| Application description claim | Code location | Verified |
|------|------|------|
| "Descriptive analytics: volume over time" | `analysis.py` imports `get_volume_over_time`, endpoint at `/{run_id}/volume` | YES |
| "Top actors ranked by post count and engagement" | Endpoints `/{run_id}/actors` and `/{run_id}/actors-unified` | YES |
| "Top matched search terms" | Endpoint `/{run_id}/terms` | YES |
| "Engagement score distributions" | Endpoint `/{run_id}/engagement` | YES |
| "Temporal volume comparisons (week-over-week, month-over-month)" | Endpoint `/{run_id}/temporal-comparison` at line 474 | YES |
| "Arena-comparative analysis" | Endpoint `/{run_id}/arena-comparison` at line 537 | YES |
| "Suggested terms use TF-IDF extraction" | Endpoint `/{run_id}/emergent-terms` at line 768 | YES |
| "Three types of networks: actor co-occurrence, term co-occurrence, bipartite" | Endpoints `/{run_id}/network/actors`, `/terms`, `/bipartite` | YES |
| "Temporal network snapshots" | Endpoint `/{run_id}/network/temporal` | YES |
| "In-browser network visualization (Sigma.js)" | `analysis/index.html` lines 20-34 (CDN loads for graphology + sigma) | YES |
| "Cross-run comparison" | Endpoint `/compare` at line 230 | YES |
| "Cross-run analysis aggregating data from multiple collection cycles" | Endpoint `/design/{design_id}` at line 1534 and related design-level endpoints | YES |
| "Enrichment results: language distribution" | Endpoint `/{run_id}/enrichments/languages` at line 1909 | YES |
| "Named entities" | Endpoint `/{run_id}/enrichments/entities` at line 1944 | YES |
| "Propagation patterns" | Endpoint `/{run_id}/enrichments/propagation` at line 1981 | YES |
| "Coordination signals" | Endpoint `/{run_id}/enrichments/coordination` at line 2022 | YES |
| "Enrichment results tab" in dashboard (SB-15) | `analysis/index.html` line 1002+ (enrichment results section with four panels) | YES |
| "Political calendar overlay" (GR-16) | `analysis/index.html` lines 16-31 (chartjs-plugin-annotation loaded) | YES |
| Per-arena GEXF export (IP2-047) | `analysis.py` route comments confirm `?arena=` parameter on network endpoints | YES |
| "Seven export formats" | `content.py` lines 55-73 (csv, xlsx, json, parquet, gexf, ris, bibtex) | YES |

### GAPS

**GAP 9: Analysis template still contains stale "BACKEND GAP" comments about endpoints that exist**
- Severity: MINOR gap
- Same issue as GAP 8 but in the analysis template. The filter-options, emergent-terms, and enrichment endpoints all exist but comments say they do not.
- Responsible agent: [frontend]

**GAP 10: Political calendar overlay loads from static JSON, not a filtered API endpoint**
- Severity: MINOR gap
- Application description says: "A political calendar overlay can annotate the volume timeline with known events."
- Code reality: The analysis template (`index.html` lines 37-40) includes a TODO comment: "expose GET /analysis/calendar-events?date_from=&date_to= returning filtered political_calendar.json events as JSON. For now, events are loaded from /static/data/political_calendar.json directly."
- Research impact: Calendar events cannot be filtered by date range, and the researcher cannot add custom events through the interface. This is a convenience limitation, not a blocker.
- File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/analysis/index.html` lines 37-40
- Responsible agent: [core]

---

## Cross-Cutting Findings

**GAP 11: "Versioned" query designs not actually versioned**
- Severity: MINOR gap
- Application description says: "a named, versioned specification of what to collect."
- Code reality: Query designs have no `version` field, no version number, and no version history. The clone mechanism (parent_design_id) provides a lineage trace, but there is no version numbering or automatic versioning when a design is modified.
- Research impact: A researcher who edits a query design after running a collection has no record of what the design looked like when the collection was run. The collection_runs table stores an arenas_config snapshot, but not a snapshot of the search terms or actor list.
- Responsible agent: [research]

**GAP 12: AI Chat Search "Learn more" link points to Anthropic docs**
- Severity: MINOR gap
- The editor template (`editor.html` line 514) includes a "Learn more about AI-powered discovery" link that points to `https://docs.anthropic.com/claude/docs`. This is the Claude documentation, not documentation about the AI Chat Search arena. A researcher clicking this link would arrive at Anthropic's Claude developer documentation, which has nothing to do with the Issue Observatory's AI Chat Search feature.
- File: `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/src/issue_observatory/api/templates/query_designs/editor.html` line 514
- Responsible agent: [frontend]

---

## Recommendations (prioritized)

1. **[core] CRITICAL: Populate page handler template context.** The page handlers in `pages.py` must load design objects, search terms, actors, and run history server-side and pass them to templates. The current approach renders empty pages that depend entirely on client-side JavaScript. This is the single most impactful gap -- it affects every page in the application.

2. **[frontend] MAJOR: Add content_type filter to content browser.** Add a `content_type` dropdown or checkbox group to the filter sidebar and add the corresponding parameter to `_build_browse_stmt`. The universal content record stores `content_type` (article, post, video, comment, etc.) but the browser cannot filter by it.

3. **[frontend] MAJOR: Dynamically populate arena checkboxes in content browser.** Replace the hardcoded 11-arena checkbox list with a dynamic list fetched from `/api/arenas/` or derived from the actual arenas present in the user's collected data. This ensures all 21+ arenas are filterable.

4. **[frontend] MINOR: Remove stale "BACKEND GAP" comments.** At least 6 template comments describe endpoints as missing that actually exist in the codebase. These comments create confusion for developers and should be removed or updated to reference the actual implementation.

5. **[frontend] MINOR: Fix actor type string mismatch.** Change `editor.html` line 665 from `'organisation'` to `'organization'` to match the ActorType enum used throughout the codebase.

6. **[frontend] MINOR: Fix duplicated actor list markup in editor.** Lines 764-786 of the editor template appear to duplicate actor list iteration markup. This should be cleaned up to prevent rendering artifacts.

7. **[frontend] MINOR: Fix AI Chat Search "Learn more" link.** Point to application documentation or remove the link if no such documentation exists.

8. **[research] MINOR: Clarify "versioned" language in application description.** Either implement version numbering on query designs or adjust the description to say "named, clonable" rather than "named, versioned."
