"""RSS/Atom feed autodiscovery from website URLs.

Provides utilities for discovering RSS and Atom feeds given a website URL.
Supports:
- Parsing HTML ``<link rel="alternate">`` tags with RSS/Atom content types
- Probing common feed path patterns (``/rss``, ``/feed``, ``/atom.xml``, etc.)
- Content-type verification to ensure discovered URLs are actually feeds

Used by the ``POST /query-designs/{id}/discover-feeds`` endpoint (SB-09) to
help researchers quickly find and add new Danish RSS feeds to their query
design configuration.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from issue_observatory.core.exceptions import ArenaCollectionError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Common feed path patterns to probe when no <link> tags are found.
COMMON_FEED_PATHS: list[str] = [
    "/rss",
    "/rss.xml",
    "/feed",
    "/feed.xml",
    "/atom.xml",
    "/feeds/posts/default",  # Blogger default
    "/index.xml",  # Hugo default
    "/feed/",
    "/feeds/",
]

#: Content-type prefixes that indicate an RSS or Atom feed.
FEED_CONTENT_TYPES: set[str] = {
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
}

#: Maximum number of HTTP redirects to follow.
MAX_REDIRECTS: int = 5

#: Request timeout in seconds.
REQUEST_TIMEOUT: float = 15.0


# ---------------------------------------------------------------------------
# Feed discovery
# ---------------------------------------------------------------------------


async def discover_feeds(url: str) -> list[dict[str, str]]:
    """Discover RSS/Atom feeds from a website URL.

    Performs the following discovery steps:
    1. Fetch the page HTML with a reasonable timeout (15 seconds).
    2. Parse ``<link rel="alternate" type="application/rss+xml">`` and
       ``<link rel="alternate" type="application/atom+xml">`` tags.
    3. If no link tags are found, probe common feed path patterns
       (``/rss``, ``/feed``, ``/atom.xml``, etc.) with HEAD requests.
    4. Return a list of discovered feed URLs with titles.

    Args:
        url: Website URL to discover feeds from.  Must be a valid HTTP(S) URL.

    Returns:
        List of dicts, each with keys:
        - ``url`` (str): Absolute feed URL.
        - ``title`` (str): Feed title extracted from the ``<link>`` tag's
          ``title`` attribute, or derived from the URL path if not available.
        - ``feed_type`` (str): ``"rss"`` or ``"atom"`` based on the declared
          content type or discovered path pattern.

        Returns an empty list when no feeds are found.

    Raises:
        ArenaCollectionError: On request timeout, invalid URL, or connection
            failure.
    """
    # Normalize URL — add scheme if missing
    parsed = urlparse(url)
    if not parsed.scheme:
        url = f"https://{url}"
        parsed = urlparse(url)

    base_url = f"{parsed.scheme}://{parsed.netloc}"

    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
    ) as client:
        # Step 1: Fetch page HTML
        try:
            response = await client.get(url, headers={"User-Agent": _user_agent()})
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ArenaCollectionError(
                f"feed_discovery: timeout fetching {url}",
                arena="rss_feeds",
                platform="rss_feeds",
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise ArenaCollectionError(
                f"feed_discovery: HTTP {exc.response.status_code} from {url}",
                arena="rss_feeds",
                platform="rss_feeds",
            ) from exc
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"feed_discovery: connection error fetching {url}: {exc}",
                arena="rss_feeds",
                platform="rss_feeds",
            ) from exc

        # Step 2: Parse <link> tags
        feeds: list[dict[str, str]] = []
        try:
            soup = BeautifulSoup(response.text, "html.parser")
            link_tags = soup.find_all("link", rel="alternate")

            for tag in link_tags:
                if not isinstance(tag, Tag):
                    continue
                content_type: str | None = tag.get("type")
                href: str | None = tag.get("href")
                if not content_type or not href:
                    continue

                # Filter to RSS/Atom content types
                if not any(ct in content_type for ct in FEED_CONTENT_TYPES):
                    continue

                # Resolve relative URLs
                absolute_url = urljoin(base_url, href)

                # Extract title from link tag or derive from URL
                title: str = tag.get("title") or _derive_title_from_url(absolute_url)
                feed_type = _infer_feed_type(content_type, absolute_url)

                feeds.append({"url": absolute_url, "title": title, "feed_type": feed_type})

        except Exception as exc:  # noqa: BLE001
            logger.warning("feed_discovery: failed to parse HTML from %s: %s", url, exc)

        # Step 3: Probe common feed paths if no <link> tags found
        if not feeds:
            logger.debug("feed_discovery: no <link> tags found, probing common paths")
            for path in COMMON_FEED_PATHS:
                probe_url = urljoin(base_url, path)
                if await _probe_feed_url(client, probe_url):
                    feeds.append(
                        {
                            "url": probe_url,
                            "title": _derive_title_from_url(probe_url),
                            "feed_type": _infer_feed_type_from_path(path),
                        }
                    )

        # Deduplicate by URL
        seen_urls: set[str] = set()
        deduplicated: list[dict[str, str]] = []
        for feed in feeds:
            if feed["url"] not in seen_urls:
                seen_urls.add(feed["url"])
                deduplicated.append(feed)

        logger.info(
            "feed_discovery: discovered %d feeds from %s",
            len(deduplicated),
            url,
        )
        return deduplicated


async def _probe_feed_url(client: httpx.AsyncClient, url: str) -> bool:
    """Probe a URL with a HEAD request to verify it's a valid feed.

    Args:
        client: Shared HTTP client.
        url: Absolute URL to probe.

    Returns:
        ``True`` if the URL returns a 200 status and a feed content type.
        ``False`` otherwise.
    """
    try:
        response = await client.head(url, headers={"User-Agent": _user_agent()})
        if response.status_code != 200:
            return False
        content_type = response.headers.get("content-type", "").lower()
        return any(ct in content_type for ct in FEED_CONTENT_TYPES)
    except (httpx.RequestError, httpx.HTTPStatusError):
        return False


def _derive_title_from_url(url: str) -> str:
    """Derive a human-readable feed title from a URL path.

    Args:
        url: Feed URL.

    Returns:
        A title derived from the URL path or domain.
    """
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if path:
        # Use the last path segment as the title
        return path.split("/")[-1].replace("-", " ").replace("_", " ").title()
    return parsed.netloc


def _infer_feed_type(content_type: str, url: str) -> str:
    """Infer whether a feed is RSS or Atom from its content type or URL.

    Args:
        content_type: The declared ``Content-Type`` header or ``<link>`` type.
        url: The feed URL.

    Returns:
        ``"rss"`` or ``"atom"``.
    """
    if "atom" in content_type.lower():
        return "atom"
    if "atom" in url.lower():
        return "atom"
    return "rss"


def _infer_feed_type_from_path(path: str) -> str:
    """Infer whether a feed path pattern is RSS or Atom.

    Args:
        path: Feed path (e.g. ``"/rss"``, ``"/atom.xml"``).

    Returns:
        ``"rss"`` or ``"atom"``.
    """
    if "atom" in path.lower():
        return "atom"
    return "rss"


def _user_agent() -> str:
    """Return a descriptive User-Agent string for feed discovery requests."""
    return "IssueObservatory/1.0 (feed-discovery; +https://github.com/issue-observatory)"
