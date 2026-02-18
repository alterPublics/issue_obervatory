"""Configuration for the Discord arena.

Defines tier settings and API constants used by
:class:`~issue_observatory.arenas.discord.collector.DiscordCollector`.

Discord is a free-only arena. The bot token is the sole credential required.
Bots cannot search messages by keyword; all term matching is client-side.
Rate limits are parsed from ``X-RateLimit-*`` response headers.
"""

from __future__ import annotations

from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

DISCORD_TIERS: dict[Tier, TierConfig] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=10_000,
        rate_limit_per_minute=300,  # 5 req/s global Discord limit
        requires_credential=True,   # Bot token is mandatory
        estimated_credits_per_1k=0,
    ),
}
"""Tier definitions for the Discord arena.

Only FREE is supported. Discord does not offer paid API tiers.
A valid bot token is always required — without it the API returns HTTP 401.
"""

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------

DISCORD_API_BASE: str = "https://discord.com/api/v10"
"""Base URL for the Discord REST API, pinned to version 10."""

DISCORD_RATE_LIMIT_PER_SECOND: float = 5.0
"""Conservative global request rate (req/s) for the bot.

Discord's documented global limit is 50 req/s, but the per-route limit for
``GET /channels/{id}/messages`` is approximately 5 req/5 s. Using 5 req/s
globally is a safe default that respects both limits.
"""

MESSAGES_PER_REQUEST: int = 100
"""Maximum messages returned per ``GET /channels/{id}/messages`` call.

Discord's hard maximum is 100. Using the maximum minimises round trips.
"""

DEFAULT_MAX_RESULTS: int = 1_000
"""Default result cap applied when ``max_results`` is not specified by the caller."""

HEALTH_CHECK_ENDPOINT: str = "/gateway"
"""Lightweight endpoint used by the health check.

``GET /gateway`` requires a valid bot token and returns the WebSocket URL.
A 200 response confirms that the token is valid and the API is reachable.
"""
