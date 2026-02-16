"""Prometheus metrics for Issue Observatory.

Exposes application-level metrics alongside the standard process metrics
from prometheus_client.

All metrics are module-level singletons registered on the default
``REGISTRY``.  They are safe to import from multiple modules because
prometheus_client deduplicates by metric name.

Metrics defined here:

  collection_runs_total{status, tier}
      Counter — collection run completions broken down by final status
      (completed, failed, cancelled, suspended) and collection tier.

  collection_records_total{arena, platform}
      Counter — total content records ingested, labelled by arena key and
      source platform name.

  arena_health_status{arena}
      Gauge — per-arena health indicator.  1 = healthy, 0 = degraded or down.
      Updated by the ``health_check_all_arenas`` Celery task.

  credit_transactions_total{type, arena}
      Counter — credit transactions by transaction type
      (reservation, settlement, refund) and arena.

  http_requests_total{method, path, status}
      Counter — HTTP requests handled by the FastAPI application, labelled by
      HTTP method, normalised path, and response status code.

  http_request_duration_seconds{method, path}
      Histogram — HTTP request latency in seconds.

  celery_tasks_total{task_name, status}
      Counter — Celery task completions by task name and outcome (success, error).

  celery_task_duration_seconds{task_name}
      Histogram — Celery task wall-clock duration in seconds.

Usage::

    from issue_observatory.api.metrics import collection_runs_total
    collection_runs_total.labels(status="completed", tier="free").inc()
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Collection metrics
# ---------------------------------------------------------------------------

collection_runs_total: Counter = Counter(
    "collection_runs_total",
    "Total collection run completions by status and tier.",
    labelnames=["status", "tier"],
)
"""Counter incremented when a collection run reaches a terminal state.

Labels:
  status: one of completed, failed, cancelled, suspended
  tier:   one of free, medium, premium
"""

collection_records_total: Counter = Counter(
    "collection_records_total",
    "Total content records ingested by arena and platform.",
    labelnames=["arena", "platform"],
)
"""Counter incremented for each content record written to the database.

Labels:
  arena:    arena key (e.g. google_search, bluesky)
  platform: source platform name (e.g. google, bsky.social)
"""

# ---------------------------------------------------------------------------
# Arena health
# ---------------------------------------------------------------------------

arena_health_status: Gauge = Gauge(
    "arena_health_status",
    "Per-arena health indicator. 1 = healthy, 0 = degraded or down.",
    labelnames=["arena"],
)
"""Gauge updated by the health_check_all_arenas Celery task.

Labels:
  arena: arena key (e.g. google_search, bluesky)
"""

# ---------------------------------------------------------------------------
# Credit metrics
# ---------------------------------------------------------------------------

credit_transactions_total: Counter = Counter(
    "credit_transactions_total",
    "Credit transactions by type and arena.",
    labelnames=["type", "arena"],
)
"""Counter incremented on every credit transaction.

Labels:
  type:  one of reservation, settlement, refund
  arena: arena key or 'system' for non-arena transactions
"""

# ---------------------------------------------------------------------------
# HTTP metrics (populated by middleware in main.py)
# ---------------------------------------------------------------------------

http_requests_total: Counter = Counter(
    "http_requests_total",
    "HTTP requests handled by the FastAPI application.",
    labelnames=["method", "path", "status"],
)
"""Counter incremented after every HTTP response.

Labels:
  method: HTTP method (GET, POST, …)
  path:   normalised URL path (route template where possible)
  status: HTTP response status code as string (e.g. '200', '404')
"""

http_request_duration_seconds: Histogram = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    labelnames=["method", "path"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)
"""Histogram of HTTP request durations.

Labels:
  method: HTTP method
  path:   normalised URL path
"""

# ---------------------------------------------------------------------------
# Celery task metrics (populated in workers/tasks.py)
# ---------------------------------------------------------------------------

celery_tasks_total: Counter = Counter(
    "celery_tasks_total",
    "Celery task completions by task name and outcome.",
    labelnames=["task_name", "status"],
)
"""Counter incremented at the end of each Celery task execution.

Labels:
  task_name: short task name (e.g. trigger_daily_collection)
  status:    'success' or 'error'
"""

celery_task_duration_seconds: Histogram = Histogram(
    "celery_task_duration_seconds",
    "Celery task wall-clock duration in seconds.",
    labelnames=["task_name"],
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0],
)
"""Histogram of Celery task durations.

Labels:
  task_name: short task name
"""


# ---------------------------------------------------------------------------
# Response helper
# ---------------------------------------------------------------------------


def get_metrics_response() -> tuple[bytes, str]:
    """Generate a Prometheus text-format metrics response.

    Returns:
        A tuple of (body_bytes, content_type_string) suitable for constructing
        a FastAPI ``Response`` object.
    """
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest  # noqa: PLC0415

    return generate_latest(), CONTENT_TYPE_LATEST
