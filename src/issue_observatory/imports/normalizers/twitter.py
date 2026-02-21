"""Twitter/X normalizer adapter for Zeeschuimer data.

This normalizer adapts Zeeschuimer's Twitter data format to the format expected
by the existing X/Twitter collector's normalization logic. Zeeschuimer captures
data from the X.com GraphQL API endpoints, which is structurally similar to what
the official X API v2 returns.

The adapter's job is to:
1. Flatten the Zeeschuimer-specific nested structure
2. Map field names to match what the X/Twitter collector expects
3. Return a dict that can be passed to the universal normalizer
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class TwitterNormalizer:
    """Normalizes Twitter/X data from Zeeschuimer to IO schema.

    This is an adapter normalizer that reuses the existing X/Twitter collector's
    field mapping logic.
    """

    def normalize(
        self,
        raw_data: dict[str, Any],
        envelope: dict[str, Any],
    ) -> dict[str, Any]:
        """Normalize a Twitter/X item from Zeeschuimer.

        Args:
            raw_data: The nested ``data`` field from the Zeeschuimer item (tweet data).
            envelope: Zeeschuimer envelope fields.

        Returns:
            Flat dict with keys compatible with the universal normalizer.
        """
        # Extract tweet ID (modern or legacy format)
        tweet_id = raw_data.get("rest_id") or raw_data.get("id_str") or str(raw_data.get("id", ""))

        # Extract legacy format if present
        legacy = raw_data.get("legacy", {})

        # Tweet text
        text_content = legacy.get("full_text") or raw_data.get("text", "")

        # Timestamp parsing
        created_at_str = legacy.get("created_at") or raw_data.get("created_at")
        published_at = self._parse_twitter_timestamp(created_at_str)

        # Author information
        author_info = self._extract_author(raw_data)

        # Engagement metrics
        likes_count = legacy.get("favorite_count", 0)
        retweet_count = legacy.get("retweet_count", 0)
        reply_count = legacy.get("reply_count", 0)
        quote_count = legacy.get("quote_count", 0)
        bookmark_count = legacy.get("bookmark_count", 0)

        # Total engagement
        total_engagement = likes_count + retweet_count + reply_count + quote_count

        # Check if promoted
        is_promoted = raw_data.get("promoted", False) or raw_data.get("promotedContent") is not None

        # Construct tweet URL
        tweet_url = None
        if tweet_id and author_info["username"]:
            tweet_url = f"https://x.com/{author_info['username']}/status/{tweet_id}"

        # Build flat record
        flat_record: dict[str, Any] = {
            "id": tweet_id,
            "platform_id": tweet_id,
            "text": text_content,
            "text_content": text_content,
            "url": tweet_url,
            "author_id": author_info["user_id"],
            "author_platform_id": author_info["user_id"],
            "author_display_name": author_info["display_name"],
            "author": author_info["display_name"],
            "published_at": published_at,
            "timestamp": published_at,
            "created_at": published_at,
            "likes_count": likes_count,
            "shares_count": retweet_count,
            "comments_count": reply_count,
            "content_type": "post",
            # Twitter-specific metadata
            "twitter": {
                "quote_count": quote_count,
                "bookmark_count": bookmark_count,
                "is_promoted": is_promoted,
                "username": author_info["username"],
            },
        }

        return flat_record

    def _extract_author(self, raw: dict[str, Any]) -> dict[str, str | None]:
        """Extract author information from tweet data.

        Returns:
            Dict with user_id, username, display_name.
        """
        # Try core.user_results.result.legacy (GraphQL format)
        core = raw.get("core", {})
        user_results = core.get("user_results", {})
        result = user_results.get("result", {})
        legacy_user = result.get("legacy", {})

        # Fallback to top-level user or legacy.user
        if not legacy_user:
            legacy = raw.get("legacy", {})
            user = legacy.get("user", {}) or raw.get("user", {})
            legacy_user = user.get("legacy", {}) or user

        user_id = (
            result.get("rest_id")
            or legacy_user.get("id_str")
            or str(legacy_user.get("id", ""))
        )
        username = legacy_user.get("screen_name", "")
        display_name = legacy_user.get("name", "")

        return {
            "user_id": user_id,
            "username": username,
            "display_name": display_name,
        }

    def _parse_twitter_timestamp(self, created_at: str | None) -> datetime | None:
        """Parse Twitter timestamp format to datetime.

        Twitter timestamps look like: "Mon Jan 15 12:34:56 +0000 2026"

        Args:
            created_at: Twitter timestamp string.

        Returns:
            Parsed datetime (UTC) or None if parsing fails.
        """
        if not created_at:
            return None

        try:
            # Twitter format: "Mon Jan 15 12:34:56 +0000 2026"
            return datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
        except (ValueError, TypeError) as exc:
            logger.warning(
                "twitter.timestamp_parse_error",
                created_at=created_at,
                error=str(exc),
            )
            return None
