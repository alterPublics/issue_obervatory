# Database & Data Processing Engineer — Status

## Migrations Ready

- [x] `001_initial_schema` — all core tables, indexes, and initial content_records partitions

## Models (Task 0.2 — COMPLETE)

- [x] `core/models/base.py` — `Base` (DeclarativeBase), `TimestampMixin`, `UserOwnedMixin`
- [x] `core/models/users.py` — `User`, `CreditAllocation`, `RefreshToken`
- [x] `core/models/content.py` — `UniversalContentRecord` (composite PK, partitioned by `published_at`)
- [x] `core/models/actors.py` — `Actor`, `ActorAlias`, `ActorPlatformPresence`, `ActorListMember`
- [x] `core/models/query_design.py` — `QueryDesign`, `SearchTerm`, `ActorList`
- [x] `core/models/collection.py` — `CollectionRun`, `CollectionTask`, `CreditTransaction`
- [x] `core/models/credentials.py` — `ApiCredential`
- [x] `core/models/__init__.py` — all models exported for Alembic discovery and application use
- [x] `core/database.py` — async engine, `AsyncSessionLocal`, `get_db()` FastAPI dependency

## Schema Notes

### content_records partitioning
The `content_records` table is RANGE-partitioned by `published_at`.  Because
Alembic autogenerate does not support `PARTITION BY`, the table is created via
raw DDL in `001_initial_schema.py`.  Do NOT use `alembic revision
--autogenerate` for changes to this table — write explicit migrations.

Initial partitions created:
- `content_records_2026_02` — February 2026
- `content_records_2026_03` — March 2026
- `content_records_2026_04` — April 2026
- `content_records_default` — catch-all for NULL / out-of-range dates

A rolling partition maintenance job should create partitions at least one month
ahead (see Phase 3 hardening tasks).

### Indexes on content_records
All indexes are created on the parent table and inherited by all partitions
(PostgreSQL 11+):

| Index | Type | Columns |
|-------|------|---------|
| `idx_content_platform` | B-tree | `platform` |
| `idx_content_arena` | B-tree | `arena` |
| `idx_content_published` | B-tree | `published_at` |
| `idx_content_query` | B-tree | `query_design_id` |
| `idx_content_hash` | B-tree | `content_hash` |
| `idx_content_author` | B-tree | `author_id` |
| `idx_content_terms` | GIN | `search_terms_matched` |
| `idx_content_metadata` | GIN | `raw_metadata` |
| `idx_content_fulltext` | GIN | `to_tsvector('danish', ...)` |

### FK dependency order (create order)
users → credit_allocations, refresh_tokens → api_credentials → actors →
actor_aliases, actor_platform_presences → query_designs → search_terms,
actor_lists → actor_list_members → collection_runs → collection_tasks,
credit_transactions → content_records

## Credit Service (Task 0.8 — COMPLETE)

- [x] `core/credit_service.py` — `CreditService` class and `get_credit_service()` dependency

### CreditService implementation notes

Balance formula implemented as four separate aggregation queries (avoids a
complex CASE-based single query that is harder to audit and extend):

  available = total_allocated - reserved - settled + refunded

All `CreditAllocation` validity checks use `valid_from <= today` AND
`(valid_until IS NULL OR valid_until >= today)` computed in UTC.

Write methods (`reserve`, `settle`, `refund`) commit immediately and catch
database exceptions, wrapping them in `CreditReservationError` with the
`collection_run_id` for structured error tracking in `collection_tasks`.

`settle()` automatically calls `refund()` for any surplus between reserved
and actual credits, so callers do not need to manually issue a refund on
under-consumption.

`estimate()` lazy-imports the arena registry and `TIER_DEFAULTS` to avoid
circular imports.  Unknown arenas (registry `KeyError`) fall back to
`TIER_DEFAULTS[resolved_tier].estimated_credits_per_1k`.  Arenas whose
`estimate_credits()` raises are logged at WARNING and default to 0.

`get_transaction_history()` uses keyset pagination over
`(created_at DESC, id DESC)` with a hard cap of 200 rows per page.

## Automated Backup (Task 0.11 — COMPLETE)

### Deliverables

- [x] `scripts/backup_postgres.py` — standalone Python backup script
- [x] `scripts/restore_postgres.py` — restore script with `--list` and `--restore` flags
- [x] `docker-compose.yml` `backup` service — profile-gated, exits after one run
- [x] `docs/operations/backup_restore.md` — complete runbook (replaced shell-based version)
- [x] `pyproject.toml` — added `minio>=7.2,<8.0` dependency

### Design decisions

**Python over shell**: The new scripts replace the prior `backup_postgres.sh` /
`restore_postgres.sh`.  Python gives structured JSON logging (consistent with
`structlog` used by the application), proper exit codes, `--dry-run` support, and
testability.  The shell scripts are retained for reference but are no longer
invoked by the Docker service.

**`minio` Python client over `boto3`**: The `minio` package is significantly
lighter than `boto3` (no AWS SDK dependency tree).  It exposes the full MinIO
API, including object listing with metadata needed for retention pruning.

**Backup naming convention**: `postgres/YYYY/MM/DD/observatory_YYYYMMDD_HHMMSS.sql.gz`.
Date-partitioned paths allow MinIO to list backups for a specific day without
scanning all objects.

**Retention pruning**: Performed at the end of every backup run.  Iterates all
objects under `postgres/` and deletes those with `last_modified < now - retention_days`.
Pruning failures emit `WARNING` and do not fail the backup run.

**Credential fallback**: `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` take precedence;
both scripts fall back to `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` for backward
compatibility with the existing Docker Compose environment.

**Docker Compose cron**: The `backup` service uses `profiles: [backup]` so it
never starts with `docker compose up`.  Scheduling is delegated to a host cron
job (`0 2 * * * docker compose --profile backup run --rm backup`) — see
`docs/operations/backup_restore.md` for the full setup.

### Environment variables consumed

| Variable | Default |
|----------|---------|
| `DATABASE_URL` | required |
| `MINIO_ENDPOINT` | required |
| `MINIO_ACCESS_KEY` | `minioadmin` (or `MINIO_ROOT_USER`) |
| `MINIO_SECRET_KEY` | `minioadmin` (or `MINIO_ROOT_PASSWORD`) |
| `MINIO_BUCKET` | `observatory-backups` |
| `MINIO_SECURE` | `false` |
| `BACKUP_RETENTION_DAYS` | `30` |

## Analysis Module

- [ ] Descriptive statistics (`analysis/descriptive.py`)
- [ ] Network analysis (`analysis/network.py`)
- [ ] Export: CSV, GEXF, JSON, Parquet (`analysis/export.py`)
