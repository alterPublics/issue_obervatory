"""Query expansion module for the AI Chat Search arena.

This module is private to the ``ai_chat_search`` package (indicated by the
leading underscore).  External code should not import from here directly;
use :class:`~issue_observatory.arenas.ai_chat_search.collector.AiChatSearchCollector`
instead.

The expansion step converts a short search term (e.g. ``"CO2 afgift"``) into
N realistic Danish-language phrasings that simulate how real users would ask
the question to an AI chatbot (e.g. ``"Hvad er CO2 afgiften i Danmark?"``).

Uses ``google/gemma-3-27b-it:free`` on OpenRouter — zero token cost, ~20
req/min rate limit.  The response is parsed by splitting on newlines, stripping
common numbering prefixes (``"1. "``, ``"1) "``), and discarding empty lines.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from issue_observatory.arenas.ai_chat_search.config import (
    EXPANSION_MODEL,
    EXPANSION_SYSTEM_PROMPT_TEMPLATE,
    OPENROUTER_RATE_LIMITER_KEY,
)
from issue_observatory.arenas.ai_chat_search._openrouter import chat_completion

logger = logging.getLogger(__name__)

# Pre-compiled regex to strip leading numbering from expansion output lines.
# Matches patterns like "1. ", "1) ", "1: ", "1 - " at the start of a line.
_NUMBERING_PREFIX_RE: re.Pattern[str] = re.compile(r"^\d+[\.\)\:\-]\s*")


async def expand_term(
    client: httpx.AsyncClient,
    term: str,
    n_phrasings: int,
    api_key: str,
    rate_limiter: Any = None,
) -> list[str]:
    """Generate N realistic Danish phrasings from a search term.

    Calls the ``google/gemma-3-27b-it:free`` model on OpenRouter to expand a
    short search term (e.g. ``"CO2 afgift"``) into ``n_phrasings`` natural-
    language questions that a Danish user might ask an AI chatbot.

    Response parsing:
    1. Extract the text content from ``choices[0].message.content``.
    2. Split by newlines.
    3. Strip leading numbering prefixes (``"1. "``, ``"2) "``, etc.).
    4. Strip surrounding whitespace.
    5. Discard empty lines and lines that look like meta-commentary (e.g.
       lines that do not end with ``"?"`` and are very short).
    6. Return up to ``n_phrasings`` non-empty lines.

    Args:
        client: Shared :class:`httpx.AsyncClient` instance.
        term: Original search term to expand (e.g. ``"CO2 afgift"``).
        n_phrasings: Number of phrasings to generate and return.
        api_key: OpenRouter API key.
        rate_limiter: Optional shared Redis-backed RateLimiter.

    Returns:
        List of up to ``n_phrasings`` cleaned Danish phrasing strings.
        May return fewer if the model produces fewer valid lines.

    Raises:
        ArenaRateLimitError: On HTTP 429 from OpenRouter.
        ArenaAuthError: On HTTP 401/403 from OpenRouter.
        ArenaCollectionError: On other API errors or network failures.
    """
    system_prompt = EXPANSION_SYSTEM_PROMPT_TEMPLATE.replace("{N}", str(n_phrasings))

    response = await chat_completion(
        client=client,
        model=EXPANSION_MODEL,
        system_prompt=system_prompt,
        user_message=term,
        api_key=api_key,
        rate_limiter=rate_limiter,
        arena_name="ai_chat_search",
        platform_name="openrouter",
    )

    raw_text = _extract_text_content(response)
    phrasings = _parse_phrasings(raw_text, n_phrasings)

    if len(phrasings) < n_phrasings:
        logger.warning(
            "ai_chat_search: query expansion for '%s' returned %d phrasings "
            "(requested %d). Model output may be malformed.",
            term,
            len(phrasings),
            n_phrasings,
        )

    return phrasings


def _extract_text_content(response: dict[str, Any]) -> str:
    """Extract the assistant's message text from an OpenRouter response.

    Args:
        response: Parsed JSON response dict from OpenRouter.

    Returns:
        The text content string, or empty string if not found.
    """
    try:
        choices = response.get("choices") or []
        if choices:
            return choices[0].get("message", {}).get("content") or ""
    except (KeyError, IndexError, TypeError):
        pass
    return ""


def _parse_phrasings(raw_text: str, n_phrasings: int) -> list[str]:
    """Parse the expansion model's raw text output into a list of phrasings.

    Applies the following cleaning steps to each line:
    - Strip leading numbering prefixes (``"1. "``, ``"2) "``, etc.).
    - Strip surrounding whitespace.
    - Discard empty lines.
    - Keep only up to ``n_phrasings`` non-empty results.

    Args:
        raw_text: The raw text response from the expansion model.
        n_phrasings: Maximum number of phrasings to return.

    Returns:
        Cleaned list of phrasing strings.
    """
    phrasings: list[str] = []

    for line in raw_text.splitlines():
        # Strip leading numbering prefixes
        cleaned = _NUMBERING_PREFIX_RE.sub("", line).strip()

        if not cleaned:
            continue

        phrasings.append(cleaned)

        if len(phrasings) >= n_phrasings:
            break

    return phrasings
