"""Via Ritzau arena collector implementation.

Collects press releases from Via Ritzau's free, unauthenticated REST API v2.
Via Ritzau is operated by Ritzaus Bureau A/S, Denmark's national news agency.

Two collection modes are supported:

- :meth:`RitzauViaCollector.collect_by_terms` — full-text keyword search
  across release titles and bodies with ``language=da`` filter.
- :meth:`RitzauViaCollector.collect_by_actors` — publisher-based collection
  using Via Ritzau publisher IDs.

No authentication or credentials are required. The API is fully public.
HTML body content is stripped to plain text; original HTML is preserved in
``raw_metadata``.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from issue_observatory.arenas.base import ArenaCollector, TemporalMode, Tier
from issue_observatory.arenas.query_builder import format_boolean_query_for_platform
from issue_observatory.arenas.registry import register
from issue_observatory.arenas.ritzau_via.config import (
    RITZAU_DEFAULT_LANGUAGE,
    RITZAU_PAGE_SIZE,
    RITZAU_PUBLISHERS_ENDPOINT,
    RITZAU_RATE_LIMIT_MAX_CALLS,
    RITZAU_RATE_LIMIT_WINDOW_SECONDS,
    RITZAU_RELEASES_ENDPOINT,
    RITZAU_TIERS,
)
from issue_observatory.config.tiers import TierConfig
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
)
from issue_observatory.core.normalizer import Normalizer

logger = logging.getLogger(__name__)

_RATE_LIMIT_KEY_PREFIX: str = "ratelimit:ritzau_via:public"


@register
class RitzauViaCollector(ArenaCollector):
    """Collects press releases from the Via Ritzau REST API v2.

    No credentials required — the API is fully public and unauthenticated.
    Pass ``credential_pool=None`` (default) in all contexts.

    Class Attributes:
        arena_name: ``"news_media"``
        platform_name: ``"ritzau_via"``
        supported_tiers: ``[Tier.FREE]``

    Args:
        credential_pool: Accepted for interface consistency but ignored.
        rate_limiter: Optional Redis-backed rate limiter.
        http_client: Optional injected ``httpx.AsyncClient`` for testing.
    """

    arena_name: str = "news_media"
    platform_name: str = "ritzau_via"
    supported_tiers: list[Tier] = [Tier.FREE]
    temporal_mode: TemporalMode = TemporalMode.FORWARD_ONLY

    def __init__(
        self,
        credential_pool: Any = None,
        rate_limiter: Any = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(credential_pool=None, rate_limiter=rate_limiter)
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
        """Collect Via Ritzau press releases matching one or more search terms.

        Uses ``GET /json/v2/releases?query={term}&language=da`` with
        offset-based pagination. Applies ``language=da`` by default.

        Via Ritzau does not support boolean syntax.  When ``term_groups``
        is provided each AND-group is searched as a separate space-joined
        query.

        Args:
            terms: Keywords (used when ``term_groups`` is ``None``).
            tier: Operational tier. Only FREE is valid.
            date_from: Earliest publication date (inclusive).
            date_to: Latest publication date (inclusive).
            max_results: Cap on total records. Defaults to tier max.
            term_groups: Optional boolean AND/OR groups.  Each group issues
                a separate query with terms space-joined.
            language_filter: Optional language codes.  The first code
                overrides the default ``language=da`` parameter.

        Returns:
            List of normalized content record dicts.

        Raises:
            ArenaRateLimitError: On HTTP 429 (unlikely but handled).
            ArenaCollectionError: On other unrecoverable errors.
        """
        if tier != Tier.FREE:
            logger.warning(
                "ritzau_via: tier=%s requested but only FREE exists. "
                "Proceeding with FREE tier.",
                tier.value,
            )

        tier_config = self.get_tier_config(Tier.FREE)
        effective_max = (
            max_results
            if max_results is not None
            else (tier_config.max_results_per_run if tier_config else 10_000)
        )

        date_from_str = _to_date_str(date_from)
        date_to_str = _to_date_str(date_to)
        lang_code = (language_filter[0] if language_filter else None) or RITZAU_DEFAULT_LANGUAGE

        # Build effective terms list from groups or plain terms.
        if term_groups is not None:
            effective_terms: list[str] = [
                format_boolean_query_for_platform(groups=[grp], platform="bluesky")
                for grp in term_groups
                if grp
            ]
        else:
            effective_terms = list(terms)

        all_records: list[dict[str, Any]] = []

        async with self._build_http_client() as client:
            for term in effective_terms:
                if len(all_records) >= effective_max:
                    break
                remaining = effective_max - len(all_records)
                params: dict[str, Any] = {
                    "query": term,
                    "language": lang_code,
                    "limit": RITZAU_PAGE_SIZE,
                }
                if date_from_str:
                    params["fromDate"] = date_from_str
                if date_to_str:
                    params["toDate"] = date_to_str

                records = await self._paginate_releases(
                    client=client,
                    params=params,
                    max_results=remaining,
                )
                all_records.extend(records)

        logger.info(
            "ritzau_via: collected %d press releases for %d queries",
            len(all_records),
            len(effective_terms),
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
        """Collect Via Ritzau press releases from specific publishers.

        Actor IDs are Via Ritzau publisher IDs (integers stored as strings).

        Args:
            actor_ids: Via Ritzau publisher IDs.
            tier: Operational tier. Only FREE is valid.
            date_from: Earliest publication date (inclusive).
            date_to: Latest publication date (inclusive).
            max_results: Cap on total records.

        Returns:
            List of normalized content record dicts.

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaCollectionError: On other unrecoverable errors.
        """
        if tier != Tier.FREE:
            logger.warning(
                "ritzau_via: tier=%s requested but only FREE exists. "
                "Proceeding with FREE tier.",
                tier.value,
            )

        tier_config = self.get_tier_config(Tier.FREE)
        effective_max = (
            max_results
            if max_results is not None
            else (tier_config.max_results_per_run if tier_config else 10_000)
        )

        date_from_str = _to_date_str(date_from)
        date_to_str = _to_date_str(date_to)

        all_records: list[dict[str, Any]] = []

        async with self._build_http_client() as client:
            for publisher_id in actor_ids:
                if len(all_records) >= effective_max:
                    break
                remaining = effective_max - len(all_records)
                params: dict[str, Any] = {
                    "publisherId": publisher_id,
                    "language": RITZAU_DEFAULT_LANGUAGE,
                    "limit": RITZAU_PAGE_SIZE,
                }
                if date_from_str:
                    params["fromDate"] = date_from_str
                if date_to_str:
                    params["toDate"] = date_to_str

                records = await self._paginate_releases(
                    client=client,
                    params=params,
                    max_results=remaining,
                )
                all_records.extend(records)

        logger.info(
            "ritzau_via: collected %d press releases for %d publishers",
            len(all_records),
            len(actor_ids),
        )
        return all_records

    def get_tier_config(self, tier: Tier) -> TierConfig | None:
        """Return the tier configuration for this arena.

        Args:
            tier: The requested operational tier.

        Returns:
            ``TierConfig`` for FREE. ``None`` for MEDIUM and PREMIUM.
        """
        return RITZAU_TIERS.get(tier)

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single Via Ritzau press release to the universal schema.

        Strips HTML tags from the ``body`` field for ``text_content`` while
        preserving the original HTML in ``raw_metadata.body_html``.

        Args:
            raw_item: Raw dict from the Via Ritzau API.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        release_id = str(raw_item.get("id", ""))
        headline = raw_item.get("headline", "") or ""
        body_html = raw_item.get("body", "") or ""
        text_content = _strip_html(body_html)

        publisher = raw_item.get("publisher") or {}
        publisher_id = str(publisher.get("id", "")) if publisher else None
        publisher_name = publisher.get("name") or None

        url = raw_item.get("url") or None
        language = raw_item.get("language") or RITZAU_DEFAULT_LANGUAGE
        published_at = raw_item.get("publishedAt") or None

        # Extract image URLs from the images array.
        images = raw_item.get("images") or []
        media_urls = [img["url"] for img in images if isinstance(img, dict) and img.get("url")]

        flat: dict[str, Any] = {
            "id": release_id,
            "platform_id": release_id,
            "content_type": "press_release",
            "title": headline.strip() or None,
            "text_content": text_content or None,
            "url": url,
            "language": language,
            "published_at": published_at,
            "author_platform_id": publisher_id,
            "author_display_name": publisher_name,
            # No engagement metrics for press releases.
            # Preserve full raw item for raw_metadata (Normalizer stores raw_item).
            # Additional structured metadata fields:
            "sub_headline": raw_item.get("subHeadline"),
            "summary": raw_item.get("summary"),
            "body_html": body_html,
            "channels": raw_item.get("channels"),
            "attachments": raw_item.get("attachments"),
            "contacts": raw_item.get("contacts"),
            "updated_at": raw_item.get("updatedAt"),
            "media_urls": media_urls,
        }

        normalized = self._normalizer.normalize(
            raw_item=flat,
            platform=self.platform_name,
            arena=self.arena_name,
            collection_tier="free",
        )
        normalized["platform_id"] = release_id
        if media_urls:
            normalized["media_urls"] = media_urls
        return normalized

    async def health_check(self) -> dict[str, Any]:
        """Verify that the Via Ritzau API is reachable.

        Sends a minimal request with ``limit=1&language=da`` and verifies
        a valid JSON response is returned.

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
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    RITZAU_RELEASES_ENDPOINT,
                    params={"limit": 1, "language": RITZAU_DEFAULT_LANGUAGE},
                )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, (list, dict)):
                    return {
                        **base,
                        "status": "degraded",
                        "detail": "Unexpected response format.",
                    }
                return {**base, "status": "ok"}
        except httpx.HTTPStatusError as exc:
            return {
                **base,
                "status": "degraded",
                "detail": f"HTTP {exc.response.status_code} from Via Ritzau API",
            }
        except httpx.RequestError as exc:
            return {**base, "status": "down", "detail": f"Connection error: {exc}"}

    async def fetch_publishers(self) -> list[dict[str, Any]]:
        """Fetch the full list of publishers from the Via Ritzau API.

        Useful for discovering publisher IDs for actor-based collection.

        Returns:
            List of publisher dicts with ``id`` and ``name`` fields.
        """
        async with self._build_http_client() as client:
            try:
                await self._wait_for_rate_limit()
                response = await client.get(RITZAU_PUBLISHERS_ENDPOINT)
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, list) else []
            except Exception as exc:
                logger.warning("ritzau_via: failed to fetch publishers: %s", exc)
                return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_http_client(self) -> httpx.AsyncClient:
        """Return an ``httpx.AsyncClient`` for use as a context manager."""
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]
        return httpx.AsyncClient(timeout=30.0)

    async def _wait_for_rate_limit(self, suffix: str = "default") -> None:
        """Wait for a rate-limit slot before making an API call.

        Args:
            suffix: Key suffix for the Redis rate-limit key.
        """
        if self.rate_limiter is None:
            return
        key = f"{_RATE_LIMIT_KEY_PREFIX}:{suffix}"
        await self.rate_limiter.wait_for_slot(
            key=key,
            max_calls=RITZAU_RATE_LIMIT_MAX_CALLS,
            window_seconds=RITZAU_RATE_LIMIT_WINDOW_SECONDS,
        )

    async def _make_request(
        self,
        client: httpx.AsyncClient,
        params: dict[str, Any],
    ) -> Any:
        """Make a rate-limited GET request to the Via Ritzau releases endpoint.

        Args:
            client: Shared HTTP client.
            params: Query parameters for the releases endpoint.

        Returns:
            Parsed JSON response (list or dict).

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaCollectionError: On other non-2xx responses or connection errors.
        """
        await self._wait_for_rate_limit()
        try:
            response = await client.get(RITZAU_RELEASES_ENDPOINT, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                retry_after = float(exc.response.headers.get("Retry-After", 60))
                raise ArenaRateLimitError(
                    "ritzau_via: 429 rate limit",
                    retry_after=retry_after,
                    arena=self.arena_name,
                    platform=self.platform_name,
                ) from exc
            raise ArenaCollectionError(
                f"ritzau_via: HTTP {exc.response.status_code} from Via Ritzau API",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"ritzau_via: connection error: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

    async def _paginate_releases(
        self,
        client: httpx.AsyncClient,
        params: dict[str, Any],
        max_results: int,
    ) -> list[dict[str, Any]]:
        """Paginate through releases using offset-based pagination.

        Args:
            client: Shared HTTP client.
            params: Base query parameters (query, publisherId, language, etc.).
            max_results: Maximum records to retrieve.

        Returns:
            List of normalized records.
        """
        records: list[dict[str, Any]] = []
        offset = 0
        page_size = min(RITZAU_PAGE_SIZE, max_results)

        while len(records) < max_results:
            page_params = {**params, "limit": page_size, "offset": offset}
            data = await self._make_request(client, page_params)

            # The API may return a list directly or a wrapper object.
            items: list[dict[str, Any]] = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                # Try common wrapper keys.
                items = (
                    data.get("releases")
                    or data.get("items")
                    or data.get("data")
                    or []
                )

            if not items:
                break

            for item in items:
                if len(records) >= max_results:
                    break
                records.append(self.normalize(item))

            if len(items) < page_size:
                break  # Last page reached.

            offset += len(items)
            page_size = min(RITZAU_PAGE_SIZE, max_results - len(records))

        return records


# ---------------------------------------------------------------------------
# Module-level utility functions
# ---------------------------------------------------------------------------


def _strip_html(html: str) -> str:
    """Strip HTML tags from a string, preserving paragraph structure.

    Converts ``<p>``, ``<br>``, ``<div>`` tags to newlines before stripping
    all remaining tags, so that paragraph breaks are retained as blank lines.

    Args:
        html: HTML-formatted string.

    Returns:
        Plain text string with paragraph structure preserved.
    """
    if not html:
        return ""
    # Convert block-level tags to newlines before stripping.
    text = re.sub(r"<(?:p|br|div|h[1-6]|li)[^>]*>", "\n", html, flags=re.IGNORECASE)
    # Strip all remaining HTML tags.
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse multiple blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _to_date_str(value: datetime | str | None) -> str | None:
    """Convert a datetime or string to an ISO 8601 date string (YYYY-MM-DD).

    Args:
        value: Datetime object, ISO 8601 string, or None.

    Returns:
        Date string in ``YYYY-MM-DD`` format, or None.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str):
        # Return as-is if already looks like a date.
        return value.split("T")[0] if "T" in value else value
    return None
