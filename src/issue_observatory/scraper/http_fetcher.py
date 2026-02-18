"""Async HTTP fetcher with robots.txt support and JS-shell detection.

Uses ``httpx`` for all HTTP requests.  Detects JavaScript-only page shells
(near-empty body) and sets ``needs_playwright=True`` on the result so the
caller can retry with :mod:`issue_observatory.scraper.playwright_fetcher`.
"""

from __future__ import annotations

import logging
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field

import httpx

from issue_observatory.scraper.config import (
    BINARY_CONTENT_TYPES,
    JS_SHELL_BODY_THRESHOLD,
    ROBOTS_USER_AGENT,
    ROBOTS_USER_AGENT_FALLBACK,
    USER_AGENT,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class FetchResult:
    """Result of a single HTTP fetch attempt.

    Attributes:
        html: Raw HTML string, or ``None`` if the fetch failed or was skipped.
        status_code: HTTP status code, or ``None`` on network error.
        final_url: URL after following redirects, or ``None`` on error.
        error: Human-readable error description, or ``None`` on success.
        needs_playwright: ``True`` if the response body appears to be a
            JS-only shell that requires a headless browser retry.
    """

    html: str | None
    status_code: int | None
    final_url: str | None
    error: str | None
    needs_playwright: bool = False


# ---------------------------------------------------------------------------
# robots.txt helpers
# ---------------------------------------------------------------------------


def _is_allowed_by_robots(
    url: str,
    robots_cache: dict[str, bool],
    timeout: int,
) -> bool:
    """Return ``True`` if the URL is allowed by the site's robots.txt.

    Results are cached in ``robots_cache`` keyed by origin (scheme + host).
    On any network / parse error the URL is considered allowed (fail-open).

    Args:
        url: Target URL.
        robots_cache: Mutable dict used as a domain-level TTL-less cache.
        timeout: Seconds to wait when fetching robots.txt.

    Returns:
        ``True`` if allowed (or if the check fails), ``False`` if disallowed.
    """
    parsed = urllib.parse.urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    robots_url = f"{origin}/robots.txt"

    cache_key = f"{origin}:{url}"
    if cache_key in robots_cache:
        return robots_cache[cache_key]

    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)
    try:
        rp.read()
    except Exception as exc:  # noqa: BLE001
        logger.debug("scraper: robots.txt fetch failed for %s: %s — allowing", origin, exc)
        robots_cache[cache_key] = True
        return True

    allowed_primary = rp.can_fetch(ROBOTS_USER_AGENT, url)
    allowed_fallback = rp.can_fetch(ROBOTS_USER_AGENT_FALLBACK, url)
    # If neither agent is explicitly listed, default to allowed.
    allowed = allowed_primary and allowed_fallback
    robots_cache[cache_key] = allowed
    return allowed


# ---------------------------------------------------------------------------
# Binary content-type check
# ---------------------------------------------------------------------------


def _is_binary_content_type(content_type: str) -> bool:
    """Return ``True`` if the Content-Type indicates a non-text binary resource."""
    ct = content_type.lower().split(";")[0].strip()
    return any(ct.startswith(prefix) for prefix in BINARY_CONTENT_TYPES)


# ---------------------------------------------------------------------------
# JS-only shell detection
# ---------------------------------------------------------------------------


def _is_js_shell(html: str) -> bool:
    """Return ``True`` if the page body is too short to contain real content.

    A very short body after stripping whitespace is a strong signal that the
    page requires JavaScript execution to populate its content.

    Args:
        html: Raw HTML string.

    Returns:
        ``True`` if the stripped body length is below the configured threshold.
    """
    return len(html.strip()) < JS_SHELL_BODY_THRESHOLD


# ---------------------------------------------------------------------------
# Public fetch function
# ---------------------------------------------------------------------------


async def fetch_url(
    url: str,
    *,
    client: httpx.AsyncClient,
    timeout: int,
    respect_robots: bool,
    robots_cache: dict[str, bool],
) -> FetchResult:
    """Fetch a single URL using httpx with robots.txt checking.

    Performs the following checks in order:

    1. **robots.txt** — if ``respect_robots`` is ``True``, fetches and caches
       the robots.txt for the URL's origin.  Returns an error result if
       disallowed.
    2. **HTTP GET** — sends a ``GET`` request with a custom user-agent.
       Follows redirects (up to httpx defaults).
    3. **Binary content-type** — returns a skip result for PDFs, images, etc.
    4. **JS-shell detection** — sets ``needs_playwright=True`` on the result
       if the response body is too short to contain real content.

    Args:
        url: Target URL to fetch.
        client: Shared :class:`httpx.AsyncClient` instance.
        timeout: Request timeout in seconds.
        respect_robots: Whether to honour robots.txt disallow rules.
        robots_cache: Mutable dict used as a domain-level robots.txt cache.

    Returns:
        A :class:`FetchResult` instance.
    """
    # 1. robots.txt check
    if respect_robots and not _is_allowed_by_robots(url, robots_cache, timeout):
        logger.info("scraper: robots.txt disallows %s", url)
        return FetchResult(
            html=None,
            status_code=None,
            final_url=url,
            error="robots.txt disallowed",
        )

    # 2. HTTP GET
    try:
        response = await client.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
    except httpx.TimeoutException:
        logger.warning("scraper: timeout fetching %s", url)
        return FetchResult(html=None, status_code=None, final_url=url, error="timeout")
    except httpx.TooManyRedirects:
        logger.warning("scraper: too many redirects for %s", url)
        return FetchResult(
            html=None, status_code=None, final_url=url, error="too many redirects"
        )
    except httpx.RequestError as exc:
        logger.warning("scraper: request error for %s: %s", url, exc)
        return FetchResult(
            html=None, status_code=None, final_url=url, error=f"request error: {exc}"
        )

    final_url = str(response.url)

    # 3. HTTP error status
    if response.status_code >= 400:
        logger.info(
            "scraper: HTTP %d for %s", response.status_code, url
        )
        return FetchResult(
            html=None,
            status_code=response.status_code,
            final_url=final_url,
            error=f"HTTP {response.status_code}",
        )

    # 4. Binary content-type check
    content_type = response.headers.get("content-type", "")
    if _is_binary_content_type(content_type):
        logger.info("scraper: skipping binary content-type '%s' for %s", content_type, url)
        return FetchResult(
            html=None,
            status_code=response.status_code,
            final_url=final_url,
            error=f"binary content-type: {content_type}",
        )

    # Decode response body
    try:
        html = response.text
    except Exception as exc:  # noqa: BLE001
        logger.warning("scraper: decode error for %s: %s", url, exc)
        return FetchResult(
            html=None,
            status_code=response.status_code,
            final_url=final_url,
            error=f"decode error: {exc}",
        )

    # 5. JS-only shell detection
    needs_playwright = _is_js_shell(html)
    if needs_playwright:
        logger.info(
            "scraper: JS-only shell detected for %s (body_len=%d)",
            url,
            len(html.strip()),
        )

    return FetchResult(
        html=html,
        status_code=response.status_code,
        final_url=final_url,
        error=None,
        needs_playwright=needs_playwright,
    )
