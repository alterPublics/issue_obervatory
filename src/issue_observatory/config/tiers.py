"""Arena tier definitions and per-tier configuration.

Defines the three operational tiers (FREE, MEDIUM, PREMIUM) used across all
arena collectors.  Every arena must support at least one tier and must gracefully
skip collection (returning an empty list with a warning log) when the requested
tier is not available for that arena.

The credit costs defined here (``estimated_credits_per_1k``) map directly to
real monetary cost units and are used by :mod:`issue_observatory.core.credit_service`
to compute pre-flight estimates before a collection run is launched.

Credit mapping examples:
  - FREE arenas:          0 credits  (no API cost)
  - YouTube Data API v3:  1 credit   = 1 API unit  (search = 100 credits)
  - Serper.dev SERP:      1 credit   = 1 SERP query
  - TwitterAPI.io:        1 credit   = 1 tweet retrieved
  - TikTok Research API:  1 credit   = 1 API request
"""

from __future__ import annotations

from dataclasses import dataclass

from issue_observatory.arenas.base import Tier


@dataclass(frozen=True)
class TierConfig:
    """Configuration parameters for a single tier within an arena.

    Attributes:
        tier: The :class:`Tier` this configuration applies to.
        max_results_per_run: Hard upper bound on results returned per collection run.
            Arenas must honour this limit even if the upstream API would return more.
        rate_limit_per_minute: Target request rate the shared
            :class:`issue_observatory.workers.rate_limiter.RateLimiter` enforces
            for this tier.  Individual arenas may apply tighter limits via their own
            config if the upstream provider requires it.
        requires_credential: Whether this tier needs an API key / session credential
            acquired from the credential pool before collecting.
        estimated_credits_per_1k: Approximate credit cost per 1,000 collected items.
            Used exclusively for pre-flight budget estimation — actual settlement is
            recorded in ``credit_transactions`` after the run completes.
    """

    tier: Tier
    max_results_per_run: int
    rate_limit_per_minute: int
    requires_credential: bool
    estimated_credits_per_1k: int


TIER_DEFAULTS: dict[Tier, TierConfig] = {
    Tier.FREE: TierConfig(
        tier=Tier.FREE,
        max_results_per_run=10_000,
        rate_limit_per_minute=60,
        requires_credential=False,
        estimated_credits_per_1k=0,
    ),
    Tier.MEDIUM: TierConfig(
        tier=Tier.MEDIUM,
        max_results_per_run=100_000,
        rate_limit_per_minute=300,
        requires_credential=True,
        estimated_credits_per_1k=1,
    ),
    Tier.PREMIUM: TierConfig(
        tier=Tier.PREMIUM,
        max_results_per_run=1_000_000,
        rate_limit_per_minute=1000,
        requires_credential=True,
        estimated_credits_per_1k=5,
    ),
}
"""Default tier configurations applied when an arena does not override them.

Individual arenas may return a customised :class:`TierConfig` from their
``get_tier_config()`` method to reflect provider-specific limits (e.g. YouTube
Data API v3 has a 10,000-unit daily cap per GCP project key that differs from
the generic FREE defaults).

These defaults serve as the fallback and as the source of truth for the
pre-flight cost estimation UI.
"""
