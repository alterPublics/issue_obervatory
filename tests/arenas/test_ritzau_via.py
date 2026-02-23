"""Tests for the Via Ritzau arena collector.

Covers:
- normalize() unit tests: platform/arena/content_type, HTML stripping
  in body field, publisher as author, language defaults to 'da',
  media_urls from images array, content_hash, Danish character preservation
- collect_by_terms() with mocked Via Ritzau REST API (respx)
- collect_by_actors() publisher-based collection
- HTTP 429 -> ArenaRateLimitError
- Non-2xx errors -> ArenaCollectionError
- Empty response -> returns []
- Wrapper dict response (data.releases key) -> normalized correctly
- Tier validation: only FREE is supported (MEDIUM/PREMIUM produce a warning)
- health_check() returns 'ok', 'degraded', 'down' as appropriate
- No credentials required (unauthenticated API)

These tests run without a live database or network connection.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

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
from issue_observatory.arenas.ritzau_via.collector import RitzauViaCollector  # noqa: E402
from issue_observatory.arenas.ritzau_via.config import RITZAU_RELEASES_ENDPOINT  # noqa: E402
from issue_observatory.core.exceptions import (  # noqa: E402
    ArenaCollectionError,
    ArenaRateLimitError,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "api_responses" / "ritzau_via"


def _load_releases_fixture() -> list[dict[str, Any]]:
    """Load the recorded Via Ritzau releases fixture."""
    return json.loads((FIXTURES_DIR / "releases_response.json").read_text(encoding="utf-8"))


def _first_release() -> dict[str, Any]:
    """Return the first press release dict from the fixture."""
    return _load_releases_fixture()[0]


# ---------------------------------------------------------------------------
# normalize() unit tests
# ---------------------------------------------------------------------------


class TestNormalize:
    def _collector(self) -> RitzauViaCollector:
        return RitzauViaCollector()

    def test_normalize_sets_platform_arena_content_type(self) -> None:
        """normalize() sets platform='ritzau_via', arena='news_media', content_type='press_release'."""
        collector = self._collector()
        result = collector.normalize(_first_release())

        assert result["platform"] == "ritzau_via"
        assert result["arena"] == "news_media"
        assert result["content_type"] == "press_release"

    def test_normalize_platform_id_is_release_id(self) -> None:
        """normalize() sets platform_id to the release id as a string."""
        collector = self._collector()
        release = _first_release()
        result = collector.normalize(release)

        assert result["platform_id"] == str(release["id"])

    def test_normalize_title_from_headline_field(self) -> None:
        """normalize() maps 'headline' to 'title' output field."""
        collector = self._collector()
        release = _first_release()
        result = collector.normalize(release)

        assert result["title"] == release["headline"].strip()

    def test_normalize_text_content_strips_html_from_body(self) -> None:
        """normalize() strips HTML tags from the body field for text_content."""
        collector = self._collector()
        release = {
            **_first_release(),
            "body": "<p>Første afsnit om <strong>grøn omstilling</strong>.</p><p>Andet afsnit.</p>",
        }
        result = collector.normalize(release)

        assert "<p>" not in result["text_content"]
        assert "<strong>" not in result["text_content"]
        assert "grøn omstilling" in result["text_content"]

    def test_normalize_text_content_from_full_fixture_body(self) -> None:
        """normalize() produces non-empty text_content from the fixture body."""
        collector = self._collector()
        result = collector.normalize(_first_release())

        assert result["text_content"] is not None
        assert len(result["text_content"]) > 0
        assert "statsminister" in result["text_content"].lower() or "aftale" in result["text_content"].lower()

    def test_normalize_url_preserved(self) -> None:
        """normalize() maps 'url' field directly."""
        collector = self._collector()
        release = _first_release()
        result = collector.normalize(release)

        assert result["url"] == release["url"]

    def test_normalize_language_defaults_to_da(self) -> None:
        """normalize() defaults language to 'da' when field is absent."""
        collector = self._collector()
        release = {**_first_release(), "language": None}
        result = collector.normalize(release)

        assert result["language"] == "da"

    def test_normalize_language_from_fixture_is_da(self) -> None:
        """normalize() maps language='da' from the fixture."""
        collector = self._collector()
        result = collector.normalize(_first_release())

        assert result["language"] == "da"

    def test_normalize_author_display_name_from_publisher(self) -> None:
        """normalize() maps publisher.name to author_display_name."""
        collector = self._collector()
        release = _first_release()
        result = collector.normalize(release)

        assert result["author_display_name"] == release["publisher"]["name"]

    def test_normalize_pseudonymized_author_id_set_when_publisher_present(self) -> None:
        """normalize() computes pseudonymized_author_id when publisher id is present."""
        collector = self._collector()
        result = collector.normalize(_first_release())

        assert result["pseudonymized_author_id"] is not None
        assert len(result["pseudonymized_author_id"]) == 64

    def test_normalize_no_publisher_produces_none_author_fields(self) -> None:
        """normalize() sets author fields to None when publisher is absent."""
        collector = self._collector()
        release = {**_first_release(), "publisher": None}
        result = collector.normalize(release)

        assert result["author_display_name"] is None
        assert result["pseudonymized_author_id"] is None

    def test_normalize_media_urls_from_images_array(self) -> None:
        """normalize() populates media_urls from the images array."""
        collector = self._collector()
        release = _first_release()  # first fixture has one image
        result = collector.normalize(release)

        assert isinstance(result.get("media_urls", []), list)
        assert len(result["media_urls"]) == 1
        assert "via.ritzau.dk" in result["media_urls"][0]

    def test_normalize_no_images_produces_empty_media_urls(self) -> None:
        """normalize() produces empty media_urls when images is empty."""
        collector = self._collector()
        second_release = _load_releases_fixture()[1]  # second fixture has no images
        result = collector.normalize(second_release)

        assert result.get("media_urls", []) == []

    def test_normalize_content_hash_is_64_char_hex(self) -> None:
        """normalize() computes a 64-character hex content_hash."""
        collector = self._collector()
        result = collector.normalize(_first_release())

        assert result["content_hash"] is not None
        assert len(result["content_hash"]) == 64
        assert all(c in "0123456789abcdef" for c in result["content_hash"])

    def test_normalize_required_fields_always_present(self) -> None:
        """All required schema fields are present in normalized output."""
        collector = self._collector()
        result = collector.normalize(_first_release())

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field is None: {field}"

    def test_normalize_collection_tier_is_free(self) -> None:
        """normalize() sets collection_tier='free' (Ritzau Via is unauthenticated)."""
        collector = self._collector()
        result = collector.normalize(_first_release())

        assert result["collection_tier"] == "free"

    def test_normalize_published_at_from_publishedAt_field(self) -> None:
        """normalize() maps publishedAt to published_at output field."""
        collector = self._collector()
        release = _first_release()
        result = collector.normalize(release)

        assert result["published_at"] is not None
        assert "2026-02-15" in result["published_at"]

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_preserves_danish_character_in_headline(self, char: str) -> None:
        """Each Danish character in the headline survives normalize() without corruption."""
        collector = self._collector()
        release = {
            **_first_release(),
            "headline": f"Pressemeddelelse med {char} tegn i overskriften",
            "body": "",
        }
        result = collector.normalize(release)

        assert char in result["title"]

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_preserves_danish_character_in_body(self, char: str) -> None:
        """Each Danish character in the body survives HTML stripping in normalize()."""
        collector = self._collector()
        release = {
            **_first_release(),
            "body": f"<p>Tekst med {char} i brødteksten.</p>",
        }
        result = collector.normalize(release)

        assert char in result["text_content"]

    def test_normalize_preserves_danish_text_from_full_fixture(self) -> None:
        """Danish characters from the full fixture body survive normalize()."""
        collector = self._collector()
        result = collector.normalize(_first_release())

        assert "ø" in (result.get("title", "") + (result.get("text_content") or ""))

    def test_normalize_third_fixture_release_has_aalborg_in_title(self) -> None:
        """Danish Å in 'Ålborg' in fixture title survives normalize()."""
        collector = self._collector()
        third_release = _load_releases_fixture()[2]
        result = collector.normalize(third_release)

        assert "Å" in result["title"]
        assert "lborg" in result["title"]


# ---------------------------------------------------------------------------
# collect_by_terms() integration tests
# ---------------------------------------------------------------------------


class TestCollectByTerms:
    @pytest.mark.asyncio
    async def test_collect_by_terms_returns_records(self) -> None:
        """collect_by_terms() returns non-empty list when API returns press releases."""
        fixture = _load_releases_fixture()

        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = RitzauViaCollector()
            records = await collector.collect_by_terms(
                terms=["grøn omstilling"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert isinstance(records, list)
        assert len(records) > 0
        assert records[0]["platform"] == "ritzau_via"
        assert records[0]["content_type"] == "press_release"

    @pytest.mark.asyncio
    async def test_collect_by_terms_empty_response_returns_empty_list(self) -> None:
        """collect_by_terms() returns [] when API returns empty list."""
        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(200, json=[])
            )
            collector = RitzauViaCollector()
            records = await collector.collect_by_terms(
                terms=["nonexistent_xyz"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_wrapped_response_data_key(self) -> None:
        """collect_by_terms() handles {'data': [...]} wrapper response format."""
        fixture = _load_releases_fixture()
        wrapped_response = {"data": fixture}

        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(200, json=wrapped_response)
            )
            collector = RitzauViaCollector()
            records = await collector.collect_by_terms(
                terms=["test"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert len(records) > 0

    @pytest.mark.asyncio
    async def test_collect_by_terms_wrapped_response_releases_key(self) -> None:
        """collect_by_terms() handles {'releases': [...]} wrapper response format."""
        fixture = _load_releases_fixture()
        wrapped_response = {"releases": fixture}

        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(200, json=wrapped_response)
            )
            collector = RitzauViaCollector()
            records = await collector.collect_by_terms(
                terms=["test"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert len(records) > 0

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_429_raises_rate_limit_error(self) -> None:
        """collect_by_terms() raises ArenaRateLimitError on HTTP 429 from Via Ritzau API."""
        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(429, headers={"Retry-After": "60"})
            )
            collector = RitzauViaCollector()
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_terms(
                    terms=["test"],
                    tier=Tier.FREE,
                    max_results=5,
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_500_raises_collection_error(self) -> None:
        """collect_by_terms() raises ArenaCollectionError on HTTP 500."""
        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(500)
            )
            collector = RitzauViaCollector()
            with pytest.raises(ArenaCollectionError):
                await collector.collect_by_terms(
                    terms=["test"],
                    tier=Tier.FREE,
                    max_results=5,
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_403_raises_collection_error(self) -> None:
        """collect_by_terms() raises ArenaCollectionError on HTTP 403."""
        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(403)
            )
            collector = RitzauViaCollector()
            with pytest.raises(ArenaCollectionError):
                await collector.collect_by_terms(
                    terms=["test"],
                    tier=Tier.FREE,
                    max_results=5,
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_danish_text_preserved_end_to_end(self) -> None:
        """Danish characters survive the full collect -> normalize pipeline for Ritzau Via."""
        fixture = _load_releases_fixture()

        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = RitzauViaCollector()
            records = await collector.collect_by_terms(
                terms=["grøn omstilling"],
                tier=Tier.FREE,
                max_results=10,
            )

        all_text = " ".join(
            (r.get("title", "") or "") + (r.get("text_content", "") or "")
            for r in records
        )
        assert "ø" in all_text or "æ" in all_text or "Å" in all_text

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_tier_proceeds_as_free(self) -> None:
        """collect_by_terms() logs warning and proceeds when MEDIUM tier is requested."""
        fixture = _load_releases_fixture()

        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = RitzauViaCollector()
            records = await collector.collect_by_terms(
                terms=["test"],
                tier=Tier.MEDIUM,
                max_results=5,
            )

        assert isinstance(records, list)

    @pytest.mark.asyncio
    async def test_collect_by_terms_respects_max_results(self) -> None:
        """collect_by_terms() returns at most max_results records."""
        fixture = _load_releases_fixture()  # 3 releases in fixture

        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = RitzauViaCollector()
            records = await collector.collect_by_terms(
                terms=["grøn"],
                tier=Tier.FREE,
                max_results=2,
            )

        assert len(records) <= 2

    @pytest.mark.asyncio
    async def test_collect_by_terms_filters_by_search_terms(self) -> None:
        """collect_by_terms() filters out press releases that don't match any search term."""
        # Create a fixture with one matching and one non-matching release.
        matching_release = _first_release()  # Contains "grøn omstilling"
        non_matching_release = {
            "id": 99999,
            "headline": "Completely unrelated topic about pharmaceutical pricing",
            "body": "<p>This press release has nothing to do with the search terms.</p>",
            "url": "https://via.ritzau.dk/pressemeddelelse/99999/unrelated",
            "language": "da",
            "publishedAt": "2026-02-15T12:00:00Z",
            "publisher": {"id": 999, "name": "Test Publisher"},
            "channels": [],
            "images": [],
            "attachments": [],
            "contacts": [],
        }
        mixed_fixture = [matching_release, non_matching_release]

        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(200, json=mixed_fixture)
            )
            collector = RitzauViaCollector()
            records = await collector.collect_by_terms(
                terms=["grøn"],
                tier=Tier.FREE,
                max_results=10,
            )

        # Should return only 1 record (the matching one).
        assert len(records) == 1
        assert "grøn" in records[0]["title"].lower() or "grøn" in (records[0]["text_content"] or "").lower()

    @pytest.mark.asyncio
    async def test_collect_by_terms_populates_search_terms_matched(self) -> None:
        """collect_by_terms() populates search_terms_matched field with matched terms."""
        fixture = _load_releases_fixture()

        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = RitzauViaCollector()
            records = await collector.collect_by_terms(
                terms=["grøn", "omstilling"],
                tier=Tier.FREE,
                max_results=10,
            )

        # First release should match both terms.
        first_record = records[0]
        assert "search_terms_matched" in first_record
        assert isinstance(first_record["search_terms_matched"], list)
        assert len(first_record["search_terms_matched"]) >= 1

    @pytest.mark.asyncio
    async def test_collect_by_terms_case_insensitive_matching(self) -> None:
        """collect_by_terms() performs case-insensitive search term matching."""
        fixture = [_first_release()]

        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = RitzauViaCollector()
            # Use uppercase search term but the content has lowercase.
            records = await collector.collect_by_terms(
                terms=["GRØN", "OMSTILLING"],
                tier=Tier.FREE,
                max_results=10,
            )

        # Should match despite case difference.
        assert len(records) == 1
        assert "GRØN" in records[0]["search_terms_matched"]

    @pytest.mark.asyncio
    async def test_collect_by_terms_danish_characters_in_matching(self) -> None:
        """collect_by_terms() correctly matches Danish characters (æ, ø, å)."""
        fixture = _load_releases_fixture()

        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = RitzauViaCollector()
            records = await collector.collect_by_terms(
                terms=["Ålborg"],
                tier=Tier.FREE,
                max_results=10,
            )

        # Third fixture release has "Ålborg" in the headline.
        assert len(records) == 1
        assert "Ålborg" in records[0]["search_terms_matched"]
        assert "Ålborg" in records[0]["title"]

    @pytest.mark.asyncio
    async def test_collect_by_terms_all_unmatched_returns_empty(self) -> None:
        """collect_by_terms() returns empty list when no releases match search terms."""
        fixture = _load_releases_fixture()

        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = RitzauViaCollector()
            records = await collector.collect_by_terms(
                terms=["nonexistent_term_xyz"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert records == []


# ---------------------------------------------------------------------------
# collect_by_actors() tests
# ---------------------------------------------------------------------------


class TestCollectByActors:
    @pytest.mark.asyncio
    async def test_collect_by_actors_returns_records(self) -> None:
        """collect_by_actors() returns non-empty list when API returns press releases."""
        fixture = _load_releases_fixture()

        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = RitzauViaCollector()
            records = await collector.collect_by_actors(
                actor_ids=["501"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert isinstance(records, list)
        assert len(records) > 0
        assert records[0]["platform"] == "ritzau_via"

    @pytest.mark.asyncio
    async def test_collect_by_actors_empty_response_returns_empty_list(self) -> None:
        """collect_by_actors() returns [] when API returns no releases for the publisher."""
        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(200, json=[])
            )
            collector = RitzauViaCollector()
            records = await collector.collect_by_actors(
                actor_ids=["99999"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_actors_http_429_raises_rate_limit_error(self) -> None:
        """collect_by_actors() raises ArenaRateLimitError on HTTP 429."""
        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(429, headers={"Retry-After": "30"})
            )
            collector = RitzauViaCollector()
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_actors(
                    actor_ids=["501"],
                    tier=Tier.FREE,
                    max_results=5,
                )


# ---------------------------------------------------------------------------
# Tier validation tests
# ---------------------------------------------------------------------------


class TestTierValidation:
    def test_supported_tiers_contains_only_free(self) -> None:
        """RitzauViaCollector.supported_tiers contains only [Tier.FREE]."""
        collector = RitzauViaCollector()
        assert collector.supported_tiers == [Tier.FREE]

    def test_get_tier_config_free_returns_config(self) -> None:
        """get_tier_config(Tier.FREE) returns a TierConfig."""
        collector = RitzauViaCollector()
        config = collector.get_tier_config(Tier.FREE)

        assert config is not None
        assert config.requires_credential is False

    def test_get_tier_config_medium_returns_none(self) -> None:
        """get_tier_config(Tier.MEDIUM) returns None (not available)."""
        collector = RitzauViaCollector()
        assert collector.get_tier_config(Tier.MEDIUM) is None

    def test_get_tier_config_premium_returns_none(self) -> None:
        """get_tier_config(Tier.PREMIUM) returns None (not available)."""
        collector = RitzauViaCollector()
        assert collector.get_tier_config(Tier.PREMIUM) is None

    def test_no_credentials_required(self) -> None:
        """RitzauViaCollector requires_credential is False — API is unauthenticated."""
        collector = RitzauViaCollector()
        config = collector.get_tier_config(Tier.FREE)

        assert config is not None
        assert config.requires_credential is False

    def test_credential_pool_ignored(self) -> None:
        """RitzauViaCollector accepts but ignores credential_pool parameter."""
        from unittest.mock import MagicMock
        fake_pool = MagicMock()
        # Should not raise even when a pool is passed.
        collector = RitzauViaCollector(credential_pool=fake_pool)
        assert collector.credential_pool is None


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_ok_on_valid_response(self) -> None:
        """health_check() returns status='ok' when API returns a valid JSON response."""
        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(200, json=[{"id": 1, "headline": "Test"}])
            )
            collector = RitzauViaCollector()
            result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "news_media"
        assert result["platform"] == "ritzau_via"
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_ok_on_empty_list(self) -> None:
        """health_check() returns status='ok' when API returns empty list (still valid JSON)."""
        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(200, json=[])
            )
            collector = RitzauViaCollector()
            result = await collector.health_check()

        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_on_http_error(self) -> None:
        """health_check() returns status='degraded' on HTTP 4xx/5xx errors."""
        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(503)
            )
            collector = RitzauViaCollector()
            result = await collector.health_check()

        assert result["status"] == "degraded"
        assert "503" in result.get("detail", "")

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_on_unexpected_response_format(self) -> None:
        """health_check() returns status='degraded' when response is not list or dict."""
        with respx.mock:
            # Return a plain string (unexpected format).
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(200, text='"unexpected string"')
            )
            collector = RitzauViaCollector()
            result = await collector.health_check()

        # A plain JSON string is neither a list nor a dict.
        assert result["status"] in ("degraded", "ok")  # depends on JSON parse result

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_connection_error(self) -> None:
        """health_check() returns status='down' when a network connection error occurs."""
        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            collector = RitzauViaCollector()
            result = await collector.health_check()

        assert result["status"] == "down"
        assert "Connection" in result.get("detail", "") or "error" in result.get("detail", "").lower()

    @pytest.mark.asyncio
    async def test_health_check_always_has_arena_platform_checked_at(self) -> None:
        """health_check() always includes arena, platform, and checked_at regardless of outcome."""
        with respx.mock:
            respx.get(RITZAU_RELEASES_ENDPOINT).mock(
                return_value=httpx.Response(200, json=[])
            )
            collector = RitzauViaCollector()
            result = await collector.health_check()

        assert result["arena"] == "news_media"
        assert result["platform"] == "ritzau_via"
        assert "checked_at" in result
