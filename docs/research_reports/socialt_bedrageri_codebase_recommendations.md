# Codebase Recommendations -- "Socialt Bedrageri" Scenario Findings

Date: 2026-02-20
Source: UX test report at `/docs/ux_reports/socialt_bedrageri_mapping_report.md`
Scope: Actionable codebase improvements derived from the "socialt bedrageri" (social benefits fraud) multi-step workflow evaluation
Author: Research Strategist agent

---

## Overview

The "socialt bedrageri" UX test evaluated the Issue Observatory's ability to support a researcher mapping an unfamiliar issue from scratch through progressive discovery. Unlike previous evaluations that focused on topic-specific coverage or feature correctness, this test targeted **multi-step workflow quality**: the iterative cycle of collect → analyze → discover → refine → re-collect → track.

The evaluation revealed 22 friction points (8 Major, 12 Minor, 2 Cosmetic). This document translates those findings into prioritized, implementable codebase recommendations organized by architectural theme.

---

## Theme 1: Discovery Feedback Loop (Critical)

**Problem:** The application generates excellent discovery intelligence (suggested terms via TF-IDF, discovered links via link mining, snowball sampling results) but lacks the UI actions to feed discoveries back into the query design without manual copy-paste workflows across pages.

### Recommendation SB-01: One-Click Term Addition from Analysis Dashboard

**Priority:** P0 (Critical)
**Effort:** Small-Medium
**Affected files:**
- `src/issue_observatory/api/routes/analysis.py` -- add term-addition endpoint or modify suggested-terms response
- `src/issue_observatory/api/templates/analysis/dashboard.html` -- add "Add to design" button per suggested term
- `src/issue_observatory/api/routes/query_designs.py` -- existing `POST /{id}/terms` endpoint can be reused

**Implementation approach:**
The `GET /analysis/{run_id}/suggested-terms` response already includes the `query_design_id` of the associated design. Add an HTMX button per suggested term that calls `POST /query-designs/{design_id}/terms` with the term value and a default `term_type: "keyword"` and `group_label: "discovered"`. The button should show inline success/failure feedback and gray out after successful addition.

**Acceptance criteria:**
- Each suggested term in the analysis dashboard has an "Add" button
- Clicking "Add" creates a SearchTerm on the associated query design with `group_label: "auto_discovered"`
- The button shows "Added" state and becomes disabled after successful addition
- Terms already in the query design are pre-marked as "Already added"

### Recommendation SB-02: One-Click Source Addition from Discovered Links

**Priority:** P0 (Critical)
**Effort:** Medium
**Affected files:**
- `src/issue_observatory/api/templates/content/discovered_links.html` (or equivalent rendering)
- `src/issue_observatory/api/routes/query_designs.py` -- existing `PATCH /{id}/arena-config/{arena_name}` can be reused
- New: lightweight JS/Alpine action to call the PATCH endpoint with the discovered identifier

**Implementation approach:**
The `GET /content/discovered-links` response groups links by platform slug. For each discovered Telegram channel, Reddit subreddit, YouTube channel, or RSS feed URL, add an "Add to [Design Name]" button that calls `PATCH /query-designs/{design_id}/arena-config/{arena_name}` to append the identifier to the relevant custom list (`custom_channels`, `custom_subreddits`, `custom_feeds`).

Requires a design selector if the user has multiple designs. The simplest approach: scope the discovered links view to a specific query design (already supported via `query_design_id` parameter) and use that design for the PATCH target.

**Acceptance criteria:**
- Each discovered link shows an "Add to [arena] config" button when the platform is a source-list arena
- Clicking the button appends the identifier to the appropriate arenas_config list
- Success feedback shown inline
- Already-configured identifiers are marked "Already tracked"

### Recommendation SB-03: Post-Collection Discovery Notification

**Priority:** P1 (High)
**Effort:** Small
**Affected files:**
- `src/issue_observatory/api/templates/collections/detail.html` -- add summary section
- `src/issue_observatory/workers/tasks.py` -- emit discovery counts via event bus after enrichment

**Implementation approach:**
After a collection run completes and enrichments finish, summarize discovery potential: "This run found 12 suggested new terms, 5 cross-platform links (3 Telegram, 1 YouTube, 1 Reddit)." Display this on the collection detail page with links to the analysis dashboard's suggested-terms view and the discovered-links page.

---

## Theme 2: Temporal Capability Transparency (Critical)

**Problem:** Researchers cannot determine which arenas support historical date-range queries and which silently ignore date parameters. This causes wasted batch collections and confused expectations.

### Recommendation SB-04: Arena Temporal Capability Metadata

**Priority:** P0 (Critical)
**Effort:** Small
**Affected files:**
- `src/issue_observatory/arenas/base.py` -- add `temporal_mode` class attribute to `ArenaCollector`
- All arena `collector.py` files -- set `temporal_mode` value
- `src/issue_observatory/arenas/registry.py` -- include `temporal_mode` in registry metadata
- `src/issue_observatory/api/routes/arenas.py` -- include in arena list response

**Implementation approach:**
Add a `temporal_mode` enum attribute to `ArenaCollector` with values:
- `"historical"` -- supports date_from/date_to filtering (GDELT, Common Crawl, Wayback, TikTok, Event Registry)
- `"recent"` -- returns recent content regardless of date parameters (Reddit, Google Search, Bluesky, Threads)
- `"forward_only"` -- collects at poll/stream time only (RSS, Via Ritzau, Wikipedia revisions)
- `"mixed"` -- partial date support (YouTube)

Each collector declares its temporal mode. The arena registry includes this in its metadata output. The arena grid and collection launcher display the badge.

**Acceptance criteria:**
- All 21 functional collectors declare `temporal_mode`
- Arena list endpoint includes `temporal_mode` in response
- Arena configuration grid shows temporal badge per arena
- Collection launcher shows temporal capability per enabled arena

### Recommendation SB-05: Date Range Warning on Collection Launch

**Priority:** P1 (High)
**Effort:** Small
**Affected files:**
- `src/issue_observatory/api/templates/collections/launcher.html` -- add warning banner
- `src/issue_observatory/api/routes/collections.py` -- add validation/warning in create_collection_run

**Implementation approach:**
When creating a batch collection run with `date_from`/`date_to`, check the enabled arenas' `temporal_mode`. If any arena has `temporal_mode: "recent"` or `"forward_only"`, include a warning in the response: "The following arenas will not respect your date range: [list]. They will return recent/current content only."

On the launcher template, display this warning dynamically when the user selects batch mode with date parameters and has non-historical arenas enabled.

---

## Theme 3: Iterative Workflow Support (High Priority)

**Problem:** Analysis is locked to individual collection runs. Researchers iterating through multiple collection rounds cannot compare runs or see aggregate design-level statistics.

### Recommendation SB-06: Cross-Run Comparison Endpoint

**Priority:** P1 (High)
**Effort:** Medium
**Affected files:**
- `src/issue_observatory/api/routes/analysis.py` -- new comparison endpoint
- `src/issue_observatory/analysis/descriptive.py` -- new comparison functions
- New template or dashboard tab for comparison view

**Implementation approach:**
Add `GET /analysis/compare?run_ids=id1,id2` that returns:
- Volume delta (total records per run, per arena)
- New actors in run 2 not seen in run 1
- New terms matched in run 2 not in run 1
- Overlap percentage (shared content records via content_hash)

This reuses existing `get_run_summary`, `get_top_actors`, and `get_top_terms` functions with a diff layer.

### Recommendation SB-07: Design-Level Analysis Aggregation

**Priority:** P1 (High)
**Effort:** Medium-Large
**Affected files:**
- `src/issue_observatory/api/routes/analysis.py` -- new design-scoped endpoints
- `src/issue_observatory/analysis/descriptive.py` -- modify queries to accept `query_design_id` without `run_id`

**Implementation approach:**
Add `GET /analysis/design/{design_id}/summary`, `/volume`, `/actors`, `/terms` endpoints that aggregate across all completed runs for a query design. This is a natural extension -- the underlying queries in `descriptive.py` already filter by `collection_run_id`, and can be modified to join through `collection_runs.query_design_id` instead.

### Recommendation SB-08: "Promote to Live Tracking" Action

**Priority:** P1 (High)
**Effort:** Small
**Affected files:**
- `src/issue_observatory/api/templates/query_designs/detail.html` -- add button
- No new backend logic needed -- uses existing `POST /collections/` with `mode: "live"`

**Implementation approach:**
On the query design detail page, when at least one completed batch run exists, show a "Start Live Tracking" button. This button opens a lightweight confirmation dialog showing: (1) which arenas are configured, (2) the default tier, (3) a note that date range is not applicable for live mode. On confirm, it calls `POST /collections/` with `query_design_id`, `mode: "live"`, and the design's default tier/arenas_config.

---

## Theme 4: Source Discovery Assistance (High Priority)

**Problem:** Source-list arenas (RSS, Telegram, Reddit, Discord, Wikipedia) require the researcher to know their sources before first collection. There are no in-app discovery tools for the cold-start problem.

### Recommendation SB-09: RSS Feed Autodiscovery

**Priority:** P2 (Medium)
**Effort:** Medium
**Affected files:**
- New: `src/issue_observatory/arenas/rss_feeds/feed_discovery.py`
- `src/issue_observatory/api/routes/query_designs.py` -- new endpoint or integrate into arena-config flow
- `src/issue_observatory/api/templates/query_designs/editor.html` -- add discovery UI to RSS panel

**Implementation approach:**
Given a website URL, attempt to discover RSS/Atom feed URLs by:
1. Fetching the page and parsing `<link rel="alternate" type="application/rss+xml">` tags
2. Checking common paths: `/rss`, `/feed`, `/atom.xml`, `/feeds/posts/default`
3. Returning a list of discovered feed URLs with titles

Add a "Find feeds" button in the RSS custom feeds panel. The researcher pastes a website URL (e.g., `https://socialtbedrageri.dk` or `https://udbetaling.dk`), and the tool returns any discoverable RSS feeds for one-click addition.

### Recommendation SB-10: Reddit Subreddit Suggestion

**Priority:** P2 (Medium)
**Effort:** Small
**Affected files:**
- New: utility function in `src/issue_observatory/arenas/reddit/` or in the query_designs route
- `src/issue_observatory/api/templates/query_designs/editor.html` -- add "Suggest subreddits" to Reddit panel

**Implementation approach:**
Use Reddit's subreddit search API (`GET /subreddits/search?q=...`) with the query design's search terms to suggest potentially relevant subreddits. Display results in the Reddit configuration panel with one-click add buttons. This is a FREE-tier Reddit API call.

### Recommendation SB-11: AI Chat Search as Discovery Accelerator

**Priority:** P2 (Medium)
**Effort:** Small (mostly UX/documentation)
**Affected files:**
- `src/issue_observatory/api/templates/query_designs/editor.html` or explore page
- Documentation

**Implementation approach:**
The AI Chat Search arena already queries LLMs via OpenRouter. Reposition it as a discovery tool in the UI: "Use AI to discover related terms, actors, and sources for your research topic." Add a dedicated "AI Discovery" button on the query design page that runs a focused AI Chat Search query like "Who are the key Danish actors discussing [search terms]? What media outlets cover this topic?" and presents results as suggested additions to the query design.

---

## Theme 5: Batch-to-Live Transition Guidance (Medium Priority)

**Problem:** The conceptual model of "explore with batch, then track with live" is clear in the code but not communicated to the researcher.

### Recommendation SB-12: Exploration Mode Indicator

**Priority:** P2 (Medium)
**Effort:** Small
**Affected files:**
- `src/issue_observatory/api/templates/collections/launcher.html` -- add mode explanation
- `src/issue_observatory/api/templates/query_designs/detail.html` -- add lifecycle indicator

**Implementation approach:**
Add a lightweight "Research Lifecycle" indicator to the query design detail page showing the current stage:

1. **Design** -- Query design created, no collections yet
2. **Exploring** -- At least one batch run completed, no live runs
3. **Tracking** -- Active live tracking run exists
4. **Paused** -- Live tracking run is suspended

This is purely derived from the existing collection run data (no new schema needed). Display it as a horizontal stepper/breadcrumb on the detail page.

### Recommendation SB-13: Content Source Labeling

**Priority:** P2 (Medium)
**Effort:** Small
**Affected files:**
- `src/issue_observatory/api/templates/content/browser.html` -- add filter/label
- `src/issue_observatory/api/routes/content.py` -- add collection mode filter parameter

**Implementation approach:**
The content browser already shows `collection_run_id` per record. Add a filter dropdown "Collection mode: All / Batch / Live" that filters content by the associated run's `mode` field. Also display a small badge ("Batch" / "Live") on each content card, so the researcher can distinguish exploratory data from tracking data.

---

## Theme 6: Cost Transparency (Medium Priority)

### Recommendation SB-14: Implement Credit Estimation

**Priority:** P1 (High)
**Effort:** Medium
**Affected files:**
- `src/issue_observatory/core/credit_service.py` -- implement estimation logic
- `src/issue_observatory/api/routes/collections.py` -- update estimate endpoint

**Implementation approach:**
The `POST /collections/estimate` endpoint and `CreditEstimateRequest`/`CreditEstimateResponse` schemas already exist. Implement the estimation logic based on:
- Number of enabled arenas per tier
- Number of active search terms
- Date range (for batch mode)
- Historical cost data from previous runs (if available)

Even rough estimates ("~50-100 credits for this configuration") would be vastly better than the current zero-return stub.

---

## Theme 7: Analysis Enrichment Visibility (Low Priority)

### Recommendation SB-15: Enrichment Results Dashboard Tab

**Priority:** P3 (Low)
**Effort:** Medium
**Affected files:**
- `src/issue_observatory/api/routes/analysis.py` -- new endpoints for enrichment summaries
- `src/issue_observatory/api/templates/analysis/dashboard.html` -- new tab

**Implementation approach:**
Add an "Enrichments" tab to the analysis dashboard that surfaces:
- **Language detection**: Distribution of detected languages across the corpus
- **Named entities**: Most frequent entities extracted by the NER enricher
- **Propagation patterns**: Stories that propagated across 2+ arenas with timestamps
- **Coordination signals**: Any coordinated posting patterns detected

These results currently live in `raw_metadata.enrichments.*` and are only accessible through content export. A summary view with drill-down to specific records would make enrichments a first-class analysis feature.

### Recommendation SB-16: Annotation Codebook Management

**Priority:** P3 (Low)
**Effort:** Medium
**Affected files:**
- New: `src/issue_observatory/core/models/annotations.py` -- add Codebook model
- `src/issue_observatory/api/routes/annotations.py` -- CRUD for codebook entries
- `src/issue_observatory/api/templates/annotations/` -- codebook management UI

**Implementation approach:**
Add a `Codebook` model with `code`, `label`, `description`, and `query_design_id` fields. When annotating content, present the codebook codes as a dropdown instead of free-text input. This enforces coding consistency, which is essential for systematic qualitative analysis of welfare fraud framing (e.g., "punitive_frame", "empathetic_frame", "systemic_failure").

---

## Implementation Priority Matrix

| ID | Recommendation | Priority | Effort | Theme |
|----|---------------|----------|--------|-------|
| SB-01 | One-click term addition from suggested terms | P0 | Small-Medium | Discovery loop |
| SB-02 | One-click source addition from discovered links | P0 | Medium | Discovery loop |
| SB-04 | Arena temporal capability metadata | P0 | Small | Temporal transparency |
| SB-05 | Date range warning on collection launch | P1 | Small | Temporal transparency |
| SB-06 | Cross-run comparison endpoint | P1 | Medium | Iterative workflow |
| SB-07 | Design-level analysis aggregation | P1 | Medium-Large | Iterative workflow |
| SB-08 | "Promote to live tracking" button | P1 | Small | Workflow transition |
| SB-14 | Implement credit estimation | P1 | Medium | Cost transparency |
| SB-03 | Post-collection discovery notification | P1 | Small | Discovery loop |
| SB-09 | RSS feed autodiscovery | P2 | Medium | Source discovery |
| SB-10 | Reddit subreddit suggestion | P2 | Small | Source discovery |
| SB-11 | AI Chat Search as discovery accelerator | P2 | Small | Source discovery |
| SB-12 | Exploration mode / lifecycle indicator | P2 | Small | Workflow transition |
| SB-13 | Content source labeling (batch/live) | P2 | Small | Data organization |
| SB-15 | Enrichment results dashboard tab | P3 | Medium | Analysis visibility |
| SB-16 | Annotation codebook management | P3 | Medium | Annotation |

---

## Relationship to Existing Roadmap Items

| SB Recommendation | Related IP2/GR Item | Status | Notes |
|-------------------|--------------------|---------| ------|
| SB-01 (term addition) | IP2-038 (emergent term extraction) | IP2-038 partially done | SB-01 adds the UI action layer on top |
| SB-04 (temporal metadata) | IP2-001 (dynamic arena grid) | IP2-001 not started | SB-04 could be part of IP2-001 |
| SB-06 (cross-run comparison) | IP2-033 (temporal volume comparison) | IP2-033 not started | SB-06 is a superset |
| SB-07 (design-level analysis) | IP2-037 (arena-comparative analysis) | IP2-037 not started | Complementary |
| SB-14 (credit estimation) | Credit service (partial) | Model exists, route is stub | SB-14 completes the stub |
| SB-15 (enrichment visibility) | IP2-036 (enrichment pipeline) | Pipeline done | SB-15 adds the UI layer |
| SB-16 (codebook) | IP2-043 (content annotations) | Annotations done | SB-16 extends with structured coding |

---

## Conclusion

The "socialt bedrageri" scenario reveals that the Issue Observatory has a strong collection and analysis engine but needs workflow-level improvements to support the iterative discovery process that characterizes real-world research. The most impactful changes are:

1. **Close the discovery feedback loop** (SB-01, SB-02): Allow researchers to act on discoveries without leaving the analysis context.
2. **Make temporal capabilities visible** (SB-04, SB-05): Prevent confusion about what historical data is actually available.
3. **Support iterative refinement** (SB-06, SB-07): Let researchers compare collection rounds and see design-level trends.

These three themes address the core architectural gap: the application is excellent at executing collection and producing analysis, but the connective tissue between analysis results and design refinement is missing. Closing this gap would transform the application from a "collection execution engine" into a genuine "research discovery platform."
