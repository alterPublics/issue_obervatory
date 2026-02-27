"""Reddit arena configuration and tier definitions.

Reddit is a free-only arena for this project.  The Reddit OAuth API provides
100 requests per minute per OAuth client at no cost for non-commercial academic
use.  No MEDIUM or PREMIUM tiers exist.

Credential environment variable fallbacks (Phase 0 / dev):
- ``REDDIT_CLIENT_ID``     — OAuth app client ID.
- ``REDDIT_CLIENT_SECRET`` — OAuth app client secret.
- ``REDDIT_USER_AGENT``    — Descriptive user agent string.
  Defaults to ``"IssueObservatory/1.0 (research project)"``.

The ``REDDIT_FREE_API_KEY`` env-var name is also honoured by the CredentialPool
env-var fallback mechanism (``{PLATFORM}_{TIER}_API_KEY`` convention) for the
``client_id`` field when a full DB credential row is not present.

Danish subreddits are sourced from
:data:`issue_observatory.config.danish_defaults.DANISH_SUBREDDITS` and extended
with additional relevant communities defined in :data:`EXTRA_DANISH_SUBREDDITS`.
"""

from __future__ import annotations

from issue_observatory.config.danish_defaults import DANISH_SUBREDDITS
from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

REDDIT_RATE_LIMIT_PER_MINUTE: int = 90
"""Safety-net rate limit for the shared RateLimiter.

PRAW handles Reddit's 100 req/min limit internally.  The shared RateLimiter is
configured at 90 req/min to leave a 10% headroom and avoid any risk of hitting
the hard Reddit limit when multiple fast requests coincide.
"""

REDDIT_WINDOW_SECONDS: int = 60
"""Sliding window duration in seconds for the shared RateLimiter."""

# ---------------------------------------------------------------------------
# Search configuration
# ---------------------------------------------------------------------------

MAX_RESULTS_PER_SEARCH: int = 1000
"""Maximum results per Reddit search call.

asyncpraw handles Reddit's ``after`` token pagination automatically via its
generator.  The old value of 100 capped results at a single page.  Reddit's
listing API has a hard ceiling of ~1000 results regardless of pagination; this
constant matches that platform-imposed limit.
"""

DEFAULT_MAX_RESULTS: int = 1000
"""Default upper bound on results when ``max_results`` is not specified."""

DEFAULT_SEARCH_SORT: str = "new"
"""Default sort order for Reddit search queries (chronological)."""

DEFAULT_TIME_FILTER: str = "all"
"""Default time filter for Reddit search — no lower date bound."""

INCLUDE_COMMENTS_DEFAULT: bool = False
"""Whether to fetch top-level comments for each matched post by default.

Collecting comments significantly increases API quota usage.  Set to ``True``
in the query design if comment-level discourse analysis is required.
"""

MAX_COMMENTS_PER_POST: int = 100
"""Maximum number of top-level comments to collect per post."""

# ---------------------------------------------------------------------------
# Danish subreddits
# ---------------------------------------------------------------------------

EXTRA_DANISH_SUBREDDITS: list[str] = [
    "dkfinance",
    "dkpolitik",
    "scandinavia",
    "NORDVANSEN",
]
"""Additional Danish-relevant subreddits beyond the four defaults.

These supplement :data:`DANISH_SUBREDDITS` and are included in all collection
runs unless overridden by a query design configuration.

``dkfinance`` covers Danish economic and personal finance discourse.
``dkpolitik`` covers Danish political discussion and debate.
"""

ALL_DANISH_SUBREDDITS: list[str] = DANISH_SUBREDDITS + EXTRA_DANISH_SUBREDDITS
"""Combined list of default Danish subreddits used for term-based search.

Composed of :data:`~issue_observatory.config.danish_defaults.DANISH_SUBREDDITS`
(``["Denmark", "danish", "copenhagen", "aarhus"]``) plus
:data:`EXTRA_DANISH_SUBREDDITS`.
"""

DANISH_SUBREDDIT_SEARCH_STRING: str = "+".join(ALL_DANISH_SUBREDDITS)
"""Multireddit search string for all Danish subreddits.

Passed to ``asyncpraw.Reddit.subreddit()`` to search across all Danish
communities simultaneously (e.g. ``"Denmark+danish+copenhagen+aarhus+..."``)
in a single API call.
"""

# ---------------------------------------------------------------------------
# Default user agent
# ---------------------------------------------------------------------------

DEFAULT_USER_AGENT: str = "IssueObservatory/1.0 (academic research project)"
"""Fallback user agent used when no credential provides one.

Reddit blocks requests with generic user agents.  This string is used when the
credential payload does not include a ``user_agent`` field and the
``REDDIT_USER_AGENT`` environment variable is not set.
"""

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

REDDIT_TIERS: dict[Tier, TierConfig] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=5_000,
        rate_limit_per_minute=REDDIT_RATE_LIMIT_PER_MINUTE,
        requires_credential=True,
        estimated_credits_per_1k=0,
        # Reddit OAuth is free for non-commercial academic use.
        # 0 credits per result — no monetary cost.
    ),
}
"""Per-tier configuration for the Reddit arena.

Only ``Tier.FREE`` is available.  MEDIUM and PREMIUM tiers do not exist for
Reddit at this project's scale and usage category.
"""
