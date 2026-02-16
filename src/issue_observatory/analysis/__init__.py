"""Analysis modules: descriptive statistics, network analysis, and data export."""

from __future__ import annotations

from issue_observatory.analysis.descriptive import (
    DescriptiveStats,
    get_engagement_distribution,
    get_run_summary,
    get_top_actors,
    get_top_terms,
    get_volume_over_time,
)
from issue_observatory.analysis.export import ContentExporter
from issue_observatory.analysis.network import (
    build_bipartite_network,
    get_actor_co_occurrence,
    get_cross_platform_actors,
    get_term_co_occurrence,
)

__all__ = [
    # descriptive
    "DescriptiveStats",
    "get_volume_over_time",
    "get_top_actors",
    "get_top_terms",
    "get_engagement_distribution",
    "get_run_summary",
    # network
    "get_actor_co_occurrence",
    "get_term_co_occurrence",
    "get_cross_platform_actors",
    "build_bipartite_network",
    # export
    "ContentExporter",
]
