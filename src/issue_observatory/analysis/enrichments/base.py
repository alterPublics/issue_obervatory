"""Abstract base class for content enrichers.

Owned by the Core Application Engineer.

Enrichers are pluggable post-collection processors that add derived data to
content records without requiring schema migrations.  Each enricher writes
its output into ``raw_metadata.enrichments.{enricher_name}`` as a JSONB
sub-object.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ContentEnricher(ABC):
    """Pluggable enricher interface for post-collection content enhancement.

    Enrichments are stored in raw_metadata.enrichments.{enricher_name} as
    a JSONB sub-object.  This keeps enrichment data alongside the content
    record without requiring schema migrations for each new enricher.

    Implementors must override enricher_name, enrich(), and is_applicable().

    Usage (Celery task context)::

        enricher = DanishLanguageDetector()
        for record in records:
            if enricher.is_applicable(record):
                result = await enricher.enrich(record)
                # Merge into raw_metadata.enrichments.{enricher.enricher_name}
    """

    enricher_name: str  # must be set by subclasses; used as key in enrichments dict

    @abstractmethod
    async def enrich(self, record: dict[str, Any]) -> dict[str, Any]:
        """Run the enrichment on a content record dict.

        Args:
            record: A content record dict with keys matching ORM column names.

        Returns:
            A dict of enrichment data to store in
            ``raw_metadata.enrichments.{self.enricher_name}``.
            Example: ``{"language": "da", "confidence": 0.97}``

        Raises:
            EnrichmentError: If enrichment fails and the error should be logged.
        """

    @abstractmethod
    def is_applicable(self, record: dict[str, Any]) -> bool:
        """Whether this enricher should run on this record.

        Args:
            record: A content record dict.

        Returns:
            True if the record meets the criteria for this enricher.
        """

    def __repr__(self) -> str:
        """Return a human-readable representation of this enricher."""
        return f"{self.__class__.__name__}(enricher_name={self.enricher_name!r})"


class EnrichmentError(Exception):
    """Raised when an enrichment fails in a recoverable way."""
