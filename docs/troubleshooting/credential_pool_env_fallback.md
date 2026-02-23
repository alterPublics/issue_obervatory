# Credential Pool .env Fallback Troubleshooting

## Issue
Collection fails with `NoCredentialAvailableError` even though the API key is set in the `.env` file.

## How the Fallback Works

The credential pool automatically falls back to environment variables when no database credentials exist:

1. **Checks the database first** for stored credentials
2. **Falls back to .env variables** if no DB credentials are found
3. **Uses platform-specific mappings** defined in `_PLATFORM_ENV_MAP`

### Supported Platforms with Mapped Credentials

| Platform | Tier | Env Var Names |
|----------|------|---------------|
| serper | medium | `SERPER_API_KEY` |
| serpapi | premium | `SERPAPI_API_KEY` |
| youtube | free | `YOUTUBE_API_KEY` |
| reddit | free | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` |
| tiktok | free | `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` |
| telegram | free | `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION_STRING` |
| bluesky | free | `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` |
| event_registry | medium/premium | `EVENT_REGISTRY_API_KEY` |
| twitterapi_io | medium | `TWITTERAPIIO_API_KEY` |
| x_twitter | premium | `X_BEARER_TOKEN`, `X_API_KEY`, `X_API_SECRET` |
| discord | free | `DISCORD_BOT_TOKEN` |
| openrouter | medium/premium | `OPENROUTER_API_KEY` |
| gab | free | `GAB_ACCESS_TOKEN` |
| threads | free | `THREADS_ACCESS_TOKEN` |
| brightdata_facebook | medium | `BRIGHTDATA_FACEBOOK_API_TOKEN` |
| brightdata_instagram | medium | `BRIGHTDATA_INSTAGRAM_API_TOKEN` |
| majestic | premium | `MAJESTIC_API_KEY` |
| twitch | free | `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` |

For platforms not in this list, the fallback tries the generic pattern: `{PLATFORM}_{TIER}_API_KEY`

## Common Causes and Solutions

### 1. Celery Worker Not Restarted

**Symptom**: Env var is in `.env` but collection still fails.

**Cause**: The Celery worker loads environment variables at startup. If you added/changed the env var after the worker started, it won't see the new value.

**Solution**: Restart the Celery worker.

```bash
# Stop the worker (Ctrl+C if running in terminal)
# Then restart:
celery -A issue_observatory.workers.celery_app worker -l info
```

### 2. Wrong Working Directory

**Symptom**: `.env` file exists but isn't being loaded.

**Cause**: `load_dotenv()` looks for `.env` in the current working directory. If you're running Celery from a different directory, it won't find the file.

**Solution**: Always run Celery from the project root directory.

```bash
# Make sure you're in the project root
cd /path/to/issue_observatory

# Then start the worker
celery -A issue_observatory.workers.celery_app worker -l info
```

### 3. Credential on Cooldown

**Symptom**: First collection attempt failed, subsequent attempts also fail even though the credential is valid.

**Cause**: After an error (especially rate limit or auth errors), the credential is placed on cooldown in-memory for a few minutes.

**Solution**: Wait a few minutes and try again, or restart the Celery worker to clear the in-memory cooldown state.

### 4. Wrong Env Var Name

**Symptom**: Using `SERPER_MEDIUM_API_KEY` instead of `SERPER_API_KEY`.

**Cause**: The generic pattern (`{PLATFORM}_{TIER}_API_KEY`) is only used as a last resort. The mapped credentials take precedence.

**Solution**: Use the exact env var name from the table above. For Google Search (MEDIUM tier), use `SERPER_API_KEY` not `SERPER_MEDIUM_API_KEY`.

### 5. Env Var Not Exported in Shell

**Symptom**: Running Celery directly from a shell where the env var is not set.

**Cause**: `.env` file is not automatically loaded by the shell. You must either export the var or rely on `load_dotenv()`.

**Solution**: Let the application load the `.env` file via `load_dotenv()`. Don't manually export vars unless necessary.

## Verifying the Fix

### Check the Logs

When a credential is acquired from env, you should see a DEBUG log message:

```
Acquired env credential 'env:serper:medium' for serper/medium (mapped).
```

To see DEBUG logs, set `LOG_LEVEL=DEBUG` in your `.env` file and restart the worker.

### Run the Test

Verify that the mapped credential acquisition works:

```bash
pytest tests/unit/test_credential_pool.py::TestCredentialPoolAcquire::test_acquire_uses_mapped_env_var_over_generic_pattern -v
```

### Test with a Script

Create a test script to verify env acquisition:

```python
import asyncio
import os
from issue_observatory.core.credential_pool import CredentialPool

async def test():
    print(f"SERPER_API_KEY: {os.environ.get('SERPER_API_KEY', 'NOT SET')}")

    pool = CredentialPool()
    cred = await pool.acquire(platform="serper", tier="medium")

    if cred:
        print(f"✅ Acquired: {cred['id']}")
    else:
        print("❌ Failed to acquire")

asyncio.run(test())
```

Run it from the project root:

```bash
python test_script.py
```

## Still Not Working?

If the credential pool still fails after trying the above:

1. **Check the `.env` file format**: Make sure there are no quotes around the value unless necessary, no extra spaces, and the file uses Unix line endings (LF not CRLF).

2. **Verify the env var is actually set**: Add logging to the credential pool's `_acquire_from_env_map` method to print the env dict.

3. **Check for DB credentials**: If there ARE DB credentials but they're all on cooldown or quota-exceeded, the env fallback won't be used. The pool only falls back when NO DB credentials exist for the platform+tier.

4. **File a bug report**: If none of the above helps, this is a genuine bug. File an issue with:
   - The exact error message
   - The collector and tier you're trying to use
   - The env var name and whether it's set in `.env`
   - Whether the Celery worker was restarted after setting the env var
   - Log output with `LOG_LEVEL=DEBUG`
