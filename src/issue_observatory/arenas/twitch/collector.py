"""Twitch arena collector — DEFERRED stub implementation.

Implements channel discovery via the Twitch Helix REST API. This is a
partial implementation covering the batch API use case only. Real-time chat
collection via the EventSub WebSocket is NOT implemented here.

IMPORTANT ARCHITECTURAL CONSTRAINT: Twitch does not expose any endpoint for
retrieving historical chat messages. Once a stream ends, chat is gone. The
only way to capture Twitch chat is via the EventSub ``channel.chat.message``
subscription type while the stream is live. This requires:

    1. A persistent WebSocket connection (streaming worker).
    2. An OAuth user access token with ``user:read:chat`` scope.
    3. EventSub subscription registration per channel.

The batch methods here (``collect_by_terms``, ``collect_by_actors``) return
**channel metadata records**, not chat messages. They are useful for channel
discovery and building the ``DANISH_TWITCH_CHANNELS`` watchlist.

Collection modes:
    - ``collect_by_terms``: ``GET /search/channels`` — discovers channels by
      name query. Returns channel metadata records.
    - ``collect_by_actors``: ``GET /search/channels`` per broadcaster login —
      returns channel metadata for known actor names.
    - Streaming (future): ``TwitchStreamer`` class via EventSub WebSocket.

Credentials: Stored in the CredentialPool with ``platform="twitch"`` and JSON
fields ``{"client_id": "...", "client_secret": "...", "user_token": "..."}``.
The app access token (Client Credentials grant) is obtained on demand.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from issue_observatory.arenas.base import ArenaCollector, TemporalMode, Tier
from issue_observatory.arenas.registry import register
from issue_observatory.arenas.twitch.config import (
    DEFAULT_MAX_RESULTS,
    HEALTH_CHECK_ENDPOINT,
    SEARCH_RESULTS_PER_REQUEST,
    TWITCH_API_BASE,
    TWITCH_TIERS,
    TWITCH_TOKEN_URL,
)
from issue_observatory.config.tiers import TierConfig
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.core.normalizer import Normalizer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


@register
class TwitchCollector(ArenaCollector):
    """Discovers Twitch channels via the Helix REST API.

    DEFERRED STUB: This collector implements channel discovery only. Real-time
    chat collection requires a ``TwitchStreamer`` class using the EventSub
    WebSocket (``channel.chat.message`` subscription type) and is not yet
    implemented.

    The batch ``collect_by_terms`` and ``collect_by_actors`` methods return
    **channel metadata records** (content_type ``"chat_message"`` per the UCR
    spec for Twitch), not actual chat messages. Chat is streaming-only on Twitch.

    Supported tiers:
        - ``Tier.FREE`` — Twitch Helix API; client_id + client_secret required.

    Class Attributes:
        arena_name: ``"social_media"``
        platform_name: ``"twitch"``
        supported_tiers: ``[Tier.FREE]``

    Args:
        credential_pool: CredentialPool with ``platform="twitch"`` credential
            containing ``{"client_id": "...", "client_secret": "...", "user_token": "..."}``.
        rate_limiter: Optional shared rate limiter.
        http_client: Optional injected :class:`httpx.AsyncClient` for testing.
    """

    arena_name: str = "social_media"
    platform_name: str = "twitch"
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
        # Cached app access token to avoid re-fetching on every request
        self._app_token: str | None = None

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
        """Discover Twitch channels matching the supplied search terms.

        Uses ``GET /search/channels`` to find channels whose name or title
        matches each term. Returns **channel metadata records**, NOT chat
        messages. Chat is streaming-only — there is no batch chat endpoint.

        Real-time chat collection requires the streaming worker and EventSub
        WebSocket integration. This batch method only returns channel metadata
        that can be used to populate the ``DANISH_TWITCH_CHANNELS`` watchlist.

        Date range filtering is NOT supported by the Twitch search API.
        ``date_from`` and ``date_to`` parameters are accepted for interface
        compatibility but are ignored.

        Args:
            terms: Channel name search queries (each term = one API call).
            tier: Must be ``Tier.FREE``.
            date_from: Ignored — Twitch search has no date filter.
            date_to: Ignored — Twitch search has no date filter.
            max_results: Upper bound on returned channel metadata records.
            term_groups: Ignored — Twitch search is term-by-term.
            language_filter: Optional ISO 639-1 codes; matched against
                ``broadcaster_language`` on returned channels.

        Returns:
            List of normalized channel metadata record dicts.

        Raises:
            ValueError: If *tier* is not ``Tier.FREE``.
            ArenaCollectionError: On unrecoverable Helix API failure.
            ArenaRateLimitError: On HTTP 429.
            NoCredentialAvailableError: If no Twitch credentials are available.
        """
        self._validate_tier(tier)
        effective_max = max_results if max_results is not None else DEFAULT_MAX_RESULTS

        logger.info(
            "twitch: collect_by_terms — terms=%d max=%d tier=%s",
            len(terms),
            effective_max,
            tier.value,
        )
        logger.info(
            "twitch: STUB — returning channel metadata only. "
            "Real-time chat requires the EventSub streaming worker (not yet implemented)."
        )

        if date_from or date_to:
            logger.info(
                "twitch: date_from/date_to ignored — Twitch search API has no date filter."
            )

        creds = await self._acquire_credentials()
        app_token = await self._get_app_token(creds)

        all_records: list[dict[str, Any]] = []
        language_set = set(language_filter) if language_filter else None

        async with self._build_http_client(creds["client_id"], app_token) as client:
            for term in terms:
                if len(all_records) >= effective_max:
                    break

                channels = await self._search_channels(
                    client=client,
                    query=term,
                    max_count=effective_max - len(all_records),
                )

                for ch in channels:
                    if language_set and ch.get("broadcaster_language") not in language_set:
                        continue

                    record = self.normalize(ch)
                    all_records.append(record)

                    if len(all_records) >= effective_max:
                        break

        logger.info(
            "twitch: collect_by_terms complete — channels=%d", len(all_records)
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
        """Retrieve Twitch channel metadata for known broadcaster logins.

        Uses ``GET /search/channels`` for each actor ID (interpreted as a
        broadcaster login name). Returns channel metadata records, NOT chat.

        Real-time chat collection requires the streaming worker and EventSub
        WebSocket integration. This batch method only returns channel metadata.

        Args:
            actor_ids: Twitch broadcaster login names (e.g. ``["shroud", "pokimane"]``).
            tier: Must be ``Tier.FREE``.
            date_from: Ignored — Twitch has no historical chat API.
            date_to: Ignored.
            max_results: Upper bound on returned channel metadata records.

        Returns:
            List of normalized channel metadata record dicts.

        Raises:
            ValueError: If *tier* is not ``Tier.FREE``.
            ArenaCollectionError: On unrecoverable Helix API failure.
            ArenaRateLimitError: On HTTP 429.
            NoCredentialAvailableError: If no Twitch credentials are available.
        """
        self._validate_tier(tier)
        effective_max = max_results if max_results is not None else DEFAULT_MAX_RESULTS

        logger.info(
            "twitch: collect_by_actors — actors=%d max=%d tier=%s",
            len(actor_ids),
            effective_max,
            tier.value,
        )
        logger.info(
            "twitch: STUB — returning channel metadata only. "
            "Real-time chat requires the EventSub streaming worker (not yet implemented)."
        )

        creds = await self._acquire_credentials()
        app_token = await self._get_app_token(creds)

        all_records: list[dict[str, Any]] = []

        async with self._build_http_client(creds["client_id"], app_token) as client:
            for actor_id in actor_ids:
                if len(all_records) >= effective_max:
                    break

                # Search by exact broadcaster login name
                channels = await self._search_channels(
                    client=client,
                    query=actor_id,
                    max_count=effective_max - len(all_records),
                )

                # Filter to exact login match where possible
                login_lower = actor_id.lower()
                matched = [
                    ch for ch in channels
                    if ch.get("broadcaster_login", "").lower() == login_lower
                ]
                # Fall back to all results if no exact match
                if not matched:
                    matched = channels

                for ch in matched:
                    record = self.normalize(ch)
                    all_records.append(record)

                    if len(all_records) >= effective_max:
                        break

        logger.info(
            "twitch: collect_by_actors complete — channels=%d", len(all_records)
        )
        return all_records

    def get_tier_config(self, tier: Tier) -> TierConfig:
        """Return tier configuration for the Twitch arena.

        Args:
            tier: Requested operational tier.

        Returns:
            :class:`~issue_observatory.config.tiers.TierConfig` for FREE tier.

        Raises:
            ValueError: If *tier* is not in ``supported_tiers``.
        """
        if tier not in TWITCH_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}' for twitch. "
                f"Valid tiers: {list(TWITCH_TIERS.keys())}"
            )
        return TWITCH_TIERS[tier]

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw Twitch channel metadata dict to the universal schema.

        Note: This normalizes CHANNEL METADATA, not chat messages. Chat
        messages are only available via the EventSub streaming worker
        (not yet implemented). The ``content_type`` is set to
        ``"chat_message"`` per the UCR spec for Twitch, but the actual
        content here is channel metadata.

        Real-time chat collection requires the streaming worker and EventSub
        WebSocket integration. This method only handles channel metadata.

        Args:
            raw_item: Raw channel dict from the Twitch Helix ``/search/channels``
                response.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        channel = raw_item
        channel_id = str(channel.get("id", ""))
        broadcaster_login = channel.get("broadcaster_login", "")
        broadcaster_language = channel.get("broadcaster_language")

        normalized_raw: dict[str, Any] = {
            "id": channel_id,
            "platform_id": channel_id,
            "content_type": "chat_message",  # Per UCR spec for Twitch
            "text_content": channel.get("title"),
            "title": channel.get("display_name"),
            "url": f"https://twitch.tv/{broadcaster_login}" if broadcaster_login else None,
            "language": broadcaster_language,
            "published_at": None,  # No timestamp on channel metadata
            "author_platform_id": channel_id,
            "author_display_name": channel.get("display_name", broadcaster_login),
            "views_count": None,
            "likes_count": None,
            "shares_count": None,
            "comments_count": None,
            "raw_metadata": {
                "broadcaster_login": broadcaster_login,
                "broadcaster_language": broadcaster_language,
                "game_id": channel.get("game_id"),
                "game_name": channel.get("game_name"),
                "is_live": channel.get("is_live"),
                "tags": channel.get("tags", []),
                "thumbnail_url": channel.get("thumbnail_url"),
                "started_at": channel.get("started_at"),
                "_collection_note": (
                    "Channel metadata only — chat messages require EventSub streaming worker"
                ),
            },
        }

        return self._normalizer.normalize(
            raw_item=normalized_raw,
            platform=self.platform_name,
            arena=self.arena_name,
            collection_tier="free",
            search_terms_matched=[],
        )

    async def health_check(self) -> dict[str, Any]:
        """Verify that the Twitch Helix API is reachable and credentials are valid.

        Calls ``GET /streams?first=1`` with an app access token. A 200 response
        confirms the API is reachable and the credentials authenticate correctly.

        Returns:
            Dict with ``status`` (``"ok"`` | ``"down"``), ``arena``,
            ``platform``, ``checked_at``, and optionally ``detail``.
        """
        checked_at = datetime.now(timezone.utc).isoformat() + "Z"
        base: dict[str, Any] = {
            "arena": self.arena_name,
            "platform": self.platform_name,
            "checked_at": checked_at,
        }

        try:
            creds = await self._acquire_credentials()
            app_token = await self._get_app_token(creds)
        except NoCredentialAvailableError as exc:
            return {
                **base,
                "status": "down",
                "detail": f"No Twitch credentials available: {exc}",
            }
        except ArenaCollectionError as exc:
            return {
                **base,
                "status": "down",
                "detail": f"Failed to obtain app access token: {exc}",
            }

        url = f"{TWITCH_API_BASE}{HEALTH_CHECK_ENDPOINT}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    url,
                    params={"first": 1},
                    headers={
                        "Client-Id": creds["client_id"],
                        "Authorization": f"Bearer {app_token}",
                    },
                )
                response.raise_for_status()
                data = response.json()
                stream_count = len(data.get("data", []))
                return {
                    **base,
                    "status": "ok",
                    "detail": f"Helix API reachable; streams_returned={stream_count}",
                }
        except httpx.HTTPStatusError as exc:
            return {
                **base,
                "status": "down",
                "detail": f"HTTP {exc.response.status_code} from {url}",
            }
        except httpx.RequestError as exc:
            return {**base, "status": "down", "detail": f"Connection error: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {**base, "status": "down", "detail": f"Unexpected error: {exc}"}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _acquire_credentials(self) -> dict[str, str]:
        """Retrieve Twitch credentials from the credential pool.

        Returns:
            Dict with ``client_id``, ``client_secret``, and optionally
            ``user_token``.

        Raises:
            NoCredentialAvailableError: If the pool is absent or has no
                active Twitch credential.
        """
        if self.credential_pool is None:
            raise NoCredentialAvailableError(platform="twitch", tier="free")

        credential = await self.credential_pool.acquire(
            platform="twitch", tier="free"
        )
        if credential is None:
            raise NoCredentialAvailableError(platform="twitch", tier="free")

        client_id = credential.get("client_id")
        client_secret = credential.get("client_secret")
        if not client_id or not client_secret:
            raise NoCredentialAvailableError(platform="twitch", tier="free")

        return {
            "client_id": str(client_id),
            "client_secret": str(client_secret),
            "user_token": str(credential.get("user_token", "")),
        }

    async def _get_app_token(self, creds: dict[str, str]) -> str:
        """Obtain a Twitch app access token via the Client Credentials grant.

        Caches the token in ``self._app_token`` for the lifetime of the
        collector instance.

        Args:
            creds: Credential dict with ``client_id`` and ``client_secret``.

        Returns:
            App access token string.

        Raises:
            ArenaCollectionError: If the token request fails.
        """
        if self._app_token:
            return self._app_token

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    TWITCH_TOKEN_URL,
                    data={
                        "client_id": creds["client_id"],
                        "client_secret": creds["client_secret"],
                        "grant_type": "client_credentials",
                    },
                )
                response.raise_for_status()
                data = response.json()
                token = data.get("access_token")
                if not token:
                    raise ArenaCollectionError(
                        "twitch: token response missing 'access_token' field",
                        arena=self.arena_name,
                        platform=self.platform_name,
                    )
                self._app_token = str(token)
                return self._app_token
        except httpx.HTTPStatusError as exc:
            raise ArenaCollectionError(
                f"twitch: failed to obtain app access token: HTTP {exc.response.status_code}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"twitch: connection error obtaining app access token: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

    def _build_http_client(
        self,
        client_id: str,
        app_token: str,
    ) -> httpx.AsyncClient:
        """Build an :class:`httpx.AsyncClient` with Twitch Helix authentication.

        Args:
            client_id: Twitch application Client ID for the ``Client-Id`` header.
            app_token: App access token for the ``Authorization`` header.

        Returns:
            Configured :class:`httpx.AsyncClient` context manager.
        """
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]
        return httpx.AsyncClient(
            base_url=TWITCH_API_BASE,
            headers={
                "Client-Id": client_id,
                "Authorization": f"Bearer {app_token}",
                "User-Agent": "IssueObservatory/1.0 (twitch-collector; research tool)",
            },
            timeout=30.0,
        )

    async def _search_channels(
        self,
        client: httpx.AsyncClient,
        query: str,
        max_count: int,
    ) -> list[dict[str, Any]]:
        """Search for Twitch channels matching a query string.

        Paginates through ``GET /search/channels`` results using the
        ``after`` cursor until ``max_count`` is reached.

        Args:
            client: Authenticated Helix HTTP client.
            query: Channel name search query.
            max_count: Maximum channels to return.

        Returns:
            List of raw channel dicts from the Helix API.
        """
        channels: list[dict[str, Any]] = []
        cursor: str | None = None

        while len(channels) < max_count:
            params: dict[str, Any] = {
                "query": query,
                "first": min(SEARCH_RESULTS_PER_REQUEST, max_count - len(channels)),
            }
            if cursor:
                params["after"] = cursor

            try:
                response = await client.get("/search/channels", params=params)
            except httpx.RequestError as exc:
                raise ArenaCollectionError(
                    f"twitch: request error on /search/channels: {exc}",
                    arena=self.arena_name,
                    platform=self.platform_name,
                ) from exc

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "60"))
                raise ArenaRateLimitError(
                    f"twitch: rate limited on /search/channels; retry_after={retry_after}s",
                    retry_after=retry_after,
                    arena=self.arena_name,
                    platform=self.platform_name,
                )

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ArenaCollectionError(
                    f"twitch: HTTP {exc.response.status_code} on /search/channels",
                    arena=self.arena_name,
                    platform=self.platform_name,
                ) from exc

            data = response.json()
            batch = data.get("data", [])
            channels.extend(batch)

            pagination = data.get("pagination", {})
            cursor = pagination.get("cursor")

            if not cursor or len(batch) < SEARCH_RESULTS_PER_REQUEST:
                break

        return channels[:max_count]
