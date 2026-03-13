"""Diagnose why the AI Chat Search (OpenRouter) collector returns 0 records.

Simulates the production Celery task flow step by step:
1. Credential pool acquisition (platform="openrouter")
2. Query expansion (term → phrasings)
3. Chat completion with web search
4. Citation extraction
5. Record creation + normalization
6. Full collector flow (without batch persistence)

Run with:
    uv run python scripts/diagnose_openrouter.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("diagnose_openrouter")

# Silence noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("hpack").setLevel(logging.WARNING)


def separator(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")


async def step1_check_credentials() -> dict | None:
    """Check if OpenRouter credentials exist."""
    separator("Step 1: Credential Check")

    # Check env var
    env_key = os.environ.get("OPENROUTER_API_KEY", "")
    if env_key:
        print(f"  ENV: OPENROUTER_API_KEY = {env_key[:12]}...{env_key[-4:]}")
    else:
        print("  ENV: OPENROUTER_API_KEY = NOT SET")

    # Check DB credential pool
    try:
        from issue_observatory.core.credential_pool import CredentialPool

        pool = CredentialPool()
        cred = await pool.acquire(platform="openrouter", tier="medium")
        if cred is None:
            print("  DB POOL: No credential for platform='openrouter', tier='medium'")
            if env_key:
                print("  >>> Will fall back to env var (this is the normal path)")
                return {"api_key": env_key, "id": "env"}
            else:
                print("  >>> NO CREDENTIAL AVAILABLE — this will cause NoCredentialAvailableError")

                # List all credentials
                try:
                    from issue_observatory.core.database import get_sync_session
                    from sqlalchemy import text

                    with get_sync_session() as session:
                        result = session.execute(
                            text(
                                "SELECT id, platform, tier, is_active "
                                "FROM credentials WHERE platform LIKE '%openrouter%' OR platform LIKE '%open_router%' "
                                "ORDER BY created_at DESC LIMIT 10"
                            )
                        )
                        rows = result.fetchall()
                        if rows:
                            print(f"\n  Related credentials in DB:")
                            for row in rows:
                                print(f"    - id={row[0]}, platform={row[1]}, tier={row[2]}, active={row[3]}")
                        else:
                            print("\n  No 'openrouter' credentials in DB at all.")
                except Exception as exc:
                    print(f"  Could not query DB: {exc}")
                return None
        else:
            api_key = cred.get("api_key", "")
            cred_id = cred.get("id", "unknown")
            print(f"  DB POOL: Got credential id={cred_id}")
            print(f"  DB POOL: api_key = {api_key[:12]}...{api_key[-4:]}" if api_key else "  DB POOL: api_key = EMPTY")
            await pool.release(credential_id=cred_id)
            return cred
    except Exception as exc:
        print(f"  ERROR: {type(exc).__name__}: {exc}")
        if env_key:
            print("  >>> Falling back to env var")
            return {"api_key": env_key, "id": "env"}
        return None


async def step2_test_expansion(api_key: str) -> list[str]:
    """Test query expansion (term → phrasings)."""
    separator("Step 2: Query Expansion")

    import httpx

    from issue_observatory.arenas.ai_chat_search import _query_expander
    from issue_observatory.arenas.ai_chat_search.config import get_chat_model

    test_term = "CO2 afgift"
    n_phrasings = 3

    from issue_observatory.arenas.base import Tier

    model = get_chat_model(Tier.MEDIUM)
    print(f"  Term: '{test_term}'")
    print(f"  Model: {model} (using tier's chat model for expansion)")
    print(f"  Requesting {n_phrasings} phrasings...")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            phrasings = await _query_expander.expand_term(
                client=client,
                term=test_term,
                n_phrasings=n_phrasings,
                api_key=api_key,
                rate_limiter=None,
                model_override=model,
            )

        print(f"\n  Expansion returned {len(phrasings)} phrasings:")
        for i, p in enumerate(phrasings, 1):
            print(f"    {i}. {p}")

        if not phrasings:
            print("  >>> EXPANSION RETURNED EMPTY — this causes 0 records!")
            print("  >>> The collector logs a warning and skips the term entirely.")

        return phrasings

    except Exception as exc:
        print(f"  >>> EXPANSION ERROR: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return []


async def step3_test_chat_completion(api_key: str, phrasing: str) -> dict:
    """Test chat completion with web search."""
    separator("Step 3: Chat Completion + Web Search")

    import httpx

    from issue_observatory.arenas.ai_chat_search import _openrouter
    from issue_observatory.arenas.ai_chat_search.config import (
        CHAT_SYSTEM_PROMPT,
        get_chat_model,
    )
    from issue_observatory.arenas.base import Tier

    model = get_chat_model(Tier.MEDIUM)
    print(f"  Model: {model}")
    print(f"  Phrasing: '{phrasing}'")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await _openrouter.chat_completion(
                client=client,
                model=model,
                system_prompt=CHAT_SYSTEM_PROMPT,
                user_message=phrasing,
                api_key=api_key,
                rate_limiter=None,
            )

        # Check response structure
        choices = response.get("choices") or []
        print(f"  Response has {len(choices)} choices")

        if choices:
            message = choices[0].get("message", {})
            content = message.get("content", "")
            print(f"  Content length: {len(content)} chars")
            if content:
                print(f"  Content preview: {content[:200]}...")
            else:
                print("  >>> CONTENT IS EMPTY — response record will have no text!")

            # Check for annotations/citations in the raw message
            annotations = message.get("annotations")
            msg_citations = message.get("citations")
            print(f"  message.annotations: {type(annotations).__name__} ({len(annotations) if annotations else 0} items)" if annotations else "  message.annotations: None")
            print(f"  message.citations: {type(msg_citations).__name__} ({len(msg_citations) if msg_citations else 0} items)" if msg_citations else "  message.citations: None")
        else:
            print("  >>> NO CHOICES in response — record creation will produce empty content!")

        # Check top-level citations
        top_citations = response.get("citations")
        print(f"  top-level citations: {type(top_citations).__name__} ({len(top_citations) if top_citations else 0} items)" if top_citations else "  top-level citations: None")

        usage = response.get("usage", {})
        print(f"  Tokens: prompt={usage.get('prompt_tokens')}, completion={usage.get('completion_tokens')}")

        return response

    except Exception as exc:
        print(f"  >>> CHAT ERROR: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return {}


def step4_test_citation_extraction(response: dict) -> list[dict]:
    """Test citation extraction from the response."""
    separator("Step 4: Citation Extraction")

    if not response:
        print("  SKIP — no response to extract from")
        return []

    from issue_observatory.arenas.ai_chat_search import _openrouter

    citations = _openrouter.extract_citations(response)
    print(f"  Extracted {len(citations)} citations:")
    for i, c in enumerate(citations, 1):
        print(f"    [{i}] {c.get('url', 'no url')[:80]}")
        print(f"        title: {c.get('title', 'N/A')}")

    if not citations:
        print("  >>> NO CITATIONS — this means only response records (no citation records)")
        print("  >>> This is model-dependent and may be normal for some models.")

    return citations


def step5_test_record_creation(phrasing: str, response: dict, citations: list[dict]) -> list[dict]:
    """Test record creation (response + citation records)."""
    separator("Step 5: Record Creation")

    if not response:
        print("  SKIP — no response data")
        return []

    from issue_observatory.arenas.ai_chat_search._records import (
        make_citation_record,
        make_response_record,
    )
    from issue_observatory.arenas.ai_chat_search.config import get_chat_model
    from issue_observatory.arenas.base import Tier

    model = get_chat_model(Tier.MEDIUM)
    records = []

    try:
        response_record = make_response_record(
            phrasing=phrasing,
            original_term="CO2 afgift",
            response=response,
            model_used=model,
            citations=citations,
            day_bucket="2026-03-06",
            arena_name="ai_chat_search",
            platform_name="openrouter",
        )
        records.append(response_record)
        print(f"  Response record: content_type={response_record.get('content_type')}")
        print(f"    url: {response_record.get('url', 'N/A')[:60]}")
        print(f"    text_content length: {len(response_record.get('text_content') or '')}")
        print(f"    content_hash: {response_record.get('content_hash', 'N/A')[:20]}...")
    except Exception as exc:
        print(f"  >>> RESPONSE RECORD ERROR: {type(exc).__name__}: {exc}")

    if citations:
        try:
            citation_records = []
            for rank, cite in enumerate(citations, 1):
                cr = make_citation_record(
                    citation=cite,
                    phrasing=phrasing,
                    original_term="CO2 afgift",
                    model_used=model,
                    rank=rank,
                    parent_platform_id=response_record.get("platform_id", ""),
                    day_bucket="2026-03-06",
                    arena_name="ai_chat_search",
                )
                citation_records.append(cr)
            records.extend(citation_records)
            print(f"  Citation records: {len(citation_records)}")
            for i, cr in enumerate(citation_records[:3], 1):
                url = cr.get("url") or "N/A"
                print(f"    [{i}] {url[:60]} — type={cr.get('content_type')}")
        except Exception as exc:
            print(f"  >>> CITATION RECORDS ERROR: {type(exc).__name__}: {exc}")

    print(f"\n  Total records created: {len(records)}")
    return records


async def step6_full_collector_test(api_key: str) -> None:
    """Test the full collector flow (without batch persistence)."""
    separator("Step 6: Full Collector Flow (no batch persistence)")

    try:
        from issue_observatory.arenas.ai_chat_search.collector import AiChatSearchCollector
        from issue_observatory.arenas.base import Tier

        # Create collector without credential pool — use direct env key
        collector = AiChatSearchCollector(
            credential_pool=None,
            rate_limiter=None,
        )

        print(f"  Terms: ['CO2 afgift']")
        print(f"  Tier: MEDIUM")
        print(f"  max_results: 10")
        print(f"  No batch persistence configured (raw return value test)")
        print()

        # Set the env var so the collector can find it
        os.environ["OPENROUTER_API_KEY"] = api_key

        records = await collector.collect_by_terms(
            terms=["CO2 afgift"],
            tier=Tier.MEDIUM,
            max_results=10,
        )

        print(f"\n  Collector returned {len(records)} records")
        print(f"  Batch stats: {collector.batch_stats}")

        for i, rec in enumerate(records[:5]):
            ct = rec.get("content_type", "?")
            url = rec.get("url", "N/A")[:60]
            print(f"    [{i+1}] type={ct}, url={url}")

        if not records:
            print("  >>> COLLECTOR RETURNED 0 RECORDS")
            print("  >>> Check the DEBUG logs above for warnings about:")
            print("  >>>   - 'expansion failed for term'")
            print("  >>>   - 'no phrasings generated'")
            print("  >>>   - 'chat search failed for phrasing'")

    except Exception as exc:
        print(f"  >>> COLLECTOR ERROR: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()


async def main() -> None:
    separator("AI Chat Search (OpenRouter) Arena Diagnostic")
    print("  This script simulates the production Celery task flow step by step.\n")

    # Step 1: Credentials
    cred = await step1_check_credentials()
    if not cred:
        separator("DIAGNOSTIC COMPLETE — BLOCKED")
        print("  Cannot proceed without an API key.")
        print("  Set OPENROUTER_API_KEY in .env or add a credential to the DB pool.")
        return

    api_key = cred.get("api_key", "")
    if not api_key:
        print("  >>> Credential exists but api_key is empty!")
        return

    # Step 2: Query expansion
    phrasings = await step2_test_expansion(api_key)

    # Step 3: Chat completion
    test_phrasing = phrasings[0] if phrasings else "Hvad er CO2 afgiften i Danmark?"
    response = await step3_test_chat_completion(api_key, test_phrasing)

    # Step 4: Citation extraction
    citations = step4_test_citation_extraction(response)

    # Step 5: Record creation
    records = step5_test_record_creation(test_phrasing, response, citations)

    # Step 6: Full collector test
    await step6_full_collector_test(api_key)

    separator("Diagnostic Summary")
    issues = []
    if not phrasings:
        issues.append("EXPANSION FAILED: Query expansion returned 0 phrasings — all terms are skipped")
    if not response:
        issues.append("CHAT FAILED: Chat completion returned no response")
    elif not response.get("choices"):
        issues.append("EMPTY RESPONSE: Chat completion returned no choices")
    if not records:
        issues.append("NO RECORDS: Record creation produced 0 records")

    if issues:
        print("  LIKELY ROOT CAUSES:")
        for i, issue in enumerate(issues, 1):
            print(f"    {i}. {issue}")
    else:
        print("  All steps produced valid output. If production still returns 0 records,")
        print("  the issue is likely in:")
        print("    - Credential pool acquisition (DB-based, not env var)")
        print("    - Batch persistence sink losing records (check batch_stats)")
        print("    - Term groups (boolean query) producing empty effective_terms")
        print("    - The coverage checker skipping the collection run")


if __name__ == "__main__":
    asyncio.run(main())
