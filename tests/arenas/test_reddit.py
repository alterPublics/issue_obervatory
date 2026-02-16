"""Tests for the Reddit arena collector.

Reddit uses the asyncpraw library rather than direct HTTP, so these tests
mock the asyncpraw.Reddit client instead of HTTP endpoints.

Covers:
- normalize() unit tests with raw dicts mirroring asyncpraw model output
- collect_by_terms() integration tests with mocked asyncpraw client
- Edge cases: empty results, rate limit, malformed data, missing author
- health_check() test
- Danish character preservation (æ, ø, å)

These tests run without a live database or network connection.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Env bootstrap (must run before any application imports)
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==")
# Set reddit env vars so _acquire_credential() env-var fallback works in tests
os.environ.setdefault("REDDIT_CLIENT_ID", "test_client_id")
os.environ.setdefault("REDDIT_CLIENT_SECRET", "test_client_secret")

from issue_observatory.arenas.base import Tier  # noqa: E402
from issue_observatory.arenas.reddit.collector import RedditCollector  # noqa: E402
from issue_observatory.core.exceptions import ArenaRateLimitError  # noqa: E402

# ---------------------------------------------------------------------------
# Raw item helpers (mirrors what _post_to_raw / _comment_to_raw produce)
# ---------------------------------------------------------------------------


def _make_raw_post(
    post_id: str = "test001",
    title: str = "Test post title",
    selftext: str = "Test post body",
    author_name: str = "testuser",
    score: int = 100,
    num_comments: int = 10,
    subreddit: str = "Denmark",
) -> dict[str, Any]:
    """Build a raw post dict equivalent to what _post_to_raw() produces."""
    return {
        "content_type": "post",
        "platform_id": post_id,
        "title": title,
        "text_content": selftext,
        "body": selftext,
        "url": f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/",
        "published_at": 1739620200.0,
        "author_platform_id": author_name,
        "author_display_name": author_name,
        "score": score,
        "likes_count": score,
        "num_comments": num_comments,
        "comments_count": num_comments,
        "shares_count": 0,
        "engagement_score": 0.92,
        "media_urls": [],
        "subreddit": subreddit,
        "subreddit_id": "t5_2qiuf",
        "link_flair_text": None,
        "is_self": True,
        "domain": f"self.{subreddit}",
        "over_18": False,
        "spoiler": False,
        "stickied": False,
        "distinguished": None,
        "gilded": 0,
        "post_type": "self",
        "permalink": f"/r/{subreddit}/comments/{post_id}/",
        "upvote_ratio": 0.92,
        "search_term_matched": None,
    }


def _make_raw_comment(
    comment_id: str = "comment001",
    body: str = "Test comment body",
    author_name: str = "commenter",
    score: int = 5,
    subreddit: str = "Denmark",
) -> dict[str, Any]:
    """Build a raw comment dict equivalent to what _comment_to_raw() produces."""
    return {
        "content_type": "comment",
        "platform_id": comment_id,
        "title": None,
        "text_content": body,
        "body": body,
        "url": f"https://www.reddit.com/r/{subreddit}/comments/parent/comment/{comment_id}/",
        "published_at": 1739620300.0,
        "author_platform_id": author_name,
        "author_display_name": author_name,
        "score": score,
        "likes_count": score,
        "num_comments": None,
        "comments_count": None,
        "shares_count": None,
        "engagement_score": None,
        "media_urls": [],
        "subreddit": subreddit,
        "subreddit_id": "t5_2qiuf",
        "link_flair_text": None,
        "is_self": None,
        "domain": None,
        "over_18": False,
        "spoiler": False,
        "stickied": False,
        "distinguished": None,
        "gilded": 0,
        "post_type": None,
        "permalink": f"/r/{subreddit}/comments/parent/comment/{comment_id}/",
        "upvote_ratio": None,
        "parent_id": "t3_parent",
        "depth": 0,
        "parent_post_id": None,
        "parent_post_title": None,
    }


# ---------------------------------------------------------------------------
# normalize() unit tests
# ---------------------------------------------------------------------------


class TestNormalize:
    def _collector(self) -> RedditCollector:
        return RedditCollector()

    def test_normalize_post_sets_correct_platform_arena_content_type(self) -> None:
        """normalize() sets platform='reddit', arena='social_media', content_type='post'."""
        collector = self._collector()
        raw = _make_raw_post()
        result = collector.normalize(raw)

        assert result["platform"] == "reddit"
        assert result["arena"] == "social_media"
        assert result["content_type"] == "post"

    def test_normalize_comment_sets_correct_content_type(self) -> None:
        """normalize() sets content_type='comment' for comment raw items."""
        collector = self._collector()
        raw = _make_raw_comment()
        result = collector.normalize(raw)

        assert result["content_type"] == "comment"

    def test_normalize_post_title_preserved(self) -> None:
        """normalize() preserves the post title field."""
        collector = self._collector()
        raw = _make_raw_post(title="Folkeskolen i Danmark bør reformeres")
        result = collector.normalize(raw)

        assert result["title"] == "Folkeskolen i Danmark bør reformeres"

    def test_normalize_post_pseudonymized_author_id_is_set(self) -> None:
        """normalize() produces non-None pseudonymized_author_id when author is present."""
        collector = self._collector()
        raw = _make_raw_post(author_name="danskdebattoer")
        result = collector.normalize(raw)

        assert result["pseudonymized_author_id"] is not None
        assert len(result["pseudonymized_author_id"]) == 64

    def test_normalize_post_engagement_metrics_mapped(self) -> None:
        """normalize() maps score to likes_count and num_comments to comments_count."""
        collector = self._collector()
        raw = _make_raw_post(score=156, num_comments=47)
        result = collector.normalize(raw)

        assert result["likes_count"] == 156
        assert result["comments_count"] == 47

    def test_normalize_post_published_at_from_unix_timestamp(self) -> None:
        """normalize() converts created_utc Unix timestamp to an ISO 8601 string."""
        collector = self._collector()
        raw = _make_raw_post()
        result = collector.normalize(raw)

        # Unix 1739620200 = 2026-02-15
        assert result["published_at"] is not None
        assert "2026-02-15" in result["published_at"]

    def test_normalize_post_collection_tier_is_free(self) -> None:
        """normalize() sets collection_tier='free' (Reddit is free-only)."""
        collector = self._collector()
        raw = _make_raw_post()
        result = collector.normalize(raw)

        assert result["collection_tier"] == "free"

    def test_normalize_post_missing_author_produces_none_pseudonym(self) -> None:
        """normalize() handles None author gracefully — pseudonymized_author_id is None."""
        collector = self._collector()
        raw = _make_raw_post(author_name="")
        raw["author_platform_id"] = None
        raw["author_display_name"] = None
        result = collector.normalize(raw)

        assert result["pseudonymized_author_id"] is None

    def test_normalize_deleted_comment_body_maps_to_none(self) -> None:
        """normalize() maps deleted/removed comment body to None text_content."""
        collector = self._collector()
        raw = _make_raw_comment(body="")
        raw["text_content"] = None
        raw["body"] = None
        result = collector.normalize(raw)

        assert result["text_content"] is None

    def test_normalize_preserves_danish_characters_in_post_title(self) -> None:
        """æ, ø, å in post title survive normalize() without corruption."""
        collector = self._collector()
        danish_title = "Hvad synes I om folkeskolen i Danmark? Diskussion om æøå og reform"
        raw = _make_raw_post(title=danish_title)
        result = collector.normalize(raw)

        assert result["title"] == danish_title
        assert "æ" in result["title"]
        assert "ø" in result["title"]
        assert "å" in result["title"]

    def test_normalize_preserves_danish_characters_in_body(self) -> None:
        """æ, ø, å in post body text survive normalize() without corruption."""
        collector = self._collector()
        danish_body = "Aarhus kommune og Ålborg har grønne planer for velfærden."
        raw = _make_raw_post(selftext=danish_body)
        result = collector.normalize(raw)

        assert result["text_content"] == danish_body

    def test_normalize_preserves_danish_author_name(self) -> None:
        """Danish characters in author names survive normalize()."""
        collector = self._collector()
        raw = _make_raw_post(author_name="søren_øberg")
        result = collector.normalize(raw)

        assert result["author_display_name"] == "søren_øberg"

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_handles_each_danish_character_in_title(self, char: str) -> None:
        """Each Danish character in title survives normalize() without error."""
        collector = self._collector()
        raw = _make_raw_post(title=f"Artikel med {char} tegn")
        result = collector.normalize(raw)

        assert char in result["title"]

    def test_normalize_required_fields_always_present(self) -> None:
        """All required schema fields are present in the normalized output."""
        collector = self._collector()
        raw = _make_raw_post()
        result = collector.normalize(raw)

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field None: {field}"


# ---------------------------------------------------------------------------
# collect_by_terms() integration tests — mocked asyncpraw
# ---------------------------------------------------------------------------


def _make_mock_post(
    post_id: str = "test001",
    title: str = "Test post",
    selftext: str = "Test body",
    author_name: str = "testuser",
    score: int = 50,
    num_comments: int = 5,
    subreddit_name: str = "Denmark",
) -> MagicMock:
    """Build a MagicMock simulating an asyncpraw.models.Submission."""
    post = MagicMock()
    post.id = post_id
    post.title = title
    post.selftext = selftext

    author = MagicMock()
    author.name = author_name
    post.author = author

    subreddit = MagicMock()
    subreddit.__str__ = lambda _: subreddit_name
    post.subreddit = subreddit

    post.score = score
    post.num_comments = num_comments
    post.permalink = f"/r/{subreddit_name}/comments/{post_id}/"
    post.url = f"https://www.reddit.com/r/{subreddit_name}/comments/{post_id}/"
    post.created_utc = 1739620200.0
    post.upvote_ratio = 0.92
    post.subreddit_id = "t5_2qiuf"
    post.link_flair_text = None
    post.is_self = True
    post.is_video = False
    post.post_hint = ""
    post.domain = f"self.{subreddit_name}"
    post.over_18 = False
    post.spoiler = False
    post.stickied = False
    post.distinguished = None
    post.gilded = 0
    post.num_crossposts = 0
    return post


async def _async_generator_from_list(items: list) -> Any:
    """Yield items from a list as an async generator."""
    for item in items:
        yield item


class TestCollectByTerms:
    @pytest.mark.asyncio
    async def test_collect_by_terms_returns_records(self) -> None:
        """collect_by_terms() returns normalized records from asyncpraw search results."""
        mock_post = _make_mock_post(
            post_id="abc001",
            title="Folkeskolen i Aarhus diskuteres",
            selftext="En god diskussion om folkeskolen.",
        )

        async def fake_search(*args, **kwargs):
            yield mock_post

        mock_subreddit = AsyncMock()
        mock_subreddit.search = MagicMock(side_effect=lambda *a, **kw: _async_generator_from_list([mock_post]))

        mock_reddit = AsyncMock()
        mock_reddit.subreddit = AsyncMock(return_value=mock_subreddit)
        mock_reddit.__aenter__ = AsyncMock(return_value=mock_reddit)
        mock_reddit.__aexit__ = AsyncMock(return_value=None)

        collector = RedditCollector()

        with patch(
            "issue_observatory.arenas.reddit.collector.RedditCollector._build_reddit_client",
            new=AsyncMock(return_value=mock_reddit),
        ):
            records = await collector.collect_by_terms(
                terms=["folkeskolen"], tier=Tier.FREE, max_results=10
            )

        assert isinstance(records, list)
        assert len(records) >= 1
        assert records[0]["platform"] == "reddit"
        assert records[0]["content_type"] == "post"

    @pytest.mark.asyncio
    async def test_collect_by_terms_empty_search_returns_empty_list(self) -> None:
        """collect_by_terms() returns [] when asyncpraw search yields no posts."""
        mock_subreddit = AsyncMock()
        mock_subreddit.search = MagicMock(side_effect=lambda *a, **kw: _async_generator_from_list([]))

        mock_reddit = AsyncMock()
        mock_reddit.subreddit = AsyncMock(return_value=mock_subreddit)
        mock_reddit.__aenter__ = AsyncMock(return_value=mock_reddit)
        mock_reddit.__aexit__ = AsyncMock(return_value=None)

        collector = RedditCollector()

        with patch(
            "issue_observatory.arenas.reddit.collector.RedditCollector._build_reddit_client",
            new=AsyncMock(return_value=mock_reddit),
        ):
            records = await collector.collect_by_terms(
                terms=["obscure_term_xyz"], tier=Tier.FREE, max_results=10
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_rate_limit_raises_arena_rate_limit_error(self) -> None:
        """collect_by_terms() raises ArenaRateLimitError when asyncpraw hits rate limit."""
        import asyncprawcore.exceptions

        mock_subreddit = AsyncMock()

        async def rate_limited_search(*args, **kwargs):
            raise asyncprawcore.exceptions.TooManyRequests(MagicMock())
            yield  # Make it an async generator

        mock_subreddit.search = MagicMock(side_effect=rate_limited_search)

        mock_reddit = AsyncMock()
        mock_reddit.subreddit = AsyncMock(return_value=mock_subreddit)
        mock_reddit.__aenter__ = AsyncMock(return_value=mock_reddit)
        mock_reddit.__aexit__ = AsyncMock(return_value=None)

        collector = RedditCollector()

        with patch(
            "issue_observatory.arenas.reddit.collector.RedditCollector._build_reddit_client",
            new=AsyncMock(return_value=mock_reddit),
        ):
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_terms(
                    terms=["test"], tier=Tier.FREE, max_results=5
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_deduplicates_posts(self) -> None:
        """collect_by_terms() deduplicates posts with the same ID across multiple terms."""
        mock_post = _make_mock_post(post_id="dup001", title="Duplicate post")

        mock_subreddit = AsyncMock()
        mock_subreddit.search = MagicMock(
            side_effect=lambda *a, **kw: _async_generator_from_list([mock_post])
        )

        mock_reddit = AsyncMock()
        mock_reddit.subreddit = AsyncMock(return_value=mock_subreddit)
        mock_reddit.__aenter__ = AsyncMock(return_value=mock_reddit)
        mock_reddit.__aexit__ = AsyncMock(return_value=None)

        collector = RedditCollector()

        with patch(
            "issue_observatory.arenas.reddit.collector.RedditCollector._build_reddit_client",
            new=AsyncMock(return_value=mock_reddit),
        ):
            # Pass same post ID from two different search terms
            records = await collector.collect_by_terms(
                terms=["term1", "term2"], tier=Tier.FREE, max_results=20
            )

        post_ids = [r["platform_id"] for r in records]
        assert post_ids.count("dup001") == 1, "Duplicate post should appear only once"

    @pytest.mark.asyncio
    async def test_collect_by_terms_danish_text_preserved_in_records(self) -> None:
        """Danish characters in Reddit posts survive the full collect pipeline."""
        danish_title = "Grøn omstilling og velfærdsstat i Ålborg"
        mock_post = _make_mock_post(
            post_id="danish001",
            title=danish_title,
            selftext="Diskussion om æøå og klima.",
        )

        mock_subreddit = AsyncMock()
        mock_subreddit.search = MagicMock(
            side_effect=lambda *a, **kw: _async_generator_from_list([mock_post])
        )

        mock_reddit = AsyncMock()
        mock_reddit.subreddit = AsyncMock(return_value=mock_subreddit)
        mock_reddit.__aenter__ = AsyncMock(return_value=mock_reddit)
        mock_reddit.__aexit__ = AsyncMock(return_value=None)

        collector = RedditCollector()

        with patch(
            "issue_observatory.arenas.reddit.collector.RedditCollector._build_reddit_client",
            new=AsyncMock(return_value=mock_reddit),
        ):
            records = await collector.collect_by_terms(
                terms=["grøn omstilling"], tier=Tier.FREE, max_results=10
            )

        assert len(records) >= 1
        assert records[0]["title"] == danish_title
        assert "ø" in records[0]["title"]
        assert "å" in records[0]["title"]


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_ok_on_success(self) -> None:
        """health_check() returns status='ok' when Reddit client is reachable."""
        mock_post = _make_mock_post(post_id="health_post_001")

        mock_subreddit = AsyncMock()
        mock_subreddit.hot = MagicMock(side_effect=lambda limit: _async_generator_from_list([mock_post]))

        mock_reddit = AsyncMock()
        mock_reddit.subreddit = AsyncMock(return_value=mock_subreddit)
        mock_reddit.__aenter__ = AsyncMock(return_value=mock_reddit)
        mock_reddit.__aexit__ = AsyncMock(return_value=None)

        collector = RedditCollector()

        with patch(
            "issue_observatory.arenas.reddit.collector.RedditCollector._build_reddit_client",
            new=AsyncMock(return_value=mock_reddit),
        ):
            result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "social_media"
        assert result["platform"] == "reddit"

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_exception(self) -> None:
        """health_check() returns status='down' when connection fails."""
        collector = RedditCollector()

        with patch(
            "issue_observatory.arenas.reddit.collector.RedditCollector._build_reddit_client",
            new=AsyncMock(side_effect=Exception("connection refused")),
        ):
            result = await collector.health_check()

        assert result["status"] == "down"
        assert "arena" in result
        assert "platform" in result
