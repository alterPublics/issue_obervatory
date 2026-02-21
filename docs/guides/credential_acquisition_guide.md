# Credential Acquisition Guide -- The Issue Observatory

**Created:** 2026-02-21
**Last updated:** 2026-02-21
**Author:** Research Agent

---

## Table of Contents

1. [Overview and Prerequisites](#1-overview-and-prerequisites)
2. [Infrastructure Credentials](#2-infrastructure-credentials)
3. [Free Tier Arenas](#3-free-tier-arenas)
   - 3.1 [Bluesky](#31-bluesky)
   - 3.2 [Reddit](#32-reddit)
   - 3.3 [YouTube](#33-youtube)
   - 3.4 [RSS Feeds](#34-rss-feeds)
   - 3.5 [GDELT](#35-gdelt)
   - 3.6 [Telegram](#36-telegram)
   - 3.7 [TikTok](#37-tiktok)
   - 3.8 [Via Ritzau](#38-via-ritzau)
   - 3.9 [Gab](#39-gab)
   - 3.10 [Common Crawl](#310-common-crawl)
   - 3.11 [Wayback Machine](#311-wayback-machine)
   - 3.12 [URL Scraper](#312-url-scraper)
   - 3.13 [Wikipedia](#313-wikipedia)
   - 3.14 [Discord](#314-discord)
   - 3.15 [Threads](#315-threads)
4. [Medium Tier Arenas](#4-medium-tier-arenas)
   - 4.1 [Google Search / Google Autocomplete](#41-google-search--google-autocomplete)
   - 4.2 [Event Registry (NewsAPI.ai)](#42-event-registry-newsapiai)
   - 4.3 [X/Twitter (via TwitterAPI.io)](#43-xtwitter-via-twitterapiio)
   - 4.4 [AI Chat Search (via OpenRouter)](#44-ai-chat-search-via-openrouter)
5. [Premium Tier Arenas](#5-premium-tier-arenas)
   - 5.1 [Facebook (via Bright Data / MCL)](#51-facebook-via-bright-data--mcl)
   - 5.2 [Instagram (via Bright Data)](#52-instagram-via-bright-data)
   - 5.3 [Majestic](#53-majestic)
6. [Deferred Arenas](#6-deferred-arenas)
   - 6.1 [Twitch](#61-twitch)
   - 6.2 [VKontakte](#62-vkontakte)
7. [Credential Pool System](#7-credential-pool-system)
8. [Adding Credentials via Admin UI vs. Environment Variables](#8-adding-credentials-via-admin-ui-vs-environment-variables)
9. [Environment Variable Reference](#9-environment-variable-reference)
10. [Redis Configuration for Credential Leasing](#10-redis-configuration-for-credential-leasing)
11. [Quick-Start Checklist](#11-quick-start-checklist)

---

## 1. Overview and Prerequisites

This guide provides step-by-step instructions for obtaining all credentials needed to run the Issue Observatory's data collection arenas. The system supports 25 arenas across free, medium, and premium tiers.

### Before You Begin

You will need:
- A working Issue Observatory installation (see the main README)
- PostgreSQL 16+ and Redis 7+ running
- A valid `CREDENTIAL_ENCRYPTION_KEY` (Fernet key) in your `.env` file
- Admin access to the Issue Observatory web interface

### Credential Storage Methods

Credentials can be stored in two ways:

1. **Environment variables** (`.env` file) -- suitable for development and single-credential setups
2. **Database credential pool** (via Admin UI) -- recommended for production, supports multiple keys per arena, Fernet encryption, lease tracking, and quota management

### How to Read This Guide

For each arena, the following information is provided:

| Field | Meaning |
|-------|---------|
| **Credentials needed** | What type of key/token/secret is required |
| **Signup URL** | Where to register for access |
| **Steps** | Numbered walkthrough of the signup process |
| **Tier(s)** | Which Issue Observatory tier(s) this unlocks |
| **Pricing** | Cost information as of February 2026 |
| **Special requirements** | Approval processes, business accounts, etc. |
| **Environment variable(s)** | Exact `.env` variable name(s) |
| **Rate limits** | Platform-imposed request limits |

---

## 2. Infrastructure Credentials

Before configuring any arena, set up the core application credentials.

### 2.1 Application Secret Key

| Field | Value |
|-------|-------|
| Env variable | `SECRET_KEY` |
| Purpose | Signs session cookies and CSRF tokens |
| Generation | `openssl rand -hex 32` |

**Steps:**
1. Open a terminal.
2. Run: `openssl rand -hex 32`
3. Copy the output.
4. Set `SECRET_KEY=<output>` in your `.env` file.

### 2.2 Credential Encryption Key (Fernet)

| Field | Value |
|-------|-------|
| Env variable | `CREDENTIAL_ENCRYPTION_KEY` |
| Purpose | Encrypts all API credentials stored in the database |
| Generation | `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` |

**Steps:**
1. Ensure `cryptography` is installed: `pip install cryptography`
2. Run: `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`
3. Copy the output (a base64-encoded string).
4. Set `CREDENTIAL_ENCRYPTION_KEY=<output>` in your `.env` file.

**WARNING:** If this key is lost, all stored credentials become unrecoverable. Back it up securely.

### 2.3 Pseudonymization Salt (GDPR Requirement)

| Field | Value |
|-------|-------|
| Env variable | `PSEUDONYMIZATION_SALT` |
| Purpose | GDPR-compliant SHA-256 pseudonymization of author identifiers |
| Generation | `openssl rand -hex 32` |

**Steps:**
1. Run: `openssl rand -hex 32`
2. Set `PSEUDONYMIZATION_SALT=<output>` in your `.env` file.

The application will refuse to start without a valid salt value.

### 2.4 Database and Redis

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `postgresql+asyncpg://observatory:observatory@localhost:5432/issue_observatory` | PostgreSQL connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for caching and rate limiting |
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | Celery task broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/2` | Celery result storage |

---

## 3. Free Tier Arenas

### 3.1 Bluesky

| Field | Details |
|-------|---------|
| **Credentials needed** | None for read-only public API access. Optional: Bluesky account handle + app password for authenticated access. |
| **Signup URL** | https://bsky.app (account creation); https://bsky.app/settings/app-passwords (app passwords) |
| **Tier(s)** | FREE only |
| **Pricing** | Completely free |
| **Rate limits** | 3,000 requests / 5 minutes (600 req/min) unauthenticated |

**What This Arena Collects:** Posts from the Bluesky social network via the AT Protocol public API, with `lang:da` filtering for Danish content. Also supports WebSocket Jetstream firehose for real-time collection.

**Steps:**
1. No credentials are strictly required. The Bluesky AT Protocol public API at `https://public.api.bsky.app/xrpc` allows unauthenticated read access to public posts.
2. (Optional) To use authenticated endpoints or increase rate limits:
   a. Create a Bluesky account at https://bsky.app if you do not already have one.
   b. Navigate to Settings > App Passwords (https://bsky.app/settings/app-passwords).
   c. Click "Add App Password" and give it a descriptive name (e.g., "IssueObservatory").
   d. Copy the generated password (format: `xxxx-xxxx-xxxx-xxxx`). This is shown only once.

**Environment Variables:**
```
BLUESKY_HANDLE=your-handle.bsky.social
BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
```

**Credential Pool (Admin UI):**
- Platform: `bluesky`
- Tier: `free`
- Payload: `{"handle": "your-handle.bsky.social", "app_password": "xxxx-xxxx-xxxx-xxxx"}`

**Rate Limits:**
- Unauthenticated: 3,000 requests per 5 minutes (enforced per IP)
- Authenticated: Same limit but per-account rather than per-IP
- Jetstream WebSocket: No explicit rate limit on subscriptions

---

### 3.2 Reddit

| Field | Details |
|-------|---------|
| **Credentials needed** | OAuth2 client ID + client secret |
| **Signup URL** | https://www.reddit.com/prefs/apps |
| **Tier(s)** | FREE only |
| **Pricing** | Free for non-commercial academic use |
| **Special requirements** | Reddit account required; must agree to Reddit's Responsible Builder Policy |
| **Rate limits** | 100 requests/minute per OAuth client (system configured at 90 req/min for safety) |

**What This Arena Collects:** Posts and optionally comments from Danish-relevant subreddits (r/Denmark, r/danish, r/copenhagen, r/aarhus, r/dkpolitik, r/dkfinance, r/scandinavia, r/NORDVANSEN) plus any researcher-configured subreddits.

**Steps:**
1. Log in to Reddit at https://www.reddit.com (create an account if needed).
2. Navigate to https://www.reddit.com/prefs/apps.
3. Scroll to the bottom and click **"are you a developer? create an app..."**.
4. Fill in the form:
   - **Name:** `IssueObservatory` (or your preferred name)
   - **App type:** Select **"script"** (for server-side academic use)
   - **Description:** `Academic research data collection tool`
   - **About URL:** (leave blank or enter your project URL)
   - **Redirect URI:** `http://localhost:8000/callback` (required but not used for script apps)
5. Click **"create app"**.
6. Note down two values:
   - **Client ID:** The string shown directly under the app name (below "personal use script")
   - **Client Secret:** The string labeled "secret"

**Environment Variables:**
```
REDDIT_CLIENT_ID=your_client_id_here
REDDIT_CLIENT_SECRET=your_client_secret_here
REDDIT_USER_AGENT=IssueObservatory/1.0 (academic research project)
```

**Credential Pool (Admin UI):**
- Platform: `reddit`
- Tier: `free`
- Payload: `{"client_id": "...", "client_secret": "...", "user_agent": "IssueObservatory/1.0 (academic research project)"}`

**Rate Limits:**
- 100 requests per minute per OAuth client
- System configured at 90 req/min to maintain headroom
- Reddit blocks requests with generic user agents -- always use a descriptive `user_agent`

---

### 3.3 YouTube

| Field | Details |
|-------|---------|
| **Credentials needed** | Google Cloud API key |
| **Signup URL** | https://console.cloud.google.com |
| **Tier(s)** | FREE (MEDIUM and PREMIUM tiers exist but use identical quotas) |
| **Pricing** | Free (10,000 quota units/day per GCP project) |
| **Special requirements** | Google account required |
| **Rate limits** | 10,000 quota units/day; search.list costs 100 units per call |

**What This Arena Collects:** YouTube videos via the Data API v3 search endpoint and channel RSS feeds. RSS-first strategy (zero quota cost) is used for channel-based collection; search is reserved for keyword discovery.

**Steps:**
1. Go to https://console.cloud.google.com and sign in with your Google account.
2. Click the project selector at the top of the page, then click **"New Project"**.
3. Name your project (e.g., `issue-observatory`) and click **"Create"**.
4. Select the newly created project.
5. Navigate to **APIs & Services > Library** in the left sidebar.
6. Search for **"YouTube Data API v3"** and click on it.
7. Click **"Enable"**.
8. Navigate to **APIs & Services > Credentials**.
9. Click **"Create Credentials" > "API key"**.
10. Copy the generated API key.
11. (Recommended) Click on the newly created key to add restrictions:
    - Under "API restrictions", select "Restrict key" and choose only "YouTube Data API v3".
    - Click **"Save"**.

**Multiplying Quota:** Create additional GCP projects (each with its own API key) to multiply your effective daily quota. For example, 3 keys = 30,000 units/day. Add them as separate credential pool entries.

**Environment Variables:**
```
YOUTUBE_API_KEY=AIza...your_key_here
```

Additional keys use the naming convention:
```
YOUTUBE_FREE_API_KEY=AIza...key_1
YOUTUBE_FREE_API_KEY_2=AIza...key_2
YOUTUBE_FREE_API_KEY_3=AIza...key_3
```

**Credential Pool (Admin UI):**
- Platform: `youtube`
- Tier: `free`
- Payload: `{"api_key": "AIza..."}`
- Add one entry per GCP project key

**Rate Limits and Quota Costs:**

| Endpoint | Quota Cost |
|----------|-----------|
| `search.list` | 100 units/call |
| `videos.list` | 1 unit/call (batch up to 50 IDs) |
| `channels.list` | 1 unit/call |
| `commentThreads.list` | 1 unit/call |
| `comments.list` | 1 unit/call |

Daily quota: 10,000 units per project. Quota resets at midnight Pacific Time.

---

### 3.4 RSS Feeds

| Field | Details |
|-------|---------|
| **Credentials needed** | None |
| **Signup URL** | N/A |
| **Tier(s)** | FREE only |
| **Pricing** | Completely free |
| **Rate limits** | Self-imposed: 60 req/min, 0.5s delay between requests to same outlet |

**What This Arena Collects:** News articles from 28+ curated Danish RSS feeds including DR, TV2, BT, Politiken, Berlingske, Ekstra Bladet, Information, Jyllands-Posten, Nordjyske, Borsen, Kristeligt Dagblad, Altinget (main + section feeds), and education-sector feeds (Folkeskolen, Gymnasieskolen, KU, DTU, CBS). Researchers can add custom feeds via the query design `arenas_config`.

**Setup:**
No credentials or environment variables are needed. The RSS Feeds arena uses `feedparser` to fetch publicly available RSS/Atom feeds directly. The feed list is built into the application at `src/issue_observatory/config/danish_defaults.py`.

**Adding Custom Feeds:**
Researchers can add custom RSS feed URLs via the Query Design editor. These are stored in:
```
arenas_config["rss"]["custom_feeds"] = ["https://example.dk/feed.xml", ...]
```

---

### 3.5 GDELT

| Field | Details |
|-------|---------|
| **Credentials needed** | None |
| **Signup URL** | N/A |
| **Tier(s)** | FREE only |
| **Pricing** | Completely free |
| **Rate limits** | Approximately 1 request/second (empirical) |

**What This Arena Collects:** Global news articles from the GDELT Project's DOC 2.0 API, filtered by `sourcelang:danish` and `sourcecountry:DA`. Note: GDELT's Danish coverage has approximately 55% accuracy with translation artifacts.

**Setup:**
No credentials or environment variables are needed. The GDELT DOC 2.0 API at `https://api.gdeltproject.org/api/v2/doc/doc` is entirely free and unauthenticated.

**Environment Variables (optional override):**
```
GDELT_DOC_API_URL=https://api.gdeltproject.org/api/v2/doc/doc
```

**Rate Limits:**
- No documented rate limit
- Empirical safe rate: 1 request per second
- System configured at 60 req/min
- Maximum 250 records per API request (hard API limit)

---

### 3.6 Telegram

| Field | Details |
|-------|---------|
| **Credentials needed** | Telegram API ID + API Hash + session string |
| **Signup URL** | https://my.telegram.org/apps |
| **Tier(s)** | FREE only |
| **Pricing** | Free |
| **Special requirements** | Active Telegram account with verified phone number; one-time interactive session authorization |
| **Rate limits** | No fixed rate; FloodWaitError-based throttling. System configured at 20 req/min. |

**What This Arena Collects:** Messages from public Telegram broadcast channels using the MTProto protocol via the Telethon library. Default Danish channels include dr_nyheder, tv2nyhederne, berlingske, politiken_dk, bt_dk, and informationdk. Researchers can add custom channels.

**Steps:**

**Part A -- Obtain API ID and API Hash:**
1. Open https://my.telegram.org in your browser.
2. Enter the phone number associated with your Telegram account (with country code, e.g., `+45...`).
3. Telegram will send a confirmation code via the Telegram app (not SMS). Enter it.
4. Click **"API development tools"**.
5. If you have not created an application before, fill out the form:
   - **App title:** `IssueObservatory`
   - **Short name:** `issueobs`
   - **URL:** (leave blank or enter your project URL)
   - **Platform:** `Other`
   - **Description:** `Academic research data collection`
6. Click **"Create application"**.
7. Note down:
   - **App api_id:** A numeric value (e.g., `12345678`)
   - **App api_hash:** A hexadecimal string (e.g., `abc123def456...`)

**Part B -- Generate a Session String:**

The session string is a serialized Telethon session that avoids re-authenticating on every run. Generate it once:

```python
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = 12345678          # Your api_id from step A.7
api_hash = "abc123def456"  # Your api_hash from step A.7

with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("Session string:", client.session.save())
```

When you run this script:
1. It will prompt for your phone number.
2. Telegram sends a code to your Telegram app. Enter it.
3. If you have 2FA enabled, enter your password.
4. The script prints a long base64-encoded session string. Copy and save it.

**Environment Variables:**
```
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abc123def456...
TELEGRAM_PHONE=+4512345678
```

**Credential Pool (Admin UI):**
- Platform: `telegram`
- Tier: `free`
- Payload: `{"api_id": 12345678, "api_hash": "abc123...", "session_string": "1BQA..."}`

**Rate Limits:**
- No published fixed rate limit
- Telegram uses `FloodWaitError` with dynamic backoff
- System uses a conservative baseline of 20 requests per minute
- Always honor the `FloodWaitError.seconds` attribute exactly

**Important Notes:**
- Each phone number can only have one api_id.
- The session string is equivalent to being logged in as you. Store it with the same security as a password.
- Only public broadcast channels are accessible. Encrypted Secret Chats and private groups cannot be monitored.

---

### 3.7 TikTok

| Field | Details |
|-------|---------|
| **Credentials needed** | TikTok Research API client key + client secret |
| **Signup URL** | https://developers.tiktok.com/products/research-api/ |
| **Tier(s)** | FREE only |
| **Pricing** | Free for approved academic researchers |
| **Special requirements** | Must be affiliated with a non-profit university in the US or Europe; application reviewed by TikTok; approval takes approximately 2 weeks |
| **Rate limits** | 1,000 requests/day; 100 results per request; 30-day max date range per query |

**What This Arena Collects:** TikTok videos matching keyword queries with `region_code=DK` filtering. Note the 10-day engagement lag: view, like, share, and comment counts are only accurate after approximately 10 days.

**Steps:**
1. Navigate to https://developers.tiktok.com/.
2. Log in or create a TikTok for Developers account.
3. Go to **Products > Research API** (https://developers.tiktok.com/products/research-api/).
4. Click **"Apply for Access"**.
5. Fill out the application form:
   - **Principal researcher name** and institutional affiliation
   - **Research topic** and description
   - **Intended use** of the data
   - **Expected data volume**
6. Submit the application. Approval typically takes approximately 2 weeks.
7. Once approved, log in to the TikTok for Developers portal.
8. Navigate to your approved organization.
9. Create a new application under the Research API product.
10. Note down:
    - **Client Key** (also called client_key)
    - **Client Secret** (also called client_secret)

**Environment Variables:**
```
TIKTOK_CLIENT_KEY=your_client_key
TIKTOK_CLIENT_SECRET=your_client_secret
```

**Credential Pool (Admin UI):**
- Platform: `tiktok`
- Tier: `free`
- Payload: `{"client_key": "...", "client_secret": "..."}`

**Rate Limits:**
- 1,000 requests per day (resets at 12:00 AM UTC)
- 100 results per request (`max_count=100`)
- 30-day maximum date range per query
- Access tokens expire every 2 hours (system caches and auto-refreshes in Redis)

**Important Notes:**
- The principal researcher can add up to 9 collaborators.
- The application must be submitted by the project's principal researcher.
- EU-based researchers are eligible under DSA Article 40 provisions.

---

### 3.8 Via Ritzau

| Field | Details |
|-------|---------|
| **Credentials needed** | None |
| **Signup URL** | N/A |
| **Tier(s)** | FREE only |
| **Pricing** | Completely free |
| **Rate limits** | No documented limit; courtesy throttle of 10 req/min |

**What This Arena Collects:** Danish press releases from government, companies, NGOs, police, and other organizations via the Via Ritzau public JSON API.

**Setup:**
No credentials, no signup, no environment variables needed. The API at `https://via.ritzau.dk/json/v2` is fully public and unauthenticated.

---

### 3.9 Gab

| Field | Details |
|-------|---------|
| **Credentials needed** | OAuth 2.0 bearer token (Mastodon-compatible API) |
| **Signup URL** | https://gab.com (account); https://gab.com/settings/applications (developer apps) |
| **Tier(s)** | FREE only |
| **Pricing** | Free (Gab Pro membership may be required for developer API access) |
| **Special requirements** | Gab account required; Gab Pro subscription may be required for API access |
| **Rate limits** | ~300 requests / 5 minutes (Mastodon default); system configured at 40 req/min |

**What This Arena Collects:** Posts from Gab using the Mastodon-compatible API. Supports keyword search (may be limited), hashtag timelines, and account-based collection. Danish-relevant content is sparse on Gab.

**Steps:**
1. Create a Gab account at https://gab.com.
2. Navigate to **Settings > Developer Apps** (https://gab.com/settings/applications).
3. Click **"New Application"**.
4. Fill in the form:
   - **Application name:** `IssueObservatory`
   - **Redirect URI:** `urn:ietf:wg:oauth:2.0:oob`
   - **Scopes:** Select `read` (read-only access is sufficient)
5. Click **"Submit"**.
6. Note down:
   - **Client ID**
   - **Client Secret**
7. Obtain a bearer token using the OAuth 2.0 client credentials flow:
   ```
   POST https://gab.com/oauth/token
   Content-Type: application/x-www-form-urlencoded

   grant_type=client_credentials
   client_id=YOUR_CLIENT_ID
   client_secret=YOUR_CLIENT_SECRET
   scope=read
   ```
8. The response includes an `access_token`. Copy it.

**Credential Pool (Admin UI):**
- Platform: `gab`
- Tier: `free`
- Payload: `{"access_token": "your_bearer_token", "client_id": "...", "client_secret": "..."}`

**Rate Limits:**
- ~300 requests per 5 minutes (Mastodon default)
- System configured at 40 req/min with headroom
- Full-text search (`/api/v2/search`) may return HTTP 422; falls back to hashtag timeline

**Important Notes:**
- Gab Pro may be required for API access. Verify current requirements on the platform.
- Danish-relevant content volume on Gab is very low.
- The Mastodon-compatible API documentation at https://docs.joinmastodon.org applies.

---

### 3.10 Common Crawl

| Field | Details |
|-------|---------|
| **Credentials needed** | None |
| **Signup URL** | N/A |
| **Tier(s)** | FREE only |
| **Pricing** | Completely free (data hosted on AWS S3 as a public dataset) |
| **Rate limits** | Approximately 1 request/second (informal) |

**What This Arena Collects:** Web page captures from the Common Crawl index, filtered by Danish `.dk` TLD and `dan` (ISO 639-3) language code. Useful for historical web content analysis.

**Setup:**
No credentials or environment variables needed. The Common Crawl Index API at `https://index.commoncrawl.org` is entirely free and unauthenticated.

**Access Points:**
- Index API: `https://index.commoncrawl.org/{index}/search`
- Collection info: `https://index.commoncrawl.org/collinfo.json`
- Raw data (S3): `s3://commoncrawl/` or `https://data.commoncrawl.org/`

**Rate Limits:**
- ~1 request per second (informal courtesy limit)
- System configured at 60 req/min with max 3 concurrent requests

---

### 3.11 Wayback Machine

| Field | Details |
|-------|---------|
| **Credentials needed** | None |
| **Signup URL** | N/A |
| **Tier(s)** | FREE only |
| **Pricing** | Completely free |
| **Rate limits** | ~1 req/sec for CDX search; ~15 req/min for content retrieval |

**What This Arena Collects:** Historical captures of Danish web pages from the Internet Archive's Wayback Machine CDX API. Supports optional content fetching for archived pages (configurable via `arenas_config["wayback"]["fetch_content"]`).

**Setup:**
No credentials or environment variables needed. The CDX API at `https://web.archive.org/cdx/search/cdx` is entirely free and unauthenticated.

**Access Points:**
- CDX API: `https://web.archive.org/cdx/search/cdx`
- Availability API: `https://archive.org/wayback/available`
- Content playback: `https://web.archive.org/web/{timestamp}id_/{url}`

**Rate Limits:**
- CDX search: ~1 request per second (IP-rate-limited)
- Content retrieval: 15 requests per minute (stricter separate limit)
- Content fetch size limit: 500 KB max per page
- Per-run content fetch limits: 50 (FREE tier), 200 (MEDIUM tier)

---

### 3.12 URL Scraper

| Field | Details |
|-------|---------|
| **Credentials needed** | None |
| **Signup URL** | N/A |
| **Tier(s)** | FREE, MEDIUM |
| **Pricing** | Completely free (self-hosted extraction) |
| **Rate limits** | 1 req/sec per domain (FREE), 2 req/sec per domain (MEDIUM) |

**What This Arena Collects:** Web page content extracted from researcher-provided URL lists using `trafilatura` for text extraction. MEDIUM tier adds Playwright fallback for JavaScript-rendered pages.

**Setup:**
No credentials or environment variables needed. This arena is entirely self-hosted and fetches live web pages directly.

**Tier Differences:**
- **FREE:** Up to 100 URLs per run, 1 req/sec per domain, httpx only
- **MEDIUM:** Up to 500 URLs per run, 2 req/sec per domain, Playwright fallback for JS pages

For MEDIUM tier Playwright support, install the optional dependency:
```bash
pip install playwright
playwright install chromium
```

---

### 3.13 Wikipedia

| Field | Details |
|-------|---------|
| **Credentials needed** | None (only a descriptive User-Agent header is required) |
| **Signup URL** | N/A |
| **Tier(s)** | FREE only |
| **Pricing** | Completely free |
| **Rate limits** | Wikimedia guideline: stay below ~200 req/sec; system targets 5 req/sec |

**What This Arena Collects:** Article revisions and pageview data from Danish Wikipedia (da.wikipedia.org) and English Wikipedia (en.wikipedia.org). Monitors seed articles for editorial activity that may signal public attention.

**Setup:**
No credentials or environment variables needed. The MediaWiki Action API and Wikimedia Analytics API are fully open with no API key requirement.

**Environment Variables (optional):**
```
WIKIPEDIA_USER_AGENT=IssueObservatory/1.0 (https://github.com/issue-observatory; contact@observatory.dk) python-httpx
```

The default User-Agent is already configured in the arena's config module. Override it only if you need a different contact address.

**Rate Limits:**
- Wikimedia requests automated tools stay below ~200 req/sec
- System targets 5 req/sec (300 req/min) as a polite baseline
- Requests without a descriptive User-Agent may be throttled or blocked

**Important Notes:**
- Wikimedia API etiquette requires a meaningful User-Agent with a contact address.
- Pageview data has approximately 24-hour delay.
- Bot edits are filtered out by default to focus on human editorial attention.

---

### 3.14 Discord

| Field | Details |
|-------|---------|
| **Credentials needed** | Bot token |
| **Signup URL** | https://discord.com/developers/applications |
| **Tier(s)** | FREE only |
| **Pricing** | Free |
| **Special requirements** | The bot must be invited to each server you want to monitor; MESSAGE_CONTENT privileged intent required |
| **Rate limits** | 5 req/sec global; ~5 req/5 sec per route for message history |

**What This Arena Collects:** Messages from Discord channels where the bot has been invited. No server-side keyword search -- all term matching is client-side.

**Steps:**

**Part A -- Create a Bot Application:**
1. Go to https://discord.com/developers/applications.
2. Log in with your Discord account.
3. Click **"New Application"** in the top right.
4. Enter a name (e.g., `IssueObservatory`) and click **"Create"**.
5. On the application page, note the **Application ID**.

**Part B -- Add a Bot User:**
1. In the left sidebar, click **"Bot"**.
2. Click **"Add Bot"** (or it may be created automatically).
3. Under the bot settings:
   - Toggle **"MESSAGE CONTENT INTENT"** to ON (required to read message content).
   - Optionally toggle off "Public Bot" if you do not want others to invite it.
4. Click **"Reset Token"** to generate a bot token.
5. Copy the token immediately. It is shown only once.

**Part C -- Invite the Bot to Servers:**
1. In the left sidebar, click **"OAuth2" > "URL Generator"**.
2. Under "Scopes", select **`bot`**.
3. Under "Bot Permissions", select:
   - `Read Messages/View Channels`
   - `Read Message History`
4. Copy the generated URL at the bottom.
5. Open the URL in your browser. Select the server you want to add the bot to and click **"Authorize"**.
6. Repeat for each server you want to monitor.

**Environment Variables:**
```
DISCORD_BOT_TOKEN=your_bot_token_here
```

**Credential Pool (Admin UI):**
- Platform: `discord`
- Tier: `free`
- Payload: `{"bot_token": "..."}`

**Rate Limits:**
- Global: 50 requests per second (documented)
- Per-route for `GET /channels/{id}/messages`: approximately 5 requests per 5 seconds
- System configured at 300 req/min (5 req/sec)
- Rate limit headers (`X-RateLimit-*`) are parsed at runtime

**Important Notes:**
- The bot can only see channels it has been explicitly granted access to.
- The MESSAGE_CONTENT privileged intent must be enabled in the Developer Portal, otherwise message content will be empty.
- There is no way to search messages by keyword via the bot API; all filtering is done client-side.

---

### 3.15 Threads

| Field | Details |
|-------|---------|
| **Credentials needed** | OAuth 2.0 long-lived access token |
| **Signup URL** | https://developers.facebook.com (Meta for Developers) |
| **Tier(s)** | FREE (MEDIUM via MCL is not yet implemented) |
| **Pricing** | Free |
| **Special requirements** | Meta Developer App required; Threads/Instagram account required |
| **Rate limits** | 250 API calls per hour per user token (~4 req/min) |

**What This Arena Collects:** Threads posts from specific accounts. The FREE tier is actor-first: there is no global keyword search. `collect_by_terms()` iterates over a curated account list and filters client-side.

**Steps:**

**Part A -- Create a Meta Developer App:**
1. Go to https://developers.facebook.com and log in.
2. Click **"My Apps"** then **"Create App"**.
3. Select **"Access the Threads API"** as the use case.
4. Give your app a name (e.g., `IssueObservatory`) and provide a contact email.
5. Click **"Create App"**.
6. In your app's settings, add the product **"Threads API"** if not auto-added.

**Part B -- Configure Permissions:**
1. In the app dashboard, ensure the following permissions are included:
   - `threads_basic` (auto-selected)
   - `threads_content_publish` (optional, for testing)
2. Add your Threads/Instagram test account under **"Roles > Test Users"**.

**Part C -- Generate a Long-Lived Access Token:**
1. Use the Threads authorization flow to obtain a short-lived token:
   - Direct users to: `https://threads.net/oauth/authorize?client_id={APP_ID}&redirect_uri={REDIRECT_URI}&scope=threads_basic&response_type=code`
   - Exchange the authorization code for a short-lived token.
2. Exchange the short-lived token for a long-lived token:
   ```
   GET https://graph.threads.net/access_token
     ?grant_type=th_exchange_token
     &client_secret={APP_SECRET}
     &access_token={SHORT_LIVED_TOKEN}
   ```
3. The long-lived token is valid for 60 days. The system auto-refreshes tokens at day 55.

**Credential Pool (Admin UI):**
- Platform: `threads`
- Tier: `free`
- Payload: `{"access_token": "...", "app_id": "...", "app_secret": "..."}`

**Rate Limits:**
- 250 API calls per hour per user token
- System configured at 4 req/min
- Long-lived tokens expire after 60 days; auto-refreshed at 55 days

**Important Notes:**
- Engagement metrics (views, likes, replies, reposts, quotes) are only returned for the authenticated token owner's own posts. For other users, these fields are absent.
- The Threads API does not support global keyword search. Collection requires known account identifiers.
- The MEDIUM tier (Meta Content Library) is stubbed but not yet implemented.

---

## 4. Medium Tier Arenas

### 4.1 Google Search / Google Autocomplete

These two arenas share credentials. Google Search has no FREE tier; Google Autocomplete has a FREE tier using an undocumented endpoint (no credentials needed for that).

#### MEDIUM Tier: Serper.dev

| Field | Details |
|-------|---------|
| **Credentials needed** | Serper.dev API key |
| **Signup URL** | https://serper.dev |
| **Tier(s)** | MEDIUM (for both Google Search and Google Autocomplete) |
| **Pricing** | Pay-as-you-go starting at $50 for 50,000 queries ($1.00/1K); rates as low as $0.30/1K at higher volumes. Credits last 6 months. No monthly subscription. |
| **Rate limits** | Up to 300 queries/second; system configured at 100 req/min |

**Steps:**
1. Go to https://serper.dev.
2. Click **"Get API Key"** or **"Sign Up"**.
3. Create an account with your email.
4. After signing in, your API key is displayed on the dashboard.
5. Copy the API key.
6. Purchase credits as needed (minimum $50 for 50K queries).

**Environment Variables:**
```
SERPER_API_KEY=your_serper_api_key
```

**Credential Pool (Admin UI):**
- Platform: `serper`
- Tier: `medium`
- Payload: `{"api_key": "..."}`

#### PREMIUM Tier: SerpAPI

| Field | Details |
|-------|---------|
| **Credentials needed** | SerpAPI API key |
| **Signup URL** | https://serpapi.com |
| **Tier(s)** | PREMIUM (for both Google Search and Google Autocomplete) |
| **Pricing** | Plans from $50/month (5,000 searches) to $2,500/month. Enterprise at $3,750/month with 100,000 complimentary searches. Unused searches do not roll over. |
| **Rate limits** | System configured at 200 req/min |

**Steps:**
1. Go to https://serpapi.com.
2. Click **"Register"** or **"Start free trial"**.
3. Create an account with your email.
4. After signing in, navigate to your dashboard.
5. Your API key is displayed on the dashboard page.
6. Copy the API key.
7. Select a subscription plan (starting at $50/month for 5,000 searches).

**Environment Variables:**
```
SERPAPI_API_KEY=your_serpapi_api_key
```

**Credential Pool (Admin UI):**
- Platform: `serpapi`
- Tier: `premium`
- Payload: `{"api_key": "..."}`

**Google Autocomplete FREE tier (no credentials):**
The Google Autocomplete arena also supports a FREE tier using the undocumented endpoint `https://suggestqueries.google.com/complete/search`. No credentials are needed, but this endpoint has unreliable rate limits and no SLA. Use only for low-volume exploratory work.

---

### 4.2 Event Registry (NewsAPI.ai)

| Field | Details |
|-------|---------|
| **Credentials needed** | NewsAPI.ai API key |
| **Signup URL** | https://newsapi.ai (also accessible via https://eventregistry.org) |
| **Tier(s)** | MEDIUM, PREMIUM |
| **Pricing** | Free registration with 2,000 tokens (no credit card needed). MEDIUM (Starter): ~$90/month for 5,000 tokens. PREMIUM (Business): ~$490/month for 50,000 tokens. Extra tokens: $0.015 each. |
| **Rate limits** | ~10 req/sec empirically; system configured at 5 req/sec (300 req/min) |

**What This Arena Collects:** News articles from worldwide sources, filtered for Danish content using ISO 639-3 code `"dan"` and Denmark's Wikipedia concept URI as `sourceLocationUri`.

**Steps:**
1. Go to https://newsapi.ai.
2. Click **"Register"** or **"Sign Up for Free"**.
3. Create an account with your email (no credit card required for the free tier).
4. After signing in, navigate to your account dashboard.
5. Your API key is displayed on the dashboard.
6. Copy the API key.
7. You start with 2,000 free tokens. To upgrade:
   - Go to https://newsapi.ai/plans.
   - Select a plan (Starter at ~$90/month or Business at ~$490/month).
   - Payment via credit card or PayPal. Invoice billing available for organizations.

**Environment Variables:**
```
EVENT_REGISTRY_API_KEY=your_api_key
```

**Credential Pool (Admin UI):**
- Platform: `event_registry`
- Tier: `medium` or `premium`
- Payload: `{"api_key": "..."}`

**Token Budget Model:**
- 1 token per `getArticles` request (returns up to 100 articles per page)
- Historical searches cost more tokens (e.g., 2017 data costs 5 tokens per request)
- System monitors token budget and logs WARNING at 20% remaining, CRITICAL at 5%

**Rate Limits:**
- ~10 req/sec empirically allowed
- System configured at 5 req/sec to manage token burn rate
- Token budget is the primary operational constraint, not request rate

---

### 4.3 X/Twitter (via TwitterAPI.io)

#### MEDIUM Tier: TwitterAPI.io

| Field | Details |
|-------|---------|
| **Credentials needed** | TwitterAPI.io API key |
| **Signup URL** | https://twitterapi.io |
| **Tier(s)** | MEDIUM |
| **Pricing** | Pay-as-you-go at $0.15 per 1,000 tweets. No monthly subscription. |
| **Rate limits** | Over 1,000 requests/second (platform capacity); system configured at 60 req/min (1 req/sec) |

**Steps:**
1. Go to https://twitterapi.io.
2. Click **"Get Started"** or **"Sign Up"**.
3. Create an account with your email.
4. After signing in, navigate to your API dashboard.
5. Copy your API key.
6. Add credits to your account (pay-as-you-go billing).

**Credential Pool (Admin UI):**
- Platform: `twitterapiio`
- Tier: `medium`
- Payload: `{"api_key": "..."}`

#### PREMIUM Tier: Official X API v2

| Field | Details |
|-------|---------|
| **Credentials needed** | X API v2 Bearer token (Pro tier or higher) |
| **Signup URL** | https://developer.x.com |
| **Tier(s)** | PREMIUM |
| **Pricing** | X API Pro tier: $5,000/month for full-archive search. Basic tier: $100/month (recent search only, 7 days). |
| **Special requirements** | Developer account approval; Pro tier subscription |
| **Rate limits** | Full-archive search: 300 req / 15 min; system configured at 15 req/min |

**Steps:**
1. Go to https://developer.x.com and sign in with your X account.
2. Apply for a Developer Account if you do not have one.
3. Create a Project and an App within the Project.
4. Navigate to your App's "Keys and tokens" section.
5. Generate a Bearer Token.
6. Subscribe to the Pro tier ($5,000/month) for full-archive search access.

**Environment Variables (legacy, commented out in `.env.example`):**
```
X_BEARER_TOKEN=your_bearer_token
X_API_KEY=your_api_key
X_API_SECRET=your_api_secret
```

**Credential Pool (Admin UI):**
- Platform: `x_twitter`
- Tier: `premium`
- Payload: `{"bearer_token": "...", "api_key": "...", "api_secret": "..."}`

**Important Notes:**
- The MEDIUM tier (TwitterAPI.io) is strongly recommended over the official API due to cost: $0.15/1K tweets vs. $5,000/month.
- Danish content is filtered using the `lang:da` search operator.
- TwitterAPI.io accesses only publicly available content.

---

### 4.4 AI Chat Search (via OpenRouter)

| Field | Details |
|-------|---------|
| **Credentials needed** | OpenRouter API key |
| **Signup URL** | https://openrouter.ai |
| **Tier(s)** | MEDIUM, PREMIUM |
| **Pricing** | Pay-per-use. Perplexity Sonar (MEDIUM): ~$1/1M input tokens + $1/1M output tokens. Sonar Pro (PREMIUM): ~$3/1M input + $15/1M output. Query expansion uses `google/gemma-3-27b-it:free` (zero cost). Estimated monthly: $5-15 (MEDIUM), $15-45 (PREMIUM). |
| **Rate limits** | System configured at 50 req/min (MEDIUM), 100 req/min (PREMIUM) |

**What This Arena Collects:** AI-synthesized search results with citations. Uses query expansion to generate realistic Danish phrasings, then sends them to Perplexity Sonar models for web search with citation extraction.

**Steps:**
1. Go to https://openrouter.ai.
2. Click **"Sign Up"** or **"Get Started"**.
3. Create an account (email or social login).
4. After signing in, navigate to **"Keys"** in your account settings (https://openrouter.ai/keys).
5. Click **"Create Key"**.
6. Give the key a name (e.g., `IssueObservatory`) and click **"Create"**.
7. Copy the API key (format: `sk-or-v1-...`). It is shown only once.
8. Add credits to your account. Unused credits remain in your account indefinitely (no expiration).

**Credential Pool (Admin UI):**
- Platform: `openrouter`
- Tier: `medium` (a single key covers both MEDIUM and PREMIUM tiers)
- Payload: `{"api_key": "sk-or-v1-..."}`

**Rate Limits:**
- OpenRouter itself has generous rate limits
- Free model (`google/gemma-3-27b-it:free`): ~20 req/min
- System configured at 50 req/min (MEDIUM) and 100 req/min (PREMIUM)
- Each Perplexity Sonar call performs a live web search (3-15 seconds latency)

---

## 5. Premium Tier Arenas

### 5.1 Facebook (via Bright Data / MCL)

#### MEDIUM Tier: Bright Data

| Field | Details |
|-------|---------|
| **Credentials needed** | Bright Data API token |
| **Signup URL** | https://brightdata.com |
| **Tier(s)** | MEDIUM |
| **Pricing** | ~$2.50 per 1,000 records ($250 per 100K records) |
| **Rate limits** | 2 API trigger calls per second (courtesy throttle); async delivery with polling |

**What This Arena Collects:** Public Facebook posts matching search criteria, delivered via Bright Data's Datasets v3 API. Operates asynchronously: a collection request triggers a dataset job, which is polled until delivery (up to 20 minutes).

**Steps:**
1. Go to https://brightdata.com.
2. Click **"Start Free Trial"** or **"Sign Up"**.
3. Create an account with your business email.
4. After signing in, navigate to the Dashboard.
5. Go to **"Datasets"** or **"Web Scraper API"** section.
6. Find the **"Facebook"** dataset (dataset ID: `gd_l95fol7l1ru6rlo116`).
7. Generate an API token:
   - Navigate to your account settings or API section.
   - Create a new API token.
   - Copy the token.
8. Add funds to your account (minimum varies; pricing is per-record).

**Credential Pool (Admin UI):**
- Platform: `brightdata_facebook`
- Tier: `medium`
- Payload: `{"api_token": "...", "zone": "facebook_zone"}`

#### PREMIUM Tier: Meta Content Library (MCL)

| Field | Details |
|-------|---------|
| **Credentials needed** | MCL access token + Meta App credentials |
| **Signup URL** | https://transparency.meta.com/researchtools/meta-content-library/ |
| **Tier(s)** | PREMIUM (not yet implemented in the Issue Observatory) |
| **Pricing** | Free via Meta Secure Research Environment. Via SOMAR Virtual Data Enclave: $371/month per research team + $1,000 one-time project-start fee (starting January 2026). |
| **Special requirements** | Must be affiliated with an academic institution or non-profit research organization; application reviewed by CASD |

**Steps:**
1. Go to https://transparency.meta.com/researchtools/meta-content-library/.
2. Click **"Apply for Access"**.
3. Ensure you meet eligibility requirements:
   - Affiliation with an academic institution or non-profit research organization
   - Research must serve a scientific or public interest purpose
4. Submit your application through Meta Research Tools Manager (desktop/laptop only).
5. The application is reviewed by CASD (Secure Data Access Center).
6. If approved, choose your computing platform:
   - **Meta Secure Research Environment** (free computation)
   - **SOMAR Virtual Data Enclave** ($371/month + $1,000 setup)
7. Receive your access credentials.

**Credential Pool (Admin UI):**
- Platform: `meta_content_library`
- Tier: `premium`
- Payload: `{"access_token": "...", "app_id": "...", "app_secret": "..."}`

**WARNING:** MCL access is not yet approved for this project. Both PREMIUM methods currently raise `NotImplementedError` in the codebase.

---

### 5.2 Instagram (via Bright Data)

#### MEDIUM Tier: Bright Data

| Field | Details |
|-------|---------|
| **Credentials needed** | Bright Data API token |
| **Signup URL** | https://brightdata.com |
| **Tier(s)** | MEDIUM |
| **Pricing** | ~$1.50 per 1,000 records |
| **Rate limits** | 2 API trigger calls per second (courtesy throttle); async delivery with polling |

**What This Arena Collects:** Public Instagram posts (including Reels) matching search criteria via Bright Data's Datasets v3 API. Instagram has no native language filter; Danish content is identified by targeting known Danish accounts, searching Danish hashtags, and client-side language detection.

**Steps:**
1. Follow the same Bright Data signup process described in section 5.1 (Facebook).
2. After signing in, find the **"Instagram"** dataset (dataset ID: `gd_lyclm20il4r5helnj`).
3. Use the same API token created for Facebook (or create a separate one).

**Credential Pool (Admin UI):**
- Platform: `brightdata_instagram`
- Tier: `medium`
- Payload: `{"api_token": "...", "zone": "instagram_zone"}`

#### PREMIUM Tier: Meta Content Library (MCL)

Same as Facebook PREMIUM tier -- see section 5.1. MCL access covers Facebook, Instagram, and Threads once approved.

---

### 5.3 Majestic

| Field | Details |
|-------|---------|
| **Credentials needed** | Majestic API key |
| **Signup URL** | https://majestic.com/plans-pricing |
| **Tier(s)** | PREMIUM only |
| **Pricing** | API plan: $399.99/month ($333.33/month if billed annually). Includes 100 million analysis units/month. |
| **Special requirements** | API plan subscription required (Pro or API tier) |
| **Rate limits** | ~1 request/second recommended; system configured at 60 req/min |

**What This Arena Collects:** Backlink intelligence (Trust Flow, Citation Flow, backlink counts, referring domains) for web domains and URLs. This arena is reactive: collection is triggered by domain URLs discovered from other arenas, not by periodic keyword searches.

**Steps:**
1. Go to https://majestic.com/plans-pricing.
2. Select the **"API"** plan ($399.99/month) or the **"Pro"** plan ($99.99/month, which also includes API access).
3. Create an account with your email.
4. Complete payment (credit card, debit card, or PayPal; invoice billing available for annual Pro and API subscriptions).
5. After signing in, navigate to **"Account" > "API"** (https://majestic.com/account/api).
6. Generate or find your API key.
7. Copy the API key.

**Credential Pool (Admin UI):**
- Platform: `majestic`
- Tier: `premium`
- Payload: `{"api_key": "..."}`

**Rate Limits:**
- Majestic recommends ~1 request/second for batch analysis
- System configured at 60 req/min with 30-second timeout per slot
- 100 million analysis units per month on the API plan

**Analysis Unit Costs:**

| API Command | Unit Cost |
|-------------|-----------|
| `GetIndexItemInfo` | ~1 unit per item |
| `GetBackLinkData` | ~1 unit per row returned |
| `GetRefDomains` | ~1 unit per domain returned |
| `GetNewLostBackLinks` | ~1 unit per row returned |

The system maps 1 credit = 1,000 analysis units.

---

## 6. Deferred Arenas

These arenas are deferred but documented for future implementation.

### 6.1 Twitch

| Field | Details |
|-------|---------|
| **Credentials needed** | Twitch application client ID + client secret |
| **Signup URL** | https://dev.twitch.tv/console/apps |
| **Tier(s)** | FREE (deferred) |
| **Pricing** | Free |
| **Status** | Deferred stub -- channel discovery only, no historical chat collection |
| **Rate limits** | 800 points/minute per app access token; most endpoints cost 1 point |

**Steps:**
1. Go to https://dev.twitch.tv and log in with your Twitch account (create one at https://twitch.tv if needed).
2. Navigate to **Console > Applications** (https://dev.twitch.tv/console/apps).
3. Click **"Register Your Application"**.
4. Fill in the form:
   - **Name:** `IssueObservatory`
   - **OAuth Redirect URLs:** `http://localhost:8000/callback`
   - **Category:** `Analytics Tool` or `Other`
5. Click **"Create"**.
6. Click **"Manage"** on the newly created application.
7. Note down the **Client ID**.
8. Click **"New Secret"** to generate a Client Secret. Copy it immediately.

**Environment Variables (commented out in `.env.example`):**
```
TWITCH_CLIENT_ID=your_client_id
TWITCH_CLIENT_SECRET=your_client_secret
```

**Credential Pool (Admin UI):**
- Platform: `twitch`
- Tier: `free`
- Payload: `{"client_id": "...", "client_secret": "..."}`

**Important Notes:**
- No historical chat endpoint exists on Twitch. Only channel metadata can be collected in batch mode.
- Real-time chat requires an EventSub WebSocket connection (not yet implemented).
- The Twitch Helix API uses Client Credentials flow for server-to-server auth.

---

### 6.2 VKontakte

| Field | Details |
|-------|---------|
| **Credentials needed** | VK standalone application access token + app ID |
| **Signup URL** | https://vk.com/dev |
| **Tier(s)** | FREE (deferred, pending legal review) |
| **Pricing** | Free |
| **Status** | Deferred pending university legal review |
| **Rate limits** | 3 requests/second per access token |

**LEGAL WARNING:** Do NOT activate or enable VKontakte collection without completing a university legal review covering:
- EU sanctions implications (VK Company / former Mail.ru Group)
- Cross-border data transfer under GDPR (no Russia adequacy decision)
- Russian Federal Law No. 152-FZ on Personal Data
- API geo-restriction verification from Danish deployment location
- University DPO sign-off and DPIA documentation

**Steps (for future reference only):**
1. Go to https://vk.com/dev.
2. Log in with a VK account.
3. Click **"Create app"** (or navigate to "My Apps").
4. Fill in the form:
   - **Title:** `IssueObservatory`
   - **Platform:** `Standalone`
5. Create the app and note the **App ID**.
6. Set OAuth permission scopes: `wall`, `groups`, `offline`.
7. Generate a user access token via the OAuth flow:
   ```
   https://oauth.vk.com/authorize
     ?client_id={APP_ID}
     &scope=wall,groups,offline
     &redirect_uri=https://oauth.vk.com/blank.html
     &display=page
     &response_type=token
   ```
8. Copy the `access_token` from the redirect URL.

**Environment Variables (commented out in `.env.example`):**
```
VK_ACCESS_TOKEN=your_access_token
```

**Credential Pool (Admin UI):**
- Platform: `vkontakte`
- Tier: `free`
- Payload: `{"access_token": "...", "app_id": "..."}`

---

## 7. Credential Pool System

The Issue Observatory uses a database-backed credential pool with Fernet encryption for secure storage and Redis for runtime state management.

### Architecture Overview

```
PostgreSQL (api_credentials table)        Redis (runtime state)
+----------------------------------+      +-----------------------------------+
| id | platform | tier | payload   |      | credential:lease:{id}:{task_id}   |
|    |          |      | (Fernet-  |      | credential:quota:{id}:daily       |
|    |          |      |  encrypted)|     | credential:quota:{id}:monthly     |
|    |          |      |           |      | credential:cooldown:{id}          |
+----------------------------------+      +-----------------------------------+
```

### How It Works

1. **Storage:** Credentials are stored in the `api_credentials` PostgreSQL table. The `payload` column contains a Fernet-encrypted JSON blob with the actual API keys/tokens.

2. **Encryption:** All payloads are encrypted using the `CREDENTIAL_ENCRYPTION_KEY` Fernet key from the environment. Decryption happens in-process at runtime.

3. **Acquisition:** When an arena collector needs a credential, it calls `CredentialPool.acquire(platform=..., tier=...)`. The pool:
   - Queries the database for active credentials matching the platform and tier
   - Skips credentials that are leased, on cooldown, or quota-exhausted
   - Returns the first available credential (decrypted)

4. **Leasing:** Acquired credentials are marked with a Redis lease key (`credential:lease:{id}:{task_id}`) with a 3600-second TTL. This prevents the same credential from being used by multiple concurrent tasks.

5. **Quota Tracking:** Daily and monthly quotas are tracked in Redis with appropriate TTLs (until midnight UTC for daily, until month-end for monthly).

6. **Cooldown and Circuit Breaker:** After 5 consecutive errors, a credential is placed on a 1-hour cooldown. An admin must reset the `error_count` column in the database to re-enable it.

7. **Release:** When a task finishes, it calls `CredentialPool.release(credential_id=..., task_id=...)` to clear the Redis lease.

### Environment Variable Fallback

When no database credential is found, the pool falls back to environment variable discovery using the pattern:
```
{PLATFORM}_{TIER}_API_KEY
{PLATFORM}_{TIER}_API_KEY_2
{PLATFORM}_{TIER}_API_KEY_3
...
```

For example:
- `SERPER_MEDIUM_API_KEY` for Serper.dev at MEDIUM tier
- `YOUTUBE_FREE_API_KEY` for YouTube at FREE tier

This fallback ensures development and testing work without database setup.

---

## 8. Adding Credentials via Admin UI vs. Environment Variables

### Method 1: Admin UI (Recommended for Production)

1. Log in to the Issue Observatory as an admin.
2. Navigate to **Admin > Credentials** (typically at `/admin/credentials`).
3. Click **"Add Credential"**.
4. Fill in the form:
   - **Platform:** Select the platform name (e.g., `serper`, `reddit`, `youtube`)
   - **Tier:** Select the tier (e.g., `free`, `medium`, `premium`)
   - **Credential Payload:** Enter the JSON payload specific to the platform (see individual arena sections above for the exact format)
   - **Label:** (Optional) A human-readable label (e.g., "GCP Project 1 - YouTube")
   - **Daily Quota:** (Optional) Maximum daily uses
   - **Monthly Quota:** (Optional) Maximum monthly uses
5. Click **"Save"**. The payload is automatically Fernet-encrypted before storage.

**Advantages of Admin UI:**
- Supports multiple credentials per platform (credential rotation)
- Quota tracking and circuit breaker protection
- Lease tracking prevents concurrent use conflicts
- Encrypted at rest in the database
- Can be updated without restarting the application

### Method 2: Environment Variables (Development / Simple Setups)

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Fill in the relevant variables for each arena (see the per-arena sections above).
3. Restart the application to pick up changes.

**Advantages of Environment Variables:**
- Simple setup for development
- No database dependency for credential storage
- Familiar to developers

**Limitations:**
- Only one credential per platform/tier
- No quota tracking or circuit breaker
- Requires application restart to update
- Credentials stored in plaintext in the `.env` file

---

## 9. Environment Variable Reference

This is the complete list of arena-related environment variables from `.env.example`:

### Core Security (Required)

| Variable | Arena | Purpose |
|----------|-------|---------|
| `SECRET_KEY` | Core | Application session signing |
| `CREDENTIAL_ENCRYPTION_KEY` | Core | Fernet key for credential encryption |
| `PSEUDONYMIZATION_SALT` | Core | GDPR pseudonymization salt |

### Database and Infrastructure (Required)

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `postgresql+asyncpg://observatory:observatory@localhost:5432/issue_observatory` | PostgreSQL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/2` | Celery results |

### Google Search / Autocomplete

| Variable | Tier | Purpose |
|----------|------|---------|
| `SERPER_API_KEY` | MEDIUM | Serper.dev API key |
| `SERPAPI_API_KEY` | PREMIUM | SerpAPI API key |
| `GOOGLE_CUSTOM_SEARCH_API_KEY` | (Legacy) | Google Custom Search API key |
| `GOOGLE_CUSTOM_SEARCH_CX` | (Legacy) | Custom Search Engine ID |

### Social Media

| Variable | Arena | Tier |
|----------|-------|------|
| `BLUESKY_HANDLE` | Bluesky | FREE |
| `BLUESKY_APP_PASSWORD` | Bluesky | FREE |
| `REDDIT_CLIENT_ID` | Reddit | FREE |
| `REDDIT_CLIENT_SECRET` | Reddit | FREE |
| `REDDIT_USER_AGENT` | Reddit | FREE |
| `TIKTOK_CLIENT_KEY` | TikTok | FREE |
| `TIKTOK_CLIENT_SECRET` | TikTok | FREE |
| `TELEGRAM_API_ID` | Telegram | FREE |
| `TELEGRAM_API_HASH` | Telegram | FREE |
| `TELEGRAM_PHONE` | Telegram | FREE |
| `YOUTUBE_API_KEY` | YouTube | FREE |
| `DISCORD_BOT_TOKEN` | Discord | FREE |

### News APIs

| Variable | Arena | Tier |
|----------|-------|------|
| `EVENT_REGISTRY_API_KEY` | Event Registry | MEDIUM/PREMIUM |
| `GDELT_DOC_API_URL` | GDELT | FREE (optional override) |

### X/Twitter (Commented Out)

| Variable | Arena | Tier |
|----------|-------|------|
| `X_BEARER_TOKEN` | X/Twitter | PREMIUM |
| `X_API_KEY` | X/Twitter | PREMIUM |
| `X_API_SECRET` | X/Twitter | PREMIUM |

### Wikipedia (Commented Out, Optional)

| Variable | Arena | Tier |
|----------|-------|------|
| `WIKIPEDIA_USER_AGENT` | Wikipedia | FREE |

### Deferred Arenas (Commented Out)

| Variable | Arena | Tier |
|----------|-------|------|
| `TWITCH_CLIENT_ID` | Twitch | FREE |
| `TWITCH_CLIENT_SECRET` | Twitch | FREE |
| `VK_ACCESS_TOKEN` | VKontakte | FREE |

---

## 10. Redis Configuration for Credential Leasing

The credential pool uses Redis for real-time state management. The following Redis key patterns are used:

### Key Patterns

| Pattern | TTL | Purpose |
|---------|-----|---------|
| `credential:lease:{credential_id}:{task_id}` | 3,600s (1 hour) | Active credential lease. Prevents concurrent use. |
| `credential:quota:{credential_id}:daily` | Until midnight UTC | Daily usage counter. Incremented on each use. |
| `credential:quota:{credential_id}:monthly` | Until month end | Monthly usage counter. Incremented on each use. |
| `credential:cooldown:{credential_id}` | Varies (max 3,600s) | Cooldown after errors. Exponential backoff. |

### Rate Limiter Keys

Each arena also uses Redis for rate limiting:

| Pattern | Purpose |
|---------|---------|
| `ratelimit:news_media:event_registry:{credential_id}` | Event Registry per-credential limit |
| `ratelimit:news_media:gdelt:shared` | GDELT shared limit |
| `ratelimit:web:common_crawl:shared` | Common Crawl shared limit |
| `ratelimit:web:wayback:shared` | Wayback Machine shared limit |
| `ratelimit:web:majestic:{credential_id}` | Majestic per-credential limit |
| `tiktok:token:{credential_id}` | TikTok cached OAuth token |

### Redis Database Allocation

The Issue Observatory uses three separate Redis databases to isolate concerns:

| Database | Variable | Purpose |
|----------|----------|---------|
| `/0` | `REDIS_URL` | Application cache, credential leasing, rate limiting |
| `/1` | `CELERY_BROKER_URL` | Celery task broker |
| `/2` | `CELERY_RESULT_BACKEND` | Celery task results |

### Circuit Breaker Configuration

| Parameter | Value |
|-----------|-------|
| Error threshold | 5 consecutive errors |
| Maximum cooldown | 3,600 seconds (1 hour) |
| Lease TTL | 3,600 seconds (1 hour) |

To reset a circuit-broken credential:
1. Fix the underlying issue (expired token, billing, etc.)
2. In the Admin UI, navigate to the credential
3. Reset the `error_count` to 0
4. The Redis cooldown key will expire on its own, or clear it manually

---

## 11. Quick-Start Checklist

Use this checklist to set up the Issue Observatory from scratch. Start with the essentials and add arenas as needed.

### Phase 1: Core Infrastructure (Required)

- [ ] Generate `SECRET_KEY`: `openssl rand -hex 32`
- [ ] Generate `CREDENTIAL_ENCRYPTION_KEY`: `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`
- [ ] Generate `PSEUDONYMIZATION_SALT`: `openssl rand -hex 32`
- [ ] Configure `DATABASE_URL` for PostgreSQL 16+
- [ ] Configure `REDIS_URL` for Redis 7+
- [ ] Set `FIRST_ADMIN_EMAIL` and `FIRST_ADMIN_PASSWORD`
- [ ] Run database migrations: `alembic upgrade head`
- [ ] Bootstrap admin user: `python scripts/bootstrap_admin.py`

### Phase 2: Free Arenas (No Cost)

- [ ] **RSS Feeds** -- No setup needed (works immediately)
- [ ] **GDELT** -- No setup needed
- [ ] **Via Ritzau** -- No setup needed
- [ ] **Common Crawl** -- No setup needed
- [ ] **Wayback Machine** -- No setup needed
- [ ] **Wikipedia** -- No setup needed (optional: set custom User-Agent)
- [ ] **URL Scraper** -- No setup needed (optional: install Playwright for MEDIUM tier)
- [ ] **Bluesky** -- No setup needed for unauthenticated access (optional: create app password)
- [ ] **Reddit** -- Create app at https://www.reddit.com/prefs/apps
- [ ] **YouTube** -- Create API key at https://console.cloud.google.com
- [ ] **Telegram** -- Register at https://my.telegram.org/apps + generate session string
- [ ] **TikTok** -- Apply at https://developers.tiktok.com/products/research-api/ (2-week approval)
- [ ] **Discord** -- Create bot at https://discord.com/developers/applications
- [ ] **Threads** -- Create Meta Developer App at https://developers.facebook.com
- [ ] **Gab** -- Create account and register app at https://gab.com/settings/applications

### Phase 3: Paid Arenas (Budget Required)

- [ ] **Google Search/Autocomplete (MEDIUM)** -- Sign up at https://serper.dev ($50 minimum)
- [ ] **Event Registry (MEDIUM)** -- Sign up at https://newsapi.ai (free 2K tokens, then ~$90/month)
- [ ] **X/Twitter (MEDIUM)** -- Sign up at https://twitterapi.io (pay-as-you-go, $0.15/1K tweets)
- [ ] **AI Chat Search** -- Sign up at https://openrouter.ai (pay-per-use, ~$5-15/month)
- [ ] **Google Search/Autocomplete (PREMIUM)** -- Sign up at https://serpapi.com (from $50/month)

### Phase 4: Premium Arenas (Significant Budget)

- [ ] **Facebook (MEDIUM)** -- Sign up at https://brightdata.com (~$2.50/1K records)
- [ ] **Instagram (MEDIUM)** -- Sign up at https://brightdata.com (~$1.50/1K records)
- [ ] **Majestic (PREMIUM)** -- Sign up at https://majestic.com ($399.99/month)
- [ ] **Facebook/Instagram (PREMIUM)** -- Apply for Meta Content Library access (free-$371/month)

### Phase 5: Deferred (Future)

- [ ] **Twitch** -- Register at https://dev.twitch.tv/console/apps (when chat collection is implemented)
- [ ] **VKontakte** -- Complete legal review before any setup (university DPO sign-off required)

---

## Cost Summary

| Arena | Tier | Monthly Cost Estimate | Notes |
|-------|------|-----------------------|-------|
| RSS Feeds, GDELT, Via Ritzau, Common Crawl, Wayback, Wikipedia, URL Scraper | FREE | $0 | No credentials needed |
| Bluesky | FREE | $0 | Optional credentials |
| Reddit | FREE | $0 | Free OAuth credentials |
| YouTube | FREE | $0 | Free API key (quota-limited) |
| Telegram | FREE | $0 | Free with phone verification |
| TikTok | FREE | $0 | Free with academic approval |
| Discord | FREE | $0 | Free bot token |
| Threads | FREE | $0 | Free with Meta Developer App |
| Gab | FREE | $0 | Free (Pro may be required) |
| Google Search (MEDIUM) | MEDIUM | $15-50 | Serper.dev, pay-as-you-go |
| Event Registry (MEDIUM) | MEDIUM | ~$90 | NewsAPI.ai Starter |
| X/Twitter (MEDIUM) | MEDIUM | $15-75 | TwitterAPI.io, pay-as-you-go |
| AI Chat Search (MEDIUM) | MEDIUM | $5-15 | OpenRouter, pay-per-use |
| Facebook (MEDIUM) | MEDIUM | $25-250 | Bright Data, per-record |
| Instagram (MEDIUM) | MEDIUM | $15-150 | Bright Data, per-record |
| Google Search (PREMIUM) | PREMIUM | $50-250 | SerpAPI subscription |
| Event Registry (PREMIUM) | PREMIUM | ~$490 | NewsAPI.ai Business |
| X/Twitter (PREMIUM) | PREMIUM | $5,000 | Official X API Pro |
| Majestic (PREMIUM) | PREMIUM | ~$400 | API plan |
| Meta Content Library | PREMIUM | $0-371 | Pending approval |

**Minimum viable research setup (free arenas only):** $0/month
**Recommended research setup (free + MEDIUM tier):** ~$125-230/month
**Full MEDIUM tier coverage:** ~$165-630/month
**Full PREMIUM tier coverage:** ~$6,300+/month

---

*This guide reflects API access procedures, pricing, and URLs as of February 2026. Platform terms, pricing, and signup processes may change. Always verify current information at the official platform documentation.*
