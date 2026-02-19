"""Arena registry for dynamic discovery and registration of collectors.

Arenas register themselves on import using the ``@register`` decorator.
The registry is a module-level singleton that maps ``platform_name`` strings
to ``ArenaCollector`` subclasses.

Registry key design
-------------------
The registry is keyed by **``platform_name``**, not ``arena_name``.
``arena_name`` is a logical *grouping* label (e.g. ``"social_media"``,
``"news_media"``, ``"web"``) shared by multiple collectors on the same
logical arena tier.  ``platform_name`` is the unique per-collector
identifier (e.g. ``"reddit"``, ``"youtube"``, ``"wayback"``).  Keying by
``arena_name`` causes registry collisions when multiple collectors share
the same logical arena.

Example — registering an arena::

    from issue_observatory.arenas.registry import register
    from issue_observatory.arenas.base import ArenaCollector, Tier

    @register
    class BlueskyCollector(ArenaCollector):
        arena_name = "bluesky"
        platform_name = "bluesky"
        supported_tiers = [Tier.FREE]
        ...

Example — looking up a collector::

    from issue_observatory.arenas.registry import get_arena, list_arenas

    cls = get_arena("bluesky")   # look up by platform_name
    collector = cls()

    all_arenas = list_arenas()
    # [{"arena_name": "social_media", "platform_name": "reddit", ...}, ...]
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from issue_observatory.arenas.base import ArenaCollector

logger = logging.getLogger(__name__)

# Registry singleton: platform_name -> ArenaCollector subclass
#
# Keyed by platform_name (unique per collector) rather than arena_name
# (which is a shared logical grouping label used by multiple collectors).
# Multiple collectors may share the same arena_name (e.g. "social_media"
# is shared by Reddit, YouTube, Telegram, TikTok, Gab, X/Twitter, Threads,
# Facebook, and Instagram), so keying by arena_name causes silent
# last-import-wins collisions that drop earlier registrations from the
# registry entirely.
_REGISTRY: dict[str, type[ArenaCollector]] = {}

# ---------------------------------------------------------------------------
# Arena descriptions
#
# Human-readable one-liner for each registered arena, keyed by arena_name.
# Used by the GET /api/arenas/ endpoint to enrich the arena list returned to
# the frontend.  Add an entry here whenever a new arena is registered.
# ---------------------------------------------------------------------------

ARENA_DESCRIPTIONS: dict[str, str] = {
    # Keyed by platform_name (unique per collector).
    # Fallback lookup also checks arena_name grouping labels below.
    "openrouter": (
        "AI chat interface search (OpenRouter) capturing LLM-cited web sources"
    ),
    "bluesky": (
        "Decentralised social network (AT Protocol) with Danish academic and political presence"
    ),
    "event_registry": (
        "Global news aggregator (Event Registry) with strong Danish media coverage"
    ),
    "facebook": (
        "Facebook public posts via third-party scraping API (paid tiers only)"
    ),
    "gab": (
        "Far-right social platform; public posts collected via unauthenticated API"
    ),
    "gdelt": (
        "GDELT global event database — open dataset of news mentions worldwide"
    ),
    # "google" as platform_name is not used by any collector.
    # Both Google collectors use distinct platform_names (google_search,
    # google_autocomplete).  Kept as a fallback for any ad-hoc lookups.
    "google": (
        "Google services (see google_search and google_autocomplete for specific collectors)"
    ),
    "google_autocomplete": (
        "Google Autocomplete suggestions revealing real-time public search intent"
    ),
    "google_search": (
        "Google Search organic results via Serper.dev (medium) or SerpAPI (premium)"
    ),
    "instagram": (
        "Instagram public posts via third-party scraping API (paid tiers only)"
    ),
    "majestic": (
        "Majestic backlink index — maps web authority and citation networks (premium)"
    ),
    "reddit": (
        "Reddit posts and comments from Danish-language subreddits (r/Denmark, etc.)"
    ),
    "ritzau_via": (
        "Ritzau Via — Danish news-wire aggregator providing press-release content"
    ),
    "rss_feeds": (
        "Danish RSS feeds from DR, TV2, Politiken, Berlingske, and other major outlets"
    ),
    "telegram": (
        "Telegram public channels collected via Telegram MTProto API"
    ),
    "threads": (
        "Threads (Meta) public posts via unofficial API (free/medium tiers)"
    ),
    "tiktok": (
        "TikTok public videos collected via unofficial scraping API"
    ),
    "common_crawl": (
        "Common Crawl open web archive — petabyte-scale crawl dataset (free)"
    ),
    "url_scraper": (
        "URL Scraper — live web page content extraction from a researcher-provided URL list (free/medium)"
    ),
    "wayback": (
        "Wayback Machine (Internet Archive) — historical web snapshots (free)"
    ),
    "x_twitter": (
        "X/Twitter posts via third-party API providers (paid tiers only)"
    ),
    "youtube": (
        "YouTube videos and comments via Data API v3 (free quota)"
    ),
    # Phase 2.5 / 3+ / Future arenas
    "wikipedia": (
        "Wikipedia editorial attention signals: revision history, talk page activity, and pageview statistics"
    ),
    "discord": (
        "Discord server messages from curated Danish community servers (bot-based collection)"
    ),
    "twitch": (
        "Twitch live stream chat messages captured in real time via EventSub (deferred — streaming-only)"
    ),
    "vkontakte": (
        "VKontakte (VK) public posts and community content (deferred — pending legal review)"
    ),
    # Arena grouping labels kept as fallback keys for ARENA_DESCRIPTIONS.get()
    # calls that still use arena_name.  These are not registry keys.
    "ai_chat_search": (
        "AI chat interface search (OpenRouter) capturing LLM-cited web sources"
    ),
    "news_media": (
        "General news-media arena (used by ritzau_via and event_registry collectors)"
    ),
    "reference": (
        "Reference and encyclopedic sources (Wikipedia, Wikidata) tracking editorial attention"
    ),
    "social_media": (
        "Social media arena grouping Reddit, YouTube, Bluesky, Telegram, TikTok, etc."
    ),
    "web": (
        "Open web archive arena grouping Common Crawl and Wayback Machine collectors"
    ),
}


def register(cls: type[ArenaCollector]) -> type[ArenaCollector]:
    """Decorator that registers an ``ArenaCollector`` subclass in the global registry.

    The class must define both ``arena_name`` and ``platform_name`` as
    class-level string attributes.  The registry is keyed by
    **``platform_name``** (unique per collector) so that multiple collectors
    sharing the same ``arena_name`` grouping label (e.g. ``"social_media"``)
    do not overwrite each other.

    If a collector with the same ``platform_name`` has already been registered,
    the new registration overwrites the old one and a warning is emitted.

    Args:
        cls: ``ArenaCollector`` subclass to register.

    Returns:
        The same class (decorator pass-through), enabling normal class
        definition syntax.

    Raises:
        AttributeError: If ``cls`` does not define ``platform_name`` or
            ``arena_name``.

    Example::

        @register
        class MyCollector(ArenaCollector):
            arena_name = "social_media"   # logical grouping label
            platform_name = "my_platform" # unique registry key
            ...
    """
    platform_name: str = cls.platform_name  # type: ignore[attr-defined]
    arena_name: str = cls.arena_name  # type: ignore[attr-defined]
    if platform_name in _REGISTRY:
        logger.warning(
            "Platform '%s' (arena '%s') is already registered (was %s). Overwriting with %s.",
            platform_name,
            arena_name,
            _REGISTRY[platform_name].__qualname__,
            cls.__qualname__,
        )
    _REGISTRY[platform_name] = cls
    logger.debug(
        "Registered arena collector: platform=%s arena=%s class=%s",
        platform_name,
        arena_name,
        cls.__qualname__,
    )
    return cls


def get_arena(platform_name: str) -> type[ArenaCollector]:
    """Retrieve a registered ``ArenaCollector`` class by platform name.

    The registry is keyed by ``platform_name`` (e.g. ``"reddit"``,
    ``"youtube"``, ``"wayback"``), not by the logical ``arena_name``
    grouping label (e.g. ``"social_media"``).

    Args:
        platform_name: The ``platform_name`` class attribute value to look
            up (e.g. ``"google_search"``, ``"bluesky"``, ``"reddit"``).

    Returns:
        The ``ArenaCollector`` subclass registered under *platform_name*.

    Raises:
        KeyError: If no collector with the given platform name is registered.
            Callers should call ``autodiscover()`` before their first lookup
            if registration may not have happened yet.
    """
    try:
        return _REGISTRY[platform_name]
    except KeyError:
        registered = sorted(_REGISTRY.keys())
        raise KeyError(
            f"No collector registered for platform '{platform_name}'. "
            f"Registered platforms: {registered}. "
            "Did you forget to call autodiscover() or import the collector module?"
        ) from None


def get_arenas_by_arena_name(arena_name: str) -> list[type[ArenaCollector]]:
    """Retrieve all registered collectors belonging to a logical arena group.

    Multiple collectors may share the same ``arena_name`` grouping label
    (e.g. ``"social_media"`` is shared by Reddit, YouTube, Telegram, etc.).
    This function returns all of them.

    Args:
        arena_name: The ``arena_name`` class attribute value to match
            (e.g. ``"social_media"``, ``"news_media"``, ``"web"``).

    Returns:
        List of ``ArenaCollector`` subclasses whose ``arena_name`` matches.
        Empty list if no collectors are registered for that arena group.
    """
    return [
        cls
        for cls in _REGISTRY.values()
        if cls.arena_name == arena_name  # type: ignore[attr-defined]
    ]


def list_arenas() -> list[dict]:  # type: ignore[type-arg]
    """Return metadata for all registered arena collectors.

    The list is ordered first by ``arena_name`` (logical grouping) then by
    ``platform_name`` (unique platform), so related arenas appear together.
    One entry is returned per distinct registered collector class — there is
    no deduplication because the registry is keyed by ``platform_name``.

    This output is used by the collection launcher's arena configuration grid
    and by the admin health dashboard (``GET /api/arenas/``).

    Returns:
        List of dicts, each containing:

        - ``arena_name`` (str): Logical arena group label
          (e.g. ``"social_media"``, ``"news_media"``).
        - ``platform_name`` (str): Unique platform identifier used as the
          registry key (e.g. ``"reddit"``, ``"youtube"``).
        - ``supported_tiers`` (list[str]): Tier values the collector supports.
        - ``description`` (str): One-line human-readable description from
          :data:`ARENA_DESCRIPTIONS`, looked up first by ``platform_name``
          then by ``arena_name`` (empty string if neither is defined).
        - ``collector_class`` (str): Fully qualified class name (for debugging).
    """
    return [
        {
            "arena_name": cls.arena_name,  # type: ignore[attr-defined]
            "platform_name": cls.platform_name,  # type: ignore[attr-defined]
            "supported_tiers": [
                t.value for t in cls.supported_tiers  # type: ignore[attr-defined]
            ],
            "description": (
                ARENA_DESCRIPTIONS.get(cls.platform_name)  # type: ignore[attr-defined]
                or ARENA_DESCRIPTIONS.get(cls.arena_name, "")  # type: ignore[attr-defined]
            ),
            "collector_class": f"{cls.__module__}.{cls.__qualname__}",
        }
        for cls in sorted(
            _REGISTRY.values(),
            key=lambda c: (c.arena_name, c.platform_name),  # type: ignore[attr-defined]
        )
    ]


def autodiscover() -> None:
    """Import all arena ``collector`` modules to trigger ``@register`` decorators.

    This walks the ``issue_observatory.arenas`` package tree and imports
    every submodule named ``collector``. Arenas that use the ``@register``
    decorator will be added to the registry on import.

    This function is idempotent — calling it multiple times is safe.

    Raises:
        ImportError: If an individual collector module fails to import.
            Other arenas continue to load; the error is logged.
    """
    import issue_observatory.arenas as arenas_pkg

    arenas_path = arenas_pkg.__path__
    arenas_prefix = arenas_pkg.__name__ + "."

    for finder, module_name, is_pkg in pkgutil.walk_packages(
        path=arenas_path, prefix=arenas_prefix
    ):
        if module_name.endswith(".collector"):
            try:
                importlib.import_module(module_name)
                logger.debug("Autodiscovered arena module: %s", module_name)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Failed to import arena collector module '%s': %s",
                    module_name,
                    exc,
                    exc_info=True,
                )
