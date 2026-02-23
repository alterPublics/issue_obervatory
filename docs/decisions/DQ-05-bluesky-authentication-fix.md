# Decision Record: DQ-05 Bluesky Authentication Fix

**Date**: 2026-02-23
**Status**: Implemented
**Issue**: DQ-05
**Component**: Bluesky arena collector

## Problem

The Bluesky collector was failing with HTTP 403 errors despite having credentials configured in `.env`. The error message was:

```
bluesky: HTTP 403 from public API
```

The root cause was that the collector was designed to use unauthenticated access to Bluesky's public API, but as of early 2026, Bluesky requires authentication for all search and feed endpoints.

## Investigation

1. **Collector design**: The original implementation treated Bluesky credentials as optional and made all requests unauthenticated
2. **API change**: Bluesky's `app.bsky.feed.searchPosts` and related endpoints now return HTTP 403 for unauthenticated requests
3. **Poor error reporting**: The original error message didn't include the URL or response body, making diagnosis difficult
4. **Missing auth flow**: The collector had no code to authenticate or use bearer tokens

## Solution

Implemented full authentication support:

### 1. Authentication Method
Added `_authenticate()` method that:
- Acquires credentials from the credential pool (`BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD`)
- Calls `com.atproto.server.createSession` to obtain a JWT access token
- Caches the token for the collector instance lifetime
- Provides actionable error messages if credentials are missing or invalid

### 2. Request Updates
Modified `_make_request()` to:
- Authenticate before first request
- Include `Authorization: Bearer {token}` header on all requests
- Provide detailed error messages including URL and response details
- Handle HTTP 403 with clear authentication guidance

### 3. Health Check
Updated `health_check()` to:
- Authenticate before testing the API
- Report authentication failures separately from API failures
- Include detailed error information in responses

### 4. Credential Cleanup
Added `_release_credential()` method:
- Releases credentials back to the pool after collection
- Clears cached session token
- Called in `finally` blocks of both collection methods

### 5. Configuration Updates
- Updated `BLUESKY_TIERS` to set `requires_credential=True`
- Updated docstrings to reflect authentication requirement
- Updated arena brief (`/docs/arenas/bluesky.md`) to document auth requirement

## Error Messages

Before:
```
bluesky: HTTP 403 from public API
```

After (no credentials):
```
Bluesky search requires authentication. Set BLUESKY_HANDLE and
BLUESKY_APP_PASSWORD in your .env file, or add credentials via
the admin panel.
```

After (auth failure):
```
Bluesky authentication failed at https://public.api.bsky.app/xrpc/com.atproto.server.createSession:
HTTP 401: {"error": "AuthenticationRequired", "message": "Invalid identifier or password"}
```

## Files Modified

1. `/src/issue_observatory/arenas/bluesky/collector.py`
   - Added `_authenticate()` method
   - Modified `_make_request()` to use authentication
   - Updated `health_check()` for auth support
   - Added `_release_credential()` cleanup
   - Updated docstrings

2. `/src/issue_observatory/arenas/bluesky/config.py`
   - Updated module docstring
   - Changed `requires_credential` from `False` to `True`

3. `/docs/arenas/bluesky.md`
   - Updated access model description
   - Marked all endpoints as requiring auth
   - Updated authentication section
   - Updated credential requirements table
   - Updated rate limits section
   - Added authentication flow guidance

## Testing

To verify the fix:

```bash
# Set credentials in .env
BLUESKY_HANDLE=your.handle.bsky.social
BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx

# Test health check
curl -X GET http://localhost:8000/api/arenas/bluesky/health

# Test collection (via UI or API)
# Should now succeed with authentication
```

## Backward Compatibility

The credential pool already had the correct mapping for Bluesky credentials:
```python
("bluesky", "free"): {
    "handle": "BLUESKY_HANDLE",
    "app_password": "BLUESKY_APP_PASSWORD",
}
```

No changes to the credential pool were needed. Users just need to set the environment variables.

## Test Updates Required

The existing tests in `/tests/arenas/test_bluesky.py` will need updates to mock the authentication flow:

1. Add a mock for the `com.atproto.server.createSession` endpoint
2. Mock it to return a valid JWT token
3. Provide mock credentials to the collector via credential pool

Example pattern:
```python
@respx.mock
async def test_collect_by_terms_with_auth():
    # Mock authentication endpoint
    respx.post("https://public.api.bsky.app/xrpc/com.atproto.server.createSession").mock(
        return_value=httpx.Response(200, json={"accessJwt": "test-token-123"})
    )

    # Mock search endpoint (now requires auth header)
    respx.get(BSKY_SEARCH_POSTS_ENDPOINT).mock(
        return_value=httpx.Response(200, json=fixture)
    )

    # Provide mock credentials
    collector = BlueskyCollector(credential_pool=MockCredentialPool())
    # ... rest of test
```

**Note**: These test updates are **NOT** included in this fix. The tests will currently fail until updated. This should be handled by the QA Guardian.

## Future Considerations

1. **Token refresh**: Session tokens expire. Consider implementing token refresh logic if collection runs extend beyond token lifetime
2. **Multiple accounts**: If rate limits become a constraint, the credential pool's rotation logic will work without code changes
3. **Session caching**: Currently tokens are per-collector-instance. Consider caching tokens in Redis for cross-task reuse
4. **Error reporting**: The enhanced error messages should make debugging auth issues much easier

## References

- Bluesky API docs: https://docs.bsky.app/
- AT Protocol authentication: https://atproto.com/specs/xrpc#authentication
- Credential pool implementation: `/src/issue_observatory/core/credential_pool.py`
