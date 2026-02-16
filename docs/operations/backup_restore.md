# Backup and Restore Operations

This document covers the complete backup and restore procedures for the PostgreSQL
database used by The Issue Observatory.  Backups are taken with `pg_dump`,
compressed with gzip, and stored in MinIO (S3-compatible object storage) under the
`observatory-backups` bucket using a date-partitioned path convention.

---

## Prerequisites

### Tools required on the host or inside a container

| Tool | Purpose |
|------|---------|
| `pg_dump` | Create the database dump (provided by `postgres:16-alpine`) |
| `psql` | Apply the dump during restore (provided by `postgres:16-alpine`) |
| Python 3.12+ | Run the backup/restore scripts |
| `minio>=7.2` | Python client for MinIO — installed via `pip install 'minio>=7.2,<8.0'` |

The `backup` Docker Compose service (profile `backup`) provides all of these
in the application image.

### Environment variables

All variables are read directly from the environment (or a `.env` file loaded by
Docker Compose).  No variables are read from the application `settings.py` at
runtime — the scripts are standalone.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | Full PostgreSQL DSN, e.g. `postgresql+asyncpg://user:pass@host:5432/db`. **Required.** |
| `MINIO_ENDPOINT` | — | MinIO host:port, e.g. `minio:9000`. **Required.** |
| `MINIO_ACCESS_KEY` | `minioadmin` | MinIO access key (falls back to `MINIO_ROOT_USER`). |
| `MINIO_SECRET_KEY` | `minioadmin` | MinIO secret key (falls back to `MINIO_ROOT_PASSWORD`). |
| `MINIO_BUCKET` | `observatory-backups` | Destination/source bucket. |
| `MINIO_SECURE` | `false` | Set to `true` to use TLS (HTTPS). |
| `BACKUP_RETENTION_DAYS` | `30` | MinIO objects older than this number of days are deleted. |

---

## Backup naming convention

Every backup is stored in MinIO under:

```
postgres/YYYY/MM/DD/observatory_YYYYMMDD_HHMMSS.sql.gz
```

For example:

```
postgres/2026/02/16/observatory_20260216_020000.sql.gz
```

---

## Running a manual backup

### Using Docker Compose (recommended)

From the project root:

```bash
docker compose --profile backup run --rm backup
```

This starts the `backup` service, runs `scripts/backup_postgres.py` once, and
removes the container on exit.  All output is JSON-structured and goes to stdout.

### Dry run — see what would happen without executing

```bash
docker compose --profile backup run --rm backup \
    python scripts/backup_postgres.py --dry-run
```

### Running directly on the host

Requires `pg_dump`, Python 3.12+, and the `minio` package installed:

```bash
pip install 'minio>=7.2,<8.0'

export DATABASE_URL="postgresql+asyncpg://observatory:observatory@localhost:5432/observatory"
export MINIO_ENDPOINT="localhost:9000"
export MINIO_ACCESS_KEY="minioadmin"
export MINIO_SECRET_KEY="minioadmin"

python scripts/backup_postgres.py
```

---

## Listing available backups

```bash
docker compose --profile backup run --rm backup \
    python scripts/restore_postgres.py --list
```

Or directly on the host:

```bash
export MINIO_ENDPOINT="localhost:9000"
export MINIO_ACCESS_KEY="minioadmin"
export MINIO_SECRET_KEY="minioadmin"

python scripts/restore_postgres.py --list
```

The command prints a human-readable table sorted newest first, for example:

```
Object name                                                             Size  Last modified
--------------------------------------------------------------------------------------------------------------
postgres/2026/02/16/observatory_20260216_020000.sql.gz           1,245,312  2026-02-16 02:00:04 UTC
postgres/2026/02/15/observatory_20260215_020000.sql.gz           1,241,088  2026-02-15 02:00:03 UTC
```

You can also browse backups via the MinIO web console at `http://localhost:9001`
(credentials from `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY`).

---

## Restoring from a specific backup

### Interactive restore (will prompt for confirmation)

```bash
docker compose --profile backup run --rm -it backup \
    python scripts/restore_postgres.py \
    --restore postgres/2026/02/16/observatory_20260216_020000.sql.gz
```

The script will print a warning and ask you to type `yes` before proceeding.

### Non-interactive restore (CI, automation)

```bash
docker compose --profile backup run --rm backup \
    python scripts/restore_postgres.py \
    --restore postgres/2026/02/16/observatory_20260216_020000.sql.gz \
    --yes
```

### What the restore script does

1. Downloads the `.sql.gz` file from MinIO to a temporary local file.
2. Terminates all active connections to the target database.
3. Drops and recreates the target database.
4. Decompresses the dump and pipes it into `psql` to restore all objects.
5. Removes the temporary file.

---

## Automated backup setup

Docker Compose does not have a native cron scheduler.  The recommended approach
is a **host-level cron job** that invokes the `backup` profile service.

### Host cron setup

Open the crontab on the host machine:

```bash
crontab -e
```

Add the following line to run the backup daily at **02:00 UTC**:

```cron
0 2 * * * cd /path/to/issue_observatory && \
  docker compose --profile backup run --rm backup >> /var/log/obs_backup.log 2>&1
```

Replace `/path/to/issue_observatory` with the absolute path to the project root.

### Verifying the cron job ran

Check the log file:

```bash
tail -f /var/log/obs_backup.log
```

The output is JSON-structured.  A successful run ends with:

```json
{"timestamp": "2026-02-16T02:00:05Z", "level": "INFO", "event": "backup_finished", "status": "success", "object_name": "postgres/2026/02/16/observatory_20260216_020000.sql.gz"}
```

---

## Retention policy

| Storage tier | Retention |
|-------------|-----------|
| MinIO current objects | `BACKUP_RETENTION_DAYS` (default: 30 days) |

The backup script automatically prunes MinIO objects under `postgres/` that are
older than `BACKUP_RETENTION_DAYS` at the end of every successful run.

To change retention, set `BACKUP_RETENTION_DAYS` in your `.env` or shell
environment before running the backup.  The new value takes effect on the next run.

---

## Testing the backup — restore to a test database

Use this procedure to verify that a backup is valid without touching the
production database.

### 1. Create a temporary test database

```bash
docker compose exec postgres psql -U observatory -c \
    "CREATE DATABASE observatory_restore_test OWNER observatory;"
```

### 2. Point DATABASE_URL at the test database and restore

```bash
docker compose --profile backup run --rm backup \
    sh -c "DATABASE_URL=postgresql+asyncpg://observatory:observatory@postgres:5432/observatory_restore_test \
           python scripts/restore_postgres.py \
           --restore postgres/2026/02/16/observatory_20260216_020000.sql.gz \
           --yes"
```

### 3. Verify row counts

Connect to the test database and compare row counts against production:

```bash
docker compose exec postgres psql -U observatory -d observatory_restore_test -c "
SELECT
    schemaname,
    relname        AS table_name,
    n_live_tup     AS row_count
FROM pg_stat_user_tables
ORDER BY n_live_tup DESC;
"
```

Run the same query against the production database and confirm the numbers match
(allow for rows written during the backup window).

### 4. Drop the test database

```bash
docker compose exec postgres psql -U observatory -c \
    "DROP DATABASE IF EXISTS observatory_restore_test;"
```

---

## MinIO credential rotation

This section describes how to rotate the MinIO access credentials without
losing any backup data.

**No downtime is required** — MinIO stores objects independently of which
credentials were used to write them.  Credential rotation only affects future
access.

### Procedure

1. **Generate new credentials** in the MinIO web console (`http://localhost:9001`)
   under Identity > Service Accounts, or via the MinIO admin API:

   ```bash
   mc admin user add obs_alias new_access_key new_secret_key
   mc admin policy attach obs_alias readwrite --user new_access_key
   ```

2. **Update `.env`** (or your secrets manager / Docker Secrets):

   ```dotenv
   MINIO_ACCESS_KEY=new_access_key
   MINIO_SECRET_KEY=new_secret_key
   ```

3. **Verify access** by running a dry-run backup with the new credentials:

   ```bash
   MINIO_ACCESS_KEY=new_access_key \
   MINIO_SECRET_KEY=new_secret_key \
   python scripts/backup_postgres.py --dry-run
   ```

4. **Run a live backup** to confirm the upload succeeds with the new credentials.

5. **Revoke the old credentials** in the MinIO web console or via `mc admin user remove`.

6. Record the rotation date and the operator identity in your change log.

---

## Rotating CREDENTIAL_ENCRYPTION_KEY

`CREDENTIAL_ENCRYPTION_KEY` is used by the application to encrypt platform API
credentials stored in the database (not related to MinIO backups).  Rotating it
requires a re-encryption migration and involves a maintenance window.

**Always take a verified backup before starting.**

### Procedure

1. **Take a verified backup** (follow the manual backup steps above and confirm the
   object appears in MinIO).

2. **Generate a new Fernet key**:

   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

3. **Stop application services** to prevent new credentials being written with the
   old key during migration:

   ```bash
   docker compose stop app worker beat
   ```

4. **Run the re-encryption migration script**
   (`scripts/reencrypt_credentials.py` — to be implemented by Core Infrastructure).
   The script must load every encrypted credential using the OLD key and re-encrypt
   it with the NEW key in a single transaction.

5. **Deploy with the new key** by updating `CREDENTIAL_ENCRYPTION_KEY` in your
   environment or secrets manager, then restart services:

   ```bash
   docker compose up -d app worker beat
   ```

6. **Verify** that credentials can be decrypted by running a smoke test against a
   known platform integration.

7. **Revoke the old key** in your secrets manager and remove it from all
   configuration.

Keep a record of the rotation date and the identity of the operator who performed it.

---

## Environment variable reference (complete)

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | Full async PostgreSQL DSN (required by backup and restore scripts) |
| `MINIO_ENDPOINT` | — | MinIO host:port, e.g. `minio:9000` |
| `MINIO_ACCESS_KEY` | `minioadmin` | MinIO access key (falls back to `MINIO_ROOT_USER`) |
| `MINIO_SECRET_KEY` | `minioadmin` | MinIO secret key (falls back to `MINIO_ROOT_PASSWORD`) |
| `MINIO_BUCKET` | `observatory-backups` | Bucket for backup storage |
| `MINIO_SECURE` | `false` | Use TLS when connecting to MinIO |
| `BACKUP_RETENTION_DAYS` | `30` | Prune MinIO objects older than this many days |
