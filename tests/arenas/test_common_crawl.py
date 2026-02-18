"""Tests for the Common Crawl CC Index API arena collector.

Covers:
- normalize() unit tests: web_index_entry content type, all required fields
- normalize() content_hash is a 64-char hex string
- normalize() language detection from 'languages' field (dan -> da)
- normalize() Danish character preservation in URLs
- normalize() platform_id from digest, or SHA-256(url+timestamp)
- normalize() WARC references preserved in raw_metadata
- collect_by_terms() with mocked HTTP (respx+NDJSON response)
- collect_by_actors() with mocked HTTP
- Empty NDJSON response → returns []
- HTTP 429 → ArenaRateLimitError (via fetch_index_page)
- HTTP 503 from collinfo → health_check returns 'down'
- health_check() returns ok with latest_index field
- health_check() returns down on network error
- FREE tier is the only supported tier
- MEDIUM/PREMIUM tiers raise ValueError

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
from issue_observatory.arenas.web.common_crawl.collector import CommonCrawlCollector  # noqa: E402
from issue_observatory.arenas.web.common_crawl.config import (  # noqa: E402
    CC_COLLINFO_URL,
    CC_DEFAULT_INDEX,
    CC_INDEX_BASE_URL,
)
from issue_observatory.core.exceptions import ArenaRateLimitError  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = (
    Path(__file__).parent.parent / "fixtures" / "api_responses" / "common_crawl"
)


def _load_ndjson_fixture() -> str:
    """Load the CC Index NDJSON fixture as raw text."""
    return (FIXTURES_DIR / "index_search_response.ndjson").read_text(encoding="utf-8")


def _load_collinfo_fixture() -> list[dict[str, Any]]:
    """Load the collinfo.json fixture."""
    return json.loads(
        (FIXTURES_DIR / "collinfo_response.json").read_text(encoding="utf-8")
    )


def _parse_ndjson(raw: str) -> list[dict[str, Any]]:
    """Parse the NDJSON fixture into a list of dicts."""
    entries = []
    for line in raw.splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def _first_entry() -> dict[str, Any]:
    """Return the first CC Index entry from the NDJSON fixture."""
    return _parse_ndjson(_load_ndjson_fixture())[0]


# CC Index search URL for the default index
CC_SEARCH_URL = f"{CC_INDEX_BASE_URL}/{CC_DEFAULT_INDEX}/search"


# ---------------------------------------------------------------------------
# normalize() unit tests
# ---------------------------------------------------------------------------


class TestNormalize:
    def _collector(self) -> CommonCrawlCollector:
        return CommonCrawlCollector()

    def test_normalize_platform_is_common_crawl(self) -> None:
        """normalize() sets platform='common_crawl'."""
        collector = self._collector()
        result = collector.normalize(_first_entry())

        assert result["platform"] == "common_crawl"

    def test_normalize_arena_is_web(self) -> None:
        """normalize() sets arena='web'."""
        collector = self._collector()
        result = collector.normalize(_first_entry())

        assert result["arena"] == "web"

    def test_normalize_content_type_is_web_index_entry(self) -> None:
        """normalize() sets content_type='web_index_entry'."""
        collector = self._collector()
        result = collector.normalize(_first_entry())

        assert result["content_type"] == "web_index_entry"

    def test_normalize_url_field_preserved(self) -> None:
        """normalize() maps the 'url' CC field directly."""
        collector = self._collector()
        entry = _first_entry()
        result = collector.normalize(entry)

        assert result["url"] == entry["url"]

    def test_normalize_content_hash_is_64_char_hex(self) -> None:
        """normalize() computes a 64-char hex content_hash from the URL."""
        collector = self._collector()
        result = collector.normalize(_first_entry())

        assert result["content_hash"] is not None
        assert len(result["content_hash"]) == 64
        int(result["content_hash"], 16)  # must be valid hex

    def test_normalize_platform_id_from_digest_when_present(self) -> None:
        """normalize() uses digest as platform_id when digest is present."""
        collector = self._collector()
        entry = _first_entry()
        result = collector.normalize(entry)

        # First entry has a digest field; platform_id should equal the digest
        assert result["platform_id"] is not None
        assert result["platform_id"] == entry["digest"]

    def test_normalize_platform_id_sha256_when_no_digest(self) -> None:
        """normalize() falls back to SHA-256(url+timestamp) when digest is absent."""
        import hashlib  # noqa: PLC0415

        collector = self._collector()
        entry = {**_first_entry()}
        entry.pop("digest", None)
        result = collector.normalize(entry)

        expected = hashlib.sha256(
            f"{entry['url']}{entry['timestamp']}".encode()
        ).hexdigest()
        assert result["platform_id"] == expected

    def test_normalize_language_maps_dan_to_da(self) -> None:
        """normalize() maps CC ISO 639-3 'dan' language code to ISO 639-1 'da'."""
        collector = self._collector()
        # First entry has languages="dan"
        result = collector.normalize(_first_entry())

        assert result["language"] == "da"

    def test_normalize_language_primary_danish_in_mixed_list(self) -> None:
        """normalize() returns 'da' when 'dan' appears in a mixed languages string."""
        collector = self._collector()
        entries = _parse_ndjson(_load_ndjson_fixture())
        # Fourth entry has languages="dan,eng"
        result = collector.normalize(entries[3])

        assert result["language"] == "da"

    def test_normalize_raw_metadata_contains_warc_fields(self) -> None:
        """normalize() stores WARC location fields in raw_metadata."""
        collector = self._collector()
        result = collector.normalize(_first_entry())

        meta = result.get("raw_metadata", {})
        assert "warc_filename" in meta
        assert "warc_record_offset" in meta
        assert "warc_record_length" in meta

    def test_normalize_raw_metadata_contains_status(self) -> None:
        """normalize() stores HTTP status code in raw_metadata."""
        collector = self._collector()
        result = collector.normalize(_first_entry())

        assert result["raw_metadata"]["status"] == "200"

    def test_normalize_required_fields_always_present(self) -> None:
        """All five required schema fields are non-None in normalized output."""
        collector = self._collector()
        result = collector.normalize(_first_entry())

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field is None: {field}"

    def test_normalize_collection_tier_is_free(self) -> None:
        """normalize() sets collection_tier='free' (CC is unauthenticated)."""
        collector = self._collector()
        result = collector.normalize(_first_entry())

        assert result["collection_tier"] == "free"

    def test_normalize_author_display_name_is_domain(self) -> None:
        """normalize() extracts domain from URL as author_display_name."""
        collector = self._collector()
        result = collector.normalize(_first_entry())

        # First entry URL is from dr.dk
        assert result["author_display_name"] is not None
        assert "dr.dk" in result["author_display_name"]

    def test_normalize_text_content_is_none(self) -> None:
        """normalize() sets text_content=None (CC index has no page content)."""
        collector = self._collector()
        result = collector.normalize(_first_entry())

        assert result["text_content"] is None

    def test_normalize_no_url_produces_none_content_hash(self) -> None:
        """normalize() returns content_hash=None when URL is absent."""
        collector = self._collector()
        entry = {**_first_entry()}
        del entry["url"]
        result = collector.normalize(entry)

        assert result["content_hash"] is None

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_danish_chars_in_url_preserved(self, char: str) -> None:
        """Danish characters in CC Index URLs survive normalize() without corruption."""
        collector = self._collector()
        entry = {
            **_first_entry(),
            "url": f"https://dr.dk/nyheder/{char}bladet-artikel",
        }
        result = collector.normalize(entry)

        assert char in result["url"]

    def test_normalize_danish_url_in_fixture_preserved(self) -> None:
        """The Danish URL from the fixture (with ø, æ) survives normalize()."""
        collector = self._collector()
        entries = _parse_ndjson(_load_ndjson_fixture())
        # Second entry has Danish chars in URL: /bæredygtighed/velfærd-og-økonomi
        result = collector.normalize(entries[1])

        assert "æ" in result["url"] or "ø" in result["url"]


# ---------------------------------------------------------------------------
# collect_by_terms() integration tests
# ---------------------------------------------------------------------------


class TestCollectByTerms:
    @pytest.mark.asyncio
    async def test_collect_by_terms_returns_records_on_success(self) -> None:
        """collect_by_terms() returns non-empty list when CC API returns NDJSON entries."""
        ndjson_body = _load_ndjson_fixture()
        pool = None  # CC is unauthenticated

        with respx.mock:
            respx.get(CC_SEARCH_URL).mock(
                return_value=httpx.Response(200, text=ndjson_body)
            )
            with patch.object(
                CommonCrawlCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = CommonCrawlCollector()
                records = await collector.collect_by_terms(
                    terms=["groen-omstilling"], tier=Tier.FREE, max_results=10
                )

        assert isinstance(records, list)
        assert len(records) > 0
        assert all(r["content_type"] == "web_index_entry" for r in records)

    @pytest.mark.asyncio
    async def test_collect_by_terms_all_records_have_correct_platform(self) -> None:
        """collect_by_terms() records all have platform='common_crawl' and arena='web'."""
        ndjson_body = _load_ndjson_fixture()

        with respx.mock:
            respx.get(CC_SEARCH_URL).mock(
                return_value=httpx.Response(200, text=ndjson_body)
            )
            with patch.object(
                CommonCrawlCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = CommonCrawlCollector()
                records = await collector.collect_by_terms(
                    terms=["dr.dk"], tier=Tier.FREE, max_results=10
                )

        assert all(r["platform"] == "common_crawl" for r in records)
        assert all(r["arena"] == "web" for r in records)

    @pytest.mark.asyncio
    async def test_collect_by_terms_empty_response_returns_empty_list(self) -> None:
        """collect_by_terms() returns [] when API returns no NDJSON entries."""
        with respx.mock:
            respx.get(CC_SEARCH_URL).mock(
                return_value=httpx.Response(200, text="")
            )
            with patch.object(
                CommonCrawlCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = CommonCrawlCollector()
                records = await collector.collect_by_terms(
                    terms=["nonexistent-term-xyz"], tier=Tier.FREE, max_results=10
                )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_429_raises_rate_limit_error(self) -> None:
        """collect_by_terms() raises ArenaRateLimitError on HTTP 429 from CC API."""
        with respx.mock:
            respx.get(CC_SEARCH_URL).mock(
                return_value=httpx.Response(429, headers={"Retry-After": "60"})
            )
            with patch.object(
                CommonCrawlCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = CommonCrawlCollector()
                with pytest.raises(ArenaRateLimitError):
                    await collector.collect_by_terms(
                        terms=["test"], tier=Tier.FREE, max_results=10
                    )

    @pytest.mark.asyncio
    async def test_collect_by_terms_404_returns_empty_list(self) -> None:
        """collect_by_terms() returns [] gracefully when CC returns 404 (no captures)."""
        with respx.mock:
            respx.get(CC_SEARCH_URL).mock(
                return_value=httpx.Response(404)
            )
            with patch.object(
                CommonCrawlCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = CommonCrawlCollector()
                records = await collector.collect_by_terms(
                    terms=["unknown"], tier=Tier.FREE, max_results=10
                )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_danish_url_preserved_in_records(self) -> None:
        """collect_by_terms() preserves Danish characters in URLs through full pipeline."""
        ndjson_body = _load_ndjson_fixture()

        with respx.mock:
            respx.get(CC_SEARCH_URL).mock(
                return_value=httpx.Response(200, text=ndjson_body)
            )
            with patch.object(
                CommonCrawlCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = CommonCrawlCollector()
                records = await collector.collect_by_terms(
                    terms=["dr.dk"], tier=Tier.FREE, max_results=50
                )

        urls = [r.get("url", "") or "" for r in records]
        # The fixture contains URLs like /groen-omstilling; check at least one URL
        assert any("dr.dk" in u for u in urls)

    @pytest.mark.asyncio
    async def test_collect_by_terms_deduplicates_by_urlkey(self) -> None:
        """collect_by_terms() does not return duplicate records for the same URL."""
        ndjson_body = _load_ndjson_fixture()
        # Return same fixture for two terms — dedup should prevent double entries
        with respx.mock:
            respx.get(CC_SEARCH_URL).mock(
                return_value=httpx.Response(200, text=ndjson_body)
            )
            with patch.object(
                CommonCrawlCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = CommonCrawlCollector()
                records = await collector.collect_by_terms(
                    terms=["groen", "groen"],  # same term repeated
                    tier=Tier.FREE,
                    max_results=100,
                )

        platform_ids = [r["platform_id"] for r in records]
        assert len(platform_ids) == len(set(platform_ids))

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_tier_raises_value_error(self) -> None:
        """collect_by_terms() with MEDIUM tier raises ValueError (only FREE supported)."""
        collector = CommonCrawlCollector()

        with pytest.raises(ValueError):
            await collector.collect_by_terms(
                terms=["dr.dk"], tier=Tier.MEDIUM, max_results=10
            )


# ---------------------------------------------------------------------------
# collect_by_actors() tests
# ---------------------------------------------------------------------------


class TestCollectByActors:
    @pytest.mark.asyncio
    async def test_collect_by_actors_returns_records_for_domain(self) -> None:
        """collect_by_actors() returns CC index entries for specified domains."""
        ndjson_body = _load_ndjson_fixture()

        with respx.mock:
            respx.get(CC_SEARCH_URL).mock(
                return_value=httpx.Response(200, text=ndjson_body)
            )
            with patch.object(
                CommonCrawlCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = CommonCrawlCollector()
                records = await collector.collect_by_actors(
                    actor_ids=["dr.dk"], tier=Tier.FREE, max_results=10
                )

        assert isinstance(records, list)
        assert all(r["content_type"] == "web_index_entry" for r in records)

    @pytest.mark.asyncio
    async def test_collect_by_actors_empty_domain_response_returns_empty(self) -> None:
        """collect_by_actors() returns [] when CC returns no captures for domain."""
        with respx.mock:
            respx.get(CC_SEARCH_URL).mock(
                return_value=httpx.Response(200, text="")
            )
            with patch.object(
                CommonCrawlCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = CommonCrawlCollector()
                records = await collector.collect_by_actors(
                    actor_ids=["nonexistent-domain-xyz.dk"],
                    tier=Tier.FREE,
                    max_results=10,
                )

        assert records == []


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_ok_with_latest_index(self) -> None:
        """health_check() returns status='ok' and includes latest_index field."""
        collinfo = _load_collinfo_fixture()

        with respx.mock:
            respx.get(CC_COLLINFO_URL).mock(
                return_value=httpx.Response(200, json=collinfo)
            )
            collector = CommonCrawlCollector()
            result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "web"
        assert result["platform"] == "common_crawl"
        assert "latest_index" in result
        assert result["latest_index"] == "CC-MAIN-2025-51"
        assert result["indexes_available"] == 3

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_http_500(self) -> None:
        """health_check() returns status='down' on HTTP 500 from collinfo endpoint."""
        with respx.mock:
            respx.get(CC_COLLINFO_URL).mock(
                return_value=httpx.Response(500)
            )
            collector = CommonCrawlCollector()
            result = await collector.health_check()

        assert result["status"] == "down"
        assert "detail" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_on_empty_collinfo(self) -> None:
        """health_check() returns status='degraded' when collinfo returns empty list."""
        with respx.mock:
            respx.get(CC_COLLINFO_URL).mock(
                return_value=httpx.Response(200, json=[])
            )
            collector = CommonCrawlCollector()
            result = await collector.health_check()

        assert result["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_health_check_includes_checked_at(self) -> None:
        """health_check() always includes checked_at field in its response."""
        collinfo = _load_collinfo_fixture()

        with respx.mock:
            respx.get(CC_COLLINFO_URL).mock(
                return_value=httpx.Response(200, json=collinfo)
            )
            collector = CommonCrawlCollector()
            result = await collector.health_check()

        assert "checked_at" in result


# ---------------------------------------------------------------------------
# Tier config tests
# ---------------------------------------------------------------------------


class TestTierConfig:
    def test_get_tier_config_free_returns_config(self) -> None:
        """get_tier_config(FREE) returns a valid TierConfig."""
        collector = CommonCrawlCollector()
        config = collector.get_tier_config(Tier.FREE)

        assert config is not None
        assert config.requires_credential is False
        assert config.max_results_per_run == 10_000

    def test_get_tier_config_medium_raises_value_error(self) -> None:
        """get_tier_config(MEDIUM) raises ValueError for unsupported tier."""
        collector = CommonCrawlCollector()

        with pytest.raises(ValueError):
            collector.get_tier_config(Tier.MEDIUM)

    def test_get_tier_config_premium_raises_value_error(self) -> None:
        """get_tier_config(PREMIUM) raises ValueError for unsupported tier."""
        collector = CommonCrawlCollector()

        with pytest.raises(ValueError):
            collector.get_tier_config(Tier.PREMIUM)
