#!/usr/bin/env bash
# Restore PostgreSQL from a backup file for The Issue Observatory.
# Usage:
#   ./scripts/restore_postgres.sh <backup_file.sql.gz>
#   ./scripts/restore_postgres.sh minio://observatory-backups/backups/issue_observatory_2026-02-15_020000.sql.gz
#
# The first argument is either:
#   - A local path to a .sql.gz file, or
#   - A minio:// URI in the form  minio://<bucket>/<object-path>
#
# Environment variables (same as backup_postgres.sh):
#   DATABASE_URL, POSTGRES_HOST/PORT/DB/USER/PASSWORD
#   MINIO_ENDPOINT, MINIO_ROOT_USER, MINIO_ROOT_PASSWORD, MINIO_BUCKET

set -euo pipefail

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
log()  { printf '[%s] INFO  %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }
err()  { printf '[%s] ERROR %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >&2; }
die()  { err "$*"; exit 1; }

# ---------------------------------------------------------------------------
# Argument check
# ---------------------------------------------------------------------------
if [[ $# -lt 1 ]]; then
    die "Usage: $0 <backup_file.sql.gz | minio://<bucket>/<path>>"
fi

BACKUP_ARG="$1"

# ---------------------------------------------------------------------------
# Parse connection parameters (same logic as backup script)
# ---------------------------------------------------------------------------
if [[ -n "${DATABASE_URL:-}" ]]; then
    _raw="${DATABASE_URL#postgresql+asyncpg://}"
    _raw="${_raw#postgresql://}"
    _userinfo="${_raw%%@*}"
    _hostinfo="${_raw##*@}"
    PGUSER="${_userinfo%%:*}"
    PGPASSWORD="${_userinfo#*:}"
    _hostport="${_hostinfo%%/*}"
    PGHOST="${_hostport%%:*}"
    PGPORT="${_hostport##*:}"
    PGDATABASE="${_hostinfo##*/}"
    PGDATABASE="${PGDATABASE%%\?*}"
    export PGPASSWORD
fi

PGHOST="${PGHOST:-${POSTGRES_HOST:-postgres}}"
PGPORT="${PGPORT:-${POSTGRES_PORT:-5432}}"
PGDATABASE="${PGDATABASE:-${POSTGRES_DB:-observatory}}"
PGUSER="${PGUSER:-${POSTGRES_USER:-observatory}}"
PGPASSWORD="${PGPASSWORD:-${POSTGRES_PASSWORD:-}}"
export PGPASSWORD

MINIO_ENDPOINT="${MINIO_ENDPOINT:-}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-minioadmin}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-minioadmin}"

LOCAL_FILE=""
TEMP_FILE=""

# ---------------------------------------------------------------------------
# Resolve the backup source
# ---------------------------------------------------------------------------
if [[ "${BACKUP_ARG}" == minio://* ]]; then
    # Parse minio://<bucket>/<object-path>
    _minio_path="${BACKUP_ARG#minio://}"
    _bucket="${_minio_path%%/*}"
    _object="${_minio_path#*/}"
    _filename="$(basename "${_object}")"

    [[ -n "${MINIO_ENDPOINT}" ]] || die "MINIO_ENDPOINT must be set to restore from MinIO"

    log "Downloading from MinIO: ${BACKUP_ARG}"
    TEMP_FILE="/tmp/${_filename}"

    MC_ALIAS="observatory_restore"
    mc alias set "${MC_ALIAS}" \
        "http://${MINIO_ENDPOINT}" \
        "${MINIO_ROOT_USER}" \
        "${MINIO_ROOT_PASSWORD}" \
        --quiet

    mc cp \
        "${MC_ALIAS}/${_bucket}/${_object}" \
        "${TEMP_FILE}" \
        --quiet

    LOCAL_FILE="${TEMP_FILE}"
    log "Downloaded to ${LOCAL_FILE}"
else
    LOCAL_FILE="${BACKUP_ARG}"
    [[ -f "${LOCAL_FILE}" ]] || die "File not found: ${LOCAL_FILE}"
fi

# ---------------------------------------------------------------------------
# Safety prompt (skip in CI / non-interactive sessions)
# ---------------------------------------------------------------------------
if [[ -t 0 ]]; then
    log "WARNING: This will DROP and recreate the database '${PGDATABASE}' on ${PGHOST}:${PGPORT}."
    read -r -p "Type 'yes' to continue: " _confirm
    [[ "${_confirm}" == "yes" ]] || die "Restore aborted by user"
fi

# ---------------------------------------------------------------------------
# Terminate existing connections so we can drop the database
# ---------------------------------------------------------------------------
log "Terminating active connections to '${PGDATABASE}'"
psql \
    --host="${PGHOST}" \
    --port="${PGPORT}" \
    --username="${PGUSER}" \
    --dbname="postgres" \
    --no-password \
    -c "SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = '${PGDATABASE}'
          AND pid <> pg_backend_pid();" \
    --quiet

# ---------------------------------------------------------------------------
# Drop and recreate the target database
# ---------------------------------------------------------------------------
log "Dropping database '${PGDATABASE}'"
psql \
    --host="${PGHOST}" \
    --port="${PGPORT}" \
    --username="${PGUSER}" \
    --dbname="postgres" \
    --no-password \
    -c "DROP DATABASE IF EXISTS \"${PGDATABASE}\";" \
    --quiet

log "Creating database '${PGDATABASE}'"
psql \
    --host="${PGHOST}" \
    --port="${PGPORT}" \
    --username="${PGUSER}" \
    --dbname="postgres" \
    --no-password \
    -c "CREATE DATABASE \"${PGDATABASE}\" OWNER \"${PGUSER}\";" \
    --quiet

# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------
log "Restoring from ${LOCAL_FILE}"
gunzip -c "${LOCAL_FILE}" \
    | psql \
        --host="${PGHOST}" \
        --port="${PGPORT}" \
        --username="${PGUSER}" \
        --dbname="${PGDATABASE}" \
        --no-password \
        --quiet

log "Restore complete"

# ---------------------------------------------------------------------------
# Clean up temp file if we downloaded from MinIO
# ---------------------------------------------------------------------------
if [[ -n "${TEMP_FILE}" && -f "${TEMP_FILE}" ]]; then
    rm -f "${TEMP_FILE}"
    log "Removed temp file ${TEMP_FILE}"
fi

log "Database '${PGDATABASE}' restored successfully from '${BACKUP_ARG}'"
