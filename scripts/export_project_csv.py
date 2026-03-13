"""Quick manual CSV export of all content records for a project.

Usage:
    uv run python scripts/export_project_csv.py <project_name_or_id> [output.csv]

Exports ALL records (posts + comments, term-matched or not) using the same
column format as the built-in export function.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime

from sqlalchemy import text

from issue_observatory.core.database import get_sync_session

COLUMNS = [
    "platform",
    "arena",
    "content_type",
    "title",
    "text_content",
    "url",
    "author_display_name",
    "pseudonymized_author_id",
    "published_at",
    "views_count",
    "likes_count",
    "shares_count",
    "comments_count",
    "engagement_score",
    "language",
    "collection_tier",
    "search_terms_matched",
    "content_hash",
    "collection_run_id",
    "query_design_id",
    "raw_metadata",
]

HEADERS = {
    "platform": "Platform",
    "arena": "Arena",
    "content_type": "Content Type",
    "title": "Title",
    "text_content": "Text Content",
    "url": "URL",
    "author_display_name": "Author",
    "pseudonymized_author_id": "Author ID (Pseudonymized)",
    "published_at": "Published At",
    "views_count": "Views",
    "likes_count": "Likes",
    "shares_count": "Shares",
    "comments_count": "Comments",
    "engagement_score": "Engagement Score",
    "language": "Language",
    "collection_tier": "Collection Tier",
    "search_terms_matched": "Matched Search Terms",
    "content_hash": "Content Hash",
    "collection_run_id": "Collection Run ID",
    "query_design_id": "Query Design ID",
    "raw_metadata": "Raw Metadata (JSON)",
}


def _safe(val):
    if val is None:
        return ""
    if isinstance(val, list):
        return " | ".join(str(v) for v in val)
    if isinstance(val, dict):
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, datetime):
        return val.isoformat()
    return str(val)


def find_project_id(session, name_or_id: str) -> str:
    """Resolve a project name or UUID to its ID."""
    # Try UUID first
    row = session.execute(
        text("SELECT id, name FROM projects WHERE id::text = :val"),
        {"val": name_or_id},
    ).fetchone()
    if row:
        print(f"Project: {row[1]} ({row[0]})")
        return str(row[0])

    # Try name (case-insensitive)
    row = session.execute(
        text("SELECT id, name FROM projects WHERE LOWER(name) LIKE LOWER(:val)"),
        {"val": f"%{name_or_id}%"},
    ).fetchone()
    if row:
        print(f"Project: {row[1]} ({row[0]})")
        return str(row[0])

    print(f"No project found matching '{name_or_id}'")
    print("\nAvailable projects:")
    for r in session.execute(text("SELECT id, name FROM projects ORDER BY name")).fetchall():
        print(f"  {r[1]}  ({r[0]})")
    sys.exit(1)


def export(project_id: str, output_path: str):
    sql = text("""
        SELECT
            cr.platform,
            cr.arena,
            cr.content_type,
            cr.title,
            cr.text_content,
            cr.url,
            cr.author_display_name,
            cr.pseudonymized_author_id,
            cr.published_at,
            cr.views_count,
            cr.likes_count,
            cr.shares_count,
            cr.comments_count,
            cr.engagement_score,
            cr.language,
            cr.collection_tier,
            cr.search_terms_matched,
            cr.content_hash,
            cr.collection_run_id,
            cr.query_design_id,
            cr.raw_metadata
        FROM content_records cr
        WHERE cr.collection_run_id IN (
            SELECT id FROM collection_runs WHERE project_id = CAST(:project_id AS uuid)
        )
        ORDER BY cr.published_at DESC NULLS LAST
    """)

    with get_sync_session() as db:
        result = db.execute(sql, {"project_id": project_id})
        rows = result.fetchall()

    print(f"Found {len(rows)} records")

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, lineterminator="\r\n")
        writer.writerow([HEADERS[c] for c in COLUMNS])
        for row in rows:
            writer.writerow([_safe(row[i]) for i in range(len(COLUMNS))])

    print(f"Exported to {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/export_project_csv.py <project_name_or_id> [output.csv]")
        sys.exit(1)

    name_or_id = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) > 2 else f"export_{name_or_id}.csv"

    with get_sync_session() as db:
        pid = find_project_id(db, name_or_id)

    export(pid, output)
