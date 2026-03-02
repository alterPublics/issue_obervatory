"""Configuration for the AI Chat Search arena.

Defines OpenRouter API constants, model identifiers, prompt templates,
timeout values, and per-tier settings used by
:class:`~issue_observatory.arenas.ai_chat_search.collector.AiChatSearchCollector`.

Key design decisions:
- Both MEDIUM and PREMIUM tiers use the same OpenRouter API endpoint and
  the same credential (``platform="openrouter"``).  Tier selection controls
  which Perplexity Sonar model is called.
- Query expansion always uses ``google/gemma-3-27b-it:free`` regardless of
  tier — it has zero token cost on OpenRouter.
- FREE tier is explicitly unsupported.  The collector returns ``[]`` with a
  warning log when ``tier=Tier.FREE`` is requested.
- Temperature is always ``0`` for maximum reproducibility.

See research brief: ``docs/arenas/ai_chat_search.md``.
"""

from __future__ import annotations

from issue_observatory.config.tiers import Tier, TierConfig

# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------

OPENROUTER_API_URL: str = "https://openrouter.ai/api/v1/chat/completions"
"""OpenRouter chat completions endpoint (OpenAI-compatible)."""

# ---------------------------------------------------------------------------
# Model identifiers
# ---------------------------------------------------------------------------

CHAT_MODEL_MEDIUM: str = "openai/gpt-5-nano:online"
"""Default model for the MEDIUM tier — GPT-5 Nano with OpenRouter web search.

The ``:online`` suffix activates OpenRouter's web search plugin, which
incorporates real-time search results into the response and returns citations
as ``annotations`` objects in the message.

Cost: pay-per-token via OpenRouter; GPT-5 Nano is among the cheapest options.
"""

CHAT_MODEL_PREMIUM: str = "openai/gpt-5-nano:online"
"""Default model for the PREMIUM tier — GPT-5 Nano with OpenRouter web search.

Same model as MEDIUM; PREMIUM tier generates more phrasings per term
for broader coverage.
"""

EXPANSION_MODEL: str = "google/gemma-3-27b-it:free"
"""Free LLM used to expand search terms into realistic Danish phrasings.

Zero token cost on OpenRouter.  Rate limits are lower (~20 req/min) but
sufficient for the expansion step (N phrasings per search term).
"""

# ---------------------------------------------------------------------------
# Tier parameters
# ---------------------------------------------------------------------------

PHRASINGS_PER_TERM_MEDIUM: int = 5
"""Number of query phrasings generated per search term at MEDIUM tier."""

PHRASINGS_PER_TERM_PREMIUM: int = 10
"""Number of query phrasings generated per search term at PREMIUM tier."""

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

CHAT_SYSTEM_PROMPT: str = (
    "Du er en hjælpsom assistent. Svar altid på dansk. "
    "Besvar brugerens spørgsmål grundigt og præcist."
)
"""System prompt for the Perplexity Sonar chat search calls.

Enforces Danish-language responses regardless of the language of cited
source material.  This is the primary Danish localisation mechanism for
this arena (no ``lang=da`` parameter exists for Perplexity's web search).
"""

EXPANSION_SYSTEM_PROMPT_TEMPLATE: str = (
    "Du er en dansk bruger der søger information via en AI-chatbot.\n"
    "Generer præcis {N} realistiske spørgsmål som en dansker ville stille\n"
    "om dette emne. Varier mellem faktuelle, holdningssøgende og praktiske\n"
    "spørgsmål. Svar kun med spørgsmålene, et per linje."
)
"""System prompt template for the query expansion calls.

``{N}`` is replaced at runtime with the number of phrasings to generate.
Instructs the model to output exactly N Danish questions — one per line —
without any preamble or numbering.
"""

# ---------------------------------------------------------------------------
# HTTP timeouts (seconds)
# ---------------------------------------------------------------------------

EXPANSION_TIMEOUT_SECONDS: float = 30.0
"""HTTP timeout for query expansion calls (fast free model)."""

CHAT_TIMEOUT_SECONDS: float = 60.0
"""HTTP timeout for Perplexity Sonar chat search calls.

Perplexity performs a live web search per request, which can take 3–15
seconds.  The 60-second timeout provides sufficient headroom for Sonar Pro
on complex queries.
"""

HEALTH_CHECK_TIMEOUT_SECONDS: float = 15.0
"""HTTP timeout for health-check calls (expansion model only)."""

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

OPENROUTER_RATE_LIMITER_KEY: str = "openrouter"
"""Provider key used with the shared Redis-backed RateLimiter."""

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

AI_CHAT_SEARCH_TIERS: dict[Tier, TierConfig] = {
    Tier.MEDIUM: TierConfig(
        tier=Tier.MEDIUM,
        max_results_per_run=500,     # 10 terms * 5 phrasings * (1 response + ~5 citations)
        rate_limit_per_minute=50,    # Conservative: 50 phrasings/run, mostly sequential
        requires_credential=True,
        estimated_credits_per_1k=1,  # Token-based; nominal 1 credit per request
    ),
    Tier.PREMIUM: TierConfig(
        tier=Tier.PREMIUM,
        max_results_per_run=1_000,   # 10 terms * 10 phrasings * (1 response + ~5 citations)
        rate_limit_per_minute=100,   # Wider budget for Sonar Pro
        requires_credential=True,
        estimated_credits_per_1k=5,  # Higher per-token cost for Sonar Pro
    ),
}
"""Tier definitions for the AI Chat Search arena.

- ``MEDIUM``: ``perplexity/sonar`` via OpenRouter, 5 phrasings/term.
  ~$5–15/month at 10 terms/day.
- ``PREMIUM``: ``perplexity/sonar-pro`` via OpenRouter, 10 phrasings/term.
  ~$15–45/month at 10 terms/day.

FREE tier is not supported.  Credentials use ``platform="openrouter"``
in the CredentialPool; a single key covers both tiers.
"""


def get_chat_model(tier: Tier) -> str:
    """Return the OpenRouter model identifier for the given collection tier.

    Args:
        tier: Operational tier (``MEDIUM`` or ``PREMIUM``).

    Returns:
        OpenRouter model ID string.

    Raises:
        ValueError: If *tier* is ``FREE`` or unrecognised.
    """
    if tier == Tier.MEDIUM:
        return CHAT_MODEL_MEDIUM
    if tier == Tier.PREMIUM:
        return CHAT_MODEL_PREMIUM
    raise ValueError(
        f"AI Chat Search does not support tier '{tier.value}'. "
        "Supported tiers: medium, premium."
    )


def get_n_phrasings(tier: Tier) -> int:
    """Return the number of query phrasings to generate per search term.

    Args:
        tier: Operational tier (``MEDIUM`` or ``PREMIUM``).

    Returns:
        Integer count of phrasings to generate.

    Raises:
        ValueError: If *tier* is ``FREE`` or unrecognised.
    """
    if tier == Tier.MEDIUM:
        return PHRASINGS_PER_TERM_MEDIUM
    if tier == Tier.PREMIUM:
        return PHRASINGS_PER_TERM_PREMIUM
    raise ValueError(
        f"AI Chat Search does not support tier '{tier.value}'. "
        "Supported tiers: medium, premium."
    )
