"""Synchronous DB helpers for the enrich_collection_run Celery task.

Separated from ``workers/_task_helpers.py`` to keep each file under 400 lines
and to make the individual helpers unit-testable without importing the Celery
application.

All functions use the synchronous ``get_sync_session()`` context manager
(psycopg2 driver) rather than ``AsyncSessionLocal`` (asyncpg driver).  This
avoids the "Future attached to a different loop" error that occurs when Celery
workers call ``asyncio.run()`` for the collector then attempt to re-use
asyncpg connections on a second ``asyncio.run()`` call.
"""

from __future__ import annotations

import json
import uuid  # noqa: F401 — kept for the type hint on write_enrichment signature
from typing import Any

from sqlalchemy import text

from issue_observatory.core.database import get_sync_session

# Batch size for fetching content records per DB round-trip.
_BATCH_SIZE = 100


def fetch_content_records_for_run(
    run_id: str,
    offset: int,
    limit: int = _BATCH_SIZE,
) -> list[dict[str, Any]]:
    """Fetch a batch of content records for a collection run.

    Args:
        run_id: UUID string of the CollectionRun.
        offset: Row offset for pagination.
        limit: Maximum number of rows to return (default: 100).

    Returns:
        List of dicts with at minimum the keys ``id``, ``text_content``,
        ``language``, and ``raw_metadata``.
    """
    with get_sync_session() as db:
        stmt = text(
            """
            SELECT id, text_content, language, raw_metadata
            FROM content_records
            WHERE collection_run_id = CAST(:run_id AS uuid)
            ORDER BY id
            LIMIT :limit OFFSET :offset
            """
        )
        result = db.execute(
            stmt,
            {"run_id": run_id, "limit": limit, "offset": offset},
        )
        rows = result.mappings().all()
        return [dict(row) for row in rows]


def write_enrichment(
    record_id: uuid.UUID | str,
    enricher_name: str,
    enrichment_data: dict[str, Any],
) -> None:
    """Merge a single enrichment result into raw_metadata.enrichments.{name}.

    Uses PostgreSQL ``jsonb_set`` with ``create_missing=true`` so the
    ``enrichments`` key is created if absent.

    Args:
        record_id: UUID of the content_records row.
        enricher_name: Key under ``raw_metadata.enrichments`` to write.
        enrichment_data: The enrichment result dict to store.
    """
    with get_sync_session() as db:
        # Two-level jsonb_set:
        # 1. Ensure raw_metadata is non-null by coalescing with '{}'.
        # 2. Ensure the top-level 'enrichments' sub-object exists.
        # 3. Write the enricher-specific key inside 'enrichments'.
        #
        # The path argument to jsonb_set must be a text[] literal.  We
        # embed the (trusted, internal-only) enricher_name directly into
        # the SQL template; it is never user-supplied and is validated
        # against the enricher registry before this helper is called.
        stmt = text(
            f"""
            UPDATE content_records
            SET raw_metadata = jsonb_set(
                    jsonb_set(
                        COALESCE(raw_metadata, '{{}}'::jsonb),
                        '{{enrichments}}',
                        COALESCE(raw_metadata->'enrichments', '{{}}'::jsonb),
                        true
                    ),
                    '{{enrichments,{enricher_name}}}',
                    CAST(:data AS jsonb),
                    true
                )
            WHERE id = CAST(:record_id AS uuid)
            """
        )
        db.execute(
            stmt,
            {
                "data": json.dumps(enrichment_data),
                "record_id": str(record_id),
            },
        )
        db.commit()
