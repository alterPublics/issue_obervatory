"""YouTube arena configuration, tier definitions, and quota constants.

The YouTube Data API v3 has a strict daily quota of 10,000 units per GCP
project.  Search is the most expensive endpoint at 100 units per call.
The RSS-first strategy (zero quota cost) is therefore mandatory for
channel-based collection; search is reserved for keyword discovery.

Credential convention (CredentialPool ``platform="youtube"``, ``tier="free"``):
- Each credential payload must contain ``{"api_key": "AIza..."}``.
- Create one credential per GCP project to multiply the effective daily quota.

Environment variable fallback names::

    YOUTUBE_FREE_API_KEY
    YOUTUBE_FREE_API_KEY_2
    YOUTUBE_FREE_API_KEY_3
    ...

Quota unit costs (from the YouTube Data API v3 documentation):
- ``search.list``:        100 units per call
- ``videos.list``:          1 unit  per call (batch up to 50 IDs)
- ``channels.list``:        1 unit  per call
- ``commentThreads.list``:  1 unit  per call
- ``comments.list``:        1 unit  per call
"""

from __future__ import annotations

from issue_observatory.config.danish_defaults import YOUTUBE_DANISH_PARAMS
from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# API base URL
# ---------------------------------------------------------------------------

YOUTUBE_API_BASE_URL: str = "https://www.googleapis.com/youtube/v3"
"""Base URL for all YouTube Data API v3 endpoints."""

# ---------------------------------------------------------------------------
# RSS feed URL template
# ---------------------------------------------------------------------------

YOUTUBE_CHANNEL_RSS_URL: str = (
    "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
)
"""URL template for a YouTube channel's Atom RSS feed.

Returns up to 15 most recent videos.  No API key required.  Zero quota cost.
"""

# ---------------------------------------------------------------------------
# Known Danish YouTube channel IDs for RSS polling
# ---------------------------------------------------------------------------

DANISH_YOUTUBE_CHANNEL_IDS: dict[str, str] = {
    # Public broadcasters
    "dr_nyheder": "UCMufUaGlcuAvsSdzQV08BEA",
    "dr_ramasjang": "UCXMFBZZJv9GCWcbFuCeHp5w",
    "tv2_nyheder": "UCRrMFv4KT2TRBi8JZFiBfRA",
    "tv2_lorry": "UCEqhLX3pIqJFhQw4JHO0IAA",
    # Major newspapers
    "berlingske": "UCX8nJRBi8eGUL7WkMJJxMig",
    "politiken": "UCt-aABiHl_MO-kgFJfuEjMQ",
    "jyllandsposten": "UCpSKqv8R6jfV8cAVVSUb9pQ",
    "bt": "UCi4lfuKQE_fqNsRkxGVkAKg",
    "ekstrabladet": "UCiHYWCSKB6-9FWzJEhZXHdQ",
    # Parliament and public institutions
    "folketinget": "UCLLKdVWcEJLqDDTSMnQAWjw",
    # Political parties (sample)
    "socialdemokratiet": "UCJZZ-4FhLHwBvPNt8hFJxZA",
    "venstredk": "UCB5y5eA6yf5ItTeMzJnP1UA",
}
"""Curated map of label -> YouTube channel ID for key Danish channels.

These channels are polled via RSS feeds in ``collect_by_actors()`` when
no explicit actor_ids are provided, and are used for proactive channel
monitoring.  Channel IDs use the ``UC...`` format.

Note: Channel IDs were accurate as of early 2026.  Run the health check
periodically to verify RSS feed availability.
"""

# ---------------------------------------------------------------------------
# Quota unit costs
# ---------------------------------------------------------------------------

QUOTA_COSTS: dict[str, int] = {
    "search.list": 100,
    "videos.list": 1,
    "channels.list": 1,
    "commentThreads.list": 1,
    "comments.list": 1,
}
"""Quota unit cost for each YouTube Data API v3 endpoint.

Used by ``estimate_credits()`` and for logging purposes.  A single GCP
project has 10,000 units/day; pooling N keys gives N x 10,000 units/day.
"""

DAILY_QUOTA_PER_KEY: int = 10_000
"""Default YouTube Data API v3 daily quota units per GCP project key."""

# ---------------------------------------------------------------------------
# Request parameters
# ---------------------------------------------------------------------------

MAX_RESULTS_PER_SEARCH_PAGE: int = 50
"""Maximum results the YouTube ``search.list`` endpoint returns per page."""

MAX_VIDEO_IDS_PER_BATCH: int = 50
"""Maximum video IDs per ``videos.list`` batch call (1 quota unit)."""

YOUTUBE_VIDEO_BASE_URL: str = "https://www.youtube.com/watch?v={video_id}"
"""URL template for a YouTube video page."""

# ---------------------------------------------------------------------------
# Danish search parameters (from danish_defaults)
# ---------------------------------------------------------------------------

DANISH_PARAMS: dict[str, str] = YOUTUBE_DANISH_PARAMS
"""Danish locale parameters applied to all YouTube ``search.list`` requests.

Equivalent to ``{"relevanceLanguage": "da", "regionCode": "DK"}``.
"""

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

REQUEST_RATE_MAX_CALLS: int = 10
"""Maximum HTTP requests per sliding window for request-rate throttling.

This controls per-second request rate only — it is distinct from quota
management which tracks daily API units.  The YouTube API allows approximately
10-20 requests/second empirically.
"""

REQUEST_RATE_WINDOW_SECONDS: int = 1
"""Sliding window duration (seconds) for request-rate throttling."""

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

YOUTUBE_TIERS: dict[Tier, TierConfig] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=5_000,
        rate_limit_per_minute=600,
        requires_credential=True,
        estimated_credits_per_1k=100,
        # 1 credit = 1 YouTube API unit.
        # 1,000 results via search requires: ceil(1000/50) = 20 search pages
        # = 20 x 100 = 2,000 units.  But with batch enrichment the per-result
        # cost amortizes to ~2 units/result → 2,000 credits per 1K results.
        # We set 100 as a conservative estimate that accounts for the search
        # cost being the dominant factor.
    ),
    Tier.MEDIUM: TierConfig(
        tier=Tier.MEDIUM,
        max_results_per_run=5_000,
        rate_limit_per_minute=600,
        requires_credential=True,
        estimated_credits_per_1k=100,
    ),
    Tier.PREMIUM: TierConfig(
        tier=Tier.PREMIUM,
        max_results_per_run=50_000,
        rate_limit_per_minute=600,
        requires_credential=True,
        estimated_credits_per_1k=100,
    ),
}
"""Per-tier configuration for the YouTube arena.

YouTube only has a FREE tier (no paid API tier exists).  MEDIUM and PREMIUM
entries are identical to FREE to allow future differentiation (e.g. higher
quota via Google's quota increase programme).
"""
