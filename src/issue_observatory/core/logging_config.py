"""Structured JSON logging configuration using structlog.

Call ``configure_logging()`` once at application startup in ``main.py``.
All modules can then use either the stdlib logging API or structlog directly:

Stdlib usage::

    import logging
    logger = logging.getLogger(__name__)
    logger.info("message", extra={"key": "value"})

Structlog usage (richer context binding)::

    import structlog
    logger = structlog.get_logger(__name__)
    logger.info("message", key="value", arena="reddit")

A ``request_id`` context variable is populated by the request-logging
middleware in ``api/main.py`` and automatically merged into every log record
emitted during that request's lifetime.
"""

from __future__ import annotations

import logging
import logging.config
import sys
from contextvars import ContextVar

import structlog
from structlog.types import EventDict, WrappedLogger

# ---------------------------------------------------------------------------
# Context variable — set by the HTTP middleware, read by the log processor
# ---------------------------------------------------------------------------

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
"""Per-request ID propagated from the HTTP middleware to log processors.

Usage in middleware::

    from issue_observatory.core.logging_config import request_id_var
    request_id_var.set(str(uuid.uuid4()))
"""


# ---------------------------------------------------------------------------
# Custom processors
# ---------------------------------------------------------------------------


_SECRET_SUBSTRINGS: frozenset[str] = frozenset({
    "api_key",
    "password",
    "secret",
    "token",
    "credential",
    "bearer",
    "authorization",
    "x-api-key",
    "app_password",
    "encryption_key",
    "fernet",
    "salt",
})
"""Lower-cased substrings that identify log event-dict keys whose values
must be redacted before the record reaches any renderer."""


def _redact_secrets(
    logger: WrappedLogger,  # noqa: ARG001
    method_name: str,  # noqa: ARG001
    event_dict: EventDict,
) -> EventDict:
    """Replace values of secret-bearing keys with a redaction marker.

    Scans both top-level keys and any nested ``dict`` values one level deep.
    Keys are matched case-insensitively against :data:`_SECRET_SUBSTRINGS`.

    Args:
        logger: The wrapped logger instance (unused).
        method_name: The log method name (unused).
        event_dict: Mutable event dictionary being assembled.

    Returns:
        The event dict with sensitive values replaced by ``"[REDACTED]"``.
    """
    redacted = "[REDACTED]"
    for key in list(event_dict.keys()):
        key_lower = key.lower()
        if any(secret in key_lower for secret in _SECRET_SUBSTRINGS):
            event_dict[key] = redacted
            continue
        # Scan one level of nested dicts (e.g. headers={...}).
        val = event_dict[key]
        if isinstance(val, dict):
            for nested_key in list(val.keys()):
                if any(secret in nested_key.lower() for secret in _SECRET_SUBSTRINGS):
                    val[nested_key] = redacted
    return event_dict


def _inject_request_id(
    logger: WrappedLogger,  # noqa: ARG001
    method_name: str,  # noqa: ARG001
    event_dict: EventDict,
) -> EventDict:
    """Inject the current request ID into the log event dict if set.

    This processor runs after ``merge_contextvars`` so it acts as a fallback
    for any code path that uses the ``ContextVar`` directly rather than
    structlog's ``bind_contextvars``.

    Args:
        logger: The wrapped logger instance (unused).
        method_name: The log method name (e.g. ``"info"``). Unused.
        event_dict: Mutable event dictionary being assembled.

    Returns:
        The event dict, possibly with ``request_id`` added.
    """
    rid = request_id_var.get()
    if rid is not None and "request_id" not in event_dict:
        event_dict["request_id"] = rid
    return event_dict


# ---------------------------------------------------------------------------
# Public configuration entry-point
# ---------------------------------------------------------------------------


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog with JSON output for production.

    In production (log_level != ``"DEBUG"``), outputs newline-delimited JSON
    suitable for log aggregators (Loki, Datadog, CloudWatch, etc.).

    In development (log_level == ``"DEBUG"``), uses structlog's
    ``ConsoleRenderer`` for human-readable coloured output.

    Standard fields added to every log record:

    - ``timestamp``: ISO 8601 string.
    - ``level``: Log level name (``"info"``, ``"warning"``, etc.).
    - ``logger``: Module name that emitted the record.
    - ``request_id``: Current HTTP request ID (or omitted if not in a
      request context).
    - ``event``: The log message string.

    This function is idempotent — calling it multiple times is safe because
    structlog replaces its own configuration each call.

    Args:
        log_level: Logging verbosity string.  One of ``"DEBUG"``, ``"INFO"``,
            ``"WARNING"``, ``"ERROR"``, ``"CRITICAL"``.  Case-insensitive.
    """
    level_upper = log_level.upper()
    numeric_level = getattr(logging, level_upper, logging.INFO)
    is_development = level_upper == "DEBUG"

    # ------------------------------------------------------------------
    # Shared pre-chain processors (run before the final renderer)
    # ------------------------------------------------------------------
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        _inject_request_id,
        _redact_secrets,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # ------------------------------------------------------------------
    # Final renderer — JSON for production, coloured console for dev
    # ------------------------------------------------------------------
    if is_development:
        final_renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer(
            colors=True,
        )
    else:
        final_renderer = structlog.processors.JSONRenderer()

    # ------------------------------------------------------------------
    # Configure stdlib logging so that ``logging.getLogger(__name__)``
    # calls are routed through structlog's ProcessorFormatter.
    # ------------------------------------------------------------------
    formatter = structlog.stdlib.ProcessorFormatter(
        # Processors run only on records that enter via stdlib logging.
        foreign_pre_chain=shared_processors,
        # Final formatter receives both structlog-native and stdlib records.
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            final_renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # Remove any previously attached handlers to avoid duplicate output
    # when configure_logging() is called more than once (e.g. in tests).
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(numeric_level)

    # Silence noisy libraries unless we are in DEBUG mode.
    if not is_development:
        for noisy_logger in ("uvicorn.access", "httpx", "httpcore"):
            logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    # ------------------------------------------------------------------
    # Configure structlog itself
    # ------------------------------------------------------------------
    structlog.configure(
        processors=shared_processors
        + [
            # Bridge from structlog's chain into stdlib so the formatter above
            # applies when code uses ``structlog.get_logger()``.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
