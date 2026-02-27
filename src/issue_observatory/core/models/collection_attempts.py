"""Collection attempt metadata ORM model.

Lightweight log of every collection attempt — analogous to the ``pull``
collection in the legacy ``spreadAnalysis`` MongoDB tool.  Each row records
what was requested (platform, input, date range) and how many records came
back, without storing the actual data.

The pre-collection coverage checker queries *only* this small table to
decide whether an API call is needed, avoiding expensive scans of the
partitioned ``content_records`` table entirely.

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


class CollectionAttempt(Base):
    """Records a single collection attempt for a (platform, input, date range).

    After each arena task completes (success or failure), one row is inserted
    per input value (search term or actor ID).  The coverage checker reads
    ``MIN(date_from)`` / ``MAX(date_to)`` from this table grouped by
    ``(platform, input_value, input_type)`` — a query that hits a small,
    well-indexed table instead of the multi-million-row ``content_records``.

    Columns mirror the old MongoDB pull document::

        {input, method, input_type,
         attempts: [{returned_posts, start_date, end_date, inserted_at}]}

    but flattened into a relational row-per-attempt design.
    """

    __tablename__ = "collection_attempts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    platform: Mapped[str] = mapped_column(
        sa.String(50),
        nullable=False,
    )
    input_value: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
        comment="Search term or actor platform ID that was collected.",
    )
    input_type: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        comment="'term' or 'actor' — the type of input_value.",
    )
    date_from: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    date_to: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    records_returned: Mapped[Optional[int]] = mapped_column(
        sa.Integer,
        nullable=True,
        comment="Number of records returned by the API. NULL if the attempt failed.",
    )
    collection_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("collection_runs.id", ondelete="CASCADE"),
        nullable=True,
        comment=(
            "NULL for synthetic backfill rows created by the coverage checker "
            "fallback when data exists but no recent attempt metadata was found."
        ),
    )
    query_design_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("query_designs.id", ondelete="SET NULL"),
        nullable=True,
    )
    attempted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
    is_valid: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.text("TRUE"),
        comment=(
            "Set to FALSE by the reconciliation routine when the underlying "
            "data in content_records no longer exists.  Invalid attempts are "
            "excluded from coverage checks."
        ),
    )

    __table_args__ = (
        # Primary lookup index for the coverage checker:
        # SELECT MIN(date_from), MAX(date_to) FROM collection_attempts
        # WHERE platform = :p AND input_value = :v AND input_type = :t
        #   AND records_returned IS NOT NULL
        sa.Index(
            "idx_collection_attempts_lookup",
            "platform",
            "input_value",
            "input_type",
        ),
        # Cascade cleanup index — find attempts for a given run quickly.
        sa.Index(
            "idx_collection_attempts_run",
            "collection_run_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CollectionAttempt platform={self.platform!r} "
            f"input={self.input_value!r} type={self.input_type!r} "
            f"range={self.date_from}..{self.date_to} "
            f"records={self.records_returned}>"
        )
