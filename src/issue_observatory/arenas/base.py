"""Abstract base class for all arena collectors.

Every platform integration must subclass ``ArenaCollector`` and implement
the required interface methods. Stubs should raise ``NotImplementedError``
with an explanatory message where a platform does not support a given
collection mode (e.g. ``collect_by_actors`` for Google Search).

Example usage::

    from issue_observatory.arenas.base import ArenaCollector, Tier

    class MyCollector(ArenaCollector):
        arena_name = "my_arena"
        platform_name = "my_platform"
        supported_tiers = [Tier.FREE]

        async def collect_by_terms(self, terms, tier, ...): ...
        async def collect_by_actors(self, actor_ids, tier, ...): ...
        def get_tier_config(self, tier): ...
        def normalize(self, raw_item): ...
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from issue_observatory.core.credential_pool import CredentialPool
    from issue_observatory.workers.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class Tier(str, Enum):
    """Operational tier controlling API provider and cost level.

    Attributes:
        FREE: Uses free-access APIs or unauthenticated endpoints only.
            No credential required. Returns empty results gracefully if
            the arena has no free option.
        MEDIUM: Uses affordable paid services (e.g. Serper.dev, TwitterAPI.io).
            Credential required; credits are deducted per use.
        PREMIUM: Uses the best available API (e.g. official X Pro, SerpAPI).
            Highest quality and rate limits; highest cost per result.
    """

    FREE = "free"
    MEDIUM = "medium"
    PREMIUM = "premium"


class TemporalMode(str, Enum):
    """Temporal capabilities of an arena collector.

    Attributes:
        HISTORICAL: Supports deep historical search, can retrieve content
            from years ago (e.g. GDELT, Common Crawl, Wayback Machine, Event Registry).
        RECENT: Limited to recent content only, typically within the last
            few days or weeks. Date filters may be ignored or return incomplete
            results (e.g. Google Search, X/Twitter, Reddit, Bluesky).
        FORWARD_ONLY: Real-time or near-real-time only, cannot backfill
            historical content. Useful for monitoring from collection start
            onward (e.g. RSS feeds, Via Ritzau).
        MIXED: Supports both historical search (via API) and real-time
            streaming (e.g. YouTube: historical via Data API, real-time via RSS).
    """

    HISTORICAL = "historical"
    RECENT = "recent"
    FORWARD_ONLY = "forward_only"
    MIXED = "mixed"


class ArenaCollector(ABC):
    """Abstract base class for all Issue Observatory arena collectors.

    Subclasses must define the class-level attributes ``arena_name``,
    ``platform_name``, ``supported_tiers``, and ``temporal_mode``, and
    implement all abstract methods. The constructor injects a
    ``CredentialPool`` and a ``RateLimiter`` so that individual arena
    implementations do not need to manage credential rotation or rate-limit
    state directly.

    Class Attributes:
        arena_name: Logical arena group (e.g. ``"google_search"``,
            ``"social_media"``). Used as the ``arena`` column in
            ``content_records``.
        platform_name: Specific platform within an arena
            (e.g. ``"google"``, ``"bluesky"``). Used as the ``platform``
            column in ``content_records``.
        supported_tiers: List of ``Tier`` values this collector can operate
            at. Collectors that support only free access list ``[Tier.FREE]``.
        temporal_mode: ``TemporalMode`` value describing the arena's date
            range capabilities. Used to warn researchers when date filters
            may be ignored or incomplete.

    Args:
        credential_pool: Optional shared credential pool. If ``None``,
            the collector must either use unauthenticated access or raise
            ``NoCredentialAvailableError``.
        rate_limiter: Optional shared Redis-backed rate limiter. If ``None``,
            rate limiting is the collector's own responsibility.
    """

    arena_name: str
    platform_name: str
    supported_tiers: list[Tier]
    temporal_mode: TemporalMode

    def __init__(
        self,
        credential_pool: CredentialPool | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.credential_pool = credential_pool
        self.rate_limiter = rate_limiter
        # GR-14: set of platform_user_id strings for actors whose content
        # should bypass SHA-256 pseudonymization.  Populated by the Celery
        # task before calling collect_by_terms() / collect_by_actors().
        # Subclass normalize() implementations should pass this set to
        # Normalizer.normalize() as the ``public_figure_ids`` argument.
        self._public_figure_ids: set[str] = set()

    # ------------------------------------------------------------------
    # Abstract interface — must be implemented by every arena
    # ------------------------------------------------------------------

    @abstractmethod
    async def collect_by_terms(
        self,
        terms: list[str],
        tier: Tier,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
        term_groups: list[list[str]] | None = None,
        language_filter: list[str] | None = None,
    ) -> list[dict]:  # type: ignore[type-arg]
        """Collect content matching one or more search terms.

        Implementations must apply Danish locale defaults where the
        platform supports them (e.g. ``gl=dk&hl=da`` for Google,
        ``lang:da`` for Bluesky).

        When ``term_groups`` is provided, it encodes boolean AND/OR logic:
        each inner list is a set of terms to be ANDed together, and the
        groups themselves are ORed.  Implementations that support native
        boolean query syntax should use :func:`~arenas.query_builder.
        format_boolean_query_for_platform` to build the query string.
        Implementations that do not support native boolean should issue one
        request per group and combine results (deduplicating by
        ``content_hash``).  When ``term_groups`` is ``None`` the plain
        ``terms`` list is used as before.

        Args:
            terms: List of search terms or phrases to query.  Used as a
                flat list when ``term_groups`` is ``None``.
            tier: Operational tier controlling which API provider is used.
            date_from: Earliest publication date (inclusive). Accepts ISO
                8601 string or ``datetime`` object.  ``None`` means no lower
                bound.
            date_to: Latest publication date (inclusive). ``None`` means no
                upper bound (collect up to now).
            max_results: Upper bound on returned records. ``None`` means
                use the tier default.
            term_groups: Optional boolean group structure produced by
                :func:`~arenas.query_builder.build_boolean_query_groups`.
                When provided, the collector uses this instead of the flat
                ``terms`` list.
            language_filter: Optional list of ISO 639-1 language codes
                (e.g. ``["da", "en"]``) to restrict collected content.
                When ``None`` the arena's default locale applies.

        Returns:
            List of normalized content record dicts matching the
            ``content_records`` universal schema.

        Raises:
            ArenaCollectionError: On unrecoverable collection failure.
            ArenaRateLimitError: When the upstream API returns HTTP 429.
            ArenaAuthError: When credentials are rejected by the upstream API.
            NoCredentialAvailableError: When no suitable credential exists.
        """

    @abstractmethod
    async def collect_by_actors(
        self,
        actor_ids: list[str],
        tier: Tier,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
    ) -> list[dict]:  # type: ignore[type-arg]
        """Collect content published by specific actors/accounts.

        For platforms that do not support actor-based collection (e.g.
        Google Search), implementations should raise ``NotImplementedError``
        with a clear explanation::

            raise NotImplementedError(
                "Google Search does not support actor-based collection. "
                "Use collect_by_terms() with 'site:domain.com' syntax."
            )

        Args:
            actor_ids: Platform-native user identifiers (e.g. Reddit
                usernames, Bluesky DIDs, YouTube channel IDs).
            tier: Operational tier.
            date_from: Earliest publication date (inclusive).
            date_to: Latest publication date (inclusive).
            max_results: Upper bound on returned records.

        Returns:
            List of normalized content record dicts.

        Raises:
            NotImplementedError: If the platform does not support
                actor-based collection.
            ArenaCollectionError: On unrecoverable collection failure.
            ArenaRateLimitError: On HTTP 429 from the upstream API.
            ArenaAuthError: On credential rejection.
            NoCredentialAvailableError: When no suitable credential exists.
        """

    @abstractmethod
    def get_tier_config(self, tier: Tier) -> dict:  # type: ignore[type-arg]
        """Return the API / service configuration for a given tier.

        The returned dict is arena-specific but should include at minimum:

        - ``provider``: Name of the API provider used at this tier.
        - ``max_results_per_query``: Default result cap.
        - ``requires_credentials``: Whether a credential is needed.
        - ``credits_per_result``: Credit cost per returned record.

        Args:
            tier: The tier to retrieve configuration for.

        Returns:
            Arena-specific configuration dict for the requested tier.

        Raises:
            ValueError: If ``tier`` is not in ``self.supported_tiers``.
        """

    @abstractmethod
    def normalize(self, raw_item: dict) -> dict:  # type: ignore[type-arg]
        """Normalize a single platform-specific record to the universal schema.

        Implementations should populate all fields that the platform
        provides and set missing optional fields to ``None``. The
        ``pseudonymized_author_id`` must be computed via
        ``Normalizer.pseudonymize_author()``. The ``content_hash`` must
        be computed via ``Normalizer.compute_content_hash()``.

        Args:
            raw_item: Raw dict as returned by the upstream API.

        Returns:
            Dict matching the ``content_records`` universal schema.

        Raises:
            NormalizationError: If the raw item cannot be normalized.
        """

    # ------------------------------------------------------------------
    # Concrete helpers — may be overridden
    # ------------------------------------------------------------------

    def set_public_figure_ids(self, ids: set[str]) -> None:
        """Register a set of platform user IDs for the GR-14 bypass.

        Call this **before** ``collect_by_terms()`` or
        ``collect_by_actors()`` when the owning query design has
        ``public_figure=True`` actors.  The ``_public_figure_ids`` set is
        then available inside the collector's ``normalize()`` method and
        must be forwarded to
        :meth:`~core.normalizer.Normalizer.normalize` as the
        ``public_figure_ids`` keyword argument.

        This method is a no-op when *ids* is empty — existing collectors
        that do not implement the GR-14 hook continue to pseudonymize all
        authors normally.

        Args:
            ids: Set of ``platform_user_id`` strings whose authors should
                bypass SHA-256 pseudonymization (GR-14 — GDPR Art. 89(1)
                research exemption).  Pass an empty set to clear any
                previously registered IDs.
        """
        self._public_figure_ids = ids

    async def estimate_credits(
        self,
        terms: list[str] | None = None,
        actor_ids: list[str] | None = None,
        tier: Tier = Tier.FREE,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
    ) -> int:
        """Estimate the number of credits a collection run will consume.

        The default implementation returns ``0`` (suitable for free-tier
        arenas with no API cost). Paid arenas should override this method to
        return a realistic heuristic estimate based on:

        - Number of search terms
        - Date range duration (days)
        - Expected result volume per term/day
        - Tier-specific rate limits and result caps

        Estimates are heuristic-based and may vary from actual costs by ±50%.
        They provide order-of-magnitude accuracy for budget planning, not
        exact billing.

        Args:
            terms: Search terms to be queried.
            actor_ids: Actor IDs to be monitored.
            tier: Requested tier.
            date_from: Start of the date range.
            date_to: End of the date range.
            max_results: Requested result cap.

        Returns:
            Estimated credit cost as a non-negative integer.
        """
        return 0

    async def refresh_engagement(
        self,
        external_ids: list[str],
        tier: Tier = Tier.FREE,
    ) -> dict[str, dict[str, int]]:
        """Re-fetch engagement metrics for existing content records.

        This optional method allows arenas to update engagement counts
        (likes, shares, comments, views) for previously collected content.
        Not all arenas support metric refresh — the default implementation
        returns an empty dict, signaling that refresh is not available.

        Arenas that support refresh should:
        1. Query the platform API to fetch current engagement counts for
           each external_id
        2. Return a mapping of external_id → {metric_name: count}
        3. Handle API errors gracefully (skip unavailable records)
        4. Respect rate limits (use the injected rate_limiter)

        Standard metric names:
        - ``likes_count``
        - ``shares_count``
        - ``comments_count``
        - ``views_count``

        Args:
            external_ids: List of platform-native content identifiers
                (e.g. tweet IDs, YouTube video IDs, Reddit submission IDs).
            tier: Operational tier controlling which API provider is used.

        Returns:
            Mapping of external_id (str) to engagement metrics (dict).
            Missing external_ids indicate the arena could not refresh
            those records (e.g. content deleted, API error).

        Example return value::

            {
                "1234567890": {
                    "likes_count": 42,
                    "shares_count": 7,
                    "comments_count": 13,
                    "views_count": 1500,
                },
                "9876543210": {
                    "likes_count": 3,
                    "shares_count": 0,
                    "comments_count": 1,
                },
            }
        """
        return {}

    async def health_check(self) -> dict:  # type: ignore[type-arg]
        """Verify that the arena's upstream data sources are reachable.

        The default implementation returns a minimal ``not_implemented``
        status. Arenas should override this to make a lightweight API call
        (e.g. fetching a single result or calling a ``/status`` endpoint)
        and report the outcome.

        Returns:
            Dict with at minimum:
            - ``status``: ``"ok"`` | ``"degraded"`` | ``"down"`` |
              ``"not_implemented"``.
            - ``arena``: Arena name.
            - ``platform``: Platform name.
            - ``checked_at``: ISO 8601 timestamp string.
        """
        return {
            "status": "not_implemented",
            "arena": getattr(self, "arena_name", "unknown"),
            "platform": getattr(self, "platform_name", "unknown"),
            "checked_at": datetime.now(timezone.utc).isoformat() + "Z",
        }

    def _validate_tier(self, tier: Tier) -> None:
        """Assert that *tier* is in ``self.supported_tiers``.

        Tier Precedence Rule (IP2-022):
        When an arena worker resolves which tier to use for a collection run,
        it must follow this priority order (highest priority first):

        1. Per-arena tier in ``CollectionRun.arenas_config`` (saved from the
           query design's ``arenas_config`` at launch time).
        2. Per-arena tier in the launcher request's ``arenas_config``.
        3. Global default ``CollectionRun.tier`` field.

        Celery tasks and orchestration workers are responsible for reading
        the merged ``CollectionRun.arenas_config`` and passing the resolved
        per-arena tier to each collector's ``collect_by_terms()`` /
        ``collect_by_actors()`` call.  Workers must NOT fall back to the
        global tier without first checking the per-arena config.

        Args:
            tier: Tier to validate.

        Raises:
            ValueError: If the tier is not supported by this collector.
        """
        if tier not in self.supported_tiers:
            raise ValueError(
                f"Tier '{tier.value}' is not supported by {self.__class__.__name__}. "
                f"Supported tiers: {[t.value for t in self.supported_tiers]}"
            )

    def __repr__(self) -> str:
        """Return a developer-friendly representation of the collector."""
        return (
            f"<{self.__class__.__name__} "
            f"arena={getattr(self, 'arena_name', '?')} "
            f"platform={getattr(self, 'platform_name', '?')}>"
        )
