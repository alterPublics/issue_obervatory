"""Configuration for the VKontakte (VK) arena.

DEFERRED ARENA -- Phase 4 / Future
====================================

This module is a stub. The VKontakte arena is pending university legal review
before any live collection implementation begins.

See docs/arenas/new_arenas_implementation_plan.md section 6.10 for the full
list of legal considerations that must be resolved prior to activation:

- EU sanctions implications (VK Company / former Mail.ru Group)
- Cross-border data transfer under GDPR (no Russia adequacy decision)
- Russian Federal Law No. 152-FZ on Personal Data
- API geo-restriction verification from Danish deployment location
- University DPO sign-off and DPIA documentation

DO NOT activate or enable collection without completing the legal review first.

API Reference
-------------
- Base URL: https://api.vk.com/method/
- API version: 5.199
- Rate limit: 3 requests/second per access token
- Key collection methods: newsfeed.search, wall.get, wall.getComments

Credential Requirements
-----------------------
Credentials are stored in the CredentialPool with platform="vkontakte":
    {"access_token": "<user_token>", "app_id": "<vk_app_id>"}

A VK standalone application must be created at vk.com/dev with the following
OAuth permission scopes: wall, groups, offline.
"""

from __future__ import annotations

from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

VKONTAKTE_TIERS: dict[Tier, TierConfig] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=10_000,
        rate_limit_per_minute=180,  # 3 req/s per VK API limit
        requires_credential=True,
        estimated_credits_per_1k=0,
    ),
}
"""Tier definitions for the VKontakte arena.

Only FREE is supported. VK provides comprehensive access to public data
at no cost. The 180 req/min figure reflects the 3 req/s per-token limit
documented in the VK API reference.

Note: The execute() VKScript method allows batching up to 25 API calls per
single request, effectively raising throughput to 75 calls/second when used.
This should be exploited in the full implementation for high-throughput
community wall collection.
"""

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------

VK_API_BASE: str = "https://api.vk.com/method/"
"""Base URL for all VK API method calls.

All requests append the method name (e.g. 'newsfeed.search') and pass
access_token + v as query parameters.
"""

VK_API_VERSION: str = "5.199"
"""VK API version to request on every call.

Always include the v parameter. Breaking changes between versions are common.
Pin this and test explicitly when upgrading.
"""

VK_RATE_LIMIT_PER_SECOND: float = 3.0
"""Hard rate limit imposed by VK API per access token.

Error code 6 ('Too many requests per second') is returned on violation.
Implement exponential backoff on error codes 6 and 29 (rate limit reached).
"""

VK_EXECUTE_BATCH_SIZE: int = 25
"""Maximum number of VK API calls that can be batched in a single execute() request.

Using execute() with 25 sub-calls per request effectively multiplies throughput
by 25x relative to the 3 req/s base limit.
"""

DEFAULT_MAX_RESULTS: int = 500
"""Default result cap for a single collection call when max_results is not specified."""

# ---------------------------------------------------------------------------
# Collection method constants
#
# Documented here for reference when the full implementation is written.
# These values reflect VK API constraints as of API version 5.199.
# ---------------------------------------------------------------------------

VK_NEWSFEED_SEARCH_MAX_COUNT: int = 200
"""Maximum items per newsfeed.search request (VK API hard limit)."""

VK_WALL_GET_MAX_COUNT: int = 100
"""Maximum items per wall.get request (VK API hard limit)."""

VK_WALL_GETCOMMENTS_MAX_COUNT: int = 100
"""Maximum items per wall.getComments request (VK API hard limit)."""

# ---------------------------------------------------------------------------
# VK error codes relevant to collection
# ---------------------------------------------------------------------------

VK_ERROR_TOO_MANY_REQUESTS: int = 6
"""VK API error code for per-second rate limit violation."""

VK_ERROR_RATE_LIMIT_REACHED: int = 29
"""VK API error code for daily/monthly rate limit exhaustion."""

VK_ERROR_ACCESS_DENIED: int = 15
"""VK API error code when the resource is not publicly accessible."""
