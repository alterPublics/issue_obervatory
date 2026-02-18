"""Discord arena collector.

Batch message retrieval from curated Danish server channels via the Discord
Bot API (REST, v10). Requires a DISCORD_BOT_TOKEN credential stored in the
CredentialPool with ``platform="discord"`` and field ``{"bot_token": "..."}``.

Discord's architecture is channel-first: bots cannot search by keyword across
servers. All term matching is performed client-side after message retrieval.
The researcher must curate a list of server channels to monitor and have the
research bot invited to each target server by its administrator.

Collection modes:
    - Batch (``collect_by_terms``, ``collect_by_actors``): REST API pagination
      via ``GET /channels/{id}/messages`` with ``before``/``after`` cursors.
    - Streaming (future): Discord Gateway WebSocket; not implemented here.

Phase: 3+ (Medium priority)
Brief: /docs/arenas/discord.md
"""
