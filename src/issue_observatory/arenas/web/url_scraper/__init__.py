"""URL Scraper arena — live web page content extraction.

Fetches researcher-provided URLs, extracts article text via ``trafilatura``,
and stores results as Universal Content Records in the ``web`` arena.

Supported tiers:
- ``FREE``: max 100 URLs/run, httpx only, 1 req/sec per domain.
- ``MEDIUM``: max 500 URLs/run, Playwright fallback for JS pages, 2 req/sec.

No external API required.  Respects ``robots.txt`` and applies per-domain
politeness delays.
"""
