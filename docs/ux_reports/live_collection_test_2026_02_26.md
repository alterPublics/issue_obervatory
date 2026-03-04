# Live Collection Test Report -- All Arenas
Date: 2026-02-26/27
Tester: UX Test Agent (researcher perspective)
Project: greenland_v1
Query Design: greenland_base (ID: 58784edf-0d8f-4c54-b8a7-e6d2f69aed94)
Search terms: "gronland", "Inatsisartut", "nuuk", "#gronland" (TikTok override)
Date range: 2026-02-19 to 2026-02-26 (one week)
Collection mode: batch

---

## Executive Summary

Out of 25 registered arenas, **10 collected data successfully**, **10 failed with errors**, and **5 became stuck in pending/running state** with no Celery task processing them. A total of **1,442 content records** were collected across three collection runs. The data quality is generally good for platforms that succeeded -- content is relevant to the Greenland search terms, Danish-language filtering works on most platforms, and timestamps are plausible. However, several critical issues surfaced:

1. **Four platforms (Reddit, Wikipedia, GDELT, Google Autocomplete) do not populate `search_terms_matched`**, making 670 collected records (46% of total) invisible in the default content browser view. A researcher would see "100 records collected" on the collection detail page but find nothing when browsing content.
2. **Five arena tasks became permanently stuck** (openrouter, vkontakte, url_scraper stuck at "pending"; telegram and twitch stuck at "running") with no Celery worker processing them, preventing collection runs from ever reaching "completed" status.
3. **Tier misconfiguration is easy and unrecoverable per-run**: the query design defaulted all arenas to "premium" tier, but only medium-tier credentials were configured for Google Search, Google Autocomplete, and X/Twitter. Three separate collection runs were needed to discover this.

---

## Test Setup

### Actors Added to Query Design (14 actors, 14 platform presences)

| Platform | Actor | Presence |
|----------|-------|----------|
| Facebook | Facebook Page 57497067718 | platform_user_id: 57497067718 |
| Facebook | Facebook Page 520449347983427 | platform_user_id: 520449347983427 |
| Instagram | Enhedslisten Instagram | username: enhedslisten |
| Reddit | r/Denmark | username: Denmark |
| Telegram | Frihedslisten Telegram | username: Frihedslisten |
| Telegram | Flemming Blicher Telegram | username: flemmingblicher |
| X/Twitter | MBrgger X | username: MBrgger |
| X/Twitter | Pelle Dragsted X | username: pelledragsted |
| Bluesky | Socialdemokratiet Bluesky | username: socialdemokratiet.dk |
| YouTube | YouTube Channel UC5Ryu8RV7pYi8JnXsy8DkqQ | channel_id |
| YouTube | YouTube Channel UCc3XOJeHmoq3pePvlsomGaA | channel_id |
| TikTok | SF Politik TikTok | username: sfpolitik |
| TikTok | TV2 Echo TikTok | username: tv2echo |
| Discord | r/Denmark Discord | username: r/Denmark |

### Collection Runs Launched

| Run | Config | Purpose |
|-----|--------|---------|
| Run 1 (7329380a) | All 25 arenas, tier=premium | Main collection |
| Run 2 (963d7122) | All 25 arenas, tier=premium (QD unchanged) | Duplicate of Run 1 (launched before QD config could be changed) |
| Run 3 (44403410) | 6 arenas at medium tier (google_search, google_autocomplete, x_twitter, facebook, instagram, openrouter) | Retry with correct tier |

---

## Results by Arena

### Arenas That Collected Data Successfully

| Arena | Platform | Records | Lang Distribution | Data Quality Notes |
|-------|----------|---------|-------------------|--------------------|
| Bluesky | bluesky | 154 | All `da` | Good. `lang:da` filter working. Real Danish political discourse. Pseudonymization active. |
| YouTube | youtube | 274 | 160 da, 114 non-da | Mixed languages. Many English/Hindi/other videos mentioning "Greenland" or "Nuuk". Danish relevance filter not strict enough. Pseudonymization active. |
| Reddit | reddit | 100 | All empty (`""`) | Relevant content from r/Denmark. **Language field empty for all records.** **`search_terms_matched` empty for all records** -- invisible in default content browser. Pseudonymization active. |
| TikTok | tiktok | 46 | 45 da, 1 other | Good. Danish content. Engagement scores present (7-21 range, normalized). Pseudonymization active. |
| Wikipedia | wikipedia | 505 | All empty or `""` | High volume but content is revision metadata, not article text. **`search_terms_matched` empty for all 505 records.** **No pseudonymization.** No language field. |
| GDELT | gdelt | 25 | All `da` | Good. Danish news articles from DR, Computerworld, Alt.dk. **`search_terms_matched` empty for all records.** **No pseudonymization.** |
| Google Search | google_search | 255 | 234 da, 21 non-da | Good. Relevant search results with Danish locale (gl=dk, hl=da). 21 duplicate content hashes (same page across multiple search terms). **No pseudonymization** (expected -- search results have URLs, not authors). |
| Google Autocomplete | google_autocomplete | 40 | N/A | Good. Autocomplete suggestions for each search term. **`search_terms_matched` empty for all records** -- invisible in browser. **No pseudonymization.** |
| Ritzau Via | ritzau_via | 39 | All `da` | Good. Press releases. Pseudonymization active. Relevant content (Gronlandsbanken, political content). |
| RSS Feeds | rss_feeds | 4 | All `da` | **Very low yield**: only 4 articles (2 DR, 2 TV2) for a week of Greenland coverage across 28+ feeds. Expected much more given the topic's prominence. RSS is `forward_only` temporal mode, so it only captures current feed content, not historical. |

### Arenas That Failed

| Arena | Error | Root Cause | Severity |
|-------|-------|------------|----------|
| Google Search (Run 1) | `No credential available for platform 'serpapi' at tier 'premium'` | QD set tier=premium but only SERPER_API_KEY (medium) is configured. SERPAPI_API_KEY is blank in .env. | **Config error** -- resolved by launching Run 3 with medium tier |
| Google Autocomplete (Run 1) | Same as above | Same credential/tier mismatch | Config error |
| X/Twitter (Run 1) | `No credential available for platform 'x_twitter' at tier 'premium'` | QD set premium but only TWITTERAPIIO_API_KEY (medium) exists | Config error |
| X/Twitter (Run 3) | `TwitterAPI.io HTTP 405` | Medium-tier credential is present but the API returned HTTP 405 Method Not Allowed. Possible API endpoint change or invalid request format. | **API failure** -- needs investigation |
| Facebook | `Facebook does not support keyword-based collection` | Facebook is actor-only (Bright Data). The collection dispatch tried keyword search but this platform only supports collect_by_actors. | **Design gap** -- no separate actor-based collection dispatch |
| Instagram | `Instagram does not support keyword-based or hashtag-based collection` | Same as Facebook -- actor-only platform. | Same design gap |
| Discord | `Discord requires explicit channel_ids` | Discord bot cannot search globally; needs channel snowflake IDs in arenas_config. The actor "r/Denmark Discord" was added but the platform needs channel IDs, not a named actor. | **Config gap** -- researcher guidance needed |
| Gab | `No credential available for platform 'gab' at tier 'free'` | GAB_ACCESS_TOKEN is blank in .env | Missing credential |
| Event Registry | `No credential available for platform 'event_registry' at tier 'premium'` | EVENT_REGISTRY_API_KEY is blank in .env | Missing credential |
| Majestic | `No credential available for platform 'majestic' at tier 'premium'` | MAJESTIC_API_KEY is blank in .env | Missing credential |
| Common Crawl | `Server disconnected without sending a response` | Common Crawl index server connectivity issue | **Transient failure** -- retry should work |

### Arenas Stuck (Never Completed)

| Arena | Status | Duration Stuck | Notes |
|-------|--------|---------------|-------|
| OpenRouter | pending | 30+ minutes | Celery task never dispatched or dispatched but lost. No active/reserved tasks in Celery inspect. |
| VKontakte | pending | 30+ minutes | Same as OpenRouter. VK credentials are present in .env but the platform is a deferred stub. |
| URL Scraper | pending | 30+ minutes | URL Scraper requires researcher-provided URLs. No URLs were provided, but the task should fail gracefully rather than hang. |
| Telegram | running | 30+ minutes | Task started but never completed. Telethon MTProto session may have stalled. No records collected. |
| Twitch | running | 30+ minutes | Task started but never completed. Twitch is listed as a "deferred stub" so it should not accept collection at all. |

### Arenas Not Tested (No Credentials / Stubs)

| Arena | Reason |
|-------|--------|
| Threads | No THREADS_ACCESS_TOKEN. Completed with 0 records (no error). |
| Wayback Machine | Completed with 0 records. Expected for a week-old topic (Wayback archives are much older). |

---

## Critical Findings

### BLOCKER-1: search_terms_matched Not Populated for 4 Platforms [core] [data]

**What happens**: Reddit, Wikipedia, GDELT, and Google Autocomplete collectors do not set the `search_terms_matched` field on content records.

**Research impact**: The content browser's default view filters to records that have at least one matched search term. Records without this field are invisible. A researcher sees "100 records collected" for Reddit on the collection detail page, then navigates to the content browser and finds zero Reddit results. This is a fundamental trust violation -- the system claims to have data but the researcher cannot access it.

**Affected records**: 670 out of 1,442 (46%).

**Platforms affected**:
- Reddit: 100 records (all without terms)
- Wikipedia: 505 records (all without terms)
- GDELT: 25 records (all without terms)
- Google Autocomplete: 40 records (all without terms)

**UX note**: The `show_all=true` parameter exists to reveal these records, but a researcher would never know to use it unless told. The content browser UI should either default to showing all records or prominently display a count of "hidden records that lack term matching."

### BLOCKER-2: Arena Tasks Stuck in Pending/Running State [core]

**What happens**: Five arena tasks (openrouter, vkontakte, url_scraper, telegram, twitch) become permanently stuck, preventing the collection run from ever reaching "completed" status. Celery worker inspection shows no active, reserved, or scheduled tasks -- the tasks are simply lost.

**Research impact**: The collection run stays in "running" status indefinitely. The researcher has no way to know the run is effectively done. There is no timeout mechanism, no "mark as stale" button, and no guidance on what to do with a run that appears to be hanging.

**Suspected causes**:
- OpenRouter: Celery task may not have been dispatched (queuing issue or race condition).
- VKontakte/Twitch: These are deferred stubs that should not accept collection tasks at all, but the dispatcher created tasks for them anyway.
- Telegram: MTProto session string may have expired or the connection stalled without a timeout.
- URL Scraper: No URLs were provided, so the task should have failed immediately rather than hanging.

### BLOCKER-3: Facebook/Instagram Actor-Based Collection Not Dispatched [core]

**What happens**: Facebook and Instagram are actor-only platforms (no keyword search). The batch collection dispatcher only attempts keyword-based collection (`collect_by_terms`), not actor-based collection (`collect_by_actors`). Even though actors with Facebook/Instagram presences were added to the query design, their posts were never collected.

**Research impact**: Researchers who add Facebook pages and Instagram profiles to their query design and launch a collection will always see these platforms fail with "does not support keyword-based collection." There is no way to trigger actor-based collection through the standard collection launcher.

### HIGH-1: Tier Mismatch Causes Silent Failures [frontend] [core]

**What happens**: The query design defaulted all arenas to "premium" tier. Google Search, Google Autocomplete, and X/Twitter only have medium-tier credentials configured. The collection silently fails for these platforms with "No credential available for platform X at tier 'premium'."

**Research impact**: A researcher who has a Serper.dev API key (medium tier) and configures their query design via the arena grid must manually verify that each arena's tier matches their available credentials. The system does not warn at launch time that "you selected premium tier for Google Search but only a medium-tier credential is available."

**Workaround attempted**: Changing the arena tier required using the dedicated `POST /query-designs/{id}/arena-config` endpoint. The standard `PATCH /query-designs/{id}` endpoint does NOT support updating `arenas_config` -- the `QueryDesignUpdate` schema does not include it. This means a researcher using the API cannot update arena tiers via the standard update flow.

### HIGH-2: Reddit Records Missing Language Field [data]

**What happens**: All 100 Reddit records have an empty `language` field.

**Research impact**: Language-based filtering in the content browser will miss all Reddit content. If a researcher filters to `language=da`, Reddit posts are excluded even though they are clearly Danish (from r/Denmark with Danish titles).

### HIGH-3: YouTube Results Not Filtered to Danish [data]

**What happens**: 114 of 274 YouTube records (42%) are in non-Danish languages (English, Hindi, Indonesian, Norwegian, etc.).

**Research impact**: A researcher studying Danish discourse on Greenland receives a significant proportion of non-Danish content. The `relevanceLanguage=da` and `regionCode=DK` filters on YouTube do not strictly limit to Danish-language results.

### HIGH-4: Wikipedia Records Lack Pseudonymization [data]

**What happens**: All 505 Wikipedia records and all 25 GDELT records have NULL `pseudonymized_author_id`.

**Research impact**: GDPR compliance requires pseudonymization of author identifiers. Wikipedia editor usernames and GDELT source attributions are stored in plain text without pseudonymization.

### HIGH-5: Intra-Platform Content Duplication [data]

**What happens**: 1,442 total records but only 930 unique content hashes. The worst case is Google Search with one content hash appearing 21 times (the same page appeared in results for different search terms). Wikipedia has groups of 7 records with the same hash.

**Research impact**: Volume metrics are inflated. A researcher analyzing "how many unique pieces of content mention Greenland" would overcount by ~35%.

---

## Friction Points

### FRICTION-1: No Way to Update Arena Tiers via Standard PATCH [frontend] [core]

The `QueryDesignUpdate` schema does not include `arenas_config`. The only way to update arena tiers is via the dedicated `POST /query-designs/{id}/arena-config` endpoint. A researcher using the query design editor in the browser can presumably use the arena grid, but a researcher working via the API has no obvious way to change tiers after initial creation.

### FRICTION-2: Actor Create Response Omits Presences [core]

When creating an actor with `POST /actors/` and including a `presence` field, the response body shows `presences: []` even though the presence was successfully created. The presence only appears when fetching the actor detail via `GET /actors/{id}`. This is confusing for API users who expect the response to reflect the created state.

### FRICTION-3: Collection Run Never Reaches "Completed" Status [core]

Because of the stuck tasks (BLOCKER-2), all three collection runs remain in "running" status indefinitely. The researcher has no way to finalize a run or acknowledge that some tasks will never complete.

### FRICTION-4: RSS Feed Yield is Very Low for Forward-Only Arenas [research]

RSS feeds returned only 4 articles for a week of Greenland coverage. Since RSS is `forward_only` (only captures current feed items at collection time), it misses articles that were published and then aged out of the feed. For a prominent topic like Greenland, major Danish outlets published many articles during the week, but by collection time only the most recent remained in feeds. The researcher should be warned that RSS is only effective for live/recurring collection, not retrospective batch collection.

### FRICTION-5: Deferred Stubs Accept Collection Tasks [core]

VKontakte and Twitch are documented as "deferred stubs" but the collection dispatcher still creates tasks for them. These tasks then hang forever. Stubs should either refuse task creation or fail immediately with a clear "not implemented" message.

### FRICTION-6: Political Party Actor Type Shows as "Account" in UI [frontend]

When actors with `actor_type=political_party` are added to the query design, the HTMX-rendered list item displays "Account" badge instead of "Party" or "Political Party". The badge rendering only has cases for "person", "organization", and "media_outlet"; other types fall through to a generic "Account" label.

---

## Data Quality Summary

### Language Accuracy

| Platform | Expected Language | Actual | Assessment |
|----------|------------------|--------|------------|
| Bluesky | da (lang:da filter) | 100% da | PASS |
| YouTube | da (relevanceLanguage=da) | 58% da, 42% other | PARTIAL -- non-Danish content leaks through |
| Reddit | da (r/Denmark) | 100% empty field | FAIL -- no language set |
| TikTok | da | 98% da | PASS |
| GDELT | da (sourcelang:danish) | 100% da | PASS |
| Google Search | da (gl=dk, hl=da) | 92% da | GOOD |
| Ritzau Via | da | 100% da | PASS |
| RSS Feeds | da (Danish outlets) | 100% da | PASS |

### Pseudonymization (GDPR Compliance)

| Platform | Pseudonymized | Assessment |
|----------|---------------|------------|
| Bluesky | Yes (100%) | PASS |
| YouTube | Yes (100%) | PASS |
| Reddit | Yes (100%) | PASS |
| TikTok | Yes (100%) | PASS |
| Ritzau Via | Yes (100%) | PASS |
| Wikipedia | No (0%) | FAIL |
| GDELT | No (0%) | FAIL |
| Google Search | No (0%) | N/A (search results, not user content) |
| Google Autocomplete | No (0%) | N/A (no author concept) |
| RSS Feeds | No (0%) | N/A (news articles, publisher is the author) |

### Content Relevance

All platforms returned content genuinely related to the search terms ("gronland", "Inatsisartut", "nuuk"). The content includes:
- Political discourse about Trump and Greenland (Reddit, Bluesky, TikTok)
- Danish news articles about Greenland governance (GDELT, RSS, Ritzau Via)
- YouTube videos about Greenland travel, politics, and culture
- Google Search results for Greenland-related queries
- Wikipedia revision activity on Greenland-related articles

---

## Recommendations (Prioritized)

### Critical (Must Fix)

1. **[core] [data] Fix `search_terms_matched` population for Reddit, Wikipedia, GDELT, and Google Autocomplete collectors.** These four collectors must set the field during normalization. Without it, 46% of collected content is invisible in the default content browser.

2. **[core] Implement task timeout and stale-run cleanup.** Arena tasks that remain in "pending" or "running" for more than N minutes (configurable, suggest 15 min) should be automatically marked as failed. Collection runs where all tasks have reached a terminal state should be marked "completed."

3. **[core] Dispatch actor-based collection for actor-only platforms (Facebook, Instagram).** The batch collection orchestrator should detect platforms that only support `collect_by_actors` and dispatch actor collection when actors with presences for those platforms exist in the query design's actor list.

4. **[core] Prevent deferred stubs from accepting collection tasks.** VKontakte and Twitch should either not appear as enabled arenas in the collection dispatcher or should fail immediately with "This arena is not yet implemented."

### High Priority

5. **[core] Validate credential availability against tier at launch time.** Before creating collection tasks, the launcher should check `has_credentials` for each enabled arena at its configured tier and warn the researcher: "Google Search (premium) has no credential. Switch to medium tier or add a SerpAPI key."

6. **[data] Populate the `language` field on Reddit records.** The Reddit collector should detect language (at minimum from the subreddit locale, or via post-collection language detection enrichment).

7. **[data] Fix pseudonymization for Wikipedia and GDELT collectors.** Wikipedia editor usernames and GDELT author names should be pseudonymized according to the GDPR protocol.

8. **[data] Implement intra-platform deduplication.** When the same URL or content hash appears multiple times within a single collection run (from different search terms), only one record should be stored. Currently, Google Search stores the same page 21 times.

9. **[core] Add `arenas_config` to `QueryDesignUpdate` schema.** Allow researchers to update arena tiers via the standard PATCH endpoint, not just the dedicated arena-config POST endpoint.

### Medium Priority

10. **[frontend] Add a visible "show all records" toggle in the content browser.** The default view should either show all records or display a warning: "N records are hidden because they lack matched search terms. Click to show all."

11. **[core] Investigate and fix Telegram MTProto session timeout.** The Telegram collector appears to hang indefinitely on connection. Add a connection timeout and session validation before attempting collection.

12. **[core] Investigate X/Twitter HTTP 405 error.** The TwitterAPI.io medium-tier credential returned HTTP 405. Check if the API endpoint URL or request method has changed.

13. **[research] Document that RSS feeds are forward-only and not suitable for retrospective batch collection.** The collection launcher date-range warning should specifically mention this.

14. **[frontend] Show correct actor type badges for all enum values.** Political_party, educational_institution, teachers_union, think_tank, government_body, ngo, and company should each have a distinct badge label.

15. **[core] Fix actor create response to include presences.** The `POST /actors/` response should reflect the attached presence in the `presences` field, not require a separate GET call.

---

## Appendix: Database Content Distribution

```
Platform             | Records | Unique Hashes | search_terms_matched | Pseudonymized | Language
---------------------|---------|---------------|----------------------|---------------|--------
wikipedia            |     505 |           ~72 | 0% populated         | No            | empty
youtube              |     274 |          ~260 | 100% populated       | Yes           | mixed
google_search        |     255 |          ~220 | 100% populated       | No (N/A)      | 92% da
bluesky              |     154 |           154 | 100% populated       | Yes           | 100% da
reddit               |     100 |           ~88 | 0% populated         | Yes           | empty
tiktok               |      46 |            46 | 100% populated       | Yes           | 98% da
google_autocomplete  |      40 |            40 | 0% populated         | No (N/A)      | N/A
ritzau_via           |      39 |            39 | 100% populated       | Yes           | 100% da
gdelt                |      25 |            25 | 0% populated         | No            | 100% da
rss_feeds (dr+tv2)   |       4 |             4 | 100% populated       | No (N/A)      | 100% da
---------------------|---------|---------------|----------------------|---------------|--------
TOTAL                |   1,442 |           930 |                      |               |
```

## Appendix: Credential Configuration Status

```
Platform             | .env Key                    | Has Value | Tier Available
---------------------|-----------------------------|-----------|---------------
Bluesky              | BLUESKY_HANDLE/APP_PASSWORD | Yes       | free
Reddit               | REDDIT_CLIENT_ID/SECRET     | Yes       | free
YouTube              | YOUTUBE_API_KEY             | Yes       | free
TikTok               | TIKTOK_CLIENT_KEY/SECRET    | Yes       | free
Telegram             | TELEGRAM_API_ID/HASH/SESSION| Yes       | free
Google (Serper)      | SERPER_API_KEY              | Yes       | medium
Google (SerpAPI)     | SERPAPI_API_KEY              | No        | premium (missing)
X/Twitter (API.io)   | TWITTERAPIIO_API_KEY        | Yes       | medium
Facebook (BrightData)| BRIGHTDATA_FACEBOOK_API_TOKEN| Yes      | medium
Instagram (BrightData)| BRIGHTDATA_INSTAGRAM_API_TOKEN| Yes   | medium
Discord              | DISCORD_BOT_TOKEN           | Yes       | free
OpenRouter           | OPENROUTER_API_KEY          | Yes       | medium
Event Registry       | EVENT_REGISTRY_API_KEY      | No        | missing
Gab                  | GAB_ACCESS_TOKEN            | No        | missing
Majestic             | MAJESTIC_API_KEY            | No        | missing
Threads              | THREADS_ACCESS_TOKEN        | No        | missing
```
