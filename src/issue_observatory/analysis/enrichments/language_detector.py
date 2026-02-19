"""Language detector enricher — generalised for any target language.

Uses langdetect (if installed) with a neutral fallback strategy:

- If langdetect is installed, run probabilistic detection and report the top
  result with its confidence score.
- If langdetect is not installed, and the caller configured exactly one
  expected language, assume that language (confidence: None, detector:
  "heuristic_single_lang").  This preserves the original Danish-only
  behaviour for Danish-only collections.
- Otherwise, return language=None / confidence=None / detector="none".

The enricher also tags each result with an ``expected`` field:
- ``True`` if the detected language is in ``expected_languages``.
- ``False`` if ``expected_languages`` was configured but the detected
  language is not in it.
- ``None`` if no ``expected_languages`` list was provided.

Owned by the Core Application Engineer.

Backwards compatibility: ``DanishLanguageDetector`` remains as an alias for
``LanguageDetector`` so existing imports continue to work without change.
"""

from __future__ import annotations

from typing import Any

import structlog

from issue_observatory.analysis.enrichments.base import ContentEnricher, EnrichmentError

logger = structlog.get_logger(__name__)


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


class LanguageDetector(ContentEnricher):
    """Detect language of content records lacking a language tag.

    enricher_name = "language_detection"

    Runs langdetect on text_content when the platform has not provided a
    language tag.  Falls back to a neutral strategy when langdetect is not
    installed:

    - If exactly one ``expected_languages`` entry is configured, that
      language is assumed (confidence: None, detector:
      "heuristic_single_lang").
    - Otherwise, returns language=None / confidence=None / detector="none".

    The enrichment result is stored at
    ``raw_metadata.enrichments.language_detection``::

        {
            "language": "da",
            "confidence": 0.97,
            "detector": "langdetect",
            "expected": True,
        }

    When using a fallback detector, ``confidence`` is ``null`` and
    ``detector`` is either ``"heuristic_single_lang"`` or ``"none"``.

    The ``expected`` field is:
    - ``True`` / ``False`` when ``expected_languages`` is provided.
    - ``None`` when no ``expected_languages`` list was configured.

    Args:
        expected_languages: Optional list of ISO 639-1 language codes that
            the query design expects to collect.  Used to compute the
            ``expected`` tag on each enrichment result.
    """

    enricher_name = "language_detection"

    def __init__(self, expected_languages: list[str] | None = None) -> None:
        """Initialise the detector with an optional expected-language list.

        Args:
            expected_languages: ISO 639-1 codes for languages the owning
                query design targets (e.g. ``["da"]`` for a Danish-only
                collection).  When provided, enrichment results include an
                ``"expected"`` boolean field.  Pass ``None`` (the default)
                to omit the ``"expected"`` field entirely.
        """
        self.expected_languages: list[str] = expected_languages or []

    # ------------------------------------------------------------------
    # ContentEnricher interface
    # ------------------------------------------------------------------

    def is_applicable(self, record: dict[str, Any]) -> bool:
        """Return True if the record lacks a language tag but has text.

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
        """Detect language; return a detection result dict.

        Tries langdetect first.  When langdetect is not installed, falls
        back to a single-language assumption (if exactly one
        ``expected_languages`` entry exists) or returns ``language=None``.

        Args:
            record: A content record dict.  Must contain ``text_content``.

        Returns:
            Dict with keys:
            - ``language`` (str or None): detected ISO 639-1 code.
            - ``confidence`` (float or None): detector confidence.
            - ``detector`` (str): ``"langdetect"``,
              ``"heuristic_single_lang"``, or ``"none"``.
            - ``expected`` (bool or None): whether the detected language
              appears in ``expected_languages``; ``None`` when
              ``expected_languages`` is empty.

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
            return self._build_result(
                language=lang_code,
                confidence=round(confidence, 4),
                detector="langdetect",
            )
        except ImportError:
            log.debug(
                "language_detector: langdetect not installed; using fallback"
            )
        except EnrichmentError as exc:
            log.warning(
                "language_detector: langdetect error; using fallback",
                error=str(exc),
            )

        # --- Neutral fallback ---
        if len(self.expected_languages) == 1:
            # Safe assumption: a single-language collection is almost
            # certainly in that language when the text is very short or
            # contains no distinctive n-grams.
            assumed = self.expected_languages[0]
            log.debug(
                "language_detector: single-lang heuristic",
                assumed_lang=assumed,
            )
            return self._build_result(
                language=assumed,
                confidence=None,
                detector="heuristic_single_lang",
            )

        # No library and no safe assumption — report unknown.
        log.debug("language_detector: no detector available; returning unknown")
        return self._build_result(
            language=None,
            confidence=None,
            detector="none",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_result(
        self,
        language: str | None,
        confidence: float | None,
        detector: str,
    ) -> dict[str, Any]:
        """Assemble the enrichment result dict.

        Appends the ``expected`` field when ``expected_languages`` is
        configured.

        Args:
            language: Detected ISO 639-1 code, or ``None`` when unknown.
            confidence: Detector confidence in [0, 1], or ``None``.
            detector: Name of the detection strategy used.

        Returns:
            Enrichment result dict ready to be stored in
            ``raw_metadata.enrichments.language_detection``.
        """
        result: dict[str, Any] = {
            "language": language,
            "confidence": confidence,
            "detector": detector,
        }

        if self.expected_languages:
            result["expected"] = (
                language in self.expected_languages if language is not None else False
            )
        else:
            result["expected"] = None

        return result


# ---------------------------------------------------------------------------
# Backwards compatibility alias
# ---------------------------------------------------------------------------

DanishLanguageDetector = LanguageDetector
"""Deprecated alias for :class:`LanguageDetector`.

Kept so that existing imports of ``DanishLanguageDetector`` continue to work
without modification.  New code should import :class:`LanguageDetector`
directly.

A plain ``DanishLanguageDetector()`` call now creates a
``LanguageDetector(expected_languages=None)`` instance.  To restore the
original Danish-only behaviour (single-language heuristic fallback), pass
``expected_languages=["da"]`` explicitly::

    detector = LanguageDetector(expected_languages=["da"])
"""
