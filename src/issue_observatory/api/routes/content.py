"""Content browser and export routes.

Provides a read-only API for browsing and exporting collected content records
stored in the universal ``content_records`` table.

Results are always filtered to the current user's own collection runs.
Records from shared or public query designs are not exposed here unless
the current user's run collected them.

Routes:
    GET /content/              — browse collected content with cursor pagination
    GET /content/{id}          — get a single content record detail

    GET  /content/export                    — synchronous export (up to 10 K records)
    POST /content/export/async              — async export via Celery (unlimited records)
    GET  /content/export/{job_id}/status    — poll Celery export job status from Redis
    GET  /content/export/{job_id}/download  — redirect to MinIO pre-signed download URL
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Annotated, Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.analysis.export import ContentExporter
from issue_observatory.api.dependencies import (
    PaginationParams,
    get_current_active_user,
    get_pagination,
)
from issue_observatory.core.database import get_db
from issue_observatory.core.models.collection import CollectionRun
from issue_observatory.core.models.content import UniversalContentRecord
from issue_observatory.core.models.users import User
from issue_observatory.core.schemas.content import ContentRecordRead

logger = structlog.get_logger(__name__)

router = APIRouter()

_MAX_LIMIT = 200
_EXPORT_SYNC_LIMIT = 10_000

# ---------------------------------------------------------------------------
# Content-Type headers per export format
# ---------------------------------------------------------------------------

_EXPORT_CONTENT_TYPES: dict[str, str] = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "json": "application/x-ndjson",
    "parquet": "application/octet-stream",
    "gexf": "application/xml",
}

_EXPORT_EXTENSIONS: dict[str, str] = {
    "csv": "csv",
    "xlsx": "xlsx",
    "json": "ndjson",
    "parquet": "parquet",
    "gexf": "gexf",
}


# ---------------------------------------------------------------------------
# Shared filter helper
# ---------------------------------------------------------------------------


def _build_content_stmt(
    current_user: User,
    platform: Optional[str],
    arena: Optional[str],
    query_design_id: Optional[uuid.UUID],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    search_term: Optional[str],
    language: Optional[str],
    run_id: Optional[uuid.UUID],
    limit: Optional[int],
) -> Any:  # noqa: ANN401
    """Build a SELECT statement against ``content_records`` with ownership scope.

    Non-admin users are restricted to records that belong to their own
    collection runs.  Admins see all records.

    Args:
        current_user: The authenticated user making the request.
        platform: Optional platform filter.
        arena: Optional arena filter.
        query_design_id: Optional query design UUID filter.
        date_from: Optional lower bound on ``published_at``.
        date_to: Optional upper bound on ``published_at``.
        search_term: Optional term that must appear in ``search_terms_matched``.
        language: Optional ISO 639-1 language code filter.
        run_id: Optional specific collection run UUID filter.
        limit: Maximum number of rows to return (applied as SQL LIMIT).

    Returns:
        A SQLAlchemy ``Select`` statement ready for ``await db.execute()``.
    """
    if current_user.role == "admin":
        stmt = (
            select(UniversalContentRecord)
            .order_by(UniversalContentRecord.collected_at.desc())
        )
    else:
        user_run_ids_subq = (
            select(CollectionRun.id)
            .where(CollectionRun.initiated_by == current_user.id)
            .scalar_subquery()
        )
        stmt = (
            select(UniversalContentRecord)
            .where(UniversalContentRecord.collection_run_id.in_(user_run_ids_subq))
            .order_by(UniversalContentRecord.collected_at.desc())
        )

    if platform is not None:
        stmt = stmt.where(UniversalContentRecord.platform == platform)
    if arena is not None:
        stmt = stmt.where(UniversalContentRecord.arena == arena)
    if query_design_id is not None:
        stmt = stmt.where(UniversalContentRecord.query_design_id == query_design_id)
    if date_from is not None:
        stmt = stmt.where(UniversalContentRecord.published_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(UniversalContentRecord.published_at <= date_to)
    if language is not None:
        stmt = stmt.where(UniversalContentRecord.language == language)
    if run_id is not None:
        stmt = stmt.where(UniversalContentRecord.collection_run_id == run_id)
    if search_term is not None:
        stmt = stmt.where(
            UniversalContentRecord.search_terms_matched.contains([search_term])
        )
    if limit is not None:
        stmt = stmt.limit(limit)

    return stmt


def _record_to_dict(record: UniversalContentRecord) -> dict[str, Any]:
    """Convert an ORM row to a plain dict suitable for the ``ContentExporter``.

    Args:
        record: An ORM instance of ``UniversalContentRecord``.

    Returns:
        Dict with string keys matching ORM column names.
    """
    return {
        "id": record.id,
        "platform": record.platform,
        "arena": record.arena,
        "content_type": record.content_type,
        "title": record.title,
        "text_content": record.text_content,
        "url": record.url,
        "author_display_name": record.author_display_name,
        "author_platform_id": record.author_platform_id,
        "pseudonymized_author_id": record.pseudonymized_author_id,
        "published_at": record.published_at,
        "collected_at": record.collected_at,
        "views_count": record.views_count,
        "likes_count": record.likes_count,
        "shares_count": record.shares_count,
        "comments_count": record.comments_count,
        "engagement_score": record.engagement_score,
        "language": record.language,
        "collection_tier": record.collection_tier,
        "search_terms_matched": record.search_terms_matched,
        "collection_run_id": record.collection_run_id,
        "query_design_id": record.query_design_id,
        "raw_metadata": record.raw_metadata,
        "content_hash": record.content_hash,
    }


# ---------------------------------------------------------------------------
# List / browse
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[ContentRecordRead])
async def browse_content(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    pagination: Annotated[PaginationParams, Depends(get_pagination)],
    platform: Optional[str] = Query(default=None, description="Filter by platform name."),
    arena: Optional[str] = Query(default=None, description="Filter by arena name."),
    query_design_id: Optional[uuid.UUID] = Query(
        default=None, description="Filter by query design UUID."
    ),
    date_from: Optional[datetime] = Query(
        default=None, description="Filter content published on or after this timestamp."
    ),
    date_to: Optional[datetime] = Query(
        default=None, description="Filter content published on or before this timestamp."
    ),
    search_term: Optional[str] = Query(
        default=None,
        description="Filter records where search_terms_matched contains this term.",
    ),
    language: Optional[str] = Query(
        default=None, description="Filter by ISO 639-1 language code."
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=_MAX_LIMIT,
        description="Number of records to return (max 200).",
    ),
) -> list[UniversalContentRecord]:
    """Browse collected content with optional filters and cursor pagination.

    Results are scoped to content collected by the current user's own
    collection runs.  Records are ordered by ``collected_at`` descending
    (most recently ingested first).

    Query parameters allow narrowing by platform, arena, date range, matched
    search term, and language.  All filters are additive (AND logic).

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        pagination: Cursor and page-size parameters from query string.
        platform: Optional platform filter (e.g. ``'youtube'``).
        arena: Optional arena filter (e.g. ``'social_media'``).
        query_design_id: Optional filter to content from a specific design.
        date_from: Optional lower bound on ``published_at``.
        date_to: Optional upper bound on ``published_at``.
        search_term: Optional filter on ``search_terms_matched`` array membership.
        language: Optional ISO 639-1 language code filter.
        limit: Maximum records to return (1–200, overrides ``page_size`` from
            the shared pagination params for this endpoint).

    Returns:
        A list of ``ContentRecordRead`` dicts matching the applied filters.
    """
    stmt = _build_content_stmt(
        current_user=current_user,
        platform=platform,
        arena=arena,
        query_design_id=query_design_id,
        date_from=date_from,
        date_to=date_to,
        search_term=search_term,
        language=language,
        run_id=None,
        limit=limit,
    )

    if pagination.cursor:
        try:
            cursor_id = uuid.UUID(pagination.cursor)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="cursor must be a valid UUID.",
            ) from exc
        stmt = stmt.where(UniversalContentRecord.id < cursor_id)

    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


@router.get("/{record_id}", response_model=ContentRecordRead)
async def get_content_record(
    record_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UniversalContentRecord:
    """Retrieve a single content record by ID.

    The record must belong to a collection run initiated by the current user.
    Admin users can access any record.

    Args:
        record_id: UUID of the content record.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The ``ContentRecordRead`` for the requested record.

    Raises:
        HTTPException 404: If the record does not exist or is not owned
            by the current user.
    """
    if current_user.role == "admin":
        stmt = select(UniversalContentRecord).where(
            UniversalContentRecord.id == record_id
        )
    else:
        user_run_ids_subq = (
            select(CollectionRun.id)
            .where(CollectionRun.initiated_by == current_user.id)
            .scalar_subquery()
        )
        stmt = select(UniversalContentRecord).where(
            UniversalContentRecord.id == record_id,
            UniversalContentRecord.collection_run_id.in_(user_run_ids_subq),
        )

    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Content record '{record_id}' not found.",
        )

    return record


# ---------------------------------------------------------------------------
# Export — synchronous (up to 10 K records, returns file directly)
# ---------------------------------------------------------------------------


@router.get("/export")
async def export_content_sync(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    format: str = Query(
        default="csv",
        description="Export format: csv, xlsx, json, parquet, gexf.",
    ),
    platform: Optional[str] = Query(default=None, description="Filter by platform name."),
    arena: Optional[str] = Query(default=None, description="Filter by arena name."),
    query_design_id: Optional[uuid.UUID] = Query(default=None),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    language: Optional[str] = Query(default=None),
    run_id: Optional[uuid.UUID] = Query(
        default=None, description="Filter by specific collection run UUID."
    ),
    search_term: Optional[str] = Query(default=None),
    limit: int = Query(
        default=_EXPORT_SYNC_LIMIT,
        ge=1,
        le=_EXPORT_SYNC_LIMIT,
        description="Maximum records to export (hard cap: 10 000). For larger datasets use POST /export/async.",
    ),
    include_metadata: bool = Query(
        default=False,
        description="Include raw_metadata JSONB column (CSV only).",
    ),
) -> Response:
    """Export up to 10 000 content records directly as a file download.

    The response is returned synchronously — the file is assembled in memory
    and streamed to the client with appropriate ``Content-Disposition`` and
    ``Content-Type`` headers.

    For datasets larger than 10 000 records, use ``POST /content/export/async``
    which dispatches a background Celery task.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        format: Export format — one of ``csv``, ``xlsx``, ``json``,
            ``parquet``, ``gexf``.
        platform: Optional platform filter.
        arena: Optional arena filter.
        query_design_id: Optional query design UUID filter.
        date_from: Optional lower bound on ``published_at``.
        date_to: Optional upper bound on ``published_at``.
        language: Optional ISO 639-1 language code filter.
        run_id: Optional collection run UUID filter.
        search_term: Optional term contained in ``search_terms_matched``.
        limit: Maximum records (1–10 000; default 10 000).
        include_metadata: If True, include ``raw_metadata`` as a JSON string
            column (CSV export only).

    Returns:
        A ``Response`` with the file bytes and a ``Content-Disposition:
        attachment`` header.

    Raises:
        HTTPException 400: If the requested format is not supported.
        HTTPException 500: If serialization fails due to a missing optional
            dependency (openpyxl / pyarrow not installed).
    """
    if format not in _EXPORT_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported export format {format!r}. Choose from: {', '.join(_EXPORT_CONTENT_TYPES)}.",
        )

    stmt = _build_content_stmt(
        current_user=current_user,
        platform=platform,
        arena=arena,
        query_design_id=query_design_id,
        date_from=date_from,
        date_to=date_to,
        search_term=search_term,
        language=language,
        run_id=run_id,
        limit=limit,
    )

    db_result = await db.execute(stmt)
    orm_rows = list(db_result.scalars().all())
    records = [_record_to_dict(r) for r in orm_rows]

    exporter = ContentExporter()

    try:
        if format == "csv":
            file_bytes = await exporter.export_csv(records, include_metadata=include_metadata)
        elif format == "xlsx":
            file_bytes = await exporter.export_xlsx(records)
        elif format == "json":
            file_bytes = await exporter.export_json(records)
        elif format == "parquet":
            file_bytes = await exporter.export_parquet(records)
        else:  # gexf
            file_bytes = await exporter.export_gexf(records)
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    ext = _EXPORT_EXTENSIONS[format]
    filename = f"content_export.{ext}"
    content_type = _EXPORT_CONTENT_TYPES[format]

    logger.info(
        "export.sync.complete",
        user_id=str(current_user.id),
        format=format,
        record_count=len(records),
    )

    return Response(
        content=file_bytes,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Record-Count": str(len(records)),
        },
    )


# ---------------------------------------------------------------------------
# Export — async via Celery (for > 10 K records)
# ---------------------------------------------------------------------------


@router.post("/export/async", status_code=status.HTTP_202_ACCEPTED)
async def export_content_async(
    current_user: Annotated[User, Depends(get_current_active_user)],
    format: str = Query(
        default="csv",
        description="Export format: csv, xlsx, json, parquet, gexf.",
    ),
    platform: Optional[str] = Query(default=None),
    arena: Optional[str] = Query(default=None),
    query_design_id: Optional[uuid.UUID] = Query(default=None),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    language: Optional[str] = Query(default=None),
    run_id: Optional[uuid.UUID] = Query(default=None),
    search_term: Optional[str] = Query(default=None),
) -> dict[str, str]:
    """Dispatch an asynchronous export job for large datasets.

    Dispatches a ``export_content_records`` Celery task.  The task queries the
    database, serializes the result, uploads the file to MinIO under
    ``exports/{user_id}/{job_id}.{ext}``, and writes progress to Redis.

    Poll ``GET /content/export/{job_id}/status`` for progress updates.
    Download the completed file from ``GET /content/export/{job_id}/download``.

    Args:
        current_user: The authenticated, active user making the request.
        format: Export format — one of ``csv``, ``xlsx``, ``json``,
            ``parquet``, ``gexf``.
        platform: Optional platform filter.
        arena: Optional arena filter.
        query_design_id: Optional query design UUID.
        date_from: Optional lower bound on ``published_at``.
        date_to: Optional upper bound on ``published_at``.
        language: Optional ISO 639-1 language code.
        run_id: Optional collection run UUID.
        search_term: Optional term in ``search_terms_matched``.

    Returns:
        ``{"job_id": "<uuid>", "status": "pending"}``

    Raises:
        HTTPException 400: If the format is not supported.
    """
    if format not in _EXPORT_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported export format {format!r}. Choose from: {', '.join(_EXPORT_CONTENT_TYPES)}.",
        )

    job_id = str(uuid.uuid4())
    filters: dict[str, Any] = {}

    if platform:
        filters["platform"] = platform
    if arena:
        filters["arena"] = arena
    if query_design_id:
        filters["query_design_id"] = str(query_design_id)
    if date_from:
        filters["date_from"] = date_from.isoformat()
    if date_to:
        filters["date_to"] = date_to.isoformat()
    if language:
        filters["language"] = language
    if run_id:
        filters["run_id"] = str(run_id)
    if search_term:
        filters["search_term"] = search_term

    # Write initial pending status to Redis before dispatching the task
    # so that a status poll immediately after this response returns something
    # meaningful rather than a key-not-found.
    from issue_observatory.config.settings import get_settings
    import redis as redis_lib

    settings = get_settings()
    redis_client = redis_lib.from_url(settings.redis_url, decode_responses=True)
    redis_client.setex(
        f"export:{job_id}:status",
        86_400,
        json.dumps({"status": "pending", "pct_complete": 0}),
    )

    from issue_observatory.workers.export_tasks import export_content_records

    export_content_records.apply_async(
        kwargs={
            "user_id": str(current_user.id),
            "job_id": job_id,
            "filters": filters,
            "export_format": format,
        },
        task_id=job_id,
    )

    logger.info(
        "export.async.dispatched",
        job_id=job_id,
        user_id=str(current_user.id),
        format=format,
    )

    return {"job_id": job_id, "status": "pending"}


# ---------------------------------------------------------------------------
# Export job status
# ---------------------------------------------------------------------------


@router.get("/export/{job_id}/status")
async def get_export_job_status(
    job_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Return the current status of an async export job.

    Reads the Redis key ``export:{job_id}:status`` written by the
    ``export_content_records`` Celery task.

    Status values:
        - ``pending``: task is queued but not yet started.
        - ``running``: task is in progress; ``pct_complete`` (0–100) indicates
          progress.
        - ``complete``: export finished; ``download_url`` and ``record_count``
          are populated.
        - ``failed``: export failed; ``error`` contains the exception message.

    Args:
        job_id: UUID string of the export job (returned by POST /export/async).
        current_user: The authenticated, active user making the request.

    Returns:
        The status dict stored in Redis.

    Raises:
        HTTPException 404: If no status entry exists for the given job_id
            (job never started or TTL expired).
    """
    from issue_observatory.config.settings import get_settings
    import redis as redis_lib

    settings = get_settings()
    redis_client = redis_lib.from_url(settings.redis_url, decode_responses=True)
    raw = redis_client.get(f"export:{job_id}:status")

    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No export job found for job_id '{job_id}'. It may have expired or never been created.",
        )

    return json.loads(raw)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Export job download (redirect to pre-signed MinIO URL)
# ---------------------------------------------------------------------------


@router.get("/export/{job_id}/download")
async def download_export_file(
    job_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> RedirectResponse:
    """Redirect to a fresh MinIO pre-signed URL for a completed export file.

    Generates a new 1-hour pre-signed URL on each call so that the link
    remains usable even after the URL embedded in the status payload expires.

    Args:
        job_id: UUID string of the export job.
        current_user: The authenticated, active user making the request.

    Returns:
        HTTP 307 redirect to the pre-signed MinIO download URL.

    Raises:
        HTTPException 404: If no status entry exists or the job is not yet
            complete.
        HTTPException 400: If the job failed or is still in progress.
    """
    from datetime import timedelta

    import redis as redis_lib
    from minio import Minio  # type: ignore[import-untyped]

    from issue_observatory.config.settings import get_settings

    settings = get_settings()
    redis_client = redis_lib.from_url(settings.redis_url, decode_responses=True)
    raw = redis_client.get(f"export:{job_id}:status")

    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No export job found for job_id '{job_id}'.",
        )

    job_status = json.loads(raw)

    if job_status.get("status") == "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Export job '{job_id}' failed: {job_status.get('error', 'unknown error')}.",
        )

    if job_status.get("status") != "complete":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Export job '{job_id}' is not yet complete "
                f"(status: {job_status.get('status', 'unknown')}, "
                f"pct_complete: {job_status.get('pct_complete', 0)})."
            ),
        )

    object_key: Optional[str] = job_status.get("object_key")
    if not object_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Export job '{job_id}' has no object_key stored in status.",
        )

    minio_client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        secure=settings.minio_secure,
    )

    presigned_url = minio_client.presigned_get_object(
        settings.minio_bucket,
        object_key,
        expires=timedelta(hours=1),
    )

    return RedirectResponse(url=presigned_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
