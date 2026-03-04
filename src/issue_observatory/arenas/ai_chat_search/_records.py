"""Content record factory functions for the AI Chat Search arena.

This module is private to the ``ai_chat_search`` package (indicated by the
leading underscore).  It contains the two factory functions that build
universal content record dicts from raw OpenRouter / Perplexity API responses:

- :func:`make_response_record` — builds an ``ai_chat_response`` record from
  a Perplexity Sonar API response.
- :func:`make_citation_record` — builds an ``ai_chat_citation`` record from a
  single normalised citation dict.

These are separated from ``collector.py`` to keep that module within the
~400-line file size limit.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Mapping from model-identifier prefix to the producing organisation.
# Used to populate ``author_display_name`` on AI chat response records.
MODEL_PRODUCERS: dict[str, str] = {
    "gpt-": "OpenAI",
    "claude-": "Anthropic",
    "sonar-": "Perplexity",
    "gemini-": "Google",
    "llama-": "Meta",
    "mistral-": "Mistral",
    "qwen-": "Alibaba",
    "deepseek-": "DeepSeek",
}


def _resolve_model_producer(model_id: str) -> str | None:
    """Resolve a human-readable producer name from an OpenRouter model identifier.

    Strips the optional provider prefix (e.g. ``"perplexity/"`` in
    ``"perplexity/sonar"``), then matches the remainder against
    :data:`MODEL_PRODUCERS` by prefix.

    Args:
        model_id: OpenRouter model identifier string (e.g. ``"perplexity/sonar"``,
            ``"openai/gpt-4o"``, ``"claude-3-5-sonnet"``).

    Returns:
        Producer name string (e.g. ``"Perplexity"``) or ``None`` if unrecognised.
    """
    # Strip provider routing prefix (e.g. "perplexity/sonar" -> "sonar")
    bare = model_id.split("/")[-1] if "/" in model_id else model_id
    for prefix, producer in MODEL_PRODUCERS.items():
        if bare.startswith(prefix):
            return producer
    return None


def _sha256(s: str) -> str:
    """Return the hex-encoded SHA-256 digest of a UTF-8 string.

    Args:
        s: Input string to hash.

    Returns:
        Lowercase hex digest string (64 characters).
    """
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _extract_domain(url: str) -> str:
    """Extract the registered domain from a URL for use as the ``platform`` field.

    Args:
        url: A full URL string (e.g. ``"https://dr.dk/nyheder/..."``).

    Returns:
        The netloc / hostname component (e.g. ``"dr.dk"``).  Falls back to
        the full URL string if parsing fails.
    """
    try:
        parsed = urlparse(url)
        return parsed.netloc or url
    except Exception:  # noqa: BLE001
        return url


def make_response_record(
    phrasing: str,
    original_term: str,
    response: dict[str, Any],
    model_used: str,
    citations: list[dict[str, Any]],
    day_bucket: str,
    arena_name: str = "ai_chat_search",
    platform_name: str = "openrouter",
) -> dict[str, Any]:
    """Build a universal content record for an AI chat search response.

    Creates one ``ai_chat_response`` record per expanded phrasing.  The
    ``platform_id`` is a deterministic SHA-256 of the phrasing + model +
    UTC day bucket, ensuring that re-running collection on the same day
    produces the same ID (deduplication-safe).

    Args:
        phrasing: The expanded Danish phrasing submitted to the model.
        original_term: The original search term before expansion.
        response: Raw JSON response dict from the OpenRouter API.
        model_used: OpenRouter model identifier (e.g. ``"perplexity/sonar"``).
        citations: Normalised citation list (from
            :func:`~._openrouter.extract_citations`).
        day_bucket: UTC date string ``"YYYY-MM-DD"`` for dedup key construction.
        arena_name: Arena name written to the ``arena`` field.
        platform_name: Platform name written to the ``platform`` field.

    Returns:
        Dict conforming to the ``content_records`` universal schema with
        ``content_type="ai_chat_response"``.
    """
    now = datetime.now(timezone.utc)

    # Deterministic dedup key: same phrasing + model + day = same ID
    platform_id = _sha256(phrasing + model_used + day_bucket)

    # Extract response text from choices[0].message.content
    text_content: str | None = None
    try:
        choices = response.get("choices") or []
        if choices:
            text_content = choices[0].get("message", {}).get("content")
    except (KeyError, IndexError, TypeError):
        pass

    content_hash = _sha256(text_content) if text_content else _sha256(platform_id)

    # Extract token usage
    usage = response.get("usage") or {}
    tokens_used: dict[str, Any] = {
        "prompt": usage.get("prompt_tokens"),
        "completion": usage.get("completion_tokens"),
    }

    model_producer: str | None = _resolve_model_producer(model_used)

    raw_metadata: dict[str, Any] = {
        "query_phrasing": phrasing,
        "search_term_original": original_term,
        "model_used": model_used,
        "model_producer": model_producer,
        "citations": citations,
        "tokens_used": tokens_used,
        "temperature": 0,
        "search_engine_underlying": "perplexity",
    }

    return {
        "platform": platform_name,
        "arena": arena_name,
        "platform_id": platform_id,
        "content_type": "ai_chat_response",
        "text_content": text_content,
        "title": phrasing,
        "url": None,
        "language": "da",
        "published_at": now.isoformat(),
        "collected_at": now.isoformat(),
        "author_platform_id": model_used,
        "author_display_name": model_producer,
        "views_count": None,
        "likes_count": None,
        "shares_count": None,
        "comments_count": None,
        "engagement_score": None,
        "media_urls": [],
        "content_hash": content_hash,
        "raw_metadata": raw_metadata,
    }


def make_citation_record(
    citation: dict[str, Any],
    phrasing: str,
    original_term: str,
    model_used: str,
    rank: int,
    parent_platform_id: str,
    day_bucket: str,
    arena_name: str = "ai_chat_search",
) -> dict[str, Any]:
    """Build a universal content record for a single cited URL.

    Creates one ``ai_chat_citation`` record per citation in a Perplexity
    Sonar response.  The ``platform`` field is set to the domain of the
    cited URL (e.g. ``"dr.dk"``), enabling source-domain analysis across
    citation records.

    The ``platform_id`` is a deterministic SHA-256 of the citation URL +
    phrasing + UTC day bucket, ensuring deduplication when the same URL is
    cited for the same phrasing on the same day.

    Args:
        citation: Normalised citation dict with keys ``url`` (str), ``title``
            (str or None), and ``snippet`` (str or None).
        phrasing: The expanded Danish phrasing that produced this citation.
        original_term: The original search term before expansion.
        model_used: OpenRouter model identifier.
        rank: 1-indexed citation rank within the response (1 = first cited).
        parent_platform_id: ``platform_id`` of the parent
            ``ai_chat_response`` record (for linking).
        day_bucket: UTC date string ``"YYYY-MM-DD"`` for dedup key construction.
        arena_name: Arena name written to the ``arena`` field.

    Returns:
        Dict conforming to the ``content_records`` universal schema with
        ``content_type="ai_chat_citation"``.
    """
    now = datetime.now(timezone.utc)

    citation_url: str = citation["url"]
    domain = _extract_domain(citation_url)

    # Deterministic dedup key: same citation URL + phrasing + day = same ID
    platform_id = _sha256(citation_url + phrasing + day_bucket)
    content_hash = _sha256(citation_url)

    raw_metadata: dict[str, Any] = {
        "parent_response_platform_id": parent_platform_id,
        "citation_rank": rank,
        "original_term": original_term,
        "expanded_phrasing": phrasing,
        "model": model_used,
    }

    return {
        "platform": domain,
        "arena": arena_name,
        "platform_id": platform_id,
        "content_type": "ai_chat_citation",
        "text_content": citation.get("snippet"),
        "title": citation.get("title"),
        "url": citation_url,
        "language": None,
        "published_at": None,
        "collected_at": now.isoformat(),
        "author_platform_id": None,
        "author_display_name": None,
        "views_count": None,
        "likes_count": None,
        "shares_count": None,
        "comments_count": None,
        "engagement_score": None,
        "media_urls": [],
        "content_hash": content_hash,
        "raw_metadata": raw_metadata,
    }
