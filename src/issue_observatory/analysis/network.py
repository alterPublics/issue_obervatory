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

    Args:
        table_alias: Optional table alias prefix (e.g. ``"a."``).  Include
            trailing dot.

    Returns:
        List of SQL predicate strings (no leading ``WHERE``).
    """
    prefix = table_alias
    clauses: list[str] = []

    if query_design_id is not None:
        clauses.append(f"{prefix}query_design_id = :query_design_id")
        params["query_design_id"] = str(query_design_id)

    if run_id is not None:
        clauses.append(f"{prefix}collection_run_id = :run_id")
        params["run_id"] = str(run_id)

    if arena is not None:
        clauses.append(f"{prefix}arena = :arena")
        params["arena"] = arena

    if platform is not None:
        clauses.append(f"{prefix}platform = :platform")
        params["platform"] = platform

    if date_from is not None:
        clauses.append(f"{prefix}published_at >= :date_from")
        params["date_from"] = date_from

    if date_to is not None:
        clauses.append(f"{prefix}published_at <= :date_to")
        params["date_to"] = date_to

    return clauses


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
        query_design_id, run_id, None, platform, date_from, date_to, params, "a."
    )
    # Duplicate filter params for the b side — use _b suffixed names.
    b_params: dict[str, Any] = {}
    b_clauses_raw = _build_run_filter(
        query_design_id, run_id, None, platform, date_from, date_to, b_params, "b."
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
        query_design_id, run_id, None, platform, date_from, date_to, edge_params, "a."
    )
    b_params2: dict[str, Any] = {}
    b_clauses_raw2 = _build_run_filter(
        query_design_id, run_id, None, platform, date_from, date_to, b_params2, "b."
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

    scope_clauses: list[str] = []
    if query_design_id is not None:
        scope_clauses.append("query_design_id = :query_design_id")
        params["query_design_id"] = str(query_design_id)
    if run_id is not None:
        scope_clauses.append("collection_run_id = :run_id")
        params["run_id"] = str(run_id)

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

    scope_clauses: list[str] = []
    if query_design_id is not None:
        scope_clauses.append("c.query_design_id = :query_design_id")
        params["query_design_id"] = str(query_design_id)
    if run_id is not None:
        scope_clauses.append("c.collection_run_id = :run_id")
        params["run_id"] = str(run_id)

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
        limit: Maximum number of edges to return (heaviest first).

    Returns:
        Graph dict ``{nodes: [...], edges: [...]}`` where:
        - actor node attributes: ``id``, ``label`` (display name), ``type`` = ``"actor"``
        - term node attributes: ``id``, ``label`` (term), ``type`` = ``"term"``
        - edge attributes: ``source`` (author id), ``target`` (term), ``weight``
    """
    params: dict[str, Any] = {"limit": limit}

    scope_clauses: list[str] = []
    if query_design_id is not None:
        scope_clauses.append("query_design_id = :query_design_id")
        params["query_design_id"] = str(query_design_id)
    if run_id is not None:
        scope_clauses.append("collection_run_id = :run_id")
        params["run_id"] = str(run_id)

    scope_filter = _and(scope_clauses)

    sql = text(
        f"""
        SELECT
            cr.pseudonymized_author_id AS author_id,
            MAX(cr.author_display_name) AS display_name,
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
    actor_nodes: dict[str, str] = {}  # author_id -> display_name
    term_nodes: set[str] = set()

    for row in rows:
        actor_nodes[row.author_id] = row.display_name or row.author_id
        term_nodes.add(row.term)

    nodes: list[dict] = []
    for author_id, display_name in actor_nodes.items():
        nodes.append(
            {
                "id": author_id,
                "label": display_name,
                "type": "actor",
            }
        )
    for term in sorted(term_nodes):
        nodes.append(
            {
                "id": f"term:{term}",
                "label": term,
                "type": "term",
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
