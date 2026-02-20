"""Threads arena collector implementation.

Collects posts from Threads via the official Threads API (free tier, OAuth 2.0).

Two collection modes are supported:

- :meth:`ThreadsCollector.collect_by_actors` — PRIMARY mode.  Retrieves posts
  published by specific Threads accounts.  Uses ``GET /{user_id}/threads`` with
  cursor-based pagination.  Date filtering applied client-side.

- :meth:`ThreadsCollector.collect_by_terms` — FALLBACK mode at free tier.
  Global keyword search is not available in the Threads API.  This method logs
  a WARNING and falls back to collecting from ``DEFAULT_DANISH_THREADS_ACCOUNTS``
  (if any are configured), filtering client-side for term matches in post text.

Credentials are acquired from :class:`CredentialPool` as
``platform="threads", tier="free"``.  The JSONB payload must contain
``access_token``, ``user_id``, and optionally ``expires_at`` (ISO 8601).

Rate limiting uses :meth:`RateLimiter.wait_for_slot` with key
``ratelimit:social_media:threads:{credential_id}`` and a 250 calls/3600 s
sliding window.

Token management: long-lived tokens expire after 60 days.  Call
:meth:`ThreadsCollector.refresh_token_if_needed` periodically (driven by the
``threads_refresh_tokens`` Celery Beat task) to renew tokens before expiry.

The Meta Content Library (MCL) tier is stubbed — both collection methods raise
``NotImplementedError`` when ``tier=Tier.MEDIUM`` is requested.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from issue_observatory.arenas.base import ArenaCollector, TemporalMode, Tier
from issue_observatory.arenas.query_builder import build_boolean_query_groups
from issue_observatory.arenas.registry import register
from issue_observatory.arenas.threads.config import (
    DEFAULT_DANISH_THREADS_ACCOUNTS,
    THREADS_API_BASE,
    THREADS_FIELDS,
    THREADS_ME_ENDPOINT,
    THREADS_PAGE_SIZE,
    THREADS_RATE_LIMIT,
    THREADS_RATE_WINDOW_SECONDS,
    THREADS_TIERS,
    TOKEN_REFRESH_DAYS,
    TOKEN_REFRESH_ENDPOINT,
)
from issue_observatory.config.tiers import TierConfig
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
)
from issue_observatory.core.normalizer import Normalizer

logger = logging.getLogger(__name__)

_RATE_LIMIT_ARENA: str = "social_media"
_RATE_LIMIT_PLATFORM: str = "threads"


@register
class ThreadsCollector(ArenaCollector):
    """Collects Threads posts via the official Threads API (OAuth 2.0).

    The primary collection mode is actor-based (``collect_by_actors``).
    Term-based collection at FREE tier is a client-side filter over known
    Danish accounts because the Threads API has no global keyword search.

    Class Attributes:
        arena_name: ``"social_media"``
        platform_name: ``"threads"``
        supported_tiers: ``[Tier.FREE, Tier.MEDIUM]``

    Args:
        credential_pool: Application-scoped credential pool.
        rate_limiter: Optional Redis-backed rate limiter.
        http_client: Optional injected :class:`httpx.AsyncClient` for testing.
    """

    arena_name: str = "social_media"
    platform_name: str = "threads"
    supported_tiers: list[Tier] = [Tier.FREE, Tier.MEDIUM]
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

    async def collect_by_actors(
        self,
        actor_ids: list[str],
        tier: Tier,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect Threads posts published by specific actors.

        Uses ``GET /{user_id}/threads`` with cursor-based pagination.
        Date filtering is applied client-side on the ``timestamp`` field
        because the Threads API does not support date range parameters.

        Engagement metrics (``views``, ``likes``, ``replies``, ``reposts``,
        ``quotes``) are only returned for the authenticated token owner's own
        posts.  For other users these fields are absent — normalised to
        ``None``.

        FREE tier: fully implemented.
        MEDIUM tier (MCL): raises ``NotImplementedError`` — Phase 2 stub.

        Args:
            actor_ids: Threads user IDs or usernames to collect posts from.
            tier: Operational tier.
            date_from: Earliest post date (inclusive).
            date_to: Latest post date (inclusive).
            max_results: Upper bound on total records across all actors.

        Returns:
            List of normalized content record dicts.

        Raises:
            NotImplementedError: When ``tier=Tier.MEDIUM`` (MCL not yet
                implemented).
            ArenaRateLimitError: On HTTP 429 from the Threads API.
            ArenaAuthError: On HTTP 401 / 403 (token expired or invalid).
            ArenaCollectionError: On other unrecoverable API errors.
            NoCredentialAvailableError: When no Threads credential is
                available in the pool.
        """
        if tier == Tier.MEDIUM:
            raise NotImplementedError(
                "Meta Content Library integration pending MCL approval. "
                "Use Tier.FREE (actor-based collection) in the interim."
            )

        self._validate_tier(tier)

        tier_config = self.get_tier_config(Tier.FREE)
        effective_max = (
            max_results
            if max_results is not None
            else (tier_config.max_results_per_run if tier_config else 10_000)
        )

        date_from_dt = _parse_datetime(date_from)
        date_to_dt = _parse_datetime(date_to)

        cred = await self._acquire_credential()
        if cred is None:
            from issue_observatory.core.credential_pool import NoCredentialAvailableError  # noqa: PLC0415
            raise NoCredentialAvailableError(platform="threads", tier="free")

        credential_id = cred["id"]
        access_token = cred["access_token"]

        all_records: list[dict[str, Any]] = []

        async with self._build_http_client() as client:
            for actor_id in actor_ids:
                if len(all_records) >= effective_max:
                    break
                remaining = effective_max - len(all_records)
                try:
                    records = await self._fetch_actor_threads(
                        client=client,
                        actor_id=actor_id,
                        access_token=access_token,
                        credential_id=credential_id,
                        max_results=remaining,
                        date_from=date_from_dt,
                        date_to=date_to_dt,
                    )
                    all_records.extend(records)
                except (ArenaRateLimitError, ArenaAuthError):
                    raise
                except ArenaCollectionError as exc:
                    logger.warning(
                        "threads: collection error for actor '%s' — skipping: %s",
                        actor_id,
                        exc,
                    )

        if self.credential_pool is not None:
            await self.credential_pool.release(credential_id=credential_id)

        logger.info(
            "threads: collect_by_actors completed — %d records for %d actors",
            len(all_records),
            len(actor_ids),
        )
        return all_records

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
        """Collect Threads posts matching one or more search terms.

        FREE tier limitation: the Threads API has no global keyword search.
        This method logs a WARNING and falls back to collecting all posts from
        ``DEFAULT_DANISH_THREADS_ACCOUNTS``, then filters client-side.

        When ``term_groups`` is provided, boolean AND/OR logic is applied
        client-side: an entry matches when at least one group has ALL its
        terms present in the post text.

        MEDIUM tier (MCL): raises ``NotImplementedError`` — global keyword
        search requires Meta Content Library access (Phase 2).

        Args:
            terms: Search terms (used when ``term_groups`` is ``None``).
            tier: Operational tier.
            date_from: Earliest post date (inclusive).
            date_to: Latest post date (inclusive).
            max_results: Upper bound on returned records.
            term_groups: Optional boolean AND/OR groups for client-side
                filtering.
            language_filter: Not used — Threads has no language filter.

        Returns:
            List of normalized content record dicts whose text matches.

        Raises:
            NotImplementedError: When ``tier=Tier.MEDIUM`` (MCL not yet
                implemented).
            ArenaRateLimitError: On HTTP 429 from the Threads API.
            ArenaAuthError: On expired or invalid token.
            ArenaCollectionError: On other unrecoverable API errors.
        """
        if tier == Tier.MEDIUM:
            raise NotImplementedError(
                "Keyword search requires Meta Content Library (MCL). "
                "MCL integration is pending approval — Phase 2 stub only."
            )

        self._validate_tier(tier)

        if not DEFAULT_DANISH_THREADS_ACCOUNTS:
            logger.warning(
                "threads: collect_by_terms() called at FREE tier but "
                "DEFAULT_DANISH_THREADS_ACCOUNTS is empty.  Global keyword "
                "search is not available in the Threads API.  Add known Danish "
                "Threads accounts via the actor management UI and re-run.  "
                "Returning empty result set."
            )
            return []

        logger.warning(
            "threads: collect_by_terms() at FREE tier — global keyword search "
            "is not available in the Threads API.  Collecting from %d configured "
            "Danish accounts and filtering client-side.",
            len(DEFAULT_DANISH_THREADS_ACCOUNTS),
        )

        tier_config = self.get_tier_config(Tier.FREE)
        effective_max = (
            max_results
            if max_results is not None
            else (tier_config.max_results_per_run if tier_config else 10_000)
        )

        # Collect all posts from known accounts, then filter.
        all_posts = await self.collect_by_actors(
            actor_ids=DEFAULT_DANISH_THREADS_ACCOUNTS,
            tier=Tier.FREE,
            date_from=date_from,
            date_to=date_to,
            max_results=effective_max * 10,  # over-collect before filtering
        )

        # Build lowercase boolean groups for client-side filtering.
        if term_groups is not None:
            lower_groups: list[list[str]] = [
                [t.lower() for t in grp] for grp in term_groups if grp
            ]
        else:
            lower_groups = [[t.lower()] for t in terms]

        matched: list[dict[str, Any]] = []
        for record in all_posts:
            text = (record.get("text_content") or "").lower()
            # Match if at least one AND-group has all its terms present.
            if any(all(t in text for t in grp) for grp in lower_groups):
                matched.append(record)
            if len(matched) >= effective_max:
                break

        logger.info(
            "threads: collect_by_terms — %d matches from %d posts across %d accounts",
            len(matched),
            len(all_posts),
            len(DEFAULT_DANISH_THREADS_ACCOUNTS),
        )
        return matched

    def get_tier_config(self, tier: Tier) -> TierConfig | None:
        """Return the tier configuration for the Threads arena.

        Args:
            tier: The requested operational tier.

        Returns:
            :class:`TierConfig` for FREE.  ``None`` for MEDIUM and PREMIUM.
        """
        return THREADS_TIERS.get(tier)

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single Threads API post to the universal content schema.

        Maps Threads API thread fields to the ``content_records`` universal
        schema.  Engagement fields (``views``, ``likes``, ``replies``,
        ``reposts``, ``quotes``) are set to ``None`` unless present in the
        raw item — they are only returned for the token owner's own posts.

        Args:
            raw_item: Raw thread dict from the Threads API response.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        thread_id: str = raw_item.get("id", "")
        username: str = raw_item.get("username", "")
        text: str = raw_item.get("text", "")
        timestamp_str: str | None = raw_item.get("timestamp")
        permalink: str | None = raw_item.get("permalink")
        is_reply: bool = bool(raw_item.get("is_reply", False))
        media_type: str | None = raw_item.get("media_type")

        # content_type: "reply" for replies, "post" for everything else.
        content_type = "reply" if is_reply else "post"

        # Engagement: only present if this is the token owner's post.
        # Absence means None, not zero.
        views_count: int | None = raw_item.get("views")
        likes_count: int | None = raw_item.get("likes")
        comments_count: int | None = raw_item.get("replies")
        shares_count: int | None = raw_item.get("reposts")

        # Build flat dict for Normalizer.normalize().
        flat: dict[str, Any] = {
            "platform_id": thread_id,
            "content_type": content_type,
            "text_content": text,
            "title": None,
            "url": permalink,
            "language": None,  # Threads API does not expose language metadata
            "published_at": timestamp_str,
            "author_platform_id": username,
            "author_display_name": username,
            "views_count": views_count,
            "likes_count": likes_count,
            "comments_count": comments_count,
            "shares_count": shares_count,
            # Raw metadata preserves all API response fields.
            "media_type": media_type,
            "is_reply": is_reply,
            "has_replies": raw_item.get("has_replies"),
            "reply_to_id": raw_item.get("reply_to_id"),
        }

        normalized = self._normalizer.normalize(
            raw_item=flat,
            platform=self.platform_name,
            arena=self.arena_name,
            collection_tier="free",
        )
        # Ensure platform_id is set to the Threads thread ID.
        normalized["platform_id"] = thread_id
        return normalized

    async def health_check(self) -> dict[str, Any]:
        """Verify that the Threads API is reachable with the configured token.

        Calls ``GET /me?fields=id,username`` to confirm the token is valid and
        the API is responsive.

        Returns:
            Dict with ``status`` (``"ok"`` | ``"degraded"`` | ``"down"``),
            ``arena``, ``platform``, ``checked_at``, and optionally
            ``username`` or ``detail``.
        """
        checked_at = datetime.utcnow().isoformat() + "Z"
        base: dict[str, Any] = {
            "arena": self.arena_name,
            "platform": self.platform_name,
            "checked_at": checked_at,
        }

        cred = await self._acquire_credential()
        if cred is None:
            return {
                **base,
                "status": "down",
                "detail": "No Threads credential available in pool.",
            }

        access_token = cred["access_token"]
        credential_id = cred["id"]

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    THREADS_ME_ENDPOINT,
                    params={"fields": "id,username"},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                response.raise_for_status()
                data = response.json()
                username = data.get("username", "unknown")
                return {**base, "status": "ok", "username": username}
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in (401, 403):
                return {
                    **base,
                    "status": "down",
                    "detail": f"HTTP {status_code} — token expired or invalid.",
                }
            return {
                **base,
                "status": "degraded",
                "detail": f"HTTP {status_code} from Threads API.",
            }
        except httpx.RequestError as exc:
            return {**base, "status": "down", "detail": f"Connection error: {exc}"}
        finally:
            if self.credential_pool is not None:
                await self.credential_pool.release(credential_id=credential_id)

    # ------------------------------------------------------------------
    # Token refresh
    # ------------------------------------------------------------------

    async def refresh_token_if_needed(
        self,
        credential_id: str,
        credential_pool: Any,
    ) -> bool:
        """Refresh a long-lived Threads token if it is within TOKEN_REFRESH_DAYS of expiry.

        Checks the Redis key ``threads:token_expiry:{credential_id}`` for the
        stored expiry timestamp.  If within ``TOKEN_REFRESH_DAYS`` days of
        expiry, calls ``GET /refresh_access_token`` to obtain a refreshed token,
        then updates the credential pool with the new token and logs at INFO.

        This method is invoked by the ``threads_refresh_tokens`` Celery Beat
        task.  It gracefully handles Redis unavailability and non-existent
        expiry keys (returns ``False`` without error).

        Args:
            credential_id: String UUID of the credential to check and refresh.
            credential_pool: The :class:`CredentialPool` instance.

        Returns:
            ``True`` if a token refresh was performed, ``False`` otherwise.
        """
        expiry_redis_key = f"threads:token_expiry:{credential_id}"

        # Read expiry from Redis.
        expiry_str: str | None = None
        try:
            r = await credential_pool._get_redis()
            expiry_str = await r.get(expiry_redis_key)
        except Exception as exc:
            logger.warning(
                "threads: could not read token expiry for credential '%s' "
                "from Redis: %s — skipping refresh check.",
                credential_id,
                exc,
            )
            return False

        if expiry_str is None:
            # No expiry info stored — cannot determine if refresh needed.
            logger.debug(
                "threads: no expiry key found for credential '%s' — skipping.",
                credential_id,
            )
            return False

        try:
            expiry_dt = datetime.fromisoformat(expiry_str)
            if expiry_dt.tzinfo is None:
                expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError) as exc:
            logger.warning(
                "threads: invalid expiry value '%s' for credential '%s': %s",
                expiry_str,
                credential_id,
                exc,
            )
            return False

        now = datetime.now(tz=timezone.utc)
        refresh_threshold = expiry_dt - timedelta(days=TOKEN_REFRESH_DAYS)

        if now < refresh_threshold:
            logger.debug(
                "threads: credential '%s' token is fresh — next refresh after %s.",
                credential_id,
                refresh_threshold.isoformat(),
            )
            return False

        # Fetch the current token from the credential pool.
        cred = await credential_pool.acquire(
            platform="threads",
            tier="free",
            task_id=f"token_refresh_{credential_id}",
        )
        if cred is None:
            logger.warning(
                "threads: could not acquire credential '%s' for token refresh.",
                credential_id,
            )
            return False

        access_token = cred.get("access_token", "")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    TOKEN_REFRESH_ENDPOINT,
                    params={
                        "grant_type": "th_refresh_token",
                        "access_token": access_token,
                    },
                )
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.error(
                "threads: token refresh request failed for credential '%s': %s",
                credential_id,
                exc,
            )
            await credential_pool.release(credential_id=credential_id)
            return False

        new_token = data.get("access_token")
        expires_in = data.get("expires_in")  # seconds

        if not new_token:
            logger.error(
                "threads: token refresh response missing 'access_token' "
                "for credential '%s'.",
                credential_id,
            )
            await credential_pool.release(credential_id=credential_id)
            return False

        # Compute new expiry.
        if expires_in:
            new_expiry = now + timedelta(seconds=int(expires_in))
        else:
            new_expiry = now + timedelta(days=60)

        # Update expiry in Redis.
        try:
            r = await credential_pool._get_redis()
            # Keep expiry key for TOKEN_REFRESH_DAYS + 10 days as safety buffer.
            ttl_seconds = int((new_expiry - now).total_seconds()) + 10 * 86400
            await r.setex(expiry_redis_key, ttl_seconds, new_expiry.isoformat())
        except Exception as exc:
            logger.warning(
                "threads: failed to update token expiry in Redis for '%s': %s",
                credential_id,
                exc,
            )

        logger.info(
            "threads: refreshed long-lived token for credential '%s'. "
            "New expiry: %s.",
            credential_id,
            new_expiry.isoformat(),
        )

        await credential_pool.release(credential_id=credential_id)
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_http_client(self) -> httpx.AsyncClient:
        """Return an :class:`httpx.AsyncClient` for use as an async context manager.

        Returns:
            A new client (30 s timeout) or the injected test client.
        """
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]
        return httpx.AsyncClient(timeout=30.0)

    async def _acquire_credential(self) -> dict[str, Any] | None:
        """Acquire a Threads API credential from the pool.

        Returns:
            Credential dict or ``None`` if no pool is configured or no
            credential is available.
        """
        if self.credential_pool is None:
            return None
        return await self.credential_pool.acquire(platform="threads", tier="free")

    async def _wait_for_rate_limit(self, credential_id: str) -> None:
        """Wait for a rate-limit slot before making an API call.

        Uses ``RateLimiter.wait_for_slot`` with key
        ``ratelimit:social_media:threads:{credential_id}`` and a sliding
        window of 250 calls per 3600 seconds.

        Args:
            credential_id: Credential UUID or env-var name used as key suffix.
        """
        if self.rate_limiter is None:
            return
        key = (
            f"ratelimit:{_RATE_LIMIT_ARENA}:{_RATE_LIMIT_PLATFORM}:{credential_id}"
        )
        await self.rate_limiter.wait_for_slot(
            key=key,
            max_calls=THREADS_RATE_LIMIT,
            window_seconds=THREADS_RATE_WINDOW_SECONDS,
        )

    async def _make_request(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, Any],
        access_token: str,
        credential_id: str,
    ) -> dict[str, Any]:
        """Make a rate-limited, authenticated GET request to the Threads API.

        Args:
            client: Shared HTTP client.
            url: Endpoint URL (absolute).
            params: Query parameters.
            access_token: Bearer token for the Authorization header.
            credential_id: Credential ID used for rate-limit key suffix.

        Returns:
            Parsed JSON response dict.

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaAuthError: On HTTP 401 or 403.
            ArenaCollectionError: On other non-2xx responses or connection errors.
        """
        await self._wait_for_rate_limit(credential_id)
        try:
            response = await client.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code == 429:
                retry_after = float(
                    exc.response.headers.get("Retry-After", 60)
                )
                raise ArenaRateLimitError(
                    "threads: 429 rate limit hit",
                    retry_after=retry_after,
                    arena=self.arena_name,
                    platform=self.platform_name,
                ) from exc
            if status_code in (401, 403):
                raise ArenaAuthError(
                    f"threads: HTTP {status_code} — token expired or invalid",
                    arena=self.arena_name,
                    platform=self.platform_name,
                ) from exc
            raise ArenaCollectionError(
                f"threads: HTTP {status_code} from Threads API",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"threads: connection error: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

    async def _fetch_actor_threads(
        self,
        client: httpx.AsyncClient,
        actor_id: str,
        access_token: str,
        credential_id: str,
        max_results: int,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Paginate through threads for a single actor.

        Uses cursor-based pagination via ``paging.cursors.after``.  Date
        filtering is applied client-side.  Pagination stops early when a post
        timestamp falls before ``date_from`` (posts are returned in
        reverse-chronological order).

        Args:
            client: Shared HTTP client.
            actor_id: Threads user ID or username.
            access_token: Bearer token for the Authorization header.
            credential_id: Credential ID used for rate-limit key suffix.
            max_results: Maximum records to retrieve for this actor.
            date_from: Earliest post date filter (inclusive).
            date_to: Latest post date filter (inclusive).

        Returns:
            List of normalized records within the date range.
        """
        records: list[dict[str, Any]] = []
        cursor: str | None = None
        endpoint = f"{THREADS_API_BASE}/{actor_id}/threads"

        while len(records) < max_results:
            params: dict[str, Any] = {
                "fields": THREADS_FIELDS,
                "limit": min(THREADS_PAGE_SIZE, max_results - len(records)),
            }
            if cursor:
                params["after"] = cursor

            data = await self._make_request(
                client=client,
                url=endpoint,
                params=params,
                access_token=access_token,
                credential_id=credential_id,
            )

            items: list[dict[str, Any]] = data.get("data", [])
            if not items:
                break

            stop_early = False
            for item in items:
                ts_str: str | None = item.get("timestamp")
                published_at = _parse_datetime(ts_str) if ts_str else None

                # Stop early if we've gone past date_from (reverse-chron order).
                if published_at and date_from and published_at < date_from:
                    stop_early = True
                    break

                # Skip posts newer than date_to.
                if published_at and date_to and published_at > date_to:
                    continue

                if len(records) >= max_results:
                    break
                records.append(self.normalize(item))

            # Advance cursor.
            paging = data.get("paging", {})
            cursors = paging.get("cursors", {})
            next_cursor = cursors.get("after")

            if not next_cursor or stop_early:
                break
            cursor = next_cursor

        return records


# ---------------------------------------------------------------------------
# Module-level utility functions
# ---------------------------------------------------------------------------


def _parse_datetime(value: datetime | str | None) -> datetime | None:
    """Parse a datetime value to a timezone-aware datetime object.

    Args:
        value: Datetime object, ISO 8601 string, or ``None``.

    Returns:
        Timezone-aware datetime, or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
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
