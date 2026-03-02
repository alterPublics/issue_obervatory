"""Redis-backed sliding window rate limiter for arena API calls.

Implements the sliding window algorithm using Redis sorted sets (ZADD /
ZREMRANGEBYSCORE / ZCARD) to enforce per-credential and per-arena rate
limits.  Lua scripts are used for atomic check-and-set operations so that
concurrent workers share a single consistent view of the rate-limit state.

Typical usage::

    redis_client = await get_redis_client()
    limiter = RateLimiter(redis_client)

    async with rate_limited_request(limiter, "reddit", "oauth2"):
        response = await http_client.get(url)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncGenerator

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RateLimitTimeoutError(Exception):
    """Raised when :meth:`RateLimiter.wait_for_slot` times out.

    Indicates that a rate-limit slot could not be acquired within the
    specified timeout duration.

    Attributes:
        key: The rate-limit key that timed out.
        timeout: The timeout value (seconds) that was exceeded.
    """

    def __init__(self, key: str, timeout: float) -> None:
        self.key = key
        self.timeout = timeout
        super().__init__(
            f"Rate limit slot for '{key}' not acquired within {timeout:.1f}s timeout."
        )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WINDOW_SECONDS: dict[str, int] = {
    "minute": 60,
    "hour": 3600,
    "day": 86400,
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RateLimitConfig:
    """Rate limit configuration for a specific arena/provider.

    Attributes:
        requests_per_minute: Maximum requests allowed per 60-second window.
        requests_per_hour: Maximum requests allowed per 3600-second window.
            ``None`` means no hourly cap.
        requests_per_day: Maximum requests allowed per 86400-second window.
            ``None`` means no daily cap.
        burst_size: Maximum burst above the per-minute rate.  When set, the
            effective per-minute cap is ``requests_per_minute + burst_size``
            for short spikes.  ``None`` disables burst allowance.
    """

    requests_per_minute: int = 60
    requests_per_hour: int | None = None
    requests_per_day: int | None = None
    burst_size: int | None = None


# Per-arena default rate limit configurations.
ARENA_DEFAULTS: dict[str, RateLimitConfig] = {
    "reddit": RateLimitConfig(
        requests_per_minute=100,
        requests_per_hour=3600,
        requests_per_day=None,
    ),
    "youtube": RateLimitConfig(
        requests_per_minute=10000,
        requests_per_hour=None,
        requests_per_day=10000,
    ),
    "bluesky": RateLimitConfig(
        requests_per_minute=50,
        requests_per_hour=None,
        requests_per_day=None,
    ),
    "google_search": RateLimitConfig(
        requests_per_minute=100,
        requests_per_hour=None,
        requests_per_day=None,
    ),
    "google_autocomplete": RateLimitConfig(
        requests_per_minute=60,
        requests_per_hour=None,
        requests_per_day=None,
    ),
    "gdelt": RateLimitConfig(
        requests_per_minute=60,
        requests_per_hour=None,
        requests_per_day=None,
    ),
    "telegram": RateLimitConfig(
        requests_per_minute=20,
        requests_per_hour=None,
        requests_per_day=None,
    ),
    "tiktok": RateLimitConfig(
        requests_per_minute=10,
        requests_per_hour=None,
        requests_per_day=None,
    ),
    "x_twitter": RateLimitConfig(
        requests_per_minute=15,
        requests_per_hour=None,
        requests_per_day=None,
    ),
    "ai_chat_search": RateLimitConfig(
        requests_per_minute=20,
        requests_per_hour=None,
        requests_per_day=None,
    ),
}

_DEFAULT_CONFIG = RateLimitConfig()

# ---------------------------------------------------------------------------
# Lua scripts
# ---------------------------------------------------------------------------

# Atomic sliding-window check-and-acquire.
#
# KEYS[1]  — sorted-set key for the window
# ARGV[1]  — current timestamp (float string)
# ARGV[2]  — window size in seconds
# ARGV[3]  — maximum requests allowed in the window
# ARGV[4]  — unique member ID for this request
# ARGV[5]  — TTL for the key (seconds, slightly > window)
#
# Returns 1 if the slot was acquired, 0 if rate-limited.
_LUA_CHECK_AND_ACQUIRE = """
local key        = KEYS[1]
local now        = tonumber(ARGV[1])
local window     = tonumber(ARGV[2])
local limit      = tonumber(ARGV[3])
local member     = ARGV[4]
local ttl        = tonumber(ARGV[5])
local cutoff     = now - window

redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local count = redis.call('ZCARD', key)
if count < limit then
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, ttl)
    return 1
end
return 0
"""

# Atomic sliding-window check-only (no acquire).
#
# Returns the current request count within the window.
_LUA_CHECK_ONLY = """
local key    = KEYS[1]
local now    = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local cutoff = now - window

redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
return redis.call('ZCARD', key)
"""

# Return the score (timestamp) of the oldest entry in the sorted set,
# or -1 if the set is empty.
_LUA_OLDEST_ENTRY = """
local key = KEYS[1]
local items = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
if #items == 0 then
    return '-1'
end
return items[2]
"""


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


@dataclass
class RateLimiter:
    """Redis-based sliding window rate limiter shared across all arenas.

    Uses Redis sorted sets keyed as::

        ratelimit:{arena}:{provider}:{key_suffix}:{window}

    where *window* is one of ``minute``, ``hour``, or ``day``.

    Lua scripts guarantee atomicity so that multiple Celery workers sharing
    the same Redis instance do not over-count or under-count requests.

    Attributes:
        redis_client: An initialised ``redis.asyncio.Redis`` connection.
    """

    redis_client: aioredis.Redis
    _sha_acquire: str = field(default="", init=False, repr=False)
    _sha_check: str = field(default="", init=False, repr=False)
    _sha_oldest: str = field(default="", init=False, repr=False)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _key(self, arena: str, provider: str, key_suffix: str, window: str) -> str:
        """Build a namespaced Redis key for a given window.

        Args:
            arena: Arena identifier (e.g. ``"reddit"``).
            provider: Provider / credential label (e.g. ``"oauth2"``).
            key_suffix: Additional discriminator (e.g. ``"default"``).
            window: One of ``"minute"``, ``"hour"``, or ``"day"``.

        Returns:
            The fully-qualified Redis key string.
        """
        return f"ratelimit:{arena}:{provider}:{key_suffix}:{window}"

    def _resolve_config(
        self, arena: str, config: RateLimitConfig | None
    ) -> RateLimitConfig:
        """Return the effective config for an arena.

        Args:
            arena: Arena identifier used to look up ``ARENA_DEFAULTS``.
            config: Caller-supplied override, or ``None`` to use defaults.

        Returns:
            The resolved :class:`RateLimitConfig`.
        """
        if config is not None:
            return config
        return ARENA_DEFAULTS.get(arena, _DEFAULT_CONFIG)

    async def _ensure_scripts_loaded(self) -> None:
        """Upload Lua scripts to Redis and cache their SHA1 hashes.

        This is called lazily on the first request so that the Redis
        connection is not required at construction time.
        """
        if self._sha_acquire:
            return
        try:
            self._sha_acquire = await self.redis_client.script_load(_LUA_CHECK_AND_ACQUIRE)
            self._sha_check = await self.redis_client.script_load(_LUA_CHECK_ONLY)
            self._sha_oldest = await self.redis_client.script_load(_LUA_OLDEST_ENTRY)
        except Exception:
            logger.exception("Failed to load Lua scripts into Redis")
            raise

    async def _run_acquire(
        self,
        key: str,
        window_name: str,
        limit: int,
        member: str,
    ) -> bool:
        """Execute the atomic check-and-acquire Lua script for one window.

        Args:
            key: Redis sorted-set key.
            window_name: Window identifier (``"minute"``, ``"hour"``, ``"day"``).
            limit: Maximum allowed requests within the window.
            member: Unique identifier for this request slot.

        Returns:
            ``True`` if the slot was acquired, ``False`` if rate-limited.
        """
        window_sec = _WINDOW_SECONDS[window_name]
        now = time.time()
        ttl = window_sec + 10  # slight buffer so Redis keeps the key alive
        result = await self.redis_client.evalsha(  # type: ignore[attr-defined]
            self._sha_acquire,
            1,
            key,
            str(now),
            str(window_sec),
            str(limit),
            member,
            str(ttl),
        )
        return bool(result)

    async def _run_check(self, key: str, window_name: str) -> int:
        """Return the current request count within *window_name* for *key*.

        Args:
            key: Redis sorted-set key.
            window_name: Window identifier.

        Returns:
            Number of requests recorded in the sliding window.
        """
        window_sec = _WINDOW_SECONDS[window_name]
        now = time.time()
        result = await self.redis_client.evalsha(  # type: ignore[attr-defined]
            self._sha_check,
            1,
            key,
            str(now),
            str(window_sec),
        )
        return int(result)

    async def _oldest_timestamp(self, key: str) -> float:
        """Return the timestamp of the oldest entry in the sorted set.

        Args:
            key: Redis sorted-set key.

        Returns:
            Unix timestamp as a float, or ``-1.0`` if the set is empty.
        """
        result = await self.redis_client.evalsha(  # type: ignore[attr-defined]
            self._sha_oldest,
            1,
            key,
        )
        return float(result)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check_and_acquire(
        self,
        arena: str,
        provider: str,
        key_suffix: str = "default",
        config: RateLimitConfig | None = None,
    ) -> bool:
        """Check rate limit and acquire a slot if available.

        Checks all configured windows (minute, hour, day) in cascade.  The
        request is allowed only when *all* applicable windows have capacity.
        If any window is exhausted the method returns ``False`` and does
        **not** record the request in any window.

        The check and record operation is atomic within each window via a
        Lua script.

        Args:
            arena: Arena identifier (e.g. ``"reddit"``).
            provider: Provider / credential label (e.g. ``"oauth2"``).
            key_suffix: Additional discriminator — use the API key ID or
                ``"default"`` for shared credentials.
            config: Override rate-limit configuration.  Falls back to
                ``ARENA_DEFAULTS[arena]`` then :data:`_DEFAULT_CONFIG`.

        Returns:
            ``True`` if the request is allowed and has been recorded.
            ``False`` if the caller is currently rate-limited.
        """
        try:
            await self._ensure_scripts_loaded()
        except Exception:
            logger.warning(
                "Redis unavailable — allowing request without rate limiting",
                extra={"arena": arena, "provider": provider},
            )
            return True

        cfg = self._resolve_config(arena, config)
        member = str(uuid.uuid4())

        # Build the set of (window_name, limit) pairs to check.
        windows: list[tuple[str, int]] = []
        effective_minute = cfg.requests_per_minute + (cfg.burst_size or 0)
        windows.append(("minute", effective_minute))
        if cfg.requests_per_hour is not None:
            windows.append(("hour", cfg.requests_per_hour))
        if cfg.requests_per_day is not None:
            windows.append(("day", cfg.requests_per_day))

        # We need all windows to have capacity before we record anything.
        # Pre-check without acquiring, then do a single acquire pass.
        # Because each window uses its own sorted set the multi-window
        # atomicity guarantee is "best effort" — good enough for API rate
        # limiting where slight over-admission is preferable to deadlock.
        acquired_keys: list[tuple[str, str]] = []
        try:
            for window_name, limit in windows:
                key = self._key(arena, provider, key_suffix, window_name)
                ok = await self._run_acquire(key, window_name, limit, member)
                if not ok:
                    # Roll back already-acquired windows.
                    for rollback_key, rollback_member in acquired_keys:
                        try:
                            await self.redis_client.zrem(rollback_key, rollback_member)
                        except Exception:
                            logger.debug(
                                "Failed to roll back rate-limit slot",
                                extra={"key": rollback_key},
                            )
                    logger.debug(
                        "Rate limited",
                        extra={
                            "arena": arena,
                            "provider": provider,
                            "window": window_name,
                        },
                    )
                    return False
                acquired_keys.append((key, member))
        except Exception:
            logger.exception(
                "Redis error during rate-limit check — allowing request",
                extra={"arena": arena, "provider": provider},
            )
            return True

        return True

    async def is_rate_limited(
        self,
        arena: str,
        provider: str,
        key_suffix: str = "default",
        config: RateLimitConfig | None = None,
    ) -> bool:
        """Check whether the caller is currently rate limited.

        Does **not** consume a request slot.

        Args:
            arena: Arena identifier.
            provider: Provider / credential label.
            key_suffix: Additional discriminator.
            config: Override rate-limit configuration.

        Returns:
            ``True`` if at least one rate-limit window is exhausted.
        """
        try:
            await self._ensure_scripts_loaded()
        except Exception:
            logger.warning("Redis unavailable — reporting not rate-limited")
            return False

        cfg = self._resolve_config(arena, config)

        windows: list[tuple[str, int]] = []
        effective_minute = cfg.requests_per_minute + (cfg.burst_size or 0)
        windows.append(("minute", effective_minute))
        if cfg.requests_per_hour is not None:
            windows.append(("hour", cfg.requests_per_hour))
        if cfg.requests_per_day is not None:
            windows.append(("day", cfg.requests_per_day))

        try:
            for window_name, limit in windows:
                key = self._key(arena, provider, key_suffix, window_name)
                count = await self._run_check(key, window_name)
                if count >= limit:
                    return True
        except Exception:
            logger.exception("Redis error during is_rate_limited check")
            return False

        return False

    async def get_wait_time(
        self,
        arena: str,
        provider: str,
        key_suffix: str = "default",
        config: RateLimitConfig | None = None,
    ) -> float:
        """Return seconds to wait before the next request is allowed.

        Inspects all configured windows and returns the maximum wait across
        all exhausted windows.  If no window is exhausted, returns ``0.0``.

        Args:
            arena: Arena identifier.
            provider: Provider / credential label.
            key_suffix: Additional discriminator.
            config: Override rate-limit configuration.

        Returns:
            Seconds (float) until rate limiting clears.  ``0.0`` means the
            caller may proceed immediately.
        """
        try:
            await self._ensure_scripts_loaded()
        except Exception:
            logger.warning("Redis unavailable — returning 0 wait time")
            return 0.0

        cfg = self._resolve_config(arena, config)

        windows: list[tuple[str, int]] = []
        effective_minute = cfg.requests_per_minute + (cfg.burst_size or 0)
        windows.append(("minute", effective_minute))
        if cfg.requests_per_hour is not None:
            windows.append(("hour", cfg.requests_per_hour))
        if cfg.requests_per_day is not None:
            windows.append(("day", cfg.requests_per_day))

        max_wait = 0.0
        now = time.time()

        try:
            for window_name, limit in windows:
                key = self._key(arena, provider, key_suffix, window_name)
                count = await self._run_check(key, window_name)
                if count >= limit:
                    oldest = await self._oldest_timestamp(key)
                    if oldest > 0:
                        window_sec = _WINDOW_SECONDS[window_name]
                        expires_at = oldest + window_sec
                        wait = max(0.0, expires_at - now)
                        max_wait = max(max_wait, wait)
        except Exception:
            logger.exception("Redis error in get_wait_time — returning 1 second")
            return 1.0

        return max_wait

    async def acquire(
        self,
        key: str,
        max_calls: int,
        window_seconds: int,
    ) -> bool:
        """Check rate limit and acquire a slot using an explicit key.

        This is the simple, low-level API required by Task 0.6.  It operates
        on an arbitrary Redis sorted-set key rather than the structured
        ``arena/provider/suffix`` hierarchy used by :meth:`check_and_acquire`.

        The sliding window algorithm is identical: the Lua script atomically
        removes expired entries, checks the current count, and inserts a new
        entry if the limit has not been reached.

        Per-arena key convention expected by callers::

            ratelimit:{arena}:{platform}:{credential_id}

        Args:
            key: Fully-qualified Redis key (caller is responsible for
                constructing the namespaced key string).
            max_calls: Maximum number of calls allowed within the window.
            window_seconds: Duration of the sliding window in seconds.

        Returns:
            ``True`` if the slot was acquired, ``False`` if rate-limited.
        """
        try:
            await self._ensure_scripts_loaded()
        except Exception:
            logger.warning(
                "Redis unavailable in acquire() — allowing request without rate limiting",
                extra={"key": key},
            )
            return True

        member = str(uuid.uuid4())
        now = time.time()
        ttl = window_seconds + 10
        try:
            result = await self.redis_client.evalsha(  # type: ignore[attr-defined]
                self._sha_acquire,
                1,
                key,
                str(now),
                str(window_seconds),
                str(max_calls),
                member,
                str(ttl),
            )
            return bool(result)
        except Exception:
            logger.exception(
                "Redis error in acquire() — allowing request",
                extra={"key": key},
            )
            return True

    async def wait_for_slot(
        self,
        key: str,
        max_calls: int,
        window_seconds: int,
        timeout: float = 60.0,
    ) -> None:
        """Block until a rate-limit slot is available or timeout is reached.

        Polls :meth:`acquire` in a loop, sleeping briefly between attempts.
        The sleep duration is calculated as ``window_seconds / max_calls``
        (i.e. the average time between permitted calls) capped at 5 seconds
        so this never stalls for too long per iteration.

        Args:
            key: Fully-qualified Redis key (same convention as
                :meth:`acquire`).
            max_calls: Maximum calls allowed within the window.
            window_seconds: Duration of the sliding window in seconds.
            timeout: Maximum total seconds to wait before raising
                :exc:`RateLimitTimeoutError`.  Defaults to 60 seconds.

        Raises:
            RateLimitTimeoutError: If a slot cannot be acquired within
                *timeout* seconds.
        """
        deadline = time.monotonic() + timeout
        sleep_seconds = min(window_seconds / max(max_calls, 1), 5.0)

        while True:
            if await self.acquire(key, max_calls, window_seconds):
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RateLimitTimeoutError(key=key, timeout=timeout)
            await asyncio.sleep(min(sleep_seconds, remaining))

    async def reset(
        self,
        arena: str,
        provider: str,
        key_suffix: str = "default",
    ) -> None:
        """Reset all rate-limit counters for an arena/provider combination.

        Deletes the sorted sets for all windows (minute, hour, day).  Useful
        for testing or administrative overrides.

        Args:
            arena: Arena identifier.
            provider: Provider / credential label.
            key_suffix: Additional discriminator.
        """
        try:
            keys = [
                self._key(arena, provider, key_suffix, window)
                for window in _WINDOW_SECONDS
            ]
            await self.redis_client.delete(*keys)
            logger.info(
                "Rate limit counters reset",
                extra={"arena": arena, "provider": provider, "key_suffix": key_suffix},
            )
        except Exception:
            logger.exception(
                "Redis error while resetting rate limits",
                extra={"arena": arena, "provider": provider},
            )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


async def get_redis_client() -> aioredis.Redis:
    """Create and return an async Redis client from application settings.

    Reads ``redis_url`` from the Pydantic Settings object.  Falls back to
    ``redis://localhost:6379/0`` if settings are not yet initialised (e.g.
    during early bootstrapping or tests).

    Returns:
        A connected :class:`redis.asyncio.Redis` instance.
    """
    try:
        from issue_observatory.config.settings import get_settings  # noqa: PLC0415

        settings = get_settings()
        redis_url = str(settings.redis_url)
    except Exception:
        redis_url = "redis://localhost:6379/0"
        logger.warning(
            "Could not load settings — using default Redis URL: %s", redis_url
        )

    client: aioredis.Redis = aioredis.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
    )
    return client


# ---------------------------------------------------------------------------
# Context manager helper
# ---------------------------------------------------------------------------


@asynccontextmanager
async def rate_limited_request(
    rate_limiter: RateLimiter,
    arena: str,
    provider: str,
    key_suffix: str = "default",
    config: RateLimitConfig | None = None,
) -> AsyncGenerator[None, None]:
    """Async context manager that waits for rate-limit clearance before yielding.

    Polls :meth:`RateLimiter.check_and_acquire` in a loop, sleeping for the
    calculated wait time (capped at 60 seconds) between attempts.

    Args:
        rate_limiter: The shared :class:`RateLimiter` instance.
        arena: Arena identifier.
        provider: Provider / credential label.
        key_suffix: Additional discriminator.
        config: Override rate-limit configuration.

    Yields:
        Control to the caller once a rate-limit slot has been acquired.

    Example::

        async with rate_limited_request(limiter, "reddit", "oauth2"):
            response = await http_client.get(url)
    """
    while not await rate_limiter.check_and_acquire(arena, provider, key_suffix, config):
        wait = await rate_limiter.get_wait_time(arena, provider, key_suffix, config)
        sleep_for = min(wait if wait > 0 else 1.0, 60.0)
        logger.debug(
            "Rate limited — sleeping %.1f s before retry",
            sleep_for,
            extra={"arena": arena, "provider": provider},
        )
        await asyncio.sleep(sleep_for)
    yield
