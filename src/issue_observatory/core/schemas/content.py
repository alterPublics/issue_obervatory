"""Pydantic request/response schemas for the content browser.

These schemas are used by the content API routes for validation,
serialisation, and OpenAPI documentation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

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
    platform_id: Optional[str]
    content_type: str
    text_content: Optional[str]
    title: Optional[str]
    url: Optional[str]
    language: Optional[str]
    published_at: Optional[datetime]
    collected_at: datetime
    author_platform_id: Optional[str]
    author_display_name: Optional[str]
    author_id: Optional[uuid.UUID]
    pseudonymized_author_id: Optional[str]
    views_count: Optional[int]
    likes_count: Optional[int]
    shares_count: Optional[int]
    comments_count: Optional[int]
    engagement_score: Optional[float]
    collection_run_id: Optional[uuid.UUID]
    query_design_id: Optional[uuid.UUID]
    search_terms_matched: Optional[list[str]]
    collection_tier: str
    content_hash: Optional[str]
    media_urls: Optional[list[str]]
    raw_metadata: Optional[dict]

    model_config = ConfigDict(from_attributes=True)
