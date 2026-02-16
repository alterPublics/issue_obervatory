"""Threads arena configuration and tier definitions.

The Threads API (free tier) is actor-first: there is no global keyword search.
The ``collect_by_terms()`` method at FREE tier iterates over a curated account
list and filters client-side.

The Meta Content Library (MCL) tier is stubbed — it will be implemented in
Phase 2 alongside the Facebook/Instagram MCL integration once access is
approved.

Base URL: ``https://graph.threads.net/v1.0``
Auth: OAuth 2.0 Bearer tokens (long-lived, 60-day expiry)
Rate limit: 250 API calls per hour per user token
"""

from __future__ import annotations

from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------

THREADS_API_BASE: str = "https://graph.threads.net/v1.0"
"""Threads Graph API base URL."""

THREADS_ME_ENDPOINT: str = f"{THREADS_API_BASE}/me"
"""Authenticated user info endpoint (health check)."""

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

THREADS_RATE_LIMIT: int = 250
"""API calls allowed per hour per authenticated user token."""

THREADS_RATE_WINDOW_SECONDS: int = 3600
"""Sliding window duration for the per-token rate limit (1 hour)."""

# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

TOKEN_REFRESH_DAYS: int = 55
"""Refresh long-lived tokens when fewer than this many days remain before
the 60-day expiry.  Refreshed tokens receive a full new 60-day validity."""

TOKEN_REFRESH_ENDPOINT: str = f"{THREADS_API_BASE}/refresh_access_token"
"""Endpoint for refreshing a long-lived Threads token."""

# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------

THREADS_FIELDS: str = (
    "id,text,timestamp,media_type,is_reply,has_replies,"
    "reply_to_id,username,permalink,views,likes,replies,reposts,quotes"
)
"""Comma-separated list of fields requested on every thread retrieval call.

Note: ``views``, ``likes``, ``replies``, ``reposts``, ``quotes`` are only
returned for the authenticated token owner's own posts.  For other users these
fields are silently absent from the response — normalise to ``None``.
"""

THREADS_PAGE_SIZE: int = 25
"""Number of threads requested per paginated API call."""

# ---------------------------------------------------------------------------
# Danish defaults
# ---------------------------------------------------------------------------

DEFAULT_DANISH_THREADS_ACCOUNTS: list[str] = []
"""Curated list of known Danish Threads account IDs or usernames.

Start empty — actors are added via the actor management UI as they are
discovered.  This list is used as the fallback source for
``collect_by_terms()`` at FREE tier (client-side keyword filtering over
known accounts).
"""

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

THREADS_TIERS: dict[Tier, TierConfig | None] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=10_000,
        rate_limit_per_minute=4,  # 250/hour ≈ 4/minute
        requires_credential=True,
        estimated_credits_per_1k=0,
    ),
    Tier.MEDIUM: None,   # MCL stub — Phase 2
    Tier.PREMIUM: None,
}
"""Per-tier configuration for the Threads arena.

FREE uses the official Threads API with OAuth 2.0 tokens.
MEDIUM (MCL) is not yet implemented — raises ``NotImplementedError``.
PREMIUM is not available.
"""
