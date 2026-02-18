"""Tests for the Gab arena collector.

Covers:
- normalize() unit tests: platform/arena/content_type, HTML stripping,
  author fields, media_urls from attachments, reblog handling,
  Danish character preservation
- collect_by_terms() with mocked Gab search API (respx)
- collect_by_terms() hashtag fallback path (#tag -> hashtag timeline)
- collect_by_actors() with account lookup and statuses pagination
- HTTP 429 -> ArenaRateLimitError
- HTTP 401 -> ArenaAuthError
- Empty response -> returns []
- Tier validation: only FREE is supported (MEDIUM/PREMIUM produce a warning
  but still use FREE under the hood)
- health_check() returns 'ok', 'degraded', 'down' as appropriate
- Missing 'access_token' in credential -> raises ArenaAuthError
- NoCredentialAvailableError when no credential pool is configured

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
from issue_observatory.arenas.gab.collector import GabCollector  # noqa: E402
from issue_observatory.arenas.gab.config import (  # noqa: E402
    GAB_ACCOUNT_LOOKUP_ENDPOINT,
    GAB_ACCOUNT_STATUSES_ENDPOINT,
    GAB_HASHTAG_TIMELINE_ENDPOINT,
    GAB_INSTANCE_ENDPOINT,
    GAB_PUBLIC_TIMELINE_ENDPOINT,
    GAB_SEARCH_ENDPOINT,
)
from issue_observatory.core.exceptions import (  # noqa: E402
    ArenaAuthError,
    ArenaRateLimitError,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "api_responses" / "gab"


def _load_search_fixture() -> dict[str, Any]:
    """Load the recorded Gab search statuses fixture."""
    return json.loads((FIXTURES_DIR / "search_statuses_response.json").read_text(encoding="utf-8"))


def _load_hashtag_timeline_fixture() -> list[dict[str, Any]]:
    """Load the recorded Gab hashtag timeline fixture."""
    return json.loads((FIXTURES_DIR / "hashtag_timeline_response.json").read_text(encoding="utf-8"))


def _first_status() -> dict[str, Any]:
    """Return the first status dict from the search fixture."""
    return _load_search_fixture()["statuses"][0]


# ---------------------------------------------------------------------------
# Mock credential pool
# ---------------------------------------------------------------------------


def _make_mock_pool(access_token: str = "test-gab-access-token") -> Any:
    """Build a minimal mock CredentialPool returning a Gab credential."""
    pool = MagicMock()
    pool.acquire = AsyncMock(
        return_value={
            "id": "cred-gab-001",
            "access_token": access_token,
        }
    )
    pool.release = AsyncMock(return_value=None)
    pool.report_error = AsyncMock(return_value=None)
    return pool


# ---------------------------------------------------------------------------
# normalize() unit tests
# ---------------------------------------------------------------------------


class TestNormalize:
    def _collector(self) -> GabCollector:
        return GabCollector()

    def test_normalize_sets_platform_arena_content_type(self) -> None:
        """normalize() sets platform='gab', arena='social_media', content_type='post'."""
        collector = self._collector()
        result = collector.normalize(_first_status())

        assert result["platform"] == "gab"
        assert result["arena"] == "social_media"
        assert result["content_type"] == "post"

    def test_normalize_platform_id_is_status_id(self) -> None:
        """normalize() sets platform_id to the status id string."""
        collector = self._collector()
        status = _first_status()
        result = collector.normalize(status)

        assert result["platform_id"] == status["id"]

    def test_normalize_strips_html_from_content(self) -> None:
        """normalize() strips HTML tags from the content field for text_content."""
        collector = self._collector()
        status = {
            **_first_status(),
            "content": "<p>Dette er en <strong>vigtig</strong> besked.</p>",
        }
        result = collector.normalize(status)

        assert "<p>" not in result["text_content"]
        assert "<strong>" not in result["text_content"]
        assert "Dette er en" in result["text_content"]
        assert "vigtig" in result["text_content"]

    def test_normalize_url_from_url_field(self) -> None:
        """normalize() maps the 'url' field directly."""
        collector = self._collector()
        status = _first_status()
        result = collector.normalize(status)

        assert result["url"] == status["url"]

    def test_normalize_language_preserved(self) -> None:
        """normalize() maps the 'language' field to the output language."""
        collector = self._collector()
        result = collector.normalize(_first_status())

        assert result["language"] == "da"

    def test_normalize_author_display_name_from_account(self) -> None:
        """normalize() extracts display_name from the account dict."""
        collector = self._collector()
        status = _first_status()
        result = collector.normalize(status)

        assert result["author_display_name"] == status["account"]["display_name"]

    def test_normalize_pseudonymized_author_id_set_when_author_present(self) -> None:
        """normalize() computes pseudonymized_author_id when account id is present."""
        collector = self._collector()
        result = collector.normalize(_first_status())

        assert result["pseudonymized_author_id"] is not None
        assert len(result["pseudonymized_author_id"]) == 64

    def test_normalize_no_account_produces_none_author_fields(self) -> None:
        """normalize() sets author fields to None when account is absent."""
        collector = self._collector()
        status = {**_first_status(), "account": None}
        result = collector.normalize(status)

        assert result["author_display_name"] is None
        assert result["pseudonymized_author_id"] is None

    def test_normalize_media_urls_from_attachments(self) -> None:
        """normalize() populates media_urls from media_attachments array."""
        collector = self._collector()
        second_status = _load_search_fixture()["statuses"][1]
        result = collector.normalize(second_status)

        assert isinstance(result["media_urls"], list)
        assert len(result["media_urls"]) == 1
        assert "gab.com" in result["media_urls"][0]

    def test_normalize_no_attachments_produces_empty_media_urls(self) -> None:
        """normalize() produces empty or absent media_urls when no attachments."""
        collector = self._collector()
        status = {**_first_status(), "media_attachments": []}
        result = collector.normalize(status)

        assert result.get("media_urls", []) == []

    def test_normalize_content_hash_is_64_char_hex(self) -> None:
        """normalize() computes a 64-character hex content_hash."""
        collector = self._collector()
        result = collector.normalize(_first_status())

        assert result["content_hash"] is not None
        assert len(result["content_hash"]) == 64
        assert all(c in "0123456789abcdef" for c in result["content_hash"])

    def test_normalize_required_fields_always_present(self) -> None:
        """All required schema fields are present in normalized output."""
        collector = self._collector()
        result = collector.normalize(_first_status())

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field is None: {field}"

    def test_normalize_collection_tier_is_free(self) -> None:
        """normalize() sets collection_tier='free' (Gab is FREE-only)."""
        collector = self._collector()
        result = collector.normalize(_first_status())

        assert result["collection_tier"] == "free"

    def test_normalize_reblog_uses_original_content(self) -> None:
        """normalize() uses the original post content when the status is a reblog."""
        collector = self._collector()
        original = _first_status()
        reblog_status = {
            "id": "999888777666555444",
            "created_at": "2026-02-15T10:00:00.000Z",
            "url": "https://gab.com/@reblogger/999888777666555444",
            "uri": "https://gab.com/users/reblogger/statuses/999888777666555444",
            "content": "",
            "language": "da",
            "account": {
                "id": "9911111",
                "username": "reblogger",
                "display_name": "Reblogger",
                "acct": "reblogger",
            },
            "reblogs_count": 0,
            "favourites_count": 0,
            "replies_count": 0,
            "reblog": original,
            "media_attachments": [],
        }
        result = collector.normalize(reblog_status)

        # The text_content should come from the original post, not the empty reblog wrapper.
        assert result["text_content"] is not None
        assert len(result["text_content"]) > 0

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_preserves_danish_character_in_content(self, char: str) -> None:
        """Each Danish character in content survives HTML stripping in normalize()."""
        collector = self._collector()
        status = {
            **_first_status(),
            "content": f"<p>En status med {char} tegn i teksten.</p>",
        }
        result = collector.normalize(status)

        assert char in result["text_content"]

    def test_normalize_preserves_danish_text_from_fixture(self) -> None:
        """Danish characters from the full fixture survive normalize()."""
        collector = self._collector()
        result = collector.normalize(_first_status())

        text = result.get("text_content", "")
        assert "ø" in text or "æ" in text or "Å" in text or "å" in text


# ---------------------------------------------------------------------------
# collect_by_terms() integration tests
# ---------------------------------------------------------------------------


class TestCollectByTerms:
    @pytest.mark.asyncio
    async def test_collect_by_terms_returns_records(self) -> None:
        """collect_by_terms() returns non-empty list when search API returns statuses."""
        fixture = _load_search_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(GAB_SEARCH_ENDPOINT).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = GabCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["grøn omstilling"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert isinstance(records, list)
        assert len(records) > 0
        assert records[0]["platform"] == "gab"
        assert records[0]["content_type"] == "post"

    @pytest.mark.asyncio
    async def test_collect_by_terms_empty_response_returns_empty_list(self) -> None:
        """collect_by_terms() returns [] when API returns empty statuses list."""
        pool = _make_mock_pool()
        empty_response = {"statuses": [], "accounts": [], "hashtags": []}

        with respx.mock:
            respx.get(GAB_SEARCH_ENDPOINT).mock(
                return_value=httpx.Response(200, json=empty_response)
            )
            collector = GabCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["nonexistent_xyz_query"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_429_raises_rate_limit_error(self) -> None:
        """collect_by_terms() raises ArenaRateLimitError on HTTP 429 from Gab API."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(GAB_SEARCH_ENDPOINT).mock(
                return_value=httpx.Response(429, headers={"Retry-After": "60"})
            )
            collector = GabCollector(credential_pool=pool)
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_terms(
                    terms=["test"],
                    tier=Tier.FREE,
                    max_results=5,
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_401_raises_auth_error(self) -> None:
        """collect_by_terms() raises ArenaAuthError on HTTP 401 from Gab API."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(GAB_SEARCH_ENDPOINT).mock(
                return_value=httpx.Response(401)
            )
            collector = GabCollector(credential_pool=pool)
            with pytest.raises(ArenaAuthError):
                await collector.collect_by_terms(
                    terms=["test"],
                    tier=Tier.FREE,
                    max_results=5,
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_missing_access_token_raises_auth_error(self) -> None:
        """collect_by_terms() raises ArenaAuthError when credential lacks 'access_token'."""
        pool = MagicMock()
        pool.acquire = AsyncMock(
            return_value={"id": "cred-no-token", "client_id": "some-id"}
        )
        pool.release = AsyncMock(return_value=None)

        collector = GabCollector(credential_pool=pool)
        with pytest.raises(ArenaAuthError):
            await collector.collect_by_terms(
                terms=["test"],
                tier=Tier.FREE,
                max_results=5,
            )

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_422_is_skipped_not_raised(self) -> None:
        """collect_by_terms() returns [] and does not raise on HTTP 422 (search restricted)."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(GAB_SEARCH_ENDPOINT).mock(
                return_value=httpx.Response(422)
            )
            collector = GabCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["ordinary_keyword"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_hashtag_falls_back_to_timeline(self) -> None:
        """collect_by_terms() falls back to hashtag timeline when search returns [] for #tag."""
        timeline_fixture = _load_hashtag_timeline_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            # Search returns empty list.
            respx.get(GAB_SEARCH_ENDPOINT).mock(
                return_value=httpx.Response(200, json={"statuses": [], "accounts": [], "hashtags": []})
            )
            # Hashtag timeline URL ends with /tag/dkpol.
            respx.get(GAB_HASHTAG_TIMELINE_ENDPOINT.format(hashtag="dkpol")).mock(
                return_value=httpx.Response(200, json=timeline_fixture)
            )
            collector = GabCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["#dkpol"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert isinstance(records, list)
        assert len(records) > 0
        assert records[0]["platform"] == "gab"

    @pytest.mark.asyncio
    async def test_collect_by_terms_danish_text_preserved_end_to_end(self) -> None:
        """Danish characters in Gab posts survive the full collect -> normalize pipeline."""
        fixture = _load_search_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(GAB_SEARCH_ENDPOINT).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = GabCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["velfærd"],
                tier=Tier.FREE,
                max_results=10,
            )

        texts = [r.get("text_content", "") or "" for r in records]
        assert any("ø" in t or "æ" in t or "å" in t or "Å" in t for t in texts)

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_tier_proceeds_as_free(self) -> None:
        """collect_by_terms() logs warning and proceeds when MEDIUM tier is requested."""
        fixture = _load_search_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(GAB_SEARCH_ENDPOINT).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = GabCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["test"],
                tier=Tier.MEDIUM,
                max_results=5,
            )

        assert isinstance(records, list)


# ---------------------------------------------------------------------------
# collect_by_actors() tests
# ---------------------------------------------------------------------------


class TestCollectByActors:
    @pytest.mark.asyncio
    async def test_collect_by_actors_numeric_id_skips_lookup(self) -> None:
        """collect_by_actors() uses a numeric actor_id directly without an account lookup."""
        fixture_statuses = _load_search_fixture()["statuses"]
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(GAB_ACCOUNT_STATUSES_ENDPOINT.format(account_id="9900011")).mock(
                return_value=httpx.Response(200, json=fixture_statuses)
            )
            collector = GabCollector(credential_pool=pool)
            records = await collector.collect_by_actors(
                actor_ids=["9900011"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert isinstance(records, list)
        assert len(records) > 0
        assert records[0]["platform"] == "gab"

    @pytest.mark.asyncio
    async def test_collect_by_actors_resolves_username_to_id(self) -> None:
        """collect_by_actors() looks up username via account lookup endpoint."""
        fixture_statuses = _load_search_fixture()["statuses"]
        pool = _make_mock_pool()
        lookup_response = {"id": "9900011", "username": "dansk_debat"}

        with respx.mock:
            respx.get(GAB_ACCOUNT_LOOKUP_ENDPOINT).mock(
                return_value=httpx.Response(200, json=lookup_response)
            )
            respx.get(GAB_ACCOUNT_STATUSES_ENDPOINT.format(account_id="9900011")).mock(
                return_value=httpx.Response(200, json=fixture_statuses)
            )
            collector = GabCollector(credential_pool=pool)
            records = await collector.collect_by_actors(
                actor_ids=["dansk_debat"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert len(records) > 0

    @pytest.mark.asyncio
    async def test_collect_by_actors_unknown_username_returns_empty(self) -> None:
        """collect_by_actors() returns [] when account lookup fails for unknown username."""
        pool = _make_mock_pool()

        with respx.mock:
            # Account lookup returns 404 (account not found).
            respx.get(GAB_ACCOUNT_LOOKUP_ENDPOINT).mock(
                return_value=httpx.Response(404)
            )
            collector = GabCollector(credential_pool=pool)
            records = await collector.collect_by_actors(
                actor_ids=["nonexistent_user_xyz"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_actors_http_429_raises_rate_limit_error(self) -> None:
        """collect_by_actors() raises ArenaRateLimitError on HTTP 429."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(GAB_ACCOUNT_STATUSES_ENDPOINT.format(account_id="9900011")).mock(
                return_value=httpx.Response(429, headers={"Retry-After": "30"})
            )
            collector = GabCollector(credential_pool=pool)
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_actors(
                    actor_ids=["9900011"],
                    tier=Tier.FREE,
                    max_results=5,
                )


# ---------------------------------------------------------------------------
# Tier validation tests
# ---------------------------------------------------------------------------


class TestTierValidation:
    def test_supported_tiers_contains_only_free(self) -> None:
        """GabCollector.supported_tiers contains only [Tier.FREE]."""
        collector = GabCollector()
        assert collector.supported_tiers == [Tier.FREE]

    def test_get_tier_config_free_returns_config(self) -> None:
        """get_tier_config(Tier.FREE) returns a TierConfig."""
        collector = GabCollector()
        config = collector.get_tier_config(Tier.FREE)

        assert config is not None
        assert config.requires_credential is True

    def test_get_tier_config_medium_returns_none(self) -> None:
        """get_tier_config(Tier.MEDIUM) returns None (not available)."""
        collector = GabCollector()
        assert collector.get_tier_config(Tier.MEDIUM) is None

    def test_get_tier_config_premium_returns_none(self) -> None:
        """get_tier_config(Tier.PREMIUM) returns None (not available)."""
        collector = GabCollector()
        assert collector.get_tier_config(Tier.PREMIUM) is None


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_ok_on_200_timeline(self) -> None:
        """health_check() returns status='ok' when public timeline returns 200."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(GAB_PUBLIC_TIMELINE_ENDPOINT).mock(
                return_value=httpx.Response(200, json=[{"id": "1"}])
            )
            collector = GabCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "social_media"
        assert result["platform"] == "gab"
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_when_timeline_fails_but_instance_ok(
        self,
    ) -> None:
        """health_check() returns status='degraded' when timeline fails but instance endpoint responds."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(GAB_PUBLIC_TIMELINE_ENDPOINT).mock(
                return_value=httpx.Response(503)
            )
            respx.get(GAB_INSTANCE_ENDPOINT).mock(
                return_value=httpx.Response(200, json={"uri": "gab.com", "title": "Gab"})
            )
            collector = GabCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_health_check_returns_down_when_both_endpoints_fail(self) -> None:
        """health_check() returns status='down' when both timeline and instance endpoints fail."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(GAB_PUBLIC_TIMELINE_ENDPOINT).mock(
                return_value=httpx.Response(503)
            )
            respx.get(GAB_INSTANCE_ENDPOINT).mock(
                return_value=httpx.Response(503)
            )
            collector = GabCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "down"

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_no_credential(self) -> None:
        """health_check() returns status='down' when no credential pool is configured."""
        collector = GabCollector(credential_pool=None)
        result = await collector.health_check()

        assert result["status"] == "down"
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_always_has_arena_platform_checked_at(self) -> None:
        """health_check() always includes arena, platform, and checked_at regardless of outcome."""
        collector = GabCollector(credential_pool=None)
        result = await collector.health_check()

        assert result["arena"] == "social_media"
        assert result["platform"] == "gab"
        assert "checked_at" in result
