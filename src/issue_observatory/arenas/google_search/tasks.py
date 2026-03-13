"""Celery tasks for the Google Search arena.

Wraps :class:`GoogleSearchCollector` methods as Celery tasks with automatic
retry behaviour, collection run status tracking, and error reporting.

Task naming follows the project convention::

    issue_observatory.arenas.google_search.tasks.<action>

All tasks are registered in the Celery app via the ``include`` list in
:mod:`issue_observatory.workers.celery_app`.

Retry policy:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff
  (``autoretry_for`` + ``retry_backoff=True``), up to ``max_retries=3``.
- Other ``ArenaCollectionError`` subclasses are logged and re-raised so
  that Celery marks the task as FAILED.  The ``collection_tasks`` row is
  updated with the error message regardless.

Database updates:
- The tasks update the ``collection_tasks`` table at task start and on
  completion/failure.  The update is a best-effort fire-and-forget via a
  synchronous SQLAlchemy session run inside ``asyncio.run()`` to avoid
  requiring an event loop on the Celery worker thread.

SSE event bus:
- :func:`~issue_observatory.core.event_bus.publish_task_update` is called at
  each status transition (running, completed, failed).  This is the canonical
  pattern for all arena tasks.  Copy the three call sites into every new arena
  task that participates in SSE streaming.

Note: In Phase 0, the full database-backed session is used only if the DB
infrastructure is available.  Tasks are designed to degrade gracefully if the
database is not reachable — they log an error and continue rather than masking
the original collection outcome.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from issue_observatory.arenas.google_search.collector import GoogleSearchCollector
from issue_observatory.config.settings import get_settings
from issue_observatory.core.credential_pool import CredentialPool
from issue_observatory.core.event_bus import elapsed_since, publish_task_update
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

    Runs the DB update in a new event loop on the calling thread.  If the
    update fails for any reason the error is logged at WARNING level and
    execution continues — a DB update failure must not mask the collection
    outcome.

    Args:
        collection_run_id: UUID string of the parent collection run.
        arena: Arena identifier (``"google_search"``).
        status: New status value (``"running"`` | ``"completed"`` | ``"failed"``).
        records_collected: Number of records collected (for ``"completed"`` updates).
        error_message: Error description (for ``"failed"`` updates).
    """
    try:
        from issue_observatory.core.database import get_sync_session

        with get_sync_session() as session:
            from sqlalchemy import text

            session.execute(
                text(
                    """
                    UPDATE collection_tasks
                    SET status = :status,
                        records_collected = GREATEST(records_collected, :records_collected),
                        error_message = :error_message,
                        completed_at = CASE WHEN :status IN ('completed', 'failed')
                                            THEN NOW() ELSE completed_at END,
                        started_at   = CASE WHEN :status = 'running' AND started_at IS NULL
                                            THEN NOW() ELSE started_at END
                    WHERE collection_run_id = :run_id AND arena = :arena
                        AND status != 'cancelled'
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
    except Exception as exc:
        logger.warning(
            "google_search: failed to update collection_tasks status to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.google_search.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,  # cap backoff at 5 minutes
    acks_late=True,
    # No fixed time limit — records persist incrementally and stale_run_cleanup handles stuck tasks.
)
def google_search_collect_terms(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    terms: list[str],
    tier: str = "medium",
    language_filter: list[str] | None = None,
    public_figure_ids: list[str] | None = None,
    **_extra: Any,
) -> dict[str, Any]:
    """Collect Google Search results for a list of terms.

    Wraps :meth:`GoogleSearchCollector.collect_by_terms` as an idempotent
    Celery task.  Updates the ``collection_tasks`` row with progress and
    final status.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms to query.
        tier: Tier string — ``"medium"`` (Serper.dev) or ``"premium"`` (SerpAPI).
            Defaults to ``"medium"``.
        language_filter: Optional list of ISO 639-1 language codes (IP2-052).
            When provided, restricts results to the given language(s).
        public_figure_ids: Optional list of platform user IDs whose authors
            should bypass SHA-256 pseudonymization (GR-14 — GDPR Art. 89(1)
            research exemption).  Passed by ``trigger_daily_collection`` from
            the actor-list configuration of the owning query design.  When
            ``None`` or empty, all authors are pseudonymized as normal.

    Returns:
        Dict with:
        - ``records_collected`` (int): Number of normalized records retrieved.
        - ``status`` (str): ``"completed"`` or ``"skipped"``.
        - ``arena`` (str): ``"google_search"``.
        - ``tier`` (str): The tier used.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED in Celery.
        NoCredentialAvailableError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "google_search: collect_by_terms started — run=%s terms=%d tier=%s",
        collection_run_id,
        len(terms),
        tier,
    )
    _update_task_status(collection_run_id, "google_search", "running")
    # SSE: notify subscribers that this arena task has started.
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="google_search",
        platform="google",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"google_search: invalid tier '{tier}'. Valid values: free, medium, premium."
        logger.error(msg)
        _update_task_status(collection_run_id, "google_search", "failed", error_message=msg)
        # SSE: notify subscribers of the failure.
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="google_search",
            platform="google",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise ArenaCollectionError(msg, arena="google_search", platform="google")

    if tier_enum == Tier.FREE:
        logger.warning(
            "google_search: FREE tier requested — no results available. "
            "Task completing with 0 records."
        )
        _update_task_status(collection_run_id, "google_search", "completed", records_collected=0)
        # SSE: notify subscribers of the skipped-but-terminal state.
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="google_search",
            platform="google",
            status="completed",
            records_collected=0,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )
        return {
            "records_collected": 0,
            "status": "skipped",
            "arena": "google_search",
            "tier": tier,
            "detail": "FREE tier not available for Google Search.",
        }

    credential_pool = CredentialPool()
    collector = GoogleSearchCollector(credential_pool=credential_pool)

    # GR-14: make the public-figure ID set available to the collector's
    # normalize() method so that per-record bypass decisions happen without
    # an additional DB round-trip at collection time.
    pf_ids: set[str] = set(public_figure_ids) if public_figure_ids else set()
    collector.set_public_figure_ids(pf_ids)

    from issue_observatory.workers._task_helpers import (
        make_batch_sink,
        persist_collected_records,
    )

    sink = make_batch_sink(collection_run_id, query_design_id)
    collector.configure_batch_persistence(sink=sink, batch_size=100, collection_run_id=collection_run_id)

    from issue_observatory.workers._task_helpers import run_with_tier_fallback

    try:
        remaining, used_tier = run_with_tier_fallback(
            collector=collector,
            collect_method="collect_by_terms",
            kwargs={
                "terms": terms,
                "tier": tier_enum,
                "max_results": None,
                "language_filter": language_filter,
            },
            requested_tier_str=tier,
            platform="google_search",
            task_logger=logger,
        )
        tier = used_tier  # update for reporting
    except NoCredentialAvailableError as exc:
        msg = f"google_search: no credential available for any supported tier (requested={tier}): {exc}"
        logger.error(msg)
        _update_task_status(collection_run_id, "google_search", "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="google_search",
            platform="google",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise
    except ArenaRateLimitError:
        # Let autoretry handle it — status stays "running" until retry resolves.
        logger.warning(
            "google_search: rate limited on collect_by_terms for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error("google_search: collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, "google_search", "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="google_search",
            platform="google",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise

    fallback_inserted, fallback_skipped = 0, 0
    if remaining:
        fallback_inserted, fallback_skipped = persist_collected_records(
            remaining, collection_run_id, query_design_id
        )
    inserted = collector.batch_stats["inserted"] + fallback_inserted
    skipped = collector.batch_stats["skipped"] + fallback_skipped

    # Fallback: if in-memory counters lost track, use the actual DB count.
    if inserted == 0:
        from issue_observatory.workers._task_helpers import (
            count_run_platform_records,
        )

        db_count = count_run_platform_records(collection_run_id, "google_search")
        if db_count > 0:
            logger.info(
                "google_search: in-memory counter=0 but DB has %d records — using DB count",
                db_count,
            )
            inserted = db_count

    logger.info(
        "google_search: collect_by_terms completed — run=%s emitted=%d inserted=%d skipped=%d",
        collection_run_id,
        collector.batch_stats["emitted"],
        inserted,
        skipped,
    )
    _update_task_status(
        collection_run_id, "google_search", "completed", records_collected=inserted
    )
    # SSE: notify subscribers of successful completion.
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="google_search",
        platform="google",
        status="completed",
        records_collected=inserted,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    return {
        "records_collected": inserted,
        "status": "completed",
        "arena": "google_search",
        "tier": tier,
    }


@celery_app.task(
    name="issue_observatory.arenas.google_search.tasks.health_check",
    bind=False,
)
def google_search_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the Google Search arena.

    Delegates to :meth:`GoogleSearchCollector.health_check`, which sends a
    minimal test query to Serper.dev.  This task is designed to be called
    from the admin health dashboard (via Celery ``send_task``) or from a
    Celery Beat schedule.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    credential_pool = CredentialPool()
    collector = GoogleSearchCollector(credential_pool=credential_pool)
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info(
        "google_search: health_check status=%s", result.get("status", "unknown")
    )
    return result
