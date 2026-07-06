"""Re-run url_extraction enricher on existing Google Search records.

Fixes records enriched before the url_extractor was taught that Google
Search's ``record.url`` is an outbound target link, not a post permalink.
After this script runs, those target URLs are tagged ``type='structured'``
instead of ``'self_reference'`` — both in the JSONB enrichment payload
(``raw_metadata.enrichments.url_extraction``) and in the ``extracted_urls``
relational table.

For each affected record the script:

1. Calls :meth:`UrlExtractor.enrich` to produce a fresh enrichment dict.
2. Overwrites ``raw_metadata.enrichments.url_extraction`` via ``jsonb_set``.
3. Deletes the record's existing rows in ``extracted_urls`` and re-inserts
   them from the fresh enrichment.  This is required because the unique
   index ``(content_record_id, content_record_published_at, url_cleaned)``
   with ``ON CONFLICT DO NOTHING`` would otherwise leave the stale rows
   in place.

Usage::

    uv run python scripts/rerun_google_search_url_extraction.py
    uv run python scripts/rerun_google_search_url_extraction.py --batch-size 1000
    uv run python scripts/rerun_google_search_url_extraction.py --limit 500
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from typing import Any

from sqlalchemy import text

from issue_observatory.analysis.enrichments.url_extractor import UrlExtractor
from issue_observatory.core.database import get_sync_session

logging.basicConfig(level=logging.WARNING)

BATCH_SIZE = 500


def count_target_records() -> int:
    """Count google_search records that already have a url_extraction enrichment."""
    with get_sync_session() as db:
        stmt = text(
            """
            SELECT COUNT(*) FROM content_records
            WHERE platform = 'google_search'
              AND raw_metadata->'enrichments'->'url_extraction' IS NOT NULL
            """
        )
        return int(db.execute(stmt).scalar() or 0)


def fetch_target_records(offset: int, limit: int) -> list[dict[str, Any]]:
    """Fetch a page of google_search records that have a url_extraction payload.

    Joins through ``collection_runs`` and ``query_designs`` to get
    ``query_design_id`` and ``project_id`` for the ``extracted_urls`` insert.
    """
    with get_sync_session() as db:
        stmt = text(
            """
            SELECT cr.id, cr.published_at, cr.text_content, cr.url,
                   cr.platform, cr.raw_metadata,
                   crun.query_design_id,
                   qd.project_id
            FROM content_records cr
            LEFT JOIN collection_runs crun ON cr.collection_run_id = crun.id
            LEFT JOIN query_designs qd ON crun.query_design_id = qd.id
            WHERE cr.platform = 'google_search'
              AND cr.raw_metadata->'enrichments'->'url_extraction' IS NOT NULL
            ORDER BY cr.id
            LIMIT :limit OFFSET :offset
            """
        )
        result = db.execute(stmt, {"limit": limit, "offset": offset})
        return [dict(row) for row in result.mappings().all()]


def rewrite_record(record: dict[str, Any], enrichment_result: dict[str, Any]) -> None:
    """Overwrite the JSONB enrichment and replace extracted_urls rows atomically."""
    record_id = str(record["id"])
    urls_data: list[dict[str, Any]] = enrichment_result.get("urls", [])

    raw_metadata = record.get("raw_metadata") or {}
    search_terms = raw_metadata.get("search_terms_matched") or []
    if isinstance(search_terms, str):
        search_terms = [search_terms]

    query_design_id = record.get("query_design_id")
    project_id = record.get("project_id")

    with get_sync_session() as db:
        db.execute(
            text(
                """
                UPDATE content_records
                SET raw_metadata = jsonb_set(
                        jsonb_set(
                            COALESCE(raw_metadata, '{}'::jsonb),
                            '{enrichments}',
                            COALESCE(raw_metadata->'enrichments', '{}'::jsonb),
                            true
                        ),
                        '{enrichments,url_extraction}',
                        CAST(:data AS jsonb),
                        true
                    )
                WHERE id = CAST(:record_id AS uuid)
                """
            ),
            {"record_id": record_id, "data": json.dumps(enrichment_result)},
        )

        db.execute(
            text(
                """
                DELETE FROM extracted_urls
                WHERE content_record_id = CAST(:record_id AS uuid)
                """
            ),
            {"record_id": record_id},
        )

        for url_data in urls_data:
            cleaned = url_data.get("cleaned")
            if not cleaned:
                continue
            db.execute(
                text(
                    """
                    INSERT INTO extracted_urls (
                        content_record_id, content_record_published_at,
                        url_raw, url_cleaned, url_domain, url_type,
                        platform, query_design_id, project_id,
                        search_terms_matched
                    ) VALUES (
                        CAST(:record_id AS uuid),
                        :published_at,
                        :url_raw,
                        :url_cleaned,
                        :url_domain,
                        :url_type,
                        :platform,
                        CAST(:query_design_id AS uuid),
                        CAST(:project_id AS uuid),
                        :search_terms
                    )
                    """
                ),
                {
                    "record_id": record_id,
                    "published_at": record["published_at"],
                    "url_raw": url_data.get("raw", ""),
                    "url_cleaned": cleaned,
                    "url_domain": url_data.get("domain", ""),
                    "url_type": url_data.get("type", "text_extracted"),
                    "platform": record["platform"],
                    "query_design_id": str(query_design_id) if query_design_id else None,
                    "project_id": str(project_id) if project_id else None,
                    "search_terms": search_terms or None,
                },
            )

        db.commit()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-run url_extraction enricher on Google Search records."
    )
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=0, help="Max records (0=all)")
    args = parser.parse_args()

    total = count_target_records()
    print(
        f"Found {total:,} google_search records with url_extraction enrichment."
    )
    if total == 0:
        print("Nothing to do.")
        return

    extractor = UrlExtractor()
    processed = 0
    rewritten_structured = 0
    t0 = time.perf_counter()

    # Offset advances monotonically because the filter predicate
    # ("has url_extraction and platform=google_search") still matches
    # after re-writing, so ORDER BY cr.id keeps pagination stable.
    while True:
        batch = fetch_target_records(processed, args.batch_size)
        if not batch:
            break

        for record in batch:
            record_for_enrich = {
                "id": str(record["id"]),
                "platform": record["platform"],
                "url": record["url"],
                "text_content": record.get("text_content"),
                "raw_metadata": record.get("raw_metadata") or {},
            }
            result = await extractor.enrich(record_for_enrich)
            rewrite_record(record, result)
            for entry in result.get("urls", []):
                if entry.get("type") == "structured":
                    rewritten_structured += 1

        processed += len(batch)
        elapsed = time.perf_counter() - t0
        rate = processed / elapsed if elapsed > 0 else 0.0
        print(
            f"  {processed:,}/{total:,} records | "
            f"{rewritten_structured:,} structured URLs | "
            f"{rate:.0f} rec/s | {elapsed:.0f}s"
        )

        if args.limit and processed >= args.limit:
            break

    elapsed = time.perf_counter() - t0
    rate = processed / elapsed if elapsed > 0 else 0.0
    print(
        f"\nDone: {processed:,} records, "
        f"{rewritten_structured:,} URLs tagged structured "
        f"in {elapsed:.0f}s ({rate:.0f} rec/s)."
    )


if __name__ == "__main__":
    asyncio.run(main())
