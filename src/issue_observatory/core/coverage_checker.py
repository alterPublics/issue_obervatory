"""Pre-collection coverage checker.

Queries existing ``content_records`` to determine which portions of a
requested date range have already been collected for a given platform,
search terms, and/or actor IDs.  When an overlapping range is found, the
caller can narrow the API request to the uncovered portion only, saving
API credits and avoiding redundant work.

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


def get_covered_ranges(
    platform: str,
    date_from: datetime,
    date_to: datetime,
    search_term: str | None = None,
    actor_platform_id: str | None = None,
) -> list[tuple[datetime, datetime]]:
    """Query content_records for min/max published_at matching criteria.

    Returns a list of (range_start, range_end) tuples representing
    contiguous covered date ranges.  Currently returns a single range
    (min, max) if any matching records exist, or an empty list if none.

    Args:
        platform: Platform identifier (e.g. ``"bluesky"``).
        date_from: Requested start of collection window.
        date_to: Requested end of collection window.
        search_term: Optional search term to match against
            ``search_terms_matched``.
        actor_platform_id: Optional actor platform ID to match against
            ``author_platform_id``.

    Returns:
        List of ``(range_start, range_end)`` tuples.
    """
    from sqlalchemy import text  # noqa: PLC0415

    from issue_observatory.core.database import get_sync_session  # noqa: PLC0415

    clauses = [
        "platform = :platform",
        "published_at >= :date_from",
        "published_at <= :date_to",
        "(raw_metadata->>'duplicate_of') IS NULL",
    ]
    params: dict[str, Any] = {
        "platform": platform,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
    }

    if search_term:
        clauses.append(":search_term = ANY(search_terms_matched)")
        params["search_term"] = search_term

    if actor_platform_id:
        clauses.append("author_platform_id = :actor_platform_id")
        params["actor_platform_id"] = actor_platform_id

    where = " AND ".join(clauses)

    with get_sync_session() as db:
        result = db.execute(
            text(
                f"SELECT MIN(published_at), MAX(published_at), COUNT(*) "  # noqa: S608
                f"FROM content_records WHERE {where}"
            ),
            params,
        )
        row = result.fetchone()

    if not row or row[2] == 0:
        return []

    return [(row[0], row[1])]


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


def check_existing_coverage(
    platform: str,
    date_from: datetime,
    date_to: datetime,
    terms: list[str] | None = None,
    actor_ids: list[str] | None = None,
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
            )
            gaps = compute_uncovered_ranges(date_from, date_to, covered)
            all_gaps.extend(gaps)
    else:
        # No terms or actors — check platform-wide coverage
        covered = get_covered_ranges(
            platform=platform,
            date_from=date_from,
            date_to=date_to,
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
