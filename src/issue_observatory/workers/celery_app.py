"""Celery application factory for Issue Observatory.

Configures the broker, result backend, serialization, task routing, and
timezone.  All configuration values are sourced from ``Settings`` so that
no secrets or environment-specific values are hard-coded here.

Usage (starting a worker)::

    celery -A issue_observatory.workers.celery_app worker --loglevel=info

Usage (starting the Beat scheduler for live tracking)::

    celery -A issue_observatory.workers.celery_app beat --loglevel=info

Usage (within application code)::

    from issue_observatory.workers.celery_app import celery_app

    result = celery_app.send_task(
        "issue_observatory.arenas.google_search.tasks.collect_by_terms",
        kwargs={"terms": ["klima"], "tier": "free"},
    )
"""

from __future__ import annotations

import logging

from celery import Celery
from celery.signals import task_postrun, worker_process_init
from dotenv import load_dotenv

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# F-07/F-08 fix: Load .env values into os.environ so CredentialPool can
# access arena API keys via env var fallback
# ---------------------------------------------------------------------------

load_dotenv()

from issue_observatory.config.settings import get_settings

settings = get_settings()

#: The global Celery application instance.
#: Import this object wherever tasks need to be sent or inspected.
celery_app = Celery(
    "issue_observatory",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        # Phase 0
        "issue_observatory.arenas.google_search.tasks",
        # Phase 1 — implemented arenas
        "issue_observatory.arenas.google_autocomplete.tasks",
        "issue_observatory.arenas.bluesky.tasks",
        "issue_observatory.arenas.reddit.tasks",
        "issue_observatory.arenas.youtube.tasks",
        "issue_observatory.arenas.rss_feeds.tasks",
        "issue_observatory.arenas.gdelt.tasks",
        # Phase 1 — remaining arenas (uncomment as implemented)
        "issue_observatory.arenas.telegram.tasks",
        # Phase 1 — Tasks 1.11–1.13 (implemented)
        "issue_observatory.arenas.tiktok.tasks",
        "issue_observatory.arenas.gab.tasks",
        "issue_observatory.arenas.ritzau_via.tasks",
        # Phase 2 — AI Chat Search (Task 2.x)
        "issue_observatory.arenas.ai_chat_search.tasks",
        # Phase 2 — implemented
        "issue_observatory.arenas.event_registry.tasks",
        "issue_observatory.arenas.x_twitter.tasks",
        # Phase 2 — Threads (implemented, Task 2.6)
        "issue_observatory.arenas.threads.tasks",
        # Phase 2 — web archive arenas (Task 2.10)
        "issue_observatory.arenas.web.common_crawl.tasks",
        "issue_observatory.arenas.web.wayback.tasks",
        # Phase 2 — Majestic backlink intelligence (Task 2.7)
        "issue_observatory.arenas.majestic.tasks",
        # Phase 2 — Task 2.3 (implemented)
        "issue_observatory.arenas.facebook.tasks",
        "issue_observatory.arenas.instagram.tasks",
        # Phase 2 — not yet implemented
        # "issue_observatory.arenas.linkedin.tasks",
        # Phase 2.5 — Wikipedia (editorial attention signals, free, no auth)
        "issue_observatory.arenas.wikipedia.tasks",
        # Phase 3+ — Discord (bot-based, requires server invitations)
        "issue_observatory.arenas.discord.tasks",
        # Phase 3+ — Twitch (streaming-only, deferred until specific need)
        "issue_observatory.arenas.twitch.tasks",
        # Phase 4/Future — VKontakte (deferred pending legal review)
        "issue_observatory.arenas.vkontakte.tasks",
        # Phase 3 — export tasks
        "issue_observatory.workers.export_tasks",
        # Phase 3 — maintenance tasks (dedup, Task 3.8)
        "issue_observatory.workers.maintenance_tasks",
        # Core orchestration tasks (beat schedule targets) and enrichment
        "issue_observatory.workers.tasks",
        # Scraper enrichment service
        "issue_observatory.scraper.tasks",
    ],
)

# ---------------------------------------------------------------------------
# Core configuration
# ---------------------------------------------------------------------------

celery_app.conf.update(
    # Serialization — JSON ensures tasks are inspectable and avoids pickle
    # security risks.  All task arguments and return values must be
    # JSON-serializable.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone — Copenhagen local time for Beat scheduling so that
    # "midnight collection" aligns with the Danish news cycle.
    timezone="Europe/Copenhagen",
    enable_utc=True,
    # Task acknowledgement — acknowledge only after the task has completed
    # (not when it is received) to avoid data loss on worker crash.
    task_acks_late=True,
    # Worker prefetch — set to 1 so that long-running collection tasks do
    # not pile up on a single worker and starve others.
    worker_prefetch_multiplier=1,
    # Result expiry — keep task results for 24 hours for status polling.
    result_expires=86_400,
    # Task time limits — collection tasks should not run indefinitely.
    # Soft limit sends SIGTERM; hard limit sends SIGKILL.
    task_soft_time_limit=3_600,   # 1 hour soft limit
    task_time_limit=7_200,        # 2 hour hard limit
    # Retry policy defaults for all tasks.
    task_max_retries=3,
    # Routing — streaming tasks (Bluesky firehose, Reddit, Telegram) run
    # on a dedicated queue to avoid blocking batch collection workers.
    # Scraping tasks run on a dedicated queue with extended time limits.
    task_routes={
        "issue_observatory.arenas.social_media.bluesky.tasks.stream*": {
            "queue": "streaming"
        },
        "issue_observatory.arenas.social_media.reddit.tasks.stream*": {
            "queue": "streaming"
        },
        "issue_observatory.arenas.social_media.telegram.tasks.stream*": {
            "queue": "streaming"
        },
        "issue_observatory.scraper.tasks.scrape_urls_task": {
            "queue": "scraping",
            "soft_time_limit": 7_200,   # 2 hours
            "time_limit": 10_800,        # 3 hours
        },
        "issue_observatory.scraper.tasks.cancel_scraping_job_task": {
            "queue": "scraping",
        },
        # Phase 3+ streaming arenas — 24-hour time limits for persistent connections
        "issue_observatory.arenas.discord.tasks.stream*": {
            "queue": "streaming",
            "soft_time_limit": 86_400,   # 24 hours
            "time_limit": 90_000,        # 25 hours (safety net before restart)
        },
        "issue_observatory.arenas.twitch.tasks.stream*": {
            "queue": "streaming",
            "soft_time_limit": 86_400,
            "time_limit": 90_000,
        },
    },
    # Beat schedule is imported from the dedicated module.
    beat_schedule_filename="celerybeat-schedule",
)

# Import and apply the Beat schedule after the app is configured.
from issue_observatory.workers.beat_schedule import beat_schedule  # noqa: E402

celery_app.conf.beat_schedule = beat_schedule


# ---------------------------------------------------------------------------
# Engine disposal on fork — prevents "attached to a different loop" errors
# ---------------------------------------------------------------------------
@worker_process_init.connect
def _dispose_engines_on_fork(**kwargs: object) -> None:  # noqa: ARG001
    """Dispose SQLAlchemy engines after Celery forks a worker process.

    The async engine creates connection objects tied to the parent's event
    loop.  After ``fork()``, those connections cannot be reused because the
    child process has a different loop.  Disposing the engines forces fresh
    connections to be created in the child's own event loop when
    ``asyncio.run()`` is called.
    """
    from issue_observatory.core import database as _db  # noqa: PLC0415

    _db.async_engine.sync_engine.dispose(close=False)
    _db._sync_engine.dispose(close=False)


# ---------------------------------------------------------------------------
# Engine disposal after each task — prevents cross-task event loop errors
# ---------------------------------------------------------------------------
@task_postrun.connect
def _dispose_async_engine_after_task(**kwargs: object) -> None:  # noqa: ARG001
    """Dispose the async engine's connection pool after each task completes.

    Celery prefork workers reuse the same process for multiple tasks.  If a
    task called ``asyncio.run()``, asyncpg connections in the pool are bound
    to the event loop that ``asyncio.run()`` created and then destroyed.
    When the next task calls ``asyncio.run()`` with a *new* loop, those
    pooled connections fail with ``RuntimeError: ... attached to a different
    loop``.

    Disposing the underlying sync engine (which manages the actual socket
    pool for asyncpg) after each task ensures the next task starts with a
    clean connection pool.
    """
    try:
        from issue_observatory.core import database as _db  # noqa: PLC0415

        _db.async_engine.sync_engine.dispose(close=False)
    except Exception:  # noqa: BLE001
        pass  # Best effort — never let cleanup crash the worker
