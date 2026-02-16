"""HTTP client helpers for the Google Search arena.

Contains the low-level request functions for Serper.dev and SerpAPI.
These are separated from the collector to keep ``collector.py`` within
the ~400-line file size limit.

This module is private to the ``google_search`` arena package (indicated by
the leading underscore).  External code should not import from here directly;
use :class:`GoogleSearchCollector` instead.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from issue_observatory.arenas.google_search.config import (
    DANISH_PARAMS,
    MAX_RESULTS_PER_PAGE,
    SERPER_API_URL,
    SERPAPI_URL,
)
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
)

logger = logging.getLogger(__name__)

# Provider labels used as the ``provider`` argument to the rate limiter.
PROVIDER_SERPER: str = "serper"
PROVIDER_SERPAPI: str = "serpapi"


async def fetch_serper(
    client: httpx.AsyncClient,
    term: str,
    api_key: str,
    page: int,
    num: int,
    rate_limiter: Any = None,
    arena_name: str = "google_search",
    platform_name: str = "google",
) -> list[dict[str, Any]]:
    """Fetch one page of Serper.dev organic results.

    Applies the shared :class:`RateLimiter` when provided.

    Args:
        client: Shared HTTP client.
        term: Search query string.
        api_key: Serper.dev API key.
        page: Page number (1-indexed).
        num: Number of results requested (max 10).
        rate_limiter: Optional :class:`RateLimiter` instance.
        arena_name: Arena identifier for rate-limiter keying.
        platform_name: Platform identifier for error messages.

    Returns:
        List of raw organic result dicts from the Serper.dev response.

    Raises:
        ArenaRateLimitError: On HTTP 429.
        ArenaAuthError: On HTTP 401 or 403.
        ArenaCollectionError: On other non-2xx HTTP responses or network errors.
    """
    payload: dict[str, Any] = {
        "q": term,
        **DANISH_PARAMS,
        "num": num,
        "page": page,
    }
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }

    if rate_limiter is not None:
        from issue_observatory.workers.rate_limiter import rate_limited_request  # noqa: PLC0415

        async with rate_limited_request(rate_limiter, arena=arena_name, provider=PROVIDER_SERPER):
            return await _post_serper(client, payload, headers, arena_name, platform_name)
    return await _post_serper(client, payload, headers, arena_name, platform_name)


async def _post_serper(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
    headers: dict[str, str],
    arena_name: str,
    platform_name: str,
) -> list[dict[str, Any]]:
    """Execute the Serper.dev POST and return the organic result list.

    Args:
        client: Shared HTTP client.
        payload: JSON request body.
        headers: HTTP headers including the API key.
        arena_name: Used in exception messages.
        platform_name: Used in exception messages.

    Returns:
        List of raw organic result dicts (may be empty).

    Raises:
        ArenaRateLimitError: On HTTP 429.
        ArenaAuthError: On HTTP 401 or 403.
        ArenaCollectionError: On other HTTP errors or network failures.
    """
    try:
        response = await client.post(SERPER_API_URL, json=payload, headers=headers)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code == 429:
            retry_after = float(exc.response.headers.get("Retry-After", 60))
            raise ArenaRateLimitError(
                "google_search (serper): HTTP 429 — rate limited",
                retry_after=retry_after,
                arena=arena_name,
                platform=platform_name,
            ) from exc
        if code in (401, 403):
            raise ArenaAuthError(
                f"google_search (serper): HTTP {code} — invalid API key",
                arena=arena_name,
                platform=platform_name,
            ) from exc
        raise ArenaCollectionError(
            f"google_search (serper): HTTP {code} — {exc.response.text[:200]}",
            arena=arena_name,
            platform=platform_name,
        ) from exc
    except httpx.RequestError as exc:
        raise ArenaCollectionError(
            f"google_search (serper): network error — {exc}",
            arena=arena_name,
            platform=platform_name,
        ) from exc

    return response.json().get("organic", [])


async def fetch_serpapi(
    client: httpx.AsyncClient,
    term: str,
    api_key: str,
    start: int,
    num: int,
    rate_limiter: Any = None,
    arena_name: str = "google_search",
    platform_name: str = "google",
) -> list[dict[str, Any]]:
    """Fetch one page of SerpAPI organic results.

    SerpAPI uses GET requests; pagination is via the ``start`` offset.

    Args:
        client: Shared HTTP client.
        term: Search query string.
        api_key: SerpAPI API key.
        start: Zero-indexed offset for pagination.
        num: Number of results requested.
        rate_limiter: Optional :class:`RateLimiter` instance.
        arena_name: Arena identifier for rate-limiter keying.
        platform_name: Platform identifier for error messages.

    Returns:
        List of raw organic result dicts from the SerpAPI response.

    Raises:
        ArenaRateLimitError: On HTTP 429.
        ArenaAuthError: On HTTP 401 or 403.
        ArenaCollectionError: On other non-2xx HTTP responses or network errors.
    """
    params: dict[str, Any] = {
        "q": term,
        **DANISH_PARAMS,
        "num": num,
        "start": start,
        "api_key": api_key,
        "engine": "google",
        "output": "json",
    }

    if rate_limiter is not None:
        from issue_observatory.workers.rate_limiter import rate_limited_request  # noqa: PLC0415

        async with rate_limited_request(
            rate_limiter, arena=arena_name, provider=PROVIDER_SERPAPI
        ):
            return await _get_serpapi(client, params, arena_name, platform_name)
    return await _get_serpapi(client, params, arena_name, platform_name)


async def _get_serpapi(
    client: httpx.AsyncClient,
    params: dict[str, Any],
    arena_name: str,
    platform_name: str,
) -> list[dict[str, Any]]:
    """Execute the SerpAPI GET request and return the organic result list.

    Args:
        client: Shared HTTP client.
        params: Query parameters including the API key.
        arena_name: Used in exception messages.
        platform_name: Used in exception messages.

    Returns:
        List of raw organic result dicts (may be empty).

    Raises:
        ArenaRateLimitError: On HTTP 429.
        ArenaAuthError: On HTTP 401 or 403.
        ArenaCollectionError: On other HTTP errors or network failures.
    """
    try:
        response = await client.get(SERPAPI_URL, params=params)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code == 429:
            retry_after = float(exc.response.headers.get("Retry-After", 60))
            raise ArenaRateLimitError(
                "google_search (serpapi): HTTP 429 — rate limited",
                retry_after=retry_after,
                arena=arena_name,
                platform=platform_name,
            ) from exc
        if code in (401, 403):
            raise ArenaAuthError(
                f"google_search (serpapi): HTTP {code} — invalid API key",
                arena=arena_name,
                platform=platform_name,
            ) from exc
        raise ArenaCollectionError(
            f"google_search (serpapi): HTTP {code} — {exc.response.text[:200]}",
            arena=arena_name,
            platform=platform_name,
        ) from exc
    except httpx.RequestError as exc:
        raise ArenaCollectionError(
            f"google_search (serpapi): network error — {exc}",
            arena=arena_name,
            platform=platform_name,
        ) from exc

    return response.json().get("organic_results", [])
