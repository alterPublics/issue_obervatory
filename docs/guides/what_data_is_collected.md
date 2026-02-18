# What Data Is Collected

**Created:** 2026-02-16
**Last updated:** 2026-02-17

This guide explains, in plain language, what data The Issue Observatory collects from each platform (called an "arena"), how it targets Danish content, what is deliberately excluded, and what privacy protections are applied. It is written for researchers who use the system, not developers who build it.

---

## Table of Contents

1. [The Universal Content Record](#the-universal-content-record)
2. [Privacy Protections Applied to All Data](#privacy-protections-applied-to-all-data)
3. [Search Engines](#search-engines)
4. [Social Media Platforms](#social-media-platforms)
5. [News and Press Release Sources](#news-and-press-release-sources)
6. [Web Archive and Index Sources](#web-archive-and-index-sources)
7. [Backlink and Domain Analysis](#backlink-and-domain-analysis)
8. [Summary Table](#summary-table)

---

## The Universal Content Record

Every piece of content collected by any arena is transformed into the same standardized format before it is stored. This means that a tweet, a Reddit post, an RSS article, and a Google Search result all end up with the same set of fields, making cross-platform comparison straightforward.

The core fields in every record are:

- **platform** -- Which service the content came from (e.g., "google", "reddit", "bluesky").
- **arena** -- Which collector module retrieved it (e.g., "google_search", "rss_feeds").
- **platform_id** -- The original unique identifier assigned by the source platform.
- **content_type** -- What kind of content it is (e.g., "search_result", "post", "article", "press_release", "autocomplete_suggestion").
- **text_content** -- The main text body (post text, article summary, search snippet, etc.).
- **title** -- A title or headline, if available.
- **url** -- A link back to the original content on the source platform.
- **language** -- The detected or declared language of the content (e.g., "da" for Danish).
- **published_at** -- When the content was originally published.
- **collected_at** -- When The Issue Observatory retrieved it.
- **author_display_name** -- The public display name of the author (e.g., a username or channel name).
- **pseudonymized_author_id** -- A privacy-safe identifier for the author (see Privacy Protections below).
- **Engagement counts** -- Where available: views, likes, shares/reposts, and comment counts.
- **media_urls** -- Links to any images or videos attached to the content (the media files themselves are not downloaded unless specifically configured).
- **raw_metadata** -- The complete original data from the source API, preserved for advanced analysis.
- **content_hash** -- A fingerprint of the text content used to detect duplicates across collection runs.

Not every arena can fill in every field. When a field is not available from a particular source, it is left empty (null). For example, GDELT does not provide author information, and Google Autocomplete does not have URLs or engagement metrics.

---

## Privacy Protections Applied to All Data

The system applies two key privacy protections to every record:

**Pseudonymized author identifiers.** The system never stores a direct link between a platform username and collected content in its primary identifier field. Instead, it computes a one-way hash: `SHA-256(platform + user_id + project_salt)`. This means the same author always maps to the same pseudonym within a project, enabling longitudinal analysis, but the pseudonym cannot be reversed to recover the original username without the project salt. The original platform username is still present in `author_platform_id` and `author_display_name` for records where the source API provides it; the pseudonymized ID provides an additional layer for analyses that do not require identifying individuals.

**Content deduplication hashes.** Each record receives a SHA-256 hash of its normalized text content. This detects when the same content is collected multiple times (across runs or across arenas) without requiring full-text comparison.

**Data retention.** All collected records are automatically marked for deletion after 730 days (2 years) by default, in compliance with GDPR Article 5(1)(e) purpose limitation and Databeskyttelsesloven section 10 requirements for university research projects.

---

## Search Engines

### Google Search

**What it monitors:** Google Search results for Danish-language queries. Every search is scoped to Denmark (`gl=dk`, `hl=da`), so results reflect what a Danish user would see.

**What is collected for each result:**
- Title of the search result
- URL (the link Google points to)
- Snippet (the short text preview Google shows below the title)
- Position/rank in the search results
- Date (when available, typically for news-type results)

**What is NOT collected:**
- The full content of the linked web page (only the snippet Google provides)
- Ads or sponsored results
- "People also ask" or knowledge panel content
- Any data about the person performing the search

**Danish targeting:** Every query includes `gl=dk` (country=Denmark) and `hl=da` (language=Danish).

**How actors work:** When you specify actor domains (e.g., "dr.dk"), they are converted to `site:dr.dk` queries, returning only Google results from that domain.

**Tiers available:** MEDIUM (Serper.dev, ~$0.30 per 1,000 queries) and PREMIUM (SerpAPI, higher cost and rate limits). No free tier.

**Example record:** A search for "sundhedsreform" might return a record with title "Ny sundhedsreform vedtaget i Folketinget", URL "https://www.dr.dk/nyheder/...", and snippet "Regeringen har i dag vedtaget en ny sundhedsreform som..."

---

### Google Autocomplete

**What it monitors:** Google's autocomplete suggestions -- the dropdown predictions that appear as you type a search query.

**What is collected for each suggestion:**
- The suggestion text itself (e.g., typing "klima" might yield "klimaforandringer", "klimaaftale 2025", etc.)
- The input query that triggered the suggestion
- Rank position (1st suggestion, 2nd, etc.)
- Relevance score (available only on paid tiers)

**What is NOT collected:**
- Search results (this arena only captures the suggestions, not what you would see after pressing Enter)
- Any user behavior or click data
- Personalized suggestions (the system uses a clean, non-logged-in session)

**Danish targeting:** Queries include `gl=dk` and `hl=da`.

**Actor-based collection:** Not supported. Autocomplete suggestions are query-based only.

**Tiers available:** FREE (public Google Suggest endpoint, limited to approximately 1 request per second), MEDIUM (Serper.dev), PREMIUM (SerpAPI).

**Example record:** For the input "indvandring", a suggestion record might contain the text "indvandring til danmark statistik" at rank position 3.

---

## Social Media Platforms

### Bluesky

**What it monitors:** Public posts on Bluesky, the decentralized social network built on the AT Protocol.

**What is collected for each post:**
- Full post text
- AT Protocol URI (unique post identifier)
- Author handle and DID (decentralized identifier)
- Like count, repost count, reply count
- Language (from the post's declared language tags)
- Embedded media URLs (images, links)
- Creation timestamp

**What is NOT collected:**
- Private or followers-only posts (Bluesky posts are public by default)
- Direct messages
- User profile details beyond handle and display name
- Full thread context (individual posts are collected, not threaded conversations)

**Danish targeting:** For term-based collection, the search query includes a `lang:da` parameter to request Danish-language posts. For actor-based collection (fetching an actor's public feed via `getAuthorFeed`), client-side language filtering excludes posts not tagged as Danish. Posts with no declared language are included. Researchers should be aware that some actor-based results may include non-Danish content if the author did not declare a language tag.

Additionally, the system can subscribe to the Bluesky firehose (Jetstream) for real-time streaming of all posts, with client-side language filtering. Note: Jetstream streaming requires the `websockets` Python package, which is not installed by default. Install it with `pip install websockets` before enabling streaming.

**How actors work:** You provide Bluesky handles or DIDs; the system fetches their public feed using the `getAuthorFeed` endpoint.

**Tiers available:** FREE only. No credentials needed. Rate limit: 600 requests per minute.

**Example record:** A post by a Danish journalist discussing "folkeskolen" would appear with their handle, the full post text, and engagement counts.

---

### Reddit

**What it monitors:** Posts and optionally top-level comments in Danish-relevant subreddits and search results.

**What is collected for each post:**
- Title and self-text (the body of text posts)
- Score (upvotes minus downvotes), upvote ratio
- Number of comments
- Subreddit name
- Author username
- Flair text (user-assigned or moderator-assigned labels)
- Permalink
- Number of crossposts
- Creation timestamp

**What is collected for comments (when enabled):**
- Comment text body
- Score
- Author
- Whether it is a top-level comment

**What is NOT collected:**
- Downvote counts (Reddit does not expose exact downvote numbers)
- Private subreddit content
- Direct messages or chat
- Removed or deleted posts (they may appear briefly before removal)
- Full comment trees (only top-level comments are collected by default)

**Danish targeting:** The system searches within a predefined set of Danish subreddits: r/Denmark, r/danish, r/copenhagen, and r/aarhus. There is no language filter -- subreddit scoping is the primary Danish-content strategy.

**How actors work:** Actor IDs are treated as subreddit names; the system fetches new posts from those subreddits.

**Tiers available:** FREE only. Requires Reddit API credentials (client ID and client secret from a registered Reddit "script" application). Rate limit: 90 requests per minute.

**Example record:** A post in r/Denmark titled "Hvad synes I om den nye skatteaftale?" with 247 upvotes and 89 comments.

---

### X (Twitter)

**What it monitors:** Public tweets, retweets, replies, and quote tweets.

**What is collected for each tweet:**
- Full tweet text
- Like count, retweet count, reply count, view/impression count
- Author username and display name
- Tweet type (original tweet, retweet, reply, quote tweet)
- Conversation ID (for threading)
- Entities (URLs, hashtags, mentions extracted by the platform)
- Context annotations (topic labels assigned by X)
- Creation timestamp

**What is NOT collected:**
- Protected/private account tweets
- Direct messages
- Twitter Spaces audio
- Ad/promoted tweet metadata
- Follower/following lists

**Danish targeting:** Every search query is appended with `lang:da` to filter for Danish-language tweets.

**How actors work:** Actor IDs are X usernames; the system fetches their timeline.

**Tiers available:** MEDIUM (TwitterAPI.io, ~$0.15 per 1,000 tweets) and PREMIUM (X API v2 Pro with full archive access). No free tier.

**Example record:** A tweet by a Danish politician reading "Vi skal investere mere i den gronne omstilling" with 1,203 likes and 89 retweets.

---

### TikTok

**What it monitors:** Public TikTok videos via the TikTok Research API (requires approved academic access).

**What is collected for each video:**
- Video description text
- Voice-to-text transcript (when available -- TikTok's own speech-to-text output)
- View count, like count, share count, comment count
- Region code
- Hashtag names
- Music/sound ID
- Creation timestamp

**What is NOT collected:**
- The video file itself (only metadata and text)
- Private or friends-only videos
- Comments on videos
- User profile details beyond basic identifiers
- Duet/stitch source information

**Danish targeting:** The API filter `region_code=DK` restricts results to videos posted from Denmark.

**Important caveat:** TikTok engagement metrics (views, likes, shares) have an approximately 10-day accuracy lag. Numbers collected within 10 days of posting may be significantly lower than final values.

**How actors work:** Actor IDs are TikTok usernames; the system queries their videos through the Research API.

**Tiers available:** FREE only. Requires TikTok Research API credentials (client key and client secret). Rate limit: 1,000 requests per day, maximum 100 results per request. Maximum date range per query is 30 days.

**Example record:** A TikTok video with description "Koebenhavns bedste kaffesteder #kobenhavn #kaffe" with 45,000 views and 2,300 likes, region_code "DK".

---

### YouTube

**What it monitors:** Public YouTube videos, collected via the YouTube Data API v3 and channel RSS feeds.

**What is collected for each video:**
- Video title
- Description text
- View count, like count, comment count
- Channel name and channel ID
- Publication date
- Video ID
- Thumbnail URL
- Video category (e.g., "News & Politics", "Education")
- Default audio language and default language (when declared by the uploader)

**What is NOT collected:**
- Video files (only metadata and text)
- Comments on videos (only comment counts)
- Subscriber counts
- Private or unlisted videos
- Share count (not exposed by the YouTube API)
- Channel-level analytics

**Danish targeting:** Every search query includes `relevanceLanguage=da` and `regionCode=DK`, instructing the API to prioritize results relevant to Danish-speaking users in Denmark.

**How actors work:** Actor IDs are YouTube channel IDs (format: `UC...`). The system first polls the channel's public RSS feed (which returns up to 15 recent uploads at zero API quota cost), then enriches the discovered videos with full metadata via the `videos.list` API endpoint.

**Tiers available:** FREE only. Requires a YouTube Data API v3 key (created in Google Cloud Console). The API has a strict daily quota of 10,000 units per key. The system uses an RSS-first strategy to minimize quota consumption: channel RSS feeds cost zero quota units, while `search.list` costs 100 units per call and `videos.list` costs 1 unit per batch of up to 50 videos. Multiple API keys can be pooled to multiply the effective daily quota.

**Example record:** A DR Nyheder YouTube video titled "Ny klimaaftale: Hvad betyder den for dig?" with 12,400 views, 310 likes, and 47 comments.

---

### Threads

**What it monitors:** Public posts on Meta's Threads platform.

**What is collected for each post:**
- Post text
- Timestamp
- Media type (text, image, video, carousel)
- Whether the post is a reply
- Permalink
- Engagement metrics: views, likes, replies, reposts, quotes -- BUT these are only available for posts authored by the account whose access token is being used. For other accounts, engagement data is not returned by the Threads API.

**What is NOT collected:**
- Private account posts
- Direct messages
- Full thread/conversation trees
- Engagement metrics for accounts other than the token holder's own posts

**Danish targeting:** The Threads API does not support language or country filtering. Danish content is collected by targeting known Danish accounts (actor-based collection). Keyword search falls back to collecting from known accounts and filtering client-side.

**How actors work:** Actor IDs are Threads user IDs; the system fetches their public posts. This is the primary collection method for Threads.

**Tiers available:** FREE (actor-based collection via Threads API with long-lived access tokens). MEDIUM tier (Meta Content Library) is defined but not yet implemented.

**Important caveat:** Access tokens expire after 60 days and must be refreshed. The system auto-refreshes at 55 days.

---

### Facebook

**What it monitors:** Public Facebook posts, primarily from pages and public groups.

**What is collected for each post:**
- Post text/content
- Like/reaction count, comment count, share count
- Author/page information
- Post type
- Media URLs
- Creation timestamp

**What is NOT collected:**
- Private profile posts
- Posts in closed or secret groups
- Messenger conversations
- Comments on posts (only comment counts)
- Ad content or ad targeting data

**Danish targeting:** The Bright Data dataset trigger includes `country=DK` to scope collection to Danish content.

**How actors work:** Actor IDs are Facebook page URLs or IDs; the system triggers Bright Data dataset collection scoped to those pages.

**Tiers available:** MEDIUM (Bright Data Datasets, ~$2.50 per 1,000 records). PREMIUM tier (Meta Content Library) is defined but not yet implemented -- it requires a separate application to Meta.

**Important caveat:** Collection is asynchronous. The system triggers a dataset job, polls for completion (up to 20 minutes), then downloads results. There is inherent latency.

---

### Instagram

**What it monitors:** Public Instagram posts, Reels, and IGTV content.

**What is collected for each post:**
- Caption text
- Like count, comment count
- Author/account information
- Media type (photo, video, carousel, Reel)
- Media URLs (thumbnails, not full-resolution media)
- Hashtags
- Creation timestamp

**What is NOT collected:**
- Stories (ephemeral, disappear after 24 hours)
- Private account posts
- Direct messages
- Comments on posts (only comment counts)
- Shopping/product tag details
- Reel audio/music metadata

**Danish targeting:** Instagram has no native language or country filter. Danish content is identified through three methods: (1) targeting known Danish accounts, (2) searching Danish-language hashtags (#dkpol, #danmark, #kobenhavn, #dkmedier, #danmarksnatur, #dkkultur, #danskepolitikere), and (3) client-side language detection on caption text.

**How actors work:** Actor IDs are Instagram usernames or profile URLs; the system collects their posts via Bright Data.

**Tiers available:** MEDIUM (Bright Data Scraper, ~$1.50 per 1,000 records). PREMIUM tier (Meta Content Library) is defined but not yet implemented.

---

### Telegram

**What it monitors:** Public Telegram channels only. Not private groups, not secret chats, not bots.

**What is collected for each message:**
- Message text
- View count, forward count, reply count
- Reaction counts (summed across all reaction types)
- Channel name and ID
- Whether the message was forwarded from another channel (and the source)
- Media type indicator (photo, video, document -- but media files are not downloaded)
- Creation timestamp

**What is NOT collected:**
- Private group messages
- Secret chat content
- Bot interactions
- Media file content (only metadata about attached media)
- User messages in group chats (only channel posts)

**Danish targeting:** No language filter is available. The system monitors a predefined list of Danish public channels: dr_nyheder, tv2nyhederne, berlingske, politiken_dk, bt_dk, informationdk. Additional channels can be added via actor configuration.

**How actors work:** Actor IDs are Telegram channel usernames; the system joins and reads messages from those public channels.

**Tiers available:** FREE only. Requires Telegram API credentials (api_id, api_hash, and a session string generated through one-time phone verification).

**Important caveat:** Telegram enforces aggressive flood-wait limits. If the system makes too many requests, it may be forced to wait minutes or even hours before resuming. The collector handles this automatically.

---

### Gab

**What it monitors:** Public posts ("gabs") on the Gab social network.

**What is collected for each post:**
- Post text (HTML stripped to plain text)
- Favourite count, reblog count, reply count
- Author account information
- Media attachment URLs
- Language (as declared by the platform)
- Creation timestamp

**What is NOT collected:**
- Private or followers-only posts
- Direct messages
- Group content (unless publicly accessible)
- Reblog/boost chains (reblogs are normalized to the original post)

**Danish targeting:** Gab has no language filter. Danish content on Gab is expected to be very low volume. The system collects based on search terms and known accounts.

**How actors work:** Actor IDs are Gab account IDs; the system fetches their public statuses.

**Tiers available:** FREE only. Uses the public Gab API (Mastodon-compatible). Credentials (access token) are required.

---

### LinkedIn

**What it monitors:** LinkedIn does not have a public API suitable for research data collection. The Issue Observatory does not collect directly from LinkedIn.

**What is available instead:** A manual import endpoint exists for uploading LinkedIn data exported through other means (e.g., personal data downloads or authorized third-party tools). This is an import-only feature, not automated collection.

---

## News and Press Release Sources

### Danish RSS Feeds

**What it monitors:** News articles from 27+ Danish media RSS feeds, covering the major national outlets.

**Sources included:**
- DR (9 national feeds + 8 regional feeds covering Nordjylland, Midtjylland, Syddanmark, Fyn, Sjaelland, Hovedstaden, Bornholm, and Trekantomraadet)
- TV2 (national news)
- BT, Politiken, Berlingske, Ekstra Bladet, Information, Jyllands-Posten (Note: Jyllands-Posten's RSS feed availability is uncertain as of 2026. JP has shifted toward app-first content delivery, and this RSS URL may return no data. Check the arena health monitor for current feed status.)
- Nordjyske, Fyens Stiftstidende
- Borsen (business/finance)
- Kristeligt Dagblad

**What is collected for each article:**
- Headline/title
- Summary text (HTML tags stripped, original structure in raw_metadata)
- URL to the full article
- Author name (when the RSS feed includes it)
- Publication date
- Tags/categories
- Media URLs from RSS enclosures (e.g., thumbnail images)

**What is NOT collected:**
- Full article body text (RSS feeds typically provide only a summary or excerpt)
- Paywalled content behind the link
- Reader comments
- Article view or share counts

**Danish targeting:** All feeds are from Danish media outlets. All content is assumed to be Danish (language is hardcoded to "da").

**How actors work:** Actor IDs are outlet slug prefixes (e.g., "dr", "tv2", "politiken"); the system selects only feeds matching those prefixes.

**Tiers available:** FREE only. No credentials needed. The system uses conditional GET requests (ETag and If-Modified-Since headers) to avoid re-downloading unchanged feeds.

**Update frequency:** Designed for hourly polling via the beat scheduler. Up to 10 feeds are fetched concurrently.

---

### Via Ritzau (Press Releases)

**What it monitors:** Press releases distributed through Via Ritzau, the primary Danish press release distribution service. Sources include Danish government ministries, companies, NGOs, police departments, and other organizations.

**What is collected for each press release:**
- Headline
- Full body text (HTML stripped, original HTML preserved in raw_metadata)
- Publisher name and ID
- Image URLs
- Channel/category classifications
- Contact information listed in the release
- Attachment references
- Publication timestamp

**What is NOT collected:**
- Attached documents (PDFs, etc.) -- only references/URLs are stored
- Distribution metrics (how many journalists received it)
- Follow-up corrections unless published as separate releases

**Danish targeting:** The API filter `language=da` is applied to every request.

**How actors work:** Actor IDs are Via Ritzau publisher IDs; the system fetches releases from those specific publishers.

**Tiers available:** FREE only. The Via Ritzau JSON API v2 is fully public and requires no credentials.

**Example record:** A press release from Sundhedsministeriet titled "Ny aftale om lagemangel i ydomraaderne" with full body text, images, and ministry contact details.

---

### Event Registry (NewsAPI.ai)

**What it monitors:** Global news articles with strong Danish coverage. Event Registry indexes articles from thousands of news sources worldwide and provides full article text, NLP enrichments, and event clustering.

**What is collected for each article:**
- Full article body text (not just a summary)
- Title
- Source name and URL
- Publication date
- Author (when available)
- NLP-derived enrichments stored in raw_metadata: detected concepts, categories, sentiment, event clusters, linked entities

**What is NOT collected:**
- Reader comments
- Social sharing counts
- Paywalled article content that Event Registry itself cannot access
- Original article formatting or embedded media

**Danish targeting:** Queries use `lang=dan` (ISO 639-3 code for Danish) and `sourceLocationUri` set to the Wikipedia URI for Denmark, ensuring results come from Danish-language sources located in Denmark.

**How actors work:** Actor IDs are source URIs (news outlet identifiers in Event Registry's format); the system restricts queries to those sources.

**Tiers available:** MEDIUM ($90/month, 5,000 API tokens) and PREMIUM ($490/month, 50,000 API tokens). The system tracks token consumption and warns at 20% remaining, stopping collection at 5% remaining.

**Example record:** A Berlingske article about "EU's nye handelspolitik" with full body text, detected concepts ["EU", "handelspolitik", "Danmark"], and sentiment score.

---

### GDELT (Global Database of Events, Language, and Tone)

**What it monitors:** Global news coverage as indexed by the GDELT Project. GDELT monitors news media worldwide and provides article metadata, tone analysis, and event coding. Coverage of Danish sources is partial.

**What is collected for each article reference:**
- URL of the article
- Title
- Publication date (called "seendate" in GDELT)
- Source domain
- Language
- Source country
- Tone score (positive/negative sentiment measure)
- Social image URL (representative image)

**What is NOT collected:**
- Full article text (GDELT provides only metadata and URLs)
- Author information
- Engagement metrics
- Comments or reader reactions
- Articles older than 3 months (GDELT DOC API 2.0 has a rolling 3-month window)

**Danish targeting:** Two queries are run per search term: one filtered by `sourcecountry:DA` (FIPS code for Denmark) and another by `sourcelang:danish`. Results are deduplicated by URL.

**Important caveat:** GDELT's Danish coverage has approximately 55% accuracy. Many articles are machine-translated or mis-attributed. GDELT is best used as a supplementary source, not a primary one.

**Actor-based collection:** Not supported. GDELT only supports keyword-based queries.

**Tiers available:** FREE only. No credentials needed. Rate limit: 1 request per second.

---

## Web Archive and Index Sources

### Wayback Machine (Internet Archive)

**What it monitors:** Historical snapshots of web pages archived by the Internet Archive. The system queries the CDX (Capture/Digital Index) API for metadata about archived pages.

**What is collected for each capture record:**
- Original URL of the archived page
- Capture timestamp (when the Internet Archive saved the snapshot)
- MIME type of the captured content
- HTTP status code at time of capture
- Content digest (hash for deduplication)
- Content length
- Wayback Machine playback URL (link to view the archived version)

**What is NOT collected:**
- The actual content of the archived web page (only metadata about the capture)
- Pages that were not archived by the Internet Archive
- Content behind login walls or robots.txt exclusions

**Danish targeting:** Queries are scoped to `*.dk/*` domains, returning only captures of websites registered under the Danish .dk top-level domain.

**How actors work:** Actor IDs are domain names (e.g., "dr.dk"); the system queries captures for those specific domains.

**Tiers available:** FREE only. No credentials needed. Rate limit: 1 request per second (courtesy limit).

**Use case:** Useful for tracking how Danish media websites changed over time, verifying that cited sources existed at a particular date, or studying the evolution of organizational web presence.

---

### Common Crawl

**What it monitors:** The Common Crawl index, a freely available archive of web crawl data. The system queries the Common Crawl Index API for metadata about crawled pages.

**What is collected for each index record:**
- URL of the crawled page
- Crawl timestamp
- WARC file location (filename, byte offset, content length) for potential future content retrieval
- Detected language
- HTTP status code
- MIME type

**What is NOT collected:**
- The actual page content from WARC files (only index metadata is retrieved in Phase 2)
- Pages not included in Common Crawl's periodic crawls
- Dynamic or JavaScript-rendered content that Common Crawl's crawler could not capture

**Danish targeting:** Results are filtered to the `.dk` top-level domain.

**Actor-based collection:** Actor IDs are domain names; the system queries the index for those domains.

**Tiers available:** FREE only. No credentials needed.

**Use case:** Useful for broad surveys of the Danish web landscape, identifying which Danish sites exist in the crawl archive, and planning targeted content retrieval.

---

## Backlink and Domain Analysis

### Majestic

**What it monitors:** The link structure of the web -- which websites link to which other websites. Majestic is a specialized backlink and domain authority analysis service.

**What is collected:**

For domain-level metrics:
- Trust Flow (quality score based on the trustworthiness of linking sites)
- Citation Flow (quantity score based on the number of linking sites)
- Total external backlinks
- Total referring domains
- Referring domains by subnet and IP diversity

For individual backlinks:
- Source URL (the page containing the link)
- Target URL (the page being linked to)
- Anchor text (the clickable text of the link)
- Link discovery date
- Whether the link is still live
- Source Trust Flow and Citation Flow

**What is NOT collected:**
- Page content of linking or linked pages
- Traffic or visitor data
- Social media sharing metrics
- SEO rankings or keyword positions

**Danish targeting:** No language filter. Danish focus is achieved by querying domains of interest (e.g., Danish media outlets, political party websites, organization sites).

**How actors work:** Actor IDs are domain names; the system fetches domain metrics and backlinks for those domains.

**Tiers available:** PREMIUM only ($399.99/month for Majestic API access).

**Use case:** Useful for studying the link ecology of Danish public discourse -- which sources are most cited, how information flows between organizations, and how domain authority correlates with influence.

---

## Summary Table

| Arena | Content Type | Danish Filter | Free Tier | Paid Tier | Credentials Needed | Author Data | Engagement Data | Full Text |
|-------|-------------|---------------|-----------|-----------|-------------------|-------------|-----------------|-----------|
| Google Search | Search results | gl=dk, hl=da | No | MEDIUM, PREMIUM | Yes (API key) | No | No | Snippet only |
| Google Autocomplete | Suggestions | gl=dk, hl=da | Yes | MEDIUM, PREMIUM | No (free) / Yes (paid) | No | No | Suggestion text |
| Bluesky | Posts | lang:da | Yes | -- | No | Yes | Yes | Yes |
| Reddit | Posts, comments | Subreddit scoping | Yes | -- | Yes (app credentials) | Yes | Partial (score, no downvotes) | Yes |
| X/Twitter | Tweets | lang:da | No | MEDIUM, PREMIUM | Yes (API key) | Yes | Yes | Yes |
| TikTok | Video metadata | region_code=DK | Yes | -- | Yes (Research API) | Yes | Yes (10-day lag) | Description + transcript |
| YouTube | Video metadata | relevanceLanguage=da, regionCode=DK | Yes | -- | Yes (API key) | Yes | Yes (views, likes) | Description only |
| Threads | Posts | Actor-based only | Yes | MEDIUM (stub) | Yes (access token) | Yes | Limited | Yes |
| Facebook | Posts | country=DK | No | MEDIUM | Yes (Bright Data) | Yes | Yes | Yes |
| Instagram | Posts | Hashtag-based | No | MEDIUM | Yes (Bright Data) | Yes | Yes | Caption only |
| Telegram | Channel messages | Channel selection | Yes | -- | Yes (API credentials) | Channel only | Yes | Yes |
| Gab | Posts | None | Yes | -- | Yes (access token) | Yes | Yes | Yes |
| RSS Feeds | Articles | Danish outlets | Yes | -- | No | Sometimes | No | Summary only |
| Via Ritzau | Press releases | language=da | Yes | -- | No | Publisher info | No | Yes |
| Event Registry | Articles | lang=dan, Denmark | No | MEDIUM, PREMIUM | Yes (API key) | Sometimes | No | Yes |
| GDELT | Article metadata | sourcecountry:DA | Yes | -- | No | No | No | No (URL only) |
| Wayback Machine | Capture metadata | *.dk domains | Yes | -- | No | No | No | No (metadata only) |
| Common Crawl | Index metadata | .dk TLD | Yes | -- | No | No | No | No (metadata only) |
| Majestic | Backlinks, metrics | Domain selection | No | PREMIUM | Yes (API key) | No | No | No |

---

## What Is Deliberately Not Collected

Across all arenas, the following categories of data are never collected:

- **Private messages or direct messages** on any platform.
- **Content from private, closed, or secret groups** (only publicly accessible content).
- **User passwords, email addresses, or other account credentials** of platform users.
- **IP addresses or device identifiers** of content authors.
- **Advertising or promoted content metadata** (ad targeting, spend, audience).
- **Full media files** (videos, high-resolution images) -- only URLs/thumbnails are stored by default.
- **Personally identifying information beyond what is publicly posted** by the user themselves.

The system is designed for public discourse research. It collects only publicly available content and applies pseudonymization to author identifiers to minimize re-identification risk while preserving analytical utility.
