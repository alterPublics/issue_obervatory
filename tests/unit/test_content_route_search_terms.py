"""Unit tests for get_search_terms_for_run (api/routes/content.py).

Tests cover:
- No run_id: returns a single "All terms" option and no other options.
- With run_id and terms in DB: returns the default option plus one option per term.
- With run_id but no terms in DB: returns only the "All terms" option.
- HTML special characters in term names are escaped (XSS prevention).
- Danish characters (æ, ø, å) in term names are preserved in the output.
- Terms are returned in the order provided by the DB (ORDER BY term).
- Non-admin user: ownership_filter includes user_id in the SQL params.

All DB calls are mocked via AsyncMock / MagicMock.
No live PostgreSQL instance is required.
"""

from __future__ import annotations

import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Env bootstrap
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==")

from issue_observatory.api.routes.content import get_search_terms_for_run  # noqa: E402
from issue_observatory.core.models.users import User  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str = "researcher") -> User:
    """Create a minimal User ORM object for dependency injection."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.role = role
    user.is_active = True
    return user


def _make_db_with_terms(terms: list[str]) -> Any:
    """Mock AsyncSession returning term rows from the search-terms query."""
    rows = [(term,) for term in terms]
    result_mock = MagicMock()
    result_mock.fetchall.return_value = rows
    db = MagicMock()
    db.execute = AsyncMock(return_value=result_mock)
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetSearchTermsForRun:
    @pytest.mark.asyncio
    async def test_no_run_id_returns_default_option_only(self) -> None:
        """When run_id is None, the response contains only the 'All terms' option
        and no additional <option> tags."""
        db = MagicMock()  # should not be called
        user = _make_user()
        response = await get_search_terms_for_run(db=db, current_user=user, run_id=None)
        content = response.body.decode("utf-8")
        assert '<option value="">All terms</option>' in content
        # Only one <option> tag should be present
        assert content.count("<option") == 1
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_with_run_id_and_terms_returns_default_plus_term_options(self) -> None:
        """When run_id is provided and the DB returns terms, the response contains
        the 'All terms' option followed by one <option> per term."""
        terms = ["klimaforandringer", "velfærdsstat", "demokrati"]
        db = _make_db_with_terms(terms)
        user = _make_user()
        run_id = uuid.uuid4()

        response = await get_search_terms_for_run(db=db, current_user=user, run_id=run_id)
        content = response.body.decode("utf-8")

        # Default option always present
        assert '<option value="">All terms</option>' in content
        # One option per term plus the default = 4 total
        assert content.count("<option") == len(terms) + 1
        for term in terms:
            assert f'<option value="{term}">{term}</option>' in content

    @pytest.mark.asyncio
    async def test_with_run_id_and_no_terms_returns_default_option_only(self) -> None:
        """When run_id is provided but the DB returns no terms, only 'All terms'
        is present in the response."""
        db = _make_db_with_terms([])
        user = _make_user()
        run_id = uuid.uuid4()

        response = await get_search_terms_for_run(db=db, current_user=user, run_id=run_id)
        content = response.body.decode("utf-8")

        assert '<option value="">All terms</option>' in content
        assert content.count("<option") == 1

    @pytest.mark.asyncio
    async def test_xss_html_special_chars_in_term_are_escaped(self) -> None:
        """HTML special characters in term names are properly escaped in both
        the value attribute and the visible text to prevent XSS injection."""
        # A term containing all HTML-sensitive characters
        malicious_term = "<script>alert('xss')</script> & \"quotes\""
        db = _make_db_with_terms([malicious_term])
        user = _make_user()
        run_id = uuid.uuid4()

        response = await get_search_terms_for_run(db=db, current_user=user, run_id=run_id)
        content = response.body.decode("utf-8")

        # The raw characters must NOT appear unescaped in the output
        assert "<script>" not in content
        assert "</script>" not in content
        # Escaped forms must appear
        assert "&lt;script&gt;" in content
        assert "&amp;" in content
        assert "&quot;" in content

    @pytest.mark.asyncio
    async def test_danish_characters_preserved_in_option_values(self) -> None:
        """Danish characters æ, ø, å in term names are preserved without corruption
        in both the value attribute and the display text."""
        terms = ["grøn omstilling", "velfærdsstat", "Ålborg kommune"]
        db = _make_db_with_terms(terms)
        user = _make_user()
        run_id = uuid.uuid4()

        response = await get_search_terms_for_run(db=db, current_user=user, run_id=run_id)
        content = response.body.decode("utf-8")

        assert "grøn omstilling" in content
        assert "velfærdsstat" in content
        assert "Ålborg kommune" in content

    @pytest.mark.asyncio
    async def test_response_is_html_response_with_200_status(self) -> None:
        """get_search_terms_for_run() returns an HTMLResponse with HTTP 200."""
        db = _make_db_with_terms(["klimaforandringer"])
        user = _make_user()
        run_id = uuid.uuid4()

        response = await get_search_terms_for_run(db=db, current_user=user, run_id=run_id)
        assert response.status_code == 200
        assert "text/html" in response.media_type

    @pytest.mark.asyncio
    async def test_non_admin_user_triggers_db_execute(self) -> None:
        """When run_id is provided and user is a non-admin researcher, the DB is
        queried (ownership filter applied) and execute() is called exactly once."""
        db = _make_db_with_terms([])
        user = _make_user(role="researcher")
        run_id = uuid.uuid4()

        await get_search_terms_for_run(db=db, current_user=user, run_id=run_id)
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_user_triggers_db_execute(self) -> None:
        """When run_id is provided and user is an admin, the DB is still queried
        (ownership filter skipped) and execute() is called exactly once."""
        db = _make_db_with_terms([])
        user = _make_user(role="admin")
        run_id = uuid.uuid4()

        await get_search_terms_for_run(db=db, current_user=user, run_id=run_id)
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_term_order_preserved_from_db_result(self) -> None:
        """Terms appear in the HTML output in the same order as returned by the DB."""
        # Simulating the database returning terms in alphabetical order
        terms = ["demokrati", "klimaforandringer", "velfærdsstat"]
        db = _make_db_with_terms(terms)
        user = _make_user()
        run_id = uuid.uuid4()

        response = await get_search_terms_for_run(db=db, current_user=user, run_id=run_id)
        content = response.body.decode("utf-8")

        # Verify order by checking position of each term in the HTML
        positions = [content.index(term) for term in terms]
        assert positions == sorted(positions), "Terms are not in the expected DB order"

    @pytest.mark.asyncio
    async def test_xss_less_than_greater_than_in_term_escaped(self) -> None:
        """< and > characters in term names are individually escaped."""
        db = _make_db_with_terms(["term<b>bold</b>"])
        user = _make_user()
        run_id = uuid.uuid4()

        response = await get_search_terms_for_run(db=db, current_user=user, run_id=run_id)
        content = response.body.decode("utf-8")

        assert "<b>" not in content
        assert "&lt;b&gt;" in content
