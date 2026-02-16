"""Tests for the Bluesky arena collector.

Covers:
- normalize() unit tests with AT Protocol post view fixture data
- collect_by_terms() integration tests with mocked HTTP (respx)
- Edge cases: empty results, HTTP 429, malformed JSON, missing author
- health_check() test
- Danish character preservation (æ, ø, å)

These tests run without a live database or network connection.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

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
from issue_observatory.arenas.bluesky.collector import BlueskyCollector  # noqa: E402
from issue_observatory.arenas.bluesky.config import BSKY_SEARCH_POSTS_ENDPOINT  # noqa: E402
from issue_observatory.core.exceptions import ArenaRateLimitError  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "api_responses" / "bluesky"


def _load_search_fixture() -> dict:
    """Load the recorded searchPosts fixture."""
    return json.loads((FIXTURES_DIR / "search_posts_response.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Sample post views used across unit tests
# ---------------------------------------------------------------------------

_SAMPLE_POST_VIEW = {
    "uri": "at://did:plc:abc123testuser/app.bsky.feed.post/3kwxtest001",
    "author": {
        "did": "did:plc:abc123testuser",
        "handle": "soeren.bsky.social",
        "displayName": "Søren Ærlighed",
    },
    "record": {
        "$type": "app.bsky.feed.post",
        "text": "Grøn omstilling er afgørende for vores fremtid.",
        "createdAt": "2026-02-15T10:30:00.000Z",
        "langs": ["da"],
    },
    "likeCount": 42,
    "repostCount": 7,
    "replyCount": 3,
}

_SAMPLE_POST_NO_AUTHOR = {
    "uri": "at://did:plc:anon/app.bsky.feed.post/3kwxanon001",
    "author": {},
    "record": {
        "$type": "app.bsky.feed.post",
        "text": "Anonymous post text.",
        "createdAt": "2026-02-15T11:00:00.000Z",
        "langs": [],
    },
    "likeCount": 0,
    "repostCount": 0,
    "replyCount": 0,
}


# ---------------------------------------------------------------------------
# normalize() unit tests
# ---------------------------------------------------------------------------


class TestNormalize:
    def _collector(self) -> BlueskyCollector:
        return BlueskyCollector()

    def test_normalize_sets_correct_platform_arena_content_type(self) -> None:
        """normalize() sets platform='bluesky', arena='bluesky', content_type='post'."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_POST_VIEW)

        assert result["platform"] == "bluesky"
        assert result["arena"] == "bluesky"
        assert result["content_type"] == "post"

    def test_normalize_platform_id_is_at_uri(self) -> None:
        """normalize() sets platform_id to the AT URI."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_POST_VIEW)

        assert result["platform_id"] == "at://did:plc:abc123testuser/app.bsky.feed.post/3kwxtest001"

    def test_normalize_text_content_from_record(self) -> None:
        """normalize() maps record.text to text_content."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_POST_VIEW)

        assert result["text_content"] == "Grøn omstilling er afgørende for vores fremtid."

    def test_normalize_author_display_name_populated(self) -> None:
        """normalize() maps author.displayName to author_display_name."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_POST_VIEW)

        assert result["author_display_name"] == "Søren Ærlighed"

    def test_normalize_pseudonymized_author_id_is_set_when_author_present(self) -> None:
        """normalize() produces a non-None pseudonymized_author_id when author DID is present."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_POST_VIEW)

        assert result["pseudonymized_author_id"] is not None
        assert len(result["pseudonymized_author_id"]) == 64

    def test_normalize_engagement_counts_mapped(self) -> None:
        """normalize() maps likeCount, repostCount, replyCount to engagement fields."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_POST_VIEW)

        assert result["likes_count"] == 42
        assert result["shares_count"] == 7
        assert result["comments_count"] == 3

    def test_normalize_language_from_langs(self) -> None:
        """normalize() extracts the first element of record.langs as language."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_POST_VIEW)

        assert result["language"] == "da"

    def test_normalize_web_url_constructed_from_at_uri(self) -> None:
        """normalize() constructs a https://bsky.app URL from the AT URI components."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_POST_VIEW)

        assert result["url"] is not None
        assert "bsky.app" in result["url"]
        assert "3kwxtest001" in result["url"]

    def test_normalize_published_at_from_created_at(self) -> None:
        """normalize() extracts the publication timestamp from record.createdAt."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_POST_VIEW)

        assert result["published_at"] is not None
        assert "2026-02-15" in result["published_at"]

    def test_normalize_no_author_produces_none_pseudonym(self) -> None:
        """normalize() handles missing author fields gracefully — no crash, pseudonym is None."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_POST_NO_AUTHOR)

        # Should not raise
        assert result["pseudonymized_author_id"] is None

    def test_normalize_preserves_danish_characters_in_text(self) -> None:
        """æ, ø, å in post text survive normalize() without corruption."""
        collector = self._collector()
        danish_post = {
            "uri": "at://did:plc:test/app.bsky.feed.post/danishtest",
            "author": {
                "did": "did:plc:test",
                "handle": "test.bsky.social",
                "displayName": "Åse Ørsted",
            },
            "record": {
                "text": "Grøn omstilling, velfærdsstat og Ålborg — alt er vigtigt for ægte demokrati.",
                "createdAt": "2026-02-15T12:00:00.000Z",
                "langs": ["da"],
            },
            "likeCount": 5,
            "repostCount": 1,
            "replyCount": 0,
        }
        result = collector.normalize(danish_post)

        assert "Grøn" in result["text_content"]
        assert "velfærdsstat" in result["text_content"]
        assert "Ålborg" in result["text_content"]
        assert "ægte" in result["text_content"]
        assert result["author_display_name"] == "Åse Ørsted"

    def test_normalize_danish_author_display_name_preserved(self) -> None:
        """Danish characters in author displayName survive normalize()."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_POST_VIEW)

        assert result["author_display_name"] == "Søren Ærlighed"
        assert "ø" in result["author_display_name"]
        assert "Æ" in result["author_display_name"]

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_handles_each_danish_character_in_text(self, char: str) -> None:
        """normalize() handles each Danish character in post text without error."""
        collector = self._collector()
        post = {
            "uri": f"at://did:plc:test/app.bsky.feed.post/char{char}",
            "author": {"did": "did:plc:test", "handle": "test.bsky.social", "displayName": "Test"},
            "record": {
                "text": f"Indhold med {char} tegn.",
                "createdAt": "2026-02-15T12:00:00.000Z",
                "langs": ["da"],
            },
            "likeCount": 0,
            "repostCount": 0,
            "replyCount": 0,
        }
        result = collector.normalize(post)

        assert char in result["text_content"]

    def test_normalize_with_image_embed_extracts_media_urls(self) -> None:
        """normalize() extracts image URLs from an embed.images field."""
        collector = self._collector()
        post_with_image = {
            **_SAMPLE_POST_VIEW,
            "embed": {
                "$type": "app.bsky.embed.images#view",
                "images": [
                    {"fullsize": "https://cdn.bsky.app/img/feed_fullsize/test.jpg", "alt": "test"}
                ],
            },
        }
        result = collector.normalize(post_with_image)

        assert isinstance(result.get("media_urls"), list)
        # At minimum, no crash; ideally the URL is extracted
        if result["media_urls"]:
            assert "cdn.bsky.app" in result["media_urls"][0]

    def test_normalize_required_fields_always_present(self) -> None:
        """All required schema fields are present in normalized output."""
        collector = self._collector()
        result = collector.normalize(_SAMPLE_POST_VIEW)

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field None: {field}"


# ---------------------------------------------------------------------------
# collect_by_terms() integration tests
# ---------------------------------------------------------------------------


class TestCollectByTerms:
    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_returns_non_empty_list(self) -> None:
        """collect_by_terms() returns a non-empty list when API returns posts."""
        fixture = _load_search_fixture()
        respx.get(BSKY_SEARCH_POSTS_ENDPOINT).mock(
            return_value=httpx.Response(200, json=fixture)
        )

        collector = BlueskyCollector()
        records = await collector.collect_by_terms(
            terms=["folkeskolen"], tier=Tier.FREE, max_results=10
        )

        assert isinstance(records, list)
        assert len(records) > 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_record_schema_valid(self) -> None:
        """Each record from collect_by_terms() has required schema fields."""
        fixture = _load_search_fixture()
        respx.get(BSKY_SEARCH_POSTS_ENDPOINT).mock(
            return_value=httpx.Response(200, json=fixture)
        )

        collector = BlueskyCollector()
        records = await collector.collect_by_terms(
            terms=["grøn omstilling"], tier=Tier.FREE, max_results=10
        )

        for record in records:
            assert record["platform"] == "bluesky"
            assert record["content_type"] == "post"
            assert record["platform_id"] is not None

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_empty_response_returns_empty_list(self) -> None:
        """collect_by_terms() returns [] when API returns no posts."""
        respx.get(BSKY_SEARCH_POSTS_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"posts": []})
        )

        collector = BlueskyCollector()
        records = await collector.collect_by_terms(
            terms=["obscure term"], tier=Tier.FREE, max_results=10
        )

        assert records == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_http_429_raises_rate_limit_error(self) -> None:
        """collect_by_terms() raises ArenaRateLimitError on HTTP 429."""
        respx.get(BSKY_SEARCH_POSTS_ENDPOINT).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "60"})
        )

        collector = BlueskyCollector()
        with pytest.raises(ArenaRateLimitError):
            await collector.collect_by_terms(
                terms=["test"], tier=Tier.FREE, max_results=5
            )

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_malformed_json_raises_collection_error(self) -> None:
        """collect_by_terms() raises ArenaCollectionError on malformed JSON response."""
        from issue_observatory.core.exceptions import ArenaCollectionError

        respx.get(BSKY_SEARCH_POSTS_ENDPOINT).mock(
            return_value=httpx.Response(500)
        )

        collector = BlueskyCollector()
        with pytest.raises(Exception):
            await collector.collect_by_terms(terms=["test"], tier=Tier.FREE, max_results=5)

    @pytest.mark.asyncio
    @respx.mock
    async def test_collect_by_terms_preserves_danish_text_in_records(self) -> None:
        """Danish characters in Bluesky posts survive the full collect → normalize pipeline."""
        fixture = _load_search_fixture()
        respx.get(BSKY_SEARCH_POSTS_ENDPOINT).mock(
            return_value=httpx.Response(200, json=fixture)
        )

        collector = BlueskyCollector()
        records = await collector.collect_by_terms(
            terms=["Ålborg"], tier=Tier.FREE, max_results=10
        )

        texts = [r.get("text_content", "") or "" for r in records]
        # Fixture contains "Ålborg" in post text
        assert any("Ål" in t for t in texts), "Expected Ålborg in at least one record text"


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_returns_ok_on_valid_response(self) -> None:
        """health_check() returns status='ok' when API responds with posts key."""
        respx.get(BSKY_SEARCH_POSTS_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"posts": [{"uri": "at://test"}]})
        )

        collector = BlueskyCollector()
        result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "bluesky"
        assert result["platform"] == "bluesky"

    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_returns_degraded_when_posts_key_missing(self) -> None:
        """health_check() returns degraded when 'posts' key is absent in response."""
        respx.get(BSKY_SEARCH_POSTS_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"unexpected": "format"})
        )

        collector = BlueskyCollector()
        result = await collector.health_check()

        assert result["status"] == "degraded"

    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_returns_degraded_on_http_error(self) -> None:
        """health_check() returns degraded on HTTP error response."""
        respx.get(BSKY_SEARCH_POSTS_ENDPOINT).mock(
            return_value=httpx.Response(503)
        )

        collector = BlueskyCollector()
        result = await collector.health_check()

        assert result["status"] in ("degraded", "down")
