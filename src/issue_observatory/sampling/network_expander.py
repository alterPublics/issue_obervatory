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
- **Telegram**: forwarding chain analysis against ``content_records``
  rows already stored in the database.  Messages stored with
  ``raw_metadata.is_forwarded = true`` and a ``fwd_from_channel_id``
  reveal which external channels the seed channel frequently forwards
  from.  Those source channels are high-value discovery targets.
  Falls back to co-mention detection when no forwarding data exists.
- **TikTok**: call TikTok Research API ``/v2/research/user/followers/``
  and ``/v2/research/user/following/`` via OAuth client credentials.
- **Gab**: Mastodon-compatible API — lookup account ID, then paginate
  ``/api/v1/accounts/{id}/followers`` and ``/following``.
- **X/Twitter**: TwitterAPI.io ``/twitter/user/followers`` and
  ``/twitter/user/followings`` with cursor pagination.
- **Generic (all platforms)**: co-mention detection against
  ``content_records`` rows already stored in the database, augmented with
  URL-based co-mention (extracting platform links via ``link_miner``).
  This is the fallback strategy for Discord, Threads, Instagram,
  Facebook, and any other platform not explicitly handled above.

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
_TIKTOK_OAUTH_URL = "https://open.tiktokapis.com/v2/oauth/token/"
_TIKTOK_FOLLOWERS_URL = "https://open.tiktokapis.com/v2/research/user/followers/"
_TIKTOK_FOLLOWING_URL = "https://open.tiktokapis.com/v2/research/user/following/"

_GAB_API_BASE = "https://gab.com/api/v1"

_TWITTERAPIIO_FOLLOWERS_URL = "https://api.twitterapi.io/twitter/user/followers"
_TWITTERAPIIO_FOLLOWING_URL = "https://api.twitterapi.io/twitter/user/followings"

_REDDIT_MENTION_RE = re.compile(r"(?<!\w)u/([A-Za-z0-9_-]{3,20})", re.IGNORECASE)

# Regex that captures @-style mentions across major platforms.
# Covers:
#   @handle               (Twitter/X, Threads, Instagram, Gab, Mastodon, TikTok)
#   @handle.domain.tld    (Bluesky/AT Protocol)
#   @handle.subdomain     (any federated platform)
# The pattern deliberately avoids matching email addresses (preceded by word
# characters) to reduce false positives.
_COMENTION_MENTION_RE = re.compile(
    r"(?<!\w)@([A-Za-z0-9_](?:[A-Za-z0-9_.%-]{0,48}[A-Za-z0-9_])?)",
    re.UNICODE,
)

# Mapping from link_miner platform slugs to the platform identifiers used in
# the actor system.  Used by the URL co-mention detection in
# _expand_via_comention() to resolve discovered URLs to platform actors.
_URL_PLATFORM_MAP: dict[str, str] = {
    "twitter": "x_twitter",
    "bluesky": "bluesky",
    "youtube": "youtube",
    "tiktok": "tiktok",
    "gab": "gab",
    "instagram": "instagram",
    "telegram": "telegram",
    "reddit_user": "reddit",
}

# Minimum number of distinct content records in which a username must appear
# alongside the seed actor before it is considered a significant co-mention.
_COMENTION_MIN_RECORDS: int = 2

# Maximum co-mentioned actors returned by _expand_via_comention().
_COMENTION_TOP_N: int = 50


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
        min_comention_records: int = _COMENTION_MIN_RECORDS,
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
                elif platform == "telegram":
                    results = await self._expand_via_telegram_forwarding(
                        actor_id=actor_id,
                        platform=platform,
                        presence=presence,
                        db=db,
                        depth=depth,
                    )
                    if not results:
                        # Fall through to co-mention if no forwarding data
                        # has been collected yet for this channel.
                        logger.debug(
                            "expand_from_actor: no Telegram forwarding data for "
                            "actor %s — falling back to co-mention",
                            actor_id,
                        )
                        results = await self._expand_via_comention(
                            actor_id=actor_id,
                            platform=platform,
                            presence=presence,
                            db=db,
                            min_records=min_comention_records,
                        )
                elif platform == "tiktok":
                    credentials = await self._get_credentials(
                        credential_pool, "tiktok", "free"
                    )
                    results = await self._expand_tiktok(
                        presence["platform_username"], credentials
                    )
                elif platform == "gab":
                    credentials = await self._get_credentials(
                        credential_pool, "gab", "free"
                    )
                    results = await self._expand_gab(
                        presence["platform_username"], credentials
                    )
                elif platform == "x_twitter":
                    credentials = await self._get_credentials(
                        credential_pool, "twitterapi_io", "medium"
                    )
                    results = await self._expand_x_twitter(
                        presence["platform_username"], credentials
                    )
                elif platform in ("facebook", "instagram", "threads"):
                    # No public social graph API exists for these platforms;
                    # use co-mention detection against stored content records.
                    results = await self._expand_via_comention(
                        actor_id=actor_id,
                        platform=platform,
                        presence=presence,
                        db=db,
                        min_records=min_comention_records,
                    )
                else:
                    logger.debug(
                        "expand_from_actor: no platform-specific expander for %s; "
                        "using co-mention fallback",
                        platform,
                    )
                    results = await self._expand_via_comention(
                        actor_id=actor_id,
                        platform=platform,
                        presence=presence,
                        db=db,
                        min_records=min_comention_records,
                    )

                discovered.extend(results)
            except Exception:
                logger.exception(
                    "expand_from_actor: error expanding actor %s on platform %s",
                    actor_id,
                    platform,
                )

        # Cross-platform content link mining: search content authored by this
        # actor across ALL platforms (not scoped to a single platform) and
        # extract URLs that point to other actors on known platforms.
        try:
            link_results = await self._expand_via_content_links(
                actor_id=actor_id,
                presences=presences,
                db=db,
            )
            # Deduplicate against actors already found by platform-specific expanders.
            existing_keys: set[str] = {
                f"{d['platform']}:{d['platform_user_id']}" for d in discovered
            }
            for actor_dict in link_results:
                key = f"{actor_dict['platform']}:{actor_dict['platform_user_id']}"
                if key not in existing_keys:
                    existing_keys.add(key)
                    discovered.append(actor_dict)
        except Exception:
            logger.exception(
                "expand_from_actor: content link mining failed for actor %s",
                actor_id,
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
    # Telegram-specific expander — forwarding chain analysis
    # ------------------------------------------------------------------

    async def _expand_via_telegram_forwarding(
        self,
        actor_id: uuid.UUID,
        platform: str,
        presence: dict[str, str],
        db: Any,
        top_n: int = 20,
        min_forwards: int = 2,
        depth: int = 1,
    ) -> list[ActorDict]:
        """Discover Telegram channels via forwarding chain analysis.

        Queries ``content_records`` for Telegram messages from the seed actor's
        channel that were forwarded from other channels (``is_forwarded = true``
        in ``raw_metadata``), extracts the ``fwd_from_channel_id`` values, counts
        their frequency, and returns the most frequent source channels as
        discovery candidates.

        A channel that the seed channel frequently forwards from is a strong
        thematic affinity signal — it is worth monitoring directly.

        The query uses PostgreSQL JSONB operators for efficiency:

        - ``raw_metadata ->> 'is_forwarded' = 'true'`` — selects forwarded msgs.
        - ``raw_metadata ? 'fwd_from_channel_id'`` — ensures the source channel
          ID is present before extracting it.

        Args:
            actor_id: UUID of the seed Actor (used for logging and to match
                the ``author_id`` FK when present, otherwise falls back to
                matching ``author_platform_id``).
            platform: Should be ``"telegram"``.  Passed through for logging
                and to populate the returned ``ActorDict`` records.
            presence: The actor's platform presence dict (keys:
                ``platform_user_id``, ``platform_username``, ``profile_url``).
                The ``platform_user_id`` is used to scope the query to the
                seed channel's own messages.
            db: An open ``AsyncSession``.  When ``None`` an empty list is
                returned immediately.
            top_n: Maximum number of source channels to return, sorted by
                forward count descending.
            min_forwards: Minimum number of distinct messages forwarded from
                a channel for it to be included in the results.
            depth: Current expansion depth.  Used to populate the
                ``depth`` field on returned dicts (set to ``depth + 1``).

        Returns:
            List of ``ActorDict``-compatible dicts with ``discovery_method``
            set to ``"telegram_forwarding_chain"``, ordered by forward count
            descending (most-forwarded source channel first).  An extra
            ``forward_count`` key is included on each dict for downstream use.
        """
        if db is None:
            logger.debug(
                "_expand_via_telegram_forwarding: no DB session for actor %s",
                actor_id,
            )
            return []

        user_id = presence.get("platform_user_id", "").strip()
        username = presence.get("platform_username", "").strip()

        # We need at least one identifier to scope the query to the seed channel.
        if not user_id and not username:
            logger.debug(
                "_expand_via_telegram_forwarding: actor %s has no platform_user_id "
                "or platform_username — cannot scope query",
                actor_id,
            )
            return []

        try:
            from sqlalchemy import text

            # Build an author filter: match either author_platform_id or the
            # actor FK.  We use OR so that both indexed paths are tried.
            # Raw SQL is used rather than the ORM because JSONB ->> and ?
            # operators are awkward to express portably via mapped_column().
            #
            # Conditions:
            #   platform = 'telegram'
            #   (author_platform_id = :user_id OR author_id = :actor_id)
            #   raw_metadata ->> 'is_forwarded' = 'true'
            #   raw_metadata ? 'fwd_from_channel_id'
            #
            # We then extract raw_metadata ->> 'fwd_from_channel_id' for each
            # matching row and count occurrences per source channel in SQL.
            # Doing the count server-side avoids pulling thousands of rows
            # into Python just to count strings.

            if user_id:
                author_filter = (
                    "(author_platform_id = :user_id OR author_id = CAST(:actor_id AS uuid))"
                )
            else:
                # No numeric user_id — match only by actor UUID FK.
                author_filter = "author_id = CAST(:actor_id AS uuid)"

            sql = text(
                f"""
                SELECT
                    raw_metadata ->> 'fwd_from_channel_id' AS fwd_channel_id,
                    COUNT(*)                               AS fwd_count
                FROM content_records
                WHERE platform = 'telegram'
                  AND {author_filter}
                  AND raw_metadata ->> 'is_forwarded' = 'true'
                  AND raw_metadata ? 'fwd_from_channel_id'
                  AND raw_metadata ->> 'fwd_from_channel_id' IS NOT NULL
                  AND raw_metadata ->> 'fwd_from_channel_id' <> ''
                GROUP BY fwd_channel_id
                HAVING COUNT(*) >= :min_forwards
                ORDER BY fwd_count DESC
                LIMIT :top_n
                """
            )

            params: dict[str, Any] = {
                "actor_id": str(actor_id),
                "min_forwards": min_forwards,
                "top_n": top_n,
            }
            if user_id:
                params["user_id"] = user_id

            result = await db.execute(sql, params)
            rows = result.fetchall()

        except Exception:
            logger.exception(
                "_expand_via_telegram_forwarding: DB query failed for actor %s",
                actor_id,
            )
            return []

        if not rows:
            logger.debug(
                "_expand_via_telegram_forwarding: no forwarding data found for "
                "actor %s on telegram",
                actor_id,
            )
            return []

        results: list[ActorDict] = []
        next_depth = depth + 1

        for row in rows:
            fwd_channel_id: str = str(row.fwd_channel_id)
            fwd_count: int = int(row.fwd_count)

            actor_dict = _make_actor_dict(
                canonical_name=f"Telegram Channel {fwd_channel_id}",
                platform="telegram",
                platform_user_id=fwd_channel_id,
                platform_username=fwd_channel_id,
                profile_url="",
                discovery_method="telegram_forwarding_chain",
            )
            # Attach forwarding-specific metadata beyond the standard ActorDict
            # fields.  Callers that understand these extra keys can use them;
            # callers that only consume the standard fields can ignore them.
            actor_dict["display_name"] = f"Telegram Channel {fwd_channel_id}"
            actor_dict["forward_count"] = str(fwd_count)
            actor_dict["depth"] = str(next_depth)

            results.append(actor_dict)

        logger.debug(
            "_expand_via_telegram_forwarding: found %d source channel(s) for "
            "actor %s (min_forwards=%d, top_n=%d)",
            len(results),
            actor_id,
            min_forwards,
            top_n,
        )
        return results

    # ------------------------------------------------------------------
    # TikTok graph expander
    # ------------------------------------------------------------------

    async def _get_tiktok_token(
        self,
        client_key: str,
        client_secret: str,
    ) -> Optional[str]:
        """Obtain a TikTok Research API bearer token via client credentials.

        The TikTok OAuth endpoint only accepts ``application/x-www-form-urlencoded``
        requests, so this method sends form data instead of JSON.

        Args:
            client_key: TikTok application client key.
            client_secret: TikTok application client secret.

        Returns:
            Bearer token string, or ``None`` on failure.
        """
        form_data = {
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    _TIKTOK_OAUTH_URL,
                    data=form_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                result = response.json()
            return result.get("access_token")
        except Exception:
            logger.exception("_get_tiktok_token: OAuth token request failed")
            return None

    async def _expand_tiktok(
        self,
        username: str,
        credentials: Optional[dict[str, str]],
    ) -> list[ActorDict]:
        """Expand a TikTok actor via Research API follower/following endpoints.

        Uses OAuth 2.0 client credentials flow to obtain a bearer token, then
        paginates ``POST /v2/research/user/followers/`` and
        ``/v2/research/user/following/`` (max 500 per direction).

        Args:
            username: TikTok username (without ``@`` prefix).
            credentials: Dict with keys ``client_key`` and ``client_secret``.

        Returns:
            List of actor dicts with ``discovery_method`` set to
            ``"tiktok_followers"`` or ``"tiktok_following"``.
        """
        if not credentials or not credentials.get("client_key"):
            logger.debug(
                "_expand_tiktok: no credentials for @%s — skipping", username
            )
            return []

        token = await self._get_tiktok_token(
            credentials["client_key"], credentials["client_secret"]
        )
        if not token:
            logger.warning("_expand_tiktok: failed to obtain OAuth token")
            return []

        results: list[ActorDict] = []
        headers = {"Authorization": f"Bearer {token}"}

        for url, method_label in (
            (_TIKTOK_FOLLOWERS_URL, "tiktok_followers"),
            (_TIKTOK_FOLLOWING_URL, "tiktok_following"),
        ):
            cursor: int = 0
            fetched = 0
            max_per_direction = 500

            while fetched < max_per_direction:
                body: dict[str, Any] = {
                    "username": username,
                    "max_count": 100,
                }
                if cursor:
                    body["cursor"] = cursor

                data = await self._post_json(url, json_body=body, headers=headers)
                if data is None:
                    break

                inner = data.get("data", {})
                users: list[dict[str, Any]] = (
                    inner.get("user_followers")
                    or inner.get("user_following")
                    or inner.get("users")
                    or []
                )
                if not users:
                    break

                for user in users:
                    u_name = user.get("username", "")
                    display = user.get("display_name") or u_name
                    results.append(
                        _make_actor_dict(
                            canonical_name=display,
                            platform="tiktok",
                            platform_user_id=u_name,
                            platform_username=u_name,
                            profile_url=f"https://www.tiktok.com/@{u_name}",
                            discovery_method=method_label,
                        )
                    )
                    fetched += 1

                cursor = data.get("data", {}).get("cursor", 0)
                if not data.get("data", {}).get("has_more", False):
                    break

        logger.debug(
            "_expand_tiktok: found %d actors for @%s", len(results), username
        )
        return results

    # ------------------------------------------------------------------
    # Gab graph expander (Mastodon-compatible API)
    # ------------------------------------------------------------------

    async def _expand_gab(
        self,
        username: str,
        credentials: Optional[dict[str, str]],
    ) -> list[ActorDict]:
        """Expand a Gab actor via Mastodon-compatible follower/following API.

        First looks up the account ID via ``GET /api/v1/accounts/lookup``,
        then paginates followers and following lists using Mastodon ``max_id``
        cursor (max 40 per page).

        Args:
            username: Gab username.
            credentials: Optional dict with key ``access_token``.

        Returns:
            List of actor dicts with ``discovery_method`` set to
            ``"gab_followers"`` or ``"gab_following"``.
        """
        headers: dict[str, str] = {}
        if credentials and credentials.get("access_token"):
            headers["Authorization"] = f"Bearer {credentials['access_token']}"

        # Step 1: Look up account ID.
        lookup = await self._get_json(
            f"{_GAB_API_BASE}/accounts/lookup",
            params={"acct": username},
            headers=headers,
        )
        if lookup is None or not lookup.get("id"):
            logger.debug(
                "_expand_gab: account lookup failed for %s", username
            )
            return []

        account_id = lookup["id"]
        results: list[ActorDict] = []

        # Step 2: Paginate followers and following.
        for endpoint, method_label in (
            ("followers", "gab_followers"),
            ("following", "gab_following"),
        ):
            max_id: Optional[str] = None
            fetched = 0
            max_per_direction = 500

            while fetched < max_per_direction:
                params: dict[str, Any] = {"limit": 40}
                if max_id:
                    params["max_id"] = max_id

                accounts_data = await self._get_json_list(
                    f"{_GAB_API_BASE}/accounts/{account_id}/{endpoint}",
                    params=params,
                    headers=headers,
                )
                if accounts_data is None:
                    break

                accounts: list[dict[str, Any]] = accounts_data
                if not accounts:
                    break

                for acct in accounts:
                    acct_id = str(acct.get("id", ""))
                    acct_name = acct.get("acct", acct.get("username", ""))
                    display = acct.get("display_name") or acct_name
                    results.append(
                        _make_actor_dict(
                            canonical_name=display,
                            platform="gab",
                            platform_user_id=acct_id,
                            platform_username=acct_name,
                            profile_url=acct.get("url", f"https://gab.com/{acct_name}"),
                            discovery_method=method_label,
                        )
                    )
                    fetched += 1

                # Mastodon-style pagination: use the last item's ID as max_id.
                max_id = str(accounts[-1].get("id", ""))
                if len(accounts) < 40:
                    break

        logger.debug(
            "_expand_gab: found %d actors for %s", len(results), username
        )
        return results

    # ------------------------------------------------------------------
    # X/Twitter graph expander (via TwitterAPI.io)
    # ------------------------------------------------------------------

    async def _expand_x_twitter(
        self,
        username: str,
        credentials: Optional[dict[str, str]],
    ) -> list[ActorDict]:
        """Expand an X/Twitter actor via TwitterAPI.io follower/following endpoints.

        Paginates ``GET /twitter/user/followers`` and ``/twitter/user/followings``
        with cursor-based pagination. Requires a TwitterAPI.io API key.

        Args:
            username: X/Twitter username (without ``@``).
            credentials: Dict with key ``api_key``.

        Returns:
            List of actor dicts with ``discovery_method`` set to
            ``"x_twitter_followers"`` or ``"x_twitter_following"``.
        """
        if not credentials or not credentials.get("api_key"):
            logger.debug(
                "_expand_x_twitter: no credentials for @%s — skipping", username
            )
            return []

        headers = {"X-API-Key": credentials["api_key"]}
        results: list[ActorDict] = []

        for url, method_label in (
            (_TWITTERAPIIO_FOLLOWERS_URL, "x_twitter_followers"),
            (_TWITTERAPIIO_FOLLOWING_URL, "x_twitter_following"),
        ):
            cursor: Optional[str] = None
            fetched = 0
            max_per_direction = 500

            while fetched < max_per_direction:
                params: dict[str, Any] = {"userName": username}
                if cursor:
                    params["cursor"] = cursor

                data = await self._get_json(url, params=params, headers=headers)
                if data is None:
                    break

                # TwitterAPI.io returns "followers" or "followings" (not "users").
                users: list[dict[str, Any]] = (
                    data.get("followers")
                    or data.get("followings")
                    or data.get("users")
                    or []
                )
                if not users:
                    break

                for user in users:
                    screen_name = user.get("userName", user.get("screen_name", ""))
                    user_id = str(user.get("id", user.get("userId", "")))
                    display = user.get("name", screen_name)
                    results.append(
                        _make_actor_dict(
                            canonical_name=display,
                            platform="x_twitter",
                            platform_user_id=user_id,
                            platform_username=screen_name,
                            profile_url=f"https://x.com/{screen_name}",
                            discovery_method=method_label,
                        )
                    )
                    fetched += 1

                cursor = data.get("next_cursor")
                if not cursor:
                    break

        logger.debug(
            "_expand_x_twitter: found %d actors for @%s", len(results), username
        )
        return results

    # ------------------------------------------------------------------
    # Cross-platform content link mining expander
    # ------------------------------------------------------------------

    async def _expand_via_content_links(
        self,
        actor_id: uuid.UUID,
        presences: dict[str, dict[str, str]],
        db: Any,
        top_n: int = 50,
        min_records: int = 1,
    ) -> list[ActorDict]:
        """Discover actors by mining URLs from content authored by *actor_id*.

        Unlike ``_expand_via_comention()`` which scopes its content query to a
        single platform, this method searches across **all** platforms the actor
        has posted on.  It extracts URLs from ``text_content``, classifies them
        via ``link_miner``, and maps them to platform actors.  This makes
        cross-platform links visible -- e.g. a YouTube description linking to a
        Twitter account.

        Args:
            actor_id: UUID of the seed actor.
            presences: All platform presences for this actor (keyed by platform).
            db: An open ``AsyncSession``.
            top_n: Maximum number of discovered actors to return.
            min_records: Minimum distinct content records in which a URL target
                must appear to be included.

        Returns:
            List of actor dicts with ``discovery_method`` set to
            ``"content_link_mining"``.
        """
        if db is None:
            return []

        # Collect all user identifiers across platforms for the author filter.
        user_ids: list[str] = []
        for presence in presences.values():
            uid = presence.get("platform_user_id", "").strip()
            if uid:
                user_ids.append(uid)
            uname = presence.get("platform_username", "").strip()
            if uname and uname != uid:
                user_ids.append(uname)

        if not user_ids:
            logger.debug(
                "_expand_via_content_links: actor %s has no identifiers", actor_id
            )
            return []

        try:
            from sqlalchemy import text

            # Build parameterized IN clause for user identifiers.
            id_placeholders = ", ".join(f":uid{i}" for i in range(len(user_ids)))
            params: dict[str, Any] = {"actor_id": str(actor_id)}
            for i, uid in enumerate(user_ids):
                params[f"uid{i}"] = uid

            sql = text(
                f"""
                SELECT id, text_content
                FROM content_records
                WHERE text_content IS NOT NULL
                  AND (
                      author_platform_id IN ({id_placeholders})
                      OR author_id = CAST(:actor_id AS uuid)
                  )
                LIMIT 5000
                """
            )
            result = await db.execute(sql, params)
            rows = result.fetchall()
        except Exception:
            logger.exception(
                "_expand_via_content_links: DB query failed for actor %s", actor_id
            )
            return []

        if not rows:
            logger.debug(
                "_expand_via_content_links: no content records for actor %s", actor_id
            )
            return []

        # Lazy-import link_miner helpers.
        try:
            from issue_observatory.analysis.link_miner import (
                _classify_url,
                _extract_urls,
            )
        except ImportError:
            logger.debug("_expand_via_content_links: link_miner not available")
            return []

        # Build a set of the actor's own identifiers to exclude self-links.
        own_identifiers: set[str] = set()
        for presence in presences.values():
            uid = presence.get("platform_user_id", "").strip()
            if uid:
                own_identifiers.add(uid.lower())
            uname = presence.get("platform_username", "").strip()
            if uname:
                own_identifiers.add(uname.lower())

        # Extract and classify URLs from all content records.
        # url_targets[(platform, target)] = set of record IDs
        url_targets: dict[tuple[str, str], set[str]] = {}

        for row in rows:
            record_id = str(row.id)
            text_content: str = row.text_content or ""

            for url in _extract_urls(text_content):
                url_platform, target = _classify_url(url)
                actor_platform = _URL_PLATFORM_MAP.get(url_platform)
                if actor_platform is None:
                    continue
                target_lower = target.lower()
                # Skip self-links.
                if target_lower in own_identifiers:
                    continue
                url_targets.setdefault(
                    (actor_platform, target_lower), set()
                ).add(record_id)

        # Filter and sort by record count.
        qualified: list[tuple[tuple[str, str], int]] = [
            (key, len(record_set))
            for key, record_set in url_targets.items()
            if len(record_set) >= min_records
        ]
        qualified.sort(key=lambda x: x[1], reverse=True)
        qualified = qualified[:top_n]

        results: list[ActorDict] = []
        for (target_platform, target_id), _count in qualified:
            results.append(
                _make_actor_dict(
                    canonical_name=target_id,
                    platform=target_platform,
                    platform_user_id=target_id,
                    platform_username=target_id,
                    profile_url="",
                    discovery_method="content_link_mining",
                )
            )

        logger.debug(
            "_expand_via_content_links: found %d linked actor(s) across %d "
            "content records for actor %s",
            len(results),
            len(rows),
            actor_id,
        )
        return results

    # ------------------------------------------------------------------
    # Co-mention fallback expander (platform-agnostic)
    # ------------------------------------------------------------------

    async def _expand_via_comention(
        self,
        actor_id: uuid.UUID,
        platform: str,
        presence: dict[str, str],
        db: Any,
        top_n: int = _COMENTION_TOP_N,
        min_records: int = _COMENTION_MIN_RECORDS,
    ) -> list[ActorDict]:
        """Expand an actor by mining co-mentions in stored content records.

        Searches ``content_records.text_content`` for records that mention the
        seed actor's platform username.  Within those records, all other
        ``@username`` patterns are extracted and counted.  Usernames that
        co-occur in at least ``min_records`` distinct content records are
        returned as discovered actors.

        This method is the catch-all fallback for platforms that do not have a
        dedicated graph-traversal strategy (Telegram, Discord, TikTok, Gab,
        X/Twitter, Threads, Instagram, Facebook, etc.).

        Args:
            actor_id: UUID of the seed actor (used only for logging).
            platform: Platform identifier (e.g. ``"telegram"``).  Used to
                scope the content-records query and to populate the returned
                ``ActorDict`` records.
            presence: The actor's platform presence dict (keys:
                ``platform_user_id``, ``platform_username``, ``profile_url``).
            db: An open ``AsyncSession``.  When ``None`` an empty list is
                returned immediately.
            top_n: Maximum number of co-mentioned actors to return.
            min_records: Minimum number of distinct ``content_records`` rows
                in which a username must appear alongside the seed actor.

        Returns:
            List of actor dicts with ``discovery_method`` set to
            ``"comention_fallback"``, ordered by co-occurrence frequency
            (most frequent first).
        """
        if db is None:
            logger.debug(
                "_expand_via_comention: no DB session for actor %s on %s",
                actor_id,
                platform,
            )
            return []

        username = presence.get("platform_username", "").strip()
        user_id = presence.get("platform_user_id", "").strip()

        # We need at least one identifier to search for.
        if not username and not user_id:
            logger.debug(
                "_expand_via_comention: actor %s has no username or user_id on %s",
                actor_id,
                platform,
            )
            return []

        # Build a list of search tokens: @username variants we will look for.
        # We search using ILIKE (case-insensitive) with the LIKE operator so
        # that a plain SQL call works without regex support in PostgreSQL text
        # search.  A separate full-regex pass is applied in Python afterwards.
        seed_tokens: list[str] = []
        if username:
            seed_tokens.append(f"@{username}")
        if user_id and user_id != username:
            seed_tokens.append(f"@{user_id}")

        try:
            from sqlalchemy import text

            # Step 1: Fetch IDs and text of content records that mention the
            # seed actor on the target platform.  We use OR across the seed
            # tokens so that either the username or user_id handle triggers a
            # match.
            #
            # ILIKE pattern: '%@username%' — simple substring match, then we
            # re-validate with the Python regex below to avoid false positives.
            ilike_clauses = " OR ".join(
                f"text_content ILIKE :tok{i}" for i, _ in enumerate(seed_tokens)
            )
            params: dict[str, Any] = {"platform": platform}
            for i, tok in enumerate(seed_tokens):
                params[f"tok{i}"] = f"%{tok}%"

            seed_sql = text(
                f"""
                SELECT id, text_content
                FROM content_records
                WHERE platform = :platform
                  AND text_content IS NOT NULL
                  AND ({ilike_clauses})
                LIMIT 5000
                """
            )
            seed_result = await db.execute(seed_sql, params)
            seed_rows = seed_result.fetchall()

        except Exception:
            logger.exception(
                "_expand_via_comention: DB query (step 1) failed for actor %s "
                "on platform %s",
                actor_id,
                platform,
            )
            return []

        if not seed_rows:
            logger.debug(
                "_expand_via_comention: no content records mention actor %s on %s",
                actor_id,
                platform,
            )
            return []

        # Step 2: In Python, extract all @mentions from those records and count
        # how many *distinct* records each co-mentioned username appears in.
        seed_usernames_lower: set[str] = {tok.lstrip("@").lower() for tok in seed_tokens}

        # co_record_ids[username_lower] = set of record IDs where it appears
        co_record_ids: dict[str, set[str]] = {}
        # URL-based co-mention: track (platform, target_username) -> record IDs
        url_co_record_ids: dict[tuple[str, str], set[str]] = {}

        # Lazy-import link_miner helpers for URL extraction.
        try:
            from issue_observatory.analysis.link_miner import (
                _classify_url,
                _extract_urls,
            )
            has_link_miner = True
        except ImportError:
            has_link_miner = False

        for row in seed_rows:
            record_id = str(row.id)
            text_content: str = row.text_content or ""

            # First confirm this record actually mentions the seed actor via
            # regex (eliminates substring false positives like @usernamefoo
            # matching a search for @username).
            seed_confirmed = any(
                m.group(1).lower() in seed_usernames_lower
                for m in _COMENTION_MENTION_RE.finditer(text_content)
            )
            if not seed_confirmed:
                continue

            # Now collect all OTHER @mentions in this record.
            for match in _COMENTION_MENTION_RE.finditer(text_content):
                candidate = match.group(1).lower()
                if candidate in seed_usernames_lower:
                    continue  # skip the seed actor itself
                co_record_ids.setdefault(candidate, set()).add(record_id)

            # URL-based co-mention: extract URLs and classify them.
            if has_link_miner:
                for url in _extract_urls(text_content):
                    url_platform, target = _classify_url(url)
                    actor_platform = _URL_PLATFORM_MAP.get(url_platform)
                    if actor_platform is None:
                        continue
                    target_lower = target.lower()
                    # Skip if the URL target is the seed actor itself.
                    if target_lower in seed_usernames_lower:
                        continue
                    url_co_record_ids.setdefault(
                        (actor_platform, target_lower), set()
                    ).add(record_id)

        # Step 3: Filter to candidates that appear in >= min_records distinct
        # records, then sort by frequency descending and take top_n.
        qualified: list[tuple[str, int]] = [
            (username_lower, len(record_set))
            for username_lower, record_set in co_record_ids.items()
            if len(record_set) >= min_records
        ]
        qualified.sort(key=lambda x: x[1], reverse=True)
        qualified = qualified[:top_n]

        results: list[ActorDict] = []
        for comentioned_username, record_count in qualified:
            results.append(
                _make_actor_dict(
                    canonical_name=f"@{comentioned_username}",
                    platform=platform,
                    platform_user_id=comentioned_username,
                    platform_username=comentioned_username,
                    profile_url="",
                    discovery_method="comention_fallback",
                )
            )

        # Merge URL-discovered candidates (these may be on different platforms).
        seen_mention_keys: set[str] = {
            f"{platform}:{u}" for u, _ in qualified
        }
        url_qualified: list[tuple[tuple[str, str], int]] = [
            (key, len(record_set))
            for key, record_set in url_co_record_ids.items()
            if len(record_set) >= min_records
        ]
        url_qualified.sort(key=lambda x: x[1], reverse=True)

        for (url_platform, url_target), record_count in url_qualified:
            dedup_key = f"{url_platform}:{url_target}"
            if dedup_key in seen_mention_keys:
                continue
            seen_mention_keys.add(dedup_key)
            results.append(
                _make_actor_dict(
                    canonical_name=url_target,
                    platform=url_platform,
                    platform_user_id=url_target,
                    platform_username=url_target,
                    profile_url="",
                    discovery_method="url_comention",
                )
            )
            if len(results) >= top_n:
                break

        logger.debug(
            "_expand_via_comention: found %d co-mentioned actor(s) for %s on %s "
            "(searched %d content records, %d via @mention, %d via URL)",
            len(results),
            actor_id,
            platform,
            len(seed_rows),
            len(qualified),
            len([r for r in results if r["discovery_method"] == "url_comention"]),
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

    async def _get_json_list(
        self,
        url: str,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Optional[list[dict[str, Any]]]:
        """Perform a GET request and return the parsed JSON list body.

        Like ``_get_json`` but for endpoints that return a JSON array
        (e.g. Mastodon-compatible APIs).

        Args:
            url: Target URL.
            params: Query parameters.
            headers: Additional HTTP headers.

        Returns:
            Parsed JSON list, or ``None`` on any error.
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
                "_get_json_list: HTTP %d from %s", exc.response.status_code, url
            )
            return None
        except Exception:
            logger.exception("_get_json_list: request failed for %s", url)
            return None

    async def _post_json(
        self,
        url: str,
        json_body: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Optional[dict[str, Any]]:
        """Perform a POST request and return the parsed JSON body.

        Uses the injected ``_http_client`` if available; otherwise creates
        a transient ``httpx.AsyncClient``.

        Args:
            url: Target URL.
            json_body: JSON request body.
            headers: Additional HTTP headers.

        Returns:
            Parsed JSON dict, or ``None`` on any error.
        """
        request_headers = {"User-Agent": "IssueObservatory/1.0 (research)"}
        if headers:
            request_headers.update(headers)

        try:
            if self._http_client is not None:
                response = await self._http_client.post(
                    url, json=json_body, headers=request_headers
                )
                response.raise_for_status()
                return response.json()  # type: ignore[no-any-return]
            else:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        url, json=json_body, headers=request_headers
                    )
                    response.raise_for_status()
                    return response.json()  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "_post_json: HTTP %d from %s", exc.response.status_code, url
            )
            return None
        except Exception:
            logger.exception("_post_json: request failed for %s", url)
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
