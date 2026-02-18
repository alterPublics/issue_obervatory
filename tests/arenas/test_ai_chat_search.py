"""Tests for the AI Chat Search arena.

Covers:
- _openrouter.extract_citations(): Format A (top-level URL strings), Format B
  (per-message objects with url/title/snippet), priority of Format B over A,
  empty/missing citations.
- _openrouter.chat_completion(): HTTP error mapping (429, 401, 403, 500, 200).
- _query_expander.expand_term(): numbered-list prefix stripping, empty-line
  filtering, n_phrasings cap, successful parse.
- _records.make_response_record(): all required fields, platform_id and
  content_hash are 64-char hex, raw_metadata structure, Danish character
  preservation.
- _records.make_citation_record(): all required fields, domain extraction,
  snippet in text_content for Format B, None when absent (Format A).
- AiChatSearchCollector: tier behaviour (FREE returns [], MEDIUM/PREMIUM in
  supported_tiers), collect_by_actors() raises NotImplementedError,
  get_tier_config() returns TierConfig with requires_credential=True.
- collect_by_terms() integration: MEDIUM with Format A, PREMIUM with Format B,
  HTTP 429 propagation, HTTP 401 propagation, all-blank phrasings, empty
  citations list.
- health_check(): success, HTTP error, no credential.

These tests run without a live database or network connection.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

# ---------------------------------------------------------------------------
# Environment bootstrap — must precede all application imports
# ---------------------------------------------------------------------------

os.environ.setdefault("PSEUDONYMIZATION_SALT", "test-pseudonymization-salt-for-unit-tests")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault(
    "CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLXBhZGRlZA=="
)

from issue_observatory.arenas.ai_chat_search import _openrouter, _query_expander  # noqa: E402
from issue_observatory.arenas.ai_chat_search._records import (  # noqa: E402
    make_citation_record,
    make_response_record,
)
from issue_observatory.arenas.ai_chat_search.collector import AiChatSearchCollector  # noqa: E402
from issue_observatory.arenas.ai_chat_search.config import OPENROUTER_API_URL  # noqa: E402
from issue_observatory.arenas.base import Tier  # noqa: E402
from issue_observatory.core.exceptions import (  # noqa: E402
    ArenaAuthError,
    ArenaCollectionError,
    ArenaRateLimitError,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = (
    Path(__file__).parent.parent / "fixtures" / "api_responses" / "ai_chat_search"
)


def _load_fixture(filename: str) -> dict[str, Any]:
    """Load a JSON fixture file from the ai_chat_search fixture directory."""
    return json.loads((FIXTURES_DIR / filename).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Shared fixture data loaders
# ---------------------------------------------------------------------------


def _format_a_response() -> dict[str, Any]:
    """Return the Format A (top-level citations as URL strings) fixture."""
    return _load_fixture("openrouter_chat_response_format_a.json")


def _format_b_response() -> dict[str, Any]:
    """Return the Format B (per-message citation objects) fixture."""
    return _load_fixture("openrouter_chat_response_format_b.json")


def _expand_response() -> dict[str, Any]:
    """Return the query-expansion model response fixture."""
    return _load_fixture("openrouter_expand_response.json")


# ---------------------------------------------------------------------------
# Shared mock credential pool
# ---------------------------------------------------------------------------


def _make_mock_pool() -> Any:
    """Build a minimal mock CredentialPool returning an OpenRouter credential."""
    pool = MagicMock()
    pool.acquire = AsyncMock(
        return_value={"id": "cred-or-001", "api_key": "test-openrouter-key"}
    )
    pool.release = AsyncMock(return_value=None)
    pool.report_error = AsyncMock(return_value=None)
    return pool


# ---------------------------------------------------------------------------
# Constants used across tests
# ---------------------------------------------------------------------------

_TEST_PHRASING = "Hvad er CO2 afgiften i Danmark?"
_TEST_TERM = "CO2 afgift"
_TEST_MODEL = "perplexity/sonar"
_TEST_DAY_BUCKET = "2026-02-17"
_TEST_PARENT_ID = "a" * 64


# ===========================================================================
# Tests: _openrouter.extract_citations()
# ===========================================================================


class TestExtractCitations:
    def test_extract_citations_format_a_returns_url_string_list(self) -> None:
        """Format A: top-level citations list of URL strings is normalised correctly."""
        response = _format_a_response()
        result = _openrouter.extract_citations(response)

        assert isinstance(result, list)
        assert len(result) == 5
        assert result[0]["url"] == "https://www.dr.dk/nyheder/seneste/co2-afgift-denmark-climate"
        assert result[0]["title"] is None
        assert result[0]["snippet"] is None

    def test_extract_citations_format_a_all_entries_normalised(self) -> None:
        """Format A: every entry in the top-level list has url, title=None, snippet=None."""
        response = _format_a_response()
        result = _openrouter.extract_citations(response)

        for entry in result:
            assert "url" in entry
            assert "title" in entry
            assert "snippet" in entry
            assert entry["title"] is None
            assert entry["snippet"] is None

    def test_extract_citations_format_b_returns_objects_with_snippet(self) -> None:
        """Format B: choices[0].message.citations objects are returned with title and snippet."""
        response = _format_b_response()
        result = _openrouter.extract_citations(response)

        assert len(result) == 3
        assert result[0]["url"] == "https://www.dr.dk/nyheder/seneste/groenland-klimaforandringer-issmeltning"
        assert result[0]["title"] == "Grønlands indlandsis smelter hurtigere end frygtet"
        assert result[0]["snippet"] is not None
        assert "indlandsis" in result[0]["snippet"]

    def test_extract_citations_format_b_takes_priority_over_format_a(self) -> None:
        """When both top-level citations and choices[0].message.citations exist, Format B wins."""
        response = {
            **_format_b_response(),
            "citations": [
                "https://should-be-ignored.dk/article",
                "https://also-ignored.dk/article",
            ],
        }
        result = _openrouter.extract_citations(response)

        # Format B has 3 entries; the top-level list has 2 — we expect Format B
        assert len(result) == 3
        assert result[0]["title"] is not None  # Format B entries have titles

    def test_extract_citations_empty_citations_key_returns_empty_list(self) -> None:
        """An empty top-level citations list produces an empty result."""
        response = {"citations": [], "choices": []}
        result = _openrouter.extract_citations(response)

        assert result == []

    def test_extract_citations_missing_citations_key_returns_empty_list(self) -> None:
        """A response with no citations key at all returns an empty list."""
        response = {
            "id": "gen-123",
            "choices": [{"message": {"role": "assistant", "content": "Svar."}}],
        }
        result = _openrouter.extract_citations(response)

        assert result == []

    def test_extract_citations_format_b_missing_url_skipped(self) -> None:
        """Format B entries without a 'url' key are silently skipped."""
        response = {
            "choices": [
                {
                    "message": {
                        "citations": [
                            {"title": "No URL here", "snippet": "Snippet"},
                            {"url": "https://valid.dk/", "title": "Valid", "snippet": "OK"},
                        ]
                    }
                }
            ]
        }
        result = _openrouter.extract_citations(response)

        assert len(result) == 1
        assert result[0]["url"] == "https://valid.dk/"

    def test_extract_citations_format_a_empty_string_skipped(self) -> None:
        """Format A: empty string entries in the top-level list are silently skipped."""
        response = {
            "citations": ["https://dr.dk/article", "", "https://berlingske.dk/article"],
            "choices": [],
        }
        result = _openrouter.extract_citations(response)

        assert len(result) == 2


# ===========================================================================
# Tests: _openrouter.chat_completion() — HTTP error mapping
# ===========================================================================


class TestChatCompletion:
    @pytest.mark.asyncio
    async def test_chat_completion_200_returns_parsed_json(self) -> None:
        """A successful HTTP 200 response returns the parsed JSON dict."""
        fixture = _format_a_response()

        with respx.mock:
            respx.post(OPENROUTER_API_URL).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            async with httpx.AsyncClient() as client:
                result = await _openrouter.chat_completion(
                    client=client,
                    model=_TEST_MODEL,
                    system_prompt="Svar på dansk.",
                    user_message=_TEST_PHRASING,
                    api_key="test-key",
                )

        assert result["model"] == "perplexity/sonar"
        assert "choices" in result

    @pytest.mark.asyncio
    async def test_chat_completion_429_raises_rate_limit_error(self) -> None:
        """HTTP 429 response raises ArenaRateLimitError."""
        with respx.mock:
            respx.post(OPENROUTER_API_URL).mock(
                return_value=httpx.Response(
                    429, headers={"Retry-After": "30"}, json={"error": "rate limited"}
                )
            )
            async with httpx.AsyncClient() as client:
                with pytest.raises(ArenaRateLimitError) as exc_info:
                    await _openrouter.chat_completion(
                        client=client,
                        model=_TEST_MODEL,
                        system_prompt="Svar på dansk.",
                        user_message=_TEST_PHRASING,
                        api_key="test-key",
                    )

        assert exc_info.value.retry_after == 30.0

    @pytest.mark.asyncio
    async def test_chat_completion_401_raises_auth_error(self) -> None:
        """HTTP 401 response raises ArenaAuthError."""
        with respx.mock:
            respx.post(OPENROUTER_API_URL).mock(
                return_value=httpx.Response(401, json={"error": "Unauthorized"})
            )
            async with httpx.AsyncClient() as client:
                with pytest.raises(ArenaAuthError):
                    await _openrouter.chat_completion(
                        client=client,
                        model=_TEST_MODEL,
                        system_prompt="Svar på dansk.",
                        user_message=_TEST_PHRASING,
                        api_key="bad-key",
                    )

    @pytest.mark.asyncio
    async def test_chat_completion_403_raises_auth_error(self) -> None:
        """HTTP 403 response raises ArenaAuthError."""
        with respx.mock:
            respx.post(OPENROUTER_API_URL).mock(
                return_value=httpx.Response(403, json={"error": "Forbidden"})
            )
            async with httpx.AsyncClient() as client:
                with pytest.raises(ArenaAuthError):
                    await _openrouter.chat_completion(
                        client=client,
                        model=_TEST_MODEL,
                        system_prompt="Svar på dansk.",
                        user_message=_TEST_PHRASING,
                        api_key="bad-key",
                    )

    @pytest.mark.asyncio
    async def test_chat_completion_500_raises_collection_error(self) -> None:
        """HTTP 500 response raises ArenaCollectionError."""
        with respx.mock:
            respx.post(OPENROUTER_API_URL).mock(
                return_value=httpx.Response(500, text="Internal Server Error")
            )
            async with httpx.AsyncClient() as client:
                with pytest.raises(ArenaCollectionError):
                    await _openrouter.chat_completion(
                        client=client,
                        model=_TEST_MODEL,
                        system_prompt="Svar på dansk.",
                        user_message=_TEST_PHRASING,
                        api_key="test-key",
                    )


# ===========================================================================
# Tests: _query_expander._parse_phrasings() and expand_term()
# ===========================================================================


class TestQueryExpander:
    def test_parse_phrasings_strips_dot_prefix(self) -> None:
        """Lines with '1. ' prefix have the prefix stripped."""
        from issue_observatory.arenas.ai_chat_search._query_expander import _parse_phrasings

        raw = "1. Hvad er CO2 afgiften?\n2. Hvordan fungerer klimaafgiften?\n3. Er CO2-skat fair?"
        result = _parse_phrasings(raw, 5)

        assert result[0] == "Hvad er CO2 afgiften?"
        assert result[1] == "Hvordan fungerer klimaafgiften?"
        assert result[2] == "Er CO2-skat fair?"

    def test_parse_phrasings_strips_parenthesis_prefix(self) -> None:
        """Lines with '1) ' prefix have the prefix stripped."""
        from issue_observatory.arenas.ai_chat_search._query_expander import _parse_phrasings

        raw = "1) Hvad koster CO2?\n2) Hvem betaler CO2-afgiften?\n3) Hvornår stiger afgiften?"
        result = _parse_phrasings(raw, 5)

        assert result[0] == "Hvad koster CO2?"
        assert result[1] == "Hvem betaler CO2-afgiften?"

    def test_parse_phrasings_filters_empty_lines(self) -> None:
        """Empty lines (after stripping) are not included in the result."""
        from issue_observatory.arenas.ai_chat_search._query_expander import _parse_phrasings

        raw = "1. Hvad er CO2 afgiften?\n\n\n2. Hvordan virker det?\n   \n3. Hvornår stiger det?"
        result = _parse_phrasings(raw, 5)

        assert len(result) == 3

    def test_parse_phrasings_respects_n_phrasings_cap(self) -> None:
        """Only the first n_phrasings lines are returned, excess lines discarded."""
        from issue_observatory.arenas.ai_chat_search._query_expander import _parse_phrasings

        raw = "\n".join(f"{i}. Spørgsmål nummer {i}?" for i in range(1, 10))
        result = _parse_phrasings(raw, 3)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_expand_term_returns_list_of_strings(self) -> None:
        """expand_term() returns a non-empty list of string phrasings on success."""
        fixture = _expand_response()

        with respx.mock:
            respx.post(OPENROUTER_API_URL).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            async with httpx.AsyncClient() as client:
                result = await _query_expander.expand_term(
                    client=client,
                    term=_TEST_TERM,
                    n_phrasings=5,
                    api_key="test-key",
                )

        assert isinstance(result, list)
        assert len(result) == 5
        assert all(isinstance(p, str) for p in result)
        # Numbering prefix '1. ' should be stripped
        assert not result[0].startswith("1.")


# ===========================================================================
# Tests: _records.make_response_record()
# ===========================================================================


class TestMakeResponseRecord:
    def _build(
        self,
        text: str = "Svar på dansk.",
        phrasing: str = _TEST_PHRASING,
    ) -> dict[str, Any]:
        """Helper: build a minimal response record for assertions."""
        response = {
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 100},
        }
        citations = [
            {"url": "https://dr.dk/article", "title": "Artikel", "snippet": "Tekst"}
        ]
        return make_response_record(
            phrasing=phrasing,
            original_term=_TEST_TERM,
            response=response,
            model_used=_TEST_MODEL,
            citations=citations,
            day_bucket=_TEST_DAY_BUCKET,
        )

    def test_make_response_record_content_type(self) -> None:
        """make_response_record() sets content_type='ai_chat_response'."""
        record = self._build()
        assert record["content_type"] == "ai_chat_response"

    def test_make_response_record_language_is_da(self) -> None:
        """make_response_record() sets language='da'."""
        record = self._build()
        assert record["language"] == "da"

    def test_make_response_record_platform_is_openrouter(self) -> None:
        """make_response_record() sets platform='openrouter'."""
        record = self._build()
        assert record["platform"] == "openrouter"

    def test_make_response_record_arena_is_ai_chat_search(self) -> None:
        """make_response_record() sets arena='ai_chat_search'."""
        record = self._build()
        assert record["arena"] == "ai_chat_search"

    def test_make_response_record_author_platform_id_equals_model(self) -> None:
        """make_response_record() sets author_platform_id to the model name."""
        record = self._build()
        assert record["author_platform_id"] == _TEST_MODEL

    def test_make_response_record_platform_id_is_64_char_hex(self) -> None:
        """make_response_record() platform_id is a 64-character lowercase hex string."""
        record = self._build()
        pid = record["platform_id"]
        assert len(pid) == 64
        assert all(c in "0123456789abcdef" for c in pid)

    def test_make_response_record_content_hash_is_64_char_hex(self) -> None:
        """make_response_record() content_hash is a 64-character lowercase hex string."""
        record = self._build()
        ch = record["content_hash"]
        assert len(ch) == 64
        assert all(c in "0123456789abcdef" for c in ch)

    def test_make_response_record_raw_metadata_keys(self) -> None:
        """make_response_record() raw_metadata contains all required keys."""
        record = self._build()
        meta = record["raw_metadata"]
        for key in (
            "query_phrasing",
            "search_term_original",
            "model_used",
            "citations",
            "tokens_used",
            "temperature",
            "search_engine_underlying",
        ):
            assert key in meta, f"Missing key in raw_metadata: {key}"

    def test_make_response_record_raw_metadata_temperature_is_zero(self) -> None:
        """make_response_record() raw_metadata.temperature is 0 (reproducible)."""
        record = self._build()
        assert record["raw_metadata"]["temperature"] == 0

    def test_make_response_record_raw_metadata_search_engine_is_perplexity(self) -> None:
        """make_response_record() raw_metadata.search_engine_underlying is 'perplexity'."""
        record = self._build()
        assert record["raw_metadata"]["search_engine_underlying"] == "perplexity"

    def test_make_response_record_platform_id_is_deterministic(self) -> None:
        """make_response_record() platform_id is stable: same inputs produce same ID."""
        record_a = self._build()
        record_b = self._build()
        assert record_a["platform_id"] == record_b["platform_id"]

    @pytest.mark.parametrize(
        "text",
        [
            "CO2 afgift æøå er vigtig for klimaet",
            "Grønland er verdens største ø",
            "Sønderjylland og Ålborg har særlige forhold",
        ],
    )
    def test_make_response_record_preserves_danish_characters(self, text: str) -> None:
        """Danish characters æ, ø, å in text_content survive make_response_record()."""
        record = self._build(text=text)
        assert record["text_content"] == text


# ===========================================================================
# Tests: _records.make_citation_record()
# ===========================================================================


class TestMakeCitationRecord:
    def _build_format_a_citation(self) -> dict[str, Any]:
        """Return a Format A citation (no title or snippet)."""
        return {"url": "https://dr.dk/nyheder/klimaafgift", "title": None, "snippet": None}

    def _build_format_b_citation(self) -> dict[str, Any]:
        """Return a Format B citation (with title and snippet)."""
        return {
            "url": "https://www.berlingske.dk/business/co2-stiger",
            "title": "CO2-afgiften stiger markant",
            "snippet": "Afgiften øges gradvist frem mod 2030 for at nå klimamålene.",
        }

    def test_make_citation_record_content_type(self) -> None:
        """make_citation_record() sets content_type='ai_chat_citation'."""
        record = make_citation_record(
            citation=self._build_format_a_citation(),
            phrasing=_TEST_PHRASING,
            original_term=_TEST_TERM,
            model_used=_TEST_MODEL,
            rank=1,
            parent_platform_id=_TEST_PARENT_ID,
            day_bucket=_TEST_DAY_BUCKET,
        )
        assert record["content_type"] == "ai_chat_citation"

    def test_make_citation_record_arena_is_ai_chat_search(self) -> None:
        """make_citation_record() sets arena='ai_chat_search'."""
        record = make_citation_record(
            citation=self._build_format_a_citation(),
            phrasing=_TEST_PHRASING,
            original_term=_TEST_TERM,
            model_used=_TEST_MODEL,
            rank=1,
            parent_platform_id=_TEST_PARENT_ID,
            day_bucket=_TEST_DAY_BUCKET,
        )
        assert record["arena"] == "ai_chat_search"

    def test_make_citation_record_platform_is_extracted_domain(self) -> None:
        """make_citation_record() sets platform to the URL's netloc (e.g. 'dr.dk')."""
        record = make_citation_record(
            citation={"url": "https://dr.dk/nyheder/klimaafgift", "title": None, "snippet": None},
            phrasing=_TEST_PHRASING,
            original_term=_TEST_TERM,
            model_used=_TEST_MODEL,
            rank=1,
            parent_platform_id=_TEST_PARENT_ID,
            day_bucket=_TEST_DAY_BUCKET,
        )
        assert record["platform"] == "dr.dk"

    def test_make_citation_record_url_equals_full_citation_url(self) -> None:
        """make_citation_record() sets url to the complete citation URL."""
        citation = self._build_format_b_citation()
        record = make_citation_record(
            citation=citation,
            phrasing=_TEST_PHRASING,
            original_term=_TEST_TERM,
            model_used=_TEST_MODEL,
            rank=1,
            parent_platform_id=_TEST_PARENT_ID,
            day_bucket=_TEST_DAY_BUCKET,
        )
        assert record["url"] == "https://www.berlingske.dk/business/co2-stiger"

    def test_make_citation_record_platform_id_is_64_char_hex(self) -> None:
        """make_citation_record() platform_id is a 64-character lowercase hex string."""
        record = make_citation_record(
            citation=self._build_format_a_citation(),
            phrasing=_TEST_PHRASING,
            original_term=_TEST_TERM,
            model_used=_TEST_MODEL,
            rank=1,
            parent_platform_id=_TEST_PARENT_ID,
            day_bucket=_TEST_DAY_BUCKET,
        )
        pid = record["platform_id"]
        assert len(pid) == 64
        assert all(c in "0123456789abcdef" for c in pid)

    def test_make_citation_record_content_hash_is_sha256_of_url(self) -> None:
        """make_citation_record() content_hash is SHA-256 of the citation URL."""
        import hashlib

        url = "https://dr.dk/nyheder/klimaafgift"
        record = make_citation_record(
            citation={"url": url, "title": None, "snippet": None},
            phrasing=_TEST_PHRASING,
            original_term=_TEST_TERM,
            model_used=_TEST_MODEL,
            rank=1,
            parent_platform_id=_TEST_PARENT_ID,
            day_bucket=_TEST_DAY_BUCKET,
        )
        expected_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
        assert record["content_hash"] == expected_hash

    def test_make_citation_record_text_content_equals_snippet_format_b(self) -> None:
        """make_citation_record() sets text_content to snippet when snippet is present."""
        citation = self._build_format_b_citation()
        record = make_citation_record(
            citation=citation,
            phrasing=_TEST_PHRASING,
            original_term=_TEST_TERM,
            model_used=_TEST_MODEL,
            rank=1,
            parent_platform_id=_TEST_PARENT_ID,
            day_bucket=_TEST_DAY_BUCKET,
        )
        assert record["text_content"] == citation["snippet"]

    def test_make_citation_record_text_content_is_none_format_a(self) -> None:
        """make_citation_record() sets text_content to None when snippet is absent (Format A)."""
        record = make_citation_record(
            citation=self._build_format_a_citation(),
            phrasing=_TEST_PHRASING,
            original_term=_TEST_TERM,
            model_used=_TEST_MODEL,
            rank=1,
            parent_platform_id=_TEST_PARENT_ID,
            day_bucket=_TEST_DAY_BUCKET,
        )
        assert record["text_content"] is None

    def test_make_citation_record_title_preserved_format_b(self) -> None:
        """make_citation_record() preserves citation title when present."""
        citation = self._build_format_b_citation()
        record = make_citation_record(
            citation=citation,
            phrasing=_TEST_PHRASING,
            original_term=_TEST_TERM,
            model_used=_TEST_MODEL,
            rank=1,
            parent_platform_id=_TEST_PARENT_ID,
            day_bucket=_TEST_DAY_BUCKET,
        )
        assert record["title"] == "CO2-afgiften stiger markant"

    def test_make_citation_record_title_is_none_format_a(self) -> None:
        """make_citation_record() sets title to None when citation has no title."""
        record = make_citation_record(
            citation=self._build_format_a_citation(),
            phrasing=_TEST_PHRASING,
            original_term=_TEST_TERM,
            model_used=_TEST_MODEL,
            rank=1,
            parent_platform_id=_TEST_PARENT_ID,
            day_bucket=_TEST_DAY_BUCKET,
        )
        assert record["title"] is None

    def test_make_citation_record_platform_with_www_subdomain(self) -> None:
        """make_citation_record() extracts netloc including www. as the platform value."""
        record = make_citation_record(
            citation={
                "url": "https://www.berlingske.dk/business/co2",
                "title": None,
                "snippet": None,
            },
            phrasing=_TEST_PHRASING,
            original_term=_TEST_TERM,
            model_used=_TEST_MODEL,
            rank=2,
            parent_platform_id=_TEST_PARENT_ID,
            day_bucket=_TEST_DAY_BUCKET,
        )
        assert record["platform"] == "www.berlingske.dk"


# ===========================================================================
# Tests: AiChatSearchCollector — class-level properties and tier config
# ===========================================================================


class TestAiChatSearchCollectorClass:
    def test_free_tier_not_in_supported_tiers(self) -> None:
        """Tier.FREE is not listed in AiChatSearchCollector.supported_tiers."""
        assert Tier.FREE not in AiChatSearchCollector.supported_tiers

    def test_medium_tier_in_supported_tiers(self) -> None:
        """Tier.MEDIUM is in AiChatSearchCollector.supported_tiers."""
        assert Tier.MEDIUM in AiChatSearchCollector.supported_tiers

    def test_premium_tier_in_supported_tiers(self) -> None:
        """Tier.PREMIUM is in AiChatSearchCollector.supported_tiers."""
        assert Tier.PREMIUM in AiChatSearchCollector.supported_tiers

    @pytest.mark.asyncio
    async def test_collect_by_actors_raises_not_implemented(self) -> None:
        """collect_by_actors() raises NotImplementedError for all inputs."""
        collector = AiChatSearchCollector()

        with pytest.raises(NotImplementedError):
            await collector.collect_by_actors(
                actor_ids=["some-actor"], tier=Tier.MEDIUM
            )

    def test_get_tier_config_medium_requires_credential(self) -> None:
        """get_tier_config(MEDIUM) returns a TierConfig with requires_credential=True."""
        collector = AiChatSearchCollector()
        config = collector.get_tier_config(Tier.MEDIUM)
        assert config.requires_credential is True

    def test_get_tier_config_premium_requires_credential(self) -> None:
        """get_tier_config(PREMIUM) returns a TierConfig with requires_credential=True."""
        collector = AiChatSearchCollector()
        config = collector.get_tier_config(Tier.PREMIUM)
        assert config.requires_credential is True

    def test_get_tier_config_free_raises_value_error(self) -> None:
        """get_tier_config(FREE) raises ValueError because FREE is not a valid tier."""
        collector = AiChatSearchCollector()
        with pytest.raises(ValueError):
            collector.get_tier_config(Tier.FREE)

    @pytest.mark.asyncio
    async def test_collect_by_terms_free_tier_returns_empty_list(
        self, caplog: Any
    ) -> None:
        """collect_by_terms() with Tier.FREE returns [] and logs a WARNING."""
        collector = AiChatSearchCollector()

        with caplog.at_level(
            logging.WARNING,
            logger="issue_observatory.arenas.ai_chat_search.collector",
        ):
            result = await collector.collect_by_terms(
                terms=["klimapolitik"], tier=Tier.FREE
            )

        assert result == []
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warning_records) >= 1
        assert any("FREE" in r.message or "free" in r.message for r in warning_records)


# ===========================================================================
# Tests: collect_by_terms() — integration with mocked HTTP
# ===========================================================================


class TestCollectByTermsIntegration:
    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_returns_response_and_citation_records(
        self,
    ) -> None:
        """MEDIUM: successful call returns both ai_chat_response and ai_chat_citation records."""
        expand_fixture = _expand_response()
        chat_fixture = _format_a_response()
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(OPENROUTER_API_URL).mock(
                side_effect=[
                    # First call: expansion (5 times, once per phrasing requested)
                    httpx.Response(200, json=expand_fixture),
                    # Subsequent calls: one chat completion per phrasing
                    httpx.Response(200, json=chat_fixture),
                    httpx.Response(200, json=chat_fixture),
                    httpx.Response(200, json=chat_fixture),
                    httpx.Response(200, json=chat_fixture),
                    httpx.Response(200, json=chat_fixture),
                ]
            )
            async with httpx.AsyncClient() as client:
                collector = AiChatSearchCollector(
                    credential_pool=pool, http_client=client
                )
                records = await collector.collect_by_terms(
                    terms=[_TEST_TERM], tier=Tier.MEDIUM
                )

        content_types = {r["content_type"] for r in records}
        assert "ai_chat_response" in content_types
        assert "ai_chat_citation" in content_types

    @pytest.mark.asyncio
    async def test_collect_by_terms_medium_response_records_have_correct_fields(
        self,
    ) -> None:
        """MEDIUM: ai_chat_response records have platform='openrouter', language='da'."""
        expand_fixture = _expand_response()
        chat_fixture = _format_a_response()
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(OPENROUTER_API_URL).mock(
                side_effect=[
                    httpx.Response(200, json=expand_fixture),
                    httpx.Response(200, json=chat_fixture),
                    httpx.Response(200, json=chat_fixture),
                    httpx.Response(200, json=chat_fixture),
                    httpx.Response(200, json=chat_fixture),
                    httpx.Response(200, json=chat_fixture),
                ]
            )
            async with httpx.AsyncClient() as client:
                collector = AiChatSearchCollector(
                    credential_pool=pool, http_client=client
                )
                records = await collector.collect_by_terms(
                    terms=[_TEST_TERM], tier=Tier.MEDIUM
                )

        response_records = [r for r in records if r["content_type"] == "ai_chat_response"]
        assert len(response_records) > 0
        for rec in response_records:
            assert rec["platform"] == "openrouter"
            assert rec["language"] == "da"
            assert rec["arena"] == "ai_chat_search"

    @pytest.mark.asyncio
    async def test_collect_by_terms_premium_format_b_citation_has_snippet(
        self,
    ) -> None:
        """PREMIUM with Format B: ai_chat_citation records have snippet in text_content."""
        expand_fixture = _expand_response()
        # Use a response with only 1 phrasing for simplicity in this test
        single_phrasing_expand = {
            **expand_fixture,
            "choices": [
                {
                    "message": {
                        "content": "1. Hvad er Grønlands politiske status?"
                    }
                }
            ],
        }
        chat_fixture = _format_b_response()
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(OPENROUTER_API_URL).mock(
                side_effect=[
                    httpx.Response(200, json=single_phrasing_expand),
                    httpx.Response(200, json=chat_fixture),
                    httpx.Response(200, json=chat_fixture),
                    httpx.Response(200, json=chat_fixture),
                    httpx.Response(200, json=chat_fixture),
                    httpx.Response(200, json=chat_fixture),
                    httpx.Response(200, json=chat_fixture),
                    httpx.Response(200, json=chat_fixture),
                    httpx.Response(200, json=chat_fixture),
                    httpx.Response(200, json=chat_fixture),
                    httpx.Response(200, json=chat_fixture),
                ]
            )
            async with httpx.AsyncClient() as client:
                collector = AiChatSearchCollector(
                    credential_pool=pool, http_client=client
                )
                records = await collector.collect_by_terms(
                    terms=["Grønland"], tier=Tier.PREMIUM
                )

        citation_records = [r for r in records if r["content_type"] == "ai_chat_citation"]
        assert len(citation_records) > 0
        # At least one citation should have a non-None snippet (Format B provides them)
        snippets = [r["text_content"] for r in citation_records]
        assert any(s is not None for s in snippets)

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_429_raises_rate_limit_error(self) -> None:
        """collect_by_terms() propagates ArenaRateLimitError from the chat call."""
        expand_fixture = _expand_response()
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(OPENROUTER_API_URL).mock(
                side_effect=[
                    httpx.Response(200, json=expand_fixture),
                    httpx.Response(429, headers={"Retry-After": "60"}),
                ]
            )
            async with httpx.AsyncClient() as client:
                collector = AiChatSearchCollector(
                    credential_pool=pool, http_client=client
                )
                with pytest.raises(ArenaRateLimitError):
                    await collector.collect_by_terms(
                        terms=[_TEST_TERM], tier=Tier.MEDIUM
                    )

    @pytest.mark.asyncio
    async def test_collect_by_terms_http_401_raises_auth_error(self) -> None:
        """collect_by_terms() propagates ArenaAuthError from the chat call."""
        expand_fixture = _expand_response()
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(OPENROUTER_API_URL).mock(
                side_effect=[
                    httpx.Response(200, json=expand_fixture),
                    httpx.Response(401, json={"error": "Unauthorized"}),
                ]
            )
            async with httpx.AsyncClient() as client:
                collector = AiChatSearchCollector(
                    credential_pool=pool, http_client=client
                )
                with pytest.raises(ArenaAuthError):
                    await collector.collect_by_terms(
                        terms=[_TEST_TERM], tier=Tier.MEDIUM
                    )

    @pytest.mark.asyncio
    async def test_collect_by_terms_all_blank_phrasings_returns_empty_list(
        self,
    ) -> None:
        """Expansion returning only blank lines produces [] with no exception."""
        blank_expand = {
            "choices": [{"message": {"content": "\n\n\n"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        }
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(OPENROUTER_API_URL).mock(
                return_value=httpx.Response(200, json=blank_expand)
            )
            async with httpx.AsyncClient() as client:
                collector = AiChatSearchCollector(
                    credential_pool=pool, http_client=client
                )
                result = await collector.collect_by_terms(
                    terms=[_TEST_TERM], tier=Tier.MEDIUM
                )

        assert result == []

    @pytest.mark.asyncio
    async def test_collect_by_terms_empty_citations_only_response_records(
        self,
    ) -> None:
        """A chat response with no citations produces only ai_chat_response records."""
        expand_fixture = _expand_response()
        no_citation_response = {
            "id": "gen-nocite",
            "model": "perplexity/sonar",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Svar uden citationer.",
                    }
                }
            ],
            "citations": [],
            "usage": {"prompt_tokens": 40, "completion_tokens": 10},
        }
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(OPENROUTER_API_URL).mock(
                side_effect=[
                    httpx.Response(200, json=expand_fixture),
                    httpx.Response(200, json=no_citation_response),
                    httpx.Response(200, json=no_citation_response),
                    httpx.Response(200, json=no_citation_response),
                    httpx.Response(200, json=no_citation_response),
                    httpx.Response(200, json=no_citation_response),
                ]
            )
            async with httpx.AsyncClient() as client:
                collector = AiChatSearchCollector(
                    credential_pool=pool, http_client=client
                )
                records = await collector.collect_by_terms(
                    terms=[_TEST_TERM], tier=Tier.MEDIUM
                )

        content_types = {r["content_type"] for r in records}
        assert "ai_chat_response" in content_types
        assert "ai_chat_citation" not in content_types

    @pytest.mark.asyncio
    async def test_collect_by_terms_no_credential_raises_error(
        self, monkeypatch: Any
    ) -> None:
        """collect_by_terms() without credential pool and no env var raises an error."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        collector = AiChatSearchCollector(credential_pool=None)

        with pytest.raises(Exception):
            await collector.collect_by_terms(terms=[_TEST_TERM], tier=Tier.MEDIUM)


# ===========================================================================
# Tests: health_check()
# ===========================================================================


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_ok_on_successful_expansion(self) -> None:
        """health_check() returns status='ok' when expansion call succeeds."""
        fixture = _expand_response()
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(OPENROUTER_API_URL).mock(
                return_value=httpx.Response(200, json=fixture)
            )
            collector = AiChatSearchCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "ok"
        assert result["arena"] == "ai_chat_search"
        assert result["platform"] == "openrouter"
        assert "checked_at" in result
        assert "detail" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_http_401(self) -> None:
        """health_check() returns status='down' when the expansion call receives HTTP 401."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(OPENROUTER_API_URL).mock(
                return_value=httpx.Response(401, json={"error": "Unauthorized"})
            )
            collector = AiChatSearchCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "down"
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_no_credential(
        self, monkeypatch: Any
    ) -> None:
        """health_check() returns status='down' when no credential is available."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        collector = AiChatSearchCollector(credential_pool=None)

        result = await collector.health_check()

        assert result["status"] == "down"
        assert "checked_at" in result
        assert "No credential" in result.get("detail", "")

    @pytest.mark.asyncio
    async def test_health_check_includes_arena_and_platform_fields(
        self, monkeypatch: Any
    ) -> None:
        """health_check() always includes arena and platform fields regardless of outcome."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        collector = AiChatSearchCollector(credential_pool=None)
        result = await collector.health_check()

        assert "arena" in result
        assert "platform" in result
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_down_on_http_500(self) -> None:
        """health_check() returns status='down' when the expansion call receives HTTP 500."""
        pool = _make_mock_pool()

        with respx.mock:
            respx.post(OPENROUTER_API_URL).mock(
                return_value=httpx.Response(500, text="Internal Server Error")
            )
            collector = AiChatSearchCollector(credential_pool=pool)
            result = await collector.health_check()

        assert result["status"] == "down"
