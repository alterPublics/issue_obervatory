"""Pydantic request/response schemas for actors and platform presences.

These schemas are used by the actors API routes for validation, serialisation,
and OpenAPI documentation generation.  They are kept separate from the
SQLAlchemy ORM models in ``core/models/actors.py`` to avoid coupling transport
concerns to persistence concerns.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from issue_observatory.core.models.actors import ActorType

#: All valid actor type string values, derived from the ActorType enum.
#: Used as a Literal type constraint in Pydantic schemas.
ACTOR_TYPE_VALUES = Literal[
    "person",
    "organization",
    "political_party",
    "educational_institution",
    "teachers_union",
    "think_tank",
    "media_outlet",
    "government_body",
    "ngo",
    "company",
    "unknown",
]


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

    @field_validator("platform_user_id", "platform_username", mode="before")
    @classmethod
    def empty_to_none(cls, v: str | None) -> str | None:
        """Coerce empty or whitespace-only strings to None."""
        if isinstance(v, str) and not v.strip():
            return None
        return v


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
        actor_type: Actor category from the ``ActorType`` enumeration.
            Valid values: ``person``, ``organization``, ``political_party``,
            ``educational_institution``, ``teachers_union``, ``think_tank``,
            ``media_outlet``, ``government_body``, ``ngo``, ``company``,
            ``unknown``.
        description: Optional longer description or biography.
        is_shared: When ``True``, the actor is visible to all researchers.
        public_figure: GR-14 — GDPR Art. 89(1) research exemption.  When
            ``True``, the collection pipeline stores the plain platform
            username as ``pseudonymized_author_id`` instead of a salted
            SHA-256 hash.  Must only be set for publicly elected or appointed
            officials (e.g. Danish MPs, Greenlandic ministers, US federal
            officials) acting in their official capacity.  Private individuals
            must remain pseudonymized regardless of public prominence.
        presence: Optional initial platform presence to attach on creation.
    """

    canonical_name: str = Field(..., min_length=1, max_length=500)
    actor_type: Optional[ACTOR_TYPE_VALUES] = Field(default=None)
    description: Optional[str] = Field(default=None)
    is_shared: bool = Field(default=False)
    public_figure: bool = Field(
        default=False,
        description=(
            "GR-14 GDPR Art. 89(1) exemption: bypasses SHA-256 pseudonymization. "
            "Use only for elected/appointed officials in official capacity."
        ),
    )
    presence: Optional[ActorPresenceCreate] = Field(default=None)


class ActorUpdate(BaseModel):
    """Payload for partially updating an actor.

    All fields are optional — only fields explicitly included in the request
    body are applied to the stored record.

    Attributes:
        canonical_name: New canonical name for the actor.
        actor_type: New actor category from the ``ActorType`` enumeration.
        description: New description text.
        is_shared: New sharing visibility flag.
        public_figure: GR-14 — GDPR Art. 89(1) research exemption.  When
            ``True``, the collection pipeline stores the plain platform
            username as ``pseudonymized_author_id`` instead of a salted
            SHA-256 hash.  Must only be set for publicly elected or appointed
            officials acting in their official capacity.  Private individuals
            must remain pseudonymized regardless of public prominence.
    """

    canonical_name: Optional[str] = Field(default=None, min_length=1, max_length=500)
    actor_type: Optional[ACTOR_TYPE_VALUES] = Field(default=None)
    description: Optional[str] = Field(default=None)
    is_shared: Optional[bool] = Field(default=None)
    public_figure: Optional[bool] = Field(
        default=None,
        description=(
            "GR-14 GDPR Art. 89(1) exemption: bypasses SHA-256 pseudonymization. "
            "Use only for elected/appointed officials in official capacity."
        ),
    )


class ActorResponse(BaseModel):
    """Full representation of a persisted actor including platform presences.

    Attributes:
        id: Unique identifier.
        canonical_name: Authoritative display name.
        actor_type: Actor category from the ``ActorType`` enumeration.
        description: Optional description.
        created_by: UUID of the researcher who created the actor.
        is_shared: Whether the actor is visible to all researchers.
        public_figure: GR-14 flag — when ``True`` this actor's content
            records bypass SHA-256 pseudonymization.  The frontend should
            display this flag with a clear GDPR warning tooltip.
        created_at: Creation timestamp.
        presences: All linked platform presences.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    canonical_name: str
    actor_type: Optional[ACTOR_TYPE_VALUES]
    description: Optional[str]
    created_by: Optional[uuid.UUID]
    is_shared: bool
    public_figure: bool = False
    created_at: datetime
    presences: list[PresenceResponse] = Field(
        default_factory=list,
        validation_alias="platform_presences",
    )
