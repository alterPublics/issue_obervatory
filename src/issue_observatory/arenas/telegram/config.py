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

**Channel list**: :data:`DANISH_TELEGRAM_CHANNELS` is empty by default because
Danish news outlets do not operate official public Telegram channels.  Channels
must be configured per query design via ``arenas_config["telegram"]["custom_channels"]``
(GR-02).  Passing fake or unverified usernames produces silent 0-result runs
without surfacing any error, so no defaults are shipped.

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
# Humanizing inter-request delays
# ---------------------------------------------------------------------------

TELEGRAM_INTER_REQUEST_DELAY_MIN: float = 1.0
"""Minimum delay in seconds between consecutive Telegram API calls.

Adds randomized jitter on top of the sliding-window rate limiter to mimic
human pacing and reduce the risk of ``FloodWaitError`` from the MTProto server.
"""

TELEGRAM_INTER_REQUEST_DELAY_MAX: float = 3.0
"""Maximum delay in seconds between consecutive Telegram API calls."""

TELEGRAM_CHANNEL_RESOLUTION_DELAY: float = 0.5
"""Delay in seconds before resolving a channel entity via ``get_entity()``.

Channel resolution is a lightweight RPC but still counts toward Telegram's
internal rate budget.  A short delay before each resolution reduces the chance
of triggering ``FloodWaitError`` during the channel discovery phase.
"""

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

MAX_MESSAGES_PER_REQUEST: int = 100
"""Maximum messages fetched per ``get_messages()`` call (Telegram server cap)."""

# ---------------------------------------------------------------------------
# Default Danish channel list
# ---------------------------------------------------------------------------

DANISH_TELEGRAM_CHANNELS: list[str] = []
"""Default list of Danish public Telegram channel usernames.

This is intentionally empty. Danish news outlets (DR, TV2, Politiken, BT,
Berlingske, etc.) do not operate official public Telegram channels, so
shipping placeholder usernames would silently produce 0 results without
surfacing any error to the researcher.

Channels must be configured explicitly per query design via:
    ``arenas_config["telegram"]["custom_channels"]``

on the Query Design editor (GR-02). Channels are identified by their public
username without the leading ``@`` (e.g. ``"some_channel"``).

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
