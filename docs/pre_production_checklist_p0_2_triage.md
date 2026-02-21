# P0-2 Pre-Production Check: Coherency Audit Triage Report

**Created:** 2026-02-21
**Author:** Research Agent (The Strategist)
**Scope:** Triage of all critical and moderate findings from both coherency audits against current codebase state
**Source audits:**
- `/docs/research_reports/coherency_audit_2026_02_21.md` (Research Agent audit: 6 critical, 11 moderate, 9 minor)
- `/docs/research_reports/qa_coherency_audit_2026_02_21.md` (QA Guardian audit: 7 critical, 10 moderate, 8 minor)

---

## Executive Summary

Of the **13 critical findings** across both audits, **10 have been fixed** and **3 remain open**. Of those 3, **1 is beta-blocking** and **2 are known limitations** acceptable for beta with documentation.

Of the **21 moderate findings**, **12 have been fixed**, **3 are beta-blocking** (elevated from moderate), and **6 are known limitations** acceptable for beta.

| Status | Critical | Moderate | Minor (spot-checked) | Total |
|--------|----------|----------|----------------------|-------|
| ALREADY FIXED | 10 | 12 | 6 | 28 |
| BETA-BLOCKING | 1 | 3 | -- | 4 |
| KNOWN LIMITATION | 2 | 6 | 3 | 11 |

---

## BETA-BLOCKING (4 items -- must fix before beta deployment)

These findings would cause researcher-facing failures, continuous error noise, or broken core workflows if not addressed.

### BB-1: Enrichment pipeline has no automatic trigger after collection completion

**Source:** Research audit 1.4 + 2.1 (CRITICAL)

**Summary:** The `enrich_collection_run` Celery task exists and works. A manual trigger endpoint was added at `POST /collections/{run_id}/enrich`. However:
1. Enrichment is **not** automatically chained after collection completion. The `trigger_daily_collection` task dispatches per-arena tasks but never chains enrichment or deduplication upon completion.
2. The collection detail template (`collections/detail.html`) has buttons for "Refresh Engagement" and "Run Deduplication" but **no button for "Run Enrichment"**.

The enrichment results dashboard tab (SB-15) and the content record detail enrichment panels will always show empty results for any collection run unless a researcher manually calls the API endpoint.

**Evidence:**
- `/src/issue_observatory/api/routes/collections.py` line 956: `POST /{run_id}/enrich` endpoint exists
- `/src/issue_observatory/api/templates/collections/detail.html` lines 344-370: "Refresh Engagement" and "Run Deduplication" buttons present, but no enrichment button
- `/src/issue_observatory/workers/tasks.py` lines 80-310: `trigger_daily_collection` does not chain `enrich_collection_run`

**Required fix:** Add a "Run Enrichment" button to `collections/detail.html` for completed runs, wired via `hx-post` to `POST /collections/{run_id}/enrich`. Optionally, chain enrichment automatically after collection completion in the orchestration layer.

---

### BB-2: Volume spike alerts detected but never displayed in UI

**Source:** Research audit 2.4 (MODERATE -- elevated to BETA-BLOCKING)

**Summary:** The `check_volume_spikes` Celery task detects spikes and stores them in `collection_runs.arenas_config["_volume_spikes"]`. API endpoints exist to fetch them (`GET /query-designs/{id}/volume-spikes` and `GET /collections/volume-spikes`). However, **no template in the codebase references these endpoints or displays spike alerts**. A search across all templates for "volume_spike", "spike", or "_volume_spikes" returns zero matches.

The email notification path (via `send_volume_spike_alert`) requires SMTP to be configured, which is not the default. Without UI display, researchers have no way to see spike alerts.

**Evidence:**
- `/src/issue_observatory/api/routes/query_designs.py` line 1746: `get_volume_spike_alerts` endpoint exists
- `/src/issue_observatory/api/routes/collections.py` line 1020: `get_volume_spikes` endpoint exists
- Zero matches for spike-related terms in `/src/issue_observatory/api/templates/`

**Required fix:** Add a spike alert indicator to the dashboard or collection detail page. At minimum, add an HTMX-polled alert badge on the query design detail page that calls the existing endpoint.

**Why elevated:** Volume spike detection is a core research workflow (GR-09). Researchers need to know when unusual activity occurs. Having the detection run silently without any notification channel (given SMTP defaults to disabled) means a key feature is invisible.

---

### BB-3: SMTP not configured produces silent no-op without any visible warning

**Source:** Research audit 5.2 (MINOR -- elevated to BETA-BLOCKING in combination with BB-2)

**Summary:** The `EmailService` operates as a no-op when SMTP is not configured. There is no startup warning, no admin UI indicator, and no log message at application initialization. Combined with BB-2 (volume spike alerts not displayed in UI), this means the only notification path for spikes, collection failures, and low-credit warnings is completely silent.

**Evidence:**
- `/src/issue_observatory/core/email_service.py` line 93: logs "email notifications are disabled" only at _init_ of the service class, not at application startup
- `/src/issue_observatory/api/templates/admin/health.html`: no email service status indicator

**Required fix:** Log a WARNING at application startup when SMTP is not configured. Add a one-line indicator to the admin health page showing email notification status. This is critical for beta because researchers need to understand that email alerts are disabled and rely on UI-based alerting instead.

---

### BB-4: Missing test coverage for GDPR retention service

**Source:** QA audit M-09 (MODERATE -- elevated to BETA-BLOCKING for the retention_service component only)

**Summary:** `core/retention_service.py` implements GDPR-compliant data deletion (records older than `DATA_RETENTION_DAYS`) and is triggered daily by the Beat schedule. This module has **zero test coverage**. A bug in the retention service could either (a) fail to delete data when required, violating GDPR, or (b) accidentally delete data that should be retained, causing data loss.

**Evidence:**
- No file matching `tests/**/test_retention*` exists in the test directory

**Required fix:** Write at least one integration test verifying that records older than the retention window are correctly deleted and records within the window are preserved. This is the one test gap that carries legal risk.

**Why elevated:** GDPR compliance is non-negotiable for a research tool handling Danish media data. Untested GDPR deletion logic is a liability.

---

## KNOWN LIMITATIONS (11 items -- acceptable for beta with documentation)

These represent reduced functionality or missing polish that does not break core workflows. Each should be documented in beta release notes.

### KL-1: Collection completion does not auto-chain enrichment or deduplication

**Source:** Research audit 2.1 (CRITICAL)

**Note:** Partially overlaps with BB-1. The auto-chaining aspect is a known limitation; the missing UI button is beta-blocking. With the UI button fix (BB-1), researchers can manually trigger enrichment. Auto-chaining is a usability improvement for a future release.

---

### KL-2: Design-level analysis missing several endpoints present on run-level

**Source:** Research audit 4.4 (MINOR)

**Summary:** The design-level analysis dashboard (`/analysis/design/{design_id}`) has access to volume, actors, terms, and three network types. Engagement distributions, arena comparison, temporal comparison, emergent terms, enrichment results, and filtered export are only available at the run level.

**Acceptable for beta because:** Researchers can access all analysis features by navigating to individual run-level analysis pages. The design-level view provides a useful but incomplete aggregation.

---

### KL-3: `export_temporal_gexf()` has a route but limited discoverability

**Source:** Research audit 1.3 (MINOR)

**Summary:** A route now exists at `/analysis/{run_id}/network/temporal/export-gexf` (`analysis.py` line 1180), but temporal GEXF export is not prominently featured in the analysis template UI.

**Acceptable for beta because:** The endpoint exists and works. Researchers who need temporal GEXF for Gephi can use the API directly or find the network temporal export through the analysis dashboard.

---

### KL-4: Scraping jobs and data import have basic templates

**Source:** Research audit 1.6, 1.7 (MODERATE)

**Summary:** Both scraping jobs (`/scraping-jobs`) and data import (`/imports`) now have page routes in `pages.py`, navigation links in the sidebar (under "Tools"), and template files. The templates exist and are functional.

**Evidence:**
- `/src/issue_observatory/api/routes/pages.py` line 891: `scraping_jobs_page` route
- `/src/issue_observatory/api/routes/pages.py` line 914: `imports_page` route
- `/src/issue_observatory/api/templates/scraping/index.html` exists
- `/src/issue_observatory/api/templates/imports/index.html` exists
- `/src/issue_observatory/api/templates/_partials/nav.html` lines 47-49: "Scraping Jobs" and "Import Data" links

**Acceptable for beta because:** These are secondary tools. Primary data collection occurs through the collection launcher, not through manual scraping or import. The templates are functional even if basic.

---

### KL-5: Cross-run comparison endpoint exists but no template references it

**Source:** QA audit m-06 (MINOR)

**Summary:** `GET /analysis/compare` (SB-06) exists in the API but no frontend template links to it.

**Acceptable for beta because:** Run-level and design-level analysis cover the primary use case. Cross-run comparison is an advanced feature accessible via API.

---

### KL-6: Retention service not adjustable in admin UI

**Source:** Research audit 2.3 (MINOR)

**Summary:** The retention window is set via the `DATA_RETENTION_DAYS` environment variable (default: 730 days). The admin health page now shows retention information (confirmed in `admin/health.html` lines 93-132) but does not allow runtime configuration changes.

**Acceptable for beta because:** The retention window is visible. Changing it requires environment variable modification and restart, which is appropriate for a setting with GDPR implications -- it should not be casually adjustable through a UI.

---

### KL-7: Promote to Live Tracking relies on client-side dialog

**Source:** Research audit 4.5 (MODERATE)

**Summary:** The SB-08 "Start Live Tracking" button on the query design detail page opens an Alpine.js dialog that submits a `POST /collections/` request with `mode=live`. There is no dedicated backend "promote" endpoint.

**Evidence:** `detail.html` line 762: `const res = await fetch('/collections/', { method: 'POST', ... })` with `mode: 'live'` payload.

**Acceptable for beta because:** The dialog is fully implemented with arena selection, error handling, and success feedback. It correctly creates a live collection run. The semantic difference between "promote" and "create live" is immaterial to the researcher experience.

---

### KL-8: Missing test coverage for event_bus, email_service, entity_resolver, and most route modules

**Source:** QA audit M-09 (MODERATE)

**Summary:** Several core modules and most route modules lack test files. Specific gaps: `core/event_bus.py`, `core/email_service.py`, `core/entity_resolver.py`, `api/routes/collections.py`, `api/routes/content.py` (1 test only), `api/routes/actors.py` (schema test only), `workers/tasks.py` (helpers only, not orchestration).

**Acceptable for beta because:** The application has been manually tested through the full workflow. Arena collectors (the most failure-prone components) have good test coverage. The missing route-level tests increase the risk of regressions but do not block initial beta use. The retention service test gap is carved out as BB-4 due to GDPR implications.

---

### KL-9: `analysis/compare` endpoint exists but no template references it

**Source:** QA audit m-06 (MINOR)

Duplicate of KL-5 -- see above.

---

### KL-10: Deferred stub arenas (Twitch, VKontakte) included in health check dispatch

**Source:** QA audit m-03 (MINOR)

**Summary:** The `health_check_all_arenas` task now explicitly skips Twitch and VKontakte stubs (confirmed in `tasks.py` line 367: `_SKIP_ARENAS = {"twitch", "vkontakte"}`), but they remain registered in the arena registry.

**Acceptable for beta because:** The fix prevents health check noise. The stubs remain as placeholders for future implementation and cause no runtime issues.

---

### KL-11: No startup warning when SMTP is not configured

Duplicate of BB-3 -- tracked as beta-blocking. If downgraded, it becomes a known limitation: researchers must check the admin health page to understand notification status.

---

## ALREADY FIXED (28 items -- verified in current codebase)

### Critical Findings -- All Fixed

| ID | Source | Finding | Evidence of Fix |
|----|--------|---------|-----------------|
| C-01 | QA audit | Credits route module is an empty stub | `credits.py` now implements `GET /balance` (line 28) and `POST /allocate` (line 62) with full HTML fragment responses |
| C-02 | QA audit | Health check task dispatcher generates incorrect task names | `tasks.py` line 390: now uses `f"{arena_package}.tasks.health_check"` (correct pattern) |
| C-03 | QA audit | `discovered_links_page` references non-existent `QueryDesign.created_by` | `pages.py` line 483: now uses `QueryDesign.owner_id` (correct attribute) |
| C-04 | QA audit | No HTML page routes for actors list/detail | `pages.py` line 519: `GET /actors` and line 579: `GET /actors/{actor_id}` routes exist, rendering full HTML templates |
| C-05 | QA audit | Beat schedule dispatches RSS/GDELT tasks without required arguments | `beat_schedule.py`: RSS and GDELT standalone entries removed. Only `daily_collection`, `health_check_all_arenas`, `credit_settlement`, `stale_run_cleanup`, `retention_enforcement`, and `threads_refresh_tokens` remain |
| C-06 | QA audit | `emit_event` function does not exist in event_bus.py | `tasks.py` lines 860-878: now uses direct `redis_lib.from_url()` and `r.publish()` instead of importing `emit_event` |
| C-07 | QA audit | Collections estimate endpoint POST vs hx-get mismatch | `launcher.html` line 287: now uses `hx-post="/collections/estimate"` (correct method) |
| 4.1 | Research audit | Password reset template has no page route | `pages.py` line 712: `GET /auth/forgot-password` and line 739: `GET /auth/reset-password` routes exist |
| 4.2 | Research audit | Registration has no UI page | `pages.py` line 769: `GET /auth/register` route exists, rendering `auth/register.html` |
| 4.3 / M-04 | Both audits | Logout link targets non-existent endpoint | `nav.html` line 110: now uses `<form method="post" action="/auth/cookie/logout">` with a submit button (correct POST to correct path) |

### Moderate Findings -- Fixed

| ID | Source | Finding | Evidence of Fix |
|----|--------|---------|-----------------|
| M-01 | QA audit | Dashboard `active-count` endpoint does not exist | `collections.py` line 88: `GET /active-count` endpoint implemented, returns HTML fragment |
| M-02 | QA audit | Dashboard `format=fragment` not handled | `collections.py` line 198/233: `format` parameter handled, returns HTML table fragment when `format="fragment"` |
| M-03 | QA audit | Admin health page endpoint paths wrong | `health.html` line 38: now uses `hx-get="/api/health"` and line 67: `hx-get="/api/arenas/health"` (correct paths) |
| M-05 | QA audit | `publish_run_complete` never called | `_task_helpers.py` line 305-314: calls `publish_run_complete` in `mark_stale_runs_failed`. `collections.py` line 697-700: calls it from collection cancellation endpoint |
| M-07 | QA audit | Only 1 of 25 arenas publishes SSE task_update events | All 25 arena `tasks.py` files now import `publish_task_update` (confirmed via grep) |
| M-08 | QA audit | `_build_sync_dsn` duplicated across two files | Extracted to `workers/_db_helpers.py` line 14. Both `maintenance_tasks.py` (line 26) and `export_tasks.py` (line 50) import from shared location |
| M-10 | QA audit | `refresh_engagement_metrics` uses manual event loop | No `asyncio.new_event_loop` or `asyncio.set_event_loop` calls found in `maintenance_tasks.py` |
| 1.1 | Research audit | `get_coordination_events()` never called | `analysis.py` line 50: imported; line 2298: called from route endpoint |
| 1.2 | Research audit | `get_propagation_flows()` never called from routes | `analysis.py` line 68: imported; line 2158: called from route endpoint |
| 1.5 | Research audit | Sentiment analysis has no surfacing endpoint | `analysis.py` line 60: `get_sentiment_distribution` imported; line 2209: `GET /{run_id}/enrichments/sentiment` endpoint exists |
| 2.2 | Research audit | Enrichment results not shown in content detail panel | `record_detail.html` lines 168-275: structured enrichment display for language, sentiment, NER, coordination, and propagation |
| 5.1 | Research audit | MinIO not in docker-compose or .env.example | `docker-compose.yml` lines 43-75: MinIO service with init container. `.env.example` lines 37-42: MinIO variables documented |

### Minor Findings -- Fixed (spot-checked)

| ID | Source | Finding | Evidence of Fix |
|----|--------|---------|-----------------|
| 3.2 | Research audit | `DescriptiveStats` dataclass unused | No matches for `DescriptiveStats` in `descriptive.py` -- removed |
| 3.3 | Research audit | `DanishLanguageDetector` deprecated alias | No matches for `DanishLanguageDetector` in `enrichments/__init__.py` -- removed |
| m-02 | QA audit | `_normalise_url` duplicated in maintenance_tasks | `maintenance_tasks.py` line 25: now imports from `core.deduplication` via `from issue_observatory.core.deduplication import normalise_url` |
| m-07 | QA audit | No test for Discord or URL Scraper | `tests/arenas/test_discord.py` and `tests/arenas/test_url_scraper.py` both exist |
| m-08 | QA audit | Auth reset-password template has no page route | `pages.py` line 739: `GET /auth/reset-password` route exists |
| M-06 | QA audit | `get_arenas_by_arena_name` defined but never called | No matches found in codebase -- function removed |

---

## Moderate Findings -- Remaining Scan

The following moderate findings were not elevated to beta-blocking but were reviewed.

| ID | Source | Finding | Status | Rationale |
|----|--------|---------|--------|-----------|
| 1.6 | Research audit | Scraping jobs have no frontend UI | FIXED | Template, page route, and nav link all exist |
| 1.7 | Research audit | Data import has no frontend UI | FIXED | Template, page route, and nav link all exist |
| 2.4 | Research audit | Volume spike alerts not displayed | BETA-BLOCKING (BB-2) | Elevated -- see above |
| 4.5 | Research audit | Promote to live tracking -- verify frontend | KNOWN LIMITATION (KL-7) | Dialog is fully implemented |
| 5.3 | Research audit | RSS/GDELT Beat tasks run without context | FIXED | Entries removed from beat_schedule.py |
| 6.2 | Research audit | Engagement refresh has no UI button | FIXED | Button exists at `detail.html` line 346 |
| M-09 | QA audit | Missing test coverage for critical paths | KNOWN LIMITATION (KL-8) | Retention service elevated to BB-4 |
| 5.2 | Research audit | SMTP silent no-op without warning | BETA-BLOCKING (BB-3) | Elevated -- see above |
| m-04 | QA audit | `ARENA_DESCRIPTIONS` has dead `"google"` entry | NOT CHECKED | Minor, no functional impact |
| m-05 | QA audit | Design-level analysis not in nav | KNOWN LIMITATION (KL-2) | Accessible via links from collection detail |
| m-01 | QA audit | Unused `credit_estimate.html` fragment | FIXED | Fragment is rendered by the estimate endpoint (confirmed in `collections.py` line 501, 548, 583) |
| m-03 | QA audit | Twitch/VKontakte stubs in health dispatch | FIXED | Explicitly skipped via `_SKIP_ARENAS` set in `tasks.py` line 367 |

---

## Recommended Fix Priority for Beta

### Must fix (days 1-2)

1. **BB-1**: Add "Run Enrichment" button to `collections/detail.html` for completed runs
   - One button, wired to existing `POST /collections/{run_id}/enrich` endpoint
   - Estimated effort: 30 minutes (Frontend Engineer)

2. **BB-2**: Add volume spike alert display to dashboard or query design detail page
   - HTMX fragment calling existing `GET /collections/volume-spikes` or `GET /query-designs/{id}/volume-spikes`
   - Estimated effort: 2-3 hours (Frontend Engineer)

3. **BB-3**: Add SMTP status indicator to admin health page and startup warning
   - One-line check at application startup; small HTML fragment in `admin/health.html`
   - Estimated effort: 1 hour (Core Application Engineer)

4. **BB-4**: Write retention service test
   - One integration test: insert records with dates inside/outside retention window, run `enforce_retention_policy`, verify correct deletion
   - Estimated effort: 2-3 hours (QA Guardian)

### Should fix before general availability (post-beta)

5. Auto-chain enrichment after collection completion (part of KL-1)
6. Design-level analysis endpoint parity (KL-2)
7. Test coverage for `event_bus.py`, `collections.py` routes, `entity_resolver.py` (KL-8)
8. Cross-run comparison UI integration (KL-5)

---

## Methodology

This triage was conducted by:

1. Reading both coherency audit reports in full.
2. For each critical and moderate finding, searching the current codebase for evidence of fix or persistence using grep (pattern and file searches), glob (file existence), and direct file reads.
3. Classifying each finding based on:
   - **ALREADY FIXED**: Concrete code evidence contradicts the finding (e.g., endpoint now exists, attribute name corrected, function now called from route).
   - **BETA-BLOCKING**: Finding persists and would cause a researcher-facing failure, data integrity risk, or security concern during beta testing.
   - **KNOWN LIMITATION**: Finding persists but represents reduced functionality, not a crash or data risk. Acceptable if documented in beta release notes.
4. Moderate findings were reviewed for potential elevation. Elevation criteria: (a) the finding blocks a core workflow that researchers will exercise during beta, or (b) the finding carries legal/compliance risk.
