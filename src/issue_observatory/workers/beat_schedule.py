"""Celery Beat periodic task schedule for Issue Observatory.

Defines when automated collection, health-check, and maintenance tasks run.
All times are expressed in the ``Europe/Copenhagen`` timezone (configured in
``celery_app.py``) so that "midnight" aligns with the Danish news cycle.

This module is imported by ``celery_app.py`` and applied via
``celery_app.conf.beat_schedule``.  Add new periodic tasks here as new
arenas are activated in Phase 1 / Phase 2.

Schedule overview:

+---------------------------+---------------------+-----------------------------+
| Task name                 | Schedule            | Purpose                     |
+===========================+=====================+=============================+
| daily_collection          | 00:00 Copenhagen    | Trigger all active live-     |
|                           |                     | tracking query designs.      |
+---------------------------+---------------------+-----------------------------+
| health_check_all_arenas   | Every 6 hours       | Poll all arena health-check  |
|                           |                     | endpoints, update admin UI.  |
+---------------------------+---------------------+-----------------------------+
| credit_settlement         | Every 6 hours       | Settle pending credit        |
|                           |                     | reservations from completed  |
|                           |                     | collection tasks.            |
+---------------------------+---------------------+-----------------------------+
| stale_run_cleanup         | 03:00 Copenhagen    | Mark collection runs that    |
|                           |                     | have been in a non-terminal  |
|                           |                     | state for > 24 h as failed.  |
+---------------------------+---------------------+-----------------------------+
| retention_enforcement     | 04:00 Copenhagen    | Delete records older than    |
|                           |                     | DATA_RETENTION_DAYS.         |
+---------------------------+---------------------+-----------------------------+
| nightly_enrichment        | 00:00 Copenhagen    | Enrich all content records   |
|                           |                     | missing language_detection,  |
|                           |                     | actor_roles, or              |
|                           |                     | url_extraction enrichments.  |
+---------------------------+---------------------+-----------------------------+
"""

from __future__ import annotations

from celery.schedules import crontab

#: Celery Beat schedule dict.  Applied to ``celery_app.conf.beat_schedule``
#: in ``celery_app.py``.
beat_schedule: dict[str, dict] = {  # type: ignore[type-arg]
    # ------------------------------------------------------------------
    # Live collection — triggers all active query designs at midnight
    # ------------------------------------------------------------------
    "daily_collection": {
        "task": "issue_observatory.workers.tasks.trigger_daily_collection",
        "schedule": crontab(hour=0, minute=0),
        "options": {
            "queue": "celery",
            "expires": 3_600,  # discard if not started within 1 hour
        },
    },
    # ------------------------------------------------------------------
    # Arena health checks — 4 times per day (every 6 hours)
    # ------------------------------------------------------------------
    "health_check_all_arenas": {
        "task": "issue_observatory.workers.tasks.health_check_all_arenas",
        "schedule": crontab(minute=15, hour="*/6"),
        "options": {
            "queue": "celery",
            "expires": 21_600,  # discard if not started within 6 hours
        },
    },
    # ------------------------------------------------------------------
    # Credit settlement — every 6 hours
    # ------------------------------------------------------------------
    "credit_settlement": {
        "task": "issue_observatory.workers.tasks.settle_pending_credits",
        "schedule": crontab(minute=30, hour="*/6"),  # at :30 past every 6th hour
        "options": {
            "queue": "celery",
            "expires": 3_600,
        },
    },
    # ------------------------------------------------------------------
    # Stale run cleanup — 03:00 Copenhagen time (daily)
    # ------------------------------------------------------------------
    "stale_run_cleanup": {
        "task": "issue_observatory.workers.tasks.cleanup_stale_runs",
        "schedule": crontab(hour=3, minute=0),
        "options": {
            "queue": "celery",
            "expires": 3_600,
        },
    },
    # ------------------------------------------------------------------
    # GDPR retention enforcement — 04:00 Copenhagen time
    # ------------------------------------------------------------------
    "retention_enforcement": {
        "task": "issue_observatory.workers.tasks.enforce_retention_policy",
        "schedule": crontab(hour=4, minute=0),
        "options": {
            "queue": "celery",
            "expires": 3_600,
        },
    },
    # ------------------------------------------------------------------
    # Threads — daily token refresh (tokens expire after 60 days)
    # Runs at 02:00 Copenhagen time to avoid overlap with daily collection.
    # ------------------------------------------------------------------
    "threads_refresh_tokens": {
        "task": "issue_observatory.arenas.threads.tasks.refresh_tokens",
        "schedule": crontab(hour=2, minute=0),
        "options": {
            "queue": "celery",
            "expires": 3_600,  # discard if not started within 1 hour
        },
    },
    # ------------------------------------------------------------------
    # Collection attempt reconciliation — weekly Sunday 05:00 Copenhagen
    # Validates that collection_attempts entries still have corresponding
    # data in content_records.  Invalidates stale entries so coverage
    # checks don't block re-collection of deleted data.
    # ------------------------------------------------------------------
    "reconcile_collection_attempts": {
        "task": "issue_observatory.workers.tasks.reconcile_collection_attempts",
        "schedule": crontab(hour=5, minute=0, day_of_week="sunday"),
        "options": {
            "queue": "celery",
            "expires": 7_200,  # discard if not started within 2 hours
        },
    },
    # ------------------------------------------------------------------
    # Weekly engagement scaler refit — Monday 01:00 Copenhagen time
    # Fits per-platform Yeo-Johnson + MinMaxScaler transformers to actual
    # engagement distributions.  Requires scikit-learn + numpy.
    # ------------------------------------------------------------------
    "refit_engagement_scalers": {
        "task": "issue_observatory.workers.tasks.refit_engagement_scalers",
        "schedule": crontab(hour=1, minute=0, day_of_week="monday"),
        "options": {
            "queue": "celery",
            "expires": 7_200,  # discard if not started within 2 hours
        },
    },
    # ------------------------------------------------------------------
    # Nightly enrichment — 00:00 Copenhagen time
    # Processes all content records that are missing language_detection,
    # actor_roles, or url_extraction enrichments (e.g. records collected
    # before the enrichment pipeline was active, or records where spaCy
    # was not installed at collection time).
    # ------------------------------------------------------------------
    "nightly_enrichment": {
        "task": "issue_observatory.workers.tasks.enrich_all_pending",
        "schedule": crontab(hour=0, minute=0),
        "options": {
            "queue": "celery",
            "expires": 14_400,  # 4 hours — NER can be slow on large backlogs
        },
    },
}
