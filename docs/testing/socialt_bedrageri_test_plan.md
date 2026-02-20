# Socialt Bedrageri Implementation Test Plan

**Date:** 2026-02-20
**Scope:** Comprehensive testing for all 16 recommendations (SB-01 through SB-16)
**Status:** Ready for execution

---

## Test Execution Prerequisites

### Environment Setup
- [ ] PostgreSQL 16+ running and accessible
- [ ] Redis 7+ running
- [ ] Python virtual environment activated (`.venv`)
- [ ] Dependencies installed: `pip install -e ".[dev]"`
- [ ] Database migrated to head: `.venv/bin/alembic upgrade head` (includes migration 012 for codebook)
- [ ] Test database seeded with sample data (or use factories)
- [ ] FastAPI dev server running: `uvicorn issue_observatory.api.main:app --reload`
- [ ] Celery worker running (for collection tests)

### Test User Setup
- [ ] Admin user created with `scripts/bootstrap_admin.py`
- [ ] Regular test user created for non-admin scenarios
- [ ] At least one query design with completed batch runs
- [ ] At least one live tracking collection run

---

## P0 (Critical) Features

### SB-01: One-Click Term Addition from Analysis Dashboard

**Backend Test:**
```bash
pytest tests/unit/test_analysis_routes.py::test_suggested_terms_endpoint -v
```

**Frontend Test (Manual):**
1. Navigate to analysis dashboard for a completed collection run
2. Scroll to "Suggested Terms" section
3. **Expected:** Each term shows an "Add to design" button
4. Click "Add" on a term not yet in the query design
5. **Expected:** Button shows loading state, then "Added" with checkmark, becomes disabled
6. Reload page and check query design
7. **Expected:** Term is added with `group_label: "auto_discovered"`
8. Return to analysis dashboard
9. **Expected:** Previously added term is pre-marked "Already added"

**Acceptance Criteria:**
- [ ] Suggested terms API returns terms with scores
- [ ] Each term shows add button
- [ ] Clicking add creates SearchTerm via `POST /query-designs/{id}/terms`
- [ ] Success feedback shown inline
- [ ] Already-added terms pre-marked correctly (case-insensitive check)
- [ ] Auto-discovered terms have correct group_label

---

### SB-02: One-Click Source Addition from Discovered Links

**Backend Test:**
```bash
pytest tests/unit/test_content_routes.py::test_discovered_links_endpoint -v
```

**Frontend Test (Manual):**
1. Navigate to Discovered Sources page (`/content/discovered-links?query_design_id={id}`)
2. **Expected:** Links grouped by platform
3. For a Telegram channel in results, click "Add to telegram config"
4. **Expected:** Button shows loading, then "Added" with success feedback
5. Navigate to query design arena config
6. **Expected:** Channel is added to `custom_channels` list
7. Return to discovered links
8. **Expected:** Channel now shows "Already tracked"
9. Test with Reddit subreddit, RSS feed, Discord channel

**Acceptance Criteria:**
- [ ] Source-list arenas show "Add to config" buttons (telegram, reddit, rss_feeds, discord, wikipedia)
- [ ] Non-source-list arenas show "Add to actors" fallback
- [ ] Identifiers normalized correctly (@channel for Telegram, r/subreddit for Reddit)
- [ ] PATCH endpoint appends to arena config successfully
- [ ] Already-configured sources pre-marked
- [ ] Design selector works when multiple designs exist

---

### SB-04: Arena Temporal Capability Metadata

**Backend Test:**
```bash
pytest tests/unit/test_arena_registry.py::test_temporal_mode_metadata -v
pytest tests/arenas/test_all_collectors.py::test_temporal_mode_declared -v
```

**API Test:**
```bash
curl http://localhost:8000/api/arenas/ | jq '.[] | {platform_name, temporal_mode}'
```

**Expected Output:**
```json
{"platform_name": "gdelt", "temporal_mode": "HISTORICAL"}
{"platform_name": "reddit", "temporal_mode": "RECENT"}
{"platform_name": "rss_feeds", "temporal_mode": "FORWARD_ONLY"}
{"platform_name": "youtube", "temporal_mode": "MIXED"}
```

**Frontend Test (Manual):**
1. Navigate to query design editor, arena configuration section
2. **Expected:** Each arena card shows temporal mode badge:
   - Blue badge "Historical" for GDELT, Common Crawl, Wayback, TikTok, Event Registry
   - Yellow badge "Recent" for Reddit, Google Search, Bluesky, X/Twitter, etc.
   - Green badge "Forward-Only" for RSS, Via Ritzau, Wikipedia
   - Purple badge "Mixed" for YouTube

**Acceptance Criteria:**
- [ ] All 25 arena collectors declare `temporal_mode` attribute
- [ ] `ArenaCollector` base class has `TemporalMode` enum
- [ ] Registry `list_arenas()` includes temporal_mode in metadata
- [ ] API endpoint `/api/arenas/` returns temporal_mode
- [ ] Frontend displays temporal badges correctly

---

## P1 (High Priority) Features

### SB-03: Post-Collection Discovery Notification

**Backend Test:**
```bash
pytest tests/workers/test_enrichment_tasks.py::test_discovery_summary_emission -v
```

**Frontend Test (Manual):**
1. Run a complete collection with enrichment enabled
2. Open collection detail page
3. Wait for enrichment task to complete
4. **Expected:** "Discovery Summary" panel appears via SSE event with:
   - Count of suggested terms
   - Count of discovered links (total and per-platform breakdown)
   - Links to analysis dashboard and discovered sources page
5. Refresh page
6. **Expected:** Panel still visible (persisted or re-computed on load)

**Acceptance Criteria:**
- [ ] `get_discovery_summary()` queries correct counts
- [ ] Discovery summary emitted via SSE after enrichment
- [ ] Frontend SSE handler captures `discovery_summary` event
- [ ] Panel displays with correct counts and links
- [ ] Links navigate to correct pages with query params

---

### SB-05: Date Range Warning on Collection Launch

**Backend Test:**
```bash
pytest tests/unit/test_collection_routes.py::test_date_range_warnings -v
```

**Frontend Test (Manual):**
1. Navigate to collection launcher
2. Select "Batch" mode
3. Set date range (e.g., last 30 days)
4. Enable arenas: GDELT (HISTORICAL), Reddit (RECENT), RSS (FORWARD_ONLY)
5. Click "Launch Collection"
6. **Expected:** Response includes warning: "The following arenas will not respect your date range: reddit, rss_feeds. They will return recent/current content only."
7. Frontend displays warning banner before final confirmation
8. Launch collection with only HISTORICAL arenas
9. **Expected:** No warning shown

**Acceptance Criteria:**
- [ ] `create_collection_run` checks enabled arenas' temporal_mode
- [ ] Warning generated for RECENT and FORWARD_ONLY arenas
- [ ] `CollectionRunRead` schema includes `warnings` field
- [ ] Frontend displays warning prominently
- [ ] User can proceed or cancel based on warning

---

### SB-06: Cross-Run Comparison Endpoint

**Backend Test:**
```bash
pytest tests/unit/test_analysis_routes.py::test_compare_runs -v
pytest tests/analysis/test_descriptive.py::test_compare_runs_function -v
```

**API Test:**
```bash
# Get two run IDs from the same query design
RUN1="uuid-here"
RUN2="uuid-here"
curl "http://localhost:8000/analysis/compare?run_ids=$RUN1,$RUN2" | jq
```

**Expected Response:**
```json
{
  "run1_id": "uuid",
  "run2_id": "uuid",
  "volume_delta": {
    "run1_total": 150,
    "run2_total": 200,
    "delta_count": 50,
    "delta_percent": 33.33,
    "per_arena": [...]
  },
  "new_actors": [...],
  "new_terms": [...],
  "content_overlap": {
    "shared_count": 50,
    "overlap_percent": 25.0
  }
}
```

**Acceptance Criteria:**
- [ ] `compare_runs()` function computes all 4 metrics
- [ ] Endpoint validates exactly 2 UUIDs provided
- [ ] Ownership enforced on both runs
- [ ] Duplicate-flagged records excluded from all queries
- [ ] Delta calculations correct (run 2 - run 1)
- [ ] Overlap computed via content_hash

---

### SB-07: Design-Level Analysis Aggregation

**Backend Test:**
```bash
pytest tests/unit/test_analysis_routes.py::test_design_level_endpoints -v
pytest tests/analysis/test_descriptive.py::test_design_level_aggregation -v
```

**API Test:**
```bash
DESIGN_ID="uuid-here"
curl "http://localhost:8000/analysis/design/$DESIGN_ID/summary" | jq
curl "http://localhost:8000/analysis/design/$DESIGN_ID/volume" | jq
curl "http://localhost:8000/analysis/design/$DESIGN_ID/actors" | jq
curl "http://localhost:8000/analysis/design/$DESIGN_ID/terms" | jq
```

**Frontend Test (Manual):**
1. Navigate to query design detail page with multiple completed runs
2. Click "View Design-Level Analysis" (if such a button exists, or navigate directly)
3. **Expected:** Analysis dashboard shows aggregated data across all runs
4. Compare with individual run analysis
5. **Expected:** Design-level shows cumulative/aggregated metrics

**Acceptance Criteria:**
- [ ] All design-level endpoints (`/analysis/design/{id}/*`) exist
- [ ] Endpoints aggregate across completed runs for the design
- [ ] Ownership enforced
- [ ] Missing `GET /analysis/design/{id}/terms` endpoint added
- [ ] Frontend can display design-level analysis

---

### SB-08: "Promote to Live Tracking" Button

**Frontend Test (Manual):**
1. Navigate to query design detail page with at least one completed batch run
2. **Expected:** "Start Live Tracking" button visible
3. Click button
4. **Expected:** Confirmation dialog shows:
   - Explanation of live tracking (continuous, no date ranges)
   - Configured arenas list
   - Default tier
5. Click "Confirm"
6. **Expected:** New live collection run created, redirect to run detail page
7. **Expected:** Collection run has `mode: "live"`, no date_from/date_to
8. Test with query design that has no batch runs
9. **Expected:** Button not visible

**Acceptance Criteria:**
- [ ] Button appears only when batch runs exist
- [ ] Dialog shows correct configuration summary
- [ ] Calls `POST /collections/` with mode="live"
- [ ] Successful creation redirects to collection detail
- [ ] No date range included in live run

---

### SB-14: Implement Credit Estimation

**Backend Test:**
```bash
pytest tests/unit/test_credit_service.py::test_estimate_credits -v
pytest tests/unit/test_collection_routes.py::test_estimate_endpoint -v
```

**API Test:**
```bash
curl -X POST http://localhost:8000/collections/estimate \
  -H "Content-Type: application/json" \
  -d '{
    "query_design_id": "uuid-here",
    "mode": "batch",
    "date_from": "2025-01-01T00:00:00Z",
    "date_to": "2025-01-31T23:59:59Z",
    "arenas_config": {"enabled_arenas": ["reddit", "gdelt"]}
  }' | jq
```

**Expected Response:**
```json
{
  "estimated_total": 120,
  "per_arena": [
    {"arena": "reddit", "estimated_credits": 50},
    {"arena": "gdelt", "estimated_credits": 70}
  ],
  "user_balance": 500,
  "can_proceed": true
}
```

**Acceptance Criteria:**
- [ ] `CreditService.estimate()` loads query design and search terms
- [ ] Estimation considers: search terms, arenas, date range, tier
- [ ] Each arena collector's `estimate_credits()` method called
- [ ] Per-arena breakdown included in response
- [ ] User balance checked
- [ ] `can_proceed` flag accurate

---

## P2 (Medium Priority) Features

### SB-09: RSS Feed Autodiscovery

**Backend Test:**
```bash
pytest tests/arenas/test_rss_feed_discovery.py -v
pytest tests/unit/test_query_design_routes.py::test_discover_feeds_endpoint -v
```

**API Test:**
```bash
curl -X POST http://localhost:8000/query-designs/{design_id}/discover-feeds \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.dr.dk"}' | jq
```

**Expected Response:**
```json
{
  "feeds": [
    {
      "url": "https://www.dr.dk/nyheder/service/feeds/allenyheder",
      "title": "DR Nyheder - Seneste nyt",
      "type": "rss"
    }
  ]
}
```

**Frontend Test (Manual):**
1. Navigate to query design editor, RSS panel
2. Click "Discover Feeds" button
3. Enter website URL (e.g., `https://www.information.dk`)
4. Click "Find"
5. **Expected:** List of discovered feeds shown
6. Click "Add" next to a feed
7. **Expected:** Feed added to custom_feeds list
8. Test with URL that has no feeds
9. **Expected:** Friendly "No feeds found" message

**Acceptance Criteria:**
- [ ] `discover_feeds()` parses HTML link tags
- [ ] Fallback probes common feed paths
- [ ] Verifies discovered URLs with HEAD requests
- [ ] Returns titles and types
- [ ] Endpoint handles timeouts/errors gracefully
- [ ] Frontend integration allows one-click addition

---

### SB-10: Reddit Subreddit Suggestion

**Backend Test:**
```bash
pytest tests/arenas/test_reddit_subreddit_suggestion.py -v
pytest tests/unit/test_query_design_routes.py::test_suggest_subreddits_endpoint -v
```

**API Test:**
```bash
curl "http://localhost:8000/query-designs/{design_id}/suggest-subreddits?query=klimaforandringer&limit=10" | jq
```

**Expected Response:**
```json
{
  "subreddits": [
    {
      "name": "denmark",
      "display_name": "r/Denmark",
      "subscribers": 450000,
      "description": "A subreddit for Denmark...",
      "active_users": 1200
    }
  ]
}
```

**Frontend Test (Manual):**
1. Navigate to query design editor, Reddit panel
2. Click "Suggest Subreddits"
3. **Expected:** Suggestions based on search terms shown
4. Click "Add" next to a suggestion
5. **Expected:** Subreddit added to custom_subreddits
6. Test with query parameter override
7. **Expected:** Different suggestions shown

**Acceptance Criteria:**
- [ ] `suggest_subreddits()` uses Reddit search API
- [ ] FREE-tier call via asyncpraw
- [ ] Returns subscriber counts, descriptions
- [ ] Query parameter optional (defaults to search terms)
- [ ] Limit parameter works (1-100)
- [ ] Frontend displays with one-click addition

---

### SB-11: AI Chat Search as Discovery Accelerator

**Frontend Test (Manual):**
1. Navigate to query design editor
2. **Expected:** Prominent "AI Discovery" panel visible between search terms and actors
3. Read panel content
4. **Expected:** Explains AI Chat Search as discovery tool
5. Expand "How to use" section
6. **Expected:** Step-by-step instructions visible
7. Click CTA button
8. **Expected:** Navigates to arena config or shows AI Chat Search section
9. **Expected:** Panel has visual prominence (gradient background, icon)

**Acceptance Criteria:**
- [ ] Discovery panel added to query design editor
- [ ] Positioned strategically after search terms section
- [ ] Clear explanation of discovery benefits
- [ ] Step-by-step instructions included
- [ ] CTA button links to arena config
- [ ] Visual design draws attention

---

### SB-12: Research Lifecycle Indicator

**Frontend Test (Manual):**
1. Create new query design with no runs
2. **Expected:** Lifecycle shows "Design" stage as current
3. Run a batch collection to completion
4. **Expected:** Lifecycle shows "Exploring" stage
5. Start live tracking
6. **Expected:** Lifecycle shows "Tracking" stage
7. Suspend live tracking
8. **Expected:** Lifecycle shows "Paused" stage
9. Resume live tracking
10. **Expected:** Returns to "Tracking" stage

**Acceptance Criteria:**
- [ ] Horizontal stepper visible on query design detail page
- [ ] 4 stages: Design → Exploring → Tracking → Paused
- [ ] Current stage visually distinct (blue pulse animation)
- [ ] Completed stages show green checkmarks
- [ ] Future stages grayed out
- [ ] Stage derived from collection run data (no schema changes)

---

### SB-13: Content Source Labeling (Batch/Live)

**Backend Test:**
```bash
pytest tests/unit/test_content_routes.py::test_content_mode_filter -v
```

**Frontend Test (Manual):**
1. Navigate to content browser
2. **Expected:** "Collection Mode" filter dropdown visible with options: All, Batch, Live
3. Select "Batch"
4. **Expected:** Only content from batch collections shown
5. **Expected:** Each card shows gray "Batch" badge
6. Select "Live"
7. **Expected:** Only content from live tracking shown
8. **Expected:** Each card shows green "Live" badge
9. Test filter with infinite scroll
10. **Expected:** Filter persists through pagination

**Acceptance Criteria:**
- [ ] `_build_browse_stmt()` accepts mode parameter
- [ ] JOIN with collection_runs to get mode
- [ ] Filter by mode when specified
- [ ] Mode included in template dict
- [ ] Dropdown filter in sidebar
- [ ] Badges displayed on content cards
- [ ] Filter composes with user ownership scoping

---

## P3 (Low Priority) Features

### SB-15: Enrichment Results Dashboard Tab

**Backend Test:**
```bash
pytest tests/analysis/test_descriptive.py::test_enrichment_queries -v
pytest tests/unit/test_analysis_routes.py::test_enrichment_endpoints -v
```

**API Tests:**
```bash
RUN_ID="uuid-here"
curl "http://localhost:8000/analysis/$RUN_ID/enrichments/languages" | jq
curl "http://localhost:8000/analysis/$RUN_ID/enrichments/entities?limit=20" | jq
curl "http://localhost:8000/analysis/$RUN_ID/enrichments/propagation" | jq
curl "http://localhost:8000/analysis/$RUN_ID/enrichments/coordination" | jq
```

**Frontend Test (Manual):**
1. Navigate to analysis dashboard for run with enrichments
2. Scroll to "Enrichment Analysis" section
3. **Expected:** 4 panels visible:
   - Language Distribution: table with language codes and counts
   - Named Entities: top entities with types
   - Cross-Arena Propagation: stories with arena lists and timestamps
   - Coordination Signals: detected patterns with actor counts
4. Test with run that has no enrichments
5. **Expected:** "No enrichments available" message shown
6. Click on an entity or story
7. **Expected:** Drill-down to specific content records (if implemented)

**Acceptance Criteria:**
- [ ] 4 new analysis functions query `raw_metadata.enrichments.*`
- [ ] 4 new API endpoints return enrichment data
- [ ] Frontend section added to analysis dashboard
- [ ] Alpine.js component loads 4 panels in parallel
- [ ] Loading states and error handling
- [ ] Empty states when no enrichments exist
- [ ] Drill-down links to content records

---

### SB-16: Annotation Codebook Management

**Database Test:**
```bash
# After running migration 012
.venv/bin/python -c "
from issue_observatory.core.models import CodebookEntry
print('CodebookEntry model loaded successfully')
"
```

**Backend Test:**
```bash
pytest tests/unit/test_codebook_routes.py -v
pytest tests/integration/test_codebook_crud.py -v
```

**API Tests:**
```bash
# Create codebook entry
curl -X POST http://localhost:8000/codebooks/design/{design_id} \
  -H "Content-Type: application/json" \
  -d '{
    "code": "punitive_frame",
    "label": "Punitive Framing",
    "category": "framing",
    "description": "Content that frames social benefits fraud in punitive terms"
  }' | jq

# List codebook entries
curl "http://localhost:8000/codebooks/design/{design_id}" | jq

# Update entry
curl -X PATCH http://localhost:8000/codebooks/{entry_id} \
  -H "Content-Type: application/json" \
  -d '{"label": "Punitive Framing (Updated)"}' | jq

# Delete entry
curl -X DELETE http://localhost:8000/codebooks/{entry_id}
```

**Frontend Test (Manual):**
1. Navigate to query design detail page
2. Click "Manage Codebook" link
3. **Expected:** Codebook manager page loads
4. Click "Add Entry"
5. **Expected:** Modal with form fields opens
6. Fill in: code="economic_impact", label="Economic Impact", category="framing"
7. Click "Save"
8. **Expected:** Entry added to table, success feedback shown
9. Click "Edit" on an entry
10. **Expected:** Pre-filled form opens
11. Modify label, save
12. **Expected:** Entry updated in table
13. Click "Delete", confirm
14. **Expected:** Entry removed from table
15. Navigate to content detail panel
16. Click "Annotate"
17. **Expected:** Codebook dropdown shown (if codebook exists for design)
18. Select a codebook entry
19. **Expected:** Code applied to annotation's frame field
20. Test "Use custom code" checkbox
21. **Expected:** Free-text input revealed

**Acceptance Criteria:**
- [ ] Migration 012 creates `codebook_entries` table
- [ ] `CodebookEntry` model loads without errors
- [ ] All CRUD endpoints functional
- [ ] Ownership guards enforced
- [ ] Global vs scoped codebook logic works
- [ ] Codebook manager UI complete
- [ ] Annotation UI integrates codebook dropdown
- [ ] Custom code fallback available
- [ ] Categories group codes in dropdown

---

## Integration Test Scenarios

### Scenario 1: Full Discovery Workflow
1. Create new query design with initial search terms
2. Run batch collection
3. Navigate to analysis dashboard
4. Add 3 suggested terms via SB-01
5. Navigate to discovered links
6. Add 2 Telegram channels via SB-02
7. Return to query design, verify terms and channels added
8. Run second batch collection with expanded config
9. Compare runs via SB-06
10. Promote to live tracking via SB-08
11. Verify lifecycle indicator shows "Tracking" stage

**Expected:** Complete iterative discovery workflow functions end-to-end

---

### Scenario 2: Temporal Capability Awareness
1. Create query design
2. Navigate to collection launcher
3. Enable mix of HISTORICAL, RECENT, and FORWARD_ONLY arenas
4. Set date range for historical query (6 months ago)
5. **Expected:** Warning shows which arenas will ignore date range
6. Proceed with collection
7. After completion, verify only HISTORICAL arenas returned historical data
8. Check arena cards in config
9. **Expected:** Temporal badges visible on all arenas

**Expected:** Researcher understands temporal limitations before collection

---

### Scenario 3: Design-Level Analysis and Comparison
1. Create query design with 5 search terms
2. Run 3 batch collections over time, expanding terms each time
3. Navigate to design-level analysis
4. **Expected:** See aggregated metrics across all 3 runs
5. Use SB-06 to compare run 1 vs run 3
6. **Expected:** See new actors, new terms, volume delta
7. Export design-level data
8. **Expected:** Export includes all runs' content

**Expected:** Researcher can track query evolution over multiple iterations

---

### Scenario 4: Source Discovery and Configuration
1. Create query design for unfamiliar topic
2. Use SB-09 to discover RSS feeds from 2 news sites
3. Add discovered feeds to config
4. Use SB-10 to suggest Reddit subreddits
5. Add 3 suggested subreddits
6. Enable AI Chat Search and run discovery query
7. Review AI-suggested actors and terms
8. Run collection with configured sources
9. Navigate to discovered links page
10. Find additional sources mentioned in collected content
11. Add via SB-02

**Expected:** Researcher builds comprehensive source list from zero knowledge

---

### Scenario 5: Qualitative Coding Workflow
1. Create query design for "welfare fraud" study
2. Navigate to codebook manager (SB-16)
3. Create codebook with 5 framing codes
4. Group codes under "framing" category
5. Navigate to content browser
6. Open content detail for a record
7. Annotate using codebook dropdown
8. Select "punitive_frame" code
9. Add notes
10. Save annotation
11. Annotate 10 more records with various codes
12. Export content with annotations
13. **Expected:** Consistent coding vocabulary applied

**Expected:** Systematic qualitative analysis with structured codebook

---

## Performance Tests

### Load Test: Enrichment Dashboard
```bash
# Simulate 50 concurrent requests to enrichment endpoints
ab -n 500 -c 50 http://localhost:8000/analysis/{run_id}/enrichments/languages
```
**Expected:** < 500ms p95 latency, no errors

### Load Test: Discovery Endpoints
```bash
# Test RSS autodiscovery with 20 concurrent requests
ab -n 100 -c 20 -T application/json -p feed_discovery_payload.json \
  http://localhost:8000/query-designs/{id}/discover-feeds
```
**Expected:** < 2s p95 latency (network-dependent)

---

## Accessibility Tests

1. Navigate through all new UI elements using keyboard only (Tab, Enter, Escape)
2. **Expected:** All modals, buttons, dropdowns accessible
3. Test with screen reader (VoiceOver on macOS)
4. **Expected:** All new elements have proper ARIA labels
5. Test color contrast on new badges and buttons
6. **Expected:** WCAG AA compliance

---

## Browser Compatibility

Test all frontend features in:
- [ ] Chrome (latest)
- [ ] Firefox (latest)
- [ ] Safari (latest)
- [ ] Edge (latest)
- [ ] Mobile Safari (iOS)
- [ ] Chrome Mobile (Android)

---

## Rollback Test

1. Take database snapshot before migration 012
2. Run migration 012
3. Test codebook CRUD
4. Rollback migration: `.venv/bin/alembic downgrade -1`
5. **Expected:** Database returns to migration 011 state
6. **Expected:** No data loss in existing tables
7. Re-upgrade to head
8. **Expected:** Migration applies cleanly

---

## Documentation Tests

1. Verify all new API endpoints documented in:
   - OpenAPI schema (visit `/docs`)
   - README updates (if applicable)
   - Status files updated (`docs/status/*.md`)
2. Verify ADRs created for significant design decisions
3. Verify implementation notes exist for complex features

---

## Test Execution Checklist

Before declaring features production-ready:
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] All manual frontend tests executed
- [ ] All API tests executed
- [ ] All 5 integration scenarios completed successfully
- [ ] Performance tests meet targets
- [ ] Accessibility tests pass
- [ ] Browser compatibility verified
- [ ] Rollback test successful
- [ ] Documentation complete

---

## Known Issues / Limitations

_(To be filled during testing)_

---

## Test Results Summary

_(To be filled after test execution)_

| Feature | Status | Notes |
|---------|--------|-------|
| SB-01 | ⬜ Not tested | |
| SB-02 | ⬜ Not tested | |
| SB-03 | ⬜ Not tested | |
| SB-04 | ⬜ Not tested | |
| SB-05 | ⬜ Not tested | |
| SB-06 | ⬜ Not tested | |
| SB-07 | ⬜ Not tested | |
| SB-08 | ⬜ Not tested | |
| SB-09 | ⬜ Not tested | |
| SB-10 | ⬜ Not tested | |
| SB-11 | ⬜ Not tested | |
| SB-12 | ⬜ Not tested | |
| SB-13 | ⬜ Not tested | |
| SB-14 | ⬜ Not tested | |
| SB-15 | ⬜ Not tested | |
| SB-16 | ⬜ Not tested | |
