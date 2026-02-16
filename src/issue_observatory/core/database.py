"""Async SQLAlchemy engine and session factory.

Provides:
- async_engine:         the application-wide AsyncEngine instance
- AsyncSessionLocal:    the async_sessionmaker factory
- get_db():             FastAPI dependency that yields an AsyncSession
- Base.metadata:        re-exported so migrations can reference it without
                        importing individual models

Connection pool is sized for concurrent Celery workers + the FastAPI process:
- pool_size=10:         baseline connections held open
- max_overflow=20:      burst connections allowed above pool_size
- pool_pre_ping=True:   verify connection health before handing out

The DATABASE_URL must use the asyncpg driver scheme, e.g.:
    postgresql+asyncpg://user:password@localhost/issue_observatory

Owned by the DB Engineer.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ---------------------------------------------------------------------------
# Import Base so callers can do:
#   from issue_observatory.core.database import Base
# without importing individual model files.
# ---------------------------------------------------------------------------
from issue_observatory.core.models.base import Base  # noqa: F401

if TYPE_CHECKING:
    pass


def _build_engine(database_url: str):
    """Create the async engine from a database URL.

    Separated from module-level code so tests can call this with a test DSN
    without importing settings.
    """
    return create_async_engine(
        database_url,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )


def _get_database_url() -> str:
    """Resolve the database URL from application settings.

    Imported lazily so that test code can patch settings before the engine
    is created.
    """
    from issue_observatory.config.settings import get_settings  # noqa: PLC0415

    return str(get_settings().database_url)


# ---------------------------------------------------------------------------
# Application-wide engine and session factory.
# These are module-level singletons created on first import.
# ---------------------------------------------------------------------------
async_engine = _build_engine(_get_database_url())

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession for use as a FastAPI dependency.

    Usage in a route:

        from fastapi import Depends
        from issue_observatory.core.database import get_db

        @router.get("/things")
        async def list_things(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(Thing))
            return result.scalars().all()

    The session is closed (and the connection returned to the pool) after
    the response is sent, even if an exception is raised.  The caller is
    responsible for committing the transaction; the session is NOT
    auto-committed on exit so that route handlers remain explicit about
    their transaction boundaries.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
