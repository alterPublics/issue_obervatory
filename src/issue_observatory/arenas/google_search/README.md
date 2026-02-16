# Google Search Arena

Collects Google Search organic results via programmatic APIs.
Targeting the Danish media landscape by default (`gl=dk`, `hl=da`).

## Supported Tiers

| Tier    | Provider    | Cost          | Rate Limit       | Max Results/Run |
|---------|-------------|---------------|------------------|-----------------|
| FREE    | —           | Not available | —                | —               |
| MEDIUM  | Serper.dev  | $0.30 / 1K    | 100 req/min      | 10,000          |
| PREMIUM | SerpAPI     | ~$2.75–25/1K  | 200 req/min      | 100,000         |

**FREE tier is not available.** Google has no free programmatic search API.
Requesting `tier=free` returns an empty result set with a warning log.
Use `tier=medium` or `tier=premium`.

## Required Credentials

Set these environment variables before running the arena.
The Phase 0 credential pool reads them by convention
(`{PLATFORM}_{TIER}_API_KEY`):

| Tier    | Environment Variable      | Provider account         |
|---------|---------------------------|--------------------------|
| MEDIUM  | `SERPER_MEDIUM_API_KEY`   | https://serper.dev       |
| PREMIUM | `SERPAPI_PREMIUM_API_KEY` | https://serpapi.com      |

Sign up at the respective provider, create an API key, and set the variable
in your `.env` file or Docker Compose environment section.

## Danish Defaults

Every outbound request includes `gl=dk&hl=da` (geolocation: Denmark,
host language: Danish). These parameters are sourced from
`config/danish_defaults.py` and cannot be overridden per-request — they
are applied automatically to all collection calls.

This ensures results reflect the Danish Google index rather than a
generic international result set.

## Rate Limiting

The collector uses the shared Redis-backed `RateLimiter` from
`workers/rate_limiter.py` when one is injected. The defaults registered
in `ARENA_DEFAULTS` are:

- `google_search`: 100 requests/minute (matches Serper.dev default quota).

Celery tasks automatically retry on `ArenaRateLimitError` with exponential
backoff (up to 3 retries, capped at 5 minutes between attempts).

## Pagination

Both providers return up to 10 organic results per request.
The collector paginates automatically by incrementing:

- Serper.dev: `page` parameter (1-indexed).
- SerpAPI: `start` parameter (0-indexed offset).

Pagination stops when the API returns fewer than 10 results (no more
pages) or the `max_results` limit is reached.

## Actor Collection

Google Search does not natively support actor-based collection.
`collect_by_actors()` converts actor identifiers (expected to be domain
names) to `site:` search queries and delegates to `collect_by_terms()`.

Example:
```
actor_id = "dr.dk" → query = "site:dr.dk"
```

This retrieves all pages indexed from `dr.dk` in the Danish Google index.

## Known Limitations

- **No historical search**: Google Search returns current results only.
  Neither Serper.dev nor SerpAPI supports date-filtering in the standard
  API. Use GDELT or Event Registry for historical news content.
- **No date filter**: The `date_from` / `date_to` parameters accepted by
  the collector interface are ignored for this arena.
- **10 results per query**: Both providers cap results at 10 per page.
  Deep pagination (100+ pages) is expensive and the result quality
  degrades significantly beyond the first few pages.
- **No media/engagement metrics**: Search results do not include
  engagement counts (likes, shares, comments). These fields will be `null`
  in normalized records.
- **Position metadata**: The SERP position (`position` field) is stored
  in `raw_metadata` and not mapped to a dedicated universal schema field.

## Quick Test

```bash
# Test the health endpoint (requires a valid SERPER_MEDIUM_API_KEY)
curl -X GET http://localhost:8000/api/arenas/google-search/health \
     -H "Authorization: Bearer <your_jwt_token>"

# Ad-hoc collection
curl -X POST http://localhost:8000/api/arenas/google-search/collect \
     -H "Authorization: Bearer <your_jwt_token>" \
     -H "Content-Type: application/json" \
     -d '{"terms": ["klimaforandringer", "dansk politik"], "tier": "medium", "max_results": 50}'
```

## Celery Tasks

```python
from issue_observatory.workers.celery_app import celery_app

# Dispatch a collection task
celery_app.send_task(
    "issue_observatory.arenas.google_search.tasks.collect_by_terms",
    kwargs={
        "query_design_id": "<uuid>",
        "collection_run_id": "<uuid>",
        "terms": ["klimaforandringer"],
        "tier": "medium",
    },
)

# Dispatch a health check task
celery_app.send_task("issue_observatory.arenas.google_search.tasks.health_check")
```
