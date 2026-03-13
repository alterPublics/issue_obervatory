"""YouTube arena collector implementation.

Implements the RSS-first quota strategy for the YouTube Data API v3:

1. **RSS feeds** (zero quota): poll ``https://www.youtube.com/feeds/videos.xml``
   for known channel IDs via ``feedparser`` — no API key required.
2. **videos.list batch enrichment** (1 unit per 50 videos): after RSS
   discovery, enrich video metadata with statistics and content details.
3. **search.list** (100 units per call): keyword discovery when RSS is
   insufficient, with ``relevanceLanguage=da`` and ``regionCode=DK``.

Credential rotation on quota exhaustion:
- HTTP 403 with ``reason="quotaExceeded"`` → ``ArenaRateLimitError``
- The Celery task layer triggers credential rotation via ``CredentialPool``
  before scheduling a retry.

Low-level HTTP and RSS I/O lives in :mod:`._client` to keep this module
within the ~400-line file-size limit.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

import httpx

from issue_observatory.arenas.base import ArenaCollector, TemporalMode, Tier
from issue_observatory.arenas.query_builder import format_boolean_query_for_platform
from issue_observatory.arenas.registry import register
from issue_observatory.arenas.youtube._client import (
    fetch_videos_batch,
    poll_channel_rss,
    search_videos_page,
)
from issue_observatory.arenas.youtube.config import (
    MAX_RESULTS_PER_SEARCH_PAGE,
    MAX_VIDEO_IDS_PER_BATCH,
    QUOTA_COSTS,
    REQUEST_RATE_MAX_CALLS,
    REQUEST_RATE_WINDOW_SECONDS,
    YOUTUBE_TIERS,
    YOUTUBE_VIDEO_BASE_URL,
)
from issue_observatory.config.tiers import TierConfig
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.core.language_utils import resolve_youtube_params
from issue_observatory.core.normalizer import Normalizer

logger = logging.getLogger(__name__)

# YouTube video category ID -> human-readable name mapping (partial).
_CATEGORY_NAMES: dict[str, str] = {
    "1": "Film & Animation", "2": "Autos & Vehicles", "10": "Music",
    "15": "Pets & Animals", "17": "Sports", "18": "Short Movies",
    "19": "Travel & Events", "20": "Gaming", "21": "Videoblogging",
    "22": "People & Blogs", "23": "Comedy", "24": "Entertainment",
    "25": "News & Politics", "26": "Howto & Style", "27": "Education",
    "28": "Science & Technology", "29": "Nonprofits & Activism",
}


@register
class YouTubeCollector(ArenaCollector):
    """Collects YouTube videos via YouTube Data API v3 and channel RSS feeds.

    Supports ``Tier.FREE`` only — YouTube has no paid API tier.  Multiple
    GCP project API keys can be pooled via ``CredentialPool`` to multiply the
    effective daily quota (10,000 units per key per day).

    Collection strategy:
    - ``collect_by_terms()``: ``search.list`` with Danish locale params,
      followed by ``videos.list`` batch enrichment.
    - ``collect_by_actors()``: RSS feed polling for each channel ID (zero
      quota), followed by ``videos.list`` batch enrichment.

    Class Attributes:
        arena_name: ``"social_media"``
        platform_name: ``"youtube"``
        supported_tiers: ``[Tier.FREE]``

    Args:
        credential_pool: Credential pool for YouTube API key rotation.
            Platform identifier: ``"youtube"``, tier: ``"free"``.
        rate_limiter: Optional Redis-backed rate limiter for request-rate
            throttling (separate from quota management).
        http_client: Optional injected :class:`httpx.AsyncClient` for testing.
    """

    arena_name: str = "social_media"
    platform_name: str = "youtube"
    supported_tiers: list[Tier] = [Tier.FREE]
    temporal_mode: TemporalMode = TemporalMode.MIXED
    supports_actor_collection: bool = True
    source_list_config_key: str | None = "custom_channels"

    def __init__(
        self,
        credential_pool: Any = None,
        rate_limiter: Any = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(credential_pool=credential_pool, rate_limiter=rate_limiter)
        self._http_client = http_client
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
    ) -> list[dict[str, Any]]:
        """Collect YouTube videos matching one or more search terms.

        Uses ``search.list`` (100 units/call) with ``relevanceLanguage=da``
        and ``regionCode=DK``.  Paginates via ``nextPageToken``.  After
        collecting video IDs, enriches them via ``videos.list`` batch calls
        (1 unit per 50 videos).

        When ``term_groups`` is provided, YouTube's pipe ``|`` OR and space AND
        syntax is used to build a single combined query that captures all groups.

        Args:
            terms: Search terms (used when ``term_groups`` is ``None``).
            tier: Operational tier.  Only ``Tier.FREE`` is supported.
            date_from: Optional ``publishedAfter`` ISO 8601 / datetime filter.
            date_to: Optional ``publishedBefore`` ISO 8601 / datetime filter.
            max_results: Maximum records to return across all terms.
            term_groups: Optional boolean AND/OR groups.  Groups are joined
                with ``|`` (YouTube OR) and terms within a group are
                space-joined (YouTube AND).
            language_filter: Optional language codes; the first code overrides
                the default ``relevanceLanguage`` param (default ``"da"``).

        Returns:
            List of normalized content record dicts.

        Raises:
            ArenaRateLimitError: On HTTP 403 with ``quotaExceeded``.
            ArenaAuthError: On HTTP 401 or non-quota 403.
            ArenaCollectionError: On other unrecoverable API errors.
            NoCredentialAvailableError: When no API key is available.
        """
        self._validate_tier(tier)
        self._reset_batch_state()
        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

        # Resolve locale parameters for this collection run.
        yt_locale = resolve_youtube_params(language_filter)

        cred = await self._acquire_credential()
        published_after = self._to_iso8601(date_from) if date_from else None
        published_before = self._to_iso8601(date_to) if date_to else None

        # Build query strings.  YouTube supports pipe-OR and space-AND natively,
        # so all groups can be combined into one query string.
        if term_groups is not None:
            query_strings: list[str] = [
                format_boolean_query_for_platform(groups=term_groups, platform="youtube")
            ]
        else:
            query_strings = list(terms)

        all_video_ids: list[str] = []
        # Track which term retrieved each video ID for search_terms_matched
        video_id_to_term: dict[str, str] = {}

        try:
            async with self._build_http_client() as client:
                for term in query_strings:
                    if len(all_video_ids) >= effective_max:
                        break
                    count_before = len(all_video_ids)
                    page_token: str | None = None
                    while len(all_video_ids) < effective_max:
                        remaining = effective_max - len(all_video_ids)
                        await self._throttle_request(cred["id"])
                        try:
                            ids, page_token = await search_videos_page(
                                client=client,
                                api_key=cred["api_key"],
                                credential_pool=self.credential_pool,
                                cred_id=cred["id"],
                                term=term,
                                max_results_page=min(MAX_RESULTS_PER_SEARCH_PAGE, remaining),
                                page_token=page_token,
                                published_after=published_after,
                                published_before=published_before,
                                locale_params=yt_locale,
                            )
                        except ArenaRateLimitError:
                            # Quota exhausted — rotate to the next credential.
                            if self.credential_pool is not None:
                                await self.credential_pool.release(credential_id=cred["id"])
                            logger.warning(
                                "youtube: quota exhausted for cred=%s, rotating",
                                cred["id"],
                            )
                            cred = await self._acquire_credential()
                            continue
                        for video_id in ids:
                            video_id_to_term[video_id] = term
                        all_video_ids.extend(ids)
                        if not page_token or not ids:
                            break
                    self._record_input_count(term, len(all_video_ids) - count_before)

                try:
                    await self._enrich_videos(
                        client=client,
                        api_key=cred["api_key"],
                        cred_id=cred["id"],
                        video_ids=all_video_ids[:effective_max],
                        video_id_to_term=video_id_to_term,
                    )
                except ArenaRateLimitError:
                    if self.credential_pool is not None:
                        await self.credential_pool.release(credential_id=cred["id"])
                    logger.warning(
                        "youtube: quota exhausted during enrichment for cred=%s, rotating",
                        cred["id"],
                    )
                    cred = await self._acquire_credential()
                    await self._enrich_videos(
                        client=client,
                        api_key=cred["api_key"],
                        cred_id=cred["id"],
                        video_ids=all_video_ids[:effective_max],
                        video_id_to_term=video_id_to_term,
                    )
        finally:
            if self.credential_pool is not None:
                await self.credential_pool.release(credential_id=cred["id"])

        self._flush()
        logger.info(
            "youtube: collect_by_terms — queries=%d, emitted=%d, tier=%s",
            len(query_strings), self._total_emitted, tier.value,
        )
        return list(self._batch_buffer)

    async def collect_by_actors(
        self,
        actor_ids: list[str],
        tier: Tier,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect videos from YouTube channel IDs via RSS feeds.

        Actor IDs must be YouTube channel IDs (format: ``UC...``).  RSS feeds
        are polled at zero quota cost.  Discovered video IDs are then
        batch-enriched via ``videos.list`` (1 unit per 50 videos).

        Args:
            actor_ids: YouTube channel IDs (format: ``UC...``).
            tier: Operational tier.  Only ``Tier.FREE`` is supported.
            date_from: Optional lower bound for filtering by publication date.
            date_to: Optional upper bound for filtering by publication date.
            max_results: Maximum records to return across all channels.

        Returns:
            List of normalized content record dicts.

        Raises:
            ArenaRateLimitError: On HTTP 403 with ``quotaExceeded``.
            ArenaAuthError: On HTTP 401 or non-quota 403.
            ArenaCollectionError: On unrecoverable API errors.
            NoCredentialAvailableError: When no API key is available.
        """
        self._validate_tier(tier)
        self._reset_batch_state()
        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

        date_from_dt = self._parse_datetime(date_from)
        date_to_dt = self._parse_datetime(date_to)
        all_video_ids: list[str] = []
        self._skipped_actors = []

        for channel_id in actor_ids:
            if len(all_video_ids) >= effective_max:
                break
            count_before = len(all_video_ids)
            try:
                rss_ids = await poll_channel_rss(
                    channel_id=channel_id,
                    date_from=date_from_dt,
                    date_to=date_to_dt,
                )
            except ArenaRateLimitError:
                raise
            except (ArenaCollectionError, Exception) as exc:
                self._record_skipped_actor(
                    actor_id=channel_id,
                    reason="rss_error",
                    error=str(exc),
                )
                continue
            all_video_ids.extend(rss_ids)
            self._record_input_count(channel_id, len(all_video_ids) - count_before)

        cred = await self._acquire_credential()
        try:
            async with self._build_http_client() as client:
                try:
                    await self._enrich_videos(
                        client=client,
                        api_key=cred["api_key"],
                        cred_id=cred["id"],
                        video_ids=all_video_ids[:effective_max],
                    )
                except ArenaRateLimitError:
                    if self.credential_pool is not None:
                        await self.credential_pool.release(credential_id=cred["id"])
                    logger.warning(
                        "youtube: quota exhausted during actor enrichment for cred=%s, rotating",
                        cred["id"],
                    )
                    cred = await self._acquire_credential()
                    await self._enrich_videos(
                        client=client,
                        api_key=cred["api_key"],
                        cred_id=cred["id"],
                        video_ids=all_video_ids[:effective_max],
                    )
        finally:
            if self.credential_pool is not None:
                await self.credential_pool.release(credential_id=cred["id"])

        self._flush()
        logger.info(
            "youtube: collect_by_actors — channels=%d, rss_ids=%d, emitted=%d, skipped=%d",
            len(actor_ids), len(all_video_ids), self._total_emitted, len(self._skipped_actors),
        )
        return list(self._batch_buffer)

    def get_tier_config(self, tier: Tier) -> TierConfig:
        """Return tier configuration for the YouTube arena.

        Args:
            tier: Requested operational tier.

        Returns:
            :class:`TierConfig` for the requested tier.

        Raises:
            ValueError: If the tier is not in ``YOUTUBE_TIERS``.
        """
        if tier not in YOUTUBE_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}' for youtube. "
                f"Valid tiers: {list(YOUTUBE_TIERS.keys())}"
            )
        return YOUTUBE_TIERS[tier]

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw YouTube video resource to the universal schema.

        Maps fields from a ``videos.list`` response item to the
        ``content_records`` schema.  ``raw_metadata`` stores the complete
        original resource plus a human-readable ``category_name``.

        Args:
            raw_item: Raw video resource dict from ``videos.list``.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        video_id = raw_item.get("id", "")
        snippet = raw_item.get("snippet", {})
        statistics = raw_item.get("statistics", {})

        url = YOUTUBE_VIDEO_BASE_URL.format(video_id=video_id) if video_id else None
        title = snippet.get("title")
        description = snippet.get("description")
        published_at = snippet.get("publishedAt")
        channel_id = snippet.get("channelId")
        channel_title = snippet.get("channelTitle")
        language = snippet.get("defaultAudioLanguage") or snippet.get("defaultLanguage")

        views_count = self._parse_int(statistics.get("viewCount"))
        likes_count = self._parse_int(statistics.get("likeCount"))
        comments_count = self._parse_int(statistics.get("commentCount"))

        thumbnails = snippet.get("thumbnails", {})
        thumbnail_url = (
            thumbnails.get("high", {}).get("url")
            or thumbnails.get("default", {}).get("url")
        )
        media_urls = [thumbnail_url] if thumbnail_url else []

        category_id = snippet.get("categoryId")
        raw_metadata: dict[str, Any] = {
            **raw_item,
            "category_name": _CATEGORY_NAMES.get(str(category_id)) if category_id else None,
        }

        hash_input = (title or "") + (description or "")
        content_hash = (
            self._normalizer.compute_content_hash(hash_input)
            if hash_input.strip() else None
        )
        pseudonymized_author_id = (
            self._normalizer.pseudonymize_author(
                platform=self.platform_name, platform_user_id=channel_id
            )
            if channel_id else None
        )
        normalized_published_at = self._normalizer._extract_datetime(
            {"published_at": published_at}, ["published_at"]
        )
        collected_at = datetime.now(UTC).isoformat() + "Z"

        # Extract search term matched if present
        search_term = raw_item.get("_search_term")
        search_terms_matched = [search_term] if search_term else []

        # Compute engagement score using platform-specific weights
        engagement_score = self._normalizer.compute_normalized_engagement(
            platform=self.platform_name,
            views=views_count,
            likes=likes_count,
            comments=comments_count,
        )

        return {
            "platform": self.platform_name,
            "arena": self.arena_name,
            "platform_id": video_id or None,
            "content_type": "video",
            "text_content": description,
            "title": title,
            "url": url,
            "language": language,
            "published_at": normalized_published_at,
            "collected_at": collected_at,
            "author_platform_id": channel_id,
            "author_display_name": channel_title,
            "author_id": None,
            "pseudonymized_author_id": pseudonymized_author_id,
            "views_count": views_count,
            "likes_count": likes_count,
            "shares_count": None,  # YouTube API does not expose share count
            "comments_count": comments_count,
            "engagement_score": engagement_score,
            "collection_run_id": None,
            "query_design_id": None,
            "search_terms_matched": search_terms_matched,
            "collection_tier": "free",
            "raw_metadata": raw_metadata,
            "media_urls": media_urls,
            "content_hash": content_hash,
        }

    async def health_check(self) -> dict[str, Any]:
        """Verify YouTube Data API v3 connectivity.

        Calls ``videos.list(id="dQw4w9WgXcQ", part="snippet")`` — 1 quota unit.

        Returns:
            Dict with ``status``, ``arena``, ``platform``, ``checked_at``,
            and optionally ``detail``.
        """
        checked_at = datetime.now(UTC).isoformat() + "Z"
        base: dict[str, Any] = {
            "arena": self.arena_name,
            "platform": self.platform_name,
            "checked_at": checked_at,
        }
        cred: dict[str, Any] | None = None
        if self.credential_pool is not None:
            cred = await self.credential_pool.acquire(
                platform=self.platform_name, tier="free"
            )
        if cred is None:
            return {
                **base,
                "status": "degraded",
                "detail": "No YOUTUBE_FREE_API_KEY credential available.",
            }
        try:
            from issue_observatory.arenas.youtube._client import (
                make_api_request,
            )
            async with httpx.AsyncClient(timeout=10.0) as client:
                data = await make_api_request(
                    client=client,
                    endpoint="videos",
                    params={"id": "dQw4w9WgXcQ", "part": "snippet", "key": cred["api_key"]},
                    credential_pool=self.credential_pool,
                    cred_id=cred["id"],
                )
            if not data.get("items"):
                return {**base, "status": "degraded", "detail": "Empty items in health check response."}
            return {**base, "status": "ok"}
        except ArenaRateLimitError as exc:
            return {**base, "status": "degraded", "detail": f"Quota exhausted: {exc}"}
        except (ArenaAuthError, ArenaCollectionError) as exc:
            return {**base, "status": "degraded", "detail": str(exc)}
        except Exception as exc:
            return {**base, "status": "down", "detail": f"Unexpected error: {exc}"}
        finally:
            if self.credential_pool is not None and cred is not None:
                await self.credential_pool.release(
                    platform=self.platform_name, credential_id=cred["id"]
                )

    async def estimate_credits(
        self,
        terms: list[str] | None = None,
        actor_ids: list[str] | None = None,
        tier: Tier = Tier.FREE,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
    ) -> int:
        """Estimate the monetary credit cost for a YouTube collection run.

        YouTube Data API v3 is free (no monetary cost), so FREE tier
        returns 0 credits.  The API has a daily quota (10,000 units per
        GCP project key), but quota units are not monetary credits.

        Args:
            terms: Search terms (each contributes 100 units/page).
            actor_ids: Channel IDs (RSS free; enrichment 1 unit/50 videos).
            tier: Requested tier.
            date_from: Not used for estimation.
            date_to: Not used for estimation.
            max_results: Upper bound on results.

        Returns:
            Estimated monetary credit cost (0 for FREE tier).
        """
        # YouTube is a free API — no monetary cost for any tier.
        # Quota units are managed internally but are not credits.
        if tier == Tier.FREE:
            return 0
        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run
        total_units = 0
        all_terms = list(terms or [])
        if all_terms:
            pages_per_term = math.ceil(effective_max / MAX_RESULTS_PER_SEARCH_PAGE)
            total_units += len(all_terms) * pages_per_term * QUOTA_COSTS["search.list"]
        total_ids = effective_max * max(len(all_terms), 1)
        if actor_ids:
            total_ids += len(actor_ids) * 15  # up to 15 per RSS feed
        total_units += math.ceil(total_ids / MAX_VIDEO_IDS_PER_BATCH) * QUOTA_COSTS["videos.list"]
        return total_units

    async def collect_comments(
        self,
        post_ids: list[dict[str, Any]],
        tier: Tier,
        max_comments_per_post: int = 100,
        depth: int = 0,
    ) -> list[dict[str, Any]]:
        """Collect comments for YouTube videos using ``commentThreads.list``.

        Fetches top-level comment threads for each video via the YouTube Data
        API v3 ``commentThreads.list`` endpoint (1 quota unit per call).  When
        ``depth`` is greater than zero, replies nested under each top-level
        thread are also included.

        Pagination is performed via ``nextPageToken`` until either
        ``max_comments_per_post`` is reached or the API returns no further
        pages.  Each comment is normalized into the universal content record
        schema with ``content_type="comment"``.

        Args:
            post_ids: List of dicts each containing a ``platform_id`` key
                whose value is a YouTube video ID (e.g. ``"dQw4w9WgXcQ"``).
            tier: Operational tier.  Only ``Tier.FREE`` is supported.
            max_comments_per_post: Maximum comment threads to collect per
                video.  Defaults to 100.
            depth: Depth of reply collection.  ``0`` = top-level threads
                only.  ``1`` = include replies from each thread's
                ``replies.comments`` list (does not issue additional requests
                beyond what ``part=snippet,replies`` returns).

        Returns:
            List of normalized comment record dicts conforming to the
            ``content_records`` universal schema.

        Raises:
            ArenaRateLimitError: On HTTP 403 with ``quotaExceeded``.
            ArenaAuthError: On HTTP 401 or non-quota 403.
            ArenaCollectionError: On other unrecoverable API errors.
            NoCredentialAvailableError: When no API key is available.
        """
        self._validate_tier(tier)
        self._reset_batch_state()

        cred = await self._acquire_credential()

        try:
            async with self._build_http_client() as client:
                from issue_observatory.arenas.youtube._client import (
                    make_api_request,
                )

                for post in post_ids:
                    video_id: str | None = post.get("platform_id")
                    if not video_id:
                        logger.warning(
                            "youtube: collect_comments — skipping entry missing 'platform_id': %s",
                            post,
                        )
                        continue

                    collected_for_video = 0
                    page_token: str | None = None

                    while collected_for_video < max_comments_per_post:
                        remaining = max_comments_per_post - collected_for_video
                        params: dict[str, Any] = {
                            "part": "snippet,replies",
                            "videoId": video_id,
                            "maxResults": min(100, remaining),
                            "key": cred["api_key"],
                        }
                        if page_token:
                            params["pageToken"] = page_token

                        await self._throttle_request(cred["id"])
                        try:
                            data = await make_api_request(
                                client=client,
                                endpoint="commentThreads",
                                params=params,
                                credential_pool=self.credential_pool,
                                cred_id=cred["id"],
                            )
                        except ArenaRateLimitError:
                            if self.credential_pool is not None:
                                await self.credential_pool.release(
                                    credential_id=cred["id"]
                                )
                            logger.warning(
                                "youtube: quota exhausted during collect_comments cred=%s, rotating",
                                cred["id"],
                            )
                            cred = await self._acquire_credential()
                            continue
                        except ArenaCollectionError as exc:
                            # 404 = comments disabled or video deleted; skip this video
                            logger.warning(
                                "youtube: collect_comments — skipping video %s: %s",
                                video_id,
                                exc,
                            )
                            break

                        items: list[dict[str, Any]] = data.get("items", [])
                        page_token = data.get("nextPageToken")

                        for thread in items:
                            if collected_for_video >= max_comments_per_post:
                                break
                            top_snippet = (
                                thread.get("snippet", {})
                                .get("topLevelComment", {})
                                .get("snippet", {})
                            )
                            comment_id: str = (
                                thread.get("snippet", {})
                                .get("topLevelComment", {})
                                .get("id", "")
                            )
                            author_channel_id: str | None = (
                                top_snippet.get("authorChannelId", {}).get("value")
                            )
                            raw_comment: dict[str, Any] = {
                                "_comment_type": "top_level",
                                "id": comment_id,
                                "videoId": video_id,
                                "content_type": "comment",
                                "text": top_snippet.get("textDisplay"),
                                "author_platform_id": author_channel_id,
                                "author_display_name": top_snippet.get(
                                    "authorDisplayName"
                                ),
                                "published_at": top_snippet.get("publishedAt"),
                                "likes_count": self._parse_int(
                                    top_snippet.get("likeCount")
                                ),
                                "parent_post_id": video_id,
                                "url": (
                                    f"https://www.youtube.com/watch?v={video_id}"
                                    f"&lc={comment_id}"
                                ),
                            }
                            try:
                                self._emit(self._normalize_comment(raw_comment))
                                collected_for_video += 1
                            except Exception as exc:
                                logger.warning(
                                    "youtube: normalization failed for comment id=%s: %s",
                                    comment_id,
                                    exc,
                                )

                            if depth > 0:
                                for reply in thread.get("replies", {}).get(
                                    "comments", []
                                ):
                                    if collected_for_video >= max_comments_per_post:
                                        break
                                    reply_snippet = reply.get("snippet", {})
                                    reply_id: str = reply.get("id", "")
                                    reply_author_channel_id: str | None = (
                                        reply_snippet.get("authorChannelId", {}).get(
                                            "value"
                                        )
                                    )
                                    raw_reply: dict[str, Any] = {
                                        "_comment_type": "reply",
                                        "id": reply_id,
                                        "videoId": video_id,
                                        "content_type": "comment",
                                        "text": reply_snippet.get("textDisplay"),
                                        "author_platform_id": reply_author_channel_id,
                                        "author_display_name": reply_snippet.get(
                                            "authorDisplayName"
                                        ),
                                        "published_at": reply_snippet.get(
                                            "publishedAt"
                                        ),
                                        "likes_count": self._parse_int(
                                            reply_snippet.get("likeCount")
                                        ),
                                        "parent_post_id": video_id,
                                        "parent_comment_id": comment_id,
                                        "url": (
                                            f"https://www.youtube.com/watch?v={video_id}"
                                            f"&lc={reply_id}"
                                        ),
                                    }
                                    try:
                                        self._emit(
                                            self._normalize_comment(raw_reply)
                                        )
                                        collected_for_video += 1
                                    except Exception as exc:
                                        logger.warning(
                                            "youtube: normalization failed for reply id=%s: %s",
                                            reply_id,
                                            exc,
                                        )

                        if not page_token or not items:
                            break

                    # Flush after each video so comments are persisted
                    # immediately — the coverage check can then skip this
                    # video on retry.
                    self._flush()

                    logger.debug(
                        "youtube: collect_comments video=%s collected=%d",
                        video_id,
                        collected_for_video,
                    )
        finally:
            if self.credential_pool is not None:
                await self.credential_pool.release(credential_id=cred["id"])

        # Final flush for any stragglers.
        self._flush()

        logger.info(
            "youtube: collect_comments — videos=%d, total_comments=%d, tier=%s",
            len(post_ids),
            self._total_emitted,
            tier.value,
        )
        return list(self._batch_buffer)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_comment(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw YouTube comment dict to the universal schema.

        Builds a universal content record from a comment or reply dict
        produced inside :meth:`collect_comments`.  The ``raw_metadata``
        field stores the original raw dict for downstream use.

        Args:
            raw: Raw comment dict with keys such as ``id``, ``text``,
                ``author_platform_id``, ``published_at``, ``likes_count``,
                ``parent_post_id``, and ``url``.

        Returns:
            Dict conforming to the ``content_records`` universal schema with
            ``content_type="comment"``.
        """
        comment_id: str = raw.get("id", "")
        text: str | None = raw.get("text")
        author_platform_id: str | None = raw.get("author_platform_id")
        published_at_raw: str | None = raw.get("published_at")

        content_hash = (
            self._normalizer.compute_content_hash(text)
            if text and text.strip()
            else None
        )
        pseudonymized_author_id = (
            self._normalizer.pseudonymize_author(
                platform=self.platform_name, platform_user_id=author_platform_id
            )
            if author_platform_id
            else None
        )
        normalized_published_at = self._normalizer._extract_datetime(
            {"published_at": published_at_raw}, ["published_at"]
        )
        collected_at = datetime.now(UTC).isoformat() + "Z"

        # Store parent linkage in raw_metadata — content_records has no
        # parent_post_id column.
        enriched_raw = {**raw}
        enriched_raw["parent_post_id"] = raw.get("parent_post_id")
        if raw.get("parent_comment_id"):
            enriched_raw["parent_comment_id"] = raw["parent_comment_id"]

        return {
            "platform": self.platform_name,
            "arena": self.arena_name,
            "platform_id": comment_id or None,
            "content_type": "comment",
            "text_content": text,
            "title": None,
            "url": raw.get("url"),
            "language": None,
            "published_at": normalized_published_at,
            "collected_at": collected_at,
            "author_platform_id": author_platform_id,
            "author_display_name": raw.get("author_display_name"),
            "author_id": None,
            "pseudonymized_author_id": pseudonymized_author_id,
            "views_count": None,
            "likes_count": raw.get("likes_count"),
            "shares_count": None,
            "comments_count": None,
            "engagement_score": None,
            "collection_run_id": None,
            "query_design_id": None,
            "search_terms_matched": [],
            "collection_tier": "free",
            "raw_metadata": enriched_raw,
            "media_urls": [],
            "content_hash": content_hash,
        }


    async def _enrich_videos(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        cred_id: str,
        video_ids: list[str],
        video_id_to_term: dict[str, str] | None = None,
    ) -> int:
        """Batch-enrich video IDs with full metadata via ``videos.list``.

        Records are emitted incrementally via ``_emit()`` for batch persistence
        during enrichment.

        Args:
            client: Shared HTTP client.
            api_key: YouTube Data API v3 key.
            cred_id: Credential identifier for rate-limit throttling.
            video_ids: Video IDs to enrich (batched into groups of 50).
            video_id_to_term: Optional mapping from video ID to search term.

        Returns:
            Number of records emitted.
        """
        if not video_ids:
            return 0
        collected = 0
        for i in range(0, len(video_ids), MAX_VIDEO_IDS_PER_BATCH):
            batch = video_ids[i : i + MAX_VIDEO_IDS_PER_BATCH]
            await self._throttle_request(cred_id)
            items = await fetch_videos_batch(
                client=client,
                api_key=api_key,
                credential_pool=self.credential_pool,
                cred_id=cred_id,
                video_ids=batch,
            )
            for item in items:
                try:
                    # Mark item with search term if available
                    if video_id_to_term and item.get("id") in video_id_to_term:
                        item["_search_term"] = video_id_to_term[item["id"]]
                    self._emit(self.normalize(item))
                    collected += 1
                except Exception as exc:
                    logger.warning(
                        "youtube: normalization failed for video id=%s: %s",
                        item.get("id"), exc,
                    )
        return collected

    async def _throttle_request(self, key_suffix: str) -> None:
        """Gate a request through the rate limiter if one is injected.

        Args:
            key_suffix: Credential ID used as the rate-limit key suffix.
        """
        if self.rate_limiter is None:
            return
        rate_key = f"ratelimit:{self.arena_name}:{self.platform_name}:{key_suffix}"
        await self.rate_limiter.wait_for_slot(
            key=rate_key,
            max_calls=REQUEST_RATE_MAX_CALLS,
            window_seconds=REQUEST_RATE_WINDOW_SECONDS,
            timeout=60.0,
        )

    async def _acquire_credential(self) -> dict[str, Any]:
        """Acquire a YouTube API key from the credential pool.

        Returns:
            Credential dict with ``id`` and ``api_key`` keys.

        Raises:
            NoCredentialAvailableError: When no credential is available.
        """
        if self.credential_pool is None:
            raise NoCredentialAvailableError(platform=self.platform_name, tier="free")
        cred = await self.credential_pool.acquire(platform=self.platform_name, tier="free")
        if cred is None:
            raise NoCredentialAvailableError(platform=self.platform_name, tier="free")
        return cred

    def _build_http_client(self) -> httpx.AsyncClient:
        """Return an HTTP client for use as an async context manager."""
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]
        return httpx.AsyncClient(timeout=30.0)

    # ------------------------------------------------------------------
    # Static conversion helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_int(value: Any) -> int | None:
        """Convert a value to int, returning None on failure.

        Args:
            value: Value to convert (string, int, or None).

        Returns:
            Integer value, or ``None``.
        """
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _to_iso8601(value: datetime | str) -> str:
        """Convert a datetime or string to an RFC 3339 string.

        Args:
            value: Datetime object or ISO 8601 string.

        Returns:
            RFC 3339 string (suitable for ``publishedAfter``/``publishedBefore``).
        """
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.isoformat().replace("+00:00", "Z")
        s = str(value).strip()
        if s.endswith("+00:00"):
            s = s[:-6] + "Z"
        return s

    @staticmethod
    def _parse_datetime(value: datetime | str | None) -> datetime | None:
        """Parse a datetime or ISO 8601 string to a timezone-aware datetime.

        Args:
            value: Datetime object, ISO 8601 string, or ``None``.

        Returns:
            Timezone-aware :class:`datetime`, or ``None``.
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(str(value), fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt
            except ValueError:
                continue
        return None
