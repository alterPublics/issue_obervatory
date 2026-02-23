# Decision Record: Bluesky API URL Fix

**Date**: 2026-02-23
**Status**: Implemented
**Component**: Bluesky arena collector
**Issue**: HTTP 403 errors during collection

## Problem

The Bluesky collector was failing with HTTP 403 Forbidden errors. Investigation revealed that the API base URL had changed.

## Root Cause

The Bluesky AT Protocol API endpoint moved from `https://public.api.bsky.app/xrpc` to `https://bsky.social/xrpc`. The old public API endpoint now returns 403 Forbidden for all requests.

Verification via curl:
- Old URL (`public.api.bsky.app`): Returns 403 Forbidden HTML error page
- New URL (`bsky.social`): Returns 401 Authentication Required (correct response)

## Solution

Updated all references to the Bluesky API base URL from `public.api.bsky.app` to `bsky.social`:

### Code Changes

1. **`src/issue_observatory/arenas/bluesky/config.py`**
   - Changed `BSKY_API_BASE` from `https://public.api.bsky.app/xrpc` to `https://bsky.social/xrpc`
   - Updated docstring from "AT Protocol public API base URL (unauthenticated read access)" to "AT Protocol API base URL (requires authentication)"
   - Updated module docstring to reflect the correct base URL

2. **`src/issue_observatory/arenas/bluesky/collector.py`**
   - Updated module docstring to specify `https://bsky.social/xrpc` for authentication

### Documentation Changes

3. **`docs/arenas/bluesky.md`**
   - Updated access model section: `public.api.bsky.app` → `bsky.social`
   - Updated Base URL field: `https://public.api.bsky.app` → `https://bsky.social`
   - Updated health check example URL

4. **`docs/status/qa.md`**
   - Updated HTTP mocking strategy table: `respx` on `public.api.bsky.app` → `bsky.social`

5. **`docs/status/core.md`**
   - Updated Task 1.5 design notes: AT Protocol public API (`public.api.bsky.app`), unauthenticated → AT Protocol API (`bsky.social`), requires authentication

6. **`docs/decisions/DQ-05-bluesky-authentication-fix.md`**
   - Updated error message example URLs
   - Updated test example mock URLs

7. **`docs/guides/credential_acquisition_guide.md`**
   - Removed "No credentials strictly required" language
   - Made authentication required (not optional)
   - Removed unauthenticated rate limit row
   - Updated description to reflect authentication requirement

## Impact

- **Backward compatibility**: None required. The old URL never worked in production.
- **Tests**: No test code changes needed. Tests use `BSKY_SEARCH_POSTS_ENDPOINT` constant, which now automatically points to the correct URL.
- **Credentials**: No changes to credential structure. The `BLUESKY_HANDLE` and `BLUESKY_APP_PASSWORD` environment variables remain the same.

## Verification

The fix can be verified by:

1. Setting valid Bluesky credentials in `.env`
2. Running the health check: `GET /api/arenas/bluesky/health`
3. Initiating a collection with Bluesky enabled

Expected result: Collection should succeed with 200/401 responses (depending on auth status), not 403.

## Files Modified

- `src/issue_observatory/arenas/bluesky/config.py`
- `src/issue_observatory/arenas/bluesky/collector.py`
- `docs/arenas/bluesky.md`
- `docs/status/qa.md`
- `docs/status/core.md`
- `docs/decisions/DQ-05-bluesky-authentication-fix.md`
- `docs/guides/credential_acquisition_guide.md`

## References

- Bluesky API documentation: https://docs.bsky.app/
- AT Protocol XRPC specification: https://atproto.com/specs/xrpc
- Previous authentication fix: DQ-05-bluesky-authentication-fix.md
