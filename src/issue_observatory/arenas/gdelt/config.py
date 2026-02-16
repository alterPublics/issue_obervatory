"""Configuration for the GDELT arena.

Defines API endpoints, query parameters, tier settings, and language/country
code mappings used by
:class:`~issue_observatory.arenas.gdelt.collector.GDELTCollector`.
"""

from __future__ import annotations

from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------

GDELT_DOC_API_BASE: str = "https://api.gdeltproject.org/api/v2/doc/doc"
"""Base URL for the GDELT DOC 2.0 API."""

GDELT_MAX_RECORDS: int = 250
"""Maximum records per GDELT DOC API request (hard API limit)."""

GDELT_DATETIME_FORMAT: str = "%Y%m%d%H%M%S"
"""Datetime format used by GDELT's ``startdatetime``/``enddatetime`` params."""

GDELT_SEENDATE_FORMAT: str = "%Y%m%dT%H%M%SZ"
"""Datetime format used in GDELT ``seendate`` response fields."""

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

GDELT_RATE_LIMIT_KEY: str = "ratelimit:news_media:gdelt:shared"
"""Redis key for the GDELT shared rate limit slot."""

GDELT_MAX_CALLS_PER_SECOND: int = 1
"""Maximum GDELT DOC API calls per second (empirical limit)."""

GDELT_RATE_WINDOW_SECONDS: int = 1
"""Sliding window duration for the GDELT rate limit."""

GDELT_RATE_LIMIT_TIMEOUT: float = 30.0
"""Maximum seconds to wait for a rate-limit slot before raising."""

# ---------------------------------------------------------------------------
# Query defaults
# ---------------------------------------------------------------------------

GDELT_SORT_ORDER: str = "datedesc"
"""Default sort order for GDELT article list results."""

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

GDELT_TIERS: dict[Tier, TierConfig] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=5_000,
        rate_limit_per_minute=60,
        requires_credential=False,
        estimated_credits_per_1k=0,
    ),
}
"""Tier definitions for the GDELT arena.  Only FREE is supported."""

# ---------------------------------------------------------------------------
# Language code mapping
# ---------------------------------------------------------------------------

GDELT_LANGUAGE_MAP: dict[str, str] = {
    "danish": "da",
    "english": "en",
    "german": "de",
    "french": "fr",
    "spanish": "es",
    "swedish": "sv",
    "norwegian": "no",
    "finnish": "fi",
    "dutch": "nl",
    "portuguese": "pt",
    "italian": "it",
    "polish": "pl",
    "russian": "ru",
    "arabic": "ar",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
}
"""Maps GDELT full language names (lowercase) to ISO 639-1 codes."""

GDELT_COUNTRY_MAP: dict[str, str] = {
    "DA": "DK",  # GDELT FIPS -> ISO 3166-1 alpha-2
}
"""Maps GDELT FIPS 10-4 country codes to ISO 3166-1 alpha-2 codes."""


def map_language(gdelt_lang: str | None) -> str | None:
    """Map a GDELT language string to an ISO 639-1 code.

    Args:
        gdelt_lang: GDELT language string (e.g. ``"Danish"``).

    Returns:
        ISO 639-1 code (e.g. ``"da"``), or the lowercased input if not mapped.
    """
    if not gdelt_lang:
        return None
    return GDELT_LANGUAGE_MAP.get(gdelt_lang.lower(), gdelt_lang.lower()[:2])


def map_country(gdelt_country: str | None) -> str | None:
    """Map a GDELT FIPS country code to an ISO 3166-1 alpha-2 code.

    Args:
        gdelt_country: GDELT FIPS code (e.g. ``"DA"``).

    Returns:
        ISO 3166-1 code (e.g. ``"DK"``), or the original code if not mapped.
    """
    if not gdelt_country:
        return None
    return GDELT_COUNTRY_MAP.get(gdelt_country.upper(), gdelt_country)
