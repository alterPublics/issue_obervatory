"""Tests for the GDELT arena collector.

Covers:
- normalize() unit tests with recorded fixture data
- collect_by_terms() integration tests with mocked HTTP (respx)
- Edge cases: empty results, HTTP 429, malformed JSON (HTML response), missing fields
- health_check() test
- Danish character preservation (æ, ø, å)

These tests run without a live database or network connection.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

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
from issue_observatory.arenas.gdelt.collector import GDELTCollector  # noqa: E402
from issue_observatory.arenas.gdelt.config import GDELT_DOC_API_BASE  # noqa: E402
from issue_observatory.core.exceptions import ArenaRateLimitError  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "api_responses" / "gdelt"


def _load_artlist_fixture() -> dict[str, Any]:
    """Load the recorded GDELT artlist fixture."""
    return json.loads((FIXTURES_DIR / "artlist_response.json").read_text(encoding="utf-8"))


def _fixture_first_article() -> dict[str, Any]:
    """Return the first article dict from the artlist fixture."""
    return _load_artlist_fixture()["articles"][0]


# ---------------------------------------------------------------------------
# normalize() unit tests
# ---------------------------------------------------------------------------


class TestNormalize:
    def _collector(self) -> GDELTCollector:
        return GDELTCollector()

    def test_normalize_sets_correct_platform_arena_content_type(self) -> None:
        """normalize() sets platform='gdelt', arena='news_media', content_type='article'."""
        collector = self._collector()
        result = collector.normalize(_fixture_first_article())

        assert result["platform"] == "gdelt"
        assert result["arena"] == "news_media"
        assert result["content_type"] == "article"

    def test_normalize_platform_id_is_url_sha256(self) -> None:
        """normalize() sets platform_id to SHA-256 of the article URL."""
        collector = self._collector()
        article = _fixture_first_article()
        result = collector.normalize(article)

        expected_id = hashlib.sha256(article["url"].encode("utf-8")).hexdigest()
        assert result["platform_id"] == expected_id

    def test_normalize_url_preserved(self) -> None:
        """normalize() maps 'url' field directly to the url output field."""
        collector = self._collector()
        article = _fixture_first_article()
        result = collector.normalize(article)

        assert result["url"] == article["url"]

    def test_normalize_title_preserved(self) -> None:
        """normalize() maps 'title' field to the title output field."""
        collector = self._collector()
        article = _fixture_first_article()
        result = collector.normalize(article)

        assert result["title"] == article["title"]

    def test_normalize_language_mapped_from_danish_to_da(self) -> None:
        """normalize() maps GDELT language 'Danish' to ISO code 'da'."""
        collector = self._collector()
        result = collector.normalize(_fixture_first_article())

        assert result["language"] == "da"

    def test_normalize_published_at_parsed_from_seendate(self) -> None:
        """normalize() parses GDELT seendate format to an ISO 8601 string."""
        collector = self._collector()
        result = collector.normalize(_fixture_first_article())

        assert result["published_at"] is not None
        assert "2026-02-15" in result["published_at"]

    def test_normalize_content_hash_is_url_based(self) -> None:
        """normalize() computes content_hash from the URL (GDELT has no article text)."""
        collector = self._collector()
        article = _fixture_first_article()
        result = collector.normalize(article)

        assert result["content_hash"] is not None
        assert len(result["content_hash"]) == 64

    def test_normalize_media_urls_from_social_image(self) -> None:
        """normalize() populates media_urls from the socialimage field."""
        collector = self._collector()
        article = _fixture_first_article()
        result = collector.normalize(article)

        assert isinstance(result["media_urls"], list)
        assert len(result["media_urls"]) >= 1
        assert result["media_urls"][0] == article["socialimage"]

    def test_normalize_no_social_image_produces_empty_media_urls(self) -> None:
        """normalize() produces empty media_urls when socialimage is absent."""
        collector = self._collector()
        article = dict(_load_artlist_fixture()["articles"][1])  # second article has no socialimage
        result = collector.normalize(article)

        assert result["media_urls"] == []

    def test_normalize_collection_tier_is_free(self) -> None:
        """normalize() sets collection_tier='free' (GDELT is unauthenticated)."""
        collector = self._collector()
        result = collector.normalize(_fixture_first_article())

        assert result["collection_tier"] == "free"

    def test_normalize_preserves_danish_characters_in_title(self) -> None:
        """æ, ø, å in GDELT article title survive normalize() without corruption."""
        collector = self._collector()
        danish_article = {
            "url": "https://dr.dk/groen-test",
            "title": "Grøn omstilling: Mette Frederiksen taler om velfærd i Ålborg",
            "seendate": "20260215T103000Z",
            "socialimage": None,
            "domain": "dr.dk",
            "language": "Danish",
            "sourcecountry": "DA",
            "tone": "0.5",
        }
        result = collector.normalize(danish_article)

        assert result["title"] == danish_article["title"]
        assert "ø" in result["title"]
        assert "æ" in result["title"]
        assert "Å" in result["title"]

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_handles_each_danish_character_in_title(self, char: str) -> None:
        """Each Danish character in title survives normalize() without error."""
        collector = self._collector()
        article = {
            "url": f"https://example.dk/char-{char}",
            "title": f"Artikel med {char} tegn i titlen",
            "seendate": "20260215T103000Z",
            "socialimage": None,
            "domain": "example.dk",
            "language": "Danish",
            "sourcecountry": "DA",
            "tone": "0.0",
        }
        result = collector.normalize(article)

        assert char in result["title"]

    def test_normalize_missing_url_produces_none_platform_id(self) -> None:
        """normalize() handles missing URL gracefully — platform_id is None."""
        collector = self._collector()
        article = {
            "url": None,
            "title": "Article without URL",
            "seendate": "20260215T103000Z",
            "socialimage": None,
            "domain": "unknown.dk",
            "language": "Danish",
            "sourcecountry": "DA",
        }
        result = collector.normalize(article)

        assert result["platform_id"] is None

    def test_normalize_required_fields_always_present(self) -> None:
        """All required schema fields are present in the normalized output."""
        collector = self._collector()
        result = collector.normalize(_fixture_first_article())

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field None: {field}"


# ---------------------------------------------------------------------------
# collect_by_terms() integration tests
# ---------------------------------------------------------------------------


class TestCollectByTerms:
    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_returns_non_empty_records(self) -> None:
        """collect_by_terms() returns non-empty list when API returns articles."""
        fixture = _load_artlist_fixture()

        # GDELT issues one query per term (sourcecountry:DA filter)
        respx.get(GDELT_DOC_API_BASE).mock(
            return_value=httpx.Response(
                200,
                json=fixture,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
        )

        # Patch _rate_limit_wait to avoid 1-second sleeps in tests
        with patch.object(GDELTCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)):
            collector = GDELTCollector()
            records = await collector.collect_by_terms(
                terms=["folkeskolen"], tier=Tier.FREE, max_results=10
            )

        assert isinstance(records, list)
        assert len(records) > 0
        assert records[0]["platform"] == "gdelt"
        assert records[0]["content_type"] == "article"

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_deduplicates_by_url(self) -> None:
        """collect_by_terms() deduplicates records with the same URL."""
        fixture = _load_artlist_fixture()  # both articles have unique URLs

        respx.get(GDELT_DOC_API_BASE).mock(
            return_value=httpx.Response(
                200,
                json=fixture,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
        )

        with patch.object(GDELTCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)):
            collector = GDELTCollector()
            records = await collector.collect_by_terms(
                terms=["test"], tier=Tier.FREE, max_results=100
            )

        # Each URL should appear only once
        urls = [r["url"] for r in records]
        assert len(urls) == len(set(urls)), "Expected deduplicated URLs"

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_empty_response_returns_empty_list(self) -> None:
        """collect_by_terms() returns [] when API returns no articles."""
        respx.get(GDELT_DOC_API_BASE).mock(
            return_value=httpx.Response(
                200,
                json={"articles": []},
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
        )

        with patch.object(GDELTCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)):
            collector = GDELTCollector()
            records = await collector.collect_by_terms(
                terms=["obscure_query_no_results"], tier=Tier.FREE, max_results=10
            )

        assert records == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_http_429_raises_rate_limit_error(self) -> None:
        """collect_by_terms() raises ArenaRateLimitError on HTTP 429 from GDELT."""
        respx.get(GDELT_DOC_API_BASE).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "60"})
        )

        with patch.object(GDELTCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)):
            collector = GDELTCollector()
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_terms(
                    terms=["test"], tier=Tier.FREE, max_results=5
                )

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_html_response_returns_empty(self) -> None:
        """collect_by_terms() returns [] and does not raise when API returns HTML (not JSON)."""
        respx.get(GDELT_DOC_API_BASE).mock(
            return_value=httpx.Response(
                200,
                text="<html><body>Server error</body></html>",
                headers={"Content-Type": "text/html; charset=utf-8"},
            )
        )

        with patch.object(GDELTCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)):
            collector = GDELTCollector()
            records = await collector.collect_by_terms(
                terms=["test"], tier=Tier.FREE, max_results=5
            )

        assert records == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_danish_text_preserved_end_to_end(self) -> None:
        """Danish characters in GDELT titles survive the full collect → normalize pipeline."""
        fixture = _load_artlist_fixture()

        respx.get(GDELT_DOC_API_BASE).mock(
            return_value=httpx.Response(
                200,
                json=fixture,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
        )

        with patch.object(GDELTCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)):
            collector = GDELTCollector()
            records = await collector.collect_by_terms(
                terms=["folkeskolen"], tier=Tier.FREE, max_results=10
            )

        # Fixture title: "Grøn omstilling: Mette Frederiksen vil investere i folkeskolen"
        titles = [r.get("title", "") or "" for r in records]
        assert any("ø" in t for t in titles), "Expected 'ø' in at least one article title"
        assert any("Frederiksen" in t for t in titles)

    @pytest.mark.asyncio
    async def test_collect_by_terms_malformed_json_returns_empty(self) -> None:
        """collect_by_terms() returns [] when JSON parsing fails on API response."""
        with respx.mock:
            respx.get(GDELT_DOC_API_BASE).mock(
                return_value=httpx.Response(
                    200,
                    content=b"} NOT VALID JSON {",
                    headers={"Content-Type": "application/json"},
                )
            )
            with patch.object(GDELTCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)):
                collector = GDELTCollector()
                records = await collector.collect_by_terms(
                    terms=["test"], tier=Tier.FREE, max_results=5
                )

        assert records == []


# ---------------------------------------------------------------------------
# collect_by_actors() — NotImplementedError
# ---------------------------------------------------------------------------


class TestCollectByActors:
    @pytest.mark.asyncio
    async def test_collect_by_actors_raises_not_implemented(self) -> None:
        """collect_by_actors() always raises NotImplementedError for GDELT."""
        collector = GDELTCollector()
        with pytest.raises(NotImplementedError):
            await collector.collect_by_actors(actor_ids=["dr.dk"], tier=Tier.FREE)


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_returns_ok_on_valid_response(self) -> None:
        """health_check() returns status='ok' when GDELT API responds with articles."""
        respx.get(GDELT_DOC_API_BASE).mock(
            return_value=httpx.Response(
                200,
                json={"articles": [{"url": "https://test.dk/1", "title": "Test"}]},
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
        )

        collector = GDELTCollector()
        result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "gdelt"
        assert result["platform"] == "gdelt"
        assert "checked_at" in result

    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_returns_degraded_on_non_json_response(self) -> None:
        """health_check() returns degraded when response is HTML (not JSON)."""
        respx.get(GDELT_DOC_API_BASE).mock(
            return_value=httpx.Response(
                200,
                text="<html>error</html>",
                headers={"Content-Type": "text/html"},
            )
        )

        collector = GDELTCollector()
        result = await collector.health_check()

        assert result["status"] == "degraded"

    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_returns_down_on_server_error(self) -> None:
        """health_check() returns down on HTTP 5xx server error."""
        respx.get(GDELT_DOC_API_BASE).mock(
            return_value=httpx.Response(503)
        )

        collector = GDELTCollector()
        result = await collector.health_check()

        assert result["status"] == "down"

    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_returns_degraded_on_400_error(self) -> None:
        """health_check() returns degraded on HTTP 4xx client error."""
        respx.get(GDELT_DOC_API_BASE).mock(
            return_value=httpx.Response(400)
        )

        collector = GDELTCollector()
        result = await collector.health_check()

        assert result["status"] == "degraded"
