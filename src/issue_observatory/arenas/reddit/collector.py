"""Reddit arena collector implementation.

Collects Reddit posts and comments via the Reddit OAuth API using the
``asyncpraw`` async Python Reddit API wrapper.  Only the FREE tier is
supported — Reddit does not offer a paid research tier at this project's scale.

**Collection modes**:

- ``collect_by_terms()``: Searches across configured Danish subreddits
  (``DANISH_SUBREDDIT_SEARCH_STRING``) for each search term.  Deduplicates
  by post ID.  Optionally collects top-level comments per matched post.

- ``collect_by_actors()``: Collects posts and comments published by specific
  Reddit usernames (``actor_ids``).  Uses the ``redditor.submissions.new()``
  and ``redditor.comments.new()`` generators.

**Credentials**: Acquired from :class:`CredentialPool` with
``platform="reddit", tier="free"``.  Expected credential JSONB fields:
``client_id``, ``client_secret``, ``user_agent``.  Optional: ``username``,
``password`` (required for write operations, not needed for read-only OAuth).

Env-var fallbacks: ``REDDIT_CLIENT_ID``, ``REDDIT_CLIENT_SECRET``,
``REDDIT_USER_AGENT``.

**Rate limiting**: PRAW handles Reddit's 100 req/min limit internally.
The shared :class:`RateLimiter` adds a safety net at 90 req/min.

**Danish context**: Danish subreddits (``r/Denmark+danish+copenhagen+aarhus``)
are always included in term-based searches.  The research brief confirms that
r/Denmark content is a mix of Danish and English — both are collected and
downstream analysis applies language filters.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from issue_observatory.arenas.base import ArenaCollector, TemporalMode, Tier
from issue_observatory.arenas.query_builder import format_boolean_query_for_platform
from issue_observatory.arenas.reddit.config import (
    ALL_DANISH_SUBREDDITS,
    DANISH_SUBREDDIT_SEARCH_STRING,
    DEFAULT_MAX_RESULTS,
    DEFAULT_SEARCH_SORT,
    DEFAULT_TIME_FILTER,
    DEFAULT_USER_AGENT,
    INCLUDE_COMMENTS_DEFAULT,
    MAX_COMMENTS_PER_POST,
    MAX_RESULTS_PER_SEARCH,
    REDDIT_RATE_LIMIT_PER_MINUTE,
    REDDIT_TIERS,
    REDDIT_WINDOW_SECONDS,
)
from issue_observatory.arenas.registry import register
from issue_observatory.config.tiers import TierConfig
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.core.normalizer import Normalizer

logger = logging.getLogger(__name__)


@register
class RedditCollector(ArenaCollector):
    """Collects Reddit posts and comments via the Reddit OAuth API.

    Supported tiers:
    - ``Tier.FREE``  — Reddit OAuth (100 req/min, no cost).

    Reddit is a free-only arena.  The free API is sufficient for all Phase 1
    collection requirements.

    Class Attributes:
        arena_name: ``"social_media"``
        platform_name: ``"reddit"``
        supported_tiers: ``[Tier.FREE]``

    Args:
        credential_pool: Optional credential pool for OAuth credential
            acquisition.  If ``None``, the collector falls back to
            ``REDDIT_CLIENT_ID`` / ``REDDIT_CLIENT_SECRET`` environment
            variables.
        rate_limiter: Optional Redis-backed rate limiter.  When present,
            every outbound Reddit API request is gated through it.
        include_comments: Whether to collect top-level comments for matched
            posts.  Defaults to ``False`` to conserve API quota.
    """

    arena_name: str = "social_media"
    platform_name: str = "reddit"
    supported_tiers: list[Tier] = [Tier.FREE]
    temporal_mode: TemporalMode = TemporalMode.RECENT

    def __init__(
        self,
        credential_pool: Any = None,
        rate_limiter: Any = None,
        include_comments: bool = INCLUDE_COMMENTS_DEFAULT,
    ) -> None:
        super().__init__(credential_pool=credential_pool, rate_limiter=rate_limiter)
        self._include_comments = include_comments
        self._normalizer = Normalizer()

    # ------------------------------------------------------------------
    # ArenaCollector abstract method implementations
    # ------------------------------------------------------------------

    async def collect_by_terms(
        self,
        terms: list[str],
        tier: Tier,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
        term_groups: list[list[str]] | None = None,
        language_filter: list[str] | None = None,
        extra_subreddits: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Collect Reddit posts matching one or more search terms.

        Searches across all configured Danish subreddits for each term.
        Results are deduplicated by post ID across all term queries.
        Optionally collects top-level comments for each matched post when
        ``include_comments=True`` was passed to the constructor.

        When ``term_groups`` is provided, Reddit's ``+`` join syntax is used
        to AND terms within a group.  One search request is issued per group;
        the results are merged and deduplicated.

        Args:
            terms: Search terms (used when ``term_groups`` is ``None``).
            tier: Operational tier.  Only ``Tier.FREE`` is supported.
            date_from: Not used — Reddit's search API has no date-range
                parameter.
            date_to: Not used — see ``date_from``.
            max_results: Upper bound on returned records.  ``None`` uses
                :data:`~config.DEFAULT_MAX_RESULTS`.
            term_groups: Optional boolean AND/OR groups.  Each group is
                joined with ``+`` (Reddit AND syntax) and queried separately.
            language_filter: Not used — Reddit Danish subreddits provide
                implicit language scoping.
            extra_subreddits: Optional list of subreddit names (without the
                ``r/`` prefix) supplied by the researcher via
                ``arenas_config["reddit"]["custom_subreddits"]`` (GR-03).
                These are merged with :data:`ALL_DANISH_SUBREDDITS` before
                building the multireddit search string.

        Returns:
            List of normalized content record dicts (posts and optionally
            comments).

        Raises:
            ArenaRateLimitError: When Reddit returns a 429 response.
            ArenaAuthError: When the OAuth credentials are rejected.
            ArenaCollectionError: On other unrecoverable API errors.
            NoCredentialAvailableError: When no credential is available.
        """
        self._validate_tier(tier)
        effective_max = max_results if max_results is not None else DEFAULT_MAX_RESULTS
        cred = await self._acquire_credential()

        try:
            reddit = await self._build_reddit_client(cred)
        except Exception as exc:
            raise ArenaCollectionError(
                f"reddit: failed to build Reddit client: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

        all_records: list[dict[str, Any]] = []
        seen_post_ids: set[str] = set()

        # Build query strings: boolean groups use Reddit's + syntax for AND.
        if term_groups is not None:
            query_strings: list[str] = [
                format_boolean_query_for_platform(groups=[grp], platform="reddit")
                for grp in term_groups
                if grp
            ]
        else:
            query_strings = list(terms)

        # GR-03: build effective subreddit search string including extra subreddits.
        effective_subreddit_string = _build_subreddit_string(extra_subreddits)

        try:
            async with reddit:
                for query in query_strings:
                    if len(all_records) >= effective_max:
                        break
                    remaining = effective_max - len(all_records)
                    new_records, new_seen = await self._search_term(
                        reddit=reddit,
                        term=query,
                        max_results=min(remaining, MAX_RESULTS_PER_SEARCH),
                        seen_post_ids=seen_post_ids,
                        credential_id=cred.get("id", "default"),
                        subreddit_string=effective_subreddit_string,
                    )
                    seen_post_ids.update(new_seen)
                    all_records.extend(new_records)
        finally:
            if self.credential_pool is not None:
                await self.credential_pool.release(credential_id=cred.get("id", "default"))

        logger.info(
            "reddit: collect_by_terms completed — %d records for %d queries",
            len(all_records),
            len(query_strings),
        )
        return all_records

    async def collect_by_actors(
        self,
        actor_ids: list[str],
        tier: Tier,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect posts and comments published by specific Reddit users.

        Each ``actor_id`` is a Reddit username (without the ``u/`` prefix).
        Collects both submissions and comments for each user.

        Args:
            actor_ids: Reddit usernames to collect from.
            tier: Operational tier.  Only ``Tier.FREE`` is supported.
            date_from: Not used — Reddit's user history has no API-level
                date filter.  Filter by ``published_at`` downstream.
            date_to: Not used — see ``date_from``.
            max_results: Upper bound on returned records per actor.  ``None``
                uses :data:`~config.DEFAULT_MAX_RESULTS`.

        Returns:
            List of normalized content record dicts (posts and comments).

        Raises:
            ArenaRateLimitError: On HTTP 429 from Reddit.
            ArenaAuthError: On credential rejection.
            ArenaCollectionError: On other unrecoverable API errors.
            NoCredentialAvailableError: When no credential is available.
        """
        self._validate_tier(tier)
        effective_max = max_results if max_results is not None else DEFAULT_MAX_RESULTS
        cred = await self._acquire_credential()

        try:
            reddit = await self._build_reddit_client(cred)
        except Exception as exc:
            raise ArenaCollectionError(
                f"reddit: failed to build Reddit client: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

        all_records: list[dict[str, Any]] = []

        try:
            async with reddit:
                for username in actor_ids:
                    if len(all_records) >= effective_max:
                        break
                    records = await self._collect_user(
                        reddit=reddit,
                        username=username,
                        max_results=effective_max - len(all_records),
                        credential_id=cred.get("id", "default"),
                    )
                    all_records.extend(records)
        finally:
            if self.credential_pool is not None:
                await self.credential_pool.release(credential_id=cred.get("id", "default"))

        logger.info(
            "reddit: collect_by_actors completed — %d records for %d actors",
            len(all_records),
            len(actor_ids),
        )
        return all_records

    def get_tier_config(self, tier: Tier) -> TierConfig | None:
        """Return the tier configuration for the Reddit arena.

        Args:
            tier: The requested operational tier.

        Returns:
            :class:`TierConfig` for ``Tier.FREE``.  ``None`` for MEDIUM
            and PREMIUM (unavailable).

        Raises:
            ValueError: If ``tier`` is not a recognised :class:`Tier` value.
        """
        if tier not in REDDIT_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}' for reddit. "
                f"Valid tiers: {list(REDDIT_TIERS.keys())}"
            )
        return REDDIT_TIERS[tier]

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single Reddit post or comment to the universal schema.

        Delegates to :class:`Normalizer` after enriching the raw dict with
        Reddit-specific field aliases that the normalizer recognises.

        Posts and comments are distinguished by the ``content_type`` field
        already present in the raw item (set to ``"post"`` or ``"comment"``
        by the collection helpers).

        Args:
            raw_item: Raw dict produced by the collection helpers.  Must
                include ``content_type``, ``platform_id``, and either
                ``title`` (posts) or ``body`` (comments).

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        return self._normalizer.normalize(
            raw_item=raw_item,
            platform=self.platform_name,
            arena=self.arena_name,
            collection_tier="free",
        )

    async def health_check(self) -> dict[str, Any]:
        """Verify Reddit API connectivity by fetching a single hot post from r/Denmark.

        Acquires a credential, opens an asyncpraw client, and fetches the
        top hot post from r/Denmark.  Returns ``"ok"`` on success.

        Returns:
            Dict with ``status`` (``"ok"`` | ``"degraded"`` | ``"down"``),
            ``arena``, ``platform``, ``checked_at``, and optionally ``detail``.
        """
        checked_at = datetime.now(tz=timezone.utc).isoformat()
        base: dict[str, Any] = {
            "arena": self.arena_name,
            "platform": self.platform_name,
            "checked_at": checked_at,
        }

        try:
            cred = await self._acquire_credential()
        except NoCredentialAvailableError as exc:
            return {
                **base,
                "status": "degraded",
                "detail": f"No credential available for health check: {exc}",
            }

        try:
            reddit = await self._build_reddit_client(cred)
            async with reddit:
                subreddit = await reddit.subreddit("Denmark")
                posts = [post async for post in subreddit.hot(limit=1)]
                if not posts:
                    return {
                        **base,
                        "status": "degraded",
                        "detail": "r/Denmark returned 0 hot posts.",
                    }
            return {**base, "status": "ok", "detail": f"r/Denmark reachable; post={posts[0].id}"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("reddit: health_check failed: %s", exc)
            return {**base, "status": "down", "detail": str(exc)}
        finally:
            if self.credential_pool is not None:
                await self.credential_pool.release(credential_id=cred.get("id", "default"))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _acquire_credential(self) -> dict[str, Any]:
        """Acquire a Reddit OAuth credential from the credential pool.

        Falls back to environment variables when no pool is configured or
        when the pool returns no DB credential.

        Returns:
            Credential dict with at minimum ``client_id``, ``client_secret``,
            and ``user_agent`` keys.

        Raises:
            NoCredentialAvailableError: When no usable credential is found.
        """
        if self.credential_pool is not None:
            cred = await self.credential_pool.acquire(platform="reddit", tier="free")
            if cred is not None:
                # Ensure credential has required Reddit-specific fields
                if "client_id" not in cred:
                    cred["client_id"] = cred.get("api_key", "")
                cred.setdefault("client_secret", "")
                cred.setdefault("user_agent", DEFAULT_USER_AGENT)
                return cred

        # Env-var fallback
        client_id = os.environ.get("REDDIT_CLIENT_ID", "")
        client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
        user_agent = os.environ.get("REDDIT_USER_AGENT", DEFAULT_USER_AGENT)

        if not client_id or not client_secret:
            raise NoCredentialAvailableError(platform="reddit", tier="free")

        return {
            "id": "REDDIT_CLIENT_ID",
            "platform": "reddit",
            "tier": "free",
            "client_id": client_id,
            "client_secret": client_secret,
            "user_agent": user_agent,
        }

    async def _build_reddit_client(self, cred: dict[str, Any]) -> Any:
        """Construct an ``asyncpraw.Reddit`` async context manager.

        Each call produces a new Reddit instance.  Instances are not
        thread-safe and must not be shared across Celery workers.

        Args:
            cred: Credential dict with ``client_id``, ``client_secret``,
                and ``user_agent`` keys.

        Returns:
            An ``asyncpraw.Reddit`` instance ready to use as an async
            context manager.

        Raises:
            ImportError: If ``asyncpraw`` is not installed.
        """
        import asyncpraw  # noqa: PLC0415

        return asyncpraw.Reddit(
            client_id=cred["client_id"],
            client_secret=cred["client_secret"],
            user_agent=cred.get("user_agent", DEFAULT_USER_AGENT),
            # username/password are optional; required only for write operations.
            username=cred.get("username") or None,
            password=cred.get("password") or None,
        )

    async def _wait_for_rate_limit(self, credential_id: str) -> None:
        """Gate the next API call through the shared rate limiter if available.

        Args:
            credential_id: Credential ID used to namespace the rate limit key.
        """
        if self.rate_limiter is not None:
            key = f"ratelimit:{self.arena_name}:{self.platform_name}:{credential_id}"
            await self.rate_limiter.wait_for_slot(
                key=key,
                max_calls=REDDIT_RATE_LIMIT_PER_MINUTE,
                window_seconds=REDDIT_WINDOW_SECONDS,
            )

    async def _search_term(
        self,
        reddit: Any,
        term: str,
        max_results: int,
        seen_post_ids: set[str],
        credential_id: str,
        subreddit_string: str | None = None,
    ) -> tuple[list[dict[str, Any]], set[str]]:
        """Search Reddit for a single term across Danish subreddits.

        Args:
            reddit: An active ``asyncpraw.Reddit`` context.
            term: Search term to query.
            max_results: Maximum number of new posts to return.
            seen_post_ids: Set of already-seen post IDs for deduplication.
            credential_id: Credential ID for rate limiting.
            subreddit_string: Optional multireddit ``+``-joined string to search.
                When ``None``, falls back to :data:`DANISH_SUBREDDIT_SEARCH_STRING`.
                Overridden by the GR-03 extra-subreddits merge in
                :meth:`collect_by_terms`.

        Returns:
            Tuple of (list of normalized records, set of new post IDs seen).

        Raises:
            ArenaRateLimitError: On rate limit response from Reddit.
            ArenaAuthError: On authentication failure.
            ArenaCollectionError: On other API errors.
        """
        import asyncprawcore.exceptions  # noqa: PLC0415

        records: list[dict[str, Any]] = []
        new_seen: set[str] = set()

        effective_subreddit_string = subreddit_string or DANISH_SUBREDDIT_SEARCH_STRING

        try:
            await self._wait_for_rate_limit(credential_id)
            subreddit = await reddit.subreddit(effective_subreddit_string)
            search_gen = subreddit.search(
                term,
                limit=min(max_results, MAX_RESULTS_PER_SEARCH),
                sort=DEFAULT_SEARCH_SORT,
                time_filter=DEFAULT_TIME_FILTER,
            )

            async for post in search_gen:
                if post.id in seen_post_ids:
                    continue
                new_seen.add(post.id)
                raw_post = self._post_to_raw(post, search_term=term)
                records.append(self.normalize(raw_post))

                if self._include_comments:
                    comment_records = await self._collect_post_comments(
                        post=post,
                        credential_id=credential_id,
                    )
                    records.extend(comment_records)

                if len(records) >= max_results:
                    break

        except asyncprawcore.exceptions.TooManyRequests as exc:
            raise ArenaRateLimitError(
                f"reddit: rate limited during search for term={term!r}",
                retry_after=60.0,
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc
        except asyncprawcore.exceptions.Forbidden as exc:
            logger.warning(
                "reddit: forbidden access to subreddits %r for term=%r — skipping. error=%s",
                DANISH_SUBREDDIT_SEARCH_STRING,
                term,
                exc,
            )
        except asyncprawcore.exceptions.ResponseException as exc:
            if hasattr(exc, "response") and exc.response is not None:
                status = exc.response.status
                if status in (401, 403):
                    raise ArenaAuthError(
                        f"reddit: authentication failed (HTTP {status})",
                        arena=self.arena_name,
                        platform=self.platform_name,
                    ) from exc
            raise ArenaCollectionError(
                f"reddit: API error during search for term={term!r}: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc
        except Exception as exc:
            raise ArenaCollectionError(
                f"reddit: unexpected error during search for term={term!r}: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

        logger.debug("reddit: term=%r collected %d records", term, len(records))
        return records, new_seen

    async def _collect_post_comments(
        self,
        post: Any,
        credential_id: str,
    ) -> list[dict[str, Any]]:
        """Collect top-level comments for a single Reddit post.

        Uses ``replace_more(limit=0)`` to skip "load more" comment stubs,
        minimising API calls.  Only top-level comments (depth 0) are returned.

        Args:
            post: An ``asyncpraw.models.Submission`` instance.
            credential_id: Credential ID for rate limiting.

        Returns:
            List of normalized comment records.
        """
        import asyncprawcore.exceptions  # noqa: PLC0415

        records: list[dict[str, Any]] = []
        try:
            await self._wait_for_rate_limit(credential_id)
            await post.comments.replace_more(limit=0)
            comments = post.comments.list()
            count = 0
            for comment in comments:
                if count >= MAX_COMMENTS_PER_POST:
                    break
                # Only top-level comments (depth 0)
                if getattr(comment, "depth", 0) != 0:
                    continue
                raw_comment = self._comment_to_raw(comment, parent_post=post)
                records.append(self.normalize(raw_comment))
                count += 1
        except asyncprawcore.exceptions.Forbidden as exc:
            logger.warning(
                "reddit: forbidden when fetching comments for post=%s — skipping. error=%s",
                getattr(post, "id", "unknown"),
                exc,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "reddit: error fetching comments for post=%s: %s",
                getattr(post, "id", "unknown"),
                exc,
            )
        return records

    async def _collect_user(
        self,
        reddit: Any,
        username: str,
        max_results: int,
        credential_id: str,
    ) -> list[dict[str, Any]]:
        """Collect posts and comments from a single Reddit user.

        Args:
            reddit: An active ``asyncpraw.Reddit`` context.
            username: Reddit username (without ``u/`` prefix).
            max_results: Upper bound on returned records.
            credential_id: Credential ID for rate limiting.

        Returns:
            List of normalized post and comment records.

        Raises:
            ArenaRateLimitError: On rate limit response.
            ArenaCollectionError: On other errors.
        """
        import asyncprawcore.exceptions  # noqa: PLC0415

        records: list[dict[str, Any]] = []
        try:
            await self._wait_for_rate_limit(credential_id)
            redditor = await reddit.redditor(username)

            # Collect posts
            async for post in redditor.submissions.new(limit=min(max_results, 100)):
                raw_post = self._post_to_raw(post)
                records.append(self.normalize(raw_post))
                if len(records) >= max_results:
                    break

            # Collect comments (up to remaining quota)
            if len(records) < max_results:
                await self._wait_for_rate_limit(credential_id)
                async for comment in redditor.comments.new(
                    limit=min(max_results - len(records), 100)
                ):
                    raw_comment = self._comment_to_raw(comment)
                    records.append(self.normalize(raw_comment))
                    if len(records) >= max_results:
                        break

        except asyncprawcore.exceptions.TooManyRequests as exc:
            raise ArenaRateLimitError(
                f"reddit: rate limited while collecting user={username!r}",
                retry_after=60.0,
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc
        except asyncprawcore.exceptions.NotFound:
            logger.warning("reddit: user %r not found — skipping.", username)
        except asyncprawcore.exceptions.Forbidden as exc:
            logger.warning(
                "reddit: forbidden access to user %r — skipping. error=%s", username, exc
            )
        except Exception as exc:
            raise ArenaCollectionError(
                f"reddit: unexpected error collecting user={username!r}: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

        logger.debug("reddit: user=%r collected %d records", username, len(records))
        return records

    # ------------------------------------------------------------------
    # Raw-to-dict converters
    # ------------------------------------------------------------------

    def _post_to_raw(
        self,
        post: Any,
        search_term: str | None = None,
    ) -> dict[str, Any]:
        """Convert an ``asyncpraw.models.Submission`` to a raw dict.

        Args:
            post: asyncpraw Submission object.
            search_term: The search term that matched this post, if any.

        Returns:
            Dict with all fields mapped for :meth:`normalize`.
        """
        author_name: str | None = None
        if post.author is not None:
            try:
                author_name = post.author.name
            except AttributeError:
                author_name = None

        # Determine post type for raw_metadata
        post_type = "self" if getattr(post, "is_self", False) else "link"
        if getattr(post, "is_video", False):
            post_type = "video"
        elif getattr(post, "post_hint", "") == "image":
            post_type = "image"

        # Extract media URL for image/video posts
        media_urls: list[str] = []
        if post_type in ("image", "video") and hasattr(post, "url"):
            media_urls.append(post.url)

        return {
            # Universal schema fields
            "content_type": "post",
            "platform_id": post.id,
            "title": post.title,
            "text_content": post.selftext if post.selftext not in ("", "[removed]") else None,
            "body": post.selftext if post.selftext not in ("", "[removed]") else None,
            "url": f"https://www.reddit.com{post.permalink}",
            "published_at": post.created_utc,
            "author_platform_id": author_name,
            "author_display_name": author_name,
            "score": post.score,
            "likes_count": post.score,
            "num_comments": post.num_comments,
            "comments_count": post.num_comments,
            "shares_count": getattr(post, "num_crossposts", None),
            "engagement_score": getattr(post, "upvote_ratio", None),
            "media_urls": media_urls,
            # Raw metadata passthrough
            "subreddit": str(post.subreddit),
            "subreddit_id": post.subreddit_id,
            "link_flair_text": getattr(post, "link_flair_text", None),
            "is_self": getattr(post, "is_self", None),
            "domain": getattr(post, "domain", None),
            "over_18": getattr(post, "over_18", False),
            "spoiler": getattr(post, "spoiler", False),
            "stickied": getattr(post, "stickied", False),
            "distinguished": getattr(post, "distinguished", None),
            "gilded": getattr(post, "gilded", 0),
            "post_type": post_type,
            "permalink": post.permalink,
            "upvote_ratio": getattr(post, "upvote_ratio", None),
            "search_term_matched": search_term,
        }

    def _comment_to_raw(
        self,
        comment: Any,
        parent_post: Any = None,
    ) -> dict[str, Any]:
        """Convert an ``asyncpraw.models.Comment`` to a raw dict.

        Args:
            comment: asyncpraw Comment object.
            parent_post: Optional parent Submission for context metadata.

        Returns:
            Dict with all fields mapped for :meth:`normalize`.
        """
        author_name: str | None = None
        if comment.author is not None:
            try:
                author_name = comment.author.name
            except AttributeError:
                author_name = None

        body = comment.body
        if body in ("[deleted]", "[removed]"):
            body = None

        # Permalink for comments
        permalink = getattr(comment, "permalink", None)
        url = f"https://www.reddit.com{permalink}" if permalink else None

        return {
            # Universal schema fields
            "content_type": "comment",
            "platform_id": comment.id,
            "title": None,
            "text_content": body,
            "body": body,
            "url": url,
            "published_at": comment.created_utc,
            "author_platform_id": author_name,
            "author_display_name": author_name,
            "score": comment.score,
            "likes_count": comment.score,
            "num_comments": None,
            "comments_count": None,
            "shares_count": None,
            "engagement_score": None,
            "media_urls": [],
            # Raw metadata passthrough
            "subreddit": str(comment.subreddit),
            "subreddit_id": getattr(comment, "subreddit_id", None),
            "link_flair_text": None,
            "is_self": None,
            "domain": None,
            "over_18": getattr(comment, "over_18", False),
            "spoiler": False,
            "stickied": getattr(comment, "stickied", False),
            "distinguished": getattr(comment, "distinguished", None),
            "gilded": getattr(comment, "gilded", 0),
            "post_type": None,
            "permalink": permalink,
            "upvote_ratio": None,
            "parent_id": getattr(comment, "parent_id", None),
            "depth": getattr(comment, "depth", 0),
            # Parent post context
            "parent_post_id": getattr(parent_post, "id", None),
            "parent_post_title": getattr(parent_post, "title", None),
        }


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _build_subreddit_string(extra_subreddits: list[str] | None) -> str:
    """Build a Reddit multireddit ``+``-joined search string.

    Merges :data:`~config.ALL_DANISH_SUBREDDITS` with any researcher-supplied
    extra subreddit names (GR-03).  Duplicate names are removed while
    preserving the insertion order (defaults first, extras appended).

    Args:
        extra_subreddits: Optional list of additional subreddit names
            (without the ``r/`` prefix) from
            ``arenas_config["reddit"]["custom_subreddits"]``.

    Returns:
        A ``+``-joined multireddit string suitable for
        ``asyncpraw.Reddit.subreddit()``.  Falls back to
        :data:`DANISH_SUBREDDIT_SEARCH_STRING` when ``extra_subreddits``
        is ``None`` or empty.
    """
    if not extra_subreddits:
        return DANISH_SUBREDDIT_SEARCH_STRING

    seen: set[str] = set()
    merged: list[str] = []
    for name in ALL_DANISH_SUBREDDITS + [
        s.strip().lstrip("r/") for s in extra_subreddits if s and s.strip()
    ]:
        if name and name not in seen:
            seen.add(name)
            merged.append(name)

    return "+".join(merged) if merged else DANISH_SUBREDDIT_SEARCH_STRING
