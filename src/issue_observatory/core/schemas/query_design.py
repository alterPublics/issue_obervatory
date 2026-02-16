"""Pydantic request/response schemas for query designs and search terms.

These schemas are used by the query-designs API routes for validation,
serialisation, and OpenAPI documentation generation.  They are kept
separate from the SQLAlchemy ORM models in ``core/models/query_design.py``
to avoid coupling transport concerns to persistence concerns.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SearchTermCreate(BaseModel):
    """Payload for adding a new search term to a query design.

    Attributes:
        term: The search term string (keyword, phrase, hashtag, or URL pattern).
        term_type: How arena collectors should interpret this term.
            One of ``'keyword'``, ``'phrase'``, ``'hashtag'``, ``'url_pattern'``.
    """

    term: str = Field(..., min_length=1, description="The search term string.")
    term_type: str = Field(
        default="keyword",
        description="Interpretation type: keyword, phrase, hashtag, url_pattern.",
    )


class SearchTermRead(SearchTermCreate):
    """Full representation of a persisted search term.

    Extends ``SearchTermCreate`` with database-generated fields.

    Attributes:
        id: Unique identifier of the search term.
        query_design_id: Parent query design UUID.
        is_active: Whether the term is currently active.
        added_at: Timestamp when the term was added.
    """

    id: uuid.UUID
    query_design_id: uuid.UUID
    is_active: bool
    added_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QueryDesignCreate(BaseModel):
    """Payload for creating a new query design.

    Attributes:
        name: Human-readable name for this research design (max 200 chars).
        description: Optional free-text description of the research purpose.
        visibility: Access control level — ``'private'``, ``'team'``, or ``'public'``.
        default_tier: Default collection tier — ``'free'``, ``'medium'``, or ``'premium'``.
        language: ISO 639-1 language code for locale-aware arena filters (e.g. ``'da'``).
        locale_country: ISO 3166-1 alpha-2 country code for geo filters (e.g. ``'dk'``).
        search_terms: Initial list of search terms to attach on creation.
    """

    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    visibility: str = Field(default="private", pattern="^(private|team|public)$")
    default_tier: str = Field(default="free", pattern="^(free|medium|premium)$")
    language: str = Field(default="da", max_length=10)
    locale_country: str = Field(default="dk", max_length=5)
    search_terms: list[SearchTermCreate] = Field(default_factory=list)


class QueryDesignRead(BaseModel):
    """Full representation of a persisted query design.

    Returned by detail and list endpoints.  ``search_terms`` is populated
    on detail fetches where the relationship is eagerly loaded.

    Attributes:
        id: Unique identifier of the query design.
        owner_id: UUID of the user who owns this design.
        name: Human-readable name.
        description: Optional research purpose description.
        visibility: Access control level.
        created_at: Timestamp of initial creation.
        updated_at: Timestamp of last modification.
        is_active: Whether the design is active (soft-delete flag).
        default_tier: Default collection tier.
        language: ISO 639-1 language code.
        locale_country: ISO 3166-1 alpha-2 country code.
        search_terms: Attached search terms (may be empty on list views).
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: Optional[str]
    visibility: str
    created_at: datetime
    updated_at: datetime
    is_active: bool
    default_tier: str
    language: str
    locale_country: str
    search_terms: list[SearchTermRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class QueryDesignUpdate(BaseModel):
    """Partial update payload for a query design.

    All fields are optional; only provided fields are applied.  Send an
    empty body to perform a no-op update (useful for testing ownership).

    Attributes:
        name: New name (max 200 chars).
        description: New description (pass ``null`` to clear).
        visibility: New visibility level.
        default_tier: New default tier.
        is_active: Set to ``false`` to soft-delete.
    """

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    visibility: Optional[str] = Field(default=None, pattern="^(private|team|public)$")
    default_tier: Optional[str] = Field(
        default=None, pattern="^(free|medium|premium)$"
    )
    is_active: Optional[bool] = None
