"""Snowball sampling orchestrator.

Implements classic chain-referral (snowball) sampling starting from a set
of seed actors.  Each wave expands via ``NetworkExpander.expand_from_actor()``,
adds novel actors to the queue, and repeats until the configured depth or
actor budget is exhausted.

Key design properties:

- **Deduplication**: visited actors are tracked by a ``platform:user_id``
  key to avoid cycles and prevent the same account from being expanded
  more than once.
- **Per-step logging**: progress is logged at INFO level after each wave,
  with counts of new actors discovered and the discovery methods used.
- **Error isolation**: a failure expanding one actor does not abort the
  entire run — it is logged and skipped.
- **Configurable budget**: ``max_actors_per_step`` limits the number of
  new actors added at each depth level to prevent exponential blow-up in
  dense graphs.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from issue_observatory.sampling.network_expander import NetworkExpander, ActorDict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


class SnowballResult:
    """Result object returned by ``SnowballSampler.run()``.

    Attributes:
        actors: All discovered actors (seed + expanded), in order of
            discovery.  Each dict has the standard actor fields plus
            ``discovery_depth`` and ``discovery_method``.
        wave_log: Per-depth summary dict.  Keys are depth levels (0 for
            seeds, 1+ for expanded), values are dicts with ``discovered``
            (int) and ``methods`` (list of discovery method strings used).
        total_actors: Total number of unique actors in the result.
        max_depth_reached: The deepest level that was actually expanded.
    """

    def __init__(self) -> None:
        self.actors: list[dict[str, Any]] = []
        self.wave_log: dict[int, dict[str, Any]] = {}
        self.total_actors: int = 0
        self.max_depth_reached: int = 0

    def __repr__(self) -> str:
        return (
            f"<SnowballResult total_actors={self.total_actors} "
            f"max_depth={self.max_depth_reached}>"
        )


# ---------------------------------------------------------------------------
# SnowballSampler
# ---------------------------------------------------------------------------


class SnowballSampler:
    """Orchestrate iterative network expansion from seed actors.

    Uses ``NetworkExpander`` to discover new actors at each depth level.
    Novel actors (not yet seen) are added to the next wave's queue.

    Args:
        expander: A ``NetworkExpander`` instance.  When ``None``, a new
            instance is created using default settings.
    """

    def __init__(
        self,
        expander: Optional[NetworkExpander] = None,
    ) -> None:
        self._expander = expander or NetworkExpander()

    async def run(
        self,
        seed_actor_ids: list[uuid.UUID],
        platforms: list[str],
        db: Any,
        credential_pool: Optional[Any] = None,
        max_depth: int = 2,
        max_actors_per_step: int = 20,
    ) -> SnowballResult:
        """Run snowball sampling from the given seed actors.

        Starting from ``seed_actor_ids``, expands via
        ``NetworkExpander.expand_from_actor()`` up to ``max_depth``
        waves.  At each wave, at most ``max_actors_per_step`` novel actors
        are kept.  The seed actors themselves are included in the result
        at depth 0.

        Args:
            seed_actor_ids: UUIDs of the starting actors.
            platforms: Platform identifiers to expand on (e.g.
                ``["bluesky", "reddit"]``).
            db: An open ``AsyncSession``.
            credential_pool: Optional credential pool for platforms
                requiring authentication.
            max_depth: Maximum number of expansion waves after the seed
                level.  ``1`` means: expand each seed once.
            max_actors_per_step: Maximum number of novel actors to queue
                from each expansion wave.  Prevents exponential growth.

        Returns:
            A ``SnowballResult`` containing all discovered actors and a
            per-wave summary log.
        """
        result = SnowballResult()

        if not seed_actor_ids:
            logger.warning("SnowballSampler.run: no seed actors provided")
            return result

        # visited: set of "platform:user_id" strings for deduplication.
        # We also track actor UUIDs already queued for expansion.
        visited_keys: set[str] = set()
        visited_uuids: set[uuid.UUID] = set(seed_actor_ids)

        # Load seed actor presences and add them to the result at depth 0.
        seed_actors = await self._load_seed_actors(seed_actor_ids, db)
        for actor in seed_actors:
            key = f"{actor.get('platform', '')}:{actor.get('platform_user_id', '')}"
            visited_keys.add(key)
            actor["discovery_depth"] = 0
            result.actors.append(actor)

        result.wave_log[0] = {
            "discovered": len(seed_actors),
            "methods": ["seed"],
        }
        logger.info(
            "SnowballSampler wave 0 (seeds): %d actor(s)", len(seed_actors)
        )

        # Queue for next wave: list of (actor_uuid, [platform_user_id per platform])
        # We expand by actor UUID for depth waves 1+.
        current_wave_uuids: list[uuid.UUID] = list(seed_actor_ids)

        for depth in range(1, max_depth + 1):
            if not current_wave_uuids:
                logger.info(
                    "SnowballSampler: no actors to expand at depth %d — stopping",
                    depth,
                )
                break

            logger.info(
                "SnowballSampler wave %d: expanding %d actor(s)",
                depth,
                len(current_wave_uuids),
            )

            next_wave_dicts: list[ActorDict] = []
            methods_used: list[str] = []

            for actor_uuid in current_wave_uuids:
                try:
                    expansions = await self._expander.expand_from_actor(
                        actor_id=actor_uuid,
                        platforms=platforms,
                        db=db,
                        credential_pool=credential_pool,
                        depth=1,
                    )
                except Exception:
                    logger.exception(
                        "SnowballSampler: expand_from_actor failed for actor %s "
                        "at depth %d",
                        actor_uuid,
                        depth,
                    )
                    continue

                for candidate in expansions:
                    key = (
                        f"{candidate.get('platform', '')}:"
                        f"{candidate.get('platform_user_id', '')}"
                    )
                    if key in visited_keys:
                        continue
                    visited_keys.add(key)
                    candidate["discovery_depth"] = depth
                    next_wave_dicts.append(candidate)
                    method = candidate.get("discovery_method", "unknown")
                    if method not in methods_used:
                        methods_used.append(method)

                    if len(next_wave_dicts) >= max_actors_per_step:
                        break

                if len(next_wave_dicts) >= max_actors_per_step:
                    logger.debug(
                        "SnowballSampler: reached max_actors_per_step=%d at depth %d",
                        max_actors_per_step,
                        depth,
                    )
                    break

            # Record wave results.
            result.wave_log[depth] = {
                "discovered": len(next_wave_dicts),
                "methods": methods_used,
            }
            result.actors.extend(next_wave_dicts)
            result.max_depth_reached = depth

            logger.info(
                "SnowballSampler wave %d: discovered %d novel actor(s) via %s",
                depth,
                len(next_wave_dicts),
                methods_used or ["none"],
            )

            # Prepare next wave: only actors that have a UUID in the DB
            # can be expanded further.  Novel actors discovered via the
            # platform API do not yet have UUIDs — they must be resolved
            # first.  We therefore do not expand them in subsequent waves
            # unless the caller creates actor records and re-runs.
            #
            # For now, collect UUIDs of actors that were already in the
            # DB (identified by non-empty platform_user_id present in
            # actor_platform_presences).
            next_uuids = await self._resolve_uuids(next_wave_dicts, db)
            current_wave_uuids = [
                uid for uid in next_uuids if uid not in visited_uuids
            ]
            visited_uuids.update(current_wave_uuids)

            if not current_wave_uuids:
                logger.info(
                    "SnowballSampler: no resolvable UUIDs at depth %d — stopping",
                    depth,
                )
                break

        result.total_actors = len(result.actors)
        logger.info(
            "SnowballSampler complete: %d total actor(s) across %d wave(s)",
            result.total_actors,
            result.max_depth_reached,
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_seed_actors(
        self,
        actor_ids: list[uuid.UUID],
        db: Any,
    ) -> list[dict[str, Any]]:
        """Load seed actor records from the database.

        Fetches ``Actor`` and their ``ActorPlatformPresence`` rows for
        each seed UUID and returns them as actor dicts.  If the database
        is unavailable, returns minimal stub dicts keyed by UUID.

        Args:
            actor_ids: UUIDs of seed actors.
            db: An open ``AsyncSession`` or ``None``.

        Returns:
            List of actor dicts for the seeds.
        """
        if db is None:
            return [
                {
                    "canonical_name": str(uid),
                    "platform": "",
                    "platform_user_id": str(uid),
                    "platform_username": "",
                    "profile_url": "",
                    "discovery_method": "seed",
                    "actor_uuid": str(uid),
                }
                for uid in actor_ids
            ]

        results: list[dict[str, Any]] = []
        try:
            from sqlalchemy import select

            from issue_observatory.core.models.actors import (
                Actor,
                ActorPlatformPresence,
            )

            for uid in actor_ids:
                # Fetch actor row.
                actor_stmt = select(Actor).where(Actor.id == uid)
                actor_result = await db.execute(actor_stmt)
                actor_row = actor_result.scalar_one_or_none()

                canonical = actor_row.canonical_name if actor_row else str(uid)

                # Fetch first available platform presence.
                pres_stmt = select(ActorPlatformPresence).where(
                    ActorPlatformPresence.actor_id == uid
                )
                pres_result = await db.execute(pres_stmt)
                presences = pres_result.scalars().all()

                if presences:
                    # Emit one entry per presence so each platform link
                    # is visible in the result.
                    for pres in presences:
                        results.append(
                            {
                                "canonical_name": canonical,
                                "platform": pres.platform,
                                "platform_user_id": pres.platform_user_id or "",
                                "platform_username": pres.platform_username or "",
                                "profile_url": pres.profile_url or "",
                                "discovery_method": "seed",
                                "actor_uuid": str(uid),
                            }
                        )
                else:
                    results.append(
                        {
                            "canonical_name": canonical,
                            "platform": "",
                            "platform_user_id": str(uid),
                            "platform_username": "",
                            "profile_url": "",
                            "discovery_method": "seed",
                            "actor_uuid": str(uid),
                        }
                    )

        except Exception:
            logger.exception("_load_seed_actors: database query failed")

        return results

    async def _resolve_uuids(
        self,
        actor_dicts: list[ActorDict],
        db: Any,
    ) -> list[uuid.UUID]:
        """Resolve actor dicts to UUIDs via the actor_platform_presences table.

        Only actors whose ``(platform, platform_user_id)`` pair already
        exists in the database can be expanded in subsequent waves.

        Args:
            actor_dicts: List of actor dicts from the current wave.
            db: An open ``AsyncSession`` or ``None``.

        Returns:
            List of resolved actor UUIDs.
        """
        if db is None or not actor_dicts:
            return []

        uuids: list[uuid.UUID] = []
        try:
            from sqlalchemy import select

            from issue_observatory.core.models.actors import ActorPlatformPresence

            for actor in actor_dicts:
                platform = actor.get("platform", "")
                user_id = actor.get("platform_user_id", "")
                if not platform or not user_id:
                    continue

                stmt = select(ActorPlatformPresence.actor_id).where(
                    ActorPlatformPresence.platform == platform,
                    ActorPlatformPresence.platform_user_id == user_id,
                )
                result = await db.execute(stmt)
                actor_uuid = result.scalar_one_or_none()
                if actor_uuid is not None:
                    uuids.append(actor_uuid)

        except Exception:
            logger.exception("_resolve_uuids: database query failed")

        return uuids


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_snowball_sampler() -> SnowballSampler:
    """Factory function for FastAPI dependency injection.

    Returns:
        A ready-to-use ``SnowballSampler`` instance with a default
        ``NetworkExpander``.
    """
    return SnowballSampler()
