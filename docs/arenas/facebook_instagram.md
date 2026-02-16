# Arena Research Brief: Facebook/Instagram

**Created**: 2026-02-16
**Last updated**: 2026-02-16
**Status**: Ready for implementation
**Phase**: 2 (Task 2.3, High priority)
**Arena path**: `src/issue_observatory/arenas/social_media/facebook/` and `src/issue_observatory/arenas/social_media/instagram/`

---

## 1. Platform Overview

Facebook and Instagram are the two largest social media platforms in Denmark by usage. Facebook reaches 84% of Danes aged 16-74; Instagram reaches 56%. Together they dominate Danish social media discourse, particularly for news consumption (32% of Danes get news from Facebook, 19% from Instagram). Both platforms are owned by Meta and share data infrastructure, which is why this brief covers them jointly -- the Meta Content Library provides unified access to both, and the fallback strategy (Bright Data) covers both through the same vendor.

**Role in Danish discourse**: Facebook is the primary social media platform for Danish public discourse across all age groups, though daily use has declined from 68% (2022) to ~60% (2024) among 16-74-year-olds. Facebook groups host substantial community discussions on local politics, parenting, neighborhood issues, and public services. Facebook Pages of media outlets, politicians, and organizations are major distribution channels. Instagram is the second-largest platform and increasingly important for visual storytelling, news consumption among younger Danes, and influencer-driven discourse. Reels have become a significant content format.

**Access model**: CrowdTangle was shut down on August 14, 2024. Its replacement -- the Meta Content Library (MCL) -- is the premium path but requires institutional application. Bright Data provides a commercial scraping alternative for organizations that do not qualify for or have not yet received MCL access.

---

## DECISION POINT: Meta Content Library vs. Bright Data

This arena has a critical decision point at the start of Phase 2 (as specified in the Implementation Plan):

> **Confirm Meta Content Library application status. If not approved within 2 weeks of Phase 2 start, proceed with Bright Data fallback for Facebook/Instagram.**

### Path A: Meta Content Library (Premium Tier)

**When to choose**: MCL access is approved through ICPSR. The project's institutional affiliation qualifies (academic or non-profit). IRB approval is obtained.

**Advantages**: Compliant access to all public posts on Facebook, Instagram, and Threads. 100+ searchable fields. Post view counts (CrowdTangle never had this). Text-in-image search. Event-level data. Near-real-time access. No legal risk from scraping.

**Disadvantages**: $371/month per team + $1,000 one-time setup. Cleanroom environment required (no raw data export for posts below follower thresholds). Weekly 500,000-result retrieval cap. Application process takes weeks. Cannot export CSV for Threads data. Restricted to systemic risk or public interest research.

### Path B: Bright Data (Medium Tier)

**When to choose**: MCL application is rejected, delayed beyond 2 weeks into Phase 2, or the project does not qualify for MCL access.

**Advantages**: No application process. Immediate access. Per-use pricing. No cleanroom requirement. Data can be stored locally.

**Disadvantages**: Scraping-based -- Meta's Terms of Service prohibit it (though Meta lost its lawsuit against Bright Data in 2024). GDPR compliance burden is higher without Meta's institutional endorsement. Data quality may vary. No access to non-public engagement metrics that MCL provides.

### Recommendation

Apply for MCL as soon as possible (Pre-Phase task E.4). Build the collector to support both paths -- the ArenaCollector implementation should abstract the data source behind the tier configuration, with separate API clients for MCL (premium) and Bright Data (medium).

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | N/A | -- | No viable free tier for Facebook or Instagram research data. |
| **Medium** | Bright Data Facebook Datasets + Instagram Scraper API | Facebook: $250/100K records; Instagram: $1.50/1K records | Commercial scraping. Immediate access. Legal under US precedent (*Meta v. Bright Data*, 2024, dismissed). |
| **Premium** | Meta Content Library (MCL) | $371/month + $1,000 setup (via SOMAR/ICPSR) | Institutional access. Cleanroom environment. Facebook + Instagram + Threads. |

---

## 3. API/Access Details

### Premium Tier: Meta Content Library (MCL)

**Access application**:
1. Apply through Meta's Research Tools Manager
2. Independent review by France's CASD (Secure Data Access Center), typically 2-6 weeks
3. Alternatively, apply through ICPSR at the University of Michigan
4. Requires: institutional affiliation (academic/non-profit), IRB approval, research proposal focused on systemic risk or public interest topics

**Analysis environment**:
- **Meta Secure Research Environment**: Free cleanroom. Analysis runs inside Meta's infrastructure.
- **SOMAR Virtual Data Enclave** (University of Michigan): $371/month per team + $1,000 one-time project start fee (as of January 2026). More flexible than Meta's own environment.

**API capabilities**:
- Full-text keyword search across public posts
- 100+ queryable data fields
- Date range filtering
- Author/Page filtering
- Country and language filtering
- Post view counts (unique to MCL -- CrowdTangle never had this)
- Text-in-image search (OCR-based)
- Engagement metrics: reactions, comments, shares
- Reels data (Instagram)

**Data access restrictions**:
- Facebook: Raw data export limited to posts from pages with 15,000+ followers
- Instagram: Raw data export limited to profiles with 25,000+ followers
- Threads: Data cannot be exported as CSV (must be analyzed in cleanroom)
- Weekly retrieval cap: 500,000 results
- All analysis must occur within the cleanroom environment

**Rate limits**: Not publicly documented per-endpoint. The 500,000 results/week cap is the binding constraint.

### Medium Tier: Bright Data

#### Facebook (Bright Data Datasets)

**Product**: Bright Data Facebook Datasets
**Pricing**: ~$250 per 100,000 records
**Delivery**: Pre-collected or on-demand datasets delivered as JSON/CSV

**Available data types**:
- Posts from public Pages and Groups
- Comments on public posts
- Page metadata (followers, category, about)
- Post engagement metrics (reactions, comments, shares)

**Request parameters**: Specify target pages/groups, keywords, date ranges, and geographic focus.

**Limitations**:
- Not a real-time API -- dataset delivery has lag (hours to days depending on request complexity)
- No streaming or webhook support
- Data freshness depends on Bright Data's crawl schedule
- Personal profile posts are not available (only public Pages and Groups)

#### Instagram (Bright Data Scraper API)

**Product**: Bright Data Instagram Scraper API
**Pricing**: ~$1.50 per 1,000 records
**Access**: REST API with real-time scraping

**Key endpoints** (Bright Data Web Scraper API):

| Endpoint | Description | Response |
|----------|-------------|----------|
| Profile scraper | Get profile metadata by username | JSON with bio, followers, posts count |
| Posts scraper | Get posts from a profile | JSON array of posts with captions, engagement |
| Hashtag scraper | Get posts for a hashtag | JSON array of posts matching hashtag |
| Comments scraper | Get comments on a post | JSON array of comments |

**Parameters**:
- `url` or `username`: Target profile or post
- `count`: Number of results to retrieve
- `country`: Proxy country for geo-specific content

**Rate limits**: Bright Data handles proxy rotation and rate limiting internally. No per-endpoint rate limits published for the API consumer. Throughput is generally 10-50 requests per second.

**Limitations**:
- Instagram Stories are not captured (ephemeral content)
- Reels metadata is partial -- engagement metrics may be delayed
- Sponsored/ad content identification is unreliable
- Content from private accounts is not accessible

---

## 4. Danish Context

### Facebook

- **Danish Facebook usage**: 84% of Danes aged 16-74 use Facebook. It is the #1 social media platform for news in Denmark (32% of Danes get news there).
- **Key content types for Danish discourse**:
  - Public Pages of media outlets (DR, TV2, BT, Politiken, Berlingske, Ekstra Bladet)
  - Political party Pages and politician personal Pages
  - Public Groups (e.g., Danish political discussion groups, local community groups)
  - Event pages for protests, public meetings, cultural events
- **Language filtering**:
  - MCL (premium): Supports country and language filtering. Use `country=DK` and/or `language=da`.
  - Bright Data (medium): Filter by targeting known Danish Pages/Groups. No native language filter -- client-side language detection needed.
- **Content volume**: Facebook is the highest-volume Danish discourse platform. Expect tens of thousands of public posts per day from major Danish Pages and Groups combined.
- **Facebook Groups**: A significant portion of Danish public discourse occurs in semi-public Facebook Groups (visible to members only). Neither MCL nor Bright Data can access private or closed groups. Only public group content is available.

### Instagram

- **Danish Instagram usage**: 56% of Danes aged 16-74 use Instagram. 19% of Danes get news from Instagram.
- **Content types**: Feed posts, Reels, Stories (ephemeral, not collectible), IGTV (deprecated).
- **Language filtering**: Instagram does not have a native language field. Danish content must be identified by:
  - Targeting known Danish accounts
  - Searching for Danish-language hashtags (e.g., `#dkpol`, `#danmark`, `#danske`)
  - Client-side language detection on caption text
- **Hashtag-based discovery**: Instagram's hashtag ecosystem is active in Denmark. Key hashtags include `#dkpol`, `#danmark`, `#kobenhavn`, `#dkmedier`, `#danmarksnatur`, and topic-specific tags.
- **Influencer and media accounts**: Danish media outlets, politicians, and influencers maintain active Instagram presences. The platform is increasingly important for visual news storytelling and political communication.

---

## 5. Data Fields

Mapping to the Universal Content Record schema. Fields shown for the medium tier (Bright Data); MCL fields are a superset.

### Facebook Posts

| UCR Field | Bright Data Source | MCL Source | Notes |
|-----------|-------------------|------------|-------|
| `platform` | `"facebook"` | `"facebook"` | Constant |
| `arena` | `"social_media"` | `"social_media"` | Constant |
| `platform_id` | `post.id` | `post.id` | Facebook post ID |
| `content_type` | `"post"` | `"post"` | Posts, shares, comments |
| `text_content` | `post.message` or `post.description` | `post.message` | Post text content |
| `title` | `post.name` (link posts) | `post.name` | Title of shared link, if any |
| `url` | `post.url` or constructed from ID | `post.url` | Facebook post URL |
| `language` | Detect from `text_content` | `post.language` | MCL provides language; Bright Data does not |
| `published_at` | `post.created_time` | `post.creation_time` | ISO 8601 timestamp |
| `collected_at` | Now | Now | Standard |
| `author_platform_id` | `post.page_id` or `post.user_id` | `post.page_id` | Page or user ID |
| `author_display_name` | `post.page_name` or `post.user_name` | `post.page_name` | Page or user name |
| `views_count` | `NULL` | `post.view_count` | MCL only -- unique to MCL |
| `likes_count` | `post.reactions.total` or `post.likes` | `post.reactions_count` | Reaction count |
| `shares_count` | `post.shares` | `post.shares_count` | Share count |
| `comments_count` | `post.comments` | `post.comments_count` | Comment count |
| `engagement_score` | Compute from reactions + shares + comments | Compute from all metrics | Normalized |
| `raw_metadata` | Full post object | Full post object | Store: `post_type` (link/photo/video/status), `reactions_breakdown` (love/angry/sad/etc.), `parent_id` (for shared posts), `group_id`, `event_id` |
| `media_urls` | Extract from `post.images[]` or `post.video_url` | Extract from media objects | Image and video URLs |
| `content_hash` | SHA-256 of normalized `text_content` | SHA-256 of normalized `text_content` | For deduplication |

### Instagram Posts

| UCR Field | Bright Data Source | MCL Source | Notes |
|-----------|-------------------|------------|-------|
| `platform` | `"instagram"` | `"instagram"` | Constant |
| `arena` | `"social_media"` | `"social_media"` | Constant |
| `platform_id` | `post.id` or `post.shortcode` | `post.id` | Instagram post ID or shortcode |
| `content_type` | `"post"` or `"reel"` | `"post"` or `"reel"` | Feed post or Reel |
| `text_content` | `post.caption` | `post.caption_text` | Caption text |
| `title` | `NULL` | `NULL` | Instagram posts have no title |
| `url` | `https://www.instagram.com/p/{shortcode}/` | Constructed from ID | |
| `language` | Detect from `caption` | `post.language` | Client-side detection for Bright Data |
| `published_at` | `post.timestamp` | `post.creation_time` | |
| `collected_at` | Now | Now | Standard |
| `author_platform_id` | `post.owner_id` or `post.username` | `post.creator_id` | |
| `author_display_name` | `post.username` | `post.creator_name` | |
| `views_count` | `post.video_view_count` (videos/reels only) | `post.view_count` | |
| `likes_count` | `post.likes_count` | `post.likes_count` | |
| `shares_count` | `NULL` | `post.shares_count` | Shares not available via Bright Data |
| `comments_count` | `post.comments_count` | `post.comments_count` | |
| `engagement_score` | Compute from likes + comments | Compute from all metrics | Normalized |
| `raw_metadata` | Full post object | Full post object | Store: `post_type` (image/video/carousel/reel), `hashtags[]`, `mentions[]`, `location`, `is_sponsored`, `carousel_media[]` |
| `media_urls` | Extract from `post.display_url`, `post.video_url` | Extract from media objects | |
| `content_hash` | SHA-256 of normalized `text_content` | SHA-256 of normalized `text_content` | |

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Medium (Bright Data - Facebook) | `{"api_token": "bd-fb-xxx", "zone": "facebook_zone"}` | `"brightdata_facebook"` |
| Medium (Bright Data - Instagram) | `{"api_token": "bd-ig-xxx", "zone": "instagram_zone"}` | `"brightdata_instagram"` |
| Premium (Meta Content Library) | `{"access_token": "mcl-token-xxx", "app_id": "12345", "app_secret": "secret"}` | `"meta_content_library"` |

**Bright Data credentials**:
- Single Bright Data account can serve both Facebook and Instagram zones
- API token is account-level; zone identifiers select the specific scraper product
- No multi-account rotation needed -- Bright Data handles proxy rotation internally

**MCL credentials**:
- Access token obtained through Meta's Research Tools Manager after application approval
- Tokens are tied to the approved research project and institution
- Token refresh may be required periodically -- document the refresh process

---

## 7. Rate Limits and Multi-Account Notes

### Premium Tier (MCL)

| Metric | Value | Notes |
|--------|-------|-------|
| Weekly retrieval cap | 500,000 results | Binding constraint for large collections |
| Per-request limit | Not published | Managed by cleanroom environment |
| Token validity | Project-duration | Tied to approved research project |

### Medium Tier (Bright Data)

| Metric | Facebook | Instagram | Notes |
|--------|----------|-----------|-------|
| Throughput | 10-50 req/sec | 10-50 req/sec | Bright Data manages proxy rotation |
| Daily cap | No hard cap | No hard cap | Billing-based |
| Delivery latency | Hours (datasets) | Real-time (API) | Facebook uses dataset model; Instagram uses real-time API |

**Multi-account**: Not applicable. Bright Data abstracts account management. Single API token is sufficient.

**RateLimiter configuration**:
- For Bright Data: Implement client-side rate limiting at ~10 req/sec to avoid excessive costs
- For MCL: Track weekly retrieval count against 500,000 cap
- Both tiers: Enforce credit budget limits per collection run

---

## 8. Search Capabilities

### collect_by_terms()

**MCL (premium)**:
- Full-text keyword search across post text, image text (OCR), and metadata fields
- Supports date range, country (`DK`), language (`da`), and content type filters
- Results paginated; cursor-based

**Bright Data Facebook (medium)**:
- Request datasets filtered by keyword, target pages/groups, and date range
- Delivery is asynchronous (hours)
- Less precise than MCL -- keyword matching may be approximate

**Bright Data Instagram (medium)**:
- Search by hashtag: target Danish hashtags related to query design terms
- Search by account: target known Danish media and political accounts
- No full-text keyword search across all public posts -- must target specific hashtags or accounts

### collect_by_actors()

**MCL (premium)**:
- Filter by Page ID or profile ID
- Retrieve all public posts from specific actors within date range

**Bright Data Facebook (medium)**:
- Request page-specific datasets by Page URL or ID
- Asynchronous delivery

**Bright Data Instagram (medium)**:
- Use profile scraper with target username
- Real-time retrieval of recent posts
- Paginate through historical posts (limited depth)

---

## 9. Latency and Freshness

| Tier | Platform | Latency | Notes |
|------|----------|---------|-------|
| Premium (MCL) | Facebook | Near-real-time | Posts available within minutes of publication |
| Premium (MCL) | Instagram | Near-real-time | Posts available within minutes |
| Medium (Bright Data) | Facebook | Hours (dataset delivery) | Asynchronous dataset model |
| Medium (Bright Data) | Instagram | Seconds (API) | Real-time scraping |

**Polling interval recommendation**:
- MCL: Poll every 30-60 minutes for live tracking
- Bright Data Instagram: Poll every 30-60 minutes
- Bright Data Facebook: Submit dataset requests daily; process on delivery

---

## 10. Known Limitations

1. **Facebook Groups**: Only public groups are accessible. Closed and private groups (which host substantial Danish discourse) are not available through any method. This is a significant coverage gap.

2. **Instagram Stories**: Ephemeral content (24-hour lifespan) is not collectible through either tier. Stories are a major content format but cannot be archived for research.

3. **MCL export restrictions**: Facebook posts from pages with fewer than 15,000 followers and Instagram posts from profiles with fewer than 25,000 followers cannot be exported as raw data from MCL. They can be analyzed in the cleanroom but not downloaded. This limits local storage and cross-platform analysis for smaller accounts.

4. **MCL Threads limitation**: Threads data in MCL cannot be exported as CSV. Analysis must occur entirely within the cleanroom environment.

5. **Bright Data data quality**: Scraping-based collection may have gaps -- posts that fail to load, engagement metrics captured at a single point in time rather than tracked over time, and inconsistent field availability across posts.

6. **No native Instagram language filter**: Instagram does not tag posts with language metadata. Danish content identification requires targeting known Danish accounts/hashtags or client-side language detection on caption text. This means `collect_by_terms()` for Instagram at the medium tier is effectively limited to hashtag-based collection.

7. **Facebook reaction types**: Facebook supports multiple reaction types (Like, Love, Haha, Wow, Sad, Angry, Care). The normalizer should map total reactions to `likes_count` and preserve the breakdown in `raw_metadata`.

8. **Carousel posts (Instagram)**: A single Instagram post may contain up to 10 images/videos. The normalizer should extract all media URLs to `media_urls` and preserve carousel metadata in `raw_metadata`.

9. **Deduplication across platforms**: Content shared from Instagram to Facebook (cross-posting) may appear in both platform collections. The `content_hash` deduplication mechanism should catch text-identical cross-posts.

10. **MCL application timeline**: The CASD review process typically takes 2-6 weeks. Plan accordingly -- apply well before Phase 2 begins. The 2-week decision point in the Implementation Plan assumes the application was submitted during the Pre-Phase.

---

## 11. Legal Considerations

**Meta Content Library (premium)**:
- Fully compliant access path sanctioned by Meta for academic research
- Data use governed by MCL Terms of Service and the approved research proposal
- Cleanroom environment enforces data handling restrictions
- GDPR compliance is partially handled by Meta's infrastructure (e.g., data subject requests handled by Meta)
- Researcher still must maintain DPIA and privacy notice for the research project
- MCL access is restricted to research on systemic risks, public interest, or well-being -- general social media research may not qualify

**Bright Data (medium)**:
- *Meta v. Bright Data* (2024, dismissed): Meta's lawsuit against Bright Data for scraping Facebook and Instagram was dismissed. Scraping publicly accessible data was found lawful under US law.
- In the EU: GDPR applies to all personal data collected regardless of collection method. Facebook/Instagram post content and author information are personal data.
- Meta's Terms of Service prohibit scraping. While this has not been upheld in US courts, EU courts may view it differently. The legal risk in the EU is moderate.
- Recommendation: If using Bright Data, document the legal basis carefully in the DPIA. Note the research exemption under GDPR Art. 89 and the DSA Art. 40(12) right to access publicly available data for systemic risk research.

**DSA Article 40**:
- Facebook and Instagram are both designated as VLOPs under the DSA
- Meta received preliminary breach findings in October 2025 for inadequate public data access for researchers
- DSA Art. 40 does not permit platforms to charge researchers for public data access
- MCL's pricing structure for SOMAR may be challenged under DSA enforcement -- monitor developments
- For systemic risk research, DSA provides an independent legal basis for data access that supplements GDPR Art. 89

**GDPR specifics**:
- Legal basis: Art. 6(1)(e) + Art. 89 for university research
- Special category data: Facebook posts revealing political opinions, religious beliefs, health conditions are common. Art. 9(2)(j) + Databeskyttelsesloven section 10 applies.
- Pseudonymize all author identifiers: `SHA-256(platform + platform_user_id + project_salt)`
- For MCL: Meta handles some GDPR obligations within the cleanroom. For Bright Data: the researcher bears full GDPR responsibility.

---

## 12. Recommended Implementation Approach

### Architecture

- **Two separate ArenaCollectors**: `FacebookCollector` and `InstagramCollector`, each implementing the ArenaCollector base class. They share the Bright Data credential pool but have different normalizers and field mappings.
- **Tier-switching**: Each collector supports both medium (Bright Data) and premium (MCL) tiers. The tier is selected per collection run via `arenas_config` in the collection run.
- **MCL client**: If MCL access is approved, implement an MCL API client that handles authentication, search, pagination, and cleanroom data retrieval. This is a shared component used by both Facebook and Instagram collectors (and potentially the Threads collector).
- **Bright Data client**: Implement Bright Data API client as a shared component. Facebook uses the dataset model (asynchronous delivery); Instagram uses the scraper API (synchronous). Handle both patterns.

### Key Implementation Guidance

1. **Facebook `collect_by_terms()` -- Bright Data**:
   - Submit dataset request to Bright Data with keywords, target pages, date range
   - Poll for dataset delivery completion
   - Parse delivered JSON/CSV into UCR format
   - This is an asynchronous pattern -- the Celery task submits the request, then a follow-up task checks for and processes delivery

2. **Facebook `collect_by_terms()` -- MCL**:
   - Call MCL API search endpoint with keywords, `country=DK`, `language=da`, date range
   - Paginate through results with cursor
   - Track weekly retrieval count against 500,000 cap

3. **Instagram `collect_by_terms()` -- Bright Data**:
   - Map query design terms to Instagram hashtags
   - Call hashtag scraper for each hashtag
   - Paginate through results
   - Apply client-side language detection to filter Danish content

4. **Instagram `collect_by_actors()` -- Bright Data**:
   - Map actor platform presences to Instagram usernames
   - Call profile scraper for each actor
   - Retrieve recent posts and paginate
   - More reliable than hashtag-based collection for specific accounts

5. **Normalizer**: Implement four parsing paths:
   - `_parse_brightdata_facebook(raw)` for medium tier Facebook
   - `_parse_brightdata_instagram(raw)` for medium tier Instagram
   - `_parse_mcl_facebook(raw)` for premium tier Facebook
   - `_parse_mcl_instagram(raw)` for premium tier Instagram

6. **Health check**:
   - Bright Data: Verify API token validity and zone availability
   - MCL: Verify access token validity and API endpoint reachability

7. **Credit cost mapping**:
   - Bright Data Facebook: 1 credit = 1 record (dataset pricing: $250/100K = $0.0025/record)
   - Bright Data Instagram: 1 credit = 1 record (API pricing: $1.50/1K = $0.0015/record)
   - MCL: Fixed monthly cost; credit mapping based on weekly retrieval budget (500,000/week = ~71,428/day)
