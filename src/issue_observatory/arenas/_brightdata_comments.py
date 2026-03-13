"""Shared Bright Data comment collection for Facebook + Instagram.

Provides the ``BrightDataCommentCollector`` class that encapsulates the
trigger → poll → download workflow for Bright Data's comment scraper datasets.
Used by both ``FacebookCollector.collect_comments()`` and
``InstagramCollector.collect_comments()``.

The class does NOT subclass ``ArenaCollector`` — it is a utility mixin
instantiated by the platform-specific collector and given an HTTP client
and API token.

Dataset IDs:
- Facebook comments: ``gd_lkay758p1eanlolqw8`` ($1.50/1K records)
- Instagram comments: ``gd_ltppn085pokosxh13`` ($1.50/1K records)
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
)

logger = structlog.get_logger(__name__)

_BRIGHTDATA_API_BASE: str = "https://api.brightdata.com/datasets/v3"
_PROGRESS_URL: str = f"{_BRIGHTDATA_API_BASE}/progress/{{snapshot_id}}"
_SNAPSHOT_URL: str = f"{_BRIGHTDATA_API_BASE}/snapshot/{{snapshot_id}}?format=json"
_POLL_INTERVAL: int = 30
_MAX_POLL_ATTEMPTS: int = 40


def _build_trigger_url(dataset_id: str) -> str:
    """Build the full trigger URL for a comment dataset."""
    return f"{_BRIGHTDATA_API_BASE}/trigger?dataset_id={dataset_id}&include_errors=true"


class BrightDataCommentCollector:
    """Shared trigger/poll/download for Bright Data comment datasets.

    Usage::

        bd = BrightDataCommentCollector()
        async with httpx.AsyncClient(timeout=60) as client:
            comments = await bd.collect_comments_brightdata(
                client=client,
                api_token="bd-xxx",
                post_urls=["https://facebook.com/post/123"],
                dataset_id="gd_lkay758p1eanlolqw8",
                platform="facebook",
                max_comments_per_post=200,
            )
    """

    async def collect_comments_brightdata(
        self,
        client: httpx.AsyncClient,
        api_token: str,
        post_urls: list[str],
        dataset_id: str,
        platform: str,
        max_comments_per_post: int = 200,
        cancel_check: Any = None,
    ) -> list[dict[str, Any]]:
        """Trigger a Bright Data comment scrape, poll, and download results.

        Args:
            client: Shared httpx async client.
            api_token: Bright Data API bearer token.
            post_urls: List of post URLs to scrape comments from.
            dataset_id: Bright Data dataset ID for comments.
            platform: Platform name for logging (``"facebook"`` or ``"instagram"``).
            max_comments_per_post: Maximum comments to request per post URL.
            cancel_check: Optional callable to check for run cancellation.

        Returns:
            List of raw comment dicts from Bright Data.
        """
        if not post_urls:
            return []

        payload = [
            {"url": url, "num_of_comments": max_comments_per_post}
            for url in post_urls
        ]

        trigger_url = _build_trigger_url(dataset_id)
        snapshot_id = await self._trigger(client, api_token, trigger_url, payload, platform)
        raw_items = await self._poll_and_download(
            client, api_token, snapshot_id, platform, cancel_check
        )

        # Filter out error records
        valid: list[dict[str, Any]] = []
        for item in raw_items:
            if item.get("error_code"):
                input_url = (item.get("input") or {}).get("url", "unknown")
                logger.warning(
                    "%s_comments: BD error record — url=%s error=%s",
                    platform,
                    input_url,
                    item.get("error", ""),
                )
                continue
            valid.append(item)

        logger.info(
            "%s_comments: BD collected %d valid comments (filtered %d errors)",
            platform,
            len(valid),
            len(raw_items) - len(valid),
        )
        return valid

    async def _trigger(
        self,
        client: httpx.AsyncClient,
        api_token: str,
        trigger_url: str,
        payload: list[dict[str, Any]],
        platform: str,
    ) -> str:
        """POST trigger request and return snapshot_id."""
        try:
            response = await client.post(
                trigger_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                },
            )
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 60))
                raise ArenaRateLimitError(
                    f"{platform}_comments: BD 429 rate limit on trigger",
                    retry_after=retry_after,
                    arena="social_media",
                    platform=f"{platform}_comments",
                )
            if response.status_code in (401, 403):
                raise ArenaAuthError(
                    f"{platform}_comments: BD auth error HTTP {response.status_code}",
                    arena="social_media",
                    platform=f"{platform}_comments",
                )
            response.raise_for_status()
            data = response.json()
            snapshot_id: str | None = data.get("snapshot_id") or data.get("id")
            if not snapshot_id:
                raise ArenaCollectionError(
                    f"{platform}_comments: BD trigger returned no snapshot_id",
                    arena="social_media",
                    platform=f"{platform}_comments",
                )
            logger.debug("%s_comments: triggered snapshot=%s", platform, snapshot_id)
            return snapshot_id
        except (ArenaRateLimitError, ArenaAuthError, ArenaCollectionError):
            raise
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:300] if exc.response else ""
            raise ArenaCollectionError(
                f"{platform}_comments: BD trigger HTTP {exc.response.status_code}: {body}",
                arena="social_media",
                platform=f"{platform}_comments",
            ) from exc
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"{platform}_comments: BD trigger connection error: {exc}",
                arena="social_media",
                platform=f"{platform}_comments",
            ) from exc

    async def _poll_and_download(
        self,
        client: httpx.AsyncClient,
        api_token: str,
        snapshot_id: str,
        platform: str,
        cancel_check: Any = None,
    ) -> list[dict[str, Any]]:
        """Poll until ready, then download the snapshot."""
        headers = {"Authorization": f"Bearer {api_token}"}
        progress_url = _PROGRESS_URL.format(snapshot_id=snapshot_id)
        snapshot_url = _SNAPSHOT_URL.format(snapshot_id=snapshot_id)

        for attempt in range(1, _MAX_POLL_ATTEMPTS + 1):
            if cancel_check is not None:
                cancel_check()

            try:
                resp = await client.get(progress_url, headers=headers)
                resp.raise_for_status()
                prog = resp.json()
                status = prog.get("status", "")

                logger.debug(
                    "%s_comments: snapshot=%s status=%s attempt=%d/%d",
                    platform,
                    snapshot_id,
                    status,
                    attempt,
                    _MAX_POLL_ATTEMPTS,
                )

                if status == "ready":
                    break
                if status in ("failed", "error"):
                    raise ArenaCollectionError(
                        f"{platform}_comments: BD snapshot {snapshot_id} failed: {prog}",
                        arena="social_media",
                        platform=f"{platform}_comments",
                    )
            except (ArenaCollectionError, ArenaRateLimitError):
                raise
            except httpx.RequestError as exc:
                logger.warning(
                    "%s_comments: poll error (attempt %d): %s", platform, attempt, exc
                )

            if attempt < _MAX_POLL_ATTEMPTS:
                await asyncio.sleep(_POLL_INTERVAL)
        else:
            raise ArenaCollectionError(
                f"{platform}_comments: BD snapshot {snapshot_id} timed out "
                f"after {_MAX_POLL_ATTEMPTS * _POLL_INTERVAL}s",
                arena="social_media",
                platform=f"{platform}_comments",
            )

        # Download
        try:
            dl_resp = await client.get(snapshot_url, headers=headers)
            dl_resp.raise_for_status()
            raw_items: list[dict[str, Any]] = dl_resp.json()
            if not isinstance(raw_items, list):
                raw_items = raw_items.get("data", []) if isinstance(raw_items, dict) else []
            logger.info(
                "%s_comments: snapshot=%s downloaded %d items",
                platform,
                snapshot_id,
                len(raw_items),
            )
            return raw_items
        except httpx.HTTPStatusError as exc:
            raise ArenaCollectionError(
                f"{platform}_comments: BD download HTTP {exc.response.status_code}",
                arena="social_media",
                platform=f"{platform}_comments",
            ) from exc
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"{platform}_comments: BD download connection error: {exc}",
                arena="social_media",
                platform=f"{platform}_comments",
            ) from exc
