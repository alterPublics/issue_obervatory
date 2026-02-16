# Deployment Guide

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Docker Engine | 24+ | Required for all services |
| Docker Compose | v2 (plugin) | Use `docker compose` not `docker-compose` |
| Node.js | 18+ | One-time Tailwind CSS build only; not needed at runtime |
| Python | 3.12+ | Only needed for local dev; Docker handles production |

---

## Environment Variables Reference

All variables are read by `src/issue_observatory/config/settings.py` via Pydantic Settings.
Copy `.env.example` to `.env` and fill in required values before first run.

### Database

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DATABASE_URL` | — | Yes | Async PostgreSQL DSN. Must use the `asyncpg` driver: `postgresql+asyncpg://user:pass@db:5432/issue_observatory` |

### Redis

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | No | Redis connection URL for application use (sessions, caching) |

### Security

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `SECRET_KEY` | — | Yes | Random hex string for JWT signing. Generate: `openssl rand -hex 32` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | No | Short-lived JWT access token lifetime in minutes |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `30` | No | Long-lived JWT refresh token lifetime in days |
| `CREDENTIAL_ENCRYPTION_KEY` | — | Yes | Fernet key for encrypting API credentials at rest. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `PSEUDONYMIZATION_SALT` | — | Yes | Project-specific salt for SHA-256 hashing of author identifiers. Keep stable for the project lifetime. |

### MinIO / Object Storage

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MINIO_ENDPOINT` | `localhost:9000` | No | MinIO host:port without scheme |
| `MINIO_ROOT_USER` | `minioadmin` | No | MinIO access key (AWS_ACCESS_KEY_ID equivalent) |
| `MINIO_ROOT_PASSWORD` | `minioadmin` | No | MinIO secret key (AWS_SECRET_ACCESS_KEY equivalent) |
| `MINIO_BUCKET` | `issue-observatory` | No | Default bucket for media file archival |
| `MINIO_SECURE` | `false` | No | Use TLS for MinIO. Set `true` in production |

### Celery

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | No | Redis URL for Celery broker (DB 1, isolated from app) |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/2` | No | Redis URL for Celery result storage (DB 2) |

### Admin Bootstrap

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `FIRST_ADMIN_EMAIL` | `""` | No | Email for first admin account. Bootstrap script skips if empty |
| `FIRST_ADMIN_PASSWORD` | `""` | No | Password for first admin account. Only used during first-run init |

### Application Behaviour

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `APP_NAME` | `The Issue Observatory` | No | Human-readable name shown in UI and OpenAPI docs |
| `DEBUG` | `false` | No | Enable FastAPI debug mode. Never `true` in production |
| `LOG_LEVEL` | `INFO` | No | Logging verbosity: DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `DEFAULT_TIER` | `free` | No | Default collection tier when not specified per-run |
| `METRICS_ENABLED` | `true` | No | Expose Prometheus metrics at `GET /metrics` |

### Danish Locale Defaults

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DEFAULT_LANGUAGE` | `da` | No | ISO 639-1 language code for default collection filter |
| `DEFAULT_LOCALE_COUNTRY` | `dk` | No | ISO 3166-1 alpha-2 country code for default locale filter |

### GDPR / Data Retention

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DATA_RETENTION_DAYS` | `730` | No | Max age of collected records before deletion. Default = 2 years |

### CORS

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `ALLOWED_ORIGINS` | `["http://localhost:8000"]` | No | JSON list of CORS-allowed origins |

### SMTP / Email

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `SMTP_HOST` | `null` | No | SMTP hostname. When null, emails are silently disabled |
| `SMTP_PORT` | `587` | No | SMTP port (587 = STARTTLS submission) |
| `SMTP_USERNAME` | `null` | No | SMTP auth username |
| `SMTP_PASSWORD` | `null` | No | SMTP auth password |
| `SMTP_FROM_ADDRESS` | `noreply@observatory.local` | No | From address for all outgoing emails |
| `SMTP_STARTTLS` | `true` | No | Upgrade connection to TLS via STARTTLS |
| `SMTP_SSL` | `false` | No | Use implicit TLS (port 465). Mutually exclusive with STARTTLS |

### Credit System

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `LOW_CREDIT_WARNING_THRESHOLD` | `100` | No | Send low-credit warning email when balance drops below this value |

---

## Production Docker Compose Setup

All production services are defined in `docker-compose.yml`. The recommended production
profile runs these services:

| Service | Description | Resource Suggestion |
|---------|-------------|---------------------|
| `db` | PostgreSQL 16 | 2 CPU, 2 GB RAM |
| `redis` | Redis 7 | 0.5 CPU, 512 MB RAM |
| `minio` | MinIO object storage | 1 CPU, 1 GB RAM |
| `app` | FastAPI via Gunicorn+Uvicorn | 2 CPU, 1 GB RAM |
| `worker` | Celery arena collection worker | 2 CPU, 2 GB RAM |
| `beat` | Celery Beat scheduler | 0.25 CPU, 256 MB RAM |

### Healthchecks

The `app` service exposes `GET /health` (fast liveness, no I/O) and
`GET /api/health` (deep check including DB and Redis). Configure Docker
healthchecks to use the fast endpoint:

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 10s
```

### Resource Limits Example

```yaml
services:
  app:
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: 1G
        reservations:
          cpus: "0.5"
          memory: 256M
  worker:
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: 2G
```

---

## Tailwind CSS Rebuild

The compiled CSS (`src/issue_observatory/api/static/css/app.css`) is checked
into the repository. Rebuild it only when Jinja2 templates change:

```bash
# Using the Makefile target (recommended)
make css

# Equivalent manual command
npx tailwindcss \
  -i src/issue_observatory/api/static/css/input.css \
  -o src/issue_observatory/api/static/css/app.css \
  --minify
```

Node.js is required only for this step. The compiled output is checked in,
so no Node.js runtime is needed in Docker.

---

## First-Run Checklist

Run these steps in order after first `docker compose up -d`:

```bash
# 1. Run database migrations
docker compose exec app alembic upgrade head

# 2. Bootstrap the first admin account
#    (reads FIRST_ADMIN_EMAIL and FIRST_ADMIN_PASSWORD from environment)
docker compose exec app python scripts/bootstrap_admin.py

# 3. Create initial content_records partitions
#    (creates monthly partitions for the next 12 months)
docker compose exec app python scripts/create_partitions.py

# 4. Verify application health
curl http://localhost:8000/health
curl http://localhost:8000/api/health
```

---

## Reverse Proxy Setup

### Nginx

```nginx
upstream observatory {
    server app:8000;
}

server {
    listen 443 ssl http2;
    server_name observatory.example.com;

    # SSL configuration omitted — use certbot/Let's Encrypt

    location / {
        proxy_pass http://observatory;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE (Server-Sent Events) — disable buffering for live run status
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }

    location /static/ {
        proxy_pass http://observatory;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
}
```

### Caddy

```caddyfile
observatory.example.com {
    reverse_proxy app:8000 {
        header_up Host {host}
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-Proto {scheme}

        # Disable buffering for SSE endpoints
        flush_interval -1
    }
}
```

---

## Celery Worker and Beat Startup

The Docker Compose file starts workers automatically. For manual startup:

```bash
# Arena collection worker (concurrency=4 recommended for I/O-bound arena tasks)
celery -A issue_observatory.workers.celery_app worker \
  --loglevel=info \
  --concurrency=4 \
  --queues=celery,export \
  --hostname=worker1@%h

# Beat scheduler (run exactly one instance — multiple beats cause duplicate tasks)
celery -A issue_observatory.workers.celery_app beat \
  --loglevel=info \
  --scheduler celery.beat.PersistentScheduler

# Flower monitoring (optional)
celery -A issue_observatory.workers.celery_app flower \
  --port=5555
```

---

## Prometheus Scrape Configuration

Add the following to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: issue_observatory
    static_configs:
      - targets: ["app:8000"]
    metrics_path: /metrics
    scrape_interval: 15s
```

For Grafana, add Prometheus as a datasource and create panels using the
metrics documented in `docs/operations/api_reference.md` under Prometheus
Metrics. Key metrics to dashboard:

- `http_requests_total` — request volume by method/path/status
- `http_request_duration_seconds` — latency percentiles (p50, p95, p99)
- `collection_runs_total` — collection throughput by status and tier
- `collection_records_total` — records ingested by arena/platform
- `arena_health_status` — per-arena up/down gauge
- `celery_tasks_total` — task throughput and failure rate
- `celery_task_duration_seconds` — task latency by task name
- `credit_transactions_total` — credit consumption by type and arena
