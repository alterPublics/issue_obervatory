"""Danish RSS Feeds arena — free-tier news monitoring for Danish outlets.

Polls curated Danish RSS feeds from :data:`issue_observatory.config.danish_defaults.DANISH_RSS_FEEDS`,
matches entries against query-design search terms, and normalizes them to the
universal ``content_records`` schema.

Collectors:
    :class:`~issue_observatory.arenas.rss_feeds.collector.RSSFeedsCollector`

Tasks:
    :mod:`issue_observatory.arenas.rss_feeds.tasks`

Router:
    :mod:`issue_observatory.arenas.rss_feeds.router`

Configuration:
    :mod:`issue_observatory.arenas.rss_feeds.config`
"""
