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
    enforce_retention,
    fetch_live_tracking_designs,
    fetch_public_figure_ids_for_design,
    fetch_search_terms_for_arena,
    fetch_stale_runs,
    fetch_unsettled_reservations,
    get_user_credit_balance,
    get_user_email,
    mark_runs_failed,
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

    try:
        designs = asyncio.run(fetch_live_tracking_designs())
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
        owner_id = design["owner_id"]
        arenas_config: dict[str, str] = design.get("arenas_config") or {}
        default_tier: str = design.get("default_tier") or "free"
        # GR-05: arenas_config["languages"] takes priority over the single
        # query_design.language field.  If the key is missing, fall back to
        # [query_design.language] (IP2-052 behaviour).
        config_languages = arenas_config.get("languages") if isinstance(arenas_config, dict) else None
        if isinstance(config_languages, list) and config_languages:
            language_filter: list[str] = [str(lc) for lc in config_languages if lc]
        else:
            raw_language: str = design.get("language") or "da"
            language_filter = parse_language_codes(raw_language)

        task_log = log.bind(
            query_design_id=str(design_id), run_id=str(run_id)
        )
        task_log.info("trigger_daily_collection: processing design")

        # --- Credit gate ---
        try:
            balance = asyncio.run(get_user_credit_balance(owner_id))
        except Exception as exc:
            task_log.error(
                "trigger_daily_collection: failed to fetch credit balance",
                error=str(exc),
                exc_info=True,
            )
            skipped += 1
            continue

        if balance <= 0:
            task_log.warning(
                "trigger_daily_collection: insufficient credits; suspending run",
                balance=balance,
            )
            try:
                user_email = asyncio.run(get_user_email(owner_id))
                if user_email:
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

        # --- GR-14: build set of public-figure platform user IDs ---
        # This is fetched once per design (not per arena) and passed to every
        # arena task so the normalizer can bypass pseudonymization for known
        # public officials without a per-record DB lookup at collection time.
        public_figure_ids: list[str] = []
        try:
            pf_set = asyncio.run(fetch_public_figure_ids_for_design(design_id))
            public_figure_ids = list(pf_set)
            if public_figure_ids:
                task_log.info(
                    "trigger_daily_collection: GR-14 public-figure IDs loaded",
                    count=len(public_figure_ids),
                )
        except Exception as pf_exc:
            # Non-fatal: log and continue without the bypass.
            # Arena tasks will still run; all authors will be pseudonymized.
            task_log.warning(
                "trigger_daily_collection: failed to fetch public-figure IDs; "
                "all authors will be pseudonymized (GR-14 bypass unavailable)",
                error=str(pf_exc),
            )

        # --- Dispatch arena tasks ---
        # YF-01: Load and filter search terms per arena based on target_arenas.
        # Each arena receives only the terms that are either globally applicable
        # (target_arenas=NULL) or explicitly targeted to that arena's platform_name.
        for arena_name, arena_tier in arenas_config.items():
            tier = arena_tier or default_tier

            # YF-01: Fetch search terms scoped to this arena's platform_name.
            # The arena_name in arenas_config is the platform_name used in the
            # registry (e.g., "reddit", "bluesky", "google_search").
            try:
                arena_terms = asyncio.run(
                    fetch_search_terms_for_arena(design_id, arena_name)
                )
            except Exception as terms_exc:
                task_log.error(
                    "trigger_daily_collection: failed to fetch search terms for arena",
                    arena=arena_name,
                    error=str(terms_exc),
                    exc_info=True,
                )
                # Non-fatal: log and skip this arena rather than failing the
                # entire daily collection.  The run will continue with the
                # remaining arenas.
                skipped += 1
                continue

            if not arena_terms:
                task_log.info(
                    "trigger_daily_collection: no search terms scoped to arena; skipping",
                    arena=arena_name,
                )
                # No terms for this arena — skip dispatch but don't count as an
                # error.  This is expected when YF-01 per-arena scoping is in use.
                continue

            task_name = (
                f"issue_observatory.arenas.{arena_name}.tasks.collect_by_terms"
            )
            try:
                celery_app.send_task(
                    task_name,
                    kwargs={
                        "query_design_id": str(design_id),
                        "collection_run_id": str(run_id),
                        "terms": arena_terms,
                        "tier": tier,
                        # IP2-052: pass language filter so arena tasks can
                        # restrict results to the design's configured language(s).
                        "language_filter": language_filter,
                        # GR-14: public-figure platform user IDs; arena tasks
                        # forward this to the normalizer to bypass
                        # pseudonymization for known public officials.
                        "public_figure_ids": public_figure_ids,
                    },
                    queue="celery",
                )
                task_log.info(
                    "trigger_daily_collection: dispatched arena task",
                    arena=arena_name,
                    tier=tier,
                    task_name=task_name,
                    terms_count=len(arena_terms),
                )
            except Exception as dispatch_exc:
                task_log.error(
                    "trigger_daily_collection: dispatch failed",
                    arena=arena_name,
                    error=str(dispatch_exc),
                )
        dispatched += 1

    summary = {
        "designs_processed": len(designs),
        "dispatched": dispatched,
        "skipped": skipped,
    }
    log.info("trigger_daily_collection: complete", **summary)
    try:
        from issue_observatory.api.metrics import (  # noqa: PLC0415
            celery_task_duration_seconds,
            celery_tasks_total,
        )
        celery_tasks_total.labels(
            task_name="trigger_daily_collection", status="success"
        ).inc()
        celery_task_duration_seconds.labels(
            task_name="trigger_daily_collection"
        ).observe(time.perf_counter() - _task_start)
    except Exception as _metrics_exc:  # noqa: BLE001
        _stdlib_logger.debug(
            "trigger_daily_collection: metrics recording failed: %s", _metrics_exc
        )
    return summary


# ---------------------------------------------------------------------------
# Task 2: health_check_all_arenas
# ---------------------------------------------------------------------------


@celery_app.task(name="issue_observatory.workers.tasks.health_check_all_arenas")
def health_check_all_arenas() -> dict[str, Any]:  # noqa: PLR0912
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
    from issue_observatory.arenas.registry import autodiscover, list_arenas  # noqa: PLC0415

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

    for arena_info in arenas:
        arena_name: str = arena_info["arena_name"]
        platform_name: str = arena_info["platform_name"]
        collector_class: str = arena_info.get("collector_class", "")
        try:
            # collector_class = "issue_observatory.arenas.{...}.collector.ClassName"
            # Drop the class name to get the module, then drop ".collector"
            # to get the arena package.
            module_parts = collector_class.split(".")[:-1]  # drop class name
            arena_package = ".".join(module_parts[:-1])     # drop ".collector"
            # Task naming convention: {arena_package}.tasks.{platform_name}_health_check
            # (platform_name is the unique per-collector identifier; arena_name is a
            # shared grouping label that multiple collectors share, so it cannot be
            # used unambiguously as a task name component).
            task_name = f"{arena_package}.tasks.{platform_name}_health_check"
        except Exception:
            task_name = (
                f"issue_observatory.arenas.{platform_name}"
                f".tasks.{platform_name}_health_check"
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
        from issue_observatory.api.metrics import (  # noqa: PLC0415
            celery_task_duration_seconds,
            celery_tasks_total,
        )
        celery_tasks_total.labels(
            task_name="health_check_all_arenas", status="success"
        ).inc()
        celery_task_duration_seconds.labels(
            task_name="health_check_all_arenas"
        ).observe(time.perf_counter() - _task_start)
    except Exception as _metrics_exc:  # noqa: BLE001
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
        from issue_observatory.api.metrics import (  # noqa: PLC0415
            celery_task_duration_seconds,
            celery_tasks_total,
        )
        celery_tasks_total.labels(
            task_name="settle_pending_credits", status="success"
        ).inc()
        celery_task_duration_seconds.labels(
            task_name="settle_pending_credits"
        ).observe(time.perf_counter() - _task_start)
    except Exception as _metrics_exc:  # noqa: BLE001
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
        from issue_observatory.api.metrics import (  # noqa: PLC0415
            celery_task_duration_seconds,
            celery_tasks_total,
        )
        celery_tasks_total.labels(
            task_name="cleanup_stale_runs", status="success"
        ).inc()
        celery_task_duration_seconds.labels(
            task_name="cleanup_stale_runs"
        ).observe(time.perf_counter() - _task_start)
    except Exception as _metrics_exc:  # noqa: BLE001
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
        from issue_observatory.api.metrics import (  # noqa: PLC0415
            celery_task_duration_seconds,
            celery_tasks_total,
        )
        celery_tasks_total.labels(
            task_name="enforce_retention_policy", status="success"
        ).inc()
        celery_task_duration_seconds.labels(
            task_name="enforce_retention_policy"
        ).observe(time.perf_counter() - _task_start)
    except Exception as _metrics_exc:  # noqa: BLE001
        _stdlib_logger.debug(
            "enforce_retention_policy: metrics recording failed: %s", _metrics_exc
        )
    return summary


# ---------------------------------------------------------------------------
# Task 6: enrich_collection_run
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
    from issue_observatory.analysis.enrichments import (  # noqa: PLC0415
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
            batch = asyncio.run(
                fetch_content_records_for_run(run_id, offset=offset)
            )
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
                    asyncio.run(
                        write_enrichment(record_id, enricher.enricher_name, result)
                    )
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
        if len(batch) < 100:  # noqa: PLR2004 — batch size constant
            break  # last partial batch; no more rows

    summary = {
        "records_processed": records_processed,
        "enrichments_applied": enrichments_applied,
        "error_count": error_count,
    }
    log.info("enrich_collection_run: complete", **summary)
    try:
        from issue_observatory.api.metrics import (  # noqa: PLC0415
            celery_task_duration_seconds,
            celery_tasks_total,
        )
        celery_tasks_total.labels(
            task_name="enrich_collection_run", status="success"
        ).inc()
        celery_task_duration_seconds.labels(
            task_name="enrich_collection_run"
        ).observe(time.perf_counter() - _task_start)
    except Exception as _metrics_exc:  # noqa: BLE001
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
    import uuid as _uuid  # noqa: PLC0415

    _task_start = time.perf_counter()
    log = logger.bind(
        task="check_volume_spikes",
        collection_run_id=collection_run_id,
        query_design_id=query_design_id,
    )
    log.info("check_volume_spikes: starting")

    from issue_observatory.workers._alerting_helpers import (  # noqa: PLC0415
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
        from issue_observatory.api.metrics import (  # noqa: PLC0415
            celery_task_duration_seconds,
            celery_tasks_total,
        )
        celery_tasks_total.labels(
            task_name="check_volume_spikes", status="success"
        ).inc()
        celery_task_duration_seconds.labels(
            task_name="check_volume_spikes"
        ).observe(time.perf_counter() - _task_start)
    except Exception as _metrics_exc:  # noqa: BLE001
        _stdlib_logger.debug(
            "check_volume_spikes: metrics recording failed: %s", _metrics_exc
        )
    return summary
