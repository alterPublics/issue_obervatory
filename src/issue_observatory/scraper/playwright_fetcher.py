"""Playwright-based headless browser fetcher for JavaScript-heavy pages.

This module is an optional dependency — it is only imported when the
``use_playwright_fallback`` flag is set on a scraping job.  If Playwright
is not installed, any call to :func:`fetch_url_playwright` raises
``ImportError`` with installation instructions.

Install Playwright and download the Chromium browser binary::

    pip install playwright>=1.48
    playwright install chromium
"""

from __future__ import annotations

import logging

from issue_observatory.scraper.http_fetcher import FetchResult

logger = logging.getLogger(__name__)

# Guard import — playwright is an optional dependency
try:
    from playwright.async_api import async_playwright as _async_playwright

    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False


async def fetch_url_playwright(url: str, *, timeout: int) -> FetchResult:
    """Fetch a URL using a headless Chromium browser via Playwright.

    Launches a Playwright Chromium instance, navigates to ``url``, waits for
    the network to become idle (``"networkidle"``), and returns the full page
    source.  The browser is always closed in a ``finally`` block.

    Args:
        url: Target URL.
        timeout: Navigation timeout in seconds (converted to milliseconds
            for Playwright).

    Returns:
        A :class:`~issue_observatory.scraper.http_fetcher.FetchResult`.
        ``needs_playwright`` is always ``False`` on a successful result (we
        have already used Playwright; no further escalation is possible).

    Raises:
        ImportError: If ``playwright`` is not installed.
    """
    if not _PLAYWRIGHT_AVAILABLE:
        raise ImportError(
            "Playwright is not installed. "
            "Install it with: pip install playwright>=1.48 && playwright install chromium"
        )

    timeout_ms = timeout * 1000

    try:
        async with _async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                )
                page = await context.new_page()
                try:
                    response = await page.goto(
                        url,
                        timeout=timeout_ms,
                        wait_until="networkidle",
                    )
                    final_url = page.url
                    status_code = response.status if response else None
                    html = await page.content()
                    return FetchResult(
                        html=html,
                        status_code=status_code,
                        final_url=final_url,
                        error=None,
                        needs_playwright=False,
                    )
                finally:
                    await page.close()
                    await context.close()
            finally:
                await browser.close()

    except Exception as exc:  # noqa: BLE001
        logger.warning("scraper: playwright fetch failed for %s: %s", url, exc)
        return FetchResult(
            html=None,
            status_code=None,
            final_url=url,
            error=f"playwright error: {exc}",
            needs_playwright=False,
        )
