"""Celery tasks for the web scraper enrichment service.

Two tasks are provided:

``scrape_urls_task``
    Enriches a set of URLs by fetching page text and storing it in
    ``content_records``.  Supports two source modes:

    - ``"collection_run"`` — updates existing thin records from a prior run.
    - ``"manual_urls"``    — inserts new records for user-supplied URLs.

``cancel_scraping_job_task``
    Revokes the running Celery task and marks the job as cancelled.

Task naming convention::

    issue_observatory.scraper.tasks.<action>

Retry policy:
    Scraping is stateful (each URL mutates the DB), so ``max_retries=0``.
    The task handles per-URL errors internally and continues to the next URL.

Database updates:
    All DB writes use a synchronous session (``get_sync_session()``) to avoid
    running a nested event loop inside the Celery worker process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timezone
from typing import Any

import httpx

from issue_observatory.scraper.content_extractor import extract_from_html
from issue_observatory.scraper.http_fetcher import fetch_url
from issue_observatory.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_ARENA = "scraper"
_PLATFORM = "web"


# ---------------------------------------------------------------------------
# Internal DB helpers (synchronous, best-effort)
# ---------------------------------------------------------------------------


def _load_job(job_id: str) -> Any:
    """Load a ScrapingJob row by ID using a synchronous session.

    Returns the raw dict of column values, or ``None`` if not found.
    """
    from issue_observatory.core.database import get_sync_session  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    with get_sync_session() as session:
        row = session.execute(
            text(
                """
                SELECT id, source_type, source_collection_run_id, source_urls,
                       delay_min, delay_max, timeout_seconds, respect_robots_txt,
                       use_playwright_fallback, max_retries, status
                FROM scraping_jobs
                WHERE id = :job_id
                """
            ),
            {"job_id": job_id},
        ).fetchone()
        if row is None:
            return None
        return dict(row._mapping)


def _update_job(job_id: str, **kwargs: Any) -> None:
    """Update scraping_jobs columns in a best-effort synchronous write."""
    if not kwargs:
        return
    from issue_observatory.core.database import get_sync_session  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    set_clauses = ", ".join(f"{k} = :{k}" for k in kwargs)
    params = {"job_id": job_id, **kwargs}
    try:
        with get_sync_session() as session:
            session.execute(
                text(f"UPDATE scraping_jobs SET {set_clauses} WHERE id = :job_id"),
                params,
            )
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("scraper: failed to update scraping_jobs(%s): %s", job_id, exc)


def _increment_counter(job_id: str, column: str) -> None:
    """Atomically increment a progress counter column."""
    from issue_observatory.core.database import get_sync_session  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    try:
        with get_sync_session() as session:
            session.execute(
                text(
                    f"UPDATE scraping_jobs SET {column} = {column} + 1 WHERE id = :job_id"
                ),
                {"job_id": job_id},
            )
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "scraper: failed to increment %s for job %s: %s", column, job_id, exc
        )


def _get_thin_records(collection_run_id: str) -> list[tuple[str, Any, str]]:
    """Return (id, published_at, url) tuples for thin records in a collection run.

    Only records with ``text_content IS NULL`` are returned.
    """
    from issue_observatory.core.database import get_sync_session  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    with get_sync_session() as session:
        rows = session.execute(
            text(
                """
                SELECT id::text, published_at, url
                FROM content_records
                WHERE collection_run_id = :run_id
                  AND text_content IS NULL
                  AND url IS NOT NULL
                """
            ),
            {"run_id": collection_run_id},
        ).fetchall()

    return [(str(r[0]), r[1], str(r[2])) for r in rows if r[2]]


def _update_content_record_v2(
    record_id: str,
    published_at: Any,
    text_value: str | None,
    title: str | None,
    language: str | None,
    html: str | None,
) -> None:
    """Update an existing content_record with scraped content.

    Uses both ``id`` AND ``published_at`` in the WHERE clause so PostgreSQL
    can prune to the correct range partition and avoid full-table scans.
    """
    from issue_observatory.core.database import get_sync_session  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    raw_html_snippet = (html or "")[:50_000]

    with get_sync_session() as session:
        session.execute(
            text(
                """
                UPDATE content_records
                SET text_content = :text_value,
                    title = COALESCE(:title, title),
                    language = COALESCE(:language, language),
                    raw_metadata = jsonb_set(
                        COALESCE(raw_metadata, '{}'),
                        '{scraped_html}',
                        to_jsonb(:html::text)
                    )
                WHERE id = :record_id
                  AND published_at IS NOT DISTINCT FROM :published_at
                """
            ),
            {
                "text_value": text_value,
                "title": title,
                "language": language,
                "html": raw_html_snippet,
                "record_id": record_id,
                "published_at": published_at,
            },
        )
        session.commit()


def _insert_manual_record(
    url: str,
    text_value: str | None,
    title: str | None,
    language: str | None,
    html: str | None,
    job_id: str,
) -> None:
    """Insert a new content_record for a manually scraped URL."""
    from issue_observatory.core.database import get_sync_session  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    raw_html_snippet = (html or "")[:50_000]

    with get_sync_session() as session:
        session.execute(
            text(
                """
                INSERT INTO content_records (
                    platform, arena, content_type, url,
                    text_content, title, language,
                    collected_at, collection_tier,
                    raw_metadata, published_at
                ) VALUES (
                    'web', 'scraper', 'scraped_web_page', :url,
                    :text_value, :title, :language,
                    NOW(), 'free',
                    jsonb_build_object(
                        'scraped_html', :html::text,
                        'scraping_job_id', :job_id::text
                    ),
                    NOW()
                )
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "url": url,
                "text_value": text_value,
                "title": title,
                "language": language,
                "html": raw_html_snippet,
                "job_id": job_id,
            },
        )
        session.commit()


# ---------------------------------------------------------------------------
# Async scraping engine
# ---------------------------------------------------------------------------


async def _run_scraping(job_id: str, celery_task_id: str) -> None:
    """Async implementation of the scraping job.

    Loads the job config, builds the URL work-list, and iterates over each
    URL: fetches HTML (with optional Playwright fallback), extracts text, and
    persists the result.

    Args:
        job_id: UUID string of the ScrapingJob.
        celery_task_id: ID of the Celery task for cancellation support.
    """
    # ---- Load job config ---------------------------------------------------
    job = _load_job(job_id)
    if job is None:
        logger.error("scraper: job %s not found", job_id)
        return

    _update_job(
        job_id,
        status="running",
        celery_task_id=celery_task_id,
        started_at=datetime.now(tz=timezone.utc),
    )

    # ---- Build URL work-list -----------------------------------------------
    work_list: list[tuple[str | None, Any, str]] = []  # (record_id, published_at, url)

    if job["source_type"] == "collection_run":
        run_id = str(job["source_collection_run_id"])
        thin_records = _get_thin_records(run_id)
        work_list = [(rec_id, pub_at, url) for rec_id, pub_at, url in thin_records]
        logger.info(
            "scraper: job %s — collection_run mode, %d thin records found",
            job_id,
            len(work_list),
        )
    else:
        # manual_urls mode
        raw_urls = job.get("source_urls") or []
        if isinstance(raw_urls, str):
            raw_urls = json.loads(raw_urls)
        work_list = [(None, None, url) for url in raw_urls if url]
        logger.info(
            "scraper: job %s — manual_urls mode, %d URLs",
            job_id,
            len(work_list),
        )

    _update_job(job_id, total_urls=len(work_list))

    # ---- Fetch loop --------------------------------------------------------
    robots_cache: dict[str, bool] = {}

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for record_id, published_at, url in work_list:
            # Polite delay
            await asyncio.sleep(
                random.uniform(job["delay_min"], job["delay_max"])
            )

            try:
                # httpx fetch
                result = await fetch_url(
                    url,
                    client=client,
                    timeout=int(job["timeout_seconds"]),
                    respect_robots=bool(job["respect_robots_txt"]),
                    robots_cache=robots_cache,
                )

                # Playwright fallback if JS-only shell detected
                if result.needs_playwright and job["use_playwright_fallback"]:
                    logger.info(
                        "scraper: job %s — playwright fallback for %s", job_id, url
                    )
                    from issue_observatory.scraper.playwright_fetcher import (  # noqa: PLC0415
                        fetch_url_playwright,
                    )

                    result = await fetch_url_playwright(
                        url, timeout=int(job["timeout_seconds"])
                    )

                if result.error and not result.html:
                    # Skip or robots-blocked — still count as skipped
                    logger.debug(
                        "scraper: job %s — skipping %s: %s", job_id, url, result.error
                    )
                    _increment_counter(job_id, "urls_skipped")
                    continue

                # Extract content
                extracted = extract_from_html(result.html or "", result.final_url or url)

                # Persist
                if record_id is not None:
                    # collection_run mode: UPDATE existing record
                    _update_content_record_v2(
                        record_id=record_id,
                        published_at=published_at,
                        text_value=extracted.text,
                        title=extracted.title,
                        language=extracted.language,
                        html=result.html,
                    )
                else:
                    # manual_urls mode: INSERT new record
                    _insert_manual_record(
                        url=url,
                        text_value=extracted.text,
                        title=extracted.title,
                        language=extracted.language,
                        html=result.html,
                        job_id=job_id,
                    )

                _increment_counter(job_id, "urls_enriched")
                logger.debug("scraper: job %s — enriched %s", job_id, url)

            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "scraper: job %s — error processing %s: %s", job_id, url, exc
                )
                _increment_counter(job_id, "urls_failed")

    # ---- Mark completed ---------------------------------------------------
    _update_job(
        job_id,
        status="completed",
        completed_at=datetime.now(tz=timezone.utc),
    )
    logger.info("scraper: job %s completed", job_id)


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.scraper.tasks.scrape_urls_task",
    bind=True,
    acks_late=True,
    max_retries=0,
    soft_time_limit=7_200,   # 2 hours
    time_limit=10_800,       # 3 hours
)
def scrape_urls_task(self: Any, job_id: str) -> dict[str, Any]:
    """Fetch and store page text for all URLs in a ScrapingJob.

    Runs the async scraping engine via ``asyncio.run()``.  No auto-retry
    (scraping is stateful); the task handles per-URL errors internally.

    Args:
        job_id: UUID string of the ScrapingJob to execute.

    Returns:
        Dict with ``job_id`` and final ``status``.
    """
    logger.info("scraper: scrape_urls_task started for job=%s", job_id)
    try:
        asyncio.run(_run_scraping(job_id, self.request.id))
    except Exception as exc:  # noqa: BLE001
        logger.error("scraper: scrape_urls_task failed for job=%s: %s", job_id, exc)
        _update_job(
            job_id,
            status="failed",
            error_message=str(exc),
            completed_at=datetime.now(tz=timezone.utc),
        )
        raise

    return {"job_id": job_id, "status": "completed"}


@celery_app.task(
    name="issue_observatory.scraper.tasks.cancel_scraping_job_task",
    bind=False,
    acks_late=True,
)
def cancel_scraping_job_task(job_id: str) -> dict[str, Any]:
    """Revoke the running Celery task for a ScrapingJob and mark it cancelled.

    Args:
        job_id: UUID string of the ScrapingJob to cancel.

    Returns:
        Dict with ``job_id`` and final ``status``.
    """
    from issue_observatory.core.database import get_sync_session  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    try:
        with get_sync_session() as session:
            row = session.execute(
                text(
                    "SELECT celery_task_id FROM scraping_jobs WHERE id = :job_id"
                ),
                {"job_id": job_id},
            ).fetchone()

        if row and row[0]:
            celery_app.control.revoke(row[0], terminate=True, signal="SIGTERM")
            logger.info(
                "scraper: revoked celery task %s for job %s", row[0], job_id
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "scraper: failed to revoke celery task for job %s: %s", job_id, exc
        )

    _update_job(
        job_id,
        status="cancelled",
        completed_at=datetime.now(tz=timezone.utc),
    )
    logger.info("scraper: job %s cancelled", job_id)
    return {"job_id": job_id, "status": "cancelled"}
