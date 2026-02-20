"""Integration tests for YF-03 (bulk term import) and YF-07 (bulk actor import).

Tests the POST /query-designs/{id}/terms/bulk and POST /query-designs/{id}/actors/bulk
endpoints with focus on ownership validation, data integrity, and deduplication.

Uses conftest fixtures for database sessions, users, and HTTP client.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.core.models.actors import Actor, ActorListMember
from issue_observatory.core.models.query_design import ActorList, QueryDesign, SearchTerm


# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def test_design(db_session: AsyncSession, test_user) -> QueryDesign:
    """Create a query design owned by test_user."""
    design = QueryDesign(
        owner_id=test_user.id,
        name="YF Integration Test Design",
        is_active=True,
        default_tier="free",
        language="da",
        locale_country="dk",
    )
    db_session.add(design)
    await db_session.flush()
    await db_session.refresh(design)
    return design


@pytest_asyncio.fixture
async def other_auth_headers(
    test_user_2, client: AsyncClient
) -> dict[str, str]:
    """Return auth headers for a second user (non-owner of test_design)."""
    from tests.conftest import TEST_PASSWORD  # noqa: PLC0415

    response = await client.post(
        "/auth/bearer/login",
        data={"username": test_user_2.email, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, (
        f"Login failed for {test_user_2.email!r}: {response.status_code} {response.text}"
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# YF-03: Bulk Term Import Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_add_search_terms_success(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_design: QueryDesign,
    db_session: AsyncSession,
):
    """Bulk add endpoint successfully creates multiple terms."""
    payload = [
        {"term": "klimakrise", "term_type": "keyword"},
        {"term": "grøn omstilling", "term_type": "phrase"},
        {"term": "#COP28", "term_type": "hashtag"},
    ]

    response = await client.post(
        f"/query-designs/{test_design.id}/terms/bulk",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert len(data) == 3
    assert data[0]["term"] == "klimakrise"
    assert data[1]["term"] == "grøn omstilling"
    assert data[2]["term"] == "#COP28"

    # Verify database state via the same session.
    result = await db_session.execute(
        select(SearchTerm)
        .where(SearchTerm.query_design_id == test_design.id)
        .order_by(SearchTerm.added_at)
    )
    terms = result.scalars().all()
    assert len(terms) == 3
    assert [t.term for t in terms] == ["klimakrise", "grøn omstilling", "#COP28"]


@pytest.mark.asyncio
async def test_bulk_add_search_terms_preserves_target_arenas(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_design: QueryDesign,
):
    """Bulk add correctly stores target_arenas for each term (YF-01)."""
    payload = [
        {
            "term": "subreddit_term",
            "term_type": "keyword",
            "target_arenas": ["reddit"],
        },
        {
            "term": "video_term",
            "term_type": "keyword",
            "target_arenas": ["youtube", "bluesky"],
        },
        {"term": "universal_term", "term_type": "keyword", "target_arenas": None},
    ]

    response = await client.post(
        f"/query-designs/{test_design.id}/terms/bulk",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data[0]["target_arenas"] == ["reddit"]
    assert data[1]["target_arenas"] == ["youtube", "bluesky"]
    assert data[2]["target_arenas"] is None


@pytest.mark.asyncio
async def test_bulk_add_search_terms_ownership_guard(
    client: AsyncClient,
    other_auth_headers: dict[str, str],
    test_design: QueryDesign,
    db_session: AsyncSession,
):
    """Bulk add rejects requests from non-owners."""
    payload = [{"term": "unauthorized", "term_type": "keyword"}]

    response = await client.post(
        f"/query-designs/{test_design.id}/terms/bulk",
        json=payload,
        headers=other_auth_headers,
    )

    assert response.status_code == 403

    # Verify no terms were created.
    result = await db_session.execute(
        select(SearchTerm).where(SearchTerm.query_design_id == test_design.id)
    )
    terms = result.scalars().all()
    assert len(terms) == 0


@pytest.mark.asyncio
async def test_bulk_add_search_terms_rejects_empty_payload(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_design: QueryDesign,
):
    """Bulk add returns 400 for empty payload."""
    response = await client.post(
        f"/query-designs/{test_design.id}/terms/bulk",
        json=[],
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "at least one search term" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_bulk_add_search_terms_rejects_empty_term_string(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_design: QueryDesign,
    db_session: AsyncSession,
):
    """Bulk add returns 422 when any term is empty after stripping."""
    payload = [
        {"term": "valid_term", "term_type": "keyword"},
        {"term": "   ", "term_type": "keyword"},
        {"term": "another_valid", "term_type": "keyword"},
    ]

    response = await client.post(
        f"/query-designs/{test_design.id}/terms/bulk",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert "must not be empty" in response.json()["detail"].lower()

    # Verify no terms were created (atomic failure).
    result = await db_session.execute(
        select(SearchTerm).where(SearchTerm.query_design_id == test_design.id)
    )
    terms = result.scalars().all()
    assert len(terms) == 0


@pytest.mark.asyncio
async def test_bulk_add_search_terms_with_group_labels(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_design: QueryDesign,
):
    """Bulk add correctly handles group_id and group_label (IP2-046)."""
    payload = [
        {"term": "term1", "term_type": "keyword", "group_label": "Primary terms"},
        {"term": "term2", "term_type": "keyword", "group_label": "Primary terms"},
        {"term": "term3", "term_type": "keyword", "group_label": "English variants"},
    ]

    response = await client.post(
        f"/query-designs/{test_design.id}/terms/bulk",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()

    # First two terms share the same group_id.
    assert data[0]["group_id"] == data[1]["group_id"]
    assert data[0]["group_label"] == "Primary terms"

    # Third term has a different group_id.
    assert data[2]["group_id"] != data[0]["group_id"]
    assert data[2]["group_label"] == "English variants"


@pytest.mark.asyncio
async def test_bulk_add_search_terms_rejects_invalid_arenas(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_design: QueryDesign,
):
    """Bulk add rejects terms with non-existent arena names (CRITICAL-04)."""
    payload = [
        {"term": "valid", "term_type": "keyword", "target_arenas": ["reddit"]},
        {"term": "invalid", "term_type": "keyword", "target_arenas": ["fake_arena"]},
    ]

    response = await client.post(
        f"/query-designs/{test_design.id}/terms/bulk",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert "fake_arena" in response.json()["detail"]


# ---------------------------------------------------------------------------
# YF-07: Bulk Actor Import Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_add_actors_success(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_design: QueryDesign,
    db_session: AsyncSession,
    test_user,
):
    """Bulk add actors endpoint successfully creates multiple actors."""
    payload = [
        {"name": "John Doe", "actor_type": "person"},
        {"name": "DR Nyheder", "actor_type": "media_outlet"},
        {"name": "Folkeskolen", "actor_type": "organization"},
    ]

    response = await client.post(
        f"/query-designs/{test_design.id}/actors/bulk",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["total"] == 3
    assert len(data["added"]) == 3
    assert len(data["skipped"]) == 0
    assert "John Doe" in data["added"]
    assert "DR Nyheder" in data["added"]

    # Verify canonical Actor records were created.
    result = await db_session.execute(
        select(Actor).where(Actor.created_by == test_user.id)
    )
    actors = result.scalars().all()
    assert len(actors) == 3


@pytest.mark.asyncio
async def test_bulk_add_actors_deduplicates_case_insensitive(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_design: QueryDesign,
    db_session: AsyncSession,
    test_user,
):
    """Multiple entries with same name (different case) create only 1 actor."""
    payload = [
        {"name": "John Doe", "actor_type": "person"},
        {"name": "john doe", "actor_type": "person"},
        {"name": "JOHN DOE", "actor_type": "person"},
    ]

    response = await client.post(
        f"/query-designs/{test_design.id}/actors/bulk",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["total"] == 3

    # Only the first occurrence should be in "added".
    assert len(data["added"]) == 1
    assert "John Doe" in data["added"]

    # The other two should be in "skipped" (already in list after first add).
    assert len(data["skipped"]) == 2

    # Verify only 1 canonical Actor record was created.
    result = await db_session.execute(
        select(Actor).where(Actor.created_by == test_user.id)
    )
    actors = result.scalars().all()
    assert len(actors) == 1
    assert actors[0].canonical_name == "John Doe"


@pytest.mark.asyncio
async def test_bulk_add_actors_skips_existing_members(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_design: QueryDesign,
    db_session: AsyncSession,
    test_user,
):
    """Actors already in the list are skipped, not duplicated."""
    # Pre-add an actor to the list via db_session.
    actor = Actor(
        canonical_name="Jane Smith",
        actor_type="person",
        created_by=test_user.id,
        is_shared=False,
    )
    db_session.add(actor)
    await db_session.flush()

    actor_list = ActorList(
        query_design_id=test_design.id,
        name="Default",
        created_by=test_user.id,
        sampling_method="manual",
    )
    db_session.add(actor_list)
    await db_session.flush()

    member = ActorListMember(
        actor_list_id=actor_list.id,
        actor_id=actor.id,
        added_by="manual",
    )
    db_session.add(member)
    await db_session.flush()

    # Attempt to bulk-add: one existing actor + one new actor.
    payload = [
        {"name": "Jane Smith", "actor_type": "person"},
        {"name": "New Actor", "actor_type": "person"},
    ]

    response = await client.post(
        f"/query-designs/{test_design.id}/actors/bulk",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["total"] == 2
    assert len(data["added"]) == 1
    assert "New Actor" in data["added"]
    assert len(data["skipped"]) == 1
    assert "Jane Smith" in data["skipped"]


@pytest.mark.asyncio
async def test_bulk_add_actors_ownership_guard(
    client: AsyncClient,
    other_auth_headers: dict[str, str],
    test_design: QueryDesign,
    db_session: AsyncSession,
    test_user_2,
):
    """Bulk add actors rejects requests from non-owners."""
    payload = [{"name": "Unauthorized Actor", "actor_type": "person"}]

    response = await client.post(
        f"/query-designs/{test_design.id}/actors/bulk",
        json=payload,
        headers=other_auth_headers,
    )

    assert response.status_code == 403

    # Verify no actors were created by test_user_2.
    result = await db_session.execute(
        select(Actor).where(Actor.created_by == test_user_2.id)
    )
    actors = result.scalars().all()
    assert len(actors) == 0


@pytest.mark.asyncio
async def test_bulk_add_actors_rejects_empty_payload(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_design: QueryDesign,
):
    """Bulk add actors returns 400 for empty payload."""
    response = await client.post(
        f"/query-designs/{test_design.id}/actors/bulk",
        json=[],
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "at least one actor" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_bulk_add_actors_rejects_empty_name(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_design: QueryDesign,
    db_session: AsyncSession,
    test_user,
):
    """Bulk add actors returns 422 when any name is empty after stripping."""
    payload = [
        {"name": "Valid Actor", "actor_type": "person"},
        {"name": "   ", "actor_type": "person"},
    ]

    response = await client.post(
        f"/query-designs/{test_design.id}/actors/bulk",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert "must not be empty" in response.json()["detail"].lower()

    # Verify no actors were created (atomic failure).
    result = await db_session.execute(
        select(Actor).where(Actor.created_by == test_user.id)
    )
    actors = result.scalars().all()
    assert len(actors) == 0


@pytest.mark.asyncio
async def test_bulk_add_actors_atomic_transaction(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_design: QueryDesign,
    db_session: AsyncSession,
    test_user,
):
    """Bulk add is atomic: if one actor fails, none are added."""
    payload = [
        {"name": "Valid Actor 1", "actor_type": "person"},
        {"name": "", "actor_type": "person"},
        {"name": "Valid Actor 2", "actor_type": "person"},
    ]

    response = await client.post(
        f"/query-designs/{test_design.id}/actors/bulk",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 422

    # Verify no actors were created (transaction rolled back).
    result = await db_session.execute(
        select(Actor).where(Actor.created_by == test_user.id)
    )
    actors = result.scalars().all()
    assert len(actors) == 0
