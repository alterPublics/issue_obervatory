#!/usr/bin/env bash
# MinIO initialization script for The Issue Observatory.
# Runs once when the minio-init container starts (after MinIO is healthy).
#
# Actions performed:
#   1. Wait for MinIO API to become healthy.
#   2. Configure mc alias pointing at the MinIO instance.
#   3. Create the main bucket if it does not exist.
#   4. Enable bucket versioning to protect against accidental deletion.
#   5. Set a lifecycle policy: expire old non-current versions after 90 days.
#   6. Confirm the /backups/ prefix exists (MinIO is prefix-based, so this is
#      informational — the actual prefix is created on first upload).
#
# Environment variables:
#   MINIO_ENDPOINT        Host and port, e.g. minio:9000 (default: minio:9000)
#   MINIO_ROOT_USER       MinIO root access key (default: minioadmin)
#   MINIO_ROOT_PASSWORD   MinIO root secret key (default: minioadmin)
#   MINIO_BUCKET          Bucket to create (default: observatory-backups)

set -euo pipefail

log()  { printf '[%s] INFO  %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }
err()  { printf '[%s] ERROR %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >&2; }
die()  { err "$*"; exit 1; }

MINIO_ENDPOINT="${MINIO_ENDPOINT:-minio:9000}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-minioadmin}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-minioadmin}"
MINIO_BUCKET="${MINIO_BUCKET:-observatory-backups}"

MC_ALIAS="observatory"
MINIO_URL="http://${MINIO_ENDPOINT}"

# ---------------------------------------------------------------------------
# 1. Wait for MinIO to be healthy (up to 120 s)
# ---------------------------------------------------------------------------
log "Waiting for MinIO at ${MINIO_URL} ..."
RETRIES=24
SLEEP=5

for i in $(seq 1 "${RETRIES}"); do
    if curl -sf "${MINIO_URL}/minio/health/live" > /dev/null 2>&1; then
        log "MinIO is healthy"
        break
    fi
    if [[ "${i}" -eq "${RETRIES}" ]]; then
        die "MinIO did not become healthy after $((RETRIES * SLEEP))s"
    fi
    log "  Attempt ${i}/${RETRIES} — retrying in ${SLEEP}s ..."
    sleep "${SLEEP}"
done

# ---------------------------------------------------------------------------
# 2. Configure mc alias
# ---------------------------------------------------------------------------
log "Configuring mc alias '${MC_ALIAS}' -> ${MINIO_URL}"
mc alias set "${MC_ALIAS}" \
    "${MINIO_URL}" \
    "${MINIO_ROOT_USER}" \
    "${MINIO_ROOT_PASSWORD}" \
    --quiet

# ---------------------------------------------------------------------------
# 3. Create bucket if it does not exist
# ---------------------------------------------------------------------------
if mc ls "${MC_ALIAS}/${MINIO_BUCKET}" > /dev/null 2>&1; then
    log "Bucket '${MINIO_BUCKET}' already exists — skipping creation"
else
    log "Creating bucket '${MINIO_BUCKET}'"
    mc mb "${MC_ALIAS}/${MINIO_BUCKET}" --quiet
    log "Bucket created"
fi

# ---------------------------------------------------------------------------
# 4. Enable versioning
# ---------------------------------------------------------------------------
log "Enabling versioning on '${MINIO_BUCKET}'"
mc version enable "${MC_ALIAS}/${MINIO_BUCKET}" --quiet
log "Versioning enabled"

# ---------------------------------------------------------------------------
# 5. Set lifecycle policy: expire non-current versions after 90 days
# ---------------------------------------------------------------------------
log "Applying lifecycle policy (non-current versions expire after 90 days)"

# Write the policy JSON to a temp file so mc can read it.
POLICY_FILE="$(mktemp /tmp/minio-lifecycle-XXXXXX.json)"
trap 'rm -f "${POLICY_FILE}"' EXIT

cat > "${POLICY_FILE}" <<'EOF'
{
  "Rules": [
    {
      "ID": "expire-old-versions",
      "Status": "Enabled",
      "Filter": {
        "Prefix": ""
      },
      "NoncurrentVersionExpiration": {
        "NoncurrentDays": 90
      }
    }
  ]
}
EOF

mc ilm import "${MC_ALIAS}/${MINIO_BUCKET}" < "${POLICY_FILE}" --quiet
log "Lifecycle policy applied"

# ---------------------------------------------------------------------------
# 6. Informational: confirm backups prefix
# ---------------------------------------------------------------------------
log "Bucket '${MINIO_BUCKET}' is ready."
log "PostgreSQL dumps will be stored under: ${MC_ALIAS}/${MINIO_BUCKET}/backups/"
log "MinIO initialization complete"
