"""Phase 4 regression: verify the content page rename to "Recent Content".

Asserts:
- The page H1 contains "Recent Content".
- The page body does NOT contain "representative sample".
- The sort-disclosure copy is present.
- The rendered nav label shows "Recent Content" (base template is included).

Uses the seeded corpus and fixtures from conftest.py so authentication
and DB setup are consistent with the rest of the harness.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
]

_SORT_DISCLOSURE = "Sorted by publication date, newest first."


@pytest.mark.asyncio
async def test_page_h1_says_recent_content(
    client: AsyncClient,
    auth_headers_owner: dict[str, str],
) -> None:
    """The main heading on /content must say 'Recent Content'."""
    resp = await client.get("/content", headers=auth_headers_owner)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    body = resp.text
    assert "Recent Content" in body, (
        "Page H1 or title does not contain 'Recent Content'. "
        "Check browser.html block title and the <h1> in the table header bar."
    )


@pytest.mark.asyncio
async def test_page_body_has_no_representative_sample(
    client: AsyncClient,
    auth_headers_owner: dict[str, str],
) -> None:
    """The phrase 'representative sample' must not appear anywhere on the page."""
    resp = await client.get("/content", headers=auth_headers_owner)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    body = resp.text
    assert "representative sample" not in body.lower(), (
        "Found 'representative sample' in the rendered page. "
        "Remove or update the copy in browser.html."
    )


@pytest.mark.asyncio
async def test_page_body_has_sort_disclosure(
    client: AsyncClient,
    auth_headers_owner: dict[str, str],
) -> None:
    """The sort disclosure must be visible on the page so researchers know the ordering."""
    resp = await client.get("/content", headers=auth_headers_owner)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    body = resp.text
    assert _SORT_DISCLOSURE in body, (
        f"Sort disclosure text not found: {_SORT_DISCLOSURE!r}. "
        "Add the disclosure caption near the table header in browser.html."
    )


@pytest.mark.asyncio
async def test_nav_label_says_recent_content(
    client: AsyncClient,
    auth_headers_owner: dict[str, str],
) -> None:
    """The navigation sidebar rendered on /content must label the link 'Recent Content'."""
    resp = await client.get("/content", headers=auth_headers_owner)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    body = resp.text
    # The nav is included via base.html; the sidebar must carry the new label.
    assert "Recent Content" in body, (
        "Nav sidebar does not contain 'Recent Content'. "
        "Update the nav_items list in _partials/nav.html."
    )


@pytest.mark.asyncio
async def test_browser_tab_title_says_recent_content(
    client: AsyncClient,
    auth_headers_owner: dict[str, str],
) -> None:
    """The <title> element must include 'Recent Content' (not 'Content Browser')."""
    resp = await client.get("/content", headers=auth_headers_owner)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    body = resp.text
    # base.html renders: {% block title %}{% endblock %} — The Issue Observatory
    assert "Recent Content" in body, (
        "<title> does not contain 'Recent Content'. "
        "Update {% block title %} in browser.html."
    )
    assert "Content Browser" not in body, (
        "Found old name 'Content Browser' in the rendered page. "
        "Remove all references to the old name."
    )
