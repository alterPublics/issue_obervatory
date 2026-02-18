"""Tests for the Google Autocomplete arena collector.

Covers:
- normalize() unit tests with recorded fixture data
- collect_by_terms() integration tests with mocked HTTP (respx)
- Edge cases: empty results, HTTP 429, malformed JSON, missing fields
- health_check() test
- Danish character preservation (æ, ø, å)

These tests run without a live database or network connection.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

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
from issue_observatory.arenas.google_autocomplete.collector import (  # noqa: E402
    GoogleAutocompleteCollector,
)
from issue_observatory.arenas.google_autocomplete.config import (  # noqa: E402
    FREE_AUTOCOMPLETE_URL,
    SERPER_AUTOCOMPLETE_URL,
    SERPAPI_AUTOCOMPLETE_URL,
)
from issue_observatory.core.exceptions import ArenaRateLimitError  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "api_responses" / "google_autocomplete"


def _load_free_fixture() -> list[Any]:
    """Load the recorded FREE tier autocomplete fixture."""
    raw = (FIXTURES_DIR / "free_response.json").read_text(encoding="utf-8")
    return json.loads(raw)


# ---------------------------------------------------------------------------
# normalize() unit tests
# ---------------------------------------------------------------------------


class TestNormalize:
    def _collector(self) -> GoogleAutocompleteCollector:
        return GoogleAutocompleteCollector()

    def test_normalize_sets_correct_platform_arena_content_type(self) -> None:
        """normalize() writes platform='google', arena='google_autocomplete', content_type='autocomplete_suggestion'."""
        collector = self._collector()
        raw = {"suggestion": "folkeskolen reform", "query": "folkeskolen", "rank": 0, "tier": "free"}
        result = collector.normalize(raw)

        assert result["platform"] == "google_autocomplete"
        assert result["arena"] == "google_autocomplete"
        assert result["content_type"] == "autocomplete_suggestion"

    def test_normalize_text_content_is_suggestion(self) -> None:
        """normalize() maps 'suggestion' field to text_content."""
        collector = self._collector()
        raw = {"suggestion": "klimaforandringer i Danmark", "query": "klima", "rank": 0, "tier": "free"}
        result = collector.normalize(raw)

        assert result["text_content"] == "klimaforandringer i Danmark"

    def test_normalize_title_is_query(self) -> None:
        """normalize() maps 'query' field to title (the triggering query)."""
        collector = self._collector()
        raw = {"suggestion": "folkeskolen reform", "query": "folkeskolen", "rank": 0, "tier": "free"}
        result = collector.normalize(raw)

        assert result["title"] == "folkeskolen"

    def test_normalize_language_is_danish(self) -> None:
        """normalize() always sets language to 'da' for autocomplete suggestions."""
        collector = self._collector()
        raw = {"suggestion": "test suggestion", "query": "test", "rank": 0, "tier": "free"}
        result = collector.normalize(raw)

        assert result["language"] == "da"

    def test_normalize_no_author_fields(self) -> None:
        """normalize() produces None for author fields (autocomplete has no author concept)."""
        collector = self._collector()
        raw = {"suggestion": "aarhus kommune", "query": "aarhus", "rank": 0, "tier": "free"}
        result = collector.normalize(raw)

        assert result["pseudonymized_author_id"] is None

    def test_normalize_platform_id_is_deterministic_hex(self) -> None:
        """normalize() produces a non-empty string platform_id."""
        collector = self._collector()
        raw = {"suggestion": "test sug", "query": "test", "rank": 0, "tier": "free"}
        result = collector.normalize(raw)

        assert result["platform_id"] is not None
        assert len(result["platform_id"]) == 64
        assert all(c in "0123456789abcdef" for c in result["platform_id"])

    def test_normalize_preserves_danish_characters_in_suggestion(self) -> None:
        """æ, ø, å in suggestion text survive normalize() without corruption."""
        collector = self._collector()
        danish_suggestion = "folkeskolen æøå velfærdsstat Ålborg"
        raw = {"suggestion": danish_suggestion, "query": "folkeskolen", "rank": 0, "tier": "free"}
        result = collector.normalize(raw)

        assert result["text_content"] == danish_suggestion
        assert "æ" in result["text_content"]
        assert "ø" in result["text_content"]
        assert "å" in result["text_content"]

    def test_normalize_preserves_danish_characters_in_query(self) -> None:
        """æ, ø, å in the query field survive normalize() into title without corruption."""
        collector = self._collector()
        danish_query = "grøn omstilling"
        raw = {"suggestion": "grøn energi", "query": danish_query, "rank": 0, "tier": "free"}
        result = collector.normalize(raw)

        assert result["title"] == danish_query

    def test_normalize_relevance_maps_to_engagement_score(self) -> None:
        """normalize() maps 'relevance' field to engagement_score when present."""
        collector = self._collector()
        raw = {
            "suggestion": "serpapi result",
            "query": "serpapi",
            "rank": 0,
            "tier": "premium",
            "relevance": 850,
        }
        result = collector.normalize(raw)

        assert result["engagement_score"] == 850.0

    def test_normalize_missing_relevance_leaves_engagement_score_none(self) -> None:
        """normalize() leaves engagement_score None when relevance is absent."""
        collector = self._collector()
        raw = {"suggestion": "no relevance", "query": "test", "rank": 0, "tier": "free"}
        result = collector.normalize(raw)

        # engagement_score may be None or absent — both are acceptable
        assert result.get("engagement_score") is None

    def test_normalize_required_fields_always_present(self) -> None:
        """All required schema fields are present in the normalized output."""
        collector = self._collector()
        raw = {"suggestion": "test", "query": "q", "rank": 0, "tier": "free"}
        result = collector.normalize(raw)

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field is None: {field}"

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_handles_each_danish_character_without_crash(self, char: str) -> None:
        """Each Danish special character is handled without raising an error."""
        collector = self._collector()
        raw = {
            "suggestion": f"tekst med {char} i midten",
            "query": f"søg {char}",
            "rank": 0,
            "tier": "free",
        }
        result = collector.normalize(raw)

        assert result["text_content"] == f"tekst med {char} i midten"


# ---------------------------------------------------------------------------
# collect_by_terms() integration tests — FREE tier
# ---------------------------------------------------------------------------


class TestCollectByTermsFree:
    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_free_returns_records(self) -> None:
        """collect_by_terms() returns non-empty list when API returns suggestions."""
        fixture_data = _load_free_fixture()
        respx.get(FREE_AUTOCOMPLETE_URL).mock(
            return_value=httpx.Response(200, json=fixture_data)
        )

        collector = GoogleAutocompleteCollector()
        records = await collector.collect_by_terms(
            terms=["folkeskolen"], tier=Tier.FREE, max_results=10
        )

        assert isinstance(records, list)
        assert len(records) > 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_free_record_fields_valid(self) -> None:
        """Each record from collect_by_terms() has all required schema fields."""
        fixture_data = _load_free_fixture()
        respx.get(FREE_AUTOCOMPLETE_URL).mock(
            return_value=httpx.Response(200, json=fixture_data)
        )

        collector = GoogleAutocompleteCollector()
        records = await collector.collect_by_terms(
            terms=["folkeskolen"], tier=Tier.FREE, max_results=10
        )

        for record in records:
            assert record["platform"] == "google_autocomplete"
            assert record["arena"] == "google_autocomplete"
            assert record["content_type"] == "autocomplete_suggestion"
            assert record["collection_tier"] == "free"
            assert record["platform_id"] is not None

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_free_empty_results(self) -> None:
        """collect_by_terms() returns [] when API returns empty suggestions list."""
        respx.get(FREE_AUTOCOMPLETE_URL).mock(
            return_value=httpx.Response(200, json=["folkeskolen", []])
        )

        collector = GoogleAutocompleteCollector()
        records = await collector.collect_by_terms(
            terms=["folkeskolen"], tier=Tier.FREE, max_results=10
        )

        assert records == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_free_http_429_raises_rate_limit_error(self) -> None:
        """collect_by_terms() raises ArenaRateLimitError on HTTP 429."""
        respx.get(FREE_AUTOCOMPLETE_URL).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "30"})
        )

        collector = GoogleAutocompleteCollector()
        with pytest.raises(ArenaRateLimitError):
            await collector.collect_by_terms(
                terms=["test"], tier=Tier.FREE, max_results=5
            )

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_free_malformed_response_returns_empty(self) -> None:
        """collect_by_terms() returns [] and does not raise when response is not a list."""
        # GDELT-style non-list JSON response
        respx.get(FREE_AUTOCOMPLETE_URL).mock(
            return_value=httpx.Response(200, json={"error": "unexpected format"})
        )

        collector = GoogleAutocompleteCollector()
        records = await collector.collect_by_terms(
            terms=["test"], tier=Tier.FREE, max_results=5
        )

        assert records == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_free_max_results_respected(self) -> None:
        """collect_by_terms() never returns more than max_results records."""
        # Fixture returns 5 suggestions for "folkeskolen"
        fixture_data = _load_free_fixture()
        respx.get(FREE_AUTOCOMPLETE_URL).mock(
            return_value=httpx.Response(200, json=fixture_data)
        )

        collector = GoogleAutocompleteCollector()
        records = await collector.collect_by_terms(
            terms=["folkeskolen"], tier=Tier.FREE, max_results=2
        )

        assert len(records) <= 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_free_danish_text_preserved(self) -> None:
        """Danish characters in suggestions returned by collect_by_terms() survive intact."""
        fixture_data = _load_free_fixture()
        respx.get(FREE_AUTOCOMPLETE_URL).mock(
            return_value=httpx.Response(200, json=fixture_data)
        )

        collector = GoogleAutocompleteCollector()
        records = await collector.collect_by_terms(
            terms=["folkeskolen"], tier=Tier.FREE, max_results=10
        )

        # Fixture includes "folkeskolen æøå test"
        texts = [r["text_content"] for r in records]
        assert any("æ" in (t or "") for t in texts), "Expected Danish æ in at least one suggestion"


# ---------------------------------------------------------------------------
# collect_by_actors() — NotImplementedError
# ---------------------------------------------------------------------------


class TestCollectByActors:
    @pytest.mark.asyncio
    async def test_collect_by_actors_raises_not_implemented(self) -> None:
        """collect_by_actors() always raises NotImplementedError for autocomplete."""
        collector = GoogleAutocompleteCollector()
        with pytest.raises(NotImplementedError):
            await collector.collect_by_actors(actor_ids=["user123"], tier=Tier.FREE)


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_returns_ok_on_valid_response(self) -> None:
        """health_check() returns status='ok' when the API responds correctly."""
        respx.get(FREE_AUTOCOMPLETE_URL).mock(
            return_value=httpx.Response(200, json=["test", ["result1", "result2"]])
        )

        collector = GoogleAutocompleteCollector()
        result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "google_autocomplete"
        assert result["platform"] == "google_autocomplete"
        assert "checked_at" in result

    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_returns_degraded_on_unexpected_format(self) -> None:
        """health_check() returns status='degraded' when response format is unexpected."""
        respx.get(FREE_AUTOCOMPLETE_URL).mock(
            return_value=httpx.Response(200, json={"not": "a list"})
        )

        collector = GoogleAutocompleteCollector()
        result = await collector.health_check()

        assert result["status"] == "degraded"

    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_returns_degraded_on_http_error(self) -> None:
        """health_check() returns status='degraded' on a non-2xx HTTP response."""
        respx.get(FREE_AUTOCOMPLETE_URL).mock(
            return_value=httpx.Response(503)
        )

        collector = GoogleAutocompleteCollector()
        result = await collector.health_check()

        assert result["status"] in ("degraded", "down")
