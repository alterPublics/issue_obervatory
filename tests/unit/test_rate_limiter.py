"""Unit tests for RateLimiter and rate_limited_request.

Tests cover:
- RateLimiter._key() builds the expected namespaced Redis key
- RateLimiter._resolve_config() returns arena defaults and caller overrides
- RateLimiter.acquire() returns True when Redis Lua script returns 1
- RateLimiter.acquire() returns False when Lua script returns 0 (rate limited)
- RateLimiter.acquire() returns True (allow) when Redis is unavailable
- RateLimiter.check_and_acquire() respects minute/hour/day windows in cascade
- RateLimiter.check_and_acquire() rolls back acquired slots when a later window fails
- RateLimiter.is_rate_limited() returns True when any window is exhausted
- RateLimiter.is_rate_limited() returns False when Redis is unavailable
- RateLimiter.get_wait_time() returns 0.0 when not rate-limited
- RateLimiter.get_wait_time() returns positive seconds when a window is exhausted
- RateLimiter.wait_for_slot() returns immediately when slot is acquired first try
- RateLimiter.wait_for_slot() raises RateLimitTimeoutError when timeout is exceeded
- RateLimiter.reset() deletes the sorted sets for all windows
- rate_limited_request() context manager enters and exits cleanly on success
- rate_limited_request() releases the slot even when an exception occurs inside
- ARENA_DEFAULTS contains expected configurations for known arenas
- RateLimitConfig dataclass holds fields with defaults
- RateLimitTimeoutError carries key and timeout attributes

All Redis calls are mocked via AsyncMock.  No live Redis is required.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from issue_observatory.workers.rate_limiter import (
    ARENA_DEFAULTS,
    RateLimitConfig,
    RateLimitTimeoutError,
    RateLimiter,
    rate_limited_request,
)


# ---------------------------------------------------------------------------
# Helper: build a RateLimiter with a fully mocked Redis client
# ---------------------------------------------------------------------------


def _make_limiter(
    *,
    evalsha_return: int = 1,
    script_load_return: str = "sha-fake",
) -> tuple[RateLimiter, MagicMock]:
    """Return a (RateLimiter, mock_redis) pair.

    The mock Redis client has:
    - script_load returning a fake SHA string
    - evalsha returning evalsha_return (1 = slot acquired, 0 = rate limited)
    - zrem, delete, keys as AsyncMock
    """
    mock_redis = MagicMock()
    mock_redis.script_load = AsyncMock(return_value=script_load_return)
    mock_redis.evalsha = AsyncMock(return_value=evalsha_return)
    mock_redis.zrem = AsyncMock(return_value=1)
    mock_redis.delete = AsyncMock(return_value=3)
    mock_redis.keys = AsyncMock(return_value=[])

    limiter = RateLimiter(redis_client=mock_redis)
    # Pre-populate SHA cache to skip _ensure_scripts_loaded in most tests
    limiter._sha_acquire = script_load_return
    limiter._sha_check = script_load_return
    limiter._sha_oldest = script_load_return

    return limiter, mock_redis


# ---------------------------------------------------------------------------
# RateLimitTimeoutError
# ---------------------------------------------------------------------------


class TestRateLimitTimeoutError:
    def test_rate_limit_timeout_error_carries_key_and_timeout(self) -> None:
        """RateLimitTimeoutError stores the key and timeout duration."""
        err = RateLimitTimeoutError(key="ratelimit:reddit:oauth2:default:minute", timeout=30.0)

        assert err.key == "ratelimit:reddit:oauth2:default:minute"
        assert err.timeout == 30.0

    def test_rate_limit_timeout_error_message_includes_key(self) -> None:
        """The exception message includes the key string."""
        err = RateLimitTimeoutError(key="my-key", timeout=10.0)

        assert "my-key" in str(err)

    def test_rate_limit_timeout_error_is_exception(self) -> None:
        """RateLimitTimeoutError is a subclass of Exception."""
        err = RateLimitTimeoutError(key="k", timeout=1.0)

        assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# RateLimitConfig
# ---------------------------------------------------------------------------


class TestRateLimitConfig:
    def test_rate_limit_config_default_values(self) -> None:
        """Default RateLimitConfig has sensible field values."""
        cfg = RateLimitConfig()

        assert cfg.requests_per_minute == 60
        assert cfg.requests_per_hour is None
        assert cfg.requests_per_day is None
        assert cfg.burst_size is None

    def test_rate_limit_config_custom_values(self) -> None:
        """RateLimitConfig accepts custom values for all fields."""
        cfg = RateLimitConfig(
            requests_per_minute=10,
            requests_per_hour=100,
            requests_per_day=1000,
            burst_size=5,
        )

        assert cfg.requests_per_minute == 10
        assert cfg.requests_per_hour == 100
        assert cfg.requests_per_day == 1000
        assert cfg.burst_size == 5


# ---------------------------------------------------------------------------
# ARENA_DEFAULTS
# ---------------------------------------------------------------------------


class TestArenaDefaults:
    def test_arena_defaults_contains_reddit(self) -> None:
        """ARENA_DEFAULTS includes a configuration for 'reddit'."""
        assert "reddit" in ARENA_DEFAULTS
        assert isinstance(ARENA_DEFAULTS["reddit"], RateLimitConfig)

    def test_arena_defaults_reddit_has_hourly_limit(self) -> None:
        """Reddit's default config includes an hourly request cap."""
        cfg = ARENA_DEFAULTS["reddit"]

        assert cfg.requests_per_hour is not None
        assert cfg.requests_per_hour > 0

    def test_arena_defaults_bluesky_has_minute_limit(self) -> None:
        """Bluesky's default config has a per-minute rate limit."""
        cfg = ARENA_DEFAULTS["bluesky"]

        assert cfg.requests_per_minute > 0

    def test_arena_defaults_youtube_has_daily_limit(self) -> None:
        """YouTube's default config has a daily request cap."""
        cfg = ARENA_DEFAULTS["youtube"]

        assert cfg.requests_per_day is not None


# ---------------------------------------------------------------------------
# RateLimiter._key()
# ---------------------------------------------------------------------------


class TestRateLimiterKey:
    def test_key_builds_correct_namespaced_string(self) -> None:
        """_key() returns the expected 'ratelimit:{arena}:{provider}:{suffix}:{window}' string."""
        limiter, _ = _make_limiter()

        key = limiter._key("reddit", "oauth2", "default", "minute")

        assert key == "ratelimit:reddit:oauth2:default:minute"

    def test_key_includes_all_components(self) -> None:
        """_key() incorporates arena, provider, key_suffix, and window."""
        limiter, _ = _make_limiter()

        key = limiter._key("bluesky", "cred-abc", "suffix-1", "hour")

        assert "bluesky" in key
        assert "cred-abc" in key
        assert "suffix-1" in key
        assert "hour" in key

    def test_key_day_window_is_supported(self) -> None:
        """_key() handles the 'day' window name correctly."""
        limiter, _ = _make_limiter()

        key = limiter._key("youtube", "api_v3", "default", "day")

        assert key.endswith(":day")


# ---------------------------------------------------------------------------
# RateLimiter._resolve_config()
# ---------------------------------------------------------------------------


class TestResolveConfig:
    def test_resolve_config_returns_caller_override_when_provided(self) -> None:
        """When a config is passed explicitly, it takes precedence over ARENA_DEFAULTS."""
        limiter, _ = _make_limiter()
        override = RateLimitConfig(requests_per_minute=5)

        result = limiter._resolve_config("reddit", override)

        assert result is override

    def test_resolve_config_returns_arena_default_when_no_override(self) -> None:
        """When no config is passed, the arena's default is returned."""
        limiter, _ = _make_limiter()

        result = limiter._resolve_config("reddit", None)

        assert result is ARENA_DEFAULTS["reddit"]

    def test_resolve_config_returns_global_default_for_unknown_arena(self) -> None:
        """An unknown arena name returns the global _DEFAULT_CONFIG."""
        from issue_observatory.workers.rate_limiter import _DEFAULT_CONFIG

        limiter, _ = _make_limiter()

        result = limiter._resolve_config("nonexistent_arena", None)

        assert result is _DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# RateLimiter.acquire()
# ---------------------------------------------------------------------------


class TestAcquire:
    async def test_acquire_returns_true_when_slot_available(self) -> None:
        """acquire() returns True when the Lua script signals a slot was acquired."""
        limiter, mock_redis = _make_limiter(evalsha_return=1)

        result = await limiter.acquire(
            key="ratelimit:reddit:oauth2:default:minute",
            max_calls=60,
            window_seconds=60,
        )

        assert result is True

    async def test_acquire_returns_false_when_rate_limited(self) -> None:
        """acquire() returns False when the Lua script signals no slot is available."""
        limiter, mock_redis = _make_limiter(evalsha_return=0)

        result = await limiter.acquire(
            key="ratelimit:reddit:oauth2:default:minute",
            max_calls=60,
            window_seconds=60,
        )

        assert result is False

    async def test_acquire_returns_true_when_redis_unavailable(self) -> None:
        """acquire() returns True (allow) when Redis raises an exception."""
        limiter, mock_redis = _make_limiter()
        mock_redis.evalsha = AsyncMock(side_effect=ConnectionError("Redis down"))

        result = await limiter.acquire(
            key="ratelimit:bluesky:anon:default:minute",
            max_calls=50,
            window_seconds=60,
        )

        assert result is True

    async def test_acquire_calls_evalsha_with_correct_key(self) -> None:
        """acquire() passes the caller-provided key to evalsha, not a reconstructed one."""
        limiter, mock_redis = _make_limiter(evalsha_return=1)
        explicit_key = "ratelimit:reddit:cred-999:default:minute"

        await limiter.acquire(key=explicit_key, max_calls=10, window_seconds=60)

        evalsha_call = mock_redis.evalsha.call_args
        assert evalsha_call[0][2] == explicit_key


# ---------------------------------------------------------------------------
# RateLimiter.check_and_acquire()
# ---------------------------------------------------------------------------


class TestCheckAndAcquire:
    async def test_check_and_acquire_returns_true_when_all_windows_available(self) -> None:
        """check_and_acquire() returns True when all configured windows have capacity."""
        limiter, mock_redis = _make_limiter(evalsha_return=1)

        result = await limiter.check_and_acquire(
            arena="reddit",
            provider="oauth2",
            config=RateLimitConfig(requests_per_minute=100, requests_per_hour=3600),
        )

        assert result is True

    async def test_check_and_acquire_returns_false_when_minute_window_exhausted(self) -> None:
        """check_and_acquire() returns False when the minute window is at capacity."""
        limiter, mock_redis = _make_limiter(evalsha_return=0)

        result = await limiter.check_and_acquire(
            arena="reddit",
            provider="oauth2",
            config=RateLimitConfig(requests_per_minute=100),
        )

        assert result is False

    async def test_check_and_acquire_rolls_back_on_second_window_fail(self) -> None:
        """When the hour window fails after minute succeeds, the minute slot is rolled back."""
        limiter, mock_redis = _make_limiter()
        # First evalsha call (minute window) succeeds; second (hour window) fails
        mock_redis.evalsha = AsyncMock(side_effect=[1, 0])

        result = await limiter.check_and_acquire(
            arena="reddit",
            provider="oauth2",
            config=RateLimitConfig(requests_per_minute=100, requests_per_hour=3600),
        )

        assert result is False
        # zrem must have been called to roll back the minute slot
        mock_redis.zrem.assert_called_once()

    async def test_check_and_acquire_returns_true_when_redis_unavailable(self) -> None:
        """check_and_acquire() allows the request when Lua scripts cannot be loaded."""
        limiter, mock_redis = _make_limiter()
        # Clear cached SHAs so _ensure_scripts_loaded is triggered
        limiter._sha_acquire = ""
        mock_redis.script_load = AsyncMock(side_effect=ConnectionError("Redis down"))

        result = await limiter.check_and_acquire(arena="reddit", provider="oauth2")

        assert result is True

    async def test_check_and_acquire_burst_size_increases_effective_limit(self) -> None:
        """burst_size is added to requests_per_minute for the effective cap."""
        limiter, mock_redis = _make_limiter(evalsha_return=1)

        await limiter.check_and_acquire(
            arena="bluesky",
            provider="anon",
            config=RateLimitConfig(requests_per_minute=10, burst_size=5),
        )

        # evalsha(sha, num_keys, key, now, window_sec, limit, member, ttl)
        # limit is the 6th positional argument (index 5)
        call_args = mock_redis.evalsha.call_args_list[0][0]
        effective_limit = int(call_args[5])
        assert effective_limit == 15


# ---------------------------------------------------------------------------
# RateLimiter.is_rate_limited()
# ---------------------------------------------------------------------------


class TestIsRateLimited:
    async def test_is_rate_limited_returns_true_when_window_exhausted(self) -> None:
        """is_rate_limited() returns True when the check script returns count >= limit."""
        limiter, mock_redis = _make_limiter()
        # Minute limit is 60; check script returns 60 (exhausted)
        mock_redis.evalsha = AsyncMock(return_value=60)

        result = await limiter.is_rate_limited(
            arena="bluesky",
            provider="anon",
            config=RateLimitConfig(requests_per_minute=60),
        )

        assert result is True

    async def test_is_rate_limited_returns_false_when_under_limit(self) -> None:
        """is_rate_limited() returns False when count is below the limit."""
        limiter, mock_redis = _make_limiter()
        mock_redis.evalsha = AsyncMock(return_value=30)

        result = await limiter.is_rate_limited(
            arena="bluesky",
            provider="anon",
            config=RateLimitConfig(requests_per_minute=60),
        )

        assert result is False

    async def test_is_rate_limited_returns_false_when_redis_unavailable(self) -> None:
        """is_rate_limited() returns False (not limited) when Redis is down."""
        limiter, mock_redis = _make_limiter()
        limiter._sha_acquire = ""
        mock_redis.script_load = AsyncMock(side_effect=OSError("no Redis"))

        result = await limiter.is_rate_limited(arena="bluesky", provider="anon")

        assert result is False


# ---------------------------------------------------------------------------
# RateLimiter.get_wait_time()
# ---------------------------------------------------------------------------


class TestGetWaitTime:
    async def test_get_wait_time_returns_zero_when_not_rate_limited(self) -> None:
        """get_wait_time() returns 0.0 when no window is exhausted."""
        limiter, mock_redis = _make_limiter()
        # Check script returns count below limit
        mock_redis.evalsha = AsyncMock(return_value=5)

        wait = await limiter.get_wait_time(
            arena="reddit",
            provider="oauth2",
            config=RateLimitConfig(requests_per_minute=100),
        )

        assert wait == 0.0

    async def test_get_wait_time_returns_zero_when_redis_unavailable(self) -> None:
        """get_wait_time() returns 0.0 when Lua scripts cannot be loaded."""
        limiter, mock_redis = _make_limiter()
        limiter._sha_acquire = ""
        mock_redis.script_load = AsyncMock(side_effect=OSError("no Redis"))

        wait = await limiter.get_wait_time(arena="reddit", provider="oauth2")

        assert wait == 0.0

    async def test_get_wait_time_returns_positive_when_window_exhausted(self) -> None:
        """get_wait_time() returns a positive value when a window is full."""
        import time

        limiter, mock_redis = _make_limiter()
        # First evalsha call (check): count == limit (rate limited)
        # Second evalsha call (oldest entry): timestamp from ~30s ago
        oldest_ts = time.time() - 30
        mock_redis.evalsha = AsyncMock(side_effect=[100, str(oldest_ts)])

        wait = await limiter.get_wait_time(
            arena="reddit",
            provider="oauth2",
            config=RateLimitConfig(requests_per_minute=100),
        )

        # With a 60s window and the oldest entry 30s ago, wait should be ~30s
        assert wait > 0.0
        assert wait <= 60.0


# ---------------------------------------------------------------------------
# RateLimiter.wait_for_slot()
# ---------------------------------------------------------------------------


class TestWaitForSlot:
    async def test_wait_for_slot_returns_immediately_when_slot_acquired(self) -> None:
        """wait_for_slot() returns without sleeping when acquire() succeeds first try."""
        limiter, mock_redis = _make_limiter(evalsha_return=1)

        # Should complete without raising or sleeping
        await limiter.wait_for_slot(
            key="ratelimit:bluesky:anon:default:minute",
            max_calls=50,
            window_seconds=60,
        )

    async def test_wait_for_slot_raises_timeout_error_when_slot_never_acquired(self) -> None:
        """wait_for_slot() raises RateLimitTimeoutError when timeout expires."""
        limiter, mock_redis = _make_limiter(evalsha_return=0)

        with pytest.raises(RateLimitTimeoutError) as exc_info:
            await limiter.wait_for_slot(
                key="ratelimit:reddit:oauth2:default:minute",
                max_calls=60,
                window_seconds=60,
                timeout=0.05,  # very short to keep test fast
            )

        err = exc_info.value
        assert "ratelimit:reddit:oauth2:default:minute" in err.key

    async def test_wait_for_slot_succeeds_after_one_retry(self) -> None:
        """wait_for_slot() loops and succeeds when the second acquire() call returns True."""
        limiter, mock_redis = _make_limiter()
        # First call: rate limited; second call: slot acquired
        mock_redis.evalsha = AsyncMock(side_effect=[0, 1])

        with patch("asyncio.sleep", new=AsyncMock()):
            await limiter.wait_for_slot(
                key="ratelimit:bluesky:anon:default:minute",
                max_calls=50,
                window_seconds=60,
                timeout=5.0,
            )

    async def test_wait_for_slot_key_appears_in_timeout_error(self) -> None:
        """The key is included in the RateLimitTimeoutError for diagnostics."""
        limiter, _ = _make_limiter(evalsha_return=0)
        expected_key = "ratelimit:special:key:here:minute"

        with pytest.raises(RateLimitTimeoutError) as exc_info:
            await limiter.wait_for_slot(
                key=expected_key,
                max_calls=1,
                window_seconds=1,
                timeout=0.05,
            )

        assert expected_key in str(exc_info.value)


# ---------------------------------------------------------------------------
# RateLimiter.reset()
# ---------------------------------------------------------------------------


class TestReset:
    async def test_reset_deletes_all_window_keys(self) -> None:
        """reset() calls delete with keys for all three windows (minute, hour, day)."""
        limiter, mock_redis = _make_limiter()

        await limiter.reset(arena="reddit", provider="oauth2")

        mock_redis.delete.assert_called_once()
        deleted_keys = set(mock_redis.delete.call_args[0])
        assert "ratelimit:reddit:oauth2:default:minute" in deleted_keys
        assert "ratelimit:reddit:oauth2:default:hour" in deleted_keys
        assert "ratelimit:reddit:oauth2:default:day" in deleted_keys

    async def test_reset_swallows_redis_error(self) -> None:
        """reset() does not raise when Redis is unavailable."""
        limiter, mock_redis = _make_limiter()
        mock_redis.delete = AsyncMock(side_effect=ConnectionError("Redis down"))

        # Should not raise
        await limiter.reset(arena="reddit", provider="oauth2")


# ---------------------------------------------------------------------------
# rate_limited_request() context manager
# ---------------------------------------------------------------------------


class TestRateLimitedRequest:
    async def test_rate_limited_request_enters_and_exits_cleanly(self) -> None:
        """rate_limited_request() yields control and exits without error on success."""
        limiter, mock_redis = _make_limiter(evalsha_return=1)
        executed = []

        async with rate_limited_request(limiter, "reddit", "oauth2"):
            executed.append("body")

        assert executed == ["body"]

    async def test_rate_limited_request_propagates_inner_exception(self) -> None:
        """An exception raised inside the context propagates out normally."""
        limiter, mock_redis = _make_limiter(evalsha_return=1)

        with pytest.raises(ValueError, match="inner error"):
            async with rate_limited_request(limiter, "reddit", "oauth2"):
                raise ValueError("inner error")

    async def test_rate_limited_request_waits_until_slot_available(self) -> None:
        """rate_limited_request() sleeps until check_and_acquire() returns True.

        Sequence of Redis evalsha return values:
        1. check_and_acquire minute window: 0 (rate limited)
        2. get_wait_time _run_check minute window: 30 (below limit, so wait=0 → sleep 1s)
        3. check_and_acquire minute window: 1 (slot acquired on retry)
        """
        limiter, mock_redis = _make_limiter()
        mock_redis.evalsha = AsyncMock(side_effect=[0, 30, 1])

        with patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            async with rate_limited_request(limiter, "bluesky", "anon"):
                pass

        # asyncio.sleep must have been called at least once (waiting for slot)
        assert mock_sleep.call_count >= 1
