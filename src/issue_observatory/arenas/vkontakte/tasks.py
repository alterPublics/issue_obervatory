"""Celery tasks for the VKontakte (VK) arena.

DEFERRED ARENA -- Phase 4 / Future
====================================

This module is a stub. All collection tasks immediately raise
``ArenaCollectionError`` with a clear message directing the caller to the
legal review requirement. The tasks are registered with Celery so that:

1. The task names appear in the Celery task registry.
2. Misconfigured beat schedules that attempt to run these tasks will produce
   meaningful error messages rather than silent failures.
3. The task signatures document the intended calling convention for when the
   arena is eventually activated.

DO NOT configure Celery Beat to schedule these tasks until legal review is
complete and the collector methods have been fully implemented.

Task naming convention::

    issue_observatory.arenas.vkontakte.tasks.<action>

Legal Considerations
--------------------
Before enabling these tasks, university legal counsel must clear:
- EU sanctions status of VK Company
- GDPR cross-border data transfer basis (no Russia adequacy decision)
- Russian Federal Law No. 152-FZ interaction with GDPR
- API geo-restriction verification from deployment location

See docs/arenas/new_arenas_implementation_plan.md section 6.10 for the
full legal checklist.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from issue_observatory.arenas.vkontakte.collector import VKontakteCollector
from issue_observatory.core.exceptions import ArenaCollectionError
from issue_observatory.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_ARENA: str = "vkontakte"
_PLATFORM: str = "vkontakte"
_DEFERRED_MESSAGE: str = (
    "VKontakte arena is not yet implemented. This arena is DEFERRED pending "
    "university legal review of EU sanctions implications. "
    "See docs/arenas/new_arenas_implementation_plan.md section 6 for details."
)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="issue_observatory.arenas.vkontakte.tasks.collect_by_terms",
    bind=True,
    max_retries=0,
    acks_late=True,
)
def vkontakte_collect_terms(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    terms: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
    language_filter: list[str] | None = None,
) -> dict[str, Any]:
    """Stub task: would collect VK posts matching search terms via newsfeed.search.

    DEFERRED: Raises ArenaCollectionError immediately without making any
    network requests or database writes.

    Intended implementation:
        Wraps VKontakteCollector.collect_by_terms() as a Celery task.
        Uses newsfeed.search with date range (start_time/end_time as Unix
        timestamps). Paginates via next_from cursor. Updates collection_tasks
        row on completion.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        terms: Search terms to query against the VK newsfeed.
        tier: Tier string -- only "free" is valid for VKontakte.
        date_from: ISO 8601 earliest publication date (inclusive).
        date_to: ISO 8601 latest publication date (inclusive).
        max_results: Upper bound on returned records.
        language_filter: Unused -- VK has no native language filter.

    Returns:
        Never returns normally -- always raises ArenaCollectionError.

    Raises:
        ArenaCollectionError: Always -- arena is deferred pending legal review.
    """
    logger.error(
        "vkontakte: collect_by_terms task called for run=%s -- REJECTED: arena "
        "is DEFERRED pending university legal review.",
        collection_run_id,
    )
    raise ArenaCollectionError(
        _DEFERRED_MESSAGE,
        arena=_ARENA,
        platform=_PLATFORM,
    )


@celery_app.task(
    name="issue_observatory.arenas.vkontakte.tasks.collect_by_actors",
    bind=True,
    max_retries=0,
    acks_late=True,
)
def vkontakte_collect_actors(
    self: Any,
    query_design_id: str,
    collection_run_id: str,
    actor_ids: list[str],
    tier: str = "free",
    date_from: str | None = None,
    date_to: str | None = None,
    max_results: int | None = None,
) -> dict[str, Any]:
    """Stub task: would collect posts from VK community/user walls via wall.get.

    DEFERRED: Raises ArenaCollectionError immediately without making any
    network requests or database writes.

    Intended implementation:
        Wraps VKontakteCollector.collect_by_actors() as a Celery task.
        Uses wall.get with owner_id (negative for communities, positive for
        users). Paginates via numeric offset. Updates collection_tasks row
        on completion.

    Args:
        query_design_id: UUID string of the owning query design.
        collection_run_id: UUID string of the owning collection run.
        actor_ids: VK owner IDs. Negative = community; positive = user.
        tier: Tier string -- only "free" is valid for VKontakte.
        date_from: ISO 8601 earliest publication date (inclusive).
        date_to: ISO 8601 latest publication date (inclusive).
        max_results: Upper bound on returned records.

    Returns:
        Never returns normally -- always raises ArenaCollectionError.

    Raises:
        ArenaCollectionError: Always -- arena is deferred pending legal review.
    """
    logger.error(
        "vkontakte: collect_by_actors task called for run=%s -- REJECTED: arena "
        "is DEFERRED pending university legal review.",
        collection_run_id,
    )
    raise ArenaCollectionError(
        _DEFERRED_MESSAGE,
        arena=_ARENA,
        platform=_PLATFORM,
    )


@celery_app.task(
    name="issue_observatory.arenas.vkontakte.tasks.health_check",
    bind=False,
)
def vkontakte_health_check() -> dict[str, Any]:
    """Run the health check for the (deferred) VKontakte arena.

    Unlike the collection tasks, this task does not raise an error -- it
    returns a not_implemented status dict. This allows monitoring pipelines
    to query arena health without triggering error alerts for expected
    deferred arenas.

    Returns:
        Health status dict with status="not_implemented", arena="social_media",
        platform="vkontakte", and a detail message explaining the deferral.
    """
    collector = VKontakteCollector()
    result: dict[str, Any] = asyncio.run(collector.health_check())
    logger.info(
        "vkontakte: health_check status=%s", result.get("status", "unknown")
    )
    return result
