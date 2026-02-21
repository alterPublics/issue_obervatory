"""Threads normalizer adapter for Zeeschuimer data.

This normalizer adapts Zeeschuimer's Threads data format to IO's universal schema.
Zeeschuimer captures Threads data from the web API (threads.net domain), which
uses a similar structure to Instagram but with some differences.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class ThreadsNormalizer:
    """Normalizes Threads data from Zeeschuimer to IO schema.

    This is an adapter normalizer that handles Threads post data.
    """

    def normalize(
        self,
        raw_data: dict[str, Any],
        envelope: dict[str, Any],
    ) -> dict[str, Any]:
        """Normalize a Threads item from Zeeschuimer.

        Args:
            raw_data: The nested ``data`` field from the Zeeschuimer item (Threads post).
            envelope: Zeeschuimer envelope fields.

        Returns:
            Flat dict with keys compatible with the universal normalizer.
        """
        # Extract post ID and code
        post_id = str(raw_data.get("id") or raw_data.get("pk", ""))
        code = raw_data.get("code", "")

        # Construct post URL
        post_url = None
        if code:
            post_url = f"https://www.threads.net/t/{code}"
        elif post_id:
            post_url = f"https://www.threads.net/t/{post_id}"

        # Extract text content (caption)
        caption_obj = raw_data.get("caption") or {}
        if isinstance(caption_obj, dict):
            text_content = caption_obj.get("text", "")
        else:
            text_content = str(caption_obj) if caption_obj else ""

        # Alternative: thread_items format
        if not text_content:
            thread_items = raw_data.get("thread_items", [])
            if thread_items and isinstance(thread_items[0], dict):
                post = thread_items[0].get("post", {})
                text_content = post.get("caption", {}).get("text", "")

        # Extract author information
        user = raw_data.get("user") or {}
        if not user and "thread_items" in raw_data:
            thread_items = raw_data.get("thread_items", [])
            if thread_items and isinstance(thread_items[0], dict):
                user = thread_items[0].get("post", {}).get("user", {})

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
                    "threads.timestamp_parse_error",
                    taken_at=taken_at,
                    error=str(exc),
                )

        # Extract engagement metrics
        like_count = raw_data.get("like_count", 0)
        # Threads uses "text_post_app_info" for engagement metrics
        text_post_app_info = raw_data.get("text_post_app_info", {})
        if not like_count:
            like_count = text_post_app_info.get("direct_reply_count", 0)

        # Reply count (Threads-specific)
        reply_count = text_post_app_info.get("direct_reply_count", 0)
        repost_count = text_post_app_info.get("repost_count", 0)
        quote_count = text_post_app_info.get("quote_count", 0)

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
            "comments_count": int(reply_count) if reply_count else 0,
            "shares_count": int(repost_count) if repost_count else 0,
            "content_type": "post",
            # Threads-specific metadata
            "threads": {
                "code": code,
                "username": author_username,
                "quote_count": int(quote_count) if quote_count else 0,
            },
        }

        return flat_record
