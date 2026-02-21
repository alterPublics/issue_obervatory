# Pre-Production Beta Checklist

**Created:** 2026-02-21
**Purpose:** Checklist of required checks, tests, and reviews before deploying the Issue Observatory in beta test mode.
**Status:** Pending

---

## P0 — Must-Do Before Beta

### 1. Run the Full Test Suite

- [x] Execute `pytest --tb=short -q` and achieve a fully green run
- [x] All 1760 tests pass with zero failures (1 skipped)
- [x] No failures to fix — suite is clean

**Rationale:** The QA verification on 2026-02-21 confirmed test file counts and component coverage but did not execute the suite. A clean run is the minimum bar for beta.

---

### 2. Resolve Coherency Audit Critical Findings

Two independent coherency audits were produced on 2026-02-21:
- `/docs/research_reports/coherency_audit_2026_02_21.md` (6 critical, 11 moderate)
- `/docs/research_reports/qa_coherency_audit_2026_02_21.md` (7 critical, 10 moderate)

- [ ] Review all critical findings from both audits
- [ ] Triage each as beta-blocking or acceptable known limitation
- [ ] Fix all beta-blocking items
- [ ] Document accepted limitations in beta release notes

**Known critical example:** The enrichment pipeline has no automatic post-collection trigger — enrichments exist but must be invoked manually.

---

### 3. Full-Stack Docker Compose Smoke Test

Boot the entire stack from scratch on a clean environment:

- [ ] `docker-compose up -d postgres redis` starts cleanly
- [ ] `alembic upgrade head` applies all 15 migrations on a fresh database without errors
- [ ] `python scripts/bootstrap_admin.py` creates a working admin user
- [ ] `uvicorn issue_observatory.api.main:app` starts without errors
- [ ] Celery worker starts and connects to Redis
- [ ] Celery beat starts and registers scheduled tasks
- [ ] Admin login succeeds and dashboard renders

---

### 4. End-to-End Collection Workflow

Test the critical researcher workflow against at least 2-3 FREE-tier arenas (Bluesky, RSS Feeds, GDELT):

- [ ] Create a new query design with search terms
- [ ] Configure arena-specific settings (e.g., custom RSS feeds)
- [ ] Launch a collection run
- [ ] Verify SSE live monitoring updates in real time
- [ ] Confirm collected content appears in the content browser
- [ ] Open a content record detail panel and verify fields are populated
- [ ] Export results as CSV
- [ ] Export results as XLSX
- [ ] Run enrichments on the collected data
- [ ] Verify enrichment results appear in the enrichments dashboard tab

---

### 5. Secrets and Configuration Audit

- [ ] `.env.example` documents all required environment variables
- [ ] `PSEUDONYMIZATION_SALT` is enforced as required (not optional) — GDPR dependency
- [ ] `JWT_SECRET_KEY` is required at startup with a clear error if missing
- [ ] `DATABASE_URL` and `REDIS_URL` are validated on startup
- [ ] No API keys, secrets, or credentials are committed to the repository
- [ ] Run `git log --all --diff-filter=A -- '*.env' '*.key' '*.pem' '*secret*' '*credential*'` to verify no secrets in git history
- [ ] Credential pool Fernet encryption key is documented in `.env.example`

---

## P1 — Strongly Recommended

### 6. Security Review

**Authentication and authorization:**
- [ ] Login flow works correctly (valid credentials accepted, invalid rejected)
- [ ] Logout invalidates the session/token
- [ ] Session expiry works as configured
- [ ] Password reset flow works end-to-end
- [ ] All API routes require authentication (no unprotected endpoints serving data)
- [ ] Admin-only routes (`/admin/*`) reject non-admin users

**Input handling:**
- [ ] Query design name/description fields sanitized against XSS
- [ ] Search term input sanitized against injection
- [ ] Actor name fields sanitized
- [ ] URL fields validated before processing
- [ ] HTMX requests carry proper CSRF tokens

**Data protection:**
- [ ] Credential pool entries are Fernet-encrypted at rest in PostgreSQL
- [ ] API keys are never logged in plaintext (check structlog output)
- [ ] `raw_metadata` JSONB does not leak un-pseudonymized PII for non-public-figure actors

---

### 7. Migration Rollback Testing

- [ ] `alembic downgrade -1` works from head (migration 015)
- [ ] `alembic downgrade -1` works from migration 014
- [ ] Verify downgrade path for migrations 010-013 (recent additions)
- [ ] Full `alembic downgrade base` then `alembic upgrade head` round-trip succeeds
- [ ] No data loss occurs during downgrade/upgrade cycle on a test database with sample data

---

### 8. GDPR Compliance Validation

- [ ] Collect content from a live arena and verify `pseudonymized_author_id` is a SHA-256 hash (not a plaintext name)
- [ ] Set an actor as `public_figure=True` and verify their name is preserved (bypass works)
- [ ] Test data subject deletion via `retention_service.py` — confirm all content records for a given author are purged
- [ ] Verify `raw_metadata` does not contain un-pseudonymized author identifiers for non-public-figure actors
- [ ] Confirm retention policy configuration is documented and functional
- [ ] Verify audit trail exists in `raw_metadata` for public figure bypass decisions

---

### 9. Error Handling Under Failure

**Arena API failures:**
- [ ] Simulate an arena API being unavailable (e.g., wrong API key) — verify graceful error, no crash
- [ ] Verify collection run status updates to reflect the failure
- [ ] Confirm other arenas in a multi-arena collection continue despite one arena failing

**Infrastructure failures:**
- [ ] Stop Redis while a collection is running — verify the application doesn't crash
- [ ] Verify rate limiter, event bus, and credential pool degrade gracefully without Redis
- [ ] Restart Redis and confirm the application recovers

**Collection interruption:**
- [ ] Suspend a running collection and verify it can be resumed
- [ ] Kill a Celery worker mid-collection and verify the run can be restarted
- [ ] Verify Celery task retry behavior for transient API failures (exponential backoff)

---

### 10. Performance Baseline

Establish baseline performance metrics with realistic data volumes:

- [ ] Load 10,000-50,000 content records into the database
- [ ] Content browser pagination responds in under 2 seconds
- [ ] Content browser text search responds in under 5 seconds
- [ ] Analysis descriptive statistics query completes in under 10 seconds
- [ ] Network analysis (actor co-occurrence) completes in under 30 seconds for 10k records
- [ ] CSV export of 10,000 records completes without timeout
- [ ] XLSX export of 10,000 records completes without timeout
- [ ] Sigma.js network visualization renders graphs with up to 500 nodes smoothly
- [ ] SSE live monitoring does not drop connections during a 10-minute collection run
- [ ] Content records partitioning (monthly) is confirmed working

---

## P2 — Recommended for Beta Quality

### 11. UX Researcher Walkthrough

Have someone unfamiliar with the codebase attempt key workflows using only the UI:

- [ ] First-time setup: Can they log in and orient themselves on the dashboard?
- [ ] Query design creation: Is the editor discoverable and understandable?
- [ ] Arena selection: Can they understand tier selection and arena configuration?
- [ ] Collection launch: Is the process clear? Are warnings (date range, credit estimation) helpful?
- [ ] Results review: Can they find and browse collected content?
- [ ] Export: Can they export data in their preferred format without confusion?
- [ ] Error messages: When something goes wrong, are messages helpful and actionable?
- [ ] Document friction points and prioritize fixes

**Alternative:** Run the `ux-tester` agent with scenario scripts from `/docs/ux_reports/`.

---

### 12. Monitoring and Observability

- [ ] Structlog is configured and producing structured JSON logs in production mode
- [ ] Logs include sufficient context for debugging (collection run IDs, arena names, error details)
- [ ] API keys and secrets are redacted in log output
- [ ] Health endpoint (`/health`) checks PostgreSQL connectivity
- [ ] Health endpoint checks Redis connectivity
- [ ] Health endpoint checks Celery worker availability
- [ ] Consider adding alerting for failed collection runs (email or webhook)
- [ ] Consider adding log aggregation (e.g., stdout JSON for Docker log drivers)

---

### 13. Backup and Recovery

- [ ] Document PostgreSQL backup procedure (pg_dump with partitioned tables)
- [ ] Test backup/restore round-trip on a database with content records spanning multiple monthly partitions
- [ ] Verify `content_records` partitions are included in backups
- [ ] Test recovery scenario: restore from backup, verify data integrity
- [ ] Document Redis persistence configuration (if any state needs to survive restarts)
- [ ] Document recovery procedure for interrupted collection runs after a system restart

---

### 14. Rate Limit and Credit System Validation

- [ ] Verify rate limiter actually throttles requests (not just tracking) — send requests exceeding the limit and confirm they are delayed/rejected
- [ ] Test credit reservation → settlement → refund cycle end-to-end
- [ ] Compare credit estimation output against actual usage for at least 2-3 arenas
- [ ] Verify credit balance cannot go negative
- [ ] Confirm credit allocation admin UI works correctly

---

### 15. Browser Compatibility

- [ ] Test in Chrome (latest): dashboard, query editor, collection monitoring, content browser, analysis, export
- [ ] Test in Firefox (latest): same pages
- [ ] Test in Safari (latest): same pages
- [ ] Verify SSE live collection monitoring works across all three browsers
- [ ] Verify Sigma.js network visualization renders correctly in all three browsers
- [ ] Verify Alpine.js interactive components (arena grid, modals, slide-in panels) work in all three browsers
- [ ] Check for console errors in browser developer tools

---

## Sign-Off

| Check | Completed | Date | Notes |
|-------|-----------|------|-------|
| P0-1: Test suite green | YES | 2026-02-21 | 1790 passed, 1 skipped, 0 failures (49.73s). Coverage: 51%. |
| P0-2: Coherency audit triage | RESOLVED | 2026-02-21 | All 4 blockers fixed: BB-1 enrichment button added, BB-2 spike alerts on dashboard, BB-3 SMTP status on health page, BB-4 30 retention service tests written. |
| P0-3: Docker smoke test | PASSED (with fix) | 2026-02-21 | Found & fixed migration 015 bug: unique index on partitioned table must include partition key. All 15 migrations now apply cleanly. Admin bootstrap works. |
| P0-4: E2E collection workflow | DEFERRED | 2026-02-21 | Requires API keys for FREE-tier arenas. Test manually in deployment environment with credentials configured. |
| P0-5: Secrets audit | RESOLVED | 2026-02-21 | All 3 blockers fixed: BB-01 salt now raises on empty, BB-02 weak SECRET_KEY rejected at startup, BB-03 Fernet key validated at startup. |
| P1-6: Security review | | | |
| P1-7: Migration rollback | | | |
| P1-8: GDPR validation | | | |
| P1-9: Error handling | | | |
| P1-10: Performance baseline | | | |
| P2-11: UX walkthrough | | | |
| P2-12: Monitoring | | | |
| P2-13: Backup/recovery | | | |
| P2-14: Rate limits/credits | | | |
| P2-15: Browser compatibility | | | |

**Beta deployment approved by:** _______________
**Date:** _______________
