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
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.analysis._filters import build_content_where

logger = structlog.get_logger(__name__)

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

    Delegates to :func:`~issue_observatory.analysis._filters.build_content_where`
    which centralises filter logic — including the duplicate exclusion clause
    ``(raw_metadata->>'duplicate_of') IS NULL`` — so that both descriptive and
    network analysis consistently exclude duplicate-flagged records.

    Appends bind parameter values to *params* in place.

    Returns:
        A SQL string fragment starting with ``WHERE``.  Always non-empty
        because the duplicate exclusion predicate is always present.
    """
    return build_content_where(
        query_design_id, run_id, arena, platform, date_from, date_to, params
    )


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
    # _build_content_filters always returns a WHERE clause (at minimum the
    # duplicate exclusion predicate), so additional conditions always use AND.
    extra = "AND published_at IS NOT NULL"

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

    IP2-061: when a ``content_records.author_id`` FK exists and resolves to a
    row in the ``actors`` table, the returned dict includes a non-null
    ``resolved_name`` field containing ``actors.canonical_name``.  This
    allows the front-end to prefer the canonical identity over the raw
    ``author_display_name`` (which may be a pseudonymized hash) when
    labelling the top-actors chart.

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
                "resolved_name": "DR Nyheder",   # None when not resolved
                "actor_id": "uuid-string",        # None when not resolved
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
    # _build_content_filters always returns a WHERE clause, so additional
    # conditions always use AND.
    #
    # IP2-061: LEFT JOIN actors to retrieve canonical_name when author_id is
    # populated (entity resolution has been performed for this content record).
    # The MAX(a.canonical_name) aggregate is used because canonical_name is
    # functionally determined by author_id; MAX() avoids the need to GROUP BY
    # an extra text column.
    sql = text(
        f"""
        SELECT
            c.pseudonymized_author_id,
            c.author_display_name,
            c.platform,
            c.author_id,
            MAX(a.canonical_name) AS resolved_name,
            COUNT(*) AS cnt,
            SUM(
                COALESCE(c.likes_count, 0)
                + COALESCE(c.shares_count, 0)
                + COALESCE(c.comments_count, 0)
            ) AS total_engagement
        FROM content_records c
        LEFT JOIN actors a ON a.id = c.author_id
        {where}
        AND c.pseudonymized_author_id IS NOT NULL
        GROUP BY c.pseudonymized_author_id, c.author_display_name, c.platform, c.author_id
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
            "resolved_name": row.resolved_name,
            "actor_id": str(row.author_id) if row.author_id else None,
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
    # _build_content_filters always returns a WHERE clause, so additional
    # conditions always use AND.
    where = _build_content_filters(
        query_design_id, run_id, None, None, date_from, date_to, params
    )

    sql = text(
        f"""
        SELECT
            term,
            COUNT(*) AS cnt
        FROM content_records,
             unnest(search_terms_matched) AS term
        {where}
        AND search_terms_matched IS NOT NULL
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


async def get_emergent_terms(
    db: AsyncSession,
    query_design_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    top_n: int = 50,
    exclude_search_terms: bool = True,
    min_doc_frequency: int = 2,
) -> list[dict]:
    """Extract frequently-occurring terms from collected text content using TF-IDF.

    Uses scikit-learn TfidfVectorizer on ``text_content`` from matching
    content_records.  Applies Danish tokenization regex ``[a-z0-9æøå]{2,}``
    and filters out Danish and English stop words to surface meaningful terms.

    Args:
        db: Active async database session.
        query_design_id: Restrict to records in this query design.
        run_id: Restrict to records in this collection run.
        top_n: Number of top terms to return.
        exclude_search_terms: If True, exclude terms that match any of the
            query design's existing search terms (case-insensitive).
        min_doc_frequency: Minimum document frequency to include a term.

    Returns:
        List of dicts ordered by mean TF-IDF score descending::

            [{"term": "etik", "score": 0.42, "document_frequency": 87}, ...]

        Returns an empty list if scikit-learn is not installed, if fewer than
        5 text records are available, or if no terms pass the frequency filter.
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore[import]
    except ImportError:
        logger.warning(
            "get_emergent_terms: scikit-learn not installed; returning empty list"
        )
        return []

    import numpy as np  # type: ignore[import]

    params: dict[str, Any] = {}
    where = _build_content_filters(
        query_design_id, run_id, None, None, None, None, params
    )

    text_sql = text(
        f"""
        SELECT text_content
        FROM content_records
        {where}
        AND text_content IS NOT NULL
        AND length(text_content) > 20
        LIMIT 10000
        """
    )

    result = await db.execute(text_sql, params)
    rows = result.fetchall()
    texts = [row.text_content for row in rows if row.text_content]

    if len(texts) < 5:
        logger.info(
            "get_emergent_terms: fewer than 5 text records; returning empty list",
            record_count=len(texts),
        )
        return []

    # Build comprehensive stop word list: Danish + English + query-specific terms.
    stop_words_set: set[str] = set()

    # Danish stop words (comprehensive list including common function words)
    danish_stop_words = {
        "og", "i", "at", "er", "en", "et", "den", "det", "de", "til", "for",
        "af", "med", "der", "har", "var", "som", "han", "hun", "på", "kan",
        "vil", "skal", "fra", "over", "under", "efter", "inden", "mellem",
        "mod", "om", "sig", "sin", "sit", "sine", "ud", "op", "ned", "ind",
        "hen", "ad", "meg", "dig", "ham", "hende", "dem", "os", "jer", "mig",
        "mit", "min", "mine", "dit", "din", "dine", "hans", "hennes", "dens",
        "dets", "vores", "jeres", "deres", "denne", "dette", "disse", "her",
        "der", "hvor", "når", "da", "hvis", "fordi", "men", "eller", "så",
        "end", "også", "kun", "jo", "nu", "ved", "se", "gå", "gøre", "gør",
        "have", "hav", "gik", "blev", "fået", "fik", "aldrig", "ingen", "alle",
        "mange", "få", "noget", "intet", "nogen", "hver", "meget", "mere",
        "mest", "andet", "andre", "hvad", "hvilken", "hvilket", "hvilke",
        "hvem", "hvordan", "hvorfor", "hvorhen", "hvornår", "ja", "nej", "ikke",
        "være", "været", "bliver", "bliver", "bliver", "blive", "havde", "havde",
        "skulle", "kunne", "ville", "måtte", "blevet", "været", "gjort", "sagt",
        "kom", "kommer", "komme", "gør", "gjorde", "gjort", "tag", "tage",
        "tager", "tog", "taget", "før", "siden", "senere", "længe", "altid",
        "ofte", "aldrig", "nogle", "heller", "hverken", "enten", "både",
    }
    stop_words_set.update(danish_stop_words)

    # English stop words (comprehensive list for mixed-language content)
    english_stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "having", "do", "does", "did", "doing", "will",
        "would", "shall", "should", "can", "could", "may", "might", "must",
        "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
        "into", "through", "during", "before", "after", "above", "below",
        "between", "out", "off", "over", "under", "again", "further", "then",
        "once", "here", "there", "when", "where", "why", "how", "all", "both",
        "each", "few", "more", "most", "other", "some", "such", "no", "nor",
        "not", "only", "own", "same", "so", "than", "too", "very", "just",
        "about", "and", "but", "or", "if", "while", "although", "because",
        "until", "it", "its", "this", "that", "these", "those", "i", "me",
        "my", "mine", "we", "us", "our", "ours", "you", "your", "yours",
        "he", "him", "his", "she", "her", "hers", "they", "them", "their",
        "theirs", "what", "which", "who", "whom", "whose", "am", "been",
        "being", "become", "becomes", "became", "get", "gets", "got", "gotten",
        "make", "makes", "made", "go", "goes", "went", "gone", "take", "takes",
        "took", "taken", "come", "comes", "came", "know", "knows", "knew",
        "known", "think", "thinks", "thought", "see", "sees", "saw", "seen",
        "say", "says", "said", "give", "gives", "gave", "given", "find",
        "finds", "found", "tell", "tells", "told", "ask", "asks", "asked",
        "work", "works", "worked", "seem", "seems", "seemed", "feel", "feels",
        "felt", "try", "tries", "tried", "leave", "leaves", "left", "call",
        "calls", "called",
    }
    stop_words_set.update(english_stop_words)

    # Optionally exclude existing search terms for this query design.
    if exclude_search_terms and query_design_id is not None:
        term_sql = text(
            """
            SELECT term
            FROM search_terms
            WHERE query_design_id = :query_design_id
            """
        )
        term_result = await db.execute(term_sql, {"query_design_id": str(query_design_id)})
        existing_terms = [row.term.lower() for row in term_result.fetchall() if row.term]
        if existing_terms:
            stop_words_set.update(existing_terms)

    # Convert set to list for TfidfVectorizer
    stop_words_list = list(stop_words_set)

    vectorizer = TfidfVectorizer(
        analyzer="word",
        token_pattern=r"[a-z0-9æøå]{2,}",
        max_features=5000,
        min_df=min_doc_frequency,
        stop_words=stop_words_list,
    )

    try:
        tfidf_matrix = vectorizer.fit_transform(texts)
    except ValueError:
        # Raised when vocabulary is empty after filtering.
        logger.info("get_emergent_terms: empty vocabulary after filtering")
        return []

    feature_names: list[str] = vectorizer.get_feature_names_out().tolist()

    # Mean TF-IDF score per term across all documents.
    mean_scores = np.asarray(tfidf_matrix.mean(axis=0)).flatten()

    # Document frequency: number of documents in which each term appears.
    doc_freq = np.diff(tfidf_matrix.T.tocsr().indptr)

    # Sort by mean score descending, take top_n.
    top_indices = np.argsort(mean_scores)[::-1][:top_n]

    # Post-filter results to remove any remaining problematic tokens:
    # - Single-character tokens (even though token_pattern should catch this)
    # - Purely numeric tokens
    # - Tokens that are somehow still stop words (belt-and-suspenders)
    results = []
    for idx in top_indices:
        term = feature_names[idx]
        # Skip single-char tokens
        if len(term) < 2:
            continue
        # Skip purely numeric tokens
        if term.isdigit():
            continue
        # Skip if somehow still a stop word (case-insensitive check)
        if term.lower() in stop_words_set:
            continue

        results.append({
            "term": term,
            "score": round(float(mean_scores[idx]), 6),
            "document_frequency": int(doc_freq[idx]),
        })

        # Stop when we have enough valid results
        if len(results) >= top_n:
            break

    logger.info(
        "get_emergent_terms: extracted terms",
        doc_count=len(texts),
        term_count=len(results),
        query_design_id=str(query_design_id) if query_design_id else None,
        run_id=str(run_id) if run_id else None,
    )

    return results


async def get_top_actors_unified(
    db: AsyncSession,
    query_design_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 20,
) -> list[dict]:
    """Top authors by post volume, grouped by canonical Actor identity.

    Unlike :func:`get_top_actors` which groups by
    ``(pseudonymized_author_id, platform)``, this function groups by
    ``author_id`` (the UUID FK to the ``actors`` table) so that the same
    real-world actor appearing on multiple platforms is counted once.

    Only records where ``author_id IS NOT NULL`` (entity resolution has been
    performed) are counted.  Falls back gracefully to an empty list if no
    resolved actors exist.

    Args:
        db: Active async database session.
        query_design_id: Restrict to records belonging to this query design.
        run_id: Restrict to records collected in this collection run.
        date_from: Inclusive lower bound on ``published_at``.
        date_to: Inclusive upper bound on ``published_at``.
        limit: Maximum number of actors to return (default 20).

    Returns:
        A list of dicts ordered by ``count`` descending::

            [
              {
                "actor_id": "...",
                "canonical_name": "DR Nyheder",
                "platforms": ["facebook", "youtube"],
                "count": 342,
                "total_engagement": 98000,
              },
              ...
            ]

        Returns an empty list when no entity-resolved records match the filters.
    """
    params: dict[str, Any] = {"limit": limit}
    where = _build_content_filters(
        query_design_id, run_id, None, None, date_from, date_to, params
    )

    sql = text(
        f"""
        SELECT
            c.author_id,
            a.canonical_name,
            array_agg(DISTINCT c.platform ORDER BY c.platform) AS platforms,
            COUNT(c.id) AS cnt,
            SUM(
                COALESCE(c.likes_count, 0)
                + COALESCE(c.shares_count, 0)
                + COALESCE(c.comments_count, 0)
            ) AS total_engagement
        FROM content_records c
        JOIN actors a ON a.id = c.author_id
        {where}
        AND c.author_id IS NOT NULL
        GROUP BY c.author_id, a.canonical_name
        ORDER BY cnt DESC
        LIMIT :limit
        """
    )

    result = await db.execute(sql, params)
    rows = result.fetchall()

    return [
        {
            "actor_id": str(row.author_id),
            "canonical_name": row.canonical_name,
            "platforms": list(row.platforms) if row.platforms else [],
            "count": row.cnt,
            "total_engagement": int(row.total_engagement or 0),
        }
        for row in rows
    ]


async def compare_runs(
    db: AsyncSession,
    run_id_1: uuid.UUID,
    run_id_2: uuid.UUID,
) -> dict:
    """Compare two collection runs and return delta metrics.

    Computes volume deltas, new actors, new terms, and content overlap
    between two runs. Run 1 is treated as the baseline, Run 2 as the new run.

    Args:
        db: Active async database session.
        run_id_1: UUID of the first (baseline) run.
        run_id_2: UUID of the second (new) run.

    Returns:
        A dict with comparison metrics::

            {
              "run_1_id": "...",
              "run_2_id": "...",
              "volume_delta": {
                "total_records_1": 5812,
                "total_records_2": 6234,
                "delta": 422,
                "delta_pct": 7.26,
                "by_arena": [
                  {"arena": "news", "count_1": 2100, "count_2": 2300, "delta": 200},
                  ...
                ]
              },
              "new_actors": [
                {"author_display_name": "...", "pseudonymized_author_id": "...", "count": 45},
                ...
              ],
              "new_terms": [
                {"term": "...", "count": 123},
                ...
              ],
              "content_overlap": {
                "shared_hashes": 234,
                "unique_to_1": 5578,
                "unique_to_2": 6000,
                "overlap_pct": 4.0
              }
            }
    """
    params: dict[str, Any] = {"run_id_1": str(run_id_1), "run_id_2": str(run_id_2)}

    # --- Volume delta ---
    volume_sql = text(
        """
        SELECT
            COALESCE(SUM(CASE WHEN collection_run_id = :run_id_1 THEN 1 ELSE 0 END), 0) AS total_1,
            COALESCE(SUM(CASE WHEN collection_run_id = :run_id_2 THEN 1 ELSE 0 END), 0) AS total_2
        FROM content_records
        WHERE collection_run_id IN (:run_id_1, :run_id_2)
          AND (raw_metadata->>'duplicate_of') IS NULL
        """
    )
    volume_result = await db.execute(volume_sql, params)
    volume_row = volume_result.fetchone()
    total_1 = int(volume_row.total_1 or 0) if volume_row else 0
    total_2 = int(volume_row.total_2 or 0) if volume_row else 0
    delta = total_2 - total_1
    delta_pct = round((delta / total_1 * 100), 2) if total_1 > 0 else 0.0

    # Per-arena breakdown
    arena_sql = text(
        """
        SELECT
            arena,
            COALESCE(SUM(CASE WHEN collection_run_id = :run_id_1 THEN 1 ELSE 0 END), 0) AS count_1,
            COALESCE(SUM(CASE WHEN collection_run_id = :run_id_2 THEN 1 ELSE 0 END), 0) AS count_2
        FROM content_records
        WHERE collection_run_id IN (:run_id_1, :run_id_2)
          AND (raw_metadata->>'duplicate_of') IS NULL
        GROUP BY arena
        ORDER BY arena
        """
    )
    arena_result = await db.execute(arena_sql, params)
    arena_rows = arena_result.fetchall()
    by_arena = [
        {
            "arena": row.arena,
            "count_1": int(row.count_1),
            "count_2": int(row.count_2),
            "delta": int(row.count_2) - int(row.count_1),
        }
        for row in arena_rows
    ]

    # --- New actors in run 2 not seen in run 1 ---
    new_actors_sql = text(
        """
        SELECT
            c2.author_display_name,
            c2.pseudonymized_author_id,
            COUNT(*) AS cnt
        FROM content_records c2
        WHERE c2.collection_run_id = :run_id_2
          AND c2.pseudonymized_author_id IS NOT NULL
          AND (c2.raw_metadata->>'duplicate_of') IS NULL
          AND NOT EXISTS (
              SELECT 1
              FROM content_records c1
              WHERE c1.collection_run_id = :run_id_1
                AND c1.pseudonymized_author_id = c2.pseudonymized_author_id
          )
        GROUP BY c2.author_display_name, c2.pseudonymized_author_id
        ORDER BY cnt DESC
        LIMIT 50
        """
    )
    new_actors_result = await db.execute(new_actors_sql, params)
    new_actors_rows = new_actors_result.fetchall()
    new_actors = [
        {
            "author_display_name": row.author_display_name,
            "pseudonymized_author_id": row.pseudonymized_author_id,
            "count": row.cnt,
        }
        for row in new_actors_rows
    ]

    # --- New terms in run 2 not in run 1 ---
    new_terms_sql = text(
        """
        WITH terms_1 AS (
            SELECT DISTINCT unnest(search_terms_matched) AS term
            FROM content_records
            WHERE collection_run_id = :run_id_1
              AND (raw_metadata->>'duplicate_of') IS NULL
        ),
        terms_2 AS (
            SELECT unnest(search_terms_matched) AS term
            FROM content_records
            WHERE collection_run_id = :run_id_2
              AND (raw_metadata->>'duplicate_of') IS NULL
        )
        SELECT t2.term, COUNT(*) AS cnt
        FROM terms_2 t2
        LEFT JOIN terms_1 t1 ON t1.term = t2.term
        WHERE t1.term IS NULL
        GROUP BY t2.term
        ORDER BY cnt DESC
        LIMIT 50
        """
    )
    new_terms_result = await db.execute(new_terms_sql, params)
    new_terms_rows = new_terms_result.fetchall()
    new_terms = [{"term": row.term, "count": row.cnt} for row in new_terms_rows]

    # --- Content overlap via content_hash ---
    overlap_sql = text(
        """
        WITH hashes_1 AS (
            SELECT DISTINCT content_hash
            FROM content_records
            WHERE collection_run_id = :run_id_1
              AND content_hash IS NOT NULL
              AND (raw_metadata->>'duplicate_of') IS NULL
        ),
        hashes_2 AS (
            SELECT DISTINCT content_hash
            FROM content_records
            WHERE collection_run_id = :run_id_2
              AND content_hash IS NOT NULL
              AND (raw_metadata->>'duplicate_of') IS NULL
        )
        SELECT
            (SELECT COUNT(*) FROM hashes_1)                       AS total_1,
            (SELECT COUNT(*) FROM hashes_2)                       AS total_2,
            COUNT(*)                                             AS shared
        FROM hashes_1
        INNER JOIN hashes_2 ON hashes_1.content_hash = hashes_2.content_hash
        """
    )
    overlap_result = await db.execute(overlap_sql, params)
    overlap_row = overlap_result.fetchone()
    shared = int(overlap_row.shared or 0) if overlap_row else 0
    total_hashes_1 = int(overlap_row.total_1 or 0) if overlap_row else 0
    total_hashes_2 = int(overlap_row.total_2 or 0) if overlap_row else 0
    unique_to_1 = total_hashes_1 - shared
    unique_to_2 = total_hashes_2 - shared
    overlap_pct = round((shared / total_hashes_1 * 100), 2) if total_hashes_1 > 0 else 0.0

    logger.info(
        "compare_runs",
        run_id_1=str(run_id_1),
        run_id_2=str(run_id_2),
        delta=delta,
        new_actors_count=len(new_actors),
        new_terms_count=len(new_terms),
    )

    return {
        "run_1_id": str(run_id_1),
        "run_2_id": str(run_id_2),
        "volume_delta": {
            "total_records_1": total_1,
            "total_records_2": total_2,
            "delta": delta,
            "delta_pct": delta_pct,
            "by_arena": by_arena,
        },
        "new_actors": new_actors,
        "new_terms": new_terms,
        "content_overlap": {
            "shared_hashes": shared,
            "unique_to_1": unique_to_1,
            "unique_to_2": unique_to_2,
            "overlap_pct": overlap_pct,
        },
    }


async def get_temporal_comparison(
    db: AsyncSession,
    run_id: uuid.UUID,
    period: str = "week",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict:
    """Period-over-period volume comparison (current vs previous).

    Computes total volume for the current period and the immediately preceding
    period of equal length, then calculates delta and percentage change.
    Also provides per-arena breakdowns.

    Args:
        db: Active async database session.
        run_id: UUID of the collection run.
        period: Time period — one of ``"week"`` (default), ``"month"``.
        date_from: Optional explicit start of current period. If not provided,
            uses the latest date in the run as the end of the current period.
        date_to: Optional explicit end of current period.

    Returns:
        Dict with current and previous period volume::

            {
              "current_period": {
                "date_from": "2026-02-10T00:00:00+00:00",
                "date_to": "2026-02-17T00:00:00+00:00",
                "count": 1234,
              },
              "previous_period": {
                "date_from": "2026-02-03T00:00:00+00:00",
                "date_to": "2026-02-10T00:00:00+00:00",
                "count": 987,
              },
              "delta": 247,
              "pct_change": 25.03,
              "per_arena": [
                {
                  "arena": "news_media",
                  "current_count": 500,
                  "previous_count": 400,
                  "delta": 100,
                  "pct_change": 25.0,
                },
                ...
              ],
            }

    Raises:
        ValueError: If period is not ``"week"`` or ``"month"``.
    """
    if period not in {"week", "month"}:
        raise ValueError(f"Invalid period {period!r}. Must be 'week' or 'month'.")

    params: dict[str, Any] = {"run_id": str(run_id)}

    # Determine the date range for the current period.
    # If not provided, use the latest published_at as the end.
    if date_to is None:
        latest_sql = text(
            """
            SELECT MAX(published_at) AS latest
            FROM content_records
            WHERE collection_run_id = :run_id
              AND published_at IS NOT NULL
            """
        )
        latest_result = await db.execute(latest_sql, params)
        latest_row = latest_result.fetchone()
        if latest_row is None or latest_row.latest is None:
            logger.info("get_temporal_comparison: no data for run", run_id=str(run_id))
            return {
                "current_period": {"date_from": None, "date_to": None, "count": 0},
                "previous_period": {"date_from": None, "date_to": None, "count": 0},
                "delta": 0,
                "pct_change": 0.0,
                "per_arena": [],
            }
        date_to = latest_row.latest

    # Compute the interval as a timedelta
    if period == "week":
        interval_days = 7
    else:  # month
        # Use 30 days as a proxy for a month
        interval_days = 30

    if date_from is None:
        date_from = date_to - timedelta(days=interval_days)

    # Previous period is immediately before the current period
    previous_from = date_from - timedelta(days=interval_days)
    previous_to = date_from

    # Aggregate volume for current and previous periods
    volume_sql = text(
        """
        WITH current_period AS (
            SELECT COUNT(*) AS cnt
            FROM content_records
            WHERE collection_run_id = :run_id
              AND published_at >= :current_from
              AND published_at < :current_to
              AND (raw_metadata->>'duplicate_of') IS NULL
        ),
        previous_period AS (
            SELECT COUNT(*) AS cnt
            FROM content_records
            WHERE collection_run_id = :run_id
              AND published_at >= :previous_from
              AND published_at < :previous_to
              AND (raw_metadata->>'duplicate_of') IS NULL
        )
        SELECT
            (SELECT cnt FROM current_period) AS current_count,
            (SELECT cnt FROM previous_period) AS previous_count
        """
    )
    params.update({
        "current_from": date_from,
        "current_to": date_to,
        "previous_from": previous_from,
        "previous_to": previous_to,
    })
    volume_result = await db.execute(volume_sql, params)
    volume_row = volume_result.fetchone()

    current_count = int(volume_row.current_count or 0) if volume_row else 0
    previous_count = int(volume_row.previous_count or 0) if volume_row else 0
    delta = current_count - previous_count
    pct_change = round((delta / previous_count * 100), 2) if previous_count > 0 else 0.0

    # Per-arena breakdown
    arena_sql = text(
        """
        SELECT
            arena,
            SUM(CASE
                WHEN published_at >= :current_from AND published_at < :current_to
                THEN 1 ELSE 0
            END) AS current_count,
            SUM(CASE
                WHEN published_at >= :previous_from AND published_at < :previous_to
                THEN 1 ELSE 0
            END) AS previous_count
        FROM content_records
        WHERE collection_run_id = :run_id
          AND published_at >= :previous_from
          AND published_at < :current_to
          AND (raw_metadata->>'duplicate_of') IS NULL
        GROUP BY arena
        ORDER BY arena
        """
    )
    arena_result = await db.execute(arena_sql, params)
    arena_rows = arena_result.fetchall()

    per_arena = []
    for row in arena_rows:
        arena_current = int(row.current_count or 0)
        arena_previous = int(row.previous_count or 0)
        arena_delta = arena_current - arena_previous
        arena_pct = (
            round((arena_delta / arena_previous * 100), 2)
            if arena_previous > 0
            else 0.0
        )
        per_arena.append({
            "arena": row.arena,
            "current_count": arena_current,
            "previous_count": arena_previous,
            "delta": arena_delta,
            "pct_change": arena_pct,
        })

    logger.info(
        "get_temporal_comparison",
        run_id=str(run_id),
        period=period,
        current_count=current_count,
        previous_count=previous_count,
        delta=delta,
    )

    return {
        "current_period": {
            "date_from": _dt_iso(date_from),
            "date_to": _dt_iso(date_to),
            "count": current_count,
        },
        "previous_period": {
            "date_from": _dt_iso(previous_from),
            "date_to": _dt_iso(previous_to),
            "count": previous_count,
        },
        "delta": delta,
        "pct_change": pct_change,
        "per_arena": per_arena,
    }


async def get_arena_comparison(
    db: AsyncSession,
    run_id: uuid.UUID,
) -> dict:
    """Side-by-side arena metrics for a collection run.

    Returns per-arena breakdown with record count, unique actors, unique terms,
    average engagement score, and date range. Includes a totals row.

    Args:
        db: Active async database session.
        run_id: UUID of the collection run.

    Returns:
        Dict with per-arena metrics and totals::

            {
              "by_arena": [
                {
                  "arena": "news_media",
                  "record_count": 1234,
                  "unique_actors": 87,
                  "unique_terms": 23,
                  "avg_engagement": 42.5,
                  "earliest_record": "2026-02-01T00:00:00+00:00",
                  "latest_record": "2026-02-17T23:59:59+00:00",
                },
                ...
              ],
              "totals": {
                "record_count": 5678,
                "unique_actors": 321,
                "unique_terms": 45,
                "avg_engagement": 38.7,
                "earliest_record": "2026-02-01T00:00:00+00:00",
                "latest_record": "2026-02-17T23:59:59+00:00",
              },
            }

        Returns empty lists and zero counts when no records exist.
    """
    params: dict[str, Any] = {"run_id": str(run_id)}

    # Per-arena breakdown
    # Note: unique_terms requires a subquery because COUNT(DISTINCT unnest(...))
    # is not supported directly in PostgreSQL.
    arena_sql = text(
        """
        SELECT
            c.arena,
            COUNT(*) AS record_count,
            COUNT(DISTINCT c.pseudonymized_author_id) AS unique_actors,
            (
                SELECT COUNT(DISTINCT term)
                FROM content_records cr,
                     unnest(cr.search_terms_matched) AS term
                WHERE cr.collection_run_id = :run_id
                  AND cr.arena = c.arena
                  AND (cr.raw_metadata->>'duplicate_of') IS NULL
            ) AS unique_terms,
            AVG(c.engagement_score) AS avg_engagement,
            MIN(c.published_at) AS earliest_record,
            MAX(c.published_at) AS latest_record
        FROM content_records c
        WHERE c.collection_run_id = :run_id
          AND (c.raw_metadata->>'duplicate_of') IS NULL
        GROUP BY c.arena
        ORDER BY record_count DESC
        """
    )
    arena_result = await db.execute(arena_sql, params)
    arena_rows = arena_result.fetchall()

    by_arena = [
        {
            "arena": row.arena,
            "record_count": row.record_count,
            "unique_actors": row.unique_actors or 0,
            "unique_terms": row.unique_terms or 0,
            "avg_engagement": round(float(row.avg_engagement or 0), 2),
            "earliest_record": _dt_iso(row.earliest_record),
            "latest_record": _dt_iso(row.latest_record),
        }
        for row in arena_rows
    ]

    # Aggregate totals across all arenas
    totals_sql = text(
        """
        SELECT
            COUNT(*) AS record_count,
            COUNT(DISTINCT pseudonymized_author_id) AS unique_actors,
            (
                SELECT COUNT(DISTINCT term)
                FROM content_records cr,
                     unnest(cr.search_terms_matched) AS term
                WHERE cr.collection_run_id = :run_id
                  AND (cr.raw_metadata->>'duplicate_of') IS NULL
            ) AS unique_terms,
            AVG(engagement_score) AS avg_engagement,
            MIN(published_at) AS earliest_record,
            MAX(published_at) AS latest_record
        FROM content_records
        WHERE collection_run_id = :run_id
          AND (raw_metadata->>'duplicate_of') IS NULL
        """
    )
    totals_result = await db.execute(totals_sql, params)
    totals_row = totals_result.fetchone()

    if totals_row is None or totals_row.record_count == 0:
        logger.info("get_arena_comparison: no data for run", run_id=str(run_id))
        return {
            "by_arena": [],
            "totals": {
                "record_count": 0,
                "unique_actors": 0,
                "unique_terms": 0,
                "avg_engagement": 0.0,
                "earliest_record": None,
                "latest_record": None,
            },
        }

    totals = {
        "record_count": totals_row.record_count,
        "unique_actors": totals_row.unique_actors or 0,
        "unique_terms": totals_row.unique_terms or 0,
        "avg_engagement": round(float(totals_row.avg_engagement or 0), 2),
        "earliest_record": _dt_iso(totals_row.earliest_record),
        "latest_record": _dt_iso(totals_row.latest_record),
    }

    logger.info(
        "get_arena_comparison",
        run_id=str(run_id),
        arena_count=len(by_arena),
        total_records=totals["record_count"],
    )

    return {
        "by_arena": by_arena,
        "totals": totals,
    }


async def get_language_distribution(
    db: AsyncSession,
    run_id: uuid.UUID,
) -> list[dict]:
    """Query language detection enrichment results and return language counts.

    Extracts the ``raw_metadata.enrichments.language_detector.language`` field
    from all records in the specified collection run and aggregates by language
    code.  Returns an empty list when no language enrichment data exists.

    Args:
        db: Active async database session.
        run_id: UUID of the collection run to query.

    Returns:
        List of dicts ordered by count descending::

            [
              {"language": "da", "count": 523, "percentage": 68.5},
              {"language": "en", "count": 142, "percentage": 18.6},
              ...
            ]
    """
    params: dict[str, Any] = {}
    where = _build_content_filters(
        None, run_id, None, None, None, None, params
    )

    sql = text(
        f"""
        SELECT
            raw_metadata->'enrichments'->'language_detection'->>'language' AS language,
            COUNT(*) AS cnt
        FROM content_records
        {where}
        AND raw_metadata->'enrichments'->'language_detection'->>'language' IS NOT NULL
        GROUP BY 1
        ORDER BY cnt DESC
        """
    )

    result = await db.execute(sql, params)
    rows = result.fetchall()

    if not rows:
        return []

    total = sum(row.cnt for row in rows)

    return [
        {
            "language": row.language,
            "count": row.cnt,
            "percentage": round((row.cnt / total * 100), 2) if total > 0 else 0.0,
        }
        for row in rows
    ]


async def get_top_named_entities(
    db: AsyncSession,
    run_id: uuid.UUID,
    limit: int = 20,
) -> list[dict]:
    """Query NER enrichment results and return most frequent entities.

    Extracts entities from the
    ``raw_metadata.enrichments.named_entity_extractor.entities`` array,
    aggregates by entity text, and returns the top-N most frequent entities.

    Args:
        db: Active async database session.
        run_id: UUID of the collection run to query.
        limit: Maximum number of entities to return (default 20).

    Returns:
        List of dicts ordered by count descending::

            [
              {"entity": "Danmark", "count": 142, "types": ["GPE", "LOC"]},
              {"entity": "København", "count": 87, "types": ["GPE"]},
              ...
            ]

        Returns an empty list when no NER enrichment data exists.
    """
    params: dict[str, Any] = {"limit": limit}
    where = _build_content_filters(
        None, run_id, None, None, None, None, params
    )

    # Unnest the entities array and aggregate by entity text.
    # Collect all unique entity types per entity text using array_agg(DISTINCT).
    sql = text(
        f"""
        SELECT
            entity->>'text' AS entity_text,
            COUNT(*) AS cnt,
            array_agg(DISTINCT entity->>'label') AS entity_types
        FROM content_records,
             jsonb_array_elements(
                 raw_metadata->'enrichments'->'actor_roles'->'entities'
             ) AS entity
        {where}
        AND raw_metadata->'enrichments'->'actor_roles'->'entities' IS NOT NULL
        GROUP BY 1
        ORDER BY cnt DESC
        LIMIT :limit
        """
    )

    result = await db.execute(sql, params)
    rows = result.fetchall()

    return [
        {
            "entity": row.entity_text,
            "count": row.cnt,
            "types": list(row.entity_types) if row.entity_types else [],
        }
        for row in rows
    ]


async def get_propagation_patterns(
    db: AsyncSession,
    run_id: uuid.UUID,
) -> list[dict]:
    """Query propagation enrichment results and return cross-arena clusters.

    Retrieves all records flagged by the propagation enricher as having
    propagated across 2 or more arenas.  Returns cluster-level aggregates.

    Args:
        db: Active async database session.
        run_id: UUID of the collection run to query.

    Returns:
        List of dicts ordered by cluster size descending::

            [
              {
                "cluster_id": "abc123...",
                "arenas": ["news_media", "social_media"],
                "platforms": ["rss_feeds", "reddit", "bluesky"],
                "record_count": 24,
                "first_seen": "2026-02-10T08:30:00+00:00",
                "last_seen": "2026-02-15T14:22:00+00:00",
              },
              ...
            ]

        Returns an empty list when no propagation enrichment data exists.
    """
    params: dict[str, Any] = {}
    where = _build_content_filters(
        None, run_id, None, None, None, None, params
    )

    sql = text(
        f"""
        SELECT
            raw_metadata->'enrichments'->'propagation'->>'cluster_id' AS cluster_id,
            array_agg(DISTINCT arena ORDER BY arena) AS arenas,
            array_agg(DISTINCT platform ORDER BY platform) AS platforms,
            COUNT(*) AS record_count,
            MIN(published_at) AS first_seen,
            MAX(published_at) AS last_seen
        FROM content_records
        {where}
        AND raw_metadata->'enrichments'->'propagation'->>'cluster_id' IS NOT NULL
        AND raw_metadata->'enrichments'->'propagation'->>'is_origin' = 'false'
        GROUP BY 1
        HAVING COUNT(DISTINCT arena) >= 2
        ORDER BY record_count DESC
        """
    )

    result = await db.execute(sql, params)
    rows = result.fetchall()

    return [
        {
            "cluster_id": row.cluster_id,
            "arenas": list(row.arenas) if row.arenas else [],
            "platforms": list(row.platforms) if row.platforms else [],
            "record_count": row.record_count,
            "first_seen": _dt_iso(row.first_seen),
            "last_seen": _dt_iso(row.last_seen),
        }
        for row in rows
    ]


async def get_sentiment_distribution(
    db: AsyncSession,
    run_id: uuid.UUID,
) -> dict[str, Any]:
    """Query sentiment enrichment results and return sentiment distribution.

    Extracts the ``raw_metadata.enrichments.sentiment_analyzer`` field from
    all records in the specified collection run and aggregates sentiment scores.
    Returns empty counts when no sentiment enrichment data exists.

    Args:
        db: Active async database session.
        run_id: UUID of the collection run to query.

    Returns:
        Dict with sentiment distribution and average score::

            {
              "positive": 145,
              "negative": 67,
              "neutral": 423,
              "average_score": 0.12,
              "total_records": 635
            }

        All counts default to 0 when no enrichment data exists.
    """
    params: dict[str, Any] = {"run_id": str(run_id)}

    # Count records by sentiment polarity (positive, negative, neutral).
    # The sentiment_analyzer enricher stores a 'sentiment' string field that
    # can be 'positive', 'negative', or 'neutral', plus a 'score' float.
    sql = text(
        """
        SELECT
            raw_metadata->'enrichments'->'sentiment_analyzer'->>'sentiment' AS sentiment,
            COUNT(*) AS cnt,
            AVG((raw_metadata->'enrichments'->'sentiment_analyzer'->>'score')::float) AS avg_score
        FROM content_records
        WHERE collection_run_id = :run_id
          AND raw_metadata->'enrichments'->'sentiment_analyzer' IS NOT NULL
        GROUP BY 1
        """
    )

    result = await db.execute(sql, params)
    rows = result.fetchall()

    # Build result dict with default zero counts
    distribution: dict[str, int] = {
        "positive": 0,
        "negative": 0,
        "neutral": 0,
    }
    total_records = 0
    weighted_sum = 0.0

    for row in rows:
        sentiment = row.sentiment or "neutral"
        count = int(row.cnt)
        avg_score_for_sentiment = float(row.avg_score or 0.0)

        if sentiment in distribution:
            distribution[sentiment] = count
            total_records += count
            weighted_sum += avg_score_for_sentiment * count

    average_score = weighted_sum / total_records if total_records > 0 else 0.0

    return {
        "positive": distribution["positive"],
        "negative": distribution["negative"],
        "neutral": distribution["neutral"],
        "average_score": round(average_score, 3),
        "total_records": total_records,
    }


async def get_coordination_signals(
    db: AsyncSession,
    run_id: uuid.UUID,
) -> list[dict]:
    """Query coordination enrichment results and return detected patterns.

    Retrieves coordination signals flagged by the coordination enricher:
    actors posting identical or near-identical content within a short time
    window, or burst patterns indicating coordinated activity.

    Args:
        db: Active async database session.
        run_id: UUID of the collection run to query.

    Returns:
        List of dicts ordered by signal strength descending::

            [
              {
                "coordination_type": "burst",
                "actor_count": 12,
                "record_count": 87,
                "content_hash": "abc123...",
                "time_window_hours": 2.5,
                "first_post": "2026-02-14T10:00:00+00:00",
                "last_post": "2026-02-14T12:30:00+00:00",
              },
              ...
            ]

        Returns an empty list when no coordination enrichment data exists.
    """
    params: dict[str, Any] = {}
    where = _build_content_filters(
        None, run_id, None, None, None, None, params
    )

    # Aggregate coordination signals by content_hash to identify clusters.
    # Extract coordination_type from enrichment data.
    sql = text(
        f"""
        SELECT
            raw_metadata->'enrichments'->'coordination'->>'coordination_type' AS coordination_type,
            content_hash,
            COUNT(DISTINCT pseudonymized_author_id) AS actor_count,
            COUNT(*) AS record_count,
            MIN(published_at) AS first_post,
            MAX(published_at) AS last_post,
            EXTRACT(EPOCH FROM (MAX(published_at) - MIN(published_at))) / 3600.0 AS time_window_hours
        FROM content_records
        {where}
        AND raw_metadata->'enrichments'->'coordination'->>'flagged' = 'true'
        AND content_hash IS NOT NULL
        AND pseudonymized_author_id IS NOT NULL
        GROUP BY 1, 2
        HAVING COUNT(DISTINCT pseudonymized_author_id) >= 3
        ORDER BY record_count DESC
        LIMIT 50
        """
    )

    result = await db.execute(sql, params)
    rows = result.fetchall()

    return [
        {
            "coordination_type": row.coordination_type or "unknown",
            "actor_count": row.actor_count,
            "record_count": row.record_count,
            "content_hash": row.content_hash,
            "time_window_hours": round(float(row.time_window_hours or 0), 2),
            "first_post": _dt_iso(row.first_post),
            "last_post": _dt_iso(row.last_post),
        }
        for row in rows
    ]


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

    # Per-arena breakdown: count records directly from content_records,
    # with optional join to collection_tasks for task-level stats.
    # Uses LEFT JOIN so the breakdown works even when no CollectionTask
    # rows exist (e.g. for runs created before batch dispatch was implemented).
    arena_sql = text(
        """
        SELECT
            c.arena,
            COUNT(*)                                AS record_count,
            COALESCE(MAX(ct.records_collected), 0)  AS tasks_records_collected
        FROM content_records c
        LEFT JOIN collection_tasks ct
            ON ct.collection_run_id = c.collection_run_id
            AND ct.arena = c.arena
        WHERE c.collection_run_id = :run_id
        GROUP BY c.arena
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
