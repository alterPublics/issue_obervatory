"""Instagram arena collector implementation.

Collects public Instagram posts and profile data via two tiers:

- **MEDIUM** (:class:`Tier.MEDIUM`): Bright Data Instagram Scraper API.
  Polling-based delivery: POST trigger → poll progress → download snapshot.
  Credential: ``platform="brightdata_instagram"``, JSONB ``api_token`` + ``zone``.

- **PREMIUM** (:class:`Tier.PREMIUM`): Meta Content Library (MCL).
  Both collection methods raise ``NotImplementedError`` — MCL integration is
  pending institutional approval. Stubs are in place for future implementation.

Danish defaults:
- Instagram has no native language or country filter.
- ``collect_by_terms()`` maps query terms to hashtags and targets Danish hashtags.
- ``collect_by_actors()`` targets known Danish accounts by username.
- Client-side language detection: if the ``lang`` field is present in the raw
  record, it is preserved. Non-Danish records are not filtered out — the caller
  can apply language filtering downstream.

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

from issue_observatory.arenas.base import ArenaCollector, Tier
from issue_observatory.arenas.query_builder import format_boolean_query_for_platform
from issue_observatory.arenas.instagram.config import (
    BRIGHTDATA_INSTAGRAM_POSTS_URL,
    BRIGHTDATA_MAX_POLL_ATTEMPTS,
    BRIGHTDATA_POLL_INTERVAL,
    BRIGHTDATA_PROGRESS_URL,
    BRIGHTDATA_RATE_LIMIT_MAX_CALLS,
    BRIGHTDATA_RATE_LIMIT_WINDOW_SECONDS,
    BRIGHTDATA_SNAPSHOT_URL,
    INSTAGRAM_REEL_MEDIA_TYPES,
    INSTAGRAM_REEL_PRODUCT_TYPES,
    INSTAGRAM_TIERS,
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


@register
class InstagramCollector(ArenaCollector):
    """Collects Instagram posts via Bright Data (medium) or MCL (premium).

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
        """Collect Instagram posts matching one or more search terms or hashtags.

        MEDIUM tier: Maps each term to an Instagram hashtag and submits a
        Bright Data hashtag scraper request. Because Instagram has no native
        full-text search API, terms are converted to hashtags by stripping
        spaces (e.g. ``"klima debat"`` → ``"#klimadebat"``). Terms that are
        already hashtags (start with ``#``) are used as-is.

        Language filtering: Instagram does not tag posts with language metadata.
        The ``lang`` field is passed through if present in the raw data. Use
        ``collect_by_actors()`` for more reliable Danish-language collection.

        PREMIUM tier: Raises ``NotImplementedError`` — MCL pending approval.

        Args:
            terms: Search terms or hashtags to query.
            tier: :attr:`Tier.MEDIUM` (Bright Data) or :attr:`Tier.PREMIUM` (MCL stub).
            date_from: Earliest publication date (inclusive).
            date_to: Latest publication date (inclusive).
            max_results: Upper bound on returned records.

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

        # Build effective terms from groups or use plain list.
        if term_groups is not None:
            effective_terms: list[str] = [
                format_boolean_query_for_platform(groups=[grp], platform="bluesky")
                for grp in term_groups
                if grp
            ]
        else:
            effective_terms = list(terms)

        all_records: list[dict[str, Any]] = []

        try:
            async with self._build_http_client() as client:
                for term in effective_terms:
                    if len(all_records) >= effective_max:
                        break
                    remaining = effective_max - len(all_records)
                    hashtag = _term_to_hashtag(term)
                    records = await self._collect_brightdata_hashtag(
                        client,
                        api_token,
                        cred_id,
                        hashtag,
                        remaining,
                        date_from,
                        date_to,
                    )
                    all_records.extend(records)
        finally:
            if self.credential_pool:
                await self.credential_pool.release(credential_id=cred_id)

        logger.info(
            "instagram: collect_by_terms completed — tier=%s terms=%d records=%d",
            tier.value,
            len(terms),
            len(all_records),
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
        """Collect Instagram posts from specific profiles.

        MEDIUM tier: Each actor_id should be an Instagram username (without ``@``)
        or a full profile URL (e.g. ``https://www.instagram.com/drnyheder``).
        Submits a Bright Data profile scraper request.

        This is the most reliable collection mode for Danish content — target
        known Danish media, political, and organizational accounts.

        PREMIUM tier: Raises ``NotImplementedError`` — MCL pending approval.

        Args:
            actor_ids: Instagram usernames (without ``@``) or profile URLs.
            tier: :attr:`Tier.MEDIUM` (Bright Data) or :attr:`Tier.PREMIUM` (MCL stub).
            date_from: Earliest publication date (inclusive).
            date_to: Latest publication date (inclusive).
            max_results: Upper bound on returned records.

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
                    records = await self._collect_brightdata_profile(
                        client,
                        api_token,
                        cred_id,
                        actor_id,
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

    async def _collect_brightdata_hashtag(
        self,
        client: httpx.AsyncClient,
        api_token: str,
        cred_id: str,
        hashtag: str,
        max_results: int,
        date_from: datetime | str | None,
        date_to: datetime | str | None,
    ) -> list[dict[str, Any]]:
        """Submit a Bright Data Instagram hashtag request and return records.

        Args:
            client: Shared HTTP client.
            api_token: Bright Data API token.
            cred_id: Credential ID for rate limiting.
            hashtag: Instagram hashtag (with or without leading ``#``).
            max_results: Maximum records to return.
            date_from: Date range lower bound (optional).
            date_to: Date range upper bound (optional).

        Returns:
            List of normalized Instagram post records.
        """
        await self._wait_rate_limit(cred_id)

        # Strip leading # for the API payload.
        clean_hashtag = hashtag.lstrip("#")

        payload: dict[str, Any] = {
            "hashtag": clean_hashtag,
            "limit": min(max_results, 500),
        }
        if date_from:
            date_str = _to_date_str(date_from)
            if date_str:
                payload["start_date"] = date_str
        if date_to:
            date_str = _to_date_str(date_to)
            if date_str:
                payload["end_date"] = date_str

        snapshot_id = await self._trigger_dataset(client, api_token, payload)
        raw_items = await self._poll_and_download(client, api_token, snapshot_id)

        records: list[dict[str, Any]] = []
        for item in raw_items[:max_results]:
            try:
                records.append(self.normalize(item, source="brightdata"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("instagram: normalization error for item: %s", exc)
        return records

    async def _collect_brightdata_profile(
        self,
        client: httpx.AsyncClient,
        api_token: str,
        cred_id: str,
        actor_id: str,
        max_results: int,
        date_from: datetime | str | None,
        date_to: datetime | str | None,
    ) -> list[dict[str, Any]]:
        """Submit a Bright Data Instagram profile request and return records.

        Args:
            client: Shared HTTP client.
            api_token: Bright Data API token.
            cred_id: Credential ID for rate limiting.
            actor_id: Instagram username (without ``@``) or profile URL.
            max_results: Maximum records to return.
            date_from: Date range lower bound (optional).
            date_to: Date range upper bound (optional).

        Returns:
            List of normalized Instagram post records.
        """
        await self._wait_rate_limit(cred_id)

        # Build the target specification.
        if actor_id.startswith("http"):
            payload: dict[str, Any] = {
                "profile_url": actor_id,
                "limit": min(max_results, 500),
            }
        else:
            clean_username = actor_id.lstrip("@")
            payload = {
                "username": clean_username,
                "limit": min(max_results, 500),
            }

        if date_from:
            date_str = _to_date_str(date_from)
            if date_str:
                payload["start_date"] = date_str
        if date_to:
            date_str = _to_date_str(date_to)
            if date_str:
                payload["end_date"] = date_str

        snapshot_id = await self._trigger_dataset(client, api_token, payload)
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
        """Parse a Bright Data Instagram post to a flat normalizer-ready dict.

        Detects Reels from ``product_type`` or ``media_type`` fields.
        Constructs the canonical URL from shortcode. Extracts all carousel
        media URLs.

        Args:
            raw: Raw post dict from the Bright Data Instagram dataset.

        Returns:
            Flat dict for :meth:`Normalizer.normalize`.
        """
        # ID and URL construction
        post_id: str = str(raw.get("id") or raw.get("shortcode") or "")
        shortcode: str = raw.get("shortcode") or str(raw.get("id", ""))
        post_url: str | None = None
        if shortcode:
            post_url = f"https://www.instagram.com/p/{shortcode}/"

        # Author fields
        owner_id: str = str(raw.get("owner_id") or raw.get("user_id", ""))
        username: str = raw.get("username") or raw.get("owner_username", "")

        # Caption text
        text: str = raw.get("caption") or raw.get("text", "")

        # Content type detection: Reel vs. regular post
        product_type: str = str(raw.get("product_type") or "").lower()
        media_type: str = str(raw.get("media_type") or "")
        if (
            product_type in INSTAGRAM_REEL_PRODUCT_TYPES
            or media_type in INSTAGRAM_REEL_MEDIA_TYPES
        ):
            content_type: str = "reel"
        else:
            content_type = "post"

        # Engagement metrics
        likes_count: int | None = _extract_int(raw, "likes_count") or _extract_int(raw, "likes")
        comments_count: int | None = _extract_int(raw, "comments_count") or _extract_int(raw, "comments")
        # Instagram does not expose share counts via Bright Data.
        shares_count: int | None = None
        # Video view count for videos and Reels.
        views_count: int | None = _extract_int(raw, "video_view_count") or _extract_int(raw, "views_count")

        published_at: str | None = raw.get("timestamp") or raw.get("created_at")

        # Media URLs: display image, video, and carousel items.
        media_urls: list[str] = _extract_ig_media_urls(raw)

        # Language: Instagram does not provide language metadata natively.
        # Pass through if Bright Data enriches the field; otherwise None.
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
        """Estimate the credit cost for an Instagram collection run.

        Instagram via Bright Data charges per post collected.
        Estimates assume 100-300 posts per term per day.

        Args:
            terms: Search hashtags or keywords.
            actor_ids: Not yet implemented for Instagram.
            tier: MEDIUM or PREMIUM.
            date_from: Start of collection date range.
            date_to: End of collection date range.
            max_results: Upper bound on results.

        Returns:
            Estimated credit cost as a non-negative integer.
        """
        if tier not in self.supported_tiers:
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

        # Heuristic: 150 posts per term per day
        posts_per_term_per_day = 150
        estimated_posts = len(all_terms) * date_range_days * posts_per_term_per_day

        # Apply max_results cap
        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run
        estimated_posts = min(estimated_posts, effective_max)

        # 1 credit = 1 post collected
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
        checked_at = datetime.utcnow().isoformat() + "Z"
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
        payload: dict[str, Any],
    ) -> str:
        """POST a dataset trigger request to Bright Data and return the snapshot_id.

        Args:
            client: Shared HTTP client.
            api_token: Bright Data API token.
            payload: Request body with filter and limit parameters.

        Returns:
            Snapshot ID string for polling.

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaAuthError: On HTTP 401/403.
            ArenaCollectionError: On other non-2xx or connection errors.
        """
        try:
            response = await client.post(
                BRIGHTDATA_INSTAGRAM_POSTS_URL,
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

    Args:
        raw: Raw post dict from Bright Data.

    Returns:
        List of media URL strings (may be empty).
    """
    urls: list[str] = []

    # Primary display image or video.
    for field in ("display_url", "video_url", "thumbnail_url"):
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


def _term_to_hashtag(term: str) -> str:
    """Convert a search term to an Instagram hashtag.

    If the term already starts with ``#``, it is returned as-is.
    Otherwise, spaces are stripped and ``#`` is prepended.

    Args:
        term: Raw search term (e.g. ``"klima debat"`` or ``"#dkpol"``).

    Returns:
        Hashtag string with leading ``#`` (e.g. ``"#klimadebat"``).
    """
    if term.startswith("#"):
        return term
    return "#" + term.replace(" ", "").lower()


def _to_date_str(value: datetime | str | None) -> str | None:
    """Convert a datetime or string to a ``YYYY-MM-DD`` date string.

    Args:
        value: Datetime object, ISO 8601 string, or ``None``.

    Returns:
        Date string in ``YYYY-MM-DD`` format, or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str):
        return value[:10] if len(value) >= 10 else value
    return None
