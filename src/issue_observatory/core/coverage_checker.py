"""Pre-collection coverage checker.

Queries the lightweight ``collection_attempts`` metadata table to determine
which portions of a requested date range have already been collected for a
given platform, search terms, and/or actor IDs.  When an overlapping range
is found, the caller can narrow the API request to the uncovered portion
only, saving API credits and avoiding redundant work.

Two-tier lookup strategy
------------------------
1. **Fast path** — query ``collection_attempts`` (tiny metadata table).
   This is the normal case and completes in microseconds.
2. **Slow fallback** — if the fast path finds no recent/valid coverage
   (e.g. attempts are older than the staleness window, or were never
   recorded), fall back to scanning ``content_records`` directly.
   This is slower but ensures that *existing data is never re-collected*
   regardless of whether the metadata table is up-to-date.

The fallback also re-records a fresh ``collection_attempts`` row so
subsequent checks can use the fast path again.

Safety guards
-------------
- **Only successful attempts count**: ``records_returned > 0`` — failed
  attempts (NULL) and zero-result attempts are excluded on the fast path.
- **Staleness window**: Attempts older than ``max_attempt_age_days`` are
  skipped by the fast path, triggering the slow fallback instead.
- **Validity flag**: The reconciliation routine can mark attempts as
  ``is_valid = FALSE`` when underlying data is gone.  Invalid attempts
  are skipped by the fast path.
- **force_recollect**: Arena tasks pass ``force_recollect=True`` to
  bypass the check entirely when the researcher wants fresh API data.

Usage from arena Celery tasks::

    from issue_observatory.core.coverage_checker import check_existing_coverage

    gaps = check_existing_coverage(
        platform="bluesky",
        date_from=datetime(2026, 1, 1),
        date_to=datetime(2026, 1, 21),
        terms=["klima"],
    )
    # gaps is a list of (gap_from, gap_to) datetime tuples
    # If empty, the range is fully covered — skip the API call.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Default: fast-path metadata older than 90 days triggers the slow fallback.
DEFAULT_MAX_ATTEMPT_AGE_DAYS = 90


# ---------------------------------------------------------------------------
# Tier 1: fast path — collection_attempts metadata table
# ---------------------------------------------------------------------------


def _get_covered_ranges_from_attempts(
    platform: str,
    date_from: datetime,
    date_to: datetime,
    search_term: str | None = None,
    actor_platform_id: str | None = None,
    max_attempt_age_days: int = DEFAULT_MAX_ATTEMPT_AGE_DAYS,
) -> list[tuple[datetime, datetime]]:
    """Fast path: query the small ``collection_attempts`` metadata table.

    Only considers recent, valid, successful attempts.  Returns empty list
    when no qualifying attempts exist — the caller should then try the
    slow fallback.
    """
    from sqlalchemy import text  # noqa: PLC0415

    from issue_observatory.core.database import get_sync_session  # noqa: PLC0415

    if search_term:
        input_value = search_term
        input_type = "term"
    elif actor_platform_id:
        input_value = actor_platform_id
        input_type = "actor"
    else:
        input_value = None
        input_type = None

    clauses = [
        "platform = :platform",
        "records_returned > 0",
        "is_valid = TRUE",
        "attempted_at >= NOW() - CAST(:max_age AS interval)",
    ]
    params: dict[str, Any] = {
        "platform": platform,
        "max_age": f"{max_attempt_age_days} days",
    }

    if input_value is not None:
        clauses.append("input_value = :input_value")
        clauses.append("input_type = :input_type")
        params["input_value"] = input_value
        params["input_type"] = input_type

    clauses.append("date_to >= CAST(:req_from AS timestamptz)")
    clauses.append("date_from <= CAST(:req_to AS timestamptz)")
    params["req_from"] = date_from.isoformat()
    params["req_to"] = date_to.isoformat()

    where = " AND ".join(clauses)

    with get_sync_session() as db:
        result = db.execute(
            text(
                f"SELECT MIN(date_from), MAX(date_to) "  # noqa: S608
                f"FROM collection_attempts WHERE {where}"
            ),
            params,
        )
        row = result.fetchone()

    if not row or row[0] is None:
        return []

    return [(row[0], row[1])]


# ---------------------------------------------------------------------------
# Tier 2: slow fallback — content_records table
# ---------------------------------------------------------------------------


def _get_covered_ranges_from_content(
    platform: str,
    date_from: datetime,
    date_to: datetime,
    search_term: str | None = None,
    actor_platform_id: str | None = None,
) -> list[tuple[datetime, datetime]]:
    """Slow fallback: query ``content_records`` directly.

    Used only when the fast path finds no qualifying metadata.  Queries
    the partitioned ``content_records`` table with partition-pruning-friendly
    predicates.  Slower than the fast path but guarantees we never
    re-collect data that already exists in the database.

    Uses the ``@>`` operator for GIN-index-compatible term matching and
    the B-tree index on ``author_platform_id`` for actor matching.
    """
    from sqlalchemy import text  # noqa: PLC0415

    from issue_observatory.core.database import get_sync_session  # noqa: PLC0415

    clauses = [
        "platform = :platform",
        "published_at >= CAST(:date_from AS timestamptz)",
        "published_at <= CAST(:date_to AS timestamptz)",
    ]
    params: dict[str, Any] = {
        "platform": platform,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
    }

    if search_term:
        clauses.append("search_terms_matched @> CAST(:search_term_arr AS text[])")
        escaped = search_term.replace("\\", "\\\\").replace('"', '\\"')
        params["search_term_arr"] = "{" + escaped + "}"

    if actor_platform_id:
        clauses.append("author_platform_id = :actor_platform_id")
        params["actor_platform_id"] = actor_platform_id

    where = " AND ".join(clauses)

    with get_sync_session() as db:
        result = db.execute(
            text(
                f"SELECT MIN(published_at), MAX(published_at) "  # noqa: S608
                f"FROM content_records WHERE {where}"
            ),
            params,
        )
        row = result.fetchone()

    if not row or row[0] is None:
        return []

    logger.info(
        "coverage_checker: fallback found data in content_records for "
        "platform=%s term=%r actor=%r range=%s..%s",
        platform,
        search_term,
        actor_platform_id,
        row[0],
        row[1],
    )
    return [(row[0], row[1])]


def _backfill_attempt_from_fallback(
    platform: str,
    date_from: datetime,
    date_to: datetime,
    search_term: str | None,
    actor_platform_id: str | None,
) -> None:
    """Re-record a collection_attempts row after the slow fallback finds data.

    This allows subsequent coverage checks to use the fast path instead of
    falling back to content_records again.  Uses a synthetic
    ``records_returned = 1`` (we know data exists but don't have the exact
    count without an expensive COUNT query).
    """
    from sqlalchemy import text  # noqa: PLC0415

    from issue_observatory.core.database import get_sync_session  # noqa: PLC0415

    if search_term:
        input_value = search_term
        input_type = "term"
    elif actor_platform_id:
        input_value = actor_platform_id
        input_type = "actor"
    else:
        # Platform-wide — use a sentinel value.
        input_value = "__platform_wide__"
        input_type = "term"

    try:
        with get_sync_session() as db:
            db.execute(
                text(
                    "INSERT INTO collection_attempts "
                    "(platform, input_value, input_type, date_from, date_to, "
                    "records_returned, collection_run_id, query_design_id) "
                    "VALUES (:platform, :input_value, :input_type, "
                    "CAST(:date_from AS timestamptz), "
                    "CAST(:date_to AS timestamptz), "
                    "1, NULL, NULL)"
                ),
                {
                    "platform": platform,
                    "input_value": input_value,
                    "input_type": input_type,
                    "date_from": date_from.isoformat(),
                    "date_to": date_to.isoformat(),
                },
            )
            db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "coverage_checker: backfill attempt recording failed (non-critical): %s",
            exc,
        )


# ---------------------------------------------------------------------------
# Combined two-tier lookup
# ---------------------------------------------------------------------------


def get_covered_ranges(
    platform: str,
    date_from: datetime,
    date_to: datetime,
    search_term: str | None = None,
    actor_platform_id: str | None = None,
    max_attempt_age_days: int = DEFAULT_MAX_ATTEMPT_AGE_DAYS,
) -> list[tuple[datetime, datetime]]:
    """Two-tier coverage lookup: fast metadata path, then slow data fallback.

    1. Query ``collection_attempts`` for recent, valid, successful attempts.
    2. If nothing found, fall back to scanning ``content_records`` directly
       so that existing data is never re-collected even if the metadata is
       stale or missing.

    Args:
        platform: Platform identifier (e.g. ``"bluesky"``).
        date_from: Requested start of collection window.
        date_to: Requested end of collection window.
        search_term: Optional search term (``input_type='term'``).
        actor_platform_id: Optional actor platform ID (``input_type='actor'``).
        max_attempt_age_days: Fast-path staleness cutoff in days.

    Returns:
        List of ``(range_start, range_end)`` tuples, or empty list.
    """
    # Tier 1: fast path — metadata table.
    covered = _get_covered_ranges_from_attempts(
        platform=platform,
        date_from=date_from,
        date_to=date_to,
        search_term=search_term,
        actor_platform_id=actor_platform_id,
        max_attempt_age_days=max_attempt_age_days,
    )
    if covered:
        return covered

    # Tier 2: slow fallback — scan content_records directly.
    logger.debug(
        "coverage_checker: no recent metadata for platform=%s term=%r actor=%r "
        "— falling back to content_records scan",
        platform,
        search_term,
        actor_platform_id,
    )
    covered = _get_covered_ranges_from_content(
        platform=platform,
        date_from=date_from,
        date_to=date_to,
        search_term=search_term,
        actor_platform_id=actor_platform_id,
    )

    # If the fallback found data, backfill a fresh metadata row so future
    # checks can use the fast path.
    if covered:
        _backfill_attempt_from_fallback(
            platform=platform,
            date_from=covered[0][0],
            date_to=covered[0][1],
            search_term=search_term,
            actor_platform_id=actor_platform_id,
        )

    return covered


# ---------------------------------------------------------------------------
# Gap computation
# ---------------------------------------------------------------------------


def compute_uncovered_ranges(
    requested_from: datetime,
    requested_to: datetime,
    covered_ranges: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Compute date gaps not yet covered by existing records.

    Given a requested date range and a list of covered ranges, returns the
    uncovered gaps.  Uses a 1-day buffer to account for partial daily coverage.

    Args:
        requested_from: Start of the requested collection window.
        requested_to: End of the requested collection window.
        covered_ranges: Sorted list of ``(start, end)`` tuples from
            :func:`get_covered_ranges`.

    Returns:
        List of ``(gap_from, gap_to)`` tuples representing uncovered portions.
        Empty list means the range is fully covered.
    """
    if not covered_ranges:
        return [(requested_from, requested_to)]

    gaps: list[tuple[datetime, datetime]] = []
    cursor = requested_from

    for cov_start, cov_end in sorted(covered_ranges):
        # Ensure both are tz-aware for comparison
        if cov_start.tzinfo is None:
            cov_start = cov_start.replace(tzinfo=timezone.utc)
        if cov_end.tzinfo is None:
            cov_end = cov_end.replace(tzinfo=timezone.utc)
        if cursor.tzinfo is None:
            cursor = cursor.replace(tzinfo=timezone.utc)

        # Add 1-day buffer to avoid re-fetching partial days
        buffer = timedelta(days=1)

        if cov_start - buffer > cursor:
            gaps.append((cursor, cov_start - buffer))

        if cov_end + buffer > cursor:
            cursor = cov_end + buffer

    req_to = requested_to
    if req_to.tzinfo is None:
        req_to = req_to.replace(tzinfo=timezone.utc)

    if cursor < req_to:
        gaps.append((cursor, req_to))

    return gaps


# ---------------------------------------------------------------------------
# High-level API
# ---------------------------------------------------------------------------


def check_existing_coverage(
    platform: str,
    date_from: datetime,
    date_to: datetime,
    terms: list[str] | None = None,
    actor_ids: list[str] | None = None,
    max_attempt_age_days: int = DEFAULT_MAX_ATTEMPT_AGE_DAYS,
) -> list[tuple[datetime, datetime]]:
    """High-level check returning uncovered date gaps.

    Checks coverage for each term/actor and returns the UNION of all
    uncovered ranges (conservative: if ANY term has a gap, that gap is
    returned).

    Args:
        platform: Platform identifier.
        date_from: Start of collection window.
        date_to: End of collection window.
        terms: Optional search terms to check coverage for.
        actor_ids: Optional actor platform IDs to check coverage for.
        max_attempt_age_days: Fast-path staleness cutoff in days.

    Returns:
        List of ``(gap_from, gap_to)`` datetime tuples.  Empty list means
        full coverage exists — the caller can skip the API call.
    """
    # Ensure tz-aware
    if date_from.tzinfo is None:
        date_from = date_from.replace(tzinfo=timezone.utc)
    if date_to.tzinfo is None:
        date_to = date_to.replace(tzinfo=timezone.utc)

    all_gaps: list[tuple[datetime, datetime]] = []

    if terms:
        for term in terms:
            covered = get_covered_ranges(
                platform=platform,
                date_from=date_from,
                date_to=date_to,
                search_term=term,
                max_attempt_age_days=max_attempt_age_days,
            )
            gaps = compute_uncovered_ranges(date_from, date_to, covered)
            all_gaps.extend(gaps)
    elif actor_ids:
        for actor_id in actor_ids:
            covered = get_covered_ranges(
                platform=platform,
                date_from=date_from,
                date_to=date_to,
                actor_platform_id=actor_id,
                max_attempt_age_days=max_attempt_age_days,
            )
            gaps = compute_uncovered_ranges(date_from, date_to, covered)
            all_gaps.extend(gaps)
    else:
        # No terms or actors — check platform-wide coverage
        covered = get_covered_ranges(
            platform=platform,
            date_from=date_from,
            date_to=date_to,
            max_attempt_age_days=max_attempt_age_days,
        )
        all_gaps = compute_uncovered_ranges(date_from, date_to, covered)

    if all_gaps:
        # Merge overlapping gaps into a single consolidated list
        merged = _merge_ranges(all_gaps)
        logger.info(
            "coverage_checker: platform=%s has %d uncovered gap(s) in %s to %s",
            platform,
            len(merged),
            date_from.isoformat(),
            date_to.isoformat(),
        )
        return merged

    logger.info(
        "coverage_checker: platform=%s fully covered for %s to %s",
        platform,
        date_from.isoformat(),
        date_to.isoformat(),
    )
    return []


def _merge_ranges(
    ranges: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Merge overlapping or adjacent datetime ranges.

    Args:
        ranges: List of ``(start, end)`` tuples, possibly overlapping.

    Returns:
        Sorted, merged list of non-overlapping ``(start, end)`` tuples.
    """
    if not ranges:
        return []

    sorted_ranges = sorted(ranges, key=lambda r: r[0])
    merged: list[tuple[datetime, datetime]] = [sorted_ranges[0]]

    for current_start, current_end in sorted_ranges[1:]:
        last_start, last_end = merged[-1]
        if current_start <= last_end:
            merged[-1] = (last_start, max(last_end, current_end))
        else:
            merged.append((current_start, current_end))

    return merged
