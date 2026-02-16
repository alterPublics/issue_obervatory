"""Standalone FastAPI router for the Majestic backlink intelligence arena.

Exposes three endpoints under the ``/majestic`` prefix:

- ``POST /majestic/collect/terms`` — domain metrics for a list of domains.
- ``POST /majestic/collect/actors`` — domain metrics plus backlinks for actor
  domains.
- ``GET  /majestic/health`` — API key and index connectivity check.

Only ``Tier.PREMIUM`` is supported.  Requests specifying ``"free"`` or
``"medium"`` receive HTTP 501 Not Implemented.

All collection endpoints are backed by
:class:`~issue_observatory.arenas.majestic.collector.MajesticCollector` and
run synchronously (no background tasks) so the response includes the collected
records.  For large-scale production collection, submit Celery tasks via the
``/collections`` orchestration API instead.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from issue_observatory.arenas.base import Tier
from issue_observatory.arenas.majestic.collector import MajesticCollector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/majestic", tags=["majestic"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CollectTermsRequest(BaseModel):
    """Request body for ``POST /majestic/collect/terms``.

    Attributes:
        terms: List of domain names or URLs to collect metrics for.
        tier: Operational tier.  Only ``"premium"`` is accepted.
        max_results: Upper bound on returned records.
    """

    terms: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Domain names or URLs to analyse.  URLs are automatically reduced "
            "to their domain component (e.g. 'https://dr.dk/nyheder' → 'dr.dk')."
        ),
    )
    tier: str = Field(
        default="premium",
        description="Operational tier.  Only 'premium' is supported for Majestic.",
    )
    max_results: int | None = Field(
        default=None,
        ge=1,
        description="Upper bound on returned records.  None uses the tier default.",
    )


class CollectActorsRequest(BaseModel):
    """Request body for ``POST /majestic/collect/actors``.

    Attributes:
        actor_ids: List of domain names to analyse.
        tier: Operational tier.  Only ``"premium"`` is accepted.
        date_from: Optional start date for backlink filtering (``YYYY-MM-DD``).
        date_to: Optional end date for backlink filtering (``YYYY-MM-DD``).
        max_results: Upper bound on total returned records.
    """

    actor_ids: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Domain names to analyse.  For each domain, both domain-level metrics "
            "and individual backlinks are returned."
        ),
    )
    tier: str = Field(
        default="premium",
        description="Operational tier.  Only 'premium' is supported for Majestic.",
    )
    date_from: str | None = Field(
        default=None,
        description="Earliest date for backlink filtering (YYYY-MM-DD).  Optional.",
    )
    date_to: str | None = Field(
        default=None,
        description="Latest date for backlink filtering (YYYY-MM-DD).  Optional.",
    )
    max_results: int | None = Field(
        default=None,
        ge=1,
        description="Upper bound on total returned records.  None uses the tier default.",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_premium_tier(tier_str: str) -> Tier:
    """Validate the tier string and enforce PREMIUM-only access.

    Args:
        tier_str: Tier string from request body (``"free"``, ``"medium"``,
            or ``"premium"``).

    Returns:
        ``Tier.PREMIUM`` enum value.

    Raises:
        :exc:`HTTPException` 422: If the tier string is not a valid
            :class:`~issue_observatory.arenas.base.Tier` value.
        :exc:`HTTPException` 501: If the tier is ``FREE`` or ``MEDIUM``.
    """
    try:
        tier = Tier(tier_str)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid tier '{tier_str}'. "
                f"Valid values: {[t.value for t in Tier]}"
            ),
        )

    if tier in (Tier.FREE, Tier.MEDIUM):
        raise HTTPException(
            status_code=501,
            detail=(
                f"Majestic does not support the '{tier.value}' tier. "
                "The Full API plan (Tier.PREMIUM, $399.99/month) is required. "
                "The Lite ($49.99/mo) and Pro ($99.99/mo) plans provide web UI "
                "access only and are not suitable for programmatic research use."
            ),
        )

    return tier


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/collect/terms")
async def collect_by_terms(
    body: CollectTermsRequest,
) -> dict[str, Any]:
    """Collect domain-level metrics (Trust Flow, Citation Flow, RefDomains).

    Each term in ``terms`` is treated as a domain name.  If a term is a full
    URL (e.g. ``"https://dr.dk/nyheder/article123"``), the domain component
    is extracted automatically.

    Returns ``content_type="domain_metrics"`` records.

    Only ``"premium"`` tier is supported.  Requests with ``"free"`` or
    ``"medium"`` tier receive HTTP 501.

    Args:
        body: Request body with ``terms``, ``tier``, and optional
            ``max_results``.

    Returns:
        JSON with ``count`` (int) and ``records`` (list of UCR dicts).

    Raises:
        HTTPException 422: On invalid tier string.
        HTTPException 501: On non-premium tier.
        HTTPException 500: On collection failure.
    """
    tier = _check_premium_tier(body.tier)

    collector = MajesticCollector()
    try:
        records = await collector.collect_by_terms(
            terms=body.terms,
            tier=tier,
            max_results=body.max_results,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("majestic: collect_by_terms error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"count": len(records), "records": records}


@router.post("/collect/actors")
async def collect_by_actors(
    body: CollectActorsRequest,
) -> dict[str, Any]:
    """Collect domain metrics and individual backlinks for actor domains.

    For each domain in ``actor_ids`` the endpoint retrieves:
    1. Domain-level metrics (``content_type="domain_metrics"``).
    2. Up to 1,000 individual backlinks (``content_type="backlink"``,
       one per referring domain).

    The response contains a mixed list of both record types.

    Only ``"premium"`` tier is supported.  Requests with ``"free"`` or
    ``"medium"`` tier receive HTTP 501.

    Args:
        body: Request body with ``actor_ids``, ``tier``, optional date
            filters, and optional ``max_results``.

    Returns:
        JSON with ``count`` (int) and ``records`` (list of UCR dicts).

    Raises:
        HTTPException 422: On invalid tier string.
        HTTPException 501: On non-premium tier.
        HTTPException 500: On collection failure.
    """
    tier = _check_premium_tier(body.tier)

    collector = MajesticCollector()
    try:
        records = await collector.collect_by_actors(
            actor_ids=body.actor_ids,
            tier=tier,
            date_from=body.date_from,
            date_to=body.date_to,
            max_results=body.max_results,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("majestic: collect_by_actors error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"count": len(records), "records": records}


@router.get("/health")
async def health() -> dict[str, Any]:
    """Check Majestic API connectivity.

    Issues ``GetIndexItemInfo`` for ``dr.dk`` and verifies that Trust Flow
    is above zero.  Requires a valid PREMIUM credential in the
    ``CredentialPool`` or the ``MAJESTIC_PREMIUM_API_KEY`` environment
    variable.

    Returns:
        JSON health status dict with keys ``status``, ``arena``,
        ``platform``, ``checked_at``, and optionally ``trust_flow``,
        ``ref_domains``, and ``detail``.
    """
    collector = MajesticCollector()
    return await collector.health_check()
