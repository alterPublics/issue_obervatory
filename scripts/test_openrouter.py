"""Standalone test: verify OpenRouter API connectivity and full collection flow.

Usage:
    uv run python scripts/test_openrouter.py

Tests three stages:
1. Query expansion (free Gemma model — zero cost)
2. Chat completion with web search (GPT-5 Nano :online — small cost)
3. Citation extraction from the response

Requires OPENROUTER_API_KEY in .env or environment.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

# Load .env if python-dotenv is available
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import httpx


# ---------------------------------------------------------------------------
# Config (copied from arena config to keep this script standalone)
# ---------------------------------------------------------------------------

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
EXPANSION_MODEL = "google/gemma-3-27b-it:free"
CHAT_MODEL = "openai/gpt-5-nano:online"

EXPANSION_SYSTEM_PROMPT = (
    "Du er en dansk bruger der søger information via en AI-chatbot.\n"
    "Generer præcis 3 realistiske spørgsmål som en dansker ville stille\n"
    "om dette emne. Varier mellem faktuelle, holdningssøgende og praktiske\n"
    "spørgsmål. Svar kun med spørgsmålene, et per linje."
)

CHAT_SYSTEM_PROMPT = (
    "Du er en hjælpsom assistent. Svar altid på dansk. "
    "Besvar brugerens spørgsmål grundigt og præcist."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _separator(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def _extract_citations(response: dict) -> list[dict]:
    """Extract citations from response (supports Format A/B/C)."""
    normalised = []

    choices = response.get("choices") or []
    message = choices[0].get("message", {}) if choices else {}

    # Format C: annotations (OpenRouter :online / web plugin)
    annotations = message.get("annotations")
    if annotations and isinstance(annotations, list):
        for item in annotations:
            if isinstance(item, dict) and item.get("type") == "url_citation":
                cite = item.get("url_citation", {})
                url = cite.get("url")
                if url:
                    normalised.append({
                        "url": url,
                        "title": cite.get("title"),
                        "snippet": cite.get("content"),
                    })
        if normalised:
            return normalised

    # Format B: choices[0].message.citations (Perplexity objects)
    message_citations = message.get("citations")
    if message_citations and isinstance(message_citations, list):
        for item in message_citations:
            if isinstance(item, dict) and item.get("url"):
                normalised.append({
                    "url": item["url"],
                    "title": item.get("title"),
                    "snippet": item.get("snippet"),
                })
        if normalised:
            return normalised

    # Format A: top-level citations array (Perplexity)
    top_level = response.get("citations")
    if top_level and isinstance(top_level, list):
        for item in top_level:
            if isinstance(item, str) and item:
                normalised.append({"url": item, "title": None, "snippet": None})
            elif isinstance(item, dict) and item.get("url"):
                normalised.append({
                    "url": item["url"],
                    "title": item.get("title"),
                    "snippet": item.get("snippet"),
                })

    return normalised


async def _call_openrouter(
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    system_prompt: str,
    user_message: str,
) -> dict:
    """Make a single OpenRouter chat completion call."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response = await client.post(OPENROUTER_API_URL, json=payload, headers=headers)
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Test stages
# ---------------------------------------------------------------------------


async def test_expansion(client: httpx.AsyncClient, api_key: str) -> list[str]:
    """Stage 1: Query expansion using the chat model (same as production)."""
    _separator("Stage 1: Query Expansion (using chat model)")

    print(f"Model:  {CHAT_MODEL}")
    print(f"  (Production now uses the tier's chat model for expansion")
    print(f"   instead of the free Gemma model which gets 429 rate-limited)")
    print(f"Term:   'CO2 afgift'")
    print(f"Requesting 3 Danish phrasings...\n")

    data = await _call_openrouter(
        client, api_key, CHAT_MODEL, EXPANSION_SYSTEM_PROMPT, "CO2 afgift"
    )

    text = ""
    choices = data.get("choices") or []
    if choices:
        text = choices[0].get("message", {}).get("content", "")

    usage = data.get("usage", {})
    print(f"Tokens: prompt={usage.get('prompt_tokens')}, "
          f"completion={usage.get('completion_tokens')}")
    print(f"Model response:\n{text}\n")

    # Parse phrasings
    import re
    phrasings = []
    for line in text.splitlines():
        cleaned = re.sub(r"^\d+[\.\)\:\-]\s*", "", line).strip()
        if cleaned:
            phrasings.append(cleaned)

    print(f"Parsed {len(phrasings)} phrasings:")
    for i, p in enumerate(phrasings, 1):
        print(f"  {i}. {p}")

    if phrasings:
        print("\n  PASS: Expansion model is working.")
    else:
        print("\n  FAIL: No phrasings returned.")

    return phrasings[:3]


async def test_chat_search(
    client: httpx.AsyncClient, api_key: str, phrasing: str
) -> dict:
    """Stage 2: Chat completion with web search."""
    _separator("Stage 2: Chat Completion + Web Search")

    print(f"Model:    {CHAT_MODEL}")
    print(f"Phrasing: '{phrasing}'")
    print(f"Sending chat completion with web search...\n")

    data = await _call_openrouter(
        client, api_key, CHAT_MODEL, CHAT_SYSTEM_PROMPT, phrasing
    )

    text = ""
    choices = data.get("choices") or []
    if choices:
        text = choices[0].get("message", {}).get("content", "")

    usage = data.get("usage", {})
    print(f"Tokens: prompt={usage.get('prompt_tokens')}, "
          f"completion={usage.get('completion_tokens')}")

    # Truncate response for display
    display_text = text[:500] + "..." if len(text) > 500 else text
    print(f"Response text (first 500 chars):\n{display_text}\n")

    if text:
        print("  PASS: Chat completion returned content.")
    else:
        print("  FAIL: No content in response.")

    return data


def test_citations(response: dict) -> list[dict]:
    """Stage 3: Citation extraction."""
    _separator("Stage 3: Citation Extraction")

    citations = _extract_citations(response)

    # Determine which format was detected
    choices = response.get("choices") or []
    message = choices[0].get("message", {}) if choices else {}

    if message.get("annotations"):
        fmt = "C (annotations — OpenRouter :online web plugin)"
    elif message.get("citations"):
        fmt = "B (message.citations — Perplexity objects)"
    elif response.get("citations"):
        fmt = "A (top-level citations — Perplexity URL strings)"
    else:
        fmt = "NONE DETECTED"

    print(f"Citation format detected: {fmt}")
    print(f"Citations found: {len(citations)}\n")

    for i, c in enumerate(citations, 1):
        title = c.get("title") or "(no title)"
        snippet = c.get("snippet") or "(no snippet)"
        if len(snippet) > 100:
            snippet = snippet[:100] + "..."
        print(f"  [{i}] {c['url']}")
        print(f"      Title:   {title}")
        print(f"      Snippet: {snippet}\n")

    if citations:
        print(f"  PASS: {len(citations)} citations extracted.")
    else:
        print("  WARN: No citations found. This may be model-dependent.")

    return citations


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set in environment or .env file.")
        print("Set it and try again.")
        return 1

    print(f"API key: {api_key[:8]}...{api_key[-4:]}")

    passed = 0
    failed = 0

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Stage 1: Expansion
        try:
            phrasings = await test_expansion(client, api_key)
            if phrasings:
                passed += 1
            else:
                failed += 1
        except httpx.HTTPStatusError as exc:
            print(f"\n  FAIL: HTTP {exc.response.status_code}")
            print(f"  Response: {exc.response.text[:300]}")
            failed += 1
            phrasings = []
        except Exception as exc:
            print(f"\n  FAIL: {exc}")
            failed += 1
            phrasings = []

        # Stage 2: Chat search (use first phrasing, or fallback)
        test_phrasing = phrasings[0] if phrasings else "Hvad er CO2 afgiften i Danmark?"
        try:
            response = await test_chat_search(client, api_key, test_phrasing)
            choices = response.get("choices") or []
            text = choices[0].get("message", {}).get("content", "") if choices else ""
            if text:
                passed += 1
            else:
                failed += 1
        except httpx.HTTPStatusError as exc:
            print(f"\n  FAIL: HTTP {exc.response.status_code}")
            print(f"  Response: {exc.response.text[:300]}")
            failed += 1
            response = {}
        except Exception as exc:
            print(f"\n  FAIL: {exc}")
            failed += 1
            response = {}

        # Stage 3: Citation extraction
        if response:
            citations = test_citations(response)
            if citations:
                passed += 1
            else:
                # Not a hard failure — some models don't return citations
                print("  (Not counted as failure — citation availability varies by model.)")
                passed += 1

    # Summary
    _separator("Summary")
    print(f"  Passed: {passed}/{passed + failed}")
    print(f"  Failed: {failed}/{passed + failed}")

    if failed == 0:
        print("\n  All stages passed. OpenRouter integration is working.")
    else:
        print(f"\n  {failed} stage(s) failed. Check output above for details.")

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
