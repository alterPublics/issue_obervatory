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
from datetime import UTC, datetime
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
    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

    with get_sync_session() as session:
        row = session.execute(
            text(
                """
                SELECT id, source_type, source_collection_run_id, source_urls,
                       url_filter_criteria,
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
    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

    set_clauses = ", ".join(f"{k} = :{k}" for k in kwargs)
    params = {"job_id": job_id, **kwargs}
    try:
        with get_sync_session() as session:
            session.execute(
                text(f"UPDATE scraping_jobs SET {set_clauses} WHERE id = :job_id"),
                params,
            )
            session.commit()
    except Exception as exc:
        logger.warning("scraper: failed to update scraping_jobs(%s): %s", job_id, exc)


def _increment_counter(job_id: str, column: str) -> None:
    """Atomically increment a progress counter column."""
    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

    try:
        with get_sync_session() as session:
            session.execute(
                text(
                    f"UPDATE scraping_jobs SET {column} = {column} + 1 WHERE id = :job_id"
                ),
                {"job_id": job_id},
            )
            session.commit()
    except Exception as exc:
        logger.warning(
            "scraper: failed to increment %s for job %s: %s", column, job_id, exc
        )


def _record_url_error(job_id: str, url: str, reason: str) -> None:
    """Append a URL error reason to the job's url_errors JSONB dict."""
    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

    # Truncate reason to avoid bloating the JSONB
    reason = (reason or "unknown")[:200]
    try:
        with get_sync_session() as session:
            session.execute(
                text("""
                    UPDATE scraping_jobs
                    SET url_errors = jsonb_set(
                        COALESCE(url_errors, '{}'),
                        ARRAY[:url_key],
                        to_jsonb(:reason::text)
                    )
                    WHERE id = :job_id
                """),
                {"job_id": job_id, "url_key": url, "reason": reason},
            )
            session.commit()
    except Exception as exc:
        logger.debug("scraper: failed to record url_error for %s: %s", url, exc)


def _set_scrape_status_failed(record_id: str, published_at: Any) -> None:
    """Mark a content_record's scrape_status as 'failed'."""
    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

    try:
        with get_sync_session() as session:
            session.execute(
                text(
                    """
                    UPDATE content_records
                    SET scrape_status = 'failed'
                    WHERE id = :record_id
                      AND published_at IS NOT DISTINCT FROM :published_at
                    """
                ),
                {"record_id": record_id, "published_at": published_at},
            )
            session.commit()
    except Exception as exc:
        logger.warning(
            "scraper: failed to set scrape_status=failed for record %s: %s",
            record_id,
            exc,
        )


def _get_thin_records(collection_run_id: str) -> list[tuple[str, Any, str]]:
    """Return (id, published_at, url) tuples for thin records in a collection run.

    Only records with ``text_content IS NULL`` are returned.
    """
    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

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
    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

    raw_html_snippet = (html or "")[:50_000]

    with get_sync_session() as session:
        session.execute(
            text(
                """
                UPDATE content_records
                SET text_content = :text_value,
                    title = COALESCE(:title, title),
                    language = COALESCE(:language, language),
                    scrape_status = 'scraped',
                    raw_metadata = jsonb_set(
                        jsonb_set(
                            COALESCE(raw_metadata, '{}'),
                            '{scraped_html}',
                            to_jsonb(CAST(:html AS text))
                        ),
                        '{original_summary}',
                        CASE
                            WHEN raw_metadata->'original_summary' IS NULL
                                 AND text_content IS NOT NULL
                            THEN to_jsonb(text_content)
                            ELSE COALESCE(raw_metadata->'original_summary', 'null'::jsonb)
                        END
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
    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

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
                        'scraped_html', CAST(:html AS text),
                        'scraping_job_id', CAST(:job_id AS text)
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
        started_at=datetime.now(tz=UTC),
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
                    from issue_observatory.scraper.playwright_fetcher import (
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
                    _record_url_error(job_id, url, result.error)
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

            except Exception as exc:
                logger.warning(
                    "scraper: job %s — error processing %s: %s", job_id, url, exc
                )
                _increment_counter(job_id, "urls_failed")
                _record_url_error(job_id, url, f"error: {exc}")
                # Mark scrape_status as 'failed' for collection_run records
                if record_id is not None:
                    _set_scrape_status_failed(record_id, published_at)

    # ---- Mark completed ---------------------------------------------------
    _update_job(
        job_id,
        status="completed",
        completed_at=datetime.now(tz=UTC),
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
    except Exception as exc:
        logger.error("scraper: scrape_urls_task failed for job=%s: %s", job_id, exc)
        _update_job(
            job_id,
            status="failed",
            error_message=str(exc),
            completed_at=datetime.now(tz=UTC),
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
    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

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
    except Exception as exc:
        logger.warning(
            "scraper: failed to revoke celery task for job %s: %s", job_id, exc
        )

    _update_job(
        job_id,
        status="cancelled",
        completed_at=datetime.now(tz=UTC),
    )
    logger.info("scraper: job %s cancelled", job_id)
    return {"job_id": job_id, "status": "cancelled"}


# ---------------------------------------------------------------------------
# Task: scrape_extracted_urls_task
# ---------------------------------------------------------------------------


async def _run_extracted_url_scraping(job_id: str, celery_task_id: str) -> None:
    """Async implementation for scraping extracted URLs.

    Routes URLs to the correct handler based on their type:

    1. Video platform URLs (YouTube/TikTok) -> yt-dlp download via
       :class:`~issue_observatory.scraper.video_downloader.VideoDownloader`.
    2. Google Search result URLs -> UPDATE existing content_record in-place.
    3. Everything else -> standard web scraping pipeline (httpx + optional
       Playwright fallback + trafilatura extraction).

    Args:
        job_id: UUID string of the ScrapingJob to execute.
        celery_task_id: Celery task ID used for progress tracking and cancellation.
    """
    from issue_observatory.analysis.url_cleaner import is_video_platform_url
    from issue_observatory.config.settings import get_settings

    job = _load_job(job_id)
    if job is None:
        logger.error("scraper: extracted_urls job %s not found", job_id)
        return

    _update_job(
        job_id,
        status="running",
        celery_task_id=celery_task_id,
        started_at=datetime.now(tz=UTC),
    )

    # Build URL work list from source_urls
    raw_urls = job.get("source_urls") or []
    if isinstance(raw_urls, str):
        raw_urls = json.loads(raw_urls)

    work_list: list[str] = [url for url in raw_urls if url]
    _update_job(job_id, total_urls=len(work_list))

    if not work_list:
        _update_job(job_id, status="completed", completed_at=datetime.now(tz=UTC))
        return

    # Partition URLs by type
    video_urls: list[str] = []
    web_urls: list[str] = []

    for url in work_list:
        if is_video_platform_url(url):
            video_urls.append(url)
        else:
            web_urls.append(url)

    logger.info(
        "scraper: extracted_urls job %s — %d video, %d web URLs",
        job_id,
        len(video_urls),
        len(web_urls),
    )

    # --- Process video URLs ---
    if video_urls:
        settings = get_settings()
        from issue_observatory.scraper.video_downloader import VideoDownloader

        downloader = VideoDownloader(
            storage_path=settings.video_storage_path,
            max_size_mb=settings.video_max_file_size_mb,
        )

        for url in video_urls:
            try:
                result = downloader.download(url)
                if result.success:
                    _increment_counter(job_id, "urls_enriched")
                else:
                    _increment_counter(job_id, "urls_failed")
                    _record_url_error(job_id, url, f"video download: {result.error}")
                    logger.warning(
                        "scraper: video download failed for %s: %s", url, result.error
                    )
            except Exception as exc:
                logger.warning("scraper: video download error for %s: %s", url, exc)
                _increment_counter(job_id, "urls_failed")
                _record_url_error(job_id, url, f"video error: {exc}")

    # --- Process web URLs ---
    robots_cache: dict[str, bool] = {}
    max_retries = 2

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for url in web_urls:
            await asyncio.sleep(random.uniform(job["delay_min"], job["delay_max"]))

            try:
                # Resolve URL shorteners (bit.ly, t.co, etc.) via HEAD first
                resolved_url = await _resolve_shortener(client, url)

                # Check if this URL exists as a google_search record
                google_record = _find_google_search_record(resolved_url)

                # Fetch HTML with retries on transient errors
                fetch_result = None
                for attempt in range(1, max_retries + 1):
                    fetch_result = await fetch_url(
                        resolved_url,
                        client=client,
                        timeout=int(job["timeout_seconds"]),
                        respect_robots=bool(job["respect_robots_txt"]),
                        robots_cache=robots_cache,
                    )

                    # Retry on timeout or transient server errors
                    if fetch_result.error and fetch_result.error in (
                        "timeout",
                        "request error",
                    ) or (
                        fetch_result.status_code
                        and fetch_result.status_code in (502, 503, 504, 429)
                    ):
                        if attempt < max_retries:
                            logger.debug(
                                "scraper: retry %d/%d for %s (%s)",
                                attempt, max_retries, url, fetch_result.error,
                            )
                            await asyncio.sleep(2 * attempt)
                            continue
                    break

                if fetch_result.needs_playwright and job["use_playwright_fallback"]:
                    from issue_observatory.scraper.playwright_fetcher import (
                        fetch_url_playwright,
                    )

                    fetch_result = await fetch_url_playwright(
                        resolved_url, timeout=int(job["timeout_seconds"])
                    )

                if fetch_result.error and not fetch_result.html:
                    _increment_counter(job_id, "urls_skipped")
                    _record_url_error(job_id, url, fetch_result.error)
                    continue

                extracted = extract_from_html(
                    fetch_result.html or "", fetch_result.final_url or url
                )

                if google_record:
                    # Special case: UPDATE existing google_search record with scraped body
                    _update_content_record_v2(
                        record_id=google_record["id"],
                        published_at=google_record["published_at"],
                        text_value=extracted.text,
                        title=extracted.title,
                        language=extracted.language,
                        html=fetch_result.html,
                    )
                    logger.debug(
                        "scraper: updated google_search record %s with scraped content",
                        google_record["id"],
                    )
                else:
                    # Standard path: INSERT a new content_record
                    _insert_manual_record(
                        url=url,
                        text_value=extracted.text,
                        title=extracted.title,
                        language=extracted.language,
                        html=fetch_result.html,
                        job_id=job_id,
                    )

                _increment_counter(job_id, "urls_enriched")

            except Exception as exc:
                logger.warning(
                    "scraper: extracted_urls job %s — error processing %s: %s",
                    job_id,
                    url,
                    exc,
                )
                _increment_counter(job_id, "urls_failed")
                _record_url_error(job_id, url, f"error: {exc}")

    # Mark all source URLs as scraped in extracted_urls
    _mark_urls_scraped(work_list)

    _update_job(job_id, status="completed", completed_at=datetime.now(tz=UTC))
    logger.info("scraper: extracted_urls job %s completed", job_id)


#: Known URL shortener domains that should be resolved via HEAD before fetching.
_SHORTENER_DOMAINS: frozenset[str] = frozenset({
    "bit.ly", "bitly.com", "t.co", "tinyurl.com", "goo.gl", "ow.ly",
    "is.gd", "buff.ly", "amzn.to", "rebrand.ly", "shorturl.at",
    "cutt.ly", "rb.gy", "shorturl.me", "tiny.cc", "lnkd.in",
})


async def _resolve_shortener(
    client: httpx.AsyncClient,
    url: str,
) -> str:
    """Resolve URL shortener redirects via a HEAD request.

    If the URL's domain is a known shortener, sends a HEAD request to follow
    redirects and returns the final URL. Falls back to the original URL on
    any error so the main fetch can still attempt it.

    Args:
        client: Shared httpx client.
        url: Possibly-shortened URL.

    Returns:
        Resolved final URL, or the original URL if resolution fails.
    """
    try:
        from urllib.parse import urlparse

        domain = (urlparse(url).hostname or "").lower()
        if domain not in _SHORTENER_DOMAINS:
            return url

        response = await client.head(
            url,
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; IssueObservatory/1.0)"},
        )
        resolved = str(response.url)
        if resolved != url:
            logger.debug("scraper: resolved shortener %s -> %s", url, resolved)
        return resolved
    except Exception as exc:
        logger.debug("scraper: shortener resolution failed for %s: %s", url, exc)
        return url


def _mark_urls_scraped(urls: list[str]) -> None:
    """Set ``scraped = TRUE`` on extracted_urls rows matching the given URLs.

    Args:
        urls: List of cleaned URL strings to mark.
    """
    if not urls:
        return

    from issue_observatory.core.database import get_sync_session

    with get_sync_session() as db:
        for url in urls:
            db.execute(
                text(
                    "UPDATE extracted_urls SET scraped = TRUE WHERE url_cleaned = :url"
                ),
                {"url": url},
            )
        db.commit()


def _find_google_search_record(url: str) -> dict[str, Any] | None:
    """Check whether a URL exists as a ``google_search`` content record.

    Returns a minimal dict with ``id`` (text) and ``published_at`` so the
    caller can pass both to :func:`_update_content_record_v2` for partition-
    pruned UPDATE queries.

    Args:
        url: The URL to look up.

    Returns:
        ``{"id": str, "published_at": datetime | None}`` if a matching
        ``google_search`` record is found, otherwise ``None``.
    """
    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

    try:
        with get_sync_session() as session:
            row = session.execute(
                text(
                    """
                    SELECT id::text, published_at
                    FROM content_records
                    WHERE url = :url AND platform = 'google_search'
                    LIMIT 1
                    """
                ),
                {"url": url},
            ).fetchone()

            if row:
                return {"id": row[0], "published_at": row[1]}
    except Exception as exc:
        logger.warning(
            "scraper: failed to check google_search record for %s: %s", url, exc
        )

    return None


@celery_app.task(
    name="issue_observatory.scraper.tasks.scrape_extracted_urls_task",
    bind=True,
    acks_late=True,
    max_retries=0,
    soft_time_limit=7_200,
    time_limit=10_800,
)
def scrape_extracted_urls_task(self: Any, job_id: str) -> dict[str, Any]:
    """Scrape URLs from the extracted URLs pipeline.

    Handles three URL types:

    1. **Video platform URLs** (YouTube / TikTok) — downloaded via yt-dlp.
    2. **Google Search result URLs** — existing ``content_records`` rows are
       updated in-place with the scraped page body.
    3. **Other web URLs** — standard scraping pipeline: httpx fetch,
       optional Playwright fallback, trafilatura text extraction, new
       ``content_record`` inserted.

    Runs the async engine via ``asyncio.run()``.  No auto-retry because
    scraping is stateful; per-URL errors are handled internally.

    Args:
        job_id: UUID string of the ScrapingJob to execute.

    Returns:
        Dict with ``job_id`` and final ``status``.
    """
    logger.info("scraper: scrape_extracted_urls_task started for job=%s", job_id)
    try:
        asyncio.run(_run_extracted_url_scraping(job_id, self.request.id))
    except Exception as exc:
        logger.error(
            "scraper: scrape_extracted_urls_task failed for job=%s: %s", job_id, exc
        )
        _update_job(
            job_id,
            status="failed",
            error_message=str(exc),
            completed_at=datetime.now(tz=UTC),
        )
        raise

    return {"job_id": job_id, "status": "completed"}
