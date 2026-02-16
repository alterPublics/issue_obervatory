"""Event Registry / NewsAPI.ai arena for the Issue Observatory.

Collects Danish news articles via the NewsAPI.ai (eventregistry.org) API.
Provides full article text, native Danish NLP enrichment (entity extraction,
categorisation, sentiment), and cross-source event deduplication — a
significant upgrade over GDELT and RSS for paid collection tiers.

Supported tiers:
- ``Tier.MEDIUM``  — NewsAPI.ai Starter (~$90/month, 5,000 tokens/month).
- ``Tier.PREMIUM`` — NewsAPI.ai Business (~$490/month, 50,000 tokens/month).

No free tier is available.  Credentials must be provisioned in
``CredentialPool`` under ``platform="event_registry"``.

Public API:
    from issue_observatory.arenas.event_registry.collector import (
        EventRegistryCollector,
    )
    from issue_observatory.arenas.event_registry.router import router
    from issue_observatory.arenas.event_registry.tasks import (
        event_registry_collect_terms,
        event_registry_collect_actors,
        event_registry_health_check,
    )
"""
