# Near-real-time data collection across platforms: a comprehensive methods guide

**For a research application tracking cross-platform topic propagation, the landscape as of early 2026 offers dozens of viable data pipelines — but the cost, reliability, and latency vary enormously.** The most important finding is that the data access environment has bifurcated sharply: some platforms (Bluesky, Reddit, YouTube, GDELT) remain highly accessible and research-friendly, while others (X/Twitter, Facebook, Instagram) have erected steep paywalls or bureaucratic barriers following the 2023–2024 wave of API restrictions. The good news is that third-party scraping services have matured significantly, winning key court cases that established the legality of public data scraping, creating viable alternatives where official APIs have become prohibitive. Below is a systematic assessment of every major collection method organized by platform category.

---

## Google Search and Autocomplete: official APIs fading, third-party services thriving

### SERP data collection

Google's **Custom Search JSON API** is being phased out — closed to new customers with existing users required to transition by **January 1, 2027**. It provides 100 free queries/day (paid at $5/1K, max 10K/day) but returns results from Google's Programmable Search Engine, not actual google.com SERPs. Results lack featured snippets, Knowledge Panels, and People Also Ask boxes. For a research application, this API is inadequate and has no long-term future.

The third-party SERP API market is mature and competitive. Key options ranked by cost-effectiveness:

| Provider | Cost per 1K searches | Latency | Notable strengths |
|----------|---------------------|---------|-------------------|
| **DataForSEO** (queued) | **$0.60** | ~5 min (queue), ~6 sec (live) | 2,000 API calls/min; AI Overviews endpoint; autocomplete + trends included |
| **Serper.dev** | $0.30–$1.00 | **1–2 sec** | Fastest; 300 queries/sec; 2,500 free on signup; no subscription |
| **ValueSERP** | $0.15–$1.60 | Real-time | Batch processing (15K parallel); S3/GCS export |
| **SerpAPI** | $2.75–$25.00 | 3–5 sec | 80+ search engines; U.S. Legal Shield (absorbs scraping liability); Google Autocomplete endpoint |
| **Bright Data SERP API** | $3–$5 | <1 sec | 220+ data fields; 150M+ residential IPs; enterprise-grade |
| **Oxylabs** | Custom (enterprise) | 2.7–5.5 sec | 99.95% success rate; near-zero failures in stress tests |

All third-party SERP APIs technically violate Google's Terms of Service, but **legal precedent strongly favors scrapers**: the *hiQ v. LinkedIn* (2022), *X Corp v. Bright Data* (2024, dismissed), and *Meta v. Bright Data* (2024, dismissed) rulings established that scraping publicly available data is generally lawful. SerpAPI provides an explicit "U.S. Legal Shield" transferring scraping liability from customer to provider.

**Recommendation for the research application**: Serper.dev for high-volume, low-latency SERP monitoring (best speed-to-cost ratio at $0.30/1K), with SerpAPI as a backup for its autocomplete endpoint and legal protections.

### Google Autocomplete

There is **no official Google Autocomplete API** for search suggestions. The widely-used undocumented endpoint at `https://suggestqueries.google.com/complete/search` returns JSON with suggestions and relevance scores when called with parameters like `q`, `client=firefox`, `hl`, and `gl`. It is free but Google blocks excessive querying without published rate limits. For sustained collection, third-party services are more reliable:

- **SerpAPI Autocomplete** — 0.26–1.3 sec response; 1 credit per query; 1-hour caching (cached queries free)
- **DataForSEO Autocomplete** — integrated into their pay-as-you-go system
- **Serper.dev** — includes autocomplete as a search type at standard pricing

**No commercial service specifically tracks autocomplete suggestion changes over time.** The most reliable approach for monitoring autocomplete evolution is building a scheduled polling system using SerpAPI or DataForSEO's autocomplete endpoint, storing results in a time-series database. The Bing Autosuggest API was deprecated in August 2025 and is no longer viable.

---

## Social media platforms: a platform-by-platform assessment

### X/Twitter — expensive officially, viable through third parties

The official X API tier structure as of early 2026:

| Tier | Price | Read volume | Key features |
|------|-------|-------------|--------------|
| **Free** | $0 | 100 reads/mo, 500 posts/mo | Write-focused; proof-of-concept only |
| **Basic** | $200/mo | 10,000 posts/mo | 7-day search history |
| **Pro** | $5,000/mo | 1,000,000 posts/mo | Full-archive search; **filtered streaming** (near-real-time) |
| **Enterprise** | ~$42,000+/mo | 50,000,000+ posts/mo | Full firehose; dedicated support; SLAs |

**Academic Research access was eliminated in June 2023** with no replacement. A pay-per-use pilot launched in November 2025 but remains in closed beta. The Pro tier ($5,000/mo) is the minimum for meaningful research with its filtered streaming endpoint delivering data in seconds.

Third-party alternatives offer dramatically lower costs: **TwitterAPI.io** charges $0.15/1K tweets with 1,000+ QPS and ~800ms latency; **SocialData API** costs $0.0002 per tweet; **Bright Data** offers Twitter datasets at $250/100K records with 99.99% uptime. Nitter-based approaches are **effectively dead** since January 2024 when X disabled guest accounts.

### Facebook and Instagram — Meta Content Library is the gatekept path

**CrowdTangle was shut down August 14, 2024.** Its replacement, the **Meta Content Library (MCL)**, covers Facebook, Instagram, and (since February 2025) Threads. MCL provides near-real-time access to all public posts with **100+ searchable fields** including post view counts, comments, Reels data, and text-in-image search — data CrowdTangle never had.

However, access is restricted to **academic and non-profit researchers** approved through ICPSR at the University of Michigan. Journalists and for-profit organizations are excluded. The application process requires IRB approval and institutional signatures. API access through SOMAR costs **$371/month plus a $1,000 one-time setup fee** starting January 2026. The weekly retrieval cap is **500,000 results**, and raw data export is limited to posts from accounts with 15K+ followers (Facebook) or 25K+ followers (Instagram).

The **Instagram Graph API** remains available but provides minimal research utility: only 30 unique hashtag searches per week, 200 requests/hour, and no broad public search capability. The **Facebook Graph API** is restricted to managing your own Pages — not external research.

For non-qualifying organizations, **Bright Data** (Instagram scraper at $1.50/1K records; Facebook datasets at $250/100K records) and **Data365** (€300/month multi-platform API) are the primary alternatives, operating under favorable legal precedent from Meta's own lost lawsuits against Bright Data.

### YouTube — free, generous, but quota-constrained

The **YouTube Data API v3** is entirely free with a default quota of **10,000 units/day** per Google Cloud project (quota increases available on application). The critical constraint is that **search queries cost 100 units each** — limiting default projects to just 100 searches/day. However, video metadata lookups (`videos.list`) cost only **1 unit and support batching 50 video IDs per call**, making metadata enrichment highly efficient.

For near-real-time monitoring, **YouTube RSS feeds** (`youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID`) update within minutes of new uploads, are completely free, require no authentication, and consume zero API quota. This is the recommended approach for detecting new content from monitored channels.

The **youtube-transcript-api** Python library provides timestamped captions without API keys, but YouTube actively blocks cloud provider IPs — residential proxies ($5–50/month) are required for server-side deployment. New videos appear in `videos.list` within minutes but may take **hours** to appear in search results.

### TikTok — Research API has significant latency issues

The TikTok Research API (which you have) provides video search, user info, comments, followers, and reposted/pinned videos. Key constraints: **1,000 requests/day** (up to 100K records), tokens expire every 2 hours, and — critically — **the video query endpoint uses archived data, not live data**. TikTok states accurate engagement statistics can take **up to 10 days to populate**, and researchers report persistent discrepancies. Data must be refreshed every 15 days per their policy.

For fresher data, **Bright Data TikTok** ($1/1K records via scraper API, $500/200K via datasets) achieves ~4.1s response times with 100% success rates. **Apify TikTok actors** offer pay-per-event pricing on a $49+/month platform. These supplement the Research API when near-real-time freshness matters more than official approval.

### Reddit — PRAW streaming is excellent for real-time

Post-2023, the Reddit API remains **free for non-commercial and academic use** (100 queries per minute via OAuth). Commercial use requires enterprise agreements starting at reportedly $12K+/year. **PRAW** (Python Reddit API Wrapper, v7.7.1+) is actively maintained and supports real-time streaming via `subreddit.stream.comments()` and `subreddit.stream.submissions()` with **seconds-to-minutes latency**.

**Pushshift is effectively dead for research** — now restricted to Reddit moderators only. **Arctic Shift** has emerged as the primary alternative, offering a web UI, API, and downloadable data dumps of historical posts and comments (22M subreddits as of January 2025). Academic researchers can also apply via **r/reddit4researchers** for formal research access with potentially higher limits.

### Telegram — real-time via Telethon, but watch for bans

**Telethon** (v1.42, actively maintained) is the strongest tool — a Python MTProto library providing real-time event handlers for new messages across public channels, access to full message history, views, forwards, reactions, and media files. It requires API credentials from my.telegram.org plus phone number authentication. Rate limits are enforced via `FloodWaitError` (the server specifies exact wait times). The primary risk is **account bans** for aggressive scraping patterns.

**TGStat API** (tgstat.com) provides complementary analytics — subscriber dynamics, cross-channel mention tracking, keyword monitoring — but coverage is strongest in **Russia/CIS regions**. **Pyrogram** offers similar functionality to Telethon but is classified as an inactive project by Snyk; Telethon is preferred for new projects.

### Bluesky — the most research-friendly platform by far

Bluesky is uniquely accessible. **All public data is available for free** through the AT Protocol, with no API keys required for read access via `public.api.bsky.app`. Rate limits are generous: **3,000 requests per 5 minutes**. The `searchPosts` endpoint supports Lucene query syntax with date ranges, author filtering, language filtering, and hashtag filtering.

The **Jetstream firehose** delivers every public event (posts, likes, reposts, follows, blocks) via WebSocket at **sub-second latency** with no authentication required. Connect to endpoints like `wss://jetstream1.us-east.bsky.network/subscribe` and filter by collection type or up to 10,000 specific user DIDs. Bandwidth is 4–8 GB/hour unfiltered (~56% smaller with zstd compression). **Tap**, Bluesky's official repository sync tool, handles full network backfill at 35–45K events/second.

Bluesky explicitly invites research use: "We consider it a failure of AT as an open network if any third party with adequate resources cannot backfill the entire network." The **atproto Python SDK** provides a full-featured client with firehose support. With ~28M monthly active users, Bluesky is the easiest and cheapest platform to integrate.

### Gab — Mastodon-compatible API with limited tooling

Since July 2019, Gab runs on a Mastodon fork, making its API essentially the **Mastodon API** documented at docs.joinmastodon.org. Key endpoints include public timeline, hashtag timeline, user statuses, search, and a real-time WebSocket streaming API. Authentication requires OAuth 2.0 with a Gab account. Rate limits follow Mastodon defaults (~300 requests/5 minutes). Gab blocks Israeli IPs and has restricted UK access.

Historical datasets exist from the **Pushshift Gab archive** (August 2016–December 2018, pre-Mastodon era) and the Fair & Wesslen ICWSM 2019 dataset (37M posts, 24.5M comments). Post-2019 data requires using the live API. Reliability is **low-medium** — Gab may modify Mastodon behavior without notice.

---

## News media: GDELT leads, with strong paid alternatives

### GDELT — the free backbone for global news monitoring

GDELT is the strongest free option for news data. It monitors **hundreds of thousands of sources** across 65 machine-translated languages, updating every **15 minutes** (GDELT 2.0). The GDELT DOC 2.0 API provides full-text search across a rolling 3-month window; the GEO API maps geographic mentions; the Context API provides sentence-level co-occurrence analysis. The entire dataset is also available on **Google BigQuery** for SQL-based analysis (free within BigQuery's 1 TB/month free tier).

GDELT provides event coding (300+ categories), Global Knowledge Graph connections (people, organizations, themes), tone analysis via 24 sentiment packages, and image analysis processing up to 1M images/day. Limitations include a June 2025 outage (recovered by July 2), no full article text (metadata and URLs only), and the 3-month API window without BigQuery.

### Paid news APIs compared

| Service | Coverage | Latency | Full text? | Cost | Best for |
|---------|----------|---------|-----------|------|----------|
| **Event Registry / NewsAPI.ai** | 150K+ outlets, 60+ languages | Near real-time | Yes | $90/mo (5K tokens) | Event clustering; NLP enrichment |
| **NewsAPI.org** | 150K+ sources, 14 languages | 24hr delay (free) / real-time (paid) | No | $449/mo (Business) | Simple integration; broad coverage |
| **NewsCatcher** | 70K–120K+ sources, 100+ countries | Minutes | Yes | ~$10,000/mo (enterprise) | Advanced NLP; embeddings; entity disambiguation |
| **Webz.io** | Millions of sites, 170+ languages | Near real-time | Yes | Contact sales | News + blogs + forums + dark web |
| **MediaCloud** | Curated collections, ~20 languages | Hours (RSS-based) | No | Free (research) | Academic media ecosystem studies |

**Event Registry** (same platform as NewsAPI.ai) offers the best value for research, providing AI-powered event clustering that groups articles about the same real-world event, full article content, NLP enrichment (entities, sentiment, categorization), and historical data back to 2014 — all starting at $90/month.

### RSS and Google News approaches

There is **no official Google News API** (deprecated years ago). Google News RSS feeds still work (`news.google.com/rss/search?q={query}`) but provide limited metadata with no date filtering or rate limit documentation. **SerpAPI Google News** scrapes results in real-time at standard SERP API pricing.

For custom RSS monitoring, **Miniflux** (Go, single binary, full REST API) and **FreshRSS** (PHP, handles 1M+ articles and 50K+ feeds) are the strongest self-hosted options. Feed polling typically runs at 5–60 minute intervals; **WebSub/PubSubHubbub** can deliver instant push notifications from compatible sources. The **Inoreader API** offers a managed alternative at $7.50/month (Pro tier) with 2,500 feed subscriptions, monitoring feeds for keyword tracking, and 10,000 API requests/day — though its 50-articles-per-request limit constrains high-volume pipelines.

---

## Web-at-large: backlink APIs, scraping infrastructure, and archives

### SEO/backlink APIs for tracking discourse spread

For tracking how content propagates across websites via links, **Majestic** is the specialist: its Fresh Index updates daily (~844B URLs), the Historic Index spans 19 years (21.7T+ URLs), and **Topical Trust Flow** categorizes linking sites across 800+ topics — directly relevant for mapping discourse spread across topical communities. API access starts at **$399.99/month** (100M analysis units).

**Ahrefs** offers the most powerful content monitoring via **Content Explorer** — a 16-billion-page content index searchable by keyword with filtering by date, referring domains, organic traffic, and domain rating. Its "News" tab visualizes brand/topic mentions over time, and the new **Brand Radar** (2025) tracks brand mentions in AI chatbot responses. However, API access requires the Enterprise plan at **$1,499/month**. Content Explorer is available from the Standard plan ($249/month) via the web UI.

**Moz API** is the most affordable option (from $5/month for 750 rows), providing Domain Authority, Page Authority, Spam Score, and backlink data. Its link index is smaller than Majestic or Ahrefs, but DA remains the industry-standard authority metric.

### Scraping infrastructure

**Bright Data** operates the largest commercial proxy network (150M+ residential IPs) with products ranging from raw proxies ($4–8/GB) to pre-built Web Scraper APIs ($1.50–2.50/1K requests) to ready-made datasets. Their **Web MCP** (August 2025) provides a free tier of 5,000 requests/month for AI agent integration. Enterprise-grade with 99.99% claimed uptime.

**Apify** offers 10,000+ pre-built "Actors" in its marketplace, from social media scrapers to news crawlers. Pricing is compute-based: free tier includes $5/month in credits; paid plans from $29/month. Actor quality varies significantly between official and community-built options — always check ratings, user counts, and last update dates.

### Web archives

**Common Crawl** provides petabyte-scale monthly web crawls (2.5–3B pages/crawl) freely on Amazon S3. Query via AWS Athena at ~$1.50 per full index scan. Excellent for longitudinal research but **not real-time** — most recent crawls are 1–3 months old.

The **Wayback Machine** archives 1+ trillion pages back to 1995. Its CDX API enables complex querying of all captures by URL, date range, and regex filters — ideal for tracking how specific pages change over time. Completely free, no API keys required. Rate limits are informal (~1 call/second for searches, ~30/second for page retrieval). Infrastructure has experienced recent fragility (November 2025 Cloudflare disruption, October 2024 security breach).

---

## Cross-platform monitoring: commercial tools vs. open-source stacks

### Commercial social listening platforms

For organizations with budget, commercial platforms offer the broadest cross-platform coverage:

**Brandwatch** (now part of Cision) provides firehose access to X/Twitter and Reddit, compliant Facebook/Instagram coverage, YouTube, 100M+ websites, and historical data back to **2010**. Features include AI sentiment analysis, 48 Boolean operators, image recognition (OCR, logo detection), and demographic analysis. Pricing starts around **$1,000+/month** with API access on enterprise plans.

**Meltwater** covers 300,000+ global news sources plus all major social platforms, podcasts (20,000+ US), and broadcast/print monitoring. Its heritage is news monitoring — it remains strongest for traditional media. Typical cost is **$15,000–$25,000/year** (range: $6K–$100K+), annual contracts only.

**Sprinklr** covers 30+ channels with firehose access to 10+ and monitors 400,000+ media sources. It offers the broadest channel coverage but is designed for Fortune 500 brands, with enterprise-only pricing and a steep learning curve.

**BuzzSumo** fills a specific niche: tracking content performance and sharing metrics across the web. At **$199–$999/month**, it shows which content goes viral, identifies influencers, and measures social engagement — complementary to conversation-monitoring tools. API access requires the Suite ($499/mo) or Enterprise ($999/mo) plan.

### Open-source research tools

**4CAT** (Capture and Analysis Toolkit) from the University of Amsterdam is the most capable open-source option, supporting direct collection from Bluesky, Telegram, 4chan, and 8chan, plus import from Zeeschuimer captures and CSV files. It runs as a Docker container with a web interface and provides built-in analysis tools (frequency charts, network analysis, word embeddings). Actively developed (v1.47, Spring 2025).

**Zeeschuimer**, also from the Digital Methods Initiative, is a Firefox extension that captures social media API responses as you browse — supporting TikTok, Instagram, X/Twitter, LinkedIn, Gab, Truth Social, Pinterest, and more. Data exports as NDJSON or uploads directly to 4CAT. The limitation is manual browsing scale.

**Minet** from Sciences Po médialab is a Python CLI tool consolidating 10+ years of webmining practices: multithreaded fetching, HTML extraction, and API integration with YouTube, Twitter, Facebook, and MediaCloud. It is designed for fault-tolerant, long-running collection jobs and remains actively maintained (latest release December 2025).

---

## Architectural recommendations for cross-platform topic propagation tracking

The optimal architecture combines free/low-cost high-quality sources as the backbone with targeted paid services for gap-filling:

**Real-time firehose layer**: Bluesky Jetstream (free, sub-second), Reddit PRAW streaming (free, seconds), and Telegram Telethon event handlers (free, real-time) form the lowest-latency tier. These three deliver data as events occur, cost nothing, and require only compute infrastructure.

**Near-real-time polling layer**: GDELT DOC API (free, 15-minute updates), YouTube RSS feeds + Data API (free, minutes), custom RSS aggregator via Miniflux/FreshRSS (free, 5–60 minutes), and Google Autocomplete via SerpAPI or Serper.dev ($0.30–$25/1K) cover news and search signal with minimal lag.

**Periodic enrichment layer**: Google SERP data via Serper.dev or DataForSEO ($0.30–$2/1K), TikTok Research API (free but 10-day engagement lag), Majestic or Ahrefs for backlink-based discourse mapping ($250–$1,500/mo), and X/Twitter via third-party APIs like TwitterAPI.io ($0.15/1K tweets) or the official Pro tier ($5,000/mo for streaming).

**Facebook/Instagram path**: Apply for Meta Content Library access through ICPSR if your institution qualifies. If not, Bright Data ($1.50–$2.50/1K records) is the most reliable alternative under current legal precedent.

**Gab**: Mastodon-compatible REST + Streaming API with authenticated account (free, near-real-time). Low volume platform; minimal infrastructure needed.

The total monthly cost for a comprehensive monitoring stack ranges from approximately **$100–500/month** (using primarily free APIs with selective paid SERP/Twitter access) to **$5,000–10,000/month** (with official X/Twitter Pro access, Ahrefs Enterprise, and a commercial news API). The free-tier-heavy approach sacrifices some X/Twitter coverage and Facebook/Instagram access but captures the majority of cross-platform signal at a fraction of the cost.

## Conclusion

The cross-platform data collection landscape has undergone a structural shift since 2023. The collapse of free Twitter academic access, CrowdTangle's shutdown, and Pushshift's restriction have eliminated three pillars of social media research infrastructure. Yet the ecosystem has adapted: **Bluesky's radical openness** provides a model of what research-friendly platform access looks like, **third-party scraping services** have filled gaps with legal backing from favorable court rulings, and **GDELT remains an unmatched free resource** for global news monitoring. The most underappreciated finding is the cost disparity in X/Twitter data — official API access at $5,000–$42,000/month versus third-party alternatives at $0.15–$0.20 per thousand posts, with courts consistently ruling in favor of the latter for public data. For a topic propagation tracker, the key strategic insight is to build on the platforms that welcome research (Bluesky, Reddit, YouTube, GDELT) as the real-time backbone, layer in paid services selectively for the walled-garden platforms, and maintain flexibility to shift collection methods as the API landscape continues to evolve.