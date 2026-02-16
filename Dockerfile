# ---------------------------------------------------------------------------
# Stage 1: builder — install Python dependencies
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency specification first for layer caching
COPY pyproject.toml ./
COPY src/ ./src/

# Install the package and all dependencies into /build/venv
RUN python -m venv /build/venv && \
    /build/venv/bin/pip install --upgrade pip setuptools wheel && \
    /build/venv/bin/pip install -e ".[dev]"

# ---------------------------------------------------------------------------
# Stage 2: final — lean runtime image
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS final

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/venv/bin:$PATH" \
    PYTHONPATH="/app/src"

WORKDIR /app

# Runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtualenv from builder
COPY --from=builder /build/venv /app/venv

# Copy application source
COPY src/ /app/src/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/alembic.ini

# Non-root user for security
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup --no-create-home appuser && \
    chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "issue_observatory.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
