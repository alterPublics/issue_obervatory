"""Unit tests for credential bootstrap from environment variables.

Verifies that credentials defined in .env are correctly auto-populated into
the api_credentials table on application startup, with proper encryption and
deduplication.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from issue_observatory.core.credential_bootstrap import bootstrap_credentials_from_env
from issue_observatory.core.models.credentials import ApiCredential


@pytest.fixture
def mock_fernet_key() -> str:
    """Generate a valid Fernet key for test encryption."""
    return Fernet.generate_key().decode("utf-8")


@pytest.mark.asyncio
async def test_bootstrap_creates_new_credentials(
    db_session,
    mock_fernet_key,
    monkeypatch,
):
    """Verify that new credentials are inserted when they don't exist."""
    # Patch settings to use a valid Fernet key
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", mock_fernet_key)

    # Mock environment with some credentials
    env = {
        "SERPER_API_KEY": "test-serper-key-123",
        "BLUESKY_HANDLE": "test.bsky.social",
        "BLUESKY_APP_PASSWORD": "test-app-password",
        "YOUTUBE_API_KEY": "test-youtube-key-456",
    }

    # Run bootstrap
    from issue_observatory.config.settings import get_settings

    get_settings.cache_clear()  # Clear cached settings to pick up new env vars
    inserted_count = await bootstrap_credentials_from_env(env=env)

    # Should have inserted 3 credentials (serper/medium, bluesky/free, youtube/free)
    assert inserted_count == 3

    # Verify credentials are in the database
    from sqlalchemy import select

    result = await db_session.execute(
        select(ApiCredential).where(ApiCredential.is_active.is_(True))
    )
    credentials = list(result.scalars().all())
    assert len(credentials) == 3

    platforms = {(c.platform, c.tier) for c in credentials}
    assert ("serper", "medium") in platforms
    assert ("bluesky", "free") in platforms
    assert ("youtube", "free") in platforms

    # Verify credential names contain "Auto-populated"
    for cred in credentials:
        assert "Auto-populated from .env" in cred.credential_name


@pytest.mark.asyncio
async def test_bootstrap_skips_existing_credentials(
    db_session,
    mock_fernet_key,
    monkeypatch,
):
    """Verify that existing credentials are not overwritten."""
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", mock_fernet_key)

    # Insert an existing credential manually
    from issue_observatory.core.credential_bootstrap import _encrypt_payload

    existing_payload = _encrypt_payload({"api_key": "existing-key"}, mock_fernet_key)
    existing_cred = ApiCredential(
        platform="serper",
        tier="medium",
        credential_name="Manually added credential",
        credentials=existing_payload,
        is_active=True,
    )
    db_session.add(existing_cred)
    await db_session.commit()

    # Try to bootstrap with a different key
    env = {"SERPER_API_KEY": "new-key-should-be-ignored"}

    from issue_observatory.config.settings import get_settings

    get_settings.cache_clear()
    inserted_count = await bootstrap_credentials_from_env(env=env)

    # Should NOT insert a new credential
    assert inserted_count == 0

    # Verify the original credential still exists unchanged
    from sqlalchemy import select

    result = await db_session.execute(
        select(ApiCredential).where(
            ApiCredential.platform == "serper",
            ApiCredential.tier == "medium",
        )
    )
    creds = list(result.scalars().all())
    assert len(creds) == 1
    assert creds[0].credential_name == "Manually added credential"


@pytest.mark.asyncio
async def test_bootstrap_skips_empty_credentials(
    db_session,
    mock_fernet_key,
    monkeypatch,
):
    """Verify that credentials with empty values are not inserted."""
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", mock_fernet_key)

    # Environment with empty/missing values
    env = {
        "SERPER_API_KEY": "",  # Empty string
        "BLUESKY_HANDLE": "test.bsky.social",
        "BLUESKY_APP_PASSWORD": "",  # Empty password
        # YOUTUBE_API_KEY not set at all
    }

    from issue_observatory.config.settings import get_settings

    get_settings.cache_clear()
    inserted_count = await bootstrap_credentials_from_env(env=env)

    # Should insert nothing (SERPER empty, Bluesky incomplete, YouTube missing)
    assert inserted_count == 0


@pytest.mark.asyncio
async def test_bootstrap_handles_multi_field_credentials(
    db_session,
    mock_fernet_key,
    monkeypatch,
):
    """Verify that multi-field credentials (Reddit, X/Twitter) are assembled correctly."""
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", mock_fernet_key)

    env = {
        "REDDIT_CLIENT_ID": "test-client-id",
        "REDDIT_CLIENT_SECRET": "test-client-secret",
        "REDDIT_USER_AGENT": "TestAgent/1.0",
        "X_BEARER_TOKEN": "test-bearer",
        "X_API_KEY": "test-x-key",
        "X_API_SECRET": "test-x-secret",
    }

    from issue_observatory.config.settings import get_settings

    get_settings.cache_clear()
    inserted_count = await bootstrap_credentials_from_env(env=env)

    # Should have inserted 2 credentials (reddit/free, x_twitter/premium)
    assert inserted_count == 2

    from sqlalchemy import select

    result = await db_session.execute(
        select(ApiCredential).where(ApiCredential.is_active.is_(True))
    )
    credentials = list(result.scalars().all())
    platforms = {(c.platform, c.tier) for c in credentials}
    assert ("reddit", "free") in platforms
    assert ("x_twitter", "premium") in platforms


@pytest.mark.asyncio
async def test_bootstrap_with_no_encryption_key(
    db_session,
    monkeypatch,
):
    """Verify that bootstrap is skipped when CREDENTIAL_ENCRYPTION_KEY is not set."""
    # Clear the encryption key
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)

    env = {"SERPER_API_KEY": "test-key"}

    from issue_observatory.config.settings import get_settings

    get_settings.cache_clear()

    # Should return 0 and log a warning (not raise an exception)
    inserted_count = await bootstrap_credentials_from_env(env=env)
    assert inserted_count == 0


@pytest.mark.asyncio
async def test_credential_decryption_round_trip(
    db_session,
    mock_fernet_key,
    monkeypatch,
):
    """Verify that encrypted credentials can be decrypted by CredentialPool."""
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", mock_fernet_key)

    env = {"YOUTUBE_API_KEY": "test-youtube-api-key-789"}

    from issue_observatory.config.settings import get_settings

    get_settings.cache_clear()
    await bootstrap_credentials_from_env(env=env)

    # Now try to acquire the credential using CredentialPool
    from issue_observatory.core.credential_pool import CredentialPool

    pool = CredentialPool()
    cred = await pool.acquire(platform="youtube", tier="free")

    assert cred is not None
    assert cred["platform"] == "youtube"
    assert cred["tier"] == "free"
    assert cred["api_key"] == "test-youtube-api-key-789"
