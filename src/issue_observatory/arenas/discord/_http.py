"""HTTP helpers and pagination utilities for the Discord arena.

Internal module — not part of the public API. Used exclusively by
:mod:`~issue_observatory.arenas.discord.collector`.

Contains:
- Date parsing utilities
- Message enrichment helper
- Discord API pagination logic (``fetch_channel_messages``)
- Raw HTTP request dispatch with rate-limit header handling
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from issue_observatory.arenas.discord.config import MESSAGES_PER_REQUEST
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
)

logger = logging.getLogger(__name__)

# Minimum inter-request delay: 1 / 5 req/s
_MIN_DELAY_SECONDS: float = 0.2


# ---------------------------------------------------------------------------
# Date parsing utilities
# ---------------------------------------------------------------------------


def parse_date_bound(value: datetime | str | None) -> datetime | None:
    """Parse a date boundary to a timezone-aware datetime.

    Args:
        value: Datetime object, ISO 8601 string, or ``None``.

    Returns:
        Timezone-aware :class:`datetime` or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(value, fmt)
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    logger.warning("discord: could not parse date bound '%s'", value)
    return None


def parse_iso_timestamp(value: str | None) -> datetime | None:
    """Parse a Discord ISO 8601 timestamp to a timezone-aware datetime.

    Discord timestamps are formatted as ``2023-11-14T12:34:56.789000+00:00``.

    Args:
        value: ISO 8601 timestamp string or ``None``.

    Returns:
        Timezone-aware :class:`datetime` or ``None``.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Message enrichment
# ---------------------------------------------------------------------------


def enrich_message(
    msg: dict[str, Any],
    channel_id: str,
    channel_meta: dict[str, Any],
) -> dict[str, Any]:
    """Attach channel context fields to a raw message dict.

    Returns a shallow copy of *msg* with ``_channel_id`` and ``_channel_meta``
    injected so that :meth:`~DiscordCollector.normalize` can access them.

    Args:
        msg: Raw message dict from the Discord API.
        channel_id: The channel snowflake ID the message was fetched from.
        channel_meta: Channel metadata dict (from ``GET /channels/{id}``).

    Returns:
        Enriched message dict (shallow copy to avoid mutating the original).
    """
    enriched = dict(msg)
    enriched["_channel_id"] = channel_id
    enriched["_channel_meta"] = channel_meta
    return enriched


# ---------------------------------------------------------------------------
# HTTP request dispatch
# ---------------------------------------------------------------------------


async def make_request(
    client: httpx.AsyncClient,
    path: str,
    arena_name: str,
    platform_name: str,
    params: dict[str, Any] | None = None,
) -> Any:
    """Make a single Discord API request with rate-limit header handling.

    Parses ``X-RateLimit-Remaining`` and ``X-RateLimit-Reset`` response headers.
    When ``remaining == 0``, sleeps until the reset timestamp before returning
    so the next call proceeds without hitting the limit.

    A small inter-request delay is applied before every request for politeness.

    Args:
        client: Authenticated HTTP client with Discord bot token.
        path: API path relative to the base URL (e.g. ``/channels/123/messages``).
        arena_name: Arena name for error context.
        platform_name: Platform name for error context.
        params: Optional query parameters dict.

    Returns:
        Parsed JSON response (dict or list).

    Raises:
        ArenaRateLimitError: On HTTP 429.
        ArenaCollectionError: On other HTTP errors or request failures.
    """
    await asyncio.sleep(_MIN_DELAY_SECONDS)

    try:
        response = await client.get(path, params=params)
    except httpx.RequestError as exc:
        raise ArenaCollectionError(
            f"discord: request error on {path}: {exc}",
            arena=arena_name,
            platform=platform_name,
        ) from exc

    remaining = response.headers.get("X-RateLimit-Remaining")
    reset_str = response.headers.get("X-RateLimit-Reset")

    if response.status_code == 429:
        retry_after_header = response.headers.get("Retry-After", "60")
        try:
            retry_after = float(retry_after_header)
        except ValueError:
            retry_after = 60.0
        raise ArenaRateLimitError(
            f"discord: rate limited on {path}; retry_after={retry_after}s",
            retry_after=retry_after,
            arena=arena_name,
            platform=platform_name,
        )

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ArenaCollectionError(
            f"discord: HTTP {exc.response.status_code} on {path}",
            arena=arena_name,
            platform=platform_name,
        ) from exc

    # Sleep until rate-limit window resets if this was the last allowed request
    if remaining is not None and remaining == "0" and reset_str is not None:
        try:
            reset_ts = float(reset_str)
            sleep_for = max(0.0, reset_ts - time.time())
            if sleep_for > 0:
                logger.debug(
                    "discord: rate-limit window exhausted; sleeping %.2fs until reset",
                    sleep_for,
                )
                await asyncio.sleep(sleep_for)
        except (ValueError, TypeError):
            pass

    return response.json()


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


async def fetch_channel_messages(
    client: httpx.AsyncClient,
    channel_id: str,
    arena_name: str,
    platform_name: str,
    date_from_dt: datetime | None,
    date_to_dt: datetime | None,
    max_count: int,
) -> list[dict[str, Any]]:
    """Paginate through messages in a Discord channel (reverse-chronological).

    Uses the ``before`` cursor parameter to page backward from the most recent
    message until ``max_count`` is reached or the channel is exhausted.

    Date range filtering: messages newer than ``date_to_dt`` are skipped.
    When a message is older than ``date_from_dt`` paging stops immediately
    (Discord returns messages in reverse-chronological order).

    Args:
        client: Authenticated HTTP client.
        channel_id: Discord channel snowflake ID.
        arena_name: Arena name for error context.
        platform_name: Platform name for error context.
        date_from_dt: Optional lower date bound (stop paging when exceeded).
        date_to_dt: Optional upper date bound (skip messages after this).
        max_count: Maximum messages to return from this channel.

    Returns:
        List of raw message dicts from the Discord API.
    """
    messages: list[dict[str, Any]] = []
    before: str | None = None

    while len(messages) < max_count:
        params: dict[str, Any] = {
            "limit": min(MESSAGES_PER_REQUEST, max_count - len(messages))
        }
        if before:
            params["before"] = before

        try:
            batch: list[dict[str, Any]] = await make_request(
                client,
                f"/channels/{channel_id}/messages",
                arena_name=arena_name,
                platform_name=platform_name,
                params=params,
            )
        except ArenaRateLimitError:
            raise
        except ArenaCollectionError as exc:
            logger.warning(
                "discord: error fetching messages from channel %s: %s",
                channel_id,
                exc,
            )
            break

        if not batch:
            break

        stop_paging = False
        for msg in batch:
            msg_dt = parse_iso_timestamp(msg.get("timestamp"))

            if date_to_dt and msg_dt and msg_dt > date_to_dt:
                continue  # Newer than upper bound — skip

            if date_from_dt and msg_dt and msg_dt < date_from_dt:
                stop_paging = True
                break  # Older than lower bound — stop paging

            messages.append(msg)
            if len(messages) >= max_count:
                stop_paging = True
                break

        if stop_paging or len(batch) < MESSAGES_PER_REQUEST:
            break

        before = batch[-1]["id"]

    logger.debug(
        "discord: fetched %d messages from channel %s",
        len(messages),
        channel_id,
    )
    return messages
