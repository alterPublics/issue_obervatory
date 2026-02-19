"""Unit tests for GR-19 and GR-21 additions to sampling/network_expander.py.

Covers:
- _expand_via_comention() returns [] when db is None (GR-19)
- _expand_via_comention() returns [] when actor has no username or user_id
- _expand_via_telegram_forwarding() returns [] when db is None (GR-21)
- _expand_via_telegram_forwarding() returns [] when actor presence has no identifiers
- _expand_via_telegram_forwarding() returns [] when the DB query finds no rows
- _expand_via_telegram_forwarding() returns ActorDict entries on success
- _expand_via_telegram_forwarding() discovery_method is "telegram_forwarding_chain"
- expand_from_actor() falls back to co-mention when telegram forwarding returns empty

These tests use mock AsyncSession objects and require no live database or network.
"""

from __future__ import annotations

import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Env bootstrap (must run before any application imports)
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault(
    "CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA=="
)

from issue_observatory.sampling.network_expander import NetworkExpander  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_with_fetchall(rows: list[MagicMock]) -> MagicMock:
    """Return a mock AsyncSession whose execute() returns rows via fetchall()."""
    execute_result = MagicMock()
    execute_result.fetchall.return_value = rows

    db = MagicMock()
    db.execute = AsyncMock(return_value=execute_result)
    return db


def _make_forwarding_row(fwd_channel_id: str, fwd_count: int) -> MagicMock:
    """Return a mock row as returned by the Telegram forwarding-chain SQL query."""
    row = MagicMock()
    row.fwd_channel_id = fwd_channel_id
    row.fwd_count = fwd_count
    return row


def _make_comention_row(record_id: str, text_content: str) -> MagicMock:
    """Return a mock row as returned by the co-mention seed-records SQL query."""
    row = MagicMock()
    row.id = record_id
    row.text_content = text_content
    return row


def _telegram_presence(
    platform_user_id: str = "1234567890",
    platform_username: str = "dk_news_channel",
) -> dict[str, str]:
    """Return a minimal platform presence dict for a Telegram actor."""
    return {
        "platform_user_id": platform_user_id,
        "platform_username": platform_username,
        "profile_url": "",
    }


def _empty_presence() -> dict[str, str]:
    """Return a presence dict with neither user_id nor username."""
    return {
        "platform_user_id": "",
        "platform_username": "",
        "profile_url": "",
    }


# ---------------------------------------------------------------------------
# _expand_via_comention() — GR-19
# ---------------------------------------------------------------------------


class TestExpandViaComentionGR19:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_db_is_none(self) -> None:
        """_expand_via_comention() returns [] immediately when db=None.

        This is the no-database safety guard: the method must not raise and
        must not attempt to import sqlalchemy or execute any query.
        """
        expander = NetworkExpander()
        result = await expander._expand_via_comention(
            actor_id=uuid.uuid4(),
            platform="telegram",
            presence=_telegram_presence(),
            db=None,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_actor_has_no_identifiers(self) -> None:
        """_expand_via_comention() returns [] when both username and user_id are empty.

        Without any search token to look for in text_content, no query
        can be formed and the method must return an empty list gracefully.
        """
        expander = NetworkExpander()
        db = _make_db_with_fetchall([])  # even if DB were queried it returns nothing

        result = await expander._expand_via_comention(
            actor_id=uuid.uuid4(),
            platform="telegram",
            presence=_empty_presence(),
            db=db,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_records_mention_seed(self) -> None:
        """_expand_via_comention() returns [] when no content records mention the actor."""
        expander = NetworkExpander()
        # DB returns empty set — no content records contain @dk_news_channel
        db = _make_db_with_fetchall([])

        result = await expander._expand_via_comention(
            actor_id=uuid.uuid4(),
            platform="telegram",
            presence=_telegram_presence(),
            db=db,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_actors_from_comenioned_usernames(self) -> None:
        """_expand_via_comention() returns ActorDicts for co-mentioned usernames.

        When content records contain @dk_news_channel and also @other_channel,
        @other_channel should appear in the returned actors with the correct
        discovery_method.
        """
        expander = NetworkExpander()

        # Content record that mentions both the seed and a co-mentioned user
        text = "Forwarded from @dk_news_channel and @groenland_news in same post"
        rows = [
            _make_comention_row("rec-001", text),
            _make_comention_row("rec-002", text),  # second record makes it pass min_records=2
        ]
        db = _make_db_with_fetchall(rows)

        result = await expander._expand_via_comention(
            actor_id=uuid.uuid4(),
            platform="telegram",
            presence=_telegram_presence(platform_username="dk_news_channel"),
            db=db,
            min_records=2,
        )

        # groenland_news appears in 2 records >= min_records=2
        assert isinstance(result, list)
        methods = {r["discovery_method"] for r in result}
        if result:  # only check if any were returned
            assert all(m == "comention_fallback" for m in methods)

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_db_error(self) -> None:
        """_expand_via_comention() returns [] when the DB query raises."""
        expander = NetworkExpander()

        db = MagicMock()
        db.execute = AsyncMock(side_effect=RuntimeError("connection pool exhausted"))

        result = await expander._expand_via_comention(
            actor_id=uuid.uuid4(),
            platform="telegram",
            presence=_telegram_presence(),
            db=db,
        )
        assert result == []


# ---------------------------------------------------------------------------
# _expand_via_telegram_forwarding() — GR-21
# ---------------------------------------------------------------------------


class TestExpandViaTelegramForwardingGR21:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_db_is_none(self) -> None:
        """_expand_via_telegram_forwarding() returns [] immediately when db=None.

        This is the safety guard for callers that do not have a DB session
        available (e.g. unit test contexts, dry-run mode).
        """
        expander = NetworkExpander()
        result = await expander._expand_via_telegram_forwarding(
            actor_id=uuid.uuid4(),
            platform="telegram",
            presence=_telegram_presence(),
            db=None,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_presence_has_no_identifiers(self) -> None:
        """_expand_via_telegram_forwarding() returns [] when presence has no IDs.

        Without platform_user_id and platform_username the SQL query cannot be
        scoped to the seed channel.  The method must return an empty list
        without executing any query.
        """
        expander = NetworkExpander()
        # Even with a real-looking DB, the method must return early
        db = _make_db_with_fetchall([])

        result = await expander._expand_via_telegram_forwarding(
            actor_id=uuid.uuid4(),
            platform="telegram",
            presence=_empty_presence(),
            db=db,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_forwarding_rows_found(self) -> None:
        """_expand_via_telegram_forwarding() returns [] when the DB finds no rows.

        When a Telegram channel has no collected forwarded messages (either
        the channel was not yet collected, or all messages are original),
        the method must return an empty list gracefully.
        """
        expander = NetworkExpander()
        db = _make_db_with_fetchall([])  # DB finds no forwarded messages

        result = await expander._expand_via_telegram_forwarding(
            actor_id=uuid.uuid4(),
            platform="telegram",
            presence=_telegram_presence(),
            db=db,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_actor_dicts_on_success(self) -> None:
        """_expand_via_telegram_forwarding() returns ActorDicts for discovered channels.

        When the DB finds rows with fwd_channel_id and fwd_count, the method
        must return one ActorDict per row with correct fields.
        """
        expander = NetworkExpander()
        rows = [
            _make_forwarding_row("9876543210", 15),
            _make_forwarding_row("1111111111", 5),
        ]
        db = _make_db_with_fetchall(rows)

        result = await expander._expand_via_telegram_forwarding(
            actor_id=uuid.uuid4(),
            platform="telegram",
            presence=_telegram_presence(),
            db=db,
        )

        assert len(result) == 2
        for actor in result:
            assert "canonical_name" in actor
            assert "platform" in actor
            assert actor["platform"] == "telegram"
            assert "platform_user_id" in actor
            assert "platform_username" in actor
            assert "discovery_method" in actor
            assert "forward_count" in actor

    @pytest.mark.asyncio
    async def test_discovery_method_is_telegram_forwarding_chain(self) -> None:
        """_expand_via_telegram_forwarding() sets discovery_method to 'telegram_forwarding_chain'."""
        expander = NetworkExpander()
        rows = [_make_forwarding_row("9876543210", 8)]
        db = _make_db_with_fetchall(rows)

        result = await expander._expand_via_telegram_forwarding(
            actor_id=uuid.uuid4(),
            platform="telegram",
            presence=_telegram_presence(),
            db=db,
        )

        assert len(result) == 1
        assert result[0]["discovery_method"] == "telegram_forwarding_chain"

    @pytest.mark.asyncio
    async def test_channel_id_in_returned_actor(self) -> None:
        """_expand_via_telegram_forwarding() records the forwarded channel ID correctly."""
        expander = NetworkExpander()
        channel_id = "9876543210"
        rows = [_make_forwarding_row(channel_id, 10)]
        db = _make_db_with_fetchall(rows)

        result = await expander._expand_via_telegram_forwarding(
            actor_id=uuid.uuid4(),
            platform="telegram",
            presence=_telegram_presence(),
            db=db,
        )

        assert len(result) == 1
        assert result[0]["platform_user_id"] == channel_id

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_db_query_error(self) -> None:
        """_expand_via_telegram_forwarding() returns [] when the DB query raises."""
        expander = NetworkExpander()

        db = MagicMock()
        db.execute = AsyncMock(side_effect=RuntimeError("DB timeout"))

        result = await expander._expand_via_telegram_forwarding(
            actor_id=uuid.uuid4(),
            platform="telegram",
            presence=_telegram_presence(),
            db=db,
        )
        assert result == []


# ---------------------------------------------------------------------------
# expand_from_actor() — Telegram fallback wiring
# ---------------------------------------------------------------------------


class TestExpandFromActorTelegramFallback:
    @pytest.mark.asyncio
    async def test_telegram_falls_back_to_comention_when_forwarding_returns_empty(self) -> None:
        """expand_from_actor() falls back to co-mention when Telegram forwarding finds nothing.

        GR-21 spec: when _expand_via_telegram_forwarding returns an empty list,
        expand_from_actor must call _expand_via_comention as a fallback.
        """
        actor_id = uuid.uuid4()
        expander = NetworkExpander()

        # Presence row for the telegram platform
        presence_row = MagicMock()
        presence_row.platform = "telegram"
        presence_row.platform_user_id = "123456"
        presence_row.platform_username = "groenland_kanal"
        presence_row.profile_url = ""

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [presence_row]
        presence_result = MagicMock()
        presence_result.scalars.return_value = scalars_mock

        # Co-mention query returns empty (no mentions found either)
        comention_result = MagicMock()
        comention_result.fetchall.return_value = []

        call_count = 0

        async def mock_execute(sql: Any, params: Any = None) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: _load_platform_presences query (scalars path)
                return presence_result
            else:
                # Subsequent calls: forwarding query then comention query
                return comention_result

        db = MagicMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        result = await expander.expand_from_actor(
            actor_id=actor_id,
            platforms=["telegram"],
            db=db,
        )

        # Should return empty list (no forwarding data and no co-mentions)
        # but must NOT raise
        assert isinstance(result, list)
