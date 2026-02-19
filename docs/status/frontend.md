# Frontend Engineer — Status

## Phase 0.9 — Frontend Foundation

### Static Files
- [x] `css/input.css` — Tailwind input with `@tailwind base/components/utilities` + custom component classes (`.btn-primary`, `.btn-secondary`, `.btn-danger`, `.btn-ghost`, `.card`, `.form-input`, tier badges, status colours, table utilities, alert variants, `.htmx-indicator`, `[x-cloak]`)
- [x] `css/app.css` — Hand-crafted minimal CSS (HTMX indicator rules, Alpine x-cloak). Tailwind CDN handles utilities in dev; full build via `make css`.
- [x] `js/app.js` — Alpine components (`collectionLauncher`, `queryEditor`), HTMX global 401 redirect handler, HX-Redirect header handler, `dispatchEstimateResult` utility
- [x] `js/charts.js` — `initVolumeChart`, `initEngagementChart`, `initArenaBreakdownChart` (all guard against missing canvas, destroy-before-reinit, shared defaults)

### Base Templates
- [x] `base.html` — Full layout: Tailwind CDN, HTMX 2, SSE extension, Alpine 3, Chart.js 4, `app.js`, `charts.js`, nav sidebar include, flash include, content block, footer
- [x] `base_auth.html` — Standalone auth layout (no nav)

### Partials (`_partials/`)
- [x] `nav.html` — Left sidebar with active-link highlighting, admin section (role-gated), credit badge include, user info, sign-out
- [x] `flash.html` — Dismissible Alpine toast banners; supports context var + query-param flash
- [x] `credit_badge.html` — HTMX-polled (`every 30s`) credit balance widget
- [x] `pagination.html` — Cursor-based prev/next with HTMX push-url
- [x] `empty_state.html` — Generic empty-state card with optional CTA
- [x] `loading_spinner.html` — `.htmx-indicator` spinner

### Fragments (`_fragments/`)
- [x] `term_row.html` — Single search term row with type badge + HTMX delete
- [x] `credit_estimate.html` — Pre-flight cost breakdown table + sufficiency indicator + `dispatchEstimateResult` call
- [x] `task_row.html` — Per-arena task row with `hx-swap-oob`, status icons, duration, error message
- [x] `run_summary.html` — Run-level summary card with `hx-swap-oob`, progress bar, stats grid
- [x] `content_table_body.html` — (stub from earlier phase)

### Auth Templates
- [x] `auth/login.html` — Standalone card layout; session-expired + pending-activation banners; Alpine `loginForm()` component handles credential submission to FastAPI-Users cookie endpoint; inline error display

### Dashboard
- [x] `dashboard/index.html` — Summary cards (credits, active runs, records); HTMX-loaded recent collections table; quick action links

## Phase 0.9b — Minimum Viable Collection UI

### Query Designs
- [x] `query_designs/list.html` — Paginated table with tier/visibility badges, HTMX delete, empty state, "New" button
- [x] `query_designs/editor.html` — Create/edit form (name, description, visibility, tier, language); HTMX add/remove terms panel; arena config grid stub (Phase 1 placeholder)

### Collections
- [x] `collections/list.html` — Run history table with status indicators, tier badges, pagination, empty state
- [x] `collections/launcher.html` — Query design selector, batch/live mode toggle, date range (batch only), tier cards, credit estimate panel (HTMX + Alpine 400ms debounce), launch button (Alpine-gated by credit check)
- [x] `collections/detail.html` — SSE live monitor (`hx-ext="sse"`, `sse-connect`, `sse-close="run_complete"`); run summary card (hx-swap-oob); per-arena task table (hx-swap-oob rows); cancel button; post-run actions

## Phase 1 — Full Frontend (Task 1.14–1.18)

### Query Designs (Task 1.14)
- [x] `query_designs/editor.html` — **Updated**: arena configuration grid (Alpine `arenaConfigGrid()` component, 11 Phase 1 arenas hardcoded, per-arena enable toggle + tier radio buttons, debounced 400ms credit estimate via HTMX, save arena config button); actor list sub-panel (HTMX add/remove actors with type badges, profile deep-link)
- [x] `query_designs/detail.html` — Read-only detail: metadata card, search terms chip list, actor list chips, run history table with status badges + deep links to collection detail

### Collections (Task 1.15 — already complete in Phase 0.9b)
- [x] `collections/detail.html` — SSE-driven live monitor; cancel button; post-run actions; `sse-close="run_complete"` → redirect to content browser

### Content Browser (Task 1.16)
- [x] `content/browser.html` — Two-column layout: filter sidebar (arena checkboxes, date range, language, search term, collection run, reset); main area with paginated table (infinite scroll via `hx-trigger="revealed"`, capped at 2000 rows with export banner); slide-in detail panel (Alpine transition); Alpine `contentBrowser()` component manages panel state + row count
- [x] `content/record_detail.html` — Dual-mode partial: panel embed (default) + standalone full page (`standalone=true`); platform badge, title/text, metadata grid, matched search terms chips, Alpine-toggled raw JSON viewer (`<pre>` with Fernet-decrypted metadata), external URL link, actions row

### Actor Directory (Task 1.17)
- [x] `actors/list.html` — Searchable table (HTMX `keyup delay:300ms`); Add Actor modal (Alpine `open-add-actor` event, HTMX POST); type badges; content count deep-link; pagination
- [x] `actors/detail.html` — Identity card (initials avatar, type badge, content count, description); edit actor modal (HTMX PATCH → card swap); platform presences table (add/remove presence modals); HTMX-paginated content timeline with infinite scroll

### Admin Pages (Task 1.18)
- [x] `admin/credentials.html` — **Updated**: platform-specific credential fields via Alpine `credentialForm()` `x-show`; youtube/serper/bluesky/reddit → api_key; telegram → api_id + api_hash + session_string; twitter_api_io → api_key + optional bearer_token; gdelt/rss_feeds → no key needed banner; credential list with activate/deactivate/reset-errors/delete HTMX actions
- [x] `admin/health.html` — System health cards (PostgreSQL, Redis, Celery); HTMX-polled every 15s; arena health table polled every 60s; loading skeleton on initial render
- [x] `admin/users.html` — User table with activate/deactivate HTMX actions, role badges, deep link to credits
- [x] `admin/credits.html` — Credit allocation form (user selector, amount, expiry, memo); recent allocations table

### Auth
- [x] `auth/login.html` — (completed Phase 0.9)
- [x] `auth/reset_password.html` — Two-state form: request reset (email input → POST `/auth/forgot-password`) and set new password (password + confirm, Alpine strength meter, token hidden field → POST `/auth/reset-password`); success states for both flows; error banner

## Phase 3 — Analysis Dashboard (Task 3.4)

### Analysis
- [x] `analysis/index.html` — Full analysis dashboard: run summary cards (Alpine fetch), filter bar (platform/arena/date/granularity), Volume-over-time multi-arena line chart, Top actors horizontal bar chart, Top terms horizontal bar chart, Engagement distribution grouped bar chart (mean/median/p95), Network tab switcher (actor co-occurrence, term co-occurrence, bipartite, cross-platform actors table), Export section (format selector, sync export link, async export with 3s polling). All data loaded client-side via Alpine `fetch()` from `/analysis/{run_id}/*` JSON endpoints. Chart.js helpers `initActorsChart`, `initTermsChart`, `initEngagementStatsChart`, `initMultiArenaVolumeChart` added to `charts.js`.

## Phase 3 Blocker Fixes (2026-02-17)

### B-01 — Snowball Sampling UI entry point
- [x] `actors/list.html` — Added collapsible "Snowball Sampling" panel below the actor table. Panel includes: seed actor checklist pre-populated from page context (actor name + platform badges), platform checkboxes fetched from `GET /actors/sampling/snowball/platforms` in `x-init`, depth slider (1–3, default 2, labelled "How many hops"), max actors per step number input (default 20), add-to-list toggle, "Run Snowball Sampling" button with loading spinner. Results section shows summary cards (total found, depth reached, selected), discovered actors table (name, platforms, discovery depth/wave columns) with per-row checkboxes, select-all/clear controls, and "Add selected to actor list" button posting to `POST /actors/lists/{list_id}/members/bulk`. Alpine component `snowballSampler()` added with `init()` (platform fetch with fallback), `runSnowball()` (POST `/actors/sampling/snowball`), `addSelected()` (POST bulk), and toggle helpers. Platforms fall back to `['bluesky', 'reddit', 'youtube']` if the endpoint is unavailable.

### B-02 — GEXF network type buttons (critical: silently mislabelled)
- [x] `analysis/index.html` — Fixed all three GEXF download buttons to include the correct `network_type` parameter:
    - Actor Network tab button: `href="/content/export?format=gexf&network_type=actor&run_id=..."`, label "Download Actor Co-occurrence Network (GEXF)", helper text added.
    - Term Network tab button: `href="/content/export?format=gexf&network_type=term&run_id=..."`, label "Download Term Co-occurrence Network (GEXF)", helper text added.
    - Bipartite tab button: `href="/content/export?format=gexf&network_type=bipartite&run_id=..."`, label "Download Bipartite Actor-Term Network (GEXF)", helper text added.
- [x] `analysis/index.html` — Async export panel updated: added `gexfNetworkType` state (default `'actor'`) to `exportPanel()` component; GEXF network type radio group (actor / term / bipartite) shown via `x-show="exportFormat === 'gexf'"` with explanatory text; sync export `<a>` href now conditionally builds the correct `network_type` parameter for GEXF; async `startAsyncExport()` now POSTs a JSON body (changed from query-string to `Content-Type: application/json`) and includes `network_type` when format is GEXF.

### B-03 — Live tracking: schedule visibility + suspend/resume
- [x] `collections/detail.html` — Added `is_live` Jinja variable (`mode == 'live'`). Added "Live Tracking Schedule" card (visible only when `is_live`) using Alpine `liveSchedulePanel(runId, initialStatus)` component: fetches `GET /collections/{run_id}/schedule` in `init()`, displays `next_run_at` formatted with timezone (falls back to "Daily at midnight Copenhagen time"), shows `suspended_at` when present, renders green "Active — collecting daily" or amber "Suspended — collection paused" status badge. Added Suspend Tracking button (amber, `hx-post="/collections/{run_id}/suspend"`, `hx-confirm`) visible when `scheduleStatus === 'active'`; Resume Tracking button (green, `hx-post="/collections/{run_id}/resume"`, `hx-confirm`) visible when `scheduleStatus === 'suspended'`; Cancel & Delete Run button (red, destructive label, `hx-confirm` with permanent-deletion warning). Both suspend/resume update `scheduleStatus` optimistically via `@htmx:after-request`. Inline explanation: "Suspend pauses daily collection without deleting your data. Cancel permanently ends the run." Batch runs retain their original cancel button in the task table header; live runs have it moved to the schedule panel only.
- [x] `collections/list.html` — Added `suspended` status badge: amber colour (`text-amber-700`), pause-icon SVG, label "Suspended" — rendered in the `{% elif status == 'suspended' %}` branch, distinct from `failed` (red) and `active`/`running` (blue).

## Greenland Recommendations (GR-01 through GR-06)

### GR-01 — RSS custom feeds panel
- [x] `query_designs/editor.html` — Collapsible "RSS — Custom Feeds" panel in the arena config section. Tag-style list with add/remove. Persists via `PATCH /query-designs/{id}/arena-config/rss` with `{"custom_feeds": [...]}`. Alpine `arenaSourcePanel()` component handles optimistic list state, duplicate prevention, and inline save feedback. Panel collapses by default; count badge shown in header.

### GR-02 — Telegram custom channels panel
- [x] `query_designs/editor.html` — Collapsible "Telegram — Custom Channels" panel. Input accepts username without `@` prefix; display renders with `@` prefix. Persists via `PATCH /query-designs/{id}/arena-config/telegram` with `{"custom_channels": [...]}`. Same `arenaSourcePanel()` component as GR-01.

### GR-03 — Reddit custom subreddits panel
- [x] `query_designs/editor.html` — Collapsible "Reddit — Custom Subreddits" panel. Inline `r/` prefix in the input affordance; display renders with `r/` prefix. Persists via `PATCH /query-designs/{id}/arena-config/reddit` with `{"custom_subreddits": [...]}`. Same `arenaSourcePanel()` component.

### GR-04 — Discord channel IDs and Wikipedia seed articles panels
- [x] `query_designs/editor.html` — "Discord — Custom Channel IDs" panel: numeric snowflake ID input, `inputmode="numeric"`. Persists via `PATCH /query-designs/{id}/arena-config/discord` with `{"custom_channel_ids": [...]}`.
- [x] `query_designs/editor.html` — "Wikipedia — Seed Articles" panel: article title input, each item renders as a Wikipedia deep-link. Persists via `PATCH /query-designs/{id}/arena-config/wikipedia` with `{"seed_articles": [...]}`.

### GR-05 — Multi-language selector
- [x] `query_designs/editor.html` — "Languages" collapsible panel with toggle-button style multi-select for 7 languages: da, en, kl, de, sv, no, ru. At least one language always remains selected. Persists via `PATCH /query-designs/{id}/arena-config/global` with `{"languages": [...]}`. Alpine `languageSelector()` component. The legacy `language` select in the metadata form is retained for backwards compatibility and extended with kl/sv/no/ru options.

### GR-06 — Missing platforms in credentials dropdown
- [x] `admin/credentials.html` — Added `discord`, `twitch`, `openrouter` to the platform `<select>` dropdown.
- [x] `admin/credentials.html` — Added `x-show` credential field sections for each:
  - Discord: single `bot_token` field with setup instructions linking to discord.com/developers
  - Twitch: two-column `client_id` + `client_secret` grid with OAuth2 Client Credentials note
  - OpenRouter: single `api_key` field (prefix `sk-or-…`) with link to openrouter.ai/keys

**Backend API contracts needed** (to be implemented by Core Engineer, frontend ready):
- `PATCH /query-designs/{design_id}/arena-config/{arena_name}` — JSON body `{ "<field>": [...] }` → 200
- `PATCH /query-designs/{design_id}/arena-config/global` — JSON body `{ "languages": ["da", ...] }` → 200

### GR-16 — Political calendar event overlay on volume-over-time charts
- [x] `static/data/political_calendar.json` — Created with 12 events covering: Danish Folketing spring sitting, Danish General Election (expected June 2026), Denmark EU Council Presidency, Danish Arctic Defence Package, Inatsisartut general election (March 2025), Inatsisartut spring session (March 2026), Inatsisartut autumn session (September 2026), Greenlandic municipal elections, NATO Cold Response exercise, Trump Greenland address, US-Denmark diplomatic summit, NATO Hague Summit. Each event has `id`, `date`, `label`, `category`, `country`, `description`. Four categories with consistent brand colours: election (red), parliament (blue), international (purple), other (gray).
- [x] `api/templates/analysis/index.html` — Loads `chartjs-plugin-annotation@3` from jsDelivr CDN in `{% block extra_head %}` (after Chart.js, before charts.js). Registers the plugin globally via `Chart.register(window.ChartAnnotation)` in an inline `<script>`. Backend TODO comment added for `GET /analysis/calendar-events` future endpoint.
- [x] `api/templates/analysis/index.html` — Compact calendar controls row embedded inside the Volume over time card (single row, gray-50 background, <1rem height). Controls: "Calendar events" master checkbox (`x-model="showCalendarEvents"`), category filter checkboxes (Election / Parliament Session / International Event / Other), country radio buttons (All / Denmark / Greenland / International). All checked/selected by default. Any change triggers `load()`.
- [x] `api/templates/analysis/index.html` — `volumeChart()` Alpine component refactored: `load()` replaced by `init()` entry point that first loads calendar data then renders the chart. Added `_loadCalendarData()` (fetches `/static/data/political_calendar.json`, degrades silently on error), `_filteredEvents(chartLabels)` (applies category/country/date-range filters), and calendar state properties (`showCalendarEvents`, `calendarCategoryFilter`, `calendarCountryFilter`, `calendarCategories`, `calendarCountries`). Filtered events passed as third argument to `initMultiArenaVolumeChart()` / `initVolumeChart()`.
- [x] `static/js/charts.js` — Added `_buildAnnotations(events, chartLabels)` helper: maps each event to a `chartjs-plugin-annotation` `line` annotation; dashed border (4px dash / 3px gap), 1.5px width, rotated label (−90°), low-opacity (0x22 = ~13%) background fill. Events outside the chart's date range are silently excluded via label-range comparison. Plugin presence checked at runtime so the page degrades gracefully if the CDN script fails.
- [x] `static/js/charts.js` — `initVolumeChart(canvasId, data, events = [], options = {})` signature updated; annotations injected into `plugins.annotation.annotations` when plugin is present and events non-empty.
- [x] `static/js/charts.js` — `initMultiArenaVolumeChart(canvasId, data, events = [], options = {})` signature updated; same annotation injection pattern as `initVolumeChart`.
- **Backend API contract (optional future improvement)**: `GET /analysis/calendar-events?date_from=&date_to=` — server-filtered JSON list of events for the given range. Static file approach is sufficient for now.

### GR-17 — Content Browser quick-add actor modal
- [x] `content/browser.html` — Author display names in the content table are now clickable buttons. Clicking any author dispatches a `quick-add-author` custom event (Alpine) that opens the "Quick-Add Source" modal. The modal pre-fills display name, platform, and platform username (falls back to display name when `author_id` is absent). A dropdown fetches actor lists from `GET /query-designs/{design_id}/actor-lists` on modal open; list is empty when no `active_query_design_id` is in scope. Submission POSTs JSON to `POST /actors/quick-add`; on `was_created: false` shows "Already in registry — added to actor list."; on success shows "Added to collection!" and auto-closes after 1.5 s.
- **Backend gap (GR-17)**: `content.py` route `GET /content/` does not yet pass `active_query_design_id` to the template context. The route already receives `query_design_id` as a query param — the fix is adding `"active_query_design_id": str(query_design_id) if query_design_id else ""` to the `TemplateResponse` context dict. Until this is done the actor-list dropdown will render empty.
- **Backend contract needed**: `POST /actors/quick-add` — body `{ display_name, platform, platform_username, actor_type, actor_list_id }`, returns `{ was_created: bool, actor_id: str }`.

### GR-14 — Public Figure pseudonymization bypass toggle (COMPLETE)
- [x] `actors/list.html` — "Add Actor" modal: "Public Figure" toggle switch added below the actor type field. Alpine `x-data="{ publicFigure: false }"` scoped to the form element. Toggle uses amber colour scheme (`bg-amber-500` when on, `bg-gray-200` when off) to signal GDPR significance. Hidden `<input type="hidden" name="public_figure">` carries the boolean value on form submit. Conditional GDPR warning block (`x-show="publicFigure"`) appears with amber background (`bg-amber-50 border-amber-200`) and warning triangle SVG icon when the toggle is on. Warning text: "GDPR Notice: Enabling this bypasses anonymization…". Toggle resets to `false` on successful submit via `hx-on::after-request`.
- [x] `actors/list.html` — Actor table rows: amber "PF" badge (`bg-amber-100 text-amber-800`) added inline next to the actor name when `actor.public_figure` is truthy. Badge has a `title` tooltip: "Public Figure — pseudonymization bypassed (GDPR Art. 89(1))".
- [x] `actors/detail.html` — "Edit Actor" modal: same "Public Figure" toggle pattern as the create form. Alpine state initialised from the Jinja context value (`{{ 'true' if actor.public_figure | default(false) else 'false' }}`), so the toggle reflects the actor's current DB state when the modal opens. Hidden input and GDPR warning block follow the same pattern as the create form.
- [x] `actors/detail.html` — Actor identity card: amber "PF" badge added inline next to the actor name heading when `actor.public_figure` is truthy. Same styling and tooltip as the list view badge.

### GR-22 — Discovered Sources panel
- [x] `content/browser.html` — Added "Discovered Sources" link (with link icon) in the sidebar export section, pointing to `/content/discovered-links`.
- [x] `content/discovered_links.html` — New standalone page. Filter bar (platform dropdown, min-mentions range slider, query design selector) drives HTMX reload of the results container. Results table shows platform badge (colour-coded: Telegram=blue, Reddit=orange, YouTube=red, Bluesky=sky, Discord=indigo, Gab=green, Web=gray) with platform-specific SVG icon, target identifier linked to platform URL when available, source-count badge (colour intensity scales with count), first/last seen dates, and "Add" button per row. Per-row checkboxes with "Select all visible" / "Clear" controls. "Import Selected" button at top POSTs to `POST /actors/quick-add-bulk` with progress indicator and result summary banner (added / skipped / errors). "Load more" button uses HTMX `hx-swap="beforeend"` with offset parameter for incremental loading (25 per page). Inline quick-add modal (same pattern as GR-17) opens pre-filled when "Add" is clicked; actor-list dropdown reads the active query design from the filter bar at open time. Alpine components: `discoveredSources(queryDesignId)` (checkbox map, bulk import, openQuickAdd dispatcher) and `discoveredQuickAdd(queryDesignId)` (modal state, fetchActorLists, submit).
- **Backend contracts needed**:
    - `GET /content/discovered-links?platform&min_count&query_design_id&offset&limit` — returns HTML (full page) or JSON `{ items, total, has_more, next_offset }` for HTMX partial updates. Each item: `{ id, platform, target_identifier, target_url, source_count, first_seen, last_seen }`.
    - `POST /actors/quick-add-bulk` — body `{ sources: [{platform, platform_username, display_name, actor_type}], actor_list_id }`, returns `{ added, skipped, errors }`.

## Remaining / Future Work
- [ ] Tailwind production build (`make css`) to replace CDN dev script
- [ ] End-to-end tests for login flow and collection launcher
- [ ] `_fragments/actor_row.html` — dedicated fragment for HTMX search results swap in actor list
- [ ] Backend API contracts needed for arena config grid:
    - `GET /api/query-designs/{id}/arena-config` → `{ arenas: [{id, enabled, tier}] }`
    - `POST /query-designs/{id}/arena-config` → 200
    - `GET /api/collections/estimate` (already exists in launcher — needs to handle arena config params)
- [ ] Backend API contracts needed for content browser:
    - `GET /content/records?cursor&q&arenas&date_from&date_to&language&search_term&run_id` → HTML fragment (tbody rows + next cursor sentinel)
    - `GET /content/export?[same params]` → CSV download
    - `GET /content/{id}` → renders `content/record_detail.html` partial (or standalone if `Accept: text/html` full page)
- [ ] Backend API contracts needed for actors:
    - `GET /actors/search?q` → HTML fragment (tbody rows)
    - `POST /actors/` → HTML fragment (new actor row)
    - `PATCH /actors/{id}` → HTML fragment (updated profile card)
    - `POST /actors/{id}/presences` → HTML fragment (new presence row)
    - `DELETE /actors/{id}/presences/{pres_id}` → empty (row removed by hx-swap)
    - `GET /actors/{id}/content?cursor` → HTML fragment (content list items)
