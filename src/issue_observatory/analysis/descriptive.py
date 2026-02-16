"""Descriptive statistics for collected content.

Computes volume, reach, engagement distributions, and temporal trends
across a collection run or query design.

All public functions are async and accept an ``AsyncSession`` plus optional
filter parameters.  They return plain Python dicts/lists so callers can pass
the results directly to FastAPI's JSON serializer without further conversion.

Design notes
------------
- Queries use SQLAlchemy ``text()`` for PostgreSQL-specific constructs that have
  no portable ORM equivalent: ``date_trunc``, ``unnest``,
  ``percentile_cont … WITHIN GROUP``.
- Filter clauses are appended conditionally — only non-None parameters generate
  a WHERE predicate.  All filter columns are covered by existing B-tree or GIN
  indexes on ``content_records``.
- The ``get_run_summary()`` function joins ``collection_runs`` and
  ``collection_tasks`` directly; all other functions query only
  ``content_records``.
- Datetime objects in returned dicts are ISO 8601 strings so callers do not
  need a custom JSON encoder.

Owned by the DB Engineer.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Typed container for the API layer
# ---------------------------------------------------------------------------


@dataclass
class DescriptiveStats:
    """Aggregated descriptive statistics returned to the API layer.

    Populated by the individual query functions below and serialized to JSON
    by the route handler.  All datetime values are stored as ISO 8601 strings.
    """

    volume_over_time: list[dict[str, Any]] = field(default_factory=list)
    top_actors: list[dict[str, Any]] = field(default_factory=list)
    top_terms: list[dict[str, Any]] = field(default_factory=list)
    engagement_distribution: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_VALID_GRANULARITIES = frozenset({"hour", "day", "week", "month"})


def _dt_iso(value: Any) -> Any:
    """Convert a datetime to an ISO 8601 string; pass everything else through."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _build_content_filters(
    query_design_id: uuid.UUID | None,
    run_id: uuid.UUID | None,
    arena: str | None,
    platform: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    params: dict,
) -> str:
    """Build a SQL WHERE clause fragment for content_records filters.

    Appends bind parameter values to *params* in place.

    Returns:
        A SQL string fragment starting with ``WHERE`` (or an empty string if no
        filters are active).
    """
    clauses: list[str] = []

    if query_design_id is not None:
        clauses.append("query_design_id = :query_design_id")
        params["query_design_id"] = str(query_design_id)

    if run_id is not None:
        clauses.append("collection_run_id = :run_id")
        params["run_id"] = str(run_id)

    if arena is not None:
        clauses.append("arena = :arena")
        params["arena"] = arena

    if platform is not None:
        clauses.append("platform = :platform")
        params["platform"] = platform

    if date_from is not None:
        clauses.append("published_at >= :date_from")
        params["date_from"] = date_from

    if date_to is not None:
        clauses.append("published_at <= :date_to")
        params["date_to"] = date_to

    if not clauses:
        return ""
    return "WHERE " + " AND ".join(clauses)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_volume_over_time(
    db: AsyncSession,
    query_design_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    arena: str | None = None,
    platform: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    granularity: str = "day",
) -> list[dict]:
    """Content volume over time, optionally broken down by arena.

    Args:
        db: Active async database session.
        query_design_id: Restrict to records belonging to this query design.
        run_id: Restrict to records collected in this collection run.
        arena: Restrict to a single arena (e.g. ``"news"``, ``"social"``).
        platform: Restrict to a single platform (e.g. ``"reddit"``).
        date_from: Inclusive lower bound on ``published_at``.
        date_to: Inclusive upper bound on ``published_at``.
        granularity: Time bucket size — one of ``"hour"``, ``"day"``,
            ``"week"``, ``"month"``.

    Returns:
        A list of dicts, one per time-period/arena combination, sorted by
        period ascending::

            [
              {
                "period": "2026-02-01T00:00:00+00:00",
                "count": 423,
                "arenas": {"news": 200, "social": 223},
              },
              ...
            ]

    Raises:
        ValueError: If *granularity* is not one of the accepted values.
    """
    if granularity not in _VALID_GRANULARITIES:
        raise ValueError(
            f"Invalid granularity {granularity!r}. "
            f"Must be one of: {sorted(_VALID_GRANULARITIES)}"
        )

    params: dict[str, Any] = {}
    where = _build_content_filters(
        query_design_id, run_id, arena, platform, date_from, date_to, params
    )

    # The granularity value is interpolated directly into the SQL string, not
    # as a bind parameter, because date_trunc requires a literal string for
    # the field argument.  It is safe here because we validated it against
    # _VALID_GRANULARITIES above.
    extra = "AND published_at IS NOT NULL" if where else "WHERE published_at IS NOT NULL"

    sql = text(
        f"""
        SELECT
            date_trunc('{granularity}', published_at) AS period,
            arena,
            COUNT(*) AS cnt
        FROM content_records
        {where}
        {extra}
        GROUP BY 1, arena
        ORDER BY 1 ASC, arena
        """
    )

    result = await db.execute(sql, params)
    rows = result.fetchall()

    # Aggregate per-period totals and per-arena counts.
    # Use an ordered dict keyed by period ISO string to preserve sort order.
    aggregated: OrderedDict[str, dict] = OrderedDict()
    for row in rows:
        period_key = _dt_iso(row.period)
        if period_key not in aggregated:
            aggregated[period_key] = {"period": period_key, "count": 0, "arenas": {}}
        aggregated[period_key]["count"] += row.cnt
        aggregated[period_key]["arenas"][row.arena] = row.cnt

    return list(aggregated.values())


async def get_top_actors(
    db: AsyncSession,
    query_design_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    platform: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 20,
) -> list[dict]:
    """Top authors by post volume and total engagement.

    Engagement is defined as the sum of ``likes_count + shares_count +
    comments_count`` (all nullable; treated as 0 when NULL via COALESCE).

    Args:
        db: Active async database session.
        query_design_id: Restrict to records belonging to this query design.
        run_id: Restrict to records collected in this collection run.
        platform: Restrict to a single platform.
        date_from: Inclusive lower bound on ``published_at``.
        date_to: Inclusive upper bound on ``published_at``.
        limit: Maximum number of actors to return (default 20).

    Returns:
        A list of dicts ordered by ``count`` descending::

            [
              {
                "author_display_name": "DR Nyheder",
                "pseudonymized_author_id": "abc123…",
                "platform": "facebook",
                "count": 150,
                "total_engagement": 42000,
              },
              ...
            ]
    """
    params: dict[str, Any] = {"limit": limit}
    # Note: arena filter is not exposed on this function — topic not relevant.
    where = _build_content_filters(
        query_design_id, run_id, None, platform, date_from, date_to, params
    )
    null_filter = (
        "AND pseudonymized_author_id IS NOT NULL"
        if where
        else "WHERE pseudonymized_author_id IS NOT NULL"
    )

    sql = text(
        f"""
        SELECT
            pseudonymized_author_id,
            author_display_name,
            platform,
            COUNT(*) AS cnt,
            SUM(
                COALESCE(likes_count, 0)
                + COALESCE(shares_count, 0)
                + COALESCE(comments_count, 0)
            ) AS total_engagement
        FROM content_records
        {where}
        {null_filter}
        GROUP BY pseudonymized_author_id, author_display_name, platform
        ORDER BY cnt DESC
        LIMIT :limit
        """
    )

    result = await db.execute(sql, params)
    rows = result.fetchall()

    return [
        {
            "author_display_name": row.author_display_name,
            "pseudonymized_author_id": row.pseudonymized_author_id,
            "platform": row.platform,
            "count": row.cnt,
            "total_engagement": int(row.total_engagement or 0),
        }
        for row in rows
    ]


async def get_top_terms(
    db: AsyncSession,
    query_design_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 20,
) -> list[dict]:
    """Top search terms by match frequency across content records.

    Uses ``unnest(search_terms_matched)`` to expand the array column so each
    term counts independently.

    Args:
        db: Active async database session.
        query_design_id: Restrict to records belonging to this query design.
        run_id: Restrict to records collected in this collection run.
        date_from: Inclusive lower bound on ``published_at``.
        date_to: Inclusive upper bound on ``published_at``.
        limit: Maximum number of terms to return (default 20).

    Returns:
        A list of dicts ordered by ``count`` descending::

            [{"term": "klimaforandringer", "count": 834}, ...]
    """
    params: dict[str, Any] = {"limit": limit}
    # Build filters without arena/platform — terms span all arenas.
    where = _build_content_filters(
        query_design_id, run_id, None, None, date_from, date_to, params
    )
    null_filter = (
        "AND search_terms_matched IS NOT NULL"
        if where
        else "WHERE search_terms_matched IS NOT NULL"
    )

    sql = text(
        f"""
        SELECT
            term,
            COUNT(*) AS cnt
        FROM content_records,
             unnest(search_terms_matched) AS term
        {where}
        {null_filter}
        GROUP BY term
        ORDER BY cnt DESC
        LIMIT :limit
        """
    )

    result = await db.execute(sql, params)
    rows = result.fetchall()

    return [{"term": row.term, "count": row.cnt} for row in rows]


async def get_engagement_distribution(
    db: AsyncSession,
    query_design_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    arena: str | None = None,
    platform: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict:
    """Statistical distribution of per-post engagement metrics.

    Uses PostgreSQL ordered-set aggregate functions:
    - ``percentile_cont(0.5) WITHIN GROUP`` for the median
    - ``percentile_cont(0.95) WITHIN GROUP`` for the 95th percentile

    Args:
        db: Active async database session.
        query_design_id: Restrict to records belonging to this query design.
        run_id: Restrict to records collected in this collection run.
        arena: Restrict to a single arena.
        platform: Restrict to a single platform.
        date_from: Inclusive lower bound on ``published_at``.
        date_to: Inclusive upper bound on ``published_at``.

    Returns:
        A dict keyed by metric name, each containing summary statistics::

            {
              "likes":    {"mean": 12.3, "median": 4.0, "p95": 87.0, "max": 5000},
              "shares":   {"mean": 2.1,  "median": 0.0, "p95": 14.0, "max": 300},
              "comments": {"mean": 5.7,  "median": 2.0, "p95": 31.0, "max": 1200},
              "views":    {"mean": 890.0,"median": 120.0,"p95": 4500.0,"max": 250000},
            }

        Returns an empty dict if no records match the filters.
    """
    params: dict[str, Any] = {}
    where = _build_content_filters(
        query_design_id, run_id, arena, platform, date_from, date_to, params
    )

    sql = text(
        f"""
        SELECT
            AVG(likes_count)                                                 AS likes_mean,
            percentile_cont(0.5)  WITHIN GROUP (ORDER BY likes_count)       AS likes_median,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY likes_count)       AS likes_p95,
            MAX(likes_count)                                                 AS likes_max,

            AVG(shares_count)                                                AS shares_mean,
            percentile_cont(0.5)  WITHIN GROUP (ORDER BY shares_count)      AS shares_median,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY shares_count)      AS shares_p95,
            MAX(shares_count)                                                AS shares_max,

            AVG(comments_count)                                              AS comments_mean,
            percentile_cont(0.5)  WITHIN GROUP (ORDER BY comments_count)    AS comments_median,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY comments_count)    AS comments_p95,
            MAX(comments_count)                                              AS comments_max,

            AVG(views_count)                                                 AS views_mean,
            percentile_cont(0.5)  WITHIN GROUP (ORDER BY views_count)       AS views_median,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY views_count)       AS views_p95,
            MAX(views_count)                                                 AS views_max
        FROM content_records
        {where}
        """
    )

    result = await db.execute(sql, params)
    row = result.fetchone()

    if row is None:
        return {}

    def _round(value: Any, decimals: int = 2) -> float | None:
        if value is None:
            return None
        return round(float(value), decimals)

    def _int_or_none(value: Any) -> int | None:
        if value is None:
            return None
        return int(value)

    return {
        "likes": {
            "mean": _round(row.likes_mean),
            "median": _round(row.likes_median),
            "p95": _round(row.likes_p95),
            "max": _int_or_none(row.likes_max),
        },
        "shares": {
            "mean": _round(row.shares_mean),
            "median": _round(row.shares_median),
            "p95": _round(row.shares_p95),
            "max": _int_or_none(row.shares_max),
        },
        "comments": {
            "mean": _round(row.comments_mean),
            "median": _round(row.comments_median),
            "p95": _round(row.comments_p95),
            "max": _int_or_none(row.comments_max),
        },
        "views": {
            "mean": _round(row.views_mean),
            "median": _round(row.views_median),
            "p95": _round(row.views_p95),
            "max": _int_or_none(row.views_max),
        },
    }


async def get_run_summary(
    db: AsyncSession,
    run_id: uuid.UUID,
) -> dict:
    """High-level statistics for a single collection run.

    Aggregates:
    - Total records collected (from ``content_records``)
    - Per-arena breakdown (record count + ``records_collected`` from task)
    - Date range of ``published_at`` across all collected records
    - Credits spent (from ``collection_runs.credits_spent``)
    - Run metadata: mode, status, started_at, completed_at

    Args:
        db: Active async database session.
        run_id: The collection run to summarize.

    Returns:
        A dict with run metadata and aggregated statistics, or an empty dict
        if the run does not exist::

            {
              "run_id": "...",
              "status": "completed",
              "mode": "batch",
              "started_at": "2026-02-15T10:00:00+00:00",
              "completed_at": "2026-02-15T10:47:32+00:00",
              "credits_spent": 240,
              "total_records": 5812,
              "published_at_min": "2026-01-01T00:00:00+00:00",
              "published_at_max": "2026-02-14T23:59:59+00:00",
              "by_arena": [
                {"arena": "news", "record_count": 2100, "tasks_records_collected": 2100},
                ...
              ],
            }
    """
    run_sql = text(
        """
        SELECT
            id,
            status,
            mode,
            started_at,
            completed_at,
            credits_spent,
            records_collected
        FROM collection_runs
        WHERE id = :run_id
        """
    )
    run_result = await db.execute(run_sql, {"run_id": str(run_id)})
    run_row = run_result.fetchone()

    if run_row is None:
        logger.warning("get_run_summary: run not found", run_id=str(run_id))
        return {}

    # Aggregate content records for this run.
    content_sql = text(
        """
        SELECT
            COUNT(*)          AS total_records,
            MIN(published_at) AS published_at_min,
            MAX(published_at) AS published_at_max
        FROM content_records
        WHERE collection_run_id = :run_id
        """
    )
    content_result = await db.execute(content_sql, {"run_id": str(run_id)})
    content_row = content_result.fetchone()

    # Per-arena breakdown: sum records_collected from collection_tasks.
    arena_sql = text(
        """
        SELECT
            cr.arena,
            COUNT(c.id)                         AS record_count,
            COALESCE(SUM(ct.records_collected), 0) AS tasks_records_collected
        FROM content_records c
        JOIN collection_tasks ct
            ON ct.collection_run_id = c.collection_run_id
            AND ct.arena = c.arena
        RIGHT JOIN (
            SELECT DISTINCT arena
            FROM collection_tasks
            WHERE collection_run_id = :run_id
        ) cr ON cr.arena = c.arena
            AND c.collection_run_id = :run_id
        GROUP BY cr.arena
        ORDER BY record_count DESC
        """
    )
    arena_result = await db.execute(arena_sql, {"run_id": str(run_id)})
    arena_rows = arena_result.fetchall()

    return {
        "run_id": str(run_row.id),
        "status": run_row.status,
        "mode": run_row.mode,
        "started_at": _dt_iso(run_row.started_at),
        "completed_at": _dt_iso(run_row.completed_at),
        "credits_spent": run_row.credits_spent,
        "total_records": content_row.total_records if content_row else 0,
        "published_at_min": _dt_iso(content_row.published_at_min) if content_row else None,
        "published_at_max": _dt_iso(content_row.published_at_max) if content_row else None,
        "by_arena": [
            {
                "arena": row.arena,
                "record_count": row.record_count,
                "tasks_records_collected": int(row.tasks_records_collected),
            }
            for row in arena_rows
        ],
    }
