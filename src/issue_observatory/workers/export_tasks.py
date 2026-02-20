"""Celery tasks for asynchronous content export.

Large exports (> 10 K records) are dispatched here as background Celery tasks.
The task:

1. Runs the content query against PostgreSQL using a synchronous psycopg2
   connection (Celery workers are synchronous processes; asyncpg is not usable
   here without running a fresh event loop, which is fragile under Celery).
2. Builds a list of plain dicts from the result set.
3. Delegates serialization to ``ContentExporter``.
4. Uploads the file to MinIO under ``exports/{user_id}/{job_id}.{ext}``.
5. Writes a progress/status JSON blob to Redis at key
   ``export:{job_id}:status`` with a 24-hour TTL.

Progress reporting:
    The task writes status updates to Redis at the following lifecycle points:
    - On start: ``{"status": "running", "pct_complete": 0}``
    - After query: ``{"status": "running", "pct_complete": 50}``
    - After export: ``{"status": "running", "pct_complete": 80}``
    - On completion: ``{"status": "complete", "pct_complete": 100,
                        "download_url": "<presigned_url>", "record_count": N}``
    - On failure: ``{"status": "failed", "error": "<message>"}``

Download URL:
    The ``download_url`` stored in Redis is a MinIO pre-signed URL with a
    1-hour expiry generated at task completion time.  The
    ``GET /content/export/{job_id}/download`` route regenerates a fresh
    pre-signed URL on each call so that researchers who return after the
    first URL expires can still download their file.

Database access:
    The task uses ``psycopg2`` (sync) rather than ``asyncpg`` because Celery
    workers run in a synchronous context.  The synchronous DSN is derived
    from ``settings.database_url`` by replacing the ``postgresql+asyncpg://``
    scheme with ``postgresql://``.

Owned by the DB Engineer.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from issue_observatory.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Redis key helpers
# ---------------------------------------------------------------------------

_STATUS_TTL = 86_400  # 24 hours


def export_status_key(job_id: str) -> str:
    """Return the Redis key for the export job status blob.

    Args:
        job_id: UUID string identifying the export job.

    Returns:
        Redis key string in the form ``export:{job_id}:status``.
    """
    return f"export:{job_id}:status"


def _set_status(redis_client: Any, job_id: str, payload: dict[str, Any]) -> None:  # noqa: ANN401
    """Write a JSON status blob to Redis with a 24-hour TTL.

    Args:
        redis_client: A connected ``redis.Redis`` (synchronous) instance.
        job_id: UUID string of the export job.
        payload: Dict to serialize as JSON and store.
    """
    redis_client.setex(
        export_status_key(job_id),
        _STATUS_TTL,
        json.dumps(payload),
    )


# ---------------------------------------------------------------------------
# Sync DB helper
# ---------------------------------------------------------------------------


def _build_sync_dsn(async_dsn: str) -> str:
    """Convert an asyncpg DSN to a psycopg2-compatible DSN.

    Replaces ``postgresql+asyncpg://`` with ``postgresql://`` so that
    psycopg2 can connect inside the synchronous Celery worker.

    Args:
        async_dsn: The application DATABASE_URL (asyncpg scheme).

    Returns:
        A psycopg2-compatible DSN string.
    """
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", async_dsn)


def _query_records(
    sync_dsn: str,
    user_id: str,
    filters: dict[str, Any],
    limit: Optional[int],
) -> list[dict[str, Any]]:
    """Run the content query synchronously and return plain dicts.

    Uses a server-side cursor (``fetchmany`` in batches of 1 000) to avoid
    loading the entire result set into memory at once.

    Args:
        sync_dsn: psycopg2 DSN.
        user_id: UUID string of the requesting user (ownership filter).
        filters: Dict with optional keys: ``platform``, ``arena``,
            ``query_design_id``, ``date_from``, ``date_to``, ``language``,
            ``run_id``, ``search_term``.
        limit: Maximum number of records to return, or None for no limit.

    Returns:
        List of plain dicts, one per content record row.
    """
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError as exc:
        raise ImportError(
            "psycopg2 is required for async export tasks. "
            "Install it with: pip install psycopg2-binary"
        ) from exc

    # Build parameterized SQL
    conditions: list[str] = [
        "cr.collection_run_id IN "
        "(SELECT id FROM collection_runs WHERE initiated_by = %(user_id)s)"
    ]
    params: dict[str, Any] = {"user_id": user_id}

    if filters.get("platform"):
        conditions.append("cr.platform = %(platform)s")
        params["platform"] = filters["platform"]

    if filters.get("arena"):
        conditions.append("cr.arena = %(arena)s")
        params["arena"] = filters["arena"]

    if filters.get("query_design_id"):
        conditions.append("cr.query_design_id = %(query_design_id)s")
        params["query_design_id"] = filters["query_design_id"]

    if filters.get("date_from"):
        conditions.append("cr.published_at >= %(date_from)s")
        params["date_from"] = filters["date_from"]

    if filters.get("date_to"):
        conditions.append("cr.published_at <= %(date_to)s")
        params["date_to"] = filters["date_to"]

    if filters.get("language"):
        conditions.append("cr.language = %(language)s")
        params["language"] = filters["language"]

    if filters.get("run_id"):
        conditions.append("cr.collection_run_id = %(run_id)s")
        params["run_id"] = filters["run_id"]

    if filters.get("search_term"):
        conditions.append("cr.search_terms_matched @> ARRAY[%(search_term)s]::text[]")
        params["search_term"] = filters["search_term"]

    where_clause = " AND ".join(conditions)
    limit_clause = f"LIMIT {int(limit)}" if limit else ""

    sql = f"""
        SELECT
            cr.id,
            cr.platform,
            cr.arena,
            cr.content_type,
            cr.title,
            cr.text_content,
            cr.url,
            cr.author_display_name,
            cr.published_at,
            cr.views_count,
            cr.likes_count,
            cr.shares_count,
            cr.comments_count,
            cr.language,
            cr.collection_tier,
            cr.search_terms_matched,
            cr.collection_run_id,
            cr.query_design_id,
            cr.pseudonymized_author_id,
            cr.raw_metadata,
            cr.content_hash,
            cr.collected_at
        FROM content_records cr
        WHERE {where_clause}
        ORDER BY cr.collected_at DESC
        {limit_clause}
    """

    records: list[dict[str, Any]] = []
    batch_size = 1_000

    with psycopg2.connect(sync_dsn) as conn:
        with conn.cursor(name="export_cursor", cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            while True:
                batch = cur.fetchmany(batch_size)
                if not batch:
                    break
                for row in batch:
                    records.append(dict(row))

    return records


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery_app.task(name="export_content_records", bind=True)  # type: ignore[misc]
def export_content_records(
    self: Any,  # noqa: ANN401
    user_id: str,
    job_id: str,
    filters: dict[str, Any],
    export_format: str,
) -> dict[str, Any]:
    """Export content records to a file and upload it to MinIO.

    This task is dispatched by ``POST /content/export/async``.  Progress and
    the resulting download URL are written to Redis under
    ``export:{job_id}:status``.

    Args:
        user_id: UUID string of the requesting user.  Used to scope the query
            to the user's own collection runs and to namespace the MinIO path.
        job_id: UUID string uniquely identifying this export job.
        filters: Dict of query filters (see ``_query_records`` for accepted
            keys: platform, arena, query_design_id, date_from, date_to,
            language, run_id, search_term).
        export_format: One of ``csv``, ``xlsx``, ``json``, ``parquet``, ``gexf``.

    Returns:
        Dict with ``{"status": "complete", "record_count": N,
                     "object_key": "<minio_path>"}`` on success.

    Raises:
        Exception: Any unhandled exception is caught, written to Redis as a
            failed status, and re-raised so Celery marks the task as FAILED.
    """
    import redis as redis_lib

    from issue_observatory.config.settings import get_settings

    settings = get_settings()
    redis_client = redis_lib.from_url(settings.redis_url, decode_responses=True)

    _set_status(redis_client, job_id, {"status": "running", "pct_complete": 0})
    log = logger.bind(job_id=job_id, user_id=user_id, format=export_format)

    try:
        # --- Step 1: Query database ---
        sync_dsn = _build_sync_dsn(settings.database_url)
        log.info("export_task.query_start")
        records = _query_records(sync_dsn, user_id, filters, limit=None)
        log.info("export_task.query_done", record_count=len(records))
        _set_status(redis_client, job_id, {"status": "running", "pct_complete": 50})

        # --- Step 2: Serialize to bytes ---
        from issue_observatory.analysis.export import ContentExporter

        exporter = ContentExporter()
        # Extract network_type for GEXF exports.  Defaults to "actor" so that
        # jobs dispatched before this parameter was added continue to work.
        gexf_network_type: str = filters.get("network_type", "actor")

        format_method = {
            "csv": lambda: asyncio.run(exporter.export_csv(records)),
            "xlsx": lambda: asyncio.run(exporter.export_xlsx(records)),
            "json": lambda: asyncio.run(exporter.export_json(records)),
            "parquet": lambda: asyncio.run(exporter.export_parquet(records)),
            "gexf": lambda: asyncio.run(exporter.export_gexf(records, network_type=gexf_network_type)),
        }
        if export_format not in format_method:
            raise ValueError(f"Unsupported export format: {export_format!r}")

        file_bytes = format_method[export_format]()
        log.info("export_task.serialized", byte_count=len(file_bytes))
        _set_status(redis_client, job_id, {"status": "running", "pct_complete": 80})

        # --- Step 3: Upload to MinIO ---
        import io as _io

        from minio import Minio  # type: ignore[import-untyped]
        from minio.error import S3Error  # type: ignore[import-untyped]

        ext_map = {
            "csv": "csv",
            "xlsx": "xlsx",
            "json": "ndjson",
            "parquet": "parquet",
            "gexf": "gexf",
        }
        ext = ext_map[export_format]
        object_key = f"exports/{user_id}/{job_id}.{ext}"

        minio_client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_root_user,
            secret_key=settings.minio_root_password,
            secure=settings.minio_secure,
        )

        # Ensure bucket exists
        if not minio_client.bucket_exists(settings.minio_bucket):
            minio_client.make_bucket(settings.minio_bucket)

        content_type_map = {
            "csv": "text/csv; charset=utf-8",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "json": "application/x-ndjson",
            "parquet": "application/octet-stream",
            "gexf": "application/xml",
        }

        minio_client.put_object(
            settings.minio_bucket,
            object_key,
            _io.BytesIO(file_bytes),
            length=len(file_bytes),
            content_type=content_type_map[export_format],
        )

        # Generate a 1-hour pre-signed download URL
        from datetime import timedelta

        presigned_url = minio_client.presigned_get_object(
            settings.minio_bucket,
            object_key,
            expires=timedelta(hours=1),
        )

        log.info("export_task.upload_done", object_key=object_key)

        final_status: dict[str, Any] = {
            "status": "complete",
            "pct_complete": 100,
            "record_count": len(records),
            "object_key": object_key,
            "download_url": presigned_url,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        _set_status(redis_client, job_id, final_status)

        return {
            "status": "complete",
            "record_count": len(records),
            "object_key": object_key,
        }

    except S3Error as exc:
        log.error("export_task.minio_error", error=str(exc))
        _set_status(redis_client, job_id, {"status": "failed", "error": str(exc)})
        raise

    except Exception as exc:
        log.error("export_task.failed", error=str(exc))
        _set_status(redis_client, job_id, {"status": "failed", "error": str(exc)})
        raise
