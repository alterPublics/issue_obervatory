"""Volume spike detection for Issue Observatory.

Implements GR-09: threshold-based alerting that fires when collection volume
for an arena exceeds 2x the rolling 7-day average.  Spike events are stored
in ``collection_runs.arenas_config`` (JSONB) under the reserved key
``"_volume_spikes"`` — no new DB table or migration required.

This module contains the spike detection logic and the :class:`VolumeSpike`
data model.  Persistence and email notification are split into
:mod:`issue_observatory.analysis._alerting_store` to keep each file under
400 lines.

All public symbols are re-exported here so callers only need to import from
this module::

    from issue_observatory.analysis.alerting import (
        VolumeSpike,
        detect_volume_spikes,
        store_volume_spikes,
        fetch_recent_volume_spikes,
        send_volume_spike_alert,
    )

Design notes
------------
- All DB queries use raw ``sqlalchemy.text()`` for consistency with
  ``descriptive.py`` and to keep PostgreSQL-specific constructs explicit.
- The rolling average is computed from the 7 most-recent *completed* runs
  prior to the current one, not from a calendar window, so gaps in the
  schedule (weekends, holidays) do not distort the baseline.
- A minimum absolute count of 10 guards against false positives when a query
  design has very few results (ratio arithmetic is not meaningful at n<10).
- The function returns an empty list and logs a warning rather than raising
  when there is insufficient history, so callers need no special-case logic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Re-export persistence and notification helpers for a single import surface.
from issue_observatory.analysis._alerting_store import (  # noqa: F401
    fetch_recent_volume_spikes,
    send_volume_spike_alert,
    store_volume_spikes,
)

logger = structlog.get_logger(__name__)

#: Minimum absolute item count to trigger a spike alert.
#: Prevents false positives when the rolling average is very small.
_MIN_ABSOLUTE_COUNT: int = 10

#: Number of previous completed runs used to compute the rolling average.
_ROLLING_WINDOW: int = 7


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class VolumeSpike:
    """A single arena/platform that exceeded the volume spike threshold.

    Attributes:
        arena_name: Arena category (e.g. ``"social"``, ``"news"``).
        platform: Specific platform slug (e.g. ``"bluesky"``, ``"reddit"``).
        current_count: Number of records collected in the triggering run.
        rolling_7d_average: Mean records per completed run over the previous
            7 runs for this arena/platform combination.
        ratio: ``current_count / rolling_7d_average``.
        top_terms: Up to 3 search terms most frequently matched in the
            spiking records.
    """

    arena_name: str
    platform: str
    current_count: int
    rolling_7d_average: float
    ratio: float
    top_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation of this spike.

        Returns:
            Dict with all spike fields in snake_case.
        """
        return {
            "arena_name": self.arena_name,
            "platform": self.platform,
            "current_count": self.current_count,
            "rolling_7d_average": round(self.rolling_7d_average, 2),
            "ratio": round(self.ratio, 2),
            "top_terms": self.top_terms,
        }


# ---------------------------------------------------------------------------
# Core detection logic
# ---------------------------------------------------------------------------


async def detect_volume_spikes(
    session: AsyncSession,
    query_design_id: uuid.UUID,
    collection_run_id: uuid.UUID,
    threshold_multiplier: float = 2.0,
) -> list[VolumeSpike]:
    """Detect arenas where volume exceeds threshold x 7-day rolling average.

    Algorithm:
    1. Compute per-arena/platform item counts for the current run by querying
       ``content_records`` filtered to ``collection_run_id``.
    2. For each arena/platform, find the 7 most-recent *completed* runs for
       the same ``query_design_id`` *prior to* the current run.
    3. Compute the mean record count across those 7 runs.
    4. If the current count > ``threshold_multiplier * rolling_average`` AND
       current count >= ``_MIN_ABSOLUTE_COUNT``, record a spike.
    5. For each spike, fetch the top-3 search terms by match frequency from
       the spiking records.

    Returns an empty list if the query design has fewer than
    ``_ROLLING_WINDOW`` completed prior runs (insufficient history).

    Args:
        session: Active async database session.
        query_design_id: UUID of the query design being monitored.
        collection_run_id: UUID of the just-completed collection run.
        threshold_multiplier: Ratio threshold above which a spike is declared.
            Defaults to 2.0 (200% of the rolling average).

    Returns:
        List of :class:`VolumeSpike` objects, one per spiking arena/platform.
        Empty when no spikes are detected or when history is insufficient.
    """
    log = logger.bind(
        query_design_id=str(query_design_id),
        collection_run_id=str(collection_run_id),
        threshold=threshold_multiplier,
    )

    # --- Step 1: current run per-arena/platform counts ----------------------
    current_counts_sql = text(
        """
        SELECT
            arena,
            platform,
            COUNT(*) AS cnt
        FROM content_records
        WHERE collection_run_id = :run_id
          AND (raw_metadata->>'duplicate_of') IS NULL
        GROUP BY arena, platform
        """
    )
    result = await session.execute(
        current_counts_sql, {"run_id": str(collection_run_id)}
    )
    current_rows = result.fetchall()

    if not current_rows:
        log.info("detect_volume_spikes: no records in current run; skipping")
        return []

    # --- Step 2 & 3: rolling 7-run average per arena/platform ---------------
    # Find the 7 most-recent completed runs for this query design prior to the
    # current run (by completed_at DESC, then id DESC as tiebreak).
    prior_runs_sql = text(
        """
        SELECT id
        FROM collection_runs
        WHERE query_design_id = :query_design_id
          AND id != :run_id
          AND status = 'completed'
        ORDER BY COALESCE(completed_at, started_at) DESC, id DESC
        LIMIT :window
        """
    )
    prior_result = await session.execute(
        prior_runs_sql,
        {
            "query_design_id": str(query_design_id),
            "run_id": str(collection_run_id),
            "window": _ROLLING_WINDOW,
        },
    )
    prior_run_ids = [str(row.id) for row in prior_result.fetchall()]

    if len(prior_run_ids) < _ROLLING_WINDOW:
        log.info(
            "detect_volume_spikes: insufficient run history; skipping",
            prior_runs_found=len(prior_run_ids),
            required=_ROLLING_WINDOW,
        )
        return []

    # Compute per-arena/platform average across the prior runs.
    # UUIDs are materialised as a SQL literal tuple to avoid SQLAlchemy/asyncpg
    # type-casting issues with parameterised IN (:ids) lists.
    id_placeholders = ", ".join(f"'{rid}'" for rid in prior_run_ids)
    rolling_avg_sql = text(
        f"""
        SELECT
            arena,
            platform,
            AVG(cnt) AS avg_count
        FROM (
            SELECT
                arena,
                platform,
                collection_run_id,
                COUNT(*) AS cnt
            FROM content_records
            WHERE collection_run_id IN ({id_placeholders})
              AND (raw_metadata->>'duplicate_of') IS NULL
            GROUP BY arena, platform, collection_run_id
        ) sub
        GROUP BY arena, platform
        """  # noqa: S608 — id_placeholders are UUID strings, not user input
    )
    avg_result = await session.execute(rolling_avg_sql)
    avg_rows = {(row.arena, row.platform): float(row.avg_count) for row in avg_result.fetchall()}

    # --- Step 4: threshold comparison ---------------------------------------
    spikes: list[VolumeSpike] = []

    for row in current_rows:
        arena = row.arena
        platform = row.platform
        current_count = int(row.cnt)
        rolling_avg = avg_rows.get((arena, platform))

        if rolling_avg is None or rolling_avg == 0:
            # Arena not present in prior runs — skip rather than error.
            log.debug(
                "detect_volume_spikes: no prior data for arena/platform",
                arena=arena,
                platform=platform,
            )
            continue

        ratio = current_count / rolling_avg

        if current_count >= _MIN_ABSOLUTE_COUNT and ratio > threshold_multiplier:
            spikes.append(
                VolumeSpike(
                    arena_name=arena,
                    platform=platform,
                    current_count=current_count,
                    rolling_7d_average=rolling_avg,
                    ratio=ratio,
                )
            )
            log.info(
                "detect_volume_spikes: spike detected",
                arena=arena,
                platform=platform,
                current_count=current_count,
                rolling_avg=round(rolling_avg, 2),
                ratio=round(ratio, 2),
            )

    if not spikes:
        log.info("detect_volume_spikes: no spikes detected")
        return []

    # --- Step 5: top-3 terms for each spiking arena/platform ----------------
    for spike in spikes:
        spike.top_terms = await _fetch_top_terms(
            session=session,
            collection_run_id=collection_run_id,
            arena=spike.arena_name,
            platform=spike.platform,
            limit=3,
        )

    return spikes


async def _fetch_top_terms(
    session: AsyncSession,
    collection_run_id: uuid.UUID,
    arena: str,
    platform: str,
    limit: int = 3,
) -> list[str]:
    """Return the top search terms by match frequency for a spiking arena.

    Args:
        session: Active async database session.
        collection_run_id: UUID of the current collection run.
        arena: Arena name to filter on.
        platform: Platform slug to filter on.
        limit: Maximum number of terms to return.

    Returns:
        List of up to ``limit`` term strings, ordered by frequency descending.
    """
    sql = text(
        """
        SELECT
            term,
            COUNT(*) AS cnt
        FROM content_records,
             unnest(search_terms_matched) AS term
        WHERE collection_run_id = :run_id
          AND arena = :arena
          AND platform = :platform
          AND search_terms_matched IS NOT NULL
          AND (raw_metadata->>'duplicate_of') IS NULL
        GROUP BY term
        ORDER BY cnt DESC
        LIMIT :limit
        """
    )
    result = await session.execute(
        sql,
        {
            "run_id": str(collection_run_id),
            "arena": arena,
            "platform": platform,
            "limit": limit,
        },
    )
    return [row.term for row in result.fetchall()]
