"""URL Scraper arena collector implementation.

Fetches live web pages from a researcher-provided URL list, extracts article
text via ``trafilatura``, and normalizes the results into Universal Content
Records.

Collection modes:

- **collect_by_terms()**: Fetches all URLs in ``extra_urls`` (from
  ``arenas_config["url_scraper"]["custom_urls"]``), then filters pages
  client-side by term occurrence in extracted text and title.  Returns only
  records where at least one search term matches.
- **collect_by_actors()**: Fetches URLs whose domain matches actor platform
  presences (``platform="url_scraper"``).  Returns all content without term
  filtering.

Per-domain rate limiting uses ``asyncio.Semaphore`` instances.  One URL
failure never blocks remaining URLs (per-URL error isolation).

Helpers are split across two sub-modules:
- :mod:`._helpers` — URL normalization, date parsing, term matching.
- :mod:`._normalizer` — UCR normalization (raw record → universal schema).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from issue_observatory.arenas.base import ArenaCollector, TemporalMode, Tier
from issue_observatory.arenas.registry import register
from issue_observatory.arenas.web.url_scraper._helpers import (
    build_searchable_text,
    deduplicate_urls,
    extract_domain,
)
from issue_observatory.arenas.web.url_scraper._normalizer import normalize_raw_record
from issue_observatory.arenas.web.url_scraper.config import (
    CONNECTION_POOL_LIMITS_FREE,
    CONNECTION_POOL_LIMITS_MEDIUM,
    DOMAIN_DELAY_FREE,
    DOMAIN_DELAY_MEDIUM,
    HEALTH_CHECK_URL,
    URL_SCRAPER_TIERS,
)
from issue_observatory.config.tiers import TierConfig
from issue_observatory.core.normalizer import Normalizer
from issue_observatory.scraper.config import DEFAULT_TIMEOUT, USER_AGENT
from issue_observatory.scraper.content_extractor import ExtractedContent, extract_from_html
from issue_observatory.scraper.http_fetcher import FetchResult, fetch_url

logger = logging.getLogger(__name__)


def _make_failure_record(
    source_url: str,
    final_url: str,
    http_status: int | None,
    fetch_error: str | None,
    robots_txt_allowed: bool,
    needs_playwright: bool,
    fetch_duration_ms: int,
) -> dict[str, Any]:
    """Build a failure record for a URL that could not be fetched.

    Args:
        source_url: Original URL before redirects.
        final_url: URL after redirect resolution (may equal source_url).
        http_status: HTTP response status code, or ``None`` on network error.
        fetch_error: Human-readable error description.
        robots_txt_allowed: Whether robots.txt permitted access.
        needs_playwright: Whether a JS shell was detected.
        fetch_duration_ms: Elapsed milliseconds from start to failure.

    Returns:
        Failure record dict with ``_fetch_failed=True``.
    """
    return {
        "source_url": source_url,
        "final_url": final_url,
        "html": None,
        "extracted": None,
        "http_status": http_status,
        "fetch_error": fetch_error,
        "robots_txt_allowed": robots_txt_allowed,
        "needs_playwright": needs_playwright,
        "fetch_duration_ms": fetch_duration_ms,
        "last_modified_header": None,
        "_fetch_failed": True,
        "_search_terms_matched": [],
    }


@register
class UrlScraperCollector(ArenaCollector):
    """Collects web page content from a researcher-provided URL list.

    Fetches live web pages using the existing ``HttpFetcher`` infrastructure,
    extracts article text with ``trafilatura``, and returns normalized
    Universal Content Records.

    Supported tiers:

    - ``Tier.FREE``: Max 100 URLs/run, 1 req/sec per domain, httpx only.
    - ``Tier.MEDIUM``: Max 500 URLs/run, 2 req/sec per domain, Playwright
      fallback for JS-heavy pages (requires ``playwright`` package installed).

    Class Attributes:
        arena_name: ``"web"``
        platform_name: ``"url_scraper"``
        supported_tiers: ``[Tier.FREE, Tier.MEDIUM]``

    Args:
        credential_pool: Unused — no credentials required at any tier.
        rate_limiter: Optional shared Redis-backed rate limiter.  Not used;
            per-domain semaphores provide rate control.
        http_client: Optional injected :class:`httpx.AsyncClient` for testing.
    """

    arena_name: str = "web"
    platform_name: str = "url_scraper"
    supported_tiers: list[Tier] = [Tier.FREE, Tier.MEDIUM]
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
        extra_urls: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all configured URLs and return records matching the search terms.

        Fetches every URL in *extra_urls* (``arenas_config["url_scraper"]
        ["custom_urls"]``), extracts article text, then filters client-side
        by term occurrence in ``text_content`` and ``title``.

        Boolean logic is applied when ``term_groups`` is provided: a page
        matches when at least one AND-group has ALL its terms present
        (groups ORed).

        Args:
            terms: Search terms for case-insensitive substring matching
                (used when ``term_groups`` is ``None``).
            tier: ``Tier.FREE`` or ``Tier.MEDIUM``.
            date_from: Not applied — pages are fetched live without date filter.
            date_to: Not applied for the same reason.
            max_results: Upper bound on returned records.
            term_groups: Optional boolean AND/OR groups.  Pages must satisfy
                at least one AND-group.
            language_filter: Not applied — language detection is post-collection.
            extra_urls: URLs from ``arenas_config["url_scraper"]["custom_urls"]``.
                If ``None`` or empty, returns an empty list.

        Returns:
            List of normalized content record dicts for pages where at least
            one search term matches.

        Raises:
            ValueError: If *tier* is not ``Tier.FREE`` or ``Tier.MEDIUM``.
        """
        self._validate_tier(tier)

        if not extra_urls:
            logger.info("url_scraper: collect_by_terms — no URLs configured, returning empty.")
            return []

        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

        # Build lowercase group structure for client-side boolean matching.
        if term_groups is not None:
            lower_groups: list[list[str]] = [
                [t.lower() for t in grp] for grp in term_groups if grp
            ]
        else:
            lower_groups = [[t.lower()] for t in terms]

        # Deduplicate and cap URLs to tier limit.
        deduped_urls = deduplicate_urls(extra_urls)
        capped_urls = deduped_urls[: tier_config.max_results_per_run]
        if len(deduped_urls) > len(capped_urls):
            logger.info(
                "url_scraper: %d URLs exceeded tier cap of %d — truncating.",
                len(deduped_urls),
                tier_config.max_results_per_run,
            )

        fetched = await self._fetch_all_urls(capped_urls, tier)

        matched_records: list[dict[str, Any]] = []
        for raw_record in fetched:
            if len(matched_records) >= effective_max:
                break
            if raw_record.get("_fetch_failed"):
                continue

            searchable = build_searchable_text(raw_record)
            matched_terms: list[str] = []
            for grp in lower_groups:
                if all(t in searchable for t in grp):
                    matched_terms.extend(grp)
            if not matched_terms:
                continue

            raw_record["_search_terms_matched"] = matched_terms
            normalized = normalize_raw_record(
                self._normalizer, raw_record, self.platform_name,
                self.arena_name, tier, matched_terms,
            )
            matched_records.append(normalized)

        logger.info(
            "url_scraper: collect_by_terms — %d/%d URLs matched terms.",
            len(matched_records),
            len(capped_urls),
        )
        return matched_records

    async def collect_by_actors(
        self,
        actor_ids: list[str],
        tier: Tier,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
        extra_urls: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch URLs associated with actors and return all content.

        For each actor base URL, filters *extra_urls* by domain match.
        If no *extra_urls* match, fetches the actor's base URL directly.
        No term filtering is applied.

        Args:
            actor_ids: Actor base URLs from ``ActorPlatformPresence.
                platform_username`` where ``platform="url_scraper"``.
            tier: ``Tier.FREE`` or ``Tier.MEDIUM``.
            date_from: Not applied.
            date_to: Not applied.
            max_results: Upper bound on returned records.
            extra_urls: Optional URL pool to filter by actor domain.

        Returns:
            List of normalized content record dicts.

        Raises:
            ValueError: If *tier* is not ``Tier.FREE`` or ``Tier.MEDIUM``.
        """
        self._validate_tier(tier)

        if not actor_ids:
            return []

        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

        target_urls: list[str] = []
        for actor_url in actor_ids:
            actor_domain = extract_domain(actor_url)
            matched: list[str] = [
                url for url in (extra_urls or []) if extract_domain(url) == actor_domain
            ]
            target_urls.extend(matched if matched else [actor_url])

        deduped_urls = deduplicate_urls(target_urls)
        capped_urls = deduped_urls[: tier_config.max_results_per_run]

        fetched = await self._fetch_all_urls(capped_urls, tier)

        records: list[dict[str, Any]] = []
        for raw_record in fetched:
            if len(records) >= effective_max:
                break
            if raw_record.get("_fetch_failed"):
                continue
            records.append(
                normalize_raw_record(
                    self._normalizer, raw_record, self.platform_name,
                    self.arena_name, tier, [],
                )
            )

        logger.info(
            "url_scraper: collect_by_actors — %d records from %d URLs.",
            len(records),
            len(capped_urls),
        )
        return records

    def get_tier_config(self, tier: Tier) -> TierConfig:
        """Return tier configuration for the URL Scraper arena.

        Args:
            tier: Requested operational tier.

        Returns:
            :class:`~issue_observatory.config.tiers.TierConfig` for the tier.

        Raises:
            ValueError: If *tier* is not in ``supported_tiers``.
        """
        if tier not in URL_SCRAPER_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}' for url_scraper. "
                f"Valid tiers: {list(URL_SCRAPER_TIERS.keys())}"
            )
        return URL_SCRAPER_TIERS[tier]

    def normalize(self, raw_item: dict[str, Any], tier: Tier = Tier.FREE) -> dict[str, Any]:
        """Normalize a raw URL scraper record to the universal schema.

        Low-level entry point required by the ``ArenaCollector`` interface.
        Within the collector, :func:`~._normalizer.normalize_raw_record` is
        called directly with the correct tier.

        Args:
            raw_item: Raw fetch record dict (see :meth:`_fetch_single_url`).
            tier: Operational tier controlling normalization behaviour.
                Defaults to ``Tier.FREE`` to preserve backwards compatibility
                for callers that do not pass the tier parameter.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        return normalize_raw_record(
            self._normalizer, raw_item, self.platform_name, self.arena_name,
            tier, raw_item.get("_search_terms_matched", []),
        )

    async def health_check(self) -> dict[str, Any]:
        """Verify that the fetch-and-extract pipeline is functional.

        Fetches :data:`~.config.HEALTH_CHECK_URL` (``www.dr.dk``) and verifies
        that both HTTP fetch and text extraction succeed.

        Returns:
            Dict with ``status``, ``arena``, ``platform``, ``checked_at``,
            ``scraper_module``, ``trafilatura``, and optionally ``detail``.
        """
        checked_at = datetime.now(timezone.utc).isoformat() + "Z"
        base: dict[str, Any] = {
            "arena": self.arena_name,
            "platform": self.platform_name,
            "checked_at": checked_at,
        }

        trafilatura_status = "unavailable"
        try:
            import trafilatura  # type: ignore[import-untyped]  # noqa: F401

            trafilatura_status = "available"
        except ImportError:
            pass

        try:
            robots_cache: dict[str, bool] = {}
            async with self._build_http_client(Tier.FREE) as client:
                result = await fetch_url(
                    HEALTH_CHECK_URL,
                    client=client,
                    timeout=DEFAULT_TIMEOUT,
                    respect_robots=True,
                    robots_cache=robots_cache,
                )
        except Exception as exc:  # noqa: BLE001
            return {
                **base, "status": "down",
                "detail": f"HTTP fetch failed: {exc}",
                "scraper_module": "available",
                "trafilatura": trafilatura_status,
            }

        if result.error or result.html is None:
            return {
                **base, "status": "degraded",
                "detail": f"Fetch error: {result.error}",
                "scraper_module": "available",
                "trafilatura": trafilatura_status,
            }

        extracted = extract_from_html(result.html, HEALTH_CHECK_URL)
        if not extracted.text:
            return {
                **base, "status": "degraded",
                "detail": "Extraction returned no text for health check URL.",
                "scraper_module": "available",
                "trafilatura": trafilatura_status,
            }

        return {
            **base, "status": "ok",
            "scraper_module": "available",
            "trafilatura": trafilatura_status,
            "health_check_url": HEALTH_CHECK_URL,
            "extracted_chars": len(extracted.text),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_http_client(self, tier: Tier) -> httpx.AsyncClient:
        """Return an async HTTP client configured for the given tier.

        Args:
            tier: Operational tier controlling connection pool sizing.

        Returns:
            Configured :class:`httpx.AsyncClient` (context manager).
        """
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]

        limits_cfg = (
            CONNECTION_POOL_LIMITS_FREE if tier == Tier.FREE else CONNECTION_POOL_LIMITS_MEDIUM
        )
        limits = httpx.Limits(
            max_connections=limits_cfg["max_connections"],
            max_keepalive_connections=limits_cfg["max_keepalive_connections"],
        )
        return httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            limits=limits,
        )

    async def _fetch_all_urls(self, urls: list[str], tier: Tier) -> list[dict[str, Any]]:
        """Fetch all URLs in parallel, respecting per-domain rate limits.

        Groups URLs by domain and uses ``asyncio.gather()`` across domains
        for maximum throughput while keeping within per-domain limits.

        Args:
            urls: Deduplicated list of URLs to fetch.
            tier: Operational tier (controls per-domain delay).

        Returns:
            List of raw fetch record dicts (one per URL, including failures).
        """
        if not urls:
            return []

        domain_delay = DOMAIN_DELAY_FREE if tier == Tier.FREE else DOMAIN_DELAY_MEDIUM

        # Group URLs by domain for per-domain sequencing.
        domain_groups: dict[str, list[str]] = {}
        for url in urls:
            domain_groups.setdefault(extract_domain(url), []).append(url)

        domain_semaphores: dict[str, asyncio.Semaphore] = {
            d: asyncio.Semaphore(1) for d in domain_groups
        }
        robots_cache: dict[str, bool] = {}

        async with self._build_http_client(tier) as client:
            tasks = [
                self._fetch_domain_urls(
                    domain_urls=domain_urls,
                    semaphore=domain_semaphores[domain],
                    client=client,
                    tier=tier,
                    domain_delay=domain_delay,
                    robots_cache=robots_cache,
                )
                for domain, domain_urls in domain_groups.items()
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_records: list[dict[str, Any]] = []
        for domain, result in zip(domain_groups.keys(), results):
            if isinstance(result, Exception):
                logger.error("url_scraper: error processing domain '%s': %s", domain, result)
                continue
            all_records.extend(result)  # type: ignore[arg-type]

        return all_records

    async def _fetch_domain_urls(
        self,
        domain_urls: list[str],
        semaphore: asyncio.Semaphore,
        client: httpx.AsyncClient,
        tier: Tier,
        domain_delay: float,
        robots_cache: dict[str, bool],
    ) -> list[dict[str, Any]]:
        """Fetch all URLs for a single domain sequentially with a politeness delay.

        Args:
            domain_urls: URLs belonging to this domain.
            semaphore: Per-domain semaphore (ensures sequential access).
            client: Shared HTTP client.
            tier: Operational tier (used for Playwright fallback decision).
            domain_delay: Seconds to sleep between consecutive requests.
            robots_cache: Shared robots.txt cache for this run.

        Returns:
            List of raw fetch record dicts.
        """
        records: list[dict[str, Any]] = []
        for i, url in enumerate(domain_urls):
            async with semaphore:
                record = await self._fetch_single_url(url, client, tier, robots_cache)
                records.append(record)
                if i < len(domain_urls) - 1:
                    await asyncio.sleep(domain_delay)
        return records

    async def _fetch_single_url(
        self,
        url: str,
        client: httpx.AsyncClient,
        tier: Tier,
        robots_cache: dict[str, bool],
    ) -> dict[str, Any]:
        """Fetch and extract content from a single URL with error isolation.

        Any failure (network error, HTTP 4xx/5xx, robots.txt block, extraction
        error) is caught and returned as a failure record.  The caller
        continues processing remaining URLs.

        Args:
            url: Target URL.
            client: Shared HTTP client.
            tier: Operational tier (used for Playwright fallback decision).
            robots_cache: Shared robots.txt cache for this run.

        Returns:
            Raw fetch record dict with ``_fetch_failed`` boolean flag.
        """
        start_time = time.monotonic()

        try:
            fetch_result: FetchResult = await fetch_url(
                url,
                client=client,
                timeout=DEFAULT_TIMEOUT,
                respect_robots=True,
                robots_cache=robots_cache,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("url_scraper: unexpected error fetching '%s': %s", url, exc)
            return _make_failure_record(
                source_url=url, final_url=url,
                http_status=None, fetch_error=f"unexpected error: {exc}",
                robots_txt_allowed=True, needs_playwright=False,
                fetch_duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        fetch_duration_ms = int((time.monotonic() - start_time) * 1000)
        final_url = fetch_result.final_url or url
        robots_txt_allowed = fetch_result.error != "robots.txt disallowed"

        if fetch_result.error is not None or fetch_result.html is None:
            logger.info(
                "url_scraper: fetch failed for '%s': %s (HTTP %s)",
                url, fetch_result.error, fetch_result.status_code,
            )
            return _make_failure_record(
                source_url=url, final_url=final_url,
                http_status=fetch_result.status_code,
                fetch_error=fetch_result.error or "no HTML returned",
                robots_txt_allowed=robots_txt_allowed,
                needs_playwright=fetch_result.needs_playwright,
                fetch_duration_ms=fetch_duration_ms,
            )

        # At MEDIUM tier, retry JS-only shells with Playwright.
        if fetch_result.needs_playwright and tier == Tier.MEDIUM:
            logger.info("url_scraper: JS shell at MEDIUM tier — Playwright retry: '%s'", url)
            pw_start = time.monotonic()
            pw_result = await self._try_playwright_fetch(url)
            if pw_result is not None and pw_result.html is not None:
                fetch_result = pw_result
                final_url = pw_result.final_url or url
                fetch_duration_ms = int((time.monotonic() - pw_start) * 1000)
                logger.info("url_scraper: Playwright succeeded for '%s'.", url)
            else:
                logger.warning("url_scraper: Playwright also failed for '%s'.", url)
        elif fetch_result.needs_playwright:
            logger.info("url_scraper: JS shell at FREE tier (no Playwright): '%s'", url)

        extracted: ExtractedContent | None = None
        if fetch_result.html:
            try:
                extracted = extract_from_html(fetch_result.html, final_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("url_scraper: extraction error for '%s': %s", url, exc)

        return {
            "source_url": url,
            "final_url": final_url,
            "html": fetch_result.html,
            "extracted": extracted,
            "http_status": fetch_result.status_code,
            "fetch_error": fetch_result.error,
            "robots_txt_allowed": robots_txt_allowed,
            "needs_playwright": fetch_result.needs_playwright,
            "fetch_duration_ms": fetch_duration_ms,
            "last_modified_header": None,
            "_fetch_failed": False,
            "_search_terms_matched": [],
        }

    async def _try_playwright_fetch(self, url: str) -> FetchResult | None:
        """Attempt a Playwright fetch, returning ``None`` if unavailable.

        Lazily imports ``playwright_fetcher``.  If Playwright is not installed,
        logs a warning and returns ``None``.

        Args:
            url: Target URL.

        Returns:
            :class:`~issue_observatory.scraper.http_fetcher.FetchResult` on
            success, or ``None`` if unavailable.
        """
        try:
            from issue_observatory.scraper.playwright_fetcher import (  # noqa: PLC0415
                fetch_url_playwright,
            )

            return await fetch_url_playwright(url, timeout=DEFAULT_TIMEOUT)
        except ImportError:
            logger.warning("url_scraper: Playwright not installed for '%s'.", url)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("url_scraper: Playwright error for '%s': %s", url, exc)
            return None
