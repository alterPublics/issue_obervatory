"""Article text extraction from raw HTML.

Primary extractor: ``trafilatura`` (state-of-the-art boilerplate removal).
Fallback: stdlib ``html.parser`` with naive tag stripping when trafilatura
returns no content (e.g. very short pages or heavily obfuscated sites).
"""

from __future__ import annotations

import html as html_module
import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser

from issue_observatory.scraper.config import MAX_CONTENT_BYTES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------


@dataclass
class ExtractedContent:
    """Result of extracting article content from an HTML page.

    Attributes:
        text: Cleaned article text, or ``None`` if extraction failed.
        title: Page title, or ``None`` if not detected.
        language: ISO 639-1 language code detected by trafilatura, or ``None``.
    """

    text: str | None
    title: str | None
    language: str | None


# ---------------------------------------------------------------------------
# HTML tag-stripping fallback
# ---------------------------------------------------------------------------


class _TagStripper(HTMLParser):
    """Minimal HTML parser that strips tags and collects visible text."""

    _SKIP_TAGS: frozenset[str] = frozenset(
        {"script", "style", "noscript", "head", "meta", "link"}
    )

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth: int = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:  # type: ignore[override]
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def get_text(self) -> str:
        raw = " ".join(self._chunks)
        # Collapse whitespace runs
        return re.sub(r"\s+", " ", html_module.unescape(raw)).strip()


def _strip_tags(html: str) -> str:
    """Strip HTML tags and return visible text using stdlib HTMLParser."""
    stripper = _TagStripper()
    try:
        stripper.feed(html)
    except Exception:  # noqa: BLE001
        pass
    return stripper.get_text()


# ---------------------------------------------------------------------------
# Public extraction function
# ---------------------------------------------------------------------------


def extract_from_html(html: str, url: str) -> ExtractedContent:
    """Extract article text, title, and language from raw HTML.

    Uses ``trafilatura`` as the primary extractor.  Falls back to a naive
    tag-stripping approach if trafilatura returns no content.

    Args:
        html: Raw HTML string (may be partial or malformed).
        url: Canonical URL of the page (used by trafilatura for heuristics).

    Returns:
        An :class:`ExtractedContent` instance.  ``text`` may be ``None``
        if no readable content could be extracted.
    """
    text: str | None = None
    title: str | None = None
    language: str | None = None

    # --- Primary: trafilatura -------------------------------------------
    try:
        import trafilatura  # type: ignore[import-untyped]

        result = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            output_format="txt",
        )
        if result:
            text = result

        # Extract metadata separately for title + language
        meta = trafilatura.extract_metadata(html, default_url=url)
        if meta:
            title = getattr(meta, "title", None) or None
            language = getattr(meta, "language", None) or None

    except ImportError:
        logger.warning(
            "scraper: trafilatura not installed; falling back to tag stripping"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("scraper: trafilatura extraction failed: %s", exc)

    # --- Fallback: naive tag stripping ----------------------------------
    if not text:
        stripped = _strip_tags(html)
        text = stripped if stripped else None

    # --- Post-processing ------------------------------------------------
    if text:
        # Remove NUL bytes (PostgreSQL rejects them in text columns)
        text = text.replace("\x00", "")
        # Cap at max content size
        encoded = text.encode("utf-8")
        if len(encoded) > MAX_CONTENT_BYTES:
            text = encoded[:MAX_CONTENT_BYTES].decode("utf-8", errors="ignore")
            logger.debug("scraper: truncated extracted text to %d bytes for %s", MAX_CONTENT_BYTES, url)

    return ExtractedContent(text=text, title=title, language=language)
