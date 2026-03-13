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
import time
from typing import Any

from issue_observatory.arenas.reddit.collector import RedditCollector
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
    actors_skipped: int = 0,
    skipped_actor_detail: list[dict[str, str]] | None = None,
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
        actors_skipped: Number of actors skipped due to per-actor errors.
        skipped_actor_detail: List of dicts with actor_id, reason, error.
    """
    try:
        from issue_observatory.core.database import get_sync_session

        with get_sync_session() as session:
            import json

            from sqlalchemy import text

            session.execute(
                text(
                    """
                    UPDATE collection_tasks
                    SET status = :status,
                        records_collected = GREATEST(records_collected, :records_collected),
                        error_message = :error_message,
                        actors_skipped = :actors_skipped,
                        skipped_actor_detail = :skipped_actor_detail,
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
                    "actors_skipped": actors_skipped,
                    "skipped_actor_detail": json.dumps(skipped_actor_detail)
                    if skipped_actor_detail
                    else None,
                    "run_id": collection_run_id,
                    "arena": arena,
                },
            )
            session.commit()
    except Exception as exc:
        logger.warning(
            "reddit: failed to update collection_tasks status to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# arenas_config helper
# ---------------------------------------------------------------------------


def _load_arenas_config(query_design_id: str) -> dict:
    """Load ``arenas_config`` from the QueryDesign row identified by *query_design_id*.

    Uses a synchronous SQLAlchemy session (Celery worker context).  Returns an
    empty dict if the design is not found or on any DB error.

    Args:
        query_design_id: UUID string of the owning query design.

    Returns:
        The ``arenas_config`` JSONB dict, or ``{}`` on failure.
    """
    try:
        from sqlalchemy import text

        from issue_observatory.core.database import get_sync_session

        with get_sync_session() as session:
            row = session.execute(
                text("SELECT arenas_config FROM query_designs WHERE id = :id"),
                {"id": query_design_id},
            ).fetchone()
            if row and row[0]:
                return dict(row[0])
    except Exception as exc:
        logger.warning(
            "reddit: failed to load arenas_config for design %s: %s",
            query_design_id,
            exc,
        )
    return {}


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
    # No fixed time limit — records persist incrementally and stale_run_cleanup handles stuck tasks.
)
def reddit_collect_terms(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    terms: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    include_comments: bool = False,
    language_filter: list[str] | None = None,
    **_extra: Any,
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
    from issue_observatory.arenas.base import Tier

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "reddit: collect_by_terms started — run=%s terms=%d tier=%s include_comments=%s",
        collection_run_id,
        len(terms),
        tier,
        include_comments,
    )
    _update_task_status(collection_run_id, "reddit", "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="reddit",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    # GR-03: read researcher-configured extra subreddits from arenas_config.
    arenas_config = _load_arenas_config(query_design_id)
    extra_subreddits: list[str] | None = None
    reddit_config = arenas_config.get("reddit") or {}
    if isinstance(reddit_config, dict):
        raw_subreddits = reddit_config.get("custom_subreddits")
        if isinstance(raw_subreddits, list) and raw_subreddits:
            extra_subreddits = [str(s) for s in raw_subreddits if s]

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"reddit: invalid tier '{tier}'. Only 'free' is valid for Reddit."
        logger.error(msg)
        _update_task_status(collection_run_id, "reddit", "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="reddit",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise ArenaCollectionError(msg, arena="social_media", platform="reddit")

    credential_pool = CredentialPool()
    collector = RedditCollector(
        credential_pool=credential_pool,
        include_comments=include_comments,
    )

    from issue_observatory.workers._task_helpers import (
        make_batch_sink,
        persist_collected_records,
        record_collection_attempts_batch,
        reindex_existing_records,
    )

    sink = make_batch_sink(collection_run_id, query_design_id, terms=terms)
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
            platform="reddit",
            date_from=_dt.fromisoformat(date_from) if isinstance(date_from, str) else date_from,
            date_to=_dt.fromisoformat(date_to) if isinstance(date_to, str) else date_to,
            terms=terms,
        )
        if not gaps:
            logger.info(
                "reddit: full coverage exists for run=%s — skipping API call, "
                "will reindex existing records only.",
                collection_run_id,
            )
            linked = reindex_existing_records(
                platform="reddit",
                collection_run_id=collection_run_id,
                query_design_id=query_design_id,
                terms=terms,
                date_from=date_from,
                date_to=date_to,
            )
            _update_task_status(
                collection_run_id, "reddit", "completed", records_collected=0
            )
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="social_media",
                platform="reddit",
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
                "platform": "reddit",
                "tier": tier,
                "coverage_skip": True,
            }
        # Use the first gap's boundaries as the narrowed date range
        effective_date_from = gaps[0][0].isoformat()
        effective_date_to = gaps[-1][1].isoformat()
        logger.info(
            "reddit: narrowing collection to uncovered range %s — %s (run=%s)",
            effective_date_from,
            effective_date_to,
            collection_run_id,
        )

    try:
        remaining = asyncio.run(
            collector.collect_by_terms(
                terms=terms,
                tier=tier_enum,
                max_results=None,
                language_filter=language_filter,
                extra_subreddits=extra_subreddits,
            )
        )
    except NoCredentialAvailableError as exc:
        msg = f"reddit: no credential available for tier={tier}: {exc}"
        logger.error(msg)
        _update_task_status(collection_run_id, "reddit", "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="reddit",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
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
        _update_task_status(collection_run_id, "reddit", "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="reddit",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise

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
        db_count = count_run_platform_records(collection_run_id, "reddit")
        if db_count > 0:
            logger.info("reddit: in-memory counter=0 but DB has %d records — using DB count", db_count)
            inserted = db_count

    # Link existing records from other runs that match these terms/dates.
    linked = reindex_existing_records(
        platform="reddit",
        collection_run_id=collection_run_id,
        query_design_id=query_design_id,
        terms=terms,
        date_from=date_from,
        date_to=date_to,
    )

    # Record successful collection attempts for future pre-checks.
    if date_from and date_to:
        record_collection_attempts_batch(
            platform="reddit",
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
        "reddit: collect_by_terms completed — run=%s emitted=%d inserted=%d "
        "skipped=%d linked=%d",
        collection_run_id,
        collector.batch_stats["emitted"],
        inserted,
        skipped,
        linked,
    )
    _update_task_status(
        collection_run_id, "reddit", "completed", records_collected=inserted
    )
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="reddit",
        status="completed",
        records_collected=inserted,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    return {
        "records_collected": inserted,
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
    # No fixed time limit — records persist incrementally and stale_run_cleanup handles stuck tasks.
)
def reddit_collect_actors(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    actor_ids: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    **_extra: Any,
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
    from issue_observatory.arenas.base import Tier

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.info(
        "reddit: collect_by_actors started — run=%s actors=%d tier=%s",
        collection_run_id,
        len(actor_ids),
        tier,
    )
    _update_task_status(collection_run_id, "reddit", "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="reddit",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"reddit: invalid tier '{tier}'. Only 'free' is valid for Reddit."
        logger.error(msg)
        _update_task_status(collection_run_id, "reddit", "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="reddit",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise ArenaCollectionError(msg, arena="social_media", platform="reddit")

    credential_pool = CredentialPool()
    collector = RedditCollector(credential_pool=credential_pool)

    from issue_observatory.workers._task_helpers import (
        make_batch_sink,
        persist_collected_records,
        record_collection_attempts_batch,
        reindex_existing_records,
    )

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
            platform="reddit",
            date_from=_dt.fromisoformat(date_from) if isinstance(date_from, str) else date_from,
            date_to=_dt.fromisoformat(date_to) if isinstance(date_to, str) else date_to,
            actor_ids=actor_ids,
        )
        if not gaps:
            logger.info(
                "reddit: full coverage exists for run=%s — skipping API call, "
                "will reindex existing records only.",
                collection_run_id,
            )
            linked = reindex_existing_records(
                platform="reddit",
                collection_run_id=collection_run_id,
                query_design_id=query_design_id,
                actor_ids=actor_ids,
                date_from=date_from,
                date_to=date_to,
            )
            _update_task_status(
                collection_run_id, "reddit", "completed", records_collected=0
            )
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="social_media",
                platform="reddit",
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
                "platform": "reddit",
                "tier": tier,
                "coverage_skip": True,
            }
        # Use the first gap's boundaries as the narrowed date range
        effective_date_from = gaps[0][0].isoformat()
        effective_date_to = gaps[-1][1].isoformat()
        logger.info(
            "reddit: narrowing collection to uncovered range %s — %s (run=%s)",
            effective_date_from,
            effective_date_to,
            collection_run_id,
        )

    try:
        remaining = asyncio.run(
            collector.collect_by_actors(
                actor_ids=actor_ids,
                tier=tier_enum,
                max_results=None,
            )
        )
    except NoCredentialAvailableError as exc:
        msg = f"reddit: no credential available for tier={tier}: {exc}"
        logger.error(msg)
        _update_task_status(collection_run_id, "reddit", "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="reddit",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
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
        _update_task_status(collection_run_id, "reddit", "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="reddit",
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
        db_count = count_run_platform_records(collection_run_id, "reddit")
        if db_count > 0:
            logger.info("reddit: in-memory counter=0 but DB has %d records — using DB count", db_count)
            inserted = db_count

    # Link existing records from other runs that match these actors/dates.
    linked = reindex_existing_records(
        platform="reddit",
        collection_run_id=collection_run_id,
        query_design_id=query_design_id,
        actor_ids=actor_ids,
        date_from=date_from,
        date_to=date_to,
    )

    # Record successful collection attempts for future pre-checks.
    if date_from and date_to:
        record_collection_attempts_batch(
            platform="reddit",
            collection_run_id=collection_run_id,
            query_design_id=query_design_id,
            inputs=actor_ids,
            input_type="actor",
            date_from=date_from,
            date_to=date_to,
            records_returned=inserted,
            per_input_counts=collector.per_input_counts,
        )

    skipped_actors = collector.skipped_actors
    logger.info(
        "reddit: collect_by_actors completed — run=%s emitted=%d inserted=%d "
        "dupes_skipped=%d actors_skipped=%d linked=%d",
        collection_run_id,
        collector.batch_stats["emitted"],
        inserted,
        skipped,
        len(skipped_actors),
        linked,
    )
    _update_task_status(
        collection_run_id,
        "reddit",
        "completed",
        records_collected=inserted,
        actors_skipped=len(skipped_actors),
        skipped_actor_detail=skipped_actors or None,
    )
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="reddit",
        status="completed",
        records_collected=inserted,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    return {
        "records_collected": inserted,
        "status": "completed",
        "arena": "social_media",
        "platform": "reddit",
        "tier": tier,
        "actors_skipped": len(skipped_actors),
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


@celery_app.task(
    name="issue_observatory.arenas.reddit.tasks.collect_comments",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
)
def reddit_collect_comments(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    post_ids: list[dict],
    tier: str = "free",
    max_comments_per_post: int = 50,
    depth: int = 0,
    **_extra: Any,
) -> dict[str, Any]:
    """Collect comments for a list of Reddit posts.

    Wraps :meth:`RedditCollector.collect_comments` as an idempotent Celery
    task.  Updates the ``collection_tasks`` row with progress and final status.
    Publishes SSE events for live monitoring.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        post_ids: List of dicts each containing a ``platform_id`` key with
            the Reddit base-36 post ID (e.g. ``[{"platform_id": "abc123"}]``).
        tier: Tier string — only ``"free"`` is valid for Reddit.
        max_comments_per_post: Maximum comments to collect per post.
            Defaults to ``50``.
        depth: Maximum comment depth to include (``0`` = top-level only).

    Returns:
        Dict with:
        - ``records_collected`` (int): Number of normalized comment records.
        - ``status`` (str): ``"completed"`` or ``"failed"``.
        - ``arena`` (str): ``"reddit_comments"``.
        - ``platform`` (str): ``"reddit"``.
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
        "reddit: collect_comments started — run=%s posts=%d tier=%s "
        "max_comments_per_post=%d depth=%d",
        collection_run_id,
        len(post_ids),
        tier,
        max_comments_per_post,
        depth,
    )
    _update_task_status(collection_run_id, "reddit_comments", "running")
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="reddit_comments",
        platform="reddit",
        status="running",
        records_collected=0,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    try:
        tier_enum = Tier(tier)
    except ValueError:
        msg = f"reddit: invalid tier '{tier}'. Only 'free' is valid for Reddit."
        logger.error(msg)
        _update_task_status(collection_run_id, "reddit_comments", "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="reddit_comments",
            platform="reddit",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise ArenaCollectionError(msg, arena="reddit_comments", platform="reddit")

    credential_pool = CredentialPool()
    collector = RedditCollector(credential_pool=credential_pool)

    from issue_observatory.workers._task_helpers import (
        make_batch_sink,
        persist_collected_records,
    )

    sink = make_batch_sink(collection_run_id, query_design_id)
    collector.configure_batch_persistence(
        sink=sink, batch_size=100, collection_run_id=collection_run_id
    )

    try:
        remaining = asyncio.run(
            collector.collect_comments(
                post_ids=post_ids,
                tier=tier_enum,
                max_comments_per_post=max_comments_per_post,
                depth=depth,
            )
        )
    except NoCredentialAvailableError as exc:
        msg = f"reddit: no credential available for tier={tier}: {exc}"
        logger.error(msg)
        _update_task_status(collection_run_id, "reddit_comments", "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="reddit_comments",
            platform="reddit",
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise
    except ArenaRateLimitError:
        logger.warning(
            "reddit: rate limited on collect_comments for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except ArenaCollectionError as exc:
        msg = str(exc)
        logger.error("reddit: collection error for run=%s: %s", collection_run_id, msg)
        _update_task_status(collection_run_id, "reddit_comments", "failed", error_message=msg)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="reddit_comments",
            platform="reddit",
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

    # Fallback: if in-memory counters lost track, use the actual DB count.
    if inserted == 0:
        from issue_observatory.workers._task_helpers import (
            count_run_platform_records,
        )

        db_count = count_run_platform_records(collection_run_id, "reddit")
        if db_count > 0:
            logger.info(
                "reddit: collect_comments in-memory counter=0 but DB has %d records — using DB count",
                db_count,
            )
            inserted = db_count

    logger.info(
        "reddit: collect_comments completed — run=%s emitted=%d inserted=%d posts=%d",
        collection_run_id,
        collector.batch_stats["emitted"],
        inserted,
        len(post_ids),
    )
    _update_task_status(
        collection_run_id, "reddit_comments", "completed", records_collected=inserted
    )
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="reddit_comments",
        platform="reddit",
        status="completed",
        records_collected=inserted,
        error_message=None,
        elapsed_seconds=elapsed_since(_task_start),
    )

    return {
        "records_collected": inserted,
        "status": "completed",
        "arena": "reddit_comments",
        "platform": "reddit",
        "tier": tier,
    }
