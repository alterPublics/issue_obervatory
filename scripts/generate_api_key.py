#!/usr/bin/env python
"""Generate and assign a secure API key to a user by email address.

Run from the project root::

    python scripts/generate_api_key.py --email user@example.com

The script generates 32 bytes of cryptographic random data (64 hex characters),
stores it in the ``users.api_key`` column for the given user, and prints the
key to stdout.  This is the **only** time the plain-text key is displayed.

Usage::

    python scripts/generate_api_key.py --email user@example.com [--revoke]

Options:
    --email   (required) Email address of the user to update.
    --revoke  Clear the user's API key instead of generating a new one.

Exit codes:
    0 — Success.
    1 — User not found, missing arguments, or database error.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from typing import Optional

# Ensure the src layout is on sys.path when run as a standalone script.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)


async def _run(email: str, revoke: bool) -> None:
    """Update the API key for the user identified by ``email``.

    Args:
        email: The email address of the target user.
        revoke: If ``True``, clear the user's API key instead of generating
            a new one.

    Raises:
        SystemExit: With code 1 if the user is not found or a database error
            occurs.
    """
    from issue_observatory.core.database import AsyncSessionLocal  # noqa: PLC0415
    from issue_observatory.core.models.users import User  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(select(User).where(User.email == email))
            user: Optional[User] = result.scalars().first()

            if user is None:
                print(
                    f"[generate_api_key] ERROR: No user found with email '{email}'.",
                    file=sys.stderr,
                )
                sys.exit(1)

            if revoke:
                user.api_key = None
                print(f"[generate_api_key] API key revoked for '{email}'.")
            else:
                # 32 bytes → 64-character hex string, matching the VARCHAR(64) column.
                new_key = secrets.token_hex(32)
                user.api_key = new_key
                print(f"[generate_api_key] API key generated for '{email}':")
                print(f"\n  {new_key}\n")
                print(
                    "Store this key securely — it cannot be retrieved again.\n"
                    "Use it in API requests as:\n"
                    "  Authorization: Bearer <key>\n"
                    "  (or pass as the Bearer token on the /auth/bearer/login-compatible endpoints)\n"
                )


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed ``argparse.Namespace`` with ``email`` and ``revoke`` attributes.
    """
    parser = argparse.ArgumentParser(
        description="Generate or revoke an API key for an Issue Observatory user.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Email address of the user whose API key to generate or revoke.",
    )
    parser.add_argument(
        "--revoke",
        action="store_true",
        default=False,
        help="If set, clear (revoke) the user's API key instead of generating a new one.",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for the API key generation script."""
    args = _parse_args()
    asyncio.run(_run(email=args.email, revoke=args.revoke))


if __name__ == "__main__":
    main()
