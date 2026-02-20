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
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.analysis.export import ContentExporter
from issue_observatory.api.dependencies import get_current_active_user
from issue_observatory.core.database import get_db
from issue_observatory.core.models.collection import CollectionRun
from issue_observatory.core.models.content import UniversalContentRecord
from issue_observatory.core.models.users import User
from issue_observatory.api.limiter import limiter

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
# Cursor helpers
# ---------------------------------------------------------------------------


def _encode_cursor(published_at: Optional[datetime], record_id: uuid.UUID) -> str:
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


def _decode_cursor(cursor: str) -> tuple[Optional[datetime], Optional[uuid.UUID]]:
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


def _parse_date_param(value: Optional[str]) -> Optional[datetime]:
    """Parse a YYYY-MM-DD date string into a timezone-aware ``datetime``.

    Returns ``None`` if the value is missing or cannot be parsed.

    Args:
        value: A date string in ISO format (e.g. ``"2024-01-15"``).

    Returns:
        A UTC-midnight ``datetime`` or ``None``.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Browse query builder (keyset pagination with full-text search)
# ---------------------------------------------------------------------------


def _build_browse_stmt(
    current_user: User,
    q: Optional[str],
    platform: Optional[str],
    arena: Optional[str],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    language: Optional[str],
    search_term: Optional[str],
    run_id: Optional[uuid.UUID],
    mode: Optional[str],
    cursor_published_at: Optional[datetime],
    cursor_id: Optional[uuid.UUID],
    limit: int,
) -> Any:  # noqa: ANN401
    """Build a keyset-paginated SELECT for the content browser.

    Ordering is ``(published_at DESC NULLS LAST, id DESC)`` to support stable
    cursor pagination on the partitioned table.  Full-text search uses
    ``to_tsvector('danish', ...)`` with ``plainto_tsquery``.

    Args:
        current_user: Authenticated user — used for ownership scoping.
        q: Optional full-text search string.
        platform: Optional platform equality filter.
        arena: Optional arena equality filter.
        date_from: Optional lower bound on ``published_at``.
        date_to: Optional upper bound on ``published_at``.
        language: Optional ISO 639-1 language code.
        search_term: Optional member-of-array filter on ``search_terms_matched``.
        run_id: Optional collection run UUID filter.
        mode: Optional collection mode filter ('batch' or 'live').
        cursor_published_at: ``published_at`` value of the last row on the
            previous page (keyset lower bound).
        cursor_id: ``id`` value of the last row on the previous page.
        limit: Maximum rows to return.

    Returns:
        A SQLAlchemy ``Select`` statement.
    """
    ucr = UniversalContentRecord

    # SB-13: Join with collection_runs to get mode for badge display
    if current_user.role == "admin":
        stmt = select(ucr, CollectionRun.mode).join(
            CollectionRun,
            ucr.collection_run_id == CollectionRun.id,
            isouter=True,
        )
    else:
        user_run_ids_subq = (
            select(CollectionRun.id)
            .where(CollectionRun.initiated_by == current_user.id)
            .scalar_subquery()
        )
        stmt = (
            select(ucr, CollectionRun.mode)
            .join(CollectionRun, ucr.collection_run_id == CollectionRun.id, isouter=True)
            .where(ucr.collection_run_id.in_(user_run_ids_subq))
        )

    # Optional filters
    if platform is not None:
        stmt = stmt.where(ucr.platform == platform)
    if arena is not None:
        stmt = stmt.where(ucr.arena == arena)
    if date_from is not None:
        stmt = stmt.where(ucr.published_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(ucr.published_at <= date_to)
    if language is not None:
        stmt = stmt.where(ucr.language == language)
    if run_id is not None:
        stmt = stmt.where(ucr.collection_run_id == run_id)
    if search_term is not None:
        stmt = stmt.where(ucr.search_terms_matched.contains([search_term]))

    # SB-13: Filter by collection mode (batch/live)
    if mode is not None:
        mode_run_ids_subq = (
            select(CollectionRun.id)
            .where(CollectionRun.mode == mode)
        )
        # If there's already a user scoping, intersect with mode filter
        if current_user.role != "admin":
            mode_run_ids_subq = mode_run_ids_subq.where(
                CollectionRun.initiated_by == current_user.id
            )
        stmt = stmt.where(ucr.collection_run_id.in_(mode_run_ids_subq.scalar_subquery()))

    # Full-text search using the GIN index created in migration 001.
    if q:
        tsvector_expr = text(
            "to_tsvector('danish', coalesce(content_records.text_content, '')"
            " || ' ' || coalesce(content_records.title, ''))"
        )
        tsquery_expr = text("plainto_tsquery('danish', :q)")
        stmt = stmt.where(tsvector_expr.op("@@")(tsquery_expr)).params(q=q)

    # Keyset cursor: rows strictly before (published_at, id) in DESC order.
    if cursor_published_at is not None and cursor_id is not None:
        stmt = stmt.where(
            (ucr.published_at < cursor_published_at)
            | (
                (ucr.published_at == cursor_published_at)
                & (ucr.id < cursor_id)
            )
        )
    elif cursor_id is not None:
        # Cursor with null published_at — both null rows come last already.
        stmt = stmt.where(ucr.id < cursor_id)

    stmt = (
        stmt.order_by(
            ucr.published_at.desc().nullslast(),
            ucr.id.desc(),
        )
        .limit(limit)
    )

    return stmt


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
        ``created_at``.
    """
    if current_user.role == "admin":
        stmt = select(CollectionRun).order_by(CollectionRun.created_at.desc()).limit(limit)
    else:
        stmt = (
            select(CollectionRun)
            .where(CollectionRun.initiated_by == current_user.id)
            .order_by(CollectionRun.created_at.desc())
            .limit(limit)
        )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "status": r.status,
            "query_design_name": getattr(r, "query_design_name", None),
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in rows
    ]


async def _count_matching(
    db: AsyncSession,
    current_user: User,
    q: Optional[str],
    platform: Optional[str],
    arena: Optional[str],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    language: Optional[str],
    search_term: Optional[str],
    run_id: Optional[uuid.UUID],
    mode: Optional[str],
) -> int:
    """Return the total number of records matching the current browser filters.

    Used to populate the record-count badge in the browser page header.

    Args:
        db: Async database session.
        current_user: Authenticated user.
        q: Full-text search string.
        platform: Platform filter.
        arena: Arena filter.
        date_from: Lower bound on ``published_at``.
        date_to: Upper bound on ``published_at``.
        language: Language filter.
        search_term: ``search_terms_matched`` array membership filter.
        run_id: Collection run UUID filter.
        mode: Collection mode filter ('batch' or 'live').

    Returns:
        Integer row count (may be approximate on very large datasets).
    """
    from sqlalchemy import func  # noqa: PLC0415

    stmt = _build_browse_stmt(
        current_user=current_user,
        q=q,
        platform=platform,
        arena=arena,
        date_from=date_from,
        date_to=date_to,
        language=language,
        search_term=search_term,
        run_id=run_id,
        mode=mode,
        cursor_published_at=None,
        cursor_id=None,
        limit=_BROWSE_CAP + 1,  # count up to cap+1 to detect overflow
    )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    result = await db.execute(count_stmt)
    return result.scalar_one() or 0


# ---------------------------------------------------------------------------
# Template context helpers
# ---------------------------------------------------------------------------


def _orm_row_to_template_dict(row: Any) -> dict[str, Any]:  # noqa: ANN401
    """Convert a SQLAlchemy mapping row or ORM instance to a template-safe dict.

    Args:
        row: A SQLAlchemy ``RowMapping`` (from ``.mappings()``) or an ORM instance.

    Returns:
        Dict with string keys matching what the browser and detail templates
        expect.
    """
    # Supports both RowMapping (dict-like) and ORM instances.
    def _get(key: str) -> Any:  # noqa: ANN401
        try:
            return row[key]
        except (TypeError, KeyError):
            return getattr(row, key, None)

    pub = _get("published_at")
    col = _get("collected_at")
    terms = _get("search_terms_matched") or []

    # SB-13: Extract mode from the joined collection_runs table
    mode = _get("mode") or ""

    return {
        "id": str(_get("id") or ""),
        "platform": _get("platform") or "",
        "arena": _get("arena") or "",
        "content_type": _get("content_type") or "",
        "title": _get("title") or "",
        "text": _get("text_content") or "",
        "author": _get("author_display_name") or "",
        "author_id": str(_get("author_platform_id") or ""),
        "url": _get("url") or "",
        "published_at": pub.isoformat() if pub else "",
        "collected_at": col.isoformat() if col else "",
        "language": _get("language") or "",
        "engagement_score": _get("engagement_score") or 0,
        "search_terms_matched": terms if isinstance(terms, list) else [],
        "run_id": str(_get("collection_run_id") or ""),
        "metadata": _get("raw_metadata") or {},
        "mode": mode,
    }


def _orm_to_detail_dict(record: UniversalContentRecord) -> dict[str, Any]:
    """Convert an ORM ``UniversalContentRecord`` to the detail template context dict.

    Args:
        record: An ORM instance loaded from the database.

    Returns:
        Dict with keys expected by ``content/record_detail.html``.
    """
    pub = record.published_at
    col = record.collected_at
    terms = record.search_terms_matched or []

    return {
        "id": str(record.id),
        "platform": record.platform or "",
        "arena": record.arena or "",
        "content_type": record.content_type or "",
        "title": record.title or "",
        "text": record.text_content or "",
        "author": record.author_display_name or "",
        "author_id": str(record.author_platform_id or ""),
        "url": record.url or "",
        "published_at": pub.isoformat() if pub else "",
        "collected_at": col.isoformat() if col else "",
        "language": record.language or "",
        "engagement_score": record.engagement_score or 0,
        "search_terms_matched": terms if isinstance(terms, list) else [],
        "run_id": str(record.collection_run_id or ""),
        "metadata": record.raw_metadata or {},
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
    q: Optional[str] = Query(default=None, description="Full-text search query."),
    platform: Optional[str] = Query(default=None),
    arena: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    language: Optional[str] = Query(default=None),
    search_term: Optional[str] = Query(default=None),
    run_id: Optional[uuid.UUID] = Query(default=None),
    mode: Optional[str] = Query(default=None, description="Collection mode filter: 'batch' or 'live'."),
    query_design_id: Optional[uuid.UUID] = Query(default=None, description="Active query design for quick-add actor flow."),
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
        run_id: Optional collection run UUID filter.

    Returns:
        ``TemplateResponse`` rendering ``content/browser.html``.
    """
    from issue_observatory.api.main import templates  # noqa: PLC0415

    if templates is None:
        raise HTTPException(status_code=500, detail="Template engine not initialised.")

    date_from_dt = _parse_date_param(date_from)
    date_to_dt = _parse_date_param(date_to)

    stmt = _build_browse_stmt(
        current_user=current_user,
        q=q,
        platform=platform,
        arena=arena,
        date_from=date_from_dt,
        date_to=date_to_dt,
        language=language,
        search_term=search_term,
        run_id=run_id,
        mode=mode,
        cursor_published_at=None,
        cursor_id=None,
        limit=_BROWSE_LIMIT,
    )
    result = await db.execute(stmt)
    records = list(result.mappings().all())

    cursor: Optional[str] = None
    if len(records) == _BROWSE_LIMIT:
        last = records[-1]
        cursor = _encode_cursor(last["published_at"], last["id"])

    # Fetch recent collection runs for the sidebar run selector (last 20).
    recent_runs = await _fetch_recent_runs(db, current_user)

    # Total count (approximate — count without cursor/limit for display).
    total_count = await _count_matching(
        db=db,
        current_user=current_user,
        q=q,
        platform=platform,
        arena=arena,
        date_from=date_from_dt,
        date_to=date_to_dt,
        language=language,
        search_term=search_term,
        run_id=run_id,
        mode=mode,
    )

    filter_ctx = {
        "q": q or "",
        "platform": platform or "",
        "arenas": [arena] if arena else [],
        "date_from": date_from or "",
        "date_to": date_to or "",
        "language": language or "",
        "search_term": search_term or "",
        "run_id": str(run_id) if run_id else "",
        "mode": mode or "",
    }

    return templates.TemplateResponse(
        "content/browser.html",
        {
            "request": request,
            "records": [_orm_row_to_template_dict(r) for r in records],
            "total_count": total_count,
            "recent_runs": recent_runs,
            "filter": filter_ctx,
            "cursor": cursor or "",
            "active_query_design_id": str(query_design_id) if query_design_id else "",
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
    cursor: Optional[str] = Query(default=None, description="Opaque keyset cursor."),
    q: Optional[str] = Query(default=None),
    arenas: Optional[list[str]] = Query(default=None),
    platform: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    language: Optional[str] = Query(default=None),
    search_term: Optional[str] = Query(default=None),
    run_id: Optional[uuid.UUID] = Query(default=None),
    mode: Optional[str] = Query(default=None, description="Collection mode filter: 'batch' or 'live'."),
    offset: int = Query(default=0, ge=0, description="Running total of rows already sent."),
    limit: int = Query(default=_BROWSE_LIMIT, ge=1, le=_MAX_LIMIT),
) -> HTMLResponse:
    """Return an HTMX HTML fragment containing ``<tr>`` rows for the content table.

    Implements keyset pagination on ``(published_at DESC, id DESC)``.  Each
    response appends rows into ``#records-tbody`` via ``hx-swap="beforeend"``.
    Once the cumulative ``offset`` reaches 2000, an empty sentinel is returned
    so that HTMX stops triggering further loads.

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

    Returns:
        ``HTMLResponse`` containing ``<tr>`` elements plus an optional
        sentinel ``<tr hx-trigger="revealed">`` for further loading.
    """
    from issue_observatory.api.main import templates  # noqa: PLC0415

    if templates is None:
        raise HTTPException(status_code=500, detail="Template engine not initialised.")

    # Enforce hard cap: if caller has already received 2000 rows, return nothing.
    if offset >= _BROWSE_CAP:
        return HTMLResponse("", status_code=200)

    remaining = min(limit, _BROWSE_CAP - offset)

    cursor_published_at: Optional[datetime] = None
    cursor_id_val: Optional[uuid.UUID] = None
    if cursor:
        cursor_published_at, cursor_id_val = _decode_cursor(cursor)

    date_from_dt = _parse_date_param(date_from)
    date_to_dt = _parse_date_param(date_to)

    # Merge arenas multi-value list with singular platform/arena params.
    arena_filter: Optional[str] = None
    arenas_list: list[str] = arenas or []
    if len(arenas_list) == 1:
        arena_filter = arenas_list[0]
    # When multiple arenas checked we build an IN filter below.

    stmt = _build_browse_stmt(
        current_user=current_user,
        q=q,
        platform=platform,
        arena=arena_filter if len(arenas_list) <= 1 else None,
        date_from=date_from_dt,
        date_to=date_to_dt,
        language=language,
        search_term=search_term,
        run_id=run_id,
        mode=mode,
        cursor_published_at=cursor_published_at,
        cursor_id=cursor_id_val,
        limit=remaining,
    )

    # Multiple arena filter (IN clause) applied post-base when >1 selected.
    if len(arenas_list) > 1:
        stmt = stmt.where(UniversalContentRecord.arena.in_(arenas_list))

    result = await db.execute(stmt)
    records = list(result.mappings().all())

    new_offset = offset + len(records)
    next_cursor: Optional[str] = None
    if len(records) == remaining and new_offset < _BROWSE_CAP:
        last = records[-1]
        next_cursor = _encode_cursor(last["published_at"], last["id"])

    template_records = [_orm_row_to_template_dict(r) for r in records]

    html = templates.get_template("_fragments/content_table_body.html").render(
        {
            "request": request,
            "records": template_records,
            "next_cursor": next_cursor or "",
            "new_offset": new_offset,
            "browse_cap": _BROWSE_CAP,
        }
    )
    return HTMLResponse(html, status_code=200)


# ---------------------------------------------------------------------------
# Search-term filter options (HTMX fragment for content browser dropdown)
# ---------------------------------------------------------------------------


@router.get("/search-terms")
async def get_search_terms_for_run(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    run_id: Optional[uuid.UUID] = Query(default=None, description="Collection run UUID."),
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
            WHERE cr.collection_run_id = :run_id
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
# Discovered links — GR-22 cross-platform link mining
# Must be declared BEFORE the parametric /{record_id} route so that FastAPI
# does not try to parse "discovered-links" as a UUID.
# ---------------------------------------------------------------------------


@router.get("/discovered-links")
async def get_discovered_links(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    query_design_id: Optional[uuid.UUID] = Query(
        default=None,
        description=(
            "Optional UUID of a query design to scope to. "
            "If omitted, mines all content from all the current user's query designs."
        ),
    ),
    platform: Optional[str] = Query(
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
    from issue_observatory.analysis.link_miner import LinkMiner  # noqa: PLC0415

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
# Detail — HTML panel or standalone page
# ---------------------------------------------------------------------------


@router.get("/{record_id}")
async def get_content_record_html(
    record_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    hx_request: Optional[str] = Header(default=None, alias="HX-Request"),
) -> Response:
    """Return a content record as an HTML detail panel or standalone page.

    When the request includes the ``HX-Request`` header (HTMX partial load),
    the template is rendered without ``standalone=True`` so it outputs only
    the inner panel markup.  Otherwise the full ``base.html`` wrapper is used.

    Args:
        record_id: UUID of the target content record.
        request: The incoming HTTP request.
        db: Injected async database session.
        current_user: The authenticated, active user making the request.
        hx_request: Value of the ``HX-Request`` header (injected by FastAPI).

    Returns:
        ``TemplateResponse`` rendering ``content/record_detail.html``.

    Raises:
        HTTPException 404: If the record does not exist or is not accessible
            by the current user.
    """
    from issue_observatory.api.main import templates  # noqa: PLC0415

    if templates is None:
        raise HTTPException(status_code=500, detail="Template engine not initialised.")

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

    db_result = await db.execute(stmt)
    orm_record = db_result.scalar_one_or_none()

    if orm_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Content record '{record_id}' not found.",
        )

    record_ctx = _orm_to_detail_dict(orm_record)
    is_panel = hx_request is not None

    return templates.TemplateResponse(
        "content/record_detail.html",
        {
            "request": request,
            "record": record_ctx,
            "standalone": not is_panel,
        },
    )


# ---------------------------------------------------------------------------
# Export — synchronous (up to 10 K records, returns file directly)
# ---------------------------------------------------------------------------


@router.get("/export")
@limiter.limit("10/minute")
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
        network_type: GEXF network type (ignored for non-GEXF formats).
            One of ``actor``, ``term``, ``bipartite``.  Defaults to
            ``"actor"``.
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
        HTTPException 400: If the requested format is not supported, or if
            ``network_type`` is invalid for GEXF exports.
        HTTPException 500: If serialization fails due to a missing optional
            dependency (openpyxl / pyarrow not installed).
    """
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
        elif format == "ris":
            file_bytes = exporter.export_ris(records)
        elif format == "bibtex":
            file_bytes = exporter.export_bibtex(records)
        else:  # gexf
            file_bytes = await exporter.export_gexf(records, network_type=network_type)
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
        network_type: GEXF network type (ignored for non-GEXF formats).
            One of ``actor``, ``term``, ``bipartite``.  Defaults to
            ``"actor"``.
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
        HTTPException 400: If the format is not supported, or if
            ``network_type`` is invalid for GEXF exports.
    """
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
