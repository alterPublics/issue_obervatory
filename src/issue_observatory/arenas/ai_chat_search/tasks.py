"""Celery tasks for the AI Chat Search arena.

Wraps :class:`~issue_observatory.arenas.ai_chat_search.collector.AiChatSearchCollector`
methods as Celery tasks with automatic retry behaviour and collection run
status tracking.

Task naming convention::

    issue_observatory.arenas.ai_chat_search.tasks.<action>

Retry policy:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff
  (up to ``max_retries=3``), capped at 5 minutes between retries.
- ``ArenaCollectionError`` (including auth errors) is logged and re-raised so
  Celery marks the task FAILED.
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

from issue_observatory.arenas.ai_chat_search.collector import AiChatSearchCollector
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_ARENA = "ai_chat_search"
_PLATFORM = "openrouter"


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
        arena: Arena identifier (``"ai_chat_search"``).
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
            "ai_chat_search: failed to update collection_tasks status to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.ai_chat_search.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def ai_chat_search_collect_terms(
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
    """Collect AI chat search responses and citations for the given search terms.

    For each term, generates N Danish phrasings (via the free expansion model)
    and submits each to Perplexity Sonar via OpenRouter.  Returns one
    ``ai_chat_response`` record per phrasing and one ``ai_chat_citation``
    record per cited URL.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms in Danish (e.g. ``["CO2 afgift", "klimapolitik"]``).
        tier: Tier string — ``"medium"`` or ``"premium"``.
        date_from: Ignored — AI chat search has no date-filtering mechanism.
        date_to: Ignored — AI chat search has no date-filtering mechanism.
        max_results: Upper bound on returned records (responses + citations).

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED in Celery.
        NoCredentialAvailableError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    logger.info(
        "ai_chat_search: collect_by_terms started — run=%s terms=%d tier=%s",
        collection_run_id,
        len(terms),
        tier,
    )
    _update_task_status(collection_run_id, _ARENA, "running")

    if tier not in ("medium", "premium"):
        msg = (
            f"ai_chat_search: invalid tier '{tier}'. "
            "Valid tiers: 'medium', 'premium'."
        )
        logger.error(msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        raise ArenaCollectionError(msg, arena=_ARENA, platform=_PLATFORM)

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"ai_chat_search: invalid tier '{tier}'. Valid: 'medium', 'premium'."
        logger.error(msg)
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        raise ArenaCollectionError(msg, arena=_ARENA, platform=_PLATFORM)

    collector = AiChatSearchCollector()

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
            "ai_chat_search: rate limited on collect_by_terms for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except (ArenaCollectionError, NoCredentialAvailableError) as exc:
        msg = str(exc)
        logger.error(
            "ai_chat_search: collection error for run=%s: %s",
            collection_run_id,
            msg,
        )
        _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
        raise

    count = len(records)
    logger.info(
        "ai_chat_search: collect_by_terms completed — run=%s records=%d",
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
    name="issue_observatory.arenas.ai_chat_search.tasks.health_check",
    bind=False,
)
def ai_chat_search_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the AI Chat Search arena.

    Delegates to :meth:`~AiChatSearchCollector.health_check`, which attempts
    to expand the term ``"Danmark"`` with 1 phrasing using the free
    ``google/gemma-3-27b-it:free`` model (no Perplexity credits consumed).

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    collector = AiChatSearchCollector()
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info(
        "ai_chat_search: health_check status=%s",
        result.get("status", "unknown"),
    )
    return result
