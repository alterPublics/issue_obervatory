"""GDPR data retention enforcement service.

Provides two operations mandated by the project DPIA and GDPR Art. 5(1)(e):

1. **Time-based retention**: Delete ``content_records`` older than a configurable
   number of days (default 730, set via ``Settings.data_retention_days``).

2. **Right to erasure** (Art. 17): Delete all data associated with a specific actor
   (content records where ``author_id`` matches, platform presences, and aliases).

Both operations use bulk DELETE statements with WHERE clauses rather than
loading ORM objects, which is required for correctness on partitioned tables
(``content_records`` is range-partitioned by ``published_at``).

All deletions are logged at INFO level with counts so that the audit log
captures every erasure event.

Usage::

    from issue_observatory.core.retention_service import RetentionService
    from issue_observatory.core.database import get_db

    service = RetentionService()
    async with get_db() as db:
        deleted_count = await service.enforce_retention(db, retention_days=730)
        summary = await service.delete_actor_data(db, actor_id=some_uuid)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class RetentionService:
    """GDPR data retention and erasure service.

    Stateless — a single instance can be reused across requests.
    All methods accept the ``AsyncSession`` from the caller so that
    transaction management remains with the calling layer.
    """

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def enforce_retention(
        self,
        db: AsyncSession,
        retention_days: int,
    ) -> int:
        """Delete content records older than *retention_days*.

        Uses a bulk DELETE on ``content_records`` filtered by
        ``collected_at < now() - interval``.  Because ``content_records`` is
        range-partitioned by ``published_at``, PostgreSQL will prune
        unnecessary partitions during execution.

        The operation is committed inside this method.  Callers should not
        wrap it in an outer transaction unless they want to roll back on error.

        Args:
            db: Active async database session.
            retention_days: Maximum age of records to keep, in days.
                Records with ``collected_at`` older than this threshold are
                deleted.

        Returns:
            Number of rows deleted.
        """
        threshold = datetime.now(tz=timezone.utc) - timedelta(days=retention_days)

        # Import lazily to avoid circular imports at module level.
        from issue_observatory.core.models.content import UniversalContentRecord  # noqa: PLC0415

        stmt = delete(UniversalContentRecord).where(UniversalContentRecord.collected_at < threshold)
        result = await db.execute(stmt)
        deleted = result.rowcount or 0
        await db.commit()

        logger.info(
            "retention_enforcement_complete",
            extra={
                "threshold_date": threshold.isoformat(),
                "retention_days": retention_days,
                "records_deleted": deleted,
            },
        )
        return deleted

    async def delete_actor_data(
        self,
        db: AsyncSession,
        actor_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Delete all data associated with an actor (right to erasure).

        Deletes in order to respect foreign-key constraints:
        1. ``content_records`` where ``author_id = actor_id``
        2. ``actor_platform_presences`` where ``actor_id = actor_id``
        3. ``actor_aliases`` where ``actor_id = actor_id``
        4. ``actor_list_members`` where ``actor_id = actor_id``
        5. ``actors`` where ``id = actor_id``

        The entire operation is committed inside this method.

        Args:
            db: Active async database session.
            actor_id: UUID of the actor whose data should be erased.

        Returns:
            Summary dict with keys ``content_records``, ``presences``,
            ``aliases``, ``list_memberships``, ``actors`` mapping to the
            number of rows deleted for each table.
        """
        from issue_observatory.core.models.actors import (  # noqa: PLC0415
            Actor,
            ActorAlias,
            ActorListMember,
            ActorPlatformPresence,
        )
        from issue_observatory.core.models.content import UniversalContentRecord  # noqa: PLC0415

        # 1. Content records authored by this actor
        cr_result = await db.execute(
            delete(UniversalContentRecord).where(UniversalContentRecord.author_id == actor_id)
        )
        content_deleted = cr_result.rowcount or 0

        # 2. Platform presences
        pp_result = await db.execute(
            delete(ActorPlatformPresence).where(
                ActorPlatformPresence.actor_id == actor_id
            )
        )
        presences_deleted = pp_result.rowcount or 0

        # 3. Aliases
        alias_result = await db.execute(
            delete(ActorAlias).where(ActorAlias.actor_id == actor_id)
        )
        aliases_deleted = alias_result.rowcount or 0

        # 4. Actor list memberships
        alm_result = await db.execute(
            delete(ActorListMember).where(ActorListMember.actor_id == actor_id)
        )
        memberships_deleted = alm_result.rowcount or 0

        # 5. Actor row itself
        actor_result = await db.execute(
            delete(Actor).where(Actor.id == actor_id)
        )
        actors_deleted = actor_result.rowcount or 0

        await db.commit()

        summary: dict[str, Any] = {
            "actor_id": str(actor_id),
            "content_records": content_deleted,
            "presences": presences_deleted,
            "aliases": aliases_deleted,
            "list_memberships": memberships_deleted,
            "actors": actors_deleted,
        }

        logger.info(
            "actor_data_erased",
            extra=summary,
        )
        return summary
