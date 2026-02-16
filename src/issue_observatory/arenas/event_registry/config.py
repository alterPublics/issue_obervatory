"""Configuration for the Event Registry / NewsAPI.ai arena.

Defines API endpoints, Danish locale parameters, token budget thresholds,
rate-limit constants, and per-tier settings used by
:class:`~issue_observatory.arenas.event_registry.collector.EventRegistryCollector`.

Key distinctions from other arenas:
- Event Registry uses ISO 639-3 three-letter language codes (``"dan"``) not
  ISO 639-1 two-letter codes.  The ``map_language()`` helper in this module
  maps 639-3 -> 639-1 for the UCR ``language`` field.
- Token budget (not rate limit) is the primary operational constraint.
- ``sourceLocationUri`` set to Denmark's Wikipedia URI filters for Danish
  outlet articles regardless of article language.

See research brief: ``/docs/arenas/event_registry.md``.
"""

from __future__ import annotations

from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# API base URL
# ---------------------------------------------------------------------------

EVENT_REGISTRY_API_BASE: str = "https://newsapi.ai/api/v1"
"""Base URL for the NewsAPI.ai / Event Registry REST API (v1)."""

EVENT_REGISTRY_ARTICLE_ENDPOINT: str = f"{EVENT_REGISTRY_API_BASE}/article/getArticles"
"""Full URL for the article search endpoint."""

# ---------------------------------------------------------------------------
# Danish locale parameters
# ---------------------------------------------------------------------------

EVENT_REGISTRY_DANISH_LANG: str = "dan"
"""Event Registry's ISO 639-3 code for Danish.

Event Registry uses three-letter ISO 639-3 codes in request parameters and
response ``lang`` fields.  The UCR schema uses ISO 639-1 (``"da"``).
Use :func:`map_language` to convert before writing to content records.
"""

EVENT_REGISTRY_DENMARK_URI: str = "http://en.wikipedia.org/wiki/Denmark"
"""Wikipedia concept URI used as the ``sourceLocationUri`` filter.

Restricts results to articles from Danish news sources regardless of
whether the article language is Danish.  More reliable than language
filtering alone because some Danish outlets publish English-language content.
"""

EVENT_REGISTRY_DATA_TYPES: list[str] = ["news", "blog"]
"""Article data types to include in search requests.

``"news"`` covers standard news articles; ``"blog"`` covers blog posts
published on monitored domains.  Press release (``"pr"``) type is excluded
as Via Ritzau handles that category directly.
"""

# ---------------------------------------------------------------------------
# Query defaults
# ---------------------------------------------------------------------------

EVENT_REGISTRY_DEFAULT_MAX_RESULTS: int = 100
"""Default maximum articles per page request (API hard limit is 100)."""

EVENT_REGISTRY_DEFAULT_SORT_BY: str = "date"
"""Default sort order.  ``"date"`` returns newest articles first."""

EVENT_REGISTRY_DEFAULT_SORT_ASC: bool = False
"""Sort descending by date so the most recent articles come first."""

# ---------------------------------------------------------------------------
# Token budget warning thresholds
# ---------------------------------------------------------------------------

TOKEN_BUDGET_WARNING_PCT: float = 0.20
"""Log a WARNING when remaining token budget falls below this fraction.

At 20% remaining (e.g. 1,000 tokens left on the 5,000 Medium tier), the
collector emits a WARNING so operators can plan tier upgrades or add keys
before the budget is exhausted.
"""

TOKEN_BUDGET_CRITICAL_PCT: float = 0.05
"""Log a CRITICAL when remaining token budget falls below this fraction.

At 5% remaining (e.g. 250 tokens on Medium), all further collection is
halted and an error is raised so Celery tasks fail fast and alert on-call.
"""

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

EVENT_REGISTRY_RATE_LIMIT_KEY: str = "ratelimit:news_media:event_registry:{credential_id}"
"""Redis key template for per-credential rate limiting.

Formatted at runtime with the credential ID:
``"ratelimit:news_media:event_registry:abc123"``
"""

EVENT_REGISTRY_MAX_CALLS_PER_SECOND: int = 5
"""Conservative request rate: 5 calls/second per credential.

The Event Registry API allows ~10 req/sec empirically, but the token
budget constraint is more important.  5 req/sec leaves headroom while
ensuring token burn rate stays manageable.
"""

EVENT_REGISTRY_RATE_WINDOW_SECONDS: int = 1
"""Sliding window width (seconds) for the rate limiter."""

EVENT_REGISTRY_RATE_LIMIT_TIMEOUT: float = 30.0
"""Maximum seconds to wait for a rate-limit slot before raising."""

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

EVENT_REGISTRY_TIERS: dict[Tier, TierConfig] = {
    Tier.MEDIUM: TierConfig(
        tier=Tier.MEDIUM,
        max_results_per_run=5_000,   # 5,000 tokens/month * 100 articles/token
        rate_limit_per_minute=300,   # 5 req/sec * 60 sec
        requires_credential=True,
        estimated_credits_per_1k=10, # 1 token per 100-article page = 10 tokens/1,000 articles
    ),
    Tier.PREMIUM: TierConfig(
        tier=Tier.PREMIUM,
        max_results_per_run=50_000,  # 50,000 tokens/month * 100 articles/token
        rate_limit_per_minute=300,
        requires_credential=True,
        estimated_credits_per_1k=10,
    ),
}
"""Tier definitions for the Event Registry arena.

- ``MEDIUM``: NewsAPI.ai Starter (~$90/month, 5,000 tokens/month).
- ``PREMIUM``: NewsAPI.ai Business (~$490/month, 50,000 tokens/month).

Token cost model: 1 token per ``getArticles`` request.  A request can return
up to 100 articles.  One page of 100 results costs 1 token.
"""

# ---------------------------------------------------------------------------
# Language code mapping (ISO 639-3 -> ISO 639-1)
# ---------------------------------------------------------------------------

EVENT_REGISTRY_LANGUAGE_MAP: dict[str, str] = {
    "dan": "da",  # Danish
    "eng": "en",  # English
    "swe": "sv",  # Swedish
    "nob": "nb",  # Norwegian Bokmal
    "nno": "nn",  # Norwegian Nynorsk
    "deu": "de",  # German
    "fra": "fr",  # French
    "spa": "es",  # Spanish
    "ita": "it",  # Italian
    "por": "pt",  # Portuguese
    "nld": "nl",  # Dutch
    "pol": "pl",  # Polish
    "rus": "ru",  # Russian
    "ara": "ar",  # Arabic
    "zho": "zh",  # Chinese
    "jpn": "ja",  # Japanese
    "kor": "ko",  # Korean
    "fin": "fi",  # Finnish
}
"""Maps Event Registry ISO 639-3 language codes to ISO 639-1 codes for the UCR ``language`` field."""


def map_language(er_lang: str | None) -> str | None:
    """Map an Event Registry ISO 639-3 language code to ISO 639-1.

    Args:
        er_lang: Three-letter ISO 639-3 language code from the Event Registry
            API (e.g. ``"dan"``).

    Returns:
        Two-letter ISO 639-1 code (e.g. ``"da"``), or ``None`` if input is
        ``None``.  Falls back to the first two characters of the input code
        if no explicit mapping is found.
    """
    if not er_lang:
        return None
    return EVENT_REGISTRY_LANGUAGE_MAP.get(er_lang.lower(), er_lang.lower()[:2])
