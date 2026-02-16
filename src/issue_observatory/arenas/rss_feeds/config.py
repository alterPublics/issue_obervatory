"""Configuration for the RSS Feeds arena.

Defines tier settings and feed-level metadata used by
:class:`~issue_observatory.arenas.rss_feeds.collector.RSSFeedsCollector`.

All feeds are public and unauthenticated — only the FREE tier is supported.
The DANISH_RSS_FEEDS dict from :mod:`issue_observatory.config.danish_defaults`
is the authoritative feed list.  This module enriches each entry with polling
metadata and platform slug conventions.
"""

from __future__ import annotations

from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

RSS_TIERS: dict[Tier, TierConfig] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=10_000,
        rate_limit_per_minute=60,
        requires_credential=False,
        estimated_credits_per_1k=0,
    ),
}
"""Tier definitions for the RSS Feeds arena.

Only FREE is supported.  feedparser fetches feeds directly — no API key needed.
"""

# ---------------------------------------------------------------------------
# Feed concurrency / politeness settings
# ---------------------------------------------------------------------------

FETCH_CONCURRENCY: int = 10
"""Maximum number of concurrent HTTP feed fetches (semaphore size)."""

INTER_OUTLET_DELAY_SECONDS: float = 0.5
"""Delay in seconds between consecutive requests to the same outlet.

Prevents hammering a single outlet's web server even within the semaphore limit.
"""

HEALTH_CHECK_FEED_URL: str = (
    "https://www.dr.dk/nyheder/service/feeds/allenyheder"
)
"""Feed URL used for the health check — DR's all-news feed."""

HEALTH_CHECK_OUTLET: str = "dr_allenyheder"
"""Outlet key corresponding to :data:`HEALTH_CHECK_FEED_URL`."""

# ---------------------------------------------------------------------------
# Outlet slug derivation
# ---------------------------------------------------------------------------

def outlet_slug_from_key(feed_key: str) -> str:
    """Derive the short outlet name from a DANISH_RSS_FEEDS dict key.

    The convention is ``{outlet}_{category}`` — this function returns the
    ``outlet`` prefix so that, e.g., ``"dr_politik"`` becomes ``"dr"``.

    Args:
        feed_key: Key from :data:`DANISH_RSS_FEEDS`, e.g. ``"dr_politik"``.

    Returns:
        The outlet portion of the key, e.g. ``"dr"``.
    """
    return feed_key.split("_")[0]
