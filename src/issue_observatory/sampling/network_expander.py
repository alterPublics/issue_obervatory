"""Network-based actor expansion.

Discovers new actors connected to a known actor by traversing follower/
following graphs, mining co-mentions in the content_records table, and
applying platform-specific link-following heuristics.

Supported expansion strategies per platform:

- **Reddit**: fetch the actor's recent comment history and extract
  ``u/username`` mentions from comment bodies.
- **Bluesky**: call ``app.bsky.graph.getFollows`` and
  ``app.bsky.graph.getFollowers`` on the AT Protocol public API.
- **YouTube**: read the ``featuredChannelsUrls`` field from the
  channel resource's ``brandingSettings``.
- **Generic (all platforms)**: co-mention detection against
  ``content_records`` rows already stored in the database.

No arena collector classes are imported here — all platform HTTP calls
are made directly via ``httpx.AsyncClient`` to avoid circular imports.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type alias for the actor dict returned by all public methods
# ---------------------------------------------------------------------------

ActorDict = dict[str, str]

_ACTOR_DICT_FIELDS = (
    "canonical_name",
    "platform",
    "platform_user_id",
    "platform_username",
    "profile_url",
    "discovery_method",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BLUESKY_PUBLIC_API = "https://public.api.bsky.app/xrpc"
_REDDIT_API_BASE = "https://oauth.reddit.com"
_YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
_REDDIT_MENTION_RE = re.compile(r"(?<!\w)u/([A-Za-z0-9_-]{3,20})", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_actor_dict(
    canonical_name: str,
    platform: str,
    platform_user_id: str,
    platform_username: str,
    profile_url: str,
    discovery_method: str,
) -> ActorDict:
    """Build a well-typed actor discovery dict."""
    return {
        "canonical_name": canonical_name,
        "platform": platform,
        "platform_user_id": platform_user_id,
        "platform_username": platform_username,
        "profile_url": profile_url,
        "discovery_method": discovery_method,
    }


# ---------------------------------------------------------------------------
# NetworkExpander
# ---------------------------------------------------------------------------


class NetworkExpander:
    """Discover actors connected to a known actor via platform social graphs.

    This class is platform-aware but not tightly coupled to the arena
    collector implementations.  All HTTP calls use ``httpx.AsyncClient``
    directly.

    Args:
        http_client: An optional pre-configured ``httpx.AsyncClient``.
            When ``None`` (the default) a new client is created per method
            call.  Passing an explicit client enables test injection.
    """

    def __init__(
        self,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._http_client = http_client

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def expand_from_actor(
        self,
        actor_id: uuid.UUID,
        platforms: list[str],
        db: Any,
        credential_pool: Optional[Any] = None,
        depth: int = 1,
    ) -> list[ActorDict]:
        """Discover actors connected to *actor_id* on the given platforms.

        Runs one expansion wave per call (``depth`` is reserved for future
        multi-hop use; currently a single wave is executed regardless of
        value).

        Args:
            actor_id: UUID of the known actor in the ``actors`` table.
            platforms: Platform identifiers to expand on (e.g.
                ``["bluesky", "reddit", "youtube"]``).
            db: An open ``AsyncSession``.  Used to look up the actor's
                platform presences.
            credential_pool: Optional credential pool for platforms that
                require authentication (Reddit, YouTube).
            depth: Reserved.  Pass ``1`` for a single-hop expansion.

        Returns:
            List of actor dicts with ``discovery_method`` set to the
            expansion strategy used.
        """
        presences = await self._load_platform_presences(actor_id, db)
        discovered: list[ActorDict] = []

        for platform in platforms:
            presence = presences.get(platform)
            if presence is None:
                logger.debug(
                    "expand_from_actor: actor %s has no presence on %s — skipping",
                    actor_id,
                    platform,
                )
                continue

            try:
                if platform == "bluesky":
                    results = await self._expand_bluesky(
                        presence["platform_user_id"],
                        presence["platform_username"],
                    )
                elif platform == "reddit":
                    credentials = await self._get_credentials(
                        credential_pool, "reddit", "free"
                    )
                    results = await self._expand_reddit(
                        presence["platform_username"], credentials
                    )
                elif platform == "youtube":
                    credentials = await self._get_credentials(
                        credential_pool, "youtube", "free"
                    )
                    results = await self._expand_youtube(
                        presence["platform_user_id"], credentials
                    )
                else:
                    logger.debug(
                        "expand_from_actor: no platform-specific expander for %s; "
                        "using co-mention fallback",
                        platform,
                    )
                    results = []

                discovered.extend(results)
            except Exception:
                logger.exception(
                    "expand_from_actor: error expanding actor %s on platform %s",
                    actor_id,
                    platform,
                )

        return discovered

    async def find_co_mentioned_actors(
        self,
        query_design_id: uuid.UUID,
        db: Any,
        min_co_occurrences: int = 3,
    ) -> list[dict[str, Any]]:
        """Find actors that frequently appear together in collected content.

        Queries ``content_records`` for rows sharing the same
        ``query_design_id`` and counts pairs of ``author_platform_id``
        values that co-occur in the same ``search_terms_matched`` context.

        The implementation uses a self-join on ``content_records``:

        - For each pair of distinct ``author_platform_id`` values that both
          appear in records for the same ``query_design_id``, count the
          number of shared terms.
        - Pairs with ``count >= min_co_occurrences`` are returned.

        Args:
            query_design_id: UUID of the query design whose collected
                content should be searched.
            db: An open ``AsyncSession``.
            min_co_occurrences: Minimum number of term co-occurrences
                required for a pair to be returned.

        Returns:
            List of dicts with keys ``actor_a``, ``actor_b``,
            ``platform``, ``co_occurrence_count``.
        """
        if db is None:
            logger.warning(
                "find_co_mentioned_actors called without a database session — "
                "returning empty list"
            )
            return []

        try:
            from sqlalchemy import text

            sql = text(
                """
                SELECT
                    a.author_platform_id       AS actor_a,
                    b.author_platform_id       AS actor_b,
                    a.platform                 AS platform,
                    COUNT(*)                   AS co_occurrence_count
                FROM content_records AS a
                JOIN content_records AS b
                  ON  a.query_design_id = b.query_design_id
                  AND a.platform        = b.platform
                  AND a.author_platform_id IS NOT NULL
                  AND b.author_platform_id IS NOT NULL
                  AND a.author_platform_id < b.author_platform_id
                  AND a.search_terms_matched && b.search_terms_matched
                WHERE a.query_design_id = :qd_id
                GROUP BY a.author_platform_id, b.author_platform_id, a.platform
                HAVING COUNT(*) >= :min_co
                ORDER BY co_occurrence_count DESC
                """
            )
            result = await db.execute(
                sql,
                {"qd_id": str(query_design_id), "min_co": min_co_occurrences},
            )
            rows = result.fetchall()
            return [
                {
                    "actor_a": row.actor_a,
                    "actor_b": row.actor_b,
                    "platform": row.platform,
                    "co_occurrence_count": row.co_occurrence_count,
                }
                for row in rows
            ]
        except Exception:
            logger.exception(
                "find_co_mentioned_actors: database query failed for query_design_id=%s",
                query_design_id,
            )
            return []

    async def suggest_for_actor_list(
        self,
        actor_list_id: uuid.UUID,
        db: Any,
        credential_pool: Optional[Any] = None,
    ) -> list[ActorDict]:
        """Suggest new actors for an existing actor list.

        Loads all actors in the list, runs ``expand_from_actor()`` for
        each across all platforms on which they have a presence, and
        returns novel actors not already in the list.

        Args:
            actor_list_id: UUID of the ``ActorList`` to expand.
            db: An open ``AsyncSession``.
            credential_pool: Optional credential pool.

        Returns:
            Deduplicated list of actor dicts not already in the list.
        """
        if db is None:
            logger.warning(
                "suggest_for_actor_list called without a database session — "
                "returning empty list"
            )
            return []

        try:
            from sqlalchemy import select

            from issue_observatory.core.models.actors import (
                ActorListMember,
                ActorPlatformPresence,
            )

            # Load existing actor IDs in the list.
            stmt = select(ActorListMember.actor_id).where(
                ActorListMember.actor_list_id == actor_list_id
            )
            result = await db.execute(stmt)
            existing_ids: set[uuid.UUID] = {row[0] for row in result.fetchall()}

            if not existing_ids:
                logger.info(
                    "suggest_for_actor_list: actor list %s is empty", actor_list_id
                )
                return []

            # Determine which platforms each actor has a presence on.
            stmt2 = select(
                ActorPlatformPresence.actor_id,
                ActorPlatformPresence.platform,
            ).where(ActorPlatformPresence.actor_id.in_(existing_ids))
            result2 = await db.execute(stmt2)
            actor_platforms: dict[uuid.UUID, list[str]] = {}
            for row in result2.fetchall():
                actor_platforms.setdefault(row.actor_id, []).append(row.platform)

        except Exception:
            logger.exception(
                "suggest_for_actor_list: failed to load actor list %s", actor_list_id
            )
            return []

        # Run expansion for each actor.
        seen_ids: set[str] = set()
        novel: list[ActorDict] = []

        for actor_id, platforms in actor_platforms.items():
            expansions = await self.expand_from_actor(
                actor_id, platforms, db, credential_pool, depth=1
            )
            for candidate in expansions:
                key = f"{candidate['platform']}:{candidate['platform_user_id']}"
                if key not in seen_ids:
                    seen_ids.add(key)
                    novel.append(candidate)

        logger.info(
            "suggest_for_actor_list: discovered %d novel actor(s) for list %s",
            len(novel),
            actor_list_id,
        )
        return novel

    # ------------------------------------------------------------------
    # Platform-specific expanders (private)
    # ------------------------------------------------------------------

    async def _expand_bluesky(
        self,
        did: str,
        handle: str,
    ) -> list[ActorDict]:
        """Expand a Bluesky actor via follows and followers lists.

        Calls ``app.bsky.graph.getFollows`` and
        ``app.bsky.graph.getFollowers`` on the public AT Protocol API.
        Paginates until all results are fetched (up to 500 per direction).

        Args:
            did: The actor's DID (decentralised identifier).
            handle: The actor's handle (e.g. ``"alice.bsky.social"``).

        Returns:
            List of actor dicts with ``discovery_method`` set to
            ``"bluesky_follows"`` or ``"bluesky_followers"``.
        """
        results: list[ActorDict] = []
        actor_str = did or handle

        for endpoint, method_label in (
            ("getFollows", "bluesky_follows"),
            ("getFollowers", "bluesky_followers"),
        ):
            cursor: Optional[str] = None
            fetched = 0
            max_per_direction = 500

            while fetched < max_per_direction:
                params: dict[str, Any] = {"actor": actor_str, "limit": 100}
                if cursor:
                    params["cursor"] = cursor

                data = await self._get_json(
                    f"{_BLUESKY_PUBLIC_API}/app.bsky.graph.{endpoint}", params
                )
                if data is None:
                    break

                key = "follows" if endpoint == "getFollows" else "followers"
                profiles: list[dict[str, Any]] = data.get(key, [])
                if not profiles:
                    break

                for profile in profiles:
                    a_did = profile.get("did", "")
                    a_handle = profile.get("handle", "")
                    display_name = profile.get("displayName") or a_handle
                    results.append(
                        _make_actor_dict(
                            canonical_name=display_name,
                            platform="bluesky",
                            platform_user_id=a_did,
                            platform_username=a_handle,
                            profile_url=f"https://bsky.app/profile/{a_handle}",
                            discovery_method=method_label,
                        )
                    )
                    fetched += 1

                cursor = data.get("cursor")
                if not cursor:
                    break

        logger.debug(
            "_expand_bluesky: found %d actors for %s", len(results), actor_str
        )
        return results

    async def _expand_reddit(
        self,
        username: str,
        credentials: Optional[dict[str, str]],
    ) -> list[ActorDict]:
        """Expand a Reddit actor by mining u/ mentions in their comments.

        Fetches the last 100 comments from the user's profile and extracts
        ``u/username`` patterns via regex.

        Args:
            username: Reddit username (without the ``u/`` prefix).
            credentials: Dict with keys ``client_id``, ``client_secret``,
                ``user_agent``.  If ``None``, the public read-only JSON
                API is used (anonymous, limited to 1 req/sec).

        Returns:
            List of actor dicts with ``discovery_method`` set to
            ``"reddit_comment_mention"``.
        """
        mentioned: dict[str, ActorDict] = {}

        # Prefer authenticated API; fall back to public endpoint.
        if credentials:
            base = _REDDIT_API_BASE
            headers: dict[str, str] = {
                "User-Agent": credentials.get("user_agent", "IssueObservatory/1.0")
            }
            # Bearer token flow not implemented here (requires OAuth dance).
            # Use public JSON endpoint instead and treat credentials as optional.
            _ = credentials
            base = "https://www.reddit.com"
            headers = {"User-Agent": credentials.get("user_agent", "IssueObservatory/1.0")}
        else:
            base = "https://www.reddit.com"
            headers = {"User-Agent": "IssueObservatory/1.0 (research)"}

        url = f"{base}/user/{username}/comments.json"
        data = await self._get_json(url, {"limit": 100, "raw_json": 1}, headers=headers)
        if data is None:
            return []

        children: list[dict[str, Any]] = (
            data.get("data", {}).get("children", [])
        )
        for child in children:
            body: str = child.get("data", {}).get("body", "")
            for match in _REDDIT_MENTION_RE.finditer(body):
                mentioned_user = match.group(1)
                if mentioned_user.lower() == username.lower():
                    continue  # skip self-mentions
                key = mentioned_user.lower()
                if key not in mentioned:
                    mentioned[key] = _make_actor_dict(
                        canonical_name=f"u/{mentioned_user}",
                        platform="reddit",
                        platform_user_id=mentioned_user,
                        platform_username=mentioned_user,
                        profile_url=f"https://www.reddit.com/u/{mentioned_user}",
                        discovery_method="reddit_comment_mention",
                    )

        logger.debug(
            "_expand_reddit: found %d mentioned users for u/%s",
            len(mentioned),
            username,
        )
        return list(mentioned.values())

    async def _expand_youtube(
        self,
        channel_id: str,
        credentials: Optional[dict[str, str]],
    ) -> list[ActorDict]:
        """Expand a YouTube actor via featured channels metadata.

        Calls the YouTube Data API v3 ``channels.list`` endpoint and
        reads the ``featuredChannelsUrls`` array from
        ``brandingSettings``.

        Args:
            channel_id: YouTube channel ID (e.g. ``"UCxxxxxx"``).
            credentials: Dict with key ``api_key``.  If ``None``, the
                expansion is skipped and an empty list is returned.

        Returns:
            List of actor dicts with ``discovery_method`` set to
            ``"youtube_featured_channels"``.
        """
        if not credentials or not credentials.get("api_key"):
            logger.debug(
                "_expand_youtube: no credentials available for channel %s — skipping",
                channel_id,
            )
            return []

        params = {
            "part": "brandingSettings",
            "id": channel_id,
            "key": credentials["api_key"],
        }
        data = await self._get_json(f"{_YOUTUBE_API_BASE}/channels", params)
        if data is None:
            return []

        items: list[dict[str, Any]] = data.get("items", [])
        if not items:
            return []

        branding = items[0].get("brandingSettings", {})
        channel_info = branding.get("channel", {})
        featured_urls: list[str] = channel_info.get("featuredChannelsUrls", [])

        results: list[ActorDict] = []
        for url in featured_urls:
            # Attempt to extract a channel ID from the URL.
            # Common forms: https://www.youtube.com/channel/UCxxxxxx
            #               https://www.youtube.com/@handle
            channel_id_match = re.search(r"/channel/(UC[A-Za-z0-9_-]{22})", url)
            handle_match = re.search(r"/@([A-Za-z0-9_.%-]+)", url)

            if channel_id_match:
                feat_id = channel_id_match.group(1)
                results.append(
                    _make_actor_dict(
                        canonical_name=feat_id,
                        platform="youtube",
                        platform_user_id=feat_id,
                        platform_username=feat_id,
                        profile_url=f"https://www.youtube.com/channel/{feat_id}",
                        discovery_method="youtube_featured_channels",
                    )
                )
            elif handle_match:
                handle = handle_match.group(1)
                results.append(
                    _make_actor_dict(
                        canonical_name=f"@{handle}",
                        platform="youtube",
                        platform_user_id=handle,
                        platform_username=handle,
                        profile_url=f"https://www.youtube.com/@{handle}",
                        discovery_method="youtube_featured_channels",
                    )
                )

        logger.debug(
            "_expand_youtube: found %d featured channels for %s",
            len(results),
            channel_id,
        )
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_platform_presences(
        self,
        actor_id: uuid.UUID,
        db: Any,
    ) -> dict[str, dict[str, str]]:
        """Return a mapping of platform → presence fields for *actor_id*.

        Args:
            actor_id: UUID of the actor.
            db: An open ``AsyncSession``.

        Returns:
            Dict keyed by platform name, values are dicts with
            ``platform_user_id``, ``platform_username``, ``profile_url``.
        """
        if db is None:
            return {}

        try:
            from sqlalchemy import select

            from issue_observatory.core.models.actors import ActorPlatformPresence

            stmt = select(ActorPlatformPresence).where(
                ActorPlatformPresence.actor_id == actor_id
            )
            result = await db.execute(stmt)
            rows = result.scalars().all()
            return {
                row.platform: {
                    "platform_user_id": row.platform_user_id or "",
                    "platform_username": row.platform_username or "",
                    "profile_url": row.profile_url or "",
                }
                for row in rows
            }
        except Exception:
            logger.exception(
                "_load_platform_presences: failed for actor_id=%s", actor_id
            )
            return {}

    async def _get_credentials(
        self,
        credential_pool: Optional[Any],
        platform: str,
        tier: str,
    ) -> Optional[dict[str, str]]:
        """Acquire credentials from the pool, returning ``None`` on failure.

        Args:
            credential_pool: A ``CredentialPool`` instance or ``None``.
            platform: Platform identifier (e.g. ``"reddit"``).
            tier: Tier identifier (e.g. ``"free"``).

        Returns:
            Credential dict or ``None`` if not available.
        """
        if credential_pool is None:
            return None
        try:
            cred = await credential_pool.acquire(platform=platform, tier=tier)
            return cred
        except Exception:
            logger.debug(
                "_get_credentials: could not acquire %s/%s credential", platform, tier
            )
            return None

    async def _get_json(
        self,
        url: str,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Optional[dict[str, Any]]:
        """Perform a GET request and return the parsed JSON body.

        Uses the injected ``_http_client`` if available; otherwise creates
        a transient ``httpx.AsyncClient``.

        Args:
            url: Target URL.
            params: Query parameters.
            headers: Additional HTTP headers.

        Returns:
            Parsed JSON dict, or ``None`` on any error.
        """
        request_headers = {"User-Agent": "IssueObservatory/1.0 (research)"}
        if headers:
            request_headers.update(headers)

        try:
            if self._http_client is not None:
                response = await self._http_client.get(
                    url, params=params, headers=request_headers
                )
                response.raise_for_status()
                return response.json()  # type: ignore[no-any-return]
            else:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(
                        url, params=params, headers=request_headers
                    )
                    response.raise_for_status()
                    return response.json()  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "_get_json: HTTP %d from %s", exc.response.status_code, url
            )
            return None
        except Exception:
            logger.exception("_get_json: request failed for %s", url)
            return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_network_expander() -> NetworkExpander:
    """Factory function for FastAPI dependency injection.

    Returns a ``NetworkExpander`` instance with a default
    ``httpx.AsyncClient``.  The client is created fresh each call;
    for production use, inject a shared client at the application
    lifespan level.

    Returns:
        A ready-to-use ``NetworkExpander`` instance.
    """
    return NetworkExpander()
