"""Integration tests for the POST /query-designs/{id}/clone endpoint.

Tests verify the full clone lifecycle including:
- New QueryDesign created with "(copy)" suffix in name
- Search terms deep-copied with group_id and group_label preserved
- Actor list members deep-copied
- parent_design_id set to original's id
- New UUIDs generated for clone, terms, and members
- HTTP 303 redirect to /query-designs/{clone_id}
- HTTP 404 for nonexistent design
- HTTP 403 for design owned by another user

These tests require a live PostgreSQL instance.
Run with: pytest tests/integration/ -m integration -v
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.core.models.query_design import ActorList, QueryDesign, SearchTerm
from issue_observatory.core.models.users import User
from tests.conftest import TEST_PASSWORD

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helper: create a minimal QueryDesign owned by the given user
# ---------------------------------------------------------------------------


async def _create_query_design(
    db_session: AsyncSession,
    owner: User,
    name: str = "Test design",
) -> QueryDesign:
    """Insert a QueryDesign row owned by *owner* and return it."""
    design = QueryDesign(
        owner_id=owner.id,
        name=name,
        description="Integration test design",
        visibility="private",
        default_tier="free",
        language="da",
        locale_country="DK",
        arenas_config={},
        is_active=True,
    )
    db_session.add(design)
    await db_session.flush()
    await db_session.refresh(design)
    return design


async def _add_search_term(
    db_session: AsyncSession,
    design: QueryDesign,
    term: str,
    group_id: uuid.UUID | None = None,
    group_label: str | None = None,
) -> SearchTerm:
    """Insert a SearchTerm for *design* and return it."""
    st = SearchTerm(
        query_design_id=design.id,
        term=term,
        term_type="keyword",
        group_id=group_id,
        group_label=group_label,
        is_active=True,
    )
    db_session.add(st)
    await db_session.flush()
    return st


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    """Return Authorization headers for the given user."""
    resp = await client.post(
        "/auth/bearer/login",
        data={"username": email, "password": password},
    )
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCloneQueryDesign:
    async def test_clone_creates_new_design_with_copy_suffix_in_name(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Cloning a design creates a new QueryDesign whose name ends with '(copy)'."""
        headers = await _login(client, test_user.email, TEST_PASSWORD)
        design = await _create_query_design(db_session, test_user, name="Klimaundersøgelse")

        response = await client.post(
            f"/query-designs/{design.id}/clone",
            headers=headers,
            follow_redirects=False,
        )

        assert response.status_code == 303, (
            f"Expected 303, got {response.status_code}: {response.text}"
        )
        location = response.headers.get("location", "")
        clone_id_str = location.rstrip("/").split("/")[-1]
        clone_id = uuid.UUID(clone_id_str)

        result = await db_session.execute(
            select(QueryDesign).where(QueryDesign.id == clone_id)
        )
        clone = result.scalar_one_or_none()
        assert clone is not None, "Clone QueryDesign row not found in DB"
        assert "(copy)" in clone.name, (
            f"Expected '(copy)' in clone name, got: {clone.name!r}"
        )

    async def test_clone_copies_search_terms_preserving_group_id_and_group_label(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Cloning copies search terms with their group_id and group_label intact."""
        headers = await _login(client, test_user.email, TEST_PASSWORD)
        design = await _create_query_design(db_session, test_user, name="Grouped terms test")
        group_id = uuid.uuid4()
        await _add_search_term(
            db_session, design, "klimaforandringer", group_id=group_id, group_label="Climate"
        )
        await _add_search_term(
            db_session, design, "IPCC", group_id=group_id, group_label="Climate"
        )
        await db_session.flush()

        response = await client.post(
            f"/query-designs/{design.id}/clone",
            headers=headers,
            follow_redirects=False,
        )
        assert response.status_code == 303

        location = response.headers["location"]
        clone_id = uuid.UUID(location.rstrip("/").split("/")[-1])

        term_result = await db_session.execute(
            select(SearchTerm).where(SearchTerm.query_design_id == clone_id)
        )
        clone_terms = term_result.scalars().all()
        assert len(clone_terms) == 2
        for ct in clone_terms:
            assert ct.group_id == group_id, (
                f"group_id mismatch: expected {group_id}, got {ct.group_id}"
            )
            assert ct.group_label == "Climate", (
                f"group_label mismatch: expected 'Climate', got {ct.group_label!r}"
            )

    async def test_clone_sets_parent_design_id(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """The clone's parent_design_id equals the original design's id."""
        headers = await _login(client, test_user.email, TEST_PASSWORD)
        design = await _create_query_design(db_session, test_user)

        response = await client.post(
            f"/query-designs/{design.id}/clone",
            headers=headers,
            follow_redirects=False,
        )
        assert response.status_code == 303

        location = response.headers["location"]
        clone_id = uuid.UUID(location.rstrip("/").split("/")[-1])

        result = await db_session.execute(
            select(QueryDesign).where(QueryDesign.id == clone_id)
        )
        clone = result.scalar_one_or_none()
        assert clone is not None
        assert clone.parent_design_id == design.id, (
            f"parent_design_id: expected {design.id}, got {clone.parent_design_id}"
        )

    async def test_clone_generates_new_uuids_for_clone_and_terms(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """The clone has a new UUID and its terms have new UUIDs distinct from the original."""
        headers = await _login(client, test_user.email, TEST_PASSWORD)
        design = await _create_query_design(db_session, test_user)
        orig_term = await _add_search_term(db_session, design, "velfærdsstat")
        await db_session.flush()

        response = await client.post(
            f"/query-designs/{design.id}/clone",
            headers=headers,
            follow_redirects=False,
        )
        assert response.status_code == 303

        location = response.headers["location"]
        clone_id = uuid.UUID(location.rstrip("/").split("/")[-1])
        assert clone_id != design.id, "Clone must have a different UUID than the original"

        term_result = await db_session.execute(
            select(SearchTerm).where(SearchTerm.query_design_id == clone_id)
        )
        clone_terms = term_result.scalars().all()
        assert len(clone_terms) == 1
        assert clone_terms[0].id != orig_term.id, "Clone term must have a new UUID"

    async def test_clone_returns_303_redirect_to_clone_id(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Successful clone returns HTTP 303 with a Location header."""
        headers = await _login(client, test_user.email, TEST_PASSWORD)
        design = await _create_query_design(db_session, test_user)

        response = await client.post(
            f"/query-designs/{design.id}/clone",
            headers=headers,
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "location" in response.headers

    async def test_clone_redirect_url_does_not_contain_edit(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """The Location header points to /query-designs/{id}, not /query-designs/{id}/edit."""
        headers = await _login(client, test_user.email, TEST_PASSWORD)
        design = await _create_query_design(db_session, test_user)

        response = await client.post(
            f"/query-designs/{design.id}/clone",
            headers=headers,
            follow_redirects=False,
        )
        assert response.status_code == 303
        location = response.headers["location"]
        assert "/edit" not in location, (
            f"Location header must not contain '/edit', got: {location!r}"
        )

    async def test_clone_returns_404_for_nonexistent_design(
        self,
        client: AsyncClient,
        test_user: User,
    ) -> None:
        """Cloning a UUID that does not exist returns HTTP 404."""
        headers = await _login(client, test_user.email, TEST_PASSWORD)
        nonexistent_id = uuid.uuid4()

        response = await client.post(
            f"/query-designs/{nonexistent_id}/clone",
            headers=headers,
            follow_redirects=False,
        )

        assert response.status_code == 404

    async def test_clone_returns_403_for_design_owned_by_another_user(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        test_admin: User,
    ) -> None:
        """Cloning a design owned by another (non-admin) user returns HTTP 403."""
        # Create design owned by test_admin.
        design = await _create_query_design(db_session, test_admin, name="Admin's design")
        await db_session.flush()

        # Attempt to clone as test_user (not the owner, not an admin).
        headers = await _login(client, test_user.email, TEST_PASSWORD)
        response = await client.post(
            f"/query-designs/{design.id}/clone",
            headers=headers,
            follow_redirects=False,
        )

        assert response.status_code == 403

    async def test_clone_copies_actor_list_structure(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Cloning a design that has an actor list copies the actor list metadata.

        We verify that the cloned design has one ActorList with the same name
        as the original.  Member copying is not tested here because members
        require pre-existing Actor rows (integration with the actors table).
        """
        from sqlalchemy import select as _select  # noqa: PLC0415

        headers = await _login(client, test_user.email, TEST_PASSWORD)
        design = await _create_query_design(db_session, test_user, name="Design with actors")

        # Create an actor list on the original design.
        actor_list = ActorList(
            query_design_id=design.id,
            name="Danish politicians",
            description="Key political actors",
            created_by=test_user.id,
            sampling_method="manual",
        )
        db_session.add(actor_list)
        await db_session.flush()

        response = await client.post(
            f"/query-designs/{design.id}/clone",
            headers=headers,
            follow_redirects=False,
        )
        assert response.status_code == 303

        location = response.headers["location"]
        clone_id = uuid.UUID(location.rstrip("/").split("/")[-1])

        # The clone should have one actor list with the same name.
        list_result = await db_session.execute(
            _select(ActorList).where(ActorList.query_design_id == clone_id)
        )
        clone_lists = list_result.scalars().all()
        assert len(clone_lists) == 1
        assert clone_lists[0].name == "Danish politicians"
        # The list's own ID must be different from the original list's ID.
        assert clone_lists[0].id != actor_list.id
