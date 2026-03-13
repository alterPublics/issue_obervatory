# Actor/Source List Workflow Redesign: Strategic Recommendation

**Created**: 2026-03-04
**Author**: Research Agent (The Strategist)
**Status**: PROPOSAL -- awaiting team discussion
**Scope**: Actor Directory, source lists, `arenas_config` JSONB, snowball sampling, project settings UI

---

## Changelog

| Date       | Change                                            |
|------------|---------------------------------------------------|
| 2026-03-04 | Initial research and recommendation document      |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current State Analysis](#2-current-state-analysis)
3. [Problems with the Current Architecture](#3-problems-with-the-current-architecture)
4. [Proposed Architecture](#4-proposed-architecture)
5. [Data Model Changes](#5-data-model-changes)
6. [Arena-by-Arena Source List Requirements](#6-arena-by-arena-source-list-requirements)
7. [UI/UX Workflow Design](#7-uiux-workflow-design)
8. [Migration Path](#8-migration-path)
9. [Risks and Tradeoffs](#9-risks-and-tradeoffs)
10. [Implementation Phases](#10-implementation-phases)

---

## 1. Executive Summary

The Issue Observatory currently has two disconnected mechanisms for specifying which accounts/sources a researcher wants to track:

- **Source lists in `arenas_config` JSONB** (for Telegram, RSS, Reddit, Discord, Wikipedia) -- configured directly under the query design editor, stored as simple string arrays
- **The Actor Directory + ActorList + ActorPlatformPresence chain** (for Facebook, Instagram, and optionally Bluesky, YouTube, X/Twitter, etc.) -- a separate system of canonical identity records linked to query designs via ActorList membership

This split creates researcher confusion, inconsistent platform coverage, and a workflow gap where actor-only arenas (Facebook, Instagram) require the Actor Directory but most other arenas use inline source lists. The two systems do not interoperate cleanly.

**This document proposes**:

1. Extending the `arenas_config` source list pattern to all arenas that support actor-based collection, creating a unified "Sources" panel in the query design editor.
2. Repurposing the Actor Directory page as a **discovery and staging area** focused on snowball sampling, network expansion, similarity discovery, and corpus co-occurrence analysis.
3. Adding a "port to project" flow that lets researchers move discovered accounts from the staging area into specific arena source lists in their query designs.

---

## 2. Current State Analysis

### 2.1 Source Lists via `arenas_config` JSONB

Five arenas currently have researcher-configurable source lists stored in `query_designs.arenas_config`:

| Arena | `arenas_config` key path | Item type | UI location |
|-------|--------------------------|-----------|-------------|
| RSS | `rss.custom_feeds` | Feed URLs (`https://...`) | Query design editor, `arenaSourcePanel` |
| Telegram | `telegram.custom_channels` | Channel usernames (`"dr_nyheder"`) | Query design editor, `arenaSourcePanel` |
| Reddit | `reddit.custom_subreddits` | Subreddit names (`"Denmark"`) | Query design editor, `arenaSourcePanel` |
| Discord | `discord.custom_channel_ids` | Channel ID strings (`"12345"`) | Query design editor, `arenaSourcePanel` |
| Wikipedia | `wikipedia.seed_articles` | Article titles (`"Danish politics"`) | Query design editor, `arenaSourcePanel` |

**How they work technically**:

- The query design editor template (`src/issue_observatory/api/templates/query_designs/editor.html`) renders an `arenaSourcePanel` Alpine.js component for each source-list arena (lines 1326-1836).
- The component reads existing items from `design.arenas_config.{arena}.{key}` on page load, and saves changes via `PATCH /query-designs/{id}/arena-config/{arena_name}` (route at `src/issue_observatory/api/routes/query_designs.py`, line 1137).
- At collection time, the Celery task reads `arenas_config` from the QueryDesign row (e.g., `telegram/tasks.py:_load_arenas_config()`, line 119) and passes the custom list to the collector (e.g., `extra_channel_ids` parameter on `TelegramCollector.collect_by_terms()`).
- The collector merges custom sources with built-in defaults (e.g., `_build_channel_list()` in `telegram/collector.py`, line 986, or `_merge_extra_feeds()` in `rss_feeds/collector.py`, line 800).

**Key characteristics**:
- Items are simple strings (URLs, usernames, IDs) -- no relational structure
- Storage is a JSONB array on the QueryDesign row itself
- No concept of canonical identity, cross-platform linking, or GDPR classification
- UI is a simple add/remove list component, consistent across all five arenas
- The pattern is lightweight, self-contained, and works well for these arenas

### 2.2 The Actor Directory System

The Actor Directory is a separate relational system comprising:

**Models** (`src/issue_observatory/core/models/actors.py`):
- `Actor`: Canonical cross-platform entity with `canonical_name`, `actor_type`, `public_figure` (GDPR), `is_shared`, `metadata_` JSONB. Primary key: UUID.
- `ActorAlias`: Alternative name spellings for entity resolution. FK to `Actor`.
- `ActorPlatformPresence`: Maps an Actor to a specific platform account (`platform`, `platform_user_id`, `platform_username`, `profile_url`, `verified`, `follower_count`). Unique constraint on `(platform, platform_user_id)`.
- `ActorListMember`: Many-to-many join between `ActorList` and `Actor`. Records `added_by` (manual/snowball/network/similarity).

**Models** (`src/issue_observatory/core/models/query_design.py`):
- `ActorList`: Named set of actors attached to a query design. Has `sampling_method` field.

**Routes** (`src/issue_observatory/api/routes/actors.py`):
- Full CRUD for actors, presences, aliases
- Quick-add from Content Browser (GR-17)
- Bulk quick-add from discovered links
- Snowball sampling endpoint (`POST /actors/sampling/snowball`)
- Snowball from collection run (`POST /actors/sampling/snowball-from-run`)
- Entity resolution page
- Similarity discovery endpoints (GR-18: platform, content, cross-platform)
- Corpus co-occurrence analysis
- Bulk member add to actor lists

**Routes** (`src/issue_observatory/api/routes/query_designs.py`):
- `POST /query-designs/{id}/actors` -- adds an actor to the query design's default actor list (creating Actor + ActorListMember records)
- `POST /query-designs/{id}/actors/bulk` -- bulk add
- `DELETE /query-designs/{id}/actors/{member_id}` -- remove

**Templates** (`src/issue_observatory/api/templates/actors/`):
- `list.html`: Actor Directory listing with search, add modal, type filtering
- `detail.html`: Actor detail with platform presences, merge, snowball
- `resolution.html`: Cross-platform entity resolution UI

### 2.3 Actor-Only Arena Dispatch

For arenas where `supports_term_search = False` (currently Facebook and Instagram), the collection orchestrator (`src/issue_observatory/workers/tasks.py`, dispatch_batch_collection, line 1496) follows a different code path:

1. Detects actor-only arenas by checking `getattr(collector_cls, "supports_term_search", True)` (line 1276)
2. Calls `fetch_actor_ids_for_design_and_platform()` (`src/issue_observatory/workers/_task_helpers.py`, line 1262) to resolve actor identifiers
3. This function queries the `ActorPlatformPresence -> ActorListMember -> ActorList -> QueryDesign` join chain, filtered by `platform == platform_name`
4. Returns identifiers in precedence order: `profile_url > platform_user_id > platform_username`
5. Dispatches `collect_by_actors` Celery task with the resolved `actor_ids` list

**Critical implication**: For Facebook and Instagram, the ONLY way to configure which accounts to collect from is through the Actor Directory + ActorList system. There is no `arenas_config` source list for these arenas.

### 2.4 Snowball Sampling System

The sampling module (`src/issue_observatory/sampling/`) provides:

- `SnowballSampler` (`snowball.py`): Orchestrates iterative network expansion from seed actors. Runs waves up to `max_depth`, each adding up to `max_actors_per_step` novel actors.
- `NetworkExpander` (`network_expander.py`): Platform-specific expansion strategies (Bluesky follows, Reddit co-posting, YouTube related channels, Telegram forwards, TikTok, Gab, X/Twitter, Facebook, Instagram, Threads).
- `SimilarityFinder` (`similarity_finder.py`): Platform recommendations, TF-IDF content similarity, cross-platform name matching.

These tools are currently exposed via the Actor Directory routes (e.g., `POST /actors/sampling/snowball`) and produce results that can optionally be added to an ActorList.

### 2.5 The Entity Resolver

`EntityResolver` (`src/issue_observatory/core/entity_resolver.py`) provides:
- Exact lookup by `(platform, platform_user_id)`
- `create_or_update_presence()` for establishing new actor records
- `find_candidate_matches()` for fuzzy cross-platform matching
- `merge_actors()` and `split_actor()` for deduplication

---

## 3. Problems with the Current Architecture

### 3.1 Inconsistent Actor Configuration

The fundamental problem: **a researcher who wants to track specific accounts on Facebook must use the Actor Directory, but a researcher who wants to track specific Telegram channels uses the query design editor's source list panel**. These are conceptually the same operation (selecting accounts to monitor) but require completely different workflows and mental models.

| Researcher intent | For Telegram | For Facebook |
|-------------------|--------------|--------------|
| "Track @drnyheder" | Type `drnyheder` in the Telegram source list panel in query design editor | Go to Actor Directory, create an Actor, add a Facebook platform presence with `https://facebook.com/drnyheder`, ensure the actor is in an ActorList linked to the query design |
| Steps required | 1 step | 4-5 steps |
| Where configured | Project settings | Separate page |

### 3.2 Ambiguous Role of the Actor Directory

The Actor Directory page currently serves too many purposes:
- CRUD management of canonical entities (needed for entity resolution and GDPR)
- Platform presence management (needed for actor-only collection)
- Snowball sampling launcher (needed for network discovery)
- Similarity discovery (needed for research methodology)
- Collection source configuration (overlapping with arenas_config source lists)

This overloading makes the page confusing. A researcher opening it might reasonably ask: "Is this where I configure which accounts to collect from? Or is this a research tool for discovering new accounts? Both?"

### 3.3 Missing Source Lists for Important Arenas

The following arenas support `collect_by_actors()` but have NO source list panel in the query design editor:

| Arena | `collect_by_actors()` accepts | Current configuration path |
|-------|-------------------------------|---------------------------|
| Facebook | Facebook page/group/profile URLs | Actor Directory only |
| Instagram | Instagram profile URLs | Actor Directory only |
| Bluesky | Bluesky DIDs or handles | Actor Directory only (or none) |
| X/Twitter | Twitter user IDs or handles | Actor Directory only (or none) |
| YouTube | YouTube channel IDs | Actor Directory only (or none) |
| TikTok | TikTok usernames | Actor Directory only (or none) |
| Threads | Threads usernames | Actor Directory only (or none) |
| Gab | Gab usernames | Actor Directory only (or none) |
| VKontakte | VK user IDs | Actor Directory only (or none) |
| Twitch | Twitch usernames | Actor Directory only (or none) |

For all arenas other than Facebook and Instagram, the `collect_by_actors()` method exists but the dispatch_batch_collection orchestrator only routes to it when `supports_term_search = False`. For arenas like Bluesky, YouTube, and X/Twitter (where `supports_term_search = True`), actor-based collection is available as an API capability but **never triggered** through the normal project-based collection flow unless the researcher manually dispatches it.

### 3.4 No "Discover Then Track" Pipeline

Snowball sampling discovers new accounts, but there is no clear path to move those discoveries into active collection. The researcher must:
1. Run snowball sampling from the Actor Directory
2. Review results
3. Manually add interesting accounts to an ActorList
4. Hope that the ActorList is the right one linked to their query design
5. For source-list arenas (Telegram, Reddit), ALSO manually add the channel/subreddit to the `arenas_config` panel -- the ActorList alone is not sufficient

There is no "port all discovered Bluesky accounts to my project's Bluesky source list" button.

---

## 4. Proposed Architecture

### 4.1 Design Principle: Two Complementary Systems

**System A: Arena Source Lists (Query Design Editor)**
- The researcher's primary interface for specifying "which accounts to track"
- One source list panel per arena that supports actor-based collection
- Simple string arrays stored in `arenas_config` JSONB (extending the existing pattern)
- What appears here is what gets collected -- direct, transparent, predictable

**System B: Actor Staging Area (Repurposed Actor Directory)**
- A research tool for discovering, evaluating, and staging accounts
- Snowball sampling, network expansion, similarity discovery, corpus co-occurrence
- Working lists of discovered accounts that are NOT yet in any project's collection scope
- "Port to project" action to move discovered accounts INTO specific arena source lists

The two systems communicate through a one-way "port" action: discoveries in System B flow into System A when the researcher explicitly approves them.

### 4.2 Unified Source List Pattern

Extend the existing `arenaSourcePanel` pattern to all arenas that support actor-based collection. Each arena gets a source list in `arenas_config`:

```json
{
  "arenas": [...],
  "rss": {"custom_feeds": ["https://..."]},
  "telegram": {"custom_channels": ["channel_name"]},
  "reddit": {"custom_subreddits": ["SubredditName"]},
  "discord": {"custom_channel_ids": ["12345"]},
  "wikipedia": {"seed_articles": ["Article Title"]},
  "facebook": {"custom_pages": ["https://facebook.com/drnyheder"]},
  "instagram": {"custom_profiles": ["https://instagram.com/drnyheder"]},
  "bluesky": {"custom_accounts": ["drnyheder.bsky.social"]},
  "x_twitter": {"custom_accounts": ["drnyheder"]},
  "youtube": {"custom_channels": ["UCxxxxx"]},
  "tiktok": {"custom_accounts": ["@drnyheder"]},
  "threads": {"custom_accounts": ["drnyheder"]},
  "gab": {"custom_accounts": ["username"]},
  "vkontakte": {"custom_accounts": ["user_id"]},
  "twitch": {"custom_channels": ["channel_name"]}
}
```

### 4.3 Source List Resolution at Collection Time

When the orchestrator dispatches an arena task, it should:

1. **For all arenas** (not just actor-only ones): check `arenas_config[platform_name]` for a custom source list
2. **For actor-only arenas** (Facebook, Instagram): the source list is the ONLY input
3. **For dual-mode arenas** (Bluesky, YouTube, X/Twitter, Reddit, etc.):
   - Always dispatch `collect_by_terms()` with search terms
   - If a source list is also configured, ALSO dispatch `collect_by_actors()` with the source list items
   - The two modes are complementary: terms discover new content, actors ensure coverage of specific accounts

4. **Legacy compatibility**: The existing `ActorList -> ActorPlatformPresence` chain continues to work as a fallback. If no `arenas_config` source list exists for a platform, the orchestrator falls back to the existing `fetch_actor_ids_for_design_and_platform()` lookup. This provides backward compatibility during migration.

### 4.4 Repurposed Actor Directory: "Actor Workbench"

The Actor Directory page becomes the "Actor Workbench" -- a research methodology tool rather than a collection configuration tool. Its new primary functions:

1. **Snowball Sampling Hub**
   - Configure and launch snowball sampling runs
   - Set parameters: seed actors, platforms, max_depth, max_actors_per_step
   - View wave-by-wave expansion results
   - Configure co-mention threshold (`min_comention_records`)

2. **Discovery Results Staging**
   - View discovered accounts in a working table
   - Sort/filter by platform, discovery method, depth, follower count
   - Select individual accounts or apply bulk selection
   - Tag accounts for review (accept/reject/defer)

3. **Port to Project**
   - Select one or more discovered accounts
   - Choose a target query design and target arena(s)
   - "Port selected" writes the account identifiers into `arenas_config[arena].custom_{type}[]` on the target query design
   - "Port all" bulk action for efficiency
   - Clear confirmation of what was ported and where

4. **Entity Resolution** (retained)
   - Cross-platform identity linking
   - Merge/split actors
   - This remains useful for GDPR compliance (canonical actor = single DPIA record)

5. **Canonical Actor Registry** (retained, de-emphasized)
   - The Actor, ActorAlias, ActorPlatformPresence models remain
   - They serve as the long-term identity registry
   - The `public_figure` flag remains critical for GDPR (GR-14)
   - But the Actor Directory is no longer the primary place researchers go to configure collection

---

## 5. Data Model Changes

### 5.1 No Schema Migration Required

The proposed architecture requires **no database schema changes**. All new source list data is stored in the existing `arenas_config` JSONB column on `query_designs`. The Actor model and its relationships remain unchanged.

This is a deliberate advantage: JSONB-based source lists avoid the need for new tables, migrations, or foreign key chains. The tradeoff (no referential integrity on source list items) is acceptable because source list items are simple identifiers that the collector validates at runtime anyway.

### 5.2 Actor Model Relationship Preserved

The Actor -> ActorPlatformPresence -> ActorListMember -> ActorList -> QueryDesign relationship chain is preserved for:
- GDPR `public_figure` bypass (GR-14): the `set_public_figure_ids()` mechanism on collectors needs canonical Actor records with `public_figure=True`
- Entity resolution: cross-platform identity linking
- Snowball sampling: seed actors must have Actor records to be expanded
- Content attribution: linking collected content to canonical authors

However, this chain is no longer the **primary** path for configuring which accounts to collect from. It becomes a secondary/supporting path.

### 5.3 Recommended JSONB Schema Convention

For consistency across all arena source lists, adopt a naming convention:

```
arenas_config.{platform_name}.custom_{source_type}
```

Where `{source_type}` is one of: `feeds`, `channels`, `accounts`, `profiles`, `subreddits`, `pages`, `articles`, `channel_ids`.

Each value is always a JSON array of strings. Each string is the simplest identifier that the arena's collector accepts in `actor_ids` (or equivalent parameter).

### 5.4 Public Figure Bridge

When a researcher ports an account from the Actor Workbench to a source list, and that account is linked to an Actor with `public_figure=True`, the system should:
1. Record the Actor UUID alongside the source list identifier (in a parallel JSONB structure or metadata)
2. At collection time, resolve `public_figure_ids` from both the ActorList chain AND the source list metadata
3. This ensures the GDPR bypass works regardless of which path configured the source

Proposed `arenas_config` extension for this:

```json
{
  "facebook": {
    "custom_pages": ["https://facebook.com/drnyheder"],
    "_actor_map": {
      "https://facebook.com/drnyheder": "actor-uuid-here"
    }
  }
}
```

The `_actor_map` is optional and only populated when the source was ported from the Actor Workbench. The orchestrator can use it to resolve public figure status without querying the full ActorList chain.

---

## 6. Arena-by-Arena Source List Requirements

### 6.1 Already Implemented (no changes needed)

| Arena | `arenas_config` key | Identifier format | Notes |
|-------|---------------------|-------------------|-------|
| RSS | `rss.custom_feeds` | Full feed URLs | Merges with 30+ Danish defaults |
| Telegram | `telegram.custom_channels` | Channel usernames (no `@`) or numeric IDs | Empty defaults list -- channels MUST be configured |
| Reddit | `reddit.custom_subreddits` | Subreddit names (no `r/`) | Merges with Danish subreddit defaults |
| Discord | `discord.custom_channel_ids` | Discord channel ID strings | Requires bot credentials with channel access |
| Wikipedia | `wikipedia.seed_articles` | Article titles | English Wikipedia assumed unless locale overrides |

### 6.2 Needs Implementation

| Arena | Proposed key | Identifier format | What the collector `collect_by_actors()` accepts | Priority |
|-------|--------------|-------------------|--------------------------------------------------|----------|
| Facebook | `facebook.custom_pages` | Full Facebook URLs | Full page/group/profile URLs (Bright Data API) | HIGH -- actor-only arena, currently requires Actor Directory |
| Instagram | `instagram.custom_profiles` | Full Instagram URLs | Full profile URLs (Bright Data API) | HIGH -- actor-only arena, same reason |
| Bluesky | `bluesky.custom_accounts` | Handles (`user.bsky.social`) or DIDs | Handles or DIDs | HIGH -- most active Danish platform among the missing ones |
| X/Twitter | `x_twitter.custom_accounts` | Usernames (no `@`) | User IDs or usernames depending on tier | MEDIUM -- 13% Danish usage, but politically important |
| YouTube | `youtube.custom_channels` | Channel IDs (`UC...`) or channel URLs | Channel IDs | MEDIUM -- video content, longer collection cycles |
| TikTok | `tiktok.custom_accounts` | Usernames (with or without `@`) | Usernames | LOW -- 19% Danish usage but engagement lag limits utility |
| Threads | `threads.custom_accounts` | Usernames | Usernames | LOW -- limited Danish adoption |
| Gab | `gab.custom_accounts` | Usernames | Usernames | LOW -- minimal Danish presence |
| Twitch | `twitch.custom_channels` | Channel names | Channel names | LOW -- niche use case |
| VKontakte | `vkontakte.custom_accounts` | User IDs or screen names | User IDs or screen names | LOW -- minimal Danish relevance |

### 6.3 Not Applicable

These arenas do not meaningfully support actor-based collection and should NOT get source lists:

| Arena | Reason |
|-------|--------|
| Google Search | Search engine -- actors map to `site:domain.com` syntax, not account lists |
| Google Autocomplete | Query-only -- no actor concept |
| GDELT | News aggregator -- sources are outlets, not individual accounts |
| Event Registry | Same as GDELT |
| Ritzau/Via | Wire service -- no public actor concept |
| AI Chat Search | Query-only |
| Majestic | SEO backlink tool -- domains, not accounts |
| Web arenas (Common Crawl, Wayback, Domain Crawler, URL Scraper) | URL-based, not account-based |

---

## 7. UI/UX Workflow Design

### 7.1 Query Design Editor: Extended Source Lists

**Location**: Existing `editor.html` template, below the five existing source list panels.

**Behavior**: Each new arena source list panel follows the exact same `arenaSourcePanel` Alpine.js component pattern used by RSS, Telegram, Reddit, Discord, and Wikipedia. The only differences are:
- `arena_name` parameter (e.g., `'facebook'`)
- `config_key` parameter (e.g., `'custom_pages'`)
- Placeholder text and help text
- Input validation (URL format for Facebook/Instagram, handle format for Bluesky, etc.)

**Panel ordering** (recommended): Group by priority and conceptual similarity:
1. RSS -- Custom Feeds (existing)
2. Telegram -- Custom Channels (existing)
3. Reddit -- Custom Subreddits (existing)
4. Facebook -- Custom Pages (NEW)
5. Instagram -- Custom Profiles (NEW)
6. Bluesky -- Custom Accounts (NEW)
7. X/Twitter -- Custom Accounts (NEW)
8. YouTube -- Custom Channels (NEW)
9. Discord -- Custom Channel IDs (existing)
10. TikTok -- Custom Accounts (NEW)
11. Wikipedia -- Seed Articles (existing)
12. Threads, Gab, Twitch, VKontakte (NEW, collapsed by default)

**Conditional rendering**: Only show a source list panel for an arena if:
- The arena is registered in the arena registry, AND
- The arena supports actor-based collection (`collect_by_actors()` does not raise `NotImplementedError`)

This can be determined by a new registry method that reports whether an arena supports actor-based collection, or by maintaining a static list.

### 7.2 Actor Workbench: Discovery and Staging

**Page redesign** at `/actors`:

Replace the current flat actor table with a tabbed interface:

**Tab 1: Discover**
- Snowball sampling configuration panel (seed selection, platform selection, depth, budget)
- "Seed from collection run" option (existing endpoint)
- Similarity discovery controls (platform recommendations, content similarity, cross-platform search)
- Corpus co-occurrence analysis launcher

**Tab 2: Staging**
- Working table of discovered accounts from the most recent discovery run
- Columns: Name, Platform, Discovery Method, Depth, Follower Count, Status (new/reviewed/accepted/rejected)
- Bulk selection checkboxes
- "Port to Project" action: opens a modal to select target query design and target arena(s)
- "Port All" bulk action

**Tab 3: Registry** (existing functionality, retained)
- Full actor directory table with search
- Actor CRUD
- Entity resolution link
- This tab serves the canonical identity management function

**Tab 4: Entity Resolution** (existing, retained)
- Cross-platform matching candidates
- Merge/split tools

### 7.3 The "Port to Project" Flow

This is the critical new interaction connecting System B to System A.

**Trigger**: User clicks "Port to Project" button on one or more staged actors.

**Step 1: Select Target**
- Modal shows the user's query designs (filtered by `is_active=True`)
- User selects a query design

**Step 2: Map Accounts to Arenas**
- For each selected account, show which arena(s) it could be ported to (based on platform)
- Example: A Bluesky account `politiken.bsky.social` can be ported to the Bluesky source list
- Example: An Actor with presences on both Facebook and Instagram shows both options
- User can deselect specific arenas per account

**Step 3: Confirm and Execute**
- Summary: "Add 5 accounts to Query Design 'Danish Climate Debate'"
  - 2 accounts to `bluesky.custom_accounts`
  - 2 accounts to `facebook.custom_pages`
  - 1 account to `x_twitter.custom_accounts`
- "Confirm" button

**Step 4: Execution**
- For each arena, call `PATCH /query-designs/{id}/arena-config/{arena_name}` with the updated list (existing endpoint, no new API needed)
- The PATCH endpoint already deep-merges into the existing arenas_config
- For the `_actor_map` metadata (public figure bridge), include the Actor UUID mapping

**Step 5: Feedback**
- Success message with count of accounts ported per arena
- Link to the query design editor to verify

### 7.4 Backward Compatibility in UI

The existing Actor Directory page routes (`/actors`, `/actors/{id}`, `/actors/resolution`) remain at the same URLs. The visual redesign changes the page layout but not the URL structure. All existing API endpoints continue to work.

---

## 8. Migration Path

### Phase 0: Preparation (no user-visible changes)

1. Add a `supports_actor_collection` class attribute to `ArenaCollector` base class (default `True` for arenas that implement `collect_by_actors()` without raising `NotImplementedError`, `False` for those that do raise it). Alternatively, add a registry helper that reports this.
2. Add a `source_list_config_key` class attribute to each arena collector specifying the `arenas_config` key name (e.g., `"custom_pages"` for Facebook).

### Phase 1: Source Lists for Actor-Only Arenas (HIGH priority)

1. Add `arenaSourcePanel` instances for Facebook and Instagram in the query design editor template.
2. Modify `dispatch_batch_collection()` to check `arenas_config[platform_name].custom_{type}` BEFORE falling back to `fetch_actor_ids_for_design_and_platform()`.
3. The existing `facebook/tasks.py` and `instagram/tasks.py` already accept `actor_ids` as a parameter -- no task changes needed, only the orchestrator dispatch logic.

**Migration for existing data**: Any actors currently configured via ActorList for Facebook/Instagram continue to work via the existing fallback. No data migration is needed.

### Phase 2: Source Lists for Dual-Mode Arenas (MEDIUM priority)

1. Add `arenaSourcePanel` instances for Bluesky, X/Twitter, YouTube in the query design editor.
2. Modify `dispatch_batch_collection()` to ALSO dispatch `collect_by_actors()` for dual-mode arenas when a source list is configured, in addition to the existing `collect_by_terms()` dispatch.
3. Each arena's Celery task file already has both `collect_by_terms` and `collect_by_actors` tasks. The orchestrator just needs to dispatch both when both inputs are available.

### Phase 3: Actor Workbench Redesign (MEDIUM priority)

1. Redesign the `/actors` template with tabbed interface.
2. Implement the "Port to Project" modal and API flow.
3. Add staging status tracking (either in-memory via Alpine.js state, or persisted in Actor `metadata_` JSONB).

### Phase 4: Low-Priority Arenas + Polish (LOW priority)

1. Add source list panels for TikTok, Threads, Gab, Twitch, VKontakte.
2. Implement the public figure bridge (`_actor_map` in arenas_config).
3. Usability improvements based on researcher feedback.

---

## 9. Risks and Tradeoffs

### 9.1 Duplication Between Source Lists and Actor Records

**Risk**: A researcher might configure `facebook.custom_pages: ["https://facebook.com/drnyheder"]` in the source list AND have an Actor record for "DR Nyheder" with a Facebook platform presence. The orchestrator could try to collect the same account twice.

**Mitigation**: The orchestrator should deduplicate actor_ids before dispatching. When both sources are present, merge them into a single deduplicated list. The existing `_build_channel_list()` pattern in `telegram/collector.py` already does this.

### 9.2 GDPR Public Figure Bypass

**Risk**: The `public_figure` flag lives on the Actor model. If a researcher adds an account via the source list (which is a simple string, not linked to an Actor), the GDPR bypass cannot be applied.

**Mitigation**: The `_actor_map` bridge proposed in Section 5.4 addresses this. Additionally, for the common case where a researcher first creates an Actor in the registry and then uses it in a source list, the orchestrator can look up the Actor by platform presence to check `public_figure`. This lookup is already implemented in `fetch_actor_ids_for_design_and_platform()` and can be extended to work in reverse (given a platform identifier, find the Actor).

### 9.3 Validator Complexity

**Risk**: Each arena needs platform-specific input validation in the source list UI (URL format for Facebook, handle format for Bluesky, channel ID format for YouTube, etc.).

**Mitigation**: Keep validation lightweight in the UI (basic format checks) and let the collector handle full validation at runtime. The collector already handles invalid identifiers gracefully (e.g., `_record_skipped_actor()` pattern in the base class).

### 9.4 Collector Signature Changes

**Risk**: Some collectors' `collect_by_terms()` methods already accept a custom source list parameter (e.g., `extra_channel_ids` for Telegram, `extra_feed_urls` for RSS), but the orchestrator does not uniformly pass these.

**Mitigation**: Rather than changing every collector signature, have the orchestrator read the source list from `arenas_config` and:
- For actor-only arenas: pass it as `actor_ids` to `collect_by_actors()` (already works)
- For dual-mode arenas: dispatch a SEPARATE `collect_by_actors()` task alongside the `collect_by_terms()` task
- For arenas with existing custom parameters (Telegram, RSS): pass via `**_extra` kwargs that the task already reads from `arenas_config` internally (no change needed)

### 9.5 Source List Scalability

**Risk**: JSONB arrays work well for lists of 10-100 items. If a researcher adds thousands of accounts (e.g., from an aggressive snowball sampling run), the JSONB payload becomes large and the PATCH semantics (replace entire array) become costly.

**Mitigation**: For the foreseeable research use cases (tracking dozens to low hundreds of accounts per arena per project), JSONB arrays are adequate. If scalability becomes an issue, a future phase could migrate to a relational `arena_source_list_items` table. But this is premature optimization for now.

---

## 10. Implementation Phases

### Phase 1: Actor-Only Arena Source Lists (Estimated: 2-3 days)
**Priority**: HIGH
**Blocks**: Nothing -- can start immediately
**Delivers**: Facebook and Instagram configurable in query design editor

Tasks:
1. Add `arenaSourcePanel` for Facebook in `editor.html` (1 hour)
2. Add `arenaSourcePanel` for Instagram in `editor.html` (1 hour)
3. Modify `dispatch_batch_collection()` in `workers/tasks.py` to check `arenas_config[platform].custom_{key}` before falling through to `fetch_actor_ids_for_design_and_platform()` (2-3 hours)
4. Add input validation helpers for Facebook URL format and Instagram URL format (1 hour)
5. Test: verify Facebook/Instagram collection works with source list-configured accounts (2-3 hours)
6. Update arena research briefs for Facebook and Instagram (1 hour)

### Phase 2: Dual-Mode Arena Source Lists (Estimated: 3-4 days)
**Priority**: HIGH
**Depends on**: Phase 1 (for the orchestrator pattern)
**Delivers**: Bluesky, X/Twitter, YouTube configurable in query design editor

Tasks:
1. Add `arenaSourcePanel` instances for Bluesky, X/Twitter, YouTube in `editor.html` (2 hours)
2. Extend orchestrator to dispatch `collect_by_actors()` alongside `collect_by_terms()` for dual-mode arenas when a source list is present (3-4 hours)
3. Ensure deduplication between source-list-driven and term-driven collection results (2 hours)
4. Test each arena's actor-based collection via source list (3-4 hours)
5. Update arena research briefs (2 hours)

### Phase 3: Actor Workbench Redesign (Estimated: 4-5 days)
**Priority**: MEDIUM
**Depends on**: Phase 1 and Phase 2 (so the "port to project" target exists)
**Delivers**: Redesigned Actor Directory with discover/stage/port workflow

Tasks:
1. Redesign `actors/list.html` with tabbed layout (Discover / Staging / Registry / Resolution) (4-6 hours)
2. Implement "Port to Project" modal with query design selection and arena mapping (4-6 hours)
3. Implement backend for "Port to Project" (calls existing PATCH arena-config endpoint, no new API needed) (2-3 hours)
4. Add staging status tracking in the discovery results table (2-3 hours)
5. Wire up existing snowball/similarity/co-occurrence endpoints to the Discover tab (3-4 hours)
6. Test end-to-end: discover -> stage -> port -> collect (3-4 hours)

### Phase 4: Low-Priority Arenas + Polish (Estimated: 2-3 days)
**Priority**: LOW
**Depends on**: Phase 2
**Delivers**: Full arena coverage + public figure bridge

Tasks:
1. Add source list panels for TikTok, Threads, Gab, Twitch, VKontakte (3 hours)
2. Implement `_actor_map` public figure bridge in arenas_config (3-4 hours)
3. Extend orchestrator to resolve `public_figure_ids` from both ActorList chain and `_actor_map` (2-3 hours)
4. Polish: empty-state messaging, help text, input examples per arena (2 hours)
5. Update all affected arena research briefs and IMPLEMENTATION_PLAN.md (2 hours)

---

## Appendix A: Files Affected

### Files to Modify

| File | Changes |
|------|---------|
| `src/issue_observatory/api/templates/query_designs/editor.html` | Add source list panels for new arenas |
| `src/issue_observatory/workers/tasks.py` | Modify `dispatch_batch_collection()` to read source lists from arenas_config |
| `src/issue_observatory/workers/_task_helpers.py` | Add helper to read arena source lists from arenas_config |
| `src/issue_observatory/api/templates/actors/list.html` | Redesign with tabbed layout |
| `src/issue_observatory/api/routes/actors.py` | Add "port to project" endpoint |
| `src/issue_observatory/arenas/base.py` | Add `supports_actor_collection` and `source_list_config_key` class attributes |

### Files That Remain Unchanged

| File | Reason |
|------|--------|
| `src/issue_observatory/core/models/actors.py` | No schema changes |
| `src/issue_observatory/core/models/query_design.py` | No schema changes -- uses existing `arenas_config` JSONB |
| `src/issue_observatory/arenas/*/collector.py` | Collector interfaces remain the same |
| `src/issue_observatory/arenas/*/tasks.py` | Tasks already accept the right parameters |
| `src/issue_observatory/api/routes/query_designs.py` | PATCH arena-config endpoint already supports arbitrary keys |
| `src/issue_observatory/sampling/*.py` | Snowball/network/similarity modules remain unchanged |
| `src/issue_observatory/core/entity_resolver.py` | Entity resolution unchanged |
| `alembic/versions/*` | No new migrations needed |

### New Files (if any)

None anticipated. All changes fit within existing files and patterns.

---

## Appendix B: `arenaSourcePanel` Component Reference

The existing Alpine.js component `arenaSourcePanel` (defined inline in `editor.html`, approximately line 2460+) accepts these parameters and handles all CRUD operations:

```javascript
arenaSourcePanel(designId, arenaName, configKey, initialItems)
```

- `designId`: UUID string of the query design
- `arenaName`: Arena identifier for the PATCH endpoint URL path
- `configKey`: The JSONB key name within the arena's config object
- `initialItems`: JavaScript array of initial string values from server-rendered Jinja2

The component:
1. Renders an add input + existing items list
2. On add/remove, calls `PATCH /api/query-designs/{designId}/arena-config/{arenaName}` with `{configKey: updatedArray}`
3. Shows save/error feedback

To add a new source list panel, only the template HTML block needs to be added. No JavaScript component code changes are needed because the component is fully generic and parameterized.

---

## Appendix C: Orchestrator Dispatch Logic (Proposed)

Current dispatch logic in `dispatch_batch_collection()` (simplified):

```
for each arena:
    if arena is actor-only:
        actor_ids = fetch_actor_ids_for_design_and_platform(design, platform)
        dispatch collect_by_actors(actor_ids)
    else:
        terms = fetch_resolved_terms_for_arena(design, platform)
        dispatch collect_by_terms(terms)
```

Proposed dispatch logic:

```
for each arena:
    # Step 1: Read source list from arenas_config (NEW)
    source_list = read_source_list_from_arenas_config(arenas_config, platform)

    if arena is actor-only:
        # Merge source list with legacy ActorList chain
        actor_ids_legacy = fetch_actor_ids_for_design_and_platform(design, platform)
        actor_ids = deduplicate(source_list + actor_ids_legacy)
        if not actor_ids:
            mark_task_failed("No actors configured")
            continue
        dispatch collect_by_actors(actor_ids)

    else:  # dual-mode arena
        # Always dispatch terms if available
        terms = fetch_resolved_terms_for_arena(design, platform)
        if terms:
            dispatch collect_by_terms(terms)

        # Also dispatch actors if source list is configured (NEW)
        if source_list:
            dispatch collect_by_actors(source_list)
```

This is backward-compatible: existing configurations without source lists work exactly as before. Source lists are purely additive.
