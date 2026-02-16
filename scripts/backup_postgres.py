#!/usr/bin/env python3
"""Automated PostgreSQL backup script for The Issue Observatory.

Runs pg_dump, compresses with gzip, uploads to MinIO, and prunes old backups.

Usage:
    python scripts/backup_postgres.py [--dry-run]

Environment variables:
    DATABASE_URL            Full PostgreSQL DSN (required).
                            Supports postgresql+asyncpg:// and postgresql:// schemes.
    MINIO_ENDPOINT          MinIO host:port, e.g. localhost:9000 (required).
    MINIO_ACCESS_KEY        MinIO access key (also accepts MINIO_ROOT_USER).
    MINIO_SECRET_KEY        MinIO secret key (also accepts MINIO_ROOT_PASSWORD).
    MINIO_BUCKET            Destination bucket (default: observatory-backups).
    MINIO_SECURE            Use TLS (default: false).
    BACKUP_RETENTION_DAYS   Days to retain backups in MinIO (default: 30).

Exit codes:
    0  Success
    1  Failure (pg_dump error, upload error, etc.)
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
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Structured JSON logger
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


def log_warning(event: str, **kwargs: object) -> None:
    _log("WARNING", event, **kwargs)


# ---------------------------------------------------------------------------
# Environment parsing helpers
# ---------------------------------------------------------------------------

def _get_env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        log_error("missing_required_env_var", var=name)
        sys.exit(1)
    return value or ""


def _parse_database_url(database_url: str) -> dict[str, str]:
    """Extract pg_dump-compatible connection parameters from a DATABASE_URL.

    Handles both ``postgresql://`` and ``postgresql+asyncpg://`` (and other
    SQLAlchemy driver variants).  Returns a dict with keys: host, port, dbname,
    user, password.
    """
    # Normalise SQLAlchemy driver prefix (e.g. postgresql+asyncpg -> postgresql)
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
    """Return a configured minio.Minio client instance."""
    try:
        from minio import Minio  # type: ignore[import-untyped]
    except ImportError:
        log_error(
            "minio_import_failed",
            detail="Install the 'minio' package: pip install 'minio>=7.2,<8.0'",
        )
        sys.exit(1)

    return Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)


def _ensure_bucket(client: object, bucket: str, dry_run: bool) -> None:
    """Create the backup bucket if it does not already exist."""
    if dry_run:
        log_info("dry_run_ensure_bucket", bucket=bucket)
        return
    if not client.bucket_exists(bucket):  # type: ignore[attr-defined]
        client.make_bucket(bucket)  # type: ignore[attr-defined]
        log_info("bucket_created", bucket=bucket)
    else:
        log_info("bucket_exists", bucket=bucket)


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def run_pg_dump(conn: dict[str, str], output_path: str, dry_run: bool) -> None:
    """Run pg_dump and write gzip-compressed output to *output_path*."""
    cmd = [
        "pg_dump",
        "--host", conn["host"],
        "--port", conn["port"],
        "--username", conn["user"],
        "--dbname", conn["dbname"],
        "--format", "plain",
        "--no-password",
    ]

    if dry_run:
        log_info(
            "dry_run_pg_dump",
            command=" ".join(cmd),
            output=output_path,
        )
        return

    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    log_info("pg_dump_start", host=conn["host"], port=conn["port"], dbname=conn["dbname"])
    try:
        with gzip.open(output_path, "wb", compresslevel=9) as gz_file:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=False,
            )
            if result.returncode != 0:
                stderr_text = result.stderr.decode("utf-8", errors="replace").strip()
                log_error(
                    "pg_dump_failed",
                    returncode=result.returncode,
                    stderr=stderr_text,
                )
                sys.exit(1)
            gz_file.write(result.stdout)
    except OSError as exc:
        log_error("pg_dump_io_error", detail=str(exc))
        sys.exit(1)

    size_bytes = os.path.getsize(output_path)
    log_info("pg_dump_complete", output=output_path, size_bytes=size_bytes)


def upload_to_minio(
    client: object,
    local_path: str,
    bucket: str,
    object_name: str,
    dry_run: bool,
) -> None:
    """Upload a local file to MinIO under *object_name*."""
    if dry_run:
        log_info(
            "dry_run_upload",
            local_path=local_path,
            bucket=bucket,
            object_name=object_name,
        )
        return

    size_bytes = os.path.getsize(local_path)
    log_info(
        "upload_start",
        bucket=bucket,
        object_name=object_name,
        size_bytes=size_bytes,
    )
    try:
        client.fput_object(bucket, object_name, local_path)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        log_error("upload_failed", bucket=bucket, object_name=object_name, detail=str(exc))
        sys.exit(1)

    log_info("upload_complete", bucket=bucket, object_name=object_name)


def prune_old_backups(
    client: object,
    bucket: str,
    prefix: str,
    retention_days: int,
    dry_run: bool,
) -> None:
    """Delete MinIO objects under *prefix* that are older than *retention_days* days."""
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    log_info(
        "prune_start",
        bucket=bucket,
        prefix=prefix,
        retention_days=retention_days,
        cutoff=cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    try:
        objects = list(
            client.list_objects(bucket, prefix=prefix, recursive=True)  # type: ignore[attr-defined]
        )
    except Exception as exc:  # noqa: BLE001
        log_warning("prune_list_failed", bucket=bucket, prefix=prefix, detail=str(exc))
        return

    deleted = 0
    for obj in objects:
        last_modified = obj.last_modified
        if last_modified is None:
            continue
        # minio-py returns timezone-aware datetimes
        if last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=UTC)
        if last_modified < cutoff:
            if dry_run:
                log_info("dry_run_delete", object_name=obj.object_name, last_modified=str(last_modified))
            else:
                try:
                    client.remove_object(bucket, obj.object_name)  # type: ignore[attr-defined]
                    log_info("deleted_old_backup", object_name=obj.object_name)
                    deleted += 1
                except Exception as exc:  # noqa: BLE001
                    log_warning(
                        "delete_failed",
                        object_name=obj.object_name,
                        detail=str(exc),
                    )

    if not dry_run:
        log_info("prune_complete", deleted=deleted)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backup PostgreSQL database to MinIO object storage.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without executing any operations.",
    )
    args = parser.parse_args()
    dry_run: bool = args.dry_run

    if dry_run:
        log_info("dry_run_mode_enabled", detail="No operations will be executed.")

    # ------------------------------------------------------------------
    # Read configuration from environment
    # ------------------------------------------------------------------
    database_url = _get_env("DATABASE_URL", required=True)
    minio_endpoint = _get_env("MINIO_ENDPOINT", required=True)

    # Accept both MINIO_ACCESS_KEY (spec) and MINIO_ROOT_USER (compose compat)
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
    retention_days = int(_get_env("BACKUP_RETENTION_DAYS", default="30"))

    conn = _parse_database_url(database_url)

    # ------------------------------------------------------------------
    # Build timestamped object name
    # postgres/YYYY/MM/DD/observatory_YYYYMMDD_HHMMSS.sql.gz
    # ------------------------------------------------------------------
    now = datetime.now(UTC)
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    date_path = now.strftime("%Y/%m/%d")
    filename = f"observatory_{timestamp_str}.sql.gz"
    object_name = f"postgres/{date_path}/{filename}"
    # Prefix used for pruning: all objects under postgres/
    prune_prefix = "postgres/"

    log_info(
        "backup_start",
        dbname=conn["dbname"],
        host=conn["host"],
        bucket=bucket,
        object_name=object_name,
        retention_days=retention_days,
        dry_run=dry_run,
    )

    # ------------------------------------------------------------------
    # Check pg_dump availability
    # ------------------------------------------------------------------
    if not shutil.which("pg_dump"):
        log_error("pg_dump_not_found", detail="pg_dump is not installed or not in PATH")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Run backup in a temp file, then upload
    # ------------------------------------------------------------------
    client = _build_minio_client(minio_endpoint, access_key, secret_key, secure)
    _ensure_bucket(client, bucket, dry_run)

    with tempfile.NamedTemporaryFile(suffix=".sql.gz", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        run_pg_dump(conn, tmp_path, dry_run)
        upload_to_minio(client, tmp_path, bucket, object_name, dry_run)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    # ------------------------------------------------------------------
    # Prune old backups
    # ------------------------------------------------------------------
    prune_old_backups(client, bucket, prune_prefix, retention_days, dry_run)

    log_info("backup_finished", status="success", object_name=object_name)
    sys.exit(0)


if __name__ == "__main__":
    main()
