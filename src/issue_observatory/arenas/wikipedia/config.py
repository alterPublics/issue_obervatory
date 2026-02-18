"""Configuration for the Wikipedia arena.

Defines tier settings, API base URLs, and collection constants used by
:class:`~issue_observatory.arenas.wikipedia.collector.WikipediaCollector`.

Wikipedia is a **free-only arena** — the MediaWiki Action API and the
Wikimedia Analytics API are fully open, with no paid tier and no API key
requirement.  The only obligation is a descriptive ``User-Agent`` header.

Rate-limit policy:
    Wikimedia requests automated tools stay below ~200 req/s.  We target
    5 req/s (``WIKIPEDIA_RATE_LIMIT_PER_SECOND``) as a polite baseline,
    enforced via ``asyncio.Semaphore(5)`` inside the collector.
"""

from __future__ import annotations

from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

WIKIPEDIA_TIERS: dict[Tier, TierConfig] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=5_000,
        rate_limit_per_minute=300,  # 5 req/s * 60 = 300 req/min
        requires_credential=False,
        estimated_credits_per_1k=0,
    ),
}
"""Tier definitions for the Wikipedia arena.

Only FREE is supported.  Wikipedia APIs are unauthenticated; no credential
pool entry is created.
"""

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

WIKIPEDIA_RATE_LIMIT_PER_SECOND: float = 5.0
"""Target request rate to stay within Wikimedia's polite-use guidelines."""

WIKIPEDIA_RATE_LIMIT_WINDOW_SECONDS: int = 1
"""Rolling window (in seconds) for the per-second rate limit."""

# ---------------------------------------------------------------------------
# Wiki project configuration
# ---------------------------------------------------------------------------

DEFAULT_WIKI_PROJECTS: list[str] = ["da.wikipedia", "en.wikipedia"]
"""Default list of wiki projects to query.

``da.wikipedia`` targets the Danish Wikipedia (290 000+ articles relevant to
Danish public discourse).  ``en.wikipedia`` is included by default for topics
with international dimensions.  Both map to the format ``{project}.org``.
"""

# ---------------------------------------------------------------------------
# API base URLs
# ---------------------------------------------------------------------------

MEDIAWIKI_ACTION_API_BASE: str = "https://{project}.org/w/api.php"
"""MediaWiki Action API base URL template.

Replace ``{project}`` with ``da.wikipedia`` or ``en.wikipedia`` to produce
the full endpoint, e.g. ``https://da.wikipedia.org/w/api.php``.
"""

WIKIMEDIA_PAGEVIEWS_API_BASE: str = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
"""Wikimedia Analytics Pageviews REST API base URL.

Pageview data is available from July 2015 onward with daily granularity.
Data populates with approximately a 24-hour delay.
"""

# ---------------------------------------------------------------------------
# Collection defaults
# ---------------------------------------------------------------------------

DEFAULT_MAX_RESULTS: int = 500
"""Default upper bound on returned records per collection call."""

DEFAULT_RECENT_CHANGES_LIMIT: int = 500
"""Maximum revisions to request per MediaWiki API call (API hard cap = 500)."""

# ---------------------------------------------------------------------------
# Edit filtering
# ---------------------------------------------------------------------------

INCLUDE_BOT_EDITS: bool = False
"""Whether to include bot-tagged edits in revision results.

Setting this to ``False`` (the default) filters out edits whose ``tags``
list contains bot-related markers (e.g. ``mw-bot``, ``OAuth CID:...``).
Bot edits inflate edit counts without reflecting human editorial attention.
"""

# ---------------------------------------------------------------------------
# Pageview options
# ---------------------------------------------------------------------------

INCLUDE_PAGEVIEWS: bool = True
"""Whether to fetch pageview data for each discovered article."""

PAGEVIEW_ACCESS: str = "all-access"
"""Wikimedia pageview ``access`` parameter.

``"all-access"`` aggregates desktop, mobile-web, and mobile-app traffic.
Alternatives: ``"desktop"``, ``"mobile-web"``, ``"mobile-app"``.
"""

PAGEVIEW_AGENT: str = "user"
"""Wikimedia pageview ``agent`` parameter.

``"user"`` filters out most automated/bot traffic, returning only estimated
human pageviews.  Alternatives: ``"bot"``, ``"all-agents"``.
"""

PAGEVIEW_GRANULARITY: str = "daily"
"""Wikimedia pageview ``granularity`` parameter.

``"daily"`` is the most granular option and best suited for tracking
day-by-day attention spikes.  Alternative: ``"monthly"``.
"""

# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

DEFAULT_USER_AGENT: str = (
    "IssueObservatory/1.0 (research tool; contact@observatory.dk) python-httpx"
)
"""User-Agent string sent on every Wikimedia API request.

Wikimedia's API etiquette guidelines require a meaningful User-Agent that
identifies the tool and provides a contact address.  Requests without a
descriptive User-Agent may be throttled or blocked.
"""
