"""Cross-arena temporal propagation enricher.

GR-08 — Given near-duplicate clusters produced by the SimHash deduplication
system, this enricher orders records within each cluster by ``published_at``
and computes a propagation sequence: which arena published the content first
and how it spread to other arenas over time.

Owned by the Core Application Engineer.

The enrichment result is stored at
``raw_metadata.enrichments.propagation``::

    {
        "cluster_id": "...",
        "origin_arena": "gdelt",
        "origin_platform": "gdelt",
        "origin_published_at": "2026-02-19T14:00:00+00:00",
        "is_origin": true,
        "propagation_sequence": [
            {
                "arena": "news",
                "platform": "dr",
                "published_at": "2026-02-19T15:30:00+00:00",
                "lag_minutes": 90.0
            },
            ...
        ],
        "total_arenas_reached": 4,
        "max_lag_hours": 2.5,
        "computed_at": "2026-02-19T16:00:00+00:00"
    }

For non-origin records ``is_origin`` is ``false``.  The propagation_sequence
is the same for every record in the cluster (it describes the full cluster
spread, not the record's individual position).

Design notes
------------
- Records with ``published_at = None`` are placed at the end of the cluster
  sequence so they do not disrupt temporal ordering of timestamped records.
- A same-arena re-publication (two records with the same ``arena`` value) is
  NOT counted as a cross-arena propagation event.  The propagation_sequence
  only lists arenas that are distinct from each preceding arena entry.
- The enricher operates on a cluster (list of record dicts) rather than a
  single record, because propagation analysis is inherently cluster-scoped.
  The ``enrich()`` method enriches a single record within a cluster context;
  ``enrich_cluster()`` is the primary entry point that returns enrichment
  dicts for every record in the cluster.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from issue_observatory.analysis.enrichments.base import ContentEnricher, EnrichmentError

logger = structlog.get_logger(__name__)


def _parse_published_at(value: Any) -> datetime | None:
    """Coerce a raw ``published_at`` value to an aware datetime or None.

    Accepts:
    - ``datetime`` objects (naive datetimes are treated as UTC).
    - ISO 8601 strings with or without timezone offset.
    - ``None`` / empty string → returns ``None``.

    Args:
        value: Raw value from a content record dict.

    Returns:
        A timezone-aware ``datetime`` or ``None`` when the value is absent or
        unparseable.
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
                "propagation_detector: unparseable published_at; treating as None",
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


class PropagationEnricher(ContentEnricher):
    """Compute cross-arena temporal propagation for a near-duplicate cluster.

    enricher_name = "propagation"

    This enricher operates on a **cluster** of content records that share the
    same ``near_duplicate_cluster_id``.  Call :meth:`enrich_cluster` with the
    full list of records in the cluster; it returns a dict mapping each
    record's ``id`` to its enrichment payload.

    The standard :meth:`enrich` method is provided for compatibility with the
    ``ContentEnricher`` ABC but raises ``EnrichmentError`` when called without
    cluster context — use :meth:`enrich_cluster` instead for cluster-scoped
    propagation analysis.

    Ordering rules:

    1. Records with a valid ``published_at`` are sorted ascending by timestamp.
    2. Records with ``published_at = None`` are appended at the end (treated as
       unknowns; they cannot be the origin).

    Propagation sequence rules:

    - The sequence lists arenas distinct from the origin arena in chronological
      order of first appearance.
    - If the same arena appears multiple times (re-publication within the same
      arena), only the *first* appearance in the sorted order is emitted as a
      propagation event.  Subsequent appearances of an already-listed arena are
      silently skipped.
    - A cluster must span at least 2 distinct arenas to generate a meaningful
      propagation sequence; single-arena clusters receive an empty sequence.
    """

    enricher_name = "propagation"

    # ------------------------------------------------------------------
    # ContentEnricher interface
    # ------------------------------------------------------------------

    def is_applicable(self, record: dict[str, Any]) -> bool:
        """Return True when the record belongs to a near-duplicate cluster.

        Checks for a non-empty ``near_duplicate_cluster_id`` key in the record
        dict (column name used by the ORM).

        Args:
            record: A content record dict with keys matching ORM column names.

        Returns:
            True when ``near_duplicate_cluster_id`` is present and non-None.
        """
        return bool(record.get("near_duplicate_cluster_id"))

    async def enrich(self, record: dict[str, Any]) -> dict[str, Any]:
        """Single-record entry point — raises EnrichmentError.

        Propagation analysis is inherently cluster-scoped.  Use
        :meth:`enrich_cluster` with the full list of cluster members instead.

        Args:
            record: A content record dict.

        Raises:
            EnrichmentError: Always, because propagation requires cluster
                context that a single-record call cannot provide.
        """
        raise EnrichmentError(
            "PropagationEnricher.enrich() requires cluster context. "
            "Use enrich_cluster(records) with all records in the cluster."
        )

    # ------------------------------------------------------------------
    # Primary cluster-scoped entry point
    # ------------------------------------------------------------------

    async def enrich_cluster(
        self,
        records: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Compute propagation enrichment for every record in a cluster.

        Sorts the cluster by ``published_at`` ascending (None at end), elects
        the first timestamped record as the origin, builds the propagation
        sequence, and returns one enrichment dict per record id.

        Args:
            records: All content record dicts in the near-duplicate cluster.
                Each dict must contain at least: ``id``, ``arena``,
                ``platform``, ``published_at``.

        Returns:
            A dict mapping each record's ``id`` (as str) to its propagation
            enrichment payload.  The payload can be merged into
            ``raw_metadata.enrichments.propagation`` for each record.

        Raises:
            EnrichmentError: If the cluster is empty.
        """
        if not records:
            raise EnrichmentError("PropagationEnricher.enrich_cluster: empty cluster")

        computed_at: str = datetime.now(tz=timezone.utc).isoformat()

        # Determine cluster_id from the first record (all should share it)
        cluster_id: str | None = str(records[0].get("near_duplicate_cluster_id") or "")

        # Sort: records with published_at first (ascending), None at the end
        def _sort_key(rec: dict[str, Any]) -> tuple[int, datetime]:
            dt = _parse_published_at(rec.get("published_at"))
            if dt is None:
                # Use a sentinel max date so None-timestamped records sort last
                return (1, datetime.max.replace(tzinfo=timezone.utc))
            return (0, dt)

        sorted_records = sorted(records, key=_sort_key)

        # Elect origin: first record with a non-None published_at
        origin_record: dict[str, Any] | None = None
        for rec in sorted_records:
            if _parse_published_at(rec.get("published_at")) is not None:
                origin_record = rec
                break

        # If all records lack timestamps, fall back to first sorted record
        if origin_record is None:
            origin_record = sorted_records[0]

        origin_dt = _parse_published_at(origin_record.get("published_at"))
        origin_arena: str = str(origin_record.get("arena") or "")
        origin_platform: str = str(origin_record.get("platform") or "")
        origin_published_at_str: str | None = _iso(origin_dt)
        origin_id: str = str(origin_record.get("id") or "")

        # Build propagation sequence.
        # Track which arenas we have already emitted to avoid listing the same
        # arena more than once (including the origin arena itself).
        seen_arenas: set[str] = {origin_arena}
        propagation_sequence: list[dict[str, Any]] = []

        for rec in sorted_records:
            rec_id = str(rec.get("id") or "")
            if rec_id == origin_id:
                continue  # skip origin record

            rec_arena = str(rec.get("arena") or "")
            if rec_arena in seen_arenas:
                # Same arena re-publication — not a cross-arena propagation event
                continue

            seen_arenas.add(rec_arena)

            rec_platform = str(rec.get("platform") or "")
            rec_dt = _parse_published_at(rec.get("published_at"))
            rec_published_at_str = _iso(rec_dt)

            # Compute lag relative to origin
            lag_minutes: float | None = None
            if origin_dt is not None and rec_dt is not None:
                delta_seconds = (rec_dt - origin_dt).total_seconds()
                lag_minutes = round(delta_seconds / 60.0, 2)

            propagation_sequence.append(
                {
                    "arena": rec_arena,
                    "platform": rec_platform,
                    "published_at": rec_published_at_str,
                    "lag_minutes": lag_minutes,
                }
            )

        # Summary metrics
        total_arenas_reached: int = len(seen_arenas)  # includes origin arena

        max_lag_hours: float | None = None
        if propagation_sequence:
            lag_values = [
                e["lag_minutes"]
                for e in propagation_sequence
                if e["lag_minutes"] is not None
            ]
            if lag_values:
                max_lag_hours = round(max(lag_values) / 60.0, 4)

        # Base payload shared across all records in the cluster
        base_payload: dict[str, Any] = {
            "cluster_id": cluster_id,
            "origin_arena": origin_arena,
            "origin_platform": origin_platform,
            "origin_published_at": origin_published_at_str,
            "propagation_sequence": propagation_sequence,
            "total_arenas_reached": total_arenas_reached,
            "max_lag_hours": max_lag_hours,
            "computed_at": computed_at,
        }

        # Build per-record payloads
        result: dict[str, dict[str, Any]] = {}
        for rec in records:
            rec_id = str(rec.get("id") or "")
            is_origin = rec_id == origin_id
            payload = {**base_payload, "is_origin": is_origin}
            result[rec_id] = payload

        log = logger.bind(
            enricher=self.enricher_name,
            cluster_id=cluster_id,
            records=len(records),
            total_arenas_reached=total_arenas_reached,
            propagation_steps=len(propagation_sequence),
            max_lag_hours=max_lag_hours,
        )
        log.debug("propagation_detector: cluster enriched")

        return result
