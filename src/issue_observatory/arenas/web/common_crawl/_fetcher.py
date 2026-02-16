"""Low-level CC Index API fetching and pagination helpers.

Internal module used by
:class:`~issue_observatory.arenas.web.common_crawl.collector.CommonCrawlCollector`.
Not part of the public arena API.

Provides:
- :func:`fetch_index_page` — fetch one NDJSON page from the CC Index API.
- :func:`format_cc_timestamp` — format datetime values for CC API params.
- :func:`parse_cc_timestamp` — parse CC timestamps to ISO 8601.
- :func:`map_cc_language` — map CC ISO 639-3 codes to ISO 639-1.
- :func:`extract_domain` — extract registered domain from a URL.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from issue_observatory.arenas.web.common_crawl.config import (
    CC_INDEX_BASE_URL,
    CC_MAX_RECORDS_PER_PAGE,
)
from issue_observatory.core.exceptions import ArenaCollectionError, ArenaRateLimitError

logger = logging.getLogger(__name__)

# Arena identifiers for exception messages
_ARENA = "web"
_PLATFORM = "common_crawl"


async def fetch_index_page(
    client: httpx.AsyncClient,
    cc_index: str,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fetch a single page from the CC Index API.

    The CC Index API returns NDJSON (one JSON object per line). Each line is a
    separate capture record. An empty response (no captures) is not an error.

    Args:
        client: Shared async HTTP client.
        cc_index: Common Crawl index identifier (e.g. ``"CC-MAIN-2025-51"``).
        params: Query parameters for the CC Index search endpoint.

    Returns:
        List of raw index entry dicts parsed from the NDJSON response.

    Raises:
        ArenaCollectionError: On non-retryable HTTP errors (5xx).
        ArenaRateLimitError: On HTTP 429.
    """
    search_url = f"{CC_INDEX_BASE_URL}/{cc_index}/search"

    try:
        response = await client.get(search_url, params=params)
    except httpx.RequestError as exc:
        raise ArenaCollectionError(
            f"common_crawl: request error: {exc}",
            arena=_ARENA,
            platform=_PLATFORM,
        ) from exc

    if response.status_code == 404:
        logger.debug("common_crawl: 404 — no captures for params=%s", params)
        return []

    if response.status_code == 429:
        retry_after = float(response.headers.get("Retry-After", 60))
        raise ArenaRateLimitError(
            "common_crawl: HTTP 429 rate limited",
            retry_after=retry_after,
            arena=_ARENA,
            platform=_PLATFORM,
        )

    if response.status_code >= 500:
        raise ArenaCollectionError(
            f"common_crawl: server error HTTP {response.status_code}",
            arena=_ARENA,
            platform=_PLATFORM,
        )

    if response.status_code >= 400:
        logger.warning(
            "common_crawl: HTTP %d — skipping page. params=%s",
            response.status_code,
            params,
        )
        return []

    entries: list[dict[str, Any]] = []
    for line in response.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if isinstance(entry, dict):
                entries.append(entry)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "common_crawl: JSON parse error on line: %s — %s", line[:80], exc
            )

    return entries


def build_page_params(
    url_pattern: str,
    match_type: str,
    output: str,
    status_filter: str,
    limit: int,
    cc_from: str | None,
    cc_to: str | None,
    offset: int = 0,
) -> dict[str, Any]:
    """Build a CC Index API query parameter dict.

    Args:
        url_pattern: URL or pattern to search for (e.g. ``"*.dk"``).
        match_type: CDX ``matchType`` parameter (e.g. ``"domain"``).
        output: Response format (e.g. ``"json"``).
        status_filter: Filter expression (e.g. ``"=status:200"``).
        limit: Maximum records per page.
        cc_from: CC-formatted start timestamp or ``None``.
        cc_to: CC-formatted end timestamp or ``None``.
        offset: Pagination offset (used in ``from`` param for page > 0).

    Returns:
        Dict of query parameters ready to pass to ``client.get()``.
    """
    params: dict[str, Any] = {
        "url": url_pattern,
        "matchType": match_type,
        "output": output,
        "filter": status_filter,
        "limit": limit,
    }
    if cc_from:
        params["from"] = cc_from
    if cc_to:
        params["to"] = cc_to
    if offset > 0:
        params["from"] = str(offset)
    return params


def format_cc_timestamp(value: datetime | str | None) -> str | None:
    """Format a datetime value as a CC Index API timestamp string.

    CC Index format: ``YYYYMMDDHHmmss`` (14 digits).

    Args:
        value: Datetime object, ISO 8601 string, or ``None``.

    Returns:
        CC-formatted timestamp string or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d%H%M%S")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.strftime("%Y%m%d%H%M%S")
        except ValueError:
            continue
    logger.warning("common_crawl: could not format datetime '%s'.", value)
    return None


def parse_cc_timestamp(timestamp: str | None) -> str | None:
    """Parse a CC Index timestamp to an ISO 8601 string.

    CC timestamps use the format ``YYYYMMDDHHmmss`` (14 digits).

    Args:
        timestamp: Raw CC Index ``timestamp`` field value.

    Returns:
        ISO 8601 datetime string with UTC timezone, or ``None``.
    """
    if not timestamp:
        return None
    try:
        dt = datetime.strptime(timestamp, "%Y%m%d%H%M%S")
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        logger.debug("common_crawl: could not parse timestamp '%s'", timestamp)
        return None


def map_cc_language(languages_field: str | None) -> str | None:
    """Map a CC Index ``languages`` field to an ISO 639-1 code.

    The CC Index stores detected languages in ISO 639-3 format (``"dan"``)
    or as a comma-separated list. Returns ``"da"`` if Danish is detected.

    Args:
        languages_field: Raw CC ``languages`` field value.

    Returns:
        ISO 639-1 language code (e.g. ``"da"``), or ``None``.
    """
    if not languages_field:
        return None
    lang_map: dict[str, str] = {
        "dan": "da",
        "eng": "en",
        "deu": "de",
        "fra": "fr",
        "swe": "sv",
        "nor": "no",
        "fin": "fi",
    }
    parts = [p.strip().lower() for p in languages_field.split(",")]
    if "dan" in parts:
        return "da"
    for part in parts:
        if part in lang_map:
            return lang_map[part]
    if parts and len(parts[0]) == 2:
        return parts[0]
    return None


def extract_domain(url: str | None) -> str | None:
    """Extract the registered domain from a URL string.

    Args:
        url: Full URL string (e.g. ``"https://www.dr.dk/nyheder/..."``).

    Returns:
        Registered domain string (e.g. ``"dr.dk"``), or ``None``.
    """
    if not url:
        return None
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        hostname = parsed.hostname or ""
        if hostname.startswith("www."):
            hostname = hostname[4:]
        return hostname or None
    except Exception:  # noqa: BLE001
        return None
