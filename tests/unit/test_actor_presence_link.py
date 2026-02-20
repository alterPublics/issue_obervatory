"""Unit test for YF-16: Actor platform presence inline add link.

Tests that the _render_actor_list_item function includes a link to configure
platform presences that:
- Opens in a new tab (target="_blank")
- Links to the actor detail page with #presences fragment
- Contains appropriate text and styling
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Env bootstrap — must happen before any application module imports.
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test_observatory")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from issue_observatory.api.routes.query_designs import _render_actor_list_item  # noqa: E402


def test_render_actor_list_item_includes_presences_link() -> None:
    """Verify actor list item includes 'Add presences' link with correct attributes."""
    # Create a mock actor (no DB connection needed)
    actor_id = uuid.uuid4()
    design_id = uuid.uuid4()

    actor = MagicMock()
    actor.id = actor_id
    actor.canonical_name = "Test Actor"
    actor.actor_type = "person"

    # Render the HTML fragment
    html = _render_actor_list_item(
        member_id=actor_id,
        design_id=design_id,
        actor=actor,
    )

    # Verify the fragment contains the presences link
    assert f'/actors/{actor_id}#presences' in html, "Should link to actor detail with #presences anchor"
    assert 'target="_blank"' in html, "Should open in new tab"
    assert 'Add presences' in html, "Should contain 'Add presences' text"

    # Verify styling classes
    assert 'text-blue-600' in html, "Should use blue link color"
    assert 'hover:text-blue-800' in html, "Should have hover state"

    # Verify it includes the link icon (SVG path for link icon)
    assert 'M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656' in html, \
        "Should include link icon SVG"

    # Verify the separator pipe character is present
    assert '<span class="text-gray-300 flex-shrink-0">|</span>' in html, \
        "Should include separator between Profile and Add presences links"


def test_render_actor_list_item_still_includes_profile_link() -> None:
    """Verify actor list item still includes the original Profile link."""
    actor_id = uuid.uuid4()
    design_id = uuid.uuid4()

    actor = MagicMock()
    actor.id = actor_id
    actor.canonical_name = "Another Actor"
    actor.actor_type = "organization"

    html = _render_actor_list_item(
        member_id=actor_id,
        design_id=design_id,
        actor=actor,
    )

    # Verify the Profile link still exists
    assert f'href="/actors/{actor_id}"' in html, "Should still include Profile link"
    assert 'View actor profile' in html, "Should include Profile link title"
    assert '>Profile</a>' in html, "Should include Profile link text"
