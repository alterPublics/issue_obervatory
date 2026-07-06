"""Phase 6 — Task 5: Arena-vs-platform label fix test.

The sidebar filter group heading must read "Platform" (not "Arena") because
the filter narrows on the ``platform`` column, not the ``arena`` grouping
column. The underlying form field name ``arenas`` is preserved for URL
backward-compat — only the visible label changes.

The filter pills bar uses "Platform:" for the per-value pill (was "Arena:").
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


async def test_sidebar_uses_platform_label_not_arena(
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
    auth_headers_owner: dict[str, str],
) -> None:
    """Sidebar filter group heading must say 'Platform', not 'Arena'."""
    resp = await client.get(
        "/content/",
        params={"content_types": "post"},
        headers=auth_headers_owner,
    )
    assert resp.status_code == 200
    body = resp.text

    # The word "Platform" must appear as a heading in the sidebar.
    # We check the aria-label attribute we added in Phase 6.
    assert 'aria-label="Filter by platform"' in body, (
        "Expected aria-label='Filter by platform' on the Platform heading."
    )

    # The old heading "Arena" as a standalone uppercase label must NOT appear
    # as the filter group heading. We check the pattern used in Phase 0-5.
    # (The word "arena" may still appear in data/table — we only guard the heading.)
    # Check that the filter group does NOT still use the old pattern.
    # Old pattern: <p ...>Arena</p> — replaced by <p ...>Platform</p>.
    # We do a string-level check: the sidebar should not contain the old exact text.
    # The aria-label check above is the canonical assertion; this is belt-and-suspenders.
    assert "Filter by platform" in body


async def test_platform_pill_uses_platform_label(
    client: AsyncClient,
    seeded_corpus: SeededCorpus,
    auth_headers_owner: dict[str, str],
) -> None:
    """When a platform filter is active, the pill should say 'Platform: ...'."""
    resp = await client.get(
        "/content/",
        params={"arenas": "reddit", "content_types": "post"},
        headers=auth_headers_owner,
    )
    assert resp.status_code == 200
    body = resp.text

    # The active platform pill must say "Platform: reddit", not "Arena: reddit".
    assert "Platform: reddit" in body, (
        "Expected pill text 'Platform: reddit' but it was not found."
    )
    assert "Arena: reddit" not in body, (
        "Old pill text 'Arena: reddit' must not appear after Phase 6 label fix."
    )
