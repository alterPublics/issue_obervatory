"""Video download service for YouTube and TikTok content.

Uses yt-dlp programmatically to download videos and extract metadata.
Designed to be called from Celery tasks — all DB writes use synchronous
sessions (psycopg2).

The ``video`` optional extra must be installed::

    pip install issue-observatory[video]
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class VideoResult:
    """Result of a single video download attempt.

    Attributes:
        url: Original URL that was requested.
        video_id: Platform-specific video identifier, or ``None`` if unavailable.
        video_platform: Detected platform name (``"youtube"``, ``"tiktok"``, or ``"unknown"``).
        file_path: Absolute path to the downloaded file, or ``None`` on failure.
        file_size_bytes: Size of the downloaded file in bytes, or ``None`` on failure.
        duration_seconds: Video duration in seconds, or ``None`` if unavailable.
        title: Video title, or ``None`` if unavailable.
        uploader: Channel or uploader name, or ``None`` if unavailable.
        upload_date: Original upload date, or ``None`` if unavailable.
        metadata_json: Serializable subset of the yt-dlp info_dict.
        success: ``True`` if the download completed without errors.
        error: Human-readable error message, or ``None`` on success.
    """

    url: str
    video_id: str | None = None
    video_platform: str | None = None
    file_path: str | None = None
    file_size_bytes: int | None = None
    duration_seconds: float | None = None
    title: str | None = None
    uploader: str | None = None
    upload_date: date | None = None
    metadata_json: dict[str, Any] = field(default_factory=dict)
    success: bool = False
    error: str | None = None


class VideoDownloader:
    """Download videos from YouTube and TikTok via yt-dlp.

    Args:
        storage_path: Root directory for downloaded video files.
            Videos are stored at ``{storage_path}/{platform}/{video_id}.{ext}``.
        max_size_mb: Maximum file size in MB. Downloads exceeding this are aborted.
    """

    def __init__(self, storage_path: str, max_size_mb: int = 500) -> None:
        self.storage_path = Path(storage_path)
        self.max_size_bytes = max_size_mb * 1024 * 1024

    def download(self, url: str) -> VideoResult:
        """Download a single video and return metadata.

        Attempts to download the video at up to 720p quality.  On success,
        returns a :class:`VideoResult` with the file path and extracted
        metadata.  On failure, returns a result with ``success=False`` and
        a human-readable ``error`` message.

        Args:
            url: YouTube or TikTok video URL.

        Returns:
            :class:`VideoResult` with file path and metadata on success,
            or error message on failure.
        """
        try:
            import yt_dlp
        except ImportError:
            return VideoResult(
                url=url,
                error="yt-dlp not installed. Install with: pip install issue-observatory[video]",
            )

        platform = self._detect_platform(url)
        result = VideoResult(url=url, video_platform=platform)

        # Ensure storage directory exists
        platform_dir = self.storage_path / (platform or "unknown")
        platform_dir.mkdir(parents=True, exist_ok=True)

        # yt-dlp options
        ydl_opts: dict[str, Any] = {
            "format": "bestvideo[height<=720]+bestaudio/best[height<=720]",
            "outtmpl": str(platform_dir / "%(id)s.%(ext)s"),
            "max_filesize": self.max_size_bytes,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info is None:
                    result.error = "yt-dlp returned no info"
                    return result

                result.video_id = info.get("id")
                result.title = info.get("title")
                result.uploader = info.get("uploader") or info.get("channel")
                result.duration_seconds = info.get("duration")
                result.metadata_json = self._safe_metadata(info)

                # Parse upload date (yt-dlp format: YYYYMMDD)
                upload_date_str = info.get("upload_date")
                if upload_date_str and len(upload_date_str) == 8:
                    try:
                        result.upload_date = datetime.strptime(
                            upload_date_str, "%Y%m%d"
                        ).date()
                    except ValueError:
                        pass

                # Find the downloaded file
                filename = ydl.prepare_filename(info)
                if os.path.exists(filename):
                    result.file_path = filename
                    result.file_size_bytes = os.path.getsize(filename)

                result.success = True

        except Exception as exc:
            result.error = str(exc)
            logger.warning("video_download failed for %s: %s", url, exc)

        return result

    @staticmethod
    def _detect_platform(url: str) -> str:
        """Detect video platform from URL.

        Args:
            url: A video URL.

        Returns:
            ``"youtube"``, ``"tiktok"``, or ``"unknown"``.
        """
        url_lower = url.lower()
        if "youtube.com" in url_lower or "youtu.be" in url_lower:
            return "youtube"
        if "tiktok.com" in url_lower:
            return "tiktok"
        return "unknown"

    @staticmethod
    def _safe_metadata(info: dict[str, Any]) -> dict[str, Any]:
        """Extract serializable metadata from a yt-dlp info_dict.

        Removes non-serializable fields (functions, large binary data) and
        bulky nested structures (format lists, thumbnail arrays, subtitle
        dicts, HTTP headers) that are rarely needed for analysis.

        Args:
            info: Raw yt-dlp info_dict.

        Returns:
            Flat dict containing only JSON-serializable scalar and simple
            collection values.
        """
        import json

        safe: dict[str, Any] = {}
        skip_keys = {
            "formats",
            "requested_formats",
            "thumbnails",
            "automatic_captions",
            "subtitles",
            "requested_subtitles",
            "http_headers",
        }
        for key, value in info.items():
            if key.startswith("_") or key in skip_keys:
                continue
            if isinstance(value, str | int | float | bool | type(None)):
                safe[key] = value
            elif isinstance(value, list | dict):
                try:
                    json.dumps(value)
                    safe[key] = value
                except (TypeError, ValueError):
                    continue
        return safe


# ---------------------------------------------------------------------------
# DB helpers (synchronous, for Celery worker context)
# ---------------------------------------------------------------------------


def _insert_video_download(
    extracted_url_id: str,
    result: VideoResult,
    scraping_job_id: str,
) -> None:
    """Insert a video_downloads row for a completed (or failed) download.

    Uses a synchronous SQLAlchemy session so this can be called safely from
    inside a Celery worker without a nested event loop.

    Args:
        extracted_url_id: UUID of the source extracted_urls row.
        result: :class:`VideoResult` from :meth:`VideoDownloader.download`.
        scraping_job_id: UUID of the parent ScrapingJob.
    """
    import json

    from sqlalchemy import text

    from issue_observatory.core.database import get_sync_session

    with get_sync_session() as session:
        session.execute(
            text(
                """
                INSERT INTO video_downloads (
                    extracted_url_id, url, video_id, video_platform,
                    file_path, file_size_bytes, duration_seconds,
                    title, uploader, upload_date, metadata_json,
                    download_status, error_message, scraping_job_id,
                    completed_at
                ) VALUES (
                    CAST(:extracted_url_id AS uuid),
                    :url, :video_id, :video_platform,
                    :file_path, :file_size_bytes, :duration_seconds,
                    :title, :uploader, :upload_date,
                    CAST(:metadata_json AS jsonb),
                    :download_status, :error_message,
                    CAST(:scraping_job_id AS uuid),
                    :completed_at
                )
                """
            ),
            {
                "extracted_url_id": extracted_url_id,
                "url": result.url,
                "video_id": result.video_id,
                "video_platform": result.video_platform,
                "file_path": result.file_path,
                "file_size_bytes": result.file_size_bytes,
                "duration_seconds": result.duration_seconds,
                "title": result.title,
                "uploader": result.uploader,
                "upload_date": result.upload_date,
                "metadata_json": json.dumps(result.metadata_json) if result.metadata_json else "{}",
                "download_status": "completed" if result.success else "failed",
                "error_message": result.error,
                "scraping_job_id": scraping_job_id,
                "completed_at": datetime.now(tz=UTC) if result.success else None,
            },
        )
        session.commit()
