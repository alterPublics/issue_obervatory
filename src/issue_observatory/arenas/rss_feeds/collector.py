"""RSS Feeds arena collector implementation.

Polls curated Danish RSS feeds in parallel using ``httpx`` for async HTTP
and ``feedparser`` for parsing.  Supports two collection modes:

- **collect_by_terms()**: Fetches *all* configured feeds (or a subset) and
  returns entries whose title or summary contain any of the supplied terms.
- **collect_by_actors()**: Treats each ``actor_id`` as an outlet slug key
  from :data:`DANISH_RSS_FEEDS` and returns all entries from that outlet's
  feeds (no term filtering).

All entries are normalized to the universal ``content_records`` schema by
:meth:`normalize`.

No credentials are required.  Rate limiting is implemented via a
``asyncio.Semaphore`` capping concurrent feed fetches at
:data:`~config.FETCH_CONCURRENCY` (default 10) plus a small per-outlet
delay between requests to the same hostname.

Conditional GET (``If-Modified-Since`` / ``If-None-Match``) is implemented
to avoid re-processing feeds that have not changed since the last fetch.
"""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx

from issue_observatory.arenas.base import ArenaCollector, TemporalMode, Tier
from issue_observatory.arenas.query_builder import build_boolean_query_groups
from issue_observatory.arenas.registry import register
from issue_observatory.arenas.rss_feeds.config import (
    FETCH_CONCURRENCY,
    HEALTH_CHECK_FEED_URL,
    HEALTH_CHECK_OUTLET,
    INTER_OUTLET_DELAY_SECONDS,
    RSS_TIERS,
    outlet_slug_from_key,
)
from issue_observatory.config.danish_defaults import DANISH_RSS_FEEDS
from issue_observatory.config.tiers import TierConfig
from issue_observatory.core.exceptions import ArenaCollectionError
from issue_observatory.core.normalizer import Normalizer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTML tag stripping regex (safe replacement for heavy dependencies)
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Strip HTML tags from *text* and collapse whitespace.

    Args:
        text: Raw string that may contain HTML markup.

    Returns:
        Plain-text string with tags removed and whitespace normalized.
    """
    cleaned = _HTML_TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", cleaned).strip()


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


@register
class RSSFeedsCollector(ArenaCollector):
    """Collects articles from curated Danish RSS feeds.

    Supported tiers:
    - ``Tier.FREE`` — direct feedparser polling; no credentials required.

    Class Attributes:
        arena_name: ``"rss_feeds"`` (registry key; ``"news_media"`` written to content records)
        platform_name: ``"rss_feeds"``
        supported_tiers: ``[Tier.FREE]``

    Args:
        credential_pool: Unused — all feeds are public.  Pass ``None``.
        rate_limiter: Optional shared rate limiter.  Not used for RSS
            (semaphore-based local limiting is sufficient).
        http_client: Optional injected :class:`httpx.AsyncClient`.
            Inject for testing.  If ``None``, a new client is created
            per collection call.
        feed_overrides: Optional dict overriding the default feed registry
            (``DANISH_RSS_FEEDS``).  Useful for testing with mock feeds.
    """

    arena_name: str = "rss_feeds"
    platform_name: str = "rss_feeds"
    supported_tiers: list[Tier] = [Tier.FREE]
    temporal_mode: TemporalMode = TemporalMode.FORWARD_ONLY

    # The logical arena group stored in the content_records ``arena`` column.
    # Distinct from ``arena_name`` which is used as the registry key.
    _content_arena: str = "news_media"

    def __init__(
        self,
        credential_pool: Any = None,
        rate_limiter: Any = None,
        http_client: httpx.AsyncClient | None = None,
        feed_overrides: dict[str, str] | None = None,
    ) -> None:
        super().__init__(credential_pool=credential_pool, rate_limiter=rate_limiter)
        self._http_client = http_client
        self._normalizer = Normalizer()
        self._feeds: dict[str, str] = feed_overrides if feed_overrides is not None else DANISH_RSS_FEEDS
        # Cache: feed_key -> {"etag": str, "last_modified": str}
        self._feed_cache: dict[str, dict[str, str]] = {}

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
        extra_feed_urls: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Collect RSS entries matching any of the supplied terms.

        Fetches all configured feeds in parallel (bounded by semaphore),
        then filters entries by term occurrence in title or summary.

        Boolean logic is applied client-side when ``term_groups`` is provided:
        an entry matches when at least one group has ALL its terms present in
        the searchable text (group = AND, groups = OR).

        Args:
            terms: Search terms for case-insensitive substring matching
                (used when ``term_groups`` is ``None``).
            tier: Must be ``Tier.FREE``.
            date_from: Earliest publication date to include (inclusive).
            date_to: Latest publication date to include (inclusive).
            max_results: Upper bound on returned records.
            term_groups: Optional boolean AND/OR groups for client-side
                filtering.  Entries must satisfy at least one AND-group.
            language_filter: Not used — RSS feeds are language-specific by
                their source URL configuration.
            extra_feed_urls: Optional list of additional feed URLs supplied
                by the researcher via ``arenas_config["rss"]["custom_feeds"]``.
                These are merged with the default feed registry before fetching.
                Each URL is auto-keyed as ``custom_{index}`` in the registry.

        Returns:
            List of normalized content record dicts.

        Raises:
            ValueError: If *tier* is not ``Tier.FREE``.
            ArenaCollectionError: If feed fetching fails globally.
        """
        self._validate_tier(tier)
        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

        date_from_dt = _parse_date_bound(date_from)
        date_to_dt = _parse_date_bound(date_to)

        # Build lowercase group structure for client-side boolean matching.
        if term_groups is not None:
            lower_groups: list[list[str]] = [
                [t.lower() for t in grp] for grp in term_groups if grp
            ]
            # Flat list for matched-term recording
            lower_terms = [t for grp in lower_groups for t in grp]
        else:
            lower_terms = [t.lower() for t in terms]
            lower_groups = [[t] for t in lower_terms]  # each term = own OR group

        all_records: list[dict[str, Any]] = []

        # Merge extra researcher-supplied feed URLs into the active feed dict.
        effective_feeds = _merge_extra_feeds(self._feeds, extra_feed_urls)

        async with self._build_http_client() as client:
            raw_entries = await self._fetch_feeds(client, effective_feeds)

        for feed_key, outlet_slug, entry in raw_entries:
            if len(all_records) >= effective_max:
                break

            pub_dt = _entry_datetime(entry)
            if date_from_dt and pub_dt and pub_dt < date_from_dt:
                continue
            if date_to_dt and pub_dt and pub_dt > date_to_dt:
                continue

            searchable = _build_searchable_text(entry)

            # An entry matches if any AND-group has all its terms present.
            matched_terms: list[str] = []
            for grp in lower_groups:
                if all(t in searchable for t in grp):
                    matched_terms.extend(grp)
            if not matched_terms:
                continue

            record = self._normalize_entry(
                entry=entry,
                feed_key=feed_key,
                outlet_slug=outlet_slug,
                search_terms_matched=matched_terms,
            )
            all_records.append(record)

        logger.info(
            "rss_feeds: collect_by_terms — %d entries matched across all feeds",
            len(all_records),
        )
        return all_records

    async def collect_by_actors(
        self,
        actor_ids: list[str],
        tier: Tier,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
        extra_feed_urls: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Collect all entries from feeds associated with specific outlets.

        Each ``actor_id`` is a key from :data:`DANISH_RSS_FEEDS` (e.g.
        ``"dr_allenyheder"``) or an outlet slug prefix (e.g. ``"dr"``).
        All feeds whose key starts with the slug are fetched; all their
        entries are returned without term filtering.

        Args:
            actor_ids: Feed keys or outlet slug prefixes.
            tier: Must be ``Tier.FREE``.
            date_from: Earliest publication date to include.
            date_to: Latest publication date to include.
            max_results: Upper bound on returned records.
            extra_feed_urls: Optional list of additional feed URLs supplied
                by the researcher via ``arenas_config["rss"]["custom_feeds"]``.
                These are merged with the default feed registry before resolving
                actor_ids.  Each URL is auto-keyed as ``custom_{index}``.

        Returns:
            List of normalized content record dicts.

        Raises:
            ValueError: If *tier* is not ``Tier.FREE``.
        """
        self._validate_tier(tier)
        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

        date_from_dt = _parse_date_bound(date_from)
        date_to_dt = _parse_date_bound(date_to)

        # Merge extra researcher-supplied feed URLs into the active feed dict.
        effective_feeds = _merge_extra_feeds(self._feeds, extra_feed_urls)

        # Resolve actor_ids to matching feed keys
        target_feeds: dict[str, str] = {}
        for actor_id in actor_ids:
            for feed_key, feed_url in effective_feeds.items():
                if feed_key == actor_id or feed_key.startswith(actor_id + "_") or feed_key.startswith(actor_id):
                    target_feeds[feed_key] = feed_url

        if not target_feeds:
            logger.warning(
                "rss_feeds: collect_by_actors — no feeds matched actor_ids=%r", actor_ids
            )
            return []

        all_records: list[dict[str, Any]] = []

        async with self._build_http_client() as client:
            raw_entries = await self._fetch_feeds(client, target_feeds)

        for feed_key, outlet_slug, entry in raw_entries:
            if len(all_records) >= effective_max:
                break

            pub_dt = _entry_datetime(entry)
            if date_from_dt and pub_dt and pub_dt < date_from_dt:
                continue
            if date_to_dt and pub_dt and pub_dt > date_to_dt:
                continue

            record = self._normalize_entry(
                entry=entry,
                feed_key=feed_key,
                outlet_slug=outlet_slug,
                search_terms_matched=[],
            )
            all_records.append(record)

        logger.info(
            "rss_feeds: collect_by_actors — %d entries from %d feeds",
            len(all_records),
            len(target_feeds),
        )
        return all_records

    def get_tier_config(self, tier: Tier) -> TierConfig:
        """Return tier configuration for the RSS Feeds arena.

        Args:
            tier: Requested operational tier.

        Returns:
            :class:`~issue_observatory.config.tiers.TierConfig` for FREE tier.

        Raises:
            ValueError: If *tier* is not in ``supported_tiers``.
        """
        if tier not in RSS_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}' for rss_feeds. "
                f"Valid tiers: {list(RSS_TIERS.keys())}"
            )
        return RSS_TIERS[tier]

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw RSS entry dict to the universal schema.

        This is the low-level entry point used by :meth:`_normalize_entry`.
        Callers should prefer :meth:`_normalize_entry` which enriches the
        raw item before calling here.

        Args:
            raw_item: Dict with keys ``feed_key``, ``outlet_slug``, and
                all standard feedparser entry fields.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        outlet_slug = raw_item.get("outlet_slug", "rss")
        return self._normalizer.normalize(
            raw_item=raw_item,
            platform=outlet_slug,
            arena="news_media",
            collection_tier="free",
            search_terms_matched=raw_item.get("_search_terms_matched", []),
        )

    async def health_check(self) -> dict[str, Any]:
        """Verify that the DR all-news RSS feed is reachable and parseable.

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

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    HEALTH_CHECK_FEED_URL,
                    headers={"User-Agent": "IssueObservatory/1.0 (feed health check)"},
                )
                if response.status_code == 304:
                    return {**base, "status": "ok", "detail": "304 Not Modified (cached)"}
                response.raise_for_status()
                feed = feedparser.parse(response.text)
                if feed.bozo and not feed.entries:
                    return {
                        **base,
                        "status": "degraded",
                        "detail": f"feedparser bozo error: {feed.bozo_exception}",
                    }
                entry_count = len(feed.entries)
                return {
                    **base,
                    "status": "ok",
                    "feed": HEALTH_CHECK_OUTLET,
                    "entries": entry_count,
                }
        except httpx.HTTPStatusError as exc:
            return {
                **base,
                "status": "down",
                "detail": f"HTTP {exc.response.status_code} from {HEALTH_CHECK_FEED_URL}",
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
        with a 30-second timeout and a descriptive User-Agent header.
        """
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]
        return httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "IssueObservatory/1.0 (rss-collector; +https://github.com/issue-observatory)"},
        )

    async def _fetch_all_feeds(
        self, client: httpx.AsyncClient
    ) -> list[tuple[str, str, Any]]:
        """Fetch all feeds in :data:`DANISH_RSS_FEEDS` in parallel.

        Args:
            client: Shared HTTP client.

        Returns:
            List of ``(feed_key, outlet_slug, entry)`` triples.
        """
        return await self._fetch_feeds(client, self._feeds)

    async def _fetch_feeds(
        self,
        client: httpx.AsyncClient,
        feeds: dict[str, str],
    ) -> list[tuple[str, str, Any]]:
        """Fetch a specific set of feeds in parallel with a semaphore.

        Args:
            client: Shared HTTP client.
            feeds: Dict of ``{feed_key: feed_url}`` to fetch.

        Returns:
            List of ``(feed_key, outlet_slug, entry)`` triples across all feeds.
        """
        semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)
        tasks = [
            self._fetch_single_feed(client, feed_key, feed_url, semaphore)
            for feed_key, feed_url in feeds.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_entries: list[tuple[str, str, Any]] = []
        for feed_key, result in zip(feeds.keys(), results):
            if isinstance(result, Exception):
                logger.warning(
                    "rss_feeds: failed to fetch feed '%s': %s", feed_key, result
                )
                continue
            all_entries.extend(result)

        return all_entries

    async def _fetch_single_feed(
        self,
        client: httpx.AsyncClient,
        feed_key: str,
        feed_url: str,
        semaphore: asyncio.Semaphore,
    ) -> list[tuple[str, str, Any]]:
        """Fetch and parse a single RSS/Atom feed.

        Implements conditional GET using cached ETag / Last-Modified headers.
        Returns empty list on 304 Not Modified.

        Args:
            client: Shared HTTP client.
            feed_key: Key from ``DANISH_RSS_FEEDS``.
            feed_url: URL of the feed.
            semaphore: Concurrency limiter.

        Returns:
            List of ``(feed_key, outlet_slug, entry)`` triples.

        Raises:
            ArenaCollectionError: On non-retryable HTTP errors.
        """
        outlet_slug = outlet_slug_from_key(feed_key)

        async with semaphore:
            headers: dict[str, str] = {}
            cached = self._feed_cache.get(feed_key, {})
            if cached.get("etag"):
                headers["If-None-Match"] = cached["etag"]
            if cached.get("last_modified"):
                headers["If-Modified-Since"] = cached["last_modified"]

            try:
                response = await client.get(feed_url, headers=headers)
            except httpx.RequestError as exc:
                raise ArenaCollectionError(
                    f"rss_feeds: request error fetching '{feed_key}': {exc}",
                    arena="news_media",
                    platform=outlet_slug,
                ) from exc

            if response.status_code == 304:
                logger.debug("rss_feeds: '%s' — 304 Not Modified, skipping.", feed_key)
                return []

            if response.status_code >= 400:
                logger.warning(
                    "rss_feeds: '%s' returned HTTP %d — skipping.",
                    feed_key,
                    response.status_code,
                )
                return []

            # Update conditional-GET cache
            new_cache: dict[str, str] = {}
            if response.headers.get("ETag"):
                new_cache["etag"] = response.headers["ETag"]
            if response.headers.get("Last-Modified"):
                new_cache["last_modified"] = response.headers["Last-Modified"]
            if new_cache:
                self._feed_cache[feed_key] = new_cache

            # Small inter-outlet courtesy delay
            await asyncio.sleep(INTER_OUTLET_DELAY_SECONDS)

        # Parse feed (feedparser is CPU-bound but fast enough to run inline)
        try:
            feed = feedparser.parse(response.text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("rss_feeds: feedparser error for '%s': %s", feed_key, exc)
            return []

        if feed.bozo and not feed.entries:
            logger.warning(
                "rss_feeds: bozo feed '%s' with no entries: %s",
                feed_key,
                getattr(feed, "bozo_exception", "unknown"),
            )
            return []

        return [(feed_key, outlet_slug, entry) for entry in feed.entries]

    def _normalize_entry(
        self,
        entry: Any,
        feed_key: str,
        outlet_slug: str,
        search_terms_matched: list[str],
    ) -> dict[str, Any]:
        """Build a raw item dict from a feedparser entry and normalize it.

        Args:
            entry: A feedparser entry object.
            feed_key: Key from ``DANISH_RSS_FEEDS``.
            outlet_slug: Derived outlet name (e.g. ``"dr"``).
            search_terms_matched: Terms that matched this entry.

        Returns:
            Normalized content record dict.
        """
        # platform_id: prefer entry.id (guid), fall back to entry.link
        platform_id: str | None = getattr(entry, "id", None) or getattr(entry, "link", None)

        title: str | None = getattr(entry, "title", None)
        url: str | None = getattr(entry, "link", None)

        # summary / description — strip HTML
        raw_summary: str = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        text_content: str | None = _strip_html(raw_summary) if raw_summary else None

        # Author
        author: str | None = getattr(entry, "author", None)

        # Tags / categories
        tags: list[str] = []
        for tag in getattr(entry, "tags", []):
            term = getattr(tag, "term", None)
            if term:
                tags.append(str(term))

        # Media URLs from media_content or enclosures
        media_urls: list[str] = []
        for mc in getattr(entry, "media_content", []):
            url_mc = mc.get("url")
            if url_mc:
                media_urls.append(url_mc)
        for enc in getattr(entry, "enclosures", []):
            url_enc = enc.get("href") or enc.get("url")
            if url_enc:
                media_urls.append(url_enc)

        # Publication date
        published_at: str | None = None
        pub_struct = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
        if pub_struct:
            try:
                ts = calendar.timegm(pub_struct)
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                published_at = dt.isoformat()
            except (TypeError, ValueError, OverflowError):
                pass

        # content_hash — SHA-256 of normalized title for cross-feed dedup
        content_hash: str | None = None
        if title:
            content_hash = self._normalizer.compute_content_hash(title)
        elif url:
            content_hash = self._normalizer.compute_content_hash(url)

        raw_item: dict[str, Any] = {
            # Fields used by Normalizer's _extract_* methods
            "id": platform_id,
            "title": title,
            "url": url,
            "text_content": text_content,
            "author": author,
            "published_at": published_at,
            "language": "da",
            "content_type": "article",
            "media_urls": media_urls,
            # Extra metadata stored in raw_metadata
            "feed_key": feed_key,
            "outlet_name": outlet_slug,
            "tags": tags,
            "_search_terms_matched": search_terms_matched,
        }

        normalized = self._normalizer.normalize(
            raw_item=raw_item,
            platform=outlet_slug,
            arena="news_media",
            collection_tier="free",
            search_terms_matched=search_terms_matched,
        )

        # Ensure content_hash override (title-based) takes precedence
        if content_hash:
            normalized["content_hash"] = content_hash

        return normalized


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _parse_date_bound(value: datetime | str | None) -> datetime | None:
    """Parse a date boundary to a timezone-aware datetime.

    Args:
        value: Datetime object, ISO 8601 string, or ``None``.

    Returns:
        Timezone-aware :class:`datetime` or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    # Try ISO 8601 string
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    logger.warning("rss_feeds: could not parse date bound '%s'", value)
    return None


def _entry_datetime(entry: Any) -> datetime | None:
    """Extract a timezone-aware publication datetime from a feedparser entry.

    Args:
        entry: feedparser entry object.

    Returns:
        Timezone-aware :class:`datetime` or ``None``.
    """
    pub_struct = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if pub_struct is None:
        return None
    try:
        ts = calendar.timegm(pub_struct)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _merge_extra_feeds(
    base_feeds: dict[str, str],
    extra_feed_urls: list[str] | None,
) -> dict[str, str]:
    """Merge researcher-supplied feed URLs into the base feed registry.

    Extra URLs are auto-keyed as ``custom_0``, ``custom_1``, etc.  Existing
    keys are not overwritten; only URLs not already present as values are
    added (deduplication by URL).

    Args:
        base_feeds: The default feed registry (e.g. :data:`DANISH_RSS_FEEDS`).
        extra_feed_urls: Optional list of additional feed URLs from the
            researcher's ``arenas_config["rss"]["custom_feeds"]``.

    Returns:
        A new dict containing all base feeds plus any non-duplicate extra URLs.
    """
    if not extra_feed_urls:
        return base_feeds

    merged = dict(base_feeds)
    existing_urls = set(base_feeds.values())
    counter = 0
    for url in extra_feed_urls:
        if not url or url in existing_urls:
            continue
        merged[f"custom_{counter}"] = url
        existing_urls.add(url)
        counter += 1
    return merged


def _build_searchable_text(entry: Any) -> str:
    """Build a lowercase searchable string from an entry's title and summary.

    Args:
        entry: feedparser entry object.

    Returns:
        Lowercased concatenation of title and summary (HTML stripped).
    """
    parts = []
    title = getattr(entry, "title", "") or ""
    summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
    if title:
        parts.append(title)
    if summary:
        parts.append(_strip_html(summary))
    return " ".join(parts).lower()
