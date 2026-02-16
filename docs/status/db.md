# Database & Data Processing Engineer — Status

## Migrations Ready

- [x] `001_initial_schema` — all core tables, indexes, and initial content_records partitions
- [x] `002_add_arenas_config_to_query_designs` — adds `arenas_config JSONB NOT NULL DEFAULT '{}'` to `query_designs`; arena-config API endpoints now read/write this column directly instead of the `collection_runs` workaround

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
- [x] Export: CSV, XLSX, GEXF, JSON (NDJSON), Parquet (`analysis/export.py`) — Task 3.3 COMPLETE

## Export Module (Task 3.3 — COMPLETE)

### Deliverables

- [x] `analysis/export.py` — `ContentExporter` class with five format methods
- [x] `api/routes/content.py` — four export endpoints added to the content router
- [x] `workers/export_tasks.py` — `export_content_records` Celery task (async large export)
- [x] `workers/celery_app.py` — export task module registered in `include` list
- [x] `pyproject.toml` — `openpyxl>=3.1,<4.0` and `pyarrow>=15.0,<16.0` added to main dependencies

### ContentExporter (`analysis/export.py`)

All five serialization methods are `async` and return raw `bytes`:

| Method | Format | Notes |
|--------|--------|-------|
| `export_csv()` | UTF-8 CSV with BOM | Optional `include_metadata` adds `raw_metadata` JSONB as JSON string column |
| `export_xlsx()` | XLSX (openpyxl) | Danish-safe (æøå); bold/frozen header; auto-sized columns; `openpyxl>=3.1` required |
| `export_json()` | NDJSON | One JSON object per line; UUID and datetime serialized; suitable for streaming |
| `export_parquet()` | Parquet (pyarrow) | Schema-typed: string/int64/timestamp columns; `pyarrow>=15.0` required |
| `export_gexf()` | GEXF 1.3 XML | Actor co-occurrence network; nodes = `pseudonymized_author_id`; edges = shared collection run; `weight` and `shared_terms` edge attributes |

Column set (CSV/XLSX/Parquet flat columns): `platform, arena, content_type, title, text_content, url, author_display_name, published_at, views_count, likes_count, shares_count, comments_count, language, collection_tier, search_terms_matched`.

### Export Endpoints (`api/routes/content.py`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/content/export` | GET | Synchronous export, up to 10 000 records, returns file directly |
| `/content/export/async` | POST | Dispatches Celery task, returns `{"job_id": UUID, "status": "pending"}` |
| `/content/export/{job_id}/status` | GET | Reads Redis key `export:{job_id}:status` |
| `/content/export/{job_id}/download` | GET | Generates fresh 1-hour MinIO pre-signed URL and redirects (HTTP 307) |

All export endpoints require authentication (`get_current_active_user`).
Ownership scoping: non-admin users can only export from their own collection runs
(via `collection_runs.initiated_by` sub-query, same pattern as browse endpoint).
Admin users bypass ownership scope and can export all records.

Supported query parameters (all endpoints): `format`, `platform`, `arena`,
`query_design_id`, `date_from`, `date_to`, `language`, `run_id`, `search_term`.
Sync endpoint additionally accepts `limit` (max 10 000) and `include_metadata`.

### Celery Task (`workers/export_tasks.py`)

Task name: `export_content_records` (bound task, `bind=True`).

Lifecycle:
1. Writes `{"status": "pending"}` to Redis before task starts (set by route handler).
2. Task start: sets `{"status": "running", "pct_complete": 0}`.
3. After DB query: `{"status": "running", "pct_complete": 50}`.
4. After serialization: `{"status": "running", "pct_complete": 80}`.
5. After MinIO upload: `{"status": "complete", "pct_complete": 100, "record_count": N, "object_key": "...", "download_url": "<1-hour presigned>", "completed_at": "..."}`.
6. On any failure: `{"status": "failed", "error": "<message>"}`.

Redis TTL: 24 hours (`_STATUS_TTL = 86_400`).

Database access inside the task uses `psycopg2` (synchronous) with a named
server-side cursor (`fetchmany(1000)`) to avoid loading large result sets into
memory. The asyncpg DSN is converted to a psycopg2 DSN by stripping the
`+asyncpg` scheme prefix.

MinIO object path: `exports/{user_id}/{job_id}.{ext}`.
The download endpoint regenerates a fresh pre-signed URL on every call using
`minio.presigned_get_object(..., expires=timedelta(hours=1))`.

### Dependencies added

| Package | Version | Purpose |
|---------|---------|---------|
| `openpyxl` | `>=3.1,<4.0` | XLSX export; write-optimized, handles Danish characters natively |
| `pyarrow` | `>=15.0,<16.0` | Parquet export; typed columnar schema |

Both raise `ImportError` with an install hint if not available — guards exist
but should never trigger in production since both are in main dependencies.
