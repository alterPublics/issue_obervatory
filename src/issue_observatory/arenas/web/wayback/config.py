"""Configuration for the Wayback Machine arena.

Defines CDX API endpoints, default parameters, Danish URL filters, rate-limit
constants, and tier settings used by
:class:`~issue_observatory.arenas.web.wayback.collector.WaybackCollector`.

The Wayback Machine CDX API is entirely free, unauthenticated, and IP-rate-limited
at approximately 1 request/second for CDX searches and up to 30 req/sec for
individual page retrievals.

Reference: https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server
"""

from __future__ import annotations

from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------

WB_CDX_BASE_URL: str = "https://web.archive.org/cdx/search/cdx"
"""Base URL for the Wayback Machine CDX API.

Query parameters are appended as standard query string parameters.
"""

WB_AVAILABILITY_URL: str = "https://archive.org/wayback/available"
"""URL for the Wayback Machine Availability API.

Used to check whether a URL has been archived and find the closest snapshot.
"""

WB_PLAYBACK_URL_TEMPLATE: str = "https://web.archive.org/web/{timestamp}id_/{url}"
"""URL pattern for retrieving raw archived page content.

The ``id_`` suffix requests raw content without the Wayback Machine toolbar.
Used by callers to retrieve page content after finding captures via CDX API.
This template is provided for reference; content retrieval is out of scope.
"""

WB_DEFAULT_OUTPUT: str = "json"
"""Default output format for CDX API responses.

``json`` returns a 2D array: first row is field names, subsequent rows are
capture records. This is the most machine-readable format.
"""

WB_DEFAULT_FIELDS: str = "urlkey,timestamp,original,mimetype,statuscode,digest,length"
"""Default fields to return from the CDX API.

Restricting to these fields avoids fetching ``robotflags`` and other columns
that are not useful for the Issue Observatory use case.
"""

WB_DEFAULT_LIMIT: int = 500
"""Default maximum records per CDX API request.

The CDX API does not document a hard maximum, but 500 is a conservative
default that avoids response timeouts on large result sets.
"""

WB_DEFAULT_STATUS_FILTER: str = "statuscode:200"
"""Default status code filter applied to CDX queries.

Only return captures where the HTTP status was 200 (OK) to exclude
redirects, error pages, and partial content responses.
"""

WB_DEFAULT_COLLAPSE: str = "digest"
"""Default collapse parameter for CDX queries.

``digest`` deduplicates captures with identical content, returning only the
first capture for each unique page content hash. Use ``timestamp:8`` instead
to collapse to one capture per day.
"""

# ---------------------------------------------------------------------------
# Danish filter defaults
# ---------------------------------------------------------------------------

WB_DANISH_URL_PATTERN: str = "*.dk/*"
"""URL pattern for scoping CDX queries to Danish ``.dk`` domains.

Used as the ``url`` parameter with ``matchType=domain`` to return all
captures of ``.dk`` registered domains.
"""

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

WB_RATE_LIMIT_KEY: str = "ratelimit:web:wayback:shared"
"""Redis key for the Wayback Machine shared rate-limit slot."""

WB_MAX_CALLS_PER_SECOND: int = 1
"""Maximum CDX API calls per second (informal limit; no auth required)."""

WB_RATE_WINDOW_SECONDS: int = 1
"""Sliding window duration for the Wayback Machine rate limit."""

WB_RATE_LIMIT_TIMEOUT: float = 60.0
"""Maximum seconds to wait for a rate-limit slot before raising."""

WB_CONCURRENT_FETCH_LIMIT: int = 3
"""Maximum concurrent CDX API requests.

Used by ``asyncio.Semaphore`` in collect methods.
"""

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

WB_TIERS: dict[Tier, TierConfig] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=10_000,
        rate_limit_per_minute=60,
        requires_credential=False,
        estimated_credits_per_1k=0,
    ),
}
"""Tier definitions for the Wayback Machine arena. Only FREE is supported.

The Wayback Machine CDX API is entirely free and unauthenticated.
"""
