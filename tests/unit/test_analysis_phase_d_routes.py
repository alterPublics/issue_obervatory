"""Unit tests for Phase D analysis route additions.

Covers:
- GET /analysis/{run_id}/filtered-export  (H-04)
- GET /analysis/{run_id}/suggested-terms  (H-05)

All external dependencies (_get_run_or_raise, DB session, ContentExporter,
get_emergent_terms) are mocked.  No live PostgreSQL instance is required.
"""

from __future__ import annotations

import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Env bootstrap
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==")

from issue_observatory.api.routes.analysis import filtered_export, suggested_terms  # noqa: E402
from issue_observatory.core.models.users import User  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str = "researcher") -> User:
    """Build a minimal mock User."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.role = role
    user.is_active = True
    return user


def _make_mock_run(query_design_id: uuid.UUID | None = None) -> MagicMock:
    """Build a minimal mock CollectionRun."""
    run = MagicMock()
    run.id = uuid.uuid4()
    run.query_design_id = query_design_id
    return run


def _make_mock_db_for_export(orm_rows: list[Any] | None = None) -> Any:
    """Return a mock AsyncSession that returns orm_rows from execute().scalars().all()."""
    orm_rows = orm_rows or []
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = orm_rows
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    db = MagicMock()
    db.execute = AsyncMock(return_value=result_mock)
    return db


# ---------------------------------------------------------------------------
# H-04: filtered_export()
# ---------------------------------------------------------------------------


class TestFilteredExport:
    @pytest.mark.asyncio
    async def test_filtered_export_unknown_format_returns_400(self) -> None:
        """Requesting an unsupported format raises HTTPException 400."""
        run_id = uuid.uuid4()
        user = _make_user()
        db = _make_mock_db_for_export()

        with patch(
            "issue_observatory.api.routes.analysis._get_run_or_raise",
            new=AsyncMock(return_value=_make_mock_run()),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await filtered_export(
                    run_id=run_id,
                    db=db,
                    current_user=user,
                    format="unsupported_format",
                    platform=None,
                    arena=None,
                    date_from=None,
                    date_to=None,
                    search_term=None,
                    top_actors=None,
                    min_engagement=None,
                    limit=100,
                )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_filtered_export_returns_403_for_unauthorized_run(self) -> None:
        """When the user does not own the run, filtered_export raises 403."""
        run_id = uuid.uuid4()
        user = _make_user()
        db = _make_mock_db_for_export()

        with patch(
            "issue_observatory.api.routes.analysis._get_run_or_raise",
            new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await filtered_export(
                    run_id=run_id,
                    db=db,
                    current_user=user,
                    format="csv",
                    platform=None,
                    arena=None,
                    date_from=None,
                    date_to=None,
                    search_term=None,
                    top_actors=None,
                    min_engagement=None,
                    limit=100,
                )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_filtered_export_returns_404_for_nonexistent_run(self) -> None:
        """When the run does not exist, filtered_export raises 404."""
        run_id = uuid.uuid4()
        user = _make_user()
        db = _make_mock_db_for_export()

        with patch(
            "issue_observatory.api.routes.analysis._get_run_or_raise",
            new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await filtered_export(
                    run_id=run_id,
                    db=db,
                    current_user=user,
                    format="csv",
                    platform=None,
                    arena=None,
                    date_from=None,
                    date_to=None,
                    search_term=None,
                    top_actors=None,
                    min_engagement=None,
                    limit=100,
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_filtered_export_csv_content_disposition_header_set(self) -> None:
        """CSV export response has Content-Disposition: attachment header."""
        run_id = uuid.uuid4()
        user = _make_user()
        db = _make_mock_db_for_export(orm_rows=[])

        with patch(
            "issue_observatory.api.routes.analysis._get_run_or_raise",
            new=AsyncMock(return_value=_make_mock_run()),
        ):
            response = await filtered_export(
                run_id=run_id,
                db=db,
                current_user=user,
                format="csv",
                platform=None,
                arena=None,
                date_from=None,
                date_to=None,
                search_term=None,
                top_actors=None,
                min_engagement=None,
                limit=100,
            )

        content_disposition = response.headers.get("content-disposition", "")
        assert "attachment" in content_disposition

    @pytest.mark.asyncio
    async def test_filtered_export_ris_content_type_is_application_x_ris(self) -> None:
        """RIS export response uses the application/x-research-info-systems MIME type."""
        run_id = uuid.uuid4()
        user = _make_user()
        db = _make_mock_db_for_export(orm_rows=[])

        with patch(
            "issue_observatory.api.routes.analysis._get_run_or_raise",
            new=AsyncMock(return_value=_make_mock_run()),
        ):
            response = await filtered_export(
                run_id=run_id,
                db=db,
                current_user=user,
                format="ris",
                platform=None,
                arena=None,
                date_from=None,
                date_to=None,
                search_term=None,
                top_actors=None,
                min_engagement=None,
                limit=100,
            )

        assert "application/x-research-info-systems" in response.media_type

    @pytest.mark.asyncio
    async def test_filtered_export_bibtex_content_type_is_application_x_bibtex(self) -> None:
        """BibTeX export response uses the application/x-bibtex MIME type."""
        run_id = uuid.uuid4()
        user = _make_user()
        db = _make_mock_db_for_export(orm_rows=[])

        with patch(
            "issue_observatory.api.routes.analysis._get_run_or_raise",
            new=AsyncMock(return_value=_make_mock_run()),
        ):
            response = await filtered_export(
                run_id=run_id,
                db=db,
                current_user=user,
                format="bibtex",
                platform=None,
                arena=None,
                date_from=None,
                date_to=None,
                search_term=None,
                top_actors=None,
                min_engagement=None,
                limit=100,
            )

        assert "application/x-bibtex" in response.media_type

    @pytest.mark.asyncio
    async def test_filtered_export_platform_filter_accepted(self) -> None:
        """Passing a platform filter does not raise; the route accepts the parameter."""
        run_id = uuid.uuid4()
        user = _make_user()
        db = _make_mock_db_for_export(orm_rows=[])

        with patch(
            "issue_observatory.api.routes.analysis._get_run_or_raise",
            new=AsyncMock(return_value=_make_mock_run()),
        ):
            response = await filtered_export(
                run_id=run_id,
                db=db,
                current_user=user,
                format="csv",
                platform="bluesky",
                arena=None,
                date_from=None,
                date_to=None,
                search_term=None,
                top_actors=None,
                min_engagement=None,
                limit=100,
            )

        # With zero matching records the response is still valid.
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# H-05: suggested_terms()
# ---------------------------------------------------------------------------


class TestSuggestedTerms:
    @pytest.mark.asyncio
    async def test_suggested_terms_returns_list_with_required_keys(self) -> None:
        """suggested_terms() returns dicts with 'term', 'score', 'document_frequency'."""
        run_id = uuid.uuid4()
        user = _make_user()

        # Mock DB: no existing search terms.
        term_result_mock = MagicMock()
        term_result_mock.fetchall.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(return_value=term_result_mock)

        emergent_items = [
            {"term": "grøn energi", "score": 0.85, "document_frequency": 12},
            {"term": "CO2-afgift", "score": 0.72, "document_frequency": 8},
        ]

        with (
            patch(
                "issue_observatory.api.routes.analysis._get_run_or_raise",
                new=AsyncMock(return_value=_make_mock_run()),
            ),
            patch(
                "issue_observatory.api.routes.analysis.get_emergent_terms",
                new=AsyncMock(return_value=emergent_items),
            ),
        ):
            result = await suggested_terms(
                run_id=run_id,
                db=db,
                current_user=user,
                top_n=10,
                min_doc_frequency=2,
            )

        assert isinstance(result, list)
        assert len(result) > 0
        for item in result:
            assert "term" in item, "Missing 'term' key"
            assert "score" in item, "Missing 'score' key"
            assert "document_frequency" in item, "Missing 'document_frequency' key"

    @pytest.mark.asyncio
    async def test_suggested_terms_excludes_existing_search_terms(self) -> None:
        """Terms already in the query design are excluded from suggestions."""
        run_id = uuid.uuid4()
        user = _make_user()
        query_design_id = uuid.uuid4()
        run = _make_mock_run(query_design_id=query_design_id)

        # Mock DB: existing search term "klimaforandringer".
        existing_row = MagicMock()
        existing_row.__getitem__ = lambda self, idx: "klimaforandringer"
        term_result_mock = MagicMock()
        term_result_mock.fetchall.return_value = [("klimaforandringer",)]
        db = MagicMock()
        db.execute = AsyncMock(return_value=term_result_mock)

        emergent_items = [
            {"term": "klimaforandringer", "score": 0.95, "document_frequency": 50},
            {"term": "grøn energi", "score": 0.80, "document_frequency": 20},
        ]

        with (
            patch(
                "issue_observatory.api.routes.analysis._get_run_or_raise",
                new=AsyncMock(return_value=run),
            ),
            patch(
                "issue_observatory.api.routes.analysis.get_emergent_terms",
                new=AsyncMock(return_value=emergent_items),
            ),
        ):
            result = await suggested_terms(
                run_id=run_id,
                db=db,
                current_user=user,
                top_n=10,
                min_doc_frequency=2,
            )

        returned_terms = [item["term"] for item in result]
        assert "klimaforandringer" not in returned_terms, (
            "Existing search term 'klimaforandringer' must be excluded from suggestions"
        )

    @pytest.mark.asyncio
    async def test_suggested_terms_returns_404_for_nonexistent_run(self) -> None:
        """suggested_terms() propagates 404 when the run does not exist."""
        run_id = uuid.uuid4()
        user = _make_user()
        db = MagicMock()

        with patch(
            "issue_observatory.api.routes.analysis._get_run_or_raise",
            new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await suggested_terms(
                    run_id=run_id,
                    db=db,
                    current_user=user,
                    top_n=10,
                    min_doc_frequency=2,
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_suggested_terms_returns_403_for_unauthorized_run(self) -> None:
        """suggested_terms() propagates 403 when the user does not own the run."""
        run_id = uuid.uuid4()
        user = _make_user()
        db = MagicMock()

        with patch(
            "issue_observatory.api.routes.analysis._get_run_or_raise",
            new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await suggested_terms(
                    run_id=run_id,
                    db=db,
                    current_user=user,
                    top_n=10,
                    min_doc_frequency=2,
                )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_suggested_terms_returns_empty_list_gracefully_when_no_text(self) -> None:
        """When get_emergent_terms returns an empty list, suggested_terms returns []."""
        run_id = uuid.uuid4()
        user = _make_user()

        term_result_mock = MagicMock()
        term_result_mock.fetchall.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(return_value=term_result_mock)

        with (
            patch(
                "issue_observatory.api.routes.analysis._get_run_or_raise",
                new=AsyncMock(return_value=_make_mock_run()),
            ),
            patch(
                "issue_observatory.api.routes.analysis.get_emergent_terms",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await suggested_terms(
                run_id=run_id,
                db=db,
                current_user=user,
                top_n=10,
                min_doc_frequency=2,
            )

        assert result == []
