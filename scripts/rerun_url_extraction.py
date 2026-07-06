"""Re-run the ``url_extraction`` enricher for an entire platform.

Useful whenever the extraction logic changes and existing enrichment
payloads need to be regenerated — for example after adding a new
structured-field handler (``google_search`` ``link`` field) or the
shortener filter that drops ``t.co`` / ``bit.ly`` noise.

For every matching record the script:

1. Calls :meth:`UrlExtractor.enrich` to produce a fresh enrichment dict.
2. Overwrites ``raw_metadata.enrichments.url_extraction`` via
   ``jsonb_set``.
3. Deletes the record's existing rows in ``extracted_urls`` and
   re-inserts them from the fresh enrichment.  Required because the
   unique index ``(content_record_id, content_record_published_at,
   url_cleaned)`` with ``ON CONFLICT DO NOTHING`` would otherwise leave
   the stale rows in place.

Usage::

    uv run python scripts/rerun_url_extraction.py --platform x_twitter
    uv run python scripts/rerun_url_extraction.py --platform bluesky --limit 500
    uv run python scripts/rerun_url_extraction.py --platform google_search --batch-size 1000
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


def count_target_records(platform: str) -> int:
    """Count records of *platform* that already have a url_extraction enrichment."""
    with get_sync_session() as db:
        stmt = text(
            """
            SELECT COUNT(*) FROM content_records
            WHERE platform = :platform
              AND raw_metadata->'enrichments'->'url_extraction' IS NOT NULL
            """
        )
        return int(db.execute(stmt, {"platform": platform}).scalar() or 0)


def fetch_target_records(
    platform: str,
    offset: int,
    limit: int,
) -> list[dict[str, Any]]:
    """Fetch a page of platform records that already have a url_extraction payload."""
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
            WHERE cr.platform = :platform
              AND cr.raw_metadata->'enrichments'->'url_extraction' IS NOT NULL
            ORDER BY cr.id
            LIMIT :limit OFFSET :offset
            """
        )
        result = db.execute(
            stmt, {"platform": platform, "limit": limit, "offset": offset}
        )
        return [dict(row) for row in result.mappings().all()]


def rewrite_record(record: dict[str, Any], enrichment_result: dict[str, Any]) -> None:
    """Overwrite JSONB enrichment + replace extracted_urls rows in a single transaction."""
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
        description="Re-run url_extraction enricher for a single platform."
    )
    parser.add_argument(
        "--platform",
        required=True,
        help="Platform name (e.g. 'x_twitter', 'google_search', 'bluesky').",
    )
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=0, help="Max records (0=all)")
    args = parser.parse_args()

    total = count_target_records(args.platform)
    print(
        f"Found {total:,} {args.platform} records with url_extraction enrichment."
    )
    if total == 0:
        print("Nothing to do.")
        return

    extractor = UrlExtractor()
    processed = 0
    urls_emitted = 0
    t0 = time.perf_counter()

    while True:
        batch = fetch_target_records(args.platform, processed, args.batch_size)
        if not batch:
            break

        for record in batch:
            record_for_enrich = {
                "id": str(record["id"]),
                "platform": record["platform"],
                "url": record["url"],
                "content_type": (record.get("raw_metadata") or {}).get("content_type"),
                "text_content": record.get("text_content"),
                "raw_metadata": record.get("raw_metadata") or {},
            }
            result = await extractor.enrich(record_for_enrich)
            rewrite_record(record, result)
            urls_emitted += result.get("urls_found", 0)

        processed += len(batch)
        elapsed = time.perf_counter() - t0
        rate = processed / elapsed if elapsed > 0 else 0.0
        print(
            f"  {processed:,}/{total:,} records | "
            f"{urls_emitted:,} URLs emitted | "
            f"{rate:.0f} rec/s | {elapsed:.0f}s"
        )

        if args.limit and processed >= args.limit:
            break

    elapsed = time.perf_counter() - t0
    rate = processed / elapsed if elapsed > 0 else 0.0
    print(
        f"\nDone: {processed:,} {args.platform} records, "
        f"{urls_emitted:,} URLs emitted in {elapsed:.0f}s ({rate:.0f} rec/s)."
    )


if __name__ == "__main__":
    asyncio.run(main())
