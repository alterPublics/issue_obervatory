"""Cross-platform entity resolution for actors.

The ``EntityResolver`` matches actors across platforms by platform presence
lookup, and provides ``create_or_update_presence()`` to establish new
actor records with their platform presences.

This is a **stub implementation** for Phase 0. It operates against the
database via the SQLAlchemy async session. Full fuzzy matching (Phase 3.9)
will add username-similarity and display-name heuristics; the interface
defined here is stable so that all arenas can use it from Phase 1 onward.

Phase 0 capabilities:
- Exact lookup by (platform, platform_user_id).
- Create actor + platform presence if the pair is not yet known.
- Return actor UUID for linking into ``content_records.author_id``.

Phase 3 additions (not yet implemented):
- ``find_similar_actors()``: fuzzy cross-platform matching.
- ``merge()``: collapse two actor records into one.
- ``split()``: separate a merged actor back into platform-specific records.
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
    # Public interface
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
