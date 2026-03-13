"""Unit tests for the comments-config CRUD endpoints on ProjectRouter.

Tests cover:
- GET /projects/{project_id}/comments-config returns empty dict for new project
- PATCH creates a platform config with valid data
- PATCH updates (deep-merges) an existing platform config
- PATCH rejects unknown platforms (400)
- PATCH rejects invalid mode values (400)
- PATCH validates post_urls format when mode=post_urls
- PATCH rejects post_urls that are not a list
- PATCH rejects post_urls entries that are not http URLs
- DELETE removes a platform config entry
- DELETE on a platform with no existing config returns 404
- Deep-merge preserves other platforms when updating one platform
- comments_config persists correctly on the Project model after multiple patches

All external dependencies (DB session, auth) are mocked via MagicMock/AsyncMock.
No live PostgreSQL instance or network connection is required.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Env bootstrap — must run before any application module is imported.
#
# CREDENTIAL_ENCRYPTION_KEY must be a real Fernet key; Settings validates the
# format at construction time.  We generate one at bootstrap instead of using
# a hardcoded placeholder so that the import of routes/projects.py (which
# transitively imports core/database.py and calls get_settings()) succeeds.
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault(
    "SECRET_KEY",
    "test-secret-key-for-unit-tests-must-be-32-chars!",
)
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost/test_observatory",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

if "CREDENTIAL_ENCRYPTION_KEY" not in os.environ:
    # Only import Fernet when we actually need to generate the key so that the
    # import stays cheap for environments where the key is already set via .env.
    from cryptography.fernet import Fernet

    os.environ["CREDENTIAL_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

from issue_observatory.api.routes.projects import (
    delete_comments_config,
    get_comments_config,
    patch_comments_config,
)
from issue_observatory.core.models.project import Project
from issue_observatory.core.models.users import User

# ---------------------------------------------------------------------------
# Constants mirrored from the route module (kept in sync manually so tests
# are self-contained and do not import private names).
# ---------------------------------------------------------------------------

_COMMENT_CAPABLE_PLATFORMS = {
    "reddit",
    "bluesky",
    "youtube",
    "tiktok",
    "facebook",
    "instagram",
}

_VALID_COMMENT_MODES = {"search_terms", "source_list_actors", "post_urls"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str = "researcher") -> User:
    """Return a minimal mock User for dependency injection."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.role = role
    user.is_active = True
    return user


def _make_project(
    owner_id: uuid.UUID | None = None,
    comments_config: dict | None = None,
) -> Project:
    """Return a minimal mock Project with optional pre-populated comments_config."""
    project = MagicMock(spec=Project)
    project.id = uuid.uuid4()
    project.owner_id = owner_id or uuid.uuid4()
    project.comments_config = comments_config if comments_config is not None else {}
    return project


def _make_db(project: Project) -> AsyncMock:
    """Return a mock AsyncSession whose execute() returns the given project.

    The mock supports the ``select(Project).where(...)`` pattern used by
    ``_verify_project_ownership``.
    """
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = project

    db = AsyncMock()
    db.execute = AsyncMock(return_value=scalar_result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/comments-config
# ---------------------------------------------------------------------------


class TestGetCommentsConfig:
    @pytest.mark.asyncio
    async def test_returns_empty_dict_for_new_project(self) -> None:
        """GET returns {} when comments_config has not been set yet."""
        user = _make_user()
        project = _make_project(owner_id=user.id, comments_config={})
        db = _make_db(project)

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(return_value=project),
        ):
            response = await get_comments_config(
                project_id=project.id,
                db=db,
                current_user=user,
            )

        assert response.status_code == 200
        import json

        body = json.loads(response.body)
        assert body == {}

    @pytest.mark.asyncio
    async def test_returns_existing_config_for_project(self) -> None:
        """GET returns the full comments_config dict already stored on the project."""
        user = _make_user()
        existing_config = {
            "reddit": {
                "enabled": True,
                "mode": "search_terms",
                "search_terms": ["klimakrisen"],
                "max_comments_per_post": 50,
            }
        }
        project = _make_project(owner_id=user.id, comments_config=existing_config)
        db = _make_db(project)

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(return_value=project),
        ):
            response = await get_comments_config(
                project_id=project.id,
                db=db,
                current_user=user,
            )

        import json

        body = json.loads(response.body)
        assert body == existing_config

    @pytest.mark.asyncio
    async def test_returns_404_for_nonexistent_project(self) -> None:
        """GET propagates 404 when _verify_project_ownership raises HTTPException."""
        user = _make_user()
        project_id = uuid.uuid4()
        db = AsyncMock()

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(
                side_effect=HTTPException(status_code=404, detail="Not found")
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_comments_config(
                    project_id=project_id,
                    db=db,
                    current_user=user,
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_403_for_non_owner(self) -> None:
        """GET propagates 403 when the user does not own the project."""
        user = _make_user()
        project_id = uuid.uuid4()
        db = AsyncMock()

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(
                side_effect=HTTPException(status_code=403, detail="Forbidden")
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_comments_config(
                    project_id=project_id,
                    db=db,
                    current_user=user,
                )

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# PATCH /projects/{project_id}/comments-config/{platform_name}
# ---------------------------------------------------------------------------


class TestPatchCommentsConfig:
    @pytest.mark.asyncio
    async def test_creates_new_platform_config_with_valid_data(self) -> None:
        """PATCH with a valid payload on an empty project populates comments_config."""
        user = _make_user()
        project = _make_project(owner_id=user.id, comments_config={})
        db = _make_db(project)

        payload = {
            "enabled": True,
            "mode": "search_terms",
            "search_terms": ["klimakrisen"],
            "max_comments_per_post": 50,
            "depth": 0,
        }

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(return_value=project),
        ):
            response = await patch_comments_config(
                project_id=project.id,
                platform_name="reddit",
                payload=payload,
                db=db,
                current_user=user,
            )

        assert response.status_code == 200
        import json

        body = json.loads(response.body)
        assert body["platform"] == "reddit"
        section = body["comments_config_section"]
        assert section["enabled"] is True
        assert section["mode"] == "search_terms"
        assert section["search_terms"] == ["klimakrisen"]

    @pytest.mark.asyncio
    async def test_updates_existing_platform_config(self) -> None:
        """PATCH merges new fields into an already-existing platform section."""
        user = _make_user()
        project = _make_project(
            owner_id=user.id,
            comments_config={"reddit": {"enabled": False, "mode": "search_terms"}},
        )
        db = _make_db(project)

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(return_value=project),
        ):
            response = await patch_comments_config(
                project_id=project.id,
                platform_name="reddit",
                payload={"enabled": True, "max_comments_per_post": 25},
                db=db,
                current_user=user,
            )

        import json

        body = json.loads(response.body)
        section = body["comments_config_section"]
        # Updated field
        assert section["enabled"] is True
        # Pre-existing field preserved by merge
        assert section["mode"] == "search_terms"
        # Newly added field
        assert section["max_comments_per_post"] == 25

    @pytest.mark.asyncio
    async def test_rejects_unknown_platform_with_400(self) -> None:
        """PATCH raises 400 when the platform is not in _COMMENT_CAPABLE_PLATFORMS."""
        user = _make_user()
        project_id = uuid.uuid4()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await patch_comments_config(
                project_id=project_id,
                platform_name="snapchat",
                payload={"enabled": True, "mode": "search_terms"},
                db=db,
                current_user=user,
            )

        assert exc_info.value.status_code == 400
        assert "snapchat" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_rejects_all_unknown_platforms(self) -> None:
        """PATCH raises 400 for every platform outside _COMMENT_CAPABLE_PLATFORMS."""
        user = _make_user()
        project_id = uuid.uuid4()
        db = AsyncMock()

        for bad_platform in ("twitter", "linkedin", "telegram", "gab", ""):
            with pytest.raises(HTTPException) as exc_info:
                await patch_comments_config(
                    project_id=project_id,
                    platform_name=bad_platform,
                    payload={"enabled": True, "mode": "search_terms"},
                    db=db,
                    current_user=user,
                )
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_accepts_all_valid_platforms(self) -> None:
        """PATCH succeeds for every platform in _COMMENT_CAPABLE_PLATFORMS."""
        user = _make_user()

        for platform in _COMMENT_CAPABLE_PLATFORMS:
            project = _make_project(owner_id=user.id, comments_config={})
            db = _make_db(project)

            with patch(
                "issue_observatory.api.routes.projects._verify_project_ownership",
                new=AsyncMock(return_value=project),
            ):
                response = await patch_comments_config(
                    project_id=project.id,
                    platform_name=platform,
                    payload={"enabled": True, "mode": "search_terms"},
                    db=db,
                    current_user=user,
                )

            assert response.status_code == 200, (
                f"Expected 200 for valid platform '{platform}', got {response.status_code}"
            )

    @pytest.mark.asyncio
    async def test_rejects_invalid_mode_with_400(self) -> None:
        """PATCH raises 400 when the mode is not in _VALID_COMMENT_MODES."""
        user = _make_user()
        project_id = uuid.uuid4()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await patch_comments_config(
                project_id=project_id,
                platform_name="reddit",
                payload={"enabled": True, "mode": "all_posts"},
                db=db,
                current_user=user,
            )

        assert exc_info.value.status_code == 400
        assert "all_posts" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_rejects_every_invalid_mode(self) -> None:
        """PATCH raises 400 for each mode string outside _VALID_COMMENT_MODES."""
        user = _make_user()
        project_id = uuid.uuid4()
        db = AsyncMock()

        for bad_mode in ("hashtag", "trending", "batch", "live", ""):
            with pytest.raises(HTTPException) as exc_info:
                await patch_comments_config(
                    project_id=project_id,
                    platform_name="reddit",
                    payload={"mode": bad_mode},
                    db=db,
                    current_user=user,
                )
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_accepts_all_valid_modes(self) -> None:
        """PATCH succeeds for every mode in _VALID_COMMENT_MODES."""
        user = _make_user()

        for mode in _VALID_COMMENT_MODES:
            project = _make_project(owner_id=user.id, comments_config={})
            db = _make_db(project)

            with patch(
                "issue_observatory.api.routes.projects._verify_project_ownership",
                new=AsyncMock(return_value=project),
            ):
                response = await patch_comments_config(
                    project_id=project.id,
                    platform_name="youtube",
                    payload={"mode": mode},
                    db=db,
                    current_user=user,
                )

            assert response.status_code == 200, (
                f"Expected 200 for valid mode '{mode}', got {response.status_code}"
            )

    @pytest.mark.asyncio
    async def test_validates_post_urls_format_accepts_valid_http_urls(self) -> None:
        """PATCH accepts post_urls containing valid http/https URL strings."""
        user = _make_user()
        project = _make_project(owner_id=user.id, comments_config={})
        db = _make_db(project)

        valid_urls = [
            "https://www.reddit.com/r/denmark/comments/abc123/",
            "http://example.com/post/1",
        ]

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(return_value=project),
        ):
            response = await patch_comments_config(
                project_id=project.id,
                platform_name="reddit",
                payload={"mode": "post_urls", "post_urls": valid_urls},
                db=db,
                current_user=user,
            )

        assert response.status_code == 200
        import json

        body = json.loads(response.body)
        assert body["comments_config_section"]["post_urls"] == valid_urls

    @pytest.mark.asyncio
    async def test_validates_post_urls_rejects_non_http_entries(self) -> None:
        """PATCH raises 400 when a post_url entry does not start with 'http'."""
        user = _make_user()
        project_id = uuid.uuid4()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await patch_comments_config(
                project_id=project_id,
                platform_name="reddit",
                payload={
                    "mode": "post_urls",
                    "post_urls": ["ftp://bad-url.com/post"],
                },
                db=db,
                current_user=user,
            )

        assert exc_info.value.status_code == 400
        assert "ftp://bad-url.com/post" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_validates_post_urls_rejects_plain_strings(self) -> None:
        """PATCH raises 400 when a post_url entry is a plain string without a scheme."""
        user = _make_user()
        project_id = uuid.uuid4()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await patch_comments_config(
                project_id=project_id,
                platform_name="youtube",
                payload={"mode": "post_urls", "post_urls": ["not-a-url"]},
                db=db,
                current_user=user,
            )

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_validates_post_urls_rejects_non_list_value(self) -> None:
        """PATCH raises 400 when post_urls is not a list (e.g. a single string)."""
        user = _make_user()
        project_id = uuid.uuid4()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await patch_comments_config(
                project_id=project_id,
                platform_name="bluesky",
                payload={
                    "mode": "post_urls",
                    "post_urls": "https://bsky.app/profile/user/post/abc",
                },
                db=db,
                current_user=user,
            )

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_validates_post_urls_rejects_dict_entries(self) -> None:
        """PATCH raises 400 when a post_url entry is a dict instead of a string."""
        user = _make_user()
        project_id = uuid.uuid4()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await patch_comments_config(
                project_id=project_id,
                platform_name="youtube",
                payload={
                    "post_urls": [{"url": "https://youtube.com/watch?v=abc"}],
                },
                db=db,
                current_user=user,
            )

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_payload_raises_400(self) -> None:
        """PATCH raises 400 when the request body is an empty dict."""
        user = _make_user()
        project_id = uuid.uuid4()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await patch_comments_config(
                project_id=project_id,
                platform_name="reddit",
                payload={},
                db=db,
                current_user=user,
            )

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_deep_merge_preserves_other_platforms(self) -> None:
        """Patching one platform must not affect other platforms already in config."""
        user = _make_user()
        project = _make_project(
            owner_id=user.id,
            comments_config={
                "reddit": {"enabled": True, "mode": "search_terms"},
                "bluesky": {"enabled": True, "mode": "source_list_actors"},
            },
        )
        db = _make_db(project)

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(return_value=project),
        ):
            await patch_comments_config(
                project_id=project.id,
                platform_name="youtube",
                payload={"enabled": True, "mode": "search_terms"},
                db=db,
                current_user=user,
            )

        # The stored value must include all three platforms.
        stored = project.comments_config
        assert "reddit" in stored, "reddit config was lost after patching youtube"
        assert "bluesky" in stored, "bluesky config was lost after patching youtube"
        assert "youtube" in stored, "youtube config was not written"

        assert stored["reddit"]["enabled"] is True
        assert stored["bluesky"]["mode"] == "source_list_actors"

    @pytest.mark.asyncio
    async def test_deep_merge_preserves_unchanged_fields_in_same_platform(self) -> None:
        """Patching specific fields within a platform section preserves all others."""
        user = _make_user()
        initial_config = {
            "reddit": {
                "enabled": True,
                "mode": "search_terms",
                "search_terms": ["klimakrisen"],
                "max_comments_per_post": 100,
                "depth": 2,
            }
        }
        project = _make_project(owner_id=user.id, comments_config=initial_config)
        db = _make_db(project)

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(return_value=project),
        ):
            await patch_comments_config(
                project_id=project.id,
                platform_name="reddit",
                payload={"max_comments_per_post": 50},
                db=db,
                current_user=user,
            )

        stored = project.comments_config["reddit"]
        # Patched field updated
        assert stored["max_comments_per_post"] == 50
        # Unpatched fields preserved
        assert stored["mode"] == "search_terms"
        assert stored["search_terms"] == ["klimakrisen"]
        assert stored["depth"] == 2
        assert stored["enabled"] is True

    @pytest.mark.asyncio
    async def test_patch_commits_to_db(self) -> None:
        """PATCH calls db.commit() to persist the updated config."""
        user = _make_user()
        project = _make_project(owner_id=user.id, comments_config={})
        db = _make_db(project)

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(return_value=project),
        ):
            await patch_comments_config(
                project_id=project.id,
                platform_name="reddit",
                payload={"enabled": True, "mode": "search_terms"},
                db=db,
                current_user=user,
            )

        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_patch_returns_platform_name_in_response(self) -> None:
        """PATCH response body includes the 'platform' key with the correct name."""
        user = _make_user()
        project = _make_project(owner_id=user.id, comments_config={})
        db = _make_db(project)

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(return_value=project),
        ):
            response = await patch_comments_config(
                project_id=project.id,
                platform_name="tiktok",
                payload={"enabled": True, "mode": "search_terms"},
                db=db,
                current_user=user,
            )

        import json

        body = json.loads(response.body)
        assert body["platform"] == "tiktok"
        assert "comments_config_section" in body

    @pytest.mark.asyncio
    async def test_patch_propagates_404_for_missing_project(self) -> None:
        """PATCH propagates 404 from _verify_project_ownership for an unknown project."""
        user = _make_user()
        project_id = uuid.uuid4()
        db = AsyncMock()

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(
                side_effect=HTTPException(status_code=404, detail="Not found")
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await patch_comments_config(
                    project_id=project_id,
                    platform_name="reddit",
                    payload={"enabled": True},
                    db=db,
                    current_user=user,
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_patch_propagates_403_for_non_owner(self) -> None:
        """PATCH propagates 403 from _verify_project_ownership for a non-owner."""
        user = _make_user()
        project_id = uuid.uuid4()
        db = AsyncMock()

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(
                side_effect=HTTPException(status_code=403, detail="Forbidden")
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await patch_comments_config(
                    project_id=project_id,
                    platform_name="reddit",
                    payload={"enabled": True},
                    db=db,
                    current_user=user,
                )

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /projects/{project_id}/comments-config/{platform_name}
# ---------------------------------------------------------------------------


class TestDeleteCommentsConfig:
    @pytest.mark.asyncio
    async def test_delete_removes_platform_config(self) -> None:
        """DELETE removes the platform section from comments_config."""
        user = _make_user()
        project = _make_project(
            owner_id=user.id,
            comments_config={
                "reddit": {"enabled": True, "mode": "search_terms"},
            },
        )
        db = _make_db(project)

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(return_value=project),
        ):
            response = await delete_comments_config(
                project_id=project.id,
                platform_name="reddit",
                db=db,
                current_user=user,
            )

        assert response.status_code == 200
        import json

        body = json.loads(response.body)
        assert body["deleted"] is True
        assert body["platform"] == "reddit"
        assert "reddit" not in project.comments_config

    @pytest.mark.asyncio
    async def test_delete_commits_to_db(self) -> None:
        """DELETE calls db.commit() to persist the removal."""
        user = _make_user()
        project = _make_project(
            owner_id=user.id,
            comments_config={"bluesky": {"enabled": True}},
        )
        db = _make_db(project)

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(return_value=project),
        ):
            await delete_comments_config(
                project_id=project.id,
                platform_name="bluesky",
                db=db,
                current_user=user,
            )

        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_platform_raises_404(self) -> None:
        """DELETE raises 404 when the platform has no config entry in comments_config."""
        user = _make_user()
        project = _make_project(owner_id=user.id, comments_config={})
        db = _make_db(project)

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(return_value=project),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await delete_comments_config(
                    project_id=project.id,
                    platform_name="reddit",
                    db=db,
                    current_user=user,
                )

        assert exc_info.value.status_code == 404
        assert "reddit" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_delete_preserves_other_platforms(self) -> None:
        """DELETE only removes the targeted platform; other platforms are untouched."""
        user = _make_user()
        project = _make_project(
            owner_id=user.id,
            comments_config={
                "reddit": {"enabled": True, "mode": "search_terms"},
                "youtube": {"enabled": True, "mode": "post_urls"},
                "bluesky": {"enabled": False},
            },
        )
        db = _make_db(project)

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(return_value=project),
        ):
            await delete_comments_config(
                project_id=project.id,
                platform_name="reddit",
                db=db,
                current_user=user,
            )

        stored = project.comments_config
        assert "reddit" not in stored, "reddit should have been removed"
        assert "youtube" in stored, "youtube config must not be affected"
        assert "bluesky" in stored, "bluesky config must not be affected"

    @pytest.mark.asyncio
    async def test_delete_propagates_404_for_missing_project(self) -> None:
        """DELETE propagates 404 when _verify_project_ownership cannot find project."""
        user = _make_user()
        project_id = uuid.uuid4()
        db = AsyncMock()

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(
                side_effect=HTTPException(status_code=404, detail="Not found")
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await delete_comments_config(
                    project_id=project_id,
                    platform_name="reddit",
                    db=db,
                    current_user=user,
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_propagates_403_for_non_owner(self) -> None:
        """DELETE propagates 403 when the user does not own the project."""
        user = _make_user()
        project_id = uuid.uuid4()
        db = AsyncMock()

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(
                side_effect=HTTPException(status_code=403, detail="Forbidden")
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await delete_comments_config(
                    project_id=project_id,
                    platform_name="reddit",
                    db=db,
                    current_user=user,
                )

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Config persistence on Project model
# ---------------------------------------------------------------------------


class TestCommentConfigPersistsOnModel:
    @pytest.mark.asyncio
    async def test_comments_config_written_to_project_attribute(self) -> None:
        """After PATCH, project.comments_config is updated in memory before commit."""
        user = _make_user()
        project = _make_project(owner_id=user.id, comments_config={})
        db = _make_db(project)

        payload = {
            "enabled": True,
            "mode": "search_terms",
            "search_terms": ["klimakrisen"],
            "actor_list_ids": [],
            "post_urls": [],
            "max_comments_per_post": 50,
            "depth": 0,
        }

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(return_value=project),
        ):
            await patch_comments_config(
                project_id=project.id,
                platform_name="reddit",
                payload=payload,
                db=db,
                current_user=user,
            )

        # The in-memory project object must reflect the change so that
        # SQLAlchemy's unit-of-work detects the mutation and persists it.
        assert project.comments_config["reddit"]["enabled"] is True
        assert project.comments_config["reddit"]["mode"] == "search_terms"
        assert project.comments_config["reddit"]["max_comments_per_post"] == 50
        assert project.comments_config["reddit"]["depth"] == 0

    @pytest.mark.asyncio
    async def test_comments_config_deleted_from_project_attribute(self) -> None:
        """After DELETE, project.comments_config no longer holds the platform key."""
        user = _make_user()
        project = _make_project(
            owner_id=user.id,
            comments_config={
                "reddit": {"enabled": True, "mode": "search_terms"},
                "youtube": {"enabled": True},
            },
        )
        db = _make_db(project)

        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(return_value=project),
        ):
            await delete_comments_config(
                project_id=project.id,
                platform_name="reddit",
                db=db,
                current_user=user,
            )

        assert "reddit" not in project.comments_config
        # Sibling platform remains
        assert "youtube" in project.comments_config

    @pytest.mark.asyncio
    async def test_sequential_patches_accumulate_platforms(self) -> None:
        """Three sequential PATCH calls accumulate config for all three platforms."""
        user = _make_user()
        project = _make_project(owner_id=user.id, comments_config={})
        db = _make_db(project)

        platforms = ["reddit", "bluesky", "youtube"]

        for platform in platforms:
            with patch(
                "issue_observatory.api.routes.projects._verify_project_ownership",
                new=AsyncMock(return_value=project),
            ):
                await patch_comments_config(
                    project_id=project.id,
                    platform_name=platform,
                    payload={"enabled": True, "mode": "search_terms"},
                    db=db,
                    current_user=user,
                )

        stored = project.comments_config
        for platform in platforms:
            assert platform in stored, f"Missing '{platform}' after sequential patches"
            assert stored[platform]["enabled"] is True

    @pytest.mark.asyncio
    async def test_full_lifecycle_patch_then_update_then_delete(self) -> None:
        """Full CRUD cycle: create, update, then delete a platform config."""
        user = _make_user()
        project = _make_project(owner_id=user.id, comments_config={})
        db = _make_db(project)

        # Step 1: create
        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(return_value=project),
        ):
            await patch_comments_config(
                project_id=project.id,
                platform_name="instagram",
                payload={"enabled": True, "mode": "source_list_actors"},
                db=db,
                current_user=user,
            )

        assert "instagram" in project.comments_config

        # Step 2: update
        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(return_value=project),
        ):
            await patch_comments_config(
                project_id=project.id,
                platform_name="instagram",
                payload={"max_comments_per_post": 200},
                db=db,
                current_user=user,
            )

        assert project.comments_config["instagram"]["max_comments_per_post"] == 200
        assert project.comments_config["instagram"]["mode"] == "source_list_actors"

        # Step 3: delete
        with patch(
            "issue_observatory.api.routes.projects._verify_project_ownership",
            new=AsyncMock(return_value=project),
        ):
            await delete_comments_config(
                project_id=project.id,
                platform_name="instagram",
                db=db,
                current_user=user,
            )

        assert "instagram" not in project.comments_config
