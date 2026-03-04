"""Tier configurations and constants for the Domain Crawler arena.

The Domain Crawler fetches front pages from a list of web domains, extracts
same-domain article links, then fetches and extracts each linked article.
This provides a practical alternative to Common Crawl for monitoring specific
news sites.

No external API is used; the tier is free in terms of external cost.
"""

from __future__ import annotations

from issue_observatory.arenas.base import Tier
from issue_observatory.config.tiers import TierConfig

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

DOMAIN_CRAWLER_TIERS: dict[Tier, TierConfig] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=1000,
        rate_limit_per_minute=30,
        requires_credential=False,
        estimated_credits_per_1k=0,
    ),
}

# ---------------------------------------------------------------------------
# Per-domain politeness
# ---------------------------------------------------------------------------

DOMAIN_DELAY: float = 1.5
"""Seconds to wait between consecutive requests to the same domain."""

MAX_LINKS_PER_DOMAIN: int = 50
"""Maximum number of article links to follow per domain per collection run."""

FETCH_CONCURRENCY: int = 5
"""Maximum number of domains crawled concurrently (batch size)."""

IDLE_TIMEOUT: float = 1800.0
"""Seconds without any new records before the crawl aborts gracefully.

If an entire batch of domains completes without producing a single article,
the elapsed idle time is checked.  Once it exceeds this threshold the crawler
stops and returns whatever it has collected so far — a partial result, not a
failure.  Set to 30 minutes by default."""

# ---------------------------------------------------------------------------
# HTTP client configuration
# ---------------------------------------------------------------------------

CONNECTION_POOL_LIMITS: dict[str, int] = {
    "max_connections": 30,
    "max_keepalive_connections": 15,
}

# ---------------------------------------------------------------------------
# Default Danish news domains
# ---------------------------------------------------------------------------

DANISH_NEWS_DOMAINS: list[str] = [
    "dr.dk",
    "tv2.dk",
    "politiken.dk",
    "berlingske.dk",
    "bt.dk",
    "eb.dk",
    "information.dk",
    "jyllands-posten.dk",
    "kristeligt-dagblad.dk",
    "nordjyske.dk",
    "borsen.dk",
    "altinget.dk",
    "folkeskolen.dk",
]
"""Curated list of major Danish news sites with crawlable front pages."""

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

HEALTH_CHECK_URL: str = "https://www.dr.dk/"
"""Stable Danish website used to validate the full fetch-and-extract pipeline."""

# ---------------------------------------------------------------------------
# Link filtering — file extensions to exclude
# ---------------------------------------------------------------------------

EXCLUDED_EXTENSIONS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm",
    ".zip", ".rar", ".tar", ".gz", ".7z",
    ".css", ".js", ".json", ".xml", ".rss", ".atom",
})
"""File extensions excluded from link extraction (media, documents, assets)."""
