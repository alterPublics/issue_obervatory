# Explore Page Fixes (R-10 and R-11)

**Date:** 2026-02-23
**File:** `src/issue_observatory/api/templates/explore/index.html`
**Issues Fixed:** R-10 (platform errors) and R-11 (results not explorable)

## Summary

Fixed critical issues preventing the Explore page from functioning properly. The page now correctly displays available arenas, shows credential status, filters out unsupported arenas, and handles errors gracefully.

## Changes Applied

### 1. Arena Filtering (R-10 Fix)

**Problem:** Arenas that don't support term-based exploration were shown and would fail when selected.

**Solution:** Filter out arenas that don't work with ad-hoc term search:
- `url_scraper` — requires URL list
- `majestic` — backlink index only, PREMIUM tier only
- `twitch` — deferred stub
- `vkontakte` — deferred stub
- `discord` — requires `channel_ids` parameter

```javascript
.filter(arena => !['url_scraper', 'majestic', 'twitch', 'vkontakte', 'discord'].includes(arena.platform_name))
```

### 2. Credential Status Indicators (R-10 Fix)

**Problem:** Users had no way to know which arenas had credentials configured.

**Solution:**
- Added `hasCredentials: arena.has_credentials` to arena object mapping
- Added visual indicator (green dot = configured, amber dot = may be required) next to each arena name
- Tooltip shows "Credentials configured" or "Credentials may be required"

```html
<span
    class="inline-flex w-2 h-2 rounded-full"
    :class="arena.hasCredentials ? 'bg-green-500' : 'bg-amber-500'"
    :title="arena.hasCredentials ? 'Credentials configured' : 'Credentials may be required'"
></span>
```

### 3. Better Error Messages (R-10 Fix)

**Problem:** Generic error messages didn't help users understand what went wrong.

**Solution:** Added status-code-specific error messages:

```javascript
if (status === 402) {
    errorMsg = 'Credentials not configured';
} else if (status === 429) {
    errorMsg = 'Rate limit exceeded';
} else if (status === 503) {
    errorMsg = 'Service unavailable or credentials missing';
}
```

### 4. Authenticated Requests (R-10 Fix)

**Problem:** Some arena endpoints require authentication but requests weren't including credentials.

**Solution:** Added `credentials: 'include'` to all fetch calls:

```javascript
const response = await fetch(endpoint, {
    credentials: 'include',
    method: 'POST',
    // ...
});
```

### 5. Safe Field Access (R-11 Fix)

**Problem:** Missing fields in response records caused rendering failures.

**Solution:** Added proper fallbacks for all fields:

```javascript
// Title with substring fallback
x-text="record.title || (record.text_content && record.text_content.substring(0, 80)) || '(no title)'"

// Author
x-text="record.author_display_name || '—'"

// Engagement score with type check
x-text="typeof record.engagement_score === 'number' ? record.engagement_score : '—'"
```

### 6. Record Key Uniqueness (R-11 Fix)

**Problem:** Some records may not have `external_id` causing React-style keying issues.

**Solution:** Added fallback key generation:

```javascript
:key="record.external_id || record.platform_id || idx"
```

## Testing Checklist

- [x] Arenas with credentials show green indicator
- [x] Arenas without credentials show amber indicator
- [x] Excluded arenas do not appear in the list
- [x] Bluesky (no credentials required) returns results
- [x] Reddit (requires credentials) shows appropriate error if not configured
- [x] Results table displays correctly with missing fields
- [x] Record detail modal handles missing fields gracefully
- [x] Multi-arena search works and merges results
- [x] Per-arena error messages are helpful
- [x] Search progress indicators update correctly

## Supported Arenas

The following FREE tier arenas now work on the Explore page:

| Arena | Credentials Required | Status |
|-------|---------------------|--------|
| Bluesky | No | Working |
| Reddit | Yes (OAuth) | Working with credentials |
| YouTube | Yes (API key) | Working with credentials |
| RSS Feeds | No | Working |
| GDELT | No | Working |
| Telegram | Yes (API ID) | Working with credentials |
| TikTok | Yes (Client Key) | Working with credentials |
| Ritzau Via | No | Working |
| Gab | No | Working |
| Threads | Optional | Working |
| Common Crawl | No | Working |
| Wayback Machine | No | Working |
| Wikipedia | No | Working |
| Google Autocomplete | Optional (MEDIUM tier) | Working (FREE tier uses undocumented endpoint) |

## Not Included (by Design)

- **Discord** — Requires `channel_ids` parameter, not suitable for ad-hoc exploration
- **URL Scraper** — Requires researcher-provided URL list
- **Majestic** — PREMIUM tier only, backlink index requires specific domains
- **Twitch** — Deferred stub
- **VKontakte** — Deferred stub pending legal review

## Related Files

- `/api/routes/arenas.py` — Arena list endpoint with `has_credentials` field
- `/arenas/*/router.py` — Per-arena standalone routers
- `/config/danish_defaults.py` — Default language/locale settings

## Notes

- The multi-arena checkbox design was already partially implemented before this fix
- This fix builds on that foundation and makes it actually work
- All changes are backward-compatible with existing functionality
- No database migrations required
- No breaking changes to API contracts
