"""SQLAlchemy ORM models for Issue Observatory.

This package is owned by the DB Engineer. Core Application Engineers
read from here but do not modify files in this directory without DB
Engineer approval.

All models are imported here so that:
1. Alembic autogenerate can discover them via Base.metadata.
2. Application code can do `from issue_observatory.core.models import User`
   without knowing which sub-module a model lives in.
3. SQLAlchemy's relationship resolution finds all mapper targets at
   import time, avoiding "mapper not yet configured" errors.
"""

from __future__ import annotations

from issue_observatory.core.models.base import Base, TimestampMixin, UserOwnedMixin
from issue_observatory.core.models.annotations import ContentAnnotation
from issue_observatory.core.models.actors import (
    Actor,
    ActorAlias,
    ActorListMember,
    ActorPlatformPresence,
)
from issue_observatory.core.models.collection import (
    CollectionRun,
    CollectionTask,
    CreditTransaction,
)
from issue_observatory.core.models.content import UniversalContentRecord
from issue_observatory.core.models.credentials import ApiCredential
from issue_observatory.core.models.scraping import ScrapingJob
from issue_observatory.core.models.query_design import (
    ActorList,
    QueryDesign,
    SearchTerm,
)
from issue_observatory.core.models.users import (
    CreditAllocation,
    RefreshToken,
    User,
)

__all__ = [
    # Base
    "Base",
    "TimestampMixin",
    "UserOwnedMixin",
    # Annotations
    "ContentAnnotation",
    # Users
    "User",
    "CreditAllocation",
    "RefreshToken",
    # Content
    "UniversalContentRecord",
    # Actors
    "Actor",
    "ActorAlias",
    "ActorPlatformPresence",
    "ActorListMember",
    # Query design
    "QueryDesign",
    "SearchTerm",
    "ActorList",
    # Collection
    "CollectionRun",
    "CollectionTask",
    "CreditTransaction",
    # Credentials
    "ApiCredential",
    # Scraping
    "ScrapingJob",
]
