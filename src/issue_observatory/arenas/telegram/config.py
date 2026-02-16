"""Telegram arena configuration and tier definitions.

Telegram is a free-only arena accessed via the Telethon MTProto client library.
No medium or premium tiers exist.

**Credentials** are stored in CredentialPool as:
    ``platform="telegram"``, ``tier="free"``

Each credential JSONB payload must contain:
    - ``api_id`` (int): Application ID from https://my.telegram.org/apps.
    - ``api_hash`` (str): Application hash from https://my.telegram.org/apps.
    - ``session_string`` (str): Serialized Telethon StringSession. Generated
      once via interactive phone verification and stored permanently.

**Channel list**: :data:`DANISH_TELEGRAM_CHANNELS` is a starter list of known
Danish-language public Telegram channels.  This list is intentionally minimal
at Phase 1 launch; expansion is tracked as pre-Phase task E.5 in
``IMPLEMENTATION_PLAN.md``.  Users can extend the list by passing additional
channel identifiers in the ``actor_ids`` argument of collection methods.

**Rate limiting**: Telegram uses FloodWaitError rather than a fixed rate window.
A conservative baseline of 20 requests per minute per account is configured in
``workers/rate_limiter.py::ARENA_DEFAULTS["telegram"]``.  The real signal is
always the ``FloodWaitError.seconds`` attribute, which must be honoured exactly.
"""

from __future__ import annotations

from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# Rate limiting baseline
# ---------------------------------------------------------------------------

TELEGRAM_REQUESTS_PER_MINUTE: int = 20
"""Conservative baseline requests-per-minute used as the initial rate limit.

Telegram does not publish a fixed rate limit. The operative signal is the
``FloodWaitError.seconds`` attribute returned by the MTProto server.  This
baseline exists only to prevent accidental burst.
"""

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

MAX_MESSAGES_PER_REQUEST: int = 100
"""Maximum messages fetched per ``get_messages()`` call (Telegram server cap)."""

# ---------------------------------------------------------------------------
# Default Danish channel list
# ---------------------------------------------------------------------------

DANISH_TELEGRAM_CHANNELS: list[str] = [
    "dr_nyheder",
    "tv2nyhederne",
    "berlingske",
    "politiken_dk",
    "bt_dk",
    "informationdk",
]
"""Starter list of known Danish public Telegram channel usernames.

This list is intentionally small at Phase 1 launch.  Expansion is tracked as
pre-Phase task E.5 in ``IMPLEMENTATION_PLAN.md``.  Channels are identified by
their public username (without the leading ``@``).

Supply additional channel identifiers via ``actor_ids`` in collection calls or
by extending this list in a local configuration override.

Important: The Telegram collector only covers *public* broadcast channels.
Encrypted Secret Chats and private groups are not accessible via the MTProto
user client API.
"""

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

TELEGRAM_TIERS: dict[Tier, TierConfig | None] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=10_000,
        rate_limit_per_minute=TELEGRAM_REQUESTS_PER_MINUTE,
        requires_credential=True,
        estimated_credits_per_1k=0,
    ),
    Tier.MEDIUM: None,
    Tier.PREMIUM: None,
}
"""Per-tier configuration for the Telegram arena.

Only ``Tier.FREE`` is available.  MEDIUM and PREMIUM map to ``None``.
"""
