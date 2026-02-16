"""Celery tasks for the Google Autocomplete arena.

Wraps :class:`GoogleAutocompleteCollector` methods as Celery tasks with
automatic retry behaviour, collection run status tracking, and error reporting.

Task naming::

    issue_observatory.arenas.google_autocomplete.tasks.<action>

Retry policy:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff
  (``autoretry_for`` + ``retry_backoff=True``), up to ``max_retries=3``.
- Other ``ArenaCollectionError`` subclasses are logged and re-raised so that
  Celery marks the task as FAILED.
- ``NoCredentialAvailableError`` is logged and re-raised immediately (no retry).

Database updates:
- Best-effort via ``_update_task_status()`` — DB failures are logged at WARNING
  and do not mask the collection outcome.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from issue_observatory.arenas.google_autocomplete.collector import GoogleAutocompleteCollector
from issue_observatory.core.credential_pool import CredentialPool
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _update_task_status(
    collection_run_id: str,
    arena: str,
    status: str,
    records_collected: int = 0,
    error_message: str | None = None,
) -> None:
    """Best-effort update of the ``collection_tasks`` row for this arena.

    Failures are logged at WARNING and do not affect the collection outcome.

    Args:
        collection_run_id: UUID string of the parent collection run.
        arena: Arena identifier (``"google_autocomplete"``).
        status: New status (``"running"`` | ``"completed"`` | ``"failed"``).
        records_collected: Number of records collected (for completed updates).
        error_message: Error description (for failed updates).
    """
    try:
        from issue_observatory.core.database import get_sync_session  # noqa: PLC0415

        with get_sync_session() as session:
            from sqlalchemy import text  # noqa: PLC0415

            session.execute(
                text(
                    """
                    UPDATE collection_tasks
                    SET status = :status,
                        records_collected = :records_collected,
                        error_message = :error_message,
                        completed_at = CASE WHEN :status IN ('completed', 'failed')
                                            THEN NOW() ELSE completed_at END,
                        started_at   = CASE WHEN :status = 'running' AND started_at IS NULL
                                            THEN NOW() ELSE started_at END
                    WHERE collection_run_id = :run_id AND arena = :arena
                    """
                ),
                {
                    "status": status,
                    "records_collected": records_collected,
                    "error_message": error_message,
                    "run_id": collection_run_id,
                    "arena": arena,
                },
            )
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "google_autocomplete: failed to update collection_tasks to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.google_autocomplete.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def google_autocomplete_collect_terms(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    terms: list[str],
    tier: str = "free",
) -> dict[str, Any]:
    """Collect Google Autocomplete suggestions for a list of terms.

    Wraps :meth:`GoogleAutocompleteCollector.collect_by_terms` as an
    idempotent Celery task.  Updates the ``collection_tasks`` row with
    progress and final status.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms to get autocomplete suggestions for.
        tier: Tier string — ``"free"``, ``"medium"``, or ``"premium"``.
            Defaults to ``"free"``.

    Returns:
        Dict with:
        - ``records_collected`` (int): Number of normalized records.
        - ``status`` (str): ``"completed"``.
        - ``arena`` (str): ``"google_autocomplete"``.
        - ``tier`` (str): The tier used.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED in Celery.
        NoCredentialAvailableError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    logger.info(
        "google_autocomplete: collect_by_terms started — run=%s terms=%d tier=%s",
        collection_run_id,
        len(terms),
        tier,
    )
    _update_task_status(collection_run_id, "google_autocomplete", "running")

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = (
            f"google_autocomplete: invalid tier '{tier}'. "
            "Valid values: free, medium, premium."
        )
        logger.error(msg)
        _update_task_status(collection_run_id, "google_autocomplete", "failed", error_message=msg)
        raise ArenaCollectionError(msg, arena="google_autocomplete", platform="google")

    credential_pool = CredentialPool()
    collector = GoogleAutocompleteCollector(credential_pool=credential_pool)

    try:
        records = asyncio.run(
            collector.collect_by_terms(
                terms=terms,
                tier=tier_enum,
                max_results=None,
            )
        )
    except NoCredentialAvailableError as exc:
        msg = f"google_autocomplete: no credential for tier={tier}: {exc}"
        logger.error(msg)
        _update_task_status(collection_run_id, "google_autocomplete", "failed", error_message=msg)
        raise
    except ArenaRateLimitError:
        logger.warning(
            "google_autocomplete: rate limited on collect_by_terms for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error(
            "google_autocomplete: collection error for run=%s: %s", collection_run_id, msg
        )
        _update_task_status(collection_run_id, "google_autocomplete", "failed", error_message=msg)
        raise

    count = len(records)
    logger.info(
        "google_autocomplete: collect_by_terms completed — run=%s records=%d",
        collection_run_id,
        count,
    )
    _update_task_status(
        collection_run_id, "google_autocomplete", "completed", records_collected=count
    )
    return {
        "records_collected": count,
        "status": "completed",
        "arena": "google_autocomplete",
        "tier": tier,
    }


@celery_app.task(
    name="issue_observatory.arenas.google_autocomplete.tasks.health_check",
    bind=False,
)
def google_autocomplete_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the Google Autocomplete arena.

    Delegates to :meth:`GoogleAutocompleteCollector.health_check`, which
    sends a minimal test query to the FREE tier endpoint.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = GoogleAutocompleteCollector()
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info(
        "google_autocomplete: health_check status=%s", result.get("status", "unknown")
    )
    return result
