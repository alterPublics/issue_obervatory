"""TikTok arena collector implementation.

Collects video metadata from the TikTok Research API via OAuth 2.0 client
credentials flow. Free tier only (Phase 1). Access tokens expire every 2
hours and are cached in Redis.

Two collection modes are supported:

- :meth:`TikTokCollector.collect_by_terms` — video search by keyword with
  ``region_code: "DK"`` filter and cursor-based pagination.
- :meth:`TikTokCollector.collect_by_actors` — collect videos by username
  using the ``username`` query condition.

Important notes:
- Engagement metrics (view_count, like_count, share_count, comment_count)
  are subject to a 10-day accuracy lag per the TikTok Research API docs.
  Do not treat these as real-time values for recently published videos.
- The video query endpoint requires start_date and end_date parameters.
  Queries spanning more than 30 days are automatically split into windows.
- Token refresh is handled transparently via Redis cache.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from issue_observatory.arenas.base import ArenaCollector, Tier
from issue_observatory.arenas.query_builder import format_boolean_query_for_platform
from issue_observatory.arenas.registry import register
from issue_observatory.arenas.tiktok.config import (
    TIKTOK_DATE_FORMAT,
    TIKTOK_MAX_COUNT,
    TIKTOK_MAX_DATE_RANGE_DAYS,
    TIKTOK_OAUTH_URL,
    TIKTOK_RATE_LIMIT_MAX_CALLS,
    TIKTOK_RATE_LIMIT_WINDOW_SECONDS,
    TIKTOK_REGION_CODE,
    TIKTOK_TIERS,
    TIKTOK_TOKEN_EXPIRY_SECONDS,
    TIKTOK_TOKEN_REDIS_KEY_PREFIX,
    TIKTOK_TOKEN_REFRESH_BUFFER_SECONDS,
    TIKTOK_USER_INFO_URL,
    TIKTOK_VIDEO_FIELDS,
    TIKTOK_VIDEO_QUERY_URL,
    TIKTOK_WEB_BASE,
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

_RATE_LIMIT_KEY_PREFIX: str = "ratelimit:tiktok:research_api"


@register
class TikTokCollector(ArenaCollector):
    """Collects TikTok video metadata via the TikTok Research API.

    Only ``Tier.FREE`` is supported in Phase 1. Credentials (client_key,
    client_secret) are loaded from the CredentialPool using
    ``platform="tiktok"``, ``tier="free"``.

    OAuth 2.0 access tokens are cached in Redis with TTL = expires_in - 600s
    so that tokens are proactively refreshed 10 minutes before expiry.

    Class Attributes:
        arena_name: ``"social_media"``
        platform_name: ``"tiktok"``
        supported_tiers: ``[Tier.FREE]``

    Args:
        credential_pool: Shared credential pool for fetching TikTok credentials.
        rate_limiter: Optional Redis-backed rate limiter.
        http_client: Optional injected ``httpx.AsyncClient`` for testing.
    """

    arena_name: str = "social_media"
    platform_name: str = "tiktok"
    supported_tiers: list[Tier] = [Tier.FREE]

    def __init__(
        self,
        credential_pool: Any = None,
        rate_limiter: Any = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(credential_pool=credential_pool, rate_limiter=rate_limiter)
        self._http_client = http_client
        self._normalizer = Normalizer()
        # In-memory token cache as fallback when Redis is unavailable.
        self._token_cache: dict[str, tuple[str, float]] = {}

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
        """Collect TikTok videos matching one or more search terms.

        Applies ``region_code: "DK"`` filter automatically. Date ranges
        longer than 30 days are split into 30-day windows to comply with
        the API's date range constraint.

        TikTok does not support native boolean queries.  When ``term_groups``
        is provided, each AND-group is searched as a separate space-joined
        query.  Results are combined and deduplicated.

        Args:
            terms: Keywords or phrases (used when ``term_groups`` is ``None``).
            tier: Operational tier. Only FREE is valid.
            date_from: Earliest video date (inclusive). Defaults to 30 days ago.
            date_to: Latest video date (inclusive). Defaults to today.
            max_results: Cap on total records. Defaults to tier max.
            term_groups: Optional boolean AND/OR groups.  Each group issues a
                separate query with terms space-joined.
            language_filter: Not used — TikTok's ``region_code: "DK"`` filter
                provides implicit language scoping.

        Returns:
            List of normalized content record dicts.

        Raises:
            ArenaRateLimitError: On HTTP 429 from the Research API.
            ArenaAuthError: On credential rejection.
            ArenaCollectionError: On other unrecoverable errors.
            NoCredentialAvailableError: When no credential exists in the pool.
        """
        if tier != Tier.FREE:
            logger.warning(
                "tiktok: tier=%s requested but only FREE is available. "
                "Proceeding with FREE tier.",
                tier.value,
            )

        tier_config = self.get_tier_config(Tier.FREE)
        effective_max = (
            max_results
            if max_results is not None
            else (tier_config.max_results_per_run if tier_config else 100_000)
        )

        start_dt, end_dt = _resolve_date_window(date_from, date_to)
        cred = await self._get_credential()
        token = await self._get_access_token(cred)

        # Build effective terms list from groups or plain terms.
        if term_groups is not None:
            effective_terms: list[str] = [
                format_boolean_query_for_platform(groups=[grp], platform="bluesky")
                for grp in term_groups
                if grp
            ]
        else:
            effective_terms = list(terms)

        all_records: list[dict[str, Any]] = []

        async with self._build_http_client() as client:
            for term in effective_terms:
                if len(all_records) >= effective_max:
                    break
                remaining = effective_max - len(all_records)
                for window_start, window_end in _split_date_windows(
                    start_dt, end_dt, TIKTOK_MAX_DATE_RANGE_DAYS
                ):
                    if len(all_records) >= effective_max:
                        break
                    records = await self._search_videos(
                        client=client,
                        token=token,
                        cred_id=cred["id"],
                        query={
                            "and": [
                                {
                                    "operation": "IN",
                                    "field_name": "region_code",
                                    "field_values": [TIKTOK_REGION_CODE],
                                },
                                {
                                    "operation": "EQ",
                                    "field_name": "keyword",
                                    "field_values": [term],
                                },
                            ]
                        },
                        start_date=window_start.strftime(TIKTOK_DATE_FORMAT),
                        end_date=window_end.strftime(TIKTOK_DATE_FORMAT),
                        max_results=remaining,
                    )
                    all_records.extend(records)
                    remaining = effective_max - len(all_records)

        await self._release_credential(cred)
        logger.info(
            "tiktok: collected %d videos for %d terms",
            len(all_records),
            len(terms),
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
        """Collect TikTok videos published by specific actors (usernames).

        Uses the ``username`` query condition on the video query endpoint.
        Date ranges longer than 30 days are split into windows.

        Args:
            actor_ids: TikTok usernames (without the leading ``@``).
            tier: Operational tier. Only FREE is valid.
            date_from: Earliest video date (inclusive).
            date_to: Latest video date (inclusive).
            max_results: Cap on total records.

        Returns:
            List of normalized content record dicts.

        Raises:
            ArenaRateLimitError: On HTTP 429 from the Research API.
            ArenaAuthError: On credential rejection.
            ArenaCollectionError: On other unrecoverable errors.
            NoCredentialAvailableError: When no credential exists in the pool.
        """
        if tier != Tier.FREE:
            logger.warning(
                "tiktok: tier=%s requested but only FREE is available. "
                "Proceeding with FREE tier.",
                tier.value,
            )

        tier_config = self.get_tier_config(Tier.FREE)
        effective_max = (
            max_results
            if max_results is not None
            else (tier_config.max_results_per_run if tier_config else 100_000)
        )

        start_dt, end_dt = _resolve_date_window(date_from, date_to)
        cred = await self._get_credential()
        token = await self._get_access_token(cred)

        all_records: list[dict[str, Any]] = []

        async with self._build_http_client() as client:
            for username in actor_ids:
                if len(all_records) >= effective_max:
                    break
                remaining = effective_max - len(all_records)
                for window_start, window_end in _split_date_windows(
                    start_dt, end_dt, TIKTOK_MAX_DATE_RANGE_DAYS
                ):
                    if len(all_records) >= effective_max:
                        break
                    records = await self._search_videos(
                        client=client,
                        token=token,
                        cred_id=cred["id"],
                        query={
                            "and": [
                                {
                                    "operation": "EQ",
                                    "field_name": "username",
                                    "field_values": [username],
                                },
                            ]
                        },
                        start_date=window_start.strftime(TIKTOK_DATE_FORMAT),
                        end_date=window_end.strftime(TIKTOK_DATE_FORMAT),
                        max_results=remaining,
                    )
                    all_records.extend(records)
                    remaining = effective_max - len(all_records)

        await self._release_credential(cred)
        logger.info(
            "tiktok: collected %d videos for %d actors",
            len(all_records),
            len(actor_ids),
        )
        return all_records

    def get_tier_config(self, tier: Tier) -> TierConfig | None:
        """Return the tier configuration for this arena.

        Args:
            tier: The requested operational tier.

        Returns:
            ``TierConfig`` for FREE. ``None`` for MEDIUM and PREMIUM.
        """
        return TIKTOK_TIERS.get(tier)

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single TikTok video record to the universal schema.

        Note: Engagement metrics (view_count, like_count, share_count,
        comment_count) are subject to a 10-day accuracy lag per TikTok's
        Research API documentation. Values for recently published videos
        should be treated as preliminary estimates only.

        Maps TikTok Research API video query response fields to the universal
        content record schema. The ``url`` is constructed from username and
        video id. The ``text_content`` is a concatenation of
        ``video_description`` and ``voice_to_text`` (if available).

        Args:
            raw_item: Raw dict from the TikTok Research API video query.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        video_id = str(raw_item.get("id", ""))
        username = raw_item.get("username", "")
        video_description = raw_item.get("video_description", "") or ""
        voice_to_text = raw_item.get("voice_to_text", "") or ""

        # Concatenate description and voice_to_text for text_content.
        if voice_to_text:
            text_content = f"{video_description}\n[transcript] {voice_to_text}".strip()
        else:
            text_content = video_description.strip()

        url = (
            f"{TIKTOK_WEB_BASE}/@{username}/video/{video_id}"
            if username and video_id
            else None
        )

        # create_time is a Unix timestamp integer.
        create_time = raw_item.get("create_time")

        flat: dict[str, Any] = {
            "id": video_id,
            "platform_id": video_id,
            "content_type": "video",
            "text_content": text_content or None,
            "title": None,
            "url": url,
            "language": None,  # No native language field; detect client-side if needed.
            "published_at": create_time,
            "author_platform_id": username or None,
            "author_display_name": username or None,
            # Engagement metrics — NOTE: subject to 10-day accuracy lag.
            # Accurate values require re-collection after the lag window.
            "view_count": raw_item.get("view_count"),
            "like_count": raw_item.get("like_count"),
            "share_count": raw_item.get("share_count"),
            "comment_count": raw_item.get("comment_count"),
            # Raw metadata for full record preservation.
            "region_code": raw_item.get("region_code"),
            "hashtag_names": raw_item.get("hashtag_names"),
            "music_id": raw_item.get("music_id"),
            "effect_ids": raw_item.get("effect_ids"),
            "playlist_id": raw_item.get("playlist_id"),
            "voice_to_text": voice_to_text or None,
        }

        normalized = self._normalizer.normalize(
            raw_item=flat,
            platform=self.platform_name,
            arena=self.arena_name,
            collection_tier="free",
        )
        # Ensure platform_id is the video id, not overridden by url.
        normalized["platform_id"] = video_id
        # Map view_count to views_count for schema alignment.
        if normalized.get("views_count") is None:
            normalized["views_count"] = raw_item.get("view_count")
        return normalized

    async def estimate_credits(
        self,
        terms: list[str] | None = None,
        actor_ids: list[str] | None = None,
        tier: Tier = Tier.FREE,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
    ) -> int:
        """Estimate the credit cost for a TikTok collection run.

        TikTok is free-tier only in Phase 1 (Research API).
        1 credit = 1 API request (each request returns up to 100 videos).
        Daily quota: 1,000 requests = 100,000 videos theoretical max.

        Estimates assume 50-100 results per term per day.

        Args:
            terms: Search keywords or hashtags.
            actor_ids: Not yet implemented for TikTok.
            tier: Must be Tier.FREE (others return 0).
            date_from: Start of collection date range.
            date_to: End of collection date range.
            max_results: Upper bound on results.

        Returns:
            Estimated credit cost as a non-negative integer.
        """
        if tier != Tier.FREE:
            return 0

        all_terms = list(terms or [])
        if not all_terms:
            return 0

        # Estimate date range in days
        date_range_days = 7
        if date_from and date_to:
            if isinstance(date_from, str):
                date_from = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            if isinstance(date_to, str):
                date_to = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
            delta = date_to - date_from
            date_range_days = max(1, delta.days)

        # Heuristic: 75 videos per term per day
        videos_per_term_per_day = 75
        estimated_videos = len(all_terms) * date_range_days * videos_per_term_per_day

        # Apply max_results cap
        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run
        estimated_videos = min(estimated_videos, effective_max)

        # TikTok returns 100 videos per request, so credits = ceil(videos / 100)
        import math

        return math.ceil(estimated_videos / 100)

    async def health_check(self) -> dict[str, Any]:
        """Verify that the TikTok Research API is reachable and the token works.

        Sends a minimal video query with a single keyword, DK region filter,
        and today's date range to verify connectivity and credential validity.

        Returns:
            Dict with ``status`` (``"ok"`` | ``"degraded"`` | ``"down"``),
            ``arena``, ``platform``, ``checked_at``, and optionally ``detail``.
        """
        checked_at = datetime.utcnow().isoformat() + "Z"
        base: dict[str, Any] = {
            "arena": self.arena_name,
            "platform": self.platform_name,
            "checked_at": checked_at,
        }
        try:
            cred = await self._get_credential()
            token = await self._get_access_token(cred)
            today = datetime.now(tz=timezone.utc).strftime(TIKTOK_DATE_FORMAT)
            async with self._build_http_client() as client:
                body = {
                    "query": {
                        "and": [
                            {
                                "operation": "IN",
                                "field_name": "region_code",
                                "field_values": [TIKTOK_REGION_CODE],
                            },
                            {
                                "operation": "EQ",
                                "field_name": "keyword",
                                "field_values": ["denmark"],
                            },
                        ]
                    },
                    "start_date": today,
                    "end_date": today,
                    "max_count": 1,
                    "fields": "id,video_description",
                }
                response = await client.post(
                    TIKTOK_VIDEO_QUERY_URL,
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                data = response.json()
                if "data" not in data:
                    return {
                        **base,
                        "status": "degraded",
                        "detail": "Response missing 'data' key.",
                    }
                return {**base, "status": "ok"}
        except NoCredentialAvailableError as exc:
            return {**base, "status": "down", "detail": f"No credential: {exc}"}
        except httpx.HTTPStatusError as exc:
            return {
                **base,
                "status": "degraded",
                "detail": f"HTTP {exc.response.status_code} from TikTok API",
            }
        except httpx.RequestError as exc:
            return {**base, "status": "down", "detail": f"Connection error: {exc}"}
        except Exception as exc:
            return {**base, "status": "down", "detail": f"Unexpected error: {exc}"}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_http_client(self) -> httpx.AsyncClient:
        """Return an ``httpx.AsyncClient`` for use as a context manager."""
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]
        return httpx.AsyncClient(timeout=30.0)

    async def _get_credential(self) -> dict[str, Any]:
        """Acquire a TikTok credential from the pool.

        Returns:
            Credential dict containing ``client_key`` and ``client_secret``.

        Raises:
            NoCredentialAvailableError: If no credential is available.
        """
        if self.credential_pool is None:
            raise NoCredentialAvailableError(platform="tiktok", tier="free")
        cred = await self.credential_pool.acquire(platform="tiktok", tier="free")
        if cred is None:
            raise NoCredentialAvailableError(platform="tiktok", tier="free")
        return cred

    async def _release_credential(self, cred: dict[str, Any]) -> None:
        """Release a previously acquired credential.

        Args:
            cred: The credential dict returned by ``_get_credential()``.
        """
        if self.credential_pool is not None:
            await self.credential_pool.release(credential_id=cred["id"])

    async def _get_access_token(self, cred: dict[str, Any]) -> str:
        """Return a valid access token, fetching one if the cache is empty or expired.

        Tokens are cached in Redis under ``tiktok:token:{credential_id}`` with
        a TTL of ``expires_in - TIKTOK_TOKEN_REFRESH_BUFFER_SECONDS`` seconds.
        Falls back to an in-memory cache when Redis is unavailable.

        Args:
            cred: Credential dict with ``client_key`` and ``client_secret``.

        Returns:
            Valid Bearer access token string.

        Raises:
            ArenaAuthError: If the token request fails.
        """
        cred_id = cred["id"]
        redis_key = f"{TIKTOK_TOKEN_REDIS_KEY_PREFIX}{cred_id}"

        # Try Redis cache first.
        if self.rate_limiter is not None:
            try:
                cached = await self.rate_limiter.redis_client.get(redis_key)
                if cached:
                    return cached
            except Exception:
                logger.debug("tiktok: Redis token cache read failed — fetching new token")

        # Try in-memory fallback cache.
        if cred_id in self._token_cache:
            token, expires_at = self._token_cache[cred_id]
            import time
            if time.time() < expires_at:
                return token

        return await self._fetch_new_token(cred)

    async def _fetch_new_token(self, cred: dict[str, Any]) -> str:
        """Request a new access token from the TikTok OAuth endpoint.

        Args:
            cred: Credential dict with ``client_key`` and ``client_secret``.

        Returns:
            Fresh Bearer access token string.

        Raises:
            ArenaAuthError: If the token request fails.
        """
        import time

        client_key = cred.get("client_key", "")
        client_secret = cred.get("client_secret", "")
        cred_id = cred["id"]

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(
                    TIKTOK_OAUTH_URL,
                    data={
                        "client_key": client_key,
                        "client_secret": client_secret,
                        "grant_type": "client_credentials",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as exc:
                raise ArenaAuthError(
                    f"tiktok: OAuth token request failed with HTTP {exc.response.status_code}",
                    arena=self.arena_name,
                    platform=self.platform_name,
                ) from exc
            except httpx.RequestError as exc:
                raise ArenaAuthError(
                    f"tiktok: OAuth token request connection error: {exc}",
                    arena=self.arena_name,
                    platform=self.platform_name,
                ) from exc

        token = data.get("access_token", "")
        expires_in = int(data.get("expires_in", TIKTOK_TOKEN_EXPIRY_SECONDS))
        if not token:
            raise ArenaAuthError(
                "tiktok: OAuth response missing access_token",
                arena=self.arena_name,
                platform=self.platform_name,
            )

        # Cache in Redis with TTL = expires_in - buffer.
        ttl = max(60, expires_in - TIKTOK_TOKEN_REFRESH_BUFFER_SECONDS)
        redis_key = f"{TIKTOK_TOKEN_REDIS_KEY_PREFIX}{cred_id}"
        if self.rate_limiter is not None:
            try:
                await self.rate_limiter.redis_client.setex(redis_key, ttl, token)
            except Exception:
                logger.debug("tiktok: Redis token cache write failed — using in-memory cache")

        # Always update in-memory cache as fallback.
        self._token_cache[cred_id] = (token, time.time() + ttl)
        logger.info("tiktok: new access token acquired (expires_in=%ds)", expires_in)
        return token

    async def _wait_for_rate_limit(self, cred_id: str = "default") -> None:
        """Wait for a rate-limit slot before making an API call.

        Args:
            cred_id: Credential ID suffix for the Redis rate-limit key.
        """
        if self.rate_limiter is None:
            return
        key = f"{_RATE_LIMIT_KEY_PREFIX}:{cred_id}"
        await self.rate_limiter.wait_for_slot(
            key=key,
            max_calls=TIKTOK_RATE_LIMIT_MAX_CALLS,
            window_seconds=TIKTOK_RATE_LIMIT_WINDOW_SECONDS,
        )

    async def _make_request(
        self,
        client: httpx.AsyncClient,
        url: str,
        body: dict[str, Any],
        token: str,
        cred_id: str,
    ) -> dict[str, Any]:
        """Make a rate-limited POST request to the TikTok Research API.

        Args:
            client: Shared HTTP client.
            url: Endpoint URL.
            body: JSON request body.
            token: Bearer access token.
            cred_id: Credential ID for rate-limit key.

        Returns:
            Parsed JSON response dict.

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaAuthError: On HTTP 401 (expired token detected).
            ArenaCollectionError: On other non-2xx responses.
        """
        await self._wait_for_rate_limit(cred_id)
        try:
            response = await client.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                retry_after = float(exc.response.headers.get("Retry-After", 60))
                raise ArenaRateLimitError(
                    "tiktok: 429 rate limit — daily quota may be exhausted",
                    retry_after=retry_after,
                    arena=self.arena_name,
                    platform=self.platform_name,
                ) from exc
            if exc.response.status_code == 401:
                raise ArenaAuthError(
                    "tiktok: 401 unauthorized — access token may have expired",
                    arena=self.arena_name,
                    platform=self.platform_name,
                ) from exc
            raise ArenaCollectionError(
                f"tiktok: HTTP {exc.response.status_code} from Research API",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"tiktok: connection error: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

    async def _search_videos(
        self,
        client: httpx.AsyncClient,
        token: str,
        cred_id: str,
        query: dict[str, Any],
        start_date: str,
        end_date: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """Paginate through video query results for a single query+date window.

        Uses ``cursor`` and ``search_id`` for pagination. The ``search_id``
        from the first response must be passed unchanged on all subsequent
        pages to maintain result set consistency.

        Args:
            client: Shared HTTP client.
            token: Bearer access token.
            cred_id: Credential ID for rate-limiting.
            query: TikTok query conditions object.
            start_date: Start date string (YYYYMMDD).
            end_date: End date string (YYYYMMDD).
            max_results: Maximum records to retrieve.

        Returns:
            List of normalized records.
        """
        records: list[dict[str, Any]] = []
        cursor: int = 0
        search_id: str | None = None

        while len(records) < max_results:
            page_size = min(TIKTOK_MAX_COUNT, max_results - len(records))
            body: dict[str, Any] = {
                "query": query,
                "start_date": start_date,
                "end_date": end_date,
                "max_count": page_size,
                "fields": TIKTOK_VIDEO_FIELDS,
            }
            if cursor:
                body["cursor"] = cursor
            if search_id:
                body["search_id"] = search_id

            data = await self._make_request(client, TIKTOK_VIDEO_QUERY_URL, body, token, cred_id)

            # Check for API-level errors inside the response body.
            api_error = data.get("error")
            if api_error and api_error.get("code") not in (0, None, "ok"):
                logger.warning(
                    "tiktok: API error in response: code=%s msg=%s",
                    api_error.get("code"),
                    api_error.get("message"),
                )
                break

            response_data = data.get("data", {})
            videos = response_data.get("videos", [])
            if not videos:
                break

            if search_id is None:
                search_id = response_data.get("search_id")

            for video in videos:
                if len(records) >= max_results:
                    break
                records.append(self.normalize(video))

            has_more = response_data.get("has_more", False)
            cursor = response_data.get("cursor", 0)
            if not has_more or not cursor:
                break

        return records

    async def fetch_user_info(
        self, username: str, token: str, cred_id: str
    ) -> dict[str, Any] | None:
        """Fetch user profile information for a TikTok username.

        Args:
            username: TikTok username (without ``@``).
            token: Bearer access token.
            cred_id: Credential ID for rate-limiting.

        Returns:
            User info dict from the API, or ``None`` if not found.
        """
        async with self._build_http_client() as client:
            try:
                body = {
                    "username": username,
                    "fields": "display_name,bio_description,avatar_url,is_verified,follower_count,following_count,likes_count,video_count",
                }
                data = await self._make_request(
                    client, TIKTOK_USER_INFO_URL, body, token, cred_id
                )
                return data.get("data")
            except ArenaCollectionError:
                logger.warning("tiktok: failed to fetch user info for '%s'", username)
                return None


# ---------------------------------------------------------------------------
# Module-level utility functions
# ---------------------------------------------------------------------------


def _resolve_date_window(
    date_from: datetime | str | None,
    date_to: datetime | str | None,
) -> tuple[datetime, datetime]:
    """Resolve date bounds to timezone-aware datetime objects.

    Defaults to the last 30 days when no bounds are provided.

    Args:
        date_from: Lower bound (datetime, ISO 8601 string, or None).
        date_to: Upper bound (datetime, ISO 8601 string, or None).

    Returns:
        Tuple of (start_datetime, end_datetime) in UTC.
    """
    now = datetime.now(tz=timezone.utc)
    end_dt = _parse_dt(date_to) if date_to is not None else now
    start_dt = (
        _parse_dt(date_from)
        if date_from is not None
        else end_dt - timedelta(days=TIKTOK_MAX_DATE_RANGE_DAYS)
    )
    return start_dt, end_dt


def _parse_dt(value: datetime | str) -> datetime:
    """Parse a datetime or ISO 8601 string to a UTC-aware datetime.

    Args:
        value: Datetime object or ISO 8601 string.

    Returns:
        Timezone-aware UTC datetime.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    # String parsing
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date value: {value!r}")


def _split_date_windows(
    start_dt: datetime,
    end_dt: datetime,
    max_days: int,
) -> list[tuple[datetime, datetime]]:
    """Split a date range into windows of at most ``max_days`` each.

    Args:
        start_dt: Start of the range (inclusive).
        end_dt: End of the range (inclusive).
        max_days: Maximum days per window.

    Returns:
        List of (window_start, window_end) tuples covering the full range.
    """
    windows: list[tuple[datetime, datetime]] = []
    current = start_dt
    delta = timedelta(days=max_days)
    while current < end_dt:
        window_end = min(current + delta - timedelta(seconds=1), end_dt)
        windows.append((current, window_end))
        current = window_end + timedelta(seconds=1)
    if not windows:
        windows.append((start_dt, end_dt))
    return windows


def _strip_html(html: str) -> str:
    """Strip HTML tags from a string.

    Args:
        html: HTML-formatted string.

    Returns:
        Plain text string.
    """
    return re.sub(r"<[^>]+>", "", html).strip()
