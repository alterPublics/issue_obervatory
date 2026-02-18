"""Network analysis for actor interaction and term co-occurrence graphs.

Builds actor co-occurrence networks, term co-occurrence networks, cross-platform
actor mappings, and bipartite actor-term networks from collected content records.

All public functions are async and accept an ``AsyncSession`` plus optional
filter parameters.  They return plain Python dicts (JSON-serializable) in a
graph structure suitable for direct serialization into GEXF or JSON network
formats.

Graph dict format (shared across all network functions):
    {
      "nodes": [
        {"id": str, "label": str, "type": str, ...extra attributes},
        ...
      ],
      "edges": [
        {"source": str, "target": str, "weight": int, ...extra attributes},
        ...
      ]
    }

Design notes
------------
- Queries use SQLAlchemy ``text()`` for PostgreSQL-specific constructs:
  ``unnest``, array self-joins, lateral joins, and CTEs.
- Co-occurrence pairs are computed entirely in SQL via self-joins on the
  content_records table to avoid loading large intermediate result sets into
  Python memory.
- All batch data loads happen in a single query per function; graph metrics
  (degree computation) are done in Python after the SQL fetch.
- Empty result sets return ``{"nodes": [], "edges": []}`` or ``[]`` depending
  on the function return type.
- UUID bind parameters are cast to strings to satisfy asyncpg.

Owned by the DB Engineer.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.analysis._filters import build_content_filters

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _empty_graph() -> dict:
    """Return an empty graph dict."""
    return {"nodes": [], "edges": []}


def _build_run_filter(
    query_design_id: uuid.UUID | None,
    run_id: uuid.UUID | None,
    arena: str | None,
    platform: str | None,
    date_from: Any,
    date_to: Any,
    params: dict,
    table_alias: str = "",
) -> list[str]:
    """Build a list of SQL WHERE clause predicates for content_records.

    Delegates to :func:`~issue_observatory.analysis._filters.build_content_filters`
    which centralises filter logic — including the duplicate exclusion clause
    ``(raw_metadata->>'duplicate_of') IS NULL`` — so that network analysis
    consistently excludes duplicate-flagged records.

    Args:
        table_alias: Optional table alias prefix (e.g. ``"a."``).  Include
            trailing dot.

    Returns:
        List of SQL predicate strings (no leading ``WHERE``).  Never empty
        because the duplicate exclusion predicate is always present.
    """
    return build_content_filters(
        query_design_id, run_id, arena, platform, date_from, date_to, params,
        table_alias=table_alias,
    )


def _where(clauses: list[str]) -> str:
    """Join clause list into a WHERE fragment (or empty string)."""
    if not clauses:
        return ""
    return "WHERE " + " AND ".join(clauses)


def _and(clauses: list[str]) -> str:
    """Join clause list into an AND fragment (for appending to existing WHERE)."""
    if not clauses:
        return ""
    return "AND " + " AND ".join(clauses)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_actor_co_occurrence(
    db: AsyncSession,
    query_design_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    platform: str | None = None,
    arena: str | None = None,
    date_from: Any = None,
    date_to: Any = None,
    min_co_occurrences: int = 2,
    limit: int = 200,
) -> dict:
    """Actor co-occurrence network based on shared search terms.

    Two authors co-occur when they both have records that share at least one
    search term in ``search_terms_matched``.  The edge weight is the number of
    distinct content record pairs satisfying this condition.

    The query uses a self-join on ``content_records`` with the PostgreSQL array
    overlap operator ``&&`` to find pairs of different authors sharing a term.
    The join is scoped to the same ``query_design_id`` or ``collection_run_id``
    to keep it bounded.

    Args:
        db: Active async database session.
        query_design_id: Restrict to records belonging to this query design.
        run_id: Restrict to records from this collection run.
        platform: Restrict both sides of the join to a single platform.
        arena: Restrict both sides of the join to a single arena.
        date_from: Inclusive lower bound on ``published_at``.
        date_to: Inclusive upper bound on ``published_at``.
        min_co_occurrences: Minimum edge weight (pair occurrences) to include.
        limit: Maximum number of edges to return (heaviest edges first).

    Returns:
        Graph dict ``{nodes: [...], edges: [...]}`` where:
        - node attributes: ``id``, ``label`` (display name), ``platform``,
          ``post_count``, ``degree``
        - edge attributes: ``source``, ``target``, ``weight``
    """
    params: dict[str, Any] = {
        "min_co": min_co_occurrences,
        "limit": limit,
    }

    # Build filter clauses for both sides of the self-join.
    a_clauses = _build_run_filter(
        query_design_id, run_id, arena, platform, date_from, date_to, params, "a."
    )
    # Duplicate filter params for the b side — use _b suffixed names.
    b_params: dict[str, Any] = {}
    b_clauses_raw = _build_run_filter(
        query_design_id, run_id, arena, platform, date_from, date_to, b_params, "b."
    )
    # Rename b-side params to avoid collisions with a-side params.
    b_clauses: list[str] = []
    for clause in b_clauses_raw:
        new_clause = clause
        for key in list(b_params.keys()):
            new_key = key + "_b"
            new_clause = new_clause.replace(f":{key}", f":{new_key}")
            params[new_key] = b_params[key]
        b_clauses.append(new_clause)

    a_filter = _and(a_clauses)
    b_filter = _and(b_clauses)

    sql = text(
        f"""
        WITH pairs AS (
            SELECT
                LEAST(a.pseudonymized_author_id, b.pseudonymized_author_id)   AS author_a,
                GREATEST(a.pseudonymized_author_id, b.pseudonymized_author_id) AS author_b,
                COUNT(*) AS pair_count
            FROM content_records a
            JOIN content_records b
                ON a.search_terms_matched && b.search_terms_matched
                AND a.pseudonymized_author_id <> b.pseudonymized_author_id
            WHERE a.pseudonymized_author_id IS NOT NULL
              AND b.pseudonymized_author_id IS NOT NULL
              AND a.search_terms_matched IS NOT NULL
              AND b.search_terms_matched IS NOT NULL
              {a_filter}
              {b_filter}
            GROUP BY 1, 2
            HAVING COUNT(*) >= :min_co
            ORDER BY pair_count DESC
            LIMIT :limit
        ),
        node_ids AS (
            SELECT DISTINCT author_a AS author_id FROM pairs
            UNION
            SELECT DISTINCT author_b FROM pairs
        )
        SELECT
            c.pseudonymized_author_id AS author_id,
            MAX(c.author_display_name) AS display_name,
            MAX(c.platform)            AS platform,
            COUNT(c.id)                AS post_count
        FROM content_records c
        JOIN node_ids n ON n.author_id = c.pseudonymized_author_id
        GROUP BY c.pseudonymized_author_id
        """
    )

    nodes_result = await db.execute(sql, params)
    node_rows = nodes_result.fetchall()

    if not node_rows:
        return _empty_graph()

    # Re-execute for edges only.
    edge_params: dict[str, Any] = {
        "min_co": min_co_occurrences,
        "limit": limit,
    }
    a_clauses2 = _build_run_filter(
        query_design_id, run_id, arena, platform, date_from, date_to, edge_params, "a."
    )
    b_params2: dict[str, Any] = {}
    b_clauses_raw2 = _build_run_filter(
        query_design_id, run_id, arena, platform, date_from, date_to, b_params2, "b."
    )
    b_clauses2: list[str] = []
    for clause in b_clauses_raw2:
        new_clause = clause
        for key in list(b_params2.keys()):
            new_key = key + "_b"
            new_clause = new_clause.replace(f":{key}", f":{new_key}")
            edge_params[new_key] = b_params2[key]
        b_clauses2.append(new_clause)

    a_filter2 = _and(a_clauses2)
    b_filter2 = _and(b_clauses2)

    edges_sql = text(
        f"""
        SELECT
            LEAST(a.pseudonymized_author_id, b.pseudonymized_author_id)    AS author_a,
            GREATEST(a.pseudonymized_author_id, b.pseudonymized_author_id) AS author_b,
            COUNT(*) AS pair_count
        FROM content_records a
        JOIN content_records b
            ON a.search_terms_matched && b.search_terms_matched
            AND a.pseudonymized_author_id <> b.pseudonymized_author_id
        WHERE a.pseudonymized_author_id IS NOT NULL
          AND b.pseudonymized_author_id IS NOT NULL
          AND a.search_terms_matched IS NOT NULL
          AND b.search_terms_matched IS NOT NULL
          {a_filter2}
          {b_filter2}
        GROUP BY 1, 2
        HAVING COUNT(*) >= :min_co
        ORDER BY pair_count DESC
        LIMIT :limit
        """
    )
    edges_result = await db.execute(edges_sql, edge_params)
    edge_rows = edges_result.fetchall()

    # Compute node degrees from edge list.
    degree_map: dict[str, int] = defaultdict(int)
    for row in edge_rows:
        degree_map[row.author_a] += 1
        degree_map[row.author_b] += 1

    nodes = [
        {
            "id": row.author_id,
            "label": row.display_name or row.author_id,
            "platform": row.platform,
            "post_count": row.post_count,
            "degree": degree_map.get(row.author_id, 0),
        }
        for row in node_rows
    ]
    edges = [
        {
            "source": row.author_a,
            "target": row.author_b,
            "weight": row.pair_count,
        }
        for row in edge_rows
    ]

    return {"nodes": nodes, "edges": edges}


async def get_term_co_occurrence(
    db: AsyncSession,
    query_design_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    arena: str | None = None,
    min_co_occurrences: int = 2,
    limit: int = 100,
) -> dict:
    """Term co-occurrence network — pairs of search terms appearing in the same record.

    Uses ``unnest(search_terms_matched)`` twice (via a LATERAL join pattern) to
    produce all ordered pairs of distinct terms within a single content record,
    then aggregates by unordered pair.

    Args:
        db: Active async database session.
        query_design_id: Restrict to records belonging to this query design.
        run_id: Restrict to records from this collection run.
        arena: Restrict to records from a single arena.
        min_co_occurrences: Minimum number of shared records to include an edge.
        limit: Maximum number of edges to return (heaviest first).

    Returns:
        Graph dict ``{nodes: [...], edges: [...]}`` where:
        - node attributes: ``id`` (term string), ``label``, ``type`` = ``"term"``,
          ``frequency`` (total occurrences across all records)
        - edge attributes: ``source``, ``target``, ``weight``
    """
    params: dict[str, Any] = {
        "min_co": min_co_occurrences,
        "limit": limit,
    }

    # Use the shared filter builder (includes duplicate exclusion).
    # Platform is not relevant for term networks; arena is passed through
    # when the caller wants to restrict to a single arena.
    scope_clauses = _build_run_filter(
        query_design_id, run_id, arena, None, None, None, params
    )
    scope_filter = _and(scope_clauses)

    sql = text(
        f"""
        WITH term_pairs AS (
            SELECT
                LEAST(t1.term, t2.term)    AS term_a,
                GREATEST(t1.term, t2.term) AS term_b,
                COUNT(DISTINCT cr.id)      AS co_count
            FROM content_records cr,
                 unnest(search_terms_matched) AS t1(term),
                 unnest(search_terms_matched) AS t2(term)
            WHERE cr.search_terms_matched IS NOT NULL
              AND t1.term < t2.term
              {scope_filter}
            GROUP BY 1, 2
            HAVING COUNT(DISTINCT cr.id) >= :min_co
            ORDER BY co_count DESC
            LIMIT :limit
        ),
        node_ids AS (
            SELECT DISTINCT term_a AS term FROM term_pairs
            UNION
            SELECT DISTINCT term_b FROM term_pairs
        ),
        term_freq AS (
            SELECT
                t.term,
                COUNT(DISTINCT cr.id) AS frequency
            FROM content_records cr,
                 unnest(search_terms_matched) AS t(term)
            WHERE cr.search_terms_matched IS NOT NULL
              AND t.term IN (SELECT term FROM node_ids)
              {scope_filter}
            GROUP BY t.term
        )
        SELECT
            p.term_a,
            p.term_b,
            p.co_count,
            fa.frequency AS freq_a,
            fb.frequency AS freq_b
        FROM term_pairs p
        LEFT JOIN term_freq fa ON fa.term = p.term_a
        LEFT JOIN term_freq fb ON fb.term = p.term_b
        ORDER BY p.co_count DESC
        """
    )

    result = await db.execute(sql, params)
    rows = result.fetchall()

    if not rows:
        return _empty_graph()

    # Collect node data from results.
    node_freq: dict[str, int] = {}
    for row in rows:
        if row.term_a not in node_freq:
            node_freq[row.term_a] = row.freq_a or 0
        if row.term_b not in node_freq:
            node_freq[row.term_b] = row.freq_b or 0

    # Compute degree from edge list.
    degree_map: dict[str, int] = defaultdict(int)
    for row in rows:
        degree_map[row.term_a] += 1
        degree_map[row.term_b] += 1

    nodes = [
        {
            "id": term,
            "label": term,
            "type": "term",
            "frequency": freq,
            "degree": degree_map.get(term, 0),
        }
        for term, freq in node_freq.items()
    ]
    edges = [
        {
            "source": row.term_a,
            "target": row.term_b,
            "weight": row.co_count,
        }
        for row in rows
    ]

    return {"nodes": nodes, "edges": edges}


async def get_cross_platform_actors(
    db: AsyncSession,
    query_design_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    min_platforms: int = 2,
) -> list[dict]:
    """Find canonical actors active on multiple platforms.

    Joins ``content_records`` (to count distinct platforms per ``author_id``)
    with the ``actors`` table to surface the canonical name.  Only records
    where ``author_id`` is non-null (i.e. entity resolution has been performed)
    are considered.

    Args:
        db: Active async database session.
        query_design_id: Restrict to records belonging to this query design.
        run_id: Restrict to records from this collection run.
        min_platforms: Minimum number of distinct platforms required (default 2).

    Returns:
        A list of dicts ordered by ``platform_count`` descending::

            [
              {
                "actor_id": "...",
                "canonical_name": "DR Nyheder",
                "platform_count": 3,
                "platforms": ["facebook", "youtube", "instagram"],
                "total_records": 842,
              },
              ...
            ]
    """
    params: dict[str, Any] = {"min_platforms": min_platforms}

    # Use the shared filter builder with the "c." alias for content_records c.
    # The duplicate exclusion clause is included automatically.
    scope_clauses = _build_run_filter(
        query_design_id, run_id, None, None, None, None, params, table_alias="c."
    )
    scope_filter = _and(scope_clauses)

    sql = text(
        f"""
        SELECT
            c.author_id,
            a.canonical_name,
            COUNT(DISTINCT c.platform)                AS platform_count,
            array_agg(DISTINCT c.platform ORDER BY c.platform) AS platforms,
            COUNT(c.id)                               AS total_records
        FROM content_records c
        JOIN actors a ON a.id = c.author_id
        WHERE c.author_id IS NOT NULL
          {scope_filter}
        GROUP BY c.author_id, a.canonical_name
        HAVING COUNT(DISTINCT c.platform) >= :min_platforms
        ORDER BY platform_count DESC, total_records DESC
        """
    )

    result = await db.execute(sql, params)
    rows = result.fetchall()

    return [
        {
            "actor_id": str(row.author_id),
            "canonical_name": row.canonical_name,
            "platform_count": row.platform_count,
            "platforms": list(row.platforms) if row.platforms else [],
            "total_records": row.total_records,
        }
        for row in rows
    ]


async def build_bipartite_network(
    db: AsyncSession,
    query_design_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    arena: str | None = None,
    limit: int = 500,
) -> dict:
    """Bipartite network linking actors to the search terms they match.

    Each unique ``(pseudonymized_author_id, term)`` pair becomes an edge.
    The edge weight is the number of content records in which that author
    matched that term.

    Node types:
    - ``"actor"``: a pseudonymized author
    - ``"term"``: a search term string

    Args:
        db: Active async database session.
        query_design_id: Restrict to records belonging to this query design.
        run_id: Restrict to records from this collection run.
        arena: Restrict to records from a single arena.
        limit: Maximum number of edges to return (heaviest first).

    Returns:
        Graph dict ``{nodes: [...], edges: [...]}`` where:
        - actor node attributes: ``id``, ``label`` (display name), ``type`` = ``"actor"``
        - term node attributes: ``id``, ``label`` (term), ``type`` = ``"term"``
        - edge attributes: ``source`` (author id), ``target`` (term), ``weight``
    """
    params: dict[str, Any] = {"limit": limit}

    # Use the shared filter builder with the "cr." alias for content_records cr.
    # The duplicate exclusion clause is included automatically.
    scope_clauses = _build_run_filter(
        query_design_id, run_id, arena, None, None, None, params, table_alias="cr."
    )
    scope_filter = _and(scope_clauses)

    sql = text(
        f"""
        SELECT
            cr.pseudonymized_author_id AS author_id,
            MAX(cr.author_display_name) AS display_name,
            MAX(cr.platform)            AS platform,
            t.term,
            COUNT(cr.id) AS edge_weight
        FROM content_records cr,
             unnest(search_terms_matched) AS t(term)
        WHERE cr.pseudonymized_author_id IS NOT NULL
          AND cr.search_terms_matched IS NOT NULL
          {scope_filter}
        GROUP BY cr.pseudonymized_author_id, t.term
        ORDER BY edge_weight DESC
        LIMIT :limit
        """
    )

    result = await db.execute(sql, params)
    rows = result.fetchall()

    if not rows:
        return _empty_graph()

    # Collect unique actors and terms.
    # actor_nodes: author_id -> (display_name, platform)
    actor_nodes: dict[str, tuple[str, str]] = {}
    term_nodes: set[str] = set()

    for row in rows:
        actor_nodes[row.author_id] = (
            row.display_name or row.author_id,
            row.platform or "",
        )
        term_nodes.add(row.term)

    nodes: list[dict] = []
    for author_id, (display_name, platform) in actor_nodes.items():
        nodes.append(
            {
                "id": author_id,
                "label": display_name,
                "type": "actor",
                "platform": platform,
            }
        )
    for term in sorted(term_nodes):
        nodes.append(
            {
                "id": f"term:{term}",
                "label": term,
                "type": "term",
                "platform": "",
            }
        )

    edges = [
        {
            "source": row.author_id,
            "target": f"term:{row.term}",
            "weight": row.edge_weight,
        }
        for row in rows
    ]

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Temporal network snapshots
# ---------------------------------------------------------------------------

_VALID_INTERVALS = frozenset({"day", "week", "month"})
_VALID_NETWORK_TYPES = frozenset({"actor", "term"})

# Maximum number of time buckets before the interval is automatically upgraded.
_MAX_BUCKETS = 52


async def get_temporal_network_snapshots(
    db: AsyncSession,
    query_design_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    interval: str = "week",
    network_type: str = "actor",
    limit_per_snapshot: int = 200,
) -> list[dict]:
    """Generate a time-series of network snapshots.

    For each time interval bucket, returns a graph dict (nodes, edges)
    representing the network built from records in that bucket only.

    Uses a single SQL query with ``date_trunc`` to fetch all edge data across
    all periods at once, then reconstructs per-period snapshots in Python.

    Args:
        db: Active async database session.
        query_design_id: Restrict to records belonging to this query design.
        run_id: Restrict to records from this collection run.
        interval: Time bucket size — ``"day"``, ``"week"``, or ``"month"``.
            Automatically upgraded (day→week→month) if the date range would
            produce more than 52 buckets.
        network_type: ``"actor"`` for actor co-occurrence, ``"term"`` for term
            co-occurrence.
        limit_per_snapshot: Maximum number of edges per snapshot (heaviest
            first).

    Returns:
        List of snapshot dicts ordered by period ascending::

            [
              {
                "period": "2026-02-01T00:00:00",
                "node_count": 42,
                "edge_count": 87,
                "graph": {"nodes": [...], "edges": [...]},
              },
              ...
            ]

        Returns an empty list when no records match the filters.

    Raises:
        ValueError: If ``interval`` or ``network_type`` is not one of the
            accepted values.
    """
    if interval not in _VALID_INTERVALS:
        raise ValueError(
            f"Invalid interval {interval!r}. Must be one of: {sorted(_VALID_INTERVALS)}"
        )
    if network_type not in _VALID_NETWORK_TYPES:
        raise ValueError(
            f"Invalid network_type {network_type!r}. "
            f"Must be one of: {sorted(_VALID_NETWORK_TYPES)}"
        )

    params: dict[str, Any] = {}
    scope_clauses = _build_run_filter(
        query_design_id, run_id, None, None, None, None, params
    )
    scope_filter = _and(scope_clauses)

    # ------------------------------------------------------------------
    # Step 1: determine date range and auto-upgrade interval if needed.
    # ------------------------------------------------------------------
    range_sql = text(
        f"""
        SELECT
            MIN(published_at) AS min_date,
            MAX(published_at) AS max_date
        FROM content_records
        WHERE published_at IS NOT NULL
          {scope_filter}
        """
    )
    range_result = await db.execute(range_sql, params)
    range_row = range_result.fetchone()

    if range_row is None or range_row.min_date is None:
        return []

    min_date = range_row.min_date
    max_date = range_row.max_date

    interval_days = {"day": 1, "week": 7, "month": 30}
    date_span_days = max(1, (max_date - min_date).days + 1)

    # Auto-upgrade interval to stay within _MAX_BUCKETS.
    # Walk candidates from finest (day) to coarsest (month); stop as soon as
    # we find the first candidate that both (a) fits within _MAX_BUCKETS and
    # (b) is at least as coarse as the requested interval.  This ensures we
    # never downgrade the interval the caller requested.
    _interval_order = ("day", "week", "month")
    effective_interval = "month"  # safe default if nothing fits
    for candidate in _interval_order:
        estimated_buckets = date_span_days // interval_days[candidate] + 1
        if estimated_buckets <= _MAX_BUCKETS and _interval_order.index(candidate) >= _interval_order.index(interval):
            effective_interval = candidate
            break

    logger.info(
        "get_temporal_network_snapshots: date range",
        min_date=str(min_date),
        max_date=str(max_date),
        requested_interval=interval,
        effective_interval=effective_interval,
        network_type=network_type,
    )

    # ------------------------------------------------------------------
    # Step 2: fetch all edge data bucketed by period in a single query.
    # ------------------------------------------------------------------
    if network_type == "actor":
        rows = await _fetch_actor_temporal_rows(
            db, params, scope_filter, effective_interval
        )
    else:
        rows = await _fetch_term_temporal_rows(
            db, params, scope_filter, effective_interval
        )

    if not rows:
        return []

    # ------------------------------------------------------------------
    # Step 3: group rows by period and build per-period graph dicts.
    # ------------------------------------------------------------------
    from collections import defaultdict

    period_edges: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        period_key = row.period.isoformat() if hasattr(row.period, "isoformat") else str(row.period)
        period_edges[period_key].append(row)

    snapshots: list[dict] = []
    for period_key in sorted(period_edges.keys()):
        period_rows = period_edges[period_key]

        # Apply per-snapshot limit (heaviest edges first).
        period_rows_sorted = sorted(
            period_rows, key=lambda r: r.weight, reverse=True
        )[:limit_per_snapshot]

        if network_type == "actor":
            graph = _build_actor_snapshot_graph(period_rows_sorted)
        else:
            graph = _build_term_snapshot_graph(period_rows_sorted)

        snapshots.append(
            {
                "period": period_key,
                "node_count": len(graph["nodes"]),
                "edge_count": len(graph["edges"]),
                "graph": graph,
            }
        )

    return snapshots


async def _fetch_actor_temporal_rows(
    db: AsyncSession,
    params: dict[str, Any],
    scope_filter: str,
    interval: str,
) -> list[Any]:
    """Fetch actor co-occurrence edge data bucketed by time period.

    Uses a self-join on ``content_records`` via the ``search_terms_matched``
    overlap operator ``&&``.  Returns one row per ``(period, author_a,
    author_b)`` triple with an aggregated weight.

    Args:
        db: Active async database session.
        params: Bind parameter dict (already populated by the caller).
        scope_filter: SQL ``AND …`` fragment for scoping (no leading WHERE).
        interval: PostgreSQL date_trunc interval string.

    Returns:
        List of SQLAlchemy Row objects with columns ``period``, ``author_a``,
        ``author_b``, ``weight``.
    """
    # The scope filter references params keys without aliases.  For the
    # self-join we apply them to the ``a`` side only; the ``b`` side mirrors
    # the same scope via a renamed param set.
    b_params: dict[str, Any] = {}
    b_clauses_raw = _build_run_filter(
        None, None, None, None, None, None, b_params
    )
    # Extract only the duplicate-exclusion clause for the b side (since
    # run_id / query_design_id are already applied on the a side).
    # Re-alias to avoid bind-param collisions.
    b_clauses: list[str] = []
    for clause in b_clauses_raw:
        new_clause = clause.replace("raw_metadata", "b.raw_metadata")
        b_clauses.append(new_clause)

    b_filter = " AND ".join(b_clauses)
    if b_filter:
        b_filter = "AND " + b_filter

    sql = text(
        f"""
        WITH bucketed AS (
            SELECT
                date_trunc('{interval}', a.published_at) AS period,
                LEAST(a.pseudonymized_author_id, b.pseudonymized_author_id)    AS author_a,
                GREATEST(a.pseudonymized_author_id, b.pseudonymized_author_id) AS author_b,
                COUNT(*) AS pair_count
            FROM content_records a
            JOIN content_records b
                ON a.search_terms_matched && b.search_terms_matched
                AND a.pseudonymized_author_id <> b.pseudonymized_author_id
            WHERE a.pseudonymized_author_id IS NOT NULL
              AND b.pseudonymized_author_id IS NOT NULL
              AND a.search_terms_matched IS NOT NULL
              AND b.search_terms_matched IS NOT NULL
              AND a.published_at IS NOT NULL
              {scope_filter}
              {b_filter}
            GROUP BY 1, 2, 3
        )
        SELECT
            period,
            author_a,
            author_b,
            SUM(pair_count) AS weight
        FROM bucketed
        GROUP BY period, author_a, author_b
        ORDER BY period ASC, weight DESC
        """
    )

    result = await db.execute(sql, params)
    return result.fetchall()


async def _fetch_term_temporal_rows(
    db: AsyncSession,
    params: dict[str, Any],
    scope_filter: str,
    interval: str,
) -> list[Any]:
    """Fetch term co-occurrence edge data bucketed by time period.

    Uses ``unnest(search_terms_matched)`` twice to produce all ordered pairs
    of distinct terms within each content record, then aggregates by
    ``(period, term_a, term_b)``.

    Args:
        db: Active async database session.
        params: Bind parameter dict (already populated by the caller).
        scope_filter: SQL ``AND …`` fragment for scoping (no leading WHERE).
        interval: PostgreSQL date_trunc interval string.

    Returns:
        List of SQLAlchemy Row objects with columns ``period``, ``author_a``
        (actually ``term_a``), ``author_b`` (actually ``term_b``), ``weight``.
    """
    sql = text(
        f"""
        SELECT
            date_trunc('{interval}', cr.published_at) AS period,
            LEAST(t1.term, t2.term)    AS author_a,
            GREATEST(t1.term, t2.term) AS author_b,
            COUNT(DISTINCT cr.id)      AS weight
        FROM content_records cr,
             unnest(search_terms_matched) AS t1(term),
             unnest(search_terms_matched) AS t2(term)
        WHERE cr.search_terms_matched IS NOT NULL
          AND cr.published_at IS NOT NULL
          AND t1.term < t2.term
          {scope_filter}
        GROUP BY 1, 2, 3
        ORDER BY period ASC, weight DESC
        """
    )

    result = await db.execute(sql, params)
    return result.fetchall()


def _build_actor_snapshot_graph(rows: list[Any]) -> dict:
    """Build a graph dict from actor co-occurrence rows for one time period.

    Args:
        rows: SQLAlchemy Row objects with ``author_a``, ``author_b``, ``weight``.

    Returns:
        Graph dict ``{"nodes": [...], "edges": [...]}`` with degree computed
        from the local edge list.
    """
    degree_map: dict[str, int] = defaultdict(int)
    node_ids: set[str] = set()
    for row in rows:
        node_ids.add(row.author_a)
        node_ids.add(row.author_b)
        degree_map[row.author_a] += 1
        degree_map[row.author_b] += 1

    nodes = [
        {"id": nid, "label": nid, "type": "actor", "degree": degree_map[nid]}
        for nid in node_ids
    ]
    edges = [
        {"source": row.author_a, "target": row.author_b, "weight": row.weight}
        for row in rows
    ]
    return {"nodes": nodes, "edges": edges}


def _build_term_snapshot_graph(rows: list[Any]) -> dict:
    """Build a graph dict from term co-occurrence rows for one time period.

    Args:
        rows: SQLAlchemy Row objects with ``author_a`` (term_a), ``author_b``
            (term_b), ``weight``.

    Returns:
        Graph dict ``{"nodes": [...], "edges": [...]}`` with degree computed
        from the local edge list.
    """
    degree_map: dict[str, int] = defaultdict(int)
    node_ids: set[str] = set()
    for row in rows:
        node_ids.add(row.author_a)
        node_ids.add(row.author_b)
        degree_map[row.author_a] += 1
        degree_map[row.author_b] += 1

    nodes = [
        {"id": nid, "label": nid, "type": "term", "degree": degree_map[nid]}
        for nid in node_ids
    ]
    edges = [
        {"source": row.author_a, "target": row.author_b, "weight": row.weight}
        for row in rows
    ]
    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Enhanced bipartite network (search terms + emergent topics)
# ---------------------------------------------------------------------------


async def build_enhanced_bipartite_network(
    db: AsyncSession,
    emergent_terms: list[dict],
    query_design_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    limit: int = 500,
) -> dict:
    """Enhanced bipartite network combining search terms and emergent topics.

    Extends :func:`build_bipartite_network` with additional term nodes
    discovered via TF-IDF extraction.  Term nodes carry a ``term_type``
    attribute distinguishing their origin:

    - ``"search_term"``: came from the ``search_terms_matched`` array on
      content_records (the base bipartite graph).
    - ``"emergent_term"``: discovered via TF-IDF extraction
      (:func:`~issue_observatory.analysis.descriptive.get_emergent_terms`).

    The function first calls :func:`build_bipartite_network` to get the base
    graph, marks all existing term nodes as ``term_type="search_term"``, then
    queries actor-emergent_term edges via PostgreSQL full-text search
    (``to_tsvector`` / ``plainto_tsquery`` with the Danish configuration) and
    merges them into the graph.  Actors already in the base graph are reused;
    new actors are added.

    Args:
        db: Active async database session.
        emergent_terms: List from
            :func:`~issue_observatory.analysis.descriptive.get_emergent_terms`
            — each item has a ``"term"`` key (string).
        query_design_id: Restrict to records belonging to this query design.
        run_id: Restrict to records from this collection run.
        limit: Maximum number of edges in the base bipartite graph.

    Returns:
        Graph dict ``{"nodes": [...], "edges": [...]}`` where term nodes
        include a ``"term_type"`` attribute (``"search_term"`` or
        ``"emergent_term"``).  Returns the plain base graph (with
        ``term_type="search_term"`` on all term nodes) when
        ``emergent_terms`` is empty.
    """
    # Step 1: get the base bipartite graph from search-term edges.
    base_graph = await build_bipartite_network(
        db, query_design_id=query_design_id, run_id=run_id, limit=limit
    )

    # Step 2: annotate existing term nodes with term_type="search_term"
    # and existing actor nodes with term_type=None (not applicable).
    for node in base_graph["nodes"]:
        if node.get("type") == "term":
            node["term_type"] = "search_term"
        else:
            node["term_type"] = None

    if not emergent_terms:
        return base_graph

    # Determine which terms are already in the base graph (as term nodes).
    existing_term_ids: set[str] = {
        node["id"]
        for node in base_graph["nodes"]
        if node.get("type") == "term"
    }

    # Existing actor node IDs for fast dedup lookup.
    existing_actor_ids: set[str] = {
        node["id"]
        for node in base_graph["nodes"]
        if node.get("type") == "actor"
    }

    params: dict[str, Any] = {}
    scope_clauses = _build_run_filter(
        query_design_id, run_id, None, None, None, None, params, table_alias="cr."
    )
    scope_filter = _and(scope_clauses)

    nodes: list[dict] = list(base_graph["nodes"])
    edges: list[dict] = list(base_graph["edges"])

    # Step 3: for each emergent term not already present, query actor edges.
    for et in emergent_terms:
        term_str: str = et.get("term", "")
        if not term_str:
            continue

        term_node_id = f"term:{term_str}"
        if term_node_id in existing_term_ids:
            # Already in the base graph as a search term — skip to avoid duplication.
            continue

        et_params: dict[str, Any] = dict(params)
        et_params["et_term"] = term_str

        et_sql = text(
            f"""
            SELECT
                cr.pseudonymized_author_id AS author_id,
                MAX(cr.author_display_name) AS display_name,
                MAX(cr.platform)            AS platform,
                COUNT(cr.id)                AS edge_weight
            FROM content_records cr
            WHERE cr.pseudonymized_author_id IS NOT NULL
              AND cr.text_content IS NOT NULL
              AND to_tsvector('danish', cr.text_content) @@ plainto_tsquery('danish', :et_term)
              {scope_filter}
            GROUP BY cr.pseudonymized_author_id
            ORDER BY edge_weight DESC
            LIMIT 100
            """
        )

        et_result = await db.execute(et_sql, et_params)
        et_rows = et_result.fetchall()

        if not et_rows:
            continue

        # Add the emergent term node once.
        nodes.append(
            {
                "id": term_node_id,
                "label": term_str,
                "type": "term",
                "platform": "",
                "term_type": "emergent_term",
            }
        )
        existing_term_ids.add(term_node_id)

        # Add actor nodes and edges.
        for row in et_rows:
            if row.author_id not in existing_actor_ids:
                nodes.append(
                    {
                        "id": row.author_id,
                        "label": row.display_name or row.author_id,
                        "type": "actor",
                        "platform": row.platform or "",
                        "term_type": None,
                    }
                )
                existing_actor_ids.add(row.author_id)

            edges.append(
                {
                    "source": row.author_id,
                    "target": term_node_id,
                    "weight": row.edge_weight,
                }
            )

    logger.info(
        "build_enhanced_bipartite_network: graph built",
        node_count=len(nodes),
        edge_count=len(edges),
        emergent_term_count=len(emergent_terms),
        query_design_id=str(query_design_id) if query_design_id else None,
        run_id=str(run_id) if run_id else None,
    )

    return {"nodes": nodes, "edges": edges}
