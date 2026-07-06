# UX Test Report -- Network Analysis Page

Date: 2026-03-29
Project tested: valg2026 (569c15f2-3007-4d9e-8f26-72b93367fcb9)
Application: http://localhost:8022
Authenticated as: admin@example.com

Arenas with data: google_search (106k), youtube (69k), x_twitter (29k), bluesky (3.9k), tiktok (3.8k), domain_crawler (3.2k), reddit (2.4k), openrouter (1.8k), ritzau_via (1.2k), facebook (761), rss_feeds (289), gdelt (229), telegram (163), instagram (132), google_autocomplete (39)

Scenarios run: Network building (all filter combos), advanced settings, network types, rendering/UI, scale testing, export/download, error handling, data quality

---

## BLOCKERS

### B1. GEXF export crashes for both keyword and entity networks [core]

**Severity:** BLOCKER -- the primary research export feature is completely non-functional

The "Download GEXF" button (and both the "GEXF (backboned)" and "GEXF (full)" split buttons that appear after network reduction) crash with an unhandled `ValueError`. The researcher sees a raw Python stack trace in the browser.

**Root cause:** The export route at `/networks/export-gexf` passes `network_type` as `"keyword"` or `"entity"` (the values from the frontend segmented control), but `ContentExporter.export_gexf()` only accepts `"actor"`, `"term"`, `"bipartite"`, or `"enhanced_bipartite"`. Both `"keyword"` and `"entity"` hit the `else` branch and raise:

```
ValueError: Unknown network_type 'keyword'. Choose from: 'actor', 'term', 'bipartite', 'enhanced_bipartite'.
```

**Impact:** A researcher who has spent time configuring filters and building a network cannot export the result for use in Gephi. This undermines the entire network analysis workflow -- building a network in the browser is a preview step, and the real analysis happens in dedicated tools like Gephi after GEXF export.

**Verified by:** `curl ... /networks/export-gexf?network_type=keyword&...` and `curl ... /networks/export-gexf?network_type=entity&...` both return stack traces.

**Files:**
- `src/issue_observatory/api/routes/networks.py` line 543 -- passes `network_type` directly
- `src/issue_observatory/analysis/export.py` line 913-925 -- `export_gexf()` dispatch does not recognize "keyword" or "entity"

**Secondary issue:** Even if the dispatch were fixed, the GEXF serializers (`_build_actor_gexf`, `_build_term_gexf`, `_build_bipartite_gexf`) expect node attributes named `"type"`, `"platform"`, `"post_count"`, `"frequency"`, `"degree"`. The network builder produces nodes with `"node_type"`, `"doc_count"`, and `"entity_type"` -- different field names. This means the GEXF output would have incorrect/empty node attributes even after fixing the dispatch.

---

### B2. Multi-select platform and arena category filters silently ignored [core]

**Severity:** BLOCKER -- the researcher's filter selections do not produce the expected results

The frontend presents checkbox-based multi-select dropdowns for both "Platforms" and "Arenas" (arena categories). A researcher can select, for example, both "bluesky" and "reddit" and reasonably expect the network to include data from both platforms. Instead, only the first selected value is used; the rest are silently discarded.

**Root cause:** In `networks.py` lines 171-172:
```python
arena_category = categories_list[0] if categories_list else None
platform = platforms_list[0] if platforms_list else None
```

The `parse_csv_param()` correctly splits the comma-separated string into a list, but then only the first element is passed to `build_keyword_network()` / `build_entity_network()`. The downstream `build_content_where()` filter builder only accepts a single `platform` and single `arena` value.

**Verified by:** `platforms=bluesky,reddit` returns exactly 304 nodes / 380 edges -- identical to `platforms=bluesky` alone (304/380). Reddit data is completely excluded despite being selected.

**Impact:** A core use case of the Networks page is comparing actor and keyword co-occurrence across platforms. A researcher studying Danish election discourse across Bluesky, Reddit, and RSS feeds would see only Bluesky data and have no indication that their other selections were ignored. Results would be incomplete and potentially misleading if published.

**Files:**
- `src/issue_observatory/api/routes/networks.py` lines 171-172
- `src/issue_observatory/analysis/_filters.py` -- `build_content_filters()` only accepts single `arena` and `platform` parameters

---

### B3. All-arenas queries timeout without warning or cancellation [core]

**Severity:** BLOCKER -- network building appears to hang indefinitely

When the researcher clicks "Build Network" without any platform/arena filter (approximately 222k qualifying records), the request runs for over 5 minutes, exceeds HTTP timeout limits, and returns an empty response. The frontend shows the "Building network..." spinner indefinitely with no progress indication, no estimated time, and no ability to cancel.

**Verified by:** Request to keyword-network endpoint with only `project_id` and `min_weight=10` (generous threshold) timed out after 5 minutes with HTTP code 000.

Even the "news" arena category alone (approximately 5k records) takes over 2 minutes and times out. Only individual platforms with fewer than approximately 4k records (bluesky at 3.9k: 0.4 seconds; rss_feeds at 289: near-instant) complete within acceptable time.

**Impact:** A researcher who does not pre-filter to a specific platform will see the page hang. They have no way to know whether the operation is still running, whether their filters were wrong, or whether the system is broken. The "Building..." spinner provides no progress feedback and no timeout message. The researcher's only option is to reload the page and start over.

**Contributing factors:**
- The network builder processes all content records in 1000-row batches with in-memory RAKE keyword extraction per record (line 108-150 in `network_builder.py`), which is O(N) in record count
- No server-side timeout or record count cap before initiating the build
- No pre-flight estimate warning the researcher about the data volume
- No server-sent progress updates during the build

---

## FRICTION POINTS

### F1. "Unknown" sender dominates keyword networks for arenas lacking author metadata [data]

**Severity:** Major

For RSS feeds, 84% of content records (278 of 332) have `author_display_name IS NULL`. In the network builder, these all become a single "unknown" sender node, which then connects to every keyword extracted from those records. The result is a star-shaped graph with "unknown" as the hub and all keywords as spokes -- not a meaningful network structure.

The researcher sees a network where one enormous node labeled "unknown" dominates the visualization, obscuring any real author-keyword relationships. The remaining named nodes (Borsen journalists with email-format names like `hare@borsen.dk (Hakon Redder)`) are peripheral.

**Verified by:** RSS keyword bipartite network: "unknown" node has `doc_count: 236`, connects to 51 of 59 edges. Next largest sender has `doc_count: 8`.

**Affected arenas:** rss_feeds, gdelt, domain_crawler, google_search -- any arena where `author_display_name` is frequently null.

**Recommendation:** Either exclude records with null author from sender-grouped networks (with a clear message: "N records excluded due to missing author metadata"), or collapse them under a per-platform pseudo-node (e.g., "rss_feeds (anonymous)") so they do not create a single misleading hub.

---

### F2. Keyword extraction produces HTML/JavaScript artifacts as "keywords" [data]

**Severity:** Major

The RAKE keyword extractor operates on raw `text_content` that contains un-stripped HTML entities and JavaScript code fragments. This produces keywords like:

- `#248`, `#230`, `#229` (HTML character entities for o-umlaut, ae, aa -- Danish characters that were double-encoded)
- `nbsp` (HTML non-breaking space entity)
- `addeventlistener`, `window`, `event`, `document` (JavaScript DOM API calls embedded in scraped content)
- `https`, `//www`, `//t`, `com`, `//bit`, `//twitter` (URL fragments)
- `subscribe`, `in this video`, `fair use`, `comment` (YouTube boilerplate)

**Verified by:** YouTube keyword network top 15 keywords are all boilerplate/URL fragments. RSS keyword networks include HTML entity fragments.

**Impact:** Keywords are the core analytical output of the keyword network. When the top-ranked keywords are HTML artifacts rather than substantive terms, the network is not usable for research. A researcher would need to manually filter out dozens of garbage keywords before the network provides any analytical value.

**Recommendation:** Strip HTML entities, decode character references, remove URL patterns, and filter out common boilerplate phrases before running RAKE. Alternatively, apply text cleaning (similar to what a scraper's `trafilatura` pipeline does) at the keyword extraction step rather than relying on raw `text_content`.

---

### F3. Unipartite entity projection assigns wrong node_type [core]

**Severity:** Moderate

When building a `unipartite_entity` network (entity-to-entity co-occurrence via shared senders), the `project_to_unipartite()` function assigns `node_type: "keyword"` to all entity nodes. This is because the function's logic (line 511) sets node_type based on the `collapse_type` parameter, not the actual node semantics:

```python
"node_type": "sender" if collapse_type != "sender" else "keyword",
```

When projecting to entity-only (`collapse_type="sender"`), the result is `"keyword"` instead of `"entity"`.

**Verified by:** `mode=unipartite_entity` on entity network returns all nodes with `node_type: "keyword"`. In the visualization, these render as yellow (keyword color) instead of the expected entity colors (orange for PERSON, red for ORG, green for GPE/LOC). The legend does not match the visualization.

**Impact:** Visual confusion. The researcher sees a unipartite entity network where all nodes are yellow with a "Keyword" legend, even though every node is actually an entity. Entity type sub-coloring (PERSON vs ORG vs GPE) is lost entirely.

---

### F4. No loading progress or time estimate for network builds [frontend]

**Severity:** Moderate

The "Building network..." loading state shows only a spinner with no indication of progress. For smaller datasets (rss_feeds: 289 records) the build completes in under a second. For medium datasets (bluesky: 3.9k records) it takes 0.4 seconds. But for larger datasets (youtube: 69k records, taking 20+ seconds), the researcher has no way to distinguish "still processing" from "something went wrong."

There is no:
- Record count estimate before building ("This query covers approximately 3,850 records")
- Progress bar during build
- Elapsed time counter
- Cancel button
- Timeout message after a threshold

---

### F5. Advanced settings labels use ambiguous research terminology [frontend]

**Severity:** Minor

Several advanced settings lack sufficient explanation for a researcher unfamiliar with network analysis:

- **"Mode: Bipartite / Unipartite group / Unipartite type"**: The labels "Unipartite group" and "Unipartite type" are not self-explanatory. A researcher may not know that "Unipartite group" means projecting sender-to-sender (or platform-to-platform) by shared keywords, while "Unipartite type" means keyword-to-keyword (or entity-to-entity) by shared senders.
- **"Content: Full / Window"**: No explanation of what "window mode" does. The researcher would not know this means extracting only N words around search term occurrences rather than analyzing the full text.
- **"Min keywords/sender"** and **"Max keywords/sender"**: The labels update dynamically (good), but there is no tooltip explaining that min_items filters out senders who mention fewer than N distinct keywords, and max_items keeps only the top N keywords per sender.
- **"Giant component only"**: Assumes graph theory knowledge. "Show only the largest connected cluster" would be more accessible.

---

### F6. Query validation error messages are raw JSON [frontend]

**Severity:** Minor

When a validation error occurs (e.g., `min_weight=0`), the error message shown to the researcher is:

```
Network build failed (422). {"detail":[{"type":"greater_than_equal","loc":["query","min_weight"],"msg":"Input should be greater than or equal to 1","input":"0","ctx":{"ge":1}}]}
```

This is a raw Pydantic validation response concatenated with the HTTP status code -- developer output, not researcher-facing language.

---

### F7. Empty network state message could be more helpful [frontend]

**Severity:** Minor

When a build returns zero nodes, the message is: "No network data found. Try broadening your filters or selecting a different project."

This is acceptable but could be improved by indicating *why* the result is empty. For example, if the entity network returns nothing because no enrichments have been run, the message could say: "No entity data found. Entity networks require NER enrichment to be run on collected content first."

The current message gives the same generic text regardless of whether the issue is:
- No content records match the filters
- Content exists but has no author metadata (entity mode skips these)
- Content exists but has no pre-computed NER enrichments (entity network skips these)
- The search terms produced no window-mode matches

---

### F8. Sender node labels expose email addresses in RSS data [data]

**Severity:** Minor (but GDPR-relevant)

For Borsen RSS feed content, sender labels show email-format author names: `hare@borsen.dk (Hakon Redder)`, `soch@borsen.dk (Soren S. D. Christiansen)`. These appear as node labels in the network visualization and would be included in GEXF exports.

While these are journalist bylines from public news articles (and thus likely public figures), the inclusion of full email addresses in network exports deserves consideration from a data handling perspective.

---

## PASSED

### P1. Page loads and renders correctly
The Networks page loads at `/networks` with all required CDN dependencies (graphology, sigma.js, graphology-library). The Alpine.js `networksDashboard()` component initializes, filter options load from the API, and the page renders a clean empty state with the instruction "Configure filters and click Build Network to visualize."

### P2. Filter options populate correctly for project
The `/networks/filter-options` endpoint returns all 5 projects, 3 query designs (Sundhed, Udenrigspolitik og forsvar, Okonomi) with correct project_id associations, 79 search terms with proper Danish characters (gronland, vaernepligt, formueskat, etc.), 4 arena categories, and 17 distinct platforms. Project scoping works: passing `project_id` correctly restricts query designs and search terms.

### P3. Keyword bipartite network builds and renders
RSS feeds keyword bipartite network (min_weight=3): 62 nodes, 59 edges. Response time: near-instant (<1 second for 289 records). Nodes correctly typed as "sender" and "keyword". Danish keywords are present and meaningful (trump, usa, gronland, hormuzstraedet, ukraine, formueskat, socialdemokratiet, pensionsalderen).

### P4. Entity bipartite network builds correctly
RSS feeds entity bipartite network (min_weight=2): 64 nodes, 66 edges. Entity types correctly preserved (PERSON, ORG, LOC). Named entities are plausible Danish-context entities (Donald Trump, Martin Lidegaard, etc.).

### P5. Unipartite projections work
- Unipartite sender (keyword): 7 nodes, 7 edges, all nodes typed "sender"
- Unipartite keyword: 20 nodes, 110 edges, all nodes typed "keyword"
- Unipartite entity sender: 11 nodes, 20 edges
- Unipartite entity: 55 nodes, 1432 edges (though node_type is wrong -- see F3)

### P6. Group-by-platform works (with single category/platform)
Bipartite grouped by platform, arena_categories=news: 58 nodes, 110 edges. Four platform nodes correctly identified: ritzau_via (1240 docs), domain_crawler (3183), gdelt (120), rss_feeds (149). Keywords shared across platforms are visible.

### P7. Date range filtering produces different results
RSS keyword bipartite with date_from=2026-03-20, date_to=2026-03-29: 19 nodes, 18 edges (narrower than unfiltered 62/59). Date filtering is effective.

### P8. Min weight threshold works
Increasing min_weight from 1 to 3 for RSS keyword bipartite reduces from a larger set to 62 nodes / 59 edges. The threshold effectively prunes low-frequency co-occurrences.

### P9. Min/max items filtering works
RSS keyword bipartite with min_items=5, max_items=10: 23 nodes, 22 edges (reduced from 62/59 without filtering). Senders with fewer than 5 distinct keywords are excluded; each remaining sender keeps at most 10 keywords.

### P10. Giant component extraction works
RSS keyword bipartite with giant_component_only=true: 139 nodes, 138 edges. The giant component is correctly identified and isolated.

### P11. Window content mode works
Keyword network with content_mode=window, window_size=15: 135 nodes, 134 edges. The window mode produces a different, generally more focused keyword set compared to full content mode.

### P12. Entity type filtering works
Entity network with entity_types=PERSON only: 20 nodes, 18 edges. All entities are correctly filtered to PERSON type only (Donald Trump, Martin Lidegaard, Trumps, Trump). No ORG, GPE, or LOC entities leak through.

### P13. Empty results handled gracefully
Impossible date range (2030-01-01 to 2030-01-02): API returns `{"nodes":[],"edges":[]}`. The frontend displays the error message "No network data found. Try broadening your filters or selecting a different project."

### P14. Network size limits and backboning work
YouTube keyword bipartite (min_weight=5): reduced from 4,950 nodes / 6,641 edges to 268 / 358 via degree<2 pruning followed by disparity backbone (alpha=0.2). The reduction notice is displayed with original counts and an explanation.

### P15. Visualization controls present
The stats bar correctly shows node count, edge count, and density. Legend updates dynamically based on network type and grouping dimension. ForceAtlas2 toggle, gravity slider, and spread slider are present. Both backboned and full GEXF export buttons appear when reduction has been applied.

### P16. Validation rejects invalid parameters
min_weight=0 returns HTTP 422 with validation message. The input constraints (ge=1 for min_weight, ge=1 for min_items and max_items) are enforced server-side.

### P17. Clear filters button works
The clear button correctly shows/hides based on whether any filters are active, and resets all filter state (dates, query designs, search terms, categories, platforms).

---

## DATA QUALITY FINDINGS

### DQ1. YouTube content dominated by channel boilerplate

YouTube `text_content` includes channel descriptions, subscription prompts, and social media links alongside actual video descriptions. The RAKE extractor picks up "subscribe", "in this video", "fair use", "educational purpose", and URL fragments as top keywords. For a project with 69k YouTube records, this produces keyword networks where the most prominent terms are platform boilerplate rather than substantive content.

**Recommendation:** Either strip boilerplate patterns from YouTube `text_content` before keyword extraction, or use `title` field instead of `text_content` for YouTube records in the keyword network builder. [data]

### DQ2. HTML entity encoding issues in RSS content

RSS feed content contains un-decoded HTML character entities. The characters ae (U+00E6), o-slash (U+00F8), and a-ring (U+00E5) appear as `#230`, `#248`, `#229` respectively in the keyword extraction output. The `nbsp` entity also appears as a keyword. This indicates that `text_content` for some RSS records contains HTML-encoded text rather than clean plaintext.

**Recommendation:** Ensure RSS content normalisation decodes all HTML entities before storing to `text_content`. Alternatively, apply html.unescape() in the keyword extraction pipeline. [data]

### DQ3. JavaScript code fragments in crawled content

Domain crawler and possibly other web-scraping arenas include JavaScript code in `text_content`. Keywords like "addeventlistener", "window", "event", and "document" are JavaScript DOM API calls, not meaningful content terms.

**Recommendation:** Apply more aggressive text cleaning (strip `<script>` blocks, filter out common JS identifiers) at collection time or at keyword extraction time. [data]

### DQ4. Non-Danish content present in social_media arena category

The social_media keyword network for valg2026 includes significant non-Danish content: sender names like "India Today", "The Sun", "MLB", "South Korea Hotels Planet", and "I've Had It" alongside English keywords like "welcome", "scholarship", "building long-term". This suggests that the Danish language filter on YouTube and potentially other social media arenas is not sufficiently strict, or that content matching Danish search terms in non-Danish contexts is being included.

**Recommendation:** Review language filtering for YouTube and other social media collectors. Consider adding a `language` filter to the network builder so researchers can restrict to `lang=da` content only. [data]

### DQ5. Author metadata sparse across several arenas

RSS feeds: 84% of records have null `author_display_name`. This creates a single "unknown" hub node that dominates sender-grouped networks. The problem likely affects other arenas as well (GDELT articles often lack author attribution, Google Search results do not have authors, etc.).

**Recommendation:** (1) Add a metadata completeness indicator on the filter panel so researchers know what percentage of records in their selection have author data before building a sender-grouped network. (2) Consider grouping null-author records by source domain rather than collapsing them all into "unknown". [data]

---

## DOCUMENTATION GAPS

### D1. No documentation for the Networks page

There is no user-facing guide explaining what the Networks page does, how to use its filters, what the different network modes mean, or how to interpret the results. The `docs/guides/what_data_is_collected.md` guide covers arena data but not analysis features. The previous audit (`docs/ux_reports/dashboard_networks_audit.md`) documents bugs but is not a user guide.

A researcher arriving at the Networks page has only the page subtitle ("Keyword and entity co-occurrence network analysis by sender or platform") and must figure out the rest through experimentation.

### D2. No explanation of network modes anywhere in the UI

The advanced settings offer three graph modes (Bipartite, Unipartite group, Unipartite type) with no inline help text, tooltips, or links to documentation. "Bipartite" and "unipartite" are graph theory terms that many media researchers will not know.

### D3. No guidance on filter/scale trade-offs

There is no documentation or in-app guidance about the relationship between data volume and build time. A researcher selecting "All projects" with no platform filter on a dataset with 200k+ records will experience a timeout, with no prior warning. Documenting expected build times for different data volumes would prevent frustration.

---

## RECOMMENDATIONS

Prioritized by impact on research workflow:

1. **[core] Fix GEXF export dispatch** -- Map `"keyword"` to the appropriate GEXF serializer (bipartite or term, depending on graph mode) and `"entity"` likewise. Also update the GEXF serializers to read `node_type`, `doc_count`, and `entity_type` from the network builder's output format instead of the legacy `type`, `post_count`, `frequency` field names. This is the single most impactful fix because it restores the primary export path.

2. **[core] Support multi-value platform and arena_category filters** -- Change the network builder to accept lists of platforms and arena categories, and update `build_content_filters()` to generate `IN (...)` clauses. This restores the intended cross-platform comparison capability that the frontend already presents.

3. **[core] Add pre-flight record count check and timeout** -- Before running the keyword extraction loop, query the record count and either (a) warn the researcher if it exceeds a threshold (e.g., 10,000 records) or (b) enforce a server-side timeout with a clear error message suggesting the researcher narrow their filters.

4. **[data] Improve keyword extraction quality** -- Strip HTML entities, URL patterns, JavaScript identifiers, and platform boilerplate from text before running RAKE. Consider a configurable stopword list that includes common URL/HTML/JS tokens.

5. **[frontend] Add tooltips or help text for advanced settings** -- Provide plain-language descriptions for Bipartite ("Shows connections between senders and keywords"), Unipartite group ("Shows which senders share keywords in common"), Unipartite type ("Shows which keywords appear together in the same sources"), Window mode ("Extracts keywords only from the N words surrounding your search terms"), and Giant component ("Shows only the largest connected cluster, removing isolated fragments").

6. **[core] Handle null-author records in sender-grouped networks** -- Either exclude them with a clear count ("236 records without author metadata excluded"), group them by source domain or platform, or use `pseudonymized_author_id` as a fallback node identifier.

7. **[frontend] Add cancel button and progress feedback during network build** -- Show elapsed time, add a cancel button that aborts the fetch, and display a timeout message if the build exceeds 30 seconds.

8. **[core] Fix unipartite projection node_type assignment** -- Update `project_to_unipartite()` to preserve the correct node_type for the retained dimension (entity nodes should keep `node_type: "entity"` in unipartite_entity mode, not be relabeled as "keyword").

9. **[data] Add language filter to network builder** -- Allow the researcher to restrict keyword extraction to content with a specific `language` value, preventing non-Danish content from polluting Danish discourse network analysis.

10. **[frontend] Improve error message formatting** -- Parse HTTP 422 validation errors into human-readable messages. Instead of showing raw JSON, display: "Minimum edge weight must be at least 1."

11. **[frontend/docs] Create a Networks user guide** -- Document the available network types, explain what each filter does, provide recommended starting configurations for common research scenarios, and explain how to use GEXF exports in Gephi.

---

## TEST MATRIX

| Test | Filter Configuration | Expected | Actual | Status |
|------|---------------------|----------|--------|--------|
| Keyword bipartite, rss_feeds | platforms=rss_feeds, min_weight=3 | Network with sender+keyword nodes | 62 nodes, 59 edges | PASS |
| Entity bipartite, rss_feeds | platforms=rss_feeds, min_weight=2 | Network with sender+entity nodes | 64 nodes, 66 edges | PASS |
| Unipartite sender (keyword) | platforms=rss_feeds, mode=unipartite_sender | Sender-only nodes | 7 nodes, 7 edges | PASS |
| Unipartite keyword | platforms=rss_feeds, mode=unipartite_keyword | Keyword-only nodes | 20 nodes, 110 edges | PASS |
| Unipartite entity | platforms=rss_feeds, mode=unipartite_entity | Entity-only nodes | 55 nodes, 1432 edges (wrong node_type) | PARTIAL |
| Unipartite sender (entity) | platforms=rss_feeds, mode=unipartite_sender | Sender-only nodes | 11 nodes, 20 edges | PASS |
| Group by platform, news | arena_categories=news, group_by=platform | Platform+keyword nodes | 58 nodes, 4 platforms | PASS |
| Date range narrow | date_from=2026-03-20, date_to=2026-03-29 | Fewer results than unfiltered | 19 nodes (vs 62) | PASS |
| Window content mode | content_mode=window, window_size=15 | Different keywords than full mode | 135 nodes (vs 62) | PASS |
| Entity type PERSON only | entity_types=PERSON | Only PERSON entities | 20 nodes, all PERSON | PASS |
| Min/max items | min_items=5, max_items=10 | Reduced network | 23 nodes (vs 62) | PASS |
| Giant component | giant_component_only=true | Largest connected component | 139 nodes | PASS |
| Empty date range | date_from=2030-01-01 | Empty result, graceful message | `{"nodes":[],"edges":[]}` | PASS |
| Multi-platform select | platforms=bluesky,reddit | Both platforms in network | Only bluesky (304 nodes) | FAIL |
| Multi-category select | arena_categories=news,social_media | Both categories | Only news (162 nodes) | FAIL |
| Scale: YouTube (69k records) | platforms=youtube, min_weight=5 | Builds within 30s | Builds, 268 nodes (reduced from 4950) | PASS |
| Scale: All arenas (222k) | project_id only, min_weight=10 | Builds or warns | Timeout after 5min, no error | FAIL |
| Scale: News category (5k) | arena_categories=news, min_weight=3 | Builds within 30s | Timeout after 2min | FAIL |
| GEXF export keyword | network_type=keyword | Downloads .gexf file | ValueError crash | FAIL |
| GEXF export entity | network_type=entity | Downloads .gexf file | ValueError crash | FAIL |
| Invalid mode | mode=invalid_mode | Error or fallback | Defaults to bipartite (62 nodes) | PASS (silent fallback) |
| min_weight=0 | min_weight=0 | Validation error | HTTP 422 | PASS |
| Filter options API | project_id=valg2026 | Projects, designs, terms, platforms | All correct, 79 search terms | PASS |
| Query design filter | query_design_ids=Sundhed | Scoped to Sundhed | 0 nodes (only 64 Sundhed bluesky records) | PASS |
