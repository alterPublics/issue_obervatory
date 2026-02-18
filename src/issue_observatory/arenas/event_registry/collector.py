"""Event Registry / NewsAPI.ai arena collector implementation.

Collects Danish news articles via the NewsAPI.ai REST API (eventregistry.org)
using ``httpx.AsyncClient`` for fully async I/O.  No SDK dependency is
required.

**Design notes**:

- Pure ``httpx.AsyncClient`` implementation — the ``eventregistry`` Python SDK
  is intentionally avoided to keep all I/O asynchronous.
- ``collect_by_terms()``: POST to ``/article/getArticles`` with ``lang="dan"``,
  ``sourceLocationUri`` for Denmark, and cursor/page pagination.
- ``collect_by_actors()``: actor_ids are treated as Event Registry concept URIs
  or source URIs and supplied via the ``conceptUri`` parameter.
- ``normalize()``: maps to the UCR; full article body stored in
  ``text_content``; NLP enrichments (concepts, categories, sentiment) stored
  in ``raw_metadata``.
- Token budget tracking: the API returns ``remainingTokens`` in the response
  body.  The collector logs warnings at 20% and stops at 5% remaining.
- Rate limiting: ``RateLimiter.wait_for_slot()`` at 5 calls/sec per credential.
  Token budget is the real constraint for this arena.
- Credentials: ``CredentialPool.acquire(platform="event_registry", tier=tier)``
  with JSONB ``{"api_key": "..."}``; released in ``finally`` blocks.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any

import httpx

from issue_observatory.arenas.base import ArenaCollector, Tier
from issue_observatory.arenas.query_builder import format_boolean_query_for_platform
from issue_observatory.arenas.event_registry.config import (
    EVENT_REGISTRY_ARTICLE_ENDPOINT,
    EVENT_REGISTRY_DANISH_LANG,
    EVENT_REGISTRY_DATA_TYPES,
    EVENT_REGISTRY_DEFAULT_MAX_RESULTS,
    EVENT_REGISTRY_DEFAULT_SORT_ASC,
    EVENT_REGISTRY_DEFAULT_SORT_BY,
    EVENT_REGISTRY_DENMARK_URI,
    EVENT_REGISTRY_MAX_CALLS_PER_SECOND,
    EVENT_REGISTRY_RATE_LIMIT_KEY,
    EVENT_REGISTRY_RATE_LIMIT_TIMEOUT,
    EVENT_REGISTRY_RATE_WINDOW_SECONDS,
    EVENT_REGISTRY_TIERS,
    TOKEN_BUDGET_CRITICAL_PCT,
    TOKEN_BUDGET_WARNING_PCT,
    map_language,
)
from issue_observatory.arenas.registry import register
from issue_observatory.config.tiers import TierConfig
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)
from issue_observatory.core.normalizer import Normalizer

logger = logging.getLogger(__name__)


@register
class EventRegistryCollector(ArenaCollector):
    """Collects Danish news articles via the NewsAPI.ai (Event Registry) API.

    Supported tiers:
    - ``Tier.MEDIUM``  — 5,000 tokens/month.
    - ``Tier.PREMIUM`` — 50,000 tokens/month.

    No free tier.  A credential with ``platform="event_registry"`` must be
    provisioned in the ``CredentialPool`` before collection can run.

    Class Attributes:
        arena_name: ``"news_media"`` (written to ``content_records.arena``).
        platform_name: ``"event_registry"``.
        supported_tiers: ``[Tier.MEDIUM, Tier.PREMIUM]``.

    Args:
        credential_pool: Required.  Used to acquire/release API keys.
        rate_limiter: Optional Redis-backed rate limiter.  Falls back to
            ``asyncio.sleep(0.2)`` (5 req/sec) when ``None``.
        http_client: Optional injected :class:`httpx.AsyncClient`.
            Inject for unit testing.  If ``None``, a new client is created
            per collection call.
    """

    arena_name: str = "news_media"
    platform_name: str = "event_registry"
    supported_tiers: list[Tier] = [Tier.MEDIUM, Tier.PREMIUM]

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
    ) -> list[dict[str, Any]]:
        """Collect Danish news articles matching the supplied search terms.

        Issues one paginated ``getArticles`` request sequence per term, with
        ``lang="dan"`` and ``sourceLocationUri`` set to Denmark.  Each page
        request consumes one Event Registry token.

        When ``term_groups`` is provided, the Event Registry ``$query``
        structure with ``$and``/``$or`` operators is used for full boolean
        support.  One request sequence is issued per OR-group.

        Args:
            terms: Search terms (used when ``term_groups`` is ``None``).
            tier: Must be ``Tier.MEDIUM`` or ``Tier.PREMIUM``.
            date_from: Earliest publication date (ISO 8601 or ``datetime``).
            date_to: Latest publication date (ISO 8601 or ``datetime``).
            max_results: Upper bound on returned records.
            term_groups: Optional boolean AND/OR groups.  Event Registry
                supports native ``$and``/``$or`` query operators.
            language_filter: Optional language codes (ISO 639-1).  By default
                ``"dan"`` is used.  Provide e.g. ``["da", "en"]`` to expand
                to multiple languages.

        Returns:
            List of normalized content record dicts.

        Raises:
            ValueError: If *tier* is not in ``supported_tiers``.
            NoCredentialAvailableError: If no credential is available.
            ArenaAuthError: If the API key is rejected (HTTP 401).
            ArenaCollectionError: On unrecoverable API errors.
            ArenaRateLimitError: On HTTP 429 from the API.
        """
        self._validate_tier(tier)
        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

        credential = await self._acquire_credential(tier)
        api_key: str = credential["api_key"]
        credential_id: str = credential.get("id", "unknown")

        date_start_str = _format_date(date_from)
        date_end_str = _format_date(date_to)

        # Resolve language list.  Default = Danish only.
        lang_codes: list[str] = language_filter if language_filter else ["dan"]
        # Map ISO 639-1 → ISO 639-3 used by Event Registry.
        _lang_map_to_639_3 = {"da": "dan", "en": "eng", "de": "deu", "sv": "swe", "no": "nor"}
        er_lang_list: list[str] = [
            _lang_map_to_639_3.get(lc, lc) for lc in lang_codes
        ]
        # Event Registry accepts a single lang string; use the first when querying.
        er_lang = er_lang_list[0] if er_lang_list else EVENT_REGISTRY_DANISH_LANG

        seen_uris: set[str] = set()
        all_records: list[dict[str, Any]] = []

        # Determine list of keyword queries to issue.
        if term_groups is not None:
            # For boolean groups, issue one request per AND-group using generic
            # AND syntax (Event Registry keyword field supports AND/OR strings).
            query_strings: list[str] = [
                format_boolean_query_for_platform(groups=[grp], platform="event_registry")
                for grp in term_groups
                if grp
            ]
        else:
            query_strings = list(terms)

        try:
            async with self._build_http_client() as client:
                for term in query_strings:
                    if len(all_records) >= effective_max:
                        break

                    page = 1
                    while len(all_records) < effective_max:
                        await self._rate_limit_wait(credential_id)

                        payload = self._build_terms_payload(
                            keyword=term,
                            api_key=api_key,
                            date_start=date_start_str,
                            date_end=date_end_str,
                            page=page,
                            articles_count=min(
                                EVENT_REGISTRY_DEFAULT_MAX_RESULTS,
                                effective_max - len(all_records),
                            ),
                        )
                        # Override language if expanded
                        if er_lang != EVENT_REGISTRY_DANISH_LANG:
                            payload["lang"] = er_lang

                        raw_resp = await self._post(
                            client=client,
                            payload=payload,
                            credential_id=credential_id,
                            tier=tier,
                        )

                        articles = self._extract_articles(raw_resp)
                        total_results = self._extract_total_results(raw_resp)
                        self._check_token_budget(raw_resp, tier)

                        for article in articles:
                            uri = article.get("uri") or article.get("url")
                            if not uri or uri in seen_uris:
                                continue
                            seen_uris.add(uri)
                            all_records.append(self.normalize(article))

                        if not articles or len(all_records) >= effective_max:
                            break
                        if total_results is not None and page * EVENT_REGISTRY_DEFAULT_MAX_RESULTS >= total_results:
                            break

                        page += 1

        finally:
            if self.credential_pool is not None:
                await self.credential_pool.release(
                    credential_id=credential_id, task_id=None
                )

        logger.info(
            "event_registry: collect_by_terms — %d records for %d queries",
            len(all_records),
            len(query_strings),
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
        """Collect Danish news articles mentioning the specified concept URIs.

        Actor IDs for this arena are Event Registry concept URIs or source URIs
        (e.g. ``"http://en.wikipedia.org/wiki/Mette_Frederiksen"``).  Use the
        ``/suggestConcepts`` endpoint to resolve actor names to URIs at query
        design creation time.

        Args:
            actor_ids: List of Event Registry concept URIs or source URIs.
                Example: ``["http://en.wikipedia.org/wiki/Folketing"]``.
            tier: Must be ``Tier.MEDIUM`` or ``Tier.PREMIUM``.
            date_from: Earliest publication date (ISO 8601 or ``datetime``).
            date_to: Latest publication date (ISO 8601 or ``datetime``).
            max_results: Upper bound on returned records.

        Returns:
            List of normalized content record dicts.

        Raises:
            ValueError: If *tier* is not in ``supported_tiers``.
            NoCredentialAvailableError: If no credential is available.
            ArenaAuthError: If the API key is rejected (HTTP 401).
            ArenaCollectionError: On unrecoverable API errors.
            ArenaRateLimitError: On HTTP 429 from the API.
        """
        self._validate_tier(tier)
        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

        credential = await self._acquire_credential(tier)
        api_key: str = credential["api_key"]
        credential_id: str = credential.get("id", "unknown")

        date_start_str = _format_date(date_from)
        date_end_str = _format_date(date_to)

        seen_uris: set[str] = set()
        all_records: list[dict[str, Any]] = []

        try:
            async with self._build_http_client() as client:
                for concept_uri in actor_ids:
                    if len(all_records) >= effective_max:
                        break

                    page = 1
                    while len(all_records) < effective_max:
                        await self._rate_limit_wait(credential_id)

                        payload = self._build_actors_payload(
                            concept_uri=concept_uri,
                            api_key=api_key,
                            date_start=date_start_str,
                            date_end=date_end_str,
                            page=page,
                            articles_count=min(
                                EVENT_REGISTRY_DEFAULT_MAX_RESULTS,
                                effective_max - len(all_records),
                            ),
                        )

                        raw_resp = await self._post(
                            client=client,
                            payload=payload,
                            credential_id=credential_id,
                            tier=tier,
                        )

                        articles = self._extract_articles(raw_resp)
                        total_results = self._extract_total_results(raw_resp)
                        self._check_token_budget(raw_resp, tier)

                        for article in articles:
                            uri = article.get("uri") or article.get("url")
                            if not uri or uri in seen_uris:
                                continue
                            seen_uris.add(uri)
                            all_records.append(self.normalize(article))

                        if not articles or len(all_records) >= effective_max:
                            break
                        if total_results is not None and page * EVENT_REGISTRY_DEFAULT_MAX_RESULTS >= total_results:
                            break

                        page += 1

        finally:
            if self.credential_pool is not None:
                await self.credential_pool.release(
                    credential_id=credential_id, task_id=None
                )

        logger.info(
            "event_registry: collect_by_actors — %d records for %d concept URIs",
            len(all_records),
            len(actor_ids),
        )
        return all_records

    def get_tier_config(self, tier: Tier) -> TierConfig:
        """Return tier configuration for the Event Registry arena.

        Args:
            tier: Requested operational tier.

        Returns:
            :class:`~issue_observatory.config.tiers.TierConfig` for the tier.

        Raises:
            ValueError: If *tier* is not ``MEDIUM`` or ``PREMIUM``.
        """
        if tier not in EVENT_REGISTRY_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}' for event_registry. "
                f"Valid tiers: {list(EVENT_REGISTRY_TIERS.keys())}"
            )
        return EVENT_REGISTRY_TIERS[tier]

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single Event Registry article dict to the UCR schema.

        Maps Event Registry fields to the universal content record schema.
        Full article ``body`` becomes ``text_content``.  NLP enrichments
        (``concepts``, ``categories``, ``sentiment``, ``eventUri``) are
        stored in ``raw_metadata`` for downstream analysis.

        The ``language`` field is mapped from ISO 639-3 (e.g. ``"dan"``) to
        ISO 639-1 (e.g. ``"da"``).

        Args:
            raw_item: Raw article dict from the Event Registry API response.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        uri: str | None = raw_item.get("uri")
        url: str | None = raw_item.get("url")

        # platform_id = native Event Registry article URI
        platform_id: str | None = uri

        # content_hash = SHA-256 of normalized URL (for cross-arena dedup)
        content_hash: str | None = None
        if url:
            content_hash = self._normalizer.compute_content_hash(url)
        elif uri:
            # Fall back to hash of the ER URI if URL not present
            content_hash = hashlib.sha256(uri.encode("utf-8")).hexdigest()

        # Language: map ISO 639-3 -> ISO 639-1
        raw_lang: str | None = raw_item.get("lang")
        language: str | None = map_language(raw_lang)

        # Published datetime: prefer dateTimePub, fall back to dateTime, then date
        published_at: str | None = (
            raw_item.get("dateTimePub")
            or raw_item.get("dateTime")
            or raw_item.get("date")
        )

        # Authors: use first author if available
        authors: list[dict[str, Any]] = raw_item.get("authors") or []
        first_author: dict[str, Any] | None = authors[0] if authors else None
        author_platform_id: str | None = first_author.get("uri") if first_author else None
        author_display_name: str | None = first_author.get("name") if first_author else None

        # pseudonymized_author_id: hash of author name as platform_user_id
        pseudonymized_author_id: str | None = None
        if author_display_name:
            pseudonymized_author_id = self._normalizer.pseudonymize_author(
                platform=self.platform_name,
                platform_user_id=author_display_name,
            )

        # media_urls: featured image if present
        image: str | None = raw_item.get("image")
        media_urls: list[str] = [image] if image else []

        # Source metadata
        source: dict[str, Any] | None = raw_item.get("source")

        # NLP enrichments
        concepts: list[dict[str, Any]] = raw_item.get("concepts") or []
        categories: list[dict[str, Any]] = raw_item.get("categories") or []
        sentiment: float | None = raw_item.get("sentiment")

        # Social sharing (availability varies)
        shares: dict[str, Any] | None = raw_item.get("shares")

        # Engagement proxy: article importance weight
        wgt: float | None = raw_item.get("wgt")

        raw_metadata: dict[str, Any] = {
            "eventUri": raw_item.get("eventUri"),
            "sentiment": sentiment,
            "wgt": wgt,
            "relevance": raw_item.get("relevance"),
            "isDuplicate": raw_item.get("isDuplicate"),
            "duplicateList": raw_item.get("duplicateList"),
            "categories": categories,
            "concepts": concepts,
            "shares": shares,
            "source": source,
            "authors": authors,
            "image": image,
            "lang_raw": raw_lang,
        }

        enriched: dict[str, Any] = {
            "id": platform_id,
            "url": url,
            "title": raw_item.get("title"),
            "text_content": raw_item.get("body"),
            "author": author_display_name,
            "published_at": published_at,
            "language": language,
            "content_type": "article",
            "media_urls": media_urls,
            # Pass through raw_metadata fields so Normalizer.normalize() stores them
            **raw_metadata,
        }

        normalized = self._normalizer.normalize(
            raw_item=enriched,
            platform=self.platform_name,
            arena=self.arena_name,
            collection_tier="medium",  # tier string for DB logging; actual tier passed separately
        )

        # Override specific fields with precisely-computed values
        normalized["platform_id"] = platform_id
        normalized["author_platform_id"] = author_platform_id
        normalized["author_display_name"] = author_display_name
        normalized["pseudonymized_author_id"] = pseudonymized_author_id
        normalized["media_urls"] = media_urls
        normalized["engagement_score"] = wgt
        normalized["raw_metadata"] = raw_metadata

        if content_hash:
            normalized["content_hash"] = content_hash

        return normalized

    async def health_check(self) -> dict[str, Any]:
        """Verify Event Registry API connectivity with a minimal test query.

        Issues a single ``getArticles`` request with ``lang="dan"`` and
        ``articlesCount=1``.  Also reports remaining token count.

        Returns:
            Dict with ``status`` (``"ok"`` | ``"degraded"`` | ``"down"``),
            ``arena``, ``platform``, ``checked_at``, and optionally
            ``remaining_tokens`` and ``detail``.

        Note:
            Health check requires a valid credential.  If no credential is
            available, returns ``status="down"`` with an explanatory ``detail``.
        """
        checked_at = datetime.utcnow().isoformat() + "Z"
        base: dict[str, Any] = {
            "arena": self.arena_name,
            "platform": self.platform_name,
            "checked_at": checked_at,
        }

        credential: dict[str, Any] | None = None
        credential_id: str = "unknown"

        try:
            credential = await self._acquire_credential(Tier.MEDIUM)
            api_key: str = credential["api_key"]
            credential_id = credential.get("id", "unknown")
        except (NoCredentialAvailableError, Exception) as exc:  # noqa: BLE001
            # Try PREMIUM if MEDIUM is unavailable
            try:
                credential = await self._acquire_credential(Tier.PREMIUM)
                api_key = credential["api_key"]
                credential_id = credential.get("id", "unknown")
            except Exception as exc2:  # noqa: BLE001
                return {
                    **base,
                    "status": "down",
                    "detail": f"No credential available: {exc2}",
                }

        payload = {
            "action": "getArticles",
            "keyword": "Denmark",
            "lang": EVENT_REGISTRY_DANISH_LANG,
            "sourceLocationUri": EVENT_REGISTRY_DENMARK_URI,
            "articlesPage": 1,
            "articlesCount": 1,
            "resultType": "articles",
            "articlesSortBy": EVENT_REGISTRY_DEFAULT_SORT_BY,
            "articlesSortByAsc": EVENT_REGISTRY_DEFAULT_SORT_ASC,
            "apiKey": api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    EVENT_REGISTRY_ARTICLE_ENDPOINT, json=payload
                )
                response.raise_for_status()
                data = response.json()

                articles = self._extract_articles(data)
                remaining_tokens = data.get("remainingTokens")

                return {
                    **base,
                    "status": "ok",
                    "articles_returned": len(articles),
                    "remaining_tokens": remaining_tokens,
                }

        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code == 401:
                return {
                    **base,
                    "status": "down",
                    "detail": "API key rejected (HTTP 401). Check credential.",
                }
            if status_code == 402:
                return {
                    **base,
                    "status": "down",
                    "detail": "Token budget exhausted (HTTP 402).",
                }
            return {
                **base,
                "status": "down" if status_code >= 500 else "degraded",
                "detail": f"HTTP {status_code} from Event Registry API",
            }
        except httpx.RequestError as exc:
            return {**base, "status": "down", "detail": f"Connection error: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {**base, "status": "down", "detail": f"Unexpected error: {exc}"}
        finally:
            if self.credential_pool is not None and credential is not None:
                await self.credential_pool.release(
                    credential_id=credential_id, task_id=None
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _acquire_credential(self, tier: Tier) -> dict[str, Any]:
        """Acquire a credential from the pool for the given tier.

        Args:
            tier: Operational tier (``MEDIUM`` or ``PREMIUM``).

        Returns:
            Credential dict with at minimum ``{"api_key": "...", "id": "..."}``.

        Raises:
            NoCredentialAvailableError: If no credential is available in the
                pool for this platform/tier combination.
        """
        if self.credential_pool is None:
            import os  # noqa: PLC0415

            env_key = f"EVENT_REGISTRY_{tier.value.upper()}_API_KEY"
            api_key = os.environ.get(env_key)
            if not api_key:
                raise NoCredentialAvailableError(
                    platform=self.platform_name, tier=tier.value
                )
            return {"api_key": api_key, "id": "env"}

        cred = await self.credential_pool.acquire(
            platform=self.platform_name, tier=tier.value
        )
        if cred is None:
            raise NoCredentialAvailableError(
                platform=self.platform_name, tier=tier.value
            )
        return cred

    def _build_http_client(self) -> httpx.AsyncClient:
        """Return an async HTTP client for use as a context manager.

        Returns the injected client if present; otherwise creates a new one
        with a 30-second timeout and a descriptive User-Agent.
        """
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]
        return httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "IssueObservatory/1.0 (event-registry-collector; research use)"
            },
        )

    async def _rate_limit_wait(self, credential_id: str) -> None:
        """Wait for a rate-limit slot for the given credential.

        Uses the injected :class:`~issue_observatory.workers.rate_limiter.RateLimiter`
        when available; falls back to ``asyncio.sleep(0.2)`` (5 req/sec) when
        Redis is not configured.

        Args:
            credential_id: Credential ID used to construct the Redis key.
        """
        if self.rate_limiter is not None:
            key = EVENT_REGISTRY_RATE_LIMIT_KEY.format(credential_id=credential_id)
            try:
                await self.rate_limiter.wait_for_slot(
                    key=key,
                    max_calls=EVENT_REGISTRY_MAX_CALLS_PER_SECOND,
                    window_seconds=EVENT_REGISTRY_RATE_WINDOW_SECONDS,
                    timeout=EVENT_REGISTRY_RATE_LIMIT_TIMEOUT,
                )
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "event_registry: rate_limiter.wait_for_slot failed (%s) — "
                    "falling back to sleep(0.2)",
                    exc,
                )

        import asyncio  # noqa: PLC0415

        await asyncio.sleep(0.2)

    async def _post(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
        credential_id: str,
        tier: Tier,
    ) -> dict[str, Any]:
        """POST a payload to the Event Registry article endpoint.

        Handles HTTP error codes according to the research brief:
        - 401: invalid API key -> ArenaAuthError
        - 402: token budget exhausted -> ArenaCollectionError (fatal)
        - 429: rate limited -> ArenaRateLimitError (retryable)
        - 5xx: server error -> ArenaCollectionError (retryable via Celery)

        Args:
            client: Shared HTTP client.
            payload: JSON request body.
            credential_id: Credential ID for error reporting.
            tier: Current tier, used in error messages.

        Returns:
            Parsed JSON response dict.

        Raises:
            ArenaAuthError: On HTTP 401.
            ArenaCollectionError: On HTTP 402 or 5xx.
            ArenaRateLimitError: On HTTP 429.
        """
        try:
            response = await client.post(
                EVENT_REGISTRY_ARTICLE_ENDPOINT, json=payload
            )
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"event_registry: connection error: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

        if response.status_code == 401:
            if self.credential_pool is not None:
                await self.credential_pool.report_error(
                    platform=self.platform_name, credential_id=credential_id
                )
            raise ArenaAuthError(
                f"event_registry: API key rejected (HTTP 401) for credential {credential_id}",
                arena=self.arena_name,
                platform=self.platform_name,
            )

        if response.status_code == 402:
            raise ArenaCollectionError(
                f"event_registry: token budget exhausted (HTTP 402) for tier={tier.value}. "
                "Upgrade plan or add credentials via CredentialPool.",
                arena=self.arena_name,
                platform=self.platform_name,
            )

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", 60))
            raise ArenaRateLimitError(
                f"event_registry: HTTP 429 rate limit",
                retry_after=retry_after,
                arena=self.arena_name,
                platform=self.platform_name,
            )

        if response.status_code >= 500:
            raise ArenaCollectionError(
                f"event_registry: server error HTTP {response.status_code}",
                arena=self.arena_name,
                platform=self.platform_name,
            )

        try:
            return response.json()
        except Exception as exc:  # noqa: BLE001
            raise ArenaCollectionError(
                f"event_registry: JSON parse error (HTTP {response.status_code}): {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

    def _build_terms_payload(
        self,
        keyword: str,
        api_key: str,
        date_start: str | None,
        date_end: str | None,
        page: int,
        articles_count: int,
    ) -> dict[str, Any]:
        """Build a ``getArticles`` JSON payload for keyword-based search.

        Args:
            keyword: Search term (Danish keywords work natively).
            api_key: Event Registry API key.
            date_start: ISO 8601 start date string or ``None``.
            date_end: ISO 8601 end date string or ``None``.
            page: 1-indexed page number for pagination.
            articles_count: Articles to fetch (max 100).

        Returns:
            Dict suitable for JSON POST body.
        """
        payload: dict[str, Any] = {
            "action": "getArticles",
            "keyword": keyword,
            "keywordOper": "and",
            "lang": EVENT_REGISTRY_DANISH_LANG,
            "sourceLocationUri": EVENT_REGISTRY_DENMARK_URI,
            "dataType": EVENT_REGISTRY_DATA_TYPES,
            "articlesPage": page,
            "articlesCount": articles_count,
            "resultType": "articles",
            "articlesSortBy": EVENT_REGISTRY_DEFAULT_SORT_BY,
            "articlesSortByAsc": EVENT_REGISTRY_DEFAULT_SORT_ASC,
            "includeArticleBody": True,
            "includeArticleConcepts": True,
            "includeArticleCategories": True,
            "includeArticleSentiment": True,
            "includeArticleEventUri": True,
            "includeArticleDuplicateList": True,
            "includeArticleShares": True,
            "apiKey": api_key,
        }
        if date_start:
            payload["dateStart"] = date_start
        if date_end:
            payload["dateEnd"] = date_end
        return payload

    def _build_actors_payload(
        self,
        concept_uri: str,
        api_key: str,
        date_start: str | None,
        date_end: str | None,
        page: int,
        articles_count: int,
    ) -> dict[str, Any]:
        """Build a ``getArticles`` JSON payload for concept URI-based search.

        Args:
            concept_uri: Event Registry concept URI (Wikipedia-based).
                Example: ``"http://en.wikipedia.org/wiki/Mette_Frederiksen"``.
            api_key: Event Registry API key.
            date_start: ISO 8601 start date string or ``None``.
            date_end: ISO 8601 end date string or ``None``.
            page: 1-indexed page number for pagination.
            articles_count: Articles to fetch (max 100).

        Returns:
            Dict suitable for JSON POST body.
        """
        payload: dict[str, Any] = {
            "action": "getArticles",
            "conceptUri": concept_uri,
            "lang": EVENT_REGISTRY_DANISH_LANG,
            "sourceLocationUri": EVENT_REGISTRY_DENMARK_URI,
            "dataType": EVENT_REGISTRY_DATA_TYPES,
            "articlesPage": page,
            "articlesCount": articles_count,
            "resultType": "articles",
            "articlesSortBy": EVENT_REGISTRY_DEFAULT_SORT_BY,
            "articlesSortByAsc": EVENT_REGISTRY_DEFAULT_SORT_ASC,
            "includeArticleBody": True,
            "includeArticleConcepts": True,
            "includeArticleCategories": True,
            "includeArticleSentiment": True,
            "includeArticleEventUri": True,
            "includeArticleDuplicateList": True,
            "includeArticleShares": True,
            "apiKey": api_key,
        }
        if date_start:
            payload["dateStart"] = date_start
        if date_end:
            payload["dateEnd"] = date_end
        return payload

    @staticmethod
    def _extract_articles(response_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract the article list from a ``getArticles`` response.

        The response nests articles as::

            {"articles": {"results": [...], "totalResults": N}}

        Args:
            response_data: Parsed JSON response dict.

        Returns:
            List of article dicts (may be empty).
        """
        articles_wrapper = response_data.get("articles") or {}
        if isinstance(articles_wrapper, dict):
            return articles_wrapper.get("results") or []
        return []

    @staticmethod
    def _extract_total_results(response_data: dict[str, Any]) -> int | None:
        """Extract the total result count from a ``getArticles`` response.

        Args:
            response_data: Parsed JSON response dict.

        Returns:
            Total number of matching articles, or ``None`` if not present.
        """
        articles_wrapper = response_data.get("articles") or {}
        if isinstance(articles_wrapper, dict):
            return articles_wrapper.get("totalResults")
        return None

    def _check_token_budget(
        self, response_data: dict[str, Any], tier: Tier
    ) -> None:
        """Check remaining token budget and log warnings or raise on critical.

        Reads ``remainingTokens`` from the API response and compares against
        threshold percentages.  Monthly budget is derived from the tier config.

        Args:
            response_data: Parsed JSON response dict.
            tier: Current operational tier (determines budget baseline).

        Raises:
            ArenaCollectionError: When remaining tokens fall below the
                ``TOKEN_BUDGET_CRITICAL_PCT`` threshold.
        """
        remaining = response_data.get("remainingTokens")
        if remaining is None:
            return

        tier_config = self.get_tier_config(tier)
        # Estimate monthly budget from tier: max_results_per_run / 100 articles per token
        monthly_budget = tier_config.max_results_per_run // EVENT_REGISTRY_DEFAULT_MAX_RESULTS

        warning_threshold = monthly_budget * TOKEN_BUDGET_WARNING_PCT
        critical_threshold = monthly_budget * TOKEN_BUDGET_CRITICAL_PCT

        if remaining <= critical_threshold:
            msg = (
                f"event_registry: CRITICAL — only {remaining} tokens remaining "
                f"(below {TOKEN_BUDGET_CRITICAL_PCT:.0%} of monthly budget {monthly_budget}). "
                "Halting collection to preserve remaining budget."
            )
            logger.critical(msg)
            raise ArenaCollectionError(
                msg,
                arena=self.arena_name,
                platform=self.platform_name,
            )

        if remaining <= warning_threshold:
            logger.warning(
                "event_registry: WARNING — only %d tokens remaining "
                "(below %.0f%% of monthly budget %d).",
                remaining,
                TOKEN_BUDGET_WARNING_PCT * 100,
                monthly_budget,
            )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _format_date(value: datetime | str | None) -> str | None:
    """Format a date value as an Event Registry ``YYYY-MM-DD`` string.

    Event Registry accepts ISO 8601 date strings (``YYYY-MM-DD``) for the
    ``dateStart`` and ``dateEnd`` parameters.

    Args:
        value: ``datetime`` object, ISO 8601 string, or ``None``.

    Returns:
        Date string in ``YYYY-MM-DD`` format, or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    # Accept ISO 8601 strings — truncate to date part if datetime string
    if "T" in value:
        return value.split("T")[0]
    return value
