"""Common Crawl CC Index API arena collector implementation.

Queries the Common Crawl Index API for web page index entries matching
search terms or actor domains, filtering for Danish ``.dk`` content.

**Design notes**:

- Returns CC Index entries (metadata only) — WARC record retrieval is out of
  scope for Phase 2. The ``raw_metadata`` field contains WARC location
  references (``filename``, ``offset``, ``length``) for future retrieval.
- ``collect_by_terms()`` queries the CC Index for ``*.dk`` domain captures
  and filters results client-side by matching terms against the URL path.
- ``collect_by_actors()`` queries by domain; actor IDs must be registered
  domain names (e.g. ``"dr.dk"``).
- Rate limiting: 1 req/sec courtesy throttle via
  :meth:`~issue_observatory.workers.rate_limiter.RateLimiter.wait_for_slot`.
  Falls back to ``asyncio.sleep(1)`` when no ``RateLimiter`` is injected.
- Low-level HTTP helpers are in :mod:`._fetcher` to keep this file concise.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Any

import httpx

from issue_observatory.arenas.base import ArenaCollector, TemporalMode, Tier
from issue_observatory.arenas.query_builder import format_boolean_query_for_platform
from issue_observatory.arenas.registry import register
from issue_observatory.arenas.web.common_crawl._fetcher import (
    build_page_params,
    extract_domain,
    fetch_index_page,
    format_cc_timestamp,
    map_cc_language,
    parse_cc_timestamp,
)
from issue_observatory.arenas.web.common_crawl.config import (
    CC_COLLINFO_URL,
    CC_CONCURRENT_FETCH_LIMIT,
    CC_DANISH_TLD_FILTER,
    CC_DEFAULT_INDEX,
    CC_DEFAULT_MATCH_TYPE,
    CC_DEFAULT_OUTPUT,
    CC_MAX_CALLS_PER_SECOND,
    CC_MAX_RECORDS_PER_PAGE,
    CC_RATE_LIMIT_KEY,
    CC_RATE_LIMIT_TIMEOUT,
    CC_RATE_WINDOW_SECONDS,
    CC_TIERS,
)
from issue_observatory.config.tiers import TierConfig
from issue_observatory.core.exceptions import ArenaRateLimitError
from issue_observatory.core.normalizer import Normalizer

logger = logging.getLogger(__name__)


@register
class CommonCrawlCollector(ArenaCollector):
    """Collects web page index entries via the Common Crawl Index API.

    Queries the CC Index API for captures of Danish ``.dk`` domains.
    Returns index metadata only; full page content requires WARC retrieval
    which is out of scope.

    Supported tiers:
    - ``Tier.FREE`` — CC Index API; no credentials required.

    Class Attributes:
        arena_name: ``"web"``
        platform_name: ``"common_crawl"``
        supported_tiers: ``[Tier.FREE]``

    Args:
        credential_pool: Unused — Common Crawl is unauthenticated.
        rate_limiter: Optional shared Redis-backed rate limiter.
        http_client: Optional injected :class:`httpx.AsyncClient` for testing.
        cc_index: Common Crawl index identifier to query. Defaults to
            ``CC_DEFAULT_INDEX``.
    """

    arena_name: str = "web"
    platform_name: str = "common_crawl"
    supported_tiers: list[Tier] = [Tier.FREE]
    temporal_mode: TemporalMode = TemporalMode.HISTORICAL

    def __init__(
        self,
        credential_pool: Any = None,
        rate_limiter: Any = None,
        http_client: httpx.AsyncClient | None = None,
        cc_index: str = CC_DEFAULT_INDEX,
    ) -> None:
        super().__init__(credential_pool=credential_pool, rate_limiter=rate_limiter)
        self._http_client = http_client
        self._normalizer = Normalizer()
        self._cc_index = cc_index

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
        """Collect CC index entries for Danish pages matching the search terms.

        Queries the CC Index for all ``.dk`` domain captures, then filters
        results client-side by matching each term against the URL.

        No native boolean support.  When ``term_groups`` is provided each
        AND-group is searched as a separate space-joined query.

        Args:
            terms: Search terms matched as URL substrings (used when
                ``term_groups`` is ``None``).
            tier: Must be ``Tier.FREE``.
            date_from: Earliest capture timestamp (inclusive).
            date_to: Latest capture timestamp (inclusive).
            max_results: Upper bound on returned records.
            term_groups: Optional boolean AND/OR groups.
            language_filter: Not used — Common Crawl has no language filter.

        Returns:
            List of normalized content record dicts (web index entries).

        Raises:
            ValueError: If *tier* is not ``Tier.FREE``.
            ArenaCollectionError: On unrecoverable API errors.
            ArenaRateLimitError: On HTTP 429 from the CC Index API.
        """
        self._validate_tier(tier)
        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

        cc_from = format_cc_timestamp(date_from)
        cc_to = format_cc_timestamp(date_to)

        # Build effective terms: one per AND-group (space-joined) or plain list.
        if term_groups is not None:
            effective_terms: list[str] = [
                format_boolean_query_for_platform(groups=[grp], platform="bluesky")
                for grp in term_groups
                if grp
            ]
        else:
            effective_terms = list(terms)

        seen_keys: set[str] = set()
        all_records: list[dict[str, Any]] = []

        async with self._build_http_client() as client:
            semaphore = asyncio.Semaphore(CC_CONCURRENT_FETCH_LIMIT)

            for term in effective_terms:
                if len(all_records) >= effective_max:
                    break
                remaining = effective_max - len(all_records)
                term_records = await self._query_term(
                    client, semaphore, term, cc_from, cc_to, remaining, seen_keys
                )
                all_records.extend(term_records)

        logger.info(
            "common_crawl: collect_by_terms — %d records for %d queries",
            len(all_records),
            len(terms),
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
        """Collect CC index entries for domains belonging to the specified actors.

        Actor IDs must be registered domain names (e.g. ``"dr.dk"``).

        Args:
            actor_ids: Domain names to query.
            tier: Must be ``Tier.FREE``.
            date_from: Earliest capture timestamp (inclusive).
            date_to: Latest capture timestamp (inclusive).
            max_results: Upper bound on returned records.

        Returns:
            List of normalized content record dicts.

        Raises:
            ValueError: If *tier* is not ``Tier.FREE``.
            ArenaCollectionError: On unrecoverable API errors.
            ArenaRateLimitError: On HTTP 429 from the CC Index API.
        """
        self._validate_tier(tier)
        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

        cc_from = format_cc_timestamp(date_from)
        cc_to = format_cc_timestamp(date_to)

        seen_keys: set[str] = set()
        all_records: list[dict[str, Any]] = []

        async with self._build_http_client() as client:
            semaphore = asyncio.Semaphore(CC_CONCURRENT_FETCH_LIMIT)

            for domain in actor_ids:
                if len(all_records) >= effective_max:
                    break
                remaining = effective_max - len(all_records)
                domain_records = await self._query_domain(
                    client, semaphore, domain, cc_from, cc_to, remaining, seen_keys
                )
                all_records.extend(domain_records)

        logger.info(
            "common_crawl: collect_by_actors — %d records for %d domains",
            len(all_records),
            len(actor_ids),
        )
        return all_records

    def get_tier_config(self, tier: Tier) -> TierConfig:
        """Return tier configuration for the Common Crawl arena.

        Args:
            tier: Requested operational tier.

        Returns:
            :class:`~issue_observatory.config.tiers.TierConfig` for FREE tier.

        Raises:
            ValueError: If *tier* is not in ``supported_tiers``.
        """
        if tier not in CC_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}' for common_crawl. "
                f"Valid tiers: {list(CC_TIERS.keys())}"
            )
        return CC_TIERS[tier]

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single CC Index entry to the universal schema.

        Expected input fields (CC Index API response):
        ``urlkey``, ``timestamp``, ``url``, ``mime``, ``mime-detected``,
        ``status``, ``digest``, ``length``, ``offset``, ``filename``,
        ``languages``, ``charset``.

        Args:
            raw_item: Raw CC Index entry dict.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        url: str | None = raw_item.get("url")
        timestamp: str | None = raw_item.get("timestamp")
        digest: str | None = raw_item.get("digest")

        # platform_id: digest from index, or SHA-256(url+timestamp)
        platform_id: str | None = None
        if digest:
            platform_id = digest
        elif url and timestamp:
            platform_id = hashlib.sha256(f"{url}{timestamp}".encode()).hexdigest()
        elif url:
            platform_id = hashlib.sha256(url.encode()).hexdigest()

        content_hash: str | None = None
        if url:
            content_hash = self._normalizer.compute_content_hash(url)

        published_at = parse_cc_timestamp(timestamp)
        language = map_cc_language(raw_item.get("languages"))
        author_display_name = extract_domain(url)

        raw_metadata: dict[str, Any] = {
            "urlkey": raw_item.get("urlkey"),
            "timestamp": timestamp,
            "mime": raw_item.get("mime"),
            "mime_detected": raw_item.get("mime-detected"),
            "status": raw_item.get("status"),
            "content_digest": digest,
            "warc_filename": raw_item.get("filename"),
            "warc_record_offset": raw_item.get("offset"),
            "warc_record_length": raw_item.get("length"),
            "charset": raw_item.get("charset"),
            "languages": raw_item.get("languages"),
            "crawl": self._cc_index,
        }

        enriched: dict[str, Any] = {
            "id": platform_id,
            "url": url,
            "title": None,
            "text_content": None,
            "author": author_display_name,
            "author_display_name": author_display_name,
            "published_at": published_at,
            "language": language,
            "content_type": "web_index_entry",
            "media_urls": [],
            **raw_metadata,
        }

        normalized = self._normalizer.normalize(
            raw_item=enriched,
            platform=self.platform_name,
            arena=self.arena_name,
            collection_tier="free",
        )

        normalized["platform_id"] = platform_id
        normalized["content_type"] = "web_index_entry"
        normalized["content_hash"] = content_hash
        normalized["raw_metadata"] = raw_metadata
        normalized["media_urls"] = []

        return normalized

    async def health_check(self) -> dict[str, Any]:
        """Verify Common Crawl Index API connectivity via the collinfo endpoint.

        Fetches ``https://index.commoncrawl.org/collinfo.json`` and verifies
        that a non-empty list of crawl indexes is returned.

        Returns:
            Dict with ``status``, ``arena``, ``platform``, ``checked_at``,
            and optionally ``latest_index`` and ``detail``.
        """
        checked_at = datetime.utcnow().isoformat() + "Z"
        base: dict[str, Any] = {
            "arena": self.arena_name,
            "platform": self.platform_name,
            "checked_at": checked_at,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(CC_COLLINFO_URL)
                response.raise_for_status()

                data = response.json()
                if not isinstance(data, list) or len(data) == 0:
                    return {
                        **base,
                        "status": "degraded",
                        "detail": "collinfo.json returned empty or non-list response",
                    }

                latest = data[0].get("id", "unknown")
                return {
                    **base,
                    "status": "ok",
                    "latest_index": latest,
                    "indexes_available": len(data),
                }

        except httpx.HTTPStatusError as exc:
            return {
                **base,
                "status": "down" if exc.response.status_code >= 500 else "degraded",
                "detail": f"HTTP {exc.response.status_code} from CC collinfo endpoint",
            }
        except httpx.RequestError as exc:
            return {**base, "status": "down", "detail": f"Connection error: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {**base, "status": "down", "detail": f"Unexpected error: {exc}"}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_http_client(self) -> httpx.AsyncClient:
        """Return an async HTTP client for use as a context manager."""
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]
        return httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "IssueObservatory/1.0 (common-crawl-collector; research use)"
            },
        )

    async def _rate_limit_wait(self) -> None:
        """Wait for a Common Crawl rate-limit slot.

        Uses the injected ``RateLimiter.wait_for_slot`` when available;
        falls back to a 1-second sleep.
        """
        if self.rate_limiter is not None:
            try:
                await self.rate_limiter.wait_for_slot(
                    key=CC_RATE_LIMIT_KEY,
                    max_calls=CC_MAX_CALLS_PER_SECOND,
                    window_seconds=CC_RATE_WINDOW_SECONDS,
                    timeout=CC_RATE_LIMIT_TIMEOUT,
                )
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "common_crawl: rate_limiter.wait_for_slot failed (%s) — sleeping 1s", exc
                )
        await asyncio.sleep(1.0)

    async def _query_term(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        term: str,
        cc_from: str | None,
        cc_to: str | None,
        max_records: int,
        seen_keys: set[str],
    ) -> list[dict[str, Any]]:
        """Query CC Index for Danish pages where the URL contains the term.

        Args:
            client: Shared HTTP client.
            semaphore: Concurrency limiter.
            term: Search term matched against URL (case-insensitive substring).
            cc_from: CC-formatted start timestamp or ``None``.
            cc_to: CC-formatted end timestamp or ``None``.
            max_records: Maximum records to collect.
            seen_keys: Mutable set of already-seen ``urlkey`` values.

        Returns:
            List of normalized content record dicts.
        """
        term_lower = term.lower()
        records: list[dict[str, Any]] = []
        offset = 0

        while len(records) < max_records:
            params = build_page_params(
                url_pattern=f"*.{CC_DANISH_TLD_FILTER}",
                match_type=CC_DEFAULT_MATCH_TYPE,
                output=CC_DEFAULT_OUTPUT,
                status_filter="=status:200",
                limit=CC_MAX_RECORDS_PER_PAGE,
                cc_from=cc_from,
                cc_to=cc_to,
                offset=offset,
            )
            await self._rate_limit_wait()
            async with semaphore:
                page_entries = await fetch_index_page(client, self._cc_index, params)

            if not page_entries:
                break

            for entry in page_entries:
                if len(records) >= max_records:
                    break
                if term_lower not in entry.get("url", "").lower():
                    continue
                urlkey: str = entry.get("urlkey", entry.get("url", ""))
                if urlkey in seen_keys:
                    continue
                seen_keys.add(urlkey)
                records.append(self.normalize(entry))

            if len(page_entries) < CC_MAX_RECORDS_PER_PAGE:
                break
            offset += len(page_entries)

        logger.debug("common_crawl: term='%s' — %d records", term, len(records))
        return records

    async def _query_domain(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        domain: str,
        cc_from: str | None,
        cc_to: str | None,
        max_records: int,
        seen_keys: set[str],
    ) -> list[dict[str, Any]]:
        """Query CC Index for all captures of a specific domain.

        Args:
            client: Shared HTTP client.
            semaphore: Concurrency limiter.
            domain: Registered domain name (e.g. ``"dr.dk"``).
            cc_from: CC-formatted start timestamp or ``None``.
            cc_to: CC-formatted end timestamp or ``None``.
            max_records: Maximum records to collect.
            seen_keys: Mutable set of already-seen ``urlkey`` values.

        Returns:
            List of normalized content record dicts.
        """
        records: list[dict[str, Any]] = []
        offset = 0

        while len(records) < max_records:
            params = build_page_params(
                url_pattern=domain,
                match_type=CC_DEFAULT_MATCH_TYPE,
                output=CC_DEFAULT_OUTPUT,
                status_filter="=status:200",
                limit=CC_MAX_RECORDS_PER_PAGE,
                cc_from=cc_from,
                cc_to=cc_to,
                offset=offset,
            )
            await self._rate_limit_wait()
            async with semaphore:
                page_entries = await fetch_index_page(client, self._cc_index, params)

            if not page_entries:
                break

            for entry in page_entries:
                if len(records) >= max_records:
                    break
                urlkey: str = entry.get("urlkey", entry.get("url", ""))
                if urlkey in seen_keys:
                    continue
                seen_keys.add(urlkey)
                records.append(self.normalize(entry))

            if len(page_entries) < CC_MAX_RECORDS_PER_PAGE:
                break
            offset += len(page_entries)

        logger.debug("common_crawl: domain='%s' — %d records", domain, len(records))
        return records
