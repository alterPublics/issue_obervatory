"""Shared SQL filter-builder for the analysis layer.

Both ``descriptive.py`` and ``network.py`` need to generate WHERE-clause
predicates against ``content_records``.  Keeping the logic in one place
ensures that every analysis function filters duplicates the same way and
that future predicate additions only need to happen here.

Design notes
------------
- The module is intentionally private (``_filters.py``) because it is an
  implementation detail of the analysis package; callers outside the
  package should use the public functions in ``descriptive.py`` and
  ``network.py`` directly.
- Two return-value styles are provided so that callers can use the style
  that fits their existing SQL construction pattern:

  1. ``build_content_filters()`` — returns a list of predicate strings
     and mutates *params* in place.  Network functions use this style
     because they need to combine predicates with ``AND`` fragments
     appended to existing ``WHERE`` clauses.

  2. ``build_content_where()`` — wraps ``build_content_filters()`` and
     returns the full ``WHERE …`` string including the keyword.
     Descriptive functions use this style.

Owned by the DB Engineer.
"""

from __future__ import annotations

import uuid
from typing import Any


def build_content_filters(
    query_design_id: uuid.UUID | None,
    run_id: uuid.UUID | None,
    arena: str | None,
    platform: str | None,
    date_from: Any,
    date_to: Any,
    params: dict[str, Any],
    table_alias: str = "",
) -> list[str]:
    """Build a list of SQL WHERE predicates for ``content_records``.

    Appends bind parameter values to *params* in place.  Always includes
    a clause to exclude records flagged as duplicates via
    ``raw_metadata->>'duplicate_of'``.

    Args:
        query_design_id: Restrict to records belonging to this query design.
        run_id: Restrict to records from this collection run.
        arena: Restrict to a single arena (e.g. ``"news"``).
        platform: Restrict to a single platform (e.g. ``"reddit"``).
        date_from: Inclusive lower bound on ``published_at``.
        date_to: Inclusive upper bound on ``published_at``.
        params: Mutable dict that receives bind parameter values.
        table_alias: Optional table alias prefix (e.g. ``"a."``).  Include
            the trailing dot.

    Returns:
        List of SQL predicate strings (without a leading ``WHERE`` keyword).
        The list is never empty — it always contains at least the duplicate
        exclusion predicate.
    """
    prefix = table_alias
    clauses: list[str] = []

    if query_design_id is not None:
        clauses.append(f"{prefix}query_design_id = :query_design_id")
        params["query_design_id"] = str(query_design_id)

    if run_id is not None:
        # Include both directly collected records AND records linked from
        # other runs via the content_record_links table (cross-design reindex).
        clauses.append(
            f"({prefix}collection_run_id = :run_id"
            f" OR ({prefix}id, {prefix}published_at) IN ("
            f"SELECT content_record_id, content_record_published_at "
            f"FROM content_record_links WHERE collection_run_id = :run_id))"
        )
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

    # Always exclude records that have been flagged as duplicates of another
    # record.  The flag is stored as raw_metadata->>'duplicate_of' IS NOT NULL
    # by the deduplication service.  Using IS NULL on the JSONB text extraction
    # excludes both records where the key is absent and records where the key
    # maps to a JSON null — both mean "not a duplicate".
    clauses.append(f"({prefix}raw_metadata->>'duplicate_of') IS NULL")

    return clauses


def build_content_where(
    query_design_id: uuid.UUID | None,
    run_id: uuid.UUID | None,
    arena: str | None,
    platform: str | None,
    date_from: Any,
    date_to: Any,
    params: dict[str, Any],
) -> str:
    """Return a full ``WHERE …`` SQL fragment for ``content_records`` filters.

    A convenience wrapper around :func:`build_content_filters` for callers
    that embed the full ``WHERE`` clause directly into an f-string SQL query.
    No table alias is applied; use :func:`build_content_filters` directly if
    a table alias is required.

    Appends bind parameter values to *params* in place.

    Args:
        query_design_id: Restrict to records belonging to this query design.
        run_id: Restrict to records from this collection run.
        arena: Restrict to a single arena.
        platform: Restrict to a single platform.
        date_from: Inclusive lower bound on ``published_at``.
        date_to: Inclusive upper bound on ``published_at``.
        params: Mutable dict that receives bind parameter values.

    Returns:
        A SQL string starting with ``WHERE`` followed by the predicate list
        joined with ``AND``.  Always returns a non-empty string because the
        duplicate exclusion predicate is always present.
    """
    clauses = build_content_filters(
        query_design_id, run_id, arena, platform, date_from, date_to, params
    )
    return "WHERE " + " AND ".join(clauses)
