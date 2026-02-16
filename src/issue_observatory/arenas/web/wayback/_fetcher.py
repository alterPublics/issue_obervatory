"""Low-level Wayback Machine CDX API fetching and pagination helpers.

Internal module used by
:class:`~issue_observatory.arenas.web.wayback.collector.WaybackCollector`.
Not part of the public arena API.

Provides:
- :func:`fetch_cdx_page` — fetch one CDX page with resume-key pagination.
- :func:`format_wb_timestamp` — format datetime values for CDX API params.
- :func:`parse_wb_timestamp` — parse CDX timestamps to ISO 8601.
- :func:`extract_domain` — extract registered domain from a URL.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from issue_observatory.arenas.web.wayback.config import (
    WB_CDX_BASE_URL,
    WB_DEFAULT_COLLAPSE,
    WB_DEFAULT_FIELDS,
    WB_DEFAULT_OUTPUT,
    WB_DEFAULT_STATUS_FILTER,
)
from issue_observatory.core.exceptions import ArenaCollectionError, ArenaRateLimitError

logger = logging.getLogger(__name__)

_ARENA = "web"
_PLATFORM = "wayback"


async def fetch_cdx_page(
    client: httpx.AsyncClient,
    url_pattern: str,
    match_type: str,
    wb_from: str | None,
    wb_to: str | None,
    limit: int,
    resume_key: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch a single page from the Wayback Machine CDX API.

    The CDX API returns a 2D JSON array. The first row contains field names;
    subsequent rows are capture records. When ``showResumeKey=true`` is set,
    the last row may be a single-element resume key array.

    Args:
        client: Shared async HTTP client.
        url_pattern: URL or URL pattern to query.
        match_type: CDX ``matchType`` parameter (e.g. ``"domain"``).
        wb_from: WB-formatted start timestamp or ``None``.
        wb_to: WB-formatted end timestamp or ``None``.
        limit: Maximum records to fetch in this page.
        resume_key: Pagination key from the previous page, or ``None``.

    Returns:
        Tuple of (list of raw CDX entry dicts, next resume_key or ``None``).

    Raises:
        ArenaCollectionError: On non-retryable HTTP errors.
        ArenaRateLimitError: On HTTP 429.
    """
    params: dict[str, Any] = {
        "url": url_pattern,
        "matchType": match_type,
        "output": WB_DEFAULT_OUTPUT,
        "fl": WB_DEFAULT_FIELDS,
        "filter": WB_DEFAULT_STATUS_FILTER,
        "collapse": WB_DEFAULT_COLLAPSE,
        "limit": limit,
        "showResumeKey": "true",
    }
    if wb_from:
        params["from"] = wb_from
    if wb_to:
        params["to"] = wb_to
    if resume_key:
        params["resumeKey"] = resume_key

    try:
        response = await client.get(WB_CDX_BASE_URL, params=params)
    except httpx.RequestError as exc:
        raise ArenaCollectionError(
            f"wayback: request error: {exc}",
            arena=_ARENA,
            platform=_PLATFORM,
        ) from exc

    if response.status_code == 429:
        retry_after = float(response.headers.get("Retry-After", 60))
        raise ArenaRateLimitError(
            "wayback: HTTP 429 rate limited",
            retry_after=retry_after,
            arena=_ARENA,
            platform=_PLATFORM,
        )

    if response.status_code == 503:
        logger.warning("wayback: CDX API returned 503 (service overloaded). Skipping page.")
        return [], None

    if response.status_code >= 500:
        raise ArenaCollectionError(
            f"wayback: server error HTTP {response.status_code}",
            arena=_ARENA,
            platform=_PLATFORM,
        )

    if response.status_code >= 400:
        logger.warning(
            "wayback: HTTP %d — skipping page for url_pattern=%s",
            response.status_code,
            url_pattern,
        )
        return [], None

    if not response.text.strip():
        return [], None

    try:
        data = response.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("wayback: JSON parse error: %s — skipping page.", exc)
        return [], None

    if not isinstance(data, list) or len(data) < 1:
        return [], None

    field_names: list[str] = data[0]
    data_rows = data[1:]

    # Check if the last row is a resume key row (single element)
    next_resume_key: str | None = None
    if data_rows and len(data_rows[-1]) == 1:
        next_resume_key = data_rows[-1][0]
        data_rows = data_rows[:-1]

    entries: list[dict[str, Any]] = []
    for row in data_rows:
        if len(row) == len(field_names):
            entries.append(dict(zip(field_names, row)))

    return entries, next_resume_key


def format_wb_timestamp(value: datetime | str | None) -> str | None:
    """Format a datetime value as a Wayback Machine CDX timestamp string.

    CDX API timestamp format: ``YYYYMMDDHHmmss`` (14 digits).

    Args:
        value: Datetime object, ISO 8601 string, or ``None``.

    Returns:
        CDX-formatted timestamp string or ``None``.
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
    logger.warning("wayback: could not format datetime '%s'.", value)
    return None


def parse_wb_timestamp(timestamp: str | None) -> str | None:
    """Parse a Wayback Machine CDX timestamp to an ISO 8601 string.

    CDX timestamps use the format ``YYYYMMDDHHmmss`` (14 digits).

    Args:
        timestamp: Raw CDX ``timestamp`` field value.

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
        logger.debug("wayback: could not parse timestamp '%s'", timestamp)
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
