"""Pydantic request/response schemas for project management.

Projects are organizational containers that group related query designs together.
These schemas are used by the project API routes for validation, serialization,
and OpenAPI documentation generation.

Owned by the DB Engineer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    """Payload for creating a new project.

    Attributes:
        name: Human-readable project name. Max 200 characters.
        description: Optional detailed description of the project purpose.
        visibility: Access control level ('private' or 'shared').
            Defaults to 'private'.
    """

    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(default=None)
    visibility: str = Field(default="private", pattern="^(private|shared)$")


class ProjectUpdate(BaseModel):
    """Payload for partially updating a project.

    All fields are optional — only fields explicitly included in the request
    body are applied to the stored record.

    Attributes:
        name: New project name. Max 200 characters.
        description: New project description.
        visibility: New access control level ('private' or 'shared').
    """

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None)
    visibility: Optional[str] = Field(default=None, pattern="^(private|shared)$")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ProjectRead(BaseModel):
    """Response schema for a single project.

    Attributes:
        id: Unique project identifier.
        name: Project name.
        description: Project description (may be null).
        owner_id: UUID of the user who owns this project.
        visibility: Access control level.
        created_at: Timestamp when the project was created.
        updated_at: Timestamp of last modification.
        query_design_count: Number of query designs attached to this project.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: Optional[str]
    owner_id: uuid.UUID
    visibility: str
    created_at: datetime
    updated_at: datetime
    query_design_count: int = 0


class ProjectListResponse(BaseModel):
    """Response schema for listing projects.

    Attributes:
        projects: List of project summaries.
        total: Total number of projects matching the query (for pagination).
    """

    projects: list[ProjectRead]
    total: int
