#!/usr/bin/env bash
# Automated PostgreSQL backup script for The Issue Observatory.
# Usage: ./scripts/backup_postgres.sh
# Typically called by cron or the backup Docker service (daily at 02:00 UTC).
#
# Environment variables:
#   DATABASE_URL              Full DSN (preferred). Parsed for host/port/db/user.
#   POSTGRES_HOST             Database host (default: postgres)
#   POSTGRES_PORT             Database port (default: 5432)
#   POSTGRES_DB               Database name (default: observatory)
#   POSTGRES_USER             Database user (default: observatory)
#   PGPASSWORD                Database password (set from DATABASE_URL or directly)
#   BACKUP_DIR                Local staging directory (default: /backups/postgres)
#   BACKUP_RETENTION_DAYS     Days to keep local files (default: 30)
#   MINIO_ENDPOINT            MinIO server e.g. minio:9000 (skip upload if unset)
#   MINIO_ROOT_USER           MinIO access key
#   MINIO_ROOT_PASSWORD       MinIO secret key
#   MINIO_BUCKET              Destination bucket (default: observatory-backups)

set -euo pipefail

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
log()  { printf '[%s] INFO  %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }
err()  { printf '[%s] ERROR %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >&2; }
die()  { err "$*"; exit 1; }

# ---------------------------------------------------------------------------
# 1. Parse connection parameters
# ---------------------------------------------------------------------------
# If DATABASE_URL is set (e.g. postgresql+asyncpg://user:pass@host:5432/db),
# extract the individual components. The asyncpg driver prefix is normalised
# to plain postgresql so that psql / pg_dump accept it.

if [[ -n "${DATABASE_URL:-}" ]]; then
    # Strip optional SQLAlchemy driver suffix (+asyncpg, +psycopg2, …)
    _raw="${DATABASE_URL#postgresql+*://}"
    # If the URL starts with "postgresql://" strip the scheme
    _raw="${DATABASE_URL#postgresql://}"
    _raw="${DATABASE_URL#postgresql+asyncpg://}"

    # user:pass@host:port/db
    _userinfo="${_raw%%@*}"
    _hostinfo="${_raw##*@}"

    PGUSER="${_userinfo%%:*}"
    PGPASSWORD="${_userinfo#*:}"
    _hostport="${_hostinfo%%/*}"
    PGHOST="${_hostport%%:*}"
    PGPORT="${_hostport##*:}"
    PGDATABASE="${_hostinfo##*/}"
    # Remove query-string if present
    PGDATABASE="${PGDATABASE%%\?*}"
    export PGPASSWORD
fi

PGHOST="${PGHOST:-${POSTGRES_HOST:-postgres}}"
PGPORT="${PGPORT:-${POSTGRES_PORT:-5432}}"
PGDATABASE="${PGDATABASE:-${POSTGRES_DB:-observatory}}"
PGUSER="${PGUSER:-${POSTGRES_USER:-observatory}}"
PGPASSWORD="${PGPASSWORD:-${POSTGRES_PASSWORD:-}}"
export PGPASSWORD

BACKUP_DIR="${BACKUP_DIR:-/backups/postgres}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
MINIO_ENDPOINT="${MINIO_ENDPOINT:-}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-minioadmin}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-minioadmin}"
MINIO_BUCKET="${MINIO_BUCKET:-observatory-backups}"

log "Starting PostgreSQL backup"
log "  Host:     ${PGHOST}:${PGPORT}"
log "  Database: ${PGDATABASE}"
log "  User:     ${PGUSER}"

# ---------------------------------------------------------------------------
# 2. Prepare local backup directory and filename
# ---------------------------------------------------------------------------
mkdir -p "${BACKUP_DIR}"

TIMESTAMP="$(date -u '+%Y-%m-%d_%H%M%S')"
FILENAME="issue_observatory_${TIMESTAMP}.sql.gz"
FILEPATH="${BACKUP_DIR}/${FILENAME}"

# ---------------------------------------------------------------------------
# 3. Run pg_dump with gzip compression
# ---------------------------------------------------------------------------
log "Running pg_dump -> ${FILEPATH}"

pg_dump \
    --host="${PGHOST}" \
    --port="${PGPORT}" \
    --username="${PGUSER}" \
    --dbname="${PGDATABASE}" \
    --format=plain \
    --no-password \
    | gzip -9 > "${FILEPATH}"

FILESIZE="$(du -sh "${FILEPATH}" | cut -f1)"
log "Dump complete: ${FILENAME} (${FILESIZE})"

# ---------------------------------------------------------------------------
# 4. Upload to MinIO (optional)
# ---------------------------------------------------------------------------
if [[ -n "${MINIO_ENDPOINT}" ]]; then
    log "Uploading to MinIO: ${MINIO_ENDPOINT}/${MINIO_BUCKET}/backups/${FILENAME}"

    MC_ALIAS="observatory_backup"

    mc alias set "${MC_ALIAS}" \
        "http://${MINIO_ENDPOINT}" \
        "${MINIO_ROOT_USER}" \
        "${MINIO_ROOT_PASSWORD}" \
        --quiet

    mc cp \
        "${FILEPATH}" \
        "${MC_ALIAS}/${MINIO_BUCKET}/backups/${FILENAME}" \
        --quiet

    log "Upload complete"
else
    log "MINIO_ENDPOINT not set — skipping remote upload"
fi

# ---------------------------------------------------------------------------
# 5. Delete local files older than BACKUP_RETENTION_DAYS
# ---------------------------------------------------------------------------
log "Pruning local files older than ${BACKUP_RETENTION_DAYS} days from ${BACKUP_DIR}"

find "${BACKUP_DIR}" \
    -maxdepth 1 \
    -name "issue_observatory_*.sql.gz" \
    -mtime "+${BACKUP_RETENTION_DAYS}" \
    -type f \
    -print \
    -delete

log "Backup finished successfully"
