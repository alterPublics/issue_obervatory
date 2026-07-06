"""Phase-0 harness: pin the CURRENT behavior of the content filter route.

This file captures what ``/content/records`` returns **today** for every
filter case in ``_matrix.FILTER_CASES``. The expected row sets in
``_matrix.py`` reflect the fixed behavior after Phase 2, so any case where
today's output diverges is marked ``xfail(strict=False)``.

Two assertions per case:

1. **Determinism** — calling the same filter twice returns the same row set.
   This is always strict; a non-deterministic route is immediately a bug.
2. **Owner row set** — the owner's returned IDs match ``case.expected_labels``.
   Marked ``xfail(strict=False)`` today because the bugs listed in
   ``docs/qa_reports/content_page_filter_audit.md`` make this fail. Phase 2
   will flip the xfails to strict=True as each bug lands.

Why ``xfail(strict=False)`` and not ``strict=True``?
---------------------------------------------------
Because we do not yet know which cases still diverge after every intended
fix. Some bugs compose — fixing ``show_all`` may accidentally fix
``content_types`` in certain matrices. ``strict=False`` means "if this
passes, great; if it fails, document it, don't block the build". Phase 2
will tighten to strict=True as the bugs resolve.

Also includes the Danish character preservation test (QA audit §6).

Owned by: QA Guardian.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient  # noqa: TC002

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
# Determinism (always strict)
# ---------------------------------------------------------------------------


def _inject_runtime_params(
    case_name: str,
    params: dict,
    seeded_corpus: SeededCorpus,
) -> dict:
    """Inject run-time IDs for cases that depend on fixture-created UUIDs.

    Cases that parametrize on UUIDs that only exist after the fixture has run
    (collection run IDs, project IDs, query design IDs) store empty params
    and receive the actual values here at call time.
    """
    params = dict(params)
    if case_name == "run_id_batch_search_term_klima":
        params["run_id"] = str(seeded_corpus.run_batch_id)
    if case_name in ("project_id_primary_language_da",):
        params["project_id"] = str(seeded_corpus.project_id)
    if case_name in ("query_design_id_da", "query_design_da_language_da"):
        params["query_design_id"] = str(seeded_corpus.query_design_da_id)
    # Phase 5: actor rows are now seeded — inject the Reddit actor's UUID so the
    # route filters by author_id and returns the one attributed post.
    if case_name == "actor_id_filter":
        params["actor_id"] = str(seeded_corpus.actor_ids["actor:reddit"])
    return params


@pytest.mark.parametrize("case", FILTER_CASES, ids=pytest_ids(FILTER_CASES))
async def test_route_is_deterministic(
    case: FilterCase,
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
    auth_headers_owner: dict[str, str],
) -> None:
    """The same filter spec must return the same set of records twice.

    Non-determinism here would indicate pagination/cursor state leaking or
    a race against a background writer. This assertion is unconditional —
    Phase 2 cannot regress determinism.
    """
    params = _inject_runtime_params(case.name, case.params, seeded_corpus)

    status1, records1, _ = await fetch_records_json(
        client, auth_headers_owner, params
    )
    status2, records2, _ = await fetch_records_json(
        client, auth_headers_owner, params
    )
    assert status1 == 200, f"{case.name}: first call returned {status1}"
    assert status2 == 200, f"{case.name}: second call returned {status2}"

    ids1 = record_id_set(records1)
    ids2 = record_id_set(records2)
    labels1 = seeded_corpus.labels_for_ids(ids1)
    labels2 = seeded_corpus.labels_for_ids(ids2)
    assert labels1 == labels2, (
        f"{case.name}: non-deterministic response. "
        f"First call={sorted(labels1)}, second call={sorted(labels2)}"
    )


# ---------------------------------------------------------------------------
# Expected row set — xfail(strict=False) today, will tighten in Phase 2
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", FILTER_CASES, ids=pytest_ids(FILTER_CASES))
async def test_owner_sees_expected_row_set(
    case: FilterCase,
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
    auth_headers_owner: dict[str, str],
    request: pytest.FixtureRequest,
) -> None:
    """The owner's row set must match the post-fix expected set.

    Pinned xfail(strict=False) where current code diverges — the test
    docstring + the ``bug_tags`` on the case point to the exact line.
    """
    if case.bug_tags:
        reasons = ", ".join(sorted(case.bug_tags))
        request.applymarker(
            pytest.mark.xfail(
                strict=False,
                reason=(
                    f"{case.name}: pinned divergence due to [{reasons}]. "
                    f"Phase 2 will flip to strict=True once the bug is fixed."
                ),
            )
        )

    params = _inject_runtime_params(case.name, case.params, seeded_corpus)
    # Limit high enough to capture everything under the 2000-row cap.
    params["limit"] = 200

    status, records, _ = await fetch_records_json(
        client, auth_headers_owner, params
    )
    assert status == 200, f"{case.name}: HTTP {status}"

    actual = seeded_corpus.labels_for_ids(record_id_set(records))
    # Only consider rows that are in the seeded corpus; unrelated data
    # from other fixtures (e.g. auth_flow) should never leak in, but if
    # it does we want the diff to be tight.
    fixture_labels = set(seeded_corpus.record_ids.keys())
    actual = actual & fixture_labels

    assert actual == case.expected_labels, (
        f"\n{case.name}: row set mismatch.\n"
        f"  Missing (expected but not returned): "
        f"{sorted(case.expected_labels - actual)}\n"
        f"  Extra (returned but not expected): "
        f"{sorted(actual - case.expected_labels)}"
    )


# ---------------------------------------------------------------------------
# Stranger must see nothing (always strict — ownership scoping is
# non-negotiable, and the seeded stranger has no relationship with the
# corpus). This is the one assertion we trust today.
# ---------------------------------------------------------------------------


async def test_stranger_sees_zero_records_on_baseline(
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
    auth_headers_stranger: dict[str, str],
) -> None:
    """Stranger user must never see fixture records."""
    status, records, _ = await fetch_records_json(
        client, auth_headers_stranger, {"limit": 200}
    )
    assert status == 200
    actual = seeded_corpus.labels_for_ids(record_id_set(records))
    leaked = actual & set(seeded_corpus.record_ids.keys())
    assert leaked == set(), (
        f"stranger user leaked fixture records: {sorted(leaked)}"
    )


# ---------------------------------------------------------------------------
# Danish character preservation — non-negotiable per QA audit §6.
# ---------------------------------------------------------------------------


    # PHASE_3_NOT_YET_BUILT is now empty — Phase 3 filters have been shipped.
    # The placeholder was removed in Phase 3; cases that required actor_id
    # fixture injection are in FILTER_CASES with empty expected_labels until
    # the conftest seeds Actor rows (tracked in Phase 5 follow-up).


async def test_danish_characters_preserved_end_to_end(
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
    auth_headers_owner: dict[str, str],
) -> None:
    """æ/ø/å must survive filter → SQL → response without mangling.

    Seed row ``reddit_comment_danish_characters`` has the text
    ``"Grønland er fantastisk! æ ø å"``. A full-text search for ``grønland``
    must return that row with the characters intact in the JSON payload.
    """
    # Pass content_types explicitly to work around the current
    # content_types=["post"] hidden default — the seeded Danish row is a
    # ``comment`` so the default filter would exclude it. Phase 2 will
    # flip the default; until then the test expresses its intent directly.
    status, records, _ = await fetch_records_json(
        client,
        auth_headers_owner,
        {
            "q": "grønland",
            "show_all": "true",
            "content_types": ["post", "comment"],
            "limit": 200,
        },
    )
    assert status == 200, f"HTTP {status}"

    # The fixture row must be in the response.
    actual_labels = seeded_corpus.labels_for_ids(record_id_set(records))
    assert "reddit_comment_danish_characters" in actual_labels, (
        f"Danish FTS query dropped the æ/ø/å row. Returned labels: "
        f"{sorted(actual_labels & set(seeded_corpus.record_ids.keys()))}"
    )

    # The characters must round-trip intact in the text payload.
    target = next(
        r
        for r in records
        if str(r["id"]) == str(seeded_corpus.by_label("reddit_comment_danish_characters"))
    )
    text_value = target.get("text_content") or ""
    for ch in ("æ", "ø", "å"):
        assert ch in text_value, (
            f"Danish character {ch!r} missing from response text: {text_value!r}"
        )
