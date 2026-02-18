"""Tests for the Facebook arena collector.

Covers:
- normalize() unit tests: Bright Data field mapping, comment detection, reaction
  aggregation, media URL extraction
- normalize() MCL path: field mapping from Meta Content Library dict
- collect_by_terms() / collect_by_actors(): full Bright Data async dataset
  cycle (trigger -> poll -> download) with respx mocks
- HTTP 429 -> ArenaRateLimitError, HTTP 401/403 -> ArenaAuthError
- PREMIUM tier raises NotImplementedError
- FREE tier raises ValueError (unsupported)
- health_check() ok / degraded / down paths
- Danish character preservation: ae, o, a throughout
- content_hash is a 64-char hex string

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
from issue_observatory.arenas.facebook.collector import FacebookCollector  # noqa: E402
from issue_observatory.arenas.facebook.config import (  # noqa: E402
    BRIGHTDATA_TRIGGER_URL,
    BRIGHTDATA_PROGRESS_URL,
    BRIGHTDATA_SNAPSHOT_URL,
)
from issue_observatory.core.exceptions import (  # noqa: E402
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "api_responses" / "facebook"

_SNAPSHOT_ID = "snap_fb_test_001"
_PROGRESS_URL = BRIGHTDATA_PROGRESS_URL.format(snapshot_id=_SNAPSHOT_ID)
_SNAPSHOT_URL = BRIGHTDATA_SNAPSHOT_URL.format(snapshot_id=_SNAPSHOT_ID)


def _load_snapshot_fixture() -> list[dict[str, Any]]:
    """Load the recorded Bright Data Facebook snapshot fixture."""
    return json.loads(
        (FIXTURES_DIR / "brightdata_snapshot_response.json").read_text(encoding="utf-8")
    )


def _first_post() -> dict[str, Any]:
    """Return the first post dict from the fixture (a regular post with reactions)."""
    return _load_snapshot_fixture()[0]


def _comment_post() -> dict[str, Any]:
    """Return the comment post dict from the fixture (has comment_id set)."""
    return _load_snapshot_fixture()[4]


# ---------------------------------------------------------------------------
# Mock credential pool
# ---------------------------------------------------------------------------


def _make_mock_pool() -> Any:
    """Build a minimal mock CredentialPool returning a Bright Data Facebook credential."""
    pool = MagicMock()
    pool.acquire = AsyncMock(
        return_value={
            "id": "cred-fb-001",
            "api_token": "test-bd-facebook-api-token",
        }
    )
    pool.release = AsyncMock(return_value=None)
    pool.report_error = AsyncMock(return_value=None)
    return pool


# ---------------------------------------------------------------------------
# Helper: build a pre-wired collector with injected HTTP client
# ---------------------------------------------------------------------------


def _make_collector_with_client(
    http_client: httpx.AsyncClient,
    pool: Any = None,
) -> FacebookCollector:
    """Return a FacebookCollector with an injected HTTP client and optional pool."""
    return FacebookCollector(
        credential_pool=pool or _make_mock_pool(),
        http_client=http_client,
    )


# ---------------------------------------------------------------------------
# Helpers: mock the three Bright Data endpoints
# ---------------------------------------------------------------------------


def _mock_brightdata_full_cycle(
    snapshot_data: list[dict[str, Any]],
) -> None:
    """Register respx routes for trigger -> poll-ready -> download cycle."""
    # Trigger: POST returns snapshot_id
    respx.post(BRIGHTDATA_TRIGGER_URL).mock(
        return_value=httpx.Response(200, json={"snapshot_id": _SNAPSHOT_ID})
    )
    # Progress: GET returns status=ready immediately
    respx.get(_PROGRESS_URL).mock(
        return_value=httpx.Response(200, json={"status": "ready"})
    )
    # Snapshot: GET returns the records list
    respx.get(_SNAPSHOT_URL).mock(
        return_value=httpx.Response(200, json=snapshot_data)
    )


# ---------------------------------------------------------------------------
# normalize() unit tests — Bright Data path
# ---------------------------------------------------------------------------


class TestNormalizeBrightData:
    def _collector(self) -> FacebookCollector:
        return FacebookCollector()

    def test_normalize_sets_platform_and_arena(self) -> None:
        """normalize() sets platform='facebook', arena='social_media'."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert result["platform"] == "facebook"
        assert result["arena"] == "social_media"

    def test_normalize_content_type_post_for_regular_post(self) -> None:
        """normalize() sets content_type='post' when no comment_id is present."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert result["content_type"] == "post"

    def test_normalize_content_type_comment_when_comment_id_present(self) -> None:
        """normalize() sets content_type='comment' when comment_id is present."""
        collector = self._collector()
        result = collector.normalize(_comment_post(), source="brightdata")

        assert result["content_type"] == "comment"

    def test_normalize_platform_id_from_post_id(self) -> None:
        """normalize() sets platform_id to the post_id field."""
        collector = self._collector()
        post = _first_post()
        result = collector.normalize(post, source="brightdata")

        assert result["platform_id"] == post["post_id"]

    def test_normalize_text_content_from_message_field(self) -> None:
        """normalize() maps 'message' to text_content."""
        collector = self._collector()
        post = _first_post()
        result = collector.normalize(post, source="brightdata")

        assert result["text_content"] == post["message"]

    def test_normalize_url_from_url_field(self) -> None:
        """normalize() maps 'url' to the url field."""
        collector = self._collector()
        post = _first_post()
        result = collector.normalize(post, source="brightdata")

        assert result["url"] == post["url"]

    def test_normalize_author_display_name_from_page_name(self) -> None:
        """normalize() maps 'page_name' to author_display_name."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert result["author_display_name"] == "DR Nyheder"

    def test_normalize_pseudonymized_author_id_set_when_author_present(self) -> None:
        """normalize() computes pseudonymized_author_id when page_name is present."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert result["pseudonymized_author_id"] is not None
        assert len(result["pseudonymized_author_id"]) == 64

    def test_normalize_likes_count_from_reactions_total(self) -> None:
        """normalize() sums reaction.total into likes_count."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert result["likes_count"] == 628

    def test_normalize_shares_count_from_shares_field(self) -> None:
        """normalize() maps 'shares' to shares_count."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert result["shares_count"] == 89

    def test_normalize_comments_count_from_comments_field(self) -> None:
        """normalize() maps 'comments' to comments_count."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert result["comments_count"] == 134

    def test_normalize_views_count_is_none_for_brightdata(self) -> None:
        """normalize() sets views_count=None (Bright Data does not expose views)."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert result["views_count"] is None

    def test_normalize_media_urls_from_image_url(self) -> None:
        """normalize() extracts image_url into media_urls list."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert isinstance(result["media_urls"], list)
        assert len(result["media_urls"]) >= 1
        assert "facebook.com" in result["media_urls"][0]

    def test_normalize_media_urls_empty_when_no_image(self) -> None:
        """normalize() returns empty media_urls when no image fields are set."""
        collector = self._collector()
        post = _load_snapshot_fixture()[3]  # fourth post has no image
        result = collector.normalize(post, source="brightdata")

        assert result["media_urls"] == []

    def test_normalize_published_at_from_created_time(self) -> None:
        """normalize() maps 'created_time' to published_at."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert result["published_at"] is not None
        assert "2026-02-15" in result["published_at"]

    def test_normalize_required_fields_always_present(self) -> None:
        """All required schema fields are present in normalized output."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field is None: {field}"

    def test_normalize_content_hash_is_64_char_hex(self) -> None:
        """normalize() computes a 64-character hex content_hash."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert result["content_hash"] is not None
        assert len(result["content_hash"]) == 64
        assert all(c in "0123456789abcdef" for c in result["content_hash"])

    def test_normalize_preserves_danish_text_in_message(self) -> None:
        """ae, o, a in Facebook message survive normalize() without corruption."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert "Grøn" in result["text_content"]
        assert "Ålborg" in result["text_content"]

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_handles_each_danish_character_in_message(self, char: str) -> None:
        """Each Danish character in Facebook message survives normalize() without error."""
        collector = self._collector()
        post = {**_first_post(), "message": f"Indhold med {char} tegn i opslaget."}
        result = collector.normalize(post, source="brightdata")

        assert char in result["text_content"]

    def test_normalize_null_shares_and_comments_produce_none(self) -> None:
        """normalize() maps null shares/comments to None engagement counts."""
        collector = self._collector()
        post = _load_snapshot_fixture()[3]  # fourth post has null shares/comments
        result = collector.normalize(post, source="brightdata")

        assert result["shares_count"] is None
        assert result["comments_count"] is None

    def test_normalize_url_constructed_from_post_id_when_missing(self) -> None:
        """normalize() constructs fallback URL from post_id when url field is null."""
        collector = self._collector()
        post = {**_first_post(), "url": None}
        result = collector.normalize(post, source="brightdata")

        assert result["url"] is not None
        assert "facebook.com" in result["url"]


# ---------------------------------------------------------------------------
# normalize() unit tests — MCL path
# ---------------------------------------------------------------------------


class TestNormalizeMCL:
    def _collector(self) -> FacebookCollector:
        return FacebookCollector()

    def _mcl_post(self) -> dict[str, Any]:
        return {
            "id": "mcl_post_001",
            "page_id": "mcl_page_001",
            "page_name": "DR Nyheder",
            "message": "Grøn omstilling diskuteres i Folketing.",
            "url": "https://www.facebook.com/watch?v=mcl_post_001",
            "creation_time": "2026-02-15T10:00:00+0000",
            "language": "da",
            "reactions_count": 500,
            "shares_count": 80,
            "comments_count": 120,
            "view_count": 10000,
        }

    def test_normalize_mcl_sets_platform_and_arena(self) -> None:
        """normalize(source='mcl') sets platform='facebook', arena='social_media'."""
        collector = self._collector()
        result = collector.normalize(self._mcl_post(), source="mcl")

        assert result["platform"] == "facebook"
        assert result["arena"] == "social_media"

    def test_normalize_mcl_content_type_is_post(self) -> None:
        """normalize(source='mcl') sets content_type='post'."""
        collector = self._collector()
        result = collector.normalize(self._mcl_post(), source="mcl")

        assert result["content_type"] == "post"

    def test_normalize_mcl_views_count_populated(self) -> None:
        """normalize(source='mcl') maps 'view_count' to views_count."""
        collector = self._collector()
        result = collector.normalize(self._mcl_post(), source="mcl")

        assert result["views_count"] == 10000

    def test_normalize_mcl_required_fields_present(self) -> None:
        """All required schema fields present for MCL-sourced records."""
        collector = self._collector()
        result = collector.normalize(self._mcl_post(), source="mcl")

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field is None: {field}"


# ---------------------------------------------------------------------------
# get_tier_config() / tier validation tests
# ---------------------------------------------------------------------------


class TestTierValidation:
    def test_free_tier_raises_value_error(self) -> None:
        """FacebookCollector does not support Tier.FREE and raises ValueError."""
        collector = FacebookCollector()
        with pytest.raises(ValueError, match="free"):
            collector.get_tier_config(Tier.FREE)

    def test_medium_tier_config_returned(self) -> None:
        """get_tier_config(Tier.MEDIUM) returns a non-None TierConfig."""
        collector = FacebookCollector()
        config = collector.get_tier_config(Tier.MEDIUM)
        assert config is not None

    def test_premium_tier_config_returned(self) -> None:
        """get_tier_config(Tier.PREMIUM) returns a non-None TierConfig."""
        collector = FacebookCollector()
        config = collector.get_tier_config(Tier.PREMIUM)
        assert config is not None


# ---------------------------------------------------------------------------
# collect_by_terms() integration tests
# ---------------------------------------------------------------------------


class TestCollectByTerms:
    @pytest.mark.asyncio
    async def test_collect_by_terms_returns_non_empty_list(self) -> None:
        """collect_by_terms() returns non-empty list when Bright Data delivers records."""
        snapshot = _load_snapshot_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            _mock_brightdata_full_cycle(snapshot)
            async with httpx.AsyncClient() as client:
                collector = _make_collector_with_client(client, pool)
                records = await collector.collect_by_terms(
                    terms=["grøn omstilling"], tier=Tier.MEDIUM, max_results=10
                )

        assert isinstance(records, list)
        assert len(records) > 0
        assert records[0]["platform"] == "facebook"
        assert records[0]["arena"] == "social_media"

    @pytest.mark.asyncio
    async def test_collect_by_terms_empty_snapshot_returns_empty_list(self) -> None:
        """collect_by_terms() returns [] when snapshot download returns empty list."""
        pool = _make_mock_pool()

        with respx.mock:
            _mock_brightdata_full_cycle([])
            async with httpx.AsyncClient() as client:
                collector = _make_collector_with_client(client, pool)
                records = await collector.collect_by_terms(
                    terms=["nonexistent xyz"], tier=Tier.MEDIUM, max_results=10
                )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_429_on_trigger_raises_rate_limit_error(self) -> None:
        """collect_by_terms() raises ArenaRateLimitError when trigger returns 429."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(BRIGHTDATA_TRIGGER_URL).mock(
                return_value=httpx.Response(429, headers={"Retry-After": "60"})
            )
            async with httpx.AsyncClient() as client:
                collector = _make_collector_with_client(client, pool)
                with pytest.raises(ArenaRateLimitError):
                    await collector.collect_by_terms(
                        terms=["test"], tier=Tier.MEDIUM, max_results=5
                    )

    @pytest.mark.asyncio
    async def test_collect_by_terms_401_on_trigger_raises_auth_error(self) -> None:
        """collect_by_terms() raises ArenaAuthError when trigger returns 401."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(BRIGHTDATA_TRIGGER_URL).mock(
                return_value=httpx.Response(401)
            )
            async with httpx.AsyncClient() as client:
                collector = _make_collector_with_client(client, pool)
                with pytest.raises(ArenaAuthError):
                    await collector.collect_by_terms(
                        terms=["test"], tier=Tier.MEDIUM, max_results=5
                    )

    @pytest.mark.asyncio
    async def test_collect_by_terms_403_on_trigger_raises_auth_error(self) -> None:
        """collect_by_terms() raises ArenaAuthError when trigger returns 403."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(BRIGHTDATA_TRIGGER_URL).mock(
                return_value=httpx.Response(403)
            )
            async with httpx.AsyncClient() as client:
                collector = _make_collector_with_client(client, pool)
                with pytest.raises(ArenaAuthError):
                    await collector.collect_by_terms(
                        terms=["test"], tier=Tier.MEDIUM, max_results=5
                    )

    @pytest.mark.asyncio
    async def test_collect_by_terms_premium_tier_raises_not_implemented(self) -> None:
        """collect_by_terms() raises NotImplementedError for PREMIUM tier (MCL pending)."""
        pool = _make_mock_pool()
        collector = FacebookCollector(credential_pool=pool)
        with pytest.raises(NotImplementedError):
            await collector.collect_by_terms(
                terms=["test"], tier=Tier.PREMIUM, max_results=5
            )

    @pytest.mark.asyncio
    async def test_collect_by_terms_trigger_no_snapshot_id_raises_collection_error(
        self,
    ) -> None:
        """collect_by_terms() raises ArenaCollectionError when trigger returns no snapshot_id."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(BRIGHTDATA_TRIGGER_URL).mock(
                return_value=httpx.Response(200, json={"status": "queued"})  # no snapshot_id
            )
            async with httpx.AsyncClient() as client:
                collector = _make_collector_with_client(client, pool)
                with pytest.raises(ArenaCollectionError):
                    await collector.collect_by_terms(
                        terms=["test"], tier=Tier.MEDIUM, max_results=5
                    )

    @pytest.mark.asyncio
    async def test_collect_by_terms_preserves_danish_text(self) -> None:
        """Danish characters in Facebook posts survive the full collect -> normalize pipeline."""
        snapshot = _load_snapshot_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            _mock_brightdata_full_cycle(snapshot)
            async with httpx.AsyncClient() as client:
                collector = _make_collector_with_client(client, pool)
                records = await collector.collect_by_terms(
                    terms=["grøn"], tier=Tier.MEDIUM, max_results=10
                )

        texts = [r.get("text_content", "") or "" for r in records]
        assert any("ø" in t or "å" in t or "æ" in t for t in texts)

    @pytest.mark.asyncio
    async def test_collect_by_terms_snapshot_failed_status_raises_collection_error(
        self,
    ) -> None:
        """collect_by_terms() raises ArenaCollectionError when snapshot status is 'failed'."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(BRIGHTDATA_TRIGGER_URL).mock(
                return_value=httpx.Response(200, json={"snapshot_id": _SNAPSHOT_ID})
            )
            respx.get(_PROGRESS_URL).mock(
                return_value=httpx.Response(200, json={"status": "failed"})
            )
            async with httpx.AsyncClient() as client:
                collector = _make_collector_with_client(client, pool)
                with pytest.raises(ArenaCollectionError):
                    await collector.collect_by_terms(
                        terms=["test"], tier=Tier.MEDIUM, max_results=5
                    )


# ---------------------------------------------------------------------------
# collect_by_actors() integration tests
# ---------------------------------------------------------------------------


class TestCollectByActors:
    @pytest.mark.asyncio
    async def test_collect_by_actors_page_url_returns_records(self) -> None:
        """collect_by_actors() with a Facebook page URL returns normalized records."""
        snapshot = _load_snapshot_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            _mock_brightdata_full_cycle(snapshot)
            async with httpx.AsyncClient() as client:
                collector = _make_collector_with_client(client, pool)
                records = await collector.collect_by_actors(
                    actor_ids=["https://www.facebook.com/drnyheder"],
                    tier=Tier.MEDIUM,
                    max_results=10,
                )

        assert isinstance(records, list)
        assert len(records) > 0
        assert all(r["platform"] == "facebook" for r in records)

    @pytest.mark.asyncio
    async def test_collect_by_actors_numeric_id_returns_records(self) -> None:
        """collect_by_actors() with a numeric page_id returns normalized records."""
        snapshot = _load_snapshot_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            _mock_brightdata_full_cycle(snapshot)
            async with httpx.AsyncClient() as client:
                collector = _make_collector_with_client(client, pool)
                records = await collector.collect_by_actors(
                    actor_ids=["123456789"],
                    tier=Tier.MEDIUM,
                    max_results=10,
                )

        assert isinstance(records, list)
        assert len(records) > 0

    @pytest.mark.asyncio
    async def test_collect_by_actors_premium_tier_raises_not_implemented(self) -> None:
        """collect_by_actors() raises NotImplementedError for PREMIUM tier."""
        pool = _make_mock_pool()
        collector = FacebookCollector(credential_pool=pool)
        with pytest.raises(NotImplementedError):
            await collector.collect_by_actors(
                actor_ids=["https://www.facebook.com/drnyheder"],
                tier=Tier.PREMIUM,
                max_results=5,
            )

    @pytest.mark.asyncio
    async def test_collect_by_actors_429_raises_rate_limit_error(self) -> None:
        """collect_by_actors() raises ArenaRateLimitError on 429 from trigger."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(BRIGHTDATA_TRIGGER_URL).mock(
                return_value=httpx.Response(429, headers={"Retry-After": "30"})
            )
            async with httpx.AsyncClient() as client:
                collector = _make_collector_with_client(client, pool)
                with pytest.raises(ArenaRateLimitError):
                    await collector.collect_by_actors(
                        actor_ids=["https://www.facebook.com/drnyheder"],
                        tier=Tier.MEDIUM,
                        max_results=5,
                    )


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_ok_on_200(self) -> None:
        """health_check() returns status='ok' when Bright Data API returns 200."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get("https://api.brightdata.com/datasets/v3").mock(
                return_value=httpx.Response(200, json={"status": "operational"})
            )
            collector = FacebookCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "social_media"
        assert result["platform"] == "facebook"
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_on_429(self) -> None:
        """health_check() returns status='degraded' when Bright Data returns 429."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get("https://api.brightdata.com/datasets/v3").mock(
                return_value=httpx.Response(429)
            )
            collector = FacebookCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "degraded"
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_401(self) -> None:
        """health_check() returns status='down' when Bright Data returns 401."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get("https://api.brightdata.com/datasets/v3").mock(
                return_value=httpx.Response(401)
            )
            collector = FacebookCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "down"
        assert "401" in result.get("detail", "")

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_403(self) -> None:
        """health_check() returns status='down' when Bright Data returns 403."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get("https://api.brightdata.com/datasets/v3").mock(
                return_value=httpx.Response(403)
            )
            collector = FacebookCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "down"
        assert "403" in result.get("detail", "")

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_no_credentials(self) -> None:
        """health_check() returns status='down' when no credential pool is configured."""
        collector = FacebookCollector()  # no pool
        result = await collector.health_check()

        assert result["status"] == "down"
        assert "checked_at" in result
        assert "credential" in result.get("detail", "").lower()
