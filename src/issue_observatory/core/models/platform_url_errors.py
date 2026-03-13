"""Platform URL error tracking ORM model.

Tracks URLs that consistently return errors from data providers (e.g.
Bright Data ``dead_page``, ``login_required``).  URLs that fail repeatedly
are suppressed from future collection runs to avoid wasting API credits.

Suppression rule: ``failure_count >= 2 AND last_seen_at > NOW() - 30 days``.
After 30 days without a new failure the URL is automatically retried, and
:func:`~issue_observatory.workers._task_helpers.clear_url_errors` removes
the row entirely when the URL produces valid data again.

Owned by the DB Engineer.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from issue_observatory.core.models.base import Base


class PlatformUrlError(Base):
    """Records a URL that returned an error from a data provider.

    Each row tracks one ``(platform, url)`` pair.  Repeated failures
    increment ``failure_count`` and update ``last_seen_at`` via UPSERT.
    """

    __tablename__ = "platform_url_errors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    platform: Mapped[str] = mapped_column(
        sa.String(50),
        nullable=False,
        comment="Platform identifier (e.g. 'facebook', 'instagram').",
    )
    url: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
        comment="The URL that produced an error.",
    )
    error_code: Mapped[str] = mapped_column(
        sa.String(100),
        nullable=False,
        comment="Provider error code (e.g. 'dead_page', 'login_required').",
    )
    error_detail: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        comment="Human-readable error description from the provider.",
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
    failure_count: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("1"),
    )

    __table_args__ = (
        sa.UniqueConstraint("platform", "url", name="uq_platform_url_errors_platform_url"),
        sa.Index("idx_platform_url_errors_lookup", "platform", "failure_count", "last_seen_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<PlatformUrlError platform={self.platform!r} "
            f"url={self.url!r} error={self.error_code!r} "
            f"failures={self.failure_count}>"
        )
