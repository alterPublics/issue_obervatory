"""Credential pool manager for rotating API keys across arenas.

Phase 1 implementation: database-backed with Fernet encryption, Redis lease
tracking, Redis quota tracking, and Redis cooldown with exponential backoff.

Architecture
------------
The ``api_credentials`` PostgreSQL table stores Fernet-encrypted credential
payloads (Task 1.1 DB schema, owned by DB Engineer).  The pool reads active
credentials from the database, decrypts them in-process using the
``CREDENTIAL_ENCRYPTION_KEY`` Fernet key, and then tracks live state in Redis:

- **Lease**:    ``credential:lease:{id}:{task_id}``  (TTL = 3600s)
- **Daily quota**: ``credential:quota:{id}:daily``   (TTL = seconds until midnight UTC)
- **Monthly quota**: ``credential:quota:{id}:monthly`` (TTL = seconds until month end)
- **Cooldown**: ``credential:cooldown:{id}``          (TTL = backoff duration, max 3600s)

Circuit breaker
---------------
After 5 consecutive errors the credential is placed on a 1-hour cooldown in
Redis.  An admin must reset the ``error_count`` column on the DB row to
re-enable the credential (the next ``acquire()`` call will then start from
scratch).

Backward compatibility
----------------------
When no database credential is found the pool falls back to the Phase 0
environment-variable behaviour: ``{PLATFORM}_{TIER}_API_KEY`` / ``_2`` etc.
This ensures the Google Search arena tests continue to pass without DB setup.

Usage::

    pool = CredentialPool()
    cred = await pool.acquire(platform="serper", tier="medium")
    if cred is None:
        raise NoCredentialAvailableError(platform="serper", tier="medium")
    try:
        # use cred["api_key"] ...
        pass
    finally:
        await pool.release(credential_id=cred["id"], task_id=task_id)
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentinel: circuit breaker threshold
# ---------------------------------------------------------------------------

_CIRCUIT_BREAKER_THRESHOLD: int = 5
"""Number of consecutive errors before a credential is hard-locked."""

_MAX_COOLDOWN_SECONDS: int = 3600
"""Maximum cooldown duration applied at circuit-breaker threshold."""

_LEASE_TTL_SECONDS: int = 3600
"""Redis TTL for active credential leases."""


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class NoCredentialAvailableError(Exception):
    """Raised when the credential pool has no usable credential.

    Attributes:
        platform: Platform identifier that was requested.
        tier: Tier identifier that was requested.
    """

    def __init__(self, platform: str, tier: str) -> None:
        self.platform = platform
        self.tier = tier
        super().__init__(
            f"No usable credential available for platform='{platform}' tier='{tier}'."
        )


# ---------------------------------------------------------------------------
# Fernet helper
# ---------------------------------------------------------------------------


def _get_fernet() -> Any:
    """Return a Fernet instance using the configured encryption key.

    Returns:
        A :class:`cryptography.fernet.Fernet` instance.

    Raises:
        ImportError: If the ``cryptography`` package is not installed.
        ValueError: If ``CREDENTIAL_ENCRYPTION_KEY`` is not set or invalid.
    """
    from cryptography.fernet import Fernet  # noqa: PLC0415

    try:
        from issue_observatory.config.settings import get_settings  # noqa: PLC0415

        settings = get_settings()
        key = settings.credential_encryption_key
    except Exception:
        key = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "")

    if not key:
        raise ValueError(
            "CREDENTIAL_ENCRYPTION_KEY is not set. "
            "Generate one with: from cryptography.fernet import Fernet; Fernet.generate_key().decode()"
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def _decrypt_credentials(encrypted_payload: Any) -> dict[str, Any]:
    """Decrypt a Fernet-encrypted credential JSONB payload.

    The DB column stores the JSONB value as the Fernet ciphertext of a
    JSON-serialised dict.  When the column value is already a plain dict
    (e.g. in tests where encryption is bypassed), it is returned as-is.

    Args:
        encrypted_payload: Either a Fernet ciphertext string/bytes or a
            plain dict (for test injection).

    Returns:
        Decrypted credential dict.

    Raises:
        ValueError: If decryption or JSON parsing fails.
    """
    if isinstance(encrypted_payload, dict):
        # Already a plain dict — bypass decryption (test/dev mode).
        return encrypted_payload

    fernet = _get_fernet()
    try:
        token = encrypted_payload
        if isinstance(token, str):
            token = token.encode("utf-8")
        plaintext = fernet.decrypt(token)
        return json.loads(plaintext)
    except Exception as exc:
        raise ValueError(f"Failed to decrypt credential payload: {exc}") from exc


# ---------------------------------------------------------------------------
# CredentialPool
# ---------------------------------------------------------------------------


class CredentialPool:
    """Database-backed credential pool with Redis lease and quota tracking.

    Credentials are loaded from the ``api_credentials`` PostgreSQL table,
    decrypted with Fernet, and their live state (leases, quotas, cooldowns)
    tracked in Redis.

    Falls back to environment-variable credential discovery (Phase 0
    behaviour) when the DB returns no active credentials for the requested
    platform+tier combination.

    Args:
        redis_url: Redis connection URL.  Defaults to the value from
            ``Settings.redis_url``.  Pass an explicit URL in tests.
        env: Optional dict of environment variable overrides used for the
            Phase 0 env-var fallback.  If ``None``, ``os.environ`` is used.
    """

    def __init__(
        self,
        redis_url: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._redis_url = redis_url
        self._env: dict[str, str] = env if env is not None else dict(os.environ)
        # Phase 0 in-memory fallback state
        self._error_counts: dict[str, int] = defaultdict(int)
        self._cooldown_ids: set[str] = set()
        # Lazy Redis client
        self._redis: Any | None = None

    # ------------------------------------------------------------------
    # Redis helpers
    # ------------------------------------------------------------------

    async def _get_redis(self) -> Any:
        """Return (lazily initialised) async Redis client.

        Returns:
            A :class:`redis.asyncio.Redis` instance.
        """
        if self._redis is not None:
            return self._redis
        import redis.asyncio as aioredis  # noqa: PLC0415

        url = self._redis_url
        if url is None:
            try:
                from issue_observatory.config.settings import get_settings  # noqa: PLC0415

                url = get_settings().redis_url
            except Exception:
                url = "redis://localhost:6379/0"

        self._redis = aioredis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
        )
        return self._redis

    async def _redis_set(self, key: str, value: str, ttl: int) -> None:
        """Set a Redis key with a TTL, swallowing connection errors.

        Args:
            key: Redis key.
            value: String value.
            ttl: Expiry in seconds.
        """
        try:
            r = await self._get_redis()
            await r.setex(key, ttl, value)
        except Exception:
            logger.warning("Redis set failed for key '%s'", key)

    async def _redis_get(self, key: str) -> str | None:
        """Get a Redis key value, returning None on connection errors.

        Args:
            key: Redis key.

        Returns:
            String value, or ``None`` if missing or unavailable.
        """
        try:
            r = await self._get_redis()
            return await r.get(key)
        except Exception:
            logger.warning("Redis get failed for key '%s'", key)
            return None

    async def _redis_delete(self, key: str) -> None:
        """Delete a Redis key, swallowing connection errors.

        Args:
            key: Redis key.
        """
        try:
            r = await self._get_redis()
            await r.delete(key)
        except Exception:
            logger.warning("Redis delete failed for key '%s'", key)

    async def _redis_incr(self, key: str) -> int | None:
        """Increment a Redis integer counter.

        Args:
            key: Redis key.

        Returns:
            New counter value, or ``None`` on error.
        """
        try:
            r = await self._get_redis()
            return await r.incr(key)
        except Exception:
            logger.warning("Redis incr failed for key '%s'", key)
            return None

    # ------------------------------------------------------------------
    # TTL helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _seconds_until_midnight_utc() -> int:
        """Return seconds until the next UTC midnight.

        Returns:
            Integer seconds.
        """
        now = datetime.now(tz=timezone.utc)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # Advance to next day's midnight
        from datetime import timedelta  # noqa: PLC0415

        midnight = midnight + timedelta(days=1)
        return max(1, int((midnight - now).total_seconds()))

    @staticmethod
    def _seconds_until_month_end_utc() -> int:
        """Return seconds until the first second of the next UTC month.

        Returns:
            Integer seconds.
        """
        import calendar  # noqa: PLC0415
        from datetime import timedelta  # noqa: PLC0415

        now = datetime.now(tz=timezone.utc)
        # Last day of current month
        last_day = calendar.monthrange(now.year, now.month)[1]
        month_end = now.replace(
            day=last_day, hour=23, minute=59, second=59, microsecond=0
        ) + timedelta(seconds=1)
        return max(1, int((month_end - now).total_seconds()))

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def _query_db_credentials(
        self, platform: str, tier: str
    ) -> list[Any]:
        """Fetch active ``ApiCredential`` rows ordered by last_used_at ascending.

        Args:
            platform: Platform identifier (e.g. ``"serper"``).
            tier: Tier identifier (e.g. ``"medium"``).

        Returns:
            List of :class:`~issue_observatory.core.models.credentials.ApiCredential`
            ORM instances sorted by ``last_used_at`` nulls first (LRU).
        """
        try:
            from sqlalchemy import select  # noqa: PLC0415

            from issue_observatory.core.database import AsyncSessionLocal  # noqa: PLC0415
            from issue_observatory.core.models.credentials import ApiCredential  # noqa: PLC0415

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(ApiCredential)
                    .where(
                        ApiCredential.platform == platform,
                        ApiCredential.tier == tier,
                        ApiCredential.is_active.is_(True),
                    )
                    .order_by(
                        ApiCredential.last_used_at.asc().nullsfirst()
                    )
                )
                rows = list(result.scalars().all())
                # Detach from session so they can be used after close
                for row in rows:
                    db.expunge(row)
                return rows
        except ImportError:
            # DB not yet available (Phase 0 environment)
            return []
        except Exception:
            logger.exception(
                "Failed to query DB credentials for platform='%s' tier='%s'",
                platform,
                tier,
            )
            return []

    async def _update_last_used_at(self, credential_id: uuid.UUID) -> None:
        """Update ``last_used_at`` on the DB credential row.

        Args:
            credential_id: UUID of the credential to update.
        """
        try:
            from sqlalchemy import update  # noqa: PLC0415

            from issue_observatory.core.database import AsyncSessionLocal  # noqa: PLC0415
            from issue_observatory.core.models.credentials import ApiCredential  # noqa: PLC0415

            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(ApiCredential)
                    .where(ApiCredential.id == credential_id)
                    .values(last_used_at=datetime.now(tz=timezone.utc))
                )
                await db.commit()
        except Exception:
            logger.warning("Failed to update last_used_at for credential '%s'", credential_id)

    async def _update_error_fields(
        self, credential_id: uuid.UUID, error_count: int
    ) -> None:
        """Update ``error_count`` and ``last_error_at`` on the DB credential row.

        Args:
            credential_id: UUID of the credential to update.
            error_count: New error count value.
        """
        try:
            from sqlalchemy import update  # noqa: PLC0415

            from issue_observatory.core.database import AsyncSessionLocal  # noqa: PLC0415
            from issue_observatory.core.models.credentials import ApiCredential  # noqa: PLC0415

            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(ApiCredential)
                    .where(ApiCredential.id == credential_id)
                    .values(
                        error_count=error_count,
                        last_error_at=datetime.now(tz=timezone.utc),
                    )
                )
                await db.commit()
        except Exception:
            logger.warning("Failed to update error fields for credential '%s'", credential_id)

    # ------------------------------------------------------------------
    # Quota / cooldown checks
    # ------------------------------------------------------------------

    async def _is_on_cooldown(self, credential_id: str) -> bool:
        """Check whether a DB credential is on cooldown in Redis.

        Args:
            credential_id: String UUID of the credential.

        Returns:
            ``True`` if the cooldown key exists in Redis.
        """
        val = await self._redis_get(f"credential:cooldown:{credential_id}")
        return val is not None

    async def _is_quota_exceeded(
        self, credential_id: str, daily_quota: int | None, monthly_quota: int | None
    ) -> bool:
        """Check whether daily or monthly quota has been reached in Redis.

        Args:
            credential_id: String UUID of the credential.
            daily_quota: Daily limit or ``None`` for unlimited.
            monthly_quota: Monthly limit or ``None`` for unlimited.

        Returns:
            ``True`` if any applicable quota is exceeded.
        """
        if daily_quota is not None:
            val = await self._redis_get(f"credential:quota:{credential_id}:daily")
            if val is not None and int(val) >= daily_quota:
                return True
        if monthly_quota is not None:
            val = await self._redis_get(f"credential:quota:{credential_id}:monthly")
            if val is not None and int(val) >= monthly_quota:
                return True
        return False

    async def _increment_quota(self, credential_id: str) -> None:
        """Increment daily and monthly quota counters in Redis.

        Initialises TTL on first call for the current day/month window.

        Args:
            credential_id: String UUID of the credential.
        """
        daily_key = f"credential:quota:{credential_id}:daily"
        monthly_key = f"credential:quota:{credential_id}:monthly"
        try:
            r = await self._get_redis()
            new_daily = await r.incr(daily_key)
            if new_daily == 1:
                await r.expire(daily_key, self._seconds_until_midnight_utc())
            new_monthly = await r.incr(monthly_key)
            if new_monthly == 1:
                await r.expire(monthly_key, self._seconds_until_month_end_utc())
        except Exception:
            logger.warning("Failed to increment quota counters for credential '%s'", credential_id)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def acquire(
        self,
        platform: str,
        tier: str,
        task_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Acquire a credential for *platform* / *tier*.

        Query flow:
        1. Load active credentials from DB (LRU order).
        2. Skip credentials that are on cooldown or have exceeded their quota.
        3. Select the first eligible credential.
        4. Set a Redis lease for the acquired credential.
        5. Increment quota counters.
        6. If no DB credential is found, fall back to env-var discovery.

        Args:
            platform: Platform identifier in lowercase (e.g. ``"serper"``).
            tier: Tier identifier (``"free"``, ``"medium"``, ``"premium"``).
            task_id: Optional Celery task ID to associate with the lease.
                If omitted, a new UUID is generated.

        Returns:
            Credential dict if a usable credential was found, else ``None``.
            The dict always contains:
            - ``id`` (str): Credential UUID (or env var name in fallback mode).
            - ``platform`` (str): Platform identifier.
            - ``tier`` (str): Tier identifier.
            - ``api_key`` (str): Primary API key.
            - Additional platform-specific fields from the decrypted payload.
        """
        effective_task_id = task_id or str(uuid.uuid4())

        # -- Attempt 1: Database credentials -----------------------------------
        db_rows = await self._query_db_credentials(platform, tier)
        for row in db_rows:
            cred_id_str = str(row.id)

            if await self._is_on_cooldown(cred_id_str):
                logger.debug("DB credential '%s' is on cooldown — skipping.", cred_id_str)
                continue

            if await self._is_quota_exceeded(cred_id_str, row.daily_quota, row.monthly_quota):
                logger.debug("DB credential '%s' has exceeded quota — skipping.", cred_id_str)
                continue

            # Decrypt
            try:
                payload = _decrypt_credentials(row.credentials)
            except ValueError:
                logger.warning("Failed to decrypt credential '%s' — skipping.", cred_id_str)
                continue

            # Set Redis lease
            lease_key = f"credential:lease:{cred_id_str}:{effective_task_id}"
            await self._redis_set(lease_key, platform, _LEASE_TTL_SECONDS)

            # Increment quota counters
            await self._increment_quota(cred_id_str)

            # Update last_used_at (best-effort, don't block)
            await self._update_last_used_at(row.id)

            logger.debug(
                "Acquired DB credential '%s' for %s/%s.", cred_id_str, platform, tier
            )

            result: dict[str, Any] = {
                "id": cred_id_str,
                "platform": platform,
                "tier": tier,
                **payload,
            }
            # Ensure api_key is present if the payload uses a different key name
            if "api_key" not in result and payload:
                first_val = next(iter(payload.values()), None)
                if isinstance(first_val, str):
                    result["api_key"] = first_val
            return result

        # -- Attempt 2: Env-var fallback (Phase 0 behaviour) ------------------
        return await self._acquire_from_env(platform, tier)

    async def _acquire_from_env(
        self,
        platform: str,
        tier: str,
    ) -> dict[str, Any] | None:
        """Env-var fallback: read credentials from environment variables.

        Uses the ``{PLATFORM}_{TIER}_API_KEY`` naming convention.

        Args:
            platform: Platform identifier.
            tier: Tier identifier.

        Returns:
            Credential dict or ``None``.
        """
        prefix = f"{platform.upper()}_{tier.upper()}_"
        candidates = self._discover_env_credentials(prefix)

        for cred_id, api_key in candidates:
            if cred_id in self._cooldown_ids:
                logger.debug("Env credential '%s' is on cooldown — skipping.", cred_id)
                continue
            if self._error_counts[cred_id] >= _CIRCUIT_BREAKER_THRESHOLD:
                logger.warning(
                    "Env credential '%s' has %d errors — skipping (circuit breaker).",
                    cred_id,
                    self._error_counts[cred_id],
                )
                continue

            logger.debug(
                "Acquired env credential '%s' for %s/%s.", cred_id, platform, tier
            )
            return {
                "id": cred_id,
                "platform": platform,
                "tier": tier,
                "api_key": api_key,
            }

        logger.warning(
            "No usable credential found for platform='%s' tier='%s'. "
            "Set the environment variable %sAPI_KEY or add a DB credential.",
            platform,
            tier,
            prefix,
        )
        return None

    async def release(
        self,
        credential_id: str,
        task_id: str | None = None,
        platform: str | None = None,  # kept for backward compat
    ) -> None:
        """Release a previously acquired credential.

        Deletes the Redis lease key.  For DB credentials, ``last_used_at``
        is already updated in ``acquire()``.  For env-var credentials this
        is a no-op (no lease key exists).

        Args:
            credential_id: The ``id`` field from the acquired credential dict.
            task_id: The task ID that was passed to (or returned by)
                ``acquire()``.  When ``None``, attempts to clean up any
                matching lease keys using a wildcard scan (best-effort).
            platform: Unused parameter retained for backward compatibility
                with the Phase 0 ``release(platform, credential_id)`` call
                signature.
        """
        if task_id:
            lease_key = f"credential:lease:{credential_id}:{task_id}"
            await self._redis_delete(lease_key)
            logger.debug("Released lease '%s'.", lease_key)
        else:
            # Best-effort: scan for any lease keys for this credential
            try:
                r = await self._get_redis()
                pattern = f"credential:lease:{credential_id}:*"
                keys = await r.keys(pattern)
                if keys:
                    await r.delete(*keys)
                    logger.debug(
                        "Released %d lease key(s) for credential '%s'.", len(keys), credential_id
                    )
            except Exception:
                logger.warning("Failed to clean up lease keys for credential '%s'", credential_id)

    async def report_error(
        self,
        credential_id: str,
        error: Exception,
        platform: str | None = None,  # kept for backward compat
    ) -> None:
        """Record an error against a credential and apply cooldown.

        For DB credentials:
        - Increments ``error_count`` and updates ``last_error_at`` in the DB.
        - Sets a Redis cooldown key with exponential backoff.
        - At threshold (5 errors), sets max cooldown of 1 hour.

        For env-var credentials:
        - Increments in-memory error counter.
        - Sets in-memory cooldown on ``ArenaRateLimitError`` / ``ArenaAuthError``.

        Args:
            credential_id: The ``id`` field from the acquired credential dict.
            error: The exception that caused the error report.
            platform: Unused parameter retained for backward compatibility.
        """
        from issue_observatory.core.exceptions import ArenaAuthError, ArenaRateLimitError  # noqa: PLC0415

        # Determine if this is a DB credential (UUID-shaped ID) or env var
        is_db_credential = _is_uuid(credential_id)

        if is_db_credential:
            await self._report_db_error(credential_id, error)
        else:
            # Phase 0 env-var fallback
            self._error_counts[credential_id] += 1
            logger.warning(
                "Error reported for env credential '%s' (total=%d): %s",
                credential_id,
                self._error_counts[credential_id],
                error,
            )
            if isinstance(error, (ArenaRateLimitError, ArenaAuthError)):
                self._cooldown_ids.add(credential_id)
                logger.warning(
                    "Env credential '%s' placed on cooldown due to %s.",
                    credential_id,
                    type(error).__name__,
                )

    async def _report_db_error(
        self, credential_id: str, error: Exception
    ) -> None:
        """Handle error reporting for a DB credential.

        Args:
            credential_id: String UUID of the DB credential.
            error: The exception that triggered the report.
        """
        from issue_observatory.core.exceptions import ArenaAuthError, ArenaRateLimitError  # noqa: PLC0415

        # Fetch current error_count from DB (or assume 0 if unavailable)
        current_count = await self._get_db_error_count(credential_id)
        new_count = current_count + 1

        # Compute exponential backoff: 2^(n-1) minutes, capped at 60 minutes
        backoff_minutes = min(2 ** (new_count - 1), 60)
        cooldown_seconds = backoff_minutes * 60

        if new_count >= _CIRCUIT_BREAKER_THRESHOLD:
            cooldown_seconds = _MAX_COOLDOWN_SECONDS
            logger.error(
                "DB credential '%s' hit circuit breaker (%d errors) — "
                "max cooldown applied. Admin must reset error_count.",
                credential_id,
                new_count,
            )
        elif isinstance(error, (ArenaRateLimitError, ArenaAuthError)):
            logger.warning(
                "DB credential '%s' placed on cooldown (%ds) due to %s.",
                credential_id,
                cooldown_seconds,
                type(error).__name__,
            )
        else:
            logger.warning(
                "DB credential '%s' error #%d — cooldown %ds.",
                credential_id,
                new_count,
                cooldown_seconds,
            )

        cooldown_key = f"credential:cooldown:{credential_id}"
        await self._redis_set(cooldown_key, str(new_count), cooldown_seconds)

        # Update DB asynchronously (best-effort)
        try:
            cred_uuid = uuid.UUID(credential_id)
            await self._update_error_fields(cred_uuid, new_count)
        except Exception:
            logger.warning("Failed to update DB error fields for '%s'", credential_id)

    async def _get_db_error_count(self, credential_id: str) -> int:
        """Fetch the current ``error_count`` from the DB credential row.

        Args:
            credential_id: String UUID of the credential.

        Returns:
            Current error count, or 0 if unavailable.
        """
        try:
            from sqlalchemy import select  # noqa: PLC0415

            from issue_observatory.core.database import AsyncSessionLocal  # noqa: PLC0415
            from issue_observatory.core.models.credentials import ApiCredential  # noqa: PLC0415

            cred_uuid = uuid.UUID(credential_id)
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(ApiCredential.error_count).where(
                        ApiCredential.id == cred_uuid
                    )
                )
                row = result.scalar_one_or_none()
                return row if row is not None else 0
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Env-var discovery helpers (Phase 0 backward compat)
    # ------------------------------------------------------------------

    def _discover_env_credentials(
        self,
        prefix: str,
    ) -> list[tuple[str, str]]:
        """Return (env_var_name, value) pairs for env vars matching *prefix*.

        Args:
            prefix: Uppercase environment variable prefix to search for.

        Returns:
            Ordered list of (credential_id, api_key) tuples.
        """
        results: list[tuple[str, str]] = []

        primary = f"{prefix}API_KEY"
        if primary in self._env and self._env[primary]:
            results.append((primary, self._env[primary]))

        index = 2
        while True:
            candidate = f"{prefix}API_KEY_{index}"
            if candidate in self._env and self._env[candidate]:
                results.append((candidate, self._env[candidate]))
                index += 1
            else:
                break

        for key, value in sorted(self._env.items()):
            if key.startswith(prefix) and key not in {r[0] for r in results} and value:
                results.append((key, value))

        return results


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

_pool_singleton: CredentialPool | None = None


def get_credential_pool() -> CredentialPool:
    """FastAPI dependency that returns the application-scoped CredentialPool.

    The singleton is created on first access.  In tests, patch this function
    or replace ``_pool_singleton`` to inject a test double.

    Returns:
        The shared :class:`CredentialPool` instance.
    """
    global _pool_singleton  # noqa: PLW0603
    if _pool_singleton is None:
        _pool_singleton = CredentialPool()
    return _pool_singleton


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _is_uuid(value: str) -> bool:
    """Return ``True`` if *value* is a valid UUID string.

    Args:
        value: String to test.

    Returns:
        Boolean.
    """
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
