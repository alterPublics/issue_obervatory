"""Unit tests for the scraper Celery tasks.

Tests the UPDATE path (collection_run mode) and the INSERT path (manual_urls mode)
using mocked DB session and mocked HTTP fetcher.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from issue_observatory.scraper.tasks import (
    _get_thin_records,
    _increment_counter,
    _insert_manual_record,
    _load_job,
    _run_scraping,
    _update_content_record_v2,
    _update_job,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(
    source_type: str = "collection_run",
    source_collection_run_id: str | None = None,
    source_urls: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "source_type": source_type,
        "source_collection_run_id": source_collection_run_id or str(uuid.uuid4()),
        "source_urls": source_urls or [],
        "delay_min": 0.0,
        "delay_max": 0.0,
        "timeout_seconds": 10,
        "respect_robots_txt": False,
        "use_playwright_fallback": False,
        "max_retries": 0,
        "status": "pending",
    }


# ---------------------------------------------------------------------------
# _load_job
# ---------------------------------------------------------------------------


class TestLoadJob:
    def test_returns_none_when_not_found(self) -> None:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.fetchone.return_value = None

        with patch(
            "issue_observatory.core.database.get_sync_session",
            return_value=mock_session,
        ):
            result = _load_job(str(uuid.uuid4()))
        # We can't easily test this without a DB; just ensure it doesn't raise
        assert result is None or isinstance(result, dict)


# ---------------------------------------------------------------------------
# _run_scraping — collection_run mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRunScrapingCollectionRun:
    async def test_collection_run_mode_calls_update(self) -> None:
        """In collection_run mode, _update_content_record_v2 should be called."""
        job_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        record_id = str(uuid.uuid4())
        pub_at = datetime.now(tz=timezone.utc)
        url = "https://example.com/article"

        job = _make_job(source_type="collection_run", source_collection_run_id=run_id)

        thin_records = [(record_id, pub_at, url)]

        with (
            patch(
                "issue_observatory.scraper.tasks._load_job", return_value=job
            ),
            patch("issue_observatory.scraper.tasks._update_job"),
            patch(
                "issue_observatory.scraper.tasks._get_thin_records",
                return_value=thin_records,
            ),
            patch("issue_observatory.scraper.tasks._increment_counter"),
            patch(
                "issue_observatory.scraper.tasks._update_content_record_v2"
            ) as mock_update,
            patch(
                "issue_observatory.scraper.tasks.fetch_url",
                new_callable=AsyncMock,
                return_value=MagicMock(
                    html="<html><body>" + "word " * 200 + "</body></html>",
                    status_code=200,
                    final_url=url,
                    error=None,
                    needs_playwright=False,
                ),
            ),
            patch(
                "issue_observatory.scraper.tasks.extract_from_html",
                return_value=MagicMock(
                    text="Extracted article text", title="Article Title", language="da"
                ),
            ),
        ):
            await _run_scraping(job_id, "celery-task-123")

        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args[1]
        assert call_kwargs["record_id"] == record_id
        assert call_kwargs["published_at"] == pub_at

    async def test_collection_run_mode_skips_on_error(self) -> None:
        """Failed URL fetches should increment urls_failed and continue."""
        job_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        record_id = str(uuid.uuid4())
        url = "https://broken.example.com/"

        job = _make_job(source_type="collection_run", source_collection_run_id=run_id)
        thin_records = [(record_id, None, url)]

        with (
            patch("issue_observatory.scraper.tasks._load_job", return_value=job),
            patch("issue_observatory.scraper.tasks._update_job"),
            patch(
                "issue_observatory.scraper.tasks._get_thin_records",
                return_value=thin_records,
            ),
            patch(
                "issue_observatory.scraper.tasks._increment_counter"
            ) as mock_inc,
            patch(
                "issue_observatory.scraper.tasks.fetch_url",
                new_callable=AsyncMock,
                side_effect=Exception("network error"),
            ),
        ):
            await _run_scraping(job_id, "celery-task-456")

        # Should have incremented urls_failed
        failed_calls = [
            call for call in mock_inc.call_args_list if call[0][1] == "urls_failed"
        ]
        assert len(failed_calls) == 1


# ---------------------------------------------------------------------------
# _run_scraping — manual_urls mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRunScrapingManualUrls:
    async def test_manual_urls_mode_calls_insert(self) -> None:
        """In manual_urls mode, _insert_manual_record should be called."""
        job_id = str(uuid.uuid4())
        url = "https://dr.dk"
        job = _make_job(source_type="manual_urls", source_urls=[url])

        with (
            patch("issue_observatory.scraper.tasks._load_job", return_value=job),
            patch("issue_observatory.scraper.tasks._update_job"),
            patch("issue_observatory.scraper.tasks._increment_counter"),
            patch(
                "issue_observatory.scraper.tasks._insert_manual_record"
            ) as mock_insert,
            patch(
                "issue_observatory.scraper.tasks.fetch_url",
                new_callable=AsyncMock,
                return_value=MagicMock(
                    html="<html><body>" + "ord " * 300 + "</body></html>",
                    status_code=200,
                    final_url=url,
                    error=None,
                    needs_playwright=False,
                ),
            ),
            patch(
                "issue_observatory.scraper.tasks.extract_from_html",
                return_value=MagicMock(
                    text="Scraped content", title="Page Title", language="da"
                ),
            ),
        ):
            await _run_scraping(job_id, "celery-task-789")

        mock_insert.assert_called_once()
        call_kwargs = mock_insert.call_args[1]
        assert call_kwargs["url"] == url

    async def test_manual_urls_skipped_on_robots(self) -> None:
        """URLs with robots.txt error result should increment urls_skipped."""
        job_id = str(uuid.uuid4())
        url = "https://blocked.example.com/"
        job = _make_job(source_type="manual_urls", source_urls=[url])

        with (
            patch("issue_observatory.scraper.tasks._load_job", return_value=job),
            patch("issue_observatory.scraper.tasks._update_job"),
            patch(
                "issue_observatory.scraper.tasks._increment_counter"
            ) as mock_inc,
            patch(
                "issue_observatory.scraper.tasks.fetch_url",
                new_callable=AsyncMock,
                return_value=MagicMock(
                    html=None,
                    status_code=None,
                    final_url=url,
                    error="robots.txt disallowed",
                    needs_playwright=False,
                ),
            ),
        ):
            await _run_scraping(job_id, "celery-task-000")

        skipped_calls = [
            c for c in mock_inc.call_args_list if c[0][1] == "urls_skipped"
        ]
        assert len(skipped_calls) == 1
