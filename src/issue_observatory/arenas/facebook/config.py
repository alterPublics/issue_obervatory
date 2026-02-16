"""Facebook arena configuration constants and tier definitions.

Defines Bright Data API endpoints, polling parameters, cost constants,
rate limit settings, and tier configuration objects.

No secrets are stored here. Credentials are managed exclusively through
:class:`~issue_observatory.core.credential_pool.CredentialPool`.

Credential locations:
- MEDIUM: ``CredentialPool.acquire(platform="brightdata_facebook", tier="medium")``.
  JSONB payload: ``{"api_token": "bd-fb-xxx", "zone": "facebook_zone"}``.
- PREMIUM: ``CredentialPool.acquire(platform="meta_content_library", tier="premium")``.
  JSONB payload: ``{"access_token": "mcl-token-xxx", "app_id": "...", "app_secret": "..."}``.
  NOTE: MCL access is not yet approved — both PREMIUM methods raise NotImplementedError.
"""

from __future__ import annotations

from issue_observatory.arenas.base import Tier
from issue_observatory.config.tiers import TierConfig

# ---------------------------------------------------------------------------
# Bright Data API endpoints and parameters
# ---------------------------------------------------------------------------

BRIGHTDATA_API_BASE: str = "https://api.brightdata.com/datasets/v3"
"""Base URL for the Bright Data Datasets v3 API."""

BRIGHTDATA_FACEBOOK_DATASET_ID: str = "gd_l95fol7l1ru6rlo116"
"""Bright Data dataset ID for the Facebook public posts dataset."""

BRIGHTDATA_TRIGGER_URL: str = (
    f"{BRIGHTDATA_API_BASE}/trigger"
    f"?dataset_id={BRIGHTDATA_FACEBOOK_DATASET_ID}"
    "&type=discover_new"
    "&notify=none"
)
"""Full trigger URL for initiating a Bright Data Facebook dataset request."""

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

BRIGHTDATA_FACEBOOK_COUNTRY: str = "DK"
"""Country code for Bright Data geo-targeting. Restricts proxy location to Denmark."""

# ---------------------------------------------------------------------------
# Cost constants
# ---------------------------------------------------------------------------

FACEBOOK_COST_PER_100K: float = 250.0
"""USD cost per 100,000 records via Bright Data Facebook Datasets."""

FACEBOOK_COST_PER_RECORD: float = FACEBOOK_COST_PER_100K / 100_000
"""USD cost per individual record (0.0025 USD)."""

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
        estimated_credits_per_1k=3,  # ~$0.0025/record = ~$2.50/1K records
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
