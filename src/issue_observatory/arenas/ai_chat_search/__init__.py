"""AI Chat Search arena package.

Captures the AI-mediated information environment by collecting synthesized
answers and cited sources from web-search-enabled large language models via
OpenRouter.  Collection runs in two phases:

1. **Query expansion** — a cheap free LLM generates N realistic Danish
   phrasings from each search term.
2. **AI chat search** — each phrasing is submitted to a Perplexity Sonar
   model (via OpenRouter) which performs a live web search and returns a
   synthesized Danish response plus structured citations.

Two content record types are produced per query:

- ``ai_chat_response`` — the full synthesized answer (one per phrasing).
- ``ai_chat_citation`` — each cited URL (one per citation per phrasing).

See also:
    - Research brief: ``docs/arenas/ai_chat_search.md``
    - Collector: :class:`~issue_observatory.arenas.ai_chat_search.collector.AiChatSearchCollector`
    - Config: :mod:`~issue_observatory.arenas.ai_chat_search.config`
"""

from __future__ import annotations
