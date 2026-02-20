"""Unit tests for workers/_task_helpers.py — async DB helpers for orchestration tasks.

Covers YF-01 per-arena search term filtering logic.

The ``fetch_search_terms_for_arena()`` function opens its own async session
via ``AsyncSessionLocal``, so we patch that context manager to inject the
test session (which is rolled back after each test by conftest).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.core.models.query_design import QueryDesign, SearchTerm
from issue_observatory.workers._task_helpers import fetch_search_terms_for_arena


@asynccontextmanager
async def _mock_session_factory(session: AsyncSession):
    """Return a context manager that yields the given session (no-op close)."""

    async def _factory():
        """Yield session without closing it (test fixture handles lifecycle)."""
        yield session

    return _factory


@pytest_asyncio.fixture
async def sample_design(db_session: AsyncSession, test_user):
    """Create a query design owned by test_user with no terms."""
    design = QueryDesign(
        owner_id=test_user.id,
        name="YF-01 Test Design",
        is_active=True,
        default_tier="free",
        language="da",
        locale_country="dk",
    )
    db_session.add(design)
    await db_session.flush()
    await db_session.refresh(design)
    return design


def _patch_session(db_session: AsyncSession):
    """Return a patch context that makes AsyncSessionLocal yield db_session."""

    @asynccontextmanager
    async def _fake_session_local():
        yield db_session

    return patch(
        "issue_observatory.workers._task_helpers.AsyncSessionLocal",
        _fake_session_local,
    )


@pytest.mark.asyncio
async def test_null_target_arenas_includes_all(db_session, sample_design):
    """Terms with target_arenas=NULL are returned for any arena."""
    term = SearchTerm(
        query_design_id=sample_design.id,
        term="klimakrise",
        term_type="keyword",
        target_arenas=None,
        is_active=True,
    )
    db_session.add(term)
    await db_session.flush()

    with _patch_session(db_session):
        assert await fetch_search_terms_for_arena(sample_design.id, "reddit") == [
            "klimakrise"
        ]
        assert await fetch_search_terms_for_arena(sample_design.id, "youtube") == [
            "klimakrise"
        ]
        assert await fetch_search_terms_for_arena(sample_design.id, "bluesky") == [
            "klimakrise"
        ]


@pytest.mark.asyncio
async def test_scoped_includes_only_specified(db_session, sample_design):
    """Terms with target_arenas=["reddit"] only returned for reddit."""
    db_session.add_all(
        [
            SearchTerm(
                query_design_id=sample_design.id,
                term="r/Denmark",
                term_type="keyword",
                target_arenas=["reddit"],
                is_active=True,
            ),
            SearchTerm(
                query_design_id=sample_design.id,
                term="video_term",
                term_type="hashtag",
                target_arenas=["youtube", "bluesky"],
                is_active=True,
            ),
        ]
    )
    await db_session.flush()

    with _patch_session(db_session):
        reddit = await fetch_search_terms_for_arena(sample_design.id, "reddit")
        assert "r/Denmark" in reddit
        assert "video_term" not in reddit

        youtube = await fetch_search_terms_for_arena(sample_design.id, "youtube")
        assert "video_term" in youtube
        assert "r/Denmark" not in youtube

        bluesky = await fetch_search_terms_for_arena(sample_design.id, "bluesky")
        assert "video_term" in bluesky
        assert "r/Denmark" not in bluesky


@pytest.mark.asyncio
async def test_excludes_inactive(db_session, sample_design):
    """Inactive terms never returned regardless of target_arenas."""
    db_session.add_all(
        [
            SearchTerm(
                query_design_id=sample_design.id,
                term="active_term",
                term_type="keyword",
                target_arenas=None,
                is_active=True,
            ),
            SearchTerm(
                query_design_id=sample_design.id,
                term="inactive_term",
                term_type="keyword",
                target_arenas=None,
                is_active=False,
            ),
        ]
    )
    await db_session.flush()

    with _patch_session(db_session):
        terms = await fetch_search_terms_for_arena(sample_design.id, "reddit")
        assert "active_term" in terms
        assert "inactive_term" not in terms


@pytest.mark.asyncio
async def test_returns_empty_for_no_match(db_session, sample_design):
    """Returns empty list when no terms match the arena."""
    db_session.add(
        SearchTerm(
            query_design_id=sample_design.id,
            term="reddit_only",
            term_type="keyword",
            target_arenas=["reddit"],
            is_active=True,
        )
    )
    await db_session.flush()

    with _patch_session(db_session):
        assert await fetch_search_terms_for_arena(sample_design.id, "youtube") == []


@pytest.mark.asyncio
async def test_mixed_scoping(db_session, sample_design):
    """Returns correct terms when design has mix of scoped and unscoped terms."""
    db_session.add_all(
        [
            SearchTerm(
                query_design_id=sample_design.id,
                term="universal",
                term_type="keyword",
                target_arenas=None,
                is_active=True,
            ),
            SearchTerm(
                query_design_id=sample_design.id,
                term="reddit_specific",
                term_type="keyword",
                target_arenas=["reddit"],
                is_active=True,
            ),
            SearchTerm(
                query_design_id=sample_design.id,
                term="video_term",
                term_type="keyword",
                target_arenas=["youtube", "bluesky"],
                is_active=True,
            ),
        ]
    )
    await db_session.flush()

    with _patch_session(db_session):
        reddit = await fetch_search_terms_for_arena(sample_design.id, "reddit")
        assert set(reddit) == {"universal", "reddit_specific"}

        youtube = await fetch_search_terms_for_arena(sample_design.id, "youtube")
        assert set(youtube) == {"universal", "video_term"}

        tiktok = await fetch_search_terms_for_arena(sample_design.id, "tiktok")
        assert tiktok == ["universal"]


@pytest.mark.asyncio
async def test_preserves_insertion_order(db_session, sample_design):
    """Returns terms in added_at order (stable sort for reproducibility)."""
    db_session.add_all(
        [
            SearchTerm(
                query_design_id=sample_design.id,
                term="first",
                term_type="keyword",
                target_arenas=None,
                is_active=True,
                added_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            ),
            SearchTerm(
                query_design_id=sample_design.id,
                term="second",
                term_type="keyword",
                target_arenas=None,
                is_active=True,
                added_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
            ),
            SearchTerm(
                query_design_id=sample_design.id,
                term="third",
                term_type="keyword",
                target_arenas=None,
                is_active=True,
                added_at=datetime(2024, 1, 3, tzinfo=timezone.utc),
            ),
        ]
    )
    await db_session.flush()

    with _patch_session(db_session):
        terms = await fetch_search_terms_for_arena(sample_design.id, "reddit")
        assert terms == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_empty_design(db_session, sample_design):
    """Returns empty list for query design with no terms."""
    with _patch_session(db_session):
        terms = await fetch_search_terms_for_arena(sample_design.id, "reddit")
        assert terms == []


@pytest.mark.asyncio
async def test_nonexistent_design(db_session):
    """Returns empty list for nonexistent query design UUID."""
    fake_id = uuid.uuid4()
    with _patch_session(db_session):
        terms = await fetch_search_terms_for_arena(fake_id, "reddit")
        assert terms == []
