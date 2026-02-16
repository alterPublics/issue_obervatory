"""Tests for the Threads arena collector.

Covers:
- collect_by_actors() — pagination via cursor
- collect_by_terms() at FREE tier — returns [] when no accounts configured, logs WARNING
- Engagement fields present on token-owner posts, absent for other users
- normalize() — content_type='reply' when is_reply=True
- MEDIUM tier raises NotImplementedError
- health_check() success and failure paths
- Danish character preservation (æ, ø, å)
- HTTP 429 -> ArenaRateLimitError

These tests run without a live database or network connection.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

# ---------------------------------------------------------------------------
# Env bootstrap (must run before any application imports)
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==")

from issue_observatory.arenas.base import Tier  # noqa: E402
from issue_observatory.arenas.threads.collector import ThreadsCollector  # noqa: E402
from issue_observatory.arenas.threads.config import (  # noqa: E402
    THREADS_API_BASE,
    THREADS_ME_ENDPOINT,
)
from issue_observatory.core.exceptions import ArenaRateLimitError  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "api_responses" / "threads"


def _load_user_threads_fixture() -> dict[str, Any]:
    """Load the recorded user threads fixture."""
    return json.loads((FIXTURES_DIR / "user_threads_response.json").read_text(encoding="utf-8"))


def _first_post() -> dict[str, Any]:
    """Return the first thread post from the fixture."""
    return _load_user_threads_fixture()["data"][0]


# ---------------------------------------------------------------------------
# Mock credential pool
# ---------------------------------------------------------------------------


def _make_mock_pool() -> Any:
    """Build a minimal mock CredentialPool returning a Threads credential."""
    pool = MagicMock()
    pool.acquire = AsyncMock(
        return_value={
            "id": "cred-threads-001",
            "access_token": "test-threads-access-token",
        }
    )
    pool.release = AsyncMock(return_value=None)
    return pool


# ---------------------------------------------------------------------------
# normalize() unit tests
# ---------------------------------------------------------------------------


class TestNormalize:
    def _collector(self) -> ThreadsCollector:
        return ThreadsCollector()

    def test_normalize_sets_platform_arena(self) -> None:
        """normalize() sets platform='threads', arena='social_media'."""
        collector = self._collector()
        result = collector.normalize(_first_post())

        assert result["platform"] == "threads"
        assert result["arena"] == "social_media"

    def test_normalize_content_type_post_when_not_reply(self) -> None:
        """normalize() sets content_type='post' when is_reply=False."""
        collector = self._collector()
        post = {**_first_post(), "is_reply": False}
        result = collector.normalize(post)

        assert result["content_type"] == "post"

    def test_normalize_content_type_reply_when_is_reply_true(self) -> None:
        """normalize() sets content_type='reply' when is_reply=True."""
        collector = self._collector()
        post = _load_user_threads_fixture()["data"][2]  # third item has is_reply=True
        result = collector.normalize(post)

        assert result["content_type"] == "reply"

    def test_normalize_platform_id_is_thread_id(self) -> None:
        """normalize() sets platform_id to the Threads thread ID."""
        collector = self._collector()
        result = collector.normalize(_first_post())

        assert result["platform_id"] == "17846368219941196"

    def test_normalize_text_content_from_text_field(self) -> None:
        """normalize() maps 'text' to text_content."""
        collector = self._collector()
        result = collector.normalize(_first_post())

        assert result["text_content"] == _first_post()["text"]

    def test_normalize_url_from_permalink(self) -> None:
        """normalize() maps 'permalink' to url."""
        collector = self._collector()
        result = collector.normalize(_first_post())

        assert result["url"] == "https://www.threads.net/@drdk/post/abc123"

    def test_normalize_engagement_fields_present_for_token_owner_post(self) -> None:
        """normalize() includes engagement fields for posts that have them."""
        collector = self._collector()
        post = _first_post()  # has views, likes, replies, reposts
        result = collector.normalize(post)

        assert result["views_count"] == 12500
        assert result["likes_count"] == 340
        assert result["comments_count"] == 47
        assert result["shares_count"] == 89

    def test_normalize_engagement_fields_none_for_other_users(self) -> None:
        """normalize() sets engagement fields to None when absent in raw post."""
        collector = self._collector()
        post = _load_user_threads_fixture()["data"][2]  # reply without engagement fields
        result = collector.normalize(post)

        assert result["views_count"] is None
        assert result["likes_count"] is None
        assert result["comments_count"] is None
        assert result["shares_count"] is None

    def test_normalize_published_at_from_timestamp(self) -> None:
        """normalize() maps 'timestamp' to published_at."""
        collector = self._collector()
        result = collector.normalize(_first_post())

        assert result["published_at"] is not None
        assert "2026-02-15" in result["published_at"]

    def test_normalize_author_display_name_from_username(self) -> None:
        """normalize() maps 'username' to author_display_name."""
        collector = self._collector()
        result = collector.normalize(_first_post())

        assert result["author_display_name"] == "drdk"

    def test_normalize_required_fields_always_present(self) -> None:
        """All required schema fields are present in normalized output."""
        collector = self._collector()
        result = collector.normalize(_first_post())

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field is None: {field}"

    def test_normalize_preserves_danish_characters_in_text(self) -> None:
        """æ, ø, å in post text survive normalize() without corruption."""
        collector = self._collector()
        result = collector.normalize(_first_post())

        assert "Grøn" in result["text_content"]
        assert "Ålborg" in result["text_content"]

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_handles_each_danish_character(self, char: str) -> None:
        """Each Danish character in post text survives normalize() without error."""
        collector = self._collector()
        post = {**_first_post(), "text": f"Indhold med {char} tegn i opslaget."}
        result = collector.normalize(post)

        assert char in result["text_content"]


# ---------------------------------------------------------------------------
# collect_by_actors() tests
# ---------------------------------------------------------------------------


class TestCollectByActors:
    @pytest.mark.asyncio
    async def test_collect_by_actors_returns_records(self) -> None:
        """collect_by_actors() returns normalized records from fixture."""
        fixture = _load_user_threads_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(f"{THREADS_API_BASE}/drdk/threads").mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = ThreadsCollector(credential_pool=pool)
            records = await collector.collect_by_actors(
                actor_ids=["drdk"], tier=Tier.FREE, max_results=10
            )

        assert isinstance(records, list)
        assert len(records) > 0
        assert records[0]["platform"] == "threads"

    @pytest.mark.asyncio
    async def test_collect_by_actors_pagination_via_cursor(self) -> None:
        """collect_by_actors() paginates by following the cursor in paging.cursors.after."""
        # First page returns data with a cursor; second page returns data without cursor.
        page1 = {
            "data": [
                {
                    "id": "1001",
                    "text": "Første opslag om grøn omstilling.",
                    "timestamp": "2026-02-15T10:00:00+0000",
                    "permalink": "https://www.threads.net/@drdk/post/p1",
                    "media_type": "TEXT",
                    "is_reply": False,
                    "username": "drdk",
                }
            ],
            "paging": {"cursors": {"before": "c_before", "after": "cursor_page2"}},
        }
        page2 = {
            "data": [
                {
                    "id": "1002",
                    "text": "Andet opslag om velfærdsstat og Ørsted.",
                    "timestamp": "2026-02-15T09:00:00+0000",
                    "permalink": "https://www.threads.net/@drdk/post/p2",
                    "media_type": "TEXT",
                    "is_reply": False,
                    "username": "drdk",
                }
            ],
            "paging": {"cursors": {"before": "c_before2", "after": None}},
        }
        pool = _make_mock_pool()

        call_count = 0

        def paginated_response(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(200, json=page1)
            return httpx.Response(200, json=page2)

        with respx.mock:
            respx.get(f"{THREADS_API_BASE}/drdk/threads").mock(
                side_effect=paginated_response
            )
            collector = ThreadsCollector(credential_pool=pool)
            records = await collector.collect_by_actors(
                actor_ids=["drdk"], tier=Tier.FREE, max_results=50
            )

        assert len(records) == 2
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_collect_by_actors_429_raises_rate_limit_error(self) -> None:
        """collect_by_actors() raises ArenaRateLimitError on HTTP 429."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(f"{THREADS_API_BASE}/drdk/threads").mock(
                return_value=httpx.Response(429, headers={"Retry-After": "60"})
            )
            collector = ThreadsCollector(credential_pool=pool)
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_actors(
                    actor_ids=["drdk"], tier=Tier.FREE, max_results=10
                )

    @pytest.mark.asyncio
    async def test_collect_by_actors_medium_tier_raises_not_implemented(self) -> None:
        """collect_by_actors() at MEDIUM tier raises NotImplementedError."""
        collector = ThreadsCollector()
        with pytest.raises(NotImplementedError):
            await collector.collect_by_actors(
                actor_ids=["drdk"], tier=Tier.MEDIUM, max_results=10
            )

    @pytest.mark.asyncio
    async def test_collect_by_actors_preserves_danish_text(self) -> None:
        """Danish characters in Threads posts survive the full collect → normalize pipeline."""
        fixture = _load_user_threads_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(f"{THREADS_API_BASE}/drdk/threads").mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = ThreadsCollector(credential_pool=pool)
            records = await collector.collect_by_actors(
                actor_ids=["drdk"], tier=Tier.FREE, max_results=10
            )

        texts = [r.get("text_content", "") or "" for r in records]
        assert any("Grøn" in t or "Ålborg" in t or "Ørsted" in t for t in texts)


# ---------------------------------------------------------------------------
# collect_by_terms() tests
# ---------------------------------------------------------------------------


class TestCollectByTerms:
    @pytest.mark.asyncio
    async def test_collect_by_terms_free_tier_empty_accounts_returns_empty_and_logs_warning(
        self, caplog: Any
    ) -> None:
        """collect_by_terms() at FREE tier with no accounts configured returns [] and logs WARNING."""
        collector = ThreadsCollector()

        with caplog.at_level(logging.WARNING, logger="issue_observatory.arenas.threads.collector"):
            with patch(
                "issue_observatory.arenas.threads.collector.DEFAULT_DANISH_THREADS_ACCOUNTS",
                [],
            ):
                records = await collector.collect_by_terms(
                    terms=["grøn omstilling"], tier=Tier.FREE, max_results=10
                )

        assert records == []
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("DEFAULT_DANISH_THREADS_ACCOUNTS" in r.message or
                   "no accounts" in r.message.lower() or
                   "empty" in r.message.lower()
                   for r in warning_records)

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_tier_raises_not_implemented(self) -> None:
        """collect_by_terms() at MEDIUM tier raises NotImplementedError."""
        collector = ThreadsCollector()
        with pytest.raises(NotImplementedError):
            await collector.collect_by_terms(
                terms=["test"], tier=Tier.MEDIUM, max_results=5
            )

    @pytest.mark.asyncio
    async def test_collect_by_terms_filters_by_text_match(self) -> None:
        """collect_by_terms() with configured accounts filters posts by term match."""
        fixture = _load_user_threads_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(f"{THREADS_API_BASE}/drdk/threads").mock(
                return_value=httpx.Response(200, json=fixture)
            )
            with patch(
                "issue_observatory.arenas.threads.collector.DEFAULT_DANISH_THREADS_ACCOUNTS",
                ["drdk"],
            ):
                collector = ThreadsCollector(credential_pool=pool)
                # Search for "grøn" which appears in the first post
                records = await collector.collect_by_terms(
                    terms=["grøn"], tier=Tier.FREE, max_results=10
                )

        assert isinstance(records, list)
        # All returned records should contain the search term
        for record in records:
            assert "grøn" in (record.get("text_content") or "").lower()


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_ok_when_me_endpoint_works(self) -> None:
        """health_check() returns status='ok' when /me endpoint returns username."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(THREADS_ME_ENDPOINT).mock(
                return_value=httpx.Response(
                    200, json={"id": "12345", "username": "drdk"}
                )
            )
            collector = ThreadsCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "social_media"
        assert result["platform"] == "threads"
        assert result.get("username") == "drdk"
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_down_when_no_credentials(self) -> None:
        """health_check() returns status='down' when no credential pool is configured."""
        collector = ThreadsCollector()  # no pool
        result = await collector.health_check()

        assert result["status"] == "down"
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_http_401(self) -> None:
        """health_check() returns status='down' on HTTP 401 (token expired)."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(THREADS_ME_ENDPOINT).mock(
                return_value=httpx.Response(401)
            )
            collector = ThreadsCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "down"
        assert "401" in result.get("detail", "")

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_on_http_5xx(self) -> None:
        """health_check() returns status='degraded' on server-side HTTP errors."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(THREADS_ME_ENDPOINT).mock(
                return_value=httpx.Response(503)
            )
            collector = ThreadsCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "degraded"
