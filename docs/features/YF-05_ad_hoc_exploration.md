# YF-05: Ad-Hoc Exploration Mode

**Status:** Implemented
**Implementation Date:** 2026-02-19

## Overview

The Ad-Hoc Exploration Mode allows researchers to run quick, exploratory queries against low-cost arenas before committing to a formal query design. This addresses the workflow gap where researchers need to discover what associations exist around a topic before creating a structured query design.

## Implementation Details

### New Page Route

- **Path:** `/explore`
- **Template:** `src/issue_observatory/api/templates/explore/index.html`
- **Route Handler:** `explore_page()` in `src/issue_observatory/api/routes/pages.py`

### Supported Arenas

The exploration page is limited to free or low-cost arenas:

1. **Google Autocomplete** - Search term suggestions and related queries
2. **Bluesky** - Danish social media posts
3. **Reddit** - Danish subreddit discussions
4. **RSS Feeds** - Danish news media articles
5. **Gab** - Alternative social media platform

### Features

#### Search Interface
- Single text input for topic/search term
- Radio button selector for arena choice
- "Run Exploration" button with loading state
- Real-time error display with user-friendly messages

#### Special Handling for Google Autocomplete
- When Google Autocomplete is selected, suggestions are displayed in a separate "Related Terms and Suggestions" card
- Useful for discovering term variations and related queries

#### Results Display
- Simple table showing:
  - Platform badge
  - Title/content preview
  - Author name
  - Published date
  - Engagement score
- Limited to 50 visible rows (with indicator if more results exist)
- Empty state when no results found
- Click-to-expand placeholder (future enhancement)

#### Bridge to Query Design
- "Create Query Design from This Term" button
- Navigates to `/query-designs/new`
- Future enhancement: pre-populate the form with the explored term

### Technical Architecture

#### Frontend
- Built with Alpine.js 3 for reactive state management
- No HTMX used (direct fetch API calls)
- Inline `explorerApp()` Alpine component with:
  - `searchTerm` - user input
  - `selectedArena` - arena radio selection
  - `isLoading` - request state
  - `error` - error message display
  - `results` - normalized content records
  - `suggestions` - Google Autocomplete-specific term list

#### Backend Endpoints Used
All endpoints are existing arena ad-hoc collection endpoints:

- `/arenas/google-autocomplete/collect` (POST)
- `/arenas/bluesky/collect/terms` (POST)
- `/arenas/reddit/collect/terms` (POST)
- `/arenas/rss-feeds/collect/terms` (POST)
- `/arenas/gab/collect/terms` (POST)

Request body format (standardized across arenas):
```json
{
  "terms": ["search_term"],
  "max_results": 100
}
```

Response format:
```json
{
  "count": 42,
  "arena": "bluesky",
  "records": [
    {
      "platform": "bluesky",
      "title": "Post title",
      "author_display_name": "Author Name",
      "published_at": "2026-02-19T12:00:00Z",
      "engagement_score": 15,
      "external_id": "...",
      "text_content": "..."
    }
  ]
}
```

### Navigation Integration

The "Explore" link is positioned **before** "Query Designs" in the sidebar navigation to encourage the explore-first workflow:

1. Dashboard
2. **Explore** ← NEW
3. Query Designs
4. Collections
5. Content
6. Actors
7. Analysis

This ordering guides researchers to explore before formalizing their queries.

### Key Design Decisions

#### Why No Credit Deduction?
The exploration endpoints use arena routers that explicitly do not deduct credits. This allows researchers to freely explore without worrying about credit consumption. The route documentation for each arena router states: "Credits are not deducted by this endpoint."

#### Why These Five Arenas?
- **Google Autocomplete:** FREE tier, instant suggestions, no API key required
- **Bluesky:** FREE tier, no authentication required, `lang:da` filter built-in
- **Reddit:** FREE tier, uses asyncpraw with read-only access
- **RSS Feeds:** FREE tier, Danish feeds curated and pre-configured
- **Gab:** FREE tier, Mastodon-compatible API

Excluded arenas (not suitable for exploration):
- Paid tiers (TikTok, X/Twitter, Event Registry, Facebook, Instagram)
- Slow/bulk arenas (GDELT, Common Crawl, Wayback Machine)
- Credential-dependent arenas (Telegram, Discord, YouTube API)

#### Why Limit to 100 Results?
Exploration is meant to be quick and lightweight. 100 results provides sufficient signal for researchers to determine if a topic is worth formalizing into a query design without overwhelming the UI or consuming excessive API quota.

## User Workflow

### Discovery Flow
1. Researcher lands on `/explore`
2. Enters a topic (e.g., "klimaforandring")
3. Selects an arena (default: Google Autocomplete)
4. Clicks "Run Exploration"
5. Reviews results:
   - For Google Autocomplete: sees related term suggestions
   - For other arenas: sees actual content records
6. If topic looks promising, clicks "Create Query Design" to formalize it

### Error Handling
- Invalid arena selection → 400 error (handled by backend)
- Missing credentials → 402 error with guidance to contact admin
- Rate limiting → 429 error with retry-after message
- Arena API errors → 502 error with arena-specific detail

All errors are displayed in a dismissible alert banner at the top of the results area.

## Future Enhancements

### Query Design Pre-Population (Not Implemented)
The "Create Query Design" button currently navigates to `/query-designs/new` without pre-populating the form. A future enhancement would:
1. Pass `?term=...&arena=...` query parameters
2. Modify the query design editor to read these parameters
3. Auto-populate the first search term and select the appropriate arena checkbox

### Record Detail Modal (Not Implemented)
Clicking a result row could open a modal with full record details (raw metadata, full text, engagement breakdown). Currently it only logs to console.

### Cross-Arena Comparison (Not Implemented)
Allow running the same term against multiple arenas simultaneously and displaying results side-by-side.

### Saved Explorations (Not Implemented)
Allow bookmarking exploration results for later reference without creating a full query design.

## Testing

### Manual Testing Checklist
- [ ] Page loads at `/explore`
- [ ] "Explore" link appears in nav before "Query Designs"
- [ ] Default arena is Google Autocomplete
- [ ] Entering a term and clicking "Run" triggers the correct endpoint
- [ ] Google Autocomplete shows suggestions card
- [ ] Other arenas show content table
- [ ] Error states display correctly
- [ ] "Create Query Design" button navigates to correct page
- [ ] Results table shows all expected columns
- [ ] Empty state appears when no results found
- [ ] Loading spinner appears during request

### Automated Tests (Future)
- Unit test for `explore_page()` route handler
- Integration test for exploration flow (mocked arena responses)
- End-to-end test for full user workflow

## Files Modified

### New Files
- `src/issue_observatory/api/templates/explore/index.html`

### Modified Files
- `src/issue_observatory/api/routes/pages.py` - Added `explore_page()` route
- `src/issue_observatory/api/templates/_partials/nav.html` - Added "Explore" nav item

## Related Documentation

- Arena router documentation in each `arenas/{name}/router.py`
- YF-02: Source-list arena configuration UI (related feature)
- Implementation Plan 2.0: Item YF-05

## Notes

- This feature complements but does not replace formal query designs
- Exploration is a discovery tool, not a data collection tool
- All exploration endpoints use authenticated access (no anonymous probing)
- Arena health is not checked before exploration (fails gracefully if arena is down)
