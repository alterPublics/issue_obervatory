"""Phase-1a diff harness: route vs shared filter helper.

Every ``FilterCase`` in ``_matrix.FILTER_CASES`` is run through two paths:

- **Path A (route):** ``GET /content/records?format=json&<params>`` via the
  HTTP client — exercises the full FastAPI route stack.
- **Path B (helper):** ``ContentFilterSpec.from_browse_route(...)`` →
  ``build_browse_stmt(spec)`` → direct DB query — exercises the shared filter
  helper in isolation.

The diff test asserts that both paths return **identical record ID sets** for
every case. Any divergence is a Phase 1a bug; fix the helper, not the test.

Phase 0 placeholder removed: this module is now the real diff gate.

Owned by: QA Guardian (harness), Core Application Engineer (Phase 1a).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient  # noqa: TC002
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from tests.integration.api.content._matrix import (
    FILTER_CASES,
    FilterCase,
    pytest_ids,
)
from tests.integration.api.content.conftest import (
    SeededCorpus,
    fetch_records_json,
    record_id_set,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
]


# ---------------------------------------------------------------------------
# Helper: run a spec directly through the filter helper (Path B)
# ---------------------------------------------------------------------------


async def _run_spec_via_helper(
    db_session: AsyncSession,
    seeded_corpus: SeededCorpus,
    case: FilterCase,
) -> set[str]:
    """Execute the filter spec directly against the DB via the shared helper.

    Mirrors exactly what the route does, including:
    - ``effective_show_all`` mutation (bug preserved).
    - ``content_types=["post"]`` default (bug preserved).
    - ``owner_only`` ownership scoping (browse route path).

    Returns a set of record ID strings.
    """
    # Resolve the owner user from the DB so we have a real User ORM instance.
    from sqlalchemy import select as sa_select

    from issue_observatory.core.models.users import User
    from issue_observatory.core.queries.content_filters import (
        ContentFilterSpec,
        build_browse_stmt,
    )

    user_stmt = sa_select(User).where(User.id == seeded_corpus.owner_user_id)
    user_result = await db_session.execute(user_stmt)
    owner = user_result.scalar_one()

    # Convert matrix params to from_browse_route kwargs.
    params = _matrix_params_to_browse_kwargs(case, seeded_corpus)
    spec = ContentFilterSpec.from_browse_route(
        current_user=owner,
        **params,
    )

    stmt = build_browse_stmt(spec, limit=200)
    result = await db_session.execute(stmt)
    rows = result.mappings().all()
    return {str(row["UniversalContentRecord"].id) for row in rows}


def _matrix_params_to_browse_kwargs(
    case: FilterCase,
    corpus: SeededCorpus,
) -> dict:
    """Convert a FilterCase.params dict to ``from_browse_route`` kwargs.

    Replicates the parsing that the FastAPI route does before delegating
    to the helper (``_parse_date_param``, ``_parse_uuid``, multi-arena
    list normalisation, etc.).
    """
    from tests.integration.api.content.test_filter_current_behavior import _inject_runtime_params

    raw = _inject_runtime_params(case.name, case.params, corpus)

    def _parse_date(val: str | None, *, end_of_day: bool = False) -> datetime | None:
        if not val:
            return None
        try:
            dt = datetime.fromisoformat(val).replace(tzinfo=UTC)
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            return dt
        except ValueError:
            return None

    def _parse_uuid(val: str | None) -> uuid.UUID | None:
        if not val or not str(val).strip():
            return None
        try:
            return uuid.UUID(str(val))
        except (ValueError, AttributeError):
            return None

    arenas_raw = raw.get("arenas") or []
    if isinstance(arenas_raw, str):
        arenas_raw = [arenas_raw]
    arenas_list = list(arenas_raw)
    platform_filter: str | None = raw.get("platform")
    if len(arenas_list) == 1:
        platform_filter = arenas_list[0]

    # Phase 6 — Task 2: apply same enum validation that the route applies so
    # Path B (helper) matches Path A (route) when invalid values are submitted.
    from issue_observatory.api.routes.content import (
        _VALID_LANGUAGES,
        _VALID_MODES,
        _VALID_SCRAPE_STATUSES,
    )

    def _validate_enum(val: str | None, allowed: frozenset) -> str | None:
        if val and val not in allowed:
            return None
        return val

    raw_mode = _validate_enum(raw.get("mode"), _VALID_MODES)
    raw_scrape = _validate_enum(raw.get("scrape_status"), _VALID_SCRAPE_STATUSES)
    raw_language = raw.get("language") or None
    if raw_language:
        raw_language = _validate_enum(raw_language, _VALID_LANGUAGES)

    # show_all: route coerces "true"/"false" strings from form.
    show_all_raw = raw.get("show_all", False)
    if isinstance(show_all_raw, str):
        show_all = show_all_raw.lower() == "true"
    else:
        show_all = bool(show_all_raw)

    # show_duplicates: route coerces "true"/"false" strings from form.
    show_dup_raw = raw.get("show_duplicates", False)
    if isinstance(show_dup_raw, str):
        show_duplicates = show_dup_raw.lower() == "true"
    else:
        show_duplicates = bool(show_dup_raw)

    # content_types: list[str] | None
    content_types_raw = raw.get("content_types")
    if isinstance(content_types_raw, str):
        content_types: list[str] | None = [content_types_raw]
    else:
        content_types = list(content_types_raw) if content_types_raw else None

    # actor_ids: list[uuid.UUID]
    actor_ids_raw = raw.get("actor_id") or []
    if isinstance(actor_ids_raw, str):
        actor_ids_raw = [actor_ids_raw]
    actor_ids = [_id for raw_id in actor_ids_raw if (_id := _parse_uuid(raw_id)) is not None]

    return {
        "q": raw.get("q"),
        "platform": platform_filter if len(arenas_list) <= 1 else None,
        "arena": raw.get("arena"),
        "arenas_list": arenas_list,
        "date_from": _parse_date(raw.get("date_from")),
        "date_to": _parse_date(raw.get("date_to"), end_of_day=True),
        "language": raw_language,
        "search_term": raw.get("search_term"),
        "run_id": _parse_uuid(raw.get("run_id")),
        "mode": raw_mode,
        "project_id": _parse_uuid(raw.get("project_id")),
        "query_design_id": _parse_uuid(raw.get("query_design_id")),
        "show_all": show_all,
        "include_duplicates": show_duplicates,
        "actor_ids": actor_ids,
        "scrape_status": raw_scrape,
        "content_types": content_types,
        "sort_by": raw.get("sort_by"),
        "sort_dir": raw.get("sort_dir"),
        "limit": 200,
    }


# ---------------------------------------------------------------------------
# Diff test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", FILTER_CASES, ids=pytest_ids(FILTER_CASES))
async def test_diff_harness(
    case: FilterCase,
    client: AsyncClient,
    db_session: AsyncSession,
    seeded_corpus: SeededCorpus,
    auth_headers_owner: dict[str, str],
) -> None:
    """Route vs helper must return identical record ID sets for every case.

    Path A: ``GET /content/records?format=json&<params>`` (HTTP route).
    Path B: ``ContentFilterSpec.from_browse_route`` → ``build_browse_stmt``
            → direct DB execute.

    A divergence here is a Phase 1a bug. Fix the helper to match the route
    output — do NOT weaken this assertion.
    """
    from tests.integration.api.content.test_filter_current_behavior import _inject_runtime_params

    # Build the HTTP params for Path A.
    params = _inject_runtime_params(case.name, case.params, seeded_corpus)
    params["limit"] = 200

    # Path A — route
    status_a, records_a, _ = await fetch_records_json(
        client, auth_headers_owner, params
    )
    assert status_a == 200, f"{case.name}: HTTP route returned {status_a}"

    # Path B — shared helper
    helper_ids = await _run_spec_via_helper(db_session, seeded_corpus, case)
    route_ids = record_id_set(records_a)

    labels_route = seeded_corpus.labels_for_ids(route_ids)
    labels_helper = seeded_corpus.labels_for_ids(helper_ids)

    assert labels_route == labels_helper, (
        f"{case.name}: route vs helper row-set divergence.\n"
        f"  Only in route:  {sorted(labels_route - labels_helper)}\n"
        f"  Only in helper: {sorted(labels_helper - labels_route)}\n"
        "Fix the helper (content_filters.py) to match the route output."
    )
