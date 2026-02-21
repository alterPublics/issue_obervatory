"""Tests for the Discord arena collector.

Covers:
- normalize() unit tests: platform/arena/content_type, author fields,
  reactions aggregated to likes_count, thread message_count to comments_count,
  referenced_message mapping, attachment/embed/mention raw_metadata,
  Discord message URL construction, Danish character preservation
- collect_by_terms() with mocked Discord API (respx): happy path,
  empty results, client-side term matching, boolean term_groups,
  missing channel_ids raises ArenaCollectionError, GR-04 extra_channel_ids
- collect_by_actors() with mocked Discord API: happy path, author filtering
- HTTP 429 -> ArenaRateLimitError
- Tier validation: only FREE is supported
- health_check() returns 'ok', 'down' as appropriate
- NoCredentialAvailableError when no credential pool is configured

These tests run without a live database or network connection.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

# ---------------------------------------------------------------------------
# Env bootstrap (must run before any application imports)
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==")

from issue_observatory.arenas.base import Tier  # noqa: E402
from issue_observatory.arenas.discord._http import enrich_message  # noqa: E402
from issue_observatory.arenas.discord.collector import (  # noqa: E402
    DiscordCollector,
    _merge_channel_ids,
)
from issue_observatory.arenas.discord.config import DISCORD_API_BASE  # noqa: E402
from issue_observatory.core.exceptions import (  # noqa: E402
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "api_responses" / "discord"


def _load_messages_fixture() -> list[dict[str, Any]]:
    """Load the recorded Discord channel messages fixture."""
    return json.loads(
        (FIXTURES_DIR / "channel_messages_response.json").read_text(encoding="utf-8")
    )


def _load_channel_metadata_fixture() -> dict[str, Any]:
    """Load the recorded Discord channel metadata fixture."""
    return json.loads(
        (FIXTURES_DIR / "channel_metadata_response.json").read_text(encoding="utf-8")
    )


def _load_gateway_fixture() -> dict[str, Any]:
    """Load the recorded Discord gateway fixture."""
    return json.loads(
        (FIXTURES_DIR / "gateway_response.json").read_text(encoding="utf-8")
    )


def _first_message_enriched() -> dict[str, Any]:
    """Return the first message, enriched with channel metadata for normalize()."""
    messages = _load_messages_fixture()
    channel_meta = _load_channel_metadata_fixture()
    return enrich_message(messages[0], "9876543210987654321", channel_meta)


def _second_message_enriched() -> dict[str, Any]:
    """Return the second message (with attachments/thread/reply), enriched."""
    messages = _load_messages_fixture()
    channel_meta = _load_channel_metadata_fixture()
    return enrich_message(messages[1], "9876543210987654321", channel_meta)


# ---------------------------------------------------------------------------
# Mock credential pool
# ---------------------------------------------------------------------------


def _make_mock_pool(bot_token: str = "test-discord-bot-token") -> Any:
    """Build a minimal mock CredentialPool returning a Discord bot token."""
    pool = MagicMock()
    pool.acquire = AsyncMock(
        return_value={
            "id": "cred-discord-001",
            "bot_token": bot_token,
        }
    )
    pool.release = AsyncMock(return_value=None)
    pool.report_error = AsyncMock(return_value=None)
    return pool


# ---------------------------------------------------------------------------
# normalize() unit tests
# ---------------------------------------------------------------------------


class TestNormalize:
    def _collector(self) -> DiscordCollector:
        return DiscordCollector()

    def test_normalize_sets_platform_arena_content_type(self) -> None:
        """normalize() sets platform='discord', arena='social_media', content_type='post'."""
        collector = self._collector()
        result = collector.normalize(_first_message_enriched())

        assert result["platform"] == "discord"
        assert result["arena"] == "social_media"
        assert result["content_type"] == "post"

    def test_normalize_platform_id_is_message_id(self) -> None:
        """normalize() sets platform_id to the Discord message snowflake ID."""
        collector = self._collector()
        msg = _first_message_enriched()
        result = collector.normalize(msg)

        assert result["platform_id"] == "1234567890123456789"

    def test_normalize_text_content_from_message_content(self) -> None:
        """normalize() maps the 'content' field to text_content."""
        collector = self._collector()
        result = collector.normalize(_first_message_enriched())

        assert result["text_content"] is not None
        assert "klimapolitik" in result["text_content"]

    def test_normalize_url_is_discord_message_link(self) -> None:
        """normalize() constructs the correct discord.com message URL."""
        collector = self._collector()
        result = collector.normalize(_first_message_enriched())

        expected_url = (
            "https://discord.com/channels/"
            "5555555555555555555/9876543210987654321/1234567890123456789"
        )
        assert result["url"] == expected_url

    def test_normalize_author_display_name_from_global_name(self) -> None:
        """normalize() uses global_name as author_display_name when available."""
        collector = self._collector()
        result = collector.normalize(_first_message_enriched())

        assert result["author_display_name"] == "Soeren Oestergaard"

    def test_normalize_author_display_name_falls_back_to_username(self) -> None:
        """normalize() falls back to username when global_name is absent."""
        collector = self._collector()
        msg = _first_message_enriched()
        msg["author"]["global_name"] = None
        result = collector.normalize(msg)

        assert result["author_display_name"] == "soeren_dk"

    def test_normalize_pseudonymized_author_id_set(self) -> None:
        """normalize() computes a 64-char hex pseudonymized_author_id."""
        collector = self._collector()
        result = collector.normalize(_first_message_enriched())

        assert result["pseudonymized_author_id"] is not None
        assert len(result["pseudonymized_author_id"]) == 64

    def test_normalize_no_author_produces_none_author_fields(self) -> None:
        """normalize() handles missing author dict gracefully."""
        collector = self._collector()
        msg = _first_message_enriched()
        msg["author"] = None
        result = collector.normalize(msg)

        assert result["author_display_name"] is None or result["author_display_name"] == ""
        assert result["pseudonymized_author_id"] is None

    def test_normalize_likes_count_from_reactions(self) -> None:
        """normalize() sums reaction counts into likes_count."""
        collector = self._collector()
        result = collector.normalize(_first_message_enriched())

        # First message has 5 + 3 = 8 reactions
        assert result["likes_count"] == 8

    def test_normalize_no_reactions_produces_none_likes(self) -> None:
        """normalize() returns None for likes_count when there are no reactions."""
        collector = self._collector()
        msg = _first_message_enriched()
        msg["reactions"] = []
        result = collector.normalize(msg)

        assert result["likes_count"] is None

    def test_normalize_comments_count_from_thread(self) -> None:
        """normalize() maps thread.message_count to comments_count."""
        collector = self._collector()
        result = collector.normalize(_second_message_enriched())

        assert result["comments_count"] == 12

    def test_normalize_comments_count_none_when_no_thread(self) -> None:
        """normalize() returns None for comments_count when no thread exists."""
        collector = self._collector()
        result = collector.normalize(_first_message_enriched())

        assert result["comments_count"] is None

    def test_normalize_raw_metadata_has_guild_channel_info(self) -> None:
        """normalize() embeds guild_id, channel_id, channel_name in raw_metadata."""
        collector = self._collector()
        result = collector.normalize(_first_message_enriched())

        # The Normalizer wraps raw_metadata as dict(raw_item), so the
        # arena-specific metadata dict is nested at raw_metadata["raw_metadata"].
        meta = result["raw_metadata"]["raw_metadata"]
        assert meta["guild_id"] == "5555555555555555555"
        assert meta["channel_id"] == "9876543210987654321"
        assert meta["channel_name"] == "dansk-politik"
        assert meta["guild_name"] == "Danmark Debat Server"

    def test_normalize_raw_metadata_attachments(self) -> None:
        """normalize() lists attachment URLs in raw_metadata.attachments."""
        collector = self._collector()
        result = collector.normalize(_second_message_enriched())

        meta = result["raw_metadata"]["raw_metadata"]
        assert len(meta["attachments"]) == 1
        assert "folkeskolen.pdf" in meta["attachments"][0]

    def test_normalize_raw_metadata_embeds_count(self) -> None:
        """normalize() stores embed count in raw_metadata.embeds."""
        collector = self._collector()
        result = collector.normalize(_second_message_enriched())

        assert result["raw_metadata"]["raw_metadata"]["embeds"] == 1

    def test_normalize_raw_metadata_mentions(self) -> None:
        """normalize() lists mentioned user IDs in raw_metadata.mentions."""
        collector = self._collector()
        result = collector.normalize(_second_message_enriched())

        assert "1111111111111111111" in result["raw_metadata"]["raw_metadata"]["mentions"]

    def test_normalize_raw_metadata_referenced_message_id(self) -> None:
        """normalize() stores the referenced message ID when present."""
        collector = self._collector()
        result = collector.normalize(_second_message_enriched())

        assert result["raw_metadata"]["raw_metadata"]["referenced_message_id"] == "1234567890123456789"

    def test_normalize_raw_metadata_thread_id(self) -> None:
        """normalize() stores thread_id when the message has a thread."""
        collector = self._collector()
        result = collector.normalize(_second_message_enriched())

        assert result["raw_metadata"]["raw_metadata"]["thread_id"] == "9999999999999999999"

    def test_normalize_published_at_from_timestamp(self) -> None:
        """normalize() maps the Discord timestamp to published_at."""
        collector = self._collector()
        result = collector.normalize(_first_message_enriched())

        assert result["published_at"] is not None
        assert "2026-02-15" in result["published_at"]

    def test_normalize_content_hash_is_64_char_hex(self) -> None:
        """normalize() computes a 64-character hex content_hash."""
        collector = self._collector()
        result = collector.normalize(_first_message_enriched())

        assert result["content_hash"] is not None
        assert len(result["content_hash"]) == 64
        assert all(c in "0123456789abcdef" for c in result["content_hash"])

    def test_normalize_collection_tier_is_free(self) -> None:
        """normalize() sets collection_tier='free'."""
        collector = self._collector()
        result = collector.normalize(_first_message_enriched())

        assert result["collection_tier"] == "free"

    def test_normalize_required_fields_always_present(self) -> None:
        """All required schema fields are present in normalized output."""
        collector = self._collector()
        result = collector.normalize(_first_message_enriched())

        for field in ("platform", "arena", "content_type", "collected_at", "collection_tier"):
            assert field in result, f"Missing required field: {field}"
            assert result[field] is not None, f"Required field is None: {field}"

    @pytest.mark.parametrize("char", ["ae", "oe", "aa", "AE", "OE", "AA"])
    def test_normalize_preserves_danish_transliterated_chars(self, char: str) -> None:
        """Danish transliterated character sequences survive normalize()."""
        collector = self._collector()
        msg = _first_message_enriched()
        msg["content"] = f"En besked med {char} tegn i teksten."
        result = collector.normalize(msg)

        assert char in result["text_content"]

    def test_normalize_preserves_danish_text_from_fixture(self) -> None:
        """Danish text from the fixture survives normalize() without corruption."""
        collector = self._collector()
        result = collector.normalize(_first_message_enriched())

        text = result.get("text_content", "")
        # The fixture uses ASCII-transliterated Danish -- verify content is preserved
        assert "klimapolitik" in text
        assert "Aalborg" in text

    def test_normalize_empty_content_produces_none_text(self) -> None:
        """normalize() returns None for text_content when message content is empty."""
        collector = self._collector()
        msg = _first_message_enriched()
        msg["content"] = ""
        result = collector.normalize(msg)

        assert result["text_content"] is None


# ---------------------------------------------------------------------------
# _merge_channel_ids() unit tests
# ---------------------------------------------------------------------------


class TestMergeChannelIds:
    def test_merge_both_lists(self) -> None:
        """_merge_channel_ids() merges and deduplicates two lists."""
        result = _merge_channel_ids(["111", "222"], ["222", "333"])
        assert result == ["111", "222", "333"]

    def test_merge_none_inputs(self) -> None:
        """_merge_channel_ids() returns empty list when both inputs are None."""
        assert _merge_channel_ids(None, None) == []

    def test_merge_only_channel_ids(self) -> None:
        """_merge_channel_ids() works with only channel_ids provided."""
        result = _merge_channel_ids(["111", "222"], None)
        assert result == ["111", "222"]

    def test_merge_only_extra_ids(self) -> None:
        """_merge_channel_ids() works with only extra_channel_ids provided."""
        result = _merge_channel_ids(None, ["333", "444"])
        assert result == ["333", "444"]

    def test_merge_strips_whitespace(self) -> None:
        """_merge_channel_ids() strips whitespace from IDs."""
        result = _merge_channel_ids(["  111  "], [" 222 "])
        assert result == ["111", "222"]

    def test_merge_skips_empty_strings(self) -> None:
        """_merge_channel_ids() skips empty string IDs."""
        result = _merge_channel_ids(["111", "", "  "], ["222"])
        assert result == ["111", "222"]


# ---------------------------------------------------------------------------
# collect_by_terms() integration tests
# ---------------------------------------------------------------------------


class TestCollectByTerms:
    @pytest.mark.asyncio
    async def test_collect_by_terms_returns_matching_records(self) -> None:
        """collect_by_terms() returns records matching search terms."""
        messages = _load_messages_fixture()
        channel_meta = _load_channel_metadata_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            # Channel metadata request
            respx.get(f"{DISCORD_API_BASE}/channels/9876543210987654321").mock(
                return_value=httpx.Response(200, json=channel_meta)
            )
            # Channel messages request
            respx.get(f"{DISCORD_API_BASE}/channels/9876543210987654321/messages").mock(
                return_value=httpx.Response(200, json=messages)
            )
            collector = DiscordCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["klimapolitik"],
                tier=Tier.FREE,
                max_results=10,
                channel_ids=["9876543210987654321"],
            )

        assert isinstance(records, list)
        assert len(records) >= 1
        assert records[0]["platform"] == "discord"
        assert records[0]["content_type"] == "post"

    @pytest.mark.asyncio
    async def test_collect_by_terms_no_matching_terms_returns_empty(self) -> None:
        """collect_by_terms() returns [] when no messages match the search terms."""
        messages = _load_messages_fixture()
        channel_meta = _load_channel_metadata_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(f"{DISCORD_API_BASE}/channels/9876543210987654321").mock(
                return_value=httpx.Response(200, json=channel_meta)
            )
            respx.get(f"{DISCORD_API_BASE}/channels/9876543210987654321/messages").mock(
                return_value=httpx.Response(200, json=messages)
            )
            collector = DiscordCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["nonexistent_xyz_query"],
                tier=Tier.FREE,
                max_results=10,
                channel_ids=["9876543210987654321"],
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_empty_channel_returns_empty(self) -> None:
        """collect_by_terms() returns [] when channel has no messages."""
        channel_meta = _load_channel_metadata_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(f"{DISCORD_API_BASE}/channels/9876543210987654321").mock(
                return_value=httpx.Response(200, json=channel_meta)
            )
            respx.get(f"{DISCORD_API_BASE}/channels/9876543210987654321/messages").mock(
                return_value=httpx.Response(200, json=[])
            )
            collector = DiscordCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["test"],
                tier=Tier.FREE,
                max_results=10,
                channel_ids=["9876543210987654321"],
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_no_channel_ids_raises_error(self) -> None:
        """collect_by_terms() raises ArenaCollectionError when no channel_ids are provided."""
        pool = _make_mock_pool()
        collector = DiscordCollector(credential_pool=pool)

        with pytest.raises(ArenaCollectionError, match="channel_ids"):
            await collector.collect_by_terms(
                terms=["test"],
                tier=Tier.FREE,
                max_results=10,
            )

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_429_raises_rate_limit_error(self) -> None:
        """collect_by_terms() raises ArenaRateLimitError on HTTP 429."""
        channel_meta = _load_channel_metadata_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(f"{DISCORD_API_BASE}/channels/9876543210987654321").mock(
                return_value=httpx.Response(200, json=channel_meta)
            )
            respx.get(f"{DISCORD_API_BASE}/channels/9876543210987654321/messages").mock(
                return_value=httpx.Response(429, headers={"Retry-After": "60"})
            )
            collector = DiscordCollector(credential_pool=pool)
            with pytest.raises(ArenaRateLimitError):
                await collector.collect_by_terms(
                    terms=["test"],
                    tier=Tier.FREE,
                    max_results=5,
                    channel_ids=["9876543210987654321"],
                )

    @pytest.mark.asyncio
    async def test_collect_by_terms_no_credential_pool_raises_error(self) -> None:
        """collect_by_terms() raises NoCredentialAvailableError without a credential pool."""
        collector = DiscordCollector(credential_pool=None)

        with pytest.raises(NoCredentialAvailableError):
            await collector.collect_by_terms(
                terms=["test"],
                tier=Tier.FREE,
                max_results=5,
                channel_ids=["9876543210987654321"],
            )

    @pytest.mark.asyncio
    async def test_collect_by_terms_missing_bot_token_raises_error(self) -> None:
        """collect_by_terms() raises NoCredentialAvailableError when credential has no bot_token."""
        pool = MagicMock()
        pool.acquire = AsyncMock(return_value={"id": "cred-no-token", "some_key": "val"})
        pool.release = AsyncMock(return_value=None)

        collector = DiscordCollector(credential_pool=pool)
        with pytest.raises(NoCredentialAvailableError):
            await collector.collect_by_terms(
                terms=["test"],
                tier=Tier.FREE,
                max_results=5,
                channel_ids=["9876543210987654321"],
            )

    @pytest.mark.asyncio
    async def test_collect_by_terms_boolean_term_groups(self) -> None:
        """collect_by_terms() supports boolean AND/OR term groups for matching."""
        messages = _load_messages_fixture()
        channel_meta = _load_channel_metadata_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(f"{DISCORD_API_BASE}/channels/9876543210987654321").mock(
                return_value=httpx.Response(200, json=channel_meta)
            )
            respx.get(f"{DISCORD_API_BASE}/channels/9876543210987654321/messages").mock(
                return_value=httpx.Response(200, json=messages)
            )
            collector = DiscordCollector(credential_pool=pool)

            # AND group: both terms must appear. "klimapolitik" AND "dansk" in first msg.
            records = await collector.collect_by_terms(
                terms=[],
                tier=Tier.FREE,
                max_results=10,
                channel_ids=["9876543210987654321"],
                term_groups=[["klimapolitik", "dansk"]],
            )

        assert len(records) >= 1

    @pytest.mark.asyncio
    async def test_collect_by_terms_extra_channel_ids_merged(self) -> None:
        """collect_by_terms() merges extra_channel_ids with channel_ids (GR-04)."""
        messages = _load_messages_fixture()
        channel_meta = _load_channel_metadata_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            # Both channels get the same responses for simplicity
            for ch_id in ["9876543210987654321", "1111111111111111112"]:
                respx.get(f"{DISCORD_API_BASE}/channels/{ch_id}").mock(
                    return_value=httpx.Response(200, json=channel_meta)
                )
                respx.get(f"{DISCORD_API_BASE}/channels/{ch_id}/messages").mock(
                    return_value=httpx.Response(200, json=messages)
                )
            collector = DiscordCollector(credential_pool=pool)
            records = await collector.collect_by_terms(
                terms=["klimapolitik"],
                tier=Tier.FREE,
                max_results=20,
                channel_ids=["9876543210987654321"],
                extra_channel_ids=["1111111111111111112"],
            )

        # Records from both channels should be present
        assert len(records) >= 2

    @pytest.mark.asyncio
    async def test_collect_by_terms_max_results_caps_output(self) -> None:
        """collect_by_terms() respects max_results cap."""
        messages = _load_messages_fixture()
        channel_meta = _load_channel_metadata_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(f"{DISCORD_API_BASE}/channels/9876543210987654321").mock(
                return_value=httpx.Response(200, json=channel_meta)
            )
            respx.get(f"{DISCORD_API_BASE}/channels/9876543210987654321/messages").mock(
                return_value=httpx.Response(200, json=messages)
            )
            collector = DiscordCollector(credential_pool=pool)
            # Use a broad term so multiple messages match
            records = await collector.collect_by_terms(
                terms=["e"],  # matches nearly everything
                tier=Tier.FREE,
                max_results=1,
                channel_ids=["9876543210987654321"],
            )

        assert len(records) <= 1


# ---------------------------------------------------------------------------
# collect_by_actors() tests
# ---------------------------------------------------------------------------


class TestCollectByActors:
    @pytest.mark.asyncio
    async def test_collect_by_actors_returns_matching_author_records(self) -> None:
        """collect_by_actors() returns records from messages by specified author IDs."""
        messages = _load_messages_fixture()
        channel_meta = _load_channel_metadata_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(f"{DISCORD_API_BASE}/channels/9876543210987654321").mock(
                return_value=httpx.Response(200, json=channel_meta)
            )
            respx.get(f"{DISCORD_API_BASE}/channels/9876543210987654321/messages").mock(
                return_value=httpx.Response(200, json=messages)
            )
            collector = DiscordCollector(credential_pool=pool)
            records = await collector.collect_by_actors(
                actor_ids=["1111111111111111111"],
                tier=Tier.FREE,
                max_results=10,
                channel_ids=["9876543210987654321"],
            )

        assert isinstance(records, list)
        assert len(records) == 1
        assert records[0]["platform"] == "discord"

    @pytest.mark.asyncio
    async def test_collect_by_actors_no_matching_actor_returns_empty(self) -> None:
        """collect_by_actors() returns [] when no messages match the actor IDs."""
        messages = _load_messages_fixture()
        channel_meta = _load_channel_metadata_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(f"{DISCORD_API_BASE}/channels/9876543210987654321").mock(
                return_value=httpx.Response(200, json=channel_meta)
            )
            respx.get(f"{DISCORD_API_BASE}/channels/9876543210987654321/messages").mock(
                return_value=httpx.Response(200, json=messages)
            )
            collector = DiscordCollector(credential_pool=pool)
            records = await collector.collect_by_actors(
                actor_ids=["9999999999999999999"],
                tier=Tier.FREE,
                max_results=10,
                channel_ids=["9876543210987654321"],
            )

        assert records == []

    @pytest.mark.asyncio
    async def test_collect_by_actors_no_channel_ids_raises_error(self) -> None:
        """collect_by_actors() raises ArenaCollectionError without channel_ids."""
        pool = _make_mock_pool()
        collector = DiscordCollector(credential_pool=pool)

        with pytest.raises(ArenaCollectionError, match="channel_ids"):
            await collector.collect_by_actors(
                actor_ids=["1111111111111111111"],
                tier=Tier.FREE,
                max_results=10,
            )

    @pytest.mark.asyncio
    async def test_collect_by_actors_multiple_actor_ids(self) -> None:
        """collect_by_actors() returns messages from multiple specified authors."""
        messages = _load_messages_fixture()
        channel_meta = _load_channel_metadata_fixture()
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(f"{DISCORD_API_BASE}/channels/9876543210987654321").mock(
                return_value=httpx.Response(200, json=channel_meta)
            )
            respx.get(f"{DISCORD_API_BASE}/channels/9876543210987654321/messages").mock(
                return_value=httpx.Response(200, json=messages)
            )
            collector = DiscordCollector(credential_pool=pool)
            records = await collector.collect_by_actors(
                actor_ids=["1111111111111111111", "2222222222222222222"],
                tier=Tier.FREE,
                max_results=10,
                channel_ids=["9876543210987654321"],
            )

        assert len(records) == 2


# ---------------------------------------------------------------------------
# Tier validation tests
# ---------------------------------------------------------------------------


class TestTierValidation:
    def test_supported_tiers_contains_only_free(self) -> None:
        """DiscordCollector.supported_tiers contains only [Tier.FREE]."""
        collector = DiscordCollector()
        assert collector.supported_tiers == [Tier.FREE]

    def test_get_tier_config_free_returns_config(self) -> None:
        """get_tier_config(Tier.FREE) returns a TierConfig."""
        collector = DiscordCollector()
        config = collector.get_tier_config(Tier.FREE)

        assert config is not None
        assert config.requires_credential is True

    def test_get_tier_config_medium_raises_value_error(self) -> None:
        """get_tier_config(Tier.MEDIUM) raises ValueError."""
        collector = DiscordCollector()
        with pytest.raises(ValueError, match="Unknown tier"):
            collector.get_tier_config(Tier.MEDIUM)

    def test_get_tier_config_premium_raises_value_error(self) -> None:
        """get_tier_config(Tier.PREMIUM) raises ValueError."""
        collector = DiscordCollector()
        with pytest.raises(ValueError, match="Unknown tier"):
            collector.get_tier_config(Tier.PREMIUM)

    @pytest.mark.asyncio
    async def test_collect_by_terms_unsupported_tier_raises_value_error(self) -> None:
        """collect_by_terms() raises ValueError when an unsupported tier is passed."""
        pool = _make_mock_pool()
        collector = DiscordCollector(credential_pool=pool)

        with pytest.raises(ValueError, match="not supported"):
            await collector.collect_by_terms(
                terms=["test"],
                tier=Tier.MEDIUM,
                max_results=5,
                channel_ids=["9876543210987654321"],
            )


# ---------------------------------------------------------------------------
# health_check() tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_ok_on_200_gateway(self) -> None:
        """health_check() returns status='ok' when /gateway returns 200."""
        pool = _make_mock_pool()
        gateway_fixture = _load_gateway_fixture()

        with respx.mock:
            respx.get(f"{DISCORD_API_BASE}/gateway").mock(
                return_value=httpx.Response(200, json=gateway_fixture)
            )
            collector = DiscordCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "social_media"
        assert result["platform"] == "discord"
        assert "checked_at" in result
        assert result["gateway_url"] == "wss://gateway.discord.gg"

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_http_error(self) -> None:
        """health_check() returns status='down' on HTTP error from /gateway."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(f"{DISCORD_API_BASE}/gateway").mock(
                return_value=httpx.Response(401)
            )
            collector = DiscordCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "down"
        assert "401" in result["detail"]

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_no_credential(self) -> None:
        """health_check() returns status='down' when no credential pool is configured."""
        collector = DiscordCollector(credential_pool=None)
        result = await collector.health_check()

        assert result["status"] == "down"
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_connection_error(self) -> None:
        """health_check() returns status='down' on connection error."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.get(f"{DISCORD_API_BASE}/gateway").mock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            collector = DiscordCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "down"
        assert "Connection" in result["detail"]

    @pytest.mark.asyncio
    async def test_health_check_always_has_arena_platform_checked_at(self) -> None:
        """health_check() always includes arena, platform, and checked_at."""
        collector = DiscordCollector(credential_pool=None)
        result = await collector.health_check()

        assert result["arena"] == "social_media"
        assert result["platform"] == "discord"
        assert "checked_at" in result
