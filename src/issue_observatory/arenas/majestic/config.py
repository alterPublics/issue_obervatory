"""Configuration constants for the Majestic backlink intelligence arena.

Majestic is a premium-only arena providing link graph data (Trust Flow,
Citation Flow, backlink counts) for web domains and URLs.  It is reactive
rather than polling: collection is triggered by domain URLs discovered from
other arenas, not by periodic keyword searches.

Documentation: https://developer-support.majestic.com/api/documentation
"""

from __future__ import annotations

from issue_observatory.arenas.base import Tier
from issue_observatory.config.tiers import TierConfig

# ---------------------------------------------------------------------------
# API base URL
# ---------------------------------------------------------------------------

MAJESTIC_API_BASE = "https://api.majestic.com/api/json"
"""JSON endpoint for all Majestic API commands."""

# ---------------------------------------------------------------------------
# Subscription / budget constants
# ---------------------------------------------------------------------------

MAJESTIC_ANALYSIS_UNITS_PER_MONTH = 100_000_000
"""Monthly analysis unit budget on the Full API plan."""

MAJESTIC_COST_PER_MONTH = 399.99
"""Monthly subscription cost (USD) for the Full API plan as of early 2026."""

# ---------------------------------------------------------------------------
# Supported API commands
# ---------------------------------------------------------------------------

CMD_GET_INDEX_ITEM_INFO = "GetIndexItemInfo"
"""Retrieve Trust Flow, Citation Flow, and link counts for one or more items."""

CMD_GET_BACKLINK_DATA = "GetBackLinkData"
"""Retrieve individual backlinks pointing to a URL or domain."""

CMD_GET_REF_DOMAINS = "GetRefDomains"
"""Retrieve referring domains for a URL or domain."""

CMD_GET_NEW_LOST_BACKLINKS = "GetNewLostBackLinks"
"""Retrieve backlinks gained or lost within a time period."""

# ---------------------------------------------------------------------------
# Default request parameters
# ---------------------------------------------------------------------------

MAJESTIC_DEFAULT_DATASOURCE = "fresh"
"""Use the Fresh Index (daily updates, last 120 days) by default.
Switch to 'historic' for longitudinal studies."""

MAJESTIC_MAX_BACKLINKS_PER_DOMAIN = 1000
"""Cap for initial backlink collection per domain.
Use Mode=1 (one per referring domain) to maximise coverage within budget."""

MAJESTIC_BACKLINK_MODE_ONE_PER_DOMAIN = 1
"""GetBackLinkData Mode=1: return at most one backlink per referring domain.
More efficient for initial surveys than Mode=0 (all backlinks)."""

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

MAJESTIC_MAX_CALLS_PER_SECOND = 1
"""Conservative rate: Majestic recommends ~1 req/sec for batch analysis."""

MAJESTIC_RATE_LIMIT_WINDOW_SECONDS = 1
"""Sliding window size in seconds for the rate limiter."""

MAJESTIC_RATE_LIMIT_TIMEOUT = 30.0
"""Maximum seconds to wait for a rate-limit slot before giving up."""

MAJESTIC_RATE_LIMIT_KEY_TEMPLATE = "ratelimit:web:majestic:{credential_id}"
"""Redis key template for the Majestic rate limiter."""

# ---------------------------------------------------------------------------
# Analysis unit credit mapping
# ---------------------------------------------------------------------------

MAJESTIC_UNITS_PER_CREDIT = 1_000
"""1 credit = 1,000 analysis units.
A GetBackLinkData call returning 1,000 rows costs ~1 credit."""

# ---------------------------------------------------------------------------
# Health check domain
# ---------------------------------------------------------------------------

MAJESTIC_HEALTH_CHECK_DOMAIN = "dr.dk"
"""Reliable Danish domain used for health checks (GetIndexItemInfo)."""

MAJESTIC_HEALTH_MIN_TRUST_FLOW = 1
"""Minimum Trust Flow required for a healthy health-check response.
dr.dk should consistently return Trust Flow > 40."""

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

MAJESTIC_TIERS: dict[Tier, TierConfig] = {
    Tier.PREMIUM: TierConfig(
        tier=Tier.PREMIUM,
        max_results_per_run=MAJESTIC_MAX_BACKLINKS_PER_DOMAIN,
        rate_limit_per_minute=MAJESTIC_MAX_CALLS_PER_SECOND * 60,
        requires_credential=True,
        estimated_credits_per_1k=1,
    ),
}
"""Tier configuration map.  Only PREMIUM is supported."""
