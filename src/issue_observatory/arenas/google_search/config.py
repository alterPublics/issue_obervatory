"""Google Search arena configuration and tier definitions.

Defines API endpoints, tier configurations, and Danish locale parameters for
the Google Search arena.  Two providers are supported:

- **MEDIUM tier** — Serper.dev (``https://google.serper.dev/search``).
  POST-based JSON API, $0.30 per 1,000 queries, 100 req/min default.
- **PREMIUM tier** — SerpAPI (``https://serpapi.com/search``).
  Higher rate limits and additional result metadata; higher per-query cost.

FREE tier is explicitly unavailable — Google has no free programmatic search
API.  Collectors receiving ``Tier.FREE`` must log a warning and return ``[]``.

Credential environment variables (Phase 0 env-var convention):
- ``SERPER_MEDIUM_API_KEY``   — Serper.dev API key for MEDIUM tier.
- ``SERPAPI_PREMIUM_API_KEY`` — SerpAPI API key for PREMIUM tier.

Danish locale parameters (:data:`DANISH_PARAMS`) are sourced from
:mod:`issue_observatory.config.danish_defaults` and must be included on every
outbound request so results reflect the Danish media landscape.
"""

from __future__ import annotations

from issue_observatory.config.danish_defaults import DANISH_GOOGLE_PARAMS
from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

SERPER_API_URL: str = "https://google.serper.dev/search"
"""Serper.dev Google Search endpoint (POST, JSON body)."""

SERPAPI_URL: str = "https://serpapi.com/search"
"""SerpAPI Google Search endpoint (GET, query parameters)."""

# ---------------------------------------------------------------------------
# Danish locale parameters
# ---------------------------------------------------------------------------

DANISH_PARAMS: dict[str, str] = DANISH_GOOGLE_PARAMS
"""Locale parameters applied to all Google Search requests.

Equivalent to ``{"gl": "dk", "hl": "da"}``.  Sourced from
:data:`issue_observatory.config.danish_defaults.DANISH_GOOGLE_PARAMS` so that
there is a single source of truth for Danish defaults across all Google arenas.
"""

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

MAX_RESULTS_PER_PAGE: int = 10
"""Number of results returned per Serper.dev page.

Serper.dev returns up to 10 organic results per request when ``num=10`` is
set in the request body.  Pagination is achieved by incrementing the ``page``
parameter (1-indexed).
"""

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

GOOGLE_SEARCH_TIERS: dict[Tier, TierConfig | None] = {
    Tier.FREE: None,
    # FREE is not available — Google has no free programmatic search API.
    # Returning None signals to the collector that this tier must be skipped.
    Tier.MEDIUM: TierConfig(
        tier=Tier.MEDIUM,
        max_results_per_run=10_000,
        rate_limit_per_minute=100,
        requires_credential=True,
        estimated_credits_per_1k=1,
        # 1 credit = 1 Serper.dev query (each query retrieves one page of 10
        # results).  A run collecting 10,000 results needs 1,000 queries =
        # 1,000 credits.
    ),
    Tier.PREMIUM: TierConfig(
        tier=Tier.PREMIUM,
        max_results_per_run=100_000,
        rate_limit_per_minute=200,
        requires_credential=True,
        estimated_credits_per_1k=3,
        # SerpAPI charges more per query; estimated at 3 credits / 1K results
        # to approximate the higher per-query cost relative to Serper.dev.
    ),
}
"""Per-tier configuration for the Google Search arena.

``Tier.FREE`` maps to ``None`` to indicate unavailability.  Collectors should
check for ``None`` and return an empty list with a warning log.
"""
