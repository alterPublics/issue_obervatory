"""Pluggable content enrichment pipeline.

Owned by the Core Application Engineer.

Enrichers are post-collection processors that add derived data to content
records without requiring schema migrations.  Each enricher writes its
output into ``raw_metadata.enrichments.{enricher_name}`` as a JSONB
sub-object.

Available enrichers:
- :class:`LanguageDetector` — detects language for any target language using
  langdetect, with a configurable expected-language list that tags results as
  ``expected`` or not.  Accepts optional ``expected_languages`` (ISO 639-1
  list) at construction.
- :class:`DanishLanguageDetector` — deprecated alias for
  :class:`LanguageDetector`; kept for backwards compatibility.
- :class:`NamedEntityExtractor` — extracts named entities and classifies
  actor roles in text (stub; full NER requires the ``nlp-ner`` extra).
- :class:`PropagationEnricher` — GR-08: computes cross-arena temporal
  propagation sequences for near-duplicate clusters, identifying which arena
  published content first and how it spread over time.
- :class:`CoordinationDetector` — GR-11: detects potential coordinated
  inauthentic behaviour (CIB) by flagging near-duplicate clusters where
  multiple distinct authors post near-identical content within a narrow
  time window.
"""

from __future__ import annotations

from issue_observatory.analysis.enrichments.base import ContentEnricher, EnrichmentError
from issue_observatory.analysis.enrichments.coordination_detector import CoordinationDetector
from issue_observatory.analysis.enrichments.language_detector import (
    DanishLanguageDetector,
    LanguageDetector,
)
from issue_observatory.analysis.enrichments.named_entity_extractor import NamedEntityExtractor
from issue_observatory.analysis.enrichments.propagation_detector import PropagationEnricher

__all__ = [
    "ContentEnricher",
    "EnrichmentError",
    "LanguageDetector",
    "DanishLanguageDetector",
    "NamedEntityExtractor",
    "PropagationEnricher",
    "CoordinationDetector",
]
