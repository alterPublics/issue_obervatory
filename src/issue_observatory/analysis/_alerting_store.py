"""Persistence and notification helpers for volume spike alerting.

This module is an internal implementation detail of the alerting subsystem
(GR-09).  It contains the storage and email functions that are split out from
:mod:`issue_observatory.analysis.alerting` to keep each file under 400 lines.

Public surface:
- :func:`store_volume_spikes`
- :func:`fetch_recent_volume_spikes`
- :func:`send_volume_spike_alert`

All callers should import from :mod:`issue_observatory.analysis.alerting`
which re-exports these symbols.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from issue_observatory.analysis.alerting import VolumeSpike
    from issue_observatory.core.email_service import EmailService

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def store_volume_spikes(
    session: AsyncSession,
    collection_run_id: uuid.UUID,
    spikes: list[VolumeSpike],
) -> None:
    """Persist spike events into ``collection_runs.arenas_config["_volume_spikes"]``.

    ``CollectionRun`` does not have a dedicated ``metadata`` JSONB column, so
    spikes are stored under a reserved key ``"_volume_spikes"`` (underscore
    prefix distinguishes it from real arena name keys) inside the existing
    ``arenas_config`` JSONB column.  No schema migration is required.

    Uses PostgreSQL ``jsonb_set`` with ``create_missing=true`` to safely
    initialise the key without overwriting other arena config entries.

    Args:
        session: Active async database session (will be committed).
        collection_run_id: UUID of the collection run to annotate.
        spikes: Non-empty list of :class:`~issue_observatory.analysis.alerting.VolumeSpike`
            objects to persist.
    """
    import json  # noqa: PLC0415

    spike_payload = json.dumps([s.to_dict() for s in spikes])

    sql = text(
        """
        UPDATE collection_runs
        SET arenas_config = jsonb_set(
            COALESCE(arenas_config, '{}'::jsonb),
            '{_volume_spikes}',
            :spike_json::jsonb,
            true
        )
        WHERE id = :run_id
        """
    )
    await session.execute(
        sql,
        {"spike_json": spike_payload, "run_id": str(collection_run_id)},
    )
    await session.commit()
    logger.info(
        "store_volume_spikes: persisted spikes",
        collection_run_id=str(collection_run_id),
        spike_count=len(spikes),
    )


async def fetch_recent_volume_spikes(
    session: AsyncSession,
    query_design_id: uuid.UUID,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Return spike events recorded in the last ``days`` days for a query design.

    Reads ``collection_runs.arenas_config["_volume_spikes"]`` across all
    completed runs for the query design within the requested window.

    Args:
        session: Active async database session.
        query_design_id: UUID of the query design to query.
        days: Number of past days to include.  Defaults to 30.

    Returns:
        List of dicts, each containing ``run_id``, ``completed_at``, and the
        ``volume_spikes`` list from that run's stored arenas_config.  Empty
        when no spikes exist in the window.
    """
    sql = text(
        """
        SELECT
            id AS run_id,
            completed_at,
            arenas_config->'_volume_spikes' AS spikes
        FROM collection_runs
        WHERE query_design_id = :query_design_id
          AND status = 'completed'
          AND completed_at >= NOW() - make_interval(days => :days)
          AND arenas_config ? '_volume_spikes'
          AND jsonb_array_length(arenas_config->'_volume_spikes') > 0
        ORDER BY completed_at DESC
        """
    )
    result = await session.execute(
        sql,
        {"query_design_id": str(query_design_id), "days": days},
    )
    rows = result.fetchall()

    output: list[dict[str, Any]] = []
    for row in rows:
        output.append(
            {
                "run_id": str(row.run_id),
                "completed_at": row.completed_at.isoformat()
                if row.completed_at
                else None,
                "volume_spikes": row.spikes or [],
            }
        )
    return output


# ---------------------------------------------------------------------------
# Email notification
# ---------------------------------------------------------------------------


async def send_volume_spike_alert(
    email_svc: EmailService,
    user_email: str,
    query_design_name: str,
    query_design_id: uuid.UUID,
    spikes: list[VolumeSpike],
    dashboard_base_url: str = "http://localhost:8000",
) -> None:
    """Send an email alert for detected volume spikes to the query design owner.

    Composes a plain-text email listing each spiking arena, the item counts,
    the spike ratio, and the top search terms driving the spike.  Silently
    no-ops if ``email_svc.is_configured()`` returns ``False``.

    Args:
        email_svc: Configured :class:`~issue_observatory.core.email_service.EmailService`.
        user_email: Recipient email address (the query design owner).
        query_design_name: Human-readable name of the query design.
        query_design_id: UUID of the query design, used to build the
            dashboard link.
        spikes: Non-empty list of :class:`~issue_observatory.analysis.alerting.VolumeSpike`
            objects to report.
        dashboard_base_url: Base URL for the analysis dashboard.  Defaults to
            ``http://localhost:8000`` for local development.
    """
    if not email_svc.is_configured():
        logger.debug(
            "send_volume_spike_alert: email not configured; skipping",
            query_design_id=str(query_design_id),
        )
        return

    subject = f"[Issue Observatory] Volume spike detected in {query_design_name}"
    dashboard_url = (
        f"{dashboard_base_url.rstrip('/')}"
        f"/query-designs/{query_design_id}/alerts"
    )

    lines: list[str] = [
        f"Volume spike alert for query design: {query_design_name}",
        f"Query design ID: {query_design_id}",
        "",
        f"{len(spikes)} arena(s) exceeded 2x the 7-day rolling average:",
        "",
    ]

    for spike in spikes:
        terms_str = (
            ", ".join(spike.top_terms) if spike.top_terms else "(no terms matched)"
        )
        lines += [
            f"Arena   : {spike.arena_name} / {spike.platform}",
            f"Current : {spike.current_count:,} records",
            f"7d avg  : {spike.rolling_7d_average:,.1f} records",
            f"Ratio   : {spike.ratio:.1f}x",
            f"Top terms: {terms_str}",
            "",
        ]

    lines += [
        "View alerts on the dashboard:",
        dashboard_url,
        "",
        "You are receiving this alert because you own this query design.",
        "Log in to the Issue Observatory to review or adjust your settings.",
    ]

    body = "\n".join(lines)

    await email_svc._send(  # noqa: SLF001 — intentional access to internal helper
        recipient=user_email,
        subject=subject,
        body=body,
    )
    logger.info(
        "send_volume_spike_alert: alert sent",
        query_design_id=str(query_design_id),
        recipient=user_email,
        spike_count=len(spikes),
    )
