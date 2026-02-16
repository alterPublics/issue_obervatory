"""Unit tests for the structured logging configuration.

Verifies that ``configure_logging()`` produces well-formed output and that
the ``request_id_var`` context variable is correctly propagated.
"""

from __future__ import annotations

import json
import logging
import sys
from io import StringIO

import pytest

from issue_observatory.core.logging_config import configure_logging, request_id_var


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capture_log_output(log_level: str, message: str, **extra) -> str:
    """Emit a single log record and capture the raw text written to stdout.

    Args:
        log_level: Logging level string (e.g. ``"INFO"``).
        message: Log message to emit.
        **extra: Additional fields passed via ``extra=`` to the logger.

    Returns:
        The raw text captured from the stream handler's output.
    """
    configure_logging(log_level)

    # Replace the root handler's stream with our own StringIO buffer so we
    # can inspect what would have been written to stdout.
    buffer = StringIO()
    root = logging.getLogger()
    original_streams = []
    for handler in root.handlers:
        if hasattr(handler, "stream"):
            original_streams.append((handler, handler.stream))
            handler.stream = buffer

    logger = logging.getLogger("test.logging_config")
    logger.info(message, extra=extra if extra else {})

    # Flush and restore
    for handler, stream in original_streams:
        handler.flush()
        handler.stream = stream

    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConfigureLoggingJson:
    """Verify INFO-level (production) JSON output."""

    def test_logging_produces_json(self) -> None:
        """configure_logging('INFO') emits valid JSON for each log record."""
        output = _capture_log_output("INFO", "test_message_json")

        # Each line should be parseable JSON
        lines = [line for line in output.strip().splitlines() if line.strip()]
        assert lines, "Expected at least one log line, got none"

        for line in lines:
            record = json.loads(line)
            assert isinstance(record, dict), f"Log line is not a JSON object: {line!r}"

    def test_json_contains_event_field(self) -> None:
        """Emitted JSON record contains an 'event' key with the log message."""
        output = _capture_log_output("INFO", "hello_world")

        lines = [line for line in output.strip().splitlines() if line.strip()]
        records = [json.loads(line) for line in lines]

        matching = [r for r in records if r.get("event") == "hello_world"]
        assert matching, (
            f"No record with event='hello_world' found in output: {output!r}"
        )

    def test_json_contains_required_fields(self) -> None:
        """Emitted JSON record contains timestamp, level, and logger fields."""
        output = _capture_log_output("INFO", "required_fields_test")

        lines = [line for line in output.strip().splitlines() if line.strip()]
        records = [json.loads(line) for line in lines]
        target = next(
            (r for r in records if r.get("event") == "required_fields_test"),
            None,
        )
        assert target is not None, "Expected log record not found"

        assert "timestamp" in target, f"'timestamp' missing from record: {target}"
        assert "level" in target, f"'level' missing from record: {target}"
        assert "logger" in target, f"'logger' missing from record: {target}"

    def test_json_level_value_is_lowercase(self) -> None:
        """The 'level' field uses lowercase (e.g. 'info', not 'INFO')."""
        output = _capture_log_output("INFO", "level_case_test")

        lines = [line for line in output.strip().splitlines() if line.strip()]
        records = [json.loads(line) for line in lines]
        target = next(
            (r for r in records if r.get("event") == "level_case_test"),
            None,
        )
        assert target is not None
        assert target["level"] == "info", (
            f"Expected lowercase 'info', got {target['level']!r}"
        )


class TestRequestIdContextVar:
    """Verify that the request_id ContextVar is propagated into log records."""

    def test_request_id_appears_in_json_output(self) -> None:
        """Setting request_id_var before logging includes it in the JSON record."""
        test_request_id = "test-req-1234"
        token = request_id_var.set(test_request_id)

        try:
            output = _capture_log_output("INFO", "request_id_propagation_test")
        finally:
            request_id_var.reset(token)

        lines = [line for line in output.strip().splitlines() if line.strip()]
        records = [json.loads(line) for line in lines]
        target = next(
            (r for r in records if r.get("event") == "request_id_propagation_test"),
            None,
        )
        assert target is not None, "Expected log record not found"
        assert target.get("request_id") == test_request_id, (
            f"Expected request_id={test_request_id!r}, got {target.get('request_id')!r}"
        )

    def test_no_request_id_when_var_unset(self) -> None:
        """When request_id_var is not set, 'request_id' is absent from the record."""
        # Ensure the var is cleared
        request_id_var.set(None)

        output = _capture_log_output("INFO", "no_request_id_test")

        lines = [line for line in output.strip().splitlines() if line.strip()]
        records = [json.loads(line) for line in lines]
        target = next(
            (r for r in records if r.get("event") == "no_request_id_test"),
            None,
        )
        assert target is not None
        # request_id should either be absent or explicitly None
        assert target.get("request_id") is None, (
            f"Expected no request_id, got {target.get('request_id')!r}"
        )


class TestConfigureLoggingIdempotent:
    """Verify configure_logging() is safe to call multiple times."""

    def test_calling_twice_does_not_duplicate_handlers(self) -> None:
        """Calling configure_logging() twice produces exactly one root handler."""
        configure_logging("INFO")
        handler_count_first = len(logging.getLogger().handlers)

        configure_logging("INFO")
        handler_count_second = len(logging.getLogger().handlers)

        assert handler_count_second == handler_count_first, (
            f"Handler count changed from {handler_count_first} to "
            f"{handler_count_second} after second configure_logging() call"
        )
        assert handler_count_second == 1, (
            f"Expected exactly 1 root handler, got {handler_count_second}"
        )
