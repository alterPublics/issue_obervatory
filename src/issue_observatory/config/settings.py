"""Application settings loaded from environment variables.

Uses Pydantic Settings v2 for validated, type-safe configuration.
All credentials and secrets are accessed exclusively through this module —
never call ``os.getenv`` directly elsewhere in the codebase.

Usage::

    from issue_observatory.config.settings import get_settings

    settings = get_settings()
    db_url = settings.database_url
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import EmailStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide configuration backed by environment variables and an optional .env file.

    All fields without defaults are required and must be supplied via the environment
    or a .env file before the application starts.  Secrets (passwords, keys, salts)
    should never be committed to version control.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------

    database_url: str
    """Async-compatible PostgreSQL DSN.

    Must use the ``asyncpg`` driver, e.g.::

        postgresql+asyncpg://user:password@localhost:5432/issue_observatory
    """

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------

    redis_url: str = "redis://localhost:6379/0"
    """Redis connection URL used by the application (session state, caching)."""

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------

    secret_key: str
    """Random secret used to sign JWT tokens.  Generate with ``openssl rand -hex 32``."""

    access_token_expire_minutes: int = 30
    """Lifetime of short-lived JWT access tokens in minutes."""

    refresh_token_expire_days: int = 30
    """Lifetime of long-lived JWT refresh tokens in days."""

    credential_encryption_key: str
    """Fernet symmetric key used to encrypt API credentials at rest.

    Generate with::

        from cryptography.fernet import Fernet
        Fernet.generate_key().decode()

    **This is the single most critical secret in the system.**  If lost, all stored
    API credentials become unrecoverable.  Back up securely (Docker Secrets / Vault).
    """

    pseudonymization_salt: str
    """Project-specific salt appended before SHA-256 hashing of author identifiers.

    Used to compute ``pseudonymized_author_id`` on every collected content record::

        SHA-256(platform + platform_user_id + pseudonymization_salt)

    Must be kept stable across the lifetime of a research project so that the same
    author always maps to the same pseudonym.
    """

    # ------------------------------------------------------------------
    # MinIO / S3-compatible object storage
    # ------------------------------------------------------------------

    minio_endpoint: str = "localhost:9000"
    """Host:port of the MinIO (or S3-compatible) endpoint — without a scheme prefix."""

    minio_root_user: str = "minioadmin"
    """MinIO root access key (equivalent to AWS_ACCESS_KEY_ID)."""

    minio_root_password: str = "minioadmin"
    """MinIO root secret key (equivalent to AWS_SECRET_ACCESS_KEY)."""

    minio_bucket: str = "issue-observatory"
    """Default bucket name for media file archival (images, thumbnails, PDFs)."""

    minio_secure: bool = False
    """Whether to use TLS when connecting to MinIO.  Set to True in production."""

    # ------------------------------------------------------------------
    # Celery task queue
    # ------------------------------------------------------------------

    celery_broker_url: str = "redis://localhost:6379/1"
    """Redis URL used as Celery's message broker (database 1 to isolate from app)."""

    celery_result_backend: str = "redis://localhost:6379/2"
    """Redis URL used to store Celery task results (database 2)."""

    # ------------------------------------------------------------------
    # Admin bootstrap
    # ------------------------------------------------------------------

    first_admin_email: EmailStr = ""  # type: ignore[assignment]
    """E-mail address for the bootstrapped admin account.  Optional at runtime;
    the admin bootstrap script will skip creation if empty."""

    first_admin_password: str = ""
    """Password for the bootstrapped admin account.  Only used during first-run init."""

    # ------------------------------------------------------------------
    # Application behaviour
    # ------------------------------------------------------------------

    app_name: str = "The Issue Observatory"
    """Human-readable application name shown in the UI and OpenAPI docs."""

    debug: bool = False
    """Enable FastAPI debug mode and verbose error responses.  Never True in production."""

    log_level: str = "INFO"
    """Logging verbosity.  One of: DEBUG, INFO, WARNING, ERROR, CRITICAL."""

    default_tier: str = "free"
    """Default collection tier applied when a collection run does not specify one.
    Must be one of the values defined in :class:`issue_observatory.config.tiers.Tier`."""

    # ------------------------------------------------------------------
    # Danish locale defaults
    # ------------------------------------------------------------------

    default_language: str = "da"
    """ISO 639-1 language code applied as the default collection filter."""

    default_locale_country: str = "dk"
    """ISO 3166-1 alpha-2 country code applied as the default locale filter."""

    # ------------------------------------------------------------------
    # GDPR / data retention
    # ------------------------------------------------------------------

    data_retention_days: int = 730
    """Maximum age (in days) of collected records before the retention enforcement
    job marks them for deletion.  Defaults to 2 years (730 days).

    Aligns with the purpose-limitation principle under Art. 5(1)(e) GDPR and the
    Databeskyttelsesloven §10 requirements for university research projects.
    """

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------

    allowed_origins: list[str] = ["http://localhost:8000"]
    """Origins permitted by the CORS middleware.  Extend for production domains."""

    # ------------------------------------------------------------------
    # SMTP / email notifications
    # ------------------------------------------------------------------

    smtp_host: Optional[str] = None
    """SMTP server hostname.  When ``None``, email notifications are disabled
    and all ``EmailService`` send methods silently no-op."""

    smtp_port: int = 587
    """SMTP server port.  587 is the standard submission port for STARTTLS."""

    smtp_username: Optional[str] = None
    """SMTP authentication username.  Leave ``None`` for open relays."""

    smtp_password: Optional[str] = None
    """SMTP authentication password.  Leave ``None`` for open relays."""

    smtp_from_address: str = "noreply@observatory.local"
    """The ``From:`` address used for all outgoing notification emails."""

    smtp_starttls: bool = True
    """Upgrade the connection to TLS via STARTTLS after connecting.
    Standard for port 587.  Set to ``False`` for localhost dev relays."""

    smtp_ssl: bool = False
    """Use implicit TLS from the start (e.g. port 465).  Mutually exclusive
    with ``smtp_starttls``."""

    # ------------------------------------------------------------------
    # Credit warning threshold
    # ------------------------------------------------------------------

    low_credit_warning_threshold: int = 100
    """Send a low-credit warning email when the user's remaining credit
    balance drops below this value after a collection run settles."""

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    metrics_enabled: bool = True
    """Expose Prometheus metrics at ``GET /metrics``.

    Set to ``False`` to disable the endpoint entirely (e.g. in environments
    where the metrics path must not be publicly reachable and a network-level
    restriction is not practical).
    """


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings singleton.

    Uses ``functools.lru_cache`` so that Pydantic Settings reads the environment
    and .env file exactly once per process lifetime.  In tests, call
    ``get_settings.cache_clear()`` after patching environment variables.

    Returns:
        Settings: The validated, immutable settings object.
    """
    return Settings()
