"""Danish sentiment analysis enricher using the AFINN package.

Uses the AFINN word list to compute sentiment scores for Danish text content.
AFINN is a lexicon-based approach that assigns polarity scores to words.

The enricher:
- Operates on records with text_content and language='da'
- Computes a raw AFINN score (sum of word polarities)
- Normalizes the raw score to [-1.0, 1.0] using tanh
- Labels the sentiment as positive/negative/neutral based on thresholds

Owned by the Core Application Engineer.
"""

from __future__ import annotations

import math
from typing import Any

import structlog

from issue_observatory.analysis.enrichments.base import ContentEnricher, EnrichmentError

logger = structlog.get_logger(__name__)


class SentimentAnalyzer(ContentEnricher):
    """Compute sentiment scores for Danish text using AFINN.

    enricher_name = "sentiment"

    The AFINN lexicon assigns integer polarity scores to Danish words.
    This enricher sums the scores for all words in the text and normalizes
    the result to a [-1.0, 1.0] range using tanh transformation.

    Sentiment labels:
    - score > 1.0: "positive"
    - score < -1.0: "negative"
    - otherwise: "neutral"

    The enrichment result is stored at ``raw_metadata.enrichments.sentiment``::

        {
            "score": 0.92,           # normalized sentiment score [-1.0, 1.0]
            "raw_score": 8.0,        # raw AFINN sum
            "label": "positive",     # positive|negative|neutral
        }

    When AFINN is not installed, this enricher silently skips applicable
    records and logs a debug message.
    """

    enricher_name = "sentiment"

    def __init__(self) -> None:
        """Initialize the sentiment analyzer with AFINN for Danish."""
        self._afinn_available = False
        self._afinn = None

        try:
            from afinn import Afinn  # type: ignore[import-untyped]

            self._afinn = Afinn(language="da")
            self._afinn_available = True
        except ImportError:
            logger.debug(
                "sentiment_analyzer: afinn package not installed; enricher will be skipped"
            )

    # ------------------------------------------------------------------
    # ContentEnricher interface
    # ------------------------------------------------------------------

    def is_applicable(self, record: dict[str, Any]) -> bool:
        """Return True if the record has Danish text content and AFINN is available.

        Args:
            record: A content record dict with keys matching ORM column names.

        Returns:
            True when language='da', text_content is non-empty, and AFINN
            is installed.
        """
        if not self._afinn_available:
            return False

        language: str | None = record.get("language")
        text_content: str | None = record.get("text_content")

        is_danish = language == "da"
        has_text = bool(text_content and text_content.strip())

        return is_danish and has_text

    async def enrich(self, record: dict[str, Any]) -> dict[str, Any]:
        """Compute sentiment score for Danish text.

        Args:
            record: A content record dict. Must contain text_content.

        Returns:
            Dict with keys:
            - ``score`` (float): normalized sentiment [-1.0, 1.0]
            - ``raw_score`` (float): raw AFINN sum
            - ``label`` (str): "positive", "negative", or "neutral"

        Raises:
            EnrichmentError: If AFINN raises an unexpected error.
        """
        text: str = record.get("text_content") or ""
        record_id = record.get("id", "<unknown>")
        log = logger.bind(enricher=self.enricher_name, record_id=str(record_id))

        if not self._afinn_available or self._afinn is None:
            raise EnrichmentError("AFINN package is not installed")

        try:
            # Compute raw AFINN score (sum of word polarities)
            raw_score = float(self._afinn.score(text))

            # Normalize to [-1.0, 1.0] using tanh
            # tanh naturally compresses large scores while preserving directionality
            normalized_score = math.tanh(raw_score / 10.0)

            # Determine sentiment label based on normalized score
            if normalized_score > 0.1:  # threshold: raw_score > ~1.0
                label = "positive"
            elif normalized_score < -0.1:  # threshold: raw_score < ~-1.0
                label = "negative"
            else:
                label = "neutral"

            log.debug(
                "sentiment_analyzer: computed sentiment",
                raw_score=round(raw_score, 2),
                normalized_score=round(normalized_score, 4),
                label=label,
            )

            return {
                "score": round(normalized_score, 4),
                "raw_score": round(raw_score, 2),
                "label": label,
            }

        except Exception as exc:
            log.warning("sentiment_analyzer: AFINN error", error=str(exc))
            raise EnrichmentError(f"AFINN sentiment analysis failed: {exc}") from exc
