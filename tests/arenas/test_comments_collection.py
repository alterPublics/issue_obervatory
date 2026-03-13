"""Tests for the Comments Collection Module.

Covers per-platform ``collect_comments()`` implementations for six platforms
(Reddit, Bluesky, YouTube, TikTok, Facebook, Instagram), plus the orchestration
task ``trigger_comment_collection`` and the helper
``fetch_posts_for_comment_collection``.

All tests are pure unit tests — no live network connections or databases are
required.  External I/O is mocked via ``unittest.mock`` and ``respx``.

Platform coverage:
- Reddit: asyncpraw mocking, comment extraction/normalization, depth filtering.
- Bluesky: httpx mocking via getPostThread, reply extraction.
- YouTube: httpx mocking via commentThreads.list, pagination, reply depth.
- TikTok: httpx mocking via research comment list endpoint, cursor pagination.
- Facebook: BrightDataCommentCollector delegation, credential acquisition.
- Instagram: same Bright Data pattern as Facebook.

Orchestration coverage:
- trigger_comment_collection dispatches correct platform tasks.
- fetch_posts_for_comment_collection handles ``search_terms``,
  ``source_list_actors``, and ``post_urls`` modes.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Module-level filterwarnings: suppress ResourceWarning arising from unclosed
# Redis / DB connections that are created during workers.tasks module import
# (Celery + asyncpg engine construction happens at module level).
# These are teardown artefacts from the module import side-effect, not test bugs.
pytestmark = pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnraisableExceptionWarning",
    "ignore::ResourceWarning",
)

# ---------------------------------------------------------------------------
# Environment bootstrap — must run before any application imports
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only-xxxxx-xxxxx-xxxxx")
# Valid Fernet key required for Settings validation when workers modules are imported.
os.environ.setdefault(
    "CREDENTIAL_ENCRYPTION_KEY", "NTB2qKXBV1LU6L_dZKyS_-m-s8iWi_12SqRrMHIPOxM="
)
# A valid DATABASE_URL is needed for module-level DB engine construction in workers.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:test@localhost:5432/test_observatory",
)
# Redis URL needed by Celery app module.  Use the localhost default.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
# Reddit env-var fallback so _acquire_credential() works without a pool
os.environ.setdefault("REDDIT_CLIENT_ID", "test_client_id")
os.environ.setdefault("REDDIT_CLIENT_SECRET", "test_client_secret")


from issue_observatory.arenas.base import Tier
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)

# ---------------------------------------------------------------------------
# Shared mock factory helpers
# ---------------------------------------------------------------------------


def _mock_pool(
    platform: str = "reddit",
    cred_id: str = "cred-001",
    api_key: str = "test_api_key",
    extra: dict | None = None,
) -> AsyncMock:
    """Return an AsyncMock credential pool for any platform."""
    pool = AsyncMock()
    cred: dict[str, Any] = {"id": cred_id, "api_key": api_key, "platform": platform}
    if extra:
        cred.update(extra)
    pool.acquire = AsyncMock(return_value=cred)
    pool.release = AsyncMock(return_value=None)
    return pool


# ===========================================================================
# REDDIT
# ===========================================================================


class TestRedditCollectComments:
    """Unit tests for RedditCollector.collect_comments()."""

    def _collector(self) -> Any:
        from issue_observatory.arenas.reddit.collector import RedditCollector

        return RedditCollector()

    # ------------------------------------------------------------------
    # Helpers — fake asyncpraw objects
    # ------------------------------------------------------------------

    @staticmethod
    def _make_fake_comment(
        comment_id: str = "c001",
        body: str = "Great post!",
        depth: int = 0,
        score: int = 10,
    ) -> MagicMock:
        """Build a minimal fake asyncpraw Comment object."""
        comment = MagicMock()
        comment.id = comment_id
        comment.body = body
        comment.depth = depth
        comment.score = score
        comment.created_utc = 1739620300.0
        comment.author = MagicMock()
        comment.author.name = "commenter_user"
        comment.subreddit = MagicMock()
        comment.subreddit.__str__ = lambda self: "Denmark"
        comment.subreddit_id = "t5_2qiuf"
        comment.permalink = f"/r/Denmark/comments/p001/{comment_id}/"
        comment.stickied = False
        comment.distinguished = None
        comment.gilded = 0
        comment.over_18 = False
        comment.parent_id = "t3_p001"
        comment.author_fullname = "t2_abc"
        return comment

    @staticmethod
    def _make_fake_submission(
        post_id: str = "p001",
        title: str = "Test post",
        comments: list | None = None,
    ) -> AsyncMock:
        """Build a minimal fake asyncpraw Submission object."""
        sub = AsyncMock()
        sub.id = post_id
        sub.title = title
        sub.selftext = "post body text"
        sub.author = MagicMock()
        sub.author.name = "poster_user"
        sub.permalink = f"/r/Denmark/comments/{post_id}/"
        sub.score = 100
        sub.num_comments = 5
        sub.subreddit = MagicMock()
        sub.subreddit.__str__ = lambda self: "Denmark"
        sub.subreddit_id = "t5_2qiuf"
        sub.created_utc = 1739620200.0
        sub.is_self = True
        sub.is_video = False
        sub.upvote_ratio = 0.92

        fake_comments = comments or []
        sub.comments = AsyncMock()
        sub.comments.replace_more = AsyncMock(return_value=None)
        sub.comments.list = MagicMock(return_value=fake_comments)
        return sub

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_collect_comments_returns_normalized_records(self) -> None:
        """collect_comments() returns one normalized record per comment."""
        fake_comment = self._make_fake_comment("c001", "Very interesting!")
        fake_sub = self._make_fake_submission("p001", comments=[fake_comment])

        collector = self._collector()

        async def _fake_ctx_enter(self_inner):  # noqa: ANN001
            return self_inner

        async def _fake_ctx_exit(self_inner, *args):  # noqa: ANN001
            pass

        fake_reddit = AsyncMock()
        fake_reddit.__aenter__ = _fake_ctx_enter
        fake_reddit.__aexit__ = _fake_ctx_exit
        fake_reddit.submission = AsyncMock(return_value=fake_sub)

        with patch.object(collector, "_build_reddit_client", return_value=fake_reddit):
            records = await collector.collect_comments(
                post_ids=[{"platform_id": "p001"}],
                tier=Tier.FREE,
            )

        assert len(records) == 1
        rec = records[0]
        assert rec["platform"] == "reddit"
        assert rec["content_type"] == "comment"
        assert rec["text_content"] == "Very interesting!"

    @pytest.mark.asyncio
    async def test_collect_comments_skips_entry_with_no_platform_id(self) -> None:
        """Entries without 'platform_id' are silently skipped."""
        collector = self._collector()

        fake_reddit = AsyncMock()
        fake_reddit.__aenter__ = AsyncMock(return_value=fake_reddit)
        fake_reddit.__aexit__ = AsyncMock(return_value=None)

        with patch.object(collector, "_build_reddit_client", return_value=fake_reddit):
            records = await collector.collect_comments(
                post_ids=[{"platform_id": ""}],
                tier=Tier.FREE,
            )

        assert records == []
        fake_reddit.submission.assert_not_called()

    @pytest.mark.asyncio
    async def test_collect_comments_depth_zero_excludes_nested(self) -> None:
        """depth=0 only includes top-level comments (depth attribute == 0)."""
        top_level = self._make_fake_comment("c001", "top-level reply", depth=0)
        nested = self._make_fake_comment("c002", "nested reply", depth=1)
        fake_sub = self._make_fake_submission("p001", comments=[top_level, nested])

        collector = self._collector()
        fake_reddit = AsyncMock()
        fake_reddit.__aenter__ = AsyncMock(return_value=fake_reddit)
        fake_reddit.__aexit__ = AsyncMock(return_value=None)
        fake_reddit.submission = AsyncMock(return_value=fake_sub)

        with patch.object(collector, "_build_reddit_client", return_value=fake_reddit):
            records = await collector.collect_comments(
                post_ids=[{"platform_id": "p001"}],
                tier=Tier.FREE,
                depth=0,
            )

        # Only the top-level comment should appear
        assert len(records) == 1
        assert records[0]["text_content"] == "top-level reply"

    @pytest.mark.asyncio
    async def test_collect_comments_depth_one_includes_nested(self) -> None:
        """depth=1 allows both depth-0 and depth-1 comments."""
        top_level = self._make_fake_comment("c001", "top-level", depth=0)
        nested = self._make_fake_comment("c002", "nested reply", depth=1)
        fake_sub = self._make_fake_submission("p001", comments=[top_level, nested])

        collector = self._collector()
        fake_reddit = AsyncMock()
        fake_reddit.__aenter__ = AsyncMock(return_value=fake_reddit)
        fake_reddit.__aexit__ = AsyncMock(return_value=None)
        fake_reddit.submission = AsyncMock(return_value=fake_sub)

        with patch.object(collector, "_build_reddit_client", return_value=fake_reddit):
            records = await collector.collect_comments(
                post_ids=[{"platform_id": "p001"}],
                tier=Tier.FREE,
                depth=1,
            )

        assert len(records) == 2

    @pytest.mark.asyncio
    async def test_collect_comments_respects_max_per_post(self) -> None:
        """max_comments_per_post caps records collected from a single post."""
        comments = [self._make_fake_comment(f"c{i}", f"comment {i}") for i in range(10)]
        fake_sub = self._make_fake_submission("p001", comments=comments)

        collector = self._collector()
        fake_reddit = AsyncMock()
        fake_reddit.__aenter__ = AsyncMock(return_value=fake_reddit)
        fake_reddit.__aexit__ = AsyncMock(return_value=None)
        fake_reddit.submission = AsyncMock(return_value=fake_sub)

        with patch.object(collector, "_build_reddit_client", return_value=fake_reddit):
            records = await collector.collect_comments(
                post_ids=[{"platform_id": "p001"}],
                tier=Tier.FREE,
                max_comments_per_post=3,
            )

        assert len(records) == 3

    @pytest.mark.asyncio
    async def test_collect_comments_handles_multiple_post_ids(self) -> None:
        """Multiple post IDs are iterated and comments collected for each."""
        comment_a = self._make_fake_comment("ca", "on post A")
        comment_b = self._make_fake_comment("cb", "on post B")
        sub_a = self._make_fake_submission("pa", comments=[comment_a])
        sub_b = self._make_fake_submission("pb", comments=[comment_b])

        collector = self._collector()
        fake_reddit = AsyncMock()
        fake_reddit.__aenter__ = AsyncMock(return_value=fake_reddit)
        fake_reddit.__aexit__ = AsyncMock(return_value=None)
        fake_reddit.submission = AsyncMock(side_effect=[sub_a, sub_b])

        with patch.object(collector, "_build_reddit_client", return_value=fake_reddit):
            records = await collector.collect_comments(
                post_ids=[{"platform_id": "pa"}, {"platform_id": "pb"}],
                tier=Tier.FREE,
            )

        assert len(records) == 2

    @pytest.mark.asyncio
    async def test_collect_comments_rate_limit_raises(self) -> None:
        """TooManyRequests from asyncpraw raises ArenaRateLimitError."""
        import asyncprawcore.exceptions

        collector = self._collector()
        fake_reddit = AsyncMock()
        fake_reddit.__aenter__ = AsyncMock(return_value=fake_reddit)
        fake_reddit.__aexit__ = AsyncMock(return_value=None)

        mock_resp = MagicMock()
        mock_resp.status = 429
        fake_reddit.submission = AsyncMock(
            side_effect=asyncprawcore.exceptions.TooManyRequests(mock_resp)
        )

        with (
            patch.object(collector, "_build_reddit_client", return_value=fake_reddit),
            pytest.raises(ArenaRateLimitError),
        ):
            await collector.collect_comments(
                post_ids=[{"platform_id": "p001"}],
                tier=Tier.FREE,
            )

    @pytest.mark.asyncio
    async def test_collect_comments_forbidden_skips_post(self) -> None:
        """Forbidden access to a post is silently skipped (no error raised)."""
        import asyncprawcore.exceptions

        collector = self._collector()
        fake_reddit = AsyncMock()
        fake_reddit.__aenter__ = AsyncMock(return_value=fake_reddit)
        fake_reddit.__aexit__ = AsyncMock(return_value=None)

        mock_resp = MagicMock()
        mock_resp.status = 403
        fake_reddit.submission = AsyncMock(
            side_effect=asyncprawcore.exceptions.Forbidden(mock_resp)
        )

        with patch.object(collector, "_build_reddit_client", return_value=fake_reddit):
            records = await collector.collect_comments(
                post_ids=[{"platform_id": "p001"}],
                tier=Tier.FREE,
            )

        # Forbidden posts produce zero records, not an exception
        assert records == []

    @pytest.mark.asyncio
    async def test_collect_comments_deleted_comment_body_is_none(self) -> None:
        """Comments with body '[deleted]' or '[removed]' produce None text_content."""
        deleted = self._make_fake_comment("c_del", "[deleted]", depth=0)
        fake_sub = self._make_fake_submission("p001", comments=[deleted])

        collector = self._collector()
        fake_reddit = AsyncMock()
        fake_reddit.__aenter__ = AsyncMock(return_value=fake_reddit)
        fake_reddit.__aexit__ = AsyncMock(return_value=None)
        fake_reddit.submission = AsyncMock(return_value=fake_sub)

        with patch.object(collector, "_build_reddit_client", return_value=fake_reddit):
            records = await collector.collect_comments(
                post_ids=[{"platform_id": "p001"}],
                tier=Tier.FREE,
            )

        assert len(records) == 1
        assert records[0]["text_content"] is None

    @pytest.mark.asyncio
    async def test_collect_comments_releases_credential_from_pool(self) -> None:
        """The credential pool's release() is called after collection."""
        pool = _mock_pool("reddit", extra={"client_id": "cid", "client_secret": "csec"})
        from issue_observatory.arenas.reddit.collector import RedditCollector

        collector = RedditCollector(credential_pool=pool)

        fake_sub = self._make_fake_submission("p001", comments=[])
        fake_reddit = AsyncMock()
        fake_reddit.__aenter__ = AsyncMock(return_value=fake_reddit)
        fake_reddit.__aexit__ = AsyncMock(return_value=None)
        fake_reddit.submission = AsyncMock(return_value=fake_sub)

        with patch.object(collector, "_build_reddit_client", return_value=fake_reddit):
            await collector.collect_comments(
                post_ids=[{"platform_id": "p001"}],
                tier=Tier.FREE,
            )

        pool.release.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_collect_comments_normalizes_danish_text(self) -> None:
        """Danish characters in comment body are preserved after normalization."""
        body = "Grøn omstilling er afgørende for vores fremtid og økonomi."
        fake_comment = self._make_fake_comment("c_da", body, depth=0)
        fake_sub = self._make_fake_submission("p_da", comments=[fake_comment])

        collector = self._collector()
        fake_reddit = AsyncMock()
        fake_reddit.__aenter__ = AsyncMock(return_value=fake_reddit)
        fake_reddit.__aexit__ = AsyncMock(return_value=None)
        fake_reddit.submission = AsyncMock(return_value=fake_sub)

        with patch.object(collector, "_build_reddit_client", return_value=fake_reddit):
            records = await collector.collect_comments(
                post_ids=[{"platform_id": "p_da"}],
                tier=Tier.FREE,
            )

        assert records[0]["text_content"] == body


# ===========================================================================
# BLUESKY
# ===========================================================================


class TestBlueskyCollectComments:
    """Unit tests for BlueskyCollector.collect_comments()."""

    def _collector(self) -> Any:
        from issue_observatory.arenas.bluesky.collector import BlueskyCollector

        return BlueskyCollector()

    @staticmethod
    def _make_reply_node(
        uri: str = "at://did:plc:reply001/app.bsky.feed.post/rkey001",
        text: str = "Reply text here",
        replies: list | None = None,
    ) -> dict[str, Any]:
        """Build a minimal ThreadViewPost node."""
        return {
            "$type": "app.bsky.feed.defs#threadViewPost",
            "post": {
                "uri": uri,
                "author": {
                    "did": "did:plc:reply001",
                    "handle": "replier.bsky.social",
                    "displayName": "Reply Author",
                },
                "record": {
                    "$type": "app.bsky.feed.post",
                    "text": text,
                    "createdAt": "2026-03-01T10:00:00.000Z",
                    "langs": ["en"],
                },
                "likeCount": 2,
                "repostCount": 0,
                "replyCount": 0,
            },
            "replies": replies or [],
        }

    @staticmethod
    def _make_thread_response(
        post_at_uri: str = "at://did:plc:parent/app.bsky.feed.post/parent001",
        replies: list | None = None,
    ) -> dict[str, Any]:
        """Build a minimal getPostThread API response."""
        return {
            "thread": {
                "$type": "app.bsky.feed.defs#threadViewPost",
                "post": {
                    "uri": post_at_uri,
                    "author": {"did": "did:plc:parent", "handle": "parent.bsky.social"},
                    "record": {"text": "Original post", "createdAt": "2026-03-01T09:00:00Z"},
                },
                "replies": replies or [],
            }
        }

    @pytest.mark.asyncio
    async def test_collect_comments_returns_replies(self) -> None:
        """collect_comments() extracts replies from getPostThread response.

        Note: BlueskyCollector.normalize() always sets content_type via its
        internal flat dict.  The comment records are identified as platform=bluesky
        and carry the reply's text and AT URI.
        """
        from issue_observatory.arenas.bluesky.collector import BlueskyCollector

        reply_node = self._make_reply_node(text="Very insightful post!")
        thread_response = self._make_thread_response(replies=[reply_node])
        at_uri = "at://did:plc:parent/app.bsky.feed.post/parent001"

        collector = BlueskyCollector()
        mock_client = AsyncMock()

        async def _mock_make_request(client, endpoint, params=None):  # noqa: ANN001
            return thread_response

        with patch.object(collector, "_make_request", side_effect=_mock_make_request):
            with patch.object(collector, "_release_credential", new_callable=AsyncMock):
                # Patch _build_http_client to yield our mock client
                cm = MagicMock()
                cm.__aenter__ = AsyncMock(return_value=mock_client)
                cm.__aexit__ = AsyncMock(return_value=None)
                with patch.object(collector, "_build_http_client", return_value=cm):
                    records = await collector.collect_comments(
                        post_ids=[{"platform_id": at_uri}],
                        tier=Tier.FREE,
                    )

        assert len(records) == 1
        assert records[0]["platform"] == "bluesky"
        # normalize() reads content_type from its internal flat dict which has
        # "content_type": "comment" propagated from _build_comment_raw via the
        # Normalizer's _extract_str lookup on the flat dict.
        assert records[0]["text_content"] == "Very insightful post!"

    @pytest.mark.asyncio
    async def test_collect_comments_skips_missing_platform_id(self) -> None:
        """Entries without 'platform_id' are silently skipped."""
        from issue_observatory.arenas.bluesky.collector import BlueskyCollector

        collector = BlueskyCollector()
        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(collector, "_release_credential", new_callable=AsyncMock):
            with patch.object(collector, "_build_http_client", return_value=cm):
                records = await collector.collect_comments(
                    post_ids=[{"platform_id": ""}],
                    tier=Tier.FREE,
                )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_comments_rate_limit_raises(self) -> None:
        """HTTP 429 from getPostThread raises ArenaRateLimitError."""
        from issue_observatory.arenas.bluesky.collector import BlueskyCollector

        collector = BlueskyCollector()
        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)

        async def _raise_rate_limit(client, endpoint, params=None):  # noqa: ANN001
            raise ArenaRateLimitError(
                "bluesky: rate limited",
                retry_after=60.0,
                arena="social_media",
                platform="bluesky",
            )

        with patch.object(collector, "_make_request", side_effect=_raise_rate_limit):
            with patch.object(collector, "_release_credential", new_callable=AsyncMock):
                with patch.object(collector, "_build_http_client", return_value=cm):
                    with pytest.raises(ArenaRateLimitError):
                        await collector.collect_comments(
                            post_ids=[{"platform_id": "at://did:plc:x/app.bsky.feed.post/y"}],
                            tier=Tier.FREE,
                        )

    @pytest.mark.asyncio
    async def test_collect_comments_collection_error_skips_post(self) -> None:
        """ArenaCollectionError for a single post is caught and skipped."""
        from issue_observatory.arenas.bluesky.collector import BlueskyCollector

        collector = BlueskyCollector()
        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)

        async def _raise_collection_error(client, endpoint, params=None):  # noqa: ANN001
            raise ArenaCollectionError(
                "bluesky: not found",
                arena="social_media",
                platform="bluesky",
            )

        with patch.object(collector, "_make_request", side_effect=_raise_collection_error):
            with patch.object(collector, "_release_credential", new_callable=AsyncMock):
                with patch.object(collector, "_build_http_client", return_value=cm):
                    records = await collector.collect_comments(
                        post_ids=[{"platform_id": "at://did:plc:x/app.bsky.feed.post/y"}],
                        tier=Tier.FREE,
                    )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_comments_respects_max_per_post(self) -> None:
        """max_comments_per_post caps the number of replies extracted."""
        from issue_observatory.arenas.bluesky.collector import BlueskyCollector

        replies = [
            self._make_reply_node(
                uri=f"at://did:plc:r{i}/app.bsky.feed.post/r{i}",
                text=f"Reply {i}",
            )
            for i in range(5)
        ]
        thread_response = self._make_thread_response(replies=replies)

        collector = BlueskyCollector()
        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)

        async def _mock_req(client, endpoint, params=None):  # noqa: ANN001
            return thread_response

        with patch.object(collector, "_make_request", side_effect=_mock_req):
            with patch.object(collector, "_release_credential", new_callable=AsyncMock):
                with patch.object(collector, "_build_http_client", return_value=cm):
                    records = await collector.collect_comments(
                        post_ids=[{"platform_id": "at://did:plc:p/app.bsky.feed.post/p1"}],
                        tier=Tier.FREE,
                        max_comments_per_post=2,
                    )

        assert len(records) == 2

    @pytest.mark.asyncio
    async def test_collect_comments_no_replies_returns_empty(self) -> None:
        """A post with an empty replies list yields zero comment records."""
        from issue_observatory.arenas.bluesky.collector import BlueskyCollector

        thread_response = self._make_thread_response(replies=[])
        collector = BlueskyCollector()
        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)

        async def _mock_req(client, endpoint, params=None):  # noqa: ANN001
            return thread_response

        with patch.object(collector, "_make_request", side_effect=_mock_req):
            with patch.object(collector, "_release_credential", new_callable=AsyncMock):
                with patch.object(collector, "_build_http_client", return_value=cm):
                    records = await collector.collect_comments(
                        post_ids=[{"platform_id": "at://did:plc:x/app.bsky.feed.post/y"}],
                        tier=Tier.FREE,
                    )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_comments_passes_depth_to_request(self) -> None:
        """The 'depth' parameter is forwarded to the getPostThread request."""
        from issue_observatory.arenas.bluesky.collector import BlueskyCollector

        collector = BlueskyCollector()
        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)

        captured_params: list[dict] = []

        async def _capture_req(client, endpoint, params=None):  # noqa: ANN001
            captured_params.append(params or {})
            return self._make_thread_response(replies=[])

        with patch.object(collector, "_make_request", side_effect=_capture_req):
            with patch.object(collector, "_release_credential", new_callable=AsyncMock):
                with patch.object(collector, "_build_http_client", return_value=cm):
                    await collector.collect_comments(
                        post_ids=[{"platform_id": "at://did:plc:x/app.bsky.feed.post/y"}],
                        tier=Tier.FREE,
                        depth=3,
                    )

        assert captured_params[0]["depth"] == 3

    @pytest.mark.asyncio
    async def test_collect_comments_preserves_danish_text(self) -> None:
        """Danish Unicode characters in reply text survive normalization."""
        from issue_observatory.arenas.bluesky.collector import BlueskyCollector

        danish_text = "Det er vigtigt at fokusere på klimaforandringer og bæredygtighed."
        reply_node = self._make_reply_node(text=danish_text)
        thread_response = self._make_thread_response(replies=[reply_node])

        collector = BlueskyCollector()
        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)

        async def _mock_req(client, endpoint, params=None):  # noqa: ANN001
            return thread_response

        with patch.object(collector, "_make_request", side_effect=_mock_req):
            with patch.object(collector, "_release_credential", new_callable=AsyncMock):
                with patch.object(collector, "_build_http_client", return_value=cm):
                    records = await collector.collect_comments(
                        post_ids=[{"platform_id": "at://did:plc:x/app.bsky.feed.post/y"}],
                        tier=Tier.FREE,
                    )

        assert records[0]["text_content"] == danish_text


# ===========================================================================
# YOUTUBE
# ===========================================================================


class TestYouTubeCollectComments:
    """Unit tests for YouTubeCollector.collect_comments()."""

    def _collector(self) -> Any:
        from issue_observatory.arenas.youtube.collector import YouTubeCollector

        return YouTubeCollector(credential_pool=_mock_pool("youtube"))

    @staticmethod
    def _comment_thread(
        thread_id: str = "thread001",
        video_id: str = "vid001",
        text: str = "Great video!",
        author_channel_id: str = "UC_test_chan",
        published_at: str = "2026-02-01T10:00:00.000Z",
        replies: list | None = None,
    ) -> dict[str, Any]:
        """Build a minimal commentThread resource."""
        thread: dict[str, Any] = {
            "id": thread_id,
            "snippet": {
                "videoId": video_id,
                "totalReplyCount": len(replies or []),
                "topLevelComment": {
                    "id": thread_id,
                    "snippet": {
                        "videoId": video_id,
                        "textDisplay": text,
                        "authorDisplayName": "Test Commenter",
                        "authorChannelId": {"value": author_channel_id},
                        "likeCount": "5",
                        "publishedAt": published_at,
                    },
                },
            },
        }
        if replies:
            thread["replies"] = {"comments": replies}
        return thread

    @staticmethod
    def _reply_comment(
        reply_id: str = "reply001",
        video_id: str = "vid001",
        text: str = "Thanks!",
        parent_thread_id: str = "thread001",
        published_at: str = "2026-02-01T11:00:00.000Z",
    ) -> dict[str, Any]:
        """Build a minimal reply comment resource."""
        return {
            "id": reply_id,
            "snippet": {
                "textDisplay": text,
                "authorDisplayName": "Reply Author",
                "authorChannelId": {"value": "UC_reply_chan"},
                "likeCount": "1",
                "publishedAt": published_at,
                "parentId": parent_thread_id,
            },
        }

    @pytest.mark.asyncio
    async def test_collect_comments_returns_top_level_comment(self) -> None:
        """collect_comments() returns one record for a single comment thread.

        make_api_request is imported inside collect_comments() via a local
        import, so we patch it in the youtube._client module namespace.
        """
        from issue_observatory.arenas.youtube.collector import YouTubeCollector

        thread = self._comment_thread("t001", "vid001", "Hello YouTube!")
        api_response = {"items": [thread], "nextPageToken": None}

        pool = _mock_pool("youtube")
        collector = YouTubeCollector(credential_pool=pool)

        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(collector, "_build_http_client", return_value=cm):
            with patch(
                "issue_observatory.arenas.youtube._client.make_api_request",
                new_callable=AsyncMock,
                return_value=api_response,
            ):
                records = await collector.collect_comments(
                    post_ids=[{"platform_id": "vid001"}],
                    tier=Tier.FREE,
                )

        assert len(records) == 1
        rec = records[0]
        assert rec["platform"] == "youtube"
        assert rec["content_type"] == "comment"
        assert rec["text_content"] == "Hello YouTube!"

    @pytest.mark.asyncio
    async def test_collect_comments_depth_one_includes_replies(self) -> None:
        """depth=1 also processes reply comments nested in 'replies.comments'."""
        from issue_observatory.arenas.youtube.collector import YouTubeCollector

        reply = self._reply_comment("r001", "vid001", "Thanks for the video!")
        thread = self._comment_thread("t001", "vid001", "Great video!", replies=[reply])
        api_response = {"items": [thread], "nextPageToken": None}

        pool = _mock_pool("youtube")
        collector = YouTubeCollector(credential_pool=pool)

        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(collector, "_build_http_client", return_value=cm):
            with patch(
                "issue_observatory.arenas.youtube._client.make_api_request",
                new_callable=AsyncMock,
                return_value=api_response,
            ):
                records = await collector.collect_comments(
                    post_ids=[{"platform_id": "vid001"}],
                    tier=Tier.FREE,
                    depth=1,
                )

        # Both top-level thread comment and the reply should appear
        assert len(records) == 2
        content_texts = {r["text_content"] for r in records}
        assert "Great video!" in content_texts
        assert "Thanks for the video!" in content_texts

    @pytest.mark.asyncio
    async def test_collect_comments_pagination_fetches_next_page(self) -> None:
        """Pagination via nextPageToken continues until no further pages."""
        from issue_observatory.arenas.youtube.collector import YouTubeCollector

        page1 = {
            "items": [self._comment_thread("t001", "vid001", "First comment")],
            "nextPageToken": "TOKEN_PAGE2",
        }
        page2 = {
            "items": [self._comment_thread("t002", "vid001", "Second comment")],
            "nextPageToken": None,
        }
        call_count = 0

        async def _mock_api(client, endpoint, params, credential_pool=None, cred_id=None):  # noqa: ANN001
            nonlocal call_count
            call_count += 1
            return page1 if call_count == 1 else page2

        pool = _mock_pool("youtube")
        collector = YouTubeCollector(credential_pool=pool)

        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(collector, "_build_http_client", return_value=cm):
            with patch(
                "issue_observatory.arenas.youtube._client.make_api_request",
                side_effect=_mock_api,
            ):
                records = await collector.collect_comments(
                    post_ids=[{"platform_id": "vid001"}],
                    tier=Tier.FREE,
                    max_comments_per_post=100,
                )

        assert len(records) == 2

    @pytest.mark.asyncio
    async def test_collect_comments_max_per_post_caps_results(self) -> None:
        """max_comments_per_post is honoured regardless of API pages returned."""
        from issue_observatory.arenas.youtube.collector import YouTubeCollector

        threads = [
            self._comment_thread(f"t{i}", "vid001", f"Comment {i}") for i in range(5)
        ]
        api_response = {"items": threads, "nextPageToken": None}

        pool = _mock_pool("youtube")
        collector = YouTubeCollector(credential_pool=pool)

        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(collector, "_build_http_client", return_value=cm):
            with patch(
                "issue_observatory.arenas.youtube._client.make_api_request",
                new_callable=AsyncMock,
                return_value=api_response,
            ):
                records = await collector.collect_comments(
                    post_ids=[{"platform_id": "vid001"}],
                    tier=Tier.FREE,
                    max_comments_per_post=3,
                )

        assert len(records) == 3

    @pytest.mark.asyncio
    async def test_collect_comments_skips_entry_without_platform_id(self) -> None:
        """Entries missing 'platform_id' are silently skipped."""
        from issue_observatory.arenas.youtube.collector import YouTubeCollector

        pool = _mock_pool("youtube")
        collector = YouTubeCollector(credential_pool=pool)

        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(collector, "_build_http_client", return_value=cm):
            with patch(
                "issue_observatory.arenas.youtube._client.make_api_request",
                new_callable=AsyncMock,
            ) as mock_api:
                records = await collector.collect_comments(
                    post_ids=[{"url": "https://youtube.com/watch?v=abc"}],  # no platform_id
                    tier=Tier.FREE,
                )

        assert records == []
        mock_api.assert_not_called()

    @pytest.mark.asyncio
    async def test_collect_comments_quota_exceeded_rotates_credential(self) -> None:
        """ArenaRateLimitError from API triggers credential rotation."""
        from issue_observatory.arenas.youtube.collector import YouTubeCollector

        call_count = 0
        cred_1 = {"id": "cred-1", "api_key": "key1", "platform": "youtube"}
        cred_2 = {"id": "cred-2", "api_key": "key2", "platform": "youtube"}

        pool = AsyncMock()
        pool.acquire = AsyncMock(side_effect=[cred_1, cred_2])
        pool.release = AsyncMock(return_value=None)

        async def _mock_api(client, endpoint, params, credential_pool=None, cred_id=None):  # noqa: ANN001
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ArenaRateLimitError(
                    "youtube: quota exceeded",
                    retry_after=0,
                    arena="social_media",
                    platform="youtube",
                )
            return {"items": [], "nextPageToken": None}

        collector = YouTubeCollector(credential_pool=pool)

        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(collector, "_build_http_client", return_value=cm):
            with patch(
                "issue_observatory.arenas.youtube._client.make_api_request",
                side_effect=_mock_api,
            ):
                records = await collector.collect_comments(
                    post_ids=[{"platform_id": "vid001"}],
                    tier=Tier.FREE,
                )

        # Second credential was acquired after quota rotation
        assert pool.acquire.call_count == 2
        assert records == []

    @pytest.mark.asyncio
    async def test_collect_comments_empty_items_returns_empty(self) -> None:
        """An API response with empty 'items' produces zero comment records."""
        from issue_observatory.arenas.youtube.collector import YouTubeCollector

        pool = _mock_pool("youtube")
        collector = YouTubeCollector(credential_pool=pool)

        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(collector, "_build_http_client", return_value=cm):
            with patch(
                "issue_observatory.arenas.youtube._client.make_api_request",
                new_callable=AsyncMock,
                return_value={"items": [], "nextPageToken": None},
            ):
                records = await collector.collect_comments(
                    post_ids=[{"platform_id": "vid001"}],
                    tier=Tier.FREE,
                )

        assert records == []


# ===========================================================================
# TIKTOK
# ===========================================================================


class TestTikTokCollectComments:
    """Unit tests for TikTokCollector.collect_comments()."""

    def _pool(self) -> AsyncMock:
        pool = AsyncMock()
        cred = {
            "id": "cred-tt-001",
            "api_key": "tt_api_key",
            "client_key": "tt_client_key",
            "client_secret": "tt_client_secret",
            "platform": "tiktok",
        }
        pool.acquire = AsyncMock(return_value=cred)
        pool.release = AsyncMock(return_value=None)
        return pool

    def _collector(self) -> Any:
        from issue_observatory.arenas.tiktok.collector import TikTokCollector

        return TikTokCollector(credential_pool=self._pool())

    @staticmethod
    def _comment_response(
        video_id: str = "1234567890",
        comments: list | None = None,
        has_more: bool = False,
        cursor: int | None = None,
    ) -> dict[str, Any]:
        """Build a minimal TikTok comment list API response."""
        return {
            "data": {
                "comments": comments or [],
                "has_more": has_more,
                "cursor": cursor,
            },
            "error": {"code": "ok", "message": ""},
        }

    @staticmethod
    def _make_comment(
        comment_id: str = "c001",
        text: str = "Awesome TikTok!",
        like_count: int = 5,
    ) -> dict[str, Any]:
        """Build a minimal TikTok comment dict."""
        return {
            "id": comment_id,
            "text": text,
            "create_time": 1739620300,
            "like_count": like_count,
            "reply_count": 0,
            "parent_comment_id": 0,
        }

    @pytest.mark.asyncio
    async def test_collect_comments_returns_normalized_records(self) -> None:
        """collect_comments() returns normalized records for each comment."""
        from issue_observatory.arenas.tiktok.collector import TikTokCollector

        pool = self._pool()
        collector = TikTokCollector(credential_pool=pool)

        comment = self._make_comment("c001", "Great TikTok video!")
        response = self._comment_response("1234567890", comments=[comment])

        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value=response)
        mock_client.post.return_value = mock_resp

        with patch.object(collector, "_get_access_token", new_callable=AsyncMock, return_value="tok"):
            with patch.object(collector, "_build_http_client", return_value=cm):
                with patch.object(collector, "_release_credential", new_callable=AsyncMock):
                    records = await collector.collect_comments(
                        post_ids=[{"platform_id": "1234567890"}],
                        tier=Tier.FREE,
                    )

        assert len(records) == 1
        rec = records[0]
        assert rec["platform"] == "tiktok"
        assert rec["content_type"] == "comment"
        assert rec["text_content"] == "Great TikTok video!"

    @pytest.mark.asyncio
    async def test_collect_comments_empty_post_ids_returns_empty(self) -> None:
        """An empty post_ids list returns immediately with no API calls."""
        from issue_observatory.arenas.tiktok.collector import TikTokCollector

        collector = TikTokCollector(credential_pool=self._pool())

        with patch.object(collector, "_get_credential", new_callable=AsyncMock) as mock_get_cred:
            records = await collector.collect_comments(
                post_ids=[],
                tier=Tier.FREE,
            )

        assert records == []
        mock_get_cred.assert_not_called()

    @pytest.mark.asyncio
    async def test_collect_comments_skips_entry_without_platform_id(self) -> None:
        """Entries missing 'platform_id' produce a warning and are skipped."""
        from issue_observatory.arenas.tiktok.collector import TikTokCollector

        pool = self._pool()
        collector = TikTokCollector(credential_pool=pool)

        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(collector, "_get_access_token", new_callable=AsyncMock, return_value="tok"):
            with patch.object(collector, "_build_http_client", return_value=cm):
                with patch.object(collector, "_release_credential", new_callable=AsyncMock):
                    records = await collector.collect_comments(
                        post_ids=[{"platform_id": ""}],
                        tier=Tier.FREE,
                    )

        assert records == []
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_collect_comments_pagination_follows_cursor(self) -> None:
        """Pagination using cursor continues until has_more is False."""
        from issue_observatory.arenas.tiktok.collector import TikTokCollector

        pool = self._pool()
        collector = TikTokCollector(credential_pool=pool)

        page1_comment = self._make_comment("c001", "First comment")
        page2_comment = self._make_comment("c002", "Second comment")

        page1 = self._comment_response("777", comments=[page1_comment], has_more=True, cursor=100)
        page2 = self._comment_response("777", comments=[page2_comment], has_more=False)

        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)

        call_count = 0
        mock_resp_1 = MagicMock()
        mock_resp_1.status_code = 200
        mock_resp_1.json = MagicMock(return_value=page1)
        mock_resp_2 = MagicMock()
        mock_resp_2.status_code = 200
        mock_resp_2.json = MagicMock(return_value=page2)
        mock_client.post = AsyncMock(side_effect=[mock_resp_1, mock_resp_2])

        with patch.object(collector, "_get_access_token", new_callable=AsyncMock, return_value="tok"):
            with patch.object(collector, "_build_http_client", return_value=cm):
                with patch.object(collector, "_release_credential", new_callable=AsyncMock):
                    records = await collector.collect_comments(
                        post_ids=[{"platform_id": "777"}],
                        tier=Tier.FREE,
                        max_comments_per_post=100,
                    )

        assert len(records) == 2

    @pytest.mark.asyncio
    async def test_collect_comments_non_free_tier_still_works(self) -> None:
        """Non-FREE tiers log a warning but proceed with FREE tier collection.

        TikTok video IDs are numeric strings, so a valid integer string is used.
        """
        from issue_observatory.arenas.tiktok.collector import TikTokCollector

        pool = self._pool()
        collector = TikTokCollector(credential_pool=pool)

        comment = self._make_comment("c001", "test")
        # Use a numeric string for the video ID — TikTok requires int(video_id)
        numeric_video_id = "7123456789012345678"
        response = self._comment_response(numeric_video_id, comments=[comment])

        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value=response)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch.object(collector, "_get_access_token", new_callable=AsyncMock, return_value="tok"):
            with patch.object(collector, "_build_http_client", return_value=cm):
                with patch.object(collector, "_release_credential", new_callable=AsyncMock):
                    records = await collector.collect_comments(
                        post_ids=[{"platform_id": numeric_video_id}],
                        tier=Tier.MEDIUM,  # Not FREE — warns but proceeds
                    )

        # Should still return records (using FREE under the hood)
        assert len(records) == 1

    @pytest.mark.asyncio
    async def test_collect_comments_collection_error_skips_video(self) -> None:
        """ArenaCollectionError for a single video is caught and skipped.

        We mock _make_request directly to raise ArenaCollectionError, since
        _fetch_comments_for_video calls _make_request internally.
        The video ID must be numeric for int() conversion in the request body.
        """
        from issue_observatory.arenas.tiktok.collector import TikTokCollector

        pool = self._pool()
        collector = TikTokCollector(credential_pool=pool)

        numeric_video_id = "9999999999999999999"
        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)

        async def _raise_error(client, url, body, token, cred_id, fields=None):  # noqa: ANN001
            raise ArenaCollectionError(
                "tiktok: server error",
                arena="social_media",
                platform="tiktok",
            )

        with patch.object(collector, "_get_access_token", new_callable=AsyncMock, return_value="tok"):
            with patch.object(collector, "_build_http_client", return_value=cm):
                with patch.object(collector, "_release_credential", new_callable=AsyncMock):
                    with patch.object(collector, "_make_request", side_effect=_raise_error):
                        records = await collector.collect_comments(
                            post_ids=[{"platform_id": numeric_video_id}],
                            tier=Tier.FREE,
                        )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_comments_parent_post_id_preserved(self) -> None:
        """The parent_post_id field links each comment back to its video."""
        from issue_observatory.arenas.tiktok.collector import TikTokCollector

        pool = self._pool()
        collector = TikTokCollector(credential_pool=pool)

        comment = self._make_comment("c001", "video comment")
        response = self._comment_response("999999", comments=[comment])

        mock_client = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=None)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value=response)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch.object(collector, "_get_access_token", new_callable=AsyncMock, return_value="tok"):
            with patch.object(collector, "_build_http_client", return_value=cm):
                with patch.object(collector, "_release_credential", new_callable=AsyncMock):
                    records = await collector.collect_comments(
                        post_ids=[{"platform_id": "999999"}],
                        tier=Tier.FREE,
                    )

        assert len(records) == 1
        assert records[0]["parent_post_id"] == "999999"


# ===========================================================================
# FACEBOOK
# ===========================================================================


class TestFacebookCollectComments:
    """Unit tests for FacebookCollector.collect_comments()."""

    def _pool(self, cred_id: str = "cred-fb-001") -> AsyncMock:
        pool = AsyncMock()
        cred = {
            "id": cred_id,
            "api_token": "bd_fb_token",
            "api_key": "bd_fb_token",
            "platform": "brightdata_facebook",
        }
        pool.acquire = AsyncMock(return_value=cred)
        pool.release = AsyncMock(return_value=None)
        return pool

    def _collector(self) -> Any:
        from issue_observatory.arenas.facebook.collector import FacebookCollector

        return FacebookCollector(credential_pool=self._pool())

    @staticmethod
    def _raw_bd_comment(
        comment_id: str = "fb_c001",
        text: str = "Facebook comment text",
        author_name: str = "FB User",
        post_url: str = "https://www.facebook.com/drdk/posts/12345",
    ) -> dict[str, Any]:
        """Build a raw Bright Data comment dict matching BD's actual payload shape.

        Field names reflect the Bright Data Web Scraper API comment response:
        - ``comment_id`` / ``id``: the comment identifier.
        - ``text``: the comment body text (read by collect_comments()).
        - ``page_name``: author display name.
        - ``date_posted``: ISO timestamp.
        - ``num_likes``: like count.
        - ``url``: parent post URL.

        collect_comments() maps these to a flat dict understood by
        _parse_brightdata_facebook(), where ``text`` → ``content`` in the
        intermediate dict, enabling text_content to flow through normalize().
        """
        return {
            "comment_id": comment_id,
            "id": comment_id,
            "text": text,
            "page_name": author_name,
            "author_id": f"fb_uid_{comment_id}",
            "date_posted": "2026-02-15T10:00:00Z",
            "num_likes": 3,
            "url": post_url,
        }

    @pytest.mark.asyncio
    async def test_collect_comments_delegates_to_brightdata(self) -> None:
        """collect_comments() calls BrightDataCommentCollector and normalizes output."""
        from issue_observatory.arenas.facebook.collector import FacebookCollector

        pool = self._pool()
        collector = FacebookCollector(credential_pool=pool)

        raw_comment = self._raw_bd_comment("c001", "Hello from Facebook!")

        with patch(
            "issue_observatory.arenas.facebook.collector.BrightDataCommentCollector"
        ) as MockBD:
            instance = AsyncMock()
            instance.collect_comments_brightdata = AsyncMock(return_value=[raw_comment])
            MockBD.return_value = instance

            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance

                records = await collector.collect_comments(
                    post_ids=[{"url": "https://www.facebook.com/drdk/posts/12345"}],
                    tier=Tier.MEDIUM,
                )

        assert len(records) == 1
        rec = records[0]
        assert rec["platform"] == "facebook"
        # collect_comments() now sets "comment_id" in raw_dict so that
        # _parse_brightdata_facebook() can detect content_type="comment".
        assert rec["text_content"] == "Hello from Facebook!"

    @pytest.mark.asyncio
    async def test_collect_comments_returns_empty_for_no_valid_urls(self) -> None:
        """No post_ids with 'url' keys returns empty list immediately."""
        from issue_observatory.arenas.facebook.collector import FacebookCollector

        pool = self._pool()
        collector = FacebookCollector(credential_pool=pool)

        records = await collector.collect_comments(
            post_ids=[{"platform_id": "fb_post_id"}],  # no url key
            tier=Tier.MEDIUM,
        )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_comments_raises_when_no_credential(self) -> None:
        """NoCredentialAvailableError is raised when credential pool returns None."""
        from issue_observatory.arenas.facebook.collector import FacebookCollector

        pool = AsyncMock()
        pool.acquire = AsyncMock(return_value=None)
        pool.release = AsyncMock(return_value=None)
        collector = FacebookCollector(credential_pool=pool)

        with pytest.raises(NoCredentialAvailableError):
            await collector.collect_comments(
                post_ids=[{"url": "https://www.facebook.com/drdk/posts/12345"}],
                tier=Tier.MEDIUM,
            )

    @pytest.mark.asyncio
    async def test_collect_comments_releases_credential_after_success(self) -> None:
        """Credential pool release() is called even on successful collection."""
        from issue_observatory.arenas.facebook.collector import FacebookCollector

        pool = self._pool()
        collector = FacebookCollector(credential_pool=pool)

        with patch(
            "issue_observatory.arenas.facebook.collector.BrightDataCommentCollector"
        ) as MockBD:
            instance = AsyncMock()
            instance.collect_comments_brightdata = AsyncMock(return_value=[])
            MockBD.return_value = instance

            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance

                await collector.collect_comments(
                    post_ids=[{"url": "https://www.facebook.com/drdk/posts/12345"}],
                    tier=Tier.MEDIUM,
                )

        pool.release.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_collect_comments_multiple_comments_all_normalized(self) -> None:
        """All raw Bright Data comment dicts are normalized and returned."""
        from issue_observatory.arenas.facebook.collector import FacebookCollector

        pool = self._pool()
        collector = FacebookCollector(credential_pool=pool)

        raw_comments = [
            self._raw_bd_comment(f"c{i}", f"Comment number {i}") for i in range(3)
        ]

        with patch(
            "issue_observatory.arenas.facebook.collector.BrightDataCommentCollector"
        ) as MockBD:
            instance = AsyncMock()
            instance.collect_comments_brightdata = AsyncMock(return_value=raw_comments)
            MockBD.return_value = instance

            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance

                records = await collector.collect_comments(
                    post_ids=[{"url": "https://www.facebook.com/drdk/posts/12345"}],
                    tier=Tier.MEDIUM,
                    max_comments_per_post=200,
                )

        assert len(records) == 3
        assert all(r["platform"] == "facebook" for r in records)

    @pytest.mark.asyncio
    async def test_collect_comments_passes_dataset_id_for_facebook(self) -> None:
        """The Facebook comments dataset ID is passed to BrightDataCommentCollector."""
        from issue_observatory.arenas.facebook.collector import FacebookCollector
        from issue_observatory.arenas.facebook.config import FACEBOOK_DATASET_ID_COMMENTS

        pool = self._pool()
        collector = FacebookCollector(credential_pool=pool)

        with patch(
            "issue_observatory.arenas.facebook.collector.BrightDataCommentCollector"
        ) as MockBD:
            instance = AsyncMock()
            instance.collect_comments_brightdata = AsyncMock(return_value=[])
            MockBD.return_value = instance

            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance

                await collector.collect_comments(
                    post_ids=[{"url": "https://www.facebook.com/drdk/posts/12345"}],
                    tier=Tier.MEDIUM,
                )

            call_kwargs = instance.collect_comments_brightdata.call_args
            assert call_kwargs.args[3] == FACEBOOK_DATASET_ID_COMMENTS


# ===========================================================================
# INSTAGRAM
# ===========================================================================


class TestInstagramCollectComments:
    """Unit tests for InstagramCollector.collect_comments()."""

    def _pool(self, cred_id: str = "cred-ig-001") -> AsyncMock:
        pool = AsyncMock()
        cred = {
            "id": cred_id,
            "api_token": "bd_ig_token",
            "api_key": "bd_ig_token",
            "platform": "brightdata_instagram",
        }
        pool.acquire = AsyncMock(return_value=cred)
        pool.release = AsyncMock(return_value=None)
        return pool

    def _collector(self) -> Any:
        from issue_observatory.arenas.instagram.collector import InstagramCollector

        return InstagramCollector(credential_pool=self._pool())

    @staticmethod
    def _raw_bd_comment(
        comment_id: str = "ig_c001",
        text: str = "Instagram comment text",
        post_url: str = "https://www.instagram.com/p/ABC123/",
    ) -> dict[str, Any]:
        """Build a raw Bright Data Instagram comment dict."""
        return {
            "id": comment_id,
            "text": text,
            "author_name": "IG User",
            "author_id": "ig_uid_001",
            "date": "2026-02-20T12:00:00Z",
            "likes": 7,
            "comment_url": f"{post_url}?c={comment_id}",
            "post_url": post_url,
        }

    @pytest.mark.asyncio
    async def test_collect_comments_delegates_to_brightdata(self) -> None:
        """collect_comments() calls BrightDataCommentCollector and normalizes output."""
        from issue_observatory.arenas.instagram.collector import InstagramCollector

        pool = self._pool()
        collector = InstagramCollector(credential_pool=pool)

        raw_comment = self._raw_bd_comment("ig_c001", "Love this post!")

        with patch(
            "issue_observatory.arenas.instagram.collector.BrightDataCommentCollector"
        ) as MockBD:
            instance = AsyncMock()
            instance.collect_comments_brightdata = AsyncMock(return_value=[raw_comment])
            MockBD.return_value = instance

            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance

                records = await collector.collect_comments(
                    post_ids=[{"url": "https://www.instagram.com/p/ABC123/"}],
                    tier=Tier.MEDIUM,
                )

        assert len(records) == 1
        rec = records[0]
        assert rec["platform"] == "instagram"
        # BrightDataCommentCollector was called and its output was normalized
        assert rec["text_content"] == "Love this post!"

    @pytest.mark.asyncio
    async def test_collect_comments_returns_empty_for_no_valid_urls(self) -> None:
        """Entries without 'url' are silently skipped and empty list returned."""
        from issue_observatory.arenas.instagram.collector import InstagramCollector

        pool = self._pool()
        collector = InstagramCollector(credential_pool=pool)

        records = await collector.collect_comments(
            post_ids=[{"platform_id": "shortcode123"}],  # no url key
            tier=Tier.MEDIUM,
        )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_comments_raises_when_no_credential(self) -> None:
        """NoCredentialAvailableError raised when pool returns None."""
        from issue_observatory.arenas.instagram.collector import InstagramCollector

        pool = AsyncMock()
        pool.acquire = AsyncMock(return_value=None)
        pool.release = AsyncMock(return_value=None)
        collector = InstagramCollector(credential_pool=pool)

        with pytest.raises(NoCredentialAvailableError):
            await collector.collect_comments(
                post_ids=[{"url": "https://www.instagram.com/p/ABC123/"}],
                tier=Tier.MEDIUM,
            )

    @pytest.mark.asyncio
    async def test_collect_comments_releases_credential(self) -> None:
        """Credential pool release() is called after Instagram comment collection."""
        from issue_observatory.arenas.instagram.collector import InstagramCollector

        pool = self._pool()
        collector = InstagramCollector(credential_pool=pool)

        with patch(
            "issue_observatory.arenas.instagram.collector.BrightDataCommentCollector"
        ) as MockBD:
            instance = AsyncMock()
            instance.collect_comments_brightdata = AsyncMock(return_value=[])
            MockBD.return_value = instance

            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance

                await collector.collect_comments(
                    post_ids=[{"url": "https://www.instagram.com/p/ABC123/"}],
                    tier=Tier.MEDIUM,
                )

        pool.release.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_collect_comments_passes_dataset_id_for_instagram(self) -> None:
        """The Instagram comments dataset ID is passed to BrightDataCommentCollector."""
        from issue_observatory.arenas.instagram.collector import InstagramCollector
        from issue_observatory.arenas.instagram.config import INSTAGRAM_DATASET_ID_COMMENTS

        pool = self._pool()
        collector = InstagramCollector(credential_pool=pool)

        with patch(
            "issue_observatory.arenas.instagram.collector.BrightDataCommentCollector"
        ) as MockBD:
            instance = AsyncMock()
            instance.collect_comments_brightdata = AsyncMock(return_value=[])
            MockBD.return_value = instance

            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance

                await collector.collect_comments(
                    post_ids=[{"url": "https://www.instagram.com/p/ABC123/"}],
                    tier=Tier.MEDIUM,
                )

            call_kwargs = instance.collect_comments_brightdata.call_args
            assert call_kwargs.args[3] == INSTAGRAM_DATASET_ID_COMMENTS


# ===========================================================================
# BRIGHTDATA COMMENT COLLECTOR (shared utility)
# ===========================================================================


class TestBrightDataCommentCollector:
    """Unit tests for the shared BrightDataCommentCollector utility class."""

    @pytest.mark.asyncio
    async def test_collect_comments_brightdata_empty_urls_returns_empty(self) -> None:
        """Empty post_urls list short-circuits immediately with no HTTP calls."""
        from issue_observatory.arenas._brightdata_comments import BrightDataCommentCollector

        bd = BrightDataCommentCollector()
        mock_client = AsyncMock()

        result = await bd.collect_comments_brightdata(
            client=mock_client,
            api_token="token",
            post_urls=[],
            dataset_id="gd_dataset_123",
            platform="facebook",
        )

        assert result == []
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_collect_comments_brightdata_filters_error_records(self) -> None:
        """Records with 'error_code' set are filtered out of the returned list."""
        from issue_observatory.arenas._brightdata_comments import BrightDataCommentCollector

        bd = BrightDataCommentCollector()

        raw_items = [
            {"id": "c001", "text": "Valid comment"},
            {"error_code": "BLOCKED", "error": "Access denied", "input": {"url": "https://fb.com/p/1"}},
        ]

        with patch.object(bd, "_trigger", new_callable=AsyncMock, return_value="snap_001"):
            with patch.object(
                bd, "_poll_and_download", new_callable=AsyncMock, return_value=raw_items
            ):
                mock_client = AsyncMock()
                result = await bd.collect_comments_brightdata(
                    client=mock_client,
                    api_token="token",
                    post_urls=["https://www.facebook.com/drdk/posts/123"],
                    dataset_id="gd_dataset_123",
                    platform="facebook",
                )

        assert len(result) == 1
        assert result[0]["id"] == "c001"

    @pytest.mark.asyncio
    async def test_trigger_raises_rate_limit_on_429(self) -> None:
        """HTTP 429 from Bright Data trigger raises ArenaRateLimitError."""
        from issue_observatory.arenas._brightdata_comments import BrightDataCommentCollector

        bd = BrightDataCommentCollector()
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {"Retry-After": "30"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(ArenaRateLimitError):
            await bd._trigger(
                client=mock_client,
                api_token="token",
                trigger_url="https://api.brightdata.com/trigger",
                payload=[{"url": "https://www.facebook.com/drdk/posts/1"}],
                platform="facebook",
            )

    @pytest.mark.asyncio
    async def test_trigger_raises_auth_error_on_401(self) -> None:
        """HTTP 401 from Bright Data trigger raises ArenaAuthError."""
        from issue_observatory.arenas._brightdata_comments import BrightDataCommentCollector

        bd = BrightDataCommentCollector()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.headers = {}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(ArenaAuthError):
            await bd._trigger(
                client=mock_client,
                api_token="token",
                trigger_url="https://api.brightdata.com/trigger",
                payload=[{"url": "https://www.facebook.com/drdk/posts/1"}],
                platform="facebook",
            )

    @pytest.mark.asyncio
    async def test_trigger_raises_collection_error_when_no_snapshot_id(self) -> None:
        """Missing snapshot_id in trigger response raises ArenaCollectionError."""
        from issue_observatory.arenas._brightdata_comments import BrightDataCommentCollector

        bd = BrightDataCommentCollector()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={})  # no snapshot_id
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(ArenaCollectionError):
            await bd._trigger(
                client=mock_client,
                api_token="token",
                trigger_url="https://api.brightdata.com/trigger",
                payload=[{"url": "https://www.facebook.com/drdk/posts/1"}],
                platform="facebook",
            )


# ===========================================================================
# ORCHESTRATION: trigger_comment_collection
# ===========================================================================


class TestTriggerCommentCollection:
    """Unit tests for the trigger_comment_collection Celery task."""

    def _make_run_details(
        self,
        project_id: str = "proj-uuid-001",
        query_design_id: str = "qd-uuid-001",
    ) -> dict[str, Any]:
        """Build a minimal run_details dict."""
        return {"project_id": project_id, "query_design_id": query_design_id}

    def _make_comments_config(
        self,
        platforms: list[str] | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Build a minimal comments_config."""
        selected = platforms or ["reddit"]
        return {
            p: {
                "enabled": enabled,
                "mode": "search_terms",
                "max_comments_per_post": 50,
                "depth": 0,
            }
            for p in selected
        }

    def test_trigger_dispatches_task_for_enabled_platforms(self) -> None:
        """trigger_comment_collection sends a task for each enabled platform."""
        from issue_observatory.workers.tasks import trigger_comment_collection

        run_id = "run-uuid-001"
        run_details = self._make_run_details()
        comments_config = self._make_comments_config(["reddit", "bluesky"])
        posts = [{"platform_id": "p001", "url": None, "published_at": None}]

        with (
            patch(
                "issue_observatory.workers.tasks.fetch_batch_run_details",
                new_callable=AsyncMock,
                return_value=run_details,
            ),
            patch(
                "issue_observatory.workers.tasks.fetch_project_comments_config",
                new_callable=AsyncMock,
                return_value=comments_config,
            ),
            patch(
                "issue_observatory.workers.tasks.fetch_posts_for_comment_collection",
                new_callable=AsyncMock,
                return_value=posts,
            ),
            patch(
                "issue_observatory.workers._task_helpers.create_collection_tasks",
                new_callable=AsyncMock,
            ),
            patch("issue_observatory.workers.tasks.celery_app") as mock_celery,
            patch("asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)),
        ):
            result = trigger_comment_collection(run_id)

        assert result["platforms_dispatched"] == 2
        assert mock_celery.send_task.call_count == 2

    def test_trigger_skips_disabled_platforms(self) -> None:
        """Platforms with enabled=False are not dispatched."""
        from issue_observatory.workers.tasks import trigger_comment_collection

        run_id = "run-uuid-002"
        run_details = self._make_run_details()
        comments_config = {
            "reddit": {"enabled": True, "mode": "search_terms", "max_comments_per_post": 50, "depth": 0},
            "bluesky": {"enabled": False, "mode": "search_terms", "max_comments_per_post": 50, "depth": 0},
        }
        posts = [{"platform_id": "p001", "url": None, "published_at": None}]

        with (
            patch(
                "issue_observatory.workers.tasks.fetch_batch_run_details",
                new_callable=AsyncMock,
                return_value=run_details,
            ),
            patch(
                "issue_observatory.workers.tasks.fetch_project_comments_config",
                new_callable=AsyncMock,
                return_value=comments_config,
            ),
            patch(
                "issue_observatory.workers.tasks.fetch_posts_for_comment_collection",
                new_callable=AsyncMock,
                return_value=posts,
            ),
            patch(
                "issue_observatory.workers._task_helpers.create_collection_tasks",
                new_callable=AsyncMock,
            ),
            patch("issue_observatory.workers.tasks.celery_app") as mock_celery,
            patch("asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)),
        ):
            result = trigger_comment_collection(run_id)

        assert result["platforms_dispatched"] == 1

    def test_trigger_returns_zero_when_no_run_details(self) -> None:
        """Returns early with platforms_dispatched=0 if run_details is None."""
        from issue_observatory.workers.tasks import trigger_comment_collection

        with (
            patch(
                "issue_observatory.workers.tasks.fetch_batch_run_details",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)),
        ):
            result = trigger_comment_collection("run-uuid-none")

        assert result["platforms_dispatched"] == 0

    def test_trigger_returns_zero_when_no_project_id(self) -> None:
        """Run details without project_id produce platforms_dispatched=0."""
        from issue_observatory.workers.tasks import trigger_comment_collection

        run_details = {"project_id": None, "query_design_id": "qd-001"}

        with (
            patch(
                "issue_observatory.workers.tasks.fetch_batch_run_details",
                new_callable=AsyncMock,
                return_value=run_details,
            ),
            patch("asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)),
        ):
            result = trigger_comment_collection("run-uuid-003")

        assert result["platforms_dispatched"] == 0

    def test_trigger_returns_zero_when_no_comments_config(self) -> None:
        """Empty comments_config produces platforms_dispatched=0."""
        from issue_observatory.workers.tasks import trigger_comment_collection

        run_details = self._make_run_details()

        with (
            patch(
                "issue_observatory.workers.tasks.fetch_batch_run_details",
                new_callable=AsyncMock,
                return_value=run_details,
            ),
            patch(
                "issue_observatory.workers.tasks.fetch_project_comments_config",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)),
        ):
            result = trigger_comment_collection("run-uuid-004")

        assert result["platforms_dispatched"] == 0

    def test_trigger_skips_unsupported_platform(self) -> None:
        """Platforms not in _COMMENT_TASK_MAP are logged and skipped."""
        from issue_observatory.workers.tasks import trigger_comment_collection

        run_details = self._make_run_details()
        comments_config = {
            "telegram": {  # Not in _COMMENT_TASK_MAP
                "enabled": True,
                "mode": "search_terms",
                "max_comments_per_post": 50,
                "depth": 0,
            }
        }

        with (
            patch(
                "issue_observatory.workers.tasks.fetch_batch_run_details",
                new_callable=AsyncMock,
                return_value=run_details,
            ),
            patch(
                "issue_observatory.workers.tasks.fetch_project_comments_config",
                new_callable=AsyncMock,
                return_value=comments_config,
            ),
            patch("asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)),
        ):
            result = trigger_comment_collection("run-uuid-005")

        assert result["platforms_dispatched"] == 0

    def test_trigger_skips_platform_when_no_posts(self) -> None:
        """When no qualifying posts exist for a platform, it is skipped."""
        from issue_observatory.workers.tasks import trigger_comment_collection

        run_details = self._make_run_details()
        comments_config = self._make_comments_config(["reddit"])

        with (
            patch(
                "issue_observatory.workers.tasks.fetch_batch_run_details",
                new_callable=AsyncMock,
                return_value=run_details,
            ),
            patch(
                "issue_observatory.workers.tasks.fetch_project_comments_config",
                new_callable=AsyncMock,
                return_value=comments_config,
            ),
            patch(
                "issue_observatory.workers.tasks.fetch_posts_for_comment_collection",
                new_callable=AsyncMock,
                return_value=[],  # No qualifying posts
            ),
            patch("asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)),
        ):
            result = trigger_comment_collection("run-uuid-006")

        assert result["platforms_dispatched"] == 0

    def test_trigger_uses_correct_task_names_from_comment_task_map(self) -> None:
        """The task name sent to celery matches _COMMENT_TASK_MAP entries."""
        from issue_observatory.workers.tasks import trigger_comment_collection, _COMMENT_TASK_MAP

        run_details = self._make_run_details()
        comments_config = self._make_comments_config(["youtube"])
        posts = [{"platform_id": "vid001", "url": None, "published_at": None}]

        with (
            patch(
                "issue_observatory.workers.tasks.fetch_batch_run_details",
                new_callable=AsyncMock,
                return_value=run_details,
            ),
            patch(
                "issue_observatory.workers.tasks.fetch_project_comments_config",
                new_callable=AsyncMock,
                return_value=comments_config,
            ),
            patch(
                "issue_observatory.workers.tasks.fetch_posts_for_comment_collection",
                new_callable=AsyncMock,
                return_value=posts,
            ),
            patch(
                "issue_observatory.workers._task_helpers.create_collection_tasks",
                new_callable=AsyncMock,
            ),
            patch("issue_observatory.workers.tasks.celery_app") as mock_celery,
            patch("asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)),
        ):
            trigger_comment_collection("run-uuid-007")

        call_args = mock_celery.send_task.call_args
        assert call_args.args[0] == _COMMENT_TASK_MAP["youtube"]

    def test_trigger_includes_correct_kwargs_in_dispatch(self) -> None:
        """The dispatched task kwargs include post_ids, tier, max_comments, depth."""
        from issue_observatory.workers.tasks import trigger_comment_collection

        run_details = self._make_run_details(project_id="proj-001", query_design_id="qd-001")
        comments_config = {
            "reddit": {
                "enabled": True,
                "mode": "search_terms",
                "max_comments_per_post": 75,
                "depth": 1,
            }
        }
        posts = [{"platform_id": "p001", "url": None, "published_at": None}]

        with (
            patch(
                "issue_observatory.workers.tasks.fetch_batch_run_details",
                new_callable=AsyncMock,
                return_value=run_details,
            ),
            patch(
                "issue_observatory.workers.tasks.fetch_project_comments_config",
                new_callable=AsyncMock,
                return_value=comments_config,
            ),
            patch(
                "issue_observatory.workers.tasks.fetch_posts_for_comment_collection",
                new_callable=AsyncMock,
                return_value=posts,
            ),
            patch(
                "issue_observatory.workers._task_helpers.create_collection_tasks",
                new_callable=AsyncMock,
            ),
            patch("issue_observatory.workers.tasks.celery_app") as mock_celery,
            patch("asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)),
        ):
            trigger_comment_collection("run-uuid-008")

        kwargs = mock_celery.send_task.call_args.kwargs["kwargs"]
        assert kwargs["post_ids"] == posts
        assert kwargs["max_comments_per_post"] == 75
        assert kwargs["depth"] == 1
        assert kwargs["tier"] == "free"

    def test_trigger_handles_fetch_run_details_error_gracefully(self) -> None:
        """An exception from fetch_batch_run_details is caught and reported."""
        from issue_observatory.workers.tasks import trigger_comment_collection

        with (
            patch(
                "issue_observatory.workers.tasks.fetch_batch_run_details",
                new_callable=AsyncMock,
                side_effect=Exception("DB connection failed"),
            ),
            patch("asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)),
        ):
            result = trigger_comment_collection("run-uuid-err")

        assert "error" in result
        assert result["platforms_dispatched"] == 0


# ===========================================================================
# HELPER: fetch_posts_for_comment_collection
# ===========================================================================


class TestFetchPostsForCommentCollection:
    """Unit tests for the fetch_posts_for_comment_collection async helper."""

    @pytest.mark.asyncio
    async def test_post_urls_mode_returns_url_dicts_without_db(self) -> None:
        """'post_urls' mode returns the configured URLs without querying the DB."""
        from issue_observatory.workers._task_helpers import fetch_posts_for_comment_collection

        config = {
            "mode": "post_urls",
            "post_urls": [
                "https://www.reddit.com/r/Denmark/comments/abc/",
                "https://www.reddit.com/r/Denmark/comments/xyz/",
            ],
        }

        result = await fetch_posts_for_comment_collection(
            collection_run_id="run-001",
            platform="reddit",
            comments_config=config,
            project_id="proj-001",
        )

        assert len(result) == 2
        assert result[0]["url"] == "https://www.reddit.com/r/Denmark/comments/abc/"
        assert result[0]["platform_id"] is None

    @pytest.mark.asyncio
    async def test_post_urls_mode_filters_empty_urls(self) -> None:
        """Empty strings in 'post_urls' are excluded from the result.

        The implementation uses ``if u`` which filters falsy values (empty
        string ``""``).  Whitespace-only strings (``"  "``) are truthy and
        are passed through without trimming — the caller is responsible for
        providing clean URLs.
        """
        from issue_observatory.workers._task_helpers import fetch_posts_for_comment_collection

        config = {
            "mode": "post_urls",
            "post_urls": ["https://reddit.com/r/Denmark/comments/abc/", ""],
        }

        result = await fetch_posts_for_comment_collection(
            collection_run_id="run-001",
            platform="reddit",
            comments_config=config,
            project_id="proj-001",
        )

        # Empty string "" is falsy and filtered; the valid URL remains
        assert len(result) == 1
        assert result[0]["url"] == "https://reddit.com/r/Denmark/comments/abc/"

    @pytest.mark.asyncio
    async def test_search_terms_mode_queries_db(self) -> None:
        """'search_terms' mode issues a DB query filtered by search_terms_matched."""
        from issue_observatory.workers._task_helpers import fetch_posts_for_comment_collection

        config = {
            "mode": "search_terms",
            "search_terms": ["klima", "bæredygtighed"],
        }

        mock_row_1 = MagicMock()
        mock_row_1.__getitem__ = lambda self, key: {
            "platform_id": "post_abc",
            "url": "https://reddit.com/r/Denmark/comments/abc/",
            "published_at": None,
        }[key]

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [
            {"platform_id": "post_abc", "url": "https://reddit.com/r/Denmark/comments/abc/", "published_at": None}
        ]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "issue_observatory.workers._task_helpers.AsyncSessionLocal",
            return_value=mock_session_ctx,
        ):
            result = await fetch_posts_for_comment_collection(
                collection_run_id="run-001",
                platform="reddit",
                comments_config=config,
                project_id="proj-001",
            )

        mock_db.execute.assert_awaited_once()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_source_list_actors_mode_queries_db(self) -> None:
        """'source_list_actors' mode issues a DB query filtered by actor_id."""
        from issue_observatory.workers._task_helpers import fetch_posts_for_comment_collection

        config = {
            "mode": "source_list_actors",
            "actor_list_ids": ["list-uuid-001"],
        }

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "issue_observatory.workers._task_helpers.AsyncSessionLocal",
            return_value=mock_session_ctx,
        ):
            result = await fetch_posts_for_comment_collection(
                collection_run_id="run-001",
                platform="bluesky",
                comments_config=config,
                project_id="proj-001",
            )

        mock_db.execute.assert_awaited_once()
        assert result == []

    @pytest.mark.asyncio
    async def test_default_mode_is_search_terms(self) -> None:
        """Config without 'mode' key defaults to 'search_terms' mode."""
        from issue_observatory.workers._task_helpers import fetch_posts_for_comment_collection

        # No 'mode' key in config
        config: dict[str, Any] = {}

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "issue_observatory.workers._task_helpers.AsyncSessionLocal",
            return_value=mock_session_ctx,
        ):
            result = await fetch_posts_for_comment_collection(
                collection_run_id="run-001",
                platform="reddit",
                comments_config=config,
                project_id="proj-001",
            )

        # Should have executed a DB query (search_terms mode)
        mock_db.execute.assert_awaited_once()
        assert result == []

    @pytest.mark.asyncio
    async def test_post_urls_mode_empty_list_returns_empty(self) -> None:
        """'post_urls' mode with empty list returns empty result without DB access."""
        from issue_observatory.workers._task_helpers import fetch_posts_for_comment_collection

        config = {"mode": "post_urls", "post_urls": []}

        result = await fetch_posts_for_comment_collection(
            collection_run_id="run-001",
            platform="facebook",
            comments_config=config,
            project_id="proj-001",
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_search_terms_mode_with_no_configured_terms_queries_without_filter(self) -> None:
        """'search_terms' mode with empty search_terms list still queries all posts."""
        from issue_observatory.workers._task_helpers import fetch_posts_for_comment_collection

        config = {
            "mode": "search_terms",
            "search_terms": [],  # No term filtering
        }

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [
            {"platform_id": "post_123", "url": "https://bsky.app/profile/x/post/y", "published_at": None}
        ]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "issue_observatory.workers._task_helpers.AsyncSessionLocal",
            return_value=mock_session_ctx,
        ):
            result = await fetch_posts_for_comment_collection(
                collection_run_id="run-001",
                platform="bluesky",
                comments_config=config,
                project_id="proj-001",
            )

        assert len(result) == 1
        assert result[0]["platform_id"] == "post_123"

    @pytest.mark.asyncio
    async def test_result_dicts_have_expected_keys(self) -> None:
        """Results from search_terms mode have platform_id, url, published_at keys."""
        from issue_observatory.workers._task_helpers import fetch_posts_for_comment_collection
        from datetime import datetime, UTC

        pub_at = datetime(2026, 2, 1, 10, 0, 0, tzinfo=UTC)
        config = {"mode": "search_terms", "search_terms": ["test"]}

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [
            {"platform_id": "post_abc", "url": "https://reddit.com/r/x/y", "published_at": pub_at}
        ]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "issue_observatory.workers._task_helpers.AsyncSessionLocal",
            return_value=mock_session_ctx,
        ):
            result = await fetch_posts_for_comment_collection(
                collection_run_id="run-001",
                platform="reddit",
                comments_config=config,
                project_id="proj-001",
            )

        assert len(result) == 1
        rec = result[0]
        assert "platform_id" in rec
        assert "url" in rec
        assert "published_at" in rec
        assert rec["platform_id"] == "post_abc"
        assert rec["published_at"] == pub_at.isoformat()
