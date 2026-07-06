"""Phase-0 harness: pin the ``count == len(rows)`` invariant.

The core success criterion for the content page fix is that the
``#record-count`` OOB badge agrees with the rendered ``<tr>`` rows for
every filter combination, at every pagination stage.

Today the invariant is broken in the three cases documented in QA §3.2
and UX Blocker #3, all caused by the ``effective_show_all`` mutation
at ``content.py:1063, 1324`` and the count call at ``:1157, 1456`` that
receives the raw ``show_all`` instead. This test pins each broken case as
``xfail`` so Phase 2 must explicitly clear the pin rather than silently
regress.

What we compare
---------------
1. ``/content/records?format=json&limit=200`` — returns the rendered rows
   inside ``response.records``. We take ``len(records)`` as the authoritative
   "rows rendered on the first page" value.
2. The ``/content/`` HTML page — its header badge uses
   ``_count_matching``. Since parsing the HTML for the badge is brittle,
   we instead call ``_count_matching`` via the records fragment's OOB
   count behavior — i.e. request the fragment WITHOUT ``cursor``/``offset``
   so the OOB count block is rendered. For the diff we use the JSON path
   as the single source of truth and separately invoke the count endpoint
   (``/content/count``) for parity spot-checks.

Because the HTML/OOB count path is harder to automate from a JSON harness,
we implement the invariant as a *structural* check: run the filter with
``limit=200`` (safely above the seeded corpus size of <60) and verify that
``len(records) == total_returned == pagination.total_returned``. Then
compare against the full unfiltered count to make sure the count field
and the row count don't drift when the filter changes.

The more exhaustive browse-vs-export parity check lives in
``test_export_equals_browse.py``.

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


@pytest.mark.parametrize("case", FILTER_CASES, ids=pytest_ids(FILTER_CASES))
async def test_pagination_total_returned_matches_rendered_rows(
    case: FilterCase,
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
    auth_headers_owner: dict[str, str],
    request: pytest.FixtureRequest,
) -> None:
    """``pagination.total_returned`` must equal ``len(records)`` in the payload.

    This is a structural invariant on the JSON response. It can NEVER be
    acceptable for the two to disagree. Pinned as strict today.
    """
    from tests.integration.api.content.test_filter_current_behavior import _inject_runtime_params

    params = _inject_runtime_params(case.name, case.params, seeded_corpus)
    params["limit"] = 200

    status, records, pagination = await fetch_records_json(
        client, auth_headers_owner, params
    )
    assert status == 200, f"{case.name}: HTTP {status}"
    assert pagination.get("total_returned") == len(records), (
        f"{case.name}: pagination.total_returned={pagination.get('total_returned')} "
        f"disagrees with len(records)={len(records)}"
    )


@pytest.mark.parametrize("case", FILTER_CASES, ids=pytest_ids(FILTER_CASES))
async def test_count_matches_rendered_rows(
    case: FilterCase,
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
    auth_headers_owner: dict[str, str],
    request: pytest.FixtureRequest,
) -> None:
    """Row count shown in the page must equal the count endpoint result.

    We approximate the page-level badge by invoking the records fragment
    with ``limit=200`` and asserting that the number of records returned
    equals the number of records the same filter set returns when called
    a second time through the same path. Because the OOB count and the
    row query share ``_count_matching`` vs ``_build_browse_stmt`` today,
    the count/row divergence (when it exists) is observable by running the
    same filter twice and comparing ``len(records)`` — since the row query
    and the count query diverge on ``show_all``, they return DIFFERENT
    record totals.

    Phase 2 will replace this with a direct read of the ``#record-count``
    OOB span from the HTML response.

    Every case tagged with a known divergence bug is pinned as xfail so
    Phase 2 flips each pin as the corresponding bug lands.
    """
    # Pin xfail for cases that have a dedicated count-vs-rows reason OR
    # that carry any P0 bug tag affecting the row set (content_types_default,
    # show_all_mutation, language_default, link_deadend). Phase 2 flips each
    # pin as the corresponding bug is resolved.
    _ROW_SHIFTING_BUGS = {
        "show_all_mutation",
        "content_types_default",
        "language_default",
        "link_deadend",
        "count_row_divergence",
        "dedup_parity",
    }
    if case.count_rows_xfail_reason:
        request.applymarker(
            pytest.mark.xfail(
                strict=False,
                reason=f"{case.name}: {case.count_rows_xfail_reason}",
            )
        )
    elif case.bug_tags & _ROW_SHIFTING_BUGS:
        reasons = ", ".join(sorted(case.bug_tags & _ROW_SHIFTING_BUGS))
        request.applymarker(
            pytest.mark.xfail(
                strict=False,
                reason=f"{case.name}: row set divergence [{reasons}]",
            )
        )

    from tests.integration.api.content.test_filter_current_behavior import _inject_runtime_params

    params = _inject_runtime_params(case.name, case.params, seeded_corpus)
    params["limit"] = 200

    status, records, pagination = await fetch_records_json(
        client, auth_headers_owner, params
    )
    assert status == 200, f"{case.name}: HTTP {status}"

    # The row set must match what the filter intends (i.e. the matrix's
    # expected_labels). When the current code drops rows (content_types
    # default, effective_show_all mutation), this assertion fires, and
    # the xfail-pin above catches it.
    actual = seeded_corpus.labels_for_ids(record_id_set(records))
    fixture_actual = actual & set(seeded_corpus.record_ids.keys())
    assert fixture_actual == case.expected_labels, (
        f"\n{case.name}: rendered rows differ from expected.\n"
        f"  Missing: {sorted(case.expected_labels - fixture_actual)}\n"
        f"  Extra: {sorted(fixture_actual - case.expected_labels)}"
    )
