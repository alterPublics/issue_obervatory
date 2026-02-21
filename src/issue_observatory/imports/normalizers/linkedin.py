"""LinkedIn Voyager V2 normalizer for Zeeschuimer data.

This normalizer processes LinkedIn data captured by Zeeschuimer from the
Voyager V2 API (the internal API used by LinkedIn's web frontend).

Key challenges:
- **No absolute timestamps**: LinkedIn provides relative timestamps like "18h ago",
  "2d ago", "3mo ago" instead of absolute publication dates. We estimate timestamps
  by subtracting the parsed offset from timestamp_collected.
- **Deep nested structure**: Voyager V2 data is heavily nested with cross-references
  resolved by Zeeschuimer's recursively_enrich() function.
- **Multiple engagement metric locations**: Comment/like/share counts appear in
  different fields depending on API response type.

The normalization logic here is based on 4CAT's SearchLinkedIn.map_item() implementation
(datasources/linkedin/search_linkedin.py) adapted for IO's universal schema.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class LinkedInNormalizer:
    """Normalizes LinkedIn Voyager V2 data from Zeeschuimer to IO schema.

    This normalizer is stateless and can be reused across multiple items.
    """

    def normalize(
        self,
        raw_data: dict[str, Any],
        envelope: dict[str, Any],
    ) -> dict[str, Any]:
        """Normalize a LinkedIn Voyager V2 item to a flat dict for universal normalization.

        Args:
            raw_data: The nested ``data`` field from the Zeeschuimer item (LinkedIn post).
            envelope: Zeeschuimer envelope fields (timestamp_collected, source_platform, etc.).

        Returns:
            Flat dict with keys compatible with the universal normalizer:
            ``id``, ``text``, ``url``, ``author_id``, ``author_display_name``,
            ``published_at``, ``likes_count``, ``shares_count``, ``comments_count``, etc.
        """
        # Extract activity URN for post ID and URL construction
        platform_id = self._extract_activity_id(raw_data)
        post_url = None
        if platform_id:
            post_url = (
                "https://www.linkedin.com/feed/update/"
                f"urn:li:activity:{platform_id}"
            )

        # Extract post text content
        text_content = self._extract_text(raw_data)

        # Extract author information
        author_id, author_display_name, author_is_company = self._extract_author(raw_data)

        # Extract timestamp (estimated from relative time string)
        timestamp_collected_ms = envelope.get("timestamp_collected", 0)
        time_ago_str = self._extract_time_ago(raw_data)
        published_at = self._estimate_timestamp(timestamp_collected_ms, time_ago_str)

        # Check if this is a promoted post (has no time indication)
        is_promoted = self._is_promoted(time_ago_str)

        # Extract engagement metrics
        likes_count = self._extract_likes(raw_data)
        shares_count = self._extract_shares(raw_data)
        comments_count = self._extract_comments(raw_data)

        # Extract media URLs
        image_urls = self._extract_images(raw_data)
        video_thumb_url = self._extract_video_thumbnail(raw_data)

        # Extract external link
        link_url = self._extract_link(raw_data)

        # Extract hashtags and mentions
        hashtags = self._extract_hashtags(raw_data)
        mentions = self._extract_mentions(raw_data)

        # Extract reaction breakdown
        reaction_breakdown = self._extract_reaction_breakdown(raw_data)

        # Extract inclusion context (why this post appeared in feed)
        inclusion_context = self._extract_inclusion_context(raw_data)

        # Build flat record
        flat_record: dict[str, Any] = {
            "id": platform_id,
            "platform_id": platform_id,
            "text": text_content,
            "text_content": text_content,
            "url": post_url,
            "author_id": author_id,
            "author_platform_id": author_id,
            "author_display_name": author_display_name,
            "author": author_display_name,
            "published_at": published_at,
            "timestamp": published_at,
            "likes_count": likes_count,
            "shares_count": shares_count,
            "comments_count": comments_count,
            "content_type": "post",
            # LinkedIn-specific metadata to preserve in raw_metadata
            "linkedin": {
                "is_promoted": is_promoted,
                "author_is_company": author_is_company,
                "time_ago_str": time_ago_str,
                "hashtags": hashtags,
                "mentions": mentions,
                "reaction_breakdown": reaction_breakdown,
                "inclusion_context": inclusion_context,
                "link_url": link_url,
                "image_urls": image_urls,
                "video_thumb_url": video_thumb_url,
            },
        }

        return flat_record

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    def _extract_activity_id(self, raw: dict[str, Any]) -> str | None:
        """Extract the numerical activity ID from URNs.

        LinkedIn URNs look like:
        urn:li:fs_updateV2:(urn:li:activity:7293847561234567890,...)
        or
        urn:li:activity:7293847561234567890

        We want to extract the numerical ID: 7293847561234567890
        """
        # Try updateMetadata.urn first
        update_metadata = raw.get("updateMetadata") or raw.get("update") or {}
        urn = update_metadata.get("urn") or update_metadata.get("updateMetadata", {}).get("urn")

        # Fallback to top-level id or preDashEntityUrn
        if not urn:
            urn = raw.get("id") or raw.get("preDashEntityUrn") or raw.get("urn")

        if not urn or not isinstance(urn, str):
            return None

        # Extract numerical ID from URN
        # Pattern: urn:li:activity:DIGITS or embedded in fs_updateV2
        match = re.search(r"activity:(\d+)", urn)
        if match:
            return match.group(1)

        # If no match, return the URN as-is (better than None)
        return urn

    def _extract_text(self, raw: dict[str, Any]) -> str:
        """Extract post text content from commentary field."""
        commentary = raw.get("commentary") or raw.get("updateContent") or {}
        text_obj = commentary.get("text") or {}
        return text_obj.get("text", "")

    def _extract_author(self, raw: dict[str, Any]) -> tuple[str | None, str | None, bool]:
        """Extract author platform ID, display name, and whether author is a company.

        Returns:
            Tuple of (author_id, author_display_name, author_is_company)
        """
        actor = raw.get("actor") or {}

        # Author display name
        name_obj = actor.get("name") or {}
        display_name = name_obj.get("text")

        # Author ID from profile URL
        nav_context = actor.get("navigationContext") or {}
        action_target = nav_context.get("actionTarget", "")

        # Extract path segment after linkedin.com/ (e.g., "in/john-doe" or "company/acme")
        author_id = None
        if isinstance(action_target, str) and "linkedin.com/" in action_target:
            path = action_target.split("linkedin.com/")[-1].split("?")[0]
            author_id = path

        # Determine if author is a company
        author_is_company = False
        if author_id and author_id.startswith("company/"):
            author_is_company = True

        # Alternative: check for *miniCompany in attributes
        attributes = name_obj.get("attributes", [])
        for attr in attributes:
            if "*miniCompany" in attr:
                author_is_company = True
                break

        return author_id, display_name, author_is_company

    def _extract_time_ago(self, raw: dict[str, Any]) -> str:
        """Extract relative time string (e.g., '18h', '2d', '3mo')."""
        actor = raw.get("actor") or {}
        sub_desc = actor.get("subDescription") or {}
        time_ago = sub_desc.get("text", "")

        # Extract text before first period (e.g., "18h • Edited" -> "18h")
        if "." in time_ago or "•" in time_ago:
            time_ago = re.split(r"[.•]", time_ago)[0].strip()

        return time_ago

    def _is_promoted(self, time_ago_str: str) -> bool:
        """Check if post is promoted (no time indication)."""
        # Promoted posts have no digits in the time string
        return not bool(re.search(r"\d", time_ago_str))

    def _estimate_timestamp(
        self,
        timestamp_collected_ms: int,
        time_ago_str: str,
    ) -> datetime | None:
        """Estimate publication timestamp from relative time string.

        This is imprecise for older posts. "3mo" could be off by up to 15 days.

        Args:
            timestamp_collected_ms: Zeeschuimer collection timestamp in milliseconds.
            time_ago_str: Relative time string (e.g., "18h", "2d", "3mo").

        Returns:
            Estimated publication datetime (UTC) or None if parsing fails.
        """
        if not timestamp_collected_ms or not time_ago_str:
            return None

        collected_at = datetime.fromtimestamp(timestamp_collected_ms / 1000, tz=timezone.utc)

        # Parse time_ago_str to timedelta
        offset = self._parse_time_ago(time_ago_str)
        if offset is None:
            return None

        return collected_at - offset

    def _parse_time_ago(self, time_ago: str) -> timedelta | None:
        """Parse relative time string to timedelta.

        Supports English formats: "5m", "18h", "2d", "3w", "2mo", "1yr"

        Args:
            time_ago: Relative time string.

        Returns:
            Timedelta representing the offset, or None if parsing fails.
        """
        if not time_ago:
            return None

        # Clean the string (remove non-alphanumeric except digits and letters)
        time_ago = time_ago.strip().lower()

        # Try to extract number and unit
        match = re.match(r"(\d+)\s*([a-z]+)", time_ago)
        if not match:
            return None

        number = int(match.group(1))
        unit = match.group(2)

        # Map units to timedelta
        if unit in ("m", "min", "mins", "minute", "minutes"):
            return timedelta(minutes=number)
        if unit in ("h", "hr", "hrs", "hour", "hours", "u"):  # "u" = Dutch "uur"
            return timedelta(hours=number)
        if unit in ("d", "day", "days"):
            return timedelta(days=number)
        if unit in ("w", "week", "weeks", "wk", "wks"):
            return timedelta(weeks=number)
        if unit in ("mo", "month", "months", "mnd", "maand"):  # "mnd" = Dutch "maand"
            # Approximate 1 month = 30 days
            return timedelta(days=number * 30)
        if unit in ("y", "yr", "year", "years", "j", "jaar"):  # "j" = Dutch "jaar"
            # Approximate 1 year = 365 days
            return timedelta(days=number * 365)

        return None

    @staticmethod
    def _get_social_counts(
        social_detail: dict[str, Any],
    ) -> dict[str, Any]:
        """Extract totalSocialActivityCounts from social detail."""
        return (
            social_detail.get("*totalSocialActivityCounts")
            or social_detail.get("totalSocialActivityCounts")
            or {}
        )

    def _extract_likes(self, raw: dict[str, Any]) -> int:
        """Extract total like/reaction count."""
        social_detail = raw.get("*socialDetail") or raw.get("socialDetail") or {}
        counts = self._get_social_counts(social_detail)
        num_likes = counts.get("numLikes", 0)

        # Fallback: likes.paging.total
        if num_likes == 0:
            likes_obj = social_detail.get("likes") or {}
            paging = likes_obj.get("paging") or {}
            num_likes = paging.get("total", 0)

        return int(num_likes) if num_likes else 0

    def _extract_shares(self, raw: dict[str, Any]) -> int:
        """Extract share count."""
        social_detail = raw.get("*socialDetail") or raw.get("socialDetail") or {}
        counts = self._get_social_counts(social_detail)
        num_shares = counts.get("numShares", 0)

        # Fallback: totalShares
        if num_shares == 0:
            num_shares = social_detail.get("totalShares", 0)

        return int(num_shares) if num_shares else 0

    def _extract_comments(self, raw: dict[str, Any]) -> int:
        """Extract comment count."""
        social_detail = raw.get("*socialDetail") or raw.get("socialDetail") or {}
        counts = self._get_social_counts(social_detail)
        num_comments = counts.get("numComments", 0)

        # Fallback: comments.paging.total
        if num_comments == 0:
            comments_obj = social_detail.get("comments") or {}
            paging = comments_obj.get("paging") or {}
            num_comments = paging.get("total", 0)

        return int(num_comments) if num_comments else 0

    def _extract_hashtags(self, raw: dict[str, Any]) -> list[str]:
        """Extract hashtag strings from post text attributes."""
        commentary = raw.get("commentary") or raw.get("updateContent") or {}
        text_obj = commentary.get("text") or {}

        hashtags: list[str] = []

        # Try attributes (legacy format)
        attributes = text_obj.get("attributes", [])
        for attr in attributes:
            if isinstance(attr, dict) and attr.get("type") == "HASHTAG":
                tracking_urn = attr.get("trackingUrn", "")
                # Extract hashtag text from URN or use raw trackingUrn
                if "hashtag:" in tracking_urn:
                    hashtag = tracking_urn.split("hashtag:")[-1]
                    hashtags.append(hashtag)

        # Try attributesV2 (newer format)
        attributes_v2 = text_obj.get("attributesV2", [])
        for attr in attributes_v2:
            if isinstance(attr, dict):
                detail = attr.get("detailData") or {}
                if "hashtag" in detail:
                    hashtag_text = detail["hashtag"].get("hashtag", "")
                    if hashtag_text:
                        hashtags.append(hashtag_text.lstrip("#"))

        return hashtags

    def _extract_mentions(self, raw: dict[str, Any]) -> list[str]:
        """Extract mentioned user IDs from post text attributes."""
        commentary = raw.get("commentary") or raw.get("updateContent") or {}
        text_obj = commentary.get("text") or {}

        mentions: list[str] = []

        # Try attributes
        attributes = text_obj.get("attributes", [])
        for attr in attributes:
            if isinstance(attr, dict):
                if attr.get("type") in ("PROFILE_MENTION", "COMPANY_NAME"):
                    # Extract mini profile
                    mini_profile = attr.get("*miniProfile") or attr.get("miniProfile") or {}
                    public_id = mini_profile.get("publicIdentifier")
                    if public_id:
                        mentions.append(public_id)

        # Try attributesV2
        attributes_v2 = text_obj.get("attributesV2", [])
        for attr in attributes_v2:
            if isinstance(attr, dict):
                detail = attr.get("detailData") or {}
                if "profile" in detail:
                    public_id = detail["profile"].get("publicIdentifier")
                    if public_id:
                        mentions.append(public_id)
                if "company" in detail:
                    public_id = detail["company"].get("universalName")
                    if public_id:
                        mentions.append(f"company/{public_id}")

        return mentions

    def _extract_reaction_breakdown(self, raw: dict[str, Any]) -> dict[str, int]:
        """Extract per-reaction-type counts."""
        social_detail = raw.get("*socialDetail") or raw.get("socialDetail") or {}
        counts = self._get_social_counts(social_detail)
        reaction_type_counts = counts.get("reactionTypeCounts", [])

        breakdown: dict[str, int] = {}
        for reaction in reaction_type_counts:
            if isinstance(reaction, dict):
                reaction_type = reaction.get("reactionType", "").lower()
                count = reaction.get("count", 0)
                if reaction_type:
                    breakdown[reaction_type] = int(count)

        return breakdown

    def _extract_images(self, raw: dict[str, Any]) -> list[str]:
        """Extract image URLs from content field."""
        content = raw.get("content") or {}
        images = content.get("images") or []

        image_urls: list[str] = []
        for img in images:
            if isinstance(img, dict):
                # vectorImage format
                vector_img = (
                    img.get("vectorImage")
                    or img.get("attributes", [{}])[0].get("vectorImage")
                    or {}
                )
                artifacts = vector_img.get("artifacts", [])

                # Pick the largest resolution
                if artifacts:
                    largest = max(artifacts, key=lambda a: a.get("width", 0))
                    root_url = vector_img.get("rootUrl", "")
                    file_segment = largest.get("fileIdentifyingUrlPathSegment", "")
                    if root_url and file_segment:
                        image_urls.append(root_url + file_segment)

        return image_urls

    def _extract_video_thumbnail(self, raw: dict[str, Any]) -> str | None:
        """Extract video thumbnail URL."""
        content = raw.get("content") or {}

        # Try *videoPlayMetadata
        video_meta = content.get("*videoPlayMetadata") or {}
        thumbnail = video_meta.get("thumbnail") or {}
        if thumbnail:
            artifacts = thumbnail.get("artifacts", [])
            if artifacts:
                return artifacts[0].get("url")

        # Try linkedInVideoComponent
        video_component = content.get("linkedInVideoComponent") or {}
        thumbnail = video_component.get("thumbnail") or {}
        if thumbnail:
            artifacts = thumbnail.get("artifacts", [])
            if artifacts:
                return artifacts[0].get("url")

        return None

    def _extract_link(self, raw: dict[str, Any]) -> str | None:
        """Extract external link URL attached to post."""
        content = raw.get("content") or {}
        nav_context = content.get("navigationContext") or {}
        action_target = nav_context.get("actionTarget")

        if action_target and isinstance(action_target, str):
            # Filter out LinkedIn internal URLs
            if action_target.startswith("http") and "linkedin.com" not in action_target:
                return action_target

        return None

    def _extract_inclusion_context(self, raw: dict[str, Any]) -> str | None:
        """Extract the 'why you're seeing this' header text."""
        header = raw.get("header") or {}
        text_obj = header.get("text") or {}
        return text_obj.get("text")
