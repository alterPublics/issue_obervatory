"""Tests for the Instagram arena collector -- Web Scraper API migration.

Covers:
- collect_by_terms() now raises ArenaCollectionError (actor-only arena)
- normalize() unit tests: Web Scraper API field mapping (description, user_posted,
  date_posted, likes, num_comments, video_view_count, video_play_count, hashtags)
- normalize() fallback chains: legacy Dataset field names (caption, username,
  timestamp, likes_count, comments_count) handled correctly
- normalize() MCL path: content_type detection for Reel/post, view_count
- _normalize_profile_url(): username, @-prefixed, and URL input normalization
- collect_by_actors(): full Bright Data Web Scraper API async cycle
  (trigger -> poll -> download) with respx mocks and URL-based payloads
- Dataset routing: all profile URLs -> Reels scraper (gd_lyclm20il4r5helnj)
- Date format conversion: to_brightdata_date() outputs MM-DD-YYYY
- HTTP 429 -> ArenaRateLimitError, HTTP 401/403 -> ArenaAuthError
- PREMIUM tier raises NotImplementedError
- FREE tier raises ValueError (unsupported)
- health_check() ok / degraded / down paths
- Danish character preservation: ae, o, a throughout

These tests run without a live database or network connection.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
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
from issue_observatory.arenas.instagram.collector import (  # noqa: E402
    InstagramCollector,
    _normalize_profile_url,
)
from issue_observatory.arenas.instagram.config import (  # noqa: E402
    BRIGHTDATA_PROGRESS_URL,
    BRIGHTDATA_SNAPSHOT_URL,
    INSTAGRAM_DATASET_ID_REELS,
    build_trigger_url,
    to_brightdata_date,
)
from issue_observatory.core.exceptions import (  # noqa: E402
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "api_responses" / "instagram"

_SNAPSHOT_ID = "snap_ig_test_001"
_PROGRESS_URL = BRIGHTDATA_PROGRESS_URL.format(snapshot_id=_SNAPSHOT_ID)
_SNAPSHOT_URL = BRIGHTDATA_SNAPSHOT_URL.format(snapshot_id=_SNAPSHOT_ID)

# Default trigger URL for the Reels scraper (profile URL input).
_TRIGGER_URL_REELS = build_trigger_url(INSTAGRAM_DATASET_ID_REELS)


def _load_web_scraper_fixture() -> list[dict[str, Any]]:
    """Load the Web Scraper API Instagram snapshot fixture (new format)."""
    return json.loads(
        (FIXTURES_DIR / "web_scraper_snapshot_response.json").read_text(encoding="utf-8")
    )


def _load_legacy_fixture() -> list[dict[str, Any]]:
    """Load the legacy Bright Data Dataset Instagram snapshot fixture (old format)."""
    return json.loads(
        (FIXTURES_DIR / "brightdata_snapshot_response.json").read_text(encoding="utf-8")
    )


def _first_post() -> dict[str, Any]:
    """Return the first post from the Web Scraper API fixture (regular image post)."""
    return _load_web_scraper_fixture()[0]


def _reel_post() -> dict[str, Any]:
    """Return the third post which is a Reel (product_type='clips', media_type='2')."""
    return _load_web_scraper_fixture()[2]


def _carousel_post() -> dict[str, Any]:
    """Return the second post which has carousel media."""
    return _load_web_scraper_fixture()[1]


# ---------------------------------------------------------------------------
# Mock credential pool
# ---------------------------------------------------------------------------


def _make_mock_pool() -> Any:
    """Build a minimal mock CredentialPool returning a Bright Data Instagram credential."""
    pool = MagicMock()
    pool.acquire = AsyncMock(
        return_value={
            "id": "cred-ig-001",
            "api_token": "test-bd-instagram-api-token",
        }
    )
    pool.release = AsyncMock(return_value=None)
    pool.report_error = AsyncMock(return_value=None)
    return pool


# ---------------------------------------------------------------------------
# Helpers: mock the three Bright Data endpoints
# ---------------------------------------------------------------------------


def _mock_brightdata_full_cycle(snapshot_data: list[dict[str, Any]]) -> None:
    """Register respx routes for trigger -> poll-ready -> download cycle."""
    respx.post(_TRIGGER_URL_REELS).mock(
        return_value=httpx.Response(200, json={"snapshot_id": _SNAPSHOT_ID})
    )
    respx.get(_PROGRESS_URL).mock(
        return_value=httpx.Response(200, json={"status": "ready"})
    )
    respx.get(_SNAPSHOT_URL).mock(
        return_value=httpx.Response(200, json=snapshot_data)
    )


# ---------------------------------------------------------------------------
# to_brightdata_date() unit tests
# ---------------------------------------------------------------------------


class TestToBrightdataDate:
    """Verify that to_brightdata_date() outputs the MM-DD-YYYY format."""

    def test_datetime_object_formatted_as_mm_dd_yyyy(self) -> None:
        """A datetime(2026, 1, 15) should produce '01-15-2026'."""
        dt = datetime(2026, 1, 15, tzinfo=timezone.utc)
        assert to_brightdata_date(dt) == "01-15-2026"

    def test_iso_string_converted_to_mm_dd_yyyy(self) -> None:
        """An ISO 8601 string '2026-02-26' should produce '02-26-2026'."""
        assert to_brightdata_date("2026-02-26") == "02-26-2026"

    def test_iso_string_with_time_converted_to_mm_dd_yyyy(self) -> None:
        """An ISO 8601 string with time '2026-12-01T10:00:00Z' -> '12-01-2026'."""
        assert to_brightdata_date("2026-12-01T10:00:00Z") == "12-01-2026"

    def test_none_returns_none(self) -> None:
        """None input should return None."""
        assert to_brightdata_date(None) is None

    def test_invalid_string_returns_none(self) -> None:
        """An unparseable string should return None."""
        assert to_brightdata_date("not-a-date") is None

    def test_short_string_returns_none(self) -> None:
        """A string shorter than 10 characters should return None."""
        assert to_brightdata_date("2026") is None


# ---------------------------------------------------------------------------
# _normalize_profile_url() tests
# ---------------------------------------------------------------------------


class TestNormalizeProfileUrl:
    """Verify that _normalize_profile_url() correctly normalizes inputs."""

    def test_full_url_returned_as_is(self) -> None:
        """A full URL starting with https:// is returned unchanged."""
        url = "https://www.instagram.com/drnyheder/"
        assert _normalize_profile_url(url) == url

    def test_plain_username_builds_url(self) -> None:
        """A plain username (no @, no URL) builds a full profile URL."""
        assert _normalize_profile_url("drnyheder") == "https://www.instagram.com/drnyheder/"

    def test_at_prefixed_username_builds_url(self) -> None:
        """A @-prefixed username strips @ and builds a full profile URL."""
        assert _normalize_profile_url("@drnyheder") == "https://www.instagram.com/drnyheder/"

    def test_http_url_returned_as_is(self) -> None:
        """An http:// URL is returned unchanged (starts with 'http')."""
        url = "http://www.instagram.com/drnyheder/"
        assert _normalize_profile_url(url) == url


class TestBuildTriggerUrl:
    """Verify that build_trigger_url() produces correct trigger URLs."""

    def test_reels_trigger_url_contains_reels_dataset_id(self) -> None:
        """Trigger URL for Reels should contain the Reels dataset ID."""
        url = build_trigger_url(INSTAGRAM_DATASET_ID_REELS)
        assert INSTAGRAM_DATASET_ID_REELS in url
        assert "trigger?dataset_id=" in url

    def test_trigger_url_does_not_contain_discover_new(self) -> None:
        """Web Scraper API trigger URL must not contain type=discover_new."""
        url = build_trigger_url(INSTAGRAM_DATASET_ID_REELS)
        assert "discover_new" not in url
        assert "notify=none" not in url


# ---------------------------------------------------------------------------
# normalize() unit tests -- Web Scraper API path
# ---------------------------------------------------------------------------


class TestNormalizeBrightData:
    """Normalize Web Scraper API Instagram records to the universal schema."""

    def _collector(self) -> InstagramCollector:
        return InstagramCollector()

    def test_normalize_sets_platform_and_arena(self) -> None:
        """normalize() sets platform='instagram', arena='social_media'."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert result["platform"] == "instagram"
        assert result["arena"] == "social_media"

    def test_normalize_content_type_post_for_image_post(self) -> None:
        """normalize() sets content_type='post' for a regular image post."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert result["content_type"] == "post"

    def test_normalize_content_type_reel_for_clips_product_type(self) -> None:
        """normalize() sets content_type='reel' when product_type is 'clips'."""
        collector = self._collector()
        result = collector.normalize(_reel_post(), source="brightdata")

        assert result["content_type"] == "reel"

    def test_normalize_content_type_reel_for_media_type_2(self) -> None:
        """normalize() sets content_type='reel' when media_type is '2'."""
        collector = self._collector()
        post = {**_first_post(), "media_type": "2", "product_type": "feed"}
        result = collector.normalize(post, source="brightdata")

        assert result["content_type"] == "reel"

    def test_normalize_platform_id_from_shortcode(self) -> None:
        """normalize() sets platform_id to the shortcode field."""
        collector = self._collector()
        post = _first_post()
        result = collector.normalize(post, source="brightdata")

        assert result["platform_id"] == post["shortcode"]

    def test_normalize_platform_id_extracted_from_url_when_no_shortcode(self) -> None:
        """normalize() extracts shortcode from URL when shortcode field is absent."""
        collector = self._collector()
        post = {**_first_post()}
        del post["shortcode"]
        result = collector.normalize(post, source="brightdata")

        # Should extract CqXzABC123def from https://www.instagram.com/p/CqXzABC123def/
        assert result["platform_id"] == "CqXzABC123def"

    def test_normalize_url_from_url_field(self) -> None:
        """normalize() uses the url field directly from the Web Scraper API response."""
        collector = self._collector()
        post = _first_post()
        result = collector.normalize(post, source="brightdata")

        assert result["url"] == post["url"]

    def test_normalize_url_constructed_from_shortcode_when_url_absent(self) -> None:
        """normalize() builds URL from shortcode when url field is missing."""
        collector = self._collector()
        post = {**_first_post(), "url": None}
        result = collector.normalize(post, source="brightdata")

        assert result["url"] == f"https://www.instagram.com/p/{post['shortcode']}/"

    def test_normalize_text_content_from_description(self) -> None:
        """normalize() maps 'description' (Web Scraper API field) to text_content."""
        collector = self._collector()
        post = _first_post()
        result = collector.normalize(post, source="brightdata")

        assert result["text_content"] == post["description"]

    def test_normalize_author_display_name_from_user_posted(self) -> None:
        """normalize() maps 'user_posted' to author_display_name."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert result["author_display_name"] == "drnyheder"

    def test_normalize_pseudonymized_author_id_set_when_author_present(self) -> None:
        """normalize() computes pseudonymized_author_id when user_posted is present."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert result["pseudonymized_author_id"] is not None
        assert len(result["pseudonymized_author_id"]) == 64

    def test_normalize_likes_count_from_likes_field(self) -> None:
        """normalize() maps 'likes' (Web Scraper API field) to likes_count."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert result["likes_count"] == 1240

    def test_normalize_comments_count_from_num_comments(self) -> None:
        """normalize() maps 'num_comments' to comments_count."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert result["comments_count"] == 87

    def test_normalize_shares_count_is_none_for_instagram(self) -> None:
        """normalize() sets shares_count=None (Instagram does not expose shares)."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert result["shares_count"] is None

    def test_normalize_views_count_from_video_view_count_for_reels(self) -> None:
        """normalize() maps 'video_view_count' to views_count for Reel posts."""
        collector = self._collector()
        result = collector.normalize(_reel_post(), source="brightdata")

        assert result["views_count"] == 45000

    def test_normalize_views_count_falls_back_to_video_play_count(self) -> None:
        """normalize() falls back to video_play_count when video_view_count is absent."""
        collector = self._collector()
        post = {**_reel_post(), "video_view_count": None}
        result = collector.normalize(post, source="brightdata")

        assert result["views_count"] == 38000

    def test_normalize_media_urls_from_display_url(self) -> None:
        """normalize() extracts display_url into media_urls."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert isinstance(result["media_urls"], list)
        assert len(result["media_urls"]) >= 1
        assert "instagram.com" in result["media_urls"][0]

    def test_normalize_media_urls_includes_carousel_items(self) -> None:
        """normalize() extracts carousel_media items into media_urls."""
        collector = self._collector()
        result = collector.normalize(_carousel_post(), source="brightdata")

        assert isinstance(result["media_urls"], list)
        # Should include the primary display_url plus carousel items
        assert len(result["media_urls"]) >= 3

    def test_normalize_media_urls_video_url_for_reel(self) -> None:
        """normalize() includes video_url in media_urls for Reel posts."""
        collector = self._collector()
        result = collector.normalize(_reel_post(), source="brightdata")

        assert any("mp4" in url or "reel" in url for url in result["media_urls"])

    def test_normalize_published_at_from_date_posted(self) -> None:
        """normalize() maps 'date_posted' to published_at."""
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

    def test_normalize_preserves_danish_text_in_description(self) -> None:
        """ae, o, a in Instagram description survive normalize() without corruption."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert "Gr\u00f8n" in result["text_content"]
        assert "\u00c5lborg" in result["text_content"]

    @pytest.mark.parametrize("char", ["\u00e6", "\u00f8", "\u00e5", "\u00c6", "\u00d8", "\u00c5"])
    def test_normalize_handles_each_danish_character_in_description(self, char: str) -> None:
        """Each Danish character in Instagram description survives normalize()."""
        collector = self._collector()
        post = {**_first_post(), "description": f"Indhold med {char} tegn i opslaget."}
        result = collector.normalize(post, source="brightdata")

        assert char in result["text_content"]

    def test_normalize_null_likes_produce_none(self) -> None:
        """normalize() maps null likes to None."""
        collector = self._collector()
        post = _load_web_scraper_fixture()[3]  # fourth post has null likes
        result = collector.normalize(post, source="brightdata")

        assert result["likes_count"] is None

    def test_normalize_title_is_none_for_instagram(self) -> None:
        """normalize() sets title=None (Instagram posts have no title field)."""
        collector = self._collector()
        result = collector.normalize(_first_post(), source="brightdata")

        assert result.get("title") is None


# ---------------------------------------------------------------------------
# normalize() fallback chain tests -- legacy Dataset fields
# ---------------------------------------------------------------------------


class TestNormalizeLegacyFallback:
    """Verify that normalize() handles legacy Dataset field names correctly."""

    def _collector(self) -> InstagramCollector:
        return InstagramCollector()

    def test_normalize_falls_back_to_caption_when_description_absent(self) -> None:
        """normalize() maps 'caption' to text_content when 'description' is absent."""
        collector = self._collector()
        legacy_post = _load_legacy_fixture()[0]
        result = collector.normalize(legacy_post, source="brightdata")

        assert result["text_content"] == legacy_post["caption"]
        assert "Gr\u00f8n" in result["text_content"]

    def test_normalize_falls_back_to_username_when_user_posted_absent(self) -> None:
        """normalize() maps 'username' when 'user_posted' is not present."""
        collector = self._collector()
        legacy_post = _load_legacy_fixture()[0]
        result = collector.normalize(legacy_post, source="brightdata")

        assert result["author_display_name"] == "drnyheder"

    def test_normalize_falls_back_to_likes_count_when_likes_absent(self) -> None:
        """normalize() maps 'likes_count' to likes_count when 'likes' is not present."""
        collector = self._collector()
        legacy_post = _load_legacy_fixture()[0]
        result = collector.normalize(legacy_post, source="brightdata")

        assert result["likes_count"] == 1240

    def test_normalize_falls_back_to_timestamp_when_date_posted_absent(self) -> None:
        """normalize() maps 'timestamp' when 'date_posted' is not present."""
        collector = self._collector()
        legacy_post = _load_legacy_fixture()[0]
        result = collector.normalize(legacy_post, source="brightdata")

        assert result["published_at"] is not None
        assert "2026-02-15" in result["published_at"]

    def test_normalize_falls_back_to_comments_count_when_num_comments_absent(self) -> None:
        """normalize() maps 'comments_count' when 'num_comments' is not present."""
        collector = self._collector()
        legacy_post = _load_legacy_fixture()[0]
        result = collector.normalize(legacy_post, source="brightdata")

        assert result["comments_count"] == 87

    def test_normalize_shortcode_from_legacy_fixture(self) -> None:
        """normalize() uses 'shortcode' as platform_id from legacy fixture format."""
        collector = self._collector()
        legacy_post = _load_legacy_fixture()[0]
        result = collector.normalize(legacy_post, source="brightdata")

        assert result["platform_id"] == legacy_post["shortcode"]


# ---------------------------------------------------------------------------
# normalize() unit tests -- MCL path
# ---------------------------------------------------------------------------


class TestNormalizeMCL:
    def _collector(self) -> InstagramCollector:
        return InstagramCollector()

    def _mcl_post(self) -> dict[str, Any]:
        return {
            "id": "mcl_ig_001",
            "creator_id": "creator_001",
            "creator_name": "drnyheder",
            "caption_text": "Gr\u00f8n omstilling #klimadk",
            "creation_time": "2026-02-15T10:00:00+0000",
            "media_type": "IMAGE",
            "product_type": "feed",
            "likes_count": 1000,
            "shares_count": 50,
            "comments_count": 75,
            "view_count": None,
        }

    def _mcl_reel(self) -> dict[str, Any]:
        return {
            "id": "mcl_ig_002",
            "creator_id": "creator_002",
            "creator_name": "tv2nyheder",
            "caption_text": "Reel om dansk natur",
            "creation_time": "2026-02-15T09:00:00+0000",
            "media_type": "REEL",
            "product_type": "clips",
            "likes_count": 5000,
            "shares_count": 200,
            "comments_count": 150,
            "view_count": 80000,
        }

    def test_normalize_mcl_sets_platform_and_arena(self) -> None:
        """normalize(source='mcl') sets platform='instagram', arena='social_media'."""
        collector = self._collector()
        result = collector.normalize(self._mcl_post(), source="mcl")

        assert result["platform"] == "instagram"
        assert result["arena"] == "social_media"

    def test_normalize_mcl_content_type_post_for_image(self) -> None:
        """normalize(source='mcl') sets content_type='post' for image media_type."""
        collector = self._collector()
        result = collector.normalize(self._mcl_post(), source="mcl")

        assert result["content_type"] == "post"

    def test_normalize_mcl_content_type_reel_for_reel_media_type(self) -> None:
        """normalize(source='mcl') sets content_type='reel' when media_type='REEL'."""
        collector = self._collector()
        result = collector.normalize(self._mcl_reel(), source="mcl")

        assert result["content_type"] == "reel"

    def test_normalize_mcl_views_count_from_view_count(self) -> None:
        """normalize(source='mcl') maps 'view_count' to views_count."""
        collector = self._collector()
        result = collector.normalize(self._mcl_reel(), source="mcl")

        assert result["views_count"] == 80000

    def test_normalize_mcl_required_fields_present(self) -> None:
        """All required schema fields present for MCL-sourced Instagram records."""
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
        """InstagramCollector does not support Tier.FREE and raises ValueError."""
        collector = InstagramCollector()
        with pytest.raises(ValueError, match="free"):
            collector.get_tier_config(Tier.FREE)

    def test_medium_tier_config_returned(self) -> None:
        """get_tier_config(Tier.MEDIUM) returns a non-None TierConfig."""
        collector = InstagramCollector()
        config = collector.get_tier_config(Tier.MEDIUM)
        assert config is not None

    def test_premium_tier_config_returned(self) -> None:
        """get_tier_config(Tier.PREMIUM) returns a non-None TierConfig."""
        collector = InstagramCollector()
        config = collector.get_tier_config(Tier.PREMIUM)
        assert config is not None


# ---------------------------------------------------------------------------
# collect_by_terms() -- must raise ArenaCollectionError (actor-only arena)
# ---------------------------------------------------------------------------


class TestCollectByTerms:
    """collect_by_terms() must raise ArenaCollectionError for all tiers.

    Instagram is an actor-only arena. The Web Scraper API does not support
    keyword or hashtag-based discovery.
    """

    @pytest.mark.asyncio
    async def test_collect_by_terms_raises_arena_collection_error(self) -> None:
        """collect_by_terms() raises ArenaCollectionError regardless of tier."""
        collector = InstagramCollector()
        with pytest.raises(ArenaCollectionError):
            await collector.collect_by_terms(
                terms=["gronomstilling"], tier=Tier.MEDIUM, max_results=10
            )

    @pytest.mark.asyncio
    async def test_collect_by_terms_error_message_mentions_actor_directory(self) -> None:
        """The error message guides users to the Actor Directory."""
        collector = InstagramCollector()
        with pytest.raises(ArenaCollectionError, match="Actor Directory"):
            await collector.collect_by_terms(
                terms=["test"], tier=Tier.MEDIUM, max_results=5
            )

    @pytest.mark.asyncio
    async def test_collect_by_terms_error_message_mentions_keyword_not_supported(self) -> None:
        """The error message explains keyword search is not supported."""
        collector = InstagramCollector()
        with pytest.raises(ArenaCollectionError, match="does not support keyword"):
            await collector.collect_by_terms(
                terms=["klima"], tier=Tier.MEDIUM, max_results=5
            )

    @pytest.mark.asyncio
    async def test_collect_by_terms_raises_for_premium_tier_too(self) -> None:
        """collect_by_terms() raises ArenaCollectionError even for PREMIUM tier."""
        collector = InstagramCollector()
        with pytest.raises(ArenaCollectionError):
            await collector.collect_by_terms(
                terms=["test"], tier=Tier.PREMIUM, max_results=5
            )


# ---------------------------------------------------------------------------
# collect_by_actors() integration tests
# ---------------------------------------------------------------------------


class TestCollectByActors:
    @pytest.mark.asyncio
    async def test_collect_by_actors_profile_url_returns_records(self) -> None:
        """collect_by_actors() with a profile URL returns normalized records."""
        snapshot = _load_web_scraper_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            _mock_brightdata_full_cycle(snapshot)
            async with httpx.AsyncClient() as client:
                collector = InstagramCollector(credential_pool=pool, http_client=client)
                records = await collector.collect_by_actors(
                    actor_ids=["https://www.instagram.com/drnyheder"],
                    tier=Tier.MEDIUM,
                    max_results=10,
                )

        assert isinstance(records, list)
        assert len(records) > 0
        assert all(r["platform"] == "instagram" for r in records)

    @pytest.mark.asyncio
    async def test_collect_by_actors_username_returns_records(self) -> None:
        """collect_by_actors() with a plain username returns normalized records."""
        snapshot = _load_web_scraper_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            _mock_brightdata_full_cycle(snapshot)
            async with httpx.AsyncClient() as client:
                collector = InstagramCollector(credential_pool=pool, http_client=client)
                records = await collector.collect_by_actors(
                    actor_ids=["drnyheder"],
                    tier=Tier.MEDIUM,
                    max_results=10,
                )

        assert isinstance(records, list)
        assert len(records) > 0

    @pytest.mark.asyncio
    async def test_collect_by_actors_at_prefixed_username_returns_records(self) -> None:
        """collect_by_actors() with a @-prefixed username returns normalized records."""
        snapshot = _load_web_scraper_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            _mock_brightdata_full_cycle(snapshot)
            async with httpx.AsyncClient() as client:
                collector = InstagramCollector(credential_pool=pool, http_client=client)
                records = await collector.collect_by_actors(
                    actor_ids=["@drnyheder"],
                    tier=Tier.MEDIUM,
                    max_results=10,
                )

        assert isinstance(records, list)
        assert len(records) > 0

    @pytest.mark.asyncio
    async def test_collect_by_actors_premium_raises_not_implemented(self) -> None:
        """collect_by_actors() raises NotImplementedError for PREMIUM tier."""
        pool = _make_mock_pool()
        collector = InstagramCollector(credential_pool=pool)
        with pytest.raises(NotImplementedError):
            await collector.collect_by_actors(
                actor_ids=["drnyheder"], tier=Tier.PREMIUM, max_results=5
            )

    @pytest.mark.asyncio
    async def test_collect_by_actors_429_raises_rate_limit_error(self) -> None:
        """collect_by_actors() raises ArenaRateLimitError on 429 from trigger."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(_TRIGGER_URL_REELS).mock(
                return_value=httpx.Response(429, headers={"Retry-After": "60"})
            )
            async with httpx.AsyncClient() as client:
                collector = InstagramCollector(credential_pool=pool, http_client=client)
                with pytest.raises(ArenaRateLimitError):
                    await collector.collect_by_actors(
                        actor_ids=["drnyheder"], tier=Tier.MEDIUM, max_results=5
                    )

    @pytest.mark.asyncio
    async def test_collect_by_actors_401_raises_auth_error(self) -> None:
        """collect_by_actors() raises ArenaAuthError on 401 from trigger."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(_TRIGGER_URL_REELS).mock(
                return_value=httpx.Response(401)
            )
            async with httpx.AsyncClient() as client:
                collector = InstagramCollector(credential_pool=pool, http_client=client)
                with pytest.raises(ArenaAuthError):
                    await collector.collect_by_actors(
                        actor_ids=["drnyheder"], tier=Tier.MEDIUM, max_results=5
                    )

    @pytest.mark.asyncio
    async def test_collect_by_actors_403_raises_auth_error(self) -> None:
        """collect_by_actors() raises ArenaAuthError on 403 from trigger."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(_TRIGGER_URL_REELS).mock(
                return_value=httpx.Response(403)
            )
            async with httpx.AsyncClient() as client:
                collector = InstagramCollector(credential_pool=pool, http_client=client)
                with pytest.raises(ArenaAuthError):
                    await collector.collect_by_actors(
                        actor_ids=["drnyheder"], tier=Tier.MEDIUM, max_results=5
                    )

    @pytest.mark.asyncio
    async def test_collect_by_actors_no_snapshot_id_raises_collection_error(self) -> None:
        """collect_by_actors() raises ArenaCollectionError when trigger has no snapshot_id."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(_TRIGGER_URL_REELS).mock(
                return_value=httpx.Response(200, json={"queued": True})
            )
            async with httpx.AsyncClient() as client:
                collector = InstagramCollector(credential_pool=pool, http_client=client)
                with pytest.raises(ArenaCollectionError):
                    await collector.collect_by_actors(
                        actor_ids=["drnyheder"], tier=Tier.MEDIUM, max_results=5
                    )

    @pytest.mark.asyncio
    async def test_collect_by_actors_snapshot_failed_raises_collection_error(self) -> None:
        """collect_by_actors() raises ArenaCollectionError when snapshot status='failed'."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(_TRIGGER_URL_REELS).mock(
                return_value=httpx.Response(200, json={"snapshot_id": _SNAPSHOT_ID})
            )
            respx.get(_PROGRESS_URL).mock(
                return_value=httpx.Response(200, json={"status": "failed"})
            )
            async with httpx.AsyncClient() as client:
                collector = InstagramCollector(credential_pool=pool, http_client=client)
                with pytest.raises(ArenaCollectionError):
                    await collector.collect_by_actors(
                        actor_ids=["drnyheder"], tier=Tier.MEDIUM, max_results=5
                    )

    @pytest.mark.asyncio
    async def test_collect_by_actors_empty_snapshot_returns_empty_list(self) -> None:
        """collect_by_actors() returns [] when snapshot download returns empty list."""
        pool = _make_mock_pool()

        with respx.mock:
            _mock_brightdata_full_cycle([])
            async with httpx.AsyncClient() as client:
                collector = InstagramCollector(credential_pool=pool, http_client=client)
                records = await collector.collect_by_actors(
                    actor_ids=["drnyheder"], tier=Tier.MEDIUM, max_results=10
                )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_actors_preserves_danish_text(self) -> None:
        """Danish characters survive the full collect_by_actors -> normalize pipeline."""
        snapshot = _load_web_scraper_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            _mock_brightdata_full_cycle(snapshot)
            async with httpx.AsyncClient() as client:
                collector = InstagramCollector(credential_pool=pool, http_client=client)
                records = await collector.collect_by_actors(
                    actor_ids=["drnyheder"], tier=Tier.MEDIUM, max_results=10
                )

        texts = [r.get("text_content", "") or "" for r in records]
        assert any("\u00f8" in t or "\u00e5" in t or "\u00e6" in t for t in texts)


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
            collector = InstagramCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "social_media"
        assert result["platform"] == "instagram"
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_on_429(self) -> None:
        """health_check() returns status='degraded' when Bright Data returns 429."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get("https://api.brightdata.com/datasets/v3").mock(
                return_value=httpx.Response(429)
            )
            collector = InstagramCollector(credential_pool=pool)
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
            collector = InstagramCollector(credential_pool=pool)
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
            collector = InstagramCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "down"
        assert "403" in result.get("detail", "")

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_no_credentials(self) -> None:
        """health_check() returns status='down' when no credential pool is configured."""
        collector = InstagramCollector()  # no pool
        result = await collector.health_check()

        assert result["status"] == "down"
        assert "checked_at" in result
        assert "credential" in result.get("detail", "").lower()
