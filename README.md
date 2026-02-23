# The Issue Observatory

A modular multi-platform media data collection and analysis application for media and communications research. Tracks mediated content around specific issues across 25 platform arenas, initially targeting a Danish context with architecture for international expansion.

## Architecture

- **Arena-based modularity**: Each data source is a self-contained module (collector, router, tasks, config)
- **Query design driven**: All collection revolves around configurable sets of search terms and actor lists
- **Three-tier pricing**: FREE, MEDIUM, PREMIUM — configurable per arena, per run
- **Dual operation modes**: Batch collection over date ranges, or live daily tracking

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| Web Framework | FastAPI |
| Frontend | Jinja2 + HTMX 2 + Alpine.js 3 + Tailwind CSS |
| Charts | Chart.js 4 (CDN) |
| Database | PostgreSQL 16+ (JSONB, partitioned tables) |
| Task Queue | Celery + Redis |
| Object Storage | MinIO (S3-compatible) |
| Migrations | Alembic |
| Auth | FastAPI-Users + JWT (HttpOnly cookies) |
| Containers | Docker + Docker Compose |

## Prerequisites

- Python 3.12+
- Docker and Docker Compose
- Node.js (for Tailwind CSS CLI only — no JS build pipeline)

## Quick Start

```bash
# Clone and enter project
git clone <repo-url> issue_observatory
cd issue_observatory

# Copy environment configuration
cp .env.example .env
# Edit .env — you MUST set SECRET_KEY, PSEUDONYMIZATION_SALT,
# and CREDENTIAL_ENCRYPTION_KEY (see .env.example for generation commands)
# Optional: Add API credentials for arenas you want to use (SERPER_API_KEY,
# BLUESKY_HANDLE, YOUTUBE_API_KEY, etc.) — they will be automatically
# loaded into the credential pool on startup

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Start infrastructure services
docker compose up -d postgres redis minio

# Install Python dependencies
pip install -e ".[dev]"

# Run database migrations
alembic upgrade head

# Bootstrap admin user
python scripts/bootstrap_admin.py

# Start the application
uvicorn issue_observatory.api.main:app --reload

# Start Celery worker (separate terminal)
celery -A issue_observatory.workers.celery_app worker --loglevel=info

# Start Celery beat scheduler (separate terminal)
celery -A issue_observatory.workers.celery_app beat --loglevel=info
```

## Project Structure

```
issue_observatory/
├── src/issue_observatory/       # Python package
│   ├── config/                  # Settings, tiers, Danish defaults
│   ├── core/                    # Models, schemas, normalizer, services
│   ├── arenas/                  # 25 platform collectors (one dir per arena)
│   ├── imports/                 # Zeeschuimer / manual data import
│   ├── sampling/                # Actor discovery and snowball sampling
│   ├── analysis/                # Descriptive stats, network analysis, enrichments, export
│   ├── scraper/                 # URL content extraction (httpx + Playwright)
│   ├── workers/                 # Celery app, beat schedule, rate limiter
│   └── api/                     # FastAPI routes, templates, static files
├── alembic/                     # Database migrations (15 revisions)
├── tests/                       # Test suite (1790 tests)
├── docs/                        # Status files, arena briefs, research reports
├── reports/                     # Research knowledge base
└── docker-compose.yml
```

## Key Documentation

- `IMPLEMENTATION_PLAN.md` — Full architecture, schema, phased build plan
- `AGENTS.md` — Agent roles and coordination protocol
- `docs/release_notes/` — Implementation status and release notes
- `docs/arenas/` — Research briefs for each platform arena
- `reports/cross_platform_data_collection.md` — Platform API/access research
- `reports/danish_context_guide.md` — Denmark-specific sources, legal, GDPR

## Development

```bash
# Run tests with coverage
make test

# Run linter (and auto-fix)
make lint-fix

# Type checking
make typecheck

# Rebuild CSS after template changes
make css
```

## Make Targets

| Target | Description |
|--------|-------------|
| `make run` | Start FastAPI dev server with reload |
| `make worker` | Start Celery worker |
| `make beat` | Start Celery Beat scheduler |
| `make migrate` | Run Alembic migrations (upgrade head) |
| `make css` | Compile Tailwind CSS in watch mode |
| `make css-build` | Compile Tailwind CSS once (minified) |
| `make test` | Run pytest with coverage |
| `make lint` | Check code style with ruff |
| `make lint-fix` | Fix code style issues automatically |
| `make typecheck` | Run mypy static type checking |
| `make docker-up` | Start all Docker services |
| `make docker-down` | Stop all Docker services |
| `make docker-logs` | Tail service logs |

## License

TBD
