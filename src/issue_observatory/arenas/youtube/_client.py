"""Low-level HTTP and RSS client functions for the YouTube arena.

Separates network I/O from the collector business logic so that
:mod:`.collector` stays within the ~400-line file-size limit.

Functions in this module are pure I/O helpers:
- :func:`search_videos_page` — one ``search.list`` page call.
- :func:`fetch_videos_batch` — one ``videos.list`` batch call.
- :func:`poll_channel_rss` — parse an Atom RSS feed with ``feedparser``.
- :func:`extract_error_reason` — extract ``reason`` from a YouTube error body.

All functions that call the YouTube Data API require an initialised
:class:`httpx.AsyncClient`.  Callers are responsible for providing the client
and for managing rate-limit throttling before calling these functions.
"""

from __future__ import annotations

import calendar
import logging
import time as _time
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx

from issue_observatory.arenas.youtube.config import (
    MAX_RESULTS_PER_SEARCH_PAGE,
    YOUTUBE_API_BASE_URL,
    YOUTUBE_CHANNEL_RSS_URL,
)
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
)

logger = logging.getLogger(__name__)

_ARENA = "social_media"
_PLATFORM = "youtube"


def extract_error_reason(response: httpx.Response) -> str:
    """Extract the ``reason`` field from a YouTube API error response body.

    Args:
        response: The :class:`httpx.Response` containing the error body.

    Returns:
        The ``reason`` string (e.g. ``"quotaExceeded"``), or ``"unknown"``
        if the body cannot be parsed.
    """
    try:
        body = response.json()
        errors = body.get("error", {}).get("errors", [])
        if errors:
            return errors[0].get("reason", "unknown")
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


async def make_api_request(
    client: httpx.AsyncClient,
    endpoint: str,
    params: dict[str, Any],
    credential_pool: Any,
    cred_id: str,
) -> dict[str, Any]:
    """Make a YouTube Data API v3 GET request with error handling.

    Handles quota exhaustion (HTTP 403 ``quotaExceeded``) by calling
    ``credential_pool.report_error()`` and raising ``ArenaRateLimitError``
    so the caller can rotate credentials.

    Args:
        client: Shared :class:`httpx.AsyncClient`.
        endpoint: API endpoint path segment (e.g. ``"search"``, ``"videos"``).
        params: Query parameter dict.  Must include ``key``.
        credential_pool: Application-scoped ``CredentialPool`` or ``None``.
        cred_id: Credential identifier used for error reporting.

    Returns:
        Parsed JSON response dict.

    Raises:
        ArenaRateLimitError: HTTP 403 with ``reason="quotaExceeded"``.
        ArenaAuthError: HTTP 401 or non-quota HTTP 403.
        ArenaCollectionError: Any other non-2xx HTTP response or network error.
    """
    url = f"{YOUTUBE_API_BASE_URL}/{endpoint}"
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if status_code == 403:
            reason = extract_error_reason(exc.response)
            if reason == "quotaExceeded":
                if credential_pool is not None:
                    from issue_observatory.core.exceptions import (  # noqa: PLC0415
                        ArenaRateLimitError as _ARLR,
                    )
                    await credential_pool.report_error(
                        credential_id=cred_id,
                        error=_ARLR("quota exceeded"),
                    )
                raise ArenaRateLimitError(
                    f"youtube: quota exceeded on endpoint '{endpoint}'",
                    retry_after=3600.0,
                    arena=_ARENA,
                    platform=_PLATFORM,
                ) from exc
            raise ArenaAuthError(
                f"youtube: HTTP 403 (reason={reason}) on endpoint '{endpoint}'",
                arena=_ARENA,
                platform=_PLATFORM,
            ) from exc
        if status_code == 401:
            raise ArenaAuthError(
                f"youtube: HTTP 401 on endpoint '{endpoint}'",
                arena=_ARENA,
                platform=_PLATFORM,
            ) from exc
        raise ArenaCollectionError(
            f"youtube: HTTP {status_code} on endpoint '{endpoint}'",
            arena=_ARENA,
            platform=_PLATFORM,
        ) from exc
    except httpx.RequestError as exc:
        raise ArenaCollectionError(
            f"youtube: connection error on endpoint '{endpoint}': {exc}",
            arena=_ARENA,
            platform=_PLATFORM,
        ) from exc


async def search_videos_page(
    client: httpx.AsyncClient,
    api_key: str,
    credential_pool: Any,
    cred_id: str,
    term: str,
    max_results_page: int,
    page_token: str | None,
    published_after: str | None,
    published_before: str | None,
    danish_params: dict[str, str],
) -> tuple[list[str], str | None]:
    """Fetch one page of YouTube ``search.list`` results.

    Args:
        client: Shared HTTP client.
        api_key: YouTube Data API v3 key.
        credential_pool: Credential pool for error reporting on quota exhaustion.
        cred_id: Credential identifier.
        term: Search query string.
        max_results_page: Number of results to request (1–50).
        page_token: Pagination token from a previous response, or ``None``.
        published_after: ISO 8601 ``publishedAfter`` filter, or ``None``.
        published_before: ISO 8601 ``publishedBefore`` filter, or ``None``.
        danish_params: Danish locale parameters dict.

    Returns:
        Tuple of (list of video ID strings, next page token or ``None``).

    Raises:
        ArenaRateLimitError: On quota exhaustion.
        ArenaAuthError: On authentication failure.
        ArenaCollectionError: On other API errors.
    """
    params: dict[str, Any] = {
        "q": term,
        "part": "id,snippet",
        "type": "video",
        "order": "date",
        "maxResults": min(max_results_page, MAX_RESULTS_PER_SEARCH_PAGE),
        "key": api_key,
        **danish_params,
    }
    if page_token:
        params["pageToken"] = page_token
    if published_after:
        params["publishedAfter"] = published_after
    if published_before:
        params["publishedBefore"] = published_before

    data = await make_api_request(
        client=client,
        endpoint="search",
        params=params,
        credential_pool=credential_pool,
        cred_id=cred_id,
    )

    items = data.get("items", [])
    video_ids = [
        item["id"]["videoId"]
        for item in items
        if item.get("id", {}).get("videoId")
    ]
    next_token: str | None = data.get("nextPageToken")

    logger.debug(
        "youtube: search page term=%r → %d ids, next_token=%s",
        term,
        len(video_ids),
        bool(next_token),
    )
    return video_ids, next_token


async def fetch_videos_batch(
    client: httpx.AsyncClient,
    api_key: str,
    credential_pool: Any,
    cred_id: str,
    video_ids: list[str],
) -> list[dict[str, Any]]:
    """Fetch full metadata for a batch of up to 50 video IDs.

    Calls ``videos.list`` with ``part=snippet,statistics,contentDetails``
    (1 quota unit for up to 50 IDs).

    Args:
        client: Shared HTTP client.
        api_key: YouTube Data API v3 key.
        credential_pool: Credential pool for error reporting.
        cred_id: Credential identifier.
        video_ids: List of video ID strings (max 50).

    Returns:
        List of raw video resource dicts from the API response.

    Raises:
        ArenaRateLimitError: On quota exhaustion.
        ArenaAuthError: On authentication failure.
        ArenaCollectionError: On other API errors.
    """
    params: dict[str, Any] = {
        "id": ",".join(video_ids),
        "part": "snippet,statistics,contentDetails",
        "key": api_key,
    }
    data = await make_api_request(
        client=client,
        endpoint="videos",
        params=params,
        credential_pool=credential_pool,
        cred_id=cred_id,
    )
    items: list[dict[str, Any]] = data.get("items", [])
    logger.debug(
        "youtube: videos.list batch size=%d → %d items returned",
        len(video_ids),
        len(items),
    )
    return items


async def poll_channel_rss(
    channel_id: str,
    date_from: datetime | None,
    date_to: datetime | None,
) -> list[str]:
    """Poll a YouTube channel's Atom RSS feed for recent video IDs.

    Parses the feed with ``feedparser``.  Returns up to 15 video IDs (the
    RSS feed limit).  Applies optional date-range filtering.

    Args:
        channel_id: YouTube channel ID (format: ``UC...``).
        date_from: Optional timezone-aware lower bound for publication date.
        date_to: Optional timezone-aware upper bound for publication date.

    Returns:
        List of YouTube video ID strings (may be empty on feed error).
    """
    url = YOUTUBE_CHANNEL_RSS_URL.format(channel_id=channel_id)
    try:
        feed = feedparser.parse(url)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "youtube: failed to parse RSS for channel %s: %s", channel_id, exc
        )
        return []

    if feed.bozo and not feed.entries:
        logger.warning(
            "youtube: RSS bozo error for channel %s: %s",
            channel_id,
            feed.bozo_exception,
        )
        return []

    video_ids: list[str] = []
    for entry in feed.entries:
        video_id: str | None = getattr(entry, "yt_videoid", None)
        if not video_id:
            link = getattr(entry, "link", "")
            if "watch?v=" in link:
                video_id = link.split("watch?v=")[-1].split("&")[0]
        if not video_id:
            continue

        published_struct = getattr(entry, "published_parsed", None)
        if published_struct is not None:
            pub_ts = calendar.timegm(published_struct)
            pub_dt = datetime.fromtimestamp(pub_ts, tz=timezone.utc)
            if date_from and pub_dt < date_from:
                continue
            if date_to and pub_dt > date_to:
                continue

        video_ids.append(video_id)

    logger.debug(
        "youtube: RSS channel %s → %d ids", channel_id, len(video_ids)
    )
    return video_ids
