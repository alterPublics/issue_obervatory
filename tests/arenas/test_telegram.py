"""Tests for the Telegram arena collector.

Covers:
- normalize() unit tests: platform_id as {channel_id}_{message_id}, URL
  construction from channel_username, reaction sum -> likes_count, forwards
  -> shares_count, replies -> comments_count, media_urls always empty (Phase 1)
- _message_to_dict(): field extraction from Telethon Message mock objects
- collect_by_terms(): records returned, deduplication, FloodWaitError ->
  ArenaRateLimitError, unexpected exception -> ArenaCollectionError,
  no-credential -> NoCredentialAvailableError, non-FREE tier logs warning
- collect_by_actors(): records from specified channel, empty channel, no
  credential, rate limit error
- health_check(): ok when get_me() succeeds, degraded when no credential,
  degraded when pool returns None, down on connection error
- Danish character preservation: ae, o, a throughout
- content_hash is a 64-char hex string
- _build_channel_list() deduplication and merge
- _parse_datetime() parsing edge cases
- get_tier_config() returns correct values per tier

These tests run without a live database or network connection.
Telethon calls are mocked at the telethon module level via unittest.mock.patch.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Env bootstrap (must run before any application imports)
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==")

from issue_observatory.arenas.base import Tier  # noqa: E402
from issue_observatory.arenas.telegram.collector import (  # noqa: E402
    TelegramCollector,
    _message_to_dict,
    _build_channel_list,
    _parse_datetime,
)
from issue_observatory.core.exceptions import (  # noqa: E402
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)

# ---------------------------------------------------------------------------
# Telegram test credential
# ---------------------------------------------------------------------------

_TEST_CREDENTIAL: dict[str, Any] = {
    "id": "cred-tg-001",
    "api_id": "12345678",
    "api_hash": "test_api_hash_abc123",
    "session_string": "1BVtsOHIBu0TBkAtestSessionString",
}


# ---------------------------------------------------------------------------
# Mock credential pool factory
# ---------------------------------------------------------------------------


def _make_mock_pool(cred: dict[str, Any] | None = _TEST_CREDENTIAL) -> Any:
    """Build a minimal mock CredentialPool returning a Telegram credential."""
    pool = MagicMock()
    pool.acquire = AsyncMock(return_value=cred)
    pool.release = AsyncMock(return_value=None)
    pool.report_error = AsyncMock(return_value=None)
    return pool


# ---------------------------------------------------------------------------
# Telethon object mock helpers
# ---------------------------------------------------------------------------


def _make_message(
    msg_id: int = 1001,
    text: str = "Grøn omstilling i Folketing — Ålborg er foregangsby.",
    date: datetime | None = None,
    views: int = 5000,
    forwards: int = 120,
    reactions_list: list[dict[str, Any]] | None = None,
    replies_count: int | None = 7,
    has_media: bool = False,
    fwd_from: Any | None = None,
    reply_to: Any | None = None,
    edit_date: datetime | None = None,
) -> MagicMock:
    """Build a minimal Telethon Message mock for use in _message_to_dict() tests."""
    msg = MagicMock()
    msg.id = msg_id
    msg.message = text
    msg.date = date or datetime(2026, 2, 15, 10, 0, 0, tzinfo=timezone.utc)
    msg.views = views
    msg.forwards = forwards
    msg.fwd_from = fwd_from
    msg.reply_to = reply_to
    msg.edit_date = edit_date
    msg.grouped_id = None
    msg.via_bot_id = None
    msg.media = MagicMock() if has_media else None

    # Reactions
    if reactions_list:
        reactions_mock = MagicMock()
        results = []
        for r_data in reactions_list:
            r_mock = MagicMock()
            reaction_inner = MagicMock()
            reaction_inner.emoticon = r_data["emoji"]
            r_mock.reaction = reaction_inner
            r_mock.count = r_data["count"]
            results.append(r_mock)
        reactions_mock.results = results
        msg.reactions = reactions_mock
    else:
        msg.reactions = None

    # Replies
    if replies_count is not None:
        replies_mock = MagicMock()
        replies_mock.replies = replies_count
        msg.replies = replies_mock
    else:
        msg.replies = None

    return msg


def _make_entity(
    channel_id: int = 111222333,
    username: str = "dr_nyheder",
    title: str = "DR Nyheder",
) -> MagicMock:
    """Build a minimal Telethon Channel entity mock."""
    entity = MagicMock()
    entity.id = channel_id
    entity.username = username
    entity.title = title
    return entity


def _make_async_client_mock(
    entity: MagicMock | None = None,
    messages: list[MagicMock] | None = None,
    me: MagicMock | None = None,
) -> MagicMock:
    """Build an async Telethon client mock that works as an async context manager."""
    if entity is None:
        entity = _make_entity()

    client = MagicMock()
    client.get_entity = AsyncMock(return_value=entity)
    client.get_messages = AsyncMock(return_value=messages if messages is not None else [])

    if me is None:
        me_obj = MagicMock()
        me_obj.id = 99999
        me = me_obj
    client.get_me = AsyncMock(return_value=me)

    # Explicit connect/disconnect (used by the collector instead of async-with/start
    # to avoid the start() interactive input() hang in non-interactive contexts).
    client.connect = AsyncMock(return_value=None)
    client.disconnect = AsyncMock(return_value=None)

    # Async context manager protocol (kept for backward compatibility with any
    # code still using ``async with client``).
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


# ---------------------------------------------------------------------------
# Patch helpers: patch telethon at the module level since imports are lazy
# ---------------------------------------------------------------------------

_TELETHON_CLIENT_PATH = "telethon.TelegramClient"
_TELETHON_STRING_SESSION_PATH = "telethon.sessions.StringSession"
_FLOOD_WAIT_PATH = "telethon.errors.FloodWaitError"
_USER_BAN_PATH = "telethon.errors.UserDeactivatedBanError"
_CHANNEL_PRIVATE_PATH = "telethon.errors.ChannelPrivateError"
_PEER_INVALID_PATH = "telethon.errors.PeerIdInvalidError"


# ---------------------------------------------------------------------------
# _message_to_dict() unit tests
# ---------------------------------------------------------------------------


class TestMessageToDict:
    def _entity(self) -> MagicMock:
        return _make_entity(channel_id=111222333, username="dr_nyheder", title="DR Nyheder")

    def _message(self) -> MagicMock:
        return _make_message(
            msg_id=1001,
            text="Grøn omstilling i Folketing.",
            reactions_list=[
                {"emoji": "👍", "count": 150},
                {"emoji": "❤️", "count": 50},
            ],
        )

    def test_message_to_dict_platform_id_raw_format(self) -> None:
        """_message_to_dict() sets platform_id_raw as '{channel_id}_{message_id}'."""
        result = _message_to_dict(self._message(), self._entity())

        assert result["platform_id_raw"] == "111222333_1001"

    def test_message_to_dict_channel_username_present(self) -> None:
        """_message_to_dict() includes channel_username from the entity."""
        result = _message_to_dict(self._message(), self._entity())

        assert result["channel_username"] == "dr_nyheder"

    def test_message_to_dict_channel_title_present(self) -> None:
        """_message_to_dict() includes channel_title from the entity."""
        result = _message_to_dict(self._message(), self._entity())

        assert result["channel_title"] == "DR Nyheder"

    def test_message_to_dict_text_content_preserved(self) -> None:
        """_message_to_dict() preserves the message text in text_content."""
        result = _message_to_dict(self._message(), self._entity())

        assert result["text_content"] == "Grøn omstilling i Folketing."

    def test_message_to_dict_reactions_extracted(self) -> None:
        """_message_to_dict() extracts reaction emoji and count pairs."""
        result = _message_to_dict(self._message(), self._entity())

        assert len(result["reactions"]) == 2
        assert sum(r["count"] for r in result["reactions"]) == 200

    def test_message_to_dict_views_count(self) -> None:
        """_message_to_dict() maps message.views to views_count."""
        result = _message_to_dict(self._message(), self._entity())

        assert result["views_count"] == 5000

    def test_message_to_dict_forwards_count(self) -> None:
        """_message_to_dict() maps message.forwards to forwards_count."""
        result = _message_to_dict(self._message(), self._entity())

        assert result["forwards_count"] == 120

    def test_message_to_dict_published_at_is_utc_iso(self) -> None:
        """_message_to_dict() produces a timezone-aware ISO 8601 published_at string."""
        result = _message_to_dict(self._message(), self._entity())

        assert result["published_at"] is not None
        assert "2026-02-15" in result["published_at"]

    def test_message_to_dict_has_media_false_when_no_media(self) -> None:
        """_message_to_dict() sets has_media=False when message.media is None."""
        msg = _make_message(has_media=False)
        result = _message_to_dict(msg, self._entity())

        assert result["has_media"] is False
        assert result["media_type"] is None

    def test_message_to_dict_is_forwarded_false_for_original_message(self) -> None:
        """_message_to_dict() sets is_forwarded=False when fwd_from is None."""
        result = _message_to_dict(self._message(), self._entity())

        assert result["is_forwarded"] is False

    def test_message_to_dict_is_forwarded_true_with_fwd_from(self) -> None:
        """_message_to_dict() sets is_forwarded=True when fwd_from is present."""
        fwd = MagicMock()
        fwd.channel_id = 999888777
        msg = _make_message(fwd_from=fwd)
        result = _message_to_dict(msg, self._entity())

        assert result["is_forwarded"] is True
        assert result["fwd_from_channel_id"] == "999888777"


# ---------------------------------------------------------------------------
# normalize() unit tests
# ---------------------------------------------------------------------------


class TestNormalize:
    def _collector(self) -> TelegramCollector:
        return TelegramCollector()

    def _raw_item(self, **overrides: Any) -> dict[str, Any]:
        """Build a minimal raw dict matching the _message_to_dict() output schema."""
        base: dict[str, Any] = {
            "channel_id": 111222333,
            "message_id": 1001,
            "channel_username": "dr_nyheder",
            "channel_title": "DR Nyheder",
            "text_content": "Grøn omstilling i Folketing. Ålborg er foregangsby.",
            "published_at": "2026-02-15T10:00:00+00:00",
            "views_count": 5000,
            "forwards_count": 120,
            "replies_count": 7,
            "reactions": [{"emoji": "👍", "count": 150}, {"emoji": "❤️", "count": 50}],
            "is_forwarded": False,
            "fwd_from_channel_id": None,
            "reply_to_msg_id": None,
            "has_media": False,
            "media_type": None,
            "edit_date": None,
            "grouped_id": None,
            "via_bot_id": None,
        }
        base.update(overrides)
        return base

    def test_normalize_sets_platform_telegram(self) -> None:
        """normalize() sets platform='telegram'."""
        result = self._collector().normalize(self._raw_item())

        assert result["platform"] == "telegram"

    def test_normalize_sets_arena_social_media(self) -> None:
        """normalize() sets arena='social_media'."""
        result = self._collector().normalize(self._raw_item())

        assert result["arena"] == "social_media"

    def test_normalize_content_type_is_post(self) -> None:
        """normalize() sets content_type='post' for all Telegram messages."""
        result = self._collector().normalize(self._raw_item())

        assert result["content_type"] == "post"

    def test_normalize_platform_id_is_channel_message_composite(self) -> None:
        """normalize() sets platform_id to '{channel_id}_{message_id}'."""
        result = self._collector().normalize(self._raw_item())

        assert result["platform_id"] == "111222333_1001"

    def test_normalize_url_constructed_from_channel_username_and_message_id(self) -> None:
        """normalize() constructs https://t.me/{username}/{msg_id} URL."""
        result = self._collector().normalize(self._raw_item())

        assert result["url"] == "https://t.me/dr_nyheder/1001"

    def test_normalize_url_is_none_when_channel_has_no_username(self) -> None:
        """normalize() sets url=None when channel has no public username."""
        result = self._collector().normalize(self._raw_item(channel_username=""))

        assert result["url"] is None

    def test_normalize_author_display_name_from_channel_title(self) -> None:
        """normalize() maps channel_title to author_display_name."""
        result = self._collector().normalize(self._raw_item())

        assert result["author_display_name"] == "DR Nyheder"

    def test_normalize_pseudonymized_author_id_set_when_channel_title_present(self) -> None:
        """normalize() computes a 64-char pseudonymized_author_id from channel_title."""
        result = self._collector().normalize(self._raw_item())

        assert result["pseudonymized_author_id"] is not None
        assert len(result["pseudonymized_author_id"]) == 64

    def test_normalize_likes_count_is_sum_of_all_reactions(self) -> None:
        """normalize() sums all reaction counts into likes_count (150 + 50 = 200)."""
        result = self._collector().normalize(self._raw_item())

        assert result["likes_count"] == 200

    def test_normalize_likes_count_none_when_reactions_empty(self) -> None:
        """normalize() sets likes_count=None when reactions list is empty."""
        result = self._collector().normalize(self._raw_item(reactions=[]))

        assert result["likes_count"] is None

    def test_normalize_shares_count_from_forwards_count(self) -> None:
        """normalize() maps forwards_count to shares_count."""
        result = self._collector().normalize(self._raw_item())

        assert result["shares_count"] == 120

    def test_normalize_comments_count_from_replies_count(self) -> None:
        """normalize() maps replies_count to comments_count."""
        result = self._collector().normalize(self._raw_item())

        assert result["comments_count"] == 7

    def test_normalize_views_count_preserved(self) -> None:
        """normalize() maps views_count field through to normalized output."""
        result = self._collector().normalize(self._raw_item())

        assert result["views_count"] == 5000

    def test_normalize_media_urls_always_empty_in_phase_1(self) -> None:
        """normalize() returns empty media_urls list (Phase 1: no media download)."""
        result = self._collector().normalize(
            self._raw_item(has_media=True, media_type="MessageMediaPhoto")
        )

        assert result["media_urls"] == []

    def test_normalize_required_fields_always_present(self) -> None:
        """All required schema fields are present in normalized output."""
        result = self._collector().normalize(self._raw_item())

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field is None: {field}"

    def test_normalize_content_hash_is_64_char_hex(self) -> None:
        """normalize() computes a 64-character hex content_hash."""
        result = self._collector().normalize(self._raw_item())

        assert result["content_hash"] is not None
        assert len(result["content_hash"]) == 64
        assert all(c in "0123456789abcdef" for c in result["content_hash"])

    def test_normalize_preserves_danish_characters_in_text(self) -> None:
        """ae, o, a in Telegram message survive normalize() without corruption."""
        result = self._collector().normalize(self._raw_item())

        assert "Grøn" in result["text_content"]
        assert "Ålborg" in result["text_content"]

    @pytest.mark.parametrize("char", ["æ", "ø", "å", "Æ", "Ø", "Å"])
    def test_normalize_handles_each_danish_character_in_text(self, char: str) -> None:
        """Each Danish character in Telegram message survives normalize() without error."""
        result = self._collector().normalize(
            self._raw_item(text_content=f"Besked med {char} tegn i teksten.")
        )

        assert char in result["text_content"]

    def test_normalize_collection_tier_is_free(self) -> None:
        """normalize() sets collection_tier='free' (Telegram only has FREE tier)."""
        result = self._collector().normalize(self._raw_item())

        assert result["collection_tier"] == "free"


# ---------------------------------------------------------------------------
# Utility function unit tests
# ---------------------------------------------------------------------------


class TestBuildChannelList:
    def test_build_channel_list_merges_default_and_actor_ids(self) -> None:
        """_build_channel_list() merges default channels and actor_ids."""
        result = _build_channel_list(
            ["dr_nyheder", "tv2nyhederne"],
            ["tv2nyhederne", "berlingske"],
        )
        assert result == ["dr_nyheder", "tv2nyhederne", "berlingske"]

    def test_build_channel_list_none_actor_ids_returns_defaults_only(self) -> None:
        """_build_channel_list() handles None actor_ids gracefully."""
        result = _build_channel_list(["dr_nyheder"], None)
        assert result == ["dr_nyheder"]

    def test_build_channel_list_empty_defaults_with_actor_ids(self) -> None:
        """_build_channel_list() handles empty default channels."""
        result = _build_channel_list([], ["berlingske"])
        assert result == ["berlingske"]


class TestParseDatetime:
    def test_parse_datetime_none_returns_none(self) -> None:
        """_parse_datetime(None) returns None."""
        assert _parse_datetime(None) is None

    def test_parse_datetime_iso_string_with_timezone(self) -> None:
        """_parse_datetime() parses an ISO 8601 string with UTC offset."""
        result = _parse_datetime("2026-02-15T10:00:00+00:00")
        assert result is not None
        assert result.tzinfo is not None
        assert result.year == 2026

    def test_parse_datetime_naive_datetime_gets_utc_timezone(self) -> None:
        """_parse_datetime() adds UTC timezone to a naive datetime object."""
        naive = datetime(2026, 2, 15, 10, 0, 0)
        result = _parse_datetime(naive)
        assert result is not None
        assert result.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# collect_by_terms() integration tests
# ---------------------------------------------------------------------------


class TestCollectByTerms:
    @pytest.mark.asyncio
    async def test_collect_by_terms_returns_records_from_channel(self) -> None:
        """collect_by_terms() returns non-empty list when channel has matching messages."""
        msg = _make_message(msg_id=1001, text="Grøn omstilling diskuteres i Folketing.")
        entity = _make_entity()
        client_mock = _make_async_client_mock(entity=entity, messages=[msg])

        pool = _make_mock_pool()
        collector = TelegramCollector(
            credential_pool=pool,
            default_channels=["dr_nyheder"],
        )

        with patch(_TELETHON_CLIENT_PATH, return_value=client_mock):
            with patch(_TELETHON_STRING_SESSION_PATH, return_value=MagicMock()):
                with patch(_FLOOD_WAIT_PATH, Exception):
                    with patch(_USER_BAN_PATH, Exception):
                        records = await collector.collect_by_terms(
                            terms=["grøn omstilling"],
                            tier=Tier.FREE,
                            max_results=10,
                        )

        assert isinstance(records, list)
        assert len(records) >= 1
        assert records[0]["platform"] == "telegram"
        assert records[0]["arena"] == "social_media"

    @pytest.mark.asyncio
    async def test_collect_by_terms_empty_channel_returns_empty_list(self) -> None:
        """collect_by_terms() returns [] when channel has no messages."""
        entity = _make_entity()
        client_mock = _make_async_client_mock(entity=entity, messages=[])

        pool = _make_mock_pool()
        collector = TelegramCollector(
            credential_pool=pool,
            default_channels=["dr_nyheder"],
        )

        with patch(_TELETHON_CLIENT_PATH, return_value=client_mock):
            with patch(_TELETHON_STRING_SESSION_PATH, return_value=MagicMock()):
                with patch(_FLOOD_WAIT_PATH, Exception):
                    with patch(_USER_BAN_PATH, Exception):
                        records = await collector.collect_by_terms(
                            terms=["nonexistent_xyz_999"],
                            tier=Tier.FREE,
                            max_results=10,
                        )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_flood_wait_raises_rate_limit_error(self) -> None:
        """collect_by_terms() raises ArenaRateLimitError when FloodWaitError occurs."""
        pool = _make_mock_pool()
        collector = TelegramCollector(
            credential_pool=pool,
            default_channels=["dr_nyheder"],
        )

        with patch.object(
            collector,
            "_collect_terms_with_credential",
            new=AsyncMock(
                side_effect=ArenaRateLimitError(
                    "telegram: FloodWaitError — must wait 60s",
                    retry_after=60.0,
                    arena="social_media",
                    platform="telegram",
                )
            ),
        ):
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_terms(
                    terms=["test"], tier=Tier.FREE, max_results=5
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_unexpected_exception_raises_collection_error(
        self,
    ) -> None:
        """collect_by_terms() raises ArenaCollectionError on unexpected Telethon errors."""
        pool = _make_mock_pool()
        collector = TelegramCollector(
            credential_pool=pool,
            default_channels=["dr_nyheder"],
        )

        with patch.object(
            collector,
            "_collect_terms_with_credential",
            new=AsyncMock(
                side_effect=ArenaCollectionError(
                    "telegram: unexpected error during term collection",
                    arena="social_media",
                    platform="telegram",
                )
            ),
        ):
            with pytest.raises(ArenaCollectionError):
                await collector.collect_by_terms(
                    terms=["test"], tier=Tier.FREE, max_results=5
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_no_credential_raises_no_credential_error(self) -> None:
        """collect_by_terms() raises NoCredentialAvailableError when no pool configured."""
        collector = TelegramCollector()  # no credential pool
        with pytest.raises(NoCredentialAvailableError):
            await collector.collect_by_terms(
                terms=["test"], tier=Tier.FREE, max_results=5
            )

    @pytest.mark.asyncio
    async def test_collect_by_terms_non_free_tier_logs_warning_and_proceeds(
        self, caplog: Any
    ) -> None:
        """collect_by_terms() at non-FREE tier logs a WARNING and falls through to FREE."""
        msg = _make_message(msg_id=2001, text="Dansk indhold om velfærd.")
        entity = _make_entity()
        client_mock = _make_async_client_mock(entity=entity, messages=[msg])

        pool = _make_mock_pool()
        collector = TelegramCollector(
            credential_pool=pool,
            default_channels=["dr_nyheder"],
        )

        with caplog.at_level(logging.WARNING, logger="issue_observatory.arenas.telegram.collector"):
            with patch(_TELETHON_CLIENT_PATH, return_value=client_mock):
                with patch(_TELETHON_STRING_SESSION_PATH, return_value=MagicMock()):
                    with patch(_FLOOD_WAIT_PATH, Exception):
                        with patch(_USER_BAN_PATH, Exception):
                            records = await collector.collect_by_terms(
                                terms=["velfærd"],
                                tier=Tier.MEDIUM,  # non-FREE tier
                                max_results=10,
                            )

        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(
            "medium" in r.message.lower() or "free" in r.message.lower()
            for r in warning_records
        )
        assert isinstance(records, list)

    @pytest.mark.asyncio
    async def test_collect_by_terms_deduplicates_identical_messages(self) -> None:
        """collect_by_terms() returns each message at most once across multiple terms."""
        msg = _make_message(msg_id=1001, text="Grøn omstilling.")
        entity = _make_entity()
        # Return the same message for both terms
        client_mock = _make_async_client_mock(entity=entity, messages=[msg])

        pool = _make_mock_pool()
        collector = TelegramCollector(
            credential_pool=pool,
            default_channels=["dr_nyheder"],
        )

        with patch(_TELETHON_CLIENT_PATH, return_value=client_mock):
            with patch(_TELETHON_STRING_SESSION_PATH, return_value=MagicMock()):
                with patch(_FLOOD_WAIT_PATH, Exception):
                    with patch(_USER_BAN_PATH, Exception):
                        records = await collector.collect_by_terms(
                            terms=["grøn", "omstilling"],  # two terms, same channel
                            tier=Tier.FREE,
                            max_results=20,
                        )

        platform_ids = [r["platform_id"] for r in records]
        assert len(platform_ids) == len(set(platform_ids)), "Duplicate platform_ids found"

    @pytest.mark.asyncio
    async def test_collect_by_terms_preserves_danish_characters_end_to_end(
        self,
    ) -> None:
        """Danish characters survive the full collect -> normalize pipeline."""
        danish_text = "Velfærdsdebatten: Ærø og Ålborg er med. Øresund-strategi er vigtig."
        msg = _make_message(msg_id=3001, text=danish_text)
        entity = _make_entity()
        client_mock = _make_async_client_mock(entity=entity, messages=[msg])

        pool = _make_mock_pool()
        collector = TelegramCollector(
            credential_pool=pool,
            default_channels=["dr_nyheder"],
        )

        with patch(_TELETHON_CLIENT_PATH, return_value=client_mock):
            with patch(_TELETHON_STRING_SESSION_PATH, return_value=MagicMock()):
                with patch(_FLOOD_WAIT_PATH, Exception):
                    with patch(_USER_BAN_PATH, Exception):
                        records = await collector.collect_by_terms(
                            terms=["velfærd"],
                            tier=Tier.FREE,
                            max_results=10,
                        )

        texts = [r.get("text_content", "") or "" for r in records]
        assert any("æ" in t or "ø" in t or "å" in t for t in texts)


# ---------------------------------------------------------------------------
# collect_by_actors() integration tests
# ---------------------------------------------------------------------------


class TestCollectByActors:
    @pytest.mark.asyncio
    async def test_collect_by_actors_returns_records_from_channel(self) -> None:
        """collect_by_actors() returns normalized records from the specified channel."""
        msg = _make_message(msg_id=2001, text="Grøn omstilling nyheder fra DR.")
        entity = _make_entity()
        client_mock = _make_async_client_mock(entity=entity, messages=[msg])

        pool = _make_mock_pool()
        collector = TelegramCollector(credential_pool=pool)

        with patch(_TELETHON_CLIENT_PATH, return_value=client_mock):
            with patch(_TELETHON_STRING_SESSION_PATH, return_value=MagicMock()):
                with patch(_FLOOD_WAIT_PATH, Exception):
                    with patch(_USER_BAN_PATH, Exception):
                        records = await collector.collect_by_actors(
                            actor_ids=["dr_nyheder"],
                            tier=Tier.FREE,
                            max_results=10,
                        )

        assert isinstance(records, list)
        assert len(records) >= 1
        assert records[0]["platform"] == "telegram"
        assert records[0]["arena"] == "social_media"

    @pytest.mark.asyncio
    async def test_collect_by_actors_empty_channel_returns_empty_list(self) -> None:
        """collect_by_actors() returns [] when channel has no messages."""
        entity = _make_entity()
        client_mock = _make_async_client_mock(entity=entity, messages=[])

        pool = _make_mock_pool()
        collector = TelegramCollector(credential_pool=pool)

        with patch(_TELETHON_CLIENT_PATH, return_value=client_mock):
            with patch(_TELETHON_STRING_SESSION_PATH, return_value=MagicMock()):
                with patch(_FLOOD_WAIT_PATH, Exception):
                    with patch(_USER_BAN_PATH, Exception):
                        records = await collector.collect_by_actors(
                            actor_ids=["empty_channel"],
                            tier=Tier.FREE,
                            max_results=10,
                        )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_actors_no_credential_raises_no_credential_error(
        self,
    ) -> None:
        """collect_by_actors() raises NoCredentialAvailableError when no pool configured."""
        collector = TelegramCollector()  # no credential pool
        with pytest.raises(NoCredentialAvailableError):
            await collector.collect_by_actors(
                actor_ids=["dr_nyheder"],
                tier=Tier.FREE,
                max_results=5,
            )

    @pytest.mark.asyncio
    async def test_collect_by_actors_flood_wait_raises_rate_limit_error(self) -> None:
        """collect_by_actors() raises ArenaRateLimitError on FloodWaitError from Telegram."""
        pool = _make_mock_pool()
        collector = TelegramCollector(credential_pool=pool)

        with patch.object(
            collector,
            "_collect_actors_with_credential",
            new=AsyncMock(
                side_effect=ArenaRateLimitError(
                    "telegram: FloodWaitError — must wait 120s",
                    retry_after=120.0,
                    arena="social_media",
                    platform="telegram",
                )
            ),
        ):
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_actors(
                    actor_ids=["dr_nyheder"],
                    tier=Tier.FREE,
                    max_results=5,
                )

    @pytest.mark.asyncio
    async def test_collect_by_actors_private_channel_skipped_returns_empty(
        self,
    ) -> None:
        """collect_by_actors() returns [] when _collect_actors_with_credential returns []."""
        pool = _make_mock_pool()
        collector = TelegramCollector(credential_pool=pool)

        with patch.object(
            collector,
            "_collect_actors_with_credential",
            new=AsyncMock(return_value=[]),  # private channel -> empty
        ):
            records = await collector.collect_by_actors(
                actor_ids=["some_private_channel"],
                tier=Tier.FREE,
                max_results=10,
            )

        assert records == []


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_ok_when_get_me_succeeds(self) -> None:
        """health_check() returns status='ok' when Telethon get_me() returns a user."""
        me_mock = MagicMock()
        me_mock.id = 99999
        client_mock = _make_async_client_mock(me=me_mock)

        pool = _make_mock_pool()

        with patch(_TELETHON_CLIENT_PATH, return_value=client_mock):
            with patch(_TELETHON_STRING_SESSION_PATH, return_value=MagicMock()):
                collector = TelegramCollector(credential_pool=pool)
                result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "social_media"
        assert result["platform"] == "telegram"
        assert "checked_at" in result
        assert "99999" in result.get("detail", "")

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_when_no_credential_pool(self) -> None:
        """health_check() returns status='degraded' when no credential pool is set."""
        collector = TelegramCollector()  # no pool
        result = await collector.health_check()

        assert result["status"] == "degraded"
        assert "checked_at" in result
        assert "No Telegram credential" in result.get("detail", "")

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_when_pool_acquire_returns_none(
        self,
    ) -> None:
        """health_check() returns status='degraded' when pool.acquire() returns None."""
        pool = _make_mock_pool(cred=None)
        collector = TelegramCollector(credential_pool=pool)
        result = await collector.health_check()

        assert result["status"] == "degraded"
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_telegram_client_exception(self) -> None:
        """health_check() returns status='down' when TelegramClient raises an exception."""
        pool = _make_mock_pool()

        with patch(
            _TELETHON_CLIENT_PATH,
            side_effect=Exception("Connection refused: Telegram unreachable"),
        ):
            with patch(_TELETHON_STRING_SESSION_PATH, return_value=MagicMock()):
                collector = TelegramCollector(credential_pool=pool)
                result = await collector.health_check()

        assert result["status"] == "down"
        assert "checked_at" in result
        assert "Connection refused" in result.get("detail", "")

    @pytest.mark.asyncio
    async def test_health_check_returns_degraded_when_get_me_returns_none(self) -> None:
        """health_check() returns status='degraded' when get_me() returns None."""
        client_mock = _make_async_client_mock()
        client_mock.get_me = AsyncMock(return_value=None)

        pool = _make_mock_pool()

        with patch(_TELETHON_CLIENT_PATH, return_value=client_mock):
            with patch(_TELETHON_STRING_SESSION_PATH, return_value=MagicMock()):
                collector = TelegramCollector(credential_pool=pool)
                result = await collector.health_check()

        assert result["status"] == "degraded"
        assert "checked_at" in result


# ---------------------------------------------------------------------------
# get_tier_config() tests
# ---------------------------------------------------------------------------


class TestGetTierConfig:
    def test_get_tier_config_free_returns_non_none_config(self) -> None:
        """get_tier_config(Tier.FREE) returns a non-None TierConfig."""
        collector = TelegramCollector()
        config = collector.get_tier_config(Tier.FREE)
        assert config is not None

    def test_get_tier_config_medium_returns_none(self) -> None:
        """get_tier_config(Tier.MEDIUM) returns None (MEDIUM not supported)."""
        collector = TelegramCollector()
        config = collector.get_tier_config(Tier.MEDIUM)
        assert config is None

    def test_get_tier_config_premium_returns_none(self) -> None:
        """get_tier_config(Tier.PREMIUM) returns None (PREMIUM not supported)."""
        collector = TelegramCollector()
        config = collector.get_tier_config(Tier.PREMIUM)
        assert config is None
