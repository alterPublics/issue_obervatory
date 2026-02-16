"""Cross-platform entity resolution for actors.

The ``EntityResolver`` matches actors across platforms by platform presence
lookup, and provides ``create_or_update_presence()`` to establish new
actor records with their platform presences.

Phase 0 capabilities:
- Exact lookup by (platform, platform_user_id).
- Create actor + platform presence if the pair is not yet known.
- Return actor UUID for linking into ``content_records.author_id``.

Phase 3.9 additions:
- ``find_candidate_matches()``: fuzzy cross-platform matching via exact
  name match, shared platform username, and pg_trgm trigram similarity.
- ``merge_actors()``: collapse duplicate actor records into one canonical actor.
- ``split_actor()``: separate platform presences from an actor into a new actor.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class EntityResolver:
    """Resolves and manages cross-platform actor identities.

    The resolver uses the SQLAlchemy async session injected at construction.
    Pass ``None`` during unit tests to run the resolver in a no-op / stub mode.

    Args:
        session: An open ``AsyncSession``. If ``None``, all database
            operations are skipped and ``find_actor`` always returns ``None``.
    """

    def __init__(self, session: Any = None) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Public interface — Phase 0
    # ------------------------------------------------------------------

    async def find_actor(
        self,
        platform: str,
        platform_user_id: str,
    ) -> uuid.UUID | None:
        """Look up an actor by their platform presence.

        Queries ``actor_platform_presences`` for the exact
        (platform, platform_user_id) pair and returns the associated
        ``actor_id`` if found.

        Args:
            platform: Platform identifier (e.g. ``"bluesky"``, ``"reddit"``).
            platform_user_id: Native platform user ID.

        Returns:
            The actor's UUID if a matching presence exists, else ``None``.

        Raises:
            EntityResolutionError: If the database query fails.
        """
        if self._session is None:
            logger.debug(
                "EntityResolver running without a session — find_actor returning None "
                "(platform=%s, platform_user_id=%s)",
                platform,
                platform_user_id,
            )
            return None

        from issue_observatory.core.exceptions import EntityResolutionError

        try:
            from sqlalchemy import select

            from issue_observatory.core.models.actors import ActorPlatformPresence

            stmt = select(ActorPlatformPresence.actor_id).where(
                ActorPlatformPresence.platform == platform,
                ActorPlatformPresence.platform_user_id == platform_user_id,
            )
            result = await self._session.execute(stmt)
            actor_id: uuid.UUID | None = result.scalar_one_or_none()
            return actor_id
        except Exception as exc:
            raise EntityResolutionError(
                f"Failed to look up actor on platform '{platform}' "
                f"with user_id '{platform_user_id}': {exc}",
                platform=platform,
                platform_user_id=platform_user_id,
            ) from exc

    async def create_or_update_presence(
        self,
        actor_data: dict[str, Any],
    ) -> uuid.UUID:
        """Create or update an actor and their platform presence record.

        If no actor with the given (platform, platform_user_id) pair exists,
        a new ``Actor`` row is inserted with ``canonical_name`` set to the
        display name, and a new ``ActorPlatformPresence`` row is inserted.

        If the presence already exists, the ``follower_count``,
        ``platform_username``, ``profile_url``, and ``last_checked_at``
        fields are updated in place.

        Args:
            actor_data: Dict describing the actor. Recognized keys:

                - ``platform`` (str, required): Platform identifier.
                - ``platform_user_id`` (str, required): Native user ID.
                - ``platform_username`` (str | None): @-handle or username.
                - ``display_name`` (str | None): Human-readable name.
                - ``profile_url`` (str | None): URL to the actor's profile.
                - ``follower_count`` (int | None): Current follower count.
                - ``actor_type`` (str | None): ``"person"``, ``"organization"``, etc.
                - ``is_shared`` (bool): Whether this actor is visible to all users.

        Returns:
            The ``actor_id`` UUID — either newly created or the existing one.

        Raises:
            ValueError: If required keys are missing from *actor_data*.
            EntityResolutionError: If the database operation fails.
        """
        platform = actor_data.get("platform")
        platform_user_id = actor_data.get("platform_user_id")

        if not platform or not platform_user_id:
            raise ValueError(
                "actor_data must contain non-empty 'platform' and 'platform_user_id' keys."
            )

        if self._session is None:
            logger.warning(
                "EntityResolver running without a session — returning a transient UUID "
                "(platform=%s, platform_user_id=%s)",
                platform,
                platform_user_id,
            )
            return uuid.uuid4()

        from issue_observatory.core.exceptions import EntityResolutionError

        try:
            from datetime import datetime, timezone

            from sqlalchemy import select, update

            from issue_observatory.core.models.actors import (
                Actor,
                ActorPlatformPresence,
            )

            # Check whether the presence already exists.
            stmt = select(ActorPlatformPresence).where(
                ActorPlatformPresence.platform == platform,
                ActorPlatformPresence.platform_user_id == platform_user_id,
            )
            result = await self._session.execute(stmt)
            presence: ActorPlatformPresence | None = result.scalar_one_or_none()

            if presence is not None:
                # Update mutable fields on the existing presence.
                update_stmt = (
                    update(ActorPlatformPresence)
                    .where(ActorPlatformPresence.id == presence.id)
                    .values(
                        platform_username=actor_data.get("platform_username"),
                        profile_url=actor_data.get("profile_url"),
                        follower_count=actor_data.get("follower_count"),
                        last_checked_at=datetime.now(tz=timezone.utc),
                    )
                )
                await self._session.execute(update_stmt)
                await self._session.commit()
                return presence.actor_id  # type: ignore[return-value]

            # Create a new actor row.
            display_name: str = (
                actor_data.get("display_name")
                or actor_data.get("platform_username")
                or platform_user_id
            )
            new_actor = Actor(
                canonical_name=display_name,
                actor_type=actor_data.get("actor_type"),
                is_shared=bool(actor_data.get("is_shared", False)),
            )
            self._session.add(new_actor)
            await self._session.flush()  # populate new_actor.id

            # Create the platform presence.
            new_presence = ActorPlatformPresence(
                actor_id=new_actor.id,
                platform=platform,
                platform_user_id=platform_user_id,
                platform_username=actor_data.get("platform_username"),
                profile_url=actor_data.get("profile_url"),
                follower_count=actor_data.get("follower_count"),
                last_checked_at=datetime.now(tz=timezone.utc),
            )
            self._session.add(new_presence)
            await self._session.commit()

            logger.info(
                "Created new actor id=%s for %s/%s",
                new_actor.id,
                platform,
                platform_user_id,
            )
            return new_actor.id  # type: ignore[return-value]

        except Exception as exc:
            await self._session.rollback()
            raise EntityResolutionError(
                f"Failed to create/update actor presence for platform '{platform}', "
                f"platform_user_id '{platform_user_id}': {exc}",
                platform=platform,
                platform_user_id=platform_user_id,
            ) from exc

    # ------------------------------------------------------------------
    # Public interface — Phase 3.9
    # ------------------------------------------------------------------

    async def find_candidate_matches(
        self,
        db: Any,
        actor_id: uuid.UUID,
        threshold: float = 0.7,
    ) -> list[dict]:
        """Find actors that may be the same real-world entity.

        Matching strategy applied in priority order:

        1. Exact ``canonical_name`` match (case-insensitive) on a different actor.
        2. Shared ``platform_username`` across different platforms / actors.
        3. Trigram similarity on ``canonical_name`` via PostgreSQL ``pg_trgm``
           (``similarity() > threshold``).

        The method enables ``pg_trgm`` with ``CREATE EXTENSION IF NOT EXISTS``
        before executing the similarity query.

        Args:
            db: Active ``AsyncSession``.
            actor_id: UUID of the actor to find candidates for.
            threshold: Minimum trigram similarity score (0–1, default 0.7).

        Returns:
            A list of dicts, each with keys:

            - ``actor_id`` (str): UUID of the candidate actor.
            - ``canonical_name`` (str): Candidate's canonical name.
            - ``similarity`` (float): Trigram similarity score (1.0 for
              exact/username matches).
            - ``match_reason`` (str): One of ``"exact_name"``,
              ``"shared_username"``, ``"trigram"``.
            - ``platforms`` (list[str]): Platforms this candidate appears on.
        """
        from sqlalchemy import func, select, text
        from sqlalchemy.dialects.postgresql import ARRAY

        from issue_observatory.core.models.actors import Actor, ActorPlatformPresence

        # Fetch the target actor for comparison.
        target_stmt = select(Actor).where(Actor.id == actor_id)
        target_result = await db.execute(target_stmt)
        target: Actor | None = target_result.scalar_one_or_none()
        if target is None:
            return []

        candidates: dict[str, dict] = {}  # actor_id str -> result dict

        # ---- Strategy 1: Exact canonical_name match (case-insensitive) ----
        exact_stmt = (
            select(Actor)
            .where(
                func.lower(Actor.canonical_name) == func.lower(target.canonical_name),
                Actor.id != actor_id,
            )
            .limit(20)
        )
        exact_result = await db.execute(exact_stmt)
        for actor in exact_result.scalars().all():
            aid = str(actor.id)
            if aid not in candidates:
                candidates[aid] = {
                    "actor_id": aid,
                    "canonical_name": actor.canonical_name,
                    "similarity": 1.0,
                    "match_reason": "exact_name",
                    "platforms": [],
                }

        # ---- Strategy 2: Shared platform_username across different actors ----
        # Find usernames belonging to the target actor.
        target_usernames_stmt = select(
            ActorPlatformPresence.platform_username
        ).where(
            ActorPlatformPresence.actor_id == actor_id,
            ActorPlatformPresence.platform_username.isnot(None),
        )
        tu_result = await db.execute(target_usernames_stmt)
        target_usernames = [row[0] for row in tu_result.all() if row[0]]

        if target_usernames:
            shared_stmt = (
                select(Actor)
                .join(ActorPlatformPresence, ActorPlatformPresence.actor_id == Actor.id)
                .where(
                    ActorPlatformPresence.platform_username.in_(target_usernames),
                    Actor.id != actor_id,
                )
                .distinct()
                .limit(20)
            )
            shared_result = await db.execute(shared_stmt)
            for actor in shared_result.scalars().all():
                aid = str(actor.id)
                if aid not in candidates:
                    candidates[aid] = {
                        "actor_id": aid,
                        "canonical_name": actor.canonical_name,
                        "similarity": 1.0,
                        "match_reason": "shared_username",
                        "platforms": [],
                    }

        # ---- Strategy 3: Trigram similarity via pg_trgm ----
        # Ensure the extension exists (idempotent).
        await db.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

        trgm_stmt = text(
            """
            SELECT a.id::text,
                   a.canonical_name,
                   similarity(a.canonical_name, :target_name) AS sim
            FROM actors a
            WHERE a.id != :actor_id
              AND similarity(a.canonical_name, :target_name) > :threshold
            ORDER BY sim DESC
            LIMIT 20
            """
        )
        trgm_result = await db.execute(
            trgm_stmt,
            {
                "target_name": target.canonical_name,
                "actor_id": str(actor_id),
                "threshold": threshold,
            },
        )
        for row in trgm_result.all():
            aid = row[0]
            if aid not in candidates:
                candidates[aid] = {
                    "actor_id": aid,
                    "canonical_name": row[1],
                    "similarity": float(row[2]),
                    "match_reason": "trigram",
                    "platforms": [],
                }

        if not candidates:
            return []

        # Enrich with platform list for each candidate.
        candidate_ids = list(candidates.keys())
        pres_stmt = select(
            ActorPlatformPresence.actor_id,
            ActorPlatformPresence.platform,
        ).where(
            ActorPlatformPresence.actor_id.in_(
                [uuid.UUID(aid) for aid in candidate_ids]
            )
        )
        pres_result = await db.execute(pres_stmt)
        for row in pres_result.all():
            aid = str(row.actor_id)
            if aid in candidates and row.platform not in candidates[aid]["platforms"]:
                candidates[aid]["platforms"].append(row.platform)

        return sorted(candidates.values(), key=lambda x: x["similarity"], reverse=True)

    async def merge_actors(
        self,
        db: Any,
        canonical_id: uuid.UUID,
        duplicate_ids: list[uuid.UUID],
        performed_by: uuid.UUID,
    ) -> dict:
        """Merge duplicate actors into the canonical actor.

        Steps executed inside a single transaction:

        1. Re-point ``content_records.author_id`` from each duplicate to
           ``canonical_id``.
        2. Move ``ActorPlatformPresence`` rows to ``canonical_id``, skipping
           any that would violate the ``UNIQUE(platform, platform_user_id)``
           constraint (silently discarded — the canonical actor already has
           that presence).
        3. Create ``ActorAlias`` rows: one per duplicate, with
           ``alias = duplicate.canonical_name`` and
           ``source = 'entity_resolution'``.
        4. Delete the duplicate ``Actor`` rows (cascade deletes any remaining
           presences, list memberships, and aliases).

        Args:
            db: Active ``AsyncSession``.
            canonical_id: UUID of the actor to keep.
            duplicate_ids: UUIDs of actors to merge into the canonical.
            performed_by: UUID of the user who initiated the merge (for audit
                logging).

        Returns:
            Dict with keys:

            - ``merged`` (int): Number of duplicate actors removed.
            - ``records_updated`` (int): Content records re-pointed.
            - ``presences_moved`` (int): Platform presences migrated.
        """
        import structlog as _structlog
        from sqlalchemy import delete, select, update

        from issue_observatory.core.models.actors import (
            Actor,
            ActorAlias,
            ActorPlatformPresence,
        )
        from issue_observatory.core.models.content import UniversalContentRecord

        log = _structlog.get_logger(__name__).bind(
            event="entity_resolver.merge",
            canonical_id=str(canonical_id),
            performed_by=str(performed_by),
            duplicate_count=len(duplicate_ids),
        )

        records_updated = 0
        presences_moved = 0

        for dup_id in duplicate_ids:
            # Fetch the duplicate actor before deletion (need canonical_name).
            dup_result = await db.execute(select(Actor).where(Actor.id == dup_id))
            dup_actor: Actor | None = dup_result.scalar_one_or_none()
            if dup_actor is None:
                log.warning("merge.duplicate_not_found", duplicate_id=str(dup_id))
                continue

            # Step 1: Re-point content_records.author_id.
            update_content = (
                update(UniversalContentRecord)
                .where(UniversalContentRecord.author_id == dup_id)
                .values(author_id=canonical_id)
                .execution_options(synchronize_session=False)
            )
            cr_result = await db.execute(update_content)
            records_updated += cr_result.rowcount

            # Step 2: Move platform presences, skipping conflicts.
            pres_result = await db.execute(
                select(ActorPlatformPresence).where(
                    ActorPlatformPresence.actor_id == dup_id
                )
            )
            presences = pres_result.scalars().all()

            for pres in presences:
                # Check whether the canonical actor already has this (platform, user_id).
                conflict_result = await db.execute(
                    select(ActorPlatformPresence).where(
                        ActorPlatformPresence.actor_id == canonical_id,
                        ActorPlatformPresence.platform == pres.platform,
                        ActorPlatformPresence.platform_user_id == pres.platform_user_id,
                    )
                )
                if conflict_result.scalar_one_or_none() is not None:
                    # Canonical already has this presence — skip.
                    continue
                await db.execute(
                    update(ActorPlatformPresence)
                    .where(ActorPlatformPresence.id == pres.id)
                    .values(actor_id=canonical_id)
                    .execution_options(synchronize_session=False)
                )
                presences_moved += 1

            # Step 3: Create ActorAlias from the duplicate's canonical_name.
            alias = ActorAlias(
                actor_id=canonical_id,
                alias=dup_actor.canonical_name,
            )
            db.add(alias)
            try:
                await db.flush()
            except Exception:
                # Alias may already exist — rollback the flush and continue.
                await db.rollback()

            # Step 4: Delete the duplicate actor (cascade).
            await db.execute(
                delete(Actor).where(Actor.id == dup_id)
            )

        await db.commit()

        result = {
            "merged": len(duplicate_ids),
            "records_updated": records_updated,
            "presences_moved": presences_moved,
        }
        log.info("merge.complete", **result)
        return result

    async def split_actor(
        self,
        db: Any,
        actor_id: uuid.UUID,
        platform_presence_ids: list[uuid.UUID],
        new_canonical_name: str,
        performed_by: uuid.UUID,
    ) -> dict:
        """Split platform presences from an actor into a new actor record.

        Steps:

        1. Create a new ``Actor`` with ``new_canonical_name`` and
           ``created_by = performed_by``.
        2. Move the specified ``ActorPlatformPresence`` rows to the new actor.
        3. Re-point ``content_records.author_id`` for records whose
           ``author_platform_id`` matches one of the moved presences' user IDs.
        4. Create an ``ActorAlias`` on the original actor pointing to the new
           actor's name (``source='split'``).

        Args:
            db: Active ``AsyncSession``.
            actor_id: UUID of the actor to split from.
            platform_presence_ids: UUIDs of the presences to move to the new actor.
            new_canonical_name: Canonical name for the newly created actor.
            performed_by: UUID of the user who initiated the split.

        Returns:
            Dict with keys:

            - ``new_actor_id`` (str): UUID of the newly created actor.
            - ``presences_moved`` (int): Number of presences migrated.
            - ``records_updated`` (int): Content records re-pointed.
        """
        import structlog as _structlog
        from sqlalchemy import select, update

        from issue_observatory.core.models.actors import (
            Actor,
            ActorAlias,
            ActorPlatformPresence,
        )
        from issue_observatory.core.models.content import UniversalContentRecord

        log = _structlog.get_logger(__name__).bind(
            event="entity_resolver.split",
            actor_id=str(actor_id),
            performed_by=str(performed_by),
            presence_count=len(platform_presence_ids),
        )

        # Step 1: Create the new actor.
        new_actor = Actor(
            canonical_name=new_canonical_name,
            created_by=performed_by,
            is_shared=False,
        )
        db.add(new_actor)
        await db.flush()  # populate new_actor.id

        presences_moved = 0
        records_updated = 0

        # Step 2 & 3: Move presences and re-point content records.
        for pres_id in platform_presence_ids:
            pres_result = await db.execute(
                select(ActorPlatformPresence).where(
                    ActorPlatformPresence.id == pres_id,
                    ActorPlatformPresence.actor_id == actor_id,
                )
            )
            pres: ActorPlatformPresence | None = pres_result.scalar_one_or_none()
            if pres is None:
                log.warning("split.presence_not_found", presence_id=str(pres_id))
                continue

            # Capture the platform_user_id before moving the presence.
            puid = pres.platform_user_id

            # Move presence.
            await db.execute(
                update(ActorPlatformPresence)
                .where(ActorPlatformPresence.id == pres_id)
                .values(actor_id=new_actor.id)
                .execution_options(synchronize_session=False)
            )
            presences_moved += 1

            # Re-point content records authored via this presence.
            if puid:
                cr_result = await db.execute(
                    update(UniversalContentRecord)
                    .where(
                        UniversalContentRecord.author_platform_id == puid,
                        UniversalContentRecord.author_id == actor_id,
                    )
                    .values(author_id=new_actor.id)
                    .execution_options(synchronize_session=False)
                )
                records_updated += cr_result.rowcount

        # Step 4: Alias on original actor pointing to the split-off name.
        alias = ActorAlias(
            actor_id=actor_id,
            alias=new_canonical_name,
        )
        db.add(alias)
        try:
            await db.flush()
        except Exception:
            await db.rollback()

        await db.commit()

        result = {
            "new_actor_id": str(new_actor.id),
            "presences_moved": presences_moved,
            "records_updated": records_updated,
        }
        log.info("split.complete", **result)
        return result


# ---------------------------------------------------------------------------
# FastAPI dependency factory
# ---------------------------------------------------------------------------


def get_entity_resolver() -> EntityResolver:
    """FastAPI dependency factory returning a session-less stub.

    Routes that need a database-backed resolver must inject the session
    themselves and pass it to ``EntityResolver(session=db)``.

    Returns:
        A stub ``EntityResolver`` instance (no session).
    """
    return EntityResolver()
