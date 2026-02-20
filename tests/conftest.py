"""Shared pytest fixtures for Issue Observatory tests.

Fixture summary
---------------
db_session      — Async PostgreSQL session with automatic per-test rollback.
client          — httpx.AsyncClient against the FastAPI app with DB override.
test_user       — Active researcher User ORM object.
test_admin      — Admin User ORM object.
auth_headers    — Bearer-token Authorization headers for test_user.
admin_auth_headers — Bearer-token Authorization headers for test_admin.

Integration tests that use ``db_session`` or ``client`` require a live
PostgreSQL instance.  Set DATABASE_URL in the environment or in .env before
running.  Unit tests that mock all external dependencies run without any
infrastructure.

Owned by QA Engineer.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# Test environment bootstrap
# ---------------------------------------------------------------------------
# Set required env vars before any application modules are imported so that
# Settings() does not raise a ValidationError during collection.
# In CI these are injected by the GitHub Actions workflow; locally they can
# live in a .env file or be exported in the shell.

_TEST_ENV_DEFAULTS: dict[str, str] = {
    "DATABASE_URL": "postgresql+asyncpg://postgres:test@localhost:5432/test_observatory",
    "SECRET_KEY": "test-secret-key-for-tests-only-not-production",
    "CREDENTIAL_ENCRYPTION_KEY": "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==",
    "PSEUDONYMIZATION_SALT": "test-pseudonymization-salt-for-unit-tests",
    "REDIS_URL": "redis://localhost:6379/0",
    "FIRST_ADMIN_EMAIL": "admin@test.example.com",
    "FIRST_ADMIN_PASSWORD": "test-admin-password-123",
}

for _key, _default in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _default)

# ---------------------------------------------------------------------------
# Application imports (after env bootstrap)
# ---------------------------------------------------------------------------

from issue_observatory.api.main import app  # noqa: E402
from issue_observatory.config.settings import get_settings  # noqa: E402
from issue_observatory.core.database import Base  # noqa: E402
from issue_observatory.core.models.users import CreditAllocation, User  # noqa: E402

# Clear the lru_cache so Settings() re-reads from the patched environment.
get_settings.cache_clear()

# ---------------------------------------------------------------------------
# Password helper (shared by user factories)
# ---------------------------------------------------------------------------

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TEST_PASSWORD = "password123"
TEST_PASSWORD_HASH: str = _pwd_context.hash(TEST_PASSWORD)


# ---------------------------------------------------------------------------
# Test database engine and session factory
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Return the DATABASE_URL for the test session.

    Reads from the environment (set by CI or by the developer's shell).
    Falls back to the default localhost URL for local development.
    """
    return os.environ["DATABASE_URL"]


# Session-scoped table creation (runs once, synchronously, to avoid
# event-loop issues).
_tables_created = False


@pytest.fixture(scope="session", autouse=True)
def _ensure_tables(test_database_url: str) -> None:
    """Create all tables once per session using a synchronous engine.

    Drops and recreates all tables to ensure the schema matches the current
    SQLAlchemy models. This is crucial when models have been updated since the
    last test run (e.g., new columns added).

    Also creates content_records partitions spanning 2024-2027 for test data.

    In CI the Alembic migration step (``alembic upgrade head``) runs before
    pytest, so this is a safety net for local runs that skip migrations.
    """
    import sqlalchemy as sa  # noqa: PLC0415
    from sqlalchemy import create_engine as create_sync_engine  # noqa: PLC0415

    global _tables_created  # noqa: PLW0603
    if _tables_created:
        return
    sync_url = test_database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"
    ).replace("postgresql://", "postgresql+psycopg2://")

    sync_engine = create_sync_engine(sync_url, echo=False)
    with sync_engine.begin() as conn:
        # Drop all tables first to ensure fresh schema matching current models
        Base.metadata.drop_all(bind=conn)
        Base.metadata.create_all(bind=conn)

        # Create content_records partitions for test date ranges (2024-2027)
        # This covers the range used by existing tests
        for year in range(2024, 2028):
            for month in range(1, 13):
                next_month = month + 1 if month < 12 else 1
                next_year = year if month < 12 else year + 1
                partition_name = f"content_records_{year}_{month:02d}"

                conn.execute(sa.text(f"""
                    CREATE TABLE IF NOT EXISTS {partition_name}
                    PARTITION OF content_records
                    FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{next_year}-{next_month:02d}-01')
                """))

        # Create default partition for dates outside normal range
        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS content_records_default
            PARTITION OF content_records DEFAULT
        """))

    sync_engine.dispose()
    _tables_created = True


@pytest_asyncio.fixture
async def test_engine(test_database_url: str):
    """Create an async engine scoped to the current test's event loop.

    Each test function gets its own event loop in pytest-asyncio auto mode,
    so the engine (and its connection pool) must be created on that same loop
    to avoid 'Future attached to a different loop' errors.

    Yields:
        AsyncEngine configured against the test PostgreSQL instance.
    """
    engine = create_async_engine(
        test_database_url,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
def test_session_factory(test_engine) -> async_sessionmaker[AsyncSession]:
    """Return a sessionmaker bound to the test engine."""
    return async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


@pytest_asyncio.fixture
async def db_session(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession that rolls back after each test.

    Each test runs inside a transaction savepoint that is rolled back on
    teardown, keeping the database in a clean state without dropping and
    recreating tables.

    Yields:
        An open :class:`AsyncSession` ready for use in tests.
    """
    async with test_session_factory() as session:
        await session.begin()
        try:
            yield session
        finally:
            await session.rollback()


# ---------------------------------------------------------------------------
# FastAPI test client with DB override
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Yield an httpx.AsyncClient against the FastAPI app.

    The app's ``get_db`` dependency is overridden to use the test session so
    that test-created rows are visible inside route handlers, and so the
    rollback in ``db_session`` cleans up after each test.

    Yields:
        :class:`httpx.AsyncClient` configured for the test app.
    """
    from issue_observatory.core.database import get_db  # noqa: PLC0415

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    # Manually trigger startup events to ensure app.state is initialized
    # (httpx ASGITransport doesn't automatically trigger them)
    for handler in app.router.on_startup:
        if callable(handler):
            await handler()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        follow_redirects=True,
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# User fixtures
# ---------------------------------------------------------------------------


async def _create_user(
    db_session: AsyncSession,
    *,
    email: str,
    role: str = "researcher",
    is_active: bool = True,
    display_name: str | None = None,
) -> User:
    """Internal helper: insert a User row directly into the test database.

    Bypasses FastAPI-Users registration so tests do not depend on a full
    SMTP / user verification round-trip.
    """
    user = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=TEST_PASSWORD_HASH,
        display_name=display_name or email.split("@")[0],
        role=role,
        is_active=is_active,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """An active researcher user for use in tests.

    Returns:
        :class:`User` with ``role='researcher'`` and ``is_active=True``.
    """
    return await _create_user(
        db_session,
        email=f"researcher-{uuid.uuid4().hex[:8]}@example.com",
        role="researcher",
        is_active=True,
        display_name="Test Researcher",
    )


@pytest_asyncio.fixture
async def test_admin(db_session: AsyncSession) -> User:
    """An admin user for use in tests.

    Returns:
        :class:`User` with ``role='admin'`` and ``is_active=True``.
    """
    return await _create_user(
        db_session,
        email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
        role="admin",
        is_active=True,
        display_name="Test Admin",
    )


@pytest_asyncio.fixture
async def test_user_2(db_session: AsyncSession) -> User:
    """A second active researcher user for multi-user tests.

    Returns:
        :class:`User` with ``role='researcher'`` and ``is_active=True``.
    """
    return await _create_user(
        db_session,
        email=f"researcher2-{uuid.uuid4().hex[:8]}@example.com",
        role="researcher",
        is_active=True,
        display_name="Test Researcher 2",
    )


@pytest_asyncio.fixture
async def test_inactive_user(db_session: AsyncSession) -> User:
    """An inactive (pending admin approval) user for use in tests.

    Returns:
        :class:`User` with ``is_active=False``.
    """
    return await _create_user(
        db_session,
        email=f"inactive-{uuid.uuid4().hex[:8]}@example.com",
        role="researcher",
        is_active=False,
        display_name="Inactive User",
    )


# ---------------------------------------------------------------------------
# Auth header fixtures (bearer token)
# ---------------------------------------------------------------------------


async def _get_bearer_token(client: AsyncClient, email: str, password: str) -> str:
    """Log in via the bearer endpoint and return the access token.

    Args:
        client: The test HTTP client.
        email: User email.
        password: Plaintext password.

    Returns:
        JWT access token string.

    Raises:
        AssertionError: If login does not return HTTP 200.
    """
    response = await client.post(
        "/auth/bearer/login",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200, (
        f"Login failed for {email!r}: {response.status_code} {response.text}"
    )
    return response.json()["access_token"]


@pytest_asyncio.fixture
async def auth_headers(test_user: User, client: AsyncClient) -> dict[str, str]:
    """Return Authorization headers for the active researcher user.

    Returns:
        Dict suitable for passing as ``headers=`` to ``client`` calls,
        e.g. ``{"Authorization": "Bearer <token>"}``.
    """
    token = await _get_bearer_token(client, test_user.email, TEST_PASSWORD)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def admin_auth_headers(test_admin: User, client: AsyncClient) -> dict[str, str]:
    """Return Authorization headers for the admin user.

    Returns:
        Dict suitable for passing as ``headers=`` to ``client`` calls.
    """
    token = await _get_bearer_token(client, test_admin.email, TEST_PASSWORD)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Credit fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def funded_user(db_session: AsyncSession) -> User:
    """An active researcher user with 1,000 credits allocated.

    Returns:
        :class:`User` with a :class:`CreditAllocation` of 1,000 credits valid
        indefinitely from today.
    """
    import datetime  # noqa: PLC0415

    user = await _create_user(
        db_session,
        email=f"funded-{uuid.uuid4().hex[:8]}@example.com",
        role="researcher",
        is_active=True,
        display_name="Funded Researcher",
    )
    allocation = CreditAllocation(
        user_id=user.id,
        credits_amount=1000,
        valid_from=datetime.date.today(),
        valid_until=None,
        memo="Test allocation",
    )
    db_session.add(allocation)
    await db_session.flush()
    return user


# ---------------------------------------------------------------------------
# Normalizer fixture (unit tests — no DB required)
# ---------------------------------------------------------------------------


@pytest.fixture
def normalizer() -> Any:
    """Return a :class:`Normalizer` instance with a test salt.

    The salt is hard-coded so that unit tests produce deterministic
    pseudonymized IDs without reading from the environment.

    Returns:
        :class:`issue_observatory.core.normalizer.Normalizer` instance.
    """
    from issue_observatory.core.normalizer import Normalizer  # noqa: PLC0415

    return Normalizer(pseudonymization_salt="test-pseudonymization-salt-for-unit-tests")


# ---------------------------------------------------------------------------
# Mock HTTP client fixture (for arena collector unit tests)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_http_client() -> Any:
    """Return an httpx.MockTransport-based AsyncClient stub.

    Arena collector unit tests should replace this fixture's implementation
    with ``respx`` or ``unittest.mock`` to return recorded API responses.

    This fixture provides the interface contract; arena-specific test modules
    should override it with a parametrized version that loads from
    ``tests/fixtures/api_responses/<platform>/``.
    """
    import httpx  # noqa: PLC0415

    # Default: returns 200 with empty organic results (safe default).
    return httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"organic": []})
        )
    )
