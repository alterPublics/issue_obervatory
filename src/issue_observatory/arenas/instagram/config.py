"""Instagram arena configuration constants and tier definitions.

Defines Bright Data Web Scraper API endpoints, cost constants, rate limit settings,
dataset ID mappings, and tier configuration objects.

No secrets are stored here. Credentials are managed exclusively through
:class:`~issue_observatory.core.credential_pool.CredentialPool`.

Credential locations:
- MEDIUM: ``CredentialPool.acquire(platform="brightdata_instagram", tier="medium")``.
  JSONB payload: ``{"api_token": "bd-ig-xxx", "zone": "instagram_zone"}``.
- PREMIUM: ``CredentialPool.acquire(platform="meta_content_library", tier="premium")``.
  JSONB payload: ``{"access_token": "mcl-token-xxx", "app_id": "...", "app_secret": "..."}``.
  NOTE: MCL access is not yet approved — both PREMIUM methods raise NotImplementedError.

Dataset routing (Web Scraper API):
- Instagram profile URL -> Reels scraper (``gd_lyclm20il4r5helnj``) — covers all content types.
  This is the primary scraper for profile-based collection (posts and reels).
- Instagram individual post URL -> Posts scraper (``gd_lk5ns7kz21pck8jpis``).
  Used for targeted scraping of specific post URLs.

Date format: Web Scraper API requires ``MM-DD-YYYY`` (not ISO 8601).

Danish targeting note:
  Instagram has no native language field. Danish content is identified by:
  1. Targeting known Danish accounts via ``collect_by_actors()`` (primary method).
  2. Client-side language detection on caption text applied downstream.
  Keyword/hashtag search is not supported by the Web Scraper API.
"""

from __future__ import annotations

from issue_observatory.arenas.base import Tier
from issue_observatory.config.tiers import TierConfig

# ---------------------------------------------------------------------------
# Bright Data Web Scraper API — base URL and endpoints
# ---------------------------------------------------------------------------

BRIGHTDATA_API_BASE: str = "https://api.brightdata.com/datasets/v3"
"""Base URL for the Bright Data Datasets v3 API (shared with Facebook)."""

BRIGHTDATA_PROGRESS_URL: str = f"{BRIGHTDATA_API_BASE}/progress/{{snapshot_id}}"
"""URL template for polling snapshot delivery progress. Format with ``snapshot_id``."""

BRIGHTDATA_SNAPSHOT_URL: str = f"{BRIGHTDATA_API_BASE}/snapshot/{{snapshot_id}}?format=json"
"""URL template for downloading a completed snapshot. Format with ``snapshot_id``."""

# ---------------------------------------------------------------------------
# Web Scraper API — dataset IDs by content type
# ---------------------------------------------------------------------------

INSTAGRAM_DATASET_ID_REELS: str = "gd_lyclm20il4r5helnj"
"""Web Scraper API dataset ID for Instagram Reels (profile URL input).

This is the primary scraper for actor-based collection. Accepts a profile URL
and returns all recent content (posts and reels). Preferred over the Posts
scraper for profile-level collection because it covers all content types.
"""

INSTAGRAM_DATASET_ID_POSTS: str = "gd_lk5ns7kz21pck8jpis"
"""Web Scraper API dataset ID for Instagram Posts (individual post URL input).

Used for targeted scraping of specific post URLs. Not suitable for
profile-level collection — use ``INSTAGRAM_DATASET_ID_REELS`` for profiles.
"""

# ---------------------------------------------------------------------------
# Trigger URL builder helper
# ---------------------------------------------------------------------------


def build_trigger_url(dataset_id: str) -> str:
    """Build the full trigger URL for a given Instagram Web Scraper dataset ID.

    The Web Scraper API does not use ``type=discover_new`` or ``&notify=none``
    parameters that were present in the legacy Datasets product trigger URL.

    Args:
        dataset_id: One of the ``INSTAGRAM_DATASET_ID_*`` constants.

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
        try:
            dt = datetime.fromisoformat(value[:10])
            return dt.strftime("%m-%d-%Y")
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Cost constants (Web Scraper API pricing)
# ---------------------------------------------------------------------------

INSTAGRAM_COST_PER_1K: float = 1.50
"""USD cost per 1,000 records via Bright Data Web Scraper API (pay-as-you-go)."""

INSTAGRAM_COST_PER_RECORD: float = INSTAGRAM_COST_PER_1K / 1_000
"""USD cost per individual record (0.0015 USD)."""

# ---------------------------------------------------------------------------
# Rate limit parameters
# ---------------------------------------------------------------------------

BRIGHTDATA_RATE_LIMIT_MAX_CALLS: int = 2
"""Maximum Bright Data API trigger calls per window (courtesy throttle)."""

BRIGHTDATA_RATE_LIMIT_WINDOW_SECONDS: int = 1
"""Sliding window duration for the Bright Data courtesy rate limit."""

# ---------------------------------------------------------------------------
# Media type detection constants
# ---------------------------------------------------------------------------

INSTAGRAM_REEL_PRODUCT_TYPES: frozenset[str] = frozenset(
    {"clips", "reel", "igtv"}
)
"""Bright Data ``product_type`` values that indicate a Reel or video content."""

INSTAGRAM_REEL_MEDIA_TYPES: frozenset[str] = frozenset({"2"})
"""Bright Data ``media_type`` numeric values for video/Reel content."""

# ---------------------------------------------------------------------------
# Tier configuration objects
# ---------------------------------------------------------------------------

INSTAGRAM_TIERS: dict[Tier, TierConfig] = {
    Tier.MEDIUM: TierConfig(
        tier=Tier.MEDIUM,
        max_results_per_run=50_000,
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
"""Tier configuration objects for the Instagram arena."""
