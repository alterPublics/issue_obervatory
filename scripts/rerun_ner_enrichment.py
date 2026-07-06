"""Re-run NER enrichment on records that have stub actor_roles.

Records that were enriched while spaCy was not installed have
actor_roles.model = "stub" with empty entity lists. This script
replaces those with real NER extraction using da_core_news_lg,
using spaCy's nlp.pipe() for batch processing.

Usage:
    uv run python scripts/rerun_ner_enrichment.py [--batch-size 500] [--limit 0]
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

import spacy
from sqlalchemy import text

from issue_observatory.core.database import get_sync_session

# Suppress debug logs for cleaner output
logging.basicConfig(level=logging.WARNING)

BATCH_SIZE = 500
_RELEVANT_LABELS = frozenset({"PER", "ORG", "GPE", "LOC"})
_LABEL_MAP = {"PER": "PERSON", "ORG": "ORG", "GPE": "GPE", "LOC": "LOC"}
_SPEAKER_PATTERNS = frozenset(
    ["sagde", "siger", "mener", "udtaler", "forklarede", "tilføjer"]
)
_QUOTED_PATTERNS = frozenset(["ifølge", "ifølge som", "udtaler sig til"])
_CONTEXT_WINDOW = 80


def _classify_role(ent_text: str, full_text: str) -> str:
    idx = full_text.find(ent_text)
    if idx == -1:
        return "mentioned"
    after_snippet = full_text[idx + len(ent_text) : idx + len(ent_text) + 60].lower()
    before_snippet = full_text[max(0, idx - 60) : idx].lower()
    for p in _SPEAKER_PATTERNS:
        if p in after_snippet:
            return "speaker"
    for p in _QUOTED_PATTERNS:
        if p in before_snippet:
            return "quoted_source"
    return "mentioned"


def fetch_stub_records(offset: int, limit: int = BATCH_SIZE) -> list[dict]:
    with get_sync_session() as db:
        stmt = text("""
            SELECT id, text_content, raw_metadata
            FROM content_records
            WHERE text_content IS NOT NULL
              AND LENGTH(text_content) > 100
              AND raw_metadata->'enrichments'->'actor_roles'->>'model' = 'stub'
            ORDER BY id
            LIMIT :limit OFFSET :offset
        """)
        result = db.execute(stmt, {"limit": limit, "offset": offset})
        return [dict(row._mapping) for row in result.fetchall()]


def write_enrichment_batch(items: list[tuple[str, dict[str, Any]]]) -> None:
    if not items:
        return
    with get_sync_session() as db:
        stmt = text("""
            UPDATE content_records
            SET raw_metadata = jsonb_set(
                    jsonb_set(
                        COALESCE(raw_metadata, '{}'::jsonb),
                        '{enrichments}',
                        COALESCE(raw_metadata->'enrichments', '{}'::jsonb),
                        true
                    ),
                    '{enrichments,actor_roles}',
                    CAST(:data AS jsonb),
                    true
                )
            WHERE id = CAST(:record_id AS uuid)
        """)
        for record_id, data in items:
            db.execute(stmt, {"record_id": record_id, "data": json.dumps(data)})
        db.commit()


def process_batch_with_pipe(
    nlp: Any,
    records: list[dict],
) -> list[tuple[str, dict[str, Any]]]:
    """Process a batch of records using spaCy's nlp.pipe() for speed."""
    processed_at = datetime.now(UTC).isoformat()
    texts = [r["text_content"] for r in records]
    record_ids = [str(r["id"]) for r in records]

    results: list[tuple[str, dict[str, Any]]] = []
    for doc, record_id, full_text in zip(
        nlp.pipe(texts, batch_size=64), record_ids, texts, strict=False
    ):
        entities: list[dict[str, Any]] = []
        for ent in doc.ents:
            if ent.label_ not in _RELEVANT_LABELS:
                continue
            name = ent.text.strip()
            if not name or len(name) < 2:
                continue
            start = max(0, ent.start_char - _CONTEXT_WINDOW)
            end = min(len(full_text), ent.end_char + _CONTEXT_WINDOW)
            entities.append({
                "name": name,
                "entity_type": _LABEL_MAP.get(ent.label_, ent.label_),
                "role": _classify_role(name, full_text),
                "confidence": 1.0,
                "context": full_text[start:end],
            })
        results.append((
            record_id,
            {
                "entities": entities,
                "model": "da_core_news_lg",
                "processed_at": processed_at,
            },
        ))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-run NER on stub-enriched records")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=0, help="Max records (0=all)")
    args = parser.parse_args()

    print("Loading spaCy da_core_news_lg...")
    nlp = spacy.load("da_core_news_lg")
    print("Model loaded.")

    total_processed = 0
    total_entities = 0
    offset = 0
    t0 = time.perf_counter()

    while True:
        batch = fetch_stub_records(offset, limit=args.batch_size)
        if not batch:
            break

        results = process_batch_with_pipe(nlp, batch)
        entity_count = sum(len(r[1]["entities"]) for r in results)
        total_entities += entity_count

        write_enrichment_batch(results)

        total_processed += len(batch)
        elapsed = time.perf_counter() - t0
        rate = total_processed / elapsed if elapsed > 0 else 0
        print(
            f"  {total_processed:,} records | "
            f"{total_entities:,} entities | "
            f"{rate:.0f} rec/s | "
            f"{elapsed:.0f}s"
        )

        if args.limit and total_processed >= args.limit:
            break

        # Don't advance offset - processed records no longer match the query
        # (their model changes from "stub" to "da_core_news_lg")

    elapsed = time.perf_counter() - t0
    print(
        f"\nDone: {total_processed:,} records, "
        f"{total_entities:,} entities in {elapsed:.0f}s "
        f"({total_processed / elapsed:.0f} rec/s)"
    )


if __name__ == "__main__":
    main()
