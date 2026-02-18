"""Telegram arena collector implementation.

Collects messages from public Telegram channels via the Telethon MTProto client
library (free, credential-required).

Two collection modes are supported:

- :meth:`TelegramCollector.collect_by_terms` — searches a configured list of
  Danish channels for each term using ``client.get_messages(channel, search=term)``.
  Paginates via ``offset_id`` until ``date_from`` is exceeded or ``max_results``
  is reached.

- :meth:`TelegramCollector.collect_by_actors` — fetches recent messages from
  each specified channel using ``client.get_messages(channel, limit=100)`` with
  date-based pagination.  ``actor_ids`` are public Telegram channel usernames
  (e.g. ``"dr_nyheder"``) or numeric channel IDs (e.g. ``"-1001234567890"``).

**Session management**: Credentials are acquired from :class:`CredentialPool`
(``platform="telegram"``, ``tier="free"``).  Each credential payload must
contain ``api_id``, ``api_hash``, and ``session_string`` (Telethon StringSession).
The Telethon client is created as an async context manager and torn down
after each collection call.  The credential is always released in a ``finally``
block.

**FloodWaitError handling**: When Telethon raises a ``FloodWaitError``, the
exact ``error.seconds`` wait is stored as a Redis cooldown on the credential
(key ``credential:cooldown:{id}``, TTL = ``error.seconds``), the credential is
released, and ``ArenaRateLimitError`` is raised to trigger Celery retry.

**Danish defaults**: No built-in language filter exists in Telegram.  All
messages from the configured Danish channel list are collected regardless of
language.  Language detection must be applied by a downstream analysis layer.
The channel list (:data:`~config.DANISH_TELEGRAM_CHANNELS`) is a curated
starter set of known Danish-language public channels.

**Media**: Photo, document, and video media attached to messages cannot be
resolved to public HTTP URLs without downloading via Telethon.  The collector
records the presence and type of attached media in ``raw_metadata.media_type``
and leaves ``media_urls`` as an empty list.  Full media download is out of scope
for Phase 1 collection.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from issue_observatory.arenas.base import ArenaCollector, Tier
from issue_observatory.arenas.query_builder import format_boolean_query_for_platform
from issue_observatory.arenas.registry import register
from issue_observatory.arenas.telegram.config import (
    DANISH_TELEGRAM_CHANNELS,
    MAX_MESSAGES_PER_REQUEST,
    TELEGRAM_TIERS,
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
# Rate-limit key constants
# ---------------------------------------------------------------------------

_RATE_LIMIT_ARENA: str = "telegram"
_RATE_LIMIT_PROVIDER: str = "free"
_RATE_LIMIT_MAX_CALLS: int = 20
_RATE_LIMIT_WINDOW_SECONDS: int = 60


@register
class TelegramCollector(ArenaCollector):
    """Collects Telegram channel messages via the Telethon MTProto client.

    Only ``Tier.FREE`` is supported.  Credentials (``api_id``, ``api_hash``,
    ``session_string``) are required and must be pre-provisioned in the
    :class:`CredentialPool`.  Interactive phone verification cannot be performed
    by this collector — session strings must be generated once manually and then
    stored in the pool.

    Class Attributes:
        arena_name: ``"social_media"``
        platform_name: ``"telegram"``
        supported_tiers: ``[Tier.FREE]``

    Args:
        credential_pool: Required credential pool for Telegram account rotation.
            If ``None``, all collection calls raise ``NoCredentialAvailableError``.
        rate_limiter: Optional Redis-backed rate limiter.  Used as a baseline
            before Telegram's own FloodWaitError signal.
        default_channels: Optional list of channel usernames to search when
            no actor_ids are provided.  Defaults to
            :data:`~config.DANISH_TELEGRAM_CHANNELS`.
    """

    arena_name: str = "social_media"
    platform_name: str = "telegram"
    supported_tiers: list[Tier] = [Tier.FREE]

    def __init__(
        self,
        credential_pool: Any = None,
        rate_limiter: Any = None,
        default_channels: list[str] | None = None,
    ) -> None:
        super().__init__(credential_pool=credential_pool, rate_limiter=rate_limiter)
        self._normalizer = Normalizer()
        self._default_channels: list[str] = (
            default_channels if default_channels is not None else list(DANISH_TELEGRAM_CHANNELS)
        )

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
        actor_ids: list[str] | None = None,
        term_groups: list[list[str]] | None = None,
        language_filter: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Collect Telegram messages matching one or more search terms.

        Iterates over the configured Danish channel list (plus any channels
        in ``actor_ids``) and searches each for the supplied terms using
        the ``search`` parameter of ``client.get_messages()``.  Results are
        deduplicated by ``{channel_id}_{message_id}``.

        Telegram does not support boolean query syntax.  When ``term_groups``
        is provided, each AND-group is searched as a space-joined phrase (one
        request per group).  Results from all groups are merged.

        Args:
            terms: Search terms (used when ``term_groups`` is ``None``).
            tier: Operational tier — only ``Tier.FREE`` is accepted.
            date_from: Earliest message date (inclusive).
            date_to: Latest message date (inclusive).
            max_results: Upper bound on total records.
            actor_ids: Additional channel usernames or numeric IDs to search.
            term_groups: Optional boolean AND/OR groups.  Each group issues
                a separate search with terms space-joined as a phrase.
            language_filter: Not used — Telegram channels are pre-selected
                for Danish content.

        Returns:
            List of normalized content record dicts.

        Raises:
            NoCredentialAvailableError: When no Telegram credential is available.
            ArenaRateLimitError: When a FloodWaitError is raised by Telegram.
            ArenaCollectionError: On unrecoverable MTProto errors.
        """
        if tier != Tier.FREE:
            logger.warning(
                "telegram: tier=%s requested but only FREE is available. "
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

        channels = _build_channel_list(self._default_channels, actor_ids)

        # Telegram has no boolean support; for groups, search each group as a
        # space-joined phrase (one query per group).
        if term_groups is not None:
            effective_terms: list[str] = [
                format_boolean_query_for_platform(groups=[grp], platform="bluesky")
                for grp in term_groups
                if grp
            ]
        else:
            effective_terms = list(terms)

        cred = await self._acquire_credential()
        try:
            records = await self._collect_terms_with_credential(
                cred=cred,
                terms=effective_terms,
                channels=channels,
                date_from=date_from_dt,
                date_to=date_to_dt,
                max_results=effective_max,
            )
        finally:
            if self.credential_pool is not None:
                await self.credential_pool.release(credential_id=cred["id"])

        logger.info(
            "telegram: collect_by_terms collected %d records for %d queries across %d channels",
            len(records),
            len(effective_terms),
            len(channels),
        )
        return records

    async def collect_by_actors(
        self,
        actor_ids: list[str],
        tier: Tier,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect recent messages from specific Telegram channels.

        Each ``actor_id`` is a public Telegram channel username (e.g.
        ``"dr_nyheder"``) or a numeric channel ID (e.g. ``"-1001234567890"``).
        Messages are fetched in reverse-chronological order; pagination stops
        when ``message.date`` falls before ``date_from`` or ``max_results``
        is reached.

        Args:
            actor_ids: Channel usernames or numeric IDs to collect from.
            tier: Operational tier — only ``Tier.FREE`` is accepted.
            date_from: Earliest message date (inclusive).
            date_to: Latest message date (inclusive).
            max_results: Upper bound on total records.

        Returns:
            List of normalized content record dicts.

        Raises:
            NoCredentialAvailableError: When no Telegram credential is available.
            ArenaRateLimitError: When a FloodWaitError is raised by Telegram.
            ArenaCollectionError: On unrecoverable MTProto errors.
        """
        if tier != Tier.FREE:
            logger.warning(
                "telegram: tier=%s requested but only FREE is available. "
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

        cred = await self._acquire_credential()
        try:
            records = await self._collect_actors_with_credential(
                cred=cred,
                actor_ids=actor_ids,
                date_from=date_from_dt,
                date_to=date_to_dt,
                max_results=effective_max,
            )
        finally:
            if self.credential_pool is not None:
                await self.credential_pool.release(credential_id=cred["id"])

        logger.info(
            "telegram: collect_by_actors collected %d records for %d channels",
            len(records),
            len(actor_ids),
        )
        return records

    def get_tier_config(self, tier: Tier) -> TierConfig | None:
        """Return the tier configuration for this arena.

        Args:
            tier: The requested operational tier.

        Returns:
            :class:`TierConfig` for FREE.  ``None`` for MEDIUM and PREMIUM.
        """
        return TELEGRAM_TIERS.get(tier)

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single Telegram message to the universal content record schema.

        Expects a dict built by :meth:`_message_to_dict` containing message
        and channel attributes.  Produces a record matching ``content_records``.

        Args:
            raw_item: Dict with pre-extracted message and channel fields.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        channel_id = raw_item.get("channel_id", "")
        message_id = raw_item.get("message_id", "")
        channel_username = raw_item.get("channel_username") or ""
        channel_title = raw_item.get("channel_title") or channel_username

        # Global-unique platform_id: {channel_id}_{message_id}
        platform_id = f"{channel_id}_{message_id}" if channel_id and message_id else str(message_id)

        # Construct public URL if the channel has a username
        url: str | None = None
        if channel_username and message_id:
            url = f"https://t.me/{channel_username}/{message_id}"

        # Extract reaction sum (likes_count)
        reactions_list: list[dict[str, Any]] = raw_item.get("reactions", []) or []
        likes_count: int | None = None
        if reactions_list:
            likes_count = sum(r.get("count", 0) for r in reactions_list)

        # Build the flat dict for Normalizer
        flat: dict[str, Any] = {
            "platform_id": platform_id,
            "content_type": "post",
            "text_content": raw_item.get("text_content"),
            "title": None,
            "url": url,
            "language": None,  # No native language field; detect downstream
            "published_at": raw_item.get("published_at"),
            "author_platform_id": str(channel_id) if channel_id else None,
            "author_display_name": channel_title,
            "views_count": raw_item.get("views_count"),
            "likes_count": likes_count,
            "shares_count": raw_item.get("forwards_count"),
            "comments_count": raw_item.get("replies_count"),
            "media_urls": [],  # Media download is out of scope for Phase 1
            # Raw metadata fields
            "channel_id": str(channel_id) if channel_id else None,
            "channel_username": channel_username or None,
            "channel_title": channel_title or None,
            "is_forwarded": raw_item.get("is_forwarded", False),
            "fwd_from_channel_id": raw_item.get("fwd_from_channel_id"),
            "reply_to_msg_id": raw_item.get("reply_to_msg_id"),
            "has_media": raw_item.get("has_media", False),
            "media_type": raw_item.get("media_type"),
            "reactions": reactions_list,
            "edit_date": raw_item.get("edit_date"),
            "grouped_id": raw_item.get("grouped_id"),
            "via_bot_id": raw_item.get("via_bot_id"),
        }

        normalized = self._normalizer.normalize(
            raw_item=flat,
            platform=self.platform_name,
            arena=self.arena_name,
            collection_tier="free",
        )
        # Force platform_id to the combined value (Normalizer may pick up url)
        normalized["platform_id"] = platform_id
        return normalized

    async def health_check(self) -> dict[str, Any]:
        """Verify that the Telegram API is reachable using the first available credential.

        Connects to Telegram via the Telethon client and calls ``client.get_me()``
        to verify the session is valid.  If no credential is available the status
        is ``"degraded"`` rather than ``"down"`` because the API itself may be fine.

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

        cred = None
        if self.credential_pool is not None:
            cred = await self.credential_pool.acquire(platform="telegram", tier="free")

        if cred is None:
            return {
                **base,
                "status": "degraded",
                "detail": "No Telegram credential available for health check.",
            }

        try:
            from telethon import TelegramClient  # noqa: PLC0415
            from telethon.sessions import StringSession  # noqa: PLC0415

            api_id = int(cred["api_id"])
            api_hash = str(cred["api_hash"])
            session_string = str(cred["session_string"])

            client = TelegramClient(
                StringSession(session_string), api_id, api_hash
            )
            async with client:
                me = await client.get_me()
                if me is None:
                    return {
                        **base,
                        "status": "degraded",
                        "detail": "get_me() returned None — session may be invalid.",
                    }
                return {
                    **base,
                    "status": "ok",
                    "detail": f"Authenticated as user_id={me.id}",
                }
        except Exception as exc:
            return {**base, "status": "down", "detail": f"Connection error: {exc}"}
        finally:
            if self.credential_pool is not None and cred is not None:
                await self.credential_pool.release(credential_id=cred["id"])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _acquire_credential(self) -> dict[str, Any]:
        """Acquire a Telegram credential from the pool.

        Returns:
            Credential dict with ``id``, ``api_id``, ``api_hash``,
            and ``session_string`` keys.

        Raises:
            NoCredentialAvailableError: When no credential is available.
        """
        if self.credential_pool is None:
            raise NoCredentialAvailableError(platform="telegram", tier="free")

        cred = await self.credential_pool.acquire(platform="telegram", tier="free")
        if cred is None:
            raise NoCredentialAvailableError(platform="telegram", tier="free")
        return cred

    async def _wait_for_rate_limit(self, credential_id: str) -> None:
        """Wait for a baseline rate-limit slot before making a Telegram request.

        Args:
            credential_id: Credential ID suffix for the Redis rate-limit key.
        """
        if self.rate_limiter is None:
            return
        key = f"ratelimit:{_RATE_LIMIT_ARENA}:{_RATE_LIMIT_PROVIDER}:{credential_id}"
        await self.rate_limiter.wait_for_slot(
            key=key,
            max_calls=_RATE_LIMIT_MAX_CALLS,
            window_seconds=_RATE_LIMIT_WINDOW_SECONDS,
        )

    async def _set_flood_wait_cooldown(
        self, credential_id: str, seconds: int
    ) -> None:
        """Set a Redis cooldown key for a credential after a FloodWaitError.

        The key ``credential:cooldown:{credential_id}`` is set with TTL equal
        to ``seconds`` exactly, as mandated by the Telegram API contract.

        Args:
            credential_id: Credential ID to cool down.
            seconds: Exact wait time from ``FloodWaitError.seconds``.
        """
        if self.credential_pool is None:
            return
        try:
            redis = await self.credential_pool._get_redis()
            await redis.setex(f"credential:cooldown:{credential_id}", seconds, "flood_wait")
            logger.warning(
                "telegram: FloodWaitError — credential %s on cooldown for %ds.",
                credential_id,
                seconds,
            )
        except Exception as exc:
            logger.warning("telegram: failed to set flood-wait cooldown: %s", exc)

    async def _collect_terms_with_credential(
        self,
        cred: dict[str, Any],
        terms: list[str],
        channels: list[str],
        date_from: datetime | None,
        date_to: datetime | None,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """Collect term-matched messages using the given credential.

        Args:
            cred: Decrypted credential dict.
            terms: Search terms.
            channels: Channel usernames/IDs to search.
            date_from: Earliest date filter.
            date_to: Latest date filter.
            max_results: Maximum records to collect.

        Returns:
            Deduplicated list of normalized records.

        Raises:
            ArenaRateLimitError: On FloodWaitError.
            ArenaCollectionError: On unrecoverable errors.
        """
        from telethon import TelegramClient  # noqa: PLC0415
        from telethon.errors import FloodWaitError, UserDeactivatedBanError  # noqa: PLC0415
        from telethon.sessions import StringSession  # noqa: PLC0415

        api_id = int(cred["api_id"])
        api_hash = str(cred["api_hash"])
        session_string = str(cred["session_string"])
        cred_id = cred["id"]

        records: list[dict[str, Any]] = []
        seen: set[str] = set()

        client = TelegramClient(StringSession(session_string), api_id, api_hash)
        try:
            async with client:
                for term in terms:
                    if len(records) >= max_results:
                        break
                    for channel_id in channels:
                        if len(records) >= max_results:
                            break
                        remaining = max_results - len(records)
                        channel_records = await self._search_channel_for_term(
                            client=client,
                            cred_id=cred_id,
                            channel=channel_id,
                            term=term,
                            date_from=date_from,
                            date_to=date_to,
                            max_results=remaining,
                            seen=seen,
                        )
                        records.extend(channel_records)
        except FloodWaitError as exc:
            await self._set_flood_wait_cooldown(cred_id, exc.seconds)
            raise ArenaRateLimitError(
                f"telegram: FloodWaitError — must wait {exc.seconds}s",
                retry_after=float(exc.seconds),
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc
        except UserDeactivatedBanError as exc:
            if self.credential_pool is not None:
                await self.credential_pool.report_error(credential_id=cred_id, error=exc)
            raise NoCredentialAvailableError(platform="telegram", tier="free") from exc
        except Exception as exc:
            raise ArenaCollectionError(
                f"telegram: unexpected error during term collection: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

        return records

    async def _collect_actors_with_credential(
        self,
        cred: dict[str, Any],
        actor_ids: list[str],
        date_from: datetime | None,
        date_to: datetime | None,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """Collect messages from specific channels using the given credential.

        Args:
            cred: Decrypted credential dict.
            actor_ids: Channel usernames or numeric IDs.
            date_from: Earliest date filter.
            date_to: Latest date filter.
            max_results: Maximum records to collect.

        Returns:
            List of normalized records.

        Raises:
            ArenaRateLimitError: On FloodWaitError.
            ArenaCollectionError: On unrecoverable errors.
        """
        from telethon import TelegramClient  # noqa: PLC0415
        from telethon.errors import FloodWaitError, UserDeactivatedBanError  # noqa: PLC0415
        from telethon.sessions import StringSession  # noqa: PLC0415

        api_id = int(cred["api_id"])
        api_hash = str(cred["api_hash"])
        session_string = str(cred["session_string"])
        cred_id = cred["id"]

        records: list[dict[str, Any]] = []
        seen: set[str] = set()

        client = TelegramClient(StringSession(session_string), api_id, api_hash)
        try:
            async with client:
                for channel_id in actor_ids:
                    if len(records) >= max_results:
                        break
                    remaining = max_results - len(records)
                    channel_records = await self._fetch_channel_messages(
                        client=client,
                        cred_id=cred_id,
                        channel=channel_id,
                        date_from=date_from,
                        date_to=date_to,
                        max_results=remaining,
                        seen=seen,
                    )
                    records.extend(channel_records)
        except FloodWaitError as exc:
            await self._set_flood_wait_cooldown(cred_id, exc.seconds)
            raise ArenaRateLimitError(
                f"telegram: FloodWaitError — must wait {exc.seconds}s",
                retry_after=float(exc.seconds),
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc
        except UserDeactivatedBanError as exc:
            if self.credential_pool is not None:
                await self.credential_pool.report_error(credential_id=cred_id, error=exc)
            raise NoCredentialAvailableError(platform="telegram", tier="free") from exc
        except Exception as exc:
            raise ArenaCollectionError(
                f"telegram: unexpected error during actor collection: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

        return records

    async def _search_channel_for_term(
        self,
        client: Any,
        cred_id: str,
        channel: str,
        term: str,
        date_from: datetime | None,
        date_to: datetime | None,
        max_results: int,
        seen: set[str],
    ) -> list[dict[str, Any]]:
        """Search a single channel for messages matching a term.

        Paginates via ``offset_id`` until ``date_from`` is exceeded or
        ``max_results`` is reached.

        Args:
            client: Active Telethon client.
            cred_id: Credential ID for rate-limit keying.
            channel: Channel username or numeric ID.
            term: Search term.
            date_from: Earliest date boundary.
            date_to: Latest date boundary.
            max_results: Maximum records to collect from this channel.
            seen: Mutable set of already-seen platform_ids (deduplification).

        Returns:
            List of normalized records from this channel for the term.
        """
        from telethon.errors import ChannelPrivateError, PeerIdInvalidError  # noqa: PLC0415

        records: list[dict[str, Any]] = []
        offset_id = 0

        try:
            entity = await client.get_entity(channel)
        except ChannelPrivateError:
            logger.warning("telegram: channel %r is private — skipping.", channel)
            return records
        except PeerIdInvalidError:
            logger.warning("telegram: invalid peer ID %r — skipping.", channel)
            return records
        except Exception as exc:
            logger.warning("telegram: could not resolve channel %r: %s — skipping.", channel, exc)
            return records

        while len(records) < max_results:
            await self._wait_for_rate_limit(cred_id)
            batch_limit = min(MAX_MESSAGES_PER_REQUEST, max_results - len(records))

            messages = await client.get_messages(
                entity,
                search=term,
                limit=batch_limit,
                offset_date=date_to,
                add_offset=0,
                offset_id=offset_id,
            )

            if not messages:
                break

            stop_early = False
            for msg in messages:
                if not msg.message:
                    # Skip service messages with no text
                    continue
                if date_from and msg.date and msg.date.replace(tzinfo=timezone.utc) < date_from:
                    stop_early = True
                    break
                if date_to and msg.date and msg.date.replace(tzinfo=timezone.utc) > date_to:
                    continue

                raw_dict = _message_to_dict(msg, entity)
                pid = raw_dict.get("platform_id_raw", "")
                if pid in seen:
                    continue
                seen.add(pid)
                records.append(self.normalize(raw_dict))

                if len(records) >= max_results:
                    break

            if stop_early or len(messages) < batch_limit:
                break

            # Advance offset_id to the ID of the last message in this batch
            offset_id = messages[-1].id

        return records

    async def _fetch_channel_messages(
        self,
        client: Any,
        cred_id: str,
        channel: str,
        date_from: datetime | None,
        date_to: datetime | None,
        max_results: int,
        seen: set[str],
    ) -> list[dict[str, Any]]:
        """Fetch messages from a channel with date filtering.

        Paginates via ``offset_id`` until ``date_from`` is exceeded or
        ``max_results`` is reached.

        Args:
            client: Active Telethon client.
            cred_id: Credential ID for rate-limit keying.
            channel: Channel username or numeric ID.
            date_from: Earliest date boundary.
            date_to: Latest date boundary.
            max_results: Maximum records to collect from this channel.
            seen: Mutable set of already-seen platform_ids (deduplication).

        Returns:
            List of normalized records.
        """
        from telethon.errors import ChannelPrivateError, PeerIdInvalidError  # noqa: PLC0415

        records: list[dict[str, Any]] = []
        offset_id = 0

        try:
            entity = await client.get_entity(channel)
        except ChannelPrivateError:
            logger.warning("telegram: channel %r is private — skipping.", channel)
            return records
        except PeerIdInvalidError:
            logger.warning("telegram: invalid peer ID %r — skipping.", channel)
            return records
        except Exception as exc:
            logger.warning("telegram: could not resolve channel %r: %s — skipping.", channel, exc)
            return records

        while len(records) < max_results:
            await self._wait_for_rate_limit(cred_id)
            batch_limit = min(MAX_MESSAGES_PER_REQUEST, max_results - len(records))

            messages = await client.get_messages(
                entity,
                limit=batch_limit,
                offset_id=offset_id,
            )

            if not messages:
                break

            stop_early = False
            for msg in messages:
                if not msg.message:
                    continue
                msg_date = msg.date
                if msg_date and msg_date.tzinfo is None:
                    msg_date = msg_date.replace(tzinfo=timezone.utc)

                if date_from and msg_date and msg_date < date_from:
                    stop_early = True
                    break
                if date_to and msg_date and msg_date > date_to:
                    continue

                raw_dict = _message_to_dict(msg, entity)
                pid = raw_dict.get("platform_id_raw", "")
                if pid in seen:
                    continue
                seen.add(pid)
                records.append(self.normalize(raw_dict))

                if len(records) >= max_results:
                    break

            if stop_early or len(messages) < batch_limit:
                break

            offset_id = messages[-1].id

        return records


# ---------------------------------------------------------------------------
# Module-level utility functions
# ---------------------------------------------------------------------------


def _message_to_dict(message: Any, channel_entity: Any) -> dict[str, Any]:
    """Convert a Telethon Message object to a flat dict for normalization.

    Extracts all fields needed for the universal content record schema and for
    ``raw_metadata``.

    Args:
        message: Telethon ``Message`` object.
        channel_entity: Telethon entity object for the source channel.

    Returns:
        Flat dict with all extracted fields.
    """
    channel_id = getattr(channel_entity, "id", None)
    channel_username = getattr(channel_entity, "username", None) or ""
    channel_title = getattr(channel_entity, "title", None) or channel_username

    message_id = message.id
    platform_id_raw = f"{channel_id}_{message_id}"

    # Published timestamp — ensure timezone-aware
    published_at: str | None = None
    if message.date:
        dt = message.date
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        published_at = dt.isoformat()

    # Edit date
    edit_date: str | None = None
    if getattr(message, "edit_date", None):
        ed = message.edit_date
        if ed.tzinfo is None:
            ed = ed.replace(tzinfo=timezone.utc)
        edit_date = ed.isoformat()

    # Forwarded message metadata
    is_forwarded = message.fwd_from is not None
    fwd_from_channel_id: str | None = None
    if is_forwarded and message.fwd_from:
        fwd_channel = getattr(message.fwd_from, "channel_id", None)
        fwd_from_channel_id = str(fwd_channel) if fwd_channel else None

    # Reply-to message ID
    reply_to_msg_id: int | None = None
    if getattr(message, "reply_to", None):
        reply_to_msg_id = getattr(message.reply_to, "reply_to_msg_id", None)

    # Media type detection (no download)
    has_media = message.media is not None
    media_type: str | None = None
    if has_media and message.media:
        media_type = type(message.media).__name__

    # Reactions: list of {emoji, count}
    reactions: list[dict[str, Any]] = []
    msg_reactions = getattr(message, "reactions", None)
    if msg_reactions:
        results = getattr(msg_reactions, "results", []) or []
        for r in results:
            reaction_obj = getattr(r, "reaction", None)
            if reaction_obj:
                emoji = getattr(reaction_obj, "emoticon", None) or str(reaction_obj)
                reactions.append({"emoji": emoji, "count": getattr(r, "count", 0)})

    # Comments count
    replies_count: int | None = None
    msg_replies = getattr(message, "replies", None)
    if msg_replies:
        replies_count = getattr(msg_replies, "replies", None)

    return {
        "platform_id_raw": platform_id_raw,
        "message_id": message_id,
        "channel_id": channel_id,
        "channel_username": channel_username,
        "channel_title": channel_title,
        "text_content": message.message or "",
        "published_at": published_at,
        "views_count": getattr(message, "views", None),
        "forwards_count": getattr(message, "forwards", None),
        "replies_count": replies_count,
        "reactions": reactions,
        "is_forwarded": is_forwarded,
        "fwd_from_channel_id": fwd_from_channel_id,
        "reply_to_msg_id": reply_to_msg_id,
        "has_media": has_media,
        "media_type": media_type,
        "edit_date": edit_date,
        "grouped_id": getattr(message, "grouped_id", None),
        "via_bot_id": getattr(message, "via_bot_id", None),
    }


def _build_channel_list(
    default_channels: list[str],
    actor_ids: list[str] | None,
) -> list[str]:
    """Merge default channels and actor_ids into a deduplicated list.

    Args:
        default_channels: Configured default Danish channels.
        actor_ids: Optional additional channel identifiers.

    Returns:
        Deduplicated list of channel identifiers preserving insertion order.
    """
    seen: set[str] = set()
    result: list[str] = []
    for ch in (default_channels or []) + (actor_ids or []):
        if ch not in seen:
            seen.add(ch)
            result.append(ch)
    return result


def _parse_datetime(value: datetime | str | None) -> datetime | None:
    """Parse a datetime value to a timezone-aware datetime object.

    Args:
        value: Datetime object, ISO 8601 string, or ``None``.

    Returns:
        Timezone-aware datetime or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
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
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None
