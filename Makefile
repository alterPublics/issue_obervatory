.PHONY: run worker beat migrate css test lint typecheck shell help

PYTHON := python
UVICORN := uvicorn
CELERY := celery
APP_MODULE := issue_observatory.api.main:app
CELERY_APP := issue_observatory.workers.celery_app

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

## run: Start the FastAPI development server with auto-reload
run:
	$(UVICORN) $(APP_MODULE) --reload --host 0.0.0.0 --port 8000

## worker: Start a Celery worker
worker:
	$(CELERY) -A $(CELERY_APP) worker --loglevel=info --concurrency=4

## beat: Start Celery Beat scheduler
beat:
	$(CELERY) -A $(CELERY_APP) beat --loglevel=info

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

## migrate: Run Alembic migrations (upgrade head)
migrate:
	alembic upgrade head

## migration: Create a new Alembic migration (usage: make migration MSG="describe change")
migration:
	alembic revision --autogenerate -m "$(MSG)"

# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

## css: Compile Tailwind CSS (watch mode)
css:
	npx tailwindcss -i ./src/issue_observatory/api/static/css/input.css \
	    -o ./src/issue_observatory/api/static/css/app.css --watch

## css-build: Compile Tailwind CSS once (minified, for production)
css-build:
	npx tailwindcss -i ./src/issue_observatory/api/static/css/input.css \
	    -o ./src/issue_observatory/api/static/css/app.css --minify

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------

## test: Run the test suite with coverage
test:
	pytest

## lint: Run ruff linter and formatter check
lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

## lint-fix: Run ruff linter with auto-fix and reformat
lint-fix:
	ruff check --fix src/ tests/
	ruff format src/ tests/

## typecheck: Run mypy static type checker
typecheck:
	mypy src/

# ---------------------------------------------------------------------------
# Development utilities
# ---------------------------------------------------------------------------

## shell: Open a Python REPL with the application context
shell:
	$(PYTHON) -c "import asyncio; import issue_observatory; print('issue_observatory loaded'); import IPython; IPython.start_ipython()"

## docker-up: Start all Docker services
docker-up:
	docker compose up -d

## docker-down: Stop all Docker services
docker-down:
	docker compose down

## docker-logs: Tail logs from all services
docker-logs:
	docker compose logs -f

## help: Print this help message
help:
	@grep -E '^##' Makefile | sed 's/## //' | column -t -s ':'
