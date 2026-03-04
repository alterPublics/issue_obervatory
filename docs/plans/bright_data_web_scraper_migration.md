# Implementation Plan: Bright Data Web Scraper API Migration

**Created:** 2026-02-26
**Updated:** 2026-02-26
**Status:** Draft -- pending approval
**Scope:** Migrate Facebook and Instagram collectors from Bright Data Datasets product to Web Scraper API; remove keyword-based collection for these arenas

---

## 1. Problem Statement

The Facebook and Instagram collectors currently use the **Bright Data Datasets product** (pre-collected data snapshots) rather than the **Web Scraper API** (on-demand, real-time collection). This causes several issues:

1. **Stale dataset IDs**: The hardcoded Facebook dataset ID (`gd_l95fol7l1ru6rlo116`) does not match any currently listed Bright Data product. The Instagram collector uses the Reels dataset ID (`gd_lyclm20il4r5helnj`) for all Instagram content.
2. **Wrong product model**: Datasets are pre-collected snapshots refreshed monthly -- not suitable for live tracking or on-demand research collection.
3. **Higher cost**: Datasets cost ~$2.50/1K records; the Web Scraper API costs ~$1.00-$1.50/1K records (pay-as-you-go).
4. **Limited content types**: Both collectors route all requests through a single dataset ID. The Web Scraper API offers separate scrapers for Posts, Comments, Reels, Groups (Facebook) and Posts, Reels, Profiles, Comments (Instagram).

---

## 2. Confirmed: No Keyword Discovery

**Tested 2026-02-26.** The Bright Data Web Scraper API does **not** support keyword-based discovery for Facebook or Instagram. Every scraper was tested with `type=discover_new&discover_by=keyword` and all returned errors:

| Scraper | Dataset ID | Supported discovery types | Keyword? |
|---------|-----------|--------------------------|----------|
| Facebook Posts | `gd_lkaxegm826bjpoo9m5` | `user_name` | No |
| Facebook Reels | `gd_lyclm3ey2q6rww027t` | `url_collection` | No |
| Facebook Groups | `gd_lz11l67o2cb3r0lkj3` | `url_collection` | No |
| Instagram Posts | `gd_lk5ns7kz21pck8jpis` | `url` | No |
| Instagram Reels | `gd_lyclm20il4r5helnj` | `url`, `url_all_reels` | No |

**Consequence:** `collect_by_terms()` must be **removed** from both the Facebook and Instagram collectors. These arenas will operate as **actor-only** collection platforms, relying on:

- Manually added actors (researcher-curated Facebook pages, groups, Instagram profiles)
- Actors discovered through snowball sampling and cross-platform actor matching
- One-click actor addition from the content browser (GR-17)

This is consistent with how these platforms actually work -- Facebook and Instagram have no public keyword search API. Any prior keyword-based collection was routed through Bright Data's pre-collected dataset product, which is no longer viable.

---

## 3. Target Architecture

### Web Scraper API Overview

The Web Scraper API uses the **same base URL** (`https://api.brightdata.com/datasets/v3`) and the **same async workflow** (trigger -> poll -> download) as the Datasets product. The key differences are:

- **Different dataset IDs** per content type
- **URL-based input only** (profile URLs, page URLs, group URLs)
- **Fresh data** collected on demand, not pre-collected snapshots
- **Date format**: `MM-DD-YYYY` (not `YYYY-MM-DD`)
- **Cheaper**: ~$1.50/1K records (pay-as-you-go) vs ~$2.50/1K (Datasets)

### Dataset IDs

**Facebook (Web Scraper API):**

| Scraper | Dataset ID | Input | Use Case |
|---------|-----------|-------|----------|
| Posts | `gd_lkaxegm826bjpoo9m5` | Profile/Group/Page URL | Primary: page/profile post collection |
| Groups | `gd_lz11l67o2cb3r0lkj3` | Group URL | Group post collection |
| Reels | `gd_lyclm3ey2q6rww027t` | Profile URL | Reel-specific collection |
| Comments | `gd_lkay758p1eanlolqw8` | Post URL | Future: comment collection |
| Events | `gd_m14sd0to1jz48ppm51` | Event URL | Future: event metadata |
| Marketplace | `gd_lvt9iwuh6fbcwmx1a` | Listing URL or keyword | Not relevant for research |

**Instagram (Web Scraper API):**

| Scraper | Dataset ID | Input | Use Case |
|---------|-----------|-------|----------|
| Posts | `gd_lk5ns7kz21pck8jpis` | Post URL | Individual post scraping |
| Reels | `gd_lyclm20il4r5helnj` | Profile URL | Primary: profile reel/post collection |
| Comments | `gd_ltppn085pokosxh13` | Post URL | Future: comment collection |
| Profiles | `gd_l1vikfch901nx3by4` | Profile URL | Profile metadata |

### Input Format

**Current (Datasets product -- Facebook):**
```json
{
  "filters": [
    {"type": "keyword", "value": "klimaforandring"},
    {"type": "country", "value": "DK"}
  ],
  "limit": 1000
}
```

**New (Web Scraper API -- by actors):**
```json
[
  {"url": "https://www.facebook.com/drnyheder", "num_of_posts": 100, "start_date": "01-01-2026", "end_date": "02-26-2026"}
]
```

---

## 4. Implementation Steps

### Phase 1: Remove collect_by_terms()

**Files:** `facebook/collector.py`, `instagram/collector.py`, `facebook/tasks.py`, `instagram/tasks.py`

The `collect_by_terms()` method on both collectors currently builds keyword filter payloads for the Datasets product. Since the Web Scraper API does not support keyword discovery, this method must be disabled:

1. Override `collect_by_terms()` to raise a clear `ArenaCollectionError` explaining that Facebook/Instagram do not support keyword search and that actors (page/profile URLs) must be used instead
2. Remove the Celery tasks `facebook_collect_terms` and `instagram_collect_terms` (or have them immediately fail with a descriptive error)
3. Update the arena registry metadata to indicate these arenas do not support term-based collection

### Phase 2: Config Updates

**Files:** `facebook/config.py`, `instagram/config.py`

1. Replace single dataset IDs with a mapping of content type -> dataset ID:
   - Facebook: Posts (`gd_lkaxegm826bjpoo9m5`), Groups (`gd_lz11l67o2cb3r0lkj3`), Reels (`gd_lyclm3ey2q6rww027t`)
   - Instagram: Reels (`gd_lyclm20il4r5helnj`), Posts (`gd_lk5ns7kz21pck8jpis`)
2. Update date format helper to output `MM-DD-YYYY`
3. Update cost constants to reflect Web Scraper API pricing ($1.50/1K pay-as-you-go)
4. Remove `type=discover_new` and `&notify=none` from trigger URL templates
5. Add new output field mappings for the Web Scraper API response schema

### Phase 3: Refactor collect_by_actors()

**Files:** `facebook/collector.py`, `instagram/collector.py`

1. Update `collect_by_actors()` to build Web Scraper API payload format:
   ```json
   [{"url": "https://www.facebook.com/pagename", "num_of_posts": 100, "start_date": "MM-DD-YYYY", "end_date": "MM-DD-YYYY"}]
   ```
2. Route to the correct dataset ID based on input type:
   - Facebook page/profile URL -> Posts scraper
   - Facebook group URL -> Groups scraper
   - Instagram profile URL -> Reels scraper (covers both posts and reels)
3. Update trigger URL construction (remove `type=discover_new` parameters)
4. Keep the existing poll -> download workflow (identical endpoints)
5. Accept actor IDs as Facebook/Instagram page URLs or profile URLs (not opaque IDs)

### Phase 4: Normalization Updates

**Files:** `facebook/collector.py`, `instagram/collector.py`

Update `_parse_brightdata_post()` / `_parse_brightdata_item()` for the new response fields:

**Facebook field mapping changes:**

| Current field | Web Scraper API field |
|---------------|----------------------|
| `post_id` | `post_id` (same) |
| `message` / `description` | `content` |
| `page_id` | `user_url` (URL, not ID) |
| `page_name` | `page_name` (same) |
| `created_time` / `date` | `date_posted` |
| `reactions.total` | `num_likes` |
| `shares` | (not in basic output) |
| `comments` | `num_comments` |
| `images` | `attachments`, `post_image` |
| `views` | `video_view_count` |

**Instagram field mapping changes:**

| Current field | Web Scraper API field |
|---------------|----------------------|
| `id` / `shortcode` | (construct from `url`) |
| `caption` / `text` | `description` |
| `owner_username` | `user_posted` |
| `likes_count` | `likes` |
| `comments_count` | `num_comments` |
| `video_view_count` | `video_view_count` / `video_play_count` |
| `timestamp` / `created_at` | `date_posted` |
| `hashtags` | `hashtags` (same) |

### Phase 5: Frontend Updates

**Files:** `templates/collections/launcher.html`, `templates/arenas/index.html`, `static/js/app.js`

1. Update the collection launcher to clearly indicate that Facebook and Instagram only support actor-based collection (no term search)
2. Show guidance in the arena config grid: "Add Facebook pages/groups or Instagram profiles in the Actor Directory to collect from these arenas"
3. Disable/hide the "by terms" collection option when only Facebook/Instagram arenas are selected
4. Update the arena overview page descriptions

### Phase 6: Credit Estimation Updates

**Files:** `facebook/collector.py`, `instagram/collector.py`

1. Update cost-per-record constants:
   - Facebook: $0.0025 -> $0.0015 per record
   - Instagram: keep at $0.0015 per record
2. Update `estimate_credits()` to only estimate for actor-based collection (no term-based heuristic needed)

### Phase 7: Test Updates

**Files:** `tests/arenas/test_facebook.py`, `tests/arenas/test_instagram.py`, `tests/fixtures/api_responses/facebook/`, `tests/fixtures/api_responses/instagram/`

1. Remove or update tests for `collect_by_terms()` (should now raise `ArenaCollectionError`)
2. Update `collect_by_actors()` mock payloads to match new URL-based format
3. Update mock response fixtures with Web Scraper API field names
4. Add tests for dataset ID routing (Posts vs Groups vs Reels)
5. Test date format conversion (`MM-DD-YYYY`)
6. Add test for the clear error message when `collect_by_terms()` is called

---

## 5. Files Affected

| File | Change Type | Description |
|------|-------------|-------------|
| `arenas/facebook/config.py` | Modify | Dataset ID mapping, cost constants, date format, remove discover_new |
| `arenas/facebook/collector.py` | Modify | Remove collect_by_terms, refactor collect_by_actors, update normalization |
| `arenas/facebook/tasks.py` | Modify | Remove or disable collect_terms task |
| `arenas/instagram/config.py` | Modify | Dataset ID mapping, cost constants, date format |
| `arenas/instagram/collector.py` | Modify | Remove collect_by_terms, refactor collect_by_actors, update normalization |
| `arenas/instagram/tasks.py` | Modify | Remove or disable collect_terms task |
| `api/templates/collections/launcher.html` | Modify | Actor-only guidance for FB/IG |
| `api/templates/arenas/index.html` | Modify | Update arena descriptions |
| `tests/arenas/test_facebook.py` | Modify | Update mocks and assertions |
| `tests/arenas/test_instagram.py` | Modify | Update mocks and assertions |
| `tests/fixtures/api_responses/facebook/` | Modify | New response format fixtures |
| `tests/fixtures/api_responses/instagram/` | Modify | New response format fixtures |
| `docs/guides/credential_acquisition_guide.md` | Already updated | Web Scraper API instructions |
| `docs/release_notes/release_notes_2026_02_26.md` | Already updated | Documents this migration |

**No database migration needed** -- the credential structure (`api_token`) is the same. The same Bright Data API token works for the Web Scraper API.

---

## 6. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Dataset IDs change without notice | Collection fails | Log dataset ID in error messages; make IDs configurable in config.py for easy updates |
| Web Scraper API response schema differs from documented | Normalization breaks | Build normalization defensively with `.get()` and fallback chains |
| Date format mismatch (`MM-DD-YYYY` vs ISO) | Wrong date filtering | Centralize date formatting in a helper function |
| Instagram media links expire after 24 hours | Broken URLs in stored records | Document this limitation; store metadata about expiration |
| Researchers expect keyword search on FB/IG | Confusion | Clear UI messaging explaining actor-only collection; link to Actor Directory |
| Actor URLs may be in different formats | Wrong dataset ID selected | Normalize URLs and detect page vs group vs profile patterns |

---

## 7. Research Workflow Impact

### Before (current, broken)

Researchers could (in theory) search Facebook/Instagram by keyword via Bright Data Datasets. In practice this relied on stale dataset IDs and pre-collected snapshots.

### After (proposed)

Facebook and Instagram become **actor-driven arenas**. The research workflow is:

1. **Curate actors**: Researcher adds Facebook pages/groups and Instagram profiles to the Actor Directory (manually or via bulk import)
2. **Collect**: `collect_by_actors()` fetches recent posts from those pages/profiles
3. **Discover more actors**: Snowball sampling, cross-platform actor matching, and the Discovered Sources panel surface new pages/profiles
4. **Iterate**: Researcher adds newly discovered actors and re-collects

This aligns with how other arenas already work (Discord requires channel IDs, Telegram requires channel usernames). Facebook and Instagram join the set of **source-list arenas** where the researcher curates the input sources.

### Arenas Supporting Term-Based Collection (unchanged)

The following arenas continue to support `collect_by_terms()`:
- Google Search, Google Autocomplete
- Bluesky, Reddit, YouTube
- RSS Feeds, GDELT, Event Registry
- X/Twitter, Gab, Threads
- Via Ritzau, Common Crawl, Wayback Machine
- AI Chat Search, Wikipedia

---

## 8. Open Questions

1. **Should we support multiple content types per collection run?** E.g., fetch both Posts and Reels from a Facebook page in a single `collect_by_actors()` call, or keep them as separate scraper selections.
2. **Facebook Groups URL detection**: Should the collector auto-detect group URLs (containing `/groups/`) and route to the Groups dataset ID, or should the researcher explicitly tag actors as "group" vs "page"?
3. **Instagram: Posts vs Reels scraper**: The Reels scraper (`gd_lyclm20il4r5helnj`) accepts profile URLs and may return all content types. Should we default to this, or use the Posts scraper (`gd_lk5ns7kz21pck8jpis`) which requires individual post URLs?
