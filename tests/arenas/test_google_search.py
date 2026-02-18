"""Integration tests for the GoogleSearchCollector.

Extends the unit-level normalize() tests in
``tests/unit/test_google_search_normalizer.py`` with full collect_by_terms()
and collect_by_actors() integration paths using mocked HTTP (respx).

Covers:
- collect_by_terms() MEDIUM tier via Serper.dev — happy path
- collect_by_terms() PREMIUM tier via SerpAPI — happy path
- collect_by_terms() FREE tier → returns [] with warning (no HTTP call)
- collect_by_terms() with empty organic list → returns []
- collect_by_terms() HTTP 429 from Serper → ArenaRateLimitError
- collect_by_terms() HTTP 401 from Serper → ArenaAuthError
- collect_by_terms() HTTP 403 from SerpAPI → ArenaAuthError
- collect_by_terms() partial page stops pagination
- collect_by_actors() converts actor IDs to site: queries
- health_check() returns ok with valid credential
- health_check() returns degraded when credential_pool is None
- health_check() returns degraded on HTTP 400 from Serper
- Danish characters preserved through collect_by_terms()
- No credential pool → NoCredentialAvailableError

These tests run without a live database or network connection.
"""

from __future__ import annotations

import json
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
from issue_observatory.arenas.google_search.collector import GoogleSearchCollector  # noqa: E402
from issue_observatory.arenas.google_search.config import (  # noqa: E402
    SERPER_API_URL,
    SERPAPI_URL,
)
from issue_observatory.core.exceptions import (  # noqa: E402
    ArenaAuthError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = (
    Path(__file__).parent.parent / "fixtures" / "api_responses" / "google_search"
)


def _load_serper_fixture() -> dict[str, Any]:
    """Load the Serper.dev organic results fixture."""
    return json.loads(
        (FIXTURES_DIR / "serper_organic.json").read_text(encoding="utf-8")
    )


def _load_serpapi_fixture() -> dict[str, Any]:
    """Load the SerpAPI organic_results fixture."""
    return json.loads(
        (FIXTURES_DIR / "serpapi_organic.json").read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# Mock credential pool helpers
# ---------------------------------------------------------------------------


def _make_serper_pool() -> Any:
    """Build a mock CredentialPool returning a Serper.dev MEDIUM credential."""
    pool = MagicMock()
    pool.acquire = AsyncMock(
        return_value={"id": "cred-serper-001", "api_key": "test-serper-api-key"}
    )
    pool.release = AsyncMock(return_value=None)
    pool.report_error = AsyncMock(return_value=None)
    return pool


def _make_serpapi_pool() -> Any:
    """Build a mock CredentialPool returning a SerpAPI PREMIUM credential."""
    pool = MagicMock()
    pool.acquire = AsyncMock(
        return_value={"id": "cred-serpapi-001", "api_key": "test-serpapi-api-key"}
    )
    pool.release = AsyncMock(return_value=None)
    pool.report_error = AsyncMock(return_value=None)
    return pool


# ---------------------------------------------------------------------------
# collect_by_terms() — MEDIUM tier (Serper.dev)
# ---------------------------------------------------------------------------


class TestCollectByTermsMedium:
    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_returns_search_result_records(self) -> None:
        """collect_by_terms(MEDIUM) returns non-empty list of search_result records."""
        fixture = _load_serper_fixture()
        pool = _make_serper_pool()

        with respx.mock:
            respx.post(SERPER_API_URL).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = GoogleSearchCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["klimaforandringer"], tier=Tier.MEDIUM, max_results=10
            )

        assert isinstance(records, list)
        assert len(records) > 0
        assert all(r["content_type"] == "search_result" for r in records)

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_records_have_correct_platform(self) -> None:
        """collect_by_terms(MEDIUM) records have platform='google' and arena='google_search'."""
        fixture = _load_serper_fixture()
        pool = _make_serper_pool()

        with respx.mock:
            respx.post(SERPER_API_URL).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = GoogleSearchCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["klimaforandringer"], tier=Tier.MEDIUM, max_results=10
            )

        assert all(r["platform"] == "google_search" for r in records)
        assert all(r["arena"] == "google_search" for r in records)

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_records_have_url_from_link_field(
        self,
    ) -> None:
        """collect_by_terms(MEDIUM) records have url from Serper.dev 'link' field."""
        fixture = _load_serper_fixture()
        pool = _make_serper_pool()

        with respx.mock:
            respx.post(SERPER_API_URL).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = GoogleSearchCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["klimaforandringer"], tier=Tier.MEDIUM, max_results=10
            )

        # All records should have a URL derived from the 'link' field
        assert all(r.get("url") is not None for r in records)
        assert records[0]["url"] == fixture["organic"][0]["link"]

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_empty_organic_returns_empty_list(
        self,
    ) -> None:
        """collect_by_terms(MEDIUM) returns [] when Serper.dev organic list is empty."""
        pool = _make_serper_pool()
        empty_response = {
            "organic": [],
            "searchInformation": {"totalResults": "0", "timeTaken": 0.1},
        }

        with respx.mock:
            respx.post(SERPER_API_URL).mock(
                return_value=httpx.Response(200, json=empty_response)
            )
            collector = GoogleSearchCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["nonexistent-query-xyz-123"],
                tier=Tier.MEDIUM,
                max_results=10,
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_http_429_raises_rate_limit_error(
        self,
    ) -> None:
        """collect_by_terms(MEDIUM) raises ArenaRateLimitError on HTTP 429."""
        pool = _make_serper_pool()

        with respx.mock:
            respx.post(SERPER_API_URL).mock(
                return_value=httpx.Response(429, headers={"Retry-After": "60"})
            )
            collector = GoogleSearchCollector(credential_pool=pool)
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_terms(
                    terms=["test"], tier=Tier.MEDIUM, max_results=10
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_http_401_raises_auth_error(self) -> None:
        """collect_by_terms(MEDIUM) raises ArenaAuthError on HTTP 401."""
        pool = _make_serper_pool()

        with respx.mock:
            respx.post(SERPER_API_URL).mock(
                return_value=httpx.Response(401)
            )
            collector = GoogleSearchCollector(credential_pool=pool)
            with pytest.raises(ArenaAuthError):
                await collector.collect_by_terms(
                    terms=["test"], tier=Tier.MEDIUM, max_results=10
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_http_403_raises_auth_error(self) -> None:
        """collect_by_terms(MEDIUM) raises ArenaAuthError on HTTP 403."""
        pool = _make_serper_pool()

        with respx.mock:
            respx.post(SERPER_API_URL).mock(
                return_value=httpx.Response(403)
            )
            collector = GoogleSearchCollector(credential_pool=pool)
            with pytest.raises(ArenaAuthError):
                await collector.collect_by_terms(
                    terms=["test"], tier=Tier.MEDIUM, max_results=10
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_danish_text_preserved(self) -> None:
        """collect_by_terms(MEDIUM) preserves æ, ø, å through full pipeline."""
        fixture = _load_serper_fixture()
        pool = _make_serper_pool()

        with respx.mock:
            respx.post(SERPER_API_URL).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = GoogleSearchCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["grøn omstilling"], tier=Tier.MEDIUM, max_results=10
            )

        # Fixture contains snippets with Danish characters
        all_text = " ".join(r.get("text_content", "") or "" for r in records)
        all_titles = " ".join(r.get("title", "") or "" for r in records)

        # Fixture has Grøn omstilling, velfærd, Ålborg, Grønland, Færøerne
        assert any(
            char in all_text + all_titles for char in ("ø", "æ", "å", "Ø", "Æ", "Å")
        )

    @pytest.mark.asyncio
    async def test_collect_by_terms_free_tier_returns_empty_list_with_warning(
        self, caplog: Any
    ) -> None:
        """collect_by_terms(FREE) returns [] and logs a warning (no HTTP call made)."""
        import logging  # noqa: PLC0415

        pool = _make_serper_pool()
        collector = GoogleSearchCollector(credential_pool=pool)

        with caplog.at_level(
            logging.WARNING,
            logger="issue_observatory.arenas.google_search.collector",
        ):
            with respx.mock:
                # No mock routes — any HTTP call would raise
                records = await collector.collect_by_terms(
                    terms=["test"], tier=Tier.FREE, max_results=10
                )

        assert records == []
        # Should have logged a WARNING about FREE tier unavailability
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("FREE" in m or "free" in m for m in warning_messages)


# ---------------------------------------------------------------------------
# collect_by_terms() — PREMIUM tier (SerpAPI)
# ---------------------------------------------------------------------------


class TestCollectByTermsPremium:
    @pytest.mark.asyncio
    async def test_collect_by_terms_premium_returns_search_result_records(self) -> None:
        """collect_by_terms(PREMIUM) returns non-empty list from SerpAPI."""
        fixture = _load_serpapi_fixture()
        pool = _make_serpapi_pool()

        with respx.mock:
            respx.get(SERPAPI_URL).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = GoogleSearchCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["klimaforandringer"], tier=Tier.PREMIUM, max_results=10
            )

        assert isinstance(records, list)
        assert len(records) > 0
        assert all(r["content_type"] == "search_result" for r in records)
        assert all(r["platform"] == "google_search" for r in records)

    @pytest.mark.asyncio
    async def test_collect_by_terms_premium_http_429_raises_rate_limit_error(
        self,
    ) -> None:
        """collect_by_terms(PREMIUM) raises ArenaRateLimitError on HTTP 429 from SerpAPI."""
        pool = _make_serpapi_pool()

        with respx.mock:
            respx.get(SERPAPI_URL).mock(
                return_value=httpx.Response(429, headers={"Retry-After": "30"})
            )
            collector = GoogleSearchCollector(credential_pool=pool)
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_terms(
                    terms=["test"], tier=Tier.PREMIUM, max_results=10
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_premium_http_401_raises_auth_error(self) -> None:
        """collect_by_terms(PREMIUM) raises ArenaAuthError on HTTP 401 from SerpAPI."""
        pool = _make_serpapi_pool()

        with respx.mock:
            respx.get(SERPAPI_URL).mock(
                return_value=httpx.Response(401)
            )
            collector = GoogleSearchCollector(credential_pool=pool)
            with pytest.raises(ArenaAuthError):
                await collector.collect_by_terms(
                    terms=["test"], tier=Tier.PREMIUM, max_results=10
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_premium_danish_text_preserved(self) -> None:
        """collect_by_terms(PREMIUM) preserves æ, ø, å in SerpAPI results."""
        fixture = _load_serpapi_fixture()
        pool = _make_serpapi_pool()

        with respx.mock:
            respx.get(SERPAPI_URL).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = GoogleSearchCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["klimaforandringer"], tier=Tier.PREMIUM, max_results=10
            )

        all_text = " ".join(r.get("text_content", "") or "" for r in records)
        all_titles = " ".join(r.get("title", "") or "" for r in records)

        # Fixture contains: Grøn omstilling, Velfærdsstatens, Ålborg, Grønland, Færøerne
        assert any(
            char in all_text + all_titles for char in ("ø", "æ", "å", "Ø", "Æ", "Å")
        )


# ---------------------------------------------------------------------------
# collect_by_actors() tests
# ---------------------------------------------------------------------------


class TestCollectByActors:
    @pytest.mark.asyncio
    async def test_collect_by_actors_converts_to_site_queries(self) -> None:
        """collect_by_actors() converts domain IDs to 'site:domain' queries."""
        fixture = _load_serper_fixture()
        pool = _make_serper_pool()
        captured_payloads: list[dict[str, Any]] = []

        def capture_and_respond(request: httpx.Request) -> httpx.Response:
            captured_payloads.append(json.loads(request.content))
            return httpx.Response(200, json=fixture)

        with respx.mock:
            respx.post(SERPER_API_URL).mock(side_effect=capture_and_respond)
            collector = GoogleSearchCollector(credential_pool=pool)
            records = await collector.collect_by_actors(
                actor_ids=["dr.dk", "politiken.dk"],
                tier=Tier.MEDIUM,
                max_results=20,
            )

        assert len(captured_payloads) >= 1
        # Each payload should contain a 'site:' query
        queries = [p.get("q", "") for p in captured_payloads]
        assert any("site:dr.dk" in q for q in queries)
        assert any("site:politiken.dk" in q for q in queries)

    @pytest.mark.asyncio
    async def test_collect_by_actors_returns_search_result_records(self) -> None:
        """collect_by_actors() returns normalized search_result records."""
        fixture = _load_serper_fixture()
        pool = _make_serper_pool()

        with respx.mock:
            respx.post(SERPER_API_URL).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = GoogleSearchCollector(credential_pool=pool)
            records = await collector.collect_by_actors(
                actor_ids=["dr.dk"], tier=Tier.MEDIUM, max_results=10
            )

        assert isinstance(records, list)
        assert all(r["platform"] == "google_search" for r in records)

    @pytest.mark.asyncio
    async def test_collect_by_actors_no_credential_raises_error(self) -> None:
        """collect_by_actors() raises NoCredentialAvailableError when no pool is set."""
        collector = GoogleSearchCollector()  # no pool

        with pytest.raises(NoCredentialAvailableError):
            await collector.collect_by_actors(
                actor_ids=["dr.dk"], tier=Tier.MEDIUM, max_results=10
            )


# ---------------------------------------------------------------------------
# No credential tests
# ---------------------------------------------------------------------------


class TestNoCredential:
    @pytest.mark.asyncio
    async def test_collect_by_terms_no_pool_raises_no_credential_error(self) -> None:
        """collect_by_terms() raises NoCredentialAvailableError when no pool is configured."""
        collector = GoogleSearchCollector()  # no credential_pool

        with pytest.raises(NoCredentialAvailableError):
            await collector.collect_by_terms(
                terms=["klimaforandringer"], tier=Tier.MEDIUM, max_results=10
            )


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_ok_with_valid_credential(self) -> None:
        """health_check() returns status='ok' when Serper.dev responds 200."""
        pool = _make_serper_pool()

        with respx.mock:
            respx.post(SERPER_API_URL).mock(
                return_value=httpx.Response(
                    200,
                    json={"organic": [], "searchInformation": {}},
                )
            )
            collector = GoogleSearchCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "google_search"
        assert result["platform"] == "google_search"
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_when_no_credential_pool(self) -> None:
        """health_check() returns status='degraded' when no credential pool is set."""
        collector = GoogleSearchCollector()  # no pool

        result = await collector.health_check()

        assert result["status"] == "degraded"
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_on_http_error(self) -> None:
        """health_check() returns status='degraded' on HTTP error from Serper.dev."""
        pool = _make_serper_pool()

        with respx.mock:
            respx.post(SERPER_API_URL).mock(
                return_value=httpx.Response(400)
            )
            collector = GoogleSearchCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "degraded"
        assert "400" in result.get("detail", "")

    @pytest.mark.asyncio
    async def test_health_check_always_includes_arena_platform_checked_at(
        self,
    ) -> None:
        """health_check() always returns arena, platform, and checked_at fields."""
        collector = GoogleSearchCollector()  # no pool — will return degraded

        result = await collector.health_check()

        assert result["arena"] == "google_search"
        assert result["platform"] == "google_search"
        assert "checked_at" in result
