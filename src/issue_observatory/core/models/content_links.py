"""Cross-design content record link ORM model.

When a collection run finds that matching records already exist from other
runs (same platform, matching terms or actors, overlapping date range), a
``ContentRecordLink`` row is created to associate the existing record with
the new run.  This allows analysis dashboards to include pre-existing
records without re-fetching them from the upstream API.

Owned by the DB Engineer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from issue_observatory.core.models.base import Base


class ContentRecordLink(Base):
    """Associates an existing content record with a different collection run.

    Created by the post-collection reindex step when coverage overlap is
    detected.  Allows analysis filters to include linked records when
    querying by ``collection_run_id``.

    The composite ``(content_record_id, content_record_published_at,
    collection_run_id)`` unique constraint prevents duplicate links.
    """

    __tablename__ = "content_record_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    content_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    content_record_published_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    collection_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("collection_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    query_design_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("query_designs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    linked_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
    link_type: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        server_default=sa.text("'reindex'"),
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "content_record_id",
            "content_record_published_at",
            "collection_run_id",
            name="uq_content_record_link",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ContentRecordLink record={self.content_record_id} "
            f"run={self.collection_run_id} type={self.link_type!r}>"
        )
