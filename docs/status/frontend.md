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
