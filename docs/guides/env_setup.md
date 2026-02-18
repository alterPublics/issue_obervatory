# Environment Setup Guide

**Created:** 2026-02-16
**Last updated:** 2026-02-17

This guide walks you through setting up the `.env` file for The Issue Observatory from scratch. It covers every setting, explains what each one does, and provides the exact commands to generate secrets.

---

## Table of Contents

1. [Before You Start](#before-you-start)
2. [Part 1: Required Settings (the application will not start without these)](#part-1-required-settings)
3. [Part 2: Infrastructure Credentials](#part-2-infrastructure-credentials)
4. [Part 3: Security Keys](#part-3-security-keys)
5. [Part 4: Email / SMTP (optional)](#part-4-email--smtp)
6. [Part 5: Application Behaviour and Defaults](#part-5-application-behaviour-and-defaults)
7. [Part 6: Arena Credentials](#part-6-arena-credentials)
8. [Part 7: Complete .env Template](#part-7-complete-env-template)
9. [Part 8: Verification](#part-8-verification)

---

## Before You Start

1. The `.env` file must be placed in the project root directory (the same directory as `docker-compose.yml`).
2. Never commit `.env` to version control. It is already listed in `.gitignore`.
3. All settings are read by `src/issue_observatory/config/settings.py` using Pydantic Settings v2. Variable names are case-insensitive, but this guide uses UPPER_CASE by convention.
4. Settings with a default value shown below can be omitted from `.env` if the default is acceptable.
5. Arena-specific API credentials are NOT stored in `.env`. They are entered through the admin UI or bootstrap script and stored encrypted in the database. This guide covers the system-level settings only; see Part 6 for an explanation of how arena credentials work.

---

## Part 1: Required Settings

These four settings have no defaults. The application will fail to start if any of them is missing.

### DATABASE_URL

The PostgreSQL connection string. Must use the `asyncpg` driver.

```
DATABASE_URL=postgresql+asyncpg://observatory:your_db_password@localhost:5432/issue_observatory
```

If you are using Docker Compose with the bundled PostgreSQL service, use:

```
DATABASE_URL=postgresql+asyncpg://observatory:your_db_password@db:5432/issue_observatory
```

Replace `your_db_password` with a strong password. The hostname `db` refers to the PostgreSQL container defined in `docker-compose.yml`.

### SECRET_KEY

A random hex string used to sign JWT authentication tokens. Generate it with:

```bash
openssl rand -hex 32
```

This produces a 64-character hex string. Paste it as:

```
SECRET_KEY=a3f1c2e9d4b8... (your 64-character hex string)
```

If you lose or change this key, all active user sessions are invalidated. Users will need to log in again. This is inconvenient but not catastrophic.

### CREDENTIAL_ENCRYPTION_KEY

A Fernet symmetric encryption key used to encrypt all API credentials stored in the database. Generate it with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

This produces a 44-character base64-encoded string. Paste it as:

```
CREDENTIAL_ENCRYPTION_KEY=h3ZpQ8k2... (your 44-character base64 string)
```

**This is the single most critical secret in the system.** If you lose this key, every stored API credential becomes permanently unrecoverable. You would need to re-enter all arena API keys manually. Back up this key securely and separately from the database backup. See `docs/operations/secrets_management.md` for backup procedures.

### PSEUDONYMIZATION_SALT

A project-specific random string used as a salt when hashing author identifiers. The system computes `SHA-256(platform + user_id + salt)` to create pseudonymized author IDs. Generate it with:

```bash
openssl rand -hex 16
```

Paste it as:

```
PSEUDONYMIZATION_SALT=7f2a9c1e... (your random hex string)
```

**This value must remain stable for the entire lifetime of your research project.** If you change it, the same author will produce a different pseudonymized ID, breaking longitudinal analysis. Choose it once and never change it.

---

## Part 2: Infrastructure Credentials

These settings configure connections to the services that The Issue Observatory depends on. All have sensible defaults for local development with Docker Compose.

### Redis

```
REDIS_URL=redis://localhost:6379/0
```

Default: `redis://localhost:6379/0`. Used for application caching and session state.

If using Docker Compose, change `localhost` to `redis` (the container hostname):

```
REDIS_URL=redis://redis:6379/0
```

### Celery (Task Queue)

```
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
```

Defaults: Redis databases 1 and 2 (isolated from the application Redis on database 0). If using Docker Compose, replace `localhost` with `redis`.

### MinIO (Object Storage)

```
MINIO_ENDPOINT=localhost:9000
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin
MINIO_BUCKET=issue-observatory
MINIO_SECURE=false
```

These are the defaults. For production:
- Change `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` to strong, unique values.
- Set `MINIO_SECURE=true` if MinIO is behind TLS.
- If using Docker Compose, replace `localhost` with `minio` (the container hostname).

MinIO stores archived media files (images, thumbnails, PDFs). If you are not archiving media, these defaults are fine for development.

---

## Part 3: Security Keys

Beyond the required `SECRET_KEY` and `CREDENTIAL_ENCRYPTION_KEY` covered in Part 1, these optional security settings control token lifetimes:

```
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=30
```

- `ACCESS_TOKEN_EXPIRE_MINUTES` (default: 30) -- How long a JWT access token remains valid. Lower values are more secure but require more frequent token refreshes.
- `REFRESH_TOKEN_EXPIRE_DAYS` (default: 30) -- How long a refresh token remains valid. After this period, the user must log in again with their password.

For most deployments, the defaults are appropriate. Reduce `ACCESS_TOKEN_EXPIRE_MINUTES` to 15 for higher-security environments.

---

## Part 4: Email / SMTP

Email is optional. When `SMTP_HOST` is not set (or set to empty), all email functionality is silently disabled. The system will still function; users simply will not receive email notifications (e.g., low-credit warnings, collection run completions).

To enable email:

```
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=your_smtp_username
SMTP_PASSWORD=your_smtp_password
SMTP_FROM_ADDRESS=noreply@your-domain.dk
SMTP_STARTTLS=true
SMTP_SSL=false
```

**Common configurations:**

For university SMTP (e.g., KU or AAU mail servers):
```
SMTP_HOST=smtp.ku.dk
SMTP_PORT=587
SMTP_USERNAME=abc123@ku.dk
SMTP_PASSWORD=your_university_password
SMTP_FROM_ADDRESS=abc123@ku.dk
SMTP_STARTTLS=true
SMTP_SSL=false
```

For Gmail (testing only):
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your.email@gmail.com
SMTP_PASSWORD=your_app_specific_password
SMTP_FROM_ADDRESS=your.email@gmail.com
SMTP_STARTTLS=true
SMTP_SSL=false
```

For local development without email (the default):
```
# Simply omit all SMTP_ variables, or set:
SMTP_HOST=
```

Additional email-related setting:

```
LOW_CREDIT_WARNING_THRESHOLD=100
```

Default: 100. When a user's credit balance drops below this number after a collection run, a warning email is sent (if SMTP is configured).

---

## Part 5: Application Behaviour and Defaults

These settings control general application behavior. All have defaults.

### General

```
APP_NAME=The Issue Observatory
DEBUG=false
LOG_LEVEL=INFO
DEFAULT_TIER=free
METRICS_ENABLED=true
```

- `APP_NAME` -- Shown in the web UI header and OpenAPI documentation.
- `DEBUG` -- Enables verbose error responses and FastAPI debug mode. Set to `true` only during development. **Never enable in production** as it exposes internal error details.
- `LOG_LEVEL` -- One of: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Use `DEBUG` during development for maximum verbosity.
- `DEFAULT_TIER` -- The default collection tier applied when a collection run or query design does not specify one. Usually `free`.
- `METRICS_ENABLED` -- Exposes a Prometheus-compatible metrics endpoint at `GET /metrics`. Set to `false` to disable.

### Danish Locale Defaults

```
DEFAULT_LANGUAGE=da
DEFAULT_LOCALE_COUNTRY=dk
```

These are the defaults and should not be changed for Danish public discourse research. They set the system-wide default language filter to Danish (`da`, ISO 639-1) and the default country to Denmark (`dk`, ISO 3166-1 alpha-2).

### GDPR / Data Retention

```
DATA_RETENTION_DAYS=730
```

Default: 730 (2 years). Collected records older than this are automatically marked for deletion by the retention enforcement job. This aligns with the purpose-limitation principle under GDPR Article 5(1)(e) and Databeskyttelsesloven section 10 requirements for university research.

Adjust this value if your Data Protection Impact Assessment (DPIA) specifies a different retention period.

### CORS

```
ALLOWED_ORIGINS=["http://localhost:8000"]
```

Default: only localhost. For production, add your domain:

```
ALLOWED_ORIGINS=["https://observatory.your-university.dk", "http://localhost:8000"]
```

### Admin Bootstrap

```
FIRST_ADMIN_EMAIL=
FIRST_ADMIN_PASSWORD=
```

These are used only during first-run initialization by the bootstrap script. If set, the system creates an admin account with these credentials on first startup. Leave empty to skip automatic admin creation and create the account manually later.

For first-time setup:
```
FIRST_ADMIN_EMAIL=researcher@ku.dk
FIRST_ADMIN_PASSWORD=a_strong_temporary_password
```

Change the admin password through the UI immediately after first login.

---

## Part 6: Arena Credentials

Arena API credentials (Serper.dev API keys, Reddit client secrets, TikTok client keys, etc.) are **not stored in the `.env` file**. They are managed through the application's credential system:

1. Credentials are entered via the **admin UI** (Admin > Credentials) or the **bootstrap script** (`scripts/bootstrap_admin.py`).
2. They are encrypted with the `CREDENTIAL_ENCRYPTION_KEY` and stored in the `api_credentials` database table.
3. The credential pool rotates keys automatically for arenas that support multiple keys.

This design means that API keys are encrypted at rest and never appear in plaintext in configuration files or environment variables.

### Which arenas need credentials

**No credentials needed (fully free and open):**
- RSS Feeds
- GDELT
- Via Ritzau
- Google Autocomplete (free tier)
- Bluesky
- Common Crawl
- Wayback Machine

**Credentials needed (free-tier arenas with authenticated APIs):**

| Arena | Platform key | Credential fields | How to obtain |
|-------|-------------|-------------------|---------------|
| Reddit | `reddit` | `client_id`, `client_secret`, `user_agent` | Create a "script" app at https://www.reddit.com/prefs/apps |
| YouTube | `youtube` | `api_key` | Enable YouTube Data API v3 in Google Cloud Console and create an API key |
| Telegram | `telegram` | `api_id`, `api_hash`, `session_string` | Register at https://my.telegram.org. Run `scripts/telegram_auth.py` for session string |
| TikTok | `tiktok` | `client_key`, `client_secret` | Apply for TikTok Research API access at https://developers.tiktok.com |
| Gab | `gab` | `access_token` | Generate via Gab developer settings |
| Threads | `threads` | `access_token` | Create a Meta app, request Threads API access, generate long-lived token |

**Credentials needed (paid-tier arenas):**

| Arena | Platform key | Tier | Credential fields | Approximate cost |
|-------|-------------|------|-------------------|-----------------|
| Google Search | `serper` | MEDIUM | `api_key` | ~$0.30 / 1K queries |
| Google Search | `serpapi` | PREMIUM | `api_key` | Higher (see SerpAPI pricing) |
| X/Twitter | `twitterapi_io` | MEDIUM | `api_key` | ~$0.15 / 1K tweets |
| X/Twitter | `x_twitter` | PREMIUM | `bearer_token` | X API Pro plan pricing |
| Facebook | `brightdata_facebook` | MEDIUM | `api_token`, `zone` | ~$2.50 / 1K records |
| Instagram | `brightdata_instagram` | MEDIUM | `api_token`, `zone` | ~$1.50 / 1K records |
| Event Registry | `event_registry` | MEDIUM | `api_key` | $90/month (5K tokens) |
| Event Registry | `event_registry` | PREMIUM | `api_key` | $490/month (50K tokens) |
| Majestic | `majestic` | PREMIUM | `api_key` | $399.99/month |

### Adding a credential through the admin UI

1. Log in as an admin user.
2. Navigate to **Admin > Credentials**.
3. Click **Add credential**.
4. Select the platform (e.g., "serper") and tier (e.g., "medium").
5. Enter the credential fields as JSON (e.g., `{"api_key": "your-key-here"}`).
6. Click Submit. The credential is encrypted and stored.

**Note:** The following platforms are not yet available in the admin UI credential dropdown and must be configured via the bootstrap script below: Gab (`gab`), Threads (`threads`), Facebook via Bright Data (`brightdata_facebook`), Instagram via Bright Data (`brightdata_instagram`), and Google Search premium via SerpAPI (`serpapi`).

### Adding a credential via the bootstrap script

```bash
docker compose exec app python scripts/bootstrap_admin.py
```

The script prompts interactively for credentials. Suitable for initial setup.

---

## Part 7: Complete .env Template

Copy the block below into a file named `.env` in the project root. Replace every placeholder marked with `<...>` with your actual values. Lines starting with `#` are comments.

```bash
# ==============================================================================
# THE ISSUE OBSERVATORY -- Environment Configuration
# ==============================================================================
# Copy this file to .env and fill in the required values.
# Never commit .env to version control.
# ==============================================================================

# ------------------------------------------------------------------------------
# REQUIRED -- the application will not start without these
# ------------------------------------------------------------------------------

# PostgreSQL connection string (asyncpg driver required)
# For Docker Compose: use "db" as hostname
# For local dev: use "localhost"
DATABASE_URL=postgresql+asyncpg://observatory:<db_password>@db:5432/issue_observatory

# JWT signing secret (generate: openssl rand -hex 32)
SECRET_KEY=<generate_with_openssl_rand_hex_32>

# Fernet key for encrypting stored API credentials
# Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# CRITICAL: back up this key securely. If lost, all stored credentials are unrecoverable.
CREDENTIAL_ENCRYPTION_KEY=<generate_with_fernet>

# Salt for pseudonymizing author identifiers (generate: openssl rand -hex 16)
# MUST remain stable for the project lifetime. Never change after data collection begins.
PSEUDONYMIZATION_SALT=<generate_with_openssl_rand_hex_16>

# ------------------------------------------------------------------------------
# INFRASTRUCTURE -- defaults work for Docker Compose local development
# ------------------------------------------------------------------------------

# Redis (application cache and sessions)
REDIS_URL=redis://redis:6379/0

# Celery task queue
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# MinIO object storage (media archival)
MINIO_ENDPOINT=minio:9000
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin
MINIO_BUCKET=issue-observatory
MINIO_SECURE=false

# ------------------------------------------------------------------------------
# SECURITY -- token lifetimes (defaults are fine for most deployments)
# ------------------------------------------------------------------------------

ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=30

# ------------------------------------------------------------------------------
# APPLICATION BEHAVIOUR
# ------------------------------------------------------------------------------

APP_NAME=The Issue Observatory
DEBUG=false
LOG_LEVEL=INFO
DEFAULT_TIER=free
METRICS_ENABLED=true

# Danish locale defaults (do not change for Danish discourse research)
DEFAULT_LANGUAGE=da
DEFAULT_LOCALE_COUNTRY=dk

# GDPR data retention (730 days = 2 years)
DATA_RETENTION_DAYS=730

# CORS allowed origins (add your production domain)
ALLOWED_ORIGINS=["http://localhost:8000"]

# ------------------------------------------------------------------------------
# ADMIN BOOTSTRAP (first-run only; leave empty to skip)
# ------------------------------------------------------------------------------

FIRST_ADMIN_EMAIL=
FIRST_ADMIN_PASSWORD=

# ------------------------------------------------------------------------------
# EMAIL / SMTP (optional; leave SMTP_HOST empty to disable all email)
# ------------------------------------------------------------------------------

# SMTP_HOST=smtp.example.com
# SMTP_PORT=587
# SMTP_USERNAME=
# SMTP_PASSWORD=
# SMTP_FROM_ADDRESS=noreply@observatory.local
# SMTP_STARTTLS=true
# SMTP_SSL=false

# Credit warning threshold (sends email when balance drops below this)
LOW_CREDIT_WARNING_THRESHOLD=100
```

---

## Part 8: Verification

After creating your `.env` file, verify that the configuration is valid.

### Step 1: Check that all required variables are set

Review your `.env` file and confirm that these four variables have non-empty values:
- `DATABASE_URL`
- `SECRET_KEY`
- `CREDENTIAL_ENCRYPTION_KEY`
- `PSEUDONYMIZATION_SALT`

### Step 2: Validate the settings module loads

**Prerequisite:** You must have Python 3.11+ installed and a virtual environment set up with the project's dependencies. If you have not done this, run the following from the project root:

```bash
python -m venv .venv && source .venv/bin/activate && pip install -e .
```

If `pip install -e .` fails, ensure you have the project's build dependencies (see `pyproject.toml`).

```bash
# From the project root, with your virtual environment activated:
python -c "
from issue_observatory.config.settings import get_settings
s = get_settings()
print('DATABASE_URL:', s.database_url[:30] + '...')
print('SECRET_KEY length:', len(s.secret_key))
print('CREDENTIAL_ENCRYPTION_KEY length:', len(s.credential_encryption_key))
print('PSEUDONYMIZATION_SALT length:', len(s.pseudonymization_salt))
print('Settings loaded successfully.')
"
```

If this prints the lengths without errors, your settings are syntactically valid.

### Step 3: Start the services

**Prerequisite:** Docker Desktop (or Docker Engine + Docker Compose plugin) must be installed. Verify with `docker --version`. If the command is not found, install Docker Desktop from https://www.docker.com/products/docker-desktop/ before continuing.

```bash
docker compose up -d
```

Check that all containers are running:

```bash
docker compose ps
```

You should see containers for: `app`, `db` (PostgreSQL), `redis`, `minio`, `worker` (Celery).

### Step 4: Verify the health endpoint

```bash
curl http://localhost:8000/api/health
```

A successful response looks like:

```json
{"status": "ok", "database": "ok", "redis": "ok"}
```

### Step 5: Log in to the admin UI

Open `http://localhost:8000` in your browser. If you set `FIRST_ADMIN_EMAIL` and `FIRST_ADMIN_PASSWORD`, log in with those credentials. Navigate to Admin > Credentials to begin adding arena API keys.

### Common Issues

**"Settings validation error: field required"** -- One of the four required settings is missing from `.env`. Check for typos in variable names.

**"Connection refused" on DATABASE_URL** -- The PostgreSQL container may not be ready yet. Wait a few seconds and try again, or check `docker compose logs db`.

**"InvalidToken" errors when using arena credentials** -- The `CREDENTIAL_ENCRYPTION_KEY` in your `.env` does not match the key that was used to encrypt the stored credentials. This happens if you regenerated the key without re-entering credentials. See `docs/operations/secrets_management.md` for recovery steps.

**Redis connection errors** -- Verify that `REDIS_URL`, `CELERY_BROKER_URL`, and `CELERY_RESULT_BACKEND` hostnames match your Docker Compose service names (usually `redis`).
