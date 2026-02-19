"""Internal helper functions for the URL Scraper arena collector.

This module contains:
- URL normalization and deduplication
- Publication date extraction (trafilatura metadata, Last-Modified header)
- Domain name extraction
- Searchable-text builder for client-side term matching

All functions in this module are pure (no I/O) except where noted.
They are internal to the ``url_scraper`` arena and should not be imported
by other arenas.
"""

from __future__ import annotations

import email.utils
import urllib.parse
from datetime import datetime, timezone
from typing import Any

from issue_observatory.arenas.web.url_scraper.config import TRACKING_PARAMS
from issue_observatory.scraper.content_extractor import ExtractedContent


# ---------------------------------------------------------------------------
# Domain utilities
# ---------------------------------------------------------------------------


def extract_domain(url: str) -> str:
    """Return the bare hostname from *url*, stripping the ``www.`` prefix.

    Args:
        url: Absolute URL string.

    Returns:
        Lowercase hostname with ``www.`` stripped, or the full netloc on
        parse failure.
    """
    try:
        netloc = urllib.parse.urlparse(url).netloc.lower()
        return netloc.removeprefix("www.")
    except Exception:  # noqa: BLE001
        return url


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------


def normalize_url(url: str) -> str:
    """Normalize a URL for deduplication purposes.

    Performs the following transformations in order:

    1. Lowercase the scheme and hostname.
    2. Strip trailing slash from the path (root ``/`` is preserved).
    3. Remove known tracking query parameters (UTM, fbclid, gclid, etc.).

    Args:
        url: Raw URL string.

    Returns:
        Normalized URL string suitable for deduplication.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/") or "/"
        qs_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        filtered_qs = [(k, v) for k, v in qs_pairs if k not in TRACKING_PARAMS]
        new_query = urllib.parse.urlencode(filtered_qs)
        return urllib.parse.urlunparse(
            (parsed.scheme, netloc, path, parsed.params, new_query, "")
        )
    except Exception:  # noqa: BLE001
        return url


def deduplicate_urls(urls: list[str]) -> list[str]:
    """Deduplicate a list of URLs after normalization.

    Preserves first-occurrence order.  URLs that normalize to the same
    canonical form are deduplicated — only the first occurrence is retained.

    Args:
        urls: Raw list of URLs, possibly containing duplicates.

    Returns:
        Deduplicated list in original-occurrence order.
    """
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        key = normalize_url(url)
        if key not in seen:
            seen.add(key)
            result.append(url)
    return result


# ---------------------------------------------------------------------------
# Publication date extraction
# ---------------------------------------------------------------------------


def parse_date_from_trafilatura(html: str, url: str) -> datetime | None:
    """Extract the publication date from page HTML via trafilatura metadata.

    Uses ``trafilatura.extract_metadata()`` which parses Open Graph
    ``article:published_time``, ``<meta name="date">``, JSON-LD
    ``datePublished``, and visible date patterns in the body text.

    Args:
        html: Raw HTML string.
        url: Canonical page URL (passed to trafilatura for heuristics).

    Returns:
        Timezone-aware :class:`datetime` in UTC, or ``None`` if no date
        could be detected.
    """
    try:
        import trafilatura  # type: ignore[import-untyped]

        meta = trafilatura.extract_metadata(html, default_url=url)
        if meta and getattr(meta, "date", None):
            date_str: str = meta.date
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
                try:
                    dt = datetime.strptime(date_str, fmt)
                    return dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
    except Exception:  # noqa: BLE001
        pass
    return None


def parse_last_modified_header(header_value: str) -> datetime | None:
    """Parse an HTTP ``Last-Modified`` header into a timezone-aware datetime.

    Uses :func:`email.utils.parsedate_to_datetime` which handles all RFC 2822
    date format variants.

    Args:
        header_value: Raw ``Last-Modified`` header string.

    Returns:
        Timezone-aware :class:`datetime` in UTC, or ``None`` on parse failure.
    """
    try:
        parsed = email.utils.parsedate_to_datetime(header_value)
        return parsed.astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def resolve_published_at(
    html: str | None,
    url: str,
    last_modified_header: str | None,
) -> datetime:
    """Resolve the best available publication date with fallback chain.

    Priority order (highest to lowest):

    1. ``trafilatura.extract_metadata().date`` — parses structured and
       visible date signals in the HTML.
    2. HTTP ``Last-Modified`` response header (a weak proxy for publish date).
    3. Current UTC time — collection timestamp as the final fallback.

    Args:
        html: Raw HTML string, or ``None`` if the fetch failed.
        url: Page URL (for trafilatura heuristics).
        last_modified_header: Raw ``Last-Modified`` header value, or ``None``.

    Returns:
        Timezone-aware :class:`datetime` representing the best available
        publication date estimate.
    """
    if html:
        trafilatura_date = parse_date_from_trafilatura(html, url)
        if trafilatura_date is not None:
            return trafilatura_date

    if last_modified_header:
        lm_date = parse_last_modified_header(last_modified_header)
        if lm_date is not None:
            return lm_date

    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Term matching
# ---------------------------------------------------------------------------


def build_searchable_text(raw: dict[str, Any]) -> str:
    """Build a lowercase searchable string from a fetch record's extracted content.

    Concatenates the extracted title and text content (both lowercased) so
    that client-side term matching can check both fields in one pass.

    Args:
        raw: Raw fetch record dict produced by
            :meth:`~.collector.UrlScraperCollector._fetch_single_url`.

    Returns:
        Lowercased concatenation of title and text content.  Empty string
        if neither is available.
    """
    parts: list[str] = []
    extracted: ExtractedContent | None = raw.get("extracted")
    if extracted:
        if extracted.title:
            parts.append(extracted.title)
        if extracted.text:
            parts.append(extracted.text)
    return " ".join(parts).lower()
