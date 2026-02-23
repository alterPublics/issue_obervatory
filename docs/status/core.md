# Core Application Engineer — Status

## Bug Fixes (Ongoing)

- [x] F-07/F-08 credential pool env var fallback (2026-02-23): Fixed "No credential available" errors for arenas with .env-configured API keys when called from Celery workers. Root cause: `load_dotenv()` was only called in `api/main.py` (FastAPI), not in `workers/celery_app.py` (Celery). Pydantic Settings loads `.env` into its model but does NOT inject values into `os.environ`. `CredentialPool` reads from `os.environ` for env var fallback. Fix: added `from dotenv import load_dotenv` and `load_dotenv()` call to `workers/celery_app.py` before importing `Settings`, matching the pattern in `api/main.py`. Applies to all Celery workers and Beat scheduler. Decision record: `docs/decisions/F07_F08_credential_pool_env_var_fallback.md`.

## Socialt Bedrageri Recommendations (P2)

- [x] SB-09 backend complete (2026-02-20): RSS feed autodiscovery. New `arenas/rss_feeds/feed_discovery.py` module with `discover_feeds(url)` function. Discovery algorithm: (1) fetch HTML, (2) parse `<link rel="alternate">` tags with RSS/Atom content types, (3) probe common feed paths (`/rss`, `/feed`, `/atom.xml`, etc.) if no tags found, (4) verify with HEAD requests. New endpoint `POST /query-designs/{design_id}/discover-feeds` accepts website URL, returns list of discovered feed URLs with titles and types for one-click addition to `arenas_config["rss"]["custom_feeds"]`. Added `beautifulsoup4>=4.12,<5.0` dependency to `pyproject.toml`. Documentation: `ADR-012-source-discovery-assistance.md`, `SB-09-SB-10-source-discovery.md`.
- [x] SB-10 backend complete (2026-02-20): Reddit subreddit suggestion. New `arenas/reddit/subreddit_suggestion.py` module with `suggest_subreddits(reddit, query, limit)` function using Reddit's `/subreddits/search` API. New endpoint `GET /query-designs/{design_id}/suggest-subreddits?query=...&limit=20` accepts optional query (defaults to query design's active search terms), returns list of subreddit metadata (name, subscribers, description, active users) for one-click addition to `arenas_config["reddit"]["custom_subreddits"]`. FREE-tier asyncpraw call. No new dependencies required.

## Greenland Roadmap

- [x] GR-01 backend complete (2026-02-19): Researcher-configurable RSS feed list via `arenas_config["rss"]["custom_feeds"]`. Added `extra_feed_urls` param to `collect_by_terms()`/`collect_by_actors()` in RSS collector, `_merge_extra_feeds()` helper deduplicates URLs, tasks.py loads arenas_config and passes extra feeds.
- [x] GR-02 backend complete (2026-02-19): Researcher-configurable Telegram channel list via `arenas_config["telegram"]["custom_channels"]`. Added `extra_channel_ids` param to Telegram `collect_by_terms()`, merged into channel list alongside actor_ids. Tasks.py wired accordingly.
- [x] GR-03 backend complete (2026-02-19): Researcher-configurable Reddit subreddit list via `arenas_config["reddit"]["custom_subreddits"]`. Added `extra_subreddits` param to `collect_by_terms()`, `_build_subreddit_string()` helper merges with Danish defaults to produce `+`-joined multireddit string. `_search_term()` accepts optional `subreddit_string`. Tasks.py wired accordingly.
- [x] GR-04 backend complete (2026-02-19): Discord channel IDs via `arenas_config["discord"]["custom_channel_ids"]` and Wikipedia seed articles via `arenas_config["wikipedia"]["seed_articles"]`. `_merge_channel_ids()` deduplicates Discord channel lists. Wikipedia `collect_by_terms()` collects revisions+pageviews directly for seed article titles (bypassing search). Both tasks.py files load and pass arenas_config values.
- [x] GR-05 backend complete (2026-02-19): Language list via `arenas_config["languages"]` takes priority over `query_design.language` in `trigger_daily_collection` in `workers/tasks.py`. Falls back to single-language field if arenas_config languages not set.
- [x] GR-05 PATCH endpoint complete (2026-02-19): `PATCH /query-designs/{design_id}/arena-config/{arena_name}` deep-merges payload into `arenas_config[arena_name]` sub-dict. `arena_name == "global"` writes to arenas_config root (for languages list). Response: `ArenaCustomConfigResponse(arena_name, arenas_config_section)`.
- [x] GR-17 backend complete (2026-02-19): `POST /actors/quick-add`, `POST /actors/quick-add-bulk`, `GET /query-designs/{id}/actor-lists` — single-step actor creation from Content Browser, idempotent by (platform, platform_username), optional actor-list membership.
- [x] GR-22 backend complete (2026-02-19): `analysis/link_miner.py` (LinkMiner class with regex URL extraction, platform classification, source-count aggregation, DiscoveredLink dataclass), `GET /content/discovered-links` endpoint (grouped by platform, filterable, min_source_count threshold), `POST /actors/quick-add-bulk` (bulk import from Discovered Sources panel).
- [x] GR-14 normalizer bypass complete (2026-02-19): Public-figure pseudonymization exception. `Normalizer.pseudonymize_author()` extended with `is_public_figure: bool = False` and `platform_username: str | None = None` — when `True`, returns the raw handle instead of the SHA-256 hash. `Normalizer.normalize()` extended with `is_public_figure`, `platform_username`, and `public_figure_ids: set[str] | None` params; when `public_figure_ids` is supplied the normalizer auto-detects matching authors. Audit annotation (`public_figure_bypass: true`, `bypass_reason`) added to `raw_metadata` on every bypassed record. `ArenaCollector` base class gains `_public_figure_ids: set[str]` attribute and `set_public_figure_ids(ids)` method. `GoogleSearchCollector.normalize()` forwards `self._public_figure_ids` to the normalizer. New `fetch_public_figure_ids_for_design()` async helper in `workers/_task_helpers.py` queries `actor_platform_presences` via `actor_list_members` → `actor_lists` for all `public_figure=True` actors in a query design. `trigger_daily_collection` calls the helper once per design, converts the result to a list, and passes it as `public_figure_ids` to every arena's `collect_by_terms` Celery task. Google Search task accepts `public_figure_ids: list[str] | None = None` and calls `collector.set_public_figure_ids()` before collection. Default behaviour (no bypass) is unchanged for all existing callers.
- [x] GR-11 backend complete (2026-02-19): Coordinated posting detection enricher. New `CoordinationDetector(ContentEnricher)` in `analysis/enrichments/coordination_detector.py` — sliding-window algorithm finds the 1-hour window with the most distinct authors in a near-duplicate cluster, flags clusters where distinct_authors >= threshold (default 5), computes coordination_score normalised 0-1 across all clusters in a batch. New `analysis/coordination.py` with `get_coordination_events()` async query function (DISTINCT ON cluster_id, filtered by flagged=true and min_score). `DeduplicationService.run_coordination_analysis()` added to `core/deduplication.py` (two-pass: pre-pass for cross-cluster normalisation, second pass to persist enrichment via JSONB SET). Module-level `run_coordination_analysis()` wrapper added. `CoordinationDetector` exported from `analysis/enrichments/__init__.py`.
- [x] GR-12 backend complete (2026-02-19): Optional Wayback Machine content retrieval. Added `fetch_content: bool = False` parameter to `collect_by_terms()` and `collect_by_actors()` in `WaybackCollector`. New `_fetch_single_record_content()` fetches archived page via playback URL, handles 503 with single retry, enforces 500 KB size guard, extracts text with `extract_from_html()` (trafilatura primary, fallback tag-strip). New `_fetch_content_for_records()` orchestrates batch with per-tier cap (FREE: 50, MEDIUM: 200) and `asyncio.Semaphore(1)` + 4 s sleep to enforce 15 req/min limit. On success: sets `text_content`, `content_type="web_page"`, `raw_metadata["content_fetched"]=true`, `content_fetch_url`, `content_fetched_at`, `extractor`. On failure: sets `raw_metadata["content_fetch_error"]` and continues. Config: added `WB_CONTENT_FETCH_SIZE_LIMIT`, `WB_CONTENT_FETCH_RATE_LIMIT`, `WB_MAX_CONTENT_FETCHES` to `config.py`. Tasks: `arenas_config["wayback"]["fetch_content"]` pass-through added. Router: `fetch_content` field added to both request models.

## Phase 0
- [ ] Project bootstrap (pyproject.toml, Docker Compose, Makefile)
- [ ] FastAPI application shell with middleware
- [x] Celery infrastructure (app, beat schedule) — Task 0.3 complete (2026-02-15)
- [x] Redis rate limiter (workers/rate_limiter.py) — Task 0.6 complete (2026-02-16)
- [x] Configuration system — settings.py implemented by DB/Core (2026-02-15)
- [x] Tier definitions (config/tiers.py) — Task 0.5 complete (2026-02-16)
- [x] Danish defaults (config/danish_defaults.py) — Task 0.5 complete (2026-02-16)
- [x] ArenaCollector base class (arenas/base.py) — Task 0.3 complete (2026-02-15)
- [x] Arena registry (arenas/registry.py) — Task 0.3 complete (2026-02-15); registry collision bugfix (2026-02-18): re-keyed by platform_name, added get_arenas_by_arena_name(), fixed all callers
- [x] Normalizer pipeline (core/normalizer.py) — Task 0.3 complete (2026-02-15)
- [x] Credential pool — Task 1.1 complete (2026-02-16): DB-backed with Fernet encryption, Redis lease/quota/cooldown, env-var fallback
- [ ] Credit service (core/credit_service.py) — Task 0.8 (DB Engineer)
- [x] Exception hierarchy (core/exceptions.py) — Task 0.3 complete (2026-02-15)
- [x] Entity resolver stub (core/entity_resolver.py) — Task 0.3 complete (2026-02-15)
- [x] Auth routes (login, logout, refresh, register, password reset) — Task 0.7 complete (2026-02-15)
- [x] FastAPI app assembly (main.py, CORS, logging middleware, /health) — Task 0.7 complete (2026-02-15)
- [x] Auth dependencies (get_current_user, require_admin, ownership_guard) — Task 0.7 complete (2026-02-15)
- [x] Admin bootstrap script (scripts/bootstrap_admin.py) — Task 0.7 complete (2026-02-15)
- [x] API key generation script (scripts/generate_api_key.py) — Task 0.7 complete (2026-02-15)
- [x] Core API routes: query_designs.py, collections.py — Task 1.3 confirmed (2026-02-16): ownership_guard applied on all routes
- [x] Actors routes (`api/routes/actors.py`) — Task 0.9b complete (2026-02-16): full CRUD + presences + HTMX support
- [x] Arena-config endpoints on query_designs — Task 0.4 partial complete (2026-02-16): GET/POST /query-designs/{id}/arena-config implemented
- [x] Celery orchestration tasks (workers/tasks.py) — Task 0.4 / 3.5 complete (2026-02-16): trigger_daily_collection (credit-gated, retries×3), health_check_all_arenas (Redis TTL cache), settle_pending_credits (reservation→settlement, completion email), cleanup_stale_runs (24h threshold, cascade to CollectionTask), enforce_retention_policy (RetentionService bridge)
- [ ] Content routes — Task 0.4 still pending

### Task 0.4 / 3.5 — Delivered files
| File | Status |
|------|--------|
| `src/issue_observatory/workers/tasks.py` | Done — 5 orchestration tasks, async DB bridge via asyncio.run(), structlog throughout |
| `src/issue_observatory/workers/celery_app.py` | Updated — added `issue_observatory.workers.tasks` to include list |

**Design notes:**
- `trigger_daily_collection`: joins `QueryDesign` (is_active=True) to `CollectionRun` (mode='live', status='active'); credit check via `CreditService.get_available_credits()`; on zero balance suspends the run, emails the owner (using `settings.low_credit_warning_threshold`), skips dispatch. Dispatches `collect_by_terms` per arena with `max_retries=3, countdown=60`.
- `health_check_all_arenas`: calls `autodiscover()` then `list_arenas()`; derives task name from `collector_class` module path; writes `arena:health:{name}` Redis keys with 360s TTL using synchronous `redis.from_url()`.
- `settle_pending_credits`: finds reservation transactions whose run has `completed_at != NULL` but no settlement for the same (run, arena, platform) triple; calls `CreditService.settle()` with reserved amount as actual (conservative); sends one `send_collection_complete` email per run (deduped by run_id).
- `cleanup_stale_runs`: targets status in ('pending','running') with started_at older than 24h (or NULL for pending); bulk-updates run + cascades to CollectionTask non-terminal rows.
- `enforce_retention_policy`: calls `RetentionService.enforce_retention(db, settings.data_retention_days)`. All tasks catch-all exceptions and log ERROR without re-raising.

### Task 0.3 — Delivered files
| File | Status |
|------|--------|
| `src/issue_observatory/core/exceptions.py` | Done |
| `src/issue_observatory/arenas/base.py` | Done |
| `src/issue_observatory/arenas/registry.py` | Done |
| `src/issue_observatory/core/normalizer.py` | Done |
| `src/issue_observatory/core/entity_resolver.py` | Done (stub) |
| `src/issue_observatory/core/credential_pool.py` | Done (Phase 0 env-var stub) |
| `src/issue_observatory/workers/celery_app.py` | Done |
| `src/issue_observatory/workers/beat_schedule.py` | Done |

### Task 0.7 — Delivered files
| File | Status |
|------|--------|
| `src/issue_observatory/core/user_manager.py` | Done — FastAPI-Users adapter, UserManager, schemas, dependency factories |
| `src/issue_observatory/api/routes/auth.py` | Done — cookie + bearer backends, auth/register/reset routers |
| `src/issue_observatory/api/dependencies.py` | Done — get_current_user, get_current_active_user, get_optional_user, require_admin, ownership_guard, get_pagination |
| `src/issue_observatory/api/main.py` | Done — app factory, CORS, request logging middleware, /health, all routers mounted |
| `src/issue_observatory/api/routes/users.py` | Done — admin activation, role management, API key CRUD |
| `scripts/bootstrap_admin.py` | Done — idempotent first-run admin creation |
| `scripts/generate_api_key.py` | Done — CLI tool for API key generation/revocation by email |

### Task 0.7 — Design notes
- **No modifications to `core/models/users.py`** (DB Engineer-owned).  The
  `ObservatoryUserDatabase` adapter in `user_manager.py` injects virtual
  `is_superuser` (derived from `role == 'admin'`) and `is_verified` (always
  `True`) attributes onto returned `User` instances at runtime.
- `UserCreate.is_active` is always forced to `False` in the adapter's
  `create()` override — admin activation is required for every new account.
- Two auth backends: `cookie` (browser, HttpOnly SameSite=Lax, 30 min) and
  `bearer` (API clients, `Authorization: Bearer`).  Both use the same JWT
  strategy and secret.
- `ownership_guard()` is a plain function (not a FastAPI dependency) that
  route handlers call explicitly after fetching the resource.

### Task 0.5 — Completed (2026-02-16)
`config/tiers.py` was already fully implemented.  `config/danish_defaults.py`
received three new constants:
- `PSEUDONYMIZATION_SALT_ENV_VAR = "PSEUDONYMIZATION_SALT"`
- `FULL_TEXT_SEARCH_CONFIG = "danish"` (alias for `POSTGRES_FTS_LANGUAGE`)
- `BLUESKY_LANG_FILTER = "da"` (bare language code companion to `BLUESKY_DANISH_FILTER`)

### Task 0.6 — Completed (2026-02-16)
`workers/rate_limiter.py` received two additions:
- `RateLimitTimeoutError` exception class (key, timeout attributes).
- `RateLimiter.acquire(key, max_calls, window_seconds) -> bool` — low-level
  method using an explicit Redis key string; uses the same Lua sliding-window
  script as `check_and_acquire`.
- `RateLimiter.wait_for_slot(key, max_calls, window_seconds, timeout=60.0)` —
  polls `acquire()` in a loop with calculated sleep, raises
  `RateLimitTimeoutError` on timeout.
- Key convention: `ratelimit:{arena}:{platform}:{credential_id}`.

### Task 1.1 — Completed (2026-02-16)
`core/credential_pool.py` fully replaced with DB-backed implementation:
- Fernet decryption of `api_credentials.credentials` JSONB column.
- Redis lease: `credential:lease:{id}:{task_id}` TTL=3600s.
- Redis daily quota: `credential:quota:{id}:daily` TTL=seconds-until-midnight-UTC.
- Redis monthly quota: `credential:quota:{id}:monthly` TTL=seconds-until-month-end.
- Redis cooldown: `credential:cooldown:{id}` exponential backoff (2^(n-1) min, max 60 min = 3600s).
- Circuit breaker: 5 consecutive errors → max cooldown; admin resets `error_count` in DB.
- `acquire()` queries DB LRU-ordered, skips cooldown/quota-exceeded, sets lease, increments quota.
- `release()` deletes Redis lease key(s).
- `report_error()` increments DB `error_count`, sets Redis cooldown.
- Env-var fallback preserves Phase 0 `{PLATFORM}_{TIER}_API_KEY` behaviour when DB has no rows.
- `get_credential_pool()` FastAPI dependency (singleton).
- Backward-compat: `release(platform=..., credential_id=...)` and `report_error(platform=..., credential_id=...)` still work.

### Task 1.2 — Completed (2026-02-16)
`core/normalizer.py` changes:
- `pseudonymize_author()` formula updated to `SHA-256(platform + ":" + platform_user_id + ":" + salt)` (colons added as separators, matching DPIA spec).
- Empty salt now logs WARNING instead of raising `ValueError`; `pseudonymize_author()` returns `None` when salt is empty.
- `Normalizer.__init__` falls back to `os.environ.get("PSEUDONYMIZATION_SALT", "")` if Settings cannot be loaded.

`core/retention_service.py` created:
- `RetentionService.enforce_retention(db, retention_days) -> int` — bulk DELETE on `content_records` by `collected_at`, returns count.
- `RetentionService.delete_actor_data(db, actor_id) -> dict` — deletes `content_records`, `actor_platform_presences`, `actor_aliases`, `actor_list_members`, `actors` rows; returns per-table counts.
- All deletions logged at INFO.

### Task 1.3 — Confirmed complete (2026-02-16)
`api/routes/query_designs.py` and `api/routes/collections.py` already existed
with full `ownership_guard` coverage on all read/write routes.  No changes needed.
- `query_designs.py`: list (owner filter in WHERE clause), create (sets owner_id), get/put/delete/terms (ownership_guard call after fetch).
- `collections.py`: list (initiated_by filter), create (ownership_guard on query_design), get/cancel (ownership_guard after fetch), estimate (ownership_guard on query_design).

### Blockers / Notes
- `workers/tasks.py` (orchestration tasks) needs to be created in Task 0.4.
- Entity resolver's `create_or_update_presence()` imports `core/models/actors.py` — DB Engineer must ensure `Actor` and `ActorPlatformPresence` models are available.
- `credential_pool.py` uses `AsyncSessionLocal` from `core/database.py` — requires DB to be initialised before credential pool operations can reach the database layer.  Env-var fallback remains available when DB is not yet running.

## Task 1.15 — SSE Collection Stream (2026-02-16) — Complete

| File | Status |
|------|--------|
| `src/issue_observatory/core/event_bus.py` | Done — sync `publish_task_update` + `publish_run_complete` + `elapsed_since` helper |
| `src/issue_observatory/api/dependencies.py` | Updated — added `get_redis()` async dependency |
| `src/issue_observatory/api/routes/collections.py` | Updated — `GET /{run_id}/stream` is now a working SSE endpoint |
| `src/issue_observatory/arenas/google_search/tasks.py` | Updated — `publish_task_update` called at running/completed/failed transitions (reference pattern for all arenas) |

**Design notes**:
- `GET /collections/{run_id}/stream` returns `text/event-stream` with headers `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `Connection: keep-alive`.
- On connection the endpoint immediately emits the current state of all `CollectionTask` rows (snapshot), then subscribes to `collection:{run_id}` Redis pub/sub.
- If the run is already terminal, the snapshot is followed by a `run_complete` event and the generator closes.
- Live messages are forwarded verbatim as `event: <type>\ndata: <json>\n\n` frames.
- Keepalive comment (`": keepalive\n\n"`) sent every 30 s of inactivity to prevent proxy timeout.
- Generator unsubscribes and closes the pubsub handle in a `finally` block regardless of how the loop exits.
- `get_redis()` in `api/dependencies.py`: per-request `redis.asyncio.Redis` instance, `decode_responses=True`, closed in `finally` via `await client.aclose()`. Uses `settings.redis_url`. No new dependency needed — `redis>=5.2` (already in `pyproject.toml`) ships `redis.asyncio`.
- `event_bus.py` uses synchronous `redis.from_url()` (not `redis.asyncio`) so it can be called from Celery worker threads without an event loop. Fire-and-forget: publish failures are logged at WARNING, never propagate.
- **Pattern for other arenas**: import `publish_task_update` and `elapsed_since` from `issue_observatory.core.event_bus`. Record `_task_start = time.monotonic()` at the top of the task, then call `publish_task_update(redis_url=_settings.redis_url, run_id=..., arena=..., platform=..., status=..., ...)` at the three transition points: initial "running", final "completed", and each "failed" branch.

---

## Task 1.19 — Email Notifications (2026-02-16) — Complete

| File | Status |
|------|--------|
| `src/issue_observatory/core/email_service.py` | Done — `EmailService` class + `get_email_service()` dependency |
| `src/issue_observatory/config/settings.py` | Updated — SMTP settings + `low_credit_warning_threshold` added |
| `pyproject.toml` | Updated — `fastapi-mail>=1.4,<2.0` added |
| `src/issue_observatory/api/routes/collections.py` | Updated — cancel route fires `send_collection_failure` fire-and-forget |

**Design notes**:
- `EmailService` silently no-ops (DEBUG log) when `smtp_host` is `None` (the default). Never raises on send failure — SMTP errors are logged at WARNING and swallowed.
- Three public methods: `send_collection_failure`, `send_low_credit_warning`, `send_collection_complete`.
- All sends are plain-text (`MessageType.plain`) — no HTML templates required.
- `get_email_service()` returns an `lru_cache`-backed singleton — safe because `EmailService` has no per-request mutable state.
- `fastapi-mail` is imported lazily inside `__init__` to avoid `ImportError` breaking the service when the package is not yet installed (logs WARNING instead).
- **Wiring status**:
  - `failed` (cancel): `cancel_collection_run` fires `send_collection_failure` via `asyncio.create_task()`.
  - `completed` and credit settlement (`send_collection_complete`, `send_low_credit_warning`): These transitions happen in the Celery orchestration layer (`workers/tasks.py`) which is pending Task 0.4. The `EmailService` is ready to be imported there; call pattern from a sync Celery context: create a local event loop with `asyncio.run(email_svc.send_collection_complete(...))`, or use `asyncio.get_event_loop().create_task()` if already inside an async context.
- New settings fields in `config/settings.py`: `smtp_host`, `smtp_port`, `smtp_username`, `smtp_password`, `smtp_from_address`, `smtp_starttls`, `smtp_ssl`, `low_credit_warning_threshold`.

---

## Integration Wiring (2026-02-16)

All Phase 1 arenas wired into the application backbone.

### Task modules registered in `workers/celery_app.py` `include` list

| Module | Status |
|--------|--------|
| `issue_observatory.arenas.google_search.tasks` | Was already registered (Phase 0) |
| `issue_observatory.arenas.google_autocomplete.tasks` | Added |
| `issue_observatory.arenas.bluesky.tasks` | Added |
| `issue_observatory.arenas.reddit.tasks` | Added |
| `issue_observatory.arenas.youtube.tasks` | Added |
| `issue_observatory.arenas.rss_feeds.tasks` | Added |
| `issue_observatory.arenas.gdelt.tasks` | Added |
| `issue_observatory.arenas.event_registry.tasks` | Added (Phase 2, Task 2.4) |

Stale phase-1 comment paths (e.g. `arenas.social_media.bluesky.tasks`) replaced
with correct flat paths matching the actual arena directory layout.

### Arena routers mounted in `api/main.py`

All arena routers are mounted under the `/arenas` prefix, consistent with the
docstring convention in each `router.py` file.  The resulting endpoint paths are:

| Arena | Endpoints |
|-------|-----------|
| Google Search | `POST /arenas/google-search/collect`, `GET /arenas/google-search/health` |
| Google Autocomplete | `POST /arenas/google-autocomplete/collect`, `GET /arenas/google-autocomplete/health` |
| Bluesky | `POST /arenas/bluesky/collect/terms`, `POST /arenas/bluesky/collect/actors`, `GET /arenas/bluesky/health` |
| Reddit | `POST /arenas/reddit/collect/terms`, `POST /arenas/reddit/collect/actors`, `GET /arenas/reddit/health` |
| YouTube | `POST /arenas/youtube/collect/terms`, `POST /arenas/youtube/collect/actors`, `GET /arenas/youtube/health`, `GET /arenas/youtube/estimate` |
| RSS Feeds | `POST /arenas/rss-feeds/collect/terms`, `POST /arenas/rss-feeds/collect/actors`, `GET /arenas/rss-feeds/health`, `GET /arenas/rss-feeds/feeds` |
| GDELT | `POST /arenas/gdelt/collect`, `GET /arenas/gdelt/health` |
| Event Registry | `POST /arenas/event-registry/collect/terms`, `POST /arenas/event-registry/collect/actors`, `GET /arenas/event-registry/health` |

### Dependencies added to `pyproject.toml`

| Dependency | Note |
|------------|------|
| `asyncpraw>=7.7,<8.0` | Was already present (Reddit arena) |
| `feedparser>=6.0,<7.0` | Was already present (RSS + YouTube arenas) |
| `websockets>=13.0,<14.0` | Added — Bluesky Jetstream streamer |

### Beat schedule entries added to `workers/beat_schedule.py`

| Entry key | Task | Schedule |
|-----------|------|----------|
| `rss_feeds_collect_terms` | `issue_observatory.arenas.rss_feeds.tasks.collect_by_terms` | Every 15 minutes |
| `gdelt_collect_terms` | `issue_observatory.arenas.gdelt.tasks.collect_by_terms` | Every 15 minutes |

Note: The beat schedule entries will fire collection tasks but they require
`query_design_id` and `collection_run_id` arguments.  Until the orchestration
layer (`workers/tasks.py`) is in place, these entries serve as a placeholder
that will be refined in Task 0.4 to trigger all active query designs.

---

## Arenas Implemented

### Task 2.1 — X/Twitter Arena (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/x_twitter/__init__.py` | Done |
| `src/issue_observatory/arenas/x_twitter/config.py` | Done |
| `src/issue_observatory/arenas/x_twitter/collector.py` | Done |
| `src/issue_observatory/arenas/x_twitter/tasks.py` | Done |
| `src/issue_observatory/arenas/x_twitter/router.py` | Done |

**Design notes**:
- `arena_name = "social_media"`, `platform_name = "x_twitter"`, `supported_tiers = [Tier.MEDIUM, Tier.PREMIUM]`.
- No free tier: the official X free tier (100 reads/month) is unusable for research.
- Medium tier (TwitterAPI.io): POST to `https://api.twitterapi.io/twitter/tweet/advanced_search` with `X-API-Key` header. Cursor pagination via `next_cursor`. Credential: `platform="twitterapi_io"`, `tier="medium"`, JSONB `{"api_key": "..."}`.
- Premium tier (X API v2 Pro): GET `/2/tweets/search/all` (full-archive). Bearer token auth. `next_token` pagination. Credential: `platform="x_twitter"`, `tier="premium"`, JSONB `{"bearer_token": "..."}`.
- Danish defaults: `lang:da` unconditionally appended to every query. Optional `since:YYYY-MM-DD until:YYYY-MM-DD` operators applied from date range parameters.
- `collect_by_terms()`: builds `{term} lang:da [since:... until:...]`, paginates until `max_results` or no more pages.
- `collect_by_actors()`: constructs `from:{handle} lang:da` for medium tier. For premium, uses `/2/users/{id}/tweets` for numeric IDs, falls back to `from:{handle}` search for handles.
- Tweet type detection: two helpers — `_detect_tweet_type_twitterapiio()` (boolean `isRetweet`/`isReply`/`isQuote`) and `_detect_tweet_type_v2()` (`referenced_tweets[].type` field). Types: `"tweet"`, `"retweet"`, `"reply"`, `"quote_tweet"`.
- Two parsing paths: `_parse_twitterapiio(raw)` and `_parse_twitter_v2(raw)`, both converging to a flat dict for `Normalizer.normalize()`. The v2 parser accepts an injected `_users` lookup dict for author hydration from `includes.users`.
- URL construction: `https://x.com/{username}/status/{tweet_id}` for both tiers.
- Engagement metrics: `likes_count`, `shares_count` (retweets + quotes for v2), `comments_count` (reply count), `views_count` (impression count where available).
- Rate limiting: medium at 1 call/sec via `RateLimiter.wait_for_slot()`; premium at 15 calls/60 sec + adaptive sleep on `x-rate-limit-remaining=0`.
- `health_check()`: acquires medium credential first, fires `"test lang:da"` test query; falls back to premium if medium unavailable.
- Celery tasks: `x_twitter_collect_terms`, `x_twitter_collect_actors`, `x_twitter_health_check`. Max 3 retries, exponential backoff capped at 600 seconds. `asyncio.run()` bridges sync Celery to async collector.
- Standalone router: `POST /arenas/x-twitter/collect/terms`, `POST /arenas/x-twitter/collect/actors`, `GET /arenas/x-twitter/health`.
- `issue_observatory.arenas.x_twitter.tasks` added to `include` in `workers/celery_app.py`. Router mounted under `/arenas` in `api/main.py`.

**Blockers / Notes for QA**:
- Medium credential: TwitterAPI.io account required. `platform="twitterapi_io"`, `tier="medium"`, JSONB `{"api_key": "..."}`.
- Premium credential: X API Pro subscription required ($5,000/month). `platform="x_twitter"`, `tier="premium"`, JSONB `{"bearer_token": "..."}`.
- Integration tests: mock `httpx.AsyncClient` via `respx` or `pytest-httpx`. Inject via `http_client` constructor parameter on `XTwitterCollector`.
- v2 test fixtures must include the full `includes.users` envelope for author hydration to work.
- `TWITTER_V2_SEARCH_RECENT` constant in `config.py` can be substituted for `search/all` when testing on the Basic tier ($100/month, 7-day search only).
- GDPR: ensure `PSEUDONYMIZATION_SALT` is set. Tweet text and author display names are personal data under GDPR Art. 6(1)(e) + Art. 89. Political tweets (e.g. `#dkpol`) are Art. 9(1) special category data; legal basis Art. 9(2)(j).

---

### Task 1.10 — Telegram Arena (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/telegram/__init__.py` | Done |
| `src/issue_observatory/arenas/telegram/config.py` | Done |
| `src/issue_observatory/arenas/telegram/collector.py` | Done |
| `src/issue_observatory/arenas/telegram/tasks.py` | Done |
| `src/issue_observatory/arenas/telegram/router.py` | Done |

**Design notes**:
- `arena_name = "social_media"`, `platform_name = "telegram"`, `supported_tiers = [Tier.FREE]`.
- Free-only arena: Telethon MTProto client. Credentials: `platform="telegram"`, `tier="free"`. JSONB fields: `api_id`, `api_hash`, `session_string`.
- `collect_by_terms()`: searches each term across the configured Danish channel list (plus any `actor_ids`) using `client.get_messages(channel, search=term)`. Paginates via `offset_id` until `date_from` exceeded or `max_results` reached.
- `collect_by_actors()`: fetches messages from each specified channel with date filtering. Pagination via `offset_id`.
- `normalize()`: `platform_id = "{channel_id}_{message_id}"` (globally unique). `url = "https://t.me/{username}/{id}"` when channel has a username. `author_platform_id` = channel entity ID. `likes_count` = sum of reaction counts. Media presence/type recorded in `raw_metadata`; actual media download is out of scope (Phase 1).
- FloodWaitError: sets `credential:cooldown:{id}` Redis key with exact TTL = `error.seconds`. Raises `ArenaRateLimitError`. Celery auto-retries (max 3, exp backoff capped 600s).
- ChannelPrivateError and PeerIdInvalidError: log WARNING and skip channel (do not raise).
- UserDeactivatedBanError: calls `report_error()` on credential, raises `NoCredentialAvailableError`.
- Baseline rate limit: 20 req/min per credential via `RateLimiter.wait_for_slot()`. Real signal is FloodWaitError.
- `health_check()`: connects via Telethon and calls `client.get_me()` to verify session validity.
- Celery tasks: `telegram_collect_terms`, `telegram_collect_actors`, `telegram_health_check`. Tasks use `asyncio.run()` to bridge sync Celery worker to async Telethon.
- Standalone router: `POST /telegram/collect/terms`, `POST /telegram/collect/actors`, `GET /telegram/health`.
- Default Danish channel list in `config.DANISH_TELEGRAM_CHANNELS` (6 starter channels). Expansion tracked as pre-Phase task E.5.
- `telethon>=1.36,<2.0` added to `pyproject.toml`.
- Arena path is `arenas/telegram/` (not `arenas/social_media/telegram/`); `arena_name = "social_media"` sets the correct DB column value.

**Blockers / Notes for QA**:
- Telegram credentials must be manually provisioned: generate `api_id`/`api_hash` at https://my.telegram.org/apps, perform one-time interactive phone auth to generate a `session_string`, then store in CredentialPool (`platform="telegram"`, `tier="free"`).
- Integration tests must mock `TelegramClient` (inject via `unittest.mock.patch` on `telethon.TelegramClient`) since live credentials cannot be used in CI.
- The `telegram` arena must be added to the Celery `include` list in `workers/celery_app.py` to register the tasks.
- Pre-Phase task E.5 (channel curation) and E.3 (ethics documentation) are prerequisites for production use.



### Task 1.8 — Danish RSS Feeds Arena (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/rss_feeds/__init__.py` | Done |
| `src/issue_observatory/arenas/rss_feeds/config.py` | Done |
| `src/issue_observatory/arenas/rss_feeds/collector.py` | Done |
| `src/issue_observatory/arenas/rss_feeds/tasks.py` | Done |
| `src/issue_observatory/arenas/rss_feeds/router.py` | Done |

**Design notes**:
- `arena_name = "rss_feeds"` (registry key); `arena="news_media"` written to content records.
- `platform` per record is the outlet slug (e.g. `"dr"`, `"tv2"`) derived from `DANISH_RSS_FEEDS` key prefix.
- `collect_by_terms()`: fetches all feeds in parallel (asyncio.Semaphore(10)), case-insensitive term matching on title+summary.
- `collect_by_actors()`: actor_ids are outlet slug prefixes or exact feed keys.
- Conditional GET (ETag / If-Modified-Since) cached per-feed in memory.
- `feedparser` used for parsing; `httpx.AsyncClient` for async fetching.
- HTML stripped from summaries via regex.
- `content_hash` is SHA-256 of normalized title for cross-feed deduplication.
- `health_check()` fetches DR all-news feed; verifies non-empty entries.
- Celery tasks: `rss_feeds_collect_terms`, `rss_feeds_collect_actors`, `rss_feeds_health_check`.
- No credentials required.

### Task 1.9 — GDELT Arena (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/gdelt/__init__.py` | Done |
| `src/issue_observatory/arenas/gdelt/config.py` | Done |
| `src/issue_observatory/arenas/gdelt/collector.py` | Done |
| `src/issue_observatory/arenas/gdelt/tasks.py` | Done |
| `src/issue_observatory/arenas/gdelt/router.py` | Done |

**Design notes**:
- `arena_name = "gdelt"` (registry key); `arena="news_media"` written to content records.
- `collect_by_terms()`: two queries per term — `sourcecountry:DA` and `sourcelang:danish` — deduplicated by URL.
- `collect_by_actors()` raises `NotImplementedError` (GDELT does not track authors).
- Rate limiting: `RateLimiter.wait_for_slot("ratelimit:news_media:gdelt:shared", max_calls=1, window_seconds=1)`. Falls back to `asyncio.sleep(1)` when no Redis.
- GDELT may return HTML on errors; `content-type` header checked before JSON parse.
- `platform_id` = SHA-256 of URL. `content_hash` = SHA-256 of normalized URL.
- Language mapping: `"Danish"` → `"da"`. Country mapping: FIPS `"DA"` → ISO `"DK"`.
- `health_check()` queries `"denmark"` with maxrecords=1.
- Celery tasks: `gdelt_collect_terms`, `gdelt_health_check`.
- No credentials required.

### Task 1.4 — Google Autocomplete Arena (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/google_autocomplete/__init__.py` | Done |
| `src/issue_observatory/arenas/google_autocomplete/config.py` | Done |
| `src/issue_observatory/arenas/google_autocomplete/collector.py` | Done |
| `src/issue_observatory/arenas/google_autocomplete/tasks.py` | Done |
| `src/issue_observatory/arenas/google_autocomplete/router.py` | Done |

### Task 1.4 — Design notes
- FREE tier: undocumented Google endpoint `suggestqueries.google.com/complete/search?client=firefox`; no auth.
- MEDIUM tier: Serper.dev `POST google.serper.dev/autocomplete`; credentials `platform="serper"` (shared with Google Search).
- PREMIUM tier: SerpAPI `GET serpapi.com/search?engine=google_autocomplete`; credentials `platform="serpapi"` (shared with Google Search).
- Danish params `gl=dk&hl=da` on all requests.
- `collect_by_actors()` raises `NotImplementedError` — not applicable.
- `content_type="autocomplete_suggestion"`, `arena="google_autocomplete"`, `platform="google"`.
- `platform_id` = SHA-256(query + suggestion + minute-bucket).
- Rate limiter key: `ratelimit:google_search:google_autocomplete:{credential_id}` (10 calls/sec).
- Celery task `google_autocomplete_collect_terms` auto-retries on `ArenaRateLimitError` (max 3, exp backoff).

### Task 1.5 — Bluesky Arena (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/bluesky/__init__.py` | Done |
| `src/issue_observatory/arenas/bluesky/config.py` | Done |
| `src/issue_observatory/arenas/bluesky/collector.py` | Done |
| `src/issue_observatory/arenas/bluesky/tasks.py` | Done |
| `src/issue_observatory/arenas/bluesky/router.py` | Done |

### Task 1.5 — Design notes
- FREE tier only: AT Protocol public API (`public.api.bsky.app`), unauthenticated, 3,000 req/5 min per IP.
- `collect_by_terms()`: `searchPosts` with `lang=da` filter and cursor pagination.
- `collect_by_actors()`: `getAuthorFeed` with cursor pagination; date filter applied client-side.
- `platform="bluesky"`, `arena="bluesky"`, `platform_id` = AT URI, web URL from handle/rkey.
- `BlueskyStreamer` in `collector.py`: optional Jetstream WebSocket (future enhancement; not required by Celery tasks).
- Rate limiter key: `ratelimit:bluesky:public:{credential_id}` (10 calls/sec).
- Celery tasks: `bluesky_collect_terms`, `bluesky_collect_actors`, `bluesky_health_check`.
- No credentials required.

### Task 1.6 — Reddit Arena (2026-02-16) — READY FOR QA

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/reddit/__init__.py` | Done |
| `src/issue_observatory/arenas/reddit/config.py` | Done |
| `src/issue_observatory/arenas/reddit/collector.py` | Done |
| `src/issue_observatory/arenas/reddit/tasks.py` | Done |
| `src/issue_observatory/arenas/reddit/router.py` | Done |

### Task 1.6 — Design notes
- FREE-only arena. ``arena_name = "social_media"``, ``platform_name = "reddit"``.
- ``asyncpraw>=7.7,<8.0`` added to ``pyproject.toml``.
- Credentials: ``CredentialPool.acquire(platform="reddit", tier="free")``. JSONB fields: ``client_id``, ``client_secret``, ``user_agent``. Env-var fallbacks: ``REDDIT_CLIENT_ID``, ``REDDIT_CLIENT_SECRET``, ``REDDIT_USER_AGENT``.
- ``collect_by_terms()``: searches ``Denmark+danish+copenhagen+aarhus+dkfinance+scandinavia+NORDVANSEN`` for each term. Deduplicates by post ID. Optional comment collection (``include_comments=False`` default).
- ``collect_by_actors()``: fetches from ``redditor.submissions.new()`` and ``redditor.comments.new()``. Handles NotFound gracefully.
- Deleted posts: ``author`` None → ``author_platform_id = None``; ``[deleted]``/``[removed]`` text → ``None``.
- Rate limiting: safety-net at 90 req/min via shared RateLimiter (key: ``ratelimit:social_media:reddit:{credential_id}``).
- ``asyncprawcore.TooManyRequests`` → ``ArenaRateLimitError``; ``Forbidden`` → WARNING + skip.
- ``health_check()``: fetches ``r/Denmark.hot(limit=1)``.
- Celery tasks: ``reddit_collect_terms``, ``reddit_collect_actors`` (max 3 retries, exp backoff capped 5 min).
- Standalone router: ``POST /reddit/collect/terms``, ``POST /reddit/collect/actors``, ``GET /reddit/health``.
- Arena path is ``arenas/reddit/`` (not ``arenas/social_media/reddit/``); ``arena_name = "social_media"`` sets the correct DB column value.

### Task 1.7 — YouTube Arena (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/youtube/__init__.py` | Done |
| `src/issue_observatory/arenas/youtube/config.py` | Done |
| `src/issue_observatory/arenas/youtube/collector.py` | Done |
| `src/issue_observatory/arenas/youtube/tasks.py` | Done |
| `src/issue_observatory/arenas/youtube/router.py` | Done |

### Task 1.7 — Design notes
- `arena_name = "social_media"`, `platform_name = "youtube"`, `supported_tiers = [Tier.FREE]`.
- **RSS-first strategy**: `collect_by_actors()` polls `https://www.youtube.com/feeds/videos.xml?channel_id={id}` (zero quota) via `feedparser`, then batch-enriches via `videos.list` (1 unit/50 videos).
- **Keyword discovery**: `collect_by_terms()` uses `search.list` (100 units/call) with `relevanceLanguage=da` + `regionCode=DK` from `YOUTUBE_DANISH_PARAMS` in `danish_defaults.py`.
- **Credential rotation**: HTTP 403 + `reason="quotaExceeded"` → `ArenaRateLimitError` → `CredentialPool.report_error()` then Celery auto-retry acquires fresh key. All keys exhausted → `NoCredentialAvailableError` → task CRITICAL + fails.
- **Rate-limit throttling**: `RateLimiter.wait_for_slot()` at 10 calls/second (separate from quota management).
- **Normalizer**: manual `normalize()` implementation (not delegated to `Normalizer.normalize()`) to precisely control field mapping per the research brief. `content_hash` = SHA-256 of title+description. `pseudonymized_author_id` computed via `Normalizer.pseudonymize_author()`.
- **`shares_count`**: always `None` — YouTube API does not expose share count.
- **`raw_metadata`**: includes full API resource plus `category_name` (human-readable from `_CATEGORY_NAMES` map).
- **`health_check()`**: `videos.list(id="dQw4w9WgXcQ", part="snippet")` — 1 quota unit.
- **Celery tasks**: `youtube_collect_terms`, `youtube_collect_actors`, `youtube_health_check`. Max 5 retries, exponential backoff capped at 10 minutes.
- **Standalone router**: `/youtube/collect/terms`, `/youtube/collect/actors`, `/youtube/health`, `/youtube/estimate` — all independently testable.
- **Credit cost**: `estimate_credits()` computes `pages * 100 + batches * 1` units. `DAILY_QUOTA_PER_KEY = 10,000`.
- **Danish channel IDs**: 14 curated channels in `DANISH_YOUTUBE_CHANNEL_IDS` (config.py).
- Add `feedparser` to `pyproject.toml` dependencies.

### Task 1.7 — Blockers / Notes
- `feedparser` must be added to `pyproject.toml` as a dependency.
- QA Engineer: integration tests should mock `feedparser.parse()` calls and `httpx.AsyncClient` via `respx` or `pytest-httpx`. The `http_client` constructor parameter on `YouTubeCollector` supports test injection.
- The `youtube` arena is not yet added to the Celery `include` list in `workers/celery_app.py` — this must be done to register the tasks.
- Status file updated 2026-02-16.

### Task 1.11 — TikTok Arena (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/tiktok/__init__.py` | Done |
| `src/issue_observatory/arenas/tiktok/config.py` | Done |
| `src/issue_observatory/arenas/tiktok/collector.py` | Done |
| `src/issue_observatory/arenas/tiktok/tasks.py` | Done |
| `src/issue_observatory/arenas/tiktok/router.py` | Done |

**Design notes**:
- `arena_name = "social_media"`, `platform_name = "tiktok"`, `supported_tiers = [Tier.FREE]`.
- FREE tier only (Phase 1). TikTok Research API. Credentials: `platform="tiktok"`, `tier="free"`. JSONB: `{"client_key": "...", "client_secret": "..."}`.
- OAuth 2.0 client credentials flow. Tokens expire every 2 hours. Cached in Redis: `tiktok:token:{credential_id}` with TTL = expires_in - 600s. In-memory fallback when Redis unavailable.
- `collect_by_terms()`: `POST /v2/research/video/query/` with `region_code: "DK"` and `keyword` conditions. Cursor + search_id pagination. Date ranges > 30 days split into 30-day windows.
- `collect_by_actors()`: same endpoint with `username` condition.
- `normalize()`: `platform_id` = video id, `url` = `https://www.tiktok.com/@{username}/video/{id}`, `text_content` = `video_description` + `\n[transcript] voice_to_text`. Engagement metrics subject to 10-day accuracy lag (noted in code comment).
- Rate limiter key: `ratelimit:tiktok:research_api:{credential_id}` (1 call/sec, conservative).
- `tiktok_refresh_engagement` task: skeleton with TODO for Phase 3 engagement re-collection (10-15 day lag window). Required by TikTok policy (15-day refresh cycle).
- Celery tasks: `tiktok_collect_terms`, `tiktok_collect_actors`, `tiktok_health_check`, `tiktok_refresh_engagement`.
- Standalone router: `POST /tiktok/collect/terms`, `POST /tiktok/collect/actors`, `GET /tiktok/health`.

**Blockers / Notes for QA**:
- TikTok Research API credentials require academic access approval from TikTok for Developers. Store in CredentialPool as `platform="tiktok"`, `tier="free"`.
- Integration tests must mock `httpx.AsyncClient` via `respx` or `pytest-httpx`. Inject via `http_client` constructor param.
- `voice_to_text` quality for Danish speech is unverified (WARNING in brief).
- Phase 3 action required: implement `tiktok_refresh_engagement` task body (see task docstring).

---

### Task 1.12 — Via Ritzau Arena (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/ritzau_via/__init__.py` | Done |
| `src/issue_observatory/arenas/ritzau_via/config.py` | Done |
| `src/issue_observatory/arenas/ritzau_via/collector.py` | Done |
| `src/issue_observatory/arenas/ritzau_via/tasks.py` | Done |
| `src/issue_observatory/arenas/ritzau_via/router.py` | Done |

**Design notes**:
- `arena_name = "news_media"`, `platform_name = "ritzau_via"`, `supported_tiers = [Tier.FREE]`.
- No credentials required. API is fully public and unauthenticated. `credential_pool=None` always.
- `collect_by_terms()`: `GET /json/v2/releases?query={term}&language=da` with offset pagination.
- `collect_by_actors()`: `GET /json/v2/releases?publisherId={id}&language=da` with offset pagination.
- `normalize()`: `content_type = "press_release"`. HTML body stripped with block-tag-to-newline conversion. Original HTML preserved in `raw_metadata`. Media URLs extracted from `images[].url`.
- Rate limiter: courtesy throttle 2 calls/sec.
- `health_check()`: `GET /json/v2/releases?limit=1&language=da`.
- `fetch_publishers()` helper for publisher ID discovery.
- Celery tasks: `ritzau_via_collect_terms`, `ritzau_via_collect_actors`, `ritzau_via_health_check`.
- Standalone router: `POST /ritzau-via/collect/terms`, `POST /ritzau-via/collect/actors`, `GET /ritzau-via/health`.

---

### Task 2.10 — Common Crawl and Wayback Machine Arenas (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/web/__init__.py` | Done |
| `src/issue_observatory/arenas/web/common_crawl/__init__.py` | Done |
| `src/issue_observatory/arenas/web/common_crawl/config.py` | Done |
| `src/issue_observatory/arenas/web/common_crawl/collector.py` | Done |
| `src/issue_observatory/arenas/web/common_crawl/tasks.py` | Done |
| `src/issue_observatory/arenas/web/common_crawl/router.py` | Done |
| `src/issue_observatory/arenas/web/wayback/__init__.py` | Done |
| `src/issue_observatory/arenas/web/wayback/config.py` | Done |
| `src/issue_observatory/arenas/web/wayback/collector.py` | Done |
| `src/issue_observatory/arenas/web/wayback/tasks.py` | Done |
| `src/issue_observatory/arenas/web/wayback/router.py` | Done |

**Design notes**:

**Common Crawl** (`arena_name="web"`, `platform_name="common_crawl"`, `supported_tiers=[Tier.FREE]`):
- No credentials required. CC Index API is unauthenticated.
- `collect_by_terms()`: queries `*.dk` domain captures from the CC Index API with `matchType=domain` and `filter=status:200`. Filters client-side by term substring match against `url` field. Pagination via `from` offset parameter.
- `collect_by_actors()`: queries CC Index directly by domain name (actor_ids must be registered domain names, e.g. `"dr.dk"`).
- `normalize()`: `content_type="web_index_entry"`. `platform_id` = CC `content_digest` if available, else SHA-256(`url+timestamp`). `published_at` parsed from CC `timestamp` (YYYYMMDDHHmmss). Language mapped from ISO 639-3 (`"dan"`) to ISO 639-1 (`"da"`). WARC location (`filename`, `offset`, `length`) stored in `raw_metadata` for future retrieval.
- Rate limit: 1 req/sec via `RateLimiter.wait_for_slot`. Falls back to `asyncio.sleep(1)`.
- `health_check()`: GET `https://index.commoncrawl.org/collinfo.json` and verify non-empty index list.
- `cc_index` parameter on collector and Celery task allows overriding the default index (`CC-MAIN-2025-51`).
- Celery tasks: `common_crawl_collect_terms`, `common_crawl_collect_actors`, `common_crawl_health_check`.
- Standalone router: `POST /common-crawl/collect/terms`, `POST /common-crawl/collect/actors`, `GET /common-crawl/health`.

**Wayback Machine** (`arena_name="web"`, `platform_name="wayback"`, `supported_tiers=[Tier.FREE]`):
- No credentials required. CDX API is unauthenticated.
- `collect_by_terms()`: queries `*.dk` captures with `matchType=domain`, `filter=statuscode:200`, `collapse=digest`. Filters client-side by term substring match against `original` URL. Pagination via `showResumeKey=true` and `resumeKey` parameter.
- `collect_by_actors()`: queries CDX by domain or URL prefix. Actor_ids are domain names or URL prefixes.
- `normalize()`: `content_type="web_page_snapshot"`. `platform_id` = SHA-256(`url+timestamp`). `published_at` from CDX `timestamp` (YYYYMMDDHHmmss). Language inferred from `.dk` TLD. CDX metadata + `wayback_url` stored in `raw_metadata`.
- Rate limit: 1 req/sec. 503 responses handled gracefully (WARNING log, skip page).
- `health_check()`: CDX query for `dr.dk` with `limit=1`.
- Celery tasks: `wayback_collect_terms`, `wayback_collect_actors`, `wayback_health_check`.
- Standalone router: `POST /wayback/collect/terms`, `POST /wayback/collect/actors`, `GET /wayback/health`.

**Wiring**:
- Both task modules added to `workers/celery_app.py` `include` list.
- Both routers mounted in `api/main.py` under `/arenas` prefix.

**Blockers / Notes for QA**:
- Both arenas are batch-only; they do not participate in Celery Beat live tracking.
- Integration tests should mock `httpx.AsyncClient` via `respx` or `pytest-httpx`. `http_client` constructor parameter supports injection.
- CC Index may return 404 for URLs not in a given crawl — not an error, handled gracefully (returns `[]`).
- Wayback Machine 503 responses handled gracefully. Infrastructure fragility is a known limitation.
- `CC_DEFAULT_INDEX = "CC-MAIN-2025-51"` must be updated as new crawls are released.
- No new dependencies required — both arenas use only `httpx` (already in `pyproject.toml`).

---

### Task 2.6 — Threads Arena (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/threads/__init__.py` | Done |
| `src/issue_observatory/arenas/threads/config.py` | Done |
| `src/issue_observatory/arenas/threads/collector.py` | Done |
| `src/issue_observatory/arenas/threads/tasks.py` | Done |
| `src/issue_observatory/arenas/threads/router.py` | Done |

**Design notes**:
- `arena_name = "social_media"`, `platform_name = "threads"`, `supported_tiers = [Tier.FREE, Tier.MEDIUM]`.
- FREE tier: Official Threads API (OAuth 2.0). Base URL: `https://graph.threads.net/v1.0`. 250 calls/hour per user token.
- MEDIUM tier (MCL): Both collection methods raise `NotImplementedError`. Phase 2 stub — pending MCL access approval.
- **Actor-first architecture**: `collect_by_actors()` is the PRIMARY mode. `GET /{user_id}/threads?fields=...&limit=25` with `paging.cursors.after` pagination. Date filter client-side.
- **No global keyword search at FREE tier**: `collect_by_terms()` logs WARNING, falls back to `DEFAULT_DANISH_THREADS_ACCOUNTS` + client-side text filtering. Returns `[]` if no accounts configured.
- **Engagement metrics gap**: `views`, `likes`, `replies`, `reposts`, `quotes` only returned for the authenticated token owner's own posts. Other users get `None` for all engagement fields.
- `normalize()`: `content_type = "reply"` if `is_reply=True`, else `"post"`. `platform_id` = thread `id`. `url` = `permalink`. Engagement set only when field is present in raw response.
- **Token refresh**: `refresh_token_if_needed()` checks Redis key `threads:token_expiry:{credential_id}`. Within 55 days of 60-day expiry: calls `GET /refresh_access_token?grant_type=th_refresh_token`. Updates Redis expiry key with new TTL.
- Credentials: `platform="threads"`, `tier="free"`. JSONB: `{"access_token": "...", "user_id": "...", "expires_at": "ISO8601"}`.
- Rate limiter: `ratelimit:social_media:threads:{credential_id}`, 250 calls/3600 s.
- `health_check()`: `GET /me?fields=id,username` with Bearer token. Returns `{"status": "ok", "username": "..."}`.
- Celery tasks: `threads_collect_terms`, `threads_collect_actors`, `threads_health_check`, `threads_refresh_tokens`.
- `threads_refresh_tokens` beat entry: daily at 02:00 Copenhagen time (`workers/beat_schedule.py`).
- `issue_observatory.arenas.threads.tasks` wired into `workers/celery_app.py` include list.
- Router mounted in `api/main.py` under `/arenas`: endpoints at `/arenas/threads/collect/terms`, `/arenas/threads/collect/actors`, `/arenas/threads/health`.

**Blockers / Notes for QA**:
- Threads credentials require a Meta Developer account, registered app with Threads API permissions, and an OAuth 2.0 long-lived token. Store as `platform="threads"`, `tier="free"`. JSONB: `{"access_token": "...", "user_id": "...", "expires_at": "ISO8601"}`.
- Mirror `expires_at` to Redis at key `threads:token_expiry:{credential_id}` on credential creation so the refresh task can trigger.
- `DEFAULT_DANISH_THREADS_ACCOUNTS` in `config.py` starts empty — populate via actor management UI.
- Integration tests: mock `httpx.AsyncClient` via `respx`/`pytest-httpx`; inject via `http_client` constructor param on `ThreadsCollector`.
- GDPR note: Threads identities are linked to Instagram accounts — pseudonymization is especially important. Pseudonymization formula: `SHA-256("threads" + ":" + username + ":" + salt)` via `Normalizer.pseudonymize_author()`.

---

### Task 1.13 — Gab Arena (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/gab/__init__.py` | Done |
| `src/issue_observatory/arenas/gab/config.py` | Done |
| `src/issue_observatory/arenas/gab/collector.py` | Done |
| `src/issue_observatory/arenas/gab/tasks.py` | Done |
| `src/issue_observatory/arenas/gab/router.py` | Done |

**Design notes**:
- `arena_name = "social_media"`, `platform_name = "gab"`, `supported_tiers = [Tier.FREE]`.
- FREE tier only. Mastodon-compatible API at `https://gab.com/api/`. Credentials: `platform="gab"`, `tier="free"`. JSONB: `{"client_id": "...", "client_secret": "...", "access_token": "..."}`.
- `collect_by_terms()`: `GET /api/v2/search?type=statuses`. Falls back to `GET /api/v1/timelines/tag/{hashtag}` for `#hashtag` terms or if search returns 422.
- `collect_by_actors()`: account lookup via `GET /api/v1/accounts/lookup?acct={username}` (if username provided), then paginate `GET /api/v1/accounts/{id}/statuses` using `max_id` cursor. Date filter applied client-side.
- `normalize()`: HTML stripped from `content` field. Reblogs: original status used as base; reblog context preserved in `raw_metadata`. `likes_count` = `favourites_count`, `shares_count` = `reblogs_count`, `comments_count` = `replies_count`.
- Rate limiter: 60 calls/60 sec (conservative vs 300/5 min Mastodon default).
- `health_check()`: `GET /api/v1/timelines/public?limit=1` with Bearer token; falls back to `GET /api/v1/instance`.
- Expected content volume: very low (Danish-relevant content is sparse on Gab). Primary value is cross-platform actor tracking.
- Celery tasks: `gab_collect_terms`, `gab_collect_actors`, `gab_health_check`.
- Standalone router: `POST /gab/collect/terms`, `POST /gab/collect/actors`, `GET /gab/health`.

**Blockers / Notes for QA**:
- Gab account required for OAuth. Access token is obtained interactively (one-time). Store in CredentialPool as `platform="gab"`, `tier="free"`.
- Gab's Mastodon fork may have API deviations from the standard Mastodon spec. Verify search endpoint behavior during integration testing.
- Research ethics: creating a Gab account for research purposes should be documented in Pre-Phase task E.3.
- Integration tests must mock `httpx.AsyncClient`. Inject via `http_client` constructor param.

---

### Tasks 2.8 & 2.9 — Actor Sampling Modules (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/sampling/__init__.py` | Done — exports all public symbols |
| `src/issue_observatory/sampling/network_expander.py` | Done — Task 2.8 |
| `src/issue_observatory/sampling/similarity_finder.py` | Done — Task 2.9 |
| `src/issue_observatory/sampling/snowball.py` | Done — Tasks 2.8/2.9 combined |

**Design notes**:

**NetworkExpander** (`network_expander.py`):
- `expand_from_actor(actor_id, platforms, db, credential_pool, depth=1)`: dispatches to platform-specific expanders.
  - Bluesky: `app.bsky.graph.getFollows` + `app.bsky.graph.getFollowers` (public AT Protocol API, up to 500 per direction with cursor pagination).
  - Reddit: fetches user's last 100 comments via public JSON API (`/user/{username}/comments.json`), extracts `u/username` mentions with regex `(?<!\w)u/([A-Za-z0-9_-]{3,20})`.
  - YouTube: reads `featuredChannelsUrls` from `brandingSettings` via `channels.list` (requires API key credential).
  - Unknown platforms: no-op (empty list returned, not an error).
- `find_co_mentioned_actors(query_design_id, db, min_co_occurrences=3)`: self-join on `content_records` comparing `search_terms_matched && search_terms_matched` and counting co-occurrences of `author_platform_id` pairs. Returns `{actor_a, actor_b, platform, co_occurrence_count}` dicts.
- `suggest_for_actor_list(actor_list_id, db, credential_pool)`: loads all actors from `actor_list_members`, determines platforms from `actor_platform_presences`, runs `expand_from_actor` for each, deduplicates by `platform:user_id` key.
- No arena collector imports — all HTTP via `httpx.AsyncClient` directly.
- `get_network_expander()` factory for FastAPI dependency injection.

**SimilarityFinder** (`similarity_finder.py`):
- `find_similar_by_platform(actor_id, platform, credential_pool, db, top_n=25)`:
  - Bluesky: `app.bsky.graph.getSuggestedFollowsByActor` (public, up to 25 results).
  - Reddit: fetches user's subreddits via `/user/{username}/submitted.json`, then top posters from each subreddit's `/r/{sr}/top.json` (up to 3 subreddits, 25 posts each).
  - YouTube: reads `relatedPlaylists.uploads` from `channels.list`, then `playlistItems.list` to extract `videoOwnerChannelId` fields (requires API key).
- `find_similar_by_content(actor_id, db, top_n=10)`:
  - Fetches `STRING_AGG(text_content)` for target actor and up to 500 other actors from `content_records`.
  - TF-IDF cosine similarity via `sklearn.feature_extraction.text.TfidfVectorizer` + `cosine_similarity` when scikit-learn is installed.
  - Falls back to Jaccard word-overlap similarity with WARNING log when scikit-learn is absent.
  - Minimum 5-token threshold applied to both target and candidates.
- `cross_platform_match(name_or_handle, platforms, credential_pool, top_n=5)`:
  - Bluesky: `app.bsky.actor.searchActors`.
  - Reddit: `/users/search.json`.
  - YouTube: `search.list?type=channel` (requires API key, costs 100 quota units per call).
  - Confidence score via character-trigram Jaccard similarity between query and returned handle/display name.
- `get_similarity_finder()` factory for FastAPI dependency injection.
- `scikit-learn>=1.4,<2.0` added to `pyproject.toml` under `[project.optional-dependencies] ml`.

**SnowballSampler** (`snowball.py`):
- `run(seed_actor_ids, platforms, db, credential_pool, max_depth=2, max_actors_per_step=20)`:
  - Wave 0: loads seed actors from DB (`Actor` + `ActorPlatformPresence`), adds to result with `discovery_depth=0`.
  - Waves 1+: calls `expand_from_actor` for each actor UUID in current wave queue.
  - Deduplication: `visited_keys` set of `"platform:user_id"` strings; `visited_uuids` set of actor UUIDs.
  - Novel actors (not in `visited_keys`) appended to result with `discovery_depth=N`.
  - Budget: stops adding to current wave when `len(next_wave_dicts) >= max_actors_per_step`.
  - UUID resolution: at end of each wave, resolves novel actor dicts back to DB UUIDs via `actor_platform_presences`. Only DB-known actors can be expanded in subsequent waves.
  - Per-wave INFO logging: actor count, discovery methods used.
  - Error isolation: exceptions in `expand_from_actor` logged and skipped.
- Returns `SnowballResult` with `actors`, `wave_log`, `total_actors`, `max_depth_reached`.
- `get_snowball_sampler()` factory for FastAPI dependency injection.

**Blockers / Notes for QA**:
- All HTTP calls use `httpx.AsyncClient`; inject via constructor `http_client` param for mocking.
- `find_similar_by_content` and `find_co_mentioned_actors` require `content_records` to be populated with `author_id` and `text_content` data.
- YouTube expansion and cross-platform search require a YouTube Data API v3 key credential in the pool.
- Reddit public JSON API is rate-limited to ~1 req/sec for anonymous clients; integration tests must mock `_get_json`.
- scikit-learn is optional: `pip install 'issue-observatory[ml]'`.

---

### Task 2.7 — Majestic Backlink Intelligence Arena (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/majestic/__init__.py` | Done |
| `src/issue_observatory/arenas/majestic/config.py` | Done |
| `src/issue_observatory/arenas/majestic/collector.py` | Done |
| `src/issue_observatory/arenas/majestic/tasks.py` | Done |
| `src/issue_observatory/arenas/majestic/router.py` | Done |

**Design notes**:
- `arena_name = "web"`, `platform_name = "majestic"`, `supported_tiers = [Tier.PREMIUM]`.
- Premium-only arena ($399.99/month Full API plan). No free or medium tier.
- Reactive analysis tool, not a polling/streaming arena. Collection is triggered by domain names discovered from other arenas.
- `collect_by_terms()`: treats each term as a domain name (extracts domain from URLs automatically). Calls `GetIndexItemInfo` in batches of up to 100 items. Returns `content_type="domain_metrics"` records.
- `collect_by_actors()`: actor_ids are domain names. Calls `GetIndexItemInfo` for metrics AND `GetBackLinkData` (Mode=1, one backlink per referring domain, up to 1,000) for individual backlinks. Returns mixed `domain_metrics` + `backlink` records.
- `FREE`/`MEDIUM` tiers: `collect_by_terms()` and `collect_by_actors()` both raise `NotImplementedError` with explanation.
- `normalize()` dispatches on `_record_type` private field:
  - `"domain_metrics"`: `platform_id` = SHA-256(domain+"_"+date), `engagement_score` = TrustFlow, all Majestic metrics in `raw_metadata`, `language=None`.
  - `"backlink"`: `platform_id` = SHA-256(SourceURL+TargetURL), `engagement_score` = SourceTrustFlow, `text_content` = AnchorText, `published_at` = FirstIndexedDate, `language=None`.
- `pseudonymized_author_id = None` for all records (no personal data in backlink/domain data).
- `author_platform_id` = domain name (proxy "author").
- `_call_majestic()`: GET `{MAJESTIC_API_BASE}?app_api_key={key}&cmd={cmd}&{params}`. Checks `response["Code"]` for `"InvalidAPIKey"`, `"RateLimitExceeded"`, `"InsufficientCredits"`, and generic non-OK codes.
- Rate limiting: `RateLimiter.wait_for_slot()` at 1 call/sec. Falls back to `asyncio.sleep(1.0)`.
- `health_check()`: `GetIndexItemInfo` for `dr.dk`, verifies TrustFlow > 0.
- Credentials: `CredentialPool.acquire(platform="majestic", tier="premium")`. JSONB: `{"api_key": "..."}`. Env-var fallback: `MAJESTIC_PREMIUM_API_KEY`.
- `estimate_credits()`: 1 credit = 1,000 analysis units. Domain metrics ~1 unit each; backlink calls ~N units for N rows.
- Celery tasks: `majestic_collect_terms`, `majestic_collect_actors`, `majestic_health_check`. Max 3 retries, exponential backoff capped at 300s. `asyncio.run()` bridges sync Celery to async collector.
- `issue_observatory.arenas.majestic.tasks` added to `workers/celery_app.py` `include` list.
- Router mounted in `api/main.py` under `/arenas` prefix: `POST /arenas/majestic/collect/terms`, `POST /arenas/majestic/collect/actors`, `GET /arenas/majestic/health`.
- HTTP 501 returned for non-premium tier requests from the router.

**Blockers / Notes for QA**:
- Credential: Majestic Full API subscription required ($399.99/month). Store API key as `platform="majestic"`, `tier="premium"`, JSONB `{"api_key": "..."}`. Also accepted via `MAJESTIC_PREMIUM_API_KEY` env var.
- Integration tests: mock `httpx.AsyncClient` via `respx` or `pytest-httpx`. Inject via `http_client` constructor parameter on `MajesticCollector`.
- `GetIndexItemInfo` response structure: `data["DataTables"]["Results"]["Data"]` (list of items). `GetBackLinkData`: `data["DataTables"]["BackLinks"]["Data"]`. Test fixtures must replicate this nesting.
- GDPR: backlink data is structural web graph data (URLs, domains). No personal data unless anchor text contains personal names. `pseudonymized_author_id` is always `None`. Art. 89 research exemption applies.
- Note on arena path: the brief specifies `arenas/web/majestic/` but the flat layout `arenas/majestic/` was used for consistency with all other Phase 1/2 arenas. The `arena_name="web"` constant correctly writes `"web"` to the DB `arena` column.

---

### Task 2.3 — Facebook and Instagram Arenas (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/facebook/__init__.py` | Done |
| `src/issue_observatory/arenas/facebook/config.py` | Done |
| `src/issue_observatory/arenas/facebook/collector.py` | Done |
| `src/issue_observatory/arenas/facebook/tasks.py` | Done |
| `src/issue_observatory/arenas/facebook/router.py` | Done |
| `src/issue_observatory/arenas/instagram/__init__.py` | Done |
| `src/issue_observatory/arenas/instagram/config.py` | Done |
| `src/issue_observatory/arenas/instagram/collector.py` | Done |
| `src/issue_observatory/arenas/instagram/tasks.py` | Done |
| `src/issue_observatory/arenas/instagram/router.py` | Done |

**Decision**: MCL is NOT approved. Bright Data is the default implementation.
PREMIUM tier methods raise `NotImplementedError` with an explanatory message.
The MCL parsing paths (`_parse_mcl_facebook`, `_parse_mcl_instagram`) are
implemented as stubs with field mappings defined so MCL can be wired in once
institutional approval is granted.

**Facebook design notes**:
- `arena_name = "social_media"`, `platform_name = "facebook"`, `supported_tiers = [Tier.MEDIUM, Tier.PREMIUM]`.
- MEDIUM: Bright Data Facebook Datasets. Asynchronous dataset delivery pattern:
  1. POST `BRIGHTDATA_TRIGGER_URL` (dataset_id=`gd_l95fol7l1ru6rlo116`) with keyword/page filters and `country="DK"`.
  2. Get `snapshot_id` from trigger response.
  3. Poll `GET /datasets/v3/progress/{snapshot_id}` every 30 seconds until `status=="ready"` (max 40 attempts = 20 minutes).
  4. GET `/datasets/v3/snapshot/{snapshot_id}?format=json` to download results.
- `collect_by_terms()`: builds keyword + country=DK filter payload, runs full trigger→poll→download cycle per term.
- `collect_by_actors()`: targets specific page by `page_url` or `page_id` in filter payload.
- `normalize()`: dispatches to `_parse_brightdata_facebook()`. Reactions total → `likes_count`; full reaction breakdown preserved in `raw_metadata`. `content_type = "comment"` if `comment_id` field is present, else `"post"`. `views_count = None` (Bright Data does not expose view counts; MCL does).
- Credentials: `CredentialPool.acquire(platform="brightdata_facebook", tier="medium")`. JSONB: `{"api_token": "bd-fb-xxx", "zone": "facebook_zone"}`.
- Rate limit: 2 calls/sec courtesy throttle via `RateLimiter.wait_for_slot()`.
- `health_check()`: GET `https://api.brightdata.com/datasets/v3` with Bearer token — 200 or 404 both confirm reachability.
- Celery tasks: `facebook_collect_terms`, `facebook_collect_actors`, `facebook_health_check`. Max 2 retries (dataset delivery is expensive). `time_limit=1800`, `soft_time_limit=1500`.
- Standalone router: `POST /arenas/facebook/collect/terms`, `POST /arenas/facebook/collect/actors`, `GET /arenas/facebook/health`.
- `issue_observatory.arenas.facebook.tasks` added to `workers/celery_app.py` include list.
- Router mounted in `api/main.py` under `/arenas` prefix.

**Instagram design notes**:
- `arena_name = "social_media"`, `platform_name = "instagram"`, `supported_tiers = [Tier.MEDIUM, Tier.PREMIUM]`.
- MEDIUM: Bright Data Instagram Scraper API. Same polling pattern as Facebook.
  Dataset ID: `gd_lyclm20il4r5helnj`. Trigger URL: `BRIGHTDATA_INSTAGRAM_POSTS_URL`.
- `collect_by_terms()`: converts terms to hashtags (`"klima debat"` → `"#klimadebat"`); terms already starting with `#` used as-is. Submits hashtag scraper request per term.
- `collect_by_actors()`: targets profile by `username` or `profile_url`. This is the recommended mode for Danish content (known accounts).
- No native language filter on Instagram. Language field passed through if Bright Data provides it; otherwise `None`. Downstream language detection applies.
- `normalize()`: dispatches to `_parse_brightdata_instagram()`. `content_type = "reel"` if `product_type` in (`clips`, `reel`, `igtv`) or `media_type == "2"`, else `"post"`. `url = "https://www.instagram.com/p/{shortcode}/"`. `shares_count = None` (not available via Bright Data). Carousel media URLs extracted from `carousel_media[]` into `media_urls`. Hashtags extracted from caption if not already in raw data.
- Credentials: `CredentialPool.acquire(platform="brightdata_instagram", tier="medium")`. JSONB: `{"api_token": "bd-ig-xxx", "zone": "instagram_zone"}`.
- Rate limit: 2 calls/sec courtesy throttle via `RateLimiter.wait_for_slot()`.
- `health_check()`: same pattern as Facebook — GET Bright Data API base URL with Bearer token.
- Celery tasks: `instagram_collect_terms`, `instagram_collect_actors`, `instagram_health_check`. Max 2 retries. `time_limit=1800`, `soft_time_limit=1500`.
- Standalone router: `POST /arenas/instagram/collect/terms`, `POST /arenas/instagram/collect/actors`, `GET /arenas/instagram/health`.
- `issue_observatory.arenas.instagram.tasks` added to `workers/celery_app.py` include list.
- Router mounted in `api/main.py` under `/arenas` prefix.

**Blockers / Notes for QA**:
- Facebook credential: Bright Data account with Facebook Datasets zone required. `platform="brightdata_facebook"`, `tier="medium"`, JSONB `{"api_token": "bd-fb-xxx", "zone": "facebook_zone"}`.
- Instagram credential: Bright Data account with Instagram Scraper zone required. `platform="brightdata_instagram"`, `tier="medium"`, JSONB `{"api_token": "bd-ig-xxx", "zone": "instagram_zone"}`.
- Note: a single Bright Data account can serve both zones; use the same account-level API token in both credentials with different zone identifiers.
- PREMIUM tier MCL stub: both `collect_by_terms()` and `collect_by_actors()` raise `NotImplementedError` for PREMIUM tier. MCL application status must be confirmed before implementing. The MCL parsing paths (`_parse_mcl_facebook`, `_parse_mcl_instagram`) contain the field mappings from the research brief and are ready for wiring once access tokens are available.
- Integration tests: mock `httpx.AsyncClient` via `respx` or `pytest-httpx`. Inject via `http_client` constructor parameter. Two sets of fixtures needed: one for the trigger response (containing `snapshot_id`), one for the progress polling responses, and one for the snapshot download response.
- Bright Data delivery latency: Facebook datasets may take hours; Instagram may take minutes to tens of minutes. `BRIGHTDATA_MAX_POLL_ATTEMPTS=40` and `BRIGHTDATA_POLL_INTERVAL=30` give a 20-minute maximum wait. The Celery `time_limit=1800` provides a 30-minute hard cap.
- GDPR: Facebook and Instagram post content and author identifiers are personal data under GDPR Art. 6(1)(e) + Art. 89 (research). Posts revealing political opinions, religious beliefs, or health conditions are Art. 9(1) special category data. Legal basis: Art. 9(2)(j) + Databeskyttelsesloven section 10. `pseudonymized_author_id` computed via `Normalizer.pseudonymize_author()`. Ensure `PSEUDONYMIZATION_SALT` is configured.
- Legal note: *Meta v. Bright Data* (2024, US District Court, dismissed). Scraping publicly accessible posts is lawful under US law. EU legal risk is moderate under GDPR and Meta ToS — document in DPIA with research exemption under GDPR Art. 89 and DSA Art. 40(12).
- No new dependencies required: both arenas use only `httpx` and `asyncio` (already in `pyproject.toml`).
- `DANISH_INSTAGRAM_HASHTAGS` in `instagram/config.py` provides a starter list of Danish hashtags for ad-hoc term collection. Expand via the query design system for production runs.

---

### Task 2.4 — Event Registry / NewsAPI.ai Arena (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/event_registry/__init__.py` | Done |
| `src/issue_observatory/arenas/event_registry/config.py` | Done |
| `src/issue_observatory/arenas/event_registry/collector.py` | Done |
| `src/issue_observatory/arenas/event_registry/tasks.py` | Done |
| `src/issue_observatory/arenas/event_registry/router.py` | Done |

**Design notes**:
- `arena_name = "news_media"`, `platform_name = "event_registry"`, `supported_tiers = [Tier.MEDIUM, Tier.PREMIUM]`.
- No free tier.  Credentials required in `CredentialPool` as `platform="event_registry"`. JSONB: `{"api_key": "..."}`.
- Pure `httpx.AsyncClient` implementation — no `eventregistry` SDK dependency. No new dependencies added to `pyproject.toml`.
- `collect_by_terms()`: POST to `https://newsapi.ai/api/v1/article/getArticles` with `lang="dan"`, `sourceLocationUri="http://en.wikipedia.org/wiki/Denmark"`, `dataType=["news","blog"]`. Page pagination with 1-token-per-request cost.
- `collect_by_actors()`: same endpoint with `conceptUri` parameter.  Actor IDs must be Event Registry concept URIs (Wikipedia-based).
- `normalize()`: `platform_id` = article `uri`, `content_type = "article"`, `language` mapped from ISO 639-3 `"dan"` → ISO 639-1 `"da"`, full `body` → `text_content`, `pseudonymized_author_id` via `Normalizer.pseudonymize_author()` using author name, NLP enrichments (`concepts`, `categories`, `sentiment`, `eventUri`) in `raw_metadata`.
- `content_hash` = SHA-256 of normalized article URL for cross-arena deduplication.
- Token budget tracking: `remainingTokens` from API response checked against `TOKEN_BUDGET_WARNING_PCT=20%` (WARNING) and `TOKEN_BUDGET_CRITICAL_PCT=5%` (CRITICAL + halt).
- Rate limit: 5 calls/sec per credential via `RateLimiter.wait_for_slot()`. Falls back to `asyncio.sleep(0.2)` when Redis unavailable.
- Error handling: HTTP 401 → `ArenaAuthError` + `credential_pool.report_error()`; HTTP 402 → `ArenaCollectionError` (token budget); HTTP 429 → `ArenaRateLimitError` (Celery auto-retry); HTTP 5xx → `ArenaCollectionError`.
- `health_check()`: tries MEDIUM then PREMIUM credential; issues single `getArticles` request; reports `remaining_tokens`.
- Celery tasks: `event_registry_collect_terms`, `event_registry_collect_actors`, `event_registry_health_check`. Max 3 retries, exponential backoff capped 300s.
- Standalone router: `POST /arenas/event-registry/collect/terms`, `POST /arenas/event-registry/collect/actors`, `GET /arenas/event-registry/health`.
- `issue_observatory.arenas.event_registry.tasks` added to `workers/celery_app.py` `include` list.
- Router mounted in `api/main.py` under `/arenas` prefix.

**Blockers / Notes for QA**:
- Credentials must be provisioned manually: register at https://newsapi.ai/register, store API key in CredentialPool as `platform="event_registry"`, `tier="medium"` or `"premium"`.
- Integration tests must mock `httpx.AsyncClient` via `respx` or `pytest-httpx`. Inject via `http_client` constructor param.
- Actor IDs (concept URIs) must be resolved before calling `collect_by_actors()`. Use `POST /api/v1/suggestConcepts` to resolve Danish entity names to URIs. This resolution step is out of scope for the collector itself.
- Token budget is the primary constraint. At 5,000 tokens/month (Medium), ~5,000 search pages (up to 500,000 articles) are available per month. Targeted use only at Medium tier.
- `isDuplicate` flag is preserved in `raw_metadata`. Downstream deduplication policy (skip vs. ingest duplicates) should be configured at the query design level.

---

### Task 2.5 — LinkedIn Import Endpoint (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/api/routes/imports.py` | Done — full implementation replacing stub |
| `src/issue_observatory/api/main.py` | Updated — imports router now mounted at `/api` prefix |

**Design notes**:
- `POST /api/content/import` — multipart form upload with `file`, `collection_method`, and optional `query_design_id` fields.
- Auth: `get_current_active_user` required (rejects inactive/unauthenticated users with HTTP 401/403).
- Format detection: `.ndjson`/`.jsonl`/`application/x-ndjson` → NDJSON; `.csv`/`text/csv` → CSV. Falls back to content-type substring match. HTTP 415 when format cannot be determined.
- File size limit: 50 MB hard cap. HTTP 413 when exceeded.
- NDJSON path: each non-empty line parsed as JSON, platform inferred via `_infer_platform_from_ndjson()` (explicit `platform` key first, then Zeeschuimer fingerprints for LinkedIn/TikTok). `collection_method` injected into raw item and `raw_metadata` before normalization.
- CSV path: `csv.DictReader` with columns `url`, `text`, `title`, `published_at`, `platform`, `author_display_name`, `author_id`, `language` mapped to normalizer-compatible keys via `_CSV_COLUMN_MAP`.
- Both paths call `Normalizer.normalize()` with `collection_tier="manual"` for imported data.
- Bulk insert: `INSERT INTO content_records (...) VALUES (...) ON CONFLICT (content_hash) DO NOTHING` per record, using SQLAlchemy `text()` with parameterized binds. Returns `(inserted, skipped)` counts.
- Error threshold: if >10% of rows error, returns HTTP 422 with full error list and aborts DB insert.
- Per-row errors returned as `{"row": N, "error": "..."}` dicts even when below threshold.
- Response: `{"imported": N, "skipped": M, "errors": [...]}`.

**Blockers / Notes for QA**:
- `content_records` table must have a unique constraint on `content_hash` for ON CONFLICT to work. Verify in DB migrations.
- LinkedIn NDJSON from Zeeschuimer does not always contain a `platform` field — the LinkedIn fingerprint detector checks for `"urn:li:"` URN patterns. Test with real Zeeschuimer exports to verify detection.
- The `arena` field defaults to `"import"` for CSV rows and falls back to `"import"` for NDJSON without an `arena` key. For LinkedIn Zeeschuimer data, explicitly include `"arena": "social_media"` in the NDJSON records or the arena column will contain `"import"`.
- Pseudonymization: `PSEUDONYMIZATION_SALT` must be set for `pseudonymized_author_id` to be populated. Without it, `Normalizer` logs a WARNING and sets `pseudonymized_author_id=None`.
- No new dependencies required — only stdlib (`csv`, `io`, `json`) and existing project dependencies.

---

### Task 2.2 — Google SERP Verification (2026-02-16)

**Verification result**: Two defects found and fixed.

**Checks performed**:

1. `acquire()` called with correct `platform` and `tier` arguments — **PASS (no change needed)**
   - `_acquire_credential()` calls `self.credential_pool.acquire(platform=provider_platform, tier=tier.value)` where `provider_platform` is `"serper"` for MEDIUM and `"serpapi"` for PREMIUM. The `tier.value` produces the lowercase tier string (`"medium"` / `"premium"`) as required by `CredentialPool.acquire()`.

2. `release()` called in `finally` block — **FAIL — FIXED**
   - `collect_by_terms()` acquired the credential at line 145 but had no `try/finally` around the HTTP client block. If any exception escaped from `_collect_term()` (e.g. `ArenaCollectionError` other than rate-limit/auth), the credential lease in Redis would never be released.
   - Fix: wrapped the `async with self._build_http_client()` block in `try/finally`, calling `self.credential_pool.release(credential_id=cred["id"])` in the `finally` clause.

3. `report_error()` called on 429/auth failures — **PARTIAL FAIL — FIXED**
   - `_collect_term()` correctly catches `(ArenaRateLimitError, ArenaAuthError)` and calls `report_error()`.
   - Defect: the `error` argument was hardcoded as `ArenaRateLimitError("rate limit hit")` regardless of which exception was actually raised. When an `ArenaAuthError` was caught, the credential pool received a synthetic rate-limit error instead of the real auth error, causing incorrect backoff classification in `_report_db_error()` (the isinstance check on `ArenaAuthError` would never trigger for DB credentials).
   - Fix: changed `except (ArenaRateLimitError, ArenaAuthError) as exc` and passed `error=exc` to `report_error()`.

4. No hardcoded API keys — **PASS (no change needed)**
   - All credentials flow through `CredentialPool`. No string literals resembling API keys appear in the file.

**Files modified**:
- `src/issue_observatory/arenas/google_search/collector.py` — two targeted fixes (lines ~149-162 and ~435-441 in original).

---

### Task 0.12 — Google Search Arena (2026-02-15)

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/google_search/__init__.py` | Done |
| `src/issue_observatory/arenas/google_search/config.py` | Done |
| `src/issue_observatory/arenas/google_search/collector.py` | Done |
| `src/issue_observatory/arenas/google_search/tasks.py` | Done |
| `src/issue_observatory/arenas/google_search/router.py` | Done |
| `src/issue_observatory/arenas/google_search/README.md` | Done |

### Task 0.12 — Design notes
- FREE tier returns `[]` with a warning log; no exception raised.
- MEDIUM tier uses Serper.dev (POST JSON, `X-API-KEY` header).
- PREMIUM tier uses SerpAPI (GET with query params, `api_key` param).
- Danish params `gl=dk&hl=da` applied on every request via `DANISH_PARAMS`.
- Credentials acquired via `CredentialPool.acquire(platform="serper", tier="medium")`
  and `acquire(platform="serpapi", tier="premium")`.  Env var names:
  `SERPER_MEDIUM_API_KEY`, `SERPAPI_PREMIUM_API_KEY`.
- `collect_by_actors()` converts domain actor IDs to `site:` queries and
  delegates to `collect_by_terms()` — not a `NotImplementedError` stub.
- `normalize()` delegates to `Normalizer.normalize()` with `content_type="search_result"`.
- Celery task `google_search_collect_terms` auto-retries on `ArenaRateLimitError`
  (max 3 retries, exponential backoff capped at 5 min).
- `_update_task_status()` is best-effort: DB failures are logged at WARNING
  and do not mask collection outcomes.
- `health_check()` acquires MEDIUM credential, fires a 1-result test query to
  Serper.dev, and always releases the credential in a `finally` block.

---

### Task 0.9b — Actors Routes (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/api/routes/actors.py` | Done — full implementation replacing stub |
| `src/issue_observatory/core/schemas/actors.py` | Done — ActorCreate, ActorUpdate, ActorResponse, PresenceResponse, ActorPresenceCreate |

**Design notes**:
- `GET /actors/` and `GET /actors/search`: filter on `created_by = current_user.id OR is_shared = true`. Cursor pagination by UUID on list; fixed 20-result cap on search.
- `POST /actors/`: creates `Actor` with `created_by = current_user.id`. Optional inline `presence` field creates an `ActorPlatformPresence` in the same transaction (flush → commit pattern).
- `GET /actors/{id}`: read-accessible when `is_shared=True` or owner/admin. Uses `_check_actor_readable()` helper (calls `ownership_guard` only for private actors).
- `PATCH /actors/{id}`: partial update via `model_dump(exclude_unset=True)`. Ownership required.
- `DELETE /actors/{id}`: hard delete with cascade (aliases, presences, list memberships). Ownership required.
- `GET /actors/{id}/content`: queries `content_records WHERE author_id = actor.id`. Keyset cursor on `(published_at DESC, id DESC)`. Returns HTML `<ul>` fragment when `HX-Request` header is present, JSON list otherwise.
- `POST /actors/{id}/presences`: creates `ActorPlatformPresence`. HTTP 409 on unique constraint violation (platform + platform_user_id pair).
- `DELETE /actors/{id}/presences/{pid}`: hard delete of presence record.
- HTMX detection: `HX-Request` header (alias in `Header(alias="HX-Request")`). HTML fragments use `HTMLResponse` from `fastapi.responses`.
- All write routes use `ownership_guard(actor.created_by or uuid.UUID(int=0), current_user)` — the fallback `uuid.UUID(int=0)` means an actor with no creator is only modifiable by admins.

**Blockers / Notes for QA**:
- `content_records.author_id` FK must be populated for `GET /actors/{id}/content` to return results. Normaliser sets this field when the actor is known at collection time.
- `HX-Request` header may be blocked by some CORS configurations; ensure it is listed in `allow_headers` in CORS middleware (currently `["*"]` — safe).
- Integration tests: mock `get_db` session with SQLAlchemy in-memory or test DB.

---

### Task 0.4 — Arena Config Endpoints (2026-02-16) — Partial, DB blocker

**Added to `api/routes/query_designs.py`**:
- `GET  /query-designs/{id}/arena-config` — returns per-arena tier config
- `POST /query-designs/{id}/arena-config` — validates and saves per-arena tier config

**Design notes**:
- Ownership guard applied via `ownership_guard(design.owner_id, current_user)` on both endpoints.
- `GET`: reads `arenas_config` JSONB from the most recent `CollectionRun` for the design. Returns `{"arenas": []}` when no run exists.
- `POST`: validates all `tier` values against `Tier` enum. Persists as `{"arenas": [...]}` on the most recent run. If no run exists, creates a `CollectionRun(mode="batch", status="pending")` placeholder.
- Tier validation: unknown values return HTTP 422 with list of invalid values and acceptable set.
- `_raw_config_to_response()` supports both legacy dict format (`{"arena_id": "tier"}`) and the list format written by POST.

**DB Schema Blocker**:
- The spec requested storage on `query_designs.arenas_config` JSONB, but that column does not exist on the `QueryDesign` ORM model (DB Engineer owned).
- Current workaround: config is stored on `collection_runs.arenas_config` via the most recent run.
- **Action required from DB Engineer**: add `arenas_config JSONB NOT NULL DEFAULT '{}'` to `query_designs` table and update `QueryDesign` model, then migrate these endpoints to read/write from `QueryDesign` directly.

---

### Task 0.12 — Blockers / Notes
- `/docs/arenas/google_search.md` brief does not exist on disk.  Task was
  executed using the inline specification provided in the task description,
  which is functionally equivalent.  The Research Agent should create the
  brief retroactively for completeness.
- QA Engineer: integration test should mock Serper.dev responses using
  `respx` or `pytest-httpx`.  The `http_client` constructor argument on
  `GoogleSearchCollector` supports injection of a mock client.
- `_update_task_status()` imports `get_sync_session` lazily — if the DB
  schema is not yet migrated, the import will fail gracefully (logged at
  WARNING).  This is acceptable in Phase 0 where the DB migration may lag
  arena implementation.

---

### GR-07 — Generalised Language Detector (2026-02-19) — Complete

| File | Change |
|------|--------|
| `src/issue_observatory/analysis/enrichments/language_detector.py` | `DanishLanguageDetector` renamed to `LanguageDetector`; `DanishLanguageDetector` kept as backwards-compat alias |
| `src/issue_observatory/analysis/enrichments/__init__.py` | Both `LanguageDetector` and `DanishLanguageDetector` exported; `__all__` updated; module docstring updated |
| `src/issue_observatory/workers/tasks.py` | `enrich_collection_run` now instantiates `LanguageDetector(expected_languages=language_codes)`; new optional `language_codes` task parameter |

**Changes**:

1. **Renamed class** — `DanishLanguageDetector` → `LanguageDetector`. The old
   name is retained as a module-level alias so any existing import continues to
   resolve without modification.

2. **`expected_languages` constructor param** — `LanguageDetector` accepts an
   optional `list[str]` of ISO 639-1 codes.  When provided, every enrichment
   result carries an `"expected"` boolean field (`True` if detected language is
   in the list, `False` otherwise).  When omitted, `"expected"` is `None`.

3. **Neutral fallback** — the Danish-character heuristic (`_DANISH_CHARS`,
   `_HEURISTIC_THRESHOLD`) is removed.  When langdetect is unavailable:
   - If exactly one `expected_languages` code is configured, that code is
     assumed with `confidence=None, detector="heuristic_single_lang"`.  This
     restores the original Danish-only behaviour for Danish-only collections.
   - Otherwise, returns `language=None, confidence=None, detector="none"`.

4. **Output schema** — enrichment result dict gains the `"expected"` field.
   All existing fields (`language`, `confidence`, `detector`) are unchanged.

5. **Task wiring** — `enrich_collection_run` in `workers/tasks.py` now accepts
   an optional `language_codes: list[str] | None` parameter and passes it to
   `LanguageDetector(expected_languages=language_codes)`.  Callers that
   dispatch `enrich_collection_run` can now supply the query design's language
   codes (already available via `parse_language_codes()` in
   `trigger_daily_collection`).  Existing callers that do not pass the argument
   get `LanguageDetector(expected_languages=None)`, which is equivalent to the
   previous unconfigured `DanishLanguageDetector()`.

**Backwards compatibility**: existing imports of `DanishLanguageDetector` from
either `language_detector` or `enrichments` continue to work.
`DanishLanguageDetector()` (no args) → `LanguageDetector(expected_languages=None)`.

---

### Task 0.4 (remaining) — Content Browser Routes (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/api/routes/content.py` | Done — browse page, records fragment, detail endpoints |
| `src/issue_observatory/api/templates/_fragments/content_table_body.html` | Done — full `<tr>` row rendering with chips, badges, detail link |

**New routes added to `content.py`**:

- `GET /content/` — renders `content/browser.html` full page.  Passes `records` (first 50), `total_count`, `recent_runs`, `filter`, `cursor` to template.
- `GET /content/records` — HTMX HTML fragment endpoint.  Returns `<tr>` rows via `_fragments/content_table_body.html`.  Keyset pagination on `(published_at DESC NULLS LAST, id DESC)`.  Hard cap at 2000 rows via `offset` query param.  Supports multi-value `arenas` checkbox group. Full-text search via `to_tsvector('danish', ...)` + `plainto_tsquery`.
- `GET /content/{record_id}` — renders `content/record_detail.html`.  Panel partial when `HX-Request` header present; standalone full page otherwise.

**Helper functions added**:
- `_build_browse_stmt()` — keyset-paginated SELECT with full-text search and all filters.
- `_encode_cursor()` / `_decode_cursor()` — opaque `published_at|id` cursor format.
- `_parse_date_param()` — YYYY-MM-DD → UTC datetime.
- `_orm_row_to_template_dict()` / `_orm_to_detail_dict()` — ORM → template context dicts.
- `_fetch_recent_runs()` — last 20 runs for sidebar selector.
- `_count_matching()` — approximate total count for the record-count badge.

**Ownership scoping**: non-admin users restricted to records in their own collection runs via `CollectionRun.initiated_by` subquery.

**Blockers / Notes for QA**:
- `_count_matching()` runs a `COUNT(*)` over a subquery — may be slow on large partitioned tables.  Consider `EXPLAIN ANALYZE` and caching if this becomes a bottleneck.
- `to_tsvector` FTS relies on the GIN index created in migration `001_initial_schema.py`.  Ensure migration has run before testing the `q` parameter.
- The `arenas` multi-value param (checkbox group) works when the browser sends `arenas=foo&arenas=bar`.  FastAPI decodes this as `list[str]` via `Query(default=None)`.

---

### Task 3.10 — Inbound API Rate Limiting (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/api/limiter.py` | Done — new module holding the `Limiter` singleton |
| `src/issue_observatory/api/main.py` | Done — `SlowAPIMiddleware` + exception handler wired into `create_app()` |
| `src/issue_observatory/api/routes/content.py` | Done — `@limiter.limit("10/minute")` on `GET /content/export` |
| `src/issue_observatory/api/routes/collections.py` | Done — `@limiter.limit("20/minute")` on `POST /collections/` |
| `pyproject.toml` | Done — `slowapi>=0.1.9,<1.0` added to `[project.dependencies]` |

**Design**:
- Global limit: 100 requests/minute per IP, applied via `SlowAPIMiddleware` (middleware-level, no per-route annotation needed).
- `GET /content/export` → 10/minute per IP (heavy: DB query + in-memory file assembly).
- `POST /collections/` → 20/minute per IP (heavy: spawns Celery tasks, credits check).
- Limiter singleton lives in `api/limiter.py` to avoid circular imports (`main.py` imports route modules; route modules needed the limiter before `main.py` fully loaded).
- `request: Request` parameter added to both rate-limited route functions (required by slowapi to resolve the key function).

**Notes for QA**:
- Test 429 responses by hitting `/content/export` 11 times within a minute from the same IP.
- `SlowAPIMiddleware` is added before `CORSMiddleware` in the middleware stack so that 429 responses are returned before CORS headers are appended.
- The `_rate_limit_exceeded_handler` returns JSON `{"error": "Rate limit exceeded: ..."}` with `Retry-After` header.

---

### Task 3.7 — Analysis API Routes (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/api/routes/analysis.py` | Done — full implementation replacing stub |

**Endpoints implemented**:
- `GET /analysis/` → 302 redirect to `/collections` (select-a-run prompt)
- `GET /analysis/{run_id}` → HTML dashboard (`analysis/index.html` Jinja2 TemplateResponse)
- `GET /analysis/{run_id}/summary` → JSON run summary via `get_run_summary()`
- `GET /analysis/{run_id}/volume` → JSON volume over time via `get_volume_over_time()`, params: `platform`, `arena`, `date_from`, `date_to`, `granularity`
- `GET /analysis/{run_id}/actors` → JSON top actors via `get_top_actors()`, params: `platform`, `date_from`, `date_to`, `limit`
- `GET /analysis/{run_id}/terms` → JSON top terms via `get_top_terms()`, params: `date_from`, `date_to`, `limit`
- `GET /analysis/{run_id}/engagement` → JSON engagement distribution via `get_engagement_distribution()`, params: `platform`, `arena`, `date_from`, `date_to`
- `GET /analysis/{run_id}/network/actors` → JSON actor co-occurrence graph
- `GET /analysis/{run_id}/network/terms` → JSON term co-occurrence graph
- `GET /analysis/{run_id}/network/cross-platform` → JSON cross-platform actor list
- `GET /analysis/{run_id}/network/bipartite` → JSON bipartite actor-term graph

**Auth + ownership**: all endpoints require `get_current_active_user`. `_get_run_or_raise()` helper fetches the `CollectionRun`, raises HTTP 404 if not found, calls `ownership_guard()` to raise HTTP 403 if the user is not the owner or admin.

**Router mounting**: already mounted in `api/main.py` with `prefix="/analysis", tags=["analysis"]` — no change needed.

---

### Task 3.4 — Analysis UI Template (2026-02-16) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/api/templates/analysis/index.html` | Done — full implementation |
| `src/issue_observatory/api/static/js/charts.js` | Done — four new helper functions added |

**Template sections**:
- Page header with run UUID, status badge, tier badge, mode badge (server-rendered from `run` context dict)
- Summary cards (4): total records, arena count, date range, credits spent — fetched via Alpine `summaryCards()` component calling `GET /analysis/{run_id}/summary`
- Filter bar: platform, arena, date from/to, granularity toggle (hour/day/week/month), Apply and Reset buttons — managed by top-level `analysisDashboard()` Alpine component; filter state shared via `window.__analysisFilters`; Apply broadcasts `filter-applied` CustomEvent; chart panels reload on `@filter-applied.window`
- Volume-over-time chart (multi-arena line): canvas `#volumeChart`, uses `initMultiArenaVolumeChart()`
- Top actors horizontal bar chart: canvas `#actorsChart`, uses `initActorsChart()`
- Top terms horizontal bar chart: canvas `#termsChart`, uses `initTermsChart()`
- Engagement distribution grouped bar chart (mean/median/p95): canvas `#engagementChart`, uses `initEngagementStatsChart()`
- Network section: 4-tab switcher (actor/term/bipartite/cross-platform); first three tabs show GEXF download link; cross-platform tab renders live table loaded via `networkTabs()` Alpine component
- Export section: format radio buttons (csv/xlsx/json/parquet/gexf); sync export anchor; async export button with 3s polling via `exportPanel()` Alpine component; job status display with progress percentage

**New `charts.js` helpers**:
- `initActorsChart(canvasId, data)` — horizontal bar, blue palette
- `initTermsChart(canvasId, data)` — horizontal bar, amber palette
- `initEngagementStatsChart(canvasId, data)` — grouped bar with mean/median/p95 datasets
- `initMultiArenaVolumeChart(canvasId, data)` — multi-dataset line chart, one series per arena

**Notes for QA**:
- Chart panels gracefully show an error message if the fetch fails (network issue, 403, 404).
- If entity resolution has not been run for a collection, the cross-platform actors table shows an empty-state message.
- The async export polling stops automatically on `complete` or `failed` status.
- Alpine `window.__analysisFilters` is a live proxy object so chart sub-components always read the latest filter state without re-parsing query parameters.

---

## Task 3.11 — Documentation (2026-02-16) — Complete

Four operations documentation files written:

| File | Status |
|------|--------|
| `docs/operations/deployment.md` | Done — prerequisites, env var reference table, production Docker Compose, Tailwind rebuild, first-run checklist, Nginx/Caddy reverse proxy snippets, Celery startup commands, Prometheus scrape config |
| `docs/operations/secrets_management.md` | Done — SECRET_KEY and CREDENTIAL_ENCRYPTION_KEY generation, Docker Secrets approach, backup procedure, rotation procedures, consequence-of-loss guidance |
| `docs/operations/arena_config.md` | Done — three-tier pricing summary, per-arena credential setup for all 19 arenas (credential_key, tier, JSONB fields, env-var fallbacks), admin UI vs script vs direct DB insert, credit cost table, beat schedule summary |
| `docs/operations/api_reference.md` | Done — auth (cookie/bearer/API key), pagination, ownership scoping, HTMX vs JSON, all endpoint groups with paths, rate limits (100/min global, 20/min collection launch, 10/min export), error format, Prometheus metrics table |

---

## Task 3.12 — Prometheus Metrics (2026-02-16) — Complete

| File | Status |
|------|--------|
| `src/issue_observatory/api/metrics.py` | Done — 8 metrics: collection_runs_total, collection_records_total, arena_health_status, credit_transactions_total, http_requests_total, http_request_duration_seconds, celery_tasks_total, celery_task_duration_seconds; get_metrics_response() helper |
| `src/issue_observatory/config/settings.py` | Updated — added `metrics_enabled: bool = True` field |
| `src/issue_observatory/api/main.py` | Updated — `GET /metrics` route (gated by settings.metrics_enabled); Prometheus HTTP middleware recording http_requests_total and http_request_duration_seconds, skipping /metrics and /static paths |
| `src/issue_observatory/workers/tasks.py` | Updated — all 5 orchestration tasks record celery_tasks_total and celery_task_duration_seconds at completion; metrics import wrapped in try/except so failures never crash tasks |
| `pyproject.toml` | Updated — added `prometheus-client>=0.20,<1.0` to [project.dependencies] |

**Design notes**:
- All metric objects are module-level singletons in `api/metrics.py`. Prometheus deduplicates by name so safe to import from multiple modules.
- HTTP middleware skips `/metrics` self-scrape and `/static` asset paths to avoid noise.
- Celery tasks use lazy imports (`from issue_observatory.api.metrics import ...` inside the task body) wrapped in `try/except Exception` — metrics recording failures are logged at DEBUG and never propagate to the task return value.
- `arena_health_status` Gauge is defined here for arena tasks to set directly; the `health_check_all_arenas` task should be extended to call `arena_health_status.labels(arena=name).set(1 or 0)` based on actual health check results.
- Prometheus scrape config snippet documented in `docs/operations/deployment.md`.

---

## Phase 3 Blocker Fixes (2026-02-17)

### B-01 — Snowball Sampling API Route — Fixed

| File | Status |
|------|--------|
| `src/issue_observatory/api/routes/actors.py` | Updated — three new endpoints added |

**New endpoints**:
- `GET /actors/sampling/snowball/platforms` — returns the list of platforms that support first-class network expansion (`bluesky`, `reddit`, `youtube`). Derived from the explicit `if/elif` dispatch in `NetworkExpander.expand_from_actor()`. Auth: `get_current_active_user`.
- `POST /actors/sampling/snowball` — runs `SnowballSampler.run()` synchronously. Body: `{seed_actor_ids, platforms, max_depth=2, max_actors_per_step=20, add_to_actor_list_id?}`. Returns `{total_actors, max_depth_reached, wave_log, actors}`. Logs a WARNING if the operation takes >30 s. Auth: `get_current_active_user`.
- `POST /actors/lists/{list_id}/members/bulk` — idempotent bulk-add. Body: `{actor_ids}`. Returns `{added, already_present}`. Auth: ownership_guard on the ActorList. Returns HTTP 200 (idempotent convenience call, not a creation).

**Design notes**:
- All three endpoints are declared before the parametric `/{actor_id}` routes to prevent FastAPI routing ambiguity.
- `SnowballRequest`, `SnowballResponse`, `SnowballWaveEntry`, `SnowballActorEntry`, `BulkMemberRequest`, `BulkMemberResponse` Pydantic schemas are defined inline in the actors router module.
- `add_to_actor_list_id` is validated (ownership check) *before* the expensive sampling call so the API fails fast on auth errors.
- The `_bulk_add_to_list()` private helper is shared between the snowball endpoint and the standalone bulk-member endpoint.
- `ActorList` is imported inside route bodies (lazy import) to avoid a cross-module circular import between `actors.py` routes and `query_design` models.
- `_NETWORK_EXPANSION_PLATFORMS` constant is defined at module level from code inspection of `NetworkExpander`; update it if new platform expanders are added.

---

### B-03 — Live Tracking Suspend/Resume/Schedule — Fixed

| File | Status |
|------|--------|
| `src/issue_observatory/core/models/collection.py` | Updated — `suspended_at` column + `'suspended'` status documented |
| `src/issue_observatory/core/schemas/collection.py` | Updated — `suspended_at: Optional[datetime]` added to `CollectionRunRead` |
| `src/issue_observatory/api/routes/collections.py` | Updated — three new endpoints added |
| `alembic/versions/003_add_suspended_at_to_collection_runs.py` | Created — migration adds `suspended_at TIMESTAMPTZ NULL` column |

**New endpoints**:
- `POST /collections/{run_id}/suspend` — sets `status='suspended'`, records `suspended_at=NOW()`. HTTP 409 if not `mode='live'` and `status='active'`.
- `POST /collections/{run_id}/resume` — sets `status='active'`, clears `suspended_at`. HTTP 409 if not `mode='live'` and `status='suspended'`.
- `GET /collections/{run_id}/schedule` — returns `{mode, status, next_run_at, timezone, last_triggered_at, suspended_at}`. HTTP 400 if not a live run.

**Design notes**:
- `next_run_at` is derived statically from `beat_schedule.py` (`crontab(hour=0, minute=0)` → `"00:00 Copenhagen time"`). This is intentionally a human-readable string rather than a computed timestamp to avoid timezone arithmetic issues in the API layer; the frontend can render it directly.
- `last_triggered_at` maps to `CollectionRun.started_at` (the timestamp of the last Celery Beat trigger for this run).
- `suspended_at` is nullable on both the ORM model and the Alembic migration; it is `None` for batch runs and active live runs.
- Migration 003 chains `down_revision = "002"`. Run `alembic upgrade 003` (or `alembic upgrade head`) to apply.

---

## Phase D — Item 14 / IP2-052 / IP2-061 (2026-02-18) — Complete

### Item 14 — Boolean Query Support in Arena Collectors

**New shared utility: `src/issue_observatory/arenas/query_builder.py`**
- `build_boolean_query_groups(term_specs)` — groups SearchTerm-like dicts into AND groups (same group_id → AND, different groups → OR, group_id=None → individual OR)
- `format_boolean_query_for_platform(groups, platform)` — formats AND/OR groups as platform-native query syntax (google: implicit AND space, twitter/x_twitter: `(t1 t2) OR`, reddit: `t1+t2`, youtube: `|` for OR, gdelt: explicit `AND`/`OR`, bluesky: space-join)
- `has_boolean_groups(term_specs)` — predicate

**Updated `arenas/base.py`**: `collect_by_terms()` abstract signature extended with `term_groups: list[list[str]] | None = None` and `language_filter: list[str] | None = None`.

**Updated all 20 collector implementations** (google_search, google_autocomplete, bluesky, reddit, youtube, rss_feeds, gdelt, telegram, tiktok, ritzau_via, gab, threads, facebook, instagram, common_crawl, wayback, majestic, event_registry, x_twitter, ai_chat_search):
- Native boolean via single query: google_search, x_twitter, gdelt, youtube, event_registry
- Separate-requests-per-group with deduplication: bluesky, reddit, telegram, tiktok, ritzau_via, gab, facebook, instagram, common_crawl, wayback
- Client-side filtering: rss_feeds, threads
- Flatten all groups (domain names, no boolean): majestic
- Individual terms per group (autocomplete): google_autocomplete, ai_chat_search

**Updated all 20 arena `tasks.py` files**: added `language_filter: list[str] | None = None` parameter; passed through to `collector.collect_by_terms()`.

### IP2-052 — Multilingual Query Design

**Updated `core/schemas/query_design.py`**:
- Added `parse_language_codes(language: str) -> list[str]` utility — splits comma-separated language string, strips/lowercases/deduplicates
- Added `_normalise_language(value: str) -> str` — validates each code against `[a-zA-Z]{2,3}`, normalises for storage
- `QueryDesignCreate.language` accepts comma-separated codes (`"da,en"`); validated via `@field_validator`; `max_length=10` aligned to DB column
- `QueryDesignUpdate.language` (new field): same validator, optional

**Updated `workers/_task_helpers.py`**: `fetch_live_tracking_designs()` now returns `language` field from `QueryDesign.language`.

**Updated `workers/tasks.py`**: `trigger_daily_collection` imports `parse_language_codes`, splits `raw_language` per design, passes `language_filter` list in Celery task kwargs alongside `collection_run_id` and `tier`.

### Phase 2.5 — Wikipedia Arena (2026-02-18) — Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/wikipedia/__init__.py` | Done |
| `src/issue_observatory/arenas/wikipedia/config.py` | Done |
| `src/issue_observatory/arenas/wikipedia/collector.py` | Done |
| `src/issue_observatory/arenas/wikipedia/tasks.py` | Done |
| `src/issue_observatory/arenas/wikipedia/router.py` | Done |

**Design notes**:
- `arena_name = "reference"` (new arena group), `platform_name = "wikipedia"`, `supported_tiers = [Tier.FREE]`.
- No credentials required. Mandatory `User-Agent` header set via `DEFAULT_USER_AGENT` constant.
- Two record types: `wiki_revision` (edit to article) and `wiki_pageview` (daily view count).
- `collect_by_terms()`: three-step pipeline — (1) search articles via `action=query&list=search`, (2) collect revision history via `action=query&prop=revisions`, (3) collect pageviews via Wikimedia Analytics API.
- `collect_by_actors()`: treats `actor_ids` as Wikipedia usernames; fetches via `action=query&list=usercontribs` on both da.wikipedia and en.wikipedia.
- Rate limiting: `asyncio.Semaphore(5)` + 0.2 s inter-request sleep = 5 req/s polite limit.
- Bot edit filtering: edits with bot-related tags excluded by default (`INCLUDE_BOT_EDITS = False`).
- Danish defaults: `da.wikipedia.org` queried first; `en.wikipedia.org` included when `language_filter` is None or includes `"en"`.
- `platform_id` format: `{wiki_project}:rev:{revision_id}` for revisions; `{wiki_project}:pv:{article}:{date}` for pageviews.
- `raw_metadata` structure: revisions include `delta`, `minor`, `tags`, `parentid`, `namespace`, `is_talk_page`, `wiki_project`, `page_id`; pageviews include `access`, `agent`, `wiki_project`.
- Celery tasks: `wikipedia_collect_terms`, `wikipedia_collect_actors`, `wikipedia_health_check`.
- Router: 4 endpoints — `POST /wikipedia/collect/terms`, `POST /wikipedia/collect/actors`, `GET /wikipedia/health`, `GET /wikipedia/pageviews/{article}`.
- Cross-cutting registry/celery updates (ARENA_DESCRIPTIONS entry, celery_app include) are a separate task; the collector registers itself via `@register` on import.

---

### IP2-061 — Mixed Hash/Name Resolution in Top Actors Chart

**Updated `analysis/descriptive.py`**: `get_top_actors()` now LEFT JOINs `actors a ON a.id = c.author_id`. Returns two additional fields:
- `resolved_name`: `actors.canonical_name` when entity resolution is complete, `None` otherwise
- `actor_id`: UUID string of the resolved actor, `None` otherwise

---

## GR-19 — Co-mention Fallback in Network Expander (2026-02-19) — Complete

| File | Change |
|------|--------|
| `src/issue_observatory/sampling/network_expander.py` | Implemented `_expand_via_comention()` method; hooked into `expand_from_actor()` `else` branch |

**Implementation details:**

- `_expand_via_comention(actor_id, platform, presence, db, top_n=50, min_records=2)` — new async method on `NetworkExpander`.
- **Step 1 (SQL)**: queries `content_records` (platform-scoped) for rows whose `text_content` contains the seed actor's `@username` or `@user_id` via PostgreSQL `ILIKE` (case-insensitive substring), capped at 5 000 rows.
- **Step 2 (Python regex)**: applies `_COMENTION_MENTION_RE` (`(?<!\w)@([A-Za-z0-9_](?:[A-Za-z0-9_.%-]{0,48}[A-Za-z0-9_])?)`) to re-validate that the seed actor is genuinely mentioned (eliminates false-positive substrings), then extracts all other `@mention` patterns from those records.
- **Step 3 (filter + rank)**: retains only co-mentioned usernames present in >= 2 distinct content records; returns top 50 ordered by frequency descending.
- **Dispatch integration**: the `else` branch of `expand_from_actor()` now calls `_expand_via_comention()` for all platforms without a dedicated expander (Telegram, Discord, TikTok, Gab, X/Twitter, Threads, Instagram, Facebook, etc.).
- **Regex coverage**: the combined `@`-pattern covers Twitter/X, Threads, Instagram, Gab, Mastodon, TikTok (plain handles) and Bluesky/AT Protocol (handles with dots).
- `discovery_method` on returned dicts: `"comention_fallback"`.
- Module constants added: `_COMENTION_MENTION_RE`, `_COMENTION_MIN_RECORDS = 2`, `_COMENTION_TOP_N = 50`.

---

## GR-20 — Auto-create Actor Records for Snowball-discovered Accounts (2026-02-19) — Complete

| File | Change |
|------|--------|
| `src/issue_observatory/sampling/snowball.py` | Added `auto_created_actor_ids` field to `SnowballResult`; added `auto_create_actor_records()` method to `SnowballSampler` |
| `src/issue_observatory/api/routes/actors.py` | Updated `SnowballRequest` (`auto_create_actors: bool = True`), `SnowballResponse` (`newly_created_actors: int`), and `run_snowball_sampling` route handler |

**Implementation details:**

- `SnowballResult.auto_created_actor_ids: list[uuid.UUID]` — new attribute (empty list until `auto_create_actor_records()` is called).
- `SnowballSampler.auto_create_actor_records(result, db, created_by)` — async method that:
  1. Iterates `result.actors`, skipping seed actors (`discovery_depth == 0`) which are guaranteed to already exist.
  2. For each non-seed actor with `platform` + `platform_user_id`, checks `actor_platform_presences` for a pre-existing row.
  3. If none exists: creates `Actor(canonical_name, actor_type="unknown", is_shared=False, metadata_={"auto_created_by": "snowball_sampling", "notes": "Auto-created by snowball sampling"})` and `ActorPlatformPresence(platform, platform_user_id, platform_username, profile_url, verified=False)`.
  4. Uses `db.flush()` per record to obtain the generated UUID, then a single `db.commit()` at the end.
  5. On per-record DB error: rolls back that record and continues (error isolation).
  6. Annotates each created `actor_dict` with `"actor_uuid"` so `_bulk_add_to_list` can add them to an actor list in the same request.
  7. Returns the list of newly created UUIDs and appends them to `result.auto_created_actor_ids`.
- **API changes**:
  - `SnowballRequest.auto_create_actors: bool = True` — opt-out flag for callers that want discovery-only without DB writes.
  - `SnowballResponse.newly_created_actors: int = 0` — count of auto-created Actor records in the response body.
  - The route handler calls `auto_create_actor_records()` before `_bulk_add_to_list()` so that auto-created actors (now carrying `actor_uuid`) are included when populating an actor list.
  - `snowball_sampling_complete` log event now includes `newly_created_actors` count.

The front-end in `analysis/index.html` `actorsChart()` function already used `r.resolved_name` (written in anticipation of this feature); no template changes required.

---

## GR-21 — Telegram Forwarding Chain Expander (2026-02-19) — Complete

| File | Change |
|------|--------|
| `src/issue_observatory/sampling/network_expander.py` | Added `_expand_via_telegram_forwarding()` method; wired into `expand_from_actor()` `elif platform == "telegram"` branch |

**Implementation details:**

- `_expand_via_telegram_forwarding(actor_id, platform, presence, db, top_n=20, min_forwards=2, depth=1)` — queries `content_records` for Telegram messages from the seed actor's channel that contain forwarded-message metadata (`raw_metadata ->> 'is_forwarded' = 'true'`), extracts `fwd_from_channel_id` values using PostgreSQL JSONB operators, counts their frequency, and returns the top-`top_n` source channels as discovery candidates.
- The query uses a PostgreSQL `GROUP BY ... HAVING COUNT(*) >= :min_forwards` clause so that only channels from which the seed forwarded at least `min_forwards` messages are returned. The count is done server-side to avoid fetching large result sets into Python.
- Author filtering uses `(author_platform_id = :user_id OR author_id = :actor_id::uuid)` so that both the numeric Telegram channel ID and the Actor UUID FK are tried. When only the actor UUID is available (no `platform_user_id`), only the UUID FK path is used.
- Returns empty list immediately when `db is None` (graceful no-DB handling).
- Returns empty list when neither `platform_user_id` nor `platform_username` is present in the actor presence (cannot scope the query).
- Each returned dict contains the standard `ActorDict` fields (`canonical_name`, `platform`, `platform_user_id`, `platform_username`, `profile_url`, `discovery_method`) plus extra keys `forward_count` and `depth` for downstream use.
- `discovery_method` is set to `"telegram_forwarding_chain"`.
- **Fallback ordering in `expand_from_actor()`**: the `elif platform == "telegram"` branch calls `_expand_via_telegram_forwarding()` first. If it returns an empty list (no forwarding data collected yet for that channel), it falls through to `_expand_via_comention()`. This `elif`/fallback ordering ensures that the forwarding-chain strategy takes priority while still providing useful results for new or low-activity channels.

See the GR-19 section for co-mention fallback context. The `elif` ordering in `expand_from_actor()` ensures the Telegram forwarding strategy is always tried first.

---

## GR-09 — Volume Spike Alerting (2026-02-19) — Complete

Threshold-based alerting that detects when collection volume for an arena
exceeds 2x the rolling 7-day average and sends an email notification to the
query design owner.

| File | Status |
|------|--------|
| `src/issue_observatory/analysis/alerting.py` | Done — spike detection, persistence, email notification, fetch helper |
| `src/issue_observatory/workers/_alerting_helpers.py` | Done — async DB helper bridging Celery sync context |
| `src/issue_observatory/workers/tasks.py` | Updated — Task 7 `check_volume_spikes_task` added; `settle_pending_credits` dispatches it once per completed run |
| `src/issue_observatory/workers/_task_helpers.py` | Updated — `fetch_unsettled_reservations` now also returns `query_design_id` |
| `src/issue_observatory/api/routes/query_designs.py` | Updated — `GET /query-designs/{design_id}/alerts` endpoint added |

**Design notes:**

- `detect_volume_spikes()` in `analysis/alerting.py`:
  - Queries `content_records` for the current run's per-arena/platform counts.
  - Fetches the 7 most-recent prior *completed* runs for the same query design (by `completed_at DESC`), not a calendar window, so scheduling gaps do not distort the baseline.
  - Computes the per-arena/platform mean across those 7 runs.
  - Flags arenas where `current_count > 2.0 * rolling_avg` AND `current_count >= 10` (minimum absolute guard).
  - For each spiking arena, fetches the top-3 matched search terms by frequency.
  - Returns an empty list (no alert) when fewer than 7 prior runs exist — insufficient history logged at INFO, never raises.

- `store_volume_spikes()`: persists spike data to `collection_runs.arenas_config["_volume_spikes"]` via `jsonb_set` with `create_missing=true`. Uses the underscore prefix `"_volume_spikes"` to distinguish from real arena name keys. No DB migration required.

- `fetch_recent_volume_spikes()`: reads `arenas_config->'_volume_spikes'` across completed runs within the configured window (default 30 days).

- **Celery task** `check_volume_spikes_task` (`issue_observatory.workers.tasks.check_volume_spikes`):
  - Dispatched by `settle_pending_credits` once per completed run that has a `query_design_id` (deduped by `spike_checked_runs` set).
  - Runs fire-and-forget — failure does not block collection or settlement.
  - Pattern: `asyncio.run(run_spike_detection(...))`.

- **Hook point**: `settle_pending_credits` now carries `query_design_id` in the row dict (via `CollectionRun.query_design_id` added to `fetch_unsettled_reservations` SELECT) and dispatches `check_volume_spikes` alongside the completion email for each newly-settled run.

- **API endpoint** `GET /query-designs/{design_id}/alerts?days=30`:
  - Enforces ownership (owner or admin).
  - Returns list of alert dicts ordered by `completed_at` descending.
  - Each dict: `{run_id, completed_at, volume_spikes: [{arena_name, platform, current_count, rolling_7d_average, ratio, top_terms}]}`.
  - Returns `[]` when no spikes have been recorded in the window.

- **Email**: uses existing `EmailService._send()` (plain-text, fastapi-mail). Subject: `[Issue Observatory] Volume spike detected in {name}`. Body lists each spiking arena with counts, ratio, top terms, and a dashboard link. Silently no-ops when SMTP is not configured.

- **QA notes**:
  - Unit tests should mock `AsyncSession` and verify the SQL queries in `detect_volume_spikes()`.
  - The rolling-window SQL uses a literal UUID tuple (not a bind-parameter list) to avoid SQLAlchemy/asyncpg type casting issues with `IN (:ids)`. Safe because IDs are UUID strings, not user input.
  - The `_volume_spikes` key in `arenas_config` is reserved and must not collide with arena names (all real arena names use alphanumeric/underscore without leading underscore).

---

## GR-08 — Cross-arena Temporal Propagation Detection (2026-02-19) — Complete

| File | Change |
|------|--------|
| `src/issue_observatory/analysis/enrichments/propagation_detector.py` | New file — `PropagationEnricher(ContentEnricher)` class |
| `src/issue_observatory/core/deduplication.py` | Added `DeduplicationService.run_propagation_analysis()` method and module-level `run_propagation_analysis()` convenience wrapper |
| `src/issue_observatory/analysis/propagation.py` | New file — `get_propagation_flows()` query function |
| `src/issue_observatory/analysis/enrichments/__init__.py` | `PropagationEnricher` exported; module docstring updated |
| `src/issue_observatory/analysis/__init__.py` | `PropagationEnricher` and `get_propagation_flows` exported |

**Implementation details:**

### PropagationEnricher (`propagation_detector.py`)

- `enricher_name = "propagation"`.
- Primary entry point: `enrich_cluster(records: list[dict]) -> dict[str, dict]` — returns a mapping of record id → propagation enrichment payload for every record in a near-duplicate cluster.
- `is_applicable(record)`: returns `True` when `near_duplicate_cluster_id` is non-None.
- `enrich(record)`: raises `EnrichmentError` — propagation is inherently cluster-scoped; callers must use `enrich_cluster()`.
- **Ordering**: records sorted by `published_at` ascending; records with `published_at=None` sorted to the end using a sentinel `datetime.max` value.
- **Origin election**: first record with a non-None `published_at` is the origin; falls back to the first sorted record if all timestamps are absent.
- **Propagation sequence**: lists distinct arenas that appear after the origin, in chronological order of first appearance. Same-arena re-publications are skipped (already-seen arena names tracked in `seen_arenas` set).
- **Lag computation**: `lag_minutes = (rec_dt - origin_dt).total_seconds() / 60.0`, rounded to 2 decimal places. `None` when either timestamp is absent.
- **Payload fields**: `cluster_id`, `origin_arena`, `origin_platform`, `origin_published_at`, `is_origin`, `propagation_sequence`, `total_arenas_reached`, `max_lag_hours`, `computed_at`.
- `_parse_published_at()` helper: coerces datetime objects, ISO 8601 strings, and None values; naive datetimes treated as UTC.

### run_propagation_analysis (`deduplication.py`)

- Added as both a method on `DeduplicationService` and a module-level convenience function.
- Re-runs `find_near_duplicates()` to obtain fresh cluster membership (avoids reliance on a pre-populated `near_duplicate_cluster_id` column).
- Filters clusters by `min_distinct_arenas` (default 2) before enriching — single-arena clusters are skipped.
- Persists enrichment using a raw parameterised `UPDATE content_records SET raw_metadata = jsonb_set(...)` statement; the propagation payload is passed as a bind parameter (`:prop_json`) and cast to `::jsonb` by PostgreSQL — no quoting/injection risk.
- Path `'{enrichments,propagation}'` with `create_missing=true` creates the `enrichments` intermediate key if absent and preserves sibling keys (e.g. `language_detection`).
- Lazy import of `PropagationEnricher` avoids circular dependency at module load time.
- Returns summary dict: `{clusters_found, clusters_analysed, records_enriched}`.
- Callers must commit the session after this method returns.

### get_propagation_flows (`propagation.py`)

- Queries `content_records` for records where `raw_metadata -> 'enrichments' -> 'propagation'` exists, `is_origin = true`, and `total_arenas_reached >= min_arenas_reached`.
- Filters by optional `collection_run_id` and `query_design_id`.
- Orders by `total_arenas_reached DESC, max_lag_hours DESC NULLS LAST`.
- Returns one dict per cluster (origin record) with: `cluster_id`, `record_id`, `arena`, `platform`, `origin_published_at`, `total_arenas_reached`, `max_lag_hours`, `propagation_sequence`, `computed_at`.

**Notes for QA:**
- `run_propagation_analysis()` must be called after `detect_and_mark_near_duplicates()` has been run for the same collection run; it re-uses the SimHash clustering logic internally.
- A session commit must be issued by the caller after `run_propagation_analysis()` returns.
- `get_propagation_flows()` relies on the `idx_content_metadata` GIN index on `raw_metadata` — ensure the migration has run before testing.
- Integration tests should mock `find_near_duplicates()` and verify that the `UPDATE content_records SET raw_metadata = jsonb_set(...)` SQL is executed with a valid JSON payload for each qualifying cluster member.

---

## GR-18 — Similarity Finder API + Actor Directory UI (2026-02-19) — API Routes Complete

### Status: API routes complete. "Discover Similar" panel templates need frontend QA review.

| File | Status |
|------|--------|
| `src/issue_observatory/api/routes/actors.py` | Updated — three new POST routes + three new Pydantic schemas |
| `src/issue_observatory/api/templates/_partials/similarity_platform.html` | Done — HTMX partial, candidate cards with platform badge + Add to Registry |
| `src/issue_observatory/api/templates/_partials/similarity_content.html` | Done — HTMX partial, actor cards with similarity progress bar |
| `src/issue_observatory/api/templates/_partials/similarity_cross_platform.html` | Done — HTMX partial, cross-platform candidates with confidence bar |
| `src/issue_observatory/api/templates/actors/detail.html` | Updated — "Discover Similar" collapsible section with three Alpine.js sub-tabs |

### New API routes

| Route | Method | Description |
|-------|--------|-------------|
| `/actors/{actor_id}/similar/platform` | POST | Platform recommendations via `SimilarityFinder.find_similar_by_platform()` |
| `/actors/{actor_id}/similar/content` | POST | Content-similar actors via `SimilarityFinder.find_similar_by_content()` |
| `/actors/{actor_id}/similar/cross-platform` | POST | Cross-platform name search via `SimilarityFinder.cross_platform_match()` |

### New Pydantic schemas (added to `actors.py`)
- `SimilarPlatformRequest`: `platforms: list[str]`, `max_results: int = 20`
- `SimilarContentRequest`: `max_results: int = 20`, `min_similarity: float = 0.3`
- `SimilarCrossPlatformRequest`: `platforms: list[str]`, `max_results: int = 10`

### Design notes
- All three routes return `list[dict] | HTMLResponse` — JSON by default, HTMX partial when `HX-Request` header is present.
- `SimilarityFinder` is instantiated without a persistent HTTP client per request (`SimilarityFinder()`). The finder creates a fresh `httpx.AsyncClient` per API call internally, matching the factory `get_similarity_finder()` in `similarity_finder.py`.
- No credential pool is passed to the finder; all platform calls fall back to public/unauthenticated endpoints (Bluesky public API, Reddit JSON API). YouTube similarity is a no-op without an `api_key` credential in the pool.
- `similar_by_content` enriches results with `canonical_name` via a single bulk `SELECT id, canonical_name FROM actors WHERE id IN (...)` query.
- `similar_cross_platform` sorts by `confidence_score` descending before applying the `max_results` cap.
- All routes enforce read access via `_check_actor_readable()` and return HTTP 404 via `_get_actor_or_404()`.
- `SimilarityFinder` is imported inside each route handler to avoid circular import risk.

### Frontend QA checklist (needs review)
- [ ] Platform Suggestions tab: verify HTMX POST fires with Alpine `:hx-vals` binding (dynamic JSON from reactive `platformSims` array)
- [ ] Content Similar tab: verify slider `x-model="contentMinSim"` updates `:hx-vals` before POST
- [ ] Cross-Platform tab: verify HTMX POST fires with `crossPlatforms` array binding
- [ ] "Add to Registry" buttons: verify `hx-post="/actors/quick-add"` with `hx-vals` submits `platform` + `platform_username` + `display_name` as JSON
- [ ] Loading spinners (`htmx-indicator`) appear during each fetch
- [ ] Empty state messages render correctly when no candidates are returned
- [ ] Progress bars render at boundary values (0%, 100%)

---

## GR-10 — URL Scraper Arena (2026-02-19) — Complete, Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/arenas/web/url_scraper/__init__.py` | Done |
| `src/issue_observatory/arenas/web/url_scraper/config.py` | Done — tier configs, domain delay constants, health check URL |
| `src/issue_observatory/arenas/web/url_scraper/collector.py` | Done — UrlScraperCollector with collect_by_terms, collect_by_actors, normalize, health_check |
| `src/issue_observatory/arenas/web/url_scraper/router.py` | Done — standalone FastAPI router, 3 endpoints |
| `src/issue_observatory/arenas/web/url_scraper/tasks.py` | Done — 3 Celery tasks (collect_terms, collect_actors, health_check) |
| `src/issue_observatory/arenas/web/url_scraper/README.md` | Done — setup instructions, API reference, known limitations |
| `src/issue_observatory/arenas/registry.py` | Updated — added `url_scraper` entry to ARENA_DESCRIPTIONS |

### Implementation notes

- **Collection mode**: Batch-only (no Celery Beat schedule — URL list is static per query design).
- **Reuse**: 100% of HTTP fetching (`fetch_url`) and content extraction (`extract_from_html`) delegated to existing `src/issue_observatory/scraper/` module.  No re-implementation.
- **Rate limiting**: Per-domain `asyncio.Semaphore(1)` dictionary; `asyncio.gather()` across domains for parallel throughput.  FREE: 1.0s delay; MEDIUM: 0.5s delay between same-domain requests.
- **robots.txt**: Single `robots_cache: dict[str, bool]` created per collection run and passed to all `fetch_url()` calls.  Existing `_is_allowed_by_robots()` in `http_fetcher.py` handles caching by origin.
- **Playwright**: Lazily imported at MEDIUM tier when `needs_playwright=True`.  `ImportError` caught gracefully — falls back to httpx-only with a warning.
- **Error isolation**: Each URL is wrapped in try/except; failures return a `_fetch_failed=True` record that is excluded from term-matched results but logged.
- **URL normalization**: `_normalize_url()` strips tracking params (UTM, fbclid, gclid) and trailing slashes before deduplication.
- **UCR normalization**: `platform_id=sha256(final_url)`, `author_platform_id=domain`, `language=None` (enrichment pipeline handles detection), `content_type="web_page"`.
- **published_at** resolution order: (1) trafilatura metadata date, (2) HTTP Last-Modified header, (3) `datetime.now(UTC)` fallback.
- **Registry**: `@register` decorator on `UrlScraperCollector`; `autodiscover()` imports the collector module on startup.

### Known gaps (for QA review)

- `FetchResult` from `http_fetcher.py` does not expose response headers (e.g. `Last-Modified`).  The `last_modified_header` key is always `None` in the raw record; only trafilatura date and `collected_at` fallback are used.  To fix: modify `FetchResult` to include a `headers` field — requires DB Engineer sign-off since it touches shared infrastructure.
- The `normalize()` method (single-arg public interface required by `ArenaCollector`) delegates to `_normalize_raw_record()` with `Tier.FREE`.  Callers within the collector always use `_normalize_raw_record()` directly with the correct tier.
- No `date_from` / `date_to` filtering is applied — the URL Scraper fetches live page content regardless of date. The parameters are accepted for API consistency but ignored.

### QA checklist

- [ ] `UrlScraperCollector` registered in arena registry after `autodiscover()`
- [ ] `collect_by_terms()` returns empty list when `extra_urls` is `None`
- [ ] `collect_by_terms()` applies term filtering correctly (case-insensitive)
- [ ] `collect_by_terms()` respects `max_results` cap
- [ ] `collect_by_actors()` domain-prefix matching against `custom_urls`
- [ ] `collect_by_actors()` falls back to actor base URL when no `custom_urls` match
- [ ] Per-URL error isolation: one 404 does not abort remaining URLs
- [ ] robots.txt disallowed URL produces failure record with `robots_txt_allowed=False`
- [ ] MEDIUM tier Playwright path: import error handled gracefully
- [ ] `health_check()` returns `{"status": "ok", "trafilatura": "available"}`
- [ ] URL deduplication: duplicate and near-duplicate URLs (UTM variants) deduplicated
- [ ] `platform_id` is deterministic for same URL
- [ ] `content_hash` differs for pages with different text content

---

## YF-01 — Per-Arena Search Term Scoping (2026-02-19) — Complete, Ready for QA

| File | Status |
|------|--------|
| `src/issue_observatory/workers/_task_helpers.py` | Done — added `fetch_search_terms_for_arena()` async helper (lines 368-418) |
| `src/issue_observatory/workers/tasks.py` | Done — modified `trigger_daily_collection()` to load and filter terms per arena (lines 216-286) |
| `docs/status/YF-01_implementation_summary.md` | Updated — added Core Application Layer section |

### Implementation notes

- **Database layer**: Already complete (migration 010, `target_arenas` JSONB field on `search_terms`, Pydantic schemas updated)
- **Filtering logic**: Centralized in `fetch_search_terms_for_arena()` helper function
- **SQL query**: Uses PostgreSQL JSONB `?` operator (`has_key()` in SQLAlchemy) to check if platform_name exists in array
- **Backward compatibility**: All existing terms have `target_arenas = NULL`, which means "all arenas" (pre-YF-01 behavior)
- **Error handling**: Term loading errors are non-fatal — arena is skipped with error log, remaining arenas continue
- **Empty term lists**: When no terms are scoped to an arena, it is skipped with info-level log (not an error)
- **Task parameters**: Now passing `query_design_id` and `terms` to all arena tasks (was missing before)

### Filtering logic

```python
# SQL (via SQLAlchemy):
SELECT term FROM search_terms
WHERE query_design_id = :design_id
  AND is_active = TRUE
  AND (
    target_arenas IS NULL           -- applies to all arenas
    OR target_arenas ? :platform_name  -- JSONB ? operator
  )
ORDER BY added_at
```

### Functional scenarios

| Scenario | `target_arenas` value | Result |
|----------|----------------------|--------|
| All arenas (backward-compatible) | `NULL` | Term dispatched to all enabled arenas |
| Reddit only | `["reddit"]` | Term dispatched to Reddit only |
| Reddit and Bluesky | `["reddit", "bluesky"]` | Term dispatched to both |
| Empty list | `[]` | Term excluded from all arenas |
| No matching arenas | `["twitter"]` (no match) | Arena skipped with info log |

### QA checklist

- [ ] `fetch_search_terms_for_arena()` returns terms with `target_arenas = NULL`
- [ ] `fetch_search_terms_for_arena()` returns terms with matching `platform_name` in array
- [ ] `fetch_search_terms_for_arena()` excludes terms with non-matching `platform_name`
- [ ] `fetch_search_terms_for_arena()` excludes inactive terms (`is_active = False`)
- [ ] `fetch_search_terms_for_arena()` returns empty list when no terms match
- [ ] `trigger_daily_collection()` skips arena when term list is empty (info log)
- [ ] `trigger_daily_collection()` handles term loading errors gracefully (error log, arena skipped)
- [ ] `trigger_daily_collection()` passes `query_design_id` and `terms` to arena tasks
- [ ] `trigger_daily_collection()` logs term count per dispatched arena
- [ ] Integration test: mixed scoped/unscoped terms dispatch correctly to each arena
- [ ] Edge case: `target_arenas = []` excludes term from all arenas
- [ ] Edge case: all terms scoped away from arena results in arena skip (not error)
