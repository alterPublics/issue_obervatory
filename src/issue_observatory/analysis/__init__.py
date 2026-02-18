"""Analysis modules: descriptive statistics, network analysis, and data export."""

from __future__ import annotations

from issue_observatory.analysis._filters import build_content_filters, build_content_where
from issue_observatory.analysis.descriptive import (
    DescriptiveStats,
    get_emergent_terms,
    get_engagement_distribution,
    get_run_summary,
    get_top_actors,
    get_top_actors_unified,
    get_top_terms,
    get_volume_over_time,
)
from issue_observatory.analysis.export import ContentExporter
from issue_observatory.analysis.network import (
    build_bipartite_network,
    build_enhanced_bipartite_network,
    get_actor_co_occurrence,
    get_cross_platform_actors,
    get_temporal_network_snapshots,
    get_term_co_occurrence,
)

__all__ = [
    # filters (shared between descriptive and network)
    "build_content_filters",
    "build_content_where",
    # descriptive
    "DescriptiveStats",
    "get_volume_over_time",
    "get_top_actors",
    "get_top_actors_unified",
    "get_top_terms",
    "get_emergent_terms",
    "get_engagement_distribution",
    "get_run_summary",
    # network
    "get_actor_co_occurrence",
    "get_term_co_occurrence",
    "get_cross_platform_actors",
    "build_bipartite_network",
    "build_enhanced_bipartite_network",
    "get_temporal_network_snapshots",
    # export
    "ContentExporter",
]
