# The Issue Observatory

A modular multi-platform media data collection and analysis application for media and communications research. Tracks mediated content around specific issues across diverse platforms, initially targeting a Danish context with architecture for international expansion.

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
# Edit .env with your credentials

# Start infrastructure services
docker compose up -d postgres redis minio

# Install Python dependencies
pip install -e ".[dev]"

# Run database migrations
alembic upgrade head

# Build CSS (one-off, output is checked in)
make css

# Start the application
uvicorn src.issue_observatory.api.main:app --reload

# Start Celery worker (separate terminal)
celery -A src.issue_observatory.workers.celery_app worker --loglevel=info

# Start Celery beat scheduler (separate terminal)
celery -A src.issue_observatory.workers.celery_app beat --loglevel=info
```

## Project Structure

```
issue_observatory/
├── src/issue_observatory/       # Python package
│   ├── config/                  # Settings, tiers, Danish defaults
│   ├── core/                    # Models, schemas, normalizer, services
│   ├── arenas/                  # Platform collectors (one dir per arena)
│   ├── sampling/                # Actor discovery and snowball sampling
│   ├── analysis/                # Descriptive stats, network analysis, export
│   ├── workers/                 # Celery app, beat schedule, rate limiter
│   └── api/                     # FastAPI routes, templates, static files
├── alembic/                     # Database migrations
├── tests/                       # Test suite
├── docs/                        # Status files, arena briefs, ADRs
├── reports/                     # Research knowledge base
└── docker-compose.yml
```

## Key Documentation

- `IMPLEMENTATION_PLAN.md` — Full architecture, schema, phased build plan
- `AGENTS.md` — Agent roles and coordination protocol
- `reports/cross_platform_data_collection.md` — Platform API/access research
- `reports/danish_context_guide.md` — Denmark-specific sources, legal, GDPR

## Development

```bash
# Run tests
pytest

# Run linter
ruff check src/ tests/

# Type checking
mypy src/

# Rebuild CSS after template changes
make css
```

## License

TBD
