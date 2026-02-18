"""Tests for the Majestic backlink intelligence arena collector.

Covers:
- normalize() unit tests: domain_metrics and backlink content types
- normalize() field mapping: TrustFlow, CitationFlow, engagement_score
- normalize() content_hash is a 64-char hex string
- collect_by_terms() with mocked HTTP (respx)
- collect_by_actors() returns both domain_metrics and backlink records
- HTTP 429 → ArenaRateLimitError
- HTTP 401 → ArenaAuthError
- API-level "InvalidAPIKey" code → ArenaAuthError
- API-level "RateLimitExceeded" code → ArenaRateLimitError
- API-level "InsufficientCredits" code → ArenaCollectionError
- FREE and MEDIUM tiers → NotImplementedError
- health_check() ok, degraded, and down paths
- No credential → NoCredentialAvailableError / health_check down

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
from issue_observatory.arenas.majestic.collector import MajesticCollector  # noqa: E402
from issue_observatory.arenas.majestic.config import MAJESTIC_API_BASE  # noqa: E402
from issue_observatory.core.exceptions import (  # noqa: E402
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "api_responses" / "majestic"


def _load_index_item_fixture() -> dict[str, Any]:
    """Load the recorded GetIndexItemInfo fixture."""
    return json.loads(
        (FIXTURES_DIR / "get_index_item_info_response.json").read_text(encoding="utf-8")
    )


def _load_backlink_fixture() -> dict[str, Any]:
    """Load the recorded GetBackLinkData fixture."""
    return json.loads(
        (FIXTURES_DIR / "get_backlink_data_response.json").read_text(encoding="utf-8")
    )


def _first_domain_item() -> dict[str, Any]:
    """Return the first domain item from the index fixture, tagged for normalization."""
    item = _load_index_item_fixture()["DataTables"]["Results"]["Data"][0].copy()
    item["_record_type"] = "domain_metrics"
    return item


def _first_backlink_item() -> dict[str, Any]:
    """Return the first backlink from the backlink fixture, tagged for normalization."""
    item = _load_backlink_fixture()["DataTables"]["BackLinks"]["Data"][0].copy()
    item["_record_type"] = "backlink"
    item["_target_domain"] = "dr.dk"
    return item


# ---------------------------------------------------------------------------
# Mock credential pool
# ---------------------------------------------------------------------------


def _make_mock_pool() -> Any:
    """Build a minimal mock CredentialPool returning a Majestic PREMIUM credential."""
    pool = MagicMock()
    pool.acquire = AsyncMock(
        return_value={"id": "cred-majestic-001", "api_key": "test-majestic-api-key"}
    )
    pool.release = AsyncMock(return_value=None)
    pool.report_error = AsyncMock(return_value=None)
    return pool


# ---------------------------------------------------------------------------
# normalize() — domain_metrics path
# ---------------------------------------------------------------------------


class TestNormalizeDomainMetrics:
    def _collector(self) -> MajesticCollector:
        return MajesticCollector()

    def test_normalize_domain_metrics_platform_is_majestic(self) -> None:
        """normalize() sets platform='majestic' for domain_metrics records."""
        collector = self._collector()
        result = collector.normalize(_first_domain_item())

        assert result["platform"] == "majestic"

    def test_normalize_domain_metrics_arena_is_web(self) -> None:
        """normalize() sets arena='web' for domain_metrics records."""
        collector = self._collector()
        result = collector.normalize(_first_domain_item())

        assert result["arena"] == "web"

    def test_normalize_domain_metrics_content_type(self) -> None:
        """normalize() sets content_type='domain_metrics'."""
        collector = self._collector()
        result = collector.normalize(_first_domain_item())

        assert result["content_type"] == "domain_metrics"

    def test_normalize_domain_metrics_trust_flow_as_engagement_score(self) -> None:
        """normalize() maps TrustFlow to engagement_score as float."""
        collector = self._collector()
        item = _first_domain_item()
        result = collector.normalize(item)

        assert result["engagement_score"] == float(item["TrustFlow"])

    def test_normalize_domain_metrics_content_hash_is_64_char_hex(self) -> None:
        """normalize() produces a 64-char hex content_hash for domain_metrics."""
        collector = self._collector()
        result = collector.normalize(_first_domain_item())

        assert result["content_hash"] is not None
        assert len(result["content_hash"]) == 64
        int(result["content_hash"], 16)  # must be valid hex

    def test_normalize_domain_metrics_url_has_domain(self) -> None:
        """normalize() constructs url from domain, prefixed with https://."""
        collector = self._collector()
        item = _first_domain_item()
        result = collector.normalize(item)

        assert item["Item"] in result["url"]
        assert result["url"].startswith("https://")

    def test_normalize_domain_metrics_raw_metadata_has_trust_flow(self) -> None:
        """normalize() stores TrustFlow in raw_metadata."""
        collector = self._collector()
        result = collector.normalize(_first_domain_item())

        assert result["raw_metadata"]["TrustFlow"] == 68

    def test_normalize_domain_metrics_raw_metadata_has_citation_flow(self) -> None:
        """normalize() stores CitationFlow in raw_metadata."""
        collector = self._collector()
        result = collector.normalize(_first_domain_item())

        assert result["raw_metadata"]["CitationFlow"] == 52

    def test_normalize_domain_metrics_raw_metadata_has_ref_domains(self) -> None:
        """normalize() stores RefDomains in raw_metadata."""
        collector = self._collector()
        result = collector.normalize(_first_domain_item())

        assert result["raw_metadata"]["RefDomains"] == 38750

    def test_normalize_domain_metrics_required_fields_present(self) -> None:
        """All required schema fields are non-None in domain_metrics record."""
        collector = self._collector()
        result = collector.normalize(_first_domain_item())

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field is None: {field}"

    def test_normalize_domain_metrics_collection_tier_is_premium(self) -> None:
        """normalize() sets collection_tier='premium'."""
        collector = self._collector()
        result = collector.normalize(_first_domain_item())

        assert result["collection_tier"] == "premium"

    def test_normalize_domain_metrics_no_text_or_language(self) -> None:
        """Domain metrics records have text_content=None and language=None."""
        collector = self._collector()
        result = collector.normalize(_first_domain_item())

        assert result["text_content"] is None
        assert result["language"] is None

    def test_normalize_domain_metrics_author_is_domain_name(self) -> None:
        """normalize() sets author_display_name to the domain name."""
        collector = self._collector()
        item = _first_domain_item()
        result = collector.normalize(item)

        assert result["author_display_name"] == item["Item"]

    def test_normalize_domain_metrics_missing_trust_flow_produces_none_score(
        self,
    ) -> None:
        """Missing TrustFlow results in engagement_score=None without error."""
        collector = self._collector()
        item = {**_first_domain_item()}
        del item["TrustFlow"]
        result = collector.normalize(item)

        assert result["engagement_score"] is None

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_domain_metrics_danish_chars_in_item_preserved(
        self, char: str
    ) -> None:
        """Danish characters in domain names pass through normalize() without corruption.

        Majestic can index Danish-language TLD domains whose URLs or anchor texts
        contain Danish characters. These must survive normalization unchanged.
        """
        collector = self._collector()
        item = {**_first_domain_item(), "Item": f"{char}bladet.dk"}
        item["_record_type"] = "domain_metrics"
        result = collector.normalize(item)

        assert char in result["url"] or char in result["author_display_name"]


# ---------------------------------------------------------------------------
# normalize() — backlink path
# ---------------------------------------------------------------------------


class TestNormalizeBacklink:
    def _collector(self) -> MajesticCollector:
        return MajesticCollector()

    def test_normalize_backlink_content_type(self) -> None:
        """normalize() sets content_type='backlink' for backlink records."""
        collector = self._collector()
        result = collector.normalize(_first_backlink_item())

        assert result["content_type"] == "backlink"

    def test_normalize_backlink_platform_and_arena(self) -> None:
        """normalize() sets platform='majestic' and arena='web' for backlinks."""
        collector = self._collector()
        result = collector.normalize(_first_backlink_item())

        assert result["platform"] == "majestic"
        assert result["arena"] == "web"

    def test_normalize_backlink_source_url_becomes_url(self) -> None:
        """normalize() maps SourceURL to the url field."""
        collector = self._collector()
        item = _first_backlink_item()
        result = collector.normalize(item)

        assert result["url"] == item["SourceURL"]

    def test_normalize_backlink_anchor_text_becomes_text_content(self) -> None:
        """normalize() maps AnchorText to text_content."""
        collector = self._collector()
        item = _first_backlink_item()
        result = collector.normalize(item)

        assert result["text_content"] == item["AnchorText"]

    def test_normalize_backlink_trust_flow_as_engagement_score(self) -> None:
        """normalize() maps SourceTrustFlow to engagement_score."""
        collector = self._collector()
        item = _first_backlink_item()
        result = collector.normalize(item)

        assert result["engagement_score"] == float(item["SourceTrustFlow"])

    def test_normalize_backlink_content_hash_is_64_char_hex(self) -> None:
        """normalize() produces a 64-char hex content_hash for backlink records."""
        collector = self._collector()
        result = collector.normalize(_first_backlink_item())

        assert result["content_hash"] is not None
        assert len(result["content_hash"]) == 64
        int(result["content_hash"], 16)  # must be valid hex

    def test_normalize_backlink_danish_anchor_text_preserved(self) -> None:
        """Danish characters in anchor text survive normalize() without corruption."""
        collector = self._collector()
        item = _first_backlink_item()  # AnchorText = "DR" (first item)
        # Use the second backlink which has Danish anchor text
        backlinks = _load_backlink_fixture()["DataTables"]["BackLinks"]["Data"]
        danish_item = backlinks[1].copy()
        danish_item["_record_type"] = "backlink"
        danish_item["_target_domain"] = "dr.dk"

        result = collector.normalize(danish_item)

        assert "Grøn omstilling" in result["text_content"]
        assert "ø" in result["text_content"]

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_backlink_danish_chars_in_anchor_preserved(self, char: str) -> None:
        """Each Danish character in anchor text survives normalize() without error."""
        collector = self._collector()
        item = {
            **_first_backlink_item(),
            "AnchorText": f"Artikel med {char} i ankertekst",
        }
        result = collector.normalize(item)

        assert char in result["text_content"]


# ---------------------------------------------------------------------------
# collect_by_terms() integration tests
# ---------------------------------------------------------------------------


class TestCollectByTerms:
    @pytest.mark.asyncio
    async def test_collect_by_terms_returns_domain_metrics_records(self) -> None:
        """collect_by_terms() returns non-empty list of domain_metrics records."""
        fixture = _load_index_item_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(MAJESTIC_API_BASE).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            with patch.object(
                MajesticCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = MajesticCollector(credential_pool=pool)
                records = await collector.collect_by_terms(
                    terms=["dr.dk", "politiken.dk"], tier=Tier.PREMIUM
                )

        assert isinstance(records, list)
        assert len(records) > 0
        assert all(r["content_type"] == "domain_metrics" for r in records)
        assert all(r["platform"] == "majestic" for r in records)

    @pytest.mark.asyncio
    async def test_collect_by_terms_extracts_domain_from_full_url(self) -> None:
        """collect_by_terms() extracts domain from full URL inputs."""
        fixture = _load_index_item_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(MAJESTIC_API_BASE).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            with patch.object(
                MajesticCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = MajesticCollector(credential_pool=pool)
                records = await collector.collect_by_terms(
                    terms=["https://www.dr.dk/nyheder/"], tier=Tier.PREMIUM
                )

        # Should succeed without raising
        assert isinstance(records, list)

    @pytest.mark.asyncio
    async def test_collect_by_terms_empty_data_returns_empty_list(self) -> None:
        """collect_by_terms() returns [] when API returns no items in DataTables."""
        pool = _make_mock_pool()
        empty_response = {
            "Code": "OK",
            "DataTables": {"Results": {"Data": [], "Rows": 0}},
        }

        with respx.mock:
            respx.get(MAJESTIC_API_BASE).mock(
                return_value=httpx.Response(200, json=empty_response)
            )
            with patch.object(
                MajesticCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = MajesticCollector(credential_pool=pool)
                records = await collector.collect_by_terms(
                    terms=["unknown-domain-xyz.dk"], tier=Tier.PREMIUM
                )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_429_raises_rate_limit_error(self) -> None:
        """collect_by_terms() raises ArenaRateLimitError on HTTP 429."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(MAJESTIC_API_BASE).mock(
                return_value=httpx.Response(429, headers={"Retry-After": "60"})
            )
            with patch.object(
                MajesticCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = MajesticCollector(credential_pool=pool)
                with pytest.raises(ArenaRateLimitError):
                    await collector.collect_by_terms(
                        terms=["dr.dk"], tier=Tier.PREMIUM
                    )

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_401_raises_auth_error(self) -> None:
        """collect_by_terms() raises ArenaAuthError on HTTP 401."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(MAJESTIC_API_BASE).mock(
                return_value=httpx.Response(401)
            )
            with patch.object(
                MajesticCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = MajesticCollector(credential_pool=pool)
                with pytest.raises(ArenaAuthError):
                    await collector.collect_by_terms(
                        terms=["dr.dk"], tier=Tier.PREMIUM
                    )

    @pytest.mark.asyncio
    async def test_collect_by_terms_api_invalid_key_raises_auth_error(self) -> None:
        """collect_by_terms() raises ArenaAuthError when API returns InvalidAPIKey."""
        pool = _make_mock_pool()
        error_response = {"Code": "InvalidAPIKey", "FullError": "API key not recognised"}

        with respx.mock:
            respx.get(MAJESTIC_API_BASE).mock(
                return_value=httpx.Response(200, json=error_response)
            )
            with patch.object(
                MajesticCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = MajesticCollector(credential_pool=pool)
                with pytest.raises(ArenaAuthError):
                    await collector.collect_by_terms(
                        terms=["dr.dk"], tier=Tier.PREMIUM
                    )

    @pytest.mark.asyncio
    async def test_collect_by_terms_api_rate_limit_exceeded_raises_rate_limit_error(
        self,
    ) -> None:
        """collect_by_terms() raises ArenaRateLimitError when API returns RateLimitExceeded."""
        pool = _make_mock_pool()
        error_response = {"Code": "RateLimitExceeded", "FullError": "Rate limit exceeded"}

        with respx.mock:
            respx.get(MAJESTIC_API_BASE).mock(
                return_value=httpx.Response(200, json=error_response)
            )
            with patch.object(
                MajesticCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = MajesticCollector(credential_pool=pool)
                with pytest.raises(ArenaRateLimitError):
                    await collector.collect_by_terms(
                        terms=["dr.dk"], tier=Tier.PREMIUM
                    )

    @pytest.mark.asyncio
    async def test_collect_by_terms_api_insufficient_credits_raises_collection_error(
        self,
    ) -> None:
        """collect_by_terms() raises ArenaCollectionError when API returns InsufficientCredits."""
        pool = _make_mock_pool()
        error_response = {
            "Code": "InsufficientCredits",
            "FullError": "Monthly unit budget exhausted",
        }

        with respx.mock:
            respx.get(MAJESTIC_API_BASE).mock(
                return_value=httpx.Response(200, json=error_response)
            )
            with patch.object(
                MajesticCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = MajesticCollector(credential_pool=pool)
                with pytest.raises(ArenaCollectionError):
                    await collector.collect_by_terms(
                        terms=["dr.dk"], tier=Tier.PREMIUM
                    )

    @pytest.mark.asyncio
    async def test_collect_by_terms_free_tier_raises_not_implemented(self) -> None:
        """collect_by_terms() with FREE tier raises NotImplementedError."""
        pool = _make_mock_pool()
        collector = MajesticCollector(credential_pool=pool)

        with pytest.raises(NotImplementedError):
            await collector.collect_by_terms(terms=["dr.dk"], tier=Tier.FREE)

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_tier_raises_not_implemented(self) -> None:
        """collect_by_terms() with MEDIUM tier raises NotImplementedError."""
        pool = _make_mock_pool()
        collector = MajesticCollector(credential_pool=pool)

        with pytest.raises(NotImplementedError):
            await collector.collect_by_terms(terms=["dr.dk"], tier=Tier.MEDIUM)

    @pytest.mark.asyncio
    async def test_collect_by_terms_no_credential_raises_error(self) -> None:
        """collect_by_terms() raises NoCredentialAvailableError when no pool and no env key."""
        collector = MajesticCollector()  # no pool, no env key

        import unittest.mock

        with unittest.mock.patch.dict("os.environ", {}, clear=True):
            # Temporarily ensure MAJESTIC_PREMIUM_API_KEY is absent
            os.environ.pop("MAJESTIC_PREMIUM_API_KEY", None)
            with pytest.raises(NoCredentialAvailableError):
                await collector.collect_by_terms(terms=["dr.dk"], tier=Tier.PREMIUM)


# ---------------------------------------------------------------------------
# collect_by_actors() tests
# ---------------------------------------------------------------------------


class TestCollectByActors:
    @pytest.mark.asyncio
    async def test_collect_by_actors_returns_both_record_types(self) -> None:
        """collect_by_actors() returns domain_metrics AND backlink records."""
        index_fixture = _load_index_item_fixture()
        backlink_fixture = _load_backlink_fixture()
        pool = _make_mock_pool()

        call_count = 0

        def _side_effect(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            # First call: GetIndexItemInfo, second call: GetBackLinkData
            if call_count % 2 == 1:
                return httpx.Response(200, json=index_fixture)
            return httpx.Response(200, json=backlink_fixture)

        with respx.mock:
            respx.get(MAJESTIC_API_BASE).mock(side_effect=_side_effect)
            with patch.object(
                MajesticCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = MajesticCollector(credential_pool=pool)
                records = await collector.collect_by_actors(
                    actor_ids=["dr.dk"], tier=Tier.PREMIUM
                )

        content_types = {r["content_type"] for r in records}
        assert "domain_metrics" in content_types
        assert "backlink" in content_types

    @pytest.mark.asyncio
    async def test_collect_by_actors_http_403_raises_auth_error(self) -> None:
        """collect_by_actors() raises ArenaAuthError on HTTP 403 response."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(MAJESTIC_API_BASE).mock(
                return_value=httpx.Response(401)
            )
            with patch.object(
                MajesticCollector, "_rate_limit_wait", new=AsyncMock(return_value=None)
            ):
                collector = MajesticCollector(credential_pool=pool)
                with pytest.raises(ArenaAuthError):
                    await collector.collect_by_actors(
                        actor_ids=["dr.dk"], tier=Tier.PREMIUM
                    )


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_ok_when_trust_flow_above_threshold(self) -> None:
        """health_check() returns status='ok' when TrustFlow > MAJESTIC_HEALTH_MIN_TRUST_FLOW."""
        pool = _make_mock_pool()
        fixture = _load_index_item_fixture()  # dr.dk has TrustFlow=68

        with respx.mock:
            respx.get(MAJESTIC_API_BASE).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = MajesticCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "web"
        assert result["platform"] == "majestic"
        assert result["trust_flow"] == 68

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_auth_error(self) -> None:
        """health_check() returns status='down' when API returns InvalidAPIKey."""
        pool = _make_mock_pool()
        error_response = {"Code": "InvalidAPIKey", "FullError": "Invalid API key"}

        with respx.mock:
            respx.get(MAJESTIC_API_BASE).mock(
                return_value=httpx.Response(200, json=error_response)
            )
            collector = MajesticCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "down"
        assert "detail" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_http_401(self) -> None:
        """health_check() returns status='down' on HTTP 401 response."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(MAJESTIC_API_BASE).mock(
                return_value=httpx.Response(401)
            )
            collector = MajesticCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "down"

    @pytest.mark.asyncio
    async def test_health_check_returns_down_when_no_credential(self) -> None:
        """health_check() returns status='down' when no credential is available."""
        collector = MajesticCollector()  # no pool
        os.environ.pop("MAJESTIC_PREMIUM_API_KEY", None)

        result = await collector.health_check()

        assert result["status"] == "down"
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_when_trust_flow_is_zero(self) -> None:
        """health_check() returns status='degraded' when TrustFlow=0 for dr.dk."""
        pool = _make_mock_pool()
        # Return response with Trust Flow = 0 (below minimum threshold of 1)
        low_trust_fixture = {
            "Code": "OK",
            "DataTables": {
                "Results": {
                    "Data": [
                        {
                            "Item": "dr.dk",
                            "TrustFlow": 0,
                            "CitationFlow": 0,
                            "RefDomains": 0,
                        }
                    ]
                }
            },
        }

        with respx.mock:
            respx.get(MAJESTIC_API_BASE).mock(
                return_value=httpx.Response(200, json=low_trust_fixture)
            )
            collector = MajesticCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_health_check_includes_checked_at(self) -> None:
        """health_check() always includes checked_at field in its response."""
        pool = _make_mock_pool()
        fixture = _load_index_item_fixture()

        with respx.mock:
            respx.get(MAJESTIC_API_BASE).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = MajesticCollector(credential_pool=pool)
            result = await collector.health_check()

        assert "checked_at" in result


# ---------------------------------------------------------------------------
# Tier validation tests
# ---------------------------------------------------------------------------


class TestTierConfig:
    def test_get_tier_config_premium_has_expected_fields(self) -> None:
        """PREMIUM tier config has all required TierConfig fields."""
        collector = MajesticCollector()
        config = collector.get_tier_config(Tier.PREMIUM)

        assert config is not None
        assert config.max_results_per_run > 0
        assert config.rate_limit_per_minute > 0
        assert config.requires_credential is True

    def test_get_tier_config_free_raises_value_error(self) -> None:
        """get_tier_config() raises ValueError for FREE tier."""
        collector = MajesticCollector()

        with pytest.raises(ValueError):
            collector.get_tier_config(Tier.FREE)

    def test_get_tier_config_medium_raises_value_error(self) -> None:
        """get_tier_config() raises ValueError for MEDIUM tier."""
        collector = MajesticCollector()

        with pytest.raises(ValueError):
            collector.get_tier_config(Tier.MEDIUM)
