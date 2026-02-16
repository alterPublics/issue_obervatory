"""API credential pool ORM model.

The credentials JSONB column stores Fernet-encrypted credential payloads.
The CREDENTIAL_ENCRYPTION_KEY environment variable (a Fernet key) is the
single secret that must be protected carefully; all other API secrets derive
from it.

The model intentionally exposes no plaintext accessor methods — decryption
is performed exclusively inside core/credential_pool.py.

Live quota state (daily/monthly usage, cooldown, active leases) is tracked
in Redis with TTL-based keys; do not poll this table per-request for quota.

Owned by the DB Engineer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from issue_observatory.core.models.base import Base


class ApiCredential(Base):
    """An encrypted API credential entry in the shared credential pool.

    platform:        the service this credential grants access to
                     ('youtube', 'telegram', 'serper', 'twitterapiio', …)
    tier:            the pricing tier this credential enables
                     ('free', 'medium', 'premium')
    credential_name: human-readable label, e.g. "YouTube key — researcher A"
    credentials:     Fernet-encrypted JSONB payload; field structure is
                     platform-specific (e.g. {'api_key': '…'} for YouTube,
                     {'api_id': …, 'api_hash': '…', 'session': '…'} for Telegram)
    daily_quota /
    monthly_quota:   NULL means unlimited; non-null values are enforced via
                     Redis counters by the CredentialPool
    error_count:     circuit-breaker counter; CredentialPool skips credentials
                     where error_count exceeds a configured threshold until
                     an admin resets this field
    """

    __tablename__ = "api_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    platform: Mapped[str] = mapped_column(
        sa.String(50),
        nullable=False,
    )
    tier: Mapped[str] = mapped_column(
        sa.String(10),
        nullable=False,
    )
    credential_name: Mapped[str] = mapped_column(
        sa.String(200),
        nullable=False,
    )
    credentials: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.text("true"),
    )
    daily_quota: Mapped[Optional[int]] = mapped_column(
        sa.Integer,
        nullable=True,
    )
    monthly_quota: Mapped[Optional[int]] = mapped_column(
        sa.Integer,
        nullable=True,
    )
    quota_reset_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    last_error_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    error_count: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    )
    notes: Mapped[Optional[str]] = mapped_column(
        sa.Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
        onupdate=sa.text("NOW()"),
    )

    __table_args__ = (
        sa.Index(
            "idx_credentials_platform_tier_active",
            "platform",
            "tier",
            "is_active",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ApiCredential id={self.id} platform={self.platform!r} "
            f"tier={self.tier!r} name={self.credential_name!r} "
            f"active={self.is_active}>"
        )
