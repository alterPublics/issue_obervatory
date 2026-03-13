"""Celery tasks for the Gab arena.

Wraps :class:`GabCollector` methods as Celery tasks with automatic retry
behaviour, collection run status tracking, and error reporting.

Task naming::

    issue_observatory.arenas.gab.tasks.<action>

Note: Expected Danish-relevant content volume from Gab is very low.
These tasks are expected to complete quickly with small result sets.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from issue_observatory.arenas.gab.collector import GabCollector
from issue_observatory.config.settings import get_settings
from issue_observatory.core.credential_pool import CredentialPool
from issue_observatory.core.event_bus import elapsed_since, publish_task_update
from issue_observatory.core.exceptions import (
    ArenaAuthError,
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

    Args:
        collection_run_id: UUID string of the parent collection run.
        arena: Arena identifier (``"gab"``).
        status: New status (``"running"`` | ``"completed"`` | ``"failed"``).
        records_collected: Number of records collected.
        error_message: Error description for failed updates.
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
            "gab: failed to update collection_tasks to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.gab.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
    # No fixed time limit — records persist incrementally and stale_run_cleanup handles stuck tasks.
)
def gab_collect_terms(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    terms: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
    language_filter: list[str] | None = None,
    **_extra: Any,
) -> dict[str, Any]:
    """Collect Gab posts for a list of search terms.

    For hashtag terms (starting with ``#``), falls back to the hashtag
    timeline if the search endpoint is restricted. Date filtering is
    applied client-side.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Keywords or hashtags (``#tag``) to search for.
        tier: Tier string — always ``"free"`` for Gab.
        date_from: ISO 8601 lower date bound (optional, client-side filter).
        date_to: ISO 8601 upper date bound (optional, client-side filter).
        max_results: Optional cap on total records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry.
        ArenaCollectionError: Marks the task as FAILED.
    """
    from issue_observatory.arenas.base import Tier

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "gab: collect_by_terms started — run=%s terms=%d",
        collection_run_id,
        len(terms),
    )
    _update_task_status(collection_run_id, "gab", "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="gab",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    credential_pool = CredentialPool()
    collector = GabCollector(credential_pool=credential_pool)

    from issue_observatory.workers._task_helpers import make_batch_sink

    sink = make_batch_sink(collection_run_id, query_design_id)
    collector.configure_batch_persistence(sink=sink, batch_size=100, collection_run_id=collection_run_id)

    # Check if force_recollect is set (opt-out from coverage check)
    force_recollect = _extra.get("force_recollect", False)

    # Pre-collection coverage check: narrow date range to uncovered gaps
    effective_date_from = date_from
    effective_date_to = date_to
    if not force_recollect and date_from and date_to:
        from datetime import datetime as _dt

        from issue_observatory.core.coverage_checker import (
            check_existing_coverage,
        )

        gaps = check_existing_coverage(
            platform="gab",
            date_from=_dt.fromisoformat(date_from) if isinstance(date_from, str) else date_from,
            date_to=_dt.fromisoformat(date_to) if isinstance(date_to, str) else date_to,
            terms=terms,
        )
        if not gaps:
            logger.info(
                "gab: full coverage exists for run=%s — skipping API call, "
                "will reindex existing records only.",
                collection_run_id,
            )
            from issue_observatory.workers._task_helpers import (
                reindex_existing_records,
            )

            linked = reindex_existing_records(
                platform="gab",
                collection_run_id=collection_run_id,
                query_design_id=query_design_id,
                terms=terms,
                date_from=date_from,
                date_to=date_to,
            )
            _update_task_status(
                collection_run_id, "gab", "completed", records_collected=0
            )
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="social_media",
                platform="gab",
                status="completed",
                records_collected=0,
                error_message=None,
                elapsed_seconds=elapsed_since(_task_start),
            )
            return {
                "records_collected": 0,
                "records_linked": linked,
                "status": "completed",
                "arena": "social_media",
                "tier": tier,
                "coverage_skip": True,
            }
        effective_date_from = gaps[0][0].isoformat()
        effective_date_to = gaps[-1][1].isoformat()
        logger.info(
            "gab: narrowing collection to uncovered range %s — %s (run=%s)",
            effective_date_from,
            effective_date_to,
            collection_run_id,
        )

    try:
        remaining = asyncio.run(
            collector.collect_by_terms(
                terms=terms,
                tier=Tier.FREE,
                date_from=effective_date_from,
                date_to=effective_date_to,
                max_results=max_results,
                language_filter=language_filter,
            )
        )
    except NoCredentialAvailableError as exc:
        msg = f"gab: no credential available: {exc}"
        logger.error(msg)
        _update_task_status(collection_run_id, "gab", "failed", error_message=msg)
        raise ArenaCollectionError(msg, arena="social_media", platform="gab") from exc
    except ArenaRateLimitError:
        logger.warning(
            "gab: rate limited on collect_by_terms for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except (ArenaAuthError, ArenaCollectionError) as exc:
        msg = str(exc)
        logger.error("gab: collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, "gab", "failed", error_message=msg)
        raise

    # Persist collected records to the database.
    from issue_observatory.workers._task_helpers import (
        persist_collected_records,
        record_collection_attempts_batch,
    )

    fallback_inserted, fallback_skipped = 0, 0
    if remaining:
        fallback_inserted, fallback_skipped = persist_collected_records(
            remaining, collection_run_id, query_design_id, terms=terms
        )
    inserted = collector.batch_stats["inserted"] + fallback_inserted
    skipped = collector.batch_stats["skipped"] + fallback_skipped

    # Fallback: if in-memory counters lost track, use the actual DB count.
    if inserted == 0:
        from issue_observatory.workers._task_helpers import (
            count_run_platform_records,
        )
        db_count = count_run_platform_records(collection_run_id, "gab")
        if db_count > 0:
            logger.info("gab: in-memory counter=0 but DB has %d records — using DB count", db_count)
            inserted = db_count

    # Record successful collection attempts for future pre-checks.
    if date_from and date_to:
        record_collection_attempts_batch(
            platform="gab",
            collection_run_id=collection_run_id,
            query_design_id=query_design_id,
            inputs=terms,
            input_type="term",
            date_from=date_from,
            date_to=date_to,
            records_returned=inserted,
            per_input_counts=collector.per_input_counts,
        )

    logger.info(
        "gab: collect_by_terms completed — run=%s emitted=%d inserted=%d skipped=%d",
        collection_run_id,
        collector.batch_stats["emitted"],
        inserted,
        skipped,
    )
    _update_task_status(collection_run_id, "gab", "completed", records_collected=inserted)
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="gab",
        status="completed",
        records_collected=inserted,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )
    return {
        "records_collected": inserted,
        "status": "completed",
        "arena": "social_media",
        "tier": "free",
    }


@celery_app.task(
    name="issue_observatory.arenas.gab.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
    # No fixed time limit — records persist incrementally and stale_run_cleanup handles stuck tasks.
)
def gab_collect_actors(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    actor_ids: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
    **_extra: Any,
) -> dict[str, Any]:
    """Collect Gab posts from specific accounts.

    Actor IDs can be Gab account IDs (numeric) or usernames. Usernames
    are resolved to account IDs via the account lookup endpoint.
    Paginates using Mastodon ``max_id`` cursor.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: Gab account IDs or usernames.
        tier: Tier string — always ``"free"`` for Gab.
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
        max_results: Optional cap on total records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry.
        ArenaCollectionError: Marks the task as FAILED.
    """
    from issue_observatory.arenas.base import Tier

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "gab: collect_by_actors started — run=%s actors=%d",
        collection_run_id,
        len(actor_ids),
    )
    _update_task_status(collection_run_id, "gab", "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="gab",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    credential_pool = CredentialPool()
    collector = GabCollector(credential_pool=credential_pool)

    from issue_observatory.workers._task_helpers import make_batch_sink

    sink = make_batch_sink(collection_run_id, query_design_id)
    collector.configure_batch_persistence(sink=sink, batch_size=100, collection_run_id=collection_run_id)

    # Check if force_recollect is set (opt-out from coverage check)
    force_recollect = _extra.get("force_recollect", False)

    # Pre-collection coverage check: narrow date range to uncovered gaps
    effective_date_from = date_from
    effective_date_to = date_to
    if not force_recollect and date_from and date_to:
        from datetime import datetime as _dt

        from issue_observatory.core.coverage_checker import (
            check_existing_coverage,
        )

        gaps = check_existing_coverage(
            platform="gab",
            date_from=_dt.fromisoformat(date_from) if isinstance(date_from, str) else date_from,
            date_to=_dt.fromisoformat(date_to) if isinstance(date_to, str) else date_to,
            actor_ids=actor_ids,
        )
        if not gaps:
            logger.info(
                "gab: full coverage exists for run=%s — skipping API call, "
                "will reindex existing records only.",
                collection_run_id,
            )
            from issue_observatory.workers._task_helpers import (
                reindex_existing_records,
            )

            linked = reindex_existing_records(
                platform="gab",
                collection_run_id=collection_run_id,
                query_design_id=query_design_id,
                actor_ids=actor_ids,
                date_from=date_from,
                date_to=date_to,
            )
            _update_task_status(
                collection_run_id, "gab", "completed", records_collected=0
            )
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="social_media",
                platform="gab",
                status="completed",
                records_collected=0,
                error_message=None,
                elapsed_seconds=elapsed_since(_task_start),
            )
            return {
                "records_collected": 0,
                "records_linked": linked,
                "status": "completed",
                "arena": "social_media",
                "tier": tier,
                "coverage_skip": True,
            }
        effective_date_from = gaps[0][0].isoformat()
        effective_date_to = gaps[-1][1].isoformat()
        logger.info(
            "gab: narrowing collection to uncovered range %s — %s (run=%s)",
            effective_date_from,
            effective_date_to,
            collection_run_id,
        )

    try:
        remaining = asyncio.run(
            collector.collect_by_actors(
                actor_ids=actor_ids,
                tier=Tier.FREE,
                date_from=effective_date_from,
                date_to=effective_date_to,
                max_results=max_results,
            )
        )
    except NoCredentialAvailableError as exc:
        msg = f"gab: no credential available: {exc}"
        logger.error(msg)
        _update_task_status(collection_run_id, "gab", "failed", error_message=msg)
        raise ArenaCollectionError(msg, arena="social_media", platform="gab") from exc
    except ArenaRateLimitError:
        logger.warning(
            "gab: rate limited on collect_by_actors for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except (ArenaAuthError, ArenaCollectionError) as exc:
        msg = str(exc)
        logger.error("gab: actor collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, "gab", "failed", error_message=msg)
        raise

    # Persist collected records to the database.
    from issue_observatory.workers._task_helpers import (
        persist_collected_records,
        record_collection_attempts_batch,
    )

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
        db_count = count_run_platform_records(collection_run_id, "gab")
        if db_count > 0:
            logger.info("gab: in-memory counter=0 but DB has %d records — using DB count", db_count)
            inserted = db_count

    # Record successful collection attempts for future pre-checks.
    if date_from and date_to:
        record_collection_attempts_batch(
            platform="gab",
            collection_run_id=collection_run_id,
            query_design_id=query_design_id,
            inputs=actor_ids,
            input_type="actor",
            date_from=date_from,
            date_to=date_to,
            records_returned=inserted,
            per_input_counts=collector.per_input_counts,
        )

    logger.info(
        "gab: collect_by_actors completed — run=%s emitted=%d inserted=%d skipped=%d",
        collection_run_id,
        collector.batch_stats["emitted"],
        inserted,
        skipped,
    )
    _update_task_status(collection_run_id, "gab", "completed", records_collected=inserted)
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="gab",
        status="completed",
        records_collected=inserted,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )
    return {
        "records_collected": inserted,
        "status": "completed",
        "arena": "social_media",
        "tier": "free",
    }


@celery_app.task(
    name="issue_observatory.arenas.gab.tasks.health_check",
    bind=False,
)
def gab_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the Gab arena.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    credential_pool = CredentialPool()
    collector = GabCollector(credential_pool=credential_pool)
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info("gab: health_check status=%s", result.get("status", "unknown"))
    return result
