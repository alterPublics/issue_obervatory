"""Pydantic request/response schemas for the content browser.

These schemas are used by the content API routes for validation,
serialisation, and OpenAPI documentation.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ContentRecordRead(BaseModel):
    """A single universal content record as returned by the API.

    Attributes:
        id: Unique content record identifier.
        platform: Source platform name (e.g. ``'youtube'``, ``'reddit'``).
        arena: Arena category (e.g. ``'social_media'``, ``'news_media'``).
        platform_id: Native ID on the source platform.
        content_type: Content type string (``'post'``, ``'video'``, etc.).
        text_content: Extracted or transcribed text body.
        title: Content title (articles, videos).
        url: Canonical URL of the content on the source platform.
        language: ISO 639-1 language code.
        published_at: Publication timestamp on the source platform.
        collected_at: Timestamp when the record was ingested.
        author_platform_id: Author's native user ID on the source platform.
        author_display_name: Author's display name at collection time.
        author_id: Resolved internal actor UUID (nullable).
        pseudonymized_author_id: SHA-256 pseudonym for GDPR-safe analytics.
        views_count: View/impression count (nullable).
        likes_count: Like/reaction count (nullable).
        shares_count: Share/retweet count (nullable).
        comments_count: Comment/reply count (nullable).
        engagement_score: Normalised cross-platform engagement score (nullable).
        collection_run_id: UUID of the collection run that ingested this record.
        query_design_id: UUID of the query design that triggered collection.
        search_terms_matched: Array of matched query terms.
        collection_tier: Tier used when this record was collected.
        content_hash: SHA-256 of normalised text (deduplication).
        media_urls: Array of media asset URLs (images, thumbnails).
        raw_metadata: Platform-specific payload (JSONB).
    """

    id: uuid.UUID
    platform: str
    arena: str
    platform_id: str | None
    content_type: str
    text_content: str | None
    title: str | None
    url: str | None
    language: str | None
    published_at: datetime | None
    collected_at: datetime
    author_platform_id: str | None
    author_display_name: str | None
    author_id: uuid.UUID | None
    pseudonymized_author_id: str | None
    views_count: int | None
    likes_count: int | None
    shares_count: int | None
    comments_count: int | None
    engagement_score: float | None
    collection_run_id: uuid.UUID | None
    query_design_id: uuid.UUID | None
    search_terms_matched: list[str] | None
    collection_tier: str
    content_hash: str | None
    media_urls: list[str] | None
    raw_metadata: dict | None

    model_config = ConfigDict(from_attributes=True)
