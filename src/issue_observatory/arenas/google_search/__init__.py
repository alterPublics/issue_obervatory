"""Google Search arena collector.

Provides programmatic access to Google Search organic results via Serper.dev
(MEDIUM tier) and SerpAPI (PREMIUM tier).  FREE tier is not available.

Importing this package registers ``GoogleSearchCollector`` in the arena
registry via the ``@register`` decorator applied in ``collector.py``.

Typical usage::

    from issue_observatory.arenas.google_search import GoogleSearchCollector
    from issue_observatory.arenas.base import Tier
    from issue_observatory.core.credential_pool import CredentialPool

    collector = GoogleSearchCollector(credential_pool=CredentialPool())
    records = await collector.collect_by_terms(
        terms=["klimaforandringer"],
        tier=Tier.MEDIUM,
        max_results=100,
    )
"""

from __future__ import annotations

from issue_observatory.arenas.google_search.collector import GoogleSearchCollector

__all__ = ["GoogleSearchCollector"]
