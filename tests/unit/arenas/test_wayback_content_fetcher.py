"""Unit tests for arenas/web/wayback/_content_fetcher.py (GR-12, W-01).

Covers:
- Importability of both public functions (W-01 circular-import guard)
- fetch_single_record_content() returns a failure record dict (not raise) on HTTP error
- The 500KB size guard skips text extraction and sets content_skipped_size_bytes
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Env bootstrap (must run before any application imports)
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault(
    "CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA=="
)


# ---------------------------------------------------------------------------
# W-01 — import guard
# ---------------------------------------------------------------------------


def test_wayback_content_fetcher_importable() -> None:
    """Verify _content_fetcher can be imported without circular import error.

    This test is the runtime verification recommended in the GR QA report (W-01).
    It confirms that the cross-module import from arenas into the scraper module
    does not create a circular dependency at import time.
    """
    from issue_observatory.arenas.web.wayback._content_fetcher import (  # noqa: PLC0415
        fetch_content_for_records,
        fetch_single_record_content,
    )

    assert callable(fetch_content_for_records)
    assert callable(fetch_single_record_content)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_semaphore() -> asyncio.Semaphore:
    """Return a real asyncio.Semaphore(1) suitable for testing."""
    return asyncio.Semaphore(1)


def _make_record_with_wayback_url(wayback_url: str = "https://web.archive.org/web/20240101000000id_/https://example.dk/") -> dict[str, Any]:
    """Return a minimal normalized CDX record dict with a wayback_url."""
    return {
        "id": "test-record-id-001",
        "platform": "wayback",
        "platform_id": "sha256-of-url",
        "text_content": None,
        "raw_metadata": {
            "wayback_url": wayback_url,
        },
    }


def _make_record_without_wayback_url() -> dict[str, Any]:
    """Return a normalized CDX record dict with no wayback_url."""
    return {
        "id": "test-record-id-002",
        "platform": "wayback",
        "platform_id": "sha256-of-url-2",
        "text_content": None,
        "raw_metadata": {},
    }


# ---------------------------------------------------------------------------
# fetch_single_record_content() — HTTP error path
# ---------------------------------------------------------------------------


class TestFetchSingleRecordContentHttpError:
    @pytest.mark.asyncio
    async def test_returns_failure_record_on_fetch_error(self) -> None:
        """fetch_single_record_content() records the error and returns the dict, not raises.

        When fetch_url raises an unexpected exception inside the semaphore block,
        the function must catch it, set raw_metadata['content_fetch_error'], and
        return the (mutated) record dict.
        """
        from issue_observatory.arenas.web.wayback._content_fetcher import (  # noqa: PLC0415
            fetch_single_record_content,
        )

        record = _make_record_with_wayback_url()
        semaphore = _make_semaphore()
        robots_cache: dict[str, bool] = {}

        mock_client = MagicMock()

        with patch(
            "issue_observatory.arenas.web.wayback._content_fetcher.fetch_url",
            new=AsyncMock(side_effect=RuntimeError("simulated network failure")),
        ):
            result = await fetch_single_record_content(
                record=record,
                client=mock_client,
                semaphore=semaphore,
                robots_cache=robots_cache,
            )

        # Must return the dict — not raise
        assert isinstance(result, dict)
        # Error must be recorded in raw_metadata
        assert "content_fetch_error" in result["raw_metadata"]
        error_msg: str = result["raw_metadata"]["content_fetch_error"]
        assert "simulated network failure" in error_msg or "unexpected error" in error_msg
        # text_content must still be None (no extraction attempted)
        assert result.get("text_content") is None

    @pytest.mark.asyncio
    async def test_returns_failure_record_on_http_error_response(self) -> None:
        """fetch_single_record_content() sets content_fetch_error on non-200 responses.

        When fetch_url returns a FetchResult with .error set (e.g. HTTP 404),
        the function must record the error string without raising.
        """
        from issue_observatory.arenas.web.wayback._content_fetcher import (  # noqa: PLC0415
            fetch_single_record_content,
        )

        record = _make_record_with_wayback_url()
        semaphore = _make_semaphore()
        robots_cache: dict[str, bool] = {}
        mock_client = MagicMock()

        # Simulate a FetchResult with an error (e.g. 404 response)
        mock_fetch_result = MagicMock()
        mock_fetch_result.error = "HTTP 404 Not Found"
        mock_fetch_result.html = None
        mock_fetch_result.status_code = 404

        with patch(
            "issue_observatory.arenas.web.wayback._content_fetcher.fetch_url",
            new=AsyncMock(return_value=mock_fetch_result),
        ):
            result = await fetch_single_record_content(
                record=record,
                client=mock_client,
                semaphore=semaphore,
                robots_cache=robots_cache,
            )

        assert isinstance(result, dict)
        assert "content_fetch_error" in result["raw_metadata"]
        assert result.get("text_content") is None

    @pytest.mark.asyncio
    async def test_returns_record_unchanged_when_no_wayback_url(self) -> None:
        """fetch_single_record_content() handles missing wayback_url gracefully.

        A record without raw_metadata['wayback_url'] must be returned immediately
        with content_fetch_error set — no network call attempted.
        """
        from issue_observatory.arenas.web.wayback._content_fetcher import (  # noqa: PLC0415
            fetch_single_record_content,
        )

        record = _make_record_without_wayback_url()
        semaphore = _make_semaphore()
        robots_cache: dict[str, bool] = {}
        mock_client = MagicMock()

        with patch(
            "issue_observatory.arenas.web.wayback._content_fetcher.fetch_url",
            new=AsyncMock(side_effect=AssertionError("fetch_url must not be called")),
        ):
            result = await fetch_single_record_content(
                record=record,
                client=mock_client,
                semaphore=semaphore,
                robots_cache=robots_cache,
            )

        assert isinstance(result, dict)
        assert "content_fetch_error" in result["raw_metadata"]
        assert "wayback_url" in result["raw_metadata"]["content_fetch_error"]


# ---------------------------------------------------------------------------
# fetch_single_record_content() — 500KB size guard
# ---------------------------------------------------------------------------


class TestFetchSingleRecordContentSizeGuard:
    @pytest.mark.asyncio
    async def test_size_guard_skips_extraction_and_sets_skipped_bytes(self) -> None:
        """fetch_single_record_content() skips extraction for responses > 500KB.

        When the HTML response body exceeds WB_CONTENT_FETCH_SIZE_LIMIT bytes,
        extraction must be skipped and raw_metadata['content_skipped_size_bytes']
        must be set to the actual byte count.  No text_content must be set.
        """
        from issue_observatory.arenas.web.wayback._content_fetcher import (  # noqa: PLC0415
            fetch_single_record_content,
        )
        from issue_observatory.arenas.web.wayback.config import (  # noqa: PLC0415
            WB_CONTENT_FETCH_SIZE_LIMIT,
        )

        # Generate HTML body that exceeds the size limit by 1 byte
        oversized_html = "x" * (WB_CONTENT_FETCH_SIZE_LIMIT + 1)
        assert len(oversized_html.encode("utf-8")) > WB_CONTENT_FETCH_SIZE_LIMIT

        record = _make_record_with_wayback_url()
        semaphore = _make_semaphore()
        robots_cache: dict[str, bool] = {}
        mock_client = MagicMock()

        # Successful fetch but oversized body
        mock_fetch_result = MagicMock()
        mock_fetch_result.error = None
        mock_fetch_result.html = oversized_html
        mock_fetch_result.status_code = 200

        with patch(
            "issue_observatory.arenas.web.wayback._content_fetcher.fetch_url",
            new=AsyncMock(return_value=mock_fetch_result),
        ), patch(
            "issue_observatory.arenas.web.wayback._content_fetcher.extract_from_html",
            side_effect=AssertionError("extract_from_html must not be called for oversized pages"),
        ):
            result = await fetch_single_record_content(
                record=record,
                client=mock_client,
                semaphore=semaphore,
                robots_cache=robots_cache,
            )

        assert isinstance(result, dict)
        # text_content must NOT be set — extraction was skipped
        assert result.get("text_content") is None
        # The skipped-size marker must be present
        assert "content_skipped_size_bytes" in result["raw_metadata"]
        skipped_bytes: int = result["raw_metadata"]["content_skipped_size_bytes"]
        assert skipped_bytes > WB_CONTENT_FETCH_SIZE_LIMIT

    @pytest.mark.asyncio
    async def test_size_guard_does_not_trigger_for_small_response(self) -> None:
        """fetch_single_record_content() proceeds with extraction for small responses.

        When the response body is within the size limit, the extraction path
        must be followed (no content_skipped_size_bytes set).
        """
        from issue_observatory.arenas.web.wayback._content_fetcher import (  # noqa: PLC0415
            fetch_single_record_content,
        )

        small_html = "<html><body><p>Grøn omstilling er vigtig for Danmark.</p></body></html>"

        record = _make_record_with_wayback_url()
        semaphore = _make_semaphore()
        robots_cache: dict[str, bool] = {}
        mock_client = MagicMock()

        mock_fetch_result = MagicMock()
        mock_fetch_result.error = None
        mock_fetch_result.html = small_html
        mock_fetch_result.status_code = 200

        extracted_mock = MagicMock()
        extracted_mock.text = "Grøn omstilling er vigtig for Danmark."
        extracted_mock.title = None
        extracted_mock.language = "da"

        with patch(
            "issue_observatory.arenas.web.wayback._content_fetcher.fetch_url",
            new=AsyncMock(return_value=mock_fetch_result),
        ), patch(
            "issue_observatory.arenas.web.wayback._content_fetcher.extract_from_html",
            return_value=extracted_mock,
        ):
            result = await fetch_single_record_content(
                record=record,
                client=mock_client,
                semaphore=semaphore,
                robots_cache=robots_cache,
            )

        assert isinstance(result, dict)
        # Size guard must NOT have triggered
        assert "content_skipped_size_bytes" not in result["raw_metadata"]
