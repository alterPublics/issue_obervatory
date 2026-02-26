"""Google Search arena collector implementation.

Collects Google Search results via two API providers depending on the
operational tier:

- **MEDIUM** — Serper.dev (``https://google.serper.dev/search``).
  POST requests with JSON body; paginated via the ``page`` parameter.
- **PREMIUM** — SerpAPI (``https://serpapi.com/search``).
  GET requests with query parameters; paginated via ``start`` offset.

**FREE tier is unavailable** — the collector logs a warning and returns an
empty list when ``tier=Tier.FREE``.

All requests include Danish locale parameters (``gl=dk``, ``hl=da``) sourced
from :data:`issue_observatory.config.danish_defaults.DANISH_GOOGLE_PARAMS`.

Low-level HTTP request logic lives in :mod:`._client` to keep this module
within the ~400-line file size limit.

Credentials are acquired from the injected :class:`CredentialPool` using
the platform/tier naming convention::

    SERPER_MEDIUM_API_KEY    (Serper.dev, MEDIUM tier)
    SERPAPI_PREMIUM_API_KEY  (SerpAPI, PREMIUM tier)

Rate limiting is delegated to the injected :class:`RateLimiter` when present.

``collect_by_actors()`` accepts actor identifiers as domain names and
reformulates them as ``site:`` queries before delegating to
``collect_by_terms()``.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from issue_observatory.arenas.base import ArenaCollector, TemporalMode, Tier
from issue_observatory.arenas.google_search._client import fetch_serper, fetch_serpapi
from issue_observatory.arenas.query_builder import format_boolean_query_for_platform
from issue_observatory.arenas.google_search.config import (
    DANISH_PARAMS,
    GOOGLE_SEARCH_TIERS,
    MAX_RESULTS_PER_PAGE,
    SERPER_API_URL,
)
from issue_observatory.arenas.registry import register
from issue_observatory.config.tiers import TierConfig
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.core.normalizer import Normalizer

logger = logging.getLogger(__name__)


@register
class GoogleSearchCollector(ArenaCollector):
    """Collects Google Search results via Serper.dev (MEDIUM) or SerpAPI (PREMIUM).

    Supported tiers:
    - ``Tier.FREE``    — not available; returns empty list with warning.
    - ``Tier.MEDIUM``  — Serper.dev API ($0.30/1K queries).
    - ``Tier.PREMIUM`` — SerpAPI (higher cost, higher rate limits).

    Class Attributes:
        arena_name: ``"google_search"``
        platform_name: ``"google_search"``
        supported_tiers: ``[Tier.MEDIUM, Tier.PREMIUM]``

    Args:
        credential_pool: Optional credential pool for API key rotation.
            If ``None``, the collector cannot collect at MEDIUM or PREMIUM tier.
        rate_limiter: Optional Redis-backed rate limiter.  When present,
            every outbound HTTP request is gated through it.
        http_client: Optional injected :class:`httpx.AsyncClient`.  Inject
            for testing.  If ``None``, a new client is created per collection
            call.
    """

    arena_name: str = "google_search"
    platform_name: str = "google_search"
    supported_tiers: list[Tier] = [Tier.MEDIUM, Tier.PREMIUM]
    temporal_mode: TemporalMode = TemporalMode.RECENT

    def __init__(
        self,
        credential_pool: Any = None,
        rate_limiter: Any = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(credential_pool=credential_pool, rate_limiter=rate_limiter)
        self._http_client = http_client
        self._normalizer = Normalizer()

    # ------------------------------------------------------------------
    # ArenaCollector abstract method implementations
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
        """Collect Google Search results for each search term.

        When ``term_groups`` is provided the groups are serialised into a
        single boolean query string using implicit-AND (space-separated)
        and explicit ``OR`` syntax supported by Serper.dev / SerpAPI.  One
        query is issued per OR-group to maximise result diversity.

        Args:
            terms: Search terms to query independently (used when
                ``term_groups`` is ``None``).
            tier: Operational tier.  FREE returns ``[]`` with a warning.
            date_from: Not used — Google Search has no API-level date filter.
            date_to: Not used — see ``date_from``.
            max_results: Upper bound on returned records.  ``None`` uses the
                tier default.
            term_groups: Optional boolean AND/OR group structure.  When
                provided, one request is issued per group (group terms are
                ANDed via implicit space syntax).
            language_filter: Not used by this arena (Danish locale params
                are always applied via DANISH_PARAMS).

        Returns:
            List of normalized content record dicts.

        Raises:
            ArenaRateLimitError: On HTTP 429 from the upstream API.
            ArenaAuthError: On HTTP 401 or 403 from the upstream API.
            ArenaCollectionError: On other unrecoverable API errors.
            NoCredentialAvailableError: When no API key is available.
        """
        if tier == Tier.FREE:
            logger.warning(
                "google_search: FREE tier is not available (no free Google Search API). "
                "Returning empty results. Use MEDIUM or PREMIUM tier."
            )
            return []

        tier_config = self.get_tier_config(tier)
        if tier_config is None:
            logger.warning("google_search: tier %s has no config. Returning [].", tier.value)
            return []

        effective_max = max_results if max_results is not None else tier_config.max_results_per_run
        cred = await self._acquire_credential(tier)

        # Build the list of query strings to issue.
        # Boolean mode: one query per AND-group (groups are ORed by running separately).
        # Simple mode: one query per term.
        if term_groups is not None:
            query_strings: list[str] = [
                format_boolean_query_for_platform(groups=[grp], platform="google")
                for grp in term_groups
            ]
        else:
            query_strings = list(terms)

        all_records: list[dict[str, Any]] = []

        try:
            async with self._build_http_client() as client:
                for query in query_strings:
                    if len(all_records) >= effective_max:
                        break
                    records = await self._collect_term(
                        client=client,
                        term=query,
                        tier=tier,
                        credential=cred,
                        max_results=effective_max - len(all_records),
                    )
                    all_records.extend(records)
        finally:
            if self.credential_pool is not None:
                await self.credential_pool.release(credential_id=cred["id"])

        logger.info(
            "google_search: collected %d records for %d queries at tier=%s",
            len(all_records),
            len(query_strings),
            tier.value,
        )
        return all_records

    async def collect_by_actors(
        self,
        actor_ids: list[str],
        tier: Tier,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect Google Search results scoped to specific actor domains.

        Google Search does not natively support actor-based collection.
        Each *actor_id* is treated as a domain name and converted to a
        ``site:`` query before delegating to :meth:`collect_by_terms`.

        Example::

            actor_id = "dr.dk" → query = "site:dr.dk"

        Args:
            actor_ids: Domain names for each actor (e.g. ``"dr.dk"``).
            tier: Operational tier.
            date_from: Not used.
            date_to: Not used.
            max_results: Maximum records to return across all actors.

        Returns:
            List of normalized content record dicts.
        """
        site_terms = [f"site:{actor_id.strip()}" for actor_id in actor_ids]
        logger.info(
            "google_search: collect_by_actors converted %d actor IDs to site: queries.",
            len(site_terms),
        )
        return await self.collect_by_terms(
            terms=site_terms,
            tier=tier,
            date_from=date_from,
            date_to=date_to,
            max_results=max_results,
        )

    def get_tier_config(self, tier: Tier) -> TierConfig | None:
        """Return the tier configuration for this arena.

        Args:
            tier: The requested operational tier.

        Returns:
            :class:`TierConfig` for MEDIUM and PREMIUM.  ``None`` for FREE.

        Raises:
            ValueError: If *tier* is not a recognised :class:`Tier` value.
        """
        if tier not in GOOGLE_SEARCH_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}' for google_search. "
                f"Valid tiers: {list(GOOGLE_SEARCH_TIERS.keys())}"
            )
        return GOOGLE_SEARCH_TIERS[tier]

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single Serper.dev or SerpAPI organic result.

        Delegates to :class:`Normalizer` with ``content_type="search_result"``
        set on the raw item before normalization.  Raw item is preserved in
        ``raw_metadata``.

        When ``self._public_figure_ids`` is non-empty (set by the Celery task
        via :meth:`~arenas.base.ArenaCollector.set_public_figure_ids`), the
        public-figure ID set is forwarded to the normalizer so that records
        authored by known public officials bypass SHA-256 pseudonymization
        (GR-14 — GDPR Art. 89(1) research exemption).

        Expected input fields (Serper.dev):
        - ``title``, ``link`` (URL), ``snippet`` (text), ``position``, ``date``.

        Args:
            raw_item: Raw dict from the ``organic`` list in the API response.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        enriched = dict(raw_item)
        enriched.setdefault("content_type", "search_result")
        # Set language based on Danish locale settings (gl=dk, hl=da)
        enriched.setdefault("language", "da")

        # author_display_name = domain extracted from the result URL
        result_url: str = raw_item.get("link", "") or ""
        try:
            enriched["author_display_name"] = urlparse(result_url).netloc.removeprefix("www.")
        except Exception:  # noqa: BLE001
            enriched["author_display_name"] = ""

        # text_content is set to None — the scraper will populate it later.
        # The snippet is preserved in raw_metadata instead.
        snippet: str | None = raw_item.get("snippet")
        enriched["text_content"] = None

        # Extract search term matched if present
        search_term = raw_item.get("_search_term")
        search_terms_matched = [search_term] if search_term else []

        normalized = self._normalizer.normalize(
            raw_item=enriched,
            platform=self.platform_name,
            arena=self.arena_name,
            collection_tier="medium",  # overwritten by Celery tasks with actual tier
            public_figure_ids=self._public_figure_ids or None,
            search_terms_matched=search_terms_matched,
        )

        # Store the snippet in raw_metadata and signal scrape intent.
        # The normalizer sets raw_metadata = dict(enriched), so we patch it here
        # to add the search_snippet key cleanly.
        if isinstance(normalized.get("raw_metadata"), dict):
            normalized["raw_metadata"]["search_snippet"] = snippet
        normalized["scrape_status"] = "pending"

        return normalized

    async def health_check(self) -> dict[str, Any]:
        """Verify Serper.dev connectivity with a minimal test query.

        Returns:
            Dict with ``status`` (``"ok"`` | ``"degraded"`` | ``"down"``),
            ``arena``, ``platform``, ``checked_at``, and optionally ``detail``.
        """
        checked_at = datetime.now(timezone.utc).isoformat() + "Z"
        base: dict[str, Any] = {
            "arena": self.arena_name,
            "platform": self.platform_name,
            "checked_at": checked_at,
        }

        cred = None
        if self.credential_pool is not None:
            cred = await self.credential_pool.acquire(platform="serper", tier="medium")

        if cred is None:
            return {
                **base,
                "status": "degraded",
                "detail": "No SERPER_MEDIUM_API_KEY credential available for health check.",
            }

        payload = {"q": "test", **DANISH_PARAMS, "num": 1}
        headers = {"X-API-KEY": cred["api_key"], "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(SERPER_API_URL, json=payload, headers=headers)
                response.raise_for_status()
                return {**base, "status": "ok"}
        except httpx.HTTPStatusError as exc:
            return {
                **base,
                "status": "degraded",
                "detail": f"HTTP {exc.response.status_code} from Serper.dev",
            }
        except httpx.RequestError as exc:
            return {**base, "status": "down", "detail": f"Connection error: {exc}"}
        finally:
            if self.credential_pool is not None:
                await self.credential_pool.release(credential_id=cred["id"])

    async def estimate_credits(
        self,
        terms: list[str] | None = None,
        actor_ids: list[str] | None = None,
        tier: Tier = Tier.FREE,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
    ) -> int:
        """Estimate the credit cost for a Google Search collection run.

        1 credit = 1 API query (one page of up to 10 results).

        Args:
            terms: Search terms to be queried.
            actor_ids: Actor IDs (converted to ``site:`` terms).
            tier: Requested tier.
            date_from: Not used.
            date_to: Not used.
            max_results: Upper bound on results.

        Returns:
            Estimated credit cost as a non-negative integer.
        """
        if tier == Tier.FREE:
            return 0
        tier_config = self.get_tier_config(tier)
        if tier_config is None:
            return 0

        all_terms = list(terms or []) + [f"site:{a}" for a in (actor_ids or [])]
        if not all_terms:
            return 0

        effective_max = max_results if max_results is not None else tier_config.max_results_per_run
        pages_per_term = math.ceil(effective_max / MAX_RESULTS_PER_PAGE)
        total_queries = len(all_terms) * pages_per_term

        if tier == Tier.MEDIUM:
            return total_queries
        results_estimate = len(all_terms) * effective_max
        return math.ceil(results_estimate * tier_config.estimated_credits_per_1k / 1000)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _acquire_credential(self, tier: Tier) -> dict[str, Any]:
        """Acquire an API credential for *tier* from the credential pool.

        Args:
            tier: Operational tier (determines provider platform).

        Returns:
            Credential dict with ``id`` and ``api_key`` keys.

        Raises:
            NoCredentialAvailableError: When no credential is available.
        """
        if self.credential_pool is None:
            raise NoCredentialAvailableError(platform=self.platform_name, tier=tier.value)

        provider_platform = "serper" if tier == Tier.MEDIUM else "serpapi"
        cred = await self.credential_pool.acquire(platform=provider_platform, tier=tier.value)
        if cred is None:
            raise NoCredentialAvailableError(platform=provider_platform, tier=tier.value)
        return cred

    def _build_http_client(self) -> httpx.AsyncClient:
        """Return an :class:`httpx.AsyncClient` for use as a context manager.

        Returns the injected client if present; otherwise creates a new one
        with a 30-second timeout.
        """
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]
        return httpx.AsyncClient(timeout=30.0)

    async def _collect_term(
        self,
        client: httpx.AsyncClient,
        term: str,
        tier: Tier,
        credential: dict[str, Any],
        max_results: int,
    ) -> list[dict[str, Any]]:
        """Paginate through results for a single search term.

        Args:
            client: Shared HTTP client.
            term: Search query string.
            tier: Operational tier (selects provider).
            credential: Credential dict from the pool.
            max_results: Maximum results to retrieve for this term.

        Returns:
            List of normalized records for the term.

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaAuthError: On HTTP 401 or 403.
            ArenaCollectionError: On other non-2xx responses.
        """
        records: list[dict[str, Any]] = []
        page = 1

        while len(records) < max_results:
            remaining = max_results - len(records)
            num = min(MAX_RESULTS_PER_PAGE, remaining)

            try:
                if tier == Tier.MEDIUM:
                    raw_results = await fetch_serper(
                        client=client,
                        term=term,
                        api_key=credential["api_key"],
                        page=page,
                        num=num,
                        rate_limiter=self.rate_limiter,
                        arena_name=self.arena_name,
                        platform_name=self.platform_name,
                    )
                else:
                    raw_results = await fetch_serpapi(
                        client=client,
                        term=term,
                        api_key=credential["api_key"],
                        start=(page - 1) * MAX_RESULTS_PER_PAGE,
                        num=num,
                        rate_limiter=self.rate_limiter,
                        arena_name=self.arena_name,
                        platform_name=self.platform_name,
                    )
            except (ArenaRateLimitError, ArenaAuthError) as exc:
                if self.credential_pool:
                    await self.credential_pool.report_error(
                        credential_id=credential["id"],
                        error=exc,
                    )
                raise

            if not raw_results:
                break  # No more results — stop paginating.

            for raw_item in raw_results[:remaining]:
                # Mark result with the search term
                raw_item["_search_term"] = term
                records.append(self.normalize(raw_item))

            if len(raw_results) < MAX_RESULTS_PER_PAGE:
                break  # Partial page — no further pages available.

            page += 1

        logger.debug(
            "google_search: term=%r retrieved %d records (tier=%s)",
            term,
            len(records),
            tier.value,
        )
        return records
