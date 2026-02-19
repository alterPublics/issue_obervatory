"""Coordinated inauthentic behaviour (CIB) analysis queries.

GR-11 — Provides query functions over the coordination enrichment data written
by :class:`~issue_observatory.analysis.enrichments.coordination_detector.CoordinationDetector`
and persisted by
:meth:`~issue_observatory.core.deduplication.DeduplicationService.run_coordination_analysis`.

All public functions are async and accept an ``AsyncSession`` plus optional
filter parameters.  They return plain Python dicts/lists so callers can pass
results directly to FastAPI's JSON serialiser without further conversion.

Design notes
------------
- Coordination enrichment data is stored in
  ``content_records.raw_metadata -> 'enrichments' -> 'coordination'`` as a
  JSONB sub-object.  SQL JSONB operators are used to filter and sort within
  the query rather than loading all records into Python.
- Queries return one row per cluster by finding the record with the earliest
  timestamp within the flagged window (i.e., the row that has the minimum
  ``earliest_in_window`` value in the cluster).  This is approximated by
  ordering by ``earliest_in_window`` ascending and using ``DISTINCT ON
  (cluster_id)`` — which PostgreSQL evaluates deterministically because of the
  leading ORDER BY.
- All datetime values in returned dicts are ISO 8601 strings already stored
  by the enricher.

Owned by the Core Application Engineer.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


async def get_coordination_events(
    session: AsyncSession,
    collection_run_id: uuid.UUID | None = None,
    query_design_id: uuid.UUID | None = None,
    min_score: float = 0.5,
    limit: int = 50,
) -> list[dict]:
    """Return clusters flagged as potential coordination events, sorted by score.

    Queries ``content_records`` for records where
    ``raw_metadata.enrichments.coordination.flagged = true`` and
    ``coordination_score >= min_score``, returning one summary dict per
    distinct cluster ordered by ``coordination_score`` descending.

    One representative record per cluster is returned (the record carrying the
    highest ``coordination_score`` value for that cluster — ties are broken by
    the PostgreSQL ``DISTINCT ON`` ordering).

    Args:
        session: Active async database session.
        collection_run_id: Restrict results to a specific collection run.
            When ``None``, all enriched records are included.
        query_design_id: Restrict results to a specific query design.
        min_score: Minimum ``coordination_score`` (0–1) a cluster must have
            to appear in the results.  Defaults to 0.5.
        limit: Maximum number of distinct cluster summaries to return, ordered
            by ``coordination_score`` descending.  Defaults to 50.

    Returns:
        A list of dicts ordered by ``coordination_score`` descending::

            [
              {
                "cluster_id": "...",
                "record_id": "...",
                "flagged": true,
                "distinct_authors_in_window": 12,
                "time_window_hours": 1.0,
                "coordination_score": 0.85,
                "earliest_in_window": "2026-02-19T14:00:00+00:00",
                "latest_in_window": "2026-02-19T14:45:00+00:00",
                "platforms_involved": ["gab", "reddit", "telegram"],
                "computed_at": "2026-02-19T16:00:00+00:00"
              },
              ...
            ]

        Returns an empty list when no coordination-enriched records match the
        filters.
    """
    params: dict[str, Any] = {
        "min_score": min_score,
        "limit": limit,
    }

    extra_conditions: list[str] = []
    if collection_run_id is not None:
        extra_conditions.append("AND collection_run_id = :run_id")
        params["run_id"] = str(collection_run_id)
    if query_design_id is not None:
        extra_conditions.append("AND query_design_id = :query_design_id")
        params["query_design_id"] = str(query_design_id)

    extra_sql = "\n            ".join(extra_conditions)

    # Use DISTINCT ON (cluster_id) to return one row per cluster.  The leading
    # ORDER BY clause drives both the DISTINCT ON selection and the final sort:
    # PostgreSQL selects the first row in each cluster group after applying
    # the ORDER BY, so ordering by cluster_id then score DESC means we get the
    # row with the highest score for each cluster.  A wrapping SELECT then
    # re-sorts by score DESC for the final result set.
    sql = text(
        f"""
        SELECT *
        FROM (
            SELECT DISTINCT ON (
                raw_metadata -> 'enrichments' -> 'coordination' ->> 'cluster_id'
            )
                id,
                raw_metadata -> 'enrichments' -> 'coordination' AS coordination
            FROM content_records
            WHERE
                raw_metadata -> 'enrichments' -> 'coordination' IS NOT NULL
                AND (
                    raw_metadata -> 'enrichments' -> 'coordination' ->> 'flagged'
                )::boolean = true
                AND (
                    raw_metadata -> 'enrichments' -> 'coordination' ->> 'coordination_score'
                )::float >= :min_score
                {extra_sql}
            ORDER BY
                raw_metadata -> 'enrichments' -> 'coordination' ->> 'cluster_id',
                (
                    raw_metadata -> 'enrichments' -> 'coordination' ->> 'coordination_score'
                )::float DESC
        ) subq
        ORDER BY
            (coordination ->> 'coordination_score')::float DESC
        LIMIT :limit
        """
    )

    result = await session.execute(sql, params)
    rows = result.fetchall()

    events: list[dict] = []
    for row in rows:
        coord: dict[str, Any] = row.coordination or {}
        events.append(
            {
                "cluster_id": coord.get("cluster_id"),
                "record_id": str(row.id),
                "flagged": coord.get("flagged", True),
                "distinct_authors_in_window": coord.get("distinct_authors_in_window"),
                "time_window_hours": coord.get("time_window_hours"),
                "coordination_score": coord.get("coordination_score"),
                "earliest_in_window": coord.get("earliest_in_window"),
                "latest_in_window": coord.get("latest_in_window"),
                "platforms_involved": coord.get("platforms_involved", []),
                "computed_at": coord.get("computed_at"),
            }
        )

    logger.info(
        "coordination.get_events",
        events_returned=len(events),
        min_score=min_score,
        collection_run_id=str(collection_run_id) if collection_run_id else None,
        query_design_id=str(query_design_id) if query_design_id else None,
    )
    return events
