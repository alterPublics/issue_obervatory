"""Cross-arena temporal propagation analysis queries.

GR-08 — Provides query functions over the propagation enrichment data
written by :class:`~issue_observatory.analysis.enrichments.propagation_detector.PropagationEnricher`
and persisted by
:func:`~issue_observatory.core.deduplication.run_propagation_analysis`.

All public functions are async and accept an ``AsyncSession`` plus optional
filter parameters.  They return plain Python dicts/lists so callers can pass
the results directly to FastAPI's JSON serialiser without further conversion.

Design notes
------------
- Propagation enrichment data is stored in
  ``content_records.raw_metadata -> 'enrichments' -> 'propagation'`` as a
  JSONB sub-object.  We use the PostgreSQL ``->`` / ``->>`` operators and
  ``jsonb_array_length`` to filter and sort within the query rather than
  loading all records into Python.
- Queries are scoped to the *canonical* (origin) record of each cluster
  (``is_origin = true``) to avoid returning the same cluster multiple times.
- All datetime values in returned dicts are ISO 8601 strings.

Owned by the Core Application Engineer.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


async def get_propagation_flows(
    session: AsyncSession,
    collection_run_id: uuid.UUID | None = None,
    query_design_id: uuid.UUID | None = None,
    min_arenas_reached: int = 2,
    limit: int = 100,
) -> list[dict]:
    """Return top propagation flows sorted by number of arenas reached.

    A "propagation flow" is a near-duplicate cluster where content first
    appeared in one arena and subsequently spread to one or more other arenas.
    This function returns the origin record for each qualifying cluster,
    enriched with the full propagation sequence stored in
    ``raw_metadata.enrichments.propagation``.

    Only records marked as ``is_origin = true`` in their propagation
    enrichment are returned (one row per cluster).

    Args:
        session: Active async database session.
        collection_run_id: Restrict flows to a specific collection run.
            When ``None``, all enriched records are included.
        query_design_id: Restrict flows to a specific query design.
        min_arenas_reached: Minimum number of distinct arenas the cluster
            must have reached to appear in the results.  Defaults to 2.
        limit: Maximum number of flows to return, ordered by
            ``total_arenas_reached`` descending.  Defaults to 100.

    Returns:
        A list of dicts ordered by ``total_arenas_reached`` descending, then
        by ``max_lag_hours`` descending::

            [
              {
                "cluster_id": "...",
                "record_id": "...",
                "arena": "gdelt",
                "platform": "gdelt",
                "origin_published_at": "2026-02-19T14:00:00+00:00",
                "total_arenas_reached": 4,
                "max_lag_hours": 2.5,
                "propagation_sequence": [
                    {
                        "arena": "news",
                        "platform": "dr",
                        "published_at": "...",
                        "lag_minutes": 90.0
                    },
                    ...
                ],
                "computed_at": "2026-02-19T16:00:00+00:00"
              },
              ...
            ]

        Returns an empty list when no propagation-enriched records match the
        filters.
    """
    params: dict[str, Any] = {
        "min_arenas": min_arenas_reached,
        "limit": limit,
    }

    # Build optional WHERE predicates on top of the base conditions.
    extra_conditions: list[str] = []
    if collection_run_id is not None:
        extra_conditions.append("AND collection_run_id = :run_id")
        params["run_id"] = str(collection_run_id)
    if query_design_id is not None:
        extra_conditions.append("AND query_design_id = :query_design_id")
        params["query_design_id"] = str(query_design_id)

    extra_sql = "\n        ".join(extra_conditions)

    # We query records where:
    #   1. raw_metadata -> 'enrichments' -> 'propagation' exists.
    #   2. The propagation 'is_origin' flag is true (one row per cluster).
    #   3. 'total_arenas_reached' meets the minimum threshold.
    # All filtering is done in SQL so we only pull back qualifying rows.
    sql = text(
        f"""
        SELECT
            id,
            arena,
            platform,
            raw_metadata -> 'enrichments' -> 'propagation' AS propagation
        FROM content_records
        WHERE
            raw_metadata -> 'enrichments' -> 'propagation' IS NOT NULL
            AND (raw_metadata -> 'enrichments' -> 'propagation' ->> 'is_origin')::boolean = true
            AND (
                raw_metadata -> 'enrichments' -> 'propagation' ->> 'total_arenas_reached'
            )::int >= :min_arenas
        {extra_sql}
        ORDER BY
            (raw_metadata -> 'enrichments' -> 'propagation' ->> 'total_arenas_reached')::int DESC,
            (raw_metadata -> 'enrichments' -> 'propagation' ->> 'max_lag_hours')::float DESC NULLS LAST
        LIMIT :limit
        """
    )

    result = await session.execute(sql, params)
    rows = result.fetchall()

    flows: list[dict] = []
    for row in rows:
        propagation: dict[str, Any] = row.propagation or {}
        flows.append(
            {
                "cluster_id": propagation.get("cluster_id"),
                "record_id": str(row.id),
                "arena": row.arena,
                "platform": row.platform,
                "origin_published_at": propagation.get("origin_published_at"),
                "total_arenas_reached": propagation.get("total_arenas_reached"),
                "max_lag_hours": propagation.get("max_lag_hours"),
                "propagation_sequence": propagation.get("propagation_sequence", []),
                "computed_at": propagation.get("computed_at"),
            }
        )

    logger.info(
        "propagation.get_flows",
        flows_returned=len(flows),
        min_arenas_reached=min_arenas_reached,
        collection_run_id=str(collection_run_id) if collection_run_id else None,
        query_design_id=str(query_design_id) if query_design_id else None,
    )
    return flows
