"""X/Twitter arena configuration constants and tier definitions.

Defines API base URLs, Danish search defaults, cost constants, rate limit
configurations, and default field sets for both supported tiers:

- MEDIUM: TwitterAPI.io third-party search service.
- PREMIUM: Official X API v2 Pro tier (full-archive search).

No secrets are stored here. Credentials are managed exclusively through
:class:`~issue_observatory.core.credential_pool.CredentialPool`.
"""

from __future__ import annotations

from issue_observatory.arenas.base import Tier
from issue_observatory.config.tiers import TierConfig

# ---------------------------------------------------------------------------
# API base URLs
# ---------------------------------------------------------------------------

TWITTERAPIIO_BASE_URL: str = "https://api.twitterapi.io/twitter/tweet/advanced_search"
"""Base URL for the TwitterAPI.io advanced search endpoint (medium tier)."""

TWITTERAPIIO_USER_TWEETS_URL: str = "https://api.twitterapi.io/twitter/user/last_tweets"
"""TwitterAPI.io endpoint for fetching the most recent tweets from a user."""

TWITTER_V2_BASE_URL: str = "https://api.twitter.com/2"
"""Base URL for the official X API v2 (premium tier)."""

TWITTER_V2_SEARCH_ALL: str = f"{TWITTER_V2_BASE_URL}/tweets/search/all"
"""Full-archive search endpoint (Pro tier only)."""

TWITTER_V2_SEARCH_RECENT: str = f"{TWITTER_V2_BASE_URL}/tweets/search/recent"
"""Recent (7-day) search endpoint."""

TWITTER_V2_USER_TWEETS: str = f"{TWITTER_V2_BASE_URL}/users/{{user_id}}/tweets"
"""User timeline endpoint. Format with ``user_id``."""

# ---------------------------------------------------------------------------
# Danish search defaults
# ---------------------------------------------------------------------------

DANISH_LANG_OPERATOR: str = "lang:da"
"""X/Twitter search operator to restrict results to Danish-language tweets.

Must be appended to every query to focus collection on Danish public discourse.
"""

# ---------------------------------------------------------------------------
# Cost constants (medium tier)
# ---------------------------------------------------------------------------

TWITTERAPIIO_COST_PER_1K: float = 0.15
"""Cost in USD per 1,000 tweets retrieved via TwitterAPI.io."""

# ---------------------------------------------------------------------------
# Rate limit config per tier
# ---------------------------------------------------------------------------

# Medium: TwitterAPI.io is cost-limited, not rate-limited.
# A client-side rate limit of 1 call/sec is used to avoid bursting
# and to maintain predictable credit consumption.
MEDIUM_RATE_LIMIT_MAX_CALLS: int = 1
MEDIUM_RATE_LIMIT_WINDOW_SECONDS: int = 1

# Premium: Official X API Pro full-archive search allows 300 req / 15 min
# = 1 req/sec. Safety net enforced at 15 calls/min.
PREMIUM_RATE_LIMIT_MAX_CALLS: int = 15
PREMIUM_RATE_LIMIT_WINDOW_SECONDS: int = 60

# ---------------------------------------------------------------------------
# Default tweet.fields and expansions for X API v2
# ---------------------------------------------------------------------------

TWITTER_V2_TWEET_FIELDS: str = (
    "id,text,author_id,created_at,public_metrics,lang,"
    "referenced_tweets,entities,conversation_id,in_reply_to_user_id,"
    "source,possibly_sensitive,context_annotations"
)
"""Comma-separated tweet.fields requested for all v2 API calls."""

TWITTER_V2_USER_FIELDS: str = "id,name,username,description,profile_image_url,verified"
"""User fields expanded alongside tweet objects."""

TWITTER_V2_EXPANSIONS: str = "author_id,referenced_tweets.id,referenced_tweets.id.author_id"
"""Expansions for tweet objects to hydrate author and referenced tweet data."""

TWITTER_V2_MAX_RESULTS_PER_PAGE: int = 100
"""Maximum results per page for the v2 search endpoints (10–500, default 10)."""

TWITTERAPIIO_QUERY_TYPE: str = "Latest"
"""TwitterAPI.io queryType for reverse-chronological results."""

# ---------------------------------------------------------------------------
# Tier configuration objects
# ---------------------------------------------------------------------------

XTWITTER_TIERS: dict[Tier, TierConfig] = {
    Tier.MEDIUM: TierConfig(
        provider="twitterapi_io",
        max_results_per_run=10_000,
        requires_credentials=True,
        credits_per_result=1,
        requests_per_minute=MEDIUM_RATE_LIMIT_MAX_CALLS * 60,
    ),
    Tier.PREMIUM: TierConfig(
        provider="x_twitter_v2",
        max_results_per_run=50_000,
        requires_credentials=True,
        credits_per_result=1,
        requests_per_minute=PREMIUM_RATE_LIMIT_MAX_CALLS,
    ),
}
"""Tier configuration objects for the X/Twitter arena."""
