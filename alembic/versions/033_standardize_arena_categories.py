"""Standardize arena column to 4 canonical categories.

Reclassifies the ``content_records.arena`` column from per-platform or
ad-hoc group names to the four canonical arena categories: news, search,
web, social_media.

Affected mappings:
- gdelt, rss_feeds, news_media (ritzau_via, event_registry) -> news
- domain_crawler records with arena='web' -> news
- google_search, google_autocomplete, ai_chat_search, reference -> search
- web, social_media -> unchanged

Revision ID: 033
Revises: 032
"""
from __future__ import annotations

from alembic import op

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Reclassify news arenas
    op.execute(
        "UPDATE content_records SET arena = 'news' "
        "WHERE arena IN ('gdelt', 'rss_feeds', 'news_media')"
    )
    # domain_crawler was 'web' but should be 'news'
    op.execute(
        "UPDATE content_records SET arena = 'news' "
        "WHERE arena = 'web' AND platform = 'domain_crawler'"
    )
    # Reclassify search arenas
    op.execute(
        "UPDATE content_records SET arena = 'search' "
        "WHERE arena IN ('google_search', 'google_autocomplete', 'ai_chat_search', 'reference')"
    )
    # 'web' and 'social_media' stay unchanged


def downgrade() -> None:
    # Reverse news -> original values using platform column
    op.execute(
        "UPDATE content_records SET arena = 'gdelt' "
        "WHERE arena = 'news' AND platform = 'gdelt'"
    )
    op.execute(
        "UPDATE content_records SET arena = 'rss_feeds' "
        "WHERE arena = 'news' AND platform = 'rss_feeds'"
    )
    op.execute(
        "UPDATE content_records SET arena = 'news_media' "
        "WHERE arena = 'news' AND platform IN ('ritzau_via', 'event_registry')"
    )
    op.execute(
        "UPDATE content_records SET arena = 'web' "
        "WHERE arena = 'news' AND platform = 'domain_crawler'"
    )
    # Reverse search -> original values using platform column
    op.execute(
        "UPDATE content_records SET arena = 'google_search' "
        "WHERE arena = 'search' AND platform = 'google_search'"
    )
    op.execute(
        "UPDATE content_records SET arena = 'google_autocomplete' "
        "WHERE arena = 'search' AND platform = 'google_autocomplete'"
    )
    op.execute(
        "UPDATE content_records SET arena = 'ai_chat_search' "
        "WHERE arena = 'search' AND platform = 'openrouter'"
    )
    op.execute(
        "UPDATE content_records SET arena = 'reference' "
        "WHERE arena = 'search' AND platform = 'wikipedia'"
    )
