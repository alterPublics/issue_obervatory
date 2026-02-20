"""AI Chat Search arena collector implementation.

Collects AI-mediated information environment data via OpenRouter, capturing
the synthesized answers and cited sources returned by web-search-enabled
LLMs (Perplexity Sonar) when queried with Danish search terms.

**Collection flow**:

1. For each search term, call :func:`~._query_expander.expand_term` to
   generate N realistic Danish phrasings.
2. For each phrasing, call :func:`~._openrouter.chat_completion` with the
   Perplexity Sonar model to get a synthesized response and citations.
3. Create one ``ai_chat_response`` content record per phrasing.
4. Create one ``ai_chat_citation`` content record per cited URL.
5. Return all records.

Two content record types are produced:
- ``ai_chat_response`` — the synthesized answer (``text_content`` = model
  output, ``language="da"``, ``author_platform_id`` = model name).
- ``ai_chat_citation`` — each cited URL (``platform`` = domain, ``url`` =
  cited URL, ``text_content`` = snippet if available).

**Tiers**: MEDIUM (``perplexity/sonar``, 5 phrasings/term) and PREMIUM
(``perplexity/sonar-pro``, 10 phrasings/term).  FREE tier is not supported
and returns ``[]`` with a warning log.

**Dedup keys**:
- Response: ``sha256(phrasing + model + day_bucket_utc)``
- Citation: ``sha256(citation_url + phrasing + day_bucket_utc)``

Record factory functions live in :mod:`._records` to keep this module within
the ~400-line file size limit.

See research brief: ``docs/arenas/ai_chat_search.md``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx

from issue_observatory.arenas.ai_chat_search import _openrouter, _query_expander
from issue_observatory.arenas.ai_chat_search._records import (
    make_citation_record,
    make_response_record,
)
from issue_observatory.arenas.ai_chat_search.config import (
    AI_CHAT_SEARCH_TIERS,
    CHAT_SYSTEM_PROMPT,
    CHAT_TIMEOUT_SECONDS,
    EXPANSION_TIMEOUT_SECONDS,
    get_chat_model,
    get_n_phrasings,
)
from issue_observatory.arenas.base import ArenaCollector, TemporalMode, Tier
from issue_observatory.arenas.query_builder import format_boolean_query_for_platform
from issue_observatory.arenas.registry import register
from issue_observatory.config.tiers import TierConfig
from issue_observatory.core.exceptions import (
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
    NoCredentialAvailableError,
)

logger = logging.getLogger(__name__)


def _day_bucket_utc() -> str:
    """Return today's UTC date as a ``YYYY-MM-DD`` string.

    Used as part of the deterministic dedup key so that re-running
    collection for the same day does not create duplicate records.

    Returns:
        UTC date string in ISO 8601 format, e.g. ``"2026-02-17"``.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@register
class AiChatSearchCollector(ArenaCollector):
    """Collects AI-mediated search responses from OpenRouter (Perplexity Sonar).

    Supported tiers:
    - ``Tier.MEDIUM``  — ``perplexity/sonar``, 5 phrasings per term.
    - ``Tier.PREMIUM`` — ``perplexity/sonar-pro``, 10 phrasings per term.

    FREE tier is not supported.  A credential with
    ``platform="openrouter"`` must be provisioned in the ``CredentialPool``
    before collection can run (or ``OPENROUTER_API_KEY`` env var set).

    Class Attributes:
        arena_name: ``"ai_chat_search"`` (written to ``content_records.arena``).
        platform_name: ``"openrouter"`` (written to ``content_records.platform``
            for response records; citation records use the cited domain).
        supported_tiers: ``[Tier.MEDIUM, Tier.PREMIUM]``.

    Args:
        credential_pool: Optional shared credential pool.  Used to
            acquire/release OpenRouter API keys.  Falls back to
            ``OPENROUTER_API_KEY`` env var when ``None``.
        rate_limiter: Optional Redis-backed rate limiter.
        http_client: Optional injected :class:`httpx.AsyncClient`.
            Inject for unit testing.  If ``None``, a new client is
            created per collection call with tier-appropriate timeouts.
    """

    arena_name: str = "ai_chat_search"
    platform_name: str = "openrouter"
    supported_tiers: list[Tier] = [Tier.MEDIUM, Tier.PREMIUM]
    temporal_mode: TemporalMode = TemporalMode.RECENT

    def __init__(
        self,
        credential_pool: Any = None,
        rate_limiter: Any = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(credential_pool=credential_pool, rate_limiter=rate_limiter)
        self._http_client = http_client

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
        """Collect AI chat search responses and citations for the given terms.

        For each term, the collector:
        1. Expands the term into N Danish phrasings (via ``google/gemma-3-27b-it:free``).
        2. Submits each phrasing to Perplexity Sonar via OpenRouter.
        3. Creates one ``ai_chat_response`` record per phrasing.
        4. Creates one ``ai_chat_citation`` record per cited URL.

        When ``term_groups`` is provided, each AND-group is concatenated into
        a single query phrase and passed as a separate prompt.

        Note: ``date_from`` and ``date_to`` are not supported by this arena.

        Args:
            terms: Search terms (used when ``term_groups`` is ``None``).
            tier: Must be ``Tier.MEDIUM`` or ``Tier.PREMIUM``.
            date_from: Ignored — no date filtering available for this arena.
            date_to: Ignored — no date filtering available for this arena.
            max_results: Upper bound on returned records.
            term_groups: Optional boolean AND/OR groups.  Each group is
                submitted as a space-joined phrase prompt.
            language_filter: Not used — prompts are already in Danish.

        Returns:
            List of normalized content record dicts (mix of
            ``ai_chat_response`` and ``ai_chat_citation`` types).

        Raises:
            ValueError: If *tier* is not in ``supported_tiers``.
            NoCredentialAvailableError: If no OpenRouter credential is available.
            ArenaAuthError: If the API key is rejected (HTTP 401/403).
            ArenaCollectionError: On unrecoverable API errors.
            ArenaRateLimitError: On HTTP 429 from OpenRouter.
        """
        if tier == Tier.FREE:
            logger.warning(
                "ai_chat_search: FREE tier is not supported. "
                "No free web-search AI API exists. Returning empty list."
            )
            return []

        self._validate_tier(tier)
        tier_config = self.get_tier_config(tier)
        effective_max = (
            max_results if max_results is not None else tier_config.max_results_per_run
        )

        model = get_chat_model(tier)
        n_phrasings = get_n_phrasings(tier)

        credential = await self._acquire_credential(tier)
        api_key: str = credential["api_key"]
        credential_id: str = credential.get("id", "unknown")

        # Build effective terms: one space-joined query per AND-group.
        if term_groups is not None:
            effective_terms: list[str] = [
                format_boolean_query_for_platform(groups=[grp], platform="bluesky")
                for grp in term_groups
                if grp
            ]
        else:
            effective_terms = list(terms)

        all_records: list[dict[str, Any]] = []
        day_bucket = _day_bucket_utc()

        try:
            async with self._build_http_client(CHAT_TIMEOUT_SECONDS) as client:
                for term in effective_terms:
                    if len(all_records) >= effective_max:
                        break

                    term_records = await self._collect_term(
                        client=client,
                        term=term,
                        model=model,
                        n_phrasings=n_phrasings,
                        api_key=api_key,
                        credential_id=credential_id,
                        day_bucket=day_bucket,
                        remaining_budget=effective_max - len(all_records),
                    )
                    all_records.extend(term_records)

        finally:
            if self.credential_pool is not None:
                await self.credential_pool.release(
                    credential_id=credential_id, task_id=None
                )

        logger.info(
            "ai_chat_search: collect_by_terms — %d records for %d queries (tier=%s)",
            len(all_records),
            len(effective_terms),
            tier.value,
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
        """Not supported for the AI Chat Search arena.

        AI chatbots have no concept of "search by author" or "search by domain."
        Source-level analysis is performed post-hoc by analysing the
        citation records produced by :meth:`collect_by_terms`.

        Raises:
            NotImplementedError: Always raised.
        """
        raise NotImplementedError(
            "AI Chat Search does not support actor-based collection. "
            "Use collect_by_terms() instead. "
            "Source-level analysis is performed by querying the ai_chat_citation records."
        )

    def get_tier_config(self, tier: Tier) -> TierConfig:
        """Return tier configuration for the AI Chat Search arena.

        Args:
            tier: Requested operational tier.

        Returns:
            :class:`~issue_observatory.config.tiers.TierConfig` for the tier.

        Raises:
            ValueError: If *tier* is not ``MEDIUM`` or ``PREMIUM``.
        """
        if tier not in AI_CHAT_SEARCH_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}' for ai_chat_search. "
                f"Valid tiers: {list(AI_CHAT_SEARCH_TIERS.keys())}"
            )
        return AI_CHAT_SEARCH_TIERS[tier]

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Not used directly — raises NotImplementedError.

        This arena produces two distinct record types (``ai_chat_response``
        and ``ai_chat_citation``) via dedicated factory functions in
        :mod:`._records`.  Use :func:`~._records.make_response_record` and
        :func:`~._records.make_citation_record` directly.

        Raises:
            NotImplementedError: Always raised.
        """
        raise NotImplementedError(
            "Use _make_response_record or _make_citation_record directly. "
            "This arena produces two distinct record types that cannot be "
            "normalised through a single generic normalize() path."
        )

    async def estimate_credits(
        self,
        terms: list[str] | None = None,
        actor_ids: list[str] | None = None,
        tier: Tier = Tier.MEDIUM,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
    ) -> int:
        """Estimate the credit cost for an AI Chat Search collection run.

        Each term generates N phrasings (5 for MEDIUM, 10 for PREMIUM).
        Each phrasing calls the Perplexity Sonar API once.
        1 credit ≈ 1 API call.

        Args:
            terms: Search terms to expand and query.
            actor_ids: Not applicable for AI Chat Search.
            tier: MEDIUM or PREMIUM.
            date_from: Not used (AI chat search is real-time only).
            date_to: Not used.
            max_results: Not used (results depend on citation count).

        Returns:
            Estimated credit cost as a non-negative integer.
        """
        if tier not in self.supported_tiers:
            return 0

        all_terms = list(terms or [])
        if not all_terms:
            return 0

        # Get phrasings per term based on tier
        from issue_observatory.arenas.ai_chat_search.config import get_n_phrasings

        n_phrasings = get_n_phrasings(tier)

        # Each phrasing = 1 API call to Perplexity Sonar
        total_calls = len(all_terms) * n_phrasings

        # Approximate cost multiplier for PREMIUM (higher token costs)
        if tier == Tier.PREMIUM:
            return total_calls * 5  # 5x cost factor for Sonar Pro
        return total_calls

    async def health_check(self) -> dict[str, Any]:
        """Verify OpenRouter connectivity with a minimal expansion test.

        Attempts to expand the term ``"Danmark"`` with 1 phrasing using the
        free ``google/gemma-3-27b-it:free`` model.  No Perplexity credits
        are consumed.  Returns ``"ok"`` on success, ``"degraded"`` if the
        expansion call returns no phrasings, or ``"down"`` if no credential
        is available or a fatal error occurs.

        Returns:
            Dict with ``status`` (``"ok"`` | ``"degraded"`` | ``"down"``),
            ``arena``, ``platform``, ``checked_at``, and optionally ``detail``.
        """
        checked_at = datetime.now(timezone.utc).isoformat()
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

        try:
            async with httpx.AsyncClient(
                timeout=EXPANSION_TIMEOUT_SECONDS,
                headers={
                    "User-Agent": (
                        "IssueObservatory/1.0 "
                        "(ai-chat-search-health-check; research use)"
                    )
                },
            ) as client:
                phrasings = await _query_expander.expand_term(
                    client=client,
                    term="Danmark",
                    n_phrasings=1,
                    api_key=api_key,
                    rate_limiter=None,
                )

            if phrasings:
                return {
                    **base,
                    "status": "ok",
                    "detail": (
                        f"Expansion model reachable; sample: {phrasings[0]!r}"
                    ),
                }
            return {
                **base,
                "status": "degraded",
                "detail": "Expansion call succeeded but returned no phrasings.",
            }

        except ArenaAuthError as exc:
            return {
                **base,
                "status": "down",
                "detail": f"API key rejected (HTTP 401/403): {exc}",
            }
        except ArenaRateLimitError as exc:
            return {
                **base,
                "status": "degraded",
                "detail": f"Rate limited during health check: {exc}",
            }
        except ArenaCollectionError as exc:
            return {
                **base,
                "status": "down",
                "detail": f"Collection error during health check: {exc}",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                **base,
                "status": "down",
                "detail": f"Unexpected error: {exc}",
            }
        finally:
            if self.credential_pool is not None and credential is not None:
                await self.credential_pool.release(
                    credential_id=credential_id, task_id=None
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _acquire_credential(self, tier: Tier) -> dict[str, Any]:
        """Acquire an OpenRouter credential for the given tier.

        Falls back to the ``OPENROUTER_API_KEY`` environment variable when
        no credential pool is configured.

        Args:
            tier: Operational tier (``MEDIUM`` or ``PREMIUM``).

        Returns:
            Credential dict with at minimum ``{"api_key": "...", "id": "..."}``.

        Raises:
            NoCredentialAvailableError: If no credential is available.
        """
        if self.credential_pool is None:
            import os  # noqa: PLC0415

            api_key = os.environ.get("OPENROUTER_API_KEY")
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

    @asynccontextmanager
    async def _build_http_client(self, timeout: float) -> AsyncIterator[httpx.AsyncClient]:
        """Async context manager yielding an HTTP client.

        Yields the injected client directly (for testing, without re-entering);
        otherwise creates a new client with the specified timeout.

        Args:
            timeout: Request timeout in seconds.
        """
        if self._http_client is not None:
            yield self._http_client
            return
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={
                "User-Agent": (
                    "IssueObservatory/1.0 (ai-chat-search-collector; research use)"
                )
            },
        ) as client:
            yield client

    async def _collect_term(
        self,
        client: httpx.AsyncClient,
        term: str,
        model: str,
        n_phrasings: int,
        api_key: str,
        credential_id: str,
        day_bucket: str,
        remaining_budget: int,
    ) -> list[dict[str, Any]]:
        """Expand one search term and collect responses for all phrasings.

        Args:
            client: Shared HTTP client.
            term: Original search term (e.g. ``"CO2 afgift"``).
            model: OpenRouter model identifier for the chat search step.
            n_phrasings: Number of Danish phrasings to generate.
            api_key: OpenRouter API key.
            credential_id: Credential ID for error reporting.
            day_bucket: UTC date string for dedup key construction.
            remaining_budget: Maximum additional records to add.

        Returns:
            List of content records (responses + citations) for this term.
        """
        records: list[dict[str, Any]] = []

        # Expand term into Danish phrasings
        try:
            phrasings = await _query_expander.expand_term(
                client=client,
                term=term,
                n_phrasings=n_phrasings,
                api_key=api_key,
                rate_limiter=self.rate_limiter,
            )
        except (ArenaRateLimitError, ArenaAuthError):
            if self.credential_pool is not None:
                await self.credential_pool.report_error(
                    platform=self.platform_name,
                    credential_id=credential_id,
                )
            raise
        except ArenaCollectionError:
            logger.warning(
                "ai_chat_search: expansion failed for term '%s' — skipping.", term
            )
            return records

        if not phrasings:
            logger.warning(
                "ai_chat_search: no phrasings generated for term '%s' — skipping.",
                term,
            )
            return records

        # Submit each phrasing to the chat search model
        for phrasing in phrasings:
            if len(records) >= remaining_budget:
                break

            try:
                response = await _openrouter.chat_completion(
                    client=client,
                    model=model,
                    system_prompt=CHAT_SYSTEM_PROMPT,
                    user_message=phrasing,
                    api_key=api_key,
                    rate_limiter=self.rate_limiter,
                )
            except (ArenaRateLimitError, ArenaAuthError):
                if self.credential_pool is not None:
                    await self.credential_pool.report_error(
                        platform=self.platform_name,
                        credential_id=credential_id,
                    )
                raise
            except ArenaCollectionError:
                logger.warning(
                    "ai_chat_search: chat search failed for phrasing '%s' — skipping.",
                    phrasing,
                )
                continue

            citations = _openrouter.extract_citations(response)

            response_record = make_response_record(
                phrasing=phrasing,
                original_term=term,
                response=response,
                model_used=model,
                citations=citations,
                day_bucket=day_bucket,
                arena_name=self.arena_name,
                platform_name=self.platform_name,
            )
            records.append(response_record)
            parent_id = response_record["platform_id"]

            for rank, citation in enumerate(citations, start=1):
                if len(records) >= remaining_budget:
                    break
                citation_record = make_citation_record(
                    citation=citation,
                    phrasing=phrasing,
                    original_term=term,
                    model_used=model,
                    rank=rank,
                    parent_platform_id=parent_id,
                    day_bucket=day_bucket,
                    arena_name=self.arena_name,
                )
                records.append(citation_record)

        return records
