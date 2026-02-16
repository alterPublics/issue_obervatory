"""Reddit arena — social media collector for r/Denmark and Danish subreddits.

Provides async collection of Reddit posts and comments via the Reddit OAuth API
using the ``asyncpraw`` library.  Only the FREE tier is available; Reddit does
not offer a paid research API tier for this project's scale.

Exports:
    RedditCollector: The main arena collector class.

Usage::

    from issue_observatory.arenas.reddit import RedditCollector
    from issue_observatory.arenas.base import Tier

    collector = RedditCollector(credential_pool=pool)
    records = await collector.collect_by_terms(["klimaforandringer"], tier=Tier.FREE)
"""

from issue_observatory.arenas.reddit.collector import RedditCollector

__all__ = ["RedditCollector"]
