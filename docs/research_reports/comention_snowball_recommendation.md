# Co-Mention Detection in Snowball Sampling: Methodology Recommendation

**Author:** Research Strategist
**Date:** 2026-02-20
**Status:** Recommendation for team discussion
**Scope:** Snowball sampling feature, NetworkExpander, Actor Directory UI

---

## Changelog

- 2026-02-20: Initial recommendation

---

## 1. Summary

Co-mention-based actor expansion is a methodologically distinct and valuable strategy that currently operates as a silent, invisible fallback. This is a problem for research transparency and a missed opportunity for deliberate analytical use. The recommendation is threefold: (a) make the discovery method visible in all snowball results, (b) expose co-mention as an explicit researcher-selectable strategy alongside graph-based expansion, and (c) surface `find_co_mentioned_actors()` as a standalone discovery tool scoped to query designs. None of these changes require new backend capabilities -- the code exists, but the API and UI suppress the information.

---

## 2. Methodological Value Assessment

### 2.1 What co-mention detection reveals that graph traversal does not

Graph-based expansion (follower/following lists, featured channels, forwarding chains) discovers **structural connections** -- who chose to connect with whom on a platform. Co-mention detection discovers **discursive connections** -- who appears alongside whom in the actual content that the researcher has collected.

These are fundamentally different analytical signals:

| Dimension | Graph traversal | Co-mention detection |
|-----------|----------------|---------------------|
| Relationship type | Structural (follow, feature, forward) | Discursive (co-occurrence in text) |
| What it measures | Platform-native social ties | Topical association within collected data |
| Scope | All connections, regardless of topic | Only connections within the research query's scope |
| Bias | Platform popularity bias (high-follower accounts dominate) | Collection bias (only actors mentioned in already-collected content) |
| Coverage | Limited to platforms with public graph APIs (Bluesky, Reddit, YouTube, Telegram) | Works on any platform with text content in `content_records` |
| Danish media research value | Moderate -- many Danish public figures have small follower graphs | High -- Danish discourse is concentrated; co-mentions in news and social media reveal issue-specific actor constellations |

For Danish media research specifically, co-mention detection is arguably **more informative** than graph traversal for most use cases. The reason: Danish public discourse is relatively small and concentrated. A politician, an interest group, and a journalist are more likely to appear together in collected content about a specific issue than to follow each other on Bluesky. The co-mention signal is issue-specific by construction, because it only operates on content already matched by the researcher's query design.

### 2.2 Methodological lineage

Co-mention detection is a standard technique in media and communications research. It maps directly to:

- **Actor co-occurrence analysis** in issue mapping (Marres & Rogers 2005; Venturini 2010), where the goal is to discover which actors are discursively associated with an issue
- **Name co-occurrence networks** in computational journalism studies (Maier et al. 2018), where co-mention frequency in news articles indicates issue-level association
- **Seed expansion in snowball sampling** (Goodman 1961), where the referral chain follows discursive rather than structural links

The system already builds actor co-occurrence networks in `analysis/network.py` via `build_actor_cooccurrence_network()`. The `_expand_via_comention()` method in `NetworkExpander` is effectively a per-actor version of the same analytical operation, but it is hidden from the researcher.

### 2.3 Assessment: high methodological value, currently underutilized

Co-mention detection is not a "fallback" -- it is a first-class expansion strategy that operates on a different analytical dimension than graph traversal. Treating it as a silent fallback:

- Prevents researchers from choosing it deliberately when it would be the appropriate strategy
- Conceals which strategy produced a given discovery, undermining reproducibility
- Prevents researchers from combining strategies thoughtfully (e.g., "run graph expansion on Bluesky, then co-mention expansion on X/Twitter where we have collected content but no graph API")

---

## 3. Transparency Problem

### 3.1 Current state: discovery method is silently dropped

The `NetworkExpander` correctly populates `discovery_method` on every returned `ActorDict`. The `SnowballSampler` preserves this field through the `wave_log` and `actors` list. However:

1. **The API response schema (`SnowballActorEntry`) does not include `discovery_method`.** The field is silently dropped when building the response in `actors.py` lines 687-698.

2. **The wave log includes method names** (`wave_log[depth]["methods"]`) and these are returned via `SnowballWaveEntry.methods`, but they are aggregated per-wave, not per-actor. The UI does not display them.

3. **The UI table columns** are: checkbox, Name, Platforms, Discovery depth. There is no column for discovery method.

4. **The platform selection list** only shows platforms with "first-class graph traversal" (Bluesky, Reddit, YouTube, Telegram). The YF-11 info box states: *"For other platforms, use Discovered Sources to find connected actors through cross-platform links."* This is misleading -- if the researcher selects a seed actor with an X/Twitter presence and includes X/Twitter in the platforms list, co-mention expansion will run silently, but the UI does not offer X/Twitter as a selectable platform.

### 3.2 Why this matters for research

In any published research using snowball sampling, the method section must describe the expansion strategy. A researcher currently cannot distinguish between:

- "This actor was discovered because the seed actor follows them on Bluesky" (structural connection)
- "This actor was discovered because they were mentioned in the same content as the seed actor" (discursive co-occurrence)

These produce different kinds of evidence and support different kinds of claims. Conflating them in the results set is a methodological deficiency.

---

## 4. Recommendations

### 4.1 MUST: Surface discovery method in snowball results (effort: small)

**Priority: Critical**

Add `discovery_method` to `SnowballActorEntry` and display it in the results table. The data already exists in `result.actors` -- it is just dropped during response construction.

Specific changes:
- Add `discovery_method: str` field to `SnowballActorEntry` in `/src/issue_observatory/api/routes/actors.py`
- Populate it from `actor_dict.get("discovery_method", "unknown")` in the response builder (line ~695)
- Add a "Method" column to the discovered actors table in `actors/list.html`
- Use human-readable labels: "Bluesky follows", "Bluesky followers", "Reddit comment mentions", "YouTube featured channels", "Telegram forwarding chain", "Co-mention in collected content"

This change is non-breaking, low-effort, and resolves the transparency problem immediately.

### 4.2 SHOULD: Allow researchers to explicitly select co-mention expansion (effort: small-medium)

**Priority: High**

Currently, the platform list endpoint (`GET /actors/sampling/snowball/platforms`) returns only `["bluesky", "reddit", "youtube", "telegram"]`. Platforms where co-mention is the strategy (X/Twitter, Facebook, Instagram, Threads, TikTok, Gab, Discord) are excluded.

The recommended change:
- The platforms endpoint should return **all** platforms, grouped by expansion type
- Suggested response format:
  ```json
  {
    "graph_platforms": ["bluesky", "reddit", "youtube", "telegram"],
    "comention_platforms": ["x_twitter", "facebook", "instagram", "threads", "tiktok", "gab", "discord"]
  }
  ```
- The UI should present these in two groups with clear labels:
  - "Graph-based expansion" (traverses platform social graphs -- requires API access)
  - "Co-mention expansion" (finds actors mentioned alongside seed actors in your collected data -- requires prior collection runs)
- The YF-11 info box should be updated to explain both strategies, replacing the current text that directs researchers to Discovered Sources for non-graph platforms

This makes the researcher's choice explicit and documented, which is essential for methods sections in published research.

**Important caveat to display in the UI:** Co-mention expansion only works when the researcher has already collected content on the selected platforms. If no content exists for a platform, the expansion will return zero results. The UI should indicate this (e.g., by showing a badge with the count of content records available per platform, or by graying out platforms with no collected data).

### 4.3 SHOULD: Expose `find_co_mentioned_actors()` as a standalone discovery tool (effort: medium)

**Priority: High**

The standalone `find_co_mentioned_actors()` method on `NetworkExpander` performs a different operation than the per-actor `_expand_via_comention()` method. It finds pairs of actors that co-occur across a query design's entire collected content -- a corpus-level analysis rather than a seed-actor-centric one.

This is a powerful discovery tool that currently has no API endpoint and no UI. It answers the question: "Within all the content I have collected for this research question, which actors tend to appear together?"

Recommended implementation:
- New API endpoint: `GET /query-designs/{design_id}/co-mentioned-actors?min_co_occurrences=3`
- Response: list of `{actor_a, actor_b, platform, co_occurrence_count}` pairs
- UI location: the Analysis dashboard (alongside network visualization and descriptive stats), or the Actor Directory when scoped to a query design
- Include an "Add to actor list" action on discovered pairs, following the existing quick-add pattern

This tool is complementary to the existing actor co-occurrence network in `analysis/network.py`, but serves a different purpose: the network visualization shows the full co-occurrence structure; the standalone tool provides an actionable discovery list that feeds back into the actor directory.

### 4.4 COULD: Add co-mention count as evidence strength indicator (effort: small)

**Priority: Medium**

When co-mention expansion discovers an actor, the `_expand_via_comention()` method counts how many distinct content records contain the co-mention. This count is not currently returned (it is used for the `min_records` threshold but then discarded).

Adding a `co_occurrence_count` or `evidence_strength` field to the `ActorDict` for co-mention discoveries would allow the UI to display how strong the co-mention signal is. This helps researchers make informed decisions about which discoveries to add to their actor list.

The same principle applies to graph-based strategies: a Bluesky actor discovered via "follows" is different from one discovered via "followers", and an actor that appears in 50 forwarded messages is a stronger signal than one appearing in 2.

---

## 5. Caveats Researchers Must Understand

The following caveats should be presented in the UI (e.g., as an expandable "About these methods" section in the snowball panel):

### 5.1 Co-mention detection is dependent on prior collection

Co-mention expansion searches `content_records` rows already in the database. If no content has been collected on a platform, co-mention expansion on that platform returns nothing. This is fundamentally different from graph-based expansion, which queries the platform's live API.

**Practical implication:** The workflow should be collection-first, expansion-second. Researchers should run at least one keyword-based collection before attempting co-mention expansion.

### 5.2 Co-mention detection inherits collection bias

The actors discovered via co-mention are bounded by the search terms used in prior collections. If the search terms are narrow, co-mention expansion will only find actors associated with that narrow topic. This is by design (issue-specific discovery), but researchers should understand that broadening search terms would yield different co-mention results.

### 5.3 Regex-based mention extraction has limitations

The current implementation uses `@username` regex patterns (`_COMENTION_MENTION_RE`) to extract mentions from `text_content`. This works well for platforms that use @-mention conventions (X/Twitter, Bluesky, Instagram, TikTok, Gab) but has limitations:

- **News articles** (RSS, GDELT, Event Registry) rarely use @-mentions -- they refer to actors by full name. The regex will not capture "Mette Frederiksen" as a mention.
- **Reddit** uses `u/username`, which is handled by a separate regex in the Reddit-specific expander but not by the generic co-mention regex.
- **Telegram** channel names may not follow the `@` convention in forwarded message bodies.

This means co-mention expansion currently works best on social media platforms and is weak on news media platforms. A future enhancement could combine regex mention extraction with named entity recognition (the `NamedEntityExtractor` enricher already exists) to expand the scope of co-mention detection to news content.

### 5.4 The threshold parameter affects results significantly

The `_COMENTION_MIN_RECORDS` constant is set to 2 (an actor must appear alongside the seed actor in at least 2 distinct content records). For `find_co_mentioned_actors()`, the default `min_co_occurrences` is 3.

These thresholds are not currently configurable by the researcher. Making them adjustable (via the snowball panel UI) would give researchers more control over the sensitivity vs. precision trade-off.

### 5.5 Co-mention is not the same as co-occurrence

The current implementation in `_expand_via_comention()` looks for `@username` patterns that appear in content records that also mention the seed actor. This is **mention co-occurrence** -- both actors are mentioned in the same content item.

The standalone `find_co_mentioned_actors()` uses a different definition: it looks for pairs of `author_platform_id` values that share overlapping `search_terms_matched` arrays within the same query design. This is **authorship co-occurrence** -- both actors authored content matching the same search terms.

These are different analytical constructs. The UI should clearly label which is being used.

---

## 6. Implementation Priority and Dependencies

| Recommendation | Priority | Effort | Depends on |
|----------------|----------|--------|------------|
| 4.1: Surface discovery method | Critical | 2-3 hours | Nothing |
| 4.2: Explicit co-mention platform selection | High | 1-2 days | 4.1 (for transparency) |
| 4.3: Standalone co-mentioned actors endpoint | High | 2-3 days | Nothing (independent) |
| 4.4: Evidence strength indicator | Medium | 0.5-1 day | 4.1 |

Items 4.1 and 4.3 can proceed in parallel. Item 4.2 depends on 4.1 for full value.

No database migrations are required for any of these recommendations. All changes are in the API route layer, Pydantic schemas, and Jinja2 templates.

---

## 7. Files Referenced in This Assessment

- `/src/issue_observatory/sampling/network_expander.py` -- `NetworkExpander` class, `_expand_via_comention()`, `find_co_mentioned_actors()`
- `/src/issue_observatory/sampling/snowball.py` -- `SnowballSampler` class
- `/src/issue_observatory/api/routes/actors.py` -- snowball API endpoint, `SnowballActorEntry` schema (missing `discovery_method`)
- `/src/issue_observatory/api/templates/actors/list.html` -- snowball sampling UI panel
- `/src/issue_observatory/analysis/network.py` -- `build_actor_cooccurrence_network()` (related but separate)
- `/src/issue_observatory/analysis/coordination.py` -- coordination detection (contextual reference)
