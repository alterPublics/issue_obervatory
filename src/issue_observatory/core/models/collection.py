"""Collection run and task ORM models.

Covers:
- CollectionRun: an owner-initiated execution of a query design across
  one or more arenas, in batch or live mode.
- CollectionTask: a per-arena-platform unit of work within a run,
  executed by a Celery worker.
- CreditTransaction: an immutable audit record of every credit reservation,
  settlement, or refund event.

Owned by the DB Engineer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from issue_observatory.core.models.base import Base

if TYPE_CHECKING:
    from issue_observatory.core.models.credentials import ApiCredential
    from issue_observatory.core.models.project import Project
    from issue_observatory.core.models.query_design import QueryDesign
    from issue_observatory.core.models.users import User


class CollectionRun(Base):
    """A single execution of a query design across selected arenas.

    mode:   'batch'  — collect over a fixed date range (date_from … date_to)
            'live'   — Celery Beat re-runs at a configured interval

    status progression (happy path):
        pending → running → completed
    failure path:
        pending / running → failed
    live-tracking suspension:
        active → suspended → active  (live mode only)

    arenas_config stores per-arena tier overrides as a JSON object:
        {"youtube": "medium", "reddit": "free", "bluesky": "free"}
    Arenas absent from the map use default_tier from the query design.

    credits_spent is settled from the sum of CreditTransaction rows with
    transaction_type='settlement' once the run completes.
    """

    __tablename__ = "collection_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    query_design_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("query_designs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    initiated_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    mode: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        server_default=sa.text("'pending'"),
        index=True,
    )
    tier: Mapped[str] = mapped_column(
        sa.String(10),
        nullable=False,
        server_default=sa.text("'free'"),
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    suspended_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    date_from: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    date_to: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    arenas_config: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        server_default=sa.text("'{}'"),
    )
    estimated_credits: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    )
    credits_spent: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    )
    error_log: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )
    records_collected: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    )

    # Relationships
    query_design: Mapped[Optional[QueryDesign]] = relationship(
        "QueryDesign",
        back_populates="collection_runs",
    )
    project: Mapped[Optional[Project]] = relationship(
        "Project",
        back_populates="collection_runs",
    )
    initiator: Mapped[User] = relationship(
        "User",
        foreign_keys=[initiated_by],
        back_populates="collection_runs",
    )
    tasks: Mapped[list[CollectionTask]] = relationship(
        "CollectionTask",
        back_populates="collection_run",
        cascade="all, delete-orphan",
    )
    credit_transactions: Mapped[list[CreditTransaction]] = relationship(
        "CreditTransaction",
        back_populates="collection_run",
    )

    def __repr__(self) -> str:
        return (
            f"<CollectionRun id={self.id} mode={self.mode!r} "
            f"status={self.status!r}>"
        )


class CollectionTask(Base):
    """A single arena-platform unit of work within a CollectionRun.

    Each CollectionTask corresponds to one Celery task invocation.
    celery_task_id allows the API to check live task state via the Celery
    inspector or result backend.

    credential_id records which ApiCredential was leased for this task.
    rate_limit_state captures backoff / retry context so that a resumed task
    can continue from where it left off.
    """

    __tablename__ = "collection_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    collection_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("collection_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    arena: Mapped[str] = mapped_column(
        sa.String(50),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(
        sa.String(50),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        server_default=sa.text("'pending'"),
        index=True,
    )
    celery_task_id: Mapped[Optional[str]] = mapped_column(
        sa.String(200),
        nullable=True,
    )
    credential_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("api_credentials.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    records_collected: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    )
    duplicates_skipped: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )
    rate_limit_state: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        server_default=sa.text("'{}'"),
    )

    # Relationships
    collection_run: Mapped[CollectionRun] = relationship(
        "CollectionRun",
        back_populates="tasks",
    )
    credential: Mapped[Optional[ApiCredential]] = relationship(
        "ApiCredential",
        foreign_keys=[credential_id],
    )

    def __repr__(self) -> str:
        return (
            f"<CollectionTask id={self.id} arena={self.arena!r} "
            f"platform={self.platform!r} status={self.status!r}>"
        )


class CreditTransaction(Base):
    """An immutable credit audit record.

    transaction_type values:
    - 'reservation':  credits reserved at run start (pre-flight estimate)
    - 'settlement':   actual credits consumed, recorded after task completes
    - 'refund':       credits returned when a task fails or is cancelled

    The credit balance visible to users is computed as:
        SUM(credits_amount) across valid non-expired CreditAllocations
        MINUS SUM(credits_consumed) for 'reservation' transactions
        PLUS  SUM(credits_consumed) for 'refund' transactions

    Do not UPDATE rows in this table — only INSERT.
    """

    __tablename__ = "credit_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    collection_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("collection_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    arena: Mapped[str] = mapped_column(
        sa.String(50),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(
        sa.String(50),
        nullable=False,
    )
    tier: Mapped[str] = mapped_column(
        sa.String(10),
        nullable=False,
    )
    credits_consumed: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
    )
    transaction_type: Mapped[str] = mapped_column(
        sa.String(50),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
        index=True,
    )
    description: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )

    # Relationships
    user: Mapped[Optional[User]] = relationship(
        "User",
        back_populates="credit_transactions",
    )
    collection_run: Mapped[Optional[CollectionRun]] = relationship(
        "CollectionRun",
        back_populates="credit_transactions",
    )

    def __repr__(self) -> str:
        return (
            f"<CreditTransaction id={self.id} type={self.transaction_type!r} "
            f"credits={self.credits_consumed} user_id={self.user_id}>"
        )
