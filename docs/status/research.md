# Research Strategist -- Status

## Arena Briefs -- Phase 1
| Arena | Brief Status | Path | Priority |
|-------|-------------|------|----------|
| Google Search | Not started | `/docs/arenas/google_search.md` | Phase 0 |
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
| Google SERP | Not started | `/docs/arenas/google_serp.md` | Critical (2.2) |
| Facebook/Instagram | **Ready for implementation** | `/docs/arenas/facebook_instagram.md` | High (2.3) |
| LinkedIn | **Ready for implementation** | `/docs/arenas/linkedin.md` | High (2.5) |
| Threads | **Ready for implementation** | `/docs/arenas/threads.md` | High (2.6) |

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
- [x] Event Registry / NewsAPI.ai (brief: `/docs/arenas/event_registry.md`)
- [x] Majestic (brief: `/docs/arenas/majestic.md`)
- [x] Common Crawl / Wayback Machine (brief: `/docs/arenas/common_crawl_wayback.md`)
- [x] X/Twitter (brief: `/docs/arenas/x_twitter.md`)
- [x] Facebook/Instagram (brief: `/docs/arenas/facebook_instagram.md`)
- [x] LinkedIn (brief: `/docs/arenas/linkedin.md`)
- [x] Threads (brief: `/docs/arenas/threads.md`)

## Knowledge Base Documents
- [x] Cross-platform data collection guide (`/reports/cross_platform_data_collection.md`)
- [x] Danish context guide (`/reports/danish_context_guide.md`)
- [x] Zeeschuimer assessment (`/reports/zeeschuimer_assessment.md`) -- 2026-02-15

## Decisions (ADRs)
_None yet._

## Notes
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
