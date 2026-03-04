"""Facebook arena configuration constants and tier definitions.

Defines Bright Data Web Scraper API endpoints, polling parameters, cost constants,
rate limit settings, dataset ID mappings, and tier configuration objects.

No secrets are stored here. Credentials are managed exclusively through
:class:`~issue_observatory.core.credential_pool.CredentialPool`.

Credential locations:
- MEDIUM: ``CredentialPool.acquire(platform="brightdata_facebook", tier="medium")``.
  JSONB payload: ``{"api_token": "bd-fb-xxx", "zone": "facebook_zone"}``.
- PREMIUM: ``CredentialPool.acquire(platform="meta_content_library", tier="premium")``.
  JSONB payload: ``{"access_token": "mcl-token-xxx", "app_id": "...", "app_secret": "..."}``.
  NOTE: MCL access is not yet approved — both PREMIUM methods raise NotImplementedError.

Dataset routing (Web Scraper API):
- Facebook page/profile URLs -> Posts scraper (``gd_lkaxegm826bjpoo9m5``)
- Facebook group URLs (containing ``/groups/``) -> Groups scraper (``gd_lz11l67o2cb3r0lkj3``)
- Reels-specific collection -> Reels scraper (``gd_lyclm3ey2q6rww027t``)

Date format: Web Scraper API requires ``MM-DD-YYYY`` (not ISO 8601).
"""

from __future__ import annotations

from issue_observatory.arenas.base import Tier
from issue_observatory.config.tiers import TierConfig

# ---------------------------------------------------------------------------
# Bright Data Web Scraper API — base URL and endpoints
# ---------------------------------------------------------------------------

BRIGHTDATA_API_BASE: str = "https://api.brightdata.com/datasets/v3"
"""Base URL for the Bright Data Datasets v3 API."""

BRIGHTDATA_PROGRESS_URL: str = f"{BRIGHTDATA_API_BASE}/progress/{{snapshot_id}}"
"""URL template for polling snapshot delivery progress. Format with ``snapshot_id``."""

BRIGHTDATA_SNAPSHOT_URL: str = f"{BRIGHTDATA_API_BASE}/snapshot/{{snapshot_id}}?format=json"
"""URL template for downloading a completed snapshot. Format with ``snapshot_id``."""

# ---------------------------------------------------------------------------
# Web Scraper API — dataset IDs by content type
# ---------------------------------------------------------------------------

FACEBOOK_DATASET_ID_POSTS: str = "gd_lkaxegm826bjpoo9m5"
"""Web Scraper API dataset ID for Facebook Posts (page/profile URL input)."""

FACEBOOK_DATASET_ID_GROUPS: str = "gd_lz11l67o2cb3r0lkj3"
"""Web Scraper API dataset ID for Facebook Groups (group URL input)."""

FACEBOOK_DATASET_ID_REELS: str = "gd_lyclm3ey2q6rww027t"
"""Web Scraper API dataset ID for Facebook Reels (profile URL input)."""

# ---------------------------------------------------------------------------
# Trigger URL builder helper
# ---------------------------------------------------------------------------


def build_trigger_url(dataset_id: str) -> str:
    """Build the full trigger URL for a given Facebook Web Scraper dataset ID.

    The Web Scraper API does not use ``type=discover_new`` or ``&notify=none``
    parameters that were present in the legacy Datasets product trigger URL.

    Args:
        dataset_id: One of the ``FACEBOOK_DATASET_ID_*`` constants.

    Returns:
        Full trigger URL string ready for HTTP POST.
    """
    return f"{BRIGHTDATA_API_BASE}/trigger?dataset_id={dataset_id}&include_errors=true"


# ---------------------------------------------------------------------------
# Polling parameters
# ---------------------------------------------------------------------------

BRIGHTDATA_POLL_INTERVAL: int = 30
"""Seconds to wait between dataset delivery status checks."""

BRIGHTDATA_MAX_POLL_ATTEMPTS: int = 40
"""Maximum polling attempts before aborting (40 * 30s = 20 minutes)."""

# ---------------------------------------------------------------------------
# Danish locale targeting
# ---------------------------------------------------------------------------

BRIGHTDATA_FACEBOOK_COUNTRY: str = "DK"
"""Country code for Bright Data geo-targeting. Restricts proxy location to Denmark."""

# ---------------------------------------------------------------------------
# Date format helper
# ---------------------------------------------------------------------------


def to_brightdata_date(value: object) -> str | None:
    """Convert a datetime or string to the Web Scraper API date format ``MM-DD-YYYY``.

    The Bright Data Web Scraper API requires ``MM-DD-YYYY`` format, not ISO 8601.

    Args:
        value: :class:`datetime.datetime` object, ISO 8601 string, or ``None``.

    Returns:
        Date string in ``MM-DD-YYYY`` format, or ``None`` if *value* is ``None``
        or cannot be parsed.
    """
    from datetime import datetime  # noqa: PLC0415

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%m-%d-%Y")
    if isinstance(value, str) and len(value) >= 10:
        # Try ISO 8601 parse (YYYY-MM-DD prefix).
        try:
            dt = datetime.fromisoformat(value[:10])
            return dt.strftime("%m-%d-%Y")
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Cost constants (Web Scraper API pricing)
# ---------------------------------------------------------------------------

FACEBOOK_COST_PER_1K: float = 1.50
"""USD cost per 1,000 records via Bright Data Web Scraper API (pay-as-you-go)."""

FACEBOOK_COST_PER_RECORD: float = FACEBOOK_COST_PER_1K / 1_000
"""USD cost per individual record (0.0015 USD)."""

# ---------------------------------------------------------------------------
# Rate limit parameters
# ---------------------------------------------------------------------------

BRIGHTDATA_RATE_LIMIT_MAX_CALLS: int = 2
"""Maximum Bright Data API trigger calls per window (courtesy throttle)."""

BRIGHTDATA_RATE_LIMIT_WINDOW_SECONDS: int = 1
"""Sliding window duration for the Bright Data courtesy rate limit."""

# ---------------------------------------------------------------------------
# Tier configuration objects
# ---------------------------------------------------------------------------

FACEBOOK_TIERS: dict[Tier, TierConfig] = {
    Tier.MEDIUM: TierConfig(
        tier=Tier.MEDIUM,
        max_results_per_run=100_000,
        rate_limit_per_minute=BRIGHTDATA_RATE_LIMIT_MAX_CALLS * 60,
        requires_credential=True,
        estimated_credits_per_1k=2,  # ~$0.0015/record = ~$1.50/1K records
    ),
    Tier.PREMIUM: TierConfig(
        tier=Tier.PREMIUM,
        max_results_per_run=500_000,  # MCL weekly cap
        rate_limit_per_minute=60,
        requires_credential=True,
        estimated_credits_per_1k=5,
    ),
}
"""Tier configuration objects for the Facebook arena."""
