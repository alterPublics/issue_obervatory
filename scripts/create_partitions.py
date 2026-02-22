#!/usr/bin/env python
"""Create monthly partitions for content_records table.

The ``content_records`` table is range-partitioned by ``published_at``
with monthly boundaries. This script ensures partitions exist for the
next N months (default 12) ahead of the latest existing partition.

The script is idempotent — it skips partitions that already exist and
only creates missing ones.

Usage:
    # Create partitions for next 12 months (default)
    python scripts/create_partitions.py

    # Create partitions for next 24 months
    python scripts/create_partitions.py --months 24

Environment:
    Requires DATABASE_URL environment variable to be set.

IMPORTANT:
    Run this script periodically (e.g., quarterly) to stay ahead of the
    current date and ensure partitions exist for incoming data. Without
    future partitions, inserts for dates beyond the last partition will
    fall into the ``content_records_default`` partition, which signals a
    data quality issue.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import text

# Add project root to path so we can import settings
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from issue_observatory.config.settings import get_settings


def get_existing_partitions(conn: sa.Connection) -> set[str]:
    """Query PostgreSQL catalog to get existing content_records partitions.

    Args:
        conn: SQLAlchemy synchronous connection.

    Returns:
        Set of partition table names (e.g., {"content_records_2026_02", ...}).
    """
    query = text("""
        SELECT child.relname
        FROM pg_catalog.pg_inherits
        JOIN pg_catalog.pg_class AS parent ON parent.oid = pg_inherits.prrelid
        JOIN pg_catalog.pg_class AS child ON child.oid = pg_inherits.inhrelid
        WHERE parent.relname = 'content_records'
          AND child.relname != 'content_records_default'
    """)
    result = conn.execute(query)
    return {row[0] for row in result}


def parse_partition_name(partition_name: str) -> datetime | None:
    """Extract the month start date from a partition table name.

    Args:
        partition_name: Table name like "content_records_2026_02".

    Returns:
        datetime object for the first day of the month, or None if the
        name doesn't match the expected pattern.
    """
    if not partition_name.startswith("content_records_"):
        return None

    parts = partition_name.split("_")
    if len(parts) != 3:  # noqa: PLR2004
        return None

    try:
        year = int(parts[1])
        month = int(parts[2])
        return datetime(year, month, 1)
    except (ValueError, IndexError):
        return None


def get_latest_partition_date(partitions: set[str]) -> datetime | None:
    """Find the latest month represented in existing partitions.

    Args:
        partitions: Set of partition table names.

    Returns:
        datetime for the latest month's first day, or None if no valid
        partitions found.
    """
    dates = [parse_partition_name(p) for p in partitions]
    valid_dates = [d for d in dates if d is not None]
    return max(valid_dates) if valid_dates else None


def create_partition(
    conn: sa.Connection, year: int, month: int, verbose: bool = True
) -> None:
    """Create a single monthly partition for content_records.

    Args:
        conn: SQLAlchemy synchronous connection.
        year: Four-digit year (e.g., 2026).
        month: Month number (1-12).
        verbose: If True, print progress messages.
    """
    partition_name = f"content_records_{year:04d}_{month:02d}"

    # Calculate the range boundaries.
    start_date = datetime(year, month, 1)
    # Next month is either month+1 in same year, or January of next year.
    if month == 12:  # noqa: PLR2004
        next_month = datetime(year + 1, 1, 1)
    else:
        next_month = datetime(year, month + 1, 1)

    ddl = text(f"""
        CREATE TABLE {partition_name}
        PARTITION OF content_records
        FOR VALUES FROM ('{start_date:%Y-%m-%d}') TO ('{next_month:%Y-%m-%d}')
    """)

    try:
        conn.execute(ddl)
        conn.commit()
        if verbose:
            print(f"Created partition: {partition_name} ({start_date:%Y-%m-%d} to {next_month:%Y-%m-%d})")
    except sa.exc.ProgrammingError as exc:
        # If partition already exists, PostgreSQL raises "relation already exists"
        conn.rollback()
        if "already exists" in str(exc).lower():
            if verbose:
                print(f"Skipped (already exists): {partition_name}")
        else:
            raise


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Create monthly partitions for content_records table"
    )
    parser.add_argument(
        "--months",
        type=int,
        default=12,
        help="Number of months ahead to create (default: 12)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress messages",
    )
    args = parser.parse_args()

    verbose = not args.quiet

    # Load database URL from settings
    settings = get_settings()
    if not settings.database_url:
        print("ERROR: DATABASE_URL environment variable not set", file=sys.stderr)
        sys.exit(1)

    # Create synchronous engine
    engine = sa.create_engine(settings.database_url.unicode_string())

    with engine.connect() as conn:
        # 1. Get existing partitions
        existing = get_existing_partitions(conn)
        if verbose:
            print(f"Found {len(existing)} existing content_records partitions")

        # 2. Determine starting point
        latest_date = get_latest_partition_date(existing)
        if latest_date:
            # Start from the month after the latest partition
            start_date = latest_date + timedelta(days=32)  # ~1 month
            start_date = start_date.replace(day=1)  # normalize to first of month
            if verbose:
                print(f"Latest partition: {latest_date:%Y-%m}")
                print(f"Creating partitions starting from: {start_date:%Y-%m}")
        else:
            # No partitions found — start from current month
            start_date = datetime.now().replace(day=1)
            if verbose:
                print("No existing partitions found. Starting from current month.")

        # 3. Create partitions for the next N months
        created_count = 0
        current = start_date
        for _ in range(args.months):
            create_partition(conn, current.year, current.month, verbose=verbose)
            created_count += 1

            # Advance to next month
            if current.month == 12:  # noqa: PLR2004
                current = datetime(current.year + 1, 1, 1)
            else:
                current = datetime(current.year, current.month + 1, 1)

        if verbose:
            print(f"\nDone. Created/verified {created_count} partitions.")


if __name__ == "__main__":
    main()
