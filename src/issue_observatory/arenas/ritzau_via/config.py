"""Via Ritzau arena configuration and tier definitions.

Via Ritzau is a free-only arena. No authentication is required.
The API is fully public and unauthenticated.

Coverage: Danish press releases from government, companies, NGOs, police, etc.
Rate limit: No documented limit; use courtesy throttle of 10 req/min.
Pagination: Offset-based (limit + offset parameters).
"""

from __future__ import annotations

from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

RITZAU_API_BASE: str = "https://via.ritzau.dk/json/v2"
"""Via Ritzau REST API v2 base URL."""

RITZAU_RELEASES_ENDPOINT: str = f"{RITZAU_API_BASE}/releases"
"""List and search press releases."""

RITZAU_PUBLISHERS_ENDPOINT: str = f"{RITZAU_API_BASE}/publishers"
"""List all available publishers."""

RITZAU_CHANNELS_ENDPOINT: str = f"{RITZAU_API_BASE}/channels"
"""List all available channels/categories."""

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------

RITZAU_DEFAULT_LANGUAGE: str = "da"
"""Default language filter for Danish press releases."""

RITZAU_PAGE_SIZE: int = 50
"""Number of releases to request per page."""

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

RITZAU_RATE_LIMIT_MAX_CALLS: int = 2
"""Maximum requests per rate-limit window (courtesy throttle)."""

RITZAU_RATE_LIMIT_WINDOW_SECONDS: int = 1
"""Rate-limit window duration in seconds."""

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

RITZAU_TIERS: dict[Tier, TierConfig | None] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=10_000,
        rate_limit_per_minute=10,
        requires_credential=False,
        estimated_credits_per_1k=0,
        # No authentication, no API cost, no documented rate limits.
        # Use a courtesy rate of 10 requests/minute.
    ),
    Tier.MEDIUM: None,
    Tier.PREMIUM: None,
}
"""Per-tier configuration for the Via Ritzau arena. Only FREE exists."""
