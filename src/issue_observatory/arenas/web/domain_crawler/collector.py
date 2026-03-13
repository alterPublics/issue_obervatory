"""Domain Crawler arena collector implementation.

Fetches front pages from a list of web domains, extracts same-domain article
links, then fetches and extracts each linked article.  Each article becomes
its own content record with extracted title, text, publication date, and
domain as author.

Collection modes:

- **collect_by_terms()**: Crawls all configured domains (defaults + researcher
  custom), extracts articles, then filters client-side by term occurrence in
  title + text.  Returns only records matching at least one search term.
- **collect_by_actors()**: Treats ``actor_ids`` as domain names.  Crawls those
  domains and returns all articles without term filtering.

Per-domain rate limiting uses ``asyncio.Semaphore`` instances and a politeness
delay between consecutive requests to the same domain.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

import httpx

from issue_observatory.arenas.base import ArenaCollector, TemporalMode, Tier
from issue_observatory.arenas.query_builder import match_groups_in_text
from issue_observatory.arenas.registry import register
from issue_observatory.arenas.web.domain_crawler.config import (
    CONNECTION_POOL_LIMITS,
    DANISH_NEWS_DOMAINS,
    DOMAIN_CRAWLER_TIERS,
    DOMAIN_DELAY,
    EXCLUDED_EXTENSIONS,
    FETCH_CONCURRENCY,
    HEALTH_CHECK_URL,
    IDLE_TIMEOUT,
    MAX_LINKS_PER_DOMAIN,
)
from issue_observatory.arenas.web.url_scraper._helpers import (
    extract_domain,
    resolve_published_at,
)
from issue_observatory.arenas.web.url_scraper.config import TRACKING_PARAMS
from issue_observatory.config.tiers import TierConfig
from issue_observatory.core.normalizer import Normalizer
from issue_observatory.scraper.config import DEFAULT_TIMEOUT, USER_AGENT
from issue_observatory.scraper.content_extractor import ExtractedContent, extract_from_html
from issue_observatory.scraper.http_fetcher import FetchResult, fetch_url

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Link extraction helper
# ---------------------------------------------------------------------------


class _LinkExtractor(HTMLParser):
    """Extract ``<a href>`` links from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            for attr_name, attr_value in attrs:
                if attr_name == "href" and attr_value:
                    self.links.append(attr_value)


def _normalize_link_url(href: str) -> str:
    """Strip tracking parameters from a URL for deduplication."""
    try:
        parsed = urllib.parse.urlparse(href)
        qs_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        filtered_qs = [(k, v) for k, v in qs_pairs if k not in TRACKING_PARAMS]
        new_query = urllib.parse.urlencode(filtered_qs)
        path = parsed.path.rstrip("/") or "/"
        return urllib.parse.urlunparse(
            (parsed.scheme, parsed.netloc.lower(), path, parsed.params, new_query, "")
        )
    except Exception:
        return href


def _extract_same_domain_links(
    html: str,
    base_url: str,
    target_domain: str,
) -> list[str]:
    """Extract deduplicated same-domain links from HTML.

    Resolves relative URLs against *base_url*, filters to same registered
    domain, excludes anchors/mailto/javascript/media files, and strips
    tracking parameters.

    Args:
        html: Raw HTML string.
        base_url: Base URL for resolving relative links.
        target_domain: Domain to match (without ``www.``).

    Returns:
        Deduplicated list of absolute URLs on the same domain.
    """
    parser = _LinkExtractor()
    try:
        parser.feed(html)
    except Exception:
        return []

    seen: set[str] = set()
    result: list[str] = []

    for href in parser.links:
        href = href.strip()

        # Skip non-HTTP schemes and fragments
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue

        # Resolve relative URLs
        try:
            absolute = urllib.parse.urljoin(base_url, href)
        except Exception:
            continue

        parsed = urllib.parse.urlparse(absolute)

        # HTTP(S) only
        if parsed.scheme not in ("http", "https"):
            continue

        # Same domain check
        link_domain = parsed.netloc.lower().removeprefix("www.")
        if link_domain != target_domain:
            continue

        # Exclude media/document file extensions
        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in EXCLUDED_EXTENSIONS):
            continue

        # Skip the front page itself
        if parsed.path.rstrip("/") in ("", "/"):
            continue

        # Normalize and deduplicate
        normalized = _normalize_link_url(absolute)
        if normalized not in seen:
            seen.add(normalized)
            result.append(absolute)

    return result


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


@register
class DomainCrawlerCollector(ArenaCollector):
    """Crawls web domains and extracts articles from front-page links.

    Fetches each domain's front page, discovers same-domain article links,
    then fetches and extracts each linked article.  Uses the existing
    ``HttpFetcher`` + ``trafilatura`` pipeline for content extraction.

    Supported tiers:

    - ``Tier.FREE``: Max 1000 records/run, 30 req/min, no credential needed.

    Class Attributes:
        arena_name: ``"web"``
        platform_name: ``"domain_crawler"``
        supported_tiers: ``[Tier.FREE]``
    """

    arena_name: str = "web"
    platform_name: str = "domain_crawler"
    supported_tiers: list[Tier] = [Tier.FREE]
    temporal_mode: TemporalMode = TemporalMode.RECENT

    custom_config_fields: list[dict[str, str]] = [
        {
            "key": "target_domains",
            "label": "Target domains",
            "type": "list",
            "description": "Web domains to crawl (e.g., dr.dk, tv2.dk)",
        },
    ]

    def __init__(
        self,
        credential_pool: Any = None,
        rate_limiter: Any = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(credential_pool=credential_pool, rate_limiter=rate_limiter)
        self._http_client = http_client
        self._normalizer = Normalizer()
        self._known_urls: set[str] = set()

    def set_known_urls(self, urls: set[str]) -> None:
        """Set URLs already collected so they can be skipped during crawling."""
        self._known_urls = urls

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
        extra_domains: list[str] | None = None,
        on_batch: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Crawl domains and return articles matching the search terms.

        Args:
            terms: Search terms for case-insensitive matching.
            tier: ``Tier.FREE``.
            date_from: Not applied (articles are fetched live).
            date_to: Not applied.
            max_results: Upper bound on returned records.
            term_groups: Optional boolean AND/OR groups.
            language_filter: Not applied.
            extra_domains: Researcher-configured domains from
                ``arenas_config["domain_crawler"]["target_domains"]``.
            on_batch: Optional callback invoked with each batch of normalized
                records as they become available.  Enables incremental
                persistence so records are browsable before the full crawl
                finishes.

        Returns:
            List of normalized content record dicts matching search terms.
        """
        self._validate_tier(tier)

        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

        # Build lowercase group structure for client-side boolean matching.
        if term_groups is not None:
            lower_groups: list[list[str]] = [
                [t.lower() for t in grp] for grp in term_groups if grp
            ]
        else:
            lower_groups = [[t.lower()] for t in terms]

        effective_domains = self._merge_domains(extra_domains)

        if not effective_domains:
            logger.info("domain_crawler: no domains configured, returning empty.")
            return []

        logger.info(
            "domain_crawler: collect_by_terms — crawling %d domains",
            len(effective_domains),
        )

        # When on_batch is provided, filter+normalize each batch incrementally
        # and persist via the callback so records are visible immediately.
        matched_records: list[dict[str, Any]] = []

        def _filter_and_flush(raw_articles: list[dict[str, Any]]) -> None:
            batch_matched: list[dict[str, Any]] = []
            for article in raw_articles:
                if len(matched_records) >= effective_max:
                    break
                searchable = self._build_searchable_text(article)
                matched_terms = match_groups_in_text(lower_groups, searchable)
                if not matched_terms:
                    continue
                normalized = self._normalize_article(article, tier, matched_terms)
                matched_records.append(normalized)
                batch_matched.append(normalized)

            if on_batch and batch_matched:
                on_batch(batch_matched)

        if on_batch is not None:
            await self._crawl_domains(effective_domains, tier, on_batch=_filter_and_flush)
        else:
            all_articles = await self._crawl_domains(effective_domains, tier)
            for article in all_articles:
                if len(matched_records) >= effective_max:
                    break
                searchable = self._build_searchable_text(article)
                matched_terms = match_groups_in_text(lower_groups, searchable)
                if not matched_terms:
                    continue
                normalized = self._normalize_article(article, tier, matched_terms)
                matched_records.append(normalized)
                self._flush()

        logger.info(
            "domain_crawler: collect_by_terms — %d articles matched terms.",
            len(matched_records),
        )
        return matched_records

    async def collect_by_actors(
        self,
        actor_ids: list[str],
        tier: Tier,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
        extra_domains: list[str] | None = None,
        on_batch: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Crawl actor domains and return all articles (no term filtering).

        ``actor_ids`` are treated as domain names (e.g., ``"dr.dk"``).

        Args:
            actor_ids: Domain names to crawl.
            tier: ``Tier.FREE``.
            date_from: Not applied.
            date_to: Not applied.
            max_results: Upper bound on returned records.
            extra_domains: Not used (actor_ids are the domains).
            on_batch: Optional callback invoked with each batch of normalized
                records as they become available.

        Returns:
            List of normalized content record dicts.
        """
        self._validate_tier(tier)

        if not actor_ids:
            return []

        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

        # Treat actor_ids as domains
        domains = list(dict.fromkeys(actor_ids))  # deduplicate preserving order

        logger.info(
            "domain_crawler: collect_by_actors — crawling %d domains",
            len(domains),
        )

        records: list[dict[str, Any]] = []

        def _normalize_and_flush(raw_articles: list[dict[str, Any]]) -> None:
            batch_records: list[dict[str, Any]] = []
            for article in raw_articles:
                if len(records) >= effective_max:
                    break
                normalized = self._normalize_article(article, tier, [])
                records.append(normalized)
                batch_records.append(normalized)
            if on_batch and batch_records:
                on_batch(batch_records)

        if on_batch is not None:
            await self._crawl_domains(domains, tier, on_batch=_normalize_and_flush)
        else:
            all_articles = await self._crawl_domains(domains, tier)
            for article in all_articles:
                if len(records) >= effective_max:
                    break
                records.append(self._normalize_article(article, tier, []))
                self._flush()

        logger.info(
            "domain_crawler: collect_by_actors — %d records from %d domains.",
            len(records),
            len(domains),
        )
        return records

    def get_tier_config(self, tier: Tier) -> TierConfig:
        """Return tier configuration for the Domain Crawler arena."""
        if tier not in DOMAIN_CRAWLER_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}' for domain_crawler. "
                f"Valid tiers: {list(DOMAIN_CRAWLER_TIERS.keys())}"
            )
        return DOMAIN_CRAWLER_TIERS[tier]

    def normalize(self, raw_item: dict[str, Any], tier: Tier = Tier.FREE) -> dict[str, Any]:
        """Normalize a raw article record to the universal schema."""
        return self._normalize_article(
            raw_item, tier, raw_item.get("_search_terms_matched", [])
        )

    async def health_check(self) -> dict[str, Any]:
        """Verify that the fetch-and-extract pipeline is functional."""
        checked_at = datetime.now(UTC).isoformat() + "Z"
        base: dict[str, Any] = {
            "arena": self.arena_name,
            "platform": self.platform_name,
            "checked_at": checked_at,
        }

        try:
            robots_cache: dict[str, bool] = {}
            async with self._build_http_client() as client:
                result = await fetch_url(
                    HEALTH_CHECK_URL,
                    client=client,
                    timeout=DEFAULT_TIMEOUT,
                    respect_robots=True,
                    robots_cache=robots_cache,
                )
        except Exception as exc:
            return {**base, "status": "down", "detail": f"HTTP fetch failed: {exc}"}

        if result.error or result.html is None:
            return {**base, "status": "degraded", "detail": f"Fetch error: {result.error}"}

        links = _extract_same_domain_links(result.html, HEALTH_CHECK_URL, "dr.dk")
        return {
            **base,
            "status": "ok",
            "health_check_url": HEALTH_CHECK_URL,
            "links_found": len(links),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_domains(extra_domains: list[str] | None) -> list[str]:
        """Merge default Danish domains with researcher-provided extras."""
        domains = list(DANISH_NEWS_DOMAINS)
        if extra_domains:
            for d in extra_domains:
                cleaned = d.strip().lower().removeprefix("https://").removeprefix("http://")
                cleaned = cleaned.rstrip("/")
                if cleaned and cleaned not in domains:
                    domains.append(cleaned)
        return domains

    def _build_http_client(self) -> httpx.AsyncClient:
        """Return an async HTTP client configured for domain crawling."""
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]

        limits = httpx.Limits(
            max_connections=CONNECTION_POOL_LIMITS["max_connections"],
            max_keepalive_connections=CONNECTION_POOL_LIMITS["max_keepalive_connections"],
        )
        return httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            limits=limits,
        )

    async def _crawl_domains(
        self,
        domains: list[str],
        tier: Tier,
        on_batch: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Crawl all domains: fetch front page, discover links, fetch articles.

        Domains are processed in batches of ``FETCH_CONCURRENCY``.  Within each
        batch, all domains are crawled in parallel.  Between batches, an idle
        timeout check runs: if no batch has produced any records for longer
        than ``IDLE_TIMEOUT`` seconds, the crawl stops early and returns
        whatever has been collected so far (a partial result, not a failure).

        Args:
            domains: List of domain names to crawl.
            tier: Operational tier.
            on_batch: Optional callback invoked with each batch's raw article
                dicts immediately after the batch completes.  Enables the task
                layer to persist records incrementally.

        Returns:
            Flat list of raw article dicts from all domains.
        """
        robots_cache: dict[str, bool] = {}
        all_articles: list[dict[str, Any]] = []
        last_record_at = time.monotonic()

        # Split domains into batches of FETCH_CONCURRENCY
        batches: list[list[str]] = [
            domains[i : i + FETCH_CONCURRENCY]
            for i in range(0, len(domains), FETCH_CONCURRENCY)
        ]

        async with self._build_http_client() as client:
            for batch_idx, batch in enumerate(batches):
                # Idle timeout check between batches
                if batch_idx > 0:
                    idle_seconds = time.monotonic() - last_record_at
                    if idle_seconds > IDLE_TIMEOUT:
                        logger.warning(
                            "domain_crawler: idle timeout after %.0fs without new "
                            "records — stopping with %d articles from %d/%d domains",
                            idle_seconds,
                            len(all_articles),
                            batch_idx * FETCH_CONCURRENCY,
                            len(domains),
                        )
                        break

                # Crawl all domains in this batch concurrently
                tasks = [
                    self._crawl_single_domain(domain, client, robots_cache)
                    for domain in batch
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                batch_articles: list[dict[str, Any]] = []
                for domain, result in zip(batch, results, strict=False):
                    if isinstance(result, Exception):
                        logger.error(
                            "domain_crawler: error crawling domain '%s': %s",
                            domain,
                            result,
                        )
                        continue
                    batch_articles.extend(result)

                all_articles.extend(batch_articles)

                if batch_articles:
                    last_record_at = time.monotonic()

                logger.info(
                    "domain_crawler: batch %d/%d done — %d articles from %s",
                    batch_idx + 1,
                    len(batches),
                    len(batch_articles),
                    [d for d in batch],
                )

                # Flush batch to caller for incremental persistence.
                if on_batch and batch_articles:
                    on_batch(batch_articles)

        return all_articles

    async def _crawl_single_domain(
        self,
        domain: str,
        client: httpx.AsyncClient,
        robots_cache: dict[str, bool],
    ) -> list[dict[str, Any]]:
        """Crawl a single domain: fetch front page → discover links → fetch articles.

        Args:
            domain: Bare domain name (e.g., ``"dr.dk"``).
            client: Shared HTTP client.
            robots_cache: Shared robots.txt cache.

        Returns:
            List of raw article dicts extracted from this domain.
        """
        front_page_url = f"https://{domain}/"

        # Step 1: Fetch front page
        try:
            front_result: FetchResult = await fetch_url(
                front_page_url,
                client=client,
                timeout=DEFAULT_TIMEOUT,
                respect_robots=True,
                robots_cache=robots_cache,
            )
        except Exception as exc:
            logger.warning(
                "domain_crawler: failed to fetch front page '%s': %s",
                front_page_url, exc,
            )
            return []

        if front_result.error or front_result.html is None:
            logger.info(
                "domain_crawler: front page fetch failed for '%s': %s",
                domain, front_result.error,
            )
            return []

        # Step 2: Extract same-domain links
        article_urls = _extract_same_domain_links(
            front_result.html,
            front_result.final_url or front_page_url,
            domain,
        )

        # Skip URLs already collected in previous runs
        if self._known_urls:
            before = len(article_urls)
            article_urls = [u for u in article_urls if u not in self._known_urls]
            skipped = before - len(article_urls)
            if skipped > 0:
                logger.info(
                    "domain_crawler: '%s' — skipped %d already-collected URLs",
                    domain,
                    skipped,
                )

        # Cap at MAX_LINKS_PER_DOMAIN
        if len(article_urls) > MAX_LINKS_PER_DOMAIN:
            logger.info(
                "domain_crawler: %s has %d links, capping to %d",
                domain, len(article_urls), MAX_LINKS_PER_DOMAIN,
            )
            article_urls = article_urls[:MAX_LINKS_PER_DOMAIN]

        if not article_urls:
            logger.info("domain_crawler: no article links found on '%s'", domain)
            return []

        # Step 3: Fetch each article with politeness delay
        articles: list[dict[str, Any]] = []
        for i, url in enumerate(article_urls):
            article = await self._fetch_article(
                url, domain, front_page_url, client, robots_cache
            )
            if article is not None:
                articles.append(article)

            # Politeness delay between requests to same domain
            if i < len(article_urls) - 1:
                await asyncio.sleep(DOMAIN_DELAY)

        logger.info(
            "domain_crawler: '%s' — %d/%d articles extracted",
            domain, len(articles), len(article_urls),
        )
        return articles

    async def _fetch_article(
        self,
        url: str,
        domain: str,
        front_page_url: str,
        client: httpx.AsyncClient,
        robots_cache: dict[str, bool],
    ) -> dict[str, Any] | None:
        """Fetch and extract a single article URL.

        Returns ``None`` on fetch failure or if no text could be extracted.
        """
        try:
            result: FetchResult = await fetch_url(
                url,
                client=client,
                timeout=DEFAULT_TIMEOUT,
                respect_robots=True,
                robots_cache=robots_cache,
            )
        except Exception as exc:
            logger.debug("domain_crawler: fetch error for '%s': %s", url, exc)
            return None

        if result.error or result.html is None:
            return None

        final_url = result.final_url or url

        try:
            extracted: ExtractedContent = extract_from_html(result.html, final_url)
        except Exception as exc:
            logger.debug("domain_crawler: extraction error for '%s': %s", url, exc)
            return None

        if not extracted.text:
            return None

        # Resolve publication date
        published_at = resolve_published_at(result.html, final_url, None)

        return {
            "url": final_url,
            "source_url": url,
            "title": extracted.title,
            "text_content": extracted.text,
            "language": extracted.language,
            "domain": domain,
            "front_page_url": front_page_url,
            "published_at": published_at,
            "html": result.html,
        }

    @staticmethod
    def _build_searchable_text(article: dict[str, Any]) -> str:
        """Build a lowercase searchable string from an article dict."""
        parts: list[str] = []
        if article.get("title"):
            parts.append(article["title"])
        if article.get("text_content"):
            parts.append(article["text_content"])
        return " ".join(parts).lower()

    def _normalize_article(
        self,
        article: dict[str, Any],
        tier: Tier,
        search_terms_matched: list[str],
    ) -> dict[str, Any]:
        """Normalize a raw article dict to a Universal Content Record."""
        url = article.get("url", "")
        domain = article.get("domain", extract_domain(url))
        text_content = article.get("text_content")
        title = article.get("title")
        language = article.get("language")

        # platform_id: SHA-256 of URL
        platform_id = hashlib.sha256(url.encode()).hexdigest()

        # content_hash: SHA-256 of text content
        content_hash: str | None = (
            self._normalizer.compute_content_hash(text_content)
            if text_content
            else self._normalizer.compute_content_hash(url)
        )

        # pseudonymized_author_id: domain treated as the "author"
        pseudonymized_author_id = self._normalizer.pseudonymize_author(
            self.platform_name, domain
        )

        published_at = article.get("published_at")
        if isinstance(published_at, datetime):
            published_at_str = published_at.isoformat()
        elif published_at:
            published_at_str = str(published_at)
        else:
            published_at_str = datetime.now(tz=UTC).isoformat()

        raw_metadata: dict[str, Any] = {
            "source_domain": domain,
            "source_page": article.get("front_page_url", f"https://{domain}/"),
            "source_url": article.get("source_url", url),
            "final_url": url,
        }

        norm_input: dict[str, Any] = {
            "id": platform_id,
            "url": url,
            "title": title,
            "text_content": text_content,
            "author": domain,
            "author_display_name": domain,
            "published_at": published_at_str,
            "language": language,
            "content_type": "article",
            "media_urls": [],
            "_search_terms_matched": search_terms_matched,
        }

        normalized = self._normalizer.normalize(
            raw_item=norm_input,
            platform=self.platform_name,
            arena=self.arena_name,
            collection_tier=tier.value,
            search_terms_matched=search_terms_matched,
        )

        # Ensure computed values take precedence
        normalized["platform_id"] = platform_id
        normalized["content_type"] = "article"
        normalized["content_hash"] = content_hash
        normalized["pseudonymized_author_id"] = pseudonymized_author_id
        normalized["raw_metadata"] = raw_metadata
        normalized["media_urls"] = []

        return normalized
