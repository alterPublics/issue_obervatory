"""Celery tasks for the Facebook arena.

Wraps :class:`FacebookCollector` methods as Celery tasks with retry logic,
collection run status tracking, and error reporting.

**Actor-only arena**: Facebook does not support keyword-based collection via the
Bright Data Web Scraper API. The ``facebook_collect_terms`` task immediately fails
with a descriptive :exc:`~issue_observatory.core.exceptions.ArenaCollectionError`
explaining that actor-based collection must be used instead.

Task naming::

    issue_observatory.arenas.facebook.tasks.<action>

Retry policy:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff.
  Maximum 2 retries (Bright Data dataset delivery is expensive — minimize
  duplicate requests). Backoff capped at 900 seconds (15 minutes).
- ``NoCredentialAvailableError`` immediately marks the task as FAILED.

Time limits:
- No Celery-level time limits — actors are collected sequentially, each taking
  2-4 minutes for Bright Data trigger/poll/download. Coverage is recorded
  per-actor so a crash preserves progress. Stale run cleanup handles genuinely
  stuck tasks (no activity for >30 min).

All task arguments are JSON-serializable.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

from issue_observatory.arenas.facebook.collector import FacebookCollector
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

_ARENA: str = "social_media"
_PLATFORM: str = "facebook"

_TERM_COLLECTION_NOT_SUPPORTED: str = (
    "Facebook does not support keyword-based collection. "
    "The Bright Data Web Scraper API only supports actor-based collection "
    "(Facebook page URLs, group URLs, or profile URLs). "
    "To collect from Facebook: add pages or groups to the Actor Directory "
    "and use actor-based collection mode."
)


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
        arena: Arena identifier (``"social_media"``).
        status: New status (``"running"`` | ``"completed"`` | ``"failed"``).
        records_collected: Number of records collected (for completed updates).
        error_message: Error description (for failed updates).
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
            "facebook: failed to update collection_tasks to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.facebook.tasks.collect_by_terms",
    bind=True,
    max_retries=0,
    acks_late=True,
    time_limit=60,
)
def facebook_collect_terms(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    terms: list[str],
    tier: str = "medium",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
    language_filter: list[str] | None = None,
    **_extra: Any,
) -> dict[str, Any]:
    """Immediately fail — Facebook does not support keyword-based collection.

    Facebook and Instagram are actor-only arenas. The Bright Data Web Scraper API
    does not support keyword-based discovery. This task exists to provide a clear
    error message if it is mistakenly dispatched, rather than silently doing nothing.

    To collect from Facebook, add Facebook pages or groups to the Actor Directory
    and use the ``facebook_collect_actors`` task instead.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Ignored — keyword search is not supported.
        tier: Ignored.
        date_from: Ignored.
        date_to: Ignored.
        max_results: Ignored.
        language_filter: Ignored.

    Raises:
        ArenaCollectionError: Always — Facebook does not support keyword search.
    """
    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.error(
        "facebook: collect_by_terms called but Facebook does not support keyword search. "
        "run=%s — failing immediately.",
        collection_run_id,
    )
    _update_task_status(
        collection_run_id, _PLATFORM, "failed", error_message=_TERM_COLLECTION_NOT_SUPPORTED
    )
    publish_task_update(
        redis_url=_redis_url,
        run_id=collection_run_id,
        arena="social_media",
        platform="facebook",
        status="failed",
        records_collected=0,
        error_message=_TERM_COLLECTION_NOT_SUPPORTED,
        elapsed_seconds=elapsed_since(_task_start),
    )
    raise ArenaCollectionError(
        _TERM_COLLECTION_NOT_SUPPORTED,
        arena=_ARENA,
        platform=_PLATFORM,
    )


@celery_app.task(
    name="issue_observatory.arenas.facebook.tasks.collect_by_actors",
    bind=True,
    max_retries=2,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=900,
    acks_late=True,
    # No fixed time limit — chunks persist records incrementally, and
    # stale_run_cleanup catches genuinely stuck tasks (>30 min inactivity).
)
def facebook_collect_actors(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    actor_ids: list[str],
    tier: str = "medium",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
    **_extra: Any,
) -> dict[str, Any]:
    """Collect Facebook posts from specific pages, groups, or profiles.

    Wraps :meth:`FacebookCollector.collect_by_actors` as a Celery task.
    Each entry in *actor_ids* should be a full Facebook page URL, group URL,
    or profile URL. Group URLs (containing ``/groups/``) are automatically routed
    to the Groups scraper; all other URLs use the Posts scraper.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: Facebook page URLs, group URLs, or profile URLs.
        tier: Tier string — ``"medium"`` (Bright Data, default).
        date_from: ISO 8601 lower date bound (optional).
        date_to: ISO 8601 upper date bound (optional).
        max_results: Optional cap on total records.
        **_extra: Extra keyword arguments passed by the orchestration layer
            (e.g. ``public_figure_ids``, ``language_filter``). Silently
            ignored — actor-only tasks do not use these parameters.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``platform``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry (max 2, backoff ≤ 900s).
        ArenaCollectionError: Marks the task as FAILED.
        NoCredentialAvailableError: Marks the task as FAILED immediately.
    """
    from issue_observatory.arenas.base import Tier

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    try:
        logger.info(
            "facebook: collect_by_actors started — run=%s tier=%s actors=%d",
            collection_run_id,
            tier,
            len(actor_ids),
        )
        _update_task_status(collection_run_id, _PLATFORM, "running")
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="facebook",
            status="running",
            records_collected=0,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        from issue_observatory.workers._task_helpers import make_batch_sink

        credential_pool = CredentialPool()
        collector = FacebookCollector(credential_pool=credential_pool)

        # Facebook PREMIUM (MCL) raises NotImplementedError — fall back to MEDIUM.
        tier_enum = Tier(tier)
        if tier_enum == Tier.PREMIUM:
            logger.info(
                "facebook: PREMIUM tier not implemented, falling back to MEDIUM for run=%s",
                collection_run_id,
            )
            tier_enum = Tier.MEDIUM
            tier = "medium"
        sink = make_batch_sink(collection_run_id, query_design_id)
        collector.configure_batch_persistence(
            sink=sink, batch_size=100, collection_run_id=collection_run_id
        )

        # Normalize URLs before coverage check so keys match BD's format.
        from issue_observatory.arenas.facebook.collector import (
            _normalize_facebook_url,
        )
        from issue_observatory.workers._task_helpers import (
            RunCancelledError,
            check_run_cancelled,
            clear_url_errors,
            count_run_platform_records,
            get_suppressed_urls,
            record_collection_attempts_batch,
            record_url_errors,
        )

        normalized_actor_ids = []
        for aid in actor_ids:
            url = _normalize_facebook_url(aid)
            if url is not None:
                normalized_actor_ids.append(url)
        if not normalized_actor_ids:
            normalized_actor_ids = actor_ids  # fallback to originals

        # Randomize actor order to avoid always hitting the same actors first
        # if a run is interrupted partway through.
        random.shuffle(normalized_actor_ids)

        # Check if force_recollect is set (opt-out from coverage check)
        force_recollect = _extra.get("force_recollect", False)

        # Suppress dead/errored URLs to avoid wasting Bright Data credits.
        suppressed = get_suppressed_urls(_PLATFORM, normalized_actor_ids)
        if suppressed:
            original_count = len(normalized_actor_ids)
            normalized_actor_ids = [u for u in normalized_actor_ids if u not in suppressed]
            logger.info(
                "facebook: suppressed %d/%d dead/errored URLs for run=%s",
                len(suppressed),
                original_count,
                collection_run_id,
            )
            if not normalized_actor_ids:
                logger.info(
                    "facebook: ALL URLs suppressed — completing with 0 records for run=%s",
                    collection_run_id,
                )
                _update_task_status(
                    collection_run_id, _PLATFORM, "completed", records_collected=0
                )
                publish_task_update(
                    redis_url=_redis_url,
                    run_id=collection_run_id,
                    arena=_ARENA,
                    platform=_PLATFORM,
                    status="completed",
                    records_collected=0,
                    error_message=None,
                    elapsed_seconds=elapsed_since(_task_start),
                )
                return {
                    "records_collected": 0,
                    "status": "completed",
                    "arena": _ARENA,
                    "platform": _PLATFORM,
                    "tier": tier,
                    "all_urls_suppressed": True,
                }

        # ---------------------------------------------------------------
        # Per-actor sequential collection loop (single event loop)
        # ---------------------------------------------------------------
        async def _run_per_actor_loop() -> tuple[int, list[str]]:
            """Collect each actor sequentially within one asyncio event loop.

            Returns (total_inserted, actor_errors).
            """
            _total = 0
            _errors: list[str] = []

            for actor_idx, actor_url in enumerate(normalized_actor_ids, 1):
                actor_label = actor_url.split("/")[-1] or actor_url

                # 1. Check for cancellation between actors.
                try:
                    check_run_cancelled(collection_run_id)
                except RunCancelledError:
                    logger.info(
                        "facebook: run cancelled after %d/%d actors — stopping.",
                        actor_idx - 1,
                        len(normalized_actor_ids),
                    )
                    break

                # 2. Per-actor coverage check (sync DB — fine from async).
                effective_date_from = date_from
                effective_date_to = date_to
                if not force_recollect and date_from and date_to:
                    from datetime import datetime as _dt

                    from issue_observatory.core.coverage_checker import (
                        check_existing_coverage,
                    )

                    gaps = check_existing_coverage(
                        platform=_PLATFORM,
                        date_from=(
                            _dt.fromisoformat(date_from)
                            if isinstance(date_from, str)
                            else date_from
                        ),
                        date_to=(
                            _dt.fromisoformat(date_to)
                            if isinstance(date_to, str)
                            else date_to
                        ),
                        actor_ids=[actor_url],
                    )
                    if not gaps:
                        logger.info(
                            "facebook: [%d/%d] %s — skipped (full coverage exists)",
                            actor_idx,
                            len(normalized_actor_ids),
                            actor_label,
                        )
                        continue
                    effective_date_from = gaps[0][0].isoformat()
                    effective_date_to = gaps[-1][1].isoformat()

                # 3. Collect from this single actor.
                logger.info(
                    "facebook: [%d/%d] %s — collecting with dates=%s..%s "
                    "max_results=%s tier=%s",
                    actor_idx,
                    len(normalized_actor_ids),
                    actor_label,
                    effective_date_from,
                    effective_date_to,
                    max_results,
                    tier,
                )
                try:
                    await collector.collect_by_actors(
                        [actor_url],
                        tier_enum,
                        date_from=effective_date_from,
                        date_to=effective_date_to,
                        max_results=max_results,
                    )
                except (
                    NoCredentialAvailableError,
                    ArenaRateLimitError,
                    NotImplementedError,
                    ArenaAuthError,
                ):
                    raise
                except Exception as exc:
                    logger.error(
                        "facebook: [%d/%d] %s — error: %s",
                        actor_idx,
                        len(normalized_actor_ids),
                        actor_label,
                        exc,
                    )
                    _errors.append(f"{actor_label}: {exc}")
                    continue

                # 4. Track per-actor results.
                stats = collector.batch_stats
                actor_count = stats["inserted"]
                logger.info(
                    "facebook: [%d/%d] %s — batch_stats=%s "
                    "bd_errors=%d",
                    actor_idx,
                    len(normalized_actor_ids),
                    actor_label,
                    stats,
                    len(collector.brightdata_errors),
                )
                _total += actor_count

                # 5. Record per-actor coverage immediately (sync DB).
                if date_from and date_to:
                    record_collection_attempts_batch(
                        platform=_PLATFORM,
                        collection_run_id=collection_run_id,
                        query_design_id=query_design_id,
                        inputs=[actor_url],
                        input_type="actor",
                        date_from=date_from,
                        date_to=date_to,
                        records_returned=actor_count,
                        per_input_counts={actor_url: actor_count},
                    )

                # 6. Track Bright Data errors and clear recovered URLs.
                bd_errors = collector.brightdata_errors
                actor_bd_errors = [
                    e for e in bd_errors if e.get("url") == actor_url
                ]
                if actor_bd_errors:
                    record_url_errors(_PLATFORM, actor_bd_errors)
                else:
                    clear_url_errors(_PLATFORM, [actor_url])

                # 7. Log per-actor progress.
                logger.info(
                    "facebook: [%d/%d] %s — %d records",
                    actor_idx,
                    len(normalized_actor_ids),
                    actor_label,
                    actor_count,
                )

                # 8. SSE progress update (sync Redis).
                publish_task_update(
                    redis_url=_redis_url,
                    run_id=collection_run_id,
                    arena=_ARENA,
                    platform=_PLATFORM,
                    status="running",
                    records_collected=_total,
                    error_message=None,
                    elapsed_seconds=elapsed_since(_task_start),
                )

            return _total, _errors

        try:
            total_inserted, actor_errors = asyncio.run(_run_per_actor_loop())
        except NoCredentialAvailableError as exc:
            msg = f"facebook: no credential available for tier={tier}: {exc}"
            logger.error(msg)
            _update_task_status(
                collection_run_id, _PLATFORM, "failed", error_message=msg
            )
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="social_media",
                platform="facebook",
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise ArenaCollectionError(
                msg, arena=_ARENA, platform=_PLATFORM
            ) from exc
        except ArenaRateLimitError:
            logger.warning(
                "facebook: rate limited — will retry for run=%s.",
                collection_run_id,
            )
            raise
        except NotImplementedError:
            raise
        except ArenaAuthError as exc:
            msg = f"facebook: auth error for run={collection_run_id}: {exc}"
            logger.error(msg)
            _update_task_status(
                collection_run_id, _PLATFORM, "failed", error_message=msg
            )
            raise ArenaCollectionError(
                msg, arena=_ARENA, platform=_PLATFORM
            ) from exc

        # ---------------------------------------------------------------
        # Post-loop: finalize
        # ---------------------------------------------------------------

        # Fallback: if per-actor counters missed records, use DB count.
        if total_inserted == 0:
            db_count = count_run_platform_records(collection_run_id, "facebook")
            if db_count > 0:
                logger.info(
                    "facebook: per-actor counter=0 but DB has %d records — using DB count",
                    db_count,
                )
                total_inserted = db_count

        error_summary = (
            f" ({len(actor_errors)} actor errors)" if actor_errors else ""
        )
        logger.info(
            "facebook: collect_by_actors completed — run=%s inserted=%d%s",
            collection_run_id,
            total_inserted,
            error_summary,
        )
        _update_task_status(
            collection_run_id, _PLATFORM, "completed", records_collected=total_inserted
        )
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena=_ARENA,
            platform=_PLATFORM,
            status="completed",
            records_collected=total_inserted,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )
        return {
            "records_collected": total_inserted,
            "status": "completed",
            "arena": _ARENA,
            "platform": _PLATFORM,
            "tier": tier,
        }
    except Exception as exc:
        msg = f"facebook: unexpected error for run={collection_run_id}: {type(exc).__name__}: {exc}"
        logger.error(msg, exc_info=True)

        # Salvage: per-actor persistence means most records are already saved.
        salvaged_count = 0
        try:
            from issue_observatory.workers._task_helpers import (
                count_run_platform_records as _count,
            )

            salvaged_count = _count(collection_run_id, "facebook")
        except Exception:
            logger.warning("facebook: failed to count salvaged records", exc_info=True)

        _update_task_status(
            collection_run_id, _PLATFORM, "failed",
            records_collected=salvaged_count,
            error_message=msg[:500],
        )
        publish_task_update(
            redis_url=_settings.redis_url,
            run_id=collection_run_id,
            arena=_ARENA,
            platform=_PLATFORM,
            status="failed",
            records_collected=salvaged_count,
            error_message=msg[:500],
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise


@celery_app.task(
    name="issue_observatory.arenas.facebook.tasks.collect_comments",
    bind=True,
    max_retries=2,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=900,
    acks_late=True,
)
def facebook_collect_comments(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    post_ids: list[dict],
    tier: str = "medium",
    max_comments_per_post: int = 200,
    depth: int = 0,
    **_extra: Any,
) -> dict[str, Any]:
    """Collect comments for Facebook posts via Bright Data.

    Wraps :meth:`FacebookCollector.collect_comments` as a Celery task.
    Each entry in *post_ids* must be a dict with a ``url`` key pointing to
    a Facebook post URL. Comments are collected in a single Bright Data
    trigger/poll/download cycle.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        post_ids: List of dicts with ``url`` key (Facebook post URLs).
        tier: Tier string — ``"medium"`` (Bright Data, default).
        max_comments_per_post: Maximum comments to request per post.
        depth: Unused — Bright Data returns a flat comment list.
        **_extra: Extra keyword arguments from the orchestration layer.
            Silently ignored.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``platform``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry (max 2, backoff ≤ 900s).
        ArenaCollectionError: Marks the task as FAILED.
        NoCredentialAvailableError: Marks the task as FAILED immediately.
    """
    from issue_observatory.arenas.base import Tier

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()
    _arena_label = "facebook_comments"

    try:
        logger.info(
            "facebook: collect_comments started — run=%s tier=%s posts=%d",
            collection_run_id,
            tier,
            len(post_ids),
        )
        _update_task_status(collection_run_id, _arena_label, "running")
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena=_ARENA,
            platform=_arena_label,
            status="running",
            records_collected=0,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        from issue_observatory.workers._task_helpers import (
            make_batch_sink,
            persist_collected_records,
        )

        credential_pool = CredentialPool()
        collector = FacebookCollector(credential_pool=credential_pool)
        tier_enum = Tier(tier)

        sink = make_batch_sink(collection_run_id, query_design_id)
        collector.configure_batch_persistence(
            sink=sink, batch_size=100, collection_run_id=collection_run_id
        )

        records = asyncio.run(
            collector.collect_comments(
                post_ids=post_ids,
                tier=tier_enum,
                max_comments_per_post=max_comments_per_post,
                depth=depth,
            )
        )

        inserted, skipped = 0, 0
        if records:
            inserted, skipped = persist_collected_records(
                records, collection_run_id, query_design_id
            )

        logger.info(
            "facebook: collect_comments completed — run=%s inserted=%d skipped=%d",
            collection_run_id,
            inserted,
            skipped,
        )
        _update_task_status(
            collection_run_id, _arena_label, "completed", records_collected=inserted
        )
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena=_ARENA,
            platform=_arena_label,
            status="completed",
            records_collected=inserted,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )
        return {
            "records_collected": inserted,
            "status": "completed",
            "arena": _ARENA,
            "platform": _arena_label,
            "tier": tier,
        }
    except NoCredentialAvailableError as exc:
        msg = f"facebook: no credential available for comments tier={tier}: {exc}"
        logger.error(msg)
        _update_task_status(
            collection_run_id, _arena_label, "failed", error_message=msg
        )
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena=_ARENA,
            platform=_arena_label,
            status="failed",
            records_collected=0,
            error_message=msg,
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise ArenaCollectionError(msg, arena=_ARENA, platform=_arena_label) from exc
    except ArenaRateLimitError:
        logger.warning(
            "facebook: rate limited on collect_comments for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except Exception as exc:
        msg = (
            f"facebook: collect_comments unexpected error for run={collection_run_id}: "
            f"{type(exc).__name__}: {exc}"
        )
        logger.error(msg, exc_info=True)
        _update_task_status(
            collection_run_id, _arena_label, "failed", error_message=msg[:500]
        )
        publish_task_update(
            redis_url=_settings.redis_url,
            run_id=collection_run_id,
            arena=_ARENA,
            platform=_arena_label,
            status="failed",
            records_collected=0,
            error_message=msg[:500],
            elapsed_seconds=elapsed_since(_task_start),
        )
        raise


@celery_app.task(
    name="issue_observatory.arenas.facebook.tasks.health_check",
    bind=False,
)
def facebook_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the Facebook arena.

    Delegates to :meth:`FacebookCollector.health_check`, which performs a
    lightweight request to the Bright Data API to verify token validity.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail`` and ``tier_tested``.
    """
    credential_pool = CredentialPool()
    collector = FacebookCollector(credential_pool=credential_pool)
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info("facebook: health_check status=%s", result.get("status", "unknown"))
    return result
