"""Pydantic request/response schemas for collection runs and credit estimates.

These schemas are used by the collections API routes for validation,
serialisation, and OpenAPI documentation generation.  They are kept
separate from the SQLAlchemy ORM models in ``core/models/collection.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CollectionRunCreate(BaseModel):
    """Payload for launching a new collection run.

    Attributes:
        query_design_id: The query design to execute.
        mode: Operation mode — ``'batch'`` for a fixed date range,
            ``'live'`` for recurring Celery Beat execution.
        tier: Default collection tier for arenas without an explicit override.
        date_from: Start of the collection window (batch mode only).
        date_to: End of the collection window (batch mode only).
        arenas_config: Per-arena tier overrides, e.g.
            ``{"youtube": "medium", "reddit": "free"}``.
    """

    query_design_id: uuid.UUID
    mode: str = Field(default="batch", pattern="^(batch|live)$")
    tier: str = Field(default="free", pattern="^(free|medium|premium)$")
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    arenas_config: dict = Field(default_factory=dict)


class CollectionRunRead(BaseModel):
    """Full representation of a persisted collection run.

    Returned by list and detail endpoints.

    Attributes:
        id: Unique run identifier.
        query_design_id: UUID of the associated query design (may be ``None``
            if the query design was deleted after the run was created).
        initiated_by: UUID of the user who launched the run.
        mode: ``'batch'`` or ``'live'``.
        status: Current status — ``'pending'``, ``'running'``, ``'completed'``,
            or ``'failed'``.
        tier: Default collection tier.
        started_at: Timestamp when the run transitioned to ``'running'``.
        completed_at: Timestamp when the run reached a terminal state.
        date_from: Batch mode start timestamp.
        date_to: Batch mode end timestamp.
        estimated_credits: Credits reserved at run start (pre-flight estimate).
        credits_spent: Actual credits consumed (settled on completion).
        records_collected: Total content records ingested by this run.
    """

    id: uuid.UUID
    query_design_id: Optional[uuid.UUID]
    initiated_by: uuid.UUID
    mode: str
    status: str
    tier: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    date_from: Optional[datetime]
    date_to: Optional[datetime]
    estimated_credits: int
    credits_spent: int
    records_collected: int

    model_config = ConfigDict(from_attributes=True)


class CreditEstimateRequest(BaseModel):
    """Payload for requesting a pre-flight credit estimate.

    The estimate is non-destructive — no credits are reserved and no run
    is created.  Use this from the collection launcher UI to show the user
    the projected cost before they commit.

    Attributes:
        query_design_id: The query design whose terms/actors drive the estimate.
        tier: Default tier to use in the estimate calculation.
        arenas_config: Per-arena tier overrides applied before estimating.
        date_from: Batch mode start (affects volume-based estimates).
        date_to: Batch mode end.
    """

    query_design_id: uuid.UUID
    tier: str = Field(default="free", pattern="^(free|medium|premium)$")
    arenas_config: dict = Field(default_factory=dict)
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


class CreditEstimateResponse(BaseModel):
    """Pre-flight credit cost estimate broken down by arena.

    Attributes:
        total_credits: Sum of per-arena estimates.
        available_credits: Credits available to the requesting user.
        can_run: ``True`` when ``total_credits <= available_credits``.
        per_arena: Mapping of arena name → estimated credit cost.
    """

    total_credits: int
    available_credits: int
    can_run: bool
    per_arena: dict[str, int]
