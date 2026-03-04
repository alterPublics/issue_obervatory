#!/usr/bin/env python
"""Bootstrap the first admin user.

Run **once** after the database has been initialised (Alembic migrations
applied) to create the initial admin account.  The admin account can then
log in, activate other users, and allocate credits.

Usage::

    python scripts/bootstrap_admin.py

Environment variables (via .env or shell)::

    FIRST_ADMIN_EMAIL     The email address for the admin account.
    FIRST_ADMIN_PASSWORD  The initial password for the admin account.

Both variables must be set for the script to proceed.  If the users table
already contains a user with the given email, the existing user is updated to
``role='admin'`` and ``is_active=True`` (idempotent re-run).

Exit codes:
    0 — Success (user created or already existed and was updated).
    1 — Missing environment variables or database error.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Optional

# Resolve package root so the script works when run from the project root
# without installing the package:  python scripts/bootstrap_admin.py
import importlib.util
import os

# Ensure the src layout is on sys.path when running as a standalone script.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)


async def _bootstrap() -> None:
    """Create or update the admin user row in the database.

    Raises:
        SystemExit: With code 1 if configuration is missing or a database
            error occurs.
    """
    from issue_observatory.config.settings import get_settings  # noqa: PLC0415
    from issue_observatory.core.database import AsyncSessionLocal  # noqa: PLC0415
    from issue_observatory.core.models.users import User  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    settings = get_settings()

    admin_email: str = str(settings.first_admin_email)
    admin_password: str = settings.first_admin_password

    if not admin_email or not admin_password:
        print(
            "[bootstrap_admin] ERROR: FIRST_ADMIN_EMAIL and FIRST_ADMIN_PASSWORD "
            "must be set in the environment or .env file.",
            file=sys.stderr,
        )
        print(
            "  Example:\n"
            "    FIRST_ADMIN_EMAIL=admin@example.com \\\n"
            "    FIRST_ADMIN_PASSWORD=changeme123 \\\n"
            "    python scripts/bootstrap_admin.py",
            file=sys.stderr,
        )
        sys.exit(1)

    # Hash the password using FastAPI-Users' password helper.
    from fastapi_users.password import PasswordHelper  # noqa: PLC0415

    password_helper = PasswordHelper()
    hashed = password_helper.hash(admin_password)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                select(User).where(User.email == admin_email)
            )
            existing: Optional[User] = result.scalars().first()

            if existing is not None:
                # Idempotent: ensure admin has the correct role and is active.
                changed: list[str] = []
                if existing.role != "admin":
                    existing.role = "admin"
                    changed.append("role -> admin")
                if not existing.is_active:
                    existing.is_active = True
                    changed.append("is_active -> True")
                if not existing.display_name:
                    existing.display_name = "Administrator"
                    changed.append("display_name -> Administrator")
                if changed:
                    print(
                        f"[bootstrap_admin] Existing user '{admin_email}' updated: "
                        + ", ".join(changed)
                    )
                else:
                    print(
                        f"[bootstrap_admin] Admin user '{admin_email}' already exists "
                        "with correct role and is_active=True.  Nothing to do."
                    )
            else:
                new_user = User(
                    email=admin_email,
                    hashed_password=hashed,
                    role="admin",
                    is_active=True,
                    display_name="Administrator",
                )
                session.add(new_user)
                print(
                    f"[bootstrap_admin] Created admin user '{admin_email}'."
                )

    print("[bootstrap_admin] Done.")
    print(
        "\nNext steps:\n"
        "  1. Log in at  http://localhost:8000/auth/login\n"
        "  2. Activate researcher accounts at  http://localhost:8000/admin/users\n"
        "  3. Allocate credits at  http://localhost:8000/admin/credits/allocate\n"
    )


def main() -> None:
    """Entry point for the bootstrap script.

    Wraps the async coroutine in ``asyncio.run``.
    """
    asyncio.run(_bootstrap())


if __name__ == "__main__":
    main()
