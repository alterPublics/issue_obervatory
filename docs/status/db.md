# Database & Data Processing Engineer — Status

## Migrations Ready

- [x] `001_initial_schema` — all core tables, indexes, and initial content_records partitions
- [x] `002_add_arenas_config_to_query_designs` — adds `arenas_config JSONB NOT NULL DEFAULT '{}'` to `query_designs`; arena-config API endpoints now read/write this column directly instead of the `collection_runs` workaround
- [x] `003_add_suspended_at_to_collection_runs` — adds `suspended_at TIMESTAMPTZ` column to `collection_runs`
- [x] `004_add_scraping_jobs` — creates `scraping_jobs` table and `idx_content_collection_run` index on `content_records`
- [x] `005_add_content_annotations` — creates `content_annotations` table (IP2-043)
- [x] `006_add_search_term_groups` — adds `group_id UUID NULL` and `group_label VARCHAR(200) NULL` to `search_terms` with `idx_search_term_group` B-tree index (Item 14)
- [x] `007_add_simhash_to_content_records` — adds `simhash BIGINT NULL` to `content_records` (partitioned; uses raw ALTER TABLE DDL) with `idx_content_records_simhash` B-tree index (Item 15)
- [x] `008_add_query_design_cloning` — adds `parent_design_id UUID NULL REFERENCES query_designs(id) ON DELETE SET NULL` with `idx_query_design_parent` B-tree index (IP2-051)
- [x] `009_add_public_figure_flag_to_actors` — adds `public_figure BOOLEAN NOT NULL DEFAULT false` to `actors`; GDPR Art. 89(1) research exemption for public-figure pseudonymization bypass (GR-14)
- [x] `010_add_target_arenas_to_search_terms` — adds `target_arenas JSONB NULL` to `search_terms`; implements YF-01 per-arena search term scoping (2026-02-19)

## Models (Task 0.2 — COMPLETE)

- [x] `core/models/base.py` — `Base` (DeclarativeBase), `TimestampMixin`, `UserOwnedMixin`
- [x] `core/models/users.py` — `User`, `CreditAllocation`, `RefreshToken`
- [x] `core/models/content.py` — `UniversalContentRecord` (composite PK, partitioned by `published_at`)
- [x] `core/models/actors.py` — `Actor`, `ActorAlias`, `ActorPlatformPresence`, `ActorListMember`
- [x] `core/models/query_design.py` — `QueryDesign`, `SearchTerm`, `ActorList`
- [x] `core/models/collection.py` — `CollectionRun`, `CollectionTask`, `CreditTransaction`
- [x] `core/models/credentials.py` — `ApiCredential`
- [x] `core/models/annotations.py` — `ContentAnnotation` (IP2-043)
- [x] `core/models/__init__.py` — all models exported for Alembic discovery and application use
- [x] `core/database.py` — async engine, `AsyncSessionLocal`, `get_db()` FastAPI dependency

## Content Annotation Layer (IP2-043 — COMPLETE)

### Deliverables

- [x] `core/models/annotations.py` — `ContentAnnotation` ORM model
- [x] `core/models/__init__.py` — `ContentAnnotation` exported
- [x] `alembic/versions/005_add_content_annotations.py` — reversible migration
- [x] `api/routes/annotations.py` — GET / POST / DELETE endpoints under `/annotations`
- [x] `api/main.py` — annotations router registered at `/annotations`
- [x] `api/templates/content/record_detail.html` — annotation panel widget

### Schema design notes

**No FK to `content_records`**: `content_records` is range-partitioned with a
composite PK `(id, published_at)`.  PostgreSQL requires FK references to match
the full composite PK.  A FK on just `content_record_id` would fail; a FK on
both columns would couple `content_annotations` tightly to the partitioning
scheme.  Instead, `(content_record_id, content_published_at)` are stored as a
logical reference without a DB-level constraint.  The unique constraint on
`(created_by, content_record_id, content_published_at)` is the integrity
mechanism — orphaned annotations are detectable by a maintenance query.

**`created_by` uses `ON DELETE SET NULL`**: Unlike `ScrapingJob` (which uses
`CASCADE`), annotations survive user deletion.  This preserves the research
data produced by a researcher account even after that account is removed,
which is important for shared study datasets and audit trails.

**`TimestampMixin` without `UserOwnedMixin`**: `UserOwnedMixin` adds `owner_id`
with `ON DELETE RESTRICT`, which prevents user deletion while annotations exist.
The annotation model uses `TimestampMixin` + an explicit `created_by` column
with `SET NULL` instead, following the same pattern as `ScrapingJob`.

**`tags` as JSONB array**: A GIN index (`idx_annotation_tags`) supports fast
containment queries (`tags @> '["climate"]'`).  Stored as `list[str]` in the ORM.

**Stance vocabulary**: Validated at the application layer (not a DB CHECK
constraint) so that the allowed terms can evolve without a schema migration.
Current vocabulary: `positive`, `negative`, `neutral`, `contested`, `irrelevant`.

### Indexes on `content_annotations`

| Index | Type | Column(s) |
|-------|------|-----------|
| `uq_annotation_user_record` (UNIQUE) | B-tree | `created_by, content_record_id, content_published_at` |
| `idx_annotation_created_by` | B-tree | `created_by` |
| `idx_annotation_content_record` | B-tree | `content_record_id` |
| `idx_annotation_published_at` | B-tree | `content_published_at` |
| `idx_annotation_run` | B-tree | `collection_run_id` |
| `idx_annotation_qd` | B-tree | `query_design_id` |
| `idx_annotation_tags` | GIN | `tags` |

### API endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/annotations/{record_id}?published_at=...` | GET | Returns current user's annotation or `{"annotation": null}` |
| `/annotations/{record_id}` | POST | Upsert annotation (body: stance, frame, is_relevant, notes, tags, published_at, ...) |
| `/annotations/{record_id}?published_at=...` | DELETE | Delete current user's annotation |

All routes require `get_current_active_user`.  Researchers can only read/modify
their own annotations.  Admins can delete any annotation.

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

- [x] Descriptive statistics (`analysis/descriptive.py`) — Task 3.1 COMPLETE
- [x] Network analysis (`analysis/network.py`) — Task 3.2 COMPLETE
- [x] Export: CSV, XLSX, GEXF, JSON (NDJSON), Parquet (`analysis/export.py`) — Task 3.3 COMPLETE
- [x] Cross-arena near-duplicate deduplication (`core/deduplication.py`) — Task 3.8 COMPLETE
- [x] Entity resolution: fuzzy actor matching + merge/split (`core/entity_resolver.py`) — Task 3.9 COMPLETE
- [x] B-02 FIXED: GEXF export extended to support three network types — Task 3.3 Phase-3 fix COMPLETE
- [x] IP2-004 / IP2-024: Shared filter builder `_filters.py` created; duplicate exclusion added to all analysis queries — Phase A COMPLETE
- [x] IP2-005: `_FLAT_COLUMNS` extended with `pseudonymized_author_id`, `content_hash`, `collection_run_id`, `query_design_id` — Phase A COMPLETE
- [x] IP2-006: `_COLUMN_HEADERS` dict added; CSV/XLSX header rows now use human-readable labels; JSON format relabelled to "NDJSON (one record per line)" in analysis template — Phase A COMPLETE
- [x] IP2-025: GEXF builders refactored to consume graph dicts from `network.py` rather than reconstructing networks from flat records — Phase A COMPLETE
- [x] IP2-047: Per-arena GEXF export — `arena` parameter added to `get_actor_co_occurrence()`, `get_term_co_occurrence()`, `build_bipartite_network()` in `network.py`; corresponding `?arena=` query parameters added to `/network/actors`, `/network/terms`, and `/network/bipartite` API endpoints; `export_gexf()` docstring updated — Phase C COMPLETE
- [x] IP2-049: Named entity extraction stub (Step 1) — `NamedEntityExtractor` stub class created in `analysis/enrichments/named_entity_extractor.py`; storage contract defined (`raw_metadata.enrichments.actor_roles`); `nlp-ner` optional dependency group added to `pyproject.toml`; enricher exported from `enrichments/__init__.py` — Phase C Step 1 COMPLETE
- [x] Item 15: SimHash near-duplicate detection — `compute_simhash()`, `hamming_distance()`, `find_near_duplicates()` added to `core/deduplication.py`; `detect_and_mark_near_duplicates()` added to `DeduplicationService`; `simhash` field added to `UniversalContentRecord` ORM model and normalizer output — Phase D COMPLETE
- [x] IP2-051: Query design cloning — `parent_design_id` added to `QueryDesign` model; `POST /query-designs/{design_id}/clone` endpoint added with deep-copy of search terms and actor lists — Phase D COMPLETE
- [x] IP2-055: Filtered export — `GET /analysis/{run_id}/filtered-export` endpoint with format/platform/arena/date/search_term/top_actors/min_engagement filters; "Export filtered records" section added to analysis dashboard — Phase D COMPLETE
- [x] IP2-056: RIS/BibTeX export — `export_ris()` and `export_bibtex()` methods added to `ContentExporter`; both formats added to `/content/export` and `/analysis/{run_id}/filtered-export`; format selector in analysis dashboard now shows RIS and BibTeX options with tooltips — Phase D COMPLETE
- [x] IP2-053: Suggested terms — `GET /analysis/{run_id}/suggested-terms` endpoint added returning emergent terms not yet in query design; "Suggested terms" panel with "Add to query design" HTMX button added to analysis dashboard — Phase D COMPLETE

## Descriptive Statistics (Task 3.1 — COMPLETE)

### Deliverables

- [x] `analysis/descriptive.py` — five async query functions and `DescriptiveStats` dataclass
- [x] `analysis/__init__.py` — all public symbols exported

### Functions

| Function | Returns | Notes |
|----------|---------|-------|
| `get_volume_over_time()` | `list[dict]` | `date_trunc(granularity, published_at)` grouped by period + arena; granularity validated against allowlist before string interpolation |
| `get_top_actors()` | `list[dict]` | Groups by `pseudonymized_author_id + author_display_name + platform`; engagement = `COALESCE(likes,0) + COALESCE(shares,0) + COALESCE(comments,0)` |
| `get_top_terms()` | `list[dict]` | `unnest(search_terms_matched)` with GROUP BY; uses GIN index on `search_terms_matched` |
| `get_engagement_distribution()` | `dict` | `percentile_cont(0.5)` and `percentile_cont(0.95) WITHIN GROUP` for median and p95; single-row aggregation query |
| `get_run_summary()` | `dict` | Three queries: run metadata from `collection_runs`, totals from `content_records`, per-arena breakdown via RIGHT JOIN on `collection_tasks` |

### Design decisions

- `date_trunc` granularity is validated against a `frozenset` before f-string interpolation — safe against injection.
- Bind parameters for UUID values are cast to `str` to satisfy asyncpg's strict type handling.
- `DescriptiveStats` dataclass provides a typed container for the API layer without requiring Pydantic (avoids an import dependency from the analysis layer into the API layer).
- All datetime values in returned dicts are ISO 8601 strings via `_dt_iso()` helper.
- `get_volume_over_time()` returns one dict per time period (not per period×arena row) — per-arena counts are nested under an `arenas` sub-dict for convenient frontend consumption.

## Network Analysis (Task 3.2 — COMPLETE)

### Deliverables

- [x] `analysis/network.py` — four async network construction functions
- [x] `analysis/__init__.py` — all public symbols exported

### Functions

| Function | Returns | Notes |
|----------|---------|-------|
| `get_actor_co_occurrence()` | `dict` (graph) | Self-join on `content_records` using `&&` array overlap operator; two separate queries (nodes via CTE, edges standalone) to avoid CTE materialisation issues |
| `get_term_co_occurrence()` | `dict` (graph) | Double `unnest` with `t1.term < t2.term` predicate to deduplicate pairs; CTE chain: `term_pairs → node_ids → term_freq` |
| `get_cross_platform_actors()` | `list[dict]` | Joins `content_records` with `actors`; requires non-null `author_id` (entity resolution prerequisite); uses `array_agg(DISTINCT … ORDER BY …)` |
| `build_bipartite_network()` | `dict` (graph) | Single aggregation query; term node IDs prefixed with `"term:"` to avoid collision with actor IDs; actor and term nodes distinguished by `type` attribute |

### Graph dict format (shared)

```json
{
  "nodes": [{"id": "...", "label": "...", "type": "actor|term", ...}],
  "edges": [{"source": "...", "target": "...", "weight": N}]
}
```

### Design decisions

- **SQL-side co-occurrence**: All pair computation happens in PostgreSQL via self-joins and `unnest` — Python only assembles the final graph dict. This avoids loading O(N²) intermediate pairs into memory.
- **Degree computation in Python**: Node degrees are computed from the edge list in Python after the SQL fetch. This is O(E) and avoids a second aggregation query.
- **`LEAST/GREATEST` trick**: Used to canonicalize undirected pairs `(a, b)` = `(b, a)` without a self-join deduplication subquery.
- **`&&` operator**: The GIN index on `search_terms_matched` is used by the array overlap operator in `get_actor_co_occurrence`. The query planner will use `idx_content_terms` for both sides of the self-join if `query_design_id` or `collection_run_id` filters are applied first.
- **Empty result handling**: All functions return `{"nodes": [], "edges": []}` (or `[]`) on empty result sets without raising exceptions.
- **b-side parameter renaming**: In `get_actor_co_occurrence`, filter parameters for the b-side of the self-join are renamed with a `_b` suffix at runtime to avoid bind-parameter name collisions.

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
| `export_gexf(graph, network_type="actor")` | GEXF 1.3 XML | Accepts a graph dict from `network.py`; dispatches to one of three GEXF serializers (IP2-025 refactor; see B-02 fix below) |

#### B-02 Fix — Three GEXF network types (2026-02-17)

`export_gexf()` now accepts a `network_type` parameter with three values:

| `network_type` | Description | GEXF nodes | GEXF edges |
|----------------|-------------|-----------|-----------|
| `"actor"` (default) | Actor co-occurrence: authors linked by shared search terms | `id=pseudonymized_author_id`, attrs: `display_name`, `platform`, `total_posts` | `weight=distinct_shared_terms`, attr: `shared_terms` (pipe-joined) |
| `"term"` | Term co-occurrence: search terms linked by same-record co-appearance | `id=term_string`, attrs: `type="term"`, `frequency` | `weight=co_occurrence_count` |
| `"bipartite"` | Bipartite actor-term: authors linked to terms they matched | Actor nodes: `type="actor"`; Term nodes: `id="term:{term}"`, `type="term"` | `source=author_id`, `target="term:{term}"`, `weight=record_count` |

All three types:
- Use GEXF 1.3 namespace (`xmlns="http://gexf.net/1.3"`)
- Include `<meta>` block with `creator`, `description`, `lastmodifieddate`
- Declare `<attributes class="node">` and `<attributes class="edge">` with typed attribute declarations
- Produce valid, indented UTF-8 XML with `<?xml version="1.0" encoding="UTF-8"?>` declaration

Internal structure refactored: `_make_gexf_root()` and `_serialize_gexf()` are shared static helpers; `_build_actor_gexf()`, `_build_term_gexf()`, and `_build_bipartite_gexf()` are the three private constructors; `export_gexf()` dispatches based on `network_type`.

Both export endpoints (`GET /content/export` and `POST /content/export/async`) now accept a `network_type` query parameter (default: `"actor"`).  The Celery task reads `network_type` from the `filters` dict and passes it through.  Invalid `network_type` values for GEXF format raise HTTP 400 before the task is dispatched.

The three download buttons in `analysis/index.html` now use distinct hrefs:
- Actor: `?format=gexf&network_type=actor&run_id=...`
- Term: `?format=gexf&network_type=term&run_id=...`
- Bipartite: `?format=gexf&network_type=bipartite&run_id=...`

Column set (CSV/XLSX/Parquet flat columns — updated Phase A IP2-005): `platform, arena, content_type, title, text_content, url, author_display_name, pseudonymized_author_id, published_at, views_count, likes_count, shares_count, comments_count, language, collection_tier, search_terms_matched, content_hash, collection_run_id, query_design_id`.

Human-readable headers (IP2-006): CSV and XLSX header rows are written from `_COLUMN_HEADERS` — e.g. `author_display_name` → "Author", `pseudonymized_author_id` → "Author ID (Pseudonymized)", `search_terms_matched` → "Matched Search Terms".

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

## Cross-Arena Near-Duplicate Deduplication (Task 3.8 — COMPLETE)

### Deliverables

- [x] `core/deduplication.py` — `DeduplicationService` class + `normalise_url()` pure function
- [x] `workers/maintenance_tasks.py` — `deduplicate_run` Celery task
- [x] `workers/celery_app.py` — maintenance task module registered in `include` list
- [x] `api/routes/content.py` — two new endpoints: `POST /content/deduplicate` and `GET /content/duplicates`

### DeduplicationService (`core/deduplication.py`)

| Method | Description |
|--------|-------------|
| `normalise_url(url)` | Pure function: lowercase, strip `www.`, strip 10 tracking params (`utm_*`, `fbclid`, `gclid`, `ref`, `source`, `_ga`), strip trailing slash, re-sort query string |
| `find_url_duplicates(db, run_id, query_design_id)` | Group records by normalised URL; return groups with > 1 record |
| `find_hash_duplicates(db, run_id, query_design_id)` | Group records by `content_hash`; return only groups where platform or arena differs |
| `mark_duplicates(db, canonical_id, duplicate_ids)` | Set `raw_metadata['duplicate_of'] = str(canonical_id)` via `jsonb_set(coalesce(...))` |
| `run_dedup_pass(db, run_id)` | Run URL pass then hash pass; elect canonical as lowest UUID; commit; return summary dict |

### Design decisions

- URL normalisation is a pure Python function using only `urllib.parse` — no new dependencies.
- Grouping is performed in Python after a single SELECT to avoid pushing normalisation logic into SQL, which simplifies testing.
- Canonical election uses `min(UUID)` (lowest UUID value) — deterministic and reproducible without consulting engagement scores on the hot path.
- `mark_duplicates` uses `jsonb_set(coalesce(raw_metadata, '{}'), ...)` rather than `||` merge to avoid overwriting sibling keys and to work correctly when `raw_metadata` is NULL.
- The Celery task (`maintenance_tasks.py`) re-implements the core logic with psycopg2 (synchronous) to avoid running asyncio inside a Celery worker.

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/content/deduplicate?run_id={uuid}` | POST | Dispatches `deduplicate_run` Celery task; returns `{"job_id": ..., "status": "pending"}` |
| `/content/duplicates?run_id={uuid}` | GET | Runs sync URL + hash detection; returns both group lists as JSON |

## Entity Resolution: Fuzzy Actor Matching + Merge/Split (Task 3.9 — COMPLETE)

### Deliverables

- [x] `core/entity_resolver.py` — Phase 3.9 methods added to `EntityResolver`
- [x] `api/routes/actors.py` — three new endpoints: candidates, merge, split
- [x] `api/templates/actors/detail.html` — collapsible Entity Resolution section

### EntityResolver Phase 3.9 methods

| Method | Description |
|--------|-------------|
| `find_candidate_matches(db, actor_id, threshold)` | Three-strategy matching: exact name → shared username → pg_trgm similarity. Enables `pg_trgm` via `CREATE EXTENSION IF NOT EXISTS` before similarity query. Returns candidates enriched with platform list. |
| `merge_actors(db, canonical_id, duplicate_ids, performed_by)` | Re-points `content_records.author_id`, moves presences (skips conflicts), creates `ActorAlias` entries, deletes duplicate actors. |
| `split_actor(db, actor_id, presence_ids, new_canonical_name, performed_by)` | Creates new `Actor`, moves presences, re-points `content_records` by `author_platform_id`, adds alias on original actor. |

### pg_trgm dependency note

`find_candidate_matches` executes `CREATE EXTENSION IF NOT EXISTS pg_trgm` immediately before the similarity query. This is idempotent and requires no migration. If the PostgreSQL user lacks `CREATE EXTENSION` privileges in production, a DBA must run it once manually:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

### API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/actors/{id}/candidates` | GET | read access | Returns fuzzy match candidates with similarity scores; HTMX returns HTML table fragment |
| `/actors/{id}/merge` | POST | ownership or admin | Body: `{"duplicate_ids": [...]}` |
| `/actors/{id}/split` | POST | ownership or admin | Body: `{"presence_ids": [...], "new_canonical_name": "..."}` |

### UI (actors/detail.html)

A collapsible "Entity Resolution" section is appended at the bottom of the actor detail page.

- "Search for duplicates" button triggers `GET /actors/{id}/candidates` via HTMX and renders a candidate table with Merge buttons per row.
- Merge buttons use an Alpine confirm dialog before posting to `POST /actors/{id}/merge`.
- Split section renders checkboxes for each platform presence and a new actor name input; form handled via Alpine `fetch` to `POST /actors/{id}/split`.
- All UI interactions are handled by the `entityResolution()` Alpine component injected via inline `<script>`.

## GR-14: Public Figure Pseudonymization Exception (COMPLETE — schema/API layer)

**Status**: DB schema and API layer complete. Normalizer and frontend changes outstanding (see below).

### What was implemented

| File | Change |
|------|--------|
| `src/issue_observatory/core/models/actors.py` | Added `public_figure: Mapped[bool]` column with `server_default=false` and full GDPR comment |
| `alembic/versions/009_add_public_figure_flag_to_actors.py` | Reversible migration; adds `public_figure BOOLEAN NOT NULL DEFAULT false` to `actors` |
| `src/issue_observatory/core/schemas/actors.py` | `public_figure: bool` added to `ActorCreate`, `ActorUpdate`, and `ActorResponse` |
| `src/issue_observatory/api/routes/actors.py` | `public_figure=payload.public_figure` passed through in `create_actor` handler |

### Schema design notes

- `server_default=false`: every existing actor continues to be pseudonymized on migration; no back-fill required.
- No index on `public_figure`: the flag will be checked by the normalizer via a direct actor lookup (join on `author_platform_id`), not via a standalone query on this column.  If a covering index is ever needed, `CREATE INDEX idx_actors_public_figure ON actors (id) WHERE public_figure = true;` is a partial index and will remain small.
- The field is `NOT NULL` deliberately: nullable booleans are a footgun in Python (`if actor.public_figure` passes on `None`, which could accidentally bypass pseudonymization).

### GDPR Art. 89(1) compliance constraints

- This exemption applies only to **publicly elected or appointed officials** (Danish Folketing MPs, Greenlandic ministers, US federal officials, etc.).
- The exception covers only statements made **in official capacity**.  Private posts by the same individual on the same account do NOT automatically fall under the exemption — collection scope must be defined accordingly in the query design.
- **Private individuals must remain pseudonymized** regardless of public prominence (e.g. activists, academics, journalists are NOT covered unless they hold an official appointment).
- The research institution's **DPO must review** the set of `public_figure = true` actors periodically (suggested: quarterly).  A maintenance query is:
  ```sql
  SELECT id, canonical_name, actor_type, created_at
  FROM actors
  WHERE public_figure = true
  ORDER BY canonical_name;
  ```

---

### GR-14 normalizer change required (for Core Application Engineer)

**File**: `src/issue_observatory/core/normalizer.py`

**What to change**: The `pseudonymize_author()` method (line 272) currently always returns a salted SHA-256 hash.  It must be extended to accept an `is_public_figure: bool = False` parameter.  When `True`, it should return the raw `platform_username` (display handle) instead of the hash.

Suggested signature change:

```python
def pseudonymize_author(
    self,
    platform: str,
    platform_user_id: str,
    is_public_figure: bool = False,
    platform_username: str | None = None,
) -> str | None:
    """Return pseudonymized or plain author identifier.

    When is_public_figure is True (GR-14), returns the plain
    platform_username so that content can be attributed to named
    public officials.  Falls back to platform_user_id if
    platform_username is not supplied.

    When is_public_figure is False (default), returns the salted
    SHA-256 hash as usual.
    """
    if is_public_figure:
        return platform_username or platform_user_id
    if not self._salt:
        return None
    payload = f"{platform}:{platform_user_id}:{self._salt}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

**Collection runner integration**: Before calling `normalizer.normalize()`, the collection runner must look up the actor in the registry to check `public_figure`.  The recommended pattern:

```python
# In the collection runner / task, before calling normalizer.normalize():
actor = await db.scalar(
    select(Actor)
    .join(ActorPlatformPresence, ActorPlatformPresence.actor_id == Actor.id)
    .where(
        ActorPlatformPresence.platform == platform,
        ActorPlatformPresence.platform_user_id == raw_author_platform_id,
    )
)
is_public_figure = actor.public_figure if actor else False

record = normalizer.normalize(
    raw_item=raw_item,
    platform=platform,
    arena=arena,
    is_public_figure=is_public_figure,
    platform_username=raw_author_display_name,
)
```

The `normalize()` method signature should also be extended to accept and forward `is_public_figure` and `platform_username` to `pseudonymize_author()`.

---

### GR-14 frontend change needed (for Frontend Engineer)

The actor detail/edit form (`templates/actors/detail.html` or equivalent) should include a "Public Figure" toggle checkbox.

- Label: "Public Figure (GDPR Art. 89(1) exemption)"
- The checkbox must carry a warning tooltip explaining the GDPR implications:
  > "This bypasses anonymization. Use only for elected officials, ministers, and other public figures acting in official capacity. Private individuals must remain pseudonymized."
- The toggle should only be visible to users with admin or researcher roles — not to read-only guests.
- When toggled to `True`, display a confirmation dialog:
  > "Are you sure? Setting this actor as a public figure will store their platform username in plain text in collected content records. This is a GDPR-significant action. Confirm only for publicly elected or appointed officials."
- API call on save: `PATCH /actors/{id}` with body `{"public_figure": true}` or `{"public_figure": false}`.
