"""Wayback Machine CDX API arena collector implementation.

Queries the Internet Archive's Wayback Machine CDX API for historical web
page snapshots of Danish domains. Returns capture metadata from the CDX
index; actual page content retrieval is out of scope for Phase 2.

**Design notes**:

- Returns CDX capture records (metadata only). ``raw_metadata`` contains
  CDX fields plus a ``wayback_url`` field (full archive URL) for future
  content retrieval.
- ``collect_by_terms()`` queries ``*.dk`` captures and filters client-side
  by term substring match against the ``original`` URL field.
- ``collect_by_actors()`` queries captures for specific domains or URL
  prefixes. Actor IDs are domain names (e.g. ``"dr.dk"``).
- Pagination via ``showResumeKey=true`` and ``resumeKey`` parameter.
- Rate limiting: 1 req/sec courtesy throttle. Falls back to
  ``asyncio.sleep(1)`` when no ``RateLimiter`` is injected.
- 503 responses are handled gracefully (WARNING + skip page, no exception).
- Low-level HTTP helpers are in :mod:`._fetcher` to keep this file concise.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from issue_observatory.arenas.base import ArenaCollector, Tier
from issue_observatory.arenas.registry import register
from issue_observatory.arenas.web.wayback._fetcher import (
    extract_domain,
    fetch_cdx_page,
    format_wb_timestamp,
    parse_wb_timestamp,
)
from issue_observatory.arenas.web.wayback.config import (
    WB_CDX_BASE_URL,
    WB_CONCURRENT_FETCH_LIMIT,
    WB_DEFAULT_LIMIT,
    WB_DEFAULT_STATUS_FILTER,
    WB_MAX_CALLS_PER_SECOND,
    WB_PLAYBACK_URL_TEMPLATE,
    WB_RATE_LIMIT_KEY,
    WB_RATE_LIMIT_TIMEOUT,
    WB_RATE_WINDOW_SECONDS,
    WB_TIERS,
)
from issue_observatory.config.tiers import TierConfig
from issue_observatory.core.exceptions import ArenaRateLimitError
from issue_observatory.core.normalizer import Normalizer

logger = logging.getLogger(__name__)


@register
class WaybackCollector(ArenaCollector):
    """Collects web page snapshot metadata via the Wayback Machine CDX API.

    Queries the Internet Archive CDX API for captures of Danish ``.dk`` domains.
    Returns snapshot metadata only; full page content retrieval is out of scope.

    Supported tiers:
    - ``Tier.FREE`` — Wayback Machine CDX API; no credentials required.

    Class Attributes:
        arena_name: ``"web"``
        platform_name: ``"wayback"``
        supported_tiers: ``[Tier.FREE]``

    Args:
        credential_pool: Unused — Wayback Machine is unauthenticated.
        rate_limiter: Optional shared Redis-backed rate limiter.
        http_client: Optional injected :class:`httpx.AsyncClient` for testing.
    """

    arena_name: str = "web"
    platform_name: str = "wayback"
    supported_tiers: list[Tier] = [Tier.FREE]

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
    ) -> list[dict[str, Any]]:
        """Collect Wayback Machine CDX captures for Danish pages matching terms.

        Queries the CDX API for all ``.dk`` domain captures, then filters
        client-side by matching each term against the ``original`` URL.

        Args:
            terms: Search terms matched as URL substrings (case-insensitive).
            tier: Must be ``Tier.FREE``.
            date_from: Earliest capture timestamp (inclusive).
            date_to: Latest capture timestamp (inclusive).
            max_results: Upper bound on returned records.

        Returns:
            List of normalized content record dicts (web page snapshots).

        Raises:
            ValueError: If *tier* is not ``Tier.FREE``.
            ArenaCollectionError: On unrecoverable API errors.
            ArenaRateLimitError: On HTTP 429 from the CDX API.
        """
        self._validate_tier(tier)
        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

        wb_from = format_wb_timestamp(date_from)
        wb_to = format_wb_timestamp(date_to)

        seen_keys: set[str] = set()
        all_records: list[dict[str, Any]] = []

        async with self._build_http_client() as client:
            semaphore = asyncio.Semaphore(WB_CONCURRENT_FETCH_LIMIT)

            for term in terms:
                if len(all_records) >= effective_max:
                    break
                remaining = effective_max - len(all_records)
                term_records = await self._query_term(
                    client, semaphore, term, wb_from, wb_to, remaining, seen_keys
                )
                all_records.extend(term_records)

        logger.info(
            "wayback: collect_by_terms — %d records for %d terms",
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
        """Collect Wayback Machine CDX captures for the specified domains.

        Actor IDs are domain names or URL prefixes (e.g. ``"dr.dk"``).

        Args:
            actor_ids: Domain names or URL prefixes to query.
            tier: Must be ``Tier.FREE``.
            date_from: Earliest capture timestamp (inclusive).
            date_to: Latest capture timestamp (inclusive).
            max_results: Upper bound on returned records.

        Returns:
            List of normalized content record dicts.

        Raises:
            ValueError: If *tier* is not ``Tier.FREE``.
            ArenaCollectionError: On unrecoverable API errors.
            ArenaRateLimitError: On HTTP 429 from the CDX API.
        """
        self._validate_tier(tier)
        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

        wb_from = format_wb_timestamp(date_from)
        wb_to = format_wb_timestamp(date_to)

        seen_keys: set[str] = set()
        all_records: list[dict[str, Any]] = []

        async with self._build_http_client() as client:
            semaphore = asyncio.Semaphore(WB_CONCURRENT_FETCH_LIMIT)

            for actor_id in actor_ids:
                if len(all_records) >= effective_max:
                    break
                remaining = effective_max - len(all_records)
                actor_records = await self._query_url_pattern(
                    client, semaphore, actor_id, "domain",
                    wb_from, wb_to, remaining, seen_keys,
                )
                all_records.extend(actor_records)

        logger.info(
            "wayback: collect_by_actors — %d records for %d actors",
            len(all_records),
            len(actor_ids),
        )
        return all_records

    def get_tier_config(self, tier: Tier) -> TierConfig:
        """Return tier configuration for the Wayback Machine arena.

        Args:
            tier: Requested operational tier.

        Returns:
            :class:`~issue_observatory.config.tiers.TierConfig` for FREE tier.

        Raises:
            ValueError: If *tier* is not in ``supported_tiers``.
        """
        if tier not in WB_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}' for wayback. "
                f"Valid tiers: {list(WB_TIERS.keys())}"
            )
        return WB_TIERS[tier]

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single CDX capture record to the universal schema.

        Expected input fields (CDX API response):
        ``original``, ``timestamp``, ``digest``, ``statuscode``,
        ``mimetype``, ``length``, ``urlkey``.

        Args:
            raw_item: Raw CDX capture record dict.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        original_url: str | None = raw_item.get("original")
        timestamp: str | None = raw_item.get("timestamp")
        digest: str | None = raw_item.get("digest")

        # platform_id: SHA-256 of url + timestamp
        platform_id: str | None = None
        if original_url and timestamp:
            platform_id = hashlib.sha256(
                f"{original_url}{timestamp}".encode("utf-8")
            ).hexdigest()
        elif original_url:
            platform_id = hashlib.sha256(original_url.encode("utf-8")).hexdigest()

        content_hash: str | None = None
        if original_url:
            content_hash = self._normalizer.compute_content_hash(original_url)

        published_at = parse_wb_timestamp(timestamp)
        author_display_name = extract_domain(original_url)

        # Construct full Wayback Machine playback URL for reference
        wayback_url: str | None = None
        if original_url and timestamp:
            wayback_url = WB_PLAYBACK_URL_TEMPLATE.format(
                timestamp=timestamp,
                url=original_url,
            )

        # Language: infer from .dk TLD (CDX API does not provide language)
        language: str | None = None
        if original_url:
            try:
                parsed = urlparse(
                    original_url if "://" in original_url else f"https://{original_url}"
                )
                hostname = parsed.hostname or ""
                if hostname.endswith(".dk") or hostname == "dk":
                    language = "da"
            except Exception:  # noqa: BLE001
                pass

        raw_metadata: dict[str, Any] = {
            "urlkey": raw_item.get("urlkey"),
            "timestamp": timestamp,
            "digest": digest,
            "statuscode": raw_item.get("statuscode"),
            "mimetype": raw_item.get("mimetype"),
            "length": raw_item.get("length"),
            "wayback_url": wayback_url,
        }

        enriched: dict[str, Any] = {
            "id": platform_id,
            "url": original_url,
            "title": None,
            "text_content": None,
            "author": author_display_name,
            "author_display_name": author_display_name,
            "published_at": published_at,
            "language": language,
            "content_type": "web_page_snapshot",
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
        normalized["content_type"] = "web_page_snapshot"
        normalized["content_hash"] = content_hash
        normalized["raw_metadata"] = raw_metadata
        normalized["media_urls"] = []
        normalized["language"] = language

        return normalized

    async def health_check(self) -> dict[str, Any]:
        """Verify Wayback Machine CDX API connectivity with a minimal test query.

        Queries the CDX API for a single capture of ``dr.dk``.

        Returns:
            Dict with ``status`` (``"ok"`` | ``"degraded"`` | ``"down"``),
            ``arena``, ``platform``, ``checked_at``, and optionally ``detail``.
        """
        checked_at = datetime.utcnow().isoformat() + "Z"
        base: dict[str, Any] = {
            "arena": self.arena_name,
            "platform": self.platform_name,
            "checked_at": checked_at,
        }

        params = {
            "url": "dr.dk",
            "output": "json",
            "limit": "1",
            "filter": WB_DEFAULT_STATUS_FILTER,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(WB_CDX_BASE_URL, params=params)
                response.raise_for_status()

                data = response.json()
                if isinstance(data, list) and len(data) >= 1:
                    return {
                        **base,
                        "status": "ok",
                        "captures_returned": max(0, len(data) - 1),
                    }
                return {**base, "status": "ok", "captures_returned": 0}

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 503:
                return {
                    **base,
                    "status": "down",
                    "detail": "Wayback Machine CDX API returned 503 (service overloaded)",
                }
            return {
                **base,
                "status": "down" if exc.response.status_code >= 500 else "degraded",
                "detail": f"HTTP {exc.response.status_code} from Wayback Machine CDX API",
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
                "User-Agent": "IssueObservatory/1.0 (wayback-collector; research use)"
            },
        )

    async def _rate_limit_wait(self) -> None:
        """Wait for a Wayback Machine rate-limit slot.

        Uses the injected ``RateLimiter.wait_for_slot`` when available;
        falls back to a 1-second sleep.
        """
        if self.rate_limiter is not None:
            try:
                await self.rate_limiter.wait_for_slot(
                    key=WB_RATE_LIMIT_KEY,
                    max_calls=WB_MAX_CALLS_PER_SECOND,
                    window_seconds=WB_RATE_WINDOW_SECONDS,
                    timeout=WB_RATE_LIMIT_TIMEOUT,
                )
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "wayback: rate_limiter.wait_for_slot failed (%s) — sleeping 1s", exc
                )
        await asyncio.sleep(1.0)

    async def _query_term(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        term: str,
        wb_from: str | None,
        wb_to: str | None,
        max_records: int,
        seen_keys: set[str],
    ) -> list[dict[str, Any]]:
        """Query CDX for Danish pages where the URL contains the search term.

        Args:
            client: Shared HTTP client.
            semaphore: Concurrency limiter.
            term: Search term matched against ``original`` URL.
            wb_from: WB-formatted start timestamp or ``None``.
            wb_to: WB-formatted end timestamp or ``None``.
            max_records: Maximum records to collect.
            seen_keys: Mutable set of already-seen ``url+timestamp`` keys.

        Returns:
            List of normalized content record dicts.
        """
        term_lower = term.lower()
        records: list[dict[str, Any]] = []
        resume_key: str | None = None

        while len(records) < max_records:
            await self._rate_limit_wait()
            async with semaphore:
                entries, resume_key = await fetch_cdx_page(
                    client=client,
                    url_pattern="*.dk",
                    match_type="domain",
                    wb_from=wb_from,
                    wb_to=wb_to,
                    limit=min(WB_DEFAULT_LIMIT, max_records - len(records)),
                    resume_key=resume_key,
                )

            if not entries:
                break

            for entry in entries:
                if len(records) >= max_records:
                    break
                original: str = entry.get("original", "")
                if term_lower not in original.lower():
                    continue
                dedup_key = f"{original}{entry.get('timestamp', '')}"
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                records.append(self.normalize(entry))

            if not resume_key:
                break

        logger.debug("wayback: term='%s' — %d records", term, len(records))
        return records

    async def _query_url_pattern(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        url_pattern: str,
        match_type: str,
        wb_from: str | None,
        wb_to: str | None,
        max_records: int,
        seen_keys: set[str],
    ) -> list[dict[str, Any]]:
        """Query CDX for all captures matching a URL pattern.

        Args:
            client: Shared HTTP client.
            semaphore: Concurrency limiter.
            url_pattern: Domain or URL prefix to query.
            match_type: CDX ``matchType`` parameter.
            wb_from: WB-formatted start timestamp or ``None``.
            wb_to: WB-formatted end timestamp or ``None``.
            max_records: Maximum records to collect.
            seen_keys: Mutable set of already-seen ``url+timestamp`` keys.

        Returns:
            List of normalized content record dicts.
        """
        records: list[dict[str, Any]] = []
        resume_key: str | None = None

        while len(records) < max_records:
            await self._rate_limit_wait()
            async with semaphore:
                entries, resume_key = await fetch_cdx_page(
                    client=client,
                    url_pattern=url_pattern,
                    match_type=match_type,
                    wb_from=wb_from,
                    wb_to=wb_to,
                    limit=min(WB_DEFAULT_LIMIT, max_records - len(records)),
                    resume_key=resume_key,
                )

            if not entries:
                break

            for entry in entries:
                if len(records) >= max_records:
                    break
                original: str = entry.get("original", "")
                dedup_key = f"{original}{entry.get('timestamp', '')}"
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                records.append(self.normalize(entry))

            if not resume_key:
                break

        logger.debug(
            "wayback: url_pattern='%s' — %d records", url_pattern, len(records)
        )
        return records
