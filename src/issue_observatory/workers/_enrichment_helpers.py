"""Async DB helpers for the enrich_collection_run Celery task.

Separated from ``workers/_task_helpers.py`` to keep each file under 400 lines
and to make the individual helpers unit-testable without importing the Celery
application.

All functions open their own ``AsyncSessionLocal`` context managers and
commit before returning.  This is intentional: Celery workers call these
via ``asyncio.run()`` from synchronous task bodies, so each invocation
requires a fresh event loop with no pre-existing session.
"""

from __future__ import annotations

import json
import uuid  # noqa: F401 — kept for the type hint on write_enrichment signature
from typing import Any

from sqlalchemy import text

from issue_observatory.core.database import AsyncSessionLocal

# Batch size for fetching content records per DB round-trip.
_BATCH_SIZE = 100


async def fetch_content_records_for_run(
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
    async with AsyncSessionLocal() as db:
        stmt = text(
            """
            SELECT id, text_content, language, raw_metadata
            FROM content_records
            WHERE collection_run_id = :run_id
            ORDER BY id
            LIMIT :limit OFFSET :offset
            """
        )
        result = await db.execute(
            stmt,
            {"run_id": run_id, "limit": limit, "offset": offset},
        )
        rows = result.mappings().all()
        return [dict(row) for row in rows]


async def write_enrichment(
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
    async with AsyncSessionLocal() as db:
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
                    :data::jsonb,
                    true
                )
            WHERE id = :record_id
            """
        )
        await db.execute(
            stmt,
            {
                "data": json.dumps(enrichment_data),
                "record_id": str(record_id),
            },
        )
        await db.commit()
