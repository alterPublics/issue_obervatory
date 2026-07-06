"""Phase 6 — Task 3: 20-run cap disclosure test.

Asserts that the rendered content browser page contains the caption disclosing
the 20-run cap on the Collection Run dropdown, with a link to /collections/.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient  # noqa: TC002

from tests.integration.api.content.conftest import SeededCorpus  # noqa: TC001

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
]


async def test_run_cap_disclosure_caption_present(
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
    auth_headers_owner: dict[str, str],
) -> None:
    """The content browser must show the 20-most-recent-runs caption.

    Asserts:
    1. The phrase '20 most recent runs' appears in the page HTML.
    2. A link to /collections/ appears near the caption.
    """
    resp = await client.get(
        "/content/",
        params={"content_types": "post"},
        headers=auth_headers_owner,
    )
    assert resp.status_code == 200, f"HTTP {resp.status_code}"
    body = resp.text

    assert "20 most recent runs" in body, (
        "Expected '20 most recent runs' caption below Collection Run dropdown — not found."
    )
    assert "/collections/" in body, (
        "Expected link to /collections/ in the run-cap caption — not found."
    )
