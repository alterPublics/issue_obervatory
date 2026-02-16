"""Celery tasks for database maintenance operations.

Currently covers:

- ``deduplicate_run``: run a full cross-arena near-duplicate detection pass
  for one collection run (Task 3.8).

Database access uses ``psycopg2`` (synchronous) because Celery workers are
synchronous processes.  The async deduplication service logic is re-implemented
here using direct SQL to avoid running a nested asyncio event loop under Celery.

Owned by the DB Engineer.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import structlog

from issue_observatory.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Sync DSN helper (shared pattern with export_tasks)
# ---------------------------------------------------------------------------

_STRIP_PARAMS: frozenset[str] = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
        "fbclid",
        "gclid",
        "ref",
        "source",
        "_ga",
    }
)


def _build_sync_dsn(async_dsn: str) -> str:
    """Convert an asyncpg DSN to a psycopg2-compatible DSN.

    Args:
        async_dsn: The application DATABASE_URL (asyncpg scheme).

    Returns:
        A psycopg2-compatible DSN string.
    """
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", async_dsn)


def _normalise_url(url: str) -> str:
    """Normalise a URL for deduplication comparison.

    See ``core.deduplication.normalise_url`` for the full specification.
    Duplicated here to keep the synchronous Celery task self-contained.

    Args:
        url: Raw URL string.

    Returns:
        Normalised URL string.
    """
    lowered = url.strip().lower()
    parsed = urlparse(lowered)
    if not parsed.netloc:
        return lowered
    host = parsed.netloc
    if host.startswith("www."):
        host = host[4:]
    qs_pairs = [(k, v) for k, v in parse_qsl(parsed.query) if k not in _STRIP_PARAMS]
    qs_pairs.sort()
    new_query = urlencode(qs_pairs)
    path = parsed.path.rstrip("/") if parsed.path != "/" else parsed.path
    return urlunparse((parsed.scheme, host, path, parsed.params, new_query, parsed.fragment))


# ---------------------------------------------------------------------------
# Synchronous dedup logic
# ---------------------------------------------------------------------------


def _run_dedup_sync(sync_dsn: str, run_id: str) -> dict[str, Any]:
    """Execute a full dedup pass inside a synchronous psycopg2 connection.

    Args:
        sync_dsn: psycopg2-compatible database DSN.
        run_id: UUID string of the collection run to process.

    Returns:
        Dict with ``url_groups``, ``hash_groups``, ``total_marked``.
    """
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError as exc:
        raise ImportError(
            "psycopg2 is required for maintenance tasks. "
            "Install it with: pip install psycopg2-binary"
        ) from exc

    from collections import defaultdict

    total_marked = 0
    url_group_count = 0
    hash_group_count = 0

    with psycopg2.connect(sync_dsn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            # ---- URL pass ----
            cur.execute(
                """
                SELECT id::text, url, platform, arena
                FROM content_records
                WHERE collection_run_id = %(run_id)s
                  AND url IS NOT NULL
                """,
                {"run_id": run_id},
            )
            url_rows = cur.fetchall()

            url_groups: dict[str, list[str]] = defaultdict(list)
            for row in url_rows:
                key = _normalise_url(row["url"])
                url_groups[key].append(row["id"])

            for norm_url, ids in url_groups.items():
                if len(ids) < 2:
                    continue
                url_group_count += 1
                canonical = min(ids)
                dupes = [i for i in ids if i != canonical]
                cur.execute(
                    """
                    UPDATE content_records
                    SET raw_metadata = jsonb_set(
                        COALESCE(raw_metadata, '{}'::jsonb),
                        '{duplicate_of}',
                        to_jsonb(%(canonical)s::text)
                    )
                    WHERE id = ANY(%(dupes)s::uuid[])
                    """,
                    {"canonical": canonical, "dupes": dupes},
                )
                total_marked += cur.rowcount

            # ---- Hash pass ----
            cur.execute(
                """
                SELECT id::text, content_hash, platform, arena
                FROM content_records
                WHERE collection_run_id = %(run_id)s
                  AND content_hash IS NOT NULL
                """,
                {"run_id": run_id},
            )
            hash_rows = cur.fetchall()

            hash_groups: dict[str, list[dict]] = defaultdict(list)
            for row in hash_rows:
                hash_groups[row["content_hash"]].append(
                    {"id": row["id"], "platform": row["platform"], "arena": row["arena"]}
                )

            for content_hash, records in hash_groups.items():
                if len(records) < 2:
                    continue
                platforms = {r["platform"] for r in records}
                arenas = {r["arena"] for r in records}
                if len(platforms) <= 1 and len(arenas) <= 1:
                    continue
                hash_group_count += 1
                ids = [r["id"] for r in records]
                canonical = min(ids)
                dupes = [i for i in ids if i != canonical]
                cur.execute(
                    """
                    UPDATE content_records
                    SET raw_metadata = jsonb_set(
                        COALESCE(raw_metadata, '{}'::jsonb),
                        '{duplicate_of}',
                        to_jsonb(%(canonical)s::text)
                    )
                    WHERE id = ANY(%(dupes)s::uuid[])
                    """,
                    {"canonical": canonical, "dupes": dupes},
                )
                total_marked += cur.rowcount

        conn.commit()

    return {
        "url_groups": url_group_count,
        "hash_groups": hash_group_count,
        "total_marked": total_marked,
    }


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery_app.task(name="deduplicate_run", bind=True)  # type: ignore[misc]
def deduplicate_run(
    self: Any,  # noqa: ANN401
    run_id: str,
) -> dict[str, Any]:
    """Run a full cross-arena near-duplicate detection pass for a collection run.

    Detects duplicates via two strategies:

    1. **URL normalisation**: records whose normalised URL (stripped tracking
       params, lowercased, ``www.``-stripped) matches across different arenas.
    2. **Content hash**: records sharing the same SHA-256 ``content_hash``
       across different platforms or arenas.

    Duplicate records are marked in-place by setting
    ``raw_metadata['duplicate_of']`` to the canonical record's UUID string.
    The canonical record within each group is chosen as the record with the
    lowest UUID value.

    This task is dispatched by ``POST /content/deduplicate?run_id={uuid}``.

    Args:
        run_id: UUID string of the collection run to process.

    Returns:
        Dict with ``url_groups``, ``hash_groups``, ``total_marked`` counts.
    """
    log = logger.bind(task="deduplicate_run", run_id=run_id)
    log.info("dedup_task.start")

    from issue_observatory.config.settings import get_settings

    settings = get_settings()
    sync_dsn = _build_sync_dsn(settings.database_url)

    try:
        result = _run_dedup_sync(sync_dsn, run_id)
        log.info("dedup_task.complete", **result)
        return result
    except Exception as exc:
        log.error("dedup_task.failed", error=str(exc))
        raise
