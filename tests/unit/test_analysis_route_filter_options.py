"""Unit tests for get_filter_options (api/routes/analysis.py).

Tests cover:
- Valid run_id with content records: returns correct platforms and arenas lists.
- Unknown run_id (run not found, _get_run_or_raise raises): returns empty lists.
- Run owned by another user (ownership check fails): returns empty lists.
- Empty content records for valid run: returns empty platforms and arenas lists.
- Response always has both 'platforms' and 'arenas' keys.
- Multiple distinct values returned sorted as provided by the DB.

All external dependencies (_get_run_or_raise, DB session) are mocked.
No live PostgreSQL instance is required.
"""

from __future__ import annotations

import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Env bootstrap
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==")

from issue_observatory.api.routes.analysis import get_filter_options  # noqa: E402
from issue_observatory.core.models.users import User  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str = "researcher") -> User:
    """Create a minimal mock User for dependency injection."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.role = role
    user.is_active = True
    return user


def _make_db_with_results(
    platform_rows: list[str],
    arena_rows: list[str],
) -> Any:
    """Return a mock AsyncSession that returns platforms on the first execute()
    call and arenas on the second call.

    The mock simulates the two SELECT DISTINCT queries made by get_filter_options().
    """
    call_count = 0

    async def _execute(stmt: Any) -> MagicMock:
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        if call_count == 1:
            # First call: platforms
            mock.fetchall.return_value = [(p,) for p in platform_rows]
        else:
            # Second call: arenas
            mock.fetchall.return_value = [(a,) for a in arena_rows]
        return mock

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetFilterOptions:
    @pytest.mark.asyncio
    async def test_valid_run_returns_platforms_and_arenas(self) -> None:
        """With a valid run_id and content records, returns correct platform and
        arena lists."""
        run_id = uuid.uuid4()
        user = _make_user()
        db = _make_db_with_results(
            platform_rows=["bluesky", "reddit"],
            arena_rows=["social_media"],
        )

        with patch(
            "issue_observatory.api.routes.analysis._get_run_or_raise",
            new=AsyncMock(return_value=MagicMock()),
        ):
            result = await get_filter_options(run_id=run_id, db=db, current_user=user)

        assert result == {
            "platforms": ["bluesky", "reddit"],
            "arenas": ["social_media"],
        }

    @pytest.mark.asyncio
    async def test_unknown_run_id_returns_empty_lists(self) -> None:
        """When the run_id does not exist (_get_run_or_raise raises HTTPException 404),
        get_filter_options() returns {'platforms': [], 'arenas': []} instead of
        propagating the 404 error."""
        run_id = uuid.uuid4()
        user = _make_user()
        db = MagicMock()

        with patch(
            "issue_observatory.api.routes.analysis._get_run_or_raise",
            new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found")),
        ):
            result = await get_filter_options(run_id=run_id, db=db, current_user=user)

        assert result == {"platforms": [], "arenas": []}
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_ownership_failure_returns_empty_lists(self) -> None:
        """When the requesting user does not own the run (_get_run_or_raise raises
        HTTPException 403), get_filter_options() returns empty lists gracefully."""
        run_id = uuid.uuid4()
        user = _make_user()
        db = MagicMock()

        with patch(
            "issue_observatory.api.routes.analysis._get_run_or_raise",
            new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
        ):
            result = await get_filter_options(run_id=run_id, db=db, current_user=user)

        assert result == {"platforms": [], "arenas": []}

    @pytest.mark.asyncio
    async def test_empty_content_records_returns_empty_lists(self) -> None:
        """When a valid run has no content records yet, both platforms and arenas
        are empty lists."""
        run_id = uuid.uuid4()
        user = _make_user()
        db = _make_db_with_results(platform_rows=[], arena_rows=[])

        with patch(
            "issue_observatory.api.routes.analysis._get_run_or_raise",
            new=AsyncMock(return_value=MagicMock()),
        ):
            result = await get_filter_options(run_id=run_id, db=db, current_user=user)

        assert result == {"platforms": [], "arenas": []}

    @pytest.mark.asyncio
    async def test_response_always_has_platforms_and_arenas_keys(self) -> None:
        """The returned dict always has 'platforms' and 'arenas' keys regardless
        of whether the run exists."""
        run_id = uuid.uuid4()
        user = _make_user()
        db = _make_db_with_results(platform_rows=["bluesky"], arena_rows=["social_media"])

        with patch(
            "issue_observatory.api.routes.analysis._get_run_or_raise",
            new=AsyncMock(return_value=MagicMock()),
        ):
            result = await get_filter_options(run_id=run_id, db=db, current_user=user)

        assert "platforms" in result
        assert "arenas" in result

    @pytest.mark.asyncio
    async def test_multiple_platforms_returned_in_db_order(self) -> None:
        """Multiple distinct platform values are returned in the order provided by
        the database (ORDER BY is handled by SQL, not Python)."""
        run_id = uuid.uuid4()
        user = _make_user()
        db = _make_db_with_results(
            platform_rows=["bluesky", "reddit", "youtube"],
            arena_rows=["social_media", "news_media"],
        )

        with patch(
            "issue_observatory.api.routes.analysis._get_run_or_raise",
            new=AsyncMock(return_value=MagicMock()),
        ):
            result = await get_filter_options(run_id=run_id, db=db, current_user=user)

        assert result["platforms"] == ["bluesky", "reddit", "youtube"]
        assert result["arenas"] == ["social_media", "news_media"]

    @pytest.mark.asyncio
    async def test_null_platform_values_excluded_from_result(self) -> None:
        """None values returned by the DB for platform or arena are excluded from
        the result lists (SQL NULL filtering)."""
        run_id = uuid.uuid4()
        user = _make_user()

        # Simulate DB returning one None row mixed in with real rows
        call_count = 0

        async def _execute(stmt: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            if call_count == 1:
                mock.fetchall.return_value = [("bluesky",), (None,), ("reddit",)]
            else:
                mock.fetchall.return_value = [(None,), ("social_media",)]
            return mock

        db = MagicMock()
        db.execute = AsyncMock(side_effect=_execute)

        with patch(
            "issue_observatory.api.routes.analysis._get_run_or_raise",
            new=AsyncMock(return_value=MagicMock()),
        ):
            result = await get_filter_options(run_id=run_id, db=db, current_user=user)

        assert None not in result["platforms"]
        assert None not in result["arenas"]
        assert "bluesky" in result["platforms"]
        assert "reddit" in result["platforms"]
        assert "social_media" in result["arenas"]

    @pytest.mark.asyncio
    async def test_two_db_execute_calls_made_for_valid_run(self) -> None:
        """get_filter_options() makes exactly two DB execute() calls for a valid run
        — one for distinct platforms, one for distinct arenas."""
        run_id = uuid.uuid4()
        user = _make_user()
        db = _make_db_with_results(platform_rows=["bluesky"], arena_rows=["social_media"])

        with patch(
            "issue_observatory.api.routes.analysis._get_run_or_raise",
            new=AsyncMock(return_value=MagicMock()),
        ):
            await get_filter_options(run_id=run_id, db=db, current_user=user)

        assert db.execute.call_count == 2
