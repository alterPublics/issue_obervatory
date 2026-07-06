"""Unit tests for the network analysis module.

Tests cover:
- _empty_graph(): returns expected empty structure
- _build_run_filter(): correct predicate generation with table alias
- _where() / _and(): correct SQL fragment construction
- get_actor_co_occurrence(): empty DB → empty graph; nodes + edges built correctly
- get_term_co_occurrence(): empty DB → empty graph; nodes and edges present
- get_cross_platform_actors(): empty DB → empty list; cross-platform actor mapped
- build_bipartite_network(): empty DB → empty graph; actor/term node types correct
- Degree computation: node degree matches edge count
- Danish actor/term names preserved in graph output

All database calls are mocked via unittest.mock.AsyncMock / MagicMock.
No live PostgreSQL instance is required.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Env bootstrap
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA==")

from issue_observatory.analysis.network import (
    _and,
    _build_run_filter,
    _empty_graph,
    _where,
    build_bipartite_network,
    get_actor_co_occurrence,
    get_cross_platform_actors,
    get_term_co_occurrence,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db_multi_execute(call_map: dict[int, Any]) -> Any:
    """Create a mock AsyncSession returning different results per call index.

    call_map: {1: MagicMock_for_first_call, 2: MagicMock_for_second_call, ...}
    Falls back to an empty-fetchall mock for any call beyond the map.
    """
    call_count = 0

    async def _execute(sql: Any, params: Any) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count in call_map:
            return call_map[call_count]
        default = MagicMock()
        default.fetchall.return_value = []
        default.fetchone.return_value = None
        return default

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db


def _empty_result() -> MagicMock:
    m = MagicMock()
    m.fetchall.return_value = []
    m.fetchone.return_value = None
    return m


def _make_node_row(
    author_id: str,
    display_name: str = "Test Author",
    platform: str = "bluesky",
    post_count: int = 10,
) -> Any:
    row = MagicMock()
    row.author_id = author_id
    row.display_name = display_name
    row.platform = platform
    row.post_count = post_count
    return row


def _make_edge_row(author_a: str, author_b: str, pair_count: int = 5) -> Any:
    row = MagicMock()
    row.author_a = author_a
    row.author_b = author_b
    row.pair_count = pair_count
    return row


def _make_term_edge_row(
    term_a: str,
    term_b: str,
    co_count: int,
    freq_a: int = 10,
    freq_b: int = 8,
) -> Any:
    row = MagicMock()
    row.term_a = term_a
    row.term_b = term_b
    row.co_count = co_count
    row.freq_a = freq_a
    row.freq_b = freq_b
    return row


def _make_cross_platform_row(
    actor_id: str,
    canonical_name: str,
    platform_count: int,
    platforms: list[str],
    total_records: int,
) -> Any:
    row = MagicMock()
    row.author_id = actor_id
    row.canonical_name = canonical_name
    row.platform_count = platform_count
    row.platforms = platforms
    row.total_records = total_records
    return row


def _make_bipartite_row(
    author_id: str,
    display_name: str,
    term: str,
    edge_weight: int,
) -> Any:
    row = MagicMock()
    row.author_id = author_id
    row.display_name = display_name
    row.term = term
    row.edge_weight = edge_weight
    return row


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class TestEmptyGraph:
    def test_empty_graph_returns_nodes_and_edges_keys(self) -> None:
        """_empty_graph() returns dict with 'nodes' and 'edges' keys."""
        result = _empty_graph()
        assert "nodes" in result
        assert "edges" in result

    def test_empty_graph_nodes_and_edges_are_empty_lists(self) -> None:
        """_empty_graph() nodes and edges are both empty lists."""
        result = _empty_graph()
        assert result["nodes"] == []
        assert result["edges"] == []


class TestBuildRunFilter:
    def test_build_run_filter_no_args_returns_duplicate_exclusion_clause(self) -> None:
        """_build_run_filter() with no args returns a WHERE string containing
        the duplicate exclusion predicate.

        Phase 1b refactoring: _build_run_filter now returns a WHERE clause
        string (not a list).  The duplicate exclusion predicate is always
        present so that network analysis functions never accidentally include
        records flagged as duplicates.
        """
        params: dict = {}
        where = _build_run_filter(None, None, None, None, None, None, params)
        assert isinstance(where, str)
        assert where.startswith("WHERE")
        assert "raw_metadata->>'duplicate_of' IS NULL" in where

    def test_build_run_filter_query_design_id_adds_clause(self) -> None:
        """query_design_id generates a predicate including the alias."""
        params: dict = {}
        qd_id = uuid.uuid4()
        where = _build_run_filter(qd_id, None, None, None, None, None, params, table_alias="a.")
        assert "a.query_design_id" in where
        assert params.get("query_design_id") == str(qd_id)

    def test_build_run_filter_run_id_adds_clause(self) -> None:
        """run_id generates a collection_run_id predicate."""
        params: dict = {}
        run_id = uuid.uuid4()
        where = _build_run_filter(None, run_id, None, None, None, None, params)
        assert "collection_run_id" in where

    def test_build_run_filter_platform_adds_clause(self) -> None:
        """platform filter generates a platform predicate."""
        params: dict = {}
        where = _build_run_filter(None, None, None, "bluesky", None, None, params)
        assert "platform" in where
        assert "bluesky" in str(list(params.values()))

    def test_build_run_filter_date_range_adds_three_clauses(self) -> None:
        """date_from and date_to each add a predicate; duplicate exclusion is always added.

        Phase 1b refactoring: the returned WHERE string contains both date
        predicates and the duplicate exclusion predicate.
        """
        params: dict = {}
        date_from = datetime(2026, 1, 1, tzinfo=UTC)
        date_to = datetime(2026, 1, 31, tzinfo=UTC)
        where = _build_run_filter(None, None, None, None, date_from, date_to, params)
        assert "published_at >=" in where
        assert "published_at <=" in where
        assert "raw_metadata->>'duplicate_of' IS NULL" in where

    def test_build_run_filter_table_alias_applied_to_all_clauses(self) -> None:
        """Table alias is applied to column references in the WHERE string.

        Phase 1b refactoring: the WHERE string now contains the alias on all
        column references (query_design_id, collection_run_id, platform, and
        the JSONB raw_metadata expression).
        """
        params: dict = {}
        qd_id = uuid.uuid4()
        run_id = uuid.uuid4()
        where = _build_run_filter(qd_id, run_id, None, "bluesky", None, None, params, "cr.")
        # The complete WHERE string must contain the alias
        assert "cr." in where
        # Named column predicates must use the alias
        assert "cr.query_design_id" in where
        assert "cr.collection_run_id" in where


class TestWhereAnd:
    def test_where_empty_string_returns_empty_string(self) -> None:
        """_where('') returns an empty string (pass-through)."""
        assert _where("") == ""

    def test_where_single_clause_returns_same_string(self) -> None:
        """_where(s) returns s unchanged (pass-through for WHERE strings)."""
        where_str = "WHERE x = :x"
        assert _where(where_str) == where_str

    def test_where_full_clause_preserved(self) -> None:
        """_where() is a pass-through: the WHERE prefix is preserved."""
        where_str = "WHERE a = :a AND b = :b"
        result = _where(where_str)
        assert result.startswith("WHERE")
        assert "AND" in result

    def test_and_empty_string_returns_empty_string(self) -> None:
        """_and('') returns an empty string."""
        assert _and("") == ""

    def test_and_where_string_strips_where_prefix(self) -> None:
        """_and('WHERE x = :x') returns 'AND x = :x'."""
        result = _and("WHERE x = :x")
        assert result == "AND x = :x"


# ---------------------------------------------------------------------------
# get_actor_co_occurrence
# ---------------------------------------------------------------------------


class TestGetActorCoOccurrence:
    @pytest.mark.asyncio
    async def test_actor_co_occurrence_empty_db_returns_empty_graph(self) -> None:
        """Empty DB (no rows) returns {'nodes': [], 'edges': []}."""
        # First DB call (nodes query) returns empty → triggers early return
        first_result = MagicMock()
        first_result.fetchall.return_value = []
        db = _mock_db_multi_execute({1: first_result})
        result = await get_actor_co_occurrence(db)
        assert result == {"nodes": [], "edges": []}

    @pytest.mark.asyncio
    async def test_actor_co_occurrence_returns_graph_dict(self) -> None:
        """Non-empty DB returns a dict with 'nodes' and 'edges' keys."""
        node_result = MagicMock()
        node_result.fetchall.return_value = [
            _make_node_row("author-a", "Actor A", "bluesky", 10),
            _make_node_row("author-b", "Actor B", "bluesky", 5),
        ]
        edge_result = MagicMock()
        edge_result.fetchall.return_value = [
            _make_edge_row("author-a", "author-b", 3),
        ]
        db = _mock_db_multi_execute({1: node_result, 2: edge_result})
        result = await get_actor_co_occurrence(db)
        assert "nodes" in result
        assert "edges" in result

    @pytest.mark.asyncio
    async def test_actor_co_occurrence_node_count_matches_unique_actors(self) -> None:
        """Node list contains one entry per unique pseudonymized_author_id."""
        node_result = MagicMock()
        node_result.fetchall.return_value = [
            _make_node_row("author-a"),
            _make_node_row("author-b"),
        ]
        edge_result = MagicMock()
        edge_result.fetchall.return_value = [_make_edge_row("author-a", "author-b", 2)]
        db = _mock_db_multi_execute({1: node_result, 2: edge_result})
        result = await get_actor_co_occurrence(db)
        assert len(result["nodes"]) == 2

    @pytest.mark.asyncio
    async def test_actor_co_occurrence_edge_weight_preserved(self) -> None:
        """Edge weight from SQL row is correctly placed in the returned edge dict."""
        node_result = MagicMock()
        node_result.fetchall.return_value = [
            _make_node_row("author-a"),
            _make_node_row("author-b"),
        ]
        edge_result = MagicMock()
        edge_result.fetchall.return_value = [_make_edge_row("author-a", "author-b", 7)]
        db = _mock_db_multi_execute({1: node_result, 2: edge_result})
        result = await get_actor_co_occurrence(db)
        assert len(result["edges"]) == 1
        assert result["edges"][0]["weight"] == 7

    @pytest.mark.asyncio
    async def test_actor_co_occurrence_node_degree_computed_from_edges(self) -> None:
        """Node degree is computed as the number of edges each node participates in."""
        node_result = MagicMock()
        node_result.fetchall.return_value = [
            _make_node_row("author-a"),
            _make_node_row("author-b"),
            _make_node_row("author-c"),
        ]
        edge_result = MagicMock()
        # A-B and A-C: author-a has degree 2; author-b and author-c have degree 1
        edge_result.fetchall.return_value = [
            _make_edge_row("author-a", "author-b", 3),
            _make_edge_row("author-a", "author-c", 2),
        ]
        db = _mock_db_multi_execute({1: node_result, 2: edge_result})
        result = await get_actor_co_occurrence(db)
        node_map = {n["id"]: n["degree"] for n in result["nodes"]}
        assert node_map["author-a"] == 2
        assert node_map["author-b"] == 1
        assert node_map["author-c"] == 1

    @pytest.mark.asyncio
    async def test_actor_co_occurrence_danish_display_name_preserved(self) -> None:
        """Danish characters in actor display names survive network construction."""
        node_result = MagicMock()
        node_result.fetchall.return_value = [
            _make_node_row("author-dk", "Søren Ærlighed-Øberg"),
        ]
        edge_result = MagicMock()
        edge_result.fetchall.return_value = []
        db = _mock_db_multi_execute({1: node_result, 2: edge_result})
        result = await get_actor_co_occurrence(db)
        labels = [n["label"] for n in result["nodes"]]
        assert "Søren Ærlighed-Øberg" in labels

    @pytest.mark.asyncio
    async def test_actor_co_occurrence_uses_author_id_when_no_display_name(self) -> None:
        """Node label falls back to author_id when display_name is None."""
        node_result = MagicMock()
        row = MagicMock()
        row.author_id = "author-no-name"
        row.display_name = None
        row.platform = "bluesky"
        row.post_count = 3
        node_result.fetchall.return_value = [row]
        edge_result = MagicMock()
        edge_result.fetchall.return_value = []
        db = _mock_db_multi_execute({1: node_result, 2: edge_result})
        result = await get_actor_co_occurrence(db)
        assert result["nodes"][0]["label"] == "author-no-name"


# ---------------------------------------------------------------------------
# get_term_co_occurrence
# ---------------------------------------------------------------------------


class TestGetTermCoOccurrence:
    @pytest.mark.asyncio
    async def test_term_co_occurrence_empty_db_returns_empty_graph(self) -> None:
        """Empty DB returns {'nodes': [], 'edges': []}."""
        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await get_term_co_occurrence(db)
        assert result == {"nodes": [], "edges": []}

    @pytest.mark.asyncio
    async def test_term_co_occurrence_two_terms_produce_one_edge(self) -> None:
        """Two co-occurring terms produce exactly one edge."""
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            _make_term_edge_row("klimaforandringer", "grøn omstilling", 15),
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await get_term_co_occurrence(db)
        assert len(result["edges"]) == 1

    @pytest.mark.asyncio
    async def test_term_co_occurrence_edge_source_and_target_are_terms(self) -> None:
        """Edge source and target are the raw term strings (not node IDs)."""
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            _make_term_edge_row("klimaforandringer", "velfærdsstat", 10),
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await get_term_co_occurrence(db)
        edge = result["edges"][0]
        assert edge["source"] == "klimaforandringer"
        assert edge["target"] == "velfærdsstat"
        assert edge["weight"] == 10

    @pytest.mark.asyncio
    async def test_term_co_occurrence_node_type_is_term(self) -> None:
        """All nodes in the term co-occurrence graph have type='term'."""
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            _make_term_edge_row("klimaforandringer", "grøn omstilling", 5),
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await get_term_co_occurrence(db)
        for node in result["nodes"]:
            assert node["type"] == "term"

    @pytest.mark.asyncio
    async def test_term_co_occurrence_node_frequency_populated(self) -> None:
        """Node 'frequency' attribute reflects the per-term occurrence count."""
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            _make_term_edge_row("klimaforandringer", "grøn omstilling", 5, freq_a=20, freq_b=12),
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await get_term_co_occurrence(db)
        node_map = {n["id"]: n["frequency"] for n in result["nodes"]}
        assert node_map["klimaforandringer"] == 20
        assert node_map["grøn omstilling"] == 12

    @pytest.mark.asyncio
    async def test_term_co_occurrence_degree_computed_correctly(self) -> None:
        """Term node degree equals its edge count."""
        result_mock = MagicMock()
        # term_a participates in 2 edges; term_b and term_c in 1 each
        result_mock.fetchall.return_value = [
            _make_term_edge_row("term_a", "term_b", 10),
            _make_term_edge_row("term_a", "term_c", 8),
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await get_term_co_occurrence(db)
        node_map = {n["id"]: n["degree"] for n in result["nodes"]}
        assert node_map["term_a"] == 2
        assert node_map.get("term_b", 0) == 1
        assert node_map.get("term_c", 0) == 1

    @pytest.mark.asyncio
    async def test_term_co_occurrence_danish_terms_preserved(self) -> None:
        """Danish characters in term strings survive network construction."""
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            _make_term_edge_row("grøn omstilling", "velfærdsstat", 5),
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await get_term_co_occurrence(db)
        node_ids = {n["id"] for n in result["nodes"]}
        assert "grøn omstilling" in node_ids
        assert "velfærdsstat" in node_ids


# ---------------------------------------------------------------------------
# get_cross_platform_actors
# ---------------------------------------------------------------------------


class TestGetCrossPlatformActors:
    @pytest.mark.asyncio
    async def test_cross_platform_empty_db_returns_empty_list(self) -> None:
        """Empty DB returns an empty list."""
        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await get_cross_platform_actors(db)
        assert result == []

    @pytest.mark.asyncio
    async def test_cross_platform_actor_fields_correct(self) -> None:
        """Returned list contains correctly mapped actor dicts."""
        actor_id = str(uuid.uuid4())
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            _make_cross_platform_row(
                actor_id, "DR Nyheder", 3, ["bluesky", "reddit", "youtube"], 842
            )
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await get_cross_platform_actors(db)
        assert len(result) == 1
        actor = result[0]
        assert actor["actor_id"] == actor_id
        assert actor["canonical_name"] == "DR Nyheder"
        assert actor["platform_count"] == 3
        assert set(actor["platforms"]) == {"bluesky", "reddit", "youtube"}
        assert actor["total_records"] == 842

    @pytest.mark.asyncio
    async def test_cross_platform_actor_same_actor_two_platforms_identified(self) -> None:
        """An actor active on 2 platforms is returned with platform_count=2."""
        actor_id = str(uuid.uuid4())
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            _make_cross_platform_row(
                actor_id, "Søren Ørsted", 2, ["bluesky", "reddit"], 50
            )
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await get_cross_platform_actors(db)
        assert result[0]["platform_count"] == 2

    @pytest.mark.asyncio
    async def test_cross_platform_danish_canonical_name_preserved(self) -> None:
        """Danish characters in canonical_name survive cross-platform mapping."""
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            _make_cross_platform_row(
                "actor-da", "Søren Ærlighed-Øberg", 2, ["bluesky", "reddit"], 10
            )
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await get_cross_platform_actors(db)
        assert result[0]["canonical_name"] == "Søren Ærlighed-Øberg"

    @pytest.mark.asyncio
    async def test_cross_platform_empty_platforms_array_handled(self) -> None:
        """A row with platforms=None returns an empty platforms list."""
        row = MagicMock()
        row.author_id = "actor-x"
        row.canonical_name = "Test"
        row.platform_count = 2
        row.platforms = None  # simulate SQL NULL
        row.total_records = 5
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [row]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await get_cross_platform_actors(db)
        assert result[0]["platforms"] == []


# ---------------------------------------------------------------------------
# build_bipartite_network
# ---------------------------------------------------------------------------


class TestBuildBipartiteNetwork:
    @pytest.mark.asyncio
    async def test_bipartite_empty_db_returns_empty_graph(self) -> None:
        """Empty DB returns {'nodes': [], 'edges': []}."""
        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await build_bipartite_network(db)
        assert result == {"nodes": [], "edges": []}

    @pytest.mark.asyncio
    async def test_bipartite_actor_node_type_is_actor(self) -> None:
        """Actor nodes have type='actor'."""
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            _make_bipartite_row("author-a", "Actor A", "klimaforandringer", 5),
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await build_bipartite_network(db)
        actor_nodes = [n for n in result["nodes"] if n["type"] == "actor"]
        assert len(actor_nodes) >= 1
        assert actor_nodes[0]["id"] == "author-a"

    @pytest.mark.asyncio
    async def test_bipartite_term_node_type_is_term(self) -> None:
        """Term nodes have type='term'."""
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            _make_bipartite_row("author-a", "Actor A", "klimaforandringer", 5),
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await build_bipartite_network(db)
        term_nodes = [n for n in result["nodes"] if n["type"] == "term"]
        assert len(term_nodes) >= 1

    @pytest.mark.asyncio
    async def test_bipartite_term_node_id_has_term_prefix(self) -> None:
        """Term node IDs are prefixed with 'term:' to avoid collision with actor IDs."""
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            _make_bipartite_row("author-a", "Actor A", "klimaforandringer", 5),
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await build_bipartite_network(db)
        term_ids = [n["id"] for n in result["nodes"] if n["type"] == "term"]
        assert all(tid.startswith("term:") for tid in term_ids)
        assert "term:klimaforandringer" in term_ids

    @pytest.mark.asyncio
    async def test_bipartite_edge_source_is_actor_target_is_term(self) -> None:
        """Edges go from actor ID to term:X ID."""
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            _make_bipartite_row("author-a", "Actor A", "klimaforandringer", 7),
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await build_bipartite_network(db)
        assert len(result["edges"]) == 1
        edge = result["edges"][0]
        assert edge["source"] == "author-a"
        assert edge["target"] == "term:klimaforandringer"
        assert edge["weight"] == 7

    @pytest.mark.asyncio
    async def test_bipartite_multiple_actors_same_term(self) -> None:
        """Multiple actors linked to the same term produce multiple edges."""
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            _make_bipartite_row("author-a", "Actor A", "klimaforandringer", 5),
            _make_bipartite_row("author-b", "Actor B", "klimaforandringer", 3),
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await build_bipartite_network(db)
        # Two actor nodes + one term node
        actor_nodes = [n for n in result["nodes"] if n["type"] == "actor"]
        term_nodes = [n for n in result["nodes"] if n["type"] == "term"]
        assert len(actor_nodes) == 2
        assert len(term_nodes) == 1
        assert len(result["edges"]) == 2

    @pytest.mark.asyncio
    async def test_bipartite_actor_label_falls_back_to_id(self) -> None:
        """Actor label falls back to author_id when display_name is None."""
        result_mock = MagicMock()
        row = MagicMock()
        row.author_id = "author-no-name"
        row.display_name = None
        row.term = "klimaforandringer"
        row.edge_weight = 2
        result_mock.fetchall.return_value = [row]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await build_bipartite_network(db)
        actor_nodes = [n for n in result["nodes"] if n["type"] == "actor"]
        assert actor_nodes[0]["label"] == "author-no-name"

    @pytest.mark.asyncio
    async def test_bipartite_danish_term_preserved(self) -> None:
        """Danish characters in search term strings survive bipartite network construction."""
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            _make_bipartite_row("author-a", "Actor A", "grøn omstilling", 4),
            _make_bipartite_row("author-a", "Actor A", "velfærdsstat", 2),
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await build_bipartite_network(db)
        term_ids = {n["id"] for n in result["nodes"] if n["type"] == "term"}
        assert "term:grøn omstilling" in term_ids
        assert "term:velfærdsstat" in term_ids

    @pytest.mark.asyncio
    async def test_bipartite_network_density_matches_expected(self) -> None:
        """With N actors and M terms, node count = N + M and edge count = rows."""
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            _make_bipartite_row("author-a", "A", "term1", 3),
            _make_bipartite_row("author-a", "A", "term2", 1),
            _make_bipartite_row("author-b", "B", "term1", 2),
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await build_bipartite_network(db)
        actor_count = sum(1 for n in result["nodes"] if n["type"] == "actor")
        term_count = sum(1 for n in result["nodes"] if n["type"] == "term")
        # 2 distinct actors, 2 distinct terms, 3 edges
        assert actor_count == 2
        assert term_count == 2
        assert len(result["edges"]) == 3

    @pytest.mark.asyncio
    async def test_bipartite_graph_has_correct_structure_keys(self) -> None:
        """The returned graph dict has 'nodes' and 'edges' keys."""
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            _make_bipartite_row("author-a", "A", "term1", 1),
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        result = await build_bipartite_network(db)
        assert "nodes" in result
        assert "edges" in result
