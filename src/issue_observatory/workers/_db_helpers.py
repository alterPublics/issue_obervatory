"""Database helper utilities for synchronous Celery workers.

Shared helpers used by maintenance_tasks.py and export_tasks.py to avoid
code duplication.

Owned by the Core Application Engineer.
"""

from __future__ import annotations

import re


def _build_sync_dsn(async_dsn: str) -> str:
    """Convert an asyncpg DSN to a psycopg2-compatible DSN.

    Replaces ``postgresql+asyncpg://`` with ``postgresql://`` so that
    psycopg2 can connect inside synchronous Celery workers.

    Args:
        async_dsn: The application DATABASE_URL (asyncpg scheme).

    Returns:
        A psycopg2-compatible DSN string.
    """
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", async_dsn)
