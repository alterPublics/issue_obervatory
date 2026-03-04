# Issue Observatory -- Release Notes 2026-02-26

**Date:** 2026-02-26
**Scope:** Bright Data migration planning, credential guide updates, .env cleanup

---

## Changes

### Bright Data Web Scraper API Migration Plan

A comprehensive migration plan has been drafted at `/docs/plans/bright_data_web_scraper_migration.md` to migrate the Facebook and Instagram collectors from the Bright Data **Datasets** product (pre-collected snapshots) to the **Web Scraper API** (on-demand, real-time collection).

**Motivation:**
- The hardcoded Facebook dataset ID (`gd_l95fol7l1ru6rlo116`) does not match any currently listed Bright Data product
- The Instagram collector routes all requests through the Reels dataset ID (`gd_lyclm20il4r5helnj`) regardless of content type
- The Datasets product provides pre-collected monthly snapshots, not suitable for live tracking
- The Web Scraper API is cheaper (~$1.50/1K vs ~$2.50/1K) and returns fresh on-demand data

**Key findings from research and testing:**
- Bright Data now offers **10 separate Facebook scrapers** (Posts, Comments, Reels, Groups, Events, Marketplace, etc.) and **4 Instagram scrapers** (Posts, Reels, Comments, Profiles), each with distinct dataset IDs
- The Web Scraper API uses the **same base URL and async workflow** (trigger -> poll -> download) but requires **URL-based input** instead of keyword filters
- The same API token works for all Bright Data products -- no credential changes needed
- The `"zone"` field in credential payloads is not used by the Web Scraper API
- **Keyword discovery is NOT supported** on any Facebook or Instagram Web Scraper API endpoint (tested 2026-02-26 against all 5 dataset IDs -- all returned 400 errors)

**Consequence:** `collect_by_terms()` will be **removed** from both Facebook and Instagram collectors. These arenas become actor-only collection platforms, relying on manually curated page/profile URLs, snowball sampling discoveries, and cross-platform actor matching. This aligns with how Discord and Telegram already operate as source-list arenas.

**Migration approach:** 7-phase plan covering: remove `collect_by_terms()`, update config and dataset IDs, refactor `collect_by_actors()` for URL-based input, update normalization for new response fields, add frontend guidance for actor-only collection, update credit estimation, and update tests.

### Credential Guide Updates

Updated `/docs/guides/credential_acquisition_guide.md`:

- **Facebook (section 5.1):** Rewrote to reflect Web Scraper API product. Added table of all 6 Facebook scraper dataset IDs. Updated pricing from ~$2.50/1K to ~$1.50/1K. Updated API token generation steps with correct dashboard navigation. Removed `"zone"` from credential payload.
- **Instagram (section 5.2):** Rewrote to reflect Web Scraper API product. Added table of all 4 Instagram scraper dataset IDs. Noted that Instagram media URLs expire after 24 hours. Removed `"zone"` from credential payload.
- **Cost summary table:** Updated Facebook and Instagram monthly cost estimates.

### .env.example Cleanup

- Removed redundant "Arena API Credentials -- Consolidated Reference" section at the bottom (was a commented-out, incomplete duplicate of the variables above)
- Moved the auto-bootstrap explanation note to the file header
- Removed unused environment variables:
  - `GOOGLE_CUSTOM_SEARCH_API_KEY` / `GOOGLE_CUSTOM_SEARCH_CX` (not referenced in any code; Google Search uses Serper/SerpAPI)
  - `TELEGRAM_PHONE` (informational only, not used by the collector)
  - `GDELT_DOC_API_URL` (URL is hardcoded in `gdelt/config.py`)
- Added explanatory comment on `TELEGRAM_SESSION_STRING` pointing to the credential guide

### Documentation Notes

- **Gab API access** requires a Gab Pro subscription ($15/month) to create developer apps. The Mastodon-compatible API that the Gab collector relies on was frozen in December 2020; reliability is uncertain.
- **Threads API** requires a separate "Threads App ID" (found under Use Cases > Customize > Settings in Meta Developer Dashboard), not the main Meta app ID. Adding testers is currently disabled by Meta, which blocks development-mode OAuth.
- **Discord bot invitation** cannot be automated -- server admins must manually authorize via the OAuth2 invite URL. The invite URL is generated under OAuth2 > URL Generator in the developer portal (select only the `bot` scope).

---

## Files Changed

| File | Change |
|------|--------|
| `.env.example` | Removed redundant section, unused vars; added bootstrap note and Telegram comment |
| `docs/guides/credential_acquisition_guide.md` | Rewrote Facebook and Instagram Bright Data sections for Web Scraper API |
| `docs/plans/bright_data_web_scraper_migration.md` | New: comprehensive migration plan |
| `docs/release_notes/release_notes_2026_02_26.md` | New: this file |
