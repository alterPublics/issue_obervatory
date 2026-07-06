"""Tests for network size enforcement and disparity filter backboning."""
from __future__ import annotations

import pytest

from issue_observatory.analysis.network_builder import (
    _apply_disparity_backbone,
    _safe_power,
    enforce_network_limits,
)


def _make_graph(n_nodes: int, edges: list[tuple[int, int, int]]) -> dict:
    """Helper: build a graph dict from numbered nodes and weighted edges."""
    node_ids = set()
    edge_list = []
    for src, tgt, w in edges:
        s, t = f"n{src}", f"n{tgt}"
        node_ids.add(s)
        node_ids.add(t)
        edge_list.append({"source": s, "target": t, "weight": w})
    nodes = [{"id": nid, "label": nid, "node_type": "test"} for nid in sorted(node_ids)]
    return {"nodes": nodes, "edges": edge_list}


class TestSafePower:
    def test_normal(self) -> None:
        assert _safe_power(0.5, 2) == pytest.approx(0.25)

    def test_zero_base(self) -> None:
        assert _safe_power(0.0, 5) == 0.0

    def test_one_base(self) -> None:
        assert _safe_power(1.0, 100) == 1.0

    def test_zero_exponent(self) -> None:
        assert _safe_power(0.5, 0) == 1.0

    def test_underflow(self) -> None:
        assert _safe_power(1e-10, 1000) == 0.0


class TestDisparityBackbone:
    def test_keeps_significant_edges(self) -> None:
        """Star graph: one very strong edge among many weak ones."""
        edges = [(0, i, 1) for i in range(1, 11)]  # 10 weak edges
        edges.append((0, 11, 50))  # 1 strong edge
        graph = _make_graph(12, edges)

        result = _apply_disparity_backbone(graph, alpha=0.05)
        # The strong edge must survive
        strong = [e for e in result["edges"] if e["weight"] == 50]
        assert len(strong) == 1
        # Most weak edges should be removed
        assert len(result["edges"]) < len(graph["edges"])

    def test_empty_graph(self) -> None:
        graph = {"nodes": [], "edges": []}
        result = _apply_disparity_backbone(graph, alpha=0.05)
        assert result["nodes"] == []
        assert result["edges"] == []


class TestEnforceNetworkLimits:
    def test_small_graph_unchanged(self) -> None:
        graph = _make_graph(3, [(0, 1, 1), (1, 2, 1)])
        result = enforce_network_limits(graph)
        assert len(result["nodes"]) == 3
        assert "reduced" not in result

    def test_degree_filtering_applied(self) -> None:
        """Graph with many degree-1 leaf nodes should get trimmed."""
        # Hub connected to 600 leaves (each with degree 1)
        edges = [(0, i, 1) for i in range(1, 601)]
        graph = _make_graph(601, edges)
        assert len(graph["nodes"]) == 601

        result = enforce_network_limits(graph, max_nodes=500, max_edges=5000)
        # All leaves have degree 1, so after filtering the graph
        # should be empty (hub also loses all edges)
        assert "reduced" in result
        assert len(result["nodes"]) <= 500

    def test_large_clique_triggers_backbone(self) -> None:
        """Dense graph that survives degree filtering should get backboned."""
        # Build a graph where every node has degree >= 2 but > 500 nodes
        n = 520
        edges = []
        for i in range(n):
            edges.append((i, (i + 1) % n, 1))  # ring: degree 2 each
        # Add a few extra strong edges to ensure some survive backboning
        for i in range(0, n, 50):
            edges.append((i, (i + 2) % n, 100))

        graph = _make_graph(n, edges)
        assert len(graph["nodes"]) == n

        result = enforce_network_limits(graph, max_nodes=500, max_edges=5000)
        assert "reduced" in result
        assert len(result["nodes"]) <= 500
        assert len(result["edges"]) <= 5000

    def test_edge_limit_respected(self) -> None:
        """Graph within node limit but over edge limit."""
        # 50 nodes forming a near-complete graph
        edges = []
        for i in range(50):
            for j in range(i + 1, 50):
                edges.append((i, j, 1))
        graph = _make_graph(50, edges)
        assert len(graph["edges"]) > 1000  # 50*49/2 = 1225

        result = enforce_network_limits(graph, max_nodes=500, max_edges=1000)
        assert len(result["edges"]) <= 1000
