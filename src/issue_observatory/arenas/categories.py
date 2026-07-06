"""Canonical arena category mapping.

Every ``platform_name`` in the system maps to exactly one of four
arena categories.  This module is the single source of truth for that
mapping; all UI labels, filter dropdowns, and analysis groupings should
reference the constants defined here rather than hard-coding category
strings.

The four categories are:

- ``news`` — News media outlets, wire services, and news aggregators.
- ``search`` — Search engines, autocomplete, reference, and AI search.
- ``web`` — Open web archives, backlink indexes, and URL scraping tools.
- ``social_media`` — Social networks and messaging platforms.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Canonical mapping: platform_name -> arena category
# ---------------------------------------------------------------------------

ARENA_CATEGORIES: dict[str, str] = {
    # news
    "gdelt": "news",
    "rss_feeds": "news",
    "ritzau_via": "news",
    "event_registry": "news",
    "domain_crawler": "news",
    # search
    "google_search": "search",
    "google_autocomplete": "search",
    "wikipedia": "search",
    "openrouter": "search",
    # web
    "url_scraper": "web",
    "majestic": "web",
    "common_crawl": "web",
    "wayback": "web",
    # social_media
    "reddit": "social_media",
    "bluesky": "social_media",
    "youtube": "social_media",
    "facebook": "social_media",
    "instagram": "social_media",
    "tiktok": "social_media",
    "threads": "social_media",
    "telegram": "social_media",
    "gab": "social_media",
    "discord": "social_media",
    "twitch": "social_media",
    "x_twitter": "social_media",
    "vkontakte": "social_media",
}

# ---------------------------------------------------------------------------
# Human-readable display labels for each category
# ---------------------------------------------------------------------------

ARENA_CATEGORY_LABELS: dict[str, str] = {
    "news": "News",
    "search": "Search",
    "web": "Web",
    "social_media": "Social Media",
}

# All valid category values (for validation)
VALID_CATEGORIES: frozenset[str] = frozenset(ARENA_CATEGORY_LABELS.keys())


def get_arena_category(platform_name: str) -> str:
    """Look up the arena category for a platform.

    Args:
        platform_name: Unique platform identifier (e.g. ``"reddit"``).

    Returns:
        One of ``"news"``, ``"search"``, ``"web"``, or ``"social_media"``.

    Raises:
        KeyError: If the platform name is not in the mapping.
    """
    return ARENA_CATEGORIES[platform_name]
