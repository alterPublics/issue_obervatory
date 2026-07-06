"""Named entity extraction for content analysis.

Hybrid strategy:
1. Check raw_metadata.enrichments.actor_roles for pre-computed NER results
2. For records without enrichment, run spaCy da_core_news_lg at query time
3. Cache loaded spaCy model as module-level singleton
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.core.queries.content_filters import (
    ContentFilterSpec,
    build_content_where_sql,
)

logger = structlog.get_logger(__name__)

# Module-level singleton for spaCy model
_nlp_model = None
_nlp_load_attempted = False


def _get_nlp() -> Any:
    """Load spaCy Danish model (singleton)."""
    global _nlp_model, _nlp_load_attempted
    if _nlp_load_attempted:
        return _nlp_model
    _nlp_load_attempted = True
    try:
        import spacy
        _nlp_model = spacy.load("da_core_news_lg")
        logger.info("spacy_model_loaded", model="da_core_news_lg")
    except (ImportError, OSError) as exc:
        logger.warning("spacy_unavailable", error=str(exc))
        _nlp_model = None
    return _nlp_model


async def extract_named_entities(
    db: AsyncSession,
    query_design_ids: list[uuid.UUID] | None = None,
    platform: str | None = None,
    arena_category: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    entity_types: list[str] | None = None,
    batch_size: int = 200,
) -> list[dict]:
    """Extract named entities from content records.

    Uses a hybrid approach: checks for pre-computed enrichments first,
    falls back to spaCy query-time extraction.

    Args:
        db: Async database session.
        query_design_ids: Filter by query designs.
        platform: Filter by platform.
        arena_category: Filter by arena category.
        date_from: Start date filter.
        date_to: End date filter.
        entity_types: Entity types to include (PERSON, ORG, GPE, LOC).
            Defaults to all four.
        batch_size: Processing batch size.

    Returns:
        List of dicts with entity name, type, and doc_count.
    """
    if entity_types is None:
        entity_types = ["PERSON", "ORG", "GPE", "LOC"]

    entity_type_set = set(entity_types)

    params: dict[str, Any] = {}
    _arena_ner = (
        [arena_category]
        if isinstance(arena_category, str) and arena_category
        else []
    )
    _platform_ner = (
        [platform] if isinstance(platform, str) and platform else []
    )
    spec_ner = ContentFilterSpec(
        query_design_ids=query_design_ids or [],
        arenas=_arena_ner,
        platforms=_platform_ner,
        date_from=date_from,
        date_to=date_to,
        include_linked=True,
        include_duplicates=False,
        ownership_mode="admin",
    )
    where = build_content_where_sql(spec_ner, table_alias="", params=params)

    # Count total records
    count_sql = text(
        f"SELECT COUNT(*) FROM content_records {where} "
        f"AND text_content IS NOT NULL AND LENGTH(text_content) > 100"
    )
    total = (await db.execute(count_sql, params)).scalar() or 0

    if total == 0:
        return []

    # Accumulate entity frequencies
    entity_counts: dict[tuple[str, str], int] = {}  # (name, type) -> count

    nlp = _get_nlp()

    offset = 0
    while offset < total:
        batch_params = {**params, "_limit": batch_size, "_offset": offset}
        sql = text(
            f"SELECT text_content, raw_metadata FROM content_records {where} "
            f"AND text_content IS NOT NULL AND LENGTH(text_content) > 100 "
            f"ORDER BY published_at DESC LIMIT :_limit OFFSET :_offset"
        )
        rows = (await db.execute(sql, batch_params)).fetchall()
        if not rows:
            break

        texts_to_process: list[str] = []

        for row in rows:
            text_content = row[0]
            raw_meta = row[1] or {}

            # Check for pre-computed enrichments first
            enrichments = raw_meta.get("enrichments", {})
            actor_roles = enrichments.get("actor_roles", {})
            entities_list = actor_roles.get("entities", [])

            if entities_list:
                # Use pre-computed entities
                for ent in entities_list:
                    ent_type = ent.get("entity_type", "")
                    if ent_type in entity_type_set:
                        name = ent.get("name", "").strip()
                        if name:
                            key = (name, ent_type)
                            entity_counts[key] = entity_counts.get(key, 0) + 1
            else:
                # Queue for spaCy processing
                texts_to_process.append(text_content)

        # Process un-enriched texts with spaCy
        if texts_to_process and nlp is not None:
            for doc in nlp.pipe(texts_to_process, batch_size=min(50, len(texts_to_process))):
                for ent in doc.ents:
                    if ent.label_ in entity_type_set:
                        name = ent.text.strip()
                        if name and len(name) > 1:
                            key = (name, ent.label_)
                            entity_counts[key] = entity_counts.get(key, 0) + 1

        offset += batch_size

    # Build result sorted by doc_count descending
    result = [
        {"entity": name, "type": ent_type, "doc_count": count}
        for (name, ent_type), count in entity_counts.items()
    ]
    result.sort(key=lambda x: x["doc_count"], reverse=True)
    return result
