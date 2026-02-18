"""Unit tests for the shared SQL filter-builder (analysis/_filters.py).

Tests cover:
- build_content_filters(): with no args, with query_design_id, with run_id,
  with both, with arena/platform, with date range.
- build_content_where(): correct WHERE prefix, duplicate exclusion always present.
- Duplicate exclusion clause is always present regardless of other arguments.
- Table alias is correctly prepended when provided.
- Bind parameters are correctly populated in the mutable params dict.

No database or network connection is required.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Env bootstrap
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==")

from issue_observatory.analysis._filters import (  # noqa: E402
    build_content_filters,
    build_content_where,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DUPLICATE_EXCLUSION = "(raw_metadata->>'duplicate_of') IS NULL"


# ---------------------------------------------------------------------------
# build_content_filters
# ---------------------------------------------------------------------------


class TestBuildContentFilters:
    def test_no_args_returns_list_with_one_element(self) -> None:
        """build_content_filters() with no optional args returns exactly one clause
        — the duplicate exclusion predicate — and leaves params empty."""
        params: dict[str, Any] = {}
        clauses = build_content_filters(None, None, None, None, None, None, params)
        assert isinstance(clauses, list)
        assert len(clauses) == 1
        assert params == {}

    def test_no_args_clause_is_duplicate_exclusion(self) -> None:
        """The single clause returned when no args are given is the duplicate
        exclusion predicate."""
        params: dict[str, Any] = {}
        clauses = build_content_filters(None, None, None, None, None, None, params)
        assert clauses[0] == _DUPLICATE_EXCLUSION

    def test_query_design_id_adds_clause_and_param(self) -> None:
        """query_design_id generates a query_design_id = :query_design_id predicate
        and inserts the stringified UUID into params."""
        params: dict[str, Any] = {}
        qd_id = uuid.uuid4()
        clauses = build_content_filters(qd_id, None, None, None, None, None, params)
        combined = " ".join(clauses)
        assert "query_design_id = :query_design_id" in combined
        assert params.get("query_design_id") == str(qd_id)

    def test_run_id_adds_clause_and_param(self) -> None:
        """run_id generates a collection_run_id = :run_id predicate and inserts
        the stringified UUID into params."""
        params: dict[str, Any] = {}
        run_id = uuid.uuid4()
        clauses = build_content_filters(None, run_id, None, None, None, None, params)
        combined = " ".join(clauses)
        assert "collection_run_id = :run_id" in combined
        assert params.get("run_id") == str(run_id)

    def test_both_query_design_id_and_run_id_add_two_extra_clauses(self) -> None:
        """Supplying both query_design_id and run_id produces three clauses total:
        one per filter plus the always-present duplicate exclusion clause."""
        params: dict[str, Any] = {}
        qd_id = uuid.uuid4()
        run_id = uuid.uuid4()
        clauses = build_content_filters(qd_id, run_id, None, None, None, None, params)
        assert len(clauses) == 3  # qd + run_id + duplicate exclusion

    def test_duplicate_exclusion_always_present_with_query_design_id(self) -> None:
        """Duplicate exclusion clause is present even when query_design_id is provided."""
        params: dict[str, Any] = {}
        clauses = build_content_filters(uuid.uuid4(), None, None, None, None, None, params)
        assert any(_DUPLICATE_EXCLUSION in c for c in clauses)

    def test_duplicate_exclusion_always_present_with_run_id(self) -> None:
        """Duplicate exclusion clause is present even when run_id is provided."""
        params: dict[str, Any] = {}
        clauses = build_content_filters(None, uuid.uuid4(), None, None, None, None, params)
        assert any(_DUPLICATE_EXCLUSION in c for c in clauses)

    def test_duplicate_exclusion_always_present_with_all_filters(self) -> None:
        """Duplicate exclusion clause is present when all filter args are supplied."""
        params: dict[str, Any] = {}
        date_from = datetime(2026, 1, 1, tzinfo=timezone.utc)
        date_to = datetime(2026, 1, 31, tzinfo=timezone.utc)
        clauses = build_content_filters(
            uuid.uuid4(), uuid.uuid4(), "news_media", "bluesky", date_from, date_to, params
        )
        assert any(_DUPLICATE_EXCLUSION in c for c in clauses)

    def test_arena_filter_adds_predicate(self) -> None:
        """arena filter adds an arena = :arena predicate and populates params."""
        params: dict[str, Any] = {}
        clauses = build_content_filters(None, None, "news_media", None, None, None, params)
        combined = " ".join(clauses)
        assert "arena = :arena" in combined
        assert params.get("arena") == "news_media"

    def test_platform_filter_adds_predicate(self) -> None:
        """platform filter adds a platform = :platform predicate and populates params."""
        params: dict[str, Any] = {}
        clauses = build_content_filters(None, None, None, "bluesky", None, None, params)
        combined = " ".join(clauses)
        assert "platform = :platform" in combined
        assert params.get("platform") == "bluesky"

    def test_date_from_adds_published_at_gte_clause(self) -> None:
        """date_from adds a published_at >= :date_from clause."""
        params: dict[str, Any] = {}
        date_from = datetime(2026, 1, 1, tzinfo=timezone.utc)
        clauses = build_content_filters(None, None, None, None, date_from, None, params)
        combined = " ".join(clauses)
        assert "published_at >= :date_from" in combined
        assert params.get("date_from") == date_from

    def test_date_to_adds_published_at_lte_clause(self) -> None:
        """date_to adds a published_at <= :date_to clause."""
        params: dict[str, Any] = {}
        date_to = datetime(2026, 1, 31, tzinfo=timezone.utc)
        clauses = build_content_filters(None, None, None, None, None, date_to, params)
        combined = " ".join(clauses)
        assert "published_at <= :date_to" in combined
        assert params.get("date_to") == date_to

    def test_date_range_adds_two_date_clauses_plus_exclusion(self) -> None:
        """date_from and date_to together yield three clauses: two dates plus
        the duplicate exclusion."""
        params: dict[str, Any] = {}
        date_from = datetime(2026, 1, 1, tzinfo=timezone.utc)
        date_to = datetime(2026, 1, 31, tzinfo=timezone.utc)
        clauses = build_content_filters(None, None, None, None, date_from, date_to, params)
        assert len(clauses) == 3

    def test_table_alias_prepended_to_named_column_clauses(self) -> None:
        """table_alias is prepended to column names for aliased query contexts."""
        params: dict[str, Any] = {}
        qd_id = uuid.uuid4()
        clauses = build_content_filters(
            qd_id, None, None, None, None, None, params, table_alias="a."
        )
        named = [c for c in clauses if "duplicate_of" not in c]
        for clause in named:
            assert clause.startswith("a."), (
                f"Expected clause to start with 'a.' but got: {clause!r}"
            )

    def test_table_alias_applied_to_duplicate_exclusion_as_parenthesised_form(self) -> None:
        """When a table alias is provided, the duplicate exclusion clause uses the
        parenthesised form (alias.raw_metadata->>'duplicate_of') IS NULL."""
        params: dict[str, Any] = {}
        clauses = build_content_filters(
            None, None, None, None, None, None, params, table_alias="cr."
        )
        dup_clause = clauses[-1]
        assert "cr.raw_metadata" in dup_clause

    def test_return_list_is_never_empty(self) -> None:
        """build_content_filters() always returns a non-empty list."""
        params: dict[str, Any] = {}
        clauses = build_content_filters(None, None, None, None, None, None, params)
        assert len(clauses) >= 1


# ---------------------------------------------------------------------------
# build_content_where
# ---------------------------------------------------------------------------


class TestBuildContentWhere:
    def test_no_args_returns_where_string_with_duplicate_exclusion(self) -> None:
        """build_content_where() with no optional args returns a non-empty WHERE
        clause containing the duplicate exclusion predicate."""
        params: dict[str, Any] = {}
        result = build_content_where(None, None, None, None, None, None, params)
        assert result.startswith("WHERE")
        assert _DUPLICATE_EXCLUSION in result

    def test_query_design_id_included_in_where_clause(self) -> None:
        """query_design_id filter generates a WHERE clause mentioning
        query_design_id."""
        params: dict[str, Any] = {}
        qd_id = uuid.uuid4()
        result = build_content_where(qd_id, None, None, None, None, None, params)
        assert "query_design_id" in result
        assert "WHERE" in result
        assert params.get("query_design_id") == str(qd_id)

    def test_run_id_included_in_where_clause(self) -> None:
        """run_id filter generates a WHERE clause mentioning collection_run_id."""
        params: dict[str, Any] = {}
        run_id = uuid.uuid4()
        result = build_content_where(None, run_id, None, None, None, None, params)
        assert "collection_run_id" in result
        assert params.get("run_id") == str(run_id)

    def test_both_query_design_id_and_run_id_joined_with_and(self) -> None:
        """Multiple predicates are joined with AND in the returned WHERE clause."""
        params: dict[str, Any] = {}
        qd_id = uuid.uuid4()
        run_id = uuid.uuid4()
        result = build_content_where(qd_id, run_id, None, None, None, None, params)
        assert "AND" in result

    def test_always_returns_non_empty_string(self) -> None:
        """build_content_where() always returns a non-empty string (never '')."""
        params: dict[str, Any] = {}
        result = build_content_where(None, None, None, None, None, None, params)
        assert result != ""
        assert len(result) > 5  # at minimum 'WHERE ' + something

    def test_date_range_predicates_present_in_where_clause(self) -> None:
        """date_from and date_to generate appropriate predicates in the WHERE clause."""
        params: dict[str, Any] = {}
        date_from = datetime(2026, 1, 1, tzinfo=timezone.utc)
        date_to = datetime(2026, 1, 31, tzinfo=timezone.utc)
        result = build_content_where(None, None, None, None, date_from, date_to, params)
        assert "published_at >=" in result
        assert "published_at <=" in result

    def test_no_table_alias_in_build_content_where(self) -> None:
        """build_content_where() does not accept or apply a table alias —
        its output has no table alias prefix on plain column references."""
        params: dict[str, Any] = {}
        qd_id = uuid.uuid4()
        result = build_content_where(qd_id, None, None, None, None, None, params)
        # Without alias the direct predicate should not have a dot-prefix like 'cr.'
        assert "cr.query_design_id" not in result
        assert "query_design_id = :query_design_id" in result
