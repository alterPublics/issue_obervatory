"""Unit tests for CredentialPool.

Tests cover:
- acquire() returning credentials from the env-var fallback path
- acquire() returning None when no credential exists
- acquire() skipping credentials that are on cooldown (in-memory)
- acquire() skipping credentials that have exceeded the circuit-breaker threshold
- release() deleting the Redis lease key
- report_error() incrementing the in-memory error counter
- report_error() placing a credential on cooldown for rate-limit / auth errors
- Circuit breaker: credential skipped after error_count >= 5
- _discover_env_credentials() picking up primary and numbered keys
- _is_on_cooldown() returning True/False based on Redis key presence
- _is_quota_exceeded() checking daily and monthly Redis counters
- _increment_quota() setting TTL on first call, incrementing on subsequent calls
- _decrypt_credentials() with plain dict (no-op) and Fernet-encrypted bytes
- _seconds_until_midnight_utc() always returning a positive integer
- _seconds_until_month_end_utc() always returning a positive integer
- get_credential_pool() returning a singleton CredentialPool
- _is_uuid() utility for valid and invalid strings
- Redis helper methods swallow connection errors gracefully
- NoCredentialAvailableError carries platform and tier attributes

All tests use mocked Redis (AsyncMock) and do NOT require a live database or
Redis instance.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from issue_observatory.core.credential_pool import (
    CredentialPool,
    NoCredentialAvailableError,
    _decrypt_credentials,
    _is_uuid,
    get_credential_pool,
)
from issue_observatory.core.exceptions import ArenaAuthError, ArenaRateLimitError


# ---------------------------------------------------------------------------
# Helper: build a pool with Redis pre-wired via an AsyncMock
# ---------------------------------------------------------------------------


def _make_pool_with_mock_redis(
    *,
    env: dict[str, str] | None = None,
    redis_get_return: str | None = None,
) -> tuple[CredentialPool, MagicMock]:
    """Return a (CredentialPool, mock_redis) pair.

    The pool's internal ``_redis`` is set directly to an AsyncMock so that
    no actual Redis connection is made.
    """
    pool = CredentialPool(redis_url="redis://mock:6379/0", env=env or {})

    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=redis_get_return)
    mock_redis.setex = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock(return_value=1)
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock(return_value=True)
    mock_redis.keys = AsyncMock(return_value=[])

    pool._redis = mock_redis
    return pool, mock_redis


# ---------------------------------------------------------------------------
# NoCredentialAvailableError
# ---------------------------------------------------------------------------


class TestNoCredentialAvailableError:
    def test_no_credential_error_carries_platform_and_tier(self) -> None:
        """NoCredentialAvailableError stores platform and tier for diagnostics."""
        err = NoCredentialAvailableError(platform="serper", tier="medium")

        assert err.platform == "serper"
        assert err.tier == "medium"

    def test_no_credential_error_message_includes_platform_and_tier(self) -> None:
        """The exception message includes both platform and tier strings."""
        err = NoCredentialAvailableError(platform="reddit", tier="free")

        assert "reddit" in str(err)
        assert "free" in str(err)

    def test_no_credential_error_is_exception(self) -> None:
        """NoCredentialAvailableError is a subclass of Exception."""
        err = NoCredentialAvailableError(platform="x", tier="premium")

        assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# _is_uuid utility
# ---------------------------------------------------------------------------


class TestIsUuid:
    def test_is_uuid_returns_true_for_valid_uuid(self) -> None:
        """A properly formatted UUID string is recognised."""
        assert _is_uuid(str(uuid.uuid4())) is True

    def test_is_uuid_returns_false_for_env_var_name(self) -> None:
        """An environment variable name like 'SERPER_MEDIUM_API_KEY' is not a UUID."""
        assert _is_uuid("SERPER_MEDIUM_API_KEY") is False

    def test_is_uuid_returns_false_for_empty_string(self) -> None:
        """An empty string is not a UUID."""
        assert _is_uuid("") is False

    def test_is_uuid_returns_false_for_arbitrary_string(self) -> None:
        """Random text does not parse as UUID."""
        assert _is_uuid("not-a-uuid-at-all") is False


# ---------------------------------------------------------------------------
# _decrypt_credentials
# ---------------------------------------------------------------------------


class TestDecryptCredentials:
    def test_decrypt_credentials_with_plain_dict_returns_as_is(self) -> None:
        """When the payload is already a dict (test mode), it is returned unchanged."""
        payload = {"api_key": "secret123", "extra_field": "value"}

        result = _decrypt_credentials(payload)

        assert result == payload

    def test_decrypt_credentials_with_encrypted_bytes_decrypts_correctly(self) -> None:
        """Fernet-encrypted JSON bytes are decrypted and parsed back to a dict."""
        import json

        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        f = Fernet(key)
        original = {"api_key": "my-secret-api-key"}
        ciphertext = f.encrypt(json.dumps(original).encode())

        with patch(
            "issue_observatory.core.credential_pool._get_fernet",
            return_value=f,
        ):
            result = _decrypt_credentials(ciphertext)

        assert result == original

    def test_decrypt_credentials_with_invalid_ciphertext_raises_value_error(self) -> None:
        """Tampered or random bytes raise ValueError with an informative message."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        f = Fernet(key)

        with patch(
            "issue_observatory.core.credential_pool._get_fernet",
            return_value=f,
        ):
            with pytest.raises(ValueError, match="Failed to decrypt"):
                _decrypt_credentials(b"this-is-not-valid-fernet-ciphertext")

    def test_decrypt_credentials_with_string_ciphertext_is_supported(self) -> None:
        """A string ciphertext (not bytes) is also decrypted correctly."""
        import json

        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        f = Fernet(key)
        original = {"api_key": "string-path-key"}
        ciphertext_bytes = f.encrypt(json.dumps(original).encode())
        # Pass as a decoded string instead of bytes
        ciphertext_str = ciphertext_bytes.decode("utf-8")

        with patch(
            "issue_observatory.core.credential_pool._get_fernet",
            return_value=f,
        ):
            result = _decrypt_credentials(ciphertext_str)

        assert result == original


# ---------------------------------------------------------------------------
# _discover_env_credentials
# ---------------------------------------------------------------------------


class TestDiscoverEnvCredentials:
    def test_discover_env_credentials_finds_primary_key(self) -> None:
        """Primary key ``{PREFIX}API_KEY`` is discovered first."""
        env = {"SERPER_MEDIUM_API_KEY": "key-primary"}
        pool = CredentialPool(env=env)

        results = pool._discover_env_credentials("SERPER_MEDIUM_")

        assert ("SERPER_MEDIUM_API_KEY", "key-primary") in results

    def test_discover_env_credentials_finds_numbered_keys(self) -> None:
        """Numbered keys ``{PREFIX}API_KEY_2``, ``_3`` etc. are discovered in order."""
        env = {
            "SERPER_MEDIUM_API_KEY": "key-1",
            "SERPER_MEDIUM_API_KEY_2": "key-2",
            "SERPER_MEDIUM_API_KEY_3": "key-3",
        }
        pool = CredentialPool(env=env)

        results = pool._discover_env_credentials("SERPER_MEDIUM_")
        ids = [r[0] for r in results]

        assert "SERPER_MEDIUM_API_KEY" in ids
        assert "SERPER_MEDIUM_API_KEY_2" in ids
        assert "SERPER_MEDIUM_API_KEY_3" in ids

    def test_discover_env_credentials_skips_empty_values(self) -> None:
        """Environment variables with empty string values are not returned."""
        env = {"SERPER_MEDIUM_API_KEY": ""}
        pool = CredentialPool(env=env)

        results = pool._discover_env_credentials("SERPER_MEDIUM_")

        assert results == []

    def test_discover_env_credentials_ignores_unrelated_prefix(self) -> None:
        """Only variables matching the given prefix are returned."""
        env = {
            "SERPER_MEDIUM_API_KEY": "key-1",
            "REDDIT_MEDIUM_API_KEY": "reddit-key",
        }
        pool = CredentialPool(env=env)

        results = pool._discover_env_credentials("SERPER_MEDIUM_")
        ids = [r[0] for r in results]

        assert "REDDIT_MEDIUM_API_KEY" not in ids
        assert "SERPER_MEDIUM_API_KEY" in ids


# ---------------------------------------------------------------------------
# acquire() — env-var fallback path (no DB)
# ---------------------------------------------------------------------------


class TestAcquireEnvFallback:
    async def test_acquire_returns_credential_dict_when_env_var_present(self) -> None:
        """acquire() returns a dict with id, platform, tier, api_key from env vars."""
        env = {"SERPER_MEDIUM_API_KEY": "my-api-key-value"}
        pool, _ = _make_pool_with_mock_redis(env=env)

        # Patch out the DB query so it returns no DB rows
        with patch.object(pool, "_query_db_credentials", return_value=[]):
            result = await pool.acquire(platform="serper", tier="medium")

        assert result is not None
        assert result["platform"] == "serper"
        assert result["tier"] == "medium"
        assert result["api_key"] == "my-api-key-value"
        assert "id" in result

    async def test_acquire_uses_mapped_env_var_over_generic_pattern(self) -> None:
        """acquire() prefers _PLATFORM_ENV_MAP entries over the generic {PLATFORM}_{TIER}_API_KEY pattern."""
        env = {"SERPER_API_KEY": "mapped-key-value"}
        pool, _ = _make_pool_with_mock_redis(env=env)

        with patch.object(pool, "_query_db_credentials", return_value=[]):
            result = await pool.acquire(platform="serper", tier="medium")

        assert result is not None
        assert result["platform"] == "serper"
        assert result["tier"] == "medium"
        assert result["api_key"] == "mapped-key-value"
        # The credential ID should be the mapped form, not the generic env var name
        assert result["id"] == "env:serper:medium"

    async def test_acquire_maps_multi_field_credentials_from_env(self) -> None:
        """acquire() assembles multi-field credentials from the _PLATFORM_ENV_MAP mapping."""
        env = {
            "REDDIT_CLIENT_ID": "test-client-id",
            "REDDIT_CLIENT_SECRET": "test-client-secret",
            "REDDIT_USER_AGENT": "TestBot/1.0",
        }
        pool, _ = _make_pool_with_mock_redis(env=env)

        with patch.object(pool, "_query_db_credentials", return_value=[]):
            result = await pool.acquire(platform="reddit", tier="free")

        assert result is not None
        assert result["platform"] == "reddit"
        assert result["tier"] == "free"
        assert result["client_id"] == "test-client-id"
        assert result["client_secret"] == "test-client-secret"
        assert result["user_agent"] == "TestBot/1.0"
        # Ensure api_key is present for backward compatibility (takes first value)
        assert "api_key" in result
        assert result["api_key"] == "test-client-id"

    async def test_acquire_returns_none_when_no_env_var_and_no_db(self) -> None:
        """acquire() returns None when no credential is available from any source."""
        pool, _ = _make_pool_with_mock_redis(env={})

        with patch.object(pool, "_query_db_credentials", return_value=[]):
            result = await pool.acquire(platform="serper", tier="medium")

        assert result is None

    async def test_acquire_skips_env_credential_on_cooldown(self) -> None:
        """A credential in the in-memory cooldown set is not returned by acquire()."""
        env = {"SERPER_MEDIUM_API_KEY": "key-on-cooldown"}
        pool, _ = _make_pool_with_mock_redis(env=env)
        cred_id = "SERPER_MEDIUM_API_KEY"
        pool._cooldown_ids.add(cred_id)

        with patch.object(pool, "_query_db_credentials", return_value=[]):
            result = await pool.acquire(platform="serper", tier="medium")

        assert result is None

    async def test_acquire_skips_env_credential_past_circuit_breaker_threshold(self) -> None:
        """acquire() skips a credential whose in-memory error count is at/above 5."""
        env = {"SERPER_MEDIUM_API_KEY": "key-with-errors"}
        pool, _ = _make_pool_with_mock_redis(env=env)
        cred_id = "SERPER_MEDIUM_API_KEY"
        pool._error_counts[cred_id] = 5  # at threshold

        with patch.object(pool, "_query_db_credentials", return_value=[]):
            result = await pool.acquire(platform="serper", tier="medium")

        assert result is None

    async def test_acquire_returns_first_healthy_credential_from_multiple(self) -> None:
        """When one credential is on cooldown, the next healthy one is returned."""
        env = {
            "SERPER_MEDIUM_API_KEY": "key-on-cooldown",
            "SERPER_MEDIUM_API_KEY_2": "key-healthy",
        }
        pool, _ = _make_pool_with_mock_redis(env=env)
        pool._cooldown_ids.add("SERPER_MEDIUM_API_KEY")

        with patch.object(pool, "_query_db_credentials", return_value=[]):
            result = await pool.acquire(platform="serper", tier="medium")

        assert result is not None
        assert result["api_key"] == "key-healthy"

    async def test_acquire_uses_supplied_task_id_in_result(self) -> None:
        """When a task_id is provided to acquire(), it is honoured (no UUID generation)."""
        env = {"SERPER_MEDIUM_API_KEY": "key-value"}
        pool, _ = _make_pool_with_mock_redis(env=env)

        with patch.object(pool, "_query_db_credentials", return_value=[]):
            result = await pool.acquire(
                platform="serper", tier="medium", task_id="celery-task-abc"
            )

        # The credential dict does not embed task_id, but acquire() must not raise
        assert result is not None

    async def test_acquire_with_db_credential_sets_redis_lease(self) -> None:
        """When a DB credential is acquired, a Redis lease key is set."""
        cred_id = uuid.uuid4()
        mock_row = MagicMock()
        mock_row.id = cred_id
        mock_row.credentials = {"api_key": "db-api-key"}
        mock_row.daily_quota = None
        mock_row.monthly_quota = None

        pool, mock_redis = _make_pool_with_mock_redis()
        # Redis returns None for cooldown/quota keys (not on cooldown, no quota exceeded)
        mock_redis.get = AsyncMock(return_value=None)

        with (
            patch.object(pool, "_query_db_credentials", return_value=[mock_row]),
            patch.object(pool, "_update_last_used_at", new=AsyncMock()),
            patch.object(pool, "_increment_quota", new=AsyncMock()),
        ):
            result = await pool.acquire(platform="serper", tier="medium", task_id="task-1")

        assert result is not None
        assert result["platform"] == "serper"
        assert result["api_key"] == "db-api-key"
        # Lease key must have been set
        mock_redis.setex.assert_called_once()
        lease_key_arg = mock_redis.setex.call_args[0][0]
        assert f"credential:lease:{cred_id}" in lease_key_arg

    async def test_acquire_skips_db_credential_on_cooldown(self) -> None:
        """A DB credential with an active Redis cooldown key is skipped."""
        cred_id = uuid.uuid4()
        mock_row = MagicMock()
        mock_row.id = cred_id
        mock_row.credentials = {"api_key": "key"}
        mock_row.daily_quota = None
        mock_row.monthly_quota = None

        # Redis returns a cooldown marker
        pool, mock_redis = _make_pool_with_mock_redis()
        mock_redis.get = AsyncMock(return_value="1")  # cooldown key exists

        with (
            patch.object(pool, "_query_db_credentials", return_value=[mock_row]),
            patch.object(pool, "_acquire_from_env", new=AsyncMock(return_value=None)),
        ):
            result = await pool.acquire(platform="serper", tier="medium")

        assert result is None


# ---------------------------------------------------------------------------
# release()
# ---------------------------------------------------------------------------


class TestRelease:
    async def test_release_with_task_id_deletes_lease_key(self) -> None:
        """release() with a task_id deletes the specific lease key."""
        cred_id = str(uuid.uuid4())
        task_id = "task-xyz"
        pool, mock_redis = _make_pool_with_mock_redis()

        await pool.release(credential_id=cred_id, task_id=task_id)

        expected_key = f"credential:lease:{cred_id}:{task_id}"
        mock_redis.delete.assert_called_once_with(expected_key)

    async def test_release_without_task_id_scans_for_lease_keys(self) -> None:
        """release() without task_id uses a wildcard scan to find lease keys."""
        cred_id = str(uuid.uuid4())
        pool, mock_redis = _make_pool_with_mock_redis()
        mock_redis.keys = AsyncMock(return_value=[f"credential:lease:{cred_id}:task1"])

        await pool.release(credential_id=cred_id)

        mock_redis.keys.assert_called_once()
        pattern_arg = mock_redis.keys.call_args[0][0]
        assert cred_id in pattern_arg

    async def test_release_swallows_redis_error_gracefully(self) -> None:
        """release() does not raise even when Redis is unavailable."""
        pool = CredentialPool(redis_url="redis://unavailable:6379/0")
        # _redis is None; _get_redis will raise because the URL is not reachable.
        # We simulate the connection failure by making _get_redis raise.
        with patch.object(pool, "_get_redis", side_effect=ConnectionError("down")):
            # Should not raise
            await pool.release(credential_id=str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# report_error() — env-var path
# ---------------------------------------------------------------------------


class TestReportErrorEnvPath:
    async def test_report_error_increments_env_error_count(self) -> None:
        """report_error() increments the in-memory error_count for env credentials."""
        env = {"SERPER_MEDIUM_API_KEY": "key"}
        pool, _ = _make_pool_with_mock_redis(env=env)
        cred_id = "SERPER_MEDIUM_API_KEY"

        await pool.report_error(cred_id, error=RuntimeError("upstream error"))

        assert pool._error_counts[cred_id] == 1

    async def test_report_error_multiple_times_accumulates_count(self) -> None:
        """Repeated report_error() calls accumulate the error count."""
        env = {"REDDIT_FREE_API_KEY": "key"}
        pool, _ = _make_pool_with_mock_redis(env=env)
        cred_id = "REDDIT_FREE_API_KEY"

        await pool.report_error(cred_id, error=RuntimeError("err"))
        await pool.report_error(cred_id, error=RuntimeError("err"))
        await pool.report_error(cred_id, error=RuntimeError("err"))

        assert pool._error_counts[cred_id] == 3

    async def test_report_error_rate_limit_error_adds_to_cooldown(self) -> None:
        """ArenaRateLimitError causes the env credential to be placed on cooldown."""
        env = {"SERPER_MEDIUM_API_KEY": "key"}
        pool, _ = _make_pool_with_mock_redis(env=env)
        cred_id = "SERPER_MEDIUM_API_KEY"

        await pool.report_error(
            cred_id, error=ArenaRateLimitError("rate limited", arena="serper")
        )

        assert cred_id in pool._cooldown_ids

    async def test_report_error_auth_error_adds_to_cooldown(self) -> None:
        """ArenaAuthError causes the env credential to be placed on cooldown."""
        env = {"SERPER_MEDIUM_API_KEY": "key"}
        pool, _ = _make_pool_with_mock_redis(env=env)
        cred_id = "SERPER_MEDIUM_API_KEY"

        await pool.report_error(
            cred_id, error=ArenaAuthError("auth failed", arena="serper")
        )

        assert cred_id in pool._cooldown_ids

    async def test_report_error_generic_error_does_not_add_to_cooldown(self) -> None:
        """A generic RuntimeError does not place the env credential on cooldown."""
        env = {"SERPER_MEDIUM_API_KEY": "key"}
        pool, _ = _make_pool_with_mock_redis(env=env)
        cred_id = "SERPER_MEDIUM_API_KEY"

        await pool.report_error(cred_id, error=RuntimeError("some other error"))

        assert cred_id not in pool._cooldown_ids

    async def test_circuit_breaker_blocks_acquisition_after_five_errors(self) -> None:
        """After 5 report_error() calls the credential cannot be acquired."""
        env = {"SERPER_MEDIUM_API_KEY": "key"}
        pool, _ = _make_pool_with_mock_redis(env=env)
        cred_id = "SERPER_MEDIUM_API_KEY"

        for _ in range(5):
            await pool.report_error(cred_id, error=RuntimeError("err"))

        with patch.object(pool, "_query_db_credentials", return_value=[]):
            result = await pool.acquire(platform="serper", tier="medium")

        assert result is None


# ---------------------------------------------------------------------------
# report_error() — DB credential path (UUID-shaped ID)
# ---------------------------------------------------------------------------


class TestReportErrorDbPath:
    async def test_report_error_db_credential_sets_redis_cooldown_key(self) -> None:
        """report_error() for a UUID credential sets a Redis cooldown key."""
        cred_id = str(uuid.uuid4())
        pool, mock_redis = _make_pool_with_mock_redis()

        with (
            patch.object(pool, "_get_db_error_count", new=AsyncMock(return_value=0)),
            patch.object(pool, "_update_error_fields", new=AsyncMock()),
        ):
            await pool.report_error(cred_id, error=RuntimeError("upstream failure"))

        # setex must have been called with the cooldown key
        mock_redis.setex.assert_called()
        cooldown_key = f"credential:cooldown:{cred_id}"
        call_args_list = mock_redis.setex.call_args_list
        keys_set = [call[0][0] for call in call_args_list]
        assert any(cooldown_key in k for k in keys_set)

    async def test_report_error_db_credential_at_threshold_uses_max_cooldown(self) -> None:
        """At error count >= 5, the Redis cooldown TTL is set to 3600 seconds."""
        cred_id = str(uuid.uuid4())
        pool, mock_redis = _make_pool_with_mock_redis()

        # Current count is 4; after increment it becomes 5 (threshold)
        with (
            patch.object(pool, "_get_db_error_count", new=AsyncMock(return_value=4)),
            patch.object(pool, "_update_error_fields", new=AsyncMock()),
        ):
            await pool.report_error(cred_id, error=RuntimeError("final error"))

        # Find the setex call for the cooldown key
        cooldown_key = f"credential:cooldown:{cred_id}"
        for call in mock_redis.setex.call_args_list:
            args = call[0]
            if args[0] == cooldown_key:
                # TTL must be the max cooldown
                assert args[1] == 3600
                break


# ---------------------------------------------------------------------------
# Redis helpers: _is_on_cooldown, _is_quota_exceeded, _increment_quota
# ---------------------------------------------------------------------------


class TestRedisHelpers:
    async def test_is_on_cooldown_returns_true_when_key_exists(self) -> None:
        """_is_on_cooldown() returns True when Redis has a value for the key."""
        pool, mock_redis = _make_pool_with_mock_redis(redis_get_return="1")

        result = await pool._is_on_cooldown("some-cred-id")

        assert result is True

    async def test_is_on_cooldown_returns_false_when_key_absent(self) -> None:
        """_is_on_cooldown() returns False when Redis has no value for the key."""
        pool, mock_redis = _make_pool_with_mock_redis(redis_get_return=None)

        result = await pool._is_on_cooldown("some-cred-id")

        assert result is False

    async def test_is_quota_exceeded_daily_limit_reached(self) -> None:
        """_is_quota_exceeded() returns True when the daily counter equals the limit."""
        pool, mock_redis = _make_pool_with_mock_redis(redis_get_return="100")

        result = await pool._is_quota_exceeded("cred-id", daily_quota=100, monthly_quota=None)

        assert result is True

    async def test_is_quota_exceeded_daily_limit_not_reached(self) -> None:
        """_is_quota_exceeded() returns False when the daily counter is below the limit."""
        pool, mock_redis = _make_pool_with_mock_redis(redis_get_return="99")

        result = await pool._is_quota_exceeded("cred-id", daily_quota=100, monthly_quota=None)

        assert result is False

    async def test_is_quota_exceeded_monthly_limit_reached(self) -> None:
        """_is_quota_exceeded() returns True when the monthly counter reaches the limit.

        daily_quota is None so the daily Redis check is skipped entirely.
        Only one Redis get call is made, for the monthly key.
        """
        pool, mock_redis = _make_pool_with_mock_redis()
        # Only the monthly key is fetched (daily check is skipped when daily_quota=None)
        mock_redis.get = AsyncMock(return_value="5000")

        result = await pool._is_quota_exceeded("cred-id", daily_quota=None, monthly_quota=5000)

        assert result is True

    async def test_is_quota_exceeded_no_limits_returns_false(self) -> None:
        """_is_quota_exceeded() returns False when both limits are None (unlimited)."""
        pool, mock_redis = _make_pool_with_mock_redis()

        result = await pool._is_quota_exceeded("cred-id", daily_quota=None, monthly_quota=None)

        assert result is False

    async def test_increment_quota_sets_expiry_on_first_call(self) -> None:
        """_increment_quota() sets an expiry on the daily key the first time it is created."""
        pool, mock_redis = _make_pool_with_mock_redis()
        # incr returns 1 (first call) for both daily and monthly
        mock_redis.incr = AsyncMock(return_value=1)

        await pool._increment_quota("cred-id")

        # expire must be called twice (once for daily, once for monthly)
        assert mock_redis.expire.call_count == 2

    async def test_increment_quota_does_not_reset_expiry_on_subsequent_calls(self) -> None:
        """_increment_quota() does not re-set TTL when counter is already > 1."""
        pool, mock_redis = _make_pool_with_mock_redis()
        # incr returns > 1 (not first call)
        mock_redis.incr = AsyncMock(return_value=5)

        await pool._increment_quota("cred-id")

        # expire should NOT have been called
        mock_redis.expire.assert_not_called()


# ---------------------------------------------------------------------------
# TTL helpers
# ---------------------------------------------------------------------------


class TestTtlHelpers:
    def test_seconds_until_midnight_utc_is_positive(self) -> None:
        """_seconds_until_midnight_utc() always returns a positive integer."""
        result = CredentialPool._seconds_until_midnight_utc()

        assert isinstance(result, int)
        assert result > 0

    def test_seconds_until_midnight_utc_is_at_most_one_day(self) -> None:
        """The value is never more than 86400 seconds (one full day)."""
        result = CredentialPool._seconds_until_midnight_utc()

        assert result <= 86400

    def test_seconds_until_month_end_utc_is_positive(self) -> None:
        """_seconds_until_month_end_utc() always returns a positive integer."""
        result = CredentialPool._seconds_until_month_end_utc()

        assert isinstance(result, int)
        assert result > 0

    def test_seconds_until_month_end_utc_is_at_most_31_days(self) -> None:
        """The value is never more than 31 days worth of seconds."""
        result = CredentialPool._seconds_until_month_end_utc()

        assert result <= 31 * 86400


# ---------------------------------------------------------------------------
# get_credential_pool singleton
# ---------------------------------------------------------------------------


class TestGetCredentialPool:
    def test_get_credential_pool_returns_credential_pool_instance(self) -> None:
        """get_credential_pool() returns a CredentialPool object."""
        import issue_observatory.core.credential_pool as cp_module

        # Reset the singleton to ensure a fresh instance
        original = cp_module._pool_singleton
        cp_module._pool_singleton = None
        try:
            pool = get_credential_pool()
            assert isinstance(pool, CredentialPool)
        finally:
            cp_module._pool_singleton = original

    def test_get_credential_pool_returns_same_instance_on_repeated_calls(self) -> None:
        """get_credential_pool() returns the same singleton on every call."""
        import issue_observatory.core.credential_pool as cp_module

        original = cp_module._pool_singleton
        cp_module._pool_singleton = None
        try:
            pool_1 = get_credential_pool()
            pool_2 = get_credential_pool()
            assert pool_1 is pool_2
        finally:
            cp_module._pool_singleton = original
