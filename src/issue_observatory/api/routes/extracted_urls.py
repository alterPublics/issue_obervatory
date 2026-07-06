"""API routes for the extracted URLs browser.

Provides aggregated URL data with filtering for the scraping page's
URL Browser tab. Supports both HTMX fragment responses (for the table)
and JSON API responses.

Routes:
    GET  /api/extracted-urls/        — aggregated URL list (HTMX or JSON)
    GET  /api/extracted-urls/stats   — summary statistics for current filter
    POST /api/extracted-urls/scrape  — create a scraping job from extracted URLs
"""

from __future__ import annotations

import uuid as _uuid_module
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.arenas.categories import ARENA_CATEGORIES
from issue_observatory.core.database import get_db
from issue_observatory.core.models.users import User
from issue_observatory.core.schemas.extracted_urls import (
    ExtractedUrlAggregated,
    ExtractedUrlFilterParams,
    ExtractedUrlStats,
    ScrapeFromUrlsRequest,
)

logger = structlog.get_logger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Domain constant sets (trusted internal data — safe to embed in SQL)
# ---------------------------------------------------------------------------

#: Social media domains excluded when ``exclude_social=True``.
_SOCIAL_DOMAINS: tuple[str, ...] = (
    "facebook.com",
    "fb.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "t.co",
    "tiktok.com",
    "vm.tiktok.com",
    "youtube.com",
    "youtu.be",
    "m.youtube.com",
    "reddit.com",
    "linkedin.com",
    "pinterest.com",
    "tumblr.com",
    "snapchat.com",
    "threads.net",
    "mastodon.social",
    "bsky.app",
    "gab.com",
    "vk.com",
    "telegram.org",
    "t.me",
    "discord.com",
    "discord.gg",
)

#: Video platform domain sets keyed by platform slug.
_VIDEO_DOMAINS: dict[str, tuple[str, ...]] = {
    "youtube": ("youtube.com", "youtu.be", "m.youtube.com"),
    "tiktok": ("tiktok.com", "vm.tiktok.com"),
}

# ---------------------------------------------------------------------------
# Sort-order mapping
# ---------------------------------------------------------------------------

_SORT_ORDER: dict[str, str] = {
    "count": "total_count DESC",
    "domain": "url_domain ASC",
    "first_seen": "first_seen DESC",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _domain_list_sql(domains: tuple[str, ...]) -> str:
    """Format a tuple of trusted domain strings as a SQL IN-list literal.

    The domains are internal constants (not user input), so direct embedding
    is safe and avoids the tuple-binding limitations of SQLAlchemy ``text()``.

    Args:
        domains: Tuple of domain strings to format.

    Returns:
        SQL fragment such as ``('facebook.com','twitter.com',...)``.
    """
    escaped = ", ".join(f"'{d}'" for d in domains)
    return f"({escaped})"


def _build_where_clauses(
    filters: ExtractedUrlFilterParams,
) -> tuple[str, dict[str, Any]]:
    """Build a SQL WHERE clause and bound parameters from filter state.

    Domain allow/block lists are embedded directly into the SQL string because
    they are hardcoded internal constants, not user-supplied values. All
    user-supplied identifiers (UUIDs, platform name, search term) are bound
    via parameterised placeholders to prevent injection.

    Args:
        filters: Validated filter parameters.

    Returns:
        A 2-tuple of ``(where_clause_string, params_dict)``.
    """
    clauses: list[str] = ["scraped = FALSE"]
    params: dict[str, Any] = {}

    if filters.project_id:
        clauses.append("project_id = CAST(:project_id AS uuid)")
        params["project_id"] = str(filters.project_id)

    if filters.query_design_id:
        clauses.append("query_design_id = CAST(:query_design_id AS uuid)")
        params["query_design_id"] = str(filters.query_design_id)

    if filters.platform:
        clauses.append("platform = :platform")
        params["platform"] = filters.platform

    if filters.category:
        # Resolve category to list of platform names (trusted internal data)
        category_platforms = [
            p for p, c in ARENA_CATEGORIES.items() if c == filters.category
        ]
        if category_platforms:
            clauses.append(
                f"platform IN {_domain_list_sql(tuple(category_platforms))}"
            )

    if filters.search_term:
        clauses.append(":search_term = ANY(search_terms_matched)")
        params["search_term"] = filters.search_term

    # Domain filter — embed trusted constants directly into SQL
    if filters.video_only == "youtube":
        clauses.append(f"url_domain IN {_domain_list_sql(_VIDEO_DOMAINS['youtube'])}")
    elif filters.video_only == "tiktok":
        clauses.append(f"url_domain IN {_domain_list_sql(_VIDEO_DOMAINS['tiktok'])}")
    elif filters.exclude_social:
        clauses.append(f"url_domain NOT IN {_domain_list_sql(_SOCIAL_DOMAINS)}")

    return (" AND ".join(clauses) if clauses else "TRUE"), params


def _parse_filters(
    project_id: str | None = None,
    query_design_id: str | None = None,
    search_term: str | None = None,
    platform: str | None = None,
    category: str | None = None,
    exclude_social: bool = True,
    video_only: str | None = None,
    sort_by: str = "count",
    page: int = 1,
    page_size: int = 50,
) -> ExtractedUrlFilterParams:
    """Parse raw query-parameter strings into a validated filter model.

    Args:
        project_id: Optional project UUID string.
        query_design_id: Optional query design UUID string.
        search_term: Optional search term to filter by.
        platform: Optional platform slug to filter by.
        exclude_social: Whether to exclude social media domains.
        video_only: Restrict to ``"youtube"`` or ``"tiktok"`` domains, or None.
        sort_by: Sort column slug (``"count"``, ``"domain"``, ``"first_seen"``).
        page: 1-based page number.
        page_size: Rows per page.

    Returns:
        Validated :class:`~issue_observatory.core.schemas.extracted_urls.ExtractedUrlFilterParams`.
    """
    return ExtractedUrlFilterParams(
        project_id=_uuid_module.UUID(project_id) if project_id else None,
        query_design_id=_uuid_module.UUID(query_design_id) if query_design_id else None,
        search_term=search_term or None,
        platform=platform or None,
        category=category or None,
        exclude_social=exclude_social,
        video_only=video_only or None,
        sort_by=sort_by,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/search-terms")
async def suggest_search_terms(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    q: str = Query("", min_length=0),
    project_id: str | None = Query(None),
) -> JSONResponse:
    """Return distinct search terms matching the query prefix.

    Sourced from ``content_records.search_terms_matched`` since that column
    is authoritative.  Results are filtered by project when provided.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        q: Prefix to match against (case-insensitive).
        project_id: Optional project UUID to scope results.

    Returns:
        JSON list of matching term strings (max 20).
    """
    clauses = ["cr.search_terms_matched IS NOT NULL"]
    params: dict[str, Any] = {}

    if project_id:
        clauses.append(
            "crun.query_design_id IN ("
            "  SELECT id FROM query_designs WHERE project_id = CAST(:project_id AS uuid)"
            ")"
        )
        params["project_id"] = project_id

    where = " AND ".join(clauses)

    if q:
        sql = f"""
            SELECT DISTINCT term FROM (
                SELECT unnest(cr.search_terms_matched) AS term
                FROM content_records cr
                LEFT JOIN collection_runs crun ON cr.collection_run_id = crun.id
                WHERE {where}
            ) sub
            WHERE term ILIKE :prefix
            ORDER BY term
            LIMIT 20
        """
        params["prefix"] = f"{q}%"
    else:
        sql = f"""
            SELECT DISTINCT term FROM (
                SELECT unnest(cr.search_terms_matched) AS term
                FROM content_records cr
                LEFT JOIN collection_runs crun ON cr.collection_run_id = crun.id
                WHERE {where}
            ) sub
            ORDER BY term
            LIMIT 20
        """

    result = await db.execute(text(sql), params)
    terms = [row[0] for row in result]
    return JSONResponse(terms)


@router.get("/", response_model=None)
async def list_extracted_urls(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    project_id: str | None = Query(None),
    query_design_id: str | None = Query(None),
    search_term: str | None = Query(None),
    platform: str | None = Query(None),
    category: str | None = Query(None),
    exclude_social: bool = Query(True),
    video_only: str | None = Query(None),
    sort_by: str = Query("count"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=5000),
) -> HTMLResponse | JSONResponse:
    """Return aggregated extracted URLs with filtering and pagination.

    Returns an HTMX HTML fragment when the ``HX-Request`` header is present,
    or a JSON array of
    :class:`~issue_observatory.core.schemas.extracted_urls.ExtractedUrlAggregated`
    objects otherwise.
    """
    filters = _parse_filters(
        project_id=project_id,
        query_design_id=query_design_id,
        search_term=search_term,
        platform=platform,
        category=category,
        exclude_social=exclude_social,
        video_only=video_only,
        sort_by=sort_by,
        page=page,
        page_size=page_size,
    )

    where, params = _build_where_clauses(filters)
    offset = (filters.page - 1) * filters.page_size
    order_by = _SORT_ORDER.get(filters.sort_by, "total_count DESC")

    query_sql = f"""
        SELECT url_cleaned, url_domain,
               COUNT(*) AS total_count,
               COUNT(DISTINCT platform) AS platform_count,
               ARRAY_AGG(DISTINCT platform) AS platforms_list,
               MIN(extracted_at) AS first_seen
        FROM extracted_urls
        WHERE {where}
        GROUP BY url_cleaned, url_domain
        ORDER BY {order_by}
        LIMIT :limit OFFSET :offset
    """
    params["limit"] = filters.page_size
    params["offset"] = offset

    result = await db.execute(text(query_sql), params)
    rows = [dict(row._mapping) for row in result]

    logger.debug(
        "extracted_urls_listed",
        user_id=str(current_user.id),
        row_count=len(rows),
        page=filters.page,
    )

    if request.headers.get("HX-Request"):
        templates = request.app.state.templates
        return templates.TemplateResponse(
            "scraping/_url_table.html",
            {
                "request": request,
                "urls": rows,
                "page": filters.page,
                "page_size": filters.page_size,
                "has_more": len(rows) == filters.page_size,
            },
        )

    return JSONResponse(
        [ExtractedUrlAggregated(**row).model_dump(mode="json") for row in rows]
    )


@router.get("/stats")
async def get_extracted_url_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    project_id: str | None = Query(None),
    query_design_id: str | None = Query(None),
    search_term: str | None = Query(None),
    platform: str | None = Query(None),
    category: str | None = Query(None),
    exclude_social: bool = Query(True),
    video_only: str | None = Query(None),
) -> JSONResponse:
    """Return summary statistics for the current URL filter."""
    filters = _parse_filters(
        project_id=project_id,
        query_design_id=query_design_id,
        search_term=search_term,
        platform=platform,
        category=category,
        exclude_social=exclude_social,
        video_only=video_only,
    )

    where, params = _build_where_clauses(filters)

    stats_sql = f"""
        SELECT COUNT(DISTINCT url_cleaned) AS total_unique_urls,
               COUNT(*) AS total_appearances,
               COUNT(DISTINCT url_domain) AS unique_domains
        FROM extracted_urls
        WHERE {where}
    """
    result = await db.execute(text(stats_sql), params)
    row = result.mappings().first()

    stats = ExtractedUrlStats(
        total_unique_urls=row["total_unique_urls"] if row else 0,
        total_appearances=row["total_appearances"] if row else 0,
        unique_domains=row["unique_domains"] if row else 0,
    )
    return JSONResponse(stats.model_dump())


@router.post("/scrape")
async def scrape_extracted_urls(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    body: ScrapeFromUrlsRequest,
) -> JSONResponse:
    """Create a scraping job sourced from the extracted URLs table.

    The URL list is resolved from ``body.selected_urls`` if provided, otherwise
    derived dynamically from ``body.url_filter_criteria`` via a DB query.
    A :class:`~issue_observatory.core.models.scraping.ScrapingJob` row is
    inserted in ``"pending"`` status and the Celery task is dispatched.

    Args:
        request: The incoming HTTP request.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        body: Validated
            :class:`~issue_observatory.core.schemas.extracted_urls.ScrapeFromUrlsRequest`.

    Returns:
        JSON ``{"job_id": "...", "total_urls": N}`` with HTTP 201.

    Raises:
        JSONResponse 400: If neither ``selected_urls`` nor ``url_filter_criteria``
            is provided, or if the filter produces an empty URL set.
    """
    from issue_observatory.core.models.scraping import ScrapingJob

    # Resolve source URL list
    if body.selected_urls:
        source_urls = body.selected_urls
    elif body.url_filter_criteria:
        where, params = _build_where_clauses(body.url_filter_criteria)
        url_sql = f"SELECT DISTINCT url_cleaned FROM extracted_urls WHERE {where}"
        result = await db.execute(text(url_sql), params)
        source_urls = [row[0] for row in result]
    else:
        return JSONResponse(
            {"detail": "Either selected_urls or url_filter_criteria required"},
            status_code=400,
        )

    if not source_urls:
        return JSONResponse(
            {"detail": "No URLs match the filter"},
            status_code=400,
        )

    # Filter out URLs already scraped
    already_scraped_result = await db.execute(
        text("""
            SELECT DISTINCT url FROM content_records
            WHERE platform IN ('url_scraper', 'domain_crawler')
              AND url = ANY(CAST(:urls AS text[]))
        """),
        {"urls": source_urls},
    )
    already_scraped: set[str] = {row[0] for row in already_scraped_result}

    if already_scraped:
        source_urls = [u for u in source_urls if u not in already_scraped]
        logger.info(
            "filtered_already_scraped_urls",
            skipped=len(already_scraped),
            remaining=len(source_urls),
        )

    if not source_urls:
        return JSONResponse(
            {
                "detail": f"All {len(already_scraped)} URL(s) have already been scraped.",
            },
            status_code=400,
        )

    job = ScrapingJob(
        created_by=current_user.id,
        source_type="extracted_urls",
        source_urls=source_urls,
        url_filter_criteria=(
            body.url_filter_criteria.model_dump(mode="json")
            if body.url_filter_criteria
            else None
        ),
        delay_min=body.delay_min,
        delay_max=body.delay_max,
        timeout_seconds=body.timeout_seconds,
        respect_robots_txt=body.respect_robots_txt,
        use_playwright_fallback=body.use_playwright_fallback,
        total_urls=len(source_urls),
        status="pending",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    from issue_observatory.scraper.tasks import scrape_extracted_urls_task

    scrape_extracted_urls_task.apply_async(
        kwargs={"job_id": str(job.id)},
        queue="celery",
    )

    logger.info(
        "scraping_job_created_from_extracted_urls",
        job_id=str(job.id),
        total_urls=len(source_urls),
        user_id=str(current_user.id),
    )

    response_data: dict[str, Any] = {
        "job_id": str(job.id),
        "total_urls": len(source_urls),
    }
    if already_scraped:
        response_data["skipped_already_scraped"] = len(already_scraped)

    return JSONResponse(response_data, status_code=201)
