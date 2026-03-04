"""Discord arena collector implementation.

Fetches messages from curated Discord server channels using the Discord Bot
REST API (v10). Supports two collection modes:

- **collect_by_terms()**: Fetches messages from configured channels and filters
  client-side by term occurrence in message content. Discord bots cannot use
  the search endpoint — all term matching happens after retrieval.
- **collect_by_actors()**: Fetches all messages from monitored channels and
  filters by ``author.id`` matching provided Discord user snowflake IDs.

A bot token credential is required for all collection. The token is retrieved
from the CredentialPool with ``platform="discord", tier="free"``. The
credential JSON must contain ``{"bot_token": "..."}``.

Rate limiting is implemented by parsing ``X-RateLimit-Remaining`` and
``X-RateLimit-Reset`` response headers (see :mod:`._http`). When
``X-RateLimit-Remaining == 0`` the collector sleeps until the reset timestamp
before issuing the next request.

All messages are normalized to the universal ``content_records`` schema by
:meth:`normalize`. HTTP helpers and pagination logic live in :mod:`._http`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from issue_observatory.arenas.base import ArenaCollector, TemporalMode, Tier
from issue_observatory.arenas.discord._http import (
    enrich_message,
    fetch_channel_messages,
    make_request,
    parse_date_bound,
)
from issue_observatory.arenas.discord.config import (
    DEFAULT_MAX_RESULTS,
    DISCORD_API_BASE,
    DISCORD_TIERS,
)
from issue_observatory.arenas.registry import register
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
class DiscordCollector(ArenaCollector):
    """Collects messages from curated Discord server channels.

    Supported tiers:
        - ``Tier.FREE`` — Discord Bot REST API; bot token credential required.

    Discord does not provide a keyword search endpoint for bots. Term matching
    is applied client-side after fetching all messages from configured channels.
    Researchers must curate a list of channel IDs and have the bot invited to
    each target server by its administrator.

    Class Attributes:
        arena_name: ``"social_media"``
        platform_name: ``"discord"``
        supported_tiers: ``[Tier.FREE]``

    Args:
        credential_pool: CredentialPool instance used to acquire the bot token.
            A credential with ``platform="discord"`` and JSON field
            ``{"bot_token": "..."}`` must exist.
        rate_limiter: Optional shared rate limiter (not actively used; header-
            based adaptive limiting is used instead via :mod:`._http`).
        http_client: Optional injected :class:`httpx.AsyncClient`. Inject for
            testing. If ``None``, a new client is created per collection call.
    """

    arena_name: str = "social_media"
    platform_name: str = "discord"
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
        channel_ids: list[str] | None = None,
        extra_channel_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Collect Discord messages matching any of the supplied terms.

        Fetches all messages from the provided channels and filters client-side
        by term occurrence in message content.

        NOTE: Discord does not support server-side keyword search for bot
        accounts. The ``/channels/{id}/messages/search`` endpoint is restricted
        to user tokens. All term matching happens client-side after full message
        retrieval from each channel.

        Boolean logic is applied when ``term_groups`` is provided:
        a message matches when at least one AND-group has all its terms present
        in the message content (group = AND, groups = OR).

        Args:
            terms: Search terms for case-insensitive substring matching
                (used when ``term_groups`` is ``None``).
            tier: Must be ``Tier.FREE``.
            date_from: Earliest publication date to include (inclusive).
            date_to: Latest publication date to include (inclusive).
            max_results: Upper bound on returned records.
            term_groups: Optional boolean AND/OR groups for client-side
                filtering.
            language_filter: Not used — Discord messages carry no language
                field. Language detection happens downstream.
            channel_ids: List of Discord channel snowflake IDs to fetch
                messages from. Required — Discord bots have no global search.
            extra_channel_ids: Optional list of additional channel snowflake
                IDs supplied by the researcher via
                ``arenas_config["discord"]["custom_channel_ids"]`` (GR-04).
                These are merged with ``channel_ids`` before fetching.

        Returns:
            List of normalized content record dicts.

        Raises:
            ValueError: If *tier* is not ``Tier.FREE``.
            ArenaCollectionError: If no channel IDs are provided, or on
                unrecoverable API failure.
            ArenaRateLimitError: On HTTP 429 from the Discord API.
            NoCredentialAvailableError: If no bot token is available.
        """
        self._validate_tier(tier)
        effective_max = max_results if max_results is not None else DEFAULT_MAX_RESULTS

        # GR-04: merge researcher-supplied extra channel IDs with explicitly
        # provided channel_ids (deduplicating by snowflake string value).
        effective_channel_ids = _merge_channel_ids(channel_ids, extra_channel_ids)

        if not effective_channel_ids:
            raise ArenaCollectionError(
                "Discord requires explicit channel_ids — there is no global keyword "
                "search for bot accounts. Pass channel_ids=[...] with the snowflake "
                "IDs of the channels you want to search.",
                arena=self.arena_name,
                platform=self.platform_name,
            )

        logger.info(
            "discord: collect_by_terms — channels=%d terms=%d tier=%s",
            len(effective_channel_ids),
            len(terms),
            tier.value,
        )
        logger.info(
            "discord: NOTE — Discord bots cannot use the search API. "
            "Terms are matched client-side after full channel retrieval."
        )

        if term_groups is not None:
            lower_groups: list[list[str]] = [
                [t.lower() for t in grp] for grp in term_groups if grp
            ]
        else:
            lower_groups = [[t.lower()] for t in terms]

        date_from_dt = parse_date_bound(date_from)
        date_to_dt = parse_date_bound(date_to)

        bot_token = await self._acquire_bot_token()
        all_records: list[dict[str, Any]] = []

        async with self._build_http_client(bot_token) as client:
            for channel_id in effective_channel_ids:
                if len(all_records) >= effective_max:
                    break

                channel_meta = await self._fetch_channel_metadata(client, channel_id)
                messages = await fetch_channel_messages(
                    client=client,
                    channel_id=channel_id,
                    arena_name=self.arena_name,
                    platform_name=self.platform_name,
                    date_from_dt=date_from_dt,
                    date_to_dt=date_to_dt,
                    max_count=effective_max - len(all_records),
                )

                for msg in messages:
                    content_lower = (msg.get("content") or "").lower()
                    matched = any(
                        all(term in content_lower for term in grp)
                        for grp in lower_groups
                    )
                    if not matched:
                        continue

                    record = self.normalize(enrich_message(msg, channel_id, channel_meta))
                    all_records.append(record)

                    if len(all_records) >= effective_max:
                        break

        logger.info(
            "discord: collect_by_terms complete — matched=%d across %d channel(s)",
            len(all_records),
            len(effective_channel_ids),
        )
        return all_records

    async def collect_by_actors(
        self,
        actor_ids: list[str],
        tier: Tier,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
        channel_ids: list[str] | None = None,
        extra_channel_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Collect Discord messages authored by specific users.

        Fetches all messages from the provided channels, then filters by
        ``author.id`` matching any of the provided Discord user snowflake IDs.

        Args:
            actor_ids: Discord user snowflake IDs (as strings) to match
                against ``message.author.id``.
            tier: Must be ``Tier.FREE``.
            date_from: Earliest publication date to include (inclusive).
            date_to: Latest publication date to include (inclusive).
            max_results: Upper bound on returned records.
            channel_ids: Channel snowflake IDs to search. Required — Discord
                bots cannot enumerate all messages by user globally.
            extra_channel_ids: Optional list of additional channel snowflake
                IDs supplied by the researcher via
                ``arenas_config["discord"]["custom_channel_ids"]`` (GR-04).
                These are merged with ``channel_ids`` before fetching.

        Returns:
            List of normalized content record dicts.

        Raises:
            ValueError: If *tier* is not ``Tier.FREE``.
            ArenaCollectionError: If no channel IDs are provided.
            ArenaRateLimitError: On HTTP 429 from the Discord API.
            NoCredentialAvailableError: If no bot token is available.
        """
        self._validate_tier(tier)
        effective_max = max_results if max_results is not None else DEFAULT_MAX_RESULTS

        # GR-04: merge researcher-supplied extra channel IDs.
        effective_channel_ids = _merge_channel_ids(channel_ids, extra_channel_ids)

        if not effective_channel_ids:
            raise ArenaCollectionError(
                "Discord collect_by_actors requires explicit channel_ids — the bot "
                "cannot enumerate all messages by user across all servers without a "
                "specific channel list. Pass channel_ids=[...] with the snowflake "
                "IDs of the channels to search.",
                arena=self.arena_name,
                platform=self.platform_name,
            )

        actor_id_set = {str(a) for a in actor_ids}

        logger.info(
            "discord: collect_by_actors — channels=%d actors=%d tier=%s",
            len(effective_channel_ids),
            len(actor_ids),
            tier.value,
        )

        date_from_dt = parse_date_bound(date_from)
        date_to_dt = parse_date_bound(date_to)

        bot_token = await self._acquire_bot_token()
        all_records: list[dict[str, Any]] = []

        async with self._build_http_client(bot_token) as client:
            for channel_id in effective_channel_ids:
                if len(all_records) >= effective_max:
                    break

                channel_meta = await self._fetch_channel_metadata(client, channel_id)
                messages = await fetch_channel_messages(
                    client=client,
                    channel_id=channel_id,
                    arena_name=self.arena_name,
                    platform_name=self.platform_name,
                    date_from_dt=date_from_dt,
                    date_to_dt=date_to_dt,
                    max_count=effective_max - len(all_records),
                )

                for msg in messages:
                    author_id = str(msg.get("author", {}).get("id", ""))
                    if author_id not in actor_id_set:
                        continue

                    record = self.normalize(enrich_message(msg, channel_id, channel_meta))
                    all_records.append(record)

                    if len(all_records) >= effective_max:
                        break

        logger.info(
            "discord: collect_by_actors complete — matched=%d across %d channel(s)",
            len(all_records),
            len(effective_channel_ids),
        )
        return all_records

    def get_tier_config(self, tier: Tier) -> TierConfig:
        """Return tier configuration for the Discord arena.

        Args:
            tier: Requested operational tier.

        Returns:
            :class:`~issue_observatory.config.tiers.TierConfig` for FREE tier.

        Raises:
            ValueError: If *tier* is not in ``supported_tiers``.
        """
        if tier not in DISCORD_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}' for discord. "
                f"Valid tiers: {list(DISCORD_TIERS.keys())}"
            )
        return DISCORD_TIERS[tier]

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw Discord message dict to the universal schema.

        The raw item must be pre-enriched with ``_channel_id`` and
        ``_channel_meta`` (via :func:`~._http.enrich_message`) before calling
        this method.

        Args:
            raw_item: Enriched Discord message dict containing the original API
                response fields plus ``_channel_id`` and ``_channel_meta``.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        msg = raw_item
        channel_id = msg.get("_channel_id", "")
        channel_meta = msg.get("_channel_meta", {})
        guild_id = channel_meta.get("guild_id", "")
        channel_name = channel_meta.get("name", "")
        guild_name = channel_meta.get("guild_name", "")

        message_id = str(msg.get("id", ""))
        author = msg.get("author") or {}
        author_id = str(author.get("id", ""))
        author_display = author.get("global_name") or author.get("username", "")

        text_content: str | None = msg.get("content") or None

        url = (
            f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
            if guild_id and channel_id and message_id
            else None
        )

        likes_count: int = sum(
            r.get("count", 0) for r in (msg.get("reactions") or [])
        )

        thread_info = msg.get("thread") or {}
        comments_count: int | None = thread_info.get("message_count")

        referenced_msg = msg.get("referenced_message")
        referenced_id: str | None = (
            str(referenced_msg.get("id")) if referenced_msg else None
        )

        raw_metadata: dict[str, Any] = {
            "guild_id": guild_id,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "guild_name": guild_name,
            "attachments": [
                a["url"] for a in (msg.get("attachments") or []) if a.get("url")
            ],
            "embeds": len(msg.get("embeds") or []),
            "mentions": [
                str(m["id"]) for m in (msg.get("mentions") or []) if m.get("id")
            ],
            "referenced_message_id": referenced_id,
            "reactions": msg.get("reactions") or [],
            "thread_id": thread_info.get("id"),
            "actual_poster_name": author_display,
            "actual_poster_id": author_id,
        }

        # Compose a source-level display name: "Server / #channel"
        composed_display = (
            f"{guild_name} / {channel_name}"
            if guild_name and channel_name
            else guild_name or channel_name or author_display
        )

        normalized_raw: dict[str, Any] = {
            "id": message_id,
            "platform_id": message_id,
            "content_type": "post",
            "text_content": text_content,
            "title": None,
            "url": url,
            "language": None,
            "published_at": msg.get("timestamp"),
            "author_platform_id": author_id,
            "author_display_name": composed_display,
            "views_count": None,
            "likes_count": likes_count if likes_count > 0 else None,
            "shares_count": None,
            "comments_count": comments_count,
            "raw_metadata": raw_metadata,
        }

        return self._normalizer.normalize(
            raw_item=normalized_raw,
            platform=self.platform_name,
            arena=self.arena_name,
            collection_tier="free",
            search_terms_matched=[],
        )

    async def health_check(self) -> dict[str, Any]:
        """Verify that the Discord API is reachable and the bot token is valid.

        Calls ``GET /gateway`` which returns the WebSocket URL. A 200 response
        confirms the API is up and the bot token authenticates correctly.

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
            bot_token = await self._acquire_bot_token()
        except NoCredentialAvailableError as exc:
            return {
                **base,
                "status": "down",
                "detail": f"No bot token available: {exc}",
            }

        url = f"{DISCORD_API_BASE}/gateway"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bot {bot_token}"},
                )
                response.raise_for_status()
                return {
                    **base,
                    "status": "ok",
                    "gateway_url": response.json().get("url"),
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

    async def _acquire_bot_token(self) -> str:
        """Retrieve the Discord bot token from the credential pool.

        Returns:
            Bot token string.

        Raises:
            NoCredentialAvailableError: If the credential pool is absent or
                has no active ``discord`` credential.
        """
        if self.credential_pool is None:
            raise NoCredentialAvailableError(platform="discord", tier="free")

        credential = await self.credential_pool.acquire(
            platform="discord", tier="free"
        )
        if credential is None:
            raise NoCredentialAvailableError(platform="discord", tier="free")

        token = credential.get("bot_token")
        if not token:
            raise NoCredentialAvailableError(platform="discord", tier="free")

        return str(token)

    def _build_http_client(self, bot_token: str) -> httpx.AsyncClient:
        """Build an :class:`httpx.AsyncClient` with Discord bot authentication.

        Args:
            bot_token: Discord bot token used in the ``Authorization`` header.

        Returns:
            Configured :class:`httpx.AsyncClient` context manager.
        """
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]
        return httpx.AsyncClient(
            base_url=DISCORD_API_BASE,
            headers={
                "Authorization": f"Bot {bot_token}",
                "User-Agent": "IssueObservatory/1.0 (discord-collector; research bot)",
            },
            timeout=30.0,
        )

    async def _fetch_channel_metadata(
        self,
        client: httpx.AsyncClient,
        channel_id: str,
    ) -> dict[str, Any]:
        """Fetch metadata for a single channel (non-fatal on failure).

        Used to enrich messages with ``channel_name`` and ``guild_id``.

        Args:
            client: Authenticated HTTP client.
            channel_id: Discord channel snowflake ID.

        Returns:
            Channel metadata dict from the API, or empty dict on error.
        """
        try:
            return await make_request(  # type: ignore[return-value]
                client,
                f"/channels/{channel_id}",
                arena_name=self.arena_name,
                platform_name=self.platform_name,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "discord: could not fetch metadata for channel %s: %s",
                channel_id,
                exc,
            )
            return {}


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _merge_channel_ids(
    channel_ids: list[str] | None,
    extra_channel_ids: list[str] | None,
) -> list[str]:
    """Merge explicit and researcher-supplied Discord channel snowflake IDs.

    Deduplicates by string value while preserving insertion order (explicit
    ``channel_ids`` first, then ``extra_channel_ids``).

    Args:
        channel_ids: Channel IDs explicitly provided to the collector method.
        extra_channel_ids: Optional additional IDs from
            ``arenas_config["discord"]["custom_channel_ids"]`` (GR-04).

    Returns:
        Deduplicated list of channel ID strings.
    """
    seen: set[str] = set()
    result: list[str] = []
    for cid in (channel_ids or []) + (extra_channel_ids or []):
        s = str(cid).strip()
        if s and s not in seen:
            seen.add(s)
            result.append(s)
    return result
