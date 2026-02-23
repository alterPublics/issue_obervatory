"""Bluesky arena configuration and tier definitions.

Bluesky is a free-only arena — the AT Protocol API provides all
required functionality at no cost.  No medium or premium tiers exist.

Authentication is required via handle + app password. The collector
obtains a session token via ``com.atproto.server.createSession`` and
uses it for all subsequent requests.

The API base URL is ``https://bsky.social/xrpc``.

Key endpoints:
- ``app.bsky.feed.searchPosts`` — full-text post search with ``lang`` filter (requires auth).
- ``app.bsky.feed.getAuthorFeed`` — paginated author post history (requires auth).
- ``app.bsky.actor.searchActors`` — user search by handle/display name (requires auth).
- ``com.atproto.server.createSession`` — authentication endpoint.

Danish content is collected via the ``lang=da`` query parameter.
"""

from __future__ import annotations

from issue_observatory.config.danish_defaults import BLUESKY_LANG_FILTER
from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# API base URL and endpoints
# ---------------------------------------------------------------------------

BSKY_API_BASE: str = "https://bsky.social/xrpc"
"""AT Protocol API base URL (requires authentication)."""

BSKY_SEARCH_POSTS_ENDPOINT: str = f"{BSKY_API_BASE}/app.bsky.feed.searchPosts"
"""Full-text post search endpoint."""

BSKY_AUTHOR_FEED_ENDPOINT: str = f"{BSKY_API_BASE}/app.bsky.feed.getAuthorFeed"
"""Paginated author post feed endpoint."""

BSKY_ACTOR_SEARCH_ENDPOINT: str = f"{BSKY_API_BASE}/app.bsky.actor.searchActors"
"""Actor/user search endpoint."""

BSKY_GET_PROFILE_ENDPOINT: str = f"{BSKY_API_BASE}/app.bsky.actor.getProfile"
"""Single actor profile lookup endpoint."""

BSKY_WEB_BASE: str = "https://bsky.app"
"""Web URL base for constructing post URLs from AT URIs."""

# ---------------------------------------------------------------------------
# Jetstream firehose endpoints
# ---------------------------------------------------------------------------

JETSTREAM_ENDPOINTS: list[str] = [
    "wss://jetstream1.us-east.bsky.network/subscribe",
    "wss://jetstream2.us-east.bsky.network/subscribe",
    "wss://jetstream1.us-west.bsky.network/subscribe",
    "wss://jetstream2.us-west.bsky.network/subscribe",
]
"""Jetstream WebSocket endpoints (regional; use first available)."""

# ---------------------------------------------------------------------------
# Danish defaults
# ---------------------------------------------------------------------------

DANISH_LANG: str = BLUESKY_LANG_FILTER
"""Language code for Danish content filtering (``"da"``)."""

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

MAX_RESULTS_PER_PAGE: int = 100
"""Maximum posts returned per API request (AT Protocol hard cap)."""

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

BLUESKY_TIERS: dict[Tier, TierConfig | None] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=300_000,
        rate_limit_per_minute=600,
        requires_credential=True,
        estimated_credits_per_1k=0,
        # 3,000 req / 5 min = 600 req/min with authentication.
        # Each request retrieves up to 100 posts.
    ),
    Tier.MEDIUM: None,
    Tier.PREMIUM: None,
}
"""Per-tier configuration for the Bluesky arena.

Only ``Tier.FREE`` is available.  MEDIUM and PREMIUM map to ``None``.
Authentication is required via handle + app password.
"""
