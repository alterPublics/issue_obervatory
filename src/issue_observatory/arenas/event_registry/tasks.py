"""Celery tasks for the Event Registry arena.

Wraps :class:`~issue_observatory.arenas.event_registry.collector.EventRegistryCollector`
methods as Celery tasks with automatic retry behaviour and collection run status
tracking.

Task naming convention::

    issue_observatory.arenas.event_registry.tasks.<action>

Retry policy:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff
  (up to ``max_retries=3``), capped at 5 minutes between retries.
- ``ArenaCollectionError`` (including token budget exhaustion) is logged and
  re-raised so Celery marks the task FAILED.
- ``NoCredentialAvailableError`` is logged and re-raised; Celery marks FAILED.

Database updates are best-effort; failures are logged and do not mask
collection outcomes.

Note on tier strings:
    Task arguments carry tier as a plain string (``"medium"`` or
    ``"premium"``).  The :class:`~issue_observatory.arenas.base.Tier` enum is
    reconstructed inside each task to keep Celery arguments JSON-serializable.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from issue_observatory.arenas.event_registry.collector import EventRegistryCollector
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_ARENA = "event_registry"
_PLATFORM = "event_registry"


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

    Args:
        collection_run_id: UUID string of the parent collection run.
        arena: Arena identifier.
        status: New status value (``"running"``, ``"completed"``, ``"failed"``).
        records_collected: Number of records collected so far.
        error_message: Error description for failed updates.
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
            "event_registry: failed to update collection_tasks status to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.event_registry.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def event_registry_collect_terms(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    terms: list[str],
    tier: str = "medium",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
    language_filter: list[str] | None = None,
) -> dict[str, Any]:
    """Collect Event Registry Danish news articles matching search terms.

    Each term produces one paginated ``getArticles`` query sequence with
    ``lang="dan"`` and ``sourceLocationUri=Denmark``.  Each page request
    consumes one Event Registry token.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms (Danish keywords work natively).
        tier: Tier string — ``"medium"`` or ``"premium"``.
        date_from: ISO 8601 earliest publication date (inclusive).
        date_to: ISO 8601 latest publication date (inclusive).
        max_results: Upper bound on returned records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED in Celery.
        NoCredentialAvailableError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    logger.info(
        "event_registry: collect_by_terms started — run=%s terms=%d tier=%s",
        collection_run_id,
        len(terms),
        tier,
    )
    _update_task_status(collection_run_id, _ARENA, "running")

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"event_registry: invalid tier '{tier}'. Valid: 'medium', 'premium'."
        logger.error(msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        raise ArenaCollectionError(msg, arena=_ARENA, platform=_PLATFORM)

    collector = EventRegistryCollector()

    try:
        records = asyncio.run(
            collector.collect_by_terms(
                terms=terms,
                tier=tier_enum,
                date_from=date_from,
                date_to=date_to,
                max_results=max_results,
                language_filter=language_filter,
            )
        )
    except ArenaRateLimitError:
        logger.warning(
            "event_registry: rate limited on collect_by_terms for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except (ArenaCollectionError, NoCredentialAvailableError) as exc:
        msg = str(exc)
        logger.error(
            "event_registry: collection error for run=%s: %s", collection_run_id, msg
        )
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        raise

    count = len(records)
    logger.info(
        "event_registry: collect_by_terms completed — run=%s records=%d",
        collection_run_id,
        count,
    )
    _update_task_status(
        collection_run_id, _ARENA, "completed", records_collected=count
    )

    return {
        "records_collected": count,
        "status": "completed",
        "arena": _ARENA,
        "tier": tier,
    }


@celery_app.task(
    name="issue_observatory.arenas.event_registry.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def event_registry_collect_actors(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    actor_ids: list[str],
    tier: str = "medium",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
) -> dict[str, Any]:
    """Collect Event Registry Danish news articles mentioning concept URIs.

    Actor IDs must be Event Registry concept URIs (Wikipedia-based), such as
    ``"http://en.wikipedia.org/wiki/Mette_Frederiksen"``.  Use the
    ``/suggestConcepts`` endpoint to resolve actor names to URIs.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: List of Event Registry concept or source URIs.
        tier: Tier string — ``"medium"`` or ``"premium"``.
        date_from: ISO 8601 earliest publication date (inclusive).
        date_to: ISO 8601 latest publication date (inclusive).
        max_results: Upper bound on returned records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED in Celery.
        NoCredentialAvailableError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    logger.info(
        "event_registry: collect_by_actors started — run=%s actors=%d tier=%s",
        collection_run_id,
        len(actor_ids),
        tier,
    )
    _update_task_status(collection_run_id, _ARENA, "running")

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"event_registry: invalid tier '{tier}'. Valid: 'medium', 'premium'."
        logger.error(msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        raise ArenaCollectionError(msg, arena=_ARENA, platform=_PLATFORM)

    collector = EventRegistryCollector()

    try:
        records = asyncio.run(
            collector.collect_by_actors(
                actor_ids=actor_ids,
                tier=tier_enum,
                date_from=date_from,
                date_to=date_to,
                max_results=max_results,
            )
        )
    except ArenaRateLimitError:
        logger.warning(
            "event_registry: rate limited on collect_by_actors for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except (ArenaCollectionError, NoCredentialAvailableError) as exc:
        msg = str(exc)
        logger.error(
            "event_registry: collection error for run=%s: %s", collection_run_id, msg
        )
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        raise

    count = len(records)
    logger.info(
        "event_registry: collect_by_actors completed — run=%s records=%d",
        collection_run_id,
        count,
    )
    _update_task_status(
        collection_run_id, _ARENA, "completed", records_collected=count
    )

    return {
        "records_collected": count,
        "status": "completed",
        "arena": _ARENA,
        "tier": tier,
    }


@celery_app.task(
    name="issue_observatory.arenas.event_registry.tasks.health_check",
    bind=False,
)
def event_registry_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the Event Registry arena.

    Delegates to :meth:`~EventRegistryCollector.health_check`, which issues
    a single minimal ``getArticles`` request with ``articlesCount=1`` and
    returns the API response status including remaining token count.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, ``remaining_tokens`` (if available), and optionally
        ``detail``.
    """
    collector = EventRegistryCollector()
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info(
        "event_registry: health_check status=%s remaining_tokens=%s",
        result.get("status", "unknown"),
        result.get("remaining_tokens"),
    )
    return result
