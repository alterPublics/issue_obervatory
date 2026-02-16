"""Factory Boy model factories for test data generation.

Available factories
-------------------
UserFactory                 — researcher user dict
AdminUserFactory            — admin user dict
InactiveUserFactory         — pending-activation user dict
CreditAllocationFactory     — credit allocation dict
QueryDesignFactory          — query design dict (Danish defaults)
DanishQueryDesignFactory    — query design with Danish name/description
SearchTermFactory           — search term dict
DanishSearchTermFactory     — Danish-keyword search terms (æ, ø, å)
ContentRecordFactory        — universal content record dict (Danish text)
GoogleSearchResultFactory   — Serper.dev organic result dict (raw)
"""

from __future__ import annotations

from tests.factories.content import ContentRecordFactory, GoogleSearchResultFactory
from tests.factories.query_designs import (
    DanishQueryDesignFactory,
    DanishSearchTermFactory,
    QueryDesignFactory,
    SearchTermFactory,
)
from tests.factories.users import (
    AdminUserFactory,
    CreditAllocationFactory,
    InactiveUserFactory,
    UserFactory,
)

__all__ = [
    "AdminUserFactory",
    "ContentRecordFactory",
    "CreditAllocationFactory",
    "DanishQueryDesignFactory",
    "DanishSearchTermFactory",
    "GoogleSearchResultFactory",
    "InactiveUserFactory",
    "QueryDesignFactory",
    "SearchTermFactory",
    "UserFactory",
]
