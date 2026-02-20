"""VKontakte (VK) arena collector stub.

DEFERRED ARENA -- Phase 4 / Future
====================================

This module is a stub. All collection methods immediately raise
``ArenaCollectionError`` with a clear message directing the caller to the
legal review requirement. No network requests are made.

The stub is structured to show the full intended implementation so that,
once legal review is complete, a developer can implement each method by
removing the ``raise`` statement and replacing it with the documented logic.

DO NOT activate or enable collection without completing the legal review
described in docs/arenas/new_arenas_implementation_plan.md section 6.10
and the arena brief at docs/arenas/vkontakte.md.

Legal Considerations (Summary)
-------------------------------
- EU sanctions context: VK Company sanctions status must be verified.
- Cross-border data transfer: No Russia GDPR adequacy decision (Schrems II).
- Russian jurisdiction: Federal Law No. 152-FZ interaction with GDPR.
- Geo-restrictions: API access from Denmark must be empirically verified.
- University DPO sign-off required before any data collection begins.

Intended Implementation (for reference)
----------------------------------------
collect_by_terms():
    POST to https://api.vk.com/method/newsfeed.search
    Params: q={term}&count=200&start_time={unix}&end_time={unix}
            &access_token={token}&v=5.199&extended=1
    Paginate via next_from cursor in response.

collect_by_actors():
    POST to https://api.vk.com/method/wall.get
    Params: owner_id={actor_id}&count=100&offset={offset}
            &access_token={token}&v=5.199&extended=1
    Negative owner_id for communities; positive for users.
    Paginate via numeric offset.

normalize():
    Map VK post fields to the universal content_records schema:
    - platform_id  <- "{owner_id}_{post_id}"
    - text_content <- post.text
    - url          <- "https://vk.com/wall{owner_id}_{post_id}"
    - published_at <- datetime.utcfromtimestamp(post.date)
    - author_platform_id <- str(post.from_id)
    - author_display_name <- resolved from profiles[] (extended=1 response)
    - views_count  <- post.views.count (community posts only)
    - likes_count  <- post.likes.count
    - shares_count <- post.reposts.count
    - comments_count <- post.comments.count
    - raw_metadata <- full post object + resolved profiles/groups
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from issue_observatory.arenas.base import ArenaCollector, TemporalMode, Tier
from issue_observatory.arenas.registry import register
from issue_observatory.arenas.vkontakte.config import (
    VKONTAKTE_TIERS,
)
from issue_observatory.config.tiers import TierConfig
from issue_observatory.core.exceptions import ArenaCollectionError

logger = logging.getLogger(__name__)

_DEFERRED_MESSAGE: str = (
    "VKontakte arena is not yet implemented. This arena is DEFERRED pending "
    "university legal review of EU sanctions implications. "
    "See docs/arenas/new_arenas_implementation_plan.md section 6 for details."
)

_ARENA: str = "social_media"
_PLATFORM: str = "vkontakte"


@register
class VKontakteCollector(ArenaCollector):
    """Stub collector for the VKontakte (VK) social media platform.

    DEFERRED ARENA -- Phase 4 / Future.

    This class is registered in the arena registry so that the platform
    appears in API documentation and status reports. All collection methods
    raise ``ArenaCollectionError`` immediately with a message directing the
    caller to the pending legal review.

    Once university legal review is complete and the arena is approved for
    implementation, each method stub should be replaced with the full
    implementation as documented in the module docstring above.

    Class Attributes:
        arena_name: ``"social_media"`` (registry key and content_records
            ``arena`` column value).
        platform_name: ``"vkontakte"``
        supported_tiers: ``[Tier.FREE]`` -- VK is a free-only arena.

    Intended credential requirements (post-legal-review):
        CredentialPool platform: ``"vkontakte"``
        Fields: ``{"access_token": "...", "app_id": "..."}``
        A VK standalone application with wall + groups + offline OAuth scopes.
    """

    arena_name: str = "social_media"
    platform_name: str = "vkontakte"
    supported_tiers: list[Tier] = [Tier.FREE]
    temporal_mode: TemporalMode = TemporalMode.RECENT

    def __init__(
        self,
        credential_pool: Any = None,
        rate_limiter: Any = None,
    ) -> None:
        """Initialise the VKontakte collector stub.

        Args:
            credential_pool: Unused until the arena is activated. Pass None.
            rate_limiter: Unused until the arena is activated. Pass None.
        """
        super().__init__(credential_pool=credential_pool, rate_limiter=rate_limiter)
        logger.warning(
            "VKontakteCollector instantiated but this arena is DEFERRED pending "
            "university legal review. No collection will occur."
        )

    # ------------------------------------------------------------------
    # ArenaCollector abstract method implementations (stubs)
    # ------------------------------------------------------------------

    async def collect_by_terms(
        self,
        terms: list[str],
        tier: Tier,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
        term_groups: list[list[str]] | None = None,
        language_filter: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Stub: would collect VK posts matching search terms via newsfeed.search.

        DEFERRED: This method raises ArenaCollectionError immediately.

        Intended implementation:
            For each term, POST to https://api.vk.com/method/newsfeed.search
            with params q={term}&count=200&start_time={unix}&end_time={unix}
            &access_token={token}&v=5.199&extended=1. Paginate via next_from
            cursor. Normalize results and apply max_results cap.

        Args:
            terms: Search terms to query against VK newsfeed.
            tier: Must be Tier.FREE (only supported tier).
            date_from: Earliest publication date (maps to start_time Unix ts).
            date_to: Latest publication date (maps to end_time Unix ts).
            max_results: Upper bound on returned records.
            term_groups: Boolean AND/OR groups for multi-term queries.
            language_filter: Not natively supported by VK; would be applied
                client-side via language detection.

        Raises:
            ArenaCollectionError: Always -- arena is deferred pending legal
                review.
        """
        raise ArenaCollectionError(
            _DEFERRED_MESSAGE,
            arena=_ARENA,
            platform=_PLATFORM,
        )

    async def collect_by_actors(
        self,
        actor_ids: list[str],
        tier: Tier,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """Stub: would collect posts from VK community/user walls via wall.get.

        DEFERRED: This method raises ArenaCollectionError immediately.

        Intended implementation:
            For each actor_id (a VK owner_id: negative for communities,
            positive for users), POST to https://api.vk.com/method/wall.get
            with params owner_id={actor_id}&count=100&offset={offset}
            &access_token={token}&v=5.199&extended=1. Paginate via numeric
            offset until all posts in the date range are collected.

        Args:
            actor_ids: VK owner IDs. Negative integers are community IDs
                (e.g. "-12345"); positive integers are user IDs.
            tier: Must be Tier.FREE (only supported tier).
            date_from: Earliest publication date (inclusive).
            date_to: Latest publication date (inclusive).
            max_results: Upper bound on returned records.

        Raises:
            ArenaCollectionError: Always -- arena is deferred pending legal
                review.
        """
        raise ArenaCollectionError(
            _DEFERRED_MESSAGE,
            arena=_ARENA,
            platform=_PLATFORM,
        )

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Stub: would normalize a raw VK post/comment to the universal schema.

        DEFERRED: Raises NotImplementedError immediately.

        Intended field mapping:
            platform_id      <- "{owner_id}_{post_id}" (e.g. "-12345_67890")
            content_type     <- "post" or "comment"
            text_content     <- post["text"]
            title            <- None (VK posts have no title field)
            url              <- "https://vk.com/wall{owner_id}_{post_id}"
            language         <- None (no language field; detect downstream)
            published_at     <- datetime.utcfromtimestamp(post["date"]).isoformat()
            author_platform_id   <- str(post["from_id"])
            author_display_name  <- resolved from profiles[] in extended response
            views_count      <- post.get("views", {}).get("count")
            likes_count      <- post.get("likes", {}).get("count")
            shares_count     <- post.get("reposts", {}).get("count")
            comments_count   <- post.get("comments", {}).get("count")
            media_urls       <- [att["photo"]["sizes"][-1]["url"] for att in
                                 post.get("attachments", []) if att["type"] == "photo"]
            raw_metadata     <- full post object + profiles[] + groups[]

        Args:
            raw_item: Raw dict from VK API wall.get or newsfeed.search response.

        Raises:
            NotImplementedError: Always -- normalization not yet implemented
                for this deferred arena.
        """
        raise NotImplementedError(
            "VKontakte normalization not yet implemented (deferred arena). "
            "See docs/arenas/vkontakte.md section 5 for the full field mapping."
        )

    def get_tier_config(self, tier: Tier) -> TierConfig:
        """Return the tier configuration for the VKontakte arena.

        Args:
            tier: Requested operational tier.

        Returns:
            TierConfig for the requested tier.

        Raises:
            ValueError: If tier is not in VKONTAKTE_TIERS (only FREE is
                supported).
        """
        if tier not in VKONTAKTE_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}' for vkontakte. "
                f"Valid tiers: {list(VKONTAKTE_TIERS.keys())}"
            )
        return VKONTAKTE_TIERS[tier]

    async def health_check(self) -> dict[str, Any]:
        """Return a not_implemented health status for the deferred VK arena.

        Does not make any network request. Returns a static status dict
        explaining that the arena is deferred pending legal review.

        Returns:
            Health status dict with status="not_implemented".
        """
        return {
            "status": "not_implemented",
            "arena": _ARENA,
            "platform": _PLATFORM,
            "detail": (
                "VKontakte arena is deferred pending university legal review. "
                "See docs/arenas/new_arenas_implementation_plan.md section 6 "
                "for details."
            ),
        }
