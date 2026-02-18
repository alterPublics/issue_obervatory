"""Configuration for the Twitch arena.

Defines tier settings and API constants used by
:class:`~issue_observatory.arenas.twitch.collector.TwitchCollector`.

Twitch is a free-only arena (streaming-only for chat). This module covers
the Helix REST API used for channel discovery and metadata. Real-time chat
collection via EventSub WebSocket is not configured here — it belongs in a
future ``TwitchStreamer`` class.

IMPORTANT: There is no historical chat endpoint on Twitch. The batch
``collect_by_terms`` and ``collect_by_actors`` methods only return channel
metadata (not chat messages).
"""

from __future__ import annotations

from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

TWITCH_TIERS: dict[Tier, TierConfig] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=10_000,
        rate_limit_per_minute=800,  # 800 points/minute with app access token
        requires_credential=True,   # client_id + client_secret required
        estimated_credits_per_1k=0,
    ),
}
"""Tier definitions for the Twitch arena.

Only FREE is supported. Twitch does not offer paid API tiers. The Helix API
rate limit is 800 points/minute per app access token; most endpoints cost
1 point per request.
"""

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------

TWITCH_API_BASE: str = "https://api.twitch.tv/helix"
"""Base URL for the Twitch Helix REST API."""

TWITCH_TOKEN_URL: str = "https://id.twitch.tv/oauth2/token"
"""OAuth 2.0 token endpoint for the Client Credentials grant."""

TWITCH_EVENTSUB_URL: str = "wss://eventsub.wss.twitch.tv/ws"
"""EventSub WebSocket endpoint for real-time chat collection.

NOTE: Historical chat messages cannot be retrieved from this endpoint.
Only messages sent while a WebSocket connection is active are delivered.
A future ``TwitchStreamer`` class will connect here for real-time collection.
"""

SEARCH_RESULTS_PER_REQUEST: int = 100
"""Maximum results per ``GET /search/channels`` request (Twitch maximum)."""

DEFAULT_MAX_RESULTS: int = 500
"""Default result cap applied when ``max_results`` is not specified."""

HEALTH_CHECK_ENDPOINT: str = "/streams"
"""Lightweight Helix endpoint used by the health check.

``GET /streams?first=1`` requires only an app access token and returns a
minimal response. A 200 response confirms the API is reachable and the
credentials are valid.
"""
