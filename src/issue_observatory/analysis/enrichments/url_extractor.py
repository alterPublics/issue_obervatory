"""URL extraction enricher for content records.

Extracts, cleans, and catalogs URLs found within content records.

Extraction rules:
- ``domain_crawler`` records are skipped entirely (already scraped URLs).
- YouTube/TikTok **video** records: the record's own ``url`` is added as a
  ``self_reference``.  Comments on these platforms are scanned for
  text-extracted URLs only (the comment ``url`` is just a permalink back to
  the platform).
- ``google_search`` records: the record's ``url`` is the outbound search
  target (populated from ``raw_metadata['link']``), not a post permalink,
  so it is extracted as a ``structured`` URL via the structured-field path
  rather than as ``self_reference``.
- All other platforms: the record's ``url`` is included as a
  ``self_reference`` and ``text_content`` is scanned for additional URLs.
- Platform-specific structured URL fields are also extracted:
  - X/Twitter: ``entities.urls[].expanded_url``
  - Bluesky: ``facets[].features[].uri`` and ``embed.external.uri``
  - OpenRouter: ``citations[].url``
  - Google Search: ``link`` (the organic result's target URL).

Results are written to both:

1. ``raw_metadata.enrichments.url_extraction`` (JSONB)
2. ``extracted_urls`` table (relational, for aggregation queries)

Owned by the Core Application Engineer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from issue_observatory.analysis.enrichments.base import ContentEnricher
from issue_observatory.analysis.url_cleaner import (
    clean_url,
    extract_domain,
    extract_urls_from_text,
    is_shortener_url,
)

logger = structlog.get_logger(__name__)

#: Platforms whose records are already scraped URLs — skip entirely.
_SKIP_PLATFORMS: frozenset[str] = frozenset({"domain_crawler"})

#: Platforms where ``url`` is only a self-reference for *video* content_type.
#: Comments on these platforms have a permalink ``url`` that should not be
#: extracted; their ``text_content`` is still scanned for external links.
_VIDEO_PLATFORMS: frozenset[str] = frozenset({"youtube", "tiktok"})

#: Platforms where the record's ``url`` is an outbound target link rather
#: than a post permalink.  For these the URL is added by the structured
#: extractor as ``type="structured"`` and MUST NOT be re-added as
#: ``self_reference``.
_OUTBOUND_URL_PLATFORMS: frozenset[str] = frozenset({"google_search"})


def _extract_structured_urls(platform: str, raw_metadata: dict[str, Any]) -> list[str]:
    """Extract URLs from platform-specific structured fields in raw_metadata.

    Args:
        platform: The platform identifier.
        raw_metadata: The record's raw_metadata dict.

    Returns:
        List of raw URL strings found in structured fields.
    """
    urls: list[str] = []

    if platform == "x_twitter":
        # entities.urls[].expanded_url — the real URL behind t.co shortlinks
        entities = raw_metadata.get("entities") or {}
        for entry in entities.get("urls") or []:
            expanded = entry.get("expanded_url")
            if expanded:
                urls.append(expanded)

    elif platform == "bluesky":
        # facets[].features[].uri — rich text link annotations
        for facet in raw_metadata.get("facets") or []:
            for feature in facet.get("features") or []:
                uri = feature.get("uri")
                if uri and feature.get("$type") == "app.bsky.richtext.facet#link":
                    urls.append(uri)
        # embed.external.uri — embedded link cards
        embed = raw_metadata.get("embed") or {}
        if embed.get("$type") == "app.bsky.embed.external#view":
            external = embed.get("external") or {}
            uri = external.get("uri")
            if uri:
                urls.append(uri)

    elif platform == "openrouter":
        # citations[].url — AI-cited source URLs
        for citation in raw_metadata.get("citations") or []:
            url = citation.get("url")
            if url:
                urls.append(url)

    elif platform == "google_search":
        # link — the organic search result's target URL.  Treated as a
        # structured outbound link (not a self-reference) so downstream
        # filters that exclude self-references still see Google Search
        # target domains.
        link = raw_metadata.get("link")
        if link:
            urls.append(link)

    return urls


class UrlExtractor(ContentEnricher):
    """Extract, clean, and catalog URLs found within content records."""

    enricher_name = "url_extraction"

    def is_applicable(self, record: dict[str, Any]) -> bool:
        """Return True if the record contains extractable URL data.

        Skips ``domain_crawler`` records entirely.  Otherwise applicable if
        the record has a usable ``url`` field, ``text_content`` longer
        than 10 characters, or structured URL fields in ``raw_metadata``.

        Args:
            record: A content record dict.

        Returns:
            True when URL extraction should run on this record.
        """
        platform = record.get("platform", "")
        if platform in _SKIP_PLATFORMS:
            return False

        if self._should_include_url(record):
            return True
        text = record.get("text_content") or ""
        if len(text) > 10:
            return True
        # Check for structured URL fields
        raw_metadata = record.get("raw_metadata") or {}
        if _extract_structured_urls(platform, raw_metadata):
            return True
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _should_include_url(record: dict[str, Any]) -> bool:
        """Decide whether the record's ``url`` should be added as ``self_reference``.

        For video platforms (YouTube, TikTok) only video posts get their
        ``url`` extracted as a self-reference.  Comments have a permalink
        URL back to the platform which is not useful to extract.

        For ``google_search`` the ``url`` column holds the outbound search
        target (set from ``raw_metadata['link']``).  It is added via the
        structured-field path instead, so we skip the self-reference add
        here to avoid duplicating it under the wrong type label.

        For all other platforms, the ``url`` is included unconditionally.
        """
        url = record.get("url")
        if not url:
            return False

        platform = record.get("platform", "")
        if platform in _VIDEO_PLATFORMS:
            return record.get("content_type") == "video"
        if platform in _OUTBOUND_URL_PLATFORMS:
            return False

        return True

    async def enrich(self, record: dict[str, Any]) -> dict[str, Any]:
        """Extract URLs from the record.

        Args:
            record: A content record dict.

        Returns:
            Dict with keys ``urls_found``, ``urls_after_cleaning``,
            ``extracted_at``, and ``urls`` (list of url detail dicts).
        """
        urls_data: list[dict[str, str | None]] = []
        seen_cleaned: set[str] = set()

        def _add_url(raw_url: str, url_type: str) -> None:
            cleaned = clean_url(raw_url)
            if not cleaned or cleaned in seen_cleaned:
                return
            # Drop URL shorteners (t.co, bit.ly, ...).  They mask the real
            # destination and would otherwise aggregate into a single
            # super-node in domain networks.  Structured extractors
            # (``entities.urls[].expanded_url`` for Twitter, etc.) already
            # surface the expanded URL directly when the upstream source
            # provides it.
            if is_shortener_url(cleaned):
                return
            seen_cleaned.add(cleaned)
            urls_data.append({
                "raw": raw_url,
                "cleaned": cleaned,
                "domain": extract_domain(cleaned),
                "type": url_type,
            })

        # Include the record's own URL when applicable
        if self._should_include_url(record):
            _add_url(record["url"], "self_reference")

        # Extract URLs from text_content
        text = record.get("text_content") or ""
        if len(text) > 10:
            for raw_url in extract_urls_from_text(text):
                _add_url(raw_url, "text_extracted")

        # Extract URLs from platform-specific structured fields
        platform = record.get("platform", "")
        raw_metadata = record.get("raw_metadata") or {}
        for raw_url in _extract_structured_urls(platform, raw_metadata):
            _add_url(raw_url, "structured")

        return {
            "urls_found": len(urls_data),
            "urls_after_cleaning": len([u for u in urls_data if u["cleaned"]]),
            "extracted_at": datetime.now(tz=UTC).isoformat(),
            "urls": urls_data,
        }

    def write_relational(
        self,
        record: dict[str, Any],
        enrichment_result: dict[str, Any],
    ) -> None:
        """Write extracted URLs to the ``extracted_urls`` relational table.

        Called by the task loop after ``write_enrichment()`` succeeds.
        Uses synchronous DB session (psycopg2) for Celery compatibility.

        Args:
            record: The content record dict (must include ``id``,
                ``published_at``, ``platform``, ``raw_metadata``).
            enrichment_result: The dict returned by :meth:`enrich`.
        """
        from issue_observatory.workers._enrichment_helpers import write_extracted_urls

        urls_data: list[dict[str, Any]] = enrichment_result.get("urls", [])
        if not urls_data:
            return

        record_id = record.get("id")
        published_at = record.get("published_at")
        platform = record.get("platform", "")
        query_design_id = record.get("query_design_id")
        project_id = record.get("project_id")

        # Extract search_terms_matched from raw_metadata
        raw_metadata = record.get("raw_metadata") or {}
        search_terms: list[str] = raw_metadata.get("search_terms_matched") or []
        if isinstance(search_terms, str):
            search_terms = [search_terms]

        write_extracted_urls(
            record_id=str(record_id),
            published_at=published_at,
            urls=urls_data,
            platform=platform,
            query_design_id=str(query_design_id) if query_design_id else None,
            project_id=str(project_id) if project_id else None,
            search_terms_matched=search_terms,
        )
