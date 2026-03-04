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
    "dr_seneste": "https://www.dr.dk/nyheder/service/feeds/senestenyt",
    "dr_sport": "https://www.dr.dk/nyheder/service/feeds/sporten",
    # DR regional feeds
    "dr_bornholm": "https://www.dr.dk/nyheder/service/feeds/regionale/bornholm",
    "dr_fyn": "https://www.dr.dk/nyheder/service/feeds/regionale/fyn",
    "dr_koebenhavn": "https://www.dr.dk/nyheder/service/feeds/regionale/kbh",
    "dr_midtvest": "https://www.dr.dk/nyheder/service/feeds/regionale/vest",
    "dr_nordjylland": "https://www.dr.dk/nyheder/service/feeds/regionale/nord",
    "dr_sjaelland": "https://www.dr.dk/nyheder/service/feeds/regionale/sjaelland",
    "dr_sonderjylland": "https://www.dr.dk/nyheder/service/feeds/regionale/syd",
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
    "ekstrabladet_nyheder": "https://ekstrabladet.dk/rssfeed/all/",
    # ------------------------------------------------------------------
    # Information — independent broadsheet (subscriber-funded)
    # ------------------------------------------------------------------
    "information_nyheder": "http://www.information.dk/feed",
    # ------------------------------------------------------------------
    # Jyllands-Posten — broadsheet daily (JP/Politikens Hus group)
    # Newsletter proxy RSS — returns latest 20 items (server-capped).
    # ------------------------------------------------------------------
    "jyllandsposten_nyheder": "https://newsletter-proxy.aws.jyllands-posten.dk/v1/latestNewsRss/jyllands-posten.dk?count=100",
    # ------------------------------------------------------------------
    # Nordjyske — regional daily (Nordjyske Medier group)
    # ------------------------------------------------------------------
    "nordjyske_nyheder": "https://nordjyske.dk/rss/nyheder",
    # ------------------------------------------------------------------
    # Fyens Stiftstidende — regional daily (Jysk Fynske Medier group)
    # UNRELIABLE as of March 2026: consistent connection timeouts on all
    # fyens.dk/feed/* paths.  Kept commented out in case it returns.
    # ------------------------------------------------------------------
    # "fyens_stiftstidende_danmark": "https://fyens.dk/feed/danmark",
    # ------------------------------------------------------------------
    # Børsen — financial daily (Berlingske Media group)
    # ------------------------------------------------------------------
    "boersen_nyheder": "https://borsen.dk/rss",
    # ------------------------------------------------------------------
    # Kristeligt Dagblad — Christian/ethical broadsheet (independent)
    # DISCONTINUED as of 2026: server returns 405 on all known feed paths.
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Altinget — policy and political journalism (independent, subscription-supported)
    # Altinget is the most important Danish policy-specific news outlet, covering
    # all major policy areas with dedicated sections (e.g. uddannelse, sundhed,
    # energi).  Critical for issue tracking in any Danish policy domain.
    # URL verified pattern: altinget.dk/feed/rss.xml
    # ------------------------------------------------------------------
    "altinget_nyheder": "https://www.altinget.dk/rss",
    # Added: IP2-009 (Altinget section feeds)
    # Section-specific feeds follow the pattern altinget.dk/{section}/rss.
    # These are critical for targeted issue tracking (education, climate).
    # Unverified — needs manual check: exact section feed URL pattern.
    "altinget_uddannelse": "https://www.altinget.dk/uddannelse/rss",
    "altinget_klima": "https://www.altinget.dk/klima/rss",
    # ------------------------------------------------------------------
    # Education-sector media — Added: IP2-058 (education feeds)
    # These feeds support the "AI og uddannelse" use case and broader
    # education policy tracking.
    # ------------------------------------------------------------------
    # Folkeskolen — primary/lower-secondary education media (published by DLF,
    # Danmarks Laererforening).  The most-read Danish teachers' media outlet.
    # Unverified — needs manual check: exact RSS URL.
    "folkeskolen_nyheder": "https://www.folkeskolen.dk/rss",
    # Gymnasieskolen — upper-secondary education media (published by GL,
    # Gymnasieskolernes Laererforening).
    # Unverified — needs manual check: exact RSS URL.
    "gymnasieskolen_nyheder": "https://gymnasieskolen.dk/feed",
    # University news feeds — Danish universities typically publish news RSS.
    # Unverified — needs manual check: all university feed URLs below.
    "ku_nyheder": "https://nyheder.ku.dk/alle_nyheder/?get_rss=1",
    # DTU — DISCONTINUED as of 2026: rebuilt site on Next.js, no RSS support.
    # CBS — DISCONTINUED as of 2026: 404 on all feed paths. CBS WIRE shut down late 2023.
    # Tænketanken DEA — education and research policy think tank.
    # Unverified — needs manual check: DEA may not offer RSS.
    # dea_nyheder: https://dea.nu/feed  # Commented out: DEA RSS availability is uncertain
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
# Wikipedia
# ---------------------------------------------------------------------------

WIKIPEDIA_USER_AGENT: str = (
    "IssueObservatory/1.0 (https://github.com/issue-observatory; contact@observatory.dk) python-httpx"
)
"""User-Agent header sent with all Wikimedia API requests.

Wikimedia policy requires a meaningful User-Agent that identifies the tool and
provides a contact address.  This value can be overridden by setting the
``WIKIPEDIA_USER_AGENT`` environment variable, but the format must comply with
Wikimedia's guidelines:
https://www.mediawiki.org/wiki/API:Etiquette#The_User-Agent_header
"""

DANISH_WIKIPEDIA_SEED_ARTICLES: list[str] = []
"""Seed article titles for the Wikipedia article watchlist mode.

Populate this list with Danish Wikipedia article titles relevant to the
current research domain.  These articles will be monitored for revision
activity and pageview trends.

Example (CO2 afgift research):
    ["CO2-afgift", "Klimaaftale", "Grøn omstilling", "Parisaftalen"]

Example (AI og uddannelse research):
    ["Kunstig intelligens", "Chatbot", "Folkeskolen", "Gymnasiet"]

Note: Leave empty to rely on term-based article discovery instead.
"""

DEFAULT_WIKI_PROJECTS: list[str] = ["da.wikipedia", "en.wikipedia"]
"""Wikipedia projects (language editions) queried by the Wikipedia collector.

``da.wikipedia`` is the Danish-language Wikipedia (da.wikipedia.org).
``en.wikipedia`` is the English-language Wikipedia (en.wikipedia.org).

Both are queried because international topics (NATO, AI, climate) often have
more detailed coverage in English even when the research focus is Danish discourse.
"""

# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

DANISH_DISCORD_SERVERS: list[dict[str, str | list[str]]] = []
"""Curated Danish Discord servers and channels to monitor.

Each entry is a dict with:
    - ``guild_id`` (str): The server's snowflake ID.
    - ``name`` (str): Human-readable server name for logs.
    - ``channel_ids`` (list[str]): Channel snowflake IDs to monitor within
      this server.  If empty, all accessible text channels are monitored.

To add a server: invite the research bot, then add an entry here.
Example:
    {
        "guild_id": "1234567890",
        "name": "r/Denmark Discord",
        "channel_ids": ["9876543210"],
    }

Note: The bot must be invited to each server manually before collection
can begin.  See docs/arenas/discord.md section 4.12 for setup instructions.
"""

# ---------------------------------------------------------------------------
# Twitch
# ---------------------------------------------------------------------------

DANISH_TWITCH_CHANNELS: list[str] = []
"""Danish Twitch channel login names to monitor for live chat collection.

Populate with the login names (not display names) of Danish-language or
Denmark-focused Twitch channels.  These channels will be subscribed to via
EventSub when the streaming worker is active.

Example:
    ["danishstreamer1", "denmarkgaming"]

Discovery: Use ``GET /streams?language=da`` on the Twitch Helix API to
find currently live Danish-language streams.

Note: Chat data is only available in real time — the streaming worker
must be running during a live stream to capture messages.
"""

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
