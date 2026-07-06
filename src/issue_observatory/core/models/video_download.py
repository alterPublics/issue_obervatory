"""ORM model for video downloads sourced from extracted URLs.

The ``video_downloads`` table tracks yt-dlp download jobs initiated for URLs
that resolve to video content (YouTube, TikTok, etc.).  Each row is linked
to an ``extracted_urls`` row and optionally to the ``scraping_jobs`` job that
triggered the download.

Owned by the DB Engineer.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from issue_observatory.core.models.base import Base


class VideoDownload(Base):
    """A video download job for a URL found in the extracted_urls table.

    Attributes:
        id: UUID primary key.
        extracted_url_id: FK to ``extracted_urls.id`` (CASCADE on delete).
        url: The video URL that was (or will be) downloaded.
        video_id: Platform-native video identifier (e.g. YouTube watch ID).
        video_platform: Platform slug — ``"youtube"`` or ``"tiktok"``.
        file_path: Filesystem path to the downloaded media file, if saved.
        file_size_bytes: Size of the downloaded file in bytes.
        duration_seconds: Video duration in fractional seconds.
        title: Video title as reported by yt-dlp.
        uploader: Channel or user name that uploaded the video.
        upload_date: Date the video was published on the platform.
        metadata_json: Full yt-dlp ``info_dict`` for the video.
        download_status: Lifecycle state — ``"pending"``, ``"downloading"``,
            ``"completed"``, ``"failed"``, or ``"skipped"``.
        error_message: Human-readable error description when status is
            ``"failed"``.
        scraping_job_id: FK to the ``scraping_jobs`` row that triggered this
            download (nullable; SET NULL on delete).
        created_at: Timestamp when the row was inserted.
        completed_at: Timestamp when the download reached a terminal state.
    """

    __tablename__ = "video_downloads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    extracted_url_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("extracted_urls.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
    )
    video_id: Mapped[str | None] = mapped_column(
        sa.String(200),
        nullable=True,
    )
    video_platform: Mapped[str | None] = mapped_column(
        sa.String(30),
        nullable=True,
    )
    file_path: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
    )
    file_size_bytes: Mapped[int | None] = mapped_column(
        sa.BigInteger,
        nullable=True,
    )
    duration_seconds: Mapped[float | None] = mapped_column(
        sa.Float,
        nullable=True,
    )
    title: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
    )
    uploader: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
    )
    upload_date: Mapped[date | None] = mapped_column(
        sa.Date,
        nullable=True,
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    download_status: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        server_default=sa.text("'pending'"),
    )
    error_message: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
    )
    scraping_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("scraping_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

    # Relationships
    extracted_url: Mapped[ExtractedUrl] = relationship(  # type: ignore[name-defined]
        "ExtractedUrl",
        back_populates="video_downloads",
        foreign_keys=[extracted_url_id],
    )

    __table_args__ = (
        sa.Index("idx_video_downloads_extracted_url_id", "extracted_url_id"),
        sa.Index("idx_video_downloads_download_status", "download_status"),
        # Composite index for platform-native deduplication checks.
        sa.Index(
            "idx_video_downloads_platform_video_id",
            "video_platform",
            "video_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<VideoDownload id={self.id} platform={self.video_platform!r} "
            f"video_id={self.video_id!r} status={self.download_status!r}>"
        )
