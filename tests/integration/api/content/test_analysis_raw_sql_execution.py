"""Regression harness for the analysis layer's raw-SQL filter path.

Catches the class of bug where ``core/queries/content_filters.py``
``build_content_where_sql`` emits ``IN :param`` with a tuple bind instead of
expanded placeholders — asyncpg rejects this with
``PostgresSyntaxError: syntax error at or near "$N"``, silently breaking every
dashboard chart and every descriptive statistics endpoint.

The existing Phase 0 harness exercises the SQLAlchemy Core path (which uses
``sa_clause`` with ``.in_()``). This file exercises the **raw-SQL** path that
the analysis layer uses via ``build_content_where_sql``, so the two halves of
the neutral-IR helper are both covered.

Any future predicate added to the helper must also be exercised here against
the real fixture corpus — otherwise the bug can silently reappear.

Covered raw-SQL predicates:

- ``show_all=False`` actor-only exemption (both ``include_linked=True`` EXISTS
  branch and ``include_linked=False`` simple branch).
- ``content_types`` IN predicate.
- ``languages`` split_part IN predicate.
- ``arenas`` / ``platforms`` IN predicates.
- ``query_design_ids`` IN predicate with linked-records EXISTS.
- ``search_terms`` array overlap predicate.

Each test asserts that the function executes without error and returns a
well-formed result — not the exact row counts, because the fixture corpus
is small and the analysis functions operate on aggregates.

Owned by: DB Engineer (analysis layer).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from issue_observatory.analysis.descriptive import (
    get_top_actors,
    get_top_terms,
    get_volume_over_time,
    get_volume_with_deltas,
)
from tests.integration.api.content.conftest import SeededCorpus  # noqa: TC001

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
]


# ---------------------------------------------------------------------------
# get_volume_over_time — hits actor_only_platforms predicate
# ---------------------------------------------------------------------------


async def test_volume_over_time_default_executes(
    db_session: AsyncSession,
    seeded_corpus: SeededCorpus,
) -> None:
    """Baseline: show_all=False default must not emit broken IN :param SQL."""
    rows = await get_volume_over_time(
        db_session,
        query_design_ids=[seeded_corpus.query_design_da_id, seeded_corpus.query_design_en_id],
        granularity="day",
    )
    assert isinstance(rows, list)
    # At least one period with data — the fixture has term-matched records.
    assert any(row["count"] > 0 for row in rows), rows


async def test_volume_over_time_include_linked_false(
    db_session: AsyncSession,
    seeded_corpus: SeededCorpus,
) -> None:
    """include_linked=False hits the simpler actor_only_platforms branch.

    This is the path the dashboard charts use (dashboard.py passes
    include_linked=False for performance).
    """
    rows = await get_volume_over_time(
        db_session,
        query_design_ids=[seeded_corpus.query_design_da_id],
        granularity="day",
        include_linked=False,
    )
    assert isinstance(rows, list)


async def test_volume_over_time_include_linked_true_with_designs(
    db_session: AsyncSession,
    seeded_corpus: SeededCorpus,
) -> None:
    """include_linked=True with query_design_ids hits the EXISTS branch."""
    rows = await get_volume_over_time(
        db_session,
        query_design_ids=[seeded_corpus.query_design_da_id, seeded_corpus.query_design_en_id],
        granularity="day",
        include_linked=True,
    )
    assert isinstance(rows, list)


async def test_volume_over_time_with_language(
    db_session: AsyncSession,
    seeded_corpus: SeededCorpus,
) -> None:
    """language filter exercises the split_part COALESCE predicate in raw SQL."""
    rows = await get_volume_over_time(
        db_session,
        query_design_ids=[seeded_corpus.query_design_da_id],
        granularity="day",
        language="da",
        include_linked=False,
    )
    assert isinstance(rows, list)


async def test_volume_over_time_with_arena(
    db_session: AsyncSession,
    seeded_corpus: SeededCorpus,
) -> None:
    """arena filter exercises the arena = :arena predicate in raw SQL."""
    rows = await get_volume_over_time(
        db_session,
        query_design_ids=[seeded_corpus.query_design_da_id],
        granularity="day",
        arena="social_media",
        include_linked=False,
    )
    assert isinstance(rows, list)


async def test_volume_with_deltas_executes(
    db_session: AsyncSession,
    seeded_corpus: SeededCorpus,
) -> None:
    """get_volume_with_deltas is the dashboard's actual entry point."""
    rows = await get_volume_with_deltas(
        db_session,
        query_design_ids=[seeded_corpus.query_design_da_id, seeded_corpus.query_design_en_id],
        granularity="day",
        include_linked=False,
    )
    assert isinstance(rows, list)


# ---------------------------------------------------------------------------
# get_top_actors / get_top_terms — also use raw SQL, different SELECT shape
# ---------------------------------------------------------------------------


async def test_top_actors_executes(
    db_session: AsyncSession,
    seeded_corpus: SeededCorpus,
) -> None:
    """get_top_actors exercises the same WHERE path with a different SELECT."""
    rows = await get_top_actors(
        db_session,
        query_design_ids=[seeded_corpus.query_design_da_id, seeded_corpus.query_design_en_id],
        limit=10,
    )
    assert isinstance(rows, list)


async def test_top_terms_executes(
    db_session: AsyncSession,
    seeded_corpus: SeededCorpus,
) -> None:
    """get_top_terms exercises the same WHERE path with yet another SELECT."""
    rows = await get_top_terms(
        db_session,
        query_design_ids=[seeded_corpus.query_design_da_id, seeded_corpus.query_design_en_id],
        limit=10,
    )
    assert isinstance(rows, list)


# ---------------------------------------------------------------------------
# Direct helper smoke tests — exercise the raw-SQL predicates in isolation
# ---------------------------------------------------------------------------


async def test_build_content_where_sql_executes_with_content_types(
    db_session: AsyncSession,
    seeded_corpus: SeededCorpus,
) -> None:
    """content_types IN predicate must use expanded placeholders in raw SQL.

    This is the second class of the asyncpg tuple-bind bug.
    """
    from sqlalchemy import text

    from issue_observatory.core.queries.content_filters import (
        ContentFilterSpec,
        build_content_where_sql,
    )

    spec = ContentFilterSpec(
        query_design_ids=[seeded_corpus.query_design_da_id],
        content_types=["post", "comment"],
        content_types_was_explicit=True,
        include_linked=False,
        include_duplicates=False,
        ownership_mode="admin",
    )
    params: dict[str, object] = {}
    where = build_content_where_sql(spec, table_alias="", params=params)

    sql = text(f"SELECT count(*) FROM content_records {where}")
    result = await db_session.execute(sql, params)
    count = result.scalar()
    assert isinstance(count, int)


async def test_build_content_where_sql_executes_with_multi_platform(
    db_session: AsyncSession,
    seeded_corpus: SeededCorpus,
) -> None:
    """platforms IN predicate must use expanded placeholders in raw SQL."""
    from sqlalchemy import text

    from issue_observatory.core.queries.content_filters import (
        ContentFilterSpec,
        build_content_where_sql,
    )

    spec = ContentFilterSpec(
        query_design_ids=[seeded_corpus.query_design_da_id],
        platforms=["reddit", "bluesky", "facebook"],
        include_linked=False,
        include_duplicates=False,
        ownership_mode="admin",
    )
    params: dict[str, object] = {}
    where = build_content_where_sql(spec, table_alias="", params=params)

    sql = text(f"SELECT count(*) FROM content_records {where}")
    result = await db_session.execute(sql, params)
    count = result.scalar()
    assert isinstance(count, int)


async def test_build_content_where_sql_executes_with_search_terms(
    db_session: AsyncSession,
    seeded_corpus: SeededCorpus,
) -> None:
    """search_terms && predicate must use expanded placeholders in raw SQL."""
    from sqlalchemy import text

    from issue_observatory.core.queries.content_filters import (
        ContentFilterSpec,
        build_content_where_sql,
    )

    spec = ContentFilterSpec(
        query_design_ids=[seeded_corpus.query_design_da_id],
        search_terms=["klima", "nato"],
        include_linked=False,
        include_duplicates=False,
        ownership_mode="admin",
    )
    params: dict[str, object] = {}
    where = build_content_where_sql(spec, table_alias="", params=params)

    sql = text(f"SELECT count(*) FROM content_records {where}")
    result = await db_session.execute(sql, params)
    count = result.scalar()
    assert isinstance(count, int)


async def test_build_content_where_sql_executes_with_languages(
    db_session: AsyncSession,
    seeded_corpus: SeededCorpus,
) -> None:
    """languages split_part IN predicate must use expanded placeholders."""
    from sqlalchemy import text

    from issue_observatory.core.queries.content_filters import (
        ContentFilterSpec,
        build_content_where_sql,
    )

    spec = ContentFilterSpec(
        query_design_ids=[seeded_corpus.query_design_da_id],
        languages=["da", "en", "de"],
        include_linked=False,
        include_duplicates=False,
        ownership_mode="admin",
    )
    params: dict[str, object] = {}
    where = build_content_where_sql(spec, table_alias="", params=params)

    sql = text(f"SELECT count(*) FROM content_records {where}")
    result = await db_session.execute(sql, params)
    count = result.scalar()
    assert isinstance(count, int)


async def test_build_content_where_sql_executes_show_all_false_default(
    db_session: AsyncSession,
    seeded_corpus: SeededCorpus,
) -> None:
    """show_all=False with include_linked=False hits the simple actor-only branch.

    This is the exact predicate shape that broke the dashboard charts for
    galgotias — the ``platform IN :actor_only_platforms`` tuple-bind bug.
    """
    from sqlalchemy import text

    from issue_observatory.core.queries.content_filters import (
        ContentFilterSpec,
        build_content_where_sql,
    )

    spec = ContentFilterSpec(
        query_design_ids=[seeded_corpus.query_design_da_id],
        show_all=False,
        include_linked=False,
        include_duplicates=False,
        ownership_mode="admin",
    )
    params: dict[str, object] = {}
    where = build_content_where_sql(spec, table_alias="", params=params)

    sql = text(f"SELECT count(*) FROM content_records {where}")
    result = await db_session.execute(sql, params)
    count = result.scalar()
    assert isinstance(count, int)


async def test_build_content_where_sql_executes_show_all_false_with_linked(
    db_session: AsyncSession,
    seeded_corpus: SeededCorpus,
) -> None:
    """show_all=False + include_linked=True hits the EXISTS branch variant."""
    from sqlalchemy import text

    from issue_observatory.core.queries.content_filters import (
        ContentFilterSpec,
        build_content_where_sql,
    )

    spec = ContentFilterSpec(
        query_design_ids=[seeded_corpus.query_design_da_id],
        show_all=False,
        include_linked=True,
        include_duplicates=False,
        ownership_mode="admin",
    )
    params: dict[str, object] = {}
    where = build_content_where_sql(spec, table_alias="", params=params)

    sql = text(f"SELECT count(*) FROM content_records {where}")
    result = await db_session.execute(sql, params)
    count = result.scalar()
    assert isinstance(count, int)
