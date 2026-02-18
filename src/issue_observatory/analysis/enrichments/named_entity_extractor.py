"""Named entity extraction enricher for actor role identification.

Extracts persons, organizations, and locations from text_content and
classifies them by role in the text (speaker, mentioned, quoted_source).

This implementation is a STUB that defines the enrichment storage contract
and interface.  Full NER requires spaCy with da_core_news_lg or DaCy.

Install NER dependencies with:
    pip install 'issue-observatory[nlp-ner]'

Owned by the Core Application Engineer.
"""

from __future__ import annotations

from typing import Any

import structlog

from issue_observatory.analysis.enrichments.base import ContentEnricher, EnrichmentError

logger = structlog.get_logger(__name__)


class NamedEntityExtractor(ContentEnricher):
    """Extract named entities and classify their roles in content.

    enricher_name = "actor_roles"

    Output stored in raw_metadata.enrichments.actor_roles:
    {
        "entities": [
            {
                "name": "Mette Frederiksen",
                "entity_type": "PERSON",   # PERSON, ORG, GPE, LOC
                "role": "mentioned",       # mentioned, speaker, quoted_source
                "confidence": 0.95,
                "context": "...surrounding text..."
            },
            ...
        ],
        "model": "stub",   # "da_core_news_lg", "dacy_large", "stub"
        "processed_at": "2026-02-18T..."
    }

    Role classification patterns (for future full implementation):
    - "speaker": entity appears before "sagde", "siger", "mener", "udtaler"
    - "quoted_source": entity appears after "ifølge", "citat:", "udtalte"
    - "mentioned": default for all other occurrences
    """

    enricher_name = "actor_roles"

    # Danish patterns for role classification (future use).
    _SPEAKER_PATTERNS = ["sagde", "siger", "mener", "udtaler", "forklarede", "tilføjer"]
    _QUOTED_PATTERNS = ["ifølge", "ifølge som", "udtaler sig til"]

    def is_applicable(self, record: dict[str, Any]) -> bool:
        """Applicable when text_content is present and longer than 100 chars.

        Args:
            record: A content record dict with keys matching ORM column names.

        Returns:
            True when ``text_content`` is a string with more than 100 characters.
        """
        text = record.get("text_content") or ""
        return len(text) > 100

    async def enrich(self, record: dict[str, Any]) -> dict[str, Any]:
        """Attempt NER; return stub result if spaCy unavailable.

        Returns the JSONB structure defined in the class docstring.
        In stub mode, returns an empty entity list with model="stub".

        Args:
            record: A content record dict.  Must contain ``text_content``.

        Returns:
            Dict with keys ``entities`` (list), ``model`` (str), and
            ``processed_at`` (ISO 8601 string).  Stored at
            ``raw_metadata.enrichments.actor_roles``.

        Raises:
            EnrichmentError: If spaCy raises an unexpected error during
                entity extraction (does not apply in stub mode).
        """
        from datetime import datetime, timezone

        processed_at = datetime.now(timezone.utc).isoformat()

        try:
            import spacy  # noqa: F401
            # Full implementation placeholder:
            # nlp = spacy.load("da_core_news_lg")
            # doc = nlp(record.get("text_content", ""))
            # entities = [self._classify_entity(ent, doc) for ent in doc.ents]
            raise ImportError("spaCy NER not configured — using stub")
        except ImportError:
            logger.debug(
                "named_entity_extractor.stub_mode",
                record_id=str(record.get("id", "")),
                reason="spaCy not installed or da_core_news_lg not available",
            )
            return {
                "entities": [],
                "model": "stub",
                "processed_at": processed_at,
            }
        except Exception as exc:
            raise EnrichmentError(f"NER extraction failed: {exc}") from exc
