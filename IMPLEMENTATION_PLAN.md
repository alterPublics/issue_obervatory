# The Issue Observatory — Implementation Plan

## Project Overview

The Issue Observatory is a modular, multi-platform media data collection and analysis application for tracking how issues, actors, and discourses propagate across the media ecosystem. The first iteration targets a **Danish context** while maintaining architecture for international expansion. It builds on the existing Issue Observatory Search (Google Search tracker) and extends collection to social media, news media, and the broader web.

---

## Foundational Architecture

### Core Principles

1. **Arena-based modularity**: Each data source (arena) is a self-contained module with its own backend API, runnable independently without the full application stack.
2. **Query design driven**: All collection revolves around a configurable query design — a set of key phrases, media tokens, and/or curated actor lists — that propagate across arenas.
3. **Three-tier pricing model**: Every arena supports three operational tiers — Free (ignore sources without free access), Medium (cheap services only), Premium (best available option) — configurable per-arena and per-run.
4. **Dual operation modes**: (a) Standalone batch collection over a specified time range, (b) Live daily tracking from an active query design.
5. **Incremental arena addition**: New arenas and platforms can be added without modifying core infrastructure.
6. **User-scoped collections**: All query designs and collection runs are owned by authenticated users. An admin allocates credits (API call budgets) to users.

### Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Language | Python 3.12+ | Ecosystem fit (data science, API clients, NLP), existing codebase compatibility |
| Framework | FastAPI | Async support, auto-generated OpenAPI docs, lightweight, each arena gets its own router |
| Templating | Jinja2 (served from FastAPI) | Server-rendered HTML; single Python codebase; no JS build pipeline |
| Frontend interactions | HTMX 2 | Handles server communication, pagination, SSE, inline CRUD via HTML attributes |
| Frontend reactivity | Alpine.js 3 (CDN) | Local browser state for arena config grid, pre-flight estimate, form show/hide; no build step |
| CSS | Tailwind CSS (one-off CLI build) | Utility-first; `npx tailwindcss` run as documented Makefile step, not a watch process |
| Charts | Chart.js 4 (CDN) | Descriptive statistics only; network analysis exported to GEXF for Gephi |
| Database | PostgreSQL 16+ with JSONB | Structured universal records + flexible platform metadata, proven at scale, full-text search |
| Task Queue | Celery + Redis | Proven in Issue Observatory Search, handles rate limiting, retries, scheduling |
| Object Storage | MinIO (self-hosted) or S3 | Media file archival (images, video thumbnails, PDFs) |
| Containerization | Docker + Docker Compose | Reproducible dev/deploy, isolates services |
| Testing | pytest + pytest-asyncio | Standard Python testing with async support |
| Migrations | Alembic | SQLAlchemy-integrated, versioned schema evolution |
| Auth | FastAPI-Users + JWT (HttpOnly cookie) | User registration, login, role-based access, API key support; CookieTransport for browser sessions |

### Project Structure

```
issue_observatory/                       # Project root
├── docker-compose.yml
├── pyproject.toml
├── Makefile
├── Dockerfile
├── alembic.ini
├── alembic/
│   └── versions/
├── src/
│   └── issue_observatory/               # Python package root
│       ├── __init__.py
│       ├── config/
│       │   ├── __init__.py
│       │   ├── settings.py              # Pydantic settings, env-based configuration
│       │   ├── tiers.py                 # Pricing tier definitions and feature flags
│       │   └── danish_defaults.py       # Danish-specific defaults (RSS feeds, locale params)
│       ├── core/
│       │   ├── __init__.py
│       │   ├── models/                  # SQLAlchemy ORM models
│       │   │   ├── __init__.py
│       │   │   ├── base.py              # Base model, UserOwnedMixin, TimestampMixin
│       │   │   ├── users.py             # User, UserCredits, CreditTransaction, RefreshToken
│       │   │   ├── content.py           # UniversalContentRecord (partitioned by published_at)
│       │   │   ├── actors.py            # Actor, ActorAlias, ActorPlatformPresence
│       │   │   ├── query_design.py      # QueryDesign (owner-scoped), SearchTerm, ActorList
│       │   │   ├── collection.py        # CollectionRun (owner-scoped), CollectionTask, ArenaStatus
│       │   │   ├── credentials.py       # ApiCredential (encrypted credential pool)
│       │   │   └── arena_extensions/    # Per-platform extension models
│       │   ├── schemas/                 # Pydantic request/response schemas
│       │   ├── database.py              # Session management, engine config
│       │   ├── normalizer.py            # Platform → universal record normalization
│       │   ├── entity_resolver.py       # Cross-platform actor matching
│       │   ├── credential_pool.py       # Credential acquisition, rotation, quota tracking
│       │   ├── credit_service.py        # Credit reservation, settlement, balance checks
│       │   └── exceptions.py
│       ├── arenas/
│       │   ├── __init__.py
│       │   ├── base.py                  # Abstract ArenaCollector base class
│       │   ├── registry.py              # Dynamic arena discovery/registration
│       │   ├── google_search/
│       │   │   ├── __init__.py
│       │   │   ├── collector.py
│       │   │   ├── router.py            # Standalone FastAPI router
│       │   │   ├── tasks.py             # Celery tasks
│       │   │   └── config.py            # Arena-specific settings
│       │   ├── google_autocomplete/
│       │   ├── social_media/
│       │   │   ├── facebook/
│       │   │   ├── x_twitter/
│       │   │   ├── instagram/
│       │   │   ├── youtube/
│       │   │   ├── tiktok/
│       │   │   ├── reddit/
│       │   │   ├── telegram/
│       │   │   ├── bluesky/
│       │   │   ├── gab/
│       │   │   ├── linkedin/
│       │   │   └── threads/
│       │   ├── news_media/
│       │   │   ├── rss_feeds/           # Curated Danish + international RSS
│       │   │   ├── gdelt/
│       │   │   ├── event_registry/      # NewsAPI.ai
│       │   │   └── ritzau_via/          # Via Ritzau press releases
│       │   └── web/
│       │       ├── majestic/
│       │       ├── common_crawl/
│       │       └── wayback/
│       ├── sampling/
│       │   ├── __init__.py
│       │   ├── network_expander.py      # Discover new actors from existing ones
│       │   ├── similarity_finder.py     # Find similar actors across platforms
│       │   └── snowball.py              # Snowball/chain-referral sampling
│       ├── analysis/
│       │   ├── __init__.py
│       │   ├── descriptive.py           # Volume, frequency, timeline statistics
│       │   ├── network.py               # Co-occurrence networks, actor networks
│       │   └── export.py                # CSV, XLSX, GEXF, JSON, Parquet export
│       ├── workers/
│       │   ├── __init__.py
│       │   ├── celery_app.py            # Celery configuration
│       │   ├── beat_schedule.py         # Periodic task scheduling for live tracking
│       │   └── rate_limiter.py          # Redis-based sliding window rate limiter (shared)
│       └── api/
│           ├── __init__.py
│           ├── main.py                  # FastAPI app assembly, mounts arena routers
│           ├── routes/
│           │   ├── auth.py              # POST /auth/login, /auth/refresh, /auth/logout
│           │   ├── users.py             # User CRUD (self + admin endpoints)
│           │   ├── credits.py           # Credit balance, allocation (admin), transactions
│           │   ├── query_designs.py     # CRUD for query designs (owner-scoped)
│           │   ├── collections.py       # Start/stop/status/cancel; POST /estimate (pre-flight, non-destructive); GET /{id}/stream (SSE)
│           │   ├── content.py           # Search/browse collected content (cursor-paginated)
│           │   ├── actors.py            # Actor management
│           │   └── analysis.py          # Trigger and retrieve analysis results; export job status
│           ├── dependencies.py          # get_current_user, require_admin, ownership guards
│           ├── middleware/
│           ├── templates/               # Jinja2 HTML templates
│           │   ├── base.html                    # Root: <html>, CDN links, nav, footer
│           │   ├── _partials/                   # Shared fragments included across views
│           │   │   ├── nav.html                 # Sidebar/top nav with active state
│           │   │   ├── flash.html               # Toast/banner messages
│           │   │   ├── credit_badge.html        # Balance display (HTMX-polled, in nav)
│           │   │   ├── pagination.html          # Cursor-based page controls
│           │   │   ├── empty_state.html         # Empty state card (icon + CTA)
│           │   │   └── loading_spinner.html     # hx-indicator spinner
│           │   ├── _fragments/                  # Partial renders returned by HTMX/SSE requests
│           │   │   ├── credit_estimate.html     # Pre-flight cost breakdown fragment
│           │   │   ├── task_row.html            # Per-arena task row (hx-swap-oob target)
│           │   │   ├── run_summary.html         # Run-level SSE summary fragment
│           │   │   ├── content_table_body.html  # Paginated content rows
│           │   │   └── term_row.html            # Search term row (add/remove target)
│           │   ├── auth/
│           │   │   ├── login.html               # Full-page, no nav; session expired banner
│           │   │   └── reset_password.html
│           │   ├── dashboard/
│           │   │   └── index.html               # Active runs, credit balance, recent activity
│           │   ├── query_designs/
│           │   │   ├── list.html                # Paginated table of owned designs
│           │   │   ├── detail.html              # Read-only with run history
│           │   │   └── editor.html              # Create/edit: terms + actor lists + arena config grid (Alpine)
│           │   ├── collections/
│           │   │   ├── launcher.html            # Config form + live pre-flight estimate panel
│           │   │   ├── list.html                # Run history
│           │   │   └── detail.html              # SSE-driven live status with per-arena task table
│           │   ├── content/
│           │   │   ├── browser.html             # Filter sidebar + paginated table (max 2,000 rows)
│           │   │   └── record_detail.html       # Expandable record detail panel
│           │   ├── actors/
│           │   │   ├── list.html                # Searchable actor directory
│           │   │   └── detail.html              # Profile, platform presences, content timeline
│           │   ├── analysis/
│           │   │   └── index.html               # Chart.js containers + export form
│           │   └── admin/
│           │       ├── users.html               # User list, activation toggle, role management
│           │       ├── credits.html             # Credit allocation form + transaction history
│           │       ├── credentials.html         # Credential pool (write-only: add/delete, no view)
│           │       └── health.html              # System health: DB, Redis, Celery, arena status
│           └── static/
│               ├── css/
│               │   └── app.css                  # Compiled Tailwind output (checked in, not generated at runtime)
│               ├── js/
│               │   ├── app.js                   # Alpine component definitions + HTMX global 401 handler
│               │   └── charts.js                # Chart.js initialisation per page
│               └── img/
│                   └── platform_icons/          # SVG icons per platform
├── docs/
│   ├── arenas/                  # Per-arena research briefs
│   ├── status/                  # Agent handoff status files
│   ├── decisions/               # Architectural Decision Records (ADRs)
│   ├── use_cases/               # Query specification documents
│   ├── gdpr/                    # DPIA template, privacy notice, legal basis documentation
│   └── ethics/                  # Research ethics self-assessment
├── reports/                     # Research reports for reference
│   ├── cross_platform_data_collection.md
│   └── danish_context_guide.md
└── tests/
    ├── conftest.py
    ├── factories/               # Test data factories
    ├── unit/
    ├── integration/
    └── arenas/                  # Per-arena test suites
```

> **Package layout**: This project uses the [src layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/) recommended by PyPA. All application code lives under `src/issue_observatory/`. Import paths use the `issue_observatory.` prefix (e.g., `from issue_observatory.arenas.base import ArenaCollector`). The `src/` directory is configured in `pyproject.toml` via `[tool.setuptools.packages.find] where = ["src"]`.

---

## Data Schema Design

### Universal Content Record (Layer 1)

The central table that every piece of collected content normalizes into. Partitioned by `published_at` month to enable efficient archival and query performance as the dataset grows.

```sql
-- Range-partitioned by published_at month
CREATE TABLE content_records (
    id                  UUID NOT NULL DEFAULT gen_random_uuid(),
    platform            VARCHAR(50) NOT NULL,          -- 'youtube', 'reddit', 'dr_rss', etc.
    arena               VARCHAR(50) NOT NULL,          -- 'social_media', 'news_media', 'google_search', etc.
    platform_id         VARCHAR(500),                  -- native ID on source platform
    content_type        VARCHAR(50) NOT NULL,          -- 'post', 'video', 'article', 'search_result', 'comment'
    text_content        TEXT,                          -- extracted/transcribed text
    title               TEXT,
    url                 VARCHAR(2000),
    language            VARCHAR(10),                   -- ISO 639-1 ('da', 'en', etc.)
    published_at        TIMESTAMPTZ,                   -- partition key
    collected_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Author (denormalized for query speed, FK to actors table)
    author_platform_id      VARCHAR(500),
    author_display_name     VARCHAR(500),
    author_id               UUID REFERENCES actors(id),
    pseudonymized_author_id VARCHAR(64),               -- SHA-256(platform + platform_user_id + project_salt)

    -- Engagement (nullable — not all platforms provide all metrics)
    views_count         BIGINT,
    likes_count         BIGINT,
    shares_count        BIGINT,
    comments_count      BIGINT,
    engagement_score    FLOAT,                         -- normalized cross-platform score

    -- Collection context
    collection_run_id   UUID REFERENCES collection_runs(id),
    query_design_id     UUID REFERENCES query_designs(id),
    search_terms_matched TEXT[],                       -- array of matched query terms
    collection_tier     VARCHAR(10) NOT NULL,          -- 'free', 'medium', 'premium'

    -- Platform-specific data (Layer 2)
    raw_metadata        JSONB DEFAULT '{}',
    media_urls          TEXT[],

    -- Search & deduplication
    content_hash        VARCHAR(64),                   -- SHA-256 of normalized text for dedup

    PRIMARY KEY (id, published_at),
    UNIQUE(platform, platform_id, published_at)
) PARTITION BY RANGE (published_at);

-- Indexes on the parent table (inherited by all partitions)
CREATE INDEX idx_content_platform ON content_records(platform);
CREATE INDEX idx_content_arena ON content_records(arena);
CREATE INDEX idx_content_published ON content_records(published_at);
CREATE INDEX idx_content_query ON content_records(query_design_id);
CREATE INDEX idx_content_terms ON content_records USING GIN(search_terms_matched);
CREATE INDEX idx_content_metadata ON content_records USING GIN(raw_metadata);
CREATE INDEX idx_content_hash ON content_records(content_hash);
CREATE INDEX idx_content_fulltext ON content_records
    USING GIN(to_tsvector('danish', coalesce(text_content, '') || ' ' || coalesce(title, '')));
```

### User Management & Credit System

```sql
-- Users (managed by FastAPI-Users)
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(320) UNIQUE NOT NULL,
    hashed_password VARCHAR(1024),                     -- null if using external IdP
    display_name    VARCHAR(200),
    role            VARCHAR(20) DEFAULT 'researcher',  -- 'researcher', 'admin'
    is_active       BOOLEAN DEFAULT false,             -- admin must activate new accounts
    api_key         VARCHAR(64) UNIQUE,                -- for programmatic API access
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ,
    metadata        JSONB DEFAULT '{}'
);

-- Credit allocations: admin grants credits to users per period
CREATE TABLE credit_allocations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    credits_amount  INTEGER NOT NULL,
    allocated_by    UUID REFERENCES users(id),         -- admin who allocated
    allocated_at    TIMESTAMPTZ DEFAULT NOW(),
    valid_from      DATE NOT NULL,
    valid_until     DATE,                              -- NULL = no expiry
    memo            TEXT                               -- e.g. "Q1 2026 project budget"
);

-- Credit consumption audit log
-- Credits map to actual API cost units:
--   free-tier arenas:       0 credits
--   YouTube Data API:       1 credit = 1 API unit (search = 100 credits)
--   Serper.dev:             1 credit = 1 SERP query
--   TwitterAPI.io:          1 credit = 1 tweet retrieved
--   TikTok Research API:    1 credit = 1 API request
CREATE TABLE credit_transactions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID REFERENCES users(id),
    collection_run_id   UUID REFERENCES collection_runs(id),
    arena               VARCHAR(50) NOT NULL,
    platform            VARCHAR(50) NOT NULL,
    tier                VARCHAR(10) NOT NULL,
    credits_consumed    INTEGER NOT NULL,
    transaction_type    VARCHAR(50) NOT NULL,          -- 'reservation', 'settlement', 'refund'
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    description         TEXT                           -- e.g. "youtube search: 100 units"
);

-- JWT refresh tokens (supports revocation)
CREATE TABLE refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    token_hash  VARCHAR(64) NOT NULL,                  -- SHA-256 of token
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

### API Credential Pool

```sql
-- Encrypted credential pool for multi-account API access
-- Credentials JSONB is encrypted with Fernet using CREDENTIAL_ENCRYPTION_KEY env var
CREATE TABLE api_credentials (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform        VARCHAR(50) NOT NULL,              -- 'youtube', 'telegram', 'tiktok', 'serper', etc.
    tier            VARCHAR(10) NOT NULL,              -- 'free', 'medium', 'premium'
    credential_name VARCHAR(200) NOT NULL,             -- human label, e.g. "YouTube key - researcher A"
    credentials     JSONB NOT NULL,                    -- Fernet-encrypted credential payload
    is_active       BOOLEAN DEFAULT true,
    daily_quota     INTEGER,                           -- NULL = unlimited
    monthly_quota   INTEGER,
    quota_reset_at  TIMESTAMPTZ,
    last_used_at    TIMESTAMPTZ,
    last_error_at   TIMESTAMPTZ,
    error_count     INTEGER DEFAULT 0,                 -- circuit-breaker counter
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_credentials_platform_tier ON api_credentials(platform, tier, is_active);
```

Redis keys track live quota state (TTL-based, no polling the database per request):
- `credential:quota:{id}:daily` — current daily usage counter (TTL = time to midnight)
- `credential:quota:{id}:monthly` — current monthly usage counter
- `credential:cooldown:{id}` — set on 429/FloodWait; expires after backoff period
- `credential:lease:{id}:{task_id}` — active task lease (TTL = expected task duration + buffer)

### Supporting Tables

```sql
-- Query Designs: the research instrument (owner-scoped)
CREATE TABLE query_designs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id        UUID REFERENCES users(id) NOT NULL,
    name            VARCHAR(200) NOT NULL,
    description     TEXT,
    visibility      VARCHAR(20) DEFAULT 'private',     -- 'private', 'team', 'public'
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    is_active       BOOLEAN DEFAULT true,
    default_tier    VARCHAR(10) DEFAULT 'free',
    language        VARCHAR(10) DEFAULT 'da',
    locale_country  VARCHAR(5) DEFAULT 'dk'
);

CREATE TABLE search_terms (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_design_id UUID REFERENCES query_designs(id) ON DELETE CASCADE,
    term            TEXT NOT NULL,
    term_type       VARCHAR(50) DEFAULT 'keyword',     -- 'keyword', 'phrase', 'hashtag', 'url_pattern'
    is_active       BOOLEAN DEFAULT true,
    added_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Actors: entities that publish content across platforms
CREATE TABLE actors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name  VARCHAR(500) NOT NULL,
    actor_type      VARCHAR(50),                       -- 'person', 'organization', 'media_outlet', 'government'
    description     TEXT,
    created_by      UUID REFERENCES users(id),
    is_shared       BOOLEAN DEFAULT false,             -- shared actors visible to all users
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    metadata        JSONB DEFAULT '{}'
);

CREATE TABLE actor_platform_presences (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id        UUID REFERENCES actors(id) ON DELETE CASCADE,
    platform        VARCHAR(50) NOT NULL,
    platform_user_id VARCHAR(500),
    platform_username VARCHAR(500),
    profile_url     VARCHAR(2000),
    verified        BOOLEAN DEFAULT false,
    follower_count  BIGINT,
    last_checked_at TIMESTAMPTZ,
    UNIQUE(platform, platform_user_id)
);

CREATE TABLE actor_lists (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_design_id UUID REFERENCES query_designs(id) ON DELETE CASCADE,
    name            VARCHAR(200) NOT NULL,
    description     TEXT,
    created_by      UUID REFERENCES users(id),
    sampling_method VARCHAR(50)                        -- 'manual', 'snowball', 'network', 'similarity'
);

CREATE TABLE actor_list_members (
    actor_list_id   UUID REFERENCES actor_lists(id) ON DELETE CASCADE,
    actor_id        UUID REFERENCES actors(id) ON DELETE CASCADE,
    added_at        TIMESTAMPTZ DEFAULT NOW(),
    added_by        VARCHAR(50) DEFAULT 'manual',
    PRIMARY KEY (actor_list_id, actor_id)
);

-- Collection management (owner-scoped)
CREATE TABLE collection_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_design_id UUID REFERENCES query_designs(id),
    initiated_by    UUID REFERENCES users(id) NOT NULL,
    mode            VARCHAR(20) NOT NULL,              -- 'batch' or 'live'
    status          VARCHAR(20) DEFAULT 'pending',
    tier            VARCHAR(10) DEFAULT 'free',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    date_from       TIMESTAMPTZ,                       -- for batch mode
    date_to         TIMESTAMPTZ,                       -- for batch mode
    arenas_config   JSONB DEFAULT '{}',                -- per-arena tier overrides
    estimated_credits INTEGER DEFAULT 0,              -- pre-flight estimate
    credits_spent   INTEGER DEFAULT 0,                 -- settled on completion
    error_log       TEXT,
    records_collected INTEGER DEFAULT 0
);

CREATE TABLE collection_tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_run_id UUID REFERENCES collection_runs(id) ON DELETE CASCADE,
    arena           VARCHAR(50) NOT NULL,
    platform        VARCHAR(50) NOT NULL,
    status          VARCHAR(20) DEFAULT 'pending',
    celery_task_id  VARCHAR(200),
    credential_id   UUID REFERENCES api_credentials(id),  -- which credential was used
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    records_collected INTEGER DEFAULT 0,
    error_message   TEXT,
    rate_limit_state JSONB DEFAULT '{}'
);
```

---

## Arena Implementation Guide

### Abstract Base Class

Every arena collector inherits from a common interface. It accepts an optional `CredentialPool` and `RateLimiter`, keeping credential rotation and rate enforcement transparent to individual arena implementations.

```python
# src/issue_observatory/arenas/base.py
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from issue_observatory.core.credential_pool import CredentialPool
    from issue_observatory.workers.rate_limiter import RateLimiter

class Tier(str, Enum):
    FREE = "free"
    MEDIUM = "medium"
    PREMIUM = "premium"

class ArenaCollector(ABC):
    """Base class for all arena data collectors."""

    arena_name: str
    platform_name: str
    supported_tiers: list[Tier]

    def __init__(
        self,
        credential_pool: Optional["CredentialPool"] = None,
        rate_limiter: Optional["RateLimiter"] = None,
    ):
        self.credential_pool = credential_pool
        self.rate_limiter = rate_limiter

    @abstractmethod
    async def collect_by_terms(
        self,
        terms: list[str],
        tier: Tier,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        max_results: Optional[int] = None,
    ) -> list[dict]:
        """Collect content matching search terms."""

    @abstractmethod
    async def collect_by_actors(
        self,
        actor_ids: list[str],
        tier: Tier,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        max_results: Optional[int] = None,
    ) -> list[dict]:
        """Collect content from specific actors/accounts."""

    @abstractmethod
    def get_tier_config(self, tier: Tier) -> dict:
        """Return the API/service configuration for a given tier."""

    @abstractmethod
    def normalize(self, raw_item: dict) -> dict:
        """Normalize platform-specific data to universal content record."""

    async def health_check(self) -> dict:
        """Check if the arena's data sources are accessible."""
        return {"status": "not_implemented"}
```

Each arena also exposes a **standalone FastAPI router** that can be imported and run independently for testing or ad-hoc collection without the full application.

---

## Frontend Design

The frontend is served directly from FastAPI using **Jinja2 templates + HTMX + Alpine.js**. This keeps the entire application in a single Python codebase with no continuous JavaScript build pipeline.

- **HTMX** handles all server communication: form submission, pagination, SSE-based live status, and inline CRUD via HTML attributes.
- **Alpine.js** (CDN, ~15KB) handles local browser state: the per-arena tier configuration grid, pre-flight estimate debouncing, form section show/hide, and client-side validation feedback. Alpine components are kept small (< 100 lines each); if any grows beyond that, the interaction design should be simplified.
- **Tailwind CSS** provides styling. The compiled `app.css` is generated once with `npx tailwindcss` and checked into the repository — not regenerated at runtime. This is a documented `make css` step, not a watch process.
- **Chart.js** (CDN) renders descriptive statistics. Network analysis is exported as GEXF for Gephi; no in-browser graph rendering.

**Viewport target**: Desktop-first, minimum 1024px. No mobile-specific breakpoints in the initial implementation.

**Reconsideration triggers**: Migrate to a full SPA (React + Vite) if: (a) in-browser network graph visualisation becomes a requirement, (b) multi-user real-time collaboration is needed, (c) any Alpine component exceeds ~150 lines of logic, or (d) a JavaScript engineer joins the team.

### Authentication Flow

- FastAPI-Users configured with `CookieTransport` — JWT access token stored as **HttpOnly cookie** (SameSite=Lax, short-lived 15–30 min) plus a refresh token cookie (HttpOnly, Secure, 7–30 days). Never localStorage.
- Server-side silent refresh: FastAPI middleware attempts a refresh before returning 401, eliminating most session interruptions for active users.
- Client-side fallback: `app.js` registers an `htmx:responseError` handler — on 401, saves `window.location.pathname` to `sessionStorage` and redirects to `/auth/login?session_expired=1`.
- Login redirect: `POST /auth/login` returns `303 → ?next=` parameter (validated same-origin). Post-login reads `sessionStorage` redirect target.
- New accounts are inactive (`is_active = false`) until an admin enables them. The login form shows a clear "account pending activation" message.

### Credit UI Surfaces

**1. Persistent balance widget** — In the navigation bar. Implemented as a Jinja2 include (`_partials/credit_badge.html`) polled every 30 seconds with `hx-trigger="load, every 30s"`. Displays: total credits, reserved (in-progress runs), effective available.

**2. Pre-flight cost estimate** — The collection launcher form includes a live estimate panel. Alpine debounces arena/tier changes (400ms), then HTMX fires `GET /api/collections/estimate` with the current form state. The response fragment (`_fragments/credit_estimate.html`) shows per-arena breakdown, total cost, remaining balance after the run, and a warning if insufficient. The launch button is Alpine-disabled when `estimated_credits > available_credits`.

**3. Credit transaction history** — On the user profile / Credits page: a paginated `credit_transactions` table and a Chart.js bar chart of credits consumed by arena over time.

### Credential Management (Admin Panel)

The credential API is **write-only**: credentials are never returned in any response, even to admins. The UI enforces this:

- **List view**: Shows credential name, platform, tier, is_active, last_used_at, error_count, and Redis-sourced quota utilisation. No credential values.
- **Add form**: Platform-specific fields (e.g., YouTube: `api_key`; Telegram: `api_id`, `api_hash`, `session_string`) rendered as `<input type="password">`. Submitted over HTTPS; encrypted server-side before storage.
- **No edit operation**: To update a credential value, delete and re-add. This simplifies the API contract and matches the mental model of secrets managers.
- **Actions**: Active/inactive toggle, error count reset (for circuit-breaker recovery), delete.

### Required Views

| Section | Views |
|---------|-------|
| Auth | Login (with session-expired banner variant), password reset |
| Dashboard | Active collection runs, credit balance, recent activity feed |
| Query Designs | List; editor (terms panel, actor lists panel, Alpine-powered arena config grid) |
| Collections | Launcher (with live pre-flight estimate); SSE-driven live status monitor; run history |
| Content | Server-filtered/paginated browser (max 2,000 visible rows; export prompt above that); record detail panel |
| Actors | Searchable directory; profile with platform presences and content timeline |
| Analysis | Chart.js descriptive statistics; export form (CSV/XLSX/GEXF/JSON/Parquet) |
| Admin | User list + activation; credit allocation; credential pool (write-only); system health |

### HTMX Patterns Reference

| Pattern | Use case |
|---------|----------|
| `hx-get` + `hx-target` | Filter changes reload table body; pagination loads next page |
| `hx-post` + `hx-swap="outerHTML"` | Add a search term; returns new `<li>` to replace placeholder |
| `hx-delete` + `hx-swap="delete"` | Remove a term/actor; targets `closest li` |
| `hx-ext="sse"` + `sse-swap` | Live run status; summary panel updates |
| `hx-swap-oob="true"` | SSE events update individual task rows and summary simultaneously |
| `sse-close="run_complete"` | Closes SSE connection when run finishes |
| `hx-indicator` | Shows `_partials/loading_spinner.html` during requests |
| `HX-Redirect` response header | Collection run launch → navigate to status page |
| `hx-trigger="revealed"` | Infinite-scroll append for content browser (capped at 2,000 rows) |

Live collection status uses FastAPI Server-Sent Events (`/api/collections/{run_id}/stream`) consumed via HTMX's `hx-ext="sse"` extension. Individual task row updates use `hx-swap-oob` so a single SSE event can update both the specific arena row and the overall run summary without replacing the whole table.

---

## Phased Implementation Plan

### Pre-Phase: Ethics & Legal Preparation (Before Week 1)

> These are documents, not code. They must exist before data collection begins (Phase 1).

| Task | Description |
|------|-------------|
| E.1 | Draft DPIA (Data Protection Impact Assessment) per Datatilsynet guidelines. Establish legal basis: Art. 6(1)(e) + Art. 89 GDPR for university research; Databeskyttelsesloven §10 |
| E.2 | Write public privacy notice (Art. 14(5)(b) GDPR) for collected social media content |
| E.3 | Research ethics self-assessment: data collected, from whom, storage, access, retention, pseudonymisation approach, multi-account justification (Telegram, YouTube) |
| E.4 | Confirm Meta Content Library application status (submitted via ICPSR? IRB approval obtained? ~$371/mo + $1,000 setup). Document fallback path (Bright Data) if rejected |
| E.5 | Telegram channel discovery: curate initial list of Danish public channels via domain knowledge + cross-referencing known actors from other platforms. Document as use case in `docs/use_cases/telegram_danish.md` |

---

### Phase 0: Foundation (Weeks 1–4)

**Goal**: Core infrastructure, database, auth, credential pool, rate limiter, and one working arena.

> Phase 0 is extended from the original 8 tasks. The additions (0.9–0.13) are blocking dependencies for Phase 1 — retrofitting auth, user scoping, credential pooling, rate limiting, or table partitioning after arenas are built is disproportionately costly.

| Task | Description | Owner |
|------|-------------|-------|
| 0.1 | Project init: pyproject.toml, Docker Compose (PostgreSQL, Redis, MinIO), directory structure | Core Engineer |
| 0.2 | Database models and Alembic initial migration: all core tables including `content_records` with `published_at` range partitioning, `users`, `credit_allocations`, `credit_transactions`, `refresh_tokens`, `api_credentials` | DB Engineer |
| 0.3 | Base `ArenaCollector` class (with `credential_pool` + `rate_limiter` constructor args), normalizer pipeline, Celery configuration | Core Engineer |
| 0.4 | FastAPI skeleton: main app, Jinja2 template engine, query design CRUD, collection run management | Core Engineer |
| 0.5 | Settings/config system with tier support and Danish defaults; stub `CredentialPool` (env-var backed, same interface as full pool) | Core Engineer |
| 0.6 | Redis-based sliding window `RateLimiter` in `workers/rate_limiter.py`; required by all Phase 1 arenas | Core Engineer |
| 0.7 | FastAPI-Users integration: `User` model, JWT auth endpoints (`/auth/login`, `/auth/refresh`, `/auth/logout`), `CookieTransport` for browser sessions, `get_current_user` + `require_admin` dependencies, admin bootstrap script, API key generation | Core Engineer |
| 0.8 | `CreditService` in `core/credit_service.py`: credit balance lookup, pre-flight estimation (`POST /api/collections/estimate`), reservation, settlement, refund; wire into collection run create/complete/fail lifecycle | DB Engineer |
| 0.9 | **Frontend foundation**: Tailwind CSS build (`make css`); `base.html` with CDN links for HTMX, Alpine.js, Chart.js; login page with session-expired banner variant; `app.js` with HTMX global 401 handler and silent-refresh logic; dashboard skeleton; credit balance widget in nav (HTMX-polled) | Core Engineer |
| 0.9b | **Minimum viable collection UI**: Query design list + basic create/edit form (terms panel only, no arena grid yet); collection run launcher with pre-flight estimate panel; run status page shell (SSE-ready); admin panel with user activation and credit allocation form | Core Engineer |
| 0.10 | Structured JSON logging (all modules), `/health` endpoint per arena contract, error tracking in `collection_tasks.error_message` | Core Engineer |
| 0.11 | Automated daily PostgreSQL dump script + MinIO bucket versioning; document backup/restore procedure | DB Engineer |
| 0.12 | Port Google Search arena from Issue Observatory Search (adapted to new schema, using `CredentialPool` stub and `RateLimiter`) | Core Engineer |
| 0.13 | CI setup: pytest, linting (ruff), type checking (mypy), pre-commit hooks; integration test: end-to-end Google Search collection run with auth; smoke test of login → query design create → collection launch flow via UI | QA Engineer |

**Milestone**: Authenticated app where a user logs in, creates a query design (owned by that user), executes a Google Search collection run with credit pre-flight check, and stores normalised results — all verifiable through the UI. Admin can activate users, allocate credits, and view all runs.

---

### Phase 1: Free-Tier Arenas (Weeks 5–9)

**Goal**: Add all arenas achievable at the free tier. Full credential pool, user-scoped data, GDPR baseline active.

| Task | Priority | Description | Tier |
|------|----------|-------------|------|
| 1.1 | Critical | **Database-backed `CredentialPool`**: Fernet encryption, Redis lease/quota/cooldown tracking, `acquire(platform, tier)` / `release()` / `report_error()` API; migrate YouTube, Telegram, TikTok arenas to use it | — |
| 1.2 | Critical | **GDPR baseline**: `pseudonymized_author_id` populated on all ingested records; configurable retention policy enforcement (delete records older than threshold); per-actor deletion endpoint (required for data subject requests) | DB Engineer |
| 1.3 | Critical | **User scoping**: Apply `owner_id` / `initiated_by` filters to all query design and collection run CRUD; add `visibility` checks; wire credit pre-flight into collection run creation | Core Engineer |
| 1.4 | Critical | **Google Autocomplete** — undocumented endpoint + Serper.dev, `gl=dk`, `hl=da` | Free + Medium |
| 1.5 | Critical | **Bluesky** — AT Protocol `searchPosts`, Jetstream firehose for real-time, `lang:da` filter | Free |
| 1.6 | Critical | **Reddit** — PRAW streaming + search, r/Denmark and configurable subreddits | Free |
| 1.7 | Critical | **YouTube** — Data API v3 search + metadata, RSS feeds for channels, youtube-transcript-api; pool multiple GCP project keys via `CredentialPool` | Free |
| 1.8 | Critical | **Danish RSS feeds** — DR 20+ feeds, TV2, BT, Politiken, Berlingske, Information, Ekstra Bladet, Nordjyske, Fyens Stiftstidende; feedparser polling | Free |
| 1.9 | High | **GDELT** — DOC API, `sourcelang:danish` filter, 15-min updates | Free |
| 1.10 | High | **Telegram** — Telethon event handlers for curated public channels; 2–3 accounts via `CredentialPool`; honour `FloodWaitError` wait times exactly | Free |
| 1.11 | High | **TikTok** — Research API (access confirmed); handle 10-day engagement lag | Free |
| 1.12 | Medium | **Via Ritzau** — REST API for press releases (free, unauthenticated) | Free |
| 1.13 | Medium | **Gab** — Mastodon-compatible API, OAuth 2.0 | Free |
| 1.14 | — | **Full query design editor**: Alpine-powered per-arena tier configuration grid (reactive credit estimate computed client-side from pre-loaded JSON credit table); actor list sub-panel with HTMX autocomplete; visibility controls | — |
| 1.15 | — | **Live collection status monitor**: SSE-driven per-arena task table using `hx-swap-oob` for row-level updates; cancel and retry controls; `sse-close="run_complete"` redirect to content browser on completion | — |
| 1.16 | — | **Content browser**: Server-side filter sidebar (arena, platform, date range, terms, actor, language); cursor-paginated table with `hx-trigger="revealed"` infinite scroll; 2,000-row cap with export prompt; expandable record detail panel | — |
| 1.17 | — | Actor management UI: directory, profile pages, platform presence management | — |
| 1.18 | — | Admin credential pool UI: list view with Redis quota utilisation; add form (platform-specific fields, `type="password"`); active/inactive toggle; delete; no view/edit of stored values | — |
| 1.19 | — | Email notification service: collection failure alerts, low-credit warnings (SMTP via `fastapi-mail`) | — |

**Milestone**: 10+ arenas operational at free tier. All data is user-scoped. GDPR baseline (pseudonymisation, retention, per-actor deletion) active. Batch and live collection for a Danish query design — all verifiable through the UI without touching the API docs.

---

### Phase 2: Paid-Tier Arenas & Actor Discovery (Weeks 10–14)

**Goal**: Medium/premium tier options, actor-based collection, network sampling. Full credential pool coverage.

| Task | Priority | Description | Tier |
|------|----------|-------------|------|
| 2.1 | Critical | **X/Twitter** — TwitterAPI.io ($0.15/1K, medium), official Pro ($5K/mo, premium) | Medium + Premium |
| 2.2 | Critical | **Google SERP** — Serper.dev ($0.30/1K, medium), SerpAPI (premium); credential pool for key rotation | Medium + Premium |
| 2.3 | High | **Facebook/Instagram** — Meta Content Library (decision point: approved or Bright Data fallback) | Medium + Premium |
| 2.4 | High | **Event Registry / NewsAPI.ai** — Danish NLP, token-based ($90/mo+) | Medium |
| 2.5 | High | **LinkedIn** — DSA researcher access, Zeeschuimer browser capture fallback | Premium |
| 2.6 | High | **Threads** — Meta Content Library (if approved), Threads API | Free + Medium |
| 2.7 | Medium | **Majestic** — Backlink/trust flow tracking ($400/mo) | Premium |
| 2.8 | Medium | **Network-based actor sampling** — Discover connected actors via follower graphs, co-mention, co-hashtag | — |
| 2.9 | Medium | **Similarity-based actor discovery** — Find similar accounts via platform recommendations or embeddings | — |
| 2.10 | Low | **Common Crawl / Wayback** — Historical web snapshots for batch analysis | Free |

**Decision point at start of Phase 2**: Confirm Meta Content Library application status. If not approved within 2 weeks of Phase 2 start, proceed with Bright Data fallback for Facebook/Instagram.

**Milestone**: Full three-tier pricing operational. Actor-based collection. Network sampling tools. Credential pool covers all paid arenas.

---

### Phase 3: Analysis, Export & Hardening (Weeks 15–19)

| Task | Priority | Description |
|------|----------|-------------|
| 3.1 | Critical | **Descriptive statistics backend**: Volume over time, top actors, top terms, engagement distributions |
| 3.2 | Critical | **Network analysis backend**: Actor co-occurrence, cross-platform mapping, term co-occurrence, bipartite networks |
| 3.3 | Critical | **Export backend**: CSV (flat), XLSX (UTF-8 safe for Danish characters), GEXF (Gephi networks), JSON (full records), Parquet (large datasets); filterable; large exports as Celery tasks with status indicator |
| 3.4 | Critical | **Analysis & export UI**: Chart.js descriptive statistics dashboard (volume over time, top actors, engagement distributions); export form with filter configuration, format selector, credit-cost estimate for large jobs, download link; Celery-task export status indicator |
| 3.5 | High | **Live tracking hardening**: Celery Beat scheduling, daily status, credit deduction per live-tracking cycle, run suspension on insufficient credits |
| 3.6 | High | **GDPR advanced**: Near-duplicate detection, named entity pseudonymisation in `text_content`, MinHash/LSH deduplication, DPIA finalisation |
| 3.7 | High | **Admin system health UI**: PostgreSQL size/performance, Redis queue depth, Celery worker status, per-arena health check results; quota dashboarding with "credential pool at 90% daily quota" alerts |
| 3.8 | Medium | **Deduplication**: Content hash cross-arena URL dedup (basic dedup is in Phase 0 via `content_hash`; this covers cross-arena near-duplicates) |
| 3.9 | Medium | **Entity resolution**: Fuzzy actor matching across platforms, manual merge/split |
| 3.10 | Medium | **Inbound API rate limiting**: `slowapi` middleware to throttle requests to the FastAPI application itself |
| 3.11 | Medium | **Documentation**: API docs, arena config guide, deployment guide, secrets management guide (Docker Secrets or Vault for `CREDENTIAL_ENCRYPTION_KEY`), Tailwind CSS rebuild instructions |
| 3.12 | Low | **Monitoring**: Prometheus metrics, Grafana dashboards; structured logging is Phase 0, this adds metrics and visualisation |

**Milestone**: Complete application with collection, analysis, export, and hardened operations. Research-ready for Danish context.

---

## Arena Tier Configuration Matrix

| Arena | Platform | Free Tier | Medium Tier ($) | Premium Tier ($$) |
|-------|----------|-----------|-----------------|-------------------|
| Google Search | Google | — | Serper.dev ($0.30/1K) | SerpAPI ($2.75–25/1K) |
| Google Autocomplete | Google | Undocumented endpoint | Serper.dev | SerpAPI |
| Social Media | Bluesky | AT Protocol (unlimited) | — | — |
| Social Media | Reddit | PRAW (100 req/min) | — | — |
| Social Media | YouTube | Data API v3 (10K units/day per GCP project, pool multiple keys) + RSS | — | — |
| Social Media | TikTok | Research API (1K req/day) | Bright Data ($1/1K) | — |
| Social Media | Telegram | Telethon (free, 2–3 accounts via pool) | — | — |
| Social Media | X/Twitter | — | TwitterAPI.io ($0.15/1K) | Official Pro ($5K/mo) |
| Social Media | Facebook | — | Bright Data ($250/100K) | Meta Content Library |
| Social Media | Instagram | — | Bright Data ($1.50/1K) | Meta Content Library |
| Social Media | LinkedIn | — | — | DSA Art. 40 access |
| Social Media | Threads | Threads API (limited) | — | Meta Content Library |
| Social Media | Gab | Mastodon API (free) | — | — |
| News Media | Danish RSS | feedparser (free) | Inoreader ($7.50/mo) | — |
| News Media | GDELT | DOC API (free) | — | — |
| News Media | Event Registry | — | NewsAPI.ai ($90/mo) | NewsAPI.ai ($490/mo) |
| News Media | Via Ritzau | REST API (free) | — | — |
| Web | Common Crawl | Athena (~$1.50/scan) | — | — |
| Web | Majestic | — | — | API ($400/mo) |
| Web | Wayback | CDX API (free) | — | — |

---

## Danish-Specific Defaults

The `config/danish_defaults.py` module provides:

- **Locale**: `gl=dk`, `hl=da` for Google APIs; `lang=da` for platform filters
- **Curated RSS feeds**: 30+ Danish outlets (DR, TV2, BT, Politiken, Berlingske, Ekstra Bladet, Information, JP, Nordjyske, Fyens Stiftstidende, Børsen, Kristeligt Dagblad)
- **Default subreddits**: `['Denmark', 'danish', 'copenhagen', 'aarhus']`
- **GDELT filters**: `sourcelang:danish`, `sourcecountry:DA`
- **PostgreSQL FTS**: Danish dictionary (`to_tsvector('danish', ...)`)
- **Bluesky search**: `lang:da` filter
- **Pseudonymisation salt**: project-specific `PSEUDONYMIZATION_SALT` env var; SHA-256(platform + platform_user_id + salt)

---

## Key Technical Decisions

**PostgreSQL JSONB over separate document DB**: JSONB provides document-store flexibility with ACID guarantees and SQL joins. No extra infrastructure. GIN indexes allow efficient queries into platform-specific fields.

**`content_records` partitioned by `published_at`**: Range partitioning by month enables efficient archival of old data, faster queries on recent data, and allows dropping old partitions without a full-table delete. This must be in the initial migration — adding partitioning to a large table retroactively is impractical.

**Celery over alternatives**: Proven in existing codebase. Handles rate-limited API calls with retry/backoff, periodic scheduling via Celery Beat for live tracking, task chaining, and task state visibility.

**FastAPI over Django/Flask**: Native async for I/O-bound collection. Auto-generated OpenAPI docs per arena. Pydantic validation. Router system maps cleanly to arena modularity.

**HTMX + Alpine.js + Jinja2 over React/SvelteKit**: The team is Python-first. The dominant interaction model is forms and tables — HTMX's native territory. Alpine.js (CDN, no build step) fills the local-state gap for the arena configuration grid and pre-flight estimate debouncing without introducing a framework. Chart.js via CDN covers descriptive statistics; researchers export GEXF for network visualisation in Gephi. The stack is reconsidered if in-browser network graphs, multi-user real-time collaboration, or a JavaScript engineer joins. **HttpOnly cookie transport** for browser JWTs prevents XSS token theft; API key bearer tokens remain for programmatic access.

**CredentialPool with Fernet encryption**: API credentials for paid arenas are stored encrypted in the database (not as flat env vars), enabling multi-account rotation for YouTube (multiple GCP project keys) and Telegram (multiple user sessions) while keeping secrets managed centrally. The `CREDENTIAL_ENCRYPTION_KEY` is the only secret that must be managed carefully at the environment level.

**Credit system maps to API cost units**: Credits directly correspond to monetary cost (1 credit = 1 Serper query, 1 YouTube API unit, etc.). This makes budget allocation by an admin meaningful and allows per-run cost estimation before execution.

**GDPR baseline in Phase 0/1, not Phase 3**: Pseudonymisation (`pseudonymized_author_id`), retention enforcement, and per-actor deletion must be operational before any data is collected. The DPIA and privacy notice must exist before Phase 1 begins. Phase 3 adds advanced pseudonymisation (NER in text) and near-duplicate detection; the legal baseline is not deferred.

**Deduplication**: Three layers — (1) `UNIQUE(platform, platform_id, published_at)` on the partitioned table prevents duplicate ingestion, (2) `content_hash` SHA-256 catches cross-platform reposts, (3) MinHash/LSH for near-duplicate detection (Phase 3).

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Meta Content Library rejected or delayed | Loss of FB/IG/Threads compliant access | Bright Data fallback documented; explicit decision point at Phase 2 start |
| X/Twitter third-party APIs shutdown | Loss of affordable access | Abstract data source via ArenaCollector; swap to official or DSA access |
| GDPR complaint | Legal disruption | DPIA + privacy notice pre-Phase 1; pseudonymisation from first record; per-actor deletion endpoint |
| TikTok Research API deprecated | Loss of free tier | Bright Data fallback in tier config |
| YouTube quota exhaustion | Incomplete data | Multi-key credential pool; 10K units/day per GCP project key |
| Telegram account bans | Loss of channel monitoring | 2–3 accounts via credential pool; honour FloodWait exactly; document in ethics paperwork |
| Rate limiting causes gaps | Incomplete data | Redis-based shared RateLimiter from Phase 0; backoff; retry logic; completion tracking |
| Danish RSS feeds discontinued | News gaps | Health monitoring; GDELT/Event Registry fallback |
| Credential encryption key lost | All stored API credentials unrecoverable | Document key backup procedure; use Docker Secrets or Vault in production |
| User credit balance miscalculation | Over/under-charging users | Credit reservation+settlement pattern with explicit refund on failure; audit log in `credit_transactions` |

---

## Definition of Done (per Arena)

1. Implements `ArenaCollector` base class with all abstract methods
2. All supported tiers functional; credentials acquired via `CredentialPool` (not hardcoded env vars)
3. Normalizer maps to universal content record correctly, including `pseudonymized_author_id`
4. Standalone FastAPI router works independently
5. Celery tasks use shared `RateLimiter`; handle retries, error reporting, `NoCredentialAvailableError`
6. Both `collect_by_terms` and `collect_by_actors` implemented (where supported)
7. Integration tests pass with real or recorded API fixtures
8. Danish defaults applied (locale, language filters)
9. Health check endpoint verifies API accessibility and is reflected in the admin health dashboard
10. Arena appears in the collection launcher's arena configuration grid (enabled/disabled toggle, tier selector)
11. Arena README documents tier comparison, rate limits, multi-account notes, and known limitations

## Frontend Build Reference

```bash
# Rebuild Tailwind CSS after template changes (requires Node.js installed once)
make css
# Equivalent to:
npx tailwindcss -i ./src/issue_observatory/api/static/css/input.css -o ./src/issue_observatory/api/static/css/app.css --minify
```

CDN dependencies (all pinned to exact versions with integrity hashes in `base.html`):
- HTMX 2: `https://unpkg.com/htmx.org@2/dist/htmx.min.js`
- HTMX SSE extension: `https://unpkg.com/htmx-ext-sse@2/sse.js`
- Alpine.js 3: `https://cdn.jsdelivr.net/npm/alpinejs@3/dist/cdn.min.js`
- Chart.js 4: `https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js`

For air-gapped or offline deployments (common in university infrastructure), self-host all CDN files under `src/issue_observatory/api/static/vendor/` and update the `base.html` `<script>` paths accordingly.
