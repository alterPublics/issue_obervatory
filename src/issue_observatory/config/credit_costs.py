"""Per-platform credit cost rates.

Maps platform_name -> CreditCostRate defining how many records/calls
one credit buys.  Platforms not listed here cost 0 credits (free).

Cost table (admin-defined):
    Bright Data arenas (facebook, instagram, tiktok): 1 record  = 1 credit
    X/Twitter:                                        5 records = 1 credit
    OpenRouter:                                       10 calls  = 1 credit
    Google Search:                                    100 calls = 1 credit
    Everything else:                                  free
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreditCostRate:
    """Defines the credit cost for a platform.

    Attributes:
        platform: Platform name (registry key).
        units_per_credit: Number of records/calls that 1 credit buys.
        label: Human-readable description for the admin UI.
    """

    platform: str
    units_per_credit: int
    label: str


PLATFORM_CREDIT_COSTS: dict[str, CreditCostRate] = {
    # Bright Data arenas: 1 record = 1 credit (most expensive)
    "facebook": CreditCostRate("facebook", 1, "1 record = 1 credit"),
    "instagram": CreditCostRate("instagram", 1, "1 record = 1 credit"),
    "tiktok": CreditCostRate("tiktok", 1, "1 record = 1 credit"),
    # X/Twitter: 5 records = 1 credit
    "x_twitter": CreditCostRate("x_twitter", 5, "5 records = 1 credit"),
    # OpenRouter: 10 calls = 1 credit
    "openrouter": CreditCostRate("openrouter", 10, "10 calls = 1 credit"),
    # Google Search: 100 calls = 1 credit
    "google_search": CreditCostRate("google_search", 100, "100 calls = 1 credit"),
}


def get_credit_cost(platform_name: str) -> CreditCostRate | None:
    """Return the credit cost rate for a platform, or None if free."""
    return PLATFORM_CREDIT_COSTS.get(platform_name)


def credits_for_records(platform_name: str, record_count: int) -> int:
    """Compute credits consumed for a given number of records on a platform.

    Returns 0 for free platforms.  Uses ceiling division so partial
    credits always round up (e.g. 1 record on x_twitter = 1 credit).
    """
    rate = PLATFORM_CREDIT_COSTS.get(platform_name)
    if rate is None or record_count <= 0:
        return 0
    # Ceiling division: -(-a // b)
    return -(-record_count // rate.units_per_credit)
