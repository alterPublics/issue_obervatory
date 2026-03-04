"""Facebook arena collector implementation.

Collects public Facebook posts via two tiers:

- **MEDIUM** (:class:`Tier.MEDIUM`): Bright Data Web Scraper API.
  Asynchronous delivery: POST trigger → poll progress → download snapshot.
  Credential: ``platform="brightdata_facebook"``, JSONB ``api_token`` + ``zone``.

- **PREMIUM** (:class:`Tier.PREMIUM`): Meta Content Library (MCL).
  Both collection methods raise ``NotImplementedError`` — MCL integration is
  pending institutional approval. Stubs are in place for future implementation.

**Actor-only collection arena**: Facebook and Instagram do not expose a public
keyword search API. The Bright Data Web Scraper API does not support keyword-
based discovery (tested 2026-02-26). These arenas collect exclusively via
``collect_by_actors()`` — researchers must curate Facebook pages, groups, or
profiles in the Actor Directory. ``collect_by_terms()`` raises
:exc:`~issue_observatory.core.exceptions.ArenaCollectionError` with guidance.

Dataset routing (Web Scraper API):
- Facebook page/profile URL → Posts scraper (``gd_lkaxegm826bjpoo9m5``)
- Facebook group URL (contains ``/groups/``) → Groups scraper (``gd_lz11l67o2cb3r0lkj3``)

Input format::

    [{"url": "https://www.facebook.com/drnyheder", "num_of_posts": 100,
      "start_date": "01-01-2026", "end_date": "02-26-2026"}]

Date format: ``MM-DD-YYYY`` (Web Scraper API requirement).

Rate limiting:
- Courtesy throttle: 2 calls/sec via :class:`RateLimiter`.
  Bright Data handles proxy rotation internally; this prevents cost bursts.
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
from issue_observatory.arenas.facebook.config import (
    BRIGHTDATA_MAX_POLL_ATTEMPTS,
    BRIGHTDATA_POLL_INTERVAL,
    BRIGHTDATA_PROGRESS_URL,
    BRIGHTDATA_RATE_LIMIT_MAX_CALLS,
    BRIGHTDATA_RATE_LIMIT_WINDOW_SECONDS,
    BRIGHTDATA_SNAPSHOT_URL,
    FACEBOOK_DATASET_ID_GROUPS,
    FACEBOOK_DATASET_ID_POSTS,
    FACEBOOK_TIERS,
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
_PLATFORM: str = "facebook"

# Number of posts to request per actor per API call.
_DEFAULT_NUM_POSTS: int = 100


def _detect_facebook_dataset_id(url: str) -> str:
    """Select the correct Web Scraper dataset ID based on the Facebook URL type.

    Facebook group URLs contain ``/groups/`` in the path and are routed to the
    Groups scraper. All other URLs (pages, profiles) use the Posts scraper.

    Args:
        url: Facebook page, profile, or group URL.

    Returns:
        Bright Data dataset ID string — either :data:`FACEBOOK_DATASET_ID_GROUPS`
        or :data:`FACEBOOK_DATASET_ID_POSTS`.
    """
    if "/groups/" in url:
        return FACEBOOK_DATASET_ID_GROUPS
    return FACEBOOK_DATASET_ID_POSTS


@register
class FacebookCollector(ArenaCollector):
    """Collects Facebook posts via Bright Data Web Scraper API (medium) or MCL (premium).

    Facebook and Instagram are **actor-only** collection arenas — they do not
    support keyword-based discovery. ``collect_by_terms()`` raises
    :exc:`ArenaCollectionError` with guidance to use the Actor Directory instead.

    Class Attributes:
        arena_name: ``"social_media"``
        platform_name: ``"facebook"``
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
    # Actor-only arena: keyword search is not supported by the Bright Data API.
    # The orchestration layer will dispatch collect_by_actors() instead.
    supports_term_search: bool = False

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
        """Raise ArenaCollectionError — Facebook does not support keyword search.

        The Bright Data Web Scraper API does not support keyword-based discovery
        for Facebook (tested 2026-02-26). To collect from Facebook, add pages,
        groups, or profiles to the Actor Directory and use ``collect_by_actors()``.

        Args:
            terms: Not used — keyword search is not supported.
            tier: Not used.
            date_from: Not used.
            date_to: Not used.
            max_results: Not used.
            term_groups: Not used.
            language_filter: Not used.

        Raises:
            ArenaCollectionError: Always — Facebook does not support keyword search.
        """
        raise ArenaCollectionError(
            "Facebook does not support keyword-based collection. "
            "The Bright Data Web Scraper API only supports actor-based collection "
            "(Facebook page URLs, group URLs, or profile URLs). "
            "To collect from Facebook: add pages or groups to the Actor Directory "
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
        """Collect Facebook posts from specific pages, groups, or profiles.

        MEDIUM tier: Builds a Web Scraper API payload targeting specific Facebook
        page URLs, group URLs, or profile URLs. Each actor_id should be a full
        Facebook URL (e.g. ``https://www.facebook.com/drnyheder`` for pages or
        ``https://www.facebook.com/groups/politikdanmark`` for groups).

        Dataset routing:
        - URLs containing ``/groups/`` → Groups scraper (``gd_lz11l67o2cb3r0lkj3``)
        - All other URLs → Posts scraper (``gd_lkaxegm826bjpoo9m5``)

        Multiple content types are handled in a single call by grouping actor_ids
        by their detected dataset ID and issuing one request per dataset.

        PREMIUM tier: Raises ``NotImplementedError`` — MCL pending approval.

        Args:
            actor_ids: Facebook page URLs, group URLs, or profile URLs.
                Each should be a full ``https://www.facebook.com/...`` URL.
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
                "PREMIUM tier is not yet operational for the Facebook arena. "
                "Use Tier.MEDIUM (Bright Data) until MCL access is confirmed."
            )

        tier_config = self.get_tier_config(tier)
        effective_max = (
            max_results if max_results is not None
            else (tier_config.max_results_per_run if tier_config else 10_000)
        )

        cred = await self._acquire_medium_credential()
        if cred is None:
            raise NoCredentialAvailableError(platform="brightdata_facebook", tier="medium")

        cred_id: str = cred["id"]
        api_token: str = cred.get("api_token") or cred.get("api_key", "")

        # Group actor_ids by dataset ID so each content type gets one request.
        dataset_groups: dict[str, list[str]] = {}
        for actor_id in actor_ids:
            dataset_id = _detect_facebook_dataset_id(actor_id)
            dataset_groups.setdefault(dataset_id, []).append(actor_id)

        all_records: list[dict[str, Any]] = []

        try:
            async with self._build_http_client() as client:
                for dataset_id, urls in dataset_groups.items():
                    if len(all_records) >= effective_max:
                        break
                    remaining = effective_max - len(all_records)
                    records = await self._collect_brightdata_actors(
                        client,
                        api_token,
                        cred_id,
                        dataset_id,
                        urls,
                        remaining,
                        date_from,
                        date_to,
                    )
                    all_records.extend(records)
        finally:
            if self.credential_pool:
                await self.credential_pool.release(credential_id=cred_id)

        logger.info(
            "facebook: collect_by_actors completed — tier=%s actors=%d records=%d",
            tier.value,
            len(actor_ids),
            len(all_records),
        )
        return all_records

    def get_tier_config(self, tier: Tier) -> TierConfig | None:
        """Return tier configuration for the Facebook arena.

        Args:
            tier: The requested operational tier.

        Returns:
            :class:`TierConfig` for MEDIUM or PREMIUM, or ``None``.

        Raises:
            ValueError: If *tier* is not in ``self.supported_tiers``.
        """
        if tier not in self.supported_tiers:
            raise ValueError(
                f"Tier '{tier.value}' is not supported by FacebookCollector. "
                f"Supported: {[t.value for t in self.supported_tiers]}"
            )
        return FACEBOOK_TIERS.get(tier)

    def normalize(
        self,
        raw_item: dict[str, Any],
        source: str = "brightdata",
    ) -> dict[str, Any]:
        """Normalize a single Facebook record to the universal content schema.

        Dispatches to :meth:`_parse_brightdata_facebook` for Bright Data
        records or :meth:`_parse_mcl_facebook` for MCL records (stub).

        Args:
            raw_item: Raw post dict from the upstream API.
            source: ``"brightdata"`` for Bright Data, ``"mcl"`` for MCL.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        if source == "mcl":
            flat = self._parse_mcl_facebook(raw_item)
        else:
            flat = self._parse_brightdata_facebook(raw_item)

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

    async def _collect_brightdata_actors(
        self,
        client: httpx.AsyncClient,
        api_token: str,
        cred_id: str,
        dataset_id: str,
        urls: list[str],
        max_results: int,
        date_from: datetime | str | None,
        date_to: datetime | str | None,
    ) -> list[dict[str, Any]]:
        """Submit a Web Scraper API request targeting Facebook URLs and return records.

        Builds a list payload where each entry specifies a URL, a post count
        cap, and optional date bounds. All URLs share the same dataset ID (and
        therefore the same scraper type — Posts or Groups).

        Args:
            client: Shared HTTP client.
            api_token: Bright Data API token.
            cred_id: Credential ID for rate limiting.
            dataset_id: Bright Data dataset ID (Posts or Groups scraper).
            urls: List of Facebook page/group URLs to collect from.
            max_results: Maximum total records to return.
            date_from: Date range lower bound (optional, ``MM-DD-YYYY`` format).
            date_to: Date range upper bound (optional, ``MM-DD-YYYY`` format).

        Returns:
            List of normalized Facebook post records.
        """
        await self._wait_rate_limit(cred_id)

        # Distribute max_results evenly across all URLs; minimum 10 per URL.
        per_actor_limit = max(10, min(_DEFAULT_NUM_POSTS, max_results // max(1, len(urls))))

        start_date_str = to_brightdata_date(date_from)
        end_date_str = to_brightdata_date(date_to)

        payload: list[dict[str, Any]] = []
        for url in urls:
            entry: dict[str, Any] = {
                "url": url,
                "num_of_posts": per_actor_limit,
            }
            if start_date_str:
                entry["start_date"] = start_date_str
            if end_date_str:
                entry["end_date"] = end_date_str
            payload.append(entry)

        trigger_url = build_trigger_url(dataset_id)
        snapshot_id = await self._trigger_dataset(client, api_token, trigger_url, payload)
        raw_items = await self._poll_and_download(client, api_token, snapshot_id)

        records: list[dict[str, Any]] = []
        for item in raw_items[:max_results]:
            try:
                records.append(self.normalize(item, source="brightdata"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("facebook: normalization error for item: %s", exc)
        return records

    # ------------------------------------------------------------------
    # Normalizer parsing paths
    # ------------------------------------------------------------------

    def _parse_brightdata_facebook(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Parse a Bright Data Web Scraper API Facebook record to a flat dict.

        Maps Web Scraper API field names to the universal content record schema.
        Uses defensive ``.get()`` with fallback chains to handle schema variations
        across Posts, Groups, and Reels scrapers.

        Web Scraper API field mapping:
        - ``content`` → ``text_content`` (was ``message`` / ``description``)
        - ``user_url`` → ``author_platform_id`` (was ``page_id``)
        - ``page_name`` → ``author_display_name`` (unchanged)
        - ``date_posted`` → ``published_at`` (was ``created_time`` / ``date``)
        - ``num_likes`` → ``likes_count`` (was ``reactions.total``)
        - ``num_comments`` → ``comments_count`` (was ``comments``)
        - ``attachments`` / ``post_image`` → ``media_urls`` (was ``images``)
        - ``video_view_count`` → ``views_count`` (was ``views``)

        Args:
            raw: Raw post dict from the Bright Data Web Scraper API.

        Returns:
            Flat dict for :meth:`Normalizer.normalize`.
        """
        post_id: str = str(raw.get("post_id") or raw.get("id", ""))

        # Author: user_url replaces page_id in the Web Scraper API.
        author_url: str = str(
            raw.get("user_url") or raw.get("page_id") or raw.get("user_id", "")
        )
        page_name: str = (
            raw.get("page_name") or raw.get("user_name") or raw.get("username", "")
        )

        # Text content: primary field is now ``content``.
        text: str = (
            raw.get("content")
            or raw.get("message")
            or raw.get("description")
            or raw.get("story", "")
        )
        title: str | None = raw.get("name")  # link post title

        # Post URL.
        post_url: str | None = raw.get("url") or raw.get("permalink_url")
        if not post_url and post_id:
            post_url = f"https://www.facebook.com/{post_id}"

        # Published timestamp: primary field is now ``date_posted``.
        published_at: str | None = (
            raw.get("date_posted") or raw.get("created_time") or raw.get("date")
        )

        # Engagement: reactions -> num_likes; comments -> num_comments.
        likes_count: int | None = _extract_int(raw, "num_likes")
        if likes_count is None:
            # Fallback to legacy reactions dict format.
            reactions = raw.get("reactions") or {}
            if isinstance(reactions, dict):
                likes_count = reactions.get("total") or sum(
                    v for k, v in reactions.items() if isinstance(v, int)
                ) or None
            elif isinstance(reactions, (int, float)):
                likes_count = int(reactions)
            else:
                likes_count = _extract_int(raw, "likes")

        comments_count: int | None = (
            _extract_int(raw, "num_comments") or _extract_int(raw, "comments")
        )
        shares_count: int | None = _extract_int(raw, "shares")
        views_count: int | None = _extract_int(raw, "video_view_count") or _extract_int(
            raw, "views"
        )

        # Media URLs: attachments and post_image replace images.
        media_urls: list[str] = _extract_fb_media_urls(raw)

        # Content type.
        content_type: str = "comment" if raw.get("comment_id") else "post"

        # For group posts, use the group name as the display sender so that
        # content is attributed to the community rather than the individual
        # poster.  The original poster name is preserved in raw_metadata.
        is_group_post: bool = "/groups/" in (post_url or "")
        group_name: str = raw.get("group_name") or raw.get("group_title") or ""
        if is_group_post and group_name:
            display_name: str = group_name
        else:
            display_name = page_name

        actual_poster_name: str | None = (
            raw.get("user_name") or raw.get("username") or None
            if is_group_post
            else None
        )

        flat: dict[str, Any] = {
            "platform_id": post_id,
            "id": post_id,
            "content_type": content_type,
            "text_content": text,
            "title": title,
            "url": post_url,
            "language": None,  # No language field — detect downstream
            "published_at": published_at,
            "author_platform_id": author_url,
            "author_display_name": display_name,
            "likes_count": likes_count,
            "shares_count": shares_count,
            "comments_count": comments_count,
            "views_count": views_count,
            "media_urls": media_urls,
            # Raw metadata passthrough fields.
            "post_type": raw.get("post_type") or raw.get("type"),
            "reactions_breakdown": (
                raw.get("reactions") if isinstance(raw.get("reactions"), dict) else None
            ),
            "parent_id": raw.get("parent_id"),
            "group_id": raw.get("group_id"),
            "event_id": raw.get("event_id"),
            "actual_poster_name": actual_poster_name,
        }
        return flat

    def _parse_mcl_facebook(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Parse a Meta Content Library Facebook post to a flat dict.

        MCL provides richer fields than Bright Data: view counts, native
        language codes, detailed engagement breakdowns.

        NOTE: MCL integration is pending approval. This method is implemented
        as a placeholder with field mapping defined in the research brief.

        Args:
            raw: Raw post dict from the MCL API.

        Returns:
            Flat dict for :meth:`Normalizer.normalize`.
        """
        post_id: str = str(raw.get("id", ""))
        page_id: str = str(raw.get("page_id", ""))
        page_name: str = raw.get("page_name", "")

        text: str = raw.get("message") or ""
        title: str | None = raw.get("name")
        post_url: str | None = raw.get("url")

        likes_count: int | None = _extract_int(raw, "reactions_count")
        shares_count: int | None = _extract_int(raw, "shares_count")
        comments_count: int | None = _extract_int(raw, "comments_count")
        views_count: int | None = _extract_int(raw, "view_count")

        flat: dict[str, Any] = {
            "platform_id": post_id,
            "id": post_id,
            "content_type": "post",
            "text_content": text,
            "title": title,
            "url": post_url,
            "language": raw.get("language"),
            "published_at": raw.get("creation_time"),
            "author_platform_id": page_id,
            "author_display_name": page_name,
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
        """Estimate the credit cost for a Facebook actor-based collection run.

        Facebook is an actor-only arena. Term-based estimation is not supported.
        Estimates are based on the number of actors and a configurable posts-per-actor
        heuristic, adjusted by the date range.

        Args:
            terms: Not used — Facebook only supports actor-based collection.
            actor_ids: Facebook page, group, or profile URLs to collect from.
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

        # Heuristic: 20 posts per actor per day (Facebook pages post less frequently).
        posts_per_actor_per_day = 20
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
        """Verify that the Facebook arena can reach the Bright Data API.

        Submits a minimal status request to the Bright Data API base URL
        to confirm that the API token is valid and the service is reachable.

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
                "detail": "No credentials configured for brightdata_facebook.",
            }

        cred_id: str = cred["id"]
        api_token: str = cred.get("api_token") or cred.get("api_key", "")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Check the datasets API availability with a status endpoint.
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
                # 200 or 404 both indicate a reachable API with valid token.
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
                    "facebook: Bright Data 429 rate limit on trigger",
                    retry_after=retry_after,
                    arena=self.arena_name,
                    platform=self.platform_name,
                )
            if response.status_code in (401, 403):
                raise ArenaAuthError(
                    f"facebook: Bright Data auth error HTTP {response.status_code}",
                    arena=self.arena_name,
                    platform=self.platform_name,
                )
            response.raise_for_status()
            data = response.json()
            snapshot_id: str | None = data.get("snapshot_id") or data.get("id")
            if not snapshot_id:
                raise ArenaCollectionError(
                    "facebook: Bright Data trigger returned no snapshot_id",
                    arena=self.arena_name,
                    platform=self.platform_name,
                )
            logger.debug("facebook: dataset triggered, snapshot_id=%s", snapshot_id)
            return snapshot_id
        except (ArenaRateLimitError, ArenaAuthError, ArenaCollectionError):
            raise
        except httpx.HTTPStatusError as exc:
            raise ArenaCollectionError(
                f"facebook: Bright Data trigger HTTP {exc.response.status_code}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"facebook: Bright Data trigger connection error: {exc}",
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
                    "facebook: snapshot=%s status=%s attempt=%d/%d",
                    snapshot_id,
                    status,
                    attempt,
                    BRIGHTDATA_MAX_POLL_ATTEMPTS,
                )

                if status == "ready":
                    break
                if status in ("failed", "error"):
                    raise ArenaCollectionError(
                        f"facebook: Bright Data snapshot {snapshot_id} failed: {prog_data}",
                        arena=self.arena_name,
                        platform=self.platform_name,
                    )
            except (ArenaCollectionError, ArenaRateLimitError):
                raise
            except httpx.RequestError as exc:
                logger.warning("facebook: progress poll error (attempt %d): %s", attempt, exc)

            if attempt < BRIGHTDATA_MAX_POLL_ATTEMPTS:
                await asyncio.sleep(BRIGHTDATA_POLL_INTERVAL)
        else:
            raise ArenaCollectionError(
                f"facebook: Bright Data snapshot {snapshot_id} delivery timed out "
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
                # Some Bright Data endpoints wrap in {"data": [...]}
                raw_items = raw_items.get("data", []) if isinstance(raw_items, dict) else []
            logger.info(
                "facebook: snapshot=%s downloaded %d items", snapshot_id, len(raw_items)
            )
            return raw_items
        except httpx.HTTPStatusError as exc:
            raise ArenaCollectionError(
                f"facebook: Bright Data snapshot download HTTP {exc.response.status_code}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"facebook: Bright Data snapshot download connection error: {exc}",
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
        """Acquire a Bright Data Facebook credential from the pool.

        Returns:
            Credential dict or ``None`` if unavailable.
        """
        if self.credential_pool is None:
            return None
        return await self.credential_pool.acquire(
            platform="brightdata_facebook", tier="medium"
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


def _extract_fb_media_urls(raw: dict[str, Any]) -> list[str]:
    """Extract all media URLs from a Bright Data Web Scraper API Facebook record.

    Handles the Web Scraper API field names (``attachments``, ``post_image``)
    as well as legacy Dataset field names (``images``, ``image_url``).

    Args:
        raw: Raw post dict from Bright Data.

    Returns:
        List of media URL strings (may be empty).
    """
    urls: list[str] = []

    # Web Scraper API primary image field.
    post_image = raw.get("post_image")
    if isinstance(post_image, str) and post_image:
        urls.append(post_image)

    # Web Scraper API attachments list (images or video thumbnails).
    attachments = raw.get("attachments") or []
    if isinstance(attachments, list):
        for att in attachments:
            if isinstance(att, dict):
                src = att.get("url") or att.get("src") or att.get("link")
                if isinstance(src, str) and src:
                    urls.append(src)
            elif isinstance(att, str) and att:
                urls.append(att)

    # Legacy field names (Dataset product, kept for backward compatibility).
    for field in ("image_url", "video_url", "full_picture", "picture"):
        value = raw.get(field)
        if isinstance(value, str) and value:
            urls.append(value)

    images = raw.get("images") or []
    if isinstance(images, list):
        for img in images:
            if isinstance(img, dict):
                src = img.get("src") or img.get("url")
                if src:
                    urls.append(src)
            elif isinstance(img, str):
                urls.append(img)

    return list(dict.fromkeys(urls))  # deduplicate while preserving order
