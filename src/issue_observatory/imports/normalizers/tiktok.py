"""TikTok normalizer adapter for Zeeschuimer data.

This normalizer adapts Zeeschuimer's TikTok data format to IO's universal schema.
Zeeschuimer captures TikTok video data from the web API, which includes video
metadata, author information, and engagement stats.

Supports both:
- TikTok videos (module_id: tiktok.com)
- TikTok comments (module_id: tiktok-comments)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class TikTokNormalizer:
    """Normalizes TikTok data from Zeeschuimer to IO schema.

    This is an adapter normalizer that handles both TikTok video posts and comments.
    """

    def normalize(
        self,
        raw_data: dict[str, Any],
        envelope: dict[str, Any],
    ) -> dict[str, Any]:
        """Normalize a TikTok item from Zeeschuimer.

        Args:
            raw_data: The nested ``data`` field from the Zeeschuimer item (TikTok video).
            envelope: Zeeschuimer envelope fields.

        Returns:
            Flat dict with keys compatible with the universal normalizer.
        """
        # Detect if this is a comment or a video post
        is_comment = "cid" in raw_data or envelope.get("source_platform") == "tiktok-comments"

        if is_comment:
            return self._normalize_comment(raw_data, envelope)
        else:
            return self._normalize_video(raw_data, envelope)

    def _normalize_video(
        self,
        raw_data: dict[str, Any],
        envelope: dict[str, Any],
    ) -> dict[str, Any]:
        """Normalize a TikTok video post."""
        # Extract video ID
        video_id = str(raw_data.get("id") or raw_data.get("video", {}).get("id", ""))

        # Extract text content (video description/caption)
        text_content = raw_data.get("desc") or raw_data.get("description", "")

        # Extract author information
        author = raw_data.get("author") or {}
        author_id = str(author.get("id") or author.get("uid", ""))
        author_username = author.get("uniqueId") or author.get("unique_id", "")
        author_display_name = (
            author.get("nickname")
            or author.get("nick_name", "")
            or author_username
        )

        # Construct video URL
        video_url = None
        if video_id and author_username:
            video_url = f"https://www.tiktok.com/@{author_username}/video/{video_id}"

        # Extract timestamp
        create_time = raw_data.get("createTime") or raw_data.get("create_time")
        published_at = None
        if create_time:
            try:
                published_at = datetime.fromtimestamp(int(create_time), tz=timezone.utc)
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "tiktok.timestamp_parse_error",
                    create_time=create_time,
                    error=str(exc),
                )

        # Extract engagement metrics
        stats = raw_data.get("stats") or raw_data.get("statistics", {})
        digg_count = stats.get("diggCount") or stats.get("digg_count", 0)
        comment_count = stats.get("commentCount") or stats.get("comment_count", 0)
        share_count = stats.get("shareCount") or stats.get("share_count", 0)
        play_count = stats.get("playCount") or stats.get("play_count", 0)

        # Extract video duration
        video = raw_data.get("video") or {}
        duration = video.get("duration")

        # Extract music/sound info
        music = raw_data.get("music") or {}
        music_title = music.get("title") or music.get("name", "")

        # Extract hashtags/challenges
        challenges = raw_data.get("challenges") or []
        hashtags = [
            c.get("title", "")
            for c in challenges
            if isinstance(c, dict) and c.get("title")
        ]

        # Build flat record
        flat_record: dict[str, Any] = {
            "id": video_id,
            "platform_id": video_id,
            "text": text_content,
            "text_content": text_content,
            "url": video_url,
            "author_id": author_id,
            "author_platform_id": author_id,
            "author_display_name": author_display_name,
            "author": author_display_name,
            "published_at": published_at,
            "timestamp": published_at,
            "likes_count": int(digg_count) if digg_count else 0,
            "comments_count": int(comment_count) if comment_count else 0,
            "shares_count": int(share_count) if share_count else 0,
            "views_count": int(play_count) if play_count else 0,
            "content_type": "video",
            # TikTok-specific metadata
            "tiktok": {
                "username": author_username,
                "duration": duration,
                "music_title": music_title,
                "hashtags": hashtags,
            },
        }

        return flat_record

    def _normalize_comment(
        self,
        raw_data: dict[str, Any],
        envelope: dict[str, Any],
    ) -> dict[str, Any]:
        """Normalize a TikTok comment."""
        # Extract comment ID
        comment_id = str(raw_data.get("cid") or raw_data.get("id", ""))

        # Extract comment text
        text_content = raw_data.get("text") or raw_data.get("comment", "")

        # Extract author information
        user = raw_data.get("user") or {}
        author_id = str(user.get("uid") or user.get("id", ""))
        author_username = user.get("unique_id") or user.get("uniqueId", "")
        author_display_name = user.get("nickname") or user.get("nick_name", "") or author_username

        # Extract timestamp
        create_time = raw_data.get("create_time") or raw_data.get("createTime")
        published_at = None
        if create_time:
            try:
                published_at = datetime.fromtimestamp(int(create_time), tz=timezone.utc)
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "tiktok_comment.timestamp_parse_error",
                    create_time=create_time,
                    error=str(exc),
                )

        # Extract engagement (like count)
        digg_count = raw_data.get("digg_count", 0)

        # Build flat record
        flat_record: dict[str, Any] = {
            "id": comment_id,
            "platform_id": comment_id,
            "text": text_content,
            "text_content": text_content,
            "url": None,  # Comments don't have standalone URLs
            "author_id": author_id,
            "author_platform_id": author_id,
            "author_display_name": author_display_name,
            "author": author_display_name,
            "published_at": published_at,
            "timestamp": published_at,
            "likes_count": int(digg_count) if digg_count else 0,
            "content_type": "comment",
            # TikTok-specific metadata
            "tiktok": {
                "username": author_username,
                "is_comment": True,
            },
        }

        return flat_record
