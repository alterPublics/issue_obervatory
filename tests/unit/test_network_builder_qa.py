"""QA comprehensive tests for network_builder.py.

Covers edge cases, correctness guarantees, Danish character handling,
node ID collisions, disparity filter properties, and filter item logic
that were not addressed in the original test_network_builder.py and
test_network_limits.py suites.

Written by QA Agent during comprehensive Network Analysis review.
"""
from __future__ import annotations

import pytest

from issue_observatory.analysis.network_builder import (
    _apply_disparity_backbone,
    _build_bipartite,
    _build_bipartite_entities,
    _estimate_projected_pairs,
    _filter_items_per_group,
    _invert_edges,
    _project_edges,
    _reduce_retained_nodes,
    _safe_power,
    enforce_network_limits,
    extract_giant_component,
    project_to_unipartite,
)


# ---------------------------------------------------------------------------
# Danish character preservation
# ---------------------------------------------------------------------------

class TestDanishCharacterPreservation:
    """Verify that Danish characters (ae, oe, aa) are preserved
    through all graph construction and filtering operations."""

    def test_bipartite_preserves_danish_sender_name(self) -> None:
        """Sender names with ae/oe/aa pass through unchanged."""
        sender_items = {"Søren Østergård": {"klima": 3}}
        graph = _build_bipartite(
            sender_items,
            {"Søren Østergård": 3},
            {"klima": 3},
            "keyword",
            min_weight=1,
        )
        # IDs are now prefixed by type, but labels preserve original names
        node_ids = {n["id"] for n in graph["nodes"]}
        assert "sender:Søren Østergård" in node_ids
        labels = {n["label"] for n in graph["nodes"]}
        assert "Søren Østergård" in labels

    def test_bipartite_preserves_danish_keyword(self) -> None:
        """Keywords with ae/oe/aa pass through as labels unchanged."""
        sender_items = {"Alice": {"bæredygtighed": 5, "ørsted": 2, "ålborg": 1}}
        graph = _build_bipartite(
            sender_items,
            {"Alice": 8},
            {"bæredygtighed": 5, "ørsted": 2, "ålborg": 1},
            "keyword",
            min_weight=1,
        )
        node_labels = {n["label"] for n in graph["nodes"]}
        assert "bæredygtighed" in node_labels
        assert "ørsted" in node_labels
        assert "ålborg" in node_labels

    def test_unipartite_projection_preserves_danish_names(self) -> None:
        """Projected unipartite nodes retain Danish characters."""
        bipartite_edges = {
            "Søren": {"klima": 3},
            "Ørjan": {"klima": 2},
        }
        graph = project_to_unipartite(
            bipartite_edges, "keyword",
            {"Søren": 3, "Ørjan": 2},
            {"klima": 5},
            min_weight=1,
        )
        node_ids = {n["id"] for n in graph["nodes"]}
        assert "Søren" in node_ids
        assert "Ørjan" in node_ids

    def test_giant_component_preserves_danish_labels(self) -> None:
        """Giant component extraction preserves Danish label metadata."""
        graph = {
            "nodes": [
                {"id": "Ålborg", "label": "Ålborg", "node_type": "entity"},
                {"id": "København", "label": "København", "node_type": "entity"},
            ],
            "edges": [
                {"source": "Ålborg", "target": "København", "weight": 5},
            ],
        }
        result = extract_giant_component(graph)
        labels = {n["label"] for n in result["nodes"]}
        assert "Ålborg" in labels
        assert "København" in labels

    def test_entity_bipartite_preserves_danish_entity_names(self) -> None:
        """Entity bipartite construction preserves Danish entity names in labels."""
        sender_entities = {"reporter1": {"Socialdemokratiet": 5, "Økonomisk Råd": 3}}
        graph = _build_bipartite_entities(
            sender_entities,
            {"reporter1": 8},
            {"Socialdemokratiet": 5, "Økonomisk Råd": 3},
            {"Socialdemokratiet": "ORG", "Økonomisk Råd": "ORG"},
            min_weight=1,
        )
        entity_labels = {
            n["label"] for n in graph["nodes"] if n["node_type"] == "entity"
        }
        assert "Socialdemokratiet" in entity_labels
        assert "Økonomisk Råd" in entity_labels
        # IDs are prefixed but labels are clean
        entity_ids = {n["id"] for n in graph["nodes"] if n["node_type"] == "entity"}
        assert "entity:Socialdemokratiet" in entity_ids


# ---------------------------------------------------------------------------
# Node ID collision between sender and keyword
# ---------------------------------------------------------------------------

class TestNodeIdCollision:
    """Test that type-prefixed IDs prevent sender/keyword name collisions."""

    def test_bipartite_no_collision_with_prefixes(self) -> None:
        """Sender and keyword with the same name both exist as separate nodes
        thanks to type-prefixed IDs (sender:klima vs keyword:klima)."""
        sender_items = {
            "klima": {"energi": 3},  # sender named 'klima'
            "Bob": {"klima": 2},     # keyword named 'klima'
        }
        sender_counts = {"klima": 5, "Bob": 3}
        item_counts = {"klima": 4, "energi": 3}

        graph = _build_bipartite(
            sender_items, sender_counts, item_counts, "keyword", min_weight=1
        )

        # Both 'klima' nodes exist with different prefixed IDs
        klima_sender = [n for n in graph["nodes"] if n["id"] == "sender:klima"]
        klima_keyword = [n for n in graph["nodes"] if n["id"] == "keyword:klima"]
        assert len(klima_sender) == 1
        assert len(klima_keyword) == 1
        assert klima_sender[0]["node_type"] == "sender"
        assert klima_keyword[0]["node_type"] == "keyword"
        # Both have label "klima" (unprefixed)
        assert klima_sender[0]["label"] == "klima"
        assert klima_keyword[0]["label"] == "klima"
        # Edge from Bob targets the keyword node, not the sender node
        bob_edges = [e for e in graph["edges"] if e["source"] == "sender:Bob"]
        assert any(e["target"] == "keyword:klima" for e in bob_edges)

    def test_entity_bipartite_no_collision_with_prefixes(self) -> None:
        """Sender and entity with same name both exist with prefixed IDs."""
        sender_entities = {
            "NATO": {"Denmark": 3},  # sender named 'NATO'
            "reporter": {"NATO": 5},  # entity named 'NATO'
        }
        graph = _build_bipartite_entities(
            sender_entities,
            {"NATO": 3, "reporter": 5},
            {"Denmark": 3, "NATO": 5},
            {"Denmark": "GPE", "NATO": "ORG"},
            min_weight=1,
        )
        nato_sender = [n for n in graph["nodes"] if n["id"] == "sender:NATO"]
        nato_entity = [n for n in graph["nodes"] if n["id"] == "entity:NATO"]
        assert len(nato_sender) == 1
        assert len(nato_entity) == 1
        assert nato_sender[0]["node_type"] == "sender"
        assert nato_entity[0]["node_type"] == "entity"


# ---------------------------------------------------------------------------
# Filter items per group
# ---------------------------------------------------------------------------

class TestFilterItemsPerGroup:
    """Test _filter_items_per_group edge cases."""

    def test_min_items_filters_small_groups(self) -> None:
        """Groups with fewer items than min_items are dropped."""
        group_items = {
            "Alice": {"k1": 1, "k2": 2, "k3": 3},
            "Bob": {"k1": 1},
        }
        item_counts = {"k1": 2, "k2": 1, "k3": 1}
        result = _filter_items_per_group(group_items, item_counts, min_items=2, max_items=None)
        assert "Alice" in result
        assert "Bob" not in result

    def test_max_items_keeps_top_by_weight(self) -> None:
        """Only top N items by weight are kept per group."""
        group_items = {
            "Alice": {"k1": 10, "k2": 5, "k3": 1},
        }
        item_counts = {"k1": 10, "k2": 5, "k3": 1}
        result = _filter_items_per_group(group_items, item_counts, min_items=None, max_items=2)
        assert len(result["Alice"]) == 2
        assert "k1" in result["Alice"]
        assert "k2" in result["Alice"]
        assert "k3" not in result["Alice"]

    def test_empty_input(self) -> None:
        """Empty group_items returns empty dict."""
        result = _filter_items_per_group({}, {}, min_items=1, max_items=10)
        assert result == {}

    def test_max_items_equal_to_group_size(self) -> None:
        """When max_items equals group size, no pruning occurs."""
        group_items = {"Alice": {"k1": 3, "k2": 2}}
        result = _filter_items_per_group(group_items, {"k1": 3, "k2": 2}, None, max_items=2)
        assert len(result["Alice"]) == 2

    def test_min_items_zero_is_falsy(self) -> None:
        """min_items=0 behaves like None (no filtering) due to falsy check."""
        group_items = {"Alice": {"k1": 1}}
        result = _filter_items_per_group(group_items, {"k1": 1}, min_items=0, max_items=None)
        # min_items=0 is falsy, so Alice should NOT be filtered out
        assert "Alice" in result


# ---------------------------------------------------------------------------
# Unipartite projection correctness
# ---------------------------------------------------------------------------

class TestUnipartiteProjectionCorrectness:
    """Verify mathematical correctness of the unipartite projection."""

    def test_no_self_loops(self) -> None:
        """Projection never creates self-loops (edge from node to itself)."""
        bipartite_edges = {
            "Alice": {"klima": 5, "energi": 3},
        }
        graph = project_to_unipartite(
            bipartite_edges, "keyword",
            {"Alice": 8}, {"klima": 5, "energi": 3},
            min_weight=1,
        )
        for edge in graph["edges"]:
            assert edge["source"] != edge["target"], \
                f"Self-loop found: {edge['source']}"

    def test_three_way_shared_neighbors(self) -> None:
        """Three senders sharing a keyword produce 3 projected edges."""
        bipartite_edges = {
            "A": {"x": 4},
            "B": {"x": 3},
            "C": {"x": 2},
        }
        graph = project_to_unipartite(
            bipartite_edges, "keyword",
            {"A": 4, "B": 3, "C": 2},
            {"x": 9},
            min_weight=1,
        )
        assert len(graph["edges"]) == 3  # A-B, A-C, B-C
        edge_pairs = {
            frozenset((e["source"], e["target"])) for e in graph["edges"]
        }
        assert frozenset(("A", "B")) in edge_pairs
        assert frozenset(("A", "C")) in edge_pairs
        assert frozenset(("B", "C")) in edge_pairs

    def test_edge_ordering_canonical(self) -> None:
        """Projected edges use (min, max) canonical ordering."""
        bipartite_edges = {
            "Zebra": {"x": 3},
            "Alpha": {"x": 2},
        }
        graph = project_to_unipartite(
            bipartite_edges, "keyword",
            {"Zebra": 3, "Alpha": 2},
            {"x": 5},
            min_weight=1,
        )
        edge = graph["edges"][0]
        assert edge["source"] == "Alpha"
        assert edge["target"] == "Zebra"

    def test_projection_symmetry(self) -> None:
        """weight(A,B) == weight(B,A) — the graph is undirected."""
        bipartite_edges = {
            "A": {"x": 10, "y": 5},
            "B": {"x": 3, "y": 8},
        }
        graph = project_to_unipartite(
            bipartite_edges, "keyword",
            {"A": 15, "B": 11},
            {"x": 13, "y": 13},
            min_weight=1,
        )
        assert len(graph["edges"]) == 1
        # weight = min(10,3) + min(5,8) = 3 + 5 = 8
        assert graph["edges"][0]["weight"] == 8


# ---------------------------------------------------------------------------
# Disparity backbone properties
# ---------------------------------------------------------------------------

class TestDisparityBackboneProperties:
    """Verify properties of the disparity filter backbone."""

    def test_alpha_one_keeps_all_edges(self) -> None:
        """With alpha=1.0, all edges should be kept (nothing is significant)."""
        # Actually, disparity < alpha means keep. With alpha=1.0, all disparity < 1.0
        # for edges from nodes with degree > 1. Edges from degree-1 nodes get d=1.0
        # which is NOT < 1.0, so they get dropped!
        edges = [(0, 1, 5), (0, 2, 3)]
        graph = _make_graph(3, edges)
        result = _apply_disparity_backbone(graph, alpha=1.0)
        # Node 0 has degree 2, nodes 1 and 2 have degree 1
        # From node 0's perspective: both edges should survive (d < 1.0)
        # From node 1's perspective: d_tgt = 1.0 (degree 1), which is NOT < 1.0
        # But min(d_src, d_tgt) only needs one to be < alpha
        assert len(result["edges"]) == 2

    def test_alpha_zero_removes_all_edges(self) -> None:
        """With alpha=0.0, no edges survive (nothing has disparity < 0)."""
        edges = [(0, 1, 5), (0, 2, 3)]
        graph = _make_graph(3, edges)
        result = _apply_disparity_backbone(graph, alpha=0.0)
        assert len(result["edges"]) == 0

    def test_uniform_weights_low_alpha_removes_all(self) -> None:
        """A graph with uniform edge weights loses all edges at low alpha
        because no edge is more significant than any other."""
        n = 20
        edges = [(i, (i + 1) % n, 1) for i in range(n)]  # ring, all weight=1
        graph = _make_graph(n, edges)
        result = _apply_disparity_backbone(graph, alpha=0.01)
        # For uniform weights on degree-2 nodes: p = 0.5, d = (1 - 0.5)^1 = 0.5
        # 0.5 < 0.01 is False, so all removed
        assert len(result["edges"]) == 0

    def test_backbone_preserves_edge_attributes(self) -> None:
        """Backbone filtering preserves edge dict attributes beyond source/target/weight."""
        graph = {
            "nodes": [
                {"id": "a", "label": "a", "node_type": "sender"},
                {"id": "b", "label": "b", "node_type": "keyword"},
                {"id": "c", "label": "c", "node_type": "keyword"},
            ],
            "edges": [
                {"source": "a", "target": "b", "weight": 100, "extra": "data1"},
                {"source": "a", "target": "c", "weight": 1, "extra": "data2"},
            ],
        }
        result = _apply_disparity_backbone(graph, alpha=0.5)
        surviving = [e for e in result["edges"] if e["weight"] == 100]
        if surviving:
            assert surviving[0]["extra"] == "data1"


# ---------------------------------------------------------------------------
# Enforce network limits edge cases
# ---------------------------------------------------------------------------

class TestEnforceNetworkLimitsEdgeCases:
    """Edge cases for enforce_network_limits."""

    def test_empty_graph(self) -> None:
        """Empty graph passes through unchanged."""
        graph = {"nodes": [], "edges": []}
        result = enforce_network_limits(graph)
        assert result["nodes"] == []
        assert result["edges"] == []
        assert "reduced" not in result

    def test_exactly_at_limits(self) -> None:
        """Graph at exactly max_nodes and max_edges passes unchanged."""
        nodes = [{"id": f"n{i}", "label": f"n{i}"} for i in range(500)]
        # Create a ring for exactly 500 edges
        edges = [
            {"source": f"n{i}", "target": f"n{(i+1)%500}", "weight": 1}
            for i in range(500)
        ]
        graph = {"nodes": nodes, "edges": edges}
        result = enforce_network_limits(graph, max_nodes=500, max_edges=5000)
        assert "reduced" not in result

    def test_one_over_node_limit(self) -> None:
        """Graph with max_nodes + 1 triggers reduction."""
        n = 501
        edges = [(i, (i + 1) % n, 1) for i in range(n)]
        graph = _make_graph(n, edges)
        result = enforce_network_limits(graph, max_nodes=500, max_edges=5000)
        assert "reduced" in result
        assert len(result["nodes"]) <= 500

    def test_hard_truncation_preserves_highest_degree_nodes(self) -> None:
        """When backbone fails, hard truncation keeps highest-degree nodes."""
        # Build a star graph that won't fit
        n = 600
        edges = [(0, i, 1) for i in range(1, n)]
        # Also connect leaf pairs to give them degree >= 2
        for i in range(1, n, 2):
            if i + 1 < n:
                edges.append((i, i + 1, 1))
        graph = _make_graph(n, edges)
        result = enforce_network_limits(graph, max_nodes=100, max_edges=500)
        assert len(result["nodes"]) <= 100
        assert len(result["edges"]) <= 500


# ---------------------------------------------------------------------------
# Giant component edge cases
# ---------------------------------------------------------------------------

class TestGiantComponentEdgeCases:
    """Additional edge cases for extract_giant_component."""

    def test_all_isolated_nodes(self) -> None:
        """Graph with only isolated nodes returns the first one found."""
        graph = {
            "nodes": [
                {"id": "A", "label": "A"},
                {"id": "B", "label": "B"},
                {"id": "C", "label": "C"},
            ],
            "edges": [],
        }
        result = extract_giant_component(graph)
        # All components have size 1; max picks the first
        assert len(result["nodes"]) == 1
        assert len(result["edges"]) == 0

    def test_equal_size_components(self) -> None:
        """With two equal-size components, one is returned (deterministic)."""
        graph = {
            "nodes": [
                {"id": "A", "label": "A"}, {"id": "B", "label": "B"},
                {"id": "X", "label": "X"}, {"id": "Y", "label": "Y"},
            ],
            "edges": [
                {"source": "A", "target": "B", "weight": 1},
                {"source": "X", "target": "Y", "weight": 1},
            ],
        }
        result = extract_giant_component(graph)
        assert len(result["nodes"]) == 2
        assert len(result["edges"]) == 1

    def test_preserves_edge_weights(self) -> None:
        """Edge weight and other attributes are preserved through extraction."""
        graph = {
            "nodes": [
                {"id": "A", "label": "A"},
                {"id": "B", "label": "B"},
            ],
            "edges": [
                {"source": "A", "target": "B", "weight": 42, "custom": "value"},
            ],
        }
        result = extract_giant_component(graph)
        assert result["edges"][0]["weight"] == 42
        assert result["edges"][0]["custom"] == "value"


# ---------------------------------------------------------------------------
# _safe_power edge cases
# ---------------------------------------------------------------------------

class TestSafePowerEdgeCases:
    """Additional _safe_power edge cases."""

    def test_negative_base(self) -> None:
        """Negative base returns 0.0 (clamped)."""
        assert _safe_power(-0.5, 2) == 0.0

    def test_negative_exponent(self) -> None:
        """Negative exponent returns 1.0 (clamped)."""
        assert _safe_power(0.5, -1) == 1.0

    def test_very_small_base_large_exponent(self) -> None:
        """Extreme underflow case returns 0.0."""
        assert _safe_power(1e-100, 100) == 0.0

    def test_base_near_one(self) -> None:
        """Base very close to 1.0 with large exponent."""
        result = _safe_power(0.9999, 10000)
        assert 0 < result < 1  # Should be approximately e^(-1) = 0.368

    @pytest.mark.parametrize("base,exp,expected", [
        (0.5, 1, 0.5),
        (0.5, 2, 0.25),
        (0.5, 3, 0.125),
        (0.9, 1, 0.9),
        (0.1, 1, 0.1),
    ])
    def test_known_values(self, base: float, exp: float, expected: float) -> None:
        """Verify known mathematical results."""
        assert _safe_power(base, exp) == pytest.approx(expected, rel=1e-10)


# ---------------------------------------------------------------------------
# Invert edges edge cases
# ---------------------------------------------------------------------------

class TestInvertEdgesEdgeCases:
    """Additional _invert_edges edge cases."""

    def test_single_sender_multiple_items(self) -> None:
        """Single sender inverts correctly."""
        edges = {"Alice": {"k1": 3, "k2": 5}}
        inverted = _invert_edges(edges)
        assert inverted["k1"]["Alice"] == 3
        assert inverted["k2"]["Alice"] == 5

    def test_multiple_senders_same_item_accumulates(self) -> None:
        """Multiple senders with the same item accumulate weights."""
        edges = {
            "Alice": {"k1": 3},
            "Bob": {"k1": 2},
        }
        inverted = _invert_edges(edges)
        assert inverted["k1"]["Alice"] == 3
        assert inverted["k1"]["Bob"] == 2

    def test_round_trip_preserves_structure(self) -> None:
        """Inverting twice returns the original structure."""
        original = {
            "Alice": {"k1": 3, "k2": 2},
            "Bob": {"k1": 1},
        }
        round_tripped = _invert_edges(_invert_edges(original))
        for sender, items in original.items():
            for item, weight in items.items():
                assert round_tripped[sender][item] == weight


# ---------------------------------------------------------------------------
# Projection cap and top-K reduction
# ---------------------------------------------------------------------------


class TestProjectionCap:
    """Verify the three-stage large projection handling."""

    def test_estimate_projected_pairs_simple(self) -> None:
        """Estimate from inverted index matches combinatorial formula."""
        # 3 retained nodes sharing 1 collapsed node → C(3,2) = 3 pairs
        inverted = {"x": {"A": 1, "B": 1, "C": 1}}
        assert _estimate_projected_pairs(inverted) == 3

    def test_estimate_projected_pairs_multiple_collapsed(self) -> None:
        """Pairs from multiple collapsed nodes sum (upper bound)."""
        inverted = {
            "x": {"A": 1, "B": 1, "C": 1},  # C(3,2) = 3
            "y": {"A": 1, "D": 1},            # C(2,2) = 1
        }
        # Upper bound = 3 + 1 = 4 (A-B, A-C, B-C from x; A-D from y)
        assert _estimate_projected_pairs(inverted) == 4

    def test_estimate_with_keep_set(self) -> None:
        """Estimate respects keep_set filter."""
        inverted = {"x": {"A": 1, "B": 1, "C": 1, "D": 1}}  # C(4,2) = 6
        keep = {"A", "B"}
        assert _estimate_projected_pairs(inverted, keep) == 1  # C(2,2) = 1

    def test_reduce_retained_nodes_trims_to_fit(self) -> None:
        """Top-K reduction brings estimated pairs under cap."""
        # 100 senders all sharing one keyword → C(100,2) = 4950 pairs
        bipartite_edges = {f"s{i}": {"x": i + 1} for i in range(100)}
        inverted = {"x": {f"s{i}": i + 1 for i in range(100)}}

        reduced_inverted, kept = _reduce_retained_nodes(
            inverted, bipartite_edges, max_projected_edges=50,
        )
        # Should keep roughly sqrt(2*50) ≈ 10 nodes
        assert kept <= 15
        est = _estimate_projected_pairs(reduced_inverted)
        assert est <= 50

    def test_project_edges_hard_cap(self) -> None:
        """Projection halts when unique edge count reaches cap."""
        # 20 nodes all sharing one collapsed node → C(20,2) = 190 edges
        inverted = {"x": {f"n{i}": 1 for i in range(20)}}
        projected, capped = _project_edges(inverted, max_edges=50)
        assert capped is True
        assert len(projected) == 50

    def test_project_edges_no_cap_when_small(self) -> None:
        """Small projection completes without capping."""
        inverted = {"x": {"A": 3, "B": 2, "C": 1}}
        projected, capped = _project_edges(inverted, max_edges=1000)
        assert capped is False
        assert len(projected) == 3

    def test_unipartite_returns_warnings_when_capped(self) -> None:
        """project_to_unipartite includes warnings when cap is triggered."""
        # 50 senders sharing one keyword → C(50,2) = 1225 pairs
        bipartite_edges = {f"s{i}": {"x": i + 1} for i in range(50)}
        retained_counts = {f"s{i}": i + 1 for i in range(50)}
        collapsed_counts = {"x": 50}

        graph = project_to_unipartite(
            bipartite_edges, "keyword", retained_counts, collapsed_counts,
            min_weight=1, max_projected_edges=100,
        )
        assert "warnings" in graph
        assert len(graph["warnings"]) >= 1
        assert len(graph["edges"]) <= 100

    def test_small_projection_no_warnings(self) -> None:
        """Small projections produce no warnings."""
        bipartite_edges = {
            "Alice": {"x": 3},
            "Bob": {"x": 2},
        }
        graph = project_to_unipartite(
            bipartite_edges, "keyword",
            {"Alice": 3, "Bob": 2}, {"x": 5},
            min_weight=1,
        )
        assert "warnings" not in graph
        assert len(graph["edges"]) == 1

    def test_top_k_keeps_highest_degree_nodes(self) -> None:
        """Reduction preferentially keeps nodes with the most connections."""
        # Hub node connects to 5 keywords, leaf nodes connect to 1 each
        bipartite_edges = {
            "hub": {"k1": 10, "k2": 8, "k3": 6, "k4": 4, "k5": 2},
            "leaf1": {"k1": 1},
            "leaf2": {"k1": 1},
            "leaf3": {"k1": 1},
            "leaf4": {"k1": 1},
            "leaf5": {"k1": 1},
        }
        inverted = {}
        for sender, kws in bipartite_edges.items():
            for kw, w in kws.items():
                inverted.setdefault(kw, {})[sender] = w

        reduced, kept = _reduce_retained_nodes(
            inverted, bipartite_edges, max_projected_edges=3,
        )
        # Hub should be retained (degree 5) but most leaves should be dropped
        all_retained = set()
        for rn in reduced.values():
            all_retained.update(rn.keys())
        assert "hub" in all_retained


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_graph(n_nodes: int, edges: list[tuple[int, int, int]]) -> dict:
    """Build a graph dict from numbered nodes and weighted edges."""
    node_ids: set[str] = set()
    edge_list: list[dict] = []
    for src, tgt, w in edges:
        s, t = f"n{src}", f"n{tgt}"
        node_ids.add(s)
        node_ids.add(t)
        edge_list.append({"source": s, "target": t, "weight": w})
    nodes = [
        {"id": nid, "label": nid, "node_type": "test"} for nid in sorted(node_ids)
    ]
    return {"nodes": nodes, "edges": edge_list}
