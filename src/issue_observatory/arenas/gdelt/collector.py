"""GDELT DOC 2.0 API arena collector implementation.

Queries the GDELT DOC 2.0 API for news articles matching search terms,
filtering for Danish-sourced content using ``sourcecountry:DA`` and
``sourcelang:danish`` GDELT filter parameters.

**Design notes**:

- Only ``collect_by_terms()`` is supported.  ``collect_by_actors()`` raises
  ``NotImplementedError`` because GDELT does not track individual authors.
- Rate limiting: max 1 request/second via
  :meth:`~issue_observatory.workers.rate_limiter.RateLimiter.wait_for_slot`.
  When no ``RateLimiter`` is injected, a 1-second ``asyncio.sleep`` is used
  as a fallback so the API is never hammered.
- Two parallel queries are issued per term: one with ``sourcecountry:DA``
  and one with ``sourcelang:danish``.  Results are deduplicated by URL.
- GDELT's DOC API provides a rolling 3-month window; queries beyond that
  return empty results.
- GDELT may return an HTML error page instead of JSON on server errors —
  the collector checks the ``Content-Type`` header and retries on 5xx.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from issue_observatory.arenas.base import ArenaCollector, TemporalMode, Tier
from issue_observatory.arenas.query_builder import format_boolean_query_for_platform
from issue_observatory.arenas.gdelt.config import (
    GDELT_DATETIME_FORMAT,
    GDELT_DOC_API_BASE,
    GDELT_MAX_CALLS_PER_SECOND,
    GDELT_MAX_RECORDS,
    GDELT_RATE_LIMIT_KEY,
    GDELT_RATE_LIMIT_TIMEOUT,
    GDELT_RATE_WINDOW_SECONDS,
    GDELT_SEENDATE_FORMAT,
    GDELT_SORT_ORDER,
    GDELT_TIERS,
    map_country,
    map_language,
)
from issue_observatory.arenas.registry import register
from issue_observatory.config.danish_defaults import GDELT_DANISH_FILTERS
from issue_observatory.config.tiers import TierConfig
from issue_observatory.core.exceptions import ArenaCollectionError, ArenaRateLimitError
from issue_observatory.core.normalizer import Normalizer

logger = logging.getLogger(__name__)


@register
class GDELTCollector(ArenaCollector):
    """Collects news articles via the GDELT DOC 2.0 API.

    Supported tiers:
    - ``Tier.FREE`` — GDELT DOC API; no credentials required.

    Class Attributes:
        arena_name: ``"news_media"``
        platform_name: ``"gdelt"``
        supported_tiers: ``[Tier.FREE]``

    Args:
        credential_pool: Unused — GDELT is unauthenticated.  Pass ``None``.
        rate_limiter: Optional shared Redis-backed rate limiter.  When
            provided, :meth:`wait_for_slot` is used to enforce 1 req/sec.
            When ``None``, a 1-second ``asyncio.sleep`` is used as fallback.
        http_client: Optional injected :class:`httpx.AsyncClient`.
            Inject for testing.  If ``None``, a new client is created
            per collection call.
    """

    arena_name: str = "gdelt"
    platform_name: str = "gdelt"
    supported_tiers: list[Tier] = [Tier.FREE]
    temporal_mode: TemporalMode = TemporalMode.HISTORICAL

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
        """Collect GDELT articles matching the supplied search terms.

        Issues two queries per term (``sourcecountry:DA`` and
        ``sourcelang:danish``) to capture both country-filtered and
        language-filtered results.  Deduplicates by URL.

        When ``term_groups`` is provided, GDELT's native ``AND``/``OR``
        boolean syntax is used: each AND-group becomes ``(term1 AND term2)``
        and groups are ORed together.  One query pair is issued per group.

        Args:
            terms: Search terms (used when ``term_groups`` is ``None``).
            tier: Must be ``Tier.FREE``.
            date_from: Earliest observation date (inclusive).
            date_to: Latest observation date (inclusive).
            max_results: Upper bound on returned records.
            term_groups: Optional boolean AND/OR groups.  GDELT supports
                native ``AND``/``OR`` syntax.
            language_filter: Not used — Danish defaults applied via
                ``sourcecountry``/``sourcelang`` filters.

        Returns:
            List of normalized content record dicts.

        Raises:
            ValueError: If *tier* is not ``Tier.FREE``.
            ArenaCollectionError: On unrecoverable API errors.
            ArenaRateLimitError: On HTTP 429 from the GDELT API.
        """
        self._validate_tier(tier)
        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

        gdelt_from = _format_gdelt_datetime(date_from)
        gdelt_to = _format_gdelt_datetime(date_to)

        seen_urls: set[str] = set()
        all_records: list[dict[str, Any]] = []

        # Build query strings: use GDELT boolean syntax for groups.
        if term_groups is not None:
            query_strings: list[str] = [
                format_boolean_query_for_platform(groups=[grp], platform="gdelt")
                for grp in term_groups
                if grp
            ]
        else:
            query_strings = list(terms)

        async with self._build_http_client() as client:
            for term in query_strings:
                if len(all_records) >= effective_max:
                    break

                remaining = effective_max - len(all_records)

                # Query 1: source country filter (sourcecountry:DA)
                records_country = await self._query_term(
                    client=client,
                    term=term,
                    extra_filter=f"sourcecountry:{GDELT_DANISH_FILTERS['sourcecountry']}",
                    date_from=gdelt_from,
                    date_to=gdelt_to,
                    max_records=min(GDELT_MAX_RECORDS, remaining),
                    seen_urls=seen_urls,
                )
                all_records.extend(records_country)

                # Query 2: source language filter (sourcelang:danish)
                remaining2 = effective_max - len(all_records)
                if remaining2 <= 0:
                    break

                records_lang = await self._query_term(
                    client=client,
                    term=term,
                    extra_filter=f"sourcelang:{GDELT_DANISH_FILTERS['sourcelang']}",
                    date_from=gdelt_from,
                    date_to=gdelt_to,
                    max_records=min(GDELT_MAX_RECORDS, remaining2),
                    seen_urls=seen_urls,
                )
                all_records.extend(records_lang)

        logger.info(
            "gdelt: collect_by_terms — %d records for %d queries",
            len(all_records),
            len(query_strings),
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
        """Not supported for GDELT.

        GDELT does not track individual authors.  To filter by source domain,
        use ``collect_by_terms()`` with a query like ``domain:dr.dk``.

        Args:
            actor_ids: Unused.
            tier: Unused.
            date_from: Unused.
            date_to: Unused.
            max_results: Unused.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            "GDELT does not support actor-based collection — GDELT does not track "
            "individual authors or accounts.  To filter by source domain, use "
            "collect_by_terms() with a domain filter, e.g. 'domain:dr.dk'."
        )

    def get_tier_config(self, tier: Tier) -> TierConfig:
        """Return tier configuration for the GDELT arena.

        Args:
            tier: Requested operational tier.

        Returns:
            :class:`~issue_observatory.config.tiers.TierConfig` for FREE tier.

        Raises:
            ValueError: If *tier* is not in ``supported_tiers``.
        """
        if tier not in GDELT_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}' for gdelt. "
                f"Valid tiers: {list(GDELT_TIERS.keys())}"
            )
        return GDELT_TIERS[tier]

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single GDELT article dict to the universal schema.

        Expected input fields (GDELT ``artlist`` response):
        - ``url``, ``title``, ``seendate``, ``domain``, ``language``,
          ``sourcecountry``, ``socialimage``, ``tone``, ``url_mobile``.

        Args:
            raw_item: Raw article dict from the GDELT API response.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        url: str | None = raw_item.get("url")

        # platform_id: SHA-256 of the URL (GDELT has no native article ID)
        platform_id: str | None = None
        if url:
            platform_id = hashlib.sha256(url.encode("utf-8")).hexdigest()

        # content_hash: SHA-256 of the normalized URL for deduplication
        content_hash: str | None = None
        if url:
            content_hash = self._normalizer.compute_content_hash(url)

        # Language mapping: "Danish" -> "da"
        raw_lang: str | None = raw_item.get("language")
        language: str | None = map_language(raw_lang)

        # Country mapping: "DA" (FIPS) -> "DK" (ISO)
        raw_country: str | None = raw_item.get("sourcecountry")
        iso_country: str | None = map_country(raw_country)

        # Parse seendate: "20260216T123000Z" -> ISO 8601
        published_at: str | None = _parse_seendate(raw_item.get("seendate"))

        # media_urls: socialimage if present
        social_image: str | None = raw_item.get("socialimage")
        media_urls: list[str] = [social_image] if social_image else []

        # Build the enriched raw item for the normalizer
        enriched: dict[str, Any] = {
            "id": platform_id,
            "url": url,
            "title": raw_item.get("title"),
            # GDELT provides no full text — title doubles as text_content
            "text_content": raw_item.get("title"),
            # Use domain as author proxy (per research brief)
            "author": raw_item.get("domain"),
            "published_at": published_at,
            "language": language,
            "content_type": "article",
            "media_urls": media_urls,
            # Raw metadata passthrough
            "domain": raw_item.get("domain"),
            "sourcecountry": iso_country,
            "tone": raw_item.get("tone"),
            "socialimage": social_image,
            "url_mobile": raw_item.get("url_mobile"),
            "gdelt_language_raw": raw_lang,
            "gdelt_sourcecountry_raw": raw_country,
        }

        normalized = self._normalizer.normalize(
            raw_item=enriched,
            platform=self.platform_name,
            arena="news_media",
            collection_tier="free",
        )

        # Override content_hash with URL-based hash
        if content_hash:
            normalized["content_hash"] = content_hash

        return normalized

    async def health_check(self) -> dict[str, Any]:
        """Verify GDELT DOC API connectivity with a minimal test query.

        Queries for ``"denmark"`` with ``maxrecords=1`` and verifies a valid
        JSON response is returned.

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

        params = {
            "query": "denmark",
            "mode": "artlist",
            "format": "json",
            "maxrecords": "1",
            "sort": GDELT_SORT_ORDER,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(GDELT_DOC_API_BASE, params=params)
                response.raise_for_status()

                content_type = response.headers.get("content-type", "")
                if "json" not in content_type:
                    return {
                        **base,
                        "status": "degraded",
                        "detail": f"Non-JSON response (content-type: {content_type})",
                    }

                data = response.json()
                articles = data.get("articles") or []
                return {
                    **base,
                    "status": "ok",
                    "articles_returned": len(articles),
                }

        except httpx.HTTPStatusError as exc:
            return {
                **base,
                "status": "down" if exc.response.status_code >= 500 else "degraded",
                "detail": f"HTTP {exc.response.status_code} from GDELT API",
            }
        except httpx.RequestError as exc:
            return {**base, "status": "down", "detail": f"Connection error: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {**base, "status": "down", "detail": f"Unexpected error: {exc}"}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_http_client(self) -> httpx.AsyncClient:
        """Return an async HTTP client for use as a context manager.

        Returns the injected client if present; otherwise creates a new one
        with a 30-second timeout and a descriptive User-Agent.
        """
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]
        return httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "IssueObservatory/1.0 (gdelt-collector; research use)"
            },
        )

    async def _rate_limit_wait(self) -> None:
        """Wait for a GDELT rate-limit slot.

        Uses the injected ``RateLimiter.wait_for_slot`` when available;
        falls back to a simple 1-second sleep to avoid hammering the API
        when Redis is not configured.
        """
        if self.rate_limiter is not None:
            try:
                await self.rate_limiter.wait_for_slot(
                    key=GDELT_RATE_LIMIT_KEY,
                    max_calls=GDELT_MAX_CALLS_PER_SECOND,
                    window_seconds=GDELT_RATE_WINDOW_SECONDS,
                    timeout=GDELT_RATE_LIMIT_TIMEOUT,
                )
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "gdelt: rate_limiter.wait_for_slot failed (%s) — falling back to sleep(1)",
                    exc,
                )

        import asyncio  # noqa: PLC0415
        await asyncio.sleep(1.0)

    async def _query_term(
        self,
        client: httpx.AsyncClient,
        term: str,
        extra_filter: str,
        date_from: str | None,
        date_to: str | None,
        max_records: int,
        seen_urls: set[str],
    ) -> list[dict[str, Any]]:
        """Issue a single GDELT DOC API query and return normalized records.

        Args:
            client: Shared HTTP client.
            term: Search term (GDELT Boolean query syntax supported).
            extra_filter: Additional GDELT filter appended to the query
                (e.g. ``"sourcecountry:DA"`` or ``"sourcelang:danish"``).
            date_from: GDELT-formatted start datetime or ``None``.
            date_to: GDELT-formatted end datetime or ``None``.
            max_records: Maximum records to fetch (1–250).
            seen_urls: Mutable set of already-seen URLs for deduplication.

        Returns:
            List of normalized content record dicts (new URLs only).

        Raises:
            ArenaCollectionError: On non-retryable API errors.
            ArenaRateLimitError: On HTTP 429.
        """
        await self._rate_limit_wait()

        query = f"{term} {extra_filter}".strip()
        params: dict[str, str] = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": str(min(max_records, GDELT_MAX_RECORDS)),
            "sort": GDELT_SORT_ORDER,
        }
        if date_from:
            params["startdatetime"] = date_from
        if date_to:
            params["enddatetime"] = date_to

        try:
            response = await client.get(GDELT_DOC_API_BASE, params=params)
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"gdelt: request error for term='{term}': {exc}",
                arena="news_media",
                platform=self.platform_name,
            ) from exc

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", 60))
            raise ArenaRateLimitError(
                f"gdelt: HTTP 429 for term='{term}'",
                retry_after=retry_after,
                arena="news_media",
                platform=self.platform_name,
            )

        if response.status_code >= 500:
            raise ArenaCollectionError(
                f"gdelt: server error HTTP {response.status_code} for term='{term}'",
                arena="news_media",
                platform=self.platform_name,
            )

        if response.status_code >= 400:
            logger.warning(
                "gdelt: HTTP %d for term='%s' filter='%s' — skipping.",
                response.status_code,
                term,
                extra_filter,
            )
            return []

        # GDELT sometimes returns HTML on errors — check content-type
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type:
            logger.warning(
                "gdelt: non-JSON response for term='%s' (content-type=%s) — skipping.",
                term,
                content_type,
            )
            return []

        try:
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "gdelt: JSON parse error for term='%s': %s — skipping.", term, exc
            )
            return []

        articles = data.get("articles") or []
        records: list[dict[str, Any]] = []

        for article in articles:
            url = article.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            records.append(self.normalize(article))

        logger.debug(
            "gdelt: term='%s' filter='%s' — %d articles (%d new)",
            term,
            extra_filter,
            len(articles),
            len(records),
        )
        return records


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _format_gdelt_datetime(value: datetime | str | None) -> str | None:
    """Format a datetime value as a GDELT API datetime string.

    GDELT format: ``YYYYMMDDHHMMSS`` (e.g. ``"20260216120000"``).

    Args:
        value: Datetime object, ISO 8601 string, or ``None``.

    Returns:
        GDELT-formatted datetime string or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime(GDELT_DATETIME_FORMAT)
    # Try to parse ISO 8601 string
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.strftime(GDELT_DATETIME_FORMAT)
        except ValueError:
            continue
    logger.warning("gdelt: could not format datetime '%s' for GDELT API.", value)
    return None


def _parse_seendate(seendate: str | None) -> str | None:
    """Parse a GDELT ``seendate`` string to an ISO 8601 string.

    GDELT ``seendate`` format: ``YYYYMMDDTHHMMSSZ`` (e.g.
    ``"20260216T123000Z"``).

    Args:
        seendate: Raw GDELT ``seendate`` field value.

    Returns:
        ISO 8601 datetime string with UTC timezone, or ``None``.
    """
    if not seendate:
        return None
    try:
        dt = datetime.strptime(seendate, GDELT_SEENDATE_FORMAT)
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        logger.debug("gdelt: could not parse seendate '%s'", seendate)
        return None
