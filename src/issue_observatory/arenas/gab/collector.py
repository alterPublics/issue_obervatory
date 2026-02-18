"""Gab arena collector implementation.

Collects posts from Gab via the Mastodon-compatible REST API at gab.com.
Gab has been operating on a Mastodon fork since July 2019.

Two collection modes are supported:

- :meth:`GabCollector.collect_by_terms` — search by keyword or hashtag.
  Uses ``GET /api/v2/search?q={term}&type=statuses``. If the search endpoint
  returns HTTP 422 (full-text search not enabled), falls back to the hashtag
  timeline endpoint for hashtag-prefixed terms (``#tag``).
- :meth:`GabCollector.collect_by_actors` — collect posts by Gab account ID
  or username. Uses account lookup then paginates via ``max_id``.

Authentication: OAuth 2.0 Bearer token from CredentialPool.
Credentials: ``platform="gab"``, ``tier="free"``,
JSONB: ``{"client_id": "...", "client_secret": "...", "access_token": "..."}``.

Note: Expected Danish-relevant content volume is very low. The primary
research value is cross-platform actor tracking, not volume.

Note: Gab's Mastodon fork may have API deviations from the standard spec.
Flag any discovered deviations during testing.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from issue_observatory.arenas.base import ArenaCollector, Tier
from issue_observatory.arenas.query_builder import format_boolean_query_for_platform
from issue_observatory.arenas.gab.config import (
    GAB_ACCOUNT_LOOKUP_ENDPOINT,
    GAB_ACCOUNT_STATUSES_ENDPOINT,
    GAB_HASHTAG_TIMELINE_ENDPOINT,
    GAB_INSTANCE_ENDPOINT,
    GAB_MAX_RESULTS_PER_PAGE,
    GAB_PUBLIC_TIMELINE_ENDPOINT,
    GAB_RATE_LIMIT_MAX_CALLS,
    GAB_RATE_LIMIT_WINDOW_SECONDS,
    GAB_SEARCH_ENDPOINT,
    GAB_TIERS,
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

_RATE_LIMIT_KEY_PREFIX: str = "ratelimit:gab:api"


@register
class GabCollector(ArenaCollector):
    """Collects posts from Gab via the Mastodon-compatible REST API.

    Only ``Tier.FREE`` is supported — no paid tiers exist for Gab.
    Credentials (access_token) are loaded from the CredentialPool using
    ``platform="gab"``, ``tier="free"``.

    Class Attributes:
        arena_name: ``"social_media"``
        platform_name: ``"gab"``
        supported_tiers: ``[Tier.FREE]``

    Args:
        credential_pool: Shared credential pool for fetching Gab credentials.
        rate_limiter: Optional Redis-backed rate limiter.
        http_client: Optional injected ``httpx.AsyncClient`` for testing.
    """

    arena_name: str = "social_media"
    platform_name: str = "gab"
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
        """Collect Gab posts matching one or more search terms or hashtags.

        Uses ``GET /api/v2/search?q={term}&type=statuses`` for keyword search.
        Falls back to ``GET /api/v1/timelines/tag/{hashtag}`` for hashtag
        terms (those starting with ``#``) if the search endpoint returns 422.

        Gab has no native boolean support.  When ``term_groups`` is provided
        each AND-group is searched as a space-joined phrase.

        Args:
            terms: Keywords or hashtags (used when ``term_groups`` is ``None``).
            tier: Operational tier. Only FREE is valid.
            date_from: Earliest post date (inclusive, client-side filter).
            date_to: Latest post date (inclusive, client-side filter).
            max_results: Cap on total records. Defaults to tier max.
            term_groups: Optional boolean AND/OR groups.  Each group issues
                a separate query with terms space-joined.
            language_filter: Not used — Gab has no language filter parameter.

        Returns:
            List of normalized content record dicts.

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaAuthError: On credential rejection.
            ArenaCollectionError: On other unrecoverable errors.
            NoCredentialAvailableError: When no credential exists.
        """
        if tier != Tier.FREE:
            logger.warning(
                "gab: tier=%s requested but only FREE is available. "
                "Proceeding with FREE tier.",
                tier.value,
            )

        tier_config = self.get_tier_config(Tier.FREE)
        effective_max = (
            max_results
            if max_results is not None
            else (tier_config.max_results_per_run if tier_config else 10_000)
        )

        date_from_dt = _parse_datetime(date_from)
        date_to_dt = _parse_datetime(date_to)

        cred = await self._get_credential()
        token = cred.get("access_token", "")
        if not token:
            raise ArenaAuthError(
                "gab: credential missing 'access_token' field",
                arena=self.arena_name,
                platform=self.platform_name,
            )

        # Build effective terms: one per AND-group (space-joined), or use plain list.
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

                if term.startswith("#"):
                    # Hashtag: try search first, fall back to hashtag timeline.
                    hashtag = term.lstrip("#")
                    records = await self._search_or_hashtag(
                        client=client,
                        token=token,
                        cred_id=cred["id"],
                        term=term,
                        hashtag=hashtag,
                        max_results=remaining,
                        date_from=date_from_dt,
                        date_to=date_to_dt,
                    )
                else:
                    # Plain keyword: use search endpoint.
                    records = await self._search_statuses(
                        client=client,
                        token=token,
                        cred_id=cred["id"],
                        query=term,
                        max_results=remaining,
                        date_from=date_from_dt,
                        date_to=date_to_dt,
                    )
                all_records.extend(records)

        await self._release_credential(cred)
        logger.info(
            "gab: collected %d posts for %d queries",
            len(all_records),
            len(effective_terms),
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
        """Collect Gab posts from specific accounts.

        Actor IDs are Gab account IDs (numeric strings) or usernames.
        If a username is provided, it is resolved to an account ID first.
        Paginates using ``max_id`` (Mastodon ID-based pagination).
        Date filtering is applied client-side.

        Args:
            actor_ids: Gab account IDs or usernames.
            tier: Operational tier. Only FREE is valid.
            date_from: Earliest post date (inclusive, client-side filter).
            date_to: Latest post date (inclusive, client-side filter).
            max_results: Cap on total records.

        Returns:
            List of normalized content record dicts.

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaAuthError: On credential rejection.
            ArenaCollectionError: On other unrecoverable errors.
            NoCredentialAvailableError: When no credential exists.
        """
        if tier != Tier.FREE:
            logger.warning(
                "gab: tier=%s requested but only FREE is available. "
                "Proceeding with FREE tier.",
                tier.value,
            )

        tier_config = self.get_tier_config(Tier.FREE)
        effective_max = (
            max_results
            if max_results is not None
            else (tier_config.max_results_per_run if tier_config else 10_000)
        )

        date_from_dt = _parse_datetime(date_from)
        date_to_dt = _parse_datetime(date_to)

        cred = await self._get_credential()
        token = cred.get("access_token", "")
        if not token:
            raise ArenaAuthError(
                "gab: credential missing 'access_token' field",
                arena=self.arena_name,
                platform=self.platform_name,
            )

        all_records: list[dict[str, Any]] = []

        async with self._build_http_client() as client:
            for actor_id in actor_ids:
                if len(all_records) >= effective_max:
                    break
                remaining = effective_max - len(all_records)

                # Resolve username to account ID if needed.
                account_id = await self._resolve_account_id(
                    client=client, token=token, cred_id=cred["id"], actor_id=actor_id
                )
                if account_id is None:
                    logger.warning("gab: could not resolve account for actor='%s'", actor_id)
                    continue

                records = await self._fetch_account_statuses(
                    client=client,
                    token=token,
                    cred_id=cred["id"],
                    account_id=account_id,
                    max_results=remaining,
                    date_from=date_from_dt,
                    date_to=date_to_dt,
                )
                all_records.extend(records)

        await self._release_credential(cred)
        logger.info(
            "gab: collected %d posts for %d actors",
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
        return GAB_TIERS.get(tier)

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single Gab status to the universal schema.

        Strips HTML from the ``content`` field (Mastodon returns HTML).
        Handles reblogs: if the status is a reblog, uses the original
        content while recording reblog context in raw_metadata.

        Args:
            raw_item: Raw status dict from the Mastodon-compatible API.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        # If this is a reblog, normalize the original status but preserve context.
        reblog = raw_item.get("reblog")
        if reblog and isinstance(reblog, dict):
            base = reblog.copy()
            base["_reblogged_by"] = raw_item.get("account", {}).get("username")
            base["_reblog_created_at"] = raw_item.get("created_at")
        else:
            base = raw_item

        status_id = str(base.get("id", ""))
        content_html = base.get("content", "") or ""
        text_content = _strip_html(content_html)
        url = base.get("url") or base.get("uri") or None
        language = base.get("language") or None
        created_at = base.get("created_at") or None

        account = base.get("account") or {}
        author_id = str(account.get("id", "")) if account else None
        author_display_name = (
            account.get("display_name") or account.get("username") or None
        )

        # Extract media URLs from attachments.
        attachments = base.get("media_attachments") or []
        media_urls = [
            att["url"]
            for att in attachments
            if isinstance(att, dict) and att.get("url")
        ]

        flat: dict[str, Any] = {
            "id": status_id,
            "platform_id": status_id,
            "content_type": "post",
            "text_content": text_content or None,
            "title": None,
            "url": url,
            "language": language,
            "published_at": created_at,
            "author_platform_id": author_id,
            "author_display_name": author_display_name,
            # Engagement metrics.
            "favourites_count": base.get("favourites_count"),
            "reblogs_count": base.get("reblogs_count"),
            "replies_count": base.get("replies_count"),
            # Raw metadata fields preserved in the flat dict.
            "account": account,
            "in_reply_to_id": base.get("in_reply_to_id"),
            "in_reply_to_account_id": base.get("in_reply_to_account_id"),
            "reblog": raw_item.get("reblog"),
            "media_attachments": attachments,
            "mentions": base.get("mentions"),
            "tags": base.get("tags"),
            "emojis": base.get("emojis"),
            "card": base.get("card"),
            "poll": base.get("poll"),
            "sensitive": base.get("sensitive"),
            "spoiler_text": base.get("spoiler_text"),
            "visibility": base.get("visibility"),
            "application": base.get("application"),
            "media_urls": media_urls,
        }

        normalized = self._normalizer.normalize(
            raw_item=flat,
            platform=self.platform_name,
            arena=self.arena_name,
            collection_tier="free",
        )
        normalized["platform_id"] = status_id
        # Map Mastodon engagement fields to schema fields.
        if normalized.get("likes_count") is None:
            normalized["likes_count"] = base.get("favourites_count")
        if normalized.get("shares_count") is None:
            normalized["shares_count"] = base.get("reblogs_count")
        if normalized.get("comments_count") is None:
            normalized["comments_count"] = base.get("replies_count")
        if media_urls:
            normalized["media_urls"] = media_urls
        return normalized

    async def health_check(self) -> dict[str, Any]:
        """Verify that the Gab API is reachable and credentials are valid.

        Tries ``GET /api/v1/timelines/public?limit=1`` first, then falls
        back to ``GET /api/v1/instance`` for server status information.

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
            token = cred.get("access_token", "")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    GAB_PUBLIC_TIMELINE_ENDPOINT,
                    params={"limit": 1},
                    headers={"Authorization": f"Bearer {token}"},
                )
                if response.status_code == 200:
                    return {**base, "status": "ok"}
                # Fall back to instance endpoint.
                inst_response = await client.get(GAB_INSTANCE_ENDPOINT)
                if inst_response.status_code == 200:
                    return {
                        **base,
                        "status": "degraded",
                        "detail": f"Timeline returned {response.status_code}; instance OK.",
                    }
                return {
                    **base,
                    "status": "down",
                    "detail": f"Both timeline ({response.status_code}) and instance ({inst_response.status_code}) failed.",
                }
        except NoCredentialAvailableError as exc:
            return {**base, "status": "down", "detail": f"No credential: {exc}"}
        except httpx.HTTPStatusError as exc:
            return {
                **base,
                "status": "degraded",
                "detail": f"HTTP {exc.response.status_code} from Gab API",
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
        """Acquire a Gab credential from the pool.

        Returns:
            Credential dict with ``access_token``.

        Raises:
            NoCredentialAvailableError: If no credential is available.
        """
        if self.credential_pool is None:
            raise NoCredentialAvailableError(platform="gab", tier="free")
        cred = await self.credential_pool.acquire(platform="gab", tier="free")
        if cred is None:
            raise NoCredentialAvailableError(platform="gab", tier="free")
        return cred

    async def _release_credential(self, cred: dict[str, Any]) -> None:
        """Release a previously acquired credential.

        Args:
            cred: The credential dict returned by ``_get_credential()``.
        """
        if self.credential_pool is not None:
            await self.credential_pool.release(credential_id=cred["id"])

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
            max_calls=GAB_RATE_LIMIT_MAX_CALLS,
            window_seconds=GAB_RATE_LIMIT_WINDOW_SECONDS,
        )

    async def _make_get_request(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, Any],
        token: str,
        cred_id: str,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Make a rate-limited authenticated GET request to the Gab API.

        Args:
            client: Shared HTTP client.
            url: Endpoint URL.
            params: Query parameters.
            token: Bearer access token.
            cred_id: Credential ID for rate-limiting.

        Returns:
            Parsed JSON response (dict or list).

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaAuthError: On HTTP 401.
            ArenaCollectionError: On other non-2xx responses.
        """
        await self._wait_for_rate_limit(cred_id)
        try:
            response = await client.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                retry_after = float(exc.response.headers.get("Retry-After", 60))
                raise ArenaRateLimitError(
                    "gab: 429 rate limit",
                    retry_after=retry_after,
                    arena=self.arena_name,
                    platform=self.platform_name,
                ) from exc
            if exc.response.status_code == 401:
                raise ArenaAuthError(
                    "gab: 401 unauthorized — check access_token in CredentialPool",
                    arena=self.arena_name,
                    platform=self.platform_name,
                ) from exc
            raise ArenaCollectionError(
                f"gab: HTTP {exc.response.status_code} from Gab API: {url}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"gab: connection error: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

    async def _search_statuses(
        self,
        client: httpx.AsyncClient,
        token: str,
        cred_id: str,
        query: str,
        max_results: int,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Search for statuses matching a keyword query.

        Uses offset-based pagination on ``/api/v2/search?type=statuses``.
        Applies client-side date filtering.

        Args:
            client: Shared HTTP client.
            token: Bearer access token.
            cred_id: Credential ID for rate-limiting.
            query: Search query string.
            max_results: Maximum records to retrieve.
            date_from: Client-side lower date filter.
            date_to: Client-side upper date filter.

        Returns:
            List of normalized records.
        """
        records: list[dict[str, Any]] = []
        offset = 0

        while len(records) < max_results:
            page_size = min(GAB_MAX_RESULTS_PER_PAGE, max_results - len(records))
            params: dict[str, Any] = {
                "q": query,
                "type": "statuses",
                "limit": page_size,
                "resolve": "false",
                "offset": offset,
            }

            try:
                data = await self._make_get_request(
                    client, GAB_SEARCH_ENDPOINT, params, token, cred_id
                )
            except ArenaCollectionError as exc:
                # HTTP 422 may indicate full-text search is restricted.
                if "422" in str(exc):
                    logger.warning(
                        "gab: search returned 422 for query='%s' — "
                        "full-text search may be restricted. Skipping term.",
                        query,
                    )
                    break
                raise

            statuses: list[dict[str, Any]] = []
            if isinstance(data, dict):
                statuses = data.get("statuses", [])
            elif isinstance(data, list):
                statuses = data

            if not statuses:
                break

            for status in statuses:
                if len(records) >= max_results:
                    break
                if not _passes_date_filter(status, date_from, date_to):
                    continue
                records.append(self.normalize(status))

            if len(statuses) < page_size:
                break  # Last page.
            offset += len(statuses)

        return records

    async def _search_or_hashtag(
        self,
        client: httpx.AsyncClient,
        token: str,
        cred_id: str,
        term: str,
        hashtag: str,
        max_results: int,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Try search endpoint first, fall back to hashtag timeline for hashtags.

        Args:
            client: Shared HTTP client.
            token: Bearer access token.
            cred_id: Credential ID for rate-limiting.
            term: The original search term (may start with ``#``).
            hashtag: The hashtag without the ``#`` prefix.
            max_results: Maximum records to retrieve.
            date_from: Client-side lower date filter.
            date_to: Client-side upper date filter.

        Returns:
            List of normalized records.
        """
        try:
            records = await self._search_statuses(
                client=client,
                token=token,
                cred_id=cred_id,
                query=term,
                max_results=max_results,
                date_from=date_from,
                date_to=date_to,
            )
            if records:
                return records
        except ArenaCollectionError:
            pass

        # Fall back to hashtag timeline.
        logger.info(
            "gab: falling back to hashtag timeline for hashtag='%s'", hashtag
        )
        return await self._fetch_hashtag_timeline(
            client=client,
            token=token,
            cred_id=cred_id,
            hashtag=hashtag,
            max_results=max_results,
            date_from=date_from,
            date_to=date_to,
        )

    async def _fetch_hashtag_timeline(
        self,
        client: httpx.AsyncClient,
        token: str,
        cred_id: str,
        hashtag: str,
        max_results: int,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Paginate through the hashtag timeline using ``max_id`` cursor.

        Args:
            client: Shared HTTP client.
            token: Bearer access token.
            cred_id: Credential ID for rate-limiting.
            hashtag: Hashtag string without the ``#`` prefix.
            max_results: Maximum records to retrieve.
            date_from: Client-side lower date filter.
            date_to: Client-side upper date filter.

        Returns:
            List of normalized records.
        """
        url = GAB_HASHTAG_TIMELINE_ENDPOINT.format(hashtag=hashtag)
        records: list[dict[str, Any]] = []
        max_id: str | None = None

        while len(records) < max_results:
            page_size = min(GAB_MAX_RESULTS_PER_PAGE, max_results - len(records))
            params: dict[str, Any] = {"limit": page_size}
            if max_id:
                params["max_id"] = max_id

            data = await self._make_get_request(client, url, params, token, cred_id)
            statuses: list[dict[str, Any]] = data if isinstance(data, list) else []

            if not statuses:
                break

            stop_early = False
            for status in statuses:
                if len(records) >= max_results:
                    break
                # Stop pagination if posts are older than date_from.
                if date_from:
                    created_at = _parse_datetime(status.get("created_at"))
                    if created_at and created_at < date_from:
                        stop_early = True
                        break
                if not _passes_date_filter(status, date_from, date_to):
                    continue
                records.append(self.normalize(status))

            if stop_early or len(statuses) < page_size:
                break

            # Mastodon max_id pagination: use the smallest ID from this page.
            max_id = statuses[-1].get("id")
            if not max_id:
                break

        return records

    async def _resolve_account_id(
        self,
        client: httpx.AsyncClient,
        token: str,
        cred_id: str,
        actor_id: str,
    ) -> str | None:
        """Resolve a Gab username to its account ID.

        If ``actor_id`` is already numeric (account ID), return it directly.
        Otherwise, look up the username via ``GET /api/v1/accounts/lookup``.

        Args:
            client: Shared HTTP client.
            token: Bearer access token.
            cred_id: Credential ID for rate-limiting.
            actor_id: Account ID or username string.

        Returns:
            Account ID string, or ``None`` if not found.
        """
        if actor_id.isdigit():
            return actor_id

        try:
            data = await self._make_get_request(
                client,
                GAB_ACCOUNT_LOOKUP_ENDPOINT,
                {"acct": actor_id},
                token,
                cred_id,
            )
            if isinstance(data, dict):
                return str(data.get("id", "")) or None
        except ArenaCollectionError:
            logger.warning("gab: account lookup failed for actor='%s'", actor_id)
        return None

    async def _fetch_account_statuses(
        self,
        client: httpx.AsyncClient,
        token: str,
        cred_id: str,
        account_id: str,
        max_results: int,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Paginate through account statuses using ``max_id`` cursor.

        Args:
            client: Shared HTTP client.
            token: Bearer access token.
            cred_id: Credential ID for rate-limiting.
            account_id: Numeric Gab account ID.
            max_results: Maximum records to retrieve.
            date_from: Client-side lower date filter.
            date_to: Client-side upper date filter.

        Returns:
            List of normalized records.
        """
        url = GAB_ACCOUNT_STATUSES_ENDPOINT.format(account_id=account_id)
        records: list[dict[str, Any]] = []
        max_id: str | None = None

        while len(records) < max_results:
            page_size = min(GAB_MAX_RESULTS_PER_PAGE, max_results - len(records))
            params: dict[str, Any] = {
                "limit": page_size,
                "exclude_replies": "false",
                "exclude_reblogs": "false",
            }
            if max_id:
                params["max_id"] = max_id

            data = await self._make_get_request(client, url, params, token, cred_id)
            statuses: list[dict[str, Any]] = data if isinstance(data, list) else []

            if not statuses:
                break

            stop_early = False
            for status in statuses:
                if len(records) >= max_results:
                    break
                # Posts are in reverse-chronological order; stop if past date_from.
                if date_from:
                    created_at = _parse_datetime(status.get("created_at"))
                    if created_at and created_at < date_from:
                        stop_early = True
                        break
                if not _passes_date_filter(status, date_from, date_to):
                    continue
                records.append(self.normalize(status))

            if stop_early or len(statuses) < page_size:
                break

            max_id = statuses[-1].get("id")
            if not max_id:
                break

        return records


# ---------------------------------------------------------------------------
# Module-level utility functions
# ---------------------------------------------------------------------------


def _strip_html(html: str) -> str:
    """Strip HTML tags from a Mastodon status content string.

    Converts ``<br>`` and ``<p>`` tags to newlines before stripping all
    remaining HTML tags to preserve readable plain text structure.

    Args:
        html: HTML-formatted content string.

    Returns:
        Plain text string.
    """
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    """Parse a datetime string or object to a UTC-aware datetime.

    Args:
        value: ISO 8601 string, datetime object, or None.

    Returns:
        Timezone-aware datetime or None.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S.%fZ",
        ):
            try:
                dt = datetime.strptime(value, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
    return None


def _passes_date_filter(
    status: dict[str, Any],
    date_from: datetime | None,
    date_to: datetime | None,
) -> bool:
    """Return True if the status falls within the date range.

    Args:
        status: Raw status dict with ``created_at`` field.
        date_from: Inclusive lower date bound (or None for no lower bound).
        date_to: Inclusive upper date bound (or None for no upper bound).

    Returns:
        True if the status should be included, False if filtered out.
    """
    if date_from is None and date_to is None:
        return True
    created_at = _parse_datetime(status.get("created_at"))
    if created_at is None:
        return True
    if date_from and created_at < date_from:
        return False
    if date_to and created_at > date_to:
        return False
    return True
