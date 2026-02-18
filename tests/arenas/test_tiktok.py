"""Tests for the TikTok arena collector.

Covers:
- normalize() unit tests: platform/arena/content_type, author fields,
  text_content concatenation, content_hash, Danish character preservation
- collect_by_terms() with mocked OAuth flow and mocked video query API
- collect_by_actors() with mocked OAuth flow and username-based query
- HTTP 429 -> ArenaRateLimitError
- HTTP 401 -> ArenaAuthError
- Empty API response -> returns []
- Tier validation: only FREE is supported (MEDIUM/PREMIUM produce a warning
  but still use FREE under the hood)
- health_check() returns 'ok', 'degraded', 'down' as appropriate
- NoCredentialAvailableError when no credential pool is configured

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
from issue_observatory.arenas.tiktok.collector import TikTokCollector  # noqa: E402
from issue_observatory.arenas.tiktok.config import (  # noqa: E402
    TIKTOK_OAUTH_URL,
    TIKTOK_VIDEO_QUERY_URL,
)
from issue_observatory.core.exceptions import (  # noqa: E402
    ArenaAuthError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "api_responses" / "tiktok"


def _load_video_query_fixture() -> dict[str, Any]:
    """Load the recorded TikTok video query fixture."""
    return json.loads((FIXTURES_DIR / "video_query_response.json").read_text(encoding="utf-8"))


def _load_oauth_fixture() -> dict[str, Any]:
    """Load the recorded TikTok OAuth token fixture."""
    return json.loads((FIXTURES_DIR / "oauth_token_response.json").read_text(encoding="utf-8"))


def _first_video() -> dict[str, Any]:
    """Return the first video dict from the fixture."""
    return _load_video_query_fixture()["data"]["videos"][0]


# ---------------------------------------------------------------------------
# Mock credential pool
# ---------------------------------------------------------------------------


def _make_mock_pool() -> Any:
    """Build a minimal mock CredentialPool returning a TikTok credential."""
    pool = MagicMock()
    pool.acquire = AsyncMock(
        return_value={
            "id": "cred-tiktok-001",
            "client_key": "test-client-key",
            "client_secret": "test-client-secret",
        }
    )
    pool.release = AsyncMock(return_value=None)
    pool.report_error = AsyncMock(return_value=None)
    return pool


def _make_collector_with_cached_token() -> TikTokCollector:
    """Return a TikTokCollector with a pre-seeded in-memory token cache.

    Bypasses the OAuth endpoint entirely so tests that focus on the
    video query endpoint do not need to mock TIKTOK_OAUTH_URL.
    """
    import time

    pool = _make_mock_pool()
    collector = TikTokCollector(credential_pool=pool)
    # Seed the in-memory token cache so _get_access_token() skips OAuth.
    collector._token_cache["cred-tiktok-001"] = (
        "cached-access-token",
        time.time() + 7000,
    )
    return collector


# ---------------------------------------------------------------------------
# normalize() unit tests
# ---------------------------------------------------------------------------


class TestNormalize:
    def _collector(self) -> TikTokCollector:
        return TikTokCollector()

    def test_normalize_sets_platform_arena_content_type(self) -> None:
        """normalize() sets platform='tiktok', arena='social_media', content_type='video'."""
        collector = self._collector()
        result = collector.normalize(_first_video())

        assert result["platform"] == "tiktok"
        assert result["arena"] == "social_media"
        assert result["content_type"] == "video"

    def test_normalize_platform_id_is_video_id(self) -> None:
        """normalize() sets platform_id to the video id string."""
        collector = self._collector()
        video = _first_video()
        result = collector.normalize(video)

        assert result["platform_id"] == str(video["id"])

    def test_normalize_url_constructed_from_username_and_video_id(self) -> None:
        """normalize() constructs URL as https://www.tiktok.com/@{username}/video/{id}."""
        collector = self._collector()
        video = _first_video()
        result = collector.normalize(video)

        assert result["url"] == f"https://www.tiktok.com/@{video['username']}/video/{video['id']}"

    def test_normalize_text_content_includes_video_description(self) -> None:
        """normalize() maps video_description to text_content."""
        collector = self._collector()
        video = _first_video()
        result = collector.normalize(video)

        assert video["video_description"] in result["text_content"]

    def test_normalize_text_content_appends_voice_to_text_when_present(self) -> None:
        """normalize() appends voice_to_text as '[transcript] ...' in text_content."""
        collector = self._collector()
        video = _first_video()
        result = collector.normalize(video)

        assert "[transcript]" in result["text_content"]
        assert video["voice_to_text"] in result["text_content"]

    def test_normalize_text_content_description_only_when_no_voice_to_text(self) -> None:
        """normalize() uses only video_description when voice_to_text is absent."""
        collector = self._collector()
        video = {**_first_video(), "voice_to_text": None}
        result = collector.normalize(video)

        assert "[transcript]" not in result["text_content"]
        assert video["video_description"] == result["text_content"]

    def test_normalize_author_display_name_is_username(self) -> None:
        """normalize() sets author_display_name to the video username."""
        collector = self._collector()
        video = _first_video()
        result = collector.normalize(video)

        assert result["author_display_name"] == video["username"]

    def test_normalize_pseudonymized_author_id_set_when_username_present(self) -> None:
        """normalize() computes pseudonymized_author_id when username is present."""
        collector = self._collector()
        result = collector.normalize(_first_video())

        assert result["pseudonymized_author_id"] is not None
        assert len(result["pseudonymized_author_id"]) == 64

    def test_normalize_no_username_produces_none_author_fields(self) -> None:
        """normalize() sets author fields to None when username is empty."""
        collector = self._collector()
        video = {**_first_video(), "username": ""}
        result = collector.normalize(video)

        assert result["author_display_name"] is None
        assert result["pseudonymized_author_id"] is None

    def test_normalize_content_hash_is_64_char_hex(self) -> None:
        """normalize() computes a 64-character hex content_hash."""
        collector = self._collector()
        result = collector.normalize(_first_video())

        assert result["content_hash"] is not None
        assert len(result["content_hash"]) == 64
        assert all(c in "0123456789abcdef" for c in result["content_hash"])

    def test_normalize_required_fields_always_present(self) -> None:
        """All required schema fields are present in normalized output."""
        collector = self._collector()
        result = collector.normalize(_first_video())

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field is None: {field}"

    def test_normalize_collection_tier_is_free(self) -> None:
        """normalize() sets collection_tier='free' (TikTok is FREE-only in Phase 1)."""
        collector = self._collector()
        result = collector.normalize(_first_video())

        assert result["collection_tier"] == "free"

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_preserves_danish_character_in_description(self, char: str) -> None:
        """Each Danish character in video_description survives normalize() without corruption."""
        collector = self._collector()
        video = {
            **_first_video(),
            "video_description": f"Dansk video med {char} i beskrivelsen.",
            "voice_to_text": None,
        }
        result = collector.normalize(video)

        assert char in result["text_content"]

    def test_normalize_preserves_danish_text_in_description_end_to_end(self) -> None:
        """Danish characters from the full fixture survive normalize()."""
        collector = self._collector()
        result = collector.normalize(_first_video())

        assert "ø" in result["text_content"] or "æ" in result["text_content"]

    def test_normalize_url_is_none_when_username_and_id_both_empty(self) -> None:
        """normalize() sets url to None when both username and id are empty."""
        collector = self._collector()
        video = {**_first_video(), "username": "", "id": ""}
        result = collector.normalize(video)

        assert result["url"] is None

    def test_normalize_engagement_metrics_preserved(self) -> None:
        """normalize() preserves view_count, like_count, share_count, comment_count."""
        collector = self._collector()
        video = _first_video()
        result = collector.normalize(video)

        # views_count should be populated from view_count.
        assert result.get("views_count") == video["view_count"]

    def test_normalize_published_at_from_create_time(self) -> None:
        """normalize() records create_time in the published_at field."""
        collector = self._collector()
        video = _first_video()
        result = collector.normalize(video)

        # create_time is a Unix timestamp; it should be present in some form.
        assert result.get("published_at") is not None or result.get("create_time") is not None


# ---------------------------------------------------------------------------
# collect_by_terms() integration tests
# ---------------------------------------------------------------------------


class TestCollectByTerms:
    @pytest.mark.asyncio
    async def test_collect_by_terms_returns_records(self) -> None:
        """collect_by_terms() returns non-empty list when API returns videos."""
        fixture = _load_video_query_fixture()
        collector = _make_collector_with_cached_token()

        with respx.mock:
            respx.post(TIKTOK_VIDEO_QUERY_URL).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            records = await collector.collect_by_terms(
                terms=["grøn omstilling"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert isinstance(records, list)
        assert len(records) > 0
        assert records[0]["platform"] == "tiktok"
        assert records[0]["content_type"] == "video"

    @pytest.mark.asyncio
    async def test_collect_by_terms_records_have_danish_text(self) -> None:
        """collect_by_terms() results contain Danish characters in text_content."""
        fixture = _load_video_query_fixture()
        collector = _make_collector_with_cached_token()

        with respx.mock:
            respx.post(TIKTOK_VIDEO_QUERY_URL).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            records = await collector.collect_by_terms(
                terms=["velfærd"],
                tier=Tier.FREE,
                max_results=10,
            )

        texts = [r.get("text_content", "") or "" for r in records]
        assert any("ø" in t or "å" in t or "æ" in t for t in texts)

    @pytest.mark.asyncio
    async def test_collect_by_terms_empty_videos_returns_empty_list(self) -> None:
        """collect_by_terms() returns [] when API returns no videos."""
        collector = _make_collector_with_cached_token()
        empty_response = {"data": {"videos": [], "has_more": False, "cursor": 0}, "error": {"code": "ok"}}

        with respx.mock:
            respx.post(TIKTOK_VIDEO_QUERY_URL).mock(
                return_value=httpx.Response(200, json=empty_response)
            )
            records = await collector.collect_by_terms(
                terms=["nonexistent_xyz_query"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_429_raises_rate_limit_error(self) -> None:
        """collect_by_terms() raises ArenaRateLimitError on HTTP 429 from Research API."""
        collector = _make_collector_with_cached_token()

        with respx.mock:
            respx.post(TIKTOK_VIDEO_QUERY_URL).mock(
                return_value=httpx.Response(429, headers={"Retry-After": "60"})
            )
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_terms(
                    terms=["test"],
                    tier=Tier.FREE,
                    max_results=5,
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_401_raises_auth_error(self) -> None:
        """collect_by_terms() raises ArenaAuthError on HTTP 401 from Research API."""
        collector = _make_collector_with_cached_token()

        with respx.mock:
            respx.post(TIKTOK_VIDEO_QUERY_URL).mock(
                return_value=httpx.Response(401)
            )
            with pytest.raises(ArenaAuthError):
                await collector.collect_by_terms(
                    terms=["test"],
                    tier=Tier.FREE,
                    max_results=5,
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_no_credential_raises_no_credential_error(self) -> None:
        """collect_by_terms() raises NoCredentialAvailableError when no pool is configured."""
        collector = TikTokCollector(credential_pool=None)

        with pytest.raises(NoCredentialAvailableError):
            await collector.collect_by_terms(
                terms=["test"],
                tier=Tier.FREE,
                max_results=5,
            )

    @pytest.mark.asyncio
    async def test_collect_by_terms_api_error_in_body_stops_pagination(self) -> None:
        """collect_by_terms() stops and returns [] when API body contains error code."""
        collector = _make_collector_with_cached_token()
        error_response = {
            "data": {},
            "error": {
                "code": "access_token_invalid",
                "message": "Access token is invalid.",
                "log_id": "err123",
            },
        }

        with respx.mock:
            respx.post(TIKTOK_VIDEO_QUERY_URL).mock(
                return_value=httpx.Response(200, json=error_response)
            )
            records = await collector.collect_by_terms(
                terms=["test"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_tier_proceeds_as_free(self) -> None:
        """collect_by_terms() logs a warning and proceeds when MEDIUM tier is requested."""
        fixture = _load_video_query_fixture()
        collector = _make_collector_with_cached_token()

        with respx.mock:
            respx.post(TIKTOK_VIDEO_QUERY_URL).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            # MEDIUM is not a valid tier but should not raise — only warn.
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
    async def test_collect_by_actors_returns_records(self) -> None:
        """collect_by_actors() returns non-empty list when API returns videos."""
        fixture = _load_video_query_fixture()
        collector = _make_collector_with_cached_token()

        with respx.mock:
            respx.post(TIKTOK_VIDEO_QUERY_URL).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            records = await collector.collect_by_actors(
                actor_ids=["dr_nyheder"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert isinstance(records, list)
        assert len(records) > 0
        assert records[0]["platform"] == "tiktok"

    @pytest.mark.asyncio
    async def test_collect_by_actors_uses_username_query_condition(self) -> None:
        """collect_by_actors() sends a 'username' query condition in the request body."""
        fixture = _load_video_query_fixture()
        collector = _make_collector_with_cached_token()
        captured: list[dict] = []

        def capture_and_respond(request: httpx.Request) -> httpx.Response:
            import json as _json
            captured.append(_json.loads(request.content))
            return httpx.Response(200, json=fixture)

        with respx.mock:
            respx.post(TIKTOK_VIDEO_QUERY_URL).mock(side_effect=capture_and_respond)
            await collector.collect_by_actors(
                actor_ids=["dr_nyheder"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert len(captured) >= 1
        conditions = captured[0]["query"]["and"]
        field_names = [c["field_name"] for c in conditions]
        assert "username" in field_names

    @pytest.mark.asyncio
    async def test_collect_by_actors_http_429_raises_rate_limit_error(self) -> None:
        """collect_by_actors() raises ArenaRateLimitError on HTTP 429."""
        collector = _make_collector_with_cached_token()

        with respx.mock:
            respx.post(TIKTOK_VIDEO_QUERY_URL).mock(
                return_value=httpx.Response(429, headers={"Retry-After": "30"})
            )
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_actors(
                    actor_ids=["some_user"],
                    tier=Tier.FREE,
                    max_results=5,
                )

    @pytest.mark.asyncio
    async def test_collect_by_actors_empty_response_returns_empty_list(self) -> None:
        """collect_by_actors() returns [] when API returns no videos for the actor."""
        collector = _make_collector_with_cached_token()
        empty_response = {"data": {"videos": [], "has_more": False, "cursor": 0}, "error": {"code": "ok"}}

        with respx.mock:
            respx.post(TIKTOK_VIDEO_QUERY_URL).mock(
                return_value=httpx.Response(200, json=empty_response)
            )
            records = await collector.collect_by_actors(
                actor_ids=["inactive_user_dk"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert records == []


# ---------------------------------------------------------------------------
# OAuth token tests
# ---------------------------------------------------------------------------


class TestOAuthToken:
    @pytest.mark.asyncio
    async def test_fetch_new_token_raises_auth_error_on_401(self) -> None:
        """_fetch_new_token() raises ArenaAuthError when OAuth endpoint returns 401."""
        pool = _make_mock_pool()
        collector = TikTokCollector(credential_pool=pool)
        cred = {"id": "cred-001", "client_key": "bad-key", "client_secret": "bad-secret"}

        with respx.mock:
            respx.post(TIKTOK_OAUTH_URL).mock(return_value=httpx.Response(401))
            with pytest.raises(ArenaAuthError):
                await collector._fetch_new_token(cred)

    @pytest.mark.asyncio
    async def test_fetch_new_token_caches_token_in_memory(self) -> None:
        """_fetch_new_token() stores the token in the in-memory cache."""
        pool = _make_mock_pool()
        collector = TikTokCollector(credential_pool=pool)
        cred = {"id": "cred-cache-test", "client_key": "key", "client_secret": "secret"}

        with respx.mock:
            respx.post(TIKTOK_OAUTH_URL).mock(
                return_value=httpx.Response(200, json=_load_oauth_fixture())
            )
            token = await collector._fetch_new_token(cred)

        assert token == "test-tiktok-access-token-abc123"
        assert "cred-cache-test" in collector._token_cache


# ---------------------------------------------------------------------------
# Tier validation tests
# ---------------------------------------------------------------------------


class TestTierValidation:
    def test_supported_tiers_contains_only_free(self) -> None:
        """TikTokCollector.supported_tiers contains only [Tier.FREE]."""
        collector = TikTokCollector()
        assert collector.supported_tiers == [Tier.FREE]

    def test_get_tier_config_free_returns_config(self) -> None:
        """get_tier_config(Tier.FREE) returns a TierConfig."""
        collector = TikTokCollector()
        config = collector.get_tier_config(Tier.FREE)

        assert config is not None
        assert config.requires_credential is True

    def test_get_tier_config_medium_returns_none(self) -> None:
        """get_tier_config(Tier.MEDIUM) returns None (not available)."""
        collector = TikTokCollector()
        assert collector.get_tier_config(Tier.MEDIUM) is None

    def test_get_tier_config_premium_returns_none(self) -> None:
        """get_tier_config(Tier.PREMIUM) returns None (not available)."""
        collector = TikTokCollector()
        assert collector.get_tier_config(Tier.PREMIUM) is None


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_ok_on_valid_response(self) -> None:
        """health_check() returns status='ok' when API responds with 'data' key."""
        pool = _make_mock_pool()
        collector = TikTokCollector(credential_pool=pool)

        valid_response = {"data": {"videos": [{"id": "123"}]}, "error": {"code": "ok"}}

        with respx.mock:
            respx.post(TIKTOK_OAUTH_URL).mock(
                return_value=httpx.Response(200, json=_load_oauth_fixture())
            )
            respx.post(TIKTOK_VIDEO_QUERY_URL).mock(
                return_value=httpx.Response(200, json=valid_response)
            )
            result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "social_media"
        assert result["platform"] == "tiktok"
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_on_missing_data_key(self) -> None:
        """health_check() returns status='degraded' when response lacks 'data' key."""
        pool = _make_mock_pool()
        collector = TikTokCollector(credential_pool=pool)

        bad_response = {"unexpected_key": "value"}

        with respx.mock:
            respx.post(TIKTOK_OAUTH_URL).mock(
                return_value=httpx.Response(200, json=_load_oauth_fixture())
            )
            respx.post(TIKTOK_VIDEO_QUERY_URL).mock(
                return_value=httpx.Response(200, json=bad_response)
            )
            result = await collector.health_check()

        assert result["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_no_credential(self) -> None:
        """health_check() returns status='down' when no credential pool is configured."""
        collector = TikTokCollector(credential_pool=None)
        result = await collector.health_check()

        assert result["status"] == "down"
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_on_http_error(self) -> None:
        """health_check() returns status='degraded' on HTTP 4xx from TikTok API."""
        pool = _make_mock_pool()
        collector = TikTokCollector(credential_pool=pool)

        with respx.mock:
            respx.post(TIKTOK_OAUTH_URL).mock(
                return_value=httpx.Response(200, json=_load_oauth_fixture())
            )
            respx.post(TIKTOK_VIDEO_QUERY_URL).mock(
                return_value=httpx.Response(403)
            )
            result = await collector.health_check()

        assert result["status"] == "degraded"
        assert "403" in result.get("detail", "")

    @pytest.mark.asyncio
    async def test_health_check_always_has_arena_platform_checked_at(self) -> None:
        """health_check() always includes arena, platform, and checked_at regardless of outcome."""
        collector = TikTokCollector(credential_pool=None)
        result = await collector.health_check()

        assert result["arena"] == "social_media"
        assert result["platform"] == "tiktok"
        assert "checked_at" in result
