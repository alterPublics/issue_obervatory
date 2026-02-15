# The Issue Observatory — Agent Definitions

This project uses five specialized Claude Code agents, each with defined ownership boundaries. Agent definitions live in `.claude/agents/`.

## Agent Summary

| Agent | Prefix | Primary Responsibility | Owned Paths |
|-------|--------|----------------------|-------------|
| **Core Application Engineer** | `core/` | Application backbone: FastAPI, Celery, arena collectors, configuration | `src/issue_observatory/` (except `core/models/`, `analysis/`, `api/templates/`, `api/static/`) |
| **Database & Data Engineer** | `db/` | Schema design, ORM models, migrations, analysis module, query optimization | `src/issue_observatory/core/models/`, `src/issue_observatory/core/database.py`, `alembic/`, `src/issue_observatory/analysis/` |
| **Frontend Engineer** | `frontend/` | Jinja2 templates, HTMX interactions, Alpine.js components, Tailwind CSS, Chart.js | `src/issue_observatory/api/templates/`, `src/issue_observatory/api/static/` |
| **QA Guardian** | `qa/` | Test suite, CI/CD, code review, arena approval checklist | `tests/`, `.pre-commit-config.yaml`, linting/typing config in `pyproject.toml` |
| **Research Strategist** | `research/` | Arena briefs, knowledge base, use case planning, ADRs | `docs/`, `reports/` |

## Coordination Rules

- **Arena implementation requires a research brief first.** The Core Application Engineer is blocked until `/docs/arenas/{platform}.md` exists.
- **Schema changes require DB Engineer approval.** No direct DDL or model modifications without review.
- **QA Guardian has blocking authority** on all merges. Nothing ships without passing the Arena Review Checklist.
- **Frontend Engineer reads route handlers** but does not modify them. Data shape gaps are documented as issues.
- **Research Strategist produces knowledge artifacts, not code.**

## Handoff Protocol

1. Research Strategist produces arena brief → unblocks Core Application Engineer
2. DB Engineer provides models + migration → unblocks Core Application Engineer
3. Core Application Engineer implements collector + routes → unblocks Frontend Engineer (templates) and QA Guardian (review)
4. QA Guardian approves or blocks with specific, actionable feedback

## Decision Authority

| Decision Type | Who Decides |
|--------------|-------------|
| What platforms to collect from | Research Strategist |
| Schema design, indexes, migrations | DB & Data Engineer |
| Code architecture, API patterns, task design | Core Application Engineer |
| Template structure, HTMX patterns, styling | Frontend Engineer |
| Test strategy, coverage thresholds, CI config | QA Guardian |
| New dependencies, base class interface changes | Team (propose → discuss → decide) |
