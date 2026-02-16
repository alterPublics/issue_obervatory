"""Google Autocomplete arena configuration and tier definitions.

Defines API endpoints, tier configurations, and Danish locale parameters for
the Google Autocomplete arena.  Three tiers are supported:

- **FREE** — Undocumented Google endpoint (no auth, unreliable rate limits).
- **MEDIUM** — Serper.dev autocomplete endpoint.  Credentials shared with the
  Google Search arena (``platform="serper"``).
- **PREMIUM** — SerpAPI autocomplete endpoint.  Credentials shared with the
  Google Search arena (``platform="serpapi"``).

Danish locale parameters (:data:`DANISH_PARAMS`) are sourced from
:mod:`issue_observatory.config.danish_defaults` so there is a single source
of truth across all Google arenas.
"""

from __future__ import annotations

from issue_observatory.config.danish_defaults import DANISH_GOOGLE_PARAMS
from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

FREE_AUTOCOMPLETE_URL: str = "https://suggestqueries.google.com/complete/search"
"""Undocumented Google suggest endpoint (FREE tier).

Returns a JSON array: ``["query", ["suggestion1", "suggestion2", ...]]``
when ``client=firefox`` is passed.
"""

SERPER_AUTOCOMPLETE_URL: str = "https://google.serper.dev/autocomplete"
"""Serper.dev autocomplete endpoint (MEDIUM tier, POST with JSON body)."""

SERPAPI_AUTOCOMPLETE_URL: str = "https://serpapi.com/search"
"""SerpAPI search endpoint with ``engine=google_autocomplete`` (PREMIUM tier)."""

# ---------------------------------------------------------------------------
# Danish locale parameters
# ---------------------------------------------------------------------------

DANISH_PARAMS: dict[str, str] = DANISH_GOOGLE_PARAMS
"""Locale parameters applied to all Google Autocomplete requests.

Equivalent to ``{"gl": "dk", "hl": "da"}``.
"""

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

GOOGLE_AUTOCOMPLETE_TIERS: dict[Tier, TierConfig | None] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=10_000,
        rate_limit_per_minute=60,
        requires_credential=False,
        estimated_credits_per_1k=0,
        # ~1 req/sec empirical safe limit; Google may block higher rates.
        # No published SLA.
    ),
    Tier.MEDIUM: TierConfig(
        tier=Tier.MEDIUM,
        max_results_per_run=50_000,
        rate_limit_per_minute=300,
        requires_credential=True,
        estimated_credits_per_1k=1,
        # 1 credit = 1 autocomplete query.  Serper credits are shared with
        # the Google Search arena (same credential pool key).
    ),
    Tier.PREMIUM: TierConfig(
        tier=Tier.PREMIUM,
        max_results_per_run=100_000,
        rate_limit_per_minute=300,
        requires_credential=True,
        estimated_credits_per_1k=3,
        # SerpAPI caches identical queries for 1 hour — repeated queries
        # within the cache window are free (do not count against quota).
    ),
}
"""Per-tier configuration for the Google Autocomplete arena.

All three tiers are available.  FREE tier uses the undocumented endpoint
and should be used for low-volume exploratory work only.
"""
