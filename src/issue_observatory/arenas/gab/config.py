"""Gab arena configuration and tier definitions.

Gab is a free-only arena. The API is Mastodon-compatible at gab.com.
OAuth 2.0 Bearer token required — credentials stored in CredentialPool as
``platform="gab"``, ``tier="free"``.

Rate limits: ~300 req/5 min (Mastodon default). Set conservative baseline
of 200 req/5 min = 40 req/min to leave headroom.

Note on search: Mastodon's full-text search may be restricted on Gab.
If ``GET /api/v2/search`` returns HTTP 422, fall back to hashtag timeline
for hashtag-prefixed terms.
"""

from __future__ import annotations

from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

GAB_API_BASE: str = "https://gab.com/api"
"""Gab Mastodon-compatible API base URL."""

GAB_SEARCH_ENDPOINT: str = f"{GAB_API_BASE}/v2/search"
"""Full-text search endpoint (type=statuses)."""

GAB_ACCOUNT_STATUSES_ENDPOINT: str = f"{GAB_API_BASE}/v1/accounts/{{account_id}}/statuses"
"""Account statuses endpoint — fill in ``account_id`` before use."""

GAB_ACCOUNT_LOOKUP_ENDPOINT: str = f"{GAB_API_BASE}/v1/accounts/lookup"
"""Look up account by username."""

GAB_HASHTAG_TIMELINE_ENDPOINT: str = f"{GAB_API_BASE}/v1/timelines/tag/{{hashtag}}"
"""Hashtag timeline endpoint — fill in ``hashtag`` before use."""

GAB_PUBLIC_TIMELINE_ENDPOINT: str = f"{GAB_API_BASE}/v1/timelines/public"
"""Public timeline endpoint (used for health check)."""

GAB_INSTANCE_ENDPOINT: str = f"{GAB_API_BASE}/v1/instance"
"""Instance information endpoint (used as health check fallback)."""

GAB_OAUTH_TOKEN_ENDPOINT: str = "https://gab.com/oauth/token"
"""OAuth 2.0 token endpoint."""

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------

GAB_MAX_RESULTS_PER_PAGE: int = 40
"""Maximum results per request (Mastodon API spec maximum)."""

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

GAB_RATE_LIMIT_MAX_CALLS: int = 60
"""Maximum API calls per rate-limit window (conservative: 60/min = 300/5min)."""

GAB_RATE_LIMIT_WINDOW_SECONDS: int = 60
"""Rate-limit window duration in seconds."""

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

GAB_TIERS: dict[Tier, TierConfig | None] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=10_000,
        rate_limit_per_minute=40,
        requires_credential=True,
        estimated_credits_per_1k=0,
        # ~300 req/5 min Mastodon default; conservative baseline 200 req/5 min.
        # Expected volume is very low (Danish-relevant content is sparse on Gab).
    ),
    Tier.MEDIUM: None,
    Tier.PREMIUM: None,
}
"""Per-tier configuration for the Gab arena. Only FREE is available."""
