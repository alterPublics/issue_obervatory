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
from datetime import datetime, timezone
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
    DANISH_PARAMS,
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
        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

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
                    page_token: str | None = None
                    while len(all_video_ids) < effective_max:
                        remaining = effective_max - len(all_video_ids)
                        await self._throttle_request(cred["id"])
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
                            danish_params=DANISH_PARAMS,
                        )
                        for video_id in ids:
                            video_id_to_term[video_id] = term
                        all_video_ids.extend(ids)
                        if not page_token or not ids:
                            break

                records = await self._enrich_videos(
                    client=client,
                    api_key=cred["api_key"],
                    cred_id=cred["id"],
                    video_ids=all_video_ids[:effective_max],
                    video_id_to_term=video_id_to_term,
                )
        finally:
            if self.credential_pool is not None:
                await self.credential_pool.release(credential_id=cred["id"])

        logger.info(
            "youtube: collect_by_terms — queries=%d, records=%d, tier=%s",
            len(query_strings), len(records), tier.value,
        )
        return records

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
        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

        date_from_dt = self._parse_datetime(date_from)
        date_to_dt = self._parse_datetime(date_to)
        all_video_ids: list[str] = []

        for channel_id in actor_ids:
            if len(all_video_ids) >= effective_max:
                break
            rss_ids = await poll_channel_rss(
                channel_id=channel_id,
                date_from=date_from_dt,
                date_to=date_to_dt,
            )
            all_video_ids.extend(rss_ids)

        cred = await self._acquire_credential()
        try:
            async with self._build_http_client() as client:
                records = await self._enrich_videos(
                    client=client,
                    api_key=cred["api_key"],
                    cred_id=cred["id"],
                    video_ids=all_video_ids[:effective_max],
                )
        finally:
            if self.credential_pool is not None:
                await self.credential_pool.release(credential_id=cred["id"])

        logger.info(
            "youtube: collect_by_actors — channels=%d, rss_ids=%d, records=%d",
            len(actor_ids), len(all_video_ids), len(records),
        )
        return records

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
        collected_at = datetime.now(timezone.utc).isoformat() + "Z"

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
        checked_at = datetime.now(timezone.utc).isoformat() + "Z"
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
            from issue_observatory.arenas.youtube._client import (  # noqa: PLC0415
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
        except Exception as exc:  # noqa: BLE001
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _enrich_videos(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        cred_id: str,
        video_ids: list[str],
        video_id_to_term: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Batch-enrich video IDs with full metadata via ``videos.list``.

        Args:
            client: Shared HTTP client.
            api_key: YouTube Data API v3 key.
            cred_id: Credential identifier for rate-limit throttling.
            video_ids: Video IDs to enrich (batched into groups of 50).
            video_id_to_term: Optional mapping from video ID to search term.

        Returns:
            List of normalized content record dicts.
        """
        if not video_ids:
            return []
        records: list[dict[str, Any]] = []
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
                    records.append(self.normalize(item))
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "youtube: normalization failed for video id=%s: %s",
                        item.get("id"), exc,
                    )
        return records

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
            from datetime import timezone  # noqa: PLC0415
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
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
            from datetime import timezone  # noqa: PLC0415
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        from datetime import timezone  # noqa: PLC0415
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(str(value), fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        return None
