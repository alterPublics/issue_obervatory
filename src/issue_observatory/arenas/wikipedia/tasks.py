"""Celery tasks for the Wikipedia arena.

Wraps :class:`~issue_observatory.arenas.wikipedia.collector.WikipediaCollector`
methods as Celery tasks with automatic retry behaviour and collection run
status tracking.

Task naming convention::

    issue_observatory.arenas.wikipedia.tasks.<action>

Retry policy:
- ``ArenaRateLimitError`` triggers automatic retry with exponential backoff
  (up to ``max_retries=3``).  The Wikimedia API rarely rate-limits at 5 req/s,
  but this handles transient HTTP 429 responses defensively.
- ``ArenaCollectionError`` is logged and re-raised so Celery marks the task
  FAILED.

All tasks update the ``collection_tasks`` row as best-effort (DB failures are
logged at WARNING and do not mask collection outcomes).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from issue_observatory.arenas.wikipedia.collector import WikipediaCollector
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
)
from issue_observatory.config.settings import get_settings
from issue_observatory.core.event_bus import elapsed_since, publish_task_update
from issue_observatory.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_ARENA = "wikipedia"


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
        status: New status value (``"running"`` | ``"completed"`` | ``"failed"``).
        records_collected: Number of records collected.
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
            "wikipedia: failed to update collection_tasks status to '%s': %s",
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
        from issue_observatory.core.database import get_sync_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with get_sync_session() as session:
            row = session.execute(
                text("SELECT arenas_config FROM query_designs WHERE id = :id"),
                {"id": query_design_id},
            ).fetchone()
            if row and row[0]:
                return dict(row[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "wikipedia: failed to load arenas_config for design %s: %s",
            query_design_id,
            exc,
        )
    return {}


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.wikipedia.tasks.collect_by_terms",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
    soft_time_limit=600,
    time_limit=720,
)
def wikipedia_collect_terms(
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
    """Collect Wikipedia revision and pageview records for search terms.

    Wraps :meth:`~WikipediaCollector.collect_by_terms` as an idempotent
    Celery task.  Updates the ``collection_tasks`` row with progress and
    final status.

    For each term, the task:
    1. Searches ``da.wikipedia.org`` (and ``en.wikipedia.org`` when
       ``language_filter`` allows) for matching articles.
    2. Collects revision history for each discovered article.
    3. Collects daily pageview data for each discovered article.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms to match against Wikipedia article content.
        tier: Tier string — only ``"free"`` is valid for Wikipedia.
        date_from: ISO 8601 earliest publication date (inclusive).
        date_to: ISO 8601 latest publication date (inclusive).
        max_results: Upper bound on returned records.
        language_filter: Optional list of ISO 639-1 language codes
            (e.g. ``["da"]`` or ``["da", "en"]``).

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry with exponential backoff.
        ArenaCollectionError: Marks the task as FAILED in Celery.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    try:
        logger.info(
            "wikipedia: collect_by_terms started — run=%s terms=%d tier=%s",
            collection_run_id,
            len(terms),
            tier,
        )
        _update_task_status(collection_run_id, _ARENA, "running")
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="reference",
            platform="wikipedia",
            status="running",
            records_collected=0,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        # GR-04: read researcher-configured seed articles from arenas_config.
        arenas_config = _load_arenas_config(query_design_id)
        extra_seed_articles: list[str] | None = None
        wiki_config = arenas_config.get("wikipedia") or {}
        if isinstance(wiki_config, dict):
            raw_seeds = wiki_config.get("seed_articles")
            if isinstance(raw_seeds, list) and raw_seeds:
                extra_seed_articles = [str(a) for a in raw_seeds if a]

        try:
            tier_enum = Tier(tier)
        except ValueError:
            msg = f"wikipedia: invalid tier '{tier}'. Only 'free' is supported."
            logger.error(msg)
            _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="reference",
                platform="wikipedia",
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise ArenaCollectionError(msg, arena=_ARENA, platform="wikipedia")

        collector = WikipediaCollector()

        # NOTE: Wikipedia is FORWARD_ONLY — it monitors editorial revisions and
        # pageviews going forward.  Coverage pre-check is intentionally skipped
        # because revision monitoring should always fetch the latest state.

        try:
            records = asyncio.run(
                collector.collect_by_terms(
                    terms=terms,
                    tier=tier_enum,
                    date_from=date_from,
                    date_to=date_to,
                    max_results=max_results,
                    language_filter=language_filter,
                    extra_seed_articles=extra_seed_articles,
                )
            )
        except ArenaRateLimitError:
            logger.warning(
                "wikipedia: rate limited on collect_by_terms for run=%s — will retry.",
                collection_run_id,
            )
            raise
        except ArenaCollectionError as exc:
            msg = str(exc)
            logger.error("wikipedia: collection error for run=%s: %s", collection_run_id, msg)
            _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="reference",
                platform="wikipedia",
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise

        count = len(records)

        # Persist collected records to the database.
        from issue_observatory.workers._task_helpers import persist_collected_records  # noqa: PLC0415

        inserted, skipped = persist_collected_records(records, collection_run_id, query_design_id, terms=terms)

        logger.info(
            "wikipedia: collect_by_terms completed — run=%s records=%d inserted=%d skipped=%d",
            collection_run_id,
            count,
            inserted,
            skipped,
        )
        _update_task_status(collection_run_id, _ARENA, "completed", records_collected=inserted)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="reference",
            platform="wikipedia",
            status="completed",
            records_collected=inserted,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        return {
            "records_collected": inserted,
            "status": "completed",
            "arena": _ARENA,
            "tier": tier,
        }
    except SoftTimeLimitExceeded:
        logger.error(
            "wikipedia: collect_by_terms timed out after 10 minutes — run=%s",
            collection_run_id,
        )
        _update_task_status(
            collection_run_id,
            _ARENA,
            "failed",
            error_message="Collection timed out after 10 minutes",
        )
        return {"status": "failed", "error": "timeout", "arena": _ARENA}


@celery_app.task(
    name="issue_observatory.arenas.wikipedia.tasks.collect_by_actors",
    bind=True,
    max_retries=3,
    autoretry_for=(ArenaRateLimitError,),
    retry_backoff=True,
    retry_backoff_max=300,
    acks_late=True,
    soft_time_limit=600,
    time_limit=720,
)
def wikipedia_collect_actors(
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
    """Collect Wikipedia revisions authored by specific Wikipedia editors.

    Wraps :meth:`~WikipediaCollector.collect_by_actors`.  Each ``actor_id``
    is a Wikipedia username.  The task queries both Danish and English
    Wikipedia for each username's contribution history.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: Wikipedia usernames to collect contributions for.
        tier: Tier string — only ``"free"`` is valid.
        date_from: ISO 8601 earliest publication date (inclusive).
        date_to: ISO 8601 latest publication date (inclusive).
        max_results: Upper bound on returned records.

    Returns:
        Dict with ``records_collected``, ``status``, ``arena``, ``tier``.

    Raises:
        ArenaRateLimitError: Triggers automatic retry.
        ArenaCollectionError: Marks the task as FAILED.
    """
    from issue_observatory.arenas.base import Tier  # noqa: PLC0415

    _settings = get_settings()
    _redis_url = _settings.redis_url
    _task_start = time.monotonic()

    try:
        logger.info(
            "wikipedia: collect_by_actors started — run=%s actors=%d tier=%s",
            collection_run_id,
            len(actor_ids),
            tier,
        )
        _update_task_status(collection_run_id, _ARENA, "running")
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="reference",
            platform="wikipedia",
            status="running",
            records_collected=0,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        try:
            tier_enum = Tier(tier)
        except ValueError:
            msg = f"wikipedia: invalid tier '{tier}'. Only 'free' is supported."
            logger.error(msg)
            _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="reference",
                platform="wikipedia",
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise ArenaCollectionError(msg, arena=_ARENA, platform="wikipedia")

        collector = WikipediaCollector()

        # NOTE: Wikipedia is FORWARD_ONLY — coverage pre-check skipped.
        # See collect_by_terms for explanation.

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
                "wikipedia: rate limited on collect_by_actors for run=%s — will retry.",
                collection_run_id,
            )
            raise
        except ArenaCollectionError as exc:
            msg = str(exc)
            logger.error("wikipedia: collection error for run=%s: %s", collection_run_id, msg)
            _update_task_status(collection_run_id, _ARENA, "failed", error_message=msg)
            publish_task_update(
                redis_url=_redis_url,
                run_id=collection_run_id,
                arena="reference",
                platform="wikipedia",
                status="failed",
                records_collected=0,
                error_message=msg,
                elapsed_seconds=elapsed_since(_task_start),
            )
            raise

        count = len(records)

        # Persist collected records to the database.
        from issue_observatory.workers._task_helpers import persist_collected_records  # noqa: PLC0415

        inserted, skipped = persist_collected_records(records, collection_run_id, query_design_id)

        logger.info(
            "wikipedia: collect_by_actors completed — run=%s records=%d inserted=%d skipped=%d",
            collection_run_id,
            count,
            inserted,
            skipped,
        )
        _update_task_status(collection_run_id, _ARENA, "completed", records_collected=inserted)
        publish_task_update(
            redis_url=_redis_url,
            run_id=collection_run_id,
            arena="reference",
            platform="wikipedia",
            status="completed",
            records_collected=inserted,
            error_message=None,
            elapsed_seconds=elapsed_since(_task_start),
        )

        return {
            "records_collected": inserted,
            "status": "completed",
            "arena": _ARENA,
            "tier": tier,
        }
    except SoftTimeLimitExceeded:
        logger.error(
            "wikipedia: collect_by_actors timed out after 10 minutes — run=%s",
            collection_run_id,
        )
        _update_task_status(
            collection_run_id,
            _ARENA,
            "failed",
            error_message="Collection timed out after 10 minutes",
        )
        return {"status": "failed", "error": "timeout", "arena": _ARENA}


@celery_app.task(
    name="issue_observatory.arenas.wikipedia.tasks.health_check",
    bind=False,
)
def wikipedia_health_check() -> dict[str, Any]:
    """Run a connectivity health check for the Wikipedia arena.

    Delegates to :meth:`~WikipediaCollector.health_check`, which fetches
    ``action=query&meta=siteinfo`` from ``da.wikipedia.org`` and verifies
    the response is valid JSON.

    Returns:
        Health status dict with keys ``status``, ``arena``, ``platform``,
        ``checked_at``, and optionally ``site`` or ``detail``.
    """
    collector = WikipediaCollector()
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info(
        "wikipedia: health_check status=%s", result.get("status", "unknown")
    )
    return result
