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

from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

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


def _get_sync_database_url() -> str:
    """Return a synchronous (psycopg2) database URL derived from the async URL.

    Replaces the ``postgresql+asyncpg://`` driver prefix with the standard
    ``postgresql+psycopg2://`` prefix required by the synchronous engine used
    in Celery task helpers.
    """
    url = _get_database_url()
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://").replace(
        "postgresql://", "postgresql+psycopg2://"
    )


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
# Synchronous engine and session factory (used by Celery task helpers)
# ---------------------------------------------------------------------------

_sync_engine = create_engine(
    _get_sync_database_url(),
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

SyncSessionLocal: sessionmaker[Session] = sessionmaker(
    bind=_sync_engine,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@contextmanager
def get_sync_session() -> Generator[Session, None, None]:
    """Yield a synchronous SQLAlchemy Session for use in Celery task helpers.

    The session is committed on clean exit and rolled back on exception.
    Intended for best-effort status updates inside arena tasks where an
    async event loop is not available.

    Usage::

        with get_sync_session() as session:
            session.execute(text("UPDATE ..."), {...})
            session.commit()
    """
    session = SyncSessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


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
