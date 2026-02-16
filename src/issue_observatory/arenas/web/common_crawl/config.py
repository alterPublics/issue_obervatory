"""Configuration for the Common Crawl arena.

Defines API endpoints, index identifiers, Danish TLD filter, rate-limit
constants, and tier settings used by
:class:`~issue_observatory.arenas.web.common_crawl.collector.CommonCrawlCollector`.

The Common Crawl Index API exposes one endpoint per crawl:
``https://index.commoncrawl.org/{index}/search``

The collection-info endpoint returns a list of all available indexes:
``https://index.commoncrawl.org/collinfo.json``
"""

from __future__ import annotations

from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------

CC_INDEX_BASE_URL: str = "https://index.commoncrawl.org"
"""Base URL for the Common Crawl Index API.

Append ``/{index}/search`` for search queries, or ``/collinfo.json`` for the
list of available crawl indexes.
"""

CC_COLLINFO_URL: str = f"{CC_INDEX_BASE_URL}/collinfo.json"
"""URL for the Common Crawl collection info endpoint.

Returns a JSON array of available crawl indexes with metadata (id, name,
timegate, cdx-api URL). Used by the health check and to resolve 'latest'.
"""

CC_DEFAULT_INDEX: str = "CC-MAIN-2025-51"
"""Default Common Crawl index to query when no explicit index is specified.

This should be updated periodically to reflect the most recent available crawl.
The :meth:`~CommonCrawlCollector.health_check` method dynamically resolves
the latest index from collinfo.json; this constant is the fallback.
"""

CC_DEFAULT_MATCH_TYPE: str = "domain"
"""Default URL match type for CC Index API queries.

``domain`` matches all captures where the registered domain equals the query
domain, including all subdomains and paths.
"""

CC_DEFAULT_OUTPUT: str = "json"
"""Output format for CC Index API responses.

``json`` returns one JSON object per line (NDJSON). This is the only
format that supports all fields and is used exclusively.
"""

CC_MAX_RECORDS_PER_PAGE: int = 1_000
"""Maximum records requested per CC Index API page.

The API does not document a hard limit, but 1,000 is a conservative page size
that avoids timeouts on large result sets.
"""

# ---------------------------------------------------------------------------
# Danish filter defaults
# ---------------------------------------------------------------------------

CC_DANISH_TLD_FILTER: str = "dk"
"""Danish TLD used to scope CC Index API queries to Danish web content.

Applied as ``url=*.dk`` in the query URL pattern, returning all captures
where the registered domain has a ``.dk`` TLD.
"""

CC_DANISH_LANGUAGE_CODE: str = "dan"
"""ISO 639-3 language code for Danish, as used in Common Crawl ``languages`` field.

The CC index stores detected languages in ISO 639-3 format (``"dan"``) rather
than the ISO 639-1 format (``"da"``) used throughout the rest of the system.
"""

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

CC_RATE_LIMIT_KEY: str = "ratelimit:web:common_crawl:shared"
"""Redis key for the Common Crawl shared rate-limit slot."""

CC_MAX_CALLS_PER_SECOND: int = 1
"""Maximum CC Index API calls per second (informal limit; no auth required)."""

CC_RATE_WINDOW_SECONDS: int = 1
"""Sliding window duration for the CC rate limit."""

CC_RATE_LIMIT_TIMEOUT: float = 60.0
"""Maximum seconds to wait for a rate-limit slot before raising."""

CC_CONCURRENT_FETCH_LIMIT: int = 3
"""Maximum concurrent HTTP requests during paginated fetches.

Used by ``asyncio.Semaphore`` in collect methods to avoid overwhelming the
API with simultaneous page requests.
"""

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

CC_TIERS: dict[Tier, TierConfig] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=10_000,
        rate_limit_per_minute=60,
        requires_credential=False,
        estimated_credits_per_1k=0,
    ),
}
"""Tier definitions for the Common Crawl arena. Only FREE is supported.

The CC Index API is entirely free and unauthenticated.  AWS Athena queries
(out of scope for Phase 2) would incur variable cost depending on scan volume.
"""
