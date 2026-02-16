"""Danish locale defaults applied automatically to collection queries.

When a query design does not specify language or locale filters, the constants
defined here are used to focus collection on Danish public discourse.  They are
also consumed directly by arena collectors:

- Google Search / Autocomplete: :data:`DANISH_GOOGLE_PARAMS`
- Reddit: :data:`DANISH_SUBREDDITS`
- RSS news: :data:`DANISH_RSS_FEEDS`
- GDELT DOC API: :data:`GDELT_DANISH_FILTERS`
- Bluesky AT Protocol search: :data:`BLUESKY_DANISH_FILTER`
- YouTube Data API v3: :data:`YOUTUBE_DANISH_PARAMS`
- PostgreSQL full-text search: :data:`POSTGRES_FTS_LANGUAGE`

All feed URLs were verified active as of early 2026 (see
``reports/danish_context_guide.md`` for provenance).  Health monitoring should
re-verify them periodically; the RSS arena's health check endpoint is the
canonical liveness signal.

**Excluded sources**: Infomedia is explicitly excluded per project specification,
despite being the most comprehensive Danish news archive.  Do not add Infomedia
feeds or API calls to this module or any arena implementation.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Language / locale identifiers
# ---------------------------------------------------------------------------

DEFAULT_LANGUAGE: str = "da"
"""ISO 639-1 language code for Danish."""

DEFAULT_LOCALE_COUNTRY: str = "DK"
"""ISO 3166-1 alpha-2 country code for Denmark (upper-case, matching platform conventions)."""

DEFAULT_LOCALE_COUNTRY_LOWER: str = "dk"
"""Lower-case variant of the country code, used where platforms expect lower-case (e.g. Google ``gl`` param)."""

DEFAULT_LOCALE_TAG: str = "da-DK"
"""BCP 47 locale tag combining language and country."""

# ---------------------------------------------------------------------------
# Danish RSS feeds
# ---------------------------------------------------------------------------

DANISH_RSS_FEEDS: dict[str, str] = {
    # ------------------------------------------------------------------
    # DR (Danmarks Radio) — public broadcaster
    # Base pattern: https://www.dr.dk/nyheder/service/feeds/{category}
    # Source: dr.dk/nyheder/service/feeds (updated September 2024, no auth required)
    # ------------------------------------------------------------------
    "dr_allenyheder": "https://www.dr.dk/nyheder/service/feeds/allenyheder",
    "dr_indland": "https://www.dr.dk/nyheder/service/feeds/indland",
    "dr_udland": "https://www.dr.dk/nyheder/service/feeds/udland",
    "dr_penge": "https://www.dr.dk/nyheder/service/feeds/penge",
    "dr_politik": "https://www.dr.dk/nyheder/service/feeds/politik",
    "dr_viden": "https://www.dr.dk/nyheder/service/feeds/viden",
    "dr_kultur": "https://www.dr.dk/nyheder/service/feeds/kultur",
    "dr_seneste": "https://www.dr.dk/nyheder/service/feeds/seneste",
    "dr_sport": "https://www.dr.dk/nyheder/service/feeds/sport",
    # DR regional feeds
    "dr_bornholm": "https://www.dr.dk/nyheder/service/feeds/regionale/bornholm",
    "dr_fyn": "https://www.dr.dk/nyheder/service/feeds/regionale/fyn",
    "dr_koebenhavn": "https://www.dr.dk/nyheder/service/feeds/regionale/koebenhavn",
    "dr_midtvest": "https://www.dr.dk/nyheder/service/feeds/regionale/midtvest",
    "dr_nordjylland": "https://www.dr.dk/nyheder/service/feeds/regionale/nordjylland",
    "dr_sjaelland": "https://www.dr.dk/nyheder/service/feeds/regionale/sjaelland",
    "dr_sonderjylland": "https://www.dr.dk/nyheder/service/feeds/regionale/sonderjylland",
    "dr_trekanten": "https://www.dr.dk/nyheder/service/feeds/regionale/trekanten",
    "dr_oestjylland": "https://www.dr.dk/nyheder/service/feeds/regionale/oestjylland",
    # ------------------------------------------------------------------
    # TV2 — commercial public broadcaster
    # Restored via API-based feed (verified active, replaces feeds discontinued 2019)
    # ------------------------------------------------------------------
    "tv2_nyheder": "https://feeds.services.tv2.dk/api/feeds/nyheder/rss",
    # ------------------------------------------------------------------
    # BT — tabloid daily (Berlingske Media group)
    # ------------------------------------------------------------------
    "bt_seneste": "https://www.bt.dk/bt/seneste/rss",
    # ------------------------------------------------------------------
    # Politiken — broadsheet daily (JP/Politikens Hus group)
    # ------------------------------------------------------------------
    "politiken_seneste": "http://politiken.dk/rss/senestenyt.rss",
    # ------------------------------------------------------------------
    # Berlingske — broadsheet daily (Berlingske Media group)
    # ------------------------------------------------------------------
    "berlingske_nyheder": "https://www.berlingske.dk/content/rss",
    # ------------------------------------------------------------------
    # Ekstra Bladet — tabloid daily (JP/Politikens Hus group)
    # Feed directory: https://ekstrabladet.dk/services/rss-feeds-fra-ekstra-bladet/4576561
    # ------------------------------------------------------------------
    "ekstrabladet_nyheder": "https://ekstrabladet.dk/nyheder/rss",
    # ------------------------------------------------------------------
    # Information — independent broadsheet (subscriber-funded)
    # ------------------------------------------------------------------
    "information_nyheder": "http://www.information.dk/feed",
    # ------------------------------------------------------------------
    # Jyllands-Posten — broadsheet daily (JP/Politikens Hus group)
    # NOTE: JP's RSS availability is uncertain as of 2026 (shifting to app-first
    # delivery).  This URL may return 404 — the RSS arena health check will flag it.
    # ------------------------------------------------------------------
    "jyllandsposten_nyheder": "https://jyllands-posten.dk/rss/topnyheder.jsp",
    # ------------------------------------------------------------------
    # Nordjyske — regional daily (Nordjyske Medier group)
    # ------------------------------------------------------------------
    "nordjyske_nyheder": "https://nordjyske.dk/rss/nyheder",
    # ------------------------------------------------------------------
    # Fyens Stiftstidende — regional daily (Jysk Fynske Medier group)
    # Shares the /feed/{category} pattern across the JFM group outlets.
    # ------------------------------------------------------------------
    "fyens_stiftstidende_danmark": "https://fyens.dk/feed/danmark",
    # ------------------------------------------------------------------
    # Børsen — financial daily (Berlingske Media group)
    # ------------------------------------------------------------------
    "boersen_nyheder": "https://borsen.dk/rss",
    # ------------------------------------------------------------------
    # Kristeligt Dagblad — Christian/ethical broadsheet (independent)
    # ------------------------------------------------------------------
    "kristeligt_dagblad_nyheder": "https://www.kristeligt-dagblad.dk/feed/rss.xml",
}
"""Curated Danish news outlet RSS feeds.

Keys follow the naming convention ``{outlet_slug}_{feed_category}``.
Values are the feed URLs.  All feeds require no authentication and carry no
full-article paywall at the RSS level (though linked articles may be paywalled).

**Excluded**: Infomedia (per project rules — see module docstring).

Arena implementations that consume these feeds (e.g.
``arenas/news_media/rss_feeds/``) should iterate over this dictionary and
report the outlet name (key) as the ``platform`` field on collected content
records.
"""

# ---------------------------------------------------------------------------
# Reddit
# ---------------------------------------------------------------------------

DANISH_SUBREDDITS: list[str] = [
    "Denmark",
    "danish",
    "copenhagen",
    "aarhus",
]
"""Default subreddits to monitor for Danish public discourse.

These are English-language subreddits used by the Danish Reddit community.
The Reddit arena may extend this list via query-design-level configuration,
but these four are always included for Danish collection runs.
"""

# ---------------------------------------------------------------------------
# Google Search / Autocomplete
# ---------------------------------------------------------------------------

DANISH_GOOGLE_PARAMS: dict[str, str] = {
    "gl": "dk",   # Geolocation: Denmark
    "hl": "da",   # Host language: Danish
}
"""Query parameters appended to all Google Search and Google Autocomplete requests.

Must be included on every request to ensure results reflect the Danish media
landscape rather than a generic international result set.  Both Serper.dev and
SerpAPI honour these standard Google parameters.
"""

# ---------------------------------------------------------------------------
# GDELT
# ---------------------------------------------------------------------------

GDELT_DANISH_FILTERS: dict[str, str] = {
    "sourcelang": "danish",
    "sourcecountry": "DA",
}
"""GDELT DOC API filter parameters for Danish-language content.

``sourcelang`` uses GDELT's own language identifiers (lowercase, full word).
``sourcecountry`` uses FIPS 10-4 two-letter country codes (``DA`` = Denmark).

See: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
"""

# ---------------------------------------------------------------------------
# Bluesky
# ---------------------------------------------------------------------------

BLUESKY_DANISH_FILTER: str = "lang:da"
"""Language filter string applied to Bluesky AT Protocol ``searchPosts`` queries.

Appended to search queries to restrict results to posts written in Danish.
Example combined query: ``klimaforandringer lang:da``
"""

# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------

YOUTUBE_DANISH_PARAMS: dict[str, str] = {
    "relevanceLanguage": "da",
    "regionCode": "DK",
}
"""Query parameters for the YouTube Data API v3 search endpoint.

``relevanceLanguage``: Instructs the API to return results most relevant to
Danish-speaking users.
``regionCode``: Restricts the result set to content available in Denmark,
applying regional content policies.

These are passed to the ``search.list`` method of the YouTube Data API v3.
"""

# ---------------------------------------------------------------------------
# PostgreSQL full-text search
# ---------------------------------------------------------------------------

POSTGRES_FTS_LANGUAGE: str = "danish"
"""PostgreSQL text search configuration name for Danish.

Used in ``to_tsvector`` and ``to_tsquery`` calls throughout the application::

    to_tsvector('danish', coalesce(text_content, '') || ' ' || coalesce(title, ''))

The ``danish`` configuration applies a Danish snowball stemmer and stop-word list
from the PostgreSQL ``pg_catalog`` — no additional extensions are required.
This matches the GIN index definition on ``content_records`` in the initial
Alembic migration.
"""

# ---------------------------------------------------------------------------
# Via Ritzau press release API
# ---------------------------------------------------------------------------

VIA_RITZAU_API_BASE: str = "https://via.ritzau.dk/json/v2/releases"
"""Base URL for the Via Ritzau REST API v2 (free, unauthenticated).

Supports filtering by publisher, keyword, channel, and language.
Language values accepted: ``da`` (Danish), ``en`` (English), ``fi`` (Finnish),
``no`` (Norwegian), ``sv`` (Swedish).

This is the only free, programmatic access path to Ritzau content available
without a media-house subscription.
"""

VIA_RITZAU_DEFAULT_LANGUAGE: str = "da"
"""Default language filter for Via Ritzau press release queries."""

# ---------------------------------------------------------------------------
# GDPR / pseudonymization
# ---------------------------------------------------------------------------

PSEUDONYMIZATION_SALT_ENV_VAR: str = "PSEUDONYMIZATION_SALT"
"""Name of the environment variable that supplies the pseudonymization salt.

Referenced by :mod:`issue_observatory.core.normalizer` when loading the salt
at construction time.  Centralising the env var name here avoids magic strings
scattered across the codebase.
"""

# ---------------------------------------------------------------------------
# PostgreSQL full-text search
# ---------------------------------------------------------------------------

FULL_TEXT_SEARCH_CONFIG: str = "danish"
"""PostgreSQL text-search configuration name for Danish.

Alias for :data:`POSTGRES_FTS_LANGUAGE` using the name referenced by the
task specification.  Both constants resolve to the same value; prefer
:data:`POSTGRES_FTS_LANGUAGE` in new code that imports from this module
directly.
"""

# ---------------------------------------------------------------------------
# Bluesky language filter (simple string form)
# ---------------------------------------------------------------------------

BLUESKY_LANG_FILTER: str = "da"
"""BCP 47 language tag used to filter Bluesky posts to Danish.

This is the bare language code (``"da"``) used when the arena constructs
the ``lang`` parameter directly.  :data:`BLUESKY_DANISH_FILTER` contains the
full ``lang:da`` query suffix for appending to free-text queries.
"""
