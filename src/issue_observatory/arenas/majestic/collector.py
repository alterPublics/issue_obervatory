"""Majestic backlink intelligence arena collector.

Majestic provides link graph data (Trust Flow, Citation Flow, backlink counts)
for web domains and URLs.  It is a reactive analysis tool: collection is
triggered by domain names discovered from other arenas, not by keyword queries
or user account feeds.

**Supported tiers**: PREMIUM only (Full API plan, $399.99/month).

**Collection modes**:

- ``collect_by_terms()``: Each term is treated as a domain name (or a URL from
  which the domain is extracted).  Calls ``GetIndexItemInfo`` to retrieve
  domain-level metrics (Trust Flow, Citation Flow, RefDomains, ExtBackLinks).
  Returns ``content_type="domain_metrics"`` records.

- ``collect_by_actors()``: Actor IDs are domain names.  In addition to domain
  metrics, also calls ``GetBackLinkData`` to retrieve individual backlinks.
  Returns both ``content_type="domain_metrics"`` AND
  ``content_type="backlink"`` records.

**No Danish language filter**: Majestic indexes URL/domain structure, not page
content.  Danish focus is achieved by querying Danish domains, not via a
language parameter.

**Credentials**: ``CredentialPool.acquire(platform="majestic", tier="premium")``
with JSONB ``{"api_key": "..."}``.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from issue_observatory.arenas.base import ArenaCollector, Tier
from issue_observatory.arenas.query_builder import format_boolean_query_for_platform
from issue_observatory.arenas.majestic.config import (
    CMD_GET_BACKLINK_DATA,
    CMD_GET_INDEX_ITEM_INFO,
    MAJESTIC_API_BASE,
    MAJESTIC_BACKLINK_MODE_ONE_PER_DOMAIN,
    MAJESTIC_DEFAULT_DATASOURCE,
    MAJESTIC_HEALTH_CHECK_DOMAIN,
    MAJESTIC_HEALTH_MIN_TRUST_FLOW,
    MAJESTIC_MAX_BACKLINKS_PER_DOMAIN,
    MAJESTIC_MAX_CALLS_PER_SECOND,
    MAJESTIC_RATE_LIMIT_KEY_TEMPLATE,
    MAJESTIC_RATE_LIMIT_TIMEOUT,
    MAJESTIC_RATE_LIMIT_WINDOW_SECONDS,
    MAJESTIC_TIERS,
    MAJESTIC_UNITS_PER_CREDIT,
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
class MajesticCollector(ArenaCollector):
    """Collects backlink intelligence from the Majestic Full API.

    Treats each search term or actor ID as a domain name.
    ``collect_by_terms()`` retrieves domain-level metrics only.
    ``collect_by_actors()`` additionally retrieves individual backlinks.

    Only ``Tier.PREMIUM`` is supported.  No free or medium tier exists for
    the Majestic API.

    Class Attributes:
        arena_name: ``"web"`` (written to ``content_records.arena``).
        platform_name: ``"majestic"``.
        supported_tiers: ``[Tier.PREMIUM]``.

    Args:
        credential_pool: Required for PREMIUM tier.
        rate_limiter: Optional Redis-backed rate limiter.  Falls back to
            ``asyncio.sleep(1.0)`` (1 req/sec) when ``None``.
        http_client: Optional injected :class:`httpx.AsyncClient`.
            Inject for unit testing.  If ``None``, a new client is created
            per collection call.
    """

    arena_name: str = "web"
    platform_name: str = "majestic"
    supported_tiers: list[Tier] = [Tier.PREMIUM]

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
        """Collect domain-level metrics for a list of domain names or URLs.

        Each term is treated as a domain name.  If a term looks like a full
        URL (contains ``://``), the domain is extracted automatically.

        Majestic operates on domain names, not boolean text queries.  When
        ``term_groups`` is provided, all terms from all groups are flattened
        into a single domain list (since domain metrics do not have boolean
        logic).

        Only ``Tier.PREMIUM`` is supported.  ``Tier.FREE`` or ``Tier.MEDIUM``
        raise ``NotImplementedError``.

        Args:
            terms: List of domain names or URLs (used when ``term_groups``
                is ``None``).
            tier: Must be ``Tier.PREMIUM``.
            date_from: Unused — Majestic does not support date filtering.
            date_to: Unused — Majestic does not support date filtering.
            max_results: Upper bound on returned records.
            term_groups: Optional groups; all terms across groups are merged
                into the domain list (boolean logic does not apply to domains).
            language_filter: Not used.

        Returns:
            List of normalized ``content_type="domain_metrics"`` records.

        Raises:
            NotImplementedError: If ``tier`` is ``FREE`` or ``MEDIUM``.
            ValueError: If ``tier`` is not in ``supported_tiers``.
            NoCredentialAvailableError: If no credential is available.
            ArenaAuthError: If the API key is rejected.
            ArenaCollectionError: On unrecoverable API errors.
        """
        _raise_if_not_premium(tier)
        self._validate_tier(tier)

        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

        credential = await self._acquire_credential()
        api_key: str = credential["api_key"]
        credential_id: str = credential.get("id", "unknown")

        # For Majestic, flatten all groups into a single term list.
        effective_terms: list[str] = (
            [t for grp in term_groups for t in grp] if term_groups is not None else list(terms)
        )
        domains = [_extract_domain(term) for term in effective_terms]
        domains = [d for d in domains if d][:effective_max]

        all_records: list[dict[str, Any]] = []

        try:
            async with self._build_http_client() as client:
                # Batch GetIndexItemInfo calls (up to 100 items per call)
                for batch_start in range(0, len(domains), 100):
                    batch = domains[batch_start : batch_start + 100]
                    await self._rate_limit_wait(credential_id)
                    raw_response = await self._call_majestic(
                        cmd=CMD_GET_INDEX_ITEM_INFO,
                        params=_build_index_item_params(batch),
                        credential=credential,
                        client=client,
                        credential_id=credential_id,
                    )
                    items = _extract_index_items(raw_response)
                    for item in items:
                        item["_record_type"] = "domain_metrics"
                        all_records.append(self.normalize(item))
        finally:
            if self.credential_pool is not None:
                await self.credential_pool.release(
                    credential_id=credential_id, task_id=None
                )

        logger.info(
            "majestic: collect_by_terms — %d domain_metrics records for %d domains",
            len(all_records),
            len(domains),
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
        """Collect domain metrics and individual backlinks for domain actor IDs.

        Actor IDs are expected to be domain names (e.g. ``"dr.dk"``).  For
        each domain the method calls:
        1. ``GetIndexItemInfo`` — domain-level metrics record.
        2. ``GetBackLinkData`` — up to ``MAJESTIC_MAX_BACKLINKS_PER_DOMAIN``
           individual backlink records (Mode=1: one per referring domain).

        Returns a mixed list of ``content_type="domain_metrics"`` records
        followed by ``content_type="backlink"`` records.

        Only ``Tier.PREMIUM`` is supported.

        Args:
            actor_ids: List of domain names to analyse.
                Example: ``["dr.dk", "tv2.dk"]``.
            tier: Must be ``Tier.PREMIUM``.
            date_from: Optional earliest date filter passed to
                ``GetBackLinkData`` (``YYYY-MM-DD`` string or ``datetime``).
            date_to: Optional latest date filter passed to
                ``GetBackLinkData`` (``YYYY-MM-DD`` string or ``datetime``).
            max_results: Upper bound on total returned records.  ``None``
                uses the tier default (``MAJESTIC_MAX_BACKLINKS_PER_DOMAIN``).

        Returns:
            List of normalized records mixing domain_metrics and backlink
            content types.

        Raises:
            NotImplementedError: If ``tier`` is ``FREE`` or ``MEDIUM``.
            ValueError: If ``tier`` is not in ``supported_tiers``.
            NoCredentialAvailableError: If no credential is available.
            ArenaAuthError: If the API key is rejected.
            ArenaCollectionError: On unrecoverable API errors.
        """
        _raise_if_not_premium(tier)
        self._validate_tier(tier)

        tier_config = self.get_tier_config(tier)
        effective_max = max_results if max_results is not None else tier_config.max_results_per_run

        credential = await self._acquire_credential()
        api_key: str = credential["api_key"]
        credential_id: str = credential.get("id", "unknown")

        date_from_str = _format_date(date_from)
        date_to_str = _format_date(date_to)

        all_records: list[dict[str, Any]] = []

        try:
            async with self._build_http_client() as client:
                for domain in actor_ids:
                    if len(all_records) >= effective_max:
                        break

                    # 1. Domain metrics
                    await self._rate_limit_wait(credential_id)
                    metrics_response = await self._call_majestic(
                        cmd=CMD_GET_INDEX_ITEM_INFO,
                        params=_build_index_item_params([domain]),
                        credential=credential,
                        client=client,
                        credential_id=credential_id,
                    )
                    for item in _extract_index_items(metrics_response):
                        item["_record_type"] = "domain_metrics"
                        all_records.append(self.normalize(item))

                    if len(all_records) >= effective_max:
                        break

                    # 2. Individual backlinks
                    remaining = effective_max - len(all_records)
                    backlink_count = min(MAJESTIC_MAX_BACKLINKS_PER_DOMAIN, remaining)
                    await self._rate_limit_wait(credential_id)
                    backlinks_response = await self._call_majestic(
                        cmd=CMD_GET_BACKLINK_DATA,
                        params=_build_backlink_params(
                            domain=domain,
                            count=backlink_count,
                            date_from=date_from_str,
                            date_to=date_to_str,
                        ),
                        credential=credential,
                        client=client,
                        credential_id=credential_id,
                    )
                    for backlink in _extract_backlinks(backlinks_response, domain):
                        backlink["_record_type"] = "backlink"
                        backlink["_target_domain"] = domain
                        all_records.append(self.normalize(backlink))

        finally:
            if self.credential_pool is not None:
                await self.credential_pool.release(
                    credential_id=credential_id, task_id=None
                )

        logger.info(
            "majestic: collect_by_actors — %d records for %d domains",
            len(all_records),
            len(actor_ids),
        )
        return all_records

    def get_tier_config(self, tier: Tier) -> TierConfig:
        """Return tier configuration for the Majestic arena.

        Only ``Tier.PREMIUM`` is supported.

        Args:
            tier: Requested operational tier.

        Returns:
            :class:`~issue_observatory.config.tiers.TierConfig` for PREMIUM.

        Raises:
            ValueError: If ``tier`` is not ``Tier.PREMIUM``.
        """
        if tier not in MAJESTIC_TIERS:
            raise ValueError(
                f"Unknown tier '{tier}' for majestic. "
                f"Valid tiers: {list(MAJESTIC_TIERS.keys())}"
            )
        return MAJESTIC_TIERS[tier]

    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single Majestic API record to the universal schema.

        Dispatches to one of two normalisation paths based on
        ``raw_item["_record_type"]``:

        - ``"domain_metrics"``: Produces a ``content_type="domain_metrics"``
          record with Trust Flow as the engagement proxy.
        - ``"backlink"``: Produces a ``content_type="backlink"`` record with
          the source URL's Trust Flow as the engagement proxy.

        Args:
            raw_item: Dict from the Majestic API, augmented with a private
                ``_record_type`` field (``"domain_metrics"`` or
                ``"backlink"``).

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        record_type = raw_item.get("_record_type", "domain_metrics")

        if record_type == "backlink":
            return self._normalize_backlink(raw_item)
        return self._normalize_domain_metrics(raw_item)

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """Verify Majestic API connectivity with a minimal test query.

        Issues ``GetIndexItemInfo`` for ``dr.dk`` and checks that Trust Flow
        is above zero, confirming the API key is valid and the index is
        responding.

        Returns:
            Dict with ``status`` (``"ok"`` | ``"degraded"`` | ``"down"``),
            ``arena``, ``platform``, ``checked_at``, and optionally
            ``trust_flow``, ``ref_domains``, and ``detail``.
        """
        checked_at = datetime.utcnow().isoformat() + "Z"
        base: dict[str, Any] = {
            "arena": self.arena_name,
            "platform": self.platform_name,
            "checked_at": checked_at,
        }

        credential: dict[str, Any] | None = None
        credential_id = "unknown"

        try:
            credential = await self._acquire_credential()
            credential_id = credential.get("id", "unknown")
        except (NoCredentialAvailableError, Exception) as exc:  # noqa: BLE001
            return {**base, "status": "down", "detail": f"No credential available: {exc}"}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                raw_response = await self._call_majestic(
                    cmd=CMD_GET_INDEX_ITEM_INFO,
                    params=_build_index_item_params([MAJESTIC_HEALTH_CHECK_DOMAIN]),
                    credential=credential,
                    client=client,
                    credential_id=credential_id,
                )
                items = _extract_index_items(raw_response)
                if not items:
                    return {
                        **base,
                        "status": "degraded",
                        "detail": f"{MAJESTIC_HEALTH_CHECK_DOMAIN} not found in Majestic index.",
                    }

                item = items[0]
                trust_flow = item.get("TrustFlow", 0)
                try:
                    trust_flow_int = int(trust_flow)
                except (TypeError, ValueError):
                    trust_flow_int = 0

                if trust_flow_int < MAJESTIC_HEALTH_MIN_TRUST_FLOW:
                    return {
                        **base,
                        "status": "degraded",
                        "detail": (
                            f"{MAJESTIC_HEALTH_CHECK_DOMAIN} returned Trust Flow {trust_flow_int} "
                            f"(expected >= {MAJESTIC_HEALTH_MIN_TRUST_FLOW})"
                        ),
                        "trust_flow": trust_flow_int,
                    }

                return {
                    **base,
                    "status": "ok",
                    "trust_flow": trust_flow_int,
                    "ref_domains": item.get("RefDomains"),
                }

        except ArenaAuthError as exc:
            return {**base, "status": "down", "detail": f"API key rejected: {exc}"}
        except ArenaCollectionError as exc:
            return {**base, "status": "down", "detail": str(exc)}
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

    async def _acquire_credential(self) -> dict[str, Any]:
        """Acquire a PREMIUM credential from the pool.

        Falls back to the ``MAJESTIC_PREMIUM_API_KEY`` environment variable
        when no pool is configured.

        Returns:
            Credential dict with at minimum ``{"api_key": "...", "id": "..."}``.

        Raises:
            NoCredentialAvailableError: If no credential is available.
        """
        if self.credential_pool is None:
            import os  # noqa: PLC0415

            api_key = os.environ.get("MAJESTIC_PREMIUM_API_KEY")
            if not api_key:
                raise NoCredentialAvailableError(
                    platform=self.platform_name, tier="premium"
                )
            return {"api_key": api_key, "id": "env"}

        cred = await self.credential_pool.acquire(
            platform=self.platform_name, tier="premium"
        )
        if cred is None:
            raise NoCredentialAvailableError(
                platform=self.platform_name, tier="premium"
            )
        return cred

    def _build_http_client(self) -> httpx.AsyncClient:
        """Return an async HTTP client for use as a context manager.

        Returns the injected client if present; otherwise creates a new one
        with a 30-second timeout and a descriptive User-Agent.

        Returns:
            :class:`httpx.AsyncClient` instance.
        """
        if self._http_client is not None:
            return self._http_client  # type: ignore[return-value]
        return httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "IssueObservatory/1.0 (majestic-collector; research use)"
            },
        )

    async def _rate_limit_wait(self, credential_id: str) -> None:
        """Wait for a rate-limit slot before making an API call.

        Uses the injected :class:`~issue_observatory.workers.rate_limiter.RateLimiter`
        when available; falls back to ``asyncio.sleep(1.0)`` (1 req/sec) when
        Redis is not configured.

        Args:
            credential_id: Credential ID used to construct the Redis key.
        """
        if self.rate_limiter is not None:
            key = MAJESTIC_RATE_LIMIT_KEY_TEMPLATE.format(credential_id=credential_id)
            try:
                await self.rate_limiter.wait_for_slot(
                    key=key,
                    max_calls=MAJESTIC_MAX_CALLS_PER_SECOND,
                    window_seconds=MAJESTIC_RATE_LIMIT_WINDOW_SECONDS,
                    timeout=MAJESTIC_RATE_LIMIT_TIMEOUT,
                )
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "majestic: rate_limiter.wait_for_slot failed (%s) — "
                    "falling back to sleep(1.0)",
                    exc,
                )

        await asyncio.sleep(1.0)

    async def _call_majestic(
        self,
        cmd: str,
        params: dict[str, Any],
        credential: dict[str, Any],
        client: httpx.AsyncClient,
        credential_id: str,
    ) -> dict[str, Any]:
        """Make a rate-limited GET request to the Majestic JSON API.

        Constructs the full parameter set (adding ``app_api_key`` and
        ``cmd``), executes the request, checks the Majestic ``Code`` field
        for application-level errors, and raises appropriate exceptions.

        Args:
            cmd: Majestic API command name (e.g. ``"GetIndexItemInfo"``).
            params: Command-specific query parameters (without API key or cmd).
            credential: Credential dict containing ``api_key``.
            client: Shared async HTTP client.
            credential_id: Credential ID for error reporting.

        Returns:
            Parsed JSON response dict.

        Raises:
            ArenaAuthError: If Majestic returns ``"InvalidAPIKey"``.
            ArenaCollectionError: If Majestic returns any non-OK result code,
                or on HTTP errors.
            ArenaRateLimitError: If Majestic returns ``"RateLimitExceeded"``,
                or on HTTP 429.
        """
        request_params: dict[str, Any] = {
            "app_api_key": credential["api_key"],
            "cmd": cmd,
            **params,
        }

        try:
            response = await client.get(MAJESTIC_API_BASE, params=request_params)
        except httpx.RequestError as exc:
            raise ArenaCollectionError(
                f"majestic: connection error: {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", 60))
            raise ArenaRateLimitError(
                "majestic: HTTP 429 rate limit",
                retry_after=retry_after,
                arena=self.arena_name,
                platform=self.platform_name,
            )

        if response.status_code == 401:
            if self.credential_pool is not None:
                await self.credential_pool.report_error(
                    credential_id=credential_id,
                    error=ArenaAuthError(
                        "majestic: HTTP 401",
                        arena=self.arena_name,
                        platform=self.platform_name,
                    ),
                )
            raise ArenaAuthError(
                f"majestic: API key rejected (HTTP 401) for credential {credential_id}",
                arena=self.arena_name,
                platform=self.platform_name,
            )

        if response.status_code >= 500:
            raise ArenaCollectionError(
                f"majestic: server error HTTP {response.status_code}",
                arena=self.arena_name,
                platform=self.platform_name,
            )

        try:
            data: dict[str, Any] = response.json()
        except Exception as exc:  # noqa: BLE001
            raise ArenaCollectionError(
                f"majestic: JSON parse error (HTTP {response.status_code}): {exc}",
                arena=self.arena_name,
                platform=self.platform_name,
            ) from exc

        result_code: str = data.get("Code", "")

        if result_code == "InvalidAPIKey":
            if self.credential_pool is not None:
                await self.credential_pool.report_error(
                    credential_id=credential_id,
                    error=ArenaAuthError(
                        "majestic: InvalidAPIKey",
                        arena=self.arena_name,
                        platform=self.platform_name,
                    ),
                )
            raise ArenaAuthError(
                f"majestic: Invalid API key (credential={credential_id})",
                arena=self.arena_name,
                platform=self.platform_name,
            )

        if result_code == "RateLimitExceeded":
            raise ArenaRateLimitError(
                "majestic: RateLimitExceeded from API",
                retry_after=60.0,
                arena=self.arena_name,
                platform=self.platform_name,
            )

        if result_code == "InsufficientCredits":
            raise ArenaCollectionError(
                "majestic: InsufficientCredits — monthly analysis unit budget exhausted. "
                "Stop collection to preserve remaining budget.",
                arena=self.arena_name,
                platform=self.platform_name,
            )

        if result_code not in ("OK", ""):
            raise ArenaCollectionError(
                f"majestic: API returned non-OK result code '{result_code}' "
                f"for cmd='{cmd}'",
                arena=self.arena_name,
                platform=self.platform_name,
            )

        return data

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------

    def _normalize_domain_metrics(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalise a ``GetIndexItemInfo`` item to the UCR schema.

        Produces a ``content_type="domain_metrics"`` record.  Trust Flow is
        used as the ``engagement_score``.  All metrics are stored in
        ``raw_metadata`` for downstream analysis.

        Args:
            raw_item: Single item dict from the ``DataTables.Results`` list
                of a ``GetIndexItemInfo`` response.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        domain: str = raw_item.get("Item", "")
        collected_at_str = datetime.now(tz=timezone.utc).isoformat()
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

        platform_id = hashlib.sha256(
            f"{domain}_{date_str}".encode("utf-8")
        ).hexdigest()

        trust_flow = raw_item.get("TrustFlow")
        try:
            engagement_score = float(trust_flow) if trust_flow is not None else None
        except (TypeError, ValueError):
            engagement_score = None

        raw_metadata: dict[str, Any] = {
            "TrustFlow": raw_item.get("TrustFlow"),
            "CitationFlow": raw_item.get("CitationFlow"),
            "ExtBackLinks": raw_item.get("ExtBackLinks"),
            "RefDomains": raw_item.get("RefDomains"),
            "RefSubNets": raw_item.get("RefSubNets"),
            "RefIPs": raw_item.get("RefIPs"),
            "IndexedURLs": raw_item.get("IndexedURLs"),
            "TopicalTrustFlow_Topic_0": raw_item.get("TopicalTrustFlow_Topic_0"),
            "TopicalTrustFlow_Value_0": raw_item.get("TopicalTrustFlow_Value_0"),
            "TopicalTrustFlow_Topic_1": raw_item.get("TopicalTrustFlow_Topic_1"),
            "TopicalTrustFlow_Value_1": raw_item.get("TopicalTrustFlow_Value_1"),
            "Status": raw_item.get("Status"),
            "ResultCode": raw_item.get("ResultCode"),
            "AnalysisResUnits": raw_item.get("AnalysisResUnits"),
            "datasource": MAJESTIC_DEFAULT_DATASOURCE,
        }

        url = f"https://{domain}" if domain and not domain.startswith("http") else domain

        content_hash = hashlib.sha256(
            f"{domain}_{date_str}".encode("utf-8")
        ).hexdigest()

        return {
            "platform": self.platform_name,
            "arena": self.arena_name,
            "platform_id": platform_id,
            "content_type": "domain_metrics",
            "url": url,
            "title": None,
            "text_content": None,
            "language": None,
            "published_at": None,
            "collected_at": collected_at_str,
            "author_platform_id": domain,
            "author_display_name": domain,
            "pseudonymized_author_id": None,
            "views_count": None,
            "likes_count": None,
            "shares_count": None,
            "comments_count": None,
            "engagement_score": engagement_score,
            "raw_metadata": raw_metadata,
            "media_urls": [],
            "content_hash": content_hash,
            "collection_tier": "premium",
        }

    def _normalize_backlink(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Normalise a ``GetBackLinkData`` backlink item to the UCR schema.

        Produces a ``content_type="backlink"`` record.  The source URL's
        Trust Flow is used as the ``engagement_score``.  The anchor text
        becomes ``text_content``.

        Args:
            raw_item: Single backlink dict from the ``DataTables.Results``
                list of a ``GetBackLinkData`` response, augmented with
                ``_target_domain``.

        Returns:
            Dict conforming to the ``content_records`` universal schema.
        """
        source_url: str = raw_item.get("SourceURL", "")
        target_url: str = raw_item.get("TargetURL", raw_item.get("_target_domain", ""))
        anchor_text: str | None = raw_item.get("AnchorText") or None
        first_indexed_date: str | None = raw_item.get("FirstIndexedDate") or None

        platform_id = hashlib.sha256(
            f"{source_url}{target_url}".encode("utf-8")
        ).hexdigest()

        content_hash = platform_id  # Same key — dedup on link pair

        source_trust_flow = raw_item.get("SourceTrustFlow")
        try:
            engagement_score = (
                float(source_trust_flow) if source_trust_flow is not None else None
            )
        except (TypeError, ValueError):
            engagement_score = None

        # Extract linking domain as proxy "author"
        linking_domain: str = _extract_domain(source_url) or source_url

        collected_at_str = datetime.now(tz=timezone.utc).isoformat()

        raw_metadata: dict[str, Any] = {
            "SourceURL": source_url,
            "TargetURL": target_url,
            "SourceTrustFlow": raw_item.get("SourceTrustFlow"),
            "SourceCitationFlow": raw_item.get("SourceCitationFlow"),
            "SourceTopicalTrustFlow_Topic_0": raw_item.get(
                "SourceTopicalTrustFlow_Topic_0"
            ),
            "FlagNoFollow": raw_item.get("FlagNoFollow"),
            "FlagRedirect": raw_item.get("FlagRedirect"),
            "FirstIndexedDate": first_indexed_date,
            "LastSeenDate": raw_item.get("LastSeenDate"),
            "DateLost": raw_item.get("DateLost"),
            "ReasonLost": raw_item.get("ReasonLost"),
            "AnchorText": anchor_text,
        }

        return {
            "platform": self.platform_name,
            "arena": self.arena_name,
            "platform_id": platform_id,
            "content_type": "backlink",
            "url": source_url,
            "title": None,
            "text_content": anchor_text,
            "language": None,
            "published_at": first_indexed_date,
            "collected_at": collected_at_str,
            "author_platform_id": linking_domain,
            "author_display_name": linking_domain,
            "pseudonymized_author_id": None,
            "views_count": None,
            "likes_count": None,
            "shares_count": None,
            "comments_count": None,
            "engagement_score": engagement_score,
            "raw_metadata": raw_metadata,
            "media_urls": [],
            "content_hash": content_hash,
            "collection_tier": "premium",
        }

    async def estimate_credits(
        self,
        terms: list[str] | None = None,
        actor_ids: list[str] | None = None,
        tier: Tier = Tier.PREMIUM,
        date_from: datetime | str | None = None,
        date_to: datetime | str | None = None,
        max_results: int | None = None,
    ) -> int:
        """Estimate the analysis unit cost (in credits) for a collection run.

        Mapping: 1 credit = ``MAJESTIC_UNITS_PER_CREDIT`` (1,000) analysis
        units.  Each domain metric call costs ~1 unit.  Each backlink call
        returning N rows costs ~N units.

        Args:
            terms: Domain names to query for metrics.
            actor_ids: Domain names for deep backlink collection.
            tier: Must be ``Tier.PREMIUM``.
            date_from: Unused.
            date_to: Unused.
            max_results: Upper bound on results.

        Returns:
            Estimated credit cost as a non-negative integer.
        """
        items = terms or []
        actors = actor_ids or []
        effective_max = max_results or MAJESTIC_MAX_BACKLINKS_PER_DOMAIN

        # Domain metric calls: 1 unit per domain
        metric_units = len(items) + len(actors)

        # Backlink calls: up to effective_max units per actor domain
        backlink_units = len(actors) * min(MAJESTIC_MAX_BACKLINKS_PER_DOMAIN, effective_max)

        total_units = metric_units + backlink_units
        return max(1, total_units // MAJESTIC_UNITS_PER_CREDIT)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _extract_domain(term: str) -> str:
    """Extract a bare domain name from a URL or return the term as-is.

    If the term contains ``://``, parse it as a URL and return the
    ``netloc`` component (without ``www.`` prefix).  Otherwise treat the
    term itself as a domain name.

    Args:
        term: URL or domain string.

    Returns:
        Bare domain name (e.g. ``"dr.dk"``), or the original term if
        parsing fails.
    """
    if "://" in term:
        try:
            parsed = urlparse(term)
            netloc = parsed.netloc.lower()
            if netloc.startswith("www."):
                netloc = netloc[4:]
            return netloc
        except Exception:  # noqa: BLE001
            return term
    return term.lower().strip()


def _format_date(value: datetime | str | None) -> str | None:
    """Format a date value as a ``YYYY-MM-DD`` string for Majestic filters.

    Args:
        value: ``datetime`` object, ISO 8601 string, or ``None``.

    Returns:
        Date string in ``YYYY-MM-DD`` format, or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if "T" in value:
        return value.split("T")[0]
    return value


def _build_index_item_params(domains: list[str]) -> dict[str, Any]:
    """Build query parameters for a ``GetIndexItemInfo`` batch request.

    Args:
        domains: List of domain names to query (up to 100).

    Returns:
        Dict of query parameters (without ``app_api_key`` and ``cmd``).
    """
    params: dict[str, Any] = {
        "items": len(domains),
        "datasource": MAJESTIC_DEFAULT_DATASOURCE,
    }
    for i, domain in enumerate(domains):
        params[f"item{i}"] = domain
    return params


def _build_backlink_params(
    domain: str,
    count: int,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Build query parameters for a ``GetBackLinkData`` request.

    Uses ``Mode=1`` (one backlink per referring domain) for efficient initial
    surveys.

    Args:
        domain: Target domain to retrieve backlinks for.
        count: Maximum number of backlinks to retrieve.
        date_from: Optional start date filter (``YYYY-MM-DD``).
        date_to: Optional end date filter (``YYYY-MM-DD``).

    Returns:
        Dict of query parameters (without ``app_api_key`` and ``cmd``).
    """
    params: dict[str, Any] = {
        "item": domain,
        "datasource": MAJESTIC_DEFAULT_DATASOURCE,
        "Count": count,
        "Mode": MAJESTIC_BACKLINK_MODE_ONE_PER_DOMAIN,
    }
    if date_from:
        params["From"] = date_from
    if date_to:
        params["To"] = date_to
    return params


def _extract_index_items(response_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the items list from a ``GetIndexItemInfo`` response.

    The Majestic JSON response nests results as::

        {"DataTables": {"Results": {"Data": [...]}}}

    Args:
        response_data: Parsed JSON response dict.

    Returns:
        List of item dicts (may be empty).
    """
    try:
        return response_data["DataTables"]["Results"]["Data"] or []
    except (KeyError, TypeError):
        return []


def _extract_backlinks(
    response_data: dict[str, Any], target_domain: str
) -> list[dict[str, Any]]:
    """Extract backlink rows from a ``GetBackLinkData`` response.

    The response structure mirrors ``GetIndexItemInfo``::

        {"DataTables": {"BackLinks": {"Data": [...]}}}

    Args:
        response_data: Parsed JSON response dict.
        target_domain: Target domain being linked to.  Used as a fallback
            ``TargetURL`` when the backlink row does not include it.

    Returns:
        List of backlink dicts (may be empty).
    """
    try:
        rows: list[dict[str, Any]] = (
            response_data["DataTables"]["BackLinks"]["Data"] or []
        )
    except (KeyError, TypeError):
        rows = []

    # Ensure TargetURL is present
    for row in rows:
        if not row.get("TargetURL"):
            row["TargetURL"] = target_domain
    return rows


def _raise_if_not_premium(tier: Tier) -> None:
    """Raise ``NotImplementedError`` for FREE and MEDIUM tiers.

    Majestic has no free or medium API access.  Only the Full API plan
    ($399.99/month) provides programmatic access.

    Args:
        tier: The requested tier.

    Raises:
        NotImplementedError: If ``tier`` is ``FREE`` or ``MEDIUM``.
    """
    if tier in (Tier.FREE, Tier.MEDIUM):
        raise NotImplementedError(
            f"Majestic does not support the '{tier.value}' tier. "
            "The Full API plan (Tier.PREMIUM, $399.99/month) is required for "
            "programmatic backlink data collection. "
            "The Lite ($49.99/mo) and Pro ($99.99/mo) plans provide web UI "
            "access only and are not sufficient for research use."
        )
