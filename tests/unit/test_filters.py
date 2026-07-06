"""Unit tests for the shared SQL filter-builder (Phase 1b migration).

Phase 1b: tests now cover build_content_where_sql + ContentFilterSpec from
``core/queries/content_filters.py``. The old ``analysis/_filters.py`` module
has been deleted; these tests validate that the new shared helper produces
equivalent SQL predicates for analysis-layer callers.

Tests cover:
- build_content_where_sql() with no args (only dedup exclusion), with
  query_design_id, with run_id, with both, with arenas/platforms, with date
  range, with table alias.
- ContentFilterSpec.include_duplicates=False always emits the duplicate
  exclusion predicate.
- Bind parameters are correctly populated in the mutable params dict.

No database or network connection is required.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Env bootstrap
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==")

from issue_observatory.core.queries.content_filters import (
    ContentFilterSpec,
    build_content_where_sql,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DUPLICATE_EXCLUSION = "raw_metadata->>'duplicate_of' IS NULL"


def _make_spec(**kwargs: Any) -> ContentFilterSpec:
    """Build a ContentFilterSpec for analysis-layer use with sensible defaults."""
    defaults: dict[str, Any] = {
        "include_duplicates": False,
        "ownership_mode": "admin",
        "include_linked": True,
    }
    defaults.update(kwargs)
    return ContentFilterSpec(**defaults)


def _build(spec: ContentFilterSpec, table_alias: str = "") -> tuple[str, dict[str, Any]]:
    """Call build_content_where_sql and return (where_str, params)."""
    params: dict[str, Any] = {}
    where = build_content_where_sql(spec, table_alias=table_alias, params=params)
    return where, params


# ---------------------------------------------------------------------------
# Duplicate exclusion always present when include_duplicates=False
# ---------------------------------------------------------------------------


class TestDuplicateExclusion:
    def test_no_args_returns_where_with_duplicate_exclusion(self) -> None:
        """With no filters, the WHERE clause includes the duplicate exclusion predicate.

        Note: when show_all=False (default), an actor_only_platforms bind param
        is also emitted as part of the term_matched predicate.
        """
        spec = _make_spec()
        where, params = _build(spec)
        assert where.startswith("WHERE")
        assert _DUPLICATE_EXCLUSION in where

    def test_duplicate_exclusion_present_with_query_design_id(self) -> None:
        spec = _make_spec(query_design_id=uuid.uuid4())
        where, _ = _build(spec)
        assert _DUPLICATE_EXCLUSION in where

    def test_duplicate_exclusion_present_with_run_id(self) -> None:
        spec = _make_spec(run_id=uuid.uuid4())
        where, _ = _build(spec)
        assert _DUPLICATE_EXCLUSION in where

    def test_duplicate_exclusion_present_with_all_filters(self) -> None:
        spec = _make_spec(
            query_design_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            arenas=["news_media"],
            platforms=["bluesky"],
            date_from=datetime(2026, 1, 1, tzinfo=UTC),
            date_to=datetime(2026, 1, 31, tzinfo=UTC),
        )
        where, _ = _build(spec)
        assert _DUPLICATE_EXCLUSION in where

    def test_no_duplicate_exclusion_when_include_duplicates_true(self) -> None:
        """When include_duplicates=True (default) the exclusion is NOT emitted."""
        spec = ContentFilterSpec(
            ownership_mode="admin",
            include_duplicates=True,
        )
        where, _ = _build(spec)
        assert _DUPLICATE_EXCLUSION not in where


# ---------------------------------------------------------------------------
# query_design_id (singular)
# ---------------------------------------------------------------------------


class TestQueryDesignId:
    def test_query_design_id_adds_clause_and_param(self) -> None:
        qd_id = uuid.uuid4()
        spec = _make_spec(query_design_id=qd_id)
        where, params = _build(spec)
        assert "query_design_id = :query_design_id" in where
        assert params.get("query_design_id") == str(qd_id)

    def test_query_design_id_suppressed_when_list_provided(self) -> None:
        """When query_design_ids list is non-empty the singular predicate is skipped."""
        qd_id = uuid.uuid4()
        list_id = uuid.uuid4()
        spec = _make_spec(query_design_id=qd_id, query_design_ids=[list_id])
        where, params = _build(spec)
        # Singular predicate not present — the list IN predicate dominates.
        assert "= :query_design_id" not in where
        assert any(str(list_id) in v for v in params.values())


# ---------------------------------------------------------------------------
# query_design_ids (list)
# ---------------------------------------------------------------------------


class TestQueryDesignIds:
    def test_query_design_ids_adds_in_predicate(self) -> None:
        ids = [uuid.uuid4(), uuid.uuid4()]
        spec = _make_spec(query_design_ids=ids)
        where, params = _build(spec)
        assert "query_design_id IN" in where
        assert all(str(qd_id) in params.values() for qd_id in ids)

    def test_query_design_ids_with_include_linked_has_exists(self) -> None:
        ids = [uuid.uuid4()]
        spec = _make_spec(query_design_ids=ids, include_linked=True)
        where, params = _build(spec)
        assert "EXISTS" in where
        assert "content_record_links" in where

    def test_query_design_ids_without_include_linked_no_exists(self) -> None:
        ids = [uuid.uuid4()]
        spec = _make_spec(query_design_ids=ids, include_linked=False)
        where, params = _build(spec)
        # No EXISTS subquery when include_linked=False
        assert "content_record_links" not in where


# ---------------------------------------------------------------------------
# run_id
# ---------------------------------------------------------------------------


class TestRunId:
    def test_run_id_adds_collection_run_id_clause(self) -> None:
        run_id = uuid.uuid4()
        spec = _make_spec(run_id=run_id)
        where, params = _build(spec)
        assert "collection_run_id = :run_id" in where
        assert params.get("run_id") == str(run_id)


# ---------------------------------------------------------------------------
# arenas and platforms (list predicates)
# ---------------------------------------------------------------------------


class TestListFilters:
    def test_arenas_list_generates_in_predicate(self) -> None:
        spec = _make_spec(arenas=["news_media"])
        where, params = _build(spec)
        assert "arena IN" in where
        assert "news_media" in params.values()

    def test_platforms_list_generates_in_predicate(self) -> None:
        spec = _make_spec(platforms=["bluesky"])
        where, params = _build(spec)
        assert "platform IN" in where
        assert "bluesky" in params.values()

    def test_languages_list_generates_split_part_in(self) -> None:
        spec = _make_spec(languages=["da"])
        where, params = _build(spec)
        assert "split_part" in where
        assert "IN" in where
        assert "da" in params.values()

    def test_search_terms_list_generates_overlap_operator(self) -> None:
        spec = _make_spec(search_terms=["klima", "energi"])
        where, params = _build(spec)
        assert "&&" in where
        assert "klima" in params.values()
        assert "energi" in params.values()
        # Default path must NOT include the ILIKE fallback.
        assert "ILIKE" not in where.upper()

    def test_search_terms_text_fallback_adds_ilike_branch(self) -> None:
        """Window-mode fallback widens the predicate with ILIKE ANY on text_content."""
        spec = _make_spec(
            search_terms=["klima", "energi"],
            search_terms_text_fallback=True,
        )
        where, params = _build(spec)
        # Both branches present, combined by OR.
        assert "&&" in where
        assert "ILIKE ANY" in where
        assert "text_content ILIKE" in where
        # Array-overlap binds are present as plain strings.
        assert "klima" in params.values()
        assert "energi" in params.values()
        # ILIKE binds are wrapped in % wildcards.
        ilike_vals = [v for k, v in params.items() if k.startswith("_stl_")]
        assert set(ilike_vals) == {"%klima%", "%energi%"}

    def test_search_terms_text_fallback_escapes_like_wildcards(self) -> None:
        """User-supplied % and _ must be escaped so they are treated literally."""
        spec = _make_spec(
            search_terms=["50%", "a_b"],
            search_terms_text_fallback=True,
        )
        _, params = _build(spec)
        ilike_vals = {v for k, v in params.items() if k.startswith("_stl_")}
        # Both wildcards should be backslash-escaped inside the pattern.
        assert r"%50\%%" in ilike_vals
        assert r"%a\_b%" in ilike_vals

    def test_multiple_arenas_uses_indexed_params(self) -> None:
        spec = _make_spec(arenas=["news", "social"])
        where, params = _build(spec)
        assert "arena IN" in where
        arena_vals = [v for k, v in params.items() if k.startswith("_arena_")]
        assert set(arena_vals) == {"news", "social"}


# ---------------------------------------------------------------------------
# date range
# ---------------------------------------------------------------------------


class TestDateRange:
    def test_date_from_adds_gte_clause(self) -> None:
        date_from = datetime(2026, 1, 1, tzinfo=UTC)
        spec = _make_spec(date_from=date_from)
        where, params = _build(spec)
        assert "published_at >= :date_from" in where
        assert params.get("date_from") == date_from

    def test_date_to_adds_lte_clause(self) -> None:
        date_to = datetime(2026, 1, 31, tzinfo=UTC)
        spec = _make_spec(date_to=date_to)
        where, params = _build(spec)
        assert "published_at <= :date_to" in where
        assert params.get("date_to") == date_to

    def test_date_range_predicates_present(self) -> None:
        spec = _make_spec(
            date_from=datetime(2026, 1, 1, tzinfo=UTC),
            date_to=datetime(2026, 1, 31, tzinfo=UTC),
        )
        where, _ = _build(spec)
        assert "published_at >=" in where
        assert "published_at <=" in where


# ---------------------------------------------------------------------------
# table alias
# ---------------------------------------------------------------------------


class TestTableAlias:
    def test_no_alias_no_prefix(self) -> None:
        qd_id = uuid.uuid4()
        spec = _make_spec(query_design_id=qd_id)
        where, _ = _build(spec, table_alias="")
        assert "cr.query_design_id" not in where
        assert "query_design_id = :query_design_id" in where

    def test_cr_alias_prepended_to_predicates(self) -> None:
        qd_id = uuid.uuid4()
        spec = _make_spec(query_design_id=qd_id)
        where, _ = _build(spec, table_alias="cr.")
        assert "cr.query_design_id = :query_design_id" in where

    def test_duplicate_exclusion_uses_alias(self) -> None:
        spec = _make_spec()
        where, _ = _build(spec, table_alias="cr.")
        assert "cr.raw_metadata->>'duplicate_of' IS NULL" in where

    def test_a_alias_for_self_join(self) -> None:
        spec = _make_spec(arenas=["news"])
        where, _ = _build(spec, table_alias="a.")
        assert "a.arena IN" in where


# ---------------------------------------------------------------------------
# WHERE string invariants
# ---------------------------------------------------------------------------


class TestWhereStringInvariants:
    def test_always_non_empty_when_include_duplicates_false(self) -> None:
        spec = _make_spec()
        where, _ = _build(spec)
        assert where != ""
        assert len(where) > 5

    def test_starts_with_where_keyword(self) -> None:
        spec = _make_spec()
        where, _ = _build(spec)
        assert where.startswith("WHERE")

    def test_multiple_predicates_joined_with_and(self) -> None:
        spec = _make_spec(
            query_design_id=uuid.uuid4(),
            arenas=["news"],
        )
        where, _ = _build(spec)
        assert "AND" in where
