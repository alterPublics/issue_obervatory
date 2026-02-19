"""Internal async DB helpers for the volume spike alerting task.

This module contains the async coroutines called by the synchronous
``check_volume_spikes`` Celery task in ``workers/tasks.py``.  They are kept
separate to follow the established pattern (see ``_task_helpers.py``) of
keeping each file under 400 lines and making helpers unit-testable in
isolation from the Celery application.

All functions open their own ``AsyncSessionLocal`` context manager and close
the session before returning, because Celery workers call these via
``asyncio.run()`` from synchronous task bodies.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select

from issue_observatory.analysis.alerting import (
    VolumeSpike,
    detect_volume_spikes,
    fetch_recent_volume_spikes,
    send_volume_spike_alert,
    store_volume_spikes,
)
from issue_observatory.core.database import AsyncSessionLocal
from issue_observatory.core.email_service import get_email_service
from issue_observatory.core.models.query_design import QueryDesign
from issue_observatory.core.models.users import User

logger = structlog.get_logger(__name__)


async def run_spike_detection(
    collection_run_id: uuid.UUID,
    query_design_id: uuid.UUID,
    threshold_multiplier: float = 2.0,
) -> list[dict[str, Any]]:
    """Detect volume spikes and persist/notify if any are found.

    This coroutine is the single entry point called by the Celery task.  It:

    1. Opens an ``AsyncSessionLocal`` and runs :func:`detect_volume_spikes`.
    2. If spikes are found, persists them via :func:`store_volume_spikes`.
    3. Looks up the query design owner's email and the design's display name.
    4. Sends the alert email via :func:`send_volume_spike_alert`.

    Args:
        collection_run_id: UUID of the just-completed collection run.
        query_design_id: UUID of the associated query design.
        threshold_multiplier: Spike detection ratio threshold.  Defaults to
            2.0 (200 % of the 7-day rolling average).

    Returns:
        List of spike dicts (one per spiking arena) or an empty list when
        no spikes were detected or when history is insufficient.
    """
    log = logger.bind(
        collection_run_id=str(collection_run_id),
        query_design_id=str(query_design_id),
    )

    async with AsyncSessionLocal() as db:
        # --- Spike detection ------------------------------------------------
        spikes: list[VolumeSpike] = await detect_volume_spikes(
            session=db,
            query_design_id=query_design_id,
            collection_run_id=collection_run_id,
            threshold_multiplier=threshold_multiplier,
        )

        if not spikes:
            log.info("run_spike_detection: no spikes detected")
            return []

        # --- Persist spikes -------------------------------------------------
        await store_volume_spikes(
            session=db,
            collection_run_id=collection_run_id,
            spikes=spikes,
        )

        # --- Fetch owner info -----------------------------------------------
        qd_result = await db.execute(
            select(
                QueryDesign.name,
                QueryDesign.owner_id,
            ).where(QueryDesign.id == query_design_id)
        )
        qd_row = qd_result.fetchone()
        if qd_row is None:
            log.warning(
                "run_spike_detection: query design not found; skipping alert",
                query_design_id=str(query_design_id),
            )
            return [s.to_dict() for s in spikes]

        design_name: str = qd_row.name or f"Design {query_design_id}"
        owner_id = qd_row.owner_id

        owner_result = await db.execute(
            select(User.email).where(User.id == owner_id)
        )
        owner_email: str | None = owner_result.scalar_one_or_none()

    # --- Send alert (outside the session context) ---------------------------
    if owner_email:
        email_svc = get_email_service()
        try:
            await send_volume_spike_alert(
                email_svc=email_svc,
                user_email=owner_email,
                query_design_name=design_name,
                query_design_id=query_design_id,
                spikes=spikes,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "run_spike_detection: alert email failed",
                error=str(exc),
            )
    else:
        log.warning(
            "run_spike_detection: owner email not found; skipping alert email",
            owner_id=str(owner_id) if owner_id else None,
        )

    log.info(
        "run_spike_detection: complete",
        spike_count=len(spikes),
        owner_email=owner_email,
    )
    return [s.to_dict() for s in spikes]


async def get_query_design_alerts(
    query_design_id: uuid.UUID,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Fetch recent volume spike alerts for a query design.

    Thin wrapper around :func:`fetch_recent_volume_spikes` that opens its own
    database session so it can be called from the API layer via dependency
    injection without needing a pre-existing session (or can be called from
    Celery via ``asyncio.run()``).

    Args:
        query_design_id: UUID of the query design to look up.
        days: Number of past days to include.  Defaults to 30.

    Returns:
        List of alert dicts as returned by
        :func:`~issue_observatory.analysis.alerting.fetch_recent_volume_spikes`.
    """
    async with AsyncSessionLocal() as db:
        return await fetch_recent_volume_spikes(
            session=db,
            query_design_id=query_design_id,
            days=days,
        )
