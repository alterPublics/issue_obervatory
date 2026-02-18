# Arena Research Brief: VKontakte (VK)

**Created**: 2026-02-18
**Last updated**: 2026-02-18
**Status**: Deferred (pending legal review and specific research need)
**Phase**: 4 / Future (not in current roadmap)
**Arena path**: `src/issue_observatory/arenas/vkontakte/`

---

## 1. Platform Overview

VKontakte (VK) is the dominant social media platform in Russia and the Commonwealth of Independent States (CIS), with approximately 100 million monthly active users. VK provides a substantially more open API than most Western social media platforms, offering direct access to public posts, comments, community content, and global keyword search -- all at the free tier.

**Role in Danish discourse**: Essentially none. VK has negligible Danish user penetration. Denmark does not have a significant Russian-speaking diaspora compared to countries such as Germany, Finland, or the Baltic states. VK is not a venue for Danish public discourse in any meaningful sense.

**Value proposition for this project**: VK's relevance lies entirely in potential future expansion scenarios:
1. Studying Russian-language influence operations targeting Danish or European discourse.
2. Comparative analysis of CIS media ecosystems.
3. Tracking Russian-language reactions to Danish policy decisions (NATO, Arctic policy, energy policy).
4. Cross-platform analysis of disinformation flows originating from Russian-language social media.

**Danish user base**: Negligible. No Danish social media surveys include VK.

---

## 2. Tier Configuration

| Tier | Service | Cost | Notes |
|------|---------|------|-------|
| **Free** | VK Official API (`api.vk.com/method/`) | $0 | Generous limits (3 req/s), comprehensive public data access |
| **Medium** | N/A | -- | Free tier is comprehensive |
| **Premium** | N/A | -- | Free tier is comprehensive |

VK is a free-only arena. The official API provides full access to public data without cost.

---

## 3. API/Access Details

### VK API

**Base URL**: `https://api.vk.com/method/`

All requests require `access_token` and `v` (API version) parameters. Current API version: `5.199`.

**Key methods**:

| Method | Description | Key Parameters |
|--------|-------------|---------------|
| `newsfeed.search` | Global keyword search across all public posts | `q`, `count` (max 200), `start_time`, `end_time`, `extended` (include profiles) |
| `wall.search` | Keyword search on a specific wall (profile/community) | `owner_id`, `query`, `count` (max 100), `owners_only` |
| `wall.get` | Get posts from a specific community/profile | `owner_id`, `count` (max 100), `offset`, `filter`, `extended` |
| `wall.getComments` | Get comments on a specific post | `owner_id`, `post_id`, `count` (max 100) |
| `groups.search` | Find communities by keyword | `q`, `type`, `country_id`, `city_id`, `count` (max 1000) |
| `groups.getMembers` | List community members | `group_id`, `count` (max 1000) |
| `users.get` | Get user profile information | `user_ids`, `fields` |
| `groups.getById` | Get community information | `group_ids`, `fields` |
| `execute` | Batch execute up to 25 API calls | VKScript code body |

**Response format**: JSON. All responses include an outer `response` key with the data payload, or an `error` key with error details.

### Authentication

OAuth 2.0 with standalone application token:
1. Create an application at `vk.com/dev` (type: "Standalone application").
2. Generate an access token with required permissions: `wall`, `groups`, `offline`.
3. Pass the token as `access_token` parameter on every request.

**Token types**:
- **User token**: Most comprehensive access. Generated via Authorization Code flow (requires browser interaction).
- **Service token**: Limited access. Generated automatically for the app.

For research collection, a **user token** with `wall` and `groups` permissions is recommended.

### Python Library

**Package**: `vk_api` (PyPI)
- Handles authentication, rate limiting (queues to respect 3 req/s), and pagination.
- Methods mirror the VK API: `vk.wall.get(owner_id=-12345, count=100)`.
- Supports the `execute` method for batching.

---

## 4. Danish Context

- **No native language filter**: VK API has no language filtering parameter on search endpoints. Content language must be determined via:
  1. Geographic filtering: `newsfeed.search` supports `latitude`/`longitude` parameters (center on Danish cities).
  2. Community curation: Identify any Danish-language communities on VK (expected to be extremely few).
  3. Keyword filtering: Search for Danish-language terms.
  4. Client-side language detection on collected text.
- **Practical Danish content**: There is virtually no Danish-language content on VK. Any research using VK in a Danish context would focus on Russian-language content *about* Denmark (e.g., searching for "Danmark", "Dania" in Russian, or specific policy topics transliterated into Russian).
- **Geographic filtering coordinates**: Copenhagen: 55.6761, 12.5683. Aarhus: 56.1629, 10.2039.

---

## 5. Data Fields

| UCR Field | VK Source | Notes |
|-----------|----------|-------|
| `platform` | `"vkontakte"` | Constant |
| `arena` | `"social_media"` | Shared arena group |
| `platform_id` | `"{owner_id}_{post_id}"` | Negative owner_id = community; positive = user. e.g., `"-12345_67890"` |
| `content_type` | `"post"` or `"comment"` | Posts from walls; comments from `wall.getComments` |
| `text_content` | `post.text` | Post text content |
| `title` | NULL | VK posts have no title field |
| `url` | `"https://vk.com/wall{owner_id}_{post_id}"` | Constructed permalink |
| `language` | NULL | No language field; detect downstream |
| `published_at` | `post.date` | Unix timestamp |
| `author_platform_id` | `post.from_id` | VK user/community ID |
| `author_display_name` | Resolved via `users.get` or `groups.getById` | **Not included in post response directly**; use `extended=1` parameter to include profiles |
| `views_count` | `post.views.count` | Available for community posts |
| `likes_count` | `post.likes.count` | |
| `shares_count` | `post.reposts.count` | |
| `comments_count` | `post.comments.count` | |
| `raw_metadata` | Full post object | Include: `attachments[]` (photos, videos, links, documents, audio), `copy_history[]` (repost chain with original post), `geo` (location if shared), `signer_id` (if community post signed by specific author), `is_pinned`, `marked_as_ads`, `post_source` (origin: API, widget, etc.), `donut` (if behind paywall) |
| `media_urls` | Extract from `attachments[].photo.sizes[-1].url` | Largest available photo resolution |

**Repost chain**: VK preserves the full repost chain in `copy_history`. Each entry contains the original post content, author, and timestamp. This is valuable for tracking content propagation.

**Author name resolution**: Post objects contain `from_id` (numeric) but not the author's name. To get names, either:
1. Use `extended=1` parameter on `wall.get` and `newsfeed.search` (includes `profiles` and `groups` arrays in response).
2. Make separate `users.get` or `groups.getById` calls.

---

## 6. Credential Requirements

| Tier | Credential Fields | CredentialPool `platform` value |
|------|------------------|-------------------------------|
| Free | `{"access_token": "...", "app_id": "..."}` | `"vkontakte"` |

**Setup process**:
1. Create an account at `vk.com` (requires phone number).
2. Create a standalone application at `vk.com/dev`.
3. Generate an access token with `wall`, `groups`, `offline` permissions.
4. Store in CredentialPool.

**Note**: VK account creation may require a Russian or CIS phone number. International numbers may work but this is not guaranteed.

---

## 7. Rate Limits and Multi-Account Notes

| Scope | Limit | Notes |
|-------|-------|-------|
| Global | 3 requests/second per access token | Strictly enforced; error code 6 on violation |
| `execute` method | 25 API calls per single request | Effectively 75 calls/second when using batch |
| Daily | No documented daily limit | |

**RateLimiter configuration**: 3 requests per second per token. Use the `execute` method for batching when making many related calls.

**Multi-account**: VK allows multiple access tokens. Each token has its own 3 req/s limit. Credential pool rotation would provide linear throughput scaling. However, creating multiple VK accounts may require multiple phone numbers and carries account suspension risk.

**`vk_api` library**: The Python `vk_api` library handles rate limiting internally by queuing requests with appropriate delays. When using this library, the project's RateLimiter serves as a safety net.

---

## 8. Known Limitations

1. **Geo-restrictions**: VK is banned or restricted in several countries (notably Ukraine). Access from some EU locations may be unreliable. API access from Denmark should be tested before implementation. A VPN or proxy may be required, with associated legal considerations.

2. **Account creation barriers**: VK account creation may require a Russian/CIS phone number. International phone numbers have mixed success.

3. **Author name resolution overhead**: Post objects do not include author names. Either use `extended=1` (which increases response size) or make separate lookup calls (which consume rate limit quota).

4. **API version sensitivity**: VK API behavior can change between versions. Always pin the `v` parameter (current: `5.199`). Test for breaking changes when updating.

5. **VKScript complexity**: The `execute` method uses VKScript, a JavaScript-like domain-specific language. Building efficient batch queries requires learning this syntax.

6. **Community privacy**: Closed (private) communities are not accessible via the API. Only public and open communities can be searched and read.

7. **Search result freshness**: `newsfeed.search` results may have a delay of several minutes from when a post is published to when it appears in search results.

8. **Sanctions and legal complexity**: EU sanctions against Russia create a complex legal landscape for research involving Russian platforms. University legal counsel should be consulted.

9. **Content in Cyrillic**: Most VK content is in Russian (Cyrillic script). Text processing pipelines, tokenization, and NLP tools must support Cyrillic. The existing Danish tokenizer in `similarity_finder.py` (regex `[a-z0-9aeoa]{2,}`) would not match Cyrillic characters.

---

## 9. Collector Implementation Notes

### Architecture

**Standard batch polling** -- VK is a conventional REST API with no streaming component.

1. **`collect_by_terms()`**: Use `newsfeed.search` for global keyword search. Paginate via the `start_from` parameter returned in responses. Apply date range filtering with `start_time`/`end_time` (Unix timestamps).

2. **`collect_by_actors()`**: Use `wall.get` with `owner_id` set to the user or community ID. Paginate via `offset`. Negative `owner_id` for communities, positive for users.

3. **Author name resolution**: When `extended=1` is used, the response includes `profiles[]` and `groups[]` arrays. Build a local lookup dict to map `from_id` to display names.

### Key Implementation Guidance

1. **Python library**: Use `vk_api` for authentication and API calls. It handles rate limiting, pagination, and error handling.

2. **Batch collection with `execute`**: For collecting posts from many communities, use the `execute` method to batch up to 25 `wall.get` calls per request. This is the most efficient collection pattern.

3. **Repost tracking**: Extract `copy_history` from post objects to track content propagation chains. Each repost references the original post, enabling network analysis of how content spreads through VK communities.

4. **Pagination**: `newsfeed.search` returns a `next_from` cursor. `wall.get` uses `offset` (numeric). Both support `count` parameter for page size.

5. **Health check**: Call `utils.getServerTime` with the access token. Verify 200 response with a valid Unix timestamp.

6. **Credit cost**: 0 credits (free tier only).

7. **Error handling**: VK API returns structured error objects with numeric error codes. Key codes: 6 (too many requests), 15 (access denied), 29 (rate limit reached). Implement retry with backoff for code 6 and 29.

---

## 10. Legal Considerations (Expanded)

- **VK Terms of Service**: Allow use of publicly available data via the API for non-commercial research. However, VK is a Russian company subject to Russian data protection law (Federal Law No. 152-FZ on Personal Data).
- **GDPR**: If the research processes personal data of EU residents found on VK, GDPR applies. For data of non-EU residents (most VK users), the legal framework differs. Pseudonymization via `pseudonymized_author_id` should be applied regardless.
- **EU Sanctions**: EU sanctions against Russia (post-2022 escalation) do not explicitly prohibit academic research use of VK, but the sanctions landscape is complex and evolving. Key considerations:
  - VK (Mail.ru Group / VK Company) is not individually sanctioned as of February 2026, but some of its controlling shareholders may be.
  - Data transfer between EU and Russia is subject to Schrems II considerations (no adequacy decision for Russia).
  - Consult with university legal counsel and DPO before implementation.
- **Geo-restrictions**: VK may block or restrict API access from certain EU IP addresses. Access availability from Denmark must be verified empirically before any development begins.
- **Ethical considerations**: Research involving Russian social media data in the current geopolitical context requires careful ethical framing:
  - Document the specific research question that requires VK data.
  - Explain why the research serves a legitimate public interest.
  - Describe data handling, access controls, and retention policies.
  - Consider whether the research could be used to identify or endanger individuals.

**Legal risk assessment**: Moderate to high. The combination of Russian jurisdiction, EU sanctions context, cross-border data transfer concerns, and potential geo-restrictions makes VK the most legally complex arena in this plan. **University legal review is mandatory before any implementation begins.**

---

## 11. Latency and Freshness

| Data Type | Latency | Notes |
|-----------|---------|-------|
| `wall.get` (posts) | Near-real-time | Posts available within seconds |
| `newsfeed.search` | Minutes | Search index has moderate delay |
| `wall.getComments` | Near-real-time | Comments available immediately |

---

## 12. Recommended Architecture Summary

| Component | Recommendation |
|-----------|---------------|
| Arena group | `"social_media"` (existing) |
| Platform name | `"vkontakte"` |
| Supported tiers | `[Tier.FREE]` |
| Collection pattern | Batch polling (REST API) |
| Python library | `vk_api` |
| RateLimiter config | 3 req/s per token |
| Credential pool | `platform="vkontakte"`, fields: `{"access_token", "app_id"}` |
| Celery queue | Default (not streaming) |
| Beat schedule | Daily (if activated for live tracking) |
| Content types | `"post"`, `"comment"` |
| Danish targeting | Keyword search for Danish topics in Russian; geographic filtering |
| Pre-implementation | **Mandatory**: University legal review of EU sanctions implications, API access verification from Denmark, VK account creation |
