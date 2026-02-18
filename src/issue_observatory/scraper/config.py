"""Constants and tuning parameters for the web scraper enrichment service."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Fetch timing
# ---------------------------------------------------------------------------

#: Default minimum inter-request delay (seconds).  Overridden per job.
DEFAULT_DELAY_MIN: float = 2.0

#: Default maximum inter-request delay (seconds).  Overridden per job.
DEFAULT_DELAY_MAX: float = 5.0

#: Default HTTP request timeout in seconds.
DEFAULT_TIMEOUT: int = 30

# ---------------------------------------------------------------------------
# Content size guards
# ---------------------------------------------------------------------------

#: Maximum extracted text size (bytes).  PostgreSQL's tsvector limit is ~1 MB;
#: keeping below 900 KB leaves headroom for encoding overhead.
MAX_CONTENT_BYTES: int = 900 * 1024  # 900 KB

#: Body length threshold (stripped characters) below which a page is
#: considered a JS-only shell requiring a Playwright retry.
JS_SHELL_BODY_THRESHOLD: int = 500

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

#: User-agent string sent with every HTTP request.
USER_AGENT: str = (
    "IssueObservatory/1.0 (+https://github.com/issue-observatory; "
    "research scraper; contact: research@example.org)"
)

#: Content-Type prefixes that indicate binary/non-text resources that should
#: be skipped without attempting extraction.
BINARY_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/zip",
        "application/octet-stream",
        "application/x-executable",
        "application/vnd.",
        "image/",
        "video/",
        "audio/",
        "font/",
    }
)

# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------

#: robots.txt user-agent token to check against.
ROBOTS_USER_AGENT: str = "IssueObservatory"

#: Fallback user-agent token if a site has no entry for ``ROBOTS_USER_AGENT``.
ROBOTS_USER_AGENT_FALLBACK: str = "*"
