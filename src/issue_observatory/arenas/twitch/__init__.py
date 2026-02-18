"""Twitch arena collector — DEFERRED stub.

This arena is deferred until a specific research need arises. Twitch is a
streaming-only platform: there is no API endpoint for retrieving historical
chat messages. Once a stream ends, chat messages are permanently lost unless
captured in real time via the EventSub WebSocket.

Implemented functionality:
    - ``collect_by_terms``: Channel discovery via ``GET /search/channels``.
      Returns channel metadata records (NOT chat messages). Chat is streaming-only.
    - ``collect_by_actors``: Same channel-metadata pattern for known broadcaster IDs.
    - ``health_check``: Verifies the Helix API and app access token are valid.

NOT implemented (requires streaming worker):
    - Real-time chat collection via EventSub WebSocket (``channel.chat.message``).
    - Historical chat retrieval (not possible with any Twitch API).

Phase: 3+ (Low priority — deferred)
Brief: /docs/arenas/twitch.md

To activate real-time chat collection, implement ``TwitchStreamer`` following
the BlueskyStreamer pattern in ``arenas/bluesky/collector.py`` and route
``issue_observatory.arenas.twitch.tasks.stream*`` to the ``"streaming"`` Celery queue.
"""
