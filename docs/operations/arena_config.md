# Arena Configuration Guide

## Three-Tier Pricing Model

Every arena supports up to three operational tiers:

| Tier | Key | Description |
|------|-----|-------------|
| Free | `free` | Uses only sources with no API cost. Rate-limited public endpoints, scraping, or open datasets. |
| Medium | `medium` | Low-cost paid APIs. Suitable for moderate research budgets. |
| Premium | `premium` | Best available option: highest quotas, richest data, paid per-request APIs. |

Tiers are configured per-arena within each query design's `arenas_config` JSONB field.
The `default_tier` on a query design applies to arenas without an explicit override.

---

## Credit System

Credits map to actual API cost units. The table below shows the mapping:

| Arena / API | Credit cost |
|-------------|-------------|
| Free-tier arenas (RSS, GDELT, Gab, Google Autocomplete, Bluesky, Common Crawl, Wayback) | 0 credits |
| YouTube Data API | 1 credit = 1 API unit (search endpoint = 100 credits per call) |
| Serper.dev (Google Search medium/premium) | 1 credit = 1 SERP query |
| TwitterAPI.io (X/Twitter) | 1 credit = 1 tweet retrieved |
| TikTok Research API | 1 credit = 1 API request |
| Event Registry | 1 credit = 1 article retrieved |
| Majestic | 1 credit = 1 API unit (varies by endpoint) |
| Via Ritzau | Negotiated per-subscription; contact arena maintainer |
| Telegram, Reddit, Threads, Facebook, Instagram | 0 credits (free tier); paid tier costs vary |

Credits are pre-flight estimated before a collection run launches. The user's
balance is reserved at run start and settled on completion.

---

## Per-Arena Credential Setup

### Credential storage

Credentials are stored encrypted in the `api_credentials` table.
The `credential_key` column identifies the platform; the `tier` column
identifies which tier the credential unlocks; the `encrypted_value` column
stores a Fernet-encrypted JSON object with the credential fields.

### Adding credentials

**Via admin UI:**
1. Log in as admin.
2. Navigate to Admin > Credentials.
3. Click "Add credential", select platform and tier, fill in the required fields.
4. Submit. The app encrypts and stores the credential.

**Via bootstrap script:**
```bash
docker compose exec app python scripts/bootstrap_admin.py
```
The script prompts for credentials interactively. Suitable for first-run setup.

**Via direct DB insert (advanced):**
```python
from cryptography.fernet import Fernet
import json

fernet = Fernet(settings.credential_encryption_key.encode())
encrypted = fernet.encrypt(json.dumps({"api_key": "..."}).encode()).decode()
# INSERT INTO api_credentials (platform, tier, credential_key, encrypted_value, is_active)
# VALUES ('google_search', 'medium', 'serper_api_key', :encrypted, true);
```

---

## Arena Reference

### google_search

| Property | Value |
|----------|-------|
| Arena key | `google_search` |
| Tiers | `free` (SerpApi free quota), `medium` (Serper.dev), `premium` (ValueSERP or SerpApi paid) |
| Schedule | Batch and Beat (daily live-tracking) |

**Free tier:** No credentials required. Uses SerpApi free plan (100 searches/month).

**Medium tier credential fields:**
```json
{"api_key": "<serper.dev API key>"}
```

**Premium tier credential fields:**
```json
{"api_key": "<SerpApi key or ValueSERP key>", "provider": "serpapi"}
```

**Env-var fallback:** `GOOGLE_SEARCH_API_KEY`

---

### google_autocomplete

| Property | Value |
|----------|-------|
| Arena key | `google_autocomplete` |
| Tiers | `free` only |
| Schedule | Batch only |

No credentials required. Uses the public Google Suggest endpoint.

---

### bluesky

| Property | Value |
|----------|-------|
| Arena key | `bluesky` |
| Tiers | `free` (public AppView API), `medium` (authenticated AT Protocol) |
| Schedule | Batch and Beat |

**Free tier:** No credentials required.

**Medium tier credential fields:**
```json
{"handle": "user.bsky.social", "app_password": "<app password>"}
```

**Env-var fallback:** `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD`

---

### reddit

| Property | Value |
|----------|-------|
| Arena key | `reddit` |
| Tiers | `free` (public PRAW read-only), `medium` (authenticated script app) |
| Schedule | Batch and Beat |

**Free tier:** No credentials required.

**Medium tier credential fields:**
```json
{
  "client_id": "<Reddit app client_id>",
  "client_secret": "<Reddit app client_secret>",
  "user_agent": "IssueObservatory/0.1"
}
```

**Env-var fallback:** `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`

---

### youtube

| Property | Value |
|----------|-------|
| Arena key | `youtube` |
| Tiers | `free` (YouTube Data API v3 — 10,000 units/day free quota) |
| Schedule | Batch and Beat |

**Free tier credential fields:**
```json
{"api_key": "<Google Cloud API key with YouTube Data API v3 enabled>"}
```

**Env-var fallback:** `YOUTUBE_API_KEY`

---

### rss_feeds

| Property | Value |
|----------|-------|
| Arena key | `rss_feeds` |
| Tiers | `free` only |
| Schedule | Beat (hourly) |

No credentials required. Feed URLs are configured in the query design's
`arenas_config` under the `rss_feeds` key:
```json
{"rss_feeds": {"tier": "free", "feeds": ["https://example.dk/rss"]}}
```

---

### gdelt

| Property | Value |
|----------|-------|
| Arena key | `gdelt` |
| Tiers | `free` only |
| Schedule | Batch only |

No credentials required. Uses the public GDELT 2.0 Event/GKG API.

---

### telegram

| Property | Value |
|----------|-------|
| Arena key | `telegram` |
| Tiers | `free` (Telethon MTProto client) |
| Schedule | Batch and Beat |

**Free tier credential fields:**
```json
{
  "api_id": 12345,
  "api_hash": "<Telegram API hash>",
  "phone": "+4512345678",
  "session_string": "<serialized Telethon session>"
}
```

**Env-var fallback:** `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`

Note: The first run requires interactive phone verification to create the
session string. Run `python scripts/telegram_auth.py` to generate it.

---

### tiktok

| Property | Value |
|----------|-------|
| Arena key | `tiktok` |
| Tiers | `free` (TikTok Research API — requires academic access application) |
| Schedule | Batch only |

**Free tier credential fields:**
```json
{"client_key": "<TikTok Research API client key>", "client_secret": "<secret>"}
```

**Env-var fallback:** `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`

---

### gab

| Property | Value |
|----------|-------|
| Arena key | `gab` |
| Tiers | `free` only |
| Schedule | Batch only |

No credentials required. Uses the public Gab API endpoints.

---

### ritzau_via

| Property | Value |
|----------|-------|
| Arena key | `ritzau_via` |
| Tiers | `premium` (subscription required) |
| Schedule | Beat (hourly) |

**Premium tier credential fields:**
```json
{"username": "<Via Ritzau username>", "password": "<Via Ritzau password>"}
```

**Env-var fallback:** `RITZAU_VIA_USERNAME`, `RITZAU_VIA_PASSWORD`

---

### x_twitter

| Property | Value |
|----------|-------|
| Arena key | `x_twitter` |
| Tiers | `medium` (TwitterAPI.io), `premium` (X Official API v2 Basic/Pro) |
| Schedule | Batch and Beat |

**Medium tier credential fields:**
```json
{"api_key": "<TwitterAPI.io key>"}
```

**Premium tier credential fields:**
```json
{
  "bearer_token": "<X API v2 Bearer Token>",
  "api_key": "<X API Key>",
  "api_secret": "<X API Secret>",
  "access_token": "<Access Token>",
  "access_token_secret": "<Access Token Secret>"
}
```

**Env-var fallback:** `X_TWITTER_BEARER_TOKEN`, `X_TWITTER_API_KEY`

---

### threads

| Property | Value |
|----------|-------|
| Arena key | `threads` |
| Tiers | `free` (public graph endpoints), `medium` (Meta Threads API) |
| Schedule | Batch only |

**Medium tier credential fields:**
```json
{"access_token": "<Meta Threads API long-lived access token>"}
```

**Env-var fallback:** `THREADS_ACCESS_TOKEN`

---

### facebook

| Property | Value |
|----------|-------|
| Arena key | `facebook` |
| Tiers | `medium` (Meta Graph API — page access tokens) |
| Schedule | Batch only |

**Medium tier credential fields:**
```json
{"page_access_token": "<Meta Graph API page access token>", "app_id": "<App ID>"}
```

**Env-var fallback:** `FACEBOOK_PAGE_ACCESS_TOKEN`

---

### instagram

| Property | Value |
|----------|-------|
| Arena key | `instagram` |
| Tiers | `medium` (Meta Graph API — Instagram Basic Display or Business) |
| Schedule | Batch only |

**Medium tier credential fields:**
```json
{"access_token": "<Instagram Graph API token>", "app_id": "<App ID>"}
```

**Env-var fallback:** `INSTAGRAM_ACCESS_TOKEN`

---

### event_registry

| Property | Value |
|----------|-------|
| Arena key | `event_registry` |
| Tiers | `medium` (Event Registry standard plan), `premium` (Event Registry professional) |
| Schedule | Batch and Beat |

**Medium/premium tier credential fields:**
```json
{"api_key": "<Event Registry API key>"}
```

**Env-var fallback:** `EVENT_REGISTRY_API_KEY`

---

### majestic

| Property | Value |
|----------|-------|
| Arena key | `majestic` |
| Tiers | `premium` (Majestic API) |
| Schedule | Batch only |

**Premium tier credential fields:**
```json
{"api_key": "<Majestic API key>"}
```

**Env-var fallback:** `MAJESTIC_API_KEY`

---

### common_crawl (web)

| Property | Value |
|----------|-------|
| Arena key | `common_crawl` |
| Tiers | `free` only |
| Schedule | Batch only |

No credentials required. Uses the public Common Crawl Index API.

---

### wayback (web)

| Property | Value |
|----------|-------|
| Arena key | `wayback` |
| Tiers | `free` only |
| Schedule | Batch only |

No credentials required. Uses the public Wayback Machine CDX API.

---

## Beat Schedule Summary

| Arena | Runs on Beat | Frequency |
|-------|-------------|-----------|
| rss_feeds | Yes | Hourly |
| ritzau_via | Yes | Hourly |
| google_search | Yes | Daily (trigger_daily_collection) |
| bluesky | Yes | Daily |
| reddit | Yes | Daily |
| youtube | Yes | Daily |
| telegram | Yes | Daily |
| x_twitter | Yes | Daily |
| event_registry | Yes | Daily |
| google_autocomplete | No | Batch only |
| gdelt | No | Batch only |
| tiktok | No | Batch only |
| gab | No | Batch only |
| threads | No | Batch only |
| facebook | No | Batch only |
| instagram | No | Batch only |
| majestic | No | Batch only |
| common_crawl | No | Batch only |
| wayback | No | Batch only |
