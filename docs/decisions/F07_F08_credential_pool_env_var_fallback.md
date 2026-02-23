# F-07/F-08: Credential Pool Environment Variable Fallback Fix

**Date**: 2026-02-23
**Status**: Implemented
**Related Issues**: F-07, F-08

---

## Problem

Multiple arenas fail with "No credential available for platform 'X' at tier 'Y'" despite having API keys configured in `.env`:

- Google Search: `SERPER_API_KEY` is set but fails with "No credential available for platform 'serper' at tier 'medium'"
- TikTok: `TIKTOK_CLIENT_KEY` and `TIKTOK_CLIENT_SECRET` are set but fail
- Gab: `GAB_ACCESS_TOKEN` is empty (correctly fails, but issue was reported as a bug)

### Root Cause

The `CredentialPool` class has environment variable fallback logic that reads from `os.environ` (lines 598-660 in `core/credential_pool.py`). However, Celery workers were not calling `load_dotenv()` to load the `.env` file into `os.environ`.

**Flow breakdown**:

1. FastAPI application (`api/main.py`):
   - Calls `load_dotenv()` on line 49 ✓
   - `.env` values are injected into `os.environ` ✓
   - `CredentialPool()` can read env vars ✓

2. Celery workers (`workers/celery_app.py`):
   - Did NOT call `load_dotenv()` ✗
   - Pydantic Settings loads `.env` into its own model attributes, but does NOT inject into `os.environ` ✗
   - `CredentialPool()` gets empty `os.environ` dict ✗
   - Env var fallback fails ✗

### Why Pydantic Settings Isn't Enough

`pydantic_settings.BaseSettings` with `env_file=".env"` loads the `.env` file into the Pydantic model's attributes, but it does **not** modify `os.environ`. This is by design — Pydantic Settings is meant to provide validated, typed access to configuration without polluting the global environment.

The `CredentialPool` uses `dict(os.environ)` (line 221) to initialize its `_env` attribute, which is used by the env var fallback logic. Without `load_dotenv()`, `os.environ` doesn't contain the arena API keys from `.env`.

---

## Solution

Added `load_dotenv()` call to `workers/celery_app.py` before importing `Settings`, matching the pattern already used in `api/main.py`.

**Changed file**: `src/issue_observatory/workers/celery_app.py`

```python
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# F-07/F-08 fix: Load .env values into os.environ so CredentialPool can
# access arena API keys via env var fallback
# ---------------------------------------------------------------------------

load_dotenv()

from issue_observatory.config.settings import get_settings
```

---

## Impact

### What Now Works

1. **Google Search (Serper.dev, MEDIUM tier)**:
   - `SERPER_API_KEY` env var is now accessible to Celery workers
   - Credential pool's `_acquire_from_env_map()` finds the mapping for `("serper", "medium")` → `{"api_key": "SERPER_API_KEY"}`
   - Returns valid credential dict

2. **TikTok (FREE tier)**:
   - `TIKTOK_CLIENT_KEY` and `TIKTOK_CLIENT_SECRET` env vars are now accessible
   - Credential pool's `_acquire_from_env_map()` finds the mapping for `("tiktok", "free")` → `{"client_key": "TIKTOK_CLIENT_KEY", "client_secret": "TIKTOK_CLIENT_SECRET"}`
   - Returns valid credential dict

3. **All other arenas with env-var-configured credentials**: YouTube, Reddit, Telegram, Bluesky, Event Registry, X/Twitter, Discord, OpenRouter, Threads, Bright Data, Majestic, etc.

### What Correctly Fails

**Gab**: `GAB_ACCESS_TOKEN` is empty in `.env`, so the credential pool correctly returns `None`. This is expected behavior. Gab requires OAuth 2.0 credentials (client_id, client_secret, access_token) per its arena brief. The user must:

1. Register an OAuth application on Gab
2. Complete the OAuth authorization flow
3. Store the access token in `.env` or register a credential in the database

**Arenas that don't require credentials** (RSS feeds, GDELT, Via Ritzau, Common Crawl, Wayback Machine, Wikipedia) accept `credential_pool=None` in their constructors and never call `acquire()`. They are unaffected by this fix.

---

## Verification

To verify the fix works:

1. **Standalone router test** (FastAPI already had `load_dotenv()`):
   ```bash
   curl -X POST http://localhost:8000/google-search/collect/terms \
     -H "Content-Type: application/json" \
     -d '{"terms": ["denmark"], "tier": "medium", "max_results": 10}'
   ```

2. **Celery task test** (now fixed):
   ```bash
   celery -A issue_observatory.workers.celery_app call \
     issue_observatory.arenas.google_search.tasks.collect_by_terms \
     --kwargs='{"terms": ["denmark"], "tier": "medium", "max_results": 10}'
   ```

Both should now succeed if `SERPER_API_KEY` is set in `.env`.

---

## Future Considerations

### Alternative Approaches (Rejected)

1. **Read credentials directly from Pydantic Settings in `CredentialPool`**:
   - Would require `CredentialPool` to import `get_settings()` and map each `(platform, tier)` to a specific Settings attribute
   - Tight coupling between credential pool and settings
   - Less flexible for testing (can't easily inject custom env dicts)
   - Rejected in favor of `load_dotenv()` which maintains existing architecture

2. **Register all env vars as database credentials at startup**:
   - Could auto-register env-var-based credentials into the `api_credentials` table on app startup
   - Would unify DB and env var credential paths
   - Complex migration; unclear ownership (what if both DB and env var exist?)
   - Deferred for future consideration (IP2-070)

### Credential Priority (Current Behavior)

When `CredentialPool.acquire(platform, tier)` is called:

1. **First**: Query database for active `ApiCredential` rows (lines 552-596)
2. **Second**: If no DB credentials, fall back to `_acquire_from_env()` (line 599)
   - Check `_PLATFORM_ENV_MAP` for platform-specific mapping (line 621)
   - If mapping exists, try `_acquire_from_env_map()` (line 623)
   - Otherwise, try generic `{PLATFORM}_{TIER}_API_KEY` pattern (line 628)
3. **Result**: Returns first usable credential, or `None` if none found

This priority order is correct: DB credentials take precedence, allowing admins to rotate keys without redeploying.

---

## Related Code

- **Credential pool**: `src/issue_observatory/core/credential_pool.py`
- **Platform env map**: Lines 75-117 in credential_pool.py
- **Entry points**:
  - FastAPI: `src/issue_observatory/api/main.py` (already had `load_dotenv()`)
  - Celery workers: `src/issue_observatory/workers/celery_app.py` (fixed in this change)
  - Celery Beat: Uses same `celery_app`, so fix applies automatically

---

## Testing Notes

- Unit tests for `CredentialPool` already inject custom `env` dicts (e.g., `tests/unit/test_credential_pool.py` line 60), so they are unaffected
- Integration tests that spawn actual Celery workers now require `.env` to be present or `load_dotenv()` to be mocked
- Arena router tests (FastAPI TestClient) use the main app which already had `load_dotenv()`, so they are unaffected

---

## Documentation Updates

1. This decision record (ADR)
2. Updated release notes with F-07/F-08 fix
3. No changes needed to `.env.example` (already documents all arena credentials)
4. No changes needed to arena briefs (credential requirements are already documented)
