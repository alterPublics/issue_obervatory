"""Shared query helpers for the Issue Observatory core layer.

Re-exports the public API from :mod:`content_filters` so callers can
write ``from issue_observatory.core.queries import ContentFilterSpec``.
"""

from __future__ import annotations

from issue_observatory.core.queries.content_filters import (
    ContentFilterSpec,
    apply_content_filters,
    build_browse_stmt,
    build_content_where_sql,
    build_count_stmt,
)

__all__ = [
    "ContentFilterSpec",
    "apply_content_filters",
    "build_browse_stmt",
    "build_content_where_sql",
    "build_count_stmt",
]
