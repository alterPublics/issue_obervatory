"""Pydantic request/response schemas for annotation codebook management.

These schemas are used by the codebook API routes for validation, serialisation,
and OpenAPI documentation generation. They are kept separate from the SQLAlchemy
ORM models to avoid coupling transport concerns to persistence concerns.

The codebook feature provides structured qualitative coding for content annotations.
Instead of free-text codes, researchers can define and manage a controlled vocabulary
of codes with labels and descriptions, either globally or scoped to specific query designs.

BLOCKING DEPENDENCY: This module requires a ``CodebookEntry`` model to be created
by the DB Engineer in ``core/models/annotations.py`` with the following schema:

    - id: UUID primary key
    - code: str (unique per query_design_id, max 100 chars)
    - label: str (human-readable display name, max 200 chars)
    - description: Optional[str] (longer explanation, nullable)
    - category: Optional[str] (grouping label like "stance", "frame", max 100 chars)
    - query_design_id: Optional[UUID] (NULL = global codebook, FK to query_designs)
    - created_by: Optional[UUID] (FK to users, SET NULL on delete)
    - created_at: datetime (auto)
    - updated_at: datetime (auto)

    Unique constraint: (query_design_id, code)
    Indexes: query_design_id, created_by
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CodebookEntryCreate(BaseModel):
    """Payload for creating a new codebook entry.

    Attributes:
        code: Short identifier used in annotations (e.g. "punitive_frame",
            "empathetic"). Must be unique within the query_design_id scope.
            Max 100 characters. Should be lowercase_with_underscores by
            convention but not enforced.
        label: Human-readable display name for the UI (e.g. "Punitive Framing").
            Max 200 characters.
        description: Optional longer explanation of when to apply this code.
            Useful for training coders or documenting the coding scheme.
        category: Optional grouping label (e.g. "stance", "frame", "relevance").
            Used to organize codes in the UI. Max 100 characters.
        query_design_id: Optional UUID of the query design this codebook entry
            belongs to. NULL creates a global codebook entry visible to all
            researchers (admin-only). Non-admin users must provide a query_design_id
            they own.
    """

    code: str = Field(..., min_length=1, max_length=100)
    label: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(default=None)
    category: Optional[str] = Field(default=None, max_length=100)
    query_design_id: Optional[uuid.UUID] = Field(default=None)


class CodebookEntryUpdate(BaseModel):
    """Payload for partially updating a codebook entry.

    All fields are optional — only fields explicitly included in the request
    body are applied to the stored record. The ``code`` field should generally
    not be changed after creation if annotations already reference it, to avoid
    orphaning those annotations.

    Attributes:
        code: New short identifier. WARNING: changing this will orphan existing
            annotations that reference the old code unless you also update those
            annotations.
        label: New human-readable display name.
        description: New description text.
        category: New category grouping.
    """

    code: Optional[str] = Field(default=None, min_length=1, max_length=100)
    label: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None)
    category: Optional[str] = Field(default=None, max_length=100)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class CodebookEntryRead(BaseModel):
    """Full representation of a persisted codebook entry.

    Attributes:
        id: Unique identifier of the codebook entry.
        code: Short identifier used in annotations.
        label: Human-readable display name.
        description: Optional longer explanation.
        category: Optional grouping label.
        query_design_id: UUID of the owning query design, or NULL for global entries.
        created_by: UUID of the user who created this entry (NULL if created by
            a deleted user).
        created_at: Creation timestamp.
        updated_at: Last modification timestamp.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    label: str
    description: Optional[str]
    category: Optional[str]
    query_design_id: Optional[uuid.UUID]
    created_by: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime


class CodebookListResponse(BaseModel):
    """Response for listing codebook entries with optional metadata.

    Attributes:
        entries: List of codebook entries matching the query.
        total: Total count of entries (before pagination if implemented).
        query_design_id: The query_design_id filter that was applied, if any.
    """

    entries: list[CodebookEntryRead]
    total: int
    query_design_id: Optional[uuid.UUID] = None
