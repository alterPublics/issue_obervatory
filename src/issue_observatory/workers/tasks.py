"""Celery orchestration tasks for Issue Observatory.

Defines the five periodic maintenance and collection orchestration tasks that
are driven by the Celery Beat schedule in ``workers/beat_schedule.py``:

- ``trigger_daily_collection`` — dispatches arena collection tasks for every
  live-tracking query design that has sufficient credits.
- ``health_check_all_arenas`` — pings all registered arenas and caches results
  in Redis for the admin health UI.
- ``settle_pending_credits`` — converts pending credit reservations into
  settled transactions once their collection run has completed.
- ``cleanup_stale_runs`` — marks collection runs stuck in non-terminal states
  for more than 24 hours as failed.
- ``enforce_retention_policy`` — deletes content records older than the
  configured GDPR retention window.

All tasks are synchronous Celery tasks that bridge to async DB operations via
``asyncio.run()``.  Async DB helpers live in ``workers._task_helpers`` to
keep this file under 400 lines.

Error handling policy: each task catches all exceptions at the outermost
level, logs them at ERROR level, and does NOT re-raise.  This prevents a
single task failure from triggering a retry storm for orchestration tasks.
``trigger_daily_collection`` is the sole exception: it retries up to three
times on transient DB errors (``max_retries=3, countdown=60``).

Task names must match the references in ``workers/beat_schedule.py``::

    issue_observatory.workers.tasks.trigger_daily_collection
    issue_observatory.workers.tasks.health_check_all_arenas
    issue_observatory.workers.tasks.settle_pending_credits
    issue_observatory.workers.tasks.cleanup_stale_runs
    issue_observatory.workers.tasks.enforce_retention_policy
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import redis
import structlog
from celery.exceptions import Retry

from issue_observatory.config.settings import get_settings
from issue_observatory.core.email_service import get_email_service
from issue_observatory.core.schemas.query_design import parse_language_codes
from issue_observatory.workers._enrichment_helpers import (
    fetch_content_records_for_run,
    write_enrichment,
)
from issue_observatory.workers._task_helpers import (
    check_all_tasks_terminal,
    create_collection_tasks,
    enforce_retention,
    fetch_actor_ids_for_design_and_platform,
    fetch_actor_ids_for_project_and_platform,
    fetch_batch_run_details,
    fetch_designs_with_prep,
    fetch_posts_for_comment_collection,
    fetch_project_comments_config,
    fetch_public_figure_ids_for_design,
    fetch_public_figure_ids_for_project,
    fetch_resolved_terms_for_arena,
    fetch_stale_runs,
    fetch_unsettled_reservations,
    filter_new_actors,
    filter_new_terms,
    mark_runs_failed,
    mark_task_failed,
    read_source_list_from_arenas_config,
    set_run_status,
    settle_single_reservation,
    suspend_run,
)
from issue_observatory.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)
_stdlib_logger = logging.getLogger(__name__)

settings = get_settings()
email_service = get_email_service()


# ---------------------------------------------------------------------------
# Task 1: trigger_daily_collection
# ---------------------------------------------------------------------------


_INDEXING_LAG_HOURS: dict[str, int] = {
    # TikTok Research API: nominal 48-hour indexing lag, but empirically
    # observed at 8-10 days (March 2026).  240 hours = 10 days.
    "tiktok": 240,
}


def _compute_live_date_bounds(
    last_collected_by_platform: dict[str, datetime],
    arena_name: str,
) -> tuple[str, str]:
    """Compute date_from/date_to ISO strings for a live collection dispatch.

    Uses the most recent collected_at timestamp for the arena's platform to
    avoid re-fetching already-collected content.  Falls back to 24 hours ago
    when no prior data exists.

    For platforms with a known indexing lag (e.g. TikTok's 48-hour delay),
    ``date_from`` is extended further back so that content published before
    the lag window but only recently indexed is still captured.  ``date_to``
    remains at now so that anything indexed earlier than the maximum lag is
    not missed.

    Args:
        last_collected_by_platform: Mapping of platform name to last collected datetime.
        arena_name: The platform name being dispatched.

    Returns:
        Tuple of (date_from_iso, date_to_iso).
    """
    lag_hours = _INDEXING_LAG_HOURS.get(arena_name, 0)
    now = datetime.now(UTC)

    last_collected = last_collected_by_platform.get(arena_name)
    if last_collected is not None:
        date_from_dt = last_collected - timedelta(hours=lag_hours)
    else:
        date_from_dt = now - timedelta(days=1) - timedelta(hours=lag_hours)

    return date_from_dt.isoformat(), now.isoformat()


@celery_app.task(
    name="issue_observatory.workers.tasks.trigger_daily_collection",
    bind=True,
    max_retries=3,
)
def trigger_daily_collection(self: Any) -> dict[str, Any]:
    """Dispatch arena collection tasks for all active live-tracking query designs.

    For each active live-tracking query design:

    1. Checks the initiating user's credit balance via ``CreditService``.
    2. If the balance is zero or negative: sends a low-credit warning email,
       suspends the run (``status='suspended'``), and skips dispatch.
    3. Otherwise, dispatches a ``collect_by_terms`` Celery task for each
       arena listed in the design's ``arenas_config``.

    Retries up to three times (60-second countdown) on transient DB errors.

    Returns:
        Dict with ``designs_processed``, ``dispatched``, and ``skipped``.
    """
    _task_start = time.perf_counter()
    log = logger.bind(task="trigger_daily_collection")
    log.info("trigger_daily_collection: starting")

    # Single asyncio.run() for ALL async DB queries.  Multiple asyncio.run()
    # calls cause "Future attached to a different loop" errors because the
    # SQLAlchemy async connection pool ties connections to the first event loop.
    try:
        designs = asyncio.run(fetch_designs_with_prep())
    except Exception as exc:
        log.error(
            "trigger_daily_collection: DB error fetching designs",
            error=str(exc),
            exc_info=True,
        )
        try:
            raise self.retry(countdown=60, exc=exc)
        except Retry:
            raise
        except Exception:
            return {"error": str(exc), "dispatched": 0, "skipped": 0}

    dispatched = 0
    skipped = 0

    for design in designs:
        design_id = design["query_design_id"]
        run_id = design["run_id"]
        default_tier: str = design.get("default_tier") or "free"
        raw_arenas_config: dict = design.get("arenas_config") or {}
        arenas_config: dict[str, str] = design.get("_flat_arenas") or {}

        # GR-05: arenas_config["languages"] takes priority over the single
        # query_design.language field.
        config_languages = raw_arenas_config.get("languages") if isinstance(raw_arenas_config, dict) else None
        if isinstance(config_languages, list) and config_languages:
            language_filter: list[str] = [str(lc) for lc in config_languages if lc]
        else:
            raw_language: str = design.get("language") or "da"
            language_filter = parse_language_codes(raw_language)

        task_log = log.bind(
            query_design_id=str(design_id), run_id=str(run_id)
        )
        task_log.info("trigger_daily_collection: processing design")

        balance = design.get("credit_balance", 0)
        public_figure_ids: list[str] = design.get("public_figure_ids", [])

        # --- Credit gate ---
        if balance <= 0:
            task_log.warning(
                "trigger_daily_collection: insufficient credits; suspending run",
                balance=balance,
            )
            user_email = design.get("user_email")
            if user_email:
                try:
                    asyncio.run(
                        email_service.send_low_credit_warning(
                            user_email=user_email,
                            remaining_credits=balance,
                            threshold=settings.low_credit_warning_threshold,
                        )
                    )
                except Exception as email_exc:
                    task_log.warning(
                        "trigger_daily_collection: low-credit email failed",
                        error=str(email_exc),
                    )
            try:
                asyncio.run(suspend_run(run_id))
            except Exception as suspend_exc:
                task_log.error(
                    "trigger_daily_collection: failed to suspend run",
                    error=str(suspend_exc),
                )
            skipped += 1
            continue

        if not arenas_config:
            task_log.warning(
                "trigger_daily_collection: no arenas configured; skipping design"
            )
            skipped += 1
            continue

        if public_figure_ids:
            task_log.info(
                "trigger_daily_collection: GR-14 public-figure IDs loaded",
                count=len(public_figure_ids),
            )

        # --- Dispatch arena tasks ---
        from issue_observatory.arenas.registry import (
            get_arena as _get_arena,
        )
        from issue_observatory.arenas.registry import (
            get_task_module as _gtm,
        )

        for arena_name, arena_tier in arenas_config.items():
            tier = arena_tier or default_tier

            try:
                _collector_cls = _get_arena(arena_name)
                _is_actor_only = not getattr(_collector_cls, "supports_term_search", True)
            except KeyError:
                _is_actor_only = False

            try:
                _task_module = _gtm(arena_name)
            except KeyError:
                _task_module = f"issue_observatory.arenas.{arena_name}.tasks"

            if _is_actor_only:
                actor_ids = design.get("arena_actor_ids", {}).get(arena_name, [])
                if not actor_ids:
                    task_log.warning(
                        "trigger_daily_collection: actor-only arena has no actors configured; skipping",
                        arena=arena_name,
                    )
                    skipped += 1
                    continue

                _task_name = f"{_task_module}.collect_by_actors"
                last_collected_map = design.get("last_collected_by_platform", {})
                date_from, date_to = _compute_live_date_bounds(last_collected_map, arena_name)
                try:
                    celery_app.send_task(
                        _task_name,
                        kwargs={
                            "query_design_id": str(design_id),
                            "collection_run_id": str(run_id),
                            "actor_ids": actor_ids,
                            "tier": tier,
                            "public_figure_ids": public_figure_ids,
                            "date_from": date_from,
                            "date_to": date_to,
                        },
                        queue="celery",
                    )
                    task_log.info(
                        "trigger_daily_collection: dispatched actor-only arena task",
                        arena=arena_name,
                        tier=tier,
                        task_name=_task_name,
                        actors_count=len(actor_ids),
                        date_from=date_from,
                        date_to=date_to,
                    )
                except Exception as dispatch_exc:
                    task_log.error(
                        "trigger_daily_collection: actor-only dispatch failed",
                        arena=arena_name,
                        error=str(dispatch_exc),
                    )
                    skipped += 1
                    continue

            else:
                arena_terms = design.get("arena_terms", {}).get(arena_name, [])
                if not arena_terms:
                    task_log.info(
                        "trigger_daily_collection: no search terms scoped to arena; skipping",
                        arena=arena_name,
                    )
                    continue

                _task_name = f"{_task_module}.collect_by_terms"
                last_collected_map = design.get("last_collected_by_platform", {})
                date_from, date_to = _compute_live_date_bounds(last_collected_map, arena_name)
                try:
                    celery_app.send_task(
                        _task_name,
                        kwargs={
                            "query_design_id": str(design_id),
                            "collection_run_id": str(run_id),
                            "terms": arena_terms,
                            "tier": tier,
                            "language_filter": language_filter,
                            "public_figure_ids": public_figure_ids,
                            "date_from": date_from,
                            "date_to": date_to,
                        },
                        queue="celery",
                    )
                    task_log.info(
                        "trigger_daily_collection: dispatched arena task",
                        arena=arena_name,
                        tier=tier,
                        task_name=_task_name,
                        terms_count=len(arena_terms),
                        date_from=date_from,
                        date_to=date_to,
                    )
                except Exception as dispatch_exc:
                    task_log.error(
                        "trigger_daily_collection: dispatch failed",
                        arena=arena_name,
                        error=str(dispatch_exc),
                    )

                # Also dispatch collect_by_actors for dual-mode arenas with a
                # source list (e.g. Telegram custom_channels).
                try:
                    _config_key = getattr(_collector_cls, "source_list_config_key", None)
                except (KeyError, AttributeError):
                    _config_key = None

                if _config_key and getattr(_collector_cls, "supports_actor_collection", False):
                    _source_list = read_source_list_from_arenas_config(
                        raw_arenas_config, arena_name, _config_key
                    )
                    if _source_list:
                        _chunk_size = getattr(
                            _collector_cls, "source_list_daily_chunk_size", None
                        )
                        if _chunk_size and len(_source_list) > _chunk_size:
                            _source_list = _apply_daily_chunking(
                                _source_list, _chunk_size, task_log, arena_name
                            )

                        _actors_task = f"{_task_module}.collect_by_actors"
                        try:
                            celery_app.send_task(
                                _actors_task,
                                kwargs={
                                    "query_design_id": str(design_id),
                                    "collection_run_id": str(run_id),
                                    "actor_ids": _source_list,
                                    "tier": tier,
                                    "public_figure_ids": public_figure_ids,
                                    "date_from": date_from,
                                    "date_to": date_to,
                                },
                                queue="celery",
                            )
                            task_log.info(
                                "trigger_daily_collection: dispatched dual-mode actor task",
                                arena=arena_name,
                                tier=tier,
                                task_name=_actors_task,
                                actors_count=len(_source_list),
                                date_from=date_from,
                                date_to=date_to,
                            )
                        except Exception as actor_dispatch_exc:
                            task_log.error(
                                "trigger_daily_collection: dual-mode actor dispatch failed",
                                arena=arena_name,
                                error=str(actor_dispatch_exc),
                            )

        dispatched += 1

    summary = {
        "designs_processed": len(designs),
        "dispatched": dispatched,
        "skipped": skipped,
    }
    log.info("trigger_daily_collection: complete", **summary)
    try:
        from issue_observatory.api.metrics import (
            celery_task_duration_seconds,
            celery_tasks_total,
        )
        celery_tasks_total.labels(
            task_name="trigger_daily_collection", status="success"
        ).inc()
        celery_task_duration_seconds.labels(
            task_name="trigger_daily_collection"
        ).observe(time.perf_counter() - _task_start)
    except Exception as _metrics_exc:
        _stdlib_logger.debug(
            "trigger_daily_collection: metrics recording failed: %s", _metrics_exc
        )
    return summary


# ---------------------------------------------------------------------------
# Task 2: health_check_all_arenas
# ---------------------------------------------------------------------------


@celery_app.task(name="issue_observatory.workers.tasks.health_check_all_arenas")
def health_check_all_arenas() -> dict[str, Any]:
    """Dispatch health-check tasks for all registered arenas and cache results.

    For each arena in the registry, dispatches the arena-specific Celery
    health-check task and writes a status entry to Redis under the key
    ``arena:health:{arena_name}`` with a 360-second TTL.

    Health-check task names follow the convention::

        {arena_package}.tasks.{arena_name}_health_check

    where ``arena_package`` is derived from the collector class's
    ``__module__`` attribute by dropping the trailing ``.collector`` segment.

    Returns:
        Dict with ``arenas_checked`` count and list of arena names dispatched.
    """
    from issue_observatory.arenas.registry import autodiscover, list_arenas

    _task_start = time.perf_counter()
    log = logger.bind(task="health_check_all_arenas")
    log.info("health_check_all_arenas: starting")

    try:
        autodiscover()
    except Exception as exc:
        log.error(
            "health_check_all_arenas: autodiscover() failed",
            error=str(exc),
            exc_info=True,
        )
        return {"error": str(exc), "arenas_checked": 0}

    arenas = list_arenas()
    log.info("health_check_all_arenas: registry loaded", arena_count=len(arenas))

    try:
        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    except Exception as exc:
        log.error(
            "health_check_all_arenas: Redis connection failed",
            error=str(exc),
        )
        return {"error": str(exc), "arenas_checked": 0}

    checked_arenas: list[str] = []

    # m-03: Skip deferred stub arenas (Twitch and VKontakte) from automated health checks.
    # These arenas are not fully implemented and should not appear in health dashboards.
    _SKIP_ARENAS = {"twitch", "vkontakte"}

    for arena_info in arenas:
        arena_name: str = arena_info["arena_name"]
        platform_name: str = arena_info["platform_name"]
        collector_class: str = arena_info.get("collector_class", "")

        # Skip deferred stub arenas
        if platform_name in _SKIP_ARENAS:
            log.debug(
                "health_check_all_arenas: skipping deferred stub arena",
                platform=platform_name,
            )
            continue
        try:
            # collector_class = "issue_observatory.arenas.{...}.collector.ClassName"
            # Drop the class name to get the module, then drop ".collector"
            # to get the arena package.
            module_parts = collector_class.split(".")[:-1]  # drop class name
            arena_package = ".".join(module_parts[:-1])     # drop ".collector"
            # Task naming convention: {arena_package}.tasks.health_check
            # All arena health_check tasks are registered with the same name "health_check"
            # (not platform_name-prefixed) in each arena's tasks module.
            task_name = f"{arena_package}.tasks.health_check"
        except Exception:
            task_name = (
                f"issue_observatory.arenas.{platform_name}"
                f".tasks.health_check"
            )

        try:
            celery_app.send_task(task_name, queue="celery")
            redis_client.setex(f"arena:health:{platform_name}", 360, "dispatched")
            log.info(
                "health_check_all_arenas: dispatched",
                arena=arena_name,
                platform=platform_name,
                task_name=task_name,
            )
            checked_arenas.append(platform_name)
        except Exception as exc:
            log.error(
                "health_check_all_arenas: dispatch failed",
                arena=arena_name,
                platform=platform_name,
                error=str(exc),
            )
            try:
                redis_client.setex(
                    f"arena:health:{platform_name}", 360, f"dispatch_error: {exc}"
                )
            except Exception:
                pass

    summary = {"arenas_checked": len(checked_arenas), "arenas": checked_arenas}
    log.info("health_check_all_arenas: complete", **summary)
    try:
        from issue_observatory.api.metrics import (
            celery_task_duration_seconds,
            celery_tasks_total,
        )
        celery_tasks_total.labels(
            task_name="health_check_all_arenas", status="success"
        ).inc()
        celery_task_duration_seconds.labels(
            task_name="health_check_all_arenas"
        ).observe(time.perf_counter() - _task_start)
    except Exception as _metrics_exc:
        _stdlib_logger.debug(
            "health_check_all_arenas: metrics recording failed: %s", _metrics_exc
        )
    return summary


# ---------------------------------------------------------------------------
# Task 3: settle_pending_credits
# ---------------------------------------------------------------------------


@celery_app.task(name="issue_observatory.workers.tasks.settle_pending_credits")
def settle_pending_credits() -> dict[str, Any]:
    """Settle pending credit reservations for completed collection runs.

    Finds all ``'reservation'`` transactions whose associated run has a
    ``completed_at`` timestamp but no matching ``'settlement'`` transaction
    for the same (run, arena, platform) tuple, then writes settlements via
    :class:`~issue_observatory.core.credit_service.CreditService`.

    After settling, sends one ``send_collection_complete`` notification email
    per run (de-duplicated by run ID).

    Returns:
        Dict with ``settled_count`` and ``error_count``.
    """
    _task_start = time.perf_counter()
    log = logger.bind(task="settle_pending_credits")
    log.info("settle_pending_credits: starting")

    try:
        pending = asyncio.run(fetch_unsettled_reservations())
    except Exception as exc:
        log.error(
            "settle_pending_credits: DB error",
            error=str(exc),
            exc_info=True,
        )
        return {"error": str(exc), "settled_count": 0, "error_count": 0}

    log.info("settle_pending_credits: found pending", count=len(pending))

    settled_count = 0
    error_count = 0
    emailed_runs: set[str] = set()  # avoid duplicate completion emails per run
    spike_checked_runs: set[str] = set()  # avoid duplicate spike checks per run

    for row in pending:
        run_id_str = str(row["collection_run_id"])
        try:
            asyncio.run(settle_single_reservation(row))
            log.info(
                "settle_pending_credits: settled",
                txn_id=str(row["txn_id"]),
                run_id=run_id_str,
                arena=row["arena"],
                platform=row["platform"],
                credits=row["reserved_credits"],
            )
            settled_count += 1

            if run_id_str not in emailed_runs:
                user_email: str | None = row.get("user_email")
                if user_email:
                    try:
                        asyncio.run(
                            email_service.send_collection_complete(
                                user_email=user_email,
                                run_id=row["collection_run_id"],
                                records_collected=row.get("records_collected") or 0,
                            )
                        )
                        emailed_runs.add(run_id_str)
                    except Exception as email_exc:
                        log.warning(
                            "settle_pending_credits: completion email failed",
                            run_id=run_id_str,
                            error=str(email_exc),
                        )

            # GR-09: dispatch spike check once per completed run, but only
            # when the run is associated with a query design (batch/live runs
            # spawned by trigger_daily_collection always have one; ad-hoc runs
            # created via the API may not).
            if run_id_str not in spike_checked_runs:
                query_design_id = row.get("query_design_id")
                if query_design_id is not None:
                    try:
                        celery_app.send_task(
                            "issue_observatory.workers.tasks.check_volume_spikes",
                            kwargs={
                                "collection_run_id": run_id_str,
                                "query_design_id": str(query_design_id),
                            },
                            queue="celery",
                        )
                        spike_checked_runs.add(run_id_str)
                        log.info(
                            "settle_pending_credits: dispatched spike check",
                            run_id=run_id_str,
                            query_design_id=str(query_design_id),
                        )
                    except Exception as spike_exc:
                        log.warning(
                            "settle_pending_credits: spike check dispatch failed",
                            run_id=run_id_str,
                            error=str(spike_exc),
                        )

        except Exception as exc:
            log.error(
                "settle_pending_credits: settlement failed",
                txn_id=str(row.get("txn_id")),
                run_id=run_id_str,
                error=str(exc),
                exc_info=True,
            )
            error_count += 1

    summary = {"settled_count": settled_count, "error_count": error_count}
    log.info("settle_pending_credits: complete", **summary)
    try:
        from issue_observatory.api.metrics import (
            celery_task_duration_seconds,
            celery_tasks_total,
        )
        celery_tasks_total.labels(
            task_name="settle_pending_credits", status="success"
        ).inc()
        celery_task_duration_seconds.labels(
            task_name="settle_pending_credits"
        ).observe(time.perf_counter() - _task_start)
    except Exception as _metrics_exc:
        _stdlib_logger.debug(
            "settle_pending_credits: metrics recording failed: %s", _metrics_exc
        )
    return summary


# ---------------------------------------------------------------------------
# Task 4: cleanup_stale_runs
# ---------------------------------------------------------------------------


@celery_app.task(name="issue_observatory.workers.tasks.cleanup_stale_runs")
def cleanup_stale_runs() -> dict[str, Any]:
    """Mark collection runs stuck in non-terminal states for > 24 hours as failed.

    Targets ``CollectionRun`` rows with ``status`` in ``('pending', 'running')``
    where ``started_at`` is more than 24 hours in the past (or NULL for
    pending runs).  Also marks any non-terminal ``CollectionTask`` rows for
    those runs as failed.

    Returns:
        Dict with ``runs_failed`` count.
    """
    _task_start = time.perf_counter()
    log = logger.bind(task="cleanup_stale_runs")
    log.info("cleanup_stale_runs: starting")

    try:
        stale = asyncio.run(fetch_stale_runs())
    except Exception as exc:
        log.error(
            "cleanup_stale_runs: DB error fetching stale runs",
            error=str(exc),
            exc_info=True,
        )
        return {"error": str(exc), "runs_failed": 0}

    if not stale:
        log.info("cleanup_stale_runs: no stale runs found")
        return {"runs_failed": 0}

    run_ids = [row["id"] for row in stale]
    log.info("cleanup_stale_runs: marking runs failed", count=len(run_ids))

    try:
        runs_failed = asyncio.run(mark_runs_failed(run_ids))
    except Exception as exc:
        log.error(
            "cleanup_stale_runs: DB error marking runs failed",
            error=str(exc),
            exc_info=True,
        )
        return {"error": str(exc), "runs_failed": 0}

    summary = {"runs_failed": runs_failed}
    log.info("cleanup_stale_runs: complete", **summary)
    try:
        from issue_observatory.api.metrics import (
            celery_task_duration_seconds,
            celery_tasks_total,
        )
        celery_tasks_total.labels(
            task_name="cleanup_stale_runs", status="success"
        ).inc()
        celery_task_duration_seconds.labels(
            task_name="cleanup_stale_runs"
        ).observe(time.perf_counter() - _task_start)
    except Exception as _metrics_exc:
        _stdlib_logger.debug(
            "cleanup_stale_runs: metrics recording failed: %s", _metrics_exc
        )
    return summary


# ---------------------------------------------------------------------------
# Task 5: enforce_retention_policy
# ---------------------------------------------------------------------------


@celery_app.task(name="issue_observatory.workers.tasks.enforce_retention_policy")
def enforce_retention_policy() -> dict[str, Any]:
    """Delete content records that exceed the configured GDPR retention window.

    Delegates to :meth:`~issue_observatory.core.retention_service.RetentionService.enforce_retention`
    using ``settings.data_retention_days`` (default: 730 days / 2 years) as
    defined in :class:`~issue_observatory.config.settings.Settings`.

    Returns:
        Dict with ``records_deleted`` count and the ``retention_days`` value used.
    """
    _task_start = time.perf_counter()
    log = logger.bind(task="enforce_retention_policy")
    retention_days = settings.data_retention_days
    log.info("enforce_retention_policy: starting", retention_days=retention_days)

    try:
        deleted = asyncio.run(enforce_retention(retention_days))
    except Exception as exc:
        log.error(
            "enforce_retention_policy: error",
            error=str(exc),
            exc_info=True,
        )
        return {
            "error": str(exc),
            "records_deleted": 0,
            "retention_days": retention_days,
        }

    summary = {"records_deleted": deleted, "retention_days": retention_days}
    log.info("enforce_retention_policy: complete", **summary)
    try:
        from issue_observatory.api.metrics import (
            celery_task_duration_seconds,
            celery_tasks_total,
        )
        celery_tasks_total.labels(
            task_name="enforce_retention_policy", status="success"
        ).inc()
        celery_task_duration_seconds.labels(
            task_name="enforce_retention_policy"
        ).observe(time.perf_counter() - _task_start)
    except Exception as _metrics_exc:
        _stdlib_logger.debug(
            "enforce_retention_policy: metrics recording failed: %s", _metrics_exc
        )
    return summary


# ---------------------------------------------------------------------------
# Task 6: reconcile_collection_attempts
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.workers.tasks.reconcile_collection_attempts",
    bind=False,
)
def reconcile_collection_attempts_task() -> dict[str, Any]:
    """Validate collection_attempts against actual content_records data.

    For each valid attempt older than 14 days with ``records_returned > 0``,
    checks whether at least one matching content record still exists.  If not
    (e.g. due to manual deletion or retention policy enforcement), marks the
    attempt as ``is_valid = FALSE`` so the coverage checker stops trusting it
    and future collection runs can re-fetch the data.

    Recent attempts (< 14 days) are skipped to avoid invalidating current
    coverage for terms that simply returned zero results from the API.

    Runs weekly via Celery Beat (Sunday 05:00 Copenhagen time).

    Returns:
        Dict with ``attempts_checked`` and ``attempts_invalidated`` counts.
    """
    _task_start = time.perf_counter()
    log = logger.bind(task="reconcile_collection_attempts")
    log.info("reconcile_collection_attempts: starting")

    from issue_observatory.workers._task_helpers import (
        reconcile_collection_attempts,
    )

    result = reconcile_collection_attempts()

    log.info(
        "reconcile_collection_attempts: complete",
        attempts_checked=result["attempts_checked"],
        attempts_invalidated=result["attempts_invalidated"],
    )
    try:
        from issue_observatory.api.metrics import (
            celery_task_duration_seconds,
            celery_tasks_total,
        )
        celery_tasks_total.labels(
            task_name="reconcile_collection_attempts", status="success"
        ).inc()
        celery_task_duration_seconds.labels(
            task_name="reconcile_collection_attempts"
        ).observe(time.perf_counter() - _task_start)
    except Exception as _metrics_exc:
        _stdlib_logger.debug(
            "reconcile_collection_attempts: metrics recording failed: %s",
            _metrics_exc,
        )
    return result


# ---------------------------------------------------------------------------
# Task 7: enrich_collection_run
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.workers.tasks.enrich_collection_run",
    bind=True,
    max_retries=3,
)
def enrich_collection_run(
    self: Any,
    run_id: str,
    enricher_names: list[str] | None = None,
    language_codes: list[str] | None = None,
) -> dict[str, Any]:
    """Run content enrichment on all records from a collection run.

    Fetches content records in batches of 100, applies each registered
    enricher whose ``is_applicable()`` returns True, and writes results
    into ``raw_metadata.enrichments.{enricher_name}`` via ``jsonb_set``.

    Enrichers are imported lazily from
    :mod:`issue_observatory.analysis.enrichments` to avoid circular imports
    at module load time.

    Args:
        run_id: UUID string of the CollectionRun whose records to enrich.
        enricher_names: Optional list of enricher names to run.  If None,
            all registered enrichers are applied.  Pass a list to restrict
            to a subset (e.g. ``["language_detection"]``).
        language_codes: Optional list of ISO 639-1 language codes from the
            query design's language configuration (e.g. ``["da"]`` for a
            Danish-only collection).  When provided, the language detector
            will tag records as ``expected`` or ``unexpected`` and will use
            a single-language heuristic fallback when langdetect is not
            installed.

    Returns:
        Dict with ``records_processed``, ``enrichments_applied``, and
        ``error_count``.
    """
    _task_start = time.perf_counter()
    log = logger.bind(task="enrich_collection_run", run_id=run_id)
    log.info(
        "enrich_collection_run: starting",
        enricher_names=enricher_names,
        language_codes=language_codes,
    )

    # --- Build enricher registry ---
    from issue_observatory.analysis.enrichments import (
        LanguageDetector,
    )

    _all_enrichers: list[Any] = [
        LanguageDetector(expected_languages=language_codes),
    ]

    if enricher_names is not None:
        enrichers = [e for e in _all_enrichers if e.enricher_name in enricher_names]
        unknown = set(enricher_names) - {e.enricher_name for e in enrichers}
        if unknown:
            log.warning(
                "enrich_collection_run: unknown enricher names ignored",
                unknown=sorted(unknown),
            )
    else:
        enrichers = _all_enrichers

    if not enrichers:
        log.warning("enrich_collection_run: no enrichers to run; exiting")
        return {"records_processed": 0, "enrichments_applied": 0, "error_count": 0}

    log.info(
        "enrich_collection_run: enrichers loaded",
        enrichers=[e.enricher_name for e in enrichers],
    )

    # --- Process records in batches ---
    records_processed = 0
    enrichments_applied = 0
    error_count = 0
    offset = 0

    while True:
        try:
            batch = fetch_content_records_for_run(run_id, offset=offset)
        except Exception as exc:
            log.error(
                "enrich_collection_run: DB error fetching batch",
                offset=offset,
                error=str(exc),
                exc_info=True,
            )
            try:
                raise self.retry(countdown=60, exc=exc)
            except Exception:
                return {
                    "records_processed": records_processed,
                    "enrichments_applied": enrichments_applied,
                    "error_count": error_count + 1,
                }

        if not batch:
            break  # all records consumed

        log.debug(
            "enrich_collection_run: processing batch",
            offset=offset,
            batch_size=len(batch),
        )

        for record in batch:
            record_id = record.get("id")
            for enricher in enrichers:
                if not enricher.is_applicable(record):
                    continue
                try:
                    result = asyncio.run(enricher.enrich(record))
                    write_enrichment(record_id, enricher.enricher_name, result)
                    enrichments_applied += 1
                    log.debug(
                        "enrich_collection_run: enrichment written",
                        record_id=str(record_id),
                        enricher=enricher.enricher_name,
                    )
                except Exception as exc:
                    log.error(
                        "enrich_collection_run: enrichment failed",
                        record_id=str(record_id),
                        enricher=enricher.enricher_name,
                        error=str(exc),
                        exc_info=True,
                    )
                    error_count += 1

            records_processed += 1

        offset += len(batch)
        if len(batch) < 100:
            break  # last partial batch; no more rows

    # -----------------------------------------------------------------------
    # SB-03: Post-Collection Discovery Notification
    #
    # After enrichment completes, compute and emit discovery stats (suggested
    # terms count, discovered links count) to the event bus so the collection
    # detail page can display them.
    # -----------------------------------------------------------------------
    discovery_summary: dict[str, int] = {}
    try:
        from issue_observatory.workers._task_helpers import (
            get_discovery_summary,
        )

        discovery_summary = asyncio.run(get_discovery_summary(run_id))
        if discovery_summary:
            # Emit via event bus for SSE consumers
            try:
                import json

                import redis as redis_lib

                payload = {
                    "event": "discovery_summary",
                    "suggested_terms": discovery_summary.get("suggested_terms", 0),
                    "discovered_links": discovery_summary.get("discovered_links", 0),
                    "telegram_links": discovery_summary.get("telegram_links", 0),
                }
                channel = f"collection:{run_id}"
                r = redis_lib.from_url(settings.redis_url, decode_responses=True)
                try:
                    r.publish(channel, json.dumps(payload))
                    log.info(
                        "enrich_collection_run: discovery summary emitted", **discovery_summary
                    )
                finally:
                    r.close()
            except Exception as event_exc:
                log.warning(
                    "enrich_collection_run: event bus emission failed",
                    error=str(event_exc),
                )
    except Exception as disco_exc:
        log.warning(
            "enrich_collection_run: discovery summary computation failed",
            error=str(disco_exc),
            exc_info=True,
        )

    summary = {
        "records_processed": records_processed,
        "enrichments_applied": enrichments_applied,
        "error_count": error_count,
        "discovery": discovery_summary,
    }
    log.info("enrich_collection_run: complete", **summary)
    try:
        from issue_observatory.api.metrics import (
            celery_task_duration_seconds,
            celery_tasks_total,
        )
        celery_tasks_total.labels(
            task_name="enrich_collection_run", status="success"
        ).inc()
        celery_task_duration_seconds.labels(
            task_name="enrich_collection_run"
        ).observe(time.perf_counter() - _task_start)
    except Exception as _metrics_exc:
        _stdlib_logger.debug(
            "enrich_collection_run: metrics recording failed: %s", _metrics_exc
        )
    return summary


# ---------------------------------------------------------------------------
# Task 7: check_volume_spikes  (GR-09)
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.workers.tasks.check_volume_spikes",
)
def check_volume_spikes_task(
    collection_run_id: str,
    query_design_id: str,
    threshold_multiplier: float = 2.0,
) -> dict[str, Any]:
    """Check for volume spikes after a collection run completes.

    Runs as a fire-and-forget task dispatched by arena collection tasks
    (or by the collection orchestration layer) upon run completion.  The
    spike check is intentionally isolated here so that any failure does not
    block or affect the collection run itself.

    Algorithm (delegated to
    :func:`~issue_observatory.workers._alerting_helpers.run_spike_detection`):

    1. Compute per-arena record counts for the completed run.
    2. Compute the rolling 7-run average per arena from the prior 7 completed
       runs for the same query design.
    3. Flag arenas where current count > ``threshold_multiplier`` x rolling
       average AND current count >= 10 (to avoid false positives at low volume).
    4. Persist flagged spikes to ``collection_runs.arenas_config["_volume_spikes"]``.
    5. Send an email alert to the query design owner.

    Silently returns ``{"spikes": []}`` when there is insufficient run history
    (fewer than 7 prior completed runs), so no special handling is required
    in the caller.

    Args:
        collection_run_id: UUID string of the completed collection run.
        query_design_id: UUID string of the associated query design.
        threshold_multiplier: Ratio above which a volume increase is flagged.
            Defaults to 2.0 (double the rolling average).

    Returns:
        Dict with key ``"spikes"`` containing a list of spike dicts, and
        ``"spike_count"`` for fast summary logging.
    """
    import uuid as _uuid

    _task_start = time.perf_counter()
    log = logger.bind(
        task="check_volume_spikes",
        collection_run_id=collection_run_id,
        query_design_id=query_design_id,
    )
    log.info("check_volume_spikes: starting")

    from issue_observatory.workers._alerting_helpers import (
        run_spike_detection,
    )

    try:
        run_uuid = _uuid.UUID(collection_run_id)
        design_uuid = _uuid.UUID(query_design_id)
    except ValueError as exc:
        log.error(
            "check_volume_spikes: invalid UUID arguments",
            error=str(exc),
        )
        return {"spikes": [], "spike_count": 0, "error": str(exc)}

    try:
        spikes = asyncio.run(
            run_spike_detection(
                collection_run_id=run_uuid,
                query_design_id=design_uuid,
                threshold_multiplier=threshold_multiplier,
            )
        )
    except Exception as exc:
        log.error(
            "check_volume_spikes: detection failed",
            error=str(exc),
            exc_info=True,
        )
        return {"spikes": [], "spike_count": 0, "error": str(exc)}

    summary: dict[str, Any] = {"spikes": spikes, "spike_count": len(spikes)}
    log.info("check_volume_spikes: complete", spike_count=len(spikes))
    try:
        from issue_observatory.api.metrics import (
            celery_task_duration_seconds,
            celery_tasks_total,
        )
        celery_tasks_total.labels(
            task_name="check_volume_spikes", status="success"
        ).inc()
        celery_task_duration_seconds.labels(
            task_name="check_volume_spikes"
        ).observe(time.perf_counter() - _task_start)
    except Exception as _metrics_exc:
        _stdlib_logger.debug(
            "check_volume_spikes: metrics recording failed: %s", _metrics_exc
        )
    return summary


# ---------------------------------------------------------------------------
# Task 8: dispatch_batch_collection (B-1 fix)
# ---------------------------------------------------------------------------


def _apply_daily_chunking(
    source_list: list[str],
    chunk_size: int,
    log: Any,
    platform_name: str,
) -> list[str]:
    """Split a source list into daily rotating chunks.

    Uses ``date.today().toordinal() % num_chunks`` so that a different
    chunk is dispatched each calendar day, achieving full coverage over
    ``ceil(len(source_list) / chunk_size)`` days.
    """
    import math
    from datetime import date

    total = len(source_list)
    if total <= chunk_size:
        return source_list

    num_chunks = math.ceil(total / chunk_size)
    chunk_idx = date.today().toordinal() % num_chunks
    start = chunk_idx * chunk_size
    end = min(start + chunk_size, total)
    chunk = source_list[start:end]
    log.info(
        "dispatch_batch_collection: chunking source list",
        arena=platform_name,
        chunk=f"{chunk_idx + 1}/{num_chunks}",
        actors_in_chunk=len(chunk),
        total_actors=total,
    )
    return chunk


async def _dispatch_batch_async(
    run_uuid: Any,
    run_id: str,
    log: Any,
) -> dict[str, Any]:
    """Inner async function that performs all DB operations in one event loop.

    This consolidates all async DB calls into a single asyncio.run() to avoid
    event loop corruption from multiple asyncio.run() invocations in the same
    Celery task (Bug 1 fix).

    Args:
        run_uuid: Parsed UUID of the CollectionRun.
        run_id: String representation of the run UUID.
        log: Structlog logger bound to task context.

    Returns:
        Dict with keys:
        - details: Run and design details from DB, or None if not found
        - public_figure_ids: List of public figure platform IDs
        - arena_terms_map: Dict[platform_name, list[str]] of search terms
        - arenas_config: Normalized dict[platform_name, tier]
        - language_filter: List of language codes
        - arena_entries: List of dicts for create_collection_tasks
        - no_arenas_dispatched: bool flag for completion handling
    """
    from issue_observatory.arenas.registry import (
        autodiscover,
        get_arena,
        list_arenas,
    )

    # --- Step 1: Load run details ---
    details = await fetch_batch_run_details(run_uuid)
    if details is None:
        return {"details": None, "no_arenas_dispatched": True}

    design_id = details["query_design_id"]
    project_id = details.get("project_id")
    raw_arenas_config: dict = details.get("arenas_config") or {}
    default_tier: str = details.get("default_tier") or "free"
    date_from = details.get("date_from")
    date_to = details.get("date_to")

    # --- Step 2: Sync operations (arenas_config normalization) ---
    # Autodiscover happens in sync context but can run inside async function
    autodiscover()

    # Normalize arenas_config to flat dict: {"platform_name": "tier", ...}
    arenas_config: dict[str, str] = {}

    if "arenas" in raw_arenas_config and isinstance(raw_arenas_config["arenas"], list):
        # Nested list format from the query design editor
        for entry in raw_arenas_config["arenas"]:
            if isinstance(entry, dict) and entry.get("enabled", True):
                platform_id = entry.get("id") or entry.get("platform_name")
                tier = entry.get("tier", default_tier)
                if platform_id:
                    arenas_config[platform_id] = tier
    else:
        # Already flat, or has non-arena metadata keys.
        # Copy platform entries, skip internal keys.
        for key, value in raw_arenas_config.items():
            if key.startswith("_") or key == "languages":
                continue
            # Value might be a tier string or a dict of settings
            if isinstance(value, str):
                arenas_config[key] = value
            elif isinstance(value, dict) and "tier" in value:
                arenas_config[key] = value["tier"]
            # Skip non-arena config entries (rss custom_feeds, etc.)

    # Fallback: if no arenas were configured AND no explicit empty list was
    # provided, dispatch ALL registered arenas.  An explicit empty list
    # ({"arenas": []}) means the project intentionally has all arenas disabled
    # (e.g. comment-only collection run).
    has_explicit_arenas_list = (
        "arenas" in raw_arenas_config
        and isinstance(raw_arenas_config["arenas"], list)
    )
    if not arenas_config and not has_explicit_arenas_list:
        for arena_info in list_arenas():
            arenas_config[arena_info["platform_name"]] = default_tier
        log.info(
            "dispatch_batch_collection: no arena config; falling back to all %d arenas",
            len(arenas_config),
        )

    # Apply per-run arena exclusions from the launcher form.
    exclude_list = raw_arenas_config.get("_exclude_arenas")
    if isinstance(exclude_list, list) and exclude_list:
        before = len(arenas_config)
        for arena_id in exclude_list:
            arenas_config.pop(arena_id, None)
        log.info(
            "dispatch_batch_collection: excluded %d arenas per launcher request",
            before - len(arenas_config),
        )

    # "Only collect new" flag — skip terms/actors that already have records.
    only_collect_new = bool(raw_arenas_config.get("_only_collect_new"))
    if only_collect_new:
        log.info("dispatch_batch_collection: only_collect_new mode enabled")

    # Extract language config from the original raw config (not the normalized one)
    config_languages = raw_arenas_config.get("languages") if isinstance(raw_arenas_config, dict) else None
    if isinstance(config_languages, list) and config_languages:
        language_filter: list[str] = [str(lc) for lc in config_languages if lc]
    else:
        raw_language: str = details.get("language") or "da"
        language_filter = parse_language_codes(raw_language)

    # --- Step 3: Set run to running ---
    await set_run_status(run_uuid, "running", started_at=True)

    # --- Step 4: GR-14: load public-figure IDs ---
    try:
        if project_id:
            pf_set = await fetch_public_figure_ids_for_project(project_id)
        else:
            pf_set = await fetch_public_figure_ids_for_design(design_id)
        public_figure_ids = list(pf_set)
        if public_figure_ids:
            log.info(
                "dispatch_batch_collection: GR-14 public-figure IDs loaded",
                count=len(public_figure_ids),
            )
    except Exception as pf_exc:
        log.warning(
            "dispatch_batch_collection: failed to fetch public-figure IDs",
            error=str(pf_exc),
        )
        public_figure_ids = []

    # --- Step 5: Filter arenas to those actually registered ---
    # Also record whether each arena supports term-based or actor-only collection,
    # and capture source_list_config_key for the new unified source list dispatch.
    arena_entries: list[dict[str, str]] = []
    # Maps platform_name -> True if the arena is actor-only (supports_term_search=False).
    actor_only_arenas: set[str] = set()
    # Maps platform_name -> source_list_config_key (None if the arena has no source list).
    arena_source_list_keys: dict[str, str | None] = {}
    skipped = 0

    for platform_name in arenas_config:
        # Verify the arena is registered
        try:
            collector_cls = get_arena(platform_name)
        except KeyError:
            log.warning(
                "dispatch_batch_collection: arena not registered; skipping",
                arena=platform_name,
            )
            skipped += 1
            continue

        arena_entries.append({
            "arena_name": platform_name,
            "platform_name": platform_name,
        })

        # Detect actor-only arenas (e.g. Facebook, Instagram).
        if not getattr(collector_cls, "supports_term_search", True):
            actor_only_arenas.add(platform_name)
            log.debug(
                "dispatch_batch_collection: actor-only arena detected",
                arena=platform_name,
            )

        # Capture the source_list_config_key so the dispatch loop can read
        # the researcher-curated source list from arenas_config JSONB.
        arena_source_list_keys[platform_name] = getattr(
            collector_cls, "source_list_config_key", None
        )

    # --- Step 6: Create CollectionTask rows ---
    if arena_entries:
        await create_collection_tasks(run_uuid, arena_entries)
        log.info(
            "dispatch_batch_collection: created CollectionTask rows",
            count=len(arena_entries),
        )

    # --- Step 7: Fetch search terms and/or actor IDs for each arena ---
    #
    # New dispatch logic (actor workflow redesign):
    #
    # For actor-only arenas (supports_term_search=False):
    #   1. Read source list from arenas_config[platform][config_key] (NEW path)
    #   2. Merge with legacy ActorList chain (backward-compatible fallback)
    #   3. Deduplicate; fail the task if no actor IDs remain
    #
    # For dual-mode arenas (supports_term_search=True):
    #   1. Always fetch search terms and dispatch collect_by_terms (existing behaviour)
    #   2. Additionally, if a source list is configured in arenas_config, populate
    #      arena_actors_map so the sync dispatch loop also fires collect_by_actors
    #
    # arena_actors_map stores actor lists for BOTH actor-only arenas and dual-mode
    # arenas that have a configured source list.  The sync dispatch loop checks
    # arena_actors_map independently of arena_terms_map so both can fire.
    arena_terms_map: dict[str, list[str]] = {}
    arena_actors_map: dict[str, list[str]] = {}

    for entry in arena_entries:
        platform_name = entry["platform_name"]
        config_key = arena_source_list_keys.get(platform_name)

        if platform_name in actor_only_arenas:
            # Actor-only arena: merge source list with legacy ActorList chain.
            # Source list takes priority; legacy chain provides backward compatibility.
            source_list: list[str] = []
            if config_key:
                source_list = read_source_list_from_arenas_config(
                    raw_arenas_config, platform_name, config_key
                )
                if source_list:
                    log.debug(
                        "dispatch_batch_collection: source list read from arenas_config",
                        arena=platform_name,
                        config_key=config_key,
                        count=len(source_list),
                    )

            # Fetch legacy ActorList-based IDs as fallback / supplement.
            try:
                if project_id:
                    legacy_actor_ids = await fetch_actor_ids_for_project_and_platform(
                        project_id, platform_name
                    )
                else:
                    legacy_actor_ids = await fetch_actor_ids_for_design_and_platform(
                        design_id, platform_name
                    )
            except Exception as actors_exc:
                log.error(
                    "dispatch_batch_collection: failed to fetch legacy actor IDs for actor-only arena",
                    arena=platform_name,
                    error=str(actors_exc),
                )
                legacy_actor_ids = []

            # Deduplicate: source list items come first (they are the primary input),
            # followed by legacy items not already present in the source list.
            seen: set[str] = set(source_list)
            merged_actor_ids = list(source_list)
            for legacy_id in legacy_actor_ids:
                if legacy_id not in seen:
                    seen.add(legacy_id)
                    merged_actor_ids.append(legacy_id)

            # Filter out actors already present in the previous run (only_collect_new).
            if only_collect_new and merged_actor_ids:
                merged_actor_ids = await filter_new_actors(
                    str(design_id), platform_name, merged_actor_ids, config_key
                )
                log.info(
                    "only_collect_new: filtered actor-only actors",
                    arena=platform_name,
                    remaining=len(merged_actor_ids),
                )

            # Apply daily chunking if the collector defines a chunk size.
            collector_cls = get_arena(platform_name)
            chunk_size = getattr(collector_cls, "source_list_daily_chunk_size", None)
            if chunk_size and len(merged_actor_ids) > chunk_size:
                merged_actor_ids = _apply_daily_chunking(
                    merged_actor_ids, chunk_size, log, platform_name
                )

            arena_actors_map[platform_name] = merged_actor_ids

            if not merged_actor_ids:
                log.warning(
                    "dispatch_batch_collection: actor-only arena has no actors configured; "
                    "marking task as failed",
                    arena=platform_name,
                )
                try:
                    await mark_task_failed(
                        run_uuid,
                        platform_name,
                        f"No actors configured for actor-only platform '{platform_name}'. "
                        "Add page/profile URLs to the arena source list in the query "
                        "design editor, or add actors via the Actor Directory.",
                    )
                except Exception as mark_exc:
                    log.warning(
                        "dispatch_batch_collection: failed to mark task as failed",
                        arena=platform_name,
                        error=str(mark_exc),
                    )

        else:
            # Dual-mode arena: always fetch search terms for collect_by_terms.
            terms_fetch_error: Exception | None = None
            try:
                arena_terms = await fetch_resolved_terms_for_arena(design_id, platform_name)
                # Filter out terms that already have records (only_collect_new).
                if only_collect_new and arena_terms:
                    arena_terms = await filter_new_terms(
                        str(design_id), platform_name, arena_terms
                    )
                    log.info(
                        "only_collect_new: filtered terms",
                        arena=platform_name,
                        remaining=len(arena_terms),
                    )
                arena_terms_map[platform_name] = arena_terms
            except Exception as terms_exc:
                log.error(
                    "dispatch_batch_collection: failed to fetch search terms",
                    arena=platform_name,
                    error=str(terms_exc),
                )
                arena_terms_map[platform_name] = []
                terms_fetch_error = terms_exc

            # Also check for a researcher-curated source list.  When present,
            # the sync dispatch loop will fire collect_by_actors alongside
            # collect_by_terms so both modes run in the same collection pass.
            if config_key:
                dual_mode_source_list = read_source_list_from_arenas_config(
                    raw_arenas_config, platform_name, config_key
                )
                # Filter out actors already present in the previous run (only_collect_new).
                if only_collect_new and dual_mode_source_list:
                    dual_mode_source_list = await filter_new_actors(
                        str(design_id), platform_name, dual_mode_source_list, config_key
                    )
                    log.info(
                        "only_collect_new: filtered dual-mode actors",
                        arena=platform_name,
                        remaining=len(dual_mode_source_list),
                    )
                if dual_mode_source_list:
                    # Apply daily chunking if the collector defines a chunk size.
                    collector_cls = get_arena(platform_name)
                    chunk_size = getattr(
                        collector_cls, "source_list_daily_chunk_size", None
                    )
                    if chunk_size and len(dual_mode_source_list) > chunk_size:
                        dual_mode_source_list = _apply_daily_chunking(
                            dual_mode_source_list, chunk_size, log, platform_name
                        )

                    arena_actors_map[platform_name] = dual_mode_source_list
                    log.debug(
                        "dispatch_batch_collection: dual-mode arena has source list; "
                        "will also dispatch collect_by_actors",
                        arena=platform_name,
                        config_key=config_key,
                        count=len(dual_mode_source_list),
                    )

            # Only mark as failed when NEITHER terms NOR a source list exist.
            # If a source list is present the actor dispatch will proceed even
            # without search terms, so the CollectionTask must not be put into
            # a terminal "failed" state prematurely (M-1 fix).
            arena_terms = arena_terms_map.get(platform_name, [])
            has_source_list = bool(arena_actors_map.get(platform_name))
            if not arena_terms and not has_source_list:
                if terms_fetch_error is not None:
                    failure_reason = f"Failed to fetch search terms: {terms_fetch_error}"
                else:
                    failure_reason = "No search terms scoped to this arena (YF-01)"
                log.info(
                    "dispatch_batch_collection: no search terms and no source list for arena; "
                    "marking failed",
                    arena=platform_name,
                )
                try:
                    await mark_task_failed(
                        run_uuid,
                        platform_name,
                        failure_reason,
                    )
                except Exception as mark_exc:
                    log.warning(
                        "dispatch_batch_collection: failed to mark task as failed",
                        arena=platform_name,
                        error=str(mark_exc),
                    )

    # --- Step 8: Handle no-arenas case ---
    # An arena is dispatchable if it has terms (term-based) OR actor IDs (actor-only
    # or dual-mode with a source list).
    has_any_dispatchable = any(
        (
            (pn in actor_only_arenas and bool(arena_actors_map.get(pn)))
            or (pn not in actor_only_arenas and bool(arena_terms_map.get(pn)))
            or bool(arena_actors_map.get(pn))  # dual-mode with source list
        )
        for pn in (e["platform_name"] for e in arena_entries)
    )
    no_arenas_dispatched = False
    if not arena_entries or not has_any_dispatchable:
        # No arenas have anything to dispatch — mark run as completed with 0 records
        log.warning("dispatch_batch_collection: no arenas to dispatch; completing run")
        await set_run_status(run_uuid, "completed", completed_at=True)
        no_arenas_dispatched = True

    return {
        "details": details,
        "public_figure_ids": public_figure_ids,
        "arena_terms_map": arena_terms_map,
        "arena_actors_map": arena_actors_map,
        "actor_only_arenas": actor_only_arenas,
        "arenas_config": arenas_config,
        "language_filter": language_filter,
        "arena_entries": arena_entries,
        "no_arenas_dispatched": no_arenas_dispatched,
        "skipped": skipped,
        "date_from": date_from,
        "date_to": date_to,
        "default_tier": default_tier,
    }


@celery_app.task(
    name="issue_observatory.workers.tasks.dispatch_batch_collection",
    bind=True,
    max_retries=2,
)
def dispatch_batch_collection(self: Any, run_id: str) -> dict[str, Any]:
    """Dispatch per-arena collection tasks for a batch collection run.

    This is the missing orchestration layer that bridges the gap between
    ``create_collection_run`` (which creates the DB record) and the
    per-arena Celery tasks (which do the actual data collection).

    Steps:
    1. Load the CollectionRun and its QueryDesign from the database.
    2. Set the run status to ``'running'`` with ``started_at``.
    3. Autodiscover all registered arenas.
    4. For each arena in ``arenas_config``, filter search terms (YF-01),
       create a ``CollectionTask`` row, and dispatch the arena task.
    5. Schedule ``check_batch_completion`` to monitor completion.

    Args:
        run_id: UUID string of the CollectionRun to dispatch.

    Returns:
        Dict with ``dispatched``, ``skipped``, and ``arenas`` lists.
    """
    import uuid as _uuid

    _task_start = time.perf_counter()
    log = logger.bind(task="dispatch_batch_collection", run_id=run_id)
    log.info("dispatch_batch_collection: starting")

    # --- Single asyncio.run() call to avoid event loop corruption (Bug 1 fix) ---
    try:
        run_uuid = _uuid.UUID(run_id)
        async_result = asyncio.run(_dispatch_batch_async(run_uuid, run_id, log))
    except Exception as exc:
        log.error(
            "dispatch_batch_collection: async operations failed",
            error=str(exc),
            exc_info=True,
        )
        try:
            raise self.retry(countdown=30, exc=exc)
        except Retry:
            raise
        except Exception:
            return {"error": str(exc), "dispatched": 0}

    # Check if run was not found
    if async_result["details"] is None:
        log.error("dispatch_batch_collection: run not found", run_id=run_id)
        return {"error": "Run not found", "dispatched": 0}

    # Unpack async results
    public_figure_ids = async_result["public_figure_ids"]
    arena_terms_map = async_result["arena_terms_map"]
    arena_actors_map: dict[str, list[str]] = async_result["arena_actors_map"]
    actor_only_arenas: set[str] = async_result["actor_only_arenas"]
    arenas_config = async_result["arenas_config"]
    language_filter = async_result["language_filter"]
    arena_entries = async_result["arena_entries"]
    no_arenas_dispatched = async_result["no_arenas_dispatched"]
    skipped = async_result["skipped"]
    date_from = async_result["date_from"]
    date_to = async_result["date_to"]
    default_tier = async_result["default_tier"]

    # Import registry helpers for task name resolution
    from issue_observatory.arenas.registry import get_task_module

    # --- Dispatch per-arena tasks (sync Celery calls) ---
    dispatched_arenas: list[str] = []
    # Track tasks that need their celery_task_id updated in the DB
    task_id_updates: list[tuple[str, str]] = []  # (platform_name, celery_task_id)

    for entry in arena_entries:
        platform_name = entry["platform_name"]
        tier = arenas_config.get(platform_name) or default_tier

        # Derive the task module from the collector's actual module path so
        # that nested arenas (e.g. web.common_crawl) resolve correctly.
        try:
            task_module = get_task_module(platform_name)
        except KeyError:
            task_module = f"issue_observatory.arenas.{platform_name}.tasks"

        if platform_name in actor_only_arenas:
            # Actor-only arena: dispatch collect_by_actors instead of collect_by_terms.
            actor_ids = arena_actors_map.get(platform_name, [])
            if not actor_ids:
                # Already marked as failed in the async block above.
                log.debug(
                    "dispatch_batch_collection: skipping actor-only arena with no actors",
                    arena=platform_name,
                )
                continue

            task_name = f"{task_module}.collect_by_actors"
            task_kwargs: dict[str, Any] = {
                "query_design_id": str(async_result["details"]["query_design_id"]),
                "collection_run_id": run_id,
                "actor_ids": actor_ids,
                "tier": tier,
                "public_figure_ids": public_figure_ids,
            }
            if date_from:
                task_kwargs["date_from"] = (
                    date_from.isoformat() if hasattr(date_from, "isoformat") else str(date_from)
                )
            if date_to:
                task_kwargs["date_to"] = (
                    date_to.isoformat() if hasattr(date_to, "isoformat") else str(date_to)
                )

            try:
                async_task = celery_app.send_task(
                    task_name,
                    kwargs=task_kwargs,
                    queue="celery",
                )
                dispatched_arenas.append(platform_name)
                task_id_updates.append((platform_name, async_task.id))
                log.info(
                    "dispatch_batch_collection: dispatched actor-only arena task",
                    arena=platform_name,
                    tier=tier,
                    actors_count=len(actor_ids),
                    task_name=task_name,
                    celery_task_id=async_task.id,
                )
            except Exception as dispatch_exc:
                log.error(
                    "dispatch_batch_collection: actor-only dispatch failed",
                    arena=platform_name,
                    error=str(dispatch_exc),
                )
                try:
                    async def _mark_failed_actors(
                        _run_uuid: Any = run_uuid,
                        _pn: str = platform_name,
                        _exc: Exception = dispatch_exc,
                    ) -> None:
                        await mark_task_failed(
                            _run_uuid, _pn, f"Celery dispatch failed: {_exc}"
                        )
                    asyncio.run(_mark_failed_actors())
                except Exception as mark_exc:
                    log.warning(
                        "dispatch_batch_collection: failed to mark actor-only task as failed",
                        arena=platform_name,
                        error=str(mark_exc),
                    )
                skipped += 1

        else:
            # Dual-mode arena: dispatch collect_by_terms when terms are available,
            # and also dispatch collect_by_actors when a source list is configured.
            arena_terms = arena_terms_map.get(platform_name, [])
            dual_mode_actor_ids = arena_actors_map.get(platform_name, [])

            if not arena_terms and not dual_mode_actor_ids:
                # Task already marked as failed in the async block above (no terms).
                # Also no source list configured — nothing to do for this arena.
                log.debug(
                    "dispatch_batch_collection: skipping arena with no terms and no source list",
                    arena=platform_name,
                )
                continue

            # --- dispatch collect_by_terms (if terms exist) ---
            if arena_terms:
                task_name = f"{task_module}.collect_by_terms"

                # Always include language_filter and public_figure_ids since all
                # arena tasks accept **_extra.
                task_kwargs = {
                    "query_design_id": str(async_result["details"]["query_design_id"]),
                    "collection_run_id": run_id,
                    "terms": arena_terms,
                    "tier": tier,
                    "language_filter": language_filter,
                    "public_figure_ids": public_figure_ids,
                }
                if date_from:
                    task_kwargs["date_from"] = (
                        date_from.isoformat() if hasattr(date_from, "isoformat") else str(date_from)
                    )
                if date_to:
                    task_kwargs["date_to"] = (
                        date_to.isoformat() if hasattr(date_to, "isoformat") else str(date_to)
                    )

                try:
                    # Capture the AsyncResult to get the celery_task_id
                    async_task = celery_app.send_task(
                        task_name,
                        kwargs=task_kwargs,
                        queue="celery",
                    )
                    dispatched_arenas.append(platform_name)
                    task_id_updates.append((platform_name, async_task.id))
                    log.info(
                        "dispatch_batch_collection: dispatched arena task",
                        arena=platform_name,
                        tier=tier,
                        terms_count=len(arena_terms),
                        celery_task_id=async_task.id,
                    )
                except Exception as dispatch_exc:
                    log.error(
                        "dispatch_batch_collection: dispatch failed",
                        arena=platform_name,
                        error=str(dispatch_exc),
                    )
                    # Mark the task as failed in the DB - use a separate async run
                    # because we're in sync context after the main async block
                    try:
                        async def _mark_failed(
                            _run_uuid: Any = run_uuid,
                            _pn: str = platform_name,
                            _exc: Exception = dispatch_exc,
                        ) -> None:
                            await mark_task_failed(
                                _run_uuid, _pn, f"Celery dispatch failed: {_exc}"
                            )
                        asyncio.run(_mark_failed())
                    except Exception as mark_exc:
                        log.warning(
                            "dispatch_batch_collection: failed to mark task as failed",
                            arena=platform_name,
                            error=str(mark_exc),
                        )
                    skipped += 1

            # --- ALSO dispatch collect_by_actors if a source list is configured (NEW) ---
            # This runs in parallel with collect_by_terms; results are deduplicated
            # downstream by the content_hash deduplication pipeline.
            if dual_mode_actor_ids:
                actors_task_name = f"{task_module}.collect_by_actors"
                actors_task_kwargs: dict[str, Any] = {
                    "query_design_id": str(async_result["details"]["query_design_id"]),
                    "collection_run_id": run_id,
                    "actor_ids": dual_mode_actor_ids,
                    "tier": tier,
                    "public_figure_ids": public_figure_ids,
                }
                if date_from:
                    actors_task_kwargs["date_from"] = (
                        date_from.isoformat() if hasattr(date_from, "isoformat") else str(date_from)
                    )
                if date_to:
                    actors_task_kwargs["date_to"] = (
                        date_to.isoformat() if hasattr(date_to, "isoformat") else str(date_to)
                    )

                try:
                    actors_async_task = celery_app.send_task(
                        actors_task_name,
                        kwargs=actors_task_kwargs,
                        queue="celery",
                    )
                    if platform_name not in dispatched_arenas:
                        dispatched_arenas.append(platform_name)
                    # Only record the actor task's celery_task_id when no terms
                    # task was dispatched for this arena.  When both are dispatched
                    # we keep the FIRST (terms) task ID on the CollectionTask row
                    # so the ID is deterministic and not silently overwritten
                    # (m-1 fix: avoid overwriting celery_task_id with actor task ID).
                    terms_already_dispatched = any(
                        raw_key == platform_name for raw_key, _ in task_id_updates
                    )
                    if not terms_already_dispatched:
                        task_id_updates.append((platform_name, actors_async_task.id))
                    log.info(
                        "dispatch_batch_collection: dispatched dual-mode actor task",
                        arena=platform_name,
                        tier=tier,
                        actors_count=len(dual_mode_actor_ids),
                        celery_task_id=actors_async_task.id,
                    )
                except Exception as actors_dispatch_exc:
                    log.error(
                        "dispatch_batch_collection: dual-mode actor dispatch failed",
                        arena=platform_name,
                        error=str(actors_dispatch_exc),
                    )

    # --- Update CollectionTask rows with celery_task_ids ---
    if task_id_updates:
        try:
            from issue_observatory.workers._task_helpers import (
                update_task_celery_id,
            )
            # Batch all updates into a single async context.
            # Each entry is (platform_name, celery_task_id) — one entry per arena,
            # always holding the FIRST (terms) task ID when both modes are dispatched.
            async def _update_all_ids() -> None:
                for platform_name_key, celery_task_id in task_id_updates:
                    await update_task_celery_id(run_uuid, platform_name_key, celery_task_id)
            asyncio.run(_update_all_ids())
            log.info(
                "dispatch_batch_collection: updated celery_task_ids",
                count=len(task_id_updates),
            )
        except Exception as update_exc:
            log.warning(
                "dispatch_batch_collection: failed to update celery_task_ids",
                error=str(update_exc),
            )

    # --- Schedule completion checker or emit completion event ---
    if dispatched_arenas:
        check_batch_completion.apply_async(
            kwargs={"run_id": run_id},
            countdown=15,
        )
        log.info(
            "dispatch_batch_collection: scheduled completion checker",
            check_delay_seconds=15,
        )
    elif no_arenas_dispatched:
        # Already marked completed in async function; just emit the event
        from issue_observatory.core.event_bus import publish_run_complete

        publish_run_complete(
            redis_url=settings.redis_url,
            run_id=run_id,
            status="completed",
            records_collected=0,
            credits_spent=0,
        )

        # Dispatch comment collection even when no post arenas ran
        # (comment-only run collecting from previously gathered posts).
        try:
            trigger_comment_collection.delay(run_id)
            log.info("dispatch_batch_collection: comment collection triggered (no post arenas)")
        except Exception as exc:
            log.warning(
                "dispatch_batch_collection: comment trigger failed", error=str(exc),
            )

    summary = {
        "dispatched": len(dispatched_arenas),
        "skipped": skipped,
        "arenas": dispatched_arenas,
    }
    log.info("dispatch_batch_collection: complete", **summary)
    return summary


# ---------------------------------------------------------------------------
# Task 9: check_batch_completion (B-1 fix)
# ---------------------------------------------------------------------------


async def _check_batch_async(run_uuid: Any) -> dict[str, Any] | None:
    """Single async context for check_batch_completion DB operations.

    Consolidates all async DB calls into one event loop to avoid asyncpg
    connection pool corruption from multiple asyncio.run() calls.
    """
    result = await check_all_tasks_terminal(run_uuid)
    if result is None or not result["all_done"]:
        return result

    # All tasks terminal: determine final status and update DB
    if result["failed"] > 0 and result["completed"] == 0:
        final_status = "failed"
        error_msg = f"All {result['failed']} arena tasks failed."
    elif result["failed"] > 0:
        final_status = "completed"
        error_msg = f"{result['failed']} of {result['total']} arena tasks failed."
    else:
        final_status = "completed"
        error_msg = None

    await set_run_status(
        run_uuid,
        final_status,
        completed_at=True,
        error_log=error_msg,
    )

    result["final_status"] = final_status
    result["error_msg"] = error_msg
    return result


_CHECK_BATCH_MAX_ATTEMPTS: int = 480
"""Maximum number of check_batch_completion re-schedules (~2 hours at 15s intervals)."""


@celery_app.task(
    name="issue_observatory.workers.tasks.check_batch_completion",
)
def check_batch_completion(run_id: str, attempt: int = 1) -> dict[str, Any]:
    """Check whether all arena tasks for a batch run have finished.

    Polls the ``collection_tasks`` table to see if every task has reached
    a terminal state (``completed`` or ``failed``).  If not all done,
    re-schedules itself with a 15-second countdown, up to
    ``_CHECK_BATCH_MAX_ATTEMPTS`` (480 checks, ~2 hours).

    After exceeding the max attempts, forces the run to ``failed`` status
    to prevent infinite polling.

    When all tasks are terminal:
    1. Sets the run status to ``completed`` (or ``failed`` if all tasks failed).
    2. Sets ``completed_at`` on the run.
    3. Publishes a ``run_complete`` SSE event.
    4. Dispatches the enrichment pipeline.

    Args:
        run_id: UUID string of the CollectionRun to check.
        attempt: Current attempt number (1-indexed, auto-incremented).

    Returns:
        Dict with ``status``, ``total_tasks``, ``completed``, ``failed``.
    """
    import uuid as _uuid

    log = logger.bind(task="check_batch_completion", run_id=run_id, attempt=attempt)

    # Single asyncio.run() call for all DB operations
    try:
        run_uuid = _uuid.UUID(run_id)
        result = asyncio.run(_check_batch_async(run_uuid))
    except Exception as exc:
        log.error(
            "check_batch_completion: DB error — will retry",
            error=str(exc),
            exc_info=True,
        )
        # Re-schedule instead of silently returning.  DB errors (e.g.
        # connection pool exhaustion from zombie tasks) are transient;
        # giving up here leaves the run stuck as "running" forever.
        if attempt < _CHECK_BATCH_MAX_ATTEMPTS:
            check_batch_completion.apply_async(
                kwargs={"run_id": run_id, "attempt": attempt + 1},
                countdown=15,
            )
            return {"status": "db_error_retry", "error": str(exc), "attempt": attempt}
        return {"status": "db_error_max_attempts", "error": str(exc)}

    if result is None:
        log.warning("check_batch_completion: no tasks found for run")
        return {"status": "no_tasks"}

    # Log if stuck tasks were detected and marked as failed
    stuck_count = result.get("stuck_marked_failed", 0)
    if stuck_count > 0:
        log.warning(
            "check_batch_completion: marked stuck tasks as failed",
            stuck_count=stuck_count,
            run_id=run_id,
        )

    if not result["all_done"]:
        if attempt >= _CHECK_BATCH_MAX_ATTEMPTS:
            log.error(
                "check_batch_completion: max attempts reached — forcing run to failed",
                attempt=attempt,
                max_attempts=_CHECK_BATCH_MAX_ATTEMPTS,
                remaining=result["total"] - result["completed"] - result["failed"],
            )
            asyncio.run(set_run_status(
                _uuid.UUID(run_id),
                "failed",
                completed_at=True,
                error_log=(
                    f"Batch completion checker exceeded {_CHECK_BATCH_MAX_ATTEMPTS} "
                    f"attempts (~{_CHECK_BATCH_MAX_ATTEMPTS * 15 // 60} min). "
                    f"Completed: {result['completed']}/{result['total']}, "
                    f"Failed: {result['failed']}/{result['total']}."
                ),
            ))
            from issue_observatory.core.event_bus import publish_run_complete

            publish_run_complete(
                redis_url=settings.redis_url,
                run_id=run_id,
                status="failed",
                records_collected=result.get("total_records", 0),
                credits_spent=result.get("credits_spent", 0),
            )
            return {"status": "failed", "reason": "max_attempts_exceeded", **result}

        # Re-schedule to check again
        remaining = result["total"] - result["completed"] - result["failed"]
        log.debug(
            "check_batch_completion: not all done; re-scheduling",
            remaining=remaining,
            total=result["total"],
            completed=result["completed"],
            failed=result["failed"],
        )
        check_batch_completion.apply_async(
            kwargs={"run_id": run_id, "attempt": attempt + 1},
            countdown=15,
        )
        return {"status": "waiting", **result}

    # --- All tasks terminal: finalize ---
    final_status = result["final_status"]
    total_records = result["total_records"]
    credits_spent = result["credits_spent"]

    log.info(
        "check_batch_completion: all tasks terminal; finalizing run",
        final_status=final_status,
        total_records=total_records,
        completed=result["completed"],
        failed=result["failed"],
    )

    # Publish run_complete SSE event (sync Redis, no asyncio needed)
    from issue_observatory.core.event_bus import publish_run_complete

    publish_run_complete(
        redis_url=settings.redis_url,
        run_id=run_id,
        status=final_status,
        records_collected=total_records,
        credits_spent=credits_spent,
    )

    # Dispatch enrichment pipeline
    if total_records > 0 and final_status == "completed":
        try:
            enrich_collection_run.delay(run_id)
            log.info("check_batch_completion: enrichment pipeline dispatched")
        except Exception as exc:
            log.warning(
                "check_batch_completion: enrichment dispatch failed",
                error=str(exc),
            )

    # Dispatch Phase 2 comment collection if any platforms are enabled
    if final_status == "completed":
        try:
            trigger_comment_collection.delay(run_id)
            log.info("check_batch_completion: comment collection triggered")
        except Exception as exc:
            log.warning(
                "check_batch_completion: comment collection dispatch failed",
                error=str(exc),
            )

    return {
        "status": final_status,
        "total_tasks": result["total"],
        "completed": result["completed"],
        "failed": result["failed"],
        "total_records": total_records,
    }


# ---------------------------------------------------------------------------
# Task 7: trigger_comment_collection  (Phase 2 — runs after post collection)
# ---------------------------------------------------------------------------

# Map of platform name → Celery task name for comment collection
_COMMENT_TASK_MAP: dict[str, str] = {
    "reddit": "issue_observatory.arenas.reddit.tasks.collect_comments",
    "bluesky": "issue_observatory.arenas.bluesky.tasks.collect_comments",
    "youtube": "issue_observatory.arenas.youtube.tasks.collect_comments",
    "tiktok": "issue_observatory.arenas.tiktok.tasks.collect_comments",
    "facebook": "issue_observatory.arenas.facebook.tasks.collect_comments",
    "instagram": "issue_observatory.arenas.instagram.tasks.collect_comments",
}

# Default tier per platform for comment tasks
_COMMENT_DEFAULT_TIER: dict[str, str] = {
    "reddit": "free",
    "bluesky": "free",
    "youtube": "free",
    "tiktok": "free",
    "facebook": "medium",
    "instagram": "medium",
}


async def _trigger_comments_async(
    collection_run_id: str,
    log: Any,
) -> dict[str, Any]:
    """Single async context for all comment-collection DB operations.

    Consolidates every async call into one event loop to avoid the asyncpg
    ``attached to a different loop`` error that occurs when ``asyncio.run()``
    is called multiple times within one Celery task.
    """
    import uuid as _uuid

    from issue_observatory.workers._task_helpers import create_collection_tasks

    # --- 1. Fetch run details ---
    run_details = await fetch_batch_run_details(collection_run_id)
    if not run_details:
        log.warning("trigger_comment_collection: no run details found")
        return {"platforms_dispatched": 0}

    project_id = run_details.get("project_id")
    query_design_id = run_details.get("query_design_id")

    if not project_id:
        log.info("trigger_comment_collection: run has no project_id, skipping")
        return {"platforms_dispatched": 0}

    # --- 2. Fetch comments_config ---
    comments_config = await fetch_project_comments_config(str(project_id))
    if not comments_config:
        log.debug("trigger_comment_collection: no comments_config, skipping")
        return {"platforms_dispatched": 0}

    # --- 3. Per-platform: fetch posts + create task rows ---
    # Celery send_task is sync and must be called outside this async fn,
    # so collect dispatch instructions to return.
    dispatches: list[dict[str, Any]] = []

    for platform, platform_config in comments_config.items():
        if not isinstance(platform_config, dict):
            continue
        if not platform_config.get("enabled", False):
            continue
        if platform not in _COMMENT_TASK_MAP:
            log.warning(
                "trigger_comment_collection: unsupported comment platform=%s", platform
            )
            continue

        # Fetch qualifying posts
        try:
            posts = await fetch_posts_for_comment_collection(
                collection_run_id=collection_run_id,
                platform=platform,
                comments_config=platform_config,
                project_id=str(project_id),
                date_from=run_details.get("date_from"),
                date_to=run_details.get("date_to"),
            )
        except Exception as exc:
            log.error(
                "trigger_comment_collection: failed to fetch posts for %s: %s",
                platform,
                exc,
            )
            continue

        if not posts:
            log.info("trigger_comment_collection: no qualifying posts for %s", platform)
            continue

        task_name = _COMMENT_TASK_MAP[platform]
        tier = _COMMENT_DEFAULT_TIER.get(platform, "free")
        max_comments = platform_config.get("max_comments_per_post", 50)
        depth = platform_config.get("depth", 1)
        arena_label = f"{platform}_comments"

        # Create CollectionTask row for tracking
        try:
            await create_collection_tasks(
                collection_run_id=_uuid.UUID(collection_run_id),
                arena_tasks=[{
                    "arena": arena_label,
                    "platform": platform,
                    "tier": tier,
                }],
            )
        except Exception as exc:
            log.warning(
                "trigger_comment_collection: failed to create task row for %s: %s",
                arena_label,
                exc,
            )

        dispatches.append({
            "task_name": task_name,
            "arena_label": arena_label,
            "query_design_id": str(query_design_id),
            "collection_run_id": collection_run_id,
            "posts": posts,
            "tier": tier,
            "max_comments": max_comments,
            "depth": depth,
        })

    return {"dispatches": dispatches}


@celery_app.task(
    name="issue_observatory.workers.tasks.trigger_comment_collection",
    bind=True,
    max_retries=3,
)
def trigger_comment_collection(
    self: Any,
    collection_run_id: str,
) -> dict[str, Any]:
    """Dispatch comment collection tasks for enabled platforms (Phase 2).

    Called after all Phase 1 (post collection) arena tasks complete.
    Loads the project's ``comments_config``, queries for qualifying posts,
    creates ``CollectionTask`` rows, and dispatches per-platform Celery tasks.

    All async DB operations are consolidated into a single ``asyncio.run()``
    call to avoid asyncpg event-loop contamination.
    """
    log = logger.bind(task="trigger_comment_collection", run_id=collection_run_id)
    log.info("trigger_comment_collection: starting")

    # --- Single asyncio.run() for all DB operations ---
    try:
        result = asyncio.run(_trigger_comments_async(collection_run_id, log))
    except Exception as exc:
        log.error("trigger_comment_collection: async operations failed", error=str(exc))
        return {"error": str(exc), "platforms_dispatched": 0}

    dispatches = result.get("dispatches")
    if dispatches is None:
        # Early return from async function (no project, no config, etc.)
        return result

    # --- Sync Celery dispatch (outside asyncio.run) ---
    platforms_dispatched = 0
    total_posts = 0

    for d in dispatches:
        try:
            celery_app.send_task(
                d["task_name"],
                kwargs={
                    "query_design_id": d["query_design_id"],
                    "collection_run_id": d["collection_run_id"],
                    "post_ids": d["posts"],
                    "tier": d["tier"],
                    "max_comments_per_post": d["max_comments"],
                    "depth": d["depth"],
                },
            )
            platforms_dispatched += 1
            total_posts += len(d["posts"])
            log.info(
                "trigger_comment_collection: dispatched %s — %d posts",
                d["arena_label"],
                len(d["posts"]),
            )
        except Exception as exc:
            log.error(
                "trigger_comment_collection: failed to dispatch %s: %s",
                d["arena_label"],
                exc,
            )

    log.info(
        "trigger_comment_collection: done — dispatched=%d total_posts=%d",
        platforms_dispatched,
        total_posts,
    )
    return {
        "platforms_dispatched": platforms_dispatched,
        "total_posts": total_posts,
    }
