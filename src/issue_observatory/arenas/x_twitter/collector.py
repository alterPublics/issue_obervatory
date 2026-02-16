"""X/Twitter arena collector implementation.

Collects tweets from two tiers:

- **MEDIUM** (:class:`Tier.MEDIUM`): TwitterAPI.io third-party search service.
  POST to ``/twitter/tweet/advanced_search`` with cursor-based pagination.
  Credential: ``platform="twitterapi_io"``, JSONB field ``api_key``.

- **PREMIUM** (:class:`Tier.PREMIUM`): Official X API v2 Pro.
  Full-archive search via GET ``/2/tweets/search/all`` (or ``/recent`` for
  7-day only). Bearer-token authentication. Credential: ``platform="x_twitter"``,
  JSONB field ``bearer_token``.

Both tiers append ``lang:da`` to every query and use cursor-based pagination.

Rate limiting:

- Medium: ``ratelimit:social_media:x_twitter:{credential_id}`` at 1 call/sec.
- Premium: ``ratelimit:social_media:x_twitter:{credential_id}`` at 15 calls/60 sec;
  also respects ``x-rate-limit-remaining`` / ``x-rate-limit-reset`` response headers.

Danish defaults: ``lang:da`` operator is unconditionally appended.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from issue_observatory.arenas.base import ArenaCollector, Tier
from issue_observatory.arenas.registry import register
from issue_observatory.arenas.x_twitter.config import (
    DANISH_LANG_OPERATOR,
    MEDIUM_RATE_LIMIT_MAX_CALLS,
    MEDIUM_RATE_LIMIT_WINDOW_SECONDS,
    PREMIUM_RATE_LIMIT_MAX_CALLS,
    PREMIUM_RATE_LIMIT_WINDOW_SECONDS,
    TWITTERAPIIO_BASE_URL,
    TWITTERAPIIO_QUERY_TYPE,
    TWITTERAPIIO_USER_TWEETS_URL,
    TWITTER_V2_EXPANSIONS,
    TWITTER_V2_MAX_RESULTS_PER_PAGE,
    TWITTER_V2_SEARCH_ALL,
    TWITTER_V2_SEARCH_RECENT,
    TWITTER_V2_TWEET_FIELDS,
    TWITTER_V2_USER_FIELDS,
    TWITTER_V2_USER_TWEETS,
    XTWITTER_TIERS,
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

_ARENA: str = "social_media"
_PLATFORM: str = "x_twitter"


@register
class XTwitterCollector(ArenaCollector):
    """Collects tweets from X/Twitter via TwitterAPI.io (medium) or X API v2 (premium).

    Class Attributes:
        arena_name: ``"social_media"``
        platform_name: ``"x_twitter"``
        supported_tiers: ``[Tier.MEDIUM, Tier.PREMIUM]``

    Args:
        credential_pool: Shared credential pool. Required for both tiers.
        rate_limiter: Optional Redis-backed rate limiter.
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
        """Collect tweets matching one or more search terms.

        Appends ``lang:da`` to every query term. Paginates through all results
        up to *max_results*. For MEDIUM tier uses TwitterAPI.io cursor pagination;
        for PREMIUM tier uses X API v2 ``next_token`` pagination.

        Args:
            terms: Search terms or X operator query strings.
            tier: :attr:`Tier.MEDIUM` (TwitterAPI.io) or :attr:`Tier.PREMIUM`
                (X API v2 Pro).
            date_from: Earliest publication date (inclusive).
            date_to: Latest publication date (inclusive).
            max_results: Upper bound on returned records. ``None`` uses the
                tier default.

        Returns:
            List of normalized content record dicts.

        Raises:
            ArenaRateLimitError: On HTTP 429 from the upstream API.
            ArenaAuthError: On HTTP 401/403 (invalid credentials).
            ArenaCollectionError: On other unrecoverable API errors.
            NoCredentialAvailableError: When no suitable credential exists.
        """
        self._validate_tier(tier)
        tier_config = self.get_tier_config(tier)
        effective_max = (
            max_results if max_results is not None
            else (tier_config.max_results_per_run if tier_config else 1_000)
        )

        date_from_str = _to_date_str(date_from)
        date_to_str = _to_date_str(date_to)

        all_records: list[dict[str, Any]] = []

        async with self._build_http_client() as client:
            for term in terms:
                if len(all_records) >= effective_max:
                    break
                remaining = effective_max - len(all_records)
                if tier == Tier.MEDIUM:
                    records = await self._collect_medium_term(
                        client, term, remaining, date_from_str, date_to_str
                    )
                else:
                    records = await self._collect_premium_term(
                        client, term, remaining, date_from_str, date_to_str
                    )
                all_records.extend(records)

        logger.info(
            "x_twitter: collect_by_terms completed — tier=%s terms=%d records=%d",
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
        """Collect tweets published by specific X/Twitter users.

        Accepts numeric Twitter user IDs (strings of digits) or handles
        prefixed with ``@`` (e.g. ``"@LarsLoekke"``). Strips leading ``@``
        internally when constructing search operators.

        For MEDIUM tier: uses ``from:{handle} lang:da`` queries via the
        TwitterAPI.io advanced search endpoint with cursor pagination.
        For PREMIUM tier: uses ``GET /2/users/{id}/tweets`` for numeric IDs,
        or falls back to ``from:{handle}`` search for handles.

        Args:
            actor_ids: Twitter user IDs (numeric strings) or ``@handles``.
            tier: :attr:`Tier.MEDIUM` or :attr:`Tier.PREMIUM`.
            date_from: Earliest publication date (inclusive).
            date_to: Latest publication date (inclusive).
            max_results: Upper bound on returned records.

        Returns:
            List of normalized content record dicts.

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaAuthError: On HTTP 401/403.
            ArenaCollectionError: On other unrecoverable API errors.
            NoCredentialAvailableError: When no credential is available.
        """
        self._validate_tier(tier)
        tier_config = self.get_tier_config(tier)
        effective_max = (
            max_results if max_results is not None
            else (tier_config.max_results_per_run if tier_config else 1_000)
        )

        date_from_str = _to_date_str(date_from)
        date_to_str = _to_date_str(date_to)

        all_records: list[dict[str, Any]] = []

        async with self._build_http_client() as client:
            for actor_id in actor_ids:
                if len(all_records) >= effective_max:
                    break
                remaining = effective_max - len(all_records)
                if tier == Tier.MEDIUM:
                    records = await self._collect_medium_actor(
                        client, actor_id, remaining, date_from_str, date_to_str
                    )
                else:
                    records = await self._collect_premium_actor(
                        client, actor_id, remaining, date_from_str, date_to_str
                    )
                all_records.extend(records)

        logger.info(
            "x_twitter: collect_by_actors completed — tier=%s actors=%d records=%d",
            tier.value,
            len(actor_ids),
            len(all_records),
        )
        return all_records

    def get_tier_config(self, tier: Tier) -> TierConfig | None:
        """Return tier configuration for the X/Twitter arena.

        Args:
            tier: The requested operational tier.

        Returns:
            :class:`TierConfig` for MEDIUM or PREMIUM.  ``None`` for FREE
            (not supported).

        Raises:
            ValueError: If *tier* is not in ``self.supported_tiers``.
        """
        if tier not in self.supported_tiers:
            raise ValueError(
                f"Tier '{tier.value}' is not supported by XTwitterCollector. "
                f"Supported: {[t.value for t in self.supported_tiers]}"
            )
        return XTWITTER_TIERS.get(tier)

    def normalize(
        self,
        raw_item: dict[str, Any],
        tier_source: str = "medium",
    ) -> dict[str, Any]:
        """Normalize a single tweet to the universal content record schema.

        Dispatches to either :meth:`_parse_twitterapiio` (medium tier) or
        :meth:`_parse_twitter_v2` (premium tier) based on *tier_source*.

        Args:
            raw_item: Raw tweet dict from the upstream API.
            tier_source: ``"medium"`` for TwitterAPI.io, ``"premium"`` for
                the official X API v2.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        if tier_source == "premium":
            flat = self._parse_twitter_v2(raw_item)
        else:
            flat = self._parse_twitterapiio(raw_item)

        normalized = self._normalizer.normalize(
            raw_item=flat,
            platform=self.platform_name,
            arena=self.arena_name,
            collection_tier=tier_source,
        )
        # Ensure platform_id is the tweet ID string, not the URL.
        if flat.get("platform_id"):
            normalized["platform_id"] = flat["platform_id"]
        return normalized

    # ------------------------------------------------------------------
    # Tier-specific collection helpers
    # ------------------------------------------------------------------

    async def _collect_medium_term(
        self,
        client: httpx.AsyncClient,
        term: str,
        max_results: int,
        date_from: str | None,
        date_to: str | None,
    ) -> list[dict[str, Any]]:
        """Paginate TwitterAPI.io results for a single search term.

        Args:
            client: Shared HTTP client.
            term: Search term (operators allowed).
            max_results: Maximum records to retrieve.
            date_from: ISO date lower bound (``YYYY-MM-DD``), optional.
            date_to: ISO date upper bound (``YYYY-MM-DD``), optional.

        Returns:
            List of normalized tweet records.
        """
        cred = await self._acquire_medium_credential()
        if cred is None:
            raise NoCredentialAvailableError(platform="twitterapi_io", tier="medium")

        cred_id: str = cred["id"]
        api_key: str = cred.get("api_key", "")
        records: list[dict[str, Any]] = []
        cursor: str | None = None

        try:
            while len(records) < max_results:
                query = _build_query(term, date_from, date_to)
                await self._wait_rate_limit_medium(cred_id)

                payload: dict[str, Any] = {
                    "query": query,
                    "queryType": TWITTERAPIIO_QUERY_TYPE,
                }
                if cursor:
                    payload["cursor"] = cursor

                data = await self._post_twitterapiio(client, api_key, payload)
                tweets = data.get("tweets") or []
                if not tweets:
                    break

                for tweet in tweets:
                    if len(records) >= max_results:
                        break
                    records.append(self.normalize(tweet, tier_source="medium"))

                cursor = data.get("next_cursor")
                if not cursor:
                    break

        finally:
            if self.credential_pool:
                await self.credential_pool.release(credential_id=cred_id)

        return records

    async def _collect_medium_actor(
        self,
        client: httpx.AsyncClient,
        actor_id: str,
        max_results: int,
        date_from: str | None,
        date_to: str | None,
    ) -> list[dict[str, Any]]:
        """Collect tweets from a single actor using TwitterAPI.io search.

        Constructs a ``from:{handle}`` search query and paginates with the
        advanced_search endpoint.

        Args:
            client: Shared HTTP client.
            actor_id: Twitter user ID or ``@handle``.
            max_results: Maximum records to retrieve.
            date_from: ISO date lower bound, optional.
            date_to: ISO date upper bound, optional.

        Returns:
            List of normalized tweet records.
        """
        cred = await self._acquire_medium_credential()
        if cred is None:
            raise NoCredentialAvailableError(platform="twitterapi_io", tier="medium")

        cred_id: str = cred["id"]
        api_key: str = cred.get("api_key", "")
        handle = _normalize_handle(actor_id)
        records: list[dict[str, Any]] = []
        cursor: str | None = None

        try:
            while len(records) < max_results:
                term = f"from:{handle}"
                query = _build_query(term, date_from, date_to)
                await self._wait_rate_limit_medium(cred_id)

                payload: dict[str, Any] = {
                    "query": query,
                    "queryType": TWITTERAPIIO_QUERY_TYPE,
                }
                if cursor:
                    payload["cursor"] = cursor

                data = await self._post_twitterapiio(client, api_key, payload)
                tweets = data.get("tweets") or []
                if not tweets:
                    break

                for tweet in tweets:
                    if len(records) >= max_results:
                        break
                    records.append(self.normalize(tweet, tier_source="medium"))

                cursor = data.get("next_cursor")
                if not cursor:
                    break

        finally:
            if self.credential_pool:
                await self.credential_pool.release(credential_id=cred_id)

        return records

    async def _collect_premium_term(
        self,
        client: httpx.AsyncClient,
        term: str,
        max_results: int,
        date_from: str | None,
        date_to: str | None,
    ) -> list[dict[str, Any]]:
        """Paginate X API v2 full-archive search results for a single term.

        Uses ``/2/tweets/search/all`` for full-archive access.

        Args:
            client: Shared HTTP client.
            term: Search term.
            max_results: Maximum records to retrieve.
            date_from: ISO date lower bound, optional.
            date_to: ISO date upper bound, optional.

        Returns:
            List of normalized tweet records.
        """
        cred = await self._acquire_premium_credential()
        if cred is None:
            raise NoCredentialAvailableError(platform="x_twitter", tier="premium")

        cred_id: str = cred["id"]
        bearer_token: str = cred.get("bearer_token", "")
        records: list[dict[str, Any]] = []
        next_token: str | None = None

        try:
            while len(records) < max_results:
                page_size = min(TWITTER_V2_MAX_RESULTS_PER_PAGE, max_results - len(records))
                query = f"{term} {DANISH_LANG_OPERATOR}"
                params: dict[str, Any] = {
                    "query": query,
                    "max_results": page_size,
                    "tweet.fields": TWITTER_V2_TWEET_FIELDS,
                    "expansions": TWITTER_V2_EXPANSIONS,
                    "user.fields": TWITTER_V2_USER_FIELDS,
                }
                if date_from:
                    params["start_time"] = f"{date_from}T00:00:00Z"
                if date_to:
                    params["end_time"] = f"{date_to}T23:59:59Z"
                if next_token:
                    params["next_token"] = next_token

                await self._wait_rate_limit_premium(cred_id)
                data, rate_headers = await self._get_twitter_v2(
                    client, TWITTER_V2_SEARCH_ALL, bearer_token, params
                )
                await self._handle_v2_rate_headers(rate_headers)

                tweets = data.get("data") or []
                users = _index_v2_users(data.get("includes", {}).get("users", []))

                for tweet in tweets:
                    if len(records) >= max_results:
                        break
                    raw = {**tweet, "_users": users}
                    records.append(self.normalize(raw, tier_source="premium"))

                meta = data.get("meta", {})
                next_token = meta.get("next_token")
                if not next_token:
                    break

        finally:
            if self.credential_pool:
                await self.credential_pool.release(credential_id=cred_id)

        return records

    async def _collect_premium_actor(
        self,
        client: httpx.AsyncClient,
        actor_id: str,
        max_results: int,
        date_from: str | None,
        date_to: str | None,
    ) -> list[dict[str, Any]]:
        """Collect tweets from a single actor using X API v2.

        Uses ``GET /2/users/{id}/tweets`` when *actor_id* is a numeric string,
        or falls back to a ``from:{handle}`` search for handles.

        Args:
            client: Shared HTTP client.
            actor_id: Twitter user ID (numeric) or ``@handle``.
            max_results: Maximum records to retrieve.
            date_from: ISO date lower bound, optional.
            date_to: ISO date upper bound, optional.

        Returns:
            List of normalized tweet records.
        """
        cred = await self._acquire_premium_credential()
        if cred is None:
            raise NoCredentialAvailableError(platform="x_twitter", tier="premium")

        cred_id: str = cred["id"]
        bearer_token: str = cred.get("bearer_token", "")
        records: list[dict[str, Any]] = []
        next_token: str | None = None

        # Determine endpoint based on whether actor_id is numeric.
        is_numeric = actor_id.lstrip("@").isdigit()

        try:
            while len(records) < max_results:
                page_size = min(TWITTER_V2_MAX_RESULTS_PER_PAGE, max_results - len(records))
                await self._wait_rate_limit_premium(cred_id)

                if is_numeric:
                    numeric_id = actor_id.lstrip("@")
                    endpoint = TWITTER_V2_USER_TWEETS.format(user_id=numeric_id)
                    params: dict[str, Any] = {
                        "max_results": page_size,
                        "tweet.fields": TWITTER_V2_TWEET_FIELDS,
                        "expansions": TWITTER_V2_EXPANSIONS,
                        "user.fields": TWITTER_V2_USER_FIELDS,
                    }
                    if date_from:
                        params["start_time"] = f"{date_from}T00:00:00Z"
                    if date_to:
                        params["end_time"] = f"{date_to}T23:59:59Z"
                    if next_token:
                        params["pagination_token"] = next_token

                    data, rate_headers = await self._get_twitter_v2(
                        client, endpoint, bearer_token, params
                    )
                else:
                    # Handle-based fallback via full-archive search.
                    handle = _normalize_handle(actor_id)
                    endpoint = TWITTER_V2_SEARCH_ALL
                    params = {
                        "query": f"from:{handle} {DANISH_LANG_OPERATOR}",
                        "max_results": page_size,
                        "tweet.fields": TWITTER_V2_TWEET_FIELDS,
                        "expansions": TWITTER_V2_EXPANSIONS,
                        "user.fields": TWITTER_V2_USER_FIELDS,
                    }
                    if date_from:
                        params["start_time"] = f"{date_from}T00:00:00Z"
                    if date_to:
                        params["end_time"] = f"{date_to}T23:59:59Z"
                    if next_token:
                        params["next_token"] = next_token

                    data, rate_headers = await self._get_twitter_v2(
                        client, endpoint, bearer_token, params
                    )

                await self._handle_v2_rate_headers(rate_headers)
                tweets = data.get("data") or []
                users = _index_v2_users(data.get("includes", {}).get("users", []))

                for tweet in tweets:
                    if len(records) >= max_results:
                        break
                    raw = {**tweet, "_users": users}
                    records.append(self.normalize(raw, tier_source="premium"))

                meta = data.get("meta", {})
                next_token = meta.get("next_token") or meta.get("pagination_token")
                if not next_token:
                    break

        finally:
            if self.credential_pool:
                await self.credential_pool.release(credential_id=cred_id)

        return records

    # ------------------------------------------------------------------
    # Normalizer parsing paths
    # ------------------------------------------------------------------

    def _parse_twitterapiio(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Parse a TwitterAPI.io tweet object to a flat normalizer-ready dict.

        Args:
            raw: Raw tweet object from the TwitterAPI.io response.

        Returns:
            Flat dict for :meth:`Normalizer.normalize`.
        """
        tweet_id: str = str(raw.get("id", ""))
        author = raw.get("author") or {}
        username: str = author.get("userName", "") or author.get("username", "")
        user_id: str = str(author.get("id", ""))
        display_name: str = author.get("name", "") or username

        text: str = raw.get("text", "")
        lang: str = raw.get("lang", "da")

        # Detect tweet type from isRetweet / isReply / isQuote fields.
        content_type: str = _detect_tweet_type_twitterapiio(raw)

        url: str | None = (
            f"https://x.com/{username}/status/{tweet_id}" if username and tweet_id else None
        )

        # Engagement metrics.
        likes_count: int | None = raw.get("favorites") or raw.get("likeCount")
        shares_count: int | None = raw.get("retweets") or raw.get("retweetCount")
        comments_count: int | None = raw.get("replies") or raw.get("replyCount")
        views_count: int | None = raw.get("views") or raw.get("viewCount")

        # Media URLs.
        media_urls: list[str] = _extract_twitterapiio_media(raw)

        flat: dict[str, Any] = {
            "platform_id": tweet_id,
            "id": tweet_id,
            "content_type": content_type,
            "text_content": text,
            "title": None,
            "url": url,
            "language": lang,
            "published_at": raw.get("createdAt") or raw.get("created_at"),
            "author_platform_id": user_id,
            "author_display_name": display_name,
            "likes_count": likes_count,
            "shares_count": shares_count,
            "comments_count": comments_count,
            "views_count": views_count,
            "media_urls": media_urls,
            # Raw metadata passthrough.
            "tweet_type": content_type,
            "is_retweet": content_type == "retweet",
            "conversation_id": raw.get("conversationId"),
            "entities": raw.get("entities"),
            "source_app": raw.get("source"),
        }
        return flat

    def _parse_twitter_v2(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Parse an official X API v2 tweet object to a flat normalizer-ready dict.

        The *raw* dict may contain a ``_users`` key with a lookup dict of
        user objects keyed by their numeric ID (injected by the collection
        helpers for author hydration).

        Args:
            raw: Raw tweet object from the v2 API response (possibly with
                ``_users`` injected).

        Returns:
            Flat dict for :meth:`Normalizer.normalize`.
        """
        tweet_id: str = raw.get("id", "")
        text: str = raw.get("text", "")
        lang: str = raw.get("lang", "da")
        author_id: str = raw.get("author_id", "")

        # Hydrate author from injected _users lookup dict.
        users: dict[str, Any] = raw.get("_users", {})
        author = users.get(author_id, {})
        username: str = author.get("username", "")
        display_name: str = author.get("name", "") or username

        content_type: str = _detect_tweet_type_v2(raw)
        url: str | None = (
            f"https://x.com/{username}/status/{tweet_id}" if username and tweet_id else None
        )

        metrics: dict[str, Any] = raw.get("public_metrics") or {}
        likes_count: int | None = metrics.get("like_count")
        shares_count_val = (metrics.get("retweet_count") or 0) + (metrics.get("quote_count") or 0)
        shares_count: int | None = shares_count_val if shares_count_val else None
        comments_count: int | None = metrics.get("reply_count")
        views_count: int | None = metrics.get("impression_count")

        flat: dict[str, Any] = {
            "platform_id": tweet_id,
            "id": tweet_id,
            "content_type": content_type,
            "text_content": text,
            "title": None,
            "url": url,
            "language": lang,
            "published_at": raw.get("created_at"),
            "author_platform_id": author_id,
            "author_display_name": display_name,
            "likes_count": likes_count,
            "shares_count": shares_count,
            "comments_count": comments_count,
            "views_count": views_count,
            "media_urls": [],
            # Raw metadata passthrough.
            "tweet_type": content_type,
            "is_retweet": content_type == "retweet",
            "conversation_id": raw.get("conversation_id"),
            "in_reply_to_user_id": raw.get("in_reply_to_user_id"),
            "referenced_tweets": raw.get("referenced_tweets"),
            "entities": raw.get("entities"),
            "context_annotations": raw.get("context_annotations"),
            "source_app": raw.get("source"),
        }
        return flat

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """Verify that the X/Twitter upstream APIs are reachable.

        Tests the MEDIUM tier first (TwitterAPI.io). If no medium credential
        exists, attempts the PREMIUM tier. Returns ``"down"`` if neither is
        configured.

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

        # Try medium tier first.
        cred = await self._acquire_medium_credential()
        if cred is not None:
            cred_id = cred["id"]
            api_key = cred.get("api_key", "")
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    payload = {
                        "query": f"test {DANISH_LANG_OPERATOR}",
                        "queryType": TWITTERAPIIO_QUERY_TYPE,
                    }
                    response = await client.post(
                        TWITTERAPIIO_BASE_URL,
                        json=payload,
                        headers={"X-API-Key": api_key},
                    )
                    if response.status_code == 429:
                        return {
                            **base,
                            "status": "degraded",
                            "detail": "TwitterAPI.io: 429 rate limited",
                            "tier_tested": "medium",
                        }
                    response.raise_for_status()
                    return {**base, "status": "ok", "tier_tested": "medium"}
            except httpx.HTTPStatusError as exc:
                return {
                    **base,
                    "status": "degraded",
                    "detail": f"TwitterAPI.io HTTP {exc.response.status_code}",
                    "tier_tested": "medium",
                }
            except httpx.RequestError as exc:
                return {
                    **base,
                    "status": "down",
                    "detail": f"TwitterAPI.io connection error: {exc}",
                    "tier_tested": "medium",
                }
            finally:
                if self.credential_pool:
                    await self.credential_pool.release(credential_id=cred_id)

        # Try premium tier.
        cred = await self._acquire_premium_credential()
        if cred is not None:
            cred_id = cred["id"]
            bearer_token = cred.get("bearer_token", "")
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    params = {
                        "query": f"test {DANISH_LANG_OPERATOR}",
                        "max_results": 10,
                        "tweet.fields": "id,text",
                    }
                    _, rate_headers = await self._get_twitter_v2(
                        client, TWITTER_V2_SEARCH_RECENT, bearer_token, params
                    )
                    return {**base, "status": "ok", "tier_tested": "premium"}
            except (ArenaRateLimitError, ArenaCollectionError, ArenaAuthError) as exc:
                return {
                    **base,
                    "status": "degraded",
                    "detail": str(exc),
                    "tier_tested": "premium",
                }
            finally:
                if self.credential_pool:
                    await self.credential_pool.release(credential_id=cred_id)

        return {
            **base,
            "status": "down",
            "detail": "No credentials configured for twitterapi_io or x_twitter.",
        }

    # ------------------------------------------------------------------
    # Low-level HTTP helpers
    # ------------------------------------------------------------------

    def _build_http_client(self) -> httpx.AsyncClient:
        """Return an :class:`httpx.AsyncClient` for use as a context manager.

        Returns:
            A new or injected :class:`httpx.AsyncClient`.
        """
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]
        return httpx.AsyncClient(timeout=30.0)

    async def _post_twitterapiio(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """POST to TwitterAPI.io advanced search with API key auth.

        Args:
            client: Shared HTTP client.
            api_key: TwitterAPI.io API key.
            payload: Request body dict.

        Returns:
            Parsed JSON response dict.

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaAuthError: On HTTP 401/403.
            ArenaCollectionError: On other non-2xx or connection errors.
        """
        try:
            response = await client.post(
                TWITTERAPIIO_BASE_URL,
                json=payload,
                headers={"X-API-Key": api_key},
            )
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 60))
                raise ArenaRateLimitError(
                    "x_twitter: TwitterAPI.io 429 rate limit",
                    retry_after=retry_after,
                    arena=self.arena_name,
                    platform=self.platform_name,
                )
            if response.status_code in (401, 403):
                raise ArenaAuthError(
                    f"x_twitter: TwitterAPI.io auth error HTTP {response.status_code}",
                    arena=self.arena_name,
                    platform=self.platform_name,
                )
            response.raise_for_status()
            return response.json()
        except (ArenaRateLimitError, ArenaAuthError):
            raise
        except httpx.HTTPStatusError as exc:
            raise ArenaCollectionError(
                f"x_twitter: TwitterAPI.io HTTP {exc.response.status_code}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"x_twitter: TwitterAPI.io connection error: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

    async def _get_twitter_v2(
        self,
        client: httpx.AsyncClient,
        url: str,
        bearer_token: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """GET request to the X API v2 with Bearer token auth.

        Args:
            client: Shared HTTP client.
            url: Full endpoint URL.
            bearer_token: OAuth 2.0 bearer token.
            params: Query parameters.

        Returns:
            Tuple of (parsed JSON response dict, rate-limit headers dict).

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaAuthError: On HTTP 401/403.
            ArenaCollectionError: On other non-2xx or connection errors.
        """
        try:
            response = await client.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
            rate_headers: dict[str, str] = {
                "x-rate-limit-remaining": response.headers.get("x-rate-limit-remaining", ""),
                "x-rate-limit-reset": response.headers.get("x-rate-limit-reset", ""),
            }
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 60))
                raise ArenaRateLimitError(
                    "x_twitter: X API v2 429 rate limit",
                    retry_after=retry_after,
                    arena=self.arena_name,
                    platform=self.platform_name,
                )
            if response.status_code in (401, 403):
                raise ArenaAuthError(
                    f"x_twitter: X API v2 auth error HTTP {response.status_code}",
                    arena=self.arena_name,
                    platform=self.platform_name,
                )
            response.raise_for_status()
            return response.json(), rate_headers
        except (ArenaRateLimitError, ArenaAuthError):
            raise
        except httpx.HTTPStatusError as exc:
            raise ArenaCollectionError(
                f"x_twitter: X API v2 HTTP {exc.response.status_code}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"x_twitter: X API v2 connection error: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

    # ------------------------------------------------------------------
    # Rate limit helpers
    # ------------------------------------------------------------------

    async def _wait_rate_limit_medium(self, credential_id: str) -> None:
        """Wait for a rate-limit slot before a TwitterAPI.io call.

        Args:
            credential_id: Credential ID used as the Redis key suffix.
        """
        if self.rate_limiter is None:
            return
        key = f"ratelimit:{self.arena_name}:{self.platform_name}:{credential_id}"
        await self.rate_limiter.wait_for_slot(
            key=key,
            max_calls=MEDIUM_RATE_LIMIT_MAX_CALLS,
            window_seconds=MEDIUM_RATE_LIMIT_WINDOW_SECONDS,
        )

    async def _wait_rate_limit_premium(self, credential_id: str) -> None:
        """Wait for a rate-limit slot before an X API v2 call.

        Args:
            credential_id: Credential ID used as the Redis key suffix.
        """
        if self.rate_limiter is None:
            return
        key = f"ratelimit:{self.arena_name}:{self.platform_name}:{credential_id}"
        await self.rate_limiter.wait_for_slot(
            key=key,
            max_calls=PREMIUM_RATE_LIMIT_MAX_CALLS,
            window_seconds=PREMIUM_RATE_LIMIT_WINDOW_SECONDS,
        )

    async def _handle_v2_rate_headers(self, headers: dict[str, str]) -> None:
        """Log and adaptively sleep based on X API v2 rate-limit headers.

        Pauses execution when ``x-rate-limit-remaining`` reaches 0 to avoid
        a hard 429 on the next request.

        Args:
            headers: Dict with ``x-rate-limit-remaining`` and
                ``x-rate-limit-reset`` keys (may be empty strings).
        """
        import asyncio  # noqa: PLC0415
        import time  # noqa: PLC0415

        remaining_str = headers.get("x-rate-limit-remaining", "")
        reset_str = headers.get("x-rate-limit-reset", "")

        if remaining_str and remaining_str.isdigit() and int(remaining_str) == 0:
            if reset_str and reset_str.isdigit():
                wait = max(0.0, float(reset_str) - time.time())
                logger.warning(
                    "x_twitter: x-rate-limit-remaining=0, sleeping %.1f s until reset",
                    wait,
                )
                await asyncio.sleep(min(wait + 1.0, 900.0))

    # ------------------------------------------------------------------
    # Credential acquisition helpers
    # ------------------------------------------------------------------

    async def _acquire_medium_credential(self) -> dict[str, Any] | None:
        """Acquire a TwitterAPI.io credential from the pool.

        Returns:
            Credential dict or ``None`` if unavailable.
        """
        if self.credential_pool is None:
            return None
        return await self.credential_pool.acquire(platform="twitterapi_io", tier="medium")

    async def _acquire_premium_credential(self) -> dict[str, Any] | None:
        """Acquire an X API v2 Pro credential from the pool.

        Returns:
            Credential dict or ``None`` if unavailable.
        """
        if self.credential_pool is None:
            return None
        return await self.credential_pool.acquire(platform="x_twitter", tier="premium")


# ---------------------------------------------------------------------------
# Module-level utility functions
# ---------------------------------------------------------------------------


def _build_query(
    term: str,
    date_from: str | None,
    date_to: str | None,
) -> str:
    """Construct a search query string with Danish language and date operators.

    Args:
        term: Base search term or X operator query.
        date_from: ISO date lower bound (``YYYY-MM-DD``), optional.
        date_to: ISO date upper bound (``YYYY-MM-DD``), optional.

    Returns:
        Fully-constructed query string.
    """
    parts = [term, DANISH_LANG_OPERATOR]
    if date_from:
        parts.append(f"since:{date_from}")
    if date_to:
        parts.append(f"until:{date_to}")
    return " ".join(parts)


def _normalize_handle(actor_id: str) -> str:
    """Strip leading ``@`` from a Twitter handle or return numeric ID as-is.

    Args:
        actor_id: Twitter handle (with or without ``@``) or numeric user ID.

    Returns:
        Cleaned handle string without leading ``@``.
    """
    return actor_id.lstrip("@")


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


def _detect_tweet_type_twitterapiio(raw: dict[str, Any]) -> str:
    """Infer the tweet type from TwitterAPI.io boolean fields.

    Args:
        raw: Raw tweet object from TwitterAPI.io.

    Returns:
        One of ``"retweet"``, ``"reply"``, ``"quote_tweet"``, or ``"tweet"``.
    """
    if raw.get("isRetweet") or raw.get("is_retweet"):
        return "retweet"
    if raw.get("isReply") or raw.get("is_reply"):
        return "reply"
    if raw.get("isQuote") or raw.get("is_quote"):
        return "quote_tweet"
    return "tweet"


def _detect_tweet_type_v2(raw: dict[str, Any]) -> str:
    """Infer the tweet type from X API v2 ``referenced_tweets`` field.

    Args:
        raw: Raw tweet object from the v2 API.

    Returns:
        One of ``"retweet"``, ``"reply"``, ``"quote_tweet"``, or ``"tweet"``.
    """
    refs: list[dict[str, Any]] = raw.get("referenced_tweets") or []
    for ref in refs:
        ref_type = ref.get("type", "")
        if ref_type == "retweeted":
            return "retweet"
        if ref_type == "quoted":
            return "quote_tweet"
        if ref_type == "replied_to":
            return "reply"
    return "tweet"


def _extract_twitterapiio_media(raw: dict[str, Any]) -> list[str]:
    """Extract media URLs from a TwitterAPI.io tweet object.

    Args:
        raw: Raw tweet object.

    Returns:
        List of media URL strings (may be empty).
    """
    media: list[dict[str, Any]] = raw.get("media") or []
    urls: list[str] = []
    for item in media:
        if isinstance(item, dict):
            url = item.get("media_url_https") or item.get("url") or item.get("media_url")
            if url:
                urls.append(url)
    return urls


def _index_v2_users(users: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build a lookup dict of v2 user objects keyed by their numeric ID.

    Args:
        users: List of user objects from the ``includes.users`` field.

    Returns:
        Dict mapping string user ID to user object dict.
    """
    return {str(u.get("id", "")): u for u in users if u.get("id")}
