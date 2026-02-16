"""TikTok arena configuration and tier definitions.

TikTok is a free-only arena in Phase 1. The TikTok Research API provides
academic access to video search and user information. Access tokens expire
every 2 hours and are cached in Redis.

Key limits:
- 1,000 requests per day across all endpoints (per application)
- 100 results per request (max_count)
- 30-day maximum date range per query
- 10-day engagement lag for accuracy of view/like/share counts
"""

from __future__ import annotations

from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

TIKTOK_OAUTH_URL: str = "https://open.tiktokapis.com/v2/oauth/token/"
"""OAuth 2.0 token endpoint for client credentials flow."""

TIKTOK_VIDEO_QUERY_URL: str = "https://open.tiktokapis.com/v2/research/video/query/"
"""Video search endpoint. POST with JSON body."""

TIKTOK_USER_INFO_URL: str = "https://open.tiktokapis.com/v2/research/user/info/"
"""User profile information endpoint."""

TIKTOK_WEB_BASE: str = "https://www.tiktok.com"
"""Web URL base for constructing video URLs."""

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------

TIKTOK_MAX_COUNT: int = 100
"""Maximum results per video query request."""

TIKTOK_REGION_CODE: str = "DK"
"""Danish region code applied to all video queries by default."""

TIKTOK_DATE_FORMAT: str = "%Y%m%d"
"""Date format expected by the TikTok Research API (YYYYMMDD)."""

TIKTOK_MAX_DATE_RANGE_DAYS: int = 30
"""Maximum date range per single video query request (API limit)."""

TIKTOK_TOKEN_EXPIRY_SECONDS: int = 7200
"""Access token lifetime in seconds (2 hours)."""

TIKTOK_TOKEN_REFRESH_BUFFER_SECONDS: int = 600
"""Refresh the token this many seconds before expiry (10 minutes)."""

TIKTOK_TOKEN_REDIS_KEY_PREFIX: str = "tiktok:token:"
"""Redis key prefix for cached access tokens: ``tiktok:token:{credential_id}``."""

# ---------------------------------------------------------------------------
# Video fields requested from the API
# ---------------------------------------------------------------------------

TIKTOK_VIDEO_FIELDS: str = (
    "id,video_description,create_time,region_code,share_count,"
    "view_count,like_count,comment_count,music_id,hashtag_names,"
    "username,effect_ids,playlist_id,voice_to_text"
)
"""Comma-separated list of fields to request for each video."""

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

TIKTOK_RATE_LIMIT_MAX_CALLS: int = 1
"""Maximum API calls per rate-limit window (conservative per-second throttle)."""

TIKTOK_RATE_LIMIT_WINDOW_SECONDS: int = 1
"""Rate-limit window duration in seconds."""

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

TIKTOK_TIERS: dict[Tier, TierConfig | None] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=100_000,
        rate_limit_per_minute=10,
        requires_credential=True,
        estimated_credits_per_1k=10,
        # 1,000 requests/day / 100 results/request = 100,000 records/day theoretical max.
        # Conservative rate: ~40 req/hour = 960/day to avoid exhausting daily quota in bursts.
    ),
    Tier.MEDIUM: None,
    Tier.PREMIUM: None,
}
"""Per-tier configuration for the TikTok arena. Only FREE is available in Phase 1."""
