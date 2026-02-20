"""Unit tests for GET /api/arenas/ endpoint (api/routes/arenas.py).

Tests cover:
- Returns all arenas from list_arenas() with correct fields.
- has_credentials is True for platforms that have an active credential.
- has_credentials is False for platforms with no active credential.
- Empty registry produces an empty list response.
- Each ArenaInfo item has the required field set.

All external dependencies (DB session, autodiscover, list_arenas, DB query)
are mocked.  No live database or network connection is required.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Env bootstrap — must happen before any application module imports.
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test_observatory")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from issue_observatory.api.routes.arenas import list_available_arenas  # noqa: E402

# ---------------------------------------------------------------------------
# Sample arena registry data returned by the mocked list_arenas()
# ---------------------------------------------------------------------------

_SAMPLE_ARENAS: list[dict[str, Any]] = [
    {
        "arena_name": "social_media",
        "platform_name": "bluesky",
        "supported_tiers": ["free"],
        "description": "Decentralised social network",
        "collector_class": "issue_observatory.arenas.bluesky.collector.BlueskyCollector",
        "custom_config_fields": None,
        "temporal_mode": "recent",
    },
    {
        "arena_name": "social_media",
        "platform_name": "reddit",
        "supported_tiers": ["free", "medium"],
        "description": "Reddit posts from Danish subreddits",
        "collector_class": "issue_observatory.arenas.reddit.collector.RedditCollector",
        "custom_config_fields": [
            {
                "field": "custom_subreddits",
                "label": "Custom Subreddits",
                "type": "list",
                "placeholder": "SubredditName",
                "help": "Additional subreddits beyond default Danish ones",
                "example": "dkfinance",
            }
        ],
        "temporal_mode": "recent",
    },
    {
        "arena_name": "news_media",
        "platform_name": "rss_feeds",
        "supported_tiers": ["free"],
        "description": "Danish RSS feeds",
        "collector_class": "issue_observatory.arenas.rss_feeds.collector.RssFeedsCollector",
        "custom_config_fields": [
            {
                "field": "custom_feeds",
                "label": "Custom RSS Feeds",
                "type": "list",
                "placeholder": "https://example.com/feed.xml",
                "help": "Additional RSS/Atom feeds",
                "example": "https://sermitsiaq.ag/rss",
            }
        ],
        "temporal_mode": "forward_only",
    },
]


def _make_db(platform_names_with_credentials: set[str]) -> Any:
    """Return a mock AsyncSession whose execute() simulates the credential query.

    The credential query returns rows of the form ``(platform_name,)`` for
    every platform that has at least one active credential.
    """
    rows = [(platform,) for platform in platform_names_with_credentials]
    result_mock = MagicMock()
    result_mock.fetchall.return_value = rows
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_mock)
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestListAvailableArenas:
    @pytest.mark.asyncio
    async def test_returns_all_arenas_from_list_arenas(self) -> None:
        """list_available_arenas() returns one ArenaInfo entry per entry in
        list_arenas()."""
        db = _make_db({"bluesky"})

        with patch(
            "issue_observatory.api.routes.arenas.autodiscover"
        ) as mock_autodiscover, patch(
            "issue_observatory.api.routes.arenas.list_arenas",
            return_value=_SAMPLE_ARENAS,
        ):
            result = await list_available_arenas(db=db)

        mock_autodiscover.assert_called_once()
        assert len(result) == len(_SAMPLE_ARENAS)

    @pytest.mark.asyncio
    async def test_each_arena_has_required_fields(self) -> None:
        """Each returned ArenaInfo object has all five required attributes."""
        db = _make_db(set())

        with patch("issue_observatory.api.routes.arenas.autodiscover"), patch(
            "issue_observatory.api.routes.arenas.list_arenas",
            return_value=_SAMPLE_ARENAS[:1],
        ):
            result = await list_available_arenas(db=db)

        arena = result[0]
        assert hasattr(arena, "arena_name")
        assert hasattr(arena, "platform_name")
        assert hasattr(arena, "supported_tiers")
        assert hasattr(arena, "description")
        assert hasattr(arena, "has_credentials")

    @pytest.mark.asyncio
    async def test_has_credentials_true_for_platform_with_active_credential(self) -> None:
        """has_credentials is True when the DB reports the platform as credentialed."""
        # Only bluesky has an active credential; reddit does not.
        db = _make_db({"bluesky"})

        with patch("issue_observatory.api.routes.arenas.autodiscover"), patch(
            "issue_observatory.api.routes.arenas.list_arenas",
            return_value=_SAMPLE_ARENAS[:2],  # bluesky + reddit
        ):
            result = await list_available_arenas(db=db)

        by_platform = {a.platform_name: a for a in result}
        assert by_platform["bluesky"].has_credentials is True
        assert by_platform["reddit"].has_credentials is False

    @pytest.mark.asyncio
    async def test_has_credentials_false_when_no_credentials_in_db(self) -> None:
        """has_credentials is False for all arenas when the credential table is empty."""
        db = _make_db(set())

        with patch("issue_observatory.api.routes.arenas.autodiscover"), patch(
            "issue_observatory.api.routes.arenas.list_arenas",
            return_value=_SAMPLE_ARENAS,
        ):
            result = await list_available_arenas(db=db)

        assert all(a.has_credentials is False for a in result)

    @pytest.mark.asyncio
    async def test_empty_registry_returns_empty_list(self) -> None:
        """When list_arenas() returns [], list_available_arenas() returns []."""
        db = _make_db(set())

        with patch("issue_observatory.api.routes.arenas.autodiscover"), patch(
            "issue_observatory.api.routes.arenas.list_arenas", return_value=[]
        ):
            result = await list_available_arenas(db=db)

        assert result == []

    @pytest.mark.asyncio
    async def test_supported_tiers_list_preserved(self) -> None:
        """supported_tiers from list_arenas() are included unchanged in the result."""
        db = _make_db(set())

        with patch("issue_observatory.api.routes.arenas.autodiscover"), patch(
            "issue_observatory.api.routes.arenas.list_arenas",
            return_value=[_SAMPLE_ARENAS[1]],  # reddit: ["free", "medium"]
        ):
            result = await list_available_arenas(db=db)

        assert result[0].supported_tiers == ["free", "medium"]

    @pytest.mark.asyncio
    async def test_arena_name_and_platform_name_correct(self) -> None:
        """arena_name and platform_name are correctly passed through from list_arenas()."""
        db = _make_db(set())

        with patch("issue_observatory.api.routes.arenas.autodiscover"), patch(
            "issue_observatory.api.routes.arenas.list_arenas",
            return_value=[_SAMPLE_ARENAS[0]],  # bluesky
        ):
            result = await list_available_arenas(db=db)

        assert result[0].arena_name == "social_media"
        assert result[0].platform_name == "bluesky"

    @pytest.mark.asyncio
    async def test_description_passed_through_from_registry(self) -> None:
        """Arena description from list_arenas() is included in the ArenaInfo result."""
        db = _make_db(set())

        with patch("issue_observatory.api.routes.arenas.autodiscover"), patch(
            "issue_observatory.api.routes.arenas.list_arenas",
            return_value=[_SAMPLE_ARENAS[0]],  # bluesky
        ):
            result = await list_available_arenas(db=db)

        assert result[0].description == "Decentralised social network"

    @pytest.mark.asyncio
    async def test_autodiscover_called_exactly_once(self) -> None:
        """autodiscover() is called exactly once per request to ensure all
        @register decorators have fired before list_arenas() is called."""
        db = _make_db(set())

        with patch(
            "issue_observatory.api.routes.arenas.autodiscover"
        ) as mock_autodiscover, patch(
            "issue_observatory.api.routes.arenas.list_arenas", return_value=[]
        ):
            await list_available_arenas(db=db)

        mock_autodiscover.assert_called_once()

    @pytest.mark.asyncio
    async def test_custom_config_fields_present_when_available(self) -> None:
        """custom_config_fields are included when the arena has them (YF-02)."""
        db = _make_db(set())

        with patch("issue_observatory.api.routes.arenas.autodiscover"), patch(
            "issue_observatory.api.routes.arenas.list_arenas",
            return_value=[_SAMPLE_ARENAS[1]],  # reddit with custom_config_fields
        ):
            result = await list_available_arenas(db=db)

        assert result[0].custom_config_fields is not None
        assert len(result[0].custom_config_fields) == 1
        assert result[0].custom_config_fields[0].field == "custom_subreddits"
        assert result[0].custom_config_fields[0].type == "list"

    @pytest.mark.asyncio
    async def test_custom_config_fields_none_when_not_required(self) -> None:
        """custom_config_fields is None for arenas that don't require configuration (YF-02)."""
        db = _make_db(set())

        with patch("issue_observatory.api.routes.arenas.autodiscover"), patch(
            "issue_observatory.api.routes.arenas.list_arenas",
            return_value=[_SAMPLE_ARENAS[0]],  # bluesky without custom_config_fields
        ):
            result = await list_available_arenas(db=db)

        assert result[0].custom_config_fields is None
