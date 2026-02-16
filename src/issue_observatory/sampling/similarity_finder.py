"""Similarity-based actor discovery.

Finds actors similar to a known actor using three complementary strategies:

1. **Platform recommendations** (``find_similar_by_platform``): calls
   native platform endpoints that return "similar" or "suggested" accounts.

   - Bluesky: ``app.bsky.graph.getSuggestedFollowsByActor``
   - Reddit: find subreddits the actor posted in, then find other top
     posters in those subreddits.
   - YouTube: read ``relatedPlaylists`` from the channel resource, then
     extract channel IDs from playlist items.

2. **Content similarity** (``find_similar_by_content``): TF-IDF cosine
   similarity on ``text_content`` from collected posts.  Falls back to
   word-overlap Jaccard similarity when ``scikit-learn`` is not installed.

3. **Cross-platform name matching** (``cross_platform_match``): search for
   a name or handle string across specified platforms and return candidate
   matches with confidence scores.

No arena collector classes are imported — all HTTP calls are made directly
via ``httpx.AsyncClient`` to avoid circular imports.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import Counter
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

ActorDict = dict[str, Any]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BLUESKY_PUBLIC_API = "https://public.api.bsky.app/xrpc"
_REDDIT_PUBLIC_API = "https://www.reddit.com"
_YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

# Minimum word count for text content to be included in TF-IDF computation.
_MIN_WORD_COUNT = 5


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
    similarity_score: Optional[float] = None,
) -> ActorDict:
    """Build a well-typed actor similarity dict."""
    result: ActorDict = {
        "canonical_name": canonical_name,
        "platform": platform,
        "platform_user_id": platform_user_id,
        "platform_username": platform_username,
        "profile_url": profile_url,
        "discovery_method": discovery_method,
    }
    if similarity_score is not None:
        result["similarity_score"] = similarity_score
    return result


def _tokenize(text: str) -> list[str]:
    """Tokenize *text* into lowercase word tokens.

    Args:
        text: Raw text string.

    Returns:
        List of lowercase alpha-numeric tokens (length >= 2).
    """
    return [t for t in re.findall(r"\b[a-z0-9æøå]{2,}\b", text.lower())]


def _word_overlap_similarity(tokens_a: list[str], tokens_b: list[str]) -> float:
    """Compute Jaccard similarity between two token lists.

    Args:
        tokens_a: Token list for document A.
        tokens_b: Token list for document B.

    Returns:
        Jaccard coefficient in ``[0.0, 1.0]``.
    """
    if not tokens_a or not tokens_b:
        return 0.0
    set_a = set(tokens_a)
    set_b = set(tokens_b)
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def _tfidf_cosine(
    target_tokens: list[str],
    other_tokens_list: list[tuple[str, list[str]]],
) -> list[tuple[str, float]]:
    """Compute TF-IDF cosine similarity using scikit-learn.

    Falls back to word-overlap Jaccard if scikit-learn is unavailable.

    Args:
        target_tokens: Token list for the target actor's combined posts.
        other_tokens_list: List of ``(actor_id_str, tokens)`` pairs for
            candidate actors.

    Returns:
        List of ``(actor_id_str, similarity_score)`` pairs, descending.
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore[import-not-found]
        from sklearn.metrics.pairwise import cosine_similarity  # type: ignore[import-not-found]

        docs = [" ".join(target_tokens)] + [
            " ".join(tokens) for _, tokens in other_tokens_list
        ]
        vectorizer = TfidfVectorizer(
            min_df=1,
            sublinear_tf=True,
            analyzer="word",
            token_pattern=r"\b[a-z0-9æøå]{2,}\b",
        )
        matrix = vectorizer.fit_transform(docs)
        sims = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
        return [
            (actor_id, float(score))
            for (actor_id, _), score in zip(other_tokens_list, sims)
        ]

    except ImportError:
        logger.warning(
            "scikit-learn is not installed; falling back to word-overlap similarity. "
            "Install with: pip install 'issue-observatory[ml]'"
        )
        return [
            (actor_id, _word_overlap_similarity(target_tokens, tokens))
            for actor_id, tokens in other_tokens_list
        ]


# ---------------------------------------------------------------------------
# SimilarityFinder
# ---------------------------------------------------------------------------


class SimilarityFinder:
    """Discover actors similar to a known actor across platforms.

    This class is platform-aware but does not import arena collectors,
    avoiding circular dependency issues.  All HTTP calls use
    ``httpx.AsyncClient`` directly.

    Args:
        http_client: An optional pre-configured ``httpx.AsyncClient``.
            When ``None`` (the default) a new client is created per
            method call.  Passing an explicit client enables test injection.
    """

    def __init__(
        self,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._http_client = http_client

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def find_similar_by_platform(
        self,
        actor_id: uuid.UUID,
        platform: str,
        credential_pool: Optional[Any] = None,
        db: Optional[Any] = None,
        top_n: int = 25,
    ) -> list[ActorDict]:
        """Find actors similar to *actor_id* using platform recommendations.

        Dispatches to the correct platform-specific implementation.

        Args:
            actor_id: UUID of the actor in the ``actors`` table.
            platform: Platform identifier (``"bluesky"``, ``"reddit"``,
                ``"youtube"``).
            credential_pool: Optional credential pool for authenticated
                platforms.
            db: An open ``AsyncSession`` — required to look up the actor's
                platform presence.
            top_n: Maximum number of similar actors to return.

        Returns:
            List of actor dicts with ``discovery_method`` and optionally
            ``similarity_score``.
        """
        presence = await self._get_presence(actor_id, platform, db)
        if presence is None:
            logger.debug(
                "find_similar_by_platform: actor %s has no presence on %s",
                actor_id,
                platform,
            )
            return []

        credentials = await self._get_credentials(credential_pool, platform, "free")

        try:
            if platform == "bluesky":
                return await self._similar_bluesky(
                    presence["platform_user_id"],
                    presence["platform_username"],
                    top_n,
                )
            elif platform == "reddit":
                return await self._similar_reddit(
                    presence["platform_username"],
                    credentials,
                    top_n,
                )
            elif platform == "youtube":
                return await self._similar_youtube(
                    presence["platform_user_id"],
                    credentials,
                    top_n,
                )
            else:
                logger.info(
                    "find_similar_by_platform: no platform-specific similarity "
                    "implementation for '%s'",
                    platform,
                )
                return []
        except Exception:
            logger.exception(
                "find_similar_by_platform: error for actor %s on platform %s",
                actor_id,
                platform,
            )
            return []

    async def find_similar_by_content(
        self,
        actor_id: uuid.UUID,
        db: Any,
        top_n: int = 10,
    ) -> list[ActorDict]:
        """Find actors with similar content to *actor_id*.

        Retrieves ``text_content`` from ``content_records`` for the target
        actor and for all other actors that have at least
        ``_MIN_WORD_COUNT`` tokens, then ranks by TF-IDF cosine similarity
        (or Jaccard word overlap when scikit-learn is unavailable).

        Args:
            actor_id: UUID of the actor whose content forms the query.
            db: An open ``AsyncSession``.
            top_n: Number of most-similar actors to return.

        Returns:
            List of dicts with keys ``actor_id``, ``similarity_score``,
            ``platform`` (from first matching presence), plus the standard
            actor dict fields where available.
        """
        if db is None:
            logger.warning(
                "find_similar_by_content called without a database session"
            )
            return []

        # Step 1: fetch text_content for the target actor.
        target_tokens = await self._fetch_actor_tokens(actor_id, db)
        if len(target_tokens) < _MIN_WORD_COUNT:
            logger.info(
                "find_similar_by_content: actor %s has too little content "
                "(%d tokens); skipping",
                actor_id,
                len(target_tokens),
            )
            return []

        # Step 2: fetch tokens for all other actors with collected content.
        try:
            from sqlalchemy import text

            sql = text(
                """
                SELECT
                    cr.author_id,
                    cr.platform,
                    STRING_AGG(cr.text_content, ' ') AS combined_text
                FROM content_records AS cr
                WHERE cr.author_id IS NOT NULL
                  AND cr.author_id != :target_id
                  AND cr.text_content IS NOT NULL
                  AND LENGTH(cr.text_content) > 0
                GROUP BY cr.author_id, cr.platform
                HAVING LENGTH(STRING_AGG(cr.text_content, ' ')) > 50
                LIMIT 500
                """
            )
            result = await db.execute(sql, {"target_id": str(actor_id)})
            rows = result.fetchall()
        except Exception:
            logger.exception(
                "find_similar_by_content: DB query failed for actor %s", actor_id
            )
            return []

        if not rows:
            return []

        # Build (actor_id_str, tokens) pairs.
        candidates: list[tuple[str, list[str]]] = []
        candidate_platform: dict[str, str] = {}
        for row in rows:
            tokens = _tokenize(row.combined_text or "")
            if len(tokens) >= _MIN_WORD_COUNT:
                id_str = str(row.author_id)
                candidates.append((id_str, tokens))
                candidate_platform[id_str] = row.platform or ""

        if not candidates:
            return []

        # Compute similarity scores.
        scored = _tfidf_cosine(target_tokens, candidates)
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:top_n]

        return [
            {
                "actor_id": actor_id_str,
                "similarity_score": round(score, 4),
                "platform": candidate_platform.get(actor_id_str, ""),
                "discovery_method": "content_similarity",
                "canonical_name": "",
                "platform_user_id": "",
                "platform_username": "",
                "profile_url": "",
            }
            for actor_id_str, score in top
            if score > 0.0
        ]

    async def cross_platform_match(
        self,
        name_or_handle: str,
        platforms: list[str],
        credential_pool: Optional[Any] = None,
        top_n: int = 5,
    ) -> list[ActorDict]:
        """Search for a name/handle across multiple platforms.

        Attempts a lookup/search on each platform and returns candidate
        matches with a confidence score computed from string similarity
        between the query and the returned username/display name.

        Args:
            name_or_handle: Name or handle to search for (e.g.
                ``"drdk"`` or ``"DR Nyheder"``).
            platforms: Platforms to search (e.g.
                ``["bluesky", "reddit", "youtube"]``).
            credential_pool: Optional credential pool for authenticated
                platforms.
            top_n: Maximum number of candidates to return per platform.

        Returns:
            List of actor dicts with ``confidence_score`` added.
        """
        results: list[ActorDict] = []

        for platform in platforms:
            credentials = await self._get_credentials(
                credential_pool, platform, "free"
            )
            try:
                if platform == "bluesky":
                    candidates = await self._search_bluesky(
                        name_or_handle, top_n
                    )
                elif platform == "reddit":
                    candidates = await self._search_reddit(
                        name_or_handle, credentials, top_n
                    )
                elif platform == "youtube":
                    candidates = await self._search_youtube(
                        name_or_handle, credentials, top_n
                    )
                else:
                    logger.debug(
                        "cross_platform_match: no search implementation for '%s'",
                        platform,
                    )
                    candidates = []

                results.extend(candidates)
            except Exception:
                logger.exception(
                    "cross_platform_match: error searching '%s' on %s",
                    name_or_handle,
                    platform,
                )

        return results

    # ------------------------------------------------------------------
    # Platform-specific similarity (private)
    # ------------------------------------------------------------------

    async def _similar_bluesky(
        self,
        did: str,
        handle: str,
        top_n: int,
    ) -> list[ActorDict]:
        """Call ``app.bsky.graph.getSuggestedFollowsByActor`` on Bluesky.

        Args:
            did: Actor's DID.
            handle: Actor's handle.
            top_n: Maximum number of suggestions to return.

        Returns:
            List of actor dicts with ``discovery_method`` set to
            ``"bluesky_suggested_follows"``.
        """
        actor_str = did or handle
        params: dict[str, Any] = {"actor": actor_str, "limit": min(top_n, 25)}
        data = await self._get_json(
            f"{_BLUESKY_PUBLIC_API}/app.bsky.graph.getSuggestedFollowsByActor",
            params,
        )
        if data is None:
            return []

        suggestions: list[dict[str, Any]] = data.get("suggestions", [])
        return [
            _make_actor_dict(
                canonical_name=s.get("displayName") or s.get("handle", ""),
                platform="bluesky",
                platform_user_id=s.get("did", ""),
                platform_username=s.get("handle", ""),
                profile_url=f"https://bsky.app/profile/{s.get('handle', '')}",
                discovery_method="bluesky_suggested_follows",
            )
            for s in suggestions[:top_n]
        ]

    async def _similar_reddit(
        self,
        username: str,
        credentials: Optional[dict[str, str]],
        top_n: int,
    ) -> list[ActorDict]:
        """Find similar Reddit users via shared subreddits.

        Fetches the subreddits the actor posted in (from their submission
        history), then retrieves the top posters in each of those
        subreddits.

        Args:
            username: Reddit username (without ``u/`` prefix).
            credentials: Optional credential dict.
            top_n: Maximum number of similar users to return.

        Returns:
            List of actor dicts with ``discovery_method`` set to
            ``"reddit_shared_subreddit"``.
        """
        ua = (
            credentials.get("user_agent", "IssueObservatory/1.0")
            if credentials
            else "IssueObservatory/1.0 (research)"
        )
        headers = {"User-Agent": ua}

        # Fetch the user's 10 most recent submissions to find their subreddits.
        submissions_data = await self._get_json(
            f"{_REDDIT_PUBLIC_API}/user/{username}/submitted.json",
            {"limit": 25, "raw_json": 1},
            headers=headers,
        )
        if submissions_data is None:
            return []

        subreddits: set[str] = set()
        for child in submissions_data.get("data", {}).get("children", []):
            sr = child.get("data", {}).get("subreddit")
            if sr:
                subreddits.add(sr)

        if not subreddits:
            return []

        # For each subreddit, fetch top 10 posters.
        found: dict[str, ActorDict] = {}
        for subreddit in list(subreddits)[:3]:  # limit to 3 subreddits
            if len(found) >= top_n:
                break
            posts_data = await self._get_json(
                f"{_REDDIT_PUBLIC_API}/r/{subreddit}/top.json",
                {"limit": 25, "raw_json": 1, "t": "month"},
                headers=headers,
            )
            if posts_data is None:
                continue
            for child in posts_data.get("data", {}).get("children", []):
                post_author: Optional[str] = child.get("data", {}).get("author")
                if not post_author or post_author == username:
                    continue
                if post_author in ("[deleted]", "[removed]"):
                    continue
                key = post_author.lower()
                if key not in found:
                    found[key] = _make_actor_dict(
                        canonical_name=f"u/{post_author}",
                        platform="reddit",
                        platform_user_id=post_author,
                        platform_username=post_author,
                        profile_url=f"https://www.reddit.com/u/{post_author}",
                        discovery_method="reddit_shared_subreddit",
                    )
                if len(found) >= top_n:
                    break

        return list(found.values())[:top_n]

    async def _similar_youtube(
        self,
        channel_id: str,
        credentials: Optional[dict[str, str]],
        top_n: int,
    ) -> list[ActorDict]:
        """Find similar YouTube channels via related playlists.

        Reads the ``relatedPlaylists`` map from the channel's
        ``contentDetails`` resource, then fetches playlist items to
        discover associated channel IDs.

        Args:
            channel_id: YouTube channel ID (``"UCxxxxxx"``).
            credentials: Dict with key ``api_key``.
            top_n: Maximum number of channels to return.

        Returns:
            List of actor dicts with ``discovery_method`` set to
            ``"youtube_related_playlist"``.
        """
        if not credentials or not credentials.get("api_key"):
            return []

        api_key = credentials["api_key"]

        # Fetch the channel's contentDetails to get relatedPlaylists.
        ch_data = await self._get_json(
            f"{_YOUTUBE_API_BASE}/channels",
            {"part": "contentDetails", "id": channel_id, "key": api_key},
        )
        if ch_data is None:
            return []

        items = ch_data.get("items", [])
        if not items:
            return []

        related: dict[str, str] = (
            items[0].get("contentDetails", {}).get("relatedPlaylists", {})
        )
        uploads_playlist = related.get("uploads")
        if not uploads_playlist:
            return []

        # Fetch items from the uploads playlist to find video authors.
        # Each playlistItem carries a ``videoOwnerChannelId``.
        pl_data = await self._get_json(
            f"{_YOUTUBE_API_BASE}/playlistItems",
            {
                "part": "snippet",
                "playlistId": uploads_playlist,
                "maxResults": 50,
                "key": api_key,
            },
        )
        if pl_data is None:
            return []

        seen: dict[str, ActorDict] = {}
        for item in pl_data.get("items", []):
            snippet = item.get("snippet", {})
            owner_id: Optional[str] = snippet.get("videoOwnerChannelId")
            owner_title: Optional[str] = snippet.get("videoOwnerChannelTitle")
            if not owner_id or owner_id == channel_id:
                continue
            if owner_id not in seen:
                seen[owner_id] = _make_actor_dict(
                    canonical_name=owner_title or owner_id,
                    platform="youtube",
                    platform_user_id=owner_id,
                    platform_username=owner_id,
                    profile_url=f"https://www.youtube.com/channel/{owner_id}",
                    discovery_method="youtube_related_playlist",
                )
            if len(seen) >= top_n:
                break

        return list(seen.values())[:top_n]

    # ------------------------------------------------------------------
    # Cross-platform search helpers (private)
    # ------------------------------------------------------------------

    async def _search_bluesky(
        self,
        query: str,
        top_n: int,
    ) -> list[ActorDict]:
        """Search Bluesky for actors matching *query*.

        Uses the ``app.bsky.actor.searchActors`` endpoint.

        Args:
            query: Name or handle to search.
            top_n: Maximum results.

        Returns:
            List of actor dicts with ``confidence_score``.
        """
        data = await self._get_json(
            f"{_BLUESKY_PUBLIC_API}/app.bsky.actor.searchActors",
            {"q": query, "limit": min(top_n, 25)},
        )
        if data is None:
            return []

        results: list[ActorDict] = []
        for actor in data.get("actors", [])[:top_n]:
            handle = actor.get("handle", "")
            display = actor.get("displayName") or handle
            score = _name_similarity(query, handle) or _name_similarity(
                query, display
            )
            entry = _make_actor_dict(
                canonical_name=display,
                platform="bluesky",
                platform_user_id=actor.get("did", ""),
                platform_username=handle,
                profile_url=f"https://bsky.app/profile/{handle}",
                discovery_method="cross_platform_search",
            )
            entry["confidence_score"] = round(score, 3)
            results.append(entry)

        return results

    async def _search_reddit(
        self,
        query: str,
        credentials: Optional[dict[str, str]],
        top_n: int,
    ) -> list[ActorDict]:
        """Search Reddit for users/subreddits matching *query*.

        Uses the public ``/users/search.json`` endpoint.

        Args:
            query: Name or handle to search.
            credentials: Optional credential dict.
            top_n: Maximum results.

        Returns:
            List of actor dicts with ``confidence_score``.
        """
        ua = (
            credentials.get("user_agent", "IssueObservatory/1.0")
            if credentials
            else "IssueObservatory/1.0 (research)"
        )
        data = await self._get_json(
            f"{_REDDIT_PUBLIC_API}/users/search.json",
            {"q": query, "limit": top_n, "raw_json": 1},
            headers={"User-Agent": ua},
        )
        if data is None:
            return []

        results: list[ActorDict] = []
        for child in data.get("data", {}).get("children", [])[:top_n]:
            udata = child.get("data", {})
            username: str = udata.get("name", "")
            if not username:
                continue
            score = _name_similarity(query, username)
            entry = _make_actor_dict(
                canonical_name=f"u/{username}",
                platform="reddit",
                platform_user_id=username,
                platform_username=username,
                profile_url=f"https://www.reddit.com/u/{username}",
                discovery_method="cross_platform_search",
            )
            entry["confidence_score"] = round(score, 3)
            results.append(entry)

        return results

    async def _search_youtube(
        self,
        query: str,
        credentials: Optional[dict[str, str]],
        top_n: int,
    ) -> list[ActorDict]:
        """Search YouTube channels for *query*.

        Uses the ``search.list`` endpoint (100 quota units per call).

        Args:
            query: Channel name or handle to search.
            credentials: Dict with key ``api_key``.
            top_n: Maximum results.

        Returns:
            List of actor dicts with ``confidence_score``.
        """
        if not credentials or not credentials.get("api_key"):
            return []

        data = await self._get_json(
            f"{_YOUTUBE_API_BASE}/search",
            {
                "part": "snippet",
                "q": query,
                "type": "channel",
                "maxResults": min(top_n, 25),
                "key": credentials["api_key"],
            },
        )
        if data is None:
            return []

        results: list[ActorDict] = []
        for item in data.get("items", [])[:top_n]:
            snippet = item.get("snippet", {})
            channel_id: str = item.get("id", {}).get("channelId", "")
            title: str = snippet.get("channelTitle", "")
            if not channel_id:
                continue
            score = _name_similarity(query, title)
            entry = _make_actor_dict(
                canonical_name=title,
                platform="youtube",
                platform_user_id=channel_id,
                platform_username=channel_id,
                profile_url=f"https://www.youtube.com/channel/{channel_id}",
                discovery_method="cross_platform_search",
            )
            entry["confidence_score"] = round(score, 3)
            results.append(entry)

        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_presence(
        self,
        actor_id: uuid.UUID,
        platform: str,
        db: Optional[Any],
    ) -> Optional[dict[str, str]]:
        """Return the actor's platform presence dict for a given platform.

        Args:
            actor_id: UUID of the actor.
            platform: Platform to look up.
            db: An open ``AsyncSession`` or ``None``.

        Returns:
            Dict with ``platform_user_id``, ``platform_username``,
            ``profile_url``, or ``None`` if not found.
        """
        if db is None:
            return None
        try:
            from sqlalchemy import select

            from issue_observatory.core.models.actors import ActorPlatformPresence

            stmt = select(ActorPlatformPresence).where(
                ActorPlatformPresence.actor_id == actor_id,
                ActorPlatformPresence.platform == platform,
            )
            result = await db.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {
                "platform_user_id": row.platform_user_id or "",
                "platform_username": row.platform_username or "",
                "profile_url": row.profile_url or "",
            }
        except Exception:
            logger.exception(
                "_get_presence: failed for actor_id=%s platform=%s",
                actor_id,
                platform,
            )
            return None

    async def _fetch_actor_tokens(
        self,
        actor_id: uuid.UUID,
        db: Any,
    ) -> list[str]:
        """Fetch and tokenize combined text content for *actor_id*.

        Args:
            actor_id: UUID of the target actor.
            db: An open ``AsyncSession``.

        Returns:
            List of tokens from all collected posts by the actor.
        """
        try:
            from sqlalchemy import text

            sql = text(
                """
                SELECT STRING_AGG(text_content, ' ') AS combined
                FROM content_records
                WHERE author_id = :actor_id
                  AND text_content IS NOT NULL
                  AND LENGTH(text_content) > 0
                """
            )
            result = await db.execute(sql, {"actor_id": str(actor_id)})
            row = result.fetchone()
            if row is None or row.combined is None:
                return []
            return _tokenize(row.combined)
        except Exception:
            logger.exception(
                "_fetch_actor_tokens: DB query failed for actor_id=%s", actor_id
            )
            return []

    async def _get_credentials(
        self,
        credential_pool: Optional[Any],
        platform: str,
        tier: str,
    ) -> Optional[dict[str, str]]:
        """Acquire credentials from pool, returning ``None`` on failure.

        Args:
            credential_pool: A ``CredentialPool`` instance or ``None``.
            platform: Platform identifier.
            tier: Tier identifier.

        Returns:
            Credential dict or ``None``.
        """
        if credential_pool is None:
            return None
        try:
            return await credential_pool.acquire(platform=platform, tier=tier)  # type: ignore[no-any-return]
        except Exception:
            logger.debug(
                "_get_credentials: could not acquire %s/%s credential",
                platform,
                tier,
            )
            return None

    async def _get_json(
        self,
        url: str,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Optional[dict[str, Any]]:
        """Perform a GET request and return the parsed JSON body.

        Args:
            url: Target URL.
            params: Query parameters.
            headers: Additional HTTP headers.

        Returns:
            Parsed JSON dict, or ``None`` on any error.
        """
        request_headers: dict[str, str] = {
            "User-Agent": "IssueObservatory/1.0 (research)"
        }
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
# String similarity helper
# ---------------------------------------------------------------------------


def _name_similarity(query: str, candidate: str) -> float:
    """Compute character-trigram similarity between *query* and *candidate*.

    Returns a value in ``[0.0, 1.0]``.  Used to compute ``confidence_score``
    for cross-platform search results.

    Args:
        query: Search query string.
        candidate: Candidate name or handle.

    Returns:
        Trigram Jaccard similarity.
    """
    query_norm = re.sub(r"[^a-z0-9æøå]", "", query.lower())
    cand_norm = re.sub(r"[^a-z0-9æøå]", "", candidate.lower())

    if not query_norm or not cand_norm:
        return 0.0

    # Exact or prefix match → high confidence.
    if query_norm == cand_norm:
        return 1.0
    if cand_norm.startswith(query_norm) or query_norm.startswith(cand_norm):
        return 0.85

    def trigrams(s: str) -> Counter[str]:
        return Counter(s[i : i + 3] for i in range(len(s) - 2))

    tq = trigrams(query_norm)
    tc = trigrams(cand_norm)
    if not tq or not tc:
        return 0.0

    intersection = sum((tq & tc).values())
    union = sum((tq | tc).values())
    return intersection / union if union else 0.0


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_similarity_finder() -> SimilarityFinder:
    """Factory function for FastAPI dependency injection.

    Returns:
        A ready-to-use ``SimilarityFinder`` instance.
    """
    return SimilarityFinder()
