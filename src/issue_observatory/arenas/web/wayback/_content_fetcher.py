"""Content retrieval helpers for the Wayback Machine arena (GR-12).

Provides two async functions used by
:class:`~issue_observatory.arenas.web.wayback.collector.WaybackCollector`
when ``fetch_content=True``:

- :func:`fetch_single_record_content` — fetches and extracts text for one CDX
  record via the Wayback Machine playback URL.
- :func:`fetch_content_for_records` — orchestrates a rate-limited batch of
  content fetches respecting the per-tier cap.

**Rate limiting**: the Wayback Machine applies a separate, stricter limit on
individual page retrievals compared to the CDX search API.  We use a single
``asyncio.Semaphore(1)`` combined with a 4-second sleep between acquires to
stay within the 15 req/min soft limit.

**Error isolation**: a single fetch failure (4xx, timeout, extraction error)
is logged and recorded in ``raw_metadata["content_fetch_error"]`` without
raising, so the rest of the batch is not affected.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.web.wayback.config import (
    WB_CONTENT_FETCH_SIZE_LIMIT,
    WB_MAX_CONTENT_FETCHES,
)
from issue_observatory.scraper.content_extractor import extract_from_html
from issue_observatory.scraper.http_fetcher import fetch_url

logger = logging.getLogger(__name__)

# Delay between content-fetch semaphore acquires to stay within the
# 15 req/min Wayback Machine rate limit (60 / 15 = 4.0 seconds/request).
_CONTENT_FETCH_DELAY: float = 60.0 / 15

# User-Agent sent for Wayback content page requests (distinct from CDX UA).
_CONTENT_UA: str = "IssueObservatory/1.0 (wayback-content; research use)"


def _detect_extractor(html: str, url: str) -> str:
    """Return ``'trafilatura'`` if trafilatura can extract content, else ``'fallback'``.

    Used after a successful extraction to label which code path produced
    the result, without duplicating the extraction work.

    Args:
        html: Raw HTML string.
        url: Canonical URL of the page (used for trafilatura heuristics).

    Returns:
        ``"trafilatura"`` if trafilatura is installed and extracts non-empty
        text; ``"fallback"`` otherwise.
    """
    try:
        import trafilatura  # type: ignore[import-untyped]  # noqa: PLC0415

        return "trafilatura" if trafilatura.extract(html, url=url) else "fallback"
    except Exception:  # noqa: BLE001
        return "fallback"


async def fetch_single_record_content(
    record: dict[str, Any],
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    robots_cache: dict[str, bool],
) -> dict[str, Any]:
    """Fetch and extract text content for a single CDX record.

    Acquires *semaphore* before making the HTTP request and sleeps
    :data:`_CONTENT_FETCH_DELAY` seconds inside the lock to enforce
    the 15 req/min rate limit.

    Handles 503 responses with a single retry after a 10-second pause.
    Skips extraction if the response body exceeds
    :data:`~issue_observatory.arenas.web.wayback.config.WB_CONTENT_FETCH_SIZE_LIMIT`.

    On success the *record* dict is mutated with:

    - ``text_content``: extracted article text
    - ``content_type``: ``"web_page"``
    - ``raw_metadata["content_fetched"]``: ``True``
    - ``raw_metadata["content_fetch_url"]``: the playback URL used
    - ``raw_metadata["content_fetched_at"]``: ISO 8601 UTC timestamp
    - ``raw_metadata["extractor"]``: ``"trafilatura"`` or ``"fallback"``

    On failure ``raw_metadata["content_fetch_error"]`` is set and
    ``text_content`` remains ``None``.

    Args:
        record: Normalized CDX record dict (mutated in place).
        client: Shared :class:`httpx.AsyncClient` for content requests.
        semaphore: Semaphore(1) limiting concurrent content fetches.
        robots_cache: Mutable robots.txt result cache (pass-through to
            :func:`~issue_observatory.scraper.http_fetcher.fetch_url`).

    Returns:
        The mutated *record* dict.
    """
    raw_meta: dict[str, Any] = record.get("raw_metadata", {})
    wayback_url: str | None = raw_meta.get("wayback_url")

    if not wayback_url:
        raw_meta["content_fetch_error"] = "no wayback_url in raw_metadata"
        record["raw_metadata"] = raw_meta
        return record

    # --- First fetch attempt (rate-limited) ---
    async with semaphore:
        await asyncio.sleep(_CONTENT_FETCH_DELAY)
        try:
            fetch_result = await fetch_url(
                wayback_url,
                client=client,
                timeout=30,
                respect_robots=False,  # archive.org robots.txt is not relevant
                robots_cache=robots_cache,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("wayback: unexpected fetch error for %s: %s", wayback_url, exc)
            raw_meta["content_fetch_error"] = f"unexpected error: {exc}"
            record["raw_metadata"] = raw_meta
            return record

    # --- 503 retry (single attempt, outside semaphore) ---
    if fetch_result.status_code == 503:
        logger.warning(
            "wayback: 503 on content fetch for %s — retrying after 10s", wayback_url
        )
        await asyncio.sleep(10)
        async with semaphore:
            try:
                fetch_result = await fetch_url(
                    wayback_url,
                    client=client,
                    timeout=30,
                    respect_robots=False,
                    robots_cache=robots_cache,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "wayback: 503 retry failed for %s: %s", wayback_url, exc
                )
                raw_meta["content_fetch_error"] = f"503 retry failed: {exc}"
                record["raw_metadata"] = raw_meta
                return record

    # --- Error / empty response ---
    if fetch_result.error or fetch_result.html is None:
        error_msg = fetch_result.error or "no html returned"
        logger.info("wayback: content fetch failed for %s: %s", wayback_url, error_msg)
        raw_meta["content_fetch_error"] = error_msg
        record["raw_metadata"] = raw_meta
        return record

    # --- Size guard ---
    content_bytes = fetch_result.html.encode("utf-8")
    if len(content_bytes) > WB_CONTENT_FETCH_SIZE_LIMIT:
        logger.info(
            "wayback: skipping extraction for %s — %d bytes exceeds limit",
            wayback_url,
            len(content_bytes),
        )
        raw_meta["content_skipped_size_bytes"] = len(content_bytes)
        record["raw_metadata"] = raw_meta
        return record

    # --- Text extraction ---
    try:
        extracted = extract_from_html(fetch_result.html, url=wayback_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("wayback: extraction error for %s: %s", wayback_url, exc)
        raw_meta["content_fetch_error"] = f"extraction error: {exc}"
        record["raw_metadata"] = raw_meta
        return record

    fetched_at = datetime.now(tz=timezone.utc).isoformat()

    if extracted.text:
        extractor_name = _detect_extractor(fetch_result.html, wayback_url)
        record["text_content"] = extracted.text
        record["content_type"] = "web_page"
        if extracted.title and not record.get("title"):
            record["title"] = extracted.title
        if extracted.language and not record.get("language"):
            record["language"] = extracted.language
        raw_meta["content_fetched"] = True
        raw_meta["content_fetch_url"] = wayback_url
        raw_meta["content_fetched_at"] = fetched_at
        raw_meta["extractor"] = extractor_name
        logger.debug(
            "wayback: extracted %d chars from %s (extractor=%s)",
            len(extracted.text),
            wayback_url,
            extractor_name,
        )
    else:
        raw_meta["content_fetch_error"] = "extraction returned no text"
        raw_meta["content_fetch_url"] = wayback_url
        raw_meta["content_fetched_at"] = fetched_at

    record["raw_metadata"] = raw_meta
    return record


async def fetch_content_for_records(
    records: list[dict[str, Any]],
    tier: Tier,
) -> list[dict[str, Any]]:
    """Fetch archived page content for a batch of CDX records.

    Applies the per-tier cap from
    :data:`~issue_observatory.arenas.web.wayback.config.WB_MAX_CONTENT_FETCHES`
    before dispatching fetches.  Uses ``asyncio.Semaphore(1)`` combined with
    a 4-second sleep per acquire to enforce the 15 req/min rate limit.

    Records beyond the tier cap are returned unmodified (CDX metadata only).

    Args:
        records: List of normalized CDX record dicts.
        tier: Current operational tier — determines the fetch cap.

    Returns:
        The same list with content-enriched records where applicable.  The
        list order and length are preserved.
    """
    max_fetches: int = WB_MAX_CONTENT_FETCHES.get(tier, 50)
    fetch_candidates = [
        (i, r) for i, r in enumerate(records)
        if r.get("raw_metadata", {}).get("wayback_url")
    ][:max_fetches]

    if not fetch_candidates:
        logger.debug("wayback: no records with wayback_url — skipping content fetch")
        return records

    logger.info(
        "wayback: fetching content for %d / %d records (tier=%s, max=%d)",
        len(fetch_candidates),
        len(records),
        tier.value,
        max_fetches,
    )

    content_semaphore = asyncio.Semaphore(1)
    robots_cache: dict[str, bool] = {}

    async with httpx.AsyncClient(
        timeout=35.0,
        follow_redirects=True,
        headers={"User-Agent": _CONTENT_UA},
    ) as content_client:
        coro_list = [
            fetch_single_record_content(
                records[idx], content_client, content_semaphore, robots_cache
            )
            for idx, _ in fetch_candidates
        ]
        await asyncio.gather(*coro_list, return_exceptions=False)

    fetched_count = sum(
        1 for _, r in fetch_candidates
        if r.get("raw_metadata", {}).get("content_fetched")
    )
    logger.info(
        "wayback: content fetch complete — %d succeeded / %d attempted",
        fetched_count,
        len(fetch_candidates),
    )
    return records
