"""Auto-populate credential pool from environment variables on startup.

This module bridges the gap between `.env` configuration and the database-backed
credential pool. On application startup, it checks for credentials in environment
variables and automatically inserts them into the `api_credentials` table if they
don't already exist.

This prevents the cryptic "no credential available" errors that occur when a
researcher configures API keys in `.env` but does not manually enter them via
the admin UI.

Usage::

    # In api/main.py startup event:
    from issue_observatory.core.credential_bootstrap import bootstrap_credentials_from_env

    @app.on_event("startup")
    async def on_startup():
        await bootstrap_credentials_from_env()
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Environment variable mapping
# ---------------------------------------------------------------------------

# Maps (platform, tier) to {credential_field: env_var_name}.
# This MUST stay in sync with credential_pool._PLATFORM_ENV_MAP.
_ENV_CREDENTIAL_MAP: dict[tuple[str, str], dict[str, str]] = {
    ("serper", "medium"): {"api_key": "SERPER_API_KEY"},
    ("serpapi", "premium"): {"api_key": "SERPAPI_API_KEY"},
    ("youtube", "free"): {"api_key": "YOUTUBE_API_KEY"},
    ("reddit", "free"): {
        "client_id": "REDDIT_CLIENT_ID",
        "client_secret": "REDDIT_CLIENT_SECRET",
        "user_agent": "REDDIT_USER_AGENT",
    },
    ("tiktok", "free"): {
        "client_key": "TIKTOK_CLIENT_KEY",
        "client_secret": "TIKTOK_CLIENT_SECRET",
    },
    ("telegram", "free"): {
        "api_id": "TELEGRAM_API_ID",
        "api_hash": "TELEGRAM_API_HASH",
        "session_string": "TELEGRAM_SESSION_STRING",
    },
    ("bluesky", "free"): {
        "handle": "BLUESKY_HANDLE",
        "app_password": "BLUESKY_APP_PASSWORD",
    },
    ("event_registry", "medium"): {"api_key": "EVENT_REGISTRY_API_KEY"},
    ("event_registry", "premium"): {"api_key": "EVENT_REGISTRY_API_KEY"},
    ("twitterapi_io", "medium"): {"api_key": "TWITTERAPIIO_API_KEY"},
    ("x_twitter", "premium"): {
        "bearer_token": "X_BEARER_TOKEN",
        "api_key": "X_API_KEY",
        "api_secret": "X_API_SECRET",
    },
    ("discord", "free"): {"bot_token": "DISCORD_BOT_TOKEN"},
    ("openrouter", "medium"): {"api_key": "OPENROUTER_API_KEY"},
    ("openrouter", "premium"): {"api_key": "OPENROUTER_API_KEY"},
    ("gab", "free"): {"access_token": "GAB_ACCESS_TOKEN"},
    ("threads", "free"): {"access_token": "THREADS_ACCESS_TOKEN"},
    ("brightdata_facebook", "medium"): {"api_token": "BRIGHTDATA_FACEBOOK_API_TOKEN"},
    ("brightdata_instagram", "medium"): {"api_token": "BRIGHTDATA_INSTAGRAM_API_TOKEN"},
    ("majestic", "premium"): {"api_key": "MAJESTIC_API_KEY"},
    ("twitch", "free"): {
        "client_id": "TWITCH_CLIENT_ID",
        "client_secret": "TWITCH_CLIENT_SECRET",
    },
}


# ---------------------------------------------------------------------------
# Bootstrap function
# ---------------------------------------------------------------------------


async def bootstrap_credentials_from_env(env: dict[str, str] | None = None) -> int:
    """Auto-populate the credential pool from environment variables.

    Scans the environment for API credentials defined in `.env` and inserts
    them into the `api_credentials` table if they do not already exist for
    the given (platform, tier) combination.

    This is safe to call multiple times — it only inserts credentials that are
    missing from the database and skips entries that already exist.

    Args:
        env: Optional dict of environment variable overrides. If ``None``,
            uses ``os.environ``.

    Returns:
        The number of credentials auto-populated into the database.
    """
    if env is None:
        env = dict(os.environ)

    # Deferred imports to avoid circular dependency issues.
    try:
        from issue_observatory.config.settings import get_settings  # noqa: PLC0415
        from issue_observatory.core.database import AsyncSessionLocal  # noqa: PLC0415
        from issue_observatory.core.models.credentials import ApiCredential  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415
    except ImportError as exc:
        logger.warning(
            "credential_bootstrap_import_failed",
            detail=f"Could not import required modules for credential bootstrap: {exc}",
        )
        return 0

    settings = get_settings()
    if not settings.credential_encryption_key:
        logger.warning(
            "credential_bootstrap_skipped",
            detail="CREDENTIAL_ENCRYPTION_KEY is not set. Credential bootstrap is disabled.",
        )
        return 0

    inserted_count = 0

    async with AsyncSessionLocal() as db:
        for (platform, tier), field_map in _ENV_CREDENTIAL_MAP.items():
            # Build the credential payload from environment variables.
            payload: dict[str, str] = {}
            for field, env_var in field_map.items():
                value = env.get(env_var, "").strip()
                if value:
                    payload[field] = value

            # Skip if no values are set for this platform+tier.
            if not payload:
                continue

            # Check if a credential already exists for this platform+tier.
            existing = await db.execute(
                select(ApiCredential).where(
                    ApiCredential.platform == platform,
                    ApiCredential.tier == tier,
                    ApiCredential.is_active.is_(True),
                )
            )
            if existing.scalar_one_or_none() is not None:
                logger.debug(
                    "credential_bootstrap_skip_existing",
                    platform=platform,
                    tier=tier,
                    detail=f"Credential already exists for {platform}/{tier} — skipping auto-insert.",
                )
                continue

            # Encrypt the payload.
            encrypted_payload = _encrypt_payload(payload, settings.credential_encryption_key)
            if encrypted_payload is None:
                logger.warning(
                    "credential_bootstrap_encryption_failed",
                    platform=platform,
                    tier=tier,
                    detail=f"Failed to encrypt credential payload for {platform}/{tier} — skipping.",
                )
                continue

            # Insert the credential into the database.
            credential_name = f"Auto-populated from .env ({platform}/{tier})"
            new_cred = ApiCredential(
                platform=platform,
                tier=tier,
                credential_name=credential_name,
                credentials=encrypted_payload,
                is_active=True,
                daily_quota=None,  # No quota limits for env-based credentials
                monthly_quota=None,
            )
            db.add(new_cred)
            inserted_count += 1
            logger.info(
                "credential_bootstrap_inserted",
                platform=platform,
                tier=tier,
                credential_name=credential_name,
                detail=f"Auto-populated credential for {platform}/{tier} from .env",
            )

        # Commit all new credentials at once.
        if inserted_count > 0:
            await db.commit()
            logger.info(
                "credential_bootstrap_complete",
                inserted_count=inserted_count,
                detail=f"Auto-populated {inserted_count} credential(s) from .env into the database.",
            )
        else:
            logger.info(
                "credential_bootstrap_complete",
                inserted_count=0,
                detail="No new credentials found in .env — all configured credentials already exist in the database.",
            )

    return inserted_count


def _encrypt_payload(payload: dict[str, str], encryption_key: str) -> Any | None:
    """Encrypt a credential payload using Fernet.

    Args:
        payload: The plaintext credential dict (e.g. {"api_key": "..."}).
        encryption_key: The Fernet encryption key from settings.

    Returns:
        The encrypted payload suitable for the `credentials` JSONB column,
        or ``None`` if encryption failed.
    """
    try:
        from cryptography.fernet import Fernet  # noqa: PLC0415

        fernet = Fernet(encryption_key.encode("utf-8") if isinstance(encryption_key, str) else encryption_key)
        plaintext = json.dumps(payload)
        ciphertext = fernet.encrypt(plaintext.encode("utf-8"))
        # Return the ciphertext as a string so it can be stored in the JSONB column.
        # The credential_pool module decrypts it on read.
        return ciphertext.decode("utf-8")
    except Exception as exc:
        logger.exception(
            "credential_encryption_failed",
            detail=f"Failed to encrypt credential payload: {exc}",
        )
        return None
