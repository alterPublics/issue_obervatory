"""Danish language detector enricher.

Uses langdetect (if installed) with a simple character-frequency heuristic
as a fallback.

The heuristic counts occurrences of Danish-specific characters (ae, o-slash,
aa) in the text.  If more than 0.5% of all characters are Danish-specific,
the text is classified as likely Danish.

Owned by the Core Application Engineer.
"""

from __future__ import annotations

from typing import Any

import structlog

from issue_observatory.analysis.enrichments.base import ContentEnricher, EnrichmentError

logger = structlog.get_logger(__name__)

# Danish-specific characters (lower and upper case).
_DANISH_CHARS: frozenset[str] = frozenset("æøåÆØÅ")

# Threshold: fraction of characters that must be Danish-specific.
_HEURISTIC_THRESHOLD: float = 0.005


def _detect_with_langdetect(text: str) -> tuple[str, float]:
    """Attempt language detection using the langdetect library.

    Args:
        text: The text to classify.

    Returns:
        Tuple of (language_code, confidence) where confidence is in [0, 1].

    Raises:
        ImportError: If langdetect is not installed.
        EnrichmentError: If langdetect raises an internal error.
    """
    try:
        from langdetect import DetectorFactory, detect_langs  # type: ignore[import-untyped]

        # Make detection deterministic across runs.
        DetectorFactory.seed = 0

        results = detect_langs(text)
        if not results:
            raise EnrichmentError("langdetect returned no results")

        top = results[0]
        return top.lang, float(top.prob)
    except ImportError:
        raise
    except Exception as exc:
        raise EnrichmentError(f"langdetect failed: {exc}") from exc


def _detect_with_heuristic(text: str) -> dict[str, Any]:
    """Classify text as Danish using a simple character-frequency heuristic.

    Counts the proportion of Danish-specific characters (ae, o-slash, aa).
    If > 0.5% of all characters are Danish-specific, the text is returned
    as likely Danish.  Otherwise language is left as None.

    Args:
        text: The text to classify.

    Returns:
        Enrichment result dict with ``language``, ``confidence``, and
        ``detector`` fields.  ``language`` is ``"da"`` when the threshold
        is met, otherwise ``None``.  ``confidence`` is always ``None``
        for the heuristic detector.
    """
    if not text:
        return {"language": None, "confidence": None, "detector": "heuristic"}

    danish_count = sum(1 for ch in text if ch in _DANISH_CHARS)
    ratio = danish_count / len(text)

    if ratio > _HEURISTIC_THRESHOLD:
        return {"language": "da", "confidence": None, "detector": "heuristic"}

    return {"language": None, "confidence": None, "detector": "heuristic"}


class DanishLanguageDetector(ContentEnricher):
    """Detect language of content records lacking a language tag.

    enricher_name = "language_detection"

    Runs langdetect on text_content when the platform has not provided a
    language tag.  Falls back to a Danish-character heuristic if langdetect
    is not installed.

    The enrichment result is a dict stored at
    ``raw_metadata.enrichments.language_detection``::

        {"language": "da", "confidence": 0.97, "detector": "langdetect"}

    When using the heuristic fallback, ``confidence`` is ``null`` and
    ``detector`` is ``"heuristic"``.
    """

    enricher_name = "language_detection"

    def is_applicable(self, record: dict[str, Any]) -> bool:
        """True if the record has no language tag but has non-empty text_content.

        Args:
            record: A content record dict with keys matching ORM column names.

        Returns:
            True when ``language`` is None or empty AND ``text_content`` is
            a non-empty string.
        """
        language: str | None = record.get("language")
        text_content: str | None = record.get("text_content")

        language_missing = not language  # None or empty string
        has_text = bool(text_content and text_content.strip())
        return language_missing and has_text

    async def enrich(self, record: dict[str, Any]) -> dict[str, Any]:
        """Detect language; return detection result dict.

        Tries langdetect first.  If it is not installed, falls back to the
        Danish-character heuristic.

        Args:
            record: A content record dict.  Must contain ``text_content``.

        Returns:
            Dict with keys ``language`` (str or None), ``confidence``
            (float or None), and ``detector`` (``"langdetect"`` or
            ``"heuristic"``).

        Raises:
            EnrichmentError: If langdetect raises an unexpected internal error.
        """
        text: str = record.get("text_content") or ""
        record_id = record.get("id", "<unknown>")
        log = logger.bind(enricher=self.enricher_name, record_id=str(record_id))

        # --- Try langdetect ---
        try:
            lang_code, confidence = _detect_with_langdetect(text)
            log.debug(
                "language_detector: langdetect result",
                lang=lang_code,
                confidence=round(confidence, 4),
            )
            return {
                "language": lang_code,
                "confidence": round(confidence, 4),
                "detector": "langdetect",
            }
        except ImportError:
            log.debug(
                "language_detector: langdetect not installed; using heuristic"
            )
        except EnrichmentError as exc:
            log.warning(
                "language_detector: langdetect error; falling back to heuristic",
                error=str(exc),
            )

        # --- Heuristic fallback ---
        result = _detect_with_heuristic(text)
        log.debug(
            "language_detector: heuristic result",
            lang=result.get("language"),
        )
        return result
