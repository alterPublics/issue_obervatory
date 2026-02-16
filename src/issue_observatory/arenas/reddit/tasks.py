"""Celery tasks for the Reddit arena.

Wraps :class:`RedditCollector` methods as Celery tasks with automatic retry
behaviour, collection run status tracking, and structured error reporting.

Task naming convention::

    issue_observatory.arenas.reddit.tasks.<action>

All tasks are registered in the Celery app via the ``include`` list in
:mod:`issue_observatory.workers.celery_app`.

Retry policy:
- ``ArenaRateLimitError`` (including ``asyncprawcore.exceptions.TooManyRequests``
  translated upstream) triggers automatic retry with exponential backoff
  (``autoretry_for`` + ``retry_backoff=True``), up to ``max_retries=3``.
- ``ArenaCollectionError`` subclasses are logged and re-raised so that Celery
  marks the task as FAILED.  The ``collection_tasks`` row is updated with the
  error message regardless.

Database updates:
- Best-effort fire-and-forget via synchronous SQLAlchemy run inside the
  Celery worker thread.  DB failures are logged at WARNING and do not mask
  the collection outcome.

PRAW instance ownership:
- Each task creates its own ``RedditCollector`` and ``asyncpraw.Reddit``
  instance.  Instances are not shared across workers or tasks.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from issue_observatory.arenas.reddit.collector import RedditCollector
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

    Runs the DB update in a synchronous SQLAlchemy session on the calling
    thread.  Any failure is logged at WARNING and execution continues.

    Args:
        collection_run_id: UUID string of the parent collection run.
        arena: Arena identifier (``"social_media"``).
        status: New status value (``"running"`` | ``"completed"`` | ``"failed"``).
        records_collected: Number of records collected (for ``"completed"`` updates).
        error_message: Error description (for ``"failed"`` updates).
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
            "reddit: failed to update collection_tasks status to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.reddit.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,  # cap backoff at 5 minutes
    acks_late=True,
)
def reddit_collect_terms(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    terms: list[str],
    tier: str = "free",
    include_comments: bool = False,
) -> dict[str, Any]:
    """Collect Reddit posts (and optionally comments) for a list of search terms.

    Wraps :meth:`RedditCollector.collect_by_terms` as an idempotent Celery
    task.  Updates the ``collection_tasks`` row with progress and final status.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms to query across Danish subreddits.
        tier: Tier string — only ``"free"`` is valid for Reddit.
        include_comments: Whether to collect top-level comments for matched
            posts.  Defaults to ``False`` to conserve API quota.

    Returns:
        Dict with:
        - ``records_collected`` (int): Number of normalized records retrieved.
        - ``status`` (str): ``"completed"`` or ``"failed"``.
        - ``arena`` (str): ``"social_media"``.
        - ``platform`` (str): ``"reddit"``.
        - ``tier`` (str): The tier used.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED in Celery.
        NoCredentialAvailableError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    logger.info(
        "reddit: collect_by_terms started — run=%s terms=%d tier=%s include_comments=%s",
        collection_run_id,
        len(terms),
        tier,
        include_comments,
    )
    _update_task_status(collection_run_id, "social_media", "running")

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"reddit: invalid tier '{tier}'. Only 'free' is valid for Reddit."
        logger.error(msg)
        _update_task_status(collection_run_id, "social_media", "failed", error_message=msg)
        raise ArenaCollectionError(msg, arena="social_media", platform="reddit")

    credential_pool = CredentialPool()
    collector = RedditCollector(
        credential_pool=credential_pool,
        include_comments=include_comments,
    )

    try:
        records = asyncio.run(
            collector.collect_by_terms(
                terms=terms,
                tier=tier_enum,
                max_results=None,
            )
        )
    except NoCredentialAvailableError as exc:
        msg = f"reddit: no credential available for tier={tier}: {exc}"
        logger.error(msg)
        _update_task_status(collection_run_id, "social_media", "failed", error_message=msg)
        raise
    except ArenaRateLimitError:
        logger.warning(
            "reddit: rate limited on collect_by_terms for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error("reddit: collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, "social_media", "failed", error_message=msg)
        raise

    count = len(records)
    logger.info(
        "reddit: collect_by_terms completed — run=%s records=%d",
        collection_run_id,
        count,
    )
    _update_task_status(
        collection_run_id, "social_media", "completed", records_collected=count
    )

    return {
        "records_collected": count,
        "status": "completed",
        "arena": "social_media",
        "platform": "reddit",
        "tier": tier,
    }


@celery_app.task(
    name="issue_observatory.arenas.reddit.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def reddit_collect_actors(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    actor_ids: list[str],
    tier: str = "free",
) -> dict[str, Any]:
    """Collect posts and comments by specific Reddit users (actors).

    Wraps :meth:`RedditCollector.collect_by_actors` as an idempotent Celery
    task.  Updates the ``collection_tasks`` row with progress and final status.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: Reddit usernames to collect from.
        tier: Tier string — only ``"free"`` is valid for Reddit.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``platform``,
        and ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED in Celery.
        NoCredentialAvailableError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    logger.info(
        "reddit: collect_by_actors started — run=%s actors=%d tier=%s",
        collection_run_id,
        len(actor_ids),
        tier,
    )
    _update_task_status(collection_run_id, "social_media", "running")

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"reddit: invalid tier '{tier}'. Only 'free' is valid for Reddit."
        logger.error(msg)
        _update_task_status(collection_run_id, "social_media", "failed", error_message=msg)
        raise ArenaCollectionError(msg, arena="social_media", platform="reddit")

    credential_pool = CredentialPool()
    collector = RedditCollector(credential_pool=credential_pool)

    try:
        records = asyncio.run(
            collector.collect_by_actors(
                actor_ids=actor_ids,
                tier=tier_enum,
                max_results=None,
            )
        )
    except NoCredentialAvailableError as exc:
        msg = f"reddit: no credential available for tier={tier}: {exc}"
        logger.error(msg)
        _update_task_status(collection_run_id, "social_media", "failed", error_message=msg)
        raise
    except ArenaRateLimitError:
        logger.warning(
            "reddit: rate limited on collect_by_actors for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error("reddit: collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, "social_media", "failed", error_message=msg)
        raise

    count = len(records)
    logger.info(
        "reddit: collect_by_actors completed — run=%s records=%d",
        collection_run_id,
        count,
    )
    _update_task_status(
        collection_run_id, "social_media", "completed", records_collected=count
    )

    return {
        "records_collected": count,
        "status": "completed",
        "arena": "social_media",
        "platform": "reddit",
        "tier": tier,
    }


@celery_app.task(
    name="issue_observatory.arenas.reddit.tasks.health_check",
    bind=False,
)
def reddit_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the Reddit arena.

    Delegates to :meth:`RedditCollector.health_check`, which fetches a single
    hot post from r/Denmark.  Designed for the admin health dashboard and
    Celery Beat schedule.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail``.
    """
    credential_pool = CredentialPool()
    collector = RedditCollector(credential_pool=credential_pool)
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info(
        "reddit: health_check status=%s", result.get("status", "unknown")
    )
    return result
