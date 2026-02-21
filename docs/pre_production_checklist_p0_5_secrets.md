# P0-5 Pre-Production Check: Secrets and Configuration Audit

**Audited by:** QA Guardian
**Date:** 2026-02-21
**Scope:** Full codebase scan of `/src/`, `/tests/`, `/scripts/`, `/docker-compose.yml`, `/Dockerfile`, `/alembic.ini`, `/.env.example`, `/.pre-commit-config.yaml`, `/.github/workflows/ci.yml`

---

## Executive Summary

The Issue Observatory codebase has a **solid security foundation** with centralized settings management (`config/settings.py`), Fernet encryption for credentials at rest, and proper `.gitignore` coverage for `.env` files. However, this audit identified **3 beta-blockers**, **5 high-severity** findings, and **7 medium-severity** issues that should be addressed before production deployment.

---

## 1. .env.example Completeness

### 1.1 Environment Variables Documented in .env.example

The file at `/.env.example` documents 35 variables across these categories:
- Database (1): `DATABASE_URL`
- Redis (1): `REDIS_URL`
- Celery (2): `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`
- Application (4): `SECRET_KEY`, `DEBUG`, `LOG_LEVEL`, `CORS_ORIGINS`
- Authentication (4): `FASTAPI_USERS_SECRET`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `FIRST_ADMIN_EMAIL`, `FIRST_ADMIN_PASSWORD`
- Security (2): `CREDENTIAL_ENCRYPTION_KEY`, `PSEUDONYMIZATION_SALT`
- MinIO (5): `MINIO_ENDPOINT`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, `MINIO_BUCKET`, `MINIO_SECURE`
- Default tier (1): `DEFAULT_COST_TIER`
- Arena API keys (12): Google, Bluesky, Reddit, TikTok, Telegram, YouTube, Event Registry, GDELT URL
- Commented-out future arenas (7): X/Twitter, Wikipedia, Discord, Twitch, VKontakte

### 1.2 Environment Variables Used in Code but NOT in .env.example

| Variable | Where Used | Severity | Notes |
|----------|-----------|----------|-------|
| `OPENROUTER_API_KEY` | `arenas/ai_chat_search/collector.py:469` | **HIGH** | AI Chat Search arena env-var fallback. Not documented. |
| `MAJESTIC_PREMIUM_API_KEY` | `arenas/majestic/collector.py:476` | **HIGH** | Majestic arena env-var fallback. Not documented. |
| `EVENT_REGISTRY_{TIER}_API_KEY` | `arenas/event_registry/collector.py:684-685` | **MEDIUM** | Dynamically constructed (e.g. `EVENT_REGISTRY_MEDIUM_API_KEY`). `.env.example` only has `EVENT_REGISTRY_API_KEY` (no tier prefix). |
| `POSTGRES_USER` | `docker-compose.yml:11`, `scripts/backup_postgres.sh` | MEDIUM | Docker/backup infrastructure only. Not needed in app `.env` but should be documented for Docker users. |
| `POSTGRES_PASSWORD` | `docker-compose.yml:12`, `scripts/backup_postgres.sh` | MEDIUM | Same as above. |
| `POSTGRES_DB` | `docker-compose.yml:13`, `scripts/backup_postgres.sh` | MEDIUM | Same as above. |
| `MINIO_ACCESS_KEY` | `docker-compose.yml:102`, `scripts/backup_postgres.py:297` | LOW | Alias for `MINIO_ROOT_USER`. Documented as fallback in script. |
| `MINIO_SECRET_KEY` | `docker-compose.yml:103`, `scripts/backup_postgres.py:301` | LOW | Alias for `MINIO_ROOT_PASSWORD`. Documented as fallback in script. |
| `BACKUP_RETENTION_DAYS` | `docker-compose.yml:106`, `scripts/backup_postgres.py:306` | LOW | Defaults to 30. Should be documented for ops. |
| `WIKIPEDIA_USER_AGENT` | `config/danish_defaults.py:287` (docstring reference) | LOW | Overrides the hardcoded default User-Agent. Already commented out in `.env.example`. |
| `SMTP_HOST`, `SMTP_PORT`, etc. | `config/settings.py:183-205` | MEDIUM | 6 SMTP-related settings exist in Settings class but are entirely absent from `.env.example`. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `config/settings.py:64` | LOW | Has default (30). Not in `.env.example`. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `config/settings.py:67` | LOW | Has default (30). Not in `.env.example`. |
| `DATA_RETENTION_DAYS` | `config/settings.py:164` | LOW | Has default (730). Not in `.env.example`. |
| `LOW_CREDIT_WARNING_THRESHOLD` | `config/settings.py:211` | LOW | Has default (100). Not in `.env.example`. |
| `METRICS_ENABLED` | `config/settings.py:219` | LOW | Has default (True). Not in `.env.example`. |
| `APP_NAME` | `config/settings.py:137` | LOW | Has default. Not in `.env.example`. |
| `DEFAULT_LANGUAGE` | `config/settings.py:154` | LOW | Has default ("da"). Not in `.env.example`. |
| `DEFAULT_LOCALE_COUNTRY` | `config/settings.py:157` | LOW | Has default ("dk"). Not in `.env.example`. |

### 1.3 Naming Inconsistencies in .env.example

| .env.example Name | Settings Class Name | Issue |
|-------------------|-------------------|-------|
| `FASTAPI_USERS_SECRET` | Not referenced anywhere in `settings.py` | **Orphaned**: `.env.example` line 24 documents this variable but it is not consumed by the Settings class. `secret_key` is the actual JWT signing field. |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | `first_admin_email` / `first_admin_password` | **Confusing**: `.env.example` has both `ADMIN_EMAIL`/`ADMIN_PASSWORD` AND `FIRST_ADMIN_EMAIL`/`FIRST_ADMIN_PASSWORD`. Only the `FIRST_ADMIN_*` variants are consumed by `settings.py`. |
| `DEFAULT_COST_TIER` | `default_tier` | Pydantic Settings maps `DEFAULT_TIER` env var, not `DEFAULT_COST_TIER`. The `.env.example` name will be silently ignored by the Settings class (`extra="ignore"`). |
| `CORS_ORIGINS` | `allowed_origins` | Same issue: `.env.example` uses `CORS_ORIGINS` but the Settings field is `allowed_origins`, so the env var name would be `ALLOWED_ORIGINS`. |

---

## 2. Committed Secrets Scan

### 2.1 Files That Might Contain Secrets

| Pattern | Files Found | Status |
|---------|-------------|--------|
| `*.env` | `/.env.example` only | PASS -- no `.env` files committed |
| `*.key` | None | PASS |
| `*.pem` | `.venv/` CA certs only | PASS -- standard pip/certifi, not project secrets |
| `*.env.local`, `*.env.production` | None | PASS |
| Secrets in `.gitignore` | `.env`, `.env.local`, `.env.production` are all listed | PASS |

### 2.2 Hardcoded Credentials in Python Files

| Check | Result |
|-------|--------|
| Hardcoded API keys (pattern: `api_key = "..."`) | **PASS** -- No matches found in `/src/` |
| Hardcoded passwords | **PASS** -- No matches in `/src/` |
| Bearer tokens with actual values | **PASS** -- Only references to Bearer scheme in docstrings/headers, no actual tokens |
| GitHub/GitLab/Slack tokens (regex patterns) | **PASS** -- No matches |
| OpenAI-style `sk-` keys | **PASS** -- No matches |
| Base64-encoded long strings in source | **PASS** -- Only RSS URLs and standard strings found |

### 2.3 Docker Configuration

| Check | Result | Notes |
|-------|--------|-------|
| `docker-compose.yml` hardcoded secrets | **WARN** | Default credentials `observatory:observatory` for PostgreSQL and `minioadmin:minioadmin` for MinIO are embedded as fallback defaults. These are documented development defaults, not production secrets, but the docker-compose file should warn operators to override them. |
| `Dockerfile` secrets | **PASS** | No credentials, no `ARG`/`ENV` with secrets. Non-root user configured. |
| docker-compose `SECRET_KEY` | **PASS** | Uses `${SECRET_KEY}` variable substitution without a default -- will fail loudly if not set. |
| docker-compose `CREDENTIAL_ENCRYPTION_KEY` | **PASS** | Same -- no default, requires explicit setting. |
| docker-compose `PSEUDONYMIZATION_SALT` | **PASS** | Same -- no default. |

### 2.4 alembic.ini

**FINDING (MEDIUM):** `alembic.ini` line 38 contains:
```ini
sqlalchemy.url = postgresql+asyncpg://observatory:observatory@localhost:5432/observatory
```
This is a hardcoded default database connection string with username/password. While `alembic/env.py` overrides this with the `DATABASE_URL` environment variable when set, the fallback exposes a default credential pair. This is a standard Alembic pattern and the credentials (`observatory:observatory`) match the Docker development defaults, so this is acceptable for development but should be noted for production hardening.

---

## 3. Critical Security Configuration Verification

### 3.1 PSEUDONYMIZATION_SALT

| Check | Status | Details |
|-------|--------|---------|
| Required by Settings class? | **YES** | `settings.py:82`: `pseudonymization_salt: str` -- no default, required field. Pydantic will raise `ValidationError` at startup if missing. |
| Enforced before data collection? | **PARTIAL** | `normalizer.py:151-157`: If salt is empty, a `WARNING` is logged but `pseudonymized_author_id` will silently be `None` for all records. The normalizer can be constructed with no salt via the `except` fallback path at line 148. |
| Production risk | **BETA-BLOCKER** | If a Celery worker is started with `PSEUDONYMIZATION_SALT=""`, it will process records without pseudonymization, violating GDPR. The Settings class requires a non-empty string, but the normalizer's `except` fallback at line 148-149 bypasses Settings and falls back to `os.environ.get()` with a default of `""`. |

**Recommended fix:** In `normalizer.py`, raise a `RuntimeError` instead of logging a warning when `_salt` is empty, at minimum in non-test environments. Alternatively, validate that `_salt` is non-empty in the `normalize()` method before producing any records.

### 3.2 JWT_SECRET_KEY (SECRET_KEY)

| Check | Status | Details |
|-------|--------|---------|
| Required by Settings class? | **YES** | `settings.py:61`: `secret_key: str` -- required, no default. Application will not start without it. |
| Placeholder detection? | **NO** | `.env.example` sets `SECRET_KEY=change-me-in-production`. If an operator copies `.env.example` to `.env` without changing this, the app starts with a known secret. No runtime check rejects known-weak values. |
| Production risk | **BETA-BLOCKER** | JWT tokens signed with `change-me-in-production` are trivially forgeable. |

**Recommended fix:** Add a startup check in `create_app()` or as a Settings validator that rejects `secret_key` values matching `change-me*` or shorter than 32 characters when `debug=False`.

### 3.3 DATABASE_URL

| Check | Status | Details |
|-------|--------|---------|
| Required by Settings class? | **YES** | `settings.py:42`: `database_url: str` -- required, no default. |
| Validated format? | **NO** | No Pydantic validator checks that the URL uses `asyncpg` driver or contains valid host/port. |
| Production risk | LOW | Misconfiguration causes immediate connection error -- fails safe. |

### 3.4 REDIS_URL

| Check | Status | Details |
|-------|--------|---------|
| Required by Settings class? | Has default | `settings.py:54`: defaults to `redis://localhost:6379/0`. |
| Production risk | LOW | Default points to localhost; production Dockerized services use override. |

### 3.5 CREDENTIAL_ENCRYPTION_KEY (Fernet)

| Check | Status | Details |
|-------|--------|---------|
| Required by Settings class? | **YES** | `settings.py:70`: `credential_encryption_key: str` -- required, no default. |
| Validated as valid Fernet key? | **NO** | The Settings class accepts any string. An invalid Fernet key will cause a runtime error only when `credential_pool.py:_get_fernet()` first attempts to decrypt. |
| Documented generation instructions? | **YES** | Both `settings.py` docstring (line 76) and `.env.example` (line 31) include generation command. |
| Backup warning? | **YES** | `settings.py:79`: "This is the single most critical secret in the system. If lost, all stored API credentials become unrecoverable." |
| Production risk | **BETA-BLOCKER** | `.env.example` line 31 contains a non-functional placeholder value (`generate-with-python-c-from-...`). If copied verbatim, the Fernet constructor will raise `ValueError` at runtime when any credential is first decrypted, not at startup. This deferred failure means the app starts successfully but then fails mid-operation. |

**Recommended fix:** Add a startup validator (Pydantic `@field_validator`) on `credential_encryption_key` that attempts to construct a `Fernet(key)` instance and raises immediately if invalid.

---

## 4. Test Fixtures Audit

### 4.1 Recorded API Response Fixtures

All files in `tests/fixtures/api_responses/` were scanned for real API keys, tokens, or PII.

| Fixture File | Findings |
|-------------|----------|
| `tiktok/oauth_token_response.json` | Contains `"access_token": "test-tiktok-access-token-abc123"` -- clearly synthetic test value. **PASS** |
| `ai_chat_search/openrouter_*.json` | Contains only `prompt_tokens`/`completion_tokens` counts. No API keys. **PASS** |
| `event_registry/get_articles_response.json` | Contains `"remainingTokens": 4800` -- a quota counter, not an auth token. **PASS** |
| `x_twitter/twitterapiio_response.json` | Contains synthetic Danish names (Soren Arlighed, etc.) -- clearly test data. **PASS** |
| `facebook/brightdata_snapshot_response.json` | Contains synthetic post IDs and Danish text. No real PII. **PASS** |
| `instagram/brightdata_snapshot_response.json` | Contains synthetic shortcodes and fabricated usernames. **PASS** |
| `discord/gateway_response.json` | Contains only `"url": "wss://gateway.discord.gg"` -- public Discord gateway URL. **PASS** |
| All other fixtures | Synthetic data with Danish text, test IDs. **PASS** |

### 4.2 Test Environment Variables

Tests use `os.environ.setdefault()` with synthetic values. The test credential encryption key (`dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==`) decodes to `test-fernet-key-32-bytes-padded` (31 bytes) -- this is NOT a valid Fernet key (Fernet requires exactly 32 bytes of URL-safe base64). This works only because tests bypass actual Fernet decryption. If any test path ever invokes `_get_fernet()`, it will fail.

**Severity:** LOW (test-only, does not affect production).

---

## 5. Pre-commit and CI Secret Detection

### 5.1 Pre-commit Hooks (`.pre-commit-config.yaml`)

| Hook | Present | Notes |
|------|---------|-------|
| ruff (lint + format) | YES | |
| trailing-whitespace | YES | |
| end-of-file-fixer | YES | |
| check-yaml | YES | |
| check-toml | YES | |
| check-json | YES | |
| check-merge-conflict | YES | |
| check-added-large-files | YES | |
| debug-statements | YES | |
| no-commit-to-branch (main) | YES | |
| **Secret detection (detect-secrets / gitleaks)** | **NO** | **HIGH** -- No secret scanning hook is configured. |
| mypy | **NO** | Not in pre-commit; only referenced in agent system prompt. |

**FINDING (HIGH):** No secret detection pre-commit hook is configured. The `.pre-commit-config.yaml` should include either `detect-secrets` or `gitleaks` to prevent accidental credential commits.

### 5.2 CI Pipeline (`.github/workflows/ci.yml`)

| Stage | Present | Notes |
|-------|---------|-------|
| Lint (ruff) | YES | |
| Test (pytest + coverage) | YES | `--cov-fail-under=75` enforced |
| Security audit (pip-audit) | YES | But `continue-on-error: true` -- soft fail |
| Secret scanning | **NO** | No secret scanning step in CI |
| mypy type checking | **NO** | Not in CI pipeline |
| CREDENTIAL_ENCRYPTION_KEY in CI | Uses `${{ secrets.CREDENTIAL_ENCRYPTION_KEY }}` | **WARN** -- If this GitHub Actions secret is not configured, the env var will be empty and tests that touch credential pool decryption will fail silently. |

---

## 6. Additional Bypass Patterns (os.environ direct reads)

The `config/settings.py` docstring explicitly states: "never call `os.getenv` directly elsewhere in the codebase." However, the following files bypass the Settings class:

| File | Line | Variable | Justification |
|------|------|----------|---------------|
| `core/credential_pool.py` | 97 | `CREDENTIAL_ENCRYPTION_KEY` | Fallback when Settings() fails to load |
| `core/normalizer.py` | 149 | `PSEUDONYMIZATION_SALT` | Fallback when Settings() fails to load |
| `arenas/ai_chat_search/collector.py` | 469 | `OPENROUTER_API_KEY` | No credential pool configured |
| `arenas/reddit/collector.py` | 408-410 | `REDDIT_CLIENT_ID/SECRET/USER_AGENT` | No credential pool configured |
| `arenas/majestic/collector.py` | 476 | `MAJESTIC_PREMIUM_API_KEY` | No credential pool configured |
| `arenas/event_registry/collector.py` | 685 | `EVENT_REGISTRY_{TIER}_API_KEY` | No credential pool configured |
| `alembic/env.py` | 41 | `DATABASE_URL` | Standard Alembic pattern |
| `scripts/backup_postgres.py` | 70 | Multiple MinIO/DB vars | Standalone script, acceptable |
| `scripts/restore_postgres.py` | 71 | Multiple MinIO/DB vars | Standalone script, acceptable |

The arena collector fallbacks are intentional (Phase 0 backward compatibility) and are safe because they only read optional API keys. The `core/credential_pool.py` and `core/normalizer.py` fallbacks are more concerning because they silently degrade critical security features.

---

## 7. Findings Summary

### Beta-Blockers (must fix before production)

| ID | Finding | File:Line | Impact |
|----|---------|-----------|--------|
| **BB-01** | `PSEUDONYMIZATION_SALT` can be empty without blocking data collection. The normalizer's `except` fallback path at `normalizer.py:148-149` silently degrades to no pseudonymization. | `src/issue_observatory/core/normalizer.py:148-157` | GDPR violation: author identifiers stored in plaintext when salt is empty. |
| **BB-02** | `SECRET_KEY` accepts known-weak values (e.g. `change-me-in-production`) without rejection. No minimum length or entropy check. | `src/issue_observatory/config/settings.py:61` | Full authentication bypass via forged JWT tokens if the `.env.example` placeholder is used in production. |
| **BB-03** | `CREDENTIAL_ENCRYPTION_KEY` is not validated at startup. Invalid Fernet keys are accepted by Settings and only cause errors at first decryption attempt (mid-operation). | `src/issue_observatory/config/settings.py:70` | Deferred runtime failure during credential acquisition. |

### High Severity

| ID | Finding | File | Impact |
|----|---------|------|--------|
| **H-01** | No secret detection pre-commit hook configured. | `.pre-commit-config.yaml` | Developers could accidentally commit API keys or `.env` files. |
| **H-02** | `OPENROUTER_API_KEY` env var not documented in `.env.example`. | `.env.example` | AI Chat Search arena silently fails to collect without it; operator has no reference for what to set. |
| **H-03** | `MAJESTIC_PREMIUM_API_KEY` env var not documented in `.env.example`. | `.env.example` | Same issue for Majestic arena. |
| **H-04** | `.env.example` contains phantom/orphaned variable names (`FASTAPI_USERS_SECRET`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `DEFAULT_COST_TIER`, `CORS_ORIGINS`) that do not map to any Settings field and are silently ignored. | `.env.example:18,24-26,21-22,46` | Operators configure these variables believing they have effect, but they do nothing. |
| **H-05** | `pip-audit` security scan in CI is soft-fail (`continue-on-error: true`). | `.github/workflows/ci.yml:131` | Known vulnerabilities in dependencies do not block merges. |

### Medium Severity

| ID | Finding | File | Impact |
|----|---------|------|--------|
| **M-01** | SMTP configuration (6 variables) absent from `.env.example`. | `.env.example`, `settings.py:183-205` | Email notifications cannot be configured without reading source code. |
| **M-02** | `EVENT_REGISTRY_API_KEY` in `.env.example` does not match the tiered pattern (`EVENT_REGISTRY_MEDIUM_API_KEY` / `EVENT_REGISTRY_PREMIUM_API_KEY`) used in code. | `.env.example:68`, `arenas/event_registry/collector.py:684` | Operator sets wrong env var name; Event Registry silently fails to authenticate. |
| **M-03** | `alembic.ini` contains hardcoded default DB credentials (`observatory:observatory`). | `alembic.ini:38` | Low risk since `alembic/env.py` overrides via env var, but should be redacted. |
| **M-04** | Docker Compose PostgreSQL and MinIO services use well-known default credentials without a production warning comment. | `docker-compose.yml:11-13,50-51` | Risk of deploying Docker stack with default passwords. |
| **M-05** | No mypy in CI pipeline or pre-commit hooks. | `.github/workflows/ci.yml`, `.pre-commit-config.yaml` | Type errors not caught before merge. |
| **M-06** | Docker Compose backup service uses both `MINIO_ACCESS_KEY` and `MINIO_ROOT_USER` patterns for the same credential. | `docker-compose.yml:102-103` | Confusing, could lead to misconfigured backups. |
| **M-07** | Test Fernet key (`dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==`) is not a valid Fernet key (decodes to 31 bytes, not 32). | `tests/conftest.py:44`, 20+ test files | Tests that invoke actual Fernet decryption will fail with a confusing error. |

---

## 8. Recommended Actions

### Immediate (Beta-Blockers)

1. **BB-01:** Add a startup validator or guard in `Normalizer.__init__()` that raises `RuntimeError` when `_salt` is empty and `DEBUG` is `False`. Alternatively, add a Pydantic `@field_validator` on `pseudonymization_salt` in Settings that rejects empty strings.

2. **BB-02:** Add a Pydantic `@field_validator` on `secret_key` in Settings that:
   - Rejects values containing "change-me" or "change_me"
   - Requires minimum length of 32 characters when `debug=False`

3. **BB-03:** Add a Pydantic `@field_validator` on `credential_encryption_key` in Settings that attempts `Fernet(value)` construction and raises `ValueError` with a clear message if it fails.

### Short-Term (High)

4. **H-01:** Add `detect-secrets` or `gitleaks` to `.pre-commit-config.yaml`:
   ```yaml
   - repo: https://github.com/Yelp/detect-secrets
     rev: v1.4.0
     hooks:
       - id: detect-secrets
         args: ['--baseline', '.secrets.baseline']
   ```

5. **H-02, H-03:** Add `OPENROUTER_API_KEY` and `MAJESTIC_PREMIUM_API_KEY` to `.env.example` (commented out, with descriptions).

6. **H-04:** Remove or rename orphaned `.env.example` variables:
   - Remove `FASTAPI_USERS_SECRET` (replaced by `SECRET_KEY`)
   - Remove `ADMIN_EMAIL` / `ADMIN_PASSWORD` (use `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD`)
   - Rename `DEFAULT_COST_TIER` to `DEFAULT_TIER`
   - Rename `CORS_ORIGINS` to `ALLOWED_ORIGINS`

7. **H-05:** Remove `continue-on-error: true` from the `pip-audit` CI step, or add a separate hard-fail step for critical vulnerabilities.

### Medium-Term

8. **M-01:** Add SMTP section to `.env.example` with all 6 variables and comments.
9. **M-02:** Add `EVENT_REGISTRY_MEDIUM_API_KEY` and `EVENT_REGISTRY_PREMIUM_API_KEY` to `.env.example` alongside or replacing `EVENT_REGISTRY_API_KEY`.
10. **M-03:** Replace `alembic.ini` line 38 with a placeholder: `sqlalchemy.url = driver://user:pass@localhost/dbname`
11. **M-05:** Add mypy to CI and/or pre-commit hooks.
12. **M-07:** Generate a valid Fernet key for tests and update all test files.

---

## 9. What Is Working Well

- **Centralized settings:** The `config/settings.py` Pydantic Settings class is well-structured, well-documented, and uses `lru_cache` correctly.
- **Required secrets are required:** `database_url`, `secret_key`, `credential_encryption_key`, and `pseudonymization_salt` all lack defaults, meaning the app will not start if they are missing entirely.
- **`.gitignore` coverage:** `.env`, `.env.local`, `.env.production` are all excluded.
- **Docker non-root user:** The Dockerfile creates and switches to a non-root `appuser`.
- **Credential encryption at rest:** All API credentials in the database are Fernet-encrypted.
- **Test fixtures are synthetic:** No real API keys, tokens, or PII found in any test fixture.
- **Docker Compose critical secrets have no defaults:** `SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`, and `PSEUDONYMIZATION_SALT` use `${VAR}` syntax without `:-default`, meaning Docker Compose will fail if they are not set.

---

*Report generated by QA Guardian on 2026-02-21.*
