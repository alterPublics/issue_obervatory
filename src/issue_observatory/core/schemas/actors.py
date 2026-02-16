"""Pydantic request/response schemas for actors and platform presences.

These schemas are used by the actors API routes for validation, serialisation,
and OpenAPI documentation generation.  They are kept separate from the
SQLAlchemy ORM models in ``core/models/actors.py`` to avoid coupling transport
concerns to persistence concerns.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Platform presence schemas
# ---------------------------------------------------------------------------


class ActorPresenceCreate(BaseModel):
    """Payload for adding a new platform presence to an actor.

    Attributes:
        platform: Short platform slug (e.g. ``'bluesky'``, ``'reddit'``).
        platform_user_id: Platform-native numeric or string user ID.
        platform_username: Human-readable handle or username on the platform.
        profile_url: Full URL to the actor's public profile page.
    """

    platform: str = Field(..., min_length=1, max_length=50)
    platform_user_id: Optional[str] = Field(default=None, max_length=500)
    platform_username: Optional[str] = Field(default=None, max_length=500)
    profile_url: Optional[str] = Field(default=None, max_length=2000)


class PresenceResponse(BaseModel):
    """Full representation of a persisted platform presence.

    Attributes:
        id: Unique identifier of the presence record.
        actor_id: UUID of the parent actor.
        platform: Short platform slug.
        platform_user_id: Platform-native user identifier.
        platform_username: Human-readable username.
        profile_url: Full URL to the public profile.
        verified: Whether this presence has been manually verified.
        follower_count: Last known follower count (nullable).
        last_checked_at: Timestamp of the most recent verification check.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_id: uuid.UUID
    platform: str
    platform_user_id: Optional[str]
    platform_username: Optional[str]
    profile_url: Optional[str]
    verified: bool
    follower_count: Optional[int]
    last_checked_at: Optional[datetime]


# ---------------------------------------------------------------------------
# Actor schemas
# ---------------------------------------------------------------------------


class ActorCreate(BaseModel):
    """Payload for creating a new actor.

    Attributes:
        canonical_name: The authoritative display name for the actor.
        actor_type: Free-form type label (e.g. ``'person'``, ``'outlet'``).
        description: Optional longer description or biography.
        is_shared: When ``True``, the actor is visible to all researchers.
        presence: Optional initial platform presence to attach on creation.
    """

    canonical_name: str = Field(..., min_length=1, max_length=500)
    actor_type: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = Field(default=None)
    is_shared: bool = Field(default=False)
    presence: Optional[ActorPresenceCreate] = Field(default=None)


class ActorUpdate(BaseModel):
    """Payload for partially updating an actor.

    All fields are optional — only fields explicitly included in the request
    body are applied to the stored record.

    Attributes:
        canonical_name: New canonical name for the actor.
        actor_type: New type label.
        description: New description text.
        is_shared: New sharing visibility flag.
    """

    canonical_name: Optional[str] = Field(default=None, min_length=1, max_length=500)
    actor_type: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = Field(default=None)
    is_shared: Optional[bool] = Field(default=None)


class ActorResponse(BaseModel):
    """Full representation of a persisted actor including platform presences.

    Attributes:
        id: Unique identifier.
        canonical_name: Authoritative display name.
        actor_type: Type label.
        description: Optional description.
        created_by: UUID of the researcher who created the actor.
        is_shared: Whether the actor is visible to all researchers.
        created_at: Creation timestamp.
        presences: All linked platform presences.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    canonical_name: str
    actor_type: Optional[str]
    description: Optional[str]
    created_by: Optional[uuid.UUID]
    is_shared: bool
    created_at: datetime
    presences: list[PresenceResponse] = Field(default_factory=list)
