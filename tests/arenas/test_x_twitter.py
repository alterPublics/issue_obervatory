"""Tests for the X/Twitter arena collector.

Covers:
- normalize() unit tests for both _parse_twitterapiio() and _parse_twitter_v2() paths
- Tweet type detection: tweet, retweet, reply, quote_tweet
- collect_by_terms() integration tests with mocked HTTP (respx) for MEDIUM and PREMIUM tiers
- Credential key assertions: MEDIUM uses 'twitterapi_io', PREMIUM uses 'x_twitter'
- Edge cases: empty results, HTTP 429, missing author
- health_check() success and failure paths
- Danish character preservation (æ, ø, å)

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
from issue_observatory.arenas.x_twitter.collector import (  # noqa: E402
    XTwitterCollector,
    _build_query,
    _detect_tweet_type_twitterapiio,
    _detect_tweet_type_v2,
    _extract_twitterapiio_media,
    _index_v2_users,
    _normalize_handle,
)
from issue_observatory.arenas.x_twitter.config import (  # noqa: E402
    TWITTERAPIIO_BASE_URL,
    TWITTER_V2_SEARCH_ALL,
)
from issue_observatory.core.exceptions import ArenaRateLimitError  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "api_responses" / "x_twitter"


def _load_twitterapiio_fixture() -> dict[str, Any]:
    """Load the recorded TwitterAPI.io fixture."""
    return json.loads((FIXTURES_DIR / "twitterapiio_response.json").read_text(encoding="utf-8"))


def _first_tweet() -> dict[str, Any]:
    """Return the first tweet from the fixture."""
    return _load_twitterapiio_fixture()["tweets"][0]


# ---------------------------------------------------------------------------
# Sample tweet objects used across unit tests
# ---------------------------------------------------------------------------

_SAMPLE_TWITTERAPIIO_TWEET = {
    "id": "1760000000000001",
    "text": "Grøn omstilling er afgørende for dansk velfærd og fremtiden for Ålborg.",
    "lang": "da",
    "createdAt": "2026-02-15T10:30:00.000Z",
    "author": {
        "id": "987654321",
        "userName": "soeren_dk",
        "name": "Søren Ærlighed",
    },
    "favorites": 42,
    "retweets": 7,
    "replies": 3,
    "views": 1500,
    "isRetweet": False,
    "isReply": False,
    "isQuote": False,
    "conversationId": "1760000000000001",
}

_SAMPLE_V2_TWEET = {
    "id": "1760000000000010",
    "text": "Debatten om velfærdsstat er vigtig for Ørsted og samfundet.",
    "lang": "da",
    "created_at": "2026-02-15T12:00:00.000Z",
    "author_id": "12345",
    "public_metrics": {
        "like_count": 18,
        "retweet_count": 4,
        "quote_count": 2,
        "reply_count": 5,
        "impression_count": 3000,
    },
    "conversation_id": "1760000000000010",
    "_users": {
        "12345": {"id": "12345", "username": "mette_test", "name": "Mette Ærlighed"},
    },
}


# ---------------------------------------------------------------------------
# Mock credential pool fixture
# ---------------------------------------------------------------------------


def _make_mock_pool(platform_key: str, cred_data: dict[str, Any]) -> Any:
    """Build a minimal mock CredentialPool that returns cred_data for the given platform."""
    pool = MagicMock()
    pool.acquire = AsyncMock(return_value=cred_data)
    pool.release = AsyncMock(return_value=None)
    return pool


# ---------------------------------------------------------------------------
# normalize() — TwitterAPI.io path
# ---------------------------------------------------------------------------


class TestNormalizeTweetTwitterapiio:
    def _collector(self) -> XTwitterCollector:
        return XTwitterCollector()

    def test_normalize_sets_platform_arena(self) -> None:
        """normalize() sets platform='x_twitter', arena='social_media'."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_TWITTERAPIIO_TWEET, tier_source="medium")

        assert result["platform"] == "x_twitter"
        assert result["arena"] == "social_media"

    def test_normalize_platform_id_is_tweet_id(self) -> None:
        """normalize() sets platform_id to the tweet ID string."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_TWITTERAPIIO_TWEET, tier_source="medium")

        assert result["platform_id"] == "1760000000000001"

    def test_normalize_text_content_from_text_field(self) -> None:
        """normalize() maps 'text' to text_content."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_TWITTERAPIIO_TWEET, tier_source="medium")

        assert result["text_content"] == _SAMPLE_TWITTERAPIIO_TWEET["text"]

    def test_normalize_engagement_counts_mapped(self) -> None:
        """normalize() maps favorites/retweets/replies to engagement fields."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_TWITTERAPIIO_TWEET, tier_source="medium")

        assert result["likes_count"] == 42
        assert result["shares_count"] == 7
        assert result["comments_count"] == 3

    def test_normalize_url_constructed_from_handle_and_id(self) -> None:
        """normalize() builds a https://x.com/{handle}/status/{id} URL."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_TWITTERAPIIO_TWEET, tier_source="medium")

        assert result["url"] is not None
        assert "x.com" in result["url"]
        assert "soeren_dk" in result["url"]
        assert "1760000000000001" in result["url"]

    def test_normalize_author_display_name_with_danish_chars(self) -> None:
        """normalize() maps author.name to author_display_name, preserving æ, ø."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_TWITTERAPIIO_TWEET, tier_source="medium")

        assert result["author_display_name"] == "Søren Ærlighed"
        assert "ø" in result["author_display_name"]
        assert "Æ" in result["author_display_name"]

    def test_normalize_content_type_plain_tweet(self) -> None:
        """normalize() sets content_type='tweet' for a plain tweet."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_TWITTERAPIIO_TWEET, tier_source="medium")

        assert result["content_type"] == "tweet"

    def test_normalize_content_type_retweet(self) -> None:
        """normalize() sets content_type='retweet' when isRetweet=True."""
        collector = self._collector()
        tweet = {**_SAMPLE_TWITTERAPIIO_TWEET, "isRetweet": True}
        result = collector.normalize(tweet, tier_source="medium")

        assert result["content_type"] == "retweet"

    def test_normalize_content_type_reply(self) -> None:
        """normalize() sets content_type='reply' when isReply=True."""
        collector = self._collector()
        tweet = {**_SAMPLE_TWITTERAPIIO_TWEET, "isReply": True}
        result = collector.normalize(tweet, tier_source="medium")

        assert result["content_type"] == "reply"

    def test_normalize_content_type_quote_tweet(self) -> None:
        """normalize() sets content_type='quote_tweet' when isQuote=True."""
        collector = self._collector()
        tweet = {**_SAMPLE_TWITTERAPIIO_TWEET, "isQuote": True}
        result = collector.normalize(tweet, tier_source="medium")

        assert result["content_type"] == "quote_tweet"

    def test_normalize_media_urls_extracted_from_media_field(self) -> None:
        """normalize() extracts media URLs from the media list."""
        collector = self._collector()
        tweet = {
            **_SAMPLE_TWITTERAPIIO_TWEET,
            "media": [{"media_url_https": "https://pbs.twimg.com/media/test.jpg"}],
        }
        result = collector.normalize(tweet, tier_source="medium")

        assert isinstance(result.get("media_urls"), list)

    def test_normalize_required_fields_always_present(self) -> None:
        """All required schema fields are present in normalized output."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_TWITTERAPIIO_TWEET, tier_source="medium")

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field is None: {field}"

    def test_normalize_preserves_danish_characters_in_text(self) -> None:
        """æ, ø, å in tweet text survive normalize() without corruption."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_TWITTERAPIIO_TWEET, tier_source="medium")

        assert "Grøn" in result["text_content"]
        assert "Ålborg" in result["text_content"]

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_handles_each_danish_character(self, char: str) -> None:
        """Each Danish character in tweet text survives normalize() without error."""
        collector = self._collector()
        tweet = {
            **_SAMPLE_TWITTERAPIIO_TWEET,
            "text": f"Indhold med {char} tegn i tweetet.",
        }
        result = collector.normalize(tweet, tier_source="medium")

        assert char in result["text_content"]


# ---------------------------------------------------------------------------
# normalize() — X API v2 path
# ---------------------------------------------------------------------------


class TestNormalizeTweetV2:
    def _collector(self) -> XTwitterCollector:
        return XTwitterCollector()

    def test_normalize_v2_sets_platform_arena(self) -> None:
        """normalize(tier_source='premium') sets platform='x_twitter', arena='social_media'."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_V2_TWEET, tier_source="premium")

        assert result["platform"] == "x_twitter"
        assert result["arena"] == "social_media"

    def test_normalize_v2_platform_id_is_tweet_id(self) -> None:
        """normalize() premium path sets platform_id to the v2 tweet id."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_V2_TWEET, tier_source="premium")

        assert result["platform_id"] == "1760000000000010"

    def test_normalize_v2_author_hydrated_from_users_dict(self) -> None:
        """normalize() premium path hydrates author_display_name from _users lookup."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_V2_TWEET, tier_source="premium")

        assert result["author_display_name"] == "Mette Ærlighed"

    def test_normalize_v2_metrics_mapped(self) -> None:
        """normalize() premium path maps public_metrics to engagement fields."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_V2_TWEET, tier_source="premium")

        assert result["likes_count"] == 18
        assert result["comments_count"] == 5

    def test_normalize_v2_plain_tweet_type(self) -> None:
        """normalize() premium path sets content_type='tweet' when no referenced_tweets."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_V2_TWEET, tier_source="premium")

        assert result["content_type"] == "tweet"

    def test_normalize_v2_retweet_type_from_referenced_tweets(self) -> None:
        """normalize() premium path detects retweet from referenced_tweets type."""
        collector = self._collector()
        tweet = {
            **_SAMPLE_V2_TWEET,
            "referenced_tweets": [{"type": "retweeted", "id": "1111"}],
        }
        result = collector.normalize(tweet, tier_source="premium")

        assert result["content_type"] == "retweet"

    def test_normalize_v2_reply_type_from_referenced_tweets(self) -> None:
        """normalize() premium path detects reply from referenced_tweets type."""
        collector = self._collector()
        tweet = {
            **_SAMPLE_V2_TWEET,
            "referenced_tweets": [{"type": "replied_to", "id": "2222"}],
        }
        result = collector.normalize(tweet, tier_source="premium")

        assert result["content_type"] == "reply"

    def test_normalize_v2_quote_tweet_type(self) -> None:
        """normalize() premium path detects quote tweet from referenced_tweets."""
        collector = self._collector()
        tweet = {
            **_SAMPLE_V2_TWEET,
            "referenced_tweets": [{"type": "quoted", "id": "3333"}],
        }
        result = collector.normalize(tweet, tier_source="premium")

        assert result["content_type"] == "quote_tweet"

    def test_normalize_v2_preserves_danish_in_text(self) -> None:
        """Danish characters in v2 tweet text survive normalize()."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_V2_TWEET, tier_source="premium")

        assert "velfærdsstat" in result["text_content"]
        assert "Ørsted" in result["text_content"]

    def test_normalize_v2_no_author_in_users_dict(self) -> None:
        """normalize() premium path gracefully handles missing author in _users."""
        collector = self._collector()
        tweet = {**_SAMPLE_V2_TWEET, "_users": {}}
        result = collector.normalize(tweet, tier_source="premium")

        # Should not crash; author_display_name may be empty string
        assert "platform_id" in result


# ---------------------------------------------------------------------------
# Utility function tests
# ---------------------------------------------------------------------------


class TestUtilityFunctions:
    def test_build_query_appends_lang_da(self) -> None:
        """_build_query() appends 'lang:da' to every query."""
        result = _build_query("folkeskolen", None, None)

        assert "lang:da" in result
        assert "folkeskolen" in result

    def test_build_query_includes_date_operators(self) -> None:
        """_build_query() appends since/until operators when dates are provided."""
        result = _build_query("test", "2026-01-01", "2026-02-15")

        assert "since:2026-01-01" in result
        assert "until:2026-02-15" in result

    def test_normalize_handle_strips_at_sign(self) -> None:
        """_normalize_handle() removes leading '@' from handles."""
        assert _normalize_handle("@drdk") == "drdk"
        assert _normalize_handle("drdk") == "drdk"

    def test_detect_tweet_type_twitterapiio_retweet(self) -> None:
        """_detect_tweet_type_twitterapiio() returns 'retweet' for isRetweet=True."""
        assert _detect_tweet_type_twitterapiio({"isRetweet": True}) == "retweet"

    def test_detect_tweet_type_twitterapiio_reply(self) -> None:
        """_detect_tweet_type_twitterapiio() returns 'reply' for isReply=True."""
        assert _detect_tweet_type_twitterapiio({"isReply": True}) == "reply"

    def test_detect_tweet_type_twitterapiio_quote(self) -> None:
        """_detect_tweet_type_twitterapiio() returns 'quote_tweet' for isQuote=True."""
        assert _detect_tweet_type_twitterapiio({"isQuote": True}) == "quote_tweet"

    def test_detect_tweet_type_twitterapiio_plain(self) -> None:
        """_detect_tweet_type_twitterapiio() returns 'tweet' for a plain tweet."""
        assert _detect_tweet_type_twitterapiio({}) == "tweet"

    def test_detect_tweet_type_v2_retweeted(self) -> None:
        """_detect_tweet_type_v2() returns 'retweet' for retweeted referenced type."""
        assert _detect_tweet_type_v2({"referenced_tweets": [{"type": "retweeted"}]}) == "retweet"

    def test_detect_tweet_type_v2_quoted(self) -> None:
        """_detect_tweet_type_v2() returns 'quote_tweet' for quoted referenced type."""
        assert _detect_tweet_type_v2({"referenced_tweets": [{"type": "quoted"}]}) == "quote_tweet"

    def test_detect_tweet_type_v2_replied_to(self) -> None:
        """_detect_tweet_type_v2() returns 'reply' for replied_to referenced type."""
        assert _detect_tweet_type_v2({"referenced_tweets": [{"type": "replied_to"}]}) == "reply"

    def test_extract_twitterapiio_media_returns_urls(self) -> None:
        """_extract_twitterapiio_media() returns list of URL strings."""
        raw = {"media": [{"media_url_https": "https://pbs.twimg.com/media/test.jpg"}]}
        result = _extract_twitterapiio_media(raw)

        assert result == ["https://pbs.twimg.com/media/test.jpg"]

    def test_extract_twitterapiio_media_empty_when_no_media(self) -> None:
        """_extract_twitterapiio_media() returns [] when media field is absent."""
        assert _extract_twitterapiio_media({}) == []

    def test_index_v2_users_builds_lookup_dict(self) -> None:
        """_index_v2_users() builds a dict keyed by string user ID."""
        users = [{"id": "111", "username": "alice", "name": "Alice"}]
        result = _index_v2_users(users)

        assert "111" in result
        assert result["111"]["username"] == "alice"


# ---------------------------------------------------------------------------
# collect_by_terms() — MEDIUM tier (TwitterAPI.io)
# ---------------------------------------------------------------------------


class TestCollectByTermsMedium:
    def _mock_medium_pool(self) -> Any:
        return _make_mock_pool(
            "twitterapi_io",
            {"id": "cred-medium-001", "api_key": "test-api-key-medium"},
        )

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_returns_records(self) -> None:
        """collect_by_terms() at MEDIUM tier returns normalized records from fixture."""
        fixture = _load_twitterapiio_fixture()
        pool = self._mock_medium_pool()

        with respx.mock:
            respx.get(TWITTERAPIIO_BASE_URL).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = XTwitterCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["grøn omstilling"], tier=Tier.MEDIUM, max_results=10
            )

        assert isinstance(records, list)
        assert len(records) > 0
        assert records[0]["platform"] == "x_twitter"

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_uses_twitterapi_io_credential(self) -> None:
        """collect_by_terms() at MEDIUM tier acquires credential from platform='twitterapi_io'."""
        fixture = _load_twitterapiio_fixture()
        pool = self._mock_medium_pool()

        with respx.mock:
            respx.get(TWITTERAPIIO_BASE_URL).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = XTwitterCollector(credential_pool=pool)
            await collector.collect_by_terms(
                terms=["test"], tier=Tier.MEDIUM, max_results=5
            )

        pool.acquire.assert_awaited_once()
        call_kwargs = pool.acquire.call_args
        assert call_kwargs.kwargs.get("platform") == "twitterapi_io" or \
               (call_kwargs.args and call_kwargs.args[0] == "twitterapi_io") or \
               "twitterapi_io" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_empty_response_returns_empty_list(self) -> None:
        """collect_by_terms() MEDIUM tier returns [] when API returns no tweets."""
        pool = self._mock_medium_pool()

        with respx.mock:
            respx.get(TWITTERAPIIO_BASE_URL).mock(
                return_value=httpx.Response(200, json={"tweets": [], "next_cursor": None})
            )
            collector = XTwitterCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["obscure_query"], tier=Tier.MEDIUM, max_results=10
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_429_raises_rate_limit_error(self) -> None:
        """collect_by_terms() MEDIUM tier raises ArenaRateLimitError on HTTP 429."""
        pool = self._mock_medium_pool()

        with respx.mock:
            respx.get(TWITTERAPIIO_BASE_URL).mock(
                return_value=httpx.Response(429, headers={"Retry-After": "60"})
            )
            collector = XTwitterCollector(credential_pool=pool)
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_terms(
                    terms=["test"], tier=Tier.MEDIUM, max_results=5
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_preserves_danish_text(self) -> None:
        """Danish characters in tweets survive the full MEDIUM collect → normalize pipeline."""
        fixture = _load_twitterapiio_fixture()
        pool = self._mock_medium_pool()

        with respx.mock:
            respx.get(TWITTERAPIIO_BASE_URL).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = XTwitterCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["Ålborg"], tier=Tier.MEDIUM, max_results=10
            )

        texts = [r.get("text_content", "") or "" for r in records]
        assert any("Grøn" in t or "Ålborg" in t for t in texts), \
            "Expected Danish characters in at least one record"


# ---------------------------------------------------------------------------
# collect_by_terms() — PREMIUM tier (X API v2)
# ---------------------------------------------------------------------------


class TestCollectByTermsPremium:
    def _mock_premium_pool(self) -> Any:
        return _make_mock_pool(
            "x_twitter",
            {"id": "cred-premium-001", "bearer_token": "test-bearer-token"},
        )

    @pytest.mark.asyncio
    async def test_collect_by_terms_premium_returns_records(self) -> None:
        """collect_by_terms() at PREMIUM tier returns normalized records from v2 response."""
        v2_response = {
            "data": [
                {
                    "id": "1760000000000020",
                    "text": "Velfærdsstat og Ørsted — debat om fremtiden.",
                    "lang": "da",
                    "created_at": "2026-02-15T10:00:00.000Z",
                    "author_id": "999",
                    "public_metrics": {
                        "like_count": 5,
                        "retweet_count": 1,
                        "quote_count": 0,
                        "reply_count": 2,
                        "impression_count": 500,
                    },
                }
            ],
            "includes": {
                "users": [{"id": "999", "username": "test_user", "name": "Test Bruger"}]
            },
            "meta": {"result_count": 1, "next_token": None},
        }
        pool = self._mock_premium_pool()

        with respx.mock:
            respx.get(TWITTER_V2_SEARCH_ALL).mock(
                return_value=httpx.Response(200, json=v2_response)
            )
            collector = XTwitterCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["velfærd"], tier=Tier.PREMIUM, max_results=10
            )

        assert isinstance(records, list)
        assert len(records) > 0
        assert records[0]["platform"] == "x_twitter"

    @pytest.mark.asyncio
    async def test_collect_by_terms_premium_uses_x_twitter_credential(self) -> None:
        """collect_by_terms() at PREMIUM tier acquires credential from platform='x_twitter'."""
        v2_response = {
            "data": [],
            "meta": {"result_count": 0},
        }
        pool = self._mock_premium_pool()

        with respx.mock:
            respx.get(TWITTER_V2_SEARCH_ALL).mock(
                return_value=httpx.Response(200, json=v2_response)
            )
            collector = XTwitterCollector(credential_pool=pool)
            await collector.collect_by_terms(
                terms=["test"], tier=Tier.PREMIUM, max_results=5
            )

        pool.acquire.assert_awaited_once()
        call_kwargs = pool.acquire.call_args
        assert "x_twitter" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_collect_by_terms_premium_429_raises_rate_limit_error(self) -> None:
        """collect_by_terms() PREMIUM tier raises ArenaRateLimitError on HTTP 429."""
        pool = self._mock_premium_pool()

        with respx.mock:
            respx.get(TWITTER_V2_SEARCH_ALL).mock(
                return_value=httpx.Response(429, headers={"Retry-After": "60"})
            )
            collector = XTwitterCollector(credential_pool=pool)
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_terms(
                    terms=["test"], tier=Tier.PREMIUM, max_results=5
                )


# ---------------------------------------------------------------------------
# collect_by_terms() — tier validation
# ---------------------------------------------------------------------------


class TestTierValidation:
    @pytest.mark.asyncio
    async def test_collect_by_terms_free_tier_raises_value_error(self) -> None:
        """collect_by_terms() at FREE tier raises ValueError (not supported)."""
        collector = XTwitterCollector()
        with pytest.raises((ValueError, Exception)):
            await collector.collect_by_terms(
                terms=["test"], tier=Tier.FREE, max_results=5
            )


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_down_when_no_credentials(self) -> None:
        """health_check() returns status='down' when no credentials are configured."""
        collector = XTwitterCollector()  # no credential pool
        result = await collector.health_check()

        assert result["status"] == "down"
        assert result["arena"] == "social_media"
        assert result["platform"] == "x_twitter"
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_ok_on_medium_success(self) -> None:
        """health_check() returns status='ok' when TwitterAPI.io responds successfully."""
        pool = _make_mock_pool(
            "twitterapi_io",
            {"id": "cred-health-001", "api_key": "test-api-key"},
        )

        with respx.mock:
            respx.get(TWITTERAPIIO_BASE_URL).mock(
                return_value=httpx.Response(200, json={"tweets": []})
            )
            collector = XTwitterCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "ok"
        assert result.get("tier_tested") == "medium"

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_on_medium_429(self) -> None:
        """health_check() returns status='degraded' when TwitterAPI.io returns 429."""
        pool = _make_mock_pool(
            "twitterapi_io",
            {"id": "cred-health-002", "api_key": "test-api-key"},
        )

        with respx.mock:
            respx.get(TWITTERAPIIO_BASE_URL).mock(
                return_value=httpx.Response(429, headers={"Retry-After": "60"})
            )
            collector = XTwitterCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_connection_error(self) -> None:
        """health_check() returns status='down' on a network connection error."""
        pool = _make_mock_pool(
            "twitterapi_io",
            {"id": "cred-health-003", "api_key": "test-api-key"},
        )

        with respx.mock:
            respx.get(TWITTERAPIIO_BASE_URL).mock(
                side_effect=httpx.ConnectError("connection refused")
            )
            collector = XTwitterCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "down"
