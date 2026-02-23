"""FastAPI router for the web scraper enrichment service.

Manages the lifecycle of scraping jobs: creating, monitoring, cancelling,
and streaming progress via Server-Sent Events.

All routes are owner-scoped: users can only operate on jobs they created.
Admin users bypass the ownership check.

Routes:
    POST   /scraping-jobs/                  — create + enqueue job
    GET    /scraping-jobs/                  — list jobs (paginated)
    GET    /scraping-jobs/{job_id}          — detail + progress counters
    POST   /scraping-jobs/{job_id}/cancel   — cancel a running job
    DELETE /scraping-jobs/{job_id}          — delete completed/failed/cancelled job
    GET    /scraping-jobs/{job_id}/stream   — SSE progress stream
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Annotated, AsyncGenerator, Optional

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.api.dependencies import (
    PaginationParams,
    get_current_active_user,
    get_pagination,
    ownership_guard,
)
from issue_observatory.core.database import get_db
from issue_observatory.core.models.scraping import ScrapingJob
from issue_observatory.core.models.users import User
from issue_observatory.core.schemas.scraping import ScrapingJobCreate, ScrapingJobRead

logger = structlog.get_logger(__name__)

router = APIRouter()

#: Terminal states for SSE stream termination and delete guard.
_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"completed", "failed", "cancelled"}
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _get_job_or_404(
    job_id: uuid.UUID,
    db: AsyncSession,
) -> ScrapingJob:
    """Fetch a ScrapingJob by primary key or raise HTTP 404."""
    result = await db.execute(
        select(ScrapingJob).where(ScrapingJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scraping job '{job_id}' not found.",
        )
    return job


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@router.post("/", response_model=ScrapingJobRead, status_code=status.HTTP_201_CREATED)
async def create_scraping_job(
    payload: ScrapingJobCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ScrapingJob:
    """Create and enqueue a new scraping job.

    Validates source parameters, inserts the job row in ``'pending'`` status,
    and dispatches the :func:`~issue_observatory.scraper.tasks.scrape_urls_task`
    Celery task.

    Args:
        payload: Validated :class:`~issue_observatory.core.schemas.scraping.ScrapingJobCreate`.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The newly created :class:`~issue_observatory.core.schemas.scraping.ScrapingJobRead`.

    Raises:
        HTTPException 422: If source parameters are inconsistent.
    """
    # Validate source params
    if payload.source_type == "collection_run" and not payload.source_collection_run_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="source_collection_run_id is required when source_type='collection_run'.",
        )
    if payload.source_type == "manual_urls" and not payload.source_urls:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="source_urls is required when source_type='manual_urls'.",
        )

    job = ScrapingJob(
        created_by=current_user.id,
        query_design_id=payload.query_design_id,
        source_type=payload.source_type,
        source_collection_run_id=payload.source_collection_run_id,
        source_urls=payload.source_urls,
        delay_min=payload.delay_min,
        delay_max=payload.delay_max,
        timeout_seconds=payload.timeout_seconds,
        respect_robots_txt=payload.respect_robots_txt,
        use_playwright_fallback=payload.use_playwright_fallback,
        max_retries=payload.max_retries,
        status="pending",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Dispatch Celery task
    from issue_observatory.scraper.tasks import scrape_urls_task  # noqa: PLC0415

    scrape_urls_task.apply_async(
        kwargs={"job_id": str(job.id)},
        queue="scraping",
    )

    logger.info(
        "scraping_job_created",
        job_id=str(job.id),
        source_type=job.source_type,
        user_id=str(current_user.id),
    )
    return job


@router.post("/form", response_class=HTMLResponse)
async def create_scraping_job_form(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    source_type: Annotated[str, Form()],
    source_collection_run_id: Annotated[Optional[str], Form()] = None,
    source_urls: Annotated[Optional[str], Form()] = None,
    query_design_id: Annotated[Optional[str], Form()] = None,
    delay_min: Annotated[float, Form()] = 2.0,
    delay_max: Annotated[float, Form()] = 5.0,
    timeout_seconds: Annotated[int, Form()] = 30,
    respect_robots_txt: Annotated[Optional[str], Form()] = None,
    use_playwright_fallback: Annotated[Optional[str], Form()] = None,
    max_retries: Annotated[Optional[int], Form()] = None,
) -> HTMLResponse:
    """Create a scraping job from a browser form submission.

    Accepts application/x-www-form-urlencoded data from HTMX, parses it into
    a ScrapingJobCreate payload, and delegates to the main create_scraping_job
    function for validation and job creation.

    After successful creation, returns an HTML fragment (the jobs table) by
    querying all jobs and rendering the _jobs_table.html template.

    Args:
        request: The incoming HTTP request.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        source_type: "collection_run" or "manual_urls" (form field).
        source_collection_run_id: Optional UUID string of the collection run (form field).
        source_urls: Optional newline-separated URLs (form field, textarea).
        query_design_id: Optional UUID string of the query design (form field).
        delay_min: Minimum inter-request delay in seconds (form field, default 2.0).
        delay_max: Maximum inter-request delay in seconds (form field, default 5.0).
        timeout_seconds: HTTP request timeout in seconds (form field, default 30).
        respect_robots_txt: Checkbox value "on" if checked (form field).
        use_playwright_fallback: Checkbox value "on" if checked (form field).
        max_retries: Per-URL retry count on transient errors (form field, default 2).

    Returns:
        HTML fragment containing the updated jobs table.

    Raises:
        HTTPException 422: If source parameters are inconsistent or invalid UUIDs.
    """
    # Parse UUIDs
    parsed_collection_run_id: Optional[uuid.UUID] = None
    if source_collection_run_id:
        try:
            parsed_collection_run_id = uuid.UUID(source_collection_run_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid source_collection_run_id format",
            ) from exc

    parsed_query_design_id: Optional[uuid.UUID] = None
    if query_design_id:
        try:
            parsed_query_design_id = uuid.UUID(query_design_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid query_design_id format",
            ) from exc

    # Parse source URLs from textarea (newline-separated)
    parsed_urls: Optional[list[str]] = None
    if source_urls:
        parsed_urls = [
            line.strip()
            for line in source_urls.strip().split("\n")
            if line.strip()
        ]

    # Convert checkbox values to booleans (HTML forms send "on" for checked)
    respect_robots = respect_robots_txt == "on"
    use_playwright = use_playwright_fallback == "on"

    # Build a ScrapingJobCreate payload
    payload = ScrapingJobCreate(
        source_type=source_type,
        source_collection_run_id=parsed_collection_run_id,
        source_urls=parsed_urls,
        query_design_id=parsed_query_design_id,
        delay_min=delay_min,
        delay_max=delay_max,
        timeout_seconds=timeout_seconds,
        respect_robots_txt=respect_robots,
        use_playwright_fallback=use_playwright,
        max_retries=max_retries if max_retries is not None else 2,
    )

    # Delegate to the main create function (reuses all validation logic)
    await create_scraping_job(payload, db, current_user)

    logger.info(
        "scraping_job_created_via_form",
        user_id=str(current_user.id),
    )

    # Return updated jobs table by querying all jobs for the user
    stmt = (
        select(ScrapingJob)
        .where(ScrapingJob.created_by == current_user.id)
        .order_by(ScrapingJob.created_at.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    jobs = list(result.scalars().all())

    # Render the jobs table template
    if not hasattr(request.app.state, "templates"):
        raise RuntimeError("Templates not initialized")
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "scraping/_jobs_table.html",
        {"request": request, "jobs": jobs, "user": current_user},
        media_type="text/html",
    )


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@router.get("/")
async def list_scraping_jobs(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    pagination: Annotated[PaginationParams, Depends(get_pagination)],
    status_filter: Optional[str] = None,
):
    """List scraping jobs created by the current user.

    Returns HTML fragment when Accept header includes text/html, otherwise JSON.

    Args:
        request: The current HTTP request.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        pagination: Cursor and page-size parameters from query string.
        status_filter: Optional filter on job status.

    Returns:
        A list of :class:`~issue_observatory.core.schemas.scraping.ScrapingJobRead` dicts
        or an HTML fragment of the jobs table.
    """
    stmt = (
        select(ScrapingJob)
        .where(ScrapingJob.created_by == current_user.id)
        .order_by(ScrapingJob.created_at.desc())
        .limit(pagination.page_size)
    )

    if status_filter is not None:
        stmt = stmt.where(ScrapingJob.status == status_filter)

    if pagination.cursor:
        try:
            cursor_id = uuid.UUID(pagination.cursor)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="cursor must be a valid UUID.",
            ) from exc
        stmt = stmt.where(ScrapingJob.id < cursor_id)

    result = await db.execute(stmt)
    jobs = list(result.scalars().all())

    # Return HTML fragment for HTMX requests
    accept = request.headers.get("Accept", "")
    if "text/html" in accept:
        if not hasattr(request.app.state, "templates"):
            raise RuntimeError("Templates not initialized")
        templates = request.app.state.templates
        return templates.TemplateResponse(
            "scraping/_jobs_table.html",
            {"request": request, "jobs": jobs, "user": current_user},
            media_type="text/html",
        )

    # Return JSON for API requests
    return jobs


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


@router.get("/{job_id}", response_model=ScrapingJobRead)
async def get_scraping_job(
    job_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ScrapingJob:
    """Retrieve a scraping job with current progress counters.

    Args:
        job_id: UUID of the scraping job.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The :class:`~issue_observatory.core.schemas.scraping.ScrapingJobRead`.

    Raises:
        HTTPException 404: If the job does not exist.
        HTTPException 403: If the caller did not create the job (and is not admin).
    """
    job = await _get_job_or_404(job_id, db)
    ownership_guard(job.created_by, current_user)
    return job


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


@router.post("/{job_id}/cancel", response_model=ScrapingJobRead)
async def cancel_scraping_job(
    job_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ScrapingJob:
    """Cancel a pending or running scraping job.

    Dispatches :func:`~issue_observatory.scraper.tasks.cancel_scraping_job_task`
    to revoke the Celery worker task and mark the job as ``'cancelled'``.

    Args:
        job_id: UUID of the scraping job to cancel.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        The updated :class:`~issue_observatory.core.schemas.scraping.ScrapingJobRead`.

    Raises:
        HTTPException 404: If the job does not exist.
        HTTPException 403: If the caller did not create the job (and is not admin).
        HTTPException 409: If the job is already in a terminal state.
    """
    job = await _get_job_or_404(job_id, db)
    ownership_guard(job.created_by, current_user)

    if job.status in _TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot cancel a job with status '{job.status}'. "
                "Only 'pending' and 'running' jobs can be cancelled."
            ),
        )

    # Dispatch cancel task (updates DB status to 'cancelled' asynchronously)
    from issue_observatory.scraper.tasks import cancel_scraping_job_task  # noqa: PLC0415

    cancel_scraping_job_task.apply_async(kwargs={"job_id": str(job_id)})

    # Optimistically update the DB row so the response reflects the intent
    job.status = "cancelled"
    await db.commit()
    await db.refresh(job)

    logger.info(
        "scraping_job_cancelled",
        job_id=str(job_id),
        user_id=str(current_user.id),
    )
    return job


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_scraping_job(
    job_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    """Delete a scraping job (only if in a terminal state).

    Args:
        job_id: UUID of the scraping job to delete.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Raises:
        HTTPException 404: If the job does not exist.
        HTTPException 403: If the caller did not create the job (and is not admin).
        HTTPException 409: If the job is still running.
    """
    job = await _get_job_or_404(job_id, db)
    ownership_guard(job.created_by, current_user)

    if job.status not in _TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot delete a job with status '{job.status}'. "
                "Cancel the job first."
            ),
        )

    await db.delete(job)
    await db.commit()

    logger.info(
        "scraping_job_deleted",
        job_id=str(job_id),
        user_id=str(current_user.id),
    )


# ---------------------------------------------------------------------------
# SSE progress stream
# ---------------------------------------------------------------------------


@router.get("/{job_id}/stream")
async def stream_scraping_job(
    job_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> StreamingResponse:
    """Stream live scraping job progress via Server-Sent Events.

    Polls the ``scraping_jobs`` DB row every 2 seconds and emits
    ``progress`` events with updated counters until the job reaches a
    terminal state or the client disconnects.

    **Event types**:

    ``progress``::

        event: progress
        data: {"status":"running","total_urls":50,"urls_enriched":12,
                "urls_failed":1,"urls_skipped":0}

    ``job_complete``::

        event: job_complete
        data: {"status":"completed","total_urls":50,"urls_enriched":48,
                "urls_failed":1,"urls_skipped":1}

    Args:
        job_id: UUID of the scraping job to stream.
        request: The incoming HTTP request (used for disconnect detection).
        db: Injected async database session.
        current_user: The authenticated, active user making the request.

    Returns:
        A :class:`~fastapi.responses.StreamingResponse` with
        ``Content-Type: text/event-stream``.

    Raises:
        HTTPException 404: If the job does not exist.
        HTTPException 403: If the caller did not create the job.
    """
    job = await _get_job_or_404(job_id, db)
    ownership_guard(job.created_by, current_user)

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE frames by polling the job row."""
        # Emit immediate snapshot
        payload = {
            "status": job.status,
            "total_urls": job.total_urls,
            "urls_enriched": job.urls_enriched,
            "urls_failed": job.urls_failed,
            "urls_skipped": job.urls_skipped,
        }
        yield f"event: progress\ndata: {json.dumps(payload)}\n\n"

        if job.status in _TERMINAL_STATUSES:
            yield f"event: job_complete\ndata: {json.dumps(payload)}\n\n"
            return

        # Poll loop
        while True:
            if await request.is_disconnected():
                break

            await asyncio.sleep(2.0)

            # Refresh job row
            await db.refresh(job)

            current_payload = {
                "status": job.status,
                "total_urls": job.total_urls,
                "urls_enriched": job.urls_enriched,
                "urls_failed": job.urls_failed,
                "urls_skipped": job.urls_skipped,
            }
            yield f"event: progress\ndata: {json.dumps(current_payload)}\n\n"

            if job.status in _TERMINAL_STATUSES:
                yield f"event: job_complete\ndata: {json.dumps(current_payload)}\n\n"
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
