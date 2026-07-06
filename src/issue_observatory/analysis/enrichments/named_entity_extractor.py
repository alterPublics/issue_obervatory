"""Named entity extraction enricher for actor role identification.

Extracts persons, organizations, and locations from text_content and
classifies them by role in the text (speaker, mentioned, quoted_source).

Full NER uses spaCy ``da_core_news_lg`` when it is installed.  If the model
is not available the enricher falls back to stub mode (empty entity list)
so that other enrichers in the pipeline are not blocked.

Install NER dependencies with:
    pip install 'issue-observatory[nlp-ner]'

Owned by the Core Application Engineer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from issue_observatory.analysis.enrichments.base import ContentEnricher, EnrichmentError

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# spaCy model singleton — shared with ner_extraction.py query-time path
# ---------------------------------------------------------------------------

_nlp_model: Any = None
_nlp_load_attempted: bool = False


def _get_nlp() -> Any:
    """Return the spaCy ``da_core_news_lg`` model, loading it once (singleton).

    Returns:
        The loaded spaCy Language object, or ``None`` if spaCy or the model
        is not installed.
    """
    global _nlp_model, _nlp_load_attempted
    if _nlp_load_attempted:
        return _nlp_model
    _nlp_load_attempted = True
    try:
        import spacy

        _nlp_model = spacy.load("da_core_news_lg")
        logger.info("named_entity_extractor.model_loaded", model="da_core_news_lg")
    except (ImportError, OSError) as exc:
        logger.warning(
            "named_entity_extractor.model_unavailable",
            error=str(exc),
            reason="spaCy not installed or da_core_news_lg not available",
        )
        _nlp_model = None
    return _nlp_model


# ---------------------------------------------------------------------------
# Enricher
# ---------------------------------------------------------------------------

_CONTEXT_WINDOW = 80  # characters on each side of entity span for context

# Danish verb patterns that indicate the preceding entity is a speaker.
_SPEAKER_PATTERNS: frozenset[str] = frozenset(
    ["sagde", "siger", "mener", "udtaler", "forklarede", "tilføjer"]
)

# Danish prepositions / phrases that introduce a quoted source.
_QUOTED_PATTERNS: frozenset[str] = frozenset(["ifølge", "ifølge som", "udtaler sig til"])

_RELEVANT_LABELS: frozenset[str] = frozenset(["PER", "ORG", "GPE", "LOC"])

# Map spaCy da_core_news_lg label codes → universal schema labels.
_LABEL_MAP: dict[str, str] = {
    "PER": "PERSON",
    "ORG": "ORG",
    "GPE": "GPE",
    "LOC": "LOC",
}


def _classify_role(ent_text: str, full_text: str) -> str:
    """Heuristically classify an entity's role from surrounding text.

    Checks a small window of text after the entity for Danish speaker verbs
    and before the entity for quotation-source phrases.

    Args:
        ent_text: The surface form of the entity.
        full_text: The full document text.

    Returns:
        One of ``"speaker"``, ``"quoted_source"``, or ``"mentioned"``.
    """
    idx = full_text.find(ent_text)
    if idx == -1:
        return "mentioned"

    after_start = idx + len(ent_text)
    after_snippet = full_text[after_start : after_start + 60].lower()
    before_snippet = full_text[max(0, idx - 60) : idx].lower()

    for pattern in _SPEAKER_PATTERNS:
        if pattern in after_snippet:
            return "speaker"
    for pattern in _QUOTED_PATTERNS:
        if pattern in before_snippet:
            return "quoted_source"
    return "mentioned"


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
                "confidence": 1.0,
                "context": "...surrounding text..."
            },
            ...
        ],
        "model": "da_core_news_lg",   # or "stub"
        "processed_at": "2026-02-18T..."
    }

    Role classification patterns:
    - "speaker": entity appears before "sagde", "siger", "mener", "udtaler"
    - "quoted_source": entity appears after "ifølge", "citat:", "udtalte"
    - "mentioned": default for all other occurrences
    """

    enricher_name = "actor_roles"

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
        """Run spaCy NER on text_content; fall back to stub if unavailable.

        When ``da_core_news_lg`` is installed the enricher extracts PERSON,
        ORG, GPE, and LOC entities and classifies each by its role in the
        text using Danish heuristic patterns.  When spaCy is not available
        the enricher returns an empty entity list with ``model="stub"`` so
        the pipeline can continue without error.

        Args:
            record: A content record dict.  Must contain ``text_content``.

        Returns:
            Dict with keys ``entities`` (list), ``model`` (str), and
            ``processed_at`` (ISO 8601 string).  Stored at
            ``raw_metadata.enrichments.actor_roles``.

        Raises:
            EnrichmentError: If spaCy raises an unexpected runtime error
                during entity extraction (does not apply in stub mode).
        """
        processed_at = datetime.now(UTC).isoformat()
        text = record.get("text_content") or ""

        nlp = _get_nlp()

        if nlp is None:
            logger.debug(
                "named_entity_extractor.stub_mode",
                record_id=str(record.get("id", "")),
            )
            return {
                "entities": [],
                "model": "stub",
                "processed_at": processed_at,
            }

        try:
            doc = nlp(text)
            entities: list[dict[str, Any]] = []
            for ent in doc.ents:
                if ent.label_ not in _RELEVANT_LABELS:
                    continue
                name = ent.text.strip()
                if not name or len(name) < 2:
                    continue
                start = max(0, ent.start_char - _CONTEXT_WINDOW)
                end = min(len(text), ent.end_char + _CONTEXT_WINDOW)
                entities.append(
                    {
                        "name": name,
                        "entity_type": _LABEL_MAP.get(ent.label_, ent.label_),
                        "role": _classify_role(name, text),
                        "confidence": 1.0,
                        "context": text[start:end],
                    }
                )
            logger.debug(
                "named_entity_extractor.done",
                record_id=str(record.get("id", "")),
                entity_count=len(entities),
            )
            return {
                "entities": entities,
                "model": "da_core_news_lg",
                "processed_at": processed_at,
            }
        except Exception as exc:
            raise EnrichmentError(f"NER extraction failed: {exc}") from exc
