"""Celery tasks for the Instagram arena.

Wraps :class:`InstagramCollector` methods as Celery tasks with retry logic,
collection run status tracking, and error reporting.

**Actor-only arena**: Instagram does not support keyword or hashtag-based collection
via the Bright Data Web Scraper API. The ``instagram_collect_terms`` task immediately
fails with a descriptive :exc:`~issue_observatory.core.exceptions.ArenaCollectionError`
explaining that actor-based collection must be used instead.

Task naming::

    issue_observatory.arenas.instagram.tasks.<action>

Retry policy:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff.
  Maximum 2 retries (Bright Data dataset delivery is expensive — minimize
  duplicate requests). Backoff capped at 900 seconds (15 minutes).
- ``NoCredentialAvailableError`` immediately marks the task as FAILED.

Time limits:
- No fixed time limit. Records persist incrementally via the batch sink and
  stale_run_cleanup handles any stuck tasks.

All task arguments are JSON-serializable.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

from issue_observatory.arenas.instagram.collector import InstagramCollector
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
_PLATFORM: str = "instagram"

_TERM_COLLECTION_NOT_SUPPORTED: str = (
    "Instagram does not support keyword-based or hashtag-based collection. "
    "The Bright Data Web Scraper API only supports actor-based collection "
    "(Instagram profile URLs). "
    "To collect from Instagram: add profiles to the Actor Directory "
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
            "instagram: failed to update collection_tasks to '%s': %s",
            status,
            exc,
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.instagram.tasks.collect_by_terms",
    bind=True,
    max_retries=0,
    acks_late=True,
    # No fixed time limit — records persist incrementally and stale_run_cleanup handles stuck tasks.
)
def instagram_collect_terms(
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
    """Immediately fail — Instagram does not support keyword-based collection.

    Facebook and Instagram are actor-only arenas. The Bright Data Web Scraper API
    does not support keyword or hashtag-based discovery. This task exists to provide
    a clear error message if it is mistakenly dispatched, rather than silently doing
    nothing.

    To collect from Instagram, add Instagram profiles to the Actor Directory and
    use the ``instagram_collect_actors`` task instead.

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
        ArenaCollectionError: Always — Instagram does not support keyword search.
    """
    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    logger.error(
        "instagram: collect_by_terms called but Instagram does not support keyword search. "
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
        platform="instagram",
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
    name="issue_observatory.arenas.instagram.tasks.collect_by_actors",
    bind=True,
    max_retries=2,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=900,
    acks_late=True,
    # No fixed time limit — records persist incrementally and stale_run_cleanup handles stuck tasks.
)
def instagram_collect_actors(
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
    """Collect Instagram posts from specific profiles.

    Wraps :meth:`InstagramCollector.collect_by_actors` as a Celery task.
    Actor IDs should be Instagram usernames (with or without ``@``) or full
    profile URLs (e.g. ``https://www.instagram.com/drnyheder``). Uses the
    Reels scraper which covers all content types (posts and reels).

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: Instagram usernames or profile URLs.
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
            "instagram: collect_by_actors started — run=%s tier=%s actors=%d",
            collection_run_id,
            tier,
            len(actor_ids),
        )
        _update_task_status(collection_run_id, _PLATFORM, "running")
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="social_media",
            platform="instagram",
            status="running",
            records_collected=0,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        from issue_observatory.workers._task_helpers import make_batch_sink

        credential_pool = CredentialPool()
        tier_enum = Tier(tier)
        sink = make_batch_sink(
            collection_run_id, query_design_id, actor_sourced=True,
        )

        # Normalize URLs before coverage check so keys match BD's format.
        from issue_observatory.arenas.instagram.collector import (
            _normalize_profile_url,
        )
        from issue_observatory.workers._task_helpers import (
            RunCancelledError,
            check_run_cancelled,
            clear_url_errors,
            count_run_platform_records,
            get_latest_actor_coverage_date,
            get_suppressed_urls,
            record_collection_attempts_batch,
            record_url_errors,
        )

        normalized_actor_ids = [_normalize_profile_url(aid) for aid in actor_ids]

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
                "instagram: suppressed %d/%d dead/errored URLs for run=%s",
                len(suppressed),
                original_count,
                collection_run_id,
            )
            if not normalized_actor_ids:
                logger.info(
                    "instagram: ALL URLs suppressed — completing with 0 records for run=%s",
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
        # Per-actor parallel collection loop (single event loop, 6-way)
        # ---------------------------------------------------------------
        _MAX_CONCURRENT_ACTORS = 6

        async def _run_per_actor_loop() -> tuple[int, list[str]]:
            """Collect actors with bounded parallelism within one event loop.

            Each actor gets its own collector instance (isolated batch_stats).
            A semaphore limits concurrency to ``_MAX_CONCURRENT_ACTORS``.

            Returns (total_inserted, actor_errors).
            """
            _total = 0
            _errors: list[str] = []
            _cancel = asyncio.Event()
            _sem = asyncio.Semaphore(_MAX_CONCURRENT_ACTORS)
            _total_actors = len(normalized_actor_ids)

            async def _collect_one(
                actor_idx: int, actor_url: str
            ) -> tuple[int, str | None]:
                """Collect a single actor. Returns (inserted, error_or_None)."""
                nonlocal _total
                async with _sem:
                    actor_label = actor_url.split("/")[-2] or actor_url

                    # 1. Check for cancellation.
                    if _cancel.is_set():
                        return 0, None
                    try:
                        check_run_cancelled(collection_run_id)
                    except RunCancelledError:
                        logger.info(
                            "instagram: run cancelled — signalling stop "
                            "(actor %d/%d).",
                            actor_idx,
                            _total_actors,
                        )
                        _cancel.set()
                        return 0, None

                    # 2. Per-actor coverage check (sync DB).
                    #    - latest > user end date  → skip (beyond requested range)
                    #    - latest <= user end date → re-collect from latest
                    #      (last day may be partial) through user end date
                    #    - no prior coverage       → full date range
                    effective_date_from = date_from
                    effective_date_to = date_to
                    if not force_recollect and date_from and date_to:
                        from datetime import date as _date

                        user_end = (
                            _date.fromisoformat(str(date_to)[:10])
                            if isinstance(date_to, str)
                            else date_to.date()
                            if hasattr(date_to, "date")
                            else date_to
                        )
                        latest = get_latest_actor_coverage_date(
                            _PLATFORM, actor_url
                        )
                        if latest is not None and latest > user_end:
                            logger.info(
                                "instagram: [%d/%d] %s — skipped "
                                "(covered through %s)",
                                actor_idx,
                                _total_actors,
                                actor_label,
                                latest,
                            )
                            return 0, None
                        if latest is not None:
                            # Re-collect from the last covered day (partial)
                            effective_date_from = latest.isoformat()

                    # 3. Create a dedicated collector for this actor.
                    actor_collector = InstagramCollector(
                        credential_pool=credential_pool
                    )
                    actor_collector.configure_batch_persistence(
                        sink=sink, batch_size=100,
                        collection_run_id=collection_run_id,
                    )

                    logger.info(
                        "instagram: [%d/%d] %s — collecting with dates=%s..%s "
                        "max_results=%s tier=%s",
                        actor_idx,
                        _total_actors,
                        actor_label,
                        effective_date_from,
                        effective_date_to,
                        max_results,
                        tier,
                    )
                    try:
                        await actor_collector.collect_by_actors(
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
                            "instagram: [%d/%d] %s — error: %s",
                            actor_idx,
                            _total_actors,
                            actor_label,
                            exc,
                        )
                        return 0, f"{actor_label}: {exc}"

                    # 4. Read stats from this actor's own collector.
                    stats = actor_collector.batch_stats
                    actor_count = stats["inserted"]
                    logger.info(
                        "instagram: [%d/%d] %s — batch_stats=%s "
                        "bd_errors=%d",
                        actor_idx,
                        _total_actors,
                        actor_label,
                        stats,
                        len(actor_collector.brightdata_errors),
                    )
                    _total += actor_count

                    # 5. Record per-actor coverage (sync DB).
                    if date_from and date_to:
                        record_collection_attempts_batch(
                            platform=_PLATFORM,
                            collection_run_id=collection_run_id,
                            query_design_id=query_design_id,
                            inputs=[actor_url],
                            input_type="actor",
                            date_from=effective_date_from,
                            date_to=effective_date_to,
                            records_returned=actor_count,
                            per_input_counts={actor_url: actor_count},
                        )

                    # 6. Track BD errors / clear recovered URLs.
                    bd_errors = actor_collector.brightdata_errors
                    actor_bd_errors = [
                        e for e in bd_errors if e.get("url") == actor_url
                    ]
                    if actor_bd_errors:
                        record_url_errors(_PLATFORM, actor_bd_errors)
                    else:
                        clear_url_errors(_PLATFORM, [actor_url])

                    # 7. SSE progress update.
                    logger.info(
                        "instagram: [%d/%d] %s — %d records",
                        actor_idx,
                        _total_actors,
                        actor_label,
                        actor_count,
                    )
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
                    return actor_count, None

            # Launch all actors; semaphore gates concurrency to 6.
            tasks = [
                _collect_one(idx, url)
                for idx, url in enumerate(normalized_actor_ids, 1)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Aggregate results — re-raise fatal exceptions.
            for r in results:
                if isinstance(
                    r,
                    NoCredentialAvailableError
                    | ArenaRateLimitError
                    | NotImplementedError
                    | ArenaAuthError,
                ):
                    raise r
                if isinstance(r, Exception):
                    _errors.append(str(r))
                    continue
                if isinstance(r, tuple):
                    _count, _err = r
                    if _err:
                        _errors.append(_err)

            return _total, _errors

        try:
            total_inserted, actor_errors = asyncio.run(_run_per_actor_loop())
        except NoCredentialAvailableError as exc:
            msg = f"instagram: no credential available for tier={tier}: {exc}"
            logger.error(msg)
            _update_task_status(
                collection_run_id, _PLATFORM, "failed", error_message=msg
            )
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="social_media",
                platform="instagram",
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
                "instagram: rate limited — will retry for run=%s.",
                collection_run_id,
            )
            raise
        except NotImplementedError:
            raise
        except ArenaAuthError as exc:
            msg = f"instagram: auth error for run={collection_run_id}: {exc}"
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
            db_count = count_run_platform_records(collection_run_id, "instagram")
            if db_count > 0:
                logger.info(
                    "instagram: per-actor counter=0 but DB has %d records — using DB count",
                    db_count,
                )
                total_inserted = db_count

        # Link existing records from other runs to this run so that
        # analysis includes previously collected content without
        # re-fetching from Bright Data.
        # Instagram stores a numeric owner_id as author_platform_id,
        # which doesn't match the profile URLs in actor_ids.  Extract
        # usernames and match via author_display_name instead.
        # Instagram post URLs (/p/ID, /reel/ID) don't contain the
        # username, so URL-prefix matching is not applicable here.
        from issue_observatory.workers._task_helpers import (
            reindex_existing_records,
        )

        usernames = [
            url.rstrip("/").split("/")[-1]
            for url in normalized_actor_ids
            if url.rstrip("/").split("/")[-1]
        ]
        linked = reindex_existing_records(
            platform=_PLATFORM,
            collection_run_id=collection_run_id,
            query_design_id=query_design_id,
            author_names=usernames,
            source_url_prefixes=None,
            require_term_match=True,
            date_from=date_from,
            date_to=date_to,
        )
        if linked:
            logger.info(
                "instagram: reindexed %d existing records for run=%s",
                linked,
                collection_run_id,
            )

        error_summary = (
            f" ({len(actor_errors)} actor errors)" if actor_errors else ""
        )
        logger.info(
            "instagram: collect_by_actors completed — run=%s inserted=%d linked=%d%s",
            collection_run_id,
            total_inserted,
            linked,
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
        msg = (
            f"instagram: unexpected error for run={collection_run_id}: "
            f"{type(exc).__name__}: {exc}"
        )
        logger.error(msg, exc_info=True)

        # Salvage: per-actor persistence means most records are already saved.
        salvaged_count = 0
        try:
            salvaged_count = count_run_platform_records(collection_run_id, "instagram")
        except Exception:
            logger.warning("instagram: failed to count salvaged records", exc_info=True)

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
    name="issue_observatory.arenas.instagram.tasks.collect_comments",
    bind=True,
    max_retries=2,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=900,
    acks_late=True,
)
def instagram_collect_comments(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    post_ids: list[dict],
    tier: str = "medium",
    max_comments_per_post: int = 200,
    depth: int = 0,
    **_extra: Any,
) -> dict[str, Any]:
    """Collect comments for Instagram posts via Bright Data.

    Wraps :meth:`InstagramCollector.collect_comments` as a Celery task.
    Each entry in *post_ids* must be a dict with a ``url`` key pointing to
    an Instagram post URL. Comments are collected in a single Bright Data
    trigger/poll/download cycle.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        post_ids: List of dicts with ``url`` key (Instagram post URLs).
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
    _arena_label = "instagram_comments"

    try:
        logger.info(
            "instagram: collect_comments started — run=%s tier=%s posts=%d",
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
            record_collection_attempts_batch,
        )

        credential_pool = CredentialPool()
        collector = InstagramCollector(credential_pool=credential_pool)
        tier_enum = Tier(tier)

        sink = make_batch_sink(
            collection_run_id, query_design_id, actor_sourced=True,
        )
        collector.configure_batch_persistence(
            sink=sink, batch_size=100, collection_run_id=collection_run_id
        )

        remaining = asyncio.run(
            collector.collect_comments(
                post_ids=post_ids,
                tier=tier_enum,
                max_comments_per_post=max_comments_per_post,
                depth=depth,
            )
        )

        # Most records already persisted incrementally via the batch sink.
        # Persist any remaining un-flushed records as a fallback.
        fallback_inserted, fallback_skipped = 0, 0
        if remaining:
            fallback_inserted, fallback_skipped = persist_collected_records(
                remaining, collection_run_id, query_design_id
            )
        inserted = collector.batch_stats["inserted"] + fallback_inserted
        skipped = collector.batch_stats["skipped"] + fallback_skipped

        # Record comment collection attempts so posts aren't re-submitted
        # on the next run (even if they returned 0 comments).
        from datetime import UTC, datetime

        _now_iso = datetime.now(UTC).isoformat()
        submitted_urls = [entry["url"] for entry in post_ids if entry.get("url")]
        if submitted_urls:
            record_collection_attempts_batch(
                platform=f"{_PLATFORM}_comments",
                collection_run_id=collection_run_id,
                query_design_id=query_design_id,
                inputs=submitted_urls,
                input_type="post_url",
                date_from=_now_iso,
                date_to=_now_iso,
                records_returned=inserted,
            )

        logger.info(
            "instagram: collect_comments completed — run=%s inserted=%d skipped=%d",
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
        msg = f"instagram: no credential available for comments tier={tier}: {exc}"
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
            "instagram: rate limited on collect_comments for run=%s — will retry.",
            collection_run_id,
        )
        raise
    except Exception as exc:
        msg = (
            f"instagram: collect_comments unexpected error for run={collection_run_id}: "
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
    name="issue_observatory.arenas.instagram.tasks.health_check",
    bind=False,
)
def instagram_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the Instagram arena.

    Delegates to :meth:`InstagramCollector.health_check`, which performs a
    lightweight request to the Bright Data API to verify token validity.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``detail`` and ``tier_tested``.
    """
    credential_pool = CredentialPool()
    collector = InstagramCollector(credential_pool=credential_pool)
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info("instagram: health_check status=%s", result.get("status", "unknown"))
    return result
