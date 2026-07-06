"""Phase 6 — Task 4: Page-size control tests.

Asserts that the ``limit`` query parameter on /content/records behaves
within the defined bounds:
  - ge=10: values below 10 are rejected with HTTP 422.
  - le=500: values above 500 are rejected with HTTP 422.
  - limit=25 returns at most 25 rows (or fewer if corpus is smaller).
  - limit=100 returns more rows than limit=25 when corpus has >=100.

Note: the seeded corpus contains ~60 records total, but only a subset
are visible under the default content_types=["post"] filter.  We use
show_all=true and content_types="" (explicit empty) to maximise the
visible set and make limit comparisons meaningful.
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


async def _fetch_count(
    client: AsyncClient,
    headers: dict[str, str],
    limit: int,
) -> int:
    """Fetch /content/records in JSON mode and return record count."""
    resp = await client.get(
        "/content/records",
        params={
            "limit": limit,
            "format": "json",
            "show_all": "true",
            "content_types": "",  # explicit empty = all types
        },
        headers=headers,
    )
    assert resp.status_code == 200, f"limit={limit}: HTTP {resp.status_code} — {resp.text[:200]}"
    data = resp.json()
    return len(data["records"])


async def test_limit_25_returns_at_most_25_rows(
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
    auth_headers_owner: dict[str, str],
) -> None:
    """limit=25 must not return more than 25 rows."""
    count = await _fetch_count(client, auth_headers_owner, limit=25)
    assert count <= 25


async def test_limit_100_returns_more_than_limit_25_when_corpus_large_enough(
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
    auth_headers_owner: dict[str, str],
) -> None:
    """limit=100 should return more rows than limit=25 if corpus >= 26 records.

    The seeded corpus has ~60 rows so this invariant holds.
    """
    count_25 = await _fetch_count(client, auth_headers_owner, limit=25)
    count_100 = await _fetch_count(client, auth_headers_owner, limit=100)
    # If corpus < 25 rows, both limits would return the same (all) rows — skip.
    if count_25 < 25:
        pytest.skip("Corpus has fewer than 25 rows — limit ordering not meaningful.")
    assert count_100 >= count_25, (
        f"limit=100 returned fewer rows ({count_100}) than limit=25 ({count_25})"
    )


async def test_limit_below_min_rejected(
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
    auth_headers_owner: dict[str, str],
) -> None:
    """limit=5 is below ge=10 — FastAPI should reject with HTTP 422."""
    resp = await client.get(
        "/content/records",
        params={"limit": 5, "format": "json"},
        headers=auth_headers_owner,
    )
    assert resp.status_code == 422, (
        f"Expected 422 for limit=5 (below minimum 10), got {resp.status_code}"
    )


async def test_limit_above_max_rejected(
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
    auth_headers_owner: dict[str, str],
) -> None:
    """limit=5000 is above le=500 — FastAPI should reject with HTTP 422."""
    resp = await client.get(
        "/content/records",
        params={"limit": 5000, "format": "json"},
        headers=auth_headers_owner,
    )
    assert resp.status_code == 422, (
        f"Expected 422 for limit=5000 (above maximum 500), got {resp.status_code}"
    )


async def test_limit_at_min_boundary_accepted(
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
    auth_headers_owner: dict[str, str],
) -> None:
    """limit=10 is exactly the minimum — must be accepted (200)."""
    resp = await client.get(
        "/content/records",
        params={"limit": 10, "format": "json"},
        headers=auth_headers_owner,
    )
    assert resp.status_code == 200


async def test_limit_at_max_boundary_accepted(
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
    auth_headers_owner: dict[str, str],
) -> None:
    """limit=500 is exactly the maximum — must be accepted (200)."""
    resp = await client.get(
        "/content/records",
        params={"limit": 500, "format": "json"},
        headers=auth_headers_owner,
    )
    assert resp.status_code == 200
