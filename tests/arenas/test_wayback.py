"""Tests for the Wayback Machine CDX API arena collector.

Covers:
- normalize() unit tests: web_page_snapshot content type, all required fields
- normalize() content_hash is 64-char hex
- normalize() language='da' inferred from .dk TLD
- normalize() wayback_url constructed correctly in raw_metadata
- normalize() platform_id is SHA-256(url+timestamp)
- normalize() Danish characters in original URLs preserved
- collect_by_terms() with mocked CDX API (respx)
- collect_by_actors() returns snapshot records
- Empty CDX response → returns []
- HTTP 429 → ArenaRateLimitError
- HTTP 503 in CDX → graceful skip (no exception), returns []
- health_check() returns ok, down on 503, down on 500
- health_check() handles connection error → down
- FREE tier only; MEDIUM/PREMIUM → ValueError

These tests run without a live database or network connection.
"""

from __future__ import annotations

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
from issue_observatory.arenas.web.wayback.collector import WaybackCollector  # noqa: E402
from issue_observatory.arenas.web.wayback.config import (  # noqa: E402
    WB_CDX_BASE_URL,
    WB_PLAYBACK_URL_TEMPLATE,
)
from issue_observatory.core.exceptions import ArenaRateLimitError  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = (
    Path(__file__).parent.parent / "fixtures" / "api_responses" / "wayback"
)


def _load_cdx_fixture() -> list[list[str]]:
    """Load the CDX API JSON fixture as a 2D array."""
    return json.loads(
        (FIXTURES_DIR / "cdx_response.json").read_text(encoding="utf-8")
    )


def _cdx_fixture_text() -> str:
    """Return the CDX fixture as a JSON string (for httpx response body)."""
    return (FIXTURES_DIR / "cdx_response.json").read_text(encoding="utf-8")


def _cdx_fixture_single_entry() -> str:
    """Return a CDX response with only one data row (no resume key)."""
    data = _load_cdx_fixture()
    # Keep header + first data row only
    single = [data[0], data[1]]
    return json.dumps(single)


def _make_cdx_entry() -> dict[str, Any]:
    """Build a single normalized CDX entry dict for direct normalize() calls."""
    data = _load_cdx_fixture()
    field_names: list[str] = data[0]
    first_row: list[str] = data[1]
    return dict(zip(field_names, first_row))


# ---------------------------------------------------------------------------
# normalize() unit tests
# ---------------------------------------------------------------------------


class TestNormalize:
    def _collector(self) -> WaybackCollector:
        return WaybackCollector()

    def test_normalize_platform_is_wayback(self) -> None:
        """normalize() sets platform='wayback'."""
        collector = self._collector()
        result = collector.normalize(_make_cdx_entry())

        assert result["platform"] == "wayback"

    def test_normalize_arena_is_web(self) -> None:
        """normalize() sets arena='web'."""
        collector = self._collector()
        result = collector.normalize(_make_cdx_entry())

        assert result["arena"] == "web"

    def test_normalize_content_type_is_web_page_snapshot(self) -> None:
        """normalize() sets content_type='web_page_snapshot'."""
        collector = self._collector()
        result = collector.normalize(_make_cdx_entry())

        assert result["content_type"] == "web_page_snapshot"

    def test_normalize_url_from_original_field(self) -> None:
        """normalize() maps CDX 'original' field to 'url'."""
        collector = self._collector()
        entry = _make_cdx_entry()
        result = collector.normalize(entry)

        assert result["url"] == entry["original"]

    def test_normalize_platform_id_is_sha256_of_url_and_timestamp(self) -> None:
        """normalize() computes platform_id as SHA-256(url+timestamp)."""
        import hashlib  # noqa: PLC0415

        collector = self._collector()
        entry = _make_cdx_entry()
        result = collector.normalize(entry)

        expected = hashlib.sha256(
            f"{entry['original']}{entry['timestamp']}".encode("utf-8")
        ).hexdigest()
        assert result["platform_id"] == expected

    def test_normalize_content_hash_is_64_char_hex(self) -> None:
        """normalize() computes a 64-char hex content_hash from the URL."""
        collector = self._collector()
        result = collector.normalize(_make_cdx_entry())

        assert result["content_hash"] is not None
        assert len(result["content_hash"]) == 64
        int(result["content_hash"], 16)  # must be valid hex

    def test_normalize_language_is_da_for_dk_domain(self) -> None:
        """normalize() infers language='da' from .dk TLD in the original URL."""
        collector = self._collector()
        result = collector.normalize(_make_cdx_entry())

        # First entry URL ends with .dk domain → language inferred as 'da'
        assert result["language"] == "da"

    def test_normalize_language_is_none_for_non_dk_domain(self) -> None:
        """normalize() does not infer language for non-.dk domains."""
        collector = self._collector()
        entry = {
            **_make_cdx_entry(),
            "original": "https://www.bbc.com/news/test",
        }
        result = collector.normalize(entry)

        assert result["language"] is None

    def test_normalize_wayback_url_in_raw_metadata(self) -> None:
        """normalize() constructs full Wayback Machine playback URL in raw_metadata."""
        collector = self._collector()
        entry = _make_cdx_entry()
        result = collector.normalize(entry)

        meta = result.get("raw_metadata", {})
        assert "wayback_url" in meta
        expected_wayback = WB_PLAYBACK_URL_TEMPLATE.format(
            timestamp=entry["timestamp"],
            url=entry["original"],
        )
        assert meta["wayback_url"] == expected_wayback

    def test_normalize_raw_metadata_contains_cdx_fields(self) -> None:
        """normalize() stores CDX fields (digest, statuscode, mimetype) in raw_metadata."""
        collector = self._collector()
        result = collector.normalize(_make_cdx_entry())

        meta = result.get("raw_metadata", {})
        assert "digest" in meta
        assert "statuscode" in meta
        assert "mimetype" in meta

    def test_normalize_required_fields_always_present(self) -> None:
        """All five required schema fields are non-None in normalized output."""
        collector = self._collector()
        result = collector.normalize(_make_cdx_entry())

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field is None: {field}"

    def test_normalize_collection_tier_is_free(self) -> None:
        """normalize() sets collection_tier='free' (Wayback Machine is free)."""
        collector = self._collector()
        result = collector.normalize(_make_cdx_entry())

        assert result["collection_tier"] == "free"

    def test_normalize_text_content_is_none(self) -> None:
        """normalize() sets text_content=None (CDX API provides metadata only)."""
        collector = self._collector()
        result = collector.normalize(_make_cdx_entry())

        assert result["text_content"] is None

    def test_normalize_author_display_name_is_domain(self) -> None:
        """normalize() extracts domain from original URL as author_display_name."""
        collector = self._collector()
        result = collector.normalize(_make_cdx_entry())

        assert result["author_display_name"] is not None
        assert "dr.dk" in result["author_display_name"]

    def test_normalize_empty_entry_does_not_raise(self) -> None:
        """normalize() handles a completely empty dict without raising."""
        collector = self._collector()
        result = collector.normalize({})

        assert result["platform"] == "wayback"
        assert result["content_type"] == "web_page_snapshot"
        assert result["url"] is None

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_danish_chars_in_url_preserved(self, char: str) -> None:
        """Danish characters in CDX original URLs survive normalize() without corruption."""
        collector = self._collector()
        entry = {
            **_make_cdx_entry(),
            "original": f"https://dr.dk/nyheder/{char}bladet-artikel",
        }
        result = collector.normalize(entry)

        assert char in result["url"]

    def test_normalize_published_at_parsed_from_timestamp(self) -> None:
        """normalize() parses CDX timestamp '20260115120000' to an ISO 8601 string."""
        collector = self._collector()
        entry = {**_make_cdx_entry(), "timestamp": "20260115120000"}
        result = collector.normalize(entry)

        assert result["published_at"] is not None
        assert "2026-01-15" in result["published_at"]


# ---------------------------------------------------------------------------
# collect_by_terms() integration tests
# ---------------------------------------------------------------------------


class TestCollectByTerms:
    @pytest.mark.asyncio
    async def test_collect_by_terms_returns_snapshot_records(self) -> None:
        """collect_by_terms() returns non-empty list of web_page_snapshot records."""
        cdx_body = _cdx_fixture_text()

        with respx.mock:
            respx.get(WB_CDX_BASE_URL).mock(
                return_value=httpx.Response(200, text=cdx_body)
            )
            with patch.object(
                WaybackCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = WaybackCollector()
                records = await collector.collect_by_terms(
                    terms=["groen-omstilling"], tier=Tier.FREE, max_results=10
                )

        assert isinstance(records, list)
        assert len(records) > 0
        assert all(r["content_type"] == "web_page_snapshot" for r in records)

    @pytest.mark.asyncio
    async def test_collect_by_terms_all_records_have_correct_platform(self) -> None:
        """collect_by_terms() records all have platform='wayback' and arena='web'."""
        cdx_body = _cdx_fixture_text()

        with respx.mock:
            respx.get(WB_CDX_BASE_URL).mock(
                return_value=httpx.Response(200, text=cdx_body)
            )
            with patch.object(
                WaybackCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = WaybackCollector()
                records = await collector.collect_by_terms(
                    terms=["dr.dk"], tier=Tier.FREE, max_results=10
                )

        assert all(r["platform"] == "wayback" for r in records)
        assert all(r["arena"] == "web" for r in records)

    @pytest.mark.asyncio
    async def test_collect_by_terms_empty_response_returns_empty_list(self) -> None:
        """collect_by_terms() returns [] when CDX API returns empty body."""
        with respx.mock:
            respx.get(WB_CDX_BASE_URL).mock(
                return_value=httpx.Response(200, text="")
            )
            with patch.object(
                WaybackCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = WaybackCollector()
                records = await collector.collect_by_terms(
                    terms=["nonexistent-query-xyz"],
                    tier=Tier.FREE,
                    max_results=10,
                )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_429_raises_rate_limit_error(self) -> None:
        """collect_by_terms() raises ArenaRateLimitError on HTTP 429 from CDX API."""
        with respx.mock:
            respx.get(WB_CDX_BASE_URL).mock(
                return_value=httpx.Response(429, headers={"Retry-After": "60"})
            )
            with patch.object(
                WaybackCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = WaybackCollector()
                with pytest.raises(ArenaRateLimitError):
                    await collector.collect_by_terms(
                        terms=["test"], tier=Tier.FREE, max_results=10
                    )

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_503_returns_empty_list(self) -> None:
        """collect_by_terms() returns [] gracefully on HTTP 503 (service overloaded)."""
        with respx.mock:
            respx.get(WB_CDX_BASE_URL).mock(
                return_value=httpx.Response(503)
            )
            with patch.object(
                WaybackCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = WaybackCollector()
                records = await collector.collect_by_terms(
                    terms=["dr.dk"], tier=Tier.FREE, max_results=10
                )

        # 503 is handled gracefully — skip page, no exception
        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_danish_url_preserved_end_to_end(self) -> None:
        """collect_by_terms() preserves Danish characters in original URLs through full pipeline."""
        # Build a CDX response with a Danish URL containing ø
        danish_cdx = json.dumps([
            ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"],
            ["dk,dr)/baeredygtighed", "20260110120000",
             "https://dr.dk/nyheder/grøn-omstilling", "text/html", "200",
             "SHA1:TESTDIGEST1234567890ABCDEF12345678901234", "12345"],
        ])

        with respx.mock:
            respx.get(WB_CDX_BASE_URL).mock(
                return_value=httpx.Response(200, text=danish_cdx)
            )
            with patch.object(
                WaybackCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = WaybackCollector()
                records = await collector.collect_by_terms(
                    terms=["dr.dk"],  # matches via URL substring
                    tier=Tier.FREE,
                    max_results=10,
                )

        assert len(records) > 0
        assert "ø" in records[0]["url"]

    @pytest.mark.asyncio
    async def test_collect_by_terms_deduplicates_by_url_plus_timestamp(self) -> None:
        """collect_by_terms() deduplicates captures with the same URL+timestamp key."""
        cdx_body = _cdx_fixture_text()

        with respx.mock:
            respx.get(WB_CDX_BASE_URL).mock(
                return_value=httpx.Response(200, text=cdx_body)
            )
            with patch.object(
                WaybackCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = WaybackCollector()
                records = await collector.collect_by_terms(
                    terms=["groen", "groen"],  # same term twice
                    tier=Tier.FREE,
                    max_results=100,
                )

        platform_ids = [r["platform_id"] for r in records]
        assert len(platform_ids) == len(set(platform_ids))

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_tier_raises_value_error(self) -> None:
        """collect_by_terms() with MEDIUM tier raises ValueError (only FREE supported)."""
        collector = WaybackCollector()

        with pytest.raises(ValueError):
            await collector.collect_by_terms(
                terms=["dr.dk"], tier=Tier.MEDIUM, max_results=10
            )


# ---------------------------------------------------------------------------
# collect_by_actors() tests
# ---------------------------------------------------------------------------


class TestCollectByActors:
    @pytest.mark.asyncio
    async def test_collect_by_actors_returns_snapshot_records_for_domain(self) -> None:
        """collect_by_actors() returns CDX snapshot records for specified domains."""
        cdx_body = _cdx_fixture_text()

        with respx.mock:
            respx.get(WB_CDX_BASE_URL).mock(
                return_value=httpx.Response(200, text=cdx_body)
            )
            with patch.object(
                WaybackCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = WaybackCollector()
                records = await collector.collect_by_actors(
                    actor_ids=["dr.dk"], tier=Tier.FREE, max_results=10
                )

        assert isinstance(records, list)
        assert all(r["content_type"] == "web_page_snapshot" for r in records)

    @pytest.mark.asyncio
    async def test_collect_by_actors_empty_response_returns_empty_list(self) -> None:
        """collect_by_actors() returns [] when CDX returns no captures for domain."""
        with respx.mock:
            respx.get(WB_CDX_BASE_URL).mock(
                return_value=httpx.Response(200, text="")
            )
            with patch.object(
                WaybackCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = WaybackCollector()
                records = await collector.collect_by_actors(
                    actor_ids=["noncrawled-domain-xyz.dk"],
                    tier=Tier.FREE,
                    max_results=10,
                )

        assert records == []


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_ok_when_cdx_returns_captures(self) -> None:
        """health_check() returns status='ok' when CDX API returns snapshot data."""
        cdx_body = _cdx_fixture_text()

        with respx.mock:
            respx.get(WB_CDX_BASE_URL).mock(
                return_value=httpx.Response(200, text=cdx_body)
            )
            collector = WaybackCollector()
            result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "web"
        assert result["platform"] == "wayback"
        assert "captures_returned" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_ok_on_empty_cdx_response(self) -> None:
        """health_check() returns status='ok' even when CDX returns no captures."""
        with respx.mock:
            respx.get(WB_CDX_BASE_URL).mock(
                return_value=httpx.Response(200, json=[["urlkey"]])
            )
            collector = WaybackCollector()
            result = await collector.health_check()

        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_http_503(self) -> None:
        """health_check() returns status='down' on HTTP 503 from CDX API."""
        with respx.mock:
            respx.get(WB_CDX_BASE_URL).mock(
                return_value=httpx.Response(503)
            )
            collector = WaybackCollector()
            result = await collector.health_check()

        assert result["status"] == "down"
        assert "503" in result.get("detail", "")

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_http_500(self) -> None:
        """health_check() returns status='down' on HTTP 500 from CDX API."""
        with respx.mock:
            respx.get(WB_CDX_BASE_URL).mock(
                return_value=httpx.Response(500)
            )
            collector = WaybackCollector()
            result = await collector.health_check()

        assert result["status"] == "down"

    @pytest.mark.asyncio
    async def test_health_check_includes_checked_at(self) -> None:
        """health_check() always includes checked_at in its response dict."""
        cdx_body = _cdx_fixture_text()

        with respx.mock:
            respx.get(WB_CDX_BASE_URL).mock(
                return_value=httpx.Response(200, text=cdx_body)
            )
            collector = WaybackCollector()
            result = await collector.health_check()

        assert "checked_at" in result


# ---------------------------------------------------------------------------
# Tier config tests
# ---------------------------------------------------------------------------


class TestTierConfig:
    def test_get_tier_config_free_returns_config(self) -> None:
        """get_tier_config(FREE) returns a valid TierConfig with expected fields."""
        collector = WaybackCollector()
        config = collector.get_tier_config(Tier.FREE)

        assert config is not None
        assert config.requires_credential is False
        assert config.max_results_per_run == 10_000

    def test_get_tier_config_medium_raises_value_error(self) -> None:
        """get_tier_config(MEDIUM) raises ValueError (only FREE is supported)."""
        collector = WaybackCollector()

        with pytest.raises(ValueError):
            collector.get_tier_config(Tier.MEDIUM)

    def test_get_tier_config_premium_raises_value_error(self) -> None:
        """get_tier_config(PREMIUM) raises ValueError (only FREE is supported)."""
        collector = WaybackCollector()

        with pytest.raises(ValueError):
            collector.get_tier_config(Tier.PREMIUM)
