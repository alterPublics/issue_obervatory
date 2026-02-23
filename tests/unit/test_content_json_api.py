"""Unit tests for JSON API support in content_records_fragment endpoint.

Tests cover:
- format=json query parameter returns JSON response
- Accept: application/json header returns JSON response
- Default (no format param, no Accept header) returns HTML
- HTMX requests always return HTML even with Accept: application/json
- JSON response structure includes records array and pagination metadata
- Pagination metadata includes offset, limit, total_returned, next_cursor, has_more
- Empty result set returns empty array with correct pagination
- Records in JSON format contain all expected fields
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Env bootstrap
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==")

from issue_observatory.api.routes.content import content_records_fragment  # noqa: E402
from issue_observatory.core.models.users import User  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str = "researcher") -> User:
    """Create a minimal User ORM object for dependency injection."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.role = role
    user.is_active = True
    return user


def _make_mock_request(
    headers: dict[str, str] | None = None,
    has_templates: bool = True,
) -> MagicMock:
    """Create a mock FastAPI Request object."""
    request = MagicMock()
    request.headers = MagicMock()
    request.headers.get = lambda key, default="": (headers or {}).get(key, default)

    if has_templates:
        templates_mock = MagicMock()
        template_instance = MagicMock()
        template_instance.render.return_value = "<tr>mock row</tr>"
        templates_mock.get_template.return_value = template_instance
        request.app.state.templates = templates_mock
    else:
        request.app.state.templates = None

    return request


def _make_content_record_orm(
    record_id: uuid.UUID | None = None,
    platform: str = "reddit",
    arena: str = "social_media",
    title: str = "Test Post",
    text: str = "Test content",
    author: str = "test_author",
    published_at: datetime | None = None,
) -> MagicMock:
    """Create a mock UniversalContentRecord ORM object."""
    if record_id is None:
        record_id = uuid.uuid4()
    if published_at is None:
        published_at = datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc)

    record = MagicMock()
    record.id = record_id
    record.platform = platform
    record.arena = arena
    record.content_type = "post"
    record.title = title
    record.text_content = text
    record.author_display_name = author
    record.author_platform_id = "author_123"
    record.url = f"https://example.com/{record_id}"
    record.published_at = published_at
    record.collected_at = datetime(2024, 1, 15, 13, 0, tzinfo=timezone.utc)
    record.language = "da"
    record.engagement_score = 42
    record.search_terms_matched = ["test", "example"]
    record.collection_run_id = uuid.uuid4()
    record.raw_metadata = {"source": "test"}
    record._browse_mode = "batch"
    return record


def _make_db_with_records(records: list[MagicMock]) -> MagicMock:
    """Create a mock AsyncSession that returns the given records."""
    # Create mapping-style results
    mapping_rows = []
    for record in records:
        mapping = {
            "UniversalContentRecord": record,
            "mode": record._browse_mode,
        }
        mapping_mock = MagicMock()
        mapping_mock.get.side_effect = lambda key, default=None: mapping.get(key, default)
        mapping_rows.append(mapping_mock)

    result_mock = MagicMock()
    mappings_mock = MagicMock()
    mappings_mock.all.return_value = mapping_rows
    result_mock.mappings.return_value = mappings_mock

    db = MagicMock()
    db.execute = AsyncMock(return_value=result_mock)
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestContentRecordsJsonAPI:
    @pytest.mark.asyncio
    async def test_format_json_param_returns_json_response(self) -> None:
        """When format=json query parameter is provided, returns JSONResponse."""
        request = _make_mock_request()
        db = _make_db_with_records([])
        user = _make_user()

        response = await content_records_fragment(
            request=request,
            db=db,
            current_user=user,
            format="json",
        )

        assert response.status_code == 200
        assert response.media_type == "application/json"
        # Parse the response body
        import json
        body = json.loads(response.body.decode("utf-8"))
        assert "records" in body
        assert "pagination" in body

    @pytest.mark.asyncio
    async def test_accept_json_header_returns_json_response(self) -> None:
        """When Accept: application/json header is provided, returns JSONResponse."""
        request = _make_mock_request(headers={"accept": "application/json"})
        db = _make_db_with_records([])
        user = _make_user()

        response = await content_records_fragment(
            request=request,
            db=db,
            current_user=user,
        )

        assert response.status_code == 200
        assert response.media_type == "application/json"

    @pytest.mark.asyncio
    async def test_default_returns_html_response(self) -> None:
        """When no format param and no Accept header, returns HTMLResponse."""
        request = _make_mock_request()
        db = _make_db_with_records([])
        user = _make_user()

        response = await content_records_fragment(
            request=request,
            db=db,
            current_user=user,
        )

        assert response.status_code == 200
        assert "text/html" in response.media_type

    @pytest.mark.asyncio
    async def test_htmx_request_always_returns_html(self) -> None:
        """HTMX requests return HTML even with Accept: application/json."""
        request = _make_mock_request(headers={
            "hx-request": "true",
            "accept": "application/json",
        })
        db = _make_db_with_records([])
        user = _make_user()

        response = await content_records_fragment(
            request=request,
            db=db,
            current_user=user,
        )

        assert response.status_code == 200
        assert "text/html" in response.media_type

    @pytest.mark.asyncio
    async def test_json_response_structure(self) -> None:
        """JSON response contains records array and pagination metadata."""
        record1 = _make_content_record_orm(title="Post 1")
        record2 = _make_content_record_orm(title="Post 2")

        request = _make_mock_request()
        db = _make_db_with_records([record1, record2])
        user = _make_user()

        response = await content_records_fragment(
            request=request,
            db=db,
            current_user=user,
            format="json",
            limit=50,
        )

        import json
        body = json.loads(response.body.decode("utf-8"))

        # Check top-level structure
        assert "records" in body
        assert "pagination" in body
        assert isinstance(body["records"], list)
        assert isinstance(body["pagination"], dict)

        # Check pagination metadata
        pagination = body["pagination"]
        assert "offset" in pagination
        assert "limit" in pagination
        assert "total_returned" in pagination
        assert "next_cursor" in pagination
        assert "has_more" in pagination

        # Verify counts
        assert len(body["records"]) == 2
        assert pagination["total_returned"] == 2
        assert pagination["limit"] == 50

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_array(self) -> None:
        """Empty result set returns empty records array with correct pagination."""
        request = _make_mock_request()
        db = _make_db_with_records([])
        user = _make_user()

        response = await content_records_fragment(
            request=request,
            db=db,
            current_user=user,
            format="json",
        )

        import json
        body = json.loads(response.body.decode("utf-8"))

        assert body["records"] == []
        assert body["pagination"]["total_returned"] == 0
        assert body["pagination"]["has_more"] is False
        assert body["pagination"]["next_cursor"] is None

    @pytest.mark.asyncio
    async def test_json_record_fields(self) -> None:
        """JSON records contain all expected fields."""
        record_id = uuid.uuid4()
        run_id = uuid.uuid4()
        published_at = datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc)

        record = _make_content_record_orm(
            record_id=record_id,
            platform="reddit",
            arena="social_media",
            title="Test Title",
            text="Test content text",
            author="test_user",
            published_at=published_at,
        )
        record.collection_run_id = run_id

        request = _make_mock_request()
        db = _make_db_with_records([record])
        user = _make_user()

        response = await content_records_fragment(
            request=request,
            db=db,
            current_user=user,
            format="json",
        )

        import json
        body = json.loads(response.body.decode("utf-8"))

        assert len(body["records"]) == 1
        rec = body["records"][0]

        # Check all expected fields are present
        assert rec["id"] == str(record_id)
        assert rec["platform"] == "reddit"
        assert rec["arena"] == "social_media"
        assert rec["content_type"] == "post"
        assert rec["title"] == "Test Title"
        assert rec["text_content"] == "Test content text"
        assert rec["author_display_name"] == "test_user"
        assert rec["author_platform_id"] == "author_123"
        assert rec["url"] == f"https://example.com/{record_id}"
        assert rec["published_at"] == published_at.isoformat()
        assert rec["language"] == "da"
        assert rec["engagement_score"] == 42
        assert rec["search_terms_matched"] == ["test", "example"]
        assert rec["collection_run_id"] == str(run_id)
        assert rec["mode"] == "batch"
        assert rec["raw_metadata"] == {"source": "test"}

    @pytest.mark.asyncio
    async def test_offset_cap_returns_empty_json(self) -> None:
        """When offset >= 2000, returns empty JSON result."""
        request = _make_mock_request()
        db = _make_db_with_records([])
        user = _make_user()

        response = await content_records_fragment(
            request=request,
            db=db,
            current_user=user,
            format="json",
            offset=2000,
        )

        import json
        body = json.loads(response.body.decode("utf-8"))

        assert body["records"] == []
        assert body["pagination"]["total_returned"] == 0
        assert body["pagination"]["has_more"] is False

    @pytest.mark.asyncio
    async def test_accept_text_html_returns_html(self) -> None:
        """Accept: text/html header returns HTML response."""
        request = _make_mock_request(headers={"accept": "text/html"})
        db = _make_db_with_records([])
        user = _make_user()

        response = await content_records_fragment(
            request=request,
            db=db,
            current_user=user,
        )

        assert response.status_code == 200
        assert "text/html" in response.media_type

    @pytest.mark.asyncio
    async def test_format_param_takes_precedence_over_accept_header(self) -> None:
        """format=json query parameter takes precedence over Accept header."""
        request = _make_mock_request(headers={"accept": "text/html"})
        db = _make_db_with_records([])
        user = _make_user()

        response = await content_records_fragment(
            request=request,
            db=db,
            current_user=user,
            format="json",
        )

        assert response.status_code == 200
        assert response.media_type == "application/json"
