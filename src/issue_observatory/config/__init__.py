"""Configuration package for Issue Observatory.

Re-exports the most commonly used configuration symbols so that
callers can write::

    from issue_observatory.config import get_settings, Tier, DANISH_RSS_FEEDS

without needing to know which sub-module each symbol lives in.
"""

from __future__ import annotations

from issue_observatory.config.danish_defaults import (
    BLUESKY_DANISH_FILTER,
    DANISH_GOOGLE_PARAMS,
    DANISH_RSS_FEEDS,
    DANISH_SUBREDDITS,
    DEFAULT_LANGUAGE,
    DEFAULT_LOCALE_COUNTRY,
    DEFAULT_LOCALE_TAG,
    GDELT_DANISH_FILTERS,
    POSTGRES_FTS_LANGUAGE,
    VIA_RITZAU_API_BASE,
    YOUTUBE_DANISH_PARAMS,
)
from issue_observatory.config.settings import Settings, get_settings
from issue_observatory.config.tiers import TIER_DEFAULTS, Tier, TierConfig

__all__ = [
    # settings
    "Settings",
    "get_settings",
    # tiers
    "Tier",
    "TierConfig",
    "TIER_DEFAULTS",
    # danish defaults
    "DEFAULT_LANGUAGE",
    "DEFAULT_LOCALE_COUNTRY",
    "DEFAULT_LOCALE_TAG",
    "DANISH_RSS_FEEDS",
    "DANISH_SUBREDDITS",
    "DANISH_GOOGLE_PARAMS",
    "GDELT_DANISH_FILTERS",
    "BLUESKY_DANISH_FILTER",
    "YOUTUBE_DANISH_PARAMS",
    "POSTGRES_FTS_LANGUAGE",
    "VIA_RITZAU_API_BASE",
]
