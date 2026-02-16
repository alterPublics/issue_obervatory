"""Tests for the Event Registry arena collector.

Covers:
- normalize() unit tests: ISO 639-3 'dan' -> ISO 639-1 'da' language mapping
- normalize() text_content from article body field
- collect_by_terms() with mocked HTTP (respx)
- collect_by_actors() with concept URI parameter
- Token budget: WARNING at 20%, ArenaCollectionError at 5%
- HTTP 402 -> ArenaCollectionError (budget exhausted)
- Danish article text in text_content
- health_check() reports remaining_tokens
- Edge cases: missing fields, empty results, HTTP 429

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
from issue_observatory.arenas.event_registry.collector import EventRegistryCollector  # noqa: E402
from issue_observatory.arenas.event_registry.config import (  # noqa: E402
    EVENT_REGISTRY_ARTICLE_ENDPOINT,
)
from issue_observatory.core.exceptions import (  # noqa: E402
    ArenaCollectionError,
    ArenaRateLimitError,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "api_responses" / "event_registry"


def _load_articles_fixture() -> dict[str, Any]:
    """Load the recorded getArticles fixture."""
    return json.loads((FIXTURES_DIR / "get_articles_response.json").read_text(encoding="utf-8"))


def _first_article() -> dict[str, Any]:
    """Return the first article dict from the fixture."""
    return _load_articles_fixture()["articles"]["results"][0]


# ---------------------------------------------------------------------------
# Mock credential pool
# ---------------------------------------------------------------------------


def _make_mock_pool() -> Any:
    """Build a minimal mock CredentialPool returning an Event Registry credential."""
    pool = MagicMock()
    pool.acquire = AsyncMock(
        return_value={"id": "cred-er-001", "api_key": "test-er-api-key"}
    )
    pool.release = AsyncMock(return_value=None)
    pool.report_error = AsyncMock(return_value=None)
    return pool


# ---------------------------------------------------------------------------
# normalize() unit tests
# ---------------------------------------------------------------------------


class TestNormalize:
    def _collector(self) -> EventRegistryCollector:
        return EventRegistryCollector()

    def test_normalize_sets_platform_arena_content_type(self) -> None:
        """normalize() sets platform='event_registry', arena='news_media', content_type='article'."""
        collector = self._collector()
        result = collector.normalize(_first_article())

        assert result["platform"] == "event_registry"
        assert result["arena"] == "news_media"
        assert result["content_type"] == "article"

    def test_normalize_language_maps_dan_to_da(self) -> None:
        """normalize() maps ISO 639-3 'dan' to ISO 639-1 'da'."""
        collector = self._collector()
        result = collector.normalize(_first_article())

        assert result["language"] == "da"

    def test_normalize_language_mapping_preserves_unknown_codes(self) -> None:
        """normalize() falls back to first two chars for unmapped language codes."""
        collector = self._collector()
        article = {**_first_article(), "lang": "xyz"}
        result = collector.normalize(article)

        assert result["language"] == "xy"

    def test_normalize_platform_id_is_article_uri(self) -> None:
        """normalize() sets platform_id to the Event Registry article URI."""
        collector = self._collector()
        article = _first_article()
        result = collector.normalize(article)

        assert result["platform_id"] == article["uri"]

    def test_normalize_text_content_from_body_field(self) -> None:
        """normalize() maps article 'body' to text_content."""
        collector = self._collector()
        article = _first_article()
        result = collector.normalize(article)

        assert result["text_content"] == article["body"]
        assert "grøn omstilling" in result["text_content"].lower()

    def test_normalize_title_preserved(self) -> None:
        """normalize() maps article 'title' to title output field."""
        collector = self._collector()
        article = _first_article()
        result = collector.normalize(article)

        assert result["title"] == article["title"]

    def test_normalize_url_preserved(self) -> None:
        """normalize() maps 'url' field directly."""
        collector = self._collector()
        article = _first_article()
        result = collector.normalize(article)

        assert result["url"] == article["url"]

    def test_normalize_author_display_name_from_authors_list(self) -> None:
        """normalize() extracts first author name into author_display_name."""
        collector = self._collector()
        result = collector.normalize(_first_article())

        assert result["author_display_name"] == "Jakob Nielsen"

    def test_normalize_pseudonymized_author_id_set_when_author_present(self) -> None:
        """normalize() computes pseudonymized_author_id when author name is present."""
        collector = self._collector()
        result = collector.normalize(_first_article())

        assert result["pseudonymized_author_id"] is not None
        assert len(result["pseudonymized_author_id"]) == 64

    def test_normalize_no_authors_produces_none_fields(self) -> None:
        """normalize() sets author fields to None when authors list is empty."""
        collector = self._collector()
        article = {**_first_article(), "authors": []}
        result = collector.normalize(article)

        assert result["author_display_name"] is None
        assert result["pseudonymized_author_id"] is None

    def test_normalize_media_urls_from_image_field(self) -> None:
        """normalize() populates media_urls from the 'image' field."""
        collector = self._collector()
        result = collector.normalize(_first_article())

        assert isinstance(result["media_urls"], list)
        assert len(result["media_urls"]) == 1
        assert "dr.dk" in result["media_urls"][0]

    def test_normalize_no_image_produces_empty_media_urls(self) -> None:
        """normalize() produces empty media_urls when image is None."""
        collector = self._collector()
        article = _load_articles_fixture()["articles"]["results"][1]  # second has no image
        result = collector.normalize(article)

        assert result["media_urls"] == []

    def test_normalize_published_at_from_dateTimePub(self) -> None:
        """normalize() uses dateTimePub as published_at."""
        collector = self._collector()
        result = collector.normalize(_first_article())

        assert result["published_at"] is not None
        assert "2026-02-15" in result["published_at"]

    def test_normalize_content_hash_computed_from_url(self) -> None:
        """normalize() computes a non-None content_hash when URL is present."""
        collector = self._collector()
        result = collector.normalize(_first_article())

        assert result["content_hash"] is not None
        assert len(result["content_hash"]) == 64

    def test_normalize_raw_metadata_contains_nlp_fields(self) -> None:
        """normalize() stores NLP enrichments in raw_metadata dict."""
        collector = self._collector()
        result = collector.normalize(_first_article())

        meta = result.get("raw_metadata", {})
        assert isinstance(meta, dict)
        assert "sentiment" in meta
        assert "concepts" in meta
        assert "categories" in meta

    def test_normalize_required_fields_always_present(self) -> None:
        """All required schema fields are present in normalized output."""
        collector = self._collector()
        result = collector.normalize(_first_article())

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field is None: {field}"

    def test_normalize_preserves_danish_text_in_body(self) -> None:
        """æ, ø, å in article body survive normalize() without corruption."""
        collector = self._collector()
        result = collector.normalize(_first_article())

        assert "grøn omstilling" in result["text_content"].lower()
        assert "Ålborg" in result["text_content"]

    def test_normalize_preserves_danish_in_title(self) -> None:
        """Danish characters in article title survive normalize()."""
        collector = self._collector()
        result = collector.normalize(_first_article())

        assert "Grøn" in result["title"]
        assert "ø" in result["title"]

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_handles_each_danish_character_in_body(self, char: str) -> None:
        """Each Danish character in article body survives normalize() without error."""
        collector = self._collector()
        article = {
            **_first_article(),
            "body": f"Artikel med {char} tegn i brødteksten.",
        }
        result = collector.normalize(article)

        assert char in result["text_content"]


# ---------------------------------------------------------------------------
# collect_by_terms() integration tests
# ---------------------------------------------------------------------------


class TestCollectByTerms:
    @pytest.mark.asyncio
    async def test_collect_by_terms_returns_records(self) -> None:
        """collect_by_terms() returns non-empty list when API returns articles."""
        fixture = _load_articles_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(EVENT_REGISTRY_ARTICLE_ENDPOINT).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            with patch.object(EventRegistryCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)):
                collector = EventRegistryCollector(credential_pool=pool)
                records = await collector.collect_by_terms(
                    terms=["grøn omstilling"], tier=Tier.MEDIUM, max_results=10
                )

        assert isinstance(records, list)
        assert len(records) > 0
        assert records[0]["platform"] == "event_registry"
        assert records[0]["content_type"] == "article"

    @pytest.mark.asyncio
    async def test_collect_by_terms_records_have_danish_text(self) -> None:
        """collect_by_terms() results contain Danish characters in text_content."""
        fixture = _load_articles_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(EVENT_REGISTRY_ARTICLE_ENDPOINT).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            with patch.object(EventRegistryCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)):
                collector = EventRegistryCollector(credential_pool=pool)
                records = await collector.collect_by_terms(
                    terms=["velfærd"], tier=Tier.MEDIUM, max_results=10
                )

        texts = [r.get("text_content", "") or "" for r in records]
        assert any("ø" in t or "å" in t or "æ" in t for t in texts)

    @pytest.mark.asyncio
    async def test_collect_by_terms_empty_response_returns_empty_list(self) -> None:
        """collect_by_terms() returns [] when API returns no articles."""
        pool = _make_mock_pool()
        empty_response = {"articles": {"results": [], "totalResults": 0}}

        with respx.mock:
            respx.post(EVENT_REGISTRY_ARTICLE_ENDPOINT).mock(
                return_value=httpx.Response(200, json=empty_response)
            )
            with patch.object(EventRegistryCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)):
                collector = EventRegistryCollector(credential_pool=pool)
                records = await collector.collect_by_terms(
                    terms=["nonexistent query xyz"], tier=Tier.MEDIUM, max_results=10
                )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_429_raises_rate_limit_error(self) -> None:
        """collect_by_terms() raises ArenaRateLimitError on HTTP 429."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(EVENT_REGISTRY_ARTICLE_ENDPOINT).mock(
                return_value=httpx.Response(429, headers={"Retry-After": "60"})
            )
            with patch.object(EventRegistryCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)):
                collector = EventRegistryCollector(credential_pool=pool)
                with pytest.raises(ArenaRateLimitError):
                    await collector.collect_by_terms(
                        terms=["test"], tier=Tier.MEDIUM, max_results=5
                    )

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_402_raises_collection_error(self) -> None:
        """collect_by_terms() raises ArenaCollectionError on HTTP 402 (budget exhausted)."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(EVENT_REGISTRY_ARTICLE_ENDPOINT).mock(
                return_value=httpx.Response(402)
            )
            with patch.object(EventRegistryCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)):
                collector = EventRegistryCollector(credential_pool=pool)
                with pytest.raises(ArenaCollectionError):
                    await collector.collect_by_terms(
                        terms=["test"], tier=Tier.MEDIUM, max_results=5
                    )

    @pytest.mark.asyncio
    async def test_collect_by_terms_deduplicates_by_uri(self) -> None:
        """collect_by_terms() deduplicates articles with the same URI."""
        fixture = _load_articles_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(EVENT_REGISTRY_ARTICLE_ENDPOINT).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            with patch.object(EventRegistryCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)):
                collector = EventRegistryCollector(credential_pool=pool)
                records = await collector.collect_by_terms(
                    terms=["grøn", "velfærd"],  # two terms, same fixture returned
                    tier=Tier.MEDIUM,
                    max_results=100,
                )

        # No duplicate platform_ids
        ids = [r["platform_id"] for r in records]
        assert len(ids) == len(set(ids)), "Expected deduplicated platform_ids"


# ---------------------------------------------------------------------------
# collect_by_actors() with concept URI
# ---------------------------------------------------------------------------


class TestCollectByActors:
    @pytest.mark.asyncio
    async def test_collect_by_actors_passes_concept_uri_in_payload(self) -> None:
        """collect_by_actors() sends conceptUri in the request payload."""
        fixture = _load_articles_fixture()
        pool = _make_mock_pool()
        concept_uri = "http://en.wikipedia.org/wiki/Mette_Frederiksen"

        captured_payloads: list[dict] = []

        def capture_and_respond(request: httpx.Request) -> httpx.Response:
            captured_payloads.append(json.loads(request.content))
            return httpx.Response(200, json=fixture)

        with respx.mock:
            respx.post(EVENT_REGISTRY_ARTICLE_ENDPOINT).mock(
                side_effect=capture_and_respond
            )
            with patch.object(EventRegistryCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)):
                collector = EventRegistryCollector(credential_pool=pool)
                records = await collector.collect_by_actors(
                    actor_ids=[concept_uri], tier=Tier.MEDIUM, max_results=10
                )

        assert len(captured_payloads) >= 1
        assert captured_payloads[0]["conceptUri"] == concept_uri
        assert len(records) > 0

    @pytest.mark.asyncio
    async def test_collect_by_actors_returns_normalized_records(self) -> None:
        """collect_by_actors() returns list of normalized article dicts."""
        fixture = _load_articles_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(EVENT_REGISTRY_ARTICLE_ENDPOINT).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            with patch.object(EventRegistryCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)):
                collector = EventRegistryCollector(credential_pool=pool)
                records = await collector.collect_by_actors(
                    actor_ids=["http://en.wikipedia.org/wiki/Folketing"],
                    tier=Tier.MEDIUM,
                    max_results=10,
                )

        assert isinstance(records, list)
        assert all(r["platform"] == "event_registry" for r in records)


# ---------------------------------------------------------------------------
# Token budget tests
# ---------------------------------------------------------------------------


class TestTokenBudget:
    def test_token_budget_warning_logged_at_20_pct(self, caplog: Any) -> None:
        """_check_token_budget() emits WARNING when remaining tokens below 20%."""
        collector = EventRegistryCollector()
        # MEDIUM tier: max_results_per_run=5000, tokens=5000/100=50
        # 20% of 50 = 10, so remaining=10 should trigger WARNING
        response_data = {"remainingTokens": 8}  # below 20%

        with caplog.at_level(logging.WARNING, logger="issue_observatory.arenas.event_registry.collector"):
            # should NOT raise (only warning)
            # but at 5% = 2.5, value of 8 is above critical (2) but below warning (10)
            try:
                collector._check_token_budget(response_data, Tier.MEDIUM)
            except ArenaCollectionError:
                pass  # only raised at critical threshold

        # Check the logger recorded a warning (at 8 tokens, between 5% and 20%)
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warning_records) > 0

    def test_token_budget_critical_raises_collection_error(self) -> None:
        """_check_token_budget() raises ArenaCollectionError when remaining below 5%."""
        collector = EventRegistryCollector()
        # MEDIUM tier: monthly_budget = 5000 // 100 = 50; 5% of 50 = 2.5
        # remaining=1 is below critical threshold
        response_data = {"remainingTokens": 1}

        with pytest.raises(ArenaCollectionError):
            collector._check_token_budget(response_data, Tier.MEDIUM)

    def test_token_budget_ok_does_not_raise(self) -> None:
        """_check_token_budget() does not raise when tokens are plentiful."""
        collector = EventRegistryCollector()
        response_data = {"remainingTokens": 4500}

        # Should not raise or log warning
        collector._check_token_budget(response_data, Tier.MEDIUM)

    def test_token_budget_none_skipped(self) -> None:
        """_check_token_budget() silently skips when remainingTokens is absent."""
        collector = EventRegistryCollector()
        # Should not raise
        collector._check_token_budget({}, Tier.MEDIUM)

    @pytest.mark.asyncio
    async def test_collect_by_terms_raises_when_critical_budget_in_response(self) -> None:
        """collect_by_terms() raises ArenaCollectionError when response has critical budget."""
        pool = _make_mock_pool()
        fixture = _load_articles_fixture()
        # Override remaining tokens to 1 (critical)
        critical_fixture = {**fixture, "remainingTokens": 1}

        with respx.mock:
            respx.post(EVENT_REGISTRY_ARTICLE_ENDPOINT).mock(
                return_value=httpx.Response(200, json=critical_fixture)
            )
            with patch.object(EventRegistryCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)):
                collector = EventRegistryCollector(credential_pool=pool)
                with pytest.raises(ArenaCollectionError):
                    await collector.collect_by_terms(
                        terms=["test"], tier=Tier.MEDIUM, max_results=10
                    )


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_ok_and_reports_remaining_tokens(self) -> None:
        """health_check() returns status='ok' and includes remaining_tokens."""
        pool = _make_mock_pool()
        fixture = _load_articles_fixture()  # has remainingTokens: 4800

        with respx.mock:
            respx.post(EVENT_REGISTRY_ARTICLE_ENDPOINT).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = EventRegistryCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "news_media"
        assert result["platform"] == "event_registry"
        assert "remaining_tokens" in result
        assert result["remaining_tokens"] == 4800

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_http_401(self) -> None:
        """health_check() returns status='down' on HTTP 401 (invalid API key)."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(EVENT_REGISTRY_ARTICLE_ENDPOINT).mock(
                return_value=httpx.Response(401)
            )
            collector = EventRegistryCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "down"
        assert "401" in result.get("detail", "") or "key" in result.get("detail", "").lower()

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_http_402(self) -> None:
        """health_check() returns status='down' on HTTP 402 (budget exhausted)."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(EVENT_REGISTRY_ARTICLE_ENDPOINT).mock(
                return_value=httpx.Response(402)
            )
            collector = EventRegistryCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "down"

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_no_credential(self) -> None:
        """health_check() returns status='down' when no credential pool is configured."""
        # Without credential pool and without env vars set
        collector = EventRegistryCollector()  # no pool, no env key
        result = await collector.health_check()

        assert result["status"] == "down"
        assert "checked_at" in result
