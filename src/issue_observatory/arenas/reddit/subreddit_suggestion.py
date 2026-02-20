"""Reddit subreddit suggestion utilities.

Provides utilities for discovering relevant Reddit subreddits based on search
terms via the Reddit subreddit search API (``GET /subreddits/search``).

Used by the ``GET /query-designs/{id}/suggest-subreddits`` endpoint (SB-10) to
help researchers discover Danish or topic-relevant subreddits to add to their
custom subreddit configuration (GR-03).
"""

from __future__ import annotations

import logging
from typing import Any

from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Subreddit search
# ---------------------------------------------------------------------------


async def suggest_subreddits(
    reddit: Any,
    query: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search for subreddits matching a query string.

    Uses Reddit's subreddit search API (``/subreddits/search``) to find
    subreddits whose name or description matches the query.  This is a
    FREE-tier Reddit API call via asyncpraw.

    Args:
        reddit: An active ``asyncpraw.Reddit`` context manager instance.
        query: Search query string (e.g., a search term from the query design).
        limit: Maximum number of subreddit results to return.  Defaults to 20.
            Must not exceed 100 (Reddit API limit).

    Returns:
        List of dicts, each with keys:
        - ``name`` (str): Subreddit name without the ``r/`` prefix.
        - ``display_name`` (str): Subreddit display name (same as ``name``).
        - ``display_name_prefixed`` (str): Subreddit name with ``r/`` prefix.
        - ``subscribers`` (int): Subscriber count.
        - ``description`` (str): Public description.
        - ``active_user_count`` (int | None): Current active user count (may be null).

        Returns an empty list when no matching subreddits are found or when
        an error occurs.

    Raises:
        ArenaRateLimitError: When Reddit returns a 429 response.
        ArenaAuthError: When the OAuth credentials are rejected.
        ArenaCollectionError: On other unrecoverable API errors.
    """
    import asyncprawcore.exceptions  # noqa: PLC0415

    if limit < 1:
        limit = 20
    if limit > 100:
        limit = 100

    results: list[dict[str, Any]] = []

    try:
        # Use asyncpraw's subreddit search generator
        subreddit_search = reddit.subreddits.search(query, limit=limit)
        async for subreddit in subreddit_search:
            # Extract relevant fields
            name = getattr(subreddit, "display_name", "")
            display_name_prefixed = getattr(subreddit, "display_name_prefixed", f"r/{name}")
            subscribers = getattr(subreddit, "subscribers", 0)
            description = getattr(subreddit, "public_description", "") or ""
            active_user_count = getattr(subreddit, "active_user_count", None)

            results.append(
                {
                    "name": name,
                    "display_name": name,
                    "display_name_prefixed": display_name_prefixed,
                    "subscribers": subscribers,
                    "description": description,
                    "active_user_count": active_user_count,
                }
            )

    except asyncprawcore.exceptions.TooManyRequests as exc:
        raise ArenaRateLimitError(
            f"reddit: rate limited during subreddit search for query={query!r}",
            retry_after=60.0,
            arena="social_media",
            platform="reddit",
        ) from exc
    except asyncprawcore.exceptions.ResponseException as exc:
        if hasattr(exc, "response") and exc.response is not None:
            status = exc.response.status
            if status in (401, 403):
                raise ArenaAuthError(
                    f"reddit: authentication failed (HTTP {status})",
                    arena="social_media",
                    platform="reddit",
                ) from exc
        raise ArenaCollectionError(
            f"reddit: API error during subreddit search for query={query!r}: {exc}",
            arena="social_media",
            platform="reddit",
        ) from exc
    except Exception as exc:
        raise ArenaCollectionError(
            f"reddit: unexpected error during subreddit search for query={query!r}: {exc}",
            arena="social_media",
            platform="reddit",
        ) from exc

    logger.info("reddit: subreddit search for query=%r returned %d results", query, len(results))
    return results
