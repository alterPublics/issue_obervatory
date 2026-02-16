"""Instagram arena configuration constants and tier definitions.

Defines Bright Data API endpoints, cost constants, rate limit settings,
and tier configuration objects.

No secrets are stored here. Credentials are managed exclusively through
:class:`~issue_observatory.core.credential_pool.CredentialPool`.

Credential locations:
- MEDIUM: ``CredentialPool.acquire(platform="brightdata_instagram", tier="medium")``.
  JSONB payload: ``{"api_token": "bd-ig-xxx", "zone": "instagram_zone"}``.
- PREMIUM: ``CredentialPool.acquire(platform="meta_content_library", tier="premium")``.
  JSONB payload: ``{"access_token": "mcl-token-xxx", "app_id": "...", "app_secret": "..."}``.
  NOTE: MCL access is not yet approved — both PREMIUM methods raise NotImplementedError.

Danish targeting note:
  Instagram has no native language field. Danish content is identified by:
  1. Targeting known Danish accounts (collect_by_actors).
  2. Searching Danish-language hashtags (collect_by_terms maps terms to hashtags).
  3. Client-side language detection on caption text (applied if ``lang`` field is present).
"""

from __future__ import annotations

from issue_observatory.arenas.base import Tier
from issue_observatory.config.tiers import TierConfig

# ---------------------------------------------------------------------------
# Bright Data API endpoints
# ---------------------------------------------------------------------------

BRIGHTDATA_INSTAGRAM_POSTS_URL: str = (
    "https://api.brightdata.com/datasets/v3/trigger"
    "?dataset_id=gd_lyclm20il4r5helnj"
    "&type=discover_new"
    "&notify=none"
)
"""Full trigger URL for initiating a Bright Data Instagram posts dataset request."""

BRIGHTDATA_INSTAGRAM_DATASET_ID: str = "gd_lyclm20il4r5helnj"
"""Bright Data dataset ID for the Instagram posts scraper."""

BRIGHTDATA_API_BASE: str = "https://api.brightdata.com/datasets/v3"
"""Base URL for the Bright Data Datasets v3 API (shared with Facebook)."""

BRIGHTDATA_PROGRESS_URL: str = f"{BRIGHTDATA_API_BASE}/progress/{{snapshot_id}}"
"""URL template for polling snapshot delivery progress. Format with ``snapshot_id``."""

BRIGHTDATA_SNAPSHOT_URL: str = f"{BRIGHTDATA_API_BASE}/snapshot/{{snapshot_id}}?format=json"
"""URL template for downloading a completed snapshot. Format with ``snapshot_id``."""

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

# Instagram has no native language or country filter.
# Danish hashtags are used as the primary discovery mechanism.
DANISH_INSTAGRAM_HASHTAGS: list[str] = [
    "dkpol",
    "danmark",
    "kobenhavn",
    "dkmedier",
    "danmarksnatur",
    "dkkultur",
    "danskepolitikere",
]
"""Default Danish hashtags prepended to search terms for Instagram discovery.

Used in ``collect_by_terms()`` to target Danish-language content when the
platform provides no native language filter. Terms are converted to hashtags
by stripping spaces and prepending ``#`` if not already present.
"""

# ---------------------------------------------------------------------------
# Cost constants
# ---------------------------------------------------------------------------

INSTAGRAM_COST_PER_1K: float = 1.50
"""USD cost per 1,000 records via Bright Data Instagram Scraper API."""

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
