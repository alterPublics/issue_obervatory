"""Tier configurations and constants for the URL Scraper arena.

The URL Scraper is a self-hosted web content extraction service.  It fetches
live web pages from a researcher-provided list of URLs, extracts article text
via ``trafilatura``, and stores the results as Universal Content Records.

No external API is used, so both tiers are free in terms of external cost.
The tier difference is in throughput (max URLs per run) and whether
Playwright is available for JS-heavy pages.
"""

from __future__ import annotations

from issue_observatory.arenas.base import Tier
from issue_observatory.config.tiers import TierConfig

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

URL_SCRAPER_TIERS: dict[Tier, TierConfig] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=100,
        rate_limit_per_minute=60,  # 1 req/sec per domain
        requires_credential=False,
        estimated_credits_per_1k=0,
    ),
    Tier.MEDIUM: TierConfig(
        tier=Tier.MEDIUM,
        max_results_per_run=500,
        rate_limit_per_minute=120,  # 2 req/sec per domain
        requires_credential=False,
        estimated_credits_per_1k=0,
    ),
}
"""Tier configuration for the URL Scraper arena.

Both tiers are free in terms of external API cost.  MEDIUM unlocks
Playwright fallback for JS-rendered pages and increases the per-run URL cap.
"""

# ---------------------------------------------------------------------------
# Per-domain politeness delays
# ---------------------------------------------------------------------------

DOMAIN_DELAY_FREE: float = 1.0
"""Seconds to wait between consecutive requests to the same domain (FREE tier)."""

DOMAIN_DELAY_MEDIUM: float = 0.5
"""Seconds to wait between consecutive requests to the same domain (MEDIUM tier)."""

# ---------------------------------------------------------------------------
# HTTP client configuration
# ---------------------------------------------------------------------------

#: Maximum concurrent requests per domain (both tiers).
MAX_DOMAIN_CONCURRENCY: int = 1

#: Connection pool size for the shared httpx.AsyncClient.
CONNECTION_POOL_LIMITS_FREE: dict[str, int] = {
    "max_connections": 20,
    "max_keepalive_connections": 10,
}
CONNECTION_POOL_LIMITS_MEDIUM: dict[str, int] = {
    "max_connections": 50,
    "max_keepalive_connections": 25,
}

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

HEALTH_CHECK_URL: str = "https://www.dr.dk/"
"""Stable Danish website used to validate the full fetch-and-extract pipeline."""

# ---------------------------------------------------------------------------
# URL normalization — tracking parameters stripped before deduplication
# ---------------------------------------------------------------------------

TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
        "fbclid",
        "gclid",
        "ref",
        "_ga",
    }
)
"""Query parameters removed during URL normalization to prevent fetching
the same page multiple times due to differing tracking suffixes."""
