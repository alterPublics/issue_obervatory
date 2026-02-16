"""Facebook arena collector implementation.

Collects public Facebook posts and page data via two tiers:

- **MEDIUM** (:class:`Tier.MEDIUM`): Bright Data Facebook Datasets.
  Asynchronous dataset delivery: POST trigger → poll progress → download snapshot.
  Credential: ``platform="brightdata_facebook"``, JSONB ``api_token`` + ``zone``.

- **PREMIUM** (:class:`Tier.PREMIUM`): Meta Content Library (MCL).
  Both collection methods raise ``NotImplementedError`` — MCL integration is
  pending institutional approval. Stubs are in place for future implementation.

Danish defaults:
- MEDIUM: ``country="DK"`` filter passed in dataset trigger payload.
- PREMIUM: ``country=DK`` and ``language=da`` parameters (when implemented).

Rate limiting:
- Courtesy throttle: 2 calls/sec via :class:`RateLimiter`.
  Bright Data handles proxy rotation internally; this prevents cost bursts.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from issue_observatory.arenas.base import ArenaCollector, Tier
from issue_observatory.arenas.facebook.config import (
    BRIGHTDATA_FACEBOOK_COUNTRY,
    BRIGHTDATA_MAX_POLL_ATTEMPTS,
    BRIGHTDATA_POLL_INTERVAL,
    BRIGHTDATA_PROGRESS_URL,
    BRIGHTDATA_RATE_LIMIT_MAX_CALLS,
    BRIGHTDATA_RATE_LIMIT_WINDOW_SECONDS,
    BRIGHTDATA_SNAPSHOT_URL,
    BRIGHTDATA_TRIGGER_URL,
    FACEBOOK_TIERS,
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


@register
class FacebookCollector(ArenaCollector):
    """Collects Facebook posts via Bright Data (medium) or MCL (premium).

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
    ) -> list[dict[str, Any]]:
        """Collect Facebook posts matching one or more search terms.

        MEDIUM tier: Submits a Bright Data discover_new dataset request
        with keyword filtering and ``country="DK"`` geo-targeting. Polls
        until delivery, then downloads and normalizes results.

        PREMIUM tier: Raises ``NotImplementedError`` — MCL pending approval.

        Args:
            terms: Search terms or keywords to query.
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

        all_records: list[dict[str, Any]] = []

        try:
            async with self._build_http_client() as client:
                for term in terms:
                    if len(all_records) >= effective_max:
                        break
                    remaining = effective_max - len(all_records)
                    records = await self._collect_brightdata_terms(
                        client,
                        api_token,
                        cred_id,
                        term,
                        remaining,
                        date_from,
                        date_to,
                    )
                    all_records.extend(records)
        finally:
            if self.credential_pool:
                await self.credential_pool.release(credential_id=cred_id)

        logger.info(
            "facebook: collect_by_terms completed — tier=%s terms=%d records=%d",
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
        """Collect Facebook posts from specific pages or user profiles.

        MEDIUM tier: Submits a Bright Data request targeting specific Facebook
        page URLs or page IDs. Each actor_id should be a Facebook page URL
        (e.g. ``https://www.facebook.com/drnyheder``) or a numeric page ID.

        PREMIUM tier: Raises ``NotImplementedError`` — MCL pending approval.

        Args:
            actor_ids: Facebook page URLs or numeric page IDs.
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

        all_records: list[dict[str, Any]] = []

        try:
            async with self._build_http_client() as client:
                for actor_id in actor_ids:
                    if len(all_records) >= effective_max:
                        break
                    remaining = effective_max - len(all_records)
                    records = await self._collect_brightdata_actors(
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

    async def _collect_brightdata_terms(
        self,
        client: httpx.AsyncClient,
        api_token: str,
        cred_id: str,
        term: str,
        max_results: int,
        date_from: datetime | str | None,
        date_to: datetime | str | None,
    ) -> list[dict[str, Any]]:
        """Submit a Bright Data keyword dataset request and return normalized records.

        Implements the full asynchronous dataset delivery cycle:
        trigger → poll until ready → download → normalize.

        Args:
            client: Shared HTTP client.
            api_token: Bright Data API token.
            cred_id: Credential ID for rate limiting.
            term: Keyword or search phrase.
            max_results: Maximum records to return.
            date_from: Date range lower bound (optional).
            date_to: Date range upper bound (optional).

        Returns:
            List of normalized Facebook post records.
        """
        await self._wait_rate_limit(cred_id)

        # Build filter payload for the dataset trigger.
        filters: list[dict[str, Any]] = [
            {"type": "keyword", "value": term},
            {"type": "country", "value": BRIGHTDATA_FACEBOOK_COUNTRY},
        ]
        if date_from:
            date_str = _to_date_str(date_from)
            if date_str:
                filters.append({"type": "date_from", "value": date_str})
        if date_to:
            date_str = _to_date_str(date_to)
            if date_str:
                filters.append({"type": "date_to", "value": date_str})

        payload: dict[str, Any] = {
            "filters": filters,
            "limit": min(max_results, 1000),
        }

        snapshot_id = await self._trigger_dataset(client, api_token, payload)
        raw_items = await self._poll_and_download(client, api_token, snapshot_id)

        records: list[dict[str, Any]] = []
        for item in raw_items[:max_results]:
            try:
                records.append(self.normalize(item, source="brightdata"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("facebook: normalization error for item: %s", exc)
        return records

    async def _collect_brightdata_actors(
        self,
        client: httpx.AsyncClient,
        api_token: str,
        cred_id: str,
        actor_id: str,
        max_results: int,
        date_from: datetime | str | None,
        date_to: datetime | str | None,
    ) -> list[dict[str, Any]]:
        """Submit a Bright Data page-targeted dataset request and return records.

        Targets a specific Facebook page by URL or numeric ID.

        Args:
            client: Shared HTTP client.
            api_token: Bright Data API token.
            cred_id: Credential ID for rate limiting.
            actor_id: Facebook page URL or numeric page ID.
            max_results: Maximum records to return.
            date_from: Date range lower bound (optional).
            date_to: Date range upper bound (optional).

        Returns:
            List of normalized Facebook post records.
        """
        await self._wait_rate_limit(cred_id)

        # Determine if actor_id is a URL or numeric ID.
        if actor_id.startswith("http"):
            target_filter = {"type": "page_url", "value": actor_id}
        else:
            target_filter = {"type": "page_id", "value": actor_id}

        filters: list[dict[str, Any]] = [
            target_filter,
            {"type": "country", "value": BRIGHTDATA_FACEBOOK_COUNTRY},
        ]
        if date_from:
            date_str = _to_date_str(date_from)
            if date_str:
                filters.append({"type": "date_from", "value": date_str})
        if date_to:
            date_str = _to_date_str(date_to)
            if date_str:
                filters.append({"type": "date_to", "value": date_str})

        payload: dict[str, Any] = {
            "filters": filters,
            "limit": min(max_results, 1000),
        }

        snapshot_id = await self._trigger_dataset(client, api_token, payload)
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
        """Parse a Bright Data Facebook post to a flat normalizer-ready dict.

        Maps Bright Data field names to the universal content record schema.
        Reaction totals are mapped to ``likes_count``; the full breakdown is
        preserved in the flat dict for inclusion in ``raw_metadata``.

        Args:
            raw: Raw post dict from the Bright Data Facebook dataset.

        Returns:
            Flat dict for :meth:`Normalizer.normalize`.
        """
        post_id: str = str(raw.get("post_id") or raw.get("id", ""))
        page_id: str = str(raw.get("page_id") or raw.get("user_id", ""))
        page_name: str = raw.get("page_name") or raw.get("user_name", "")

        text: str = raw.get("message") or raw.get("description") or raw.get("story", "")
        title: str | None = raw.get("name")  # link post title

        post_url: str | None = raw.get("url") or raw.get("permalink_url")
        if not post_url and post_id:
            post_url = f"https://www.facebook.com/{post_id}"

        # Reactions: Bright Data may provide total or breakdown dict.
        reactions = raw.get("reactions") or {}
        if isinstance(reactions, dict):
            likes_count: int | None = reactions.get("total") or sum(
                v for k, v in reactions.items() if isinstance(v, int)
            ) or None
        elif isinstance(reactions, (int, float)):
            likes_count = int(reactions)
        else:
            likes_count = raw.get("likes")

        shares_count: int | None = _extract_int(raw, "shares")
        comments_count: int | None = _extract_int(raw, "comments")
        # Facebook via Bright Data does not expose view counts.
        views_count: int | None = None

        published_at: str | None = raw.get("created_time") or raw.get("date")

        # Media URLs
        media_urls: list[str] = _extract_fb_media_urls(raw)

        # Determine content type
        content_type: str = "comment" if raw.get("comment_id") else "post"

        flat: dict[str, Any] = {
            "platform_id": post_id,
            "id": post_id,
            "content_type": content_type,
            "text_content": text,
            "title": title,
            "url": post_url,
            "language": None,  # Bright Data does not provide language; detect downstream
            "published_at": published_at,
            "author_platform_id": page_id,
            "author_display_name": page_name,
            "likes_count": likes_count,
            "shares_count": shares_count,
            "comments_count": comments_count,
            "views_count": views_count,
            "media_urls": media_urls,
            # Raw metadata passthrough fields
            "post_type": raw.get("post_type") or raw.get("type"),
            "reactions_breakdown": reactions if isinstance(reactions, dict) else None,
            "parent_id": raw.get("parent_id"),
            "group_id": raw.get("group_id"),
            "event_id": raw.get("event_id"),
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
                BRIGHTDATA_TRIGGER_URL,
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

    def _build_http_client(self) -> httpx.AsyncClient:
        """Return an :class:`httpx.AsyncClient` for use as a context manager.

        Uses the injected client if provided (for testing), otherwise creates
        a new client with a generous timeout for long-running dataset delivery.

        Returns:
            A new or injected :class:`httpx.AsyncClient`.
        """
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]
        return httpx.AsyncClient(timeout=60.0)


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
    """Extract all media URLs from a Bright Data Facebook post object.

    Checks common field names for image and video URLs.

    Args:
        raw: Raw post dict from Bright Data.

    Returns:
        List of media URL strings (may be empty).
    """
    urls: list[str] = []

    # Single image or video URL fields
    for field in ("image_url", "video_url", "full_picture", "picture"):
        value = raw.get(field)
        if isinstance(value, str) and value:
            urls.append(value)

    # List of image objects
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
