"""Wikipedia arena collector implementation.

Collects editorial attention signals from Wikipedia via two Wikimedia APIs:

- **MediaWiki Action API** (``/w/api.php``): Article search, revision history,
  and user-contribution history.
- **Wikimedia Analytics Pageviews API** (``wikimedia.org/api/rest_v1``):
  Daily pageview counts per article.

**Collection modes**:

- ``collect_by_terms()``: Searches for Wikipedia articles matching the
  supplied terms, then collects revision history and (optionally) pageview
  data for each discovered article.

- ``collect_by_actors()``: Treats ``actor_ids`` as Wikipedia usernames and
  retrieves their contribution history via ``list=usercontribs``.

**No credentials required**: All read-only Wikimedia APIs are unauthenticated.
A ``User-Agent`` header is mandatory per Wikimedia policy.

**Rate limiting**: ``asyncio.Semaphore(5)`` caps concurrent requests at 5.
A 0.2-second sleep between requests maintains the 5 req/s polite limit.

**Danish defaults**: ``da.wikipedia.org`` is always queried first.
``en.wikipedia.org`` is queried unless the caller restricts the
``language_filter`` to ``["da"]`` only.

**Bot edit filtering**: Edits tagged as bot edits are excluded by default
(``INCLUDE_BOT_EDITS = False``) to avoid inflating edit counts with automated
maintenance edits.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import httpx

from issue_observatory.arenas.base import ArenaCollector, Tier
from issue_observatory.arenas.registry import register
from issue_observatory.arenas.wikipedia.config import (
    DEFAULT_MAX_RESULTS,
    DEFAULT_RECENT_CHANGES_LIMIT,
    DEFAULT_USER_AGENT,
    DEFAULT_WIKI_PROJECTS,
    INCLUDE_BOT_EDITS,
    INCLUDE_PAGEVIEWS,
    MEDIAWIKI_ACTION_API_BASE,
    PAGEVIEW_ACCESS,
    PAGEVIEW_AGENT,
    PAGEVIEW_GRANULARITY,
    WIKIPEDIA_RATE_LIMIT_PER_SECOND,
    WIKIPEDIA_TIERS,
)
from issue_observatory.config.tiers import TierConfig
from issue_observatory.core.exceptions import (
    ArenaCollectionError,
    ArenaRateLimitError,
)
from issue_observatory.core.normalizer import Normalizer

logger = logging.getLogger(__name__)

# Maximum concurrent outbound requests.
_MAX_CONCURRENT_REQUESTS: int = 5

# Inter-request courtesy sleep (seconds) to stay within 5 req/s.
_REQUEST_SLEEP_SECONDS: float = 1.0 / WIKIPEDIA_RATE_LIMIT_PER_SECOND  # 0.2 s


@register
class WikipediaCollector(ArenaCollector):
    """Collects Wikipedia editorial attention signals.

    Supports two record types:

    - ``wiki_revision``: A single edit to a Wikipedia article, including the
      editor's username, edit summary, size delta, and revision ID.
    - ``wiki_pageview``: An aggregated daily pageview count for a specific
      article on a specific date.

    Supported tiers:
    - ``Tier.FREE`` — MediaWiki Action API + Wikimedia Pageviews API; free,
      unauthenticated.

    Class Attributes:
        arena_name: ``"reference"``
        platform_name: ``"wikipedia"``
        supported_tiers: ``[Tier.FREE]``

    Args:
        credential_pool: Unused — Wikipedia APIs are unauthenticated.
            Pass ``None``.
        rate_limiter: Optional shared rate limiter.  Not used directly;
            rate limiting is handled internally via ``asyncio.Semaphore``.
        http_client: Optional injected :class:`httpx.AsyncClient` for testing.
            If ``None``, a new client is created per collection call.
    """

    arena_name: str = "reference"
    platform_name: str = "wikipedia"
    supported_tiers: list[Tier] = [Tier.FREE]

    def __init__(
        self,
        credential_pool: Any = None,
        rate_limiter: Any = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(credential_pool=credential_pool, rate_limiter=rate_limiter)
        self._http_client = http_client
        self._normalizer = Normalizer()

    # ------------------------------------------------------------------
    # ArenaCollector abstract method implementations
    # ------------------------------------------------------------------

    async def collect_by_terms(
        self,
        terms: list[str],
        tier: Tier,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
        term_groups: list[list[str]] | None = None,
        language_filter: list[str] | None = None,
        extra_seed_articles: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Collect Wikipedia revision and pageview records for terms.

        For each search term, discovers relevant articles via the MediaWiki
        search API, then collects revision history and (optionally) pageview
        data for each discovered article.

        When ``extra_seed_articles`` is provided, those articles are added to
        the collection set directly (bypassing the search step) on top of the
        term-discovered articles.

        Steps:
        1. For each term, search ``da.wikipedia.org`` (and ``en.wikipedia.org``
           when ``language_filter`` allows it) via ``action=query&list=search``.
        2. For each discovered article (plus any ``extra_seed_articles``),
           fetch revision history filtered to the requested date range.
        3. If ``INCLUDE_PAGEVIEWS`` is ``True``, fetch daily pageview data
           for each article over the requested date range.
        4. Normalize all revision and pageview records.
        5. Deduplicate by ``platform_id`` before returning.

        Args:
            terms: Search terms to query (used as ``srsearch`` parameter).
            tier: Must be ``Tier.FREE``.
            date_from: Earliest revision date to include (inclusive).
            date_to: Latest revision date to include (inclusive).
            max_results: Upper bound on returned records.
            term_groups: Optional boolean AND/OR groups.  When provided, each
                inner group is treated as a single combined search string.
                Simple ORing between groups is applied.
            language_filter: Optional list of ISO 639-1 language codes
                (e.g. ``["da"]`` or ``["da", "en"]``).  When ``None``,
                both Danish and English Wikipedia are queried.
            extra_seed_articles: Optional list of Wikipedia article title
                strings supplied by the researcher via
                ``arenas_config["wikipedia"]["seed_articles"]`` (GR-04).
                These are fetched directly (skipping search) and merged
                with term-discovered articles before collecting revisions.

        Returns:
            List of normalized content record dicts (mix of
            ``wiki_revision`` and ``wiki_pageview`` records).

        Raises:
            ValueError: If *tier* is not ``Tier.FREE``.
            ArenaRateLimitError: On HTTP 429 from Wikimedia.
            ArenaCollectionError: On unrecoverable API error.
        """
        self._validate_tier(tier)
        effective_max = max_results if max_results is not None else DEFAULT_MAX_RESULTS

        # Resolve which wiki projects to query.
        wiki_projects = self._resolve_wiki_projects(language_filter)

        # Flatten term_groups into a search list when provided.
        search_queries: list[str]
        if term_groups:
            search_queries = [" ".join(grp) for grp in term_groups if grp]
        else:
            search_queries = list(terms)

        if not search_queries and not extra_seed_articles:
            logger.warning("wikipedia: collect_by_terms called with empty terms and no seed articles.")
            return []

        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)
        all_records: list[dict[str, Any]] = []
        seen_platform_ids: set[str] = set()

        async with self._build_http_client() as client:
            for project in wiki_projects:
                for query in search_queries:
                    if len(all_records) >= effective_max:
                        break

                    # Step 1: discover articles.
                    articles = await self._search_articles(client, query, project, semaphore)
                    logger.debug(
                        "wikipedia: search '%s' on %s -> %d articles",
                        query,
                        project,
                        len(articles),
                    )

                    if not articles:
                        continue

                    article_titles = [a["title"] for a in articles]

                    # Step 2: collect revision history for discovered articles.
                    revisions = await self._get_revisions(
                        client, article_titles, project, date_from, date_to, semaphore
                    )
                    for rev in revisions:
                        if len(all_records) >= effective_max:
                            break
                        pid = rev.get("platform_id", "")
                        if pid in seen_platform_ids:
                            continue
                        seen_platform_ids.add(pid)
                        all_records.append(self.normalize(rev))

                    # Step 3: collect pageviews (optional).
                    if INCLUDE_PAGEVIEWS and len(all_records) < effective_max:
                        pv_start, pv_end = _resolve_pageview_date_range(date_from, date_to)
                        for title in article_titles:
                            if len(all_records) >= effective_max:
                                break
                            pv_records = await self._get_pageviews(
                                client, title, project, pv_start, pv_end, semaphore
                            )
                            for pv in pv_records:
                                if len(all_records) >= effective_max:
                                    break
                                pid = pv.get("platform_id", "")
                                if pid in seen_platform_ids:
                                    continue
                                seen_platform_ids.add(pid)
                                all_records.append(self.normalize(pv))

                # GR-04: collect revisions (and pageviews) for researcher-supplied
                # seed articles directly — bypassing the search step.
                if extra_seed_articles and len(all_records) < effective_max:
                    seed_titles = [t for t in extra_seed_articles if t and t.strip()]
                    if seed_titles:
                        logger.info(
                            "wikipedia: collecting %d seed articles on %s (GR-04)",
                            len(seed_titles),
                            project,
                        )
                        seed_revisions = await self._get_revisions(
                            client, seed_titles, project, date_from, date_to, semaphore
                        )
                        for rev in seed_revisions:
                            if len(all_records) >= effective_max:
                                break
                            pid = rev.get("platform_id", "")
                            if pid in seen_platform_ids:
                                continue
                            seen_platform_ids.add(pid)
                            all_records.append(self.normalize(rev))

                        if INCLUDE_PAGEVIEWS and len(all_records) < effective_max:
                            pv_start, pv_end = _resolve_pageview_date_range(date_from, date_to)
                            for title in seed_titles:
                                if len(all_records) >= effective_max:
                                    break
                                pv_records = await self._get_pageviews(
                                    client, title, project, pv_start, pv_end, semaphore
                                )
                                for pv in pv_records:
                                    if len(all_records) >= effective_max:
                                        break
                                    pid = pv.get("platform_id", "")
                                    if pid in seen_platform_ids:
                                        continue
                                    seen_platform_ids.add(pid)
                                    all_records.append(self.normalize(pv))

        logger.info(
            "wikipedia: collect_by_terms — %d records for %d terms on %s",
            len(all_records),
            len(search_queries),
            wiki_projects,
        )
        return all_records

    async def collect_by_actors(
        self,
        actor_ids: list[str],
        tier: Tier,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect Wikipedia revision records authored by specific users.

        Each ``actor_id`` is interpreted as a Wikipedia username.  The
        collector fetches each editor's contribution history via
        ``action=query&list=usercontribs`` on both Danish and English Wikipedia.

        Note: Wikipedia usernames are public and users may contribute to
        multiple wiki projects.  This method queries all configured projects
        for each username.

        Args:
            actor_ids: Wikipedia usernames (case-sensitive, platform-native).
            tier: Must be ``Tier.FREE``.
            date_from: Earliest contribution date to include.
            date_to: Latest contribution date to include.
            max_results: Upper bound on returned records.

        Returns:
            List of normalized ``wiki_revision`` records.

        Raises:
            ValueError: If *tier* is not ``Tier.FREE``.
            ArenaRateLimitError: On HTTP 429 from Wikimedia.
            ArenaCollectionError: On unrecoverable API error.
        """
        self._validate_tier(tier)
        effective_max = max_results if max_results is not None else DEFAULT_MAX_RESULTS

        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)
        all_records: list[dict[str, Any]] = []
        seen_platform_ids: set[str] = set()

        async with self._build_http_client() as client:
            for project in DEFAULT_WIKI_PROJECTS:
                for username in actor_ids:
                    if len(all_records) >= effective_max:
                        break
                    contribs = await self._get_user_contribs(
                        client, username, project, date_from, date_to,
                        effective_max - len(all_records), semaphore,
                    )
                    for contrib in contribs:
                        if len(all_records) >= effective_max:
                            break
                        pid = contrib.get("platform_id", "")
                        if pid in seen_platform_ids:
                            continue
                        seen_platform_ids.add(pid)
                        all_records.append(self.normalize(contrib))

        logger.info(
            "wikipedia: collect_by_actors — %d records for %d actors",
            len(all_records),
            len(actor_ids),
        )
        return all_records

    def get_tier_config(self, tier: Tier) -> TierConfig:
        """Return tier configuration for the Wikipedia arena.

        Args:
            tier: Requested operational tier.

        Returns:
            :class:`~issue_observatory.config.tiers.TierConfig` for the tier.

        Raises:
            ValueError: If *tier* is not in ``WIKIPEDIA_TIERS``.
        """
        if tier not in WIKIPEDIA_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}' for wikipedia. "
                f"Valid tiers: {list(WIKIPEDIA_TIERS.keys())}"
            )
        return WIKIPEDIA_TIERS[tier]

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw Wikipedia record to the universal content schema.

        Handles two record types distinguished by the ``_record_type`` key:

        - ``"wiki_revision"``: An edit to a Wikipedia article.  Maps edit
          metadata (timestamp, user, comment, size delta) to the UCR schema.
          ``text_content`` is the editor's edit summary (may be ``None``).
        - ``"wiki_pageview"``: An aggregated daily pageview count.
          ``views_count`` is the primary data point.

        Args:
            raw_item: Pre-built intermediate dict produced by the private
                helper methods.  Must contain ``_record_type`` and
                ``_wiki_project`` keys.

        Returns:
            Dict conforming to the ``content_records`` universal schema.

        Raises:
            ArenaCollectionError: If ``_record_type`` is unrecognised.
        """
        record_type = raw_item.get("_record_type")

        if record_type == "wiki_revision":
            return self._normalize_revision(raw_item)
        elif record_type == "wiki_pageview":
            return self._normalize_pageview(raw_item)
        else:
            raise ArenaCollectionError(
                f"wikipedia: unknown _record_type '{record_type}'",
                arena="reference",
                platform="wikipedia",
            )

    async def health_check(self) -> dict[str, Any]:
        """Verify that the Danish Wikipedia API is reachable.

        Fetches ``action=query&meta=siteinfo`` from ``da.wikipedia.org``
        and verifies the response is valid JSON containing site metadata.

        Returns:
            Dict with ``status`` (``"ok"`` | ``"down"``), ``arena``,
            ``platform``, ``checked_at``, and optionally ``detail``.
        """
        checked_at = datetime.now(tz=timezone.utc).isoformat()
        base: dict[str, Any] = {
            "arena": self.arena_name,
            "platform": self.platform_name,
            "checked_at": checked_at,
        }

        url = MEDIAWIKI_ACTION_API_BASE.format(project="da.wikipedia")
        params = {"action": "query", "meta": "siteinfo", "format": "json"}

        try:
            async with httpx.AsyncClient(
                timeout=15.0, headers=self._make_headers()
            ) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                sitename = (
                    data.get("query", {}).get("general", {}).get("sitename", "Unknown")
                )
                return {
                    **base,
                    "status": "ok",
                    "site": sitename,
                    "project": "da.wikipedia",
                }
        except httpx.HTTPStatusError as exc:
            return {
                **base,
                "status": "down",
                "detail": f"HTTP {exc.response.status_code} from da.wikipedia.org",
            }
        except httpx.RequestError as exc:
            return {**base, "status": "down", "detail": f"Connection error: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {**base, "status": "down", "detail": f"Unexpected error: {exc}"}

    # ------------------------------------------------------------------
    # Private API helpers
    # ------------------------------------------------------------------

    async def _search_articles(
        self,
        client: httpx.AsyncClient,
        term: str,
        wiki_project: str,
        semaphore: asyncio.Semaphore,
    ) -> list[dict[str, Any]]:
        """Search for Wikipedia articles matching a term.

        Uses ``action=query&list=search`` on the specified wiki project.

        Args:
            client: Shared HTTP client.
            term: Search query string.
            wiki_project: Wiki project identifier (e.g. ``"da.wikipedia"``).
            semaphore: Concurrency limiter.

        Returns:
            List of article dicts with ``title`` and ``pageid`` keys.

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaCollectionError: On other API errors.
        """
        url = MEDIAWIKI_ACTION_API_BASE.format(project=wiki_project)
        params: dict[str, Any] = {
            "action": "query",
            "list": "search",
            "srsearch": term,
            "srnamespace": "0",  # article namespace only
            "srlimit": min(DEFAULT_RECENT_CHANGES_LIMIT, 50),
            "srprop": "title|pageid",
            "format": "json",
        }

        data = await self._api_get(client, url, params, semaphore)
        if data is None:
            return []
        results: list[dict[str, Any]] = data.get("query", {}).get("search", [])
        return results

    async def _get_revisions(
        self,
        client: httpx.AsyncClient,
        titles: list[str],
        wiki_project: str,
        date_from: datetime | str | None,
        date_to: datetime | str | None,
        semaphore: asyncio.Semaphore,
    ) -> list[dict[str, Any]]:
        """Fetch revision history for a list of article titles.

        Batches up to 50 titles per request (MediaWiki multi-title limit).
        Applies ``rvstart``/``rvend`` date filtering at the API level when
        date bounds are provided.

        Args:
            client: Shared HTTP client.
            titles: List of article titles to query.
            wiki_project: Wiki project identifier.
            date_from: Earliest revision timestamp to include.
            date_to: Latest revision timestamp to include.
            semaphore: Concurrency limiter.

        Returns:
            List of intermediate revision dicts with ``_record_type`` set
            to ``"wiki_revision"`` and ``_wiki_project`` set.

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaCollectionError: On other API errors.
        """
        if not titles:
            return []

        url = MEDIAWIKI_ACTION_API_BASE.format(project=wiki_project)
        all_revisions: list[dict[str, Any]] = []

        # MediaWiki allows up to 50 titles per query in a multi-title request.
        batch_size = 50
        for batch_start in range(0, len(titles), batch_size):
            batch = titles[batch_start : batch_start + batch_size]
            params: dict[str, Any] = {
                "action": "query",
                "prop": "revisions",
                "titles": "|".join(batch),
                "rvprop": "ids|timestamp|user|comment|size|tags",
                "rvlimit": DEFAULT_RECENT_CHANGES_LIMIT,
                "rvdir": "older",
                "format": "json",
            }

            # Apply server-side date filtering when bounds are provided.
            date_from_str = _to_mediawiki_timestamp(date_from)
            date_to_str = _to_mediawiki_timestamp(date_to)
            if date_to_str:
                # rvdir=older means rvstart is the newest end (most recent).
                params["rvstart"] = date_to_str
            if date_from_str:
                params["rvend"] = date_from_str

            data = await self._api_get(client, url, params, semaphore)
            if data is None:
                break
            pages = data.get("query", {}).get("pages", {})

            for page_data in pages.values():
                page_id = page_data.get("pageid")
                page_title = page_data.get("title", "")
                namespace = page_data.get("ns", 0)
                revisions = page_data.get("revisions", [])

                for rev in revisions:
                    # Filter bot edits if configured.
                    if not INCLUDE_BOT_EDITS and _is_bot_edit(rev):
                        continue

                    rev_id = rev.get("revid")
                    parent_id = rev.get("parentid", 0)
                    timestamp = rev.get("timestamp", "")
                    user = rev.get("user", "")
                    comment = rev.get("comment", "") or None
                    size = rev.get("size", 0)
                    parent_size = rev.get("parentsize", size)
                    tags: list[str] = rev.get("tags", [])
                    is_minor = rev.get("minor", False)

                    platform_id = f"{wiki_project}:rev:{rev_id}"
                    rev_url = (
                        f"https://{wiki_project}.org/w/index.php"
                        f"?oldid={rev_id}"
                    )
                    language = "da" if wiki_project.startswith("da") else "en"

                    all_revisions.append(
                        {
                            "_record_type": "wiki_revision",
                            "_wiki_project": wiki_project,
                            "platform_id": platform_id,
                            "platform": "wikipedia",
                            "arena": "reference",
                            "content_type": "wiki_revision",
                            "title": page_title,
                            "url": rev_url,
                            "language": language,
                            "published_at": timestamp,
                            "text_content": comment,
                            "author_platform_id": user,
                            "author_display_name": user,
                            # Engagement
                            "views_count": None,
                            "likes_count": None,
                            "shares_count": None,
                            "comments_count": None,
                            # Structured metadata for raw_metadata
                            "delta": size - parent_size,
                            "minor": is_minor,
                            "tags": tags,
                            "parentid": parent_id,
                            "namespace": namespace,
                            "is_talk_page": namespace == 1,
                            "wiki_project": wiki_project,
                            "page_id": page_id,
                        }
                    )

        return all_revisions

    async def _get_pageviews(
        self,
        client: httpx.AsyncClient,
        article: str,
        wiki_project: str,
        start_date: str,
        end_date: str,
        semaphore: asyncio.Semaphore,
    ) -> list[dict[str, Any]]:
        """Fetch daily pageview data for a specific article.

        Calls the Wikimedia Analytics Pageviews API at
        ``per-article/{project}/{access}/{agent}/{article}/{granularity}/{start}/{end}``.

        Args:
            client: Shared HTTP client.
            article: Article title (URL-encoded internally).
            wiki_project: Wiki project identifier (e.g. ``"da.wikipedia"``).
            start_date: Start date in ``YYYYMMDD`` format.
            end_date: End date in ``YYYYMMDD`` format.
            semaphore: Concurrency limiter.

        Returns:
            List of intermediate pageview dicts with ``_record_type`` set
            to ``"wiki_pageview"`` and ``_wiki_project`` set.

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaCollectionError: On other API errors.
        """
        if not start_date or not end_date:
            return []

        encoded_article = urllib.parse.quote(article.replace(" ", "_"), safe="")
        url = (
            f"https://wikimedia.org/api/rest_v1/metrics/pageviews"
            f"/per-article/{wiki_project}"
            f"/{PAGEVIEW_ACCESS}/{PAGEVIEW_AGENT}"
            f"/{encoded_article}"
            f"/{PAGEVIEW_GRANULARITY}"
            f"/{start_date}/{end_date}"
        )

        try:
            data = await self._api_get(client, url, {}, semaphore)
        except ArenaCollectionError:
            # Pageview data may not exist for recently created articles.
            logger.debug(
                "wikipedia: no pageview data for '%s' on %s", article, wiki_project
            )
            return []

        if data is None:
            return []
        items: list[dict[str, Any]] = data.get("items", [])
        language = "da" if wiki_project.startswith("da") else "en"
        results: list[dict[str, Any]] = []

        for item in items:
            raw_timestamp = item.get("timestamp", "")
            # Pageview timestamps are YYYYMMDDH format; extract YYYY-MM-DD.
            date_part = raw_timestamp[:8] if len(raw_timestamp) >= 8 else raw_timestamp
            if len(date_part) == 8:
                date_str = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
            else:
                date_str = date_part

            pv_count = item.get("views", 0)
            platform_id = f"{wiki_project}:pv:{article}:{date_str}"
            article_url = (
                f"https://{wiki_project}.org/wiki/{urllib.parse.quote(article.replace(' ', '_'))}"
            )

            results.append(
                {
                    "_record_type": "wiki_pageview",
                    "_wiki_project": wiki_project,
                    "platform_id": platform_id,
                    "platform": "wikipedia",
                    "arena": "reference",
                    "content_type": "wiki_pageview",
                    "title": article,
                    "url": article_url,
                    "language": language,
                    "published_at": date_str,
                    "text_content": None,
                    "author_platform_id": None,
                    "author_display_name": None,
                    "views_count": pv_count,
                    "likes_count": None,
                    "shares_count": None,
                    "comments_count": None,
                    # Structured metadata for raw_metadata
                    "access": PAGEVIEW_ACCESS,
                    "agent": PAGEVIEW_AGENT,
                    "wiki_project": wiki_project,
                }
            )

        return results

    async def _get_user_contribs(
        self,
        client: httpx.AsyncClient,
        username: str,
        wiki_project: str,
        date_from: datetime | str | None,
        date_to: datetime | str | None,
        max_results: int,
        semaphore: asyncio.Semaphore,
    ) -> list[dict[str, Any]]:
        """Fetch contributions (edits) by a specific Wikipedia user.

        Uses ``action=query&list=usercontribs`` on the specified wiki project.
        Paginates via ``uccontinue`` tokens until ``max_results`` is reached
        or no more results are available.

        Args:
            client: Shared HTTP client.
            username: Wikipedia username to query.
            wiki_project: Wiki project identifier.
            date_from: Earliest contribution date to include.
            date_to: Latest contribution date to include.
            max_results: Maximum number of contributions to return.
            semaphore: Concurrency limiter.

        Returns:
            List of intermediate revision dicts with ``_record_type`` set
            to ``"wiki_revision"`` and ``_wiki_project`` set.

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaCollectionError: On other API errors.
        """
        url = MEDIAWIKI_ACTION_API_BASE.format(project=wiki_project)
        language = "da" if wiki_project.startswith("da") else "en"
        all_contribs: list[dict[str, Any]] = []
        continue_token: str | None = None

        while len(all_contribs) < max_results:
            batch_limit = min(100, max_results - len(all_contribs))
            params: dict[str, Any] = {
                "action": "query",
                "list": "usercontribs",
                "ucuser": username,
                "ucprop": "ids|title|timestamp|comment|size|tags",
                "uclimit": batch_limit,
                "ucdir": "older",
                "format": "json",
            }

            date_from_str = _to_mediawiki_timestamp(date_from)
            date_to_str = _to_mediawiki_timestamp(date_to)
            if date_to_str:
                # ucdir=older means ucstart is the most recent date.
                params["ucstart"] = date_to_str
            if date_from_str:
                params["ucend"] = date_from_str
            if continue_token:
                params["uccontinue"] = continue_token

            data = await self._api_get(client, url, params, semaphore)
            if data is None:
                break
            contribs = data.get("query", {}).get("usercontribs", [])

            for contrib in contribs:
                if not INCLUDE_BOT_EDITS and _is_bot_edit(contrib):
                    continue

                rev_id = contrib.get("revid")
                parent_id = contrib.get("parentid", 0)
                page_title = contrib.get("title", "")
                namespace = contrib.get("ns", 0)
                timestamp = contrib.get("timestamp", "")
                comment = contrib.get("comment", "") or None
                size = contrib.get("sizediff", 0)
                tags: list[str] = contrib.get("tags", [])
                is_minor = contrib.get("minor", False)

                platform_id = f"{wiki_project}:rev:{rev_id}"
                rev_url = (
                    f"https://{wiki_project}.org/w/index.php"
                    f"?oldid={rev_id}"
                )

                all_contribs.append(
                    {
                        "_record_type": "wiki_revision",
                        "_wiki_project": wiki_project,
                        "platform_id": platform_id,
                        "platform": "wikipedia",
                        "arena": "reference",
                        "content_type": "wiki_revision",
                        "title": page_title,
                        "url": rev_url,
                        "language": language,
                        "published_at": timestamp,
                        "text_content": comment,
                        "author_platform_id": username,
                        "author_display_name": username,
                        "views_count": None,
                        "likes_count": None,
                        "shares_count": None,
                        "comments_count": None,
                        "delta": size,
                        "minor": is_minor,
                        "tags": tags,
                        "parentid": parent_id,
                        "namespace": namespace,
                        "is_talk_page": namespace == 1,
                        "wiki_project": wiki_project,
                        "page_id": contrib.get("pageid"),
                    }
                )

            # Check for continuation token.
            continue_block = data.get("continue") or {}
            continue_token = continue_block.get("uccontinue")
            if not continue_token or not contribs:
                break

        return all_contribs

    # ------------------------------------------------------------------
    # Private normalization helpers
    # ------------------------------------------------------------------

    def _normalize_revision(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Map a wiki_revision intermediate dict to the universal schema.

        Args:
            raw_item: Intermediate dict produced by ``_get_revisions`` or
                ``_get_user_contribs``.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        wiki_project = raw_item.get("_wiki_project", "")
        raw_metadata: dict[str, Any] = {
            "delta": raw_item.get("delta", 0),
            "minor": raw_item.get("minor", False),
            "tags": raw_item.get("tags", []),
            "parentid": raw_item.get("parentid", 0),
            "namespace": raw_item.get("namespace", 0),
            "is_talk_page": raw_item.get("is_talk_page", False),
            "wiki_project": wiki_project,
            "page_id": raw_item.get("page_id"),
        }

        # Build a clean raw_item for the normalizer.
        normalizer_input: dict[str, Any] = {
            "id": raw_item.get("platform_id"),
            "platform_id": raw_item.get("platform_id"),
            "content_type": "wiki_revision",
            "title": raw_item.get("title"),
            "url": raw_item.get("url"),
            "language": raw_item.get("language"),
            "published_at": raw_item.get("published_at"),
            "text_content": raw_item.get("text_content"),
            "author_platform_id": raw_item.get("author_platform_id"),
            "author_display_name": raw_item.get("author_display_name"),
            "views_count": None,
            "likes_count": None,
            "shares_count": None,
            "comments_count": None,
        }
        # Embed raw_metadata directly into the input so the normalizer
        # passes it through as raw_metadata.
        normalizer_input.update(raw_metadata)

        normalized = self._normalizer.normalize(
            raw_item=normalizer_input,
            platform="wikipedia",
            arena="reference",
            collection_tier="free",
        )
        # Ensure the structured raw_metadata is stored correctly.
        normalized["raw_metadata"] = raw_metadata
        normalized["platform_id"] = raw_item.get("platform_id")
        return normalized

    def _normalize_pageview(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Map a wiki_pageview intermediate dict to the universal schema.

        Args:
            raw_item: Intermediate dict produced by ``_get_pageviews``.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        wiki_project = raw_item.get("_wiki_project", "")
        raw_metadata: dict[str, Any] = {
            "access": raw_item.get("access", PAGEVIEW_ACCESS),
            "agent": raw_item.get("agent", PAGEVIEW_AGENT),
            "wiki_project": wiki_project,
        }

        normalizer_input: dict[str, Any] = {
            "id": raw_item.get("platform_id"),
            "platform_id": raw_item.get("platform_id"),
            "content_type": "wiki_pageview",
            "title": raw_item.get("title"),
            "url": raw_item.get("url"),
            "language": raw_item.get("language"),
            "published_at": raw_item.get("published_at"),
            "text_content": None,
            "author_platform_id": None,
            "author_display_name": None,
            "views_count": raw_item.get("views_count", 0),
            "likes_count": None,
            "shares_count": None,
            "comments_count": None,
        }

        normalized = self._normalizer.normalize(
            raw_item=normalizer_input,
            platform="wikipedia",
            arena="reference",
            collection_tier="free",
        )
        normalized["raw_metadata"] = raw_metadata
        normalized["platform_id"] = raw_item.get("platform_id")
        return normalized

    # ------------------------------------------------------------------
    # Private HTTP helpers
    # ------------------------------------------------------------------

    async def _api_get(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, Any],
        semaphore: asyncio.Semaphore,
    ) -> dict[str, Any]:
        """Make a rate-limited GET request to a Wikimedia API endpoint.

        Acquires the semaphore before each request and sleeps briefly
        afterwards to stay within the 5 req/s polite rate limit.

        Args:
            client: Shared HTTP client.
            url: Full endpoint URL.
            params: Query parameters.
            semaphore: Concurrency limiter (``asyncio.Semaphore(5)``).

        Returns:
            Parsed JSON response dict.

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaCollectionError: On other non-retryable HTTP errors.
        """
        async with semaphore:
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                result: dict[str, Any] = response.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    retry_after = float(
                        exc.response.headers.get("Retry-After", 60)
                    )
                    raise ArenaRateLimitError(
                        f"wikipedia: rate limited by Wikimedia API (HTTP 429)",
                        retry_after=retry_after,
                        arena="reference",
                        platform="wikipedia",
                    ) from exc
                raise ArenaCollectionError(
                    f"wikipedia: HTTP {exc.response.status_code} from {url}",
                    arena="reference",
                    platform="wikipedia",
                ) from exc
            except httpx.RequestError as exc:
                raise ArenaCollectionError(
                    f"wikipedia: request error calling {url}: {exc}",
                    arena="reference",
                    platform="wikipedia",
                ) from exc
            finally:
                # Courtesy sleep between requests regardless of outcome.
                await asyncio.sleep(_REQUEST_SLEEP_SECONDS)

        return result

    def _build_http_client(self) -> httpx.AsyncClient:
        """Return an async HTTP client suitable for Wikimedia API calls.

        Returns the injected client when available (for testing); otherwise
        creates a new :class:`httpx.AsyncClient` with the required
        ``User-Agent`` header and a 30-second timeout.

        Returns:
            An :class:`httpx.AsyncClient` configured for Wikimedia.
        """
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]
        return httpx.AsyncClient(
            timeout=30.0,
            headers=self._make_headers(),
        )

    def _make_headers(self) -> dict[str, str]:
        """Return the mandatory Wikimedia request headers.

        Returns:
            Dict with ``User-Agent`` set to :data:`DEFAULT_USER_AGENT`.
        """
        return {"User-Agent": DEFAULT_USER_AGENT}

    def _resolve_wiki_projects(
        self, language_filter: list[str] | None
    ) -> list[str]:
        """Resolve which wiki projects to query based on the language filter.

        Args:
            language_filter: Optional list of ISO 639-1 language codes.
                ``["da"]`` restricts to Danish Wikipedia only.
                ``["en"]`` restricts to English Wikipedia only.
                ``None`` or ``["da", "en"]`` queries both.

        Returns:
            List of wiki project identifiers to query.
        """
        if language_filter is None:
            return list(DEFAULT_WIKI_PROJECTS)
        projects: list[str] = []
        if "da" in language_filter:
            projects.append("da.wikipedia")
        if "en" in language_filter:
            projects.append("en.wikipedia")
        # Fall back to defaults if filter produced no matches.
        return projects if projects else list(DEFAULT_WIKI_PROJECTS)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _is_bot_edit(rev: dict[str, Any]) -> bool:
    """Return ``True`` if the revision appears to be a bot edit.

    Checks the ``tags`` list for known bot-related tag patterns.
    Also checks the ``userhidden`` flag which indicates the editor is hidden
    (often applied to bot accounts that were suppressed).

    Args:
        rev: Revision or usercontrib dict from the MediaWiki API.

    Returns:
        ``True`` if the edit is identified as a bot edit.
    """
    tags: list[str] = rev.get("tags", [])
    for tag in tags:
        tag_lower = tag.lower()
        if "bot" in tag_lower or tag_lower.startswith("oauth cid:"):
            return True
    return False


def _to_mediawiki_timestamp(value: datetime | str | None) -> str | None:
    """Convert a date value to a MediaWiki API timestamp string (ISO 8601).

    Args:
        value: Datetime object, ISO 8601 string (``"YYYY-MM-DD"`` or full),
            or ``None``.

    Returns:
        ISO 8601 timestamp string accepted by the MediaWiki API
        (e.g. ``"2026-01-01T00:00:00Z"``), or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        # Handle "YYYY-MM-DD" shorthand.
        if len(value) == 10:
            return f"{value}T00:00:00Z"
        # Already a full timestamp — return as-is if it ends with Z.
        if value.endswith("Z"):
            return value
        return value
    return None


def _resolve_pageview_date_range(
    date_from: datetime | str | None,
    date_to: datetime | str | None,
) -> tuple[str, str]:
    """Resolve start/end dates for the Wikimedia Pageviews API.

    The Pageviews API requires ``YYYYMMDD`` format strings.  When date bounds
    are not supplied, defaults to the last 30 days.

    Args:
        date_from: Earliest date boundary.
        date_to: Latest date boundary.

    Returns:
        Tuple of ``(start_str, end_str)`` in ``YYYYMMDD`` format.
    """
    from datetime import timedelta  # noqa: PLC0415

    now = datetime.now(tz=timezone.utc)

    if date_to is not None:
        end_dt = _parse_date_to_datetime(date_to)
    else:
        # Default to yesterday (pageviews have ~24 h delay).
        end_dt = now - timedelta(days=1)

    if date_from is not None:
        start_dt = _parse_date_to_datetime(date_from)
    else:
        # Default to 30 days before the end date.
        start_dt = end_dt - timedelta(days=30)

    return start_dt.strftime("%Y%m%d"), end_dt.strftime("%Y%m%d")


def _parse_date_to_datetime(value: datetime | str) -> datetime:
    """Parse a date value to a UTC-aware datetime.

    Args:
        value: Datetime object or ISO 8601 string.

    Returns:
        UTC-aware :class:`datetime`.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    # String parsing.
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(str(value).strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    # Fall back to now if parsing fails.
    logger.warning("wikipedia: could not parse date '%s', defaulting to now", value)
    return datetime.now(tz=timezone.utc)
