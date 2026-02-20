"""Celery tasks for database maintenance operations.

Currently covers:

- ``deduplicate_run``: run a full cross-arena near-duplicate detection pass
  for one collection run (Task 3.8).
- ``refresh_engagement_metrics``: re-fetch engagement metrics for existing
  content records in a collection run (IP2-035).

Database access uses ``psycopg2`` (synchronous) because Celery workers are
synchronous processes.  The async deduplication service logic is re-implemented
here using direct SQL to avoid running a nested asyncio event loop under Celery.

Owned by the Core Application Engineer (engagement refresh) and DB Engineer (dedup).
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


# ---------------------------------------------------------------------------
# Engagement metric refresh (IP2-035)
# ---------------------------------------------------------------------------


@celery_app.task(name="refresh_engagement_metrics", bind=True)  # type: ignore[misc]
def refresh_engagement_metrics(
    self: Any,  # noqa: ANN401
    run_id: str,
) -> dict[str, Any]:
    """Re-fetch engagement metrics for content records in a collection run.

    Groups records by platform, calls each arena's ``refresh_engagement()``
    method (if implemented), and updates engagement counts in the database.

    Arenas that do not implement ``refresh_engagement()`` are skipped
    silently with a debug log message.

    Records are batched (50 external_ids per API call) to avoid overwhelming
    upstream APIs and to respect rate limits.

    This task is dispatched by ``POST /collections/{run_id}/refresh-engagement``.

    Args:
        run_id: UUID string of the collection run to refresh.

    Returns:
        Dict with:
        - ``platforms_processed``: number of platforms that support refresh
        - ``records_queried``: total records sent to arena APIs
        - ``records_updated``: number of records successfully updated
        - ``platforms_skipped``: number of platforms without refresh support
    """
    log = logger.bind(task="refresh_engagement_metrics", run_id=run_id)
    log.info("refresh_engagement.start")

    from issue_observatory.config.settings import get_settings

    settings = get_settings()
    sync_dsn = _build_sync_dsn(settings.database_url)

    try:
        result = _refresh_engagement_sync(sync_dsn, run_id, settings)
        log.info("refresh_engagement.complete", **result)
        return result
    except Exception as exc:
        log.error("refresh_engagement.failed", error=str(exc))
        raise


def _refresh_engagement_sync(sync_dsn: str, run_id: str, settings: Any) -> dict[str, Any]:  # noqa: ANN401
    """Execute engagement refresh inside a synchronous psycopg2 connection.

    Args:
        sync_dsn: psycopg2-compatible database DSN.
        run_id: UUID string of the collection run to refresh.
        settings: Application settings instance.

    Returns:
        Dict with processing statistics.
    """
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError as exc:
        raise ImportError(
            "psycopg2 is required for maintenance tasks. "
            "Install it with: pip install psycopg2-binary"
        ) from exc

    import asyncio
    from collections import defaultdict

    from issue_observatory.arenas.base import Tier
    from issue_observatory.arenas.registry import get_arena

    platforms_processed = 0
    platforms_skipped = 0
    records_queried = 0
    records_updated = 0

    BATCH_SIZE = 50  # process 50 external_ids per API call

    with psycopg2.connect(sync_dsn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Fetch all records grouped by platform
            cur.execute(
                """
                SELECT
                    platform,
                    external_id,
                    id::text as record_id
                FROM content_records
                WHERE collection_run_id = %(run_id)s
                  AND external_id IS NOT NULL
                ORDER BY platform, external_id
                """,
                {"run_id": run_id},
            )
            rows = cur.fetchall()

            if not rows:
                logger.info("refresh_engagement: no records with external_id found")
                return {
                    "platforms_processed": 0,
                    "records_queried": 0,
                    "records_updated": 0,
                    "platforms_skipped": 0,
                }

            # Group records by platform
            platform_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
            for row in rows:
                platform_groups[row["platform"]].append(
                    {"external_id": row["external_id"], "record_id": row["record_id"]}
                )

            # Also fetch the tier from collection_runs
            cur.execute(
                """
                SELECT tier
                FROM collection_runs
                WHERE id = %(run_id)s
                """,
                {"run_id": run_id},
            )
            tier_row = cur.fetchone()
            tier = Tier(tier_row["tier"]) if tier_row else Tier.FREE

            # Process each platform
            for platform_name, records in platform_groups.items():
                log = logger.bind(platform=platform_name, record_count=len(records))
                log.info("refresh_engagement: processing platform")

                try:
                    # Get the arena collector
                    collector = get_arena(platform_name)
                    if collector is None:
                        log.warning("refresh_engagement: arena not found in registry")
                        platforms_skipped += 1
                        continue

                    # Process in batches
                    for i in range(0, len(records), BATCH_SIZE):
                        batch = records[i : i + BATCH_SIZE]
                        external_ids = [r["external_id"] for r in batch]
                        records_queried += len(external_ids)

                        log.debug(
                            "refresh_engagement: fetching batch",
                            batch_start=i,
                            batch_size=len(external_ids),
                        )

                        # Call the arena's refresh_engagement() method
                        # Run in a temporary asyncio event loop
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            engagement_map = loop.run_until_complete(
                                collector.refresh_engagement(external_ids, tier=tier)
                            )
                        finally:
                            loop.close()

                        if not engagement_map:
                            # Arena doesn't support refresh or returned no data
                            log.debug("refresh_engagement: arena returned empty map")
                            continue

                        # Update records in the database
                        for record in batch:
                            external_id = record["external_id"]
                            metrics = engagement_map.get(external_id)
                            if not metrics:
                                continue

                            # Build SET clause dynamically based on available metrics
                            updates = []
                            params = {"record_id": record["record_id"]}

                            if "likes_count" in metrics:
                                updates.append("likes_count = %(likes_count)s")
                                params["likes_count"] = metrics["likes_count"]
                            if "shares_count" in metrics:
                                updates.append("shares_count = %(shares_count)s")
                                params["shares_count"] = metrics["shares_count"]
                            if "comments_count" in metrics:
                                updates.append("comments_count = %(comments_count)s")
                                params["comments_count"] = metrics["comments_count"]
                            if "views_count" in metrics:
                                updates.append("views_count = %(views_count)s")
                                params["views_count"] = metrics["views_count"]

                            if updates:
                                sql = f"""
                                    UPDATE content_records
                                    SET {", ".join(updates)}
                                    WHERE id = %(record_id)s::uuid
                                """
                                cur.execute(sql, params)
                                records_updated += cur.rowcount

                    platforms_processed += 1

                except Exception as exc:
                    log.warning(
                        "refresh_engagement: platform refresh failed",
                        error=str(exc),
                    )
                    platforms_skipped += 1
                    continue

        conn.commit()

    return {
        "platforms_processed": platforms_processed,
        "records_queried": records_queried,
        "records_updated": records_updated,
        "platforms_skipped": platforms_skipped,
    }
