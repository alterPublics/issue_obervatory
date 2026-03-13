# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**The Issue Observatory** is a multi-platform media data collection and analysis app for communications research. It collects content across 25+ digital platform "arenas" (social media, news, search engines, web archives) around researcher-defined search terms and actor lists, initially targeting Danish media discourse.

**Stack:** Python 3.12+ / FastAPI / Jinja2 + HTMX 2 + Alpine.js 3 + Tailwind CSS / PostgreSQL 16+ / Celery + Redis / SQLAlchemy 2.0 async

## Common Commands

```bash
# Dev server (port 8022)
make run

# Celery worker + beat scheduler (separate terminals)
make worker
make beat

# Database
make migrate                          # alembic upgrade head
make migration MSG="describe change"  # autogenerate new migration

# Tests
make test                             # full suite with coverage
pytest tests/unit/                    # unit tests only
pytest tests/arenas/test_bluesky.py   # single arena test
pytest -m "not integration"           # skip integration tests
pytest tests/unit/test_normalizer.py::test_pseudonymize -x  # single test, stop on failure

# Linting and formatting
make lint-fix                         # ruff check --fix + ruff format
make lint                             # check only (no changes)
make typecheck                        # mypy src/

# Frontend CSS
make css                              # tailwind watch mode
make css-build                        # tailwind minified build

# Infrastructure
make docker-up                        # postgres, redis, minio
make docker-down
```

## Architecture

### Source layout (`src/issue_observatory/`)

- **`arenas/`** — Each platform collector is a self-contained directory (collector, config, tasks, router). The `ArenaCollector` ABC in `base.py` defines the interface; `registry.py` does autodiscovery keyed by `platform_name`.
- **`core/`** — Models (`core/models/`), schemas (`core/schemas/`), and shared services: normalizer, credential pool (Fernet-encrypted, DB-backed), credit service, deduplication (URL + content hash + SimHash), entity resolver, event bus (Redis pub/sub SSE), retention service.
- **`analysis/`** — Descriptive stats, network analysis, export (CSV/XLSX/NDJSON/Parquet/GEXF/RIS/BibTeX), enrichment pipeline (`analysis/enrichments/`), propagation detection, alerting, link mining, coordination detection.
- **`api/`** — FastAPI app, Jinja2 templates (`api/templates/`), static files (`api/static/`), route modules (`api/routes/`).
- **`workers/`** — Celery app, beat schedule, rate limiter (Redis sliding window).
- **`sampling/`** — Snowball sampling, network expansion, similarity finder.
- **`scraper/`** — URL content extraction (httpx + Playwright + trafilatura).
- **`config/`** — Settings, tier definitions, Danish locale defaults.
- **`imports/`** — Zeeschuimer / manual data import.

### Key architectural patterns

**Arena collector pattern:** Every arena in `arenas/{name}/` has a `collector.py` subclassing `ArenaCollector` with `@register` decorator. Implements `collect_by_terms()`, `collect_by_actors()`, `normalize()`. The registry is keyed by `platform_name` (unique per collector), while `arena_name` is a grouping label (e.g., `"social_media"`).

**Three-tier pricing:** FREE / MEDIUM / PREMIUM. Tier resolution order: per-arena override in `CollectionRun.arenas_config` > launcher request > global `CollectionRun.tier`.

**Content records:** Universal schema with `raw_metadata` JSONB for platform-specific data. Range-partitioned by `published_at` (monthly). Content records are immutable (no `updated_at`, uses `collected_at`).

**Researcher-configurable sources:** Arenas like RSS, Telegram, Reddit, Discord, Wikipedia accept custom source lists via `arenas_config` JSONB on `query_designs`. Persisted via `PATCH /query-designs/{id}/arena-config/{arena_name}`.

**Enrichment pipeline:** Pluggable post-collection processors subclassing `ContentEnricher`. Write output to `raw_metadata.enrichments.{name}`. No schema migration needed for new enrichers.

**SSE live monitoring:** Collection progress via `GET /collections/{run_id}/stream`. Event bus uses sync Redis pub/sub (callable from Celery workers). Frontend uses `hx-ext="sse"`.

**Boolean query logic:** Search terms support AND/OR grouping via `group_id`/`group_label` fields, built by `query_builder.py`.

### Database

- SQLAlchemy 2.0 declarative, async (asyncpg). Sync driver (psycopg2) used by Celery helpers.
- All tables use `TimestampMixin` (`created_at`/`updated_at`) except `content_records`.
- UUIDs for all primary keys. Platform-specific data always in `raw_metadata` JSONB.
- Alembic migrations in `alembic/versions/` (15 revisions).
- `content_records` is range-partitioned by `published_at`.

## Coding Standards

- `from __future__ import annotations` in all files
- Strict type hints on all function signatures
- Async everywhere (httpx, SQLAlchemy async, FastAPI)
- Pydantic v2 for validation/serialization
- Ruff: line length 100, double quotes, rules E/W/F/I/B/C4/UP/ANN/TCH/RUF
- Commit format: `{scope}: {description}` — scopes: `core`, `arena/{name}`, `analysis`, `sampling`, `infra`, `docs`, `tests`
- All UI text in **English** (`<html lang="en">`). Danish only in data/query parameters.
- Custom exception hierarchy from `IssueObservatoryError` in `core/exceptions.py`
- Structured logging via structlog

## Danish Context

Collectors apply Danish locale defaults (centralized in `config/danish_defaults.py`): `gl=dk`/`hl=da` for Google, `lang:da` for Bluesky/X, `sourcelang:danish` for GDELT, ISO 639-3 `"dan"` for Event Registry, curated Danish RSS feeds, Danish subreddits.

GDPR compliance: SHA-256 pseudonymization with salt (required env var `PSEUDONYMIZATION_SALT`), public figure bypass (`public_figure=True` on Actor), configurable retention policies.

## Environment Setup

Copy `.env.example` to `.env`. Three values **must** be set before first run:
- `SECRET_KEY` — `openssl rand -hex 32`
- `PSEUDONYMIZATION_SALT` — `openssl rand -hex 32`
- `CREDENTIAL_ENCRYPTION_KEY` — `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`

Arena API keys in `.env` are auto-bootstrapped into the DB credential pool on startup.

Default ports: FastAPI on 8022, PostgreSQL on 5481, Redis on 6381.

## Key Reference Documents

| Document | Path |
|----------|------|
| Full implementation plan | `IMPLEMENTATION_PLAN.md` |
| Improvement roadmap (61 items) | `docs/research_reports/implementation_plan_2_0_strategy.md` |
| Agent roles | `AGENTS.md` |
| Arena research briefs | `docs/arenas/{platform}.md` |
| Release notes / status | `docs/release_notes/` |
| Platform API research | `reports/cross_platform_data_collection.md` |
| Danish context guide | `reports/danish_context_guide.md` |

**Rule:** Arena implementation requires a completed research brief at `docs/arenas/{platform}.md` before engineering work begins.
