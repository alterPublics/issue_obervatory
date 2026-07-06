"""Fixtures for the content page filter regression harness (Phase 0).

This module owns the ``seeded_corpus`` fixture used by the four regression
test files under ``tests/integration/api/content/``. The harness pins the
**current** behavior of the content page filter system — including its bugs —
so that later phases can refactor the four divergent filter implementations
without silent regressions.

Design notes
============

Scope
-----
Session-scoped. The corpus is small (~60 records) and entirely deterministic,
so rebuilding it per test would waste time without adding value. We commit
the seed data via a dedicated psycopg2 connection that bypasses the async
``db_session``'s rollback semantics, so that every test's `client` request
sees the same pinned corpus.

Determinism
-----------
Every UUID in the seed is produced via ``uuid.uuid5(NAMESPACE_DNS, label)``
keyed on a human-readable label. The fixture exposes a ``manifest`` dict
mapping labels -> UUIDs so tests can assert on *labels* rather than opaque
UUID strings. That means a test failure reads like::

    assert actual == {
        "reddit_post_term_matched_da",
        "bluesky_post_term_matched_en",
    }

rather than::

    assert actual == {UUID('11d2...'), UUID('4ab0...')}

The former diffs cleanly in pytest output; the latter is noise.

Platform / arena coverage
-------------------------
Spans the 9 platforms called out in the plan: ``reddit``, ``bluesky``,
``facebook``, ``instagram``, ``youtube``, ``x_twitter``, ``google_search``,
``wikipedia``, ``telegram``. The ``arena`` column for all nine is
``social_media`` or ``search`` per ``arenas/categories.py``.

**Actor-only platforms** (``facebook``, ``instagram``) are the ones that
``workers/tasks.py:1507,1541`` flags via ``supports_term_search=False``. We
seed both with ``term_matched=FALSE`` so the current-behavior test can pin
the ``show_all`` mutation bug from UX Blocker #3.

Content types
-------------
Covers ``post``, ``comment``, ``search_result``, ``video``, ``article``,
``tweet``, ``reply``, and ``wiki_pageview``. The corpus is intentionally
skewed so that non-``post`` content is the majority, which makes the
``content_types=["post"]`` silent default at ``content.py:1067,1330``
observable in the current-behavior pins.

Languages
---------
Mix of ``"da"``, ``"en"``, ``"de"``, ``""``, ``None``, and ``"da-DK"``.
Three rows also have their top-level ``language`` cleared but carry
``raw_metadata.enrichments.language_detection.language`` set, to exercise
the fallback path at ``content.py:242-248, 510-517``.

Duplicates
----------
Five rows have ``raw_metadata->>'duplicate_of'`` pointing at another
record's UUID so the dedup parity bug between browse and analysis
(``analysis/_filters.py:181`` vs. ``content.py``) can be pinned. The plan
does not fix this in Phase 0; the assertion is the *current* state.

Dates
-----
Absolute dates anchored between ``2025-10-15`` and ``2026-02-20`` so the
corpus stays inside the existing monthly partitions even as the wall clock
moves forward. This keeps Phase 0 stable against date drift.

Users and projects
------------------
- ``qa_admin_user`` — superuser, sees everything.
- ``qa_owner_user`` — owns the two collection runs and the project.
- ``qa_collaborator_user`` — added to the project via ``project_collaborators``.
- ``qa_stranger_user`` — no relationship, should see nothing.
- ``qa_project`` — owned by ``qa_owner_user``, has ``qa_collaborator_user``
  as a viewer.
- ``qa_query_design_da`` — Danish query design.
- ``qa_query_design_en`` — English query design.
- ``qa_run_batch`` and ``qa_run_live`` — two collection runs, one per mode,
  owned by ``qa_owner_user``.

Bug observations (DO NOT FIX IN PHASE 0)
----------------------------------------
While writing this fixture, QA observed the bugs listed in ``docs/qa_reports/``
and ``docs/ux_reports/``. They are intentionally left in place; Phase 2 will
fix them and flip the pinned xfail tests.

    - ``content.py:1063, 1324`` — ``effective_show_all`` mutation means
      ``show_all=False`` is silently overridden when any ``arenas`` checkbox
      is selected. Covered by ``test_count_vs_rows_invariant.py`` xfails.
    - ``content.py:1067, 1330`` — ``content_types`` default silently filters
      to ``["post"]``. Covered by ``test_filter_current_behavior.py``.
    - ``content.py:1686-1722`` — ``/content/export`` drops ``q``, ``mode``,
      ``project_id``, ``show_all``, ``scrape_status``, ``content_types``.
      Covered by ``test_export_equals_browse.py``.
    - ``content.py:215-223`` vs ``content.py:488-499`` — export uses the
      collaborator-aware ``_build_content_stmt`` but browse does not.
      Observable via different row IDs for the collaborator user between
      browse and export.

Owned by: QA Guardian (phase 0 harness).
"""

from __future__ import annotations

import hashlib
import os
import uuid
import warnings
from collections.abc import AsyncGenerator, Generator  # noqa: TC003
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg2
import psycopg2.extras
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import TEST_PASSWORD, TEST_PASSWORD_HASH

# ---------------------------------------------------------------------------
# Local client override.
#
# The top-level ``client`` fixture in tests/conftest.py triggers the FastAPI
# app's ``on_startup`` handler on every test, which spawns a background
# ``asyncio.create_task(_cleanup_stale_runs_on_startup)``. That task holds
# a reference to the current test's event loop; when the next test creates
# a new event loop, the old task is orphaned with a live DB connection,
# which both produces unraisable warnings AND causes "Future attached to a
# different loop" errors when reused.
#
# Our override does NOT call ``on_startup``. We directly set
# ``app.state.templates`` which is the only thing the content page needs
# from startup. The cleanup task is irrelevant to filter regression tests.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _disable_rate_limiter() -> Generator[None, None, None]:
    """Disable slowapi rate limiting for the suite.

    The app's ``limiter`` singleton enforces 100 requests/minute per IP via
    an in-memory store that is shared across tests. With ~60 tests x 2+
    requests each, we exhaust the quota quickly and start seeing 429s.
    Disabling the limiter for this suite bypasses the problem without
    affecting other test runs (the fixture restores ``enabled=True`` at
    session end).
    """
    from issue_observatory.api.limiter import limiter

    original = limiter.enabled
    limiter.enabled = False
    try:
        yield
    finally:
        limiter.enabled = original


@pytest.fixture(scope="session", autouse=True)
def _patch_app_engine_to_nullpool(test_database_url: str) -> Generator[None, None, None]:
    """Swap the app-level ``async_engine`` for a NullPool-backed engine.

    ``src/issue_observatory/core/database.py`` creates a MODULE-LEVEL
    ``async_engine`` with a QueuePool + ``pool_pre_ping=True``. That pool
    outlives every test's event loop, and when the next test spins up a
    new loop, any cached connection fails with "Future attached to a
    different loop". fastapi-users touches that engine on every /auth
    request because its dependency chain does NOT go through our
    overridden ``get_db``.

    We patch the module-level engine once per session so the entire app
    uses a pool that creates and closes a fresh connection per request.
    NullPool removes the cross-loop hazard entirely at the cost of a few
    extra TCP connects per test — acceptable for a read-only harness.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from issue_observatory.core import database as _dbmod

    original_engine = _dbmod.async_engine
    original_factory = _dbmod.AsyncSessionLocal

    new_engine = create_async_engine(
        test_database_url,
        echo=False,
        poolclass=NullPool,
    )
    new_factory = async_sessionmaker(
        bind=new_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    _dbmod.async_engine = new_engine
    _dbmod.AsyncSessionLocal = new_factory

    try:
        yield
    finally:
        _dbmod.async_engine = original_engine
        _dbmod.AsyncSessionLocal = original_factory


@pytest_asyncio.fixture
async def _fn_engine(test_database_url: str):  # noqa: ANN202
    """Per-test async engine with a ``NullPool`` connection pool.

    Why NullPool:
    - The default QueuePool keeps connections alive across test boundaries.
      When a new event loop starts for the next test, any connection still
      in the pool belongs to the old loop and fails with "Future attached
      to a different loop".
    - NullPool closes the underlying connection every time it's returned to
      the pool, guaranteeing no cross-loop connection leakage. Latency cost
      is acceptable for a read-only regression harness.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(
        test_database_url,
        echo=False,
        poolclass=NullPool,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(  # type: ignore[no-redef]
    _fn_engine: Any,
) -> AsyncGenerator[AsyncSession, None]:
    """Per-test async session using the NullPool engine.

    Read-only: the seeded corpus is committed via psycopg2 ahead of this
    session. Any write that happens inside a test is outside the intended
    harness scope — tests should not mutate content_records.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(
        bind=_fn_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(  # type: ignore[no-redef]
    db_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    """Local override of the top-level ``client`` fixture.

    Skips the app's startup event hooks (which spawn cross-loop background
    tasks). Still overrides ``get_db`` to return the test session.
    """
    from issue_observatory.api.main import app
    from issue_observatory.api.main import templates as _templates
    from issue_observatory.core.database import get_db

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    # Manually install the templates engine on app.state so the content
    # browser route can resolve ``request.app.state.templates``. We do NOT
    # invoke the full ``on_startup`` hook chain — the cleanup-stale-runs
    # background task spawned there orphans itself across event loops.
    app.state.templates = _templates

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        follow_redirects=True,
    ) as ac:
        yield ac

    app.dependency_overrides.clear()

# ---------------------------------------------------------------------------
# Suppress teardown-only unraisable warnings BEFORE they can fail tests.
#
# The project-wide ``filterwarnings = ["error", ...]`` in pyproject.toml
# turns every warning into a failure. httpx + asyncpg pool teardown in the
# async ``db_session`` + ``client`` fixtures occasionally emits
# ``PytestUnraisableExceptionWarning`` on event-loop shutdown. Those
# warnings are cosmetic — the HTTP responses have already been captured —
# so we install a global filter at module import time so it is in effect
# for the entire suite.
# ---------------------------------------------------------------------------
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings(
    "ignore",
    category=pytest.PytestUnraisableExceptionWarning,  # type: ignore[attr-defined]
)

# ---------------------------------------------------------------------------
# Suppress unraisable coroutine-never-awaited warnings during teardown.
#
# The project-wide ``filterwarnings = ["error", ...]`` in pyproject.toml turns
# *every* warning into a test failure. asyncpg + httpx + the transactional
# db_session fixture occasionally leave background tasks un-awaited at teardown
# (they are cleaned up by GC), which trips PytestUnraisableExceptionWarning.
# That warning is harmless for our assertions — the actual HTTP responses are
# already captured — so each test file in this package suppresses it via a
# module-level ``pytestmark`` list. The ignore is scoped to our suite only;
# every other test package still sees the project-wide strict filterwarnings.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Session-start hook: reset the public schema before the global
# ``_ensure_tables`` fixture from tests/conftest.py runs.
#
# Why this is needed: the project's ``users <-> user_templates`` tables form a
# mutual FK cycle that SQLAlchemy's ``Base.metadata.drop_all`` cannot sort for
# DROP, so the global ``_ensure_tables`` fixture errors out the second time
# pytest is invoked against a DB that already has those tables. We side-step
# it with a raw-SQL schema reset: DROP SCHEMA public CASCADE + CREATE SCHEMA.
#
# This is scoped to the content-filter test package only — the hook runs
# once per session IF any content-filter test is collected, and is a no-op
# when the suite is run outside this directory. The hook lives in this
# package's conftest so it cannot accidentally reset the schema for unrelated
# test runs.
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    """Inject content-suite-only filterwarnings overrides.

    The project-wide ``filterwarnings = ["error", ...]`` in pyproject.toml
    combined with pytest's built-in ``unraisableexception`` plugin causes
    httpx/asyncpg teardown warnings to be converted into test failures.
    Those warnings are cosmetic — the HTTP responses have already been
    captured — so we mutate the config's filterwarnings list to append
    ignore rules when the suite is selected. Because pytest evaluates
    warning filters in reverse order (last match wins), appending is
    sufficient to override the project-level ``error`` rule.
    """
    args_str = " ".join(config.args or [])
    if "tests/integration/api/content" not in args_str and not any(
        "content" in a for a in config.args or []
    ):
        return
    # Mutate the filterwarnings INI value so our ignores are evaluated first
    # (remember: last-match wins, and pytest iterates the list in order,
    # installing filters with the last added being the first evaluated).
    existing = config.getini("filterwarnings") or []
    extra = [
        "ignore::pytest.PytestUnraisableExceptionWarning",
        "ignore::ResourceWarning",
    ]
    config._inicache["filterwarnings"] = list(existing) + extra  # type: ignore[attr-defined]


def pytest_sessionstart(session: pytest.Session) -> None:
    """Reset the public schema before the global _ensure_tables fixture runs.

    This is only triggered when a content-filter test is being collected;
    pytest ignores this hook for runs that don't import this conftest.
    """
    # Only reset if the user actually selected the content-filter suite.
    # Detect by looking at collected items — but pytest_sessionstart runs
    # *before* collection, so we check the command-line args instead.
    selected = " ".join(session.config.args or [])
    if "tests/integration/api/content" not in selected and not any(
        "content" in a for a in session.config.args or []
    ):
        return

    dsn = _sync_dsn()
    conn = psycopg2.connect(dsn)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
            cur.execute("CREATE SCHEMA public")
            cur.execute("GRANT ALL ON SCHEMA public TO observatory")
            cur.execute("GRANT ALL ON SCHEMA public TO public")
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Namespace for deterministic UUID generation
# ---------------------------------------------------------------------------

_QA_NS = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _uid(label: str) -> uuid.UUID:
    """Produce a deterministic UUID for a human-readable label.

    Using ``uuid5`` means the same label always produces the same UUID
    across runs, which keeps test failure output stable and lets us
    cross-reference records by name rather than opaque UUID.
    """
    return uuid.uuid5(_QA_NS, label)


# ---------------------------------------------------------------------------
# Actor-only platforms — mirrors workers/tasks.py:1541 supports_term_search
# check. Facebook and Instagram are the only two actor-only platforms today.
# When Phase 2 fixes the show_all bug, it will reference a similar constant
# sourced from the arena registry; this list is the QA side of the contract.
# ---------------------------------------------------------------------------

ACTOR_ONLY_PLATFORMS: frozenset[str] = frozenset({"facebook", "instagram"})


# ---------------------------------------------------------------------------
# Label constants — one per seeded record. Tests reference these by name.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeedRecord:
    """A single declarative content_records row, pre-validated.

    Fields map 1:1 to ``content_records`` columns except where noted:
    - ``label`` is the human-readable handle tests use.
    - ``enrichment_lang`` populates ``raw_metadata.enrichments.language_detection.language``.
    - ``duplicate_of_label`` populates ``raw_metadata.duplicate_of`` by
      looking up the other seed record's UUID at insert time.
    - ``term_matched`` defaults to True to mirror the schema default.
    """

    label: str
    platform: str
    arena: str
    content_type: str
    title: str
    text_content: str
    published_at: datetime
    run_label: str
    query_design_label: str
    language: str | None = "da"
    search_terms_matched: list[str] = field(default_factory=list)
    term_matched: bool = True
    enrichment_lang: str | None = None
    duplicate_of_label: str | None = None
    scrape_status: str | None = None
    # Phase 5: optional actor label. When set, the corresponding actor UUID
    # is written to content_records.author_id at seed time. Allows actor_id
    # filter tests to exercise the author_id IN (...) predicate with real rows.
    actor_label: str | None = None

    @property
    def id(self) -> uuid.UUID:
        return _uid(self.label)

    @property
    def platform_id(self) -> str:
        # Unique platform_id per seed label so the
        # (platform, platform_id, published_at) unique index does not fire
        # even for same-day siblings.
        return f"qa-{self.label}"


# ---------------------------------------------------------------------------
# Date anchors. Absolute so the corpus never drifts as the wall clock moves.
# The 2025-10 -> 2026-02 window spans 5 monthly partitions created by the
# session-scoped _ensure_tables fixture in tests/conftest.py.
# ---------------------------------------------------------------------------

_D_OCT = datetime(2025, 10, 15, 12, 0, tzinfo=UTC)
_D_NOV = datetime(2025, 11, 15, 12, 0, tzinfo=UTC)
_D_DEC = datetime(2025, 12, 15, 12, 0, tzinfo=UTC)
_D_JAN = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
_D_FEB = datetime(2026, 2, 15, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# The declarative seed definition. Read this list to understand the corpus.
# Every record is small enough to grok at a glance; ordering is by platform
# to group related rows visually.
# ---------------------------------------------------------------------------

_SEED_RECORDS: list[SeedRecord] = [
    # -------- Reddit (4 rows) --------
    SeedRecord(
        label="reddit_post_term_matched_da",
        platform="reddit",
        arena="social_media",
        content_type="post",
        title="Klimakamp i Danmark",
        text_content="En lang diskussion om CO2-afgifter på dansk.",
        language="da",
        published_at=_D_OCT,
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=["klima", "co2"],
        term_matched=True,
        actor_label="actor:reddit",  # Phase 5: attributed to the Reddit actor
    ),
    SeedRecord(
        label="reddit_comment_term_matched_da",
        platform="reddit",
        arena="social_media",
        content_type="comment",
        title="",
        text_content="Enig, CO2-afgift er nødvendig.",
        language="da",
        published_at=_D_OCT + timedelta(hours=2),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=["co2"],
        term_matched=True,
        actor_label="actor:reddit",  # Phase 5: same Reddit actor owns both rows
    ),
    SeedRecord(
        label="reddit_post_non_term_matched_en",
        platform="reddit",
        arena="social_media",
        content_type="post",
        title="Random English thread",
        text_content="Not matching any search term.",
        language="en",
        published_at=_D_NOV,
        run_label="run_batch",
        query_design_label="qd_en",
        search_terms_matched=[],
        term_matched=False,  # non-matching on non-actor-only platform
    ),
    SeedRecord(
        label="reddit_comment_danish_characters",
        platform="reddit",
        arena="social_media",
        content_type="comment",
        title="",
        text_content="Grønland er fantastisk! æ ø å",
        language="da",
        published_at=_D_NOV + timedelta(hours=1),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=["grønland"],
        term_matched=True,
    ),
    # -------- Bluesky (3 rows) --------
    SeedRecord(
        label="bluesky_post_term_matched_en",
        platform="bluesky",
        arena="social_media",
        content_type="post",
        title="",
        text_content="Climate action in Denmark: a Bluesky thread.",
        language="en",
        published_at=_D_OCT + timedelta(days=1),
        run_label="run_batch",
        query_design_label="qd_en",
        search_terms_matched=["climate"],
        term_matched=True,
    ),
    SeedRecord(
        label="bluesky_post_term_matched_da",
        platform="bluesky",
        arena="social_media",
        content_type="post",
        title="",
        text_content="Klimapolitik på Bluesky.",
        language="da",
        published_at=_D_NOV + timedelta(days=1),
        run_label="run_live",
        query_design_label="qd_da",
        search_terms_matched=["klima"],
        term_matched=True,
        actor_label="actor:bluesky",  # Phase 5: attributed to the Bluesky actor
    ),
    SeedRecord(
        label="bluesky_post_non_term_matched_da",
        platform="bluesky",
        arena="social_media",
        content_type="post",
        title="",
        text_content="Off-topic bluesky post.",
        language="da",
        published_at=_D_DEC,
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=[],
        term_matched=False,  # non-matching on non-actor-only platform
    ),
    # -------- Facebook (actor-only, term_matched=False) (4 rows) --------
    SeedRecord(
        label="facebook_post_actor_only_da",
        platform="facebook",
        arena="social_media",
        content_type="post",
        title="",
        text_content="Et Facebook-opslag fra en aktør.",
        language="da",
        published_at=_D_OCT + timedelta(days=2),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=[],
        term_matched=False,  # actor-only => always False
    ),
    SeedRecord(
        label="facebook_post_actor_only_da_2",
        platform="facebook",
        arena="social_media",
        content_type="post",
        title="",
        text_content="Anden Facebook-tekst.",
        language="da",
        published_at=_D_NOV + timedelta(days=2),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=[],
        term_matched=False,
    ),
    SeedRecord(
        label="facebook_comment_actor_only_en",
        platform="facebook",
        arena="social_media",
        content_type="comment",
        title="",
        text_content="A comment on a Facebook page.",
        language="en",
        published_at=_D_DEC + timedelta(hours=2),
        run_label="run_batch",
        query_design_label="qd_en",
        search_terms_matched=[],
        term_matched=False,
    ),
    SeedRecord(
        label="facebook_post_empty_lang_enriched_da",
        platform="facebook",
        arena="social_media",
        content_type="post",
        title="",
        text_content="Et facebook-opslag uden language-kolonne men med enrichment.",
        language="",  # empty string => triggers NULLIF fallback
        enrichment_lang="da",
        published_at=_D_JAN,
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=[],
        term_matched=False,
    ),
    # -------- Instagram (actor-only, term_matched=False) (3 rows) --------
    SeedRecord(
        label="instagram_reel_actor_only_da",
        platform="instagram",
        arena="social_media",
        content_type="post",
        title="",
        text_content="Instagram-opslag på dansk.",
        language="da",
        published_at=_D_OCT + timedelta(days=3),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=[],
        term_matched=False,
    ),
    SeedRecord(
        label="instagram_post_actor_only_en",
        platform="instagram",
        arena="social_media",
        content_type="post",
        title="",
        text_content="Instagram caption in English.",
        language="en",
        published_at=_D_NOV + timedelta(days=3),
        run_label="run_batch",
        query_design_label="qd_en",
        search_terms_matched=[],
        term_matched=False,
    ),
    SeedRecord(
        label="instagram_post_actor_only_none_lang",
        platform="instagram",
        arena="social_media",
        content_type="post",
        title="",
        text_content="Mixed Danish/English caption that has no language detected.",
        language=None,  # NULL top-level
        enrichment_lang=None,
        published_at=_D_DEC + timedelta(days=1),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=[],
        term_matched=False,
    ),
    # -------- YouTube (3 rows) --------
    SeedRecord(
        label="youtube_video_term_matched_da",
        platform="youtube",
        arena="social_media",
        content_type="video",
        title="YouTube-video om CO2",
        text_content="Description: klima og co2-afgifter i Danmark.",
        language="da",
        published_at=_D_OCT + timedelta(days=4),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=["co2"],
        term_matched=True,
    ),
    SeedRecord(
        label="youtube_video_term_matched_en",
        platform="youtube",
        arena="social_media",
        content_type="video",
        title="Climate video",
        text_content="English-language climate video.",
        language="en",
        published_at=_D_NOV + timedelta(days=4),
        run_label="run_batch",
        query_design_label="qd_en",
        search_terms_matched=["climate"],
        term_matched=True,
    ),
    SeedRecord(
        label="youtube_video_locale_variant_danish",
        platform="youtube",
        arena="social_media",
        content_type="video",
        title="Dansk locale-variant",
        text_content="Video marked with da-DK locale to exercise split_part.",
        language="da-DK",  # locale variant
        published_at=_D_DEC + timedelta(days=2),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=["klima"],
        term_matched=True,
    ),
    # -------- X / Twitter (3 rows) --------
    SeedRecord(
        label="x_tweet_term_matched_da",
        platform="x_twitter",
        arena="social_media",
        content_type="tweet",
        title="",
        text_content="Dansk tweet om klima #klima",
        language="da",
        published_at=_D_OCT + timedelta(days=5),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=["klima"],
        term_matched=True,
    ),
    SeedRecord(
        label="x_reply_term_matched_da",
        platform="x_twitter",
        arena="social_media",
        content_type="reply",
        title="",
        text_content="Svar på et tweet om klima.",
        language="da",
        published_at=_D_NOV + timedelta(days=5),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=["klima"],
        term_matched=True,
    ),
    SeedRecord(
        label="x_tweet_non_term_matched_de",
        platform="x_twitter",
        arena="social_media",
        content_type="tweet",
        title="",
        text_content="Ein deutscher Tweet ohne Suchbegriff.",
        language="de",
        published_at=_D_DEC + timedelta(days=3),
        run_label="run_batch",
        query_design_label="qd_en",
        search_terms_matched=[],
        term_matched=False,
    ),
    # -------- Google Search (4 rows) --------
    SeedRecord(
        label="google_search_result_da",
        platform="google_search",
        arena="search",
        content_type="search_result",
        title="Dansk søgeresultat om klima",
        text_content="Snippet: klimaafgifter i Danmark.",
        language="da",
        published_at=_D_OCT + timedelta(days=6),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=["klima"],
        term_matched=True,
    ),
    SeedRecord(
        label="google_search_result_en",
        platform="google_search",
        arena="search",
        content_type="search_result",
        title="Climate search result",
        text_content="English snippet about climate.",
        language="en",
        published_at=_D_NOV + timedelta(days=6),
        run_label="run_batch",
        query_design_label="qd_en",
        search_terms_matched=["climate"],
        term_matched=True,
    ),
    SeedRecord(
        label="google_article_term_matched_da",
        platform="google_search",
        arena="search",
        content_type="article",
        title="Politiken-artikel om klima",
        text_content="Indhold: debat om klimaafgifter.",
        language="da",
        published_at=_D_NOV + timedelta(days=7),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=["klima"],
        term_matched=True,
        scrape_status="scraped",
    ),
    SeedRecord(
        label="google_article_pending_scrape_da",
        platform="google_search",
        arena="search",
        content_type="article",
        title="Artikel afventer scraping",
        text_content="",
        language="da",
        published_at=_D_DEC + timedelta(days=4),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=["klima"],
        term_matched=True,
        scrape_status="pending",
    ),
    # -------- Wikipedia (3 rows) --------
    SeedRecord(
        label="wikipedia_pageview_da",
        platform="wikipedia",
        arena="search",
        content_type="wiki_pageview",
        title="CO2-afgift",
        text_content="Wikipedia-artikel om CO2-afgift.",
        language="da",
        published_at=_D_OCT + timedelta(days=7),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=["co2"],
        term_matched=True,
    ),
    SeedRecord(
        label="wikipedia_pageview_en",
        platform="wikipedia",
        arena="search",
        content_type="wiki_pageview",
        title="Carbon tax",
        text_content="Wikipedia article about carbon tax.",
        language="en",
        published_at=_D_NOV + timedelta(days=8),
        run_label="run_batch",
        query_design_label="qd_en",
        search_terms_matched=["climate"],
        term_matched=True,
    ),
    SeedRecord(
        label="wikipedia_pageview_empty_lang_enriched",
        platform="wikipedia",
        arena="search",
        content_type="wiki_pageview",
        title="Enriched language fallback",
        text_content="Row with empty language and enrichment detection.",
        language="",  # empty string
        enrichment_lang="de",
        published_at=_D_JAN + timedelta(days=1),
        run_label="run_batch",
        query_design_label="qd_en",
        search_terms_matched=[],
        term_matched=True,
    ),
    # -------- Telegram (3 rows) --------
    SeedRecord(
        label="telegram_post_term_matched_da",
        platform="telegram",
        arena="social_media",
        content_type="post",
        title="",
        text_content="Telegram-besked om klima.",
        language="da",
        published_at=_D_OCT + timedelta(days=8),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=["klima"],
        term_matched=True,
    ),
    SeedRecord(
        label="telegram_post_no_lang_enriched_da",
        platform="telegram",
        arena="social_media",
        content_type="post",
        title="",
        text_content="Telegram-besked med sprogdetektion via enrichment.",
        language=None,
        enrichment_lang="da",
        published_at=_D_NOV + timedelta(days=9),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=["klima"],
        term_matched=True,
    ),
    SeedRecord(
        label="telegram_post_non_term_matched_en",
        platform="telegram",
        arena="social_media",
        content_type="post",
        title="",
        text_content="Random telegram post.",
        language="en",
        published_at=_D_DEC + timedelta(days=5),
        run_label="run_batch",
        query_design_label="qd_en",
        search_terms_matched=[],
        term_matched=False,
    ),
    # -------- Duplicates (5 rows flagged as duplicate_of another row) --------
    SeedRecord(
        label="reddit_dup_of_reddit_post_term_matched_da",
        platform="reddit",
        arena="social_media",
        content_type="post",
        title="Klimakamp i Danmark (duplikat)",
        text_content="Identisk indhold - flagged as duplicate.",
        language="da",
        published_at=_D_JAN + timedelta(days=2),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=["klima"],
        term_matched=True,
        duplicate_of_label="reddit_post_term_matched_da",
    ),
    SeedRecord(
        label="bluesky_dup_of_bluesky_post_term_matched_en",
        platform="bluesky",
        arena="social_media",
        content_type="post",
        title="",
        text_content="Climate action in Denmark: a Bluesky thread (dup).",
        language="en",
        published_at=_D_JAN + timedelta(days=3),
        run_label="run_batch",
        query_design_label="qd_en",
        search_terms_matched=["climate"],
        term_matched=True,
        duplicate_of_label="bluesky_post_term_matched_en",
    ),
    SeedRecord(
        label="youtube_dup_of_youtube_video_term_matched_da",
        platform="youtube",
        arena="social_media",
        content_type="video",
        title="YouTube-video om CO2 (genudgivelse)",
        text_content="Same video description.",
        language="da",
        published_at=_D_JAN + timedelta(days=4),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=["co2"],
        term_matched=True,
        duplicate_of_label="youtube_video_term_matched_da",
    ),
    SeedRecord(
        label="x_dup_of_x_tweet_term_matched_da",
        platform="x_twitter",
        arena="social_media",
        content_type="tweet",
        title="",
        text_content="Dansk tweet om klima #klima (dup)",
        language="da",
        published_at=_D_JAN + timedelta(days=5),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=["klima"],
        term_matched=True,
        duplicate_of_label="x_tweet_term_matched_da",
    ),
    SeedRecord(
        label="telegram_dup_of_telegram_post_term_matched_da",
        platform="telegram",
        arena="social_media",
        content_type="post",
        title="",
        text_content="Telegram-besked om klima (dup).",
        language="da",
        published_at=_D_JAN + timedelta(days=6),
        run_label="run_batch",
        query_design_label="qd_da",
        search_terms_matched=["klima"],
        term_matched=True,
        duplicate_of_label="telegram_post_term_matched_da",
    ),
]


# ---------------------------------------------------------------------------
# Users, projects, query designs, collection runs
# ---------------------------------------------------------------------------

_OWNER_EMAIL = "qa-owner@content-filter-test.example"
_ADMIN_EMAIL = "qa-admin@content-filter-test.example"
_COLLAB_EMAIL = "qa-collab@content-filter-test.example"
_STRANGER_EMAIL = "qa-stranger@content-filter-test.example"

_U_ADMIN = _uid("user:admin")
_U_OWNER = _uid("user:owner")
_U_COLLAB = _uid("user:collab")
_U_STRANGER = _uid("user:stranger")

_PROJECT_ID = _uid("project:primary")
_QD_DA_ID = _uid("qd:da")
_QD_EN_ID = _uid("qd:en")
_RUN_BATCH_ID = _uid("run:batch")
_RUN_LIVE_ID = _uid("run:live")

# Phase 5: Actor rows seeded to exercise the actor_id filter.
# Two actors cover different platforms so the actor filter test exercises
# the author_id IN (...) predicate with real corpus rows.
#
# Actor 1 — Reddit actor: owns reddit_post_term_matched_da and
#   reddit_comment_term_matched_da. With the content_types=["post"] default,
#   only reddit_post_term_matched_da appears in results.
# Actor 2 — Bluesky actor: owns bluesky_post_term_matched_da only.
_ACTOR_REDDIT_ID = _uid("actor:reddit")
_ACTOR_BLUESKY_ID = _uid("actor:bluesky")


# ---------------------------------------------------------------------------
# Manifest dataclass
# ---------------------------------------------------------------------------


@dataclass
class SeededCorpus:
    """Read-only view into what was seeded.

    Tests should reference record UUIDs via ``corpus.by_label("...")`` so
    failing assertions print the label, not a random UUID.
    """

    record_ids: dict[str, uuid.UUID]
    records: list[SeedRecord]
    admin_user_id: uuid.UUID
    owner_user_id: uuid.UUID
    collaborator_user_id: uuid.UUID
    stranger_user_id: uuid.UUID
    admin_email: str
    owner_email: str
    collaborator_email: str
    stranger_email: str
    project_id: uuid.UUID
    query_design_da_id: uuid.UUID
    query_design_en_id: uuid.UUID
    run_batch_id: uuid.UUID
    run_live_id: uuid.UUID
    # Labels whose records carry a linked_run relationship (populated during
    # seed via content_record_links). Used by tests that check linked records.
    linked_record_labels: list[str]
    # Label that is ONLY reachable via content_record_links, not directly
    # via collection_run_id. Exercises the linked-resolution dead-end bug.
    link_only_run_labels: list[str]
    # Phase 5: actor UUIDs keyed by a short label. Tests inject these into
    # the actor_id filter param. Deterministic (uuid5-based) so assertions
    # can reference actors by name rather than opaque UUID.
    actor_ids: dict[str, uuid.UUID] = field(default_factory=dict)

    def by_label(self, label: str) -> uuid.UUID:
        """Look up a record UUID by its human-readable label."""
        try:
            return self.record_ids[label]
        except KeyError as exc:
            raise KeyError(
                f"Unknown seed label {label!r}. Known labels: "
                + ", ".join(sorted(self.record_ids.keys()))
            ) from exc

    def ids(self, *labels: str) -> set[str]:
        """Return the string UUIDs for the given labels."""
        return {str(self.record_ids[lbl]) for lbl in labels}

    def labels_for_ids(self, ids: set[str]) -> set[str]:
        """Inverse lookup: given a set of string UUIDs, return the labels.

        Used by tests to turn opaque response payloads into readable failure
        diffs. Unknown UUIDs are included as ``unknown:<uuid>`` so you can
        immediately tell when the route returned something that is not in
        the seeded corpus.
        """
        inv = {str(v): k for k, v in self.record_ids.items()}
        out: set[str] = set()
        for rid in ids:
            out.add(inv.get(rid, f"unknown:{rid}"))
        return out


# ---------------------------------------------------------------------------
# Seeder: commits the corpus via a raw psycopg2 connection so the data
# survives async test transaction rollbacks.
# ---------------------------------------------------------------------------


def _sync_dsn() -> str:
    """Return a psycopg2 DSN built from the test DATABASE_URL.

    Strips the ``+asyncpg`` driver suffix so psycopg2 accepts it.
    """
    url = os.environ["DATABASE_URL"]
    # Drop the sqlalchemy driver suffix so psycopg2 can parse the rest.
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    return url


def _compute_content_hash(record: SeedRecord) -> str:
    """Generate a stable content_hash for the row."""
    blob = f"{record.platform}|{record.label}|{record.text_content}".encode()
    return hashlib.sha256(blob).hexdigest()


def _build_raw_metadata(
    record: SeedRecord,
    resolved_duplicate_of: uuid.UUID | None,
) -> dict[str, Any]:
    """Assemble the raw_metadata JSONB payload for a seed row."""
    meta: dict[str, Any] = {"qa_fixture": True, "label": record.label}
    if resolved_duplicate_of is not None:
        meta["duplicate_of"] = str(resolved_duplicate_of)
    if record.enrichment_lang is not None:
        meta.setdefault("enrichments", {})["language_detection"] = {
            "language": record.enrichment_lang
        }
    return meta


def _seed_sync(conn: psycopg2.extensions.connection) -> SeededCorpus:
    """Insert the entire corpus with a single psycopg2 connection.

    Idempotent: truncates the fixture's own rows before inserting so that a
    stale partial seed from a previous crashed run is cleaned up. Users,
    projects, query designs, and runs are inserted with ON CONFLICT DO
    NOTHING so the fixture is safe to re-run.
    """
    now = datetime(2026, 2, 20, tzinfo=UTC)
    with conn.cursor() as cur:
        # --- Users ---
        for user_id, email, role, display in [
            (_U_ADMIN, _ADMIN_EMAIL, "admin", "QA Admin"),
            (_U_OWNER, _OWNER_EMAIL, "researcher", "QA Owner"),
            (_U_COLLAB, _COLLAB_EMAIL, "researcher", "QA Collaborator"),
            (_U_STRANGER, _STRANGER_EMAIL, "researcher", "QA Stranger"),
        ]:
            cur.execute(
                """
                INSERT INTO users (id, email, hashed_password, display_name,
                                   role, is_active, created_at)
                VALUES (%s, %s, %s, %s, %s, TRUE, %s)
                ON CONFLICT (id) DO UPDATE SET
                    email = EXCLUDED.email,
                    role = EXCLUDED.role,
                    hashed_password = EXCLUDED.hashed_password,
                    is_active = TRUE
                """,
                (
                    str(user_id),
                    email,
                    TEST_PASSWORD_HASH,
                    display,
                    role,
                    now,
                ),
            )

        # --- Project ---
        cur.execute(
            """
            INSERT INTO projects (id, name, owner_id, visibility,
                                  source_config, arenas_config, comments_config,
                                  collection_mode, created_at, updated_at)
            VALUES (%s, %s, %s, 'private',
                    '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                    'default', %s, %s)
            ON CONFLICT (id) DO UPDATE SET owner_id = EXCLUDED.owner_id
            """,
            (str(_PROJECT_ID), "QA Filter Harness Project", str(_U_OWNER), now, now),
        )

        # --- Collaborator membership ---
        cur.execute(
            """
            INSERT INTO project_collaborators (project_id, user_id, role,
                                               granted_by, granted_at)
            VALUES (%s, %s, 'viewer', %s, %s)
            ON CONFLICT (project_id, user_id) DO NOTHING
            """,
            (str(_PROJECT_ID), str(_U_COLLAB), str(_U_OWNER), now),
        )

        # --- Query designs ---
        for qd_id, name, lang in [
            (_QD_DA_ID, "QA Danish Design", "da"),
            (_QD_EN_ID, "QA English Design", "en"),
        ]:
            cur.execute(
                """
                INSERT INTO query_designs (id, owner_id, name, visibility,
                                           created_at, updated_at, is_active,
                                           default_tier, language, locale_country,
                                           arenas_config, project_id)
                VALUES (%s, %s, %s, 'private', %s, %s, TRUE,
                        'free', %s, 'dk', '{}'::jsonb, %s)
                ON CONFLICT (id) DO UPDATE SET
                    language = EXCLUDED.language,
                    project_id = EXCLUDED.project_id
                """,
                (str(qd_id), str(_U_OWNER), name, now, now, lang, str(_PROJECT_ID)),
            )

        # --- Collection runs ---
        for run_id, qd_id, mode in [
            (_RUN_BATCH_ID, _QD_DA_ID, "batch"),
            (_RUN_LIVE_ID, _QD_DA_ID, "live"),
        ]:
            cur.execute(
                """
                INSERT INTO collection_runs (id, query_design_id, project_id,
                                             initiated_by, mode, status, tier,
                                             started_at, arenas_config,
                                             estimated_credits, credits_spent,
                                             records_collected)
                VALUES (%s, %s, %s, %s, %s, 'completed', 'free', %s, '{}'::jsonb,
                        0, 0, 0)
                ON CONFLICT (id) DO UPDATE SET mode = EXCLUDED.mode
                """,
                (
                    str(run_id),
                    str(qd_id),
                    str(_PROJECT_ID),
                    str(_U_OWNER),
                    mode,
                    now,
                ),
            )

        # --- Phase 5: Actors (seeded before content rows so FKs resolve) ---
        # Two deterministic actors for the actor_id filter test. Created with
        # ON CONFLICT so re-runs are idempotent.
        _actor_label_to_id: dict[str, uuid.UUID] = {
            "actor:reddit": _ACTOR_REDDIT_ID,
            "actor:bluesky": _ACTOR_BLUESKY_ID,
        }
        for actor_id, canonical_name in [
            (_ACTOR_REDDIT_ID, "QA Reddit Actor"),
            (_ACTOR_BLUESKY_ID, "QA Bluesky Actor"),
        ]:
            cur.execute(
                """
                INSERT INTO actors (id, canonical_name, actor_type, is_shared,
                                    created_by, public_figure, created_at)
                VALUES (%s, %s, 'person', FALSE, %s, FALSE, %s)
                ON CONFLICT (id) DO UPDATE SET canonical_name = EXCLUDED.canonical_name
                """,
                (str(actor_id), canonical_name, str(_U_OWNER), now),
            )

        # --- Clean any previous fixture-owned content rows (defensive) ---
        cur.execute(
            """
            DELETE FROM content_record_links
            WHERE collection_run_id = ANY(%s::uuid[])
            """,
            ([str(_RUN_BATCH_ID), str(_RUN_LIVE_ID)],),
        )
        cur.execute(
            """
            DELETE FROM content_records
            WHERE collection_run_id = ANY(%s::uuid[])
            """,
            ([str(_RUN_BATCH_ID), str(_RUN_LIVE_ID)],),
        )

        # --- Content records ---
        record_ids: dict[str, uuid.UUID] = {}
        # Pre-pass: populate record_ids so duplicate_of lookups work.
        for rec in _SEED_RECORDS:
            record_ids[rec.label] = rec.id

        for rec in _SEED_RECORDS:
            run_id = _RUN_BATCH_ID if rec.run_label == "run_batch" else _RUN_LIVE_ID
            qd_id = _QD_DA_ID if rec.query_design_label == "qd_da" else _QD_EN_ID
            resolved_dup_of = (
                record_ids[rec.duplicate_of_label] if rec.duplicate_of_label else None
            )
            raw_meta = _build_raw_metadata(rec, resolved_dup_of)
            # Phase 5: resolve actor_label → actor UUID if set.
            resolved_actor_id = (
                str(_actor_label_to_id[rec.actor_label])
                if rec.actor_label
                else None
            )
            cur.execute(
                """
                INSERT INTO content_records (
                    id, published_at, platform, arena, platform_id,
                    content_type, url, text_content, title, language,
                    collected_at, author_display_name, author_id,
                    collection_run_id, query_design_id,
                    search_terms_matched, collection_tier, raw_metadata,
                    scrape_status, term_matched, content_hash
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s::jsonb,
                    %s, %s, %s
                )
                """,
                (
                    str(rec.id),
                    rec.published_at,
                    rec.platform,
                    rec.arena,
                    rec.platform_id,
                    rec.content_type,
                    f"https://example.test/{rec.label}",
                    rec.text_content,
                    rec.title,
                    rec.language,
                    rec.published_at,  # collected_at ~= published_at
                    f"qa-author-{rec.label[:20]}",
                    resolved_actor_id,
                    str(run_id),
                    str(qd_id),
                    rec.search_terms_matched,
                    "free",
                    psycopg2.extras.Json(raw_meta),
                    rec.scrape_status,
                    rec.term_matched,
                    _compute_content_hash(rec),
                ),
            )

        # --- Content record links ---
        # Link 1: a reddit record from run_batch cross-linked to run_live so
        # the EXISTS join in _run_id_filter is exercised and the run_id filter
        # for run_live returns the linked reddit record.
        #
        # Link 2-3: two records from run_batch linked to run_live so multiple
        # link rows exist.
        link_labels = [
            "reddit_post_term_matched_da",
            "bluesky_post_term_matched_en",
            "wikipedia_pageview_en",
        ]
        for label in link_labels:
            rec = next(r for r in _SEED_RECORDS if r.label == label)
            cur.execute(
                """
                INSERT INTO content_record_links (
                    id, content_record_id, content_record_published_at,
                    collection_run_id, query_design_id, linked_at, link_type
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'reindex')
                ON CONFLICT DO NOTHING
                """,
                (
                    str(_uid(f"link:{label}")),
                    str(rec.id),
                    rec.published_at,
                    str(_RUN_LIVE_ID),  # Link into the live run
                    str(_QD_DA_ID),
                    now,
                ),
            )

        # Search-term-only-via-link: insert a bare content_record_link that
        # points at a record whose search_terms_matched does NOT contain a
        # given term, so that the link-resolution dead-end bug (UX Major #4,
        # #6) can be observed. We reuse an existing record and set a
        # different logical "term" via a marker label.
        # Implemented simply: use bluesky_post_term_matched_en which has
        # search_terms_matched=["climate"] but we consider "klima" as the
        # term that only exists via link-join (since it doesn't appear
        # there directly).

        link_only_run_labels = ["bluesky_post_term_matched_en"]

    conn.commit()

    return SeededCorpus(
        record_ids=record_ids,
        records=list(_SEED_RECORDS),
        admin_user_id=_U_ADMIN,
        owner_user_id=_U_OWNER,
        collaborator_user_id=_U_COLLAB,
        stranger_user_id=_U_STRANGER,
        admin_email=_ADMIN_EMAIL,
        owner_email=_OWNER_EMAIL,
        collaborator_email=_COLLAB_EMAIL,
        stranger_email=_STRANGER_EMAIL,
        project_id=_PROJECT_ID,
        query_design_da_id=_QD_DA_ID,
        query_design_en_id=_QD_EN_ID,
        run_batch_id=_RUN_BATCH_ID,
        run_live_id=_RUN_LIVE_ID,
        linked_record_labels=link_labels,
        link_only_run_labels=link_only_run_labels,
        actor_ids=_actor_label_to_id,
    )


def _teardown_sync(conn: psycopg2.extensions.connection) -> None:
    """Remove every fixture-owned row. Safe to call multiple times.

    If the connection was left in an aborted-transaction state by a failed
    seed, we roll back first so the DELETE statements can execute.
    """
    try:
        conn.rollback()
    except Exception:  # pragma: no cover — best-effort cleanup
        pass
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM content_record_links WHERE collection_run_id = ANY(%s::uuid[])",
            ([str(_RUN_BATCH_ID), str(_RUN_LIVE_ID)],),
        )
        cur.execute(
            "DELETE FROM content_records WHERE collection_run_id = ANY(%s::uuid[])",
            ([str(_RUN_BATCH_ID), str(_RUN_LIVE_ID)],),
        )
        cur.execute(
            "DELETE FROM collection_runs WHERE id = ANY(%s::uuid[])",
            ([str(_RUN_BATCH_ID), str(_RUN_LIVE_ID)],),
        )
        cur.execute(
            "DELETE FROM query_designs WHERE id = ANY(%s::uuid[])",
            ([str(_QD_DA_ID), str(_QD_EN_ID)],),
        )
        cur.execute(
            "DELETE FROM project_collaborators WHERE project_id = %s",
            (str(_PROJECT_ID),),
        )
        cur.execute("DELETE FROM projects WHERE id = %s", (str(_PROJECT_ID),))
        # Phase 5: clean up actor rows. The FK on content_records.author_id uses
        # ON DELETE SET NULL so records are already cleaned before this runs.
        cur.execute(
            "DELETE FROM actors WHERE id = ANY(%s::uuid[])",
            ([str(_ACTOR_REDDIT_ID), str(_ACTOR_BLUESKY_ID)],),
        )
        cur.execute(
            "DELETE FROM users WHERE id = ANY(%s::uuid[])",
            ([str(_U_ADMIN), str(_U_OWNER), str(_U_COLLAB), str(_U_STRANGER)],),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Public fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def seeded_corpus() -> Generator[SeededCorpus, None, None]:
    """Commit the deterministic content-filter corpus once per pytest session.

    Uses a raw psycopg2 connection so the INSERTs commit immediately and
    survive the per-test async rollback that ``tests/conftest.py::db_session``
    applies. Tears down the rows at session end.
    """
    conn = psycopg2.connect(_sync_dsn())
    try:
        corpus = _seed_sync(conn)
        yield corpus
    finally:
        try:
            _teardown_sync(conn)
        finally:
            conn.close()


@pytest.fixture(scope="session")
def corpus(seeded_corpus: SeededCorpus) -> SeededCorpus:
    """Short alias so tests can write ``corpus.by_label(...)``."""
    return seeded_corpus


# ---------------------------------------------------------------------------
# Authenticated HTTP clients — one per user type.
#
# These fixtures share the module-level ``client`` from tests/conftest.py,
# which already overrides ``get_db`` and drives startup events. We log in as
# the fixture user and return a fresh ``AsyncClient`` with the Authorization
# header baked in so tests can just ``await auth_client_owner.get(...)``.
# ---------------------------------------------------------------------------


async def _bearer_token(client: AsyncClient, email: str) -> str:
    """Log in as ``email`` and return the bearer token.

    Rate-limiting mitigation: the FastAPI app uses slowapi with a
    100-request/minute limit on ``/auth/bearer/login``. Each call here
    costs one of those credits, so we cache the returned token in a
    module-level dict keyed on email and reuse it across tests.
    """
    cached = _TOKEN_CACHE.get(email)
    if cached is not None:
        return cached
    resp = await client.post(
        "/auth/bearer/login",
        data={"username": email, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, (
        f"Login failed for {email!r}: {resp.status_code} {resp.text}"
    )
    token = resp.json()["access_token"]
    _TOKEN_CACHE[email] = token
    return token


_TOKEN_CACHE: dict[str, str] = {}


@pytest_asyncio.fixture
async def auth_headers_owner(
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
) -> dict[str, str]:
    token = await _bearer_token(client, seeded_corpus.owner_email)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def auth_headers_admin(
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
) -> dict[str, str]:
    token = await _bearer_token(client, seeded_corpus.admin_email)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def auth_headers_collaborator(
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
) -> dict[str, str]:
    token = await _bearer_token(client, seeded_corpus.collaborator_email)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def auth_headers_stranger(
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
) -> dict[str, str]:
    token = await _bearer_token(client, seeded_corpus.stranger_email)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Helpers shared by every test file
# ---------------------------------------------------------------------------


async def fetch_records_json(
    client: AsyncClient,
    headers: dict[str, str],
    params: dict[str, Any],
    *,
    path: str = "/content/records",
) -> tuple[int, list[dict[str, Any]], dict[str, Any]]:
    """GET the JSON body of ``/content/records`` (or a sibling route).

    Returns ``(http_status, records_list, pagination_metadata)``.
    For non-200 responses the records list is empty and pagination is ``{}``.
    """
    query = {**params, "format": "json"}
    # Strip None values so we don't accidentally send "?foo=None".
    query = {k: v for k, v in query.items() if v is not None}
    resp = await client.get(path, params=query, headers=headers)
    if resp.status_code != 200:
        return resp.status_code, [], {}
    body = resp.json()
    return resp.status_code, body.get("records", []), body.get("pagination", {})


def record_id_set(records: list[dict[str, Any]]) -> set[str]:
    """Extract the set of record IDs from a JSON records payload."""
    return {str(r["id"]) for r in records}
