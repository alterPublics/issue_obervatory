"""Pluggable content enrichment pipeline.

Owned by the Core Application Engineer.

Enrichers are post-collection processors that add derived data to content
records without requiring schema migrations.  Each enricher writes its
output into ``raw_metadata.enrichments.{enricher_name}`` as a JSONB
sub-object.

Available enrichers:
- :class:`DanishLanguageDetector` — detects language, with langdetect or
  a character-frequency heuristic fallback.
- :class:`NamedEntityExtractor` — extracts named entities and classifies
  actor roles in text (stub; full NER requires the ``nlp-ner`` extra).
"""

from __future__ import annotations

from issue_observatory.analysis.enrichments.base import ContentEnricher, EnrichmentError
from issue_observatory.analysis.enrichments.language_detector import DanishLanguageDetector
from issue_observatory.analysis.enrichments.named_entity_extractor import NamedEntityExtractor

__all__ = ["ContentEnricher", "EnrichmentError", "DanishLanguageDetector", "NamedEntityExtractor"]
