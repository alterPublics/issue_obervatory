"""Unit tests for network construction utilities.

Tests the pure-Python network graph functions: bipartite construction,
unipartite projection, edge inversion, and giant component extraction.
These functions operate on dicts, not on the database.
"""
from __future__ import annotations

from issue_observatory.analysis.network_builder import (
    _build_bipartite,
    _invert_edges,
    extract_giant_component,
    project_to_unipartite,
)


class TestBuildBipartite:
    """Verify bipartite graph construction from sender-item edges."""

    def test_basic_bipartite(self) -> None:
        """Builds nodes and edges from sender-keyword pairs."""
        sender_items = {
            "Alice": {"klima": 3, "energi": 2},
            "Bob": {"klima": 1},
        }
        sender_counts = {"Alice": 5, "Bob": 2}
        item_counts = {"klima": 4, "energi": 2}

        graph = _build_bipartite(sender_items, sender_counts, item_counts, "keyword", 1)

        node_ids = {n["id"] for n in graph["nodes"]}
        assert "sender:Alice" in node_ids
        assert "sender:Bob" in node_ids
        assert "keyword:klima" in node_ids
        assert "keyword:energi" in node_ids
        assert len(graph["edges"]) == 3  # Alice->klima, Alice->energi, Bob->klima

    def test_min_weight_filters_edges(self) -> None:
        """Edges below min_weight are excluded."""
        sender_items = {
            "Alice": {"klima": 5, "energi": 1},
        }
        graph = _build_bipartite(
            sender_items, {"Alice": 6}, {"klima": 5, "energi": 1}, "keyword", min_weight=3
        )
        edge_targets = {e["target"] for e in graph["edges"]}
        assert "keyword:klima" in edge_targets
        assert "keyword:energi" not in edge_targets

    def test_node_types_correct(self) -> None:
        """Sender nodes have type 'sender', item nodes have the specified type."""
        sender_items = {"Alice": {"klima": 1}}
        graph = _build_bipartite(
            sender_items, {"Alice": 1}, {"klima": 1}, "keyword", 1
        )
        node_types = {n["id"]: n["node_type"] for n in graph["nodes"]}
        assert node_types["sender:Alice"] == "sender"
        assert node_types["keyword:klima"] == "keyword"

    def test_empty_input(self) -> None:
        """Empty sender_items produces empty graph."""
        graph = _build_bipartite({}, {}, {}, "keyword", 1)
        assert graph["nodes"] == []
        assert graph["edges"] == []


class TestInvertEdges:
    """Verify edge dict inversion (sender->item to item->sender)."""

    def test_basic_inversion(self) -> None:
        """Inverts sender->item to item->sender."""
        edges = {
            "Alice": {"klima": 3, "energi": 2},
            "Bob": {"klima": 1},
        }
        inverted = _invert_edges(edges)

        assert "klima" in inverted
        assert inverted["klima"]["Alice"] == 3
        assert inverted["klima"]["Bob"] == 1
        assert inverted["energi"]["Alice"] == 2

    def test_empty_inversion(self) -> None:
        """Inverting empty dict returns empty dict."""
        assert _invert_edges({}) == {}


class TestProjectToUnipartite:
    """Verify bipartite-to-unipartite projection."""

    def test_shared_neighbors_create_edge(self) -> None:
        """Two senders sharing a keyword get connected in the unipartite projection."""
        bipartite_edges = {
            "Alice": {"klima": 3},
            "Bob": {"klima": 2},
        }
        retained_counts = {"Alice": 5, "Bob": 3}
        collapsed_counts = {"klima": 5}

        graph = project_to_unipartite(
            bipartite_edges, "keyword", retained_counts, collapsed_counts, min_weight=1
        )

        assert len(graph["edges"]) == 1
        edge = graph["edges"][0]
        # weight = min(3, 2) = 2
        assert edge["weight"] == 2
        edge_nodes = {edge["source"], edge["target"]}
        assert edge_nodes == {"Alice", "Bob"}

    def test_no_shared_neighbors_no_edge(self) -> None:
        """Senders with disjoint keywords produce no edges."""
        bipartite_edges = {
            "Alice": {"klima": 3},
            "Bob": {"energi": 2},
        }
        graph = project_to_unipartite(
            bipartite_edges, "keyword",
            {"Alice": 3, "Bob": 2}, {"klima": 3, "energi": 2}, 1
        )
        assert len(graph["edges"]) == 0

    def test_multiple_shared_neighbors_sum_weights(self) -> None:
        """Projection weight sums min-weights across all shared neighbors."""
        bipartite_edges = {
            "Alice": {"klima": 4, "energi": 2},
            "Bob": {"klima": 1, "energi": 5},
        }
        graph = project_to_unipartite(
            bipartite_edges, "keyword",
            {"Alice": 6, "Bob": 6},
            {"klima": 5, "energi": 7}, 1,
        )
        # weight = min(4,1) + min(2,5) = 1 + 2 = 3
        assert graph["edges"][0]["weight"] == 3

    def test_min_weight_on_projection(self) -> None:
        """Projected edges below min_weight are excluded."""
        bipartite_edges = {
            "Alice": {"klima": 1},
            "Bob": {"klima": 1},
        }
        graph = project_to_unipartite(
            bipartite_edges, "keyword",
            {"Alice": 1, "Bob": 1}, {"klima": 2}, min_weight=5,
        )
        assert len(graph["edges"]) == 0


class TestExtractGiantComponent:
    """Verify BFS-based connected component extraction."""

    def test_single_component_unchanged(self) -> None:
        """A fully connected graph returns the same nodes and edges."""
        graph = {
            "nodes": [
                {"id": "A", "label": "A"},
                {"id": "B", "label": "B"},
                {"id": "C", "label": "C"},
            ],
            "edges": [
                {"source": "A", "target": "B", "weight": 1},
                {"source": "B", "target": "C", "weight": 1},
            ],
        }
        result = extract_giant_component(graph)
        assert len(result["nodes"]) == 3
        assert len(result["edges"]) == 2

    def test_two_components_returns_larger(self) -> None:
        """With two components, returns the one with more nodes."""
        graph = {
            "nodes": [
                {"id": "A", "label": "A"},
                {"id": "B", "label": "B"},
                {"id": "C", "label": "C"},
                {"id": "X", "label": "X"},
                {"id": "Y", "label": "Y"},
            ],
            "edges": [
                {"source": "A", "target": "B", "weight": 1},
                {"source": "B", "target": "C", "weight": 1},
                {"source": "X", "target": "Y", "weight": 1},
            ],
        }
        result = extract_giant_component(graph)
        node_ids = {n["id"] for n in result["nodes"]}
        assert node_ids == {"A", "B", "C"}
        assert len(result["edges"]) == 2

    def test_empty_graph(self) -> None:
        """Empty graph returns empty graph."""
        graph = {"nodes": [], "edges": []}
        result = extract_giant_component(graph)
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_isolated_node_smallest_component(self) -> None:
        """Isolated nodes form their own 1-node components."""
        graph = {
            "nodes": [
                {"id": "A", "label": "A"},
                {"id": "B", "label": "B"},
                {"id": "C", "label": "C"},  # isolated
            ],
            "edges": [
                {"source": "A", "target": "B", "weight": 1},
            ],
        }
        result = extract_giant_component(graph)
        node_ids = {n["id"] for n in result["nodes"]}
        assert node_ids == {"A", "B"}

    def test_preserves_node_attributes(self) -> None:
        """Giant component extraction preserves node metadata."""
        graph = {
            "nodes": [
                {"id": "A", "label": "Alice", "node_type": "sender", "doc_count": 10},
                {"id": "B", "label": "Bob", "node_type": "sender", "doc_count": 5},
            ],
            "edges": [
                {"source": "A", "target": "B", "weight": 3},
            ],
        }
        result = extract_giant_component(graph)
        node_a = next(n for n in result["nodes"] if n["id"] == "A")
        assert node_a["label"] == "Alice"
        assert node_a["doc_count"] == 10
