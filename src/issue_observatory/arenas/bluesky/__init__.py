"""Bluesky arena package.

Collects posts from Bluesky via the AT Protocol public API.

- **FREE** — AT Protocol public API (``public.api.bsky.app``).
  No authentication required. 3,000 req/5 min per IP.
  No medium or premium tiers exist — the free tier is sufficient.

Danish content is collected via the ``lang=da`` parameter on search requests
and by filtering author feeds for known Danish handles/DIDs.

The ``BlueskyStreamer`` class in ``collector.py`` provides optional Jetstream
firehose support for real-time collection, but batch Celery tasks do not
require it.
"""
