"""Bluesky arena collector implementation.

Collects posts from Bluesky via the AT Protocol public API (free, unauthenticated).

Two collection modes are supported:

- :meth:`BlueskyCollector.collect_by_terms` — full-text search via
  ``app.bsky.feed.searchPosts`` with ``lang=da`` filter and cursor pagination.
- :meth:`BlueskyCollector.collect_by_actors` — author feed retrieval via
  ``app.bsky.feed.getAuthorFeed`` with cursor pagination.

Rate limiting uses :meth:`RateLimiter.wait_for_slot` with key
``ratelimit:bluesky:public:{credential_id}``.

The :class:`BlueskyStreamer` class provides optional Jetstream firehose support
for real-time streaming collection.  It is NOT required by the batch Celery
tasks and is documented as a future enhancement.

All requests use Danish defaults: ``lang=da`` on term searches.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from issue_observatory.arenas.base import ArenaCollector, TemporalMode, Tier
from issue_observatory.arenas.query_builder import format_boolean_query_for_platform
from issue_observatory.arenas.bluesky.config import (
    BLUESKY_TIERS,
    BSKY_AUTHOR_FEED_ENDPOINT,
    BSKY_SEARCH_POSTS_ENDPOINT,
    BSKY_WEB_BASE,
    DANISH_LANG,
    MAX_RESULTS_PER_PAGE,
)
from issue_observatory.arenas.registry import register
from issue_observatory.config.tiers import TierConfig
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
)
from issue_observatory.core.normalizer import Normalizer

logger = logging.getLogger(__name__)

_RATE_LIMIT_ARENA: str = "bluesky"
_RATE_LIMIT_PROVIDER: str = "public"
_RATE_LIMIT_MAX_CALLS: int = 10
_RATE_LIMIT_WINDOW_SECONDS: int = 1


@register
class BlueskyCollector(ArenaCollector):
    """Collects Bluesky posts via the AT Protocol public API.

    Only ``Tier.FREE`` is supported — Bluesky does not have paid API tiers.
    No credentials are required for read-only public API access.

    Class Attributes:
        arena_name: ``"bluesky"``
        platform_name: ``"bluesky"``
        supported_tiers: ``[Tier.FREE]``

    Args:
        credential_pool: Optional; accepted for interface consistency but
            not required (Bluesky public API is unauthenticated).
        rate_limiter: Optional Redis-backed rate limiter.
        http_client: Optional injected :class:`httpx.AsyncClient` for testing.
    """

    arena_name: str = "bluesky"
    platform_name: str = "bluesky"
    supported_tiers: list[Tier] = [Tier.FREE]
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
        """Collect Bluesky posts matching one or more search terms.

        Uses ``app.bsky.feed.searchPosts`` with ``lang=da`` filter and
        cursor-based pagination.  Supports ISO 8601 ``since``/``until``
        date bounds via *date_from* / *date_to*.

        When ``term_groups`` is provided, each AND-group is serialised as a
        space-joined query (space = AND in Bluesky's search API) and executed
        as a separate request.  Results from all groups are combined and
        deduplicated by ``content_hash``.

        Only ``Tier.FREE`` is accepted.  Passing MEDIUM or PREMIUM logs a
        warning and falls back to FREE since no paid tier exists.

        Args:
            terms: Search terms (used when ``term_groups`` is ``None``).
            tier: Operational tier — only FREE is meaningful.
            date_from: Earliest post date (inclusive).
            date_to: Latest post date (inclusive).
            max_results: Upper bound on returned records.  ``None`` uses
                tier default.
            term_groups: Optional boolean AND/OR groups.  Each group issues
                a separate request with terms space-joined (AND).
            language_filter: Optional language codes.  Bluesky's ``lang``
                parameter accepts a single code; the first code in the list
                is used (default ``"da"`` from DANISH_LANG config).

        Returns:
            List of normalized content record dicts.

        Raises:
            ArenaRateLimitError: On HTTP 429 from the public API.
            ArenaCollectionError: On other unrecoverable API errors.
        """
        if tier != Tier.FREE:
            logger.warning(
                "bluesky: tier=%s requested but only FREE is available. "
                "Proceeding with FREE tier.",
                tier.value,
            )

        tier_config = self.get_tier_config(Tier.FREE)
        effective_max = (
            max_results
            if max_results is not None
            else (tier_config.max_results_per_run if tier_config else 10_000)
        )

        since_str = _to_iso_string(date_from)
        until_str = _to_iso_string(date_to)

        # Build query strings: boolean groups each become a space-joined query.
        if term_groups is not None:
            query_strings: list[str] = [
                format_boolean_query_for_platform(groups=[grp], platform="bluesky")
                for grp in term_groups
                if grp
            ]
        else:
            query_strings = list(terms)

        all_records: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()

        async with self._build_http_client() as client:
            for query in query_strings:
                if len(all_records) >= effective_max:
                    break
                remaining = effective_max - len(all_records)
                records = await self._search_term(
                    client=client,
                    term=query,
                    max_results=remaining,
                    since=since_str,
                    until=until_str,
                )
                for rec in records:
                    h = rec.get("content_hash", "")
                    if h and h in seen_hashes:
                        continue
                    if h:
                        seen_hashes.add(h)
                    all_records.append(rec)

        logger.info(
            "bluesky: collected %d posts for %d queries",
            len(all_records),
            len(query_strings),
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
        """Collect Bluesky posts published by specific actors.

        Uses ``app.bsky.feed.getAuthorFeed`` with cursor-based pagination.
        Each *actor_id* is a Bluesky DID (``did:plc:...``) or handle
        (``user.bsky.social``).  Date filtering is applied client-side.

        Args:
            actor_ids: Bluesky DIDs or handles to collect posts from.
            tier: Operational tier — only FREE is meaningful.
            date_from: Earliest post date (inclusive).
            date_to: Latest post date (inclusive).
            max_results: Upper bound on total records across all actors.

        Returns:
            List of normalized content record dicts.

        Raises:
            ArenaRateLimitError: On HTTP 429 from the public API.
            ArenaCollectionError: On other unrecoverable API errors.
        """
        if tier != Tier.FREE:
            logger.warning(
                "bluesky: tier=%s requested but only FREE is available. "
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

        all_records: list[dict[str, Any]] = []

        async with self._build_http_client() as client:
            for actor_id in actor_ids:
                if len(all_records) >= effective_max:
                    break
                remaining = effective_max - len(all_records)
                records = await self._fetch_author_feed(
                    client=client,
                    actor=actor_id,
                    max_results=remaining,
                    date_from=date_from_dt,
                    date_to=date_to_dt,
                )
                all_records.extend(records)

        logger.info(
            "bluesky: collected %d posts for %d actors",
            len(all_records),
            len(actor_ids),
        )
        return all_records

    def get_tier_config(self, tier: Tier) -> TierConfig | None:
        """Return the tier configuration for this arena.

        Args:
            tier: The requested operational tier.

        Returns:
            :class:`TierConfig` for FREE.  ``None`` for MEDIUM and PREMIUM.
        """
        return BLUESKY_TIERS.get(tier)

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single Bluesky post view to the universal schema.

        Maps AT Protocol post view fields to the universal content record
        schema.  The ``platform_id`` is set to the AT URI.  The web URL
        is constructed from the AT URI components.

        Expected input fields (from ``searchPosts`` or ``getAuthorFeed``):
        - ``uri``: AT URI (``at://did:plc:.../app.bsky.feed.post/rkey``).
        - ``author``: Dict with ``did``, ``handle``, ``displayName``.
        - ``record``: Dict with ``text``, ``createdAt``, ``langs``, etc.
        - ``likeCount``, ``repostCount``, ``replyCount``: Engagement.
        - ``embed`` (optional): Embedded media/links/quotes.

        Args:
            raw_item: Raw post view dict from the AT Protocol API.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        author = raw_item.get("author") or {}
        record = raw_item.get("record") or {}

        did = author.get("did", "")
        handle = author.get("handle", did)
        display_name = author.get("displayName") or handle

        uri = raw_item.get("uri", "")
        rkey = _parse_rkey_from_uri(uri)
        web_url = f"{BSKY_WEB_BASE}/profile/{handle}/post/{rkey}" if rkey else None

        langs = record.get("langs") or []
        language = langs[0] if langs else None

        # Build a flat dict matching the Normalizer's expected field names.
        flat: dict[str, Any] = {
            "id": uri,
            "platform_id": uri,
            "content_type": "post",
            "text_content": record.get("text", ""),
            "title": None,
            "url": web_url,
            "language": language,
            "published_at": record.get("createdAt"),
            "author_platform_id": did,
            "author_display_name": display_name,
            "likes_count": raw_item.get("likeCount"),
            "shares_count": raw_item.get("repostCount"),
            "comments_count": raw_item.get("replyCount"),
            # Raw metadata: preserve the full post view.
            "embed": raw_item.get("embed"),
            "facets": record.get("facets"),
            "labels": raw_item.get("labels"),
            "reply_ref": record.get("reply"),
        }

        # Extract media URLs from image embeds.
        media_urls = _extract_media_urls(raw_item.get("embed"))
        if media_urls:
            flat["media_urls"] = media_urls

        normalized = self._normalizer.normalize(
            raw_item=flat,
            platform=self.platform_name,
            arena=self.arena_name,
            collection_tier="free",
        )
        # Ensure platform_id is the AT URI (Normalizer may pick up 'id' field too).
        normalized["platform_id"] = uri
        return normalized

    async def health_check(self) -> dict[str, Any]:
        """Verify that the Bluesky public API is reachable.

        Sends a minimal ``searchPosts`` request with ``q=test&limit=1`` and
        verifies a valid JSON response is returned.

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
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    BSKY_SEARCH_POSTS_ENDPOINT,
                    params={"q": "test", "limit": 1},
                )
                response.raise_for_status()
                data = response.json()
                if "posts" not in data:
                    return {
                        **base,
                        "status": "degraded",
                        "detail": "Response missing 'posts' key.",
                    }
                return {**base, "status": "ok"}
        except httpx.HTTPStatusError as exc:
            return {
                **base,
                "status": "degraded",
                "detail": f"HTTP {exc.response.status_code} from Bluesky public API",
            }
        except httpx.RequestError as exc:
            return {**base, "status": "down", "detail": f"Connection error: {exc}"}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_http_client(self) -> httpx.AsyncClient:
        """Return an :class:`httpx.AsyncClient` for use as a context manager."""
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]
        return httpx.AsyncClient(timeout=30.0)

    async def _wait_for_rate_limit(self, credential_id: str = "default") -> None:
        """Wait for a rate-limit slot before making an API call.

        Args:
            credential_id: Suffix for the Redis rate-limit key.
        """
        if self.rate_limiter is None:
            return
        key = f"ratelimit:{_RATE_LIMIT_ARENA}:{_RATE_LIMIT_PROVIDER}:{credential_id}"
        await self.rate_limiter.wait_for_slot(
            key=key,
            max_calls=_RATE_LIMIT_MAX_CALLS,
            window_seconds=_RATE_LIMIT_WINDOW_SECONDS,
        )

    async def _make_request(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Make a rate-limited GET request to the Bluesky public API.

        Args:
            client: Shared HTTP client.
            url: Endpoint URL.
            params: Query parameters.

        Returns:
            Parsed JSON response dict.

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaCollectionError: On other non-2xx responses or connection errors.
        """
        await self._wait_for_rate_limit()
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                retry_after = float(exc.response.headers.get("Retry-After", 60))
                raise ArenaRateLimitError(
                    f"bluesky: 429 rate limit",
                    retry_after=retry_after,
                    arena=self.arena_name,
                    platform=self.platform_name,
                ) from exc
            raise ArenaCollectionError(
                f"bluesky: HTTP {exc.response.status_code} from public API",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"bluesky: connection error: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

    async def _search_term(
        self,
        client: httpx.AsyncClient,
        term: str,
        max_results: int,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        """Paginate through searchPosts results for a single term.

        Appends ``lang=da`` to all requests.  Pagination continues via the
        ``cursor`` field in the response until exhausted or *max_results*
        is reached.

        Args:
            client: Shared HTTP client.
            term: Search query string.
            max_results: Maximum records to retrieve.
            since: ISO 8601 lower date bound (optional).
            until: ISO 8601 upper date bound (optional).

        Returns:
            List of normalized records.
        """
        records: list[dict[str, Any]] = []
        cursor: str | None = None

        while len(records) < max_results:
            page_size = min(MAX_RESULTS_PER_PAGE, max_results - len(records))
            params: dict[str, Any] = {
                "q": term,
                "lang": DANISH_LANG,
                "limit": page_size,
            }
            if since:
                params["since"] = since
            if until:
                params["until"] = until
            if cursor:
                params["cursor"] = cursor

            data = await self._make_request(client, BSKY_SEARCH_POSTS_ENDPOINT, params)

            posts = data.get("posts", [])
            if not posts:
                break

            for post in posts:
                if len(records) >= max_results:
                    break
                records.append(self.normalize(post))

            cursor = data.get("cursor")
            if not cursor:
                break  # No more pages.

        return records

    async def _fetch_author_feed(
        self,
        client: httpx.AsyncClient,
        actor: str,
        max_results: int,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Paginate through getAuthorFeed for a single actor.

        Date filtering is applied client-side after retrieval.  Pagination
        stops early when ``published_at`` falls before *date_from* (posts
        are returned in reverse-chronological order).

        Args:
            client: Shared HTTP client.
            actor: Bluesky DID or handle.
            max_results: Maximum records to retrieve.
            date_from: Earliest post date filter.
            date_to: Latest post date filter.

        Returns:
            List of normalized records within the date range.
        """
        records: list[dict[str, Any]] = []
        cursor: str | None = None

        while len(records) < max_results:
            page_size = min(MAX_RESULTS_PER_PAGE, max_results - len(records))
            params: dict[str, Any] = {"actor": actor, "limit": page_size}
            if cursor:
                params["cursor"] = cursor

            data = await self._make_request(client, BSKY_AUTHOR_FEED_ENDPOINT, params)

            feed = data.get("feed", [])
            if not feed:
                break

            stop_early = False
            for feed_item in feed:
                post = feed_item.get("post") or feed_item
                record_data = post.get("record") or {}
                created_at_str = record_data.get("createdAt")

                if created_at_str and date_from:
                    created_at = _parse_datetime(created_at_str)
                    if created_at and created_at < date_from:
                        stop_early = True
                        break

                if created_at_str and date_to:
                    created_at = _parse_datetime(created_at_str)
                    if created_at and created_at > date_to:
                        continue

                # Apply client-side language filter to restrict posts to Danish.
                # The AT Protocol getAuthorFeed endpoint does not support a lang
                # query parameter (unlike searchPosts), so filtering must happen
                # here after retrieval.  BCP-47 language tags are in the record's
                # "langs" array.  Posts with no "langs" field are included because
                # their language is undeclared and may be Danish; posts with a
                # "langs" list that does not contain "da" are excluded.
                post_langs = record_data.get("langs")
                if post_langs and DANISH_LANG not in post_langs:
                    continue

                if len(records) >= max_results:
                    break
                records.append(self.normalize(post))

            cursor = data.get("cursor")
            if not cursor or stop_early:
                break

        return records


# ---------------------------------------------------------------------------
# BlueskyStreamer — optional Jetstream firehose support
# ---------------------------------------------------------------------------


class BlueskyStreamer:
    """Optional Jetstream firehose client for real-time Bluesky post streaming.

    This class connects to a Jetstream WebSocket endpoint and streams new
    Bluesky posts in real time.  It is NOT required by the batch Celery tasks
    and is documented as a future enhancement for live tracking.

    Usage::

        streamer = BlueskyStreamer(
            collector=BlueskyCollector(),
            on_record=lambda record: print(record),
        )
        await streamer.run()

    Notes:
        - Requires the ``websockets`` package (not installed by default).
        - No language filter is available on the Jetstream; Danish posts must
          be filtered client-side using the ``lang`` field in post records.
        - Store the cursor (Unix microsecond timestamp) for reconnection.
        - Exponential backoff is applied on disconnect.

    Args:
        collector: A :class:`BlueskyCollector` instance used for normalization.
        on_record: Async callback invoked with each normalized post record.
        endpoint: Jetstream WebSocket URL.  Defaults to the first US-East endpoint.
        wanted_dids: Optional list of DIDs to filter (up to 10,000).
    """

    DEFAULT_ENDPOINT: str = "wss://jetstream1.us-east.bsky.network/subscribe"

    def __init__(
        self,
        collector: BlueskyCollector,
        on_record: Any,
        endpoint: str | None = None,
        wanted_dids: list[str] | None = None,
    ) -> None:
        self._collector = collector
        self._on_record = on_record
        self._endpoint = endpoint or self.DEFAULT_ENDPOINT
        self._wanted_dids = wanted_dids or []
        self._cursor: str | None = None

    async def run(self) -> None:
        """Connect to Jetstream and stream posts indefinitely.

        Applies exponential backoff on disconnect (1s → 2s → 4s → ... → 60s).

        Raises:
            ImportError: If the ``websockets`` package is not installed.
        """
        try:
            import websockets  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "The 'websockets' package is required for BlueskyStreamer. "
                "Install it with: pip install websockets"
            ) from exc

        import asyncio  # noqa: PLC0415
        import json  # noqa: PLC0415

        backoff = 1.0
        logger.info("bluesky: BlueskyStreamer starting on %s", self._endpoint)

        while True:
            url = self._endpoint
            params_parts = ["wantedCollections=app.bsky.feed.post"]
            if self._wanted_dids:
                params_parts.append(
                    "&".join(f"wantedDids={d}" for d in self._wanted_dids)
                )
            if self._cursor:
                params_parts.append(f"cursor={self._cursor}")
            if params_parts:
                url = f"{url}?{'&'.join(params_parts)}"

            try:
                async with websockets.connect(url) as ws:
                    backoff = 1.0
                    logger.info("bluesky: BlueskyStreamer connected.")
                    async for message in ws:
                        try:
                            event = json.loads(message)
                        except Exception:
                            continue

                        self._cursor = str(event.get("time_us", ""))

                        commit = event.get("commit") or {}
                        record_data = commit.get("record") or {}
                        if event.get("kind") != "commit":
                            continue
                        if commit.get("collection") != "app.bsky.feed.post":
                            continue

                        # Filter by language client-side.
                        langs = record_data.get("langs") or []
                        if langs and "da" not in langs:
                            continue

                        # Build a minimal post view for normalization.
                        post_view: dict[str, Any] = {
                            "uri": f"at://{event.get('did', '')}/app.bsky.feed.post/{commit.get('rkey', '')}",
                            "author": {"did": event.get("did", ""), "handle": "", "displayName": ""},
                            "record": record_data,
                            "likeCount": 0,
                            "repostCount": 0,
                            "replyCount": 0,
                        }
                        normalized = self._collector.normalize(post_view)
                        await self._on_record(normalized)

            except Exception as exc:
                logger.warning(
                    "bluesky: BlueskyStreamer disconnected (%s). Reconnecting in %.0fs.",
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)


# ---------------------------------------------------------------------------
# Module-level utility functions
# ---------------------------------------------------------------------------


def _parse_rkey_from_uri(uri: str) -> str | None:
    """Extract the record key (rkey) from an AT URI.

    AT URI format: ``at://did:plc:xxxx/app.bsky.feed.post/yyyy``

    Args:
        uri: AT Protocol URI string.

    Returns:
        The rkey string, or ``None`` if parsing fails.
    """
    if not uri or not uri.startswith("at://"):
        return None
    parts = uri.split("/")
    # at:// did collection rkey → index 2=did, 3=collection, 4=rkey
    # Split: ['at:', '', 'did:plc:xxx', 'app.bsky.feed.post', 'yyy']
    if len(parts) >= 5:
        return parts[4] or None
    return None


def _extract_media_urls(embed: Any) -> list[str]:
    """Extract image URLs from a Bluesky post embed object.

    Handles:
    - ``app.bsky.embed.images`` — list of image objects with ``fullsize``.
    - ``app.bsky.embed.recordWithMedia`` — quoted post with images.

    Args:
        embed: The embed object from the post view, or ``None``.

    Returns:
        List of image URL strings (may be empty).
    """
    if not embed or not isinstance(embed, dict):
        return []

    embed_type = embed.get("$type", "")
    urls: list[str] = []

    if "images" in embed:
        for img in embed["images"]:
            if isinstance(img, dict):
                url = img.get("fullsize") or img.get("thumb")
                if url:
                    urls.append(url)

    if embed_type == "app.bsky.embed.recordWithMedia":
        media = embed.get("media") or {}
        urls.extend(_extract_media_urls(media))

    return urls


def _to_iso_string(value: datetime | str | None) -> str | None:
    """Convert a datetime or string to an ISO 8601 string.

    Args:
        value: Datetime object, ISO 8601 string, or ``None``.

    Returns:
        ISO 8601 string or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return None


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
