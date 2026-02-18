"""Low-level OpenRouter HTTP client for the AI Chat Search arena.

This module is private to the ``ai_chat_search`` package (indicated by the
leading underscore).  External code should not import from here directly;
use :class:`~issue_observatory.arenas.ai_chat_search.collector.AiChatSearchCollector`
instead.

Responsibilities:
- ``chat_completion()``: POST a chat message to the OpenRouter API and return
  the raw JSON response dict.
- ``extract_citations()``: Parse Perplexity citation arrays from the response,
  handling both format A (top-level URL strings) and format B (per-message
  objects with url/title/snippet).

Error handling maps HTTP status codes to typed exceptions:
- HTTP 429 -> :class:`~issue_observatory.core.exceptions.ArenaRateLimitError`
- HTTP 401/403 -> :class:`~issue_observatory.core.exceptions.ArenaAuthError`
- Other non-2xx -> :class:`~issue_observatory.core.exceptions.ArenaCollectionError`
- Network errors -> :class:`~issue_observatory.core.exceptions.ArenaCollectionError`
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from issue_observatory.arenas.ai_chat_search.config import (
    CHAT_SYSTEM_PROMPT,
    OPENROUTER_API_URL,
    OPENROUTER_RATE_LIMITER_KEY,
)
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
)

logger = logging.getLogger(__name__)


async def chat_completion(
    client: httpx.AsyncClient,
    model: str,
    system_prompt: str,
    user_message: str,
    api_key: str,
    rate_limiter: Any = None,
    arena_name: str = "ai_chat_search",
    platform_name: str = "openrouter",
) -> dict[str, Any]:
    """Call the OpenRouter chat completions endpoint and return the raw response.

    Applies the shared rate limiter when provided.  Temperature is always 0
    for maximum reproducibility.

    Args:
        client: Shared :class:`httpx.AsyncClient` instance.
        model: OpenRouter model identifier (e.g. ``"perplexity/sonar"``).
        system_prompt: System message to prepend to the conversation.
        user_message: The user's query or phrasing to submit.
        api_key: OpenRouter API key (``Bearer`` token).
        rate_limiter: Optional shared Redis-backed
            :class:`~issue_observatory.workers.rate_limiter.RateLimiter`.
        arena_name: Arena identifier used in rate-limiter keying and error messages.
        platform_name: Platform identifier used in exception constructors.

    Returns:
        Parsed JSON response dict from the OpenRouter API.

    Raises:
        ArenaRateLimitError: On HTTP 429.
        ArenaAuthError: On HTTP 401 or 403.
        ArenaCollectionError: On other non-2xx responses or network errors.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0,
    }
    headers: dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    if rate_limiter is not None:
        from issue_observatory.workers.rate_limiter import rate_limited_request  # noqa: PLC0415

        async with rate_limited_request(
            rate_limiter, arena=arena_name, provider=OPENROUTER_RATE_LIMITER_KEY
        ):
            return await _post_completion(
                client, payload, headers, arena_name, platform_name
            )

    return await _post_completion(client, payload, headers, arena_name, platform_name)


async def _post_completion(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
    headers: dict[str, str],
    arena_name: str,
    platform_name: str,
) -> dict[str, Any]:
    """Execute the OpenRouter POST request and return the parsed response.

    Args:
        client: Shared HTTP client.
        payload: JSON request body (model, messages, temperature).
        headers: HTTP headers including Authorization and Content-Type.
        arena_name: Used in exception messages.
        platform_name: Used in exception constructors.

    Returns:
        Parsed JSON response dict.

    Raises:
        ArenaRateLimitError: On HTTP 429.
        ArenaAuthError: On HTTP 401 or 403.
        ArenaCollectionError: On other HTTP errors or network failures.
    """
    try:
        response = await client.post(OPENROUTER_API_URL, json=payload, headers=headers)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code == 429:
            retry_after = float(exc.response.headers.get("Retry-After", 60))
            raise ArenaRateLimitError(
                f"ai_chat_search (openrouter): HTTP 429 — rate limited",
                retry_after=retry_after,
                arena=arena_name,
                platform=platform_name,
            ) from exc
        if code in (401, 403):
            raise ArenaAuthError(
                f"ai_chat_search (openrouter): HTTP {code} — invalid API key",
                arena=arena_name,
                platform=platform_name,
            ) from exc
        raise ArenaCollectionError(
            f"ai_chat_search (openrouter): HTTP {code} — {exc.response.text[:200]}",
            arena=arena_name,
            platform=platform_name,
        ) from exc
    except httpx.RequestError as exc:
        raise ArenaCollectionError(
            f"ai_chat_search (openrouter): network error — {exc}",
            arena=arena_name,
            platform=platform_name,
        ) from exc

    try:
        return response.json()  # type: ignore[no-any-return]
    except Exception as exc:  # noqa: BLE001
        raise ArenaCollectionError(
            f"ai_chat_search (openrouter): JSON parse error — {exc}",
            arena=arena_name,
            platform=platform_name,
        ) from exc


def extract_citations(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract Perplexity citations from an OpenRouter response dict.

    Handles two citation formats that Perplexity may return:

    **Format A** — top-level ``citations`` array of URL strings::

        {"citations": ["https://dr.dk/...", "https://berlingske.dk/..."], ...}

    **Format B** — per-message ``citations`` array of objects::

        {"choices": [{"message": {"citations": [
            {"url": "...", "title": "...", "snippet": "..."}
        ]}}]}

    The function checks both locations and normalises to a consistent list of
    ``{"url": ..., "title": ..., "snippet": ...}`` dicts.  For Format A,
    ``title`` and ``snippet`` are ``None``.

    If neither location contains citations, an empty list is returned.

    Args:
        response: Parsed JSON response dict from the OpenRouter API.

    Returns:
        List of citation dicts, each with keys ``url`` (str), ``title``
        (str or None), and ``snippet`` (str or None).
    """
    normalised: list[dict[str, Any]] = []

    # -- Format B: choices[0].message.citations (objects with url/title/snippet)
    try:
        choices = response.get("choices") or []
        if choices:
            message_citations = choices[0].get("message", {}).get("citations")
            if message_citations and isinstance(message_citations, list):
                for item in message_citations:
                    if isinstance(item, dict) and item.get("url"):
                        normalised.append(
                            {
                                "url": item["url"],
                                "title": item.get("title"),
                                "snippet": item.get("snippet"),
                            }
                        )
                if normalised:
                    return normalised
    except (KeyError, IndexError, TypeError):
        pass

    # -- Format A: top-level citations array of URL strings
    top_level = response.get("citations")
    if top_level and isinstance(top_level, list):
        for item in top_level:
            if isinstance(item, str) and item:
                normalised.append({"url": item, "title": None, "snippet": None})
            elif isinstance(item, dict) and item.get("url"):
                # Defensive: some hybrid formats exist
                normalised.append(
                    {
                        "url": item["url"],
                        "title": item.get("title"),
                        "snippet": item.get("snippet"),
                    }
                )

    return normalised
