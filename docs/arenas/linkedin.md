# Arena Research Brief: LinkedIn

**Created**: 2026-02-16
**Last updated**: 2026-02-16
**Status**: Ready for implementation
**Phase**: 2 (Task 2.5, High priority)
**Arena path**: `src/issue_observatory/arenas/social_media/linkedin/`

---

## 1. Platform Overview

LinkedIn is a professional networking platform with over 1 billion members globally. In Denmark, LinkedIn reaches approximately 33% of 16-74-year-olds, making it the fifth-largest social media platform in the country. Uniquely among major platforms, LinkedIn has shown **consistent growth** in daily usage through 2024. LinkedIn's value for Danish discourse research lies in professional and institutional communication -- organizational announcements, industry debate, policy discussions, and thought leadership content that does not appear on other platforms.

**Role in Danish discourse**: LinkedIn captures a distinct slice of Danish public discourse: professional commentary on politics, economics, education, healthcare, and industry. Danish politicians increasingly post substantive policy positions on LinkedIn. Major Danish employers (Novo Nordisk, Maersk, Vestas, Carlsberg), trade unions, professional associations, and public institutions maintain active LinkedIn presences. The platform's algorithm favors long-form text posts, making it the primary venue for detailed professional argumentation in Denmark.

**Access model**: LinkedIn is the most access-restricted major platform for researchers. There is no viable free or medium tier API for research purposes. The two paths are: (1) DSA Article 40 researcher access (premium, uncertain timeline), and (2) Zeeschuimer browser capture as a manual fallback. Third-party scraping services exist but carry significant legal risk in the EU following the CNIL's EUR 240,000 fine against KASPR in December 2024.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | N/A | -- | No free API access for research. |
| **Medium** | N/A | -- | No medium tier. Third-party scraping (Bright Data $1.50/1K, Apify, PhantomBuster) exists but is not recommended due to EU legal risk. See Legal Considerations. |
| **Premium** | DSA Article 40 researcher access | $0 (DSA mandates free access) | Aggregated, anonymized data on publicly accessible content. Application through Digitaliseringsstyrelsen (Danish DSC). |
| **Manual fallback** | Zeeschuimer browser capture | $0 | Firefox extension for passive data capture while browsing. Manual, non-scalable. See `/reports/zeeschuimer_assessment.md`. |

**This arena cannot be fully automated at any tier as of February 2026.** DSA researcher access is still in early stages of operationalization. Zeeschuimer is a manual supplement. The collector implementation should be built to accommodate DSA access when it becomes available, with a manual import pathway for Zeeschuimer data in the interim.

---

## 3. API/Access Details

### Premium Tier: DSA Article 40 Researcher Access

**Application process**:
1. Apply through Denmark's Digital Services Coordinator: **Digitaliseringsstyrelsen** (Danish Agency for Digital Government), which assumed DSC responsibility on August 29, 2024
2. Since LinkedIn is established in Ireland, the application is transmitted to Ireland's **Coimisiun na Mean** (Media Commission)
3. The vetted researcher process became operational in late October 2025 following the Delegated Act adopted in July 2025
4. Applicants must demonstrate:
   - Independence from commercial interests
   - Disclosed funding sources
   - Research focus on EU systemic risk topics (illegal content, fundamental rights, civic discourse, elections, public health, minors' well-being)

**Data access scope**:
- Aggregated, anonymized data on publicly accessible content
- Data **cannot be downloaded directly** -- analysis occurs within LinkedIn's data access infrastructure
- Exact endpoints, field sets, and query capabilities are not yet publicly documented

**Current status** (February 2026):
- The DSA vetted researcher framework is operational but **very new**
- LinkedIn's specific researcher access program launched in August 2023 but was limited in scope
- The European Commission issued preliminary breach findings against multiple VLOPs in October 2025 for inadequate researcher access
- The Commission has confirmed that Art. 40 does not permit platforms to charge researchers for access
- Practical experience reports from researchers who have obtained DSA access to LinkedIn are scarce

**What is known about available data**:
- Public posts and articles from LinkedIn profiles
- Engagement metrics (reactions, comments, shares) -- likely aggregated
- Content from LinkedIn Pages (company pages)
- Unclear: whether individual post-level data is available or only aggregate statistics
- Unclear: whether search/filter by language or country is supported
- Unclear: what the query interface looks like (API, web interface, or data enclave)

### Official LinkedIn API (Not Recommended for This Project)

**Marketing Developer Platform**:
- Requires approval through LinkedIn's Partner Program (approval rate below 10%, 3-6 months timeline)
- Development tier: Testing only, not for production data collection
- Standard tier: Requires LinkedIn review
- Rate limits: 100-500 API calls per day (free tier)
- Not designed for research -- designed for marketing automation, recruitment, and CRM integration
- Does not provide access to public post search or timeline data for research purposes

**Reported pricing** (unconfirmed, from third-party sources):
- ~$59/month: 500 requests/day
- ~$499/month: 5,000 requests/day
- ~$2,999/month: Unlimited
- These prices are for marketing API access, not research data access

### Manual Fallback: Zeeschuimer

**Tool**: Zeeschuimer Firefox extension (Digital Methods Initiative, University of Amsterdam)
**Repository**: https://github.com/digitalmethodsinitiative/zeeschuimer
**Assessment**: `/reports/zeeschuimer_assessment.md`

**How it works**:
1. Install Zeeschuimer as a Firefox extension
2. Browse LinkedIn normally while logged in
3. Zeeschuimer passively intercepts API responses from LinkedIn to the browser
4. Export captured data as NDJSON
5. Import NDJSON into the Issue Observatory via the manual import pathway (`POST /api/content/import`)

**Capabilities**:
- Captures post text, author info, engagement metrics, comments, media
- Full support for LinkedIn (no known gaps in captured fields)
- Data captured in real-time as the user browses

**Limitations**:
- Entirely manual -- requires a human to browse LinkedIn
- No search targeting: captures only what appears in the user's feed or what the user navigates to
- Cannot implement `collect_by_terms()` or `collect_by_actors()` as ArenaCollector requires
- Not scalable -- throughput is limited to human browsing speed
- Cannot be scheduled via Celery
- Data quality depends on the researcher's browsing patterns

**Legal position**: Strong. Zeeschuimer captures data that LinkedIn already sent to the user's browser. The user is authenticated and browsing normally. This is analogous to using browser developer tools.

---

## 4. Danish Context

- **LinkedIn usage in Denmark**: 33% of 16-74-year-olds, the only major platform showing consistent growth in daily usage through 2024
- **Content language**: Danish LinkedIn content is predominantly in Danish, with significant English-language content from international companies and professionals. No native `lang:da` filter exists in any available access path.
- **Key Danish LinkedIn communities**:
  - Political leaders and ministers posting policy positions
  - Major Danish employers: Novo Nordisk, Maersk, Vestas, Carlsberg, Danfoss, LEGO
  - Trade unions: 3F, HK, Dansk Metal, Djof, IDA
  - Public institutions: Sundhedsstyrelsen, Finansministeriet, Datatilsynet
  - Danish media professionals and journalists
  - University researchers and academic institutions
- **Content types**: Text posts (most common for discourse), articles (long-form), shared links with commentary, video posts, document posts (PDF/slides)
- **Algorithm bias**: LinkedIn's algorithm heavily promotes engagement and "thought leadership" content. The feed is not chronological. This means Zeeschuimer captures algorithm-curated content, not a representative sample of Danish LinkedIn discourse.

---

## 5. Data Fields

Mapping to the Universal Content Record schema. Based on Zeeschuimer capture format (the primary available data path as of February 2026).

| UCR Field | LinkedIn Source (Zeeschuimer NDJSON) | Notes |
|-----------|-------------------------------------|-------|
| `platform` | `"linkedin"` | Constant |
| `arena` | `"social_media"` | Constant |
| `platform_id` | `activity.urn` or `post.urn` | LinkedIn URN (e.g., `urn:li:activity:12345`) |
| `content_type` | `"post"` or `"article"` | Text posts, articles, shared content |
| `text_content` | `post.commentary.text` or `article.text` | Post text or article body |
| `title` | `article.title` (articles only) | NULL for regular posts |
| `url` | Constructed: `https://www.linkedin.com/posts/{activity_id}` or `https://www.linkedin.com/pulse/{article_slug}` | |
| `language` | Detect from `text_content` | LinkedIn API does not expose language in Zeeschuimer captures |
| `published_at` | `post.created_at` or `activity.timestamp` | Unix timestamp, convert to ISO 8601 |
| `collected_at` | Now (at import time) | Standard |
| `author_platform_id` | `author.urn` (e.g., `urn:li:member:12345`) or `author.vanityName` | LinkedIn member URN or company URN |
| `author_display_name` | `author.name` | Full name |
| `views_count` | `post.impressionCount` | May be approximate |
| `likes_count` | `post.likeCount` or `post.totalSocialActivityCounts.numLikes` | |
| `shares_count` | `post.shareCount` or `post.totalSocialActivityCounts.numShares` | Reshares |
| `comments_count` | `post.commentCount` or `post.totalSocialActivityCounts.numComments` | |
| `engagement_score` | Compute from impressions, likes, shares, comments | Normalized |
| `raw_metadata` | Full NDJSON object | Store: `reaction_breakdown` (Like/Celebrate/Support/Love/Insightful/Funny), `hashtags[]`, `mentions[]`, `post_type` (text/article/video/document/shared), `shared_content` (if reshare), `author.headline`, `author.industry` |
| `media_urls` | Extract from `post.images[]` or `post.video.url` | Image and video URLs |
| `content_hash` | SHA-256 of normalized `text_content` | For deduplication |

**DSA access fields**: When DSA Article 40 access becomes available, the field mapping will need to be updated. The data may be aggregated/anonymized, meaning individual `author_platform_id` and `author_display_name` may not be available. This is a significant limitation for actor-based research. Flag this as a `[TBD]` pending DSA access details.

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Premium (DSA Art. 40) | TBD -- depends on LinkedIn's implementation of DSA researcher access | `"linkedin_dsa"` |
| Manual (Zeeschuimer) | None (data imported via file upload) | N/A |

**No credentials are needed for the manual Zeeschuimer pathway.** The researcher uses their own LinkedIn account in Firefox. Zeeschuimer captures data passively.

**For DSA access**: Credential requirements will be determined when LinkedIn's researcher access infrastructure is formalized. Placeholder CredentialPool `platform` value is `"linkedin_dsa"`. Update this brief when details become available.

---

## 7. Rate Limits and Multi-Account Notes

### Premium Tier (DSA Art. 40)

Not yet documented. DSA Art. 40 does not permit platforms to impose unreasonable restrictions on researcher access, but specific rate limits, query quotas, and data volume caps will be determined by LinkedIn's implementation.

### Manual Fallback (Zeeschuimer)

| Metric | Value | Notes |
|--------|-------|-------|
| Throughput | ~50-200 posts per hour | Depends on browsing patterns and feed loading |
| Daily cap | None (limited by human endurance) | |
| Automation | Not supported | Requires manual browsing |

**Multi-account**: Not applicable. Zeeschuimer uses the researcher's own LinkedIn session. Using multiple LinkedIn accounts to increase throughput would violate LinkedIn's Terms of Service and is not recommended.

---

## 8. Search Capabilities

### collect_by_terms()

**DSA Art. 40 (premium)**: Search capabilities unknown. If LinkedIn implements a search-based API for researcher access, `collect_by_terms()` would map query design terms to search queries. This is speculative as of February 2026.

**Zeeschuimer (manual)**: Not supported. Zeeschuimer captures whatever appears in the user's feed or navigated-to pages. The researcher can manually search LinkedIn and capture results, but this is not automatable via `collect_by_terms()`.

**Workaround for manual collection**: The researcher can use LinkedIn's built-in search (keywords, hashtags, date filters) to navigate to relevant content. Zeeschuimer will capture the search results and any posts the researcher opens. This provides semi-targeted collection but requires human judgment and effort.

### collect_by_actors()

**DSA Art. 40 (premium)**: If LinkedIn implements profile-level data access, `collect_by_actors()` would map actor platform presences to LinkedIn profile URNs. Speculative.

**Zeeschuimer (manual)**: The researcher can navigate to specific LinkedIn profiles and scroll through their posts. Zeeschuimer captures the loaded content. This provides semi-targeted actor-based collection but is manual and limited by feed pagination depth.

---

## 9. Latency and Freshness

| Tier | Latency | Notes |
|------|---------|-------|
| Premium (DSA Art. 40) | Unknown | Depends on LinkedIn's implementation |
| Manual (Zeeschuimer) | Real-time capture, delayed import | Data captured instantly while browsing; imported to Issue Observatory later via NDJSON upload |

**For live tracking**: LinkedIn is not suitable for real-time live tracking at any currently available tier. Zeeschuimer-based collection has inherent lag between capture (manual browsing) and import (NDJSON upload). DSA access latency is unknown.

**Polling interval**: Not applicable. This arena does not support automated polling.

---

## 10. Known Limitations

1. **No automated collection path**: As of February 2026, there is no automated, API-based method to collect LinkedIn data for research at any price point that is legally defensible in the EU. This is the most access-restricted arena in the project.

2. **DSA access is speculative**: While the DSA Art. 40 framework is operational, LinkedIn's specific implementation of researcher data access is still in early stages. The exact data fields, query capabilities, and access constraints are unknown. This brief will need significant updates when DSA access details are published.

3. **Zeeschuimer is not scalable**: Manual browser-based capture is inherently limited. It cannot be scheduled, cannot target specific queries reliably, and cannot be parallelized without multiple human operators.

4. **Algorithmic feed bias**: Zeeschuimer captures LinkedIn content as served by LinkedIn's algorithm. This is not a representative sample -- it is biased toward content the algorithm promotes to the specific researcher's profile. This bias must be disclosed in any research using Zeeschuimer-captured LinkedIn data.

5. **Third-party scraping is high-risk in the EU**: Following the CNIL's EUR 240,000 fine against KASPR in December 2024 for scraping ~160 million LinkedIn contacts, and LinkedIn's public enforcement action against Proxycurl in January 2025, using commercial scraping services for LinkedIn data in the EU carries substantial legal risk. This project does **not** recommend using Bright Data, Apify, or PhantomBuster for LinkedIn data despite their availability.

6. **No language filter**: Neither DSA access (speculative) nor Zeeschuimer provides a language filter. Danish content must be identified by client-side language detection after capture/import.

7. **Anonymized DSA data**: DSA Art. 40 researcher access provides "aggregated, anonymized data on publicly accessible content." If the data is truly anonymized, it will not support actor-level analysis (mapping specific users to their content). This is a critical limitation for actor-based discourse research. Clarify data granularity when applying for DSA access.

8. **LinkedIn API is not for research**: The official LinkedIn Marketing Developer Platform is designed for marketing, recruitment, and CRM. Attempting to use it for research data collection will likely result in application rejection and potential account suspension.

9. **Data retention**: LinkedIn posts do not have a permanent URL format -- older posts may become inaccessible or have their URLs change. Zeeschuimer-captured data should be treated as snapshot data with `collected_at` timestamps being particularly important.

10. **Import pathway dependency**: The Zeeschuimer manual fallback depends on the generic NDJSON import endpoint (`POST /api/content/import`) described in the Implementation Plan as a Phase 2/3 feature. This import pathway must be built before LinkedIn data can flow into the system.

---

## 11. Legal Considerations

**DSA Article 40 (premium)**:
- DSA Art. 40 provides the most legally secure path for LinkedIn research data in the EU
- Art. 40 establishes an enforceable right to access publicly accessible data for systemic risk research
- Platforms cannot charge for this access (Commission confirmed, December 2025)
- Platforms cannot punish researchers for exercising this right
- Application through Denmark's DSC (Digitaliseringsstyrelsen) ensures institutional oversight
- Research must focus on systemic risk topics (Art. 34 DSA): illegal content, fundamental rights, civic discourse, elections, public health, minors

**Zeeschuimer (manual fallback)**:
- Legal position: Strong for passive capture. Zeeschuimer records data LinkedIn already sent to the browser. No additional data access occurs.
- LinkedIn Terms of Service: Technically prohibits automated data collection, but Zeeschuimer is not automated -- it is passive capture during normal browsing.
- The *hiQ v. LinkedIn* (2022) US ruling established that scraping publicly visible LinkedIn data does not violate the CFAA, but this is a US precedent and does not directly apply in the EU.
- GDPR applies to all captured LinkedIn data. Pseudonymize author identifiers immediately upon import.

**Third-party scraping (NOT RECOMMENDED)**:
- CNIL fined KASPR EUR 240,000 (December 2024) for scraping LinkedIn without informing data subjects. This is a directly applicable EU precedent.
- LinkedIn has publicly announced enforcement action against Proxycurl (January 2025).
- Under GDPR, LinkedIn profile data is personal data regardless of public visibility.
- The EU Database Directive provides additional protection for LinkedIn's database.
- Recommendation: Do NOT use third-party scraping services for LinkedIn in this project.

**GDPR specifics**:
- Legal basis: Art. 6(1)(e) + Art. 89 for university research
- LinkedIn profiles frequently reveal professional affiliations, political opinions (through post content), and other potentially sensitive information
- Pseudonymize all author identifiers: `SHA-256("linkedin" + member_urn + project_salt)`
- Include LinkedIn collection in the project DPIA
- For Zeeschuimer captures: document in the privacy notice that data is captured from publicly visible LinkedIn content during normal platform use

---

## 12. Recommended Implementation Approach

### Architecture

- **Phased implementation**:
  1. **Phase 2 (immediate)**: Build the NDJSON import pathway for Zeeschuimer data. Implement a LinkedIn normalizer that maps Zeeschuimer NDJSON to UCR format. This is a manual import, not an automated collector.
  2. **Phase 2/3 (when available)**: Build a `LinkedInCollector` implementing ArenaCollector when DSA Art. 40 access details are published. This collector will support `collect_by_terms()` and `collect_by_actors()` if the DSA access interface supports them.

- **Import-first, not collector-first**: Unlike other arenas, LinkedIn starts as an import target, not an active collector. The generic import endpoint (`POST /api/content/import`) should be the initial integration point.

### Key Implementation Guidance

1. **Zeeschuimer NDJSON import**:
   - Accept NDJSON file upload via `POST /api/content/import`
   - Detect LinkedIn data format from NDJSON structure
   - Run each record through the LinkedIn normalizer
   - Tag records with `collection_tier: "manual"` and `collection_method: "zeeschuimer"` in `raw_metadata`
   - Apply pseudonymization immediately upon import
   - Validate required fields and reject malformed records with clear error messages

2. **LinkedIn normalizer**:
   - Parse Zeeschuimer's LinkedIn JSON schema (varies between post types: text posts, articles, shared content, video posts)
   - Extract text content from `post.commentary.text` for posts and `article.text` for articles
   - Map LinkedIn URNs to `platform_id` and `author_platform_id`
   - Extract reaction breakdown to `raw_metadata`
   - Construct post URLs from activity IDs

3. **DSA access collector** (future):
   - Placeholder `LinkedInCollector` class with `NotImplementedError` for `collect_by_terms()` and `collect_by_actors()`
   - Configuration stub for `linkedin_dsa` tier
   - Update when DSA access details become available

4. **Health check**: Not applicable for manual import. When DSA access is implemented, add appropriate health check.

5. **Credit cost mapping**:
   - Manual import (Zeeschuimer): 0 credits (no API cost)
   - DSA access: 0 credits (DSA mandates free access for researchers)
   - The credit system does not apply to this arena unless a paid API path is added in the future
