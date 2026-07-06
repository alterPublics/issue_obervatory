"""Content browser and export routes.

Provides a read-only API for browsing and exporting collected content records
stored in the universal ``content_records`` table.

Results are always filtered to the current user's own collection runs.
Records from shared or public query designs are not exposed here unless
the current user's run collected them.

Routes:
    GET /content/              — HTML: render content/browser.html (full page)
    GET /content/records       — HTML fragment: HTMX cursor-paginated tbody rows
    GET /content/{id}          — HTML: record detail panel or standalone page

    GET  /content/export                    — synchronous export (up to 10 K records)
    POST /content/export/async              — async export via Celery (unlimited records)
    GET  /content/export/{job_id}/status    — poll Celery export job status from Redis
    GET  /content/export/{job_id}/download  — redirect to MinIO pre-signed download URL

    GET  /content/discovered-links          — GR-22: mine cross-platform links from corpus
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import exists, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.analysis.export import ContentExporter
from issue_observatory.analysis.network import (
    build_bipartite_network,
    get_actor_co_occurrence,
    get_term_co_occurrence,
)
from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.arenas.categories import ARENA_CATEGORIES, ARENA_CATEGORY_LABELS
from issue_observatory.core.database import get_db
from issue_observatory.core.models.actors import Actor
from issue_observatory.core.models.collection import CollectionRun
from issue_observatory.core.models.content import UniversalContentRecord
from issue_observatory.core.models.content_links import ContentRecordLink
from issue_observatory.core.models.query_design import QueryDesign
from issue_observatory.core.models.users import User
from issue_observatory.core.queries.content_filters import (
    ContentFilterSpec,
    _run_id_filter_sa,
    build_count_stmt,
    resolve_dashboard_query_design_ids,
)
from issue_observatory.core.queries.content_filters import (
    build_browse_stmt as _cf_build_browse_stmt,
)

logger = structlog.get_logger(__name__)

router = APIRouter()

_MAX_LIMIT = 200
_EXPORT_SYNC_LIMIT = 10_000

# ---------------------------------------------------------------------------
# Filter validation constants (Task 2 / Phase 6)
# ---------------------------------------------------------------------------

_VALID_MODES: frozenset[str] = frozenset({"batch", "live"})
_VALID_SCRAPE_STATUSES: frozenset[str] = frozenset({"pending", "scraped", "failed"})
_VALID_LANGUAGES: frozenset[str] = frozenset({"da", "en", "de", "kl", "sv", "no", "ru", "fr"})


def _validate_enum_filter(
    value: str | None,
    allowed: frozenset[str],
    field_name: str,
    warnings: list[str],
) -> str | None:
    """Return value if valid, None if invalid — appending a warning message."""
    if value and value not in allowed:
        warnings.append(
            f"Unknown value for {field_name}: \u2018{value}\u2019. "
            f"Allowed: {', '.join(sorted(allowed))}."
        )
        return None
    return value


def _validate_date_filter(
    raw: str | None,
    field_name: str,
    warnings: list[str],
    *,
    end_of_day: bool = False,
) -> datetime | None:
    """Parse a date param, recording a warning on parse failure."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw).replace(tzinfo=UTC)
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
        return dt
    except ValueError:
        warnings.append(
            f"Could not parse {field_name}: \u2018{raw}\u2019. "
            "Expected format: YYYY-MM-DD. Filter has been ignored."
        )
        return None


def _run_id_filter(ucr_col: Any, published_col: Any, id_col: Any, run_id: Any) -> Any:
    """Build a filter clause that matches records directly collected in a run
    OR linked to it via ``content_record_links``.

    Mirrors the EXISTS pattern used in ``analysis/_filters.py`` so that the
    content browser and analysis dashboard show the same records.
    """
    return or_(
        ucr_col == run_id,
        exists(
            select(ContentRecordLink.id).where(
                ContentRecordLink.collection_run_id == run_id,
                ContentRecordLink.content_record_id == id_col,
                ContentRecordLink.content_record_published_at == published_col,
            )
        ),
    )

# ---------------------------------------------------------------------------
# Content negotiation helper
# ---------------------------------------------------------------------------


def _prefers_json(request: Request, format_param: str | None) -> bool:
    """Return True when the client explicitly prefers JSON over HTML.

    Checks both the ``format`` query parameter and the ``Accept`` header.
    HTMX requests always get HTML.  Only programmatic API callers sending
    ``Accept: application/json`` without ``text/html`` are routed to JSON.

    Args:
        request: The incoming HTTP request.
        format_param: The ``format`` query parameter value, if provided.

    Returns:
        ``True`` if JSON response is preferred, ``False`` for HTML.
    """
    # Explicit format parameter takes precedence
    if format_param == "json":
        return True

    # HTMX requests always get HTML
    if request.headers.get("hx-request"):
        return False

    # Check Accept header
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return False
    return "application/json" in accept


# ---------------------------------------------------------------------------
# Content-Type headers per export format
# ---------------------------------------------------------------------------

_EXPORT_CONTENT_TYPES: dict[str, str] = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "json": "application/x-ndjson",
    "parquet": "application/octet-stream",
    "gexf": "application/xml",
    "ris": "application/x-research-info-systems",
    "bibtex": "application/x-bibtex",
}

_EXPORT_EXTENSIONS: dict[str, str] = {
    "csv": "csv",
    "xlsx": "xlsx",
    "json": "ndjson",
    "parquet": "parquet",
    "gexf": "gexf",
    "ris": "ris",
    "bibtex": "bib",
}


# ---------------------------------------------------------------------------
# UUID parameter helper
# ---------------------------------------------------------------------------


def _parse_uuid(value: str | None) -> uuid.UUID | None:
    """Parse an optional string as UUID, treating empty/whitespace as None.

    HTMX form serialization sends empty strings for ``<select>`` elements with
    ``<option value="">``.  FastAPI's ``Optional[uuid.UUID]`` rejects empty
    strings with HTTP 422.  This helper provides a safe fallback.
    """
    if not value or not value.strip():
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Shared filter helper
# ---------------------------------------------------------------------------


# _build_content_stmt deleted in Phase 2 (Task 2). Export now uses
# ContentFilterSpec.from_export_route + build_browse_stmt directly.


def _record_to_dict(record: UniversalContentRecord) -> dict[str, Any]:
    """Convert an ORM row to a plain dict suitable for the ``ContentExporter``.

    Args:
        record: An ORM instance of ``UniversalContentRecord``.

    Returns:
        Dict with string keys matching ORM column names.  Includes derived
        columns (``links``, ``search_rank``, ``arena_category``) needed by
        the exporter.
    """
    raw_meta = record.raw_metadata or {}

    # Extract cleaned external links from URL enrichment
    url_enrichment = (raw_meta.get("enrichments") or {}).get("url_extraction") or {}
    url_entries = url_enrichment.get("urls") or []
    cleaned_links = [
        u["cleaned"] for u in url_entries
        if u.get("cleaned") and u.get("type") != "self_reference"
    ]
    links_str = "; ".join(cleaned_links) if cleaned_links else ""

    # Search rank (Google Search position)
    search_rank = raw_meta.get("position")

    # Arena category
    arena_category = ARENA_CATEGORY_LABELS.get(
        ARENA_CATEGORIES.get(record.platform or "", ""), ""
    )

    # Language: prefer top-level field, fall back to enrichment detection
    language = record.language
    if not language:
        lang_enrichment = (raw_meta.get("enrichments") or {}).get("language_detection") or {}
        language = lang_enrichment.get("language")

    return {
        "id": record.id,
        "platform": record.platform,
        "arena": record.arena,
        "arena_category": arena_category,
        "content_type": record.content_type,
        "title": record.title,
        "text_content": record.text_content,
        "url": record.url,
        "links": links_str,
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
        "language": language,
        "search_terms_matched": record.search_terms_matched,
        "search_rank": int(search_rank) if search_rank is not None else None,
        "raw_metadata": record.raw_metadata,
        "content_hash": record.content_hash,
        "scrape_status": record.scrape_status,
        "term_matched": record.term_matched,
    }


# ---------------------------------------------------------------------------
# Cursor helpers
# ---------------------------------------------------------------------------


def _encode_cursor(published_at: datetime | None, record_id: uuid.UUID) -> str:
    """Encode a keyset cursor as a URL-safe string.

    Format: ``{published_at_iso}|{record_id_hex}``.  When ``published_at`` is
    None we use the sentinel string ``"null"``.

    Args:
        published_at: The ``published_at`` timestamp of the last returned row.
        record_id: The UUID of the last returned row.

    Returns:
        A ``|``-separated string suitable for inclusion in a query parameter.
    """
    ts = published_at.isoformat() if published_at is not None else "null"
    return f"{ts}|{record_id}"


def _decode_cursor(cursor: str) -> tuple[datetime | None, uuid.UUID | None]:
    """Decode a keyset cursor produced by ``_encode_cursor``.

    Args:
        cursor: The raw cursor string from the query parameter.

    Returns:
        A tuple of ``(published_at, record_id)``.  Either may be ``None`` if
        the cursor is malformed or uses the ``"null"`` sentinel.
    """
    try:
        ts_part, id_part = cursor.rsplit("|", 1)
        pub = None if ts_part == "null" else datetime.fromisoformat(ts_part)
        rid = uuid.UUID(id_part)
        return pub, rid
    except (ValueError, AttributeError):
        return None, None


def _parse_date_param(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    """Parse a YYYY-MM-DD date string into a timezone-aware ``datetime``.

    Returns ``None`` if the value is missing or cannot be parsed.

    Args:
        value: A date string in ISO format (e.g. ``"2024-01-15"``).
        end_of_day: If True, set time to 23:59:59 instead of 00:00:00.
            Use for upper-bound (date_to) parameters so that "2026-02-26"
            includes all records published on that day.

    Returns:
        A UTC ``datetime`` or ``None``.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value).replace(tzinfo=UTC)
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
        return dt
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Browse query builder (keyset pagination with full-text search)
# ---------------------------------------------------------------------------


def _build_browse_stmt(
    current_user: User,
    q: str | None,
    platform: str | None,
    arena: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    language: str | None,
    search_term: str | None,
    run_id: uuid.UUID | None,
    mode: str | None,
    cursor_published_at: datetime | None,
    cursor_id: uuid.UUID | None,
    limit: int,
    project_id: uuid.UUID | None = None,
    show_all: bool = False,
    scrape_status: str | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
    page_offset: int = 0,
    content_types: list[str] | None = None,
) -> Any:
    """Thin delegator to the shared filter helper (Phase 1a).

    Full logic now lives in ``core/queries/content_filters.build_browse_stmt``.
    This function signature is kept for backward compatibility with the call
    sites in this module until Phase 2 inlines the helper directly.
    """
    # Delegate to the shared filter helper.  The spec carries all filter
    # fields already resolved (including effective_show_all and
    # effective_content_types from the caller).
    spec = ContentFilterSpec(
        q=q,
        platform=platform,
        arena=arena,
        date_from=date_from,
        date_to=date_to,
        language=language,
        search_term=search_term,
        run_id=run_id,
        mode=mode,
        project_id=project_id,
        show_all=show_all,
        content_types=content_types,
        scrape_status=scrape_status,
        current_user=current_user,
        ownership_mode="admin" if current_user.role == "admin" else "owner_only",
        cursor_published_at=cursor_published_at,
        cursor_id=cursor_id,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page_offset=page_offset,
        limit=limit,
        # arenas_list not passed here — multi-arena IN is applied post-hoc
        # by the caller (same as before).
    )
    return _cf_build_browse_stmt(spec)


async def _fetch_recent_runs(
    db: AsyncSession,
    current_user: User,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return recent collection runs for the browser sidebar selector.

    Args:
        db: Async database session.
        current_user: Authenticated user — scopes to their own runs unless admin.
        limit: Maximum number of runs to return.

    Returns:
        A list of dicts with keys ``id``, ``status``, ``query_design_name``,
        ``created_at``, ``formatted_date``, ``records_collected``.
    """
    from sqlalchemy.orm import selectinload

    if current_user.role == "admin":
        stmt = (
            select(CollectionRun)
            .options(selectinload(CollectionRun.query_design))
            .order_by(CollectionRun.started_at.desc().nulls_last())
            .limit(limit)
        )
    else:
        stmt = (
            select(CollectionRun)
            .options(selectinload(CollectionRun.query_design))
            .where(CollectionRun.initiated_by == current_user.id)
            .order_by(CollectionRun.started_at.desc().nulls_last())
            .limit(limit)
        )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    # Fetch record counts for all runs in a single query
    run_ids = [r.id for r in rows]
    if run_ids:
        count_stmt = (
            select(
                UniversalContentRecord.collection_run_id,
                func.count(UniversalContentRecord.id).label("count")
            )
            .where(UniversalContentRecord.collection_run_id.in_(run_ids))
            .group_by(UniversalContentRecord.collection_run_id)
        )
        count_result = await db.execute(count_stmt)
        record_counts = {row[0]: row[1] for row in count_result.fetchall()}
    else:
        record_counts = {}

    def format_date(dt: datetime | None) -> str:
        """Format datetime as '15 Feb 2026' style."""
        if not dt:
            return ""
        return dt.strftime("%d %b %Y")

    return [
        {
            "id": str(r.id),
            "status": r.status,
            "query_design_name": r.query_design.name if r.query_design else "Untitled",
            "created_at": r.started_at.isoformat() if r.started_at else "",
            "formatted_date": format_date(r.started_at),
            "records_collected": record_counts.get(r.id, 0),
        }
        for r in rows
    ]


async def _count_matching(
    db: AsyncSession,
    spec: ContentFilterSpec,
) -> int:
    """Count records matching a ``ContentFilterSpec``.

    Phase 2: accepts the spec directly so browse and count always use the
    same filter parameters (Task 3 — eliminates count/row divergence).

    Args:
        db: Async database session.
        spec: The shared filter spec built by the browse/records route.

    Returns:
        Integer count of matching records.
    """
    count_stmt = build_count_stmt(spec)
    result = await db.execute(count_stmt)
    return result.scalar_one() or 0


# ---------------------------------------------------------------------------
# Template context helpers
# ---------------------------------------------------------------------------


def _orm_row_to_template_dict(row: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy mapping row or ORM instance to a template-safe dict.

    Args:
        row: A SQLAlchemy ``RowMapping`` (from ``.mappings()``) or an ORM instance.

    Returns:
        Dict with string keys matching what the browser and detail templates
        expect.
    """
    # Supports both RowMapping (dict-like) and ORM instances.
    def _get(key: str) -> Any:
        try:
            return row[key]
        except (TypeError, KeyError):
            return getattr(row, key, None)

    pub = _get("published_at")
    col = _get("collected_at")
    terms = _get("search_terms_matched") or []

    # SB-13: Extract mode from the joined collection_runs table
    mode = _get("mode") or _get("_browse_mode") or ""

    # A2: Use resolved actor name when available
    resolved_name = _get("_resolved_name")
    author = resolved_name or _get("author_display_name") or ""

    metadata = _get("raw_metadata") or {}
    return {
        "id": str(_get("id") or ""),
        "platform": _get("platform") or "",
        "arena": _get("arena") or "",
        "content_type": _get("content_type") or "",
        "title": _get("title") or "",
        "text": _get("text_content") or "",
        "author": author,
        "author_resolved": bool(resolved_name),
        "author_id": str(_get("author_platform_id") or ""),
        "url": _get("url") or "",
        "published_at": pub.isoformat() if pub else "",
        "collected_at": col.isoformat() if col else "",
        "language": _get("language") or "",
        "engagement_score": _get("engagement_score") or 0,
        "search_terms_matched": terms if isinstance(terms, list) else [],
        "run_id": str(_get("collection_run_id") or ""),
        "metadata": metadata,
        "mode": mode,
        "scrape_status": _get("scrape_status") or "",
        "term_matched": _get("term_matched") if _get("term_matched") is not None else True,
        "actual_poster_name": metadata.get("actual_poster_name", ""),
    }


def _orm_to_detail_dict(
    record: UniversalContentRecord,
    resolved_name: str | None = None,
) -> dict[str, Any]:
    """Convert an ORM ``UniversalContentRecord`` to the detail template context dict.

    Args:
        record: An ORM instance loaded from the database.
        resolved_name: Optional canonical actor name from a LEFT JOIN with actors.

    Returns:
        Dict with keys expected by ``content/record_detail.html``.
    """
    pub = record.published_at
    col = record.collected_at
    terms = record.search_terms_matched or []

    # A2: Prefer resolved actor name over raw display name
    author = resolved_name or record.author_display_name or ""

    metadata = record.raw_metadata or {}
    return {
        "id": str(record.id),
        "platform": record.platform or "",
        "arena": record.arena or "",
        "content_type": record.content_type or "",
        "title": record.title or "",
        "text": record.text_content or "",
        "author": author,
        "author_resolved": bool(resolved_name),
        "author_id": str(record.author_platform_id or ""),
        "url": record.url or "",
        "published_at": pub.isoformat() if pub else "",
        "collected_at": col.isoformat() if col else "",
        "language": record.language or "",
        "engagement_score": record.engagement_score or 0,
        "search_terms_matched": terms if isinstance(terms, list) else [],
        "run_id": str(record.collection_run_id or ""),
        "metadata": metadata,
        "scrape_status": record.scrape_status or "",
        "term_matched": record.term_matched if record.term_matched is not None else True,
        "actual_poster_name": metadata.get("actual_poster_name", ""),
    }


# ---------------------------------------------------------------------------
# Record count (dashboard widget)
# ---------------------------------------------------------------------------


@router.get("/count")
async def content_record_count(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    run_id: str | None = Query(default=None, description="Filter by specific collection run UUID."),
    project_id: str | None = Query(
        default=None, description="Filter by project UUID (scopes via query designs)."
    ),
) -> dict[str, int]:
    """Return content record counts for the current user's collection runs.

    Used by the dashboard Records Collected card.  Returns both a
    ``matched`` count (records where ``term_matched = TRUE``, consistent
    with the analysis layer) and a ``total`` count of all collected records.

    Scopes via query_design_id (using idx_content_query) rather than joining
    through collection_runs, which avoids full partition scans on the
    content_records table.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        run_id: Optional collection run UUID filter.
        project_id: Optional project UUID filter (scopes via query_design_id).

    Returns:
        Dict with ``matched`` and ``total`` keys.
    """
    run_id_parsed = _parse_uuid(run_id)
    project_uuid = _parse_uuid(project_id)

    # Build a spec for query-design scoping (preserves partition-pruning path).
    spec_base = ContentFilterSpec.from_dashboard_count(
        current_user=current_user,
        run_id=run_id_parsed,
        project_id=project_uuid,
    )

    # Resolve query_design_ids using the shared helper.
    qd_ids = await resolve_dashboard_query_design_ids(db, spec_base)

    if not qd_ids:
        return {"matched": 0, "total": 0}

    # Re-build spec with resolved query_design_ids so build_count_stmt can
    # use the short-circuit optimization path.
    spec = ContentFilterSpec.from_dashboard_count(
        current_user=current_user,
        run_id=run_id_parsed,
        project_id=project_uuid,
        query_design_ids=qd_ids,
    )

    # Total count: uses query_design_id IN (...) short-circuit path.
    total_stmt = build_count_stmt(spec)

    # Matched count: build directly (same base, plus term_matched=TRUE).
    # build_count_stmt's short-circuit path produces:
    #   SELECT count() WHERE query_design_id IN (...) [+ optional run_id EXISTS]
    # We replicate that here with term_matched=TRUE added.
    ucr = UniversalContentRecord
    base_matched = (
        select(func.count())
        .select_from(ucr)
        .where(ucr.query_design_id.in_(qd_ids))
        .where(ucr.term_matched.is_(True))
    )
    if run_id_parsed is not None:
        base_matched = base_matched.where(
            _run_id_filter_sa(
                ucr.collection_run_id,
                ucr.published_at,
                ucr.id,
                run_id_parsed,
            )
        )

    matched_result, total_result = await db.execute(base_matched), await db.execute(total_stmt)
    return {
        "matched": matched_result.scalar() or 0,
        "total": total_result.scalar() or 0,
    }


# ---------------------------------------------------------------------------
# Browse page (HTML full page)
# ---------------------------------------------------------------------------

_BROWSE_LIMIT = 50
_BROWSE_CAP = 2000


@router.get("/")
async def content_browser_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    q: str | None = Query(default=None, description="Full-text search query."),
    arenas: list[str] | None = Query(default=None, description="Multi-value platform filter from checkboxes."),
    platform: str | None = Query(default=None),
    arena: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    language: str | None = Query(default=None),
    search_term: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    mode: str | None = Query(default=None, description="Collection mode filter: 'batch' or 'live'."),
    query_design_id: str | None = Query(default=None, description="Filter by query design UUID."),
    project_id: str | None = Query(default=None, description="Filter content to a specific project."),
    actor_id: list[str] | None = Query(default=None, description="Filter by actor UUID(s)."),
    show_all: bool = Query(default=False, description="Show all content including non-term-matched records."),
    show_duplicates: bool = Query(default=False, description="Include duplicate records (excluded by default, decision F)."),
    scrape_status_filter: str | None = Query(default=None, alias="scrape_status", description="Filter by scrape status: pending, scraped, failed."),
    sort_by: str | None = Query(default=None, description="Column to sort by."),
    sort_dir: str | None = Query(default=None, description="Sort direction: asc or desc."),
    content_types: list[str] | None = Query(default=None, description="Content type filter."),
    reset: bool = Query(default=False, description="When true, clear all auto-applied defaults (project auto-select, language default)."),
    limit: int = Query(
        default=_BROWSE_LIMIT,
        ge=10,
        le=500,
        description="Results per page (10–500). Visible as 25/50/100/200/500 in the sidebar.",
    ),
) -> Response:
    """Render the full content browser HTML page.

    Fetches the first page of matching records and passes them, along with
    filter context and a list of recent collection runs for the sidebar
    selector, to the ``content/browser.html`` Jinja2 template.

    Args:
        request: The incoming HTTP request (required by Jinja2 templates).
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        q: Optional full-text search string (Danish tsvector).
        platform: Optional platform filter.
        arena: Optional arena filter.
        date_from: Optional lower date bound (YYYY-MM-DD string from form).
        date_to: Optional upper date bound (YYYY-MM-DD string from form).
        language: Optional ISO 639-1 language code.
        search_term: Optional filter on ``search_terms_matched`` array.
        run_id: Optional collection run UUID filter (accepts empty string).
        project_id: Optional project UUID filter (accepts empty string).
        show_all: If True, include non-term-matched records (default: False).
        scrape_status_filter: Filter by scrape status (pending/scraped/failed).
        sort_by: Column to sort by (published_at, platform, author, arena, engagement_score).
        sort_dir: Sort direction (asc or desc).
        content_types: Optional list of content types to include.

    Returns:
        ``TemplateResponse`` rendering ``content/browser.html``.
    """
    run_id = _parse_uuid(run_id)  # type: ignore[assignment]
    query_design_id = _parse_uuid(query_design_id)  # type: ignore[assignment]
    # Track whether project_id was explicitly passed (even as empty string)
    # so we can distinguish "absent" (auto-select default) from "empty" (show all).
    project_id_was_explicit = project_id is not None
    project_id = _parse_uuid(project_id)  # type: ignore[assignment]

    # Parse actor_id list (multi-value query param, coerce empty strings).
    actor_ids: list[uuid.UUID] = [
        _id for raw in (actor_id or [])
        if ((_id := _parse_uuid(raw)) is not None)
    ]

    # Sentinel: content_types was explicitly submitted when the parameter appears
    # in the query string at all (even as an empty list).
    content_types_was_explicit = "content_types" in request.query_params

    # Sentinel: language was explicitly submitted (empty string = "all languages").
    language_was_explicit = "language" in request.query_params

    templates = request.app.state.templates

    if templates is None:
        raise HTTPException(status_code=500, detail="Template engine not initialised.")

    # Phase 6 — Task 2: Validation.  Collect warnings; invalid values are dropped
    # so the query still executes with the remaining valid filters.
    filter_warnings: list[str] = []
    date_from_dt = _validate_date_filter(date_from, "date_from", filter_warnings)
    date_to_dt = _validate_date_filter(date_to, "date_to", filter_warnings, end_of_day=True)
    mode = _validate_enum_filter(mode, _VALID_MODES, "mode", filter_warnings)
    scrape_status_filter = _validate_enum_filter(
        scrape_status_filter, _VALID_SCRAPE_STATUSES, "scrape_status", filter_warnings
    )
    if language_was_explicit and language:
        language = _validate_enum_filter(language, _VALID_LANGUAGES, "language", filter_warnings)

    # Task 5 (Phase 3): ?reset=true bypasses auto-project and auto-language defaults.
    # "Reset" is about clearing the user's active filter state (e.g. clearing the
    # auto-selected project). The posts-only content_types default still applies after
    # reset because that is a product-level default, not a user-chosen filter
    # (see decision B — the filter pill will show it and the user can clear it).
    if not reset:
        # Auto-select the project with the most recent collection data when no
        # project_id was explicitly provided in the URL.
        if not project_id_was_explicit and project_id is None:
            latest_project_stmt = (
                select(CollectionRun.project_id)
                .where(CollectionRun.initiated_by == current_user.id)
                .where(CollectionRun.project_id.isnot(None))
                .order_by(CollectionRun.started_at.desc().nulls_last())
                .limit(1)
            )
            latest_pid = (await db.execute(latest_project_stmt)).scalar_one_or_none()
            if latest_pid:
                project_id = latest_pid  # type: ignore[assignment]

        # Auto-set language default from the project's query design only when language
        # was NOT explicitly provided in the query string (sentinel pattern — Task 5).
        if not language_was_explicit and not language and project_id:
            lang_result = await db.execute(
                select(QueryDesign.language)
                .where(QueryDesign.project_id == project_id)
                .limit(1)
            )
            default_lang = lang_result.scalar_one_or_none()
            if default_lang:
                language = default_lang

    # Handle arenas multi-value filter — folded into spec.arenas_list (Task 7).
    arenas_list: list[str] = arenas or []
    # When a single arena is checked, also set platform_filter for the spec.
    platform_filter: str | None = platform
    if len(arenas_list) == 1:
        platform_filter = arenas_list[0]

    # Fetch query designs for the sidebar selector, scoped to the selected project.
    user_query_designs: list[dict[str, Any]] = []
    qd_scope_stmt = (
        select(QueryDesign)
        .join(CollectionRun, CollectionRun.query_design_id == QueryDesign.id, isouter=True)
        .where(CollectionRun.initiated_by == current_user.id)
        .distinct()
        .order_by(QueryDesign.name)
    )
    if project_id:
        qd_scope_stmt = qd_scope_stmt.where(QueryDesign.project_id == project_id)
    qd_result = await db.execute(qd_scope_stmt)
    user_query_designs = [
        {"id": str(qd.id), "name": qd.name}
        for qd in qd_result.scalars().all()
    ]

    # Build ONE spec used by BOTH the browse query and the count query (Task 3).
    spec = ContentFilterSpec.from_browse_route(
        current_user=current_user,
        q=q,
        platform=platform_filter if len(arenas_list) <= 1 else None,
        arena=arena,
        arenas_list=arenas_list,
        date_from=date_from_dt,
        date_to=date_to_dt,
        language=language,
        language_was_explicit=language_was_explicit,
        search_term=search_term,
        run_id=run_id,
        mode=mode,
        project_id=project_id,
        query_design_id=query_design_id,
        show_all=show_all,
        scrape_status=scrape_status_filter,
        content_types=content_types,
        content_types_was_explicit=content_types_was_explicit,
        include_duplicates=show_duplicates,
        actor_ids=actor_ids,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
    )

    stmt = _cf_build_browse_stmt(spec)
    result = await db.execute(stmt)
    raw_rows = list(result.mappings().all())

    # Unpack the ORM instance + mode from the JOIN mapping.
    records: list[dict[str, Any]] = []
    for rrow in raw_rows:
        ucr_obj = rrow.get("UniversalContentRecord")
        if ucr_obj is None:
            continue
        # Attach mode from the joined CollectionRun so the template can show it.
        ucr_obj._browse_mode = rrow.get("mode", "")  # type: ignore[attr-defined]
        records.append(ucr_obj)

    effective_sort_page = sort_by if sort_by in {"published_at", "platform", "author", "arena", "engagement_score"} else "published_at"
    use_keyset_page = effective_sort_page == "published_at"

    cursor: str | None = None
    if len(records) == _BROWSE_LIMIT:
        if use_keyset_page:
            last_rec = records[-1]
            pub_at = getattr(last_rec, "published_at", None)
            rec_id = getattr(last_rec, "id", None)
            if pub_at and rec_id:
                cursor = _encode_cursor(pub_at, rec_id)
        else:
            cursor = "offset"

    # Fetch recent collection runs for the sidebar run selector (last 20).
    recent_runs = await _fetch_recent_runs(db, current_user)

    # Fetch user's projects for the project filter dropdown.
    from issue_observatory.core.models.project import Project as ProjectModel

    projects_stmt = (
        select(ProjectModel)
        .where(ProjectModel.owner_id == current_user.id)
        .order_by(ProjectModel.name)
    )
    projects_result = await db.execute(projects_stmt)
    user_projects = [
        {"id": str(p.id), "name": p.name}
        for p in projects_result.scalars().all()
    ]

    # Total count — use the SAME spec as the browse query (Task 3).
    count_stmt = build_count_stmt(spec)
    count_result = await db.execute(count_stmt)
    total_count: int = count_result.scalar_one() or 0

    # Resolve effective content_types for template display (filter pill).
    effective_content_types = spec.content_types  # already defaulted by from_browse_route

    filter_ctx = {
        "q": q or "",
        "platform": platform or "",
        "arenas": arenas_list,  # multi-value checkbox state
        "date_from": date_from or "",
        "date_to": date_to or "",
        "language": language or "",
        "language_was_explicit": language_was_explicit,
        "search_term": search_term or "",
        "run_id": str(run_id) if run_id else "",
        "mode": mode or "",
        "project_id": str(project_id) if project_id else "",
        "query_design_id": str(query_design_id) if query_design_id else "",
        "actor_ids": [str(a) for a in actor_ids],
        "show_all": show_all,
        "show_duplicates": show_duplicates,
        "scrape_status": scrape_status_filter or "",
        "sort_by": sort_by or "published_at",
        "sort_dir": sort_dir or "desc",
        "content_types": effective_content_types or [],
        "content_types_was_explicit": content_types_was_explicit,
        # Expose whether the content_types filter is the silent default so the
        # template can show a clearable filter pill (Task 4 / decision B).
        "content_types_is_default": not content_types_was_explicit and not content_types,
        # Phase 6 — Task 4: expose limit for the page-size selector.
        "limit": limit,
    }

    return templates.TemplateResponse(
        "content/browser.html",
        {
            "request": request,
            "user": current_user,
            "records": [_orm_row_to_template_dict(r) for r in records],
            "total_count": total_count,
            "recent_runs": recent_runs,
            "filter": filter_ctx,
            "cursor": cursor or "",
            "active_query_design_id": str(query_design_id) if query_design_id else "",
            "user_projects": user_projects,
            "user_query_designs": user_query_designs,
            "filter_warnings": filter_warnings,
        },
    )


# ---------------------------------------------------------------------------
# Records fragment (HTMX tbody rows — cursor paginated)
# ---------------------------------------------------------------------------


@router.get("/records")
async def content_records_fragment(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    cursor: str | None = Query(default=None, description="Opaque keyset cursor."),
    q: str | None = Query(default=None),
    arenas: list[str] | None = Query(default=None),
    platform: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    language: str | None = Query(default=None),
    search_term: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    mode: str | None = Query(default=None, description="Collection mode filter: 'batch' or 'live'."),
    query_design_id: str | None = Query(default=None, description="Filter by query design UUID."),
    project_id: str | None = Query(default=None, description="Filter content to a specific project."),
    actor_id: list[str] | None = Query(default=None, description="Filter by actor UUID(s)."),
    show_all: bool = Query(default=False, description="Show all content including non-term-matched records."),
    show_duplicates: bool = Query(default=False, description="Include duplicate records (excluded by default)."),
    scrape_status_filter: str | None = Query(default=None, alias="scrape_status", description="Filter by scrape status: pending, scraped, failed."),
    offset: int = Query(default=0, ge=0, description="Running total of rows already sent."),
    limit: int = Query(default=_BROWSE_LIMIT, ge=10, le=500, description="Results per page (10–500)."),
    format: str | None = Query(
        default=None,
        description="Response format: 'json' or omit for HTML. Also checks Accept header.",
    ),
    sort_by: str | None = Query(default=None, description="Column to sort by."),
    sort_dir: str | None = Query(default=None, description="Sort direction: asc or desc."),
    content_types: list[str] | None = Query(default=None, description="Content type filter."),
) -> Response:
    """Return content records as HTML fragment or JSON array.

    Implements keyset pagination on ``(published_at DESC, id DESC)``.

    **HTML mode (default for HTMX):**
    Each response appends ``<tr>`` rows into ``#records-tbody`` via
    ``hx-swap="beforeend"``.  Once the cumulative ``offset`` reaches 2000,
    an empty sentinel is returned so that HTMX stops triggering further loads.

    **JSON mode (when ``format=json`` or ``Accept: application/json``):**
    Returns a JSON object with keys:
    - ``records`` (list[dict]): Array of content record objects.
    - ``pagination`` (dict): Pagination metadata with ``offset``, ``limit``,
      ``total_returned``, ``next_cursor``, ``has_more``.

    The ``arena`` filter accepts multiple values (checkbox group named
    ``arenas``).

    Args:
        request: The incoming HTTP request.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        cursor: Encoded ``published_at|id`` keyset cursor from the previous page.
        q: Optional full-text search string.
        arenas: Optional list of arena slugs (multi-value checkbox).
        platform: Optional platform filter.
        date_from: Optional lower date bound (YYYY-MM-DD).
        date_to: Optional upper date bound (YYYY-MM-DD).
        language: Optional ISO 639-1 language code filter.
        search_term: Optional filter on ``search_terms_matched`` array.
        run_id: Optional collection run UUID.
        offset: Number of rows already rendered (used to enforce 2000-row cap).
        limit: Page size (default 50, max 200).
        format: Response format (``json`` or omit for HTML).

    Returns:
        ``HTMLResponse`` containing ``<tr>`` elements plus an optional
        sentinel ``<tr hx-trigger="revealed">`` for further loading, or
        ``JSONResponse`` with records array and pagination metadata.
    """
    # Coerce empty-string UUID params from HTMX form serialization.
    run_id = _parse_uuid(run_id)  # type: ignore[arg-type]
    query_design_id = _parse_uuid(query_design_id)  # type: ignore[arg-type]
    project_id = _parse_uuid(project_id)  # type: ignore[arg-type]
    actor_ids: list[uuid.UUID] = [
        _id for raw in (actor_id or [])
        if ((_id := _parse_uuid(raw)) is not None)
    ]

    # Sentinels for language and content_types (Task 5, Task 4).
    content_types_was_explicit = "content_types" in request.query_params
    language_was_explicit = "language" in request.query_params

    # Determine response format based on query param and Accept header.
    wants_json = _prefers_json(request, format)

    # For HTML responses, validate templates are available.
    if not wants_json:
        templates = request.app.state.templates
        if templates is None:
            raise HTTPException(status_code=500, detail="Template engine not initialised.")

    # Enforce hard cap: if caller has already received 2000 rows, return nothing.
    if offset >= _BROWSE_CAP:
        if wants_json:
            return JSONResponse(
                {
                    "records": [],
                    "pagination": {
                        "offset": offset,
                        "limit": 0,
                        "total_returned": 0,
                        "next_cursor": None,
                        "has_more": False,
                    },
                }
            )
        else:
            return HTMLResponse("", status_code=200)

    remaining = min(limit, _BROWSE_CAP - offset)

    cursor_published_at: datetime | None = None
    cursor_id_val: uuid.UUID | None = None
    if cursor:
        cursor_published_at, cursor_id_val = _decode_cursor(cursor)

    # Phase 6 — Task 2: Validation for the fragment endpoint.
    fragment_warnings: list[str] = []
    date_from_dt = _validate_date_filter(date_from, "date_from", fragment_warnings)
    date_to_dt = _validate_date_filter(date_to, "date_to", fragment_warnings, end_of_day=True)
    mode = _validate_enum_filter(mode, _VALID_MODES, "mode", fragment_warnings)
    scrape_status_filter = _validate_enum_filter(
        scrape_status_filter, _VALID_SCRAPE_STATUSES, "scrape_status", fragment_warnings
    )
    if language_was_explicit and language:
        language = _validate_enum_filter(language, _VALID_LANGUAGES, "language", fragment_warnings)

    # Merge arenas multi-value list with singular platform/arena params.
    arenas_list: list[str] = arenas or []
    platform_filter: str | None = platform
    if len(arenas_list) == 1:
        platform_filter = arenas_list[0]

    # Determine sort and pagination mode.
    effective_sort = sort_by if sort_by in {"published_at", "platform", "author", "arena", "engagement_score"} else "published_at"
    use_keyset = effective_sort == "published_at"

    # Build ONE spec for both browse and count (Task 3). No effective_show_all
    # mutation — actor-only exemption is handled inside the spec/predicates.
    spec = ContentFilterSpec.from_browse_route(
        current_user=current_user,
        q=q,
        platform=platform_filter if len(arenas_list) <= 1 else None,
        arena=None,
        arenas_list=arenas_list,
        date_from=date_from_dt,
        date_to=date_to_dt,
        language=language,
        language_was_explicit=language_was_explicit,
        search_term=search_term,
        run_id=run_id,
        mode=mode,
        project_id=project_id,
        query_design_id=query_design_id,
        show_all=show_all,
        scrape_status=scrape_status_filter,
        content_types=content_types,
        content_types_was_explicit=content_types_was_explicit,
        include_duplicates=show_duplicates,
        actor_ids=actor_ids,
        sort_by=sort_by,
        sort_dir=sort_dir,
        cursor_published_at=cursor_published_at if use_keyset else None,
        cursor_id=cursor_id_val if use_keyset else None,
        page_offset=offset if not use_keyset else 0,
        limit=remaining,
    )

    stmt = _cf_build_browse_stmt(spec)
    result = await db.execute(stmt)
    raw_rows = list(result.mappings().all())

    # Unpack the ORM instance + mode from the JOIN mapping (same as initial load).
    records: list = []
    for rrow in raw_rows:
        ucr_obj = rrow.get("UniversalContentRecord")
        if ucr_obj is None:
            continue
        ucr_obj._browse_mode = rrow.get("mode", "")  # type: ignore[attr-defined]
        records.append(ucr_obj)

    new_offset = offset + len(records)
    next_cursor: str | None = None
    if len(records) == remaining and new_offset < _BROWSE_CAP:
        if use_keyset:
            last_rec = records[-1]
            pub_at = getattr(last_rec, "published_at", None)
            rec_id = getattr(last_rec, "id", None)
            if pub_at and rec_id:
                next_cursor = _encode_cursor(pub_at, rec_id)
        else:
            next_cursor = "offset"

    template_records = [_orm_row_to_template_dict(r) for r in records]

    # Return JSON if requested, otherwise HTML.
    if wants_json:
        json_records = [
            {
                "id": r["id"],
                "platform": r["platform"],
                "arena": r["arena"],
                "content_type": r["content_type"],
                "title": r["title"],
                "text_content": r["text"],
                "author_display_name": r["author"],
                "author_platform_id": r["author_id"],
                "url": r["url"],
                "published_at": r["published_at"],
                "collected_at": r["collected_at"],
                "language": r["language"],
                "engagement_score": r["engagement_score"],
                "search_terms_matched": r["search_terms_matched"],
                "collection_run_id": r["run_id"],
                "mode": r.get("mode", ""),
                "raw_metadata": r.get("metadata", {}),
            }
            for r in template_records
        ]

        return JSONResponse(
            {
                "records": json_records,
                "pagination": {
                    "offset": new_offset,
                    "limit": limit,
                    "total_returned": len(json_records),
                    "next_cursor": next_cursor,
                    "has_more": next_cursor is not None and new_offset < _BROWSE_CAP,
                },
            }
        )
    else:
        html = templates.get_template("_fragments/content_table_body.html").render(
            {
                "request": request,
                "records": template_records,
                "next_cursor": next_cursor or "",
                "new_offset": new_offset,
                "browse_cap": _BROWSE_CAP,
            }
        )

        # OOB count update: on fresh filter requests (no cursor, offset=0),
        # compute total count with the SAME spec (Task 3 — count == rows).
        if not cursor and offset == 0:
            count_stmt = build_count_stmt(spec)
            count_result = await db.execute(count_stmt)
            total_count: int = count_result.scalar_one() or 0
            if total_count > _BROWSE_CAP:
                count_text = "2,000+ records"
            elif total_count > 0:
                count_text = f"{total_count:,} record{'s' if total_count != 1 else ''}"
            else:
                count_text = ""
            html += (
                f'<span id="record-count" hx-swap-oob="innerHTML">'
                f"{count_text}</span>"
            )

            # OOB filter warning banner update (Phase 6 — Task 2).
            # Sends an empty div when there are no warnings to clear any previous banner.
            if fragment_warnings:
                warning_items = "".join(
                    f'<li>{w}</li>' for w in fragment_warnings
                )
                html += (
                    f'<div id="filter-warning-banner" hx-swap-oob="innerHTML">'
                    f'<ul class="list-disc list-inside space-y-0.5">{warning_items}</ul>'
                    f'</div>'
                )
            else:
                html += '<div id="filter-warning-banner" hx-swap-oob="innerHTML"></div>'

        return HTMLResponse(html, status_code=200)


# ---------------------------------------------------------------------------
# Search-term filter options (HTMX fragment for content browser dropdown)
# ---------------------------------------------------------------------------


@router.get("/search-terms")
async def get_search_terms_for_run(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    run_id: str | None = Query(default=None, description="Collection run UUID."),
) -> HTMLResponse:
    """Return HTML ``<option>`` elements for the search-term filter dropdown.

    Called by the content browser template via HTMX whenever the run selector
    changes.  Queries ``content_records`` for every distinct value across all
    ``search_terms_matched`` arrays that belong to the given run, then returns
    a bare list of ``<option>`` tags that HTMX injects into the existing
    ``<select>`` element.

    Ownership scoping mirrors ``_build_browse_stmt``: non-admin users only see
    terms from their own collection runs.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        run_id: Optional UUID of the collection run to scope the query to.

    Returns:
        ``HTMLResponse`` containing a leading ``<option value="">All terms</option>``
        followed by one ``<option>`` per distinct matched search term, or just
        the "All terms" option when ``run_id`` is not provided or no terms are
        found.
    """
    run_id = _parse_uuid(run_id)  # type: ignore[assignment]
    terms: list[str] = []

    if run_id is not None:
        if current_user.role == "admin":
            ownership_filter = "TRUE"
            ownership_params: dict[str, str] = {"run_id": str(run_id)}
        else:
            ownership_filter = (
                "cr.collection_run_id IN ("
                "  SELECT id FROM collection_runs WHERE initiated_by = :user_id"
                ")"
            )
            ownership_params = {"run_id": str(run_id), "user_id": str(current_user.id)}

        raw_sql = text(
            f"""
            SELECT DISTINCT unnest(cr.search_terms_matched) AS term
            FROM content_records cr
            WHERE (cr.collection_run_id = :run_id
                   OR EXISTS (
                     SELECT 1 FROM content_record_links crl
                     WHERE crl.collection_run_id = CAST(:run_id AS uuid)
                       AND crl.content_record_id = cr.id
                       AND crl.content_record_published_at = cr.published_at))
              AND cr.search_terms_matched IS NOT NULL
              AND {ownership_filter}
            ORDER BY term
            """
        )

        result = await db.execute(raw_sql, ownership_params)
        terms = [row[0] for row in result.fetchall() if row[0]]

    option_html = '<option value="">All terms</option>\n'
    for term in terms:
        # Escape HTML special characters in term text/value.
        escaped = (
            term.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
        option_html += f'<option value="{escaped}">{escaped}</option>\n'

    return HTMLResponse(content=option_html, status_code=200)


# ---------------------------------------------------------------------------
# Actor filter options (HTMX fragment for content browser dropdown)
# Must be declared BEFORE the parametric /{record_id} route.
# ---------------------------------------------------------------------------


@router.get("/actors")
async def get_actors_for_scope(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    run_id: str | None = Query(default=None, description="Scope actor list to this collection run."),
    project_id: str | None = Query(default=None, description="Scope actor list to this project."),
) -> HTMLResponse:
    """Return HTML ``<option>`` elements for the actor filter dropdown (Task 1, Phase 3).

    Called by the content browser template via HTMX whenever the run or
    project selector changes. Returns actors linked to content records in
    the scoped run or project, limited to 500 to avoid N+1 blowup on large
    corpora. Ownership scoping mirrors the browse query.

    When neither ``run_id`` nor ``project_id`` is set, returns an empty fragment
    with a hint ``<option>`` so the user knows they need to select a run or
    project first.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        run_id: Optional UUID of the collection run to scope actor list to.
        project_id: Optional UUID of the project to scope actor list to.

    Returns:
        ``HTMLResponse`` with ``<option>`` elements: a leading "All actors" option
        followed by one option per distinct actor in the scoped records (capped at 500).
        Returns a hint option when no scope is provided.
    """
    _ACTOR_LIMIT = 500

    run_id_parsed = _parse_uuid(run_id)
    project_id_parsed = _parse_uuid(project_id)

    actors: list[tuple[uuid.UUID, str]] = []  # (id, display_name)

    if run_id_parsed is None and project_id_parsed is None:
        # No scope — return hint message instead of loading the full actor table.
        hint = '<option value="" disabled>Select a run or project to filter by actor</option>\n'
        return HTMLResponse(content=hint, status_code=200)

    # Build a subquery to identify qualifying content records, then join to actors.
    ucr = UniversalContentRecord

    # Ownership scope: restrict to runs the user can see.
    if current_user.role == "admin":
        ownership_run_ids_subq = select(CollectionRun.id).scalar_subquery()
    else:
        from issue_observatory.core.models.project_collaborator import ProjectCollaborator as PC

        collab_project_ids = (
            select(PC.project_id)
            .where(PC.user_id == current_user.id)
            .scalar_subquery()
        )
        ownership_run_ids_subq = (
            select(CollectionRun.id)
            .where(
                or_(
                    CollectionRun.initiated_by == current_user.id,
                    CollectionRun.project_id.in_(collab_project_ids),
                )
            )
            .scalar_subquery()
        )

    # Scope: run_id or project_id.
    if run_id_parsed is not None:
        scope_filter = _run_id_filter_sa(
            ucr.collection_run_id,
            ucr.published_at,
            ucr.id,
            run_id_parsed,
        )
    else:
        # project_id scope: records in any run belonging to the project.
        project_run_ids = (
            select(CollectionRun.id)
            .where(CollectionRun.project_id == project_id_parsed)
            .scalar_subquery()
        )
        scope_filter = ucr.collection_run_id.in_(project_run_ids)

    actor_stmt = (
        select(Actor.id, Actor.canonical_name)
        .join(ucr, ucr.author_id == Actor.id)
        .where(scope_filter)
        .where(ucr.collection_run_id.in_(ownership_run_ids_subq))
        .where(Actor.canonical_name.isnot(None))
        .distinct()
        .order_by(Actor.canonical_name)
        .limit(_ACTOR_LIMIT)
    )
    result = await db.execute(actor_stmt)
    actors = [(row[0], row[1]) for row in result.fetchall()]

    option_html = '<option value="">All actors</option>\n'
    if len(actors) == _ACTOR_LIMIT:
        option_html += (
            '<option value="" disabled>'
            "Showing first 500 actors — type to search"
            "</option>\n"
        )
    for actor_uuid, name in actors:
        escaped_name = (
            name.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
        escaped_id = str(actor_uuid)
        option_html += f'<option value="{escaped_id}">{escaped_name}</option>\n'

    return HTMLResponse(content=option_html, status_code=200)


# ---------------------------------------------------------------------------
# Discovered links — GR-22 cross-platform link mining
# Must be declared BEFORE the parametric /{record_id} route so that FastAPI
# does not try to parse "discovered-links" as a UUID.
# ---------------------------------------------------------------------------


@router.get("/discovered-links")
async def get_discovered_links(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    query_design_id: str | None = Query(
        default=None,
        description=(
            "Optional UUID of a query design to scope to. "
            "If omitted, mines all content from all the current user's query designs."
        ),
    ),
    platform: str | None = Query(
        default=None,
        description=(
            "Optional platform slug to filter results "
            "(e.g. 'telegram', 'bluesky', 'youtube').  Omit for all platforms."
        ),
    ),
    min_source_count: int = Query(
        default=2,
        ge=1,
        description="Minimum number of distinct content records that must link to a target.",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
        description="Maximum number of discovered links to return (default 50, max 500).",
    ),
) -> dict[str, Any]:
    """Mine cross-platform links from a query design's or user's content corpus.

    Extracts all ``https?://`` URLs from ``text_content`` of every content
    record matching the scope, classifies them by target platform, aggregates
    by target identifier, and returns the results grouped by platform and
    sorted by ``source_count`` descending.

    A link that appears in fewer than ``min_source_count`` distinct records
    is excluded (default: 2) to surface high-signal discovery targets.

    When ``query_design_id`` is provided, scopes to that single query design.
    When omitted, mines all content from all of the current user's collection
    runs across all their query designs (YF-13: cross-design view).

    The response groups results by platform for easy scanning in the Discovered
    Sources UI panel.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        query_design_id: Optional UUID of a query design to scope to. If
            ``None``, mines across all user content.
        platform: Optional platform slug to restrict results to.
        min_source_count: Minimum source-record count threshold (default: 2).
        limit: Maximum total links returned across all platforms (default 50).

    Returns:
        Dict with keys:
        - ``query_design_id`` (str | None): echoed back, or ``None`` if
          user-scope mode.
        - ``scope`` (str): either ``"single_design"`` or ``"user_all_designs"``.
        - ``total_links`` (int): total discovered links before grouping.
        - ``by_platform`` (dict[str, list]): links grouped by platform slug,
          each entry containing the ``DiscoveredLink`` fields.

    Raises:
        HTTPException 404: Not raised — an empty result is returned when no
            links are found.
    """
    query_design_id = _parse_uuid(query_design_id)  # type: ignore[assignment]

    from issue_observatory.analysis.link_miner import LinkMiner

    miner = LinkMiner()
    links = await miner.mine(
        db=db,
        query_design_id=query_design_id,
        user_id=current_user.id if query_design_id is None else None,
        platform_filter=platform,
        min_source_count=min_source_count,
        limit=limit,
    )

    # Group by platform.
    by_platform: dict[str, list[dict]] = {}
    for link in links:
        by_platform.setdefault(link.platform, []).append(
            {
                "url": link.url,
                "platform": link.platform,
                "target_identifier": link.target_identifier,
                "source_count": link.source_count,
                "first_seen_at": link.first_seen_at.isoformat(),
                "last_seen_at": link.last_seen_at.isoformat(),
                "example_source_urls": link.example_source_urls,
            }
        )

    scope = "single_design" if query_design_id else "user_all_designs"

    logger.info(
        "discovered_links.mined",
        query_design_id=str(query_design_id) if query_design_id else None,
        scope=scope,
        total_links=len(links),
        platforms=list(by_platform.keys()),
        user_id=str(current_user.id),
    )

    return {
        "query_design_id": str(query_design_id) if query_design_id else None,
        "scope": scope,
        "total_links": len(links),
        "by_platform": by_platform,
    }


# ---------------------------------------------------------------------------
# Export — synchronous (up to 10 K records, returns file directly)
# ---------------------------------------------------------------------------


@router.get("/export")
# @limiter.limit("10/minute")  # Disabled: slowapi corrupts FastAPI param parsing
async def export_content_sync(  # type: ignore[misc]
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    format: str = Query(
        default="csv",
        description="Export format: csv, xlsx, json, parquet, gexf, ris, bibtex.",
    ),
    network_type: str = Query(
        default="actor",
        description=(
            "GEXF network type (only used when format=gexf). "
            "One of: actor, term, bipartite."
        ),
    ),
    # --- Filter parameters (must match /content/records exactly — Task 2) ---
    q: str | None = Query(default=None, description="Full-text search query."),
    arenas: list[str] | None = Query(default=None, description="Multi-value platform filter from checkboxes."),
    platform: str | None = Query(default=None, description="Filter by platform name."),
    arena: str | None = Query(default=None, description="Filter by arena name."),
    query_design_id: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    language: str | None = Query(default=None),
    run_id: str | None = Query(
        default=None, description="Filter by specific collection run UUID."
    ),
    mode: str | None = Query(default=None, description="Collection mode filter: 'batch' or 'live'."),
    project_id: str | None = Query(default=None, description="Filter content to a specific project."),
    show_all: bool = Query(default=False, description="Show all content including non-term-matched records."),
    show_duplicates: bool = Query(default=False, description="Include duplicate records (excluded by default)."),
    search_term: str | None = Query(default=None),
    scrape_status: str | None = Query(default=None, description="Filter by scrape status: pending, scraped, failed."),
    content_types: list[str] | None = Query(default=None, description="Content type filter."),
    actor_id: list[str] | None = Query(default=None, description="Filter by actor UUID(s). Multi-value; same as browse route."),
    # --- Export-specific params ---
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

    Phase 2: export now accepts ALL browse filter parameters (q, mode, project_id,
    show_all, scrape_status, content_types) so the exported file exactly matches
    what the researcher sees in the content browser table. The export uses the
    same ``ContentFilterSpec.from_export_route`` helper with
    ``owner_plus_collaborators`` scoping (decision D).

    The response is returned synchronously — the file is assembled in memory
    and streamed to the client with appropriate ``Content-Disposition`` and
    ``Content-Type`` headers.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        format: Export format.
        network_type: GEXF network type (ignored for non-GEXF formats).
        q: Optional full-text search query.
        platform: Optional platform filter.
        arena: Optional arena filter.
        query_design_id: Optional query design UUID filter.
        date_from: Optional lower bound on ``published_at``.
        date_to: Optional upper bound on ``published_at``.
        language: Optional ISO 639-1 language code filter.
        run_id: Optional collection run UUID filter.
        mode: Optional collection mode filter.
        project_id: Optional project UUID filter.
        show_all: If True, include non-term-matched records.
        search_term: Optional term contained in ``search_terms_matched``.
        scrape_status: Optional scrape status filter.
        content_types: Optional list of content types to include.
        limit: Maximum records (1–10 000; default 10 000).
        include_metadata: If True, include ``raw_metadata`` column (CSV only).

    Returns:
        A ``Response`` with the file bytes and a ``Content-Disposition:
        attachment`` header.

    Raises:
        HTTPException 400: If the requested format is not supported, or if
            ``network_type`` is invalid for GEXF exports.
        HTTPException 500: If serialization fails due to a missing optional
            dependency (openpyxl / pyarrow not installed).
    """
    query_design_id_parsed = _parse_uuid(query_design_id)
    run_id_parsed = _parse_uuid(run_id)
    project_id_parsed = _parse_uuid(project_id)

    # Sentinels for language and content_types (match browse route logic).
    content_types_was_explicit = "content_types" in request.query_params
    language_was_explicit = "language" in request.query_params

    # Phase 6 — Task 2: Apply same validation as browse route so export
    # and browse agree on how invalid filter values are handled.
    _export_warnings: list[str] = []
    date_from_dt = _validate_date_filter(date_from, "date_from", _export_warnings)
    date_to_dt = _validate_date_filter(date_to, "date_to", _export_warnings, end_of_day=True)
    mode = _validate_enum_filter(mode, _VALID_MODES, "mode", _export_warnings)
    scrape_status = _validate_enum_filter(
        scrape_status, _VALID_SCRAPE_STATUSES, "scrape_status", _export_warnings
    )
    if language_was_explicit and language:
        language = _validate_enum_filter(language, _VALID_LANGUAGES, "language", _export_warnings)
    export_actor_ids: list[uuid.UUID] = [
        _id for raw in (actor_id or [])
        if ((_id := _parse_uuid(raw)) is not None)
    ]

    if format not in _EXPORT_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported export format {format!r}. Choose from: {', '.join(_EXPORT_CONTENT_TYPES)}.",
        )

    _VALID_NETWORK_TYPES = {"actor", "term", "bipartite"}
    if format == "gexf" and network_type not in _VALID_NETWORK_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported network_type {network_type!r} for GEXF export. "
                f"Choose from: {', '.join(sorted(_VALID_NETWORK_TYPES))}."
            ),
        )

    # Handle arenas multi-value filter — folded into spec (Task 7).
    arenas_list: list[str] = arenas or []
    platform_filter: str | None = platform
    if len(arenas_list) == 1:
        platform_filter = arenas_list[0]

    # Build spec using same parameters as the browse route (Task 2, decision D).
    export_spec = ContentFilterSpec.from_export_route(
        current_user=current_user,
        q=q,
        platform=platform_filter if len(arenas_list) <= 1 else None,
        arena=arena,
        arenas_list=arenas_list,
        query_design_id=query_design_id_parsed,
        date_from=date_from_dt,
        date_to=date_to_dt,
        language=language,
        language_was_explicit=language_was_explicit,
        search_term=search_term,
        run_id=run_id_parsed,
        mode=mode,
        project_id=project_id_parsed,
        show_all=show_all,
        include_duplicates=show_duplicates,
        scrape_status=scrape_status,
        content_types=content_types,
        content_types_was_explicit=content_types_was_explicit,
        actor_ids=export_actor_ids,
        limit=limit,
    )

    # Use build_browse_stmt so export and browse share the same query (Task 2).
    stmt = _cf_build_browse_stmt(export_spec)
    db_result = await db.execute(stmt)
    raw_rows = list(db_result.mappings().all())

    # Extract ORM instances from the mapping (browse_stmt returns a JOIN result).
    orm_rows = []
    for rrow in raw_rows:
        ucr_obj = rrow.get("UniversalContentRecord")
        if ucr_obj is not None:
            orm_rows.append(ucr_obj)

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
        elif format == "ris":
            file_bytes = exporter.export_ris(records)
        elif format == "bibtex":
            file_bytes = exporter.export_bibtex(records)
        else:  # gexf
            # Build network graph using proper network analysis functions.
            if network_type == "actor":
                graph = await get_actor_co_occurrence(
                    db=db,
                    run_id=run_id_parsed,
                    query_design_id=query_design_id_parsed,
                    arena=arena,
                    platform=platform,
                    date_from=date_from_dt,
                    date_to=date_to_dt,
                )
            elif network_type == "term":
                graph = await get_term_co_occurrence(
                    db=db,
                    run_id=run_id_parsed,
                    query_design_id=query_design_id_parsed,
                    arena=arena,
                )
            else:  # bipartite
                graph = await build_bipartite_network(
                    db=db,
                    run_id=run_id_parsed,
                    query_design_id=query_design_id_parsed,
                    arena=arena,
                )
            file_bytes = await exporter.export_gexf(graph, network_type=network_type)
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    ext = _EXPORT_EXTENSIONS[format]
    filename = f"content_export_{network_type}.{ext}" if format == "gexf" else f"content_export.{ext}"
    content_type = _EXPORT_CONTENT_TYPES[format]

    logger.info(
        "export.sync.complete",
        user_id=str(current_user.id),
        format=format,
        network_type=network_type if format == "gexf" else None,
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
    network_type: str = Query(
        default="actor",
        description=(
            "GEXF network type (only used when format=gexf). "
            "One of: actor, term, bipartite."
        ),
    ),
    platform: str | None = Query(default=None),
    arena: str | None = Query(default=None),
    query_design_id: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    language: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    search_term: str | None = Query(default=None),
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
        network_type: GEXF network type (ignored for non-GEXF formats).
            One of ``actor``, ``term``, ``bipartite``.  Defaults to
            ``"actor"``.
        platform: Optional platform filter.
        arena: Optional arena filter.
        query_design_id: Optional query design UUID (accepts empty string).
        date_from: Optional lower bound on ``published_at``.
        date_to: Optional upper bound on ``published_at``.
        language: Optional ISO 639-1 language code.
        run_id: Optional collection run UUID (accepts empty string).
        search_term: Optional term in ``search_terms_matched``.

    Returns:
        ``{"job_id": "<uuid>", "status": "pending"}``

    Raises:
        HTTPException 400: If the format is not supported, or if
            ``network_type`` is invalid for GEXF exports.
    """
    query_design_id = _parse_uuid(query_design_id)  # type: ignore[assignment]
    run_id = _parse_uuid(run_id)  # type: ignore[assignment]
    date_from = _parse_date_param(date_from)  # type: ignore[assignment]
    date_to = _parse_date_param(date_to, end_of_day=True)  # type: ignore[assignment]

    if format not in _EXPORT_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported export format {format!r}. Choose from: {', '.join(_EXPORT_CONTENT_TYPES)}.",
        )

    _VALID_NETWORK_TYPES = {"actor", "term", "bipartite"}
    if format == "gexf" and network_type not in _VALID_NETWORK_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported network_type {network_type!r} for GEXF export. "
                f"Choose from: {', '.join(sorted(_VALID_NETWORK_TYPES))}."
            ),
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
    # Always store network_type in filters so the Celery task can pass it
    # through to ContentExporter.export_gexf().  For non-GEXF formats the
    # task ignores this key.
    filters["network_type"] = network_type

    # Write initial pending status to Redis before dispatching the task
    # so that a status poll immediately after this response returns something
    # meaningful rather than a key-not-found.
    import redis as redis_lib

    from issue_observatory.config.settings import get_settings

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
    import redis as redis_lib

    from issue_observatory.config.settings import get_settings

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

    object_key: str | None = job_status.get("object_key")
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


# ---------------------------------------------------------------------------
# Deduplication — Task 3.8
# ---------------------------------------------------------------------------


@router.post("/deduplicate", status_code=status.HTTP_202_ACCEPTED)
async def trigger_deduplication(
    current_user: Annotated[User, Depends(get_current_active_user)],
    run_id: uuid.UUID = Query(..., description="Collection run UUID to deduplicate."),
) -> dict[str, str]:
    """Dispatch an asynchronous near-duplicate detection pass for a collection run.

    Dispatches the ``deduplicate_run`` Celery task which performs URL-normalised
    and content-hash duplicate detection, marking duplicate records by setting
    ``raw_metadata['duplicate_of']`` to the canonical record's UUID.

    Args:
        current_user: The authenticated, active user making the request.
        run_id: UUID of the collection run to deduplicate.

    Returns:
        ``{"job_id": "<task-id>", "status": "pending"}``
    """
    from issue_observatory.workers.maintenance_tasks import deduplicate_run

    task = deduplicate_run.apply_async(kwargs={"run_id": str(run_id)})

    logger.info(
        "dedup.dispatched",
        job_id=task.id,
        run_id=str(run_id),
        user_id=str(current_user.id),
    )

    return {"job_id": task.id, "status": "pending"}


@router.get("/duplicates")
async def get_duplicates(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    run_id: uuid.UUID = Query(..., description="Collection run UUID to inspect for duplicates."),
) -> dict[str, Any]:
    """Return URL and hash duplicate groups for a collection run.

    Runs both URL-normalisation and content-hash duplicate detection
    synchronously and returns the groups as JSON.  Intended for inspecting
    small runs or verifying dedup results — for large runs use the async
    ``POST /content/deduplicate`` endpoint instead.

    Args:
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        run_id: UUID of the collection run to inspect.

    Returns:
        Dict with keys ``url_groups`` and ``hash_groups``, each a list of
        duplicate group objects.
    """
    from issue_observatory.core.deduplication import DeduplicationService

    svc = DeduplicationService()
    url_groups = await svc.find_url_duplicates(db, run_id=run_id)
    hash_groups = await svc.find_hash_duplicates(db, run_id=run_id)

    logger.info(
        "dedup.inspect",
        run_id=str(run_id),
        url_groups=len(url_groups),
        hash_groups=len(hash_groups),
        user_id=str(current_user.id),
    )

    return {
        "run_id": str(run_id),
        "url_groups": url_groups,
        "hash_groups": hash_groups,
    }


# ---------------------------------------------------------------------------
# Detail — HTML panel or standalone page
# ---------------------------------------------------------------------------
# NOTE: This route MUST be defined after all named routes (e.g. /export,
# /records, /duplicates) because FastAPI matches routes in definition order
# and /{record_id} would shadow them otherwise.


@router.get("/{record_id:uuid}")
async def get_content_record_html(
    record_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    hx_request: str | None = Header(default=None, alias="HX-Request"),
) -> Response:
    """Return a content record as an HTML detail panel or standalone page.

    When the request includes the ``HX-Request`` header (HTMX partial load),
    the template is rendered without ``standalone=True`` so it outputs only
    the inner panel markup.  Otherwise the full ``base.html`` wrapper is used.
    """
    templates = request.app.state.templates

    if templates is None:
        raise HTTPException(status_code=500, detail="Template engine not initialised.")

    # A2: Include resolved actor name via LEFT JOIN
    resolved_name_col = Actor.canonical_name.label("_resolved_name")

    if current_user.role == "admin":
        stmt = (
            select(UniversalContentRecord, resolved_name_col)
            .join(Actor, UniversalContentRecord.author_id == Actor.id, isouter=True)
            .where(UniversalContentRecord.id == record_id)
        )
    else:
        user_run_ids_subq = (
            select(CollectionRun.id)
            .where(CollectionRun.initiated_by == current_user.id)
            .scalar_subquery()
        )
        stmt = (
            select(UniversalContentRecord, resolved_name_col)
            .join(Actor, UniversalContentRecord.author_id == Actor.id, isouter=True)
            .where(
                UniversalContentRecord.id == record_id,
                UniversalContentRecord.collection_run_id.in_(user_run_ids_subq),
            )
        )

    db_result = await db.execute(stmt)
    db_row = db_result.one_or_none()

    if db_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Content record '{record_id}' not found.",
        )

    orm_record = db_row[0]
    resolved_name = db_row[1]
    record_ctx = _orm_to_detail_dict(orm_record, resolved_name=resolved_name)
    is_panel = hx_request is not None

    return templates.TemplateResponse(
        "content/record_detail.html",
        {
            "request": request,
            "user": current_user,
            "record": record_ctx,
            "standalone": not is_panel,
        },
    )


# ---------------------------------------------------------------------------
# Content Fetch Enrichment
# ---------------------------------------------------------------------------


@router.post("/{record_id:uuid}/fetch-content")
async def fetch_content_for_record(
    record_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    """Fetch full page content for a thin content record.

    Retrieves the URL from the record, fetches the page, extracts text via
    trafilatura, and updates the record in place.  The original ``text_content``
    (if any) is preserved in ``raw_metadata.original_snippet``.

    Requires ``published_at`` in the JSON body for partition-pruned lookup.

    Returns:
        JSON with updated record summary on success, or error details on failure.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    published_at_str = body.get("published_at")
    if not published_at_str:
        return JSONResponse(
            {"ok": False, "error": "published_at is required"},
            status_code=400,
        )

    # Parse published_at for partition pruning
    try:
        published_at_dt = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return JSONResponse(
            {"ok": False, "error": "Invalid published_at format"},
            status_code=400,
        )

    # Fetch the record with ownership check
    if current_user.role == "admin":
        stmt = select(UniversalContentRecord).where(
            UniversalContentRecord.id == record_id,
            UniversalContentRecord.published_at == published_at_dt,
        )
    else:
        user_run_ids_subq = (
            select(CollectionRun.id)
            .where(CollectionRun.initiated_by == current_user.id)
            .scalar_subquery()
        )
        stmt = select(UniversalContentRecord).where(
            UniversalContentRecord.id == record_id,
            UniversalContentRecord.published_at == published_at_dt,
            UniversalContentRecord.collection_run_id.in_(user_run_ids_subq),
        )

    db_result = await db.execute(stmt)
    record = db_result.scalar_one_or_none()

    if record is None:
        return JSONResponse(
            {"ok": False, "error": "Record not found"},
            status_code=404,
        )

    if not record.url:
        return JSONResponse(
            {"ok": False, "error": "Record has no URL to fetch"},
            status_code=400,
        )

    # Lazy imports for scraper modules
    import httpx as _httpx

    from issue_observatory.scraper.content_extractor import (
        extract_from_html as scraper_extract,
    )
    from issue_observatory.scraper.http_fetcher import fetch_url as scraper_fetch

    # Fetch the page content
    try:
        async with _httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "IssueObservatory/1.0"},
        ) as client:
            robots_cache: dict[str, bool] = {}
            fetch_result = await scraper_fetch(
                record.url,
                client=client,
                timeout=30.0,
                respect_robots=True,
                robots_cache=robots_cache,
            )
    except Exception as exc:
        logger.error(
            "fetch_content: HTTP fetch failed for record %s: %s", record_id, exc
        )
        return JSONResponse(
            {"ok": False, "error": f"Fetch failed: {exc}"},
            status_code=502,
        )

    if fetch_result.error or fetch_result.html is None:
        return JSONResponse(
            {"ok": False, "error": f"Fetch error: {fetch_result.error or 'No HTML returned'}"},
            status_code=502,
        )

    # Extract content
    try:
        extracted = scraper_extract(fetch_result.html, fetch_result.final_url or record.url)
    except Exception as exc:
        logger.error(
            "fetch_content: extraction failed for record %s: %s", record_id, exc
        )
        return JSONResponse(
            {"ok": False, "error": f"Content extraction failed: {exc}"},
            status_code=502,
        )

    if not extracted.text:
        return JSONResponse(
            {"ok": False, "error": "No text content could be extracted from the page"},
            status_code=422,
        )

    # Preserve original snippet in raw_metadata
    metadata = dict(record.raw_metadata) if record.raw_metadata else {}
    if record.text_content and "original_snippet" not in metadata:
        metadata["original_snippet"] = record.text_content

    # Update the record
    metadata["content_fetched"] = True
    metadata["content_fetched_at"] = datetime.now(tz=UTC).isoformat()

    # Use raw SQL for partition-pruned update
    update_stmt = text("""
        UPDATE content_records
        SET text_content = :text_content,
            title = COALESCE(:title, title),
            language = COALESCE(:language, language),
            scrape_status = 'scraped',
            raw_metadata = :raw_metadata
        WHERE id = :id AND published_at = :published_at
    """)

    await db.execute(
        update_stmt,
        {
            "text_content": extracted.text,
            "title": extracted.title,
            "language": extracted.language,
            "raw_metadata": json.dumps(metadata),
            "id": str(record_id),
            "published_at": published_at_dt,
        },
    )
    await db.commit()

    logger.info(
        "fetch_content: updated record %s with %d chars of content",
        record_id,
        len(extracted.text),
    )

    return JSONResponse({
        "ok": True,
        "record_id": str(record_id),
        "title": extracted.title or record.title or "",
        "text_length": len(extracted.text),
        "language": extracted.language,
    })
