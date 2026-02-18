"""Tests for the YouTube arena collector.

Covers:
- normalize() unit tests with recorded fixture data (videos.list response)
- collect_by_terms() integration tests with mocked _client helpers
- Edge cases: empty results, quota exceeded (ArenaRateLimitError), malformed data
- health_check() test
- Danish character preservation (æ, ø, å)

These tests run without a live database or network connection.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Env bootstrap (must run before any application imports)
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==")

from issue_observatory.arenas.base import Tier  # noqa: E402
from issue_observatory.arenas.youtube.collector import YouTubeCollector  # noqa: E402
from issue_observatory.core.exceptions import ArenaRateLimitError, NoCredentialAvailableError  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "api_responses" / "youtube"


def _load_videos_fixture() -> dict[str, Any]:
    """Load the recorded videos.list fixture."""
    return json.loads((FIXTURES_DIR / "videos_list_response.json").read_text(encoding="utf-8"))


def _fixture_video_item() -> dict[str, Any]:
    """Return the first video item from the fixture."""
    return _load_videos_fixture()["items"][0]


# ---------------------------------------------------------------------------
# Credential pool mock helper
# ---------------------------------------------------------------------------


def _mock_cred_pool(api_key: str = "test_api_key_001") -> MagicMock:
    """Return a MagicMock credential pool that returns a test credential."""
    pool = AsyncMock()
    pool.acquire = AsyncMock(
        return_value={"id": "cred_test_001", "api_key": api_key, "platform": "youtube"}
    )
    pool.release = AsyncMock(return_value=None)
    return pool


# ---------------------------------------------------------------------------
# normalize() unit tests
# ---------------------------------------------------------------------------


class TestNormalize:
    def _collector(self) -> YouTubeCollector:
        return YouTubeCollector(credential_pool=_mock_cred_pool())

    def test_normalize_sets_correct_platform_arena_content_type(self) -> None:
        """normalize() writes platform='youtube', arena='social_media', content_type='video'."""
        collector = self._collector()
        item = _fixture_video_item()
        result = collector.normalize(item)

        assert result["platform"] == "youtube"
        assert result["arena"] == "social_media"
        assert result["content_type"] == "video"

    def test_normalize_platform_id_is_video_id(self) -> None:
        """normalize() sets platform_id to the YouTube video ID."""
        collector = self._collector()
        item = _fixture_video_item()
        result = collector.normalize(item)

        assert result["platform_id"] == "dXtest001"

    def test_normalize_title_from_snippet(self) -> None:
        """normalize() extracts title from snippet.title."""
        collector = self._collector()
        item = _fixture_video_item()
        result = collector.normalize(item)

        assert result["title"] == "Grøn omstilling i Danmark: Fremtiden for velfærdssamfundet"

    def test_normalize_text_content_is_description(self) -> None:
        """normalize() maps snippet.description to text_content."""
        collector = self._collector()
        item = _fixture_video_item()
        result = collector.normalize(item)

        assert result["text_content"] is not None
        assert "grøn omstilling" in result["text_content"].lower()

    def test_normalize_author_platform_id_is_channel_id(self) -> None:
        """normalize() sets author_platform_id to the channel ID."""
        collector = self._collector()
        item = _fixture_video_item()
        result = collector.normalize(item)

        assert result["author_platform_id"] == "UCtest_channel_denmark_001"

    def test_normalize_author_display_name_is_channel_title(self) -> None:
        """normalize() sets author_display_name to the channel title."""
        collector = self._collector()
        item = _fixture_video_item()
        result = collector.normalize(item)

        assert result["author_display_name"] == "DR Nyheder"

    def test_normalize_pseudonymized_author_id_is_set(self) -> None:
        """normalize() produces non-None pseudonymized_author_id when channel ID is present."""
        collector = self._collector()
        item = _fixture_video_item()
        result = collector.normalize(item)

        assert result["pseudonymized_author_id"] is not None
        assert len(result["pseudonymized_author_id"]) == 64

    def test_normalize_engagement_metrics_from_statistics(self) -> None:
        """normalize() maps viewCount, likeCount, commentCount from statistics."""
        collector = self._collector()
        item = _fixture_video_item()
        result = collector.normalize(item)

        assert result["views_count"] == 15230
        assert result["likes_count"] == 342
        assert result["comments_count"] == 87

    def test_normalize_language_from_snippet(self) -> None:
        """normalize() extracts language from defaultAudioLanguage."""
        collector = self._collector()
        item = _fixture_video_item()
        result = collector.normalize(item)

        assert result["language"] == "da"

    def test_normalize_url_constructed_from_video_id(self) -> None:
        """normalize() constructs a YouTube watch URL from the video ID."""
        collector = self._collector()
        item = _fixture_video_item()
        result = collector.normalize(item)

        assert result["url"] == "https://www.youtube.com/watch?v=dXtest001"

    def test_normalize_thumbnail_in_media_urls(self) -> None:
        """normalize() extracts high-quality thumbnail URL into media_urls."""
        collector = self._collector()
        item = _fixture_video_item()
        result = collector.normalize(item)

        assert isinstance(result["media_urls"], list)
        assert len(result["media_urls"]) >= 1
        assert "hqdefault.jpg" in result["media_urls"][0]

    def test_normalize_published_at_from_snippet(self) -> None:
        """normalize() parses publishedAt from snippet."""
        collector = self._collector()
        item = _fixture_video_item()
        result = collector.normalize(item)

        assert result["published_at"] is not None
        assert "2026-02-15" in result["published_at"]

    def test_normalize_preserves_danish_characters_in_title(self) -> None:
        """æ, ø, å in video title survive normalize() without corruption."""
        collector = self._collector()
        danish_item = {
            "id": "danish_test_001",
            "snippet": {
                "title": "Grøn omstilling og velfærdsstat i Ålborg",
                "description": "Beskrivelse med æøå tegn.",
                "publishedAt": "2026-02-15T08:00:00Z",
                "channelId": "UC_danish_channel",
                "channelTitle": "Dansk TV",
                "defaultAudioLanguage": "da",
                "thumbnails": {},
            },
            "statistics": {"viewCount": "100", "likeCount": "10", "commentCount": "2"},
        }
        result = collector.normalize(danish_item)

        assert result["title"] == "Grøn omstilling og velfærdsstat i Ålborg"
        assert "ø" in result["title"]
        assert "Å" in result["title"]

    def test_normalize_preserves_danish_in_description(self) -> None:
        """æ, ø, å in video description survive normalize()."""
        collector = self._collector()
        danish_item = {
            "id": "danish_desc_001",
            "snippet": {
                "title": "Test video",
                "description": "Grøn fremtid for velfærdssamfundet.",
                "publishedAt": "2026-02-15T08:00:00Z",
                "channelId": "UC_ch",
                "channelTitle": "Test",
                "defaultAudioLanguage": "da",
                "thumbnails": {},
            },
            "statistics": {},
        }
        result = collector.normalize(danish_item)

        assert "Grøn" in result["text_content"]
        assert "velfærdssamfundet" in result["text_content"]

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_handles_each_danish_character(self, char: str) -> None:
        """Each Danish character in title survives normalize() without error."""
        collector = self._collector()
        item = {
            "id": f"char_test_{char}",
            "snippet": {
                "title": f"Video om {char} tegn",
                "description": f"Indhold: {char}",
                "publishedAt": "2026-02-15T08:00:00Z",
                "channelId": "UC_test",
                "channelTitle": "Test",
                "defaultAudioLanguage": "da",
                "thumbnails": {},
            },
            "statistics": {},
        }
        result = collector.normalize(item)

        assert char in result["title"]

    def test_normalize_missing_statistics_produces_none_counts(self) -> None:
        """normalize() returns None engagement counts when statistics are absent."""
        collector = self._collector()
        item = {
            "id": "no_stats_001",
            "snippet": {
                "title": "Video without stats",
                "description": "Description.",
                "publishedAt": "2026-02-15T08:00:00Z",
                "channelId": "UC_nostats",
                "channelTitle": "No Stats Channel",
                "thumbnails": {},
            },
            "statistics": {},
        }
        result = collector.normalize(item)

        assert result["views_count"] is None
        assert result["likes_count"] is None
        assert result["comments_count"] is None

    def test_normalize_required_fields_always_present(self) -> None:
        """All required schema fields are present in the normalized output."""
        collector = self._collector()
        item = _fixture_video_item()
        result = collector.normalize(item)

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field None: {field}"


# ---------------------------------------------------------------------------
# collect_by_terms() integration tests — mocked _client helpers
# ---------------------------------------------------------------------------


class TestCollectByTerms:
    @pytest.mark.asyncio
    async def test_collect_by_terms_returns_records(self) -> None:
        """collect_by_terms() returns non-empty list when video IDs are found and enriched."""
        fixture_items = _load_videos_fixture()["items"]
        cred_pool = _mock_cred_pool()

        with (
            patch(
                "issue_observatory.arenas.youtube.collector.search_videos_page",
                new=AsyncMock(return_value=(["dXtest001"], None)),
            ),
            patch(
                "issue_observatory.arenas.youtube.collector.fetch_videos_batch",
                new=AsyncMock(return_value=fixture_items),
            ),
        ):
            collector = YouTubeCollector(credential_pool=cred_pool)
            records = await collector.collect_by_terms(
                terms=["grøn omstilling"], tier=Tier.FREE, max_results=10
            )

        assert isinstance(records, list)
        assert len(records) >= 1
        assert records[0]["platform"] == "youtube"
        assert records[0]["content_type"] == "video"

    @pytest.mark.asyncio
    async def test_collect_by_terms_empty_results_returns_empty_list(self) -> None:
        """collect_by_terms() returns [] when search finds no video IDs."""
        cred_pool = _mock_cred_pool()

        with (
            patch(
                "issue_observatory.arenas.youtube.collector.search_videos_page",
                new=AsyncMock(return_value=([], None)),
            ),
            patch(
                "issue_observatory.arenas.youtube.collector.fetch_videos_batch",
                new=AsyncMock(return_value=[]),
            ),
        ):
            collector = YouTubeCollector(credential_pool=cred_pool)
            records = await collector.collect_by_terms(
                terms=["totally obscure term"], tier=Tier.FREE, max_results=10
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_no_credential_raises_error(self) -> None:
        """collect_by_terms() raises NoCredentialAvailableError when no credential pool."""
        collector = YouTubeCollector(credential_pool=None)
        with pytest.raises(NoCredentialAvailableError):
            await collector.collect_by_terms(terms=["test"], tier=Tier.FREE)

    @pytest.mark.asyncio
    async def test_collect_by_terms_rate_limit_propagates(self) -> None:
        """collect_by_terms() propagates ArenaRateLimitError from search_videos_page."""
        cred_pool = _mock_cred_pool()

        with patch(
            "issue_observatory.arenas.youtube.collector.search_videos_page",
            new=AsyncMock(side_effect=ArenaRateLimitError("quota exceeded", retry_after=3600.0)),
        ):
            collector = YouTubeCollector(credential_pool=cred_pool)
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_terms(terms=["test"], tier=Tier.FREE, max_results=5)

    @pytest.mark.asyncio
    async def test_collect_by_terms_danish_text_preserved(self) -> None:
        """Danish characters in YouTube metadata survive the full collect pipeline."""
        danish_item = {
            "id": "dXdanish001",
            "snippet": {
                "title": "Grøn omstilling og velfærdsstat i Ålborg",
                "description": "Mette Frederiksen taler om folkeskolen.",
                "publishedAt": "2026-02-15T08:00:00Z",
                "channelId": "UC_danish",
                "channelTitle": "DR Nyheder",
                "defaultAudioLanguage": "da",
                "thumbnails": {"high": {"url": "https://i.ytimg.com/vi/dXdanish001/hq.jpg"}},
            },
            "statistics": {"viewCount": "1000", "likeCount": "50", "commentCount": "10"},
        }
        cred_pool = _mock_cred_pool()

        with (
            patch(
                "issue_observatory.arenas.youtube.collector.search_videos_page",
                new=AsyncMock(return_value=(["dXdanish001"], None)),
            ),
            patch(
                "issue_observatory.arenas.youtube.collector.fetch_videos_batch",
                new=AsyncMock(return_value=[danish_item]),
            ),
        ):
            collector = YouTubeCollector(credential_pool=cred_pool)
            records = await collector.collect_by_terms(
                terms=["grøn omstilling"], tier=Tier.FREE, max_results=5
            )

        assert len(records) >= 1
        assert "Grøn" in records[0]["title"]
        assert "ø" in records[0]["title"]
        assert "Å" in records[0]["title"]


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_with_no_credential_pool(self) -> None:
        """health_check() returns degraded when no credential pool is configured."""
        collector = YouTubeCollector(credential_pool=None)
        result = await collector.health_check()

        assert result["status"] == "degraded"
        assert "credential" in result.get("detail", "").lower()

    @pytest.mark.asyncio
    async def test_health_check_returns_ok_when_api_responds(self) -> None:
        """health_check() returns status='ok' when the API returns a valid item."""
        cred_pool = _mock_cred_pool()

        with patch(
            "issue_observatory.arenas.youtube._client.make_api_request",
            new=AsyncMock(
                return_value={
                    "items": [
                        {
                            "id": "dQw4w9WgXcQ",
                            "snippet": {"title": "Rick Astley - Never Gonna Give You Up"},
                        }
                    ]
                }
            ),
        ):
            collector = YouTubeCollector(credential_pool=cred_pool)
            result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "social_media"
        assert result["platform"] == "youtube"

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_when_api_returns_empty(self) -> None:
        """health_check() returns degraded when API returns no items."""
        cred_pool = _mock_cred_pool()

        with patch(
            "issue_observatory.arenas.youtube._client.make_api_request",
            new=AsyncMock(return_value={"items": []}),
        ):
            collector = YouTubeCollector(credential_pool=cred_pool)
            result = await collector.health_check()

        assert result["status"] == "degraded"
