"""Instagram arena collector implementation.

Collects public Instagram posts and profile data via two tiers:

- **MEDIUM** (:class:`Tier.MEDIUM`): Bright Data Web Scraper API.
  Polling-based delivery: POST trigger → poll progress → download snapshot.
  Credential: ``platform="brightdata_instagram"``, JSONB ``api_token`` + ``zone``.

- **PREMIUM** (:class:`Tier.PREMIUM`): Meta Content Library (MCL).
  Both collection methods raise ``NotImplementedError`` — MCL integration is
  pending institutional approval. Stubs are in place for future implementation.

**Actor-only collection arena**: Instagram does not expose a public keyword search
API. The Bright Data Web Scraper API does not support keyword or hashtag-based
discovery for Instagram (tested 2026-02-26). This arena collects exclusively via
``collect_by_actors()`` using profile URLs. ``collect_by_terms()`` raises
:exc:`~issue_observatory.core.exceptions.ArenaCollectionError` with guidance.

Default scraper: The Reels scraper (``gd_lyclm20il4r5helnj``) accepts a profile
URL and returns all recent content types (posts and reels). This is preferred over
the Posts scraper (``gd_lk5ns7kz21pck8jpis``), which requires individual post URLs.

Input format::

    [{"url": "https://www.instagram.com/drnyheder/", "num_of_posts": 100,
      "start_date": "01-01-2026", "end_date": "02-26-2026"}]

Date format: ``MM-DD-YYYY`` (Web Scraper API requirement).

Rate limiting:
- Courtesy throttle: 2 calls/sec via :class:`RateLimiter`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx

from issue_observatory.arenas.base import ArenaCollector, TemporalMode, Tier
from issue_observatory.arenas.instagram.config import (
    BRIGHTDATA_MAX_POLL_ATTEMPTS,
    BRIGHTDATA_POLL_INTERVAL,
    BRIGHTDATA_PROGRESS_URL,
    BRIGHTDATA_RATE_LIMIT_MAX_CALLS,
    BRIGHTDATA_RATE_LIMIT_WINDOW_SECONDS,
    BRIGHTDATA_SNAPSHOT_URL,
    INSTAGRAM_DATASET_ID_REELS,
    INSTAGRAM_REEL_MEDIA_TYPES,
    INSTAGRAM_REEL_PRODUCT_TYPES,
    INSTAGRAM_TIERS,
    build_trigger_url,
    to_brightdata_date,
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

_ARENA: str = "social_media"
_PLATFORM: str = "instagram"

# Number of posts to request per actor per API call.
_DEFAULT_NUM_POSTS: int = 100


def _normalize_profile_url(actor_id: str) -> str:
    """Normalize an actor identifier to a full Instagram profile URL.

    Handles three input formats:
    - Full URL: returned as-is (e.g. ``https://www.instagram.com/drnyheder/``)
    - Username with ``@``: strips ``@`` and builds URL
    - Plain username: builds ``https://www.instagram.com/{username}/``

    Args:
        actor_id: Instagram username (with or without ``@``) or full profile URL.

    Returns:
        Full Instagram profile URL string.
    """
    if actor_id.startswith("http"):
        return actor_id
    clean = actor_id.lstrip("@")
    return f"https://www.instagram.com/{clean}/"


@register
class InstagramCollector(ArenaCollector):
    """Collects Instagram posts via Bright Data Web Scraper API (medium) or MCL (premium).

    Instagram is an **actor-only** collection arena — keyword or hashtag-based
    discovery is not supported by the Web Scraper API. ``collect_by_terms()``
    raises :exc:`ArenaCollectionError` with guidance to use the Actor Directory.

    Class Attributes:
        arena_name: ``"social_media"``
        platform_name: ``"instagram"``
        supported_tiers: ``[Tier.MEDIUM, Tier.PREMIUM]``

    Args:
        credential_pool: Shared credential pool. Required for both tiers.
        rate_limiter: Optional Redis-backed rate limiter for courtesy throttling.
        http_client: Optional injected :class:`httpx.AsyncClient` for testing.
    """

    arena_name: str = _ARENA
    platform_name: str = _PLATFORM
    supported_tiers: list[Tier] = [Tier.MEDIUM, Tier.PREMIUM]
    temporal_mode: TemporalMode = TemporalMode.RECENT

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
        """Raise ArenaCollectionError — Instagram does not support keyword search.

        The Bright Data Web Scraper API does not support keyword or hashtag-based
        discovery for Instagram (tested 2026-02-26). To collect from Instagram, add
        profile URLs to the Actor Directory and use ``collect_by_actors()``.

        Args:
            terms: Not used — keyword search is not supported.
            tier: Not used.
            date_from: Not used.
            date_to: Not used.
            max_results: Not used.
            term_groups: Not used.
            language_filter: Not used.

        Raises:
            ArenaCollectionError: Always — Instagram does not support keyword search.
        """
        raise ArenaCollectionError(
            "Instagram does not support keyword-based or hashtag-based collection. "
            "The Bright Data Web Scraper API only supports actor-based collection "
            "(Instagram profile URLs). "
            "To collect from Instagram: add profiles to the Actor Directory "
            "and use actor-based collection mode.",
            arena=_ARENA,
            platform=_PLATFORM,
        )

    async def collect_by_actors(
        self,
        actor_ids: list[str],
        tier: Tier,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect Instagram posts from specific profiles.

        MEDIUM tier: Each actor_id should be an Instagram username (without ``@``)
        or a full profile URL (e.g. ``https://www.instagram.com/drnyheder``).
        Uses the Reels scraper (``gd_lyclm20il4r5helnj``) which accepts profile
        URLs and returns all recent content types (posts and reels).

        PREMIUM tier: Raises ``NotImplementedError`` — MCL pending approval.

        Args:
            actor_ids: Instagram usernames (with or without ``@``) or profile URLs.
            tier: :attr:`Tier.MEDIUM` (Bright Data) or :attr:`Tier.PREMIUM` (MCL stub).
            date_from: Earliest publication date (inclusive). Formatted as ``MM-DD-YYYY``.
            date_to: Latest publication date (inclusive). Formatted as ``MM-DD-YYYY``.
            max_results: Upper bound on returned records across all actors.

        Returns:
            List of normalized content record dicts.

        Raises:
            NotImplementedError: For PREMIUM tier (MCL pending approval).
            ArenaRateLimitError: On HTTP 429 from Bright Data.
            ArenaAuthError: On HTTP 401/403 from Bright Data.
            ArenaCollectionError: On other unrecoverable API errors.
            NoCredentialAvailableError: When no credential is available.
        """
        self._validate_tier(tier)

        if tier == Tier.PREMIUM:
            raise NotImplementedError(
                "Meta Content Library integration pending approval. "
                "PREMIUM tier is not yet operational for the Instagram arena. "
                "Use Tier.MEDIUM (Bright Data) until MCL access is confirmed."
            )

        tier_config = self.get_tier_config(tier)
        effective_max = (
            max_results if max_results is not None
            else (tier_config.max_results_per_run if tier_config else 10_000)
        )

        cred = await self._acquire_medium_credential()
        if cred is None:
            raise NoCredentialAvailableError(platform="brightdata_instagram", tier="medium")

        cred_id: str = cred["id"]
        api_token: str = cred.get("api_token") or cred.get("api_key", "")

        all_records: list[dict[str, Any]] = []

        try:
            async with self._build_http_client() as client:
                for actor_id in actor_ids:
                    if len(all_records) >= effective_max:
                        break
                    remaining = effective_max - len(all_records)
                    profile_url = _normalize_profile_url(actor_id)
                    records = await self._collect_brightdata_profile(
                        client,
                        api_token,
                        cred_id,
                        profile_url,
                        remaining,
                        date_from,
                        date_to,
                    )
                    all_records.extend(records)
        finally:
            if self.credential_pool:
                await self.credential_pool.release(credential_id=cred_id)

        logger.info(
            "instagram: collect_by_actors completed — tier=%s actors=%d records=%d",
            tier.value,
            len(actor_ids),
            len(all_records),
        )
        return all_records

    def get_tier_config(self, tier: Tier) -> TierConfig | None:
        """Return tier configuration for the Instagram arena.

        Args:
            tier: The requested operational tier.

        Returns:
            :class:`TierConfig` for MEDIUM or PREMIUM, or ``None``.

        Raises:
            ValueError: If *tier* is not in ``self.supported_tiers``.
        """
        if tier not in self.supported_tiers:
            raise ValueError(
                f"Tier '{tier.value}' is not supported by InstagramCollector. "
                f"Supported: {[t.value for t in self.supported_tiers]}"
            )
        return INSTAGRAM_TIERS.get(tier)

    def normalize(
        self,
        raw_item: dict[str, Any],
        source: str = "brightdata",
    ) -> dict[str, Any]:
        """Normalize a single Instagram record to the universal content schema.

        Dispatches to :meth:`_parse_brightdata_instagram` for Bright Data
        records or :meth:`_parse_mcl_instagram` for MCL records (stub).

        Args:
            raw_item: Raw post dict from the upstream API.
            source: ``"brightdata"`` for Bright Data, ``"mcl"`` for MCL.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        if source == "mcl":
            flat = self._parse_mcl_instagram(raw_item)
        else:
            flat = self._parse_brightdata_instagram(raw_item)

        normalized = self._normalizer.normalize(
            raw_item=flat,
            platform=self.platform_name,
            arena=self.arena_name,
            collection_tier=source if source in ("medium", "premium") else "medium",
        )
        if flat.get("platform_id"):
            normalized["platform_id"] = flat["platform_id"]
        if flat.get("content_type"):
            normalized["content_type"] = flat["content_type"]
        return normalized

    # ------------------------------------------------------------------
    # Tier-specific collection helpers
    # ------------------------------------------------------------------

    async def _collect_brightdata_profile(
        self,
        client: httpx.AsyncClient,
        api_token: str,
        cred_id: str,
        profile_url: str,
        max_results: int,
        date_from: datetime | str | None,
        date_to: datetime | str | None,
    ) -> list[dict[str, Any]]:
        """Submit a Web Scraper API Reels request for a profile and return records.

        Uses the Reels scraper (``gd_lyclm20il4r5helnj``) which accepts a profile
        URL and returns all content types (posts and reels). This is the primary
        scraper for profile-level Instagram collection.

        Args:
            client: Shared HTTP client.
            api_token: Bright Data API token.
            cred_id: Credential ID for rate limiting.
            profile_url: Full Instagram profile URL (``https://www.instagram.com/...``).
            max_results: Maximum records to return.
            date_from: Date range lower bound (optional, ``MM-DD-YYYY`` format).
            date_to: Date range upper bound (optional, ``MM-DD-YYYY`` format).

        Returns:
            List of normalized Instagram post records.
        """
        await self._wait_rate_limit(cred_id)

        per_actor_limit = min(_DEFAULT_NUM_POSTS, max_results)
        start_date_str = to_brightdata_date(date_from)
        end_date_str = to_brightdata_date(date_to)

        entry: dict[str, Any] = {
            "url": profile_url,
            "num_of_posts": per_actor_limit,
        }
        if start_date_str:
            entry["start_date"] = start_date_str
        if end_date_str:
            entry["end_date"] = end_date_str

        payload: list[dict[str, Any]] = [entry]
        trigger_url = build_trigger_url(INSTAGRAM_DATASET_ID_REELS)
        snapshot_id = await self._trigger_dataset(client, api_token, trigger_url, payload)
        raw_items = await self._poll_and_download(client, api_token, snapshot_id)

        records: list[dict[str, Any]] = []
        for item in raw_items[:max_results]:
            try:
                records.append(self.normalize(item, source="brightdata"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("instagram: normalization error for item: %s", exc)
        return records

    # ------------------------------------------------------------------
    # Normalizer parsing paths
    # ------------------------------------------------------------------

    def _parse_brightdata_instagram(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Parse a Bright Data Web Scraper API Instagram record to a flat dict.

        Maps Web Scraper API field names to the universal content record schema.
        Uses defensive ``.get()`` with fallback chains for schema resilience.

        Web Scraper API field mapping:
        - ``description`` → ``text_content`` (was ``caption`` / ``text``)
        - ``user_posted`` → ``author_display_name`` (was ``owner_username`` / ``username``)
        - ``date_posted`` → ``published_at`` (was ``timestamp`` / ``created_at``)
        - ``likes`` → ``likes_count`` (was ``likes_count``)
        - ``num_comments`` → ``comments_count`` (was ``comments_count``)
        - ``video_view_count`` / ``video_play_count`` → ``views_count``
        - Post URL is extracted from ``url`` field; ``shortcode`` used as fallback ID.

        Args:
            raw: Raw post dict from the Bright Data Web Scraper API (Reels scraper).

        Returns:
            Flat dict for :meth:`Normalizer.normalize`.
        """
        # ID: prefer shortcode, then extract from URL, then numeric id.
        post_url: str | None = raw.get("url")
        shortcode: str = raw.get("shortcode") or ""
        if not shortcode and post_url:
            # Extract shortcode from URL e.g. https://www.instagram.com/p/ABC123/
            parts = [p for p in (post_url or "").split("/") if p]
            if "p" in parts:
                idx = parts.index("p")
                shortcode = parts[idx + 1] if idx + 1 < len(parts) else ""
            elif "reel" in parts:
                idx = parts.index("reel")
                shortcode = parts[idx + 1] if idx + 1 < len(parts) else ""

        post_id: str = shortcode or str(raw.get("id") or "")

        if not post_url and shortcode:
            post_url = f"https://www.instagram.com/p/{shortcode}/"

        # Author: user_posted is the Web Scraper API field; owner_username is legacy.
        username: str = (
            raw.get("user_posted")
            or raw.get("owner_username")
            or raw.get("username")
            or ""
        )
        owner_id: str = str(
            raw.get("owner_id") or raw.get("user_id") or ""
        )

        # Caption text: description is the Web Scraper API field.
        text: str = (
            raw.get("description")
            or raw.get("caption")
            or raw.get("text", "")
        )

        # Content type detection: Reel vs. regular post.
        product_type: str = str(raw.get("product_type") or "").lower()
        media_type: str = str(raw.get("media_type") or "")
        if (
            product_type in INSTAGRAM_REEL_PRODUCT_TYPES
            or media_type in INSTAGRAM_REEL_MEDIA_TYPES
        ):
            content_type: str = "reel"
        else:
            content_type = "post"

        # Published timestamp: date_posted is the Web Scraper API field.
        published_at: str | None = (
            raw.get("date_posted")
            or raw.get("timestamp")
            or raw.get("created_at")
        )

        # Engagement metrics: Web Scraper API uses ``likes`` (not ``likes_count``).
        likes_count: int | None = (
            _extract_int(raw, "likes")
            or _extract_int(raw, "likes_count")
        )
        comments_count: int | None = (
            _extract_int(raw, "num_comments")
            or _extract_int(raw, "comments_count")
            or _extract_int(raw, "comments")
        )
        shares_count: int | None = None  # Instagram does not expose share counts.
        views_count: int | None = (
            _extract_int(raw, "video_view_count")
            or _extract_int(raw, "video_play_count")
            or _extract_int(raw, "views_count")
        )

        # Media URLs: display image, video, and carousel items.
        media_urls: list[str] = _extract_ig_media_urls(raw)

        # Language: Instagram does not provide language metadata natively.
        language: str | None = raw.get("lang") or raw.get("language")

        flat: dict[str, Any] = {
            "platform_id": post_id,
            "id": post_id,
            "content_type": content_type,
            "text_content": text,
            "title": None,  # Instagram posts have no title
            "url": post_url,
            "language": language,
            "published_at": published_at,
            "author_platform_id": owner_id,
            "author_display_name": username,
            "likes_count": likes_count,
            "shares_count": shares_count,
            "comments_count": comments_count,
            "views_count": views_count,
            "media_urls": media_urls,
            # Raw metadata passthrough
            "post_type": product_type or media_type or None,
            "hashtags": raw.get("hashtags") or _extract_hashtags(text),
            "mentions": raw.get("mentions"),
            "location": raw.get("location"),
            "is_sponsored": raw.get("is_sponsored"),
            "carousel_media": raw.get("carousel_media"),
        }
        return flat

    def _parse_mcl_instagram(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Parse a Meta Content Library Instagram post to a flat dict.

        MCL provides richer fields including native view counts, language
        codes, and share counts.

        NOTE: MCL integration is pending approval. This method is implemented
        as a placeholder with field mapping defined in the research brief.

        Args:
            raw: Raw post dict from the MCL API.

        Returns:
            Flat dict for :meth:`Normalizer.normalize`.
        """
        post_id: str = str(raw.get("id", ""))
        creator_id: str = str(raw.get("creator_id", ""))
        creator_name: str = raw.get("creator_name", "")

        text: str = raw.get("caption_text") or ""

        # Determine content type from MCL fields.
        content_type: str = "post"
        if raw.get("media_type") in ("VIDEO", "REEL") or str(
            raw.get("product_type", "")
        ).lower() in INSTAGRAM_REEL_PRODUCT_TYPES:
            content_type = "reel"

        likes_count: int | None = _extract_int(raw, "likes_count")
        shares_count: int | None = _extract_int(raw, "shares_count")
        comments_count: int | None = _extract_int(raw, "comments_count")
        views_count: int | None = _extract_int(raw, "view_count")

        flat: dict[str, Any] = {
            "platform_id": post_id,
            "id": post_id,
            "content_type": content_type,
            "text_content": text,
            "title": None,
            "url": None,  # MCL does not expose public URLs
            "language": raw.get("language"),
            "published_at": raw.get("creation_time"),
            "author_platform_id": creator_id,
            "author_display_name": creator_name,
            "likes_count": likes_count,
            "shares_count": shares_count,
            "comments_count": comments_count,
            "views_count": views_count,
            "media_urls": [],
        }
        return flat

    # ------------------------------------------------------------------
    # Credit estimation
    # ------------------------------------------------------------------

    async def estimate_credits(
        self,
        terms: list[str] | None = None,
        actor_ids: list[str] | None = None,
        tier: Tier = Tier.MEDIUM,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
    ) -> int:
        """Estimate the credit cost for an Instagram actor-based collection run.

        Instagram is an actor-only arena. Term-based estimation is not supported.
        Estimates are based on the number of actors and a posts-per-actor heuristic,
        adjusted by the date range.

        Args:
            terms: Not used — Instagram only supports actor-based collection.
            actor_ids: Instagram profile URLs or usernames to collect from.
            tier: MEDIUM or PREMIUM.
            date_from: Start of collection date range.
            date_to: End of collection date range.
            max_results: Upper bound on results.

        Returns:
            Estimated credit cost as a non-negative integer.
        """
        if tier not in self.supported_tiers:
            return 0

        all_actors = list(actor_ids or [])
        if not all_actors:
            return 0

        # Estimate date range in days.
        date_range_days = 7
        if date_from and date_to:
            if isinstance(date_from, str):
                date_from = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            if isinstance(date_to, str):
                date_to = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
            if isinstance(date_from, datetime) and isinstance(date_to, datetime):
                delta = date_to - date_from
                date_range_days = max(1, delta.days)

        # Heuristic: 15 posts per profile per day (Instagram accounts post less frequently).
        posts_per_actor_per_day = 15
        estimated_posts = len(all_actors) * date_range_days * posts_per_actor_per_day

        # Apply max_results cap.
        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else (
            tier_config.max_results_per_run if tier_config else 10_000
        )
        estimated_posts = min(estimated_posts, effective_max)

        # 1 credit = 1 record collected (Web Scraper API: $0.0015/record).
        return estimated_posts

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """Verify that the Instagram arena can reach the Bright Data API.

        Submits a lightweight request to the Bright Data API to confirm
        token validity and service reachability.

        Returns:
            Dict with ``status`` (``"ok"`` | ``"degraded"`` | ``"down"``),
            ``arena``, ``platform``, ``checked_at``, and optionally ``detail``.
        """
        checked_at = datetime.now(timezone.utc).isoformat() + "Z"
        base: dict[str, Any] = {
            "arena": self.arena_name,
            "platform": self.platform_name,
            "checked_at": checked_at,
        }

        cred = await self._acquire_medium_credential()
        if cred is None:
            return {
                **base,
                "status": "down",
                "detail": "No credentials configured for brightdata_instagram.",
            }

        cred_id: str = cred["id"]
        api_token: str = cred.get("api_token") or cred.get("api_key", "")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                status_url = "https://api.brightdata.com/datasets/v3"
                response = await client.get(
                    status_url,
                    headers={"Authorization": f"Bearer {api_token}"},
                )
                if response.status_code == 429:
                    return {
                        **base,
                        "status": "degraded",
                        "detail": "Bright Data: 429 rate limited",
                        "tier_tested": "medium",
                    }
                if response.status_code in (401, 403):
                    return {
                        **base,
                        "status": "down",
                        "detail": f"Bright Data auth error HTTP {response.status_code}",
                        "tier_tested": "medium",
                    }
                return {**base, "status": "ok", "tier_tested": "medium"}
        except httpx.RequestError as exc:
            return {
                **base,
                "status": "down",
                "detail": f"Bright Data connection error: {exc}",
                "tier_tested": "medium",
            }
        finally:
            if self.credential_pool:
                await self.credential_pool.release(credential_id=cred_id)

    # ------------------------------------------------------------------
    # Bright Data low-level HTTP helpers
    # ------------------------------------------------------------------

    async def _trigger_dataset(
        self,
        client: httpx.AsyncClient,
        api_token: str,
        trigger_url: str,
        payload: list[dict[str, Any]],
    ) -> str:
        """POST a Web Scraper API trigger request and return the snapshot_id.

        Args:
            client: Shared HTTP client.
            api_token: Bright Data API token.
            trigger_url: Full trigger URL (including dataset_id query parameter).
            payload: Request body — list of URL input dicts.

        Returns:
            Snapshot ID string for polling.

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaAuthError: On HTTP 401/403.
            ArenaCollectionError: On other non-2xx or connection errors.
        """
        try:
            response = await client.post(
                trigger_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                },
            )
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 60))
                raise ArenaRateLimitError(
                    "instagram: Bright Data 429 rate limit on trigger",
                    retry_after=retry_after,
                    arena=self.arena_name,
                    platform=self.platform_name,
                )
            if response.status_code in (401, 403):
                raise ArenaAuthError(
                    f"instagram: Bright Data auth error HTTP {response.status_code}",
                    arena=self.arena_name,
                    platform=self.platform_name,
                )
            response.raise_for_status()
            data = response.json()
            snapshot_id: str | None = data.get("snapshot_id") or data.get("id")
            if not snapshot_id:
                raise ArenaCollectionError(
                    "instagram: Bright Data trigger returned no snapshot_id",
                    arena=self.arena_name,
                    platform=self.platform_name,
                )
            logger.debug("instagram: dataset triggered, snapshot_id=%s", snapshot_id)
            return snapshot_id
        except (ArenaRateLimitError, ArenaAuthError, ArenaCollectionError):
            raise
        except httpx.HTTPStatusError as exc:
            raise ArenaCollectionError(
                f"instagram: Bright Data trigger HTTP {exc.response.status_code}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"instagram: Bright Data trigger connection error: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

    async def _poll_and_download(
        self,
        client: httpx.AsyncClient,
        api_token: str,
        snapshot_id: str,
    ) -> list[dict[str, Any]]:
        """Poll Bright Data until the snapshot is ready, then download results.

        Polls every :data:`BRIGHTDATA_POLL_INTERVAL` seconds for up to
        :data:`BRIGHTDATA_MAX_POLL_ATTEMPTS` attempts (~20 minutes).

        Args:
            client: Shared HTTP client.
            api_token: Bright Data API token.
            snapshot_id: The snapshot to wait for.

        Returns:
            List of raw post dicts from the Bright Data snapshot.

        Raises:
            ArenaCollectionError: If delivery times out or download fails.
        """
        headers = {"Authorization": f"Bearer {api_token}"}
        progress_url = BRIGHTDATA_PROGRESS_URL.format(snapshot_id=snapshot_id)
        snapshot_url = BRIGHTDATA_SNAPSHOT_URL.format(snapshot_id=snapshot_id)

        for attempt in range(1, BRIGHTDATA_MAX_POLL_ATTEMPTS + 1):
            try:
                prog_response = await client.get(progress_url, headers=headers)
                prog_response.raise_for_status()
                prog_data = prog_response.json()
                status: str = prog_data.get("status", "")

                logger.debug(
                    "instagram: snapshot=%s status=%s attempt=%d/%d",
                    snapshot_id,
                    status,
                    attempt,
                    BRIGHTDATA_MAX_POLL_ATTEMPTS,
                )

                if status == "ready":
                    break
                if status in ("failed", "error"):
                    raise ArenaCollectionError(
                        f"instagram: Bright Data snapshot {snapshot_id} failed: {prog_data}",
                        arena=self.arena_name,
                        platform=self.platform_name,
                    )
            except (ArenaCollectionError, ArenaRateLimitError):
                raise
            except httpx.RequestError as exc:
                logger.warning("instagram: progress poll error (attempt %d): %s", attempt, exc)

            if attempt < BRIGHTDATA_MAX_POLL_ATTEMPTS:
                await asyncio.sleep(BRIGHTDATA_POLL_INTERVAL)
        else:
            raise ArenaCollectionError(
                f"instagram: Bright Data snapshot {snapshot_id} delivery timed out "
                f"after {BRIGHTDATA_MAX_POLL_ATTEMPTS * BRIGHTDATA_POLL_INTERVAL}s",
                arena=self.arena_name,
                platform=self.platform_name,
            )

        # Download the snapshot.
        try:
            dl_response = await client.get(snapshot_url, headers=headers)
            dl_response.raise_for_status()
            raw_items: list[dict[str, Any]] = dl_response.json()
            if not isinstance(raw_items, list):
                raw_items = raw_items.get("data", []) if isinstance(raw_items, dict) else []
            logger.info(
                "instagram: snapshot=%s downloaded %d items", snapshot_id, len(raw_items)
            )
            return raw_items
        except httpx.HTTPStatusError as exc:
            raise ArenaCollectionError(
                f"instagram: Bright Data snapshot download HTTP {exc.response.status_code}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"instagram: Bright Data snapshot download connection error: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

    # ------------------------------------------------------------------
    # Rate limit helpers
    # ------------------------------------------------------------------

    async def _wait_rate_limit(self, credential_id: str) -> None:
        """Wait for a rate-limit slot before a Bright Data API call.

        Applies a courtesy 2 calls/sec throttle to avoid cost bursts.

        Args:
            credential_id: Credential ID used as the Redis key suffix.
        """
        if self.rate_limiter is None:
            return
        key = f"ratelimit:{self.arena_name}:{self.platform_name}:{credential_id}"
        await self.rate_limiter.wait_for_slot(
            key=key,
            max_calls=BRIGHTDATA_RATE_LIMIT_MAX_CALLS,
            window_seconds=BRIGHTDATA_RATE_LIMIT_WINDOW_SECONDS,
        )

    # ------------------------------------------------------------------
    # Credential acquisition helpers
    # ------------------------------------------------------------------

    async def _acquire_medium_credential(self) -> dict[str, Any] | None:
        """Acquire a Bright Data Instagram credential from the pool.

        Returns:
            Credential dict or ``None`` if unavailable.
        """
        if self.credential_pool is None:
            return None
        return await self.credential_pool.acquire(
            platform="brightdata_instagram", tier="medium"
        )

    # ------------------------------------------------------------------
    # HTTP client builder
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def _build_http_client(self) -> AsyncIterator[httpx.AsyncClient]:
        """Async context manager yielding an HTTP client.

        Yields the injected client directly (for testing, without re-entering);
        otherwise creates a new client with a generous timeout.
        """
        if self._http_client is not None:
            yield self._http_client
            return
        async with httpx.AsyncClient(timeout=60.0) as client:
            yield client


# ---------------------------------------------------------------------------
# Module-level utility functions
# ---------------------------------------------------------------------------


def _extract_int(raw: dict[str, Any], key: str) -> int | None:
    """Extract an integer value from a raw dict, returning None if missing.

    Args:
        raw: Source dict.
        key: Key to look up.

    Returns:
        Integer value or ``None``.
    """
    value = raw.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_ig_media_urls(raw: dict[str, Any]) -> list[str]:
    """Extract all media URLs from a Bright Data Instagram post object.

    Handles single images, videos, and carousel (multi-media) posts.
    Covers both Web Scraper API and legacy Dataset field names.

    Args:
        raw: Raw post dict from Bright Data.

    Returns:
        List of media URL strings (may be empty).
    """
    urls: list[str] = []

    # Primary display image or video.
    for field in ("display_url", "video_url", "thumbnail_url", "image_url"):
        value = raw.get(field)
        if isinstance(value, str) and value:
            urls.append(value)

    # Carousel items (up to 10 per post).
    carousel = raw.get("carousel_media") or []
    if isinstance(carousel, list):
        for item in carousel:
            if isinstance(item, dict):
                for field in ("display_url", "video_url"):
                    src = item.get(field)
                    if isinstance(src, str) and src:
                        urls.append(src)
                        break

    return list(dict.fromkeys(urls))  # deduplicate while preserving order


def _extract_hashtags(text: str) -> list[str]:
    """Extract hashtag strings from caption text.

    Args:
        text: Caption or post text.

    Returns:
        List of hashtag strings without leading ``#``.
    """
    if not text:
        return []
    import re  # noqa: PLC0415

    return re.findall(r"#(\w+)", text)
