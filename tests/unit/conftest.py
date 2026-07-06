"""Unit test conftest — overrides session-scoped DB fixtures for tests that
don't need a live database connection.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Provide a dummy URL so that fixtures depending on this don't fail.

    Unit tests in this directory should not hit the database; they test pure
    functions directly.
    """
    return "postgresql+asyncpg://localhost/unused"


@pytest.fixture(scope="session", autouse=True)
def _ensure_tables(test_database_url: str) -> None:  # noqa: ARG001
    """No-op override — unit tests don't need real tables."""
    return
