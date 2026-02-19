"""UCR normalization for the URL Scraper arena.

Contains :func:`normalize_raw_record`, which converts a raw fetch record dict
(produced by :meth:`~.collector.UrlScraperCollector._fetch_single_url`) into
a Universal Content Record conforming to the ``content_records`` schema.

Separated from :mod:`.collector` to keep individual module sizes manageable.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.web.url_scraper._helpers import (
    extract_domain,
    resolve_published_at,
)
from issue_observatory.core.normalizer import Normalizer
from issue_observatory.scraper.content_extractor import ExtractedContent


def normalize_raw_record(
    normalizer: Normalizer,
    raw: dict[str, Any],
    platform_name: str,
    arena_name: str,
    tier: Tier,
    search_terms_matched: list[str],
) -> dict[str, Any]:
    """Convert a raw URL scraper fetch record to a Universal Content Record.

    Computes ``platform_id`` (SHA-256 of the final URL), ``content_hash``
    (SHA-256 of text content for deduplication), and
    ``pseudonymized_author_id`` (domain pseudonymized by the shared
    :class:`~issue_observatory.core.normalizer.Normalizer`).

    ``raw_metadata`` captures fetch diagnostics (HTTP status, extraction
    method, robots.txt compliance, timing) for observability.

    Args:
        normalizer: Shared :class:`~issue_observatory.core.normalizer.Normalizer`
            instance (provides ``compute_content_hash`` and
            ``pseudonymize_author``).
        raw: Raw fetch record dict with keys ``source_url``, ``final_url``,
            ``html``, ``extracted``, ``http_status``, ``fetch_error``,
            ``robots_txt_allowed``, ``needs_playwright``,
            ``fetch_duration_ms``, ``last_modified_header``,
            ``_fetch_failed``, ``_search_terms_matched``.
        platform_name: Platform identifier (``"url_scraper"``).
        arena_name: Arena group identifier (``"web"``).
        tier: Operational tier used for this fetch (stored in
            ``collection_tier``).
        search_terms_matched: Terms that matched this page (empty for
            actor-based collection).

    Returns:
        Dict conforming to the ``content_records`` universal schema, with
        ``platform_id``, ``content_type``, ``content_hash``,
        ``pseudonymized_author_id``, ``raw_metadata``, and ``media_urls``
        explicitly set after the normalizer pass.
    """
    final_url: str = raw.get("final_url") or raw.get("source_url", "")
    source_url: str = raw.get("source_url", final_url)
    domain = extract_domain(final_url)

    extracted: ExtractedContent | None = raw.get("extracted")
    text_content: str | None = extracted.text if extracted else None
    title: str | None = extracted.title if extracted else None
    language: str | None = extracted.language if extracted else None

    # platform_id: SHA-256 of final URL (deterministic, redirect-aware).
    platform_id = hashlib.sha256(final_url.encode()).hexdigest()

    # content_hash: SHA-256 of text content for cross-arena deduplication.
    content_hash: str | None = (
        normalizer.compute_content_hash(text_content)
        if text_content
        else normalizer.compute_content_hash(final_url)
    )

    # pseudonymized_author_id: domain treated as the "author".
    pseudonymized_author_id: str | None = normalizer.pseudonymize_author(domain)

    # published_at: best-effort date resolution.
    html: str | None = raw.get("html")
    last_modified_header: str | None = raw.get("last_modified_header")
    published_at_dt: datetime = resolve_published_at(html, final_url, last_modified_header)

    # Determine extraction method for raw_metadata.
    if extracted and extracted.text:
        extraction_method: str | None = "trafilatura"
    elif extracted is not None:
        extraction_method = "tag_stripping"
    else:
        extraction_method = None

    is_blocked = raw.get("_fetch_failed", False) or not raw.get("robots_txt_allowed", True)

    raw_metadata: dict[str, Any] = {
        "source_url": source_url,
        "final_url": final_url,
        "http_status_code": raw.get("http_status"),
        "extraction_method": extraction_method,
        "needs_playwright": raw.get("needs_playwright", False),
        "is_blocked": is_blocked,
        "robots_txt_allowed": raw.get("robots_txt_allowed", True),
        "fetch_error": raw.get("fetch_error"),
        "fetch_duration_ms": raw.get("fetch_duration_ms"),
        "content_length_bytes": (
            len(text_content.encode("utf-8")) if text_content else None
        ),
    }

    norm_input: dict[str, Any] = {
        "id": platform_id,
        "url": final_url,
        "title": title,
        "text_content": text_content,
        "author": domain,
        "author_display_name": domain,
        "published_at": published_at_dt.isoformat() if published_at_dt else None,
        "language": language,
        "content_type": "web_page",
        "media_urls": [],
        "_search_terms_matched": search_terms_matched,
    }

    normalized = normalizer.normalize(
        raw_item=norm_input,
        platform=platform_name,
        arena=arena_name,
        collection_tier=tier.value,
        search_terms_matched=search_terms_matched,
    )

    # Ensure our computed values take precedence over normalizer defaults.
    normalized["platform_id"] = platform_id
    normalized["content_type"] = "web_page"
    normalized["content_hash"] = content_hash
    normalized["pseudonymized_author_id"] = pseudonymized_author_id
    normalized["raw_metadata"] = raw_metadata
    normalized["media_urls"] = []

    return normalized
