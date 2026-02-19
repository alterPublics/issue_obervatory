# Research Strategist -- Status

## Arena Briefs -- Phase 1
| Arena | Brief Status | Path | Priority |
|-------|-------------|------|----------|
| Google Search | **Implemented (retroactive)** | `/docs/arenas/google_search.md` | Phase 0 |
| Google Autocomplete | **Ready for implementation** | `/docs/arenas/google_autocomplete.md` | Critical (1.4) |
| Bluesky | **Ready for implementation** | `/docs/arenas/bluesky.md` | Critical (1.5) |
| Reddit | **Ready for implementation** | `/docs/arenas/reddit.md` | Critical (1.6) |
| YouTube | **Ready for implementation** | `/docs/arenas/youtube.md` | Critical (1.7) |
| Danish RSS | **Ready for implementation** | `/docs/arenas/rss_feeds.md` | Critical (1.8) |
| GDELT | **Ready for implementation** | `/docs/arenas/gdelt.md` | High (1.9) |
| Telegram | **Ready for implementation** | `/docs/arenas/telegram.md` | High (1.10) |
| TikTok | **Ready for implementation** | `/docs/arenas/tiktok.md` | High (1.11) |
| Via Ritzau | **Ready for implementation** | `/docs/arenas/ritzau_via.md` | Medium (1.12) |
| Gab | **Ready for implementation** | `/docs/arenas/gab.md` | Medium (1.13) |

## Arena Briefs -- Phase 2
| Arena | Brief Status | Path | Priority |
|-------|-------------|------|----------|
| Event Registry / NewsAPI.ai | **Ready for implementation** | `/docs/arenas/event_registry.md` | High (2.4) |
| Majestic | **Ready for implementation** | `/docs/arenas/majestic.md` | Medium (2.7) |
| Common Crawl / Wayback Machine | **Ready for implementation** | `/docs/arenas/common_crawl_wayback.md` | Low (2.10) |
| X/Twitter | **Ready for implementation** | `/docs/arenas/x_twitter.md` | Critical (2.1) |
| Google SERP | **Implemented (retroactive)** | `/docs/arenas/google_search.md` | Critical (2.2) |
| Facebook/Instagram | **Ready for implementation** | `/docs/arenas/facebook_instagram.md` | High (2.3) |
| LinkedIn | **Ready for implementation** | `/docs/arenas/linkedin.md` | High (2.5) |
| Threads | **Ready for implementation** | `/docs/arenas/threads.md` | High (2.6) |

## Arena Briefs -- New Arenas (Phase 2.5 / 3+ / Future)
| Arena | Brief Status | Path | Priority |
|-------|-------------|------|----------|
| Wikipedia | **Ready for implementation** | `/docs/arenas/wikipedia.md` | High (Phase 2.5) |
| Discord | **Ready for implementation** (pending ethical review) | `/docs/arenas/discord.md` | Medium (Phase 3+) |
| Twitch | **Deferred** | `/docs/arenas/twitch.md` | Low (Phase 3+) |
| VKontakte (VK) | **Deferred** (pending legal review) | `/docs/arenas/vkontakte.md` | Low (Phase 4 / Future) |

**Implementation plan document**: `/docs/arenas/new_arenas_implementation_plan.md`

## Arena Briefs -- Greenland Roadmap
| Arena | Brief Status | Path | Priority |
|-------|-------------|------|----------|
| URL Scraper | **Ready for implementation** | `/docs/arenas/url_scraper.md` | High (GR-10) |

## Ready for Implementation -- Phase 1
- [x] Google Autocomplete (brief: `/docs/arenas/google_autocomplete.md`)
- [x] Bluesky (brief: `/docs/arenas/bluesky.md`)
- [x] Reddit (brief: `/docs/arenas/reddit.md`)
- [x] YouTube (brief: `/docs/arenas/youtube.md`)
- [x] Danish RSS feeds (brief: `/docs/arenas/rss_feeds.md`)
- [x] GDELT (brief: `/docs/arenas/gdelt.md`)
- [x] Telegram (brief: `/docs/arenas/telegram.md`)
- [x] TikTok (brief: `/docs/arenas/tiktok.md`)
- [x] Via Ritzau (brief: `/docs/arenas/ritzau_via.md`)
- [x] Gab (brief: `/docs/arenas/gab.md`)

## Ready for Implementation -- Phase 2
- [x] Google SERP (brief: `/docs/arenas/google_search.md`) -- retroactive documentation of implemented arena
- [x] Event Registry / NewsAPI.ai (brief: `/docs/arenas/event_registry.md`)
- [x] Majestic (brief: `/docs/arenas/majestic.md`)
- [x] Common Crawl / Wayback Machine (brief: `/docs/arenas/common_crawl_wayback.md`)
- [x] X/Twitter (brief: `/docs/arenas/x_twitter.md`)
- [x] Facebook/Instagram (brief: `/docs/arenas/facebook_instagram.md`)
- [x] LinkedIn (brief: `/docs/arenas/linkedin.md`)
- [x] Threads (brief: `/docs/arenas/threads.md`)

## Ready for Implementation -- New Arenas
- [x] Wikipedia (brief: `/docs/arenas/wikipedia.md`) -- High priority, Phase 2.5
- [x] Discord (brief: `/docs/arenas/discord.md`) -- Medium priority, Phase 3+ (pending ethical review)
- [ ] Twitch (brief: `/docs/arenas/twitch.md`) -- Low priority, Phase 3+ (deferred)
- [ ] VKontakte (brief: `/docs/arenas/vkontakte.md`) -- Low priority, Phase 4 / Future (pending legal review)

## Ready for Implementation -- Greenland Roadmap
- [x] URL Scraper (brief: `/docs/arenas/url_scraper.md`) -- High priority, GR-10

## Knowledge Base Documents
- [x] Cross-platform data collection guide (`/reports/cross_platform_data_collection.md`)
- [x] Danish context guide (`/reports/danish_context_guide.md`)
- [x] Zeeschuimer assessment (`/reports/zeeschuimer_assessment.md`) -- 2026-02-15

## Research Reports
- [x] CO2 afgift codebase evaluation (`/docs/research_reports/co2_afgift_codebase_recommendations.md`) -- 2026-02-17
- [x] AI og uddannelse issue mapping codebase evaluation (`/docs/research_reports/ai_uddannelse_codebase_recommendations.md`) -- 2026-02-18
- [x] Implementation Plan 2.0 Strategic Synthesis (`/docs/research_reports/implementation_plan_2_0_strategy.md`) -- 2026-02-18
- [x] Greenland in the Danish General Election 2026 codebase evaluation (`/docs/research_reports/greenland_codebase_recommendations.md`) -- 2026-02-18
- [x] Ytringsfrihed discourse mapping codebase recommendations (`/docs/research_reports/ytringsfrihed_codebase_recommendations.md`) -- 2026-02-19

## Phase 3 UX Review

**Status:** Complete (research-strategist assessment appended 2026-02-17)
**Report:** `/docs/ux_reports/phase_3_report.md`

### Findings Summary

| ID | Type | Description | Research Validity | QA Fix |
|----|------|-------------|-------------------|--------|
| B-01 | Blocker | Snowball sampling has no frontend entry point | Medium (affects completeness) | Open |
| B-02 | Blocker | Term and bipartite GEXF exports produce actor network | Critical (invalidates findings) | Open |
| B-03 | Blocker | No UI for viewing or suspending live tracking schedule | Medium (affects completeness) | Open |
| B-04 | Blocker | Admin credential form missing 5 platform options | Medium (affects completeness) | Open |
| DQ-01 | Data Quality | Bluesky actor-based collection had no language filter | High (requires caveats) | Fixed |
| DQ-02 | Data Quality | GEXF edge construction used run_id, not shared terms | Critical (invalidates findings) | Fixed |
| DQ-03 | Data Quality | Reddit subreddit list: docs said 7, code had 4 | High (requires caveats) | Fixed |
| DQ-04 | Data Quality | GDELT deduplication scope not visible | Medium (affects completeness) | Open |
| DQ-05 | Data Quality | Jyllands-Posten RSS uncertainty not in docs | High (requires caveats) | Fixed (docs) |
| DQ-06 | Data Quality | TikTok 10-day engagement lag not shown in browser | Medium (affects completeness) | Open |

### Critical Research Validity Risks (items that can invalidate published findings)
- **DQ-02** (QA-FIXED): GEXF actor co-occurrence network was fully connected due to run_id grouping. Fix rewrites edge logic to use shared search terms. Regression tests specified but not yet verified.
- **B-02** (OPEN): Term and bipartite network exports are not implemented. All three GEXF download buttons produce the same actor network file. Researchers must not use the "term" or "bipartite" download buttons until these are implemented or removed.

### Documentation Corrections Applied (2026-02-17)

All 8 documentation corrections from the research-strategist assessment have been applied:

1. **Correction 1 -- Bluesky language filter scope** (`what_data_is_collected.md`): Rewrote Danish targeting paragraph to distinguish term-based collection (server-side `lang:da` parameter) from actor-based collection (client-side language filtering; posts with no declared language included).
2. **Correction 2 -- Bluesky Jetstream dependency** (`what_data_is_collected.md`): Added note that Jetstream streaming requires the `websockets` Python package, which is not installed by default.
3. **Correction 3 -- Reddit subreddit list** (`what_data_is_collected.md`): Verified QA-applied fix is correct -- documentation lists 4 subreddits matching the code (r/Denmark, r/danish, r/copenhagen, r/aarhus). No change needed.
4. **Correction 4 -- Jyllands-Posten RSS caveat** (`what_data_is_collected.md`): Added parenthetical note after Jyllands-Posten in the RSS sources list warning that feed availability is uncertain as of 2026.
5. **Correction 5 -- Missing YouTube section** (`what_data_is_collected.md`): Added full YouTube section under Social Media Platforms covering: collected fields, NOT collected items, Danish targeting (`relevanceLanguage=da`, `regionCode=DK`), actor-based collection via RSS feed polling + `videos.list` enrichment, FREE tier with API key, quota management strategy. Also added YouTube row to the Summary Table.
6. **Correction 6 -- Missing Python venv prerequisite** (`env_setup.md`): Added prerequisite block before Step 2 of Part 8 explaining how to create a virtual environment and install dependencies.
7. **Correction 7 -- Missing Docker prerequisite** (`env_setup.md`): Added prerequisite block before Step 3 of Part 8 instructing the reader to verify Docker is installed.
8. **Correction 8 -- Credential UI limitation** (`env_setup.md`): Added note after the admin UI credential instructions listing the 5 platforms not available in the UI dropdown (Gab, Threads, Bright Data Facebook, Bright Data Instagram, SerpAPI) and directing to the bootstrap script.

### Remaining Open Items (research-strategist perspective)
- B-02: Remove or disable Term and Bipartite tabs in analysis dashboard until exports are implemented
- B-04: Add 5 missing platforms to credential dropdown (code change, not documentation)
- B-03: Display schedule info on collection detail page for live runs
- B-01: Expose snowball sampling in actor directory UI

## Decisions (ADRs)
_None yet._

## Phase A Research Configuration Fixes
- [x] IP2-009: Add Altinget RSS feeds to `DANISH_RSS_FEEDS` (`config/danish_defaults.py`) -- main feed (existing), plus uddannelse and klima section feeds (2026-02-18)
- [x] IP2-058: Add education-specific RSS feeds to `DANISH_RSS_FEEDS` (`config/danish_defaults.py`) -- Folkeskolen, Gymnasieskolen, KU, DTU, CBS; DEA commented out pending verification (2026-02-18)
- [x] IP2-059: Expand Reddit subreddits -- added `r/dkpolitik` to `EXTRA_DANISH_SUBREDDITS`; `r/dkfinance` was already present
- [x] IP2-060: Formalize `actor_type` values -- added `ActorType` enum to `core/models/actors.py`, updated Pydantic schemas with `Literal` type validation, updated both UI dropdowns (actor list + query design editor)

## Notes
- 2026-02-19: Completed codebase improvement recommendations for "ytringsfrihed" (freedom of speech) discourse mapping scenario. Report at `/docs/research_reports/ytringsfrihed_codebase_recommendations.md` (831 lines). Derived from the UX test report at `/docs/ux_reports/ytringsfrihed_mapping_report.md`, cross-referenced against the actual codebase (14 source files examined) and 4 prior recommendation reports. 16 prioritized recommendations (2 Critical, 5 High, 6 Medium, 3 Low) organized into a 4-phase implementation roadmap. Total estimated effort: 29-49 person-days. Key findings: (1) Per-arena search term scoping (YF-01) is the single most impactful architectural change -- the shared search term list contaminating irrelevant arenas is a fundamental limitation affecting every multi-lingual/multi-arena scenario; (2) Source-list arena configuration UI (YF-02) removes the only functional blocker (BL-01) -- non-technical researchers cannot use Telegram, custom Reddit, custom RSS without API calls; (3) Bulk import for terms and actors (YF-03, YF-07) is a prerequisite for any serious research workflow; (4) Cross-run analysis (YF-06) is essential for iterative research; (5) Ad-hoc exploration mode (YF-05) addresses the "no discovery" gap. This is the fourth scenario evaluation. Cross-referencing reveals per-arena term customization and source-list arena config have now appeared in 3+ evaluations, establishing them as systemic priorities. Only YF-01 requires a database migration (nullable JSONB column on search_terms). Report follows the format conventions established by the Greenland report, including: code-level implementation suggestions with specific file paths, dependency graph, cross-cutting concerns (GDPR, performance, testing), and comprehensive mapping of UX findings to recommendations.
- 2026-02-19: Completed arena research brief for URL Scraper (GR-10) at `/docs/arenas/url_scraper.md`. This arena accepts a researcher-provided list of URLs, fetches each page asynchronously via the existing `src/issue_observatory/scraper/` module (HttpFetcher + ContentExtractor), extracts article text via trafilatura, and normalizes results to UCR format. Two tiers: FREE (100 URLs, httpx only, 1 req/sec per domain) and MEDIUM (500 URLs, optional Playwright fallback, 2 req/sec per domain). No external API cost. Key design decisions: (1) reuses existing scraper module entirely -- no HTTP fetching or text extraction re-implementation; (2) per-URL error isolation -- one URL failure does not abort the run; (3) per-domain rate limiting via asyncio.Semaphore, not global throttle; (4) robots.txt compliance with fail-open behavior; (5) URL list configured via `arenas_config["url_scraper"]["custom_urls"]` in query design (same pattern as GR-01 RSS custom feeds); (6) collect_by_actors() resolves ActorPlatformPresence records where platform="url_scraper" and platform_username is a website base URL. Engineering agent is unblocked for implementation.
- 2026-02-18: Completed comprehensive codebase evaluation for "Greenland in the Danish General Election 2026" scenario. Report at `/docs/research_reports/greenland_codebase_recommendations.md` (876 lines). Overall readiness assessed at 65-70% -- intermediate between CO2 afgift (75-80%) and AI og uddannelse (55-60%). This scenario is uniquely demanding due to: (1) multi-language requirements (Danish, English, Kalaallisut, Russian), (2) conspiracy theory and foreign interference monitoring needs, (3) cross-arena narrative propagation tracking, (4) election-bounded temporal urgency, (5) multi-jurisdictional actor space. 16 Greenland-specific improvement items (GR-01 through GR-16) defined, with 6 critical-priority items (mostly configuration changes, 3-5 days total). Key gaps: no Greenlandic news RSS feeds, Telegram channel list covers only 6 mainstream outlets, no Kalaallisut language support, no cross-arena temporal propagation detection (IP2-050 not yet implemented), no coordinated posting detection for interference monitoring, VKontakte deferred with legal blockers. 14 arenas available at free tier ($0/month); medium tier adds Event Registry + Google Search for $164-299/month. Draft query design specification included with search terms in 3 languages and multi-jurisdictional actor lists.
- 2026-02-18: Created comprehensive implementation plan for four new arenas: Wikipedia, Discord, Twitch, and VKontakte. Deliverables: (1) combined implementation plan at `/docs/arenas/new_arenas_implementation_plan.md` covering all four arenas with cross-cutting architectural concerns, (2) individual arena research briefs in 12-section format at `/docs/arenas/wikipedia.md`, `/docs/arenas/discord.md`, `/docs/arenas/twitch.md`, `/docs/arenas/vkontakte.md`. Priority assessment: Wikipedia is HIGH priority (Phase 2.5) -- provides unique editorial-attention signals, free, legally simple, technically straightforward; Discord is MEDIUM priority (Phase 3+) -- limited Danish relevance, requires ethical review for semi-private communities, no keyword search for bots; Twitch is LOW priority (Phase 3+, deferred) -- streaming-only architecture, no historical chat retrieval, low Danish relevance; VKontakte is LOW priority (Phase 4/Future) -- zero Danish discourse relevance, moderate-to-high legal risk due to EU sanctions context, university legal review mandatory before implementation. Key cross-cutting findings: (a) no new ArenaCollector base class needed -- existing pattern and streaming queue infrastructure are sufficient; (b) no new database extension tables needed -- JSONB raw_metadata handles all platform-specific data; (c) proposed new arena group "reference" for Wikipedia (pending team discussion); (d) new content_type "chat_message" for Twitch ephemeral chat; (e) Discord and Twitch streaming tasks should be routed to the existing "streaming" Celery queue with extended 24-hour time limits.
- 2026-02-18: Extended IP2-009 and implemented IP2-058. IP2-009: Added Altinget section feeds (`altinget_uddannelse`, `altinget_klima`) to `DANISH_RSS_FEEDS` in `config/danish_defaults.py`. These supplement the existing main Altinget feed and provide targeted coverage of education and climate policy discourse. IP2-058: Added 5 education-sector RSS feeds to `DANISH_RSS_FEEDS`: Folkeskolen.dk (primary education, published by DLF), Gymnasieskolen.dk (upper-secondary, published by GL), KU nyheder (University of Copenhagen), DTU nyheder (Technical University of Denmark), CBS nyheder (Copenhagen Business School). DEA (Taenketanken DEA) feed commented out pending verification. All new feed URLs are marked as unverified in code comments and in the updated arena brief (`docs/arenas/rss_feeds.md`). Updated arena brief with two new sections: Altinget Section Feeds and Education-Sector Feeds. Network verification was unavailable during this session; feeds must be validated via RSS arena health check at implementation time.
- 2026-02-18: Implemented Phase A research configuration fixes (IP2-009, IP2-059, IP2-060). IP2-009: Added Altinget.dk RSS feed (`https://www.altinget.dk/feed/rss.xml`) to `DANISH_RSS_FEEDS` in `config/danish_defaults.py`. Altinget is the most important Danish policy news outlet, identified as a critical gap in both CO2 afgift and AI og uddannelse evaluations. IP2-059: Added `r/dkpolitik` to `EXTRA_DANISH_SUBREDDITS` in `arenas/reddit/config.py`; `r/dkfinance` was already present. IP2-060: Created `ActorType(str, Enum)` with 11 research-relevant categories (person, organization, political_party, educational_institution, teachers_union, think_tank, media_outlet, government_body, ngo, company, unknown). Updated Pydantic schemas to use `Literal` type validation. Updated UI dropdowns in both `actors/list.html` and `query_designs/editor.html`. No Alembic migration needed -- the enum is enforced at the application/API level while the database column remains `String(50)` for backward compatibility with existing data. Note: the old UI had "organisation" (British spelling) and "account" as values; these are replaced by "organization" (consistent with code conventions) and the expanded set. Existing records with old values will pass through `ActorResponse` since `actor_type` is `Optional` on the response schema -- they will not be rejected, but will need manual migration if strict validation is desired.
- 2026-02-18: Completed Implementation Plan 2.0 Strategic Synthesis (`/docs/research_reports/implementation_plan_2_0_strategy.md`). Merged findings from all 4 test case reports (2 UX reports, 2 codebase evaluations) into a unified, deduplicated, prioritized roadmap. 61 improvement items (IP2-001 through IP2-061) organized into 4 phases: Phase A (Foundation Fixes, 22-28 person-days), Phase B (Discourse Tracking Maturity, 22-33 person-days), Phase C (Issue Mapping Capabilities, 27-42 person-days), Phase D (Advanced Research Features, 19-29 person-days). Total estimated effort: 90-132 person-days. Key strategic conclusions: (1) 28 systemic problems affect BOTH methodologies and must be fixed first; (2) the dynamic arena grid (IP2-001) and enrichment pipeline architecture (IP2-036) are the two items that unblock the most downstream work; (3) emergent term extraction (IP2-038) is the single most transformative capability for issue mapping; (4) Phase A alone raises discourse tracking readiness from 75-80% to 88-92% and issue mapping readiness from 55-60% to 68-72%. Cross-referenced every finding ID from all source reports to unified roadmap items (Appendix A). Included dependency graph, cost-benefit analysis per phase, and tier/arena strategy with cost projections for typical studies.
- 2026-02-18: Completed comprehensive codebase evaluation for Marres-style issue mapping of "AI og uddannelse" (AI and education) in Danish public discourse. Report at `/docs/research_reports/ai_uddannelse_codebase_recommendations.md`. Key findings: system is ~55-60% ready for issue mapping (lower than CO2 afgift's 75-80% because issue mapping requires analytical capabilities beyond data collection). 6 critical gaps identified: (1) no emergent term/topic extraction (the defining gap -- cannot discover discourse associations), (2) no actor role classification (speaker vs. mentioned vs. quoted), (3) no stance/position mapping, (4) no controversy detection, (5) no temporal network analysis, (6) bipartite network limited to search terms instead of extracted topics. 4-tier prioritized roadmap with 22 items, diverging significantly from CO2 afgift roadmap. Estimated 8K-25K records over 4 months at ~$103-120/month (Phase A+B). 18 arenas evaluated for AI og uddannelse relevance; recommended activating 7 immediately (free), 3 with budget. LinkedIn and education-specific outlets (Altinget, Folkeskolen.dk) identified as critical gaps. Actor seed list with 40+ actors across 7 categories. Bilingual query challenge more significant than CO2 afgift due to English-native AI terminology. Recommended hybrid workflow: automated collection + manual qualitative coding for stance/controversy.
- 2026-02-17: Completed comprehensive codebase evaluation for CO2 afgift (carbon tax/levy) issue mapping research. Report at `/docs/research_reports/co2_afgift_codebase_recommendations.md`. Key findings: system is ~75-80% ready; 5 critical gaps identified (no boolean query logic, no sentiment/stance indicators, no temporal comparison, limited cross-arena narrative tracking, open B-02 blocker needs verification). 4-tier prioritized improvement roadmap with 20 items. Estimated 28K-70K records over a 6-month study at ~$160-235/month. 18 arenas evaluated for CO2 afgift relevance; recommended activating 7 immediately (free), 3 with budget, 1 pending access. LinkedIn identified as highest-value coverage gap. Altinget.dk and Folketinget.dk identified as missing critical sources.
- 2026-02-17: Applied all 8 documentation corrections identified in the Phase 3 research-strategist assessment. Files modified: `docs/guides/what_data_is_collected.md` (corrections 1-5: Bluesky language filter scope, Bluesky Jetstream dependency, Reddit subreddit list verified, JP RSS caveat added, YouTube section added with Summary Table row), `docs/guides/env_setup.md` (corrections 6-8: Python venv prerequisite, Docker prerequisite, credential UI limitation note). Each correction was cross-checked against source files (`bluesky/collector.py`, `bluesky/config.py`, `danish_defaults.py`, `youtube/collector.py`, `youtube/config.py`, `settings.py`) before applying. DQ-05 (JP RSS caveat) is now resolved via documentation. Remaining open items are code-level changes (B-01, B-02, B-03, B-04), not documentation.
- 2026-02-17: Completed research-strategist assessment of Phase 3 UX report. Assessment appended to `/docs/ux_reports/phase_3_report.md`. Two findings rated Critical for research validity: DQ-02 (GEXF edge construction, now fixed by QA) and B-02 (term/bipartite GEXF exports not implemented, still open). Three findings rated High: DQ-01 (fixed), DQ-03 (fixed), DQ-05 (open -- JP RSS caveat needed). Priority remediation order established with silent-data-corruption defects ranked above visible blockers. Researcher workarounds documented for all open items. Eight documentation corrections identified across `what_data_is_collected.md` and `env_setup.md`.
- 2026-02-16: Completed retroactive arena research brief for Google Search (SERP), the final missing Phase 2 brief. This arena was already implemented at `src/issue_observatory/arenas/google_search/`. The brief documents the existing collector: Serper.dev (MEDIUM) and SerpAPI (PREMIUM) providers, Danish locale params (`gl=dk`, `hl=da`), `content_type="search_result"`, `collect_by_actors()` via `site:` queries, shared credentials with Google Autocomplete. All Phase 2 arena briefs are now complete.
- 2026-02-16: Completed 4 additional Phase 2 arena research briefs: X/Twitter (Critical, 2.1), Facebook/Instagram (High, 2.3), LinkedIn (High, 2.5), Threads (High, 2.6). All Phase 2 social media arenas now have completed briefs. Engineering agents are unblocked for implementation. Key observations:
  - X/Twitter: No viable free tier (100 reads/month is unusable). Medium tier (TwitterAPI.io at $0.15/1K tweets) is the recommended starting point -- dramatically cheaper than the official Pro tier ($5K/month). Dual normalizer required (TwitterAPI.io JSON vs. official v2 API JSON). Cost control is the primary constraint, not rate limits. `lang:da` search operator works on both tiers. Credential pool holds multiple TwitterAPI.io keys for parallelism/fault tolerance.
  - Facebook/Instagram: Critical decision point at Phase 2 start -- Meta Content Library (if approved) vs. Bright Data fallback. MCL provides engagement metrics, post view counts, and global search. Bright Data provides immediate access without application process. Two separate ArenaCollectors (FacebookCollector, InstagramCollector) share Bright Data and MCL client components. Instagram has no native language filter -- Danish content identified via hashtag targeting and client-side detection. Bright Data Facebook uses asynchronous dataset delivery (hours); Instagram uses real-time API.
  - LinkedIn: Most access-restricted arena. No automated collection path as of February 2026. DSA Article 40 researcher access is the premium path but not yet fully operationalized. Zeeschuimer browser capture is the only current data pathway (manual, non-scalable). Third-party scraping is NOT recommended due to EU legal risk (CNIL fined KASPR EUR 240K). Import-first architecture: build NDJSON import pathway, not ArenaCollector. Depends on generic import endpoint (POST /api/content/import).
  - Threads: Free API exists but has critical limitation -- no engagement metrics for other users' posts. No global keyword search at free tier (search is user-scoped). MCL includes Threads since February 2025, providing full research access. Threads data cannot be exported as CSV from MCL (cleanroom only). Small Danish content volume expected. Actor-first collection strategy at free tier. Token refresh automation critical (60-day expiry).
  - Remaining Phase 2 brief not yet started: Google SERP (2.2).
- 2026-02-16: Completed first 3 Phase 2 arena research briefs: Event Registry / NewsAPI.ai (High, 2.4), Majestic (Medium, 2.7), Common Crawl / Wayback Machine (Low, 2.10). Engineering agents are unblocked for implementation on these arenas. Key observations:
  - Event Registry: Primary paid news API. Provides full article text, native Danish NLP, event clustering, and entity extraction -- major upgrade over GDELT. Uses ISO 639-3 language codes (`"dan"`, not `"da"`). Token-budget-constrained: 5,000 tokens/month at Medium tier ($90/mo). Official Python SDK (`eventregistry`) handles pagination automatically.
  - Majestic: Premium-only ($400/mo). Provides web graph structure (backlinks, Trust Flow, Citation Flow), not content. Best used reactively -- triggered by signals from other arenas to track how content propagates through the web via hyperlinks. No language filtering; Danish focus achieved through domain curation. Analysis unit budget management is critical.
  - Common Crawl / Wayback Machine: Both free-tier, batch-oriented, retrospective. Not for live tracking. Unique value in historical baseline, deleted content recovery, and content change tracking. Two-step retrieval pattern (index query then content fetch) required for both. Wayback Machine has documented infrastructure fragility. Common Crawl Athena costs ~$1.50/scan.
  - Note: Web search and web fetch tools were unavailable during research. All briefs are based on domain knowledge and the existing cross-platform data collection report. Specific details (exact current pricing, rate limit numbers) are flagged where verification against live documentation is recommended.
  - Remaining Phase 2 briefs not yet started: X/Twitter (2.1), Google SERP (2.2), Facebook/Instagram (2.3), LinkedIn (2.5), Threads (2.6).
- 2026-02-16: Completed 7 arena research briefs for Critical and High priority Phase 1 arenas: Google Autocomplete, Bluesky, Reddit, YouTube, Danish RSS feeds, GDELT, Telegram. All briefs cover: platform overview, tier configuration, API/access details, Danish context, data field mapping, credential requirements, rate limits, known limitations, and collector implementation notes. Engineering agents are unblocked for implementation on these arenas.
- 2026-02-16: Completed remaining Phase 1 briefs: TikTok (High), Via Ritzau (Medium), Gab (Medium). All 10 Phase 1 arena briefs are now complete and ready for implementation. Engineering agents are fully unblocked for all Phase 1 arenas.
- 2026-02-16: Key observations from final three briefs:
  - TikTok: 10-day engagement lag is the primary limitation. Implement engagement metric re-collection task. 1,000 req/day is sufficient for targeted Danish collection. Token auto-refresh (2-hour expiry) is critical.
  - Via Ritzau: Simplest arena -- no auth, no rate limits, free unauthenticated JSON API. HTML body requires stripping. Valuable for tracking source-to-publication propagation when cross-referenced with RSS feeds.
  - Gab: Mastodon-compatible API, but test for fork-specific deviations. Very low Danish content volume expected. Research ethics documentation is important given the nature of the platform. Full-text search capability needs verification.
- 2026-02-16 (earlier): Remaining Phase 1 briefs (TikTok, Via Ritzau, Gab) are lower priority and will be completed next.
- 2026-02-16: Key cross-cutting observations:
  - Credential sharing: Serper.dev and SerpAPI credentials are shared between Google Search and Google Autocomplete arenas. CredentialPool must use platform-level keys (`"serper"`, `"serpapi"`), not arena-level keys.
  - YouTube quota pooling: Multiple GCP project API keys are essential. Default 10K units/day is insufficient for sustained collection. RSS-first strategy minimizes quota usage.
  - Telegram requires pre-Phase task E.5 (Danish channel curation) before meaningful collection can begin.
  - GDELT requires dual-language search (Danish + English) due to machine translation of Danish content.
- 2026-02-15: Completed Zeeschuimer assessment. Recommendation: keep as LinkedIn-only manual fallback (current IMPLEMENTATION_PLAN.md reference is correct). Do not expand to other platforms or invest in automation. Consider generic NDJSON import pathway for Phase 2/3.
