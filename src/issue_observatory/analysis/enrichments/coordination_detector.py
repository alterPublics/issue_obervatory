"""Coordinated inauthentic behaviour (CIB) detection enricher.

GR-11 — Given near-duplicate clusters produced by the SimHash deduplication
system, this enricher looks for multiple *distinct* authors posting
near-identical content within a narrow time window — a weak but useful signal
for information operations targeting the Greenland discourse dataset.

Owned by the Core Application Engineer.

The enrichment result is stored at
``raw_metadata.enrichments.coordination``::

    {
        "cluster_id": "...",
        "flagged": true,
        "distinct_authors_in_window": 12,
        "time_window_hours": 1.0,
        "coordination_score": 0.85,
        "earliest_in_window": "2026-02-19T14:00:00+00:00",
        "latest_in_window": "2026-02-19T14:45:00+00:00",
        "platforms_involved": ["telegram", "gab", "reddit"],
        "computed_at": "2026-02-19T16:00:00+00:00"
    }

For records in clusters that do NOT meet the threshold::

    {
        "cluster_id": "...",
        "flagged": false,
        "distinct_authors_in_window": 2,
        "computed_at": "..."
    }

Design notes
------------
- The enricher scans *all* time windows of width ``time_window_hours`` anchored
  at each timestamped record in the cluster (sliding-window approach).  The
  window that contains the most distinct authors is used to compute the
  coordination score.
- Records with ``author_id = None`` or an empty ``author_id`` are excluded from
  the distinct-author count; their presence does not inflate or deflate the
  signal.
- Records without a ``published_at`` timestamp are excluded from the time-window
  calculation but are still tagged with the cluster-level result.
- The ``coordination_score`` is the ratio of distinct authors in the best window
  to the maximum distinct-author count found across all clusters processed in
  the same batch (normalised 0–1).  When only one cluster is processed, the
  score is 1.0 for flagged clusters and 0.0 for non-flagged clusters.
- The enricher operates on a cluster (list of record dicts) rather than a
  single record.  ``enrich_cluster()`` is the primary entry point; ``enrich()``
  raises ``EnrichmentError`` because coordination analysis is inherently
  cluster-scoped.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from issue_observatory.analysis.enrichments.base import ContentEnricher, EnrichmentError

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Module-level helpers (mirroring propagation_detector.py conventions)
# ---------------------------------------------------------------------------


def _parse_published_at(value: Any) -> datetime | None:
    """Coerce a raw ``published_at`` value to an aware datetime or None.

    Accepts datetime objects (naive datetimes treated as UTC), ISO 8601
    strings with or without timezone offset, and None / empty string.

    Args:
        value: Raw value from a content record dict.

    Returns:
        A timezone-aware ``datetime`` or ``None`` when absent or unparseable.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            dt = datetime.fromisoformat(stripped)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            logger.warning(
                "coordination_detector: unparseable published_at; treating as None",
                value=stripped,
            )
            return None
    return None


def _iso(dt: datetime | None) -> str | None:
    """Return ISO 8601 string for a datetime, or None when absent.

    Args:
        dt: A datetime object or None.

    Returns:
        ISO 8601 string (always UTC-offset aware) or None.
    """
    if dt is None:
        return None
    return dt.isoformat()


# ---------------------------------------------------------------------------
# CoordinationDetector
# ---------------------------------------------------------------------------


class CoordinationDetector(ContentEnricher):
    """Detect potential coordinated inauthentic behaviour in a near-duplicate cluster.

    enricher_name = "coordination"

    Coordination is flagged when ``distinct_authors >= coordination_threshold``
    within any ``time_window_hours``-wide window anchored at each timestamped
    record in the cluster.

    The ``coordination_score`` for flagged clusters is the ratio of
    ``distinct_authors_in_window`` to ``max_distinct_authors_any_window``,
    normalised 0–1 across all clusters processed in the same
    :meth:`enrich_cluster` call.  Because :meth:`enrich_cluster` processes a
    single cluster at a time, callers that want a meaningful relative score
    should compute the normalisation factor externally (e.g. in
    :meth:`~issue_observatory.core.deduplication.DeduplicationService.run_coordination_analysis`).
    Within a single cluster, the score is set to 1.0 for flagged clusters and
    0.0 for non-flagged clusters unless ``max_distinct_authors`` is supplied.

    Args:
        coordination_threshold: Minimum number of distinct authors within the
            time window that triggers a coordination flag.  Defaults to 5.
        time_window_hours: Width of the sliding time window in hours.
            Defaults to 1.0.
    """

    enricher_name = "coordination"

    def __init__(
        self,
        coordination_threshold: int = 5,
        time_window_hours: float = 1.0,
    ) -> None:
        """Initialise the detector with configurable threshold and window size.

        Args:
            coordination_threshold: Distinct-author count that triggers a CIB
                flag.  Must be >= 2; values < 2 are clamped to 2.
            time_window_hours: Sliding window width in hours.  Must be > 0.
        """
        self.coordination_threshold: int = max(2, coordination_threshold)
        self.time_window_hours: float = max(0.001, time_window_hours)

    # ------------------------------------------------------------------
    # ContentEnricher interface
    # ------------------------------------------------------------------

    def is_applicable(self, record: dict[str, Any]) -> bool:
        """Return True when the record belongs to a near-duplicate cluster.

        Args:
            record: A content record dict with keys matching ORM column names.

        Returns:
            True when ``near_duplicate_cluster_id`` is present and non-None.
        """
        return bool(record.get("near_duplicate_cluster_id"))

    async def enrich(self, record: dict[str, Any]) -> dict[str, Any]:
        """Single-record entry point — raises EnrichmentError.

        Coordination analysis is inherently cluster-scoped.  Use
        :meth:`enrich_cluster` with the full list of cluster members instead.

        Args:
            record: A content record dict.

        Raises:
            EnrichmentError: Always, because coordination analysis requires
                cluster context that a single-record call cannot provide.
        """
        raise EnrichmentError(
            "CoordinationDetector.enrich() requires cluster context. "
            "Use enrich_cluster(records) with all records in the cluster."
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_best_window(
        self,
        timestamped: list[tuple[datetime, str | None, str]],
    ) -> tuple[int, datetime | None, datetime | None, list[str]]:
        """Find the time window with the most distinct authors.

        Uses a sliding-window approach anchored at each record's timestamp.
        The window spans ``[anchor, anchor + time_window_hours)``.

        Args:
            timestamped: Sorted list of ``(published_at, author_id, platform)``
                tuples for records that have a valid ``published_at``.
                ``author_id`` may be None.

        Returns:
            A 4-tuple of:

            - ``best_distinct_authors`` (int): Highest distinct-author count
              found in any window.  0 if no window had any known author.
            - ``earliest_in_window`` (datetime | None): Start of the best
              window (the anchor timestamp).
            - ``latest_in_window`` (datetime | None): Timestamp of the last
              record in the best window.
            - ``platforms_in_window`` (list[str]): Sorted list of distinct
              platform values in the best window.
        """
        if not timestamped:
            return 0, None, None, []

        window_delta = timedelta(hours=self.time_window_hours)
        best_count: int = 0
        best_earliest: datetime | None = None
        best_latest: datetime | None = None
        best_platforms: list[str] = []

        n = len(timestamped)
        right = 0

        # Sliding window: anchor at each record i, expand right while within window.
        for left in range(n):
            anchor_dt = timestamped[left][0]
            window_end = anchor_dt + window_delta

            # Advance right pointer while records are inside the window.
            while right < n and timestamped[right][0] < window_end:
                right += 1

            # All records in [left, right) fall within [anchor, anchor + window).
            window_records = timestamped[left:right]
            distinct_authors: set[str] = set()
            platforms: set[str] = set()
            latest_dt: datetime | None = None

            for dt, author_id, platform in window_records:
                if author_id:
                    distinct_authors.add(author_id)
                platforms.add(platform)
                if latest_dt is None or dt > latest_dt:
                    latest_dt = dt

            count = len(distinct_authors)
            if count > best_count:
                best_count = count
                best_earliest = anchor_dt
                best_latest = latest_dt
                best_platforms = sorted(platforms)

        return best_count, best_earliest, best_latest, best_platforms

    # ------------------------------------------------------------------
    # Primary cluster-scoped entry point
    # ------------------------------------------------------------------

    async def enrich_cluster(
        self,
        records: list[dict[str, Any]],
        max_distinct_authors: int | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Compute coordination enrichment for every record in a cluster.

        Scans the cluster for the time window with the highest number of
        distinct authors, checks it against ``coordination_threshold``, and
        returns one enrichment dict per record id.

        Args:
            records: All content record dicts in the near-duplicate cluster.
                Each dict should contain at least: ``id``, ``author_id``,
                ``platform``, ``published_at``, ``near_duplicate_cluster_id``.
            max_distinct_authors: The maximum distinct-author count found
                across all clusters in the current batch, used to normalise the
                ``coordination_score`` to [0, 1].  When ``None``, the score is
                1.0 for flagged clusters and 0.0 for non-flagged clusters.

        Returns:
            A dict mapping each record's ``id`` (as str) to its coordination
            enrichment payload.  The payload should be merged into
            ``raw_metadata.enrichments.coordination`` for each record.

        Raises:
            EnrichmentError: If the cluster is empty.
        """
        if not records:
            raise EnrichmentError(
                "CoordinationDetector.enrich_cluster: empty cluster"
            )

        computed_at: str = datetime.now(tz=timezone.utc).isoformat()
        cluster_id: str = str(records[0].get("near_duplicate_cluster_id") or "")

        # Build a sorted list of (published_at, author_id, platform) for
        # records that have a valid timestamp.
        timestamped: list[tuple[datetime, str | None, str]] = []
        for rec in records:
            dt = _parse_published_at(rec.get("published_at"))
            if dt is None:
                continue
            author_id_val = rec.get("author_id")
            author_id: str | None = str(author_id_val) if author_id_val else None
            platform: str = str(rec.get("platform") or "")
            timestamped.append((dt, author_id, platform))

        timestamped.sort(key=lambda t: t[0])

        best_distinct, earliest, latest, platforms_involved = self._find_best_window(
            timestamped
        )

        flagged: bool = best_distinct >= self.coordination_threshold

        # Compute normalised coordination_score.
        if max_distinct_authors is not None and max_distinct_authors > 0:
            coordination_score: float = round(best_distinct / max_distinct_authors, 4)
        elif flagged:
            coordination_score = 1.0
        else:
            coordination_score = 0.0

        # Build base payload for all records in the cluster.
        base_payload: dict[str, Any] = {
            "cluster_id": cluster_id,
            "flagged": flagged,
            "distinct_authors_in_window": best_distinct,
            "time_window_hours": self.time_window_hours,
            "computed_at": computed_at,
        }

        if flagged:
            base_payload.update(
                {
                    "coordination_score": coordination_score,
                    "earliest_in_window": _iso(earliest),
                    "latest_in_window": _iso(latest),
                    "platforms_involved": platforms_involved,
                }
            )

        result: dict[str, dict[str, Any]] = {}
        for rec in records:
            rec_id = str(rec.get("id") or "")
            result[rec_id] = dict(base_payload)

        log = logger.bind(
            enricher=self.enricher_name,
            cluster_id=cluster_id,
            records=len(records),
            timestamped_records=len(timestamped),
            distinct_authors_in_window=best_distinct,
            flagged=flagged,
            coordination_threshold=self.coordination_threshold,
        )
        log.debug("coordination_detector: cluster enriched")

        return result
