"""Phase-2 harness: ``/content/export`` row IDs == ``/content/records`` row IDs.

Phase 2 unified the export and browse filter stacks via a shared helper
(``ContentFilterSpec`` + ``build_browse_stmt``). The unconditional xfail that
was in place during Phase 0 has been removed.

Export format
-------------
We use ``format=json`` for both endpoints. The JSON payload is the simplest
to diff and uses the same record-to-dict transformer underneath.

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


def _export_supported_params(params: dict) -> dict:
    """Return the params to send to ``/content/export``.

    Phase 2: export accepts all browse parameters (unified via shared helper).
    """
    return params


@pytest.mark.parametrize("case", FILTER_CASES, ids=pytest_ids(FILTER_CASES))
async def test_export_row_ids_match_browse(
    case: FilterCase,
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
    auth_headers_owner: dict[str, str],
    request: pytest.FixtureRequest,
) -> None:
    """Export and browse must return the same record IDs for the same spec.

    Phase 2 fixed the export/browse divergence by routing both through
    the shared ``ContentFilterSpec`` helper. This test is now unconditional —
    no xfail markers. If a case has a dedicated ``export_browse_xfail_reason``
    we still apply it (safety net for unexpected edge cases).
    """
    # Apply any case-specific xfail reason (safety net only — no blanket xfail).
    if case.export_browse_xfail_reason:
        request.applymarker(
            pytest.mark.xfail(strict=False, reason=case.export_browse_xfail_reason)
        )

    from tests.integration.api.content.test_filter_current_behavior import _inject_runtime_params

    params = _inject_runtime_params(case.name, case.params, seeded_corpus)
    params["limit"] = 200

    # Browse path
    browse_status, browse_records, _ = await fetch_records_json(
        client, auth_headers_owner, params
    )
    assert browse_status == 200, f"{case.name}: browse HTTP {browse_status}"

    # Export path — JSON format. NOTE: /content/export/json emits NDJSON
    # (newline-delimited), not a JSON object. We parse the NDJSON body
    # directly here so the test surface is independent of a specific
    # content-type header.
    export_params = {**_export_supported_params(params), "format": "json"}
    # Strip None values as fetch_records_json does.
    export_params = {k: v for k, v in export_params.items() if v is not None}
    resp = await client.get(
        "/content/export", params=export_params, headers=auth_headers_owner
    )
    assert resp.status_code == 200, (
        f"{case.name}: export HTTP {resp.status_code} — {resp.text[:200]}"
    )

    export_ids: set[str] = set()
    for line in resp.text.splitlines():
        line = line.strip()
        if not line:
            continue
        import json

        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "id" in obj:
            export_ids.add(str(obj["id"]))

    browse_ids = record_id_set(browse_records)

    browse_labels = seeded_corpus.labels_for_ids(browse_ids) & set(
        seeded_corpus.record_ids.keys()
    )
    export_labels = seeded_corpus.labels_for_ids(export_ids) & set(
        seeded_corpus.record_ids.keys()
    )

    assert browse_labels == export_labels, (
        f"\n{case.name}: browse vs export row-set mismatch.\n"
        f"  In browse only: {sorted(browse_labels - export_labels)}\n"
        f"  In export only: {sorted(export_labels - browse_labels)}"
    )
