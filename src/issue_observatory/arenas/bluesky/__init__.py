"""Bluesky arena package.

Collects posts from Bluesky via the AT Protocol API.

- **FREE** — AT Protocol API (``bsky.social/xrpc``).
  Authentication required via handle + app password. 3,000 req/5 min per account.
  No medium or premium tiers exist — the free tier is sufficient.

Danish content is collected via the ``lang=da`` parameter on search requests
and by filtering author feeds for known Danish handles/DIDs.

The collector obtains a session token via ``com.atproto.server.createSession``
and uses it for all subsequent requests with the Authorization header.

The ``BlueskyStreamer`` class in ``collector.py`` provides optional Jetstream
firehose support for real-time collection, but batch Celery tasks do not
require it.
"""
