"""Google Autocomplete arena collector implementation.

Collects autocomplete suggestions from Google via three tiers:

- **FREE** — Undocumented Google endpoint (``suggestqueries.google.com``).
  Returns a JSON array ``["query", ["sug1", "sug2", ...]]``.
  No authentication required; ~1 req/sec empirical safe limit.
- **MEDIUM** — Serper.dev autocomplete (``POST google.serper.dev/autocomplete``).
  JSON body with ``{"q": ..., "gl": "dk", "hl": "da"}``; ``X-API-KEY`` header.
  Credentials use ``platform="serper"`` (shared with Google Search arena).
- **PREMIUM** — SerpAPI (``GET serpapi.com/search?engine=google_autocomplete``).
  Credentials use ``platform="serpapi"`` (shared with Google Search arena).

All requests include Danish locale parameters (``gl=dk``, ``hl=da``).

``collect_by_actors()`` raises ``NotImplementedError`` — autocomplete is
inherently term-based and does not support actor-based collection.

Rate limiting uses :meth:`RateLimiter.wait_for_slot` with key
``ratelimit:google_search:google_autocomplete:{credential_id}``.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from issue_observatory.arenas.base import ArenaCollector, Tier
from issue_observatory.arenas.google_autocomplete.config import (
    DANISH_PARAMS,
    FREE_AUTOCOMPLETE_URL,
    GOOGLE_AUTOCOMPLETE_TIERS,
    SERPER_AUTOCOMPLETE_URL,
    SERPAPI_AUTOCOMPLETE_URL,
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

# Rate-limiter key convention matches the task specification:
# ratelimit:google_search:google_autocomplete:{credential_id}
_RATE_LIMIT_ARENA: str = "google_search"
_RATE_LIMIT_PROVIDER: str = "google_autocomplete"
_RATE_LIMIT_MAX_CALLS: int = 10
_RATE_LIMIT_WINDOW_SECONDS: int = 1


@register
class GoogleAutocompleteCollector(ArenaCollector):
    """Collects Google autocomplete suggestions across FREE, MEDIUM, and PREMIUM tiers.

    Supported tiers:
    - ``Tier.FREE``    — Undocumented Google endpoint (no credentials).
    - ``Tier.MEDIUM``  — Serper.dev autocomplete.
    - ``Tier.PREMIUM`` — SerpAPI autocomplete.

    Class Attributes:
        arena_name: ``"google_autocomplete"``
        platform_name: ``"google"``
        supported_tiers: ``[Tier.FREE, Tier.MEDIUM, Tier.PREMIUM]``

    Args:
        credential_pool: Optional credential pool for API key rotation.
            Required for MEDIUM and PREMIUM tiers; ignored for FREE.
        rate_limiter: Optional Redis-backed rate limiter.  When present,
            every outbound request is gated through it.
        http_client: Optional injected :class:`httpx.AsyncClient`.  Inject
            for testing.  If ``None``, a new client is created per call.
    """

    arena_name: str = "google_autocomplete"
    platform_name: str = "google"
    supported_tiers: list[Tier] = [Tier.FREE, Tier.MEDIUM, Tier.PREMIUM]

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
    ) -> list[dict[str, Any]]:
        """Collect autocomplete suggestions for each search term.

        For each term, the collector fetches autocomplete suggestions from
        the configured tier's provider.  Each suggestion becomes one
        normalized content record with ``content_type="autocomplete_suggestion"``.

        Args:
            terms: Search terms to get suggestions for.
            tier: Operational tier selecting provider and authentication.
            date_from: Not used — autocomplete has no date dimension.
            date_to: Not used.
            max_results: Upper bound on total records returned.  ``None``
                uses the tier default.

        Returns:
            List of normalized content record dicts.

        Raises:
            ArenaRateLimitError: On HTTP 429 from the upstream provider.
            ArenaAuthError: On HTTP 401 or 403 from the upstream provider.
            ArenaCollectionError: On other unrecoverable API errors.
            NoCredentialAvailableError: When no API key is available for
                MEDIUM or PREMIUM tiers.
        """
        tier_config = self.get_tier_config(tier)
        if tier_config is None:
            logger.warning(
                "google_autocomplete: tier %s has no config. Returning [].", tier.value
            )
            return []

        effective_max = (
            max_results if max_results is not None else tier_config.max_results_per_run
        )

        cred: dict[str, Any] | None = None
        if tier != Tier.FREE:
            cred = await self._acquire_credential(tier)

        all_records: list[dict[str, Any]] = []

        async with self._build_http_client() as client:
            for term in terms:
                if len(all_records) >= effective_max:
                    break
                try:
                    records = await self._collect_term(
                        client=client,
                        term=term,
                        tier=tier,
                        credential=cred,
                    )
                except (ArenaRateLimitError, ArenaAuthError):
                    if cred and self.credential_pool:
                        await self.credential_pool.report_error(
                            credential_id=cred["id"],
                            error=ArenaRateLimitError("rate limit hit"),
                        )
                    raise
                all_records.extend(records)

        logger.info(
            "google_autocomplete: collected %d suggestions for %d terms at tier=%s",
            len(all_records),
            len(terms),
            tier.value,
        )
        return all_records[:effective_max]

    async def collect_by_actors(
        self,
        actor_ids: list[str],
        tier: Tier,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """Not supported for Google Autocomplete.

        Autocomplete suggestions are inherently term-based.  There is no
        meaningful concept of an "actor" in the autocomplete context.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            "Google Autocomplete does not support actor-based collection. "
            "Use collect_by_terms() with search terms relevant to the actors."
        )

    def get_tier_config(self, tier: Tier) -> TierConfig | None:
        """Return the tier configuration for this arena.

        Args:
            tier: The requested operational tier.

        Returns:
            :class:`TierConfig` for FREE, MEDIUM, and PREMIUM.  ``None``
            is not expected but may be returned if tier is not configured.

        Raises:
            ValueError: If *tier* is not a recognised :class:`Tier` value.
        """
        if tier not in GOOGLE_AUTOCOMPLETE_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}' for google_autocomplete. "
                f"Valid tiers: {list(GOOGLE_AUTOCOMPLETE_TIERS.keys())}"
            )
        return GOOGLE_AUTOCOMPLETE_TIERS[tier]

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single autocomplete suggestion to the universal schema.

        Sets ``content_type="autocomplete_suggestion"`` before delegating to
        :class:`Normalizer`.  The ``raw_item`` must contain:
        - ``suggestion``: The autocomplete suggestion text.
        - ``query``: The input query that generated the suggestion.
        - ``rank``: Zero-indexed position in the suggestions list.
        - ``tier``: Tier string used for collection.
        - ``relevance`` (optional): Relevance score from paid tiers.

        The ``platform_id`` is a deterministic SHA-256 hash of
        ``query + suggestion + collected_at_minute`` so that the same
        suggestion polled at different times creates distinct records.

        Args:
            raw_item: Raw dict from the suggestion extraction step.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        enriched = dict(raw_item)
        enriched["content_type"] = "autocomplete_suggestion"
        # Map suggestion text to fields the Normalizer recognises.
        enriched["text_content"] = enriched.get("suggestion", "")
        # title = the input query that triggered the suggestion (per brief).
        enriched["title"] = enriched.get("query", "")
        enriched["language"] = "da"
        # No URL associated with an autocomplete suggestion.
        enriched["url"] = None
        # No author concept.
        enriched["author_platform_id"] = None
        enriched["author_display_name"] = None

        # Deterministic platform_id: hash(query + suggestion + minute-bucket).
        minute_bucket = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M")
        id_input = f"{enriched.get('query', '')}:{enriched.get('suggestion', '')}:{minute_bucket}"
        enriched["id"] = hashlib.sha256(id_input.encode("utf-8")).hexdigest()

        # Engagement: use relevance score if available from paid tiers.
        relevance = enriched.get("relevance")
        if relevance is not None:
            try:
                enriched["engagement_score"] = float(relevance)
            except (TypeError, ValueError):
                pass

        return self._normalizer.normalize(
            raw_item=enriched,
            platform=self.platform_name,
            arena=self.arena_name,
            collection_tier=enriched.get("tier", "free"),
        )

    async def health_check(self) -> dict[str, Any]:
        """Verify connectivity with a minimal test query.

        Tests the FREE tier undocumented endpoint by default.  Also reports
        credential availability for MEDIUM/PREMIUM tiers if a credential
        pool is configured.

        Returns:
            Dict with ``status`` (``"ok"`` | ``"degraded"`` | ``"down"``),
            ``arena``, ``platform``, ``checked_at``, and optionally ``detail``.
        """
        checked_at = datetime.utcnow().isoformat() + "Z"
        base: dict[str, Any] = {
            "arena": self.arena_name,
            "platform": self.platform_name,
            "checked_at": checked_at,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    FREE_AUTOCOMPLETE_URL,
                    params={"q": "test", "client": "firefox", **DANISH_PARAMS},
                )
                response.raise_for_status()
                data = response.json()
                # Validate expected response format: ["query", [...suggestions...]]
                if not isinstance(data, list) or len(data) < 2:
                    return {
                        **base,
                        "status": "degraded",
                        "detail": f"Unexpected response format: {type(data).__name__}",
                    }
                return {**base, "status": "ok"}
        except httpx.HTTPStatusError as exc:
            return {
                **base,
                "status": "degraded",
                "detail": f"HTTP {exc.response.status_code} from suggestqueries.google.com",
            }
        except httpx.RequestError as exc:
            return {**base, "status": "down", "detail": f"Connection error: {exc}"}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _acquire_credential(self, tier: Tier) -> dict[str, Any]:
        """Acquire an API credential for *tier* from the credential pool.

        Uses ``platform="serper"`` for MEDIUM and ``platform="serpapi"`` for
        PREMIUM so credentials are shared with the Google Search arena.

        Args:
            tier: Operational tier (determines provider).

        Returns:
            Credential dict with ``id`` and ``api_key`` keys.

        Raises:
            NoCredentialAvailableError: When no credential is available.
        """
        if self.credential_pool is None:
            raise NoCredentialAvailableError(platform=self.platform_name, tier=tier.value)

        provider_platform = "serper" if tier == Tier.MEDIUM else "serpapi"
        cred = await self.credential_pool.acquire(platform=provider_platform, tier=tier.value)
        if cred is None:
            raise NoCredentialAvailableError(platform=provider_platform, tier=tier.value)
        return cred

    def _build_http_client(self) -> httpx.AsyncClient:
        """Return an :class:`httpx.AsyncClient` for use as a context manager.

        Returns the injected client if present; otherwise creates a new one
        with a 30-second timeout.
        """
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]
        return httpx.AsyncClient(timeout=30.0)

    async def _wait_for_rate_limit(self, credential_id: str) -> None:
        """Wait for a rate-limit slot before making an API call.

        Uses the key convention ``ratelimit:google_search:google_autocomplete:{credential_id}``.

        Args:
            credential_id: Credential identifier used as the Redis key suffix.
        """
        if self.rate_limiter is None:
            return
        key = f"ratelimit:{_RATE_LIMIT_ARENA}:{_RATE_LIMIT_PROVIDER}:{credential_id}"
        await self.rate_limiter.wait_for_slot(
            key=key,
            max_calls=_RATE_LIMIT_MAX_CALLS,
            window_seconds=_RATE_LIMIT_WINDOW_SECONDS,
        )

    async def _collect_term(
        self,
        client: httpx.AsyncClient,
        term: str,
        tier: Tier,
        credential: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Fetch autocomplete suggestions for a single term.

        Dispatches to the appropriate provider based on *tier*, parses the
        response into suggestion dicts, and normalizes each one.

        Args:
            client: Shared HTTP client.
            term: Search term to get suggestions for.
            tier: Operational tier.
            credential: Credential dict (None for FREE tier).

        Returns:
            List of normalized content record dicts for the term's suggestions.

        Raises:
            ArenaRateLimitError: On HTTP 429.
            ArenaAuthError: On HTTP 401 or 403.
            ArenaCollectionError: On other non-2xx responses.
        """
        cred_id = credential["id"] if credential else "free"
        await self._wait_for_rate_limit(cred_id)

        tier_str = tier.value

        try:
            if tier == Tier.FREE:
                raw_suggestions = await self._fetch_free(client, term)
            elif tier == Tier.MEDIUM:
                raw_suggestions = await self._fetch_serper(client, term, credential["api_key"])
            else:
                raw_suggestions = await self._fetch_serpapi(client, term, credential["api_key"])
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code == 429:
                retry_after = float(exc.response.headers.get("Retry-After", 60))
                raise ArenaRateLimitError(
                    f"google_autocomplete: 429 from provider at tier={tier_str}",
                    retry_after=retry_after,
                    arena=self.arena_name,
                    platform=self.platform_name,
                ) from exc
            if status_code in (401, 403):
                raise ArenaAuthError(
                    f"google_autocomplete: {status_code} auth error at tier={tier_str}",
                    arena=self.arena_name,
                    platform=self.platform_name,
                ) from exc
            raise ArenaCollectionError(
                f"google_autocomplete: HTTP {status_code} from provider at tier={tier_str}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"google_autocomplete: connection error at tier={tier_str}: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

        records: list[dict[str, Any]] = []
        for rank, suggestion_text in enumerate(raw_suggestions):
            raw_item: dict[str, Any] = {
                "suggestion": suggestion_text,
                "query": term,
                "rank": rank,
                "tier": tier_str,
                "gl": DANISH_PARAMS["gl"],
                "hl": DANISH_PARAMS["hl"],
            }
            records.append(self.normalize(raw_item))

        logger.debug(
            "google_autocomplete: term=%r returned %d suggestions (tier=%s)",
            term,
            len(records),
            tier_str,
        )
        return records

    async def _fetch_free(
        self, client: httpx.AsyncClient, term: str
    ) -> list[str]:
        """Fetch suggestions from the undocumented Google endpoint.

        Args:
            client: Shared HTTP client.
            term: Search term.

        Returns:
            List of suggestion strings.

        Raises:
            httpx.HTTPStatusError: On non-2xx response.
            httpx.RequestError: On connection failure.
        """
        response = await client.get(
            FREE_AUTOCOMPLETE_URL,
            params={"q": term, "client": "firefox", **DANISH_PARAMS},
        )
        response.raise_for_status()
        data = response.json()
        # Format: ["query", ["sug1", "sug2", ...]]
        if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list):
            return [str(s) for s in data[1] if s]
        logger.warning(
            "google_autocomplete: unexpected FREE response format for term=%r: %s",
            term,
            type(data).__name__,
        )
        return []

    async def _fetch_serper(
        self, client: httpx.AsyncClient, term: str, api_key: str
    ) -> list[str]:
        """Fetch suggestions from Serper.dev autocomplete endpoint.

        Args:
            client: Shared HTTP client.
            term: Search term.
            api_key: Serper.dev API key.

        Returns:
            List of suggestion strings.

        Raises:
            httpx.HTTPStatusError: On non-2xx response.
            httpx.RequestError: On connection failure.
        """
        payload = {"q": term, **DANISH_PARAMS}
        headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
        response = await client.post(SERPER_AUTOCOMPLETE_URL, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        # Serper returns a JSON object with a suggestions array.
        suggestions = data.get("suggestions", [])
        result: list[str] = []
        for item in suggestions:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                text = item.get("value") or item.get("text") or item.get("suggestion", "")
                if text:
                    result.append(str(text))
        return result

    async def _fetch_serpapi(
        self, client: httpx.AsyncClient, term: str, api_key: str
    ) -> list[str]:
        """Fetch suggestions from the SerpAPI autocomplete endpoint.

        Args:
            client: Shared HTTP client.
            term: Search term.
            api_key: SerpAPI API key.

        Returns:
            List of suggestion strings.

        Raises:
            httpx.HTTPStatusError: On non-2xx response.
            httpx.RequestError: On connection failure.
        """
        params = {
            "engine": "google_autocomplete",
            "q": term,
            "api_key": api_key,
            **DANISH_PARAMS,
        }
        response = await client.get(SERPAPI_AUTOCOMPLETE_URL, params=params)
        response.raise_for_status()
        data = response.json()
        # SerpAPI returns {"suggestions": [{"value": ..., "relevance": ...}, ...]}
        suggestions_raw = data.get("suggestions", [])
        result: list[str] = []
        for item in suggestions_raw:
            if isinstance(item, dict):
                text = item.get("value", "")
                if text:
                    result.append(str(text))
            elif isinstance(item, str):
                result.append(item)
        return result
