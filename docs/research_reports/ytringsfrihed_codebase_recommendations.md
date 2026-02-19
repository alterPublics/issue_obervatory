# Codebase Improvement Recommendations: "Ytringsfrihed" Discourse Mapping

**Author:** Research & Knowledge Agent (The Strategist)
**Date:** 2026-02-19
**Status:** Final
**Scope:** Implementation-ready recommendations derived from the ytringsfrihed (freedom of speech) UX test report, cross-referenced against the actual codebase and three prior recommendation reports (CO2 afgift, AI og uddannelse, Greenland)

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-19 | Initial report. Synthesized findings from UX test report (18 friction points, 1 blocker, 15 strengths) into 16 prioritized recommendations with code-level implementation guidance. |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Methodology](#2-methodology)
3. [Critical: Workflow-Breaking Issues](#3-critical-workflow-breaking-issues)
4. [High: Significant UX Improvements](#4-high-significant-ux-improvements)
5. [Medium: Quality-of-Life Enhancements](#5-medium-quality-of-life-enhancements)
6. [Low: Polish Items](#6-low-polish-items)
7. [Implementation Roadmap](#7-implementation-roadmap)
8. [Cross-Cutting Concerns](#8-cross-cutting-concerns)
9. [Relationship to Previous Reports](#9-relationship-to-previous-reports)

---

## 1. Executive Summary

The ytringsfrihed UX test evaluated a researcher's complete workflow for mapping freedom-of-speech discourse across all 20 mounted arenas. Unlike previous evaluations that focused on individual feature gaps, this test revealed a systematic pattern: **the application's individual features are strong, but the transitions between steps in a multi-arena research workflow are where the experience breaks down**.

The UX test identified 18 friction points, 1 functional blocker, and 15 strengths. The most impactful finding is that the application operates as a "collection execution engine" rather than a "discovery assistant" -- it assumes the researcher already knows exactly what to configure, rather than supporting the iterative explore-search-expand-collect cycle that discourse research requires.

This report synthesizes those findings into 16 implementation-ready recommendations, organized by priority tier. The recommendations prioritize **cross-arena workflow integration** over individual feature enhancements, following the UX tester's emphasis that multi-step workflows, cross-arena data integration, and progressive discovery are the most important areas for investment.

### Key Themes

1. **Per-arena search term scoping (YF-01)** is the single most impactful architectural change. The shared search term list contaminating irrelevant arenas is a fundamental design limitation that affects every multi-lingual research scenario.

2. **Source-list arena configuration UI (YF-03)** is a functional blocker. Arenas requiring researcher-curated source lists (Telegram, Reddit custom subreddits, RSS custom feeds) cannot be configured without API calls, effectively locking out non-technical researchers from critical platforms.

3. **Bulk data entry (YF-04, YF-08)** is a prerequisite for any serious research workflow. Adding 18 search terms or 8 actors one at a time is incompatible with systematic research practice.

4. **Cross-run analysis (YF-06)** is essential for iterative research. Scoping analysis to a single collection run prevents researchers from examining their full corpus after multiple collection cycles.

5. **Exploration mode (YF-05)** addresses the fundamental orientation gap: researchers need to understand what the platform can do before committing to a query design.

### Effort Summary

| Priority | Count | Estimated Total Effort |
|----------|-------|----------------------|
| Critical | 2 recommendations | 5-8 days |
| High | 5 recommendations | 12-19 days |
| Medium | 6 recommendations | 9-17 days |
| Low | 3 recommendations | 3-5 days |
| **Total** | **16 recommendations** | **29-49 days** |

---

## 2. Methodology

### Documents Reviewed

| Document | Path | Relevance |
|----------|------|-----------|
| Ytringsfrihed UX test report | `/docs/ux_reports/ytringsfrihed_mapping_report.md` | Primary source: 18 friction points, 1 blocker, 15 strengths |
| CO2 afgift codebase recommendations | `/docs/research_reports/co2_afgift_codebase_recommendations.md` | Format reference; prior recommendations for cross-referencing |
| AI og uddannelse codebase recommendations | `/docs/research_reports/ai_uddannelse_codebase_recommendations.md` | Format reference; Marres-style methodology requirements |
| Greenland codebase recommendations | `/docs/research_reports/greenland_codebase_recommendations.md` | Most recent prior report; GR-01 through GR-22 roadmap items |
| Implementation Plan 2.0 strategy | `/docs/research_reports/implementation_plan_2_0_strategy.md` | Unified roadmap; IP2-xxx cross-references |

### Codebase Files Examined

| File | Relevance |
|------|-----------|
| `src/issue_observatory/core/models/query_design.py` | SearchTerm model -- lacks `target_arenas` field; central to YF-01 |
| `src/issue_observatory/core/schemas/query_design.py` | Pydantic schemas -- SearchTermCreate needs extension for arena scoping |
| `src/issue_observatory/core/models/collection.py` | CollectionRun/CollectionTask models -- `estimated_credits` is always 0 |
| `src/issue_observatory/api/routes/query_designs.py` | CRUD routes -- single-term POST endpoint, no bulk endpoint |
| `src/issue_observatory/api/routes/collections.py` | Estimate endpoint is a stub returning zero credits |
| `src/issue_observatory/api/routes/analysis.py` | All endpoints scoped to `run_id`; no `query_design_id` parameter |
| `src/issue_observatory/api/routes/content.py` | Content browser and discovered-links routes |
| `src/issue_observatory/api/routes/actors.py` | `quick-add-bulk` endpoint exists for discovered links but not for simple name+type actors |
| `src/issue_observatory/api/templates/query_designs/editor.html` | Term add form (single entry); arena grid (no per-arena config panels); actor add form (single entry) |
| `src/issue_observatory/api/templates/collections/launcher.html` | Tier selector without precedence explanation; estimate panel wired to stub |
| `src/issue_observatory/arenas/registry.py` | `list_arenas()` returns metadata including descriptions; `ARENA_DESCRIPTIONS` dict |
| `src/issue_observatory/core/credit_service.py` | CreditService.estimate() documented but stub in route handler |
| `src/issue_observatory/analysis/descriptive.py` | `build_content_filters()` supports optional `query_design_id` -- partial foundation for cross-run analysis |
| `src/issue_observatory/config/danish_defaults.py` | Hardcoded feed/channel/subreddit lists; referenced by arena collectors |

### Evaluation Criteria

Each recommendation is assessed on five dimensions:

1. **Researcher impact**: How significantly does this improve the discourse research workflow?
2. **Implementation complexity**: How many files, models, migrations, and templates must change?
3. **Dependency chain**: Does this block or depend on other recommendations?
4. **Generalizability**: Does this improve the platform for ANY research topic, not just ytringsfrihed?
5. **Cost-effectiveness**: Ratio of researcher value delivered to engineering effort required.

---

## 3. Critical: Workflow-Breaking Issues

### YF-01: Per-Arena Search Term Scoping

**UX Finding:** FP-10 (Critical severity)
**Responsible Components:** core, db, frontend
**Estimated Complexity:** Medium (3-5 days)
**Dependencies:** None (foundational; other recommendations benefit from this)

#### Problem

The `SearchTerm` model (`src/issue_observatory/core/models/query_design.py`, line 148) has no mechanism for restricting a term to specific arenas. All search terms in a query design are dispatched to all enabled arenas. For the "ytringsfrihed" scenario, this means:

- Adding "freedom of speech Denmark" (English, needed for GDELT international coverage) would contaminate Bluesky and Reddit collections with irrelevant English-language results.
- Adding "racismeparagraffen" (a Danish legal term) would be dispatched to Gab and GDELT where it would match nothing, wasting API credits on paid arenas.
- Adding "Grundlovens paragraf 77" (a constitutional reference) is meaningless on TikTok or Telegram but critical for RSS and Google Search.

This is not a ytringsfrihed-specific problem. ANY research topic with distinct Danish and English framings -- which is the majority of Danish discourse research -- faces this contamination issue. The Greenland evaluation (GR-05) partially addressed this by recommending multi-language support, but language alone is insufficient. Even within a single language, different terms are relevant for different arenas.

#### Recommended Implementation

**Step 1: Model change.** Add an optional `target_arenas` column to the `SearchTerm` model:

```
File: src/issue_observatory/core/models/query_design.py

Add to SearchTerm class:
    target_arenas: Mapped[list[str] | None] = mapped_column(
        JSONB,
        nullable=True,
        server_default=sa.text("NULL"),
        comment="Optional list of arena platform_names. NULL = all arenas.",
    )
```

Semantics: when `target_arenas` is NULL (the default), the term is dispatched to all enabled arenas -- preserving backward compatibility. When populated, only arenas whose `platform_name` appears in the list receive this term.

**Step 2: Schema change.** Extend `SearchTermCreate` and `SearchTermRead` in `src/issue_observatory/core/schemas/query_design.py`:

```
Add to SearchTermCreate:
    target_arenas: Optional[list[str]] = Field(
        default=None,
        description="Platform names to restrict this term to. None = all arenas.",
    )
```

**Step 3: Migration.** Alembic migration adding the nullable JSONB column to `search_terms`.

**Step 4: Arena collector dispatch.** Wherever arena collectors receive their term list from the query design, add filtering:

```
terms_for_this_arena = [
    t for t in query_design.search_terms
    if t.is_active and (
        t.target_arenas is None
        or arena_platform_name in t.target_arenas
    )
]
```

This filtering should be applied in the task dispatch layer (likely `src/issue_observatory/workers/tasks.py` or the collection orchestration code) rather than in individual collectors, ensuring consistent behavior across all arenas.

**Step 5: Frontend.** In the query design editor's search term form (`src/issue_observatory/api/templates/query_designs/editor.html`, line 217), add an optional multi-select for target arenas. The arena list should be populated from `list_arenas()`. The default state (no arenas selected) means "all arenas." This should be a secondary, collapsible field so it does not complicate the simple case.

#### Why This Is Critical

Without per-arena term scoping, researchers face an impossible choice: either accept contaminated results across arenas, or create separate query designs per arena (losing cross-arena analysis capabilities). This affects every research scenario, not just ytringsfrihed. The Greenland report identified the same need (see GR-05 for multi-language, but the problem is broader than language).

---

### YF-02: Source-List Arena Configuration UI

**UX Finding:** FP-06 (High severity), BL-01 (Blocker)
**Responsible Components:** frontend, core
**Estimated Complexity:** Medium (2-4 days)
**Dependencies:** None

#### Problem

Several arenas require researcher-curated source lists rather than (or in addition to) keyword search:

| Arena | Configuration Needed | Current UI Support |
|-------|--------------------|--------------------|
| Telegram | Channel usernames | None -- API only via `PATCH /query-designs/{id}/arena-config/telegram` |
| Reddit | Custom subreddits (beyond 4 defaults) | None -- API only |
| RSS Feeds | Custom feed URLs (beyond 30 defaults) | None -- API only |
| Discord | Server/channel IDs | None -- API only |
| Wikipedia | Seed article titles | None -- API only |

The BL-01 blocker specifically flags Telegram: for "ytringsfrihed" research, Telegram is where actors who feel censored on mainstream platforms migrate. It is arguably the most important fringe-platform arena for this topic. But there is no UI pathway for researchers to specify which channels to monitor.

The `PATCH /query-designs/{id}/arena-config/{arena_name}` endpoint already supports storing custom configuration as JSON within `QueryDesign.arenas_config` (a JSONB column). The backend is ready; the UI simply does not expose it.

#### Recommended Implementation

**Step 1: Arena metadata extension.** In `src/issue_observatory/arenas/registry.py`, extend the `list_arenas()` output (or `ARENA_DESCRIPTIONS`) to include a `custom_config_fields` list for each arena. For example:

```python
ARENA_CUSTOM_CONFIG: dict[str, list[dict]] = {
    "telegram": [
        {"field": "custom_channels", "label": "Telegram Channels",
         "type": "list", "placeholder": "channel_username",
         "help": "Enter public channel usernames (without @)"}
    ],
    "reddit": [
        {"field": "custom_subreddits", "label": "Custom Subreddits",
         "type": "list", "placeholder": "SubredditName",
         "help": "Enter subreddit names (without r/)"}
    ],
    "rss_feeds": [
        {"field": "custom_feeds", "label": "Custom RSS Feeds",
         "type": "list", "placeholder": "https://example.com/feed.xml",
         "help": "Enter RSS/Atom feed URLs"}
    ],
    "discord": [
        {"field": "channel_ids", "label": "Discord Channel IDs",
         "type": "list", "placeholder": "1234567890",
         "help": "Enter Discord channel snowflake IDs"}
    ],
    "wikipedia": [
        {"field": "seed_articles", "label": "Wikipedia Seed Articles",
         "type": "list", "placeholder": "Article_Title",
         "help": "Enter Wikipedia article titles to monitor"}
    ],
}
```

**Step 2: Arena grid enhancement.** In the query design editor's arena configuration grid (`src/issue_observatory/api/templates/query_designs/editor.html`), when an arena has `custom_config_fields`, render an expandable panel below the tier selector. This panel should contain text inputs (for lists: a tag-style input or textarea with one entry per line) that populate the arena's custom config.

**Step 3: HTMX save.** When the researcher modifies custom config, use `PATCH /query-designs/{id}/arena-config/{arena_name}` to persist the change. This endpoint already exists and stores the config in the `arenas_config` JSONB column.

**Step 4: Visual distinction.** In the arena grid, arenas with custom config requirements should display a visual indicator (e.g., a "requires configuration" badge or a different card border color) to signal that enabling the arena alone is insufficient -- the researcher must also specify sources. This addresses FP-06 (the grid does not distinguish between search-capable and source-list arenas).

#### Why This Is Critical

This is the only functional blocker identified in the UX test. Non-technical researchers are completely locked out of Telegram, custom Reddit subreddits, custom RSS feeds, Discord, and Wikipedia seed articles. For any research topic where fringe platform monitoring is important (which includes ytringsfrihed, Greenland conspiracy monitoring, and many other scenarios), this blocker prevents the platform from fulfilling its core value proposition.

This recommendation corresponds to GR-01, GR-02, GR-03, and GR-04 from the Greenland report, unified into a single generic mechanism rather than per-arena implementations.

---

## 4. High: Significant UX Improvements

### YF-03: Bulk Search Term Import

**UX Finding:** FP-03 (High severity)
**Responsible Components:** frontend, core
**Estimated Complexity:** Small (1-2 days)
**Dependencies:** Benefits from YF-01 (per-arena scoping) but can be implemented independently

#### Problem

Search terms must be added one at a time through the HTMX form. A researcher with 18 terms (the ytringsfrihed scenario) or 23 terms (the Greenland scenario) faces tedious repetitive entry. Systematic researchers prepare term lists in spreadsheets before using the tool; the tool should accept that workflow.

#### Recommended Implementation

**Option A (minimal): Textarea bulk entry.** Add a "Bulk Add" toggle or button to the search terms panel in `src/issue_observatory/api/templates/query_designs/editor.html` (adjacent to the existing single-term form, around line 217). When activated, show a textarea accepting one term per line. Optionally accept a simple format like `term | type | group_label` for structured entry. On submit, POST each term individually (reusing the existing `POST /query-designs/{id}/terms` endpoint in a loop) via JavaScript.

**Option B (preferred): Backend bulk endpoint.** Add a new route `POST /query-designs/{id}/terms/bulk` in `src/issue_observatory/api/routes/query_designs.py` that accepts an array of `SearchTermCreate` objects:

```python
@router.post("/{design_id}/terms/bulk")
async def add_terms_bulk(
    design_id: uuid.UUID,
    terms: list[SearchTermCreate],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    # Ownership check, then bulk insert
```

The frontend then sends the parsed textarea content as a single request. The response replaces the entire terms list in the UI.

**Option C (CSV upload).** For maximum researcher convenience, add a file upload input that accepts CSV with columns `term, term_type, group_label`. Parse client-side or server-side and use Option B's bulk endpoint. This is lower priority than Options A/B but serves researchers who work in spreadsheets.

#### Cost-Effectiveness

Estimated 1-2 days of effort eliminates a friction point that affects every query design with more than 5 terms. Every research scenario evaluated so far has had 10+ terms. This is one of the highest value-to-effort improvements available.

---

### YF-04: Pre-Flight Credit Estimate Implementation

**UX Finding:** FP-13 (High severity)
**Responsible Components:** core
**Estimated Complexity:** Medium (2-4 days)
**Dependencies:** None

#### Problem

The `POST /collections/estimate` endpoint (`src/issue_observatory/api/routes/collections.py`, line 274) is a stub returning zero credits for all arenas. The code explicitly states: "Stub: CreditService integration deferred to Task 0.8."

For a ytringsfrihed collection across 10+ arenas with both free and paid tiers, the researcher cannot evaluate cost trade-offs before launching. They cannot compare the cost of enabling Google Search (medium) versus GDELT (free) versus Event Registry (medium) for news coverage.

#### Recommended Implementation

The `CreditService` class (`src/issue_observatory/core/credit_service.py`, line 65) already documents the estimation contract:

```
- Free-tier arenas:       0 credits
- YouTube Data API v3:    1 credit = 1 API unit
- Serper.dev:             1 credit = 1 SERP query
- TwitterAPI.io:          1 credit = 1 tweet retrieved
- TikTok Research API:    1 credit = 1 API request
```

**Step 1: Per-arena cost estimation.** Each arena's collector base class (`src/issue_observatory/arenas/base.py`) should implement or document a `estimate_credits(term_count, date_range_days, tier)` class method that returns an estimated credit cost. For free arenas this returns 0. For paid arenas, the estimate is based on:
- Number of search terms
- Date range (longer range = more pages/results)
- Known rate of results per query (arena-specific heuristic)

**Step 2: Route implementation.** Replace the stub in `src/issue_observatory/api/routes/collections.py` (lines 313-320) with logic that:
1. Loads the query design and its search terms
2. Determines the merged arenas config (design-level + launcher override)
3. For each enabled arena, calls the arena's credit estimator
4. Sums per-arena estimates into a total
5. Checks the user's available credit balance
6. Returns `CreditEstimateResponse` with real values

**Step 3: UI integration.** The collection launcher template (`src/issue_observatory/api/templates/collections/launcher.html`) already has an estimate panel wired to `requestEstimate()`. Once the backend returns real data, the UI will display it without additional frontend work.

Even approximate estimates (order-of-magnitude) are vastly better than the current zero. Document that estimates are heuristic-based and actual costs may vary.

---

### YF-05: Ad-Hoc Exploration Mode

**UX Finding:** FP-02 (High severity)
**Responsible Components:** frontend
**Estimated Complexity:** Medium (3-5 days)
**Dependencies:** None (uses existing arena `/collect` endpoints)

#### Problem

There is no way for a researcher to try a quick query before committing to a formal query design. A researcher who wants to explore what associations exist around "ytringsfrihed" cannot run a Google Autocomplete query or a Bluesky search without first creating a query design, configuring arenas, and launching a collection.

The arena routers already expose standalone `/collect` endpoints (e.g., `POST /arenas/google-autocomplete/collect`, `POST /arenas/bluesky/collect/terms`). These endpoints are API-only with no UI wrapper.

The UX report also notes (S-06) that the AI Chat Search arena's `_query_expander.py` module could serve as a discovery assistant by suggesting related search terms from a seed term.

#### Recommended Implementation

**Step 1: Exploration page.** Create a new template at `src/issue_observatory/api/templates/explore/index.html` (or integrate into the dashboard). The page should provide:

1. A single text input: "Enter a topic to explore"
2. An arena selector (radio buttons or tabs) limited to low-cost/free arenas: Google Autocomplete, Bluesky, Reddit, RSS Feeds, Gab
3. A "Run" button that calls the selected arena's `/collect` endpoint with the entered term
4. A results panel showing the returned content records in a simplified table
5. For Google Autocomplete specifically: display the suggestion list directly as a "related terms" card

**Step 2: Page route.** Add a page route in `src/issue_observatory/api/routes/pages.py`:

```python
@router.get("/explore")
async def explore_page(request: Request, ...):
    return templates.TemplateResponse("explore/index.html", {...})
```

**Step 3: Navigation integration.** Add "Explore" to the sidebar navigation in `src/issue_observatory/api/templates/_partials/nav.html`, positioned before "Query Designs" to encourage the explore-first workflow.

**Step 4: Bridge to query design.** After exploring, the researcher should be able to click "Create Query Design from These Results" to seed a new query design with the terms and arenas they explored. This is a link to `/query-designs/new` pre-populated with query parameters.

#### Why This Is High Priority

The UX test found that the application "assumes the researcher already knows what terms, actors, and arenas to configure." For any new research topic, the first step is exploration, not execution. This feature transforms the platform from a collection execution engine into a discovery assistant.

---

### YF-06: Cross-Run Analysis Aggregation

**UX Finding:** FP-17 (High severity)
**Responsible Components:** core, frontend
**Estimated Complexity:** Medium (3-5 days)
**Dependencies:** None

#### Problem

All analysis endpoints (`src/issue_observatory/api/routes/analysis.py`) are scoped to a single collection run (`/analysis/{run_id}/...`). A researcher who has run multiple collections for their ytringsfrihed study -- for example, one initial batch collection and two subsequent expansion collections after discovering new actors -- cannot analyze them together. Cross-run comparison requires exporting data from each run separately and combining externally.

#### Recommended Implementation

**Step 1: Verify existing filter support.** The `build_content_where()` function in `src/issue_observatory/analysis/_filters.py` (referenced from `descriptive.py` line 39) and the `_build_content_filters()` function in `descriptive.py` already accept a `query_design_id` parameter in addition to `run_id`. Verify that passing `query_design_id` without a `run_id` correctly filters content to all runs belonging to that design.

**Step 2: Analysis route extension.** Add a parallel set of routes scoped to `query_design_id`:

```
GET /analysis/design/{design_id}                  -- HTML analysis dashboard (all runs)
GET /analysis/design/{design_id}/summary          -- JSON aggregated summary
GET /analysis/design/{design_id}/volume           -- JSON combined volume over time
GET /analysis/design/{design_id}/actors           -- JSON top actors across all runs
GET /analysis/design/{design_id}/network/actors   -- JSON actor co-occurrence (full corpus)
```

These routes reuse the same underlying functions from `descriptive.py` and `network.py` by passing `query_design_id` instead of `run_id`.

**Step 3: UI navigation.** On the query design detail page (`src/issue_observatory/api/templates/query_designs/detail.html`), add an "Analyze All Runs" button that links to `/analysis/design/{design_id}`. On the per-run analysis page, add a "See All Runs" link that navigates to the design-level view.

**Step 4: Run comparison.** In the design-level analysis dashboard, include a run selector that allows the researcher to toggle individual runs on/off, enabling comparison of "before and after expansion" or "batch vs. live tracking."

---

### YF-07: Bulk Actor Import

**UX Finding:** FP-11 (Medium severity, elevated to High given workflow impact)
**Responsible Components:** frontend, core
**Estimated Complexity:** Small (1-2 days)
**Dependencies:** Benefits from YF-03 pattern (reuse bulk entry UI component)

#### Problem

Actors must be added one at a time through the query design editor's actor panel. A researcher with 8 seed actors (the ytringsfrihed scenario) or 15+ actors (the Greenland scenario) faces repetitive entry. The `POST /actors/quick-add-bulk` endpoint exists but requires platform usernames -- it serves the Discovered Sources flow, not the simple name+type initial actor creation flow.

#### Recommended Implementation

**Step 1: Backend endpoint.** Add `POST /query-designs/{id}/actors/bulk` in `src/issue_observatory/api/routes/query_designs.py`:

```python
class ActorBulkItem(BaseModel):
    name: str
    actor_type: str = "person"  # person, organization, media_outlet, unknown

@router.post("/{design_id}/actors/bulk")
async def add_actors_bulk(
    design_id: uuid.UUID,
    actors: list[ActorBulkItem],
    db: ..., current_user: ...,
):
    # For each: find-or-create Actor, add to default ActorList
```

**Step 2: Frontend.** In the actor panel of the query design editor (below the existing single-actor form), add a "Bulk Add" toggle showing a textarea accepting one actor per line in format `name | type`. Default type to "person" when not specified.

---

## 5. Medium: Quality-of-Life Enhancements

### YF-08: Arena Overview Page

**UX Finding:** FP-01 (Medium severity)
**Responsible Components:** frontend
**Estimated Complexity:** Small (1-2 days)
**Dependencies:** None

#### Problem

The dashboard provides no overview of available arenas. The `GET /api/arenas/` endpoint returns rich metadata (arena_name, platform_name, supported_tiers, description, has_credentials), but this information is only surfaced in the query design editor's arena grid. A first-time researcher cannot understand the platform's capabilities before committing to a query design.

#### Recommended Implementation

Create a new page at `/arenas` with a template `src/issue_observatory/api/templates/arenas/index.html` that presents:

1. All arenas organized by category (free / medium / premium, or by arena_name grouping)
2. Each arena card showing: name, description, supported tiers, credential status
3. A "What can I research?" narrative section explaining which arenas cover news, social media, fringe platforms, and archives
4. Links to arena research briefs where they exist (`/docs/arenas/{platform_name}.md`)

Add "Arenas" to the sidebar navigation between "Dashboard" and "Query Designs."

---

### YF-09: Tier Precedence Explanation

**UX Finding:** FP-14 (Medium severity)
**Responsible Components:** frontend
**Estimated Complexity:** Small (0.5-1 day)
**Dependencies:** None

#### Problem

The collection launcher has a global tier selector, but the query design may already have per-arena tier overrides in `arenas_config`. The tier precedence logic (per-arena config > query design default > launcher global) is documented in the code comments (`src/issue_observatory/api/routes/collections.py`, line 246) but not in the UI. A researcher who sets "free" globally but has "medium" for Google Search in their query design will not know which applies.

#### Recommended Implementation

In `src/issue_observatory/api/templates/collections/launcher.html`, add an info panel (tooltip or expandable section) near the tier selector:

```html
<div class="text-xs text-gray-500 mt-1">
    <strong>Tier precedence:</strong> Per-arena settings in your query design
    override this global default. Arenas without explicit tier settings
    will use this value.
</div>
```

Additionally, when a query design is selected in the launcher, display the per-arena config as a summary table showing which arenas have overrides.

---

### YF-10: Group Label Autocomplete Enhancement

**UX Finding:** FP-04 (Low severity in UX report, but Medium for repeated use)
**Responsible Components:** frontend
**Estimated Complexity:** Small (0.5 day)
**Dependencies:** None

#### Problem

The group label field is free-text, requiring the researcher to type group names identically for related terms. A datalist exists (`id="term-group-suggestions"` at line 201 of the editor template) with predefined suggestions ("Primary terms", "Discourse associations", etc.), but it does not dynamically include groups the researcher has already created for this query design.

#### Recommended Implementation

In the Alpine.js `termGroupManager()` component that manages the search terms panel, add logic to populate the datalist dynamically from the currently-displayed terms' group labels:

```javascript
// In termGroupManager() init or a MutationObserver callback:
const existingGroups = new Set();
document.querySelectorAll('#terms-list [data-group-label]').forEach(el => {
    const label = el.dataset.groupLabel;
    if (label) existingGroups.add(label);
});
const datalist = document.getElementById('term-group-suggestions');
existingGroups.forEach(label => {
    if (!datalist.querySelector(`option[value="${label}"]`)) {
        const opt = document.createElement('option');
        opt.value = label;
        datalist.appendChild(opt);
    }
});
```

This ensures that once a researcher types "Legal" as a group label, subsequent terms can select it from the dropdown rather than retyping it.

---

### YF-11: Snowball Sampling Platform Transparency

**UX Finding:** FP-16 (Medium severity)
**Responsible Components:** frontend
**Estimated Complexity:** Small (0.5-1 day)
**Dependencies:** None

#### Problem

Snowball sampling only works on Bluesky, Reddit, and YouTube (`_NETWORK_EXPANSION_PLATFORMS` in `src/issue_observatory/sampling/network_expander.py`). This limitation is not communicated in the UI. A researcher who expects to snowball-sample from a Telegram actor will not understand why it fails.

#### Recommended Implementation

In the snowball sampling panel (likely rendered in the Actor Directory or query design editor), when the researcher selects platforms for expansion:

1. Visually distinguish supported platforms (Bluesky, Reddit, YouTube) from unsupported ones
2. Show a message: "Network expansion is available for Bluesky, Reddit, and YouTube. For other platforms, use Discovered Sources to find connected actors through cross-platform links."
3. Disable (but still show) platform checkboxes for unsupported platforms with a tooltip explaining why

---

### YF-12: RSS Feed Preview

**UX Finding:** FP-08 (Medium severity)
**Responsible Components:** frontend
**Estimated Complexity:** Small (1-2 days)
**Dependencies:** None

#### Problem

The `GET /arenas/rss-feeds/feeds` endpoint lists all configured feeds, but the researcher has no way to search or preview the feed list from the UI. With 30+ feeds in `DANISH_RSS_FEEDS`, the researcher cannot quickly identify which outlets are included or check whether specific outlets relevant to their topic (e.g., Information for ytringsfrihed editorial coverage) are present.

#### Recommended Implementation

**Step 1: Feed list in arena config.** When the RSS Feeds arena card is expanded in the query design editor's arena grid (per YF-02), show the list of default feeds as a read-only summary. Each feed should display the outlet name (from the code comments in `danish_defaults.py`) and the feed URL.

**Step 2: Search/filter.** Add a client-side text filter above the feed list that matches against outlet name and URL.

**Step 3: Test feed.** Optionally, add a "Test Feed" button next to each feed that makes a single fetch attempt and reports the feed's status (responding, empty, errored) and most recent item date. This helps researchers identify which feeds are actively publishing.

---

### YF-13: Discovered Sources Cross-Design View

**UX Finding:** FP-15 (Medium severity)
**Responsible Components:** core
**Estimated Complexity:** Small-Medium (1-2 days)
**Dependencies:** Benefits from YF-06 (cross-run analysis) but can be implemented independently

#### Problem

The Discovered Sources page (`/content/discovered-links`) requires a `query_design_id` parameter, scoping link mining to a single query design's collected content. A researcher with multiple query designs for different sub-topics of ytringsfrihed cannot see a unified view of discovered sources.

#### Recommended Implementation

Add an optional `user_scope` mode to the discovered-links route in `src/issue_observatory/api/routes/content.py`:

1. When `query_design_id` is provided: current behavior (scoped to one design)
2. When no `query_design_id` is provided: mine links across all content owned by the current user

The link mining logic in `src/issue_observatory/analysis/link_miner.py` likely filters by `collection_run_id`; adding a user-scope filter (joining through `collection_runs.initiated_by`) extends coverage to all of the user's content.

---

## 6. Low: Polish Items

### YF-14: Google Search Free-Tier Guidance

**UX Finding:** FP-07 (Low severity)
**Responsible Components:** data
**Estimated Complexity:** Small (0.5 day)
**Dependencies:** None

#### Problem

Google Search's free tier returns empty results with no guidance. The router should suggest alternatives.

#### Recommended Implementation

In the Google Search arena's router (`src/issue_observatory/arenas/google_search/router.py`), when the free tier returns empty results, include a message in the response:

```python
if tier == "free":
    return CollectionResponse(
        records=[],
        total_count=0,
        message=(
            "Google Search has no free API. Try Google Autocomplete (free) "
            "for discovery, or upgrade to medium tier (Serper.dev) for "
            "search results."
        ),
    )
```

---

### YF-15: Custom Subreddit UI

**UX Finding:** FP-09 (Medium severity, but covered by YF-02)
**Responsible Components:** frontend
**Estimated Complexity:** Small (included in YF-02)
**Dependencies:** YF-02 (source-list arena configuration)

This is a specific instance of YF-02. When the generic per-arena custom configuration UI is implemented, Reddit's custom subreddit input is included automatically. No additional work beyond YF-02 is needed.

---

### YF-16: Actor Platform Presence Inline Add

**UX Finding:** FP-12 (Medium severity)
**Responsible Components:** frontend
**Estimated Complexity:** Medium (2-3 days)
**Dependencies:** None

#### Problem

When adding an actor (e.g., "Jyllands-Posten") to a query design, the researcher cannot immediately specify platform presences (Bluesky handle, RSS feed URL, etc.) without navigating away to `/actors/{id}`. This interrupts the query design creation flow.

#### Recommended Implementation

In the query design editor's actor panel, after successfully adding an actor, show an expandable inline panel with platform presence fields. The panel should offer a dropdown for platform (Bluesky, Reddit, X/Twitter, YouTube, etc.) and a text input for the platform username/identifier. On submit, call `POST /actors/{id}/presences`.

Alternatively, a simpler approach: after adding an actor, show a "Configure Presences" link that opens the actor detail page in a new tab (or a modal), allowing the researcher to add presences without losing their query design context.

---

## 7. Implementation Roadmap

### Phase 1: Foundations (Week 1-2)

| Order | ID | Recommendation | Effort | Rationale |
|-------|-----|----------------|--------|-----------|
| 1 | YF-01 | Per-arena search term scoping | 3-5 days | Foundational architectural change; affects data model and all arena dispatch logic |
| 2 | YF-02 | Source-list arena configuration UI | 2-4 days | Removes the only functional blocker (BL-01); unlocks Telegram, custom Reddit, custom RSS |

**Phase 1 deliverable:** Researchers can create query designs with arena-scoped search terms and configure source-list arenas through the UI.

### Phase 2: Bulk Entry and Discovery (Week 2-3)

| Order | ID | Recommendation | Effort | Rationale |
|-------|-----|----------------|--------|-----------|
| 3 | YF-03 | Bulk search term import | 1-2 days | Eliminates high-frequency friction; benefits from YF-01's arena scoping |
| 4 | YF-07 | Bulk actor import | 1-2 days | Same pattern as YF-03; can reuse UI component |
| 5 | YF-05 | Ad-hoc exploration mode | 3-5 days | Addresses the "no discovery" gap; standalone feature with no model dependencies |

**Phase 2 deliverable:** Researchers can bulk-import terms and actors, and can explore topics before committing to formal query designs.

### Phase 3: Analysis and Estimation (Week 3-4)

| Order | ID | Recommendation | Effort | Rationale |
|-------|-----|----------------|--------|-----------|
| 6 | YF-04 | Pre-flight credit estimates | 2-4 days | Enables informed cost decisions; requires arena-specific estimation logic |
| 7 | YF-06 | Cross-run analysis aggregation | 3-5 days | Essential for iterative research; unlocks the full research workflow |

**Phase 3 deliverable:** Researchers can estimate costs before launching and analyze their full corpus across multiple collection runs.

### Phase 4: Polish (Week 4-5)

| Order | ID | Recommendation | Effort | Rationale |
|-------|-----|----------------|--------|-----------|
| 8 | YF-08 | Arena overview page | 1-2 days | Orientation aid |
| 9 | YF-09 | Tier precedence explanation | 0.5-1 day | UI clarity |
| 10 | YF-10 | Group label autocomplete | 0.5 day | Minor friction reduction |
| 11 | YF-11 | Snowball platform transparency | 0.5-1 day | Expectation management |
| 12 | YF-12 | RSS feed preview | 1-2 days | Research planning aid |
| 13 | YF-13 | Discovered sources cross-design | 1-2 days | Discovery workflow enhancement |
| 14-16 | YF-14 to YF-16 | Low-priority items | 2-3 days | Polish |

**Phase 4 deliverable:** Comprehensive quality-of-life improvements that smooth the remaining friction points.

### Dependency Graph

```
YF-01 (per-arena terms) ─┐
                          ├─> YF-03 (bulk terms) benefits from arena scoping in bulk UI
YF-02 (arena config UI) ─┤
                          └─> YF-15 (custom subreddits) is subsumed by YF-02

YF-03 (bulk terms) ───────> YF-07 (bulk actors) reuses same UI pattern

YF-04 (credit estimates) ── standalone
YF-05 (exploration mode) ── standalone
YF-06 (cross-run analysis) ─> YF-13 (cross-design sources) benefits from same scope expansion

YF-08 through YF-16 ─────── all standalone, no critical dependencies
```

---

## 8. Cross-Cutting Concerns

### 8.1 The "Flexible Platform, Not Hard-Coded" Principle

Every recommendation in this report is designed to make the platform more flexible for ANY research topic, not just ytringsfrihed. Specifically:

- **YF-01** (per-arena terms) enables any researcher to use language-specific or arena-appropriate terms without contaminating other arenas. This serves Greenland (Danish+English+Kalaallisut), CO2 afgift (Danish policy + English climate), AI og uddannelse (Danish education + English tech), and every future topic.

- **YF-02** (arena config UI) replaces the need to hardcode feeds, channels, and subreddits per topic. The researcher adds their own sources through a generic mechanism that works for any arena.

- **YF-05** (exploration mode) is topic-agnostic: the researcher enters any term and sees what the platform can find, regardless of the research domain.

None of these recommendations add ytringsfrihed-specific content to the codebase. They build mechanisms that any researcher can use for any topic.

### 8.2 Database Migration Considerations

Only YF-01 requires a database migration (adding `target_arenas JSONB NULL` to `search_terms`). This is a non-breaking change: the column is nullable and defaults to NULL, meaning existing search terms automatically apply to all arenas. No data migration is needed.

All other recommendations either modify frontend templates, add new API routes, or implement logic in existing service classes without schema changes.

### 8.3 Impact on Existing Tests

- **YF-01**: Tests for arena task dispatch must be updated to filter terms by `target_arenas`. Existing tests that create SearchTerms without `target_arenas` will continue to pass (NULL means all arenas).
- **YF-03, YF-07**: New bulk endpoints need new test cases, but existing single-entry endpoints are unchanged.
- **YF-04**: The estimate endpoint's stub response changes to real values; update tests accordingly.
- **YF-06**: New analysis routes need new tests; existing per-run routes are unchanged.

### 8.4 GDPR Implications

None of the recommendations introduce new personal data processing. The per-arena term scoping (YF-01) may reduce unnecessary data collection by preventing irrelevant terms from being dispatched to arenas where they would collect off-topic content -- this is directionally positive for data minimization under GDPR Article 5(1)(c).

### 8.5 Performance Considerations

- **YF-01**: The term filtering logic (`target_arenas is None or platform_name in target_arenas`) is applied at dispatch time, not query time. It adds negligible overhead.
- **YF-06**: Cross-run analysis queries may scan more data than single-run queries. The existing monthly partitioning on `content_records` mitigates this; ensure queries include date range predicates to leverage partition pruning.
- **YF-13**: Cross-design link mining (user-scoped) will scan all of a user's content. For heavy users, this may require pagination or a collection run filter to remain performant.

---

## 9. Relationship to Previous Reports

### 9.1 Convergence Across Four Evaluations

The ytringsfrihed evaluation is the fourth scenario evaluated. The following table shows which recommendations have now appeared across multiple evaluations, establishing them as systemic priorities:

| Recommendation | CO2 Afgift | AI og Uddannelse | Greenland | Ytringsfrihed |
|---------------|-----------|-----------------|-----------|---------------|
| Per-arena term customization | P2.3 (boolean logic) | Gap 1 sec 4.3 | GR-05 (multi-language) | **YF-01** (full arena scoping) |
| Source-list arena config UI | -- | -- | GR-01, GR-02, GR-03, GR-04 | **YF-02** (unified mechanism) |
| Bulk term entry | -- | -- | -- | **YF-03** (first identification) |
| Pre-flight credit estimates | -- | -- | -- | **YF-04** (first identification as stub) |
| Exploration/discovery mode | -- | -- | -- | **YF-05** (first identification) |
| Cross-run analysis | -- | -- | -- | **YF-06** (first identification) |
| Bulk actor entry | -- | -- | -- | **YF-07** (first identification) |
| Arena overview/guidance | FP-13 (descriptions) | IM-13 (descriptions) | GR-06 (credentials) | **YF-08** (dedicated page) |

### 9.2 Recommendations That Build on Previous Work

| YF ID | Builds On | How It Extends |
|-------|-----------|---------------|
| YF-01 | GR-05 (multi-language per design) | GR-05 allowed multiple languages per query design. YF-01 goes further: per-term arena scoping allows different terms for different arenas within a single language. These are complementary, not competing, changes. |
| YF-02 | GR-01, GR-02, GR-03, GR-04 | The Greenland report recommended per-arena custom config (feeds, channels, subreddits, articles) as four separate items. YF-02 consolidates them into a single generic mechanism driven by arena metadata, reducing implementation effort and ensuring consistency. |
| YF-06 | IP2-050 (cross-arena flow analysis) | IP2-050 identified cross-arena temporal propagation detection. YF-06 addresses a prerequisite: before you can track how a narrative flows across arenas, you must be able to analyze content from multiple collection runs together. |

### 9.3 Previously Recommended Items Validated by This Evaluation

The following items from prior reports are independently validated by the ytringsfrihed evaluation:

| Prior ID | Description | Ytringsfrihed Validation |
|----------|-------------|------------------------|
| GR-17 | Content Browser "quick add" to collection | FP-06, BL-01: the "move actor from one arena to another" workflow requires 4+ manual steps |
| GR-22 | Cross-platform link mining | S-10: the Discovered Sources feature is the "single most important feature for cross-arena discovery" |
| IP2-038 | Emergent term extraction | The ytringsfrihed scenario needs exactly this: discover terms like "racismeparagraffen" that appear in the data but were not in the initial term list |
| GR-09 | Volume spike alerting | For a volatile topic like ytringsfrihed where posts may be deleted after backlash, real-time alerting helps capture ephemeral content |

### 9.4 Net New Findings from This Evaluation

The following findings are genuinely new, not identified in any prior report:

| Finding | Why New |
|---------|---------|
| FP-10: Shared term list causes cross-arena contamination | Prior reports focused on language mixing (GR-05); the ytringsfrihed scenario exposed the broader problem of arena-inappropriate terms even within a single language |
| FP-03/FP-11: Bulk import for terms and actors | Prior evaluations used smaller term/actor sets; the 18-term ytringsfrihed scenario made the single-entry friction obvious |
| FP-13: Credit estimate is a stub | Prior evaluations did not test the pre-flight estimation flow; the ytringsfrihed test walked through the full collection launcher |
| FP-17: Analysis scoped to single run | Prior evaluations tested individual analysis features; the ytringsfrihed test followed the iterative multi-collection workflow where this limitation becomes apparent |
| S-15: Free tier covers 6+ arenas | Prior reports acknowledged free tier but did not systematically evaluate the research value achievable at zero cost |

---

## Appendix: UX Finding to Recommendation Mapping

| UX Finding | Severity | Recommendation | Priority |
|-----------|----------|----------------|----------|
| FP-01 | Medium | YF-08 (Arena overview page) | Medium |
| FP-02 | High | YF-05 (Exploration mode) | High |
| FP-03 | High | YF-03 (Bulk search term import) | High |
| FP-04 | Low | YF-10 (Group label autocomplete) | Medium |
| FP-05 | Medium | YF-08 (Arena overview page) | Medium |
| FP-06 | High | YF-02 (Source-list arena config UI) | Critical |
| FP-07 | Low | YF-14 (Google Search free-tier guidance) | Low |
| FP-08 | Medium | YF-12 (RSS feed preview) | Medium |
| FP-09 | Medium | YF-15 (Custom subreddit UI, subsumed by YF-02) | Low |
| FP-10 | Critical | YF-01 (Per-arena search term scoping) | Critical |
| FP-11 | Medium | YF-07 (Bulk actor import) | High |
| FP-12 | Medium | YF-16 (Actor platform presence inline add) | Low |
| FP-13 | High | YF-04 (Pre-flight credit estimates) | High |
| FP-14 | Medium | YF-09 (Tier precedence explanation) | Medium |
| FP-15 | Medium | YF-13 (Discovered sources cross-design) | Medium |
| FP-16 | Medium | YF-11 (Snowball platform transparency) | Medium |
| FP-17 | High | YF-06 (Cross-run analysis) | High |
| FP-18 | Medium | Not addressed (infrastructure concern outside scope) | -- |
| BL-01 | Blocker | YF-02 (Source-list arena config UI) | Critical |
