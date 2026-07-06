"""RAKE keyword extraction for content analysis.

Extracts keywords from content records using multi_rake, which has
built-in Danish stopword support. Supports full-content and window mode
(N words around search term occurrences).
"""
from __future__ import annotations

import re
import uuid
from bisect import bisect_left
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from issue_observatory.core.queries.content_filters import (
    ContentFilterSpec,
    build_content_where_sql,
)

logger = structlog.get_logger(__name__)


def _extract_window(content: str, search_terms: list[str], window_size: int) -> str:
    """Extract text windows of N words around each search term occurrence."""
    if not content or not search_terms:
        return content

    matches = list(re.finditer(r"\S+", content))
    if not matches:
        return content

    words = [m.group() for m in matches]
    starts = [m.start() for m in matches]
    n_words = len(words)

    included_indices: set[int] = set()
    content_lower = content.lower()

    for term in search_terms:
        term_lower = term.lower()
        if not term_lower:
            continue
        start = 0
        while True:
            idx = content_lower.find(term_lower, start)
            if idx == -1:
                break
            word_idx = max(0, bisect_left(starts, idx) - 1)
            lo = max(0, word_idx - window_size)
            hi = min(n_words, word_idx + window_size + 1)
            for i in range(lo, hi):
                included_indices.add(i)
            start = idx + len(term_lower)

    if not included_indices:
        return content

    return " ".join(words[i] for i in sorted(included_indices))


async def extract_rake_keywords(
    db: AsyncSession,
    query_design_ids: list[uuid.UUID] | None = None,
    platform: str | None = None,
    arena_category: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search_terms: list[str] | None = None,
    window_size: int | None = None,
    min_keyword_score: float = 1.0,
    max_keywords_per_doc: int = 20,
    batch_size: int = 500,
) -> list[dict]:
    """Extract RAKE keywords from content records.

    Args:
        db: Async database session.
        query_design_ids: Filter by query designs.
        platform: Filter by platform.
        arena_category: Filter by arena category.
        date_from: Start date filter.
        date_to: End date filter.
        search_terms: Terms to look for in window mode.
        window_size: If set, extract N words around search term occurrences.
        min_keyword_score: Minimum RAKE score to include.
        max_keywords_per_doc: Max keywords per document.
        batch_size: Processing batch size.

    Returns:
        List of dicts with keyword, score, and doc_count.
    """
    try:
        from multi_rake import Rake
    except ImportError:
        logger.warning("multi_rake not installed, returning empty keywords")
        return []

    rake = Rake(language_code="da")

    params: dict[str, Any] = {}
    _arena_kw = (
        [arena_category]
        if isinstance(arena_category, str) and arena_category
        else []
    )
    _platform_kw = (
        [platform] if isinstance(platform, str) and platform else []
    )
    spec_kw = ContentFilterSpec(
        query_design_ids=query_design_ids or [],
        arenas=_arena_kw,
        platforms=_platform_kw,
        date_from=date_from,
        date_to=date_to,
        include_linked=True,
        include_duplicates=False,
        ownership_mode="admin",
    )
    where = build_content_where_sql(spec_kw, table_alias="", params=params)

    # Count total records
    count_sql = text(
        f"SELECT COUNT(*) FROM content_records {where} "
        f"AND text_content IS NOT NULL AND LENGTH(text_content) > 50"
    )
    total = (await db.execute(count_sql, params)).scalar() or 0

    if total == 0:
        return []

    # Accumulate keyword frequencies
    keyword_scores: dict[str, float] = {}
    keyword_counts: dict[str, int] = {}

    offset = 0
    while offset < total:
        batch_params = {**params, "_limit": batch_size, "_offset": offset}
        sql = text(
            f"SELECT text_content FROM content_records {where} "
            f"AND text_content IS NOT NULL AND LENGTH(text_content) > 50 "
            f"ORDER BY published_at DESC LIMIT :_limit OFFSET :_offset"
        )
        rows = (await db.execute(sql, batch_params)).fetchall()
        if not rows:
            break

        for row in rows:
            content = row[0]
            if window_size and search_terms:
                content = _extract_window(content, search_terms, window_size)

            try:
                keywords = rake.apply(content)
            except Exception:
                continue

            seen_in_doc: set[str] = set()
            for kw, score in keywords[:max_keywords_per_doc]:
                if score < min_keyword_score:
                    continue
                kw_lower = kw.lower().strip()
                if len(kw_lower) < 2:
                    continue
                if kw_lower not in seen_in_doc:
                    keyword_counts[kw_lower] = keyword_counts.get(kw_lower, 0) + 1
                    seen_in_doc.add(kw_lower)
                keyword_scores[kw_lower] = max(
                    keyword_scores.get(kw_lower, 0.0), score
                )

        offset += batch_size

    # Build result sorted by doc_count descending
    result = [
        {"keyword": kw, "score": keyword_scores[kw], "doc_count": keyword_counts[kw]}
        for kw in keyword_counts
    ]
    result.sort(key=lambda x: x["doc_count"], reverse=True)
    return result
