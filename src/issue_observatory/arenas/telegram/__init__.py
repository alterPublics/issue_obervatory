"""Telegram arena collector package.

Provides :class:`TelegramCollector` for collecting messages from public Telegram
channels via the MTProto protocol (Telethon library).

Only ``Tier.FREE`` is supported — Telegram is a free-only arena.  Credentials
(``api_id``, ``api_hash``, ``session_string``) are stored in the
:class:`CredentialPool` under ``platform="telegram", tier="free"``.

See the arena research brief at ``docs/arenas/telegram.md`` for full context,
ethical considerations, and channel discovery guidance.
"""

from issue_observatory.arenas.telegram.collector import TelegramCollector

__all__ = ["TelegramCollector"]
