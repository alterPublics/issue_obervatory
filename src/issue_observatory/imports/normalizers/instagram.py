"""Instagram normalizer adapter for Zeeschuimer data.

This normalizer adapts Zeeschuimer's Instagram data format to the format expected
by IO's universal normalizer. Zeeschuimer captures Instagram data in two formats:
- Graph API format (with __typename field)
- Item list format (with media_type integer codes)

The adapter handles both formats and maps to IO's schema.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class InstagramNormalizer:
    """Normalizes Instagram data from Zeeschuimer to IO schema.

    This is an adapter normalizer that handles both Instagram API response formats
    captured by Zeeschuimer.
    """

    def normalize(
        self,
        raw_data: dict[str, Any],
        envelope: dict[str, Any],
    ) -> dict[str, Any]:
        """Normalize an Instagram item from Zeeschuimer.

        Args:
            raw_data: The nested ``data`` field from the Zeeschuimer item (Instagram post).
            envelope: Zeeschuimer envelope fields.

        Returns:
            Flat dict with keys compatible with the universal normalizer.
        """
        # Extract post ID and shortcode
        post_id = str(raw_data.get("id") or raw_data.get("pk", ""))
        shortcode = raw_data.get("code") or raw_data.get("shortcode", "")

        # Construct post URL
        post_url = None
        if shortcode:
            post_url = f"https://www.instagram.com/p/{shortcode}/"
        elif post_id:
            # Fallback: use numeric ID (less reliable)
            post_url = f"https://www.instagram.com/p/{post_id}/"

        # Extract text content (caption)
        caption_obj = raw_data.get("caption") or {}
        if isinstance(caption_obj, dict):
            text_content = caption_obj.get("text", "")
        else:
            text_content = str(caption_obj) if caption_obj else ""

        # Extract author information
        user = raw_data.get("user") or raw_data.get("owner", {})
        author_id = str(user.get("pk") or user.get("id", ""))
        author_username = user.get("username", "")
        author_display_name = user.get("full_name") or user.get("name", "") or author_username

        # Extract timestamp
        taken_at = raw_data.get("taken_at") or raw_data.get("taken_at_timestamp")
        published_at = None
        if taken_at:
            try:
                published_at = datetime.fromtimestamp(int(taken_at), tz=timezone.utc)
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "instagram.timestamp_parse_error",
                    taken_at=taken_at,
                    error=str(exc),
                )

        # Extract engagement metrics
        like_count = raw_data.get("like_count") or raw_data.get("likes_count", 0)
        comment_count = raw_data.get("comment_count") or raw_data.get("comments_count", 0)

        # Skip Instagram ads (WARNING-4)
        product_type = str(raw_data.get("product_type") or "").lower()
        if product_type == "ad":
            logger.info(
                "instagram.ad_filtered",
                post_id=post_id,
                shortcode=shortcode,
            )
            # Return a minimal record that will be skipped by validation
            # (missing required fields)
            return {"id": post_id, "instagram_ad_filtered": True}

        # Content type detection (photo, video, carousel/album)
        media_type = raw_data.get("media_type")
        content_type = "post"
        if media_type == 2 or raw_data.get("video_versions"):
            content_type = "video"
        elif media_type == 8 or raw_data.get("carousel_media"):
            content_type = "carousel"

        # Check for Reels
        if product_type in ("clips", "igtv", "reels"):
            content_type = "reel"

        # Extract location
        location = raw_data.get("location") or {}
        location_name = location.get("name")

        # Build flat record
        flat_record: dict[str, Any] = {
            "id": post_id,
            "platform_id": post_id,
            "text": text_content,
            "text_content": text_content,
            "url": post_url,
            "author_id": author_id,
            "author_platform_id": author_id,
            "author_display_name": author_display_name,
            "author": author_display_name,
            "published_at": published_at,
            "timestamp": published_at,
            "likes_count": int(like_count) if like_count else 0,
            "comments_count": int(comment_count) if comment_count else 0,
            "content_type": content_type,
            # Instagram-specific metadata
            "instagram": {
                "shortcode": shortcode,
                "media_type": media_type,
                "product_type": product_type,
                "location_name": location_name,
                "username": author_username,
            },
        }

        return flat_record
