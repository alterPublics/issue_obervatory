#!/usr/bin/env python3
"""PostgreSQL restore script for The Issue Observatory.

Downloads a backup from MinIO and restores it into the target database.

Usage:
    # List available backups
    python scripts/restore_postgres.py --list

    # Restore a specific backup (will prompt for confirmation)
    python scripts/restore_postgres.py --restore postgres/2026/02/16/observatory_20260216_020000.sql.gz

    # Restore without interactive confirmation
    python scripts/restore_postgres.py --restore <object_name> --yes

Environment variables:
    DATABASE_URL        Full PostgreSQL DSN (required).
    MINIO_ENDPOINT      MinIO host:port, e.g. localhost:9000 (required).
    MINIO_ACCESS_KEY    MinIO access key (also accepts MINIO_ROOT_USER).
    MINIO_SECRET_KEY    MinIO secret key (also accepts MINIO_ROOT_PASSWORD).
    MINIO_BUCKET        Source bucket (default: observatory-backups).
    MINIO_SECURE        Use TLS (default: false).

Exit codes:
    0  Success
    1  Failure
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Structured JSON logger (identical pattern to backup_postgres.py)
# ---------------------------------------------------------------------------

def _log(level: str, event: str, **kwargs: object) -> None:
    record = {
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "level": level,
        "event": event,
        **kwargs,
    }
    print(json.dumps(record), flush=True)


def log_info(event: str, **kwargs: object) -> None:
    _log("INFO", event, **kwargs)


def log_error(event: str, **kwargs: object) -> None:
    _log("ERROR", event, **kwargs)


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def _get_env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        log_error("missing_required_env_var", var=name)
        sys.exit(1)
    return value or ""


def _parse_database_url(database_url: str) -> dict[str, str]:
    """Extract psql-compatible connection parameters from a DATABASE_URL."""
    normalised = re.sub(r"^postgresql\+[^:]+://", "postgresql://", database_url)
    parsed = urlparse(normalised)
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "dbname": (parsed.path or "/observatory").lstrip("/"),
        "user": parsed.username or "observatory",
        "password": parsed.password or "",
    }


# ---------------------------------------------------------------------------
# MinIO client factory
# ---------------------------------------------------------------------------

def _build_minio_client(
    endpoint: str,
    access_key: str,
    secret_key: str,
    secure: bool,
) -> object:
    try:
        from minio import Minio  # type: ignore[import-untyped]
    except ImportError:
        log_error(
            "minio_import_failed",
            detail="Install the 'minio' package: pip install 'minio>=7.2,<8.0'",
        )
        sys.exit(1)
    return Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

def list_backups(client: object, bucket: str, prefix: str = "postgres/") -> None:
    """Print all backup objects from MinIO, ordered by last_modified descending."""
    log_info("listing_backups", bucket=bucket, prefix=prefix)
    try:
        objects = sorted(
            client.list_objects(bucket, prefix=prefix, recursive=True),  # type: ignore[attr-defined]
            key=lambda o: o.last_modified or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
    except Exception as exc:  # noqa: BLE001
        log_error("list_failed", bucket=bucket, detail=str(exc))
        sys.exit(1)

    if not objects:
        print("No backups found.", flush=True)
        return

    # Human-readable table to stdout alongside structured records
    print(f"\n{'Object name':<70}  {'Size':>10}  {'Last modified'}", flush=True)
    print("-" * 110, flush=True)
    for obj in objects:
        size = f"{obj.size:,}" if obj.size else "unknown"
        modified = obj.last_modified.strftime("%Y-%m-%d %H:%M:%S UTC") if obj.last_modified else "unknown"
        print(f"{obj.object_name:<70}  {size:>10}  {modified}", flush=True)
    print(flush=True)


# ---------------------------------------------------------------------------
# Download from MinIO
# ---------------------------------------------------------------------------

def download_backup(
    client: object,
    bucket: str,
    object_name: str,
    local_path: str,
) -> None:
    """Download *object_name* from MinIO to *local_path*."""
    log_info("download_start", bucket=bucket, object_name=object_name)
    try:
        client.fget_object(bucket, object_name, local_path)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        log_error("download_failed", bucket=bucket, object_name=object_name, detail=str(exc))
        sys.exit(1)
    size_bytes = os.path.getsize(local_path)
    log_info("download_complete", local_path=local_path, size_bytes=size_bytes)


# ---------------------------------------------------------------------------
# Confirm prompt
# ---------------------------------------------------------------------------

def _confirm(prompt: str) -> bool:
    """Return True if the user types 'yes', False otherwise."""
    try:
        answer = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer == "yes"


# ---------------------------------------------------------------------------
# psql helpers
# ---------------------------------------------------------------------------

def _psql(
    conn: dict[str, str],
    dbname: str,
    sql: str,
) -> None:
    """Execute a single SQL statement via psql, connecting to *dbname*."""
    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]
    cmd = [
        "psql",
        "--host", conn["host"],
        "--port", conn["port"],
        "--username", conn["user"],
        "--dbname", dbname,
        "--no-password",
        "--quiet",
        "-c", sql,
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, check=False)
    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="replace").strip()
        log_error("psql_failed", sql=sql[:120], stderr=stderr_text)
        sys.exit(1)


def restore_database(conn: dict[str, str], dump_gz_path: str) -> None:
    """Decompress *dump_gz_path* and pipe it into a freshly-created database."""
    dbname = conn["dbname"]
    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    # 1. Terminate active connections
    log_info("terminate_connections", dbname=dbname)
    _psql(
        conn,
        "postgres",
        (
            f"SELECT pg_terminate_backend(pid) "
            f"FROM pg_stat_activity "
            f"WHERE datname = '{dbname}' AND pid <> pg_backend_pid();"
        ),
    )

    # 2. Drop the target database
    log_info("drop_database", dbname=dbname)
    _psql(conn, "postgres", f'DROP DATABASE IF EXISTS "{dbname}";')

    # 3. Recreate it
    log_info("create_database", dbname=dbname)
    _psql(conn, "postgres", f'CREATE DATABASE "{dbname}" OWNER "{conn["user"]}";')

    # 4. Stream decompressed dump into psql
    log_info("restore_start", dump_gz_path=dump_gz_path, dbname=dbname)
    psql_cmd = [
        "psql",
        "--host", conn["host"],
        "--port", conn["port"],
        "--username", conn["user"],
        "--dbname", dbname,
        "--no-password",
        "--quiet",
    ]
    try:
        with gzip.open(dump_gz_path, "rb") as gz:
            result = subprocess.run(
                psql_cmd,
                stdin=gz,
                capture_output=True,
                env=env,
                check=False,
            )
        if result.returncode != 0:
            stderr_text = result.stderr.decode("utf-8", errors="replace").strip()
            log_error("restore_failed", returncode=result.returncode, stderr=stderr_text)
            sys.exit(1)
    except OSError as exc:
        log_error("restore_io_error", detail=str(exc))
        sys.exit(1)

    log_info("restore_complete", dbname=dbname)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore a PostgreSQL database from a MinIO backup.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--list",
        action="store_true",
        help="List available backups in MinIO.",
    )
    group.add_argument(
        "--restore",
        metavar="OBJECT_NAME",
        help=(
            "Object name in MinIO to restore from, e.g. "
            "postgres/2026/02/16/observatory_20260216_020000.sql.gz"
        ),
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the interactive confirmation prompt.",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Read configuration from environment
    # ------------------------------------------------------------------
    minio_endpoint = _get_env("MINIO_ENDPOINT", required=True)
    access_key = (
        _get_env("MINIO_ACCESS_KEY")
        or _get_env("MINIO_ROOT_USER", default="minioadmin")
    )
    secret_key = (
        _get_env("MINIO_SECRET_KEY")
        or _get_env("MINIO_ROOT_PASSWORD", default="minioadmin")
    )
    bucket = _get_env("MINIO_BUCKET", default="observatory-backups")
    secure = _get_env("MINIO_SECURE", default="false").lower() in ("true", "1", "yes")

    client = _build_minio_client(minio_endpoint, access_key, secret_key, secure)

    # ------------------------------------------------------------------
    # --list
    # ------------------------------------------------------------------
    if args.list:
        list_backups(client, bucket)
        sys.exit(0)

    # ------------------------------------------------------------------
    # --restore
    # ------------------------------------------------------------------
    database_url = _get_env("DATABASE_URL", required=True)
    conn = _parse_database_url(database_url)
    object_name: str = args.restore

    log_info(
        "restore_requested",
        object_name=object_name,
        bucket=bucket,
        dbname=conn["dbname"],
        host=conn["host"],
    )

    # Check psql is available
    if not shutil.which("psql"):
        log_error("psql_not_found", detail="psql is not installed or not in PATH")
        sys.exit(1)

    # Confirmation
    if not args.yes:
        print(
            f"\nWARNING: This will DROP and recreate database '{conn['dbname']}' "
            f"on {conn['host']}:{conn['port']}.\n"
            "All existing data will be permanently lost.\n",
            flush=True,
        )
        if not _confirm("Type 'yes' to continue: "):
            log_info("restore_aborted", reason="user_declined")
            sys.exit(0)

    # Download the backup to a temp file
    with tempfile.NamedTemporaryFile(suffix=".sql.gz", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        download_backup(client, bucket, object_name, tmp_path)
        restore_database(conn, tmp_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
            log_info("temp_file_removed", path=tmp_path)

    log_info("restore_finished", status="success", object_name=object_name)
    sys.exit(0)


if __name__ == "__main__":
    main()
