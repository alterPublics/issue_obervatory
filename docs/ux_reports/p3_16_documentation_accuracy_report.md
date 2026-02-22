# P3-16 Documentation Accuracy Report
Date: 2026-02-22
Scope: Deployment guide, referenced scripts, .env.example, Docker Compose

---

## Item 1: Deployment Guide Accuracy

**File:** `/docs/operations/deployment.md`

**Verdict: PARTIAL**

### What is correct

- The `uvicorn issue_observatory.api.main:app` module path is accurate. The file `/src/issue_observatory/api/main.py` exists and exports a module-level `app = create_app()` singleton (line 473).
- The `celery -A issue_observatory.workers.celery_app worker` path is accurate. The file `/src/issue_observatory/workers/celery_app.py` exists and exports `celery_app`.
- The Tailwind CSS rebuild commands match the `Makefile` targets (`css` and `css-build`). Input/output paths are consistent.
- The Nginx reverse proxy config correctly disables buffering for SSE endpoints.
- Healthcheck endpoints (`/health` and `/api/health`) are verified to exist in `main.py` (lines 452-464 for `/health`; `/api/health` is registered via `health_routes.router`).
- Alembic migration infrastructure exists (`alembic.ini`, `alembic/` directory with 16 migration files).
- The Celery Beat command correctly uses `--scheduler=celery.beat:PersistentScheduler`.

### Issues found

1. **Service name mismatch in the table vs actual docker-compose.yml.** The deployment doc table (line 121) calls the PostgreSQL service `db`, but `docker-compose.yml` names it `postgres`. A researcher following the doc might be confused when they see `postgres` in the compose output instead of `db`. [Severity: Friction] [frontend]

2. **Missing `scraper_worker` service in the deployment doc table.** The docker-compose.yml defines six running services (postgres, redis, minio, app, worker, scraper_worker, beat) plus the minio-init one-shot, but the deployment guide table only lists six services and omits the dedicated `scraper_worker`. A researcher who deploys from the doc alone will not know a second Celery worker for scraping tasks exists. [Severity: Friction] [core]

3. **`scripts/` directory not available inside the `app` container.** The Dockerfile does NOT copy the `scripts/` directory into the image. The `docker-compose.yml` `app` service does not volume-mount `scripts/`. Therefore, the First-Run Checklist commands on lines 197-201 will fail:
   ```
   docker compose exec app python scripts/bootstrap_admin.py    # File not found
   docker compose exec app python scripts/create_partitions.py  # File not found (and script does not exist either)
   ```
   Only the `backup` service bind-mounts `./scripts:/app/scripts:ro`. [Severity: Blocker] [core]

4. **`make css` in the deployment doc is the watch-mode target.** The doc says "Equivalent manual command" uses `--minify`, but `make css` in the Makefile actually runs `--watch` (dev mode, not minified). The correct production target is `make css-build`. [Severity: Friction] [frontend]

---

## Item 2: Referenced Scripts Exist

**Verdict: PARTIAL (2 of 3 exist)**

### `scripts/bootstrap_admin.py`

**EXISTS.** Located at `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/scripts/bootstrap_admin.py`.

- Imports are plausible: `issue_observatory.config.settings`, `issue_observatory.core.database`, `issue_observatory.core.models.users`, `sqlalchemy.select`.
- Correctly adds `src/` to `sys.path` for standalone execution (lines 38-41).
- Uses `fastapi_users.password.PasswordHelper` for password hashing.
- Reads `FIRST_ADMIN_EMAIL` and `FIRST_ADMIN_PASSWORD` from settings.
- Idempotent: updates existing user to admin role if already present.
- Would plausibly work if run with the correct Python environment and database available.

### `scripts/backup_postgres.py`

**EXISTS.** Located at `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/scripts/backup_postgres.py`.

- Self-contained script with no application imports -- uses only stdlib + `minio` optional dependency.
- Parses `DATABASE_URL` (handles `postgresql+asyncpg://` to `postgresql://` conversion).
- Runs `pg_dump`, gzip-compresses, uploads to MinIO, prunes old backups.
- Has `--dry-run` flag for safety.
- Would plausibly work given `pg_dump` is available in PATH and `minio` Python package is installed.
- Note: The Docker image uses `python:3.12-slim` which does NOT include `pg_dump`. The `backup` service would need `postgresql-client` installed or the Dockerfile would need modification. This is a potential silent failure at runtime. [Severity: Friction] [core]

### `scripts/create_partitions.py`

**DOES NOT EXIST.** Referenced in the deployment guide at line 201 (`docker compose exec app python scripts/create_partitions.py`) and described as creating monthly partitions for the next 12 months.

This is already documented as a known gap in `/docs/pre_production_checklist.md` (line 214 and line 260). The pre-production checklist explicitly notes: "scripts/create_partitions.py is referenced in /docs/operations/deployment.md line 201 but does not exist."

Without this script, the content_records table relies only on the partitions created in migration 001. If those only cover through April 2026, any records published after that date would fall to a default partition, defeating the partitioning benefits. [Severity: Blocker] [core]

---

## Item 3: .env.example Completeness

**File:** `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/.env.example`

**Verdict: FAIL**

### Environment variable name mismatches (will silently fail)

These are the most dangerous findings because `settings.py` has `extra="ignore"`, meaning mismatched variable names are silently dropped, and the application falls back to defaults without any warning.

1. **`CORS_ORIGINS` (line 24 of .env.example) should be `ALLOWED_ORIGINS`.**
   - Settings field: `allowed_origins: list[str]` (line 179 of settings.py)
   - Pydantic Settings maps `ALLOWED_ORIGINS` from the environment.
   - The `.env.example` uses `CORS_ORIGINS`, which is silently ignored.
   - Impact: CORS is always `["http://localhost:8000"]` regardless of what the researcher sets, with no error message. In production with a real domain, all cross-origin requests fail silently. [Severity: Blocker] [core]

2. **`DEFAULT_COST_TIER` (line 53 of .env.example) should be `DEFAULT_TIER`.**
   - Settings field: `default_tier: str = "free"` (line 149 of settings.py)
   - Pydantic Settings maps `DEFAULT_TIER` from the environment.
   - The `.env.example` uses `DEFAULT_COST_TIER`, which is silently ignored.
   - Impact: The tier is always `"free"` regardless of what the researcher sets. Less critical than CORS since the default is safe, but the configuration is misleading. [Severity: Friction] [core]

### Missing environment variables (have defaults in settings, not shown in .env.example)

The following settings fields exist in `settings.py` with defaults and are documented in the deployment guide's env var table, but are absent from `.env.example`. While they all have sensible defaults, a researcher reading `.env.example` as their sole configuration reference would not know these options exist:

3. `APP_NAME` -- not in .env.example (default: "The Issue Observatory")
4. `ACCESS_TOKEN_EXPIRE_MINUTES` -- not in .env.example (default: 30)
5. `REFRESH_TOKEN_EXPIRE_DAYS` -- not in .env.example (default: 30)
6. `METRICS_ENABLED` -- not in .env.example (default: true)
7. `DEFAULT_LANGUAGE` -- not in .env.example (default: "da")
8. `DEFAULT_LOCALE_COUNTRY` -- not in .env.example (default: "dk")
9. `DATA_RETENTION_DAYS` -- not in .env.example (default: 730)
10. `LOW_CREDIT_WARNING_THRESHOLD` -- not in .env.example (default: 100)
11. `SMTP_HOST` through `SMTP_SSL` (6 variables) -- not in .env.example (default: disabled)

These are not blockers since they have safe defaults, but they represent configuration discoverability failures. A researcher who wants to enable email notifications or change the retention policy would have to read the deployment doc or the source code. [Severity: Friction] [research]

### Missing environment variables (used in code, not in .env.example)

12. **`MAJESTIC_PREMIUM_API_KEY`** -- referenced in `arenas/majestic/collector.py` (line 476) as an `os.environ.get` fallback. The `.env.example` only has `MAJESTIC_API_KEY`. The credential pool maps `("majestic", "premium")` to `MAJESTIC_API_KEY`, but the collector's own fallback uses `MAJESTIC_PREMIUM_API_KEY`. This is internally inconsistent. [Severity: Friction] [data]

### Database name mismatch between .env.example and docker-compose.yml

13. **`.env.example` DATABASE_URL uses database name `issue_observatory`; docker-compose.yml POSTGRES_DB defaults to `observatory`.**
   - `.env.example` line 8: `postgresql+asyncpg://observatory:observatory@localhost:5432/issue_observatory`
   - `docker-compose.yml` line 13: `POSTGRES_DB: ${POSTGRES_DB:-observatory}`
   - `docker-compose.yml` line 136 (app service): `DATABASE_URL=${DATABASE_URL:-postgresql+asyncpg://observatory:observatory@postgres:5432/observatory}`
   - A researcher using `.env.example` for local dev with the docker-compose postgres service will get a connection failure because the database `issue_observatory` does not exist on the server (only `observatory` exists).
   - For Docker deployment, the `app` service overrides the default to `observatory`, so it works -- but only if the researcher does NOT set `DATABASE_URL` in their `.env` from the `.env.example` template. [Severity: Blocker] [core]

### Variables in docker-compose.yml not in .env.example

14. `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` -- used by the docker-compose postgres service but absent from `.env.example`. Not technically needed if defaults are acceptable, but a researcher wanting to customize database credentials has no template guidance. [Severity: Friction] [core]

15. `BACKUP_RETENTION_DAYS` -- used by the backup service in docker-compose.yml (line 113) but absent from `.env.example`. [Severity: Friction] [core]

---

## Item 4: Docker Compose Completeness

**File:** `/Users/jakobbk/Documents/postdoc/codespace/issue_observatory/docker-compose.yml`

**Verdict: PARTIAL**

### Services defined

| Service | Present | Notes |
|---------|---------|-------|
| postgres | Yes | Correct image (postgres:16-alpine), healthcheck, named volume |
| redis | Yes | Correct image (redis:7-alpine), AOF + RDB persistence, healthcheck, named volume |
| minio | Yes | Object storage for backups, healthcheck, named volume |
| minio-init | Yes | One-shot bucket initialization, depends on minio healthy |
| app (FastAPI) | Yes | Correct CMD, port 8000, depends on postgres + redis healthy |
| worker (Celery) | Yes | Correct celery command, concurrency=4, depends on postgres + redis |
| scraper_worker | Yes | Dedicated scraping queue, Playwright install at startup, concurrency=2 |
| beat (Celery Beat) | Yes | Correct scheduler, dedicated beat_schedule volume |
| backup | Yes | Profile-gated (`--profile backup`), depends on postgres + minio |

All required services are present.

### Port mappings

| Service | Port | Assessment |
|---------|------|------------|
| postgres | 5432:5432 | Sensible for development; should be removed or restricted in production |
| redis | 6379:6379 | Same consideration as postgres |
| minio | 9000:9000, 9001:9001 | API + console; sensible |
| app | 8000:8000 | Correct |

### Volume mounts and data persistence

| Volume | Service | Assessment |
|--------|---------|------------|
| `postgres_data` | postgres | Named volume for database files -- correct |
| `redis_data` | redis | Named volume for AOF/RDB files -- correct |
| `minio_data` | minio | Named volume for object storage -- correct |
| `beat_schedule` | beat | Named volume for persistent Beat schedule -- correct |
| `backups` | (declared but unused) | Declared at line 260 but no service references it. Dead declaration. |

### Issues found

1. **`scripts/` directory not mounted in `app` service.** The `app` service mounts `./src:/app/src:ro` but not `./scripts`. The deployment guide instructs running `docker compose exec app python scripts/bootstrap_admin.py`, which would fail. The `backup` service correctly mounts `./scripts:/app/scripts:ro`, proving the pattern is known but was not applied to `app`. [Severity: Blocker] [core]

2. **`pg_dump` not installed in the Docker image.** The Dockerfile's `final` stage installs `libpq5` (client library) and `curl`, but NOT `postgresql-client` (which provides `pg_dump`). The `backup` service reuses the same Docker image and runs `scripts/backup_postgres.py`, which calls `pg_dump`. This would fail at runtime with "pg_dump not found". [Severity: Blocker] [core]

3. **Arena API credential environment variables not passed to worker and scraper_worker.** The `app`, `worker`, and `scraper_worker` services pass through core infrastructure variables (DATABASE_URL, REDIS_URL, SECRET_KEY, etc.) but none of the arena-specific API keys (SERPER_API_KEY, BLUESKY_HANDLE, REDDIT_CLIENT_ID, etc.). The credential pool's `_acquire_from_env` fallback reads from `os.environ`, which inside the container would be empty for these variables. The `app` service would need either explicit `env_file: .env` or all relevant variables listed. [Severity: Blocker] [core]

4. **Unused `backups` volume declaration.** The named volume `backups` is declared at the bottom of the file but no service references it. The backup service writes to a temp file then uploads to MinIO. This is dead configuration. [Severity: Friction] [core]

5. **`./src:/app/src:ro` volume mount in production is questionable.** The `app`, `worker`, `scraper_worker`, and `beat` services all bind-mount `./src:/app/src:ro`, which overlays the source code already copied into the image by the Dockerfile. This is a development convenience that should not appear in a production deployment guide. In production, the image should be self-contained. [Severity: Friction] [core]

6. **No `env_file` directive.** None of the application services use `env_file: .env`. This means a researcher must either: (a) export every variable to the shell before running `docker compose up`, or (b) add `env_file: .env` themselves. The deployment guide does not mention this. For Docker-based deployment, this is a significant gap in the instructions. [Severity: Blocker] [core]

---

## Summary

| Item | Verdict | Blocker Count | Friction Count |
|------|---------|---------------|----------------|
| 1. Deployment guide accuracy | PARTIAL | 1 | 3 |
| 2. Referenced scripts exist | PARTIAL | 1 | 1 |
| 3. .env.example completeness | FAIL | 2 | 5+ |
| 4. Docker Compose completeness | PARTIAL | 4 | 3 |

### Blocker summary (must fix before a researcher can self-deploy)

| # | Description | Responsible |
|---|-------------|-------------|
| B1 | `scripts/` not available inside `app` container -- bootstrap_admin.py cannot run | [core] |
| B2 | `scripts/create_partitions.py` does not exist but is in the first-run checklist | [core] |
| B3 | `CORS_ORIGINS` env var name in .env.example silently ignored; should be `ALLOWED_ORIGINS` | [core] |
| B4 | DATABASE_URL in .env.example points to database `issue_observatory` but docker-compose creates `observatory` | [core] |
| B5 | Arena API credentials not passed to Docker services (no `env_file` directive, no credential vars listed) | [core] |
| B6 | `pg_dump` not installed in Docker image; backup service will fail at runtime | [core] |
| B7 | No `env_file: .env` on any service; researcher has no documented path to pass variables to containers | [core] |

### Friction summary (will confuse but not completely block)

| # | Description | Responsible |
|---|-------------|-------------|
| F1 | Deployment doc table calls postgres service `db` but docker-compose names it `postgres` | [frontend] |
| F2 | `scraper_worker` service not mentioned in deployment doc | [core] |
| F3 | `make css` is watch mode, not the production build; doc implies it is the production command | [frontend] |
| F4 | `DEFAULT_COST_TIER` env var in .env.example silently ignored; should be `DEFAULT_TIER` | [core] |
| F5 | Multiple settings (SMTP, retention, metrics, locale) undiscoverable from .env.example alone | [research] |
| F6 | `MAJESTIC_PREMIUM_API_KEY` vs `MAJESTIC_API_KEY` inconsistency between collector and credential pool | [data] |
| F7 | Unused `backups` volume declaration in docker-compose.yml | [core] |
| F8 | Production bind-mount of `./src` overlays image source; not appropriate for production | [core] |
| F9 | Dockerfile backup stage missing `postgresql-client` package | [core] |
