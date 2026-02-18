# Implementation Plan 2.0 -- Architecture and Technical Design

**Date:** 2026-02-18
**Status:** Final
**Basis:** Cross-case synthesis of CO2 afgift (discourse tracking) and AI og uddannelse (issue mapping) evaluations

---

## Summary of Key Architectural Facts

Before detailing the plan, here are the critical architectural observations from the codebase exploration:

1. **Arena Registry**: The `registry.py` at `src/issue_observatory/arenas/registry.py` already provides `list_arenas()` which returns `arena_name`, `platform_name`, and `supported_tiers` from all registered collectors. This function is already suitable as the data source for a dynamic arena grid -- the frontend just does not call it.

2. **Hardcoded Arena List**: The editor template at `src/issue_observatory/api/templates/query_designs/editor.html` (lines 474-486) contains a static JavaScript array of 11 arenas while the backend has ~19 arena collector packages registered via `@register` decorators.

3. **Filter Duplication**: `_build_content_filters()` in `descriptive.py` (line 74) and `_build_run_filter()` in `network.py` (line 62) implement nearly identical logic. Both lack a duplicate-exclusion filter (`raw_metadata->>'duplicate_of' IS NULL`).

4. **Actor Disconnect**: The `ActorListMember` model (in `actors.py`) references `Actor` via `actor_id` FK, and the query design editor creates lightweight actor list entries. But the UI flow does not create `Actor` records in the actor directory when adding actors to a query design.

5. **Danish Tokenizer Exists**: The `_tokenize()` function in `similarity_finder.py` (line 84) already handles Danish tokenization with the regex `[a-z0-9æøå]{2,}`, including æ, ø, and å characters. The `_tfidf_cosine()` function (line 115) uses scikit-learn for TF-IDF computation. These can be reused for emergent term extraction.

6. **Export Columns**: The `_FLAT_COLUMNS` list in `export.py` (line 42) contains 15 columns and is missing `pseudonymized_author_id`, `content_hash`, `collection_run_id`, and `query_design_id`.

---

## Phase A: Foundation Fixes

These items address blockers that appeared in both UX test reports and must be completed before any research use.

### Item 1: Dynamic Arena Grid

**Problem Statement**: The arena configuration grid in the query design editor uses a hardcoded JavaScript array of 11 arenas (editor.html lines 474-486), while the backend registry contains ~19 arena collectors. Findings FP-10, FP-11, IM-11, IM-B03 across both reports. Researchers cannot access Event Registry, X/Twitter, AI Chat Search, Facebook, Instagram, Threads, Common Crawl/Wayback, or Majestic.

**Current State**:
- Backend: `list_arenas()` in `src/issue_observatory/arenas/registry.py` (line 109) already returns `arena_name`, `platform_name`, `supported_tiers`, and `collector_class` for every registered arena.
- Frontend: The `arenaConfigGrid()` function in editor.html (line 472) defines `const ARENAS = [...]` with 11 entries. The `init()` method (line 497) fetches saved per-design config from `/api/query-designs/{id}/arena-config` but does not fetch the available arena list from the server.

**Proposed Solution**:

1. Create a new API endpoint `GET /api/arenas/` that calls `autodiscover()` then `list_arenas()` and returns the full arena list enriched with:
   - `description`: A one-line human-readable description of each arena
   - `credential_status`: Whether credentials are configured for this arena (query the credentials table)
   - `supported_tiers`: Already available from the registry

2. Modify the `arenaConfigGrid()` Alpine component to fetch from `/api/arenas/` in its `init()` method instead of using the hardcoded `ARENAS` constant. Merge the fetched arena list with any saved per-design config.

3. Add arena descriptions as a class-level attribute on each `ArenaCollector` subclass (or as a dict in `registry.py`).

**Files Affected**:
- `src/issue_observatory/arenas/registry.py` -- Add `description` field to `list_arenas()` output; add an `arena_descriptions` dict
- `src/issue_observatory/api/routes/query_designs.py` -- Add `GET /api/arenas/` endpoint (or create a new `arenas.py` route file)
- `src/issue_observatory/api/templates/query_designs/editor.html` -- Replace hardcoded `ARENAS` with fetch from API; add description tooltip per arena

**New Files Needed**: Possibly `src/issue_observatory/api/routes/arenas.py` for a dedicated arenas API router.

**Database Changes**: None -- credential status can be queried from the existing `credentials` table.

**API Changes**: New endpoint `GET /api/arenas/` returning:
```json
[
  {
    "arena_name": "bluesky",
    "platform_name": "bluesky",
    "supported_tiers": ["free"],
    "description": "Decentralized social network with Danish academic and political presence",
    "has_credentials": true
  }
]
```

**Frontend Changes**: Refactor `arenaConfigGrid()` to:
- Fetch arena list from `/api/arenas/` on init
- Render description as a tooltip (title attribute or small info icon with popover)
- Show credential status indicator (green dot = configured, gray dot = not configured)

**Testing Approach**:
- Unit test for `GET /api/arenas/` endpoint verifying all registered arenas are returned
- Frontend test that the grid renders all fetched arenas
- Integration test that newly registered arenas appear without template changes

**Dependencies**: None
**Estimated Complexity**: M (2-3 days)

---

### Item 2: Arena Tier Validation

**Problem Statement**: All arenas show free/medium/premium radio buttons regardless of actual support. Bluesky, RSS Feeds, GDELT, Reddit, Ritzau, Gab, and TikTok only support the free tier. Selecting unsupported tiers provides no warning. Findings FP-09, IM-10.

**Current State**:
- Backend: Each `ArenaCollector` subclass defines `supported_tiers` as a list (e.g., `[Tier.FREE]` for Bluesky). The `_validate_tier()` method on `ArenaCollector` (base.py line 272) raises `ValueError` for unsupported tiers.
- Frontend: The tier radio template (editor.html lines 392-409) renders all three tiers unconditionally with `x-for="t in ['free', 'medium', 'premium']"`.

**Proposed Solution**:

Once Item 1 delivers `supported_tiers` per arena to the frontend, modify the tier radio rendering to:
1. Disable (grey out) radio buttons for unsupported tiers
2. Add a tooltip on disabled radios: "This arena only supports the Free tier"
3. If a saved config has an unsupported tier, auto-correct to the highest supported tier and show a warning

**Files Affected**:
- `src/issue_observatory/api/templates/query_designs/editor.html` -- Modify tier radio template to check `arena.supported_tiers.includes(t)` before enabling

**Dependencies**: Item 1 (dynamic arena grid must deliver `supported_tiers`)
**Estimated Complexity**: S (0.5-1 day)

---

### Item 3: Actor Workflow Unification

**Problem Statement**: Actors added in the query design editor are stored as lightweight `ActorListMember` entries with only a name and type. They are NOT created in the Actor Directory (`actors` table). The snowball sampling panel requires actors to exist in the directory with platform presences. Findings FP-07, IM-08, IM-24, IM-B01.

**Current State**:
- Query design actors: The editor POSTs to `/query-designs/{design_id}/actors` which creates `ActorListMember` rows. These reference `Actor` via `actor_id` FK, but the creation flow does not check for or create `Actor` records.
- Actor directory: The `Actor` model (actors.py line 30) has `canonical_name`, `actor_type`, `description`, `created_by`, `is_shared`, `metadata_`. The `ActorPlatformPresence` model (line 147) stores platform-specific identifiers.
- The editor template (line 267-271) shows a "Profile" link only if `actor.actor_id` is defined, confirming the system CAN link them.

**Proposed Solution**:

Modify the actor-add flow in the query design editor to:

1. When the researcher adds an actor to a query design, the backend should:
   a. Search the `actors` table for an existing actor with a matching `canonical_name` (case-insensitive, owned by the same user or `is_shared=True`)
   b. If found, link the `ActorListMember` to the existing `Actor` via `actor_id`
   c. If not found, create a new `Actor` record with the provided name and type, then link it

2. After linking, the query design actor row should show the "Profile" link to the Actor Directory entry.

3. The Actor Directory page should show which query designs reference each actor.

**Files Affected**:
- `src/issue_observatory/api/routes/query_designs.py` -- Modify the POST handler for `/query-designs/{id}/actors` to create-or-link Actor records
- `src/issue_observatory/api/templates/query_designs/editor.html` -- Ensure "Profile" link renders after actor creation
- `src/issue_observatory/api/routes/actors.py` -- Optionally add a query-design-membership column to the actor list/detail views

**Database Changes**: None -- the `ActorListMember.actor_id` FK already exists. The change is behavioral: always populate it.

**API Changes**: The POST `/query-designs/{id}/actors` endpoint's response should include the `actor_id` of the created/linked `Actor` record.

**Testing Approach**:
- Test: Adding an actor to a query design creates an Actor record
- Test: Adding a duplicate-named actor links to the existing record
- Test: The snowball sampling panel shows actors added via query designs

**Dependencies**: None
**Estimated Complexity**: M (2-3 days)

---

### Item 4: UI Polish Fixes

**Problem Statement**: Multiple stale labels, missing confirmations, and developer jargon throughout the UI. Findings FP-01, FP-02, FP-05, FP-14, FP-16, FP-20, IM-01, IM-07, IM-17.

**Proposed Solution**: A single sweep of template changes:

| Sub-item | File | Line(s) | Change |
|----------|------|---------|--------|
| 4a | `dashboard/index.html` | ~161 | Remove "Phase 0 -- Google Search arena active" or replace with dynamic arena count |
| 4b | `admin/health.html` | 83-95 | Replace hardcoded "Version: 0.1.0 (Phase 0)" and "Active Arenas: Google Search" with dynamic values |
| 4c | `query_designs/editor.html` | 160 | Change "termer" to "terms" (or make language consistent) |
| 4d | `query_designs/editor.html` | ~437-452 | Add `hx-on::after-settle` handler to show a success toast after arena config save |
| 4e | `collections/launcher.html` | ~112 | Replace "Celery Beat" with "Runs automatically every day at midnight Copenhagen time" |
| 4f | `collections/detail.html` | ~40-42 | Show query design name prominently in header alongside the run UUID |
| 4g | `query_designs/editor.html` | 169-175 | Add help text below term type dropdown explaining each type |

**Files Affected**:
- `src/issue_observatory/api/templates/dashboard/index.html`
- `src/issue_observatory/api/templates/admin/health.html`
- `src/issue_observatory/api/templates/query_designs/editor.html`
- `src/issue_observatory/api/templates/collections/launcher.html`
- `src/issue_observatory/api/templates/collections/detail.html`

**Dependencies**: None
**Estimated Complexity**: S (1-2 days)

---

## Phase B: Discourse Tracking Maturity

These items bring the tracking workflow to publication quality, primarily addressing findings from the CO2 afgift report.

### Item 5: Analysis Chart Improvements

**Problem Statement**: Charts lack axis labels and the filter bar uses free-text inputs instead of dropdowns. Findings FP-30, FP-31, IM-29, IM-30.

**Proposed Solution**:

1. Add axis labels to all chart configurations:
   - Volume chart: y-axis = "Number of records", x-axis = "Date"
   - Top actors chart: x-axis = "Record count"
   - Top terms chart: x-axis = "Record count"
   - Engagement chart: appropriate axis labels per metric

2. Replace free-text Platform and Arena filter inputs with `<select>` dropdowns populated from the run's actual data via HTMX GET to a new endpoint `GET /analysis/{run_id}/filter-options`.

**Files Affected**:
- `src/issue_observatory/api/templates/analysis/index.html` -- Chart config and filter bar
- `src/issue_observatory/api/routes/analysis.py` -- New endpoint for filter options

**Dependencies**: None
**Estimated Complexity**: S (1-2 days)

---

### Item 6: Export Improvements

**Problem Statement**: Column headers use snake_case, JSON label is misleading, and key columns are missing. Findings FP-33, FP-34, IM-37, IM-38.

**Proposed Solution**:

1. Add a `_COLUMN_HEADERS` mapping dict in export.py:
```python
_COLUMN_HEADERS = {
    "platform": "Platform",
    "arena": "Arena",
    "content_type": "Content Type",
    "title": "Title",
    "text_content": "Text Content",
    "url": "URL",
    "author_display_name": "Author",
    "published_at": "Published At",
    "views_count": "Views",
    "likes_count": "Likes",
    "shares_count": "Shares",
    "comments_count": "Comments",
    "language": "Language",
    "collection_tier": "Collection Tier",
    "search_terms_matched": "Matched Search Terms",
    "pseudonymized_author_id": "Author ID (Pseudonymized)",
    "content_hash": "Content Hash",
    "collection_run_id": "Collection Run ID",
    "query_design_id": "Query Design ID",
}
```

2. Extend `_FLAT_COLUMNS` to include `pseudonymized_author_id`, `content_hash`, `collection_run_id`, and `query_design_id`.

3. Use `_COLUMN_HEADERS` when writing CSV/XLSX header rows.

4. Relabel "JSON" to "NDJSON (one record per line)" in the analysis template.

**Files Affected**:
- `src/issue_observatory/analysis/export.py` -- Add header mapping, extend column list
- `src/issue_observatory/api/templates/analysis/index.html` -- Relabel JSON format option

**Dependencies**: None
**Estimated Complexity**: S (0.5-1 day)

---

### Item 7: Duplicate Exclusion in Analysis

**Problem Statement**: The descriptive and network analysis functions do not filter out records marked as duplicates via `raw_metadata->>'duplicate_of'`. This inflates volume counts and distorts network edge weights. CO2 afgift report P1.2.

**Proposed Solution**:

1. Add a duplicate exclusion clause to both filter builders:
```python
clauses.append("(raw_metadata->>'duplicate_of') IS NULL")
```

2. Since both filter builders are nearly identical (TD-2 from the codebase report), refactor them into a shared function in a new `analysis/_filters.py` module. Both `descriptive.py` and `network.py` would import from it.

**Files Affected**:
- `src/issue_observatory/analysis/descriptive.py` -- Add duplicate exclusion to `_build_content_filters()`
- `src/issue_observatory/analysis/network.py` -- Add duplicate exclusion to `_build_run_filter()`

**New Files**: Optionally `src/issue_observatory/analysis/_filters.py` for shared filter logic.

**Testing Approach**: Unit test verifying that records with `raw_metadata->>'duplicate_of'` set are excluded from volume counts, top actors, top terms, and network edges.
**Dependencies**: None
**Estimated Complexity**: S (0.5-1 day)

---

### Item 8: Collection Detail Improvements

**Problem Statement**: The collection detail page does not show the query design name, search terms used, or arena configuration. Findings FP-15, FP-19, FP-20, IM-15.

**Proposed Solution**:

1. Add a "Research Instrument" summary panel to the collection detail page showing:
   - Query design name (linked to the detail page)
   - Search terms as badges
   - Enabled arenas with their tier selections

2. Add a read-only arena configuration section to the query design detail page (below the search terms and actors sections).

**Files Affected**:
- `src/issue_observatory/api/templates/collections/detail.html`
- `src/issue_observatory/api/templates/query_designs/detail.html`
- `src/issue_observatory/api/routes/collections.py` -- Ensure the route passes query design data to the template

**Dependencies**: Item 1 (for arena descriptions in the read-only view)
**Estimated Complexity**: S (1-2 days)

---

### Item 9: Content Browser Improvements

**Problem Statement**: Arena column hidden below xl breakpoint, engagement score unexplained, "Search Term" filter is free-text. Findings FP-21, FP-22, IM-18, IM-20.

**Proposed Solution**:

1. Lower the arena column visibility breakpoint from xl (1280px) to lg (1024px) or make it always visible.
2. Add a tooltip to the engagement column header explaining cross-platform non-comparability.
3. Replace the "Search Term" text input filter with a `<select>` dropdown populated from the current query design's search terms.

**Files Affected**:
- `src/issue_observatory/api/templates/content/browser.html`

**Dependencies**: None
**Estimated Complexity**: S (1 day)

---

## Phase C: Issue Mapping Capabilities

These are the most impactful new capabilities identified by the AI og uddannelse test case. They enable Noortje Marres-style issue mapping.

### Item 10: Emergent Term Extraction

**Problem Statement**: The system can only track co-occurrence of pre-defined search terms. It cannot discover emergent terms from collected text content. This is the single most important capability for Marres-style issue mapping, identified as the defining gap in the AI uddannelse codebase report (Section 5, Gap 1). CO2 afgift report P3.2 / AI uddannelse report IM-2.1.

**Current State**:
- `get_top_terms()` in descriptive.py (line 297) only unnests `search_terms_matched` -- it does not analyze text content.
- The `_tokenize()` function in `similarity_finder.py` (line 84) already handles Danish tokenization.
- The `_tfidf_cosine()` function in `similarity_finder.py` (line 115) uses scikit-learn's `TfidfVectorizer`.

**Proposed Solution**:

Create a new `get_emergent_terms()` function:

```python
async def get_emergent_terms(
    db: AsyncSession,
    query_design_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    method: str = "tfidf",  # "tfidf" or "keybert"
    top_n: int = 50,
    exclude_search_terms: bool = True,
) -> list[dict]:
    """Extract frequently occurring terms not in the query design's search terms."""
```

Phase 1: TF-IDF extraction using scikit-learn (reusing patterns from similarity_finder.py).
Phase 2 (future): KeyBERT extraction using a Danish BERT model.

**Files Affected**:
- `src/issue_observatory/analysis/descriptive.py` -- Add `get_emergent_terms()` function
- `src/issue_observatory/api/routes/analysis.py` -- Add `GET /analysis/{run_id}/emergent-terms` endpoint
- `src/issue_observatory/api/templates/analysis/index.html` -- Add "Emergent Terms" panel to the analysis dashboard

**API Changes**: New endpoint `GET /analysis/{run_id}/emergent-terms?method=tfidf&top_n=50` returning:
```json
[
  {"term": "etik", "score": 0.42, "document_frequency": 87},
  {"term": "ansvar", "score": 0.38, "document_frequency": 65}
]
```

**Frontend Changes**: New panel in the analysis dashboard showing a bar chart or table of emergent terms. An "Add to query design" button per term would support the iterative issue mapping workflow.

**Dependencies**: None
**Estimated Complexity**: L (3-5 days)

---

### Item 11: Actor Role Classification

**Problem Statement**: The system only captures the speaking actor (content author). In news media, the author (journalist) is distinct from mentioned actors and quoted sources. This three-way distinction is fundamental to issue mapping. AI uddannelse codebase report Section 2.1.

**Proposed Solution** (incremental):

**Step 1 (enrichment storage)**: Define a standardized JSONB structure for actor roles in `raw_metadata.enrichments.actor_roles`:
```json
{
  "enrichments": {
    "actor_roles": [
      {"name": "Mette Frederiksen", "role": "mentioned", "confidence": 0.95},
      {"name": "Klimaraadet", "role": "quoted_source", "confidence": 0.85}
    ]
  }
}
```

**Step 2 (extraction)**: Create a named entity extraction enrichment using spaCy's `da_core_news_lg` or DaCy on `text_content`, classifying entities based on surrounding text patterns (e.g., "ifølge" = quoted source, "sagde" = speaker).

**Step 3 (analysis)**: Extend network analysis to use extracted actor roles, enabling "who is mentioned" networks distinct from "who speaks" networks.

**Files Affected**:
- New file: `src/issue_observatory/analysis/enrichments.py` -- Enrichment pipeline base
- `src/issue_observatory/analysis/network.py` -- Add role-aware network functions

**Database Changes**: None -- uses existing `raw_metadata` JSONB column.
**Dependencies**: Item 17 (enrichment pipeline) ideally designed first, but Step 1 can proceed independently.
**Estimated Complexity**: XL (5-7 days for full implementation; Step 1 alone is S)

---

### Item 12: Temporal Network Snapshots

**Problem Statement**: All four network analysis functions produce static snapshots. Issue mapping requires temporal analysis showing how the network evolves. AI uddannelse codebase report Section 5, Gap 5. CO2 afgift report P3.3.

**Proposed Solution**:

1. Add a `get_temporal_network_snapshots()` function to network.py:
```python
async def get_temporal_network_snapshots(
    db: AsyncSession,
    query_design_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    interval: str = "week",  # "day", "week", "month"
    network_type: str = "actor",  # "actor", "term", "bipartite"
) -> list[dict]:
    """Generate a sequence of network snapshots, one per time interval."""
```

2. Add a dynamic GEXF export option using GEXF 1.3 `mode="dynamic"` with `<spells>` elements for Gephi Timeline.

**Files Affected**:
- `src/issue_observatory/analysis/network.py` -- Add `get_temporal_network_snapshots()`
- `src/issue_observatory/analysis/export.py` -- Add dynamic GEXF export
- `src/issue_observatory/api/routes/analysis.py` -- Add temporal network endpoint
- `src/issue_observatory/api/templates/analysis/index.html` -- Add temporal controls to network tabs

**Dependencies**: None (builds on existing network functions)
**Estimated Complexity**: L (3-5 days)

---

### Item 13: Enhanced Bipartite Network

**Problem Statement**: The bipartite network uses only pre-defined search terms as "term" nodes, not emergent discourse topics. AI uddannelse codebase report Section 5, Gap 3.

**Proposed Solution**:

After Item 10 (emergent term extraction) is complete, extend the bipartite network to include extracted topics:

1. Add an `enhanced_bipartite_network()` function that combines search_terms_matched and emergent terms as "term" nodes, distinguishing between "search_term" and "emergent_term" node types for Gephi partitioning.

2. Add a `platform` attribute to actor nodes in the bipartite GEXF (currently missing per IM-35).

**Files Affected**:
- `src/issue_observatory/analysis/network.py` -- Add `build_enhanced_bipartite_network()`
- `src/issue_observatory/analysis/export.py` -- Add platform attribute to bipartite actor nodes; add enhanced bipartite GEXF builder

**Dependencies**: Item 10 (emergent term extraction)
**Estimated Complexity**: M (2-3 days)

---

## Phase D: Advanced Features

### Item 14: Boolean Query Support

**Problem Statement**: The `SearchTerm` model stores flat strings with no boolean combinations. CO2 afgift report Section 4.3, AI uddannelse report Section 4.3.

**Proposed Solution**:

Add a `TermGroup` concept:
1. Add a `group_id` column (nullable UUID) to `SearchTerm`. Terms with the same `group_id` are ANDed together; different groups are ORed.
2. Add a `group_label` column (nullable String) for display purposes ("Primary terms", "Sector terms", etc.)
3. Arena collectors parse term groups into platform-native query syntax.

**Files Affected**:
- `src/issue_observatory/core/models/query_design.py` -- Add `group_id` and `group_label` to SearchTerm
- All arena collectors under `src/issue_observatory/arenas/*/collector.py` -- Update `collect_by_terms()` to handle grouped terms

**Database Changes**: Alembic migration adding `group_id UUID NULL` and `group_label VARCHAR(200) NULL` to `search_terms` table.
**Dependencies**: None
**Estimated Complexity**: L (3-5 days)

---

### Item 15: Near-Duplicate Detection

**Problem Statement**: The deduplication service only catches exact URL and hash matches. Lightly edited wire stories are not detected. CO2 afgift report Section 5.2.

**Proposed Solution**: Add SimHash near-duplicate detection:

1. Compute a 64-bit SimHash for each record's `text_content` during normalization
2. Store in a new `simhash` column on `content_records` (BigInteger)
3. Near-duplicate detection: records with Hamming distance <= 3 are flagged
4. Add this as a new method on `DeduplicationService`

**Files Affected**:
- `src/issue_observatory/core/deduplication.py` -- Add SimHash computation and near-duplicate detection
- `src/issue_observatory/core/models/content.py` -- Add `simhash` column
- `src/issue_observatory/core/normalizer.py` -- Compute SimHash during normalization

**Database Changes**: Alembic migration adding `simhash BIGINT NULL` column to `content_records` with a B-tree index.
**Dependencies**: None
**Estimated Complexity**: L (3-5 days)

---

### Item 16: In-Browser Network Preview

**Problem Statement**: Network analysis tabs show only a description and GEXF download button. No in-browser visualization exists. Findings FP-32, IM-31.

**Proposed Solution**:

Add a lightweight force-directed graph preview using Sigma.js:

1. Add Sigma.js to static assets
2. When the network tab is selected, fetch the graph dict JSON from the existing API endpoint
3. Render a force-directed layout with node labels, size proportional to degree, edge thickness proportional to weight, zoom and pan controls

**Files Affected**:
- `src/issue_observatory/api/templates/analysis/index.html` -- Add canvas element and Sigma.js initialization
- `src/issue_observatory/api/static/` -- Add Sigma.js library

**Dependencies**: None (uses existing JSON API endpoints)
**Estimated Complexity**: M (3-5 days)

---

### Item 17: Enrichment Pipeline Architecture

**Problem Statement**: There is no formal pipeline for post-collection enrichments. Each enrichment would need ad-hoc implementation. CO2 afgift report TD-4, AI uddannelse report Section 7.

**Proposed Solution**:

Design a pluggable enricher interface:

```python
class ContentEnricher(ABC):
    enricher_name: str

    @abstractmethod
    async def enrich(self, record: dict) -> dict:
        """Return enrichment data to store in raw_metadata.enrichments."""

    @abstractmethod
    def is_applicable(self, record: dict) -> bool:
        """Whether this enricher should run on this record."""
```

With concrete implementations:
- `DanishLanguageDetector` -- fallback language detection using `langdetect` or `fasttext`
- `EmergentTermExtractor` -- TF-IDF extraction (from Item 10)
- `NamedEntityExtractor` -- Danish NER (from Item 11)

Enrichments run as Celery tasks post-collection. Results stored in `raw_metadata.enrichments.{enricher_name}`.

**New Files**:
- `src/issue_observatory/analysis/enrichments/__init__.py`
- `src/issue_observatory/analysis/enrichments/base.py`
- `src/issue_observatory/analysis/enrichments/language_detector.py`

**Files Affected**:
- `src/issue_observatory/workers/` -- Add enrichment task dispatch

**Dependencies**: None (but Items 10 and 11 benefit from this architecture)
**Estimated Complexity**: L (3-5 days for the framework; individual enrichers are M each)

---

## Implementation Sequencing

```
Phase A (Weeks 1-2):
  Item 1 (Dynamic arena grid) -----> Item 2 (Tier validation)
  Item 3 (Actor unification)          |
  Item 4 (UI polish)                  |
  Item 7 (Duplicate exclusion)        v
                                   Item 8 (Collection detail - depends on Item 1)

Phase B (Weeks 3-4):
  Item 5 (Chart improvements)
  Item 6 (Export improvements)
  Item 9 (Content browser)

Phase C (Weeks 4-6):
  Item 10 (Emergent terms) ---------> Item 13 (Enhanced bipartite - depends on 10)
  Item 12 (Temporal networks)
  Item 11 (Actor roles - Step 1)

Phase D (Weeks 6-8+):
  Item 14 (Boolean queries)
  Item 15 (Near-duplicate detection)
  Item 16 (In-browser network preview)
  Item 17 (Enrichment pipeline)
```

## Readiness Projections

| Phase Completed | Discourse Tracking Readiness | Issue Mapping Readiness |
|-----------------|---------------------------|------------------------|
| Current (pre-implementation) | 75-80% | 55-60% |
| After Phase A | 88-92% | 68-72% |
| After Phase B | 95%+ (publication quality) | 72-75% |
| After Phase C | 95%+ | 88-92% (full Marres workflow) |
| After Phase D | 97%+ | 95%+ |

## Critical Files for Implementation

| File | Items | Role |
|------|-------|------|
| `api/templates/query_designs/editor.html` | 1, 2, 3, 4 | Most-modified frontend file: hardcoded arena grid, term help text, actor panel |
| `arenas/registry.py` | 1 | Arena discovery infrastructure; already has `list_arenas()` |
| `analysis/descriptive.py` | 7, 10 | Duplicate exclusion and emergent term extraction |
| `analysis/network.py` | 7, 12, 13 | Temporal snapshots and enhanced bipartite |
| `analysis/export.py` | 6, 12, 13 | Column headers, extended columns, dynamic GEXF |

---

*This plan is detailed enough that any specialized agent (frontend-engineer, db-data-engineer, core-application-engineer) can pick up an item and implement it without ambiguity. Items within the same phase can largely be parallelized across agents.*
