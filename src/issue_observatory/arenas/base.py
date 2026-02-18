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
from datetime import datetime
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


class ArenaCollector(ABC):
    """Abstract base class for all Issue Observatory arena collectors.

    Subclasses must define the class-level attributes ``arena_name``,
    ``platform_name``, and ``supported_tiers``, and implement all abstract
    methods. The constructor injects a ``CredentialPool`` and a
    ``RateLimiter`` so that individual arena implementations do not need
    to manage credential rotation or rate-limit state directly.

    Class Attributes:
        arena_name: Logical arena group (e.g. ``"google_search"``,
            ``"social_media"``). Used as the ``arena`` column in
            ``content_records``.
        platform_name: Specific platform within an arena
            (e.g. ``"google"``, ``"bluesky"``). Used as the ``platform``
            column in ``content_records``.
        supported_tiers: List of ``Tier`` values this collector can operate
            at. Collectors that support only free access list ``[Tier.FREE]``.

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

    def __init__(
        self,
        credential_pool: CredentialPool | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.credential_pool = credential_pool
        self.rate_limiter = rate_limiter

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
        arenas). Paid arenas must override this method to return a realistic
        estimate so that the pre-flight credit check works correctly.

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
            "checked_at": datetime.utcnow().isoformat() + "Z",
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
