"""Backfill search_terms_matched on all content_records.

For each query design, loads its search terms and runs case-insensitive
substring matching against text_content + title.  Any newly matched terms
are merged into the existing search_terms_matched array (no duplicates).

Usage:
    uv run python scripts/backfill_search_terms.py [--dry-run] [--batch-size 5000]
"""

from __future__ import annotations

import argparse
import logging
import time

from sqlalchemy import text

from issue_observatory.core.database import get_sync_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE_DEFAULT = 5000


def _fetch_terms_by_design(session) -> dict[str, list[str]]:
    """Return {query_design_id: [term, ...]} for all designs with terms."""
    rows = session.execute(text("""
        SELECT query_design_id, array_agg(DISTINCT term) AS terms
        FROM search_terms
        GROUP BY query_design_id
    """)).fetchall()
    return {str(r.query_design_id): list(r.terms) for r in rows}


def backfill(dry_run: bool = False, batch_size: int = BATCH_SIZE_DEFAULT) -> None:
    """Run the backfill."""
    with get_sync_session() as session:
        design_terms = _fetch_terms_by_design(session)
        logger.info("Found %d query designs with search terms", len(design_terms))

        total_updated = 0
        total_scanned = 0

        for qd_id, terms in design_terms.items():
            if not terms:
                continue

            logger.info(
                "Processing design %s (%d terms: %s)",
                qd_id[:12],
                len(terms),
                ", ".join(terms[:5]) + ("..." if len(terms) > 5 else ""),
            )

            offset = 0
            design_updated = 0

            while True:
                rows = session.execute(
                    text("""
                        SELECT id, text_content, title, search_terms_matched
                        FROM content_records
                        WHERE query_design_id = CAST(:qd_id AS uuid)
                        ORDER BY id
                        LIMIT :limit OFFSET :offset
                    """),
                    {"qd_id": qd_id, "limit": batch_size, "offset": offset},
                ).fetchall()

                if not rows:
                    break

                total_scanned += len(rows)
                updates = []

                for row in rows:
                    existing = set(row.search_terms_matched or [])
                    existing_lower = {t.lower() for t in existing}
                    haystack = (
                        (row.title or "").lower()
                        + " "
                        + (row.text_content or "").lower()
                    )
                    if not haystack.strip():
                        continue

                    new_terms = [
                        t for t in terms
                        if t.lower() in haystack and t.lower() not in existing_lower
                    ]
                    if new_terms:
                        merged = list(existing) + new_terms
                        updates.append((str(row.id), merged))

                if updates and not dry_run:
                    for record_id, merged_terms in updates:
                        arr_literal = (
                            "{"
                            + ",".join(
                                '"'
                                + t.replace("\\", "\\\\").replace('"', '\\"')
                                + '"'
                                for t in merged_terms
                            )
                            + "}"
                        )
                        session.execute(
                            text("""
                                UPDATE content_records
                                SET search_terms_matched = CAST(:terms AS text[]),
                                    term_matched = true
                                WHERE id = CAST(:id AS uuid)
                            """),
                            {"id": record_id, "terms": arr_literal},
                        )
                    session.commit()

                design_updated += len(updates)
                offset += batch_size

                if offset % (batch_size * 20) == 0:
                    logger.info(
                        "  ... scanned %d rows, updated %d so far",
                        offset,
                        design_updated,
                    )

            total_updated += design_updated
            logger.info(
                "Design %s: updated %d records",
                qd_id[:12],
                design_updated,
            )

        # Also fix term_matched for records that have non-empty search_terms_matched
        # but term_matched = false (shouldn't happen, but safety net).
        if not dry_run:
            result = session.execute(text("""
                UPDATE content_records
                SET term_matched = true
                WHERE search_terms_matched IS NOT NULL
                  AND array_length(search_terms_matched, 1) > 0
                  AND (term_matched IS NULL OR term_matched = false)
            """))
            session.commit()
            fixed = result.rowcount
            if fixed:
                logger.info("Fixed term_matched flag on %d records", fixed)

        logger.info(
            "Backfill %s: scanned %d records, updated %d",
            "DRY RUN" if dry_run else "COMPLETE",
            total_scanned,
            total_updated,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill search_terms_matched")
    parser.add_argument("--dry-run", action="store_true", help="Count changes without writing")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE_DEFAULT)
    args = parser.parse_args()

    start = time.monotonic()
    backfill(dry_run=args.dry_run, batch_size=args.batch_size)
    elapsed = time.monotonic() - start
    logger.info("Finished in %.1f seconds", elapsed)
